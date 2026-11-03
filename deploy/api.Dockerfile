# Karnex License API (FastAPI). Build context = the repository root (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=3001 \
    HOST=0.0.0.0 \
    NODE_ENV=production

WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Code + database migrations (the API applies new database/postgres/NNN_*.sql on start).
# Demo data and tests are not copied (.dockerignore).
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/run.py ./run.py
COPY database/postgres /app/database/postgres

RUN useradd --system --uid 10001 klicense && chown -R klicense /app
USER klicense

EXPOSE 3001
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:3001/health/db', timeout=4).status == 200 else 1)"

CMD ["python", "run.py"]
