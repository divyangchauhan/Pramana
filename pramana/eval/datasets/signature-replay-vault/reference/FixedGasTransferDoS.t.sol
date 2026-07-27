// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Test} from "forge-std/Test.sol";
import {SignedVault} from "../src/SignedVault.sol";

/// A legitimately authorized recipient that happens to be a contract whose
/// receive hook writes storage, costing far more than the 2300 gas stipend that
/// `transfer` forwards.
contract StorageWritingRecipient {
    uint256 public received;

    receive() external payable {
        received += msg.value; // SSTORE — well over the 2300 gas stipend
    }
}

/// Reference exploit: `release` pays out with `to.transfer(amount)`, whose fixed
/// 2300 gas stipend cannot cover a recipient with non-trivial receive logic. A
/// validly authorized contract recipient can therefore never be paid — the
/// transfer reverts and the funds are stranded, since `release` is the only
/// withdrawal path. No misconfiguration required.
contract FixedGasTransferDoSTest is Test {
    SignedVault vault;
    address signer;
    uint256 signerKey;
    StorageWritingRecipient recipient;

    function setUp() public {
        (signer, signerKey) = makeAddrAndKey("signer");
        vault = new SignedVault{value: 5 ether}(signer);
        recipient = new StorageWritingRecipient();
    }

    function testAuthorizedContractRecipientCanNeverBePaid() public {
        uint256 amount = 1 ether;
        address payable to = payable(address(recipient));
        bytes32 digest = keccak256(abi.encodePacked(to, amount));
        bytes32 signed = keccak256(
            abi.encodePacked("\x19Ethereum Signed Message:\n32", digest)
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(signerKey, signed);

        // A perfectly valid authorization, yet the payout reverts on the
        // 2300-gas transfer to a storage-writing recipient.
        vm.expectRevert();
        vault.release(to, amount, v, r, s);

        assertEq(address(recipient).balance, 0, "recipient somehow got paid");
        assertEq(address(vault).balance, 5 ether, "funds should be stranded");
    }
}
