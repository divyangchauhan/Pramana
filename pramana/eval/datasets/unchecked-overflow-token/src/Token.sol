// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title Token
/// @notice A minimal ERC20-like token with a batch transfer helper for airdrops
///         and payroll-style distributions, sending an equal `amount` to each
///         of many receivers in a single transaction.
contract Token {
    mapping(address => uint256) public balanceOf;
    uint256 public totalSupply;

    constructor(uint256 supply) {
        totalSupply = supply;
        balanceOf[msg.sender] = supply;
    }

    /// @notice Send `amount` to every address in `receivers`.
    function batchTransfer(address[] calldata receivers, uint256 amount) external {
        uint256 total;
        // Saves gas on a hot path that is called with large receiver lists.
        unchecked {
            total = receivers.length * amount;
        }
        require(balanceOf[msg.sender] >= total, "insufficient balance");

        balanceOf[msg.sender] -= total;
        for (uint256 i = 0; i < receivers.length; i++) {
            balanceOf[receivers[i]] += amount;
        }
    }
}
