"""Run one fault end to end, unattended, and record everything.

    python -m faults.run_fault f1_embed_timeout --variant guilty_last
    python -m faults.run_fault f2_capacity

push faults:
  1. land distractors and the guilty commit, `git push` to the pipeline remote
     (verify -> SHA-tagged deploy -> deploy record -> Grafana annotation)
     - variant guilty_last:    D D | push ; G D | push      (latest deploy holds G)
     - variant guilty_earlier: G D | push ; D D | push      (latest deploy is innocent)
  2. normal background traffic runs throughout (faults.background_traffic);
     fault-specific load starts now. Symptoms appear.
  3. Prometheus fires -> Alertmanager -> alert-sink -> doctor /incident.
     THIS SCRIPT NEVER CALLS THE DOCTOR; it only waits for the finished report.
  4. revert: `git revert` the guilty commit and push; wait for the alert to clear.
environment / data faults: the same, minus the commits - a recorded function
applies the break and a recorded function undoes it.

Recorded under runtime/fault-runs/<run_id>/: ground_truth.json (with the real
guilty SHA / KB version), timeline.json (inject -> alert = time unnoticed,
alert -> report = time the doctor took), the evidence snapshot bundle.json,
and the doctor's live report.
"""

import argparse
import os
import threading
import time
from typing import Any, Dict, Optional

import httpx

from faults import distractors
from faults.catalog import FAULTS, Fault
from faults.common import (RUNS_DIR, REPO, Load, commit, compose, export_incident, git, iso, log,
                           parse_ts, push_and_deploy, setting, wait_alert, wait_report, write_json)


# ---------------------------------------------------------------- the noisy neighbour

class Neighbour:
    """Someone else using the shared Ollama: long generations alternating between
    two bigger models, as the Model Comparison page does. Loading them evicts
    nomic-embed-text, so embedding calls wait for the GPU."""

    def __init__(self, models=("llama3", "mistral")):
        self.models = models
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.calls = 0

    def _run(self):
        base = setting("OLLAMA_BASE_URL").rstrip("/")
        i = 0
        while not self.stop_event.is_set():
            model = self.models[i % len(self.models)]
            try:
                httpx.post(f"{base}/api/generate", timeout=600, trust_env=False, json={
                    "model": model, "prompt": "Write a detailed essay on the history of university libraries.",
                    "stream": False, "keep_alive": "30s", "options": {"num_predict": 400}})
                self.calls += 1
            except Exception:
                time.sleep(5)
            i += 1

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()


# ---------------------------------------------------------------- breaks

def apply_edits(fault: Fault) -> list:
    paths = []
    for path, old, new in fault.edits:
        full = os.path.join(REPO, path)
        text = open(full, encoding="utf-8").read()
        if old not in text:
            raise RuntimeError(f"{fault.id}: the code to change is not in {path} (already applied?)")
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text.replace(old, new, 1))
        paths.append(path)
    return sorted(set(paths))


def inject_push(fault: Fault, variant: str, timeline: Dict[str, Any]) -> Dict[str, Any]:
    prefer = fault.distractor_paths
    out: Dict[str, Any] = {"distractors": []}
    if variant == "guilty_last":
        out["distractors"] += distractors.land(2, prefer)
        push_and_deploy("distractors", timeline)
        timeline["t_break"] = iso()
        out["guilty_commit"] = commit(apply_edits(fault), fault.message)
        log(f"guilty {out['guilty_commit'][:7]}: {fault.message}")
        out["distractors"] += distractors.land(1, prefer)
        out["guilty_deploy"] = push_and_deploy("guilty", timeline)["short_sha"]
    else:
        timeline["t_break"] = iso()
        out["guilty_commit"] = commit(apply_edits(fault), fault.message)
        log(f"guilty {out['guilty_commit'][:7]}: {fault.message}")
        out["distractors"] += distractors.land(1, prefer)
        out["guilty_deploy"] = push_and_deploy("guilty", timeline)["short_sha"]
        out["distractors"] += distractors.land(2, prefer)
        push_and_deploy("distractors-after", timeline)
    return out


def revert_push(guilty: str, timeline: Dict[str, Any]) -> None:
    git("revert", "--no-edit", guilty)
    push_and_deploy("revert", timeline)


def kb_swap(kb_dir: Optional[str], force: bool = False) -> str:
    """Load a knowledge-base version into the live index with kb-loader (data change)."""
    compose("stop", "chroma")
    extra = {"KB_DIR": kb_dir} if kb_dir else {}
    cmd = ["run", "--rm", "kb-loader", "python", "-m", "kb.load_kb", "--kb", "/kb", "--chroma-dir", "/chroma-data",
           "--docs-dir", "/app/storage/documents", "--log", "/runtime/kb_loads.jsonl"] + (["--force"] if force else [])
    out = compose(*cmd, extra_env=extra)
    compose("start", "chroma")
    return out.strip().splitlines()[-1] if out.strip() else ""


def inject_environment(fault: Fault, timeline: Dict[str, Any]) -> Dict[str, Any]:
    timeline["t_break"] = iso()
    if fault.id == "f3_retrieval_down":
        compose("stop", "retrieval")
    elif fault.id == "f3b_retrieval_bad_address":
        compose("up", "-d", "--no-deps", "gateway",
                extra_env={"RETRIEVAL_SERVICE_URL_OVERRIDE": "http://retrieval-replica:8002"})
    elif fault.id == "f7_kb_missing_docs":
        partial = os.path.join(REPO, "runtime", "kb-partial")
        if not os.path.exists(os.path.join(partial, "manifest.json")):
            raise RuntimeError("build the partial KB first (see faults/README.md)")
        import json
        timeline["guilty_kb_version"] = json.load(open(os.path.join(partial, "manifest.json")))["kb_version"]
        timeline["kb_load"] = kb_swap("./runtime/kb-partial")
    log(f"{fault.id}: break applied")
    return {}


def revert_environment(fault: Fault) -> None:
    if fault.id == "f3_retrieval_down":
        compose("start", "retrieval")
    elif fault.id == "f3b_retrieval_bad_address":
        compose("up", "-d", "--no-deps", "gateway")
    elif fault.id == "f7_kb_missing_docs":
        kb_swap(None, force=True)


# ---------------------------------------------------------------- the human fallback

def file_ticket(fault: Fault, timeline: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A person reporting what they see. Not a deploy and not a push: the hard rule
    (DECISIONS D-42) is that changes never wake the doctor; symptoms do."""
    from faults.catalog import TICKET_TEXT
    from faults.common import doctor_url, http

    minutes = max(1, round((time.time() - parse_ts(timeline["t_break"])) / 60))
    body = {"text": TICKET_TEXT.get(fault.id, "The assistant is not working properly."),
            "since": f"about {minutes} minutes ago"}
    try:
        out = http(f"{doctor_url()}/ticket", "POST", body)
    except Exception as exc:
        log(f"ticket failed: {exc}")
        return None
    timeline["ticket_filed_at"] = iso()
    timeline["ticket"] = {**body, "response": out}
    timeline["trigger"] = "ticket"
    return out if out and out.get("incident_id") else None


def wait_report_id(incident_id: str, timeout: float = 1500) -> Optional[Dict[str, Any]]:
    from faults.common import doctor_url, http

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            detail = http(f"{doctor_url()}/api/incidents/{incident_id}")
            status = (detail.get("incident") or {}).get("status")
            if status in ("ok", "failed", "interrupted"):
                summary = next((i for i in http(f"{doctor_url()}/api/incidents") if i["id"] == incident_id), {})
                return {"summary": summary, "detail": detail}
        except Exception:
            pass
        time.sleep(10)
    return None


# ---------------------------------------------------------------- the run

def wait_resolved(first_alert: Dict[str, Any], timeout: float = 900) -> Optional[str]:
    from faults.common import alerts_since
    deadline = time.time() + timeout
    since = first_alert.get("received_at") or iso()
    while time.time() < deadline:
        for a in alerts_since(since):
            if a.get("fingerprint") == first_alert.get("fingerprint") and a.get("status") == "resolved":
                return a.get("received_at")
        time.sleep(10)
    return None


def run(fault_id: str, variant: str = "guilty_last", label: Optional[str] = None) -> str:
    fault = FAULTS[fault_id]
    run_id = f"{fault_id}-{label or time.strftime('%m%d%H%M')}"
    run_dir = os.path.join(RUNS_DIR, run_id)
    timeline: Dict[str, Any] = {"run_id": run_id, "fault_id": fault_id, "delivery": fault.delivery,
                                "variant": variant if fault.delivery == "push" else None, "started": iso(),
                                "trigger": "alert"}
    truth = {**fault.ground_truth(), "run_id": run_id, "guilty_commit": None, "guilty_kb_version": None}
    write_json(os.path.join(run_dir, "timeline.json"), timeline)
    log(f"=== {run_id}: {fault.name} ({fault.delivery})")

    if git("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("working tree is dirty; commit or stash first")

    injected: Dict[str, Any] = {}
    if fault.delivery == "push":
        injected = inject_push(fault, variant, timeline)
        truth["guilty_commit"] = injected["guilty_commit"]
        truth["guilty_deploy"] = injected["guilty_deploy"]
        truth["distractor_commits"] = [d["sha"] for d in injected["distractors"]]
    else:
        inject_environment(fault, timeline)
        truth["guilty_kb_version"] = timeline.get("guilty_kb_version")
    write_json(os.path.join(run_dir, "timeline.json"), timeline)

    neighbour = load = alert = None
    try:
        neighbour = Neighbour().start() if fault.neighbour else None
        load = Load(**fault.load).start() if fault.load else None
        timeline["load"] = fault.load
        timeline["neighbour"] = bool(neighbour)

        alert = wait_alert(timeline["t_break"], timeout=fault.alert_timeout_s)
        if alert:
            timeline["first_alert"] = {"alertname": alert["alertname"], "startsAt": alert["startsAt"],
                                       "received_at": alert["received_at"], "labels": alert.get("labels")}
            timeline["t_alert"] = alert["startsAt"]
            timeline["unnoticed_s"] = round(parse_ts(alert["startsAt"]) - parse_ts(timeline["t_break"]), 1)
            timeline["expected_alert"] = alert["alertname"] in fault.expected_alerts
            log(f"alert {alert['alertname']} after {timeline['unnoticed_s']}s")
            report = wait_report(alert)
            if report:
                inc = report["summary"]
                timeline["incident_id"] = inc["id"]
                meta = report["detail"].get("incident") or {}
                timeline["t_report"] = meta.get("report_finished")
                timeline["doctor_s"] = round(parse_ts(meta["report_finished"]) - parse_ts(alert["startsAt"]), 1) \
                    if meta.get("report_finished") else None
                timeline["joined_alerts"] = meta.get("joined_alerts", [])
                log(f"doctor report {inc['id']}: {inc['incident_class']} / {(inc.get('top_cause') or '')[:80]} "
                    f"({timeline['doctor_s']}s after the alert)")
                export_incident(inc["id"], run_dir)
            else:
                log("no doctor report within the timeout")
        else:
            # Monitoring missed it (or the fault did not reproduce). A user notices
            # and files a ticket in symptom terms - the doctor has to find the time
            # window itself. Recorded as trigger=ticket, monitoring_missed=True.
            timeline["monitoring_missed"] = True
            log("NO ALERT within the timeout - filing a user ticket")
            filed = file_ticket(fault, timeline)
            if filed:
                report = wait_report_id(filed["incident_id"])
                if report:
                    meta = report["detail"].get("incident") or {}
                    timeline["incident_id"] = filed["incident_id"]
                    timeline["t_report"] = meta.get("report_finished")
                    timeline["doctor_s"] = round(parse_ts(meta["report_finished"]) - parse_ts(timeline["ticket_filed_at"]), 1)                         if meta.get("report_finished") else None
                    inc = report["summary"]
                    log(f"doctor ticket report {inc['id']}: {inc['incident_class']} / {(inc.get('top_cause') or '')[:80]} "
                        f"({timeline['doctor_s']}s after the ticket)")
                    export_incident(inc["id"], run_dir)

        if neighbour:
            neighbour.stop()
            timeline["neighbour_calls"] = neighbour.calls
        if load:
            timeline["load_summary"] = load.join()

    except Exception as exc:  # whatever went wrong while observing, the break is always reverted
        timeline["observe_error"] = f"{type(exc).__name__}: {exc}"
        log(f"observation failed: {timeline['observe_error']}")
        if neighbour:
            neighbour.stop()

    timeline["t_revert_start"] = iso()
    if fault.delivery == "push":
        revert_push(injected["guilty_commit"], timeline)
    else:
        revert_environment(fault)
    timeline["t_reverted"] = iso()
    if alert:
        timeline["t_alert_resolved"] = wait_resolved(alert)
    timeline["finished"] = iso()
    write_json(os.path.join(run_dir, "timeline.json"), timeline)
    write_json(os.path.join(run_dir, "ground_truth.json"), truth)
    log(f"=== {run_id} done")
    return run_dir


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fault", choices=sorted(FAULTS))
    ap.add_argument("--variant", choices=["guilty_last", "guilty_earlier"], default="guilty_last")
    ap.add_argument("--label")
    args = ap.parse_args()
    run(args.fault, args.variant, args.label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

