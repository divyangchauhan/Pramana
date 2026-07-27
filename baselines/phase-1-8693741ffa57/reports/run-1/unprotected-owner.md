# Audit report — unprotected-owner

- **Config:** phase1/anthropic:claude-opus-4-8@medium
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — access-control (critical)

- **Contract:** `src/Wallet.sol`
- **Location:** initOwner() L18-20
- **Hypothesis:** Any attacker calls initOwner(attacker) to set themselves as owner, then calls withdraw() to drain the entire contract balance, because initOwner has no caller restriction and no initialized guard.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** initOwner() has no access control or initialized guard. PoC: deployer creates wallet and 10 ETH is deposited; attacker calls initOwner(attacker) to seize ownership, then withdraw() drains all 10 ETH. Test PASSED asserting attacker gained 10 ether and wallet balance is 0.

## Needs human review

None.
