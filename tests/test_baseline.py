"""Tests for baseline aggregation across repeated runs.

The point of a baseline is to survive nondeterminism, so the cases that matter
are the ones where runs disagree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pramana.eval.baseline import (
    _unmatched_per_run,
    aggregate,
    compare,
    render_comparison,
    render_markdown,
)


def _run(tmp: Path, name: str, rows: list[dict], control_fp: int = 0) -> Path:
    payload = {
        "true_positive_findings": sum(r["true_positive_findings"] for r in rows),
        "total_known_bugs": sum(r["n_known_bugs"] for r in rows),
        "negative_control_fixtures": [r["fixture"] for r in rows if r["n_known_bugs"] == 0],
        "negative_control_false_positives": control_fp,
        "negative_control_proven_false_positives": 0,
        "fixtures": rows,
    }
    path = tmp / name
    path.write_text(json.dumps(payload))
    return path


def _row(fixture: str, tp: int, known: int, confirmed: int = 1, candidates: int = 1) -> dict:
    return {
        "fixture": fixture,
        "config": "anthropic:claude-opus-4-8",
        "n_candidates": candidates,
        "n_confirmed": confirmed,
        "confirmed_poc_pass": tp,
        "true_positive_findings": tp,
        "n_known_bugs": known,
        "error": None,
    }


def test_identical_runs_are_reported_as_deterministic(tmp_path):
    runs = [_run(tmp_path, f"r{i}.json", [_row("a", 1, 1)]) for i in range(3)]
    b = aggregate(runs, "Phase 0")

    assert b["n_runs"] == 3
    assert b["true_positives_per_run"] == [1, 1, 1]
    assert b["true_positives_min"] == b["true_positives_max"] == 1
    assert b["fully_deterministic"] is True


def test_disagreeing_runs_produce_a_range_and_flag_instability(tmp_path):
    """The case a single-run baseline cannot express: 2, then 1, then 2."""
    runs = [
        _run(tmp_path, "r1.json", [_row("a", 1, 1), _row("b", 1, 1)]),
        _run(tmp_path, "r2.json", [_row("a", 1, 1), _row("b", 0, 1)]),
        _run(tmp_path, "r3.json", [_row("a", 1, 1), _row("b", 1, 1)]),
    ]
    b = aggregate(runs, "Phase 0")

    assert b["true_positives_per_run"] == [2, 1, 2]
    assert b["true_positives_min"] == 1
    assert b["true_positives_max"] == 2
    assert b["true_positives_mean"] == 1.67
    assert b["fully_deterministic"] is False

    by_name = {f["fixture"]: f for f in b["fixtures"]}
    assert by_name["a"]["stable_across_runs"] is True
    assert by_name["b"]["stable_across_runs"] is False
    # The floor, not the average, is what a later phase must not fall below.
    assert "must not fall below **1**" in render_markdown(b)


def test_negative_control_false_positives_are_tracked_per_run(tmp_path):
    runs = [
        _run(tmp_path, "r1.json", [_row("a", 1, 1), _row("ctl", 0, 0, confirmed=0)], control_fp=0),
        _run(tmp_path, "r2.json", [_row("a", 1, 1), _row("ctl", 0, 0, confirmed=1)], control_fp=1),
    ]
    b = aggregate(runs, "Phase 0")

    assert b["negative_control_false_positives_per_run"] == [0, 1]
    by_name = {f["fixture"]: f for f in b["fixtures"]}
    assert by_name["ctl"]["is_negative_control"] is True
    assert by_name["a"]["is_negative_control"] is False
    assert "must not exceed **1**" in render_markdown(b)


def test_aggregate_refuses_runs_with_errored_fixtures(tmp_path):
    """Exhausted API credits mid-sweep score every remaining fixture 0. Folding
    that in would record an infrastructure failure as a capability measurement
    and drag the regression floor to zero."""
    good = _run(tmp_path, "r1.json", [_row("a", 1, 1)])
    bad_row = _row("a", 0, 1)
    bad_row["error"] = "ProviderError: credit balance is too low"
    bad = _run(tmp_path, "r2.json", [bad_row])

    with pytest.raises(SystemExit, match="errored fixtures"):
        aggregate([good, bad], "Phase 1")


def test_aggregate_names_the_run_and_fixtures_that_failed(tmp_path):
    row = _row("a", 0, 1)
    row["error"] = "ProviderError: overloaded"
    with pytest.raises(SystemExit, match=r"r1\.json: a"):
        aggregate([_run(tmp_path, "r1.json", [row])], "Phase 0")


def test_comparison_passes_when_the_candidate_holds_the_gate(tmp_path):
    old = aggregate([_run(tmp_path, "o1.json", [_row("a", 1, 1)])], "Phase 0")
    new = aggregate([_run(tmp_path, "n1.json", [_row("a", 1, 1)])], "Phase 1")

    c = compare(new, old)
    assert c["passed"] is True
    assert c["true_positive_regression"] is False
    assert "No regression" in render_comparison(c)


def test_comparison_flags_a_true_positive_regression(tmp_path):
    old = aggregate([_run(tmp_path, "o1.json", [_row("a", 1, 1), _row("b", 1, 1)])], "Phase 0")
    new = aggregate([_run(tmp_path, "n1.json", [_row("a", 1, 1), _row("b", 0, 1)])], "Phase 1")

    c = compare(new, old)
    assert c["passed"] is False
    assert c["true_positive_regression"] is True
    assert c["true_positive_floor"] == 2
    assert c["candidate_true_positive_floor"] == 1
    assert "Regression" in render_comparison(c)


def test_comparison_flags_new_negative_control_false_positives(tmp_path):
    """Recall can hold steady while precision collapses; the gate must catch it."""
    old = aggregate(
        [_run(tmp_path, "o1.json", [_row("a", 1, 1), _row("ctl", 0, 0, confirmed=0)], 0)],
        "Phase 0",
    )
    new = aggregate(
        [_run(tmp_path, "n1.json", [_row("a", 1, 1), _row("ctl", 0, 0, confirmed=2)], 2)],
        "Phase 1",
    )

    c = compare(new, old)
    assert c["true_positive_regression"] is False, "recall is unchanged"
    assert c["false_positive_regression"] is True
    assert c["passed"] is False


def test_comparison_gates_on_the_floor_not_the_mean(tmp_path):
    """A lucky run must not mask a bad one. Baseline scores 2 every run;
    the candidate scores 4 then 1 — a better mean but a worse worst case, and
    an unstable pipeline is a regression however good its best day was."""
    steady = [_row("a", 1, 1), _row("b", 1, 1), _row("c", 0, 1), _row("d", 0, 1)]
    old = aggregate(
        [_run(tmp_path, "o1.json", steady), _run(tmp_path, "o2.json", steady)],
        "Phase 0",
    )
    new = aggregate(
        [
            _run(tmp_path, "n1.json", [_row(n, 1, 1) for n in "abcd"]),
            _run(tmp_path, "n2.json", [_row("a", 1, 1)] + [_row(n, 0, 1) for n in "bcd"]),
        ],
        "Phase 1",
    )

    assert new["true_positives_mean"] > old["true_positives_mean"], "candidate has a better mean"
    assert new["true_positives_min"] < old["true_positives_min"], "but a worse floor"
    assert compare(new, old)["passed"] is False


def test_unmatched_is_derived_for_baselines_recorded_before_the_metric_existed(tmp_path):
    """Re-aggregating an old baseline to add the field would re-stamp it with a
    newer commit and destroy its provenance, so it is derived instead."""
    old = aggregate(
        [_run(tmp_path, "o1.json", [_row("a", 1, 1, confirmed=2), _row("ctl", 0, 0, confirmed=1)])],
        "Phase 0",
    )
    del old["unmatched_confirmed_per_run"]

    # 2 confirmed but only 1 true positive on the labeled fixture -> 1 unmatched.
    # The control's confirmed finding is a negative-control FP, counted elsewhere.
    assert _unmatched_per_run(old) == [1]

    new = aggregate([_run(tmp_path, "n1.json", [_row("a", 1, 1, confirmed=1)])], "Phase 1")
    c = compare(new, old)
    assert c["unmatched_ceiling"] == 1
    assert c["candidate_unmatched_max"] == 0
    assert c["unmatched_regression"] is False


def test_unmatched_regression_is_caught_while_recall_holds(tmp_path):
    """The tx-origin duplicate case: 6/6 recall, zero control FPs, but the same
    bug reported twice. Only the unmatched metric can see it."""
    old = aggregate([_run(tmp_path, "o1.json", [_row("a", 1, 1, confirmed=1)])], "Phase 0")
    new = aggregate([_run(tmp_path, "n1.json", [_row("a", 1, 1, confirmed=2)])], "Phase 1")

    c = compare(new, old)
    assert c["true_positive_regression"] is False, "recall is unchanged"
    assert c["false_positive_regression"] is False, "no control false positives"
    assert c["unmatched_regression"] is True
    assert c["passed"] is False


def test_comparison_refuses_a_verdict_across_different_corpora(tmp_path):
    """Stripping the bug-explaining comments changed the fixtures, so the old
    numbers describe a different problem. The gate must say so, not score it."""
    old_run = _run(tmp_path, "o1.json", [_row("a", 1, 1)])
    old_run.write_text(json.dumps({**json.loads(old_run.read_text()), "corpus_fingerprint": "aaa"}))
    new_run = _run(tmp_path, "n1.json", [_row("a", 0, 1)])
    new_run.write_text(json.dumps({**json.loads(new_run.read_text()), "corpus_fingerprint": "bbb"}))

    c = compare(aggregate([new_run], "Phase 1"), aggregate([old_run], "Phase 0"))
    assert c["corpus_mismatch"] is True
    assert c["passed"] is False
    assert "Not comparable" in render_comparison(c)


def test_comparison_marks_an_unfingerprinted_baseline_as_unverified(tmp_path):
    """Silence would imply the corpora were checked and matched."""
    old = aggregate([_run(tmp_path, "o1.json", [_row("a", 1, 1)])], "Phase 0")
    new_run = _run(tmp_path, "n1.json", [_row("a", 1, 1)])
    new_run.write_text(json.dumps({**json.loads(new_run.read_text()), "corpus_fingerprint": "bbb"}))

    c = compare(aggregate([new_run], "Phase 1"), old)
    assert c["corpus_mismatch"] is False
    assert c["corpus_unverified"] is True
    assert c["passed"] is True, "advisory, not a failure"
    assert "could not be confirmed" in render_comparison(c)


def test_matching_fingerprints_are_neither_mismatched_nor_unverified(tmp_path):
    runs = []
    for name in ("o1.json", "n1.json"):
        r = _run(tmp_path, name, [_row("a", 1, 1)])
        r.write_text(json.dumps({**json.loads(r.read_text()), "corpus_fingerprint": "same"}))
        runs.append(r)

    c = compare(aggregate([runs[1]], "Phase 1"), aggregate([runs[0]], "Phase 0"))
    assert c["corpus_mismatch"] is False
    assert c["corpus_unverified"] is False
    assert "could not be confirmed" not in render_comparison(c)


def test_aggregate_refuses_to_mix_runs_from_different_corpora(tmp_path):
    a = _run(tmp_path, "a.json", [_row("a", 1, 1)])
    a.write_text(json.dumps({**json.loads(a.read_text()), "corpus_fingerprint": "aaa"}))
    b = _run(tmp_path, "b.json", [_row("a", 1, 1)])
    b.write_text(json.dumps({**json.loads(b.read_text()), "corpus_fingerprint": "bbb"}))

    with pytest.raises(SystemExit, match="different corpora"):
        aggregate([a, b], "Phase 1")


def test_reproduce_command_round_trips_the_pipeline_from_the_label(tmp_path):
    rows = [_row("a", 1, 1)]
    rows[0]["config"] = "phase1/anthropic:claude-opus-4-8"
    md = render_markdown(aggregate([_run(tmp_path, "r1.json", rows)], "Phase 1"))
    assert "--provider anthropic --pipeline phase1" in md


def test_split_role_label_still_yields_a_usable_provider(tmp_path):
    rows = [_row("a", 1, 1)]
    rows[0]["config"] = "phase1/finder=anthropic:a,verifier=openai:b"
    md = render_markdown(aggregate([_run(tmp_path, "r1.json", rows)], "Phase 1"))
    assert "--provider anthropic --pipeline phase1" in md


def test_markdown_records_provenance(tmp_path):
    b = aggregate([_run(tmp_path, "r1.json", [_row("a", 1, 1)])], "Phase 0")
    md = render_markdown(b)
    assert "# Phase 0 baseline" in md
    assert b["commit_short"] in md
    assert "anthropic:claude-opus-4-8" in md
