"""Build the versioned knowledge base: source documents + ChromaDB index.

This is the `build_kb` stage in dvc.yaml. It produces, under `kb/` at the
repository root:

    kb/documents/      the policy documents, as the seed script writes them
    kb/index/          a ChromaDB store holding the "default" collection (what
                       chat answers from) and "eval_kb" (what the evaluation
                       harness scores against)
    kb/records.json    the SQLite rows the Documents page lists
    kb/manifest.json   the knowledge-base version and what went into it

The chunking and embedding code is the application's own (seed_sample_docs.py
and evaluation/prepare_kb.py), so the index is exactly what the app would have
built. The kb-loader container copies it into the ChromaDB volume at deploy
time, and `kb_version` from the manifest is recorded in every deploy record -
that is how "which knowledge base is live" is answered.

The build fails if the embedder's silent hash fallback fired even once: an
index built from fallback vectors looks complete and answers nothing correctly.
(The fallback itself is a preserved latent bug in the app - DECISIONS.md D-0 -
this script only refuses to publish its output.)

Run:  python patient/kb/build_kb.py            (Ollama must be reachable)
"""

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

PATIENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(PATIENT_DIR)
KB_DIR = os.path.join(REPO_ROOT, "kb")
INDEX_DIR = os.path.join(KB_DIR, "index")
DOCS_DIR = os.path.join(KB_DIR, "documents")

# The index must be built into kb/index with the embedded client, never into a
# running ChromaDB server. Set before the vector store module is imported.
os.environ["CHROMA_DATA_DIR"] = INDEX_DIR
os.environ["CHROMA_HOST"] = ""
sys.path.insert(0, PATIENT_DIR)

from common import config  # noqa: E402
from evaluation import prepare_kb  # noqa: E402
from evaluation.corpus import EVAL_COLLECTION, POLICY_CORPUS  # noqa: E402
from ingestion_service.app.chunker import create_chunks  # noqa: E402
from ingestion_service.app.embedder import embedding_fallback_count, get_embedding  # noqa: E402
from ingestion_service.app.vector_store import add_chunks_to_vector_store  # noqa: E402

CHAT_COLLECTION = "default"
EMBEDDING_MODEL = "nomic-embed-text"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def kb_version() -> str:
    """Content hash of everything that determines the index."""
    h = hashlib.sha256()
    h.update(f"{EMBEDDING_MODEL}|{CHUNK_SIZE}|{CHUNK_OVERLAP}".encode())
    for doc in POLICY_CORPUS:
        h.update(doc["doc_id"].encode())
        for page in doc["pages"]:
            h.update(page["text"].encode("utf-8"))
    return h.hexdigest()[:12]


def build() -> dict:
    ollama = config.ollama_base_url()
    for path in (INDEX_DIR, DOCS_DIR):
        shutil.rmtree(path, ignore_errors=True)
    os.makedirs(DOCS_DIR, exist_ok=True)

    fallback_before = embedding_fallback_count()
    now = datetime.now(timezone.utc).isoformat()
    documents, chunk_rows = [], []

    # "default" collection - identical to seed_sample_docs.seed()
    for doc in POLICY_CORPUS:
        file_path = os.path.join(DOCS_DIR, doc["filename"])
        with open(file_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n\n".join(p["text"] for p in doc["pages"]))
        chunks = create_chunks(doc["pages"], chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        embeddings = [get_embedding(c["text"], model=EMBEDDING_MODEL, base_url=ollama) for c in chunks]
        add_chunks_to_vector_store(CHAT_COLLECTION, chunks, embeddings, doc["doc_id"], doc["filename"])
        documents.append({
            "doc_id": doc["doc_id"], "filename": doc["filename"],
            "file_path": f"/app/storage/documents/{doc['filename']}",
            "file_size": os.path.getsize(file_path), "status": "processed",
            "pages": len(doc["pages"]), "chunks_count": len(chunks),
            "collection_name": CHAT_COLLECTION, "created_at": now,
        })
        for c, emb in zip(chunks, embeddings):
            chunk_rows.append({
                "chunk_id": f"{doc['doc_id']}_c{c['chunk_index']}", "doc_id": doc["doc_id"],
                "chunk_index": c["chunk_index"], "page_number": c["page_number"],
                "text": c["text"], "token_count": c["token_count"],
                "embedding_dim": len(emb), "created_at": now,
            })

    # "eval_kb" collection - the evaluation harness's own builder, unchanged
    eval_result = prepare_kb.build(EVAL_COLLECTION, embedding_model=EMBEDDING_MODEL, ollama_base_url=ollama)

    fallbacks = embedding_fallback_count() - fallback_before
    if fallbacks:
        raise SystemExit(
            f"[build_kb] {fallbacks} embeddings came from the hash fallback (Ollama at {ollama} "
            f"unreachable or too slow). Refusing to publish a knowledge base built from noise.")

    manifest = {
        "kb_version": kb_version(),
        "built_at": now,
        "embedding_model": EMBEDDING_MODEL,
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "collections": {
            CHAT_COLLECTION: {"documents": len(documents), "chunks": len(chunk_rows)},
            EVAL_COLLECTION: {"documents": len(eval_result["documents"]),
                              "chunks": eval_result["total_chunks"]},
        },
        "documents": sorted(d["filename"] for d in documents),
        "embedding_fallbacks_during_build": fallbacks,
    }
    with open(os.path.join(KB_DIR, "records.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"documents": documents, "chunks": chunk_rows}, fh, indent=1)
    with open(os.path.join(KB_DIR, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


if __name__ == "__main__":
    result = build()
    print(json.dumps(result, indent=2))
