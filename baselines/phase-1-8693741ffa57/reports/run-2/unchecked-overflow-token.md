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
- **Location:** batchTransfer() L18-30
- **Hypothesis:** An attacker with (near) zero balance calls batchTransfer([addrA, addrB], 2**255) so that receivers.length*amount overflows in the unchecked block to 0, passing the balance require, while each receiver is credited 2**255 tokens — minting tokens out of thin air (classic batchOverflow).
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC PASSED: attacker with 0 balance called batchTransfer([a,b], 2**255). The unchecked block computed 2*2**255 == 0, passing require(balanceOf>=0), and each receiver was credited 2**255 tokens (asserted balanceOf(a)==balanceOf(b)==2**255). Tokens minted from thin air against a correctly deployed contract.

## Needs human review

None.
