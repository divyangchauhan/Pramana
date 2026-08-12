// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Test} from "forge-std/Test.sol";
import {Lottery} from "../src/Lottery.sol";

/// A predictor mirroring the weak-randomness-lottery reference exploit: it
/// computes the *old* same-transaction draw and only plays when it predicts a
/// win. On the patched lottery entry no longer draws, so this strategy buys a
/// ticket that pays nothing at entry time.
contract Predictor {
    Lottery public lottery;

    constructor(Lottery _lottery) payable {
        lottery = _lottery;
    }

    function enterOnlyIfPredictedWin() external {
        uint256 draw = uint256(
            keccak256(abi.encodePacked(block.timestamp, block.prevrandao, address(this)))
        ) % 10;
        require(draw == 0, "would lose - not entering");
        lottery.enter{value: lottery.TICKET()}();
    }

    receive() external payable {}
}

/// Control tests — NOT exploits. Same-transaction prediction must no longer
/// guarantee the pot, and an honest player must still be able to enter and
/// settle a draw.
contract LotteryControlTest is Test {
    Lottery lottery;

    function setUp() public {
        lottery = new Lottery(); // deployer (this test) is the randomness provider
        vm.deal(address(lottery), 9 ether); // pot from previous entries
    }

    /// KB-1: entry commits to a future block's hash and pays out nothing in the
    /// same transaction, so a predictor cannot compute the result before staking.
    function testEntryNeverPaysInSameTransaction() public {
        uint256 start = block.timestamp;
        Predictor predictor = new Predictor(lottery);
        vm.deal(address(predictor), 1 ether);

        bool entered;
        for (uint256 i = 0; i < 100; i++) {
            vm.warp(start + i);
            try predictor.enterOnlyIfPredictedWin() {
                entered = true;
                break;
            } catch {
                // predicted a loss under the old formula: no ticket bought
            }
        }

        assertTrue(entered, "predictor never found a 'winning' block to test against");
        // The old prediction bought a ticket but won nothing at entry time: the
        // pot is untouched and the stake is simply gone into it.
        assertEq(address(predictor).balance, 0, "entry paid out in the same transaction");
        assertEq(address(lottery).balance, 10 ether, "pot changed at entry time");
    }

    /// Only the configured provider can settle an entry.
    function testPlayerCannotSupplyRandomness() public {
        address player = makeAddr("player");
        vm.deal(player, 1 ether);
        vm.prank(player);
        lottery.enter{value: 1 ether}();
        vm.prank(player);
        vm.expectRevert(bytes("not provider"));
        lottery.fulfillRandomness(player, 0);
    }

    /// Guards against a degenerate always-revert "fix": an honest player can
    /// enter and, once the draw block has passed, settle it without reverting.
    function testHonestEntryCanBeSettled() public {
        address player = makeAddr("player");
        vm.deal(player, 1 ether);

        vm.prank(player);
        lottery.enter{value: 1 ether}();
        assertEq(lottery.entryBlock(player), block.number, "entry not recorded");

        lottery.fulfillRandomness(player, 1); // a losing draw still settles

        assertEq(lottery.entryBlock(player), 0, "entry not cleared after claim");
    }

    /// A pending ticket can always be cleared, so delayed provider delivery
    /// cannot permanently lock the player's address.
    function testPendingEntryCanBeCancelled() public {
        address player = makeAddr("player");
        vm.deal(player, 1 ether);
        vm.prank(player);
        lottery.enter{value: 1 ether}();

        vm.roll(block.number + 1000);
        vm.prank(player);
        lottery.cancel();
        assertEq(lottery.entryBlock(player), 0, "entry not cleared by cancel");
    }
}
