# Lecture guide: AI Incident Doctor, start to finish in 2 hours

You can teach the whole project from this one file. It has a checklist for before class, a
minute-by-minute plan, what to say and what to show in every block, the exact commands, and a plan B for
every live demo.

> **⚠ NEVER open `.env` on the projector.** It holds the GLM API key, the Grafana admin password and the
> MinIO password. Nothing in this guide needs `.env` on screen. If you must edit it, turn the projector off
> or switch to "duplicate off" first. When you log in to Grafana, type the password with the projector
> frozen or blanked.

**Where the numbers come from.** Every number in this guide comes from one of three places:
- **RESULTS.md** or **DECISIONS.md**: the measured results of the project.
- **A run on 2026-09-24**: I ran every demo on this laptop, at commit `73e80cf`, with all ports shifted
  +10000. Those numbers are marked *(run 2026-09-24)*, and the raw output is saved in
  [`docs/lecture/backup/`](lecture/backup/).
- If something could not be checked, it says **not verified**.

**Times are in UTC** (the laptop's clock shows IST, which is UTC + 5:30).

---

## Contents

1. [Before class: the checklist (T-60 min)](#1-before-class-the-checklist-t-60-min)
2. [The 120-minute plan](#2-the-120-minute-plan)
3. [The story, section by section](#3-the-story-section-by-section)
   - [a. The problem](#a-the-problem-why-apps-break-and-why-finding-the-cause-is-slow)
   - [b. The patient app (KnowledgeAI)](#b-the-patient-app-knowledgeai)
   - [c. Observability: logs, metrics, request ids](#c-observability-logs-metrics-and-request-ids)
   - [d. Prometheus from zero](#d-prometheus-from-zero)
   - [e. Grafana dashboards](#e-grafana-dashboards)
   - [f. Alerts](#f-alerts-the-smoke-alarms)
   - [g. The pipeline, DVC and MLflow](#g-the-pipeline-dvc-and-mlflow)
   - [h. The doctor, step by step](#h-the-doctor-step-by-step)
   - [i. The big live demo](#i-the-big-live-demo-break-it-watch-it-get-diagnosed)
   - [j. The ticket demo](#j-the-ticket-demo-a-person-reports-a-problem)
   - [k. The 8 faults](#k-the-8-faults)
   - [l. How the doctor was tested](#l-how-the-doctor-was-tested)
   - [m. Key design decisions](#m-key-design-decisions)
4. [Diagrams](#4-diagrams)
5. [Likely questions, with short answers](#5-likely-questions-with-short-answers)
6. [Command cheat sheet (one page)](#6-command-cheat-sheet-one-page)
7. [Troubleshooting during the lecture](#7-troubleshooting-during-the-lecture)
8. [Glossary](#8-glossary)
9. [Appendix: what was run, what was not](#9-appendix-what-was-run-what-was-not)

---

## 1. Before class: the checklist (T-60 min)

You need two terminal windows, both opened in `D:\college\VII-sem\IDT\ai-incident-doctor`:

- **Window A: PowerShell.** Use it for checks and for talking to the services.
- **Window B: Git Bash.** Use it for `git push`, the fault script and the load generator. These were
  tested in Git Bash.

### T-60: memory

This laptop has 15.2 GB of RAM. Docker, Ollama and a browser all need a share of it. **You need at least
2.5 GB available** before you start. DECISIONS.md D-33 records the Docker engine freezing when this laptop
fell to 0.2 GB free.

Window A:
```powershell
(Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue
Get-Process | Group-Object ProcessName | ForEach-Object { [pscustomobject]@{Name=$_.Name; MB=[math]::Round(($_.Group | Measure-Object WorkingSet64 -Sum).Sum/1MB)} } | Sort-Object MB -Descending | Select-Object -First 10 | Format-Table -AutoSize
```
*(run 2026-09-24)* With Opera (2.5 GB), Devin (0.6 GB) and Chrome open, only 1.7 GB was available. After
closing Opera and Devin it was 2.6 GB. Close everything you won't use: the heavy browser, other IDEs and
Task Manager. **Keep one browser** for the demo tabs.

### T-55: start things, in this order

1. **Docker Desktop.** Start it from the Start menu and wait until it shows the engine is running. Test it
   with `docker ps`: it must print a table header, not an error.
2. **Ollama.** It is not part of Docker. It runs on Windows itself.
   ```powershell
   Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
   Invoke-RestMethod http://127.0.0.1:11434/api/version
   ```
   You should see a version number (`0.34.3` on 2026-09-24; it answered within 2 s of starting).
3. **The stack** (all the Docker containers). They already exist, so start them:
   ```powershell
   docker start $(docker ps -aq --filter "name=^aid-")
   ```
   This prints 19 container ids. Wait about 60 s. *(run 2026-09-24: every container reported "healthy"
   within about 50 s.)*
   Two of them, `aid-kb-loader-1` and `aid-minio-init-1`, are one-shot setup jobs. They show
   **"Exited (0)"**, which is correct.
4. **Normal background traffic.** The doctor compares every problem with the 30 minutes before it, so the
   app needs ordinary users all the time. Start it **at least 30 minutes before the big demo**:
   ```powershell
   Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "-m","faults.background_traffic","--hours","4" -WindowStyle Hidden -PassThru
   ```
   It sends 0.2 chat questions/s and 0.4 searches/s, like DECISIONS.md D-58, and runs hidden for 4 hours.
   It shows up as **two** `python.exe` processes, because the venv launcher starts a child; that is normal.
   The stop command is in the [cheat sheet](#6-command-cheat-sheet-one-page).

### T-45: health check

Window A. Paste all of it at once:
```powershell
$urls = [ordered]@{
 'frontend'='http://localhost:13001/'; 'gateway'='http://localhost:18000/api/health'; 'ingestion'='http://localhost:18001/health'; 'retrieval'='http://localhost:18002/health'; 'llm'='http://localhost:18003/health';
 'chroma'='http://localhost:18010/api/v2/heartbeat'; 'doctor'='http://localhost:18100/health'; 'grafana'='http://localhost:13000/api/health'; 'prometheus'='http://localhost:19090/-/healthy';
 'alertmanager'='http://localhost:19093/-/healthy'; 'alert-sink'='http://localhost:19095/health'; 'loki'='http://localhost:13100/ready'; 'alloy'='http://localhost:22345/-/ready';
 'cadvisor'='http://localhost:18080/healthz'; 'mlflow'='http://localhost:15000/health'; 'minio'='http://localhost:19000/minio/health/live'; 'ollama'='http://localhost:11434/api/version' }
foreach ($k in $urls.Keys) { try { $r = Invoke-WebRequest $urls[$k] -UseBasicParsing -TimeoutSec 10; "{0,-13} {1}" -f $k, $r.StatusCode } catch { "{0,-13} FAILED  {1}" -f $k, $_.Exception.Message } }
Invoke-RestMethod http://localhost:18100/health
```
**Expected:** 17 lines that each end in `200`, then the doctor's status with
`primary : glm:glm-4.5-flash`, `fallback : ollama:llama3.2`, `busy :` (empty) and `queued : 0`.
*(run 2026-09-24: all 17 were 200. Saved in [`backup/00_health_check.txt`](lecture/backup/00_health_check.txt).)*

**Check the internet.** The doctor reasons with an online model (GLM):
```powershell
curl.exe -s -o NUL -w "%{http_code}`n" --max-time 10 https://api.z.ai/api/paas/v4/models
```
`000` means **no connection**. That happened on 2026-09-24 at 10:45 UTC, when the Wi-Fi lost its internet.
Any other number means Z.ai answered. That case is **not verified**, because the connection never came back
during testing. If you get `000`, read [Troubleshooting → internet](#the-internet-fails).

### T-40: open the browser tabs (in this order)

| # | Tab | URL | Why |
|---|---|---|---|
| 1 | The app | http://localhost:13001 | Chat Assistant and the **Incidents** page (left sidebar) |
| 2 | Grafana dashboard | http://localhost:13000/d/knowledgeai-ops/knowledgeai-operations | The "car dashboard" |
| 3 | Grafana Explore | http://localhost:13000/explore | For following a request id. **Log in first** (see below) |
| 4 | Prometheus query | http://localhost:19090/query | Typing PromQL |
| 5 | Prometheus alerts | http://localhost:19090/alerts | The 16 alarm rules and their state |
| 6 | Alertmanager | http://localhost:19093 | Alarm routing |
| 7 | alert-sink log | http://localhost:19095/alerts | The raw trigger log (JSON) |
| 8 | MLflow | http://localhost:15000/#/experiments/2 | The evaluation runs |
| 9 | Doctor API | http://localhost:18100/docs | The doctor's three doors (optional) |

All of these returned HTTP 200 on 2026-09-24. I did not click through the pages visually, so the page
layouts are **not verified**. The data behind every demo was checked through the same services' APIs.

**Log in to Grafana before class.** Anonymous visitors can view the dashboard, but Grafana does not let
them use **Explore**. Open http://localhost:13000/login and log in as `admin`. The password is
`GRAFANA_ADMIN_PASSWORD` in `.env`. Read it **off the projector**. *(run 2026-09-24: the admin login worked
and has Explore permission.)*

### T-30: dry run

Ask one question in the app: Chat Assistant → "What is the minimum attendance required to sit semester
examinations?". It should answer "75%" within a few seconds. Then leave everything running.

**Do not run `git push pipeline main` before the big demo.** See [g](#g-the-pipeline-dvc-and-mlflow) for
why.

### If something is not healthy

| What you see | What to do |
|---|---|
| `docker` says "cannot connect" / "error during connect" | Docker Desktop is not running. Start it and wait until `docker ps` works. |
| A service line says FAILED | `docker ps -a --filter "name=^aid-"`. Then `docker start aid-<name>-1`, and wait 30 s. |
| `ollama` FAILED | Run the `Start-Process ... ollama app.exe` line again. |
| gateway FAILED but the others are fine | The gateway waits for chroma, retrieval and llm to be healthy. Wait 30 s and check again. |
| doctor shows `primary : glm:glm-4.6` | `.env` still has the old model name. See [Troubleshooting → doctor](#the-doctor-report-says-diagnosis-failed). |
| Available memory is under 2 GB | Close programs. Never start the demo like this. |
| Many containers keep restarting | Memory is too low. Close programs, then `docker restart` them. |

---

## 2. The 120-minute plan

95 minutes of teaching + a 10-minute break + 15 minutes of Q&A = **120 minutes**.

| Clock | Min | Block | Goal | Live? | Check question |
|---|---|---|---|---|---|
| 0:00-0:03 | 3 | Opening | Promise: "by 2:00 you will watch an AI find a real fault" | - | - |
| 0:03-0:10 | 7 | **a** The problem | Why finding a cause is slow and costly | - | "What is the difference between a symptom and a cause?" |
| 0:10-0:20 | 10 | **b** The patient app | RAG, the 4 services, one question's journey | ✅ ask a question | "Which service talks to the AI model?" |
| 0:20-0:28 | 8 | **c** Observability | Logs, metrics, request ids | ✅ follow one request id | "Why does every log line carry a request id?" |
| 0:28-0:40 | 12 | **d** Prometheus | Counter, gauge, histogram, rate, p95 | ✅ load generator, values change | "If p95 is 7 s, what share of requests took longer?" |
| 0:40-0:46 | 6 | **e** Grafana | Reading a dashboard | ✅ the dashboard | "Which panel would show a memory leak?" |
| 0:46-0:56 | 10 | **BREAK** | Leave background traffic running | - | - |
| 0:56-1:04 | 8 | **f** Alerts | `expr`, `for:`, symptoms only; the alarm path | ✅ rules page | "Why doesn't the alarm say *why*?" |
| 1:04-1:10 | 6 | **g** Pipeline, DVC, MLflow | push → verify → deploy; data and run versioning | backup log + MLflow | "What stops a broken commit from being deployed?" |
| 1:10-1:24 | 14 | **h + i** The doctor + **the big live demo** | Break it, the alarm, the report, the automatic repair | ✅ **main demo** | "Did the doctor blame a commit? Should it have?" |
| 1:24-1:28 | 4 | **j** Ticket | A person reports a symptom in words | ✅ ticket | "How did it find *when* the problem started?" |
| 1:28-1:31 | 3 | **k** The 8 faults (+ live `git push`) | What was broken, how, which alarm | ✅ pipeline push runs in the background | "Which fault did monitoring miss?" |
| 1:31-1:38 | 7 | **l** How it was tested | Replay, baseline, ablation, models, honesty | MLflow | "Why is 'blame the latest deploy' a fair baseline?" |
| 1:38-1:43 | 5 | **m** Design decisions | The why behind 8-10 choices | - | "Why can't a git push wake the doctor?" |
| 1:43-1:45 | 2 | Wrap-up | Three things to remember | - | - |
| 1:45-2:00 | 15 | **Q&A** | See [section 5](#5-likely-questions-with-short-answers) | - | - |

**Why the big demo starts at 1:10.** The load-generator demo in **d** ends near 0:36. The doctor compares
the 10 minutes before an alarm with the 30 minutes before that. Starting 34 minutes later keeps the two
windows fair.

**Why the live `git push` happens at 1:28, after the doctor demos.** The push deploys the commit that
contains this guide and its backup files. Those files include the true answer for the retrieval-down fault.
The doctor reads every commit deployed in the last 6 hours, so pushing before the demo would show it the
answer. That is the same reason the doctor never reads `faults/` or `incidents/` (DECISIONS.md D-41). Teach
the pipeline at 1:04 with the saved log, and run it for real at 1:28.

---

## 3. The story, section by section

Each section has: **Goal**, **Say** (talking points), **Show** (the demo, with real output), an
**"Explain it to…" box**, and a **Check** question.

### Opening (0:00-0:03)

**Say:** "This project has two systems. The **patient** is a normal AI app that answers questions about
university rules. The **doctor** is a second AI system that watches the patient. When the patient gets
sick, the doctor collects evidence, works out the cause, proposes a fix, tests the fix on a spare copy, and
writes a report. It never touches the patient itself. Today I will break the patient in front of you, and
we will watch the doctor work."

---

### a. The problem: why apps break, and why finding the cause is slow

**Goal:** everyone understands *symptom versus cause*, and why finding the cause is the expensive part.

**Say:**
- Apps break for three kinds of reasons:
  1. **A change**: someone pushed buggy code or a bad setting.
  2. **The surroundings**: a service it depends on went down, or too many users arrived at once.
  3. **The data**: the documents it answers from changed.
- What people *see* is a **symptom**: "answers are slow", "it says it knows nothing", "errors".
  A symptom does not name its cause. "Slow" can mean too many users, a broken dependency, or a bad commit.
- Finding the cause means reading logs, graphs and recent changes across several services. It is slow
  detective work, and while it goes on, users are unhappy.
- The obvious shortcut, "just undo the latest deploy", is often wrong. In this project's measurements it
  was wrong for **every** fault that was not caused by a commit. RESULTS.md: the "blame the most recent
  deploy" baseline had a false attribution of **1.00** on environment faults.
- **Analogy:** a hospital. A patient says "I have a headache" (symptom). A doctor checks temperature,
  blood pressure and history (evidence) before deciding it is dehydration, not a tumour (cause). Doing that
  well takes time.

**Show:** nothing yet. Point at the first box chart in [section 4](#4-diagrams).

> **Explain it to…**
> - **A non-programmer:** the app is the patient. "It's slow" is the patient saying "I feel ill". The
>   doctor's job is to find out *why*.
> - **A programmer:** most debugging time goes into localisation (which change, which service), not the
>   fix itself.
> - **An ML person:** it is a classification + ranking problem with noisy, multi-modal evidence (logs,
>   time series, diffs) and a strong but misleading prior ("the last deploy did it").
> - **An ops person:** this is the MTTR problem, specifically the "diagnose" part between "alert fired"
>   and "mitigated".

**Check:** "A user says *the assistant is slow*. Is that a symptom or a cause?" (A symptom.)

---

### b. The patient app (KnowledgeAI)

**Goal:** understand RAG in plain words, the 4 services, ChromaDB and Ollama, and one question's journey.

**Say:**
- **RAG** (retrieval-augmented generation) is an *open-book exam* for an AI. Before answering, the app
  **looks up** the relevant pages in its own documents, then asks the AI model to answer **using those
  pages**. So the answer is grounded in real university documents, not in the model's memory.
- The knowledge base is 10 university policy documents (attendance, exams, hostel, library,
  scholarships, lab safety, placements, grievances, calendar, welcome guide), cut into 21 chunks
  (`kb/manifest.json`).
- The app has four services, each a small web server (FastAPI):
  - **gateway** (:18000) is the front door. It checks the question (guardrails), then calls the others.
  - **retrieval** (:18002) turns the question into an **embedding** (a list of 768 numbers that captures
    meaning) and asks **ChromaDB** for the closest chunks.
  - **llm** (:18003) asks **Ollama** (the local AI model server, `llama3.2`) to write the answer from
    those chunks.
  - **ingestion** (:18001) cuts uploaded documents into chunks and stores them.
- **ChromaDB** (:18010) is a **vector store**: a library where books are shelved by *meaning*, not by title.
- **Ollama** (:11434) runs the AI models on this laptop's GPU. It is **not** in Docker.

**Show (live, 1 min).** Tab 1 (the app) → **Chat Assistant** → type:
> What is the minimum attendance required to sit semester examinations?

*(run 2026-09-24, same question through the API)* The answer took **2.6 s**:
> "…students are required to maintain a minimum attendance of 75% in each registered course to be eligible
> to sit for semester examinations."

Four sources came back. The top one was `attendance_policy.pdf` page 1, similarity **0.8741**. Nine
guardrail checks all said "allowed", including a scope check: "top similarity 0.8741 is within the
corpus". Full output: [`backup/02_ask_a_question.txt`](lecture/backup/02_ask_a_question.txt).

Point out on screen: the answer, the **sources**, and that the answer streams in word by word.

**The journey of one question** (draw it or project it):
```text
 you ──question──▶ frontend :13001 ──▶ gateway :18000  (guardrails: is this allowed? in scope?)
                                          │
                                          ├──▶ retrieval :18002 ──▶ Ollama: embed the question (768 numbers)
                                          │                    └──▶ ChromaDB :18010: 4 nearest chunks
                                          │
                                          └──▶ llm :18003 ──▶ Ollama llama3.2: write the answer from the chunks
                                                   │
 you ◀──── answer streams back word by word ◀──────┘
```

> **Explain it to…**
> - **A non-programmer:** it's an open-book exam. First it finds the right pages, then it writes the answer
>   from them.
> - **A programmer:** four FastAPI microservices over HTTP; the gateway orchestrates; streaming via
>   server-sent events.
> - **An ML person:** dense retrieval with `nomic-embed-text` (768-dim), top-k=4 by cosine similarity, then
>   generation with llama3.2 (3B), with a similarity threshold as the scope guardrail.
> - **An ops person:** 4 stateless services + one stateful vector store + an external model server. Each
>   service has its own memory limit (gateway 768 MB, retrieval 512 MB, llm 384 MB in `docker-compose.yml`).

**Check:** "Which service talks to the AI model?" (llm for writing, retrieval for embeddings; both go
through Ollama.)

---

### c. Observability: logs, metrics and request ids

**Goal:** know the three ways to see inside a running system, and follow one request through several
services.

**Say:**
- **Observability** means being able to tell what is happening inside a system from what it outputs.
  There are three kinds of output:
  - **Logs** are a *diary*: one line per event. Here, every line is JSON with the time, level, service,
    running `git_sha` and a `request_id` (`patient/common/obs.py`).
  - **Metrics** are *vital signs*: numbers measured all the time (requests per second, errors, memory).
  - **Request ids** are a *parcel tracking number*. The gateway gives each request an id and passes it to
    every service it calls (the `X-Request-ID` header, `patient/common/telemetry.py`). Search for the id,
    and you see that request's whole journey.
- Errors also carry a **log signature**: a short fingerprint of the error with the changing parts (ids,
  numbers, paths) removed. The same bug therefore always gets the same signature and can be counted.
- **Loki** stores the logs, **Alloy** ships them from the containers to Loki, and **Grafana** lets you
  search them.

**Show (live, 3 min).** First send a question with **your own** tracking number (Window A):
```powershell
$body = @{ question = "What is the minimum attendance required to sit semester examinations?"; stream = $false } | ConvertTo-Json
$r = Invoke-WebRequest http://localhost:18000/api/chat -Method Post -ContentType 'application/json' -Body $body -Headers @{ 'X-Request-ID' = 'lecture-demo-001' } -UseBasicParsing
$r.Headers['X-Request-ID']
```
It prints `lecture-demo-001`: the id came back. Then, in Grafana **Explore** (tab 3), choose data source
**Loki**, switch to **Code**, and paste:
```text
{compose_service=~".+"} |= "lecture-demo-001"
```
Or do the same from Window A (verified):
```powershell
$end = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()*1000000; $start = $end - 600L*1000000000
$q = '{compose_service=~".+"} |= "lecture-demo-001"'
$r = Invoke-RestMethod "http://localhost:13100/loki/api/v1/query_range" -Body @{ query=$q; start=$start; end=$end; limit=100; direction='forward' }
$lines = foreach ($s in $r.data.result) { foreach ($v in $s.values) { [pscustomobject]@{ t=[long]$v[0]; svc=$s.stream.compose_service; line=$v[1] } } }
$lines | Sort-Object t | ForEach-Object { "{0,-10} {1}" -f $_.svc, ($_.line.Substring(0, [Math]::Min(200, $_.line.Length))) }
```
*(run 2026-09-24)* This returned **10 log lines from 3 services**, in time order:
- **retrieval**: the embedding call to Ollama, 3 ChromaDB calls, then `POST /retrieve` done, all within
  **12 ms** (10:08:06.735 → .747)
- **gateway**: "retrieval answered 200", then "calling llm /generate"
- **llm**: the Ollama generate call, then `/generate` done
- **gateway**: `/api/chat` done at 10:08:09.119, **2.4 s** after the first line

Full lines: [`backup/03_request_id_trace.txt`](lecture/backup/03_request_id_trace.txt).

> **Explain it to…**
> - **A non-programmer:** like tracking a parcel. The same number appears at every depot it passes through.
> - **A programmer:** a correlation id in a context variable, added to every outgoing httpx call and every
>   JSON log line.
> - **An ML person:** logs become features. The doctor groups error lines by signature and compares counts
>   before and during the incident.
> - **An ops person:** a cheap form of distributed tracing without a tracing backend. Structured JSON
>   logs in Loki, labelled by compose service.

**Check:** "Why does every log line carry the request id?" (So you can follow one user's request across
services.)

---

### d. Prometheus from zero

**Goal:** know what a metric is, counter vs gauge vs histogram, and what `rate()` and
`histogram_quantile()` mean. Then **see the numbers change** live.

**Say:**
- **Prometheus** visits every service every **5 s** (DECISIONS.md D-30), reads its `/metrics` page and
  stores the numbers over time. This is called "scraping".
- There are three kinds of metric. The analogy is a car dashboard:
  - A **counter** is the **odometer**. It only goes up, for example
    `knowledgeai_http_requests_total` (all requests ever served).
  - A **gauge** is the **fuel gauge**. It goes up and down, for example
    `knowledgeai_http_requests_in_flight` (requests being served right now), or memory.
  - A **histogram** is an **exam-marks distribution**: how many requests took under 0.05 s, under 0.1 s,
    … under 120 s. Here that is `knowledgeai_http_request_duration_seconds_bucket`, with 16 buckets from
    0.05 s to 120 s (`telemetry.py`).
- **`rate(counter[1m])`** turns an odometer into a **speedometer**: how much the counter grew per second
  over the last minute.
- **`histogram_quantile(0.95, …)`** gives **p95 latency**: "95 out of 100 requests were faster than this".
  It tells you about the slow users, which an average hides.

**Show (live, about 8 min).**

1. Tab 4 (Prometheus query). Paste **Q2**, then **Q3**, **Q4** and **Q6** from the table below. Press
   *Execute*, then the *Graph* tab. Note the values.
2. Window B (Git Bash). Send extra searches, 5 per second for 2 minutes:
   ```bash
   .venv/Scripts/python.exe loadgen/loadgen.py --mode search --rate 5 --concurrency 10 --duration 120
   ```
3. After about 90 s, re-run Q2, Q3 and Q6 in Prometheus. The request rate jumps. Search p95 barely moves,
   because searches are cheap.
4. Now make the **expensive** thing busy: 1 chat per second for 2 minutes. This one runs the AI model:
   ```bash
   .venv/Scripts/python.exe loadgen/loadgen.py --mode chat --rate 1 --concurrency 8 --duration 120
   ```
5. After about 100 s, re-run Q6 and Q7. **Chat p95 goes up** and in-flight requests appear.

Each load run prints a summary when it finishes. *(run 2026-09-24)*
- **Search run:** 601 requests, **0 errors**, client-side p95 **0.063 s**, 121 s.
- **Chat run:** 123 requests, **0 errors**, p50 **2.945 s**, p95 **6.548 s**, 125 s.

**Ready-to-paste PromQL, with the values seen on 2026-09-24.** "Before" = background traffic only;
"during" = while the load generator ran. All of it is in
[`backup/04_prometheus_queries.txt`](lecture/backup/04_prometheus_queries.txt).

| # | Query | Meaning | Value seen |
|---|---|---|---|
| Q1 | `up{job=~"gateway\|ingestion\|retrieval\|llm"}` | 1 = Prometheus can reach the service, 0 = it can't | all **1** (during the big demo, retrieval → **0**) |
| Q2 | `knowledgeai_http_requests_total{service="gateway",endpoint="/api/retrieval/search"}` | a raw **counter**: searches served since start | **42** before → **575** during search load |
| Q3 | `sum by (service) (rate(knowledgeai_http_requests_total{endpoint!="/metrics"}[1m]))` | requests per second, per service | gateway **0.82** → **5.58** req/s |
| Q4 | `sum by (endpoint) (rate(knowledgeai_http_requests_total{service="gateway",endpoint=~"/api/chat\|/api/retrieval/search"}[1m]))` | what users are doing: chats vs searches | search **0.55** → **5.36**; chat **0.22** → **1.16** (chat load) |
| Q5 | `sum by (service) (rate(knowledgeai_http_requests_total{status=~"5..",endpoint!="/metrics"}[5m])) / sum by (service) (rate(knowledgeai_http_requests_total{endpoint!="/metrics"}[5m]))` | share of requests that failed with a 5xx error | **empty** = no errors yet (during the big demo the gateway's 1-minute version reached **0.58**) |
| Q6 | `histogram_quantile(0.95, sum by (le, endpoint) (rate(knowledgeai_http_request_duration_seconds_bucket{service="gateway",endpoint=~"/api/chat\|/api/retrieval/search"}[2m])))` | **p95 latency** of chats and searches | chat **2.67 s** → **6.96 s** (chat load); search **0.097 s** → **0.078 s** (search load) |
| Q7 | `sum by (service) (knowledgeai_http_requests_in_flight)` | a **gauge**: requests being served right now | gateway **0** → **2**, llm **0** → **1** (chat load) |
| Q8 | `sum by (outcome) (rate(knowledgeai_chat_answers_total[5m]))` | how chats ended: answered, refused, error | answered **0.058/s** → **0.53/s** |
| Q9 | `knowledgeai_process_resident_memory_bytes / 1048576` | memory per service, in MiB (a gauge) | llm **58**, ingestion **91**, retrieval **93** → **105**, gateway **97** |
| Q10 | `knowledgeai_embedding_fallback_total` | the "silent failure" counter (DECISIONS.md D-0); must stay **0** | **0** on both services |

**Why Q5 can be empty.** Prometheus only creates the "5xx" series the first time a 5xx happens. Empty means
"no server errors since the service started". That's good news, not a broken query.

> **Explain it to…**
> - **A non-programmer:** a counter is an odometer, `rate` is the speedometer, p95 is "how long the
>   slowest 5% of customers waited".
> - **A programmer:** `rate()` is the per-second derivative of a monotonic counter over a window, and it
>   handles counter resets on restart.
> - **An ML person:** p95 is an empirical quantile estimated from bucket counts, interpolated linearly
>   inside a bucket. Coarse buckets mean coarse estimates.
> - **An ops person:** 5 s scrapes, RED metrics (Rate, Errors, Duration) per service, plus a USE-style
>   in-flight gauge.

**Check:** "If chat p95 is 7 s, what share of chats took longer than 7 s?" (About 5%.)

---

### e. Grafana dashboards

**Goal:** read a dashboard the way you read a car dashboard.

**Say:** Grafana draws Prometheus numbers (and Loki logs) as panels. This dashboard, **"KnowledgeAI -
operations"**, has **11 panels** (`monitoring/grafana/dashboards/knowledgeai.json`):

| Panel | What it shows | What it looked like on 2026-09-24 |
|---|---|---|
| Request rate | requests/s per service (Q3) | gateway peaked at **5.51** during the search load; retrieval shows a **gap** while it was stopped |
| Error rate | share of 5xx per service, and share of chats that ended in error | gateway **0.556** at 10:37 during the big demo, **0** otherwise |
| p95 latency | p95 of chat, search, retrieve, generate | gateway search p95 about **0.05-0.09 s** normally, **18.5-19.1 s** while retrieval was down |
| In-flight requests | requests being served right now | gateway up to **8** during the first outage |
| Memory per service | process memory, container memory, container limit | retrieval limit **537 MB** (512 MiB); container usage **71-94 MB** |
| Embedding fallback counter | the silent-failure counter | **0** all day (as it should be) |
| Downstream call failures | failed service-to-service calls, by reason | `ConnectError` gateway→retrieval **0.24-0.51/s** during each outage |
| Ollama call p95 and failures | how slow the AI model is | embed about **0.05 s**; generate about **1.8-7.4 s** |
| Retrieval: chunks per query and zero-chunk rate | is retrieval finding anything? | **4** chunks per query all day (top-k = 4); zero-chunk rate had no data (never happened) |
| Chat outcomes | answered / refused / error per second | `refused_scope` appears during the outage |
| Error log lines | the latest ERROR lines from Loki | (log panel) |

Minute-by-minute values for every panel: [`backup/04b_grafana_panels.txt`](lecture/backup/04b_grafana_panels.txt).

**Show (live, 3 min).** Tab 2. Set the time range to "Last 1 hour". Point at the bump from the load
generator in *Request rate* and *p95 latency*. Hover over a line to read exact values.

**How to read any panel:**
1. Read the title.
2. Check the y-axis unit.
3. Look for the **baseline**: what "normal" looks like.
4. Look for a **change** and **when** it started.
5. Check whether other panels changed **at the same time**. Things that change together usually share a
   cause.

> **Explain it to…**
> - **A non-programmer:** a car dashboard for the app. The speedometer is the request rate, a warning
>   light is the error rate.
> - **A programmer:** each panel is a saved PromQL query with a chart type; the dashboard is JSON in git.
> - **An ML person:** a set of time series. Anomaly = departure from the baseline window, which is exactly
>   the comparison the doctor makes.
> - **An ops person:** provisioned read-only from git, anonymous viewer access, Prometheus and Loki as
>   data sources.

**Check:** "Which panel would show a memory leak?" (*Memory per service*: a line that climbs and never
comes down.)

---

### BREAK (0:46-0:56)

Leave everything running, including background traffic. During the break, check once in Window A:
```powershell
Invoke-RestMethod http://localhost:18100/health
```
You want `busy` empty and `queued` 0.

---

### f. Alerts: the smoke alarms

**Goal:** understand how a rule works, why `for:` exists, and why alarms describe **symptoms only**. Then
the path an alarm takes.

**Say:**
- An **alert rule** is a PromQL question Prometheus asks every 5 s. "Is this true?" If it stays true for
  the `for:` time, the alarm **fires**.
- **pending** = true, but not for long enough yet. **firing** = true for at least `for:`. A smoke alarm
  that went off for one puff of toast smoke would be ignored; `for:` is the "keep smelling smoke for 45 s
  first" rule.
- **Symptoms only.** Every alarm text says *what is observed*, never *why* (the header of
  `monitoring/prometheus/alert.rules.yml`). Picking the cause is the doctor's job. If the alarm text gave
  the cause away, the doctor's measured accuracy would be meaningless (DECISIONS.md D-29).
- There are **16 rules in 5 groups**: availability, errors, latency and load, resources, retrieval
  quality. *(run 2026-09-24: promtool reported "16 rules found", and Prometheus listed all 16, all
  `inactive`.)*

**Show:** tab 5 (Prometheus → Alerts). Then walk through three real rules.

**Rule 1: `ServiceDown`** (the one that fires first in the big demo)
```yaml
- alert: ServiceDown
  expr: up{job=~"gateway|ingestion|retrieval|llm"} == 0   # Prometheus cannot reach the service
  for: 45s                                                # ...for 45 seconds in a row
  labels: { severity: critical, service: "{{ $labels.job }}" }
  annotations:
    summary: "{{ $labels.job }} is not answering Prometheus scrapes"   # symptom, not cause
```
- `up` is 1 when the scrape works and 0 when it doesn't.
- Why 45 s? A deploy recreates a container in about 15 s, and that must not look like an outage
  (DECISIONS.md D-59).
- The summary says "not answering scrapes". It does **not** say "crashed" or "stopped". It might be a
  network problem.

**Rule 2: `DownstreamCallFailures`** (the "outage" form)
```yaml
- alert: DownstreamCallFailures
  expr: sum by (service, target) (rate(knowledgeai_downstream_failures_total[30s])) > 0
  for: 1m
  labels: { severity: warning, pattern: outage }
```
- It counts failed calls **from one service to another**. Why does it exist? When retrieval is dead, the
  gateway still returns HTTP 200 with a polite "I have nothing relevant". An HTTP error-rate alarm alone
  would never notice (DECISIONS.md D-13).
- The failures must continue in every 30 s window for a full minute.

**Rule 3: `HighErrorRate`** (persistence, not a blip)
```yaml
- alert: HighErrorRate
  expr: |
    ( sum by (service) (rate(knowledgeai_http_requests_total{status=~"5..", endpoint!="/metrics"}[5m]))
      / sum by (service) (rate(knowledgeai_http_requests_total{endpoint!="/metrics"}[5m])) ) > 0.03
    and on (service)
    count_over_time((sum by (service) (increase(knowledgeai_http_requests_total{status=~"5..", endpoint!="/metrics"}[1m])) > 0)[5m:1m]) >= 4
  for: 1m
```
In plain words: "more than 3% of requests failed over 5 minutes, **and** there were failures in at least
4 of those 5 minutes". A deploy produces errors in one or two minutes, while a real bug produces them in
nearly every minute. The first version of this rule was too strict and never fired for a 5% typo bug
(DECISIONS.md D-77).

**The alarm path** (see [diagrams](#4-diagrams)):
```text
Prometheus (checks 16 rules every 5 s)
   │ firing
   ▼
Alertmanager :19093  (groups alerts; waits 5 s; no "inhibit" rules: every symptom gets through)
   │ webhook
   ▼
alert-sink :19095    (appends the alert as one JSON line to the trigger log, then...)
   │ POST /incident   (immediately, in a background thread, with retries)
   ▼
doctor :18100        (opens an incident)
```
*(run 2026-09-24, big demo run 2)* The alarm started at 10:36:46.9, Prometheus showed it firing by
10:36:52, alert-sink received it at **10:36:56.8**, and the doctor had opened the incident by **10:36:58**.
That is about 10 s from firing to the doctor. The alert JSON is in
[`backup/05_big_demo_f3_live/alert_sink_alerts.txt`](lecture/backup/05_big_demo_f3_live/alert_sink_alerts.txt).

> **Explain it to…**
> - **A non-programmer:** smoke alarms. They say "smoke in the kitchen", not "you left the toaster on".
> - **A programmer:** a boolean PromQL expression with a debounce (`for:`) and labels for routing.
> - **An ML person:** a hand-set threshold classifier on time series, tuned for precision (no false pages
>   from deploys) against recall (it must catch 5% error bugs).
> - **An ops person:** 5 s evaluation, no inhibition, symptom-based annotations, promtool unit tests
>   (`alert.rules.test.yml`) prove a 20 s deploy burst stays quiet.

**Check:** "Why doesn't the alarm say *why*?" (Because then it would be guessing, and the doctor's score
would be meaningless.)

---

### g. The pipeline, DVC and MLflow

**Goal:** understand how a change gets from a laptop to the running app, and how data and experiment
results are versioned.

**Say:**
- **The pipeline** (CI/CD) is a factory line with a quality check:
  1. `git push pipeline main` sends the commit to a **bare repository** on this laptop
     (`runtime/pipeline.git`). Its **post-receive hook** runs the pipeline.
  2. **Job 1, `scripts/pipeline/verify.sh`**: lint (ruff, yamllint), all three test suites, promtool
     (alert rules and their tests), amtool, and the compose config check. **If anything fails, it stops
     here.**
  3. **Job 2, `scripts/pipeline/deploy.sh <sha>` → `deploy/deploy.py`**:
     - builds every image tagged with the commit's **short SHA** (like the batch number on a medicine
       box);
     - starts them and runs a **smoke test** (is every service online, and does a search return chunks?);
     - on failure, **rolls back** to the images of the last good SHA;
     - appends a **deploy record** to `runtime/deploys.jsonl`.
  4. **The pipeline ends there. It never wakes the doctor** (DECISIONS.md D-42). A test fails if anything
     in the pipeline mentions the doctor.
- **Why a local bare repo instead of GitHub?** The build rules said no code may leave the machine, but a
  real `git push` was still required (DECISIONS.md D-47). GitHub Actions calls **the same two scripts**
  (`.github/workflows/ci.yml`, D-48). That path **has not been run** (RESULTS.md).
- **DVC** versions the **knowledge base**, which is data too big for git. `dvc.yaml` has one stage,
  `build_kb`. Its output goes to MinIO; `kb/manifest.json` (small, in git) records the version. The
  kb-loader writes every load to `runtime/kb_loads.jsonl`, so the doctor can blame a *data* version, not
  just a commit (D-46).
- **MLflow** is a lab notebook for experiments. Every evaluation run is logged with its settings and
  scores.

**Show at 1:04: the saved pipeline log, not a live push** ([why](#2-the-120-minute-plan)). Open
[`backup/01_pipeline_push.txt`](lecture/backup/01_pipeline_push.txt). *(run 2026-09-24, 10:05:53 UTC)*
The push took **65 s** in total:

| Step | Result | Time |
|---|---|---|
| ruff | All checks passed | 1 s |
| yamllint | ok | 2 s |
| patient tests | **173 passed** | 13 s |
| alert-sink tests | 1 passed | 1 s |
| doctor tests | **60 passed** | 6 s |
| promtool | config valid, **16 rules**, rule tests SUCCESS | 11 s |
| amtool | config valid, 0 inhibit rules, 1 receiver | 1 s |
| compose config, hook check | ok | 0 s |
| deploy (build, up, smoke test, record) | `outcome: success`, smoke test **3.2 s** | **29.5 s** |

The deploy record says `"pipeline": "local"`, `"services_changed": ["doctor"]`, 11 commits, 100 files.

**DVC (live, 10 s).** Window A:
```powershell
.venv\Scripts\python.exe -m dvc dag
.venv\Scripts\python.exe -m dvc status
```
*(run 2026-09-24, 2.7 s)*
- `dvc dag` shows a single box: `build_kb`.
- `dvc status` reports two dependency files as changed: `chunker.py` and `vector_store.py`. They were
  touched only by comment commits ("Clarify chunk size units", "Document the similarity convention in the
  vector store"). The knowledge base was not rebuilt after those, and it still reports
  `kb_version 38ba55c908d1`, 10 documents, 21 chunks.

Say this honestly: DVC noticed that a file the data depends on changed, even though only a comment
changed. See [`backup/06_dvc.txt`](lecture/backup/06_dvc.txt).

**MLflow (live, 1 min).** Tab 8. Experiment **incident-doctor-evaluation**. Two parent runs matter:
- `eval-20260924-084116`: local models, 5 configurations.
- `eval-20260924-141418`: GLM, 6 configurations. **It appears twice**, because it was logged twice; both
  copies hold the same values.

Open a child run such as `ablation|logs_commits_incidents|glm:glm-4.5-flash` to see
`environment.acc_at_1 = 0.56`. That is exactly the RESULTS.md number. See
[`backup/08_mlflow_runs.txt`](lecture/backup/08_mlflow_runs.txt).

> **Explain it to…**
> - **A non-programmer:** a factory line. Quality check first; if it fails, nothing ships. Every box gets
>   a batch number, so you can always go back to the last good batch.
> - **A programmer:** pre-deploy gate (lint + 234 tests + rule tests), immutable SHA-tagged images, smoke
>   test, automatic rollback, append-only deploy log.
> - **An ML person:** DVC = git for datasets (content hashes, remote storage); MLflow = experiment
>   tracking with nested runs per configuration and per repeat.
> - **An ops person:** the local hook and GitHub Actions share one implementation (`verify.sh`,
>   `deploy.sh`), so the only difference is the environment.

**Check:** "What stops a broken commit from being deployed?" (`verify.sh`: the linters and the tests. But
the project's faults were designed to *pass* those checks, D-52, like real bugs.)

---

### h. The doctor, step by step

Teach this **while the big demo (i) is running**: start the fault at 1:10, then talk through these steps
while you wait for the alarm and the report.

**Its three doors, and only three** (`doctor/app/main.py`):

| Door | Who opens it | How |
|---|---|---|
| **Alarm** | automatic | alert-sink → `POST /incident` |
| **Ticket** | a person | `POST /ticket` with plain words, or the "Report a problem" form on the Incidents page |
| **Replay** | the evaluation | `python -m app.replay <bundle.json>` |

**The hard rule: a push never wakes it** (DECISIONS.md D-42). If a deploy woke the doctor, it would
already know "it was the deploy", and the whole evaluation would be worthless. It only ever starts from a
**symptom**.

**The steps, in order:**
```text
 1 OPEN       alarm arrives -> incident opened (alarms on the same service within 10 min join it)
 2 WAIT       until the incident window closes: alarm start + 60 s, plus 15 s
 3 COLLECT    snapshot everything into bundle.json (collectors.py, evidence.py):
                - the alarm and the other alarms around it
                - error log lines from Loki, grouped by signature, marked NEW if absent in the baseline
                - 17 metrics: incident window (10 min before -> 1 min after the alarm)
                               vs baseline window (the 30 min before that)
                - deploy records in the last 6 hours, and every commit they shipped, with diffs
                - knowledge-base loads, and the source code around any line a stack trace names
 4 SEARCH     rank suspect commits (retrieval.py, indexes.py):
                time filter -> word overlap (60%) + meaning similarity (40%, nomic-embed-text)
              find related code (chunked by function/class) and similar past incidents
 5 ASK        build one prompt with a fixed token budget (prompt.py) and send it to GLM
              (fallback: local llama3.2). The answer must follow a fixed JSON layout (schema.py).
              If it breaks the layout, one repair round. At most 6 model calls per diagnosis.
 6 CHECK      rules the layout cannot express: a commit named must be in the candidate list;
              "capacity" may never blame a commit (reasoner.py)
 7 TEST FIX   code fix? -> turn the edits into a diff, apply it to a throwaway copy of the code at
              the running commit (git archive), run the patient's test suite (fixes.py, verify.py).
              "verified" only if every test passes. Restart/scale actions: "unverified - needs human review"
 8 REPORT     report.json + report.md -> the Incidents page. NOTHING is applied to the running system.
```

**The fixed answer layout** (`doctor/app/schema.py`):
- `summary`
- `incident_class`: one of `code_defect`, `configuration`, `capacity`, `dependency_failure`, `data_issue`
- `demand_vs_capacity`: did traffic rise or fall? Was there a deploy before the onset? A verdict.
- `hypotheses`: 1-3 ranked causes, each with `component`, `confidence`, `evidence` and
  `suspected_commit` (or null)
- `fix`: `code_diff` / `config_change` (with exact find→replace edits) or `action` (restart, scale…)

**Show a real report with a tested code fix** (if time allows): open
[`backup/10_report_with_verified_fix_f1_glm.md`](lecture/backup/10_report_with_verified_fix_f1_glm.md).
This is GLM-4.5-Flash replaying the timeout-regression fault (f1 r2). It:
- named the exact guilty commit `71b19e9` at confidence 0.90;
- proposed restoring `EMBED_TIMEOUT_S = 45.0`;
- ran the fix on a throwaway copy: *"Test suite on the patched copy: 170 passed"* and *"Acceptance test:
  1 passed"*.

> **Explain it to…**
> - **A non-programmer:** a doctor who takes your history, runs tests, forms a diagnosis, and tries the
>   medicine on a lab sample, never on you.
> - **A programmer:** RAG over your own incident: evidence retrieval, schema-constrained LLM output, and
>   patch verification in a sandbox.
> - **An ML person:** hybrid retrieval (lexical + dense), structured generation with validation and one
>   repair round, evaluated with an ablation over evidence sources.
> - **An ops person:** read-only automation. It has only read access to the repo and the deploy log, and
>   it never executes a change on the live system.

**Check:** "Name the three things that can wake the doctor." (An alarm, a ticket, a replay. Never a push.)

---

### i. The big live demo: break it, watch it get diagnosed

**The fault: `f3_retrieval_down`**, the retrieval container is stopped. It is the fastest-alarming fault:
- RESULTS.md: break → alert took **33.0 s** (r1) and **47.9 s** (r2).
- Today *(run 2026-09-24)*: **48.9 s** and **46.9 s**.

The project's own script breaks it **and puts it back automatically**. You never edit anything by hand.

**The command** (Window B, Git Bash). Give each run a new `--label`:
```bash
.venv/Scripts/python.exe -m faults.run_fault f3_retrieval_down --label class
```
What it does (`faults/run_fault.py`):
1. `docker compose stop retrieval`
2. **waits** for an alarm that began after the break (it never calls the doctor itself)
3. waits for the doctor's finished report and copies it to `runtime/fault-runs/f3_retrieval_down-class/`
4. **reverts**: `docker compose start retrieval`
5. waits for the alarm to resolve, then exits

**What you and the audience will see: the real timeline of run 2 on 2026-09-24** (break at 10:36:00 UTC):

| After the break | What happens | Where to look |
|---|---|---|
| 0 s | runner prints `f3_retrieval_down: break applied` | Window B |
| +6 s | `up{job="retrieval"}` drops **1 → 0** | Prometheus, Q1 |
| +8 s | `ServiceDown` **pending** | tab 5 (Alerts) |
| +19 s | `DownstreamCallFailures` pending; gateway→retrieval failures climb to **0.2-0.5/s** | Grafana *Downstream call failures* |
| +31 s | `HighLatencyP95` pending (search p95 heads for **18 s**) | Grafana *p95 latency* |
| +35-60 s | gateway 5xx share (1 min) rises to about **0.56**; "refused as out of scope" appears | Grafana *Error rate*, *Chat outcomes* |
| **+46.9 s** | `ServiceDown` **fires** (its `startsAt`); Prometheus page shows firing at +52 s | tab 5 |
| **+56.8 s** | alert-sink receives it | tab 7 (refresh) |
| **+58 s** | the doctor opens incident `inc_a7d4de5377` (status `open`) | tab 1 → Incidents |
| +2:01 | status `collecting` (evidence snapshot) | Incidents |
| +2:03 | status `diagnosing` (asking GLM) | Incidents |
| **+2:55** | status **`ok`**, class **`dependency_failure`**, 128.0 s after the alarm | Incidents |
| +2:57-2:59 | runner reverts: `docker compose start retrieval`; `up` back to 1 at +3:02 | Window B, Q1 |
| +3:27 | `ServiceDown` **resolved** | tab 5, tab 7 |
| **+3:29** | runner prints `=== f3_retrieval_down-lecture2 done` (total **209 s**) | Window B |

Timeline and runner output: [`backup/05_big_demo_f3_live/`](lecture/backup/05_big_demo_f3_live/).

**The report it wrote** (glm-4.5-flash, live, abridged from
[`live_report.md`](lecture/backup/05_big_demo_f3_live/live_report.md)):
- **What broke:** "The retrieval service is not answering Prometheus scrapes, causing downstream failures
  and high latency in the gateway."
- **Incident class:** `dependency_failure`, **correct** (the ground truth is `dependency_failure`,
  component `retrieval`, no guilty commit).
- **Ranked causes:**
  - #1 (0.90) retrieval, no commit: "The retrieval service is not responding to requests, causing the
    gateway to fail with ConnectError."
  - #2 (0.70) a telemetry configuration theory.
  - #3 (0.50) "the deployment at 73e80cf may have introduced a configuration issue".
- **Evidence it cited:** the `ServiceDown` alarm, the log signature `ConnectError:5b2993ef741b` (x21,
  "No address associated with hostname"), and `service_up` went to 0.
- **Fix:** kind `action`: "Restart the retrieval service". **Verification: "unverified - needs human
  review"**, because a restart cannot be tested on a copy. "Nothing was applied to the running system."
- **Rule violations:** "named a commit that is not a candidate: 73e80cf". The doctor caught the model
  breaking a rule and recorded it. Point this out; it shows the checks work.
- **Cost:** 2 model calls, 6970 + 1093 tokens, reasoning 51.2 s. The report prints $0.006587, but that
  uses the glm-4.6 list price. GLM-4.5-Flash is free (RESULTS.md).

**Narration while you wait** (about 3 minutes, one line every 20-30 s):
1. (0:00) "I've just stopped one of the four services. Watch the *Downstream call failures* panel."
2. (0:10) "Prometheus already sees `up = 0`. But the alarm is only *pending*. It must stay true for 45 s,
   so a normal deploy doesn't page anyone."
3. (0:30) "Users are getting 'I have nothing relevant', not errors. That's why we have a separate alarm for
   failed internal calls."
4. (0:50) "Firing. Alertmanager passes it to alert-sink, which logs it and knocks on the doctor's door."
5. (1:00) "The doctor has opened an incident. Now it waits about a minute for the incident window to close,
   so it sees the whole picture, not just the first seconds."
6. (2:00) "Collecting: it's taking a snapshot of logs, 17 metrics, deploys and commits into one file.
   That same file is what we replay later for testing."
7. (2:05) "Diagnosing: the prompt goes to GLM. It must answer in a fixed layout, or it gets one chance to
   repair it."
8. (3:00) "Report. Let's read it together." Then: "…and notice the script has already put retrieval back.
   Nothing was fixed by the AI; the report is advice for a human."

**After the revert (+3:29 to about +6 min):** more alarms arrive and are diagnosed one at a time. The
rolling windows still contain the outage, and a later alarm becomes a new incident (DECISIONS.md D-64).
On 2026-09-24 these were `HighLatencyP95` (159.0 s after its start), `ChatAnswersRefused` (129.3 s), and
in run 1 also `HighErrorRate` (141.7 s). **All of these were diagnosed `dependency_failure` by
glm-4.5-flash.** One exception, to be honest about: after run 1, a `HighLatencyP95` alarm diagnosed through
the doctor's catch-up poll came back as `capacity`, blaming a traffic surge. All alarms were clear **6 min
36 s** after the break (10:42:36). Use this: "one fault, several symptoms, and
every report points at the same cause".

**Check that the app is healthy again** (Window A):
```powershell
Invoke-RestMethod http://localhost:18000/api/system/status
Invoke-RestMethod http://localhost:18100/health
```
You want every service `online`, and the doctor `busy` empty with `queued` 0 before the ticket demo.

**Plan B** (if something goes wrong):

| Problem | Do this |
|---|---|
| No alarm after 90 s | Check tab 5. If `ServiceDown` is pending but not firing, wait. If `up` is still 1, the break didn't happen: check Window B for an error. Show [`05_big_demo_f3_live/watch_timeline.txt`](lecture/backup/05_big_demo_f3_live/watch_timeline.txt). |
| Report status `failed` | Almost always the online model: no internet, or the wrong model name. Show [`05_big_demo_f3_live/live_report.md`](lecture/backup/05_big_demo_f3_live/live_report.md), then run the **offline replay** (below). Tell the truth: this happened in run 1 on 2026-09-24 ([`05a_…`](lecture/backup/05a_live_f3_run1_doctor_failed/)). |
| Runner seems stuck after the report | It waits for the alarm to resolve (up to 15 min). The app is already back. Carry on teaching. |
| Anything else | Show the recorded incident [`incidents/recorded/f3_retrieval_down-r2/`](../incidents/recorded/f3_retrieval_down-r2/) (its `timeline.json` and `live_report.md`). |

**Replay: the third door, and your internet-free plan B** (Window A):
```powershell
cd doctor
..\.venv\Scripts\python.exe -m app.replay ..\incidents\recorded\f3_retrieval_down-r2\bundle.json --provider glm --model glm-4.5-flash
cd ..
```
- *(run 2026-09-24, 41.3 s)* GLM answered `dependency_failure`, retrieval, no commit. **Correct.**
  [`backup/07_replay_f3_r2_glm/report.md`](lecture/backup/07_replay_f3_r2_glm/report.md). It needs the
  internet.
- **No internet?** Use `--provider ollama --model llama3.2`. *(run 2026-09-24, 4.6 s, offline)* It
  answered **`capacity`, which is wrong.** That matches RESULTS.md: the live llama3.2 doctor answered
  "capacity" in 12 of 16 runs. Use it as a teaching moment about model size.
  [`backup/07b_replay_f3_r2_llama32_offline.md`](lecture/backup/07b_replay_f3_r2_llama32_offline.md).

**Too slow for class** (show the recorded result instead):

| Fault | Why not live | Recorded folder |
|---|---|---|
| f4 memory leak | alarm after **821-877 s** (RESULTS.md) + a real git push | `incidents/recorded/f4_memory_leak-r1/`, `-r2/` |
| f5 typo | alarm after **323-620 s**; needs a push | `incidents/recorded/f5_typo-r1/`, `-r2/` |
| f6 tight timeout | alarm after **321-323 s**; needs a push + 10 min of busy traffic | `incidents/recorded/f6_tight_timeout-r1/`, `-r2/` |
| f1 embed timeout | alarm after 104-143 s, but it also loads **llama3 + mistral** as a "noisy neighbour" (about 9 GB of models; DECISIONS.md D-54). Too heavy for this laptop's memory during a lecture | `incidents/recorded/f1_embed_timeout-r1/`, `-r2/` |
| f2 capacity | alarm after 108-114 s, but alarm → report took **246-377 s**, and during the 4 chats/s surge chat p95 reaches **75-88 s** (DECISIONS.md D-74), so the app is useless for other demos | `incidents/recorded/f2_capacity-r1/`, `-r2/` |
| f7 missing documents | **monitoring missed it**: no alarm within the 900 s timeout, then a ticket was filed | `incidents/recorded/f7_kb_missing_docs-r1/`, `-r2/` |
| f3b bad address | alarm after 77-79 s: possible live, but **not run on 2026-09-24** | `incidents/recorded/f3b_retrieval_bad_address-r1/`, `-r2/` |

> **Explain it to…**
> - **A non-programmer:** I switched off one organ; the monitors beeped; the doctor examined the patient
>   and wrote "the retrieval organ isn't responding; restart it". And a nurse (the script) switched it
>   back on.
> - **A programmer:** a chaos experiment with automatic rollback, plus automated root-cause analysis on the
>   alert.
> - **An ML person:** one live sample. The class was right, top-1 cause right, no false commit blamed.
>   Section l has the real statistics.
> - **An ops person:** detection about 47 s (the `for: 45s` debounce dominates), alarm → report 128 s,
>   automated revert in about 3.5 min.

**Check:** "Did the doctor blame a commit? Should it have?" (No, and correctly not: nothing in the code
changed.)

---

### j. The ticket demo: a person reports a problem

**Goal:** show the doctor finding **when** a problem started, from plain words and the metrics.

**Say:** "Not every problem sets off an alarm. The missing-documents fault never did. So a person can
report a symptom in their own words, and the doctor works out the time window itself."

**Show (live, about 1 min).** Make sure the doctor is idle (`busy` empty, `queued` 0). Tab 1 →
**Incidents** → **"Report a problem"**:
- **Describe the symptom:** `The assistant says it has nothing relevant in the documents, for every question.`
- **Since when?:** `about 5 minutes ago`. Use the real time since your break; on 2026-09-24 the test used
  `about 10 minutes ago`.
- Click **Submit to Incident Doctor**.

The form posts to `/doctor-api/ticket`. The same call from Window A (this exact call was run):
```powershell
$body = @{ text = "The assistant says it has nothing relevant in the documents, for every question."; since = "about 10 minutes ago" } | ConvertTo-Json
Invoke-RestMethod http://localhost:13001/doctor-api/ticket -Method Post -ContentType 'application/json' -Body $body | ConvertTo-Json -Depth 6
```
*(run 2026-09-24; ticket filed 10:43:39, the real break was at 10:36:00)*
- It turned "10 minutes ago" into a search range, **10:28:39 → 10:43:39** (1.5× the stated span).
- It scanned symptom metrics for the first departure from normal:
  - `chat_errors_per_min` at **10:35:39** (21 s *before* the real break; this metric also counts ordinary
    refused questions, so a normal refusal can set it off early. Be honest about it.)
  - `http_5xx_per_min` and `downstream_failures_per_min` at **10:36:09** (9 s after the break)
  - `chat_p95_s` at 10:36:39
- It chose 10:35:39 as the onset.
- **Report ready at 10:44:18, 39 s after the ticket.** Class `dependency_failure`; #1 cause: "The
  retrieval service is not answering Prometheus scrapes and calls from the gateway are failing". **No
  commit blamed.**

Files: [`backup/09_ticket_window.txt`](lecture/backup/09_ticket_window.txt),
[`backup/09_ticket_report.md`](lecture/backup/09_ticket_report.md).

> **Explain it to…**
> - **A non-programmer:** "Since this morning it's been weird." The doctor looks at the charts to find the
>   exact moment things changed.
> - **A programmer:** a regex turns rough time into a range, then change-point detection (the first value
>   above twice the starting level, and at least 0.5 above it) builds a synthetic alert (`doctor/app/ticket.py`).
> - **An ML person:** a simple onset detector: robust baseline (median of the first 10%), a multiplicative
>   plus additive threshold, earliest crossing wins.
> - **An ops person:** a human trigger that reuses the whole alert pipeline; tickets never break the "a
>   push never wakes it" rule.

**Check:** "How did it find *when* the problem started?" (From the metrics, not from the person's rough
time.)

---

### k. The 8 faults

**Start the live pipeline push now** (Window B), and talk over it for the 65 s it takes:
```bash
git push pipeline main
```
It deploys the commit that added this guide. Only the doctor demos are finished at this point, so this is
safe (see [the plan](#2-the-120-minute-plan)). It should end with `pipeline: SUCCESS for <sha>`. On
2026-09-24 the same command took **65 s**. If it prints `Everything up-to-date`, a push was already done
(for example in a rehearsal): show [`backup/01_pipeline_push.txt`](lecture/backup/01_pipeline_push.txt)
instead.

**The table** (delivery from DECISIONS.md D-52, timings from RESULTS.md):

| Fault | What breaks | Delivery | First alarm (live) | Break → alarm | Alarm → report |
|---|---|---|---|---|---|
| f1 embed timeout | embedding timeout 45 s → 10 s; when Ollama is busy, answers come from meaningless "fallback" vectors, silently | **push** (a real commit) | EmbeddingFallbackActive | 103.6 s, 142.6 s | 162.4 s, 139.4 s |
| f2 capacity | a chat surge (4/s) saturates the single local model | **environment** | HighLatencyP95 | 113.5 s, 108.5 s | 376.5 s, 246.5 s |
| f3 retrieval down | retrieval container stopped | **environment** | DownstreamCallFailures / ServiceDown | 33.0 s, 47.9 s | 139.0 s, 97.1 s |
| f3b bad address | gateway pointed at a retrieval host that doesn't exist | **environment** | DownstreamCallFailures | 79.0 s, 77.0 s | 96.0 s, 101.0 s |
| f4 memory leak | a cache that never forgets; memory climbs until the container is killed | **push** | MemoryClimbing | 821.2 s, 877.2 s | 104.8 s, 105.8 s |
| f5 typo | `req.qestion`: crashes only for keyword questions (no "?") | **push** | HighErrorRate | 620.0 s, 323.0 s | 96.0 s, 101.0 s |
| f6 tight timeout | gateway→retrieval timeout set to 0.05 s; about 7% of calls fail | **push** | DownstreamCallFailures | 323.0 s, 321.0 s | 102.0 s, 105.0 s |
| f7 missing docs | a knowledge-base version with 6 of 10 documents missing | **data** | **none: monitoring missed it**; a ticket was filed | - | 29.0 s, 32.0 s after the ticket |

Medians (RESULTS.md):
- **environment:** break → alarm 78 s, alarm → report 120 s
- **push:** break → alarm 323 s, alarm → report 105 s. A push's "break" includes verify + build + deploy.

**Monitoring caught 14 of 16 runs on its own.** The two misses were f7: refusals rose to about 20%, below
the 30% alarm threshold.

**Why push faults are slow to alarm:** a memory leak needs minutes of growth to stand out from noise (a
3-minute `for:`), and intermittent errors must persist in 4 of 5 minutes so that a deploy blip doesn't page
(D-71, D-72, D-77).

Push faults were real commits with ordinary messages, placed among harmless **distractor** commits, so the
guilty commit was **never** simply "the newest one" (D-53). They pass lint and all the existing tests, but
fail their own acceptance test (checked by `faults/selfcheck.py`, D-52).

> **Explain it to…**
> - **A non-programmer:** eight planned illnesses: bad code, broken surroundings, missing documents.
> - **A programmer:** each push fault passes CI, which is exactly why it's a realistic bug.
> - **An ML person:** a small labelled dataset: 16 incidents with ground truth, 3 delivery strata.
> - **An ops person:** detection latency is dominated by `for:` and persistence rules chosen to avoid
>   false pages.

**Check:** "Which fault did monitoring miss, and who noticed instead?" (f7; a user ticket.)

When the push finishes, confirm health: `Invoke-RestMethod http://localhost:18000/api/system/status`.

---

### l. How the doctor was tested

**Goal:** know how the numbers were produced, what they say, and what they don't.

**Say:**
- **Replay.** Each live incident's evidence was frozen into `bundle.json`. The evaluation
  (`doctor/eval/run_eval.py`) re-diagnoses those snapshots only. Nothing live is touched, so every setup
  sees **identical evidence**. **16 incidents** (8 push, 6 environment, 2 data).
- **Baseline**: "blame the most recent deploy". It is what a tired engineer does, and what a naive
  tool would do.
- **Evidence ablation**: run the same model with more and more evidence:
  1. logs only;
  2. + commits;
  3. + past incidents (only incidents that happened *earlier*, D-69).
- **Models**: GLM-4.5-Flash (online, free tier) vs llama3 8B vs llama3.2 3B (both local).
- **Repeats**: every configuration 3 times, with seeds 1000-1002 (D-68). The tables show the mean and the
  min-max across repeats.
- **Scoring** (`doctor/eval/scoring.py`, D-37): a cause counts as right if it names the guilty commit
  (when there is one) or, when there is none, names **no** commit **and** the right component. The
  component is a fixed list, so the check is objective.
- **Environment faults are the real score**: no commit is guilty, so the deploy history can only
  mislead.

**The headline numbers (copied from RESULTS.md, "Head to head, full evidence"):**

| | GLM-4.5-Flash (online) | llama3 8B (local) | llama3.2 3B (local) |
|---|---|---|---|
| **Environment faults: right cause (acc@1)** | **0.56** | 0.17 | 0.28 |
| Environment faults: right cause in top 3 | **0.89** | 0.17 | 0.44 |
| Environment faults: wrongly blamed a commit | **0.11** | 0.67 | 0.22 |
| Push faults: exact guilty commit (acc@1) | **0.38** | 0.33 | 0.04 |
| Push faults: fix passes the test suite | **0.75** | 0.33 | 0.08 |
| Push faults: fix passes the fault's own acceptance test | **0.71** | 0.29 | 0.08 |
| All faults: right kind of problem (class) | **0.81** | 0.69 | 0.58 |
| Seconds per diagnosis | 54.7 | 11.1 | 5.5 |
| Tokens per diagnosis | 14.2k | 11.0k | 10.6k |

- Baseline, environment faults: acc@1 **0.00**, false attribution **1.00**. It *always* blames a commit.
- Deploy-level baseline, push faults: the guilty commit was inside the most recent deploy in **0.50** of
  push runs. Rolling back would have fixed half. The doctor (GLM) named the exact commit in 0.38.

**What worked (say it plainly):**
- GLM names the right cause for environment faults over three times as often as llama3 (0.56 vs 0.17),
  and wrongly blames a commit in only 11% of runs.
- 71% of GLM's push-fault fixes passed the fault's own acceptance test, and none needed the
  reversed-edit correction (0 of 72).

**What did not work (say it plainly):**
- **Showing llama3 the commits makes it blame one.** With logs only it never blamed a commit for an
  environment fault; with commits added it did in **83%** of runs.
- **Retrieval sets the ceiling.**
  - The guilty commit reached the prompt's top 5 in only **5 of 8** push incidents, so 0.62 is the maximum
    any model could score.
  - The memory leak ranked 7th and 11th: its diff "adds a cache", which reads like an optimisation.
- **The missing-documents fault (f7) is not understood.** GLM said "ChromaDB connection failure" in every
  replay, and its class was right **0 times in 18**. That needs better evidence (the KB version and
  document count in the prompt), not a better model.
- **The live campaign doctor was weak:** llama3.2 with a 4k context got the class right in only **4 of
  16** live runs. It shared the GPU with the patient (D-63).

**What was never tested (say it plainly):**
- GitHub Actions + the Pavilion laptop (the same scripts, never run).
- Paid models (larger GLM, Gemini, Claude): no working paid key.
- The live campaign itself ran with llama3.2, not GLM. Today's live demo with GLM is **one** run, not a
  statistic.
- Small sample: 16 incidents, so one incident moves a rate by 0.12-0.5.
- Retrieval was tuned on f1 r1 (D-76), so that one incident is not held out.

**Show:** MLflow (tab 8). Compare the child runs `ablation|logs_only|…` and
`ablation|logs_commits_incidents|…` for GLM: environment acc@1 is 0.44 vs 0.56, and false attribution is
0.00 vs 0.11.

> **Explain it to…**
> - **A non-programmer:** we recorded 16 real illnesses and let each doctor diagnose the same records, 3
>   times each, then marked them against the true answer.
> - **A programmer:** offline replay = deterministic inputs; only the model and the evidence set vary.
> - **An ML person:** a stratified evaluation with an ablation, a strong heuristic baseline, 3 seeds,
>   ranges reported, and a leakage guard (the doctor never sees `faults/` or `incidents/`).
> - **An ops person:** "roll back the last deploy" fixes 50% of push faults and 0% of environment faults.
>   The doctor's value is in the second group.

**Check:** "Why is 'blame the latest deploy' a fair baseline?" (It's what people and simple tools really
do, and it is scored with the same rules.)

---

### m. Key design decisions

One or two sentences each (DECISIONS.md numbers in brackets):

1. **Two systems, no shared code** (D-1). The doctor imports nothing from the patient, so breaking the
   patient can never break the doctor.
2. **A push never wakes the doctor** (D-42). If it did, it would know "the deploy did it" before looking,
   and the evaluation would be worthless. Only symptoms wake it.
3. **Alarms describe symptoms only; no inhibit rules** (D-29). Choosing the root cause is the doctor's job;
   an alarm that hinted at the cause would leak the answer.
4. **Every incident is snapshotted before reasoning** (D-45). The replay reads the snapshot, so the
   evaluation is repeatable without breaking the app again.
5. **Fixes are search/replace edits, verified on a throwaway copy** (D-35, D-36). Small models can't write
   valid diffs, so the doctor renders the diff itself and runs the test suite on a `git archive` copy.
   Nothing touches the live system.
6. **Reasoning in the cloud, embeddings local** (D-40). The doctor keeps working when the patient's own
   Ollama is what broke. If the embeddings are down, it falls back to word-only ranking and says so.
7. **SHA-tagged images and deploy records** (D-31). Every image names its exact code; a dirty working tree
   can't be deployed. The deploy log is the doctor's history of "what changed when".
8. **Alarms are hardened against deploys** (D-59, D-72). `ServiceDown` needs 45 s and error alarms need
   persistence in 4 of 5 minutes, because a deploy recreates containers and must not look like an incident.
9. **Push faults must pass CI** (D-52, D-75). A fault the linter would catch could never have shipped, so
   it would test nothing.
10. **Experimenter paths are invisible to the doctor** (D-41). `faults/`, `incidents/` and the evaluation
    hold the answers, so the doctor drops them from commit lists.

**Check:** "Why can't a git push wake the doctor?" (It would bias the diagnosis towards "the deploy did
it".)

---

### Wrap-up (1:43-1:45)

Three things to remember:
1. **Symptoms are not causes.** Monitoring tells you *that* something is wrong; finding *why* is the hard
   part.
2. **Evidence beats guessing.** "Blame the latest deploy" was wrong for every environment fault; the
   doctor with good evidence was right about half the time and blamed an innocent commit only 11% of the
   time.
3. **The AI advises; people decide.** It tests its fixes on a copy and never touches the running system.

---

## 4. Diagrams

### The whole flow, box by box (from README.md)

```text
                          YOU CHANGE THE CODE
                                   |
                                   v
+--------------------------------------------------------------------+
| 1. PUSH the change                                                 |
|   git push pipeline main   (on this laptop)                        |
|   git push origin main     (GitHub, once it is set up)             |
|   files: scripts/pipeline/post-receive, .github/workflows/ci.yml   |
+--------------------------------------------------------------------+
                                   |
                                   v
+--------------------------------------------------------------------+
| 2. CHECK it  (stops here if anything fails)                        |
|   lint, all tests, alert-rule tests, config checks                 |
|   file:  scripts/pipeline/verify.sh                                |
+--------------------------------------------------------------------+
                                   |  all checks pass
                                   v
+--------------------------------------------------------------------+
| 3. INSTALL it                                                      |
|   build images labelled with the version, start them, smoke test   |
|   files: scripts/pipeline/deploy.sh -> deploy/deploy.py            |
|   record: runtime/deploys.jsonl                                    |
|   ** the pipeline ENDS here. It never wakes the doctor. **         |
+--------------------------------------------------------------------+
                                   |
                                   v
+--------------------------------------------------------------------+
| 4. THE APP RUNS  (KnowledgeAI)            folder: patient/         |
|   website (frontend)          :3001                                |
|     -> gateway                :8000                                |
|          -> retrieval :8002   -> ChromaDB (documents) :8010        |
|          -> llm       :8003   -> Ollama (AI model)    :11434       |
|          -> ingestion :8001                                        |
|   documents: kb/  (versioned with DVC, stored in MinIO :9000)      |
+--------------------------------------------------------------------+
                                   |  numbers (metrics) and diary lines (logs)
                                   v
+--------------------------------------------------------------------+
| 5. WATCHING                               folder: monitoring/      |
|   Prometheus :9090   collects numbers, checks 16 alarm rules       |
|   Loki :3100 + Alloy collects the diary lines (logs)               |
|   Grafana :3000      dashboards to look at                         |
+--------------------------------------------------------------------+
                                   |  SOMETHING BREAKS and a rule fires
                                   v
+--------------------------------------------------------------------+
| 6. ALARM                                                           |
|   Alertmanager :9093  ->  alert-sink :9095                         |
|   alert-sink saves the alarm, then sends it to the doctor          |
+--------------------------------------------------------------------+
                                   |
  (b) PERSON REPORTS           (a) ALARM              (c) REPLAY
  POST /ticket, or the      POST /incident            python -m app.replay
  Incidents page form                                 (from doctor/)
           +-----------------------+---------------------------+
                                   |  these three are the ONLY ways to wake it
                                   v
+--------------------------------------------------------------------+
| 7. DOCTOR WAKES UP  :8100   8. COLLECT THE CLUES   9. SEARCH       |
| 10. WORK OUT THE CAUSE (GLM, or local Ollama as backup)            |
| 11. TEST THE REPAIR ON A SPARE COPY   12. REPORT -> Incidents page  |
+--------------------------------------------------------------------+
                                   |  a person reads it and decides
                                   v
                       YOU FIX THE REAL APP
```
The ports in this chart are the defaults. **On this laptop, add 10000** (gateway 18000, Grafana 13000,
Prometheus 19090, frontend 13001, doctor 18100…). The full, unabridged chart is in README.md.

### One question's journey (request flow)

```text
browser ─▶ frontend (nginx) :13001 ─▶ gateway :18000 ──▶ retrieval :18002 ──▶ Ollama /api/embeddings
                                        │    X-Request-ID     └──▶ ChromaDB :18010 (4 nearest chunks)
                                        │    is passed on
                                        └──▶ llm :18003 ──▶ Ollama /api/generate (llama3.2)
every service: JSON log lines ─▶ Alloy ─▶ Loki :13100          every 5 s: Prometheus scrapes /metrics
```

### The alarm path

```text
 [patient /metrics] ──scrape every 5 s──▶ [Prometheus :19090]  16 rules, evaluated every 5 s
                                               │ firing (after `for:`)
                                               ▼
                                         [Alertmanager :19093]  group_wait 5 s, no inhibit rules
                                               │ webhook
                                               ▼
                                         [alert-sink :19095]   1. append JSON line to trigger log
                                               │               2. POST /incident (background, retries)
                                               ▼
                                         [doctor :18100]        open incident -> wait -> diagnose
                                               ▲
                                  catch-up poll every 60 s (fills gaps if the doctor was down)
```

### The doctor's steps

```text
 alarm / ticket / replay
        │
        ▼
  OPEN ─▶ WAIT (window closes) ─▶ COLLECT bundle.json ─▶ SEARCH commits, code, past incidents
                                                              │
                                                              ▼
  REPORT ◀─ TEST FIX on a throwaway copy ◀─ CHECK the rules ◀─ ASK the model (fixed JSON layout,
  (Incidents page;       (git archive + patient tests)                         1 repair round,
   nothing applied)                                                            ≤ 6 calls)
```

### The evaluation

```text
 16 recorded incidents (bundle.json + ground_truth.json)
        │ replay only - nothing live
        ▼
 baseline ("blame latest deploy")      ablation (same model):                models (full evidence):
                                         logs_only                              glm-4.5-flash
                                         logs + commits                         llama3 (8B)
                                         logs + commits + past incidents        llama3.2 (3B)
        │ × 3 repeats (seeds 1000-1002)
        ▼
 scoring.py vs ground truth ─▶ results.md / results.json / runs.jsonl ─▶ MLflow
```

---

## 5. Likely questions, with short answers

1. **Why not just roll back the latest deploy?** It works only when the latest deploy is guilty. That was
   true in 50% of push runs and 0% of environment and data faults (RESULTS.md). A rollback during a
   dependency outage changes nothing and wastes time.
2. **Can the AI break production?** No. It has only read access to the repo and the deploy log, it tests
   fixes on a `git archive` copy in a temp folder, and every report ends with "Nothing was applied to the
   running system". Actions like "restart" are marked "unverified - needs human review".
3. **Why a free model?** Paid keys didn't work: glm-4.6 answered "Insufficient balance" (we saw it live on
   2026-09-24, error 1113), and the Gemini and Claude keys failed (RESULTS.md). GLM-4.5-Flash is free and
   still the best of the three models measured.
4. **How do you know the scores are fair?**
   - The same frozen evidence is used for every setup.
   - The ground truth was written when the fault was injected.
   - Alarm texts never name causes, and the doctor never sees `faults/` or `incidents/`.
   - There are 3 repeats with different seeds, the ranges are reported, and a strong baseline is scored
     with the same rules.
   - Known leaks are disclosed: retrieval was tuned on f1 r1, and the reversed-edit correction is counted
     separately.
5. **Isn't 0.56 accuracy bad?** On environment faults the baseline gets 0.00, and the right cause is in
   GLM's top 3 in 0.89 of runs. It narrows the search a lot. It is a helper, not an autopilot.
6. **What if the AI invents a commit?** The doctor checks every commit it names against the candidate
   list; a made-up one is removed and recorded as a rule violation. We saw exactly that live: "named a
   commit that is not a candidate: 73e80cf".
7. **What if the internet is down?** The doctor falls back to local llama3.2. But in our live run 1, the
   online model's retries used up the 6-call budget, so the fallback couldn't finish and the report
   failed. That is a real weakness, found while preparing this lecture.
8. **Why so many alarms for one fault?** One cause, many symptoms (service down, failed calls, slow
   searches, refusals). No inhibit rules, on purpose. Alarms on the same service within 10 minutes join
   one incident, and later ones become new incidents that reach the same diagnosis.
9. **Why does detection take 47 s, not 5 s?** `for: 45s` on `ServiceDown`. Anything shorter pages on
   every deploy, because a recreate takes about 15 s (D-59).
10. **Why did the memory leak take 14 minutes to alarm?** Growth must be sustained for 3 minutes after
    the first 10 minutes of a process's life. Start-up allocation is not a leak (D-59, D-71).
11. **Why local Ollama for the app but a cloud model for the doctor?** The patient must be breakable
    (Ollama is one of its failure points), and the doctor must survive that. Cloud reasoning keeps the
    doctor independent of the patient's GPU (D-40, D-63).
12. **Couldn't you just give the model everything?** More evidence hurt llama3: adding commits pushed
    false attribution on environment faults from 0.00 to 0.83. Evidence needs gating.
13. **What does "verified" mean for a fix?** The diff applied to a copy of the code at the running commit,
    and **every** patient test passed. Separately, the fault's own acceptance test says whether it
    actually fixed the fault.
14. **Why search/replace edits instead of diffs?** Small models rarely produce a diff `git apply` accepts;
    exact find→replace is easier to get right, and the doctor renders the real diff itself (D-35).
15. **Why is f7 (missing documents) so hard?** Nothing errors: answers are politely refused. Refusals rose
    to about 20%, under the 30% alarm, and the prompt doesn't contain document counts. Every model missed
    the real cause.
16. **How long does a diagnosis cost?** Replay averages: GLM 54.7 s and 14.2k tokens; llama3 11.1 s. Money:
    $0. GLM-4.5-Flash is free and the local models cost nothing (RESULTS.md).
17. **Is 16 incidents enough?** It's small: one incident moves a rate by 0.12-0.5. The results are strong
    enough to show the big differences (for example 0.11 vs 0.67 false attribution), not small ones.
18. **What about GitHub Actions?** The same two scripts are wired into `.github/workflows/ci.yml` for a
    self-hosted runner on the Pavilion. **That path has never run**; all numbers come from the local
    pipeline.
19. **Why not use an existing AIOps product?** The goal was to measure *how much* each kind of evidence
    helps and whether it misleads, which needs full control of the evidence, the prompt and the scoring.
20. **What's the deliberate "latent bug" in the embedder?** When Ollama is slow, the embedder silently
    uses hash vectors, so answers are confidently wrong. It is kept on purpose as fault f1's mechanism and
    watched by the `EmbeddingFallbackActive` alarm (D-0).
21. **Does the doctor learn over time?** Only through the past-incident index: resolutions you record
    (`POST /api/incidents/{id}/resolve`) become evidence for later incidents. The model itself is not
    retrained.
22. **Could a ticket be abused to blame someone?** A ticket only sets a time window; the diagnosis still
    comes from logs, metrics and deploys. The text is shown to the model as "user report", not as fact.
23. **Why did the live doctor call it "capacity" in RESULTS.md but "dependency_failure" today?** The
    campaign ran on llama3.2 with a 4k context (4 of 16 classes right); today used GLM-4.5-Flash. The same
    difference shows in replay: 0.81 vs 0.58 class accuracy.
24. **What would you improve first?** Gate the commit evidence (only show commits when logs or metrics
    point at code), add KB version and document counts for data faults, and stop the primary model's
    retries from using up the fallback's call budget.

---

## 6. Command cheat sheet (one page)

All from `D:\college\VII-sem\IDT\ai-incident-doctor`. **A** = PowerShell, **B** = Git Bash.

| When | Win | Command |
|---|---|---|
| T-60 | A | `(Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue` |
| T-55 | A | `Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"` |
| T-55 | A | `Invoke-RestMethod http://127.0.0.1:11434/api/version` |
| T-55 | A | `docker start $(docker ps -aq --filter "name=^aid-")` |
| T-50 | A | `Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "-m","faults.background_traffic","--hours","4" -WindowStyle Hidden -PassThru` |
| T-45 | A | the health-check block in [section 1](#t-45-health-check) |
| T-45 | A | `` curl.exe -s -o NUL -w "%{http_code}`n" --max-time 10 https://api.z.ai/api/paas/v4/models `` (000 = no internet) |
| c | A | ask with a request id: the `Invoke-WebRequest ... 'X-Request-ID' = 'lecture-demo-001'` block in [c](#c-observability-logs-metrics-and-request-ids) |
| c | Grafana | Explore → Loki → `{compose_service=~".+"} \|= "lecture-demo-001"` |
| d | B | `.venv/Scripts/python.exe loadgen/loadgen.py --mode search --rate 5 --concurrency 10 --duration 120` |
| d | B | `.venv/Scripts/python.exe loadgen/loadgen.py --mode chat --rate 1 --concurrency 8 --duration 120` |
| d | Prom | Q1-Q10 from the [table in d](#d-prometheus-from-zero) |
| g | A | `.venv\Scripts\python.exe -m dvc dag` then `.venv\Scripts\python.exe -m dvc status` |
| i | B | `.venv/Scripts/python.exe -m faults.run_fault f3_retrieval_down --label class` |
| i | A | `Invoke-RestMethod http://localhost:18000/api/system/status` |
| i | A | `Invoke-RestMethod http://localhost:18100/health` |
| i plan B | A | `cd doctor` → `..\.venv\Scripts\python.exe -m app.replay ..\incidents\recorded\f3_retrieval_down-r2\bundle.json --provider glm --model glm-4.5-flash` → `cd ..` |
| i offline | A | same, with `--provider ollama --model llama3.2` |
| j | UI | Incidents → Report a problem (or the `Invoke-RestMethod .../doctor-api/ticket` block in [j](#j-the-ticket-demo-a-person-reports-a-problem)) |
| k | B | `git push pipeline main` (**only after the doctor demos**) |
| after | A | `Get-CimInstance Win32_Process -Filter "Name='python.exe'" \| Where-Object CommandLine -like '*background_traffic*' \| ForEach-Object { Stop-Process -Id $_.ProcessId }` |
| after | A | `docker stop $(docker ps -q --filter "name=^aid-")` |

---

## 7. Troubleshooting during the lecture

### Docker fails
- **Symptom:** `docker` commands hang or say "error during connect", or many services are FAILED.
- **Do:**
  1. Check memory: `(Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue`.
  2. Close programs.
  3. Restart Docker Desktop (tray icon → Restart). DECISIONS.md D-33 says restarting it recovered the
     engine after a memory freeze. How long that takes is **not verified**.
  4. Then run `docker start $(docker ps -aq --filter "name=^aid-")`.
- **Meanwhile show:** [`backup/00_health_check.txt`](lecture/backup/00_health_check.txt), then continue
  with the backups for each section.

### Ollama fails
- **Symptom:** chat answers fail or say "offline"; `http://localhost:11434/api/version` fails;
  `/api/system/status` shows `"ollama": "offline"`.
- **Do:** `Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"`, wait 10 s, try again.
- **Warning:** while Ollama is down, the embedder silently falls back to hash vectors (D-0). Answers will
  be *wrong*, not *errors*, and the `EmbeddingFallbackActive` alarm may fire. That is a good teaching
  moment ("this is fault f1's mechanism"), not a disaster.
- **Meanwhile show:** [`backup/02_ask_a_question.txt`](lecture/backup/02_ask_a_question.txt).

### An alert doesn't fire
- **Check:** tab 5 (Alerts). *Pending* means wait: `ServiceDown` needs 45 s, others 1-2 min. *Inactive*
  means the condition is false; check Q1 `up{job="retrieval"}`. Is it really 0?
- **Check:** Alertmanager (tab 6) and alert-sink (tab 7). Is the alert there?
- **Meanwhile show:**
  [`backup/05_big_demo_f3_live/watch_timeline.txt`](lecture/backup/05_big_demo_f3_live/watch_timeline.txt)
  and [`alert_sink_alerts.txt`](lecture/backup/05_big_demo_f3_live/alert_sink_alerts.txt).

### The doctor report says "Diagnosis failed"
- **Most likely cause:** the online model. Open the incident; the failures are listed at the bottom:
  - `Insufficient balance ... 1113`: the model name in `.env` is a paid model. On 2026-09-24 `.env` said
    `DOCTOR_MODEL=glm-4.6`; it was changed to `glm-4.5-flash`.
  - `APIConnectionError: Connection error`: no internet.
  - `BudgetExceeded: call budget of 6 exhausted`: the online model's retries used up the calls, so the
    local fallback couldn't finish.
- **Do in class:** don't fix config live. Show the failed report honestly
  ([`05a_live_f3_run1_doctor_failed/`](lecture/backup/05a_live_f3_run1_doctor_failed/)), then the good one
  ([`05_big_demo_f3_live/live_report.md`](lecture/backup/05_big_demo_f3_live/live_report.md)), and run the
  offline replay (`--provider ollama --model llama3.2`, 4.6 s).
- **Fix after class (if needed):** off the projector, set `DOCTOR_MODEL=glm-4.5-flash` in `.env`, then
  `.venv\Scripts\python.exe deploy\deploy.py --no-build --reason "doctor model"`. On 2026-09-24 this took
  5 s and recreated only the doctor.

### The internet fails
- **Effect:** GLM can't be reached. The live doctor's reports will very likely **fail** (see above). The
  patient app is **not** affected: it's all local.
- **Check:** `` curl.exe -s -o NUL -w "%{http_code}`n" --max-time 10 https://api.z.ai/api/paas/v4/models ``
  prints `000`.
- **On 2026-09-24 the cause was the college Wi-Fi.** From about 10:45 UTC every HTTPS connection failed
  (google.com too). `curl.exe -sv https://api.z.ai/` showed *"The certificate chain was issued by an
  authority that is not trusted"*, meaning the network was intercepting HTTPS, which usually means it wants
  you to log in again in a browser. Try opening any website and logging in to the Wi-Fi portal. That this
  fixes it is **not verified**.
- **Do:** still run the fault demo. Detection, the alarm, alert-sink and the incident opening all work
  offline. For the report, use the offline replay (llama3.2) and the saved GLM reports:
  - [`05_big_demo_f3_live/live_report.md`](lecture/backup/05_big_demo_f3_live/live_report.md)
  - [`07_replay_f3_r2_glm/report.md`](lecture/backup/07_replay_f3_r2_glm/report.md)
  - [`09_ticket_report.md`](lecture/backup/09_ticket_report.md)
  - [`10_report_with_verified_fix_f1_glm.md`](lecture/backup/10_report_with_verified_fix_f1_glm.md)

### The fault script errors out
- **`working tree is dirty; commit or stash first`:** you have uncommitted changes to tracked files.
  Don't commit in class: show the recorded result.
- It always reverts, even when watching fails (`run_fault.py` catches errors before the revert). If you
  are unsure, check `docker ps --filter "name=aid-retrieval"`. If it says "Exited", run
  `docker start aid-retrieval-1` and check health.

### The pipeline push fails or hangs
- The log path is printed: `runtime/pipeline-logs/<sha>.log`. A failed verify means nothing was
  deployed; the old version keeps running.
- **Show:** [`backup/01_pipeline_push.txt`](lecture/backup/01_pipeline_push.txt).

### The laptop gets slow
- Check memory. Stop the extra load (Ctrl+C in Window B). Close browser tabs you've finished with.

---

## 8. Glossary

| Term | Plain meaning |
|---|---|
| **acc@1 / acc@3** | Was the right cause the model's first guess (acc@1), or in its top 3 (acc@3)? |
| **Ablation** | Removing one ingredient at a time to see how much it helps. Here: logs only → + commits → + past incidents. |
| **Acceptance test** | A test written for one specific fault that fails while the fault is present and passes once it is fixed. |
| **Alert / alarm** | A rule that "fires" when a condition stays true long enough. |
| **Alert-sink** | This project's tiny service that logs every alarm and forwards it to the doctor. |
| **Alertmanager** | Receives alarms from Prometheus, groups them and sends them on. |
| **Alloy** | Grafana's log shipper: reads container output and sends it to Loki. |
| **Baseline (evaluation)** | A simple method to compare against: "blame the most recent deploy". |
| **Baseline window** | The 30 minutes before the incident window, used as "normal". |
| **Bare repository** | A git repo with no working files, used only to receive pushes. |
| **Bundle (`bundle.json`)** | The doctor's frozen snapshot of all the evidence for one incident. |
| **cAdvisor** | Google's container metrics tool. It is partly blind on this Docker version, so container-exporter fills in (D-27). |
| **Candidate commit** | A commit shipped by a deploy in the 6 hours before the alarm, the only ones the doctor may blame. |
| **CI/CD** | Continuous Integration / Continuous Delivery: automatic checks and deploys on every push. |
| **ChromaDB** | The vector store holding the document chunks. |
| **Chunk** | A piece of a document (about 800 characters here) stored with its embedding. |
| **Container** | A packaged, isolated running program (Docker). |
| **Counter** | A metric that only goes up (like an odometer). |
| **Dependency failure** | Something the app relies on is down or unreachable. |
| **Deploy record** | One JSON line in `runtime/deploys.jsonl` saying what was deployed, when, and by which pipeline. |
| **Distractor commit** | A harmless real commit placed near a guilty one, so "newest commit" is not the answer. |
| **Docker Compose** | Starts all the containers from one file (`docker-compose.yml`). |
| **DVC** | Data Version Control: git-like versioning for large data files (here the knowledge base). |
| **Embedding** | A list of numbers (768 here) that captures the meaning of a text; similar texts get similar numbers. |
| **Environment fault** | A break with no code change (a stopped service, a wrong address, a traffic surge). |
| **False attribution** | Blaming a commit when no commit was guilty. |
| **FastAPI** | The Python web framework the services are built with. |
| **`for:`** | How long an alert's condition must stay true before it fires. |
| **Gauge** | A metric that goes up and down (like a fuel gauge). |
| **GLM-4.5-Flash** | The free online language model (Z.ai) the doctor uses. |
| **Grafana** | The dashboard tool that draws metrics and searches logs. |
| **Ground truth** | The real answer for a fault, written when it was injected. |
| **Guardrail** | A check on the question or answer (in scope? safe? grounded?). |
| **Hash fallback** | The embedder's silent emergency mode: fake vectors from word hashes (D-0). |
| **Histogram** | A metric counting observations in buckets (e.g. requests under 0.1 s, under 0.25 s…). |
| **`histogram_quantile`** | PromQL function estimating a percentile (like p95) from histogram buckets. |
| **Incident** | One problem episode the doctor opens and diagnoses. |
| **Incident class** | The kind of problem: code_defect, configuration, capacity, dependency_failure, data_issue. |
| **Incident window** | From 10 minutes before the alarm to 1 minute after. |
| **In flight** | Requests being processed right now. |
| **Inhibit rule** | An Alertmanager rule that hides one alarm when another fires. This project uses none. |
| **Knowledge base (KB)** | The documents the app answers from. |
| **kb-loader** | The one-shot job that loads a KB version into ChromaDB and logs it. |
| **Label** | A key=value tag on a metric (e.g. `service="gateway"`). |
| **Latency** | How long a request takes. |
| **LLM** | Large language model, the AI that writes text (llama3.2, llama3, GLM). |
| **Log** | A diary line written by a service. |
| **Log signature** | A fingerprint of an error with the changing parts removed, so repeats group together. |
| **Loki** | The log database. |
| **LogQL** | Loki's query language (`{compose_service=~".+"} \|= "text"`). |
| **Metric** | A number measured over time. |
| **MinIO** | Local S3-compatible file storage (for DVC and MLflow). |
| **MLflow** | Experiment tracker: records each evaluation run's settings and scores. |
| **Observability** | Seeing what's happening inside from logs, metrics and traces. |
| **Ollama** | The program that runs local AI models on this laptop. |
| **OOM kill** | The system killing a container that used more memory than its limit. |
| **p50 / p95 / p99** | 50%/95%/99% of requests were faster than this time. |
| **Patient** | The app being watched and broken on purpose (KnowledgeAI). |
| **Pending / firing / resolved** | Alarm states: condition true but not long enough / alarm on / condition over. |
| **Pipeline** | The automatic sequence: push → verify → deploy. |
| **Post-receive hook** | A script git runs after receiving a push, which runs the pipeline here. |
| **Prometheus** | Collects metrics every 5 s and evaluates alarm rules. |
| **PromQL** | Prometheus's query language. |
| **Push fault** | A break delivered as a real git commit through the pipeline. |
| **RAG** | Retrieval-augmented generation: look up relevant text first, then let the AI answer from it. |
| **`rate()`** | PromQL: per-second increase of a counter over a time window. |
| **Replay** | Diagnosing a stored snapshot again, with nothing live touched. |
| **Request id** | A tracking number attached to one request and passed between services. |
| **Retrieval** | Finding the most relevant chunks (the app) or commits/code (the doctor). |
| **Rollback** | Going back to the previous good version. |
| **Sandbox / throwaway copy** | A temporary copy of the code where a fix is tested. |
| **Schema** | The fixed layout the doctor's answer must follow. |
| **Scrape** | Prometheus reading a service's `/metrics` page. |
| **SHA** | A commit's unique id (e.g. `73e80cf`); images are tagged with it. |
| **Smoke test** | A quick "is it basically working?" check after a deploy. |
| **Symptom** | What is observed (slow, errors), as opposed to the cause. |
| **Ticket** | A person's plain-words problem report to the doctor. |
| **Token** | A piece of a word; models read and write tokens and are limited by counts of them. |
| **Vector store** | A database that finds items by similarity of their embeddings. |

---

## 9. Appendix: what was run, what was not

**Run on this laptop on 2026-09-24 (commit `73e80cf`, UTC times), with timings:**

| Demo | Command | Took | Result | Backup |
|---|---|---|---|---|
| Pipeline push | `git push pipeline main` (Git Bash) | 65 s | SUCCESS; 173 + 1 + 60 tests passed; 16 rules | `01_pipeline_push.txt` |
| Health check | the block in section 1 | about 2 s | 17 × 200 | `00_health_check.txt` |
| Ask a question | `Invoke-WebRequest .../api/chat` | 2.6 s | "75%" answer, 4 sources | `02_ask_a_question.txt` |
| Request-id trace | Loki query | about 1 s | 10 lines, 3 services | `03_request_id_trace.txt` |
| Search load | loadgen search 5/s | 121 s | 601 requests, 0 errors; gateway 0.82 → 5.58 req/s | `04_prometheus_queries.txt` |
| Chat load | loadgen chat 1/s | 125 s | 123 requests, 0 errors; chat p95 2.67 → 6.96 s | `04_prometheus_queries.txt` |
| Grafana panels | panel queries via Prometheus | - | values per minute | `04b_grafana_panels.txt` |
| Big demo, run 1 | `run_fault f3_retrieval_down --label lecture` | 185 s | alarm after 48.9 s; **doctor failed** (glm-4.6: insufficient balance) | `05a_live_f3_run1_doctor_failed/` |
| Doctor model fix | `.env` DOCTOR_MODEL → glm-4.5-flash; `deploy.py --no-build` | 5 s | doctor recreated | - |
| Big demo, run 2 | `run_fault f3_retrieval_down --label lecture2` | 209 s | alarm after 46.9 s; report after 128.0 s; **correct** | `05_big_demo_f3_live/` |
| Follow-up alarms | (automatic) | 129-270 s each | all `dependency_failure` except one catch-up `capacity` | `05b_live_glm_reports_after_run1/` |
| DVC | `dvc dag`, `dvc status` | 2.7 s | 1 stage; 2 deps changed by comments | `06_dvc.txt` |
| Replay (GLM) | `app.replay ... --provider glm` | 41.3 s | correct | `07_replay_f3_r2_glm/` |
| Replay (offline) | `app.replay ... --provider ollama --model llama3.2` | 4.6 s | wrong class (`capacity`) | `07b_replay_f3_r2_llama32_offline.md` |
| MLflow | REST API | - | values match RESULTS.md | `08_mlflow_runs.txt` |
| Ticket | `POST /doctor-api/ticket` | 39 s to report | onset found; correct | `09_ticket_*.{txt,md}` |
| Report with a tested fix | from `doctor/eval/results/glm/runs.jsonl` | - | verified; acceptance passed | `10_report_with_verified_fix_f1_glm.md` |

**Not run on 2026-09-24 (show the recorded result):** f1, f2, f3b, f4, f5, f6, f7, and the full evaluation
(`python -m doctor.eval.run_eval`, hours of replays).

**Not verified:**
- The visual layout of the browser pages. URLs and data were checked, the pages were not viewed.
- Restarting Docker Desktop mid-lecture.
- What Z.ai returns to the internet check when the connection works (the Wi-Fi lost internet at about
  10:45 UTC and did not return during testing).
- Running `git push pipeline main` and `faults.run_fault` from PowerShell. They were run from Git Bash,
  which is why this guide says Window B.
