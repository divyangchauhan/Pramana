"""Tests for how a finding is matched to a known bug.

Two of the three true-positive conditions are executable facts: the agent said
"confirmed", and the harness re-ran the PoC in a pristine workspace and watched
it pass. The third is string equality on a free-text label, and it is the one
that goes wrong.

The case these exist for: a run proved the delegatecall storage collision on
`delegatecall-module` — its PoC deployed a malicious module, overwrote the owner
slot and drained 10 ether — but labeled the class `access-control` rather than
`delegatecall`. Recall, finder precision and verifier precision for that fixture
all went to zero on a correct finding with a passing exploit. Other runs named
the same bug `unrestricted-delegatecall`, `arbitrary-delegatecall` and
`controlled-delegatecall`. Vocabulary is a per-model habit, so a grader
sensitive to it ranks naming style, which is not what the sweep is measuring.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from pramana.eval import harness
from pramana.eval.harness import (
    GRADER_VERSION,
    QUALIFIERS,
    SYNONYMS,
    Probe,
    _match_bug,
    accepted_classes,
    grade,
    normalize_vuln_class,
)
from pramana.eval.workspace import KnownBug, load_fixtures


def _bug(bug_id: str, vuln_class: str, accepts: list[str] | None = None) -> KnownBug:
    return KnownBug(
        id=bug_id,
        vuln_class=vuln_class,
        location="X.f()",
        description="",
        accepts=accepts or [],
    )


# --- accepted_classes --------------------------------------------------------


def test_a_bug_always_answers_to_its_own_class():
    assert accepted_classes(_bug("KB-1", "delegatecall")) == {"delegatecall"}


def test_aliases_are_normalized_like_any_other_label():
    """So a fixture author writing 'Missing Access Control' gets the same
    behaviour as 'access-control' — the alias goes through one code path."""
    bug = _bug("KB-1", "delegatecall", ["Missing Access Control"])
    assert accepted_classes(bug) == {"delegatecall", "access-control"}


# --- matching ----------------------------------------------------------------


def test_an_alias_matches():
    bug = _bug("KB-1", "delegatecall", ["access-control"])
    assert _match_bug([bug], "access-control", set()) is bug


def test_an_alias_on_one_bug_does_not_reach_another():
    """The whole reason aliases are per-bug rather than a wider synonym map:
    loosening the map merges two classes everywhere, so a model that found only
    an access-control bug could be credited for a delegatecall one it never saw."""
    aliased = _bug("KB-1", "delegatecall", ["access-control"])
    other = _bug("KB-2", "reentrancy")
    assert _match_bug([other], "access-control", set()) is None
    assert _match_bug([aliased, other], "reentrancy", set()) is other


def test_a_primary_class_match_outranks_an_alias_on_an_earlier_bug():
    """An alias is a concession to naming ambiguity; it must never outrank a bug
    that carries the class outright. Otherwise a finding gets credited to the
    bug that merely tolerates its label, the bug actually named that way is
    recorded as missed, and the run total hides both."""
    aliased = _bug("KB-1", "delegatecall", ["access-control"])
    real = _bug("KB-2", "access-control")
    assert _match_bug([aliased, real], "access-control", set()) is real


def test_an_alias_still_matches_once_the_primary_bug_is_claimed():
    aliased = _bug("KB-1", "delegatecall", ["access-control"])
    real = _bug("KB-2", "access-control")
    assert _match_bug([aliased, real], "access-control", {"KB-2"}) is aliased


def test_one_bug_cannot_be_claimed_twice():
    """Two findings naming the same class are one hit and one duplicate, not a
    recall of 2/1."""
    bug = _bug("KB-1", "delegatecall", ["access-control"])
    assert _match_bug([bug], "delegatecall", set()) is bug
    assert _match_bug([bug], "access-control", {"KB-1"}) is None


def test_an_unrelated_class_matches_nothing():
    bug = _bug("KB-1", "delegatecall", ["access-control"])
    assert _match_bug([bug], "weak-randomness", set()) is None


# --- the synonym map resolves by specificity ----------------------------------


@pytest.mark.parametrize(
    "label",
    ["unrestricted-delegatecall", "arbitrary-delegatecall", "controlled-delegatecall"],
)
def test_labels_models_actually_produced_normalize_to_delegatecall(label):
    """Observed across six sweep runs on one bug. Pinned so a synonym edit that
    breaks them shows up here rather than as a mystery recall drop."""
    assert normalize_vuln_class(label) == "delegatecall"


@pytest.mark.parametrize(
    "label,expected",
    [
        # Each of these was captured by access-control or unchecked-call under
        # grader v2, purely because those classes sit higher in SYNONYMS.
        ("unprotected-delegatecall", "delegatecall"),
        ("unchecked-delegatecall", "delegatecall"),
        ("owner-hijack-via-delegatecall", "delegatecall"),
        ("privilege-escalation-via-delegatecall", "delegatecall"),
        ("auth-via-tx-origin", "tx-origin"),
        ("owner-mint-overflow", "integer-overflow"),
        ("unchecked-zero-address", "missing-zero-check"),
        ("missing-zero-address-check-on-owner", "missing-zero-check"),
        ("owner-predictable-rng", "weak-randomness"),
        ("unchecked-randomness", "weak-randomness"),
        ("owner-signature-replay", "signature-replay"),
        ("replay-of-authorized-signature", "signature-replay"),
        ("unprotected-reentrancy", "reentrancy"),
    ],
)
def test_a_qualifier_does_not_capture_a_label_that_names_another_class(label, expected):
    """The defect grader v3 fixes.

    A label carrying words from two classes belongs to the one it *names*.
    `unprotected-delegatecall` is a delegatecall bug that happens to also be
    unprotected — scoring it as access-control zeroes recall and both precision
    axes on a correct finding whose PoC passes.
    """
    assert normalize_vuln_class(label) == expected


@pytest.mark.parametrize(
    "label",
    [
        "missing-access-control",
        "unprotected-owner-change",
        "broken-ownership",
        "privilege-escalation",
    ],
)
def test_a_qualifier_still_wins_when_nothing_more_specific_is_named(label):
    """Demoting qualifiers must not make access-control unreachable: when the
    label says only that something is unguarded, that *is* the class."""
    assert normalize_vuln_class(label) == "access-control"


def test_specificity_does_not_depend_on_where_a_class_sits_in_the_map():
    """The point of v3. Under v2, precedence was declaration position, so moving
    a class silently rescored every ambiguous label — and adding one at the
    bottom (signature-replay) left it outranked by all eight above it."""
    expected = {
        "unprotected-delegatecall": "delegatecall",
        "owner-signature-replay": "signature-replay",
        "auth-via-tx-origin": "tx-origin",
    }
    reordered = dict(reversed(list(SYNONYMS.items())))
    with mock.patch.object(harness, "SYNONYMS", reordered):
        for label, canonical in expected.items():
            assert normalize_vuln_class(label) == canonical


# --- the synonym map itself ---------------------------------------------------


def test_every_needle_is_reachable():
    """`normalize_vuln_class` slugifies before matching, so a needle containing
    anything a slug cannot hold is dead code that reads as coverage. The map
    carried `tx.origin` this way until v3 — the dot can never survive."""
    for canonical, needles in SYNONYMS.items():
        for needle in needles:
            assert re.fullmatch(r"[a-z0-9-]+", needle), (
                f"{canonical}: needle {needle!r} can never match a slugified label"
            )


def test_every_canonical_class_normalizes_to_itself():
    """Otherwise a fixture labeled canonically could never be matched."""
    for canonical in SYNONYMS:
        assert normalize_vuln_class(canonical) == canonical


def test_qualifiers_are_needles_of_some_class():
    """A qualifier that belongs to no class demotes nothing and just misleads."""
    all_needles = {n for needles in SYNONYMS.values() for n in needles}
    assert QUALIFIERS <= all_needles


def test_no_class_is_built_only_from_qualifiers():
    """Such a class could never win against a substantive match, so it would be
    unreachable for exactly the labels it was added to catch."""
    for canonical, needles in SYNONYMS.items():
        assert set(needles) - QUALIFIERS, f"{canonical} has only qualifier needles"


@pytest.mark.parametrize(
    "label,expected",
    [
        ("reentrancy", "reentrancy"),
        ("access-control", "access-control"),
        ("tx-origin", "tx-origin"),
        ("integer-overflow", "integer-overflow"),
        ("unchecked-call", "unchecked-call"),
        ("unchecked-send", "unchecked-call"),
        ("missing-zero-check", "missing-zero-check"),
        ("signature-replay", "signature-replay"),
        ("weak-prng", "weak-randomness"),
        ("unrestricted-delegatecall", "delegatecall"),
        ("arbitrary-delegatecall", "delegatecall"),
        ("controlled-delegatecall", "delegatecall"),
        ("cross-contract-replay", "signature-replay"),
        ("ecrecover-zero-address", "missing-zero-check"),
        ("zero-address-signer", "missing-zero-check"),
        ("signature-malleability", "signature-malleability"),
        ("missing-domain-separation", "missing-domain-separation"),
        ("dos", "dos"),
    ],
)
def test_labels_already_recorded_in_runs_are_unaffected_by_v3(label, expected):
    """Every distinct label any model has produced across all recorded runs and
    baselines — 202 occurrences. v3 changes how ambiguous labels resolve, so the
    claim that it rescores nothing already measured has to be checked, not
    assumed. If a future map edit moves one of these, a recorded number changed
    meaning and GRADER_VERSION must move with it.
    """
    assert normalize_vuln_class(label) == expected


# --- end to end through grade() ----------------------------------------------


def _delegatecall_fixture():
    fixtures = load_fixtures(names=["delegatecall-module"])
    assert fixtures, "delegatecall-module fixture must exist"
    return fixtures[0]


def test_the_fixture_declares_the_alias_that_was_costing_a_true_positive():
    bug = _delegatecall_fixture().known_bugs[0]
    assert "access-control" in accepted_classes(bug)


def test_a_proven_exploit_labeled_access_control_now_counts():
    """The exact run that scored 9/11 instead of 10/11, replayed through the
    reference PoC: same passing exploit, the label the model chose."""
    fx = _delegatecall_fixture()
    ref_rel = fx.known_bugs[0].reference_poc or fx.reference_poc
    assert ref_rel
    probes = [
        Probe(id="F-001", vuln_class="access-control", verdict="confirmed",
              poc_file=fx.dir / ref_rel)
    ]
    with tempfile.TemporaryDirectory() as tmp:
        row = grade(fx, probes, Path(tmp), "test")

    assert row.confirmed_poc_pass == 1
    assert row.true_positive_findings == 1
    assert row.recall == 1.0
    # The mislabel used to zero all three at once; precision must recover too.
    assert row.finder_precision == 1.0
    assert row.verifier_precision == 1.0

    detail = row.details[0]
    assert detail["matched_bug"] == "KB-1"
    assert detail["matched_via_alias"] is True


def test_a_match_on_the_primary_class_is_not_recorded_as_aliased():
    """The audit trail has to distinguish them: a run where every match is
    aliased means the corpus labels have drifted from how models name bugs."""
    fx = _delegatecall_fixture()
    ref_rel = fx.known_bugs[0].reference_poc or fx.reference_poc
    assert ref_rel
    probes = [
        Probe(id="F-001", vuln_class="delegatecall", verdict="confirmed",
              poc_file=fx.dir / ref_rel)
    ]
    with tempfile.TemporaryDirectory() as tmp:
        row = grade(fx, probes, Path(tmp), "test")
    assert row.true_positive_findings == 1
    assert row.details[0]["matched_via_alias"] is False


def test_an_alias_does_not_rescue_a_finding_whose_poc_failed():
    """Aliases loosen *naming*, never the executable-proof requirement."""
    fx = _delegatecall_fixture()
    probes = [
        Probe(id="F-001", vuln_class="access-control", verdict="confirmed",
              poc_file=fx.dir / "reference" / "does_not_exist.t.sol")
    ]
    with tempfile.TemporaryDirectory() as tmp:
        row = grade(fx, probes, Path(tmp), "test")
    assert row.n_confirmed == 1
    assert row.true_positive_findings == 0


# --- versioning --------------------------------------------------------------


def test_grader_version_covers_both_matching_changes():
    """v1 graded without aliases, v2 resolved ambiguous labels by declaration
    order. Comparing a number across any of those compares two metrics, so the
    version has to travel with every recorded run."""
    assert GRADER_VERSION >= 3
