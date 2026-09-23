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
