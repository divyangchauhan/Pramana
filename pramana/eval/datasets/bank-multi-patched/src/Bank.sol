// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title Bank
/// @notice A deposit vault with an administrator. Depositors may withdraw their
///         own balance; the admin can sweep the contract's funds to a chosen
///         address, e.g. when migrating to a new deployment.
contract Bank {
    mapping(address => uint256) public balances;
    address public admin;

    constructor() {
        admin = msg.sender;
    }

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

    /// @notice Hand administration to `newAdmin`.
    function setAdmin(address newAdmin) external {
        require(msg.sender == admin, "not admin");
        require(newAdmin != address(0), "zero admin");
        admin = newAdmin;
    }

    /// @notice Move the full contract balance to `to`.
    function sweep(address payable to) external {
        require(msg.sender == admin, "not admin");
        require(to != address(0), "zero recipient");
        (bool ok, ) = to.call{value: address(this).balance}("");
        require(ok, "transfer failed");
    }

    receive() external payable {}
}
