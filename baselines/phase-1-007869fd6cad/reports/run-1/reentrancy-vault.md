# Audit report — reentrancy-vault

- **Config:** phase1/anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — reentrancy (critical)

- **Contract:** `src/EtherStore.sol`
- **Location:** withdraw() L16-24
- **Hypothesis:** An attacker contract calls deposit() with 1 ETH, then calls withdraw(); its receive/fallback re-enters withdraw() before balances[msg.sender]=0 executes (L23), and since bal is re-read as still nonzero, it repeatedly pulls 1 ETH per re-entry until the contract's entire ETH balance (including other users' deposits) is drained.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** withdraw() performs the external call `msg.sender.call{value: bal}` before zeroing `balances[msg.sender]`. PoC: Alice deposits 5 ETH; attacker deposits 1 ETH and re-enters withdraw() via receive() until the store is empty. Test PASSED with store balance == 0 and attacker balance == 6 ETH, proving the attacker stole 5 ETH of other users' deposits.

## Needs human review

None.
