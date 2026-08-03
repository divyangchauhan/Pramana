"""Offline tests for pristine Foundry compilation caching."""

from __future__ import annotations

import subprocess
from pathlib import Path

from pramana.tools import foundry
from pramana.tools.files import ToolContext


def _workspace(root: Path) -> Path:
    ws = root / "workspace"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "Target.sol").write_text("contract Target {}")
    (ws / "foundry.toml").write_text('[profile.default]\nsrc = "src"\n')
    return ws


def _fake_forge(monkeypatch, *, build_returncode: int = 0):
    calls = {"build": 0}

    def fake_run(args, **kwargs):
        if args == ["forge", "--version"]:
            return subprocess.CompletedProcess(args, 0, "forge 1.3.0", "")
        assert args == ["forge", "build"]
        calls["build"] += 1
        ws = Path(kwargs["cwd"])
        if build_returncode == 0:
            (ws / "out").mkdir(exist_ok=True)
            (ws / "cache").mkdir(exist_ok=True)
            (ws / "out" / "Target.json").write_text("artifact")
            (ws / "cache" / "solidity-files-cache.json").write_text("metadata")
        return subprocess.CompletedProcess(args, build_returncode, "", "compile failed")

    foundry._forge_version.cache_clear()
    monkeypatch.setattr(foundry.subprocess, "run", fake_run)
    return calls


def test_second_pristine_workspace_restores_without_build(tmp_path, monkeypatch) -> None:
    calls = _fake_forge(monkeypatch)
    cache = tmp_path / "shared-cache"
    first = ToolContext(_workspace(tmp_path / "one"), forge_cache_dir=cache)
    second = ToolContext(_workspace(tmp_path / "two"), forge_cache_dir=cache)

    assert foundry.prime_compile_cache(first)
    assert foundry.prime_compile_cache(second)

    assert calls["build"] == 1
    assert (second.workspace / "out" / "Target.json").read_text() == "artifact"
    assert (second.workspace / "cache" / "solidity-files-cache.json").read_text() == "metadata"


def test_source_edit_misses_compile_cache(tmp_path, monkeypatch) -> None:
    calls = _fake_forge(monkeypatch)
    cache = tmp_path / "shared-cache"
    first = ToolContext(_workspace(tmp_path / "one"), forge_cache_dir=cache)
    second = ToolContext(_workspace(tmp_path / "two"), forge_cache_dir=cache)
    assert foundry.prime_compile_cache(first)
    (second.workspace / "src" / "Target.sol").write_text("contract Target { uint x; }")
    assert foundry.prime_compile_cache(second)
    assert calls["build"] == 2


def test_failed_build_is_not_cached(tmp_path, monkeypatch) -> None:
    calls = _fake_forge(monkeypatch, build_returncode=1)
    cache = tmp_path / "shared-cache"
    ctx = ToolContext(_workspace(tmp_path / "one"), forge_cache_dir=cache)
    assert not foundry.prime_compile_cache(ctx)
    assert not foundry.prime_compile_cache(ctx)
    assert calls["build"] == 2
    assert not cache.exists()


def test_disabled_cache_does_not_precompile(tmp_path, monkeypatch) -> None:
    calls = _fake_forge(monkeypatch)
    ctx = ToolContext(_workspace(tmp_path), forge_cache_dir=None)
    assert not foundry.prime_compile_cache(ctx)
    assert calls["build"] == 0


def test_forge_version_change_misses_cache(tmp_path, monkeypatch) -> None:
    calls = _fake_forge(monkeypatch)
    cache = tmp_path / "shared-cache"
    first = ToolContext(_workspace(tmp_path / "one"), forge_cache_dir=cache)
    second = ToolContext(_workspace(tmp_path / "two"), forge_cache_dir=cache)
    assert foundry.prime_compile_cache(first)
    foundry._forge_version.cache_clear()
    monkeypatch.setattr(foundry, "_forge_version", lambda: "forge 2.0.0")
    assert foundry.prime_compile_cache(second)
    assert calls["build"] == 2
