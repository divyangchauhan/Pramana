// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title TxOriginWallet
/// @notice Authorizes transfers using `tx.origin` (SWC-115). Because tx.origin
///         is the outermost EOA of the whole call chain — not the immediate
///         caller — a phishing contract that the owner is tricked into calling
///         can move funds on the owner's behalf.
contract TxOriginWallet {
    address public owner;

    constructor() payable {
        owner = msg.sender;
    }

    function transferTo(address payable dest, uint256 amount) external {
        // BUG: tx.origin authentication is phishable.
        require(tx.origin == owner, "not owner");
        (bool ok, ) = dest.call{value: amount}("");
        require(ok, "transfer failed");
    }

    receive() external payable {}
}
