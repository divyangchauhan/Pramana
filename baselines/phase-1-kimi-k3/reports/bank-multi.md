# Audit report — bank-multi

- **Config:** phase1/kimi:kimi-k3
- **True positives:** 2 / 2 known bugs
- **Confirmed / PoC-verified:** 3 / 3

---

# Audit report

3 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — reentrancy (critical)

- **Contract:** `src/Bank.sol`
- **Location:** withdraw() L22-28
- **Hypothesis:** An attacker contract deposits 1 ETH via deposit(), then calls withdraw(); its receive() hook reenters withdraw() repeatedly, and because balances[msg.sender] is only zeroed after the external call, each reentry passes the bal > 0 check and pays out another 1 ETH, draining other depositors' funds (e.g. 10 ETH extracted for 1 ETH deposited).
- **PoC:** `test/F-001.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** PoC testReentrancyDrain PASSED. The Bank.withdraw() at L22-28 performs the external call msg.sender.call{value: bal}("") before zeroing balances[msg.sender], a classic checks-effects-interactions violation. The Attacker contract deposited 1 ETH, called withdraw(), and its receive() hook reentered withdraw() 9 times while the balance was still non-zero. Assertions confirmed: address(bank).balance == 0 (bank fully drained from 10 ETH to 0) and address(attacker).balance == 10 ether (10 ETH extracted for 1 ETH deposited), and the honest depositor's subsequent withdraw() reverted because the bank was empty. The claim of draining other depositors' funds is fully demonstrated.

### F-002 — access-control (critical)

- **Contract:** `src/Bank.sol`
- **Location:** setAdmin() L30-33
- **Hypothesis:** Any EOA or contract calls setAdmin(attacker) — which has no msg.sender == admin check — and then calls sweep(attacker) to transfer the entire contract ETH balance to themselves, stealing all deposits.
- **PoC:** `test/F-002.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** Forge run passed: an attacker with no prior privileges called Bank.setAdmin(attacker) — which contains no msg.sender == admin check — and became admin (assertEq(bank.admin(), attacker) passed), then called sweep(attacker), draining the contract. Final assertions held: address(bank).balance == 0 and attacker received the full 10 ether deposited by the victim. Test [PASS] testExploit() (gas: 60971).

### F-003 — missing-zero-check (medium)

- **Contract:** `src/Bank.sol`
- **Location:** sweep() L35-39
- **Hypothesis:** If the admin calls sweep(address(0)) by mistake, `to.transfer(address(this).balance)` succeeds (sending ETH to the zero address does not revert) and the entire contract balance is permanently burned.
- **PoC:** `test/F-003.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** forge test PASSED: testSweepToZeroBurnsFunds() — Bank funded with 10 ether, admin called sweep(payable(address(0))); the call did not revert, assertEq showed address(bank).balance == 0 and address(0).balance increased by exactly 10 ether, proving the full balance was permanently burned. sweep() (src/Bank.sol L35-39) has no zero-address check on `to`, and .transfer to address(0) succeeds at the EVM level. Severity is medium (not higher) because it requires a trusted admin input mistake rather than an external attack.

## Needs human review

None.
