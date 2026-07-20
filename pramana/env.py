"""Environment loading and validation.

The app auto-loads a local ``.env`` at startup and refuses to run a provider
whose required credential is missing — a fast, explicit failure at startup beats
an opaque auth error partway through a paid agent run.

Real environment variables always win over ``.env`` (``override=False``), so
exported secrets are never clobbered by a checked-out template.
"""

from __future__ import annotations

import os

from dotenv import find_dotenv, load_dotenv

# provider -> credential env vars; any one present (and non-empty) satisfies it.
PROVIDER_ENV: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "kimi": ("MOONSHOT_API_KEY", "KIMI_API_KEY"),
}


class EnvValidationError(RuntimeError):
    """Raised when required environment configuration is missing/invalid."""


def load_env(*, override: bool = False) -> str | None:
    """Auto-load the nearest ``.env`` (searching upward from the cwd).

    Idempotent and side-effect-safe to call at every entry point. Returns the
    path loaded, or ``None`` if no ``.env`` was found.
    """
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=override)
        return path
    return None


def validate_provider_env(provider: str) -> None:
    """Raise :class:`EnvValidationError` if ``provider``'s credential is absent
    or empty. Call before starting a real run so the app does not start when
    validation fails."""
    keys = PROVIDER_ENV.get(provider)
    if keys is None:
        raise EnvValidationError(f"unknown provider {provider!r}")
    if not any(os.environ.get(k, "").strip() for k in keys):
        names = " or ".join(keys)
        raise EnvValidationError(
            f"missing credential for provider {provider!r}: set {names} "
            "in your environment or a local .env file"
        )
