# Phase 2 paired corpus — GPT-5.5 medium via CLIProxy baseline

Captured **2026-08-11T18:38:49Z** at commit [`4994534`](https://github.com/divyangchauhan/Pramana/commit/4994534e95702409cd7b8e8549042d82a6d5abba) over **3 independent runs** of `phase2/openai-gateway:gpt-5.5@medium`.

This is the reference point for later phases. A refactor is a regression if it drops below the observed true-positive floor, or raises the negative-control false-positive ceiling.

| Fixture | Known bugs | True positives (per run) | Confirmed (per run) | Stable |
|---|:---:|:---:|:---:|:---:|
| `bank-multi` | 3 | 2, 2, 2 | 2, 2, 2 | ✅ |
| `bank-multi-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `delegatecall-module` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `delegatecall-module-patched` | 0 *(control)* | 0, 0, 0 | 0, 1, 0 | ✅ |
| `reentrancy-vault` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `reentrancy-vault-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `signature-replay-vault` | 3 | 2, 2, 2 | 2, 2, 2 | ✅ |
| `signature-replay-vault-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `tx-origin-wallet` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `tx-origin-wallet-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `unchecked-overflow-token` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `unchecked-overflow-token-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `unchecked-send-payouts` | 2 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `unchecked-send-payouts-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `unprotected-owner` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `unprotected-owner-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `weak-randomness-lottery` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `weak-randomness-lottery-patched` | 0 *(control)* | 0, 0, 0 | 2, 1, 1 | ✅ |

## Headline

- **True positives:** 11 / 14 known bugs (mean 11.0) across 3 runs
- **Negative-control false positives:** 2, 2, 1 confirmed per run; 2, 2, 1 with a passing PoC
- **Run-to-run stability:** identical results across all runs

## Regression gate for later phases

- True positives must not fall below **11**.
- Negative-control false positives must not exceed **2** confirmed / **2** proven.

Reproduce with:

```bash
uv run python -m pramana.eval.harness --provider openai-gateway --pipeline phase2 \
    --json runs/run-1.json --report-dir runs/reports-1
```
