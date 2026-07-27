"""Retry for transient provider failures (design §9 — reliability).

A sweep run is all-or-nothing: ``aggregate()`` refuses any run containing an
errored fixture, so one 503 anywhere in a ten-fixture run discards the whole
run and its money. The local CLIProxyAPI gateway fails this way intermittently
(``auth_unavailable`` while its OAuth token refreshes), which made gateway rows
effectively uncompletable.

Retrying is only correct for failures that are *transient by nature*. A 401 or
a 400 will fail identically forever, and retrying them burns time and hides a
real configuration error behind an eventual generic failure. So the retryable
set is a whitelist of status codes, plus connection-level errors, and nothing
else.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

# Transient by nature: overload, rate limiting, gateway hiccups, and the
# gateway's own auth-refresh window. Deliberately excludes 401/403 (credential
# is wrong and will stay wrong) and 400/404/422 (the request is malformed or
# the model does not exist — retrying hides the real error).
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

# Substrings that mark a retryable failure even when the status code does not.
# The gateway reports its auth-refresh window as a 500-class internal error
# whose code alone would otherwise look permanent.
RETRYABLE_MESSAGES = ("auth_unavailable", "overloaded", "temporarily unavailable")


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 4
    base_delay: float = 1.5
    max_delay: float = 30.0


def is_retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status in RETRYABLE_STATUS:
            return True
        # A 4xx that is not in the whitelist is a client error: never retry.
        if 400 <= status < 500:
            return False
    if type(exc).__name__ in ("APIConnectionError", "APITimeoutError"):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in RETRYABLE_MESSAGES)


def call_with_retries(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    on_retry: Callable[[int, float, BaseException], None] | None = None,
) -> T:
    """Call ``fn``, retrying transient failures with exponential backoff.

    Re-raises the final exception unchanged so the caller still sees the real
    error — a run that exhausted its retries must not be reported as some
    generic retry failure. ``on_retry`` exists so a run that needed three
    attempts is visible rather than silently "clean".
    """
    policy = policy or RetryPolicy()
    for attempt in range(1, policy.attempts + 1):
        try:
            return fn()
        except BaseException as exc:
            if attempt == policy.attempts or not is_retryable(exc):
                raise
            # Full jitter: sweeps run fixtures back to back, and a fixed
            # backoff would resynchronise every retry onto the same instant.
            delay = min(policy.max_delay, policy.base_delay * 2 ** (attempt - 1))
            delay = random.uniform(0, delay)
            if on_retry:
                on_retry(attempt, delay, exc)
            time.sleep(delay)
    raise AssertionError("unreachable: the final attempt always raises")
