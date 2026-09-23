"""One RAG query, instrumented - the primitive the evaluation runner repeats.

Deliberately imports the application's own pieces rather than reimplementing
them: `get_embedding` and `query_vector_store` from the ingestion service,
`assemble_context` from the retrieval service, and `build_prompt` plus
`DEFAULT_SYSTEM_PROMPT` from the LLM service. The prompt sent during evaluation
is therefore byte-identical to the one the Chat page sends. A harness with its
own private prompt would be measuring a different application.

The one thing this does not go through is the HTTP hop between microservices,
so the whole evaluation can run from a single command without five servers up.
That hop costs a couple of milliseconds and is identical for every model, so it
cannot change which model wins.
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

import httpx

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ingestion_service.app.embedder import get_embedding
from ingestion_service.app.vector_store import query_vector_store
from retrieval_service.app.main import assemble_context
from llm_service.app.main import DEFAULT_SYSTEM_PROMPT, build_prompt, resolve_model_tag

from evaluation.resources import ResourceSampler

from common import config

OLLAMA_DEFAULT_URL = config.ollama_base_url()


def retrieve(question: str, collection_name: str, top_k: int,
             embedding_model: str = "nomic-embed-text",
             ollama_base_url: str = OLLAMA_DEFAULT_URL) -> Dict[str, Any]:
    """Embed the question, search ChromaDB, assemble the prompt context."""
    started = time.perf_counter()
    query_emb = get_embedding(question, model=embedding_model, base_url=ollama_base_url)
    embed_ms = (time.perf_counter() - started) * 1000

    search_started = time.perf_counter()
    chunks = query_vector_store(collection_name, query_emb, top_k=top_k)
    search_ms = (time.perf_counter() - search_started) * 1000

    assembled = assemble_context(chunks)
    return {
        "question": question,
        "assembled_context": assembled["assembled_context"],
        "sources": assembled["sources"],
        "raw_chunks": chunks,
        "query_embedding_dim": len(query_emb),
        "results_count": len(chunks),
        "top_k": top_k,
        "embed_ms": round(embed_ms, 1),
        "search_ms": round(search_ms, 1),
        "retrieval_ms": round((time.perf_counter() - started) * 1000, 1),
        "context_chars": len(assembled["assembled_context"]),
    }


def warm_up(model: str, ollama_base_url: str = OLLAMA_DEFAULT_URL,
            timeout: float = 300.0) -> Dict[str, Any]:
    """Load a model's weights before any timed request.

    Called once per model, not once per question: keeping the model resident for
    its whole pass is what makes the 27 latencies comparable to each other, and
    stops whichever model happens to go first from wearing a cold start of tens
    of seconds that has nothing to do with its speed.
    """
    started = time.perf_counter()
    error = None
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            client.post(f"{ollama_base_url.rstrip('/')}/api/generate", json={
                "model": resolve_model_tag(model),
                "prompt": "ping",
                "stream": False,
                "options": {"num_predict": 1},
            })
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    return {"warmup_ms": round((time.perf_counter() - started) * 1000, 1), "error": error}


def unload(models: List[str], ollama_base_url: str = OLLAMA_DEFAULT_URL,
           settle_seconds: float = 3.0) -> Dict[str, Any]:
    """Evict models from VRAM so the idle baseline is genuinely idle.

    Ollama keeps a model resident for five minutes after its last request. Take
    the baseline without evicting and a model left over from a previous run is
    counted as the machine's idle floor, which makes every "VRAM over baseline"
    figure read as roughly zero - the exact opposite of the truth. `keep_alive: 0`
    asks Ollama to drop it immediately; the settle wait is because the driver
    releases the allocation slightly after the API returns.
    """
    evicted, failed = [], []
    try:
        with httpx.Client(timeout=30.0, trust_env=False) as client:
            for model in models:
                try:
                    client.post(f"{ollama_base_url.rstrip('/')}/api/generate", json={
                        "model": resolve_model_tag(model),
                        "keep_alive": 0,
                    })
                    evicted.append(model)
                except Exception as e:
                    failed.append({"model": model, "error": f"{type(e).__name__}: {e}"})
    except Exception as e:
        failed.append({"model": "*", "error": f"{type(e).__name__}: {e}"})
    if evicted:
        time.sleep(settle_seconds)
    return {"evicted": evicted, "failed": failed}


def generate(question: str, context: str, model: str,
             ollama_base_url: str = OLLAMA_DEFAULT_URL,
             max_tokens: int = 512, temperature: float = 0.2, seed: int = 42,
             timeout: float = 300.0,
             sample_resources: bool = True) -> Dict[str, Any]:
    """One measured generation: answer, timings, token counts, resource usage.

    Streams so time-to-first-token is a real measurement rather than a guess,
    and never falls back to canned text the way `/generate` does - a benchmark
    that invents an answer would also invent the numbers describing it.
    """
    endpoint = f"{ollama_base_url.rstrip('/')}/api/generate"
    model_tag = resolve_model_tag(model)
    payload = {
        "model": model_tag,
        "prompt": build_prompt(question, context),
        "system": DEFAULT_SYSTEM_PROMPT,
        "stream": True,
        "options": {"temperature": temperature, "num_predict": max_tokens, "seed": seed},
    }

    tokens: List[str] = []
    ttft_ms = 0.0
    stats: Dict[str, Any] = {}
    sampler: Optional[ResourceSampler] = None

    started = time.perf_counter()
    try:
        sampler_cm = ResourceSampler() if sample_resources else None
        if sampler_cm:
            sampler = sampler_cm.__enter__()
        try:
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                with client.stream("POST", endpoint, json=payload) as response:
                    if response.status_code != 200:
                        body = response.read().decode("utf-8", "replace")
                        return {"status": "error", "model": model, "model_tag": model_tag,
                                "error": f"Ollama returned HTTP {response.status_code}: {body[:300]}"}
                    for line in response.iter_lines():
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
        finally:
            if sampler_cm:
                sampler_cm.__exit__(None, None, None)
    except Exception as e:
        return {"status": "error", "model": model, "model_tag": model_tag,
                "error": f"{type(e).__name__}: {e}"}

    wall_ms = (time.perf_counter() - started) * 1000
    answer = "".join(tokens).strip()
    if not answer:
        return {"status": "error", "model": model, "model_tag": model_tag,
                "error": "Model produced an empty response."}

    def ns_to_ms(key: str) -> float:
        return round(stats.get(key, 0) / 1_000_000, 1)

    eval_count = int(stats.get("eval_count", 0) or 0)
    eval_ms = ns_to_ms("eval_duration")
    prompt_tokens = int(stats.get("prompt_eval_count", 0) or 0)
    prompt_eval_ms = ns_to_ms("prompt_eval_duration")

    return {
        "status": "ok",
        "model": model,
        "model_tag": model_tag,
        "answer": answer,
        "timings": {
            "ttft_ms": round(ttft_ms, 1),
            "total_ms": round(wall_ms, 1),
            "load_ms": ns_to_ms("load_duration"),
            "prompt_eval_ms": prompt_eval_ms,
            "eval_ms": eval_ms,
        },
        "tokens": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": eval_count,
            "total_tokens": prompt_tokens + eval_count,
            "tokens_per_sec": round(eval_count / (eval_ms / 1000), 2) if eval_ms else 0.0,
            "truncated": eval_count >= max_tokens,
        },
        "resources": sampler.stats() if sampler else None,
        "done_reason": stats.get("done_reason", "stop"),
    }
