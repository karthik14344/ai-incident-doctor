import os
import sys
import sqlite3
from datetime import datetime

# Add root directory to sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from api_gateway.app.db import init_db, get_db_connection
from ingestion_service.app.chunker import create_chunks
from ingestion_service.app.embedder import get_embedding
from ingestion_service.app.vector_store import add_chunks_to_vector_store
from evaluation.corpus import POLICY_CORPUS

init_db()

STORAGE_DIR = os.path.join(BASE_DIR, "storage", "documents")
os.makedirs(STORAGE_DIR, exist_ok=True)

# The corpus itself lives in evaluation/corpus.py, which is also what the Week-4
# evaluation reads. Two copies would drift, and a reworded policy line would
# silently invalidate every ground-truth label in evaluation/dataset.py.
SAMPLE_DOCUMENTS = POLICY_CORPUS

def seed():
    print("[*] Seeding sample knowledge base documents...")
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()

    for doc in SAMPLE_DOCUMENTS:
        doc_id = doc["doc_id"]
        filename = doc["filename"]
        file_path = os.path.join(STORAGE_DIR, filename)

        # Create sample document text file on disk
        full_text = "\n\n".join([p["text"] for p in doc["pages"]])
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(full_text)

        file_size = os.path.getsize(file_path)

        # Insert or update doc record
        cursor.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        cursor.execute("DELETE FROM document_chunks WHERE doc_id = ?", (doc_id,))

        # Create chunks
        chunks = create_chunks(doc["pages"], chunk_size=800, chunk_overlap=100)
        
        embeddings = []
        for chunk in chunks:
            emb = get_embedding(chunk["text"])
            embeddings.append(emb)
            chunk_id = f"{doc_id}_c{chunk['chunk_index']}"

            cursor.execute("""
                INSERT INTO document_chunks (chunk_id, doc_id, chunk_index, page_number, text, token_count, embedding_dim, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (chunk_id, doc_id, chunk['chunk_index'], chunk['page_number'], chunk['text'], chunk['token_count'], len(emb), now))

        # Vector store insertion
        add_chunks_to_vector_store("default", chunks, embeddings, doc_id, filename)

        cursor.execute("""
            INSERT INTO documents (doc_id, filename, file_path, file_size, status, pages, chunks_count, collection_name, created_at)
            VALUES (?, ?, ?, ?, 'processed', ?, ?, 'default', ?)
        """, (doc_id, filename, file_path, file_size, len(doc["pages"]), len(chunks), now))

    conn.commit()
    conn.close()
    print("[+] Knowledge base seeded successfully with sample documents & vector embeddings!")

if __name__ == "__main__":
    seed()
