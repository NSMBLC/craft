"""Closing an investigation: route outcomes to memory, archive intact (Journey 7)."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..freeze import freeze_tree
from ..paths import InvestigationPaths, Programme
from ..state import InvestigationState, Phase
from ..util import CraftError, append_jsonl, now_iso, read_doc, sha256_file, split_frontmatter
from .. import memory as mem


def _next_id(prog: Programme, prefix: str) -> str:
    existing = 0
    for fname in ("findings.jsonl", "refuted.jsonl", "open-questions.jsonl"):
        for rec in mem.read_jsonl(prog.memory_dir / fname):
            if str(rec.get("id", "")).startswith(prefix + "-"):
                try:
                    existing = max(existing, int(rec["id"].split("-")[-1]))
                except ValueError:
                    pass
    return f"{prefix}-{existing + 1:04d}"


def close_investigation(prog: Programme, inv: InvestigationPaths, state: InvestigationState, note: str) -> dict:
    """Assumes the caller already verified the researcher and integrity."""
    if state.phase != Phase.CLOSING:
        raise CraftError(f"investigation {state.id} is in phase '{state.phase.value}', not closing. {state.blocked_reason()}")
    hyp_fm, _ = read_doc(inv.hypothesis)
    prob_fm, _ = read_doc(inv.problem)
    closure_fm: dict = {}
    if inv.closure.exists():
        closure_fm, _ = read_doc(inv.closure)
    when = now_iso()
    archive_root = prog.archive_dir / state.id
    if archive_root.exists():
        raise CraftError(f"archive/{state.id} already exists")

    keywords = mem.tokenize(" ".join(str(prob_fm.get(k, "")) for k in ("title", "studying", "to_find_out")))[:40]
    routed = {"finding": [], "refuted": [], "open": []}
    criteria = {c["name"]: c for c in hyp_fm.get("criteria", []) if isinstance(c, dict)}

    for v in state.verdicts:
        vfile = inv.root / v.file
        vfm, _ = split_frontmatter(vfile.read_text(encoding="utf-8")) if vfile.exists() else ({}, "")
        crit = criteria.get(v.criterion, {})
        claim_text = f"{hyp_fm.get('claim', '')} [criterion {v.criterion}: {crit.get('metric')} {crit.get('op')} {crit.get('threshold')}]"
        lineage = {
            "criterion": v.criterion,
            "experiment": v.experiment,
            "verdict_file": f"archive/{state.id}/{v.file}",
            "verdict_sha256": sha256_file(vfile) if vfile.exists() else None,
            "evidence": [
                {"path": f"archive/{state.id}/{e['path']}", "sha256": e["sha256"]} for e in vfm.get("evidence", [])
            ],
            "observed": vfm.get("observed"),
            "threshold": vfm.get("threshold"),
            "env_version": vfm.get("env_version"),
            "seeds": vfm.get("seeds"),
            "data_ids": vfm.get("data_ids"),
            "hypothesis_sha256": state.review.frozen_sha256,
        }
        if v.label == "supported":
            rec = {"id": _next_id(prog, "F"), "claim": claim_text, "investigation": state.id, "closed": when,
                   "keywords": keywords, "lineage": lineage}
            append_jsonl(prog.memory_file("finding"), rec)
            routed["finding"].append(rec["id"])
        elif v.label == "refuted":
            rec = {"id": _next_id(prog, "R"), "claim": claim_text, "investigation": state.id, "closed": when,
                   "keywords": keywords, "lineage": lineage}
            append_jsonl(prog.memory_file("refuted"), rec)
            routed["refuted"].append(rec["id"])
        else:
            rec = {"id": _next_id(prog, "Q"), "question": f"inconclusive: {claim_text}", "investigation": state.id,
                   "closed": when, "keywords": keywords, "context": vfm.get("rationale", ""), "lineage": lineage}
            append_jsonl(prog.memory_file("open"), rec)
            routed["open"].append(rec["id"])

    for a in closure_fm.get("anomalies") or []:
        if not isinstance(a, dict) or not a.get("question"):
            continue
        rec = {"id": _next_id(prog, "Q"), "question": a["question"], "investigation": state.id, "closed": when,
               "keywords": keywords, "context": a.get("context", "")}
        append_jsonl(prog.memory_file("open"), rec)
        routed["open"].append(rec["id"])

    if state.kill.triggered:
        rec = {"id": _next_id(prog, "Q"), "question": f"killed by {state.kill.criterion}: {prob_fm.get('to_find_out', state.topic)}",
               "investigation": state.id, "closed": when, "keywords": keywords,
               "context": f"kill criterion met (observed {state.kill.observed}); evidence {state.kill.evidence}"}
        append_jsonl(prog.memory_file("open"), rec)
        routed["open"].append(rec["id"])

    state.phase = Phase.CLOSED
    state.closed_at = when
    state.closure_summary = {"routed": routed, "note": note}
    state.attend("close", state.id, note)
    state.save(inv.root)

    # archive intact and read-only
    prog.archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(inv.root), str(archive_root))
    freeze_tree(archive_root)
    mem.build_index(prog)
    return routed
