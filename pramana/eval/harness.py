"""Evaluation harness (design §8).

Runs the Phase 0 pipeline over labeled fixtures and computes the headline
number: **true-positive findings confirmed with executable PoCs**. A true
positive is a finding the agent marked "confirmed" whose PoC test the harness
*independently re-runs and sees pass* in a pristine workspace, and whose
vulnerability class matches a known bug in the fixture (matched 1:1).

That last condition is the weak one: the first two are executable facts, while
the third is string equality on a free-text label. Models name one bug many
ways — the same proven delegatecall storage collision has been reported as
`unrestricted-delegatecall`, `arbitrary-delegatecall` and plain `access-control`
— and label vocabulary is a per-model habit, so a grader sensitive to it partly
ranks naming style instead of capability. Two mechanisms keep that from costing
a correct finding, and they answer different questions:

  * `normalize_vuln_class` decides which class a label *names* when it carries
    words from several, by specificity rather than by where the classes happen
    to sit in the synonym map. General; applies to every label.
  * `KnownBug.accepts` in fixture.json declares the alternative names for a bug
    whose class is genuinely ambiguous — a delegatecall storage collision is
    equally an access-control break. Per bug, because the ambiguity is.

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
from ..cost import PRICE_TABLE_VERSION, Usage, estimate_usd, estimate_usd_notional
from ..env import EnvValidationError, load_env, validate_provider_env
from ..providers import build_adapter
from ..tools.files import ToolContext, ToolError
from ..tools.foundry import ForgeResult, forge_test
from .workspace import (
    DATASETS_DIR,
    Fixture,
    KnownBug,
    build_workspace,
    corpus_fingerprint,
    ensure_dependencies_installed,
    load_fixtures,
)

# Bumped whenever a change alters what a run scores from identical agent output.
# The corpus fingerprint cannot carry this: aliases and matching rules change
# the grade without changing the task. A recorded number is only comparable to
# another with the same corpus fingerprint *and* the same grader version.
#   1 — matching on the normalized class alone.
#   2 — per-bug `accepts` aliases; primary-class matches take precedence.
#   3 — labels resolve by specificity (qualifier tier, then needle length)
#       instead of by the synonym map's declaration order.
GRADER_VERSION = 3

# Canonical vulnerability class -> substrings that should map to it.
#
# Needles must be written in slug form (lowercase, `-` for punctuation), because
# `normalize_vuln_class` slugifies the label before matching: a needle spelled
# `tx.origin` could never fire. Enforced by test_synonym_map.
#
# Declaration order is *not* precedence — see `normalize_vuln_class`. It only
# breaks ties between needles of equal length, so a class may be added anywhere
# without silently demoting the ones below it.
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
    "tx-origin": ("tx-origin", "txorigin"),
    "integer-overflow": ("overflow", "underflow", "arithmetic", "batchoverflow"),
    "unchecked-call": ("unchecked", "unchecked-return", "unchecked-call", "unchecked-send"),
    "missing-zero-check": ("zero-address", "zero-check", "missing-zero", "zero-addr"),
    "delegatecall": ("delegatecall", "delegate-call", "storage-collision"),
    "weak-randomness": ("randomness", "weak-random", "predictable", "rng", "entropy"),
    "signature-replay": ("replay", "signature-replay", "missing-nonce", "sig-replay"),
}

# Needles that qualify a bug rather than name it.
#
# `unprotected`, `owner` and `unchecked` say how something is broken, not what
# it is, and models reach for them as adjectives in front of every class:
# `unprotected-delegatecall`, `unchecked-zero-address`, `owner-signature-replay`.
# Each names its class only when nothing more specific in the label does. Length
# alone cannot express that — `unprotected` (11) is longer than `reentran` (8) —
# so these are ranked below any substantive match instead.
QUALIFIERS = frozenset(
    {
        "unprotected",
        "authorization",
        "auth",
        "ownership",
        "owner",
        "privilege",
        "unchecked",
    }
)


def normalize_vuln_class(raw: str) -> str:
    """Canonicalize a free-text vulnerability label.

    Labels routinely carry words belonging to two classes — `unprotected-
    delegatecall` names both a mechanism and its precondition — so something has
    to decide which one the label is *about*. This resolves by specificity: a
    substantive needle beats a QUALIFIER, and within a tier the longest match
    wins, on the basis that `delegatecall` says more than `delegate` does.

    Through grader v2 this was first-match-wins over the ordered map, which made
    precedence a function of typing position. `access-control` sits near the top
    holding the most generic needles in the vocabulary, so it quietly captured
    labels belonging to six other classes; `signature-replay`, declared last,
    could be outranked by all of them. Nothing about the label is wrong when
    that happens — the finding is correct and its PoC passes, and the run still
    records a miss.

    Ties fall back to declaration order: arbitrary, but deterministic. An exact
    match on a canonical name always wins outright.
    """
    key = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    best, best_score = key, (0, 0)
    for canonical, needles in SYNONYMS.items():
        if key == canonical:
            return canonical
        hits = [n for n in needles if n in key]
        strong = max((len(n) for n in hits if n not in QUALIFIERS), default=0)
        weak = max((len(n) for n in hits if n in QUALIFIERS), default=0)
        score = (1, strong) if strong else (0, weak)
        if score > best_score:
            best, best_score = canonical, score
    return best


def accepted_classes(bug: KnownBug) -> set[str]:
    """Every normalized class that identifies ``bug``: its own, plus aliases."""
    return {normalize_vuln_class(bug.vuln_class)} | {
        normalize_vuln_class(alias) for alias in bug.accepts
    }


def _match_bug(known: list[KnownBug], cls: str, claimed: set[str]) -> KnownBug | None:
    """The unclaimed bug that ``cls`` identifies, or None.

    Primary classes are tried before aliases across the whole fixture: an alias
    is a concession to naming ambiguity, so it must never outrank a bug that
    carries the class outright. Without the two passes, a finding could be
    credited to a bug that merely tolerates its label while the bug actually
    named that way went unmatched — inflating one bug's recall and hiding the
    other's miss inside an unchanged total.
    """
    for bug in known:
        if bug.id not in claimed and normalize_vuln_class(bug.vuln_class) == cls:
            return bug
    for bug in known:
        if bug.id not in claimed and cls in accepted_classes(bug):
            return bug
    return None


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
        candidate_hit = any(cls in accepted_classes(kb) for kb in known)
        candidate_hits += int(candidate_hit)

        poc_ran = poc_passed = False
        if probe.verdict == "confirmed":
            n_confirmed += 1
            res = _verify_poc(
                fixture, probe.poc_file, grading_root / probe.id, forge_timeout, forge_retries
            )
            poc_ran, poc_passed = res.ran, res.passed
            confirmed_pass += int(poc_passed)

        matched: KnownBug | None = None
        if probe.verdict == "confirmed" and poc_passed:
            matched = _match_bug(known, cls, matched_bug_ids)
            if matched is not None:
                matched_bug_ids.add(matched.id)

        details.append(
            {
                "id": probe.id,
                "vuln_class": probe.vuln_class,
                "normalized": cls,
                "verdict": probe.verdict,
                "poc_ran": poc_ran,
                "poc_passed": poc_passed,
                "counted_true_positive": matched is not None,
                # Which bug it was credited to, and whether the label matched
                # outright or only via an alias. An audit trail: a run where
                # every match is aliased is a sign the corpus labels drifted
                # from how models actually name these bugs.
                "matched_bug": None if matched is None else matched.id,
                "matched_via_alias": (
                    matched is not None and normalize_vuln_class(matched.vuln_class) != cls
                ),
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
        notional = estimate_usd_notional(key, u)
        rows[role] = {
            "model": key,
            **u.as_dict(),
            "usd": None if usd is None else round(usd, 6),
            # Gateway rows only: list-price cost of the same tokens. Never
            # summed with `usd` — no money moved at this rate.
            "usd_notional": None if notional is None else round(notional, 6),
        }
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
    slither_cache_dir: Path | None = None,
    forge_cache_dir: Path | None = None,
) -> list[FixtureRow]:
    from ..pipeline import (  # local import: needs a provider SDK
        audit_phase0,
        audit_phase1,
        audit_phase2,
    )

    label = config.label(pipeline)

    # One adapter per distinct provider in the routing table, checked up front
    # so a bad model id fails before any fixture is run.
    if pipeline == "phase0":
        profiles = [config.agent]
    elif pipeline == "phase2":
        profiles = [config.role("finder"), config.role("verifier"), config.role("reporter")]
    else:
        profiles = [config.role("finder"), config.role("verifier")]
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
            workspace=audit_ws,
            forge_timeout=forge_timeout,
            forge_retries=forge_retries,
            slither_cache_dir=slither_cache_dir,
            forge_cache_dir=forge_cache_dir,
        )
        from ..tools.foundry import prime_compile_cache

        prime_compile_cache(ctx)
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
            elif pipeline == "phase2":
                result = audit_phase2(adapters, config, ctx, fx.contract, trace=trace)
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
        # ...and the rules they were scored under. Same corpus, different
        # grader, different number from identical agent output.
        "grader_version": GRADER_VERSION,
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
                    "usd_notional": 0.0,
                },
            )
            for field_name in ("input_tokens", "output_tokens", "calls", "elapsed_s"):
                acc[field_name] += entry[field_name]
            # One unpriced model poisons the role total rather than silently
            # dropping out of it — an understated cost picks a false winner.
            for money in ("usd", "usd_notional"):
                if acc[money] is not None and entry.get(money) is not None:
                    acc[money] += entry[money]
                else:
                    acc[money] = None
    for acc in by_role.values():
        acc["elapsed_s"] = round(acc["elapsed_s"], 3)
        for money in ("usd", "usd_notional"):
            if acc[money] is not None:
                acc[money] = round(acc[money], 6)

    def _total(field_name: str) -> float | None:
        values = [a[field_name] for a in by_role.values()]
        if not values or any(v is None for v in values):
            return None
        return round(sum(v for v in values), 6)

    return {
        "price_table_version": PRICE_TABLE_VERSION,
        "by_role": by_role,
        "usd_total": _total("usd"),
        # Gateway runs only. Never add this to usd_total — it is what the run
        # *would* have cost at list price, not money that moved.
        "usd_notional_total": _total("usd_notional"),
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

        def _money(acc: dict) -> str:
            if acc["usd"] is not None:
                return f"${acc['usd']:.4f}"
            if acc.get("usd_notional") is not None:
                # Tilde and the word "notional" both present: this is what the
                # tokens would list for, not money that moved.
                return f"~${acc['usd_notional']:.4f}*"
            return "unpriced"

        for role, acc in sorted(cost["by_role"].items()):
            print(f"  {role:<9} {acc['model']:<28} "
                  f"in {acc['input_tokens']:>8,}  out {acc['output_tokens']:>7,}  "
                  f"{acc['calls']:>3} calls  {acc['elapsed_s']:>7.1f}s  {_money(acc):>11}")
        total = _money(
            {"usd": cost["usd_total"], "usd_notional": cost["usd_notional_total"]}
        )
        print(f"  {'TOTAL':<9} {'':<28} "
              f"{'':>12}  {'':>11}  {'':>9}  {'':>8}  {total:>11}")
        if cost["usd_notional_total"] is not None:
            print("  * notional — gateway billing is a flat subscription, so no "
                  "money moved at these rates.")
            print("    Shown for efficiency comparison against first-party rows only.")
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
    parser.add_argument("--pipeline", choices=["phase0", "phase1", "phase2"], default="phase1",
                        help="phase0: one combined agent; phase1: finder -> isolated "
                             "verifier (default); phase2: adds the reporter (Nirnaya) "
                             "that writes the deliverable")
    parser.add_argument("--finder-model", help="route the finder to a different model (phase1/2)")
    parser.add_argument("--verifier-model",
                        help="route the verifier to a different model (phase1/2)")
    parser.add_argument("--reporter-model",
                        help="route the reporter to a different model (phase2); the cheap "
                             "synthesis slot, so the natural one to route to a smaller model")
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
    parser.add_argument("--slither-cache-dir", type=Path, default=Path(".cache/slither"),
                        help="content cache for Slither output, reused across runs "
                             "(default .cache/slither)")
    parser.add_argument("--no-slither-cache", action="store_true",
                        help="disable the Slither result cache (clean-room timing)")
    parser.add_argument("--forge-cache-dir", type=Path, default=Path(".cache/forge"),
                        help="content cache for pristine Foundry compilation output "
                             "(default .cache/forge)")
    parser.add_argument("--no-forge-cache", action="store_true",
                        help="disable the Foundry compile cache (clean-room timing)")
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
            reporter_model=args.reporter_model,
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
                slither_cache_dir=None if args.no_slither_cache else args.slither_cache_dir,
                forge_cache_dir=None if args.no_forge_cache else args.forge_cache_dir,
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
