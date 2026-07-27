# Audit report — bank-multi

- **Config:** phase1/anthropic:claude-opus-4-8@medium
- **True positives:** 2 / 3 known bugs
- **Confirmed / PoC-verified:** 2 / 2

---

# Audit report

2 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — reentrancy (high)

- **Contract:** `src/Bank.sol`
- **Location:** withdraw() L22-28
- **Hypothesis:** An attacker contract deposits ETH, calls withdraw(), and in its receive/fallback re-enters withdraw() before balances[msg.sender]=0 executes, repeatedly draining the contract's entire ETH balance.
- **PoC:** `test/F-001.t.sol` (proven in 4 executed forge run(s))
- **Evidence:** PoC passed: Bank funded with 10 ether by alice+bob. Attacker deposits 1 ether, calls withdraw(), and re-enters via receive() before balances[msg.sender]=0 executes (trace shows nested Bank::withdraw() -> Attacker::receive() calls). Bank balance drained from 10 ether to 0; attacker net-gained 11 ether (own 1 + 10 stolen). withdraw() at L22-28 does the external call before zeroing the balance — classic CEI violation, exploitable against a correctly deployed instance.

### F-002 — access-control (critical)

- **Contract:** `src/Bank.sol`
- **Location:** setAdmin(address) L31-33
- **Hypothesis:** Any address can call setAdmin(attacker) to become admin, then call sweep(attacker) to transfer the contract's entire balance to itself.
- **PoC:** `test/F-002.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** setAdmin(address) has no access control. PoC: victim deposits 10 ETH; attacker calls setAdmin(attacker) then sweep(attacker); test PASSED with bank.admin()==attacker, bank balance 0, attacker gained 10 ETH. Contract deployed normally (owner as deployer).

## Needs human review

None.
