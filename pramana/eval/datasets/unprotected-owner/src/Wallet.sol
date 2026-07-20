// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title Wallet
/// @notice A funds-holding wallet modeled on the unprotected-initializer class
///         of bug behind the Parity multisig incidents. Ownership is meant to
///         be set once at construction, but `initOwner` is left callable by
///         anyone with no "already initialized" guard, so an attacker can seize
///         ownership at will and drain the balance.
contract Wallet {
    address public owner;
    bool private initialized;

    constructor() {
        owner = msg.sender;
        initialized = true;
    }

    /// BUG: missing `require(!initialized)` (or any access control). Any caller
    /// can overwrite `owner` after deployment.
    function initOwner(address newOwner) external {
        owner = newOwner;
    }

    function deposit() external payable {}

    function withdraw() external {
        require(msg.sender == owner, "not owner");
        (bool ok, ) = msg.sender.call{value: address(this).balance}("");
        require(ok, "transfer failed");
    }

    receive() external payable {}
}
