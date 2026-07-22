// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title ModularVault
/// @notice An extensible vault. Functionality beyond deposit and withdrawal is
///         provided by modules, which run in the vault's own context so they
///         can read and update its state.
contract ModularVault {
    address public owner;
    address public lastModule;

    constructor() payable {
        owner = msg.sender;
    }

    /// @notice Run `data` against `module` in this contract's context.
    function execute(address module, bytes calldata data) external {
        lastModule = module;
        (bool ok, ) = module.delegatecall(data);
        require(ok, "module call failed");
    }

    /// @notice Withdraw the full balance. Restricted to the owner.
    function withdraw() external {
        require(msg.sender == owner, "not owner");
        payable(msg.sender).transfer(address(this).balance);
    }

    receive() external payable {}
}
