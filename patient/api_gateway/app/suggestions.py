"""Generate autocomplete questions from ingested knowledge-base chunks."""
import re
from typing import Any, Dict, List

from api_gateway.app.db import get_db_connection

_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "for", "on", "is", "are",
    "was", "be", "by", "at", "as", "with", "what", "how", "when", "who", "why",
}

_ORG_PREFIX = re.compile(
    r"^(university|college|institute|department|school)\s+",
    re.IGNORECASE,
)


# Suggestions are built from stored chunk text only; no model call is made while typing.
def suggest_queries(q: str, collection_name: str = "default", limit: int = 5) -> List[str]:
    query = (q or "").strip()
    if len(query) < 2:
        return []

    tokens = _tokenize(query)
    if not tokens:
        return []

    chunks = _load_chunks(collection_name)
    if not chunks:
        return []

    ranked = []
    for chunk in chunks:
        text = chunk.get("text") or ""
        filename = (chunk.get("metadata") or {}).get("filename") or ""
        score = _keyword_score(tokens, f"{filename} {text}")
        if score > 0:
            ranked.append((score, chunk))

    ranked.sort(key=lambda item: item[0], reverse=True)

    candidates: List[str] = []
    seen = set()
    for _, chunk in ranked[:24]:
        for question in _questions_from_chunk(chunk, tokens, query):
            key = _normalize(question)
            if key in seen or len(key) < 8:
                continue
            seen.add(key)
            candidates.append(question)
            if len(candidates) >= limit:
                return candidates[:limit]

    return candidates[:limit]


def _load_chunks(collection_name: str) -> List[Dict[str, Any]]:
    try:
        from ingestion_service.app.vector_store import get_collection_chunks

        chunks = get_collection_chunks(collection_name)
        if chunks:
            return chunks
    except Exception as exc:
        print(f"[Suggestions] ChromaDB read failed: {exc}")

    return _load_chunks_from_sqlite(collection_name)


def _load_chunks_from_sqlite(collection_name: str) -> List[Dict[str, Any]]:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT c.text, d.filename, c.page_number, c.chunk_index
            FROM document_chunks c
            JOIN documents d ON d.doc_id = c.doc_id
            WHERE d.collection_name = ?
            """,
            (collection_name,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "text": row["text"],
                "metadata": {
                    "filename": row["filename"],
                    "page_number": row["page_number"],
                    "chunk_index": row["chunk_index"],
                },
            }
            for row in rows
        ]
    except Exception as exc:
        print(f"[Suggestions] SQLite chunk read failed: {exc}")
        return []


def _tokenize(q: str) -> List[str]:
    tokens = re.findall(r"[a-zA-Z0-9']+", q.lower())
    meaningful = [t for t in tokens if t not in _STOPWORDS and len(t) >= 2]
    return meaningful or [t for t in tokens if len(t) >= 2]


def _keyword_score(tokens: List[str], text: str) -> float:
    lower = text.lower()
    score = 0.0
    for token in tokens:
        if re.search(rf"\b{re.escape(token)}", lower):
            score += 2.0 + 0.2 * min(lower.count(token), 6)
        elif token in lower:
            score += 0.8
    phrase = " ".join(tokens)
    if len(tokens) > 1 and phrase in lower:
        score += 2.5
    return score


def _questions_from_chunk(chunk: Dict[str, Any], tokens: List[str], raw_query: str) -> List[str]:
    text = chunk.get("text") or ""
    filename = (chunk.get("metadata") or {}).get("filename") or ""
    topic = _topic_phrase(tokens, f"{filename} {text}", raw_query)

    questions: List[str] = []
    for heading in _extract_headings(text):
        if _keyword_score(tokens, heading) > 0:
            questions.append(_heading_to_question(heading))

    for sentence in _split_sentences(text):
        if _keyword_score(tokens, sentence) <= 0:
            continue
        questions.extend(_sentence_to_questions(sentence, topic))

    if _keyword_score(tokens, filename) > 0:
        stem = re.sub(r"\.[^.]+$", "", filename.replace("_", " ").replace("-", " "))
        questions.append(_heading_to_question(stem))

    return questions


def _topic_phrase(tokens: List[str], text: str, raw_query: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]*", text)
    matched = []
    for token in tokens:
        best = None
        for word in words:
            wl = word.lower()
            if wl.startswith(token) or token in wl:
                if best is None or len(wl) > len(best):
                    best = wl
        if best:
            matched.append(best)
    if matched:
        # Prefer the longest matched document term (attendance > at).
        return sorted(set(matched), key=len, reverse=True)[0]
    return raw_query.strip().lower()


def _extract_headings(text: str) -> List[str]:
    headings = []
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) > 90:
            continue
        letters = re.sub(r"[^A-Za-z]", "", line)
        if len(letters) < 4:
            continue
        upper_ratio = sum(ch.isupper() for ch in letters) / len(letters)
        if upper_ratio >= 0.65:
            headings.append(line)
    return headings


def _heading_to_question(heading: str) -> str:
    cleaned = re.sub(r"\([^)]*\)", "", heading)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:.")
    cleaned = _ORG_PREFIX.sub("", cleaned).strip()
    cleaned = cleaned.lower()
    if cleaned.endswith("?"):
        return cleaned[0].upper() + cleaned[1:]
    if re.search(r"\b(rules|guidelines|procedures|regulations|timings)\b", cleaned):
        return f"What are the {cleaned}?"
    return f"What is the {cleaned}?"


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 20]


def _sentence_to_questions(sentence: str, topic: str) -> List[str]:
    sl = sentence.lower()
    questions = []

    if re.search(r"\b(policy|policies)\b", sl):
        questions.append(f"What is the {topic} policy?")
    if re.search(r"\b(minimum|required to|must maintain|at least)\b", sl):
        questions.append(f"What is the minimum {topic} required?")
    if re.search(
        r"\b(below|between \d|falls?|result in|will result|ineligible|deregistration|condonation)\b",
        sl,
    ):
        questions.append(f"What happens if {topic} falls below the limit?")
    if re.search(r"\bcalculat", sl):
        questions.append(f"How is {topic} calculated?")
    if re.search(r"\b(procedure|application|must be endorsed|submit)\b", sl):
        questions.append(f"What is the {topic} procedure?")
    if re.search(r"\b(rules?|regulations?)\b", sl):
        questions.append(f"What are the {topic} rules?")

    return questions


def _normalize(question: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", question.lower())
