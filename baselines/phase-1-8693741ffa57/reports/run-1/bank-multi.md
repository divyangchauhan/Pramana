# Audit report — bank-multi

- **Config:** phase1/anthropic:claude-opus-4-8@medium
- **True positives:** 2 / 3 known bugs
- **Confirmed / PoC-verified:** 2 / 2

---

# Audit report

2 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — reentrancy (critical)

- **Contract:** `src/Bank.sol`
- **Location:** withdraw() L22-28
- **Hypothesis:** A malicious contract deposits, calls withdraw(), and in its receive/fallback re-enters withdraw() before balances[msg.sender]=0 runs, draining more ETH than its balance because the external call at L25 precedes the state update at L27.
- **PoC:** `test/F-001.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** PoC PASSED: attacker deposited 1 ETH, re-entered withdraw() in receive() before balances[msg.sender]=0 executed, draining the full contract balance. Attacker ended with 7 ETH (its 1 ETH + victim's 5 ETH + prior), bank balance 0. External call at L25 precedes state update at L27 with no reentrancy guard.

### F-002 — access-control (critical)

- **Contract:** `src/Bank.sol`
- **Location:** setAdmin() L31-33
- **Hypothesis:** Any attacker calls setAdmin(attacker) with no authorization, becoming admin, then calls sweep(attacker) to transfer the entire contract balance to themselves.
- **PoC:** `test/F-002.t.sol` (proven in 3 executed forge run(s))
- **Evidence:** setAdmin() has no authorization check. PoC: victim deposited 10 ETH; attacker called setAdmin(attacker) (bank.admin() == attacker asserted), then sweep(attacker), draining the full 10 ETH balance to the attacker (attacker.balance == 10 ether, bank balance == 0). Test PASSED against a normally deployed contract (deployer = separate address).

## Needs human review

None.
