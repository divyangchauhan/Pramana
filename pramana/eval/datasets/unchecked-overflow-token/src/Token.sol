// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title Token
/// @notice An ERC20-like token modeled on the BeautyChain (BEC) batchOverflow
///         hack (2018). Solidity 0.8 checks arithmetic by default, but this
///         contract deliberately computes the transfer total inside an
///         `unchecked` block, reintroducing the classic multiplication
///         overflow: a crafted `amount` makes `total` wrap to a tiny value, the
///         balance check passes, and huge balances are minted from nothing.
contract Token {
    mapping(address => uint256) public balanceOf;
    uint256 public totalSupply;

    constructor(uint256 supply) {
        totalSupply = supply;
        balanceOf[msg.sender] = supply;
    }

    function batchTransfer(address[] calldata receivers, uint256 amount) external {
        uint256 total;
        // BUG: overflow is re-enabled here. receivers.length * amount can wrap.
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
