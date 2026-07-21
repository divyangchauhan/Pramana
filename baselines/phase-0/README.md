# Phase 0 baseline

Captured **2026-07-21T09:44:28Z** at commit [`10fbec0`](https://github.com/divyangchauhan/Pramana/commit/10fbec02b1e767e2475cd095e4b8f63934669d9c) over **3 independent runs** of `anthropic:claude-opus-4-8`.

This is the reference point for later phases. A refactor is a regression if it drops below the observed true-positive floor, or raises the negative-control false-positive ceiling.

| Fixture | Known bugs | True positives (per run) | Confirmed (per run) | Stable |
|---|:---:|:---:|:---:|:---:|
| `bank-multi` | 2 | 2, 2, 2 | 2, 2, 2 | ✅ |
| `reentrancy-vault` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `reentrancy-vault-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `tx-origin-wallet` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `unchecked-overflow-token` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `unprotected-owner` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |

## Headline

- **True positives:** 6 / 6 known bugs (mean 6.0) across 3 runs
- **Negative-control false positives:** 0, 0, 0 confirmed per run; 0, 0, 0 with a passing PoC
- **Run-to-run stability:** identical results across all runs

## Regression gate for later phases

- True positives must not fall below **6**.
- Negative-control false positives must not exceed **0** confirmed / **0** proven.

Reproduce with:

```bash
uv run python -m pramana.eval.harness --provider anthropic \
    --json runs/run-1.json --report-dir runs/reports-1
```
