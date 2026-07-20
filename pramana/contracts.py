"""Typed payloads passed across pipeline boundaries (design §4), validated with
Pydantic. Rejecting malformed model output *at the boundary* is part of the
reliability story.

Phase 0 runs one combined agent, so it emits :class:`Phase0Output` (findings +
report). :class:`Finding` and :class:`Verdict` are the finder→verifier and
verifier→reporter contracts used once the pipeline is split in later phases.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

VerdictLabel = Literal["confirmed", "inconclusive", "refuted"]
Severity = Literal["critical", "high", "medium", "low", "informational"]


class Finding(BaseModel):
    """Finder → verifier. The verifier is seeded with only the bare-claim fields."""

    id: str
    contract: str
    location: str
    vuln_class: str
    hypothesis: str
    severity_guess: Severity | None = None
    finder_notes: str | None = None  # NOT passed to the verifier


class Verdict(BaseModel):
    """Verifier → orchestrator → reporter."""

    finding_id: str
    verdict: VerdictLabel
    severity: Severity | None = None
    poc_path: str | None = None
    evidence: str | None = None
    attempts: int = 0


class Phase0Finding(BaseModel):
    """One finding from the Phase 0 combined agent (find + prove + grade)."""

    id: str
    contract: str
    location: str = ""
    vuln_class: str
    hypothesis: str = ""
    severity: Severity | None = None
    verdict: VerdictLabel
    poc_path: str | None = None
    evidence: str | None = None


class Phase0Output(BaseModel):
    """The combined agent's final JSON payload."""

    findings: list[Phase0Finding] = Field(default_factory=list)
    report_markdown: str = ""


class OutputParseError(ValueError):
    """Raised when the agent's final message is not valid Phase0Output JSON."""


def _extract_json_object(text: str) -> str:
    """Pull the outermost {...} object out of a final message, tolerating stray
    prose or ```json fences around it."""
    start = text.find("{")
    if start == -1:
        raise OutputParseError("no JSON object found in agent output")

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise OutputParseError("unterminated JSON object in agent output")


def parse_phase0_output(text: str) -> Phase0Output:
    raw = _extract_json_object(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OutputParseError(f"agent output is not valid JSON: {exc}") from exc
    try:
        return Phase0Output.model_validate(data)
    except ValidationError as exc:
        raise OutputParseError(f"agent output failed schema validation: {exc}") from exc
