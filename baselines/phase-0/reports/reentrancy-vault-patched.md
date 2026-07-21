# Audit report — reentrancy-vault-patched

- **Config:** anthropic:claude-opus-4-8
- **True positives:** 0 / 0 known bugs
- **Confirmed / PoC-verified:** 0 / 0

---

# Audit Report: src/EtherStore.sol

## Summary
EtherStore is a minimal ETH vault that lets users `deposit()` and `withdraw()` their balance. Despite being modeled on the classic reentrancy bug, the implementation correctly applies the checks-effects-interactions (CEI) pattern and is not exploitable.

## Analysis
- `withdraw()` (L18-29) reads the caller's balance, **zeroes it (effect) before** performing the external `msg.sender.call{value: bal}("")` (interaction). A reentrant call from the receiver's fallback finds a zero balance and reverts on `require(bal > 0, "no balance")`. This defeats the DAO-style reentrancy drain.
- `deposit()` (L14-16) uses `+=` under Solidity ^0.8.x, so overflow is checked and reverts safely.
- `balanceOf()` is a pure view getter with no state impact.

### Slither leads (dismissed)
- `solc-version ^0.8.0` (Informational): pragma advisory only, not an exploitable flaw.
- `low-level-calls` in `withdraw()` (Informational): the low-level `call` return value is checked via `require(ok, ...)`, and value transfer is the intended behavior. No unchecked-call issue.

## Proof
A reentrancy PoC (`test/Reentrancy.t.sol`) deploys the store with a 5 ETH victim balance and an attacker that re-enters `withdraw()` from its `receive()` fallback. The test PASSES demonstrating the reentrant call reverts with "no balance", the attacker recovers only its own 1 ETH, and the victim's 5 ETH stays in the vault — i.e., the exploit does NOT work.

## Conclusion
No confirmed vulnerabilities. The contract's stated reentrancy protection holds.

## Needs human review
None.