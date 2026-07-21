// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Test} from "forge-std/Test.sol";
import {EtherStore} from "../src/EtherStore.sol";

/// The same malicious receiver used by the reentrancy-vault reference exploit.
contract ReentrancyAttacker {
    EtherStore public store;

    constructor(EtherStore _store) {
        store = _store;
    }

    function attack() external payable {
        store.deposit{value: 1 ether}();
        store.withdraw();
    }

    receive() external payable {
        if (address(store).balance >= 1 ether) {
            store.withdraw();
        }
    }
}

/// Honest depositor — withdraws once, without re-entering.
contract HonestUser {
    EtherStore public store;

    constructor(EtherStore _store) {
        store = _store;
    }

    function depositAndWithdraw() external payable {
        store.deposit{value: msg.value}();
        store.withdraw();
    }

    receive() external payable {}
}

/// Control tests — NOT exploits. These are the negative control's guarantee:
/// the exact attack that drains `reentrancy-vault` must fail here, AND the
/// vault must still work for honest users. If either stops passing, the
/// "patched" fixture is invalid and any false-positive rate measured against
/// it is meaningless.
contract NoDrainControlTest is Test {
    EtherStore store;
    address alice;

    function setUp() public {
        store = new EtherStore();
        alice = makeAddr("alice");
        vm.deal(alice, 5 ether);
        vm.prank(alice);
        store.deposit{value: 5 ether}();
    }

    /// The reentrant withdraw finds a zeroed balance and reverts; that revert
    /// bubbles through the attacker's fallback and unwinds the whole attack.
    function testReentrancyAttackReverts() public {
        ReentrancyAttacker attacker = new ReentrancyAttacker(store);
        vm.deal(address(attacker), 1 ether);

        vm.expectRevert(bytes("transfer failed"));
        attacker.attack();

        // Nothing moved: alice's deposit is fully intact.
        assertEq(address(store).balance, 5 ether, "vault lost depositor funds");
        assertEq(store.balanceOf(alice), 5 ether, "alice's recorded balance changed");
        assertEq(address(attacker).balance, 1 ether, "attacker balance changed");
    }

    /// Guards against a degenerate "fix": a vault whose withdraw() always
    /// reverts would pass the test above while being a useless control.
    function testHonestWithdrawStillWorks() public {
        HonestUser user = new HonestUser(store);
        vm.deal(address(this), 2 ether);

        // The 2 ether is forwarded to `user` as msg.value, deposited, then
        // withdrawn — so `user` should end up holding exactly that 2 ether.
        user.depositAndWithdraw{value: 2 ether}();

        assertEq(address(user).balance, 2 ether, "honest user could not withdraw");
        assertEq(store.balanceOf(address(user)), 0, "balance not zeroed after withdraw");
        assertEq(address(store).balance, 5 ether, "alice's funds affected");
    }
}
