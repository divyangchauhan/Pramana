"""System prompts and tool schemas.

Phase 0 runs a single combined agent that does find → write PoC → report
inline. The tool *schemas* below (what the model sees) are declared once in the
canonical Anthropic shape; adapters reshape them per provider.
"""

from __future__ import annotations

from ..providers.base import ToolSchema

READ_FILE_SCHEMA: ToolSchema = {
    "name": "read_file",
    "description": "Read a text file (or list a directory) inside the audit workspace.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path, e.g. src/Vault.sol"}
        },
        "required": ["path"],
    },
}

RUN_SLITHER_SCHEMA: ToolSchema = {
    "name": "run_slither",
    "description": (
        "Run the Slither static analyzer on a single Solidity file and return a "
        "summary of its detector hits. Treat hits as leads to investigate, not findings."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path to a .sol file"}
        },
        "required": ["path"],
    },
}

WRITE_FILE_SCHEMA: ToolSchema = {
    "name": "write_file",
    "description": "Write a file inside the workspace. Use it to author Foundry PoC tests under test/.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path, e.g. test/F-001.t.sol"},
            "content": {"type": "string", "description": "Full file contents"},
        },
        "required": ["path", "content"],
    },
}

RUN_FOUNDRY_TEST_SCHEMA: ToolSchema = {
    "name": "run_foundry_test",
    "description": (
        "Compile and run the Foundry test(s) matching a path with `forge test`. "
        "The exploit is proven only if the test executes and passes."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "test_path": {
                "type": "string",
                "description": "Workspace-relative test path, e.g. test/F-001.t.sol",
            }
        },
        "required": ["test_path"],
    },
}

PHASE0_TOOLS: list[ToolSchema] = [
    READ_FILE_SCHEMA,
    RUN_SLITHER_SCHEMA,
    WRITE_FILE_SCHEMA,
    RUN_FOUNDRY_TEST_SCHEMA,
]

PHASE0_SYS = """\
You are an autonomous Solidity security auditor. Working ALONE in a Foundry \
workspace, you must find vulnerabilities in a target contract, PROVE each one \
with an executable exploit, and report the results.

WORKSPACE
- The target contract lives under src/. A Foundry project is already set up with
  forge-std available via the remapping `forge-std/=lib/forge-std/src/`.
- You have tools: read_file, run_slither, write_file, run_foundry_test.
- Write your proof-of-concept (PoC) tests under test/.

METHOD (do this for the target)
1. GROUND: read the target source with read_file. You may run_slither for leads,
   but a Slither warning is never a finding by itself — confirm it against the
   actual code, and also look for bugs Slither did not flag. Every candidate must
   cite concrete code you read.
2. PROVE: for each candidate vulnerability, write a Foundry PoC test under test/
   that triggers the claimed exploit, then run it with run_foundry_test. Your
   default assumption is that the claim is FALSE. The only accepted proof is an
   executable one: the test must run and PASS, with assertions that demonstrate
   the exploit (funds drained, ownership seized, balance minted, etc.). Iterate
   on the test if it fails to compile or does not yet demonstrate the exploit.
3. GRADE: a finding whose PoC executes and passes is "confirmed"; if you cannot
   produce a passing PoC after reasonable attempts, mark it "inconclusive".

POC TEST TEMPLATE (adapt as needed)
    // SPDX-License-Identifier: MIT
    pragma solidity ^0.8.0;
    import {Test} from "forge-std/Test.sol";
    import {Target} from "../src/Target.sol";
    contract F001Test is Test {
        function testExploit() public {
            // set up, execute the exploit, assert the impact
        }
    }

OUTPUT CONTRACT
When finished, your FINAL message must contain ONLY a single JSON object (no
prose, no markdown fences) matching exactly:
{
  "findings": [
    {
      "id": "F-001",
      "contract": "src/Target.sol",
      "location": "functionName() Lxx-yy",
      "vuln_class": "short-kebab-case class, e.g. reentrancy | access-control | tx-origin | integer-overflow | unchecked-call",
      "hypothesis": "one-sentence falsifiable claim",
      "severity": "critical | high | medium | low",
      "verdict": "confirmed | inconclusive",
      "poc_path": "test/F-001.t.sol",   // REQUIRED when confirmed; the file you wrote and ran
      "evidence": "what the passing forge run demonstrated"
    }
  ],
  "report_markdown": "A short markdown audit report: one section per confirmed finding (impact, PoC path, remediation) and a 'Needs human review' section for inconclusive ones."
}
Report every confirmed and inconclusive finding. Do not include refuted claims.
Emit the JSON object as your entire final message.
"""
