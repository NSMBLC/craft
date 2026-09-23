"""literature/sources.yaml: prior work as a conversation (Journey 2)."""

from __future__ import annotations

import re
from pathlib import Path

from ..util import CraftError, read_yaml, sha256_file, write_yaml
from .common import Validation, nonempty

USED_FIELDS = ("claims", "method", "relation", "does_not_cover")
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
) -> dict:
    data = load_sources(path)
    if any(s.get("key") == key for s in data["sources"]):
        raise CraftError(f"source '{key}' already exists in {path}")
    entry: dict = {"key": key, "title": title}
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
            raise CraftError("a consulted-and-rejected source needs --reason (one line)")
        entry.update(status="rejected", reason=reason)
    data["sources"].append(entry)
    write_yaml(path, data)
    return entry


def validate_literature(path: Path) -> Validation:
    v = Validation("literature/sources.yaml")
    if not path.exists():
        v.error("sources.yaml", "missing — run `craft literature add` for each source consulted")
        return v
    data = load_sources(path)
    used = [s for s in data["sources"] if s.get("status") == "used"]
    for s in data["sources"]:
        key = s.get("key", "?")
        if s.get("status") == "used":
            ft = s.get("fulltext")
            if not ft or not Path(ft).exists():
                v.error(f"{key}.fulltext", "used source whose full text is not on disk; move to rejected with a reason")
            for f in USED_FIELDS:
                if not nonempty(s.get(f)):
                    v.error(f"{key}.{f}", "missing (what it claims / how / supports-or-conflicts / what it does NOT cover)")
            if s.get("relation") and s["relation"] not in RELATIONS:
                v.error(f"{key}.relation", f"must be one of {sorted(RELATIONS)}")
        elif s.get("status") == "rejected":
            if not nonempty(s.get("reason")):
                v.error(f"{key}.reason", "rejected source needs a one-line reason")
        else:
            v.error(f"{key}.status", "must be 'used' or 'rejected'")
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
