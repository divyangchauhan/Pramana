"""Tests for baseline aggregation across repeated runs.

The point of a baseline is to survive nondeterminism, so the cases that matter
are the ones where runs disagree.
"""

from __future__ import annotations

import json
from pathlib import Path

from pramana.eval.baseline import aggregate, render_markdown


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


def test_fixture_errors_are_carried_into_the_record(tmp_path):
    row = _row("a", 0, 1)
    row["error"] = "ProviderError: overloaded"
    b = aggregate([_run(tmp_path, "r1.json", [row])], "Phase 0")
    assert b["fixtures"][0]["errors"] == ["ProviderError: overloaded"]


def test_markdown_records_provenance(tmp_path):
    b = aggregate([_run(tmp_path, "r1.json", [_row("a", 1, 1)])], "Phase 0")
    md = render_markdown(b)
    assert "# Phase 0 baseline" in md
    assert b["commit_short"] in md
    assert "anthropic:claude-opus-4-8" in md
