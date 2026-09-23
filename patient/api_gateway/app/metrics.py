"""Scoring for the Model Comparison page - the Week-4 criteria and nothing else.

This used to compute its own house metrics (groundedness, context utilisation,
citation counts, a weighted composite score with hand-picked weights). Those are
gone. The page now reports exactly the metrics the evaluation asks for, computed
by the same code that produces the full dataset evaluation, so a number on the
comparison page and the same number in the evaluation report cannot disagree:

  QUALITY      correctness / accuracy, relevance, retrieval quality,
               hallucination rate, test-pass rate
  PERFORMANCE  response latency, token usage, CPU / GPU / memory

A single ad-hoc question has no ground truth, so correctness, retrieval quality
and test-pass rate are only computable when the question is one of the 30 in the
evaluation dataset. The page therefore lets a run be pinned to a dataset item;
when it is not, those three come back marked not-applicable rather than filled
in with a guess. Relevance and hallucination rate need only the question and the
retrieved context, so they are always available.
"""

import os
import sys
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from evaluation import metrics as M
from evaluation.code_eval import run_code_task
from evaluation.dataset import dataset_by_id

#: Shape used when a metric cannot be computed for an ad-hoc question. Never
#: zero: "not measured" and "measured as nothing" are different claims.
NOT_APPLICABLE = {"applicable": False, "value": None}


def _ad_hoc_item(question: str) -> Dict[str, Any]:
    """A ground-truth-free stand-in for a question typed into the page.

    Topic terms fall back to the question's own content words. That makes
    relevance weaker than it is on the curated dataset - a model can score by
    echoing the question - which is why the page labels it as such.
    """
    return {
        "id": "adhoc",
        "category": "ad-hoc",
        "question": question,
        "answerable": True,
        "expected_facts": [],
        "forbidden": [],
        "topic_terms": M.content_words(question)[:8],
        "gold_sources": [],
    }


def evaluate_answer(answer: str, question: str, context: str,
                    sources: List[Dict[str, Any]],
                    dataset_id: Optional[str] = None) -> Dict[str, Any]:
    """Score one model's answer on the Week-4 quality criteria.

    `dataset_id` pins the run to an evaluation item, which is what unlocks
    correctness, retrieval quality and test-pass rate.
    """
    item = dataset_by_id().get(dataset_id) if dataset_id else None
    grounded_in_dataset = item is not None
    if item is None:
        item = _ad_hoc_item(question)

    code_result = run_code_task(answer, item["code_task"]) if "code_task" in item else None
    correctness = M.correctness(
        answer, item,
        test_pass_rate_pct=code_result["test_pass_rate_pct"] if code_result else None)
    relevance = M.relevance(answer, item, context)
    hallucination = M.hallucination(answer, context, question, item)
    retrieval = M.retrieval_quality(sources, item)

    return {
        "dataset_id": dataset_id if grounded_in_dataset else None,
        "ground_truth_available": grounded_in_dataset,

        # ---- QUALITY ----
        "correctness": {
            "applicable": grounded_in_dataset,
            "value": correctness["correctness_pct"] if grounded_in_dataset else None,
            "is_correct": correctness["is_correct"] if grounded_in_dataset else None,
            "facts_hit": correctness["facts_hit"],
            "facts_total": correctness["facts_total"],
            "forbidden_hits": correctness["forbidden_hits"],
            "abstained": correctness["abstained"],
        },
        "relevance": {
            "applicable": True,
            "value": relevance["relevance_pct"],
            "topic_coverage_pct": relevance["topic_coverage_pct"],
            "on_topic_share_pct": relevance["on_topic_share_pct"],
            "note": None if grounded_in_dataset else
                    "topic terms derived from the question itself - weaker than the dataset's curated terms",
        },
        "retrieval_quality": {
            "applicable": retrieval["applicable"],
            "value": retrieval["retrieval_quality_pct"],
            "precision_at_k": retrieval["precision_at_k"],
            "recall_at_k": retrieval["recall_at_k"],
            "mrr": retrieval["mrr"],
            "context_noise_pct": retrieval["context_noise_pct"],
            "top_similarity": retrieval["top_similarity"],
            "avg_similarity": retrieval["avg_similarity"],
            "note": retrieval["note"] or (
                None if grounded_in_dataset else
                "no gold chunk is defined for an ad-hoc question - similarity is shown instead"),
        },
        "hallucination": {
            "applicable": hallucination["applicable"],
            "value": hallucination["hallucination_rate_pct"],
            "claims_total": hallucination["claims_total"],
            "claims_unsupported": hallucination["claims_unsupported"],
            "fabricated_numbers": hallucination["fabricated_numbers"],
            "unsupported_examples": hallucination["unsupported_examples"],
        },
        "test_pass_rate": {
            "applicable": code_result is not None,
            "value": code_result["test_pass_rate_pct"] if code_result else None,
            "tests_passed": code_result["tests_passed"] if code_result else None,
            "tests_total": code_result["tests_total"] if code_result else None,
            "status": code_result["status"] if code_result else None,
            "pytest_output": code_result["pytest_output"] if code_result else None,
        },

        "answer_words": len((answer or "").split()),
    }


def summarise_run(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-criterion leaders across the models in one comparison run.

    No composite score and no overall winner: collapsing eight criteria into one
    number needs weights, and any weighting is an opinion about what matters
    rather than a measurement. The page reports who leads on each criterion and
    leaves the trade-off visible.
    """
    ok = [r for r in results if r.get("status") == "ok"]
    if not ok:
        return {"models_compared": 0, "models_failed": len(results), "leaders": {}}

    def best(path, better="higher"):
        pairs = []
        for r in ok:
            value = path(r)
            if value is None:
                continue
            pairs.append((r["model"], value))
        if not pairs:
            return None
        model, value = (max if better == "higher" else min)(pairs, key=lambda p: p[1])
        return {"model": model, "value": value,
                "ranking": sorted(pairs, key=lambda p: p[1], reverse=(better == "higher"))}

    leaders = {
        "correctness": best(lambda r: r["quality"]["correctness"]["value"], "higher"),
        "relevance": best(lambda r: r["quality"]["relevance"]["value"], "higher"),
        "hallucination": best(lambda r: r["quality"]["hallucination"]["value"], "lower"),
        "test_pass_rate": best(lambda r: r["quality"]["test_pass_rate"]["value"], "higher"),
        "latency": best(lambda r: r["timings"]["total_ms"], "lower"),
        "ttft": best(lambda r: r["timings"]["ttft_ms"], "lower"),
        "token_usage": best(lambda r: r["tokens"]["total_tokens"], "lower"),
        "cpu": best(lambda r: (r.get("resources") or {}).get("cpu_percent_mean"), "lower"),
        "gpu_memory": best(lambda r: (r.get("resources") or {}).get("gpu_mem_peak_mb"), "lower"),
        "system_memory": best(lambda r: (r.get("resources") or {}).get("system_ram_used_peak_mb"), "lower"),
    }

    return {
        "models_compared": len(ok),
        "models_failed": len(results) - len(ok),
        "leaders": {k: v for k, v in leaders.items() if v},
        "ground_truth_available": any(r["quality"]["ground_truth_available"] for r in ok),
        "note": "Retrieval runs once and is shared by every model, so retrieval quality "
                "is a property of the pipeline and is reported separately rather than "
                "credited to a model.",
    }
