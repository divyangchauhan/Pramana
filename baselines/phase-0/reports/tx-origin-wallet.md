# Audit report — tx-origin-wallet

- **Config:** anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# TxOriginWallet Audit

## F-001: tx.origin authentication is phishable (High)

**Location:** `transferTo(address,uint256)` L16-21

**Impact:** The function guards fund transfers with `require(tx.origin == owner, "not owner")`. `tx.origin` is the outermost EOA of the entire call chain, not the immediate caller (`msg.sender`). Any contract the owner is tricked into interacting with can call `transferTo` and move the wallet's full balance to an arbitrary destination, because `tx.origin` still equals `owner`. Combined with the arbitrary `dest.call{value: amount}` (Slither leads [1] and [3]), this allows complete draining of the wallet.

**PoC:** `test/F-001.t.sol` — `testTxOriginPhishing` funds the wallet with 10 ETH, has the owner (as tx.origin) call a malicious `PhishingAttack.claimReward()`, and shows all 10 ETH transferred to the attacker while `msg.sender` to the wallet was the attacker contract, not the owner.

**Remediation:** Replace `tx.origin` with `msg.sender` for authorization: `require(msg.sender == owner, "not owner")`. Additionally consider making `owner` immutable and adding a zero-address check on `dest`.

## Needs human review

None. The sole finding is confirmed with an executable PoC.