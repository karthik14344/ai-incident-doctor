"""Check every push fault before using it:

  * the linter (ruff, with the repo's config) and the existing test suite still
    PASS with the fault applied - the bug is subtle enough to get through CI,
    which is why it reaches production;
  * the fault's acceptance test FAILS with the fault applied, and passes
    without it - so it really detects the fault, and a fix that passes it
    really fixed it.

Runs on throwaway `git archive` copies; the repository is not touched.

    python -m faults.selfcheck
"""

import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

from faults.catalog import FAULTS
from faults.common import REPO

PY = sys.executable


def export(dest: str) -> None:
    data = subprocess.run(["git", "archive", "--format=tar", "HEAD", "patient"], cwd=REPO,
                          check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest)


def pytest(workdir: str, *targets: str) -> bool:
    env = {**os.environ, "KNOWLEDGEAI_ENV_FILE": os.devnull, "CHROMA_HOST": ""}
    for var in ("OLLAMA_BASE_URL", "INGESTION_SERVICE_URL", "RETRIEVAL_SERVICE_URL", "LLM_SERVICE_URL"):
        env.pop(var, None)
    r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets],
                       cwd=os.path.join(workdir, "patient"), capture_output=True, text=True, env=env, timeout=600)
    return r.returncode == 0


def check(fault) -> dict:
    out = {}
    for label, apply in (("healthy", False), ("faulty", True)):
        tmp = tempfile.mkdtemp(prefix="faultcheck_")
        try:
            export(tmp)
            if apply:
                for path, old, new in fault.edits:
                    full = os.path.join(tmp, path)
                    text = open(full, encoding="utf-8").read()
                    assert old in text, f"{fault.id}: anchor not found in {path}"
                    open(full, "w", encoding="utf-8", newline="\n").write(text.replace(old, new, 1))
            # Lint exactly as CI does (repo config, so embedder.py stays excluded).
            shutil.copy(os.path.join(REPO, "pyproject.toml"), os.path.join(tmp, "pyproject.toml"))
            lint = subprocess.run([PY, "-m", "ruff", "check", "patient"], cwd=tmp, capture_output=True, text=True)
            out[f"{label}_lint_passes"] = lint.returncode == 0
            out[f"{label}_suite_passes"] = pytest(tmp, "tests")
            if fault.acceptance_test:
                shutil.copy(fault.acceptance_test, os.path.join(tmp, "patient", "tests", "test_acceptance.py"))
                out[f"{label}_acceptance_passes"] = pytest(tmp, "tests/test_acceptance.py")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    out["ok"] = (out["healthy_suite_passes"] and out["faulty_suite_passes"] and out["faulty_lint_passes"]
                 and out.get("healthy_acceptance_passes", True) and not out.get("faulty_acceptance_passes", False))
    return out


def main() -> int:
    bad = 0
    for fault in FAULTS.values():
        if fault.delivery != "push":
            continue
        result = check(fault)
        bad += not result["ok"]
        print(f"{fault.id:<22} {'OK ' if result['ok'] else 'BAD'} {result}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
