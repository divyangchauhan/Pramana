# Audit report — unprotected-owner

- **Config:** anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Wallet.sol Audit Report

## F-001: Unprotected initializer / ownership takeover (Critical)

**Impact:** `initOwner(address newOwner)` sets `owner = newOwner` with no access control and no `require(!initialized)` guard, despite the constructor marking `initialized = true`. Any external caller can overwrite `owner` at any time, then pass the `require(msg.sender == owner)` check in `withdraw()` and drain the entire contract balance. This is the classic Parity-multisig unprotected-initializer class of bug.

**PoC:** `test/F-001.t.sol` — deployer creates and funds the wallet with 10 ether; a separate `attacker` account calls `initOwner(attacker)`, becomes owner, and calls `withdraw()`, receiving all 10 ether. Test passes.

**Remediation:** Add access control and a one-time guard. Either remove `initOwner` entirely (owner is already set in the constructor), or protect it: `require(!initialized, "already init"); require(msg.sender == owner, "not owner"); initialized = true;` and add a zero-address check `require(newOwner != address(0))`.

## Needs human review

None. The remaining Slither hits (missing zero-check on `newOwner`, `^0.8.0` version constraint, low-level call in `withdraw`, `initialized` immutability) are subsumed by or subordinate to F-001 and are not independently exploitable.