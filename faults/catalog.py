"""The fault catalogue: what each break is, how it enters, and the ground truth.

Every fault has a `delivery`:

  push         a real code/config commit, committed to main and pushed through the
               pipeline (verify -> SHA-tagged deploy -> deploy record). Subtle
               enough that the existing tests pass. There is a guilty commit.
  environment  no code change: a recorded script changes the world around the app
               (stop a container, point a URL at a dead address, a traffic surge).
               Guilty commit is null by construction.
  data         no code or infrastructure change: the knowledge base changes
               underneath the app. Guilty commit null; guilty KB version set.

Commit messages are ordinary. Nothing in a commit that reaches the pipeline
mentions a fault; this file and the ground truth live under faults/, which the
doctor never reads (DECISIONS.md D-41).
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from faults.common import REPO

ACCEPTANCE = os.path.join(REPO, "faults", "acceptance")


@dataclass
class Fault:
    id: str
    name: str
    delivery: str                                   # push | environment | data
    incident_class: str
    component: str
    true_cause: str
    expected_fix: str
    acceptable_classes: List[str] = field(default_factory=list)
    acceptable_components: List[str] = field(default_factory=list)
    # push faults: (path, old, new) text edits and the commit message
    edits: List[Tuple[str, str, str]] = field(default_factory=list)
    message: str = ""
    distractor_paths: List[str] = field(default_factory=list)
    # traffic that makes the symptom appear, on top of the background traffic
    load: Optional[Dict[str, Any]] = None
    neighbour: bool = False                          # busy bigger models on the shared Ollama
    expected_alerts: List[str] = field(default_factory=list)
    acceptance_test: Optional[str] = None
    alert_timeout_s: int = 900

    def ground_truth(self) -> Dict[str, Any]:
        return {"fault_id": self.id, "name": self.name, "delivery": self.delivery,
                "incident_class": self.incident_class,
                "acceptable_classes": sorted(set([self.incident_class] + self.acceptable_classes)),
                "component": self.component,
                "acceptable_components": sorted(set([self.component] + self.acceptable_components)),
                "true_cause": self.true_cause, "expected_fix": self.expected_fix,
                "acceptance_test": os.path.relpath(self.acceptance_test, REPO).replace("\\", "/")
                if self.acceptance_test else None}


EMBEDDER = "patient/ingestion_service/app/embedder.py"
GATEWAY = "patient/api_gateway/app/main.py"
RETRIEVAL = "patient/retrieval_service/app/main.py"

FAULTS: Dict[str, Fault] = {}


def _add(f: Fault) -> None:
    FAULTS[f.id] = f


# 1. Ticket B - the silent timeout regression -----------------------------------
_add(Fault(
    id="f1_embed_timeout", name="Embedding timeout lowered from 45 s to 10 s (silent fallback)",
    delivery="push", incident_class="code_defect", component="retrieval",
    acceptable_components=["ingestion", "ollama"],
    true_cause=("EMBED_TIMEOUT_S in embedder.py was lowered from 45 to 10 s. When Ollama is slow to serve "
                "nomic-embed-text (cold load while other models hold the GPU), embedding calls time out and "
                "the embedder silently substitutes hash vectors, so retrieval returns unrelated chunks and "
                "answers are wrong. Nothing errors; the fallback counter rises."),
    expected_fix="Restore EMBED_TIMEOUT_S to 45 s and make the fallback loud (log/raise or at least count and "
                 "alert) instead of silently answering from hash vectors.",
    edits=[(EMBEDDER,
            "# Cold nomic-embed-text can take ~15 s to load on first use. The old 10 s\n"
            "# timeout turned that first query into silent garbage instead of a slow answer.\n"
            "EMBED_TIMEOUT_S = 45.0",
            "# Embedding calls normally return in well under a second; give up after 10 s\n"
            "# so a stuck Ollama cannot hold a request thread for most of a minute.\n"
            "EMBED_TIMEOUT_S = 10.0")],
    message="Cap embedding calls at 10 s so a stuck call frees its thread",
    distractor_paths=["retrieval_service", "vector_store", "chunker"],
    neighbour=True,
    expected_alerts=["EmbeddingFallbackActive"],
    acceptance_test=os.path.join(ACCEPTANCE, "test_f1_embed_timeout.py"),
))

# 2. Concurrency starvation - the false-attribution test -----------------------
_add(Fault(
    id="f2_capacity", name="Concurrent chat surge saturates the single local model",
    delivery="environment", incident_class="capacity", component="ollama", acceptable_components=["llm"],
    true_cause=("Many simultaneous chat questions; the single local llama3.2 on Ollama serialises generation, "
                "so requests queue and latency climbs. No deploy is involved."),
    expected_fix="Bound concurrency at the gateway with a queue/semaphore and shed load (429) beyond it; "
                 "scale generation capacity. No code change caused this.",
    # Calibrated: 1.2/s did not saturate (p95 ~12 s; Ollama serves requests in parallel).
    # At 4/s with 96 in flight throughput caps at ~1.37/s and p95 reaches ~75-88 s.
    load={"mode": "chat", "rate": 4.0, "concurrency": 96, "duration": 300, "timeout": 240},
    expected_alerts=["HighLatencyP95"],
))

# 3. Retrieval unreachable - dependency failure ---------------------------------
_add(Fault(
    id="f3_retrieval_down", name="Retrieval service stopped",
    delivery="environment", incident_class="dependency_failure", component="retrieval",
    true_cause="The retrieval container was stopped; every gateway call to it fails with a connection error.",
    expected_fix="Restart the retrieval service (docker compose start retrieval).",
    expected_alerts=["ServiceDown", "DownstreamCallFailures"],
))
_add(Fault(
    id="f3b_retrieval_bad_address", name="Gateway pointed at a wrong retrieval address",
    delivery="environment", incident_class="dependency_failure", component="retrieval",
    acceptable_classes=["configuration"],
    true_cause=("The gateway was restarted with RETRIEVAL_SERVICE_URL pointing at a host that does not exist; "
                "retrieval itself is healthy but unreachable from the gateway."),
    expected_fix="Restore the retrieval address (RETRIEVAL_SERVICE_URL=http://retrieval:8002) and restart the gateway.",
    expected_alerts=["DownstreamCallFailures"],
))

# 4. Unbounded cache - memory leak ------------------------------------------------
_add(Fault(
    id="f4_memory_leak", name="Retrieval response cache that never evicts",
    delivery="push", incident_class="code_defect", component="retrieval",
    true_cause=("A commit added a module-level dict caching every retrieval response (with its query "
                "embedding) keyed by question text, with no eviction. Memory grows with every distinct "
                "question until the container hits its limit and is OOM-killed, repeatedly."),
    expected_fix="Bound the cache (LRU with maxsize, or TTL) or remove it.",
    edits=[(RETRIEVAL,
            '@app.post("/retrieve")\ndef retrieve_context(req: QueryRequest):\n'
            '    if not req.question.strip():\n'
            '        raise HTTPException(status_code=400, detail="Question cannot be empty")\n',
            '# Recent retrievals, so a repeated question skips the embedding round-trip.\n'
            '_RECENT: Dict[str, Dict[str, Any]] = {}\n\n\n'
            '@app.post("/retrieve")\ndef retrieve_context(req: QueryRequest):\n'
            '    if not req.question.strip():\n'
            '        raise HTTPException(status_code=400, detail="Question cannot be empty")\n\n'
            '    key = f"{req.collection_name}:{req.top_k}:{req.embedding_model}:{req.question.strip().lower()}"\n'
            '    if key in _RECENT:\n'
            '        return _RECENT[key]\n'),
           (RETRIEVAL,
            '    return {\n        "question": req.question,',
            '    response = {\n        "question": req.question,'),
           (RETRIEVAL,
            '        "raw_chunks": chunks\n    }\n',
            '        "raw_chunks": chunks\n    }\n'
            '    _RECENT[key] = {**response, "query_embedding": list(query_emb)}\n'
            '    return response\n')],
    message="Serve repeated retrieval questions from memory",
    distractor_paths=["retrieval_service", "vector_store"],
    load={"mode": "search", "rate": 6.0, "concurrency": 12, "duration": 900, "unique": True},
    expected_alerts=["MemoryClimbing", "ContainerMemoryNearLimit", "ContainerOOMKilled", "RestartLoop"],
    acceptance_test=os.path.join(ACCEPTANCE, "test_f4_memory_leak.py"),
    alert_timeout_s=1200,
))

# 5. A typo on a path only some inputs take ---------------------------------------
_add(Fault(
    id="f5_typo", name="AttributeError when titling a chat session from a keyword query",
    delivery="push", incident_class="code_defect", component="gateway",
    # An attribute typo, not an undefined name: pyflakes (ruff, in CI) rejects an
    # undefined name, which the first version of this fault was - it never shipped.
    true_cause=("A commit changed how new chat sessions are titled; the branch for questions without a '?' "
                "reads req.qestion, an attribute that does not exist, so keyword-style queries crash with "
                "AttributeError (HTTP 500) while normal questions work. Linters do not see attribute typos."),
    expected_fix="Fix the attribute name (req.qestion -> req.question) in the session-title branch.",
    edits=[(GATEWAY,
            '        title = req.question[:30] + ("..." if len(req.question) > 30 else "")\n',
            '        # Name the conversation after the question itself, not its first 30 characters.\n'
            '        if "?" in req.question:\n'
            '            title = req.question.split("?")[0].strip()[:60] + "?"\n'
            '        else:\n'
            '            title = req.question.strip()[:60] + ("..." if len(req.qestion) > 60 else "")\n')],
    message="Title new chat sessions after the question",
    distractor_paths=["api_gateway"],
    expected_alerts=["HighErrorRate"],
    acceptance_test=os.path.join(ACCEPTANCE, "test_f5_typo.py"),
))

# 6. Tight internal timeout --------------------------------------------------------
_add(Fault(
    # Redesigned on measurements (DECISIONS D-79): the spec's "3 s" never trips on this
    # hardware - LLM time-to-first-token p95 is 0.07 s and retrieval p99 0.1 s - so the
    # timeout is set just under the real latency instead: the gateway->retrieval call
    # finishes within 50 ms 93.4% of the time, so a 50 ms timeout fails ~1 in 15.
    id="f6_tight_timeout", name="Gateway -> retrieval timeout set to 50 ms (a unit slip)",
    delivery="push", incident_class="code_defect", component="gateway",
    acceptable_classes=["configuration"], acceptable_components=["retrieval"],
    true_cause=("A commit set the gateway's httpx timeout for the chat retrieval call to 0.05 s (meant as a "
                "'fail fast' limit, but in seconds). Retrieval normally answers in ~30-50 ms, so the slower "
                "~7% of calls raise ReadTimeout; the gateway then answers without context and refuses the "
                "question. Failures are intermittent, for no visible reason."),
    expected_fix="Restore the retrieval call timeout (30 s, or at least well above retrieval latency).",
    edits=[(GATEWAY,
            '    async with telemetry.async_client("gateway", timeout=30.0) as client:\n'
            '        try:\n'
            '            r = await client.post(f"{RETRIEVAL_SERVICE_URL}/retrieve", json=retrieval_payload)\n',
            '    # Retrieval answers in ~30 ms; fail fast rather than hold the chat request.\n'
            '    async with telemetry.async_client("gateway", timeout=0.05) as client:\n'
            '        try:\n'
            '            r = await client.post(f"{RETRIEVAL_SERVICE_URL}/retrieve", json=retrieval_payload)\n')],
    message="Fail fast when retrieval is slow - it normally answers in about 30 ms",
    distractor_paths=["api_gateway", "retrieval_service"],
    # Busy-hour chat (below capacity), so a ~7% failure rate shows up in most minutes.
    load={"mode": "chat", "rate": 0.8, "concurrency": 16, "duration": 600},
    expected_alerts=["DownstreamCallFailures"],
    acceptance_test=os.path.join(ACCEPTANCE, "test_f6_tight_timeout.py"),
))

# 7. Data: a knowledge-base version with most documents missing ------------------
PARTIAL_KB_DOCS = "attendance_policy.pdf,exam_policy.pdf,hostel_rules.pdf,welcome_guide.txt"
_add(Fault(
    id="f7_kb_missing_docs", name="Knowledge-base version published with 6 of 10 documents missing",
    delivery="data", incident_class="data_issue", component="knowledge_base",
    acceptable_components=["chroma", "retrieval"],
    true_cause=("A knowledge-base version built from only 4 of the 10 policy documents (library, scholarship, "
                "lab safety, placement, grievance and calendar missing) was loaded into the live index. "
                "Questions about the missing policies find nothing relevant and are refused as out of scope. "
                "No code or infrastructure changed."),
    expected_fix="Reload the previous complete knowledge-base version with kb-loader --force (and rebuild "
                 "the KB from the full corpus before publishing).",
    expected_alerts=["ChatAnswersRefused"],
))


# What a user would say if monitoring missed the fault - the symptom as seen from
# the chat window, never the cause. Used by the ticket fallback in run_fault.
TICKET_TEXT = {
    "f1_embed_timeout": "Answers have been wrong or unrelated to my question for a while now.",
    "f2_capacity": "The assistant has become extremely slow; answers take over a minute.",
    "f3_retrieval_down": "The assistant says it has nothing relevant in the documents, for every question.",
    "f3b_retrieval_bad_address": "The assistant says it has nothing relevant in the documents, for every question.",
    "f4_memory_leak": "Searches sometimes fail and the assistant seems to be restarting.",
    "f5_typo": "Some of my searches fail with an error while others work fine.",
    "f6_tight_timeout": "Every now and then it says it has nothing on a question it answered fine a minute ago.",
    "f7_kb_missing_docs": "It no longer answers questions about the library, scholarships or placements.",
}
