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


def test_paired_twins_differ_only_in_code_not_commentary():
    """The negative control is only valid if it is indistinguishable from its
    vulnerable twin by prose. If the patched copy advertised its own safety,
    the model could pass by reading rather than reasoning."""
    vulnerable = _fixture_source("reentrancy-vault")
    patched = _fixture_source("reentrancy-vault-patched")
    assert _comments(vulnerable) == _comments(patched)
    assert vulnerable != patched, "the twins must still differ in code"


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
