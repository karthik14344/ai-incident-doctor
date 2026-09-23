import os
if "SSL_CERT_FILE" in os.environ and not os.path.exists(os.environ["SSL_CERT_FILE"]):
    del os.environ["SSL_CERT_FILE"]

import httpx
import math
import hashlib
from typing import Dict, List

# How often the hash fallback has stood in for a real embedding this process.
# The fallback keeps the app usable offline, but a query embedded by it cannot
# be compared with chunks embedded by nomic-embed-text - the similarities are
# noise. Callers that care about correctness (the evaluation harness) read this
# counter around a call and flag any result it moved.
_FALLBACK_COUNT = 0

# Embedding calls normally return in well under a second; give up after 10 s
# so a stuck Ollama cannot hold a request thread for most of a minute.
EMBED_TIMEOUT_S = 10.0


def embedding_fallback_count() -> int:
    return _FALLBACK_COUNT


def generate_fallback_embedding(text: str, dim: int = 768) -> List[float]:
    """
    Generates a deterministic normalized pseudo-embedding vector when Ollama is unreachable.
    Allows testing ChromaDB & vector search offline.
    """
    global _FALLBACK_COUNT
    _FALLBACK_COUNT += 1
    vec = [0.0] * dim
    words = text.lower().split()
    for word in words:
        h = int(hashlib.md5(word.encode('utf-8')).hexdigest(), 16)
        idx = h % dim
        val = (h % 1000) / 500.0 - 1.0
        vec[idx] += val
    
    # Normalize vector
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    else:
        vec[0] = 1.0
    return vec

def get_embedding(text: str, model: str = "nomic-embed-text", base_url: str = "http://localhost:11434") -> List[float]:
    """
    Fetches embedding from Ollama API endpoint, fallback if unavailable.
    """
    endpoint = f"{base_url.rstrip('/')}/api/embeddings"
    try:
        with httpx.Client(timeout=EMBED_TIMEOUT_S, trust_env=False) as client:
            resp = client.post(endpoint, json={"model": model, "prompt": text})
            if resp.status_code == 200:
                data = resp.json()
                if "embedding" in data:
                    return data["embedding"]
            
            # Alternative Ollama endpoint /api/embed
            alt_endpoint = f"{base_url.rstrip('/')}/api/embed"
            alt_resp = client.post(alt_endpoint, json={"model": model, "input": text})
            if alt_resp.status_code == 200:
                alt_data = alt_resp.json()
                if "embeddings" in alt_data and len(alt_data["embeddings"]) > 0:
                    return alt_data["embeddings"][0]

    except Exception as e:
        print(f"[Embedder] Ollama embedding call failed ({e}). Using robust fallback vectorizer.")
        
    return generate_fallback_embedding(text)
