"""Unit tests for the Phase 0 boundary parsing and TP grading logic.

These run offline (no API key, no network). The corpus-level self-check
(`python -m pramana.eval.harness --self-check`) covers the Foundry path.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from pramana.contracts import OutputParseError, parse_phase0_output
from pramana.eval.harness import Probe, grade, normalize_vuln_class, probes_from_reference
from pramana.eval.workspace import load_fixtures


def test_parse_plain_json():
    out = parse_phase0_output(
        '{"findings": [{"id": "F-1", "contract": "src/A.sol", '
        '"vuln_class": "reentrancy", "verdict": "confirmed", "poc_path": "test/F-1.t.sol"}], '
        '"report_markdown": "# report"}'
    )
    assert len(out.findings) == 1
    assert out.findings[0].verdict == "confirmed"
    assert out.report_markdown == "# report"


def test_parse_json_with_fences_and_prose():
    text = (
        "Here is my final answer:\n```json\n"
        '{"findings": [], "report_markdown": "nothing found"}\n'
        "```\nThanks!"
    )
    out = parse_phase0_output(text)
    assert out.findings == []
    assert out.report_markdown == "nothing found"


def test_parse_rejects_garbage():
    with pytest.raises(OutputParseError):
        parse_phase0_output("no json here at all")


@pytest.mark.parametrize(
    "raw,canonical",
    [
        ("reentrancy-eth", "reentrancy"),
        ("Re-Entrancy", "reentrancy"),
        ("tx.origin", "tx-origin"),
        ("Integer Overflow", "integer-overflow"),
        ("arithmetic", "integer-overflow"),
        ("missing access control", "access-control"),
        ("unchecked return value", "unchecked-call"),
    ],
)
def test_normalize_vuln_class(raw, canonical):
    assert normalize_vuln_class(raw) == canonical


def _first_fixture():
    fixtures = load_fixtures(names=["reentrancy-vault"])
    assert fixtures, "reentrancy-vault fixture must exist"
    return fixtures[0]


def test_confirmed_reference_poc_counts_as_tp():
    fx = _first_fixture()
    with tempfile.TemporaryDirectory() as tmp:
        row = grade(fx, probes_from_reference(fx), Path(tmp), "test")
    assert row.true_positive_findings == 1
    assert row.confirmed_poc_pass == 1


def test_inconclusive_never_counts():
    fx = _first_fixture()
    ref = fx.dir / fx.reference_poc
    probes = [Probe(id="P1", vuln_class="reentrancy", verdict="inconclusive", poc_file=ref)]
    with tempfile.TemporaryDirectory() as tmp:
        row = grade(fx, probes, Path(tmp), "test")
    assert row.true_positive_findings == 0
    assert row.n_confirmed == 0


def test_confirmed_without_working_poc_is_not_tp():
    fx = _first_fixture()
    missing = fx.dir / "reference" / "does_not_exist.t.sol"
    probes = [Probe(id="P1", vuln_class="reentrancy", verdict="confirmed", poc_file=missing)]
    with tempfile.TemporaryDirectory() as tmp:
        row = grade(fx, probes, Path(tmp), "test")
    assert row.n_confirmed == 1
    assert row.confirmed_poc_pass == 0
    assert row.true_positive_findings == 0


def test_wrong_class_does_not_match_known_bug():
    fx = _first_fixture()  # known bug is reentrancy
    ref = fx.dir / fx.reference_poc
    # PoC passes, but the claimed class doesn't match the known bug.
    probes = [Probe(id="P1", vuln_class="tx-origin", verdict="confirmed", poc_file=ref)]
    with tempfile.TemporaryDirectory() as tmp:
        row = grade(fx, probes, Path(tmp), "test")
    assert row.confirmed_poc_pass == 1
    assert row.true_positive_findings == 0
