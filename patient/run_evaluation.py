"""Week-4 evaluation - runs the whole thing from one command.

    python run_evaluation.py                          # all installed models, full dataset
    python run_evaluation.py --models codellama llama3.2 mistral
    python run_evaluation.py --limit 5                # quick smoke run
    python run_evaluation.py --repo                   # Exercise 6 as well
    python run_evaluation.py --repo-only              # Exercise 6 alone

Only Ollama needs to be running; the five microservices do not, because the
harness imports the same pipeline modules they do.
"""

import argparse
import json
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# The Windows console defaults to cp1252, which mangles an em dash and raises
# UnicodeEncodeError outright on anything a model happens to emit outside that
# codepage. Reconfiguring is cheaper than sanitising every printed string.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import httpx

from api_gateway.app.db import init_db
from evaluation import repo_index
from evaluation.corpus import EVAL_COLLECTION
from evaluation.dataset import EVAL_DATASET, category_counts
from evaluation.pipeline import OLLAMA_DEFAULT_URL
from evaluation.runner import (
    DEFAULT_CONFIG, load_report, reanalyse, run_evaluation, save_report)

EMBEDDING_HINTS = ("embed", "bge-", "gte-", "e5-", "minilm")


def installed_models(ollama_base_url: str) -> list:
    """Chat-capable models already pulled locally. Nothing is downloaded."""
    try:
        with httpx.Client(timeout=10.0, trust_env=False) as client:
            response = client.get(f"{ollama_base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
            return [m["name"].split(":")[0] for m in response.json().get("models", [])
                    if not any(hint in m["name"].lower() for hint in EMBEDDING_HINTS)]
    except Exception as e:
        print(f"[!] Could not reach Ollama at {ollama_base_url}: {e}")
        return []


def progress_printer():
    def emit(event):
        kind = event["type"]
        if kind == "start":
            print(f"\n=== run {event['run_id']} : {len(event['models'])} models "
                  f"x {event['questions']} questions ===")
        elif kind == "kb":
            status = event["status"]
            print(f"[kb] {status['collection']}: {status['chunks']} chunks, "
                  f"{len(status.get('documents', []))} documents")
        elif kind == "baseline":
            base = event["baseline"]
            gpu = f"GPU {base['gpu_mem_used_mb']}/{base['gpu_mem_total_mb']} MB" \
                if base.get("gpu_present") else "no GPU"
            evicted = base.get("evicted_before_baseline") or []
            print(f"[baseline] CPU {base.get('cpu_percent')}%, "
                  f"RAM {base.get('system_ram_used_mb')} MB used, {gpu}"
                  + (f" (evicted {', '.join(evicted)} first)" if evicted else ""))
        elif kind == "retrieval_progress":
            end = "\n" if event["index"] == event["total"] else "\r"
            flag = " [EMBEDDING FALLBACK]" if event.get("degraded") else ""
            print(f"[retrieval] {event['index']}/{event['total']} {event['id']}"
                  f" hit={event['hit']}{flag}   ", end=end, flush=True)
        elif kind == "retrieval_done":
            s = event["summary"]
            print(f"[retrieval] quality {s['retrieval_quality_pct']}% | "
                  f"precision@k {s['precision_at_k_mean']}% | recall@k {s['recall_at_k_mean']}% | "
                  f"MRR {s['mrr_mean']} | hit rate {s['hit_rate_pct']}%")
        elif kind == "model_start":
            print(f"\n--- {event['model']} ({event['index'] + 1}/{event['total']}) ---")
        elif kind == "model_warm" and event.get("error"):
            print(f"    warmup failed: {event['error']}")
        elif kind == "question_done":
            mark = "." if event.get("is_correct") else ("x" if event["status"] == "ok" else "!")
            end = "\n" if event["index"] == event["total"] else ""
            print(mark, end=end, flush=True)
        elif kind == "model_done":
            a = event["aggregate"]
            print(f"    accuracy {a['accuracy_pct']}% | correctness {a['correctness_pct']}% | "
                  f"relevance {a['relevance_pct']}% | hallucination {a['hallucination_rate_pct']}% | "
                  f"tests {a['tests_passed']}/{a['tests_total']}")
            print(f"    latency mean {a['latency_ms_mean']} ms | ttft {a['ttft_ms_mean']} ms | "
                  f"tokens {a['total_tokens']} | {a['tokens_per_sec_mean']} tok/s")
            print(f"    CPU {a['cpu_percent_mean']}% | RSS peak {a['process_rss_peak_mb']} MB | "
                  f"VRAM peak {a['gpu_mem_peak_mb']} MB | GPU {a['gpu_util_mean_pct']}%")
        elif kind == "done":
            print(f"\n=== finished in {event['wall_seconds']} s ===")

    return emit


def print_report(report):
    print("\n" + "=" * 78)
    print("EXERCISE 3 - QUANTITATIVE COMPARISON")
    print("=" * 78)
    header = f"{'metric':<26}" + "".join(f"{a['model'][:13]:>14}" for a in report["aggregates"])
    print(header)
    rows = [
        ("Accuracy %", "accuracy_pct"), ("Correctness %", "correctness_pct"),
        ("Relevance %", "relevance_pct"), ("Hallucination %", "hallucination_rate_pct"),
        ("Test-pass %", "test_pass_rate_pct"),
        ("Latency mean ms", "latency_ms_mean"), ("TTFT mean ms", "ttft_ms_mean"),
        ("Total tokens", "total_tokens"), ("Tokens/sec", "tokens_per_sec_mean"),
        ("CPU mean %", "cpu_percent_mean"), ("RSS peak MB", "process_rss_peak_mb"),
        ("VRAM peak MB", "gpu_mem_peak_mb"), ("GPU util mean %", "gpu_util_mean_pct"),
    ]
    for label, key in rows:
        print(f"{label:<26}" + "".join(f"{str(a.get(key)):>14}" for a in report["aggregates"]))

    # The same run, broken down by the seven assessment categories. A metric
    # with nothing to measure in a category prints n/a rather than a zero: no
    # code task in a category is not a 0% test-pass rate.
    category_metrics = [
        ("Accuracy %", "accuracy_pct"), ("Correctness %", "correctness_pct"),
        ("Relevance %", "relevance_pct"), ("Hallucination %", "hallucination_rate_pct"),
        ("Test-pass %", "test_pass_rate_pct"), ("Latency mean ms", "latency_ms_mean"),
        ("Tokens total", "total_tokens"),
    ]
    all_categories = sorted({c for a in report["aggregates"] for c in (a.get("by_category") or {})})
    if all_categories:
        print("\n" + "=" * 78)
        print("CATEGORY-WISE COMPARISON (n/a = metric has nothing to measure in that category)")
        print("=" * 78)
        for label, key in category_metrics:
            print(f"\n{label}")
            for category in all_categories:
                cells = []
                for a in report["aggregates"]:
                    bucket = (a.get("by_category") or {}).get(category) or {}
                    value = bucket.get(key)
                    n = bucket.get("n", 0)
                    cells.append("n/a".rjust(14) if value is None else f"{value} (n={n})".rjust(14))
                print(f"  {category:<26}" + "".join(cells))

    analysis = report["analysis"]
    if analysis.get("available"):
        print("\n" + "=" * 78)
        print("EXERCISE 4 - ANALYSIS")
        print("=" * 78)
        for entry in analysis["questions"]:
            print(f"\nQ: {entry['question']}\nA: {entry['answer']}\n   {entry['evidence']}")
        print("\nTRADE-OFF")
        for line in analysis["tradeoff"]["summary"]:
            print(f"  - {line}")
        print(f"\nRECOMMENDATION: {analysis['recommendation']['default']}")
        print(f"  {analysis['recommendation']['why']}")
        print("\nCAVEATS")
        for line in analysis["caveats"]:
            print(f"  - {line}")

    traces = report["rag_traces"]
    print("\n" + "=" * 78)
    print("EXERCISE 5 - RAG PIPELINE ANALYSIS")
    print("=" * 78)
    print("counts:", json.dumps(traces["counts"]))
    print("\nretrieval quality -> response quality")
    for row in traces["retrieval_to_response"]:
        print(f"  {row['band']:<40} n={row['questions']:<3} "
              f"accuracy={row['accuracy_pct']} correctness={row['mean_correctness_pct']} "
              f"hallucination={row['mean_hallucination_pct']}")
    for line in traces["conclusion"]:
        print(f"  - {line}")


def main():
    parser = argparse.ArgumentParser(description="Week-4 evaluation of the KnowledgeAI RAG assistant")
    parser.add_argument("--models", nargs="*", default=None,
                        help="models to compare (default: every chat model already installed)")
    parser.add_argument("--limit", type=int, default=None,
                        help="run only the first N questions (smoke test)")
    parser.add_argument("--top-k", type=int, default=DEFAULT_CONFIG["top_k"])
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_CONFIG["max_tokens"])
    parser.add_argument("--temperature", type=float, default=DEFAULT_CONFIG["temperature"])
    parser.add_argument("--ollama", default=OLLAMA_DEFAULT_URL)
    parser.add_argument("--rebuild-kb", action="store_true",
                        help="rebuild the evaluation knowledge base before running")
    parser.add_argument("--repo", action="store_true",
                        help="also run Exercise 6 (repository-level questions)")
    parser.add_argument("--repo-only", action="store_true",
                        help="run only Exercise 6")
    parser.add_argument("--reindex-repo", action="store_true",
                        help="rebuild the code index before Exercise 6")
    parser.add_argument("--reanalyse", metavar="RUN_ID", default=None,
                        help="re-score and re-interpret a saved run without re-running "
                             "any model")
    parser.add_argument("--no-rescore", action="store_true",
                        help="with --reanalyse, recompute only the analysis and traces "
                             "and leave the per-question metrics untouched")
    args = parser.parse_args()

    init_db()

    if args.reanalyse:
        try:
            report = reanalyse(load_report(args.reanalyse), rescore=not args.no_rescore)
        except ValueError as e:
            print(f"[!] {e}")
            return 1
        save_report(report)
        print_report(report)
        print(f"\n[+] Re-analysed {report['run_id']} from stored results "
              "- no model was run.")
        return 0

    models = args.models or installed_models(args.ollama)
    if not models:
        print("[!] No models available. Start Ollama, or pass --models explicitly.")
        return 1
    print(f"[*] Models: {', '.join(models)}   (nothing is downloaded - these are already installed)")

    if not args.repo_only:
        dataset = EVAL_DATASET[:args.limit] if args.limit else EVAL_DATASET
        print(f"[*] Dataset: {len(dataset)} tasks {category_counts()}")
        report = run_evaluation(
            models, dataset=dataset,
            config={"top_k": args.top_k, "max_tokens": args.max_tokens,
                    "temperature": args.temperature, "ollama_base_url": args.ollama,
                    "collection_name": EVAL_COLLECTION},
            emit=progress_printer(), rebuild_kb=args.rebuild_kb,
        )
        # `run_evaluation` returns the report but does not persist it - the API
        # job wrapper is what normally saves. Without this the CLI would spend
        # an hour of GPU time and then announce a file it never wrote.
        save_report(report)
        print_report(report)
        print(f"\n[+] Saved: data/evaluations/{report['run_id']}.json "
              f"and SQLite table evaluation_runs")

    if args.repo or args.repo_only:
        print("\n" + "=" * 78)
        print("EXERCISE 6 - REPOSITORY-LEVEL UNDERSTANDING")
        print("=" * 78)
        if args.reindex_repo or not repo_index.status()["ready"]:
            built = repo_index.build(ollama_base_url=args.ollama)
            print(f"[index] {built['files_indexed']} files -> {built['total_chunks']} chunks")
        started = time.perf_counter()
        result = repo_index.run_repo_questions(
            models, ollama_base_url=args.ollama,
            emit=lambda e: print(f"  {e['type']} {e.get('id')} {e.get('model') or ''} "
                                 f"{e.get('coverage_pct', '')}"))
        for trace in result["traces"]:
            print(f"\n[{trace['id']}] {trace['question']}")
            print(f"  needs {trace['index_score']['expected_files']} files; index supplied "
                  f"{trace['index_score']['files_retrieved']} "
                  f"({trace['index_score']['file_recall_pct']}%)")
            if trace["index_score"]["missing"]:
                print(f"  never retrieved: {', '.join(trace['index_score']['missing'])}")
            for answer in trace["answers"]:
                if answer["status"] == "ok":
                    print(f"    {answer['model']:<12} named {answer['answer_score']['files_named']}/"
                          f"{answer['answer_score']['expected_files']} files "
                          f"({answer['answer_score']['coverage_pct']}%)")
        print("\nVERDICT")
        for line in result["summary"]["verdict"]:
            print(f"  - {line}")
        out = os.path.join(BASE_DIR, "data", "evaluations")
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "repo_understanding.json"), "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
        print(f"\n[+] Saved: data/evaluations/repo_understanding.json "
              f"({round(time.perf_counter() - started, 1)} s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
