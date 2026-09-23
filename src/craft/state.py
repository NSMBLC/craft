"""Investigation state: the single source of truth for every gate.

Only `craft` writes state.json. Transitions are explicit functions that refuse
illegal moves with a reason the researcher can read.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .paths import InvestigationPaths
from .util import CraftError, now_iso, read_json, write_json


class Phase(str, Enum):
    FRAMING = "framing"        # problem.md being drafted; nothing approved
    DESIGNING = "designing"    # problem approved (frozen); hypothesis is a draft
    RESPONDING = "responding"  # a review round left blocking objections open
    FROZEN = "frozen"          # review concluded clean; hypothesis immutable
    EXECUTING = "executing"    # tasks.md exists; experiments running
    CLOSING = "closing"        # all criteria judged or kill criterion met
    CLOSED = "closed"          # archived; memory updated

    def __ge__(self, other: "Phase") -> bool:  # type: ignore[override]
        return ORDER.index(self) >= ORDER.index(other)

    def __gt__(self, other: "Phase") -> bool:  # type: ignore[override]
        return ORDER.index(self) > ORDER.index(other)

    def __le__(self, other: "Phase") -> bool:  # type: ignore[override]
        return ORDER.index(self) <= ORDER.index(other)

    def __lt__(self, other: "Phase") -> bool:  # type: ignore[override]
        return ORDER.index(self) < ORDER.index(other)


ORDER = [
    Phase.FRAMING,
    Phase.DESIGNING,
    Phase.RESPONDING,
    Phase.FROZEN,
    Phase.EXECUTING,
    Phase.CLOSING,
    Phase.CLOSED,
]


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


class ReviewState(BaseModel):
    rounds: list[ReviewRound] = Field(default_factory=list)
    exhausted: bool = False           # round cap hit with blocking objections still open
    frozen_at: str | None = None
    frozen_sha256: str | None = None
    history: list[list[dict]] = Field(default_factory=list)  # rounds archived by `craft reopen review`


class EnvState(BaseModel):
    version: int = 0
    lock_sha256: str | None = None
    history: list[dict] = Field(default_factory=list)
    pending_proposal: dict | None = None


class VerdictRef(BaseModel):
    experiment: str
    criterion: str
    label: str
    file: str
    when: str


class KillState(BaseModel):
    triggered: bool = False
    criterion: str | None = None
    when: str | None = None
    evidence: str | None = None
    observed: float | None = None


class AttentionEntry(BaseModel):
    when: str
    kind: str            # approve-problem | approve-env | reject-env | close | reopen | untaint(resolve) | acknowledge
    subject: str
    note: str = ""


class InvestigationState(BaseModel):
    id: str
    topic: str
    created: str
    phase: Phase = Phase.FRAMING
    tainted: bool = False
    taint_reasons: list[str] = Field(default_factory=list)
    acknowledgements: list[Acknowledgement] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
    problem_sha256: str | None = None
    review: ReviewState = Field(default_factory=ReviewState)
    env: EnvState = Field(default_factory=EnvState)
    verdicts: list[VerdictRef] = Field(default_factory=list)
    kill: KillState = Field(default_factory=KillState)
    attention: list[AttentionEntry] = Field(default_factory=list)
    closed_at: str | None = None
    closure_summary: dict | None = None

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
        # state.json is kept read-only between writes so accidental edits fail loudly
        if p.exists():
            p.chmod(0o644)
        write_json(p, self.model_dump(mode="json"))
        p.chmod(0o444)

    # ---- derived -----------------------------------------------------
    @property
    def current_round(self) -> ReviewRound | None:
        return self.review.rounds[-1] if self.review.rounds else None

    @property
    def open_blocking(self) -> list[str]:
        r = self.current_round
        return list(r.blocking_open) if r else []

    @property
    def is_frozen(self) -> bool:
        return self.phase >= Phase.FROZEN

    def attend(self, kind: str, subject: str, note: str = "") -> None:
        self.attention.append(AttentionEntry(when=now_iso(), kind=kind, subject=subject, note=note))

    def taint(self, reason: str) -> None:
        self.tainted = True
        if reason not in self.taint_reasons:
            self.taint_reasons.append(reason)

    # ---- transitions ---------------------------------------------------
    def require_phase(self, *allowed: Phase, action: str) -> None:
        if self.phase not in allowed:
            names = ", ".join(p.value for p in allowed)
            raise CraftError(
                f"cannot {action}: investigation {self.id} is in phase '{self.phase.value}' "
                f"(allowed: {names}). {self.blocked_reason()}"
            )

    def require_untainted(self, action: str) -> None:
        if self.tainted:
            reasons = "; ".join(self.taint_reasons) or "integrity check failed"
            raise CraftError(
                f"cannot {action}: investigation {self.id} is on integrity hold ({reasons}). "
                "The researcher reviews what happened and types `/craft-resolve --note \"...\"`."
            )

    def next_action(self) -> tuple[str, str, str]:
        """(who, command, sentence): whose turn it is, the exact command they type, and why.

        `who` is "researcher" or "agent" (or "nobody" when closed). Researcher commands are
        given in slash form; agent commands in `craft ...` form.
        """
        if self.tainted:
            return ("researcher", "/craft-resolve --note \"...\"",
                    "the investigation is on integrity hold: " + ("; ".join(self.taint_reasons) or "a frozen file changed"))
        ph = self.phase
        if ph == Phase.FRAMING:
            return ("researcher", "/craft-approve",
                    "the one-page problem statement awaits the researcher's reading and approval "
                    "(the agent first fills it in and runs `craft validate problem`)")
        if ph == Phase.DESIGNING:
            if self.review.rounds:
                return ("agent", "craft review", "review was reopened; request a new round once the design has changed")
            return ("agent", "craft review", "draft hypothesis.md, run `craft validate`, then request the independent review")
        if ph == Phase.RESPONDING:
            ids = ", ".join(self.open_blocking) or "none listed"
            if self.review.exhausted:
                return ("researcher", "/craft-reopen review --note \"...\"",
                        f"review round {len(self.review.rounds)} left blocking objections unresolved ({ids}) and the "
                        "round cap is reached; the design must be genuinely fixed, then the researcher reopens review")
            return ("agent", "craft review respond <id> --pointer <doc#section> --note \"...\"",
                    f"review round {len(self.review.rounds)} has open blocking objections ({ids}); change the design, "
                    "answer each, then `craft review` for the next round")
        if ph == Phase.FROZEN:
            return ("agent", "write tasks.md", "the design is frozen; writing tasks.md starts execution")
        if ph == Phase.EXECUTING:
            if self.env.pending_proposal:
                return ("researcher", "/craft-approve",
                        f"the agent proposed adding '{self.env.pending_proposal['package']}' to the locked environment; "
                        "execution is halted until approved (or `/craft-reject --note`)")
            return ("agent", "craft verdict <exp> --criterion <name> --evidence <file>",
                    "run the experiments and file a verdict per criterion; a kill criterion or the last verdict routes to closure")
        if ph == Phase.CLOSING:
            return ("researcher", "/craft-close",
                    ("kill criterion met" if self.kill.triggered else "every criterion has a verdict")
                    + "; the agent writes closure.md (anomalies -> open questions), then the researcher closes")
        return ("nobody", "", "closed and archived")

    def blocked_reason(self) -> str:
        """One sentence: what stands between this investigation and the next gate, and who acts."""
        who, cmd, why = self.next_action()
        if who == "nobody":
            return "Closed."
        return f"{why}. Waiting on the {who}: `{cmd}`."


def new_state(inv_id: str, topic: str) -> InvestigationState:
    return InvestigationState(id=inv_id, topic=topic, created=now_iso())


def dump_public(state: InvestigationState) -> dict[str, Any]:
    """Compact view for `craft status`."""
    return {
        "id": state.id,
        "phase": state.phase.value,
        "tainted": state.tainted,
        "open_blocking": state.open_blocking,
        "rounds": len(state.review.rounds),
        "frozen_at": state.review.frozen_at,
        "env_version": state.env.version,
        "pending_env_proposal": bool(state.env.pending_proposal),
        "verdicts": [v.model_dump() for v in state.verdicts],
        "kill": state.kill.model_dump(),
        "blocked": state.blocked_reason(),
    }
