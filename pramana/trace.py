"""Stable, redacted JSONL observability traces (design §9)."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TRACE_SCHEMA_VERSION = 1
MAX_TRACE_STRING = 4_000
REDACTED = "[REDACTED]"
TRACE_ENVELOPE_FIELDS = frozenset({
    "schema_version", "timestamp", "run_id", "fixture", "sequence", "role", "model", "event",
})

_SENSITIVE_KEYS = {
    "api_key", "apikey", "authorization", "cookie", "password", "secret",
    "access_token", "refresh_token", "private_key", "x-api-key",
}
_SECRET_PATTERNS = (
    re.compile(
        r"(?i)((?:api[_-]?key|token|secret|password|authorization)[\"']?"
        r"\s*[:=]\s*[\"']?)[^\s\"',}]+"
    ),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\b(?:sk|gh[opusr]|github_pat)_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\b(?:AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,}|xox[baprs]-[A-Za-z0-9-]{8,})"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
)


def _redact_text(value: str) -> str:
    clean = value
    for pattern in _SECRET_PATTERNS:
        clean = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + REDACTED, clean)
    if len(clean) > MAX_TRACE_STRING:
        clean = clean[:MAX_TRACE_STRING] + f"…[truncated {len(clean) - MAX_TRACE_STRING} chars]"
    return clean


def redact(value: Any, *, key: str | None = None) -> Any:
    """Return a JSON-safe, recursively redacted and size-bounded value."""
    if key is not None and key.lower().replace("-", "_") in _SENSITIVE_KEYS:
        return REDACTED
    if isinstance(value, Mapping):
        return {str(k): redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(str(value))


class JsonlTrace:
    """Append-only per-fixture trace writer with stable envelope fields."""

    def __init__(self, path: Path, *, run_id: str, fixture: str) -> None:
        self.path = path
        self.run_id = run_id
        self.fixture = fixture
        self._sequence = 0
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")

    def __call__(self, event: dict[str, Any]) -> None:
        if not isinstance(event.get("event"), str):
            raise ValueError("trace event must contain a string 'event' field")
        with self._lock:
            record = {
                "schema_version": TRACE_SCHEMA_VERSION,
                "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "run_id": self.run_id,
                "fixture": self.fixture,
                "sequence": self._sequence,
                "role": None,
                "model": None,
                **redact(event),
            }
            self._sequence += 1
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
