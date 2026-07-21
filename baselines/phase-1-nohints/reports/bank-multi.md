# Audit report — bank-multi

- **Config:** phase1/anthropic:claude-opus-4-8
- **True positives:** 2 / 2 known bugs
- **Confirmed / PoC-verified:** 2 / 2

---

# Audit report

2 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — reentrancy (critical)

- **Contract:** `src/Bank.sol`
- **Location:** withdraw() L22-28
- **Hypothesis:** An attacker contract deposits ETH, calls withdraw(), and in its receive/fallback re-enters withdraw() before balances[msg.sender]=0 executes (the external call at L25 precedes the state write at L27), draining the entire contract balance across repeated re-entrant calls.
- **PoC:** `test/F-001.t.sol` (proven in 3 executed forge run(s))
- **Evidence:** PoC PASSED. withdraw() at L25 performs the external call (msg.sender.call{value: bal}) before zeroing balances[msg.sender] at L27. The Attacker deposited 1 ETH and re-entered withdraw() from its receive() 6 times. Trace shows repeated Bank::withdraw -> Attacker::receive -> Bank::withdraw nesting. Result: address(bank).balance == 0 (fully drained) while attacker balance rose from 1 ETH to 7 ETH (>=6 ETH), stealing the victim's 5 ETH deposit. Classic checks-effects-interactions violation / reentrancy drain.

### F-002 — access-control (critical)

- **Contract:** `src/Bank.sol`
- **Location:** setAdmin(address) L31-33
- **Hypothesis:** Any external account calls setAdmin(attackerAddress) with no authorization check, becoming admin, then calls sweep(attacker) to transfer the entire contract balance to itself.
- **PoC:** `test/F-002.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** setAdmin(address) at L31-33 has no authorization check. PoC: attacker (0xBAD) called setAdmin(attacker) becoming admin, then sweep(attacker), draining the victim's 10 ETH deposit. Test PASSED: attacker.balance increased by 10 ether and bank balance went to 0.

## Needs human review

None.
