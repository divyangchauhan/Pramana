"""Tests for the verifier refutation probe.

The probe exists to answer a question the corpus eval structurally cannot: does
the verifier ever disagree? These tests check the probe would actually catch a
broken verifier — in *both* directions, since a verifier that refuses everything
is as useless as one that confirms everything, and a refutation-only check would
give the first a clean bill of health.

Offline: a scripted adapter stands in for the model, so no forge run and no key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pramana.config import AgentConfig, ModelProfile
from pramana.eval.refutation import PROBES, ProbeCase, run_probes
from pramana.providers.base import LLMResponse


@dataclass
class ScriptedVerifier:
    """Replies with a fixed verdict, whatever it is asked."""

    verdict: str
    provider: str = "anthropic"
    seeds: list[str] = field(default_factory=list)

    def check_capabilities(self, model: str) -> None:
        return None

    def complete(self, *, model, system, tools, messages, max_tokens) -> LLMResponse:
        self.seeds.append(str(messages[0]["content"]))
        body = (
            '{"finding_id":"X","verdict":"confirmed","severity":"high",'
            '"poc_path":"test/X.t.sol","evidence":"e"}'
            if self.verdict == "confirmed"
            else f'{{"finding_id":"X","verdict":"{self.verdict}","evidence":"e"}}'
        )
        return LLMResponse(text=body, tool_calls=[], raw=None, usage={})


def _run(monkeypatch, tmp_path: Path, verdict: str, cases=None):
    adapter = ScriptedVerifier(verdict=verdict)
    monkeypatch.setattr("pramana.providers.build_adapter", lambda p: adapter)
    monkeypatch.setattr("pramana.eval.refutation.build_adapter", lambda p: adapter)
    config = AgentConfig(agent=ModelProfile(provider="anthropic", model="m"))
    return run_probes(config, cases or PROBES, tmp_path), adapter


def test_probe_suite_keeps_a_true_claim_control():
    """Without a confirmable control, a verifier that refutes everything would
    score a perfect result — the probe would certify a broken pipeline."""
    assert any(c.confirmable for c in PROBES), "probe suite needs a true-claim control"
    assert any(not c.confirmable for c in PROBES), "probe suite needs false claims"


def test_probe_claims_target_real_fixtures():
    from pramana.eval.workspace import load_fixtures

    known = {f.name for f in load_fixtures()}
    for case in PROBES:
        assert case.fixture in known, f"{case.name} targets unknown fixture {case.fixture}"


def test_a_rubber_stamping_verifier_fails_the_probe(monkeypatch, tmp_path):
    """The situation the probe was built to detect: everything confirmed."""
    results, _ = _run(monkeypatch, tmp_path, "confirmed")

    by_name = {r.case.name: r for r in results}
    assert by_name["true-claim-control"].passed is True
    assert by_name["false-claim-patched-twin"].passed is False
    assert by_name["false-claim-wrong-mechanism"].passed is False
    assert not all(r.passed for r in results)


def test_a_reject_everything_verifier_also_fails_the_probe(monkeypatch, tmp_path):
    """The opposite degenerate case, which a refutation-only check would miss."""
    results, _ = _run(monkeypatch, tmp_path, "refuted")

    by_name = {r.case.name: r for r in results}
    assert by_name["true-claim-control"].passed is False, "must catch a verifier that refuses all"
    assert by_name["false-claim-patched-twin"].passed is True


def test_inconclusive_on_a_false_claim_counts_as_not_confirmed(monkeypatch, tmp_path):
    """Failing to prove something unprovable is the honest outcome, not a miss."""
    false_only = [c for c in PROBES if not c.confirmable]
    results, _ = _run(monkeypatch, tmp_path, "inconclusive", cases=false_only)
    assert all(r.passed for r in results)


def test_probe_seeds_the_verifier_with_only_the_bare_claim(monkeypatch, tmp_path):
    """The probe must not weaken the isolation it is measuring."""
    case = next(c for c in PROBES if not c.confirmable)
    _, adapter = _run(monkeypatch, tmp_path, "refuted", cases=[case])

    seed = adapter.seeds[0]
    assert case.claim.vuln_class in seed
    assert len(adapter.seeds) == 1
    # The probe's own rationale is bookkeeping for humans — never shown to the model.
    assert case.rationale not in seed


def test_probe_case_is_constructible_for_extension():
    from pramana.contracts import Finding

    case = ProbeCase(
        name="custom",
        fixture="reentrancy-vault",
        confirmable=False,
        rationale="why",
        claim=Finding(
            id="P", contract="src/EtherStore.sol", location="f()",
            vuln_class="tx-origin", hypothesis="h",
        ),
    )
    assert case.confirmable is False


@pytest.mark.parametrize("verdict,confirmable,expected", [
    ("confirmed", True, True),
    ("refuted", True, False),
    ("inconclusive", True, False),
    ("confirmed", False, False),
    ("refuted", False, True),
    ("inconclusive", False, True),
])
def test_pass_rule_matrix(monkeypatch, tmp_path, verdict, confirmable, expected):
    from pramana.contracts import Finding

    case = ProbeCase(
        name="m", fixture="reentrancy-vault", confirmable=confirmable, rationale="r",
        claim=Finding(
            id="P", contract="src/EtherStore.sol", location="withdraw()",
            vuln_class="reentrancy", hypothesis="h",
        ),
    )
    results, _ = _run(monkeypatch, tmp_path, verdict, cases=[case])
    assert results[0].passed is expected
