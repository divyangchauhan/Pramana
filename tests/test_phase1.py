"""Tests for the Phase 1 split: finder -> context-isolated verifier.

The property Phase 1 exists to guarantee is *isolation* — the verifier must not
be able to inherit the finder's reasoning or confidence. That is enforced by
construction (a whitelist seed and a physically separate messages list), so the
tests below pin the construction rather than the prose of a prompt.

All of this runs offline against a scripted adapter; no API key, no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pramana.agents.verifier import build_verifier_seed
from pramana.config import AgentConfig, ModelProfile
from pramana.contracts import (
    BARE_CLAIM_FIELDS,
    Finding,
    OutputParseError,
    Verdict,
    bare_claim,
    parse_findings,
    parse_verdict,
)
from pramana.pipeline import (
    FINDER_TOOL_NAMES,
    VERIFIER_TOOL_NAMES,
    _AttemptBudget,
    _quarantine_unconfirmed,
    _render_report,
    audit_phase1,
)
from pramana.providers.base import LLMResponse, ToolCall
from pramana.tools.files import ToolContext
from pramana.tools.registry import build_tool_registry, dispatch

FINDING = Finding(
    id="F-001",
    contract="src/EtherStore.sol",
    location="withdraw() L18-29",
    vuln_class="reentrancy",
    hypothesis="External call before state update lets a receiver re-enter and drain.",
    severity_guess="high",
    finder_notes="SECRET_FINDER_REASONING that the verifier must never see",
)


# --- isolation ---------------------------------------------------------------


def test_bare_claim_is_exactly_the_four_whitelisted_fields():
    claim = bare_claim(FINDING)
    assert set(claim) == set(BARE_CLAIM_FIELDS)
    assert set(claim) == {"contract", "location", "vuln_class", "hypothesis"}


def test_bare_claim_withholds_finder_reasoning_and_severity():
    claim = bare_claim(FINDING)
    assert "finder_notes" not in claim
    assert "severity_guess" not in claim
    assert all("SECRET_FINDER_REASONING" not in str(v) for v in claim.values())


def test_bare_claim_is_a_whitelist_so_new_fields_cannot_leak():
    """A blacklist would leak any field added to Finding later; a whitelist can't."""
    extra_fields = set(Finding.model_fields) - set(BARE_CLAIM_FIELDS) - {"id"}
    assert extra_fields, "Finding should carry fields beyond the bare claim"
    claim = bare_claim(FINDING)
    assert not (extra_fields & set(claim))


def test_verifier_seed_contains_the_claim_but_not_the_finder_notes():
    seed = build_verifier_seed(bare_claim(FINDING), FINDING.id, max_attempts=4)
    assert "reentrancy" in seed
    assert "withdraw() L18-29" in seed
    assert "F-001" in seed
    assert "SECRET_FINDER_REASONING" not in seed
    assert "high" not in seed  # the finder's severity guess must not prime the verifier


# --- tool scope is role definition -------------------------------------------


def test_finder_cannot_write_or_execute():
    assert "write_file" not in FINDER_TOOL_NAMES
    assert "run_foundry_test" not in FINDER_TOOL_NAMES


def test_verifier_cannot_call_slither_but_can_prove():
    assert "run_slither" not in VERIFIER_TOOL_NAMES
    assert {"write_file", "run_foundry_test"} <= set(VERIFIER_TOOL_NAMES)


def test_scoped_registry_refuses_an_ungranted_tool(tmp_path):
    """Scoping the registry, not just the schema list, means a finder that
    hallucinates write_file gets an error instead of the capability."""
    ctx = ToolContext(workspace=tmp_path)
    registry = build_tool_registry(ctx, FINDER_TOOL_NAMES)
    assert "write_file" not in registry

    call = ToolCall(id="1", name="write_file", arguments={"path": "test/x.t.sol", "content": "x"})
    result = dispatch(call, registry, max_chars=1000)
    assert result.is_error
    assert not (tmp_path / "test" / "x.t.sol").exists()


def test_build_tool_registry_rejects_unknown_names(tmp_path):
    with pytest.raises(KeyError):
        build_tool_registry(ToolContext(workspace=tmp_path), ["read_file", "nope"])


# --- boundary parsing --------------------------------------------------------


def test_parse_findings_accepts_a_bare_array():
    findings = parse_findings(
        '[{"id":"F-001","contract":"src/A.sol","location":"f()",'
        '"vuln_class":"reentrancy","hypothesis":"h"}]'
    )
    assert len(findings) == 1
    assert findings[0].vuln_class == "reentrancy"


def test_parse_findings_accepts_a_wrapper_object():
    findings = parse_findings(
        'Here you go:\n```json\n{"findings":[{"id":"F-1","contract":"src/A.sol",'
        '"location":"f()","vuln_class":"tx-origin","hypothesis":"h"}]}\n```'
    )
    assert len(findings) == 1
    assert findings[0].vuln_class == "tx-origin"


def test_parse_findings_accepts_empty_array_as_a_clean_verdict():
    """The negative control depends on this: "nothing found" must parse."""
    assert parse_findings("[]") == []
    assert parse_findings("I found no vulnerabilities.\n[]") == []


def test_parse_findings_ignores_brackets_in_surrounding_prose():
    """Regression: a live finder cleared the negative control by writing prose
    containing "[CEI]" before its `[]`, and the parser committed to the first
    bracket it saw — turning a correct clean verdict into a crash."""
    text = (
        "The contract correctly applies the checks-effects-interactions [CEI] "
        "pattern, so I found no vulnerabilities.\n\n[]"
    )
    assert parse_findings(text) == []


def test_parse_findings_skips_prose_brackets_before_a_real_array():
    text = (
        "Slither flagged low-level-calls [informational]. After review:\n"
        '[{"id":"F-001","contract":"src/A.sol","location":"f()",'
        '"vuln_class":"reentrancy","hypothesis":"h"}]'
    )
    findings = parse_findings(text)
    assert len(findings) == 1
    assert findings[0].id == "F-001"


def test_parse_findings_reports_a_malformed_array_instead_of_silently_dropping_it():
    """A findings array with bad content must error, not be read as "clean"."""
    with pytest.raises(OutputParseError, match="schema validation"):
        parse_findings('note [x]\n[{"id":"F-1","vuln_class":"reentrancy"}]')


def test_parse_verdict_ignores_braces_in_prose():
    v = parse_verdict(
        'The mapping balances{} is zeroed first.\n'
        '{"finding_id":"F-1","verdict":"refuted","evidence":"guard holds"}'
    )
    assert v.verdict == "refuted"


def test_parse_findings_rejects_garbage():
    with pytest.raises(OutputParseError):
        parse_findings("no json here")
    with pytest.raises(OutputParseError):
        parse_findings('{"not_findings": []}')


def test_parse_verdict_reads_a_verdict_object():
    v = parse_verdict('{"finding_id":"F-1","verdict":"refuted","evidence":"guard holds"}')
    assert v.verdict == "refuted"
    assert v.evidence == "guard holds"


# --- attempt budget ----------------------------------------------------------


def test_attempt_budget_stops_executing_after_the_limit():
    calls: list[dict] = []
    budget = _AttemptBudget(lambda **a: calls.append(a) or "ran", limit=2)

    assert budget(test_path="t.sol") == "ran"
    assert budget(test_path="t.sol") == "ran"
    third = budget(test_path="t.sol")

    assert len(calls) == 2, "forge must not run past the budget"
    assert budget.used == 2
    assert "budget exhausted" in third.lower()
    assert "inconclusive" in third.lower(), "must tell the model how to finalize"


# --- workspace hygiene between verifications ---------------------------------


def test_unconfirmed_pocs_are_moved_out_of_the_compile_path(tmp_path):
    """`forge test --match-path` compiles the whole project, so a broken PoC from
    one verification would break every later one."""
    ws = tmp_path / "ws"
    (ws / "test").mkdir(parents=True)
    (ws / "test" / "F-001.t.sol").write_text("// confirmed, compiles")
    (ws / "test" / "F-002.t.sol").write_text("this does not compile")

    _quarantine_unconfirmed(ToolContext(workspace=ws), keep={"test/F-001.t.sol"})

    assert (ws / "test" / "F-001.t.sol").exists()
    assert not (ws / "test" / "F-002.t.sol").exists()
    # Retained as evidence, just out of the compile path.
    assert (ws / "attempts" / "F-002.t.sol").read_text() == "this does not compile"


@pytest.mark.parametrize(
    "reported", ["test/F-001.t.sol", "./test/F-001.t.sol", "test\\F-001.t.sol"]
)
def test_a_confirmed_poc_is_kept_however_its_path_was_spelled(tmp_path, reported):
    """Quarantining a confirmed PoC because its reported path merely looked
    different would make the grader score a real true positive as a miss."""
    ws = tmp_path / "ws"
    (ws / "test").mkdir(parents=True)
    (ws / "test" / "F-001.t.sol").write_text("// confirmed")

    _quarantine_unconfirmed(ToolContext(workspace=ws), keep={reported})

    assert (ws / "test" / "F-001.t.sol").exists()


# --- report synthesis --------------------------------------------------------


def _report_for(verdicts: list[Verdict]) -> str:
    return _render_report({FINDING.id: FINDING}, verdicts)


def test_refuted_findings_are_omitted_from_the_report():
    md = _report_for([Verdict(finding_id="F-001", verdict="refuted", evidence="guard holds")])
    assert "1 claim(s) refuted" in md
    assert "SECRET_FINDER_REASONING" not in md
    assert "### F-001" not in md, "a refuted claim must not appear as a finding"


def test_confirmed_report_uses_the_verifier_severity_not_the_finder_guess():
    md = _report_for(
        [
            Verdict(
                finding_id="F-001",
                verdict="confirmed",
                severity="critical",  # finder guessed "high"
                poc_path="test/F-001.t.sol",
                evidence="vault drained 6->0",
                attempts=2,
            )
        ]
    )
    assert "F-001 — reentrancy (critical)" in md
    assert "test/F-001.t.sol" in md
    assert "vault drained 6->0" in md


def test_inconclusive_findings_label_the_finder_guess_as_unverified():
    md = _report_for([Verdict(finding_id="F-001", verdict="inconclusive", attempts=4)])
    assert "Needs human review" in md
    assert "unverified" in md


# --- end-to-end orchestration against a scripted adapter ---------------------


@dataclass
class ScriptedAdapter:
    """Replays canned final messages, recording exactly what each agent saw."""

    replies: list[str]
    provider: str = "anthropic"
    seen: list[dict] = field(default_factory=list)

    def check_capabilities(self, model: str) -> None:  # pragma: no cover - trivial
        return None

    def complete(self, *, model, system, tools, messages, max_tokens) -> LLMResponse:
        self.seen.append(
            {
                "system": system,
                "tools": [t["name"] for t in tools],
                "messages": [m.get("content") for m in messages],
            }
        )
        return LLMResponse(text=self.replies.pop(0), tool_calls=[], raw=None, usage={})


def _config() -> AgentConfig:
    return AgentConfig(agent=ModelProfile(provider="anthropic", model="m"), max_poc_attempts=2)


def test_audit_phase1_wires_finder_to_verifier_and_isolates_context(tmp_path, monkeypatch):
    monkeypatch.setattr("pramana.pipeline._ground", lambda ctx, path: "(slither stub)")

    finder_reply = (
        '[{"id":"F-001","contract":"src/EtherStore.sol","location":"withdraw() L18-29",'
        '"vuln_class":"reentrancy","hypothesis":"reenter and drain",'
        '"severity_guess":"high","finder_notes":"SECRET_FINDER_REASONING"}]'
    )
    verifier_reply = (
        '{"finding_id":"F-001","verdict":"confirmed","severity":"critical",'
        '"poc_path":"test/F-001.t.sol","evidence":"drained"}'
    )
    adapter = ScriptedAdapter(replies=[finder_reply, verifier_reply])
    ws = tmp_path / "ws"
    (ws / "test").mkdir(parents=True)

    result = audit_phase1(
        {"anthropic": adapter},
        _config(),
        ToolContext(workspace=ws),
        "src/EtherStore.sol",
    )

    assert result.n_candidates == 1
    assert result.n_confirmed == 1
    assert result.output.findings[0].verdict == "confirmed"
    # The verifier — not the finder — owns severity on a confirmed finding.
    assert result.output.findings[0].severity == "critical"

    finder_call, verifier_call = adapter.seen
    # Two separate agents: different prompts, different tools.
    assert finder_call["tools"] == list(FINDER_TOOL_NAMES)
    assert verifier_call["tools"] == list(VERIFIER_TOOL_NAMES)
    # The isolation itself: the verifier's context contains only its own seed.
    assert len(verifier_call["messages"]) == 1
    assert "SECRET_FINDER_REASONING" not in str(verifier_call["messages"])
    assert "SECRET_FINDER_REASONING" not in verifier_call["system"]


def test_audit_phase1_runs_one_verifier_per_finding(tmp_path, monkeypatch):
    monkeypatch.setattr("pramana.pipeline._ground", lambda ctx, path: "(slither stub)")

    finder_reply = (
        '[{"id":"F-001","contract":"src/A.sol","location":"a()","vuln_class":"reentrancy",'
        '"hypothesis":"h1"},'
        '{"id":"F-002","contract":"src/A.sol","location":"b()","vuln_class":"access-control",'
        '"hypothesis":"h2"}]'
    )
    adapter = ScriptedAdapter(
        replies=[
            finder_reply,
            '{"finding_id":"F-001","verdict":"confirmed","severity":"high",'
            '"poc_path":"test/F-001.t.sol","evidence":"e"}',
            '{"finding_id":"F-002","verdict":"refuted","evidence":"guarded"}',
        ]
    )
    ws = tmp_path / "ws"
    (ws / "test").mkdir(parents=True)

    result = audit_phase1(
        {"anthropic": adapter}, _config(), ToolContext(workspace=ws), "src/A.sol"
    )

    assert len(adapter.seen) == 3  # 1 finder + 2 verifiers
    assert result.n_confirmed == 1
    assert result.n_refuted == 1
    # Each verifier gets its own fresh single-message context.
    assert all(len(call["messages"]) == 1 for call in adapter.seen[1:])
    # Refuted claims stay in the eval data even though the report omits them.
    assert {f.verdict for f in result.output.findings} == {"confirmed", "refuted"}


def test_audit_phase1_fails_closed_when_the_verifier_output_is_unreadable(tmp_path, monkeypatch):
    """An unparseable verdict has proven nothing — it must not silently vanish,
    and it must never be treated as confirmed."""
    monkeypatch.setattr("pramana.pipeline._ground", lambda ctx, path: "(slither stub)")

    adapter = ScriptedAdapter(
        replies=[
            '[{"id":"F-001","contract":"src/A.sol","location":"a()",'
            '"vuln_class":"reentrancy","hypothesis":"h"}]',
            "I think it is probably vulnerable, honestly.",
        ]
    )
    ws = tmp_path / "ws"
    (ws / "test").mkdir(parents=True)

    result = audit_phase1(
        {"anthropic": adapter}, _config(), ToolContext(workspace=ws), "src/A.sol"
    )

    assert result.n_candidates == 1
    assert result.n_confirmed == 0
    assert result.n_inconclusive == 1
    assert "could not be parsed" in (result.output.findings[0].evidence or "")


def test_audit_phase1_reassigns_a_mislabeled_finding_id(tmp_path, monkeypatch):
    """The verifier does not get to relabel which claim it was judging."""
    monkeypatch.setattr("pramana.pipeline._ground", lambda ctx, path: "(slither stub)")

    adapter = ScriptedAdapter(
        replies=[
            '[{"id":"F-001","contract":"src/A.sol","location":"a()",'
            '"vuln_class":"reentrancy","hypothesis":"h"}]',
            '{"finding_id":"WRONG-9","verdict":"refuted","evidence":"e"}',
        ]
    )
    ws = tmp_path / "ws"
    (ws / "test").mkdir(parents=True)

    result = audit_phase1(
        {"anthropic": adapter}, _config(), ToolContext(workspace=ws), "src/A.sol"
    )
    assert result.verdicts[0].finding_id == "F-001"


def test_audit_phase1_on_a_clean_contract_produces_no_findings(tmp_path, monkeypatch):
    """The negative-control path: an empty finder array short-circuits to a
    clean report without ever invoking a verifier."""
    monkeypatch.setattr("pramana.pipeline._ground", lambda ctx, path: "(slither stub)")

    adapter = ScriptedAdapter(replies=["[]"])
    ws = tmp_path / "ws"
    (ws / "test").mkdir(parents=True)

    result = audit_phase1(
        {"anthropic": adapter}, _config(), ToolContext(workspace=ws), "src/A.sol"
    )

    assert len(adapter.seen) == 1, "no verifier should run when there is nothing to verify"
    assert result.n_candidates == 0
    assert result.output.findings == []
    assert "None. No claim was proven" in result.output.report_markdown


# --- config routing ----------------------------------------------------------


def test_roles_fall_back_to_the_single_agent_profile():
    config = _config()
    assert config.role("finder") == config.agent
    assert config.role("verifier") == config.agent
    assert config.label("phase1") == "phase1/anthropic:m"


def test_split_routing_is_visible_in_the_run_label():
    config = AgentConfig(
        agent=ModelProfile(provider="anthropic", model="m"),
        verifier=ModelProfile(provider="anthropic", model="stronger"),
    )
    label = config.label("phase1")
    assert "finder=anthropic:m" in label
    assert "verifier=anthropic:stronger" in label


def test_phase0_and_phase1_labels_are_never_confusable():
    config = _config()
    assert config.label("phase0") != config.label("phase1")
    assert config.label("phase0").startswith("phase0/")


def test_poc_attempts_are_bounded_independently_of_max_turns():
    """`attempts` counts executed forge runs; `max_turns` counts model
    round-trips. Conflating them is explicitly called out in design §4."""
    config = AgentConfig(
        agent=ModelProfile(provider="anthropic", model="m"), max_turns=25, max_poc_attempts=4
    )
    assert config.max_turns != config.max_poc_attempts


def test_poc_path_is_workspace_relative(tmp_path):
    """Grading resolves poc_path against the audit workspace, so the verifier's
    convention must stay relative."""
    seed = build_verifier_seed(bare_claim(FINDING), "F-007", max_attempts=3)
    assert "test/F-007.t.sol" in seed
    assert not Path("test/F-007.t.sol").is_absolute()
