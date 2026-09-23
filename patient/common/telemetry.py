"""Operational telemetry for the patient services: Prometheus metrics, request
logging and request-id propagation.

Named `telemetry` on purpose. `api_gateway/app/metrics.py` and
`evaluation/metrics.py` score *answer quality* (correctness, grounding,
hallucination). This module measures *operations* - how many requests, how
slow, how many in flight, how often a dependency failed - which is what the
incident doctor needs. The two must not be confused.

One call wires a service up:

    app = FastAPI(...)
    log = telemetry.instrument(app, "retrieval")

which adds the request middleware and a `/metrics` endpoint.
"""

import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import httpx
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import CounterMetricFamily

from common import config, obs

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

# Buckets reach 120 s because a chat request against a CPU-only Ollama really
# can take that long; the default buckets stop at 10 s and would hide it.
LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13, 20, 30, 45, 60, 90, 120)

HTTP_REQUESTS = Counter(
    "knowledgeai_http_requests_total", "HTTP requests served",
    ["service", "endpoint", "method", "status"])
HTTP_LATENCY = Histogram(
    "knowledgeai_http_request_duration_seconds",
    "Time from request received to the last byte of the response (streams included)",
    ["service", "endpoint"], buckets=LATENCY_BUCKETS)
HTTP_IN_FLIGHT = Gauge(
    "knowledgeai_http_requests_in_flight", "Requests currently being served", ["service"])

DOWNSTREAM_LATENCY = Histogram(
    "knowledgeai_downstream_request_duration_seconds",
    "Time until response headers from a service-to-service call",
    ["service", "target", "operation"], buckets=LATENCY_BUCKETS)
DOWNSTREAM_FAILURES = Counter(
    "knowledgeai_downstream_failures_total",
    "Service-to-service calls that raised or returned 5xx",
    ["service", "target", "operation", "reason"])

OLLAMA_LATENCY = Histogram(
    "knowledgeai_ollama_request_duration_seconds",
    "Duration of Ollama calls (embed: one embedding; generate: the whole stream)",
    ["service", "operation"], buckets=LATENCY_BUCKETS)
OLLAMA_FAILURES = Counter(
    "knowledgeai_ollama_failures_total",
    "Ollama calls that failed or were answered by a fallback instead of the model",
    ["service", "operation", "reason"])

RETRIEVED_CHUNKS = Histogram(
    "knowledgeai_retrieved_chunks", "Chunks returned per retrieval query",
    ["service"], buckets=(0, 1, 2, 3, 4, 5, 6, 8, 10, 20))
ZERO_CHUNK_RETRIEVALS = Counter(
    "knowledgeai_zero_chunk_retrievals_total",
    "Retrieval queries that returned no chunks at all", ["service"])

CHAT_OUTCOMES = Counter(
    "knowledgeai_chat_answers_total",
    "Chat requests by how they ended (answered, refused by a guardrail, errored)",
    ["outcome"])

BUILD_INFO = Gauge(
    "knowledgeai_build_info", "Always 1; labels identify the running build",
    ["service", "git_sha", "kb_version"])

_process = psutil.Process(os.getpid()) if psutil else None
PROCESS_MEMORY = Gauge(
    "knowledgeai_process_resident_memory_bytes",
    "Resident memory of this service process (psutil; works on Windows and Linux)",
    ["service"])


class _EmbeddingFallbackCollector:
    """Exposes embedder.embedding_fallback_count() as a Prometheus counter.

    The embedder's hash fallback is a preserved latent bug (DECISIONS.md): when
    Ollama is unreachable or slow it silently returns meaningless vectors. The
    embedder itself is deliberately left untouched; this collector only *reads*
    its existing counter so the silent failure becomes visible on a dashboard.

    One collector per process; each service that embeds adds its label to it.
    (In a container there is one service per process; tests import several.)
    """

    def __init__(self):
        self.services = set()

    def collect(self):
        from ingestion_service.app.embedder import embedding_fallback_count

        family = CounterMetricFamily(
            "knowledgeai_embedding_fallback",
            "Times the hash fallback stood in for a real embedding in this process",
            labels=["service"])
        for service in sorted(self.services):
            family.add_metric([service], float(embedding_fallback_count()))
        yield family


_FALLBACK_COLLECTOR = _EmbeddingFallbackCollector()
REGISTRY.register(_FALLBACK_COLLECTOR)


def register_embedding_fallback(service: str) -> None:
    _FALLBACK_COLLECTOR.services.add(service)


def instrumented_embedding(service: str, text: str, model: str, base_url: str) -> List[float]:
    """Call get_embedding exactly as before, and record how the call went.

    Behaviour is unchanged - the fallback still happens silently and the caller
    still gets its vector. A call answered by the fallback is counted as an
    Ollama failure, since from the operator's side that is what it was.
    """
    from ingestion_service.app.embedder import embedding_fallback_count, get_embedding

    before = embedding_fallback_count()
    started = time.perf_counter()
    vector = get_embedding(text, model=model, base_url=base_url)
    OLLAMA_LATENCY.labels(service, "embed").observe(time.perf_counter() - started)
    if embedding_fallback_count() > before:
        OLLAMA_FAILURES.labels(service, "embed", "fallback").inc()
    return vector


# ---------------------------------------------------------------------------
# Outgoing calls: request-id propagation and downstream metrics
# ---------------------------------------------------------------------------

def _target_names() -> Dict[str, str]:
    names = {}
    for name in ("ingestion", "retrieval", "llm"):
        url = config.setting(f"{name.upper()}_SERVICE_URL")
        if url:
            names[urlsplit(url).netloc] = name
    ollama = config.setting("OLLAMA_BASE_URL")
    if ollama:
        names[urlsplit(ollama).netloc] = "ollama"
    return names


class InstrumentedTransport(httpx.AsyncBaseTransport):
    """Adds X-Request-ID to every outgoing call and records its outcome."""

    def __init__(self, service: str, **transport_kwargs: Any):
        self.service = service
        self._inner = httpx.AsyncHTTPTransport(**transport_kwargs)
        self._targets = _target_names()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request_id = obs.REQUEST_ID.get()
        if request_id:
            request.headers["X-Request-ID"] = request_id
        netloc = request.url.netloc
        netloc = netloc.decode("ascii") if isinstance(netloc, bytes) else netloc
        target = self._targets.get(netloc, request.url.host)
        operation = request.url.path
        started = time.perf_counter()
        try:
            response = await self._inner.handle_async_request(request)
        except Exception as exc:
            DOWNSTREAM_LATENCY.labels(self.service, target, operation).observe(time.perf_counter() - started)
            DOWNSTREAM_FAILURES.labels(self.service, target, operation, type(exc).__name__).inc()
            raise
        DOWNSTREAM_LATENCY.labels(self.service, target, operation).observe(time.perf_counter() - started)
        if response.status_code >= 500:
            DOWNSTREAM_FAILURES.labels(self.service, target, operation, f"http_{response.status_code}").inc()
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


def async_client(service: str, **kwargs: Any) -> httpx.AsyncClient:
    """httpx.AsyncClient with request-id propagation and downstream metrics.

    Accepts the same arguments the call sites already passed (timeout,
    trust_env); proxies from the environment are never used, matching the
    trust_env=False the original code set on most clients.
    """
    kwargs.pop("trust_env", None)
    return httpx.AsyncClient(transport=InstrumentedTransport(service), trust_env=False, **kwargs)


def record_downstream_failure(service: str, target: str, operation: str, exc: BaseException) -> None:
    """For failures that surface after headers, e.g. a stream read timing out."""
    DOWNSTREAM_FAILURES.labels(service, target, operation, type(exc).__name__).inc()


# ---------------------------------------------------------------------------
# Incoming requests: middleware + /metrics
# ---------------------------------------------------------------------------

_SKIP_PATHS = {"/metrics"}


class TelemetryMiddleware:
    """Pure ASGI middleware, so streamed (SSE) responses are timed to their
    last byte rather than to their first header."""

    def __init__(self, app, service: str, log: obs.ServiceLogger):
        self.app = app
        self.service = service
        self.log = log

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in _SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or [])
        request_id = (incoming.get(b"x-request-id") or b"").decode("latin-1") or obs.new_request_id()
        token = obs.REQUEST_ID.set(request_id)
        state = {"status": 500, "started": False}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                state["started"] = True
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        HTTP_IN_FLIGHT.labels(self.service).inc()
        started = time.perf_counter()
        error: Optional[BaseException] = None
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:  # unhandled: log once here, answer 500 ourselves
            error = exc
            state["status"] = 500
            if not state["started"]:
                body = b'{"detail":"Internal Server Error","request_id":"' + request_id.encode() + b'"}'
                await send({"type": "http.response.start", "status": 500,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"x-request-id", request_id.encode("latin-1"))]})
                await send({"type": "http.response.body", "body": body})
        finally:
            duration = time.perf_counter() - started
            route = scope.get("route")
            endpoint = getattr(route, "path", None) or "unmatched"
            status = state["status"]
            HTTP_IN_FLIGHT.labels(self.service).dec()
            HTTP_REQUESTS.labels(self.service, endpoint, scope.get("method", ""), str(status)).inc()
            HTTP_LATENCY.labels(self.service, endpoint).observe(duration)
            fields = {"method": scope.get("method"), "endpoint": endpoint, "path": scope.get("path"),
                      "status": status, "duration_ms": round(duration * 1000, 1)}
            if error is not None:
                self.log.error("unhandled exception", exc=error, **fields)
            elif status >= 500:
                self.log.warning("request", **fields)
            else:
                self.log.info("request", **fields)
            obs.REQUEST_ID.reset(token)


def instrument(app, service: str) -> obs.ServiceLogger:
    """Structured logging, request metrics and /metrics for one FastAPI app."""
    log = obs.configure(service, config.GIT_SHA)
    BUILD_INFO.labels(service, config.GIT_SHA or "unknown", config.setting("KB_VERSION", "unknown")).set(1)
    if _process is not None:
        PROCESS_MEMORY.labels(service).set_function(lambda: _process.memory_info().rss)

    app.add_middleware(TelemetryMiddleware, service=service, log=log)

    from starlette.responses import Response

    async def metrics_endpoint(_request):
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    app.add_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)
    return log
