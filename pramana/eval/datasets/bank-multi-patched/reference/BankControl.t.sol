// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Test} from "forge-std/Test.sol";
import {Bank} from "../src/Bank.sol";

/// The same reentrant receiver used by the bank-multi reference exploit.
contract Reenterer {
    Bank public bank;

    constructor(Bank _bank) {
        bank = _bank;
    }

    function attack() external payable {
        bank.deposit{value: 1 ether}();
        bank.withdraw();
    }

    receive() external payable {
        if (address(bank).balance >= 1 ether) {
            bank.withdraw();
        }
    }
}

/// Control tests — NOT exploits. Each of bank-multi's three reference exploits
/// (reentrancy, unprotected setAdmin, sweep-to-zero) must be neutralized here,
/// and the bank must still work for honest depositors and its legitimate admin.
/// If any of these stops passing, the patched twin is not a valid negative
/// control and any false-positive rate measured against it is meaningless.
contract BankControlTest is Test {
    Bank bank;
    address alice;

    function setUp() public {
        bank = new Bank(); // this test contract is the legitimate admin
        alice = makeAddr("alice");
        vm.deal(alice, 5 ether);
        vm.prank(alice);
        bank.deposit{value: 5 ether}();
    }

    /// KB-1: the reentrant withdraw finds a zeroed balance; that revert bubbles
    /// through the attacker's fallback and unwinds the whole attack.
    function testReentrancyAttackReverts() public {
        Reenterer atk = new Reenterer(bank);
        vm.deal(address(atk), 1 ether);

        vm.expectRevert(bytes("transfer failed"));
        atk.attack();

        assertEq(address(bank).balance, 5 ether, "bank lost depositor funds");
        assertEq(bank.balances(alice), 5 ether, "alice's recorded balance changed");
        assertEq(address(atk).balance, 1 ether, "attacker balance changed");
    }

    /// KB-2: a non-admin can no longer seize administration.
    function testUnauthorizedSetAdminReverts() public {
        address attacker = makeAddr("attacker");
        vm.prank(attacker);
        vm.expectRevert(bytes("not admin"));
        bank.setAdmin(attacker);
    }

    /// KB-3: sweeping to the zero address is rejected rather than burning funds.
    function testSweepToZeroReverts() public {
        vm.expectRevert(bytes("zero recipient"));
        bank.sweep(payable(address(0)));
        assertEq(address(bank).balance, 5 ether, "funds moved on a rejected sweep");
    }

    /// Guards against a degenerate always-revert "fix": an honest depositor can
    /// still withdraw their own balance in full.
    function testHonestWithdrawStillWorks() public {
        vm.prank(alice);
        bank.withdraw();
        assertEq(alice.balance, 5 ether, "honest depositor could not withdraw");
        assertEq(bank.balances(alice), 0, "balance not zeroed after withdraw");
        assertEq(address(bank).balance, 0, "bank retained funds it paid out");
    }

    /// The legitimate admin can still sweep to a real recipient.
    function testAdminCanSweepToRecipient() public {
        address payable treasury = payable(makeAddr("treasury"));
        bank.sweep(treasury); // this == admin
        assertEq(treasury.balance, 5 ether, "admin could not sweep to a recipient");
        assertEq(address(bank).balance, 0, "bank not fully swept");
    }
}
