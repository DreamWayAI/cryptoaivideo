FROM python:3.10-slim

WORKDIR /app

# Копируем requirements
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# Указываем переменную окружения для порта
ENV PORT=8000

# Запускаем приложение
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT}"
