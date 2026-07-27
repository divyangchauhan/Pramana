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
- **Hypothesis:** An attacker deploys a contract that computes draw = keccak256(block.timestamp, block.prevrandao, address(this)) % 10 in the same transaction and calls Lottery.enter{value:1 ether}() only when the result is 0 (reverting otherwise), guaranteeing it wins the entire pot every time and draining all accumulated losing tickets.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: draw is derived purely from on-chain values (block.timestamp, block.prevrandao, msg.sender) that a calling contract can read in the same transaction. Attacker precomputes the identical keccak256 result and only calls enter() when draw==0, guaranteeing a win. Test showed a 9 ether seeded pot drained: attacker balance ended at 10 ether and lottery balance at 0.

## Needs human review

None.
