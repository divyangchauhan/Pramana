# Audit report — unprotected-owner

- **Config:** phase1/anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — access-control (critical)

- **Contract:** `src/Wallet.sol`
- **Location:** initOwner() L18-20
- **Hypothesis:** Any address can call initOwner(attacker) to overwrite owner (no caller check, no initialized guard), then call withdraw() to drain the entire contract balance.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC PASSED: attacker (0xBEEF) called initOwner(attacker) with no caller check and no initialized guard, seizing ownership (wallet.owner() == attacker), then called withdraw() draining the full 10 ether balance. Assertions confirmed wallet balance == 0 and attacker gained 10 ether.

## Needs human review

None.
