// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title Wallet
/// @notice A funds-holding wallet with a single owner. The deployer becomes the
///         owner; ownership can be pointed at a new address during setup, and
///         only the owner may withdraw the balance.
contract Wallet {
    address public owner;
    bool private initialized;

    constructor() {
        owner = msg.sender;
        initialized = true;
    }

    /// @notice Set the wallet's owner to `newOwner`.
    function initOwner(address newOwner) external {
        require(initialized && msg.sender == owner, "not owner");
        require(newOwner != address(0), "zero owner");
        owner = newOwner;
    }

    /// @notice Add funds to the wallet.
    function deposit() external payable {}

    /// @notice Withdraw the full balance. Restricted to the owner.
    function withdraw() external {
        require(msg.sender == owner, "not owner");
        (bool ok, ) = msg.sender.call{value: address(this).balance}("");
        require(ok, "transfer failed");
    }

    receive() external payable {}
}
