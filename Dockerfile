FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    SCRIBD_DATA_DIR=/data \
    SCRIBD_BACKEND_SCRIPT=/app/backend/scribd-downloader.py \
    SCRIBD_WEB_DIR=/app/web \
    SCRIBD_HEADLESS=1 \
    CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER=/usr/bin/chromedriver \
    TMPDIR=/data/tmp \
    HOME=/home/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        chromium \
        chromium-driver \
        fonts-croscore \
        fonts-dejavu-core \
        fonts-liberation2 \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY scribd-downloader/scribd-downloader.py /app/backend/scribd-downloader.py
COPY server /app/server
COPY scribd-downloader-web/scribd-downloader-web /app/web

RUN useradd --create-home --home-dir /home/app --uid 10001 app \
    && mkdir -p /data/jobs /data/tmp \
    && chown -R app:app /data /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=6s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app:app", "--app-dir", "/app/server", "--host", "0.0.0.0", "--port", "8000"]
