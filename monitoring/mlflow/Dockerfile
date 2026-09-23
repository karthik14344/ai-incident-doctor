# MLflow tracking server: SQLite for runs/metrics, MinIO (S3 API) for artifacts.
# The official image does not ship boto3, which the S3 artifact store needs.
FROM ghcr.io/mlflow/mlflow:v3.3.2
RUN pip install --no-cache-dir boto3==1.40.30
RUN useradd --uid 10001 --create-home mlflow && mkdir -p /mlflow && chown mlflow:mlflow /mlflow
USER mlflow
EXPOSE 5000
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=4)" || exit 1
# --serve-artifacts proxies artifact uploads, so clients need no S3 credentials.
CMD ["sh", "-c", "exec mlflow server --host 0.0.0.0 --port 5000 --backend-store-uri sqlite:////mlflow/mlflow.db --artifacts-destination s3://mlflow/artifacts --serve-artifacts"]
