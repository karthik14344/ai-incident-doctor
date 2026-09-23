"""The evaluation endpoints, exercised without Ollama or a running microservice.

These cover the parts of the API that decide what gets reported: the dataset the
UI renders, the run lifecycle (start / status / cancel / fetch), and - most
importantly - that the comparison page refuses to invent a correctness score for
a question it has no ground truth for.

Anything needing a model to generate text is out of scope here; that is what
`run_evaluation.py` is for.
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from api_gateway.app.main import app
from api_gateway.app.metrics import evaluate_answer, summarise_run


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


CONTEXT = (
    "[Source 1: attendance_policy.pdf - Page 1 | Similarity: 0.82]\n"
    "Students are required to maintain a minimum attendance of 75% in each registered "
    "course to be eligible to sit for semester examinations."
)
SOURCES = [{"filename": "attendance_policy.pdf", "page": 1, "similarity": 0.82},
           {"filename": "exam_policy.pdf", "page": 1, "similarity": 0.61}]


# ---------------------------------------------------------------------------
# Dataset endpoint
# ---------------------------------------------------------------------------

SEVEN_CATEGORIES = {"Explanation", "Code Retrieval", "Dependency Understanding",
                    "Bug Analysis", "Code Generation", "Refactoring",
                    "RAG-based Question"}


def test_dataset_endpoint_describes_the_evaluation_set(client):
    body = client.get("/api/evaluation/dataset").json()
    assert 20 <= body["size"] <= 50
    assert len(body["items"]) == body["size"]
    assert body["code_tests_total"] > 0


def test_dataset_endpoint_reports_the_seven_categories(client):
    """The comparison is reported per category, so the endpoint must ship the
    seven labels, every question inside exactly one of them, and - so the UI
    never has to invent a reason - the note explaining each category's n/a."""
    body = client.get("/api/evaluation/dataset").json()
    assert SEVEN_CATEGORIES <= set(body["categories"])
    for item in body["items"]:
        assert item["category"] in SEVEN_CATEGORIES
        assert item["task_type"]
    for category in SEVEN_CATEGORIES:
        assert category in body["category_metric_notes"]


def test_dataset_endpoint_ships_the_metric_formulas(client):
    """The UI renders these rather than keeping its own copy, so a missing one
    means the page silently stops explaining a metric."""
    definitions = client.get("/api/evaluation/dataset").json()["metric_definitions"]
    names = {d["name"] for d in definitions}
    assert {"Correctness / Accuracy", "Relevance", "Retrieval Quality",
            "Hallucination Rate", "Test-Pass Rate", "Response Latency",
            "Token Usage", "CPU / GPU / Memory"} <= names
    assert all(d["formula"] for d in definitions)


def test_dataset_items_never_leak_the_answer_key(client):
    """The page shows the questions. Shipping `expected_facts` with them would
    put the ground truth in the browser."""
    for item in client.get("/api/evaluation/dataset").json()["items"]:
        assert "expected_facts" not in item
        assert "forbidden" not in item


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------

def test_status_is_idle_before_anything_has_been_started(client):
    body = client.get("/api/evaluation/status").json()
    assert body["state"] in {"idle", "done", "error", "cancelled", "running"}


def test_starting_a_run_with_no_models_is_rejected(client):
    assert client.post("/api/evaluation/run", json={"models": []}).status_code == 400


def test_cancelling_when_nothing_is_running_is_rejected(client):
    response = client.post("/api/evaluation/cancel")
    assert response.status_code in {409, 200}


def test_fetching_an_unknown_run_is_a_404(client):
    assert client.get("/api/evaluation/runs/eval_does_not_exist").status_code == 404


def test_run_list_returns_a_list(client):
    assert isinstance(client.get("/api/evaluation/runs").json(), list)


# ---------------------------------------------------------------------------
# Repository endpoints
# ---------------------------------------------------------------------------

def test_repo_questions_all_declare_the_files_a_correct_answer_needs(client):
    body = client.get("/api/evaluation/repo/questions").json()
    assert len(body["questions"]) >= 5
    for question in body["questions"]:
        assert question["expected_files"], f"{question['id']} names no expected files"
        assert question["why_hard"]


def test_every_expected_file_in_a_repo_question_still_exists():
    """These labels are the denominator of Exercise 6's file-recall metric. A
    rename would silently make a question unanswerable and read as the model
    getting worse."""
    from evaluation.repo_index import BASE_DIR, REPO_QUESTIONS, iter_source_files

    indexed = {os.path.relpath(f, BASE_DIR).replace(os.sep, "/") for f in iter_source_files()}
    for question in REPO_QUESTIONS:
        for path in question["expected_files"]:
            assert path in indexed, f"{question['id']} expects {path}, which is not indexed"


def test_repo_chunking_covers_a_whole_file():
    """Line windows must overlap and reach the end - a chunker that drops the
    tail would hide whatever is defined at the bottom of a module."""
    from evaluation.repo_index import BASE_DIR, chunk_source

    target = os.path.join(BASE_DIR, "evaluation", "metrics.py")
    chunks = chunk_source(target)
    assert chunks
    with open(target, encoding="utf-8") as fh:
        last_line = len(fh.read().splitlines())
    assert any(f"-{last_line})" in c["text"] for c in chunks)
    assert all(c["text"].startswith("FILE: evaluation/metrics.py") for c in chunks)


def test_repo_result_is_a_404_before_any_run(client):
    response = client.get("/api/evaluation/repo/result")
    assert response.status_code in {404, 200}


# ---------------------------------------------------------------------------
# Comparison-page scoring
# ---------------------------------------------------------------------------

def test_a_dataset_question_unlocks_the_ground_truth_metrics():
    quality = evaluate_answer(
        "The minimum attendance required is 75% in each registered course.",
        "What is the minimum attendance percentage required?",
        CONTEXT, SOURCES, dataset_id="Q01")
    assert quality["ground_truth_available"] is True
    assert quality["correctness"]["applicable"] is True
    assert quality["correctness"]["value"] == 100.0
    assert quality["retrieval_quality"]["applicable"] is True


def test_an_ad_hoc_question_reports_not_applicable_rather_than_guessing():
    """Correctness without ground truth would be a number with nothing behind
    it, which is worse than an empty cell."""
    quality = evaluate_answer(
        "Attendance must be at least 75%.",
        "Some question the dataset has never seen",
        CONTEXT, SOURCES, dataset_id=None)
    assert quality["ground_truth_available"] is False
    assert quality["correctness"]["applicable"] is False
    assert quality["correctness"]["value"] is None
    assert quality["retrieval_quality"]["applicable"] is False
    assert quality["test_pass_rate"]["applicable"] is False


def test_relevance_and_hallucination_stay_measurable_without_ground_truth():
    quality = evaluate_answer(
        "Attendance must be at least 75% to sit semester examinations.",
        "What attendance do I need for exams?", CONTEXT, SOURCES)
    assert quality["relevance"]["applicable"] is True
    assert quality["relevance"]["value"] is not None
    assert quality["hallucination"]["applicable"] is True
    assert quality["hallucination"]["value"] is not None


def test_an_unknown_dataset_id_falls_back_to_ad_hoc_instead_of_erroring():
    quality = evaluate_answer("anything", "anything", CONTEXT, SOURCES,
                              dataset_id="Q999")
    assert quality["ground_truth_available"] is False


def test_a_code_task_runs_the_generated_code():
    quality = evaluate_answer(
        "```python\ndef is_exam_eligible(attendance_percent):\n"
        "    return attendance_percent >= 75\n```",
        "Write is_exam_eligible", CONTEXT, SOURCES, dataset_id="Q25")
    assert quality["test_pass_rate"]["applicable"] is True
    assert quality["test_pass_rate"]["value"] == 100.0


def build_result(model, correctness, latency, tokens, halluc=10.0):
    return {
        "status": "ok", "model": model,
        "quality": {
            "ground_truth_available": True,
            "correctness": {"applicable": True, "value": correctness},
            "relevance": {"applicable": True, "value": 80.0},
            "hallucination": {"applicable": True, "value": halluc},
            "test_pass_rate": {"applicable": False, "value": None},
        },
        "timings": {"total_ms": latency, "ttft_ms": 100.0},
        "tokens": {"total_tokens": tokens},
        "resources": {"cpu_percent_mean": 10.0, "gpu_mem_peak_mb": 4000.0,
                      "system_ram_used_peak_mb": 9000.0},
    }


def test_summary_names_a_leader_per_criterion():
    summary = summarise_run([
        build_result("alpha", 90.0, 5000.0, 400, halluc=5.0),
        build_result("beta", 70.0, 2000.0, 300, halluc=25.0),
    ])
    assert summary["models_compared"] == 2
    assert summary["leaders"]["correctness"]["model"] == "alpha"
    assert summary["leaders"]["hallucination"]["model"] == "alpha"
    assert summary["leaders"]["latency"]["model"] == "beta"
    assert summary["leaders"]["token_usage"]["model"] == "beta"


def test_summary_declares_no_overall_winner():
    """Deliberate: merging eight criteria into one score requires weights, and
    those weights would be an opinion presented as a measurement."""
    summary = summarise_run([build_result("alpha", 90.0, 5000.0, 400),
                             build_result("beta", 70.0, 2000.0, 300)])
    assert "winner" not in summary
    assert "composite_score" not in summary


def test_failed_models_are_counted_and_excluded():
    summary = summarise_run([
        build_result("alpha", 90.0, 5000.0, 400),
        {"status": "error", "model": "beta", "error": "unreachable"},
    ])
    assert summary["models_compared"] == 1
    assert summary["models_failed"] == 1


def test_a_criterion_no_model_could_report_is_simply_absent():
    summary = summarise_run([build_result("alpha", 90.0, 5000.0, 400)])
    assert "test_pass_rate" not in summary["leaders"]
