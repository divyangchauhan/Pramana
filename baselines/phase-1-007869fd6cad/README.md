# Phase 1 (corpus 007869fd6cad) baseline

Captured **2026-07-22T08:56:12Z** at commit [`ec2e920`](https://github.com/divyangchauhan/Pramana/commit/ec2e9208680a7fe2bd140c4aba4f00de88cadd96) over **3 independent runs** of `phase1/anthropic:claude-opus-4-8`.

This is the reference point for later phases. A refactor is a regression if it drops below the observed true-positive floor, or raises the negative-control false-positive ceiling.

| Fixture | Known bugs | True positives (per run) | Confirmed (per run) | Stable |
|---|:---:|:---:|:---:|:---:|
| `bank-multi` | 3 | 2, 2, 2 | 2, 2, 2 | ✅ |
| `delegatecall-module` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `reentrancy-vault` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `reentrancy-vault-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `signature-replay-vault` | 1 | 1, 1, 1 | 2, 2, 2 | ✅ |
| `tx-origin-wallet` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `unchecked-overflow-token` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `unchecked-send-payouts` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `unprotected-owner` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `weak-randomness-lottery` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |

## Headline

- **True positives:** 10 / 11 known bugs (mean 10.0) across 3 runs
- **Negative-control false positives:** 0, 0, 0 confirmed per run; 0, 0, 0 with a passing PoC
- **Run-to-run stability:** identical results across all runs

## Regression gate for later phases

- True positives must not fall below **10**.
- Negative-control false positives must not exceed **0** confirmed / **0** proven.

Reproduce with:

```bash
uv run python -m pramana.eval.harness --provider anthropic --pipeline phase1 \
    --json runs/run-1.json --report-dir runs/reports-1
```
