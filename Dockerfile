FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY nexaa ./nexaa
COPY config.yaml ./
COPY .env.example ./.env.example

RUN mkdir -p /app/data/pending /app/data/published /app/data/rejected /app/data/logs /app/data/scraper_cache /app/data/search_cache

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV PORT=8000

CMD ["sh", "-c", "uvicorn --factory nexaa.web.serve:create_app --host 0.0.0.0 --port ${PORT} --log-level info"]
