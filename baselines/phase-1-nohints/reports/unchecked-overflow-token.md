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
- **Hypothesis:** Call batchTransfer([addrA, addrB], 2**255) from any account with zero balance: the unchecked multiplication receivers.length * amount = 2 * 2**255 wraps to 0, so the require(balanceOf[msg.sender] >= 0) passes and balanceOf[msg.sender] -= 0 costs nothing, while the loop credits addrA and addrB 2**255 tokens each — minting tokens from nothing and breaking supply invariants.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: attacker with 0 balance called batchTransfer([addrA, addrB], 2**255). The unchecked total = 2 * 2**255 wraps to 0, so require(balanceOf[msg.sender] >= 0) passes and balanceOf[msg.sender] -= 0 is free, while the loop credits addrA and addrB 2**255 each. Asserted balanceOf(addrA)==2**255, balanceOf(addrB)==2**255, balanceOf(attacker)==0 — tokens minted from nothing, breaking supply invariant.

## Needs human review

None.
