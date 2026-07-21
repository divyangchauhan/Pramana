# Audit report — bank-multi

- **Config:** anthropic:claude-opus-4-8
- **True positives:** 2 / 2 known bugs
- **Confirmed / PoC-verified:** 2 / 2

---

# Bank.sol Audit Report

Two independent critical vulnerabilities were confirmed with executable Foundry PoCs.

## F-001 — Reentrancy in withdraw() (Critical)
**Impact:** `withdraw()` performs the external ETH transfer `msg.sender.call{value: bal}("")` *before* setting `balances[msg.sender] = 0`. A malicious contract can re-enter `withdraw()` from its `receive()` while its balance is still non-zero, repeatedly withdrawing until the entire pooled deposits of all users are drained. PoC shows an attacker depositing 1 ether and extracting the full 4 ether pool.
**PoC:** `test/F-001.t.sol`
**Remediation:** Apply checks-effects-interactions: zero the balance before the external call, and/or add a `nonReentrant` guard (OpenZeppelin `ReentrancyGuard`).

## F-002 — Missing access control in setAdmin() (Critical)
**Impact:** `setAdmin(address)` has no authorization. Anyone can make themselves admin, then call `sweep()` (which only checks `msg.sender == admin`) to transfer the entire contract balance. PoC shows an attacker seizing admin and sweeping 5 ether of victim funds.
**PoC:** `test/F-002.t.sol`
**Remediation:** Restrict `setAdmin` to the current admin (`require(msg.sender == admin)`), ideally with a two-step ownership transfer, and add a zero-address check.

## Needs human review
None — both findings confirmed. Note the low-severity Slither leads (missing zero-checks on `sweep`/`setAdmin` addresses, `^0.8.0` pragma) are minor hardening items subsumed by the F-002 fix and were not separately exploited.