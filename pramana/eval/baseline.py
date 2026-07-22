"""Aggregate repeated harness runs into a committed baseline record.

A single agent run is not a baseline: the pipeline is nondeterministic, so one
number cannot distinguish a real regression from run-to-run variance. This
module folds N result JSONs (produced by `harness --json`) into per-fixture
ranges plus pinned provenance, so a later phase can be compared against a band
rather than a point.

    uv run python -m pramana.eval.baseline \
        --runs runs/run-*.json --out-dir baselines/phase-0 --label "Phase 0"
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _repo_url() -> str:
    """https URL for the origin remote, or "" if it can't be determined."""
    remote = _git("remote", "get-url", "origin")
    if remote in ("", "unknown"):
        return ""
    if remote.startswith("git@"):  # git@github.com:owner/repo.git
        remote = remote.replace(":", "/", 1).replace("git@", "https://", 1)
    return remote.removesuffix(".git")


def _tracked_files_dirty() -> bool:
    """True if tracked files differ from HEAD. Untracked files are ignored:
    the baseline artifact itself is untracked at capture time."""
    return bool(_git("status", "--porcelain", "--untracked-files=no"))


@dataclass
class FixtureStat:
    fixture: str
    n_known_bugs: int
    tp: list[int] = field(default_factory=list)
    confirmed: list[int] = field(default_factory=list)
    candidates: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def is_control(self) -> bool:
        return self.n_known_bugs == 0

    def stable(self) -> bool | None:
        """None when there is only one run: stability is not measurable from a
        single observation, and reporting True would assert something unknown."""
        if len(self.tp) < 2:
            return None
        return len(set(self.tp)) == 1


def aggregate(run_paths: list[Path], label: str) -> dict[str, Any]:
    runs = [json.loads(p.read_text()) for p in run_paths]
    if not runs:
        raise SystemExit("no run files given")

    stats: dict[str, FixtureStat] = {}
    for run in runs:
        for row in run["fixtures"]:
            st = stats.setdefault(
                row["fixture"], FixtureStat(row["fixture"], row["n_known_bugs"])
            )
            st.tp.append(row["true_positive_findings"])
            st.confirmed.append(row["n_confirmed"])
            st.candidates.append(row["n_candidates"])
            if row.get("error"):
                st.errors.append(row["error"])

    totals = [r["true_positive_findings"] for r in runs]
    control_fps = [r.get("negative_control_false_positives", 0) for r in runs]
    control_proven = [r.get("negative_control_proven_false_positives", 0) for r in runs]
    # Recomputed from the per-fixture rows rather than read from the summary, so
    # baselines recorded before this metric existed stay directly comparable.
    unmatched = [
        sum(
            row["n_confirmed"] - row["true_positive_findings"]
            for row in r["fixtures"]
            if row["n_known_bugs"]
        )
        for r in runs
    ]
    configs = sorted({row["config"] for r in runs for row in r["fixtures"]})
    # A run whose fixtures errored (auth failure, exhausted credits, a provider
    # outage) scores 0 for those fixtures. Folding it in would drag the floor to
    # zero and record an infrastructure failure as a capability measurement.
    broken = [
        (path.name, [row["fixture"] for row in run["fixtures"] if row.get("error")])
        for path, run in zip(run_paths, runs, strict=True)
        if any(row.get("error") for row in run["fixtures"])
    ]
    if broken:
        detail = "; ".join(f"{name}: {', '.join(fixtures)}" for name, fixtures in broken)
        raise SystemExit(
            f"refusing to build a baseline from runs with errored fixtures ({detail}). "
            "Re-run those fixtures — a baseline must describe what the pipeline does, "
            "not what the infrastructure did."
        )

    fingerprints = {r.get("corpus_fingerprint") for r in runs if r.get("corpus_fingerprint")}
    if len(fingerprints) > 1:
        raise SystemExit(
            f"runs span different corpora ({sorted(fingerprints)}); they cannot be "
            "aggregated into one baseline"
        )

    return {
        "label": label,
        "captured_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _git("rev-parse", "HEAD"),
        "commit_short": _git("rev-parse", "--short", "HEAD"),
        "commit_url": f"{url}/commit/{_git('rev-parse', 'HEAD')}" if (url := _repo_url()) else "",
        "working_tree_dirty": _tracked_files_dirty(),
        "configs": configs,
        "corpus_fingerprint": next(iter(fingerprints), None),
        "n_runs": len(runs),
        "total_known_bugs": runs[0]["total_known_bugs"],
        "true_positives_per_run": totals,
        "true_positives_min": min(totals),
        "true_positives_max": max(totals),
        "true_positives_mean": round(statistics.fmean(totals), 2),
        "negative_control_false_positives_per_run": control_fps,
        "negative_control_proven_false_positives_per_run": control_proven,
        "unmatched_confirmed_per_run": unmatched,
        # None when a single run makes variance unmeasurable.
        "fully_deterministic": (
            all(s.stable() for s in stats.values()) if len(runs) > 1 else None
        ),
        "fixtures": [
            {
                "fixture": s.fixture,
                "n_known_bugs": s.n_known_bugs,
                "is_negative_control": s.is_control,
                "true_positives_per_run": s.tp,
                "confirmed_per_run": s.confirmed,
                "candidates_per_run": s.candidates,
                "stable_across_runs": s.stable(),
                "errors": s.errors,
            }
            for s in sorted(stats.values(), key=lambda s: s.fixture)
        ],
    }


def _stability_line(b: dict[str, Any]) -> str:
    if b["n_runs"] < 2:
        return (
            "**not measured** — a single run cannot separate a real result from "
            "run-to-run variance"
        )
    if b["fully_deterministic"]:
        return "identical results across all runs"
    return "varies between runs — compare against the range, not a single number"


def render_markdown(b: dict[str, Any], comparison: dict[str, Any] | None = None) -> str:
    stats = b["fixtures"]
    pipeline, provider = _pipeline_and_provider(b["configs"][0])
    tp_span = (
        str(b["true_positives_min"])
        if b["true_positives_min"] == b["true_positives_max"]
        else f"{b['true_positives_min']}–{b['true_positives_max']}"
    )
    commit = (
        f"[`{b['commit_short']}`]({b['commit_url']})" if b.get("commit_url")
        else f"`{b['commit_short']}`"
    )
    lines = [
        f"# {b['label']} baseline",
        "",
        f"Captured **{b['captured_utc']}** at commit {commit} "
        f"over **{b['n_runs']} independent runs** of `{', '.join(b['configs'])}`.",
        "",
    ]
    if b["n_runs"] < 2:
        lines += [
            "> ⚠️ **Provisional — one run only.** Gating against this treats a single "
            "observation as a floor. Record further runs before relying on it.",
            "",
        ]
    if b.get("working_tree_dirty"):
        lines += [
            "> ⚠️ Captured with uncommitted changes to tracked files — the recorded "
            "commit does not fully describe the code that produced these numbers.",
            "",
        ]
    lines += [
        "This is the reference point for later phases. A refactor is a regression "
        "if it drops below the observed true-positive floor, or raises the "
        "negative-control false-positive ceiling.",
        "",
        "| Fixture | Known bugs | True positives (per run) | Confirmed (per run) | Stable |",
        "|---|:---:|:---:|:---:|:---:|",
    ]
    for s in stats:
        known = "0 *(control)*" if s["is_negative_control"] else str(s["n_known_bugs"])
        tp = ", ".join(str(v) for v in s["true_positives_per_run"])
        conf = ", ".join(str(v) for v in s["confirmed_per_run"])
        stable = {True: "✅", False: "⚠️", None: "–"}[s["stable_across_runs"]]
        lines.append(f"| `{s['fixture']}` | {known} | {tp} | {conf} | {stable} |")

    fps = b["negative_control_false_positives_per_run"]
    proven = b["negative_control_proven_false_positives_per_run"]
    lines += [
        "",
        "## Headline",
        "",
        f"- **True positives:** {tp_span} / {b['total_known_bugs']} known bugs "
        f"(mean {b['true_positives_mean']}) across {b['n_runs']} runs",
        f"- **Negative-control false positives:** {', '.join(str(v) for v in fps)} "
        f"confirmed per run; {', '.join(str(v) for v in proven)} with a passing PoC",
        "- **Run-to-run stability:** " + _stability_line(b),
        "",
        "## Regression gate for later phases",
        "",
        f"- True positives must not fall below **{b['true_positives_min']}**.",
        f"- Negative-control false positives must not exceed **{max(fps)}** "
        "confirmed" + (f" / **{max(proven)}** proven." if proven else "."),
        "",
        "Reproduce with:",
        "",
        "```bash",
        f"uv run python -m pramana.eval.harness --provider {provider} --pipeline {pipeline} \\",
        "    --json runs/run-1.json --report-dir runs/reports-1",
        "```",
    ]
    if comparison is not None:
        lines += ["", render_comparison(comparison).rstrip()]
    return "\n".join(lines) + "\n"


def _pipeline_and_provider(config_label: str) -> tuple[str, str]:
    """Split a run label back into (pipeline, provider).

    Labels look like ``phase1/anthropic:claude-opus-4-8`` or, when roles are
    routed apart, ``phase1/finder=anthropic:a,verifier=anthropic:b``. Baselines
    recorded before labels carried a pipeline prefix are read as phase0.
    """
    pipeline, sep, rest = config_label.partition("/")
    if not sep:
        pipeline, rest = "phase0", config_label
    first = rest.split(",")[0]
    if "=" in first:
        first = first.split("=", 1)[1]
    return pipeline, first.split(":")[0]


def _unmatched_per_run(b: dict[str, Any]) -> list[int]:
    """Unmatched confirmed findings per run, derived if not recorded.

    Baselines written before this metric existed still carry the per-fixture
    confirmed and true-positive counts it is computed from, so an old record
    can be compared against without re-running it — which would destroy its
    provenance by re-stamping numbers with a newer commit.
    """
    recorded = b.get("unmatched_confirmed_per_run")
    if recorded:
        return recorded
    n_runs = b.get("n_runs", 0)
    derived = [0] * n_runs
    for fixture in b.get("fixtures", []):
        if not fixture.get("n_known_bugs"):
            continue  # negative controls are counted separately
        confirmed = fixture.get("confirmed_per_run", [])
        tps = fixture.get("true_positives_per_run", [])
        for i, (c, tp) in enumerate(zip(confirmed, tps, strict=False)):
            if i < n_runs:
                derived[i] += c - tp
    return derived or [0]


def compare(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Check a candidate baseline against an earlier one's regression gate.

    The gate is a floor and a ceiling, not an average: a refactor regresses if
    its *worst* run finds fewer true positives than the baseline's worst run, or
    if its *worst* run produces more negative-control false positives than the
    baseline's worst. Comparing means would let a lucky run mask a bad one.
    """
    tp_floor = baseline["true_positives_min"]
    fp_ceiling = max(baseline["negative_control_false_positives_per_run"] or [0])
    tp_min = candidate["true_positives_min"]
    fp_max = max(candidate["negative_control_false_positives_per_run"] or [0])
    unmatched_ceiling = max(_unmatched_per_run(baseline))
    unmatched_max = max(_unmatched_per_run(candidate))

    base_by_fixture = {f["fixture"]: f for f in baseline["fixtures"]}
    fixtures = []
    for f in candidate["fixtures"]:
        prior = base_by_fixture.get(f["fixture"])
        if prior is None:
            continue
        before, after = min(prior["true_positives_per_run"]), min(f["true_positives_per_run"])
        fixtures.append(
            {
                "fixture": f["fixture"],
                "is_negative_control": f["is_negative_control"],
                "baseline_tp_floor": before,
                "candidate_tp_floor": after,
                "delta": after - before,
                "baseline_confirmed": prior["confirmed_per_run"],
                "candidate_confirmed": f["confirmed_per_run"],
            }
        )

    # A gate across two different corpora is meaningless — the numbers describe
    # different problems. Report it rather than quietly producing a verdict.
    base_corpus = baseline.get("corpus_fingerprint")
    cand_corpus = candidate.get("corpus_fingerprint")
    corpus_mismatch = bool(base_corpus and cand_corpus and base_corpus != cand_corpus)
    # A baseline recorded before fingerprinting existed cannot be *shown* to
    # describe the same corpus. Surface that rather than implying it was checked.
    corpus_unverified = not corpus_mismatch and not (base_corpus and cand_corpus)

    tp_regression = tp_min < tp_floor
    fp_regression = fp_max > fp_ceiling
    unmatched_regression = unmatched_max > unmatched_ceiling
    return {
        "baseline_corpus": base_corpus,
        "candidate_corpus": cand_corpus,
        "corpus_mismatch": corpus_mismatch,
        "corpus_unverified": corpus_unverified,
        "unmatched_ceiling": unmatched_ceiling,
        "candidate_unmatched_max": unmatched_max,
        "unmatched_regression": unmatched_regression,
        "baseline_label": baseline["label"],
        "baseline_commit": baseline["commit_short"],
        "candidate_label": candidate["label"],
        "candidate_commit": candidate["commit_short"],
        "true_positive_floor": tp_floor,
        "candidate_true_positive_floor": tp_min,
        "true_positive_regression": tp_regression,
        "false_positive_ceiling": fp_ceiling,
        "candidate_false_positive_max": fp_max,
        "false_positive_regression": fp_regression,
        "passed": not (
            tp_regression or fp_regression or unmatched_regression or corpus_mismatch
        ),
        "fixtures": fixtures,
    }


def render_comparison(c: dict[str, Any]) -> str:
    if c.get("corpus_mismatch"):
        return "\n".join(
            [
                f"## Comparison against {c['baseline_label']} (`{c['baseline_commit']}`)",
                "",
                "⚠️ **Not comparable — the corpus changed.**",
                "",
                f"Baseline was scored against corpus `{c['baseline_corpus']}`; this run "
                f"used `{c['candidate_corpus']}`. The fixtures themselves differ, so a "
                "regression verdict would compare numbers describing different problems. "
                "Re-record the baseline on the current corpus before gating against it.",
            ]
        ) + "\n"

    verdict = "✅ **No regression**" if c["passed"] else "❌ **Regression**"
    lines = [
        f"## Comparison against {c['baseline_label']} (`{c['baseline_commit']}`)",
        "",
        verdict,
        "",
    ]
    if c.get("corpus_unverified"):
        lines += [
            "> ⚠️ The baseline predates corpus fingerprinting, so it could not be "
            "confirmed to describe the same fixtures. Treat this verdict as advisory.",
            "",
        ]
    lines += [
        f"- True positives: floor **{c['candidate_true_positive_floor']}** vs baseline floor "
        f"**{c['true_positive_floor']}** — "
        + ("REGRESSION" if c["true_positive_regression"] else "gate held"),
        f"- Negative-control false positives: worst **{c['candidate_false_positive_max']}** vs "
        f"baseline ceiling **{c['false_positive_ceiling']}** — "
        + ("REGRESSION" if c["false_positive_regression"] else "gate held"),
        f"- Unmatched confirmed findings: worst **{c.get('candidate_unmatched_max', 0)}** vs "
        f"baseline ceiling **{c.get('unmatched_ceiling', 0)}** — "
        + ("REGRESSION" if c.get("unmatched_regression") else "gate held"),
        "",
        "| Fixture | Baseline TP (floor) | Candidate TP (floor) | Δ |",
        "|---|:---:|:---:|:---:|",
    ]
    for f in c["fixtures"]:
        name = f"`{f['fixture']}`" + (" *(control)*" if f["is_negative_control"] else "")
        delta = f["delta"]
        mark = "—" if delta == 0 else (f"+{delta}" if delta > 0 else str(delta))
        lines.append(
            f"| {name} | {f['baseline_tp_floor']} | {f['candidate_tp_floor']} | {mark} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aggregate harness runs into a baseline record")
    ap.add_argument("--runs", nargs="+", type=Path, required=True, help="harness --json outputs")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--label", default="Phase 0")
    ap.add_argument("--against", type=Path,
                    help="an earlier baseline.json to check for regression; "
                         "exits non-zero if its gate is broken")
    args = ap.parse_args(argv)

    baseline = aggregate(args.runs, args.label)

    comparison = None
    if args.against:
        comparison = compare(baseline, json.loads(args.against.read_text()))
        baseline["comparison"] = comparison

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n")
    (args.out_dir / "README.md").write_text(render_markdown(baseline, comparison))
    print(f"wrote baseline for {baseline['n_runs']} run(s) to {args.out_dir}")

    if comparison is not None:
        print()
        print(render_comparison(comparison))
        if not comparison["passed"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
