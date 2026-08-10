// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Test} from "forge-std/Test.sol";
import {TxOriginWallet} from "../src/TxOriginWallet.sol";

/// The same phishing contract used by the tx-origin-wallet reference exploit:
/// when the owner is lured into calling ping(), it relays a transfer request to
/// the wallet. On the patched wallet msg.sender is the phish contract, not the
/// owner, so the check fails.
contract Phish {
    TxOriginWallet public wallet;
    address public attacker;

    constructor(TxOriginWallet _wallet, address _attacker) {
        wallet = _wallet;
        attacker = _attacker;
    }

    function ping() external {
        wallet.transferTo(payable(attacker), address(wallet).balance);
    }
}

/// Control tests — NOT exploits. The phishing takeover must be neutralized, and
/// the real owner must still be able to move funds.
contract TxOriginWalletControlTest is Test {
    address owner;
    address attacker;
    TxOriginWallet wallet;

    function setUp() public {
        owner = makeAddr("owner");
        attacker = makeAddr("attacker");
        vm.prank(owner);
        wallet = new TxOriginWallet(); // owner == `owner`
        vm.deal(address(wallet), 5 ether);
    }

    /// KB-1: even with the owner as tx.origin, a call routed through a phishing
    /// contract has msg.sender != owner and is rejected.
    function testPhishingTransferReverts() public {
        Phish phish = new Phish(wallet, attacker);
        vm.prank(owner, owner); // msg.sender = owner, tx.origin = owner
        vm.expectRevert(bytes("not owner"));
        phish.ping();

        assertEq(attacker.balance, 0, "attacker received funds");
        assertEq(address(wallet).balance, 5 ether, "wallet was drained");
    }

    /// Guards against a degenerate always-revert "fix": the owner can still
    /// transfer directly.
    function testOwnerCanTransfer() public {
        address payable dest = payable(makeAddr("dest"));
        vm.prank(owner);
        wallet.transferTo(dest, 2 ether);
        assertEq(dest.balance, 2 ether, "owner could not transfer");
        assertEq(address(wallet).balance, 3 ether, "wrong amount left the wallet");
    }
}
