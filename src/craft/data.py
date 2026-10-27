"""Input data that criteria depend on: recorded by hash, checked like every other record.

`craft data add <path> --id <data_id>` records a file or a directory (every file in it). Verdicts whose
evidence names a recorded data_id re-hash it and record the hash; `craft verify` re-hashes everything,
and the hooks' quick check compares sizes and modification times, re-hashing only what moved.

Two inputs have no file of their own to hash beforehand. Generated inputs (`--generated --seeds 1-50`)
are recorded by what determines them: the generator code (hashed and held like any recorded input), the
seeds and the environment; evidence may use only the recorded seeds. Inputs the runner fetches just
before use (`--fetched`) are recorded by the run itself, right after fetching; evidence produced before
that record cannot cite them, so nothing used them unrecorded.
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
        derivation: str = "", source: str = "", seeds: list[str] | None = None, command: str = "") -> tuple[dict, bool]:
    """Record `path` as `data_id`. Returns (record, newly_added). A changed snapshot needs a new id.

    `derivation` says how the data were built (sources, transformations, choices that could have gone
    the other way); the referee sees it. It can be added later to a record that has none, never changed.
    """
    snap = snapshot(prog, path)
    how = {"source": source} if source else {}
    if source == "generated":
        if not seeds:
            raise CraftError("generated data is recorded with the seeds it is generated from (`--seeds 1-50`)")
        how.update(seeds=[str(x) for x in seeds], env_version=state.env.version, env_lock_sha256=state.env.lock_sha256,
                   **({"command": command} if command else {}))
    old = state.data.get(data_id)
    if old:
        same = all(old.get(k) == v for k, v in how.items() if k not in ("env_version", "env_lock_sha256"))
        if old["sha256"] == snap["sha256"] and old["path"] == snap["path"] and same and bool(old.get("source")) == bool(source):
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
    rec = {**snap, **how, "when": now_iso(), "note": note, **({"derivation": derivation} if derivation else {})}
    state.data[data_id] = rec
    return rec, True


def described(rec: dict) -> str:
    """How a record was made, for listings and verdicts: '' for a plain snapshot."""
    if rec.get("source") == "generated":
        return (f"generated by {rec['path']} from seeds {seed_text(rec['seeds'])} under env v{rec.get('env_version')}"
                + (f" (`{rec['command']}`)" if rec.get("command") else ""))
    if rec.get("source") == "fetched":
        return f"fetched by the run and recorded {rec['when']}"
    return ""


def seed_text(seeds: list[str]) -> str:
    ints = [int(x) for x in seeds if str(x).lstrip("-").isdigit()]
    if len(ints) == len(seeds) > 2 and ints == list(range(ints[0], ints[0] + len(ints))):
        return f"{ints[0]}-{ints[-1]}"
    return ", ".join(map(str, seeds))


def parse_seeds(values: list[str]) -> list[str]:
    """`--seeds 1-50`, `--seeds 1,2,7` or repeated `--seeds`; ranges are inclusive."""
    out: list[str] = []
    for v in values:
        for part in str(v).split(","):
            part = part.strip()
            lo, _, hi = part.partition("-")
            if lo.isdigit() and hi.isdigit():
                if int(hi) < int(lo):
                    raise CraftError(f"--seeds {part}: the range runs backwards")
                out += [str(i) for i in range(int(lo), int(hi) + 1)]
            elif part:
                out.append(part)
    return list(dict.fromkeys(out))


def use_problems(data_id: str, rec: dict, seeds: list, evidence_mtime: float | None) -> list[str]:
    """Why evidence cannot cite this record: seeds outside a generated record, or evidence that existed
    before a fetched input was recorded."""
    problems = []
    if rec.get("source") == "generated" and seeds:
        extra = [str(x) for x in seeds if str(x) not in set(rec["seeds"])]
        if extra:
            problems.append(f"the evidence used seeds {', '.join(extra)}, which '{data_id}' was not recorded with "
                            f"(seeds {seed_text(rec['seeds'])}); record the wider set under a new id")
    if rec.get("source") == "fetched" and evidence_mtime is not None:
        from .registry import parse_iso

        if evidence_mtime < parse_iso(rec["when"]):
            problems.append(f"the evidence was produced before '{data_id}' was recorded ({rec['when']}); a fetched input "
                            "is recorded by the run right after fetching, before anything uses it")
    return problems


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
