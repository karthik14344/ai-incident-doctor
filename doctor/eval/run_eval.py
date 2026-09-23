"""The evaluation: one command, from recorded incidents, repeatably.

    python -m doctor.eval.run_eval                       # everything in doctor/eval/config.json
    python -m doctor.eval.run_eval --repeats 1 --only-arm logs_commits_incidents

Structure follows the patient's evaluation/runner.py: hold everything constant
except the one thing being compared. Every run replays a stored evidence
snapshot (the replay trigger) - nothing live is touched, so the app never has
to be broken again.

Comparisons
  baseline   "always blame the most recent deploy" (deterministic)
  ablation   logs_only vs logs_commits vs logs_commits_incidents, same model
  models     cloud (GLM, when DOCTOR_API_KEY is set) vs local llama3.2 vs a larger
             local model, same arm (logs_commits_incidents), same evidence
Each (incident, arm, model) is run `repeats` times with different seeds and the
spread across repeats is reported, not the best run.

Every number is reported separately per delivery type - push, environment,
data - because push faults are the easy case: the deploy record almost gives the
answer away. The environment numbers are the real score.

Outputs doctor/eval/results/<timestamp>/{runs.jsonl, results.json, results.md}
and one MLflow run per (comparison, arm, model) with per-repeat child metrics.
"""

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from typing import Any, Dict, List, Optional

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
DOCTOR_DIR = os.path.dirname(EVAL_DIR)
REPO = os.path.dirname(DOCTOR_DIR)
sys.path.insert(0, DOCTOR_DIR)

from app import reasoner  # noqa: E402
from app import main as doctor_main  # noqa: E402
from app.indexes import incident_index  # noqa: E402
from app.retrieval import rank_commits  # noqa: E402
from app.settings import SETTINGS, ProviderConfig, doctor_ollama_url, get  # noqa: E402

sys.path.insert(0, EVAL_DIR)
from scoring import most_recent_deploy_baseline, score  # noqa: E402

DELIVERIES = ["push", "environment", "data"]


# ---------------------------------------------------------------- inputs

def load_incidents(root: str) -> List[Dict[str, Any]]:
    out = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        paths = {k: os.path.join(d, f"{k}.json") for k in ("bundle", "ground_truth", "timeline")}
        if not all(os.path.exists(p) for p in (paths["bundle"], paths["ground_truth"])):
            continue
        inc = {k: json.load(open(p, encoding="utf-8")) for k, p in paths.items() if os.path.exists(p)}
        inc["name"] = name
        out.append(inc)
    return sorted(out, key=lambda i: i["bundle"].get("t_alert", 0))


def provider_for(spec: Dict[str, str]) -> Optional[ProviderConfig]:
    provider, model = spec["provider"], spec["model"]
    if provider == "ollama":
        return ProviderConfig("ollama", model, base_url=doctor_ollama_url())
    key = get("DOCTOR_API_KEY") if (get("DOCTOR_PROVIDER") or "").lower() == provider else get(
        f"{provider.upper()}_API_KEY")
    if not key:
        return None
    from app.settings import DEFAULT_PRICES, PROVIDER_BASE_URLS
    pin, pout = DEFAULT_PRICES.get(provider, (0, 0))
    return ProviderConfig(provider, model, api_key=key,
                          base_url=get("DOCTOR_BASE_URL") or PROVIDER_BASE_URLS.get(provider),
                          price_in=pin, price_out=pout)


def build_past_incident_index(incidents: List[Dict[str, Any]], name: str) -> None:
    """Resolved past incidents = the ground truth of the OTHER recorded incidents.
    retrieval.past_incidents only returns incidents earlier than the one being
    diagnosed, so this is a chronological leave-future-out design."""
    idx = incident_index(SETTINGS, name)
    for inc in incidents:
        truth = inc["ground_truth"]
        res = {"root_cause": truth["true_cause"], "incident_class": truth["incident_class"],
               "fix": truth["expected_fix"], "guilty_commit": truth.get("guilty_commit")}
        idx.add([inc["bundle"]["id"]], [doctor_main.resolution_text(inc["bundle"]["id"], inc["bundle"], res)],
                [{"t_alert": inc["bundle"].get("t_alert", 0), "incident_class": truth["incident_class"]}])


# ---------------------------------------------------------------- aggregation

METRICS = ["acc_at_1", "acc_at_3", "class_correct", "class_correct_lenient", "component_at_1", "valid_output"]


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 3) if xs else None


def aggregate(rows: List[Dict[str, Any]], repeats: int) -> Dict[str, Any]:
    """Per-repeat means over incidents, then mean and spread across repeats."""
    out: Dict[str, Any] = {"n_runs": len(rows), "n_incidents": len({r["incident"] for r in rows})}
    by_rep: Dict[int, List[Dict[str, Any]]] = {}
    for r in rows:
        by_rep.setdefault(r["repeat"], []).append(r)

    def spread(fn):
        vals = [fn(rs) for rs in by_rep.values()]
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        return {"mean": round(statistics.fmean(vals), 3), "min": round(min(vals), 3), "max": round(max(vals), 3),
                "std": round(statistics.pstdev(vals), 3) if len(vals) > 1 else 0.0, "repeats": len(vals)}

    for m in METRICS:
        out[m] = spread(lambda rs, m=m: _mean([float(bool(r["score"][m])) for r in rs]))
    out["false_attribution"] = spread(lambda rs: _mean(
        [float(bool(r["score"]["false_attribution"])) for r in rs if "false_attribution" in r["score"]]))
    out["guilty_in_retrieved"] = spread(lambda rs: _mean(
        [float(bool(r["score"]["guilty_in_retrieved"])) for r in rs if "guilty_in_retrieved" in r["score"]]))
    out["guilty_in_time_filter"] = spread(lambda rs: _mean(
        [float(bool(r["score"]["guilty_in_time_filter"])) for r in rs if "guilty_in_time_filter" in r["score"]]))
    code_rows = lambda rs: [r for r in rs if r["truth"].get("acceptance_test")]  # noqa: E731
    out["fix_verified"] = spread(lambda rs: _mean([float(r["score"]["fix_verified"]) for r in code_rows(rs)]))
    out["fix_acceptance_passed"] = spread(
        lambda rs: _mean([float(r["score"]["fix_acceptance_passed"]) for r in code_rows(rs)]))
    out["reasoning_s"] = spread(lambda rs: _mean([r["score"]["reasoning_s"] for r in rs]))
    out["tokens_per_incident"] = spread(lambda rs: _mean(
        [r["score"]["prompt_tokens"] + r["score"]["completion_tokens"] for r in rs]))
    out["cost_usd_per_incident"] = spread(lambda rs: _mean([r["score"]["cost_usd"] for r in rs]))
    out["constraint_violations_per_run"] = spread(lambda rs: _mean([r["score"]["constraint_violations"] for r in rs]))
    return out


def by_delivery(rows, repeats):
    out = {"all": aggregate(rows, repeats)}
    for d in DELIVERIES:
        sub = [r for r in rows if r["truth"]["delivery"] == d]
        if sub:
            out[d] = aggregate(sub, repeats)
    return out


# ---------------------------------------------------------------- the run

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(EVAL_DIR, "config.json"))
    ap.add_argument("--incidents", default=None)
    ap.add_argument("--repeats", type=int, default=None)
    ap.add_argument("--only-arm", default=None)
    ap.add_argument("--only-model", default=None)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--baseline-only", action="store_true",
                    help="only the model-free parts: the most-recent-deploy baseline, retrieval, live timings")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    cfg = json.load(open(args.config, encoding="utf-8"))
    repeats = args.repeats or cfg["repeats"]
    inc_dir = args.incidents or os.path.join(REPO, cfg["incidents_dir"])
    incidents = load_incidents(inc_dir)
    if not incidents:
        print(f"no recorded incidents under {inc_dir}")
        return 1
    for k, v in cfg.get("replay_settings", {}).items():
        setattr(SETTINGS, k, v)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out or os.path.join(EVAL_DIR, "results", stamp)
    os.makedirs(out_dir, exist_ok=True)
    digest = hashlib.sha1("".join(i["bundle"]["id"] for i in incidents).encode()).hexdigest()[:8]
    past_index = f"eval_incidents_{digest}"
    build_past_incident_index(incidents, past_index)

    # which model does the ablation use: the cloud primary if it has a key, else the local stand-in
    primary = provider_for(cfg["primary"]) or provider_for(cfg["local_primary"])
    primary_is_cloud = primary is not None and primary.provider != "ollama"
    plan = []
    for arm in cfg["arms"]:
        plan.append(("ablation", arm, primary))
    for spec in cfg["models"]:
        p = provider_for(spec)
        plan.append(("models", "logs_commits_incidents", p if p else ProviderConfig(spec["provider"], spec["model"])))
    if args.only_arm:
        plan = [p for p in plan if p[1] == args.only_arm]
    if args.only_model:
        plan = [p for p in plan if p[2].model == args.only_model]
    if args.baseline_only:
        plan = []

    runs_path = os.path.join(out_dir, "runs.jsonl")
    rows: List[Dict[str, Any]] = []
    cache: Dict[str, Any] = {}
    skipped = []
    done_keys = {}

    # deterministic baseline and retrieval-only numbers
    baseline_rows, retrieval_rows = [], []
    for inc in incidents:
        truth, bundle = inc["ground_truth"], inc["bundle"]
        diag = most_recent_deploy_baseline(bundle)
        s = score(diag, {"status": "ok", "retrieval": {}}, truth)
        s["guilty_in_latest_deploy"] = bool(truth.get("guilty_commit")) and truth["guilty_commit"] in diag["_deploy_commits"]
        for k in ("guilty_in_retrieved", "guilty_in_time_filter", "guilty_rank", "time_filter_size"):
            s.pop(k, None)  # the baseline has no retrieval step: not applicable, not zero
        baseline_rows.append({"incident": inc["name"], "repeat": 0, "truth": truth, "score": s})
        ranked = rank_commits(bundle, SETTINGS)
        retrieval_rows.append({"incident": inc["name"], "delivery": truth["delivery"],
                               "guilty": truth.get("guilty_commit"),
                               "time_filter_size": len(ranked["time_filtered"]),
                               "in_time_filter": truth.get("guilty_commit") in ranked["time_filtered"],
                               "in_top5": truth.get("guilty_commit") in [r["sha"] for r in ranked["ranked"]],
                               "rank": ([r["sha"] for r in ranked["all_ranked"]].index(truth["guilty_commit"]) + 1
                                        if truth.get("guilty_commit") in ranked["time_filtered"] else None)})

    for comparison, arm, provider in plan:
        if provider is None or (provider.provider != "ollama" and not provider.api_key):
            skipped.append({"comparison": comparison, "arm": arm, "model": provider.label if provider else "?",
                            "reason": "no API key configured"})
            continue
        for inc in incidents:
            truth = inc["ground_truth"]
            accept = [os.path.join(REPO, truth["acceptance_test"])] if truth.get("acceptance_test") else None
            for rep in range(repeats):
                key = (arm, provider.label, inc["name"], rep)
                if key in done_keys:  # the ablation's full arm doubles as a model-comparison row
                    rows.append({**done_keys[key], "comparison": comparison})
                    continue
                report = reasoner.diagnose(inc["bundle"], arm=arm, providers=[provider],
                                           verify_fix=not args.no_verify and cfg.get("verify", True),
                                           acceptance_tests=accept, incident_index=past_index,
                                           verification_cache=cache, seed=1000 + rep)
                s = score(report.get("diagnosis"), report, truth)
                row = {"comparison": comparison, "arm": arm, "model": provider.label, "incident": inc["name"],
                       "repeat": rep, "truth": truth, "score": s,
                       "top": ((report.get("diagnosis") or {}).get("hypotheses") or [{}])[0],
                       "incident_class": (report.get("diagnosis") or {}).get("incident_class"),
                       "status": report.get("status"), "error": report.get("error")}
                done_keys[key] = row
                rows.append(row)
                with open(runs_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({**row, "report": report}, default=str) + "\n")
                print(f"{comparison:<8} {arm:<24} {provider.label:<18} {inc['name']:<34} rep{rep} "
                      f"acc@1={int(s['acc_at_1'])} class={int(s['class_correct'])} "
                      f"blame={'-' if not s['blamed_a_commit'] else 'Y'} {s['reasoning_s']}s", flush=True)

    # live timings from the recorded runs
    live = []
    for inc in incidents:
        t = inc.get("timeline") or {}
        live.append({"incident": inc["name"], "delivery": inc["ground_truth"]["delivery"],
                     "unnoticed_s": t.get("unnoticed_s"), "doctor_s": t.get("doctor_s"),
                     "first_alert": (t.get("first_alert") or {}).get("alertname"),
                     "expected_alert": t.get("expected_alert")})

    results = {"generated": stamp, "incidents": [i["name"] for i in incidents], "repeats": repeats,
               "primary_model": primary.label if primary else None, "primary_is_cloud": primary_is_cloud,
               "replay_settings": cfg.get("replay_settings"), "skipped": skipped,
               "baseline_most_recent_deploy": by_delivery(baseline_rows, 1),
               "baseline_deploy_hit": {d: _mean([float(r["score"]["guilty_in_latest_deploy"]) for r in baseline_rows
                                                 if r["truth"]["delivery"] == d and r["truth"].get("guilty_commit")])
                                       for d in DELIVERIES},
               "retrieval": retrieval_rows, "live_timings": live, "groups": {}}
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(f"{r['comparison']}|{r['arm']}|{r['model']}", []).append(r)
    for k, rs in groups.items():
        results["groups"][k] = by_delivery(rs, repeats)
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1, default=str)

    from report_tables import write_markdown
    md = write_markdown(results)
    with open(os.path.join(out_dir, "results.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    try:
        from mlflow_log import log_results
        log_results(results, rows, out_dir)
    except Exception as exc:  # results stand without MLflow
        print(f"MLflow logging skipped: {exc}")
    print(f"\nresults: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
