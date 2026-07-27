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
- **Hypothesis:** An attacker deploys a contract that recomputes uint256(keccak256(abi.encodePacked(block.timestamp, block.prevrandao, address(this)))) % 10 == 0 in the same transaction and only calls Lottery.enter() when the result is 0, guaranteeing a win and draining the entire pot (address(this).balance) risk-free.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** Test PASSED. An attacker contract recomputes uint256(keccak256(abi.encodePacked(block.timestamp, block.prevrandao, address(this)))) % 10 in the same tx and only calls enter() when it equals 0. In the PoC the attacker paid a single 1 ether ticket and drained the full 10 ether pot (attacker balance 10 ether, lottery balance 0). The on-chain PRNG is fully predictable within the transaction, so wins are guaranteed and risk-free.

## Needs human review

None.
