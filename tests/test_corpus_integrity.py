"""Guards that keep the corpus honest.

A fixture whose source comments explain its own bug measures reading
comprehension, not vulnerability discovery — and inflates every recall number
the project reports. These tests keep the target sources free of tells, which
is easy to regress the next time a fixture is added or edited.
"""

from __future__ import annotations

import re

import pytest

from pramana.eval.workspace import DATASETS_DIR, load_fixtures

# Words that give the answer away in a *target* source file. Reference PoCs
# under reference/ are exempt: they exist to describe the exploit.
TELLS = (
    "bug",
    "vulnerab",
    "exploit",
    "attack",
    "malicious",
    "phishab",
    "phishing",
    "unsafe",
    "insecure",
    "deliberate",
    "swc-",
    "the dao",
    "parity",
    "beautychain",
    "reentran",
    "re-entran",
    "checks-effects",
    "cei",
)

SOURCES = sorted(DATASETS_DIR.glob("*/src/*.sol"))


def _comments(solidity: str) -> str:
    """Only the comment text — a tell is about what the source *says*, not the
    identifiers it necessarily uses (e.g. `tx.origin` in a require)."""
    blocks = re.findall(r"/\*.*?\*/", solidity, flags=re.DOTALL)
    lines = re.findall(r"//[^\n]*", solidity)
    return "\n".join(blocks + lines).lower()


def test_corpus_is_not_empty():
    assert SOURCES, "no fixture sources found"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_target_source_comments_do_not_name_the_bug(path):
    comments = _comments(path.read_text())
    # Anchored at a word boundary so short tells match as words: "cei" must not
    # fire on "re-cei-vers". Suffixes stay open so stems like "reentran" match
    # "reentrancy" and "reentrant" alike.
    found = [tell for tell in TELLS if re.search(rf"\b{re.escape(tell)}", comments)]
    assert not found, (
        f"{path} comments give the answer away ({found}). Target sources must read "
        "like code written by someone who did not know about the bug."
    )


def _paired_twins() -> list[tuple[str, str]]:
    """(vulnerable, patched) fixture-name pairs for every twin in the corpus."""
    by_pair: dict[str, dict[str, str]] = {}
    for f in load_fixtures():
        if f.pair and f.variant:
            by_pair.setdefault(f.pair, {})[f.variant] = f.name
    return [
        (v["vulnerable"], v["patched"])
        for _, v in sorted(by_pair.items())
        if "vulnerable" in v and "patched" in v
    ]


PAIRS = _paired_twins()


def test_every_vulnerable_fixture_has_a_patched_twin():
    """The corpus goal for this phase: a patched negative control for each
    vulnerable fixture. A vulnerable fixture with no twin is a gap in the
    false-positive evidence, so the list is asserted whole rather than sampled."""
    vulnerable = {f.name for f in load_fixtures() if f.variant == "vulnerable"}
    paired = {v for v, _ in PAIRS}
    missing = sorted(vulnerable - paired)
    assert not missing, f"vulnerable fixtures without a patched twin: {missing}"
    assert len(PAIRS) == len(vulnerable), "a pair is missing one of its variants"


@pytest.mark.parametrize(
    "vulnerable,patched", PAIRS, ids=[f"{v}->{p}" for v, p in PAIRS]
)
def test_paired_twins_differ_only_in_code_not_commentary(vulnerable, patched):
    """The negative control is only valid if it is indistinguishable from its
    vulnerable twin by prose. If the patched copy advertised its own safety, or
    merely dropped the comments the vulnerable one carries, the model could tell
    them apart by reading rather than reasoning."""
    v_src = _fixture_source(vulnerable)
    p_src = _fixture_source(patched)
    assert _comments(v_src) == _comments(p_src), (
        f"{vulnerable} and {patched} differ in commentary; twins must differ "
        "only in code"
    )
    assert v_src != p_src, "the twins must still differ in code"


def test_pairing_metadata_is_consistent():
    """`pair`/`variant`/`control_poc` are the only link between a bug and its
    negative control, and the paired_patch_retention metric trusts them. A
    patched twin that still declares known bugs, or names a control PoC that is
    not on disk, silently corrupts that metric."""
    for f in load_fixtures():
        if f.variant is None:
            assert f.pair is None, f"{f.name}: pair set without a variant"
            continue
        assert f.variant in ("vulnerable", "patched"), f"{f.name}: bad variant {f.variant!r}"
        assert f.pair, f"{f.name}: variant set without a pair"
        if f.variant == "patched":
            assert f.known_bugs == [], f"{f.name}: a patched twin must carry no known bugs"
            assert f.control_poc, f"{f.name}: patched twin has no control_poc"
            assert (f.dir / f.control_poc).is_file(), f"{f.name}: missing {f.control_poc}"
        else:
            assert f.known_bugs, f"{f.name}: a vulnerable fixture must declare known bugs"


def test_fingerprint_changes_when_a_target_source_changes(tmp_path):
    """Editing a fixture — even only its comments — can change how hard it is,
    so results must not be silently compared across corpora."""
    import shutil

    from pramana.eval.workspace import corpus_fingerprint

    src = DATASETS_DIR / "reentrancy-vault"
    dst = tmp_path / "reentrancy-vault"
    shutil.copytree(src, dst)

    before = corpus_fingerprint(load_fixtures(tmp_path))
    target = dst / "src" / "EtherStore.sol"
    target.write_text(target.read_text() + "\n// an added comment\n")
    after = corpus_fingerprint(load_fixtures(tmp_path))

    assert before != after


def test_fingerprint_is_stable_for_an_unchanged_corpus():
    from pramana.eval.workspace import corpus_fingerprint

    assert corpus_fingerprint(load_fixtures()) == corpus_fingerprint(load_fixtures())


def _fixture_source(name: str) -> str:
    fixture = load_fixtures(names=[name])[0]
    sources = sorted(fixture.src_dir.glob("*.sol"))
    assert len(sources) == 1
    return sources[0].read_text()


def test_every_fixture_has_a_reference_poc_for_each_known_bug():
    """A labeled bug with no executable proof cannot be graded, and would
    silently depress every recall number that includes it."""
    for fixture in load_fixtures():
        for bug in fixture.known_bugs:
            rel = bug.reference_poc or fixture.reference_poc
            assert rel, f"{fixture.name}/{bug.id} has no reference PoC"
            assert (fixture.dir / rel).is_file(), f"{fixture.name}/{bug.id}: missing {rel}"


def test_known_bug_classes_normalize_to_themselves():
    """A vuln_class the harness cannot canonicalize can never match a finding,
    making the bug unfindable however good the agent is."""
    from pramana.eval.harness import normalize_vuln_class

    for fixture in load_fixtures():
        for bug in fixture.known_bugs:
            assert normalize_vuln_class(bug.vuln_class) == bug.vuln_class, (
                f"{fixture.name}/{bug.id}: {bug.vuln_class!r} normalizes to "
                f"{normalize_vuln_class(bug.vuln_class)!r} — label it canonically"
            )


def test_accepted_aliases_normalize_to_themselves():
    """Same rule as vuln_class: an alias the harness re-canonicalizes to
    something else does not accept what its author thought it did."""
    from pramana.eval.harness import normalize_vuln_class

    for fixture in load_fixtures():
        for bug in fixture.known_bugs:
            for alias in bug.accepts:
                assert normalize_vuln_class(alias) == alias, (
                    f"{fixture.name}/{bug.id}: alias {alias!r} normalizes to "
                    f"{normalize_vuln_class(alias)!r} — declare it canonically"
                )


def test_no_alias_collides_with_a_sibling_bugs_own_class():
    """The failure aliases exist to avoid causing.

    If bug A accepts a class that bug B *is*, one finding can satisfy either.
    Matching prefers the primary class, so the total stays right — but a fixture
    written that way has two bugs the grader cannot tell apart, and a model that
    found one would look like it found whichever the harness picked. Keep the
    classes within a fixture mutually exclusive.
    """
    for fixture in load_fixtures():
        primary = {bug.id: bug.vuln_class for bug in fixture.known_bugs}
        for bug in fixture.known_bugs:
            for alias in bug.accepts:
                clashing = [i for i, c in primary.items() if i != bug.id and c == alias]
                assert not clashing, (
                    f"{fixture.name}/{bug.id} accepts {alias!r}, which is the class of "
                    f"{', '.join(clashing)} in the same fixture"
                )


def test_a_bug_does_not_list_its_own_class_as_an_alias():
    """Redundant, and it hides whether a match was a real agreement on naming
    or an alias rescue — the distinction `matched_via_alias` records."""
    for fixture in load_fixtures():
        for bug in fixture.known_bugs:
            assert bug.vuln_class not in bug.accepts, f"{fixture.name}/{bug.id}"


def test_reference_poc_names_avoid_the_testfail_prefix():
    """Foundry reads a `testFail` prefix as 'expected to revert', which silently
    inverts a reference exploit's result."""
    import re

    for path in DATASETS_DIR.glob("*/reference/*.sol"):
        for name in re.findall(r"function\s+(\w+)\s*\(", path.read_text()):
            assert not name.startswith("testFail"), (
                f"{path.name}: {name}() uses the testFail prefix; Foundry inverts it"
            )
