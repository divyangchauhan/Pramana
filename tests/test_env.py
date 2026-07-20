"""Tests for startup env validation (offline)."""

from __future__ import annotations

import pytest

from pramana.env import EnvValidationError, validate_provider_env

ALL_KEYS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY", "KIMI_API_KEY"]


@pytest.fixture(autouse=True)
def _clear_keys(monkeypatch):
    for k in ALL_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_missing_key_fails(monkeypatch):
    with pytest.raises(EnvValidationError, match="ANTHROPIC_API_KEY"):
        validate_provider_env("anthropic")


def test_empty_key_fails(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    with pytest.raises(EnvValidationError):
        validate_provider_env("anthropic")


def test_present_key_passes(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xyz")
    validate_provider_env("anthropic")  # no raise


def test_kimi_accepts_either_alias(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "k")
    validate_provider_env("kimi")  # KIMI_API_KEY alias is accepted


def test_unknown_provider_fails():
    with pytest.raises(EnvValidationError, match="unknown provider"):
        validate_provider_env("nope")
