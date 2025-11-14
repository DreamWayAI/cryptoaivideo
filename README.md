# Video Upload Pipeline (Railway -> Cloudflare R2)

## How it works:
1. n8n sends JSON:
{
  "file_url": "https://api.telegram.org/file/botTOKEN/path/to/video.mp4"
}
2. Server downloads file stream
3. Uploads stream directly to Cloudflare R2
4. Returns public URL

## Deploy on Railway:
- Upload ZIP
- Set env vars from .env.example
- Deploy
