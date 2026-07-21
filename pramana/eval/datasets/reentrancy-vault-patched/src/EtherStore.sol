// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title EtherStore
/// @notice A minimal ETH vault modeled on the reentrancy bug behind "The DAO"
///         hack (2016). Users deposit ETH and can withdraw their balance.
///
/// The withdraw() function updates internal accounting BEFORE it performs the
/// external value transfer, so a malicious receiver that re-enters withdraw()
/// from its fallback finds its recorded balance already zeroed and is refused.
contract EtherStore {
    mapping(address => uint256) public balances;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    function withdraw() external {
        uint256 bal = balances[msg.sender];
        require(bal > 0, "no balance");

        // EFFECT applied first — a reentrant call sees a zero balance.
        balances[msg.sender] = 0;

        // INTERACTION last: the callee regains control here, but has nothing
        // left to withdraw.
        (bool ok, ) = msg.sender.call{value: bal}("");
        require(ok, "transfer failed");
    }

    function balanceOf(address who) external view returns (uint256) {
        return balances[who];
    }
}
