import os
import hashlib
from datetime import datetime, timedelta
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION", "auto")
S3_ENDPOINT = os.getenv("S3_ENDPOINT")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "2147483648"))  # 2GB default
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1048576"))  # 1MB chunks

# Initialize FastAPI
app = FastAPI(title="Video Upload Server", version="1.0")

# Initialize S3 client if credentials are provided
s3_client = None
if S3_ACCESS_KEY and S3_SECRET_KEY:
    s3_client = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION
    )

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
    expires_in: int = Field(default=3600, le=7200)
    user_id: str

# Utility functions
def generate_s3_key(user_id: str, file_name: str, prefix: str = "uploads") -> str:
    """Generate unique S3 key for file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_hash = hashlib.md5(f"{user_id}_{timestamp}".encode()).hexdigest()[:8]
    return f"{prefix}/{user_id}/{timestamp}_{file_hash}_{file_name}"

# Main endpoints
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Video Upload Server",
        "version": "1.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "s3": "connected" if s3_client else "not configured"
        }
    }

@app.post("/generate-upload-url")
async def generate_upload_url(request: PresignedUrlRequest):
    """Generate presigned URL for direct upload to S3"""
    if not s3_client:
        raise HTTPException(status_code=503, detail="S3 not configured")
    
    try:
        s3_key = generate_s3_key(request.user_id, request.file_name)
        
        # Generate presigned PUT URL
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': S3_BUCKET,
                'Key': s3_key,
                'ContentType': request.file_type
            },
            ExpiresIn=request.expires_in
        )
        
        return {
            "upload_url": presigned_url,
            "s3_key": s3_key,
            "expires_at": (datetime.now() + timedelta(seconds=request.expires_in)).isoformat(),
            "max_file_size": MAX_FILE_SIZE,
            "final_url": f"{S3_ENDPOINT}/{S3_BUCKET}/{s3_key}" if S3_ENDPOINT else f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
        }
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {str(e)}")

@app.post("/upload-telegram-file")
async def upload_telegram_file(request: UploadRequest):
    """Handle Telegram file upload with streaming to S3"""
    if not TELEGRAM_TOKEN:
        raise HTTPException(status_code=503, detail="Telegram not configured")
    
    if not s3_client:
        raise HTTPException(status_code=503, detail="S3 not configured")
    
    # Check file size limitations
    if request.file_size and request.file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE / (1024**3):.2f} GB"
        )
    
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            # Get file info from Telegram
            file_info_response = await client.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile",
                params={"file_id": request.file_id}
            )
            file_info_response.raise_for_status()
            file_data = file_info_response.json()
            
            if not file_data.get("ok"):
                raise HTTPException(status_code=400, detail="Failed to get file info from Telegram")
            
            file_path = file_data["result"]["file_path"]
            
            # Generate S3 key
            s3_key = generate_s3_key(request.user_id, request.file_name)
            
            # Download from Telegram and upload to S3
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
            
            # For smaller files, simple upload
            if not request.file_size or request.file_size < 50 * 1024 * 1024:  # < 50MB
                async with client.stream('GET', file_url) as response:
                    response.raise_for_status()
                    content = await response.aread()
                    
                s3_client.put_object(
                    Bucket=S3_BUCKET,
                    Key=s3_key,
                    Body=content,
                    ContentType='video/mp4'
                )
            else:
                # For larger files, use multipart upload
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
                        
                        # Upload part when buffer reaches 5MB
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
            
            final_url = f"{S3_ENDPOINT}/{S3_BUCKET}/{s3_key}" if S3_ENDPOINT else f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
            
            return {
                "status": "completed",
                "s3_url": final_url,
                "s3_key": s3_key,
                "message": "File uploaded successfully"
            }
            
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Failed to download from Telegram: {str(e)}")
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload to S3: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/simple-upload")
async def simple_upload(
    file: UploadFile = File(...),
    user_id: str = Form(...)
):
    """Simple file upload endpoint for testing"""
    if not s3_client:
        raise HTTPException(status_code=503, detail="S3 not configured")
    
    try:
        # Generate S3 key
        s3_key = generate_s3_key(user_id, file.filename or "upload.mp4")
        
        # Read file content
        content = await file.read()
        
        # Upload to S3
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=content,
            ContentType=file.content_type or 'video/mp4'
        )
        
        final_url = f"{S3_ENDPOINT}/{S3_BUCKET}/{s3_key}" if S3_ENDPOINT else f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
        
        return {
            "status": "success",
            "s3_url": final_url,
            "s3_key": s3_key,
            "file_size": len(content)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
