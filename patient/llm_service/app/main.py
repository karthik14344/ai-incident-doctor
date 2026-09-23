import os
if "SSL_CERT_FILE" in os.environ and not os.path.exists(os.environ["SSL_CERT_FILE"]):
    del os.environ["SSL_CERT_FILE"]

import sys
import json
import time
import httpx
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

# The comparison page reports CPU / GPU / memory consumption, which has to be
# sampled here - this is the process that waits on the generation, so it is the
# only place that knows exactly when a timed run starts and stops.
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from evaluation.resources import ResourceSampler
from common import config, telemetry

app = FastAPI(title="LLM Service", version="1.0.0")
log = telemetry.instrument(app, "llm")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class GenerateRequest(BaseModel):
    question: str
    context: str
    model: str = "llama3.2"
    ollama_base_url: str = Field(default_factory=config.ollama_base_url)
    system_prompt: Optional[str] = None
    stream: bool = True

class BenchmarkRequest(BaseModel):
    """A single measured generation used by the model comparison page."""
    question: str
    context: str
    model: str
    ollama_base_url: str = Field(default_factory=config.ollama_base_url)
    system_prompt: Optional[str] = None
    # Bounded + deterministic so every model in a comparison gets equal treatment.
    max_tokens: int = 512
    temperature: float = 0.2
    seed: int = 42
    timeout: float = 300.0
    # Load the weights before the timed run. Without this the first model in a
    # comparison absorbs a cold-start of tens of seconds and looks slow purely
    # for going first, which measures load order rather than the models.
    warmup: bool = True

DEFAULT_SYSTEM_PROMPT = """You are KnowledgeAI, an intelligent document-based RAG assistant.
For general greetings (such as "hi", "hello", "hey", "good morning"), respond with a warm, polite welcome and invite the user to ask questions about the uploaded documents.
For factual questions, use the provided context from retrieved documents to answer accurately and cite specific source details or page numbers when relevant.
Do NOT invent facts outside the provided context."""

# Ollama resolves bare model names to ':latest' anyway, but explicit tags make logs unambiguous.
def resolve_model_tag(model: str) -> str:
    """Ollama needs an explicit tag; settings/UI usually store the bare name."""
    name = (model or "").strip()
    return name if ":" in name else f"{name}:latest"

# Greetings skip retrieval context entirely - there is nothing in the documents to cite.
def is_greeting_question(q: str) -> bool:
    clean_q = q.strip().lower().strip("!.,?")
    greetings = {"hi", "hello", "hey", "greetings", "good morning", "good afternoon", "good evening", "hi there", "hello there"}
    return clean_q in greetings or len(clean_q) <= 3

def build_prompt(question: str, context: str) -> str:
    if is_greeting_question(question):
        return f"""USER QUESTION: {question}

INSTRUCTION: The user is greeting you with "{question}". Respond with a warm, friendly, professional welcome as KnowledgeAI RAG Document Assistant. Inform them that you are ready to help answer any questions about their uploaded documents (such as attendance policies, hostel regulations, examination guidelines, and rules). Keep it clear and inviting!

FINAL ANSWER:"""

    return f"""--- RETRIEVED DOCUMENT CONTEXT ---
{context}
----------------------------------

USER QUESTION: {question}

FINAL ANSWER:"""

async def stream_ollama_tokens(req: GenerateRequest):
    sys_prompt = req.system_prompt or DEFAULT_SYSTEM_PROMPT
    prompt = build_prompt(req.question, req.context)
    
    endpoint = f"{req.ollama_base_url.rstrip('/')}/api/generate"
    model_name = resolve_model_tag(req.model)

    payload = {
        "model": model_name,
        "prompt": prompt,
        "system": sys_prompt,
        "stream": True
    }

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
            async with client.stream("POST", endpoint, json=payload) as response:
                if response.status_code == 200:
                    async for line in response.aiter_lines():
                        if line.strip():
                            try:
                                data = json.loads(line)
                                token = data.get("response", "")
                                if token:
                                    yield f"data: {json.dumps({'token': token})}\n\n"
                                if data.get("done", False):
                                    yield f"data: {json.dumps({'done': True})}\n\n"
                                    break
                            except Exception:
                                pass
                    telemetry.OLLAMA_LATENCY.labels("llm", "generate").observe(time.perf_counter() - started)
                    return
                else:
                    telemetry.OLLAMA_FAILURES.labels("llm", "generate", f"http_{response.status_code}").inc()
                    log.warning("ollama returned an error status", status=response.status_code, model=model_name)
    except Exception as e:
        telemetry.OLLAMA_FAILURES.labels("llm", "generate", type(e).__name__).inc()
        log.error("ollama stream failed", exc=e, model=model_name)
    telemetry.OLLAMA_LATENCY.labels("llm", "generate").observe(time.perf_counter() - started)

    # Fallback RAG generator if Ollama connection is unavailable
    fallback_text = (
        f"Based on the retrieved document context:\n\n"
        f"{req.context[:400]}...\n\n"
        f"Key details found regarding '{req.question}' have been extracted above. "
        f"(Note: Running with llama3.2 local model integration)."
    )
    for word in fallback_text.split(" "):
        yield f"data: {json.dumps({'token': word + ' '})}\n\n"
        await asyncio.sleep(0.02)
    yield f"data: {json.dumps({'done': True})}\n\n"

@app.post("/generate")
async def generate(req: GenerateRequest):
    if req.stream:
        return StreamingResponse(
            stream_ollama_tokens(req),
            media_type="text/event-stream"
        )
    else:
        # Non-streaming response
        tokens = []
        async for chunk in stream_ollama_tokens(req):
            if chunk.startswith("data: "):
                try:
                    obj = json.loads(chunk[6:])
                    if "token" in obj:
                        tokens.append(obj["token"])
                except Exception:
                    pass
        return {"response": "".join(tokens)}

@app.post("/benchmark")
async def benchmark(req: BenchmarkRequest):
    """Run one model once and report what it cost.

    Unlike /generate this never falls back to canned text: a benchmark that
    invents an answer would also invent the numbers describing it, so an
    unreachable Ollama is reported as a failed run instead.
    """
    sys_prompt = req.system_prompt or DEFAULT_SYSTEM_PROMPT
    prompt = build_prompt(req.question, req.context)
    endpoint = f"{req.ollama_base_url.rstrip('/')}/api/generate"
    model_name = resolve_model_tag(req.model)

    payload = {
        "model": model_name,
        "prompt": prompt,
        "system": sys_prompt,
        "stream": True,
        "options": {
            "temperature": req.temperature,
            "num_predict": req.max_tokens,
            "seed": req.seed
        }
    }

    tokens: List[str] = []
    ttft_ms = 0.0
    warmup_ms = 0.0
    stats: Dict[str, Any] = {}
    sampler: Optional[ResourceSampler] = None

    try:
        async with httpx.AsyncClient(timeout=req.timeout, trust_env=False) as client:
            if req.warmup:
                warm_started = time.perf_counter()
                try:
                    await client.post(endpoint, json={
                        "model": model_name,
                        "prompt": "ping",
                        "stream": False,
                        "options": {"num_predict": 1}
                    })
                except Exception as e:
                    # A failed warmup isn't fatal - the timed run below will
                    # surface the real error, just with load time included.
                    print(f"[Benchmark] Warmup failed for {model_name}: {e}")
                warmup_ms = (time.perf_counter() - warm_started) * 1000

            # Started after warmup so the sampled window covers generation only,
            # not the weights being paged into VRAM.
            sampler = ResourceSampler()
            sampler.__enter__()
            started = time.perf_counter()
            async with client.stream("POST", endpoint, json=payload) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", "replace")
                    return {
                        "status": "error",
                        "model": req.model,
                        "model_tag": model_name,
                        "error": f"Ollama returned HTTP {response.status_code}: {body[:300]}"
                    }

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue

                    token = data.get("response", "")
                    if token:
                        if not tokens:
                            ttft_ms = (time.perf_counter() - started) * 1000
                        tokens.append(token)

                    if data.get("done", False):
                        stats = data
                        break
    except Exception as e:
        if sampler:
            sampler.__exit__(None, None, None)
        return {
            "status": "error",
            "model": req.model,
            "model_tag": model_name,
            "error": f"{type(e).__name__}: {e}"
        }

    wall_ms = (time.perf_counter() - started) * 1000
    if sampler:
        sampler.__exit__(None, None, None)
    answer = "".join(tokens).strip()

    if not answer:
        return {
            "status": "error",
            "model": req.model,
            "model_tag": model_name,
            "error": "Model produced an empty response."
        }

    # Ollama reports durations in nanoseconds.
    def ns_to_ms(key: str) -> float:
        return round(stats.get(key, 0) / 1_000_000, 1)

    eval_count = int(stats.get("eval_count", 0) or 0)
    eval_ms = ns_to_ms("eval_duration")
    prompt_tokens = int(stats.get("prompt_eval_count", 0) or 0)
    prompt_eval_ms = ns_to_ms("prompt_eval_duration")

    return {
        "status": "ok",
        "model": req.model,
        "model_tag": model_name,
        "answer": answer,
        "timings": {
            "ttft_ms": round(ttft_ms, 1),
            "total_ms": round(wall_ms, 1),
            "load_ms": ns_to_ms("load_duration"),
            "warmup_ms": round(warmup_ms, 1),
            "prompt_eval_ms": prompt_eval_ms,
            "eval_ms": eval_ms,
            "ollama_total_ms": ns_to_ms("total_duration"),
        },
        "tokens": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": eval_count,
            "total_tokens": prompt_tokens + eval_count,
            "tokens_per_sec": round(eval_count / (eval_ms / 1000), 2) if eval_ms else 0.0,
            "prompt_tokens_per_sec": round(prompt_tokens / (prompt_eval_ms / 1000), 2) if prompt_eval_ms else 0.0,
            "truncated": eval_count >= req.max_tokens,
        },
        "resources": sampler.stats() if sampler else None,
        "done_reason": stats.get("done_reason", "stop"),
    }

@app.get("/health")
def health():
    return {"service": "llm", "status": "online"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
