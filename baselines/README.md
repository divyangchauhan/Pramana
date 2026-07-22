# Baselines

Each subdirectory is a recorded reference point: N independent runs of one
pipeline over the corpus, with the commit, config and corpus pinned. Later
phases are gated against them (`pramana.eval.baseline --against`).

Results are only comparable **within the same corpus**. Runs and baselines
record a `corpus_fingerprint`; aggregating runs from different corpora is
refused, and comparing baselines across corpora reports "not comparable"
rather than a regression verdict.

| Record | Pipeline | Corpus | Status |
|---|---|---|---|
| [`phase-1-007869fd6cad/`](phase-1-007869fd6cad/) | finder → isolated verifier | `007869fd6cad` — **current**, 11 bugs | **the gating reference** |
| [`phase-0/`](phase-0/) | single combined agent | pre-strip | superseded |
| [`phase-1/`](phase-1/) | finder → isolated verifier | pre-strip | superseded |
| [`phase-1-nohints/`](phase-1-nohints/) | finder → isolated verifier | `bee662ded628` — 6 bugs | superseded by corpus growth |
| [`phase-1-kimi-k3/`](phase-1-kimi-k3/) | finder → isolated verifier | `bee662ded628` — 6 bugs | superseded; kept as the first sweep row |

## Why the earlier records are superseded

Both were measured while every fixture's source comments explained its own bug
(`BUG 1 — reentrancy: interaction before effect`, `@notice` blocks naming The
DAO, Parity, BeautyChain). The agent reads those comments, so those numbers
partly measure reading comprehension rather than vulnerability discovery.

The Phase 1 → Phase 0 no-regression comparison recorded there was **valid when
made** — both sides were measured on the same corpus, and the architectural
change was shown not to regress the true-positive count. The comments were
stripped afterwards. That decision stands; the records are kept as history
rather than re-run, since re-measuring Phase 0 would cost three runs to
re-confirm a conclusion that was never in doubt.

## The current reference

`phase-1-007869fd6cad/` — 3 runs of `phase1/anthropic:claude-opus-4-8` at
commit `ec2e920`, all three identical.

| Metric | Pre-strip, 6 bugs (3 runs) | Hint-free, 6 bugs (1 run) | **Current, 11 bugs (3 runs)** |
|---|:---:|:---:|:---:|
| True positives | 6 / 6 | 6 / 6 | **10 / 11** |
| Unmatched confirmed findings | 0 | 0 | **1** |
| Negative-control false positives | 0 | 0 | **0** |

The gate: true positives must not fall below **10**; negative-control false
positives must not exceed **0**.

Recall is no longer 100%, and that is the corpus doing its job — six bugs
across five classes was not enough spread to distinguish configurations. The
one miss is stable and specific: **`bank-multi` KB-3**, the
`sweep(address(0))` fund-burn. `claude-opus-4-8` proposed two candidates on
that contract in all three runs and never raised it, while `kimi-k3` found it
on the corpus where it was first observed. Two labs, the same contract,
different coverage — which is exactly the comparison the Phase 2 sweep exists
to make.

## The unmatched finding is not the same finding twice

Every run reports exactly 1 unmatched confirmed finding, all on
`signature-replay-vault`, and it would be easy to read that stability as one
reproducible defect. It is not:

| Run | Unmatched finding | Severity | Report |
|---|---|---|---|
| 1, 3 | `ecrecover` returns `address(0)` for garbage signatures; constructor has no zero-check on `signer` | high | [run-1](phase-1-007869fd6cad/reports/run-1/signature-replay-vault.md) |
| 2 | signature malleability — `s' = n - s` also accepted | informational | [run-2](phase-1-007869fd6cad/reports/run-2/signature-replay-vault.md) |

Reports are stored per run (`reports/run-N/`) rather than flattened, precisely
so this divergence survives in the record.

Both are real properties of the code. Neither is in `fixture.json`.

Run 2 is the more careful analysis, and it is worth reading in full because it
argues *against* the other two: it tested the zero-address branch and rejected
it, on the grounds that the constructor never actually sets `signer` to zero.
It then graded its own malleability finding *informational*, reasoning that the
vault already has no replay guard, so a second valid signature "grants no
incremental capability."

### What that exposes about the method

Runs 1 and 3 proved their claim by **deploying the vault themselves with
`signer = address(0)`**. The PoC controls the constructor arguments, so the
finding is not "this contract is exploitable" but "this contract is exploitable
if deployed misconfigured" — and under that latitude, almost any contract can
be broken.

This is the same shape as the `kimi-k3` `sweep(address(0))` finding, which also
required a bad input from a trusted party. Two independent labs converged on
the same *class* of claim, which suggests the gap is in what the corpus asks
for, not in either model.

Unresolved, and deliberately not fixed inside the measurement: whether a PoC
may choose deployment parameters. Constraining it would reject some genuine
findings (a missing zero-check *is* a real audit finding); permitting it admits
claims contingent on operator error. Whatever the answer, it belongs in the
finder/verifier contract rather than in a label.

## Does the verifier ever disagree?

A separate question these baselines cannot answer. In every run recorded here,
*every* candidate the finder proposed was confirmed — zero refuted, zero
inconclusive — because the finder never hands the verifier a bad claim.

`pramana.eval.refutation` puts hand-written claims to the verifier directly:

```
probe                        expected       kimi-k3    gpt-5.5
true-claim-control           confirmed      confirmed  confirmed
false-claim-patched-twin     not confirmed  refuted    refuted
false-claim-wrong-mechanism  not confirmed  refuted    refuted
```

The verifier discriminates on both labs tested. So the zero-refutation record
reflects a well-calibrated finder, not a rubber stamp.

**And it fires in a real run too.** `kimi-k3` produced the first refutation
outside the probe: on `unprotected-owner` its finder proposed a
`missing-zero-check` in `initOwner()`, and the verifier refuted it after failing
to demonstrate any exploitable consequence.

## What the second config exposed about the eval

`kimi-k3` matched `claude-opus-4-8` at 6/6 true positives, with one *unmatched*
confirmed finding on `bank-multi` — and reading it changed how that metric
should be understood:

> **F-003 — missing-zero-check, `sweep()`** — "admin calls `sweep(address(0))`;
> `.transfer` to the zero address does not revert and the entire balance is
> permanently burned." PoC passed: 10 ether in, `address(bank).balance == 0`.

That is a **real bug that our label set does not contain**, not a duplicate and
not a hallucination. `unmatched_confirmed_findings` therefore conflates three
different things:

1. duplicates of an already-claimed bug (the `tx-origin` case — a genuine defect),
2. spurious or unprovable claims (a genuine defect), and
3. **real findings missing from `fixture.json`** (our gap, not the model's).

Only a human reading the finding can separate them. Treat a non-zero unmatched
count as *"look at this"*, never as *"the model was wrong"* — and note that the
same claim class was correctly refuted on one fixture and correctly confirmed on
another, which is the verifier discriminating, not being inconsistent.
