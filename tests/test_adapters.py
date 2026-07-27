"""Offline tests for the canonical <-> provider wire translation.

These exercise only the pure translation (static) methods — no client, no
network, no API key. They lock down the provider-neutrality boundary (design
§1): the same canonical messages must serialize correctly for each lab.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from pramana import config
from pramana.agents.prompts import READ_FILE_SCHEMA
from pramana.providers import CapabilityError, build_adapter
from pramana.providers.anthropic import AnthropicAdapter
from pramana.providers.base import (
    ProviderError,
    ProviderRefusalError,
    ToolCall,
    ToolResult,
)
from pramana.providers.kimi import KimiAdapter
from pramana.providers.openai import OpenAIAdapter

ASSISTANT_MSG = {
    "role": "assistant",
    "content": "let me look",
    "tool_calls": [ToolCall(id="c1", name="read_file", arguments={"path": "src/A.sol"})],
}
TOOL_MSG = {
    "role": "tool",
    "content": [ToolResult(call_id="c1", content="contract A {}", is_error=False)],
}
ERROR_TOOL_MSG = {
    "role": "tool",
    "content": [ToolResult(call_id="c2", content="boom", is_error=True)],
}


def test_anthropic_assistant_and_tool_wire():
    a = AnthropicAdapter._to_wire(ASSISTANT_MSG)
    assert a["role"] == "assistant"
    types = [b["type"] for b in a["content"]]
    assert types == ["text", "tool_use"]
    assert a["content"][1] == {
        "type": "tool_use",
        "id": "c1",
        "name": "read_file",
        "input": {"path": "src/A.sol"},
    }

    t = AnthropicAdapter._to_wire(TOOL_MSG)
    assert t["role"] == "user"
    block = t["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "c1"
    assert block["is_error"] is False


def test_anthropic_drops_empty_text_block():
    msg = {"role": "assistant", "content": "  ", "tool_calls": ASSISTANT_MSG["tool_calls"]}
    wire = AnthropicAdapter._to_wire(msg)
    assert [b["type"] for b in wire["content"]] == ["tool_use"]


def test_openai_assistant_and_tool_wire():
    entries = OpenAIAdapter._to_wire(ASSISTANT_MSG)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["role"] == "assistant"
    assert entry["content"] == "let me look"
    tc = entry["tool_calls"][0]
    assert tc["id"] == "c1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "read_file"
    # OpenAI wants arguments as a JSON string.
    assert tc["function"]["arguments"] == '{"path": "src/A.sol"}'

    tool_entries = OpenAIAdapter._to_wire(TOOL_MSG)
    assert tool_entries[0] == {"role": "tool", "tool_call_id": "c1", "content": "contract A {}"}


def test_openai_marks_error_tool_result_inband():
    entry = OpenAIAdapter._to_wire(ERROR_TOOL_MSG)[0]
    assert entry["content"].startswith("[tool error]")


def test_openai_tool_schema_shape():
    wire = OpenAIAdapter._tool_to_wire(READ_FILE_SCHEMA)
    assert wire["type"] == "function"
    assert wire["function"]["name"] == "read_file"
    assert wire["function"]["parameters"] == READ_FILE_SCHEMA["input_schema"]


# --- Kimi (Moonshot AI): OpenAI-compatible, reuses the OpenAI translation -----


def test_kimi_reuses_openai_translation():
    assert KimiAdapter.provider == "kimi"
    # Inherited, not reimplemented — same wire translation as OpenAI.
    assert KimiAdapter._to_wire is OpenAIAdapter._to_wire
    assert KimiAdapter._tool_to_wire is OpenAIAdapter._tool_to_wire
    assert KimiAdapter._from_wire is OpenAIAdapter._from_wire


def test_kimi_uses_legacy_max_tokens_param():
    # Moonshot accepts `max_tokens`, not OpenAI's `max_completion_tokens`.
    assert KimiAdapter._token_param == "max_tokens"
    assert OpenAIAdapter._token_param == "max_completion_tokens"


def test_kimi_is_a_registered_provider():
    assert "kimi" in config.SUPPORTED_PROVIDERS
    assert "kimi" in config.DEFAULT_MODELS


def test_build_adapter_knows_kimi_but_needs_a_key(monkeypatch):
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    # Registered (not "unknown provider"), but missing credentials -> clear error.
    with pytest.raises(ProviderError, match="MOONSHOT_API_KEY"):
        build_adapter("kimi")


def test_build_adapter_rejects_unknown_provider():
    with pytest.raises(ValueError, match="unknown provider"):
        build_adapter("not-a-lab")


# --- Anthropic capability check tolerates a partial proxy --------------------
#
# CLIProxyAPI serves the message surface and `GET /v1/models` but 404s on
# `GET /v1/models/{id}` — even for models it does serve. The adapter must not
# turn that 404 into "no such model" and abort a paid run before it starts.


def _fake_anthropic_ns() -> SimpleNamespace:
    class APIError(Exception):
        pass

    class NotFoundError(APIError):
        pass

    class APIStatusError(APIError):
        pass

    return SimpleNamespace(
        APIError=APIError, NotFoundError=NotFoundError, APIStatusError=APIStatusError
    )


def _adapter_with_client(ns: SimpleNamespace, *, retrieve_exc=None, list_ids=None, list_exc=None):
    class _Models:
        def retrieve(self, model: str):
            if retrieve_exc is not None:
                raise retrieve_exc
            return SimpleNamespace(id=model)

        def list(self):
            if list_exc is not None:
                raise list_exc
            return [SimpleNamespace(id=i) for i in (list_ids or [])]

    adapter = AnthropicAdapter.__new__(AnthropicAdapter)  # skip real client construction
    adapter._anthropic = ns  # type: ignore[attr-defined]
    adapter._client = SimpleNamespace(models=_Models())  # type: ignore[attr-defined]
    return adapter


def test_capability_check_passes_when_retrieve_works():
    ns = _fake_anthropic_ns()
    _adapter_with_client(ns).check_capabilities("claude-opus-4-8")  # no raise


def test_capability_check_falls_back_to_list_when_retrieve_is_unimplemented():
    """The proxy case: retrieve 404s, but the model is in the list -> accept."""
    ns = _fake_anthropic_ns()
    adapter = _adapter_with_client(
        ns, retrieve_exc=ns.NotFoundError(), list_ids=["claude-opus-4-8", "gpt-5.6-terra"]
    )
    adapter.check_capabilities("claude-opus-4-8")  # no raise


def test_capability_check_rejects_a_model_absent_from_the_list():
    ns = _fake_anthropic_ns()
    adapter = _adapter_with_client(
        ns, retrieve_exc=ns.NotFoundError(), list_ids=["claude-opus-4-8"]
    )
    with pytest.raises(CapabilityError, match="claude-opus-9"):
        adapter.check_capabilities("claude-opus-9")


def test_capability_check_leaves_unvalidated_when_the_list_is_also_unavailable():
    """Neither endpoint usable -> do not block; the first request surfaces the
    truth. Refusing to start would make the adapter unusable against a proxy."""
    ns = _fake_anthropic_ns()
    adapter = _adapter_with_client(
        ns, retrieve_exc=ns.NotFoundError(), list_exc=ns.APIError("list unimplemented")
    )
    adapter.check_capabilities("claude-opus-4-8")  # no raise


def test_capability_check_surfaces_a_non_404_retrieve_error():
    """A 401/permission error is not "unimplemented" — it must not be swallowed
    by the list fallback."""
    ns = _fake_anthropic_ns()
    adapter = _adapter_with_client(ns, retrieve_exc=ns.APIStatusError("forbidden"))
    with pytest.raises(ProviderError, match="could not validate"):
        adapter.check_capabilities("claude-opus-4-8")


# --- anthropic-gateway: same model, honest cost ------------------------------


def test_anthropic_gateway_is_a_registered_provider():
    assert "anthropic-gateway" in config.SUPPORTED_PROVIDERS
    assert config.DEFAULT_MODELS["anthropic-gateway"] == config.DEFAULT_MODELS["anthropic"]


def test_anthropic_gateway_refuses_to_run_without_a_base_url(monkeypatch):
    """Without ANTHROPIC_BASE_URL the SDK reaches first-party Anthropic while the
    run labels itself a gateway — wrong provenance and wrong (absent) pricing."""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with pytest.raises(ProviderError, match="ANTHROPIC_BASE_URL"):
        build_adapter("anthropic-gateway")


def test_anthropic_gateway_reports_its_own_identity_and_longer_retries(monkeypatch):
    from pramana.providers.anthropic import AnthropicGatewayAdapter

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8317")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    adapter = build_adapter("anthropic-gateway")
    assert adapter.provider == "anthropic-gateway"
    # Same wire translation as first-party — only identity and billing differ.
    assert adapter._to_wire is AnthropicAdapter._to_wire  # type: ignore[attr-defined]
    # The burst-tolerant policy, not the first-party default.
    assert adapter.retry_policy is AnthropicGatewayAdapter.RETRY_POLICY  # type: ignore[attr-defined]
    assert adapter.retry_policy.attempts > 4  # type: ignore[union-attr]


# --- OpenAI-compatible gateways ----------------------------------------------
#
# Pointing OPENAI_BASE_URL at a gateway (OpenRouter, LiteLLM, vLLM, a local
# proxy) is the supported way to reach non-OpenAI models through this adapter.
# Such gateways commonly implement `models.list` but not per-model `retrieve`,
# where a 404 means "unimplemented" rather than "no such model".


class _FakeNotFound(Exception):
    pass


class _FakeStatusError(Exception):
    pass


class _FakeModel:
    def __init__(self, mid: str) -> None:
        self.id = mid


class _FakeModels:
    def __init__(self, *, retrieve_404: bool, listed: list[str] | None, list_500: bool = False):
        self._retrieve_404 = retrieve_404
        self._listed = listed or []
        self._list_500 = list_500
        self.retrieve_calls = 0

    def retrieve(self, model: str):
        self.retrieve_calls += 1
        if self._retrieve_404:
            raise _FakeNotFound("404")
        return _FakeModel(model)

    def list(self):
        if self._list_500:
            raise _FakeStatusError("500")
        return [_FakeModel(m) for m in self._listed]


def _adapter_with(models: _FakeModels) -> OpenAIAdapter:
    adapter = OpenAIAdapter.__new__(OpenAIAdapter)  # bypass client construction
    stub = cast(Any, adapter)  # the injected client/SDK are deliberately fakes
    stub._openai = type(
        "sdk", (), {"NotFoundError": _FakeNotFound, "APIStatusError": _FakeStatusError}
    )
    stub._client = type("client", (), {"models": models})()
    return adapter


def test_capability_check_accepts_a_model_the_gateway_only_lists():
    """The proxy case: retrieve 404s, but the model is really there."""
    models = _FakeModels(retrieve_404=True, listed=["gpt-5.5", "gpt-5.4"])
    _adapter_with(models).check_capabilities("gpt-5.5")  # must not raise


def test_capability_check_still_rejects_a_model_absent_from_the_list():
    from pramana.providers.base import CapabilityError

    models = _FakeModels(retrieve_404=True, listed=["gpt-5.5"])
    with pytest.raises(CapabilityError, match="gpt-5.5"):  # error names what IS available
        _adapter_with(models).check_capabilities("typo-model")


def test_capability_check_short_circuits_when_retrieve_works():
    models = _FakeModels(retrieve_404=False, listed=[])
    _adapter_with(models).check_capabilities("gpt-5.5")
    assert models.retrieve_calls == 1


def test_capability_check_does_not_block_when_neither_endpoint_is_available():
    """An endpoint that implements neither cannot be validated. Refusing to
    start would make the adapter unusable against otherwise working servers;
    the first real request surfaces the truth instead."""
    models = _FakeModels(retrieve_404=True, listed=None, list_500=True)
    _adapter_with(models).check_capabilities("whatever")  # must not raise


# --- Refusals: a model declining is named a refusal, not a parse error --------
#
# A safety refusal comes back as a SUCCESSFUL call with empty content
# (Anthropic stop_reason "refusal"; OpenAI finish_reason "content_filter" or a
# structured `refusal` message). Unhandled, that empty content falls through to
# the finder's JSON parser and surfaces as a misleading OutputParseError —
# blaming the pipeline for the model's own decline. Both adapters must name it,
# so a cross-model sweep can tell "this model refused the task" apart from a
# real bug (claude-fable-5 refuses the finder task; Opus runs it cleanly).


class _FakeAPIError(Exception):
    pass


def _complete_kwargs() -> dict[str, Any]:
    return dict(
        model="test-model",
        system="s",
        tools=[],
        messages=[{"role": "user", "content": "audit this"}],
        max_tokens=128,
        effort="medium",
    )


def _anthropic_adapter_returning(message: SimpleNamespace) -> AnthropicAdapter:
    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return message

    class _Messages:
        def stream(self, **kwargs):
            return _Stream()

    adapter = AnthropicAdapter.__new__(AnthropicAdapter)  # bypass client construction
    stub = cast(Any, adapter)
    stub._anthropic = SimpleNamespace(APIError=_FakeAPIError)
    stub._client = SimpleNamespace(messages=_Messages())
    return adapter


def test_anthropic_complete_raises_on_refusal():
    msg = SimpleNamespace(
        stop_reason="refusal",
        content=[],
        usage=SimpleNamespace(input_tokens=1753, output_tokens=9),
    )
    with pytest.raises(ProviderRefusalError, match="refused"):
        _anthropic_adapter_returning(msg).complete(**_complete_kwargs())


def test_anthropic_complete_returns_normally_when_not_refused():
    msg = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="[]")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=2),
    )
    assert _anthropic_adapter_returning(msg).complete(**_complete_kwargs()).text == "[]"


def _openai_adapter_returning(resp: SimpleNamespace) -> OpenAIAdapter:
    class _Completions:
        def create(self, **kwargs):
            return resp

    adapter = OpenAIAdapter.__new__(OpenAIAdapter)  # bypass client construction
    stub = cast(Any, adapter)
    stub._openai = SimpleNamespace(APIError=_FakeAPIError)
    stub._client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    return adapter


def _openai_resp(
    *, finish_reason: str, refusal: str | None = None, content: str = ""
) -> SimpleNamespace:
    message = SimpleNamespace(content=content, refusal=refusal, tool_calls=[])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=0),
    )


def test_openai_complete_raises_on_content_filter():
    resp = _openai_resp(finish_reason="content_filter")
    with pytest.raises(ProviderRefusalError, match="refused"):
        _openai_adapter_returning(resp).complete(**_complete_kwargs())


def test_openai_complete_raises_on_structured_refusal():
    resp = _openai_resp(finish_reason="stop", refusal="I can't help with that.")
    with pytest.raises(ProviderRefusalError, match="can't help"):
        _openai_adapter_returning(resp).complete(**_complete_kwargs())


def test_openai_complete_returns_normally_when_not_refused():
    resp = _openai_resp(finish_reason="stop", content="[]")
    assert _openai_adapter_returning(resp).complete(**_complete_kwargs()).text == "[]"
