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
    extra: dict[str, str] = field(default_factory=dict)

    def role(self, name: str) -> ModelProfile:
        """Profile for ``name``, falling back to ``agent`` when not routed."""
        profile = getattr(self, name, None)
        if profile is None:
            return self.agent
        return profile

    def label(self, pipeline: str = "phase0") -> str:
        """Run label recorded with results. Includes the pipeline, so Phase 0
        and Phase 1 rows are never mistaken for one another when comparing."""
        if pipeline == "phase0":
            return f"phase0/{self.agent.label()}"
        finder, verifier = self.role("finder"), self.role("verifier")
        if finder == verifier:
            return f"{pipeline}/{finder.label()}"
        return f"{pipeline}/finder={finder.label()},verifier={verifier.label()}"

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
