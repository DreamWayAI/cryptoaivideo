from fastapi import FastAPI, HTTPException
import os
import requests
import boto3
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_ENDPOINT = os.getenv("S3_ENDPOINT")
S3_KEY = os.getenv("S3_KEY")
S3_SECRET = os.getenv("S3_SECRET")

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_KEY,
    aws_secret_access_key=S3_SECRET
)

def tg_get_file_path(file_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
    r = requests.get(url)
    if not r.ok:
        raise HTTPException(status_code=400, detail="Cannot get file path")
    return r.json()["result"]["file_path"]

def tg_stream_download(file_path):
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    return requests.get(url, stream=True)

@app.post("/upload")
def upload_video(payload: dict):
    file_id = payload["file_id"]

    file_path = tg_get_file_path(file_id)
    filename = file_path.split("/")[-1]

    stream = tg_stream_download(file_path)

    s3.upload_fileobj(stream.raw, S3_BUCKET, filename)

    video_url = f"{S3_ENDPOINT}/{S3_BUCKET}/{filename}"

    return {
        "status": "ok",
        "url": video_url
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
