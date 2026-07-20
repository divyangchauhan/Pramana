// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title EtherStore
/// @notice A minimal ETH vault modeled on the reentrancy bug behind "The DAO"
///         hack (2016). Users deposit ETH and can withdraw their balance.
///
/// The withdraw() function performs the external value transfer BEFORE it
/// updates internal accounting, so a malicious receiver can re-enter withdraw()
/// from its fallback and repeatedly pull funds while its recorded balance is
/// still non-zero — draining every depositor.
contract EtherStore {
    mapping(address => uint256) public balances;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    function withdraw() external {
        uint256 bal = balances[msg.sender];
        require(bal > 0, "no balance");

        // INTERACTION before EFFECT: the callee regains control here.
        (bool ok, ) = msg.sender.call{value: bal}("");
        require(ok, "transfer failed");

        // EFFECT applied too late — reentrant calls above still see `bal`.
        balances[msg.sender] = 0;
    }

    function balanceOf(address who) external view returns (uint256) {
        return balances[who];
    }
}
