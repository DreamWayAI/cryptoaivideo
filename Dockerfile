FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# ВАЖНО: Используем shell форму (без квадратных скобок!)
# Это позволяет bash подставить значение $PORT
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
