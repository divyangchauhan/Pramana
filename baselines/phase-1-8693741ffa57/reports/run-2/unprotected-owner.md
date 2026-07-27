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
- **Hypothesis:** Any external account can call initOwner(attacker) to overwrite `owner`, then call withdraw() to drain the entire contract balance, because initOwner has no caller restriction and never checks the `initialized` flag.
- **PoC:** `test/F-001.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** PoC PASSED: after deployer deploys and funds the wallet with 10 ether, an unrelated attacker EOA calls initOwner(attacker) (no caller restriction, no initialized check), becoming owner, then calls withdraw() draining all 10 ether. Asserts confirm attacker.balance increased by 10 ether and wallet balance is 0.

## Needs human review

None.
