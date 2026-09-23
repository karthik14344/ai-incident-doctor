import os
import chromadb
from typing import List, Dict, Any

from common import config

# Local runs keep the original embedded store in chroma_data/. In compose the
# ingestion, retrieval and gateway containers share one ChromaDB server instead
# (CHROMA_HOST set): three processes opening the same on-disk store is unsafe.
CHROMA_DATA_DIR = config.setting(
    "CHROMA_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "chroma_data"),
)

# One HttpClient per server, reused. Creating a new chromadb.HttpClient per call
# leaks ~1.35 MB each (measured: 150 calls +203 MB, one reused client +0 MB);
# under ordinary traffic that OOM-killed the retrieval container within minutes.
_HTTP_CLIENTS = {}


def get_chroma_client():
    host = config.setting("CHROMA_HOST")
    if host:
        port = int(config.setting("CHROMA_PORT", "8000"))
        client = _HTTP_CLIENTS.get((host, port))
        if client is None:
            client = _HTTP_CLIENTS[(host, port)] = chromadb.HttpClient(host=host, port=port)
        return client
    os.makedirs(CHROMA_DATA_DIR, exist_ok=True)
    return chromadb.PersistentClient(path=CHROMA_DATA_DIR)

def get_or_create_collection(collection_name: str = "knowledge_base"):
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"}
    )

def add_chunks_to_vector_store(
    collection_name: str,
    chunks: List[Dict[str, Any]],
    embeddings: List[List[float]],
    doc_id: str,
    filename: str
):
    collection = get_or_create_collection(collection_name)
    
    ids = []
    documents = []
    metadatas = []

    for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        chunk_id = f"{doc_id}_c{chunk['chunk_index']}"
        ids.append(chunk_id)
        documents.append(chunk["text"])
        metadatas.append({
            "doc_id": doc_id,
            "filename": filename,
            "page_number": chunk["page_number"],
            "chunk_index": chunk["chunk_index"],
            "token_count": chunk["token_count"]
        })

    try:
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
    except Exception as e:
        print(f"[VectorStore Add Warning] Recreating collection due to dimension change ({e})")
        client = get_chroma_client()
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass
        collection = client.create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )

def query_vector_store(
    collection_name: str,
    query_embedding: List[float],
    top_k: int = 4
) -> List[Dict[str, Any]]:
    collection = get_or_create_collection(collection_name)
    
    count = collection.count()
    if count == 0:
        return []

    actual_k = min(top_k, count)
    
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=actual_k,
            include=["documents", "metadatas", "distances"]
        )
    except Exception as e:
        print(f"[VectorStore Query Warning] Dimension mismatch or query error ({e}). Attempting fallback vector match...")
        # Get peek items
        peek = collection.peek(limit=1)
        expected_dim = len(peek["embeddings"][0]) if peek and "embeddings" in peek and len(peek["embeddings"]) > 0 else len(query_embedding)
        
        # Adjust query embedding to expected dim
        adjusted_emb = query_embedding[:expected_dim] if len(query_embedding) > expected_dim else query_embedding + [0.0] * (expected_dim - len(query_embedding))
        results = collection.query(
            query_embeddings=[adjusted_emb],
            n_results=actual_k,
            include=["documents", "metadatas", "distances"]
        )

    formatted_results = []
    if results and "documents" in results and len(results["documents"]) > 0:
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0] if "distances" in results else [0.0] * len(docs)

        for doc, meta, dist in zip(docs, metas, dists):
            # Convert cosine distance to similarity score (0 to 1)
            similarity = max(0.0, min(1.0, 1.0 - float(dist)))
            formatted_results.append({
                "text": doc,
                "metadata": meta,
                "distance": float(dist),
                "similarity": round(similarity, 4)
            })

    return formatted_results

def delete_document_vectors(doc_id: str, collection_name: str = "knowledge_base"):
    try:
        collection = get_or_create_collection(collection_name)
        collection.delete(where={"doc_id": doc_id})
    except Exception as e:
        print(f"Error deleting vectors for {doc_id}: {e}")

def get_collection_chunks(collection_name: str, limit: int = 2000) -> List[Dict[str, Any]]:
    """Read stored chunk text/metadata from ChromaDB (no embedding query)."""
    client = get_chroma_client()
    try:
        collection = client.get_collection(name=collection_name)
    except Exception:
        return []

    try:
        count = collection.count()
    except Exception:
        return []
    if count == 0:
        return []

    results = collection.get(
        include=["documents", "metadatas"],
        limit=min(limit, count),
    )
    documents = results.get("documents") or []
    metadatas = results.get("metadatas") or []
    chunks = []
    for doc, meta in zip(documents, metadatas):
        chunks.append({
            "text": doc or "",
            "metadata": meta or {},
        })
    return chunks
