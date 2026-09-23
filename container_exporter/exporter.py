"""container-exporter: per-container memory, limit, restarts and OOM kills
for this compose project, read straight from the Docker Engine API.

Why this exists next to cAdvisor: on Docker 29 with the containerd image store
(the default on Docker Desktop and on fresh Linux installs), cAdvisor cannot
identify container layers and exports only root-cgroup series - no
per-container memory, no OOM events. The memory-leak fault needs exactly
those, so they are taken from the Docker API instead. Standard library only.

Metrics (label `service` = compose service name):
    aid_container_up                      1 if running
    aid_container_memory_usage_bytes      usage minus inactive page cache
    aid_container_memory_limit_bytes      configured limit
    aid_container_restart_count           Docker RestartCount
    aid_container_oom_kills_total         "oom" events seen since the exporter started
    aid_container_last_exit_code          exit code recorded in the container state
"""

import http.client
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

SOCKET = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
PROJECT = os.environ.get("COMPOSE_PROJECT", "aid")
PORT = int(os.environ.get("PORT", "9102"))
INTERVAL = float(os.environ.get("POLL_INTERVAL_S", "5"))

_state = {}   # service -> gauges
_oom = {}     # service -> count
_lock = threading.Lock()


def _log(msg, **fields):
    print(json.dumps({"service": "container-exporter", "msg": msg, **fields}), flush=True)


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, timeout=10):
        super().__init__("docker", timeout=timeout)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET)


def docker_get(path, timeout=10):
    conn = UnixConnection(timeout=timeout)
    try:
        conn.request("GET", path)
        body = conn.getresponse().read()
    finally:
        conn.close()
    return json.loads(body) if body else None


def _filters(extra=None):
    f = {"label": [f"com.docker.compose.project={PROJECT}"]}
    f.update(extra or {})
    return quote(json.dumps(f))


def working_set(stats):
    mem = stats.get("memory_stats") or {}
    usage = mem.get("usage", 0) or 0
    s = mem.get("stats") or {}
    cache = s.get("inactive_file", s.get("total_inactive_file", 0)) or 0
    return float(max(usage - cache, 0))


def poll_once():
    fresh = {}
    for c in docker_get(f"/containers/json?all=1&filters={_filters()}") or []:
        service = (c.get("Labels") or {}).get("com.docker.compose.service")
        if not service or service in fresh:
            continue
        inspect = docker_get(f"/containers/{c['Id']}/json") or {}
        state = inspect.get("State") or {}
        running = bool(state.get("Running"))
        entry = {
            "up": 1.0 if running else 0.0,
            "restart_count": float(inspect.get("RestartCount", 0) or 0),
            "memory_limit_bytes": float((inspect.get("HostConfig") or {}).get("Memory", 0) or 0),
            "last_exit_code": float(state.get("ExitCode", 0) or 0),
            "memory_usage_bytes": 0.0,
        }
        if running:
            try:
                stats = docker_get(f"/containers/{c['Id']}/stats?stream=false&one-shot=true", timeout=15)
                entry["memory_usage_bytes"] = working_set(stats or {})
            except Exception:
                pass
        fresh[service] = entry
    with _lock:
        _state.clear()
        _state.update(fresh)


def poll_loop():
    while True:
        try:
            poll_once()
        except Exception as exc:  # keep exporting the last good values
            _log("poll failed", error=str(exc))
        time.sleep(INTERVAL)


def events_loop():
    """Count OOM kills as they happen; Docker emits an 'oom' container event."""
    while True:
        try:
            conn = UnixConnection(timeout=None)
            conn.request("GET", f"/events?filters={_filters({'type': ['container'], 'event': ['oom']})}")
            resp = conn.getresponse()
            buf = b""
            while True:
                chunk = resp.read1(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    attrs = (event.get("Actor") or {}).get("Attributes") or {}
                    service = attrs.get("com.docker.compose.service")
                    if service:
                        with _lock:
                            _oom[service] = _oom.get(service, 0) + 1
                        _log("oom kill", target=service)
        except Exception as exc:
            _log("event stream failed", error=str(exc))
        time.sleep(2)


GAUGES = {
    "up": "aid_container_up",
    "memory_usage_bytes": "aid_container_memory_usage_bytes",
    "memory_limit_bytes": "aid_container_memory_limit_bytes",
    "restart_count": "aid_container_restart_count",
    "last_exit_code": "aid_container_last_exit_code",
}


def render():
    lines = []
    with _lock:
        for key, metric in GAUGES.items():
            lines.append(f"# TYPE {metric} gauge")
            for service, entry in sorted(_state.items()):
                lines.append(f'{metric}{{service="{service}"}} {entry[key]}')
        lines.append("# TYPE aid_container_oom_kills_total counter")
        for service in sorted(set(_state) | set(_oom)):
            lines.append(f'aid_container_oom_kills_total{{service="{service}"}} {float(_oom.get(service, 0))}')
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/metrics"):
            body, ctype = render().encode(), "text/plain; version=0.0.4"
        elif self.path.startswith("/health"):
            body, ctype = b'{"status":"ok"}', "application/json"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=poll_loop, daemon=True).start()
    threading.Thread(target=events_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
