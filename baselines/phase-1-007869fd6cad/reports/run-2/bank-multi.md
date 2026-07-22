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
- **Hypothesis:** An attacker contract calls deposit() with 1 ETH, then calls withdraw(); its receive/fallback re-enters withdraw() before balances[msg.sender]=0 executes, and because balances is still non-zero it repeatedly drains the contract's entire ETH balance until funds are exhausted.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC PASSED: withdraw() sends ETH via msg.sender.call BEFORE zeroing balances[msg.sender], allowing a reentrant attacker to re-enter withdraw() from its receive() while its balance is still non-zero. Attacker deposited 1 ETH and drained the contract to 0, ending with 7 ETH (1 own + 5 ETH victim funds, plus its own returned deposit). Logs: attacker balance 7e18, bank balance 0.

### F-002 — access-control (critical)

- **Contract:** `src/Bank.sol`
- **Location:** setAdmin(address) L31-33
- **Hypothesis:** Any external caller invokes setAdmin(attacker) to seize the admin role, then calls sweep(attacker) which passes the require(msg.sender==admin) check and transfers the contract's entire balance to the attacker.
- **PoC:** `test/F-002.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** setAdmin(address) has no access control (no owner/admin check). PoC: attacker (0xBAD) called setAdmin(attacker) making bank.admin()==attacker, then called sweep(attacker) passing require(msg.sender==admin), draining the 10 ETH deposited by a victim. After exploit address(bank).balance==0 and attacker.balance==10 ether. Test [PASS] testAttackerSeizesAdminAndSweeps.

## Needs human review

None.
