"""Service addresses and deployment settings for the patient (KnowledgeAI).

Every address the services use to reach each other, ChromaDB or Ollama is read
from the environment here and nowhere else. Nothing is hardcoded to localhost:
in Docker the services reach each other by container name, and on the Pavilion
Ollama lives on a different machine entirely.

For a local run outside Docker the values come from the repository's `.env`
file (see `.env.example`). A variable that is set in the real environment
always wins over the file.
"""

import os
from typing import Dict, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read_env_file(path: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


_FILE_VALUES = _read_env_file(os.environ.get("KNOWLEDGEAI_ENV_FILE", os.path.join(_REPO_ROOT, ".env")))


def setting(name: str, default: Optional[str] = None) -> Optional[str]:
    """Environment first, then the .env file, then the caller's default."""
    value = os.environ.get(name)
    if value is None or value == "":
        value = _FILE_VALUES.get(name)
    if value is None or value == "":
        return default
    return value


def required(name: str) -> str:
    value = setting(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Every service address is configuration - set it in "
            f"the environment or in .env (see .env.example)."
        )
    return value.rstrip("/")


def ollama_base_url() -> str:
    return required("OLLAMA_BASE_URL")


def service_url(name: str) -> str:
    """`service_url("retrieval")` -> value of RETRIEVAL_SERVICE_URL."""
    return required(f"{name.upper()}_SERVICE_URL")


SERVICE_NAME = setting("SERVICE_NAME", "knowledgeai")
GIT_SHA = setting("APP_GIT_SHA", "unknown")
