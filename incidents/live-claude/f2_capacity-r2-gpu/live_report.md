# Incident inc_2f42327b59

**Alert:** HighLatencyP95 - p95 latency of gateway /api/chat is 84.8s
**Started:** 2026-11-22T10:44:30.51Z  
**Running commit:** 4e34716  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

Gateway /api/chat p95 latency rose to about 85-118 s because chat/generation demand roughly quadrupled. Ollama's generate path is the shared bottleneck: requests queue behind it, in-flight hits the 100 cap at both gateway and llm, and every answer waits in line. Nothing is erroring and no relevant code change explains it.

**Incident class:** `capacity`

**Demand versus capacity:** traffic rose, deploy before onset: True, verdict: demand_rose. Total traffic_rps fell, but baseline traffic was mostly cheap retrieval searches. The demand that matters, chat requests that reach generation, rose about 4-5x: requests_rps{llm} went from 0.27 to 1.15 and answered chat outcomes from 0.20 to 1.07 rps. in_flight{llm} climbed from 0.16 to 100 (saturated). Latency rose with queue depth: p50 went to 104 s, but there were no errors, restarts or OOMs and service_up stayed 1. Requests are still answered successfully, just late, which is the signature of queueing at a saturated backend rather than something broken. The only deploy close to onset was 4e34716 at 10:30:38. It touched only retrieval, and retrieval latency is unchanged (p50 about 27 ms, p95 about 57 ms), so it does not explain the symptoms. The retrieval timeout commit cf515c9 was reverted by 1c5b681, and the running code shows timeout=30.0.

## Evidence

- alert 2026-11-22T10:44:30.51Z **HighLatencyP95** gateway: p95 latency of gateway /api/chat is 84.8s
- alert 2026-11-22T10:44:30.51Z **HighLatencyP95** llm: p95 latency of llm /generate is 84.9s
- metric `requests_rps{service=llm}` baseline 0.2672 -> 1.1454 (x4.3)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1974 -> 1.0727 (x5.4)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.5448 -> 118.4151 (x46.5)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 2.4342 -> 118.4434 (x48.7)
- metric `latency_p50_s{endpoint=/api/chat,service=gateway}` baseline 1.2033 -> 104.1509 (x86.6)
- metric `latency_p50_s{endpoint=/api/retrieval/search,service=gateway}` baseline 0.049 -> 0.0762 (x1.6)
- metric `latency_p50_s{endpoint=/generate,service=llm}` baseline 1.1483 -> 104.434 (x90.9)
- metric `in_flight{service=gateway}` baseline 0.7333 -> 100.0 (x136.4)

Deploys in the lookback window: 13; candidate commits (time filter only): 24

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.80 | ollama | none | Chat demand that requires LLM generation rose about 4-5x and exceeds the throughput of the single local Ollama server. Generate calls queue, in-flight saturates at 100, and end-to-end chat latency grows to more than 100 s. |
| 2 | 0.15 | ollama | none | Ollama generation got slower per request (for example, the model reloaded or there is GPU/CPU contention) independent of load, which would amplify queueing. |
| 3 | 0.05 | retrieval | none | The retrieval deploy 4e34716 at 10:30:38 changed behaviour in a way that increases generation work, for example by sending larger contexts. |

Evidence for #1:
- requests_rps{service=llm} baseline 0.27 -> incident max 1.15 (x4.3); chat_outcomes_rps{answered} 0.20 -> 1.07 (x5.4)
- in_flight{service=llm} and in_flight{service=gateway} baseline <1 -> 100 (saturated)
- ollama_p95_s{generate} 2.4 s -> 118.4 s, while ollama_p95_s{embed} is unchanged at about 0.05 s
- Retrieval latency is flat; no error/warning logs, no restarts, no OOM kills; memory growth in gateway/llm is consistent with queued requests

Evidence for #2:
- Generate latency explodes while embed latency stays normal
- The first incident sample of generate p95 is a normal 1.91 s, and degradation tracks the rise in llm request rate, which argues against a standalone slowdown

Evidence for #3:
- This deploy is the only change shortly before onset
- Retrieval latency and memory are normal and no diff in the candidates links it to generation load, so this is unlikely

## Proposed fix

**Kind:** action

The system is healthy, but generation demand exceeds what one Ollama server can serve. Latency is pure queueing, so the remedy is to reduce demand or add capacity. Reverting code would not help: no listed commit explains the load, and the only recent deploy (retrieval) shows unchanged behaviour.

**Recommended action:** Operator steps:
1. Shed or rate-limit the surge of /api/chat traffic at the gateway, and identify its source (client or load test).
2. Add generation capacity:
   - Run more Ollama parallelism (raise OLLAMA_NUM_PARALLEL if GPU memory allows), or add GPU/another Ollama instance.
   - Confirm models stay loaded (OLLAMA_KEEP_ALIVE=-1).
3. Cap llm in-flight concurrency with fast 429/503 rejection, so queued requests do not wait about 2 minutes.
4. Monitor in_flight{llm} draining and generate p95 returning to about 2-4 s.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 22522 prompt + 3997 completion tokens, $0.170028; reasoning 36.98s, total 44.83s
