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
- **Location:** batchTransfer() L17-30
- **Hypothesis:** An attacker calls batchTransfer([addrA, addrB], 2**255): the unchecked multiplication total = 2 * 2**255 wraps to 0, the require(balanceOf >= 0) passes trivially, msg.sender's balance is debited by 0, yet each receiver's balance is credited by 2**255 in the loop, minting tokens out of thin air (balances exceed totalSupply).
- **PoC:** `test/F-001.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** batchTransfer([addrA, addrB], 2**255) executed: total = 2 * 2**255 wrapped to 0 in the unchecked block, the require(balanceOf >= 0) passed, attacker balance stayed at 1000 (debited 0), yet both addrA and addrB were each credited 5.789e76 (2**255) tokens — each far exceeding totalSupply of 1000. Test PASSED asserting sender balance unchanged, each receiver minted 2**255, and each receiver's balance > totalSupply. Unlimited token minting from thin air.

## Needs human review

None.
