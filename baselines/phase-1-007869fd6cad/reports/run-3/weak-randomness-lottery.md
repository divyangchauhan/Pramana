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
- **Hypothesis:** An attacker deploys a contract that in one transaction recomputes draw = uint256(keccak256(abi.encodePacked(block.timestamp, block.prevrandao, address(this)))) % 10 and only calls Lottery.enter{value:1 ether}() when the result is 0 (reverting otherwise), guaranteeing draw==0 and receiving address(this).balance, thereby draining the entire accumulated pot with zero risk.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** testDrainPot() PASSED. The attacker contract precomputes draw = keccak256(block.timestamp, block.prevrandao, msg.sender) % 10 (msg.sender == the attacker's own address, which it fully controls/knows) and only calls enter{value:1 ether}() when draw==0. On that block Lottery.enter forwards address(this).balance to the attacker: pot of 5 ether + 1 ether ticket = 6 ether all drained (lottery balance 0, attacker balance 6 ether). The on-chain keccak PRNG over block/tx-controlled inputs is fully predictable, so the 1-in-10 draw can be won deterministically with zero risk.

## Needs human review

None.
