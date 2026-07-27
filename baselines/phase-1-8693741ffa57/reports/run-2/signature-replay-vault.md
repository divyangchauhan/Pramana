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
- **Hypothesis:** The signed digest is keccak256(abi.encodePacked(to, amount)) with no nonce, deadline, or consumed-signature tracking, so once the signer authorizes one release the recipient can call release(to, amount, v, r, s) with the same signature repeatedly to drain the entire vault balance.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** release() has no nonce/deadline/consumed-signature tracking; the digest is just keccak256(to, amount). PoC signed one authorization for 1 ether to recipient and replayed the identical (v,r,s) 10 times, draining the 10 ETH vault to 0 with recipient receiving all 10 ETH. Test PASSED: vault balance 0, recipient balance 10 ether.

### F-002 — access-control (medium)

- **Contract:** `src/SignedVault.sol`
- **Location:** constructor() L11-13 / release() L20
- **Hypothesis:** If the vault is deployed with _signer == address(0) (no zero-check), then ecrecover on a malformed signature returns address(0), so require(ecrecover(...) == signer) passes for any attacker-crafted invalid signature, letting anyone drain the vault to an arbitrary `to`.
- **Precondition:** requires a misconfigured deployment — the PoC had to construct or configure the contract badly to reach this. Severity is capped at medium for that reason.
- **PoC:** `test/F-002.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC deployed SignedVault with signer=address(0) and 10 ether, then called release(attacker, 10 ether, v=0, r=0, s=0). ecrecover returned address(0), passing the require, and the full 10 ether transferred to the attacker (attacker.balance==10 ether, vault balance==0). PRECONDITION: this only works when the vault is deployed with _signer==address(0), which no competent deployer would do; a real signer address makes ecrecover(address(0)) fail the check. Hence deployment-contingent, capped at medium.

## Needs human review

None.
