"""The generalized, provider-neutral agent loop (design §1).

One agent = one call to :func:`run_agent`. Its ``messages`` list is created
fresh here, so it is fully isolated from every other agent's context. The loop
is bounded (``max_turns``, not ``while True``) and tool crashes are turned into
error results by ``dispatch`` rather than killing the run.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..providers.base import LLMAdapter, Message, ToolSchema
from ..tools.registry import dispatch

TraceFn = Callable[[dict[str, Any]], None]


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
    trace: TraceFn | None = None,
) -> tuple[str, list[Message]]:
    """Run one agent to completion. Returns (final_text, full_message_history)."""
    messages: list[Message] = [{"role": "user", "content": seed}]

    for turn in range(max_turns):
        response = llm.complete(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            tools=tools,
            messages=messages,
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
            return response.text, messages  # agent is done

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

    raise RuntimeError(f"agent exceeded max_turns ({max_turns})")
