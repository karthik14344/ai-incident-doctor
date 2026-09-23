import os
import sys
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import config, telemetry

from ingestion_service.app.pdf_processor import extract_text_from_pdf
from ingestion_service.app.chunker import create_chunks
from ingestion_service.app.vector_store import add_chunks_to_vector_store
from api_gateway.app.db import get_db_connection

app = FastAPI(title="Ingestion Service", version="1.0.0")
log = telemetry.instrument(app, "ingestion")
telemetry.register_embedding_fallback("ingestion")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ProcessRequest(BaseModel):
    doc_id: str
    file_path: str
    filename: str
    collection_name: str = "default"
    chunk_size: int = 800
    chunk_overlap: int = 100
    embedding_model: str = "nomic-embed-text"
    ollama_base_url: str = Field(default_factory=config.ollama_base_url)

def update_doc_status(doc_id: str, status: str, pages: int = 0, chunks_count: int = 0, error_message: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE documents 
        SET status = ?, pages = ?, chunks_count = ?, error_message = ? 
        WHERE doc_id = ?
    """, (status, pages, chunks_count, error_message, doc_id))
    conn.commit()
    conn.close()

def process_document_pipeline(req: ProcessRequest):
    try:
        # Step 1: Extract Text
        update_doc_status(req.doc_id, "extracting")
        pages_data = extract_text_from_pdf(req.file_path)
        total_pages = len(pages_data)

        # Step 2: Chunking
        update_doc_status(req.doc_id, "chunking", pages=total_pages)
        chunks = create_chunks(pages_data, chunk_size=req.chunk_size, chunk_overlap=req.chunk_overlap)

        # Step 3: Embeddings
        update_doc_status(req.doc_id, "embedding", pages=total_pages, chunks_count=len(chunks))
        embeddings = []
        
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()

        # Clear old chunks for doc if reprocessing
        cursor.execute("DELETE FROM document_chunks WHERE doc_id = ?", (req.doc_id,))

        for chunk in chunks:
            emb = telemetry.instrumented_embedding("ingestion", chunk["text"], req.embedding_model, req.ollama_base_url)
            embeddings.append(emb)
            chunk_id = f"{req.doc_id}_c{chunk['chunk_index']}"

            cursor.execute("""
                INSERT INTO document_chunks (chunk_id, doc_id, chunk_index, page_number, text, token_count, embedding_dim, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (chunk_id, req.doc_id, chunk['chunk_index'], chunk['page_number'], chunk['text'], chunk['token_count'], len(emb), now))

        conn.commit()
        conn.close()

        # Step 4: Vector Store (ChromaDB)
        add_chunks_to_vector_store(
            collection_name=req.collection_name,
            chunks=chunks,
            embeddings=embeddings,
            doc_id=req.doc_id,
            filename=req.filename
        )

        # Step 5: Mark Processed
        update_doc_status(req.doc_id, "processed", pages=total_pages, chunks_count=len(chunks))

    except Exception as e:
        log.error("document processing failed", exc=e, doc_id=req.doc_id)
        update_doc_status(req.doc_id, "error", error_message=str(e))

@app.post("/process")
async def process_document(req: ProcessRequest):
    # Run pipeline synchronously or via background task
    process_document_pipeline(req)
    return {"status": "success", "doc_id": req.doc_id}

@app.get("/health")
def health():
    return {"service": "ingestion", "status": "online"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
