"""Slither static analysis — the finder's prioritized signal source (design §6).

Slither runs once up front (its output seeds the agent) and is also exposed as
a tool. Output is condensed to a readable summary of detector hits rather than
the raw JSON, which is both token-heavy and easy to truncate mid-structure.
Warnings are *leads*, never findings on their own.
"""

from __future__ import annotations

import json
import subprocess

from .files import ToolContext, ToolError


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


def run_slither_summary(ctx: ToolContext, path: str) -> str:
    """Run Slither on ``path`` (a single .sol file, compiled via solc) and
    return a condensed summary. Raises :class:`ToolError` if slither cannot be
    invoked at all."""
    target = ctx.resolve(path)
    if not target.exists():
        raise ToolError(f"file not found: {path}")
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
        return _summarize(proc.stdout)
    return (proc.stderr or "slither produced no output").strip()


def run_slither(ctx: ToolContext, path: str) -> str:
    return run_slither_summary(ctx, path)
