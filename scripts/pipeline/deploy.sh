#!/bin/sh
# Job 2 - deploy one commit:  scripts/pipeline/deploy.sh <sha>
#
# The ONLY entry point for deploying: the local post-receive hook and the
# GitHub Actions workflow both call this script, and neither has its own copy
# of the steps. The steps themselves (SHA-tagged build, knowledge-base swap,
# compose up, smoke test, rollback on failure, deploy record, Grafana
# annotation) are implemented once, in deploy/deploy.py.
#
# PIPELINE=local|github says which pipeline produced the deploy; it is written
# into the deploy record so results from the two are never mixed silently.
#
# It never contacts the incident doctor. The doctor starts from symptoms only.
set -eu
. "$(dirname "$0")/_env.sh"

SHA="${1:?usage: deploy.sh <sha>}"
HEAD="$(git rev-parse HEAD)"
case "$HEAD" in
  "$SHA"*) ;;
  *) echo "deploy: workspace is at $HEAD but was asked to deploy $SHA" >&2; exit 2 ;;
esac

# The knowledge base is DVC data, not git: fetch it if this workspace lacks it.
if [ ! -f kb/index/chroma.sqlite3 ]; then
  step "knowledge base" sh -c "\"$PY\" -m dvc pull || \"$PY\" -m dvc repro build_kb"
fi

SHORT="$(printf '%s' "$HEAD" | cut -c1-7)"
step deploy "$PY" deploy/deploy.py --pipeline "${PIPELINE:-local}" \
  --reason "${DEPLOY_REASON:-${PIPELINE:-local} pipeline push $SHORT}"
