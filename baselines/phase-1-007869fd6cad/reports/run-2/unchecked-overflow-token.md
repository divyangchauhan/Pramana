# Audit report — unchecked-overflow-token

- **Config:** phase1/anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — integer-overflow (critical)

- **Contract:** `src/Token.sol`
- **Location:** batchTransfer() L18-30
- **Hypothesis:** An attacker with zero balance calls batchTransfer([a,b], 2**255): the unchecked `total = receivers.length * amount` overflows to 0, the balance check passes, msg.sender's balance is reduced by 0, and each receiver is credited 2**255 tokens, minting tokens from nothing and breaking the totalSupply invariant.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: attacker with 0 balance called batchTransfer([a,b], 2**255). The unchecked `total = 2 * 2**255` overflows to 0, so the balance check passes and msg.sender's balance is decremented by 0. The checked loop then credits each receiver 2**255. Asserts confirmed balanceOf(a)==2**255, balanceOf(b)==2**255, attacker==0 — tokens minted from nothing, totalSupply invariant broken.

## Needs human review

None.
