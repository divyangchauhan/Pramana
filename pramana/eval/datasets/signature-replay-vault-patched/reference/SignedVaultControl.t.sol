// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Test} from "forge-std/Test.sol";
import {SignedVault} from "../src/SignedVault.sol";

/// A legitimately authorized recipient that is a contract whose receive hook
/// writes storage, costing far more than the 2300 gas stipend `transfer` would
/// forward. The fixed-gas DoS in the vulnerable twin left it unpayable.
contract StorageWritingRecipient {
    uint256 public received;

    receive() external payable {
        received += msg.value;
    }
}

/// Control tests — NOT exploits. All three of signature-replay-vault's
/// reference bugs (replay, zero-signer, fixed-gas transfer) must be neutralized,
/// and a validly authorized release must still pay out.
contract SignedVaultControlTest is Test {
    SignedVault vault;
    address signer;
    uint256 signerKey;

    function setUp() public {
        (signer, signerKey) = makeAddrAndKey("signer");
        vault = new SignedVault{value: 9 ether}(signer);
    }

    function _sign(address to, uint256 amount)
        internal
        view
        returns (uint8 v, bytes32 r, bytes32 s)
    {
        bytes32 digest = keccak256(abi.encodePacked(address(vault), block.chainid, to, amount));
        bytes32 signed = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", digest));
        return vm.sign(signerKey, signed);
    }

    /// KB-1: a used authorization cannot be replayed.
    function testReplayIsRejected() public {
        address payable recipient = payable(makeAddr("recipient"));
        uint256 amount = 3 ether;
        (uint8 v, bytes32 r, bytes32 s) = _sign(recipient, amount);

        vault.release(recipient, amount, v, r, s); // first use: authorized
        assertEq(recipient.balance, 3 ether, "first release failed");

        vm.expectRevert(bytes("authorization used"));
        vault.release(recipient, amount, v, r, s); // replay: rejected

        assertEq(recipient.balance, 3 ether, "replay paid out again");
        assertEq(address(vault).balance, 6 ether, "vault over-paid");
    }

    /// KB-2: a vault can no longer be deployed with a zero signer, so the
    /// garbage-signature bypass never exists.
    function testZeroSignerDeploymentReverts() public {
        vm.expectRevert(bytes("zero signer"));
        new SignedVault{value: 0}(address(0));
    }

    /// KB-3: an authorized contract recipient with non-trivial receive logic is
    /// now paid via a full-gas call rather than a 2300-gas transfer.
    function testAuthorizedContractRecipientIsPaid() public {
        StorageWritingRecipient recipient = new StorageWritingRecipient();
        address payable to = payable(address(recipient));
        uint256 amount = 1 ether;
        (uint8 v, bytes32 r, bytes32 s) = _sign(to, amount);

        vault.release(to, amount, v, r, s);

        assertEq(address(recipient).balance, 1 ether, "contract recipient not paid");
        assertEq(recipient.received(), 1 ether, "receive hook did not run");
        assertEq(address(vault).balance, 8 ether, "wrong amount left the vault");
    }
}
