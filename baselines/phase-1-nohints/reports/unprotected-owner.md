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
- **Hypothesis:** Any attacker calls initOwner(attackerAddress) to overwrite owner (no auth check, no initialized guard), then calls withdraw() to drain the entire contract balance to themselves.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** initOwner() has no access control and no initialized guard. PoC: deployer creates Wallet funded with 10 ether; attacker calls initOwner(attacker) taking ownership then withdraw(), draining the full 10 ether to themselves. Test PASSED: wallet balance 0, attacker balance +10 ether.

## Needs human review

None.
