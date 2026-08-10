// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Test} from "forge-std/Test.sol";
import {Payouts} from "../src/Payouts.sol";

/// A recipient that cannot accept ETH — the same one the unchecked-send-payouts
/// reference exploit uses to make a transfer fail.
contract RejectingRecipient {
    receive() external payable {
        revert("cannot accept");
    }
}

/// Control tests — NOT exploits. Both reference bugs (silent send failure and
/// zero-address burn) must be neutralized, and honest payouts must still work.
contract PayoutsControlTest is Test {
    Payouts payouts;

    function setUp() public {
        payouts = new Payouts();
        vm.deal(address(this), 5 ether);
    }

    /// KB-1: a failed transfer now reverts the whole payout, so the claim
    /// survives instead of being silently destroyed. (Named to avoid Foundry's
    /// `testFail` prefix, which would invert the result.)
    function testRejectedPayoutPreservesClaim() public {
        RejectingRecipient recipient = new RejectingRecipient();
        payouts.credit{value: 5 ether}(address(recipient));

        vm.expectRevert(bytes("transfer failed"));
        payouts.payout(payable(address(recipient)));

        assertEq(payouts.owed(address(recipient)), 5 ether, "claim was destroyed");
        assertEq(address(payouts).balance, 5 ether, "funds left the contract");
    }

    /// KB-2: value can no longer be credited to the zero address.
    function testCreditToZeroReverts() public {
        vm.expectRevert(bytes("zero recipient"));
        payouts.credit{value: 1 ether}(address(0));
    }

    /// KB-2 (second half): paying out to the zero address is rejected too.
    function testPayoutToZeroReverts() public {
        vm.expectRevert(bytes("zero recipient"));
        payouts.payout(payable(address(0)));
    }

    /// Guards against a degenerate always-revert "fix": an honest recipient is
    /// still credited and paid in full.
    function testHonestCreditAndPayoutWorks() public {
        address payable who = payable(makeAddr("who"));
        payouts.credit{value: 4 ether}(who);
        payouts.payout(who);

        assertEq(who.balance, 4 ether, "honest recipient not paid");
        assertEq(payouts.owed(who), 0, "claim not cleared after payout");
        assertEq(address(payouts).balance, 0, "funds retained after payout");
    }
}
