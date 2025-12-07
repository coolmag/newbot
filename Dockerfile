# Этап 1: Сборка с зависимостями
FROM python:3.11-slim as builder

# Установка системных зависимостей, необходимых для сборки некоторых Python пакетов
# и FFmpeg для обработки аудио.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем файлы с зависимостями и устанавливаем их
# Это кэшируется Docker'ом и ускоряет сборку, если меняется только код
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# Этап 2: Финальный образ
FROM python:3.11-slim

# Устанавливаем только необходимые для работы системные пакеты
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем установленные зависимости из образа-сборщика
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копируем исходный код приложения
COPY *.py ./

# Указываем команду для запуска бота
# Используем -u для несбуферизованного вывода, чтобы логи сразу появлялись в Docker logs
CMD ["python", "-u", "main.py"]

