"""Tests for the Foundry runner's transient-failure retry logic (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pramana.tools import foundry
from pramana.tools.files import ToolError
from pramana.tools.foundry import ForgeResult, forge_test


def test_transient_no_summary_is_retried_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake(ws, mp, to):
        calls["n"] += 1
        if calls["n"] == 1:
            return ForgeResult(ran=False, passed=False, output="flaky, no summary")
        return ForgeResult(ran=True, passed=True, output="1 passed; 0 failed")

    monkeypatch.setattr(foundry, "_run_once", fake)
    res = forge_test(Path("."), "test/x.t.sol", retries=2, backoff=0)
    assert res.passed
    assert calls["n"] == 2


def test_definitive_result_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def fake(ws, mp, to):
        calls["n"] += 1
        return ForgeResult(ran=True, passed=False, output="0 passed; 1 failed")

    monkeypatch.setattr(foundry, "_run_once", fake)
    res = forge_test(Path("."), "test/x.t.sol", retries=3, backoff=0)
    assert res.ran and not res.passed
    assert calls["n"] == 1  # a real pass/fail is authoritative — never retried


def test_missing_forge_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def fake(ws, mp, to):
        calls["n"] += 1
        raise ToolError("forge is not installed or not on PATH")

    monkeypatch.setattr(foundry, "_run_once", fake)
    with pytest.raises(ToolError, match="not installed"):
        forge_test(Path("."), "test/x.t.sol", retries=3, backoff=0)
    assert calls["n"] == 1


def test_persistent_transient_error_raises_after_retries(monkeypatch):
    calls = {"n": 0}

    def fake(ws, mp, to):
        calls["n"] += 1
        raise ToolError("forge test timed out after 1s")

    monkeypatch.setattr(foundry, "_run_once", fake)
    with pytest.raises(ToolError, match="timed out"):
        forge_test(Path("."), "test/x.t.sol", retries=2, backoff=0)
    assert calls["n"] == 3  # initial + 2 retries
