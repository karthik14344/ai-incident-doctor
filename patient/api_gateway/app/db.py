import sqlite3
import os

from common import config

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "app.db")

def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Idempotent: CREATE TABLE IF NOT EXISTS and INSERT OR IGNORE for default settings.
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Documents table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id TEXT UNIQUE NOT NULL,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'uploaded',
        error_message TEXT,
        pages INTEGER DEFAULT 0,
        chunks_count INTEGER DEFAULT 0,
        collection_name TEXT DEFAULT 'default',
        created_at TEXT NOT NULL
    )
    """)
    
    # Document Chunks table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS document_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chunk_id TEXT UNIQUE NOT NULL,
        doc_id TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        page_number INTEGER NOT NULL,
        text TEXT NOT NULL,
        token_count INTEGER DEFAULT 0,
        embedding_dim INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
    )
    """)

    # Chat Sessions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    # Chat Messages table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        sources TEXT,
        pipeline_debug TEXT,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
    )
    """)

    # Model Comparison runs (Model Comparison page)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS model_comparisons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT UNIQUE NOT NULL,
        question TEXT NOT NULL,
        collection_name TEXT DEFAULT 'default',
        models TEXT NOT NULL,
        retrieval_ms REAL DEFAULT 0,
        retrieval_meta TEXT,
        results TEXT NOT NULL,
        summary TEXT,
        created_at TEXT NOT NULL
    )
    """)

    # Week-4 evaluation runs: the whole dataset through every model, scored.
    # The full report is a large JSON blob (per-question answers, metrics,
    # traces); the columns beside it exist so the run list can be rendered
    # without parsing it.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS evaluation_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT UNIQUE NOT NULL,
        models TEXT NOT NULL,
        dataset_size INTEGER NOT NULL,
        config TEXT,
        report TEXT NOT NULL,
        created_at TEXT NOT NULL,
        wall_seconds REAL DEFAULT 0
    )
    """)

    # App Settings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """)

    # Default settings
    default_settings = {
        "chunk_size": "800",
        "chunk_overlap": "100",
        "top_k": "4",
        "llm_model": "llama3.2",
        "embedding_model": "nomic-embed-text",
        "ollama_base_url": config.ollama_base_url(),
    }

    for key, val in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)", (key, val))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at:", DB_PATH)
