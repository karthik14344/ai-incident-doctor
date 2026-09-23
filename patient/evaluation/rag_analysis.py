"""Exercise 5 - what retrieval actually did to the answer.

Builds the QUESTION -> RETRIEVED CONTEXT -> LLM RESPONSE record for every task
and labels it, so the five cases the exercise asks for stop being anecdotes:

  relevant_retrieved         the gold page came back, at or near rank 1
  irrelevant_retrieved       most of the context window went to chunks that do
                             not hold the answer, or none of it did
  information_missed         gold pages exist that top_k never reached
  answered_correctly         the model got it right from that context
  hallucinated_with_context  the model invented something anyway, with the
                             correct page sitting in its prompt

The last label is the one that matters: it separates "RAG failed" from "the
model failed despite RAG working", and those need completely different fixes.
The final section groups questions into retrieval-quality bands and reports the
mean answer quality in each, which is the RETRIEVAL -> CONTEXT -> RESPONSE
relationship stated as a number instead of an assertion.
"""

from typing import Any, Dict, List

#: A retrieval is "noisy" once this much of the context window holds chunks
#: that cannot answer the question.
NOISE_THRESHOLD_PCT = 60.0

#: Phrases that mark a retrieved chunk as containing instructions addressed to
#: the assistant rather than facts to answer from.
#:
#: `welcome_guide.txt` is a greeting *protocol* - "When a user says 'hi',
#: respond with 'Hello! Welcome to KnowledgeAI...'". Retrieval cannot tell
#: "content to answer from" apart from "instructions to obey", so when that
#: chunk surfaces for an unrelated question the models follow it and answer the
#: instruction instead of the user. Every model in the run did exactly that on
#: Q22. It is not hallucination and not a retrieval miss; it is a corpus design
#: defect, and it needs its own label or it gets misattributed to the model.
INSTRUCTION_MARKERS = (
    "respond with", "greeting protocol", "when a user says",
    "offer assistance", "instruction:", "you should reply",
)

#: A response whose topic coverage is at or below this, on a question whose
#: context carried assistant instructions, is answering the instruction.
INSTRUCTION_FOLLOWED_TOPIC_PCT = 25.0

#: Bands used for the retrieval-quality -> response-quality table.
BANDS = [
    ("strong (>= 80)", 80.0, 100.01),
    ("partial (50-79)", 50.0, 80.0),
    ("weak (< 50)", -0.01, 50.0),
]


def _context_preview(context: str, limit: int = 700) -> str:
    if len(context) <= limit:
        return context
    return context[:limit] + f"\n... [{len(context) - limit} more characters]"


def build_traces(retrieval_records: List[Dict[str, Any]],
                 per_model: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """One trace per question, plus the roll-ups the exercise asks for."""
    by_model_by_id = {
        model: {r["id"]: r for r in records} for model, records in per_model.items()
    }

    traces: List[Dict[str, Any]] = []
    buckets: Dict[str, List[Any]] = {
        "relevant_retrieved": [],
        "irrelevant_retrieved": [],
        "information_missed": [],
        "answered_correctly": [],
        "hallucinated_with_context": [],
        "instruction_leak": [],
    }

    for record in retrieval_records:
        rq = record["retrieval"]
        labels: List[str] = []

        # Did retrieval hand the model instructions instead of facts?
        context_lower = (record.get("context") or "").lower()
        instructive = [m for m in INSTRUCTION_MARKERS if m in context_lower]
        # Keyed on the internal task shape, not the visible category label: the
        # greeting task's seven-category label is "RAG-based Question", but the
        # instruction-leak logic cares about the shape (a canned welcome has no
        # instruction to leak into).
        is_greeting_task = record.get("task_type") == "greeting"

        if rq["applicable"]:
            if rq["hit_at_k"]:
                labels.append("relevant_retrieved")
                buckets["relevant_retrieved"].append(record["id"])
            if not rq["hit_at_k"] or rq["context_noise_pct"] >= NOISE_THRESHOLD_PCT:
                labels.append("irrelevant_retrieved")
                buckets["irrelevant_retrieved"].append(record["id"])
            if rq["recall_at_k"] < 100:
                labels.append("information_missed")
                buckets["information_missed"].append(record["id"])
        else:
            # No gold chunk exists. Retrieval still returned four chunks with
            # real similarity scores - that is precisely the trap.
            labels.append("irrelevant_retrieved")
            buckets["irrelevant_retrieved"].append(record["id"])

        responses = []
        for model, records_by_id in by_model_by_id.items():
            answer_record = records_by_id.get(record["id"])
            if not answer_record or answer_record.get("status") != "ok":
                responses.append({
                    "model": model, "status": "error",
                    "error": (answer_record or {}).get("error", "not run"),
                })
                continue

            correct = answer_record["correctness"]["is_correct"]
            halluc = answer_record["hallucination"]
            hallucinated = bool(halluc["applicable"] and (halluc["hallucination_rate_pct"] or 0) > 0)

            if correct:
                buckets["answered_correctly"].append({"id": record["id"], "model": model})
            if hallucinated and rq.get("hit_at_k"):
                buckets["hallucinated_with_context"].append({
                    "id": record["id"], "model": model,
                    "rate_pct": halluc["hallucination_rate_pct"],
                    "fabricated_numbers": halluc["fabricated_numbers"],
                })

            topic_pct = answer_record["relevance"].get("topic_coverage_pct")
            followed_instruction = bool(
                instructive and not is_greeting_task and not correct
                and topic_pct is not None and topic_pct <= INSTRUCTION_FOLLOWED_TOPIC_PCT)
            if followed_instruction:
                buckets["instruction_leak"].append({
                    "id": record["id"], "model": model,
                    "markers": instructive, "topic_coverage_pct": topic_pct,
                })

            responses.append({
                "model": model,
                "status": "ok",
                "answer": answer_record["answer"],
                "correctness_pct": answer_record["correctness"]["correctness_pct"],
                "is_correct": correct,
                "relevance_pct": answer_record["relevance"]["relevance_pct"],
                "topic_coverage_pct": topic_pct,
                "followed_context_instruction": followed_instruction,
                "hallucination_rate_pct": halluc["hallucination_rate_pct"],
                "fabricated_numbers": halluc["fabricated_numbers"],
                "unsupported_examples": halluc["unsupported_examples"],
                "abstained": answer_record["correctness"].get("abstained", False),
                "verdict": _verdict(rq, correct, hallucinated,
                                    answer_record["correctness"].get("abstained", False),
                                    record["answerable"]),
            })

        traces.append({
            "id": record["id"],
            "category": record["category"],
            "question": record["question"],
            "answerable": record["answerable"],
            "gold_sources": record["gold_sources"],
            "retrieved_sources": [
                {"filename": s["filename"], "page": s["page"],
                 "similarity": s["similarity"],
                 "relevant": f"{s['filename']} p{s['page']}" in record["gold_sources"],
                 "preview": s["text"]}
                for s in record["sources"]
            ],
            "context_preview": _context_preview(record["context"]),
            "context_chars": record["context_chars"],
            "retrieval": rq,
            "labels": labels,
            "instruction_markers_in_context": instructive,
            "responses": responses,
        })

    return {
        "traces": traces,
        "buckets": {k: v for k, v in buckets.items()},
        "counts": {k: len(v) for k, v in buckets.items()},
        "retrieval_to_response": _band_table(traces),
        "highlights": _highlights(traces),
        "conclusion": _conclusion(traces, buckets),
    }


def _verdict(rq: Dict[str, Any], correct: bool, hallucinated: bool,
             abstained: bool, answerable: bool) -> str:
    """A one-phrase reading of this question-model pair, for the trace table."""
    if not answerable:
        return "correctly abstained" if abstained else "answered an unanswerable question"
    if not rq.get("hit_at_k"):
        return "retrieval failed - model had nothing to work with"
    if correct and not hallucinated:
        return "retrieval worked, model used it"
    if correct and hallucinated:
        return "right answer, but padded with unsupported detail"
    if hallucinated:
        return "hallucinated despite correct context"
    return "context was correct, model still missed the answer"


def _band_table(traces: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """RETRIEVAL QUALITY -> CONTEXT QUALITY -> RESPONSE QUALITY, as a table.

    Groups questions by how well retrieval did, then averages what the models
    produced in each group. If retrieval quality did not matter, the rows would
    be flat.
    """
    rows = []
    for label, low, high in BANDS:
        in_band = [t for t in traces
                   if t["retrieval"]["applicable"]
                   and low <= (t["retrieval"]["retrieval_quality_pct"] or 0) < high]
        answers = [r for t in in_band for r in t["responses"] if r["status"] == "ok"]
        if not in_band:
            rows.append({"band": label, "questions": 0, "question_ids": [],
                         "answers_scored": 0, "mean_correctness_pct": None,
                         "accuracy_pct": None, "mean_hallucination_pct": None})
            continue
        halluc = [r["hallucination_rate_pct"] for r in answers
                  if r["hallucination_rate_pct"] is not None]
        rows.append({
            "band": label,
            "questions": len(in_band),
            "question_ids": [t["id"] for t in in_band],
            "answers_scored": len(answers),
            "mean_correctness_pct": round(
                sum(r["correctness_pct"] for r in answers) / len(answers), 1) if answers else None,
            "accuracy_pct": round(
                100.0 * sum(1 for r in answers if r["is_correct"]) / len(answers), 1) if answers else None,
            "mean_hallucination_pct": round(sum(halluc) / len(halluc), 1) if halluc else None,
        })

    # The out-of-scope probes get their own row: retrieval quality is undefined
    # there, but they are the sharpest test of what a model does with context
    # that looks relevant and is not.
    probes = [t for t in traces if not t["retrieval"]["applicable"]]
    if probes:
        answers = [r for t in probes for r in t["responses"] if r["status"] == "ok"]
        rows.append({
            "band": "no gold chunk exists (out-of-scope probes)",
            "questions": len(probes),
            "question_ids": [t["id"] for t in probes],
            "answers_scored": len(answers),
            "mean_correctness_pct": round(
                sum(r["correctness_pct"] for r in answers) / len(answers), 1) if answers else None,
            "accuracy_pct": round(
                100.0 * sum(1 for r in answers if r["is_correct"]) / len(answers), 1) if answers else None,
            "mean_hallucination_pct": round(
                sum(r["hallucination_rate_pct"] for r in answers
                    if r["hallucination_rate_pct"] is not None) / max(1, len(answers)), 1) if answers else None,
        })
    return rows


def _highlights(traces: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One worked example of each case, chosen to be the clearest one.

    Picked by score rather than by whichever question happens to come first.
    Every single-gold question at k=4 is technically 75% noise, so a
    first-match rule would illustrate "irrelevant information was retrieved"
    with a question the models all answered correctly - true, and useless as an
    example. The scores below select the case that actually shows the failure.
    """

    def ok_responses(trace):
        return [r for r in trace["responses"] if r["status"] == "ok"]

    def worked(trace, response, why) -> Dict[str, Any]:
        return {
            "id": trace["id"],
            "why": why,
            "question": trace["question"],
            "retrieved": [f"{s['filename']} p{s['page']} (sim {s['similarity']}"
                          f"{', GOLD' if s['relevant'] else ''})"
                          for s in trace["retrieved_sources"]],
            "context_preview": trace["context_preview"],
            "model": response["model"] if response else None,
            "answer": response["answer"] if response else None,
            "retrieval_quality_pct": trace["retrieval"].get("retrieval_quality_pct"),
            "hallucination_rate_pct": response.get("hallucination_rate_pct") if response else None,
            "fabricated_numbers": response.get("fabricated_numbers") if response else None,
        }

    def best(candidates, key):
        """Highest-scoring candidate, or None when nothing qualified."""
        scored = [c for c in candidates if c is not None]
        return max(scored, key=key) if scored else None

    # --- relevant information retrieved: gold at rank 1 and a model used it ---
    relevant = best(
        [t for t in traces
         if t["retrieval"].get("mrr") == 1.0
         and any(r["is_correct"] for r in ok_responses(t))],
        key=lambda t: (t["retrieval"].get("recall_at_k") or 0,
                       sum(1 for r in ok_responses(t) if r["is_correct"])))

    # --- irrelevant information retrieved: prefer the out-of-scope probes,
    # where nothing retrieved could possibly answer, then the noisiest. ---
    irrelevant = best(
        [t for t in traces
         if not t["retrieval"]["applicable"]
         or (t["retrieval"].get("context_noise_pct") or 0) >= NOISE_THRESHOLD_PCT],
        key=lambda t: (0 if t["retrieval"]["applicable"] else 1,
                       t["retrieval"].get("context_noise_pct") or 100,
                       max((r["hallucination_rate_pct"] or 0)
                           for r in ok_responses(t)) if ok_responses(t) else 0))

    # --- important information missed: the worst recall shortfall ---
    missed = best(
        [t for t in traces
         if t["retrieval"]["applicable"] and t["retrieval"]["recall_at_k"] < 100],
        key=lambda t: 100 - t["retrieval"]["recall_at_k"])

    # --- a correct answer with every claim traceable ---
    answered = best(
        [t for t in traces
         if any(r["is_correct"] and not r["hallucination_rate_pct"] for r in ok_responses(t))],
        key=lambda t: sum(1 for r in ok_responses(t)
                          if r["is_correct"] and not r["hallucination_rate_pct"]))

    # --- hallucinated anyway: the worst offender that had the right page ---
    hallucinated = best(
        [t for t in traces
         if t["retrieval"].get("hit_at_k")
         and any((r["hallucination_rate_pct"] or 0) > 0 for r in ok_responses(t))],
        key=lambda t: (max((r["hallucination_rate_pct"] or 0) for r in ok_responses(t)),
                       max(len(r.get("fabricated_numbers") or []) for r in ok_responses(t))))

    def worst_response(trace):
        return max((r for r in ok_responses(trace)), default=None,
                   key=lambda r: r["hallucination_rate_pct"] or 0)

    return {
        "relevant_information_retrieved": relevant and worked(
            relevant, next((r for r in ok_responses(relevant) if r["is_correct"]), None),
            "the gold page came back at rank 1 and the model used it"),

        "irrelevant_information_retrieved": irrelevant and worked(
            irrelevant, worst_response(irrelevant),
            (f"{irrelevant['retrieval']['context_noise_pct']}% of the retrieved context "
             "could not answer the question")
            if irrelevant["retrieval"]["applicable"] else
            ("no chunk in the corpus can answer this, yet retrieval still returned four "
             f"topically adjacent ones at up to {irrelevant['retrieval']['top_similarity']} "
             "similarity")),

        "important_information_missed": missed and worked(
            missed, worst_response(missed),
            f"only {missed['retrieval']['recall_at_k']}% of the pages holding the answer fit "
            f"in top_k - {len(missed['gold_sources'])} gold pages, "
            f"{len(missed['retrieved_sources'])} slots"),

        "llm_answered_correctly": answered and worked(
            answered, next((r for r in ok_responses(answered)
                            if r["is_correct"] and not r["hallucination_rate_pct"]), None),
            "correct, and every claim traceable to the retrieved context"),

        "llm_hallucinated_with_context": hallucinated and worked(
            hallucinated, worst_response(hallucinated),
            "the correct page was in the prompt and the model still asserted something "
            "the context does not say"),
    }


def _conclusion(traces: List[Dict[str, Any]], buckets: Dict[str, List[Any]]) -> List[str]:
    """What the traces show, in sentences, with the counts behind them."""
    scored = [t for t in traces if t["retrieval"]["applicable"]]
    hits = sum(1 for t in scored if t["retrieval"]["hit_at_k"])
    answers = [r for t in traces for r in t["responses"] if r["status"] == "ok"]
    correct = sum(1 for r in answers if r["is_correct"])
    hallucinated_with_good_context = len(buckets["hallucinated_with_context"])

    lines = [
        f"Retrieval put a page that genuinely holds the answer into the prompt on "
        f"{hits} of {len(scored)} scorable questions.",
        f"Across every model, {correct} of {len(answers)} answers were correct - so "
        f"{len(answers) - correct} failure(s) happened with the answer sitting in the context.",
    ]
    if hallucinated_with_good_context:
        lines.append(
            f"{hallucinated_with_good_context} answer(s) contained claims the context does not "
            "support even though the correct page was retrieved. RAG is not a guarantee: it "
            "changes what the model can know, not what it chooses to say.")
    missed = buckets["information_missed"]
    if missed:
        lines.append(
            f"On {len(set(missed))} question(s) ({', '.join(sorted(set(missed)))}) the gold pages "
            "outnumbered the top_k budget, so part of the answer could never reach any model. "
            "Raising top_k fixes those and costs prompt tokens on every other question.")
    leaks = buckets["instruction_leak"]
    if leaks:
        by_question = sorted({entry["id"] for entry in leaks})
        models_affected = sorted({entry["model"] for entry in leaks})
        lines.append(
            f"On {len(by_question)} question(s) ({', '.join(by_question)}) the retrieved context "
            f"contained instructions written for the assistant rather than facts, and "
            f"{len(models_affected)} model(s) ({', '.join(models_affected)}) followed them instead "
            "of answering. welcome_guide.txt is a greeting protocol - it tells the assistant what "
            "to say - and similarity search cannot tell 'content to answer from' apart from "
            "'instructions to obey'. This is neither hallucination nor a retrieval miss: it is a "
            "corpus that should never have had a prompt-instruction document indexed beside its "
            "policy documents.")

    noisy = set(buckets["irrelevant_retrieved"])
    if noisy:
        lines.append(
            f"{len(noisy)} question(s) filled most of the context window with chunks that cannot "
            "answer them. The out-of-scope probes are the extreme case: retrieval returns four "
            "confident, topically adjacent chunks and none of them contains the answer, which is "
            "exactly where a model either abstains or invents.")
    return lines
