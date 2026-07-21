# Audit report — unchecked-overflow-token

- **Config:** anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Token.sol Audit

## F-001: batchOverflow integer overflow in `batchTransfer` (Critical)

**Impact:** In `batchTransfer(address[] receivers, uint256 amount)` the transfer total is computed inside an `unchecked` block: `total = receivers.length * amount;`. An attacker chooses `amount` so that `receivers.length * amount` wraps around `uint256` to a tiny value (e.g. 0). The guard `require(balanceOf[msg.sender] >= total)` then passes even though the caller holds no tokens, and the loop credits each receiver the full (huge) `amount`. This mints tokens from nothing, breaks the total-supply invariant, and lets any account inflate balances arbitrarily — the exact 2018 BeautyChain (BEC) hack.

**PoC:** `test/F-001.t.sol` — attacker with balance 0 calls `batchTransfer([r1, r2], 2^255 + 1)`. Since `2 * (2^255+1)` overflows to 0, `total == 0`, the require passes, and both receivers receive ~5.7e76 tokens each while the attacker spent nothing. Assertions confirm receiver balances exceed `totalSupply`.

**Remediation:** Remove the `unchecked` block so Solidity 0.8's default checked arithmetic reverts on overflow, or explicitly validate `amount != 0 && total / receivers.length == amount`. Also enforce that `total > 0` where appropriate and consider capping batch sizes.

## Needs human review

None — the single finding is confirmed with an executable PoC.