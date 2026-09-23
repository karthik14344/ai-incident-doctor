"""Builds the evaluation knowledge base - the same Week-3 corpus, one copy each.

Why not just point the evaluation at the live `default` collection: it has
accumulated several re-uploads of the same PDFs (`attendance_policy.pdf` sits
alongside `doc_da1629aee6_attendance_policy.pdf` and
`doc_000809683d_doc_da1629aee6_attendance_policy.pdf`). With duplicates in the
index, precision@k is capped by how many copies of the right page exist rather
than by how well retrieval works, and the top-k budget is spent re-reading the
same paragraph. Both would make the retrieval-quality metric meaningless.

`eval_kb` holds exactly the documents Week 3 shipped, chunked with the same
chunker at the same settings, with real page numbers - so a gold label of
("attendance_policy.pdf", 2) can be checked.

Run directly to (re)build it::

    python -m evaluation.prepare_kb
"""

import os
import sys
from typing import Any, Dict, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ingestion_service.app.chunker import create_chunks
from common import config
from ingestion_service.app.embedder import get_embedding
from ingestion_service.app.vector_store import (
    add_chunks_to_vector_store, get_chroma_client, get_or_create_collection,
)

from evaluation.corpus import EVAL_COLLECTION, POLICY_CORPUS

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def collection_status(collection_name: str = EVAL_COLLECTION) -> Dict[str, Any]:
    """What is currently indexed, per (filename, page)."""
    try:
        collection = get_or_create_collection(collection_name)
        count = collection.count()
        if not count:
            return {"collection": collection_name, "chunks": 0, "documents": [], "ready": False}
        stored = collection.get(include=["metadatas"])
        pages: Dict[str, Any] = {}
        for meta in stored["metadatas"]:
            key = f"{meta.get('filename')} p{meta.get('page_number')}"
            pages[key] = pages.get(key, 0) + 1
        expected = sum(len(d["pages"]) for d in POLICY_CORPUS)
        return {
            "collection": collection_name,
            "chunks": count,
            "documents": sorted({m.get("filename") for m in stored["metadatas"]}),
            "pages_indexed": dict(sorted(pages.items())),
            "expected_pages": expected,
            "ready": len(pages) >= expected,
        }
    except Exception as e:
        return {"collection": collection_name, "chunks": 0, "documents": [],
                "ready": False, "error": str(e)}


def build(collection_name: str = EVAL_COLLECTION,
          embedding_model: str = "nomic-embed-text",
          ollama_base_url: Optional[str] = None) -> Dict[str, Any]:
    """Drop and rebuild the evaluation collection from POLICY_CORPUS."""
    ollama_base_url = ollama_base_url or config.ollama_base_url()
    client = get_chroma_client()
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass  # first run, or already gone

    total_chunks = 0
    per_document = []

    for doc in POLICY_CORPUS:
        chunks = create_chunks(doc["pages"], chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        embeddings = [get_embedding(c["text"], model=embedding_model,
                                    base_url=ollama_base_url) for c in chunks]
        add_chunks_to_vector_store(collection_name, chunks, embeddings,
                                   doc["doc_id"], doc["filename"])
        total_chunks += len(chunks)
        per_document.append({
            "filename": doc["filename"],
            "pages": len(doc["pages"]),
            "chunks": len(chunks),
            "embedding_dim": len(embeddings[0]) if embeddings else 0,
        })

    return {
        "collection": collection_name,
        "documents": per_document,
        "total_chunks": total_chunks,
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "embedding_model": embedding_model,
    }


def ensure(collection_name: str = EVAL_COLLECTION, **kwargs) -> Dict[str, Any]:
    """Build only if the collection is missing or incomplete."""
    status = collection_status(collection_name)
    if status.get("ready"):
        return {"built": False, "status": status}
    return {"built": True, "result": build(collection_name, **kwargs),
            "status": collection_status(collection_name)}


if __name__ == "__main__":
    print(f"[*] Building evaluation knowledge base '{EVAL_COLLECTION}'...")
    result = build()
    for doc in result["documents"]:
        print(f"    {doc['filename']:<26} {doc['pages']} pages -> {doc['chunks']} chunks "
              f"({doc['embedding_dim']}-dim)")
    print(f"[+] {result['total_chunks']} chunks indexed in '{result['collection']}'.")
