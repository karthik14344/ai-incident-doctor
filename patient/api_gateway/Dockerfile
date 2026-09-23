# KnowledgeAI gateway service. Build from the repository root:
#   docker build -f patient/api_gateway/Dockerfile --build-arg APP_GIT_SHA=$(git rev-parse HEAD) .
#
# The first layers are identical in all four service images, so Docker stores
# the heavy dependency layer once. The services import each other's modules
# (the gateway uses the vector store and the evaluation scorers, retrieval uses
# the embedder), so every image carries the whole backend package.
FROM python:3.10-slim

RUN useradd --uid 10001 --create-home app
WORKDIR /app

COPY patient/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY patient/common ./common
COPY patient/api_gateway ./api_gateway
COPY patient/ingestion_service ./ingestion_service
COPY patient/retrieval_service ./retrieval_service
COPY patient/llm_service ./llm_service
COPY patient/evaluation ./evaluation
COPY patient/kb ./kb

# Named volumes inherit this ownership, so the non-root user can write them.
RUN mkdir -p /app/data /app/storage/documents && chown -R app:app /app/data /app/storage

# Baked in last so a new commit only rebuilds the layers from here down.
ARG APP_GIT_SHA=unknown
ENV APP_GIT_SHA=${APP_GIT_SHA} \
    SERVICE_NAME=gateway \
    PORT=8000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ['PORT'], timeout=4)" || exit 1

# One worker per container: Prometheus counters (and the embedding-fallback
# counter) are per process, so a single process keeps them meaningful.
CMD ["sh", "-c", "exec uvicorn api_gateway.app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log --timeout-graceful-shutdown 10"]
