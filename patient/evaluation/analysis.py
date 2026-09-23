"""Exercise 4 - turn the comparison table into an argument.

The exercise is explicit that a table is not the deliverable, so this module
answers the questions it lists, each one from the numbers that were actually
measured, and then looks for the trade-off: whether the most accurate model is
also the cheapest, or whether quality is being bought with latency and memory.

Nothing here is a judgement call dressed as a fact. Where the evidence is thin -
four models is four data points, and a correlation over four points is a hint,
not a finding - the wording says so.
"""

import statistics
from typing import Any, Dict, List, Optional

#: Differences smaller than this are treated as a tie rather than a winner.
TIE_BANDS = {
    "accuracy_pct": 3.0,
    "correctness_pct": 3.0,
    "relevance_pct": 3.0,
    "hallucination_rate_pct": 3.0,
    "test_pass_rate_pct": 5.0,
    "latency_ms_mean": 0.0,
    "total_tokens": 0.0,
}


def _leader(aggregates: List[Dict[str, Any]], key: str,
            better: str = "higher") -> Optional[Dict[str, Any]]:
    """Best model on one metric, with the gap to the runner-up.

    The margin matters more than the ranking: "codellama wins accuracy" reads
    very differently when the margin is 20 points than when it is 0.4.
    """
    usable = [a for a in aggregates if a.get(key) is not None]
    if not usable:
        return None
    ordered = sorted(usable, key=lambda a: a[key], reverse=(better == "higher"))
    best = ordered[0]
    runner = ordered[1] if len(ordered) > 1 else None
    margin = abs(best[key] - runner[key]) if runner else None
    band = TIE_BANDS.get(key, 0.0)

    # Everything inside the tie band of the leader. Reporting "codellama wins
    # the test-pass rate" when all four models scored 100% is technically the
    # sort order speaking, not the data.
    tied = [a["model"] for a in ordered if abs(a[key] - best[key]) <= band]

    return {
        "metric": key,
        "model": best["model"],
        "value": best[key],
        "runner_up": runner["model"] if runner else None,
        "runner_up_value": runner[key] if runner else None,
        "margin": round(margin, 2) if margin is not None else None,
        # A single-model run has no runner-up to be close to, so it is decisive
        # by default rather than reported as "wins by None points".
        "decisive": runner is None or margin > band,
        "tied": tied,
        "is_tie": len(tied) > 1,
        "ranking": [{"model": a["model"], "value": a[key]} for a in ordered],
    }


def _verdict_for(leader: Dict[str, Any], unit: str = "") -> str:
    """One phrase naming the leader, or naming the tie honestly."""
    if leader["is_tie"]:
        if len(leader["tied"]) == len(leader["ranking"]):
            return f"No difference — all {len(leader['tied'])} models scored {leader['value']}{unit}"
        return ("Tied: " + ", ".join(leader["tied"])
                + f" (all within {TIE_BANDS.get(leader['metric'], 0.0)} points at {leader['value']}{unit})")
    if leader["decisive"]:
        return leader["model"]
    return f"{leader['model']}, but only just — {leader['runner_up']} is within {leader['margin']} points"


def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    try:
        return round(statistics.correlation(xs, ys), 3)
    except Exception:
        return None


def _fmt_ms(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value / 1000:.1f} s" if value >= 1000 else f"{value:.0f} ms"


def _memory_cost(agg: Dict[str, Any]) -> Optional[float]:
    """One number for "how much machine does this model need", in MB.

    Prefers VRAM over the idle baseline, because on a GPU-backed Ollama that is
    where the weights live and it isolates what this model added from whatever
    the machine was already holding. Falls back to absolute VRAM, then to
    process RSS on a CPU-only box.
    """
    for key in ("gpu_mem_over_baseline_mb", "gpu_mem_peak_mb",
                "process_rss_over_baseline_mb", "process_rss_peak_mb"):
        value = agg.get(key)
        if value:
            return value
    return None


def _pareto(aggregates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Which models are worth considering at all.

    Four axes, not three: accuracy, hallucination rate, latency and memory. An
    earlier version left hallucination out and produced a contradiction - it
    declared one model dominant on accuracy/latency/memory while the
    recommendation picked a different one for hallucinating a third as often.
    Both cannot be true. Hallucination is a first-class quality axis for an
    assistant that answers policy questions students act on, so it belongs in
    the dominance test.

    A model is dominated when another is at least as good on all four and
    strictly better on one. Anything dominated has no argument for it.
    """
    points = []
    for agg in aggregates:
        if agg.get("accuracy_pct") is None or agg.get("latency_ms_mean") is None:
            continue
        memory = _memory_cost(agg)
        points.append({
            "model": agg["model"],
            "accuracy": agg["accuracy_pct"],
            # Absent hallucination data must not read as "hallucinates nothing",
            # which would let an unmeasured model dominate a measured one.
            "hallucination": agg.get("hallucination_rate_pct")
                             if agg.get("hallucination_rate_pct") is not None else 100.0,
            "latency": agg["latency_ms_mean"],
            "memory": memory if memory is not None else 0.0,
        })

    #: (key, direction) - "higher" means more is better.
    AXES = (("accuracy", "higher"), ("hallucination", "lower"),
            ("latency", "lower"), ("memory", "lower"))

    def no_worse(a, b):
        return all(a[k] >= b[k] if d == "higher" else a[k] <= b[k] for k, d in AXES)

    def strictly_better(a, b):
        return any(a[k] > b[k] if d == "higher" else a[k] < b[k] for k, d in AXES)

    front, dominated = [], []
    for candidate in points:
        beaten_by = next(
            (other["model"] for other in points
             if other["model"] != candidate["model"]
             and no_worse(other, candidate) and strictly_better(other, candidate)),
            None)
        (dominated if beaten_by else front).append({**candidate, "dominated_by": beaten_by})

    return {"pareto_front": front, "dominated": dominated, "points": points,
            "axes": [k for k, _ in AXES]}


def analyse(aggregates: List[Dict[str, Any]], retrieval: Dict[str, Any],
            per_model: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """The full Exercise 4 write-up, derived from the measured numbers."""
    if not aggregates:
        return {"available": False, "reason": "No model completed the dataset."}

    leaders = {
        "accuracy": _leader(aggregates, "accuracy_pct", "higher"),
        "correctness": _leader(aggregates, "correctness_pct", "higher"),
        "relevance": _leader(aggregates, "relevance_pct", "higher"),
        "hallucination": _leader(aggregates, "hallucination_rate_pct", "lower"),
        "test_pass_rate": _leader(aggregates, "test_pass_rate_pct", "higher"),
        "latency": _leader(aggregates, "latency_ms_mean", "lower"),
        "ttft": _leader(aggregates, "ttft_ms_mean", "lower"),
        "token_usage": _leader(aggregates, "total_tokens", "lower"),
        "throughput": _leader(aggregates, "tokens_per_sec_mean", "higher"),
        "cpu": _leader(aggregates, "cpu_percent_mean", "lower"),
        "gpu_memory": _leader(aggregates, "gpu_mem_peak_mb", "lower"),
        "system_memory": _leader(aggregates, "system_ram_used_peak_mb", "lower"),
    }

    by_model = {a["model"]: a for a in aggregates}
    pareto = _pareto(aggregates)

    accuracies = [a["accuracy_pct"] for a in aggregates if a.get("accuracy_pct") is not None]
    latencies = [a["latency_ms_mean"] for a in aggregates if a.get("latency_ms_mean") is not None]
    memories = [_memory_cost(a) or 0.0 for a in aggregates]
    hallucinations = [a["hallucination_rate_pct"] for a in aggregates
                      if a.get("hallucination_rate_pct") is not None]

    correlations = {
        "accuracy_vs_latency": _pearson(accuracies, latencies),
        "accuracy_vs_memory": _pearson(accuracies, memories),
        "accuracy_vs_hallucination": _pearson(accuracies, hallucinations)
        if len(hallucinations) == len(accuracies) else None,
        "n_models": len(aggregates),
    }

    questions = _answer_exercise_questions(leaders, by_model, retrieval, pareto,
                                           correlations, aggregates)

    return {
        "available": True,
        "leaders": leaders,
        "questions": questions,
        "pareto": pareto,
        "correlations": correlations,
        "non_discriminating": _non_discriminating(leaders),
        "tradeoff": _tradeoff_statement(leaders, by_model, correlations, pareto),
        "recommendation": _recommend(leaders, by_model, pareto),
        "caveats": _caveats(aggregates, retrieval, leaders),
    }


def _answer_exercise_questions(leaders, by_model, retrieval, pareto,
                               correlations, aggregates) -> List[Dict[str, Any]]:
    """The seven questions Exercise 4 asks, each answered with its evidence."""
    out: List[Dict[str, Any]] = []

    def add(question: str, answer: str, evidence: str):
        out.append({"question": question, "answer": answer, "evidence": evidence})

    acc = leaders["accuracy"]
    if acc:
        add("Which model provides better accuracy?", _verdict_for(acc, "%"),
            " | ".join(f"{r['model']} {r['value']}%" for r in acc["ranking"]))

    hal = leaders["hallucination"]
    if hal:
        add("Which model produces fewer hallucinations?", _verdict_for(hal, "%"),
            "unsupported-claim rate: " +
            " | ".join(f"{r['model']} {r['value']}%" for r in hal["ranking"]))

    # Retrieval is shared, so "better retrieval-based responses" can only mean
    # which model exploits identical context best.
    rag_scores = []
    for agg in aggregates:
        parts = [agg.get("correctness_pct"), agg.get("relevance_pct")]
        halluc = agg.get("hallucination_rate_pct")
        if all(p is not None for p in parts) and halluc is not None:
            rag_scores.append((agg["model"],
                               round(0.5 * parts[0] + 0.25 * parts[1] + 0.25 * (100 - halluc), 1)))
    if rag_scores:
        rag_scores.sort(key=lambda t: t[1], reverse=True)
        add("Which model provides better retrieval-based responses?",
            f"{rag_scores[0][0]}",
            "Retrieval itself is identical for every model (run once per question, "
            f"mean retrieval quality {retrieval.get('retrieval_quality_pct')}%), so this ranks how well "
            "each model uses the same context: 0.5 x correctness + 0.25 x relevance + "
            "0.25 x (100 - hallucination). " +
            " | ".join(f"{m} {s}" for m, s in rag_scores))

    tests = leaders["test_pass_rate"]
    if tests:
        add("Which model generates code with a higher test-pass rate?",
            _verdict_for(tests, "%"),
            " | ".join(
                f"{r['model']} {r['value']}% ({by_model[r['model']]['tests_passed']}/"
                f"{by_model[r['model']]['tests_total']} tests)" for r in tests["ranking"]))

    lat = leaders["latency"]
    if lat:
        slowest = lat["ranking"][-1]
        factor = round(slowest["value"] / lat["value"], 1) if lat["value"] else None
        add("Which model has lower response latency?", _verdict_for(lat),
            "mean generation time: " +
            " | ".join(f"{r['model']} {_fmt_ms(r['value'])}" for r in lat["ranking"]) +
            (f" - the slowest is {factor}x the fastest" if factor else ""))

    resource_bits = []
    counts: Dict[str, int] = {}
    measures = 0
    for key, label in (("gpu_memory", "peak VRAM"), ("system_memory", "peak system RAM"),
                       ("cpu", "mean CPU"), ("token_usage", "total tokens")):
        entry = leaders.get(key)
        if not entry:
            continue
        measures += 1
        counts[entry["model"]] = counts.get(entry["model"], 0) + 1
        unit = "MB" if "memory" in key else ("%" if key == "cpu" else "tokens")
        resource_bits.append(f"{label}: {entry['model']} lowest at {entry['value']} {unit}")
    if resource_bits:
        cheapest = max(counts, key=counts.get)
        add("Which model requires fewer computational resources?",
            f"{cheapest} (lowest on {counts[cheapest]} of {measures} resource measures)",
            "; ".join(resource_bits))

    if acc and lat:
        same = acc["model"] == lat["model"]
        add("Is the most accurate model also the most efficient?",
            "Yes" if same else "No",
            f"most accurate: {acc['model']} ({acc['value']}%); fastest: {lat['model']} "
            f"({_fmt_ms(lat['value'])}). " +
            (f"{acc['model']} answers in {_fmt_ms(by_model[acc['model']]['latency_ms_mean'])}, "
             f"{round(by_model[acc['model']]['latency_ms_mean'] / lat['value'], 1)}x the fastest model."
             if not same and lat["value"] else ""))

    return out


#: Human labels for the metric keys, used when reporting non-discriminating ones.
LEADER_LABELS = {
    "accuracy": "accuracy", "correctness": "correctness", "relevance": "relevance",
    "hallucination": "hallucination rate", "test_pass_rate": "test-pass rate",
    "latency": "response latency", "ttft": "time to first token",
    "token_usage": "token usage", "throughput": "throughput",
    "cpu": "CPU", "gpu_memory": "GPU memory", "system_memory": "system memory",
}


def _non_discriminating(leaders: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Metrics on which every model landed in the same tie band.

    A metric that cannot separate the candidates has told you nothing about
    them - only that the tasks were not hard enough to expose a difference. It
    is worth naming, because a reader scanning the table sees a highlighted
    winner and assumes it meant something.
    """
    out = []
    for key, leader in leaders.items():
        if not leader or not leader["is_tie"]:
            continue
        if len(leader["tied"]) != len(leader["ranking"]):
            continue
        out.append({
            "metric": key,
            "label": LEADER_LABELS.get(key, key),
            "value": leader["value"],
            "models": leader["tied"],
            "note": f"Every model scored {leader['value']} on {LEADER_LABELS.get(key, key)}. "
                    "This metric did not separate them, so no conclusion should be drawn from "
                    "which name the table highlights.",
        })
    return out


def _tradeoff_statement(leaders, by_model, correlations, pareto) -> Dict[str, Any]:
    """Is quality being paid for in latency and memory, or is it free?"""
    acc, lat = leaders.get("accuracy"), leaders.get("latency")
    front = [p["model"] for p in pareto["pareto_front"]]
    dominated = pareto["dominated"]

    lines: List[str] = []

    if acc and lat and acc["model"] != lat["model"]:
        accurate = by_model[acc["model"]]
        fast = by_model[lat["model"]]
        acc_gap = round(accurate["accuracy_pct"] - fast["accuracy_pct"], 1)
        lat_ratio = round(accurate["latency_ms_mean"] / fast["latency_ms_mean"], 2) \
            if fast["latency_ms_mean"] else None
        lines.append(
            f"There is a trade-off: {acc['model']} is {acc_gap} accuracy points ahead of "
            f"{lat['model']}, and pays {lat_ratio}x the mean latency for it "
            f"({_fmt_ms(accurate['latency_ms_mean'])} vs {_fmt_ms(fast['latency_ms_mean'])}).")
    elif acc and lat:
        lines.append(
            f"No trade-off appears in this run: {acc['model']} is both the most accurate "
            f"({acc['value']}%) and the fastest ({_fmt_ms(lat['value'])}).")

    corr = correlations.get("accuracy_vs_latency")
    if corr is not None:
        direction = ("slower models scored higher" if corr > 0.3 else
                     "faster models scored higher" if corr < -0.3 else
                     "accuracy and latency move independently")
        lines.append(
            f"Across the {correlations['n_models']} models, accuracy and mean latency correlate "
            f"at r = {corr} ({direction}). With only {correlations['n_models']} points this is a "
            "direction, not a law.")

    mem_corr = correlations.get("accuracy_vs_memory")
    if mem_corr is not None:
        lines.append(
            f"Accuracy against peak memory correlates at r = {mem_corr}: "
            + ("bigger models did buy accuracy here." if mem_corr > 0.3 else
               "spending more memory did not buy accuracy here."))

    if dominated:
        axes = pareto.get("axes") or ["accuracy", "latency", "memory"]
        listed = ", ".join(axes[:-1]) + " and " + axes[-1]
        lines.append(f"Dominated by another model on {listed} at once: " +
                     ", ".join(f"{d['model']} (beaten by {d['dominated_by']})" for d in dominated) +
                     ". Nothing argues for running these.")
    if front:
        lines.append("Worth considering, each best at something: " + ", ".join(front) + ".")

    return {"summary": lines, "pareto_front": front,
            "dominated": [d["model"] for d in dominated]}


def _recommend(leaders, by_model, pareto) -> Dict[str, Any]:
    """A default pick for this application, and when to override it."""
    acc, lat, hal = leaders.get("accuracy"), leaders.get("latency"), leaders.get("hallucination")
    front = [p["model"] for p in pareto["pareto_front"]]
    if not acc:
        return {"default": None, "reasons": []}

    # This assistant answers policy questions students act on, so a wrong
    # confident answer costs more than a slow one. Accuracy leads, unless a
    # Pareto-front model is close enough on accuracy to be worth the speed.
    #
    # When accuracy ties, taking whichever name sorted first would be an
    # arbitrary choice presented as a conclusion. Break it on hallucination
    # rate instead: between two equally accurate models, the one that invents
    # less is the one to put in front of students.
    default = acc["model"]
    tie_break = None
    if acc["is_tie"] and len(acc["tied"]) > 1:
        contenders = [m for m in acc["tied"] if by_model[m].get("hallucination_rate_pct") is not None]
        if contenders:
            default = min(contenders, key=lambda m: by_model[m]["hallucination_rate_pct"])
            names = acc["tied"]
            listed = (", ".join(names[:-1]) + " and " + names[-1]) if len(names) > 1 else names[0]
            tie_break = (
                f"{listed} tied on accuracy at {acc['value']}%; "
                f"{default} is chosen for the lower hallucination rate "
                f"({by_model[default]['hallucination_rate_pct']}% against "
                + ", ".join(f"{by_model[m]['hallucination_rate_pct']}% for {m}"
                            for m in acc["tied"] if m != default) + ")")

    alternative = None
    for model in front:
        if model == default:
            continue
        gap = acc["value"] - by_model[model]["accuracy_pct"]
        if gap <= 5 and by_model[model]["latency_ms_mean"] < by_model[default]["latency_ms_mean"]:
            alternative = {
                "model": model,
                "why": f"within {round(gap, 1)} accuracy points of {default} at "
                       f"{_fmt_ms(by_model[model]['latency_ms_mean'])} instead of "
                       f"{_fmt_ms(by_model[default]['latency_ms_mean'])}",
            }
            break

    return {
        "default": default,
        "why": (tie_break or f"highest accuracy at {acc['value']}%"
                + (f", lowest hallucination rate at {hal['value']}%"
                   if hal and hal["model"] == default else ""))
               + ". A policy assistant that answers wrongly but quickly is worse "
                 "than one that answers slowly.",
        "tie_break": tie_break,
        "faster_alternative": alternative,
        "interactive_pick": lat["model"] if lat else None,
    }


def _caveats(aggregates: List[Dict[str, Any]], retrieval: Dict[str, Any],
             leaders: Optional[Dict[str, Any]] = None) -> List[str]:
    """What these numbers cannot support, stated up front."""
    notes = [
        "Quality metrics are lexical, not semantic: a correct answer phrased entirely "
        "in synonyms of the ground truth scores lower than it deserves. They compare "
        "models against each other, not against an absolute standard.",
        "One run per question with a fixed seed and temperature 0.2. Ollama is not "
        "bit-deterministic across runs, so single-question differences of a few points "
        "are noise; only the aggregate over 30 questions is meaningful.",
        "CPU and system RAM are machine-wide readings taken while the laptop was doing "
        "other things. The idle baseline is recorded alongside them so they can be read "
        "as a delta rather than as absolutes.",
    ]
    if retrieval.get("misses"):
        notes.append(
            f"Retrieval missed the gold chunk entirely on {len(retrieval['misses'])} "
            f"question(s) ({', '.join(retrieval['misses'])}). No model can be marked wrong "
            "for those - the context never contained the answer.")
    ties = _non_discriminating({k: v for k, v in (leaders or {}).items()}) if leaders else []
    for tie in ties:
        notes.append(tie["note"])
    degraded = [a for a in aggregates if a.get("questions_failed")]
    if degraded:
        notes.append("Some questions failed to generate and are excluded from that model's "
                     "averages: " + ", ".join(f"{a['model']} ({a['questions_failed']})" for a in degraded))
    return notes
