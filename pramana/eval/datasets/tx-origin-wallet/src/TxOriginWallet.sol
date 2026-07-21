// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title TxOriginWallet
/// @notice A single-owner wallet. It is funded at deployment and afterwards via
///         plain transfers; only the owner may move funds out.
contract TxOriginWallet {
    address public owner;

    constructor() payable {
        owner = msg.sender;
    }

    /// @notice Send `amount` wei to `dest`. Restricted to the owner.
    function transferTo(address payable dest, uint256 amount) external {
        require(tx.origin == owner, "not owner");
        (bool ok, ) = dest.call{value: amount}("");
        require(ok, "transfer failed");
    }

    receive() external payable {}
}
