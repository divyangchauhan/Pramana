"""Provider adapters. The core never branches on provider name — it asks the
factory for an adapter and then only speaks the canonical interface."""

from __future__ import annotations

from .base import (
    CapabilityError,
    LLMAdapter,
    LLMResponse,
    Message,
    ProviderError,
    ToolCall,
    ToolResult,
    ToolSchema,
)


def build_adapter(provider: str) -> LLMAdapter:
    """Instantiate the adapter for ``provider``. Import is deferred so a run
    that uses only one lab never needs the other lab's SDK at construction."""
    if provider == "anthropic":
        from .anthropic import AnthropicAdapter

        return AnthropicAdapter()
    if provider == "openai":
        from .openai import OpenAIAdapter

        return OpenAIAdapter()
    if provider == "openai-gateway":
        from .openai import OpenAIGatewayAdapter

        return OpenAIGatewayAdapter()
    if provider == "kimi":
        from .kimi import KimiAdapter

        return KimiAdapter()
    raise ValueError(f"unknown provider {provider!r}")


__all__ = [
    "CapabilityError",
    "LLMAdapter",
    "LLMResponse",
    "Message",
    "ProviderError",
    "ToolCall",
    "ToolResult",
    "ToolSchema",
    "build_adapter",
]
