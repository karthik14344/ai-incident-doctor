# The incident doctor. Build from the repository root:
#   docker build -f doctor/Dockerfile --build-arg APP_GIT_SHA=$(git rev-parse HEAD) .
#
# The repository (git history included) is mounted read-only at /repo at run
# time: the doctor searches commits and exports throwaway copies from it. git is
# installed for that. It never writes to the repository.
FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home app \
    && git config --system --add safe.directory '*'
WORKDIR /srv

COPY patient/requirements.txt /tmp/patient-requirements.txt
COPY doctor/requirements.txt /tmp/doctor-requirements.txt
RUN pip install --no-cache-dir -r /tmp/patient-requirements.txt -r /tmp/doctor-requirements.txt

COPY doctor/app ./app
COPY loadgen ./loadgen
RUN mkdir -p /data && chown app:app /data

ARG APP_GIT_SHA=unknown
ENV APP_GIT_SHA=${APP_GIT_SHA} \
    DOCTOR_REPO=/repo \
    DOCTOR_DATA_DIR=/data \
    DOCTOR_ENV_FILE=/dev/null \
    PYTHONPATH=/srv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app
EXPOSE 8100
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=4)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100", "--no-access-log"]
