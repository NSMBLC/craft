"""Programme discovery and canonical paths.

A *programme* is the researcher's repo, marked by `craft.yaml` at its root.
An *investigation* lives under `investigations/<id>/` until closed, then `archive/<id>/`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .util import CraftError, read_yaml

# Hypothesis files are hypotheses/<id>.md; ids start with a letter and never contain ':' (used in H1:C1).
HYP_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def natural_key(s: str) -> list:
    """Sort H2 before H10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

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
    def legacy_hypothesis(self) -> Path:
        """CRAFT v1 kept a single hypothesis here; v2 investigations never have it."""
        return self.root / "hypothesis.md"

    @property
    def hypotheses_dir(self) -> Path:
        return self.root / "hypotheses"

    def hypothesis(self, hid: str) -> Path:
        return self.hypotheses_dir / f"{hid}.md"

    def hypothesis_ids(self) -> list[str]:
        if not self.hypotheses_dir.exists():
            return []
        ids = [p.stem for p in self.hypotheses_dir.glob("*.md") if HYP_ID_RE.match(p.stem)]
        return sorted(ids, key=natural_key)

    @property
    def questions(self) -> Path:
        return self.root / "questions.md"

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

    def hyp_review_dir(self, hid: str) -> Path:
        return self.review_dir / hid

    def review_round(self, hid: str, n: int) -> Path:
        return self.hyp_review_dir(hid) / f"round-{n}.json"

    def review_prompt(self, hid: str, n: int) -> Path:
        """Exactly what the referee was shown in round n (documents included)."""
        return self.hyp_review_dir(hid) / f"round-{n}.prompt.md"

    def review_snapshot(self, hid: str, n: int) -> Path:
        return self.hyp_review_dir(hid) / f"round-{n}.hypothesis.md"

    def review_responses(self, hid: str, n: int) -> Path:
        return self.hyp_review_dir(hid) / f"round-{n}-responses.md"

    def registered(self, hid: str) -> Path:
        """The hypothesis exactly as it was when review concluded clean."""
        return self.hyp_review_dir(hid) / "registered.md"

    @property
    def experiments_dir(self) -> Path:
        return self.root / "experiments"

    def experiment(self, name: str) -> Path:
        return self.experiments_dir / name

    def experiment_plan(self, name: str) -> Path:
        return self.experiment(name) / "plan.md"

    def experiment_names(self) -> list[str]:
        if not self.experiments_dir.exists():
            return []
        return sorted((p.name for p in self.experiments_dir.iterdir() if p.is_dir() and not p.name.startswith(".")),
                      key=natural_key)

    def evidence_dir(self, name: str) -> Path:
        return self.experiment(name) / "evidence"

    def exploratory_dir(self, name: str) -> Path:
        return self.experiment(name) / "exploratory"

    def verdict(self, name: str, criterion: str) -> Path:
        """criterion is `H1:C1` (hypothesis criterion) or `K1` (kill criterion)."""
        return self.experiment(name) / f"verdict-{criterion.replace(':', '-')}.md"

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()
