"""Filesystem tools and the per-run tool context.

Every tool operates relative to a single workspace directory (a Foundry
project) and is sandboxed to it: a model-supplied path is resolved and rejected
if it escapes the workspace root. This both contains the agent and keeps runs
reproducible.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ToolError(Exception):
    """Raised by tools for conditions the model should see and recover from."""


@dataclass
class ToolContext:
    """Shared state handed to every tool in one audit run."""

    workspace: Path
    slither_timeout: int = 180
    forge_timeout: int = 300
    forge_retries: int = 2
    max_output_chars: int = 20_000
    # Content-addressed cache for deterministic tool output (Slither). ``None``
    # disables caching entirely, keeping the uncached path for tests and
    # clean-room measurements; the harness points it at a persistent directory
    # so repeated runs over identical source reuse the analysis (design §9).
    slither_cache_dir: Path | None = None
    # Cached pristine Foundry compilation state (``out`` + ``cache``). The
    # verifier's generated tests compile incrementally on top of it.
    forge_cache_dir: Path | None = None
    trace: Callable[[dict[str, Any]], None] | None = None

    def emit_trace(self, event: dict[str, Any]) -> None:
        if self.trace is not None:
            self.trace(event)

    def resolve(self, path: str) -> Path:
        """Resolve ``path`` against the workspace and reject any escape."""
        candidate = Path(path)
        target = (candidate if candidate.is_absolute() else self.workspace / candidate).resolve()
        root = self.workspace.resolve()
        if target != root and root not in target.parents:
            raise ToolError(f"path {path!r} escapes the workspace sandbox")
        return target

    def rel(self, target: Path) -> str:
        return str(target.resolve().relative_to(self.workspace.resolve()))


def read_file(ctx: ToolContext, path: str) -> str:
    target = ctx.resolve(path)
    if not target.exists():
        raise ToolError(f"file not found: {path}")
    if target.is_dir():
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
        return f"directory {ctx.rel(target)}/:\n" + "\n".join(entries)
    return target.read_text()


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    target = ctx.resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"wrote {ctx.rel(target)} ({len(content)} bytes)"
