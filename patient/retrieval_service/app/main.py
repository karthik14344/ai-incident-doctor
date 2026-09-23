import os
import sys
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import config, telemetry

from ingestion_service.app.vector_store import query_vector_store

app = FastAPI(title="Retrieval Service", version="1.0.0")
log = telemetry.instrument(app, "retrieval")
telemetry.register_embedding_fallback("retrieval")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QueryRequest(BaseModel):
    question: str
    collection_name: str = "default"
    top_k: int = 4
    embedding_model: str = "nomic-embed-text"
    ollama_base_url: str = Field(default_factory=config.ollama_base_url)

# Sources keep a 150-character preview; the full chunk text stays in raw_chunks.
def assemble_context(chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Turn ranked chunks into the prompt context block and the source list.

    Lives outside the endpoint so the Week-4 evaluation harness can run the
    identical pipeline without the service being up. If this ever forks, the
    harness would be scoring a prompt the application never actually sends.
    """
    context_blocks = []
    sources = []

    for idx, c in enumerate(chunks):
        meta = c["metadata"]
        text = c["text"]
        sim = c["similarity"]

        block = f"[Source {idx+1}: {meta.get('filename', 'Doc')} - Page {meta.get('page_number', 1)} | Similarity: {sim}]\n{text}"
        context_blocks.append(block)

        sources.append({
            "filename": meta.get("filename", "Doc"),
            "page": meta.get("page_number", 1),
            "chunk_index": meta.get("chunk_index", 0),
            "similarity": sim,
            "text": text[:150] + "..." if len(text) > 150 else text
        })

    return {
        "assembled_context": "\n\n".join(context_blocks) if context_blocks else "No relevant document chunks found.",
        "sources": sources,
    }


# Recent retrievals, so a repeated question skips the embedding round-trip.
_RECENT: Dict[str, Dict[str, Any]] = {}


@app.post("/retrieve")
def retrieve_context(req: QueryRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    key = f"{req.collection_name}:{req.top_k}:{req.embedding_model}:{req.question.strip().lower()}"
    if key in _RECENT:
        return _RECENT[key]

    # 1. Embed query
    query_emb = telemetry.instrumented_embedding("retrieval", req.question, req.embedding_model, req.ollama_base_url)

    # 2. Similarity Search in ChromaDB
    chunks = query_vector_store(
        collection_name=req.collection_name,
        query_embedding=query_emb,
        top_k=req.top_k
    )

    telemetry.RETRIEVED_CHUNKS.labels("retrieval").observe(len(chunks))
    if not chunks:
        telemetry.ZERO_CHUNK_RETRIEVALS.labels("retrieval").inc()

    # 3. Assemble Context
    assembled = assemble_context(chunks)

    response = {
        "question": req.question,
        "query_embedding_dim": len(query_emb),
        "top_k": req.top_k,
        "results_count": len(chunks),
        "sources": assembled["sources"],
        "assembled_context": assembled["assembled_context"],
        "raw_chunks": chunks
    }
    _RECENT[key] = {**response, "query_embedding": list(query_emb)}
    return response

@app.get("/health")
def health():
    return {"service": "retrieval", "status": "online"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
