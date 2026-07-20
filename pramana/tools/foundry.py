"""Foundry test execution — the verifier's ground truth (design §6).

``run_foundry_test`` is the model-facing tool. ``forge_test`` is the structured
helper the eval harness uses to *independently* re-run a confirmed PoC in a
clean workspace: a finding counts only if its test file actually passes there,
so the agent cannot fake a positive by editing the target contract.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .files import ToolContext, ToolError

_SUMMARY_RE = re.compile(r"(\d+)\s+passed;\s+(\d+)\s+failed")


@dataclass
class ForgeResult:
    ran: bool  # at least one test executed
    passed: bool  # ran and zero failures
    output: str


def _run(workspace: Path, match_path: str, timeout: int) -> ForgeResult:
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


def run_foundry_test(ctx: ToolContext, test_path: str) -> str:
    """Model-facing tool: compile and run the PoC test(s) matching ``test_path``
    and return forge's output. Forge's own pass/fail summary tells the model
    whether the exploit fired."""
    # Validate the path is inside the sandbox; forge itself takes the relative glob.
    ctx.resolve(test_path)
    result = _run(ctx.workspace, test_path, ctx.forge_timeout)
    if not result.ran:
        return (
            "No tests were executed (check the --match-path and that the file "
            "compiles).\n\n" + result.output
        )
    return result.output


def forge_test(workspace: Path, match_path: str, timeout: int = 300) -> ForgeResult:
    """Structured runner used by the grader."""
    return _run(workspace, match_path, timeout)
