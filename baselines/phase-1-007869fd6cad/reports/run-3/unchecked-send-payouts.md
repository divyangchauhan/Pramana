# Audit report — unchecked-send-payouts

- **Config:** phase1/anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — unchecked-send (medium)

- **Contract:** `src/Payouts.sol`
- **Location:** payout(address) L16-22
- **Hypothesis:** Call credit{value:X}(who) where who is a contract whose receive/fallback consumes more than 2300 gas or reverts, then call payout(who): owed[who] is zeroed and who.send(amount) returns false but the return value is ignored, so the transaction succeeds while the ETH is never delivered and becomes permanently stranded (owed is now 0, so it can never be reclaimed).
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC passed: payout() zeroes owed[who] then calls who.send(amount) with only 2300 gas forwarded. A recipient whose receive() writes storage causes send() to return false, but the return value is ignored so payout() succeeds. Asserted post-state: owed[recipient]==0, recipient balance==0 (never delivered), Payouts contract still holds the 1 ether (stranded), and a second payout() reverts with 'nothing owed' — funds permanently unrecoverable. Compiler also warns 'Failure condition of send ignored'.

## Needs human review

None.
