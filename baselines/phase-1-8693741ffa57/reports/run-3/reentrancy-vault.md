# Audit report — reentrancy-vault

- **Config:** phase1/anthropic:claude-opus-4-8@medium
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — reentrancy (critical)

- **Contract:** `src/EtherStore.sol`
- **Location:** withdraw() L16-24
- **Hypothesis:** An attacker contract calls deposit() with 1 ETH, then calls withdraw(); its receive/fallback re-enters withdraw() before balances[msg.sender]=0 executes (L23), and since bal is still nonzero it drains the contract's entire ETH balance across repeated re-entrant calls.
- **PoC:** `test/F-001.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** withdraw() sends ETH via msg.sender.call before zeroing balances[msg.sender], enabling reentrancy. PoC: victim deposited 5 ETH, attacker deposited 1 ETH then re-entered withdraw() via receive(); test PASSED asserting store balance == 0 and attacker balance == 6 ETH (drained the victim's 5 ETH). Works against a normally deployed contract.

## Needs human review

None.
