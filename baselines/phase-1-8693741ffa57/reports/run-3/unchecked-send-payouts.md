# Audit report — unchecked-send-payouts

- **Config:** phase1/anthropic:claude-opus-4-8@medium
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — unchecked-call (high)

- **Contract:** `src/Payouts.sol`
- **Location:** payout(address) L16-22
- **Hypothesis:** A recipient whose credited balance is set to zero before an unchecked who.send(amount) permanently loses funds when send fails: deploy a contract with a fallback that reverts or costs >2300 gas, credit it, then call payout(that_contract) — owed is zeroed but the 2300-gas send returns false and is ignored, leaving the ETH stuck in the contract with no way to recredit or retry.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC PASSED: credited 1 ether to a contract whose receive() reverts, then called payout(). owed[who] was zeroed but the unchecked who.send(amount) failed silently (compiler warns 'Failure condition of send ignored'). Recipient balance stayed 0, 1 ether is stuck in Payouts, and a retry reverts with 'nothing owed' — funds permanently lost with no recredit/retry path.

## Needs human review

None.
