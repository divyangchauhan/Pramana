// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title EtherStore
/// @notice A minimal ETH vault. Users deposit ETH and can withdraw their full
///         balance at any time. Balances are tracked per depositor.
contract EtherStore {
    mapping(address => uint256) public balances;

    /// @notice Deposit ETH and credit it to the sender.
    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    /// @notice Withdraw the caller's entire balance.
    function withdraw() external {
        uint256 bal = balances[msg.sender];
        require(bal > 0, "no balance");

        balances[msg.sender] = 0;

        (bool ok, ) = msg.sender.call{value: bal}("");
        require(ok, "transfer failed");
    }

    /// @notice The ETH currently credited to `who`.
    function balanceOf(address who) external view returns (uint256) {
        return balances[who];
    }
}
