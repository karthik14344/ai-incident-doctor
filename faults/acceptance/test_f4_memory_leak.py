"""Acceptance for f4: retrieval keeps no unbounded per-question state."""

import sys


def test_distinct_questions_do_not_grow_module_state(monkeypatch):
    from fastapi.testclient import TestClient

    import retrieval_service.app.main as retrieval
    from common import telemetry

    monkeypatch.setattr(telemetry, "instrumented_embedding", lambda *a, **k: [0.1] * 768)
    monkeypatch.setattr(retrieval, "query_vector_store", lambda **k: [
        {"text": "chunk text " * 50, "metadata": {"filename": "f.pdf", "page_number": 1}, "similarity": 0.8,
         "distance": 0.2}])

    def module_state_size():
        total = 0
        for value in vars(retrieval).values():
            if isinstance(value, (dict, list, set)) or type(value).__name__ in ("OrderedDict", "LRUCache", "TTLCache"):
                try:
                    total += len(value)
                except TypeError:
                    pass
        return total

    before = module_state_size()
    with TestClient(retrieval.app) as client:
        for i in range(3000):
            assert client.post("/retrieve", json={"question": f"distinct question {i}"}).status_code == 200
    grown = module_state_size() - before
    assert grown < 1500, f"module-level state grew by {grown} entries for 3000 distinct questions"
    assert sys.getsizeof(vars(retrieval)) >= 0
