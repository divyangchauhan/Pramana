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
- **Hypothesis:** An attacker contract calls deposit() with 1 ETH, then calls withdraw(); its receive/fallback re-enters withdraw() before balances[msg.sender]=0 executes, and since bal is re-read as still 1 ETH each time, it drains the entire contract balance across nested calls.
- **PoC:** `test/F-001.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** forge test PASSED. withdraw() sends ETH via msg.sender.call BEFORE zeroing balances[msg.sender], enabling reentrancy. Attacker deposited 1 ETH, re-entered withdraw() through receive() while bal was still re-read as 1 ETH each nested call, draining the bank from 6 ETH to 0. Attacker ended with 7 ETH (own 1 ETH + victim's 5 ETH stolen). Victim's later withdraw() reverts (no funds), confirming unrecoverable theft of all depositor funds.

### F-002 — access-control (critical)

- **Contract:** `src/Bank.sol`
- **Location:** setAdmin(address) L31-33
- **Hypothesis:** Any account calls setAdmin(attacker) — there is no authorization check — becoming admin, then calls sweep(attacker) to transfer the entire contract balance to itself.
- **PoC:** `test/F-002.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** setAdmin(address) has no authorization check. PoC (testExploit PASSED): attacker calls setAdmin(attacker) becoming admin (bank.admin()==attacker), then sweep(attacker) transfers the entire 10 ETH deposited by victim to attacker — bank balance 0, attacker balance 10 ether asserted.

## Needs human review

None.
