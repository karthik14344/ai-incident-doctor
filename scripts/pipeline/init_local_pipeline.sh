#!/bin/sh
# Set up the local pipeline remote:  sh scripts/pipeline/init_local_pipeline.sh
#
#   1. creates the bare repository runtime/pipeline.git (gitignored runtime state)
#   2. installs the tracked hook scripts/pipeline/post-receive into it
#   3. adds the git remote `pipeline` pointing at it
#
# Idempotent: re-run it after editing scripts/pipeline/post-receive (verify.sh
# fails if the installed hook has drifted from the tracked one).
#
# Then:  git push pipeline main   ->  verify.sh, then deploy.sh <sha>
# Nothing leaves this machine. This is a stand-in for GitHub Actions on the
# Pavilion runner, which calls the same two scripts (DECISIONS.md).
set -eu
. "$(dirname "$0")/_env.sh"

BARE="$REPO_ROOT/runtime/pipeline.git"
if [ ! -d "$BARE" ]; then
  git init --bare -q -b main "$BARE"
  echo "created $BARE"
fi
cp scripts/pipeline/post-receive "$BARE/hooks/post-receive"
chmod +x "$BARE/hooks/post-receive"
echo "installed hook $BARE/hooks/post-receive"

URL="$(cd "$BARE" && (pwd -W 2>/dev/null || pwd))"
if git remote get-url pipeline >/dev/null 2>&1; then
  git remote set-url pipeline "$URL"
else
  git remote add pipeline "$URL"
fi
echo "remote pipeline -> $URL"
