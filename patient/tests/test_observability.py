"""Structured logging and operational metrics (common/obs.py, common/telemetry.py)."""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from common import obs, telemetry


# ---- signatures -------------------------------------------------------------

def test_same_bug_with_different_ids_gets_the_same_signature():
    a = obs.signature("KeyError", "missing chunk 3f2a9c1e-77aa-4b0e-9d7e-0a1b2c3d4e5f at offset 812")
    b = obs.signature("KeyError", "missing chunk 0c9e8d7f-1111-4222-8333-944455566677 at offset 3")
    assert a == b


def test_paths_hex_and_numbers_are_normalised_away():
    a = obs.signature("FileNotFoundError", "No such file: /app/storage/documents/doc_1a2b3c4d5e_x.pdf (errno 2)")
    b = obs.signature("FileNotFoundError", "No such file: /tmp/other/place/doc_ffeeddccbb_y.pdf (errno 17)")
    assert a == b


def test_different_bugs_get_different_signatures():
    assert obs.signature("KeyError", "missing chunk") != obs.signature("ValueError", "missing chunk")
    assert obs.signature("KeyError", "missing chunk") != obs.signature("KeyError", "missing page")


def test_signature_has_the_documented_shape():
    sig = obs.signature("ConnectError", "All connection attempts failed")
    exc_type, digest = sig.split(":")
    assert exc_type == "ConnectError"
    assert len(digest) == 12


def test_request_ids_are_short_and_unique():
    ids = {obs.new_request_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(len(i) == 16 for i in ids)


def test_artifact_fingerprint_is_stable(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    assert obs.artifact_fingerprint(str(f)) == obs.artifact_fingerprint(str(f))
    assert len(obs.artifact_fingerprint(str(f))) == 12


def test_exception_lines_carry_type_stack_and_signature():
    formatter = obs.JsonFormatter("svc", "abc123")
    logger = logging.getLogger("test.obs")
    try:
        raise ValueError("bad value 42")
    except ValueError as exc:
        record = logger.makeRecord("test.obs", logging.ERROR, __file__, 1, "boom", (), None,
                                   extra={"fields": obs.exception_fields(exc)})
    line = json.loads(formatter.format(record))
    assert line["service"] == "svc"
    assert line["git_sha"] == "abc123"
    assert line["exc_type"] == "ValueError"
    assert line["log_signature"] == obs.signature("ValueError", "bad value 42")
    assert "Traceback" in line["stack"]
    assert line["error_file"].endswith("test_observability.py")


# ---- middleware and /metrics -----------------------------------------------

@pytest.fixture
def tiny_app():
    app = FastAPI()
    telemetry.instrument(app, "unit")

    @app.get("/ok")
    def ok():
        return {"request_id": obs.REQUEST_ID.get()}

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    return app


def test_metrics_endpoint_counts_requests(tiny_app):
    with TestClient(tiny_app) as client:
        client.get("/ok")
        client.get("/ok")
        body = client.get("/metrics").text
    assert 'knowledgeai_http_requests_total{endpoint="/ok",method="GET",service="unit",status="200"}' in body
    assert "knowledgeai_http_request_duration_seconds_bucket" in body
    assert 'knowledgeai_http_requests_in_flight{service="unit"}' in body
    assert 'knowledgeai_process_resident_memory_bytes{service="unit"}' in body


def test_incoming_request_id_is_honoured_and_echoed(tiny_app):
    with TestClient(tiny_app) as client:
        r = client.get("/ok", headers={"X-Request-ID": "fixedid123"})
    assert r.json()["request_id"] == "fixedid123"
    assert r.headers["x-request-id"] == "fixedid123"


def test_a_request_id_is_generated_when_absent(tiny_app):
    with TestClient(tiny_app) as client:
        r = client.get("/ok")
    assert len(r.headers["x-request-id"]) == 16


def test_unhandled_exception_is_a_500_and_is_counted(tiny_app):
    with TestClient(tiny_app, raise_server_exceptions=False) as client:
        r = client.get("/boom")
        body = client.get("/metrics").text
    assert r.status_code == 500
    assert 'endpoint="/boom",method="GET",service="unit",status="500"' in body


# ---- every real service exposes /metrics -------------------------------------

@pytest.mark.parametrize("module", [
    "api_gateway.app.main",
    "ingestion_service.app.main",
    "retrieval_service.app.main",
    "llm_service.app.main",
])
def test_every_service_serves_metrics(module):
    import importlib

    app = importlib.import_module(module).app
    with TestClient(app) as client:
        r = client.get("/metrics")
    assert r.status_code == 200
    assert "knowledgeai_build_info" in r.text


def test_embedding_fallback_counter_is_exported_by_retrieval():
    from retrieval_service.app.main import app

    with TestClient(app) as client:
        body = client.get("/metrics").text
    assert 'knowledgeai_embedding_fallback_total{service="retrieval"}' in body


def test_fallback_is_counted_as_an_ollama_failure_without_raising(unused_port):
    """The latent bug stays silent: a vector comes back, nothing raises."""
    before = telemetry.OLLAMA_FAILURES.labels("unit", "embed", "fallback")._value.get()
    vector = telemetry.instrumented_embedding("unit", "hello world", "nomic-embed-text",
                                              f"http://127.0.0.1:{unused_port}")
    assert len(vector) == 768
    after = telemetry.OLLAMA_FAILURES.labels("unit", "embed", "fallback")._value.get()
    assert after == before + 1
