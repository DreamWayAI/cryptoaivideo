import requests
from fastapi import FastAPI
from pydantic import BaseModel
import boto3
from botocore.client import Config
import uuid
import os

app = FastAPI()

R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")

s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    config=Config(signature_version='s3v4')
)

class UploadRequest(BaseModel):
    file_url: str

@app.post("/upload")
async def upload_video(req: UploadRequest):

    response = requests.get(req.file_url, stream=True)

    if response.status_code != 200:
        return {"error": "cannot download telegram file"}

    filename = f"{uuid.uuid4()}.mp4"

    s3.upload_fileobj(response.raw, R2_BUCKET, filename)

    public_url = f"{R2_ENDPOINT}/{R2_BUCKET}/{filename}"

    return {
        "status": "ok",
        "file_url": public_url
    }
