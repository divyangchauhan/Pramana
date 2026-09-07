# Phase 2 paired corpus — Kimi K3 medium baseline

Captured **2026-08-11T10:51:38Z** at commit [`4994534`](https://github.com/divyangchauhan/Pramana/commit/4994534e95702409cd7b8e8549042d82a6d5abba) over **3 independent runs** of `phase2/kimi:kimi-k3@medium`.

This is the reference point for later phases. A refactor is a regression if it drops below the observed true-positive floor, or raises the negative-control false-positive ceiling.

| Fixture | Known bugs | True positives (per run) | Confirmed (per run) | Stable |
|---|:---:|:---:|:---:|:---:|
| `bank-multi` | 3 | 2, 2, 2 | 2, 2, 2 | ✅ |
| `bank-multi-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `delegatecall-module` | 1 | 1, 1, 0 | 1, 1, 0 | ⚠️ |
| `delegatecall-module-patched` | 0 *(control)* | 0, 0, 0 | 1, 0, 0 | ✅ |
| `reentrancy-vault` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `reentrancy-vault-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `signature-replay-vault` | 3 | 2, 2, 2 | 2, 3, 2 | ✅ |
| `signature-replay-vault-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `tx-origin-wallet` | 1 | 1, 1, 1 | 2, 1, 1 | ✅ |
| `tx-origin-wallet-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `unchecked-overflow-token` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `unchecked-overflow-token-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `unchecked-send-payouts` | 2 | 1, 2, 2 | 1, 2, 2 | ⚠️ |
| `unchecked-send-payouts-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `unprotected-owner` | 1 | 1, 1, 1 | 2, 1, 1 | ✅ |
| `unprotected-owner-patched` | 0 *(control)* | 0, 0, 0 | 0, 0, 0 | ✅ |
| `weak-randomness-lottery` | 1 | 1, 1, 1 | 1, 1, 1 | ✅ |
| `weak-randomness-lottery-patched` | 0 *(control)* | 0, 0, 0 | 2, 1, 1 | ✅ |

## Headline

- **True positives:** 11–12 / 14 known bugs (mean 11.33) across 3 runs
- **Negative-control false positives:** 3, 1, 1 confirmed per run; 3, 1, 1 with a passing PoC
- **Run-to-run stability:** varies between runs — compare against the range, not a single number

## Regression gate for later phases

- True positives must not fall below **11**.
- Negative-control false positives must not exceed **3** confirmed / **3** proven.

Reproduce with:

```bash
uv run python -m pramana.eval.harness --provider kimi --pipeline phase2 \
    --json runs/run-1.json --report-dir runs/reports-1
```
