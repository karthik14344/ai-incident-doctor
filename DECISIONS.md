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

## Deployment, monitoring, CI/CD

- **D-19. One uvicorn worker per container.** Prometheus counters, the
  in-flight gauge and the embedding-fallback counter are per process; several
  workers would each report a fraction. Scale by containers, not workers.
- **D-20. Every patient image carries the whole backend package.** The
  services import each other's modules (the gateway uses the vector store and
  the evaluation scorers; retrieval uses the embedder). The dependency layer is
  identical in all four Dockerfiles, so it is stored once.
- **D-21. The knowledge base is built by a DVC stage and loaded by a one-shot
  `kb-loader`.** `build_kb` produces the documents, a ChromaDB store (tested:
  the chromadb 1.5.9 server reads a store built by the 1.5.9 embedded client)
  and the SQLite rows, stamped with a content-hash `kb_version` that also sits
  in git (`kb/manifest.json`, `cache: false`). kb-loader swaps the index in only
  when the version changed, and must run while ChromaDB is stopped. Documents
  uploaded through the UI live in the same collection and are replaced when a
  new KB version is loaded - acceptable for this project, noted here.
- **D-22. `embedder.py` is deliberately not a dependency of `build_kb`.** Its
  only edits in this project are the timeout fault and its fix, which do not
  change embedding values; listing it would mark the KB stale on every fault.
  The build refuses to publish if the hash fallback fired during the build.
- **D-23. DVC remote = MinIO in the stack** (`s3://dvc/knowledge-base`); the
  endpoint and credentials are machine-specific and live in `.dvc/config.local`
  (not committed).
- **D-24. Separate Ollama URLs for host and containers.** On Docker Desktop,
  `host.docker.internal` from the Windows host resolves to the LAN IP (where
  Ollama, bound to 127.0.0.1, is not listening) while from a container it
  reaches the host's loopback. Hence `OLLAMA_BASE_URL` (host tools) and
  `CONTAINER_OLLAMA_BASE_URL` (containers). On the Pavilion both are the
  laptop's LAN address.
- **D-25. Every host port is configurable.** The development laptop also runs
  another compose project that holds 8000, 9090, 3000 etc. This laptop's `.env`
  shifts every host port by +10000; defaults are the container ports.
- **D-26. MinIO comes from `quay.io/minio/minio`.** The Docker Hub
  `minio/minio` repository no longer serves images.
- **D-27. cAdvisor cannot see containers on Docker 29's containerd image
  store** ("failed to identify the read-write layer ID"), on Docker Desktop and
  on fresh Linux installs. Turning the containerd store off would affect other
  projects' images on the laptop, so instead a small stdlib
  `container-exporter` reads per-container memory, limit, restart count and OOM
  events from the Docker API. cAdvisor stays in the stack (raw-cgroup mode) for
  what it can see. OOM and near-limit alerts use the exporter's series.
- **D-28. nginx resolves upstreams per request** (Docker DNS, `resolver
  127.0.0.11`): containers are recreated with new IPs during deploys and fault
  injection, and startup-time resolution would pin a dead address.
- **D-29. Alert annotations are symptom-only and there are no inhibit rules.**
  Every symptom reaches the trigger log; picking the root is the doctor's job.
  Grafana "fault" annotations exist for human viewers only - the doctor never
  reads Grafana.
- **D-30. Scrape and rule evaluation every 5 s**, so faults surface within
  seconds; the alert-to-report time is one of the measured results.
- **D-31. Deploy records live outside compose** (`runtime/deploys.jsonl`, or
  `DEPLOY_LOG_PATH`, `/opt/aid/runtime` on the Pavilion). Failed deploys are
  recorded too; the "previous SHA" of a deploy is the last *successful* one.
  A dirty working tree cannot be deployed, so an image tag always describes
  exactly the code in it.
- **D-32. MLflow logging uses the REST API directly**, so the patient images
  gain no dependency. The server runs `--serve-artifacts` so clients need no
  S3 credentials.
- **D-33. The machine is memory-constrained.** With two compose stacks and the
  usual desktop apps, the laptop reached 0.2 GB free and the Docker engine
  stopped answering (HTTP 500 on every call) during an image build; restarting
  Docker Desktop recovered it. The stack itself uses about 1.4 GB. This is why
  timings measured here must be re-measured on the Pavilion (PAVILION.md).

## The doctor

- **D-34. Ollama's OpenAI-compatible endpoint is not used for reasoning.**
  Measured: an 11,000-token prompt sent to `/v1/chat/completions` was reported
  as 2,050 prompt tokens and answered from the tail only; `num_ctx` passed via
  `extra_body` was ignored. The Ollama provider therefore calls the native
  `/api/chat` with `num_ctx=16384` and the JSON schema as `format`. GLM,
  Gemini, Groq and OpenAI go through the OpenAI-compatible client as specified.
- **D-35. Fixes are requested as search/replace edits, not raw diffs.** Small
  models rarely produce a diff `git apply` accepts. The doctor renders the edits
  against the running commit into a real unified diff itself; that diff is what
  the report shows and what verification applies.
- **D-36. Verification = the patient's own test suite on a throwaway export**
  (`git archive` at the running commit, patched). "verified" requires the diff
  to apply and every test to pass. In the evaluation a fault-specific acceptance
  test is also run and reported *separately* - the suite says "nothing broke",
  the acceptance test says "the fault is fixed". Operational actions (restart,
  scale) cannot be tested on a copy and are always "unverified - needs human
  review".
- **D-37. Root-cause identity for scoring.** A hypothesis matches the truth if
  it names the guilty commit (when there is one) or, when the truth has no
  commit, names none and names the right component. `component` is an enum in
  the output schema so this is objective.
- **D-38. Symptom-to-vocabulary hints in lexical retrieval** (e.g. a rising
  fallback counter adds "embed", "fallback", "timeout" to the query). This is
  generic operational knowledge written once in `retrieval.py`, not knowledge of
  any injected fault; it is applied identically to every incident.
- **D-39. Prompt budget of ~6,500 tokens for every model**, trimmed longest-
  section-first, so llama3 (8k context) sees the same evidence as GLM.
- **D-40. The doctor's own embeddings are local**; if Ollama is down, retrieval
  degrades to lexical ranking and the report says so. Reasoning goes to the
  cloud provider with a local fallback.
- **D-41. Experimenter paths are invisible to the doctor.** `faults/`,
  `incidents/`, `doctor/eval/` and `RESULTS.md` hold fault scripts, recorded
  ground truth and the harness. They are not part of any deployed artifact, and
  their diffs would be the answer key, so the doctor drops them from commit
  file lists (commits touching only them are not candidates). Fault commits
  themselves use ordinary, realistic messages.

## Triggers

- **D-42. A git push never wakes the doctor.** The pipeline ends at the deploy
  record. Tests fail if anything under `deploy/` or `scripts/pipeline/`, or the
  workflow, references the doctor's entry points or URL.
- **D-43. Three entry points only.** `POST /incident` (alert-sink calls it for
  every firing alert, immediately after appending to the trigger log, in a
  background thread with retries), `POST /ticket` (free text + rough time; the
  doctor locates the onset from symptom metrics), and `python -m app.replay`
  (the only one the evaluation uses). A catch-up poll of alert-sink fills gaps
  while the doctor was down, sharing the same de-duplication.
- **D-44. Alerts on the same service within 10 minutes join one incident.**
  A single fault fires several alerts (e.g. ServiceDown, DownstreamCallFailures,
  ChatRequestsFailing); diagnosing each separately would triple the cost and
  count one fault three times.
- **D-45. Every incident is snapshotted before reasoning** (`bundle.json`:
  alert, related alerts, grouped logs, raw metric series and summaries, deploy
  records, the commit range with diffs, KB loads, source excerpts). Replays read
  only the snapshot.
- **D-46. Knowledge-base loads are change history too.** kb-loader appends to
  `runtime/kb_loads.jsonl`, the data counterpart of the deploy log; the doctor
  collects it, which is what lets a `data` fault have a guilty KB version.

## The pipeline: local stand-in for GitHub Actions

- **D-47. A local bare remote runs the CI/CD loop.** This build must not create
  a GitHub repository or send code off the machine, but a `push` fault has to go
  through a real `git push` and the pipeline. `runtime/pipeline.git` has a
  post-receive hook; `git push pipeline main` runs job 1 then job 2.
- **D-48. The steps exist once.** `scripts/pipeline/verify.sh` (lint + tests)
  and `scripts/pipeline/deploy.sh <sha>` (which calls `deploy/deploy.py`, the
  single implementation of build / KB swap / compose up / smoke test / rollback
  / deploy record / Grafana annotation). The hook and `.github/workflows/ci.yml`
  both call these scripts and contain no copy of the steps. Only environment
  preparation differs (pip install on GitHub runners, copying `/opt/aid/.env` on
  the Pavilion).
- **D-49. The hook is tracked** (`scripts/pipeline/post-receive`), installed by
  `scripts/pipeline/init_local_pipeline.sh`; `verify.sh` fails if the installed
  copy differs from the tracked one.
- **D-50. The hook is synchronous and bounded**: `git push` returns when the
  deploy is done, each job runs under `timeout ${PIPELINE_TIMEOUT_S:-2400}`,
  all output is tee'd to `runtime/pipeline-logs/<sha>.log`, and the log path is
  printed on success, failure and timeout. Each run is also appended to
  `runtime/pipeline_runs.jsonl`.
- **D-51. Every deploy record says which pipeline produced it**
  (`pipeline: local | github | manual`). **All results in RESULTS.md measured
  on this laptop come from the local stand-in** and are labelled as such; after
  the switch to GitHub Actions on the Pavilion they must be re-measured and
  reported separately, never merged into the same table silently. The local
  pipeline runs the identical scripts, but its timings (no network hop, no
  runner queue) are not comparable to Actions timings.

## Fault injection

- **D-52. Every fault carries a `delivery`** - `push` (a real commit through the
  pipeline; f1, f4, f5, f6), `environment` (a recorded script changes the world;
  f2, f3, f3b) or `data` (the knowledge base changes underneath; f7). Push faults
  are validated by `faults/selfcheck.py`: with the fault applied the existing
  suite still passes (the bug would ship) and the fault's acceptance test fails.
- **D-53. Distractor commits are real, harmless work** (runbook notes, new passing
  tests, explanatory comments in the very files the faults touch), applied once
  each, never reverted. Two push variants: `guilty_last` (the latest deploy holds
  the guilty commit, followed by a distractor in the same deploy) and
  `guilty_earlier` (a distractor-only deploy lands after the guilty one), so the
  "blame the most recent deploy" baseline is tested both ways.
- **D-54. f1's trigger is a noisy neighbour on the shared Ollama.** Measured: with
  llama3 and mistral busy, the first nomic-embed-text call waited 43 s (idle: 0.3 s).
  45 s covers that; 10 s turns it into silent fallback vectors. The fault run keeps
  two bigger models generating in turn (as the Model Comparison page would), which
  is a realistic condition the original timeout was written for. Ground truth stays
  `code_defect` (the commit), even though the neighbour is the trigger.
- **D-55. f5's typo is on an input-dependent path in the gateway**, not in the
  source-preview code: no chunk in the corpus is under 150 characters, so a typo in
  the short-chunk branch would never run. Keyword queries (no '?') take the broken
  branch; the load generator includes some.
- **D-56. f7 removes documents rather than swapping the embedding model.** No
  installed generative model serves embeddings on this Ollama ("does not support
  embeddings"), and downloading a second embedding model onto the user's Ollama was
  avoided. The KB version is built from 4 of 10 documents with the new
  `KB_INCLUDE_DOCS` option and loaded by kb-loader, which records the load.
- **D-57. Lenient class credit for f3b and f6.** A wrong address and a too-tight
  timeout are arguably `configuration`; the strict class is reported first, the
  lenient one alongside.
- **D-58. Background traffic runs for the whole campaign** (chat 0.2/s, search
  0.4/s), so every incident has a real baseline window. 10-minute cool-downs keep
  one run's symptoms out of the next one's baseline and out of its incident group.

## Keeping deploys from looking like incidents

- **D-59.** A deploy recreates containers, so every alert that a recreate can trip
  was hardened: `RestartLoop` counts Docker restarts (reset by a recreate) instead
  of process start times; `MemoryClimbing` ignores a process's first 10 minutes;
  `ServiceDown` needs 45 s; `HighErrorRate` needs 1 minute. The fault runner only
  accepts alerts that *begin* after the break, and it finds the report of the
  incident that exact alert opened. The first campaign attempt had picked up an
  alert that started 9 s before the break.
- **D-60. The deploy script hot-reloads Prometheus and Alertmanager.** Their config
  is bind-mounted; without a reload a changed rule file kept the old rules firing.
- **D-61. Latency thresholds come from the measured healthy baseline**: chat p95
  16.9 s (p50 1.5 s), search p95 0.29 s on the laptop under background traffic.
  A single 15 s threshold fired on a healthy system. Now 40 s for chat/generation,
  5 s for search/retrieve. To be re-measured on the Pavilion.
- **D-62. A chat refusal alert** (`ChatAnswersRefused` > 30% for 2 minutes; 0 of
  45 in the baseline) is the symptom of a knowledge base that no longer covers the
  questions.

## The doctor on a shared, memory-starved laptop

- **D-63. The live doctor matches the patient's Ollama context.** With no cloud key
  the live doctor falls back to llama3.2 - the patient's own model on the same
  Ollama. At num_ctx 16384 it made Ollama reload the model on every switch (a normal
  chat took 35.7 s), so the doctor's own diagnoses showed up as latency alerts and
  triggered more diagnoses. On this laptop `.env` sets `DOCTOR_OLLAMA_NUM_CTX=4096`,
  `DOCTOR_MAX_PROMPT_TOKENS=3000`, `DOCTOR_MAX_COMPLETION_TOKENS=900` for the live
  doctor. **Live reports on the laptop therefore use a reduced evidence budget;**
  the evaluation replays run offline at 16384 / 6500 / 2500.
- **D-64. Joining rules.** An alert joins an open incident on the same service
  within 10 minutes only while that incident is still waiting for its window; after
  the doctor has started, a later alert is a new incident. Incidents already on disk
  are not re-opened after a restart; ones mid-flight become `interrupted`.
- **D-65. Incident files are written atomically under one lock** (a race between
  the worker, the catch-up poll and request handlers corrupted a file and cost one
  live diagnosis).
- **D-66. The other compose project on the laptop was stopped** (`docker compose
  -p mlops-incident stop`, reversible with `start`) at the user's request, after the
  Docker engine stopped answering twice under memory pressure. Claude Code's
  low-memory guard also stopped background jobs once (Opera was using 5.6 GB); the
  campaign then ran background traffic inside its own process to use less memory.

## Evaluation

- **D-67. Without a cloud key, the ablation runs on llama3 (8B)** as a local
  stand-in for GLM; RESULTS.md says so in the table header. GLM rows appear as
  "not run" until `DOCTOR_API_KEY` is set, and the same command then fills them.
- **D-68. Repeats use different seeds** (1000 + repeat); with a fixed seed a local
  model would repeat itself and the reported spread would be meaningless.
- **D-69. Past incidents for the third arm are the other recorded incidents'
  ground-truth resolutions, earlier ones only** (chronological leave-future-out), in
  an index separate from the live one.
- **D-70. The "most recent deploy" baseline** names the newest commit of the latest
  successful deploy before the alert and calls it a code defect. Its deploy-level
  hit rate (guilty commit anywhere in that deploy) is reported too.

- **D-71. A real leak I introduced, found by the monitoring.** Moving ChromaDB to
  a server (D-10) created a `chromadb.HttpClient` on every vector-store call; each
  leaked ~1.35 MB (measured). Under ordinary background traffic the retrieval
  container went from 106 MB to its 512 MB limit in minutes and was OOM-killed,
  and the first clean-looking campaign run was diagnosed as "capacity / not enough
  memory in retrieval" - reasonably, given the evidence. The client is now cached
  per server (+0 MB for 150 calls). Every run before that fix was discarded as
  contaminated (`runtime/fault-runs/_contaminated-*`), not counted.
- **D-72. Failure alerts must outlast a deploy.** A recreate produces ~20 s of
  failed calls, and a 20 s burst stays inside a 2-minute `rate()` window for two
  minutes, so `for:` alone did not help: f1's first "alert" was
  DownstreamCallFailures from the guilty deploy's own recreate, 52 s after the
  push. Now `DownstreamCallFailures` / `OllamaCallFailures` need failures in every
  30 s window for a minute, `HighErrorRate` and `ChatRequestsFailing` use 1-2 minute
  windows with 2 minutes of `for`. promtool tests prove a 20 s burst stays quiet and
  a steady failure stream still pages. For that run the real symptom
  (EmbeddingFallbackActive, 45 s after the deploy) was diagnosed separately by the
  doctor; the run's record points at that incident and notes the blip.
- **D-73. The doctor is not redeployed with the patient.** Every image used the
  deploy's SHA tag, so each patient deploy recreated the doctor and interrupted a
  diagnosis in progress. The doctor, alert-sink, container-exporter, mlflow and
  frontend are now tagged with the SHA of the last commit that changed their own
  code (`<NAME>_IMAGE_TAG`, computed by deploy.py and stored in the deploy record).
- **D-74. The capacity surge was calibrated by measurement.** 1.2 chats/s with 32
  in flight did not saturate the model (p95 ~12 s): Ollama runs several requests in
  parallel. The first f2 run is recorded as "did not reproduce". At 4/s with 96 in
  flight, throughput caps at 1.37/s and p95 reaches 75-88 s.
