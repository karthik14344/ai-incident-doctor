#!/bin/sh
# Bring the whole stack up on the GCP VM. deploy/gcp/startup.sh runs this on
# every boot, after it has fetched this repo and the agent team (AGAI).
# By hand (on the VM):  sudo sh /opt/aid/ai-incident-doctor/deploy/gcp/vm-up.sh
#
#   1. Python tools for the pipeline, deploy and fault scripts (.venv)
#   2. .env from .env.example + Secret Manager (deploy/gcp/write_env.py)
#   3. the local pipeline remote, so fault runs on the VM deploy like on the laptop
#   4. the agent team's image, from AGAI's own checkout (deploy/agai/build.sh)
#   5. the knowledge base (first boot), then deploy/deploy.py: SHA-tagged images, compose up
#      (with the "agents" profile), smoke test, deploy record
set -eu
# Start-up scripts run without HOME; git --global and pip need one.
export HOME="${HOME:-/root}"
cd "$(dirname "$0")/../.."
AGAI_DIR=${AGAI_DIR:-/opt/aid/AGAI}
PY=.venv/bin/python
say() { echo "=== vm-up $(date -u +%T): $*"; }

say "python tools"
[ -x "$PY" ] || python3 -m venv .venv
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q -r requirements-dev.txt -r doctor/requirements.txt

say ".env"
"$PY" deploy/gcp/write_env.py

say "pipeline remote"
git config --global --add safe.directory "$(pwd)" 2>/dev/null || true
git config --global user.name >/dev/null || git config --global user.name "aid-vm"
git config --global user.email >/dev/null || git config --global user.email "aid-vm@localhost"
sh scripts/pipeline/init_local_pipeline.sh

say "agent team image"
TAG=$(sh deploy/agai/build.sh "$AGAI_DIR")
"$PY" deploy/gcp/write_env.py "AGAI_IMAGE_TAG=$TAG"

if [ ! -f kb/index/chroma.sqlite3 ]; then
  # The exact build dvc.lock describes, uploaded by create_vm.ps1 (rebuilding it
  # here would change dvc.lock, and deploy.py refuses a dirty tree).
  say "knowledge base"
  tar -xzf /opt/aid/kb.tar.gz
fi

say "deploy"
"$PY" deploy/deploy.py --pipeline manual --reason "GCP VM boot $(git rev-parse --short HEAD)"
say "up: app :3001  grafana :3000  doctor :8100  agent team :8200"
