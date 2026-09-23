"""Acceptance for f1: the embedding timeout is generous enough for a cold model."""


def test_embedding_timeout_covers_a_cold_or_contended_model():
    from ingestion_service.app import embedder

    # A contended cold load of nomic-embed-text was measured at 43 s.
    assert embedder.EMBED_TIMEOUT_S >= 30
