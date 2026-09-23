"""alert-sink: receives Alertmanager webhooks and appends each alert as one
JSON line to a file on a volume.

That file is the incident trigger log. The doctor tails it; the evaluation
harness replays it. Standard library only, so it has nothing to break.

Each line:
    {"received_at": "...", "status": "firing"|"resolved", "alertname": "...",
     "fingerprint": "...", "startsAt": "...", "endsAt": "...",
     "labels": {...}, "annotations": {...}, "generatorURL": "...",
     "groupKey": "..."}

GET /alerts?since=<iso> returns the lines (JSON array); GET /health for the
healthcheck; GET /metrics for a received-alerts counter.
"""

import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOG_PATH = os.environ.get("ALERT_LOG_PATH", "/data/alerts.jsonl")
PORT = int(os.environ.get("PORT", "9095"))
_lock = threading.Lock()
_received = {"firing": 0, "resolved": 0}


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
            return self._send(200, body.encode(), "text/plain; version=0.0.4")
        return self._send(404, b'{"error":"not found"}')

    def log_message(self, fmt, *args):  # one JSON line per request, like the rest of the stack
        print(json.dumps({"ts": _now(), "service": "alert-sink", "msg": fmt % args}), flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
