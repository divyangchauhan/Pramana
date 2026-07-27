"""Reporter (Nirnaya) — writes the deliverable (design §3.3).

The reporter is the pipeline's only genuinely cheap slot: by the time it runs,
every claim has already been proven or killed by the verifier, so this stage is
synthesis, not open-ended reasoning. It gets no tools — it reasons only over the
verdicts it is handed.

Crucially, it does not get to *change* those verdicts. It receives the governed
facts (severity, PoC path, verdict, deployment-contingent flag) so its prose can
be accurate, but its output carries none of them back: it returns description,
impact, remediation, an optional executive summary, and — the one structural
call it is uniquely placed to make — cross-finding duplicate links. The renderer
weaves that prose into a skeleton built from the verdicts themselves, so a
reporter that misremembered a severity or dropped a finding cannot corrupt the
record (see :class:`pramana.contracts.ReportEntry`).
"""

from __future__ import annotations

import json

from ..providers.base import ToolSchema

# No tools. The reporter synthesizes the verdicts it is given and nothing else;
# handing it read_file would invite it to re-audit and second-guess proofs the
# verifier already settled.
REPORTER_TOOLS: list[ToolSchema] = []

REPORTER_SYS = """\
You are a smart-contract audit reporter. Another agent has already found each \
vulnerability, and a separate adversarial verifier has already PROVEN or killed \
each one with an executable proof-of-concept. Your job is to write the client's \
deliverable from those settled verdicts. You are NOT re-auditing the code.

WHAT IS AND IS NOT YOURS TO DECIDE
The verdict, the severity, the PoC path, and the count of findings are FIXED.
They were established by executable proof and are not yours to change, restate
differently, or second-guess. Do not invent a severity, do not promote a
finder's guess to a verified grade, do not add or drop findings. Your
contribution is PROSE plus one structural judgment (duplicates, below).

For each CONFIRMED finding, write:
- description: what the flaw is, in plain language a client can act on, grounded
  in the hypothesis and evidence you were given.
- impact: what an attacker gains or the protocol loses when it is exploited.
- remediation: the concrete fix (e.g. checks-effects-interactions, a zero-check,
  an access-control modifier). Be specific to this bug, not generic advice.

For each NEEDS-REVIEW finding, write a description and impact framed as
UNVERIFIED: automated proof was inconclusive, so a human must judge it. Never
present its finder severity guess as authoritative.

CROSS-FINDING DUPLICATES
You are the only stage that sees every finding at once; each verifier saw one
claim in isolation and could not tell two claims were the same underlying bug.
If two confirmed findings share ONE root cause and ONE fix, set `duplicate_of`
on the later one to the id of the earlier (primary) one. This annotates the
report; it does not delete the finding. Do NOT collapse findings that merely
sit in the same function or the same class but have distinct root causes.

OUTPUT CONTRACT
Your FINAL message must contain ONLY a JSON object (no prose outside it, no
markdown fences):
{
  "summary": "2-4 sentence executive summary: confirmed count, headline risk, review count",
  "entries": [
    {
      "finding_id": "F-001",
      "description": "...",
      "impact": "...",
      "remediation": "...",
      "duplicate_of": null
    }
  ]
}
Include one entry per finding you were given (confirmed and needs-review), keyed
by its exact finding_id. Omit `remediation` (or leave it empty) for needs-review
entries. Emit the JSON object as your entire final message.
"""


def build_reporter_seed(
    confirmed: list[dict[str, object]],
    needs_review: list[dict[str, object]],
) -> str:
    """Seed Nirnaya with the two governed lists (design §3.3).

    Refuted findings are already excluded upstream — they never reach here, so
    they cannot appear in the deliverable. The severity and PoC path are passed
    for context only; the renderer, not the reporter, is what puts them in the
    report.
    """
    payload = {
        "confirmed_findings": confirmed,
        "needs_human_review": needs_review,
    }
    return (
        "Write the audit deliverable for the findings below. The verdicts and "
        "severities are already settled — do not change them.\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Return the JSON object per the output contract: an executive summary "
        "and one prose entry per finding, keyed by finding_id."
    )
