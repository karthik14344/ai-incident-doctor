"""Unit tests for the doctor. No services, no Ollama, no network."""

import importlib.util
import json
import os
import subprocess

import pytest

from app import fixes, llm, prompt, reasoner, retrieval, schema, signatures
from app.settings import ProviderConfig, Settings

from conftest import REPO_ROOT


# ---------------------------------------------------------------- signatures

def _patient_obs():
    path = os.path.join(REPO_ROOT, "patient", "common", "obs.py")
    spec = importlib.util.spec_from_file_location("patient_obs", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("exc_type,msg", [
    ("ConnectError", "All connection attempts failed"),
    ("KeyError", "missing chunk 3f2a9c1e-77aa-4b0e-9d7e-0a1b2c3d4e5f at offset 812"),
    ("NameError", "name 'txt' is not defined"),
    ("ReadTimeout", "timed out after 3.0 seconds talking to http://llm:8003/generate"),
    ("TEXT", "[Embedder] Ollama embedding call failed (timed out). Using robust fallback vectorizer."),
])
def test_doctor_signature_matches_the_patients(exc_type, msg):
    assert signatures.signature(exc_type, msg) == _patient_obs().signature(exc_type, msg)


# ---------------------------------------------------------------- schema

GOOD = {
    "summary": "retrieval down", "incident_class": "dependency_failure",
    "demand_vs_capacity": {"traffic_change": "flat", "deploy_before_onset": False, "verdict": "capacity_fell",
                           "reasoning": "r"},
    "hypotheses": [{"cause": "retrieval unreachable", "component": "retrieval", "confidence": 0.8,
                    "evidence": ["ConnectError"], "suspected_commit": None}],
    "fix": {"kind": "action", "action": "restart retrieval", "rationale": "r"},
}


def test_a_valid_diagnosis_passes_the_schema():
    assert schema.schema_errors(GOOD) == []


def test_an_unknown_incident_class_is_rejected():
    bad = {**GOOD, "incident_class": "network_gremlins"}
    assert any("incident_class" in e for e in schema.schema_errors(bad))


def test_capacity_with_a_blamed_commit_is_a_semantic_error():
    bad = json.loads(json.dumps(GOOD))
    bad["incident_class"] = "capacity"
    bad["hypotheses"][0]["suspected_commit"] = "abcdef1"
    errs = schema.semantic_errors(bad, ["abcdef1234567890"])
    assert any("must be null for a capacity incident" in e for e in errs)


def test_a_sha_outside_the_candidates_is_an_error_and_prefixes_resolve():
    assert schema.resolve_sha("abcdef1", ["abcdef1234567890"]) == "abcdef1234567890"
    assert schema.resolve_sha("1234567", ["abcdef1234567890"]) is None
    bad = json.loads(json.dumps(GOOD))
    bad["hypotheses"][0]["suspected_commit"] = "deadbee"
    assert schema.semantic_errors(bad, ["abcdef1234567890"])


def test_normalise_nulls_unknown_shas_and_flags_capacity_blame():
    obj = json.loads(json.dumps(GOOD))
    obj["incident_class"] = "capacity"
    obj["hypotheses"][0]["suspected_commit"] = "abcdef1"
    out = reasoner._normalise(obj, ["abcdef1234567890"])
    assert out["hypotheses"][0]["suspected_commit"] == "abcdef1234567890"
    assert any("capacity" in v for v in out["constraint_violations"])
    obj2 = json.loads(json.dumps(GOOD))
    obj2["hypotheses"][0]["suspected_commit"] = "not-a-sha"
    out2 = reasoner._normalise(obj2, ["abcdef1234567890"])
    assert out2["hypotheses"][0]["suspected_commit"] is None
    assert out2["constraint_violations"]


# ---------------------------------------------------------------- json parsing

@pytest.mark.parametrize("text", [
    '{"a": 1}',
    'Sure! Here it is:\n```json\n{"a": 1}\n```',
    '<think>hmm {not json}</think> {"a": 1} trailing words',
])
def test_parse_json_tolerates_wrappers(text):
    assert llm.parse_json(text) == {"a": 1}


def test_budget_stops_runaway_calls():
    b = llm.CallBudget(2)
    b.take()
    b.take()
    with pytest.raises(llm.BudgetExceeded):
        b.take()


# ---------------------------------------------------------------- fixes

@pytest.fixture
def tiny_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "patient" / "svc").mkdir(parents=True)
    (repo / "patient" / "svc" / "mod.py").write_text("TIMEOUT = 10.0\n\n\ndef f():\n    return TIMEOUT\n")
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return str(repo), sha


def test_edits_render_as_a_diff_that_applies(tiny_repo):
    repo, sha = tiny_repo
    out = fixes.edits_to_diff(repo, sha, [{"file": "patient/svc/mod.py", "find": "TIMEOUT = 10.0",
                                           "replace": "TIMEOUT = 45.0"}])
    assert out["problems"] == []
    assert "-TIMEOUT = 10.0" in out["diff"] and "+TIMEOUT = 45.0" in out["diff"]
    with fixes.Sandbox(repo, sha) as box:
        ok, msg = box.patch(out["diff"])
        assert ok, msg
        assert "45.0" in open(os.path.join(box.dir, "patient", "svc", "mod.py")).read()


def test_indentation_drift_in_find_is_tolerated(tiny_repo):
    repo, sha = tiny_repo
    out = fixes.edits_to_diff(repo, sha, [{"file": "patient/svc/mod.py", "find": "def f():\n  return TIMEOUT",
                                           "replace": "def f():\n  return TIMEOUT * 2"}])
    assert "+    return TIMEOUT * 2" in out["diff"]


def test_a_find_that_matches_nothing_is_reported(tiny_repo):
    repo, sha = tiny_repo
    out = fixes.edits_to_diff(repo, sha, [{"file": "patient/svc/mod.py", "find": "nope", "replace": "x"}])
    assert out["diff"] == "" and out["problems"]


# ---------------------------------------------------------------- retrieval

def _bundle(**over):
    b = {
        "id": "inc_test", "t_alert": 1000.0,
        "alert": {"alertname": "EmbeddingFallbackActive", "labels": {"service": "retrieval", "severity": "warning"},
                  "annotations": {"summary": "embedding fallback counter rose"}, "startsAt": "2026-09-23T10:00:00Z"},
        "windows": {"incident": ["a", "b"], "baseline": ["c", "d"]},
        "related_alerts": [], "logs": [], "sources": [], "deploys": [], "live_deploy": None,
        "metrics": {"embedding_fallbacks_per_min": {"meaning": "", "series": {
            "service=retrieval": {"baseline": {"mean": 0.0, "max": 0.0}, "incident": {"mean": 5, "max": 12}}}},
            "traffic_rps": {"meaning": "", "series": {
                "all": {"baseline": {"mean": 1.0, "max": 1.2}, "incident": {"mean": 1.1, "max": 1.3}}}}},
        "candidate_commits": [
            {"sha": "a" * 40, "subject": "Docs: clarify README", "date": "d", "deployed_in": "x",
             "files": [{"path": "README.md", "diff": "+more words about setup"}]},
            {"sha": "b" * 40, "subject": "Tighten embedding call timeout", "date": "d", "deployed_in": "x",
             "files": [{"path": "patient/ingestion_service/app/embedder.py",
                        "diff": "-EMBED_TIMEOUT_S = 45.0\n+EMBED_TIMEOUT_S = 10.0"}]},
        ],
    }
    b.update(over)
    return b


def test_notable_changes_find_the_fallback_rise_but_not_flat_traffic():
    changes = retrieval.notable_metric_changes(_bundle())
    names = {c["metric"] for c in changes}
    assert "embedding_fallbacks_per_min" in names
    assert "traffic_rps" not in names


def test_lexical_ranking_puts_the_relevant_commit_first():
    out = retrieval.rank_commits(_bundle(), use_embeddings=False)
    assert out["time_filtered"] == ["a" * 40, "b" * 40]
    assert out["ranked"][0]["sha"] == "b" * 40
    assert "embed" in out["ranked"][0]["matched_terms"] or "timeout" in out["ranked"][0]["matched_terms"]


def test_no_deploys_means_no_candidates():
    out = retrieval.rank_commits(_bundle(candidate_commits=[]), use_embeddings=False)
    assert out["ranked"] == [] and out["time_filtered"] == []


# ---------------------------------------------------------------- prompt

def test_logs_only_arm_shows_no_commits():
    built = prompt.build(_bundle(), "logs_only")
    assert "CANDIDATE COMMITS" not in built["user"]
    assert built["candidates"] == []


def test_commit_arm_lists_only_ranked_candidates_and_the_fork():
    ranked = retrieval.rank_commits(_bundle(), use_embeddings=False)
    built = prompt.build(_bundle(), "logs_commits", ranked)
    assert "b" * 40 in built["user"]
    assert "DEMAND VERSUS CAPACITY" in built["system"]
    assert set(built["candidates"]) == {"a" * 40, "b" * 40}


def test_prompt_is_trimmed_to_the_token_budget():
    big = _bundle()
    big["sources"] = [{"path": "p", "sha": "x", "excerpt": "line\n" * 20000}]
    built = prompt.build(big, "logs_only", max_tokens=3000)
    assert built["approx_prompt_tokens"] <= 3300


# ---------------------------------------------------------------- end to end with a scripted model

class ScriptedProvider:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def complete(self, system, user, schema_, budget, **kw):
        budget.take()
        return llm.Completion(text=self.outputs.pop(0), provider="scripted", model="m", prompt_tokens=100,
                              completion_tokens=50, seconds=0.01)


def test_diagnose_repairs_an_invalid_first_answer(monkeypatch):
    bad = json.dumps({**GOOD, "incident_class": "capacity",
                      "hypotheses": [{**GOOD["hypotheses"][0], "suspected_commit": "b" * 7}]})
    fixed = json.dumps({**GOOD, "incident_class": "capacity"})
    scripted = ScriptedProvider([bad, fixed])
    monkeypatch.setattr(reasoner, "make_provider", lambda cfg: scripted)
    out = reasoner.diagnose(_bundle(), arm="logs_commits", providers=[ProviderConfig("fake", "m")],
                            settings=Settings(), verify_fix=False, use_embeddings=False)
    assert out["status"] == "ok"
    assert out["repaired"] is True
    assert out["diagnosis"]["hypotheses"][0]["suspected_commit"] is None
    assert out["usage"]["calls"] == 2


def test_diagnose_falls_back_to_the_second_provider(monkeypatch):
    class Broken:
        def complete(self, *a, **k):
            raise llm.ProviderError("HTTP 401", retryable=False)

    providers = {"primary": Broken(), "fallback": ScriptedProvider([json.dumps(GOOD)])}
    monkeypatch.setattr(reasoner, "make_provider", lambda cfg: providers[cfg.provider])
    out = reasoner.diagnose(_bundle(), arm="logs_only",
                            providers=[ProviderConfig("primary", "m"), ProviderConfig("fallback", "m")],
                            settings=Settings(), verify_fix=False, use_embeddings=False)
    assert out["status"] == "ok" and out["provider"] == "fallback"
    assert out["provider_failures"][0]["provider"] == "primary:m"


def test_every_provider_failing_is_a_failed_report_not_a_crash(monkeypatch):
    class Broken:
        def complete(self, *a, **k):
            raise llm.ProviderError("down", retryable=False)

    monkeypatch.setattr(reasoner, "make_provider", lambda cfg: Broken())
    out = reasoner.diagnose(_bundle(), arm="logs_only", providers=[ProviderConfig("x", "m")],
                            settings=Settings(), verify_fix=False, use_embeddings=False)
    assert out["status"] == "failed"


def test_python_chunking_is_by_function_and_keeps_imports():
    from app.indexes import chunk_python

    src = "import os\nfrom x import y\n\nA = 1\n\ndef f():\n    return 1\n\nclass C:\n    def m(self):\n        pass\n"
    chunks = chunk_python("patient/m.py", src)
    names = {c["name"] for c in chunks}
    assert {"f", "C", "<module>"} <= names
    assert all("os" in c["imports"] and "x" in c["imports"] for c in chunks)


@pytest.mark.parametrize("value", ["2026-09-23T05:53:25.51+00:00", "2026-09-23T05:53:25Z",
                                   "2026-09-23T05:53:25.123456789Z", "2026-09-23T05:53:25.9Z"])
def test_timestamps_of_any_precision_parse(value):
    from app.collectors import parse_ts

    assert abs(parse_ts(value) - parse_ts("2026-09-23T05:53:25Z")) < 1
