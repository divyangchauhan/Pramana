"""Offline tests for the canonical <-> provider wire translation.

These exercise only the pure translation (static) methods — no client, no
network, no API key. They lock down the provider-neutrality boundary (design
§1): the same canonical messages must serialize correctly for each lab.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from pramana import config
from pramana.agents.prompts import READ_FILE_SCHEMA
from pramana.providers import build_adapter
from pramana.providers.anthropic import AnthropicAdapter
from pramana.providers.base import ProviderError, ToolCall, ToolResult
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
