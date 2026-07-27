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
- **Location:** release() L16-23
- **Hypothesis:** The digest only covers (to, amount) with no nonce, deadline, or used-signature tracking, so anyone holding one valid signature can call release(to, amount, v, r, s) repeatedly to withdraw `amount` each time until the vault is drained.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC deployed SignedVault with 10 ether and a valid signer. A single signature over (to, amount=1 ether) was replayed 10 times via release(), draining the vault to 0 and delivering 10 ether to the recipient. Test passed: assertEq(vault.balance,0) and assertEq(to.balance,10 ether). The digest covers only (to,amount) with no nonce/deadline/used-tracking, confirming signature replay.

### F-002 — missing-zero-check (medium)

- **Contract:** `src/SignedVault.sol`
- **Location:** release() L20 / constructor L11-13
- **Hypothesis:** If the vault is deployed with signer == address(0), ecrecover returns address(0) for malformed/invalid signatures, so an attacker submitting a garbage signature that recovers to zero passes the require and drains funds.
- **Precondition:** requires a misconfigured deployment — the PoC had to construct or configure the contract badly to reach this. Severity is capped at medium for that reason.
- **PoC:** `test/F-002.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** testGarbageSigDrains PASSED: vault deployed with signer==address(0) allowed release with v=27,r=0,s=0 (ecrecover returns address(0)), draining all 10 ether to the attacker. testProperSignerNotDrainable PASSED showing that with a real signer the same garbage signature reverts with 'bad signature'. The exploit only works when the deployer passes signer==address(0), a misconfiguration no competent deployer would make, hence deployment_contingent=true and capped at medium.

## Needs human review

None.
