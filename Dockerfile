# One container for small free hosts: the website, API and scheduled jobs in a single
# process, with no Redis. docker-compose.yml is the full deployment.
FROM node:25-alpine AS site
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    ARTIFACTS_DIR=/app/artifacts EMBEDDING_CACHE_DIR=/app/embeddings \
    STATIC_DIR=/app/site SINGLE_PROCESS=true
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/ .
COPY --from=site /app/dist /app/site

# A small server is too slow to train at start-up, so the models and the embedding model are
# built into the image. These two placeholders exist for this step only and connect to nothing.
RUN DATABASE_URL=postgresql://build-only JWT_SECRET=build-only-placeholder-not-a-real-secret \
    sh -c "python -m app.ml.train && python -c \"from app.rag.embeddings import get_embedder; get_embedder().embed(['ready'])\""

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips '*'"]
