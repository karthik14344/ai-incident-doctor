#!/bin/sh
# Job 1 - lint and test. The ONLY copy of these steps: the local post-receive
# hook and the GitHub Actions workflow both call this script.
# Needs nothing running except Docker (for promtool/amtool/compose config).
set -eu
. "$(dirname "$0")/_env.sh"

step ruff "$PY" -m ruff check .
step yamllint "$PY" -m yamllint -c .yamllint.yml .
step "patient tests" sh -c "cd patient && \"$PY\" -m pytest -q -p no:cacheprovider"
step "alert-sink tests" sh -c "cd alert_sink && \"$PY\" -m pytest -q -p no:cacheprovider"
step "doctor tests" "$PY" -m pytest -q -p no:cacheprovider doctor/tests
step promtool docker run --rm --entrypoint sh -v "$HOST_PWD/monitoring/prometheus:/etc/prometheus" \
  -w /etc/prometheus prom/prometheus:v3.5.0 -c "promtool check config prometheus.yml && promtool test rules alert.rules.test.yml"
step amtool docker run --rm --entrypoint amtool -v "$HOST_PWD/monitoring/alertmanager:/etc/alertmanager" \
  prom/alertmanager:v0.28.1 check-config /etc/alertmanager/alertmanager.yml
[ -f .env ] || cp .env.example .env
step "compose config" env IMAGE_TAG=verify docker compose config --quiet

# The installed hook must be the tracked one (scripts/pipeline/post-receive).
if [ -f runtime/pipeline.git/hooks/post-receive ]; then
  step "installed hook matches tracked hook" cmp -s scripts/pipeline/post-receive runtime/pipeline.git/hooks/post-receive
fi
echo "verify: all checks passed"
