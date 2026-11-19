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


_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"


def _bare(spec: str) -> str | None:
    """The package name in a spec such as `numpy==2.1`."""
    m = re.match(_NAME, spec)
    return m.group(0) if m else None


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"(?<![a-z0-9-]){re.escape(_norm(name))}(?![a-z0-9-])", text) is not None


def approved_packages(state: InvestigationState) -> list[str]:
    """Package names the researcher approved and has not since approved removing, from the environment history."""
    out: dict[str, str] = {}
    for h in state.env.history:
        if h.get("action") in ("remove", "remove-file"):
            for name in h.get("released", []):
                out.pop(_norm(name), None)
            continue
        pkg = h.get("package")
        if not pkg:
            m = re.match(r"approved addition of (\S+?):", h.get("note", ""))
            pkg = m.group(1) if m else None
        if pkg and (name := _bare(pkg)):
            out.setdefault(_norm(name), name)
    return list(out.values())


def recorded_files(state: InvestigationState) -> list[str]:
    """The lock files the current environment is recorded from (empty when it was never recorded from files)."""
    return [f["file"] for f in next((h["files"] for h in reversed(state.env.history) if h.get("files")), [])]


def _held_in(state: InvestigationState) -> dict[str, list[str]]:
    """Which lock file holds each approved package, as the latest recorded lock found it."""
    out: dict[str, list[str]] = {}
    for h in state.env.history:
        for name in h.get("released", []):
            out.pop(_norm(name), None)
        for name, labels in (h.get("packages") or {}).items():
            out[_norm(name)] = labels
    return out


def _labels(sources: list[Path]) -> list[str]:
    """How each lock file is named in the record: its file name, or its path when two share a name."""
    names = [s.name for s in sources]
    return [s.name if names.count(s.name) == 1 else s.as_posix() for s in sources]


DECIDE = "dropping one is an environment change the researcher decides: `craft propose remove <package or lock file> --reason ...`."


def _read_locks(state: InvestigationState, sources: list[Path], add: str | None = None,
                remove: str | None = None) -> tuple[bytes, list[dict], dict[str, list[str]]]:
    """Check the lock files and combine them into one record. One file is recorded as is; several are
    recorded together, each in its own section headed by its name and hash, so a project with more than
    one package manager (uv.lock and Cargo.lock) records its whole environment as one version.
    `add` is a package being approved; `remove` a package or recorded lock file whose removal is."""
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
    previous = recorded_files(state)
    drop_file = remove if remove in previous else None
    if drop_file and drop_file in labels:
        raise CraftError(f"the approved change removes {drop_file} from the environment; give the other lock files without it")
    remaining: list[str] = []
    if remove and not drop_file:
        # Only the lock files that held the package count: the same name in another package manager's lock
        # (Python and Rust both have `regex`) is a different package. It must leave at least one of them;
        # where it stays, it stays approved.
        held_files = [label for label in _held_in(state).get(_norm(remove), []) if label in texts]
        still = [label for label in held_files or texts if _mentions(texts[label], remove)]
        if not held_files and still or held_files and len(still) == len(held_files):
            raise CraftError(f"{', '.join(still)} still contains {remove}, whose removal is being approved; "
                             "resolve the lock without it")
        remaining = still
    kept = [f for f in previous if f != drop_file]
    dropped = [f for f in kept if f not in labels] if len(previous) > 1 else []
    if dropped:
        raise CraftError(
            f"the environment is recorded from {' + '.join(kept)}; this lock leaves out {', '.join(dropped)}. "
            f"Give every lock file together (`craft lock {' '.join(kept)}`); {DECIDE}"
        )
    held = _held_in(state)
    names = [n for n in approved_packages(state) if not (remove and _norm(n) == _norm(remove))]
    if add and (name := _bare(add)):
        names.append(name)
    packages: dict[str, list[str]] = {}
    missing = []
    for name in dict.fromkeys(names):
        found = [label for label, text in texts.items() if _mentions(text, name)]
        # A package once found in a lock file must stay in that file: the same name in another package
        # manager's lock (Python and Rust both have `regex`) is a different package.
        was_in = [label for label in held.get(_norm(name), []) if label != drop_file]
        if drop_file and drop_file in held.get(_norm(name), []) and not was_in:
            continue  # held only in the lock file being removed: released with it
        tied = [label for label in was_in if label in texts]
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
            f"package manager gives every lock file together, e.g. `craft lock uv.lock Cargo.lock`); {DECIDE}"
        )
    if remaining:
        packages[remove] = remaining
    return body, files, packages


def init_lock(inv: InvestigationPaths, state: InvestigationState, sources: list[Path] | None) -> None:
    """Record env.lock from the lock files (uv.lock, or uv.lock and Cargo.lock together), or an empty lock
    for a new investigation. Versions only move forward, every approved package must be in the new lock,
    and every lock file recorded before must be given again."""
    body, files, packages = _read_locks(state, sources) if sources else (None, [], {})
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


def describe(prop: dict) -> str:
    """A pending proposal in a few words: "adding 'scipy'", "removing 'regex'", "removing the lock file 'Cargo.lock'"."""
    if prop.get("action") == "remove-file":
        return f"removing the lock file '{prop['package']}'"
    return f"{'removing' if prop.get('action') == 'remove' else 'adding'} '{prop['package']}'"


def propose(inv: InvestigationPaths, state: InvestigationState, package: str, reason: str,
            action: str = "add") -> dict:
    if state.env.pending_proposal:
        raise CraftError(
            f"a proposal is already pending ({describe(state.env.pending_proposal)}); execution is halted "
            "until the researcher types `/craft-approve` (or `/craft-reject --note ...`)."
        )
    if action == "remove":
        if package in recorded_files(state):
            action = "remove-file"
        elif not (name := _bare(package)) or not (
                _norm(name) in {_norm(n) for n in approved_packages(state)}
                or (inv.env_lock.exists() and _mentions(_norm(inv.env_lock.read_text(encoding="utf-8")), name))):
            raise CraftError(f"'{package}' is neither an approved package, a package in env.lock, nor a recorded lock "
                             f"file ({', '.join(recorded_files(state)) or 'none'}); there is nothing to remove")
        else:
            package = name
    prop = {"package": package, "action": action, "reason": reason, "when": now_iso(),
            "from_version": state.env.version}
    make_writable(inv.env_proposal)
    write_yaml(inv.env_proposal, prop)
    state.env.pending_proposal = prop
    return prop


def _strip_added(text: str, name: str) -> str:
    """env.lock without the lines CRAFT appended for `name` when it was approved without a lock file."""
    return "".join(line for line in text.splitlines(keepends=True)
                   if not (re.match(rf"{_NAME}", line) and _norm(_bare(line) or "") == _norm(name)
                           and re.search(r"  # added v\d+ ", line)))


def approve(inv: InvestigationPaths, state: InvestigationState, new_locks: list[Path] | None) -> int:
    prop = state.env.pending_proposal
    if not prop:
        raise CraftError("no pending environment proposal")
    action = prop.get("action", "add")
    what = prop["package"]
    files: list[dict] = []
    packages: dict[str, list[str]] = {}
    released: list[str] = []
    if action == "remove-file":
        if not new_locks:
            raise CraftError(f"approving the removal of {what} records the remaining lock files: "
                             f"`/craft-approve --lock <file>` for each of "
                             f"{', '.join(f for f in recorded_files(state) if f != what) or 'the remaining files'}")
        before = _held_in(state)
        body, files, packages = _read_locks(state, new_locks, remove=what)
        released = [n for n in approved_packages(state) if what in before.get(_norm(n), []) and n not in packages]
    elif action == "remove":
        if new_locks:
            body, files, packages = _read_locks(state, new_locks, remove=what)
        else:
            text = inv.env_lock.read_text(encoding="utf-8") if inv.env_lock.exists() else ""
            body = _strip_added(text, what).encode()
            if _mentions(_norm(body.decode()), what):
                raise CraftError(f"env.lock still holds {what} from a recorded lock file; approve with the lock "
                                 f"files resolved without it: `/craft-approve --lock <file>`")
            body_unchanged = body.decode() == text
            if body_unchanged:
                raise CraftError(f"env.lock does not hold {what}; nothing to remove")
        released = [n for n in approved_packages(state) if _norm(n) == _norm(what) and what not in packages]
    elif new_locks:
        body, files, packages = _read_locks(state, new_locks, add=what)
    else:
        body = None
    make_writable(inv.env_lock)
    if body is not None:
        inv.env_lock.write_bytes(body)
    else:
        with inv.env_lock.open("a", encoding="utf-8") as f:
            f.write(f"{what}  # added v{state.env.version + 1} {now_iso()}\n")
    state.env.version += 1
    state.env.lock_sha256 = sha256_file(inv.env_lock)
    verb = {"add": "addition", "remove": "removal", "remove-file": "removal of the lock file"}[action]
    entry = {
        "version": state.env.version, "when": now_iso(), "sha256": state.env.lock_sha256, "package": what,
        "note": f"approved {verb} {'of ' if action != 'remove-file' else ''}{what}"
                + (f" (a package of that name stays in {', '.join(packages[what])})" if action == "remove" and what in packages else "")
                + f": {prop['reason']}",
    }
    if action != "add":
        entry["action"] = action
        entry["released"] = released
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
    state.env.history.append({"version": state.env.version, "when": now_iso(), "note": f"rejected {describe(prop)}: {note}"})
    state.env.pending_proposal = None
    if inv.env_proposal.exists():
        inv.env_proposal.unlink()


def verify_lock(inv: InvestigationPaths, state: InvestigationState) -> str | None:
    if state.env.lock_sha256 is None:
        return None
    if not inv.env_lock.exists():
        return "env.lock is missing"
    if sha256_file(inv.env_lock) != state.env.lock_sha256:
        return "env.lock was modified outside `craft` (changes go through `craft propose package|remove` + `/craft-approve`)"
    return None


def pending(state: InvestigationState) -> dict | None:
    return state.env.pending_proposal
