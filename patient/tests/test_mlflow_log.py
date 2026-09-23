"""evaluation/mlflow_log.py against a fake MLflow REST server."""

from fastapi import FastAPI, Request

from evaluation import mlflow_log
from tests.fake_servers import ThreadedServer


def make_fake_mlflow():
    app = FastAPI()
    app.state.calls = []

    @app.get("/api/2.0/mlflow/experiments/get-by-name")
    def get_by_name(experiment_name: str):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error_code": "RESOURCE_DOES_NOT_EXIST"}, status_code=404)

    @app.post("/api/2.0/mlflow/{path:path}")
    async def post(path: str, request: Request):
        body = await request.json()
        app.state.calls.append((path, body))
        if path == "experiments/create":
            return {"experiment_id": "7"}
        if path == "runs/create":
            n = sum(1 for p, _ in app.state.calls if p == "runs/create")
            return {"run": {"info": {"run_id": f"r{n}", "artifact_uri": f"mlflow-artifacts:/7/r{n}/artifacts"}}}
        return {}

    @app.put("/api/2.0/mlflow-artifacts/artifacts/{path:path}")
    async def put(path: str, request: Request):
        app.state.calls.append(("artifact", path))
        return {}

    return app


def test_a_report_becomes_a_parent_run_with_one_child_per_model():
    app = make_fake_mlflow()
    server = ThreadedServer(app).start()
    try:
        report = {"run_id": "eval_x", "models": ["llama3.2", "mistral"], "dataset_size": 3,
                  "config": {"top_k": 4}, "wall_seconds": 12.5,
                  "retrieval": {"summary": {"hit_at_k": 0.9}},
                  "aggregates": [{"model": "llama3.2", "accuracy_pct": 70.0, "latency": {"p50_ms": 900}},
                                 {"model": "mistral", "accuracy_pct": 80.0, "latency": {"p50_ms": 1500}}]}
        run_id = mlflow_log.log_report(report, tracking_uri=server.url)
    finally:
        server.stop()
    assert run_id == "r1"
    creates = [b for p, b in app.state.calls if p == "runs/create"]
    assert len(creates) == 3
    children = [c for c in creates if any(t["key"] == "mlflow.parentRunId" for t in c["tags"])]
    assert len(children) == 2
    batches = [b for p, b in app.state.calls if p == "runs/log-batch"]
    keys = {m["key"] for b in batches for m in b["metrics"]}
    assert {"accuracy_pct", "latency.p50_ms", "retrieval.hit_at_k", "wall_seconds"} <= keys
    assert ("artifact", "7/r1/artifacts/report.json") in app.state.calls


def test_logging_is_skipped_without_a_tracking_uri(monkeypatch):
    monkeypatch.setattr(mlflow_log.config, "setting", lambda name, default=None: default)
    assert mlflow_log.log_report({"run_id": "x"}) is None
