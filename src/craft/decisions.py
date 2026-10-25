"""Researcher decisions, as functions shared by the CLI (terminal) and the prompt hook.

Each function performs one decision after `confirm(preview)` returns True. The CLI passes an
interactive y/N. The UserPromptSubmit hook passes an always-yes, because the researcher typing
the exact command as a message *is* the deliberate act; the hook is a process the model does
not control, and it only ever runs on text the researcher typed.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Callable

from . import envlock, registry
from .artifacts.closure import close_investigation
from .artifacts.problem import validate_problem
from .cli_support import load_context, verify_investigation
from .paths import InvestigationPaths, Programme
from .state import Approval, InvestigationState, Phase
from .util import CraftError, now_iso, read_doc, sha256_file

Confirm = Callable[[str], bool]

REOPEN_RETIRED = (
    "Nothing to reopen: nothing is frozen. problem.md stays editable (a changed version is "
    "re-approved with `/craft-approve`), hypotheses stay editable (changes to criteria after registration are "
    "shown as post-hoc), and a review that hit its round cap starts a new cycle once the hypothesis genuinely "
    "changes (`craft review --hyp <id>`)."
)


class Declined(CraftError):
    """The researcher answered no."""


def _ctx(prog: Programme, inv_id: str | None) -> tuple[InvestigationPaths, InvestigationState]:
    return load_context(prog, inv_id)


def _template(name: str) -> str:
    from importlib import resources

    return resources.files("craft.templates").joinpath(name).read_text(encoding="utf-8")


def approve_problem(prog: Programme, inv_id: str | None, note: str, confirm: Confirm, via: str) -> str:
    inv, state = _ctx(prog, inv_id)
    state.require_untainted("approve problem")
    state.require_phase(Phase.FRAMING, Phase.OPEN, action="approve problem")
    reapproval = state.phase == Phase.OPEN
    if reapproval and not registry.problem_changed(inv, state):
        raise CraftError("problem.md has not changed since you approved it; nothing to approve.")
    v = validate_problem(inv.problem, int(prog.config["limits"]["problem_max_words"]))
    if not v.ok:
        raise CraftError("problem.md is not complete:\n" + v.render())
    fm, _ = read_doc(inv.problem)
    so = fm.get("so_that") or {}
    head = (f"Changed problem statement for {state.id} (approved version from {_last_approval(state)}):" if reapproval
            else f"Problem statement for {state.id} ({inv.problem.relative_to(prog.root)}):")
    preview = "\n".join([
        head,
        f"  studying:    {fm.get('studying')}",
        f"  to find out: {fm.get('to_find_out')}",
        f"  so that:     {so.get('reader')} understands {so.get('understands')}",
        f"  cost:        {fm.get('cost_of_not_answering')}",
        f"  kill:        {[k.get('condition') for k in fm.get('kill_criteria', [])]}",
    ])
    if not confirm(preview + "\nApprove this problem statement?"):
        raise Declined("Not approved.")
    digest = sha256_file(inv.problem)
    state.problem_sha256 = digest
    state.approvals.append(Approval(what="problem", when=now_iso(), sha256=digest, note=note))
    state.attend("approve-problem", "problem.md", (note + " " if note else "") + f"[via {via}]")
    if reapproval:
        state.save(inv.root)
        return preview + f"\nApproved (sha256 {digest[:12]}). Verdicts from now on record this version."
    state.phase = Phase.OPEN
    inv.hypotheses_dir.mkdir(exist_ok=True)
    created = ""
    if not inv.hypothesis_ids():
        inv.hypothesis("H1").write_text(_template("hypothesis.md").replace("{id}", state.id).replace("{hid}", "H1"),
                                        encoding="utf-8")
        created = " hypotheses/H1.md draft created."
    state.save(inv.root)
    return preview + f"\nApproved (sha256 {digest[:12]}). The investigation is open.{created}"


def _last_approval(state: InvestigationState) -> str:
    for a in reversed(state.approvals):
        if a.what == "problem":
            return a.when
    return "earlier"


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
    return "Proposal rejected; work may continue with the current environment."


def close(prog: Programme, inv_id: str | None, note: str, confirm: Confirm, via: str) -> str:
    """The researcher closes whenever they choose; whatever is unfinished is routed to open questions."""
    inv, state = _ctx(prog, inv_id)
    problems = verify_investigation(prog, state.id)
    if problems:
        raise CraftError("integrity problems block closure:\n  " + "\n  ".join(problems))
    state = InvestigationState.load(inv.root)
    state.require_untainted("close")
    state.require_phase(Phase.OPEN, Phase.CLOSING, action="close")
    if state.env.pending_proposal:
        raise CraftError("a package proposal is pending; `/craft-approve` or `/craft-reject --note ...` it first")
    lines = [f"Closing {state.id}" + (f" (kill criterion {state.kill.criterion} met)" if state.kill.triggered else "") + ":"]
    for h in registry.all_hypotheses(inv, state):
        if h.status == "dropped":
            continue
        crits = ", ".join(f"{c} {h.criteria_labels.get(c, 'untested')}" for c in h.criteria) if h.rec.registered_sha256 else "never registered"
        lines.append(f"  {h.id} {h.status}: {crits}" + (" [post-hoc criteria change recorded]" if h.post_hoc else ""))
    pending = [e.name for e in registry.all_experiments(inv, state) if e.status in ("planned", "run")]
    if pending:
        lines.append(f"  experiments not finished: {', '.join(pending)}")
    qs = registry.questions(inv)
    if qs:
        lines.append(f"  open questions in questions.md: {len(qs)}")
    if inv.closure.exists():
        cfm, _ = read_doc(inv.closure)
        lines.append(f"  anomalies: {len(cfm.get('anomalies') or [])}")
    preview = "\n".join(lines)
    if not confirm(preview + "\nClose and archive? Memory will be updated."):
        raise Declined("Not closed.")
    state.phase = Phase.CLOSING
    routed = close_investigation(prog, inv, state, (note + " " if note else "") + f"[via {via}]")
    return preview + (f"\nClosed. findings +{len(routed['finding'])}, refuted +{len(routed['refuted'])}, "
                      f"open questions +{len(routed['open'])}. Archived to archive/{state.id}/.")


def untaint(prog: Programme, inv_id: str | None, note: str, accept_current: bool, confirm: Confirm, via: str) -> str:
    inv, state = _ctx(prog, inv_id)
    if not state.tainted:
        return "not tainted"
    preview = "Taint reasons:\n  " + "\n  ".join(state.taint_reasons)
    if accept_current:
        if not confirm(preview + "\nRe-record the CURRENT contents of the recorded files as authoritative? This is logged."):
            raise Declined("Not untainted.")
        for rel in list(state.records):
            p = inv.root / rel
            if p.exists():
                state.records[rel] = sha256_file(p)
            else:
                del state.records[rel]
        if state.env.lock_sha256 and inv.env_lock.exists():
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

# Accepted forms: `/craft-approve` (slash skill), `/craft approve`, `craft approve`, each with optional
# subject and options. Read-only queries (status, help, decisions, explain) use the same channel.
DECISION_VERBS = ("approve", "reject", "close", "reopen", "resolve")
QUERY_VERBS = ("status", "help", "decisions", "explain")
TYPED_RE = re.compile(
    r"^\s*(?:/craft[-\s]\s*|craft\s+)(approve|reject|close|reopen|resolve|status|help|decisions|explain)\b(.*)$",
    re.S,
)
SUBJECTS = {"approve": {"problem", "package", None}, "reject": {"package", None}, "reopen": {"problem", "review"},
            "close": {None}, "resolve": {None}, "status": {None}, "help": {None}, "decisions": {None}}


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
    verb = m.group(1)
    try:
        toks = shlex.split(m.group(2))
    except ValueError:
        return None
    opts: dict = {"inv": None, "note": "", "lock": None, "incomplete": False, "accept_current": False,
                  "subject": None, "arg": None}
    if verb == "explain":
        if len(toks) != 1 or toks[0].startswith("-"):
            return None
        opts["arg"] = toks[0]
        return "explain", opts
    if toks and not toks[0].startswith("-"):
        opts["subject"] = toks.pop(0)
    if opts["subject"] not in SUBJECTS[verb]:
        return None
    if verb == "reopen" and opts["subject"] is None:
        return None
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
    subject = o.get("subject")
    if verb == "approve":
        subject = subject or pending_subject(prog, o["inv"], "approve")
        if subject == "problem":
            return approve_problem(prog, o["inv"], o["note"], typed_confirm, via)
        return env_approve(prog, o["inv"], o["lock"], typed_confirm, via)
    if verb == "reject":
        pending_subject(prog, o["inv"], "reject")
        if not o["note"]:
            raise CraftError('`/craft-reject` needs --note "why"')
        return env_reject(prog, o["inv"], o["note"], via)
    if verb == "close":
        return close(prog, o["inv"], o["note"], typed_confirm, via)
    if verb == "reopen":
        return REOPEN_RETIRED
    if verb == "resolve":
        if not o["note"]:
            raise CraftError('`/craft-resolve` needs --note "what happened"')
        return untaint(prog, o["inv"], o["note"], o["accept_current"], typed_confirm, via)
    raise CraftError(f"unknown decision '{verb}'")


def run_query(prog: Programme, verb: str, o: dict) -> str:
    """Read-only questions the researcher may ask directly; answered without the model."""
    from .cli_support import RESEARCHER_HELP, decisions_text, explain_text, status_text

    if verb == "status":
        return status_text(prog)
    if verb == "help":
        return RESEARCHER_HELP
    if verb == "decisions":
        return decisions_text(prog, o["inv"])
    if verb == "explain":
        text, _broken = explain_text(prog, o["arg"])
        return text
    raise CraftError(f"unknown query '{verb}'")


def pending_subject(prog: Programme, inv_id: str | None, verb: str) -> str:
    """What is awaiting the researcher right now: 'problem' (framing, or changed) or 'package' (pending proposal)."""
    inv, state = _ctx(prog, inv_id)
    if state.env.pending_proposal:
        return "package"
    if verb == "approve" and (state.phase == Phase.FRAMING or registry.problem_changed(inv, state)):
        return "problem"
    who, cmd, why = registry.next_action(inv, state)
    raise CraftError(
        f"nothing awaits your {verb} in {state.id} (phase {state.phase.value}): {why}. "
        + (f"Waiting on the {who}: `{cmd}`." if who != "nobody" else "")
    )
