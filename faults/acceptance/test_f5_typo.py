"""Acceptance for f5: keyword-style questions (no '?') open a chat session."""


def test_a_keyword_query_starts_a_conversation(gateway_client):
    r = gateway_client.post("/api/chat", json={"question": "hostel curfew timings"})
    assert r.status_code == 200


def test_a_question_still_starts_a_conversation(gateway_client):
    r = gateway_client.post("/api/chat", json={"question": "What are the hostel curfew timings?"})
    assert r.status_code == 200
