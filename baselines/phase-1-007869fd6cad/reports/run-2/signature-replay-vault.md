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
- **Hypothesis:** The signed digest keccak256(abi.encodePacked(to, amount)) contains no nonce, expiry, or usage tracking, so anyone holding one valid signer signature can call release(to, amount, v, r, s) repeatedly, draining the entire vault balance in multiples of `amount` rather than a single payout.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: a single valid signer signature over keccak256(abi.encodePacked(to, 1 ether)) was passed to release() 10 times. No nonce/expiry/usage tracking exists, so all 10 calls succeeded, draining the entire 10 ether vault (to.balance == 10 ether, vault balance == 0). Signature replay confirmed.

### F-002 — signature-malleability (informational)

- **Contract:** `src/SignedVault.sol`
- **Location:** release() L18-20
- **Hypothesis:** release() uses raw ecrecover without rejecting the second (high-s) valid signature or checking for the zero-address return, so a malformed (v,r,s) that makes ecrecover return address(0) would pass if signer were ever set to address(0); combined with no s-range check ecrecover also accepts the malleable counterpart of any valid signature.
- **PoC:** `test/F-002.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** testMalleabilityAccepted() PASSED: after using the signer's valid signature, the malleable counterpart (s' = n - s, flipped v) was ALSO accepted by release(), draining a second 1 ether (to.balance = 2 ether), proving ecrecover has no low-s check. However testZeroAddressReturnDoesNotBypass() PASSED showing the zero-address branch reverts because signer is a real non-zero address (the constructor never sets it to 0), refuting that half of the claim. Impact graded informational: the vault has NO replay/signature-tracking guard, so the same original signature could already be replayed to drain funds; the malleability grants no incremental capability beyond the pre-existing unguarded replay, though the malleability defect (a distinct second valid signature is accepted) is genuinely present in code.

## Needs human review

None.
