// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Test} from "forge-std/Test.sol";
import {ModularVault} from "../src/ModularVault.sol";

/// The same storage-aligned module the delegatecall-module reference exploit
/// uses to overwrite the vault's `owner` via a delegatecall.
contract SeizeModule {
    address public owner; // aligns with ModularVault.owner (slot 0)
    address public lastModule; // aligns with ModularVault.lastModule (slot 1)

    function seize() external {
        owner = msg.sender;
    }
}

/// A harmless module the legitimate owner might run: it touches no storage that
/// matters, so a normal execute() call is unaffected by the patch.
contract PingModule {
    function ping() external {}
}

/// Control tests — NOT exploits. The arbitrary-module takeover must be
/// neutralized, and the owner must still be able to run modules and withdraw.
contract ModularVaultControlTest is Test {
    ModularVault vault;
    address attacker;

    function setUp() public {
        vault = new ModularVault{value: 8 ether}(); // this == owner
        attacker = makeAddr("attacker");
    }

    /// KB-1: only the owner may drive execute(), so an attacker cannot
    /// delegatecall a module to seize ownership.
    function testArbitraryModuleCannotSeizeOwnership() public {
        SeizeModule module = new SeizeModule();
        vm.prank(attacker);
        vm.expectRevert(bytes("not owner"));
        vault.execute(address(module), abi.encodeWithSignature("seize()"));

        assertEq(vault.owner(), address(this), "ownership was seized");
        assertEq(address(vault).balance, 8 ether, "vault balance changed");
    }

    /// Guards against a degenerate "fix": the owner can still run a module and
    /// then withdraw the balance normally.
    function testOwnerCanRunModuleAndWithdraw() public {
        PingModule module = new PingModule();
        vault.execute(address(module), abi.encodeWithSignature("ping()"));
        assertEq(vault.owner(), address(this), "owner changed after a benign module");

        uint256 before = address(this).balance;
        vault.withdraw();
        assertEq(address(vault).balance, 0, "vault not drained by its owner");
        assertEq(address(this).balance, before + 8 ether, "owner did not receive funds");
    }

    receive() external payable {}
}
