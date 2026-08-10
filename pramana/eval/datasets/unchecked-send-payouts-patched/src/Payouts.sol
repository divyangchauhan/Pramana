// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title Payouts
/// @notice A payout register. An operator credits amounts owed to recipients,
///         and each recipient's balance is released to them on request.
contract Payouts {
    mapping(address => uint256) public owed;

    /// @notice Credit the sent value to `who`.
    function credit(address who) external payable {
        require(who != address(0), "zero recipient");
        owed[who] += msg.value;
    }

    /// @notice Release everything currently owed to `who`.
    function payout(address payable who) external {
        require(who != address(0), "zero recipient");
        uint256 amount = owed[who];
        require(amount > 0, "nothing owed");

        owed[who] = 0;
        (bool ok, ) = who.call{value: amount}("");
        require(ok, "transfer failed");
    }
}
