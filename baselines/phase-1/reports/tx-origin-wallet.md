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
- **Location:** transferTo() L16-21
- **Hypothesis:** An attacker deploys a phishing contract and tricks the owner (an EOA) into sending any transaction to it; that contract calls TxOriginWallet.transferTo(attacker, wallet.balance), and because tx.origin equals owner the require passes and all ETH is drained to the attacker.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: owner (tx.origin) was tricked into calling attacker's Phish.claimReward(), which invoked wallet.transferTo(attacker, balance). The require(tx.origin == owner) passed, draining the full 10 ether to the attacker. Assertions confirmed wallet balance dropped to 0 and attacker received 10 ether.

## Needs human review

None.
