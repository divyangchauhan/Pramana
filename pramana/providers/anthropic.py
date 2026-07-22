"""Anthropic adapter — Anthropic SDK translation only.

Uses the Messages API via streaming (``messages.stream`` + ``get_final_message``)
so large ``max_tokens`` values never trip the SDK's non-streaming timeout guard.
No ``temperature`` (removed on Opus 4.8 — sending it 400s).

``thinking: {type: "adaptive"}`` is sent on every request. It is not optional:
Opus 4.8 does not think at all without it, and this file previously omitted it
on the reasoning that avoiding thinking blocks kept the tool loop simple. That
traded the model's reasoning for a simpler adapter, silently, on a
vulnerability-discovery task. Assistant turns are still rebuilt as plain text +
tool_use blocks; no thinking block is returned alongside ``tool_use``, so
nothing is dropped in the replay.
"""

from __future__ import annotations

import sys
from typing import Any

from .base import (
    CapabilityError,
    LLMResponse,
    Message,
    ProviderError,
    ToolCall,
    ToolSchema,
)
from .retry import call_with_retries


def _log_retry(provider: str, model: str):
    """Make a retry visible. A run that needed three attempts to get an answer
    is not the same as one that got it first try, and silence would hide a
    degrading endpoint until it failed outright."""

    def _report(attempt: int, delay: float, exc: BaseException) -> None:
        print(
            f"  [{provider}:{model}] transient failure (attempt {attempt}), "
            f"retrying in {delay:.1f}s: {str(exc)[:120]}",
            file=sys.stderr,
        )

    return _report


class AnthropicAdapter:
    provider = "anthropic"

    def __init__(self) -> None:
        import anthropic  # lazy: importing pramana must not require the SDK

        self._anthropic = anthropic
        # Zero-arg client resolves ANTHROPIC_API_KEY / auth profile from the env.
        self._client = anthropic.Anthropic()

    def check_capabilities(self, model: str) -> None:
        try:
            self._client.models.retrieve(model)
        except self._anthropic.NotFoundError as exc:
            raise CapabilityError(f"anthropic model {model!r} not found") from exc
        except self._anthropic.APIStatusError as exc:  # auth/permission/etc.
            raise ProviderError(f"could not validate anthropic model {model!r}: {exc}") from exc
        # Tool calling is universal across Claude models, so existence is enough.

    def complete(
        self,
        *,
        model: str,
        system: str,
        tools: list[ToolSchema],
        messages: list[Message],
        max_tokens: int,
        effort: str | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [self._to_wire(m) for m in messages],
            # REQUIRED for Opus 4.8 to think at all. Anthropic's docs are
            # explicit: "Set thinking: {type: 'adaptive'} to enable thinking;
            # without it, requests run without thinking." Omitting this ran
            # every audit in this repo's history on a model that never reasoned
            # before answering — while Fable 5, whose adaptive thinking cannot
            # be disabled, would have reasoned. That is not a model comparison.
            "thinking": {"type": "adaptive"},
        }
        if effort:
            kwargs["output_config"] = {"effort": effort}
        if tools:
            kwargs["tools"] = tools

        def _send() -> Any:
            with self._client.messages.stream(**kwargs) as stream:
                return stream.get_final_message()

        try:
            message = call_with_retries(_send, on_retry=_log_retry("anthropic", model))
        except self._anthropic.APIError as exc:
            raise ProviderError(f"anthropic request failed: {exc}") from exc

        return self._from_wire(message)

    # --- translation ---------------------------------------------------------

    @staticmethod
    def _to_wire(msg: Message) -> dict[str, Any]:
        role = msg["role"]
        if role == "user":
            return {"role": "user", "content": msg["content"]}

        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = (msg.get("content") or "").strip()
            if text:
                blocks.append({"type": "text", "text": text})
            for call in msg.get("tool_calls", []):
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            return {"role": "assistant", "content": blocks}

        if role == "tool":
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.call_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    }
                    for r in msg["content"]
                ],
            }

        raise ProviderError(f"unknown canonical message role {role!r}")

    @staticmethod
    def _from_wire(message: Any) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )
        usage = {
            "input_tokens": getattr(message.usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(message.usage, "output_tokens", 0) or 0,
        }
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            raw=message,
            usage=usage,
        )
