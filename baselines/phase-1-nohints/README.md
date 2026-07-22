# Phase 1 (hint-free corpus) baseline

Captured **2026-07-21T16:17:50Z** at commit [`253069d`](https://github.com/divyangchauhan/Pramana/commit/253069d110d1b3ced63e91c320e5577ac586604c) over **1 independent runs** of `phase1/anthropic:claude-opus-4-8`.

> ⚠️ **Provisional — one run only.** Gating against this treats a single observation as a floor. Record further runs before relying on it.

This is the reference point for later phases. A refactor is a regression if it drops below the observed true-positive floor, or raises the negative-control false-positive ceiling.

| Fixture | Known bugs | True positives (per run) | Confirmed (per run) | Stable |
|---|:---:|:---:|:---:|:---:|
| `bank-multi` | 2 | 2 | 2 | – |
| `reentrancy-vault` | 1 | 1 | 1 | – |
| `reentrancy-vault-patched` | 0 *(control)* | 0 | 0 | – |
| `tx-origin-wallet` | 1 | 1 | 1 | – |
| `unchecked-overflow-token` | 1 | 1 | 1 | – |
| `unprotected-owner` | 1 | 1 | 1 | – |

## Headline

- **True positives:** 6 / 6 known bugs (mean 6.0) across 1 runs
- **Negative-control false positives:** 0 confirmed per run; 0 with a passing PoC
- **Run-to-run stability:** **not measured** — a single run cannot separate a real result from run-to-run variance

## Regression gate for later phases

- True positives must not fall below **6**.
- Negative-control false positives must not exceed **0** confirmed / **0** proven.

Reproduce with:

```bash
uv run python -m pramana.eval.harness --provider anthropic --pipeline phase1 \
    --json runs/run-1.json --report-dir runs/reports-1
```
