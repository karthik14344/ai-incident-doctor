# Incident inc_3d3a0329bf

**Alert:** DownstreamCallFailures - calls from gateway to retrieval are failing
**Started:** 2026-11-22T12:29:03.987Z  
**Running commit:** 3bf46d7  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

Gateway-to-retrieval chat calls fail with httpx.ReadTimeout because commit 3bf46d7 (deployed 12:27:56Z) cut the retrieval client timeout in chat_stream from 30 s to 0.05 s. Retrieval's own p95 is about 0.05-0.1 s, so a large share of normal calls exceed the new limit. The same change was shipped once before (cf515c9) and reverted (1c5b681); it has been reintroduced.

**Incident class:** `code_defect`

**Demand versus capacity:** traffic rose, deploy before onset: True, verdict: capacity_fell. Traffic did rise (traffic_rps x2.6), which explains slower LLM generation but not this alert. Retrieval stayed healthy and fast: /retrieve p50 went from 0.026 s to 0.030 s and p95 peaked at 0.0975 s. None of those calls would time out under the previous 30 s client timeout. The ReadTimeout failures are new (absent in baseline). They began at 12:27:49Z, coinciding with the 12:27:56Z rollout of 3bf46d7, whose diff sets timeout=0.05, at or below retrieval's normal p95. The failures come from the change, not from demand overwhelming retrieval.

## Evidence

- alert 2026-11-22T12:29:03.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- log `ReadTimeout:3bd5a2c1f252` x20 in gateway: ReadTimeout retrieval call failed
- log `ConnectTimeout:a738a48e0775` x1 in gateway: ConnectTimeout retrieval call failed
- metric `traffic_rps{all}` baseline 0.6068 -> 1.5818 (x2.6)
- metric `requests_rps{service=gateway}` baseline 0.6685 -> 1.6364 (x2.4)
- metric `requests_rps{service=llm}` baseline 0.2208 -> 1.0727 (x4.9)
- metric `requests_rps{service=retrieval}` baseline 0.6368 -> 1.6182 (x2.5)
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1571 -> 1.0182 (x6.5)
- metric `chat_outcomes_rps{outcome=refused_output}` baseline 0.0 -> 0.0182 (from ~0)
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline 0.1068 -> 0.2182 (x2.0)
- metric `latency_p95_s{endpoint=/api/chat,service=gateway}` baseline 2.0088 -> 7.368 (x3.7)

Deploys in the lookback window: 18; candidate commits (time filter only): 29

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.90 | gateway | 3bf46d7 | Commit 3bf46d7 set the gateway's retrieval client timeout in chat_stream to 0.05 s. Retrieval latencies at or above ~50 ms (p95 0.05-0.1 s, worse under higher load) now raise httpx.ReadTimeout. This reintroduces the previously reverted change cf515c9. |
| 2 | 0.10 | retrieval | none | Higher traffic (x2.5) slowed retrieval and generation somewhat. This pushed more retrieval calls past the tight timeout, but it would not cause failures on its own. |

Evidence for #1:
- diff: '-    async with telemetry.async_client("gateway", timeout=30.0) as client:' -> '+    async with telemetry.async_client("gateway", timeout=0.05) as client:'
- log signature ReadTimeout:3bd5a2c1f252 x20, NEW, first=12:27:49Z, running=3bf46d7 (deployed 12:27:56Z)
- downstream_failures_per_min{reason=ReadTimeout,target=retrieval} appeared with no baseline, max 12/min
- latency_p95_s{/retrieve} baseline 0.0537 s, incident max 0.0975 s, above the 0.05 s limit
- identical change cf515c9 was previously reverted by 1c5b681

Evidence for #2:
- traffic_rps x2.6, requests_rps{retrieval} x2.5
- latency_p50_s{/api/retrieval/search} x2.0

## Proposed fix

**Kind:** code_diff

Revert the chat_stream retrieval timeout to 30 s, matching the earlier revert 1c5b681. A 50 ms timeout sits at retrieval's normal p95 and fails healthy requests; 30 s still bounds a stuck call. If fail-fast behaviour is wanted, a separate review should choose a value well above the observed p95 (e.g. a few seconds). Deploy through the normal pipeline, not automatically.

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
  
Test suite on the patched copy: 171 passed, 4 warnings in 4.84s

Nothing was applied to the running system.

## Cost

2 calls, 23466 prompt + 3528 completion tokens, $0.164424; reasoning 29.31s, total 41.07s
