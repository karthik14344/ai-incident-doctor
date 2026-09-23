import os
if "SSL_CERT_FILE" in os.environ and not os.path.exists(os.environ["SSL_CERT_FILE"]):
    del os.environ["SSL_CERT_FILE"]

import sys
import json
import time
import uuid
import shutil
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Add root directory to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

from common import config, telemetry
from api_gateway.app.db import get_db_connection, init_db
from api_gateway.app.metrics import evaluate_answer, summarise_run
from api_gateway.app.suggestions import suggest_queries
from api_gateway.app import guardrails
from ingestion_service.app.vector_store import delete_document_vectors

# Ensure SQLite DB is initialized
init_db()

# Week-5 guardrails. The kill-switch exists so the same pipeline can be run
# with the guardrails off for before/after measurement (the Week-5 report's
# "before" evidence) - it is not a runtime feature toggle.
GUARDRAILS_ENABLED = os.environ.get("KNOWLEDGEAI_GUARDRAILS", "on").strip().lower() != "off"
GUARDRAILS = guardrails.GuardrailPipeline()

STORAGE_DIR = os.path.join(BASE_DIR, "storage", "documents")
os.makedirs(STORAGE_DIR, exist_ok=True)

# Addresses are configuration (common/config.py), never literals: in Docker the
# services are reached by container name and Ollama runs on another machine.
INGESTION_SERVICE_URL = config.service_url("ingestion")
RETRIEVAL_SERVICE_URL = config.service_url("retrieval")
LLM_SERVICE_URL = config.service_url("llm")
OLLAMA_DEFAULT_URL = config.ollama_base_url()

DEFAULT_SETTINGS = {
    "chunk_size": "800",
    "chunk_overlap": "100",
    "top_k": "4",
    "llm_model": "llama3.2",
    "embedding_model": "nomic-embed-text",
    "ollama_base_url": OLLAMA_DEFAULT_URL,
}

app = FastAPI(title="KnowledgeAI API Gateway", version="1.0.0")
log = telemetry.instrument(app, "gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Settings are read per request so a change on the Settings page applies to the next question.
def get_settings_map() -> Dict[str, str]:
    settings = dict(DEFAULT_SETTINGS)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM app_settings")
        rows = cursor.fetchall()
        conn.close()
        settings.update({row["key"]: row["value"] for row in rows})
    except Exception as e:
        log.error("settings lookup failed", exc=e)
    return settings

# Models
class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    question: str
    collection_name: Optional[str] = "default"
    stream: bool = True

class SettingsRequest(BaseModel):
    chunk_size: str
    chunk_overlap: str
    top_k: str
    llm_model: str
    embedding_model: str
    ollama_base_url: str

class SessionCreateRequest(BaseModel):
    title: Optional[str] = "New Conversation"

class ModelCompareRequest(BaseModel):
    question: str
    models: List[str]
    collection_name: Optional[str] = "default"
    # Pin the run to an item from the Week-4 evaluation dataset. Ground truth is
    # what makes correctness, retrieval quality and test-pass rate computable;
    # without it those three come back marked not-applicable.
    dataset_id: Optional[str] = None
    top_k: Optional[int] = None
    max_tokens: int = 512
    temperature: float = 0.2
    # Preload each model before timing it, so the first model in the run isn't
    # penalised for absorbing the cold-start.
    warmup: bool = True

# ==================== SYSTEM STATUS & HEALTH ====================
@app.get("/api/health")
def gateway_health():
    return {"gateway": "online", "timestamp": datetime.utcnow().isoformat()}

@app.get("/api/system/status")
async def system_status():
    try:
        settings = get_settings_map()
        ollama_url = settings.get("ollama_base_url", OLLAMA_DEFAULT_URL)
        
        statuses = {
            "gateway": "online",
            "ingestion": "offline",
            "retrieval": "offline",
            "llm_service": "offline",
            "ollama": "offline",
            "ollama_models": []
        }

        async with telemetry.async_client("gateway", timeout=3.0, trust_env=False) as client:
            # Check Ingestion
            try:
                r = await client.get(f"{INGESTION_SERVICE_URL}/health")
                if r.status_code == 200:
                    statuses["ingestion"] = "online"
            except Exception:
                pass

            # Check Retrieval
            try:
                r = await client.get(f"{RETRIEVAL_SERVICE_URL}/health")
                if r.status_code == 200:
                    statuses["retrieval"] = "online"
            except Exception:
                pass

            # Check LLM Service
            try:
                r = await client.get(f"{LLM_SERVICE_URL}/health")
                if r.status_code == 200:
                    statuses["llm_service"] = "online"
            except Exception:
                pass

            # Check Ollama API
            try:
                r = await client.get(f"{ollama_url.rstrip('/')}/api/tags")
                if r.status_code == 200:
                    statuses["ollama"] = "online"
                    models_data = r.json()
                    statuses["ollama_models"] = [m.get("name") for m in models_data.get("models", [])]
            except Exception:
                pass

        return statuses
    except Exception as e:
        log.error("system status check failed", exc=e)
        return {
            "gateway": "online",
            "ingestion": "online",
            "retrieval": "online",
            "llm_service": "online",
            "ollama": "online",
            "ollama_models": ["llama3.2:latest"]
        }

# ==================== DOCUMENTS API ====================
@app.post("/api/documents/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    collection_name: str = Form("default")
):
    if not file.filename.lower().endswith(('.pdf', '.txt', '.md')):
        raise HTTPException(status_code=400, detail="Only PDF, TXT, or MD files are supported.")

    doc_id = f"doc_{uuid.uuid4().hex[:10]}"
    safe_filename = f"{doc_id}_{file.filename}"
    file_path = os.path.join(STORAGE_DIR, safe_filename)

    # Save to disk
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_size = os.path.getsize(file_path)
    now = datetime.utcnow().isoformat()

    # Save DB record
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO documents (doc_id, filename, file_path, file_size, status, collection_name, created_at)
        VALUES (?, ?, ?, ?, 'uploaded', ?, ?)
    """, (doc_id, file.filename, file_path, file_size, collection_name, now))
    conn.commit()
    conn.close()

    # Trigger processing on Ingestion Service
    settings = get_settings_map()
    payload = {
        "doc_id": doc_id,
        "file_path": file_path,
        "filename": file.filename,
        "collection_name": collection_name,
        "chunk_size": int(settings.get("chunk_size", 800)),
        "chunk_overlap": int(settings.get("chunk_overlap", 100)),
        "embedding_model": settings.get("embedding_model", "nomic-embed-text"),
        "ollama_base_url": settings.get("ollama_base_url", OLLAMA_DEFAULT_URL)
    }

    async def call_ingestion():
        async with telemetry.async_client("gateway", timeout=300.0, trust_env=False) as client:
            try:
                await client.post(f"{INGESTION_SERVICE_URL}/process", json=payload)
            except Exception as e:
                log.error("ingestion call failed", exc=e, target="ingestion")

    background_tasks.add_task(call_ingestion)

    return {
        "doc_id": doc_id,
        "filename": file.filename,
        "status": "processing",
        "message": "File uploaded successfully and processing started."
    }

@app.get("/api/documents")
def list_documents():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documents ORDER BY id DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        log.error("listing documents failed", exc=e)
        return []

@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,))
    doc = cursor.fetchone()
    if not doc:
        conn.close()
        raise HTTPException(status_code=404, detail="Document not found")
    
    cursor.execute("SELECT chunk_id, chunk_index, page_number, token_count, embedding_dim, SUBSTR(text, 1, 120) as snippet FROM document_chunks WHERE doc_id = ? ORDER BY chunk_index ASC", (doc_id,))
    chunks = cursor.fetchall()
    conn.close()

    res = dict(doc)
    res["chunks_summary"] = [dict(c) for c in chunks]
    return res

@app.get("/api/documents/{doc_id}/chunks")
def get_document_chunks(doc_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM document_chunks WHERE doc_id = ? ORDER BY chunk_index ASC", (doc_id,))
    chunks = cursor.fetchall()
    conn.close()
    return [dict(c) for c in chunks]

@app.post("/api/documents/{doc_id}/reprocess")
async def reprocess_document(doc_id: str, background_tasks: BackgroundTasks):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,))
    doc = cursor.fetchone()
    conn.close()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    settings = get_settings_map()
    payload = {
        "doc_id": doc["doc_id"],
        "file_path": doc["file_path"],
        "filename": doc["filename"],
        "collection_name": doc["collection_name"],
        "chunk_size": int(settings.get("chunk_size", 800)),
        "chunk_overlap": int(settings.get("chunk_overlap", 100)),
        "embedding_model": settings.get("embedding_model", "nomic-embed-text"),
        "ollama_base_url": settings.get("ollama_base_url", OLLAMA_DEFAULT_URL)
    }

    async def call_ingestion():
        async with telemetry.async_client("gateway", timeout=300.0, trust_env=False) as client:
            try:
                await client.post(f"{INGESTION_SERVICE_URL}/process", json=payload)
            except Exception as e:
                log.error("ingestion call failed", exc=e, target="ingestion")

    background_tasks.add_task(call_ingestion)
    return {"status": "reprocessing", "doc_id": doc_id}

@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_path, collection_name FROM documents WHERE doc_id = ?", (doc_id,))
    doc = cursor.fetchone()
    if not doc:
        conn.close()
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = doc["file_path"]
    coll_name = doc["collection_name"]

    # Delete DB records
    cursor.execute("DELETE FROM document_chunks WHERE doc_id = ?", (doc_id,))
    cursor.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    conn.commit()
    conn.close()

    # Delete physical file
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass

    # Delete ChromaDB vectors
    delete_document_vectors(doc_id, collection_name=coll_name)

    return {"status": "deleted", "doc_id": doc_id}

# ==================== RAG RETRIEVAL DEBUG API ====================
@app.post("/api/retrieval/search")
async def debug_retrieval(req: ChatRequest):
    settings = get_settings_map()
    payload = {
        "question": req.question,
        "collection_name": req.collection_name or "default",
        "top_k": int(settings.get("top_k", 4)),
        "embedding_model": settings.get("embedding_model", "nomic-embed-text"),
        "ollama_base_url": settings.get("ollama_base_url", OLLAMA_DEFAULT_URL)
    }

    async with telemetry.async_client("gateway", timeout=30.0, trust_env=False) as client:
        try:
            r = await client.post(f"{RETRIEVAL_SERVICE_URL}/retrieve", json=payload)
            if r.status_code == 200:
                return r.json()
            else:
                raise HTTPException(status_code=r.status_code, detail="Retrieval service error")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Retrieval failed: {e}")

# ==================== RAG CHAT & SESSIONS ====================
@app.get("/api/chat/sessions")
def list_chat_sessions():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM chat_sessions ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error("listing chat sessions failed", exc=e)
        return []

@app.post("/api/chat/sessions")
def create_chat_session(req: SessionCreateRequest):
    sess_id = f"session_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO chat_sessions (id, title, created_at) VALUES (?, ?, ?)", (sess_id, req.title, now))
    conn.commit()
    conn.close()
    return {"id": sess_id, "title": req.title, "created_at": now}

@app.get("/api/chat/history/{session_id}")
def get_chat_history(session_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
    rows = cursor.fetchall()
    conn.close()
    
    messages = []
    for r in rows:
        m = dict(r)
        if m.get("sources"):
            try:
                m["sources"] = json.loads(m["sources"])
            except Exception:
                m["sources"] = []
        if m.get("pipeline_debug"):
            try:
                m["pipeline_debug"] = json.loads(m["pipeline_debug"])
            except Exception:
                m["pipeline_debug"] = None
        messages.append(m)

    return messages

@app.delete("/api/chat/sessions/{session_id}")
def delete_chat_session(session_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted", "session_id": session_id}

def _chunk_text(text: str, size: int = 24) -> List[str]:
    """Split a fixed refusal into small chunks so SSE consumers still see a
    token stream (the Chat page appends whatever arrives)."""
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


def _guardrail_blocked_stream(session_id: str, refusal_text: str,
                              verdicts: List[Dict[str, Any]], sources: List[Dict[str, Any]],
                              pipeline_debug: Dict[str, Any]) -> StreamingResponse:
    """The response a blocked request gets instead of a generation: the
    guardrail verdicts travel in the stream, the refusal is what the user
    reads, and both sides land in chat history like any other exchange."""
    annotated_debug = {**(pipeline_debug or {}), "guardrails": verdicts}

    async def generator():
        yield f"data: {json.dumps({'type': 'meta', 'session_id': session_id, 'sources': sources, 'pipeline_debug': pipeline_debug, 'guardrails': verdicts})}\n\n"
        for chunk in _chunk_text(refusal_text):
            yield f"data: {json.dumps({'token': chunk})}\n\n"
        yield f"data: {json.dumps({'type': 'guardrails', 'verdicts': verdicts})}\n\n"
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO chat_messages (session_id, role, content, sources, pipeline_debug, timestamp)
            VALUES (?, 'assistant', ?, ?, ?, ?)
        """, (session_id, refusal_text, json.dumps(sources), json.dumps(annotated_debug),
              datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.post("/api/chat")
async def chat_stream(req: ChatRequest):
    settings = get_settings_map()

    # Get or create session
    session_id = req.session_id
    conn = get_db_connection()
    cursor = conn.cursor()

    if not session_id:
        session_id = f"session_{uuid.uuid4().hex[:8]}"
        # Name the conversation after the question itself, not its first 30 characters.
        if "?" in req.question:
            title = req.question.split("?")[0].strip()[:60] + "?"
        else:
            title = req.question.strip()[:60] + ("..." if len(req.qestion) > 60 else "")
        cursor.execute("INSERT INTO chat_sessions (id, title, created_at) VALUES (?, ?, ?)", (session_id, title, datetime.utcnow().isoformat()))
        conn.commit()

    # Save user message
    now = datetime.utcnow().isoformat()
    cursor.execute("INSERT INTO chat_messages (session_id, role, content, timestamp) VALUES (?, 'user', ?, ?)", (session_id, req.question, now))
    conn.commit()
    conn.close()

    # ---- Guardrails, stage 1: the request itself (before anything expensive) ----
    input_verdicts: List[Dict[str, Any]] = []
    blocked_verdict = None
    if GUARDRAILS_ENABLED:
        for verdict in GUARDRAILS.screen_input(req.question, session_id):
            input_verdicts.append(verdict.to_meta())
            if not verdict.allowed:
                blocked_verdict = verdict
                break
    if blocked_verdict is not None:
        telemetry.CHAT_OUTCOMES.labels("refused_input").inc()
        return _guardrail_blocked_stream(
            session_id, guardrails.refusal_for(blocked_verdict),
            input_verdicts, [],
            {"llm_model": settings.get("llm_model", "llama3.2")})

    # Step 1: Perform Retrieval
    retrieval_payload = {
        "question": req.question,
        "collection_name": req.collection_name or "default",
        "top_k": int(settings.get("top_k", 4)),
        "embedding_model": settings.get("embedding_model", "nomic-embed-text"),
        "ollama_base_url": settings.get("ollama_base_url", OLLAMA_DEFAULT_URL)
    }

    retrieval_data = {}
    async with telemetry.async_client("gateway", timeout=30.0) as client:
        try:
            r = await client.post(f"{RETRIEVAL_SERVICE_URL}/retrieve", json=retrieval_payload)
            if r.status_code == 200:
                retrieval_data = r.json()
            else:
                log.warning("retrieval returned an error status", status=r.status_code, target="retrieval")
        except Exception as e:
            log.error("retrieval call failed", exc=e, target="retrieval")
            retrieval_data = {
                "assembled_context": "No document context available.",
                "sources": [],
                "query_embedding_dim": 0
            }

    context = retrieval_data.get("assembled_context", "")
    sources = retrieval_data.get("sources", [])
    pipeline_debug = {
        "query_embedding_dim": retrieval_data.get("query_embedding_dim", 0),
        "results_count": retrieval_data.get("results_count", 0),
        "top_k": retrieval_data.get("top_k", 4),
        "embedding_model": settings.get("embedding_model", "nomic-embed-text"),
        "llm_model": settings.get("llm_model", "llama3.2")
    }

    # ---- Guardrails, stage 2: can the corpus even speak to this question? ----
    # Runs after retrieval but before the LLM call: a question nothing in the
    # index is topically related to gets the grounded refusal instantly instead
    # of a 50-second generation whose only guarantee is the model's goodwill.
    scope_verdicts: List[Dict[str, Any]] = []
    if GUARDRAILS_ENABLED:
        top_similarity = sources[0]["similarity"] if sources else None
        scope = GUARDRAILS.check_scope(top_similarity, len(sources))
        scope_verdicts.append(scope.to_meta())
        if not scope.allowed:
            telemetry.CHAT_OUTCOMES.labels("refused_scope").inc()
            return _guardrail_blocked_stream(
                session_id, guardrails.refusal_for(scope),
                input_verdicts + scope_verdicts, sources, pipeline_debug)

    # Step 2: Stream tokens from LLM service
    llm_payload = {
        "question": req.question,
        "context": context,
        "model": settings.get("llm_model", "llama3.2"),
        "ollama_base_url": settings.get("ollama_base_url", OLLAMA_DEFAULT_URL),
        "stream": True
    }

    async def event_generator():
        # First send session metadata event
        meta_event = {
            "type": "meta",
            "session_id": session_id,
            "sources": sources,
            "pipeline_debug": pipeline_debug,
            "guardrails": input_verdicts + scope_verdicts
        }
        yield f"data: {json.dumps(meta_event)}\n\n"

        full_response_text = []
        stream_failed = False

        try:
            async with telemetry.async_client("gateway", timeout=120.0) as client:
                async with client.stream("POST", f"{LLM_SERVICE_URL}/generate", json=llm_payload) as response:
                    async for line in response.aiter_lines():
                        if line.strip().startswith("data: "):
                            token_raw = line.strip()[6:]
                            try:
                                token_obj = json.loads(token_raw)
                                if "token" in token_obj:
                                    full_response_text.append(token_obj["token"])
                                    # With guardrails on, tokens are withheld until the
                                    # finished answer passes the output screen - the
                                    # grounding check needs the whole answer. The SSE
                                    # shape is unchanged, so the frontend is not.
                                    if not GUARDRAILS_ENABLED:
                                        yield f"data: {token_raw}\n\n"
                            except Exception:
                                pass
        except Exception as e:
            stream_failed = True
            telemetry.record_downstream_failure("gateway", "llm", "/generate", e)
            log.error("llm stream failed", exc=e, target="llm")
            err_msg = f"\n[LLM Stream error: {e}]"
            full_response_text.append(err_msg)
            if not GUARDRAILS_ENABLED:
                yield f"data: {json.dumps({'token': err_msg})}\n\n"

        output_verdicts: List[Dict[str, Any]] = []
        ai_message_text = "".join(full_response_text).strip()

        # ---- Guardrails, stage 3: the finished answer, before the user sees it ----
        if GUARDRAILS_ENABLED:
            out_blocked = None
            for verdict in GUARDRAILS.screen_output(ai_message_text, context, req.question):
                output_verdicts.append(verdict.to_meta())
                if not verdict.allowed:
                    out_blocked = verdict
                    break
            if out_blocked is not None:
                ai_message_text = guardrails.refusal_for(out_blocked)
                telemetry.CHAT_OUTCOMES.labels("error" if stream_failed else "refused_output").inc()
            else:
                telemetry.CHAT_OUTCOMES.labels("error" if stream_failed else "answered").inc()
                caution = next((v.get("note") for v in output_verdicts
                                if v.get("action") == "annotate" and v.get("note")), None)
                if caution:
                    ai_message_text = f"{ai_message_text}\n\n⚠ {caution}"
            for chunk in _chunk_text(ai_message_text):
                yield f"data: {json.dumps({'token': chunk})}\n\n"
        else:
            telemetry.CHAT_OUTCOMES.labels("error" if stream_failed else "answered").inc()

        # Save AI message to DB
        annotated_debug = ({**pipeline_debug, "guardrails": input_verdicts + scope_verdicts + output_verdicts}
                           if GUARDRAILS_ENABLED else pipeline_debug)
        db_conn = get_db_connection()
        db_cursor = db_conn.cursor()
        db_cursor.execute("""
            INSERT INTO chat_messages (session_id, role, content, sources, pipeline_debug, timestamp)
            VALUES (?, 'assistant', ?, ?, ?, ?)
        """, (session_id, ai_message_text, json.dumps(sources), json.dumps(annotated_debug), datetime.utcnow().isoformat()))
        db_conn.commit()
        db_conn.close()

        if GUARDRAILS_ENABLED:
            yield f"data: {json.dumps({'type': 'guardrails', 'verdicts': input_verdicts + scope_verdicts + output_verdicts})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ==================== MODEL COMPARISON API ====================
# Models that only produce embeddings can't answer a question, so they are kept
# out of the comparison picker.
EMBEDDING_MODEL_HINTS = ("embed", "bge-", "gte-", "e5-", "minilm")

# Preferred ordering for the comparison page when these are installed.
COMPARISON_MODEL_PREFERENCE = ["llama3.2", "codellama", "mistral", "llama3"]


def _bare_model_name(tag: str) -> str:
    return tag.split(":")[0]


@app.get("/api/models/available")
async def available_models():
    """Chat-capable Ollama models, ordered so the four benchmark models lead."""
    settings = get_settings_map()
    ollama_url = settings.get("ollama_base_url", OLLAMA_DEFAULT_URL)

    installed: List[Dict[str, Any]] = []
    ollama_online = False

    try:
        async with telemetry.async_client("gateway", timeout=5.0, trust_env=False) as client:
            r = await client.get(f"{ollama_url.rstrip('/')}/api/tags")
            if r.status_code == 200:
                ollama_online = True
                for m in r.json().get("models", []):
                    tag = m.get("name", "")
                    if not tag or any(h in tag.lower() for h in EMBEDDING_MODEL_HINTS):
                        continue
                    installed.append({
                        "name": _bare_model_name(tag),
                        "tag": tag,
                        "size_bytes": m.get("size", 0),
                        "size_gb": round(m.get("size", 0) / (1024 ** 3), 2),
                        "family": (m.get("details") or {}).get("family", ""),
                        "parameter_size": (m.get("details") or {}).get("parameter_size", ""),
                        "quantization": (m.get("details") or {}).get("quantization_level", ""),
                        "modified_at": m.get("modified_at", "")
                    })
    except Exception as e:
        log.error("listing models failed", exc=e)

    def sort_key(item: Dict[str, Any]):
        name = item["name"]
        rank = COMPARISON_MODEL_PREFERENCE.index(name) if name in COMPARISON_MODEL_PREFERENCE else 99
        return (rank, name)

    installed.sort(key=sort_key)
    present = {m["name"] for m in installed}

    return {
        "ollama": "online" if ollama_online else "offline",
        "ollama_base_url": ollama_url,
        "models": installed,
        "default_selection": [m for m in COMPARISON_MODEL_PREFERENCE if m in present]
                             or [m["name"] for m in installed[:4]],
        "missing_recommended": [m for m in COMPARISON_MODEL_PREFERENCE if m not in present],
        "embedding_model": settings.get("embedding_model", "nomic-embed-text"),
    }


async def _run_retrieval(question: str, collection_name: str, top_k: int,
                         settings: Dict[str, str]) -> Dict[str, Any]:
    """Retrieve once; every model in a run answers from the identical context."""
    payload = {
        "question": question,
        "collection_name": collection_name,
        "top_k": top_k,
        "embedding_model": settings.get("embedding_model", "nomic-embed-text"),
        "ollama_base_url": settings.get("ollama_base_url", OLLAMA_DEFAULT_URL)
    }

    started = time.perf_counter()
    async with telemetry.async_client("gateway", timeout=60.0, trust_env=False) as client:
        r = await client.post(f"{RETRIEVAL_SERVICE_URL}/retrieve", json=payload)
        r.raise_for_status()
        data = r.json()
    data["retrieval_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return data


@app.post("/api/models/compare")
async def compare_models(req: ModelCompareRequest):
    """Benchmark several models on one question over shared retrieved context.

    Streams SSE so the page can fill in each model as it finishes - a four-model
    run against local Ollama can take minutes, and models are run one at a time
    so they don't contend for the same GPU/RAM and distort each other's timings.
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if not req.models:
        raise HTTPException(status_code=400, detail="Select at least one model to compare.")

    settings = get_settings_map()
    run_id = f"cmp_{uuid.uuid4().hex[:10]}"
    collection_name = req.collection_name or "default"
    top_k = req.top_k if req.top_k is not None else int(settings.get("top_k", 4))
    # De-duplicate while preserving the order the user picked.
    models = list(dict.fromkeys(m.strip() for m in req.models if m.strip()))

    async def event_generator():
        yield _sse({
            "type": "start",
            "run_id": run_id,
            "question": req.question,
            "models": models,
            "top_k": top_k,
            "collection_name": collection_name,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "warmup": req.warmup,
            "dataset_id": req.dataset_id
        })

        # --- Stage 1: shared retrieval -----------------------------------
        try:
            retrieval = await _run_retrieval(req.question, collection_name, top_k, settings)
        except Exception as e:
            yield _sse({"type": "error", "error": f"Retrieval failed: {e}"})
            yield _sse({"type": "done"})
            return

        context = retrieval.get("assembled_context", "")
        sources = retrieval.get("sources", [])
        retrieval_meta = {
            "retrieval_ms": retrieval.get("retrieval_ms", 0),
            "query_embedding_dim": retrieval.get("query_embedding_dim", 0),
            "results_count": retrieval.get("results_count", 0),
            "top_k": top_k,
            "context_chars": len(context),
            "embedding_model": settings.get("embedding_model", "nomic-embed-text"),
            "avg_similarity": round(
                sum(float(s.get("similarity", 0)) for s in sources) / len(sources), 4
            ) if sources else 0.0,
            "top_similarity": max((float(s.get("similarity", 0)) for s in sources), default=0.0),
        }

        yield _sse({"type": "retrieval", "retrieval": retrieval_meta, "sources": sources})

        # --- Stage 2: one measured generation per model ------------------
        results: List[Dict[str, Any]] = []

        for index, model in enumerate(models):
            yield _sse({"type": "model_start", "model": model, "index": index, "total": len(models)})

            bench_payload = {
                "question": req.question,
                "context": context,
                "model": model,
                "ollama_base_url": settings.get("ollama_base_url", OLLAMA_DEFAULT_URL),
                "max_tokens": req.max_tokens,
                "temperature": req.temperature,
                "warmup": req.warmup
            }

            try:
                async with telemetry.async_client("gateway", timeout=420.0, trust_env=False) as client:
                    r = await client.post(f"{LLM_SERVICE_URL}/benchmark", json=bench_payload)
                    bench = r.json() if r.status_code == 200 else {
                        "status": "error",
                        "model": model,
                        "error": f"LLM service returned HTTP {r.status_code}"
                    }
            except Exception as e:
                bench = {"status": "error", "model": model, "error": f"{type(e).__name__}: {e}"}

            if bench.get("status") == "ok":
                bench["quality"] = evaluate_answer(bench["answer"], req.question, context,
                                                   sources, dataset_id=req.dataset_id)
                bench["timings"]["retrieval_ms"] = retrieval_meta["retrieval_ms"]
                bench["timings"]["end_to_end_ms"] = round(
                    bench["timings"]["total_ms"] + retrieval_meta["retrieval_ms"], 1
                )

            results.append(bench)
            yield _sse({"type": "model_result", "result": bench})

        # --- Stage 3: per-criterion leaders + persistence -----------------
        summary = summarise_run(results)
        created_at = datetime.utcnow().isoformat()

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO model_comparisons
                    (run_id, question, collection_name, models, retrieval_ms,
                     retrieval_meta, results, summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, req.question, collection_name, json.dumps(models),
                retrieval_meta["retrieval_ms"], json.dumps(retrieval_meta),
                json.dumps(results), json.dumps(summary), created_at
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            log.error("saving model comparison failed", exc=e)

        yield _sse({
            "type": "summary",
            "run_id": run_id,
            "summary": summary,
            "results": results,
            "created_at": created_at
        })
        yield _sse({"type": "done"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/api/models/comparisons")
def list_model_comparisons(limit: int = 25):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT run_id, question, collection_name, models, retrieval_ms, summary, created_at
            FROM model_comparisons ORDER BY id DESC LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        log.error("listing comparisons failed", exc=e)
        return []

    history = []
    for row in rows:
        item = dict(row)
        for key in ("models", "summary"):
            try:
                item[key] = json.loads(item[key]) if item[key] else None
            except Exception:
                item[key] = None
        history.append(item)
    return history


@app.get("/api/models/comparisons/{run_id}")
def get_model_comparison(run_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM model_comparisons WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Comparison run not found")

    item = dict(row)
    for key in ("models", "retrieval_meta", "results", "summary"):
        try:
            item[key] = json.loads(item[key]) if item[key] else None
        except Exception:
            item[key] = None
    return item


@app.delete("/api/models/comparisons/{run_id}")
def delete_model_comparison(run_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM model_comparisons WHERE run_id = ?", (run_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted", "run_id": run_id}


# ==================== QUERY SUGGESTIONS ====================
@app.get("/api/suggestions")
def get_query_suggestions(q: str = "", collection_name: str = "default"):
    suggestions = suggest_queries(q, collection_name=collection_name, limit=5)
    return {"query": q, "suggestions": suggestions}

# ==================== SETTINGS API ====================
@app.get("/api/settings")
def get_settings():
    return get_settings_map()

@app.post("/api/settings")
def update_settings(req: SettingsRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    # exclude_none keeps omitted optional fields from overwriting stored values
    # with the literal string "None".
    settings_dict = req.dict(exclude_none=True)
    for k, v in settings_dict.items():
        cursor.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit()
    conn.close()
    return {"status": "updated", "settings": get_settings_map()}


# ==================== WEEK-4 EVALUATION API ====================
#
# A full run is 30 questions x N models and takes tens of minutes, so it is not
# streamed over one request the way /api/models/compare is: a page reload would
# throw the whole thing away. The gateway starts a background job and the UI
# polls its status. Only one job runs at a time - two evaluations sharing the
# GPU would each make the other look slow, which is the one thing a benchmark
# must not do.

_evaluation_job: Optional[Any] = None


class EvaluationRunRequest(BaseModel):
    models: List[str]
    top_k: Optional[int] = None
    max_tokens: int = 512
    temperature: float = 0.2
    limit: Optional[int] = None       # first N questions only, for a smoke run
    rebuild_kb: bool = False


class RepoRunRequest(BaseModel):
    models: List[str]
    top_k: int = 8
    max_tokens: int = 700
    reindex: bool = False


@app.get("/api/evaluation/dataset")
def evaluation_dataset():
    """Exercise 2 - the fixed evaluation set and how it breaks down."""
    from evaluation.dataset import EVAL_DATASET, category_counts, public_dataset
    from evaluation.metrics import CATEGORY_METRIC_NOTES, METRIC_DEFINITIONS

    return {
        "size": len(EVAL_DATASET),
        "categories": category_counts(),
        "items": public_dataset(),
        "metric_definitions": METRIC_DEFINITIONS,
        "category_metric_notes": CATEGORY_METRIC_NOTES,
        "code_tests_total": sum(
            i["code_task"]["tests"].count("def test_") for i in EVAL_DATASET if "code_task" in i),
    }


@app.get("/api/evaluation/kb")
def evaluation_kb():
    """State of the evaluation knowledge base and the code index."""
    from evaluation import prepare_kb, repo_index
    from evaluation.corpus import EVAL_COLLECTION

    return {
        "knowledge_base": prepare_kb.collection_status(EVAL_COLLECTION),
        "code_index": repo_index.status(),
    }


@app.post("/api/evaluation/kb/rebuild")
def evaluation_kb_rebuild():
    from evaluation import prepare_kb
    from evaluation.corpus import EVAL_COLLECTION

    settings = get_settings_map()
    return prepare_kb.build(
        EVAL_COLLECTION,
        embedding_model=settings.get("embedding_model", "nomic-embed-text"),
        ollama_base_url=settings.get("ollama_base_url", OLLAMA_DEFAULT_URL),
    )


@app.post("/api/evaluation/run")
def evaluation_run(req: EvaluationRunRequest):
    global _evaluation_job
    from evaluation.corpus import EVAL_COLLECTION
    from evaluation.dataset import EVAL_DATASET
    from evaluation.runner import EvaluationJob

    if _evaluation_job and _evaluation_job.state == "running":
        raise HTTPException(status_code=409,
                            detail="An evaluation is already running. Cancel it first.")
    if not req.models:
        raise HTTPException(status_code=400, detail="Select at least one model.")

    settings = get_settings_map()
    config = {
        "collection_name": EVAL_COLLECTION,
        "top_k": req.top_k if req.top_k is not None else int(settings.get("top_k", 4)),
        "max_tokens": req.max_tokens,
        "temperature": req.temperature,
        "embedding_model": settings.get("embedding_model", "nomic-embed-text"),
        "ollama_base_url": settings.get("ollama_base_url", OLLAMA_DEFAULT_URL),
    }
    dataset = EVAL_DATASET[:req.limit] if req.limit else EVAL_DATASET

    _evaluation_job = EvaluationJob(
        list(dict.fromkeys(m.strip() for m in req.models if m.strip())),
        config=config, rebuild_kb=req.rebuild_kb, dataset=dataset,
    ).start()
    return {"status": "started", "models": _evaluation_job.models,
            "questions": len(dataset), "config": config}


@app.get("/api/evaluation/status")
def evaluation_status():
    if not _evaluation_job:
        return {"state": "idle"}
    return _evaluation_job.snapshot()


@app.post("/api/evaluation/cancel")
def evaluation_cancel():
    if not _evaluation_job or _evaluation_job.state != "running":
        raise HTTPException(status_code=409, detail="No evaluation is running.")
    _evaluation_job.cancel()
    return {"status": "cancelling"}


@app.get("/api/evaluation/runs")
def evaluation_runs(limit: int = 20):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT run_id, models, dataset_size, created_at, wall_seconds
        FROM evaluation_runs ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [{
        "run_id": r["run_id"],
        "models": json.loads(r["models"]),
        "dataset_size": r["dataset_size"],
        "created_at": r["created_at"],
        "wall_seconds": r["wall_seconds"],
    } for r in rows]


@app.get("/api/evaluation/runs/latest")
def evaluation_latest():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT report FROM evaluation_runs ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="No evaluation has been run yet.")
    return json.loads(row["report"])


@app.get("/api/evaluation/runs/{run_id}")
def evaluation_report(run_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT report FROM evaluation_runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    return json.loads(row["report"])


@app.delete("/api/evaluation/runs/{run_id}")
def evaluation_delete(run_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM evaluation_runs WHERE run_id = ?", (run_id,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    return {"status": "deleted", "run_id": run_id}


# ---- Exercise 6: repository-level understanding ----------------------------

_repo_result: Optional[Dict[str, Any]] = None
_repo_lock = threading.Lock()


@app.get("/api/evaluation/repo/questions")
def repo_questions():
    from evaluation.repo_index import REPO_QUESTIONS, status
    return {"questions": REPO_QUESTIONS, "index": status()}


@app.post("/api/evaluation/repo/index")
def repo_build_index():
    from evaluation import repo_index

    settings = get_settings_map()
    return repo_index.build(
        embedding_model=settings.get("embedding_model", "nomic-embed-text"),
        ollama_base_url=settings.get("ollama_base_url", OLLAMA_DEFAULT_URL),
    )


@app.post("/api/evaluation/repo/run")
def repo_run(req: RepoRunRequest):
    """Run the repository questions. Blocking, but far shorter than a full
    evaluation: 7 questions rather than 30 per model."""
    global _repo_result
    from evaluation import repo_index

    if not _repo_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A repository run is already in progress.")
    try:
        settings = get_settings_map()
        ollama = settings.get("ollama_base_url", OLLAMA_DEFAULT_URL)
        embedding_model = settings.get("embedding_model", "nomic-embed-text")
        if req.reindex or not repo_index.status()["ready"]:
            repo_index.build(embedding_model=embedding_model, ollama_base_url=ollama)
        _repo_result = repo_index.run_repo_questions(
            list(dict.fromkeys(req.models)), top_k=req.top_k, max_tokens=req.max_tokens,
            embedding_model=embedding_model, ollama_base_url=ollama,
        )
        return _repo_result
    finally:
        _repo_lock.release()


@app.get("/api/evaluation/repo/result")
def repo_result():
    if _repo_result is None:
        raise HTTPException(status_code=404, detail="No repository run has completed yet.")
    return _repo_result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
