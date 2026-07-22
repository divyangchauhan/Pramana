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
- **Hypothesis:** An attacker with zero (or minimal) balance calls batchTransfer([addrA, addrB], 2**255); the unchecked multiplication receivers.length * amount = 2*2**255 overflows to 0, so the balance require passes and msg.sender's balance is decremented by 0, yet each of the two receivers is credited 2**255 tokens, minting tokens from nothing and breaking the supply invariant.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC PASSED. Attacker (0 balance) called batchTransfer([addrA, addrB], 2**255). The unchecked multiplication receivers.length*amount = 2*2**255 overflows to 0, so the balance require passes and msg.sender is decremented by 0. Assertions confirmed: attacker balance stayed 0, while balanceOf[addrA]==2**255 and balanceOf[addrB]==2**255 — tokens minted from nothing, breaking the supply invariant.

## Needs human review

None.
