"""Record evaluation runs in MLflow as well as in SQLite/JSON.

The harness (runner.py) already produces accuracy, latency and resource figures
per model. This logs them as an MLflow experiment - one parent run per
evaluation, one child run per model - with the full report attached as an
artifact, so runs can be compared side by side in the MLflow UI.

It talks to the MLflow REST API directly with httpx, so the service images need
no extra dependency. Active only when MLFLOW_TRACKING_URI is set; a failure to
log never fails the evaluation itself.
"""

import json
import time
from typing import Any, Dict, List, Optional

import httpx

from common import config

EXPERIMENT = "knowledgeai-model-evaluation"


class MlflowRest:
    def __init__(self, uri: str):
        self.uri = uri.rstrip("/")
        self.client = httpx.Client(timeout=30, trust_env=False)

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        r = self.client.post(f"{self.uri}/api/2.0/mlflow/{path}", json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"MLflow {path}: HTTP {r.status_code} {r.text[:200]}")
        return r.json() if r.content else {}

    def experiment_id(self, name: str) -> str:
        r = self.client.get(f"{self.uri}/api/2.0/mlflow/experiments/get-by-name", params={"experiment_name": name})
        if r.status_code == 200:
            return r.json()["experiment"]["experiment_id"]
        return self._post("experiments/create", {"name": name})["experiment_id"]

    def start_run(self, experiment_id: str, name: str, tags: Dict[str, str]) -> Dict[str, Any]:
        body = {"experiment_id": experiment_id, "run_name": name, "start_time": int(time.time() * 1000),
                "tags": [{"key": k, "value": str(v)} for k, v in tags.items()]}
        return self._post("runs/create", body)["run"]["info"]

    def log_batch(self, run_id: str, params: Dict[str, Any], metrics: Dict[str, float]) -> None:
        now = int(time.time() * 1000)
        items = list(metrics.items())
        # The API caps a batch at 1000 metrics and 100 params.
        for i in range(0, max(len(items), 1), 900):
            body = {"run_id": run_id,
                    "metrics": [{"key": k, "value": float(v), "timestamp": now, "step": 0}
                                for k, v in items[i:i + 900]],
                    "params": ([{"key": k, "value": str(v)[:500]} for k, v in list(params.items())[:100]]
                               if i == 0 else [])}
            self._post("runs/log-batch", body)

    def log_artifact(self, run_info: Dict[str, Any], name: str, content: bytes) -> None:
        # Runs on a server started with --serve-artifacts have artifact URIs of
        # the form mlflow-artifacts:/<experiment>/<run>/artifacts.
        prefix = run_info["artifact_uri"].split("mlflow-artifacts:/", 1)[-1].lstrip("/")
        r = self.client.put(f"{self.uri}/api/2.0/mlflow-artifacts/artifacts/{prefix}/{name}", content=content)
        if r.status_code >= 400:
            raise RuntimeError(f"artifact upload: HTTP {r.status_code}")

    def end_run(self, run_id: str, status: str = "FINISHED") -> None:
        self._post("runs/update", {"run_id": run_id, "status": status, "end_time": int(time.time() * 1000)})


def flatten_numbers(row: Dict[str, Any], prefix: str = "") -> Dict[str, float]:
    """Numeric leaves of an aggregate row, one level of nesting deep."""
    out: Dict[str, float] = {}
    for key, value in row.items():
        name = f"{prefix}{key}"
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out[name] = float(value)
        elif isinstance(value, dict) and not prefix:
            out.update(flatten_numbers(value, prefix=f"{key}."))
    return out


def log_report(report: Dict[str, Any], tracking_uri: Optional[str] = None) -> Optional[str]:
    """Log one finished evaluation report. Returns the parent run id, or None."""
    uri = tracking_uri or config.setting("MLFLOW_TRACKING_URI")
    if not uri:
        return None
    try:
        mlf = MlflowRest(uri)
        exp = mlf.experiment_id(EXPERIMENT)
        cfg = report.get("config", {})
        parent = mlf.start_run(exp, report["run_id"], {
            "git_sha": config.GIT_SHA, "kb_version": config.setting("KB_VERSION", "unknown"),
            "dataset_size": report.get("dataset_size")})
        mlf.log_batch(parent["run_id"], {**cfg, "models": ",".join(report.get("models", []))},
                      {"wall_seconds": report.get("wall_seconds", 0) or 0,
                       **flatten_numbers((report.get("retrieval") or {}).get("summary") or {}, "retrieval.")})
        mlf.log_artifact(parent, "report.json", json.dumps(report, indent=1).encode())
        aggregates: List[Dict[str, Any]] = report.get("aggregates") or []
        for row in aggregates:
            child = mlf.start_run(exp, f"{report['run_id']}/{row.get('model')}", {
                "mlflow.parentRunId": parent["run_id"], "model": row.get("model")})
            mlf.log_batch(child["run_id"], {"model": row.get("model"), **cfg}, flatten_numbers(row))
            mlf.end_run(child["run_id"])
        mlf.end_run(parent["run_id"])
        return parent["run_id"]
    except Exception as exc:  # never fail the evaluation over bookkeeping
        print(json.dumps({"msg": "mlflow logging failed", "error": str(exc)}))
        return None
