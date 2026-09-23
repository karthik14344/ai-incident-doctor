# Moving the patient to the HP Pavilion

This file lists exactly what changes when the stack moves from the
development laptop to the Pavilion, and which results must be measured again
there.

| | Development laptop (now) | Pavilion (target) |
|---|---|---|
| OS | Windows 11, Docker Desktop (WSL2 VM, 7.9 GB) | Ubuntu, native Docker Engine, 16 GB RAM, no GPU |
| Runs | the whole compose stack **and** Ollama | the whole compose stack; **Ollama stays on the Windows laptop** |
| Ollama reached at | `127.0.0.1:11434` (host) / `host.docker.internal:11434` (containers) | `http://<windows-laptop-LAN-IP>:11434`, over Wi-Fi |
| CI/CD | local bare remote `pipeline` (`pipeline: local` in deploy records) | GitHub Actions, self-hosted runner `pavilion` (`pipeline: github`) |
| Host ports | shifted +10000 (another project uses the defaults) | defaults (3001, 8000, 3000, 9090, ...) |

## 1. On the Windows laptop (Ollama)

Ollama listens on `127.0.0.1` only by default. The Pavilion must be able to
reach it:

1. Make Ollama listen on every interface. In *System Properties ->
   Environment Variables*, add a user variable `OLLAMA_HOST` = `0.0.0.0`.
   Quit Ollama from the tray and start it again. You can check it from
   PowerShell:
   ```powershell
   [Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0", "User")   # same as the dialog
   netstat -an | findstr 11434        # must show 0.0.0.0:11434 LISTENING
   ```
2. Open the firewall for the private network only:
   ```powershell
   New-NetFirewallRule -DisplayName "Ollama (LAN) 11434" -Direction Inbound -Protocol TCP `
       -LocalPort 11434 -Action Allow -Profile Private
   ```
   The Wi-Fi network must be marked **Private** in Windows settings. Otherwise
   the rule does not apply.
3. Note the laptop's address (`ipconfig`, the Wi-Fi adapter's IPv4 address).
   Give it a DHCP reservation on the router so the address doesn't change.
4. Keep the laptop awake while the Pavilion runs: *Power -> Screen and sleep ->
   never* while plugged in.

This matters for the results. **If the laptop sleeps or leaves the Wi-Fi,
Ollama becomes unreachable, and the patient's preserved latent bug takes
over**: the embedder silently answers with hash vectors (DECISIONS.md D-0).
That is exactly fault f1's mechanism, happening without any commit. A
fallback-rate alert from the Pavilion should therefore be read with the
laptop's state in mind.

## 2. On the Pavilion

Follow *Setup from a fresh Ubuntu install* in the README. Then change `.env`
as follows:

```ini
OLLAMA_BASE_URL=http://<windows-laptop-LAN-IP>:11434
CONTAINER_OLLAMA_BASE_URL=http://<windows-laptop-LAN-IP>:11434
# Default host ports: delete the *_HOST_PORT lines and use the default *_URL values.
RUNTIME_DIR=/opt/aid/runtime
DEPLOY_LOG_PATH=/opt/aid/runtime/deploys.jsonl
DOCTOR_API_KEY=<GLM key>          # so the doctor reasons in the cloud, not on the laptop's GPU
```

Check that Ollama is reachable from a container, not just from the host:

```bash
docker run --rm curlimages/curl -s http://<windows-laptop-LAN-IP>:11434/api/version
```

The DVC remote endpoint is machine-specific and must be set once, locally:

```bash
dvc remote modify --local minio endpointurl http://127.0.0.1:9000
dvc remote modify --local minio access_key_id <MINIO_ROOT_USER>
dvc remote modify --local minio secret_access_key <MINIO_ROOT_PASSWORD>
```

Note the doctor's local context settings. On the laptop, `.env` sets
`DOCTOR_OLLAMA_NUM_CTX=4096` (with a smaller evidence budget) because the live
doctor had no cloud key, so it fell back to the patient's own model. A
different context size made Ollama reload the model on every switch, and one
normal chat took 35 s (DECISIONS.md). With a GLM key on the Pavilion, the
doctor uses Ollama only for `nomic-embed-text` embeddings. Put the defaults
back (`16384 / 6500 / 2500`) so live reports use the full evidence.

## 3. What behaves differently, and must be re-measured

Results measured on the laptop are labelled `pipeline: local` and "laptop".
Pavilion results must be reported **separately**, never merged into the same
table.

| Result | Why it changes on the Pavilion |
|---|---|
| **All timings**: chat and search latency, break -> alert, alert -> report, pipeline duration | Every Ollama call adds a Wi-Fi round trip. GitHub Actions adds runner pick-up time and fresh checkouts. The laptop had no network hop and ran everything on one machine. |
| **Alert thresholds** (`HighLatencyP95`: 40 s chat, 5 s search) | They were set to about 2.4x the healthy p95 measured on the laptop (chat 16.9 s, search 0.29 s). Measure the healthy p95 on the Pavilion under `faults.background_traffic` and set the thresholds again from those numbers. |
| **f1, the timeout regression** | Embedding time now includes Wi-Fi latency and jitter, so the 10 s timeout may trip without any noisy neighbour, or less often. The healthy 45 s value should still cover a contended cold load (43 s measured), but with less margin. |
| **f6, the tight 3 s timeout** | Its failure rate depends on time-to-first-token plus network latency. Expect a different share of failed chats. |
| **f4, the memory leak** (**must** be re-measured) | Docker Desktop runs containers inside a WSL2 VM. There, memory limits, page-cache accounting and the OOM killer act inside a VM with its own memory pressure, and the whole VM itself fell over twice on this laptop under load. On native Linux the cgroup v2 limits apply directly, and OOM kills and restart loops will happen at different times and in a different pattern. |
| **f2, capacity** | Generation still runs on the laptop's GPU, but requests now queue across the network. The surge needed to cross the latency threshold is different. |
| **cAdvisor** | On the laptop it could not see containers: Docker 29's containerd image store gave "failed to identify the read-write layer ID". On a native install using the overlay2 storage driver it may work. container-exporter supplies the same numbers either way. |
| **Resource figures in the model-comparison harness** | These are CPU/GPU/RAM samples of the machine running the harness. On the Pavilion that machine has no GPU, and Ollama runs elsewhere. |

What does **not** change: the recorded incidents (the evidence snapshots).
Replaying them with `python -m doctor.eval.run_eval` gives comparable
accuracy numbers on any machine that can reach a model. Only the *live* runs
are machine-specific.
