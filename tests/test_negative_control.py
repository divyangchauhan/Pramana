"""Tests for the paired vulnerable/patched negative control.

A negative control is only meaningful if the "patched" fixture is genuinely
patched *and* still functional. These tests execute Foundry to prove both, and
pin the grading semantics for a fixture that carries no known bugs.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from pramana.eval.harness import Probe, grade, summarize
from pramana.eval.workspace import build_workspace, load_fixtures
from pramana.tools.foundry import forge_test

PATCHED = "reentrancy-vault-patched"
VULNERABLE = "reentrancy-vault"


def _fixture(name: str):
    fixtures = load_fixtures(names=[name])
    assert fixtures, f"{name} fixture must exist"
    return fixtures[0]


def test_patched_fixture_declares_no_known_bugs():
    fx = _fixture(PATCHED)
    assert fx.known_bugs == []
    assert fx.reference_poc is None


def test_control_poc_passes_against_patched_source():
    """The patch holds (reentrancy reverts) and the vault still works for
    honest users -- i.e. it is not a degenerate always-revert 'fix'."""
    fx = _fixture(PATCHED)
    with tempfile.TemporaryDirectory() as tmp:
        ws = build_workspace(fx, Path(tmp) / "ws")
        poc = fx.dir / "reference" / "NoDrainControl.t.sol"
        shutil.copy(poc, ws / "test" / poc.name)
        result = forge_test(ws, f"test/{poc.name}")
    assert result.ran, result.output
    assert result.passed, result.output


def test_real_exploit_fails_against_patched_source():
    """The exact PoC that drains reentrancy-vault must not drain its twin."""
    patched = _fixture(PATCHED)
    vulnerable = _fixture(VULNERABLE)
    assert vulnerable.reference_poc is not None
    with tempfile.TemporaryDirectory() as tmp:
        ws = build_workspace(patched, Path(tmp) / "ws")
        exploit = vulnerable.dir / vulnerable.reference_poc
        shutil.copy(exploit, ws / "test" / exploit.name)
        result = forge_test(ws, f"test/{exploit.name}")
    assert result.ran, result.output
    assert not result.passed, "reentrancy exploit still succeeds on the patched fixture"


def test_confirmed_finding_on_control_is_a_false_positive():
    """No probe can ever be a true positive on a zero-bug fixture, and recall
    is undefined rather than 0.0 (there is nothing to recall)."""
    fx = _fixture(PATCHED)
    probes = [Probe(id="P1", vuln_class="reentrancy", verdict="confirmed", poc_file=None)]
    with tempfile.TemporaryDirectory() as tmp:
        row = grade(fx, probes, Path(tmp), "test")
    assert row.n_known_bugs == 0
    assert row.true_positive_findings == 0
    assert row.n_confirmed == 1
    assert row.recall is None


def test_summarize_counts_control_false_positives_and_omits_report_text():
    fx = _fixture(PATCHED)
    probes = [Probe(id="P1", vuln_class="reentrancy", verdict="confirmed", poc_file=None)]
    with tempfile.TemporaryDirectory() as tmp:
        row = grade(fx, probes, Path(tmp), "test")
    row.report_markdown = "# should not appear in the JSON artifact"

    out = summarize([row])
    assert out["negative_control_fixtures"] == [PATCHED]
    assert out["negative_control_false_positives"] == 1
    assert out["negative_control_proven_false_positives"] == 0
    assert out["total_known_bugs"] == 0
    assert "report_markdown" not in out["fixtures"][0]
