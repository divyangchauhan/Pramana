"""Tests for the paired vulnerable/patched negative controls.

A negative control is only meaningful if the "patched" fixture is genuinely
patched *and* still functional. These tests execute Foundry to prove both across
every paired twin in the corpus, pin the grading semantics for a fixture that
carries no known bugs, and cover the paired_patch_retention metric that the
pairs exist to feed.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from pramana.eval.harness import (
    FixtureRow,
    Probe,
    grade,
    paired_patch_retention,
    summarize,
)
from pramana.eval.workspace import build_workspace, load_fixtures
from pramana.tools.foundry import forge_test

PATCHED = "reentrancy-vault-patched"
VULNERABLE = "reentrancy-vault"


def _fixture(name: str):
    fixtures = load_fixtures(names=[name])
    assert fixtures, f"{name} fixture must exist"
    return fixtures[0]


def _pairs():
    """(vulnerable, patched) Fixture tuples for every paired twin in the corpus."""
    by_pair: dict[str, dict] = {}
    for f in load_fixtures():
        if f.pair and f.variant:
            by_pair.setdefault(f.pair, {})[f.variant] = f
    return [
        (v["vulnerable"], v["patched"])
        for _, v in sorted(by_pair.items())
        if "vulnerable" in v and "patched" in v
    ]


PAIRS = _pairs()
PATCHED_FIXTURES = [p for _, p in PAIRS]


def _exploit_pocs(vulnerable) -> list[str]:
    """Reference exploits that can serve as a blanket "must fail on the patched
    twin" probe: the fixture-level PoC plus any per-bug ones.

    Excludes PoCs whose proof-of-harm is itself a revert (they use
    ``vm.expectRevert``). A DoS exploit asserts that a legitimate action reverts;
    run against a patched twin it can revert for an *unrelated* reason — e.g. a
    changed signing scheme rejecting the exploit's now-stale authorization — and
    the permissive expectRevert matches vacuously, so pass/fail cannot tell a
    live DoS from a fixed one. Those bugs are verified by the twin's own control
    PoC instead, which reconstructs a valid action and asserts it now succeeds.
    """
    rels = set()
    if vulnerable.reference_poc:
        rels.add(vulnerable.reference_poc)
    for bug in vulnerable.known_bugs:
        if bug.reference_poc:
            rels.add(bug.reference_poc)
    return sorted(
        rel for rel in rels if "vm.expectRevert" not in (vulnerable.dir / rel).read_text()
    )


_EXPLOIT_CASES = [(v, p, rel) for v, p in PAIRS for rel in _exploit_pocs(v)]
_EXPLOIT_IDS = [f"{p.name}:{Path(rel).name}" for _, p, rel in _EXPLOIT_CASES]


# --- corpus / metadata ------------------------------------------------------


def test_patched_fixture_declares_no_known_bugs():
    fx = _fixture(PATCHED)
    assert fx.known_bugs == []
    assert fx.reference_poc is None


@pytest.mark.parametrize("patched", PATCHED_FIXTURES, ids=lambda f: f.name)
def test_every_patched_twin_names_an_existing_control_poc(patched):
    assert patched.control_poc, f"{patched.name} has no control_poc"
    assert (patched.dir / patched.control_poc).is_file()


# --- Foundry-executing invariants (run under CI with forge installed) -------


@pytest.mark.parametrize("patched", PATCHED_FIXTURES, ids=lambda f: f.name)
def test_control_poc_passes_against_patched_source(patched):
    """The patch holds and the contract still works for honest users -- i.e. it
    is not a degenerate always-revert 'fix'."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = build_workspace(patched, Path(tmp) / "ws")
        poc = patched.dir / patched.control_poc
        shutil.copy(poc, ws / "test" / poc.name)
        result = forge_test(ws, f"test/{poc.name}")
    assert result.ran, result.output
    assert result.passed, result.output


@pytest.mark.parametrize("vulnerable,patched,rel", _EXPLOIT_CASES, ids=_EXPLOIT_IDS)
def test_real_exploit_fails_against_patched_source(vulnerable, patched, rel):
    """Each PoC that proves a bug on the vulnerable fixture must NOT succeed on
    its patched twin."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = build_workspace(patched, Path(tmp) / "ws")
        exploit = vulnerable.dir / rel
        shutil.copy(exploit, ws / "test" / exploit.name)
        result = forge_test(ws, f"test/{exploit.name}")
    assert result.ran, result.output
    assert not result.passed, (
        f"{vulnerable.name} exploit {Path(rel).name} still succeeds on {patched.name}"
    )


# --- grading semantics on a zero-bug fixture --------------------------------


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
    # Retention needs the corpus metadata, which summarize was not given here.
    assert out["paired_patch_retention"] is None
    assert "report_markdown" not in out["fixtures"][0]


# --- paired_patch_retention metric (pure Python, no Foundry) ----------------


def _row(name: str, details: list[dict]) -> FixtureRow:
    return FixtureRow(
        fixture=name,
        config="test",
        n_candidates=len(details),
        n_confirmed=sum(1 for d in details if d.get("verdict") == "confirmed"),
        confirmed_poc_pass=sum(1 for d in details if d.get("poc_passed")),
        true_positive_findings=sum(1 for d in details if d.get("counted_true_positive")),
        n_known_bugs=0,
        finder_precision=None,
        verifier_precision=None,
        recall=None,
        details=details,
    )


def _detected(cls: str) -> dict:
    return {
        "normalized": cls,
        "counted_true_positive": True,
        "verdict": "confirmed",
        "poc_passed": True,
    }


def _resurfaced(cls: str) -> dict:
    return {
        "normalized": cls,
        "counted_true_positive": False,
        "verdict": "confirmed",
        "poc_passed": True,
    }


def test_retention_credits_a_silent_patch():
    fixtures = load_fixtures(names=[VULNERABLE, PATCHED])
    rows = [_row(VULNERABLE, [_detected("reentrancy")]), _row(PATCHED, [])]
    out = paired_patch_retention(rows, fixtures)
    assert out["pairs_evaluated"] == 1
    assert out["detected_on_vulnerable"] == 1
    assert out["retained"] == 1
    assert out["rate"] == 1.0
    assert out["per_pair"][0]["retained"] == ["reentrancy"]
    assert out["per_pair"][0]["resurfaced_on_patch"] == []


def test_retention_flags_a_finding_resurfaced_on_the_patch():
    fixtures = load_fixtures(names=[VULNERABLE, PATCHED])
    rows = [
        _row(VULNERABLE, [_detected("reentrancy")]),
        _row(PATCHED, [_resurfaced("reentrancy")]),
    ]
    out = paired_patch_retention(rows, fixtures)
    assert out["retained"] == 0
    assert out["rate"] == 0.0
    assert out["per_pair"][0]["resurfaced_on_patch"] == ["reentrancy"]


def test_retention_ignores_a_patch_fp_never_detected_on_the_vulnerable_twin():
    """A false positive on the patch for a class the pipeline never proved on the
    vulnerable side is a plain control FP, not a retention failure: it does not
    enter the retention denominator."""
    fixtures = load_fixtures(names=[VULNERABLE, PATCHED])
    rows = [
        _row(VULNERABLE, [_detected("reentrancy")]),
        _row(PATCHED, [_resurfaced("integer-overflow")]),
    ]
    out = paired_patch_retention(rows, fixtures)
    assert out["retained"] == 1
    assert out["rate"] == 1.0
    assert out["per_pair"][0]["resurfaced_on_patch"] == []


def test_retention_skips_pairs_missing_a_twin():
    fixtures = load_fixtures(names=[VULNERABLE, PATCHED])
    rows = [_row(VULNERABLE, [_detected("reentrancy")])]  # patched twin not run
    out = paired_patch_retention(rows, fixtures)
    assert out["pairs_evaluated"] == 0
    assert out["rate"] is None
