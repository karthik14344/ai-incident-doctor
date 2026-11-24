# Incident inc_1862a7a2e2

**Alert:** HighLatencyP95 - p95 latency of gateway /api/chat is 85.0s
**Started:** 2026-11-22T07:53:00.51Z  
**Running commit:** 1a290b0  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

Demand on /api/chat roughly tripled: gateway requests rose x3.6 and LLM /generate calls rose x6.7. The single local Ollama generation backend saturated, so requests queued up to 100 in flight and p95 latency reached about 118 s. Embedding, retrieval and Chroma stayed fast, with no errors, restarts or OOM kills. This is a capacity problem, not a defect.

**Incident class:** `capacity`

**Demand versus capacity:** traffic rose, deploy before onset: True, verdict: demand_rose. traffic_rps went from a baseline mean of 0.53 to an incident max of 1.49 (x2.8). requests_rps for llm went from 0.17 to 1.16 (x6.7), and answered chats rose x7.2. in_flight for gateway and llm climbed from about 0 to 100 while retrieval in_flight stayed at about 0-1. Retrieval p95 stayed flat (0.055 s vs 0.054 s mean), and ollama embed p95 was flat (0.05 s). Only ollama generate p95 exploded, rising in step with the queue. The only deploy (1a290b0) landed at 07:23:16, 20 minutes before the incident window. The 07:23-07:43 baseline after that deploy shows normal latency (p95 about 1.9 s at the start of the incident window). There are no warnings or errors in the incident window, no restarts and no OOMs, and 5xx is 0. The baseline's ConnectError and 5xx were an earlier, already-resolved blip and are absent during the incident. The same service got slower only as load rose, which points to demand, not a regression. The deploy's diffs are GCP start-up and Ollama keep-alive changes plus doctor config; none of them would slow generation under the same load.

## Evidence

- alert 2026-11-22T07:53:00.51Z **HighLatencyP95** gateway: p95 latency of gateway /api/chat is 85.0s
- alert 2026-11-22T07:53:00.51Z **HighLatencyP95** llm: p95 latency of llm /generate is 84.9s
- metric `traffic_rps{all}` baseline 0.5317 -> 1.4909 (x2.8)
- metric `requests_rps{service=gateway}` baseline 0.4293 -> 1.5636 (x3.6)
- metric `requests_rps{service=ingestion}` baseline 0.088 -> 0.1455 (x1.7)
- metric `requests_rps{service=llm}` baseline 0.1732 -> 1.1636 (x6.7)
- metric `requests_rps{service=retrieval}` baseline 0.3895 -> 3.2727 (x8.4)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1538 -> 1.1091 (x7.2)
- metric `chat_outcomes_rps{outcome=refused_output}` baseline 0.0 -> 0.0182 (from ~0)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 1.8868 -> 118.3125 (x62.7)

Deploys in the lookback window: 1; candidate commits (time filter only): 6

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.85 | ollama | none | Chat demand rose above the throughput of the single Ollama llama3.2 generation backend. Generate requests queue inside Ollama, so llm and gateway in_flight pile up to 100 and per-request latency grows linearly with the queue. |
| 2 | 0.10 | gateway | none | The gateway and llm services have no admission control or concurrency limit. Excess chat requests are accepted and queued for minutes instead of being rejected fast, which turns a throughput limit into extreme tail latency. |

Evidence for #1:
- requests_rps{service=llm} rose from a baseline of 0.17 to an incident max of 1.16 (x6.7); traffic_rps{all} rose x2.8
- in_flight{service=llm} and in_flight{service=gateway} went from about 0.07 to 100, while in_flight{service=retrieval} stayed at a max of 1
- ollama_p95_s{operation=generate} rose from 2.26 to 118.3 s, while ollama_p95_s{operation=embed} stayed flat at about 0.05 s
- latency_p95_s{/retrieve} stayed flat (0.055 vs 0.054 mean)
- There are no error logs, error_ratio_5xx is 0, and container_restarts and oom_kills are 0
- Gateway and llm memory grew x2.6 and x2.4, consistent with a backlog of queued requests rather than a leak

Evidence for #2:
- in_flight{service=gateway} grew without bound to 100, while p50 /api/chat latency reached 103 s
- No 429 or 503 responses: error_ratio_5xx stayed at 0 while latency climbed

## Proposed fix

**Kind:** action

The system is healthy and the backlog is caused by demand. The only saturated resource is LLM generation in Ollama. Retrieval, embedding and Chroma are unaffected, and nothing is erroring or restarting. The remedy is more generation throughput plus admission control, not a code or config revert; the deploy 20 minutes earlier ran normally at baseline load.

**Recommended action:** Add generation capacity and shed load; do not roll back 1a290b0.
1. Raise Ollama's parallelism if the host has GPU or CPU headroom (OLLAMA_NUM_PARALLEL), then restart ollama, or move Ollama to a larger or GPU-backed instance. Alternatively, add a second Ollama backend behind the llm service.
2. Throttle or shed the extra /api/chat traffic at the gateway in the meantime: rate-limit it or cap concurrent generations so that excess requests get a fast 429/503 instead of queuing for over 100 s.
3. Confirm recovery: llm in_flight should drain to about 0 and ollama generate p95 should return to about 2-4 s.
An operator should perform these steps manually.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 23083 prompt + 3932 completion tokens, $0.170972; reasoning 32.33s, total 32.62s
