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
- **Hypothesis:** Call batchTransfer([a,b], 2**255): the unchecked total = 2 * 2**255 overflows to 0, passing the balance require even with zero balance, then each receiver gets credited 2**255, minting tokens out of thin air (classic batchOverflow).
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC PASSED: an attacker with zero balance called batchTransfer([a,b], 2**255). The unchecked total = 2 * 2**255 overflows to 0, so the require(balanceOf >= total) passes, and each receiver was credited 2**255 tokens (asserted balanceOf(a)==balanceOf(b)==2**255 while attacker balance stayed 0). Classic batchOverflow, works on a correctly deployed instance.

## Needs human review

None.
