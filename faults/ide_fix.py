"""Fix in VS Code: put an incident's code fix into the editor, the way an AI
assistant in an IDE does - the file opens with the change already made and a
red/green diff to review.

This runs on the developer's machine (showcase/fault_console.py calls it); the
doctor itself still never touches anything. It only ever edits files under
patient/, never commits, and every edit can be undone with `undo()`.

Where the patch comes from, in this order (the result says which one was used):

  1. doctor_patch    the unified diff in the doctor's report
  2. crash_line      the report has no usable diff, but a stack trace names the
                     crashing line: roll back the commit that introduced that
                     line - only if it is one of the incident's candidate commits
  3. blamed_commit   roll back the commit the doctor's top hypothesis blames

How it lands:

  applied   the bug is in the working tree: the patch is applied to the real
            file and VS Code opens `before <-> file` as a diff
  already   the working tree already contains the change: the file just opens
  preview   the bug is no longer in the working tree (the run already reverted
            it): VS Code opens a read-only `buggy <-> fixed` diff of copies
  none      nothing to apply (the fix is an action, e.g. "restart retrieval")
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED_PREFIX = "patient/"
SOURCE_LABEL = {
    "doctor_patch": "the patch in the doctor's report",
    "crash_line": "rolling back the commit that introduced the crashing line",
    "blamed_commit": "rolling back the commit the doctor blamed",
}


def state_dir(repo: str) -> str:
    return os.path.join(repo, "runtime", "ide-fix")


def _git(repo: str, *args: str, stdin: Optional[str] = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", "-C", repo, *args], input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


# ---------------------------------------------------------------- the patch

def patch_files(diff: str) -> List[str]:
    files = []
    for line in diff.splitlines():
        m = re.match(r"^\+\+\+ (?:b/)?(\S+)", line)
        if m and m.group(1) != "/dev/null" and m.group(1) not in files:
            files.append(m.group(1))
    return files


def first_changed_line(diff: str) -> int:
    """Line in the patched file where the first change sits (for --goto)."""
    lines = diff.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", line)
        if not m:
            continue
        at = int(m.group(1))
        for body in lines[i + 1:]:
            if body.startswith("+") or body.startswith("-"):
                return at
            at += 1
        return int(m.group(1))
    return 1


def safe_paths(files: List[str]) -> bool:
    return bool(files) and all(f.startswith(ALLOWED_PREFIX) and ".." not in f.split("/") and not os.path.isabs(f)
                               for f in files)


def repo_path(container_path: Optional[str]) -> Optional[str]:
    """/app/api_gateway/app/main.py (inside a container) -> patient/api_gateway/app/main.py."""
    if not container_path:
        return None
    p = container_path.replace("\\", "/")
    if p.startswith("/app/"):
        p = ALLOWED_PREFIX + p[len("/app/"):]
    p = p.lstrip("/")
    return p if p.startswith(ALLOWED_PREFIX) else None


def _commit_ok(repo: str, sha: Optional[str]) -> Optional[str]:
    if not sha or not re.fullmatch(r"[0-9a-fA-F]{7,40}", str(sha)):
        return None
    r = _git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    return r.stdout.strip() if r.returncode == 0 else None


def _rollback_patch(repo: str, sha: str) -> str:
    """The reverse of one commit, limited to patient/ (what `git revert` would change)."""
    r = _git(repo, "diff", sha, f"{sha}~1", "--", ALLOWED_PREFIX.rstrip("/"))
    return r.stdout if r.returncode == 0 else ""


def _subject(repo: str, sha: str) -> str:
    return _git(repo, "log", "-1", "--format=%s", sha).stdout.strip()


def crash_site(detail: Dict[str, Any]) -> Optional[Tuple[str, int]]:
    """(repo path, line) of the most frequent stack trace that lands in patient code."""
    logs = sorted((detail.get("evidence") or {}).get("logs") or [], key=lambda g: -(g.get("count") or 0))
    for g in logs:
        path, line = repo_path(g.get("error_file")), g.get("error_line")
        if path and isinstance(line, int) and g.get("exc_type"):
            return path, line
    return None


def plan(detail: Dict[str, Any], repo: str = REPO) -> Dict[str, Any]:
    """Decide which patch to use for this incident. Pure: changes nothing."""
    report = detail.get("report") or {}
    diagnosis = report.get("diagnosis") or {}
    fix = diagnosis.get("fix") or {}
    live_sha = _commit_ok(repo, report.get("live_sha") or (report.get("verification") or {}).get("sha"))
    base = {"fix_kind": fix.get("kind"), "action": fix.get("action") or fix.get("rationale"),
            "verified": (report.get("verification") or {}).get("status") == "verified", "live_sha": live_sha}

    diff = (fix.get("unified_diff") or "").strip("\n")
    if diff:
        files = patch_files(diff)
        if safe_paths(files):
            return {**base, "source": "doctor_patch", "diff": diff + "\n", "files": files, "commit": None,
                    "why": "It passed the test suite on a spare copy." if base["verified"] else
                           "It has not been verified by the tests."}

    candidates = {c.get("sha") for c in (detail.get("evidence") or {}).get("candidate_commits") or []}
    site = crash_site(detail)
    if site and live_sha:
        path, line = site
        r = _git(repo, "blame", "-L", f"{line},{line}", "--porcelain", live_sha, "--", path)
        sha = r.stdout.split()[0] if r.returncode == 0 and r.stdout else None
        if sha and sha in candidates:
            patch = _rollback_patch(repo, sha)
            if patch and safe_paths(patch_files(patch)):
                return {**base, "source": "crash_line", "diff": patch, "files": patch_files(patch), "commit": sha,
                        "commit_subject": _subject(repo, sha),
                        "why": f"The report has no ready-made patch. The stack trace crashes at {path}:{line}; "
                               f"that line was introduced by commit {sha[:7]}, one of this incident's candidate "
                               f"commits, so this rolls that commit back."}

    hyps = sorted(diagnosis.get("hypotheses") or [], key=lambda h: -(h.get("confidence") or 0))
    blamed = _commit_ok(repo, (hyps[0].get("suspected_commit") if hyps else None)
                        or (detail.get("incident") or {}).get("suspected_commit"))
    if blamed:
        patch = _rollback_patch(repo, blamed)
        if patch and safe_paths(patch_files(patch)):
            return {**base, "source": "blamed_commit", "diff": patch, "files": patch_files(patch), "commit": blamed,
                    "commit_subject": _subject(repo, blamed),
                    "why": f"The report has no ready-made patch. The doctor's top hypothesis blames commit "
                           f"{blamed[:7]}, so this rolls that commit back."}

    return {**base, "source": None, "diff": "", "files": [], "commit": None,
            "why": "This incident has no code change to apply"
                   + (f": the doctor proposed an action instead ({base['action']})." if base["action"] else ".")}


# ---------------------------------------------------------------- applying

def _write_patch(repo: str, incident_id: str, diff: str) -> str:
    os.makedirs(state_dir(repo), exist_ok=True)
    path = os.path.join(state_dir(repo), f"{incident_id}.patch")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(diff if diff.endswith("\n") else diff + "\n")
    return path


def _applies(repo: str, patch: str, reverse: bool = False) -> bool:
    args = ["apply", "--check", "--recount", "--whitespace=nowarn"] + (["-R"] if reverse else []) + [patch]
    return _git(repo, *args).returncode == 0


def _state_file(repo: str) -> str:
    return os.path.join(state_dir(repo), "applied.json")


def status(repo: str = REPO) -> Dict[str, Any]:
    try:
        with open(_state_file(repo), encoding="utf-8") as fh:
            applied = json.load(fh)
    except (OSError, ValueError):
        applied = None
    return {"applied": applied, "vscode": bool(find_vscode())}


def _preview(repo: str, p: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    """Copies of the first patched file before and after the fix, outside the repo."""
    path = p["files"][0]
    tmp = tempfile.mkdtemp(prefix="incident_doctor_fix_")
    if p["source"] == "doctor_patch":
        if not p["live_sha"]:
            return None
        before = _git(repo, "show", f"{p['live_sha']}:{path}")
        if before.returncode != 0:
            return None
        work = os.path.join(tmp, "work")
        os.makedirs(os.path.dirname(os.path.join(work, path)))
        with open(os.path.join(work, path), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(before.stdout)
        patch = os.path.join(tmp, "fix.patch")
        with open(patch, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(p["diff"])
        r = subprocess.run(["git", "apply", "--recount", "--whitespace=nowarn", patch], cwd=work,
                           capture_output=True, text=True)
        if r.returncode != 0:
            return None
        with open(os.path.join(work, path), encoding="utf-8") as fh:
            after_text = fh.read()
        before_text = before.stdout
    else:
        b, a = _git(repo, "show", f"{p['commit']}:{path}"), _git(repo, "show", f"{p['commit']}~1:{path}")
        if b.returncode != 0 or a.returncode != 0:
            return None
        before_text, after_text = b.stdout, a.stdout
    name = os.path.basename(path)
    out = []
    for label, text in (("buggy", before_text), ("fixed", after_text)):
        d = os.path.join(tmp, label)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        out.append(os.path.join(d, name))
    return out[0], out[1], tmp


def apply(incident_id: str, detail: Dict[str, Any], repo: str = REPO, launch: bool = True) -> Dict[str, Any]:
    """Apply the incident's fix to the working tree (or preview it) and open VS Code."""
    p = plan(detail, repo)
    out = {"incident_id": incident_id, "source": p["source"], "source_label": SOURCE_LABEL.get(p["source"]),
           "why": p["why"], "files": p["files"], "commit": p.get("commit"), "commit_subject": p.get("commit_subject"),
           "verified": p["verified"], "fix_kind": p["fix_kind"], "action": p["action"], "diff": p["diff"]}
    if not p["source"]:
        site = crash_site(detail)
        if site and os.path.exists(os.path.join(repo, site[0])):
            out.update(mode="none", opened=open_file(repo, site[0], site[1], launch), file=site[0], line=site[1],
                       message=p["why"] + f" VS Code is open at the crashing line, {site[0]}:{site[1]}.")
        else:
            out.update(mode="none", opened=False, message=p["why"])
        return out

    current = status(repo)["applied"]
    if current and current["incident_id"] != incident_id:
        undo(repo)  # one fix in the editor at a time
    patch = _write_patch(repo, incident_id, p["diff"])
    first, line = p["files"][0], first_changed_line(p["diff"])
    out.update(file=first, line=line, abs_file=os.path.join(repo, first).replace(os.sep, "/"))

    if _applies(repo, patch):
        before_dir = os.path.join(state_dir(repo), incident_id, "before")
        for f in p["files"]:
            src = os.path.join(repo, f)
            if os.path.exists(src):
                dst = os.path.join(before_dir, f)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
        r = _git(repo, "apply", "--recount", "--whitespace=nowarn", patch)
        if r.returncode != 0:
            out.update(mode="error", opened=False, message="git apply failed: " + (r.stderr or r.stdout)[-400:])
            return out
        with open(_state_file(repo), "w", encoding="utf-8") as fh:
            json.dump({"incident_id": incident_id, "patch": patch, "files": p["files"], "source": p["source"],
                       "applied_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, fh)
        before = os.path.join(before_dir, first)
        opened = open_diff(repo, before if os.path.exists(before) else None, os.path.join(repo, first), line, launch)
        out.update(mode="applied", opened=opened,
                   message=f"Applied to {', '.join(p['files'])} (not committed). Review the diff in VS Code.")
    elif _applies(repo, patch, reverse=True):
        out.update(mode="already", opened=open_file(repo, first, line, launch),
                   message=f"{first} already contains this change. VS Code is open at the line.")
    else:
        pv = _preview(repo, p)
        if pv:
            out.update(mode="preview", opened=open_diff(repo, pv[0], pv[1], line, launch, folder=False),
                       message="The bug is no longer in your working tree (the run already put the code back), "
                               "so VS Code shows the fix as a buggy / fixed comparison instead of editing files.")
        else:
            out.update(mode="error", opened=False,
                       message="The patch does not apply to the working tree and no preview could be built.")
    return out


def undo(repo: str = REPO) -> Dict[str, Any]:
    """Take an applied fix back out of the working tree. Safe to call when nothing is applied."""
    applied = status(repo)["applied"]
    if not applied:
        return {"undone": False, "message": "nothing applied"}
    how = "reversed the patch"
    r = _git(repo, "apply", "-R", "--recount", "--whitespace=nowarn", applied["patch"])
    if r.returncode != 0:
        # The files were edited further after the fix. Do not throw that work away: stash it.
        r = _git(repo, "stash", "push", "-m", f"incident-doctor fix {applied['incident_id']}", "--", *applied["files"])
        how = "stashed the edited files (git stash list)"
        if r.returncode != 0:
            return {"undone": False, "message": "could not undo: " + (r.stderr or r.stdout)[-300:]}
    try:
        os.remove(_state_file(repo))
    except OSError:
        pass
    return {"undone": True, "incident_id": applied["incident_id"], "files": applied["files"], "message": how}


# ---------------------------------------------------------------- VS Code

def find_vscode() -> Optional[str]:
    for name in ("code.cmd", "code"):
        hit = shutil.which(name)
        if hit:
            return hit
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", ""),
                 os.environ.get("ProgramFiles(x86)", "")):
        for sub in (("Programs", "Microsoft VS Code"), ("Microsoft VS Code",)):
            hit = os.path.join(base, *sub, "bin", "code.cmd") if base else ""
            if hit and os.path.exists(hit):
                return hit
    return None


def _run_code(args: List[str]) -> None:
    exe = find_vscode()
    if exe:
        subprocess.Popen([exe, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, cwd=REPO)


def open_file(repo: str, path: str, line: int, launch: bool = True) -> bool:
    if not launch or not find_vscode():
        return False
    _run_code([repo, "--goto", f"{os.path.join(repo, path)}:{line}"])
    return True


def open_diff(repo: str, before: Optional[str], after: str, line: int, launch: bool = True,
              folder: bool = True) -> bool:
    """Open the project window, then the red/green diff inside it."""
    if not launch or not find_vscode():
        return False
    if before is None:
        return open_file(repo, os.path.relpath(after, repo), line, launch)

    def go() -> None:
        if folder:
            _run_code([repo, "--goto", f"{after}:{line}"])
            time.sleep(2.5)  # let the window come up, so the diff opens in it and not in a new one
        _run_code(["--reuse-window", "--diff", before, after])
    threading.Thread(target=go, daemon=True).start()
    return True
