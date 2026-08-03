"""Foundry test execution — the verifier's ground truth (design §6).

``run_foundry_test`` is the model-facing tool. ``forge_test`` is the structured
helper the eval harness uses to *independently* re-run a confirmed PoC in a
clean workspace: a finding counts only if its test file actually passes there,
so the agent cannot fake a positive by editing the target contract.

Foundry/Anvil (and first-run solc downloads) are occasionally flaky, so runs are
retried when they produce *no* pass/fail summary — a crash or infra hiccup —
while a definitive pass/fail result is never retried (§9).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .cache import cache_tree_get, cache_tree_put, content_key
from .files import ToolContext, ToolError

_SUMMARY_RE = re.compile(r"(\d+)\s+passed;\s+(\d+)\s+failed")
_COMPILE_CACHE_FORMAT = "pramana-forge-compile-v1"


@dataclass
class ForgeResult:
    ran: bool  # at least one test executed (a definitive pass/fail result)
    passed: bool  # ran and zero failures
    output: str


@lru_cache(maxsize=1)
def _forge_version() -> str:
    """Return the Forge version used in compile-cache keys."""
    try:
        proc = subprocess.run(
            ["forge", "--version"], capture_output=True, text=True, timeout=10
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"
    return ((proc.stdout or "") + (proc.stderr or "")).strip() or "unknown"


def _compile_cache_key(workspace: Path) -> str:
    """Hash every input to the pristine workspace compilation."""
    parts: list[str | bytes] = [_COMPILE_CACHE_FORMAT, _forge_version()]
    inputs: list[tuple[str, Path]] = [
        (p.name, p) for p in workspace.glob("*.toml") if p.is_file()
    ]
    for root_name in ("src", "dependencies"):
        root = workspace / root_name
        if root.exists():
            resolved = root.resolve()
            inputs.extend(
                (f"{root_name}/{path.relative_to(resolved)}", path)
                for path in resolved.rglob("*.sol")
                if path.is_file()
            )
    for name, path in sorted(inputs, key=lambda item: item[0]):
        parts.extend((name, path.read_bytes()))
    return content_key(*parts)


def prime_compile_cache(ctx: ToolContext) -> bool:
    """Prepare reusable artifacts for the fixture's pristine source.

    On a hit, restore Foundry's paired ``out`` and ``cache`` trees. On a miss,
    run ``forge build`` once and store only a successful compilation. Returns
    whether the pristine build succeeded; callers may continue on failure so
    the verifier receives Forge's normal diagnostic when it runs its PoC.
    """
    if ctx.forge_cache_dir is None:
        return False
    key = _compile_cache_key(ctx.workspace)
    if cache_tree_get(ctx.forge_cache_dir, key, ctx.workspace / ".compile-state"):
        state = ctx.workspace / ".compile-state"
        try:
            shutil.copytree(state / "out", ctx.workspace / "out", dirs_exist_ok=True)
            shutil.copytree(state / "cache", ctx.workspace / "cache", dirs_exist_ok=True)
            shutil.rmtree(state)
            return True
        except OSError:
            shutil.rmtree(state, ignore_errors=True)
            shutil.rmtree(ctx.workspace / "out", ignore_errors=True)
            shutil.rmtree(ctx.workspace / "cache", ignore_errors=True)
    try:
        proc = subprocess.run(
            ["forge", "build"],
            capture_output=True,
            text=True,
            timeout=ctx.forge_timeout,
            cwd=ctx.workspace,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    state = ctx.workspace / ".compile-state"
    try:
        state.mkdir()
        shutil.copytree(ctx.workspace / "out", state / "out")
        shutil.copytree(ctx.workspace / "cache", state / "cache")
        cache_tree_put(ctx.forge_cache_dir, key, state)
    except OSError:
        pass
    finally:
        shutil.rmtree(state, ignore_errors=True)
    return True


def _run_once(workspace: Path, match_path: str, timeout: int) -> ForgeResult:
    try:
        proc = subprocess.run(
            ["forge", "test", "--match-path", match_path, "-vvv"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workspace,
        )
    except FileNotFoundError as exc:
        raise ToolError("forge is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"forge test timed out after {timeout}s") from exc

    output = (proc.stdout or "") + (proc.stderr or "")

    total_passed = 0
    total_failed = 0
    for passed, failed in _SUMMARY_RE.findall(output):
        total_passed += int(passed)
        total_failed += int(failed)

    ran = total_passed + total_failed > 0
    passed = ran and total_failed == 0
    return ForgeResult(ran=ran, passed=passed, output=output)


def forge_test(
    workspace: Path,
    match_path: str,
    timeout: int = 300,
    *,
    retries: int = 2,
    backoff: float = 0.5,
) -> ForgeResult:
    """Run the PoC test(s), retrying only transient failures.

    A run that yields a pass/fail summary (``ran``) is definitive and returned
    immediately. A run that produces no summary — or raises a transient error
    like a timeout — is retried up to ``retries`` times with linear backoff, to
    ride out Foundry/Anvil flakiness. A missing ``forge`` binary is not
    transient and is raised straight away.
    """
    result: ForgeResult | None = None
    for attempt in range(retries + 1):
        try:
            result = _run_once(workspace, match_path, timeout)
        except ToolError as exc:
            if "not installed" in str(exc):
                raise  # deterministic setup error — do not retry
            if attempt >= retries:
                raise  # transient error persisted across every attempt
            time.sleep(backoff * (attempt + 1))
            continue

        if result.ran:
            return result  # definitive pass/fail — never retried
        if attempt < retries:
            time.sleep(backoff * (attempt + 1))
    # The loop always runs at least once and only reaches here with `result`
    # set (a transient error on the final attempt re-raises above).
    assert result is not None
    return result  # exhausted retries with no definitive result


def run_foundry_test(ctx: ToolContext, test_path: str) -> str:
    """Model-facing tool: compile and run the PoC test(s) matching ``test_path``
    and return forge's output. Forge's own pass/fail summary tells the model
    whether the exploit fired."""
    # Validate the path is inside the sandbox; forge itself takes the relative glob.
    ctx.resolve(test_path)
    result = forge_test(ctx.workspace, test_path, ctx.forge_timeout, retries=ctx.forge_retries)
    if not result.ran:
        return (
            "No tests were executed (check the --match-path and that the file "
            "compiles).\n\n" + result.output
        )
    return result.output
