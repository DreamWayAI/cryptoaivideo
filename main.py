from fastapi import FastAPI
import requests
import boto3
import uuid
import os

app = FastAPI()

# настройки S3 / R2
S3_ENDPOINT = os.getenv("S3_ENDPOINT")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_ACCESS = os.getenv("S3_ACCESS")
S3_SECRET = os.getenv("S3_SECRET")

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS,
    aws_secret_access_key=S3_SECRET
)

@app.post("/upload")
async def upload_video(payload: dict):
    file_url = payload["file_url"]

    # генерация имени файла
    filename = f"{uuid.uuid4()}.mp4"

    # скачиваем видео из Telegram
    response = requests.get(file_url, stream=True)

    if response.status_code != 200:
        return {"error": "cannot download file"}

    # сохраняем локально временно
    temp_path = f"/tmp/{filename}"

    with open(temp_path, "wb") as f:
        for chunk in response.iter_content(1024 * 1024):
            f.write(chunk)

    # загрузка в S3
    s3.upload_file(temp_path, S3_BUCKET, filename)

    # удаляем временный файл
    os.remove(temp_path)

    # публичная ссылка
    file_link = f"{S3_ENDPOINT}/{S3_BUCKET}/{filename}"

    return {
        "status": "ok",
        "file": file_link
    }
