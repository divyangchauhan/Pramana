// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title Lottery
/// @notice A one-in-ten draw. Each entry costs a fixed ticket price; a winning
///         entry takes the whole pot, a losing one forfeits its ticket into it.
///         The draw is computed on chain at the moment of entry.
contract Lottery {
    uint256 public constant TICKET = 1 ether;
    mapping(address => uint256) public entryBlock;

    /// @notice Buy one ticket and draw immediately.
    function enter() external payable {
        require(msg.value == TICKET, "wrong ticket price");
        require(entryBlock[msg.sender] == 0, "entry pending");
        entryBlock[msg.sender] = block.number;
    }

    function claim() external {
        uint256 entered = entryBlock[msg.sender];
        require(entered != 0 && block.number > entered, "draw not ready");
        require(block.number <= entered + 256, "draw expired");
        entryBlock[msg.sender] = 0;
        uint256 draw = uint256(keccak256(abi.encodePacked(blockhash(entered), msg.sender))) % 10;
        if (draw == 0) {
            (bool ok, ) = payable(msg.sender).call{value: address(this).balance}("");
            require(ok, "transfer failed");
        }
    }

    receive() external payable {}
}
