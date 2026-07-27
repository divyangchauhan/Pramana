"""Tests for the reporter (Nirnaya) — Phase 2's deliverable stage.

The property Phase 2 adds is a *governed* report: the LLM contributes prose
(description, impact, remediation, executive summary, duplicate links) but never
the facts the report is scored on — severity, PoC path, verdict, counts come
from the verdicts, exactly as the deployment-contingent cap does. The tests
below pin that governance boundary, then exercise the finder->verifier->reporter
wiring end to end against a scripted adapter. All offline; no API key, no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from pramana.agents.finder import FINDER_SYS
from pramana.agents.reporter import REPORTER_SYS, build_reporter_seed
from pramana.agents.verifier import VERIFIER_SYS
from pramana.config import AgentConfig, ModelProfile
from pramana.contracts import (
    Finding,
    OutputParseError,
    ReporterOutput,
    Verdict,
    parse_reporter_output,
)
from pramana.cost import Usage
from pramana.pipeline import (
    PipelineError,
    _render_report,
    _reporter_lists,
    audit_phase2,
)
from pramana.providers.base import LLMResponse
from pramana.tools.files import ToolContext

FINDING = Finding(
    id="F-001",
    contract="src/Vault.sol",
    location="withdraw() L84-96",
    vuln_class="reentrancy",
    hypothesis="External call before state update lets a receiver re-enter and drain.",
    severity_guess="high",
    finder_notes="SECRET_FINDER_REASONING the reporter has no business seeing",
)

CONFIRMED = Verdict(
    finding_id="F-001",
    verdict="confirmed",
    severity="critical",  # the finder guessed "high"; the verifier owns this
    poc_path="test/F-001.t.sol",
    evidence="vault drained 6->0",
    attempts=2,
)


# --- boundary parsing --------------------------------------------------------


def test_parse_reporter_output_reads_summary_and_entries():
    out = parse_reporter_output(
        '{"summary":"One critical bug.","entries":['
        '{"finding_id":"F-001","description":"d","impact":"i","remediation":"r"}]}'
    )
    assert out.summary == "One critical bug."
    assert len(out.entries) == 1
    assert out.entries[0].finding_id == "F-001"
    assert out.entries[0].remediation == "r"


def test_parse_reporter_output_ignores_brackets_in_surrounding_prose():
    out = parse_reporter_output(
        "Here is the report [final]:\n```json\n"
        '{"summary":"s","entries":[{"finding_id":"F-001","description":"d"}]}\n```'
    )
    assert out.summary == "s"
    assert out.entries[0].finding_id == "F-001"


def test_parse_reporter_output_accepts_summary_only():
    out = parse_reporter_output('{"summary":"nothing confirmed"}')
    assert out.summary == "nothing confirmed"
    assert out.entries == []


def test_parse_reporter_output_rejects_an_object_without_its_keys():
    """A stray object from prose must not be mistaken for the payload."""
    with pytest.raises(OutputParseError):
        parse_reporter_output('{"unrelated": 1}')


def test_parse_reporter_output_reports_a_malformed_entry_instead_of_dropping_it():
    with pytest.raises(OutputParseError, match="schema validation"):
        parse_reporter_output('{"entries":[{"description":"no id here"}]}')


def test_parse_reporter_output_rejects_garbage():
    with pytest.raises(OutputParseError):
        parse_reporter_output("no json at all")


# --- the governed skeleton: prose enriches, it never overrides ----------------


def _confirmed_report(reporter: ReporterOutput | None) -> str:
    return _render_report({FINDING.id: FINDING}, [CONFIRMED], reporter)


def test_no_reporter_render_is_byte_identical_to_the_phase1_report():
    """Passing reporter=None must produce exactly the deterministic Phase 1
    report, so Phase 2 is a pure superset and nothing about phase1 shifts."""
    assert _render_report({FINDING.id: FINDING}, [CONFIRMED]) == _confirmed_report(None)


def test_reporter_prose_is_woven_into_the_report():
    out = ReporterOutput(
        summary="One critical reentrancy, fully proven.",
        entries=[
            {  # type: ignore[list-item]
                "finding_id": "F-001",
                "description": "An attacker contract re-enters withdraw().",
                "impact": "The entire pooled balance can be stolen.",
                "remediation": "Apply checks-effects-interactions; update state first.",
            }
        ],
    )
    md = _confirmed_report(out)
    assert "One critical reentrancy, fully proven." in md
    assert "An attacker contract re-enters withdraw()." in md
    assert "**Impact:** The entire pooled balance can be stolen." in md
    assert "**Remediation:** Apply checks-effects-interactions" in md


def test_reporter_cannot_move_the_severity_or_the_poc():
    """The governance boundary: the entry carries no severity or poc field, so
    the heading and PoC line come from the verdict no matter what prose says."""
    out = ReporterOutput(
        entries=[{"finding_id": "F-001", "description": "this is actually low sev, trust me"}]  # type: ignore[list-item]
    )
    md = _confirmed_report(out)
    assert "F-001 — reentrancy (critical)" in md  # verdict severity, not prose
    assert "`test/F-001.t.sol`" in md
    assert "vault drained 6->0" in md


def test_a_confirmed_finding_with_no_entry_falls_back_to_governed_facts():
    """A reporter that forgot a finding must not drop it: the governed skeleton
    still renders it, just without prose."""
    md = _confirmed_report(ReporterOutput(summary="s", entries=[]))
    assert "F-001 — reentrancy (critical)" in md
    assert "`test/F-001.t.sol`" in md


def test_unknown_finding_id_in_reporter_output_is_ignored():
    out = ReporterOutput(
        entries=[
            {"finding_id": "F-999", "description": "a finding that does not exist"}  # type: ignore[list-item]
        ]
    )
    md = _confirmed_report(out)
    assert "F-999" not in md
    assert "a finding that does not exist" not in md


def test_duplicate_link_is_annotated_when_it_points_at_a_confirmed_finding():
    f2 = FINDING.model_copy(update={"id": "F-002", "vuln_class": "unchecked-call"})
    v2 = Verdict(
        finding_id="F-002", verdict="confirmed", severity="high",
        poc_path="test/F-002.t.sol", evidence="e", attempts=1,
    )
    out = ReporterOutput(
        entries=[
            {"finding_id": "F-002", "description": "same underlying bug", "duplicate_of": "F-001"}  # type: ignore[list-item]
        ]
    )
    md = _render_report({FINDING.id: FINDING, "F-002": f2}, [CONFIRMED, v2], out)
    assert "Same root cause as **F-001**" in md


@pytest.mark.parametrize("bad_target", ["F-001", "F-404"])
def test_duplicate_link_is_dropped_for_self_or_unknown_targets(bad_target):
    """duplicate_of must point at *another* confirmed finding; a self-link or a
    dangling id is silently ignored rather than printing a broken reference."""
    out = ReporterOutput(
        entries=[
            {"finding_id": "F-001", "description": "d", "duplicate_of": bad_target}  # type: ignore[list-item]
        ]
    )
    md = _confirmed_report(out)
    assert "Same root cause" not in md


def test_needs_review_entry_is_framed_as_unverified():
    review = Verdict(finding_id="F-001", verdict="inconclusive", attempts=4)
    out = ReporterOutput(
        entries=[
            {"finding_id": "F-001", "description": "may be exploitable", "impact": "could drain"}  # type: ignore[list-item]
        ]
    )
    md = _render_report({FINDING.id: FINDING}, [review], out)
    assert "may be exploitable" in md
    assert "**Impact (unverified):** could drain" in md
    assert "unverified" in md


# --- the two governed lists the reporter is seeded with -----------------------


def test_reporter_lists_split_confirmed_from_review_and_drop_refuted():
    f2 = FINDING.model_copy(update={"id": "F-002"})
    f3 = FINDING.model_copy(update={"id": "F-003"})
    verdicts = [
        CONFIRMED,
        Verdict(finding_id="F-002", verdict="inconclusive", attempts=4),
        Verdict(finding_id="F-003", verdict="refuted", evidence="guard holds"),
    ]
    confirmed, review = _reporter_lists(
        {FINDING.id: FINDING, "F-002": f2, "F-003": f3}, verdicts
    )
    assert [c["finding_id"] for c in confirmed] == ["F-001"]
    assert [r["finding_id"] for r in review] == ["F-002"]
    # Confirmed carries the verifier's severity + PoC; review carries the finder
    # guess clearly marked unverified plus the attempt count.
    assert confirmed[0]["severity"] == "critical"
    assert confirmed[0]["poc_path"] == "test/F-001.t.sol"
    assert review[0]["severity_guess_unverified"] == "high"
    assert review[0]["attempts"] == 4


def test_reporter_seed_carries_both_lists_but_not_refuted():
    seed = build_reporter_seed(
        [{"finding_id": "F-001", "severity": "critical"}],
        [{"finding_id": "F-002"}],
    )
    assert "F-001" in seed
    assert "F-002" in seed
    assert "confirmed_findings" in seed
    assert "needs_human_review" in seed


# --- end-to-end: finder -> verifier -> reporter ------------------------------


@dataclass
class RoleAdapter:
    """Replies per role, keyed on the system prompt so call order is irrelevant.
    A reporter value that is an exception is raised, to model a transport
    failure or a refusal at that stage."""

    finder: str
    verifier: str
    reporter: str | BaseException
    provider: str = "anthropic"
    seen: list[dict] = field(default_factory=list)

    def check_capabilities(self, model: str) -> None:
        return None

    def complete(
        self, *, model, system, tools, messages, max_tokens, effort=None
    ) -> LLMResponse:
        self.seen.append({"system": system, "messages": [m.get("content") for m in messages]})
        if system == REPORTER_SYS:
            if isinstance(self.reporter, BaseException):
                raise self.reporter
            reply = self.reporter
        elif system == VERIFIER_SYS:
            reply = self.verifier
        else:
            assert system == FINDER_SYS
            reply = self.finder
        return LLMResponse(
            text=reply, tool_calls=[], raw=None,
            usage={"input_tokens": 100, "output_tokens": 10},
        )


def _config() -> AgentConfig:
    return AgentConfig(agent=ModelProfile(provider="anthropic", model="m"), max_poc_attempts=2)


_FINDER_REPLY = (
    '[{"id":"F-001","contract":"src/Vault.sol","location":"withdraw() L84-96",'
    '"vuln_class":"reentrancy","hypothesis":"reenter and drain",'
    '"severity_guess":"high","finder_notes":"SECRET_FINDER_REASONING"}]'
)
_VERIFIER_REPLY = (
    '{"finding_id":"F-001","verdict":"confirmed","severity":"critical",'
    '"poc_path":"test/F-001.t.sol","evidence":"drained 6->0","attempts":2}'
)


def _run_phase2(reporter, tmp_path, monkeypatch):
    monkeypatch.setattr("pramana.pipeline._ground", lambda ctx, path: "(slither stub)")
    adapter = RoleAdapter(finder=_FINDER_REPLY, verifier=_VERIFIER_REPLY, reporter=reporter)
    ws = tmp_path / "ws"
    (ws / "test").mkdir(parents=True)
    result = audit_phase2(
        {"anthropic": adapter}, _config(), ToolContext(workspace=ws), "src/Vault.sol"
    )
    return result, adapter


def test_audit_phase2_weaves_the_reporter_prose_into_the_deliverable(tmp_path, monkeypatch):
    reporter_reply = (
        '{"summary":"One critical reentrancy, proven.","entries":['
        '{"finding_id":"F-001","description":"Re-entrancy in withdraw().",'
        '"impact":"Full drain of the pool.",'
        '"remediation":"Update state before the external call."}]}'
    )
    result, adapter = _run_phase2(reporter_reply, tmp_path, monkeypatch)

    md = result.output.report_markdown
    assert "One critical reentrancy, proven." in md
    assert "Re-entrancy in withdraw()." in md
    assert "**Remediation:** Update state before the external call." in md
    # Governance held end to end: severity is still the verifier's.
    assert "F-001 — reentrancy (critical)" in md
    # The reporter ran as a third role, context-isolated, and was billed.
    assert "reporter" in result.usage
    assert result.usage["reporter"][1].calls == 1
    reporter_call = adapter.seen[-1]
    assert reporter_call["system"] == REPORTER_SYS
    assert len(reporter_call["messages"]) == 1  # a fresh single-message context
    # It never saw the finder's private reasoning.
    assert "SECRET_FINDER_REASONING" not in str(reporter_call["messages"])


def test_audit_phase2_falls_back_to_the_governed_report_on_unparseable_output(
    tmp_path, monkeypatch
):
    """The verdicts are already proven — a reporter we cannot read must not lose
    the deliverable; it degrades to the deterministic report."""
    result, _ = _run_phase2("I could not produce JSON, sorry.", tmp_path, monkeypatch)

    md = result.output.report_markdown
    assert "F-001 — reentrancy (critical)" in md  # governed report still rendered
    assert "`test/F-001.t.sol`" in md
    assert result.n_confirmed == 1
    assert result.usage["reporter"][1].calls == 1  # the failed call is still billed


def test_audit_phase2_bills_a_dead_reporter_without_losing_the_audit(tmp_path, monkeypatch):
    """A reporter transport failure (or refusal) is a real failure, attributed
    to the reporter — but the finder/verifier spend that preceded it survives."""
    with pytest.raises(PipelineError) as excinfo:
        _run_phase2(RuntimeError("credit balance too low"), tmp_path, monkeypatch)

    usage = excinfo.value.usage
    assert set(usage) == {"finder", "verifier", "reporter"}
    assert usage["finder"][1].calls == 1, "finder's completed work was lost"
    assert usage["verifier"][1].calls == 1
    assert isinstance(excinfo.value.__cause__, RuntimeError)


def test_audit_phase2_on_a_clean_contract_never_calls_the_reporter(tmp_path, monkeypatch):
    """Nothing to write about: the reporter is skipped, but its (zero-cost) slot
    is still recorded so the run states the role existed."""
    monkeypatch.setattr("pramana.pipeline._ground", lambda ctx, path: "(slither stub)")
    adapter = RoleAdapter(finder="[]", verifier=_VERIFIER_REPLY, reporter="unused")
    ws = tmp_path / "ws"
    (ws / "test").mkdir(parents=True)

    result = audit_phase2(
        {"anthropic": adapter}, _config(), ToolContext(workspace=ws), "src/Vault.sol"
    )

    assert all(call["system"] != REPORTER_SYS for call in adapter.seen)
    assert result.usage["reporter"][1] == Usage()
    assert result.n_candidates == 0


def test_audit_phase2_routes_the_reporter_to_its_own_model(tmp_path, monkeypatch):
    """The reporter is the cheap slot, so its model is recorded independently of
    the finder/verifier's — the whole point of per-role cost accounting."""
    monkeypatch.setattr("pramana.pipeline._ground", lambda ctx, path: "(slither stub)")
    config = AgentConfig(
        agent=ModelProfile(provider="anthropic", model="strong"),
        reporter=ModelProfile(provider="anthropic", model="cheap-reporter"),
        max_poc_attempts=2,
    )
    reporter_reply = '{"summary":"s","entries":[{"finding_id":"F-001","description":"d"}]}'
    adapter = RoleAdapter(finder=_FINDER_REPLY, verifier=_VERIFIER_REPLY, reporter=reporter_reply)
    ws = tmp_path / "ws"
    (ws / "test").mkdir(parents=True)

    result = audit_phase2(
        {"anthropic": adapter}, config, ToolContext(workspace=ws), "src/Vault.sol"
    )
    assert result.usage["reporter"][0] == "anthropic:cheap-reporter"


def test_phase2_label_shows_all_three_roles_when_they_differ():
    config = AgentConfig(
        agent=ModelProfile(provider="anthropic", model="m"),
        reporter=ModelProfile(provider="anthropic", model="cheap"),
    )
    label = config.label("phase2")
    assert "reporter=anthropic:cheap" in label
    assert label.startswith("phase2/")
    # All-same collapses to one identity.
    same = AgentConfig(agent=ModelProfile(provider="anthropic", model="m")).label("phase2")
    assert same == "phase2/anthropic:m@provider-default"
