# Audit report — signature-replay-vault

- **Config:** phase1/anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 2 / 2

---

# Audit report

2 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — signature-replay (critical)

- **Contract:** `src/SignedVault.sol`
- **Location:** release() L16-23
- **Hypothesis:** The signed digest keccak256(abi.encodePacked(to, amount)) contains no nonce, expiry, or on-chain consumption, so after obtaining one valid signature for (to, amount) an attacker can call release(to, amount, v, r, s) repeatedly with the identical parameters to drain the entire vault balance in multiples of `amount`.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** release() signs only keccak256(abi.encodePacked(to, amount)) with no nonce, expiry, or consumption. PoC signed one authorization for (to, 1 ether) and replayed the identical (v,r,s) 10 times, draining the full 10 ether vault balance to the attacker. Test PASSED: vault balance 0, recipient balance 10 ether.

### F-002 — access-control (high)

- **Contract:** `src/SignedVault.sol`
- **Location:** constructor() L11-13 and release() L21
- **Hypothesis:** If the vault is deployed with signer == address(0) (constructor performs no zero-check, Slither lead #2), then because ecrecover returns address(0) for malformed signatures, an attacker can call release with garbage v/r/s that recover to address(0), pass the require, and withdraw any amount to any address.
- **PoC:** `test/F-002.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC PASSED: deployed SignedVault with signer==address(0) funded with 10 ether; attacker called release with garbage signature (v=0, r=1, s=1), ecrecover returned address(0)==signer, passing the require, and 5 ether was transferred to the attacker (attacker.balance delta == 5 ether). Constructor performs no zero-check, so any vault deployed with signer=address(0) is fully drainable.

## Needs human review

None.
