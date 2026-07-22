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
- **Hypothesis:** An attacker contract deposits some ETH via deposit(), then calls withdraw(); its receive/fallback re-enters withdraw() during the msg.sender.call{value: bal}() at L20 (before balances[msg.sender]=0 at L23), so bal is still nonzero on each re-entry and the attacker repeatedly withdraws, draining the entire contract balance including other users' deposits.
- **PoC:** `test/F-001.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** PoC passed. withdraw() makes the external call before zeroing balances, allowing reentrancy. Attacker deposited 1 ETH into a store holding 10 ETH from Alice/Bob, then re-entered withdraw() via receive() before balances[msg.sender]=0. The trace shows nested withdraw() calls draining the vault: final store balance = 0 and attacker balance = 12 ETH (1 own + 11 stolen from other users). All assertions passed.

## Needs human review

None.
