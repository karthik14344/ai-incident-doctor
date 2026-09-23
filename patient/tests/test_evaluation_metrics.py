"""The evaluation harness scores models, so its own scoring has to be right.

A silent bug here does not crash anything - it produces a plausible number that
ranks the wrong model first, and nothing downstream can tell. These tests pin
the behaviour that the whole comparison rests on: what counts as a fact hit,
what counts as a hallucination, and when a metric refuses to produce a number
rather than guessing one.

Nothing here touches Ollama or ChromaDB. Metrics are pure functions of text.
"""

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from evaluation import metrics as M
from evaluation.code_eval import extract_code, run_code_task
from evaluation.corpus import POLICY_CORPUS, corpus_units
from evaluation.dataset import EVAL_DATASET, dataset_by_id


CONTEXT = (
    "[Source 1: attendance_policy.pdf - Page 1 | Similarity: 0.82]\n"
    "UNIVERSITY ATTENDANCE POLICY (2026-2027)\n\n"
    "Students are required to maintain a minimum attendance of 75% in each registered "
    "course to be eligible to sit for semester examinations. Attendance will be "
    "calculated from the first day of the academic session."
)


def item(qid):
    return dataset_by_id()[qid]


# ---------------------------------------------------------------------------
# Dataset integrity - the labels the whole evaluation is measured against
# ---------------------------------------------------------------------------

def test_dataset_is_within_the_required_size_range():
    # The upper bound grew when the seven assessment categories were filled in:
    # four categories had no questions at all, and each needed at least three.
    assert 20 <= len(EVAL_DATASET) <= 50


def test_every_task_has_a_unique_id():
    ids = [i["id"] for i in EVAL_DATASET]
    assert len(ids) == len(set(ids))


def test_every_task_is_labelled_with_exactly_one_of_the_seven_categories():
    """The comparison is reported per category, so a question outside the fixed
    set - or a second spelling of a category - would split a category's numbers
    in two without anything looking wrong."""
    from evaluation.dataset import CATEGORY_SET

    for task in EVAL_DATASET:
        assert task["category"] in CATEGORY_SET, \
            f"{task['id']} carries category '{task['category']}', which is not one of the seven"
        assert isinstance(task["category"], str)


def test_all_seven_categories_are_actually_represented():
    from evaluation.dataset import CATEGORY_ORDER, category_counts

    counts = category_counts()
    for category in CATEGORY_ORDER:
        assert counts.get(category, 0) >= 3, \
            f"category '{category}' is under-represented: {counts.get(category, 0)} questions"


def test_every_task_declares_a_known_task_type():
    from evaluation.dataset import TASK_TYPES

    for task in EVAL_DATASET:
        assert task["task_type"] in TASK_TYPES, \
            f"{task['id']} carries unknown task_type '{task['task_type']}'"


def test_code_snippet_tasks_carry_no_gold_pages():
    """Their evidence is quoted in the question, so retrieval quality is not
    applicable - labelling a gold page would make it measurable, and wrong."""
    for task in EVAL_DATASET:
        if task["task_type"] == "code-snippet":
            assert not task["gold_sources"], \
                f"{task['id']} quotes its evidence but still names gold pages"


def test_refactoring_tasks_are_scored_like_code_generation():
    for task in EVAL_DATASET:
        if task["category"] == "Refactoring":
            assert "code_task" in task, f"{task['id']} has no pytest suite to score behaviour"
            assert task["code_task"]["tests"].count("def test_") > 0


def test_gold_sources_all_point_at_pages_that_exist():
    """A typo in a gold label silently caps retrieval quality at zero for that
    question, and nothing else would ever report it."""
    universe = set(corpus_units())
    for task in EVAL_DATASET:
        for unit in task["gold_sources"]:
            assert unit in universe, f"{task['id']} references a page that is not in the corpus: {unit}"


def test_out_of_scope_probes_have_no_gold_and_no_expected_facts():
    for task in EVAL_DATASET:
        if task["answerable"]:
            continue
        assert not task["gold_sources"], f"{task['id']} is unanswerable but names gold pages"
        assert not task["expected_facts"], f"{task['id']} is unanswerable but expects facts"


def test_out_of_scope_answers_are_genuinely_absent_from_the_corpus():
    """The probes only measure hallucination if the corpus really cannot answer
    them. Adding a document that mentions tuition fees would turn Q21 from a
    hallucination probe into a question every model 'fails' by answering it."""
    corpus_text = " ".join(page["text"].lower()
                           for doc in POLICY_CORPUS for page in doc["pages"])
    for phrase in ("tuition fee", "menu for", "books can", "borrow up to"):
        assert phrase not in corpus_text


def test_answerable_tasks_declare_both_facts_and_gold_pages():
    """Knowledge-base questions are scored against pages that hold the answer.
    Greetings aside, the only answerable tasks exempt from gold pages are the
    self-contained code ones - their evidence is quoted in the question."""
    for task in EVAL_DATASET:
        if not task["answerable"] or task["task_type"] in ("greeting", "code-snippet"):
            continue
        assert task["expected_facts"], f"{task['id']} has no expected facts"
        assert task["gold_sources"], f"{task['id']} has no gold pages"


# ---------------------------------------------------------------------------
# Correctness
# ---------------------------------------------------------------------------

def test_correctness_credits_an_alias_of_the_expected_fact():
    exact = M.correctness("The minimum is 75%.", item("Q01"))
    spelled = M.correctness("Students need seventy-five percent attendance.", item("Q01"))
    assert exact["correctness_pct"] == 100.0
    assert spelled["correctness_pct"] == 100.0


def test_correctness_sees_through_markdown_and_spaced_percent_signs():
    assert M.correctness("The minimum is **75 %**.", item("Q01"))["correctness_pct"] == 100.0


def test_a_forbidden_value_halves_the_score_rather_than_zeroing_it():
    """Quoting the condonation floor alongside the right minimum is partly
    right, not a total failure - the penalty has to be proportionate."""
    clean = M.correctness("The minimum is 75%.", item("Q01"))
    muddled = M.correctness("The minimum is 75%, or 65% with condonation.", item("Q01"))
    assert muddled["correctness_pct"] < clean["correctness_pct"]
    assert muddled["correctness_pct"] > 0


def test_partial_fact_recall_scores_partially():
    result = M.correctness("Mid-semester carries 30% weightage.", item("Q11"))
    assert 0 < result["correctness_pct"] < 100


def test_out_of_scope_probe_scores_full_marks_only_for_abstaining():
    abstained = M.correctness(
        "The provided documents do not contain the tuition fee.", item("Q21"))
    invented = M.correctness("The annual tuition fee is Rs. 1,20,000.", item("Q21"))
    assert abstained["correctness_pct"] == 100.0 and abstained["is_correct"]
    assert invented["correctness_pct"] == 0.0 and not invented["is_correct"]


def test_code_task_correctness_is_its_test_pass_rate():
    result = M.correctness("```python\ndef is_exam_eligible(a): return a >= 75\n```",
                           item("Q25"), test_pass_rate_pct=80.0)
    assert result["mode"] == "test-pass-rate"
    assert result["correctness_pct"] == 80.0


# ---------------------------------------------------------------------------
# Relevance
# ---------------------------------------------------------------------------

def test_relevance_rewards_an_answer_that_addresses_the_topic():
    on_topic = M.relevance(
        "The minimum attendance required to be eligible for semester examinations is 75%.",
        item("Q01"), CONTEXT)
    off_topic = M.relevance(
        "Hostel gates close at 10:00 PM and visitors are allowed until 7 PM.",
        item("Q01"), CONTEXT)
    assert on_topic["relevance_pct"] > off_topic["relevance_pct"]


def test_a_correct_abstention_is_maximally_relevant():
    """Abstaining mentions almost none of the topic terms, so the raw formula
    would punish exactly the behaviour we want on an unanswerable question."""
    result = M.relevance("The documents do not contain that information.",
                         item("Q21"), CONTEXT)
    assert result["relevance_pct"] == 100.0


def test_relevance_ignores_fenced_code():
    """Code is judged by its tests; letting it into the prose metrics would
    reward whichever model emits the most identifiers."""
    with_code = M.relevance(
        "Here is the function.\n```python\ndef attendance_examination_eligible(): pass\n```",
        item("Q25"), CONTEXT)
    assert with_code["topic_coverage_pct"] < 100.0


# ---------------------------------------------------------------------------
# Hallucination
# ---------------------------------------------------------------------------

def test_a_grounded_answer_has_no_hallucination():
    result = M.hallucination(
        "Students must maintain a minimum attendance of 75% in each registered course "
        "to be eligible to sit for semester examinations.",
        CONTEXT, item("Q01")["question"], item("Q01"))
    assert result["hallucination_rate_pct"] == 0.0


def test_an_invented_number_is_caught_even_in_fluent_wording():
    """This is the failure mode that matters: a well-phrased sentence quoting a
    number the documents never stated."""
    result = M.hallucination(
        "Students are required to maintain a minimum attendance of 85% in each "
        "registered course to be eligible to sit for semester examinations.",
        CONTEXT, item("Q01")["question"], item("Q01"))
    assert result["hallucination_rate_pct"] > 0
    assert "85" in result["fabricated_numbers"]


def test_numbers_taken_from_the_question_are_not_fabrications():
    """Restating "you have 68%" is quoting the user, not inventing a policy."""
    result = M.hallucination(
        "With 68% attendance you fall below the minimum attendance of 75% required "
        "to be eligible to sit for semester examinations.",
        CONTEXT, "A student has 68% attendance. Are they eligible?", item("Q01"))
    assert "68" not in result["fabricated_numbers"]


def test_any_asserted_fact_on_an_out_of_scope_probe_is_a_fabrication():
    result = M.hallucination(
        "The annual tuition fee for the B.Tech programme is Rs. 1,20,000 payable "
        "in two instalments each academic year.",
        CONTEXT, item("Q21")["question"], item("Q21"))
    assert result["hallucination_rate_pct"] == 100.0


def test_abstaining_then_summarising_real_content_is_not_a_fabrication():
    result = M.hallucination(
        "That is not mentioned in the documents. The attendance policy does state that "
        "students must maintain a minimum attendance of 75% to be eligible to sit for "
        "semester examinations.",
        CONTEXT, item("Q21")["question"], item("Q21"))
    assert result["hallucination_rate_pct"] < 100.0


def test_a_pure_refusal_is_not_itself_a_hallucinated_claim():
    """A refusal is a statement ABOUT the context, not a claim drawn from it.
    Checking it for grounding punished the exact behaviour the out-of-scope
    probes exist to reward - mistral declined correctly on Q23 and scored 100%.
    """
    result = M.hallucination(
        "The provided documents do not contain information about the number of books "
        "a student can borrow from the central library at one time.",
        CONTEXT, item("Q23")["question"], item("Q23"))
    assert result["claims_total"] == 0
    assert result["hallucination_rate_pct"] == 0.0


def test_a_refusal_followed_by_an_invention_is_still_caught():
    """Excluding refusal sentences must not become a way to smuggle a fabricated
    fact past the metric by prefixing it with a disclaimer."""
    result = M.hallucination(
        "I could not find that in the documents. However, students may borrow up to "
        "seven books from the central library at any one time.",
        CONTEXT, item("Q23")["question"], item("Q23"))
    assert result["claims_total"] >= 1
    assert result["hallucination_rate_pct"] > 0


def test_hallucination_is_not_measured_for_greetings_or_code():
    # Q24 greeting · Q25 code generation · Q31 a self-contained code excerpt
    for qid in ("Q24", "Q25", "Q31"):
        result = M.hallucination("anything at all here", CONTEXT,
                                 item(qid)["question"], item(qid))
        assert result["applicable"] is False
        assert result["hallucination_rate_pct"] is None


# ---------------------------------------------------------------------------
# Retrieval quality
# ---------------------------------------------------------------------------

def sources(*pairs):
    return [{"filename": f, "page": p, "similarity": 0.8 - 0.05 * i}
            for i, (f, p) in enumerate(pairs)]


def test_gold_chunk_at_rank_one_scores_full_marks():
    result = M.retrieval_quality(
        sources(("attendance_policy.pdf", 1), ("exam_policy.pdf", 1),
                ("hostel_rules.pdf", 1), ("lab_safety.pdf", 1)),
        item("Q01"))
    assert result["hit_at_k"] == 1
    assert result["mrr"] == 1.0
    assert result["recall_at_k"] == 100.0


def test_raw_precision_reports_the_noise_the_normalised_figure_hides():
    """One gold page and four slots means 75% of the context cannot answer the
    question however good the retriever is. Both numbers are reported because
    they say different things."""
    result = M.retrieval_quality(
        sources(("attendance_policy.pdf", 1), ("exam_policy.pdf", 1),
                ("hostel_rules.pdf", 1), ("lab_safety.pdf", 1)),
        item("Q01"))
    assert result["precision_at_k"] == 25.0
    assert result["precision_normalised_pct"] == 100.0
    assert result["context_noise_pct"] == 75.0


def test_a_lower_ranked_gold_chunk_lowers_mrr():
    result = M.retrieval_quality(
        sources(("exam_policy.pdf", 1), ("hostel_rules.pdf", 1),
                ("attendance_policy.pdf", 1), ("lab_safety.pdf", 1)),
        item("Q01"))
    assert result["mrr"] == pytest.approx(1 / 3, abs=0.001)


def test_missing_the_gold_chunk_entirely_scores_zero():
    result = M.retrieval_quality(
        sources(("hostel_rules.pdf", 1), ("lab_safety.pdf", 1)), item("Q01"))
    assert result["hit_at_k"] == 0
    assert result["retrieval_quality_pct"] == 0.0


def test_retrieval_quality_is_not_applicable_without_gold_chunks():
    """Scoring an out-of-scope probe 0 would blame retrieval for a question no
    chunk can answer, and drag the pipeline average down for doing nothing wrong."""
    result = M.retrieval_quality(sources(("hostel_rules.pdf", 2)), item("Q22"))
    assert result["applicable"] is False
    assert result["retrieval_quality_pct"] is None
    assert result["top_similarity"] > 0


def test_recall_is_capped_when_gold_pages_outnumber_top_k():
    """Q02 exists to make this case measurable: six gold pages, four slots."""
    task = item("Q02")
    assert len(task["gold_sources"]) > 4
    result = M.retrieval_quality(sources(*task["gold_sources"][:4]), task)
    assert result["recall_at_k"] < 100.0


# ---------------------------------------------------------------------------
# Code evaluation
# ---------------------------------------------------------------------------

def test_extracts_code_from_a_fenced_block():
    code = extract_code("Here you go:\n```python\ndef f():\n    return 1\n```\nHope that helps.")
    assert code.strip() == "def f():\n    return 1"


def test_extracts_bare_code_by_dropping_the_preamble():
    code = extract_code("Sure! Here is the function:\ndef f():\n    return 1")
    assert code.startswith("def f()")


def test_prose_with_no_code_extracts_nothing():
    assert extract_code("Students need good attendance to sit the examination.") is None


def test_a_correct_solution_passes_every_test():
    result = run_code_task(
        "```python\ndef is_exam_eligible(attendance_percent):\n"
        "    return attendance_percent >= 75\n```",
        item("Q25")["code_task"])
    assert result["tests_passed"] == result["tests_total"]
    assert result["status"] == "pass"


def test_an_off_by_one_solution_scores_partially():
    result = run_code_task(
        "```python\ndef is_exam_eligible(attendance_percent):\n"
        "    return attendance_percent > 75\n```",
        item("Q25")["code_task"])
    assert 0 < result["tests_passed"] < result["tests_total"]


def test_an_answer_with_no_code_scores_zero_out_of_the_full_suite():
    """The denominator must be the suite size, not what pytest could collect -
    otherwise a broken answer scores 0/0 and vanishes from the average."""
    result = run_code_task("I am not able to write that function.",
                           item("Q25")["code_task"])
    assert result["tests_passed"] == 0
    assert result["tests_total"] == item("Q25")["code_task"]["tests"].count("def test_")


def test_code_that_will_not_import_scores_zero_rather_than_crashing():
    result = run_code_task("```python\ndef is_exam_eligible(a)\n    return a >= 75\n```",
                           item("Q25")["code_task"])
    assert result["tests_passed"] == 0
    assert result["test_pass_rate_pct"] == 0.0


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def build_record(qid, correct, halluc, latency=1000.0, tokens=100):
    task = item(qid)
    return {
        "id": qid, "category": task["category"], "question": task["question"],
        "answerable": task["answerable"], "model": "m", "status": "ok",
        "retrieval": {"applicable": True, "hit_at_k": 1, "recall_at_k": 100.0,
                      "precision_at_k": 25.0, "precision_normalised_pct": 100.0,
                      "mrr": 1.0, "retrieval_quality_pct": 100.0,
                      "context_noise_pct": 75.0, "avg_similarity": 0.6},
        "timings": {"ttft_ms": 100.0, "total_ms": latency, "end_to_end_ms": latency + 50},
        "tokens": {"prompt_tokens": tokens, "completion_tokens": tokens,
                   "total_tokens": tokens * 2, "tokens_per_sec": 20.0},
        "resources": {"cpu_percent_mean": 10.0, "cpu_percent_peak": 20.0,
                      "process_rss_peak_mb": 500.0, "system_ram_used_peak_mb": 9000.0,
                      "gpu_util_mean_pct": 40.0, "gpu_mem_peak_mb": 4000.0},
        "correctness": {"correctness_pct": 100.0 if correct else 0.0,
                        "is_correct": correct, "abstained": False},
        "relevance": {"relevance_pct": 80.0},
        "hallucination": {"applicable": halluc is not None,
                          "hallucination_rate_pct": halluc},
        "code_eval": None,
    }


def test_accuracy_is_the_share_of_questions_marked_correct():
    records = [build_record("Q01", True, 0.0), build_record("Q03", False, 50.0),
               build_record("Q04", True, 0.0), build_record("Q05", True, 0.0)]
    aggregate = M.aggregate_model("m", records)
    assert aggregate["accuracy_pct"] == 75.0


def test_hallucination_average_excludes_questions_where_it_does_not_apply():
    """Averaging a None as zero would reward a model for the questions where
    hallucination was never measured."""
    records = [build_record("Q01", True, 40.0), build_record("Q24", True, None)]
    aggregate = M.aggregate_model("m", records)
    assert aggregate["hallucination_rate_pct"] == 40.0
    assert aggregate["hallucination_n"] == 1


def test_test_pass_rate_is_none_when_no_code_task_ran():
    aggregate = M.aggregate_model("m", [build_record("Q01", True, 0.0)])
    assert aggregate["test_pass_rate_pct"] is None


def test_failed_generations_are_excluded_from_the_averages_and_counted():
    records = [build_record("Q01", True, 0.0),
               {"id": "Q03", "category": "factual-lookup", "model": "m",
                "status": "error", "error": "boom"}]
    aggregate = M.aggregate_model("m", records)
    assert aggregate["questions_failed"] == 1
    assert aggregate["accuracy_pct"] == 100.0
    assert aggregate["questions_ok"] == 1


# ---------------------------------------------------------------------------
# Category-wise aggregation
# ---------------------------------------------------------------------------

def test_category_rollup_breaks_accuracy_down_per_category():
    records = [build_record("Q01", True, 0.0),     # RAG-based Question
               build_record("Q11", False, 10.0),   # Explanation
               build_record("Q12", True, 10.0)]    # Explanation too
    aggregate = M.aggregate_model("m", records)
    assert aggregate["by_category"]["RAG-based Question"]["accuracy_pct"] == 100.0
    explanation = aggregate["by_category"]["Explanation"]
    assert explanation["accuracy_pct"] == 50.0
    assert explanation["n"] == 2 and explanation["correct"] == 1


def test_category_metrics_that_do_not_apply_report_none_not_zero():
    """A category with no code task has no test-pass rate. Folding that absence
    in as a zero would invent a number the run never measured."""
    records = [build_record("Q01", True, 0.0)]      # RAG-based: no code task
    aggregate = M.aggregate_model("m", records)
    rag = aggregate["by_category"]["RAG-based Question"]
    assert rag["test_pass_rate_pct"] is None
    assert rag["accuracy_pct"] == 100.0


def test_category_test_pass_rate_covers_only_categories_with_code_tasks():
    code_record = build_record("Q25", True, None)
    code_record["code_eval"] = {"tests_total": 5, "tests_passed": 4}
    aggregate = M.aggregate_model("m", [build_record("Q01", True, 0.0), code_record])
    code = aggregate["by_category"]["Code Generation"]
    rag = aggregate["by_category"]["RAG-based Question"]
    assert code["test_pass_rate_pct"] == 80.0
    assert code["tests_passed"] == 4 and code["tests_total"] == 5
    assert rag["test_pass_rate_pct"] is None
    # the overall row still pools every executed test across categories
    assert aggregate["test_pass_rate_pct"] == 80.0


def test_snippet_categories_carry_no_retrieval_quality_score():
    """The code-excerpt categories quote their evidence in the question, so no
    chunk can be the right chunk and retrieval quality is n/a there."""
    record = build_record("Q31", True, None)        # Code Retrieval
    record["retrieval"] = {**record["retrieval"], "applicable": False,
                           "retrieval_quality_pct": None}
    aggregate = M.aggregate_model("m", [record])
    cr = aggregate["by_category"]["Code Retrieval"]
    assert cr["retrieval_quality_pct"] is None
    assert cr["retrieval_quality_n"] == 0


def test_category_latency_and_tokens_are_recorded_per_category():
    records = [build_record("Q01", True, 0.0, latency=1000.0, tokens=100),
               build_record("Q25", True, None, latency=3000.0, tokens=50)]
    records[1]["code_eval"] = {"tests_total": 5, "tests_passed": 5}
    aggregate = M.aggregate_model("m", records)
    rag = aggregate["by_category"]["RAG-based Question"]
    code = aggregate["by_category"]["Code Generation"]
    assert rag["latency_ms_mean"] == 1000.0 and rag["total_tokens"] == 200
    assert code["latency_ms_mean"] == 3000.0 and code["total_tokens"] == 100


def test_category_averages_reconcile_with_the_overall_row():
    """The overall number is the category numbers re-merged, weighted by the
    questions each category actually covered. If a category cell were averaged
    over a different denominator than it reports, this drift would catch it."""
    records = [build_record("Q01", True, 0.0), build_record("Q03", False, 40.0),
               build_record("Q11", True, 10.0), build_record("Q12", False, None),
               build_record("Q25", True, None)]
    records[4]["code_eval"] = {"tests_total": 5, "tests_passed": 5}
    aggregate = M.aggregate_model("m", records)
    by_category = aggregate["by_category"]
    for key in ("accuracy_pct", "correctness_pct"):
        weighted = sum(by_category[c][key] * by_category[c]["n"] for c in by_category)
        total = sum(by_category[c]["n"] for c in by_category)
        assert abs(weighted / total - aggregate[key]) < 0.2, key


# ---------------------------------------------------------------------------
# Resource readings that could not be measured
# ---------------------------------------------------------------------------
# psutil not installed, no Ollama process found, or no nvidia-smi: the sampler
# reports None rather than a guess, and the aggregation has to turn that into
# "not measured" instead of crashing on max()/mean() over a list of Nones.

def _unmeasured_resources():
    """The exact shape ResourceSampler.stats() produces when it cannot sample."""
    return {
        "samples": 5, "sampled_seconds": 1.0,
        "cpu_percent_mean": None, "cpu_percent_peak": None,
        "process_rss_mean_mb": None, "process_rss_peak_mb": None,
        "system_ram_used_mean_mb": None, "system_ram_used_peak_mb": None,
        "gpu_util_mean_pct": None, "gpu_util_peak_pct": None,
        "gpu_mem_mean_mb": None, "gpu_mem_peak_mb": None,
        "gpu_measured": False, "psutil_available": False,
    }


def test_all_none_resource_samples_aggregate_to_none_without_raising():
    """The machine that could measure nothing is a legitimate run, not a crash:
    this is the exact shape that used to raise TypeError inside max()."""
    records = [build_record("Q01", True, 0.0), build_record("Q03", False, 40.0)]
    for r in records:
        r["resources"] = _unmeasured_resources()
    aggregate = M.aggregate_model("m", records)

    assert aggregate["accuracy_pct"] == 50.0          # scoring unaffected
    for key in ("cpu_percent_mean", "cpu_percent_peak", "cpu_percent_over_baseline",
                "process_rss_peak_mb", "process_rss_over_baseline_mb",
                "system_ram_used_peak_mb", "system_ram_over_baseline_mb",
                "gpu_util_mean_pct", "gpu_mem_peak_mb", "gpu_mem_over_baseline_mb"):
        assert aggregate[key] is None, f"{key} should read as not measured, got {aggregate[key]}"


def test_partly_measured_resources_keep_the_real_values():
    """Filtering the Nones must not change the number when at least one real
    sample exists - the None entries are the unmeasured questions, not zeros."""
    records = [build_record("Q01", True, 0.0), build_record("Q03", True, 0.0)]
    records[0]["resources"] = dict(_unmeasured_resources(),
                                   cpu_percent_mean=None, cpu_percent_peak=None,
                                   system_ram_used_peak_mb=None)
    records[1]["resources"] = dict(_unmeasured_resources(),
                                   psutil_available=True,
                                   cpu_percent_mean=10.0, cpu_percent_peak=20.0,
                                   system_ram_used_peak_mb=9000.0)
    aggregate = M.aggregate_model("m", records)
    assert aggregate["cpu_percent_mean"] == 10.0
    assert aggregate["cpu_percent_peak"] == 20.0
    assert aggregate["system_ram_used_peak_mb"] == 9000.0
    assert aggregate["gpu_mem_peak_mb"] is None        # still genuinely unmeasured


def test_missing_resources_block_is_reported_as_not_measured():
    """Generations run with sampling off carry no resources dict at all."""
    records = [build_record("Q01", True, 0.0)]
    records[0]["resources"] = None
    aggregate = M.aggregate_model("m", records)
    assert aggregate["cpu_percent_mean"] is None
    assert aggregate["cpu_percent_peak"] is None
    assert aggregate["system_ram_used_peak_mb"] is None
    assert aggregate["accuracy_pct"] == 100.0


def test_resource_sampler_reports_what_it_could_not_measure():
    """The sampler's contract: no samples means None fields plus an honest
    psutil_available flag - never a zero, never a guess."""
    from evaluation import resources as R

    stats = R.ResourceSampler().stats()   # never entered: zero samples
    assert stats["samples"] == 0
    assert stats["cpu_percent_mean"] is None
    assert stats["cpu_percent_peak"] is None
    assert stats["system_ram_used_peak_mb"] is None
    assert stats["gpu_mem_peak_mb"] is None
    assert stats["gpu_measured"] is False
    assert stats["psutil_available"] == (R.psutil is not None)


def test_resource_baseline_reports_real_readings_when_psutil_is_available():
    """The baseline that feeds every 'over idle' delta: CPU / RAM keys exist
    exactly when psutil does, and the GPU keys exist only with real numbers."""
    from evaluation import resources as R

    snapshot = R.baseline()
    assert snapshot["gpu_present"] == (snapshot["gpu_mem_total_mb"] is not None)
    if R.psutil is None:
        assert snapshot["psutil_available"] is False
        assert "cpu_percent" not in snapshot
        return
    # With psutil present the readings themselves are the signal; only the
    # psutil-missing branch sets the psutil_available flag.
    assert isinstance(snapshot["cpu_percent"], float) and 0.0 <= snapshot["cpu_percent"]
    assert snapshot["system_ram_used_mb"] > 0
    assert snapshot["system_ram_total_mb"] >= snapshot["system_ram_used_mb"]
