// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Test} from "forge-std/Test.sol";
import {Wallet} from "../src/Wallet.sol";

/// Control tests — NOT exploits. The unprotected-initializer takeover must be
/// neutralized, and the real owner must still be able to withdraw.
contract WalletControlTest is Test {
    Wallet wallet;

    function setUp() public {
        wallet = new Wallet(); // this test contract is the legitimate owner
        vm.deal(address(wallet), 10 ether);
    }

    /// KB-1: initOwner() is guarded, so an unrelated account can no longer seize
    /// ownership and drain the wallet.
    function testUnauthorizedInitOwnerReverts() public {
        address attacker = makeAddr("attacker");
        vm.prank(attacker);
        vm.expectRevert(bytes("not owner"));
        wallet.initOwner(attacker);

        assertEq(wallet.owner(), address(this), "ownership was seized");
        assertEq(address(wallet).balance, 10 ether, "wallet balance changed");
    }

    /// Guards against a degenerate always-revert "fix": the owner can still hand
    /// ownership to a new address and that address can withdraw.
    function testOwnerCanReassignAndWithdraw() public {
        NewOwner next = new NewOwner(wallet);
        wallet.initOwner(address(next)); // legitimate owner reassigns
        assertEq(wallet.owner(), address(next), "owner not reassigned");

        next.withdraw();
        assertEq(address(next).balance, 10 ether, "new owner could not withdraw");
        assertEq(address(wallet).balance, 0, "wallet not drained by its owner");
    }
}

/// A stand-in for a legitimate successor owner set via initOwner().
contract NewOwner {
    Wallet wallet;

    constructor(Wallet _wallet) {
        wallet = _wallet;
    }

    function withdraw() external {
        wallet.withdraw();
    }

    receive() external payable {}
}
