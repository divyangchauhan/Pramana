"""The generalized, provider-neutral agent loop (design §1).

One agent = one call to :func:`run_agent`. Its ``messages`` list is created
fresh here, so it is fully isolated from every other agent's context. The loop
is bounded (``max_turns``, not ``while True``) and tool crashes are turned into
error results by ``dispatch`` rather than killing the run.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..cost import Usage
from ..providers.base import LLMAdapter, Message, ToolSchema
from ..tools.registry import dispatch

TraceFn = Callable[[dict[str, Any]], None]


@dataclass
class AgentRun:
    """What one agent produced, and what it cost to produce it."""

    text: str
    messages: list[Message] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


class AgentTurnLimitError(RuntimeError):
    """Raised when an agent exhausts ``max_turns``, carrying what it spent."""

    def __init__(self, message: str, usage: Usage) -> None:
        super().__init__(message)
        self.usage = usage


def spent_on(exc: BaseException) -> Usage:
    """What ``exc`` had already burned before the run died, if it says.

    Every exception leaving :func:`run_agent` carries this. A failure is not a
    refund: the turns that completed were billed, and a config that dies late
    and expensively must not be recorded as the cheap one.
    """
    usage = getattr(exc, "usage", None)
    return usage if isinstance(usage, Usage) else Usage()


def run_agent(
    llm: LLMAdapter,
    system_prompt: str,
    tools: list[ToolSchema],
    tool_registry: dict[str, Callable[..., str]],
    seed: str,
    model: str,
    *,
    max_turns: int = 25,
    max_tokens: int = 16_000,
    max_output_chars: int = 20_000,
    effort: str | None = None,
    trace: TraceFn | None = None,
) -> AgentRun:
    """Run one agent to completion."""
    messages: list[Message] = [{"role": "user", "content": seed}]
    usage = Usage()

    for turn in range(max_turns):
        started = time.monotonic()
        try:
            response = llm.complete(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                tools=tools,
                messages=messages,
                effort=effort,
            )
        except BaseException as exc:
            # Every earlier turn was billed regardless of how this one ended.
            # The failing call itself is not counted: a provider that raises
            # generally did not charge for it, and we have no usage for it.
            setattr(exc, "usage", usage)  # noqa: B010 - attach to arbitrary exc
            raise
        usage += Usage(
            input_tokens=response.usage.get("input_tokens", 0),
            output_tokens=response.usage.get("output_tokens", 0),
            calls=1,
            elapsed_s=time.monotonic() - started,
        )
        messages.append(
            {
                "role": "assistant",
                "content": response.text,
                "tool_calls": response.tool_calls,
            }
        )
        if trace:
            trace(
                {
                    "event": "assistant_turn",
                    "turn": turn,
                    "text_len": len(response.text),
                    "tool_calls": [c.name for c in response.tool_calls],
                    "usage": response.usage,
                }
            )

        if not response.tool_calls:
            return AgentRun(response.text, messages, usage)  # agent is done

        results = [dispatch(call, tool_registry, max_output_chars) for call in response.tool_calls]
        messages.append({"role": "tool", "content": results})
        if trace:
            for call, res in zip(response.tool_calls, results, strict=True):
                trace(
                    {
                        "event": "tool_result",
                        "turn": turn,
                        "tool": call.name,
                        "arguments": call.arguments,
                        "is_error": res.is_error,
                        "output_len": len(res.content),
                    }
                )

    # Carries the usage burned before giving up: a run that hits the ceiling is
    # the *most* expensive kind, and dropping its cost would flatter the config
    # that caused it.
    raise AgentTurnLimitError(f"agent exceeded max_turns ({max_turns})", usage)
