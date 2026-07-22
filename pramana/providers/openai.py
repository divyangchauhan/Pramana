"""OpenAI adapter — OpenAI SDK translation only.

Uses the Chat Completions API with function calling — the most stable,
model-agnostic surface across GPT and reasoning ("o"/"gpt-5") models. No
``temperature`` is sent (reasoning models reject non-default sampling), and the
output cap is passed as ``max_completion_tokens`` (the parameter reasoning
models require). The rest of Pramana never learns which lab served a turn.

Set ``OPENAI_BASE_URL`` to target any OpenAI-compatible endpoint — a gateway
(OpenRouter, LiteLLM), a local server (vLLM, Ollama), or a proxy. The SDK reads
that variable itself, so no wiring is needed here; what *is* needed is tolerating
gateways that implement only part of the API (see ``check_capabilities``).
"""

from __future__ import annotations

import json
from typing import Any

from .base import (
    CapabilityError,
    LLMResponse,
    Message,
    ProviderError,
    ToolCall,
    ToolSchema,
)


class OpenAIGatewayAdapter:
    """The same wire protocol, deliberately a *different provider identity*.

    An OpenAI-compatible gateway serves OpenAI model ids while billing on
    entirely different terms — a proxy replaying a Codex subscription charges a
    flat fee, not $5/$30 per million tokens. Reusing the ``openai`` identity
    would price those runs off the first-party table and report dollars that
    were never charged, quietly corrupting the one axis the cost accounting
    exists to measure.

    So gateway runs are keyed ``openai-gateway:<model>``, which is absent from
    the price table and therefore reports ``usd: null`` — an honest gap rather
    than a confident fiction. Quality metrics from a gateway row are fully
    valid; only its cost is unknown.

    Requires ``OPENAI_BASE_URL``: without it the SDK would silently talk to
    first-party OpenAI while the run recorded itself as a gateway.
    """

    provider = "openai-gateway"

    def __new__(cls) -> Any:
        import os

        if not os.environ.get("OPENAI_BASE_URL", "").strip():
            raise ProviderError(
                "provider 'openai-gateway' requires OPENAI_BASE_URL to point at "
                "the gateway; without it the run would reach first-party OpenAI "
                "while recording itself as a gateway run"
            )
        adapter = OpenAIAdapter()
        adapter.provider = cls.provider  # identity differs; wire protocol does not
        return adapter


class OpenAIAdapter:
    provider = "openai"
    # OpenAI's newer output-cap parameter. OpenAI-compatible providers that only
    # accept the legacy `max_tokens` override this (see KimiAdapter).
    _token_param = "max_completion_tokens"

    def __init__(self) -> None:
        import openai  # lazy import

        self._openai = openai
        # Zero-arg client resolves OPENAI_API_KEY from the environment.
        self._client = openai.OpenAI()

    def check_capabilities(self, model: str) -> None:
        """Fail fast on an unknown model id, before any fixture is run.

        Tries ``models.retrieve`` first, then falls back to ``models.list``:
        OpenAI-compatible gateways (LiteLLM, vLLM, OpenRouter, local proxies)
        commonly serve the list endpoint but not per-model retrieve, and a 404
        from retrieve there means "unimplemented", not "no such model".

        If neither endpoint is usable the model is left unvalidated rather than
        rejected — the first real request will surface the truth, and refusing
        to start would make the adapter unusable against otherwise working
        endpoints. Never falls back to a *different* model: that would make
        results irreproducible.
        """
        try:
            self._client.models.retrieve(model)
            return
        except self._openai.NotFoundError:
            pass  # may be an unimplemented endpoint; confirm against the list
        except self._openai.APIStatusError as exc:
            raise ProviderError(f"could not validate openai model {model!r}: {exc}") from exc

        try:
            available = [m.id for m in self._client.models.list()]
        except self._openai.APIStatusError:
            return  # endpoint unavailable — cannot validate, so do not block
        if model not in available:
            raise CapabilityError(
                f"openai model {model!r} not found. Available: {', '.join(sorted(available))}"
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
        wire: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            wire.extend(self._to_wire(m))

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": wire,
            self._token_param: max_tokens,
        }
        if effort:
            # gpt-5.x and kimi-k3 both honour this — verified by measuring
            # reasoning_tokens at low vs xhigh, not by the call merely not
            # 400-ing. OpenAI-compatible endpoints ignore unknown parameters
            # silently, which is exactly how the Anthropic thinking gap hid.
            kwargs["reasoning_effort"] = effort
        if tools:
            kwargs["tools"] = [self._tool_to_wire(t) for t in tools]
            kwargs["tool_choice"] = "auto"

        try:
            resp = self._client.chat.completions.create(**kwargs)
        except self._openai.APIError as exc:
            raise ProviderError(f"openai request failed: {exc}") from exc

        return self._from_wire(resp)

    # --- translation ---------------------------------------------------------

    @staticmethod
    def _tool_to_wire(schema: ToolSchema) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": schema["input_schema"],
            },
        }

    @staticmethod
    def _to_wire(msg: Message) -> list[dict[str, Any]]:
        role = msg["role"]
        if role == "user":
            return [{"role": "user", "content": msg["content"]}]

        if role == "assistant":
            text = msg.get("content") or ""
            calls = msg.get("tool_calls", [])
            entry: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                entry["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in calls
                ]
            return [entry]

        if role == "tool":
            # OpenAI has no is_error flag on tool messages; mark errors in-band.
            out: list[dict[str, Any]] = []
            for r in msg["content"]:
                content = f"[tool error] {r.content}" if r.is_error else r.content
                out.append({"role": "tool", "tool_call_id": r.call_id, "content": content})
            return out

        raise ProviderError(f"unknown canonical message role {role!r}")

    @staticmethod
    def _from_wire(resp: Any) -> LLMResponse:
        choice = resp.choices[0].message
        tool_calls: list[ToolCall] = []
        for tc in choice.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"__raw_arguments__": tc.function.arguments}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        usage = {
            "input_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(resp.usage, "completion_tokens", 0) or 0,
        }
        return LLMResponse(
            text=choice.content or "",
            tool_calls=tool_calls,
            raw=resp,
            usage=usage,
        )
