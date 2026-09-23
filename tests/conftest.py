from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from craft.cli import app
from craft.util import CraftError

ALL_CHECKPOINTS = [
    "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7",
    "2.1", "2.2", "2.3", "2.4",
    "3.1", "3.2",
    "4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7",
    "5.1", "5.2", "5.3", "5.4", "5.5", "5.6",
    "6.1", "6.2", "6.3", "6.4", "6.5",
    "7.1", "7.2", "7.3", "7.4",
]


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def text(self) -> str:
        return self.out + "\n" + self.err


class Craft:
    """Invoke the CLI in-process. `human=True` simulates the researcher's terminal."""

    def __init__(self, root: Path):
        self.root = root
        self.runner = CliRunner()

    def __call__(self, *args: str, input: str | None = None, human: bool = False, env: dict | None = None) -> Result:
        saved = dict(os.environ)
        cwd = os.getcwd()
        try:
            os.chdir(self.root)
            os.environ["CRAFT_PROGRAMME"] = str(self.root)
            if human:
                for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
                    os.environ.pop(k, None)
                os.environ["CRAFT_ALLOW_NON_TTY"] = "1"
            else:
                os.environ.pop("CRAFT_ALLOW_NON_TTY", None)
                os.environ["CLAUDECODE"] = "1"  # tests run "as the agent" by default
            for k, v in (env or {}).items():
                os.environ[k] = v
            res = self.runner.invoke(app, list(args), input=input, catch_exceptions=True)
        finally:
            os.chdir(cwd)
            os.environ.clear()
            os.environ.update(saved)
        if isinstance(res.exception, CraftError):
            return Result(res.exception.exit_code, res.stdout, f"craft: {res.exception}")
        if res.exception is not None and not isinstance(res.exception, SystemExit):
            raise res.exception
        return Result(res.exit_code, res.stdout, getattr(res, "stderr", "") or "")

    def hook(self, tool: str, **tool_input) -> Result:
        payload = {"session_id": "t", "cwd": str(self.root), "hook_event_name": "PreToolUse",
                   "tool_name": tool, "tool_input": tool_input}
        return self("hook", "pre-tool-use", input=json.dumps(payload))

    def hook_event(self, event: str, **payload) -> Result:
        payload.setdefault("cwd", str(self.root))
        return self("hook", event, input=json.dumps(payload))

    def write(self, rel: str, text: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p


@pytest.fixture
def programme(tmp_path: Path) -> Craft:
    root = tmp_path / "prog"
    root.mkdir()
    c = Craft(root)
    r = c("init", "--path", str(root))
    assert r.code == 0, r.text
    return c


def pytest_collection_modifyitems(config, items):
    covered: set[str] = set()
    for item in items:
        for m in item.iter_markers("checkpoint"):
            covered.update(str(x) for x in m.args)
    missing = [c for c in ALL_CHECKPOINTS if c not in covered]
    lines = ["# Checkpoint coverage", "", "| checkpoint | tests |", "|---|---|"]
    for cp in ALL_CHECKPOINTS:
        tests = sorted(item.nodeid.split("::")[-1] for item in items if any(cp in [str(x) for x in m.args] for m in item.iter_markers("checkpoint")))
        lines.append(f"| {cp} | {', '.join(tests) or '**MISSING**'} |")
    Path(__file__).parent.joinpath("acceptance", "checkpoints.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    config._craft_missing = missing
