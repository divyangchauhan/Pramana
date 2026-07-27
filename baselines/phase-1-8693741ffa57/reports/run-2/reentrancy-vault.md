# Audit report — reentrancy-vault

- **Config:** phase1/anthropic:claude-opus-4-8@medium
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — reentrancy (critical)

- **Contract:** `src/EtherStore.sol`
- **Location:** withdraw() L16-24
- **Hypothesis:** An attacker contract deposits ETH, calls withdraw(), and in its receive() fallback re-enters withdraw() before balances[msg.sender]=0 runs, draining the entire contract's ETH since the balance is only zeroed after the external call.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC PASSED: attacker deposited 1 ETH into a vault seeded with 5 ETH from another user, then re-entered withdraw() via receive() before balances[msg.sender]=0 executes. Final asserts: store balance == 0 and attacker balance == 6 ether, confirming the entire vault was drained. Exploit works against a normally-deployed contract.

## Needs human review

None.
