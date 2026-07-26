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
- **Hypothesis:** An attacker deploys a malicious contract and tricks the owner into calling it (e.g. via receive/fallback or any function); that contract calls transferTo(attacker, balance) while tx.origin is still the owner, passing the require(tx.origin == owner) check and draining all wallet funds to an arbitrary destination.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** transferTo() guards with require(tx.origin == owner). PoC: owner deploys and funds wallet with 5 ETH, attacker deploys a lure contract whose receive() calls wallet.transferTo(attacker, balance). When owner sends 1 wei to the lure (tx.origin==owner), the check passes and all 5 ETH is drained to an arbitrary attacker address. Test PASSED: wallet balance 0, attacker balance 5 ether. Works against a normally deployed instance; only social-engineering the owner into one tx is required.

## Needs human review

None.
