# Audit report — weak-randomness-lottery

- **Config:** phase1/anthropic:claude-opus-4-8@medium
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — weak-prng (high)

- **Contract:** `src/Lottery.sol`
- **Location:** enter() L12-22
- **Hypothesis:** An attacker deploys a contract that computes uint256(keccak256(abi.encodePacked(block.timestamp, block.prevrandao, address(this)))) % 10 in the same transaction before calling enter(), reverting if the result is not 0, thereby only ever paying the ticket when the draw is guaranteed to win and draining the entire pot of losers' forfeited tickets.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** The draw is computed from block.timestamp, block.prevrandao and msg.sender — all values an attacker contract can read in the same transaction before calling enter(). The PoC deploys an attacker that recomputes the identical keccak256%10 formula and only calls enter() when draw==0, reverting otherwise, so it never risks a losing ticket. On a winning block the attacker receives address(this).balance. Test PASSED: attacker balance became 10 ether (9 ether of forfeited pot + its own 1 ether ticket) and the Lottery balance dropped to 0, demonstrating the pot is drained via weak PRNG prediction.

## Needs human review

None.
