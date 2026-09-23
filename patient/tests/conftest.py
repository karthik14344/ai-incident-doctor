import os
import sys
import tempfile

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Point the gateway at a throwaway SQLite file before anything imports it, so
# tests never read or write the developer's real data/app.db.
import api_gateway.app.db as gateway_db  # noqa: E402

_TEST_DB_DIR = tempfile.mkdtemp(prefix="knowledgeai_tests_")
gateway_db.DB_PATH = os.path.join(_TEST_DB_DIR, "app.db")

from tests.fake_servers import (  # noqa: E402
    ThreadedServer,
    free_port,
    make_fake_hindi_tts,
    make_fake_vexyl_stt,
    make_wav,
)


@pytest.fixture(scope="session")
def sample_wav() -> bytes:
    return make_wav(seconds=1.0)


@pytest.fixture(scope="session")
def unused_port() -> int:
    """A port nothing is listening on, for testing unreachable-backend paths."""
    return free_port()


@pytest.fixture
def fake_vexyl():
    server = ThreadedServer(make_fake_vexyl_stt()).start()
    yield server
    server.stop()


@pytest.fixture
def fake_vexyl_with_key():
    server = ThreadedServer(make_fake_vexyl_stt(api_key="s3cret")).start()
    yield server
    server.stop()


@pytest.fixture
def fake_tts():
    server = ThreadedServer(make_fake_hindi_tts()).start()
    yield server
    server.stop()


@pytest.fixture
def fake_tts_base64():
    server = ThreadedServer(make_fake_hindi_tts(as_base64=True)).start()
    yield server
    server.stop()


@pytest.fixture
def voice_app():
    """The real voice service, with its env-var defaults neutralised.

    Each test passes the backend URLs it wants explicitly, so the service must
    not silently reach for a VEXYL-STT server on the developer's machine.
    """
    import voice_service.app.main as voice_main

    originals = (
        voice_main.DEFAULT_VEXYL_URL,
        voice_main.DEFAULT_VEXYL_API_KEY,
        voice_main.DEFAULT_TTS_URL,
        voice_main.DEFAULT_TTS_REF_AUDIO,
    )
    voice_main.DEFAULT_VEXYL_URL = ""
    voice_main.DEFAULT_VEXYL_API_KEY = ""
    voice_main.DEFAULT_TTS_URL = ""
    voice_main.DEFAULT_TTS_REF_AUDIO = ""

    yield voice_main.app

    (
        voice_main.DEFAULT_VEXYL_URL,
        voice_main.DEFAULT_VEXYL_API_KEY,
        voice_main.DEFAULT_TTS_URL,
        voice_main.DEFAULT_TTS_REF_AUDIO,
    ) = originals


@pytest.fixture
def voice_client(voice_app):
    from fastapi.testclient import TestClient

    with TestClient(voice_app) as client:
        yield client


@pytest.fixture
def voice_server(voice_app):
    server = ThreadedServer(voice_app).start()
    yield server
    server.stop()


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
