# Audit report — tx-origin-wallet

- **Config:** phase1/kimi:kimi-k3
- **True positives:** 1 / 1 known bugs
- **Confirmed / PoC-verified:** 1 / 1

---

# Audit report

1 confirmed finding(s) proven with an executable PoC; 0 needing human review; 0 claim(s) refuted by the verifier.

## Confirmed findings

### F-001 — tx-origin (high)

- **Contract:** `src/TxOriginWallet.sol`
- **Location:** transferTo() L15-19
- **Hypothesis:** An attacker deploys a malicious contract and phishes the wallet owner (an EOA) into initiating any transaction to it; during that transaction the malicious contract calls wallet.transferTo(attacker, address(wallet).balance), the require(tx.origin == owner) check passes because tx.origin is the owner's EOA, and the wallet's entire ETH balance is transferred to the attacker.
- **PoC:** `test/F-001.t.sol` (proven in 2 executed forge run(s))
- **Evidence:** PoC passed: testExploit() set tx.origin to the owner (via two-arg vm.prank simulating the phished EOA transaction) while msg.sender was the attacker-deployed Malicious contract; Malicious.attack called wallet.transferTo(attacker, wallet.balance), the require(tx.origin == owner) check passed, and the wallet's entire 10 ether was drained to the attacker (asserted: wallet balance 0, attacker balance 10 ether). Control test testNonOriginBlocked confirmed the drain only works because of the tx.origin auth bypass (reverts 'not owner' when tx.origin != owner). Any transaction the owner EOA initiates to an attacker contract drains the wallet.

## Needs human review

None.
