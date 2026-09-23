"""Exercise 3 - the eight required metrics, each with its formula written down.

The assignment asks for the calculation, not just the number, so every metric
here is deterministic, lexical and inspectable: no second LLM sits in judgement,
which also means scoring a run costs nothing and cannot perturb the timings it
is reporting on.

QUALITY
  correctness / accuracy    fact recall against ground truth, minus wrong-value
                            penalty; abstention scored on the out-of-scope probes
  relevance                 does the answer address what was asked, on topic
  retrieval quality         precision@k, recall@k and MRR of retrieved chunks
                            against the (filename, page) that truly holds the answer
  hallucination rate        share of checkable claims with no support in the
                            retrieved context
  test-pass rate            see code_eval.py - generated code run against pytest

PERFORMANCE
  response latency          time to first token, generation time, end-to-end
  token usage               prompt / completion / total tokens, tokens per second
  CPU / GPU / memory        see resources.py - sampled during the timed run

Applicability
-------------
Not every metric applies to every task, and pretending otherwise would corrupt
the averages. Applicability keys on `task_type` - the internal shape of the
task - not on the visible seven-category label, so the report's categorisation
can change without the metric logic drifting with it:

* hallucination rate is skipped on greetings (no factual claim to support) and
  on code tasks (code is judged by its tests)
* retrieval quality is skipped on the out-of-scope probes, where no chunk can
  be correct, and on the self-contained code questions, whose evidence is
  quoted in the question itself
* correctness on a code task IS its test-pass rate

Each result carries the applicability flags so the aggregates can say what they
averaged over, and every category-wise number is reported as n/a where the
metric does not apply rather than being forced to a value.
"""

import re
import statistics
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Shared text handling
# ---------------------------------------------------------------------------

STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "you", "your", "our", "its", "with",
    "that", "this", "these", "those", "from", "have", "has", "had", "not", "but",
    "can", "will", "would", "should", "could", "may", "might", "must", "into",
    "than", "then", "them", "they", "their", "there", "here", "what", "when",
    "which", "who", "whom", "how", "why", "all", "any", "each", "such", "only",
    "own", "same", "some", "more", "most", "other", "also", "about", "over",
    "under", "between", "during", "after", "before", "above", "below", "been",
    "being", "does", "did", "doing", "get", "got", "let", "per", "via", "yes",
    "based", "provided", "context", "document", "documents", "answer", "question",
    "source", "sources", "page", "pages", "information", "according", "student",
    "students", "please", "note", "however", "therefore",
}

# Letters and numbers only: a trailing sentence period must not make
# "attendance." a different token from "attendance" when matching context.
_WORD_RE = re.compile(r"[a-z]+|\d+(?:\.\d+)?")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")

#: Phrases that count as the model declining to answer. The out-of-scope probes
#: are scored on whether one of these appears instead of an invented fact.
ABSTENTION_MARKERS = (
    "i don't know", "i do not know", "no relevant", "not mentioned",
    "does not contain", "doesn't contain", "do not contain", "no information",
    "cannot answer", "can't answer", "unable to answer", "not provided",
    "no document context", "insufficient information", "not available in",
    "not specified", "isn't specified", "is not found", "not found in",
    "no details", "does not provide", "doesn't provide", "not included in",
    "unable to find", "no mention", "not covered", "outside the scope",
    # Added after reading what the models actually say when they decline.
    # llama3.2 almost always phrases it as "I couldn't find any information
    # about X", which the list above missed entirely - so a model that was
    # abstaining correctly was being scored as though it had fabricated an
    # answer, on the very questions designed to measure fabrication.
    "couldn't find", "could not find", "didn't find", "did not find",
    "does not mention", "doesn't mention", "do not mention", "don't mention",
    "isn't mentioned", "aren't mentioned", "no reference to", "not listed",
    "don't have information", "do not have information", "no specific information",
    "not stated", "isn't stated", "not described", "cannot determine",
)


def normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip markdown emphasis and NBSPs.

    Ground-truth matching is substring-based, so "**75%**" and "75 %" have to
    reduce to the same shape as "75%" before comparison.
    """
    lowered = (text or "").lower().replace(" ", " ")
    lowered = re.sub(r"[*_`]", "", lowered)
    lowered = re.sub(r"(\d)\s+%", r"\1%", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def content_words(text: str) -> List[str]:
    """Meaning-bearing tokens: alphanumerics over 2 chars, minus stopwords."""
    return [w for w in _WORD_RE.findall(normalize(text))
            if len(w) > 2 and w not in STOPWORDS]


def numbers_in(text: str) -> List[str]:
    """Bare numeric tokens, normalised so 40 and 40.0 compare equal."""
    out = []
    for raw in _NUMBER_RE.findall(normalize(text)):
        value = float(raw)
        out.append(str(int(value)) if value == int(value) else str(value))
    return out


def sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text or "") if s.strip()]


def has_abstained(answer: str) -> bool:
    lowered = normalize(answer)
    return any(marker in lowered for marker in ABSTENTION_MARKERS)


def _pct(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(100.0 * numerator / denominator, 1)


def strip_code_fences(answer: str) -> str:
    """Answer text with fenced code removed, so prose metrics ignore code."""
    return re.sub(r"```.*?```", " ", answer or "", flags=re.S)


# ---------------------------------------------------------------------------
# QUALITY METRIC 1 - Correctness / Accuracy
# ---------------------------------------------------------------------------

CORRECTNESS_THRESHOLD = 70.0  #: an answer at or above this counts as correct


def correctness(answer: str, item: Dict[str, Any],
                test_pass_rate_pct: Optional[float] = None) -> Dict[str, Any]:
    """Fact recall against ground truth, penalised for stating wrong values.

        fact_recall  = expected facts found in the answer / expected facts
        penalty      = forbidden values present / forbidden values listed
        correctness  = 100 * fact_recall * (1 - 0.5 * penalty)

    A forbidden value halves rather than zeroes the score: quoting the
    condonation band while also giving the right minimum is a partly-right
    answer, not a total failure.

    Two task shapes are scored differently, because fact recall would measure
    the wrong thing:

    * out-of-scope probes - the corpus has no answer, so the only correct
      behaviour is to abstain. 100 if it abstained, 0 if it answered anyway.
    * code tasks (code generation and refactoring) - correctness IS the share
      of unit tests the code passes, supplied by the caller from code_eval.py.
    """
    if item.get("task_type") == "code-generation":
        rate = test_pass_rate_pct if test_pass_rate_pct is not None else 0.0
        return {
            "mode": "test-pass-rate",
            "facts_hit": None, "facts_total": None,
            "fact_recall_pct": None, "forbidden_hits": 0, "penalty_pct": 0.0,
            "abstained": False,
            "correctness_pct": round(rate, 1),
            "is_correct": rate >= CORRECTNESS_THRESHOLD,
        }

    abstained = has_abstained(answer)

    if not item["answerable"]:
        return {
            "mode": "abstention",
            "facts_hit": None, "facts_total": None,
            "fact_recall_pct": None, "forbidden_hits": 0, "penalty_pct": 0.0,
            "abstained": abstained,
            "correctness_pct": 100.0 if abstained else 0.0,
            "is_correct": abstained,
        }

    haystack = normalize(answer)
    facts = item["expected_facts"]
    hits = sum(1 for aliases in facts
               if any(normalize(a) in haystack for a in aliases))

    forbidden = item.get("forbidden", [])
    forbidden_hits = sum(1 for aliases in forbidden
                         if any(normalize(a) in haystack for a in aliases))

    recall = _pct(hits, len(facts))
    penalty = _pct(forbidden_hits, len(forbidden)) if forbidden else 0.0
    score = round(recall * (1 - 0.5 * (penalty / 100.0)), 1)

    return {
        "mode": "fact-recall",
        "facts_hit": hits,
        "facts_total": len(facts),
        "fact_recall_pct": recall,
        "forbidden_hits": forbidden_hits,
        "penalty_pct": penalty,
        "abstained": abstained,
        "correctness_pct": score,
        "is_correct": score >= CORRECTNESS_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# QUALITY METRIC 2 - Relevance
# ---------------------------------------------------------------------------

def relevance(answer: str, item: Dict[str, Any], context: str) -> Dict[str, Any]:
    """Does the answer address what was asked, and stay on topic?

        topic_coverage = topic terms of the task appearing in the answer / topic terms
        on_topic_share = answer sentences containing at least one topic term or
                         retrieved-context term / checkable sentences
        relevance      = 0.5 * topic_coverage + 0.5 * on_topic_share

    Topic terms are curated per task rather than lifted from the question, so a
    model cannot score well by echoing the question back. The second half
    catches the opposite failure: a correct first line followed by paragraphs
    about something else.
    """
    prose = strip_code_fences(answer)
    haystack = normalize(prose)

    terms = [normalize(t) for t in item.get("topic_terms", [])]
    covered = sum(1 for t in terms if t in haystack)
    topic_coverage = _pct(covered, len(terms))

    context_vocab = set(content_words(context))
    term_words = {w for t in terms for w in content_words(t)}

    checkable, on_topic = 0, 0
    for sentence in sentences(prose):
        words = content_words(sentence)
        if len(words) < 3:
            continue
        checkable += 1
        if any(w in term_words or w in context_vocab for w in words):
            on_topic += 1

    on_topic_share = _pct(on_topic, checkable) if checkable else 0.0

    # An abstention on an unanswerable probe is maximally relevant behaviour,
    # even though it mentions almost none of the topic terms.
    if not item["answerable"] and has_abstained(prose):
        return {
            "topic_terms_covered": covered, "topic_terms_total": len(terms),
            "topic_coverage_pct": topic_coverage,
            "sentences_checked": checkable, "sentences_on_topic": on_topic,
            "on_topic_share_pct": on_topic_share,
            "relevance_pct": 100.0,
            "note": "correct abstention on an out-of-scope question",
        }

    return {
        "topic_terms_covered": covered, "topic_terms_total": len(terms),
        "topic_coverage_pct": topic_coverage,
        "sentences_checked": checkable, "sentences_on_topic": on_topic,
        "on_topic_share_pct": on_topic_share,
        "relevance_pct": round(0.5 * topic_coverage + 0.5 * on_topic_share, 1),
        "note": None,
    }


# ---------------------------------------------------------------------------
# QUALITY METRIC 3 - Retrieval quality
# ---------------------------------------------------------------------------

def retrieval_quality(sources: List[Dict[str, Any]], item: Dict[str, Any]) -> Dict[str, Any]:
    """How good was the context retrieval handed to every model?

        relevant(chunk) = (chunk.filename, chunk.page) is in the task's gold set
        precision@k     = relevant chunks retrieved / chunks retrieved
        recall@k        = distinct gold pages retrieved / gold pages that exist
        MRR             = 1 / rank of the first relevant chunk (0 if none)
        hit@k           = 1 if any relevant chunk was retrieved
        retrieval score = 100 * (0.4*precision_norm + 0.4*recall + 0.2*MRR)

    `precision_norm` rather than raw precision, because raw precision@k has a
    ceiling of min(|gold|, k)/k that has nothing to do with retrieval quality:
    a question with one correct page can never exceed 25% precision at k=4, so a
    perfect retriever would still score 25 and look broken. precision_norm =
    relevant retrieved / min(|gold|, k) - 100% means "every slot that could have
    held a correct chunk did". Raw precision is reported alongside it.

    Retrieval runs once per question and is shared by every model, so this
    number is a property of the pipeline, not of any model. It is the ceiling
    the models are working under: a question with retrieval score 0 cannot be
    answered correctly from context by anyone.

    Not applicable to the out-of-scope probes - no chunk can be the right chunk
    when the corpus holds no answer. Their similarity scores are reported
    instead, since a low top similarity is what SHOULD trigger an abstention.

    Also not applicable to the self-contained code questions (Code Retrieval,
    Dependency Understanding, Bug Analysis): the excerpt under discussion is
    quoted in the question, so no corpus chunk is part of a correct answer and
    there is nothing for retrieval to get right or wrong.
    """
    gold = {(f.lower(), int(p)) for f, p in item.get("gold_sources", [])}
    retrieved = [(str(s.get("filename", "")).lower(), int(s.get("page", 0)))
                 for s in sources]
    similarities = [float(s.get("similarity", 0.0)) for s in sources]

    if not gold:
        note = ("no gold chunk exists - abstention is the correct outcome"
                if not item.get("answerable") else
                "the evidence is quoted in the question itself - no corpus chunk can "
                "be relevant, so retrieval quality is not applicable")
        return {
            "applicable": False,
            "precision_at_k": None, "precision_normalised_pct": None,
            "precision_ceiling_pct": None, "recall_at_k": None, "mrr": None,
            "context_noise_pct": None,
            "hit_at_k": None, "retrieval_quality_pct": None,
            "retrieved_count": len(retrieved),
            "relevant_retrieved": 0,
            "gold_units": 0,
            "top_similarity": round(max(similarities), 4) if similarities else 0.0,
            "avg_similarity": round(sum(similarities) / len(similarities), 4) if similarities else 0.0,
            "note": note,
        }

    relevant_flags = [unit in gold for unit in retrieved]
    relevant_count = sum(relevant_flags)
    distinct_gold_hit = len({u for u, ok in zip(retrieved, relevant_flags) if ok})

    precision = _pct(relevant_count, len(retrieved))
    achievable = min(len(gold), len(retrieved)) or 1
    precision_norm = _pct(relevant_count, achievable)
    recall = _pct(distinct_gold_hit, len(gold))
    first = next((i for i, ok in enumerate(relevant_flags, start=1) if ok), 0)
    mrr = round(1.0 / first, 4) if first else 0.0

    return {
        "applicable": True,
        "precision_at_k": precision,
        "precision_ceiling_pct": _pct(achievable, len(retrieved)),
        "precision_normalised_pct": precision_norm,
        # Share of the prompt's context window spent on chunks that do not hold
        # the answer. Unavoidably high when one page answers the question and
        # k=4, but it is the number that explains a model drifting off into a
        # neighbouring policy, so it is reported rather than averaged away.
        "context_noise_pct": round(100.0 - precision, 1),
        "recall_at_k": recall,
        "mrr": mrr,
        "hit_at_k": 1 if first else 0,
        "retrieval_quality_pct": round(0.4 * precision_norm + 0.4 * recall + 0.2 * mrr * 100, 1),
        "retrieved_count": len(retrieved),
        "relevant_retrieved": relevant_count,
        "gold_units": len(gold),
        "first_relevant_rank": first or None,
        "top_similarity": round(max(similarities), 4) if similarities else 0.0,
        "avg_similarity": round(sum(similarities) / len(similarities), 4) if similarities else 0.0,
        "note": None,
    }


# ---------------------------------------------------------------------------
# QUALITY METRIC 4 - Hallucination rate
# ---------------------------------------------------------------------------

CLAIM_SUPPORT_THRESHOLD = 0.6  #: share of a sentence's content words that must be in context

#: Task shapes where claim grounding in the retrieved context measures nothing:
#: a welcome message asserts nothing checkable, and code - generated or quoted
#: in the question - is judged by its tests / against the quoted excerpt, not
#: by overlap with the retrieved policy pages. Reported as not applicable.
HALLUCINATION_SKIP_TASK_TYPES = {"greeting", "code-generation", "code-snippet"}


def hallucination(answer: str, context: str, question: str,
                  item: Dict[str, Any]) -> Dict[str, Any]:
    """Share of the answer's checkable claims that the retrieved context does
    not support.

        claim          = a sentence with at least 4 content words
        supported      = at least 60% of its content words appear in the
                         retrieved context, AND every number it states appears
                         in the retrieved context or in the question itself
        hallucination  = unsupported claims / checkable claims

    Numbers are checked separately and strictly because that is how this
    application fails in practice: a fluent, well-phrased sentence that quotes
    "80% attendance" is far more damaging than one with unusual wording.
    Numbers from the question are allowed, since restating "you have 68%" is
    not an invention.

    On the out-of-scope probes the rule is absolute: any checkable claim at all
    is a fabrication, because there was nothing to ground it in.

    Skipped for greetings (a welcome message has no factual claim to support),
    for code tasks (generated code is judged by its tests) and for the
    self-contained code questions (the excerpt under discussion is quoted in
    the question, so grounding against retrieved policy pages would measure
    the wrong corpus).
    """
    if item.get("task_type") in HALLUCINATION_SKIP_TASK_TYPES:
        return {
            "applicable": False,
            "claims_total": 0, "claims_unsupported": 0,
            "hallucination_rate_pct": None,
            "fabricated_numbers": [],
            "unsupported_examples": [],
            "note": (f"not measured for {item.get('task_type')} tasks - there is no "
                     "retrieved-context claim to check here"),
        }

    prose = strip_code_fences(answer)
    context_vocab = set(content_words(context))
    allowed_numbers = set(numbers_in(context)) | set(numbers_in(question))

    claims_total = 0
    unsupported: List[str] = []
    fabricated: List[str] = []

    for sentence in sentences(prose):
        words = content_words(sentence)
        if len(words) < 4:
            continue

        # A refusal is a statement ABOUT the context, not a claim drawn from it,
        # so it has no business being checked for grounding in that context.
        # Scoring it as a claim punished exactly the behaviour the out-of-scope
        # probes exist to reward: "The provided documents do not contain
        # information about the number of books a student can borrow" shares
        # few content words with the library chunks, so a model that correctly
        # declined was being recorded as 100% hallucinating.
        if any(marker in normalize(sentence) for marker in ABSTENTION_MARKERS):
            continue

        claims_total += 1

        bad_numbers = [n for n in numbers_in(sentence) if n not in allowed_numbers]
        overlap = sum(1 for w in words if w in context_vocab) / len(words)

        if bad_numbers or overlap < CLAIM_SUPPORT_THRESHOLD:
            unsupported.append(sentence[:220])
            fabricated.extend(bad_numbers)

    if not item["answerable"]:
        abstained = has_abstained(prose)
        if not claims_total:
            offenders, rate = [], 0.0
        elif not abstained:
            # Nothing in the corpus could ground this, so every asserted fact
            # is invented - even one whose wording happens to echo a chunk.
            offenders = [s[:220] for s in sentences(prose) if len(content_words(s)) >= 4]
            rate = 100.0
        else:
            # Abstained but still volunteered detail ("no fee is listed; the
            # documents cover attendance and exams"). Score only what lacks support.
            offenders, rate = unsupported, _pct(len(unsupported), claims_total)
        return {
            "applicable": True,
            "claims_total": claims_total,
            "claims_unsupported": len(offenders),
            "hallucination_rate_pct": round(rate, 1),
            "fabricated_numbers": sorted(set(fabricated)),
            "unsupported_examples": offenders[:3],
            "abstained": abstained,
            "note": "out-of-scope probe: any asserted fact counts as fabricated",
        }

    return {
        "applicable": True,
        "claims_total": claims_total,
        "claims_unsupported": len(unsupported),
        "hallucination_rate_pct": _pct(len(unsupported), claims_total),
        "fabricated_numbers": sorted(set(fabricated)),
        "unsupported_examples": unsupported[:3],
        "note": None,
    }


# ---------------------------------------------------------------------------
# Aggregation across the dataset
# ---------------------------------------------------------------------------

def _mean(values: List[float]) -> Optional[float]:
    return round(statistics.fmean(values), 1) if values else None


def _percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return round(ordered[index], 1)


def aggregate_model(model: str, per_question: List[Dict[str, Any]],
                    baseline: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Roll one model's per-question results into the row of the comparison table.

    Every average states how many questions it covered, because the metrics have
    different applicability sets and an average over 23 items is not comparable
    with one over 27.

    `baseline` is the machine reading taken before the run began. CPU, system RAM
    and VRAM are all machine-wide, and on a laptop with a browser and an IDE open
    the idle floor is a large share of the absolute figure - 5 GB of VRAM was
    already in use here before any model loaded. Subtracting the baseline gives
    what the model actually cost; both figures are reported, because the absolute
    one is what decides whether the model fits on the machine at all.
    """
    ok = [r for r in per_question if r.get("status") == "ok"]
    failed = [r for r in per_question if r.get("status") != "ok"]

    correctness_scores = [r["correctness"]["correctness_pct"] for r in ok]
    correct_flags = [r["correctness"]["is_correct"] for r in ok]
    relevance_scores = [r["relevance"]["relevance_pct"] for r in ok]
    halluc = [r["hallucination"]["hallucination_rate_pct"] for r in ok
              if r["hallucination"]["applicable"]]
    code = [r["code_eval"] for r in ok if r.get("code_eval")]

    ttft = [r["timings"]["ttft_ms"] for r in ok]
    total = [r["timings"]["total_ms"] for r in ok]
    e2e = [r["timings"]["end_to_end_ms"] for r in ok]
    prompt_tokens = [r["tokens"]["prompt_tokens"] for r in ok]
    completion_tokens = [r["tokens"]["completion_tokens"] for r in ok]
    tps = [r["tokens"]["tokens_per_sec"] for r in ok if r["tokens"]["tokens_per_sec"]]

    # Resource readings are legitimately absent on some machines: psutil not
    # installed (CPU / RAM / RSS come back None), no Ollama process found to
    # sample (RSS None), no nvidia-smi (GPU None). Collect only the real values
    # and let the reductions resolve to None over an empty list - max() over a
    # list of Nones would crash instead of reporting "not measured".
    cpu_mean = [r["resources"]["cpu_percent_mean"] for r in ok
                if r.get("resources") and r["resources"].get("cpu_percent_mean") is not None]
    cpu_peak = [r["resources"]["cpu_percent_peak"] for r in ok
                if r.get("resources") and r["resources"].get("cpu_percent_peak") is not None]
    ram_peak = [r["resources"]["process_rss_peak_mb"] for r in ok
                if r.get("resources") and r["resources"].get("process_rss_peak_mb") is not None]
    sys_ram_peak = [r["resources"]["system_ram_used_peak_mb"] for r in ok
                    if r.get("resources") and r["resources"].get("system_ram_used_peak_mb") is not None]
    gpu_util = [r["resources"]["gpu_util_mean_pct"] for r in ok
                if r.get("resources") and r["resources"].get("gpu_util_mean_pct") is not None]
    gpu_mem = [r["resources"]["gpu_mem_peak_mb"] for r in ok
               if r.get("resources") and r["resources"].get("gpu_mem_peak_mb") is not None]

    # ---- per-category rollup -------------------------------------------
    # The row above is the dataset average; this is the same question asked
    # once per assessment category, because a model can lead overall and still
    # lose an entire category - which a single overall number hides.
    #
    # Every metric states what it averaged over, and one that does not apply
    # inside a category is reported as None rather than folded in as a zero:
    # a category with no code task has no test-pass rate (n/a), it is not 0%,
    # and a category where hallucination is never measured has no hallucination
    # rate for the same reason.
    by_category: Dict[str, Dict[str, Any]] = {}
    for r in ok:
        bucket = by_category.setdefault(r["category"], {
            "n": 0, "correct": 0, "correctness": [], "relevance": [],
            "hallucination": [], "retrieval_quality": [],
            "tests_passed": 0, "tests_total": 0,
            "code_tasks_total": 0, "code_tasks_fully_passing": 0,
            "latency_ms": [], "ttft_ms": [],
            "prompt_tokens": 0, "completion_tokens": 0,
        })
        bucket["n"] += 1
        bucket["correct"] += 1 if r["correctness"]["is_correct"] else 0
        bucket["correctness"].append(r["correctness"]["correctness_pct"])
        bucket["relevance"].append(r["relevance"]["relevance_pct"])
        if r["hallucination"]["applicable"] and \
                r["hallucination"]["hallucination_rate_pct"] is not None:
            bucket["hallucination"].append(r["hallucination"]["hallucination_rate_pct"])
        retrieval = r.get("retrieval") or {}
        if retrieval.get("applicable") and retrieval.get("retrieval_quality_pct") is not None:
            bucket["retrieval_quality"].append(retrieval["retrieval_quality_pct"])
        code_result = r.get("code_eval")
        if code_result and code_result.get("tests_total"):
            bucket["tests_passed"] += code_result["tests_passed"]
            bucket["tests_total"] += code_result["tests_total"]
            bucket["code_tasks_total"] += 1
            if code_result["tests_passed"] == code_result["tests_total"]:
                bucket["code_tasks_fully_passing"] += 1
        bucket["latency_ms"].append(r["timings"]["total_ms"])
        bucket["ttft_ms"].append(r["timings"]["ttft_ms"])
        bucket["prompt_tokens"] += r["tokens"]["prompt_tokens"]
        bucket["completion_tokens"] += r["tokens"]["completion_tokens"]

    for bucket in by_category.values():
        n = bucket.pop("n")
        hallucination_n = len(bucket["hallucination"])
        retrieval_n = len(bucket["retrieval_quality"])
        tests_total = bucket["tests_total"]
        bucket["accuracy_pct"] = _pct(bucket["correct"], n)
        bucket["correctness_pct"] = _mean(bucket.pop("correctness"))
        bucket["relevance_pct"] = _mean(bucket.pop("relevance"))
        bucket["hallucination_n"] = hallucination_n
        bucket["hallucination_rate_pct"] = _mean(bucket.pop("hallucination"))
        bucket["retrieval_quality_n"] = retrieval_n
        bucket["retrieval_quality_pct"] = _mean(bucket.pop("retrieval_quality"))
        # None, not 0, when the category contained no code task.
        bucket["test_pass_rate_pct"] = _pct(bucket["tests_passed"], tests_total) if tests_total else None
        bucket["latency_ms_mean"] = _mean(bucket.pop("latency_ms"))
        bucket["ttft_ms_mean"] = _mean(bucket.pop("ttft_ms"))
        bucket["total_tokens"] = bucket.pop("prompt_tokens") + bucket.pop("completion_tokens")
        bucket["n"] = n

    tests_passed = sum(c["tests_passed"] for c in code)
    tests_total = sum(c["tests_total"] for c in code)

    base = baseline or {}

    def over_baseline(peak: Optional[float], key: str) -> Optional[float]:
        floor = base.get(key)
        if peak is None or floor is None:
            return None
        return round(max(0.0, peak - floor), 1)

    cpu_peak_value = max(cpu_peak) if cpu_peak else None
    rss_peak_value = max(ram_peak) if ram_peak else None
    sys_ram_peak_value = max(sys_ram_peak) if sys_ram_peak else None
    gpu_mem_peak_value = max(gpu_mem) if gpu_mem else None

    return {
        "model": model,
        "questions_run": len(per_question),
        "questions_ok": len(ok),
        "questions_failed": len(failed),

        # ---- QUALITY ----
        "accuracy_pct": _pct(sum(correct_flags), len(correct_flags)),
        "correctness_pct": _mean(correctness_scores),
        "correctness_n": len(correctness_scores),
        "relevance_pct": _mean(relevance_scores),
        "relevance_n": len(relevance_scores),
        "hallucination_rate_pct": _mean(halluc),
        "hallucination_n": len(halluc),
        "abstention_correct": sum(
            1 for r in ok if not r["answerable"] and r["correctness"]["abstained"]),
        "abstention_total": sum(1 for r in ok if not r["answerable"]),
        # None, not 0, when the run contained no code task: a model that was
        # never asked to write code has not scored zero at writing code.
        "test_pass_rate_pct": _pct(tests_passed, tests_total) if tests_total else None,
        "tests_passed": tests_passed,
        "tests_total": tests_total,
        "code_tasks_fully_passing": sum(1 for c in code if c["tests_total"] and c["tests_passed"] == c["tests_total"]),
        "code_tasks_total": len(code),

        # ---- PERFORMANCE: latency ----
        "ttft_ms_mean": _mean(ttft),
        "ttft_ms_median": _percentile(ttft, 50),
        "latency_ms_mean": _mean(total),
        "latency_ms_median": _percentile(total, 50),
        "latency_ms_p95": _percentile(total, 95),
        "end_to_end_ms_mean": _mean(e2e),

        # ---- PERFORMANCE: tokens ----
        "prompt_tokens_total": sum(prompt_tokens),
        "prompt_tokens_mean": _mean([float(v) for v in prompt_tokens]),
        "completion_tokens_total": sum(completion_tokens),
        "completion_tokens_mean": _mean([float(v) for v in completion_tokens]),
        "total_tokens": sum(prompt_tokens) + sum(completion_tokens),
        "tokens_per_sec_mean": _mean(tps),

        # ---- PERFORMANCE: resources ----
        "cpu_percent_mean": _mean(cpu_mean),
        "cpu_percent_peak": cpu_peak_value,
        "cpu_percent_over_baseline": over_baseline(_mean(cpu_mean), "cpu_percent"),
        "process_rss_peak_mb": rss_peak_value,
        "process_rss_over_baseline_mb": over_baseline(rss_peak_value, "ollama_rss_mb"),
        "system_ram_used_peak_mb": sys_ram_peak_value,
        "system_ram_over_baseline_mb": over_baseline(sys_ram_peak_value, "system_ram_used_mb"),
        "gpu_util_mean_pct": _mean(gpu_util),
        "gpu_mem_peak_mb": gpu_mem_peak_value,
        "gpu_mem_over_baseline_mb": over_baseline(gpu_mem_peak_value, "gpu_mem_used_mb"),

        "by_category": by_category,
    }


def aggregate_retrieval(per_question: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pipeline-level retrieval quality - identical for every model in a run."""
    scored = [r for r in per_question if r["retrieval"]["applicable"]]
    return {
        "questions_scored": len(scored),
        "questions_skipped": len(per_question) - len(scored),
        "precision_at_k_mean": _mean([r["retrieval"]["precision_at_k"] for r in scored]),
        "precision_normalised_mean": _mean([r["retrieval"]["precision_normalised_pct"] for r in scored]),
        "context_noise_mean_pct": _mean([r["retrieval"]["context_noise_pct"] for r in scored]),
        "recall_at_k_mean": _mean([r["retrieval"]["recall_at_k"] for r in scored]),
        "mrr_mean": round(statistics.fmean([r["retrieval"]["mrr"] for r in scored]), 4) if scored else None,
        "hit_rate_pct": _pct(sum(r["retrieval"]["hit_at_k"] for r in scored), len(scored)),
        "retrieval_quality_pct": _mean([r["retrieval"]["retrieval_quality_pct"] for r in scored]),
        "avg_similarity_mean": round(
            statistics.fmean([r["retrieval"]["avg_similarity"] for r in per_question]), 4
        ) if per_question else None,
        "misses": [r["id"] for r in scored if not r["retrieval"]["hit_at_k"]],
        "partial": [r["id"] for r in scored
                    if r["retrieval"]["hit_at_k"] and r["retrieval"]["recall_at_k"] < 100],
    }


# ---------------------------------------------------------------------------
# Category-wise applicability, exposed to the UI so every per-category number
# carries its calculation (or its reason for being n/a) with it
# ---------------------------------------------------------------------------

#: One entry per assessment category, stating how each metric is computed
#: inside that category and which metrics are not applicable there. The report
#: shows an n/a rather than a number wherever a metric has no measurement to
#: make - forcing one would corrupt the category averages it sits next to.
CATEGORY_METRIC_NOTES = {
    "Explanation": {
        "correctness": "fact recall against expected facts, minus forbidden-value penalty",
        "relevance": "topic coverage + on-topic sentence share",
        "hallucination": "unsupported-claim share against the retrieved context",
        "retrieval_quality": "gold pages of the explained rule vs retrieved chunks",
        "test_pass_rate": None,
        "n_a": ["test_pass_rate - no code is written in this category"],
    },
    "Code Retrieval": {
        "correctness": "fact recall: the function/value the quoted excerpt asks for",
        "relevance": "topic coverage on the quoted code's identifiers",
        "hallucination": None,
        "retrieval_quality": None,
        "test_pass_rate": None,
        "n_a": ["hallucination - the evidence is quoted in the question, so grounding "
                "claims against retrieved policy pages measures the wrong corpus",
                "retrieval_quality - no gold chunk exists: the answer lives in the "
                "question, not in the knowledge base",
                "test_pass_rate - no code is written in this category"],
    },
    "Dependency Understanding": {
        "correctness": "fact recall: each imported file / broken module named is one fact",
        "relevance": "topic coverage on the dependency's symbols",
        "hallucination": None,
        "retrieval_quality": None,
        "test_pass_rate": None,
        "n_a": ["hallucination - the imports under discussion are quoted in the question",
                "retrieval_quality - no gold chunk exists: the answer lives in the question",
                "test_pass_rate - no code is written in this category"],
    },
    "Bug Analysis": {
        "correctness": "fact recall: identifying the misclassified case and the fix",
        "relevance": "topic coverage on the buggy snippet's symbols",
        "hallucination": None,
        "retrieval_quality": None,
        "test_pass_rate": None,
        "n_a": ["hallucination - the buggy code is quoted in the question",
                "retrieval_quality - no gold chunk exists: the answer lives in the question",
                "test_pass_rate - the defect is analysed, not executed"],
    },
    "Code Generation": {
        "correctness": "the test-pass rate itself - for code, correctness IS passing the suite",
        "relevance": "topic coverage of the prose around the code (code fences excluded)",
        "hallucination": None,
        "retrieval_quality": "gold page holding the policy constants vs retrieved chunks",
        "test_pass_rate": "tests passed / tests in the fixed suite, executed via pytest",
        "n_a": ["hallucination - generated code is judged by its tests, not by grounding"],
    },
    "Refactoring": {
        "correctness": "the test-pass rate - a correct refactor is one that preserves behaviour",
        "relevance": "topic coverage of the prose around the code (code fences excluded)",
        "hallucination": None,
        "retrieval_quality": "gold page holding the policy constants vs retrieved chunks",
        "test_pass_rate": "tests passed / tests in the fixed suite, executed via pytest",
        "n_a": ["hallucination - refactored code is judged by its tests, not by grounding"],
    },
    "RAG-based Question": {
        "correctness": "fact recall against expected facts; abstention probes score on abstaining",
        "relevance": "topic coverage + on-topic sentence share; a correct abstention scores 100",
        "hallucination": "unsupported-claim share against the retrieved context; on the "
                         "out-of-scope probes any asserted fact counts as fabricated",
        "retrieval_quality": "gold (filename, page) vs retrieved chunks - not applicable on "
                             "the out-of-scope probes, where no chunk can be correct",
        "test_pass_rate": None,
        "n_a": ["test_pass_rate - no code is written in this category"],
    },
}


# ---------------------------------------------------------------------------
# Metric definitions, exposed to the UI so the page can state the formula
# ---------------------------------------------------------------------------

METRIC_DEFINITIONS: List[Dict[str, str]] = [
    {
        "group": "Quality",
        "key": "correctness_pct",
        "plain": "Did the answer actually contain the facts it was supposed to contain? Every question has a short list of facts the answer must state; we check how many of them turned up. Stating a value the documents explicitly rule out costs marks.",
        "name": "Correctness / Accuracy",
        "unit": "%",
        "better": "higher",
        "formula": "correctness = 100 x (expected facts found / expected facts) x (1 - 0.5 x share of forbidden values stated). Accuracy = share of questions scoring 70 or above. Out-of-scope probes score 100 only for abstaining; code tasks score their test-pass rate.",
    },
    {
        "group": "Quality",
        "key": "relevance_pct",
        "plain": "Did the answer stay on the subject, or wander off? We check that it uses the words belonging to this topic, and that most of its sentences are about the question rather than filler.",
        "name": "Relevance",
        "unit": "%",
        "better": "higher",
        "formula": "relevance = 0.5 x (curated topic terms present in the answer / topic terms) + 0.5 x (answer sentences mentioning a topic or retrieved-context term / sentences with 3+ content words).",
    },
    {
        "group": "Quality",
        "key": "retrieval_quality_pct",
        "plain": "Before the model writes anything, the system searches the documents and hands it a few pages. This asks whether it handed over the right pages. If it did not, no model can answer correctly - so this is the ceiling every model works under.",
        "name": "Retrieval Quality",
        "unit": "%",
        "better": "higher",
        "formula": "A chunk is relevant if its (filename, page) is the one holding the answer. score = 100 x (0.4 x normalised precision + 0.4 x recall@k + 0.2 x MRR), where normalised precision = relevant chunks / min(gold pages, k) - raw precision@k cannot exceed min(gold,k)/k however good the retriever is. Shared by all models - retrieval runs once per question.",
    },
    {
        "group": "Quality",
        "key": "hallucination_rate_pct",
        "plain": "How much of the answer was made up? Each sentence is checked against the pages the model was actually given. If the words and the numbers are not in those pages, the model invented them.",
        "name": "Hallucination Rate",
        "unit": "%",
        "better": "lower",
        "formula": "A claim is a sentence with 4+ content words. It is supported when 60%+ of its content words appear in the retrieved context AND every number it states appears in the context or question. rate = unsupported claims / claims. On out-of-scope probes any asserted fact counts as fabricated.",
    },
    {
        "group": "Quality",
        "key": "test_pass_rate_pct",
        "plain": "Does the code the model wrote actually run? We pull the code out of the answer, save it to a file, and run real unit tests against it. Nothing is judged by eye.",
        "name": "Test-Pass Rate",
        "unit": "%",
        "better": "higher",
        "formula": "Generated code is extracted from the answer, written to solution.py and run against a fixed pytest suite in a subprocess. rate = tests passed / tests executed, summed over the 6 code tasks (30 tests). A file that will not import scores 0.",
    },
    {
        "group": "Performance",
        "key": "latency_ms_mean",
        "plain": "How long you wait for an answer.",
        "name": "Response Latency",
        "unit": "ms",
        "better": "lower",
        "formula": "Wall-clock time from sending the prompt to the final token, measured after an untimed warm-up so load order does not decide the winner. Reported as mean, median, p95, plus time-to-first-token and end-to-end (retrieval + generation).",
    },
    {
        "group": "Performance",
        "key": "total_tokens",
        "plain": "How much text goes in and comes out. Tokens are roughly word-pieces; more of them means slower answers and, on a paid API, a bigger bill.",
        "name": "Token Usage",
        "unit": "tokens",
        "better": "lower",
        "formula": "prompt_eval_count + eval_count reported by Ollama per request, summed over the dataset. Counts differ between models on identical context because each has its own tokenizer.",
    },
    {
        "group": "Performance",
        "key": "gpu_mem_peak_mb",
        "plain": "How much of the machine the model occupies while it answers - processor, memory, and graphics-card memory. Measured against how busy the machine was before the run, so the number is what this model cost rather than what was already running.",
        "name": "CPU / GPU / Memory",
        "unit": "mixed",
        "better": "lower",
        "formula": "Sampled every 200 ms during each timed generation: system CPU% (psutil), the RSS of the Ollama process group including the llama-server runner that holds the weights (psutil), system RAM in use, and GPU utilisation + VRAM (nvidia-smi). Reported as mean during generation, peak across the run, and peak minus the idle baseline captured before the run - CPU, RAM and VRAM are machine-wide, so the delta is what the model itself cost.",
    },
]
