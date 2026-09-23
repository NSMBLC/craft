"""`craft hook <event>`: the adapter between Claude Code hook events and the gate.

Deny = JSON permissionDecision on stdout AND exit code 2 (either alone blocks the call).
Context injection (UserPromptSubmit / SessionStart) = plain text on stdout, exit 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .gate import Decision, decide_bash, decide_write
from .paths import Programme, find_programme_root
from .util import CraftError

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def _read_stdin() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _programme(payload: dict) -> Programme | None:
    cwd = payload.get("cwd")
    try:
        return Programme(find_programme_root(Path(cwd) if cwd else None))
    except CraftError:
        return None


def pre_tool_use() -> int:
    payload = _read_stdin()
    prog = _programme(payload)
    if prog is None:
        return 0
    tool = payload.get("tool_name", "")
    tin = payload.get("tool_input", {}) or {}
    cwd = Path(payload.get("cwd") or Path.cwd())
    decision = Decision.ok()
    if tool in WRITE_TOOLS:
        target = tin.get("file_path") or tin.get("notebook_path")
        if target:
            p = Path(target)
            decision = decide_write(prog, p if p.is_absolute() else cwd / p)
    elif tool == "Bash":
        cmd = tin.get("command", "")
        if cmd:
            decision = decide_bash(prog, cmd, cwd)
    if decision.allow:
        return 0
    reason = "CRAFT refused: " + decision.reason
    if decision.checkpoint:
        reason += f" [checkpoint {decision.checkpoint}]"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    print(reason, file=sys.stderr)
    return 2


def user_prompt_submit() -> int:
    payload = _read_stdin()
    prog = _programme(payload)
    if prog is None:
        return 0
    prompt = payload.get("prompt") or payload.get("user_prompt") or ""
    typed = _typed_decision(prog, payload, prompt)
    if typed is not None:
        print(typed)
        return 0
    if len(prompt) < 12:
        return 0
    from . import memory as mem

    hits = mem.recall(prog, prompt)
    if not hits:
        return 0
    lines = ["<craft-memory>", "Programme memory relevant to this prompt (surface it to the researcher before drafting anything):"]
    for h in hits[:5]:
        lines.append(f"- {h.cite()} — see {h.pointer}")
    refuted = [h for h in hits if h.kind == "refuted"]
    if refuted:
        lines.append(
            "A prior investigation REFUTED a related claim. Cite it and ask what has changed that justifies "
            "revisiting; `craft new` will require --acknowledge <id> --justification."
        )
    lines.append("</craft-memory>")
    print("\n".join(lines))
    return 0


def _typed_decision(prog: Programme, payload: dict, prompt: str) -> str | None:
    """A researcher decision typed verbatim as a message is executed here, by the hook.

    The hook runs only on text the researcher typed (the model cannot type into the prompt, and
    the Bash screen denies the agent invoking `craft hook`). Typing the command is the confirmation.
    """
    from . import decisions

    parsed = decisions.parse_typed(prompt)
    if parsed is None:
        return None
    if payload.get("hook_event_name") not in (None, "UserPromptSubmit"):
        return None
    verb, opts = parsed
    head = [f"<craft-decision>", f"The researcher typed the decision `{verb}` ({prompt.strip()}). CRAFT executed it directly "
            "(this is the researcher's channel). Do NOT run the command yourself. Report the outcome below."]
    try:
        result = decisions.run_typed(prog, verb, opts)
        body = result
        tail = NEXT_STEP.get(verb, "")
    except CraftError as e:
        body = f"REFUSED: {e}"
        tail = "Explain the refusal and what must change; do not retry the decision yourself."
    return "\n".join(head + [body, tail, "</craft-decision>"])


# What the agent does after each decision. Pre-freeze phases are collaborative: propose, then wait.
# Execution (after env approve) runs itself. Closure ends the investigation.
NEXT_STEP = {
    "approve problem": ("Then propose the literature scope in a few lines (which venues/years/keywords, what is "
                        "out of scope) and WAIT for the researcher's go-ahead before searching or drafting anything."),
    "env approve": "Then resume execution where it halted, without asking.",
    "env reject": "Then continue execution with the current environment, or report what cannot be done without the change.",
    "close": "Then summarise what went to findings, refuted and open questions. Do not start a new investigation unprompted.",
    "reopen problem": "Then ask what the researcher wants changed in problem.md; do not edit it on your own.",
    "reopen review": "Then request the new review round only when the researcher says the design is ready.",
    "untaint": "Then report the current phase and wait.",
}


def session_start() -> int:
    payload = _read_stdin()
    prog = _programme(payload)
    if prog is None:
        return 0
    from .cli_support import status_text, verify_all

    problems = verify_all(prog)
    lines = ["<craft-status>", f"CRAFT programme at {prog.root}"]
    lines.append(status_text(prog))
    if problems:
        lines.append("INTEGRITY PROBLEMS (report to the researcher before anything else):")
        lines += [f"- {p}" for p in problems]
    lines.append("Use `craft status`, `craft recall`, `craft validate`. Researcher-only: approve/close/reopen/untaint.")
    lines.append("</craft-status>")
    print("\n".join(lines))
    return 0


def stop() -> int:
    payload = _read_stdin()
    prog = _programme(payload)
    if prog is None:
        return 0
    if payload.get("stop_hook_active"):
        return 0
    from .cli_support import verify_all

    problems = verify_all(prog)
    if not problems:
        return 0
    print(json.dumps({
        "decision": "block",
        "reason": "CRAFT integrity check failed; tell the researcher exactly what follows and do not continue "
                  "any investigation work: " + "; ".join(problems),
    }))
    return 0


EVENTS = {
    "pre-tool-use": pre_tool_use,
    "user-prompt-submit": user_prompt_submit,
    "session-start": session_start,
    "stop": stop,
}
