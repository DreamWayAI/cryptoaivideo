import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
import uuid
import os
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Проверка переменных окружения
S3_ENDPOINT = os.getenv("S3_ENDPOINT")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")

logger.info(f"S3_ENDPOINT: {S3_ENDPOINT}")
logger.info(f"S3_BUCKET: {S3_BUCKET}")
logger.info(f"S3_ACCESS_KEY: {'***' if S3_ACCESS_KEY else 'NOT SET'}")
logger.info(f"S3_SECRET_KEY: {'***' if S3_SECRET_KEY else 'NOT SET'}")

if not all([S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY]):
    logger.error("Не все переменные окружения настроены!")
    logger.warning("Приложение запустится, но /upload не будет работать!")
    s3 = None
else:
    # Инициализация S3 клиента
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            config=Config(signature_version='s3v4')
        )
        logger.info("✅ S3 клиент успешно инициализирован")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации S3: {e}")
        s3 = None

class UploadRequest(BaseModel):
    file_url: str

@app.get("/")
async def root():
    """Проверка работы сервера"""
    return {
        "status": "ok", 
        "message": "FastAPI сервер работает",
        "s3_configured": s3 is not None
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "s3_status": "configured" if s3 else "not configured"
    }

@app.post("/upload")
async def upload_video(req: UploadRequest):
    """
    Загружает файл из Telegram в S3
    """
    if not s3:
        raise HTTPException(
            status_code=500,
            detail="S3 не настроен. Проверьте переменные окружения."
        )
    
    logger.info(f"📥 Получен запрос на загрузку: {req.file_url}")
    
    try:
        # Скачиваем файл из Telegram
        logger.info("⏬ Начинаю загрузку файла из Telegram...")
        response = requests.get(req.file_url, stream=True, timeout=60)
        
        if response.status_code != 200:
            logger.error(f"❌ Ошибка загрузки из Telegram: {response.status_code}")
            raise HTTPException(
                status_code=400, 
                detail=f"Не удалось скачать файл из Telegram. Статус: {response.status_code}"
            )
        
        # Генерируем уникальное имя файла
        filename = f"{uuid.uuid4()}.mp4"
        logger.info(f"📝 Генерирую имя файла: {filename}")
        
        # Загружаем в S3
        logger.info(f"☁️ Начинаю загрузку в S3 bucket: {S3_BUCKET}")
        s3.upload_fileobj(
            response.raw, 
            S3_BUCKET,
            filename,
            ExtraArgs={'ContentType': 'video/mp4'}
        )
        logger.info("✅ Файл успешно загружен в S3")
        
        # Генерируем presigned URL (рекомендуется для AWS S3)
        try:
            presigned_url = s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': S3_BUCKET, 'Key': filename},
                ExpiresIn=3600 * 24 * 7  # 7 дней
            )
            logger.info(f"🔗 Файл доступен по presigned URL")
            file_url = presigned_url
        except Exception as e:
            logger.warning(f"⚠️ Не удалось создать presigned URL: {e}")
            file_url = f"{S3_ENDPOINT}/{filename}"
        
        return {
            "status": "ok",
            "filename": filename,
            "file_url": file_url,
            "bucket": S3_BUCKET
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Ошибка при загрузке из Telegram: {e}")
        raise HTTPException(
            status_code=400, 
            detail=f"Ошибка загрузки из Telegram: {str(e)}"
        )
    
    except ClientError as e:
        logger.error(f"❌ Ошибка S3: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Ошибка при загрузке в S3: {str(e)}"
        )
    
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )

@app.get("/test-s3")
async def test_s3():
    """Тестирование подключения к S3"""
    if not s3:
        raise HTTPException(
            status_code=500,
            detail="S3 не настроен. Проверьте переменные окружения."
        )
    
    try:
        # Пробуем получить список объектов в bucket
        response = s3.list_objects_v2(Bucket=S3_BUCKET, MaxKeys=1)
        return {
            "status": "ok",
            "message": "✅ S3 подключение работает",
            "bucket": S3_BUCKET,
            "endpoint": S3_ENDPOINT,
            "objects_count": response.get('KeyCount', 0)
        }
    except ClientError as e:
        logger.error(f"❌ Ошибка S3: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Ошибка подключения к S3: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
