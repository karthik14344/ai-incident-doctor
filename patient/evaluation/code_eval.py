"""Exercise 3 - test-pass rate for generated code.

The three code tasks in the dataset each ship a fixed pytest suite. A model's
answer is only credited for what actually runs: the code block is extracted,
written to `solution.py` next to the suite in a throwaway directory, and pytest
is run against it in a subprocess.

The denominator is the number of tests in the suite, never the number pytest
managed to collect. Otherwise an answer that fails to import would score 0/0 and
quietly vanish from the average instead of scoring zero.

Generated code is executed. It is confined to a temporary directory and killed
after `RUN_TIMEOUT_S`, but it is still model-written code running locally - the
suites here only exercise arithmetic over policy thresholds.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, Optional

RUN_TIMEOUT_S = 60

_FENCED_PY = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.S | re.I)
_FENCED_ANY = re.compile(r"```[a-z0-9_+-]*\s*\n(.*?)```", re.S | re.I)
_SUMMARY = re.compile(r"(\d+)\s+(passed|failed|error|errors)")


def extract_code(answer: str) -> Optional[str]:
    """Pull the Python out of a model answer.

    Tried in order: a ```python fence, any fence, then the raw answer when it
    looks like bare code. Models that were told "code block only" still narrate
    about a third of the time, so the bare-answer path needs the `def` guard to
    avoid handing pytest a paragraph of prose.
    """
    if not answer:
        return None

    blocks = _FENCED_PY.findall(answer) or _FENCED_ANY.findall(answer)
    if blocks:
        # Several fences usually means "here is the function, here is how to
        # call it" - concatenating keeps helper definitions that later blocks need.
        joined = "\n\n".join(b.strip() for b in blocks if "def " in b or "=" in b)
        if "def " in joined:
            return joined
        return blocks[0].strip()

    if "def " in answer:
        # Bare code with no fence: drop leading prose lines before the first def
        # or import, which is where models put "Here is the function:".
        lines = answer.splitlines()
        for index, line in enumerate(lines):
            if line.lstrip().startswith(("def ", "import ", "from ")):
                return "\n".join(lines[index:]).strip()
    return None


def run_code_task(answer: str, code_task: Dict[str, Any]) -> Dict[str, Any]:
    """Run one model's generated code against the task's fixed pytest suite."""
    suite = code_task["tests"]
    tests_total = suite.count("def test_")
    entry_points = code_task.get("entry_points", [])

    code = extract_code(answer)
    if not code:
        return _result(tests_total, 0, "no-code",
                       "No Python code block could be extracted from the answer.")

    missing = [name for name in entry_points if f"def {name}" not in code]
    if missing:
        # Still run it - the model may have defined them via lambda or alias -
        # but record the mismatch, because it is the usual cause of a 0.
        note = f"Answer does not define: {', '.join(missing)}"
    else:
        note = None

    workdir = tempfile.mkdtemp(prefix="knowledgeai_codeeval_")
    try:
        with open(os.path.join(workdir, "solution.py"), "w", encoding="utf-8") as fh:
            fh.write(code)
        with open(os.path.join(workdir, "test_solution.py"), "w", encoding="utf-8") as fh:
            fh.write(suite)

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--tb=line",
                 "-p", "no:cacheprovider", "test_solution.py"],
                cwd=workdir, capture_output=True, text=True, timeout=RUN_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return _result(tests_total, 0, "timeout",
                           f"pytest did not finish within {RUN_TIMEOUT_S}s.", code)

        output = f"{proc.stdout}\n{proc.stderr}".strip()
        counts = {kind.rstrip("s"): int(n) for n, kind in _SUMMARY.findall(output)}
        passed = counts.get("passed", 0)

        if counts.get("error"):
            status = "import-error"
        elif passed == tests_total:
            status = "pass"
        elif passed:
            status = "partial"
        else:
            status = "fail"

        return _result(tests_total, passed, status, note, code, output[-1500:])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _result(total: int, passed: int, status: str, note: Optional[str] = None,
            code: Optional[str] = None, output: Optional[str] = None) -> Dict[str, Any]:
    return {
        "tests_total": total,
        "tests_passed": passed,
        "test_pass_rate_pct": round(100.0 * passed / total, 1) if total else 0.0,
        "status": status,
        "note": note,
        "extracted_code": code,
        "pytest_output": output,
    }
