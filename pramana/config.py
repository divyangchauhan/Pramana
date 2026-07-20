"""Provider/model configuration, pinned and recorded with every run.

The design (§1) configures providers and models *by role* rather than
hard-coding them. Phase 0 runs a single combined agent, so only the ``agent``
role is used here; the structure leaves room for the finder/verifier/reporter
split in later phases without a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Sensible per-provider defaults. `anthropic` is pinned to the current strong
# reasoning model; the `openai` and `kimi` ids are placeholders you should
# override with a concrete, currently-available model id via `--model` at run
# time (e.g. the exact Moonshot Kimi K3 id for `kimi`).
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-5.1",
    "kimi": "kimi-k3",
}

SUPPORTED_PROVIDERS = tuple(DEFAULT_MODELS)


@dataclass(frozen=True)
class ModelProfile:
    """A pinned (provider, model) pair for one agent role."""

    provider: str
    model: str

    def __post_init__(self) -> None:
        if self.provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"unknown provider {self.provider!r}; supported: {SUPPORTED_PROVIDERS}"
            )

    def label(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class AgentConfig:
    """Everything the Phase 0 pipeline needs to run one audit, reproducibly.

    ``agent`` is the single combined finder+verifier+reporter of the Phase 0
    vertical slice. ``max_turns`` bounds model round-trips (reliability guard);
    ``max_tokens`` is the per-turn output cap.
    """

    agent: ModelProfile
    max_turns: int = 25
    max_tokens: int = 16000
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def for_provider(cls, provider: str, model: str | None = None, **kwargs: object) -> AgentConfig:
        resolved = model or DEFAULT_MODELS[provider]
        return cls(agent=ModelProfile(provider=provider, model=resolved), **kwargs)  # type: ignore[arg-type]
