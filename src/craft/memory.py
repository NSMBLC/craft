"""Institutional memory: findings, refutations, open questions, and recall.

Written only by `craft close` (closure.py). Read by `craft recall`, `craft new`, hooks.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .paths import MEMORY_FILES, Programme
from .util import read_jsonl, split_frontmatter, write_json

STOP = set("""a an the and or of to in on for with by from as at is are was were be been being this that these those
it its into over under about vs versus than then so if we our their his her they them you your i me my do does did
not no yes can could would should may might will shall into onto per via across between among whether which what
who whom how when where why all any some more most less least very much many few each both either neither""".split())

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-\.]*[a-z0-9]|[a-z0-9]")


def tokenize(text: str) -> list[str]:
    out = []
    for t in _TOKEN_RE.findall((text or "").lower()):
        t = t.strip(".-")
        if len(t) < 2 or t in STOP:
            continue
        # crude stemming
        for suf in ("ings", "ing", "ies", "ed", "es", "s"):
            if len(t) > 4 and t.endswith(suf):
                t = t[: -len(suf)] + ("y" if suf == "ies" else "")
                break
        out.append(t)
    return out


@dataclass
class Hit:
    id: str
    kind: str
    text: str
    investigation: str
    date: str
    score: float
    overlap: list[str]
    pointer: str

    def cite(self) -> str:
        return f"[{self.kind}:{self.id}] {self.text} (investigation {self.investigation}, {self.date[:10]})"


def build_index(prog: Programme) -> list[dict]:
    entries = []
    for kind, fname in MEMORY_FILES.items():
        for rec in read_jsonl(prog.memory_dir / fname):
            text = rec.get("claim") or rec.get("question") or ""
            entries.append({
                "id": rec["id"], "kind": kind, "text": text,
                "investigation": rec.get("investigation", ""), "date": rec.get("closed", rec.get("when", "")),
                "tokens": tokenize(" ".join([text, rec.get("context", ""), " ".join(rec.get("keywords", []))])),
                "pointer": f"memory/{fname}#{rec['id']}",
            })
    # archived problem statements are memory too: what was asked
    for inv_id in prog.list_archived():
        p = prog.archive_dir / inv_id / "problem.md"
        if p.exists():
            fm, body = split_frontmatter(p.read_text(encoding="utf-8"))
            text = " ".join(str(fm.get(k, "")) for k in ("title", "studying", "to_find_out"))
            entries.append({
                "id": inv_id, "kind": "investigation", "text": text.strip(),
                "investigation": inv_id, "date": str(fm.get("closed", "")),
                "tokens": tokenize(text + " " + body[:2000]),
                "pointer": f"archive/{inv_id}/problem.md",
            })
    write_json(prog.memory_index, entries)
    return entries


def _index_stale(prog: Programme) -> bool:
    if not prog.memory_index.exists():
        return True
    ts = prog.memory_index.stat().st_mtime
    for fname in MEMORY_FILES.values():
        p = prog.memory_dir / fname
        if p.exists() and p.stat().st_mtime > ts:
            return True
    if prog.archive_dir.exists() and prog.archive_dir.stat().st_mtime > ts:
        return True
    return False


def load_index(prog: Programme) -> list[dict]:
    from .util import read_json

    if not prog.memory_dir.exists():
        return []
    if _index_stale(prog):
        return build_index(prog)
    idx = read_json(prog.memory_index, None)
    return idx if idx is not None else build_index(prog)


def recall(prog: Programme, query: str, min_overlap: int | None = None) -> list[Hit]:
    """BM25 over memory entries; a hit needs at least `min_overlap` shared content tokens."""
    idx = load_index(prog)
    if not idx:
        return []
    cfg = prog.config.get("recall", {})
    if min_overlap is None:
        min_overlap = int(cfg.get("min_overlap", 2))
    q = tokenize(query)
    if not q:
        return []
    q_set = set(q)
    N = len(idx)
    avgdl = sum(len(e["tokens"]) for e in idx) / N
    df: Counter = Counter()
    for e in idx:
        for t in set(e["tokens"]):
            df[t] += 1
    k1, b = 1.5, 0.75
    hits = []
    for e in idx:
        tf = Counter(e["tokens"])
        dl = len(e["tokens"]) or 1
        score = 0.0
        overlap = []
        for t in q_set:
            if t in tf:
                overlap.append(t)
                idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * dl / avgdl))
        need = min(min_overlap, max(1, len(q_set)))
        if len(overlap) >= need and score > 0:
            hits.append(Hit(e["id"], e["kind"], e["text"], e["investigation"], e["date"], score, sorted(overlap), e["pointer"]))
    hits.sort(key=lambda h: -h.score)
    return hits


def collisions(prog: Programme, query: str) -> list[Hit]:
    kinds = set(prog.config.get("recall", {}).get("require_ack_kinds", ["refuted"]))
    return [h for h in recall(prog, query) if h.kind in kinds]


def find_entry(prog: Programme, entry_id: str) -> dict | None:
    for kind, fname in MEMORY_FILES.items():
        for rec in read_jsonl(prog.memory_dir / fname):
            if rec.get("id") == entry_id:
                rec = dict(rec)
                rec["kind"] = kind
                return rec
    return None


def ensure_memory_files(prog: Programme) -> None:
    prog.memory_dir.mkdir(parents=True, exist_ok=True)
    for fname in MEMORY_FILES.values():
        p = prog.memory_dir / fname
        if not p.exists():
            p.touch()
    if not prog.memory_index.exists():
        write_json(prog.memory_index, [])
