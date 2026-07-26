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
- **Hypothesis:** An attacker contract deposits ETH, calls withdraw(), and in its receive/fallback re-enters withdraw() before balances[msg.sender]=0 executes, draining the contract because the external call precedes the state update.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: withdraw() sends ETH via msg.sender.call BEFORE zeroing balances[msg.sender]. Attacker deposited 1 ETH into a bank holding 6 ETH total (5 ETH victim funds), re-entered withdraw() from receive(), and drained the full contract: final bank balance 0, attacker balance 6 ether. Classic checks-effects-interactions violation on a correctly deployed instance.

### F-002 — access-control (critical)

- **Contract:** `src/Bank.sol`
- **Location:** setAdmin(address) L31-33
- **Hypothesis:** Any arbitrary caller invokes setAdmin(attacker) to become admin, then calls sweep(attacker) to transfer the entire contract balance to themselves.
- **PoC:** `test/F-002.t.sol` (proven in 3 executed forge run(s))
- **Evidence:** setAdmin(address) has no access control. PoC: victim deposits 10 ETH; an arbitrary attacker (not the deployer) calls setAdmin(attacker) becoming admin, then sweep(attacker) drains the full 10 ETH. Test PASSED with attacker.balance == 10 ether and contract balance == 0, against a correctly deployed instance (admin initialized to deployer in constructor).

## Needs human review

None.
