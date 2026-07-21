// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title Bank
/// @notice A deposit vault that deliberately carries TWO independent,
///         separately-exploitable vulnerabilities — a multi-bug fixture that
///         exercises the harness's one-to-one matching of findings to known bugs.
///
///  1. Reentrancy (The DAO, 2016): withdraw() performs the external ETH transfer
///     BEFORE zeroing the caller's balance, so a malicious receiver can re-enter
///     and drain other depositors.
///  2. Access control (Parity-style): setAdmin() has no authorization, so anyone
///     can make themselves admin and sweep() the entire balance.
contract Bank {
    mapping(address => uint256) public balances;
    address public admin;

    constructor() {
        admin = msg.sender;
    }

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    /// BUG 1 — reentrancy: interaction before effect.
    function withdraw() external {
        uint256 bal = balances[msg.sender];
        require(bal > 0, "no balance");
        (bool ok, ) = msg.sender.call{value: bal}("");
        require(ok, "transfer failed");
        balances[msg.sender] = 0;
    }

    /// BUG 2 — access control: no authorization, anyone can seize admin.
    function setAdmin(address newAdmin) external {
        admin = newAdmin;
    }

    function sweep(address payable to) external {
        require(msg.sender == admin, "not admin");
        to.transfer(address(this).balance);
    }

    receive() external payable {}
}
