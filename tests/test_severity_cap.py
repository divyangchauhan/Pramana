"""Tests for the deployment-contingent severity cap.

The sweep compares models against each other, and severity is part of how a
finding is read. A model that ignores the capping instruction — or reads it
differently from its peers — must not be able to let a misconfiguration finding
outrank a real exploit. So the rule is enforced in code, and these tests pin
that enforcement rather than the prompt wording.

Background: runs 1 and 3 of the phase-1 baseline proved an ecrecover bypass by
deploying the vault themselves with signer=address(0) and graded it "high".
Run 2 rejected that reasoning. Under the cap both would be "medium", declared.
"""

from __future__ import annotations

from pramana.agents.verifier import VERIFIER_SYS
from pramana.contracts import (
    DEPLOYMENT_CONTINGENT_MAX,
    SEVERITY_ORDER,
    Verdict,
    parse_verdict,
)


def _verdict(**kw) -> Verdict:
    return Verdict(finding_id="F-001", verdict="confirmed", **kw)


# --- the cap itself ----------------------------------------------------------


def test_contingent_finding_is_capped_however_total_the_loss_looked():
    v = _verdict(severity="critical", deployment_contingent=True).capped()
    assert v.severity == DEPLOYMENT_CONTINGENT_MAX


def test_cap_applies_to_every_severity_above_the_ceiling():
    ceiling = SEVERITY_ORDER.index(DEPLOYMENT_CONTINGENT_MAX)
    for severity in SEVERITY_ORDER[:ceiling]:
        capped = _verdict(severity=severity, deployment_contingent=True).capped()
        assert capped.severity == DEPLOYMENT_CONTINGENT_MAX, severity


def test_cap_never_raises_a_lower_severity():
    """A ceiling, not an assignment: 'low' must not be promoted to 'medium'."""
    for severity in ("low", "informational"):
        capped = _verdict(severity=severity, deployment_contingent=True).capped()
        assert capped.severity == severity


def test_a_real_exploit_keeps_its_severity():
    v = _verdict(severity="critical", deployment_contingent=False).capped()
    assert v.severity == "critical"


def test_capping_is_idempotent():
    once = _verdict(severity="critical", deployment_contingent=True).capped()
    assert once.capped() == once


def test_cap_leaves_an_unrated_verdict_alone():
    """Refuted and inconclusive verdicts carry no severity; capping must not
    invent one."""
    v = Verdict(finding_id="F-001", verdict="refuted", deployment_contingent=True).capped()
    assert v.severity is None


# --- the contract boundary ---------------------------------------------------


def test_flag_defaults_false_so_silence_asserts_a_real_exploit():
    """A verifier that omits the field is claiming the exploit works against a
    correctly deployed contract — the stronger claim, and the honest default to
    hold it to."""
    v = parse_verdict(
        '{"finding_id":"F-1","verdict":"confirmed","severity":"high",'
        '"poc_path":"test/F-1.t.sol","evidence":"drained"}'
    )
    assert v.deployment_contingent is False
    assert v.capped().severity == "high"


def test_flag_parses_from_verifier_output():
    v = parse_verdict(
        '{"finding_id":"F-1","verdict":"confirmed","severity":"critical",'
        '"deployment_contingent":true,"poc_path":"test/F-1.t.sol",'
        '"evidence":"deployed with signer=address(0)"}'
    )
    assert v.deployment_contingent is True
    assert v.capped().severity == "medium"


# --- the prompt states the rule the code enforces ----------------------------


def test_verifier_prompt_documents_the_field_and_the_ceiling():
    """Belt and braces: the code enforces the cap, but a verifier that has not
    been told the rule would set the flag arbitrarily and the cap would fire on
    the wrong findings."""
    assert "deployment_contingent" in VERIFIER_SYS
    assert DEPLOYMENT_CONTINGENT_MAX in VERIFIER_SYS
