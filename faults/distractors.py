"""Innocent commits that land around each guilty commit.

Without them the guilty commit is the only change in the window and finding it
is trivial. Each distractor is a real, harmless change of the kind a team makes
every day - a runbook paragraph, a new passing test, an explanatory comment in
the very files the faults touch, a dashboard tweak - with an ordinary message.
Each is applied at most once (its text is its own marker) and none is reverted.
"""

import os
import subprocess
from typing import Callable, Dict, List, Optional

from faults.common import REPO, commit, log

RUNBOOK = "patient/docs/OPERATIONS.md"
NOTES_TEST = "patient/tests/test_behaviour_notes.py"

RUNBOOK_HEADER = """# KnowledgeAI operations notes

Short, practical notes for whoever is on call for the document assistant.
"""

RUNBOOK_SECTIONS = [
    ("Restarting a single service", "Restart one service with `docker compose restart <service>`; the gateway "
     "tolerates a restarting dependency and answers with a refusal until it is back."),
    ("Where the logs are", "Every service writes one JSON line per request to stdout. Grafana's Loki datasource "
     "has them; filter with `| json | level=\"ERROR\"` to see only failures."),
    ("Checking the knowledge base version", "The live knowledge-base version is the `kb_version` label on "
     "`knowledgeai_build_info` and in `kb/manifest.json` of the deployed commit."),
    ("Slow first answer after a restart", "The first chat after Ollama loads a model can take tens of seconds; "
     "this is model load time, not a fault. Subsequent answers are fast."),
    ("Uploading documents", "Uploads go through the Documents page. Processing runs in the ingestion service; "
     "the document status moves from uploaded to processed."),
    ("Reading the operations dashboard", "Request rate and in-flight requests show demand; p95 latency and "
     "error rate show how well it is being served. Read them together."),
    ("Rate limiting", "The gateway limits requests per chat session. A burst from one browser tab is refused by "
     "the rate-limit guardrail, which is expected behaviour."),
    ("Rolling back", "Every deploy is tagged with its git SHA. The deploy script rolls back automatically when "
     "the smoke test fails; to roll back by hand, redeploy the previous SHA."),
    ("Ollama model list", "The Settings page lists the models Ollama has installed. Only llama3.2 is used for "
     "chat by default; the Model Comparison page can benchmark the others."),
    ("Backups", "The SQLite database lives in the appdata volume and the vector index in chroma-data. Snapshot "
     "both volumes together so documents and vectors stay consistent."),
    ("Guardrail refusals", "A refusal is not an outage. Check the guardrails field in the chat response to see "
     "which guardrail refused and why."),
    ("Disk usage", "Old SHA-tagged images accumulate. `docker image prune` with a filter on the aid/ prefix "
     "reclaims space; keep at least the last two deploys for rollback."),
]

NOTES_TEST_HEADER = '''"""Small behaviour notes, written down as tests while reading the code."""
'''

NOTE_TESTS = [
    ("test_long_pages_are_split_with_overlap", '''

def test_long_pages_are_split_with_overlap():
    from ingestion_service.app.chunker import create_chunks

    chunks = create_chunks([{"page": 1, "text": "x" * 2000}], chunk_size=800, chunk_overlap=100)
    assert [c["chunk_index"] for c in chunks] == [1, 2, 3]
    assert all(c["page_number"] == 1 for c in chunks)
'''),
    ("test_empty_pages_produce_no_chunks", '''

def test_empty_pages_produce_no_chunks():
    from ingestion_service.app.chunker import create_chunks

    assert create_chunks([{"page": 1, "text": ""}, {"page": 2, "text": ""}]) == []
'''),
    ("test_bare_model_names_get_the_latest_tag", '''

def test_bare_model_names_get_the_latest_tag():
    from llm_service.app.main import resolve_model_tag

    assert resolve_model_tag("llama3.2") == "llama3.2:latest"
    assert resolve_model_tag("llama3.2:1b") == "llama3.2:1b"
'''),
    ("test_greetings_are_recognised", '''

def test_greetings_are_recognised():
    from llm_service.app.main import is_greeting_question

    assert is_greeting_question("Hello!")
    assert not is_greeting_question("What is the attendance requirement?")
'''),
    ("test_factual_prompts_carry_the_context", '''

def test_factual_prompts_carry_the_context():
    from llm_service.app.main import build_prompt

    prompt = build_prompt("What is the fee?", "CONTEXT-MARKER")
    assert "RETRIEVED DOCUMENT CONTEXT" in prompt and "CONTEXT-MARKER" in prompt
'''),
    ("test_no_chunks_gives_an_explicit_empty_context", '''

def test_no_chunks_gives_an_explicit_empty_context():
    from retrieval_service.app.main import assemble_context

    out = assemble_context([])
    assert out["assembled_context"] == "No relevant document chunks found."
    assert out["sources"] == []
'''),
    ("test_blank_questions_are_refused_before_retrieval", '''

def test_blank_questions_are_refused_before_retrieval():
    from api_gateway.app import guardrails

    assert guardrails.validate_input("   ").allowed is False
'''),
    ("test_unset_settings_fall_back_to_the_default", '''

def test_unset_settings_fall_back_to_the_default():
    from common import config

    assert config.setting("KNOWLEDGEAI_SURELY_UNSET_SETTING", "fallback") == "fallback"
'''),
]

CODE_COMMENTS = [
    ("patient/api_gateway/app/main.py", "def get_settings_map() -> Dict[str, str]:",
     "# Settings are read per request so a change on the Settings page applies to the next question.",
     "Explain why gateway settings are read per request"),
    ("patient/api_gateway/app/main.py", "def _sse(payload: Dict[str, Any]) -> str:",
     "# Server-sent events: one JSON object per 'data:' line, blank line terminated.",
     "Document the SSE framing helper"),
    ("patient/retrieval_service/app/main.py", "def assemble_context(",
     "# Sources keep a 150-character preview; the full chunk text stays in raw_chunks.",
     "Note what the source previews contain"),
    ("patient/llm_service/app/main.py", "def resolve_model_tag(model: str) -> str:",
     "# Ollama resolves bare model names to ':latest' anyway, but explicit tags make logs unambiguous.",
     "Comment on explicit Ollama model tags"),
    ("patient/llm_service/app/main.py", "def is_greeting_question(q: str) -> bool:",
     "# Greetings skip retrieval context entirely - there is nothing in the documents to cite.",
     "Explain the greeting shortcut"),
    ("patient/ingestion_service/app/vector_store.py", "def query_vector_store(",
     "# Distances are cosine (hnsw:space=cosine); similarity is reported as 1 - distance.",
     "Document the similarity convention in the vector store"),
    ("patient/ingestion_service/app/chunker.py", "def create_chunks(",
     "# Chunk sizes are in characters, not tokens; token_count is a whitespace word count.",
     "Clarify chunk size units"),
    ("patient/api_gateway/app/suggestions.py", "def suggest_queries(",
     "# Suggestions are built from stored chunk text only; no model call is made while typing.",
     "Note that query suggestions never call a model"),
    ("patient/api_gateway/app/db.py", "def init_db():",
     "# Idempotent: CREATE TABLE IF NOT EXISTS and INSERT OR IGNORE for default settings.",
     "Document that init_db is idempotent"),
    ("patient/ingestion_service/app/main.py", "def update_doc_status(",
     "# Status moves uploaded -> extracting -> chunking -> embedding -> processed (or error).",
     "Document the document status lifecycle"),
    ("patient/api_gateway/app/guardrails.py", "def validate_input(question: str) -> Verdict:",
     "# Cheapest checks first: this runs before any retrieval or model call.",
     "Comment on guardrail ordering"),
    ("patient/common/telemetry.py", "def instrument(app, service: str) -> obs.ServiceLogger:",
     "# Call once per app, before routes receive traffic.",
     "Note when to call telemetry.instrument"),
]


def _read(path: str) -> str:
    full = os.path.join(REPO, path)
    return open(full, encoding="utf-8").read() if os.path.exists(full) else ""


def _write(path: str, text: str) -> None:
    full = os.path.join(REPO, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _runbook(i: int) -> Optional[Dict]:
    title, body = RUNBOOK_SECTIONS[i]
    if f"## {title}" in _read(RUNBOOK):
        return None

    def apply():
        text = _read(RUNBOOK) or RUNBOOK_HEADER
        _write(RUNBOOK, text.rstrip("\n") + f"\n\n## {title}\n\n{body}\n")
        return [RUNBOOK]
    return {"id": f"doc:{title}", "apply": apply, "message": f"Operations notes: {title.lower()}"}


def _note_test(i: int) -> Optional[Dict]:
    name, code = NOTE_TESTS[i]
    if f"def {name}(" in _read(NOTES_TEST):
        return None

    def apply():
        text = _read(NOTES_TEST) or NOTES_TEST_HEADER
        _write(NOTES_TEST, text.rstrip("\n") + "\n" + code)
        return [NOTES_TEST]
    return {"id": f"test:{name}", "apply": apply, "message": f"Add test: {name[5:].replace('_', ' ')}"}


def _comment(i: int) -> Optional[Dict]:
    path, anchor, comment, message = CODE_COMMENTS[i]
    text = _read(path)
    if comment in text or anchor not in text:
        return None

    def apply():
        t = _read(path)
        _write(path, t.replace(anchor, f"{comment}\n{anchor}", 1))
        return [path]
    return {"id": f"comment:{path}:{anchor[:20]}", "apply": apply, "message": message}


def pool() -> List[Dict]:
    """Every distractor not yet applied, interleaved by kind."""
    kinds: List[List[Callable[[], Optional[Dict]]]] = [
        [lambda i=i: _comment(i) for i in range(len(CODE_COMMENTS))],
        [lambda i=i: _runbook(i) for i in range(len(RUNBOOK_SECTIONS))],
        [lambda i=i: _note_test(i) for i in range(len(NOTE_TESTS))],
    ]
    out = []
    for i in range(max(len(k) for k in kinds)):
        for k in kinds:
            if i < len(k):
                d = k[i]()
                if d:
                    out.append(d)
    return out


def land(n: int, prefer_paths: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Commit n distractors (preferring ones in the given files). Not pushed."""
    candidates = pool()
    if prefer_paths:
        candidates.sort(key=lambda d: 0 if any(p in d["id"] for p in prefer_paths) else 1)
    landed = []
    for d in candidates[:n]:
        paths = d["apply"]()
        if paths[0].endswith(".py"):
            subprocess.run([os.path.join(REPO, ".venv", "Scripts", "python.exe") if os.name == "nt" else "python3",
                            "-m", "ruff", "check", *paths], cwd=REPO, check=True, capture_output=True)
        sha = commit(paths, d["message"])
        landed.append({"sha": sha, "message": d["message"], "id": d["id"]})
        log(f"distractor {sha[:7]}: {d['message']}")
    return landed
