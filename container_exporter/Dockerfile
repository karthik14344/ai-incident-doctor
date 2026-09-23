# container-exporter: per-container memory/limit/restarts/OOM kills from the
# Docker API (cAdvisor cannot see containers under the containerd image store).
# Runs as root only because it must read the Docker socket.
FROM python:3.10-slim
WORKDIR /app
COPY container_exporter/exporter.py ./exporter.py
ARG APP_GIT_SHA=unknown
ENV APP_GIT_SHA=${APP_GIT_SHA} PORT=9102 PYTHONUNBUFFERED=1
EXPOSE 9102
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9102/health', timeout=2)" || exit 1
CMD ["python", "exporter.py"]
