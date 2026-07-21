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
- **Location:** batchTransfer() L19-32
- **Hypothesis:** Call batchTransfer([addrA, addrB], 2**255): inside the unchecked block total = 2 * 2**255 wraps to 0, the require(balanceOf[msg.sender] >= 0) passes, msg.sender's balance decreases by 0, and each of addrA and addrB receives amount (2**255) tokens minted from nothing, breaking the totalSupply invariant.
- **PoC:** `test/F-001.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** PoC PASSED. Attacker (balance 0) called batchTransfer([addrA, addrB], 2**255). The unchecked block computed total = 2 * 2**255 = 0, require(balanceOf >= 0) passed, attacker balance stayed 0, and each receiver received 2**255 (5.789e76) tokens minted from nothing. Asserted balanceOf(addrA) and balanceOf(addrB) each == 2**255 and each > totalSupply (1000e18), breaking the supply invariant.

## Needs human review

None.
