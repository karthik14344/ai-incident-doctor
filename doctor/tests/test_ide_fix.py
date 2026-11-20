"""Fix in VS Code (faults/ide_fix.py): which patch is chosen, and how it lands.

Each test builds a tiny git repository with a base commit and a guilty commit,
so nothing here touches the real working tree or launches VS Code.
"""

import difflib
import os
import subprocess

import pytest

from faults import ide_fix

GOOD = "def title(q):\n    text = q.strip()\n    return text[:30]\n\n\ndef other():\n    return 1\n"
BAD = GOOD.replace("return text[:30]", "return txt[:30]")
PATH = "patient/api_gateway/app/main.py"


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.com",
                        "-c", "core.autocrlf=false", *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def write(repo, text):
    full = os.path.join(repo, PATH)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read(repo):
    with open(os.path.join(repo, PATH), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture
def repo(tmp_path):
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    git(repo, "init", "-q")
    git(repo, "config", "core.autocrlf", "false")  # the same answer on every machine
    write(repo, GOOD)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    write(repo, BAD)
    git(repo, "commit", "-q", "-am", "Tidy the title helper")
    return repo


def detail(repo, diff="", suspected=None, crash_line=None, candidates=True):
    guilty = git(repo, "rev-parse", "HEAD")
    logs = [{"count": 9, "exc_type": "NameError", "error_file": "/app/api_gateway/app/main.py",
             "error_line": crash_line}] if crash_line else []
    return {"incident": {}, "report": {"live_sha": guilty, "verification": {"status": "unverified"}, "diagnosis": {
                "hypotheses": [{"confidence": 0.9, "cause": "x", "suspected_commit": suspected}],
                "fix": {"kind": "code_diff" if diff else "action", "action": "restart the gateway",
                        "unified_diff": diff}}},
            "evidence": {"logs": logs, "candidate_commits": [{"sha": guilty}] if candidates else []}}, guilty


def doctor_diff():
    return "".join(difflib.unified_diff(BAD.splitlines(keepends=True), GOOD.splitlines(keepends=True),
                                        fromfile=f"a/{PATH}", tofile=f"b/{PATH}"))


def test_doctor_patch_is_applied_and_can_be_undone(repo):
    d, _ = detail(repo, diff=doctor_diff())
    out = ide_fix.apply("inc_1", d, repo, launch=False)
    assert (out["source"], out["mode"], out["files"], out["line"]) == ("doctor_patch", "applied", [PATH], 3)
    assert read(repo) == GOOD
    assert git(repo, "log", "--oneline").count("\n") == 1  # nothing was committed
    assert ide_fix.status(repo)["applied"]["incident_id"] == "inc_1"
    assert ide_fix.undo(repo)["undone"] is True
    assert read(repo) == BAD and ide_fix.status(repo)["applied"] is None
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == ""


def test_applying_twice_reports_already_applied(repo):
    d, _ = detail(repo, diff=doctor_diff())
    ide_fix.apply("inc_1", d, repo, launch=False)
    assert ide_fix.apply("inc_1", d, repo, launch=False)["mode"] == "already"
    assert read(repo) == GOOD


def test_without_a_patch_the_crashing_line_names_the_commit_to_roll_back(repo):
    d, guilty = detail(repo, crash_line=3)
    out = ide_fix.apply("inc_2", d, repo, launch=False)
    assert (out["source"], out["mode"], out["commit"]) == ("crash_line", "applied", guilty)
    assert read(repo) == GOOD


def test_crashing_line_from_an_old_commit_is_not_rolled_back(repo):
    # Line 2 came from the base commit, which is not a candidate for this incident.
    d, _ = detail(repo, crash_line=2)
    out = ide_fix.apply("inc_3", d, repo, launch=False)
    assert (out["source"], out["mode"]) == (None, "none")
    assert read(repo) == BAD


def test_falls_back_to_the_commit_the_doctor_blamed(repo):
    d, guilty = detail(repo, suspected="deadbeef")
    assert ide_fix.plan(d, repo)["source"] is None  # an unknown sha is ignored
    d, guilty = detail(repo, suspected=guilty[:10])
    out = ide_fix.apply("inc_4", d, repo, launch=False)
    assert (out["source"], out["mode"]) == ("blamed_commit", "applied")
    assert read(repo) == GOOD


def test_bug_already_reverted_gives_a_preview_and_edits_nothing(repo):
    d, guilty = detail(repo, diff=doctor_diff())
    git(repo, "revert", "--no-edit", guilty)
    out = ide_fix.apply("inc_5", d, repo, launch=False)
    assert out["mode"] == "already"  # the revert is the same change as the fix
    d2, _ = detail(repo, crash_line=3)
    d2["report"]["live_sha"] = guilty
    d2["evidence"]["candidate_commits"] = [{"sha": guilty}]
    write(repo, GOOD.replace("return 1", "return 2"))  # the tree moved on
    git(repo, "commit", "-q", "-am", "later change")
    write(repo, GOOD.replace("text = q.strip()", "text = q.strip().lower()").replace("return 1", "return 2"))
    git(repo, "commit", "-q", "-am", "rewrite the fixed line's neighbour")
    plan = ide_fix.plan(d2, repo)
    assert plan["source"] == "crash_line"
    buggy, fixed, _ = ide_fix._preview(repo, plan)
    assert open(buggy).read() == BAD and open(fixed).read() == GOOD


def test_patches_outside_patient_are_refused(repo):
    evil = doctor_diff().replace(PATH, "deploy/deploy.py")
    d, _ = detail(repo, diff=evil)
    assert ide_fix.plan(d, repo)["source"] is None
    d, _ = detail(repo, diff=doctor_diff().replace(PATH, "patient/../.env"))
    assert ide_fix.plan(d, repo)["source"] is None


def test_undo_stashes_instead_of_discarding_later_edits(repo):
    d, _ = detail(repo, diff=doctor_diff())
    ide_fix.apply("inc_6", d, repo, launch=False)
    write(repo, GOOD.replace("return text[:30]", "return text[:60]"))  # edited after the fix
    out = ide_fix.undo(repo)
    assert out["undone"] is True and "stash" in out["message"]
    assert read(repo) == BAD and "incident-doctor fix inc_6" in git(repo, "stash", "list")


def test_a_held_run_ends_when_the_page_presses_finish(tmp_path, monkeypatch):
    from faults import run_fault
    monkeypatch.setattr(run_fault, "REPO", str(tmp_path))  # nothing applied there: undo is a no-op
    (tmp_path / "release").write_text("")
    timeline = {}
    run_fault.hold_for_fix(str(tmp_path), 60, timeline)
    assert timeline["hold_released"] == "page"
