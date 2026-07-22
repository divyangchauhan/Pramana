"""Tests for token/latency/money accounting (design §9).

The sweep decides which configuration wins partly on cost, so the failure that
matters here is not a crash — it is a *plausible wrong number*. These pin the
places where a cost could be silently understated: an unpriced model quietly
contributing zero, usage lost when an agent hits its turn ceiling, or a role
total that drops a fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from pramana.agents.loop import AgentRun, AgentTurnLimitError, run_agent, spent_on
from pramana.cost import PRICES, Usage, estimate_usd, model_key, total_usd
from pramana.eval.harness import FixtureRow, _cost_summary, _usage_rows
from pramana.providers.base import LLMResponse, ToolCall

# --- Usage arithmetic --------------------------------------------------------


def test_usage_adds_componentwise():
    a = Usage(input_tokens=10, output_tokens=2, calls=1, elapsed_s=0.5)
    b = Usage(input_tokens=5, output_tokens=3, calls=1, elapsed_s=0.25)
    assert a + b == Usage(input_tokens=15, output_tokens=5, calls=2, elapsed_s=0.75)


def test_usage_roundtrips_through_dict():
    u = Usage(input_tokens=7, output_tokens=11, calls=3, elapsed_s=1.5)
    assert Usage.from_dict(u.as_dict()) == u


# --- pricing -----------------------------------------------------------------


def test_priced_model_costs_input_and_output_at_its_own_rate():
    # anthropic:claude-opus-4-8 is $5/MTok in, $25/MTok out.
    usd = estimate_usd("anthropic:claude-opus-4-8", Usage(input_tokens=1_000_000, output_tokens=0))
    assert usd == pytest.approx(5.0)
    usd = estimate_usd("anthropic:claude-opus-4-8", Usage(input_tokens=0, output_tokens=1_000_000))
    assert usd == pytest.approx(25.0)


def test_output_is_priced_higher_than_input_for_every_model():
    """Not a style rule — it is why the reporter is the cheap slot. If this ever
    inverts, the cost model behind the routing argument has changed."""
    for key, price in PRICES.items():
        assert price.output_per_mtok > price.input_per_mtok, key


def test_unknown_model_is_unpriced_rather_than_free():
    """The dangerous failure mode: a model absent from the table costing $0 and
    therefore winning every cost comparison."""
    assert estimate_usd("someone:unreleased-model", Usage(input_tokens=10_000_000)) is None


def test_total_is_unpriced_if_any_role_is_unpriced():
    priced = ("anthropic:claude-opus-4-8", Usage(input_tokens=1_000_000))
    unpriced = ("someone:unreleased-model", Usage(input_tokens=1_000_000))
    assert total_usd({"finder": priced}) == pytest.approx(5.0)
    assert total_usd({"finder": priced, "verifier": unpriced}) is None


def test_model_key_is_provider_qualified():
    """The same model id behind a gateway bills differently; the key must not
    collapse them onto one price."""
    assert model_key("openai", "gpt-5.5") == "openai:gpt-5.5"
    assert model_key("kimi", "gpt-5.5") != model_key("openai", "gpt-5.5")


# --- the agent loop accumulates ----------------------------------------------


@dataclass
class _Adapter:
    """Emits `turns` tool-calling replies, then a final one."""

    turns: int
    provider: str = "anthropic"
    calls: int = field(default=0)

    def check_capabilities(self, model: str) -> None:
        return None

    def complete(
        self, *, model, system, tools, messages, max_tokens, effort=None
    ) -> LLMResponse:
        self.calls += 1
        usage = {"input_tokens": 100, "output_tokens": 10}
        if self.calls <= self.turns:
            return LLMResponse(
                text="",
                tool_calls=[ToolCall(id=f"c{self.calls}", name="noop", arguments={})],
                raw=None,
                usage=usage,
            )
        return LLMResponse(text="done", tool_calls=[], raw=None, usage=usage)


def _run(adapter, **kw) -> AgentRun:
    return run_agent(
        adapter, "sys", [], {"noop": lambda **_: "ok"}, seed="go", model="m", **kw
    )


def test_run_agent_sums_usage_over_every_turn():
    run = _run(_Adapter(turns=2))
    assert run.text == "done"
    assert run.usage.calls == 3  # two tool turns + the final one
    assert run.usage.input_tokens == 300
    assert run.usage.output_tokens == 30


def test_run_agent_records_latency():
    run = _run(_Adapter(turns=0))
    assert run.usage.elapsed_s >= 0.0
    assert run.usage.calls == 1


def test_turn_limit_error_carries_what_was_already_spent():
    """A run that exhausts max_turns is the most expensive kind. Dropping its
    usage would make the config that causes it look cheapest."""
    with pytest.raises(AgentTurnLimitError) as excinfo:
        _run(_Adapter(turns=99), max_turns=3)
    assert excinfo.value.usage.calls == 3
    assert excinfo.value.usage.input_tokens == 300


def test_provider_failure_carries_what_earlier_turns_already_cost():
    """The failure mode this exists for: credits run out mid-sweep, the fixture
    errors, and every token it burned first vanishes from the run's cost."""

    @dataclass
    class _DiesOnThirdCall:
        provider: str = "anthropic"
        calls: int = 0

        def check_capabilities(self, model: str) -> None:
            return None

        def complete(self, **_) -> LLMResponse:
            self.calls += 1
            if self.calls == 3:
                raise RuntimeError("credit balance too low")
            return LLMResponse(
                text="",
                tool_calls=[ToolCall(id="c", name="noop", arguments={})],
                raw=None,
                usage={"input_tokens": 100, "output_tokens": 10},
            )

    with pytest.raises(RuntimeError) as excinfo:
        _run(_DiesOnThirdCall())
    # The two turns that completed were billed; the one that raised was not.
    spent = spent_on(excinfo.value)
    assert (spent.input_tokens, spent.output_tokens, spent.calls) == (200, 20, 2)


def test_spent_on_is_zero_for_an_exception_from_elsewhere():
    assert spent_on(ValueError("unrelated")) == Usage()


def test_adapter_omitting_usage_does_not_crash_the_loop():
    """Usage is telemetry; a provider that reports none must not fail the audit."""

    @dataclass
    class _Silent:
        provider: str = "anthropic"

        def check_capabilities(self, model: str) -> None:
            return None

        def complete(self, **_) -> LLMResponse:
            return LLMResponse(text="done", tool_calls=[], raw=None, usage={})

    run = _run(_Silent())
    assert run.usage.calls == 1
    assert run.usage.input_tokens == 0


# --- rollup to the run record ------------------------------------------------


def _row(name: str, usage: dict) -> FixtureRow:
    return FixtureRow(
        fixture=name,
        config="c",
        n_candidates=0,
        n_confirmed=0,
        confirmed_poc_pass=0,
        true_positive_findings=0,
        n_known_bugs=0,
        finder_precision=None,
        verifier_precision=None,
        recall=None,
        usage=usage,
    )


def test_cost_summary_sums_each_role_across_fixtures():
    per_fixture = _usage_rows(
        {"finder": ("anthropic:claude-opus-4-8", Usage(input_tokens=1_000_000, calls=1))}
    )
    summary = _cost_summary([_row("a", per_fixture), _row("b", per_fixture)])
    finder = summary["by_role"]["finder"]
    assert finder["input_tokens"] == 2_000_000
    assert finder["calls"] == 2
    assert finder["usd"] == pytest.approx(10.0)
    assert summary["usd_total"] == pytest.approx(10.0)


def test_one_unpriced_role_makes_the_run_total_unpriced():
    rows = [
        _row("a", _usage_rows({"finder": ("anthropic:claude-opus-4-8", Usage(input_tokens=10))})),
        _row("b", _usage_rows({"verifier": ("nobody:mystery", Usage(input_tokens=10))})),
    ]
    summary = _cost_summary(rows)
    assert summary["by_role"]["verifier"]["usd"] is None
    assert summary["usd_total"] is None


def test_cost_summary_stamps_the_price_table_version():
    """A recorded dollar figure is meaningless without the table that produced it."""
    summary = _cost_summary([_row("a", _usage_rows({}))])
    assert summary["price_table_version"]


# --- gateway rows must not borrow first-party prices -------------------------


def test_gateway_key_is_unpriced_even_though_the_model_id_is_priced():
    """A proxy replaying a subscription charges a flat fee, not per token. If
    a gateway row borrowed the first-party price it would report dollars that
    were never charged — worse than reporting nothing."""
    assert estimate_usd("openai:gpt-5.6-sol", Usage(input_tokens=1_000_000)) == pytest.approx(5.0)
    assert estimate_usd("openai-gateway:gpt-5.6-sol", Usage(input_tokens=1_000_000)) is None


def test_no_gateway_entry_may_be_added_to_the_price_table():
    """A guard against a well-meaning future edit: per-token pricing for a
    gateway is not knowable from the model id alone."""
    assert not [k for k in PRICES if k.startswith("openai-gateway:")]


def test_gateway_row_reports_a_notional_cost_beside_a_null_actual():
    """Token counts are real even when the billing is a flat subscription, so
    the run is comparable on efficiency — but the two numbers must never merge."""
    rows = _usage_rows({"finder": ("openai-gateway:gpt-5.6-sol", Usage(input_tokens=1_000_000))})
    assert rows["finder"]["usd"] is None, "notional money must not fill in actual spend"
    assert rows["finder"]["usd_notional"] == pytest.approx(5.0)


def test_first_party_row_has_no_notional_figure():
    """Notional exists only where actual is unknowable; carrying both on a
    priced row invites summing them."""
    rows = _usage_rows({"finder": ("anthropic:claude-opus-4-8", Usage(input_tokens=1_000_000))})
    assert rows["finder"]["usd"] == pytest.approx(5.0)
    assert rows["finder"]["usd_notional"] is None


def test_notional_total_is_separate_from_usd_total():
    rows = [_row("a", _usage_rows(
        {"finder": ("openai-gateway:gpt-5.5", Usage(input_tokens=2_000_000))}
    ))]
    summary = _cost_summary(rows)
    assert summary["usd_total"] is None
    assert summary["usd_notional_total"] == pytest.approx(10.0)


def test_notional_uses_the_first_party_price_of_the_same_model():
    """Not a flat guess: gpt-5.5 and kimi are priced differently, and the
    notional figure must track whichever model actually ran."""
    from pramana.cost import notional_key

    assert notional_key("openai-gateway:gpt-5.5") == "openai:gpt-5.5"
    assert notional_key("anthropic:claude-opus-4-8") is None
