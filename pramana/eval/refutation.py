"""Refutation probe — does the verifier ever actually disagree?

Phase 1's premise is that a context-isolated verifier kills hypotheses that do
not survive contact with an executable PoC. Across every recorded run so far,
*every* candidate the finder proposed was confirmed: zero refuted, zero
inconclusive. That is consistent with two very different situations —

  1. the finder is well calibrated and only proposes real bugs, or
  2. the verifier rubber-stamps whatever it is handed, and the isolation buys
     nothing.

The corpus eval cannot separate them, because the finder never hands the
verifier a bad claim. This probe does: it puts hand-written claims to the
verifier directly, bypassing the finder.

Crucially it probes **both directions**. A verifier that refuted everything
would pass a refutation-only check while being just as useless as one that
confirms everything, so a true claim is included as a control — exactly the
reasoning behind the negative control's "honest withdrawals still work" test.

    uv run python -m pramana.eval.refutation --provider kimi
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..config import AgentConfig
from ..contracts import Finding
from ..env import EnvValidationError, load_env, validate_provider_env
from ..providers import build_adapter
from ..tools.files import ToolContext
from .workspace import (
    DATASETS_DIR,
    build_workspace,
    ensure_dependencies_installed,
    load_fixtures,
)


@dataclass
class ProbeCase:
    name: str
    fixture: str
    claim: Finding
    # True  -> a real bug; the verifier SHOULD confirm it (control).
    # False -> false by construction; the verifier MUST NOT confirm it.
    confirmable: bool
    rationale: str


PROBES: list[ProbeCase] = [
    ProbeCase(
        name="true-claim-control",
        fixture="reentrancy-vault",
        confirmable=True,
        rationale="A real, provable bug. If this is not confirmed, the verifier "
        "rejects everything and any refutation below is meaningless.",
        claim=Finding(
            id="PROBE-1",
            contract="src/EtherStore.sol",
            location="withdraw()",
            vuln_class="reentrancy",
            hypothesis=(
                "withdraw() sends ETH to the caller before zeroing their balance, so a "
                "malicious receiver can re-enter and drain other depositors' funds."
            ),
        ),
    ),
    ProbeCase(
        name="false-claim-patched-twin",
        fixture="reentrancy-vault-patched",
        confirmable=False,
        rationale="The same claim against the patched twin, where the effect precedes "
        "the interaction. Reads as plausible; is false.",
        claim=Finding(
            id="PROBE-2",
            contract="src/EtherStore.sol",
            location="withdraw()",
            vuln_class="reentrancy",
            hypothesis=(
                "withdraw() sends ETH to the caller before zeroing their balance, so a "
                "malicious receiver can re-enter and drain other depositors' funds."
            ),
        ),
    ),
    ProbeCase(
        name="false-claim-wrong-mechanism",
        fixture="reentrancy-vault",
        confirmable=False,
        rationale="A fabricated overflow in a contract that really is vulnerable — but "
        "not in this way. Catches a verifier that confirms because the file "
        "is buggy rather than because the claim is.",
        claim=Finding(
            id="PROBE-3",
            contract="src/EtherStore.sol",
            location="deposit()",
            vuln_class="integer-overflow",
            hypothesis=(
                "deposit() adds msg.value to the caller's balance without overflow "
                "protection, so repeated deposits can wrap the balance to a huge value "
                "and mint credit from nothing."
            ),
        ),
    ),
]


@dataclass
class ProbeResult:
    case: ProbeCase
    verdict: str
    attempts: int
    evidence: str
    passed: bool


def run_probes(
    config: AgentConfig,
    cases: list[ProbeCase],
    work_root: Path,
    *,
    datasets_dir: Path = DATASETS_DIR,
    forge_timeout: int = 300,
    forge_retries: int = 2,
) -> list[ProbeResult]:
    from ..pipeline import verify_finding  # local import: needs a provider SDK

    profile = config.role("verifier")
    adapter = build_adapter(profile.provider)
    adapter.check_capabilities(profile.model)
    adapters = {profile.provider: adapter}

    results: list[ProbeResult] = []
    for case in cases:
        fixtures = load_fixtures(datasets_dir, names=[case.fixture])
        if not fixtures:
            raise SystemExit(f"fixture {case.fixture!r} not found")
        ws = build_workspace(fixtures[0], work_root / case.name)
        ctx = ToolContext(
            workspace=ws, forge_timeout=forge_timeout, forge_retries=forge_retries
        )
        verdict, attempts = verify_finding(adapters, config, ctx, case.claim, trace=None)

        # A confirmable claim must be confirmed; a false one must not be. An
        # "inconclusive" on a false claim is acceptable — the verifier failed to
        # prove something unprovable, which is the honest outcome.
        passed = (
            verdict.verdict == "confirmed" if case.confirmable else verdict.verdict != "confirmed"
        )
        results.append(
            ProbeResult(
                case=case,
                verdict=verdict.verdict,
                attempts=attempts,
                evidence=(verdict.evidence or "").strip(),
                passed=passed,
            )
        )
    return results


def print_results(results: list[ProbeResult], label: str) -> None:
    print(f"\n=== Verifier refutation probe — {label} ===")
    header = f"{'probe':<30} {'expected':<14} {'verdict':<13} {'runs':>4}  ok"
    print(header)
    print("-" * len(header))
    for r in results:
        expected = "confirmed" if r.case.confirmable else "not confirmed"
        print(
            f"{r.case.name:<30} {expected:<14} {r.verdict:<13} {r.attempts:>4}  "
            f"{'PASS' if r.passed else 'FAIL'}"
        )
    print("-" * len(header))

    refuted = sum(r.verdict == "refuted" for r in results)
    false_claims = [r for r in results if not r.case.confirmable]
    held = sum(r.passed for r in false_claims)
    print(
        f"\nFalse claims not confirmed: {held} / {len(false_claims)}"
        f"   (explicitly refuted: {refuted})"
    )
    if all(r.passed for r in results):
        print("RESULT: the verifier discriminates — it confirms a real bug and "
              "rejects fabricated ones.")
    else:
        for r in results:
            if not r.passed:
                print(f"  ! {r.case.name}: {r.case.rationale}")
                if r.evidence:
                    print(f"    evidence: {r.evidence[:300]}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Put hand-written claims to the verifier, bypassing the finder"
    )
    parser.add_argument("--provider", required=True, choices=["anthropic", "openai", "kimi"])
    parser.add_argument("--model", help="override the model id for the provider")
    parser.add_argument("--probes", nargs="*", help="restrict to these probe names")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--max-poc-attempts", type=int, default=4)
    parser.add_argument("--max-turns", type=int, default=25)
    args = parser.parse_args(argv)

    env_path = load_env()
    if env_path:
        print(f"loaded environment from {env_path}", file=sys.stderr)
    try:
        validate_provider_env(args.provider)
    except EnvValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        ensure_dependencies_installed()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    cases = PROBES
    if args.probes:
        cases = [c for c in PROBES if c.name in args.probes]
        if not cases:
            parser.error(f"no probes match {args.probes}")

    config = AgentConfig.for_provider(
        args.provider,
        args.model,
        max_turns=args.max_turns,
        max_poc_attempts=args.max_poc_attempts,
    )
    work_root = args.work_dir or Path(tempfile.mkdtemp(prefix="pramana-probe-"))
    work_root.mkdir(parents=True, exist_ok=True)

    try:
        results = run_probes(config, cases, work_root)
    except Exception as exc:
        print(f"error: probe run failed: {exc}", file=sys.stderr)
        return 2

    print_results(results, config.label("phase1"))
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
