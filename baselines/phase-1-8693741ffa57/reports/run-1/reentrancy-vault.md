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
- **Hypothesis:** An attacker contract deposits ETH, then calls withdraw(); the msg.sender.call at L20 re-enters withdraw() before balances[msg.sender]=0 at L23, so the still-nonzero balance passes the require and pays out again, letting the attacker drain the entire contract's ETH.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: attacker deposited 1 ETH into a vault seeded with 5 ETH from a victim, then re-entered withdraw() via receive() before balances[msg.sender]=0 executed. Final store balance == 0 and attacker balance == 6 ether, proving the entire vault was drained. Classic checks-effects-interactions violation (state zeroed after external call at L20).

## Needs human review

None.
