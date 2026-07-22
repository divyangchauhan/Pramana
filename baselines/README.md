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
| *(none yet)* | finder → isolated verifier | `007869fd6cad` — **current**, 11 bugs | **pending re-measurement** |
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

## There is currently no valid reference

The corpus grew from 6 labeled bugs to 11 across 9 classes (`007869fd6cad`),
which supersedes every record here — including the `phase-1-nohints/` one that
was briefly the reference. Nothing was lost: it was provisional at n=1 anyway,
and expanding the corpus before spending runs on it is strictly cheaper than
after.

**Next measurement: 3 runs of `phase1` on `007869fd6cad`.** That becomes the
gating reference.

| Metric | Pre-strip (3 runs) | Hint-free (1 run) |
|---|:---:|:---:|
| True positives | 6 / 6 | 6 / 6 |
| Unmatched confirmed findings | 0 | 0 |
| Negative-control false positives | 0 | 0 |

Every bug was still found and proven with an executable PoC once the
explanatory comments were gone.

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
