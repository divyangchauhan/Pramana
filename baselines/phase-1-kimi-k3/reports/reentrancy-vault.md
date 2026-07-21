# Audit report — reentrancy-vault

- **Config:** phase1/kimi:kimi-k3
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — reentrancy (critical)

- **Contract:** `src/EtherStore.sol`
- **Location:** withdraw() L16-24
- **Hypothesis:** An attacker contract deposits 1 ETH via deposit(), then calls withdraw(); EtherStore sends the ETH with msg.sender.call before zeroing balances[msg.sender], so the attacker's receive() function reenters withdraw(), passes the require(bal > 0) check (balance still nonzero), and receives another payout — repeating until the contract's entire ETH balance (including other users' deposits) is drained, with balances[msg.sender] = 0 only executing after the call stack unwinds.
- **PoC:** `test/F-001.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** Forge test testReentrancyDrain PASSED. EtherStore.withdraw() sends ETH via msg.sender.call before zeroing balances[msg.sender], so the Attacker contract's receive() reentered withdraw() 9 times (visible in the execution trace as nested EtherStore::withdraw -> Attacker::receive chains), passed the require(bal > 0) check each time since the balance was only zeroed after the call stack unwound, and drained the entire vault. Assertions proved: address(store).balance == 0 (vault fully drained) and the attacker ended with 11 ETH after depositing only 1 ETH (stealing the 9 ETH deposited by victims alice and bob).

## Needs human review

None.
