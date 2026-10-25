"""Closing an investigation: route outcomes and open threads to memory, archive intact (Journey 7).

Routing: a supported criterion -> findings; refuted -> refuted; inconclusive, untested registered
criteria, draft ideas, unfinished experiments, open questions.md bullets, closure.md anomalies and a
fired kill criterion -> open questions; questions.md bullets marked answered -> answered questions;
exploratory experiments that ran -> exploratory work. Dropped hypotheses go nowhere but stay in the archive.
"""

from __future__ import annotations

import shutil

from .. import memory as mem
from .. import registry
from ..paths import MEMORY_FILES, InvestigationPaths, Programme
from ..state import InvestigationState, Phase
from ..util import CraftError, append_jsonl, now_iso, read_doc, sha256_file, split_frontmatter


def _next_id(prog: Programme, prefix: str) -> str:
    existing = 0
    for fname in MEMORY_FILES.values():
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
        raise CraftError(f"investigation {state.id} is in phase '{state.phase.value}', not closing.")
    prob_fm, _ = read_doc(inv.problem)
    closure_fm: dict = {}
    if inv.closure.exists():
        closure_fm, _ = read_doc(inv.closure)
    when = now_iso()
    archive_root = prog.archive_dir / state.id
    if archive_root.exists():
        raise CraftError(f"archive/{state.id} already exists")
    arch = f"archive/{state.id}"

    keywords = mem.tokenize(" ".join(str(prob_fm.get(k, "")) for k in ("title", "studying", "to_find_out")))[:40]
    routed: dict[str, list[str]] = {k: [] for k in MEMORY_FILES}

    def put(kind: str, prefix: str, rec: dict) -> None:
        rec = {"id": _next_id(prog, prefix), **rec, "investigation": state.id, "closed": when}
        rec.setdefault("keywords", keywords)
        append_jsonl(prog.memory_file(kind), rec)
        routed[kind].append(rec["id"])

    hyps = {h.id: h for h in registry.all_hypotheses(inv, state)}
    for v in state.verdicts:
        if v.label.startswith("kill-"):
            continue  # kill checks are not claims; a fired kill is routed below
        hid, _, cname = v.criterion.partition(":")
        h = hyps.get(hid)
        crit = h.criteria.get(cname, {}) if h else {}
        vfile = inv.root / v.file
        vfm, _ = split_frontmatter(vfile.read_text(encoding="utf-8")) if vfile.exists() else ({}, "")
        claim_text = f"{h.claim if h else ''} [{v.criterion}: {crit.get('metric')} {crit.get('op')} {crit.get('threshold')}]"
        tags = _tags(h, v.post_hoc)
        lineage = {
            "hypothesis": hid,
            "criterion": v.criterion,
            "experiment": v.experiment,
            "verdict_file": f"{arch}/{v.file}",
            "verdict_sha256": sha256_file(vfile) if vfile.exists() else None,
            "evidence": [{"path": f"{arch}/{e['path']}", "sha256": e["sha256"]} for e in vfm.get("evidence", [])],
            "observed": vfm.get("observed"),
            "threshold": vfm.get("threshold"),
            "env_version": vfm.get("env_version"),
            "seeds": vfm.get("seeds"),
            "data_ids": vfm.get("data_ids"),
            "data_records": vfm.get("data_records") or [],
            "hypothesis_file": f"{arch}/{inv.rel(inv.registered(hid))}",
            "hypothesis_sha256": h.rec.registered_sha256 if h else None,
            "post_hoc": vfm.get("post_hoc"),
        }
        if v.limitations:
            tags["limitations"] = list(v.limitations)
            lineage["limitations_file"] = f"{arch}/{inv.rel(inv.verdict_limitations(v.experiment, v.criterion))}"
        if v.label == "supported":
            put("finding", "F", {"claim": claim_text, **tags, "lineage": lineage})
        elif v.label == "refuted":
            put("refuted", "R", {"claim": claim_text, **tags, "lineage": lineage})
        else:
            put("open", "Q", {"question": f"inconclusive: {claim_text}", **tags,
                              "context": vfm.get("rationale", ""), "lineage": lineage})

    for h in hyps.values():
        if h.status == "dropped" or not h.claim:
            continue
        if not h.rec.registered_sha256:
            put("open", "Q", {"question": f"untested idea {h.id}: {h.claim}", **_tags(h, False),
                              "context": "drafted but never registered by review"})
        elif h.status == "registered" and h.untested:
            put("open", "Q", {"question": f"untested {h.id}: {h.claim} [{', '.join(h.untested)} never judged]",
                              **_tags(h, h.post_hoc), "context": f"registered {h.rec.registered_at}; no verdict before closure"})

    for e in registry.all_experiments(inv, state):
        src = {"origin": str(e.plan.get("origin") or "researcher"), "derived_from": str(e.plan.get("derived_from") or "")}
        if e.exploratory and e.status == "run":
            put("exploratory", "X", {"summary": f"exploratory experiment {e.name}: {e.description or '(no description)'}",
                                     **src, "files": [f"{arch}/{f}" for f in e.explored],
                                     "context": "completed exploratory work; it can inform designs but never backs a criterion"})
        elif e.status in ("planned", "run") and e.description:
            put("open", "Q", {"question": f"experiment {e.name} was {'planned but never run' if e.status == 'planned' else 'run but not judged'}: {e.description}",
                              **src, "context": f"tests {', '.join(e.tests) or 'nothing'}"})

    for q in registry.parked_questions(inv):
        if q.answered:
            put("answered", "A", {"question": q.text, "answered_by": _archived(inv, arch, q.pointer),
                                  "context": "parked in questions.md and answered before closure"})
        else:
            put("open", "Q", {"question": q.text, "context": "parked in questions.md"})

    for a in closure_fm.get("anomalies") or []:
        if isinstance(a, dict) and a.get("question"):
            put("open", "Q", {"question": a["question"], "context": a.get("context", "")})

    if state.kill.triggered:
        put("open", "Q", {"question": f"killed by {state.kill.criterion}: {prob_fm.get('to_find_out', state.topic)}",
                          "context": f"kill criterion met (observed {state.kill.observed}); evidence {state.kill.evidence}"})

    state.phase = Phase.CLOSED
    state.closed_at = when
    state.closure_summary = {"routed": routed, "note": note}
    state.attend("close", state.id, note)
    state.save(inv.root)

    # archive intact; `craft verify` keeps checking the recorded hashes there
    prog.archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(inv.root), str(archive_root))
    mem.build_index(prog)
    return routed


def _archived(inv: InvestigationPaths, arch: str, pointer: str) -> str:
    """A pointer to a file in the investigation, rewritten to where closing archives it."""
    path = pointer.split("#", 1)[0].strip()
    if path and (inv.root / path).exists():
        return f"{arch}/{pointer.strip()}"
    return pointer


def _tags(h: "registry.HypView | None", post_hoc: bool) -> dict:
    if h is None:
        return {"post_hoc": post_hoc}
    tags = {"hypothesis": h.id, "origin": h.origin, "derived_from": h.derived_from, "post_hoc": post_hoc}
    if h.status in registry.OUTCOMES:
        tags["hypothesis_outcome"] = h.status
        tags["outcome_basis"] = h.label_basis()
    return tags
