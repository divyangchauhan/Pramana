"""Per-run Foundry workspaces and fixture loading.

Each audit runs in a throwaway workspace: a copy of the Foundry template
(foundry.toml + a symlink to the shared vendored forge-std) plus the fixture's
target source under src/. Grading builds a *fresh* workspace with pristine src
and copies in only the agent's PoC file, so the agent cannot fake a pass by
editing the target.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = EVAL_DIR / "foundry_template"
DATASETS_DIR = EVAL_DIR / "datasets"


@dataclass
class KnownBug:
    id: str
    vuln_class: str
    location: str
    description: str


@dataclass
class Fixture:
    name: str
    dir: Path
    contract: str  # workspace-relative, e.g. "src/EtherStore.sol"
    reference_poc: str | None
    known_bugs: list[KnownBug]

    @property
    def src_dir(self) -> Path:
        return self.dir / "src"


def load_fixtures(
    datasets_dir: Path = DATASETS_DIR, names: list[str] | None = None
) -> list[Fixture]:
    fixtures: list[Fixture] = []
    for meta_path in sorted(datasets_dir.glob("*/fixture.json")):
        data = json.loads(meta_path.read_text())
        if names and data["name"] not in names:
            continue
        fixtures.append(
            Fixture(
                name=data["name"],
                dir=meta_path.parent,
                contract=data["contract"],
                reference_poc=data.get("reference_poc"),
                known_bugs=[KnownBug(**b) for b in data.get("known_bugs", [])],
            )
        )
    return fixtures


DEPS_DIR = TEMPLATE_DIR / "dependencies"


def ensure_dependencies_installed() -> None:
    """Fail with an actionable message if forge-std (a Soldeer dependency) has
    not been restored into the template. Committed to the repo are foundry.toml
    and soldeer.lock; the `dependencies/` tree itself is fetched, not vendored."""
    if not any(DEPS_DIR.glob("forge-std-*/src/Test.sol")):
        raise RuntimeError(
            "forge-std is not installed. Restore Foundry dependencies once with:\n"
            f"    (cd {TEMPLATE_DIR} && forge soldeer install)"
        )


def _scaffold(dest: Path) -> None:
    ensure_dependencies_installed()
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(TEMPLATE_DIR / "foundry.toml", dest / "foundry.toml")
    deps_link = dest / "dependencies"
    if deps_link.is_symlink() or deps_link.exists():
        if deps_link.is_symlink() or deps_link.is_file():
            deps_link.unlink()
        else:
            shutil.rmtree(deps_link)
    os.symlink(DEPS_DIR, deps_link)
    (dest / "src").mkdir(exist_ok=True)
    (dest / "test").mkdir(exist_ok=True)


def build_workspace(fixture: Fixture, dest: Path) -> Path:
    """Create a workspace with the fixture's target source under src/."""
    if dest.exists():
        shutil.rmtree(dest)
    _scaffold(dest)
    for sol in fixture.src_dir.glob("*.sol"):
        shutil.copy(sol, dest / "src" / sol.name)
    return dest
