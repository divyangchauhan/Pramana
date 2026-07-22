"""Evaluation harness (design §8).

Runs the Phase 0 pipeline over labeled fixtures and computes the headline
number: **true-positive findings confirmed with executable PoCs**. A true
positive is a finding the agent marked "confirmed" whose PoC test the harness
*independently re-runs and sees pass* in a pristine workspace, and whose
vulnerability class matches a known bug in the fixture (matched 1:1).

Run modes:
  * ``--self-check``    grade the reference PoCs (no API key; validates the
                        corpus + grading path end to end).
  * ``--provider ...``  run the real agent over each fixture and grade it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..agents.loop import TraceFn
from ..config import EFFORT_LEVELS, SUPPORTED_PROVIDERS, AgentConfig
from ..cost import PRICE_TABLE_VERSION, Usage, estimate_usd
from ..env import EnvValidationError, load_env, validate_provider_env
from ..providers import build_adapter
from ..tools.files import ToolContext, ToolError
from ..tools.foundry import ForgeResult, forge_test
from .workspace import (
    DATASETS_DIR,
    Fixture,
    build_workspace,
    corpus_fingerprint,
    ensure_dependencies_installed,
    load_fixtures,
)

# Canonical vulnerability class -> substrings that should map to it.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "reentrancy": ("reentran", "re-entran"),
    "access-control": (
        "access-control",
        "unprotected",
        "authorization",
        "auth",
        "ownership",
        "owner",
        "privilege",
    ),
    "tx-origin": ("tx-origin", "txorigin", "tx.origin"),
    "integer-overflow": ("overflow", "underflow", "arithmetic", "batchoverflow"),
    "unchecked-call": ("unchecked", "unchecked-return", "unchecked-call", "unchecked-send"),
    "missing-zero-check": ("zero-address", "zero-check", "missing-zero", "zero-addr"),
    "delegatecall": ("delegatecall", "delegate-call", "storage-collision"),
    "weak-randomness": ("randomness", "weak-random", "predictable", "rng", "entropy"),
    "signature-replay": ("replay", "signature-replay", "missing-nonce", "sig-replay"),
}


def normalize_vuln_class(raw: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    for canonical, needles in SYNONYMS.items():
        if key == canonical or any(n in key for n in needles):
            return canonical
    return key


@dataclass
class Probe:
    """A candidate finding to grade, independent of how it was produced."""

    id: str
    vuln_class: str
    verdict: str
    poc_file: Path | None  # absolute path to the PoC test file, if any


@dataclass
class FixtureRow:
    fixture: str
    config: str
    n_candidates: int
    n_confirmed: int
    confirmed_poc_pass: int
    true_positive_findings: int
    n_known_bugs: int
    finder_precision: float | None
    verifier_precision: float | None
    recall: float | None
    # Claims the verifier actively killed. Always 0 for phase0, whose single
    # agent has no refutation step — this is the count Phase 1 exists to move.
    n_refuted: int = 0
    error: str | None = None
    report_markdown: str = ""
    details: list[dict] = field(default_factory=list)
    # role -> {model, input_tokens, output_tokens, calls, elapsed_s, usd}.
    # ``usd`` is None for a model absent from the pinned price table.
    usage: dict[str, dict] = field(default_factory=dict)


def _verify_poc(
    fixture: Fixture, poc_file: Path | None, grading_dir: Path, timeout: int, retries: int
) -> ForgeResult:
    if poc_file is None or not poc_file.exists():
        return ForgeResult(ran=False, passed=False, output="PoC file not found")
    ws = build_workspace(fixture, grading_dir)  # pristine target source
    dest = ws / "test" / poc_file.name
    dest.write_text(poc_file.read_text())
    try:
        return forge_test(ws, f"test/{poc_file.name}", timeout=timeout, retries=retries)
    except ToolError as exc:  # forge missing / persistent flakiness -> not a pass
        return ForgeResult(ran=False, passed=False, output=f"forge error: {exc}")


def grade(
    fixture: Fixture,
    probes: list[Probe],
    grading_root: Path,
    config_label: str,
    *,
    forge_timeout: int = 300,
    forge_retries: int = 2,
) -> FixtureRow:
    known = fixture.known_bugs
    matched_bug_ids: set[str] = set()
    n_confirmed = 0
    confirmed_pass = 0
    candidate_hits = 0
    details: list[dict] = []

    for probe in probes:
        cls = normalize_vuln_class(probe.vuln_class)
        candidate_hit = any(normalize_vuln_class(kb.vuln_class) == cls for kb in known)
        candidate_hits += int(candidate_hit)

        poc_ran = poc_passed = False
        if probe.verdict == "confirmed":
            n_confirmed += 1
            res = _verify_poc(
                fixture, probe.poc_file, grading_root / probe.id, forge_timeout, forge_retries
            )
            poc_ran, poc_passed = res.ran, res.passed
            confirmed_pass += int(poc_passed)

        is_tp = False
        if probe.verdict == "confirmed" and poc_passed:
            for kb in known:
                if kb.id not in matched_bug_ids and normalize_vuln_class(kb.vuln_class) == cls:
                    matched_bug_ids.add(kb.id)
                    is_tp = True
                    break

        details.append(
            {
                "id": probe.id,
                "vuln_class": probe.vuln_class,
                "normalized": cls,
                "verdict": probe.verdict,
                "poc_ran": poc_ran,
                "poc_passed": poc_passed,
                "counted_true_positive": is_tp,
            }
        )

    tp = len(matched_bug_ids)
    n_candidates = len(probes)
    return FixtureRow(
        fixture=fixture.name,
        config=config_label,
        n_candidates=n_candidates,
        n_confirmed=n_confirmed,
        confirmed_poc_pass=confirmed_pass,
        true_positive_findings=tp,
        n_known_bugs=len(known),
        finder_precision=(candidate_hits / n_candidates) if n_candidates else None,
        verifier_precision=(tp / n_confirmed) if n_confirmed else None,
        recall=(tp / len(known)) if known else None,
        details=details,
    )


# --- probe construction ------------------------------------------------------


def probes_from_reference(fixture: Fixture) -> list[Probe]:
    """Self-check: one confirmed probe per known bug, pointed at its reference PoC
    (per-bug ``reference_poc`` if set, else the fixture-level one)."""
    probes: list[Probe] = []
    for kb in fixture.known_bugs:
        ref_rel = kb.reference_poc or fixture.reference_poc
        ref = fixture.dir / ref_rel if ref_rel else None
        probes.append(
            Probe(id=f"REF-{kb.id}", vuln_class=kb.vuln_class, verdict="confirmed", poc_file=ref)
        )
    return probes


def probes_from_audit(output, audit_workspace: Path) -> list[Probe]:
    probes: list[Probe] = []
    for f in output.findings:
        poc = None
        if f.poc_path:
            poc = (audit_workspace / f.poc_path).resolve()
        probes.append(Probe(id=f.id, vuln_class=f.vuln_class, verdict=f.verdict, poc_file=poc))
    return probes


# --- run modes ---------------------------------------------------------------


def run_self_check(
    fixtures: list[Fixture], work_root: Path, forge_timeout: int, forge_retries: int = 2
) -> list[FixtureRow]:
    rows: list[FixtureRow] = []
    for fx in fixtures:
        probes = probes_from_reference(fx)
        row = grade(
            fx,
            probes,
            work_root / fx.name,
            "reference-poc",
            forge_timeout=forge_timeout,
            forge_retries=forge_retries,
        )
        rows.append(row)
    return rows


def _usage_rows(usage: dict[str, tuple[str, Usage]]) -> dict[str, dict]:
    """Flatten per-role usage and price it under the pinned table."""
    rows: dict[str, dict] = {}
    for role, (key, u) in usage.items():
        usd = estimate_usd(key, u)
        rows[role] = {"model": key, **u.as_dict(), "usd": None if usd is None else round(usd, 6)}
    return rows


def run_agent_eval(
    fixtures: list[Fixture],
    config: AgentConfig,
    work_root: Path,
    forge_timeout: int,
    *,
    forge_retries: int = 2,
    verbose: bool = False,
    pipeline: str = "phase0",
) -> list[FixtureRow]:
    from ..pipeline import audit_phase0, audit_phase1  # local import: needs a provider SDK

    label = config.label(pipeline)

    # One adapter per distinct provider in the routing table, checked up front
    # so a bad model id fails before any fixture is run.
    profiles = (
        [config.agent] if pipeline == "phase0" else [config.role("finder"), config.role("verifier")]
    )
    adapters = {}
    for profile in profiles:
        adapter = adapters.get(profile.provider) or build_adapter(profile.provider)
        adapter.check_capabilities(profile.model)
        adapters[profile.provider] = adapter

    rows: list[FixtureRow] = []
    for fx in fixtures:
        audit_ws = work_root / fx.name / "audit"
        build_workspace(fx, audit_ws)
        ctx = ToolContext(
            workspace=audit_ws, forge_timeout=forge_timeout, forge_retries=forge_retries
        )
        trace: TraceFn | None = None
        if verbose:
            def _trace(e: dict, _name: str = fx.name) -> None:
                print(f"  [{_name}] {e}", file=sys.stderr)
            trace = _trace
        try:
            if pipeline == "phase0":
                result = audit_phase0(
                    adapters[config.agent.provider], config, ctx, fx.contract, trace=trace
                )
            else:
                result = audit_phase1(adapters, config, ctx, fx.contract, trace=trace)
        except Exception as exc:  # keep the sweep going; record the failure
            # A failure is not a refund. PipelineError carries the per-role
            # spend up to the point it died, so a config that fails late and
            # expensively is not recorded as the cheap one.
            spent = getattr(exc, "usage", None)
            cause = exc.__cause__ or exc
            rows.append(
                FixtureRow(
                    fixture=fx.name,
                    config=label,
                    n_candidates=0,
                    n_confirmed=0,
                    confirmed_poc_pass=0,
                    true_positive_findings=0,
                    n_known_bugs=len(fx.known_bugs),
                    finder_precision=None,
                    verifier_precision=None,
                    recall=0.0 if fx.known_bugs else None,
                    error=f"{type(cause).__name__}: {cause}",
                    usage=_usage_rows(spent) if isinstance(spent, dict) else {},
                )
            )
            continue
        probes = probes_from_audit(result.output, audit_ws)
        row = grade(
            fx,
            probes,
            work_root / fx.name / "grade",
            label,
            forge_timeout=forge_timeout,
            forge_retries=forge_retries,
        )
        row.report_markdown = result.output.report_markdown
        row.n_refuted = result.n_refuted
        row.usage = _usage_rows(result.usage)
        rows.append(row)
    return rows


# --- reporting ---------------------------------------------------------------


def summarize(rows: list[FixtureRow], fixtures: list[Fixture] | None = None) -> dict:
    total_tp = sum(r.true_positive_findings for r in rows)
    total_known = sum(r.n_known_bugs for r in rows)
    controls = [r for r in rows if r.n_known_bugs == 0]
    return {
        "true_positive_findings": total_tp,  # headline number
        "total_known_bugs": total_known,
        # Pins the corpus these numbers were scored against. Results from
        # different corpora are not comparable, however similar they look.
        "corpus_fingerprint": corpus_fingerprint(fixtures) if fixtures else None,
        # Negative controls hold no known bugs, so every confirmed finding on
        # one is unambiguously a false positive.
        "negative_control_fixtures": [r.fixture for r in controls],
        "negative_control_false_positives": sum(r.n_confirmed for r in controls),
        "negative_control_proven_false_positives": sum(r.confirmed_poc_pass for r in controls),
        # Confirmed findings on a *labeled* fixture that matched no known bug.
        # Recall cannot see these — a pipeline can hold 6/6 while flooding the
        # report. But the count conflates three things and only a human reading
        # the finding can separate them: a duplicate of an already-claimed bug,
        # a spurious claim, or a REAL bug missing from fixture.json. Treat a
        # non-zero value as "look at this", never as "the model was wrong".
        "unmatched_confirmed_findings": sum(
            r.n_confirmed - r.true_positive_findings for r in rows if r.n_known_bugs
        ),
        # What the run cost, per role, summed over fixtures. Recorded next to
        # precision/recall so a routing change is judged on what it bought and
        # not only on what it saved (design §9).
        "cost": _cost_summary(rows),
        # `report_markdown` is deliberately excluded: reports are written as
        # standalone files by --report-dir, and inlining them bloats the JSON.
        "fixtures": [
            {k: v for k, v in r.__dict__.items() if k != "report_markdown"} for r in rows
        ],
    }


def _cost_summary(rows: list[FixtureRow]) -> dict:
    """Roll per-fixture usage up to per-role totals for the run."""
    by_role: dict[str, dict] = {}
    for row in rows:
        for role, entry in row.usage.items():
            acc = by_role.setdefault(
                role,
                {
                    "model": entry["model"],
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "calls": 0,
                    "elapsed_s": 0.0,
                    "usd": 0.0,
                },
            )
            for field_name in ("input_tokens", "output_tokens", "calls", "elapsed_s"):
                acc[field_name] += entry[field_name]
            # One unpriced model poisons the role total rather than silently
            # dropping out of it — an understated cost picks a false winner.
            if acc["usd"] is not None and entry["usd"] is not None:
                acc["usd"] += entry["usd"]
            else:
                acc["usd"] = None
    for acc in by_role.values():
        acc["elapsed_s"] = round(acc["elapsed_s"], 3)
        if acc["usd"] is not None:
            acc["usd"] = round(acc["usd"], 6)
    totals = [a["usd"] for a in by_role.values()]
    return {
        "price_table_version": PRICE_TABLE_VERSION,
        "by_role": by_role,
        "usd_total": (
            None if any(t is None for t in totals) else round(sum(t for t in totals), 6)
        ),
    }


def print_report(rows: list[FixtureRow]) -> None:
    total_tp = sum(r.true_positive_findings for r in rows)
    total_known = sum(r.n_known_bugs for r in rows)
    print("\n=== Pramana eval ===")
    width = max([22, *(len(r.config) for r in rows)])
    header = (
        f"{'fixture':<26} {'cfg':<{width}} {'cand':>4} {'ref':>4} {'conf':>4} "
        f"{'poc+':>5} {'TP':>3} {'recall':>7}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        recall = "-" if r.recall is None else f"{r.recall:.2f}"
        line = (
            f"{r.fixture:<26} {r.config:<{width}} {r.n_candidates:>4} {r.n_refuted:>4} "
            f"{r.n_confirmed:>4} {r.confirmed_poc_pass:>5} "
            f"{r.true_positive_findings:>3} {recall:>7}"
        )
        print(line)
        if r.error:
            print(f"    ! error: {r.error}")
    print("-" * len(header))
    print(f"\nHEADLINE — true-positive findings confirmed with executable PoCs: "
          f"{total_tp} / {total_known} known bugs")

    # Negative controls (recall "-") carry no known bugs: any confirmed finding
    # on one is a false positive, and a *passing* PoC on one is a proven FP.
    unmatched = sum(r.n_confirmed - r.true_positive_findings for r in rows if r.n_known_bugs)
    if unmatched:
        print(f"UNMATCHED — {unmatched} confirmed finding(s) on labeled fixtures matched no "
              "known bug; recall cannot see these. Review each: duplicate, "
              "spurious, or a real bug missing from the label set?")

    controls = [r for r in rows if r.n_known_bugs == 0]
    if controls:
        fp = sum(r.n_confirmed for r in controls)
        proven = sum(r.confirmed_poc_pass for r in controls)
        print(f"NEGATIVE CONTROLS ({len(controls)}) — false positives: {fp} "
              f"confirmed, {proven} with a passing PoC")

    cost = _cost_summary(rows)
    if cost["by_role"]:
        print(f"\nCOST (price table {cost['price_table_version']})")
        for role, acc in sorted(cost["by_role"].items()):
            usd = "unpriced" if acc["usd"] is None else f"${acc['usd']:.4f}"
            print(f"  {role:<9} {acc['model']:<28} "
                  f"in {acc['input_tokens']:>8,}  out {acc['output_tokens']:>7,}  "
                  f"{acc['calls']:>3} calls  {acc['elapsed_s']:>7.1f}s  {usd:>10}")
        total = cost["usd_total"]
        print(f"  {'TOTAL':<9} {'':<28} "
              f"{'':>12}  {'':>11}  {'':>9}  {'':>8}  "
              f"{('unpriced' if total is None else f'${total:.4f}'):>10}")
    print()


def write_reports(rows: list[FixtureRow], report_dir: Path) -> int:
    """Write each fixture's audit report (the agent's markdown) to
    ``<report_dir>/<fixture>.md``. Returns the number of reports written."""
    report_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for r in rows:
        if not r.report_markdown.strip():
            continue  # self-check / errored runs have no agent report
        header = (
            f"# Audit report — {r.fixture}\n\n"
            f"- **Config:** {r.config}\n"
            f"- **True positives:** {r.true_positive_findings} / {r.n_known_bugs} known bugs\n"
            f"- **Confirmed / PoC-verified:** {r.n_confirmed} / {r.confirmed_poc_pass}\n\n---\n\n"
        )
        (report_dir / f"{r.fixture}.md").write_text(header + r.report_markdown)
        written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pramana Phase 0 evaluation harness")
    parser.add_argument("--self-check", action="store_true",
                        help="grade reference PoCs only (no API key needed)")
    # Derived, not duplicated: a hardcoded list silently omits any provider
    # added later, and the CLI is the only way anyone reaches one.
    parser.add_argument("--provider", choices=list(SUPPORTED_PROVIDERS),
                        help="LLM provider for a real agent run")
    parser.add_argument("--model", help="override the model id for the provider")
    parser.add_argument("--pipeline", choices=["phase0", "phase1"], default="phase1",
                        help="phase0: one combined agent; phase1: finder -> isolated "
                             "verifier (default)")
    parser.add_argument("--finder-model", help="route the finder to a different model (phase1)")
    parser.add_argument("--verifier-model", help="route the verifier to a different model (phase1)")
    parser.add_argument("--effort", choices=list(EFFORT_LEVELS),
                        help="reasoning depth for every role. Leaving this unset is NOT "
                             "neutral: provider defaults differ (anthropic high, openai "
                             "gpt-5.x medium), so an unset effort compares models at "
                             "different depths")
    parser.add_argument("--max-poc-attempts", type=int, default=4,
                        help="executed forge runs allowed per verification (phase1, default 4)")
    parser.add_argument("--fixtures", nargs="*", help="restrict to these fixture names")
    parser.add_argument("--datasets", type=Path, default=DATASETS_DIR)
    parser.add_argument("--work-dir", type=Path, help="where to build workspaces (default: temp)")
    parser.add_argument("--forge-timeout", type=int, default=300)
    parser.add_argument("--forge-retries", type=int, default=2,
                        help="retries for transient forge/anvil flakiness (default 2)")
    parser.add_argument("--max-turns", type=int, default=25)
    parser.add_argument("--max-tokens", type=int, default=16000)
    parser.add_argument("--json", type=Path, help="write full results JSON here")
    parser.add_argument("--report-dir", type=Path,
                        help="write a per-fixture audit report (report.md) here")
    parser.add_argument("--verbose", action="store_true", help="stream agent tool calls to stderr")
    args = parser.parse_args(argv)

    if not args.self_check and not args.provider:
        parser.error("pass --self-check, or --provider {anthropic,openai,kimi} for a real run")

    # Auto-load .env, then validate the selected provider's credential *before*
    # doing any work — do not start a real run if validation fails.
    env_path = load_env()
    if env_path:
        print(f"loaded environment from {env_path}", file=sys.stderr)
    if not args.self_check:
        try:
            validate_provider_env(args.provider)
        except EnvValidationError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    fixtures = load_fixtures(args.datasets, names=args.fixtures)
    if not fixtures:
        parser.error("no fixtures found")

    # Pre-flight: Foundry dependencies (forge-std) must be restored before any run.
    try:
        ensure_dependencies_installed()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    work_root = args.work_dir or Path(tempfile.mkdtemp(prefix="pramana-eval-"))
    work_root.mkdir(parents=True, exist_ok=True)

    if args.self_check:
        rows = run_self_check(fixtures, work_root, args.forge_timeout, args.forge_retries)
    else:
        config = AgentConfig.for_provider(
            args.provider,
            args.model,
            finder_model=args.finder_model,
            verifier_model=args.verifier_model,
            max_turns=args.max_turns,
            max_tokens=args.max_tokens,
            max_poc_attempts=args.max_poc_attempts,
            effort=args.effort,
        )
        try:
            rows = run_agent_eval(
                fixtures,
                config,
                work_root,
                args.forge_timeout,
                forge_retries=args.forge_retries,
                verbose=args.verbose,
                pipeline=args.pipeline,
            )
        except Exception as exc:  # provider setup / auth / capability failure
            print(f"error: could not start {config.label(args.pipeline)} run: {exc}",
                  file=sys.stderr)
            print(
                "hint: set the provider API key (ANTHROPIC_API_KEY / OPENAI_API_KEY / "
                "MOONSHOT_API_KEY) and pass a valid --model.",
                file=sys.stderr,
            )
            return 2

    print_report(rows)
    if args.json:
        args.json.write_text(json.dumps(summarize(rows, fixtures), indent=2))
        print(f"wrote {args.json}")
    if args.report_dir:
        n = write_reports(rows, args.report_dir)
        print(f"wrote {n} audit report(s) to {args.report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
