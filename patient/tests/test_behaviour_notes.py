"""Small behaviour notes, written down as tests while reading the code."""


def test_long_pages_are_split_with_overlap():
    from ingestion_service.app.chunker import create_chunks

    chunks = create_chunks([{"page": 1, "text": "x" * 2000}], chunk_size=800, chunk_overlap=100)
    assert [c["chunk_index"] for c in chunks] == [1, 2, 3]
    assert all(c["page_number"] == 1 for c in chunks)


def test_empty_pages_produce_no_chunks():
    from ingestion_service.app.chunker import create_chunks

    assert create_chunks([{"page": 1, "text": ""}, {"page": 2, "text": ""}]) == []
