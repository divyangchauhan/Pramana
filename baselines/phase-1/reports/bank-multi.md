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
- **Location:** withdraw() L27-33
- **Hypothesis:** An attacker deploys a contract that calls deposit() with some ETH, then calls withdraw(); its receive/fallback re-enters withdraw() before balances[msg.sender]=0 executes at L32, repeatedly receiving bal each time and draining ETH deposited by other users.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC PASSED. withdraw() sends ETH via msg.sender.call before zeroing balances[msg.sender]. Attacker deposited 1 ETH into a bank holding 5 ETH from Alice/Bob, then re-entered withdraw() from its receive() until the bank was empty. Final asserts held: attacker balance == 6 ether (started with 1), bank balance == 0 — 5 ETH of other users' funds stolen.

### F-002 — access-control (critical)

- **Contract:** `src/Bank.sol`
- **Location:** setAdmin() L36-38
- **Hypothesis:** Any account calls setAdmin(attacker) with no authorization, becoming admin, then calls sweep(attacker) which passes require(msg.sender == admin) and transfers address(this).balance to the attacker, stealing all deposited ETH.
- **PoC:** `test/F-002.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** PoC passed: victim deposited 10 ETH; attacker called setAdmin(attacker) (no auth check), became admin (bank.admin()==attacker), then sweep(attacker) passed require(msg.sender==admin) and drained the contract. Asserted bank balance == 0 and attacker gained exactly 10 ETH. Test [PASS] testAccessControlSweep().

## Needs human review

None.
