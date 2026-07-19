# Pramana — Multi-Agent Smart Contract Audit Pipeline

**System design & staged build plan.**

*(Naming — **settled**, see `PRD.md`/`ARCHITECTURE.md`. **Pramāṇa** — प्रमाण, "a valid means of knowledge / proof" — is the **system** name; a finding counts as knowledge only once it's been proven. The three agents have fixed Sanskrit identities: **Anumana** (finder / inference), **Khandana** (verifier / refutation), **Nirnaya** (reporter / conclusion). This document uses the generic role words **finder / verifier / reporter** for readability, but they map one-to-one onto Anumana / Khandana / Nirnaya respectively — these are not open choices to "swap freely.")*

---

## 0. The one idea

You do **not** write three agents. You write **one provider-neutral agent loop, as a function**, and call it three times with different configs:

```python
run_agent(llm, system_prompt, tools, tool_registry, seed) -> (final_output, messages)
```

Each call builds its own fresh `messages` list *inside* the function. So three isolated agents = three calls. Context isolation (the verifier can't see the finder's reasoning) is enforced by the fact that each call has a physically separate `messages` list — not by a rule you hope the model follows.

The "orchestrator" is just plain Python that calls this function three times and passes small JSON payloads between the calls.

---

## 1. The generalized, provider-neutral agent loop

The core loop must not import Anthropic, OpenAI, or any other lab's SDK. Instead, it consumes a small adapter interface that normalizes messages, tool calls, tool results, usage, and finish reasons. Provider-specific code lives behind that boundary.

```python
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    raw: Any
    usage: dict[str, int]


@dataclass
class ToolResult:
    """Canonical tool result. The loop produces these; each adapter serializes
    them into its provider's wire format (Anthropic `tool_result` block, OpenAI
    `tool` message, …). No provider-specific shape lives in the core."""
    call_id: str
    content: str
    is_error: bool


class LLMAdapter(Protocol):
    def complete(self, *, model, system, tools, messages,
                 max_tokens) -> LLMResponse: ...


def run_agent(llm, system_prompt, tools, tool_registry, seed,
              model, max_turns=25):
    """One agent = one loop. Its `messages` list is created fresh here, so it is
    fully isolated from every other agent's context. Returns the final text plus
    the full message history (useful for logging / eval)."""
    messages = [{"role": "user", "content": seed}]

    for _ in range(max_turns):                     # bounded, not `while True`
        response = llm.complete(
            model=model,
            max_tokens=40960,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )
        messages.append({
            "role": "assistant",
            "content": response.text,
            "tool_calls": response.tool_calls,
        })

        if not response.tool_calls:
            return response.text, messages          # agent is done

        # The model asked to call one or more tools. Run them, feed results back.
        tool_results = [
            dispatch(call, tool_registry)
            for call in response.tool_calls
        ]
        messages.append({"role": "tool", "content": tool_results})

    raise RuntimeError("agent exceeded max_turns")  # reliability guard
```

`AnthropicAdapter`, `OpenAIAdapter`, and adapters for other labs translate this canonical representation to and from their native SDK formats. For example, an Anthropic adapter maps content blocks and `tool_use`; an OpenAI adapter maps Responses API function calls. The rest of Pramana never branches on provider name.

Configure providers and models by role rather than hard-coding them:

```yaml
agents:
  finder:   { provider: anthropic, model: <reasoning-model-id> }   # hard task — not the cheap slot
  verifier: { provider: openai,    model: <reasoning-model-id> }   # hard task — not the cheap slot
  reporter: { provider: other_lab, model: <synthesis-model-id> }   # formatting — the cheap slot
```

The same provider may serve every role, or each role may use a different lab. Exact model IDs are deployment configuration, pinned and recorded with every run.

Which model is actually best per role is an **empirical question**, and the eval harness (§8) is the instrument for answering it — re-run the same fixtures across configurations and compare. Nothing in this design pre-assigns a tier to a role on cost grounds; expect this config to be swept many times before any of its values are treated as settled.

Adapters must expose capability metadata and fail during startup when a selected model lacks a required feature (notably tool calling or structured JSON output). They also own authentication, retry/rate-limit translation, and provider-specific request options; the agent loop owns the provider-independent turn budget and tool execution policy. Never silently fall back to a different provider or model, because that makes audit results and costs irreproducible.

---

## 2. Tool calling, generalized

A tool is still just **a schema (what the model sees) + a function (what you run)**. The upgrade is a *registry* so the loop can dispatch any tool by name, plus error handling — because real tools (Foundry compiles, Anvil RPC, fuzzers) crash and time out constantly.

```python
import subprocess
from pathlib import Path


# --- the functions (what YOU run) ---
def read_file(path):
    return Path(path).read_text()

def run_slither(path):
    out = subprocess.run(["slither", path, "--json", "-"],
                         capture_output=True, text=True, timeout=120)
    return out.stdout or out.stderr

def run_foundry_test(test_path):
    out = subprocess.run(["forge", "test", "--match-path", test_path, "-vvv"],
                         capture_output=True, text=True, timeout=300)
    return out.stdout + out.stderr          # forge exit code tells you pass/fail

def write_file(path, content):
    Path(path).write_text(content)
    return f"wrote {path}"


# --- the registry: tool name -> function ---
TOOL_REGISTRY = {
    "read_file": read_file,
    "run_slither": run_slither,
    "run_foundry_test": run_foundry_test,
    "write_file": write_file,
}


# --- dispatch: run the requested tool, never let a crash kill the loop ---
def dispatch(call, tool_registry) -> ToolResult:
    fn = tool_registry.get(call.name)
    try:
        if fn is None:
            raise KeyError(f"unknown tool {call.name}")
        output, is_error = fn(**call.arguments), False
    except Exception as e:                  # tool crashed / timed out -> tell the model
        output, is_error = f"Tool error: {e}", True
    return ToolResult(                       # canonical shape; the adapter serializes it
        call_id=call.id,
        content=str(output)[:20000],         # truncate to protect the context window
        is_error=is_error,
    )
```

The matching JSON **schemas** (what the model sees) are declared separately and handed to whichever agent should have that tool. Each schema looks like:

```python
READ_FILE_SCHEMA = {
    "name": "read_file",
    "description": "Read the contents of a text file on disk.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "File path to read"}},
        "required": ["path"],
    },
}
# ...and one each for run_slither, run_foundry_test, write_file.
```

**Key design move:** give each agent only the tools it needs. The finder gets read/analysis tools; only the verifier gets the ability to write and run Foundry tests. Tool scope *is* role definition.

---

## 3. The three agents

Each agent is one `run_agent(...)` call. What makes them different is **system prompt**, **tool set**, **seed**, and a provider/model profile. Finding vulnerabilities and proving them are both hard reasoning tasks and both get strong models; only the reporter, which formats verdicts already decided, is a cheap slot. Roles need not use the same lab.

### 3.1 Finder (Anumana) — proposes grounded hypotheses

- **Model profile:** a **strong reasoning model** with reliable structured output and tool use — the same tier as the verifier. Proposing a falsifiable exploit hypothesis over unfamiliar Solidity is not a cheap-model task: a weak finder both misses real bugs *and* floods the verifier with unfalsifiable noise, hurting recall and cost at the same time. Choose and pin a concrete model from any supported lab at deployment time, and let the eval harness (§8) tell you which one actually performs best here.
- **Tools:** `read_file`, `run_slither`.
- **Seed:** the contract path + Slither's raw output.
- **Job:** use Slither as a prioritized signal source, then read the actual Solidity at each flagged location and trace the relevant surrounding code, state changes, calls, inheritance, and cross-contract interactions. Slither warnings are leads, not findings: the finder must confirm that the source supports an exploitable hypothesis rather than merely restating analyzer output. While following those leads, it may also identify vulnerabilities Slither did not flag, but every candidate must cite concrete code it inspected.
- **Output contract:** a JSON array of findings (schema in §4).

System prompt sketch:
```
You are a Solidity vulnerability finder. You are given a contract path and the
output of Slither (a static analyzer). Treat each Slither signal as a lead, not a
conclusion. Use read_file to inspect the referenced Solidity, its surrounding
function, relevant state transitions and call paths, and related contracts or
base classes when needed. Determine whether the code supports a concrete,
falsifiable exploit hypothesis. You may report a vulnerability Slither did not
flag if you discover it during this source review, but every candidate must be
grounded in specific code you actually read. Do not merely restate Slither and
do not speculate beyond the source. Output ONLY a JSON array matching the Finding
schema, no prose.
```

The required grounding sequence is **Slither signal → Solidity source read → relevant flow trace → candidate finding**. A Slither warning without source evidence produces no finding; source review is the step that turns an analyzer hint into a vulnerability hypothesis.

### 3.2 Verifier (Khandana) — proves or kills each claim

This is the heart of the system. Its value comes entirely from **not** sharing the finder's reasoning, and from making verification **executable, not conversational**.

- **Model profile:** the strongest available reasoning/coding model that can reliably author and iterate on Foundry tests. It may come from any supported lab. Along with the finder, this is where higher inference cost is worth paying — hypothesising the bug and proving it are the two hard halves of the same job.
- **Tools:** `read_file`, `write_file`, `run_foundry_test`. (Optionally `run_halmos` / `run_echidna` for symbolic/property checks.)
- **Seed:** **only one finding's bare claim** — `{contract, location, vuln_class, hypothesis}`. Never the finder's chain of thought. This is the isolation: a fresh `messages` list seeded with the claim alone.
- **Job:** *disprove the claim.* Write a Foundry test that would trigger the exploit; run it against a local Anvil fork. The finding is **real only if the PoC executes and demonstrates the exploit.** If no working PoC after N attempts → `inconclusive`, downgrade to "needs human review."
- **Output contract:** a JSON verdict (schema in §4).

System prompt sketch:
```
You are an adversarial verifier. You are given a SINGLE alleged vulnerability.
Your default assumption is that it is FALSE. Your only accepted proof is an
executable one: write a Foundry test that triggers the claimed exploit and run it
against a local fork. If the test demonstrates the exploit, verdict = "confirmed"
and return the PoC path. If you cannot produce a working PoC after N attempts,
verdict = "inconclusive". Never accept the claim on reasoning alone.
```

> This one design choice — *"my false-positive rate isn't a vibe, it's whether a PoC executes"* — is the line between a demo and something production-grade.

### 3.3 Reporter (Nirnaya) — writes the deliverable

- **Model profile:** a lower-cost synthesis model with strong instruction following; this stage is formatting, not open-ended reasoning — the pipeline's only genuinely cheap slot.
- **Tools:** none needed (optionally `read_file` for extra context).
- **Seed:** two explicitly separated lists: **confirmed findings** with their PoC paths, and **inconclusive findings that need human review**. Refuted findings are omitted from the deliverable.
- **Output:** a structured markdown audit report split into two top-level sections:
  1. **Confirmed findings** — one subsection per finding with description, impact, verifier-assigned severity, PoC, evidence, and remediation.
  2. **Needs human review** — one subsection per inconclusive finding with the original hypothesis, location, verification attempts, available evidence, and why automated verification was inconclusive. Any finder severity is clearly labeled as an unverified guess, never as an authoritative grade.

---

## 4. The contracts (JSON passed between agents)

The whole pipeline runs on two small typed payloads. These are what make the handoffs unambiguous.

**Finding** (finder → verifier). The verifier is seeded with only the starred fields.

```json
{
  "id": "F-001",
  "contract": "src/Vault.sol",          
  "location": "withdraw() L84-96",       
  "vuln_class": "reentrancy",            
  "hypothesis": "External call before state update lets a malicious receiver re-enter withdraw and drain balance.",  
  "severity_guess": "high",
  "finder_notes": "…"                    // NOT passed to the verifier
}
```

**Verdict** (verifier → orchestrator → reporter):

```json
{
  "finding_id": "F-001",
  "verdict": "confirmed",                // confirmed | refuted | inconclusive
  "severity": "high",                    // authoritative, evidence-backed; required on "confirmed"
  "poc_path": "test/poc/F-001_reentrancy.t.sol",
  "evidence": "forge test output: assertion passed, balance drained from 100 to 0",
  "attempts": 2                          // one attempt = one executed forge run; bounded by N
}
```

The verifier — not the finder — owns severity for confirmed findings: it grades the impact its PoC actually demonstrated, so the reporter never presents the finder's unverified `severity_guess` as a verified grade. Note `attempts` counts *executed PoC runs*, which is a different axis from the loop's `max_turns` (model round-trips); the two must not be conflated.

Enforce these with `json.loads` at each boundary (and, if you want it bulletproof, validate against a real JSON Schema or a Pydantic model). Rejecting malformed output *at the boundary* is another piece of the reliability story.

---

## 5. The orchestrator

Plain Python. This is the entire "multi-agent" layer.

```python
import json

def audit(contract_path, adapters, agent_config):
    # Grounding: run the static analyzer once, cache it.
    slither_out = run_slither(contract_path)

    # --- Agent 1: Finder (one call, its own context) ---
    finder_seed = (
        f"Contract path: {contract_path}\n\nSlither output:\n{slither_out}\n\n"
        "Propose candidate findings as a JSON array."
    )
    finder_out, _ = run_agent(
        adapters[agent_config["finder"]["provider"]],
        FINDER_SYS, [READ_FILE_SCHEMA, RUN_SLITHER_SCHEMA], TOOL_REGISTRY,
        seed=finder_seed, model=agent_config["finder"]["model"],
    )
    findings = json.loads(finder_out)

    # --- Agent 2: Verifier, once PER finding, each in a fresh isolated context ---
    confirmed = []
    needs_human_review = []
    for f in findings:
        bare_claim = {k: f[k] for k in ("contract", "location", "vuln_class", "hypothesis")}
        verdict_out, _ = run_agent(
            adapters[agent_config["verifier"]["provider"]],
            VERIFIER_SYS,
            [READ_FILE_SCHEMA, WRITE_FILE_SCHEMA, RUN_FOUNDRY_TEST_SCHEMA], TOOL_REGISTRY,
            seed=json.dumps(bare_claim),      # ONLY the claim — this is the isolation
            model=agent_config["verifier"]["model"],
        )
        v = json.loads(verdict_out)
        if v["verdict"] == "confirmed":
            confirmed.append({**f, **v})
        elif v["verdict"] == "inconclusive":
            needs_human_review.append({**f, **v})
        # Refuted findings are retained in the trace/eval data, not the audit report.

    # --- Agent 3: Reporter (one call) ---
    report_input = {
        "confirmed_findings": confirmed,
        "needs_human_review": needs_human_review,
    }
    report, _ = run_agent(
        adapters[agent_config["reporter"]["provider"]],
        REPORTER_SYS, [], TOOL_REGISTRY,
        seed=json.dumps(report_input), model=agent_config["reporter"]["model"],
    )

    # Keep the counts — the eval and review-queue metrics fall right out of here.
    return {
        "report": report,
        "n_candidates": len(findings),
        "n_confirmed": len(confirmed),
        "n_needs_human_review": len(needs_human_review),
    }
```

The reporter therefore receives every finding that still requires action, but the report keeps epistemic status explicit: executable proofs appear under **Confirmed findings**, while inconclusive cases appear under **Needs human review**. Refuted claims do not appear in the client-facing report. For a live audit, `n_confirmed` is the number of verified findings delivered; `n_needs_human_review` is the separate manual-review queue. On labeled evaluation fixtures, the headline score is the number of confirmed findings that match known real vulnerabilities — the **true-positive finding count**. Candidate volume and false-positive reduction are supporting diagnostics, not the headline.

---

## 6. Tool inventory & wiring order

| Tool | Runs | Given to | Purpose |
|---|---|---|---|
| `run_slither` | before finder | Finder | Produce prioritized static-analysis leads; warnings are not accepted as findings by themselves |
| `read_file` | after signals and as needed | Finder, Verifier | Inspect the actual Solidity and trace the code paths needed to support or refute a hypothesis |
| `write_file` | verify phase | Verifier | Write the Foundry PoC test |
| `run_foundry_test` | verify phase | Verifier | Execute the PoC on an Anvil fork → ground truth |
| `run_echidna` / `run_halmos` | verify phase (optional) | Verifier | Property fuzzing / symbolic confirmation |

Wiring order: **Slither first** to prioritize suspicious locations, then the finder reads the relevant Solidity and reasons over **both** the analyzer signals and the source-level execution flow. Slither narrows the search; it does not replace code review or determine the finding. The verifier then lives almost entirely in Foundry/Anvil. Fuzzers belong on the *verification* side, not the finding side.

---

## 7. Repo layout

```
pramana/
├── providers/
│   ├── base.py            # LLMAdapter, LLMResponse, ToolCall
│   ├── anthropic.py       # Anthropic SDK translation only
│   ├── openai.py          # OpenAI SDK translation only
│   └── other.py           # additional lab or OpenAI-compatible adapters
├── agents/
│   ├── loop.py            # provider-neutral run_agent (§1)
│   ├── finder.py          # FINDER_SYS + tool schema list
│   ├── verifier.py        # VERIFIER_SYS + tool schema list
│   └── reporter.py        # REPORTER_SYS
├── tools/
│   ├── registry.py        # TOOL_REGISTRY, dispatch  (§2)
│   ├── slither.py
│   ├── foundry.py         # write + run Foundry tests against Anvil
│   └── files.py
├── contracts_schema.py    # Finding / Verdict schemas + validation  (§4)
├── orchestrator.py        # audit()  (§5)
├── eval/
│   ├── datasets/          # known-vuln fixtures (see §8)
│   ├── harness.py         # runs audit() over fixtures, counts true positives + supporting metrics
│   └── report.md          # eval results
├── observability/
│   └── trace.py           # structured per-step / per-tool logging  (§9)
└── targets/               # contracts under audit, incl. your kleros fixtures
```

---

## 8. Evaluation harness (build this from day one)

The eval is what makes the whole thing credible; it is *not* an afterthought. Ground truth is available:

- **Code4rena / Sherlock** past contests — public findings with known bugs.
- **DeFiHackLabs** — real exploits with reference PoCs.
- **SWC registry** — classic vulnerability classes.
- **EVMbench** (OpenAI's smart-contract benchmark) — high-severity bugs from real repositories with executable local-EVM graders; its detection tasks and programmatic exploit checks map closely onto the finder/verifier model. Deduplicate overlapping Code4rena/Sherlock cases before scoring.

Each fixture is a contract + the set of *known* real vulnerabilities in it (the ground-truth label set).

Add negative controls, preferably as vulnerable/patched revision pairs. The vulnerable revision keeps the known label and a passing exploit test; the patched revision has no label for that issue and the same exploit must fail. Audit both independently with pair metadata hidden from the agents. Findings retained on patched code are false positives, and empty-label fixtures are excluded from recall while contributing to a separately reported negative-control false-positive rate.

**The headline number: true-positive findings confirmed with executable PoCs.**

A true positive is a confirmed finding that matches a known real vulnerability in the fixture. Compare configurations on the same fixed fixture set so the count is meaningful.

```python
def evaluate(fixtures):
    rows = []
    total_true_positives = 0

    for fx in fixtures:
        result = audit(fx.contract_path)
        candidate_tp = tp(fx.known_bugs, result["n_candidates_labeled"])
        confirmed_tp = tp(fx.known_bugs, result["confirmed_labeled"])
        total_true_positives += confirmed_tp

        rows.append({
            "fixture": fx.name,
            "true_positive_findings": confirmed_tp,  # headline contribution
            "finder_precision": candidate_tp / result["n_candidates"] if result["n_candidates"] else None,
            "verifier_precision": confirmed_tp / result["n_confirmed"] if result["n_confirmed"] else None,
            "recall": confirmed_tp / len(fx.known_bugs) if fx.known_bugs else None,
        })

    return {
        "true_positive_findings": total_true_positives,  # headline number
        "fixtures": rows,
    }
```

This produces: *"The pipeline confirmed T known real vulnerabilities with executable PoCs."* Candidate count, confirmed count, precision before/after verification, recall, negative-control false-positive rate, the human-review queue, and cost remain supporting metrics that explain the quality and efficiency behind that headline.

**Run the same fixtures across model configurations.** Which model belongs in each role — the finder especially — is a question this harness answers empirically, by comparing recall and finder precision on fixed fixtures. It is not settled by assuming the finder is the cheap slot. Stamp each row with the config that produced it, and treat a config that cuts cost while cutting recall as a regression.

---

## 9. Reliability, observability, cost

- **Reliability:** bounded loops (`max_turns`), `dispatch` never lets a tool crash kill the run, malformed JSON rejected at each boundary, verifier degrades to `inconclusive` instead of guessing. Foundry/Anvil flakiness handled with retries.
- **Observability:** log every agent step and every tool call to a structured trace (one JSON line per event: agent, turn, tool, input, output, latency). That trace is simultaneously your debugger and your answer to "what did the agent actually do."
- **Cost:** route by task difficulty, then *measure*. Strong reasoning models for the finder **and** the verifier — both are hard reasoning jobs — with the cheap synthesis model reserved for the reporter. The savings come from the reporter and from caching, not from crippling the finder; a cheap finder just moves the cost downstream, where the verifier burns its bounded attempts on junk hypotheses and real bugs never get proposed at all. Normalize token usage in adapters, but calculate money using a versioned provider/model price table because token accounting and prices differ across labs. Cache Slither and compile output. Report cost per role next to precision/recall so any routing change is judged on what it bought, not just what it saved.

---

## 10. Build path — vertical slice first

The classic way this project dies is three weeks of orchestration plumbing while it never catches a real bug. Avoid that by building depth before breadth.

**Phase 0 — Vertical slice (single loop, no orchestration).**
Establish the evaluation baseline with a minimal harness, 3–5 known-bug fixtures, and a stable pipeline entry point. Implement the pipeline as a single `run_agent` call with all tools, whose prompt does find → write PoC → report inline. Success = the harness records a true-positive finding count from executable PoCs and the pipeline emits a report for each fixture.

**Phase 1 — Split out the verifier.**
Refactor the pipeline into two `run_agent` calls: finder → verifier, with the verifier context-isolated and required to produce an executable PoC. Use the Phase 0 fixtures and baseline results to verify that the architectural change does not regress the true-positive finding count.

**Phase 2 — Split finder + reporter; add grounding + routing.**
Wire Slither in front of the finder. Add provider adapters, configurable per-role model routing, and Slither/compile caching. Clean up the two JSON contracts. Run the same fixtures against at least two provider/model configurations — both to catch adapter-specific behavior and to start the per-role model comparison that §8's harness exists to run.

**Phase 3 — Scale the eval + harden.**
Run the harness over Code4rena/Sherlock/DeFiHackLabs/SWC/EVMbench + your kleros and negative/patched fixtures. Add the structured observability trace. Report the true-positive finding count first, followed by precision-before/after, recall, negative-control false-positive rates, paired-patch retention, the human-review queue, and cost.

At every phase you have a working, demoable system — each step is a refactor, never a rewrite.
