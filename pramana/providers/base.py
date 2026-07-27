"""Provider-neutral adapter boundary (design §1).

The agent loop never imports a lab SDK. It speaks in the canonical types below;
each adapter translates them to and from its provider's wire format.

Canonical message shape (a plain ``list[dict]`` the loop owns):

    {"role": "user",      "content": "<seed text>"}
    {"role": "assistant", "content": "<text>", "tool_calls": [ToolCall, ...]}
    {"role": "tool",      "content": [ToolResult, ...]}

A tool *schema* (what the model sees) is a dict in Anthropic's shape —
``{"name", "description", "input_schema"}`` — and adapters reshape it per
provider. Keeping one canonical schema shape means tool definitions are written
once (agents/prompts.py) and reused across labs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# A JSON-schema tool definition in Anthropic's shape.
ToolSchema = dict[str, Any]
# One canonical message (see module docstring).
Message = dict[str, Any]


@dataclass
class ToolCall:
    """A model's request to invoke one tool."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Canonical tool result. The loop produces these; each adapter serializes
    them into its provider's wire format (Anthropic ``tool_result`` block,
    OpenAI ``tool`` message, …). No provider-specific shape lives in the core."""

    call_id: str
    content: str
    is_error: bool


@dataclass
class LLMResponse:
    """Normalized model turn."""

    text: str
    tool_calls: list[ToolCall]
    raw: Any
    usage: dict[str, int]


class ProviderError(RuntimeError):
    """Raised for provider-side failures the loop should surface, not swallow."""


class CapabilityError(ProviderError):
    """Raised at startup when a selected model lacks a required capability."""


class ProviderRefusalError(ProviderError):
    """The model declined the request at its own safety layer.

    Distinct from a transport failure or a malformed response: the call
    succeeded and the model chose not to answer (Anthropic ``stop_reason:
    "refusal"``; OpenAI ``finish_reason: "content_filter"`` or a ``refusal``
    message). Without this, a refusal returns empty content and surfaces
    downstream as a confusing ``OutputParseError`` — recording a model's own
    decline as if the pipeline had a parsing bug. Some models refuse the
    vulnerability-finder task outright while others run it cleanly, so a
    cross-model sweep must be able to name a refusal as what it is."""


@runtime_checkable
class LLMAdapter(Protocol):
    """The only surface the agent loop depends on."""

    provider: str

    def check_capabilities(self, model: str) -> None:
        """Fail fast (raise :class:`CapabilityError`) if ``model`` cannot do
        what the pipeline requires — notably tool calling. Never silently fall
        back to another provider/model: that makes results irreproducible."""
        ...

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
        """Run one turn and return a normalized response.

        ``effort`` is the canonical reasoning-depth name (see
        ``config.EFFORT_LEVELS``); each adapter maps it onto its provider's own
        control. ``None`` means "send nothing", which is *not* a neutral choice
        — provider defaults differ across labs, so an unset effort compares
        models at different depths.
        """
        ...
