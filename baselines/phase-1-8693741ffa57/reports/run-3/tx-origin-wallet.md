# Audit report — tx-origin-wallet

- **Config:** phase1/anthropic:claude-opus-4-8@medium
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — tx-origin (high)

- **Contract:** `src/TxOriginWallet.sol`
- **Location:** transferTo() L15-19
- **Hypothesis:** An attacker deploys a malicious contract and lures the owner into calling any function on it; that contract calls TxOriginWallet.transferTo(attacker, balance), which passes because tx.origin == owner even though msg.sender is the attacker contract, draining all funds to the attacker.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** transferTo() uses `require(tx.origin == owner)`. PoC: owner deploys+funds wallet with 100 ETH; attacker deploys Malicious; owner (as tx.origin) calls mal.claimReward() which calls wallet.transferTo(attacker, balance). Test PASSED: wallet balance drained to 0 and attacker gained 100 ETH, despite msg.sender being the attacker contract. Classic tx.origin phishing.

## Needs human review

None.
