"""The gate: may the *agent* perform this write right now?

Pure decision logic shared by the Claude Code hook and the CLI's own checks.
Everything the researcher's own code/data touches outside CRAFT-managed paths is allowed.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .paths import ARCHIVE_DIR, INVESTIGATIONS_DIR, MEMORY_DIR, PROGRAMME_MARKER, Programme
from .state import InvestigationState, Phase
from .util import CraftError

HUMAN_ONLY = ("approve", "close", "reopen", "untaint")  # `craft <verb>` and `craft env approve`
HUMAN_ONLY_RE = re.compile(
    r"\bcraft\b[^;&|\n]*?\b(approve|close|reopen|untaint|hook)\b|\bCRAFT_ALLOW_NON_TTY\b|\bCRAFT_HUMAN\b"
    r"|\buser-prompt-submit\b|\bhooks\.py\b|\bcraft\.hooks\b|\bcraft\.decisions\b|\bdecisions\.py\b"
)
# `2>&1`, `>&2`, `&>/dev/null`, `>/dev/null`, `2>/dev/null` are not file writes
HARMLESS_REDIRECT_RE = re.compile(r"\d*>&\d+|&>\s*/dev/null|\d*>{1,2}\s*/dev/null")
MUTATION_RE = re.compile(
    r"(?<![<>])>{1,2}(?!>)|\btee\b|\bmv\b|\bcp\b|\brm\b|\bchmod\b|\bchown\b|\bsed\s+-[a-zA-Z]*i|"
    r"\btruncate\b|\bln\b|\bmkdir\b|\brmdir\b|\bpatch\b|\bgit\s+(checkout|restore|reset|clean|stash)\b|"
    r"\bopen\([^)]*['\"][wa]|\bwrite_text\b|\bwrite_bytes\b|\bshutil\b|\bos\.(remove|unlink|rename|replace|chmod)\b|\bunlink\b"
)


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str = ""
    checkpoint: str = ""

    @staticmethod
    def ok() -> "Decision":
        return Decision(True)

    @staticmethod
    def deny(reason: str, checkpoint: str = "") -> "Decision":
        return Decision(False, reason, checkpoint)


def _load_state(prog: Programme, inv_id: str) -> InvestigationState | None:
    try:
        return InvestigationState.load(prog.investigation_dir(inv_id))
    except CraftError:
        return None


def decide_write(prog: Programme, target: Path) -> Decision:
    """Decide whether the agent may write/edit/delete `target` (absolute or relative to cwd)."""
    rel = prog.relpath(target if target.is_absolute() else Path.cwd() / target)
    if rel is None:
        return Decision.ok()  # outside the programme: not ours to police
    parts = PurePosixPath(rel.as_posix()).parts
    if not parts:
        return Decision.ok()
    head = parts[0]

    if head == PROGRAMME_MARKER or head == ".claude":
        return Decision.deny(
            f"{rel} is researcher-owned configuration (hooks and rules). The agent may not modify it; "
            "ask the researcher to edit it in their own editor."
        )
    if head == MEMORY_DIR:
        return Decision.deny(
            f"{rel}: institutional memory accepts entries only through the closing of an investigation "
            "(`craft close`, run by the researcher). Record the result as a verdict and close the "
            "investigation instead.",
            "5.6",
        )
    if head == ARCHIVE_DIR:
        return Decision.deny(f"{rel}: archived investigations are immutable.")
    if head != INVESTIGATIONS_DIR:
        return Decision.ok()
    if len(parts) < 2:
        return Decision.ok()  # creating the investigations dir itself
    inv_id = parts[1]
    inner = PurePosixPath(*parts[2:]) if len(parts) > 2 else PurePosixPath()
    state = _load_state(prog, inv_id)
    if state is None:
        # Not a CRAFT investigation yet (or state.json missing) — only `craft new` creates these.
        if inner.name == "state.json" or not inner.parts:
            return Decision.deny(
                f"investigations are created with `craft new {inv_id} --topic ...`, not by writing files."
            )
        return Decision.deny(
            f"{rel}: no investigation '{inv_id}' exists. Create it with `craft new` first."
        )
    return decide_investigation_write(state, inner)


def decide_investigation_write(state: InvestigationState, inner: PurePosixPath) -> Decision:
    """Gate table for paths inside an investigation (see plan)."""
    name = inner.as_posix()
    ph = state.phase
    inv = state.id

    if state.phase == Phase.CLOSED:
        return Decision.deny(f"investigation {inv} is closed; it is immutable.")

    if name == "state.json":
        return Decision.deny("state.json is written only by `craft`; use the corresponding command.")

    if name == "problem.md":
        if ph == Phase.FRAMING:
            return Decision.ok()
        return Decision.deny(
            f"problem.md of {inv} was approved by the researcher on "
            f"{_approval_date(state, 'problem')} and is frozen. If the framing must change, the "
            "researcher runs `craft reopen problem`; if the question itself changed, open a new "
            "investigation.",
            "1.6",
        )

    if name == "hypothesis.md":
        if ph in (Phase.DESIGNING, Phase.RESPONDING):
            return Decision.ok()
        if ph == Phase.FRAMING:
            return Decision.deny(
                "the problem statement has not been approved yet; the hypothesis is drafted after "
                "`craft approve problem`."
            )
        return Decision.deny(
            f"hypothesis.md of {inv} is frozen: review concluded clean on {state.review.frozen_at} "
            f"(round {len(state.review.rounds)}). Frozen documents cannot be modified at all, not even "
            "for typos. The pre-registered thresholds stand; if a different threshold is wanted, open a "
            "new investigation that declares it openly.",
            "5.5",
        )

    if inner.parts and inner.parts[0] == "review":
        if re.fullmatch(r"round-\d+\.json", inner.name):
            return Decision.deny(
                "review files are written only by the referee (`craft review request`). The agent "
                "never authors or edits a review.",
                "4.1",
            )
        if re.fullmatch(r"round-\d+-responses\.md", inner.name):
            if ph == Phase.RESPONDING:
                return Decision.ok()
            return Decision.deny(
                "responses are filed with `craft review respond` while a round has open objections."
            )
        return Decision.deny("the review directory is managed by `craft review`.")

    if name == "tasks.md":
        if ph >= Phase.FROZEN:
            return Decision.ok()
        return Decision.deny(_tasks_reason(state), _tasks_checkpoint(state))

    if name == "env.lock":
        return Decision.deny(
            "env.lock changes only through `craft env propose` (agent) followed by "
            "`craft env approve` (researcher).",
            "6.1",
        )
    if name == "env.proposal.yaml":
        return Decision.deny("environment proposals are written with `craft env propose`.")

    if inner.parts and inner.parts[0] == "experiments":
        if re.fullmatch(r"verdict-.*\.md", inner.name):
            return Decision.deny(
                "verdicts are computed by `craft verdict` from the frozen criteria and an evidence "
                "file; the agent never writes a label.",
                "6.2",
            )
        if ph >= Phase.EXECUTING and ph < Phase.CLOSED:
            if ph == Phase.CLOSING and len(inner.parts) >= 3 and inner.parts[2] == "evidence":
                return Decision.deny(
                    f"investigation {inv} is closing ({_closing_why(state)}); no new evidence is accepted."
                )
            return Decision.ok()
        return Decision.deny(
            f"experiments start after the design is frozen and tasks.md exists (phase is '{ph.value}'). "
            + state.blocked_reason()
        )

    if name == "closure.md":
        if ph in (Phase.CLOSING, Phase.EXECUTING):
            return Decision.ok()
        return Decision.deny("closure.md is written when the investigation is closing.")

    if inner.parts and inner.parts[0] == "literature":
        if ph in (Phase.DESIGNING, Phase.RESPONDING, Phase.FRAMING):
            return Decision.ok()
        return Decision.deny("the literature map is part of the frozen design.")

    # anything else inside the investigation (notes, code) is fine
    return Decision.ok()


def _approval_date(state: InvestigationState, what: str) -> str:
    for a in state.approvals:
        if a.what == what:
            return a.when
    return "an earlier date"


def _closing_why(state: InvestigationState) -> str:
    if state.kill.triggered:
        return f"kill criterion {state.kill.criterion} was met"
    return "all criteria have verdicts"


def _tasks_reason(state: InvestigationState) -> str:
    ph = state.phase
    if ph == Phase.FRAMING:
        return (
            "tasks.md cannot be written: the problem statement is not approved and the design has "
            "not been reviewed. Order is: approve problem -> draft hypothesis -> `craft review "
            "request` -> answer objections -> freeze -> tasks."
        )
    if ph == Phase.DESIGNING:
        return (
            "tasks.md cannot be written: the hypothesis has not been reviewed. Run `craft review "
            "request` and answer any blocking objections; tasks are written once review concludes."
        )
    if ph == Phase.RESPONDING:
        ids = ", ".join(state.open_blocking)
        return (
            f"tasks.md cannot be written: review round {len(state.review.rounds)} left blocking "
            f"objections open ({ids}). Answer each with `craft review respond` and request the next "
            "round; tasks are written once every blocking objection is answered."
        )
    return "tasks.md cannot be written in this phase."


def _tasks_checkpoint(state: InvestigationState) -> str:
    return "5.2" if state.phase == Phase.RESPONDING else "5.1"


# ---------------------------------------------------------------- bash screening

def decide_bash(prog: Programme, command: str, cwd: Path | None = None) -> Decision:
    """Screen a shell command the agent wants to run.

    Two rules: (1) human-only `craft` subcommands are never the agent's to run;
    (2) if the command looks like it mutates files, every path-like token that resolves into
    the programme is put through the write gate.
    This is a heuristic layer; chmod 444 + hashes are the backstop.
    """
    if HUMAN_ONLY_RE.search(command):
        return Decision.deny(
            "that `craft` command is a researcher decision (approve / close / reopen / untaint / env "
            "approve). Ask the researcher to type it as a plain message (e.g. `craft approve problem`); "
            "CRAFT executes typed decisions directly. The agent cannot approve on their behalf.",
            "1.6",
        )
    if not MUTATION_RE.search(HARMLESS_REDIRECT_RE.sub(" ", command)):
        return Decision.ok()
    base = cwd or Path.cwd()
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    seen: set[str] = set()
    for tok in tokens:
        tok = tok.strip("'\"`;,()")
        if not tok or tok.startswith("-") or "=" in tok and not ("/" in tok or tok.endswith(".md")):
            continue
        if "/" not in tok and not tok.endswith((".md", ".json", ".yaml", ".lock")):
            continue
        cand = tok.split("=", 1)[1] if "=" in tok else tok
        p = Path(cand)
        p = p if p.is_absolute() else base / p
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        d = decide_write(prog, p)
        if not d.allow:
            return Decision.deny(f"(shell) {d.reason}", d.checkpoint)
    return Decision.ok()
