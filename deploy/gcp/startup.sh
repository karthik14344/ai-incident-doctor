#!/bin/bash
# Start-up script of the GCP VM (installed as instance metadata by
# deploy/gcp/create_vm.ps1). Google runs it as root on EVERY boot.
#
#   1. first boot only: Docker Engine + compose, Python venv tools, Ollama
#      (listening for the containers) and the patient's two models
#   2. this repo at origin/main from GitHub; the agent team (AGAI) at the
#      pinned commit, from the bundle create_vm.ps1 uploads
#   3. hands over to the repo's deploy/gcp/vm-up.sh, which writes .env from
#      Secret Manager and brings the whole stack up
#
# Kept small on purpose: everything that may change lives in the repo, so a
# `git push origin main` changes what the VM runs at its next boot.
# Log: /var/log/aid-startup.log
set -uo pipefail
exec >>/var/log/aid-startup.log 2>&1
echo "=== boot $(date -u +%FT%TZ)"

meta() { curl -fsS -H Metadata-Flavor:Google \
  "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
REPO_URL=$(meta aid-repo-url)
AGAI_REF=$(meta aid-agai-ref)
ROOT=/opt/aid
APP=$ROOT/ai-incident-doctor
AGAI=$ROOT/AGAI
mkdir -p "$ROOT"

# ---- 1. software (first boot only) ----------------------------------------
if ! command -v docker >/dev/null; then
  echo "=== installing Docker"
  apt-get update -q
  apt-get install -y -q ca-certificates curl git python3 python3-pip python3-venv
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-buildx-plugin
fi
if ! command -v ollama >/dev/null; then
  echo "=== installing Ollama"
  curl -fsSL https://ollama.com/install.sh | sh
  # The patient containers reach it at host.docker.internal; the GCP firewall
  # does not open 11434, so it stays private to the VM.
  mkdir -p /etc/systemd/system/ollama.service.d
  printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0"\n' > /etc/systemd/system/ollama.service.d/listen.conf
  systemctl daemon-reload
  systemctl restart ollama
fi
for _ in $(seq 60); do curl -fsS http://127.0.0.1:11434/api/version >/dev/null && break; sleep 2; done
for model in llama3.2 nomic-embed-text; do
  ollama list | grep -q "^$model" || ollama pull "$model"
done

# ---- 2. code ---------------------------------------------------------------
if [ ! -d "$APP/.git" ]; then git clone -q "$REPO_URL" "$APP"; fi
git -C "$APP" fetch -q origin main
git -C "$APP" checkout -q main
git -C "$APP" reset -q --hard origin/main
echo "=== repo at $(git -C "$APP" rev-parse --short HEAD)"

# create_vm.ps1 uploads two files the repo cannot provide: a git bundle of the
# agent team at the exact commit (the local AGAI is ahead of its GitHub repo)
# and the knowledge-base build (DVC data). Wait for them on the first boot.
for _ in $(seq 180); do
  [ -f "$ROOT/agai.bundle" ] && [ -f "$ROOT/kb.tar.gz" ] && break
  sleep 10
done
if [ -f "$ROOT/agai.bundle" ]; then
  [ -d "$AGAI/.git" ] || git clone -q "$ROOT/agai.bundle" "$AGAI"
  git -C "$AGAI" fetch -q "$ROOT/agai.bundle" "+refs/heads/*:refs/remotes/bundle/*"
fi
git -C "$AGAI" -c advice.detachedHead=false checkout -q "$AGAI_REF"
echo "=== agent team at $(git -C "$AGAI" rev-parse --short HEAD)"

# ---- 3. the stack ------------------------------------------------------------
exec sh "$APP/deploy/gcp/vm-up.sh"
