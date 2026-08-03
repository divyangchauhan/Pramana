"""Content-addressed cache for deterministic tool output (design §9).

Some tool output is a pure function of its input: Slither's detector results
depend only on the analyzed source and the analyzer version, so a run over
identical source can reuse the previous result instead of re-invoking the slow
analyzer. Across the sweep — three runs per model, the same nine fixtures — that
turns dozens of identical Slither invocations into one.

The store is keyed on a content hash, so correctness is structural: identical
inputs collide on the same key by construction, and a changed source or an
analyzer upgrade produces a *new* key rather than serving a stale hit. Caching
is opt-in — a ``None`` cache directory disables it, preserving the uncached path
for tests and clean-room before/after measurements.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


def content_key(*parts: str | bytes) -> str:
    """A stable hex digest over ``parts`` — the cache key for those inputs.

    Each part is length-prefixed before hashing, so the boundaries between parts
    are unambiguous: ``("ab", "c")`` and ``("a", "bc")`` hash differently, and a
    caller can't accidentally collide two distinct inputs by concatenation.
    """
    h = hashlib.sha256()
    for part in parts:
        raw = part.encode() if isinstance(part, str) else part
        h.update(len(raw).to_bytes(8, "big"))
        h.update(raw)
    return h.hexdigest()


def cache_get(cache_dir: Path | None, key: str) -> str | None:
    """Return the cached text for ``key``, or ``None`` on a miss or a disabled
    (``cache_dir is None``) cache. A read error is treated as a miss — a caching
    layer must never turn a recoverable run into a failed one."""
    if cache_dir is None:
        return None
    try:
        return (cache_dir / f"{key}.txt").read_text()
    except OSError:
        return None


def cache_put(cache_dir: Path | None, key: str, value: str) -> None:
    """Store ``value`` under ``key``; a no-op when caching is disabled.

    The write goes to a per-process temp file and is atomically renamed into
    place, so a reader in a parallel sweep never observes a half-written entry.
    Any I/O error is swallowed: failing to *populate* the cache must not fail the
    run that produced the value.
    """
    if cache_dir is None:
        return
    tmp = cache_dir / f"{key}.{os.getpid()}.tmp"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp.write_text(value)
        os.replace(tmp, cache_dir / f"{key}.txt")
    except OSError:
        # Best-effort cleanup; the run continues uncached either way.
        try:
            tmp.unlink()
        except OSError:
            pass


def cache_tree_get(cache_dir: Path | None, key: str, dest: Path) -> bool:
    """Restore a cached directory tree into ``dest``.

    Returns ``True`` on a hit. As with the text cache, corrupt or unreadable
    entries degrade to misses rather than breaking the tool run.
    """
    if cache_dir is None:
        return False
    source = cache_dir / key
    try:
        if not source.is_dir():
            return False
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest)
        return True
    except OSError:
        try:
            if dest.exists():
                shutil.rmtree(dest)
        except OSError:
            pass
        return False


def cache_tree_put(cache_dir: Path | None, key: str, source: Path) -> None:
    """Atomically store ``source`` as a directory-tree cache entry."""
    if cache_dir is None or not source.is_dir():
        return
    dest = cache_dir / key
    tmp = cache_dir / f"{key}.{os.getpid()}.tmp"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            return
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(source, tmp)
        try:
            os.replace(tmp, dest)
        except OSError:
            # Another process may have won the race to populate this key.
            if not dest.exists():
                raise
    except OSError:
        try:
            if tmp.exists():
                shutil.rmtree(tmp)
        except OSError:
            pass
