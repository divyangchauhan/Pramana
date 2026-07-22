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
- **Hypothesis:** An attacker deploys a malicious contract and phishes the owner into calling any function on it; that contract calls TxOriginWallet.transferTo(attacker, wallet.balance), which passes require(tx.origin == owner) because the owner originated the transaction, draining all funds to the attacker.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** transferTo() gates on require(tx.origin == owner). PoC: owner funds wallet with 10 ETH, then (as tx.origin) calls a malicious contract's claimReward(), which invokes wallet.transferTo(attacker, balance). Test PASSED with wallet balance drained to 0 and attacker balance = 10 ETH, proving the tx.origin auth bypass drains all funds.

## Needs human review

None.
