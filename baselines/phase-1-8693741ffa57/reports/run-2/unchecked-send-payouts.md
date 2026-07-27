# Audit report — unchecked-send-payouts

- **Config:** phase1/anthropic:claude-opus-4-8@medium
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — unchecked-call (medium)

- **Contract:** `src/Payouts.sol`
- **Location:** payout() L16-22
- **Hypothesis:** Call payout(who) where who is a contract whose fallback rejects/consumes >2300 gas: owed[who] is zeroed before who.send(amount), and because send's boolean return is ignored, the transfer fails silently while the balance is wiped, permanently locking the recipient's funds in the contract.
- **PoC:** `test/F-001.t.sol` (proven in 1 executed forge run(s))
- **Evidence:** PoC PASSED: credited 1 ether to a contract whose receive() reverts. payout() zeroed owed[who] to 0 and called who.send(amount), whose false return is ignored, so it did not revert. After the call owed==0, recipient balance unchanged (received nothing), and 1 ether remains permanently stuck in Payouts with no recovery path. Compiler also warns: 'Failure condition of send ignored.'

## Needs human review

None.
