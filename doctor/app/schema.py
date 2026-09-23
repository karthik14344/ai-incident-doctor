"""The diagnosis the model must return - schema-constrained JSON, never prose.

Fixes are requested as search/replace edits rather than a raw unified diff:
small models almost never produce a diff that `git apply` accepts (wrong hunk
counts, missing context), while an exact "find this, replace with that" edit is
easy to get right. The doctor renders the edits into a real unified diff itself
(`fixes.edits_to_diff`), which is what the report shows and verification applies.
A model may still return a raw `diff`; it is used when it applies cleanly.
"""

from typing import Any, Dict, List, Optional

import jsonschema

INCIDENT_CLASSES = ["code_defect", "configuration", "capacity", "dependency_failure", "data_issue"]
COMPONENTS = ["gateway", "ingestion", "retrieval", "llm", "ollama", "chroma", "knowledge_base", "infrastructure"]
FIX_KINDS = ["code_diff", "config_change", "action"]

DIAGNOSIS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["summary", "incident_class", "demand_vs_capacity", "hypotheses", "fix"],
    "properties": {
        "summary": {"type": "string"},
        "incident_class": {"type": "string", "enum": INCIDENT_CLASSES},
        "demand_vs_capacity": {
            "type": "object",
            "required": ["traffic_change", "deploy_before_onset", "verdict", "reasoning"],
            "properties": {
                "traffic_change": {"type": "string", "enum": ["rose", "flat", "fell", "unknown"]},
                "deploy_before_onset": {"type": "boolean"},
                "verdict": {"type": "string", "enum": ["demand_rose", "capacity_fell", "neither"]},
                "reasoning": {"type": "string"},
            },
        },
        "hypotheses": {
            "type": "array", "minItems": 1, "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["cause", "component", "confidence", "evidence", "suspected_commit"],
                "properties": {
                    "cause": {"type": "string"},
                    "component": {"type": "string", "enum": COMPONENTS},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "suspected_commit": {"type": ["string", "null"]},
                    "suspected_files": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "fix": {
            "type": "object",
            "required": ["kind", "rationale"],
            "properties": {
                "kind": {"type": "string", "enum": FIX_KINDS},
                "edits": {
                    "type": "array",
                    "items": {"type": "object", "required": ["file", "find", "replace"],
                              "properties": {"file": {"type": "string"}, "find": {"type": "string"},
                                             "replace": {"type": "string"}}},
                },
                "diff": {"type": ["string", "null"]},
                "action": {"type": ["string", "null"]},
                "rationale": {"type": "string"},
            },
        },
    },
}


def schema_errors(obj: Any) -> List[str]:
    validator = jsonschema.Draft202012Validator(DIAGNOSIS_SCHEMA)
    return [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in sorted(validator.iter_errors(obj), key=lambda e: list(e.path))][:12]


def resolve_sha(value: Optional[str], candidates: List[str]) -> Optional[str]:
    """Normalise a model-given SHA (prefix, any case) to a full candidate SHA."""
    if not value or str(value).strip().lower() in ("null", "none", ""):
        return None
    v = str(value).strip().lower()
    matches = [c for c in candidates if c.lower().startswith(v) or v.startswith(c.lower()[:7])]
    return matches[0] if len(matches) == 1 else None


def semantic_errors(obj: Dict[str, Any], candidates: List[str]) -> List[str]:
    """Rules the JSON schema cannot express."""
    errs = []
    for i, h in enumerate(obj.get("hypotheses", [])):
        sha = h.get("suspected_commit")
        if sha not in (None, "", "null") and resolve_sha(sha, candidates) is None:
            errs.append(f"hypotheses/{i}/suspected_commit: '{sha}' is not one of the candidate commits; "
                        f"use a SHA from the list or null")
    if obj.get("incident_class") == "capacity":
        for i, h in enumerate(obj.get("hypotheses", [])[:1]):
            if h.get("suspected_commit") not in (None, "", "null"):
                errs.append(f"hypotheses/{i}/suspected_commit must be null for a capacity incident: "
                            f"capacity means demand exceeded resources, not that a change broke something")
    kind = (obj.get("fix") or {}).get("kind")
    if kind in ("code_diff", "config_change") and not ((obj.get("fix") or {}).get("edits") or
                                                       (obj.get("fix") or {}).get("diff")):
        errs.append("fix: a code_diff or config_change needs 'edits' (or a 'diff')")
    return errs
