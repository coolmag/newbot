# Этап 1: Сборка с зависимостями
FROM python:3.11-slim as builder

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ffmpeg

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --upgrade yt-dlp



# Этап 2: Финальный образ
FROM python:3.11-slim

# Установка только FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg

WORKDIR /app

# Копируем установленные зависимости
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копируем исходный код
COPY *.py ./

# Копируем опциональные файлы
COPY .env.example .
COPY cookies.txt* ./

# Создаем пустые директории, если они нужны
RUN mkdir -p downloads

# Запуск бота
CMD ["python", "-u", "main.py"]
