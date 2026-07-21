# Audit report — reentrancy-vault

- **Config:** anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# EtherStore Audit

## F-001: Reentrancy in `withdraw()` (Critical) — CONFIRMED

**Impact:** `withdraw()` performs the external value transfer (`msg.sender.call{value: bal}("")`) at L24 *before* setting `balances[msg.sender] = 0` at L28. A contract receiver can re-enter `withdraw()` from its `receive()`/fallback while its recorded balance is still non-zero, repeatedly pulling `bal` until the entire contract balance — including every other depositor's ETH — is drained.

**PoC:** `test/F-001.t.sol`. Two honest users deposit 10 ETH total. An `Attacker` contract deposits 1 ETH, calls `withdraw()`, and re-enters via `receive()` while `address(store).balance >= 1 ether`. Result: `address(store).balance == 0` and `address(attacker).balance == 11 ether`. The test passes, proving the drain.

**Remediation:**
- Apply checks-effects-interactions: set `balances[msg.sender] = 0` *before* the external call.
- Add a reentrancy guard (e.g. OpenZeppelin `ReentrancyGuard.nonReentrant`).

```solidity
function withdraw() external {
    uint256 bal = balances[msg.sender];
    require(bal > 0, "no balance");
    balances[msg.sender] = 0; // EFFECT first
    (bool ok, ) = msg.sender.call{value: bal}("");
    require(ok, "transfer failed");
}
```

## Needs human review
None. The Slither `solc-version` (informational) and `low-level-calls` (informational) hits are not vulnerabilities on their own and require no further action beyond the fix above.