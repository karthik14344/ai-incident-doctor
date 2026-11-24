# Incident inc_557eed0e8f

**Alert:** DownstreamCallFailures - calls from gateway to retrieval are failing
**Started:** 2026-11-22T09:39:28.987Z  
**Running commit:** 952e417  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

Commit cf515c9 cut the gateway's chat_stream retrieval timeout from 30 s to 0.05 s. It shipped in deploy 952e417 at 09:38:07Z. Retrieval's tail latency (p95 up to about 160 ms under higher load) now exceeds that budget, and gateway->retrieval calls have failed with httpx.ReadTimeout since 09:38:21Z, 14 s after the deploy.

**Incident class:** `code_defect`

**Demand versus capacity:** traffic rose, deploy before onset: True, verdict: capacity_fell. Traffic rose about 2.4x (traffic_rps 0.58 -> 1.41), which pushed LLM/generate latency and in_flight up. That load does not explain the alerted failures. Retrieval stayed healthy: /retrieve p50 was about 27 ms and p95 at most 0.16 s, with no embedding fallbacks and no embed slowdown. The new ReadTimeout signature (gateway -> retrieval) first appeared at 09:38:21Z, 14 s after deploy 952e417, which contains cf515c9 setting timeout=0.05. Under the previous 30 s timeout, 160 ms tail latencies would never fail. The failures come from the code change, not from retrieval running out of capacity. The ConnectError failures in the baseline were a separate, earlier episode and are absent from the incident window.

## Evidence

- alert 2026-11-22T09:39:28.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- log `ReadTimeout:3bd5a2c1f252` x24 in gateway: ReadTimeout retrieval call failed
- metric `traffic_rps{all}` baseline 0.5838 -> 1.4064 (x2.4)
- metric `requests_rps{service=gateway}` baseline 0.6483 -> 1.4609 (x2.3)
- metric `requests_rps{service=llm}` baseline 0.2264 -> 0.8909 (x3.9)
- metric `requests_rps{service=retrieval}` baseline 0.5666 -> 1.5073 (x2.7)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.166 -> 0.8182 (x4.9)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.1383 -> 10.35 (x4.8)
- metric `latency_p95_s{endpoint=/api/retrieval/search,service=gateway}` baseline 0.0859 -> 0.1937 (x2.3)
- metric `latency_p95_s{endpoint=/generate,service=llm}` baseline 2.3462 -> 10.3125 (x4.4)

Deploys in the lookback window: 9; candidate commits (time filter only): 20

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | gateway | cf515c9 | cf515c9 set the gateway chat_stream retrieval client timeout to 0.05 s. Any /retrieve call slower than 50 ms raises httpx.ReadTimeout. Such calls are common at p95 and more common under higher load. |
| 2 | 0.20 | infrastructure | none | Higher demand (2.4x traffic) pushed retrieval and LLM latency up. This made more requests cross the tight timeout and slowed /api/chat overall. |

Evidence for #1:
- diff: `async with telemetry.async_client("gateway", timeout=0.05) as client:` (was timeout=30.0)
- log signature ReadTimeout:3bd5a2c1f252 x24, NEW, first=09:38:21Z, running=952e417 (deployed 09:38:07Z)
- downstream_failures_per_min{reason=ReadTimeout,target=retrieval} appeared, max 12/min
- latency_p95_s{/retrieve}: baseline 0.054 s, incident max 0.16 s; both exceed the 0.05 s budget

Evidence for #2:
- traffic_rps x2.4, in_flight{gateway} up to 8
- ollama generate p95 rose from 2.3 s to 10.3 s

## Proposed fix

**Kind:** code_diff

Restore the 30 s timeout for the chat_stream retrieval call, matching the other retrieval callers (30 s and 60 s). A 50 ms budget is below retrieval's normal p95, so it fails routine requests. If fail-fast behaviour is still wanted, use a budget of several seconds instead. Apply through the normal review and deploy process.

```diff
--- a/patient/api_gateway/app/main.py
+++ b/patient/api_gateway/app/main.py
@@ -507,8 +507,7 @@
     }
 
     retrieval_data = {}
-    # Retrieval answers in ~30 ms; fail fast rather than hold the chat request.
-    async with telemetry.async_client("gateway", timeout=0.05) as client:
+    async with telemetry.async_client("gateway", timeout=30.0) as client:
         try:
             r = await client.post(f"{RETRIEVAL_SERVICE_URL}/retrieve", json=retrieval_payload)
             if r.status_code == 200:
```

## Verification

**Result:** verified
  
Test suite on the patched copy: 171 passed, 4 warnings in 4.76s

Nothing was applied to the running system.

## Cost

2 calls, 22253 prompt + 3407 completion tokens, $0.157152; reasoning 30.82s, total 44.91s
