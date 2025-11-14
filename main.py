from fastapi import FastAPI, Request
from dotenv import load_dotenv
import requests
import boto3
from io import BytesIO
import os

load_dotenv()

app = FastAPI()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")


@app.get("/")
def root():
    return {"status": "ok"}


@app.post("/upload")
async def upload(request: Request):
    try:
        data = await request.json()
        file_id = data.get("file_id")
        if not file_id:
            return {"error": "file_id is missing"}

        # 1. Отримати шлях до файлу з Telegram
        get_file_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}"
        file_info = requests.get(get_file_url).json()
        file_path = file_info["result"]["file_path"]

        # 2. Завантажити файл з Telegram
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        file_content = requests.get(file_url).content
        file_name = file_path.split("/")[-1]

        # 3. Завантажити файл у S3 (Cloudflare R2)
        s3 = boto3.client("s3",
            region_name=S3_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )
        s3.upload_fileobj(BytesIO(file_content), Bucket=S3_BUCKET, Key=file_name)

        # 4. Повернути посилання на файл
        s3_url = f"https://{S3_BUCKET}.{S3_REGION}.amazonaws.com/{file_name}"
        return {"s3_url": s3_url}

    except Exception as e:
        return {"error": str(e)}
