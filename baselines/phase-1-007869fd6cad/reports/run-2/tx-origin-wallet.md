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
- **Hypothesis:** An attacker deploys a malicious contract and tricks the wallet owner into sending any transaction to it (e.g. via a payable fallback); that contract then calls TxOriginWallet.transferTo(attacker, address(this).balance), which passes require(tx.origin == owner) because the owner originated the tx, draining the entire wallet balance to the attacker.
- **PoC:** `test/F-001.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** PoC passed: the wallet uses require(tx.origin == owner) in transferTo(). When the owner (EOA 0xABCD) sends a plain 1-wei tx to a malicious Attacker contract, that contract's receive() calls wallet.transferTo(attacker, wallet.balance). tx.origin is still the owner, so the check passes and all 10 ether is transferred to the attacker EOA. Assertions confirm wallet balance == 0 and attacker EOA gained 10 ether.

## Needs human review

None.
