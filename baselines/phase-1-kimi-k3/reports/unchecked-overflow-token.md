# Audit report — unchecked-overflow-token

- **Config:** phase1/kimi:kimi-k3
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — integer-overflow (critical)

- **Contract:** `src/Token.sol`
- **Location:** batchTransfer() L17-28 (unchecked multiplication at L21)
- **Hypothesis:** An attacker with a zero (or tiny) balance calls batchTransfer([attackerAddr1, attackerAddr2], 2**255); the unchecked computation total = 2 * 2**255 wraps to 0, so the require(balanceOf[msg.sender] >= 0) check passes, nothing is deducted from the sender, and each attacker-controlled receiver is credited 2**255 tokens, minting 2**256 tokens out of thin air and inflating real balances far beyond totalSupply.
- **PoC:** `test/F-001.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** Forge test PASSED. A zero-balance attacker called batchTransfer([recv1, recv2], 2**255); the unchecked total = 2 * 2**255 wrapped to 0, the balance check passed, the call completed ([Stop], no revert), and the test asserted: attacker balance stayed 0, recv1 and recv2 each hold exactly 2**255 (57896044618658097711785492504343953926634992332820282019728792003956564819968), and a single receiver balance exceeds totalSupply (1000 ether) while totalSupply was never updated. This is the classic batchTransfer integer-overflow mint: 2**256 tokens created out of thin air, completely breaking the token's supply invariant — critical.

## Needs human review

None.
