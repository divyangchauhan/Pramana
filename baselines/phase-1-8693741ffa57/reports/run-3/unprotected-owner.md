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
- **Hypothesis:** Any attacker can call initOwner(attacker) to overwrite `owner` with their own address (no caller check, no initialized guard), then call withdraw() to drain the entire contract balance.
- **PoC:** `test/F-001.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** initOwner() has no caller check or initialized guard. PoC: deployer deploys Wallet and it holds 10 ETH; a distinct attacker calls initOwner(attacker), owner becomes attacker, then withdraw() sends the full 10 ETH to attacker. Test passed asserting attacker gained 10 ether and wallet balance is 0.

## Needs human review

None.
