"""One diagnosis: evidence bundle in, validated report out."""

import time
from typing import Any, Dict, List, Optional

from app import fixes, prompt, verify
from app.collectors import iso
from app.llm import BudgetExceeded, CallBudget, ProviderError, make_provider, parse_json
from app.retrieval import past_incidents, rank_commits, relevant_code
from app.schema import DIAGNOSIS_SCHEMA, resolve_sha, schema_errors, semantic_errors
from app.settings import SETTINGS, ProviderConfig, Settings


def _normalise(obj: Dict[str, Any], candidates: List[str]) -> Dict[str, Any]:
    """Enforce the rules the model was told, and record every time it broke one."""
    violations = []
    for h in obj.get("hypotheses", []):
        raw = h.get("suspected_commit")
        resolved = resolve_sha(raw, candidates)
        if raw not in (None, "", "null") and resolved is None:
            violations.append(f"named a commit that is not a candidate: {raw}")
            h["suspected_commit_raw"] = raw
        h["suspected_commit"] = resolved
        try:
            h["confidence"] = max(0.0, min(1.0, float(h.get("confidence", 0))))
        except (TypeError, ValueError):
            h["confidence"] = 0.0
    obj["hypotheses"] = sorted(obj.get("hypotheses", []), key=lambda h: -h["confidence"])[:3]
    if obj.get("incident_class") == "capacity" and any(h.get("suspected_commit") for h in obj["hypotheses"][:1]):
        violations.append("blamed a commit while classifying the incident as capacity")
    obj["constraint_violations"] = violations
    return obj


def _call(cfg: ProviderConfig, built: Dict[str, Any], budget: CallBudget, seed: int = 7,
          max_tokens: int = 2500) -> Dict[str, Any]:
    provider = make_provider(cfg)
    usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "seconds": 0.0}

    def account(c):
        usage["calls"] += c.attempts
        usage["prompt_tokens"] += c.prompt_tokens
        usage["completion_tokens"] += c.completion_tokens
        usage["cost_usd"] = round(usage["cost_usd"] + c.cost_usd, 6)
        usage["seconds"] = round(usage["seconds"] + c.seconds, 2)

    comp = provider.complete(built["system"], built["user"], DIAGNOSIS_SCHEMA, budget, seed=seed, max_tokens=max_tokens)
    account(comp)
    repaired, errors = False, []
    try:
        obj = parse_json(comp.text)
        errors = schema_errors(obj) or semantic_errors(obj, built["candidates"])
    except ValueError as exc:
        obj, errors = None, [str(exc)]
    if errors:
        repaired = True
        comp2 = provider.complete(built["system"], built["user"] + "\n\n" + prompt.repair(comp.text, errors),
                                  DIAGNOSIS_SCHEMA, budget, seed=seed, max_tokens=max_tokens)
        account(comp2)
        try:
            obj2 = parse_json(comp2.text)
            errs2 = schema_errors(obj2)
            if not errs2:
                obj, errors = obj2, semantic_errors(obj2, built["candidates"])
            elif obj is None:
                raise ValueError("; ".join(errs2))
        except ValueError:
            if obj is None or schema_errors(obj):
                raise
    return {"diagnosis": obj, "usage": usage, "repaired": repaired, "remaining_errors": errors,
            "provider": cfg.provider, "model": cfg.model}


def diagnose(bundle: Dict[str, Any], arm: str = "logs_commits_incidents",
             providers: Optional[List[ProviderConfig]] = None, settings: Settings = SETTINGS,
             verify_fix: bool = True, acceptance_tests: Optional[List[str]] = None,
             incident_index: str = "incidents", use_embeddings: bool = True,
             verification_cache: Optional[Dict[str, Any]] = None, seed: int = 7) -> Dict[str, Any]:
    started = time.perf_counter()
    providers = providers or [p for p in (settings.primary, settings.fallback) if p]
    live_sha = (bundle.get("live_deploy") or {}).get("git_sha")

    ranked = rank_commits(bundle, settings, use_embeddings=use_embeddings) if arm != "logs_only" else None
    code: List[Dict[str, Any]] = []
    if arm != "logs_only" and use_embeddings:
        files = [s["path"] for s in bundle.get("sources", [])]
        by_sha = {c["sha"]: c for c in bundle.get("candidate_commits", [])}
        for r in (ranked or {}).get("ranked", [])[:2]:
            files.extend(f["path"] for f in by_sha[r["sha"]]["files"] if f["path"].endswith(".py"))
        code = relevant_code(bundle, list(dict.fromkeys(files)), settings)
    incidents = (past_incidents(bundle, settings, index_name=incident_index)
                 if arm == "logs_commits_incidents" and use_embeddings else [])
    built = prompt.build(bundle, arm, ranked, code, incidents, max_tokens=settings.max_prompt_tokens)
    retrieval_s = round(time.perf_counter() - started, 2)

    budget = CallBudget(settings.max_calls_per_run)
    attempts, outcome = [], None
    for cfg in providers:
        try:
            outcome = _call(cfg, built, budget, seed=seed, max_tokens=settings.max_completion_tokens)
            break
        except (ProviderError, BudgetExceeded, ValueError) as exc:
            attempts.append({"provider": cfg.label, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
    report: Dict[str, Any] = {
        "incident_id": bundle["id"], "arm": arm, "alert": bundle["alert"],
        "created_at": iso(time.time()), "live_sha": live_sha,
        "retrieval": {"time_filtered": (ranked or {}).get("time_filtered", []),
                      "ranked": (ranked or {}).get("ranked", []),
                      "embedding_used": (ranked or {}).get("embedding_used", False),
                      "note": (ranked or {}).get("note"),
                      "code_chunks": [f"{c['path']}::{c['name']}" for c in code],
                      "past_incidents": [p["id"] for p in incidents]},
        "prompt_tokens_estimate": built["approx_prompt_tokens"],
        "provider_failures": attempts,
    }
    if outcome is None:
        report.update({"status": "failed", "error": "every provider failed", "timings": {
            "retrieval_s": retrieval_s, "total_s": round(time.perf_counter() - started, 2)}})
        return report

    diagnosis = _normalise(outcome["diagnosis"], built["candidates"])
    fix = diagnosis.get("fix") or {}
    rendered = {"diff": fix.get("diff") or "", "files": [], "problems": []}
    if fix.get("edits") and live_sha:
        rendered = fixes.edits_to_diff(settings.repo_root, live_sha, fix["edits"])
        if not rendered["diff"] and fix.get("diff"):
            rendered["diff"] = fix["diff"]
    fix["unified_diff"] = rendered["diff"]
    fix["edit_problems"] = rendered["problems"]

    verification: Dict[str, Any]
    if not verify_fix:
        verification = {"status": "skipped"}
    elif fix.get("kind") in ("code_diff", "config_change") and live_sha:
        key = f"{live_sha}:{hash(rendered['diff'])}:{','.join(acceptance_tests or [])}"
        if verification_cache is not None and key in verification_cache:
            verification = {**verification_cache[key], "cached": True}
        else:
            verification = verify.verify_code_fix(settings.repo_root, live_sha, rendered["diff"], acceptance_tests)
            if verification_cache is not None:
                verification_cache[key] = verification
    else:
        verification = {"status": verify.UNVERIFIED if fix.get("kind") == "action" else verify.NOT_APPLICABLE,
                        "reason": "an operational action cannot be tested on a copy; a human must carry it out"}

    report.update({
        "status": "ok", "provider": outcome["provider"], "model": outcome["model"],
        "diagnosis": diagnosis, "repaired": outcome["repaired"], "remaining_errors": outcome["remaining_errors"],
        "usage": outcome["usage"], "verification": verification,
        "timings": {"retrieval_s": retrieval_s, "llm_s": outcome["usage"]["seconds"],
                    "total_s": round(time.perf_counter() - started, 2)},
    })
    return report
