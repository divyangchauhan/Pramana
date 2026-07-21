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

    def stable(self) -> bool:
        return len(set(self.tp)) <= 1


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
    configs = sorted({row["config"] for r in runs for row in r["fixtures"]})

    return {
        "label": label,
        "captured_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _git("rev-parse", "HEAD"),
        "commit_short": _git("rev-parse", "--short", "HEAD"),
        "commit_url": f"{url}/commit/{_git('rev-parse', 'HEAD')}" if (url := _repo_url()) else "",
        "working_tree_dirty": _tracked_files_dirty(),
        "configs": configs,
        "n_runs": len(runs),
        "total_known_bugs": runs[0]["total_known_bugs"],
        "true_positives_per_run": totals,
        "true_positives_min": min(totals),
        "true_positives_max": max(totals),
        "true_positives_mean": round(statistics.fmean(totals), 2),
        "negative_control_false_positives_per_run": control_fps,
        "negative_control_proven_false_positives_per_run": control_proven,
        "fully_deterministic": all(s.stable() for s in stats.values()),
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


def render_markdown(b: dict[str, Any]) -> str:
    stats = b["fixtures"]
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
        lines.append(
            f"| `{s['fixture']}` | {known} | {tp} | {conf} | "
            f"{'✅' if s['stable_across_runs'] else '⚠️'} |"
        )

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
        "- **Run-to-run stability:** "
        + (
            "identical results across all runs"
            if b["fully_deterministic"]
            else "varies between runs — compare against the range, not a single number"
        ),
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
        f"uv run python -m pramana.eval.harness --provider {b['configs'][0].split(':')[0]} \\",
        "    --json runs/run-1.json --report-dir runs/reports-1",
        "```",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aggregate harness runs into a baseline record")
    ap.add_argument("--runs", nargs="+", type=Path, required=True, help="harness --json outputs")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--label", default="Phase 0")
    args = ap.parse_args(argv)

    baseline = aggregate(args.runs, args.label)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n")
    (args.out_dir / "README.md").write_text(render_markdown(baseline))
    print(f"wrote baseline for {baseline['n_runs']} run(s) to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
