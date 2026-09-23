"""The doctor's three indexes, stored as JSON files in its data directory.

* code      - the patient's source at one commit, chunked by function and class
              (not by character count) and carrying each file's import edges.
              The patient's own evaluation/repo_index.py documents why flat
              chunking fails for code: a call site and its definition land in
              different chunks, and import edges are facts no chunk states.
              The AST walk follows the approach of evaluation/repo_graph.py,
              re-implemented here because the doctor imports nothing from the
              patient.
* commits   - one chunk per commit per file: subject, timestamp, SHA and diff.
* incidents - resolved past incidents (cause, class, fix). Starts empty; it is
              the third arm of the ablation study.

Embeddings: local nomic-embed-text through Ollama, with the model's
"search_document: " / "search_query: " task prefixes. If Ollama cannot be
reached, callers fall back to lexical ranking - the doctor must still work when
Ollama is the thing that is broken.
"""

import ast
import hashlib
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

import httpx

from app.settings import SETTINGS, Settings, doctor_ollama_url

DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


class EmbeddingUnavailable(RuntimeError):
    pass


def embed(texts: List[str], query: bool = False, settings: Settings = SETTINGS) -> List[List[float]]:
    base = doctor_ollama_url()
    if not base:
        raise EmbeddingUnavailable("no Ollama URL configured for the doctor")
    prefix = QUERY_PREFIX if query else DOC_PREFIX
    out: List[List[float]] = []
    try:
        with httpx.Client(timeout=120, trust_env=False) as client:
            for i in range(0, len(texts), 32):
                batch = [prefix + t[:6000] for t in texts[i:i + 32]]
                r = client.post(f"{base}/api/embed", json={"model": settings.embed_model, "input": batch})
                r.raise_for_status()
                out.extend(r.json()["embeddings"])
    except (httpx.HTTPError, KeyError) as exc:
        raise EmbeddingUnavailable(f"{type(exc).__name__}: {exc}") from exc
    return out


def cosine(a: List[float], b: List[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    db = sum(y * y for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


# ---------------------------------------------------------------- code chunking

def file_imports(tree: ast.AST) -> List[str]:
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return sorted(set(mods))


def chunk_python(path: str, source: str, max_lines: int = 120) -> List[Dict[str, Any]]:
    """One chunk per top-level function/class; large classes split per method."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    imports = file_imports(tree)
    chunks = []

    def add(node, qualname):
        start = min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno])
        end = getattr(node, "end_lineno", node.lineno)
        body = "\n".join(lines[start - 1:end])
        chunks.append({"path": path, "name": qualname, "kind": type(node).__name__,
                       "start": start, "end": end, "imports": imports,
                       "text": f"FILE {path} :: {qualname} (lines {start}-{end})\nimports: {', '.join(imports)}\n\n{body}"})

    module_lines = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(node, node.name)
        elif isinstance(node, ast.ClassDef):
            size = getattr(node, "end_lineno", node.lineno) - node.lineno
            methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if size > max_lines and methods:
                for m in methods:
                    add(m, f"{node.name}.{m.name}")
            else:
                add(node, node.name)
        else:
            end = getattr(node, "end_lineno", node.lineno)
            module_lines.extend(lines[node.lineno - 1:end])
    if module_lines:
        body = "\n".join(module_lines)[:4000]
        chunks.append({"path": path, "name": "<module>", "kind": "Module", "start": 1, "end": len(lines),
                       "imports": imports,
                       "text": f"FILE {path} :: module-level code\nimports: {', '.join(imports)}\n\n{body}"})
    return chunks


_JS_DEF = re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\s+(\w+)|const\s+(\w+)\s*=)", re.M)


def chunk_js(path: str, source: str) -> List[Dict[str, Any]]:
    starts = [(m.start(), m.group(1) or m.group(2)) for m in _JS_DEF.finditer(source)]
    if not starts:
        return [{"path": path, "name": "<file>", "kind": "File", "start": 1, "end": source.count("\n") + 1,
                 "imports": [], "text": f"FILE {path}\n\n{source[:4000]}"}]
    chunks = []
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(source)
        body = source[pos:end]
        line = source.count("\n", 0, pos) + 1
        chunks.append({"path": path, "name": name, "kind": "JsDef", "start": line, "end": line + body.count("\n"),
                       "imports": [], "text": f"FILE {path} :: {name}\n\n{body[:4000]}"})
    return chunks


def list_source_files(repo: str, sha: str) -> List[str]:
    out = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "--name-only", sha, "--", "patient"],
                         check=True, capture_output=True, text=True).stdout.splitlines()
    return [p for p in out if p.endswith((".py", ".js", ".jsx")) and "/node_modules/" not in p
            and not p.startswith("patient/tests/")]


def code_chunks_at(repo: str, sha: str) -> List[Dict[str, Any]]:
    chunks = []
    for path in list_source_files(repo, sha):
        source = subprocess.run(["git", "-C", repo, "show", f"{sha}:{path}"], check=True, capture_output=True,
                                text=True, encoding="utf-8", errors="replace").stdout
        chunks.extend(chunk_python(path, source) if path.endswith(".py") else chunk_js(path, source))
    return chunks


# ---------------------------------------------------------------- index stores

class SmallIndex:
    """Exact cosine search over a handful of documents, stored as JSON.

    Every doctor index is small: tens of past incidents, a few hundred code
    chunks per commit, a few hundred commit chunks. ChromaDB twice lost the HNSW
    segment of such a collection mid-evaluation ("Nothing found on disk"), so the
    vectors live in one JSON file per index and are searched exhaustively -
    deterministic, exact, and written atomically so nothing is half-written.
    Vectors already stored in the old ChromaDB collection of the same name are
    carried over when they can still be read, so no embedding changes.
    """

    def __init__(self, name: str, settings: Settings = SETTINGS):
        self.settings = settings
        self.path = os.path.join(settings.data_dir, f"{name}.json")
        self.items: Dict[str, Dict[str, Any]] = {}
        if os.path.exists(self.path):
            import json
            with open(self.path, encoding="utf-8") as fh:
                self.items = json.load(fh)
        else:
            self._migrate_from_chroma(name)

    def _migrate_from_chroma(self, name: str) -> None:
        path = os.path.join(self.settings.data_dir, "chroma")
        if not os.path.isdir(path):
            return
        try:
            import chromadb

            col = chromadb.PersistentClient(path=path).get_collection(name)
            got = col.get(include=["documents", "metadatas", "embeddings"])
            self.items = {i: {"text": d, "meta": m or {}, "vector": [float(x) for x in e]}
                          for i, d, m, e in zip(got["ids"], got["documents"], got["metadatas"], got["embeddings"])}
        except Exception:  # missing or unreadable collection: rebuild by re-embedding
            self.items = {}
            return
        if self.items:
            self._save()

    def _save(self) -> None:
        import json
        import tempfile
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), prefix=".idx.")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.items, fh)
        os.replace(tmp, self.path)

    def ids(self) -> set:
        return set(self.items)

    def add(self, ids: List[str], texts: List[str], metadatas: List[Dict[str, Any]]) -> int:
        todo = [(i, t, m) for i, t, m in zip(ids, texts, metadatas) if i not in self.items]
        if not todo:
            return 0
        vectors = embed([t for _, t, _ in todo], settings=self.settings)
        for (i, t, m), v in zip(todo, vectors):
            clean = {k: (val if isinstance(val, (str, int, float, bool)) else str(val)) for k, val in m.items()}
            self.items[i] = {"text": t, "meta": clean, "vector": v}
        self._save()
        return len(todo)

    def query(self, text: str, k: int = 5, where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if not self.items:
            return []
        vec = embed([text], query=True, settings=self.settings)[0]
        scored = [{"id": i, "text": it["text"], "meta": it["meta"], "similarity": round(cosine(vec, it["vector"]), 4)}
                  for i, it in self.items.items()
                  if not where or all(it["meta"].get(key) == val for key, val in where.items())]
        return sorted(scored, key=lambda h: -h["similarity"])[:k]

    def count(self) -> int:
        return len(self.items)

    def similarities(self, text: str, ids: List[str]) -> Dict[str, float]:
        """Cosine similarity of the query to specific stored chunks."""
        ids = [i for i in ids if i in self.items]
        if not ids:
            return {}
        vec = embed([text], query=True, settings=self.settings)[0]
        return {i: cosine(vec, self.items[i]["vector"]) for i in ids}


Index = SmallIndex


def code_index(sha: str, settings: Settings = SETTINGS) -> Index:
    idx = Index(f"code_{sha[:12]}", settings)
    if idx.count() == 0:
        chunks = code_chunks_at(settings.repo_root, sha)
        idx.add([hashlib.sha1(f"{c['path']}:{c['name']}:{c['start']}".encode()).hexdigest() for c in chunks],
                [c["text"] for c in chunks],
                [{"path": c["path"], "name": c["name"], "kind": c["kind"], "start": c["start"], "end": c["end"],
                  "imports": ",".join(c["imports"])} for c in chunks])
    return idx


def commit_chunk_id(sha: str, path: str) -> str:
    return f"{sha[:12]}:{hashlib.sha1(path.encode()).hexdigest()[:10]}"


def commit_chunk_text(commit: Dict[str, Any], file: Dict[str, Any]) -> str:
    return (f"commit {commit['sha'][:12]} {commit['date']}\n{commit['subject']}\n{commit.get('body', '')[:400]}\n"
            f"file {file['path']}\n{file.get('diff', '')}")


def index_commits(commits: List[Dict[str, Any]], settings: Settings = SETTINGS) -> Index:
    idx = Index("commits", settings)
    ids, texts, metas = [], [], []
    for c in commits:
        for f in c["files"]:
            ids.append(commit_chunk_id(c["sha"], f["path"]))
            texts.append(commit_chunk_text(c, f))
            metas.append({"sha": c["sha"], "path": f["path"], "ts": c["ts"], "subject": c["subject"][:200]})
    if ids:
        idx.add(ids, texts, metas)
    return idx


def incident_index(settings: Settings = SETTINGS, name: str = "incidents") -> SmallIndex:
    return SmallIndex(name, settings)
