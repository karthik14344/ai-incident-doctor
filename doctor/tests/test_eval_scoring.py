"""Scoring, the most-recent-deploy baseline, aggregation and table rendering."""

import os
import sys

EVAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval")
sys.path.insert(0, EVAL)

from scoring import hypothesis_matches, most_recent_deploy_baseline, score  # noqa: E402

G = "a" * 40
PUSH_TRUTH = {"delivery": "push", "incident_class": "code_defect", "acceptable_classes": ["code_defect"],
              "component": "retrieval", "acceptable_components": ["retrieval"], "guilty_commit": G,
              "acceptance_test": "faults/acceptance/test_x.py"}
ENV_TRUTH = {"delivery": "environment", "incident_class": "capacity", "acceptable_classes": ["capacity"],
             "component": "ollama", "acceptable_components": ["ollama", "llm"], "guilty_commit": None,
             "acceptance_test": None}


def diag(cls, commit, component="retrieval"):
    return {"incident_class": cls, "hypotheses": [{"cause": "c", "component": component, "confidence": 0.9,
                                                   "evidence": [], "suspected_commit": commit}],
            "fix": {"kind": "action"}, "constraint_violations": []}


def test_naming_the_guilty_commit_is_a_hit():
    assert hypothesis_matches({"suspected_commit": G}, PUSH_TRUTH)
    assert not hypothesis_matches({"suspected_commit": "b" * 40}, PUSH_TRUTH)
    assert not hypothesis_matches({"suspected_commit": None, "component": "retrieval"}, PUSH_TRUTH)


def test_no_commit_truth_needs_no_commit_and_the_right_component():
    assert hypothesis_matches({"suspected_commit": None, "component": "llm"}, ENV_TRUTH)
    assert not hypothesis_matches({"suspected_commit": G, "component": "ollama"}, ENV_TRUTH)
    assert not hypothesis_matches({"suspected_commit": None, "component": "gateway"}, ENV_TRUTH)


def test_blaming_a_commit_for_capacity_is_a_false_attribution():
    s = score(diag("capacity", G, "ollama"), {"status": "ok"}, ENV_TRUTH)
    assert s["false_attribution"] is True and s["acc_at_1"] is False and s["class_correct"] is True
    s2 = score(diag("capacity", None, "ollama"), {"status": "ok"}, ENV_TRUTH)
    assert s2["false_attribution"] is False and s2["acc_at_1"] is True


def test_retrieval_fields_only_for_push_faults():
    report = {"status": "ok", "retrieval": {"ranked": [{"sha": G}], "time_filtered": [G, "c" * 40]}}
    s = score(diag("code_defect", G), report, PUSH_TRUTH)
    assert s["guilty_in_retrieved"] and s["guilty_rank"] == 1 and s["time_filter_size"] == 2
    assert "false_attribution" not in s


def test_a_failed_report_scores_nothing():
    s = score(None, {"status": "failed"}, PUSH_TRUTH)
    assert not any(s[k] for k in ("valid_output", "acc_at_1", "acc_at_3", "class_correct"))


def test_the_baseline_blames_the_newest_commit_of_the_latest_deploy():
    bundle = {"latest_deploy": {"short_sha": "abc1234", "commits": ["1" * 40, G], "services_changed": ["retrieval"]}}
    d = most_recent_deploy_baseline(bundle)
    assert d["hypotheses"][0]["suspected_commit"] == G
    assert d["incident_class"] == "code_defect"
    assert score(d, {"status": "ok"}, PUSH_TRUTH)["acc_at_1"] is True
    assert score(d, {"status": "ok"}, ENV_TRUTH)["false_attribution"] is True


def test_aggregation_reports_spread_across_repeats_and_splits_by_delivery():
    from report_tables import write_markdown
    from run_eval import aggregate, by_delivery

    rows = []
    for rep, hit in ((0, True), (1, False), (2, True)):
        for truth in (PUSH_TRUTH, ENV_TRUTH):
            d = diag("code_defect", G) if truth is PUSH_TRUTH and hit else diag("capacity", None, "ollama")
            rows.append({"incident": truth["delivery"], "repeat": rep, "truth": truth,
                         "score": score(d, {"status": "ok"}, truth)})
    agg = aggregate([r for r in rows if r["truth"] is PUSH_TRUTH], 3)
    assert agg["acc_at_1"]["mean"] == round(2 / 3, 3)
    assert agg["acc_at_1"]["min"] == 0.0 and agg["acc_at_1"]["max"] == 1.0
    split = by_delivery(rows, 3)
    assert split["environment"]["false_attribution"]["mean"] == 0.0
    md = write_markdown({"generated": "t", "incidents": ["a", "b"], "repeats": 3, "primary_model": "ollama:llama3",
                         "primary_is_cloud": False, "skipped": [], "groups": {"ablation|logs_only|ollama:llama3": split},
                         "baseline_most_recent_deploy": split, "baseline_deploy_hit": {}, "retrieval": [],
                         "live_timings": []})
    assert "environment faults" in md and "push faults" in md and "0.67 (0.00-1.00)" in md
