"""Slither result caching (design §9).

The cache is a pure-function memo: identical source + analyzer version must hit,
anything else must miss and re-run. These tests fake ``subprocess.run`` and count
invocations, so they assert the one property that matters — a hit never spawns the
analyzer — without needing Slither installed.
"""

from __future__ import annotations

from pathlib import Path

import pramana.tools.slither as slither_mod
from pramana.tools.cache import cache_get, cache_put, content_key
from pramana.tools.files import ToolContext, ToolError

_OK_JSON = (
    '{"success": true, "error": null, "results": {"detectors": ['
    '{"check": "reentrancy-eth", "impact": "High", "confidence": "Medium",'
    ' "description": "Reentrancy in withdraw()"}]}}'
)
_FAIL_JSON = '{"success": false, "error": "solc not found", "results": {}}'


class _FakeProc:
    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        self.stdout = stdout
        self.stderr = stderr


def _fake_run(counter: dict[str, int], stdout: str, stderr: str = ""):
    def _run(*_args, **_kwargs):
        counter["n"] += 1
        return _FakeProc(stdout, stderr)

    return _run


def _workspace(tmp_path: Path, source: str = "contract Foo {}") -> tuple[Path, str]:
    src = tmp_path / "ws" / "src"
    src.mkdir(parents=True)
    (src / "Foo.sol").write_text(source)
    return tmp_path / "ws", "src/Foo.sol"


# --- content_key ------------------------------------------------------------


def test_content_key_is_stable_and_input_sensitive() -> None:
    assert content_key("a", "b") == content_key("a", "b")
    assert content_key("a", b"b") == content_key("a", "b")  # str/bytes parity
    assert content_key("a", "b") != content_key("a", "c")


def test_content_key_length_prefix_prevents_join_collision() -> None:
    # Without length-prefixing these would both hash "abc".
    assert content_key("ab", "c") != content_key("a", "bc")


# --- cache_get / cache_put --------------------------------------------------


def test_cache_roundtrip(tmp_path: Path) -> None:
    cache_put(tmp_path, "k", "value")
    assert cache_get(tmp_path, "k") == "value"


def test_cache_disabled_when_dir_is_none(tmp_path: Path) -> None:
    cache_put(None, "k", "value")  # no-op, must not raise
    assert cache_get(None, "k") is None


def test_cache_miss_is_none(tmp_path: Path) -> None:
    assert cache_get(tmp_path, "absent") is None


# --- run_slither_summary caching -------------------------------------------


def test_second_run_hits_cache_and_skips_analyzer(tmp_path, monkeypatch) -> None:
    ws, path = _workspace(tmp_path)
    counter = {"n": 0}
    monkeypatch.setattr(slither_mod.subprocess, "run", _fake_run(counter, _OK_JSON))
    events = []
    ctx = ToolContext(workspace=ws, slither_cache_dir=tmp_path / "cache", trace=events.append)

    first = slither_mod.run_slither_summary(ctx, path)
    second = slither_mod.run_slither_summary(ctx, path)

    assert counter["n"] == 1  # analyzer ran once; second call served from cache
    assert first == second
    assert "reported 1 detector hit(s)" in first
    assert [(e["cache"], e["hit"]) for e in events] == [
        ("slither", False), ("slither", True)
    ]


def test_no_cache_dir_reruns_every_time(tmp_path, monkeypatch) -> None:
    ws, path = _workspace(tmp_path)
    counter = {"n": 0}
    monkeypatch.setattr(slither_mod.subprocess, "run", _fake_run(counter, _OK_JSON))
    ctx = ToolContext(workspace=ws, slither_cache_dir=None)

    slither_mod.run_slither_summary(ctx, path)
    slither_mod.run_slither_summary(ctx, path)

    assert counter["n"] == 2  # caching disabled → analyzer runs each time


def test_failed_analysis_is_not_cached(tmp_path, monkeypatch) -> None:
    ws, path = _workspace(tmp_path)
    counter = {"n": 0}
    monkeypatch.setattr(slither_mod.subprocess, "run", _fake_run(counter, _FAIL_JSON))
    ctx = ToolContext(workspace=ws, slither_cache_dir=tmp_path / "cache")

    slither_mod.run_slither_summary(ctx, path)
    slither_mod.run_slither_summary(ctx, path)

    assert counter["n"] == 2  # success:false must not poison the cache


def test_edited_source_misses_cache(tmp_path, monkeypatch) -> None:
    ws, path = _workspace(tmp_path, "contract Foo {}")
    counter = {"n": 0}
    monkeypatch.setattr(slither_mod.subprocess, "run", _fake_run(counter, _OK_JSON))
    ctx = ToolContext(workspace=ws, slither_cache_dir=tmp_path / "cache")

    slither_mod.run_slither_summary(ctx, path)
    (ws / "src" / "Foo.sol").write_text("contract Foo { uint x; }")  # edit the source
    slither_mod.run_slither_summary(ctx, path)

    assert counter["n"] == 2  # changed source → new key → re-run


def test_analyzer_version_bump_misses_cache(tmp_path, monkeypatch) -> None:
    ws, path = _workspace(tmp_path)
    counter = {"n": 0}
    monkeypatch.setattr(slither_mod.subprocess, "run", _fake_run(counter, _OK_JSON))
    ctx = ToolContext(workspace=ws, slither_cache_dir=tmp_path / "cache")

    monkeypatch.setattr(slither_mod, "_slither_version", lambda: "0.10.0")
    slither_mod.run_slither_summary(ctx, path)
    monkeypatch.setattr(slither_mod, "_slither_version", lambda: "0.11.0")
    slither_mod.run_slither_summary(ctx, path)

    assert counter["n"] == 2  # analyzer upgrade → fresh key, no stale hit


def test_missing_file_raises_before_touching_cache(tmp_path) -> None:
    ws, _ = _workspace(tmp_path)
    ctx = ToolContext(workspace=ws, slither_cache_dir=tmp_path / "cache")
    try:
        slither_mod.run_slither_summary(ctx, "src/Nope.sol")
    except ToolError as exc:
        assert "file not found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ToolError for a missing target")
