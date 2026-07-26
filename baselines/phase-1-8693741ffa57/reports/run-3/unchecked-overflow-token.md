# Audit report — unchecked-overflow-token

- **Config:** phase1/anthropic:claude-opus-4-8@medium
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — integer-overflow (critical)

- **Contract:** `src/Token.sol`
- **Location:** batchTransfer() L17-30
- **Hypothesis:** Call batchTransfer([addrA, addrB], 2**255): the unchecked total = 2 * 2**255 wraps to 0, passing the balance require even with zero balance, then the loop credits each receiver 2**255 tokens, minting tokens out of thin air.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: attacker with 0 balance called batchTransfer([a,b], 2**255). The unchecked total = 2 * 2**255 wraps to 0, so the require(balanceOf[msg.sender] >= 0) passes and the subtraction is a no-op, yet the loop credits each receiver 2**255 tokens. Asserted balanceOf(a)==balanceOf(b)==2**255 while attacker balance stayed 0 — tokens minted from thin air.

## Needs human review

None.
