# Phase 1 (corpus 8693741ffa57) baseline

Captured **2026-07-26T06:01:22Z** at commit [`2c018d1`](https://github.com/divyangchauhan/Pramana/commit/2c018d107553ed9c176c654231c897eb6abbae9c) over **3 independent runs** of `phase1/anthropic:claude-opus-4-8@medium`.

This is the reference point for later phases. A refactor is a regression if it drops below the observed true-positive floor, or raises the negative-control false-positive ceiling.

| Fixture | Known bugs | True positives (per run) | Confirmed (per run) | Stable |
|---|:---:|:---:|:---:|:---:|
| `bank-multi` | 3 | 2, 2, 2 | 2, 2, 2 | ✅ |
| `delegatecall-module` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `reentrancy-vault` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `reentrancy-vault-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `signature-replay-vault` | 3 | 2, 2, 2 | 2, 2, 2 | ✅ |
| `tx-origin-wallet` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `unchecked-overflow-token` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `unchecked-send-payouts` | 2 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `unprotected-owner` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `weak-randomness-lottery` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |

## Headline

- **True positives:** 11 / 14 known bugs (mean 11.0) across 3 runs
- **Negative-control false positives:** 0, 0, 0 confirmed per run; 0, 0, 0 with a passing PoC
- **Run-to-run stability:** identical results across all runs

## Regression gate for later phases

- True positives must not fall below **11**.
- Negative-control false positives must not exceed **0** confirmed / **0** proven.

Reproduce with:

```bash
uv run python -m pramana.eval.harness --provider anthropic --pipeline phase1 \
    --json runs/run-1.json --report-dir runs/reports-1
```
