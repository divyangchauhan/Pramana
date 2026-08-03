"""Slither static analysis — the finder's prioritized signal source (design §6).

Slither runs once up front (its output seeds the agent) and is also exposed as
a tool. Output is condensed to a readable summary of detector hits rather than
the raw JSON, which is both token-heavy and easy to truncate mid-structure.
Warnings are *leads*, never findings on their own.

Slither is deterministic in the analyzed source and the analyzer version, so its
raw output is content-cached (design §9): a run over identical source reuses the
prior result instead of re-invoking the analyzer, which dominates finder-phase
latency. The cache is keyed on the source *and* the Slither version and only
stores a genuinely successful analysis — see :func:`run_slither_summary`.
"""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
from functools import lru_cache
from pathlib import Path

from .cache import cache_get, cache_put, content_key
from .files import ToolContext, ToolError

# Bump when the *cached payload* changes meaning (e.g. we start caching summaries
# instead of raw JSON), to invalidate every stale entry without a manual purge.
_CACHE_FORMAT = "v1"


@lru_cache(maxsize=1)
def _slither_version() -> str:
    """Installed slither-analyzer version, read once. Part of the cache key so a
    Slither upgrade produces fresh keys rather than serving results from the old
    analyzer. Read via importlib (no subprocess), with a stable fallback."""
    try:
        return importlib.metadata.version("slither-analyzer")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _sources_digest(target: Path) -> str:
    """Hash every ``.sol`` Slither could compile for ``target``.

    The corpus fixtures are self-contained, so the target's directory (the
    workspace ``src/``) is the whole compilation unit; hashing all siblings — not
    just the target — keeps the key correct if a fixture ever spans files. Each
    file contributes its name and bytes so a rename or an edit changes the key.
    """
    parts: list[str | bytes] = []
    for sol in sorted(target.parent.glob("*.sol")):
        parts.append(sol.name)
        parts.append(sol.read_bytes())
    return content_key(*parts)


def _cache_key(target: Path) -> str:
    return content_key(_CACHE_FORMAT, _slither_version(), _sources_digest(target))


def _summarize(raw_json: str) -> str:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return raw_json.strip()

    if not data.get("success", False):
        err = data.get("error") or "slither reported failure"
        return f"slither did not complete: {err}"

    detectors = data.get("results", {}).get("detectors", [])
    if not detectors:
        return "slither ran successfully and reported no detector hits."

    lines: list[str] = [f"slither reported {len(detectors)} detector hit(s):"]
    for i, d in enumerate(detectors, 1):
        desc = " ".join((d.get("description") or "").split())
        if len(desc) > 500:
            desc = desc[:500] + " …"
        lines.append(
            f"\n[{i}] check={d.get('check')} impact={d.get('impact')} "
            f"confidence={d.get('confidence')}\n    {desc}"
        )
    return "\n".join(lines)


def _is_successful(raw_json: str) -> bool:
    """Whether ``raw_json`` is a real, completed analysis worth caching. A crash,
    a compile failure (``success: false``), or non-JSON output must not be
    persisted and served to later runs as though it were the true result."""
    try:
        return bool(json.loads(raw_json).get("success", False))
    except json.JSONDecodeError:
        return False


def run_slither_summary(ctx: ToolContext, path: str) -> str:
    """Run Slither on ``path`` (a single .sol file, compiled via solc) and
    return a condensed summary. Raises :class:`ToolError` if slither cannot be
    invoked at all.

    A content-cache hit (when ``ctx.slither_cache_dir`` is set) returns the
    prior analysis without spawning the analyzer; misses run it and cache only a
    successful result. The summary is re-derived from the cached raw JSON, so
    changing :func:`_summarize` never requires invalidating the cache.
    """
    target = ctx.resolve(path)
    if not target.exists():
        raise ToolError(f"file not found: {path}")

    key = _cache_key(target)
    cached = cache_get(ctx.slither_cache_dir, key)
    if cached is not None:
        ctx.emit_trace({"event": "cache", "cache": "slither", "hit": True})
        return _summarize(cached)
    ctx.emit_trace({"event": "cache", "cache": "slither", "hit": False})

    try:
        proc = subprocess.run(
            ["slither", str(target), "--json", "-"],
            capture_output=True,
            text=True,
            timeout=ctx.slither_timeout,
            cwd=ctx.workspace,
        )
    except FileNotFoundError as exc:
        raise ToolError("slither is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"slither timed out after {ctx.slither_timeout}s") from exc

    # Slither writes its JSON to stdout (`--json -`); a crash leaves stderr only.
    if proc.stdout.strip():
        if _is_successful(proc.stdout):
            cache_put(ctx.slither_cache_dir, key, proc.stdout)
        return _summarize(proc.stdout)
    return (proc.stderr or "slither produced no output").strip()


def run_slither(ctx: ToolContext, path: str) -> str:
    return run_slither_summary(ctx, path)
