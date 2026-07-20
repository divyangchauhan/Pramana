# Pramana

**Multi-agent smart-contract audit pipeline.** Full system design and staged
build plan in [`docs/design.md`](docs/design.md).

> **Pramāṇa** (प्रमाण) — "a valid means of knowledge / proof": a finding counts
> as knowledge only once it has been *proven* with an executable exploit.

This repository currently implements **Phase 0 — the vertical slice**: a single
provider-neutral agent loop that, given a Solidity contract, finds
vulnerabilities, **proves each with a working Foundry PoC**, and reports them —
scored by an evaluation harness whose headline number is the count of
**true-positive findings confirmed by an executable PoC**.

---

## What's here (Phase 0)

```
pramana/
├── providers/          # provider-neutral adapter boundary (design §1)
│   ├── base.py         #   ToolCall / LLMResponse / ToolResult / LLMAdapter
│   ├── anthropic.py    #   Anthropic (Messages API, streaming) adapter
│   └── openai.py       #   OpenAI (Chat Completions) adapter
├── agents/
│   ├── loop.py         # run_agent — one bounded, isolated agent loop (§1)
│   └── prompts.py      # Phase 0 system prompt + tool schemas
├── tools/              # sandboxed workspace tools (§2)
│   ├── files.py        #   ToolContext + read_file / write_file
│   ├── slither.py      #   run_slither (static-analysis leads, §6)
│   ├── foundry.py      #   run_foundry_test + structured grader helper
│   └── registry.py     #   TOOL_REGISTRY + crash-safe dispatch
├── contracts.py        # Pydantic Finding / Verdict / Phase0Output (§4)
├── pipeline.py         # Phase 0 audit() — single-loop entry point (§10)
├── config.py           # per-role provider/model config, pinned per run
└── eval/
    ├── datasets/       # the real-world corpus (4 known-bug fixtures)
    ├── workspace.py    # per-run Foundry workspaces
    └── harness.py      # runs audit() over fixtures, counts true positives (§8)
```

### Providers

The core loop never imports a lab SDK — it speaks the canonical types in
`providers/base.py`. Only the adapter files touch a vendor SDK, and each
translates the same canonical message list to/from its wire format. Select a
provider per run; the rest of the pipeline never branches on provider name.

- **Anthropic** (`providers/anthropic.py`) — Messages API via streaming (safe
  for large `max_tokens`); default model `claude-opus-4-8`. No `temperature`
  (removed on Opus 4.8) and no `thinking` config (assistant turns stay text +
  tool calls).
- **OpenAI** (`providers/openai.py`) — Chat Completions with function calling.
  No `temperature`, so reasoning models accept the request; output capped via
  `max_completion_tokens`.
- **Kimi / Moonshot AI** (`providers/kimi.py`) — Kimi K3 via Moonshot's
  OpenAI-compatible API. Subclasses the OpenAI adapter and reuses its wire
  translation wholesale, changing only what differs: the client points at
  Moonshot's endpoint with `MOONSHOT_API_KEY`, and the output cap uses the
  legacy `max_tokens` parameter.

For OpenAI and Kimi the built-in default model id is a placeholder — pass a
valid `--model`.

---

## The real-world corpus

Four self-contained fixtures, each modeled on a real historical exploit, with a
labeled known-bug set and a reference PoC:

| Fixture | Class | Inspiration |
|---|---|---|
| `reentrancy-vault` | reentrancy | The DAO (2016) |
| `unprotected-owner` | access-control | Parity multisig unprotected initializer (2017) |
| `tx-origin-wallet` | tx-origin | SWC-115 tx.origin auth |
| `unchecked-overflow-token` | integer-overflow | BeautyChain (BEC) `batchOverflow` (2018) |

Each `datasets/<name>/` holds the vulnerable source under `src/`, a
`fixture.json` label set, and a `reference/` exploit PoC used to validate the
grading path offline.

---

## How a true positive is counted

The headline metric is **true-positive findings confirmed with executable PoCs**
(design §8). For each finding the agent marks `confirmed`, the harness:

1. Builds a **fresh** workspace with the *pristine* target source (so the agent
   cannot fake a pass by editing the contract),
2. Copies in only the agent's PoC test file and re-runs it with `forge test`,
3. Requires the test to **execute and pass**, and
4. Matches the finding's `vuln_class` to a known bug (normalized, matched 1:1).

A finding is a true positive only if all four hold. `inconclusive` verdicts,
PoCs that don't pass, and class mismatches never count. Candidate volume,
precision before/after verification, and recall are reported as supporting
diagnostics.

---

## Running it

Requires [`uv`](https://docs.astral.sh/uv/), plus `forge`/`anvil` (Foundry) and
`slither` on `PATH`. Install deps once:

```bash
uv sync                                                  # Python deps
(cd pramana/eval/foundry_template && forge soldeer install)   # restore forge-std
```

`forge-std` is a declared [Soldeer](https://soldeer.xyz) dependency (pinned in
`pramana/eval/foundry_template/foundry.toml` + `soldeer.lock`) — it is fetched,
not vendored. The harness prints the exact restore command if it's missing.

**Self-check (no API key)** — validates the corpus + grading path by grading the
reference PoCs. This is the offline proof that the whole scoring machinery works:

```bash
uv run python -m pramana.eval.harness --self-check
```

```
fixture                    cfg                    cand conf  poc+  TP  recall
-----------------------------------------------------------------------------
reentrancy-vault           reference-poc             1    1     1   1    1.00
tx-origin-wallet           reference-poc             1    1     1   1    1.00
unchecked-overflow-token   reference-poc             1    1     1   1    1.00
unprotected-owner          reference-poc             1    1     1   1    1.00
-----------------------------------------------------------------------------
HEADLINE — true-positive findings confirmed with executable PoCs: 4 / 4 known bugs
```

**Real agent run** — put the provider key in a local `.env` (copy `.env.example`)
or export it. The app auto-loads `.env` at startup and refuses to start if the
selected provider's credential is missing.

```bash
cp .env.example .env   # then fill in ANTHROPIC_API_KEY (or OPENAI/MOONSHOT)
uv run python -m pramana.eval.harness --provider anthropic
uv run python -m pramana.eval.harness --provider openai --model <a-valid-model-id>
uv run python -m pramana.eval.harness --provider kimi   --model <a-valid-kimi-model-id>

# useful flags:
#   --fixtures reentrancy-vault tx-origin-wallet   restrict the set
#   --json results.json                            full per-finding results
#   --verbose                                      stream tool calls to stderr
#   --work-dir ./runs                              keep workspaces for inspection
```

**Tests & lint:**

```bash
uv run pytest       # offline: parsing, class matching, grading paths, wire translation
uv run ruff check pramana tests
```

---

## Status & known limitations

- Phase 0 runs one combined agent (find + prove + report inline). Phases 1–2
  split it into context-isolated finder / verifier / reporter (see `docs/design.md`
  §10) — this entry point's contract is designed to survive that refactor.
- Grading trusts that a *passing* PoC written under exploit intent demonstrates
  the exploit. Hardening this with **negative controls** (vulnerable/patched
  revision pairs, where the same PoC must fail on the patched code) is Phase 3
  (design §8).
- The OpenAI and Kimi default model ids are placeholders — always pass `--model`
  for those providers (e.g. the exact Moonshot Kimi K3 id for `kimi`).
