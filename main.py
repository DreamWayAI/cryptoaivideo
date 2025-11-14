import os
import requests
import boto3
from fastapi import FastAPI, Request
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}

@app.post("/upload")
async def upload(request: Request):
    data = await request.json()
    file_id = data.get("file_id")

    # 1. Отримати шлях до файлу
    get_file_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}"
    file_info = requests.get(get_file_url).json()
    file_path = file_info["result"]["file_path"]

    # 2. Скачати файл
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    file_content = requests.get(file_url).content

    # 3. Назва файла
    file_name = file_path.split("/")[-1]

    # 4. Завантажити у S3
    s3 = boto3.client("s3",
        region_name=S3_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )

    s3.upload_fileobj(
        Fileobj=bytes(file_content),
        Bucket=S3_BUCKET,
        Key=file_name
    )

    s3_url = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{file_name}"
    return {"status": "uploaded", "s3_url": s3_url}

