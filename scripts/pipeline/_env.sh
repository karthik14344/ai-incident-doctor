# Shared by the pipeline scripts: repository root and the Python to use.
# Sourced, not executed.
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"
if [ -n "${PYTHON:-}" ]; then
  PY="$PYTHON"
elif [ -x .venv/Scripts/python.exe ]; then
  PY=.venv/Scripts/python.exe          # Windows development laptop
elif [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python3                            # GitHub runners, the Pavilion runner
fi
case "$PY" in
  .venv/*) PY="$REPO_ROOT/$PY" ;;       # absolute, so steps may cd elsewhere
esac
# Git for Windows rewrites /paths in docker arguments unless told not to.
export MSYS_NO_PATHCONV=1
# A host path Docker understands (Windows form on Git Bash, plain elsewhere).
HOST_PWD="$(pwd -W 2>/dev/null || pwd)"
step() {
  name="$1"; shift
  echo "=== $name"
  started=$(date +%s)
  "$@"
  echo "=== $name: ok ($(( $(date +%s) - started ))s)"
}
