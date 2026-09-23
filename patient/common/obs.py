"""Structured logging for the patient services.

Every line a service writes is one JSON object on stdout:

    {"ts": "...", "level": "INFO", "service": "gateway", "git_sha": "3f2c...",
     "msg": "request", "request_id": "9c1e...", ...extra fields}

Grafana Alloy ships stdout to Loki, and the incident doctor reads it back from
there. Two properties matter to the doctor more than anything else:

* Exceptions carry a `log_signature`. `signature()` strips the parts of an error
  message that change between occurrences (ids, hex, paths, numbers) before
  hashing, so the same underlying bug always produces the same signature and
  repeat occurrences can be grouped and counted.
* Every line carries the running `git_sha`, so a log line can be tied to the
  deploy that produced it.

Written from scratch as the equivalent of the MLOps capstone's obs.py, whose
path was not readable from this workspace (see DECISIONS.md).
"""

import contextvars
import datetime as _dt
import hashlib
import json
import logging
import os
import re
import sys
import traceback
import uuid
from typing import Any, Dict, Optional

# Set by the telemetry middleware for the lifetime of one request, so that any
# log line written while serving it - in any module - carries the request id.
REQUEST_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_id", default=None)

_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b|\b(?=[0-9a-fA-F]*[0-9])(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{8,}\b")
_PATH = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][\w.\-]+){2,}[\\/]?")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_SPACE = re.compile(r"\s+")


def normalise_message(message: str) -> str:
    """Remove the parts of an error message that vary between occurrences."""
    text = str(message or "")
    text = _UUID.sub("<uuid>", text)
    text = _PATH.sub("<path>", text)
    text = _HEX.sub("<hex>", text)
    text = _NUM.sub("<n>", text)
    return _SPACE.sub(" ", text).strip()


def signature(exc_type: str, message: str) -> str:
    """`"{exc_type}:{sha1[:12]}"` - stable across occurrences of the same bug."""
    digest = hashlib.sha1(f"{exc_type}|{normalise_message(message)}".encode("utf-8")).hexdigest()
    return f"{exc_type}:{digest[:12]}"


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def artifact_fingerprint(path: str) -> str:
    """Short sha256 of a file, for recording exactly which artifact was live."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()[:12]


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _innermost_app_frame(tb) -> Dict[str, Any]:
    """File and line of the deepest frame that is our code, not a library's."""
    frames = traceback.extract_tb(tb) if tb is not None else []
    for frame in reversed(frames):
        path = frame.filename.replace("\\", "/")
        if "site-packages" in path or "/lib/python" in path:
            continue
        return {"error_file": path, "error_line": frame.lineno, "error_function": frame.name}
    return {}


def exception_fields(exc: BaseException) -> Dict[str, Any]:
    exc_type = type(exc).__name__
    message = str(exc)
    fields = {
        "exc_type": exc_type,
        "exc_message": message[:2000],
        "stack": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-8000:],
        "log_signature": signature(exc_type, message),
    }
    fields.update(_innermost_app_frame(exc.__traceback__))
    return fields


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str, git_sha: str):
        super().__init__()
        self.service = service
        self.git_sha = git_sha

    def format(self, record: logging.LogRecord) -> str:
        entry: Dict[str, Any] = {
            "ts": _utc_now(),
            "level": record.levelname,
            "service": self.service,
            "git_sha": self.git_sha,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = REQUEST_ID.get()
        if request_id:
            entry["request_id"] = request_id
        extra = getattr(record, "fields", None)
        if extra:
            entry.update(extra)
        if record.exc_info and record.exc_info[1] is not None and "log_signature" not in entry:
            entry.update(exception_fields(record.exc_info[1]))
        return json.dumps(entry, default=str)


class ServiceLogger:
    """Thin wrapper so call sites read `log.info("msg", key=value)`."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def _log(self, level: int, msg: str, exc: Optional[BaseException] = None, **fields: Any) -> None:
        if exc is not None:
            fields = {**exception_fields(exc), **fields}
        self._logger.log(level, msg, extra={"fields": fields})

    def info(self, msg: str, **fields: Any) -> None:
        self._log(logging.INFO, msg, **fields)

    def warning(self, msg: str, **fields: Any) -> None:
        self._log(logging.WARNING, msg, **fields)

    def error(self, msg: str, exc: Optional[BaseException] = None, **fields: Any) -> None:
        self._log(logging.ERROR, msg, exc=exc, **fields)


_configured: Dict[str, ServiceLogger] = {}


def configure(service: str, git_sha: Optional[str] = None) -> ServiceLogger:
    """Route the root logger and uvicorn's loggers through the JSON formatter."""
    if service in _configured:
        return _configured[service]
    git_sha = git_sha or os.environ.get("APP_GIT_SHA", "unknown")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service, git_sha))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    # Per-request lines come from the telemetry middleware; uvicorn's access
    # line would duplicate each one in a non-JSON-friendly shape.
    logging.getLogger("uvicorn.access").disabled = True
    logger = ServiceLogger(logging.getLogger(f"knowledgeai.{service}"))
    _configured[service] = logger
    return logger
