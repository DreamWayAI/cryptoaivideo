# 🎬 Telegram Video Upload Server

Высокопроизводительный сервер для обработки больших видео файлов (до 2GB+) через Telegram бота с автоматической загрузкой в S3 и интеграцией с n8n для автоматизации.

## 🚀 Основные улучшения

### ✅ Что решено:
1. **Стриминговая загрузка** - файлы не загружаются в память целиком
2. **Multipart upload** - загрузка частями для больших файлов
3. **Presigned URLs** - прямая загрузка в S3 минуя сервер
4. **Фоновая обработка** - не блокирует сервер при долгих операциях
5. **Redis очереди** - управление задачами и статусами
6. **Уведомления в Telegram** - информирование о прогрессе
7. **Обработка ошибок** - корректная работа с таймаутами Railway

## 📊 Сравнение с оригинальным сервером

| Функция | Оригинальный | Улучшенный |
|---------|--------------|------------|
| Максимальный размер файла | ~20-50 MB | 2+ GB |
| Использование памяти | Весь файл в памяти | Стриминг (< 100MB) |
| Таймауты | Падает через 3-5 мин | Фоновая обработка |
| Очереди | Нет | Redis |
| Мониторинг | Нет | Статусы задач |
| Масштабируемость | Плохая | Отличная |

## 🔧 Установка на Railway

### 1. Подготовка окружения

```bash
# Клонируйте репозиторий
git init
git add .
git commit -m "Initial commit"

# Создайте проект на Railway
railway login
railway init
```

### 2. Настройка переменных окружения в Railway

```env
# Telegram
TELEGRAM_TOKEN=your_bot_token_here
TELEGRAM_WEBHOOK_URL=https://your-app.up.railway.app/webhook

# S3 (Cloudflare R2 или AWS)
S3_BUCKET=your-bucket-name
S3_REGION=auto
S3_ENDPOINT=https://your-account.r2.cloudflarestorage.com
S3_ACCESS_KEY=your_access_key
S3_SECRET_KEY=your_secret_key

# Redis (Railway предоставляет автоматически)
REDIS_URL=${{REDIS_PRIVATE_URL}}

# Лимиты
MAX_FILE_SIZE=2147483648  # 2GB
CHUNK_SIZE=5242880         # 5MB chunks

# Performance
WORKERS=4
```

### 3. Добавьте Redis в Railway

```bash
railway add redis
```

### 4. Деплой

```bash
railway up
```

## 🔌 Интеграция с n8n

### Настройка Webhook в n8n:

1. **Создайте Telegram Trigger**
2. **Добавьте HTTP Request node** для вызова вашего сервера
3. **Используйте Function node** с кодом из `n8n_integration.js`

### Пример workflow:

```json
{
  "nodes": [
    {
      "name": "Telegram Trigger",
      "type": "n8n-nodes-base.telegramTrigger",
      "position": [250, 300]
    },
    {
      "name": "Check File Size",
      "type": "n8n-nodes-base.if",
      "position": [450, 300],
      "parameters": {
        "conditions": {
          "number": [
            {
              "value1": "={{$json[\"video\"][\"file_size\"]}}",
              "operation": "larger",
              "value2": 52428800
            }
          ]
        }
      }
    },
    {
      "name": "Process Large File",
      "type": "n8n-nodes-base.httpRequest",
      "position": [650, 200],
      "parameters": {
        "url": "https://your-railway.up.railway.app/upload-telegram-file",
        "method": "POST",
        "bodyParametersJson": {
          "file_id": "={{$json[\"video\"][\"file_id\"]}}",
          "file_name": "={{$json[\"video\"][\"file_name\"]}}",
          "user_id": "={{$json[\"from\"][\"id\"]}}",
          "chat_id": "={{$json[\"chat\"][\"id\"]}}",
          "file_size": "={{$json[\"video\"][\"file_size\"]}}"
        }
      }
    },
    {
      "name": "Generate Presigned URL",
      "type": "n8n-nodes-base.httpRequest",
      "position": [650, 400],
      "parameters": {
        "url": "https://your-railway.up.railway.app/generate-upload-url",
        "method": "POST"
      }
    }
  ]
}
```

## 📱 Использование API

### 1. Генерация presigned URL для больших файлов

```bash
curl -X POST https://your-app.railway.app/generate-upload-url \
  -H "Content-Type: application/json" \
  -d '{
    "file_name": "video.mp4",
    "file_type": "video/mp4",
    "user_id": "123456",
    "expires_in": 3600
  }'
```

### 2. Загрузка файла из Telegram

```bash
curl -X POST https://your-app.railway.app/upload-telegram-file \
  -H "Content-Type: application/json" \
  -d '{
    "file_id": "telegram_file_id",
    "file_name": "video.mp4",
    "user_id": "123456",
    "chat_id": "789",
    "file_size": 1073741824
  }'
```

### 3. Проверка статуса задачи

```bash
curl https://your-app.railway.app/status/{job_id}
```

### 4. Chunked Upload для очень больших файлов

```javascript
// Клиентский код для загрузки по частям
const CHUNK_SIZE = 5 * 1024 * 1024; // 5MB chunks
const file = document.getElementById('fileInput').files[0];
const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

for (let i = 0; i < totalChunks; i++) {
    const start = i * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, file.size);
    const chunk = file.slice(start, end);
    
    const formData = new FormData();
    formData.append('file', chunk);
    formData.append('user_id', '123456');
    formData.append('chunk_number', i);
    formData.append('total_chunks', totalChunks);
    
    await fetch('/multipart-upload', {
        method: 'POST',
        body: formData
    });
}
```

## 🎬 Интеграция с Vizard

### Автоматический запуск обработки:

```python
# После успешной загрузки видео
response = requests.post(
    "https://your-app.railway.app/initiate-vizard-processing",
    data={
        "s3_url": s3_url,
        "user_id": user_id,
        "chat_id": chat_id,
        "vizard_settings": json.dumps({
            "clips": 10,
            "duration": 60,
            "format": "vertical",
            "auto_captions": True,
            "social_networks": ["instagram", "tiktok", "youtube_shorts"]
        })
    }
)
```

## 📊 Мониторинг и отладка

### Health Check endpoint:
```bash
curl https://your-app.railway.app/health
```

### Логи в Railway:
```bash
railway logs
```

### Redis CLI для отладки:
```bash
railway run redis-cli
> KEYS job:*
> GET job:abc123
> LRANGE vizard_queue 0 -1
```

## 🚨 Решение частых проблем

### 1. Таймаут при загрузке
- Используйте presigned URLs для файлов > 50MB
- Включите фоновую обработку

### 2. Нехватка памяти
- Проверьте настройку CHUNK_SIZE
- Убедитесь, что используется стриминг

### 3. Ошибки S3
- Проверьте права доступа (IAM policy)
- Убедитесь в правильности CORS настроек

### 4. Redis connection errors
- Проверьте REDIS_URL в переменных окружения
- Перезапустите Redis сервис в Railway

## 📈 Производительность

- **Загрузка 100MB**: ~30 секунд
- **Загрузка 500MB**: ~2-3 минуты
- **Загрузка 1GB**: ~5-7 минут
- **Загрузка 2GB**: ~10-15 минут

## 🔐 Безопасность

1. Используйте HTTPS для всех соединений
2. Ограничивайте размер файлов через MAX_FILE_SIZE
3. Валидируйте типы файлов
4. Используйте rate limiting для API
5. Храните sensitive данные в переменных окружения

## 🎯 Дальнейшие улучшения

1. **CDN интеграция** - для быстрой доставки контента
2. **Превью генерация** - создание миниатюр для видео
3. **Прогресс бар** - real-time отслеживание загрузки
4. **Batch processing** - обработка нескольких видео одновременно
5. **Auto-retry** - автоматическая повторная попытка при сбоях

## 📞 Поддержка

При возникновении проблем:
1. Проверьте логи: `railway logs`
2. Проверьте статус сервисов: `/health`
3. Проверьте очередь Redis
4. Убедитесь в правильности настроек S3

---

**Важно**: Этот сервер оптимизирован для Railway и может требовать адаптации для других платформ.
