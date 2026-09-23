"""Doctor configuration. Everything is read from the environment (then the repo
.env for runs on the host). No addresses are literals.

The doctor is a separate system from the patient and imports none of its code.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Optional

DOCTOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT_DEFAULT = os.path.dirname(DOCTOR_DIR)


def _env_file() -> Dict[str, str]:
    path = os.environ.get("DOCTOR_ENV_FILE", os.path.join(REPO_ROOT_DEFAULT, ".env"))
    values: Dict[str, str] = {}
    try:
        for raw in open(path, encoding="utf-8"):
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


_FILE = _env_file()


def get(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    if value in (None, ""):
        value = _FILE.get(name)
    return default if value in (None, "") else value


# Base URLs of the OpenAI-compatible endpoints. Overridable per provider with
# DOCTOR_BASE_URL (primary) / DOCTOR_FALLBACK_BASE_URL.
PROVIDER_BASE_URLS = {
    "glm": "https://api.z.ai/api/paas/v4",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
}

# USD per million tokens (input, output). Used only to report cost per
# incident; override with DOCTOR_PRICE_IN / DOCTOR_PRICE_OUT. Local models cost
# nothing in money. The GLM figure is the published glm-4.6 list price at the
# time of writing and is an assumption, not a measurement.
DEFAULT_PRICES = {
    "glm": (0.60, 2.20),
    "gemini": (0.30, 2.50),
    "groq": (0.59, 0.79),
    "openai": (1.25, 10.0),
    "ollama": (0.0, 0.0),
}


@dataclass
class ProviderConfig:
    provider: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    price_in: float = 0.0
    price_out: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


def provider_config(prefix: str = "DOCTOR") -> Optional[ProviderConfig]:
    """DOCTOR_PROVIDER/MODEL/API_KEY or DOCTOR_FALLBACK_PROVIDER/..."""
    provider = get(f"{prefix}_PROVIDER")
    model = get(f"{prefix}_MODEL")
    if not provider or not model:
        return None
    provider = provider.lower()
    base = get(f"{prefix}_BASE_URL") or (
        doctor_ollama_url() if provider == "ollama" else PROVIDER_BASE_URLS.get(provider))
    pin, pout = DEFAULT_PRICES.get(provider, (0.0, 0.0))
    return ProviderConfig(
        provider=provider, model=model, api_key=get(f"{prefix}_API_KEY"), base_url=base,
        price_in=float(get(f"{prefix}_PRICE_IN", str(pin))),
        price_out=float(get(f"{prefix}_PRICE_OUT", str(pout))),
    )


def doctor_ollama_url() -> Optional[str]:
    """Ollama for the doctor's own embeddings / local reasoning."""
    return (get("DOCTOR_OLLAMA_BASE_URL") or get("OLLAMA_BASE_URL") or "").rstrip("/") or None


@dataclass
class Settings:
    repo_root: str = field(default_factory=lambda: get("DOCTOR_REPO", REPO_ROOT_DEFAULT))
    data_dir: str = field(default_factory=lambda: get("DOCTOR_DATA_DIR", os.path.join(DOCTOR_DIR, "data")))
    prometheus_url: Optional[str] = field(default_factory=lambda: get("DOCTOR_PROMETHEUS_URL") or get("PROMETHEUS_URL"))
    loki_url: Optional[str] = field(default_factory=lambda: get("DOCTOR_LOKI_URL") or get("LOKI_URL"))
    alert_sink_url: Optional[str] = field(default_factory=lambda: get("DOCTOR_ALERT_SINK_URL") or get("ALERT_SINK_URL"))
    deploy_log_path: str = field(default_factory=lambda: get(
        "DOCTOR_DEPLOY_LOG", get("DEPLOY_LOG_PATH", os.path.join(REPO_ROOT_DEFAULT, "runtime", "deploys.jsonl"))))
    kb_load_log_path: str = field(default_factory=lambda: get(
        "DOCTOR_KB_LOAD_LOG", os.path.join(os.path.dirname(get(
            "DOCTOR_DEPLOY_LOG", get("DEPLOY_LOG_PATH", os.path.join(REPO_ROOT_DEFAULT, "runtime", "deploys.jsonl")))),
            "kb_loads.jsonl")))
    ignore_paths: tuple = field(default_factory=lambda: tuple(
        p.strip() for p in get("DOCTOR_IGNORE_PATHS", "faults/,incidents/,doctor/eval/,RESULTS.md").split(",")
        if p.strip()))
    embed_model: str = field(default_factory=lambda: get("DOCTOR_EMBED_MODEL", "nomic-embed-text"))
    # How far before the alert a deploy can be and still be a suspect.
    deploy_lookback_s: int = field(default_factory=lambda: int(get("DOCTOR_DEPLOY_LOOKBACK_S", str(6 * 3600))))
    # Evidence windows relative to the alert's startsAt.
    incident_before_s: int = field(default_factory=lambda: int(get("DOCTOR_INCIDENT_BEFORE_S", "600")))
    incident_after_s: int = field(default_factory=lambda: int(get("DOCTOR_INCIDENT_AFTER_S", "60")))
    baseline_s: int = field(default_factory=lambda: int(get("DOCTOR_BASELINE_S", "1800")))
    max_calls_per_run: int = field(default_factory=lambda: int(get("DOCTOR_MAX_CALLS_PER_RUN", "6")))
    max_prompt_tokens: int = field(default_factory=lambda: int(get("DOCTOR_MAX_PROMPT_TOKENS", "6500")))
    auto_diagnose: bool = field(default_factory=lambda: get("DOCTOR_AUTO_DIAGNOSE", "true").lower() == "true")

    @property
    def primary(self) -> Optional[ProviderConfig]:
        return provider_config("DOCTOR")

    @property
    def fallback(self) -> Optional[ProviderConfig]:
        return provider_config("DOCTOR_FALLBACK")


SETTINGS = Settings()
