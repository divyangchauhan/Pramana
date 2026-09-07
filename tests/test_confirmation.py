"""Confirmation requires execution evidence, in both the pipeline and deliverable."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from unittest.mock import Mock

import pytest

from pramana.agents.finder import FINDER_SYS
from pramana.agents.prompts import PHASE0_SYS
from pramana.agents.reporter import REPORTER_SYS
from pramana.config import AgentConfig
from pramana.contracts import Finding, Verdict
from pramana.eval import harness
from pramana.eval.workspace import build_workspace, load_fixtures
from pramana.pipeline import audit_phase0, audit_phase1, audit_phase2, verify_finding
from pramana.providers.base import LLMResponse, ToolCall
from pramana.tools.files import ToolContext, ToolError
from pramana.tools.foundry import ForgeResult, _run_once

FINDING = Finding(
    id="F-001", contract="src/EtherStore.sol", location="withdraw()",
    vuln_class="reentrancy", hypothesis="An external call allows a repeated withdrawal.",
    severity_guess="critical",
)


@dataclass
class ClaimAdapter:
    """The model says 'confirmed' without executing any tests itself."""

    poc_path: str | None = "test/F-001.t.sol"
    writes: dict[str, str] = field(default_factory=dict)
    wrote: bool = False
    provider: str = "anthropic"
    reporter_seeds: list[str] = field(default_factory=list)

    def check_capabilities(self, model: str) -> None:
        pass

    def complete(self, *, model, system, tools, messages, max_tokens, effort=None):
        verdict = {
            "finding_id": FINDING.id, "verdict": "confirmed", "severity": "critical",
            "poc_path": self.poc_path, "evidence": "The model claims the vault was drained.",
        }
        if system == FINDER_SYS:
            text = json.dumps([FINDING.model_dump()])
        elif system == REPORTER_SYS:
            self.reporter_seeds.append(str(messages[0]["content"]))
            text = '{"summary":"MODEL_REPORT_SUMMARY","entries":[]}'
        else:
            if self.writes and not self.wrote:
                self.wrote = True
                return LLMResponse(
                    text="", raw=None, usage={},
                    tool_calls=[
                        ToolCall(id=str(i), name="write_file", arguments={"path": p, "content": c})
                        for i, (p, c) in enumerate(self.writes.items())
                    ],
                )
            if system == PHASE0_SYS:
                text = json.dumps({
                    "findings": [{**FINDING.model_dump(), **verdict}],
                    "report_markdown": "MODEL_REPORT_SUMMARY: this finding is confirmed.",
                })
            else:
                text = json.dumps(verdict)
        return LLMResponse(text=text, tool_calls=[], raw=None, usage={})


def _audit(pipeline, adapter, ws):
    config = AgentConfig.for_provider("anthropic")
    ctx = ToolContext(workspace=ws, forge_retries=0)
    if pipeline == "phase0":
        return audit_phase0(adapter, config, ctx, FINDING.contract)
    fn = audit_phase1 if pipeline == "phase1" else audit_phase2
    return fn({"anthropic": adapter}, config, ctx, FINDING.contract)


@pytest.mark.parametrize("pipeline", ["phase0", "phase1", "phase2"])
@pytest.mark.parametrize("case", ["no-path", "missing", "failed", "no-tests", "timeout", "passed"])
def test_pipeline_requires_a_passing_final_poc(pipeline, case, tmp_path, monkeypatch):
    monkeypatch.setattr("pramana.pipeline._ground", lambda *a: "no leads")
    adapter = ClaimAdapter(poc_path=None if case == "no-path" else "test/F-001.t.sol")
    if case not in {"no-path", "missing"}:
        (tmp_path / "test").mkdir()
        (tmp_path / "test/F-001.t.sol").write_text("// final PoC")
    check = ForgeResult(case != "no-tests", case == "passed", "trusted Forge diagnostic")
    runner = Mock(return_value=check)
    if case == "timeout":
        runner.side_effect = ToolError("forge test timed out")
    monkeypatch.setattr("pramana.pipeline.forge_test", runner)

    result = _audit(pipeline, adapter, tmp_path)

    expected = "confirmed" if case == "passed" else "inconclusive"
    assert result.output.findings[0].verdict == expected
    assert result.n_confirmed == int(case == "passed")
    assert result.n_inconclusive == int(case != "passed")
    if case != "passed":
        assert result.output.findings[0].severity is None
        assert "confirmation was rejected" in (result.output.findings[0].evidence or "")
        assert "0 confirmed finding(s)" in result.output.report_markdown
        assert "F-001 — reentrancy (unverified)" in result.output.report_markdown
        assert "F-001 — reentrancy (critical)" not in result.output.report_markdown
        if pipeline == "phase0":
            assert "MODEL_REPORT_SUMMARY" not in result.output.report_markdown
        if pipeline == "phase2":
            seed = adapter.reporter_seeds[0]
            assert '"confirmed_findings": []' in seed
            assert '"finding_id": "F-001"' in seed
    if case in {"no-path", "missing"}:
        runner.assert_not_called()
    else:
        assert runner.called
        assert runner.call_args.args[1] == "test/F-001.t.sol"


@pytest.mark.parametrize("path", ["../outside.t.sol", "test", "test/*.t.sol", "src/A.sol"])
def test_invalid_poc_paths_cannot_confirm(path, tmp_path, monkeypatch):
    (tmp_path / "test").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src/A.sol").write_text("contract A {}")
    runner = Mock(side_effect=AssertionError("invalid paths must not run Forge"))
    monkeypatch.setattr("pramana.pipeline.forge_test", runner)
    verdict, _, _ = verify_finding(
        {"anthropic": ClaimAdapter(poc_path=path)}, AgentConfig.for_provider("anthropic"),
        ToolContext(workspace=tmp_path), FINDING, trace=None,
    )
    assert verdict.verdict == "inconclusive"
    runner.assert_not_called()


@pytest.mark.parametrize("path", ["./test/F-001.t.sol", "test\\F-001.t.sol"])
def test_equivalent_poc_paths_are_checked_and_normalized(path, tmp_path, monkeypatch):
    (tmp_path / "test").mkdir()
    (tmp_path / "test/F-001.t.sol").write_text("// PoC")
    runner = Mock(return_value=ForgeResult(True, True, "passed"))
    monkeypatch.setattr("pramana.pipeline.forge_test", runner)
    events = []
    verdict, attempts, _ = verify_finding(
        {"anthropic": ClaimAdapter(poc_path=path)}, AgentConfig.for_provider("anthropic"),
        ToolContext(workspace=tmp_path), FINDING, trace=events.append,
    )
    assert verdict.verdict == "confirmed"
    assert verdict.poc_path == "test/F-001.t.sol"
    assert attempts == 0  # the independent check is separate from the model's attempt budget
    assert any(e.get("event") == "poc_confirmation" and e["passed"] for e in events)


def test_nonzero_forge_exit_cannot_be_a_pass_even_with_a_passing_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "pramana.tools.foundry.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess([], 1, "1 passed; 0 failed", "fatal error"),
    )
    result = _run_once(tmp_path, "test/F-001.t.sol", 30)
    assert result.ran and not result.passed


@pytest.mark.parametrize("pipeline", ["phase0", "phase1", "phase2"])
@pytest.mark.parametrize("pristine_passes", [False, True])
def test_report_and_json_follow_the_same_pristine_check(
    pipeline, pristine_passes, tmp_path, monkeypatch,
):
    monkeypatch.setattr("pramana.pipeline._ground", lambda *a: "no leads")
    monkeypatch.setattr(
        "pramana.pipeline.forge_test", lambda *a, **kw: ForgeResult(True, True, "local pass")
    )
    adapter = ClaimAdapter(writes={"test/F-001.t.sol": "// model's PoC"})
    monkeypatch.setattr(harness, "build_adapter", lambda *a: adapter)
    pristine = Mock(return_value=ForgeResult(True, pristine_passes, "pristine check result"))
    monkeypatch.setattr(harness, "_verify_poc", pristine)
    fixtures = load_fixtures(names=["reentrancy-vault"])

    row = harness.run_agent_eval(
        fixtures, AgentConfig.for_provider("anthropic"), tmp_path, 30, pipeline=pipeline,
    )[0]

    # The authoritative rerun is reused by grading; a second flaky run cannot
    # create a different score and report for the same finding.
    pristine.assert_called_once()
    assert row.n_confirmed == row.confirmed_poc_pass == row.true_positive_findings == int(
        pristine_passes
    )
    detail = row.details[0]
    assert detail["verdict"] == ("confirmed" if pristine_passes else "inconclusive")
    assert detail["pre_grading_verdict"] == "confirmed"
    assert detail["poc_ran"] is True
    assert detail["poc_passed"] is pristine_passes
    harness.write_reports([row], tmp_path / "reports")
    report = (tmp_path / "reports/reentrancy-vault.md").read_text()
    if not pristine_passes:
        assert "MODEL_REPORT_SUMMARY" not in report  # stale prose must also be removed
        assert "**Confirmed / PoC-verified:** 0 / 0" in report
        assert "0 confirmed finding(s)" in report
        assert "F-001 — reentrancy (unverified)" in report
        assert "pristine check result" in report
        assert "confirmation was rejected" in detail["evidence"]


def test_a_later_verifier_cannot_invalidate_an_earlier_poc_silently(tmp_path, monkeypatch):
    monkeypatch.setattr("pramana.pipeline._ground", lambda *a: "no leads")
    second = FINDING.model_copy(update={"id": "F-002"})
    adapter = ClaimAdapter()
    original_complete = adapter.complete

    def complete(**kwargs):
        if kwargs["system"] == FINDER_SYS:
            return LLMResponse(
                text=json.dumps([FINDING.model_dump(), second.model_dump()]),
                tool_calls=[], raw=None, usage={},
            )
        return original_complete(**kwargs)

    monkeypatch.setattr(adapter, "complete", complete)
    (tmp_path / "test").mkdir()
    poc = tmp_path / "test/F-001.t.sol"

    def verify(adapters, config, ctx, finding, **kwargs):
        from pramana.cost import Usage
        if finding.id == "F-001":
            poc.write_text("passed")
            return Verdict(finding_id=finding.id, verdict="confirmed", severity="high",
                           poc_path="test/F-001.t.sol"), 1, Usage()
        poc.write_text("broken by second verifier")
        return Verdict(finding_id=finding.id, verdict="refuted"), 1, Usage()

    monkeypatch.setattr("pramana.pipeline.verify_finding", verify)
    monkeypatch.setattr(
        "pramana.pipeline.forge_test",
        lambda *a, **kw: ForgeResult(True, poc.read_text() == "passed", "final file failed"),
    )
    result = _audit("phase1", adapter, tmp_path)
    assert result.n_confirmed == 0
    assert result.n_refuted == 1
    assert result.n_inconclusive == 1
    assert "final file failed" in result.output.report_markdown


@pytest.mark.skipif(shutil.which("forge") is None, reason="requires Foundry")
def test_real_reference_exploit_can_be_confirmed_without_trusting_model_execution(tmp_path):
    fixture = load_fixtures(names=["reentrancy-vault"])[0]
    ws = build_workspace(fixture, tmp_path / "audit")
    assert fixture.reference_poc
    shutil.copy(fixture.dir / fixture.reference_poc, ws / "test/F-001.t.sol")
    verdict, _, _ = verify_finding(
        {"anthropic": ClaimAdapter()}, AgentConfig.for_provider("anthropic"),
        ToolContext(workspace=ws, forge_retries=0), FINDING, trace=None,
    )
    assert verdict.verdict == "confirmed"


@pytest.mark.skipif(shutil.which("forge") is None, reason="requires Foundry")
def test_real_pristine_rerun_rejects_a_poc_that_only_passes_on_an_edited_target(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr("pramana.pipeline._ground", lambda *a: "no leads")
    vulnerable = load_fixtures(names=["reentrancy-vault"])[0]
    assert vulnerable.reference_poc
    adapter = ClaimAdapter(writes={
        "src/EtherStore.sol": (vulnerable.dir / "src/EtherStore.sol").read_text(),
        "test/F-001.t.sol": (vulnerable.dir / vulnerable.reference_poc).read_text(),
    })
    monkeypatch.setattr(harness, "build_adapter", lambda *a: adapter)
    fixtures = load_fixtures(names=["reentrancy-vault-patched"])
    row = harness.run_agent_eval(
        fixtures, AgentConfig.for_provider("anthropic"), tmp_path, 60,
        forge_retries=0, pipeline="phase2",
    )[0]
    assert row.error is None
    assert row.details[0]["pre_grading_verdict"] == "confirmed"  # passed against the edited target
    assert row.details[0]["verdict"] == "inconclusive"  # failed against the original target
    assert row.n_confirmed == row.confirmed_poc_pass == 0
    assert "MODEL_REPORT_SUMMARY" not in row.report_markdown
    assert "F-001 — reentrancy (unverified)" in row.report_markdown
