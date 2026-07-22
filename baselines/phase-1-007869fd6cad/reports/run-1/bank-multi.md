# Audit report — bank-multi

- **Config:** phase1/anthropic:claude-opus-4-8
- **True positives:** 2 / 3 known bugs
- **Confirmed / PoC-verified:** 2 / 2

---

# Audit report

2 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — reentrancy (critical)

- **Contract:** `src/Bank.sol`
- **Location:** withdraw() L22-28
- **Hypothesis:** An attacker contract deposits ETH then calls withdraw(); the contract sends ETH via msg.sender.call before zeroing balances[msg.sender], so the attacker's receive/fallback re-enters withdraw() repeatedly and drains the entire contract balance before the state is updated.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: withdraw() sends ETH via msg.sender.call before zeroing balances[msg.sender]. Attacker deposited 1 ETH, then re-entered withdraw() from its receive() and drained the entire 6 ETH contract balance (5 ETH belonging to the victim). Asserted address(bank).balance == 0 and attacker balance == 6 ether after attack.

### F-002 — access-control (critical)

- **Contract:** `src/Bank.sol`
- **Location:** setAdmin(address) L31-33
- **Hypothesis:** Any user calls setAdmin(attacker) to become admin (no authorization check), then calls sweep(attacker) to transfer the entire contract balance to themselves.
- **PoC:** `test/F-002.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** PoC PASSED: setAdmin(address) has no authorization check. Victim deposited 10 ETH; an unrelated attacker called setAdmin(attacker) (bank.admin() became attacker) then sweep(attacker), draining the full 10 ETH to attacker (attacker.balance == 10 ether, contract balance == 0). Full contract fund loss by any caller.

## Needs human review

None.
