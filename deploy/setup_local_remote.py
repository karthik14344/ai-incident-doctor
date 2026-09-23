"""Create the local bare remote `pipeline` that runs CI/CD on every push.

    python deploy/setup_local_remote.py
    git push pipeline main          # -> tests, then SHA-tagged deploy

The remote lives in runtime/pipeline.git (gitignored). Its post-receive hook
starts deploy/pipeline.py in the background for pushes to main, so `git push`
returns at once, exactly like pushing to GitHub and letting Actions run.
Nothing is sent anywhere outside this machine.
"""

import os
import stat
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BARE = os.path.join(REPO, "runtime", "pipeline.git")

HOOK = """#!/bin/sh
# Installed by deploy/setup_local_remote.py. Runs the pipeline for pushes to main.
while read old new ref; do
  if [ "$ref" = "refs/heads/main" ] && [ "$new" != "0000000000000000000000000000000000000000" ]; then
    mkdir -p "{repo}/runtime/pipeline"
    ( cd "{repo}" && nohup "{python}" deploy/pipeline.py --sha "$new" --ref "$ref" \\
        > "{repo}/runtime/pipeline/last-run.log" 2>&1 & )
    echo "pipeline: started for $new (logs in runtime/pipeline/)"
  fi
done
"""


def main() -> int:
    if not os.path.isdir(BARE):
        subprocess.run(["git", "init", "--bare", "-q", "-b", "main", BARE], check=True)
    hook = os.path.join(BARE, "hooks", "post-receive")
    posix = lambda p: p.replace("\\", "/")  # noqa: E731 - Git for Windows runs hooks with sh
    with open(hook, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(HOOK.format(repo=posix(REPO), python=posix(sys.executable)))
    os.chmod(hook, os.stat(hook).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    remotes = subprocess.run(["git", "remote"], cwd=REPO, capture_output=True, text=True).stdout.split()
    if "pipeline" not in remotes:
        subprocess.run(["git", "remote", "add", "pipeline", BARE], cwd=REPO, check=True)
    print(f"remote 'pipeline' -> {BARE}\nhook: {hook}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
