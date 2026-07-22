// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title Lottery
/// @notice A one-in-ten draw. Each entry costs a fixed ticket price; a winning
///         entry takes the whole pot, a losing one forfeits its ticket into it.
///         The draw is computed on chain at the moment of entry.
contract Lottery {
    uint256 public constant TICKET = 1 ether;

    /// @notice Buy one ticket and draw immediately.
    function enter() external payable {
        require(msg.value == TICKET, "wrong ticket price");

        uint256 draw = uint256(
            keccak256(abi.encodePacked(block.timestamp, block.prevrandao, msg.sender))
        ) % 10;

        if (draw == 0) {
            payable(msg.sender).transfer(address(this).balance);
        }
    }

    receive() external payable {}
}
