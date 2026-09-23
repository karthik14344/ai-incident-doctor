"""Score one diagnosis against the ground truth of a recorded incident.

Root-cause identity (DECISIONS.md D-37): a hypothesis matches the truth when
  * the truth has a guilty commit and the hypothesis names that commit, or
  * the truth has no guilty commit, the hypothesis names none, and its
    component is one of the acceptable components.
"""

from typing import Any, Dict, List, Optional


def hypothesis_matches(h: Dict[str, Any], truth: Dict[str, Any]) -> bool:
    guilty = truth.get("guilty_commit")
    named = h.get("suspected_commit")
    if guilty:
        return bool(named) and named.lower().startswith(guilty.lower()[:12])
    return not named and h.get("component") in truth.get("acceptable_components", [truth.get("component")])


def score(diagnosis: Optional[Dict[str, Any]], report: Dict[str, Any], truth: Dict[str, Any]) -> Dict[str, Any]:
    ok = report.get("status") == "ok" and diagnosis is not None
    hyps: List[Dict[str, Any]] = (diagnosis or {}).get("hypotheses", []) if ok else []
    guilty = truth.get("guilty_commit")
    top = hyps[0] if hyps else {}
    retrieval = report.get("retrieval") or {}
    ranked = [r["sha"] for r in retrieval.get("ranked", [])]
    time_filtered = retrieval.get("time_filtered", [])
    verification = report.get("verification") or {}
    out = {
        "valid_output": ok,
        "class_correct": ok and diagnosis.get("incident_class") == truth["incident_class"],
        "class_correct_lenient": ok and diagnosis.get("incident_class") in truth.get("acceptable_classes", []),
        "acc_at_1": ok and bool(top) and hypothesis_matches(top, truth),
        "acc_at_3": ok and any(hypothesis_matches(h, truth) for h in hyps[:3]),
        "component_at_1": ok and bool(top) and top.get("component") in truth.get("acceptable_components", []),
        "blamed_a_commit": ok and bool(top.get("suspected_commit")),
        "blamed_any_commit": ok and any(h.get("suspected_commit") for h in hyps),
        "constraint_violations": len((diagnosis or {}).get("constraint_violations", [])) if ok else 0,
        "fix_kind": ((diagnosis or {}).get("fix") or {}).get("kind") if ok else None,
        "fix_verified": verification.get("status") == "verified",
        "fix_acceptance_passed": bool((verification.get("acceptance") or {}).get("passed")),
        "fix_diff_applied": bool(verification.get("applied")),
        "fix_edit_reversed": any("REVERSED_EDIT_CORRECTED" in p
                                 for p in (((diagnosis or {}).get("fix") or {}).get("edit_problems") or [])),
        "prompt_tokens": (report.get("usage") or {}).get("prompt_tokens", 0),
        "completion_tokens": (report.get("usage") or {}).get("completion_tokens", 0),
        "cost_usd": (report.get("usage") or {}).get("cost_usd", 0.0),
        "llm_calls": (report.get("usage") or {}).get("calls", 0),
        "reasoning_s": (report.get("timings") or {}).get("total_s"),
    }
    if guilty:
        out["guilty_in_time_filter"] = guilty in time_filtered
        out["guilty_in_retrieved"] = guilty in ranked
        out["guilty_rank"] = ranked.index(guilty) + 1 if guilty in ranked else None
        out["time_filter_size"] = len(time_filtered)
    else:
        out["false_attribution"] = out["blamed_a_commit"]
    return out


def most_recent_deploy_baseline(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """'Always blame the most recent deploy': its newest commit, class code_defect.

    The component is the first service that deploy changed (or gateway)."""
    from app.retrieval import effective_candidates

    latest = bundle.get("latest_deploy") or {}
    commits = latest.get("commits") or ([latest["git_sha"]] if latest.get("git_sha") else [])
    # Same scope as the doctor (the patient's own commits), so the baseline is
    # not handicapped by blaming a change to the doctor or the docs tooling.
    in_scope = {c["sha"] for c in effective_candidates(bundle)}
    scoped = [c for c in commits if c in in_scope]
    commits = scoped or commits
    services = [s for s in latest.get("services_changed", []) if s in
                ("gateway", "ingestion", "retrieval", "llm")] or ["gateway"]
    sha = commits[-1] if commits else None
    return {"summary": "the most recent deploy broke it", "incident_class": "code_defect",
            "hypotheses": [{"cause": f"deploy {latest.get('short_sha')}", "component": services[0],
                            "confidence": 1.0, "evidence": [], "suspected_commit": sha}],
            "fix": {"kind": "action", "action": "roll back the most recent deploy"},
            "constraint_violations": [],
            "_deploy_commits": commits}
