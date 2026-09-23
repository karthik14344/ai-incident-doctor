import json

import sink


def test_each_alert_in_a_webhook_becomes_one_line(tmp_path, monkeypatch):
    path = tmp_path / "alerts.jsonl"
    monkeypatch.setattr(sink, "LOG_PATH", str(path))
    payload = {"status": "firing", "groupKey": "g", "alerts": [
        {"status": "firing", "labels": {"alertname": "ServiceDown", "job": "retrieval"},
         "annotations": {"summary": "retrieval is not answering scrapes"},
         "startsAt": "2026-09-23T10:00:00Z", "fingerprint": "abc"},
        {"status": "resolved", "labels": {"alertname": "HighLatencyP95"}, "fingerprint": "def"},
    ]}
    assert sink.append_alerts(payload) == 2
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [line["alertname"] for line in lines] == ["ServiceDown", "HighLatencyP95"]
    assert lines[0]["labels"]["job"] == "retrieval"
    assert lines[1]["status"] == "resolved"
    assert len(sink.read_alerts()) == 2
