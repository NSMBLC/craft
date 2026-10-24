"""Investigation state: what `craft` has recorded. The single source of truth for every gate.

Only `craft` writes state.json. What the researcher and agent *plan* (problem, hypotheses,
experiment plans, literature, questions) lives in editable files; state.json records what
*happened*: approvals, review rounds, registrations, verdicts, and the hash of every record file.
Statuses shown to the researcher are derived from both (see registry.py).
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .integrity import make_writable
from .paths import InvestigationPaths
from .util import CraftError, now_iso, read_json, write_json

SCHEMA_VERSION = 2


class Phase(str, Enum):
    FRAMING = "framing"  # problem.md being drafted; nothing approved
    OPEN = "open"        # problem approved; hypotheses and experiments come and go
    CLOSING = "closing"  # a kill criterion fired; no new evidence
    CLOSED = "closed"    # archived; memory updated

    def __ge__(self, other: "Phase") -> bool:  # type: ignore[override]
        return ORDER.index(self) >= ORDER.index(other)

    def __gt__(self, other: "Phase") -> bool:  # type: ignore[override]
        return ORDER.index(self) > ORDER.index(other)

    def __le__(self, other: "Phase") -> bool:  # type: ignore[override]
        return ORDER.index(self) <= ORDER.index(other)

    def __lt__(self, other: "Phase") -> bool:  # type: ignore[override]
        return ORDER.index(self) < ORDER.index(other)


ORDER = [Phase.FRAMING, Phase.OPEN, Phase.CLOSING, Phase.CLOSED]

# CRAFT v1 phases, so archived v1 investigations still load (for decisions, recall, explain).
LEGACY_PHASES = {"designing": "open", "responding": "open", "frozen": "open", "executing": "open"}


class Approval(BaseModel):
    what: str
    when: str
    sha256: str
    note: str = ""


class Acknowledgement(BaseModel):
    ref: str
    justification: str
    when: str


class ReviewRound(BaseModel):
    n: int
    when: str
    backend: str
    hypothesis_sha256: str
    objections: list[dict] = Field(default_factory=list)   # round-1 style
    judgements: list[dict] = Field(default_factory=list)   # round-2 style
    blocking_open: list[str] = Field(default_factory=list)
    advisory: list[str] = Field(default_factory=list)
    responses: dict[str, dict] = Field(default_factory=dict)  # objection id -> {pointer, note, when}


class HypothesisRecord(BaseModel):
    """What `craft` recorded about one hypothesis. Its file stays editable throughout."""

    rounds: list[ReviewRound] = Field(default_factory=list)  # the current review cycle
    exhausted: bool = False           # round cap hit with blocking objections still open
    cycles: list[list[dict]] = Field(default_factory=list)  # earlier cycles, archived under review/<id>/cycle-<k>/
    registered_at: str | None = None
    registered_sha256: str | None = None  # the file as it was when review concluded clean
    registrations: list[dict] = Field(default_factory=list)

    @property
    def open_blocking(self) -> list[str]:
        return list(self.rounds[-1].blocking_open) if self.rounds else []


class EnvState(BaseModel):
    version: int = 0
    lock_sha256: str | None = None
    history: list[dict] = Field(default_factory=list)
    pending_proposal: dict | None = None


class VerdictRef(BaseModel):
    experiment: str
    criterion: str        # "H1:C1" or a kill criterion id "K1"
    label: str
    file: str
    when: str
    post_hoc: bool = False  # the criterion was changed after registration


class KillState(BaseModel):
    triggered: bool = False
    criterion: str | None = None
    when: str | None = None
    evidence: str | None = None
    observed: float | None = None


class AttentionEntry(BaseModel):
    when: str
    kind: str            # approve-problem | approve-env | reject-env | close | untaint(resolve) | acknowledge
    subject: str
    note: str = ""


class InvestigationState(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: str
    topic: str
    created: str
    phase: Phase = Phase.FRAMING
    tainted: bool = False
    taint_reasons: list[str] = Field(default_factory=list)
    acknowledgements: list[Acknowledgement] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
    problem_sha256: str | None = None   # problem.md as last approved by the researcher
    hypotheses: dict[str, HypothesisRecord] = Field(default_factory=dict)
    env: EnvState = Field(default_factory=EnvState)
    verdicts: list[VerdictRef] = Field(default_factory=list)
    kill: KillState = Field(default_factory=KillState)
    attention: list[AttentionEntry] = Field(default_factory=list)
    records: dict[str, str] = Field(default_factory=dict)  # path (relative to the investigation) -> sha256
    closed_at: str | None = None
    closure_summary: dict | None = None

    @field_validator("phase", mode="before")
    @classmethod
    def _legacy_phase(cls, v):
        return LEGACY_PHASES.get(v, v) if isinstance(v, str) else v

    # ---- persistence -------------------------------------------------
    @classmethod
    def load(cls, inv_root: Path) -> "InvestigationState":
        p = InvestigationPaths(inv_root).state
        data = read_json(p)
        if data is None:
            raise CraftError(f"no state.json in {inv_root}")
        return cls.model_validate(data)

    def save(self, inv_root: Path) -> None:
        p = InvestigationPaths(inv_root).state
        make_writable(p)
        write_json(p, self.model_dump(mode="json"))

    # ---- helpers -----------------------------------------------------
    def hyp(self, hid: str) -> HypothesisRecord:
        return self.hypotheses.setdefault(hid, HypothesisRecord())

    def record(self, rel: str, sha256: str) -> None:
        self.records[rel] = sha256

    def attend(self, kind: str, subject: str, note: str = "") -> None:
        self.attention.append(AttentionEntry(when=now_iso(), kind=kind, subject=subject, note=note))

    def taint(self, reason: str) -> None:
        self.tainted = True
        if reason not in self.taint_reasons:
            self.taint_reasons.append(reason)

    def verdicts_for(self, experiment: str | None = None) -> list[VerdictRef]:
        return [v for v in self.verdicts if experiment is None or v.experiment == experiment]

    # ---- guards --------------------------------------------------------
    def require_phase(self, *allowed: Phase, action: str) -> None:
        if self.phase not in allowed:
            names = ", ".join(p.value for p in allowed)
            raise CraftError(
                f"cannot {action}: investigation {self.id} is in phase '{self.phase.value}' (allowed: {names})."
            )

    def require_untainted(self, action: str) -> None:
        if self.tainted:
            reasons = "; ".join(self.taint_reasons) or "integrity check failed"
            raise CraftError(
                f"cannot {action}: investigation {self.id} is on integrity hold ({reasons}). "
                "The researcher reviews what happened and types `/craft-resolve --note \"...\"`."
            )


def new_state(inv_id: str, topic: str) -> InvestigationState:
    return InvestigationState(id=inv_id, topic=topic, created=now_iso())
