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
- **Hypothesis:** An attacker deploys a malicious contract and tricks the owner into calling it (e.g. via a fallback/any owner-initiated tx), which then calls transferTo(attacker, balance); since tx.origin == owner passes, all wallet ETH is drained to the attacker.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: transferTo() authorizes on tx.origin == owner. A malicious contract's fallback called transferTo(attacker, balance) while the owner (tricked into calling the malicious contract with tx.origin==owner) originated the tx. Wallet balance drained from 10 ether to 0 and attacker gained the full 10 ether. Works against a correctly deployed instance.

## Needs human review

None.
