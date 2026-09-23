"""Regression tests for the endpoints that existed before voice was added."""

LEGACY_SETTINGS = {
    "chunk_size": "800",
    "chunk_overlap": "100",
    "top_k": "4",
    "llm_model": "llama3.2",
    "embedding_model": "nomic-embed-text",
    "ollama_base_url": "http://localhost:11434",
}

LEGACY_STATUS_KEYS = {"gateway", "ingestion", "retrieval", "llm_service", "ollama", "ollama_models"}


def test_health_still_reports_the_gateway_online(gateway_client):
    body = gateway_client.get("/api/health").json()
    assert body["gateway"] == "online"
    assert "timestamp" in body


def test_system_status_keeps_its_original_keys_and_adds_voice(gateway_client):
    body = gateway_client.get("/api/system/status").json()

    assert LEGACY_STATUS_KEYS <= set(body)
    assert "voice" in body
    assert body["gateway"] == "online"


def test_settings_expose_the_original_keys(gateway_client):
    body = gateway_client.get("/api/settings").json()

    for key, value in LEGACY_SETTINGS.items():
        assert body[key] == value


def test_settings_expose_the_voice_defaults(gateway_client):
    body = gateway_client.get("/api/settings").json()

    assert body["voice_input_enabled"] == "true"
    assert body["voice_output_enabled"] == "false"
    assert body["stt_language"] == "hi-IN"
    assert body["vexyl_stt_url"] == "http://localhost:8091"
    assert body["vexyl_stt_api_key"] == ""


def test_saving_legacy_settings_does_not_clobber_voice_settings(gateway_client):
    """An older client posting only the six original fields must be harmless.

    Before the voice fields were optional this wrote the string "None" over
    every voice setting.
    """
    gateway_client.post(
        "/api/settings",
        json={**LEGACY_SETTINGS, "vexyl_stt_url": "http://example.test:9000"},
    )

    response = gateway_client.post("/api/settings", json=LEGACY_SETTINGS)
    assert response.status_code == 200

    body = gateway_client.get("/api/settings").json()
    assert body["vexyl_stt_url"] == "http://example.test:9000"
    assert body["stt_language"] == "hi-IN"
    assert "None" not in body.values()

    gateway_client.post(
        "/api/settings",
        json={**LEGACY_SETTINGS, "vexyl_stt_url": "http://localhost:8091"},
    )


def test_saving_settings_round_trips_changed_values(gateway_client):
    gateway_client.post(
        "/api/settings",
        json={**LEGACY_SETTINGS, "top_k": "7", "stt_language": "ml-IN"},
    )

    body = gateway_client.get("/api/settings").json()
    assert body["top_k"] == "7"
    assert body["stt_language"] == "ml-IN"

    gateway_client.post("/api/settings", json={**LEGACY_SETTINGS, "stt_language": "hi-IN"})


def test_documents_listing_still_works(gateway_client):
    response = gateway_client.get("/api/documents")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_upload_still_rejects_unsupported_file_types(gateway_client):
    response = gateway_client.post(
        "/api/documents/upload",
        files={"file": ("notes.exe", b"binary", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_missing_document_still_returns_404(gateway_client):
    assert gateway_client.get("/api/documents/doc_does_not_exist").status_code == 404


def test_chat_sessions_create_list_and_delete(gateway_client):
    created = gateway_client.post(
        "/api/chat/sessions", json={"title": "Regression session"}
    ).json()
    assert created["title"] == "Regression session"

    sessions = gateway_client.get("/api/chat/sessions").json()
    assert any(s["id"] == created["id"] for s in sessions)

    assert gateway_client.get(f"/api/chat/history/{created['id']}").json() == []

    deleted = gateway_client.delete(f"/api/chat/sessions/{created['id']}").json()
    assert deleted["status"] == "deleted"

    sessions = gateway_client.get("/api/chat/sessions").json()
    assert not any(s["id"] == created["id"] for s in sessions)


def test_all_original_routes_are_still_registered(gateway_module):
    paths = {route.path for route in gateway_module.app.routes}

    expected = {
        "/api/health",
        "/api/system/status",
        "/api/documents",
        "/api/documents/upload",
        "/api/documents/{doc_id}",
        "/api/documents/{doc_id}/chunks",
        "/api/documents/{doc_id}/reprocess",
        "/api/retrieval/search",
        "/api/chat",
        "/api/chat/sessions",
        "/api/chat/sessions/{session_id}",
        "/api/chat/history/{session_id}",
        "/api/settings",
    }
    assert expected <= paths
