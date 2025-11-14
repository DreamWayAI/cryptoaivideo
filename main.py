import os
import asyncio
import hashlib
import aiofiles
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import httpx
from dotenv import load_dotenv
import redis.asyncio as redis
import json
from contextlib import asynccontextmanager

load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION", "auto")
S3_ENDPOINT = os.getenv("S3_ENDPOINT")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 2 * 1024 * 1024 * 1024))  # 2GB default
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 1024 * 1024))  # 1MB chunks

# Initialize S3 client
s3_client = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    region_name=S3_REGION
)

# Redis for job queue
redis_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    global redis_client
    redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    yield
    await redis_client.close()

app = FastAPI(title="Video Upload Server", version="2.0", lifespan=lifespan)

# Pydantic models
class UploadRequest(BaseModel):
    """Request model for file upload from Telegram"""
    file_id: str
    file_name: str
    user_id: str
    chat_id: str
    file_size: Optional[int] = None

class PresignedUrlRequest(BaseModel):
    """Request model for generating presigned URLs"""
    file_name: str
    file_type: str = "video/mp4"
    expires_in: int = Field(default=3600, le=7200)  # Max 2 hours
    user_id: str

class ProcessingJob(BaseModel):
    """Model for video processing jobs"""
    job_id: str
    status: str
    video_url: str
    user_id: str
    created_at: str
    updated_at: str
    result: Optional[Dict[str, Any]] = None

# Utility functions
def generate_s3_key(user_id: str, file_name: str, prefix: str = "uploads") -> str:
    """Generate unique S3 key for file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_hash = hashlib.md5(f"{user_id}_{timestamp}".encode()).hexdigest()[:8]
    return f"{prefix}/{user_id}/{timestamp}_{file_hash}_{file_name}"

async def notify_telegram(chat_id: str, message: str):
    """Send notification to Telegram chat"""
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
            )
        except Exception as e:
            print(f"Failed to send Telegram notification: {e}")

# Main endpoints
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "s3": "connected",
            "redis": "connected" if redis_client else "disconnected"
        }
    }

@app.post("/generate-upload-url")
async def generate_upload_url(request: PresignedUrlRequest):
    """
    Generate presigned URL for direct upload to S3.
    This bypasses server memory limitations.
    """
    try:
        s3_key = generate_s3_key(request.user_id, request.file_name)
        
        # Generate presigned POST URL for multipart upload
        presigned_post = s3_client.generate_presigned_post(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Fields={
                "Content-Type": request.file_type,
                "x-amz-meta-user-id": request.user_id
            },
            Conditions=[
                {"Content-Type": request.file_type},
                ["content-length-range", 0, MAX_FILE_SIZE]
            ],
            ExpiresIn=request.expires_in
        )
        
        # Also generate a simple PUT URL as alternative
        presigned_put_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': S3_BUCKET,
                'Key': s3_key,
                'ContentType': request.file_type
            },
            ExpiresIn=request.expires_in
        )
        
        return {
            "upload_url": presigned_put_url,
            "multipart_data": presigned_post,
            "s3_key": s3_key,
            "expires_at": (datetime.now() + timedelta(seconds=request.expires_in)).isoformat(),
            "max_file_size": MAX_FILE_SIZE,
            "final_url": f"{S3_ENDPOINT}/{S3_BUCKET}/{s3_key}"
        }
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {str(e)}")

@app.post("/upload-telegram-file")
async def upload_telegram_file(request: UploadRequest, background_tasks: BackgroundTasks):
    """
    Handle Telegram file upload with streaming to S3.
    For files > 50MB, returns immediately and processes in background.
    """
    # Check file size limitations
    if request.file_size and request.file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE / (1024**3):.2f} GB"
        )
    
    # For large files, process in background
    if request.file_size and request.file_size > 50 * 1024 * 1024:  # 50MB
        job_id = hashlib.md5(f"{request.user_id}_{request.file_id}".encode()).hexdigest()
        
        # Add to background tasks
        background_tasks.add_task(
            process_large_file,
            request,
            job_id
        )
        
        # Store job status in Redis
        if redis_client:
            await redis_client.setex(
                f"job:{job_id}",
                3600,  # 1 hour TTL
                json.dumps({
                    "status": "processing",
                    "file_name": request.file_name,
                    "user_id": request.user_id,
                    "created_at": datetime.now().isoformat()
                })
            )
        
        return {
            "status": "processing",
            "job_id": job_id,
            "message": "Large file detected. Processing in background.",
            "check_status_url": f"/status/{job_id}"
        }
    
    # For smaller files, process immediately
    try:
        s3_url = await stream_telegram_to_s3(request)
        return {
            "status": "completed",
            "s3_url": s3_url,
            "message": "File uploaded successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def stream_telegram_to_s3(request: UploadRequest) -> str:
    """
    Stream file from Telegram directly to S3 without loading into memory.
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        # Get file info from Telegram
        file_info_response = await client.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile",
            params={"file_id": request.file_id}
        )
        file_info_response.raise_for_status()
        file_path = file_info_response.json()["result"]["file_path"]
        
        # Generate S3 key
        s3_key = generate_s3_key(request.user_id, request.file_name)
        
        # Stream file from Telegram to S3
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        
        # Use multipart upload for large files
        multipart_upload = s3_client.create_multipart_upload(
            Bucket=S3_BUCKET,
            Key=s3_key,
            ContentType='video/mp4'
        )
        upload_id = multipart_upload['UploadId']
        
        parts = []
        part_number = 1
        
        async with client.stream('GET', file_url) as response:
            response.raise_for_status()
            
            buffer = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=CHUNK_SIZE):
                buffer.extend(chunk)
                
                # Upload part when buffer reaches 5MB (minimum part size)
                if len(buffer) >= 5 * 1024 * 1024:
                    part_response = s3_client.upload_part(
                        Bucket=S3_BUCKET,
                        Key=s3_key,
                        PartNumber=part_number,
                        UploadId=upload_id,
                        Body=bytes(buffer)
                    )
                    parts.append({
                        'PartNumber': part_number,
                        'ETag': part_response['ETag']
                    })
                    part_number += 1
                    buffer = bytearray()
            
            # Upload remaining data
            if buffer:
                part_response = s3_client.upload_part(
                    Bucket=S3_BUCKET,
                    Key=s3_key,
                    PartNumber=part_number,
                    UploadId=upload_id,
                    Body=bytes(buffer)
                )
                parts.append({
                    'PartNumber': part_number,
                    'ETag': part_response['ETag']
                })
        
        # Complete multipart upload
        s3_client.complete_multipart_upload(
            Bucket=S3_BUCKET,
            Key=s3_key,
            UploadId=upload_id,
            MultipartUpload={'Parts': parts}
        )
        
        return f"{S3_ENDPOINT}/{S3_BUCKET}/{s3_key}"

async def process_large_file(request: UploadRequest, job_id: str):
    """
    Background task to process large files.
    """
    try:
        # Notify user that processing started
        await notify_telegram(
            request.chat_id,
            f"⏳ Starting upload of large file: <b>{request.file_name}</b>\nThis may take several minutes..."
        )
        
        # Stream file to S3
        s3_url = await stream_telegram_to_s3(request)
        
        # Update job status in Redis
        if redis_client:
            await redis_client.setex(
                f"job:{job_id}",
                3600,
                json.dumps({
                    "status": "completed",
                    "s3_url": s3_url,
                    "file_name": request.file_name,
                    "user_id": request.user_id,
                    "completed_at": datetime.now().isoformat()
                })
            )
        
        # Notify user of completion
        await notify_telegram(
            request.chat_id,
            f"✅ Upload completed!\n<b>{request.file_name}</b>\n\nFile URL: {s3_url}"
        )
        
    except Exception as e:
        # Update job status with error
        if redis_client:
            await redis_client.setex(
                f"job:{job_id}",
                3600,
                json.dumps({
                    "status": "failed",
                    "error": str(e),
                    "file_name": request.file_name,
                    "user_id": request.user_id,
                    "failed_at": datetime.now().isoformat()
                })
            )
        
        # Notify user of failure
        await notify_telegram(
            request.chat_id,
            f"❌ Upload failed for <b>{request.file_name}</b>\nError: {str(e)}"
        )

@app.get("/status/{job_id}")
async def get_job_status(job_id: str):
    """Check status of background upload job"""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    
    job_data = await redis_client.get(f"job:{job_id}")
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return json.loads(job_data)

@app.post("/multipart-upload")
async def handle_multipart_upload(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    chunk_number: int = Form(0),
    total_chunks: int = Form(1)
):
    """
    Handle chunked file uploads for very large files.
    Client splits file into chunks and uploads sequentially.
    """
    # Generate consistent S3 key based on file name and user
    s3_key = generate_s3_key(user_id, file.filename, prefix="chunks")
    
    # For first chunk, initiate multipart upload
    if chunk_number == 0:
        multipart_upload = s3_client.create_multipart_upload(
            Bucket=S3_BUCKET,
            Key=s3_key,
            ContentType=file.content_type or 'video/mp4'
        )
        upload_id = multipart_upload['UploadId']
        
        # Store upload ID in Redis for subsequent chunks
        if redis_client:
            await redis_client.setex(
                f"upload:{user_id}:{file.filename}",
                7200,  # 2 hour TTL
                upload_id
            )
    else:
        # Retrieve upload ID from Redis
        if redis_client:
            upload_id = await redis_client.get(f"upload:{user_id}:{file.filename}")
            if not upload_id:
                raise HTTPException(status_code=400, detail="Upload session expired or not found")
    
    # Upload chunk
    chunk_data = await file.read()
    part_response = s3_client.upload_part(
        Bucket=S3_BUCKET,
        Key=s3_key,
        PartNumber=chunk_number + 1,
        UploadId=upload_id,
        Body=chunk_data
    )
    
    # Store part info in Redis
    if redis_client:
        part_info = {
            'PartNumber': chunk_number + 1,
            'ETag': part_response['ETag']
        }
        await redis_client.rpush(
            f"parts:{upload_id}",
            json.dumps(part_info)
        )
        await redis_client.expire(f"parts:{upload_id}", 7200)
    
    # If last chunk, complete the upload
    if chunk_number == total_chunks - 1:
        # Retrieve all parts info
        if redis_client:
            parts_data = await redis_client.lrange(f"parts:{upload_id}", 0, -1)
            parts = [json.loads(part) for part in parts_data]
        
        # Complete multipart upload
        s3_client.complete_multipart_upload(
            Bucket=S3_BUCKET,
            Key=s3_key,
            UploadId=upload_id,
            MultipartUpload={'Parts': sorted(parts, key=lambda x: x['PartNumber'])}
        )
        
        # Clean up Redis
        if redis_client:
            await redis_client.delete(f"upload:{user_id}:{file.filename}")
            await redis_client.delete(f"parts:{upload_id}")
        
        return {
            "status": "completed",
            "s3_url": f"{S3_ENDPOINT}/{S3_BUCKET}/{s3_key}",
            "message": "All chunks uploaded successfully"
        }
    
    return {
        "status": "chunk_uploaded",
        "chunk_number": chunk_number,
        "total_chunks": total_chunks,
        "message": f"Chunk {chunk_number + 1}/{total_chunks} uploaded"
    }

@app.post("/initiate-vizard-processing")
async def initiate_vizard_processing(
    s3_url: str = Form(...),
    user_id: str = Form(...),
    chat_id: str = Form(...),
    vizard_settings: str = Form("{}")
):
    """
    Initiate video processing with Vizard.
    This endpoint can be called after successful upload.
    """
    try:
        settings = json.loads(vizard_settings)
        job_id = hashlib.md5(f"{user_id}_{s3_url}_{datetime.now()}".encode()).hexdigest()
        
        # Add to processing queue
        if redis_client:
            await redis_client.rpush(
                "vizard_queue",
                json.dumps({
                    "job_id": job_id,
                    "s3_url": s3_url,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "settings": settings,
                    "created_at": datetime.now().isoformat()
                })
            )
        
        # Notify user
        await notify_telegram(
            chat_id,
            f"🎬 Video processing started!\nJob ID: <code>{job_id}</code>\nYou'll be notified when it's ready."
        )
        
        return {
            "status": "queued",
            "job_id": job_id,
            "message": "Video processing job queued successfully"
        }
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid vizard_settings JSON")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
