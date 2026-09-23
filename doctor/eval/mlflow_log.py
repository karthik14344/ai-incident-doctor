"""Log evaluation results to MLflow (REST API; the doctor adds no MLflow client).

One parent run per evaluation, one child run per (comparison, arm, model) with
its metrics per delivery type, and one grandchild per repeat so the spread is
visible in the MLflow UI. results.json and results.md are attached.
"""

import json
import os
import time
from typing import Any, Dict, List

import httpx

EXPERIMENT = "incident-doctor-evaluation"


def _uri() -> str:
    from app.settings import get
    uri = get("MLFLOW_TRACKING_URI")
    if not uri:
        raise RuntimeError("MLFLOW_TRACKING_URI not set")
    return uri.rstrip("/")


class Client:
    def __init__(self, uri: str):
        self.uri = uri
        self.http = httpx.Client(timeout=30, trust_env=False)

    def post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        r = self.http.post(f"{self.uri}/api/2.0/mlflow/{path}", json=body)
        r.raise_for_status()
        return r.json() if r.content else {}

    def experiment(self, name: str) -> str:
        r = self.http.get(f"{self.uri}/api/2.0/mlflow/experiments/get-by-name", params={"experiment_name": name})
        if r.status_code == 200:
            return r.json()["experiment"]["experiment_id"]
        return self.post("experiments/create", {"name": name})["experiment_id"]

    def run(self, exp: str, name: str, tags: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("runs/create", {"experiment_id": exp, "run_name": name, "start_time": int(time.time() * 1000),
                                         "tags": [{"key": k, "value": str(v)} for k, v in tags.items()]})["run"]["info"]

    def log(self, run_id: str, metrics: Dict[str, float], params: Dict[str, Any] = None) -> None:
        now = int(time.time() * 1000)
        self.post("runs/log-batch", {"run_id": run_id, "params": [{"key": k, "value": str(v)[:500]}
                                                                  for k, v in (params or {}).items()],
                                     "metrics": [{"key": k, "value": float(v), "timestamp": now, "step": 0}
                                                 for k, v in metrics.items() if v is not None]})

    def artifact(self, info: Dict[str, Any], name: str, content: bytes) -> None:
        prefix = info["artifact_uri"].split("mlflow-artifacts:/", 1)[-1].lstrip("/")
        self.http.put(f"{self.uri}/api/2.0/mlflow-artifacts/artifacts/{prefix}/{name}", content=content)

    def end(self, run_id: str) -> None:
        self.post("runs/update", {"run_id": run_id, "status": "FINISHED", "end_time": int(time.time() * 1000)})


def _flat(agg: Dict[str, Any], prefix: str) -> Dict[str, float]:
    out = {}
    for k, v in agg.items():
        if isinstance(v, dict) and v.get("mean") is not None:
            out[f"{prefix}{k}"] = v["mean"]
            out[f"{prefix}{k}.std"] = v.get("std", 0.0)
    return out


def log_results(results: Dict[str, Any], rows: List[Dict[str, Any]], out_dir: str) -> str:
    mlf = Client(_uri())
    exp = mlf.experiment(EXPERIMENT)
    parent = mlf.run(exp, f"eval-{results['generated']}", {"incidents": len(results["incidents"]),
                                                           "repeats": results["repeats"],
                                                           "primary_model": results["primary_model"]})
    base = results["baseline_most_recent_deploy"]
    mlf.log(parent["run_id"], {k: v for d, agg in base.items() for k, v in _flat(agg, f"baseline.{d}.").items()},
            {"replay_settings": json.dumps(results.get("replay_settings"))})
    for name in ("results.json", "results.md"):
        with open(os.path.join(out_dir, name), "rb") as fh:
            mlf.artifact(parent, name, fh.read())
    for key, by_del in results["groups"].items():
        comparison, arm, model = key.split("|")
        child = mlf.run(exp, key, {"mlflow.parentRunId": parent["run_id"], "comparison": comparison,
                                   "arm": arm, "model": model})
        mlf.log(child["run_id"], {k: v for d, agg in by_del.items() for k, v in _flat(agg, f"{d}.").items()},
                {"comparison": comparison, "arm": arm, "model": model})
        for rep in sorted({r["repeat"] for r in rows if f"{r['comparison']}|{r['arm']}|{r['model']}" == key}):
            reps = [r for r in rows if f"{r['comparison']}|{r['arm']}|{r['model']}" == key and r["repeat"] == rep]
            g = mlf.run(exp, f"{key}#rep{rep}", {"mlflow.parentRunId": child["run_id"], "repeat": rep})
            mlf.log(g["run_id"], {
                "acc_at_1": sum(r["score"]["acc_at_1"] for r in reps) / len(reps),
                "acc_at_3": sum(r["score"]["acc_at_3"] for r in reps) / len(reps),
                "class_correct": sum(r["score"]["class_correct"] for r in reps) / len(reps),
                "tokens": sum(r["score"]["prompt_tokens"] + r["score"]["completion_tokens"] for r in reps)})
            mlf.end(g["run_id"])
        mlf.end(child["run_id"])
    mlf.end(parent["run_id"])
    return parent["run_id"]
