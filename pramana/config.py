"""Provider/model configuration, pinned and recorded with every run.

The design (§1) configures providers and models *by role* rather than
hard-coding them. Phase 0 runs a single combined agent, so only the ``agent``
role is used here; the structure leaves room for the finder/verifier/reporter
split in later phases without a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Per-provider defaults, each verified to exist on that provider's endpoint and
# to complete a full audit. Override per run with `--model`.
#
# `openai` resolves against whatever `OPENAI_BASE_URL` points at, so a gateway
# serving a different catalogue needs an explicit `--model`; the capability
# check lists what that endpoint actually serves.
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-4-8",
    # Same model and wire protocol as `anthropic`, separate identity so a
    # subscription-proxy run is not priced off the first-party table (see
    # providers.anthropic.AnthropicGatewayAdapter). Requires ANTHROPIC_BASE_URL.
    "anthropic-gateway": "claude-opus-4-8",
    "openai": "gpt-5.5",
    # Same wire protocol as `openai`, separate identity so gateway runs are not
    # priced off the first-party table (see providers.openai.OpenAIGatewayAdapter).
    # Requires OPENAI_BASE_URL.
    "openai-gateway": "gpt-5.6-sol",
    "kimi": "kimi-k3",
}

SUPPORTED_PROVIDERS = tuple(DEFAULT_MODELS)

# Reasoning effort, ordered cheapest first. Every lab in the sweep accepts these
# names; each maps them onto its own control (Anthropic `output_config.effort`,
# OpenAI/Moonshot `reasoning_effort`).
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

# Recorded when no effort is sent, so a run always states what it ran at even
# when that was the provider's choice rather than ours. Provider defaults are
# NOT equal across labs — Anthropic defaults to `high`, OpenAI's gpt-5.x to
# `medium` — so an unset effort silently compares models at different depths.
UNSET_EFFORT = "provider-default"


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
    """Everything a pipeline needs to run one audit, reproducibly.

    ``agent`` is the single combined finder+verifier+reporter of the Phase 0
    vertical slice. ``finder`` and ``verifier`` route those roles independently
    in Phase 1; when unset they fall back to ``agent``, so a single ``--model``
    still configures the whole pipeline.

    ``max_turns`` bounds model round-trips (reliability guard); ``max_tokens``
    is the per-turn output cap. ``max_poc_attempts`` bounds *executed forge
    runs* per verification — a different axis from ``max_turns``, and the two
    must not be conflated (design §4).
    """

    agent: ModelProfile
    finder: ModelProfile | None = None
    verifier: ModelProfile | None = None
    max_turns: int = 25
    max_tokens: int = 16000
    max_poc_attempts: int = 4
    # Reasoning depth, applied to every role. One knob rather than per-role,
    # because the sweep varies it as a single independent variable — and
    # because leaving it unset compares models at different depths (see
    # UNSET_EFFORT).
    effort: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.effort is not None and self.effort not in EFFORT_LEVELS:
            raise ValueError(f"unknown effort {self.effort!r}; supported: {EFFORT_LEVELS}")

    @property
    def effort_label(self) -> str:
        return self.effort or UNSET_EFFORT

    def role(self, name: str) -> ModelProfile:
        """Profile for ``name``, falling back to ``agent`` when not routed."""
        profile = getattr(self, name, None)
        if profile is None:
            return self.agent
        return profile

    def label(self, pipeline: str = "phase0") -> str:
        """Run label recorded with results. Includes the pipeline, so Phase 0
        and Phase 1 rows are never mistaken for one another when comparing."""
        # Effort is part of the identity of a run, not a footnote: the same
        # model at two efforts is two different configurations, and a sweep row
        # that omitted it would be uncomparable to its own siblings.
        suffix = f"@{self.effort_label}"
        if pipeline == "phase0":
            return f"phase0/{self.agent.label()}{suffix}"
        finder, verifier = self.role("finder"), self.role("verifier")
        if finder == verifier:
            return f"{pipeline}/{finder.label()}{suffix}"
        return f"{pipeline}/finder={finder.label()},verifier={verifier.label()}{suffix}"

    @classmethod
    def for_provider(
        cls,
        provider: str,
        model: str | None = None,
        *,
        finder_model: str | None = None,
        verifier_model: str | None = None,
        **kwargs: object,
    ) -> AgentConfig:
        resolved = model or DEFAULT_MODELS[provider]
        return cls(
            agent=ModelProfile(provider=provider, model=resolved),
            finder=ModelProfile(provider=provider, model=finder_model) if finder_model else None,
            verifier=(
                ModelProfile(provider=provider, model=verifier_model) if verifier_model else None
            ),
            **kwargs,  # type: ignore[arg-type]
        )
