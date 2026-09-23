# alert-sink: Alertmanager webhook -> JSON lines on a volume. Stdlib only.
FROM python:3.10-slim
RUN useradd --uid 10001 --create-home app && mkdir -p /data && chown app:app /data
WORKDIR /app
COPY alert_sink/sink.py ./sink.py
ARG APP_GIT_SHA=unknown
ENV APP_GIT_SHA=${APP_GIT_SHA} PORT=9095 ALERT_LOG_PATH=/data/alerts.jsonl PYTHONUNBUFFERED=1
USER app
EXPOSE 9095
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9095/health', timeout=2)" || exit 1
CMD ["python", "sink.py"]
