import os
import requests
import boto3
from fastapi import FastAPI, Query
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()
@app.get("/")
def root():
    return {"status": "ok"}


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION")
S3_ENDPOINT = os.getenv("S3_ENDPOINT")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
)

@app.get("/upload")
def upload(file_id: str, file_name: str):
    r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}")
    r.raise_for_status()
    file_path = r.json()["result"]["file_path"]

    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    response = requests.get(file_url, stream=True)
    response.raise_for_status()

    s3.upload_fileobj(response.raw, S3_BUCKET, file_name)

    s3_url = f"{S3_ENDPOINT}/{S3_BUCKET}/{file_name}"
    return {"status": "ok", "s3_url": s3_url}
