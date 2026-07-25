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
from .retry import RetryPolicy, call_with_retries


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


class AnthropicGatewayAdapter:
    """The Anthropic message surface served by a subscription-replaying proxy.

    Same wire protocol and the same model as first-party ``anthropic`` — the
    only difference is billing. A proxy replaying a Claude subscription charges
    a flat fee, not $5/$25 per million tokens, so reusing the ``anthropic``
    identity would price these runs off the first-party table and report dollars
    that were never charged. This is the Anthropic twin of OpenAIGatewayAdapter;
    the reasoning there applies verbatim.

    Keyed ``anthropic-gateway:<model>``, absent from the price table, so it
    reports ``usd: null`` — an honest gap. Quality metrics are fully valid;
    only cost is unknown.

    Requires ``ANTHROPIC_BASE_URL``: without it the SDK would silently talk to
    first-party Anthropic while the run recorded itself as a gateway.
    """

    provider = "anthropic-gateway"

    # A subscription proxy goes unavailable in *bursts* while its OAuth token
    # refreshes — minutes, not seconds. The first-party default (4 attempts over
    # ~10s) cannot bridge that, and one unbridged burst discards the whole run.
    RETRY_POLICY = RetryPolicy(attempts=7, base_delay=2.0, max_delay=90.0)

    def __new__(cls) -> Any:
        import os

        if not os.environ.get("ANTHROPIC_BASE_URL", "").strip():
            raise ProviderError(
                "provider 'anthropic-gateway' requires ANTHROPIC_BASE_URL to point "
                "at the proxy; without it the run would reach first-party Anthropic "
                "while recording itself as a gateway run"
            )
        adapter = AnthropicAdapter()
        adapter.provider = cls.provider  # identity differs; wire protocol does not
        adapter.retry_policy = cls.RETRY_POLICY
        return adapter


class AnthropicAdapter:
    provider = "anthropic"
    # Overridden per-instance by the gateway, whose failures last longer.
    retry_policy: RetryPolicy | None = None

    def __init__(self) -> None:
        import anthropic  # lazy: importing pramana must not require the SDK

        self._anthropic = anthropic
        # Zero-arg client resolves ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL from
        # the env — the latter is how the gateway points this at the proxy.
        self._client = anthropic.Anthropic()

    def check_capabilities(self, model: str) -> None:
        """Fail fast on an unknown model id, before any fixture is run.

        Tries ``models.retrieve`` first, then falls back to ``models.list``: a
        subscription-replaying proxy (CLIProxyAPI) serves the message surface
        but not per-model retrieve, and a 404 there means "unimplemented", not
        "no such model". Tool calling is universal across Claude models, so
        existence is enough.

        If neither endpoint is usable the model is left unvalidated rather than
        rejected — the first real request surfaces the truth, and refusing to
        start would make the adapter unusable against a working proxy. Never
        falls back to a *different* model: that would make results
        irreproducible.
        """
        try:
            self._client.models.retrieve(model)
            return
        except self._anthropic.NotFoundError:
            pass  # may be an unimplemented endpoint; confirm against the list
        except self._anthropic.APIStatusError as exc:  # auth/permission/etc.
            raise ProviderError(f"could not validate anthropic model {model!r}: {exc}") from exc

        try:
            available = [m.id for m in self._client.models.list()]
        except self._anthropic.APIError:
            return  # endpoint unavailable/unparseable — cannot validate, do not block
        if model not in available:
            raise CapabilityError(
                f"anthropic model {model!r} not found. Available: {', '.join(sorted(available))}"
            )

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
            message = call_with_retries(
                _send,
                policy=self.retry_policy,
                on_retry=_log_retry(self.provider, model),
            )
        except self._anthropic.APIError as exc:
            raise ProviderError(f"{self.provider} request failed: {exc}") from exc

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
