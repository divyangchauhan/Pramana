// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title SignedVault
/// @notice Holds funds that are released against an authorization signed by a
///         designated signer. This lets a recipient collect without the signer
///         having to send a transaction and pay gas.
contract SignedVault {
    address public signer;

    constructor(address _signer) payable {
        signer = _signer;
    }

    /// @notice Release `amount` to `to`, given the signer's authorization.
    function release(address payable to, uint256 amount, uint8 v, bytes32 r, bytes32 s) external {
        bytes32 digest = keccak256(abi.encodePacked(to, amount));
        bytes32 signed = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", digest));

        require(ecrecover(signed, v, r, s) == signer, "bad signature");

        to.transfer(amount);
    }

    receive() external payable {}
}
