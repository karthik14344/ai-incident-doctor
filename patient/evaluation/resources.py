"""Exercise 3 - CPU / GPU / memory consumption around a single timed generation.

Ollama runs the model in its own process, so the interesting numbers are not in
this process at all. A background thread samples the machine and the Ollama
process group while a generation is in flight, and the run reports the mean
during generation plus the peak.

Two honest limitations, stated rather than hidden:

* CPU% and system RAM are machine-wide. Anything else running on the laptop
  lands in the numbers. Idle baselines are captured before each run and
  reported alongside, so a reader can subtract.
* GPU numbers come from `nvidia-smi`. Where it is missing (no NVIDIA GPU, or a
  CPU-only Ollama build) the GPU fields come back None rather than zero, so
  "not measured" never gets read as "used nothing".
"""

import shutil
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

try:
    import psutil
except ImportError:  # pragma: no cover - resources become unavailable, not fatal
    psutil = None

SAMPLE_INTERVAL_S = 0.2
#: nvidia-smi costs ~40 ms per call, so it is polled once every N CPU samples.
GPU_EVERY_N_SAMPLES = 3

_NVIDIA_SMI = shutil.which("nvidia-smi")


#: Process names that make up a local Ollama installation. `llama-server` is
#: the one that matters and the one that is easiest to miss: Ollama spawns a
#: separate runner per loaded model, and that child - not `ollama serve` - is
#: where the weights live. Matching only "ollama" reports the ~40 MB API stub
#: and calls it the model's memory footprint.
OLLAMA_PROCESS_HINTS = ("ollama", "llama-server", "ollama_llama_server", "llama_server")


def _ollama_processes() -> List[Any]:
    """Every process that makes up the local Ollama server, runner included."""
    if psutil is None:
        return []
    found = []
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if any(hint in name for hint in OLLAMA_PROCESS_HINTS):
                found.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def _read_gpu() -> Optional[Dict[str, float]]:
    """One nvidia-smi reading, or None when no NVIDIA GPU is visible."""
    if not _NVIDIA_SMI:
        return None
    try:
        out = subprocess.run(
            [_NVIDIA_SMI, "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        # Sum across GPUs; take the first line's total as the device size.
        util_sum = mem_sum = mem_total = 0.0
        lines = [l for l in out.stdout.strip().splitlines() if l.strip()]
        for line in lines:
            util, used, total = (p.strip() for p in line.split(","))
            util_sum += float(util)
            mem_sum += float(used)
            mem_total = max(mem_total, float(total))
        return {
            "util_pct": util_sum / len(lines),
            "mem_used_mb": mem_sum,
            "mem_total_mb": mem_total,
        }
    except Exception:
        return None


def gpu_available() -> bool:
    return _read_gpu() is not None


def baseline() -> Dict[str, Any]:
    """Idle reading taken before a run, so consumption can be read as a delta."""
    gpu = _read_gpu()
    snapshot: Dict[str, Any] = {
        "gpu_present": gpu is not None,
        "gpu_mem_used_mb": round(gpu["mem_used_mb"], 1) if gpu else None,
        "gpu_mem_total_mb": round(gpu["mem_total_mb"], 1) if gpu else None,
        "gpu_util_pct": round(gpu["util_pct"], 1) if gpu else None,
    }
    if psutil is not None:
        psutil.cpu_percent(interval=None)  # prime the delta counter
        time.sleep(0.15)
        mem = psutil.virtual_memory()
        snapshot.update({
            "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
            "cpu_logical_cores": psutil.cpu_count(logical=True),
            "system_ram_total_mb": round(mem.total / (1024 ** 2), 1),
            "system_ram_used_mb": round((mem.total - mem.available) / (1024 ** 2), 1),
            "ollama_rss_mb": round(
                sum(p.memory_info().rss for p in _ollama_processes()) / (1024 ** 2), 1
            ) if _ollama_processes() else None,
        })
    else:
        snapshot["psutil_available"] = False
    return snapshot


class ResourceSampler:
    """Context manager that samples the machine while the body runs.

    Usage::

        with ResourceSampler() as sampler:
            ...run one generation...
        stats = sampler.stats()
    """

    def __init__(self, interval_s: float = SAMPLE_INTERVAL_S):
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cpu: List[float] = []
        self._proc_rss: List[float] = []
        self._sys_ram: List[float] = []
        self._gpu_util: List[float] = []
        self._gpu_mem: List[float] = []
        self._started_at = 0.0
        self._samples = 0

    # -- lifecycle ------------------------------------------------------
    def __enter__(self) -> "ResourceSampler":
        self._started_at = time.perf_counter()
        if psutil is not None:
            psutil.cpu_percent(interval=None)  # prime, so the first sample is a real delta
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> bool:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        return False

    def _loop(self) -> None:
        procs = _ollama_processes()
        tick = 0
        while not self._stop.is_set():
            tick += 1
            self._samples += 1
            # Ollama can swap in a new runner mid-run when it loads a different
            # model, and a list captured once would then be tracking a dead PID.
            # Rescanning occasionally is cheap next to an LLM generation.
            if tick % 25 == 0:
                procs = _ollama_processes()
            if psutil is not None:
                try:
                    self._cpu.append(psutil.cpu_percent(interval=None))
                    mem = psutil.virtual_memory()
                    self._sys_ram.append((mem.total - mem.available) / (1024 ** 2))
                    rss = 0
                    for p in procs:
                        try:
                            rss += p.memory_info().rss
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                    if rss:
                        self._proc_rss.append(rss / (1024 ** 2))
                except Exception:
                    pass
            if tick % GPU_EVERY_N_SAMPLES == 1:
                gpu = _read_gpu()
                if gpu:
                    self._gpu_util.append(gpu["util_pct"])
                    self._gpu_mem.append(gpu["mem_used_mb"])
            self._stop.wait(self.interval_s)

    # -- results --------------------------------------------------------
    @staticmethod
    def _mean(values: List[float]) -> Optional[float]:
        return round(sum(values) / len(values), 1) if values else None

    @staticmethod
    def _peak(values: List[float]) -> Optional[float]:
        return round(max(values), 1) if values else None

    def stats(self) -> Dict[str, Any]:
        return {
            "samples": self._samples,
            "sampled_seconds": round(time.perf_counter() - self._started_at, 2),
            "cpu_percent_mean": self._mean(self._cpu),
            "cpu_percent_peak": self._peak(self._cpu),
            "process_rss_mean_mb": self._mean(self._proc_rss),
            "process_rss_peak_mb": self._peak(self._proc_rss),
            "system_ram_used_mean_mb": self._mean(self._sys_ram),
            "system_ram_used_peak_mb": self._peak(self._sys_ram),
            "gpu_util_mean_pct": self._mean(self._gpu_util),
            "gpu_util_peak_pct": self._peak(self._gpu_util),
            "gpu_mem_mean_mb": self._mean(self._gpu_mem),
            "gpu_mem_peak_mb": self._peak(self._gpu_mem),
            "gpu_measured": bool(self._gpu_mem),
            "psutil_available": psutil is not None,
        }
