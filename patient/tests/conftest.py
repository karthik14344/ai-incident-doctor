import os
import sys
import tempfile

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Service addresses are configuration. Tests pin them explicitly so they never
# depend on a developer's .env; nothing is listening on these addresses.
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("INGESTION_SERVICE_URL", "http://127.0.0.1:18001")
os.environ.setdefault("RETRIEVAL_SERVICE_URL", "http://127.0.0.1:18002")
os.environ.setdefault("LLM_SERVICE_URL", "http://127.0.0.1:18003")

# Point the gateway at a throwaway SQLite file before anything imports it, so
# tests never read or write the developer's real data/app.db.
import api_gateway.app.db as gateway_db  # noqa: E402

_TEST_DB_DIR = tempfile.mkdtemp(prefix="knowledgeai_tests_")
gateway_db.DB_PATH = os.path.join(_TEST_DB_DIR, "app.db")

from tests.fake_servers import free_port  # noqa: E402


@pytest.fixture(scope="session")
def unused_port() -> int:
    """A port nothing is listening on, for testing unreachable-backend paths."""
    return free_port()


@pytest.fixture
def gateway_client():
    """TestClient for the API gateway, backed by the throwaway database."""
    from fastapi.testclient import TestClient

    import api_gateway.app.main as gateway_main

    with TestClient(gateway_main.app) as client:
        yield client


@pytest.fixture
def gateway_module():
    import api_gateway.app.main as gateway_main

    return gateway_main
