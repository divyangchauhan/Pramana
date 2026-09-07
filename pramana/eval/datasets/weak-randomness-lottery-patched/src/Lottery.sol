// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title Lottery
/// @notice A one-in-ten draw. Each entry costs a fixed ticket price; a winning
///         entry takes the whole pot, a losing one forfeits its ticket into it.
///         The draw is computed on chain at the moment of entry.
contract Lottery {
    uint256 public constant TICKET = 1 ether;
    mapping(address => uint256) public entryBlock;
    address public immutable randomnessProvider;

    constructor() {
        randomnessProvider = msg.sender;
    }

    /// @notice Buy one ticket and draw immediately.
    function enter() external payable {
        require(msg.value == TICKET, "wrong ticket price");
        require(entryBlock[msg.sender] == 0, "entry pending");
        entryBlock[msg.sender] = block.number;
    }

    function fulfillRandomness(address player, uint256 randomWord) external {
        require(msg.sender == randomnessProvider, "not provider");
        require(entryBlock[player] != 0, "no entry");
        entryBlock[player] = 0;
        uint256 draw = randomWord % 10;
        if (draw == 0) {
            (bool ok, ) = payable(player).call{value: address(this).balance}("");
            require(ok, "transfer failed");
        }
    }

    function cancel() external {
        require(entryBlock[msg.sender] != 0, "no entry");
        entryBlock[msg.sender] = 0;
    }

    receive() external payable {}
}
