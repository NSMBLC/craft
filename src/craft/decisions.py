"""Researcher decisions, as functions shared by the CLI (terminal) and the prompt hook.

Each function performs one decision after `confirm(preview)` returns True. The CLI passes an
interactive y/N. The UserPromptSubmit hook passes an always-yes, because the researcher typing
the exact command as a message *is* the deliberate act; the hook is a process the model does
not control, and it only ever runs on text the researcher typed.
"""

from __future__ import annotations

import re
import shlex
import shutil
from pathlib import Path
from typing import Callable

from . import envlock
from .artifacts.closure import close_investigation
from .artifacts.problem import validate_problem
from .cli_support import pick_investigation, verify_investigation
from .freeze import freeze_file, thaw_file
from .paths import InvestigationPaths, Programme
from .state import Approval, InvestigationState, Phase
from .util import CraftError, now_iso, read_doc, sha256_file

Confirm = Callable[[str], bool]


class Declined(CraftError):
    """The researcher answered no."""


def _ctx(prog: Programme, inv_id: str | None) -> tuple[InvestigationPaths, InvestigationState]:
    inv_id = pick_investigation(prog, inv_id)
    root = prog.investigation_dir(inv_id)
    inv = InvestigationPaths(root)
    state = InvestigationState.load(root)
    if state.phase == Phase.FROZEN and inv.tasks.exists():
        state.phase = Phase.EXECUTING
        state.save(root)
    return inv, state


def _template(name: str) -> str:
    from importlib import resources

    return resources.files("craft.templates").joinpath(name).read_text(encoding="utf-8")


def approve_problem(prog: Programme, inv_id: str | None, note: str, confirm: Confirm, via: str) -> str:
    inv, state = _ctx(prog, inv_id)
    state.require_untainted("approve problem")
    state.require_phase(Phase.FRAMING, action="approve problem")
    v = validate_problem(inv.problem, int(prog.config["limits"]["problem_max_words"]))
    if not v.ok:
        raise CraftError("problem.md is not complete:\n" + v.render())
    fm, _ = read_doc(inv.problem)
    so = fm.get("so_that") or {}
    preview = "\n".join([
        f"Problem statement for {state.id} ({inv.problem.relative_to(prog.root)}):",
        f"  studying:    {fm.get('studying')}",
        f"  to find out: {fm.get('to_find_out')}",
        f"  so that:     {so.get('reader')} understands {so.get('understands')}",
        f"  cost:        {fm.get('cost_of_not_answering')}",
        f"  kill:        {[k.get('condition') for k in fm.get('kill_criteria', [])]}",
    ])
    if not confirm(preview + "\nApprove and freeze this problem statement?"):
        raise Declined("Not approved.")
    digest = freeze_file(inv.problem)
    state.problem_sha256 = digest
    state.approvals.append(Approval(what="problem", when=now_iso(), sha256=digest, note=note))
    state.attend("approve-problem", "problem.md", (note + " " if note else "") + f"[via {via}]")
    state.phase = Phase.DESIGNING
    if not inv.hypothesis.exists():
        inv.hypothesis.write_text(_template("hypothesis.md").replace("{id}", state.id), encoding="utf-8")
    state.save(inv.root)
    return preview + f"\nApproved. problem.md frozen (sha256 {digest[:12]}). Phase: designing. hypothesis.md draft created."


def env_approve(prog: Programme, inv_id: str | None, lock: Path | None, confirm: Confirm, via: str) -> str:
    inv, state = _ctx(prog, inv_id)
    prop = envlock.pending(state)
    if not prop:
        raise CraftError("no pending environment proposal")
    preview = f"Proposal for {state.id}: add '{prop['package']}' — {prop['reason']}"
    if not confirm(preview + "\nApprove this environment change?"):
        raise Declined("Not approved.")
    v = envlock.approve(inv, state, lock)
    state.attend("approve-env", prop["package"], f"{prop['reason']} [via {via}]")
    state.save(inv.root)
    return preview + f"\nEnvironment is now v{v} (sha256 {state.env.lock_sha256[:12]}). Subsequent verdicts record v{v}."


def env_reject(prog: Programme, inv_id: str | None, note: str, via: str) -> str:
    inv, state = _ctx(prog, inv_id)
    envlock.reject(inv, state, note)
    state.attend("reject-env", "env", f"{note} [via {via}]")
    state.save(inv.root)
    return "Proposal rejected; execution may continue with the current environment."


def close(prog: Programme, inv_id: str | None, note: str, incomplete: bool, confirm: Confirm, via: str) -> str:
    inv, state = _ctx(prog, inv_id)
    problems = verify_investigation(prog, state.id)
    if problems:
        raise CraftError("integrity problems block closure:\n  " + "\n  ".join(problems))
    state = InvestigationState.load(inv.root)
    state.require_untainted("close")
    if state.phase == Phase.EXECUTING and incomplete:
        state.phase = Phase.CLOSING
        state.attend("close-incomplete", state.id, note or "closed before all criteria had verdicts")
    state.require_phase(Phase.CLOSING, action="close")
    lines = [f"Closing {state.id}: {len(state.verdicts)} verdict(s)" + (f", kill {state.kill.criterion}" if state.kill.triggered else "")]
    for v in state.verdicts:
        lines.append(f"  {v.criterion} ({v.experiment}): {v.label}")
    if inv.closure.exists():
        cfm, _ = read_doc(inv.closure)
        lines.append(f"  anomalies: {len(cfm.get('anomalies') or [])}")
    preview = "\n".join(lines)
    if not confirm(preview + "\nClose and archive? Memory will be updated."):
        raise Declined("Not closed.")
    routed = close_investigation(prog, inv, state, (note + " " if note else "") + f"[via {via}]")
    return preview + (f"\nClosed. findings +{len(routed['finding'])}, refuted +{len(routed['refuted'])}, "
                      f"open questions +{len(routed['open'])}. Archived to archive/{state.id}/ (read-only).")


def reopen_problem(prog: Programme, inv_id: str | None, note: str, confirm: Confirm, via: str) -> str:
    inv, state = _ctx(prog, inv_id)
    state.require_phase(Phase.DESIGNING, Phase.RESPONDING, action="reopen problem")
    if not confirm(f"Reopen problem.md of {state.id}? Approval is withdrawn."):
        raise Declined("Not reopened.")
    thaw_file(inv.problem)
    state.problem_sha256 = None
    state.phase = Phase.FRAMING
    state.attend("reopen", "problem.md", f"{note} [via {via}]")
    state.save(inv.root)
    return "problem.md reopened; phase: framing."


def reopen_review(prog: Programme, inv_id: str | None, note: str, confirm: Confirm, via: str) -> str:
    inv, state = _ctx(prog, inv_id)
    state.require_phase(Phase.RESPONDING, action="reopen review")
    last = state.review.rounds[-1]
    if sha256_file(inv.hypothesis) == last.hypothesis_sha256:
        raise CraftError("hypothesis.md has not changed since the last round; reopening requires a genuine design change first.")
    if not confirm(f"Archive {len(state.review.rounds)} round(s) of {state.id} and start a fresh review cycle?"):
        raise Declined("Not reopened.")
    k = len(state.review.history) + 1
    hist = inv.review_dir / f"history-{k}"
    hist.mkdir()
    for p in list(inv.review_dir.iterdir()):
        if p.is_file():
            p.chmod(0o644)
            shutil.move(str(p), str(hist / p.name))
    state.review.history.append([r.model_dump() for r in state.review.rounds])
    state.review.rounds = []
    state.review.exhausted = False
    state.phase = Phase.DESIGNING
    state.attend("reopen", "review", f"{note} [via {via}]")
    state.save(inv.root)
    return f"Review reopened (previous rounds in review/history-{k}/). Phase: designing."


def untaint(prog: Programme, inv_id: str | None, note: str, accept_current: bool, confirm: Confirm, via: str) -> str:
    inv, state = _ctx(prog, inv_id)
    if not state.tainted:
        return "not tainted"
    preview = "Taint reasons:\n  " + "\n  ".join(state.taint_reasons)
    if accept_current:
        if not confirm(preview + "\nRe-record the CURRENT contents of frozen files as authoritative? This is logged."):
            raise Declined("Not untainted.")
        if state.problem_sha256 and inv.problem.exists():
            state.problem_sha256 = freeze_file(inv.problem)
        if state.review.frozen_sha256 and inv.hypothesis.exists():
            state.review.frozen_sha256 = freeze_file(inv.hypothesis)
        if state.env.lock_sha256 and inv.env_lock.exists():
            inv.env_lock.chmod(0o444)
            state.env.lock_sha256 = sha256_file(inv.env_lock)
    state.tainted = False
    reasons = list(state.taint_reasons)
    state.taint_reasons = []
    state.attend("untaint", state.id, note + (" [accepted current contents]" if accept_current else "") + f" [via {via}] | " + "; ".join(reasons))
    state.save(inv.root)
    remaining = verify_investigation(prog, state.id)
    if remaining:
        raise CraftError("still failing integrity (restore the files or use --accept-current):\n  " + "\n  ".join(remaining))
    return preview + "\nUntainted."


# ------------------------------------------------------------- typed-prompt dispatch

# Accepted forms: `/craft-approve problem` (slash skill), `/craft approve problem`, `craft approve problem`
TYPED_RE = re.compile(
    r"^\s*(?:/craft[-\s]\s*|craft\s+)(approve\s+problem|approve\s+package|reject\s+package|close|reopen\s+problem|reopen\s+review|untaint)\b(.*)$",
    re.S,
)


def parse_typed(prompt: str) -> tuple[str, dict] | None:
    """Recognise a researcher decision typed verbatim as a single-line message.

    Returns (verb, options) or None when the message is anything else (the model handles it).
    """
    text = prompt.strip()
    if "\n" in text:
        return None
    m = TYPED_RE.match(text)
    if not m:
        return None
    verb = re.sub(r"\s+", " ", m.group(1))
    try:
        toks = shlex.split(m.group(2))
    except ValueError:
        return None
    opts: dict = {"inv": None, "note": "", "lock": None, "incomplete": False, "accept_current": False}
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "--inv" and i + 1 < len(toks):
            opts["inv"] = toks[i + 1]
            i += 2
        elif t == "--note" and i + 1 < len(toks):
            opts["note"] = toks[i + 1]
            i += 2
        elif t == "--lock" and i + 1 < len(toks):
            opts["lock"] = Path(toks[i + 1])
            i += 2
        elif t == "--incomplete":
            opts["incomplete"] = True
            i += 1
        elif t == "--accept-current":
            opts["accept_current"] = True
            i += 1
        else:
            return None
    return verb, opts


def run_typed(prog: Programme, verb: str, o: dict) -> str:
    """Execute a typed decision. Typing the command is the confirmation."""
    def typed_confirm(_preview: str) -> bool:
        return True

    via = "typed prompt"
    if verb == "approve problem":
        return approve_problem(prog, o["inv"], o["note"], typed_confirm, via)
    if verb == "approve package":
        return env_approve(prog, o["inv"], o["lock"], typed_confirm, via)
    if verb == "reject package":
        if not o["note"]:
            raise CraftError('`craft reject package` needs --note "why"')
        return env_reject(prog, o["inv"], o["note"], via)
    if verb == "close":
        return close(prog, o["inv"], o["note"], o["incomplete"], typed_confirm, via)
    if verb == "reopen problem":
        return reopen_problem(prog, o["inv"], o["note"] or "reopened by researcher", typed_confirm, via)
    if verb == "reopen review":
        return reopen_review(prog, o["inv"], o["note"] or "reopened by researcher", typed_confirm, via)
    if verb == "untaint":
        if not o["note"]:
            raise CraftError('`craft untaint` needs --note "what happened"')
        return untaint(prog, o["inv"], o["note"], o["accept_current"], typed_confirm, via)
    raise CraftError(f"unknown decision '{verb}'")
