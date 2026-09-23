"""Programme discovery and canonical paths.

A *programme* is the researcher's repo, marked by `craft.yaml` at its root.
An *investigation* lives under `investigations/<id>/` until closed, then `archive/<id>/`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .util import CraftError, read_yaml

PROGRAMME_MARKER = "craft.yaml"
MEMORY_DIR = "memory"
ARCHIVE_DIR = "archive"
INVESTIGATIONS_DIR = "investigations"

MEMORY_FILES = {
    "finding": "findings.jsonl",
    "refuted": "refuted.jsonl",
    "open": "open-questions.jsonl",
}

DEFAULT_CONFIG = {
    "version": 1,
    "host": "claude-code",
    "referee": {
        "backend": "claude",  # claude | command | fake
        "model": "opus",
        "command": None,  # for backend=command: prompt on stdin, JSON on stdout
    },
    "recall": {
        "min_overlap": 2,
        "require_ack_kinds": ["refuted"],
        "rerank": False,
    },
    "limits": {
        "problem_max_words": 600,
        "review_rounds": 2,
    },
}


def find_programme_root(start: Path | None = None) -> Path:
    """Walk up from start (default cwd) until craft.yaml is found."""
    env = os.environ.get("CRAFT_PROGRAMME")
    if env:
        p = Path(env).resolve()
        if (p / PROGRAMME_MARKER).exists():
            return p
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / PROGRAMME_MARKER).exists():
            return candidate
    raise CraftError(
        "not inside a CRAFT programme (no craft.yaml found up the tree). Run `craft init` first."
    )


@dataclass(frozen=True)
class Programme:
    root: Path

    @property
    def config(self) -> dict:
        cfg = read_yaml(self.root / PROGRAMME_MARKER, {}) or {}
        merged = _deep_merge(DEFAULT_CONFIG, cfg)
        return merged

    @property
    def memory_dir(self) -> Path:
        return self.root / MEMORY_DIR

    @property
    def archive_dir(self) -> Path:
        return self.root / ARCHIVE_DIR

    @property
    def investigations_dir(self) -> Path:
        return self.root / INVESTIGATIONS_DIR

    def memory_file(self, kind: str) -> Path:
        return self.memory_dir / MEMORY_FILES[kind]

    @property
    def memory_index(self) -> Path:
        return self.memory_dir / "index.json"

    def investigation_dir(self, inv_id: str) -> Path:
        return self.investigations_dir / inv_id

    def list_investigations(self) -> list[str]:
        if not self.investigations_dir.exists():
            return []
        return sorted(p.name for p in self.investigations_dir.iterdir() if (p / "state.json").exists())

    def list_archived(self) -> list[str]:
        if not self.archive_dir.exists():
            return []
        return sorted(p.name for p in self.archive_dir.iterdir() if (p / "state.json").exists())

    def relpath(self, path: Path) -> Path | None:
        """Path relative to programme root, or None if outside."""
        try:
            return path.resolve().relative_to(self.root)
        except ValueError:
            return None


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass(frozen=True)
class InvestigationPaths:
    """Every CRAFT-managed file inside one investigation."""

    root: Path

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def problem(self) -> Path:
        return self.root / "problem.md"

    @property
    def hypothesis(self) -> Path:
        return self.root / "hypothesis.md"

    @property
    def tasks(self) -> Path:
        return self.root / "tasks.md"

    @property
    def closure(self) -> Path:
        return self.root / "closure.md"

    @property
    def env_lock(self) -> Path:
        return self.root / "env.lock"

    @property
    def env_proposal(self) -> Path:
        return self.root / "env.proposal.yaml"

    @property
    def literature_dir(self) -> Path:
        return self.root / "literature"

    @property
    def sources(self) -> Path:
        return self.literature_dir / "sources.yaml"

    @property
    def lit_map(self) -> Path:
        return self.literature_dir / "map.md"

    @property
    def review_dir(self) -> Path:
        return self.root / "review"

    def review_round(self, n: int) -> Path:
        return self.review_dir / f"round-{n}.json"

    def review_responses(self, n: int) -> Path:
        return self.review_dir / f"round-{n}-responses.md"

    @property
    def experiments_dir(self) -> Path:
        return self.root / "experiments"

    def experiment(self, name: str) -> Path:
        return self.experiments_dir / name

    def evidence_dir(self, name: str) -> Path:
        return self.experiment(name) / "evidence"

    def exploratory_dir(self, name: str) -> Path:
        return self.experiment(name) / "exploratory"

    def verdict(self, name: str, criterion: str) -> Path:
        return self.experiment(name) / f"verdict-{criterion}.md"
