"""Tests for provider-level retry.

A sweep run is all-or-nothing — ``aggregate()`` refuses any run containing an
errored fixture — so one transient 503 discards a whole ten-fixture run and its
money. These pin the two ways retry goes wrong: not retrying something it
should (the run dies), and retrying something it shouldn't (a wrong API key
takes four attempts and a minute to report itself as a generic failure).
"""

from __future__ import annotations

import pytest

from pramana.providers.retry import RetryPolicy, call_with_retries, is_retryable


class _Status(Exception):
    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message or f"status {status_code}")
        self.status_code = status_code


class APIConnectionError(Exception):
    """Name-matched to the SDK class the retry helper recognises."""


# --- what counts as transient ------------------------------------------------


@pytest.mark.parametrize("status", [408, 409, 425, 429, 500, 502, 503, 504])
def test_transient_statuses_are_retryable(status):
    assert is_retryable(_Status(status))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_are_not_retryable(status):
    """A wrong key or a nonexistent model fails identically forever. Retrying
    burns a minute and buries the real cause under a generic failure."""
    assert not is_retryable(_Status(status))


def test_connection_errors_are_retryable():
    assert is_retryable(APIConnectionError("connection reset"))


def test_gateway_auth_refresh_window_is_retryable_despite_its_status():
    """The proxy reports its OAuth refresh window as a 500-class internal
    error. This is the exact failure that made gateway rows uncompletable."""
    exc = _Status(500, "auth_unavailable: no auth available (providers=codex)")
    assert is_retryable(exc)


def test_an_ordinary_500_is_retryable_but_a_400_with_the_same_text_is_not():
    """Message matching must not override an explicit client error."""
    assert is_retryable(_Status(500, "overloaded"))
    assert not is_retryable(_Status(400, "overloaded"))


# --- the retry loop ----------------------------------------------------------


def _policy() -> RetryPolicy:
    return RetryPolicy(attempts=4, base_delay=0.0, max_delay=0.0)


def test_succeeds_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Status(503, "auth_unavailable")
        return "ok"

    assert call_with_retries(flaky, policy=_policy()) == "ok"
    assert calls["n"] == 3


def test_gives_up_after_the_attempt_budget():
    calls = {"n": 0}

    def always_503():
        calls["n"] += 1
        raise _Status(503)

    with pytest.raises(_Status):
        call_with_retries(always_503, policy=_policy())
    assert calls["n"] == 4, "must not retry beyond the budget"


def test_a_permanent_error_is_raised_on_the_first_attempt():
    calls = {"n": 0}

    def unauthorized():
        calls["n"] += 1
        raise _Status(401)

    with pytest.raises(_Status):
        call_with_retries(unauthorized, policy=_policy())
    assert calls["n"] == 1


def test_the_original_exception_survives_retrying():
    """The caller must still see the real error; a run that exhausted its
    retries is not a 'retry failure', it is whatever actually broke."""

    def always():
        raise _Status(503, "auth_unavailable: no auth available")

    with pytest.raises(_Status, match="auth_unavailable"):
        call_with_retries(always, policy=_policy())


def test_retries_are_reported_so_a_degrading_endpoint_is_visible():
    seen: list[tuple[int, BaseException]] = []
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Status(503)
        return "ok"

    call_with_retries(
        flaky, policy=_policy(), on_retry=lambda a, d, e: seen.append((a, e))
    )
    assert [a for a, _ in seen] == [1, 2]


def test_no_retry_means_no_report():
    seen = []
    call_with_retries(lambda: "ok", policy=_policy(), on_retry=lambda *a: seen.append(a))
    assert seen == []
