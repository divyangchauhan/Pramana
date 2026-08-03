"""Contract and redaction tests for JSONL observability traces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pramana.agents.loop import run_agent
from pramana.providers.base import LLMResponse, ToolCall
from pramana.trace import (
    MAX_TRACE_STRING,
    REDACTED,
    TRACE_ENVELOPE_FIELDS,
    TRACE_SCHEMA_VERSION,
    JsonlTrace,
    redact,
)


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_jsonl_schema_envelope_is_stable_and_sequenced(tmp_path: Path) -> None:
    path = tmp_path / "run" / "fixture.jsonl"
    trace = JsonlTrace(path, run_id="run-123", fixture="vault")
    trace({"event": "fixture_start"})
    trace({"event": "assistant_turn", "role": "finder", "model": "model-a", "turn": 0})

    records = _records(path)
    assert len(records) == 2
    assert records[0].keys() >= TRACE_ENVELOPE_FIELDS
    assert records[0]["schema_version"] == TRACE_SCHEMA_VERSION == 1
    assert records[0]["run_id"] == "run-123"
    assert records[0]["fixture"] == "vault"
    assert records[0]["sequence"] == 0
    assert records[0]["role"] is None and records[0]["model"] is None
    assert records[1]["sequence"] == 1
    assert records[1]["role"] == "finder"
    assert records[1]["model"] == "model-a"
    assert records[0]["timestamp"].endswith("+00:00")


def test_trace_requires_named_event(tmp_path: Path) -> None:
    trace = JsonlTrace(tmp_path / "trace.jsonl", run_id="r", fixture="f")
    with pytest.raises(ValueError, match="string 'event'"):
        trace({"turn": 0})


def test_redacts_sensitive_keys_and_secret_shaped_values(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    trace = JsonlTrace(path, run_id="r", fixture="f")
    trace({
        "event": "tool_result",
        "input": {
            "api_key": "plain-value",
            "headers": {"Authorization": "Bearer abc.def.ghi"},
            "path": "src/Vault.sol",
        },
        "output": (
            'OPENAI_API_KEY=sk-proj-supersecret and ghp_123456789abcdef '
            'and {"api_key":"arbitrary-credential"}'
        ),
    })

    raw = path.read_text()
    record = _records(path)[0]
    assert "plain-value" not in raw
    assert "abc.def.ghi" not in raw
    assert "supersecret" not in raw
    assert "123456789abcdef" not in raw
    assert "arbitrary-credential" not in raw
    assert record["input"]["api_key"] == REDACTED
    assert record["input"]["headers"]["Authorization"] == REDACTED
    assert record["input"]["path"] == "src/Vault.sol"
    assert REDACTED in record["output"]


def test_large_tool_output_is_bounded() -> None:
    cleaned = redact("x" * (MAX_TRACE_STRING + 25))
    assert isinstance(cleaned, str)
    assert cleaned.startswith("x" * MAX_TRACE_STRING)
    assert "truncated 25 chars" in cleaned


def test_token_usage_fields_are_not_mistaken_for_credentials() -> None:
    assert redact({"input_tokens": 42, "output_tokens": 7}) == {
        "input_tokens": 42,
        "output_tokens": 7,
    }


def test_agent_events_record_model_tool_io_latency_usage_and_errors() -> None:
    class Adapter:
        provider = "test"
        calls = 0

        def check_capabilities(self, model: str) -> None:
            return None

        def complete(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    text="trying tool",
                    tool_calls=[ToolCall("call-1", "explode", {"path": "src/Vault.sol"})],
                    raw=None,
                    usage={"input_tokens": 12, "output_tokens": 3},
                )
            return LLMResponse(
                text="done", tool_calls=[], raw=None,
                usage={"input_tokens": 5, "output_tokens": 1},
            )

    events = []

    def explode(**_kwargs):
        raise RuntimeError("tool failed")

    run_agent(
        Adapter(), "system", [], {"explode": explode}, "seed", "model-x", trace=events.append
    )

    turns = [event for event in events if event["event"] == "assistant_turn"]
    tool = next(event for event in events if event["event"] == "tool_result")
    assert turns[0]["model"] == "model-x"
    assert turns[0]["turn"] == 0
    assert turns[0]["usage"] == {"input_tokens": 12, "output_tokens": 3}
    assert turns[0]["latency_ms"] >= 0
    assert tool["model"] == "model-x"
    assert tool["input"] == {"path": "src/Vault.sol"}
    assert "tool failed" in tool["output"]
    assert tool["is_error"] is True
    assert tool["latency_ms"] >= 0
