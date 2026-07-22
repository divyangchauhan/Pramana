# Audit report — unchecked-send-payouts

- **Config:** phase1/anthropic:claude-opus-4-8
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — unchecked-call (high)

- **Contract:** `src/Payouts.sol`
- **Location:** payout() L16-22
- **Hypothesis:** Credit funds to a contract recipient whose receive/fallback uses more than 2300 gas or reverts (via credit{value}(who)), then call payout(who): owed[who] is set to 0 before who.send(amount), send silently fails and returns false (unchecked), so the balance is cleared while no ETH is transferred, permanently locking the funds in the contract.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC PASSED. payout() sets owed[who]=0 then uses who.send(amount) with unchecked return. A recipient whose receive() consumes >2300 gas causes send to silently fail (returns false). Test asserts: after payout, owed==0, recipient balance unchanged, 1 ether stuck in Payouts contract, and a second payout reverts with 'nothing owed' — funds permanently locked. Compiler also warned: 'Failure condition of send ignored.'

## Needs human review

None.
