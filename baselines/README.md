# Baselines

Each subdirectory is a recorded reference point: N independent runs of one
pipeline over the corpus, with the commit, config and corpus pinned. Later
phases are gated against them (`pramana.eval.baseline --against`).

Results are only comparable **within the same corpus**. Runs and baselines
record a `corpus_fingerprint`; aggregating runs from different corpora is
refused, and comparing baselines across corpora reports "not comparable"
rather than a regression verdict.

| Record | Pipeline | Corpus | Status |
|---|---|---|---|
| [`phase-0/`](phase-0/) | single combined agent | pre-strip (`unfingerprinted`) | superseded |
| [`phase-1/`](phase-1/) | finder → isolated verifier | pre-strip (`unfingerprinted`) | superseded |
| `phase-1-nohints/` | finder → isolated verifier | `bee662ded628` | **pending** |

## The corpus changed

Both recorded baselines were measured while every fixture's source comments
explained its own bug — `BUG 1 — reentrancy: interaction before effect`,
`BUG: tx.origin authentication is phishable`, and `@notice` blocks naming The
DAO, Parity and BeautyChain. The agent reads those comments, so those numbers
partly measure reading comprehension rather than vulnerability discovery.

Those comments have since been removed (corpus `bee662ded628`). The contracts
are otherwise unchanged and all six reference exploits still pass, so the bugs
are intact — but **the old numbers describe an easier problem and are retained
as history, not as a gate.**

## Re-measurement status

The re-baseline sweep on the hint-free corpus stopped after one run when the
Anthropic account ran out of credits. That single run is not a baseline — one
run cannot separate a real change from ordinary run-to-run variance — but it
is worth recording:

| Metric | Pre-strip baseline (3 runs) | Hint-free (1 run) |
|---|:---:|:---:|
| True positives | 6 / 6 | 6 / 6 |
| Unmatched confirmed findings | 0 | 0 |
| Negative-control false positives | 0 | 0 |

Every bug was still found and proven with an executable PoC once the
explanatory comments were gone. Two more clean runs are needed before this
becomes the gating baseline.
