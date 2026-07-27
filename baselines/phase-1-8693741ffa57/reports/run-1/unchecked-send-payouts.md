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
- **Hypothesis:** Call credit{value:1 ether}(contractThatRejectsEther), then payout(that address): owed is zeroed before send, send returns false (2300 gas / reverting fallback) but the return value is ignored, so the balance is permanently marked paid while the ether stays stuck in the contract — funds lost.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: credited 1 ether to a contract whose receive() reverts, then called payout(). owed[recipient] was zeroed to 0, send() returned false but its return value is ignored so payout did not revert; the 1 ether remained stuck in the Payouts contract (address(payouts).balance == 1 ether, recipient balance == 0). A subsequent payout reverts with 'nothing owed', proving the funds are permanently marked paid but never delivered — funds lost. Compiler even warns: 'Failure condition of send ignored.'

## Needs human review

None.
