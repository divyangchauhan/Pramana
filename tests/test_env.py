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


def test_gateway_adapter_refuses_to_run_without_a_base_url(monkeypatch):
    """Without OPENAI_BASE_URL the SDK reaches first-party OpenAI while the run
    labels itself a gateway run — wrong provenance and wrong (absent) pricing."""
    from pramana.providers import ProviderError, build_adapter

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with pytest.raises(ProviderError, match="OPENAI_BASE_URL"):
        build_adapter("openai-gateway")


def test_gateway_adapter_reports_its_own_provider_identity(monkeypatch):
    from pramana.providers import build_adapter

    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8317/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert build_adapter("openai-gateway").provider == "openai-gateway"
    assert build_adapter("openai").provider == "openai"


def test_anthropic_gateway_validates_the_same_credential_as_anthropic(monkeypatch):
    """The subscription proxy authenticates with the Anthropic key, so the two
    providers share a credential requirement — a missing key must fail the same."""
    from pramana.env import validate_provider_env

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(EnvValidationError, match="ANTHROPIC_API_KEY"):
        validate_provider_env("anthropic-gateway")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    validate_provider_env("anthropic-gateway")  # now satisfied
