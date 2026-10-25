"""Locked environment: versioned lock file, proposals, human approval (Journey 6.1)."""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path

from .integrity import make_writable
from .paths import InvestigationPaths
from .state import InvestigationState
from .util import CraftError, now_iso, read_yaml, sha256_file, write_yaml


# What an environment record can be: a resolved lock or requirements file, never data or code.
LOCK_PATTERNS = ("*.lock", "requirements*.txt", "*requirements.txt", "constraints*.txt", "environment.yml",
                 "environment.yaml", "conda-lock.yml", "conda-lock.yaml", "pylock.toml", "pylock.*.toml")


def check_lock_file(source: Path) -> None:
    """Refuse anything that is not an environment description (a data file, a binary)."""
    if not source.exists():
        raise CraftError(f"{source} does not exist")
    if not source.is_file() or not any(fnmatch(source.name, p) for p in LOCK_PATTERNS):
        raise CraftError(
            f"{source.name} is not an environment lock file ({', '.join(LOCK_PATTERNS)}). The environment record "
            "only ever describes an environment; input data is recorded with `craft data add <path> --id <data_id>`."
        )
    raw = source.read_bytes()
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        raise CraftError(f"{source.name} is not a text lock file") from None
    if b"\0" in raw:
        raise CraftError(f"{source.name} is not a text lock file")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.lower())


def approved_packages(state: InvestigationState) -> list[str]:
    """Package names the researcher approved, from the environment history."""
    out = []
    for h in state.env.history:
        pkg = h.get("package")
        if not pkg:
            m = re.match(r"approved addition of (\S+?):", h.get("note", ""))
            pkg = m.group(1) if m else None
        if pkg:
            m = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", pkg)
            if m:
                out.append(m.group(0))
    return out


def _require_approved(state: InvestigationState, source: Path, extra: list[str]) -> None:
    check_lock_file(source)
    text = _norm(source.read_text(encoding="utf-8"))
    names = approved_packages(state) + [m.group(0) for p in extra if (m := re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", p))]
    missing = [p for p in dict.fromkeys(names)
               if not re.search(rf"(?<![a-z0-9-]){re.escape(_norm(p))}(?![a-z0-9-])", text)]
    if missing:
        raise CraftError(
            f"{source.name} does not contain {', '.join(missing)}, which the researcher approved for this environment. "
            "Resolve the lock with the approved packages included; dropping one is an environment change the "
            "researcher decides."
        )


def init_lock(inv: InvestigationPaths, state: InvestigationState, source: Path | None) -> None:
    """Record env.lock from `source` (e.g. uv.lock / requirements.txt), or an empty lock for a new
    investigation. Versions only move forward, and every approved package must be in the new lock."""
    if source is not None:
        _require_approved(state, source, [])
    make_writable(inv.env_lock)
    if source is not None:
        inv.env_lock.write_bytes(source.read_bytes())
    else:
        inv.env_lock.write_text("# CRAFT environment lock (empty)\n", encoding="utf-8")
    first = state.env.version == 0
    state.env.version += 1
    state.env.lock_sha256 = sha256_file(inv.env_lock)
    note = "initial lock" if first else "lock recorded"
    state.env.history.append({"version": state.env.version, "when": now_iso(), "sha256": state.env.lock_sha256,
                              "note": note + (f" from {source.name}" if source is not None else "")})


def propose(inv: InvestigationPaths, state: InvestigationState, package: str, reason: str) -> dict:
    if state.env.pending_proposal:
        raise CraftError(
            f"a proposal is already pending ({state.env.pending_proposal['package']}); execution is halted "
            "until the researcher types `/craft-approve` (or `/craft-reject --note ...`)."
        )
    prop = {"package": package, "reason": reason, "when": now_iso(), "from_version": state.env.version}
    make_writable(inv.env_proposal)
    write_yaml(inv.env_proposal, prop)
    state.env.pending_proposal = prop
    return prop


def approve(inv: InvestigationPaths, state: InvestigationState, new_lock: Path | None) -> int:
    prop = state.env.pending_proposal
    if not prop:
        raise CraftError("no pending environment proposal")
    make_writable(inv.env_lock)
    if new_lock is not None:
        _require_approved(state, new_lock, [prop["package"]])
        inv.env_lock.write_bytes(new_lock.read_bytes())
    else:
        with inv.env_lock.open("a", encoding="utf-8") as f:
            f.write(f"{prop['package']}  # added v{state.env.version + 1} {now_iso()}\n")
    state.env.version += 1
    state.env.lock_sha256 = sha256_file(inv.env_lock)
    state.env.history.append({
        "version": state.env.version, "when": now_iso(), "sha256": state.env.lock_sha256, "package": prop["package"],
        "note": f"approved addition of {prop['package']}: {prop['reason']}",
    })
    state.env.pending_proposal = None
    if inv.env_proposal.exists():
        inv.env_proposal.unlink()
    return state.env.version


def reject(inv: InvestigationPaths, state: InvestigationState, note: str) -> None:
    prop = state.env.pending_proposal
    if not prop:
        raise CraftError("no pending environment proposal")
    state.env.history.append({"version": state.env.version, "when": now_iso(), "note": f"rejected {prop['package']}: {note}"})
    state.env.pending_proposal = None
    if inv.env_proposal.exists():
        inv.env_proposal.unlink()


def verify_lock(inv: InvestigationPaths, state: InvestigationState) -> str | None:
    if state.env.lock_sha256 is None:
        return None
    if not inv.env_lock.exists():
        return "env.lock is missing"
    if sha256_file(inv.env_lock) != state.env.lock_sha256:
        return "env.lock was modified outside `craft` (changes go through `craft propose package` + `/craft-approve`)"
    return None


def pending(state: InvestigationState) -> dict | None:
    return state.env.pending_proposal
