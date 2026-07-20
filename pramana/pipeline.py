"""Phase 0 pipeline — the vertical slice (design §10).

A single ``run_agent`` call with all tools, whose prompt does find → write PoC →
report inline. Slither runs once up front and seeds the agent (grounding, §6).
The orchestration is deliberately trivial here; Phases 1–2 split this into
finder / verifier / reporter without changing this entry point's contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agents.loop import TraceFn, run_agent
from .agents.prompts import PHASE0_SYS, PHASE0_TOOLS
from .config import AgentConfig
from .contracts import Phase0Output, parse_phase0_output
from .providers.base import LLMAdapter, Message
from .tools.files import ToolContext
from .tools.registry import build_tool_registry
from .tools.slither import run_slither_summary


@dataclass
class AuditResult:
    output: Phase0Output
    slither_summary: str
    messages: list[Message]
    n_candidates: int
    n_confirmed: int
    n_inconclusive: int


def _build_seed(contract_path: str, slither_summary: str) -> str:
    return (
        f"Target contract path: {contract_path}\n\n"
        f"Slither output (leads to investigate, not findings):\n{slither_summary}\n\n"
        "Audit this contract. Read the source, prove each vulnerability with an "
        "executable Foundry PoC test under test/, and emit the final JSON object "
        "per the output contract."
    )


def audit(
    adapter: LLMAdapter,
    config: AgentConfig,
    ctx: ToolContext,
    contract_path: str,
    *,
    trace: TraceFn | None = None,
) -> AuditResult:
    """Run one Phase 0 audit over ``contract_path`` (workspace-relative)."""
    # Grounding: run the static analyzer once, cache its summary in the seed.
    try:
        slither_summary = run_slither_summary(ctx, contract_path)
    except Exception as exc:  # slither is a lead source; never fatal
        slither_summary = f"(slither unavailable: {exc})"

    registry = build_tool_registry(ctx)
    seed = _build_seed(contract_path, slither_summary)

    final_text, messages = run_agent(
        adapter,
        PHASE0_SYS,
        PHASE0_TOOLS,
        registry,
        seed=seed,
        model=config.agent.model,
        max_turns=config.max_turns,
        max_tokens=config.max_tokens,
        max_output_chars=ctx.max_output_chars,
        trace=trace,
    )

    output = parse_phase0_output(final_text)
    confirmed = [f for f in output.findings if f.verdict == "confirmed"]
    inconclusive = [f for f in output.findings if f.verdict == "inconclusive"]
    return AuditResult(
        output=output,
        slither_summary=slither_summary,
        messages=messages,
        n_candidates=len(output.findings),
        n_confirmed=len(confirmed),
        n_inconclusive=len(inconclusive),
    )


def result_summary(result: AuditResult) -> dict[str, Any]:
    """Small JSON-friendly summary (design §5 counts)."""
    return {
        "n_candidates": result.n_candidates,
        "n_confirmed": result.n_confirmed,
        "n_needs_human_review": result.n_inconclusive,
    }
