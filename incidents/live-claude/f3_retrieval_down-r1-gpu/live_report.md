# Incident inc_c5f9b75968

**Alert:** ServiceDown - retrieval is not answering Prometheus scrapes
**Started:** 2026-11-22T07:36:31.923Z  
**Running commit:** 1a290b0  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** anthropic:claude-opus-5-5

## What broke

The retrieval container stopped and dropped off the Docker network. Its DNS name no longer resolves, so every gateway call to retrieval fails with ConnectError 'Temporary failure in name resolution', Prometheus cannot scrape retrieval:8002, and gateway 5xx reached about 63%. The deployed commits only change GCP/Ollama start-up scripts and agent config, which does not explain retrieval disappearing, so no commit is blamed.

**Incident class:** `dependency_failure`

**Demand versus capacity:** traffic rose, deploy before onset: True, verdict: capacity_fell. Traffic did rise (traffic_rps x6.9, gateway rps x14). But the failure is not saturation. Retrieval latency stayed low (p95 0.097s falling to 0.047s), in_flight peaked at 1, and retrieval memory was flat at about 96MB. The failure is a hard outage: up=0, and ConnectError with [Errno -3] name resolution failures from 07:35:44, a sign the retrieval container is no longer running on the compose network. Deploy 1a290b0 landed at 07:23:16, about 12 minutes before onset. Its commits (09770921 Ollama keep-alive in startup.sh, 1a290b0 'systemctl enable --now ollama', 25a35db Claude config) do not touch the retrieval service, compose service definitions or networking. The deploy is therefore not plausibly causal. Capacity fell because a component went down, not because demand outgrew a healthy system.

## Evidence

- alert 2026-11-22T07:36:31.923Z **ServiceDown** retrieval: retrieval is not answering Prometheus scrapes
- alert 2026-11-22T07:36:53.987Z **DownstreamCallFailures** gateway: calls from gateway to retrieval are failing
- log `WARNING:a4dace19f999` x48 in gateway:  request
- log `ConnectError:bf91e0cfbf34` x24 in gateway: ConnectError [Errno -3] Temporary failure in name resolution
- metric `traffic_rps{all}` baseline 0.1292 -> 0.8909 (x6.9)
- metric `requests_rps{service=gateway}` baseline 0.0824 -> 1.1636 (x14.1)
- metric `requests_rps{service=ingestion}` baseline 0.0663 -> 0.2727 (x4.1)
- metric `requests_rps{service=llm}` baseline 0.07 -> 0.5455 (x7.8)
- metric `requests_rps{service=retrieval}` baseline 0.0825 -> 1.1455 (x13.9)
- metric `error_ratio_5xx{service=gateway}` baseline None -> 0.6304 (appeared (no baseline))
- metric `chat_outcomes_rps{outcome=answered}` baseline 0.1713 -> 0.3455 (x2.0)
- metric `chat_outcomes_rps{outcome=refused_scope}` baseline None -> 0.2364 (appeared (no baseline))

Deploys in the lookback window: 1; candidate commits (time filter only): 6

## Ranked causes

| # | confidence | component | suspected commit | cause |
|---|---|---|---|---|
| 1 | 0.75 | retrieval | none | The retrieval container exited or was removed, so Docker's embedded DNS no longer resolves 'retrieval'. Gateway calls fail at name resolution and the Prometheus scrape of retrieval:8002 fails. |
| 2 | 0.15 | infrastructure | none | The traffic surge (gateway rps x14, retrieval rps x14) put the retrieval process under resource pressure (e.g. container OOM-kill or crash under load), after which it was not restarted. |
| 3 | 0.10 | infrastructure | none | Compose-level activity around deploy 1a290b0 (services=['compose','doctor']) recreated or stopped containers, leaving retrieval detached from the network. |

Evidence for #1:
- ConnectError:bf91e0cfbf34 x24 NEW from 2026-11-22T07:35:44Z: httpx.ConnectError: [Errno -3] Temporary failure in name resolution (gateway -> retrieval)
- service_up went 1 -> 0; ServiceDown alert for retrieval:8002 at 07:36:31Z
- downstream_failures_per_min{reason=ConnectError,target=retrieval} appeared, max 46.9/min
- requests_rps{service=retrieval} collapsed to 0.119 at window end while gateway rps stayed at 0.73
- error_ratio_5xx{gateway} appeared, max 0.63

Evidence for #2:
- traffic_rps rose x6.9 and retrieval requests_rps rose to max 1.15 just before the outage
- retrieval process_memory_mb rose from a baseline mean of 85 to 96MB, though it remained small

Evidence for #3:
- deploy 1a290b0 at 07:23:16Z touched 'compose', about 12 min before onset
- none of the deployed diffs modify the retrieval service, so this is only a timing correlation

## Proposed fix

**Kind:** action

The symptoms show the retrieval container is missing from Docker DNS: name-resolution ConnectErrors and a failed scrape, while latency and memory before the outage were healthy. No candidate commit changes retrieval, so the remedy is operational: restart the service and capture its exit reason to rule out an OOM-kill under the traffic surge. This should be done by an operator, not applied automatically.

**Recommended action:** Bring the retrieval service back on the compose network. First record the cause: run `docker compose ps retrieval` and `docker inspect <retrieval container> --format '{{.State.ExitCode}} {{.State.OOMKilled}} {{.State.Error}}'`, then capture `docker compose logs --tail=300 retrieval`. Then restart it with `docker compose up -d retrieval`. Verify that `curl retrieval:8002/metrics` from the gateway container succeeds, that up{job=retrieval}=1, and that gateway ConnectError failures stop. If the exit was an OOM-kill or crash under load, add `restart: unless-stopped` and a suitable memory limit for retrieval in the compose file as a follow-up change.

## Verification

**Result:** unverified - needs human review
  
an operational action cannot be tested on a copy; a human must carry it out

Nothing was applied to the running system.

## Cost

2 calls, 22478 prompt + 3964 completion tokens, $0.169192; reasoning 35.23s, total 40.04s
