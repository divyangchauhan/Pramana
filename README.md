# Pramana

[![CI](https://github.com/divyangchauhan/Pramana/actions/workflows/ci.yml/badge.svg)](https://github.com/divyangchauhan/Pramana/actions/workflows/ci.yml)

Pramana is a Python tool for investigating vulnerabilities in Solidity contracts. A finder agent reads the code and proposes possible bugs. A separate verifier receives each claim, writes a Foundry proof-of-concept test, and attempts to reproduce the exploit. An optional reporter turns the results into an audit report.

The repository includes the agent pipeline, an evaluation harness, contracts with known bugs and patched counterparts, and saved audit results. It supports Anthropic, OpenAI, and Kimi through provider adapters. The command-line interface runs contracts packaged as evaluation fixtures.

The name comes from *pramāṇa* (प्रमाण), meaning a valid means of knowledge or proof.

## Quickstart

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), and [Foundry](https://getfoundry.sh). Live runs also use [Slither](https://github.com/crytic/slither) and a Solidity compiler compatible with the target. Make sure `forge`, `slither`, and `solc` are on `PATH` for a live run.

From a checkout of this repository:

```bash
uv sync
(cd pramana/eval/foundry_template && forge soldeer install)
```

This installs the Python dependencies and the pinned `forge-std` dependency. Setup needs network access; Foundry may also download a Solidity compiler on first use.

Run the reference tests to check your setup. This does not call a model or require an API key:

```bash
uv run python -m pramana.eval.harness --self-check
```

With the bundled corpus, the headline should be `14 / 14 known bugs`. This checks the reference exploits and grading path. It is not an agent performance score.

For a live run, copy the example environment file and fill in the selected provider's key:

```bash
cp .env.example .env
# Set ANTHROPIC_API_KEY in .env before continuing.

mkdir -p runs/example
uv run python -m pramana.eval.harness \
    --provider anthropic --pipeline phase2 \
    --fixtures reentrancy-vault \
    --json runs/example/results.json \
    --report-dir runs/example/reports \
    --work-dir runs/example/workspaces \
    --trace-dir runs/example/traces
```

This runs the finder, verifier, and reporter on one contract. Live runs use your provider account and may incur charges. Omit `--fixtures` to run the full corpus, including the patched contracts.

## What a run produces

The example above writes:

| Output | Location |
|---|---|
| Scores, per-finding grading results, and usage | `runs/example/results.json` |
| Audit report | `runs/example/reports/reentrancy-vault.md` |
| Generated tests and contract workspace | `runs/example/workspaces/reentrancy-vault/audit/` |
| Independent PoC reruns | `runs/example/workspaces/reentrancy-vault/grade/` |
| Structured trace | `runs/example/traces/<run-id>/reentrancy-vault.jsonl` |

Reports include confirmed findings and a separate section for claims that need human review. Refuted claims remain in the evaluation data. The report header distinguishes the verifier's confirmed count from the number of PoCs that passed the harness's independent rerun.

For an example of the output, see this [saved reentrancy report](baselines/phase-1-8693741ffa57/reports/run-1/reentrancy-vault.md). Its test deposited 1 ETH into a vault holding another depositor's 5 ETH, then re-entered `withdraw()` and drained the vault. The report records the location, hypothesis, PoC path, and observed result.

## How it works

1. **Finder.** Slither supplies initial leads. The finder reads the contract and proposes claims. It can read files and run Slither, but cannot write tests or execute them.
2. **Verifier.** Each claim gets a fresh model conversation containing the contract, location, vulnerability class, and hypothesis. Finder notes and severity guesses are withheld. The verifier can write and run Foundry tests, then return `confirmed`, `refuted`, or `inconclusive`.
3. **Reporter.** The reporter writes descriptions, impact, and remediation, and can annotate possible duplicates. The renderer takes severity, verdicts, PoC paths, and counts from structured results. If the reporter fails, the pipeline falls back to a report built directly from those results.
4. **Evaluation.** The harness copies each confirmed PoC into a fresh workspace containing the original contract source and reruns it. A true positive requires a passing test and a match to an unclaimed known bug label.

The CLI keeps the original pipeline names for comparing implementations:

| Option | Behavior |
|---|---|
| `--pipeline phase0` | One agent investigates, tests, and reports. |
| `--pipeline phase1` | Finder and separate verifier, with a deterministic report. This is the CLI default. |
| `--pipeline phase2` | Finder, verifier, and reporter. Used in the quickstart above. |

The finder, verifier, and reporter are named Anumana, Khandana, and Nirnaya in the code. Phase 3 in the [original design plan](docs/design.md) describes evaluation and reliability work; it is not another pipeline option.

## Evaluation

The bundled corpus contains nine vulnerable fixtures with 14 labeled bugs across 11 vulnerability classes, plus nine patched counterparts. Each vulnerable fixture includes reference exploits. Tests check that patches stop the original attacks while preserving normal behavior.

The current corpus fingerprint is `776da97f2e2d`, with grader version `3`. The reference self-check produces:

```text
HEADLINE — true-positive findings confirmed with executable PoCs: 14 / 14 known bugs
NEGATIVE CONTROLS (9) — false positives: 0 confirmed, 0 with a passing PoC
PAIRED PATCH RETENTION — 14/14 proven classes stayed absent on the patched twin (rate 1.00, 9 pairs)
```

Three models were evaluated with the full finder–verifier–reporter pipeline (`phase2`) over all 18 fixtures, with three runs each at `effort=medium`. These baselines use corpus `15f1f83c2b28` and grader version `3`, before fixes to three patched contracts:

| Model and access | Baseline | True positives / 14, three runs | Recorded control FPs, three runs |
|---|---|---|---|
| Claude Opus 4.8, Anthropic | [Record](baselines/phase-2-paired-claude-opus-4-8/) | 10, 11, 10 | 2, 2, 0 |
| GPT-5.5, OpenAI gateway | [Record](baselines/phase-2-paired-gpt-5.5/) | 11, 11, 11 | 2, 2, 1 |
| Kimi K3, Moonshot | [Record](baselines/phase-2-paired-kimi-k3/) | 11, 12, 11 | 3, 1, 1 |

The control counts are findings with passing PoCs that the harness classified as false positives because those fixtures had no bug labels. Review of the recurring findings identified residual vulnerabilities in the lottery, bank, and delegatecall patches; [the subsequent fixes](https://github.com/divyangchauhan/Pramana/pull/21) changed those contracts and the corpus fingerprint.

No model sweep on the corrected corpus (`776da97f2e2d`) is committed yet. The reference self-check above validates the fixtures and grading path; it does not establish that live agent control findings have dropped to zero. Compare runs only when corpus fingerprints and grader versions match.

To record three runs of the full pipeline on the current corpus:

```bash
mkdir -p runs/phase2
for i in 1 2 3; do
    uv run python -m pramana.eval.harness \
        --provider anthropic --pipeline phase2 --effort medium \
        --json "runs/phase2/run-$i.json" \
        --report-dir "runs/phase2/reports-$i" \
        --work-dir "runs/phase2/workspaces-$i"
done
uv run python -m pramana.eval.baseline \
    --runs runs/phase2/run-*.json \
    --out-dir runs/phase2/baseline --label "Phase 2"
```

## Configuration

The application loads `.env` automatically. Exported environment variables take precedence. See [.env.example](.env.example) for endpoint overrides.

| `--provider` | Credential | Additional requirement |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | — |
| `openai` | `OPENAI_API_KEY` | — |
| `kimi` | `MOONSHOT_API_KEY` (`KIMI_API_KEY` also accepted) | — |
| `anthropic-gateway` | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL` |
| `openai-gateway` | `OPENAI_API_KEY` | `OPENAI_BASE_URL` |

Use `--model` to override the selected provider's [default model](pramana/config.py). `--finder-model`, `--verifier-model`, and `--reporter-model` select models for individual roles on that provider. Python callers can assign different providers through `AgentConfig` and `ModelProfile`.

`--max-turns` limits model turns, and `--max-poc-attempts` limits test-tool calls per verification. `--forge-timeout` and `--forge-retries` control test execution. Slither output and Foundry compilation are cached; use `--no-slither-cache` and `--no-forge-cache` to disable them.

Usage is reported per role. Cost estimates use the dated table in [pramana/cost.py](pramana/cost.py). Unknown prices and gateway billing appear as `null`; gateway notional costs are estimates at list price, not actual charges.

For all options:

```bash
uv run python -m pramana.eval.harness --help
```

## Using your own contracts

The harness accepts `--datasets /path/to/datasets`. Each immediate subdirectory needs a `fixture.json` and a `src/` directory; use [reentrancy-vault](pramana/eval/datasets/reentrancy-vault/) as an example. Reference PoCs are needed for the self-check.

Workspace creation copies top-level `src/*.sol` files into the shared Foundry template. It does not import an arbitrary repository's nested sources, dependencies, or build configuration. Contracts need to fit that layout. Empty `known_bugs` lists are scored as negative controls, so discovery on unlabeled contracts needs separate interpretation of the results.

## Scope and known limitations

The three agent roles, provider routing, caches, structured traces, paired fixtures, and baseline comparison are implemented. A check against the original design plan found these remaining gaps:

- **Public benchmarks:** the repository does not contain the planned Code4rena, Sherlock, DeFiHackLabs, EVMbench, or Kleros integrations. The bundled examples do not establish performance on large production repositories.
- **Confirmation enforcement:** the verifier's structured verdict can say `confirmed` without a recorded passing test. The harness rejects a missing or failing PoC from its score, but does not revise that verdict in the report body. Check the independent PoC result as well as the verdict.
- **Interrupted verification:** a verifier that exhausts its model-turn budget or raises a provider error aborts that fixture's audit. It does not currently preserve the partial audit and mark only the affected claim `inconclusive`.
- **Model preflight:** adapters check model availability where the endpoint supports it. They do not establish tool-calling and structured-output support before a run.

A passing PoC demonstrates the behavior encoded in that test. Its assertions, deployment assumptions, and impact still need review. Duplicate annotations do not remove findings or change counts. The committed full-pipeline baselines cover all 18 fixtures before the three patched-contract fixes; a model rerun on the corrected corpus is still needed.

## Development

```bash
uv run pytest
uv run ruff check pramana tests
uv run pyright pramana tests
uv run python -m pramana.eval.harness --self-check
```

The tests use scripted model responses and do not need provider keys. Foundry integration tests require the local toolchain and restored dependencies. [CI](.github/workflows/ci.yml) runs these checks for pull requests and pushes to `main`.

Start with [pramana/pipeline.py](pramana/pipeline.py) for orchestration, [pramana/agents/](pramana/agents/) for prompts and the agent loop, and [pramana/eval/](pramana/eval/) for fixtures, grading, and baselines. [docs/design.md](docs/design.md) records the original design and build plan.

## License

[MIT](LICENSE).
