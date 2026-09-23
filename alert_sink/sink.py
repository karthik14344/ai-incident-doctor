"""alert-sink: receives Alertmanager webhooks and appends each alert as one
JSON line to a file on a volume.

That file is the incident trigger log. The doctor tails it; the evaluation
harness replays it. Standard library only, so it has nothing to break.

Each line:
    {"received_at": "...", "status": "firing"|"resolved", "alertname": "...",
     "fingerprint": "...", "startsAt": "...", "endsAt": "...",
     "labels": {...}, "annotations": {...}, "generatorURL": "...",
     "groupKey": "..."}

After appending, every FIRING alert is also POSTed straight to the doctor's
/incident endpoint (DOCTOR_INCIDENT_URL), so a diagnosis starts with no human
involved. Delivery runs in a background thread with retries and never delays
Alertmanager. Resolved alerts are logged but not forwarded.

GET /alerts?since=<iso> returns the lines (JSON array); GET /health for the
healthcheck; GET /metrics for received/forwarded counters.
"""

import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOG_PATH = os.environ.get("ALERT_LOG_PATH", "/data/alerts.jsonl")
PORT = int(os.environ.get("PORT", "9095"))
_lock = threading.Lock()
DOCTOR_INCIDENT_URL = os.environ.get("DOCTOR_INCIDENT_URL", "")
_received = {"firing": 0, "resolved": 0}
_forwarded = {"ok": 0, "failed": 0}


def _log(msg: str, **fields) -> None:
    print(json.dumps({"ts": _now(), "service": "alert-sink", "msg": msg, **fields}), flush=True)


def forward_to_doctor(alert: dict, attempts: int = 5) -> bool:
    """POST one firing alert to the doctor's /incident endpoint."""
    if not DOCTOR_INCIDENT_URL:
        return False
    body = json.dumps({"alert": alert}).encode()
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(DOCTOR_INCIDENT_URL, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read() or b"{}")
            _forwarded["ok"] += 1
            _log("forwarded to doctor", alertname=alert.get("alertname"), result=result.get("status"),
                 incident_id=result.get("incident_id"))
            return True
        except Exception as exc:  # the doctor may be restarting; its catch-up poll is the backstop
            _log("forward to doctor failed", alertname=alert.get("alertname"), attempt=attempt + 1, error=str(exc))
            time.sleep(2 ** attempt)
    _forwarded["failed"] += 1
    return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def append_alerts(payload: dict) -> int:
    lines = []
    for alert in payload.get("alerts", []):
        labels = alert.get("labels", {})
        lines.append({
            "received_at": _now(),
            "status": alert.get("status", payload.get("status")),
            "alertname": labels.get("alertname"),
            "fingerprint": alert.get("fingerprint"),
            "startsAt": alert.get("startsAt"),
            "endsAt": alert.get("endsAt"),
            "labels": labels,
            "annotations": alert.get("annotations", {}),
            "generatorURL": alert.get("generatorURL"),
            "groupKey": payload.get("groupKey"),
        })
    with _lock:
        os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(json.dumps(line) + "\n")
                _received[line["status"] if line["status"] in _received else "firing"] += 1
    for line in lines:
        if line["status"] == "firing":
            threading.Thread(target=forward_to_doctor, args=(line,), daemon=True).start()
    return len(lines)


def read_alerts(since: str = "") -> list:
    if not os.path.exists(LOG_PATH):
        return []
    out = []
    with open(LOG_PATH, "r", encoding="utf-8") as fh:
        for raw in fh:
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if since and (line.get("received_at") or "") < since:
                continue
            out.append(line)
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path != "/alerts":
            return self._send(404, b'{"error":"not found"}')
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, b'{"error":"invalid json"}')
        count = append_alerts(payload)
        self._send(200, json.dumps({"stored": count}).encode())

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/health":
            return self._send(200, b'{"status":"ok"}')
        if url.path == "/alerts":
            since = parse_qs(url.query).get("since", [""])[0]
            return self._send(200, json.dumps(read_alerts(since)).encode())
        if url.path == "/metrics":
            body = "".join(
                f'alert_sink_alerts_received_total{{status="{k}"}} {v}\n' for k, v in _received.items())
            body += "".join(
                f'alert_sink_doctor_forwards_total{{result="{k}"}} {v}\n' for k, v in _forwarded.items())
            return self._send(200, body.encode(), "text/plain; version=0.0.4")
        return self._send(404, b'{"error":"not found"}')

    def log_message(self, fmt, *args):  # one JSON line per request, like the rest of the stack
        _log(fmt % args)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
