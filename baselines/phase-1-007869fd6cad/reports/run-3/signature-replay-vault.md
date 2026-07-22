# Audit report — signature-replay-vault

- **Config:** phase1/anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 2 / 2

---

# Audit report

2 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — signature-replay (high)

- **Contract:** `src/SignedVault.sol`
- **Location:** release() L16-23
- **Hypothesis:** The signed digest keccak256(abi.encodePacked(to, amount)) contains no nonce, no used-signature tracking, no contract address, and no expiry, so a caller who obtained one valid (to, amount, v, r, s) authorization can call release() repeatedly with the same signature to drain the entire vault balance in amount-sized increments.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: a single valid signer authorization for (to, 1 ether) was replayed 10 times via release(), draining the entire 10 ether vault. Final to.balance == 10 ether and vault balance == 0. The digest keccak256(abi.encodePacked(to, amount)) has no nonce, no used-signature tracking, no contract address, and no expiry, so signatures are infinitely replayable.

### F-002 — access-control (high)

- **Contract:** `src/SignedVault.sol`
- **Location:** release() L16-23 / constructor L11-13
- **Hypothesis:** If the contract is deployed with signer == address(0) (constructor lacks a zero-check), then because ecrecover returns address(0) for malformed signatures, any attacker can pass arbitrary/garbage v,r,s that resolve to address(0) and satisfy the signer check, releasing funds to any address.
- **PoC:** `test/F-002.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** Deployed SignedVault with signer==address(0) and 10 ether. Attacker called release(attacker, 5 ether, v=0, r=1, s=2). ecrecover returned address(0) matching signer, passing the require. Test PASSED: attacker.balance increased by exactly 5 ether, proving funds drained without any valid signature. Impact contingent on deployment with zero signer (constructor lacks zero-check).

## Needs human review

None.
