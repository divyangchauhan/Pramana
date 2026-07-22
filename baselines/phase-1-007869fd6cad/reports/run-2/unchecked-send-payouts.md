# Audit report — unchecked-send-payouts

- **Config:** phase1/anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — unchecked-call (medium)

- **Contract:** `src/Payouts.sol`
- **Location:** payout(address) L16-22
- **Hypothesis:** Call credit{value:X}(who) for a recipient whose fallback consumes more than the 2300-gas send stipend or reverts, then call payout(who): owed[who] is zeroed before who.send(amount) executes, the send silently fails and returns false unchecked, so the X ETH stays in the contract while the recipient's balance is permanently lost.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: after crediting 1 ETH to a recipient whose receive() consumes >2300 gas, payout() zeroes owed[who] before who.send(amount). The send silently fails (return value unchecked), leaving the 1 ETH stuck in the contract (address(payouts).balance unchanged) and the recipient's balance unchanged (received nothing). A second payout() reverts with 'nothing owed', proving the balance is permanently lost. Compiler even warned: 'Failure condition of send ignored'.

## Needs human review

None.
