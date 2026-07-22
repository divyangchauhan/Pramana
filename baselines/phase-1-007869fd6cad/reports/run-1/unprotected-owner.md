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
- **Hypothesis:** Any attacker calls initOwner(attacker) to overwrite the owner state variable (no msg.sender check, no use of the initialized flag), then calls withdraw() to drain the entire contract balance to themselves.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: initOwner() has no msg.sender check and ignores the initialized flag. Attacker (0xBEEF) called initOwner(attacker), took ownership (owner==attacker), then withdraw() drained the full 10 ether balance. Asserted wallet balance == 0 and attacker gained 10 ether.

## Needs human review

None.
