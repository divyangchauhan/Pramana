# Audit report — signature-replay-vault

- **Config:** phase1/anthropic:claude-opus-4-8@medium
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 2 / 2

---

# Audit report

2 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — signature-replay (high)

- **Contract:** `src/SignedVault.sol`
- **Location:** release() L16-22
- **Hypothesis:** Because the signed digest is only keccak256(to, amount) with no nonce, deadline, or used-signature tracking, a caller who holds one valid signature can call release(to, amount, v, r, s) repeatedly and drain the entire vault balance in multiples of `amount`.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC deployed SignedVault with 10 ether and a valid signer. A single signature over keccak256(to, amount) was replayed 10 times via release(), draining the full 10 ether to the recipient (to.balance==10 ether, vault balance==0). The digest contains no nonce/deadline and there is no used-signature tracking, so signatures are trivially replayable. Test PASSED.

### F-002 — unchecked-ecrecover (medium)

- **Contract:** `src/SignedVault.sol`
- **Location:** release() L20 / constructor L11-12
- **Hypothesis:** ecrecover returns address(0) for malformed signatures; the constructor has no zero-check on _signer, so if the vault is deployed with signer == address(0), any attacker can supply a garbage signature that recovers to address(0) and pass the require, releasing funds to an arbitrary `to`.
- **Precondition:** requires a misconfigured deployment — the PoC had to construct or configure the contract badly to reach this. Severity is capped at medium for that reason.
- **PoC:** `test/F-002.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** testExploitZeroSigner PASSED: deploying SignedVault with signer=address(0) and calling release with v=0,r=0,s=0 (ecrecover returns address(0)) drained 5 ether to an arbitrary attacker (attacker.balance == 5 ether). PRECONDITION: the vault must be deployed with signer == address(0); the constructor lacks a zero-check. testProperSignerSafe PASSED showing that with a real signer the same garbage signature reverts with 'bad signature'. Thus the exploit is contingent on a misconfigured deployment, capped at medium.

## Needs human review

None.
