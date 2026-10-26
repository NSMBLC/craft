"""The gate: may the *agent* perform this write right now?

Pure decision logic shared by the Claude Code hook and the CLI's own checks.
Everything the researcher's own code/data touches outside CRAFT-managed paths is allowed.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .paths import ARCHIVE_DIR, INVESTIGATIONS_DIR, MEMORY_DIR, PROGRAMME_MARKER, InvestigationPaths, Programme
from .state import InvestigationState, Phase
from .util import CraftError

HUMAN_ONLY = ("approve", "reject", "close", "reopen", "resolve", "correct")  # `craft <verb> ...`
# The verb must be the subcommand (`craft approve`, `uv run craft close`, `python -m craft.cli resolve`),
# not a word in a quoted reason or limitation text. The CLI also refuses these inside an agent tool
# call (human.require_human), so this screen is one layer of three.
HUMAN_ONLY_RE = re.compile(
    r"\bcraft(?:\.cli)?['\"]?\s+['\"]?(approve|reject|close|reopen|resolve|correct|hook)\b"
    r"|\bCRAFT_ALLOW_NON_TTY\b|\bCRAFT_HUMAN\b"
    r"|\buser-prompt-submit\b|\bhooks\.py\b|\bcraft\.hooks\b|\bcraft\.decisions\b|\bdecisions\.py\b"
)
# Not file writes: `2>&1`, `>&2`, `&>/dev/null`, `>/dev/null`, `2>/dev/null`, an email in angle
# brackets (`<name@host>` in commit trailers), and `->` / `=>` arrows in prose.
HARMLESS_REDIRECT_RE = re.compile(
    r"\d*>&\d+|&>\s*/dev/null|\d*>{1,2}\s*/dev/null|<[^<>\s]+@[^<>\s]+>|[-=]>"
)
# A file-open mode that writes (w, a, x or +), as a whole quoted string: only the mode argument counts,
# never a path that happens to start with "a" or "w" (open('archive/...') is a read).
_WRITE_MODE = r"""['"][rbt]*[wax+][rwabxt+]*['"]"""
MUTATION_RE = re.compile(
    r"(?<![<>])>{1,2}(?!>)|\btee\b|\bmv\b|\bcp\b|\brm\b|\bchmod\b|\bchown\b|\bsed\s+-[a-zA-Z]*i|"
    r"\btruncate\b|\bln\b|\bmkdir\b|\brmdir\b|\bpatch\b|\bgit\s+(checkout|restore|reset|clean|stash)\b|"
    rf"\bopen\([^)]*?,\s*(?:mode\s*=\s*)?{_WRITE_MODE}|\.open\(\s*(?:mode\s*=\s*)?{_WRITE_MODE}|"
    r"\bwrite_text\b|\bwrite_bytes\b|\bshutil\b|\bos\.(remove|unlink|rename|replace|chmod)\b|\bunlink\b"
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
            "(the researcher types `/craft-close`). Record the result as a verdict and let the "
            "investigation close instead.",
            "5.6",
        )
    if head == ARCHIVE_DIR:
        return Decision.deny(f"{rel}: archived investigations are the record of what happened; they are never edited.")
    from . import data as data_mod

    held = data_mod.covering(prog, rel.as_posix())
    if held:
        return Decision.deny(
            f"{rel} is recorded input data ('{held[1]}' in {held[0]}); criteria depend on it, so it is never changed in "
            "place. Write a new snapshot elsewhere and record it under a new id (`craft data add <path> --id <new-id>`)."
        )
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
    return decide_investigation_write(state, inner, InvestigationPaths(prog.investigation_dir(inv_id)))


def decide_investigation_write(state: InvestigationState, inner: PurePosixPath,
                               inv: InvestigationPaths | None = None) -> Decision:
    """Gate table for paths inside an investigation.

    Plans (problem, hypotheses, experiment plans, literature, questions, closure, notes, code) are
    the agent's to write until the investigation closes. Records of what happened (state, reviews,
    registered snapshots, verdicts, cited evidence, env.lock) are written only by `craft`.
    Evidence may be produced only for hypotheses that review has registered.
    """
    name = inner.as_posix()
    ph = state.phase
    inv_id = state.id

    if ph == Phase.CLOSED:
        return Decision.deny(f"investigation {inv_id} is closed; it is the record of what happened.")

    if name == "state.json":
        return Decision.deny("state.json is written only by `craft`; use the corresponding command.")

    if inner.parts and inner.parts[0] == "review":
        if inner.name == "registered.md":
            return Decision.deny(
                f"{name} is the hypothesis exactly as review registered it. Edit hypotheses/{inner.parts[1] if len(inner.parts) > 2 else '<id>'}.md "
                "instead: changes to criteria after registration are allowed and recorded as post-hoc in every verdict.",
                "5.5",
            )
        if re.fullmatch(r"round-\d+\.(json|prompt\.md|hypothesis\.md)", inner.name):
            return Decision.deny(
                "review files are written only by the referee (`craft review`). The agent "
                "never authors or edits a review.",
                "4.1",
            )
        return Decision.deny("the review directory is managed by `craft review` (responses: `craft review respond`).")

    if name == "env.lock":
        return Decision.deny(
            "env.lock changes only through `craft propose package` (agent) followed by "
            "`/craft-approve` (researcher).",
            "6.1",
        )
    if name == "env.proposal.yaml":
        return Decision.deny("package proposals are written with `craft propose package`.")

    if inner.parts and inner.parts[0] == "experiments" and len(inner.parts) >= 3:
        exp = inner.parts[1]
        if re.fullmatch(r"verdict-.*\.md", inner.name) and len(inner.parts) == 3:
            return Decision.deny(
                "verdicts are computed by `craft verdict` from the registered criteria and an evidence "
                "file; the agent never writes a label.",
                "6.2",
            )
        if inner.parts[2] == "evidence":
            if name in state.records:
                return Decision.deny(
                    f"{name} is the evidence a verdict cites; records of what happened are never edited (sha256 "
                    "recorded in state.json). Produce new evidence in a new file, or plan a new experiment.",
                    "6.2",
                )
            return _evidence_write(state, exp, inv)
    if name in state.records:
        return Decision.deny(f"{name} is a record `craft` wrote; it is never edited (sha256 recorded in state.json).")
    return Decision.ok()


def _evidence_write(state: InvestigationState, exp: str, inv: InvestigationPaths | None) -> Decision:
    if state.phase == Phase.FRAMING:
        return Decision.deny(
            "no evidence before the problem statement is approved: the researcher types `/craft-approve`, "
            "then evidence is produced for registered hypotheses (or kill-criterion pilots).",
            "5.1",
        )
    if state.phase == Phase.CLOSING:
        return Decision.deny(
            f"investigation {state.id} is closing (kill criterion {state.kill.criterion} was met); no new evidence is accepted."
        )
    if inv is None:
        return Decision.ok()
    from . import registry

    plan = inv.experiment_plan(exp)
    if not plan.exists():
        return Decision.ok()  # unplanned evidence (e.g. a kill-criterion pilot); `craft verdict` checks it
    view = registry.exp_view(inv, state, exp)
    if view.exploratory:
        return Decision.deny(
            f"experiment {exp} is planned as exploratory: its results go in experiments/{exp}/exploratory/, "
            "which can never back a criterion.",
            "6.3",
        )
    for hid in dict.fromkeys(t.split(":")[0] for t in view.tests):
        hv = registry.hyp_view(inv, state, hid)
        if hv.rec.registered_sha256:
            continue
        if hv.status == "in review":
            last = hv.rec.rounds[-1]
            missing = [o for o in last.blocking_open if o not in last.responses]
            return Decision.deny(
                f"experiment {exp} tests {hid}, which is not registered: review round {len(hv.rec.rounds)} left blocking "
                f"objections open ({', '.join(last.blocking_open)}). Answer each with `craft review respond` "
                f"({', '.join(missing) or 'all answered'} remaining) and request the next round; evidence is "
                "produced once review registers it.",
                "5.2",
            )
        if hv.status == "dropped":
            return Decision.deny(f"experiment {exp} tests {hid}, which is dropped or has no file; update the plan's tests.")
        return Decision.deny(
            f"experiment {exp} tests {hid}, which has not been reviewed: it is a draft. Complete it, run "
            "`craft review`, and produce evidence once review registers it (criteria fixed before data). "
            f"Exploratory runs may go in experiments/{exp}/exploratory/ now.",
            "5.1",
        )
    return Decision.ok()


# ---------------------------------------------------------------- bash screening

def decide_bash(prog: Programme, command: str, cwd: Path | None = None) -> Decision:
    """Screen a shell command the agent wants to run.

    Two rules: (1) human-only `craft` subcommands are never the agent's to run;
    (2) if the command looks like it mutates files, every path-like token that resolves into
    the programme is put through the write gate.
    This is a heuristic layer; recorded hashes (`craft verify`) are the backstop.
    """
    if HUMAN_ONLY_RE.search(command):
        return Decision.deny(
            "that `craft` command is a researcher decision (approve / reject / close / reopen / resolve / correct). "
            "Ask the researcher to type it as a slash command (e.g. `/craft-approve`); "
            "CRAFT executes typed decisions directly. The agent cannot approve on their behalf.",
            "1.6",
        )
    mutation = MUTATION_RE.search(HARMLESS_REDIRECT_RE.sub(" ", command))
    if not mutation:
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
            return Decision.deny(
                f"(shell) {d.reason} [the command looked like a write because of `{mutation.group(0)}` and "
                f"mentions `{tok}`; if it does not write that file, rephrase the command]",
                d.checkpoint,
            )
    return Decision.ok()
