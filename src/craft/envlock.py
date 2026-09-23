"""Locked environment: versioned lock file, proposals, human approval (Journey 6.1)."""

from __future__ import annotations

from pathlib import Path

from .paths import InvestigationPaths
from .state import InvestigationState
from .util import CraftError, now_iso, read_yaml, sha256_file, write_yaml


def init_lock(inv: InvestigationPaths, state: InvestigationState, source: Path | None) -> None:
    """Record env.lock v1 from `source` (e.g. uv.lock / requirements.txt) or an empty lock."""
    if inv.env_lock.exists():
        inv.env_lock.chmod(0o644)
    if source is not None:
        if not source.exists():
            raise CraftError(f"{source} does not exist")
        inv.env_lock.write_bytes(source.read_bytes())
    else:
        inv.env_lock.write_text("# CRAFT environment lock (empty)\n", encoding="utf-8")
    inv.env_lock.chmod(0o444)
    state.env.version = 1
    state.env.lock_sha256 = sha256_file(inv.env_lock)
    state.env.history.append({"version": 1, "when": now_iso(), "sha256": state.env.lock_sha256, "note": "initial lock"})


def propose(inv: InvestigationPaths, state: InvestigationState, package: str, reason: str) -> dict:
    if state.env.pending_proposal:
        raise CraftError(
            f"a proposal is already pending ({state.env.pending_proposal['package']}); execution is halted "
            "until the researcher runs `craft approve package` (or `craft reject package`)."
        )
    prop = {"package": package, "reason": reason, "when": now_iso(), "from_version": state.env.version}
    write_yaml(inv.env_proposal, prop)
    inv.env_proposal.chmod(0o444)
    state.env.pending_proposal = prop
    return prop


def approve(inv: InvestigationPaths, state: InvestigationState, new_lock: Path | None) -> int:
    prop = state.env.pending_proposal
    if not prop:
        raise CraftError("no pending environment proposal")
    inv.env_lock.chmod(0o644)
    if new_lock is not None:
        if not new_lock.exists():
            raise CraftError(f"{new_lock} does not exist")
        inv.env_lock.write_bytes(new_lock.read_bytes())
    else:
        with inv.env_lock.open("a", encoding="utf-8") as f:
            f.write(f"{prop['package']}  # added v{state.env.version + 1} {now_iso()}\n")
    inv.env_lock.chmod(0o444)
    state.env.version += 1
    state.env.lock_sha256 = sha256_file(inv.env_lock)
    state.env.history.append({
        "version": state.env.version, "when": now_iso(), "sha256": state.env.lock_sha256,
        "note": f"approved addition of {prop['package']}: {prop['reason']}",
    })
    state.env.pending_proposal = None
    if inv.env_proposal.exists():
        inv.env_proposal.chmod(0o644)
        inv.env_proposal.unlink()
    return state.env.version


def reject(inv: InvestigationPaths, state: InvestigationState, note: str) -> None:
    prop = state.env.pending_proposal
    if not prop:
        raise CraftError("no pending environment proposal")
    state.env.history.append({"version": state.env.version, "when": now_iso(), "note": f"rejected {prop['package']}: {note}"})
    state.env.pending_proposal = None
    if inv.env_proposal.exists():
        inv.env_proposal.chmod(0o644)
        inv.env_proposal.unlink()


def verify_lock(inv: InvestigationPaths, state: InvestigationState) -> str | None:
    if state.env.lock_sha256 is None:
        return None
    if not inv.env_lock.exists():
        return "env.lock is missing"
    if sha256_file(inv.env_lock) != state.env.lock_sha256:
        return "env.lock was modified outside `craft approve package`"
    return None


def pending(state: InvestigationState) -> dict | None:
    return state.env.pending_proposal
