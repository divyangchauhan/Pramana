# Audit report — unprotected-owner

- **Config:** phase1/kimi:kimi-k3
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 1 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — access-control (critical)

- **Contract:** `src/Wallet.sol`
- **Location:** initOwner() L17-19
- **Hypothesis:** After the wallet holds any ETH (via deposit() or receive()), any attacker calls initOwner(attackerAddress) to overwrite owner, then calls withdraw() and receives the entire contract balance.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** Forge run passed: [PASS] testExploit() (gas: 61287). The PoC deployed Wallet, funded it with 10 ETH via deposit(), then from an unrelated attacker address called initOwner(attacker) — which succeeded because initOwner() has no access control and never checks the `initialized` flag set in the constructor — and then called withdraw(), draining the full 10 ETH balance to the attacker. Assertions confirmed owner == attacker, wallet balance == 0, and attacker balance increased by 10 ether. Any ETH held by the wallet can be stolen by anyone in two calls.

## Needs human review

None.
