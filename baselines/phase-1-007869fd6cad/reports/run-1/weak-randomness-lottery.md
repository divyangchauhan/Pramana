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
- **Hypothesis:** An attacker deploys a helper contract that computes uint256(keccak256(abi.encodePacked(block.timestamp, block.prevrandao, address(this)))) % 10 in the same transaction and only calls Lottery.enter{value: 1 ether}() when the result is 0 (otherwise reverts); because the draw depends solely on same-block/same-sender values known at call time, the on-chain draw always equals 0 when the call proceeds, so the attacker wins the entire pot (address(this).balance) on every committed attempt, draining all forfeited tickets.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: the Lottery draw = uint256(keccak256(block.timestamp, block.prevrandao, msg.sender)) % 10 is fully computable at call time. The attacker contract precomputes the draw with its own address as msg.sender and only calls enter{value:1 ether}() when draw==0. Run showed pot went from 10 ether to 0 and attacker netted +10 ether, draining all forfeited tickets. Weak-PRNG confirmed.

## Needs human review

None.
