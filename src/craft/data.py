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


def combined(files: dict) -> str:
    h = hashlib.sha256()
    for k in sorted(files):
        h.update(f"{k}\0{files[k]['sha256']}\n".encode())
    return h.hexdigest()


def add(prog: Programme, state: InvestigationState, path: Path, data_id: str, note: str) -> tuple[dict, bool]:
    """Record `path` as `data_id`. Returns (record, newly_added). A changed snapshot needs a new id."""
    snap = snapshot(prog, path)
    old = state.data.get(data_id)
    if old:
        if old["sha256"] == snap["sha256"] and old["path"] == snap["path"]:
            return old, False
        raise CraftError(
            f"data id '{data_id}' is already recorded for {old['path']} (sha256 {old['sha256'][:12]}) and this differs. "
            "Recorded inputs never change under the same id: record the new snapshot under a new id, and name that id "
            "in new evidence."
        )
    rec = {**snap, "when": now_iso(), "note": note}
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
