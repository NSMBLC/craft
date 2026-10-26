"""Input data that criteria depend on: recorded by hash, checked like every other record.

`craft data add <path> --id <data_id>` records a file or a directory (every file in it). Verdicts whose
evidence names a recorded data_id re-hash it and record the hash; `craft verify` re-hashes everything,
and the hooks' quick check compares sizes and modification times, re-hashing only what moved.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .paths import Programme
from .state import InvestigationState
from .util import CraftError, now_iso, sha256_file


def _files(p: Path) -> list[Path]:
    if p.is_file():
        return [p]
    return sorted(f for f in p.rglob("*") if f.is_file() and not any(part.startswith(".") for part in f.relative_to(p).parts))


def snapshot(prog: Programme, path: Path) -> dict:
    p = path if path.is_absolute() else prog.root / path
    rel = prog.relpath(p)
    if rel is None or not p.exists():
        raise CraftError(f"{path}: not a file or directory inside the programme")
    files = {}
    for f in _files(p):
        st = f.stat()
        key = "." if f == p else f.relative_to(p).as_posix()
        files[key] = {"sha256": sha256_file(f), "size": st.st_size, "mtime_ns": st.st_mtime_ns}
    if not files:
        raise CraftError(f"{path}: no files to record")
    return {"path": rel.as_posix(), "kind": "file" if p.is_file() else "dir", "files": files, "sha256": combined(files)}


def shown_hash(rec: dict) -> str:
    """The hash to show a reader, said plainly: a file's own sha256, or a directory's manifest hash.

    (`sha256` in the record is always the manifest hash over path + file hash, which differs from
    a file's own sha256; that is what other tools and reports record, so it is the one shown.)"""
    if rec.get("kind") == "file":
        return f"sha256 {rec['files']['.']['sha256']}"
    return f"manifest sha256 {rec['sha256'][:12]} over {len(rec['files'])} files (each file's own hash: `craft data list`)"


def combined(files: dict) -> str:
    h = hashlib.sha256()
    for k in sorted(files):
        h.update(f"{k}\0{files[k]['sha256']}\n".encode())
    return h.hexdigest()


def add(prog: Programme, state: InvestigationState, path: Path, data_id: str, note: str,
        derivation: str = "") -> tuple[dict, bool]:
    """Record `path` as `data_id`. Returns (record, newly_added). A changed snapshot needs a new id.

    `derivation` says how the data were built (sources, transformations, choices that could have gone
    the other way); the referee sees it. It can be added later to a record that has none, never changed.
    """
    snap = snapshot(prog, path)
    old = state.data.get(data_id)
    if old:
        if old["sha256"] == snap["sha256"] and old["path"] == snap["path"]:
            if derivation and derivation != old.get("derivation"):
                if old.get("derivation"):
                    raise CraftError(f"data '{data_id}' already has a recorded derivation; it is part of the record "
                                     "and is not rewritten. Record a limitation on the affected verdicts instead.")
                old["derivation"] = derivation
                old["derivation_when"] = now_iso()
                return old, True
            return old, False
        raise CraftError(
            f"data id '{data_id}' is already recorded for {old['path']} (sha256 {old['sha256'][:12]}) and this differs. "
            "Recorded inputs never change under the same id: record the new snapshot under a new id, and name that id "
            "in new evidence."
        )
    rec = {**snap, "when": now_iso(), "note": note, **({"derivation": derivation} if derivation else {})}
    state.data[data_id] = rec
    return rec, True


def check(prog: Programme, data_id: str, rec: dict, full: bool) -> str | None:
    """Problem with recorded data, or None. Quick mode re-hashes only files whose size or mtime moved."""
    p = prog.root / rec["path"]
    if not p.exists():
        return f"recorded input data '{data_id}' ({rec['path']}) is missing"
    now = {("." if f == p else f.relative_to(p).as_posix()): f for f in _files(p)}
    if set(now) != set(rec["files"]):
        return f"recorded input data '{data_id}' ({rec['path']}) changed: files were added or removed"
    for key, f in now.items():
        old = rec["files"][key]
        st = f.stat()
        if not full and st.st_size == old["size"] and st.st_mtime_ns == old["mtime_ns"]:
            continue
        if sha256_file(f) != old["sha256"]:
            where = rec["path"] if key == "." else f"{rec['path']}/{key}"
            return f"recorded input data '{data_id}' changed since it was recorded ({where})"
    return None


def covering(prog: Programme, rel: str) -> tuple[str, str] | None:
    """(investigation id, data id) of recorded data containing programme-relative path `rel`."""
    for inv_id in prog.list_investigations():
        try:
            st = InvestigationState.load(prog.investigation_dir(inv_id))
        except CraftError:
            continue
        for did, rec in st.data.items():
            base = rec["path"]
            if rel == base or rel.startswith(base.rstrip("/") + "/"):
                return inv_id, did
    return None
