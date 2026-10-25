"""The referee: a fresh process that sees only the artifact files.

Backends:
  claude  — `claude -p` with no tools, no settings sources, no session persistence, a
            system prompt from templates, and a JSON schema for the output. It uses the
            researcher's Claude login: API credentials in the environment are removed unless
            `referee.use_api_key: true` is set in craft.yaml.
  command — any shell command; receives the full prompt on stdin, must print JSON.
  fake    — deterministic; reads `CRAFT_FAKE_REFEREE` (path to JSON with keys "1" and "2",
            or "H2:1" for one hypothesis) for tests and demos.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path

from .paths import InvestigationPaths
from .util import CraftError

# Credentials `claude -p` would silently prefer over the researcher's login.
API_KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

DOC_ORDER = ("problem.md", "{hypothesis}", "literature/map.md", "literature/sources.yaml")


def _template(name: str) -> str:
    return resources.files("craft.templates").joinpath(name).read_text(encoding="utf-8")


def build_documents(inv: InvestigationPaths, hid: str) -> str:
    """The referee sees one hypothesis at a time, with the problem and the literature as they are now."""
    parts = []
    for rel in DOC_ORDER:
        rel = rel.format(hypothesis=f"hypotheses/{hid}.md")
        p = inv.root / rel
        if p.exists():
            parts.append(f"===== {rel} =====\n{p.read_text(encoding='utf-8')}\n")
    return "\n".join(parts)


def build_round1_prompt(inv: InvestigationPaths, hid: str) -> tuple[str, str]:
    return _template("referee_round1.md"), (
        f"Review the design of hypothesis {hid} in the following documents. Respond with JSON matching the schema.\n\n"
        + build_documents(inv, hid)
    )


def build_round2_prompt(inv: InvestigationPaths, hid: str, round1: dict, responses: dict[str, dict], diff: str) -> tuple[str, str]:
    blocking = [o for o in round1.get("objections", []) if o.get("severity") == "blocking"]
    lines = [f"Your round-1 blocking objections on hypothesis {hid} and the authors' responses:\n"]
    for o in blocking:
        r = responses.get(o["id"], {})
        lines.append(f"--- {o['id']} [{o['category']}] target {o['target']['document']} § {o['target']['section']}")
        lines.append(f"Objection: {o['statement']}")
        lines.append(f"Adequate answer would show: {o['adequate_answer']}")
        lines.append(f"Response pointer: {r.get('pointer', '(none)')}")
        lines.append(f"Response note: {r.get('note', '(none)')}\n")
    lines.append(f"===== change in hypotheses/{hid}.md since round 1 (unified diff; empty means unchanged) =====")
    lines.append(diff or "(no change)")
    lines.append("\n===== current design documents =====")
    lines.append(build_documents(inv, hid))
    return _template("referee_round2.md"), "\n".join(lines)


def run_referee(config: dict, system_prompt: str, user_prompt: str, schema: dict, round_n: int, hid: str = "") -> dict:
    backend = os.environ.get("CRAFT_REFEREE_BACKEND") or config.get("backend", "claude")
    if backend == "fake":
        return _fake(round_n, hid)
    if backend == "command":
        return _command(config.get("command"), system_prompt, user_prompt, schema)
    if backend == "claude":
        return _claude(config, system_prompt, user_prompt, schema)
    raise CraftError(f"unknown referee backend '{backend}'")


def _fake(round_n: int, hid: str = "") -> dict:
    """Scripted reviews: key "<hid>:<round>" for one hypothesis, falling back to "<round>"."""
    path = os.environ.get("CRAFT_FAKE_REFEREE")
    if not path:
        raise CraftError("fake referee backend needs CRAFT_FAKE_REFEREE=<path to json with keys '1','2'>")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in (f"{hid}:{round_n}", str(round_n)):
        if key in data:
            return data[key]
    raise CraftError(f"fake referee script has no entry for round {round_n}")


def _command(cmd: str | None, system_prompt: str, user_prompt: str, schema: dict) -> dict:
    if not cmd:
        raise CraftError("referee.backend is 'command' but referee.command is not set in craft.yaml")
    payload = f"SYSTEM:\n{system_prompt}\n\nSCHEMA:\n{json.dumps(schema)}\n\nUSER:\n{user_prompt}\n"
    proc = subprocess.run(cmd, shell=True, input=payload, capture_output=True, text=True, env=_clean_env())
    if proc.returncode != 0:
        raise CraftError(f"referee command failed ({proc.returncode}): {proc.stderr.strip()[:500]}")
    return _parse_json(proc.stdout)


def _claude(config: dict, system_prompt: str, user_prompt: str, schema: dict) -> dict:
    exe = shutil.which("claude")
    if not exe:
        raise CraftError("`claude` CLI not found on PATH; install Claude Code or set referee.backend to 'command'")
    model = config.get("model") or "opus"
    args = [
        exe, "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--tools", "",
        "--setting-sources", "",
        "--no-session-persistence",
        "--system-prompt", system_prompt,
        "--model", str(model),
    ]
    if config.get("effort"):
        args += ["--effort", str(config["effort"])]
    strip = not config.get("use_api_key", False)
    # Run from an empty temp dir so no CLAUDE.md or project settings can be discovered.
    with tempfile.TemporaryDirectory(prefix="craft-referee-") as tmp:
        try:
            proc = subprocess.run(
                args, input=user_prompt, capture_output=True, text=True, cwd=tmp,
                env=_clean_env(strip_api_keys=strip), timeout=int(config.get("timeout_s", 900)),
            )
        except subprocess.TimeoutExpired as e:
            raise CraftError("referee timed out") from e
    if proc.returncode != 0:
        hint = ""
        if strip and any(os.environ.get(k) for k in API_KEY_VARS):
            hint = (" (the referee ignored the API key in your environment and used your Claude login; "
                    "log in with `claude`, or set referee.use_api_key: true in craft.yaml to use the key)")
        raise CraftError(f"referee process failed ({proc.returncode}): {proc.stderr.strip()[:800]}{hint}")
    return _parse_claude_output(proc.stdout)


def _clean_env(strip_api_keys: bool = False) -> dict:
    env = dict(os.environ)
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_PROJECT_DIR"):
        env.pop(k, None)
    if strip_api_keys:
        for k in API_KEY_VARS:
            env.pop(k, None)
    return env


def credential_note(config: dict, backend: str) -> str | None:
    """A warning when the claude backend will bill an API key; silent when it uses the Claude login."""
    if backend != "claude" or not config.get("use_api_key", False):
        return None
    present = [k for k in API_KEY_VARS if os.environ.get(k)]
    if not present:
        return None
    return f"referee credential: {', '.join(present)} (referee.use_api_key is true; usage is billed to that key)"


def _parse_claude_output(stdout: str) -> dict:
    data = _parse_json(stdout)
    if isinstance(data, dict):
        if isinstance(data.get("structured_output"), dict):
            return data["structured_output"]
        if "result" in data:
            res = data["result"]
            if isinstance(res, dict):
                return res
            if isinstance(res, str):
                return _parse_json(res)
        if "objections" in data or "judgements" in data:
            return data
    raise CraftError(f"could not find structured referee output in: {stdout[:300]}")


def _parse_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise CraftError(f"referee did not return JSON: {text[:300]}")
