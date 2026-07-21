"""The orchestrator (design §5) — plain Python. This is the entire
"multi-agent" layer.

Two pipelines live here, selectable at run time so the architectural change can
be *measured* rather than asserted:

* :func:`audit_phase0` — the vertical slice. One ``run_agent`` call with all
  tools, whose prompt does find -> prove -> report inline.
* :func:`audit_phase1` — finder -> verifier. The finder proposes hypotheses and
  can only read; each hypothesis is then handed to a separate, context-isolated
  verifier that can write and execute code, and whose job is to disprove it.

Both return the same :class:`AuditResult`, so the eval harness and grader are
identical across pipelines and the comparison is apples-to-apples.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from .agents.finder import FINDER_SYS, FINDER_TOOLS
from .agents.loop import TraceFn, run_agent
from .agents.prompts import PHASE0_SYS, PHASE0_TOOLS
from .agents.verifier import VERIFIER_SYS, VERIFIER_TOOLS, build_verifier_seed
from .config import AgentConfig
from .contracts import (
    Finding,
    OutputParseError,
    Phase0Finding,
    Phase0Output,
    Verdict,
    bare_claim,
    parse_findings,
    parse_phase0_output,
    parse_verdict,
)
from .providers.base import LLMAdapter, Message
from .tools.files import ToolContext
from .tools.registry import build_tool_registry
from .tools.slither import run_slither_summary

FINDER_TOOL_NAMES = ("read_file", "run_slither")
VERIFIER_TOOL_NAMES = ("read_file", "write_file", "run_foundry_test")

# Non-confirmed PoCs are moved here after each verification. They stay on disk
# as evidence, but out of test/ — see _quarantine_unconfirmed.
ATTEMPTS_DIR = "attempts"


@dataclass
class AuditResult:
    output: Phase0Output
    slither_summary: str
    messages: list[Message]
    n_candidates: int
    n_confirmed: int
    n_inconclusive: int
    n_refuted: int = 0
    findings: list[Finding] = field(default_factory=list)
    verdicts: list[Verdict] = field(default_factory=list)
    poc_attempts: dict[str, int] = field(default_factory=dict)


# --- Phase 0: one combined agent ---------------------------------------------


def _build_seed(contract_path: str, slither_summary: str) -> str:
    return (
        f"Target contract path: {contract_path}\n\n"
        f"Slither output (leads to investigate, not findings):\n{slither_summary}\n\n"
        "Audit this contract. Read the source, prove each vulnerability with an "
        "executable Foundry PoC test under test/, and emit the final JSON object "
        "per the output contract."
    )


def _ground(ctx: ToolContext, contract_path: str) -> str:
    """Run the static analyzer once. Slither is a lead source, never fatal."""
    try:
        return run_slither_summary(ctx, contract_path)
    except Exception as exc:
        return f"(slither unavailable: {exc})"


def audit_phase0(
    adapter: LLMAdapter,
    config: AgentConfig,
    ctx: ToolContext,
    contract_path: str,
    *,
    trace: TraceFn | None = None,
) -> AuditResult:
    """Run one Phase 0 audit over ``contract_path`` (workspace-relative)."""
    slither_summary = _ground(ctx, contract_path)
    registry = build_tool_registry(ctx)

    final_text, messages = run_agent(
        adapter,
        PHASE0_SYS,
        PHASE0_TOOLS,
        registry,
        seed=_build_seed(contract_path, slither_summary),
        model=config.agent.model,
        max_turns=config.max_turns,
        max_tokens=config.max_tokens,
        max_output_chars=ctx.max_output_chars,
        trace=trace,
    )

    output = parse_phase0_output(final_text)
    return AuditResult(
        output=output,
        slither_summary=slither_summary,
        messages=messages,
        n_candidates=len(output.findings),
        n_confirmed=sum(f.verdict == "confirmed" for f in output.findings),
        n_inconclusive=sum(f.verdict == "inconclusive" for f in output.findings),
        n_refuted=sum(f.verdict == "refuted" for f in output.findings),
    )


# Back-compat alias: the Phase 0 entry point.
audit = audit_phase0


# --- Phase 1: finder -> verifier ---------------------------------------------


class _AttemptBudget:
    """Wraps run_foundry_test to bound *executed* forge runs per verification.

    ``max_turns`` bounds model round-trips; this bounds PoC executions, which is
    a different axis (design §4). Past the budget the tool stops running and
    tells the model to finalize, so the loop ends with an honest verdict instead
    of being cut off mid-thought.
    """

    def __init__(self, inner: Callable[..., str], limit: int) -> None:
        self._inner = inner
        self._limit = limit
        self.used = 0

    def __call__(self, **arguments: Any) -> str:
        if self.used >= self._limit:
            return (
                f"Attempt budget exhausted ({self._limit} forge runs). No further "
                "PoC executions are available. Finalize your verdict now — return "
                "'inconclusive' unless an earlier run already proved the exploit."
            )
        self.used += 1
        return self._inner(**arguments)


def _role_trace(trace: TraceFn | None, role: str, finding_id: str | None = None) -> TraceFn | None:
    if trace is None:
        return None

    def _tagged(event: dict[str, Any]) -> None:
        trace({**event, "role": role, **({"finding_id": finding_id} if finding_id else {})})

    return _tagged


def _normalize_ws_path(path: str) -> str:
    """Workspace-relative path in a comparable form.

    Models report the same file as ``test/F-001.t.sol``, ``./test/F-001.t.sol``
    or with backslashes. Comparing raw strings would quarantine a *confirmed*
    PoC because its reported path merely looked different, and the grader would
    then score a real true positive as a miss.
    """
    return PurePosixPath(path.replace("\\", "/")).as_posix().removeprefix("./")


def _quarantine_unconfirmed(ctx: ToolContext, keep: set[str]) -> None:
    """Move every test/*.t.sol that is not a confirmed PoC out of the compile path.

    ``forge test --match-path`` still *compiles* the whole project, so a broken
    or failing PoC left behind by one verification would break every later one.
    Confirmed PoCs compile by definition (they ran and passed), so they stay.
    """
    test_dir = ctx.workspace / "test"
    if not test_dir.is_dir():
        return
    keep_normalized = {_normalize_ws_path(p) for p in keep}
    quarantine = ctx.workspace / ATTEMPTS_DIR
    for path in sorted(test_dir.glob("*.t.sol")):
        if _normalize_ws_path(str(path.relative_to(ctx.workspace))) in keep_normalized:
            continue
        quarantine.mkdir(parents=True, exist_ok=True)
        path.replace(quarantine / path.name)


def verify_finding(
    adapters: Mapping[str, LLMAdapter],
    config: AgentConfig,
    ctx: ToolContext,
    finding: Finding,
    *,
    trace: TraceFn | None,
) -> tuple[Verdict, int]:
    """Run one context-isolated verification. Returns (verdict, forge runs used).

    Public so a single hand-written claim can be put to the verifier directly
    (see ``pramana.eval.refutation``) without going through the finder.

    The verifier gets a fresh ``run_agent`` call seeded with the bare claim
    alone — no finder notes, no severity guess, no prior messages.
    """
    profile = config.role("verifier")
    registry = build_tool_registry(ctx, VERIFIER_TOOL_NAMES)
    budget = _AttemptBudget(registry["run_foundry_test"], config.max_poc_attempts)
    registry["run_foundry_test"] = budget

    seed = build_verifier_seed(bare_claim(finding), finding.id, config.max_poc_attempts)

    final_text, _ = run_agent(
        adapters[profile.provider],
        VERIFIER_SYS,
        VERIFIER_TOOLS,
        registry,
        seed=seed,
        model=profile.model,
        max_turns=config.max_turns,
        max_tokens=config.max_tokens,
        max_output_chars=ctx.max_output_chars,
        trace=_role_trace(trace, "verifier", finding.id),
    )

    try:
        verdict = parse_verdict(final_text)
    except OutputParseError as exc:
        # A verifier whose output we cannot read has not proven anything. Fail
        # closed to inconclusive rather than dropping the finding silently.
        verdict = Verdict(
            finding_id=finding.id,
            verdict="inconclusive",
            evidence=f"verifier output could not be parsed: {exc}",
        )

    # The verifier does not get to relabel which finding it was judging.
    if verdict.finding_id != finding.id:
        verdict = verdict.model_copy(update={"finding_id": finding.id})
    verdict = verdict.model_copy(update={"attempts": budget.used})
    return verdict, budget.used


def _render_report(findings: dict[str, Finding], verdicts: list[Verdict]) -> str:
    """Deterministic report synthesis.

    Phase 1 has no reporter agent yet (design §10 puts it in Phase 2), so the
    deliverable is assembled in Python from the verdicts. Refuted findings are
    omitted from the report but retained in the eval data (design §3.3).
    """
    confirmed = [v for v in verdicts if v.verdict == "confirmed"]
    review = [v for v in verdicts if v.verdict == "inconclusive"]
    refuted = [v for v in verdicts if v.verdict == "refuted"]

    lines = ["# Audit report", ""]
    lines.append(
        f"{len(confirmed)} confirmed finding(s) proven with an executable PoC; "
        f"{len(review)} needing human review; {len(refuted)} claim(s) refuted by the verifier."
    )
    lines.append("")

    lines.append("## Confirmed findings")
    lines.append("")
    if not confirmed:
        lines += ["None. No claim was proven with a passing proof-of-concept exploit.", ""]
    for v in confirmed:
        f = findings[v.finding_id]
        lines += [
            f"### {f.id} — {f.vuln_class} ({v.severity or 'unrated'})",
            "",
            f"- **Contract:** `{f.contract}`",
            f"- **Location:** {f.location}",
            f"- **Hypothesis:** {f.hypothesis}",
            f"- **PoC:** `{v.poc_path}` (proven in {v.attempts} executed forge run(s))",
            f"- **Evidence:** {v.evidence or '(none recorded)'}",
            "",
        ]

    lines += ["## Needs human review", ""]
    if not review:
        lines += ["None.", ""]
    for v in review:
        f = findings[v.finding_id]
        lines += [
            f"### {f.id} — {f.vuln_class} (unverified)",
            "",
            f"- **Contract:** `{f.contract}`",
            f"- **Location:** {f.location}",
            f"- **Hypothesis:** {f.hypothesis}",
            f"- **Finder severity guess:** {f.severity_guess or 'none'} "
            "*(unverified — not an authoritative grade)*",
            f"- **Verification attempts:** {v.attempts} executed forge run(s)",
            f"- **Why inconclusive:** {v.evidence or '(none recorded)'}",
            "",
        ]

    return "\n".join(lines).rstrip() + "\n"


def audit_phase1(
    adapters: Mapping[str, LLMAdapter],
    config: AgentConfig,
    ctx: ToolContext,
    contract_path: str,
    *,
    trace: TraceFn | None = None,
) -> AuditResult:
    """Finder -> verifier, with each verification context-isolated (design §10)."""
    slither_summary = _ground(ctx, contract_path)

    # --- Agent 1: finder. Read-only: it cannot prove its own hypotheses. ---
    finder_profile = config.role("finder")
    finder_text, messages = run_agent(
        adapters[finder_profile.provider],
        FINDER_SYS,
        FINDER_TOOLS,
        build_tool_registry(ctx, FINDER_TOOL_NAMES),
        seed=(
            f"Target contract path: {contract_path}\n\n"
            f"Slither output (leads to investigate, not findings):\n{slither_summary}\n\n"
            "Review this contract and propose candidate findings as a JSON array."
        ),
        model=finder_profile.model,
        max_turns=config.max_turns,
        max_tokens=config.max_tokens,
        max_output_chars=ctx.max_output_chars,
        trace=_role_trace(trace, "finder"),
    )
    findings = parse_findings(finder_text)

    # --- Agent 2: verifier, once per finding, each in a fresh context. ---
    by_id = {f.id: f for f in findings}
    verdicts: list[Verdict] = []
    attempts: dict[str, int] = {}
    confirmed_pocs: set[str] = set()

    for finding in findings:
        verdict, used = verify_finding(adapters, config, ctx, finding, trace=trace)
        verdicts.append(verdict)
        attempts[finding.id] = used
        if verdict.verdict == "confirmed" and verdict.poc_path:
            confirmed_pocs.add(verdict.poc_path)
        # Keep test/ compilable for the next verification.
        _quarantine_unconfirmed(ctx, confirmed_pocs)

    phase0_findings = [
        Phase0Finding(
            id=f.id,
            contract=f.contract,
            location=f.location,
            vuln_class=f.vuln_class,
            hypothesis=f.hypothesis,
            # The verifier owns severity; the finder's guess is never promoted.
            severity=v.severity if v.verdict == "confirmed" else None,
            verdict=v.verdict,
            poc_path=v.poc_path,
            evidence=v.evidence,
        )
        for f, v in ((by_id[v.finding_id], v) for v in verdicts)
    ]

    output = Phase0Output(
        findings=phase0_findings,
        report_markdown=_render_report(by_id, verdicts),
    )
    return AuditResult(
        output=output,
        slither_summary=slither_summary,
        messages=messages,
        n_candidates=len(findings),
        n_confirmed=sum(v.verdict == "confirmed" for v in verdicts),
        n_inconclusive=sum(v.verdict == "inconclusive" for v in verdicts),
        n_refuted=sum(v.verdict == "refuted" for v in verdicts),
        findings=findings,
        verdicts=verdicts,
        poc_attempts=attempts,
    )


PIPELINES: dict[str, str] = {
    "phase0": "single combined agent (find -> prove -> report inline)",
    "phase1": "finder -> context-isolated verifier",
}


def result_summary(result: AuditResult) -> dict[str, Any]:
    """Small JSON-friendly summary (design §5 counts)."""
    return {
        "n_candidates": result.n_candidates,
        "n_confirmed": result.n_confirmed,
        "n_refuted": result.n_refuted,
        "n_needs_human_review": result.n_inconclusive,
    }


__all__ = [
    "AuditResult",
    "PIPELINES",
    "audit",
    "audit_phase0",
    "audit_phase1",
    "verify_finding",
    "result_summary",
]
