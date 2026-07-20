"""Tests for eval workspace scaffolding / Soldeer dependency guard (offline)."""

from __future__ import annotations

import pytest

from pramana.eval import workspace


def test_dependencies_present():
    # forge-std has been restored via Soldeer, so the guard passes.
    workspace.ensure_dependencies_installed()


def test_missing_dependencies_raises_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "DEPS_DIR", tmp_path)  # empty dir, no forge-std
    with pytest.raises(RuntimeError, match="forge soldeer install"):
        workspace.ensure_dependencies_installed()
