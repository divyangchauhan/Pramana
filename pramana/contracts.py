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
    """Raised when an agent's final message is not valid JSON for its contract."""


# The bare-claim fields the verifier is seeded with. Everything else the finder
# produced — notably `finder_notes` and `severity_guess` — is withheld, so the
# verifier cannot inherit the finder's confidence or reasoning.
BARE_CLAIM_FIELDS = ("contract", "location", "vuln_class", "hypothesis")


def bare_claim(finding: Finding) -> dict[str, str]:
    """The only thing a verifier is allowed to see about a finding (design §4).

    This is the isolation boundary. It is a whitelist, not a blacklist: adding a
    field to :class:`Finding` cannot silently leak it to the verifier.
    """
    return {field: getattr(finding, field) for field in BARE_CLAIM_FIELDS}


def _balanced_span(text: str, start: int, open_ch: str, close_ch: str) -> str | None:
    """The balanced ``open_ch...close_ch`` span beginning at ``start``, or None
    if it is never closed. String contents (and escapes) are skipped, so a
    bracket inside a JSON string does not confuse the depth count."""
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
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _json_candidates(text: str) -> list[object]:
    """Every balanced JSON span in ``text`` that parses, in order of appearance.

    Agents are asked to emit only JSON, but they routinely add a sentence or a
    ```json fence — and that prose can itself contain brackets ("uses the
    checks-effects-interactions [CEI] pattern"). Committing to the *first*
    bracket therefore parses the prose instead of the answer, so collect every
    candidate and let the caller pick the one matching its schema.
    """
    candidates: list[object] = []
    consumed_until = 0
    for i, ch in enumerate(text):
        # Only top-level spans are answers. Without this, the empty array inside
        # `{"not_findings": []}` would be picked up as a valid "no findings"
        # result, silently laundering malformed output into a clean verdict.
        if i < consumed_until or ch not in "[{":
            continue
        raw = _balanced_span(text, i, ch, "]" if ch == "[" else "}")
        if raw is None:
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates.append(value)
        consumed_until = i + len(raw)
    return candidates


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise OutputParseError("no JSON object found in agent output")
    raw = _balanced_span(text, start, "{", "}")
    if raw is None:
        raise OutputParseError("unterminated JSON object in agent output")
    return raw


def _loads(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OutputParseError(f"agent output is not valid JSON: {exc}") from exc


def parse_findings(text: str) -> list[Finding]:
    """Finder boundary: a JSON array of Finding objects.

    The contract asks for a bare array, but models routinely wrap it in
    ``{"findings": [...]}``; both are accepted since the meaning is unambiguous.
    An empty array is a valid answer — it is how "this contract is clean" is
    expressed, which is exactly what a negative control must produce.
    """
    candidates = _json_candidates(text)
    if not candidates:
        raise OutputParseError("no JSON array or object found in finder output")

    last_error: ValidationError | None = None
    for value in candidates:
        # Accept a bare array or the {"findings": [...]} wrapper models often use.
        if isinstance(value, dict):
            if "findings" not in value:
                continue
            value = value["findings"]
        if not isinstance(value, list):
            continue
        try:
            return [Finding.model_validate(item) for item in value]
        except ValidationError as exc:
            # Shape matched but content did not. Keep looking — an earlier
            # candidate may be prose — but remember it, so a genuinely
            # malformed findings array reports its error instead of being
            # silently read as "no findings".
            last_error = exc

    if last_error is not None:
        raise OutputParseError(
            f"finder output failed schema validation: {last_error}"
        ) from last_error
    raise OutputParseError("no JSON array of findings found in finder output")


def parse_verdict(text: str) -> Verdict:
    """Verifier boundary: a single JSON Verdict object.

    ``finding_id`` and ``verdict`` are required, so schema validation is itself
    a reliable filter against a stray brace in surrounding prose.
    """
    last_error: ValidationError | None = None
    for value in _json_candidates(text):
        if not isinstance(value, dict):
            continue
        try:
            return Verdict.model_validate(value)
        except ValidationError as exc:
            last_error = exc

    if last_error is not None:
        raise OutputParseError(
            f"verifier output failed schema validation: {last_error}"
        ) from last_error
    raise OutputParseError("no JSON verdict object found in verifier output")


def parse_phase0_output(text: str) -> Phase0Output:
    """Phase 0 boundary: findings + report in one object.

    Every field of :class:`Phase0Output` has a default, so *any* JSON object
    validates — including a stray one from prose, which would silently parse as
    "no findings". Candidates are therefore filtered on carrying at least one of
    the contract's own keys before validation is attempted.
    """
    candidates = [v for v in _json_candidates(text) if isinstance(v, dict)]
    payloads = [v for v in candidates if {"findings", "report_markdown"} & set(v)]

    last_error: ValidationError | None = None
    for value in payloads or candidates[:1]:
        try:
            return Phase0Output.model_validate(value)
        except ValidationError as exc:
            last_error = exc

    if last_error is not None:
        raise OutputParseError(
            f"agent output failed schema validation: {last_error}"
        ) from last_error
    _extract_json_object(text)  # raises the precise "no/unterminated JSON object" error
    raise OutputParseError("no JSON object found in agent output")
