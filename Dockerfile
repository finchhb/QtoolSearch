# QtoolSearch — единый образ для трёх сервисов (api, streamlit, max-bot).
# Один и тот же образ + один и тот же код: индекс в памяти держит только api,
# streamlit и бот ходят к нему по HTTP — нет трёх копий каталога в RAM.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Сначала зависимости — слой кэшируется, пересборка кода не переустанавливает пакеты.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем код проекта.
COPY . .

# Каталог данных монтируется томом (см. docker-compose.yml), чтобы обновления
# прайсов/остатков переживали пересборку образа.
RUN mkdir -p /app/data

# По умолчанию запускается API; конкретную команду задаёт docker-compose для каждого сервиса.
EXPOSE 8000 8501 8080
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]