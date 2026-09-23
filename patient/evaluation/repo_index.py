"""Exercise 6 - can this LLM + RAG stack answer repository-level questions?

The Week-3 pipeline was built for prose policies. This module points the same
pipeline at its own source tree and asks the kind of question that only makes
sense across files: which modules take part in document ingestion, what calls
the LLM service, what breaks if a function changes.

The interesting part is not whether the answers are pretty. It is *where the
architecture runs out*. Chunking a repository by character count into a flat
vector index throws away everything that makes code navigable:

  * an import edge is a fact about two files, and neither file's text states it
  * a call site and its definition usually land in different chunks, and nothing
    links them
  * "what breaks if I change this" needs the reverse edge, which no chunk holds
  * similarity search retrieves k chunks; a real answer to "which files handle
    X" needs a complete set, not the k most similar snippets

So the questions below are scored on whether the retrieved chunks even *contain*
the files a correct answer must name (`expected_files`), which separates "the
model answered badly" from "the index could not supply an answer". That gap is
the argument for the repository-level tooling covered next week.
"""

import os
import sys
from typing import Any, Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ingestion_service.app.embedder import get_embedding
from ingestion_service.app.vector_store import (
    add_chunks_to_vector_store, get_chroma_client, get_or_create_collection,
)

REPO_COLLECTION = "codebase"

#: Source worth indexing. Dependencies, build output and the vector store
#: itself are not this application's code.
INCLUDE_SUFFIXES = (".py", ".jsx", ".js")
EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    "chroma_data", "dist", "build", ".vite", "storage", "data",
}
EXCLUDE_FILES = {"package-lock.json"}

#: Code chunks are smaller than prose chunks: a 800-character window swallows a
#: whole module and dilutes the embedding until every file looks alike.
CODE_CHUNK_LINES = 60
CODE_CHUNK_OVERLAP_LINES = 12


def iter_source_files(root: str = BASE_DIR) -> List[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in sorted(filenames):
            if name in EXCLUDE_FILES or not name.endswith(INCLUDE_SUFFIXES):
                continue
            found.append(os.path.join(dirpath, name))
    return sorted(found)


def chunk_source(path: str, root: str = BASE_DIR) -> List[Dict[str, Any]]:
    """Split one file into overlapping line windows.

    Line windows rather than character windows, and each chunk is prefixed with
    its path and line range, so a retrieved snippet can be cited and so the
    embedding carries at least the file's identity even when the body is
    boilerplate.
    """
    relative = os.path.relpath(path, root).replace("\\", "/")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    if not lines:
        return []

    chunks = []
    index = 0
    start = 0
    step = max(1, CODE_CHUNK_LINES - CODE_CHUNK_OVERLAP_LINES)
    while start < len(lines):
        end = min(start + CODE_CHUNK_LINES, len(lines))
        body = "\n".join(lines[start:end]).strip()
        if body:
            index += 1
            chunks.append({
                "chunk_index": index,
                "page_number": start + 1,   # reused as "first line" by the store
                "text": f"FILE: {relative} (lines {start + 1}-{end})\n\n{body}",
                "token_count": len(body.split()),
            })
        if end >= len(lines):
            break
        start += step
    return chunks


def build(collection_name: str = REPO_COLLECTION,
          embedding_model: str = "nomic-embed-text",
          ollama_base_url: str = "http://localhost:11434",
          root: str = BASE_DIR) -> Dict[str, Any]:
    """Index the repository into its own ChromaDB collection."""
    client = get_chroma_client()
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass

    files = iter_source_files(root)
    indexed = []
    total_chunks = 0

    for path in files:
        chunks = chunk_source(path, root)
        if not chunks:
            continue
        relative = os.path.relpath(path, root).replace("\\", "/")
        embeddings = [get_embedding(c["text"], model=embedding_model,
                                    base_url=ollama_base_url) for c in chunks]
        add_chunks_to_vector_store(collection_name, chunks, embeddings,
                                   doc_id=relative.replace("/", "_"), filename=relative)
        total_chunks += len(chunks)
        indexed.append({"file": relative, "chunks": len(chunks)})

    return {
        "collection": collection_name,
        "files_indexed": len(indexed),
        "total_chunks": total_chunks,
        "chunk_lines": CODE_CHUNK_LINES,
        "chunk_overlap_lines": CODE_CHUNK_OVERLAP_LINES,
        "files": indexed,
    }


def status(collection_name: str = REPO_COLLECTION) -> Dict[str, Any]:
    try:
        collection = get_or_create_collection(collection_name)
        count = collection.count()
        if not count:
            return {"collection": collection_name, "chunks": 0, "files": 0, "ready": False}
        stored = collection.get(include=["metadatas"])
        files = sorted({m.get("filename") for m in stored["metadatas"]})
        return {"collection": collection_name, "chunks": count,
                "files": len(files), "file_list": files, "ready": True}
    except Exception as e:
        return {"collection": collection_name, "chunks": 0, "files": 0,
                "ready": False, "error": str(e)}


# ---------------------------------------------------------------------------
# The repository-level questions
# ---------------------------------------------------------------------------
#
# `expected_files` is what a correct answer has to name. It is used two ways:
# whether retrieval surfaced those files at all (a property of the index), and
# whether the model named them (a property of the model). When the first fails,
# the second cannot be blamed on the model.

REPO_QUESTIONS: List[Dict[str, Any]] = [
    {
        "id": "R01",
        "kind": "multi-file feature",
        "question": "Which files are involved in ingesting an uploaded PDF, from the HTTP upload to the vectors being stored?",
        "expected_files": [
            "api_gateway/app/main.py",
            "ingestion_service/app/main.py",
            "ingestion_service/app/pdf_processor.py",
            "ingestion_service/app/chunker.py",
            "ingestion_service/app/embedder.py",
            "ingestion_service/app/vector_store.py",
        ],
        "why_hard": "Six files across two services, connected by HTTP calls and imports that no single chunk mentions.",
    },
    {
        "id": "R02",
        "kind": "caller lookup",
        "question": "Which components call the LLM service, and on which endpoints?",
        "expected_files": [
            "api_gateway/app/main.py",
            "llm_service/app/main.py",
        ],
        "why_hard": "The caller names the service by a URL constant, so the edge exists only as a string a chunk may not contain.",
    },
    {
        "id": "R03",
        "kind": "control flow",
        "question": "What happens after a user submits a question in the chat UI? Trace the request through every service until the answer streams back.",
        "expected_files": [
            "frontend/src/pages/Chat.jsx",
            "frontend/src/services/api.js",
            "api_gateway/app/main.py",
            "retrieval_service/app/main.py",
            "llm_service/app/main.py",
        ],
        "why_hard": "Crosses the language boundary: the trace starts in JSX and ends in Python, and nothing in either file names the other.",
    },
    {
        "id": "R04",
        "kind": "impact analysis",
        "question": "If the signature of get_embedding() changes, which files break?",
        "expected_files": [
            "ingestion_service/app/embedder.py",
            "ingestion_service/app/main.py",
            "retrieval_service/app/main.py",
            "seed_sample_docs.py",
            "evaluation/pipeline.py",
            "evaluation/prepare_kb.py",
            "evaluation/repo_index.py",
        ],
        "why_hard": "Needs the reverse edge - every caller of one function. A similarity index stores no reverse edges at all.",
    },
    {
        "id": "R05",
        "kind": "test mapping",
        "question": "Which test files cover the guardrail pipeline, and which gateway module do they exercise?",
        "expected_files": [
            "tests/test_guardrails.py",
            "tests/conftest.py",
            "api_gateway/app/guardrails.py",
            "api_gateway/app/main.py",
        ],
        "why_hard": "The link between a test and the code it covers is a naming convention, not text either file contains.",
    },
    {
        "id": "R06",
        "kind": "config trace",
        "question": "Where does the top_k setting come from, and which parts of the system read it?",
        "expected_files": [
            "api_gateway/app/db.py",
            "api_gateway/app/main.py",
            "retrieval_service/app/main.py",
            "frontend/src/pages/Settings.jsx",
        ],
        "why_hard": "One value with a default in SQLite, an override in the UI and readers in two services.",
    },
    {
        "id": "R07",
        "kind": "cross-cutting",
        "question": "Which modules write to the SQLite database, and which tables does each one touch?",
        "expected_files": [
            "api_gateway/app/db.py",
            "api_gateway/app/main.py",
            "seed_sample_docs.py",
            "evaluation/runner.py",
        ],
        "why_hard": "The answer is a set of write sites scattered across modules; ranking by similarity returns the k most database-flavoured chunks, not all of them.",
    },
]


def score_retrieval(sources: List[Dict[str, Any]], expected_files: List[str]) -> Dict[str, Any]:
    """Did the index even surface the files a correct answer needs?"""
    retrieved = {str(s.get("filename", "")).replace("\\", "/") for s in sources}
    found = [f for f in expected_files if f in retrieved]
    missing = [f for f in expected_files if f not in retrieved]
    return {
        "expected_files": len(expected_files),
        "files_retrieved": len(found),
        "file_recall_pct": round(100.0 * len(found) / len(expected_files), 1) if expected_files else 0.0,
        "found": found,
        "missing": missing,
        "retrieved_files": sorted(retrieved),
    }


def score_answer(answer: str, expected_files: List[str]) -> Dict[str, Any]:
    """Did the model name the files a correct answer needs?

    Matched on basename as well as full path, because a model that says
    "vector_store.py" has identified the file even without the directory.
    """
    lowered = (answer or "").lower()
    named = [f for f in expected_files
             if f.lower() in lowered or os.path.basename(f).lower() in lowered]
    return {
        "files_named": len(named),
        "expected_files": len(expected_files),
        "coverage_pct": round(100.0 * len(named) / len(expected_files), 1) if expected_files else 0.0,
        "named": named,
        "not_named": [f for f in expected_files if f not in named],
    }


def run_repo_questions(models: List[str], top_k: int = 8, max_tokens: int = 700,
                       temperature: float = 0.2, seed: int = 42,
                       embedding_model: str = "nomic-embed-text",
                       ollama_base_url: str = "http://localhost:11434",
                       emit=None) -> Dict[str, Any]:
    """Ask every repository question of every model over the code index.

    top_k defaults higher than the policy evaluation's 4: a question whose
    answer spans six files cannot be answered from four chunks, and starving it
    would test the budget rather than the architecture.
    """
    from evaluation.pipeline import generate, retrieve  # local: avoids a cycle

    emit = emit or (lambda _e: None)
    traces = []

    for index, item in enumerate(REPO_QUESTIONS):
        emit({"type": "repo_retrieval", "id": item["id"],
              "index": index + 1, "total": len(REPO_QUESTIONS)})
        retrieved = retrieve(item["question"], REPO_COLLECTION, top_k,
                             embedding_model=embedding_model,
                             ollama_base_url=ollama_base_url)
        index_score = score_retrieval(retrieved["sources"], item["expected_files"])

        answers = []
        for model in models:
            gen = generate(item["question"], retrieved["assembled_context"], model,
                           ollama_base_url=ollama_base_url, max_tokens=max_tokens,
                           temperature=temperature, seed=seed, sample_resources=False)
            if gen["status"] != "ok":
                answers.append({"model": model, "status": "error", "error": gen.get("error")})
                emit({"type": "repo_answer", "id": item["id"], "model": model,
                      "status": "error"})
                continue
            answer_score = score_answer(gen["answer"], item["expected_files"])
            answers.append({
                "model": model,
                "status": "ok",
                "answer": gen["answer"],
                "answer_score": answer_score,
                "latency_ms": gen["timings"]["total_ms"],
                "tokens": gen["tokens"]["total_tokens"],
                # The distinction the whole exercise turns on: a model cannot
                # name a file the index never handed it.
                "limited_by_index": answer_score["coverage_pct"] <= index_score["file_recall_pct"],
            })
            emit({"type": "repo_answer", "id": item["id"], "model": model,
                  "status": "ok", "coverage_pct": answer_score["coverage_pct"]})

        traces.append({
            **{k: item[k] for k in ("id", "kind", "question", "expected_files", "why_hard")},
            "index_score": index_score,
            "retrieved_sources": [
                {"file": s["filename"], "first_line": s["page"],
                 "similarity": s["similarity"], "preview": s["text"]}
                for s in retrieved["sources"]
            ],
            "context_chars": retrieved["context_chars"],
            "answers": answers,
        })

    return {"top_k": top_k, "traces": traces, "summary": summarise_repo(traces, models)}


def summarise_repo(traces: List[Dict[str, Any]], models: List[str]) -> Dict[str, Any]:
    """Where the current stack stands on repository-level questions."""
    index_recalls = [t["index_score"]["file_recall_pct"] for t in traces]
    per_model = {}
    for model in models:
        coverages = [a["answer_score"]["coverage_pct"]
                     for t in traces for a in t["answers"]
                     if a["model"] == model and a["status"] == "ok"]
        per_model[model] = {
            "mean_file_coverage_pct": round(sum(coverages) / len(coverages), 1) if coverages else None,
            "questions_answered": len(coverages),
            "fully_answered": sum(1 for c in coverages if c == 100.0),
        }

    fully_supplied = [t["id"] for t in traces if t["index_score"]["file_recall_pct"] == 100.0]
    starved = [t["id"] for t in traces if t["index_score"]["file_recall_pct"] < 50.0]

    return {
        "questions": len(traces),
        "mean_index_file_recall_pct": round(sum(index_recalls) / len(index_recalls), 1)
        if index_recalls else None,
        "questions_index_fully_supplied": fully_supplied,
        "questions_index_starved": starved,
        "per_model": per_model,
        "verdict": [
            f"The code index surfaced {round(sum(index_recalls) / len(index_recalls), 1)}% of the "
            f"files a correct answer needs, averaged over {len(traces)} questions."
            if index_recalls else "No questions were run.",
            f"It supplied every needed file on {len(fully_supplied)} question(s) and under half "
            f"of them on {len(starved)}.",
            "The ceiling is architectural, not a tuning problem: similarity search returns the "
            "k chunks that read most like the question, while these questions need the complete "
            "set of files on an import or call edge. Import graphs, call graphs and reverse "
            "references are exactly what a flat vector index cannot represent - which is the "
            "gap repository-level code intelligence tooling exists to fill.",
        ],
    }


if __name__ == "__main__":
    print(f"[*] Indexing repository into '{REPO_COLLECTION}'...")
    result = build()
    print(f"[+] {result['files_indexed']} files -> {result['total_chunks']} chunks "
          f"({CODE_CHUNK_LINES}-line windows, {CODE_CHUNK_OVERLAP_LINES}-line overlap)")
