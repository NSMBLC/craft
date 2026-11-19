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


def _labels(sources: list[Path]) -> list[str]:
    """How each lock file is named in the record: its file name, or its path when two share a name."""
    names = [s.name for s in sources]
    return [s.name if names.count(s.name) == 1 else s.as_posix() for s in sources]


def _read_locks(state: InvestigationState, sources: list[Path],
                extra: list[str]) -> tuple[bytes, list[dict], dict[str, list[str]]]:
    """Check the lock files and combine them into one record. One file is recorded as is; several are
    recorded together, each in its own section headed by its name and hash, so a project with more than
    one package manager (uv.lock and Cargo.lock) records its whole environment as one version."""
    if len({s.resolve() for s in sources}) != len(sources):
        raise CraftError("the same lock file is given twice")
    for s in sources:
        check_lock_file(s)
    labels = _labels(sources)
    files = [{"file": label, "sha256": sha256_file(s)} for label, s in zip(labels, sources)]
    if len(sources) == 1:
        body = sources[0].read_bytes()
    else:
        parts = [f"# CRAFT environment lock: {len(sources)} files recorded together\n".encode()]
        for f, s in zip(files, sources):
            raw = s.read_bytes()
            parts.append(f"\n# ===== {f['file']} (sha256 {f['sha256']}) =====\n".encode())
            parts.append(raw if raw.endswith(b"\n") else raw + b"\n")
        body = b"".join(parts)
    texts = {label: _norm(s.read_text(encoding="utf-8")) for label, s in zip(labels, sources)}
    names = approved_packages(state) + [m.group(0) for p in extra if (m := re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", p))]
    held = _held_in(state)
    packages: dict[str, list[str]] = {}
    missing = []
    for name in dict.fromkeys(names):
        found = [label for label, text in texts.items()
                 if re.search(rf"(?<![a-z0-9-]){re.escape(_norm(name))}(?![a-z0-9-])", text)]
        # A package once found in a lock file must stay in that file: the same name in another package
        # manager's lock (Python and Rust both have `regex`) is a different package.
        tied = [label for label in held.get(_norm(name), []) if label in texts]
        if tied:
            if lost := [label for label in tied if label not in found]:
                missing.append(f"{name} (in {', '.join(lost)})")
            packages[name] = tied
        elif found:
            packages[name] = found
        else:
            missing.append(name)
    if missing:
        raise CraftError(
            f"{' + '.join(labels)} does not contain {', '.join(missing)}, which the researcher approved for this "
            "environment. Resolve the lock with the approved packages included (a project with more than one "
            "package manager gives every lock file together, e.g. `craft lock uv.lock Cargo.lock`); dropping one "
            "is an environment change the researcher decides."
        )
    previous = next((h["files"] for h in reversed(state.env.history) if h.get("files")), [])
    dropped = [f["file"] for f in previous if f["file"] not in labels] if len(previous) > 1 else []
    if dropped:
        before = " ".join(f["file"] for f in previous)
        raise CraftError(
            f"the environment is recorded from {' + '.join(f['file'] for f in previous)}; this lock leaves out "
            f"{', '.join(dropped)}. Give every lock file together (`craft lock {before}`); dropping one is an "
            "environment change the researcher decides."
        )
    return body, files, packages


def _held_in(state: InvestigationState) -> dict[str, list[str]]:
    """Which lock file holds each approved package, as the latest recorded lock found it."""
    out: dict[str, list[str]] = {}
    for h in state.env.history:
        for name, labels in (h.get("packages") or {}).items():
            out[_norm(name)] = labels
    return out


def init_lock(inv: InvestigationPaths, state: InvestigationState, sources: list[Path] | None) -> None:
    """Record env.lock from the lock files (uv.lock, or uv.lock and Cargo.lock together), or an empty lock
    for a new investigation. Versions only move forward, every approved package must be in the new lock,
    and every lock file recorded before must be given again."""
    body, files, packages = _read_locks(state, sources, []) if sources else (None, [], {})
    make_writable(inv.env_lock)
    if body is not None:
        inv.env_lock.write_bytes(body)
    else:
        inv.env_lock.write_text("# CRAFT environment lock (empty)\n", encoding="utf-8")
    first = state.env.version == 0
    state.env.version += 1
    state.env.lock_sha256 = sha256_file(inv.env_lock)
    note = "initial lock" if first else "lock recorded"
    entry = {"version": state.env.version, "when": now_iso(), "sha256": state.env.lock_sha256,
             "note": note + (" from " + " + ".join(f["file"] for f in files) if files else "")}
    if files:
        entry["files"] = files
    if packages:
        entry["packages"] = packages
    state.env.history.append(entry)


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


def approve(inv: InvestigationPaths, state: InvestigationState, new_locks: list[Path] | None) -> int:
    prop = state.env.pending_proposal
    if not prop:
        raise CraftError("no pending environment proposal")
    files: list[dict] = []
    packages: dict[str, list[str]] = {}
    if new_locks:
        body, files, packages = _read_locks(state, new_locks, [prop["package"]])
    make_writable(inv.env_lock)
    if new_locks:
        inv.env_lock.write_bytes(body)
    else:
        with inv.env_lock.open("a", encoding="utf-8") as f:
            f.write(f"{prop['package']}  # added v{state.env.version + 1} {now_iso()}\n")
    state.env.version += 1
    state.env.lock_sha256 = sha256_file(inv.env_lock)
    entry = {
        "version": state.env.version, "when": now_iso(), "sha256": state.env.lock_sha256, "package": prop["package"],
        "note": f"approved addition of {prop['package']}: {prop['reason']}",
    }
    if files:
        entry["files"] = files
    if packages:
        entry["packages"] = packages
    state.env.history.append(entry)
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
