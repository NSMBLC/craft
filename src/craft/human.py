"""Guard for researcher-only commands.

Three independent layers keep approvals human:
  1. The Claude Code Bash hook denies the agent invoking these subcommands (gate.HUMAN_ONLY_RE).
  2. This module refuses when the process runs inside an agent's tool call (Claude Code env vars).
  3. It requires an interactive terminal and a typed confirmation.
`CRAFT_ALLOW_NON_TTY=1` bypasses layer 3 for the test-suite; the hook denies that token too.
"""

from __future__ import annotations

import os
import sys

from .util import CraftError

AGENT_ENV_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def require_human(action: str) -> None:
    for var in AGENT_ENV_MARKERS:
        if os.environ.get(var):
            raise CraftError(
                f"`craft {action}` is a researcher decision and this process is running inside an "
                f"agent tool call ({var} is set). The researcher runs it: `! craft {action}` in the "
                "prompt, or in a second terminal."
            )
    if os.environ.get("CRAFT_ALLOW_NON_TTY") == "1":
        return
    if not sys.stdin.isatty():
        raise CraftError(
            f"`craft {action}` needs an interactive terminal so the decision is provably the "
            "researcher's. Run it in a terminal (not through an agent)."
        )


def confirm(prompt: str) -> bool:
    if os.environ.get("CRAFT_ALLOW_NON_TTY") == "1":
        return os.environ.get("CRAFT_CONFIRM", "y").lower().startswith("y")
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")
