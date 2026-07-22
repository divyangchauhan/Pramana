# Audit report — tx-origin-wallet

- **Config:** phase1/anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — tx-origin (high)

- **Contract:** `src/TxOriginWallet.sol`
- **Location:** transferTo() L15-19
- **Hypothesis:** An attacker deploys a malicious contract and tricks the owner into calling it (e.g. a fallback/any function); that contract calls TxOriginWallet.transferTo(attacker, balance), where tx.origin equals owner so the require passes, draining all wallet funds to the attacker.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** transferTo() authorizes on tx.origin == owner instead of msg.sender. PoC: owner deploys wallet funded with 10 ETH, then is tricked into calling Attacker.claimReward() (vm.prank sets both msg.sender and tx.origin to owner). The attacker contract calls wallet.transferTo(evil, balance); the require(tx.origin == owner) passes because the owner initiated the transaction. Test PASSED: wallet balance drained to 0 and attacker's address (evil) received the full 10 ether.

## Needs human review

None.
