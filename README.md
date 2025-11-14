# Video Upload Server (Telegram -> Railway -> S3)

## Endpoints:
POST /upload  
Body:
{
  "file_id": "telegram_file_id"
}

## Features:
- Stream download from Telegram
- Stream upload to S3 (Cloudflare R2)
- No RAM issues
