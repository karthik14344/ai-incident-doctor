# Decisions

Every non-obvious choice made while building this project, and why. Newest
decisions are added at the end of each section.

---

## ⚠ D-0. The embedder's silent fallback is a deliberate latent bug. Do not fix it.

**File:** `patient/ingestion_service/app/embedder.py`

When Ollama is unreachable or too slow, `get_embedding()` catches the error and
returns `generate_fallback_embedding(text)` - a hash of the words, not a real
embedding. The app keeps answering, but retrieval is now comparing noise with
real `nomic-embed-text` vectors, so answers are confidently wrong. Nothing
crashes and nothing returns an error. `EMBED_TIMEOUT_S = 45.0` is the only
thing standing between a slow cold model and that silent failure.

This is **the mechanism behind the most important fault-injection case**
(Ticket B: the timeout regression). It is kept exactly as it was in the source
project:

- The file is byte-for-byte the source file, except that CRLF line endings
  were normalised to LF by `.gitattributes` (content otherwise identical;
  sha1 of the LF file: `1a25535a1feb90de4fc918a6eb0ae580bcc77d28`).
- It is excluded from ruff (`pyproject.toml`) so an auto-fix never touches it
  (ruff wanted to remove its unused `Dict` import - that was reverted).
- Its `base_url="http://localhost:11434"` default argument is left in place,
  even though the project rule is "never hardcode localhost". Every caller now
  passes `base_url` explicitly from configuration, so the default is never used.
- The fallback stays **silent**: no exception, no error status. The only change
  is *observability from the outside*: `common/telemetry.py` reads the existing
  `embedding_fallback_count()` and exports it as the Prometheus counter
  `knowledgeai_embedding_fallback_total`, and counts fallback-answered calls in
  `knowledgeai_ollama_failures_total{operation="embed",reason="fallback"}`.
  The embedder itself does not know it is being watched.
- There is intentionally **no test that pins the file's hash**: the Ticket B
  fault commit and any proposed fix must be able to change this file and still
  pass CI, exactly as a real regression would.

If you are reading this because you want to make the fallback loud: that is
the *expected fix* the doctor should propose for Ticket B. It must not be
applied to `main` by hand.

---

## Repository and scope

- **D-1. Two systems in one repo, in separate top-level folders.** `patient/`
  is KnowledgeAI (deployed, monitored, broken on purpose); `doctor/` is the
  incident doctor. They share no Python code. The doctor keeps its own copy of
  the log-signature function (tested for equality with the patient's) rather
  than importing from the patient, so breaking the patient can never break the
  doctor.
- **D-2. The source project is only ever read.** Files were copied out of
  `D:\college\VII-sem\IDT\aidevops`; nothing there was modified. The copy is
  of its *working tree* at commit `c4f6d1f`, which had uncommitted changes
  (`evaluation/metrics.py`, untracked `evaluation/repo_graph.py`) - the working
  tree is what actually ran, so that is what was copied.
- **D-3. Line endings normalised to LF** (`* text=auto eol=lf`). The source
  files were CRLF. No other edit was made in the import commit.
- **D-4. Voice removed.** `voice_service/`, the voice UI, the `/api/voice/*`
  proxy routes and the voice settings rows were dropped. The repo-understanding
  question R05 pointed at the voice tests; it now asks about the guardrail tests
  so the harness still has a test-mapping question.
- **D-5. Frontend pages kept:** Chat, Dashboard, PipelineDebug,
  ModelComparison, Settings - as specified - **plus Documents**, because it is
  the only UI entry point to the ingestion service. Evaluation Lab and Chunk
  Inspector were dropped; the evaluation API stays on the gateway because the
  harness and MLflow logging use it.
- **D-6. Not copied:** `evaluation/sg_client.py` and
  `evaluation/output_testing.py` (Week-5 Sourcegraph / output-testing helpers
  used only by scripts that were not copied), old `data/` results, `mds/`.
- **D-7. Dependency versions pinned** to what the source project's venv ran
  (chromadb 1.5.9, fastapi 0.141.1, starlette 1.6.0, httpx 0.28.1 ...), so
  ML behaviour is unchanged. Development uses a Python 3.10 venv to match the
  `python:3.10-slim` images.

## Configuration

- **D-8. No address is a literal.** `patient/common/config.py` reads every
  address from the environment, then the repo `.env`, and raises a clear error
  if one is missing. Tests set their own values in `conftest.py`.
- **D-9. The stored Ollama URL defaults from `OLLAMA_BASE_URL`.** The app keeps
  its Settings-page override (stored in SQLite), so behaviour is unchanged; the
  *default* written into a fresh database now comes from configuration. A fresh
  database is created on each machine, so the Pavilion picks up its own value.
  If a database is ever carried between machines, re-save the URL in Settings.
- **D-10. ChromaDB runs as a server in compose.** Locally the original embedded
  `PersistentClient` is used; with `CHROMA_HOST` set, `vector_store` uses
  `HttpClient`. Three containers opening one on-disk store concurrently is
  unsafe; the client/server wire format is the same chromadb 1.5.9.

## Observability

- **D-11. Operational metrics live in `common/telemetry.py`**, not in anything
  called `metrics`: `api_gateway/app/metrics.py` and `evaluation/metrics.py`
  score answer quality and are a different thing entirely.
- **D-12. Pure ASGI middleware**, not `BaseHTTPMiddleware`, so a streamed (SSE)
  chat response is timed to its last byte, not its first header. Unhandled
  exceptions are logged once (with signature) and answered with a 500 by the
  middleware itself, so the traceback is not logged twice.
- **D-13. Chat outcomes are counted separately** (`answered`,
  `refused_input`, `refused_scope`, `refused_output`, `error`). The gateway
  swallows a failed retrieval call and still returns HTTP 200 with a refusal,
  so an HTTP error-rate alert alone would never see a dead retrieval service.
  Downstream call failures are counted per target for the same reason.
- **D-14. `print()` error reports in the gateway became structured error lines**
  with a log signature. Behaviour is otherwise unchanged. The embedder's own
  `print` is left alone (D-0).
- **D-15. Process memory comes from psutil**, not only from prometheus_client's
  process collector, because the latter only works on Linux and development
  happens on Windows. cAdvisor supplies container-level memory and OOM kills.
- **D-16. httpx's own INFO lines are kept.** They log every outgoing call with
  the request id attached, which is exactly the cross-service trace the doctor
  wants.
- **D-17. The obs.py from the MLOps capstone was not readable** at
  `D:\mlops\MLOps-Capstone-Project\flask_app\obs.py` (the file does not exist
  there, nor anywhere in that project). `patient/common/obs.py` was written from
  scratch to the specification. The same applies to `monitoring/alert.rules.yml`.
- **D-18. Lint scope.** ruff enforces pyflakes + syntax errors only, so the
  imported code is not reformatted; mass reformatting would bury the real
  changes in the commit history that the doctor searches.
