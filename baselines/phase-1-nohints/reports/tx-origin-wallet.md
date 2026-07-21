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
- **Hypothesis:** An attacker deploys a malicious contract; when the wallet owner is tricked into calling any function on that contract, the contract calls TxOriginWallet.transferTo(attacker, balance), and because authorization checks tx.origin==owner (which is still the owner's EOA) the check passes and all wallet funds are sent to the attacker.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC PASSED: owner funds wallet with 5 ether; attacker's MaliciousLure.claimReward() is invoked with tx.origin==owner, calling transferTo(attacker, balance). The require(tx.origin==owner) check passes since the owner EOA is the origin, draining the wallet: wallet balance 5 ether -> 0, attacker balance 0 -> 5 ether.

## Needs human review

None.
