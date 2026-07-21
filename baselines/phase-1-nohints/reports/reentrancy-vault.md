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
- **Hypothesis:** An attacker contract deposits ETH via deposit(), then calls withdraw(); its receive/fallback re-enters withdraw() before balances[msg.sender]=0 executes, and since bal is still the original nonzero balance each nested call sends ETH again, draining the entire contract balance beyond the attacker's deposit.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** withdraw() sends ETH via msg.sender.call before zeroing balances[msg.sender], enabling reentrancy. PoC: attacker deposited 1 ETH into a store holding 6 ETH (5 ETH from a victim), then re-entered withdraw() from receive(). Test PASSED with store balance == 0 and attacker balance == 6 ETH, proving the entire contract balance was drained beyond the attacker's own deposit.

## Needs human review

None.
