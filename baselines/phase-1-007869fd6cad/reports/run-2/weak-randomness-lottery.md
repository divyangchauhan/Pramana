# Audit report — weak-randomness-lottery

- **Config:** phase1/anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — weak-prng (high)

- **Contract:** `src/Lottery.sol`
- **Location:** enter() L12-22
- **Hypothesis:** An attacker deploys a wrapper contract that computes uint256(keccak256(abi.encodePacked(block.timestamp, block.prevrandao, address(this)))) % 10 in the same transaction and calls Lottery.enter{value: 1 ether}() only when that value equals 0 (reverting otherwise), guaranteeing draw==0 every time and draining the entire accumulated pot (address(this).balance) for the price of one ticket.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** forge test PASSED: attacker wrapper recomputed uint256(keccak256(abi.encodePacked(block.timestamp, block.prevrandao, address(this)))) % 10 in-transaction and only called enter{value:1 ether}() when it equals 0. Pot seeded with 9 ether was fully drained; attacker balance went from 1 ether to 10 ether (whole pot for one ticket). The PRNG is fully predictable/gameable because msg.sender equals the attacker contract address and block values are readable in the same tx.

## Needs human review

None.
