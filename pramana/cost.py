"""Token, latency and money accounting (design §9).

The sweep's whole purpose is judging a configuration on *quality and cost
together* — design §8: "treat a config that cuts cost while cutting recall as a
regression." That judgement needs a number, so usage is accumulated per role
and carried out to the run record.

Money is deliberately the *derived* quantity. Tokens and seconds are facts we
measure; dollars are those facts multiplied by a price list that goes stale
without warning. So the table below is versioned and dated, and an unknown
model yields ``None`` rather than a plausible-looking guess — a wrong cost
number is worse than a missing one, because it silently decides which
configuration "won".
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "PRICE_TABLE_SOURCES",
    "PRICE_TABLE_VERSION",
    "PRICES",
    "Price",
    "Usage",
    "estimate_usd",
    "model_key",
]


@dataclass(frozen=True)
class Usage:
    """Accumulated cost of one or more model calls.

    ``elapsed_s`` is model latency only — the time inside ``llm.complete``.
    Tool execution (forge, slither) is excluded on purpose: this number exists
    to compare *models*, and forge takes the same time whoever called it.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    elapsed_s: float = 0.0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            calls=self.calls + other.calls,
            elapsed_s=self.elapsed_s + other.elapsed_s,
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, float | int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "calls": self.calls,
            "elapsed_s": round(self.elapsed_s, 3),
        }

    @classmethod
    def from_dict(cls, data: dict[str, float | int]) -> Usage:
        return cls(
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            calls=int(data.get("calls", 0)),
            elapsed_s=float(data.get("elapsed_s", 0.0)),
        )


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input_per_mtok: float
    output_per_mtok: float


# Bump the version whenever a price changes, so a recorded run states which
# table produced its dollar figure. Never edit a price in place without it.
PRICE_TABLE_VERSION = "2026-07-22"

PRICE_TABLE_SOURCES = {
    "anthropic": "https://platform.claude.com/docs/en/docs/about-claude/pricing",
    "openai": "https://developers.openai.com/api/docs/models/gpt-5.6",
    "kimi": "https://api.moonshot.ai/",
}

# Standard first-party API rates: no batch discount, no fast mode, global
# routing. Keyed "provider:model" — the same model billed differently through
# a gateway is a different key, not a silent reuse of this one.
PRICES: dict[str, Price] = {
    "anthropic:claude-opus-4-8": Price(5.0, 25.0),
    # 2x Opus on both axes — the most expensive slot in the sweep.
    "anthropic:claude-fable-5": Price(10.0, 50.0),
    "openai:gpt-5.5": Price(5.0, 30.0),
    "openai:gpt-5.6-sol": Price(5.0, 30.0),
    "kimi:kimi-k3": Price(3.0, 15.0),
}


# Gateway provider -> the first-party provider whose list price its models are
# served under. Used only to compute a *notional* cost; never to fill in `usd`.
NOTIONAL_EQUIVALENT: dict[str, str] = {
    "openai-gateway": "openai",
    "anthropic-gateway": "anthropic",
}


def model_key(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def notional_key(key: str) -> str | None:
    """The first-party key whose list price corresponds to ``key``, if any."""
    provider, _, model = key.partition(":")
    equivalent = NOTIONAL_EQUIVALENT.get(provider)
    return f"{equivalent}:{model}" if equivalent else None


def estimate_usd_notional(key: str, usage: Usage) -> float | None:
    """What ``usage`` *would* have cost at first-party list price.

    For gateway runs only, and deliberately a separate field from ``usd``.
    A subscription-replaying proxy bills a flat fee, so no money moved at these
    rates — but the token counts are real, and pricing them makes a gateway row
    comparable to a first-party one on efficiency.

    Read it as "what this configuration would cost to run properly", never as
    spend. ``usd`` stays ``None`` for these rows precisely so the two can never
    be added together by accident.
    """
    equivalent = notional_key(key)
    return estimate_usd(equivalent, usage) if equivalent else None


def estimate_usd(key: str, usage: Usage) -> float | None:
    """Cost of ``usage`` under the pinned price table, or ``None`` if unpriced.

    Assumes no prompt caching. The pipeline never sets ``cache_control``, so
    every input token is billed at the base rate; were caching enabled, cache
    reads bill at a fraction and this would overstate.
    """
    price = PRICES.get(key)
    if price is None:
        return None
    return (
        usage.input_tokens / 1_000_000 * price.input_per_mtok
        + usage.output_tokens / 1_000_000 * price.output_per_mtok
    )


def total_usd(by_role: dict[str, tuple[str, Usage]]) -> float | None:
    """Sum costs across roles. ``None`` if *any* role is unpriced — a partial
    total reads as a complete one and would understate the configuration."""
    costs = [estimate_usd(key, usage) for key, usage in by_role.values()]
    if any(c is None for c in costs):
        return None
    return sum(c for c in costs if c is not None)
