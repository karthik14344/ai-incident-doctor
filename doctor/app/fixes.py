"""Turn a proposed fix into a unified diff, and apply it to a throwaway copy.

Nothing here touches the running system or the real repository: the patient
source is exported from git at the running commit into a temporary directory,
and edits are applied there.
"""

import difflib
import io
import os
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any, Dict, List, Optional, Tuple


def file_at(repo: str, sha: str, path: str) -> Optional[str]:
    r = subprocess.run(["git", "-C", repo, "show", f"{sha}:{path}"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else None


def _normalise_path(path: str) -> str:
    p = path.strip().lstrip("./").replace("\\", "/")
    if p.startswith("a/") or p.startswith("b/"):
        p = p[2:]
    if p.startswith("app/") or p.startswith("/app/"):
        p = "patient/" + p.split("app/", 1)[1]
    for svc in ("api_gateway/", "ingestion_service/", "retrieval_service/", "llm_service/", "common/",
                "evaluation/", "kb/"):
        if p.startswith(svc):
            p = "patient/" + p
    return p


def apply_edits_to_text(text: str, edits: List[Dict[str, str]]) -> Tuple[str, List[str]]:
    problems = []
    for e in edits:
        find, replace = e.get("find", ""), e.get("replace", "")
        if not find:
            problems.append("empty 'find'")
            continue
        count = text.count(find)
        if count == 0:
            # Tolerate indentation drift: match ignoring leading/trailing whitespace per line.
            stripped = "\n".join(line.strip() for line in find.splitlines())
            lines = text.splitlines(keepends=True)
            n = len(find.splitlines())
            hit = None
            for i in range(len(lines) - n + 1):
                if "\n".join(line.strip() for line in lines[i:i + n]) == stripped:
                    hit = i
                    break
            if hit is None:
                problems.append(f"'find' text not found: {find[:80]!r}")
                continue
            # Re-indent each replacement line like the original line it stands in for
            # (lines beyond the matched block take the last matched line's indent).
            indents = [ln[: len(ln) - len(ln.lstrip())] for ln in lines[hit:hit + n]]
            find_lines = find.splitlines()
            new_lines = []
            for j, line in enumerate(replace.splitlines()):
                if not line.strip():
                    new_lines.append("\n")
                    continue
                k = min(j, len(indents) - 1)
                # Keep any extra nesting the model added relative to its own find text.
                own = len(line) - len(line.lstrip())
                ref = find_lines[k] if k < len(find_lines) else find_lines[-1]
                extra = max(0, own - (len(ref) - len(ref.lstrip())))
                new_lines.append(indents[k] + " " * extra + line.strip() + "\n")
            new_block = "".join(new_lines)
            text = "".join(lines[:hit]) + new_block + "".join(lines[hit + n:])
        else:
            text = text.replace(find, replace, 1)
    return text, problems


def edits_to_diff(repo: str, sha: str, edits: List[Dict[str, str]]) -> Dict[str, Any]:
    """Render search/replace edits against the running commit as one unified diff."""
    by_file: Dict[str, List[Dict[str, str]]] = {}
    for e in edits or []:
        by_file.setdefault(_normalise_path(e.get("file", "")), []).append(e)
    parts, problems, changed = [], [], []
    for path, file_edits in by_file.items():
        original = file_at(repo, sha, path)
        if original is None:
            problems.append(f"{path}: file does not exist at {sha[:7]}")
            continue
        updated, errs = apply_edits_to_text(original, file_edits)
        problems.extend(f"{path}: {e}" for e in errs)
        if updated == original:
            continue
        changed.append(path)
        parts.append("".join(difflib.unified_diff(
            original.splitlines(keepends=True), updated.splitlines(keepends=True),
            fromfile=f"a/{path}", tofile=f"b/{path}")))
    return {"diff": "".join(parts), "files": changed, "problems": problems}


def export_tree(repo: str, sha: str, dest: str, paths: Tuple[str, ...] = ("patient",)) -> None:
    """`git archive` the given paths at sha into dest (no .git, no working-tree state)."""
    data = subprocess.run(["git", "-C", repo, "archive", "--format=tar", sha, *paths],
                          check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest)


def apply_diff(workdir: str, diff: str) -> Tuple[bool, str]:
    if not diff.strip():
        return False, "empty diff"
    patch = os.path.join(workdir, "fix.patch")
    with open(patch, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(diff if diff.endswith("\n") else diff + "\n")
    for args in (["git", "apply", "--recount", "--whitespace=nowarn", patch],
                 ["git", "apply", "--recount", "--whitespace=nowarn", "-C1", patch]):
        r = subprocess.run(args, cwd=workdir, capture_output=True, text=True)
        if r.returncode == 0:
            return True, "applied"
    return False, (r.stderr or r.stdout)[-800:]


class Sandbox:
    """A throwaway copy of the patient at one commit, optionally patched."""

    def __init__(self, repo: str, sha: str):
        self.repo, self.sha = repo, sha
        self.dir = tempfile.mkdtemp(prefix="doctor_sandbox_")
        export_tree(repo, sha, self.dir)

    def patch(self, diff: str) -> Tuple[bool, str]:
        return apply_diff(self.dir, diff)

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
