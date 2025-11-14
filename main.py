import requests
from fastapi import FastAPI
import boto3
from botocore.client import Config
from pydantic import BaseModel
import uuid
import os

app = FastAPI()

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")

s3 = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    config=Config(signature_version='s3v4')
)

class VideoRequest(BaseModel):
    file_id: str

def get_file_path(file_id):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getFile?file_id={file_id}"
    res = requests.get(url).json()
    return res["result"]["file_path"]

def download_from_telegram(file_path):
    url = f"https://api.telegram.org/file/bot{TG_BOT_TOKEN}/{file_path}"
    return requests.get(url, stream=True)

def upload_to_r2(file_bytes, filename):
    s3.upload_fileobj(file_bytes, R2_BUCKET, filename)
    return f"{R2_ENDPOINT}/{R2_BUCKET}/{filename}"

@app.post("/upload")
async def upload_video(req: VideoRequest):
    file_path = get_file_path(req.file_id)
    response = download_from_telegram(file_path)

    if response.status_code != 200:
        return {"error": "cannot download file"}

    filename = f"{uuid.uuid4()}.mp4"
    file_url = upload_to_r2(response.raw, filename)

    return {
        "status": "ok",
        "file_url": file_url
    }
