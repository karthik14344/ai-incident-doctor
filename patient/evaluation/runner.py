"""Exercise 1 - run the identical dataset through every model and score it.

The run is deliberately structured so that only the model varies:

  Stage 1  retrieval, once per question. Every model then answers from the
           byte-identical context. Retrieval quality is therefore a property of
           the pipeline, reported once, not something a model can win on.
  Stage 2  one model at a time, warmed up once, then all 30 questions in order.
           Sequential rather than parallel: two models sharing a GPU would each
           make the other look slow, and the timings would measure contention.
  Stage 3  scoring, aggregation, and the Exercise 4 trade-off analysis.

Everything held constant across models: the application, the prompt template and
system prompt (imported from the LLM service), the questions, the knowledge
base, the retrieved context, top_k, max tokens, temperature and seed.
"""

import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ingestion_service.app.embedder import embedding_fallback_count

from evaluation import metrics as M
from evaluation import prepare_kb, resources
from evaluation.analysis import analyse
from evaluation.code_eval import run_code_task
from evaluation.corpus import EVAL_COLLECTION
from evaluation.dataset import EVAL_DATASET, dataset_by_id
from evaluation.pipeline import OLLAMA_DEFAULT_URL, generate, retrieve, unload, warm_up
from evaluation.rag_analysis import build_traces

DEFAULT_CONFIG = {
    "collection_name": EVAL_COLLECTION,
    "top_k": 4,
    "max_tokens": 512,
    "temperature": 0.2,
    "seed": 42,
    "embedding_model": "nomic-embed-text",
    "ollama_base_url": OLLAMA_DEFAULT_URL,
}


def _now() -> str:
    return datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# Stage 1 - retrieval, shared by every model
# ---------------------------------------------------------------------------

def run_retrieval_stage(dataset: List[Dict[str, Any]], config: Dict[str, Any],
                        emit: Callable[[Dict[str, Any]], None]) -> List[Dict[str, Any]]:
    records = []
    for index, item in enumerate(dataset):
        before = embedding_fallback_count()
        result = retrieve(
            item["question"], config["collection_name"], config["top_k"],
            embedding_model=config["embedding_model"],
            ollama_base_url=config["ollama_base_url"],
        )
        # A query embedded by the hash fallback cannot be compared with chunks
        # embedded by nomic-embed-text. Flag it rather than let a meaningless
        # similarity score quietly become a data point.
        degraded = embedding_fallback_count() > before

        quality = M.retrieval_quality(result["sources"], item)
        records.append({
            "id": item["id"],
            "category": item["category"],
            "task_type": item["task_type"],
            "question": item["question"],
            "answerable": item["answerable"],
            "gold_sources": [f"{f} p{p}" for f, p in item["gold_sources"]],
            "context": result["assembled_context"],
            "sources": result["sources"],
            "retrieval": quality,
            "retrieval_ms": result["retrieval_ms"],
            "embed_ms": result["embed_ms"],
            "search_ms": result["search_ms"],
            "context_chars": result["context_chars"],
            "embedding_degraded": degraded,
        })
        emit({"type": "retrieval_progress", "index": index + 1,
              "total": len(dataset), "id": item["id"],
              "hit": quality.get("hit_at_k"), "degraded": degraded})
    return records


# ---------------------------------------------------------------------------
# Stage 2 - one model's full pass over the dataset
# ---------------------------------------------------------------------------

def run_model(model: str, dataset: List[Dict[str, Any]],
              retrieval_records: List[Dict[str, Any]], config: Dict[str, Any],
              emit: Callable[[Dict[str, Any]], None],
              should_stop: Optional[Callable[[], bool]] = None) -> List[Dict[str, Any]]:
    by_id = {r["id"]: r for r in retrieval_records}

    warm = warm_up(model, config["ollama_base_url"])
    emit({"type": "model_warm", "model": model, "warmup_ms": warm["warmup_ms"],
          "error": warm["error"]})

    per_question: List[Dict[str, Any]] = []

    for index, item in enumerate(dataset):
        if should_stop and should_stop():
            emit({"type": "cancelled", "model": model, "after": index})
            break

        retrieved = by_id[item["id"]]
        gen = generate(
            item["question"], retrieved["context"], model,
            ollama_base_url=config["ollama_base_url"],
            max_tokens=config["max_tokens"], temperature=config["temperature"],
            seed=config["seed"],
        )

        record: Dict[str, Any] = {
            "id": item["id"],
            "category": item["category"],
            "task_type": item["task_type"],
            "question": item["question"],
            "answerable": item["answerable"],
            "model": model,
            "status": gen["status"],
            "retrieval": retrieved["retrieval"],
        }

        if gen["status"] != "ok":
            record["error"] = gen.get("error")
            per_question.append(record)
            emit({"type": "question_done", "model": model, "id": item["id"],
                  "index": index + 1, "total": len(dataset), "status": "error",
                  "error": gen.get("error")})
            continue

        answer = gen["answer"]
        code_result = run_code_task(answer, item["code_task"]) if "code_task" in item else None

        record.update({
            "answer": answer,
            "timings": {
                **gen["timings"],
                "retrieval_ms": retrieved["retrieval_ms"],
                "end_to_end_ms": round(gen["timings"]["total_ms"] + retrieved["retrieval_ms"], 1),
            },
            "tokens": gen["tokens"],
            "resources": gen["resources"],
            "correctness": M.correctness(
                answer, item,
                test_pass_rate_pct=code_result["test_pass_rate_pct"] if code_result else None),
            "relevance": M.relevance(answer, item, retrieved["context"]),
            "hallucination": M.hallucination(answer, retrieved["context"],
                                             item["question"], item),
            "code_eval": code_result,
        })
        per_question.append(record)

        emit({"type": "question_done", "model": model, "id": item["id"],
              "index": index + 1, "total": len(dataset), "status": "ok",
              "correctness_pct": record["correctness"]["correctness_pct"],
              "is_correct": record["correctness"]["is_correct"],
              "hallucination_rate_pct": record["hallucination"]["hallucination_rate_pct"],
              "latency_ms": record["timings"]["total_ms"],
              "tokens": record["tokens"]["total_tokens"]})

    return per_question


# ---------------------------------------------------------------------------
# Full run
# ---------------------------------------------------------------------------

def run_evaluation(models: List[str],
                   dataset: Optional[List[Dict[str, Any]]] = None,
                   config: Optional[Dict[str, Any]] = None,
                   emit: Optional[Callable[[Dict[str, Any]], None]] = None,
                   should_stop: Optional[Callable[[], bool]] = None,
                   rebuild_kb: bool = False) -> Dict[str, Any]:
    """Run every model over the whole dataset and return the finished report."""
    dataset = dataset or EVAL_DATASET
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    emit = emit or (lambda _event: None)

    run_id = f"eval_{uuid.uuid4().hex[:10]}"
    started_at = _now()
    wall_started = time.perf_counter()

    emit({"type": "start", "run_id": run_id, "models": models,
          "questions": len(dataset), "config": cfg, "started_at": started_at})

    kb_args = {"embedding_model": cfg["embedding_model"],
               "ollama_base_url": cfg["ollama_base_url"]}
    kb_build = (prepare_kb.build(cfg["collection_name"], **kb_args) if rebuild_kb
                else prepare_kb.ensure(cfg["collection_name"], **kb_args))
    kb_status = prepare_kb.collection_status(cfg["collection_name"])
    emit({"type": "kb", "status": kb_status, "build": kb_build})

    # Evict anything a previous run left resident before reading the idle
    # floor, or a leftover model's VRAM becomes the baseline every later
    # measurement is compared against.
    eviction = unload(models, cfg["ollama_base_url"])
    machine = resources.baseline()
    machine["evicted_before_baseline"] = eviction["evicted"]
    emit({"type": "baseline", "baseline": machine, "eviction": eviction})

    retrieval_records = run_retrieval_stage(dataset, cfg, emit)
    retrieval_summary = M.aggregate_retrieval(retrieval_records)
    emit({"type": "retrieval_done", "summary": retrieval_summary})

    per_model: Dict[str, List[Dict[str, Any]]] = {}
    aggregates: List[Dict[str, Any]] = []

    for index, model in enumerate(models):
        if should_stop and should_stop():
            break
        emit({"type": "model_start", "model": model, "index": index,
              "total": len(models)})
        records = run_model(model, dataset, retrieval_records, cfg, emit, should_stop)
        per_model[model] = records
        aggregate = M.aggregate_model(model, records, baseline=machine)
        aggregates.append(aggregate)
        emit({"type": "model_done", "model": model, "aggregate": aggregate})

    analysis = analyse(aggregates, retrieval_summary, per_model)
    emit({"type": "analysis", "analysis": analysis})

    traces = build_traces(retrieval_records, per_model)

    report = {
        "run_id": run_id,
        "created_at": started_at,
        "finished_at": _now(),
        "wall_seconds": round(time.perf_counter() - wall_started, 1),
        "config": cfg,
        "models": models,
        "dataset_size": len(dataset),
        "knowledge_base": {**kb_status, "build": kb_build},
        "machine_baseline": machine,
        "retrieval": {
            "summary": retrieval_summary,
            # The full assembled context is kept, not stripped. It is what every
            # quality metric is measured against, so a report without it can be
            # read but never re-scored - and metric definitions do get corrected
            # after you read what the models actually said. 30 contexts is a few
            # tens of kilobytes; a rerun is an hour of GPU time.
            "per_question": [{k: v for k, v in r.items()}
                             for r in retrieval_records],
            "degraded_questions": [r["id"] for r in retrieval_records if r["embedding_degraded"]],
        },
        "aggregates": aggregates,
        "per_question": per_model,
        "analysis": analysis,
        "rag_traces": traces,
    }

    emit({"type": "done", "run_id": run_id, "wall_seconds": report["wall_seconds"]})
    return report


# ---------------------------------------------------------------------------
# Background job wrapper - what the API Gateway drives
# ---------------------------------------------------------------------------

class EvaluationJob:
    """One evaluation running on a worker thread, with pollable progress.

    A full run is tens of minutes. Streaming that over one HTTP connection
    means a page reload throws it away, so the gateway starts a job and the UI
    polls `snapshot()` instead.
    """

    def __init__(self, models: List[str], config: Optional[Dict[str, Any]] = None,
                 rebuild_kb: bool = False, dataset: Optional[List[Dict[str, Any]]] = None):
        self.models = models
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.rebuild_kb = rebuild_kb
        self.dataset = dataset or EVAL_DATASET

        self.state = "pending"        # pending | running | done | error | cancelled
        self.run_id: Optional[str] = None
        self.report: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.started_at = _now()
        self.events: List[Dict[str, Any]] = []
        self.stage = "starting"
        self.progress = {"models_done": 0, "models_total": len(models),
                         "questions_done": 0, "questions_total": len(self.dataset),
                         "current_model": None}
        self.live_rows: Dict[str, Dict[str, Any]] = {}

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    # -- control --------------------------------------------------------
    def start(self) -> "EvaluationJob":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def cancel(self) -> None:
        self._stop.set()

    # -- internals ------------------------------------------------------
    def _emit(self, event: Dict[str, Any]) -> None:
        with self._lock:
            event["at"] = _now()
            self.events.append(event)
            if len(self.events) > 400:
                del self.events[:len(self.events) - 400]

            kind = event["type"]
            if kind == "start":
                self.run_id = event["run_id"]
                self.stage = "retrieving"
            elif kind == "retrieval_progress":
                self.stage = f"retrieving {event['index']}/{event['total']}"
            elif kind == "retrieval_done":
                self.stage = "generating"
            elif kind == "model_start":
                self.progress["current_model"] = event["model"]
                self.progress["questions_done"] = 0
            elif kind == "question_done":
                self.progress["questions_done"] = event["index"]
                row = self.live_rows.setdefault(
                    event["model"], {"correct": 0, "answered": 0, "latency_ms": 0.0, "tokens": 0})
                row["answered"] += 1
                if event.get("is_correct"):
                    row["correct"] += 1
                row["latency_ms"] += event.get("latency_ms") or 0
                row["tokens"] += event.get("tokens") or 0
            elif kind == "model_done":
                self.progress["models_done"] += 1
            elif kind == "analysis":
                self.stage = "analysing"

    def _run(self) -> None:
        self.state = "running"
        try:
            self.report = run_evaluation(
                self.models, dataset=self.dataset, config=self.config,
                emit=self._emit, should_stop=self._stop.is_set,
                rebuild_kb=self.rebuild_kb,
            )
            self.run_id = self.report["run_id"]
            self.state = "cancelled" if self._stop.is_set() else "done"
            self.stage = self.state
            save_report(self.report)
        except Exception as e:
            self.state = "error"
            self.stage = "error"
            self.error = f"{type(e).__name__}: {e}"

    # -- readout --------------------------------------------------------
    def snapshot(self, event_limit: int = 40) -> Dict[str, Any]:
        with self._lock:
            return {
                "state": self.state,
                "stage": self.stage,
                "run_id": self.run_id,
                "models": self.models,
                "config": self.config,
                "started_at": self.started_at,
                "progress": dict(self.progress),
                "live_rows": {m: dict(r) for m, r in self.live_rows.items()},
                "recent_events": self.events[-event_limit:],
                "error": self.error,
                "has_report": self.report is not None,
            }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def reanalyse(report: Dict[str, Any], rescore: bool = True) -> Dict[str, Any]:
    """Re-score and re-interpret a saved report without running any model.

    The report holds every answer alongside the exact context it was produced
    from, so a correction to a metric can be applied to results already
    collected. This matters more than it sounds: the first run scored llama3.2
    as the worst hallucinator because the abstention detector did not recognise
    "I couldn't find any information about X" as declining to answer. Fixing the
    detector and re-running would have changed the underlying generations too,
    leaving no way to tell the metric fix apart from run-to-run drift. Re-scoring
    the same answers isolates the correction.

    `rescore=False` recomputes only the analysis and traces, leaving the
    per-question metrics as they were.
    """
    per_model = report["per_question"]
    retrieval_records = report["retrieval"]["per_question"]
    contexts = {r["id"]: r.get("context", "") for r in retrieval_records}
    by_id = dataset_by_id()

    # Every quality metric is measured against the retrieved context, so
    # re-scoring is only valid when the stored context is the exact text the
    # model saw. Each record carries `context_chars` from the original run;
    # anything shorter means the context is missing or was rebuilt from the
    # truncated source previews, and scoring against it would mark supported
    # claims as fabricated and report the result as a finding.
    if rescore:
        for record in retrieval_records:
            stored = len(record.get("context") or "")
            expected = record.get("context_chars", 0)
            if stored < expected:
                raise ValueError(
                    f"Report {report.get('run_id')} cannot be re-scored: {record['id']} stored "
                    f"{stored} characters of context but the run used {expected}. Re-run the "
                    "evaluation, or pass rescore=False to recompute only the analysis and traces.")

    if rescore:
        for model, records in per_model.items():
            for record in records:
                item = by_id.get(record["id"])
                if item:
                    # Labels move with the dataset: a stored run predating a
                    # re-categorisation must aggregate under the current one,
                    # and metric applicability keys on the task shape.
                    record["category"] = item["category"]
                    record["task_type"] = item["task_type"]
                if not item or record.get("status") != "ok":
                    continue
                answer, context = record["answer"], contexts.get(record["id"], "")
                code_result = record.get("code_eval")
                record["correctness"] = M.correctness(
                    answer, item,
                    test_pass_rate_pct=code_result["test_pass_rate_pct"] if code_result else None)
                record["relevance"] = M.relevance(answer, item, context)
                record["hallucination"] = M.hallucination(
                    answer, context, item["question"], item)

        report["aggregates"] = [
            M.aggregate_model(model, records, baseline=report.get("machine_baseline"))
            for model, records in per_model.items()
        ]
        for record in retrieval_records:
            item = by_id.get(record["id"])
            if item:
                record["category"] = item["category"]
                record["task_type"] = item["task_type"]
                record["retrieval"] = M.retrieval_quality(record.get("sources", []), item)
        report["retrieval"]["summary"] = M.aggregate_retrieval(retrieval_records)

    report["analysis"] = analyse(report["aggregates"],
                                 report["retrieval"]["summary"], per_model)
    report["rag_traces"] = build_traces(retrieval_records, per_model)
    report["reanalysed_at"] = _now()
    report["rescored"] = rescore
    return report


def load_report(run_id: str) -> Dict[str, Any]:
    from api_gateway.app.db import get_db_connection

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT report FROM evaluation_runs WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise KeyError(f"No evaluation run named {run_id}")
    return json.loads(row["report"])


def save_report(report: Dict[str, Any]) -> None:
    """Store a finished report in SQLite and drop a JSON copy next to it."""
    from api_gateway.app.db import get_db_connection

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO evaluation_runs
                (run_id, models, dataset_size, config, report, created_at, wall_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            report["run_id"], json.dumps(report["models"]), report["dataset_size"],
            json.dumps(report["config"]), json.dumps(report),
            report["created_at"], report["wall_seconds"],
        ))
        conn.commit()
    finally:
        conn.close()

    out_dir = os.path.join(BASE_DIR, "data", "evaluations")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{report['run_id']}.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    # Also an MLflow experiment run, when MLFLOW_TRACKING_URI is configured.
    from evaluation.mlflow_log import log_report

    report["mlflow_run_id"] = log_report(report)
