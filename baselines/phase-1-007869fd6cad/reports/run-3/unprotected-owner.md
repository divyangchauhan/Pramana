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
- **Hypothesis:** An attacker calls initOwner(attackerAddress) to overwrite `owner`, then calls withdraw() to transfer the entire contract balance to themselves.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** initOwner() has no access control (no onlyOwner, no initialized guard). PoC: attacker called initOwner(attacker) becoming owner, then withdraw() drained the full 10 ether. Test PASSED: attacker.balance gained 10 ether, wallet balance == 0.

## Needs human review

None.
