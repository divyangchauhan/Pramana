"""Kimi (Moonshot AI) adapter — OpenAI-compatible Chat Completions.

Moonshot's API speaks the OpenAI wire format (function calling included), so
this adapter reuses :class:`OpenAIAdapter`'s translation wholesale and only
changes what is genuinely different: the client points at Moonshot's endpoint
with ``MOONSHOT_API_KEY``, and the output cap is the legacy ``max_tokens``
parameter (Moonshot does not accept OpenAI's ``max_completion_tokens``).
"""

from __future__ import annotations

import os

from .base import CapabilityError, ProviderError
from .openai import OpenAIAdapter

DEFAULT_BASE_URL = "https://api.moonshot.ai/v1"


class KimiAdapter(OpenAIAdapter):
    provider = "kimi"
    _token_param = "max_tokens"

    def __init__(self) -> None:
        import openai  # lazy import (OpenAI SDK, pointed at Moonshot)

        self._openai = openai
        api_key = os.environ.get("MOONSHOT_API_KEY") or os.environ.get("KIMI_API_KEY")
        if not api_key:
            raise ProviderError(
                "set MOONSHOT_API_KEY (or KIMI_API_KEY) to use the kimi provider"
            )
        base_url = os.environ.get("MOONSHOT_BASE_URL", DEFAULT_BASE_URL)
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def check_capabilities(self, model: str) -> None:
        # Moonshot's OpenAI-compatible surface reliably supports listing models;
        # single-model retrieve is not guaranteed, so validate via the list.
        try:
            available = {m.id for m in self._client.models.list().data}
        except self._openai.APIError as exc:
            raise ProviderError(f"could not list kimi models: {exc}") from exc
        if model not in available:
            raise CapabilityError(
                f"kimi model {model!r} not found; available: {sorted(available)}"
            )
