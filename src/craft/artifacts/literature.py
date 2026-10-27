"""literature/sources.yaml: prior work as a conversation (Journey 2).

Always open: new searches can add sources at any point before closure. Each entry is date-stamped,
and every review round keeps the exact documents the referee saw (review/<id>/round-<n>.prompt.md).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..util import CraftError, now_iso, read_yaml, sha256_file, write_yaml
from .common import Validation, nonempty

USED_FIELDS = ("claims", "method", "relation", "does_not_cover")
# used: full text read (may back claims); abstract-only: consulted and citable for context, never backs a
# claim; rejected: consulted and set aside as not relevant.
STATUSES = ("used", "abstract-only", "rejected")
RELATIONS = {"supports", "conflicts", "orthogonal", "mixed"}

PRIORITY_CLAIM_RE = re.compile(
    r"\b(no (prior|previous|existing) work|first to|has not been (studied|addressed|explored)|"
    r"nobody has|there is no (prior|existing) (work|study|research)|novel(ty)? claim|unprecedented)\b",
    re.I,
)


def load_sources(path: Path) -> dict:
    data = read_yaml(path, {}) or {}
    data.setdefault("sources", [])
    data.setdefault("closest_prior_work", None)
    data.setdefault("delta", "")
    return data


def add_source(
    path: Path,
    key: str,
    title: str,
    fulltext: Path | None,
    reason: str | None,
    claims: str = "",
    method: str = "",
    relation: str = "",
    does_not_cover: str = "",
    rejected: bool = False,
) -> dict:
    data = load_sources(path)
    if any(s.get("key") == key for s in data["sources"]):
        raise CraftError(f"source '{key}' already exists in {path}")
    entry: dict = {"key": key, "title": title, "added": now_iso()}
    if fulltext is not None:
        if not fulltext.exists() or fulltext.stat().st_size == 0:
            raise CraftError(
                f"--fulltext {fulltext} does not exist or is empty. A source counts as *used* only when its "
                "full text was retrieved and read. Otherwise add it with --abstract-only --reason."
            )
        entry.update(
            status="used",
            fulltext=str(fulltext),
            fulltext_sha256=sha256_file(fulltext),
            claims=claims,
            method=method,
            relation=relation,
            does_not_cover=does_not_cover,
        )
    else:
        if not reason:
            raise CraftError("a source not read in full needs --reason (one line: why only the abstract, or why it was set aside)")
        entry.update(status="rejected" if rejected else "abstract-only", reason=reason)
    data["sources"].append(entry)
    write_yaml(path, data)
    return entry


def validate_literature(path: Path) -> Validation:
    v = Validation("literature/sources.yaml")
    if not path.exists():
        v.error("sources.yaml", "missing — run `craft literature add` for each source consulted")
        for f in unrecorded_files(path.parent, {"sources": []}):
            v.warn(f"literature/{f}", "a file in literature/ that no source records")
        return v
    data = load_sources(path)
    used = [s for s in data["sources"] if s.get("status") == "used"]
    for s in data["sources"]:
        key = s.get("key", "?")
        if s.get("status") == "used":
            ft = s.get("fulltext")
            if not ft or not Path(ft).exists():
                v.error(f"{key}.fulltext", "used source whose full text is not on disk; record it as abstract-only with a reason")
            for f in USED_FIELDS:
                if not nonempty(s.get(f)):
                    v.error(f"{key}.{f}", "missing (what it claims / how / supports-or-conflicts / what it does NOT cover)")
            if s.get("relation") and s["relation"] not in RELATIONS:
                v.error(f"{key}.relation", f"must be one of {sorted(RELATIONS)}")
        elif s.get("status") in ("abstract-only", "rejected"):
            if not nonempty(s.get("reason")):
                v.error(f"{key}.reason", f"{s['status']} source needs a one-line reason")
        else:
            v.error(f"{key}.status", f"must be one of {', '.join(STATUSES)}")
    for f in unrecorded_files(path.parent, data):
        v.warn(f"literature/{f}", "a file in literature/ that no source records: add it (`craft literature add`, "
                                  "read in full or --abstract-only) or remove it")
    if used:
        cpw = data.get("closest_prior_work")
        if not cpw:
            v.error("closest_prior_work", "name the single closest prior work")
        elif cpw not in {s.get("key") for s in used}:
            v.error("closest_prior_work", f"'{cpw}' is not a used source")
        if not nonempty(data.get("delta")):
            v.error("delta", "one paragraph stating exactly what this investigation adds beyond the closest prior work")
    else:
        v.warn("sources", "no used sources yet")
    return v


_LIT_OWN = {"sources.yaml", "map.md"}


def unrecorded_files(lit_dir: Path, data: dict) -> list[str]:
    """Files under literature/ that no source's full text points at (by name or by contents)."""
    names = {Path(str(s.get("fulltext"))).name for s in data["sources"] if s.get("fulltext")}
    hashes = {s.get("fulltext_sha256") for s in data["sources"] if s.get("fulltext_sha256")}
    out = []
    for f in sorted(lit_dir.rglob("*")) if lit_dir.exists() else []:
        rel = f.relative_to(lit_dir).as_posix()
        if not f.is_file() or rel in _LIT_OWN or any(part.startswith(".") for part in f.relative_to(lit_dir).parts):
            continue
        if f.name not in names and sha256_file(f) not in hashes:
            out.append(rel)
    return out


def lint_priority_claims(doc: Path, sources: Path) -> list[str]:
    """Return problems: bare 'no prior work' style claims not backed by a named closest work + delta."""
    text = doc.read_text(encoding="utf-8")
    hits = [m.group(0) for m in PRIORITY_CLAIM_RE.finditer(text)]
    if not hits:
        return []
    data = load_sources(sources) if sources.exists() else {"closest_prior_work": None, "delta": ""}
    cpw = data.get("closest_prior_work")
    problems = []
    for h in hits:
        if not cpw or not nonempty(data.get("delta")):
            problems.append(
                f"'{h}': bare priority claim. Name the closest prior work in literature/sources.yaml and "
                "write the specific delta against it instead."
            )
        elif cpw not in text:
            problems.append(
                f"'{h}': the document asserts priority without citing the closest prior work ({cpw}). "
                "Replace the assertion with the delta against it."
            )
    return problems


def _find_fulltext(root: Path, src_dir: Path, src_id: str, ft: str, digest: str) -> Path | None:
    """The source investigation's full text, wherever it now is, if its contents still match the record."""
    p = Path(ft)
    candidates = [p] if p.is_absolute() else [root / p, src_dir / p]
    rel = p.as_posix()
    for prefix in (f"investigations/{src_id}/", f"archive/{src_id}/"):
        if rel.startswith(prefix):
            candidates.append(src_dir / rel[len(prefix):])
    candidates.append(src_dir / "literature" / p.name)
    for c in candidates:
        if c.is_file() and sha256_file(c) == digest:
            return c
    return None


def carry_sources(root: Path, src_dir: Path, src_id: str, lit_dir: Path, sources: Path,
                  keys: list[str]) -> tuple[list[str], list[str]]:
    """Copy sources (records and full texts) from another investigation into this one.

    Each carried entry keeps its fields and full-text hash, gets today's `added`, and says where it came
    from (`carried_from`). A full text is copied into this investigation's literature/ only when its
    contents still match the recorded hash. The closest prior work and the delta are not carried: they
    are judged against this investigation's question. Returns (carried keys, skipped with reasons).
    """
    src = load_sources(src_dir / "literature" / "sources.yaml")
    by_key = {s.get("key"): s for s in src["sources"]}
    unknown = [k for k in keys if k not in by_key]
    if unknown:
        raise CraftError(f"{src_id} has no source {', '.join(unknown)} (it has: {', '.join(map(str, by_key)) or 'none'})")
    data = load_sources(sources)
    have = {s.get("key") for s in data["sources"]}
    carried, skipped = [], []
    for key in keys or list(by_key):
        s = by_key[key]
        if key in have:
            skipped.append(f"{key}: already in this investigation")
            continue
        entry = {k: v for k, v in s.items() if k not in ("added", "carried_from")}
        entry["added"] = now_iso()
        entry["carried_from"] = {"investigation": src_id, "added": s.get("added"),
                                 **({"fulltext": s.get("fulltext")} if s.get("fulltext") else {})}
        if s.get("status") == "used":
            found = _find_fulltext(root, src_dir, src_id, str(s.get("fulltext") or ""), str(s.get("fulltext_sha256") or ""))
            if found is None:
                skipped.append(f"{key}: its full text is not found with the recorded hash; add it again with "
                               "`craft literature add` (read it in full, or --abstract-only)")
                continue
            dest = lit_dir / found.name
            if dest.exists() and sha256_file(dest) != s["fulltext_sha256"]:
                skipped.append(f"{key}: {dest.name} already exists in literature/ with different contents")
                continue
            lit_dir.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                dest.write_bytes(found.read_bytes())
            entry["fulltext"] = dest.relative_to(root).as_posix()
        data["sources"].append(entry)
        carried.append(key)
    if carried:
        write_yaml(sources, data)
    return carried, skipped
