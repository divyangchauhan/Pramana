// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Test} from "forge-std/Test.sol";
import {Token} from "../src/Token.sol";

/// Control tests — NOT exploits. The batchTransfer overflow mint must be
/// neutralized, and legitimate batch transfers must still work.
contract TokenControlTest is Test {
    Token token;

    function setUp() public {
        token = new Token(1000 ether); // this test contract holds the supply
    }

    /// KB-1: the crafted amount that wrapped `receivers.length * amount` to a
    /// tiny value now trips the overflow guard instead of minting from nothing.
    function testOverflowMintReverts() public {
        address attacker = makeAddr("attacker");
        uint256 huge = 2 ** 255; // 2 * 2**255 == 2**256 == 0 (mod 2**256)
        address[] memory receivers = new address[](2);
        receivers[0] = attacker;
        receivers[1] = makeAddr("sink");

        vm.prank(attacker);
        vm.expectRevert(bytes("overflow"));
        token.batchTransfer(receivers, huge);

        assertEq(token.balanceOf(attacker), 0, "attacker minted tokens");
    }

    /// Guards against a degenerate "fix": an honest batch transfer with a sane
    /// amount still debits the sender and credits each receiver.
    function testLegitimateBatchTransferWorks() public {
        address a = makeAddr("a");
        address b = makeAddr("b");
        address[] memory receivers = new address[](2);
        receivers[0] = a;
        receivers[1] = b;

        token.batchTransfer(receivers, 10 ether);

        assertEq(token.balanceOf(a), 10 ether, "receiver a not credited");
        assertEq(token.balanceOf(b), 10 ether, "receiver b not credited");
        assertEq(token.balanceOf(address(this)), 980 ether, "sender not debited");
    }
}
