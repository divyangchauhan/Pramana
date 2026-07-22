# Audit report — reentrancy-vault

- **Config:** phase1/anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — reentrancy (critical)

- **Contract:** `src/EtherStore.sol`
- **Location:** withdraw() L16-24
- **Hypothesis:** An attacker contract deposits ETH via deposit(), then calls withdraw(); its receive/fallback re-enters withdraw() before balances[msg.sender]=0 executes, draining the entire contract balance because bal is re-read as still nonzero on each nested call.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: withdraw() sends ETH via msg.sender.call before zeroing balances[msg.sender]. Attacker deposited 1 ETH, re-entered withdraw() from receive(), and drained the store from 6 ETH to 0, ending with 6 ETH (stealing Alice's 5 ETH). Test asserted store balance == 0 and attacker balance == 6 ether, both held.

## Needs human review

None.
