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
- **Location:** withdraw() L19-29
- **Hypothesis:** An attacker contract calls deposit() with 1 ETH, then calls withdraw(); the contract sends ETH via msg.sender.call before zeroing balances[msg.sender], so the attacker's fallback re-enters withdraw() which still reads the non-zero bal, repeating until the entire contract balance (including other depositors' funds) is drained.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC PASSED: Attacker deposited 1 ETH into a store holding 5 ETH from alice/bob, then via reentrant withdraw() calls from its receive() fallback drained the store to 0 and ended with 6 ETH (its 1 + 5 stolen). withdraw() sends ETH via msg.sender.call before setting balances[msg.sender]=0, allowing re-entry while bal is still non-zero. Assertions store.balance==0 and attacker.balance==6 ether both held.

## Needs human review

None.
