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

if not all([S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY]):
    logger.error("Не все переменные окружения настроены!")
    raise ValueError("Missing required environment variables")

# Инициализация S3 клиента
try:
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=Config(signature_version='s3v4')
    )
    logger.info("S3 клиент успешно инициализирован")
except Exception as e:
    logger.error(f"Ошибка инициализации S3: {e}")
    raise

class UploadRequest(BaseModel):
    file_url: str

@app.get("/")
async def root():
    """Проверка работы сервера"""
    return {"status": "ok", "message": "FastAPI сервер работает"}

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}

@app.post("/upload")
async def upload_video(req: UploadRequest):
    """
    Загружает файл из Telegram в R2/S3
    """
    logger.info(f"Получен запрос на загрузку: {req.file_url}")
    
    try:
        # Скачиваем файл из Telegram
        logger.info("Начинаю загрузку файла из Telegram...")
        response = requests.get(req.file_url, stream=True, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"Ошибка загрузки из Telegram: {response.status_code}")
            raise HTTPException(
                status_code=400, 
                detail=f"Не удалось скачать файл из Telegram. Статус: {response.status_code}"
            )
        
        # Генерируем уникальное имя файла
        filename = f"{uuid.uuid4()}.mp4"
        logger.info(f"Генерирую имя файла: {filename}")
        
        # Загружаем в R2/S3
        logger.info(f"Начинаю загрузку в S3 bucket: {S3_BUCKET}")
        s3.upload_fileobj(
            response.raw, 
            R2_BUCKET, 
            filename,
            ExtraArgs={'ContentType': 'video/mp4'}
        )
        logger.info("Файл успешно загружен в S3")
        
        # Формируем публичный URL
        # Для S3 используйте ваш custom domain или S3.dev URL
        public_url = f"{R2_ENDPOINT}/{R2_BUCKET}/{filename}"
        
        # Альтернатива: генерация presigned URL (временная ссылка)
        # presigned_url = s3.generate_presigned_url(
        #     'get_object',
        #     Params={'Bucket': S3_BUCKET, 'Key': filename},
        #     ExpiresIn=3600  # 1 час
        # )
        
        logger.info(f"Файл доступен по URL: {public_url}")
        
        return {
            "status": "ok",
            "filename": filename,
            "file_url": public_url,
            "bucket": S3_BUCKET
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при загрузке из Telegram: {e}")
        raise HTTPException(
            status_code=400, 
            detail=f"Ошибка загрузки из Telegram: {str(e)}"
        )
    
    except ClientError as e:
        logger.error(f"Ошибка S3: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Ошибка при загрузке в S3: {str(e)}"
        )
    
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )

@app.get("/test-s3")
async def test_s3():
    """Тестирование подключения к S3"""
    try:
        # Пробуем получить список объектов в bucket
        response = s3.list_objects_v2(Bucket=S3_BUCKET, MaxKeys=1)
        return {
            "status": "ok",
            "message": "S3 подключение работает",
            "bucket": S3_BUCKET
        }
    except ClientError as e:
        logger.error(f"Ошибка S3: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Ошибка подключения к S3: {str(e)}"
        )
