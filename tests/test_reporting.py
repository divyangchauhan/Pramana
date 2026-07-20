"""Tests for the multi-bug fixture matching and the report writer (offline)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from pramana.eval.harness import FixtureRow, grade, probes_from_reference, write_reports
from pramana.eval.workspace import load_fixtures


def test_multi_bug_fixture_matches_two_distinct_bugs():
    fx = load_fixtures(names=["bank-multi"])[0]
    assert len(fx.known_bugs) == 2
    with tempfile.TemporaryDirectory() as tmp:
        row = grade(fx, probes_from_reference(fx), Path(tmp), "test")
    # Two distinct bugs, each proven by its own PoC, matched 1:1.
    assert row.n_known_bugs == 2
    assert row.confirmed_poc_pass == 2
    assert row.true_positive_findings == 2
    assert row.recall == 1.0


def _row(name: str, report: str) -> FixtureRow:
    return FixtureRow(
        fixture=name,
        config="anthropic:claude-opus-4-8",
        n_candidates=1,
        n_confirmed=1,
        confirmed_poc_pass=1,
        true_positive_findings=1,
        n_known_bugs=1,
        finder_precision=1.0,
        verifier_precision=1.0,
        recall=1.0,
        report_markdown=report,
    )


def test_write_reports_writes_only_nonempty(tmp_path):
    rows = [_row("with-report", "# Findings\n\nreentrancy confirmed"), _row("no-report", "")]
    n = write_reports(rows, tmp_path)
    assert n == 1
    assert (tmp_path / "with-report.md").exists()
    assert not (tmp_path / "no-report.md").exists()
    body = (tmp_path / "with-report.md").read_text()
    assert "# Audit report — with-report" in body
    assert "reentrancy confirmed" in body
