"""Helpers shared by the CLI and hooks: context loading, integrity verification, the board."""

from __future__ import annotations

from pathlib import Path

from .envlock import verify_lock
from .integrity import check_hash
from .paths import InvestigationPaths, Programme
from .state import InvestigationState
from .util import CraftError


def load_context(prog: Programme, inv_id: str | None) -> tuple[InvestigationPaths, InvestigationState]:
    inv_id = pick_investigation(prog, inv_id)
    inv = InvestigationPaths(prog.investigation_dir(inv_id))
    if inv.legacy_hypothesis.exists() and not inv.hypotheses_dir.exists():
        raise CraftError(
            f"investigation {inv_id} uses the earlier single-hypothesis format (hypothesis.md), which is not "
            "migrated: start it again with `craft new`."
        )
    return inv, InvestigationState.load(inv.root)


def _verify_root(root: Path, label: str) -> list[str]:
    try:
        state = InvestigationState.load(root)
    except CraftError as e:
        return [f"{label}: {e}"]
    inv = InvestigationPaths(root)
    problems = []
    for rel, digest in sorted(state.records.items()):
        p = check_hash(root / rel, digest, rel)
        if p:
            problems.append(f"{label}: {p}")
    lp = verify_lock(inv, state)
    if lp:
        problems.append(f"{label}: {lp}")
    for v in state.verdicts:
        if not (root / v.file).exists():
            problems.append(f"{label}: verdict file {v.file} is missing")
    return problems


def verify_investigation(prog: Programme, inv_id: str, taint: bool = True) -> list[str]:
    root = prog.investigation_dir(inv_id)
    problems = _verify_root(root, inv_id)
    if problems and taint:
        state = InvestigationState.load(root)
        if not state.tainted:
            for p in problems:
                state.taint(p)
            state.save(root)
    return problems


def verify_archive(prog: Programme, inv_id: str) -> list[str]:
    return _verify_root(prog.archive_dir / inv_id, f"archive/{inv_id}")


def verify_memory(prog: Programme) -> list[str]:
    problems = []
    from .util import read_jsonl

    for kind in ("finding", "refuted", "open"):
        path = prog.memory_file(kind)
        try:
            read_jsonl(path)
        except Exception as e:  # noqa: BLE001
            problems.append(f"memory/{path.name} is corrupt: {e}")
    return problems


def verify_all(prog: Programme) -> list[str]:
    problems = []
    for inv_id in prog.list_investigations():
        problems += verify_investigation(prog, inv_id)
    for inv_id in prog.list_archived():
        problems += verify_archive(prog, inv_id)
    problems += verify_memory(prog)
    return problems


def status_text(prog: Programme, inv_id: str | None = None) -> str:
    from . import registry

    lines = []
    invs = [inv_id] if inv_id else prog.list_investigations()
    if not invs:
        lines.append("No open investigations. The agent starts one with `craft recall` then `craft new <id> --topic ...`.")
    for i in invs:
        try:
            inv, st = load_context(prog, i)
        except CraftError as e:
            lines.append(f"- {i}: {e}")
            continue
        lines.append(registry.board_text(inv, st))
    archived = prog.list_archived()
    if archived and not inv_id:
        lines.append(f"Archived investigations: {', '.join(archived)}")
    return "\n".join(lines)


RESEARCHER_HELP = """Your commands (type them as messages; CRAFT executes them before the agent sees them):
  /craft-approve                 approve what the agent is waiting on: the one-page problem
                                 statement (or a changed version of it), or a proposed package
  /craft-reject --note "why"     refuse a proposed package; work continues with the current environment
  /craft-close                   close the investigation whenever you choose: outcomes go to memory,
                                 untested hypotheses, ideas and questions to open questions, files to archive
  /craft-resolve --note "..."    clear an integrity hold after you have reviewed what happened
  /craft-status                  the board: hypotheses, experiments, open questions, whose turn it is
  /craft-decisions               the log of your decisions
  /craft-explain <id>            walk a finding's evidence chain (e.g. F-0001, R-0002)
  /craft-help                    this list
Everything you plan stays editable: problem, hypotheses, experiment plans, literature, questions.
Just tell the agent what to add, park, drop or pursue. Add --inv <id> when several investigations are open."""


def decisions_text(prog: Programme, inv_id: str | None = None) -> str:
    ids = [inv_id] if inv_id else prog.list_investigations() + prog.list_archived()
    lines = []
    for i in ids:
        root = prog.investigation_dir(i) if prog.investigation_dir(i).exists() else prog.archive_dir / i
        if not (root / "state.json").exists():
            continue
        st = InvestigationState.load(root)
        for a in st.attention:
            lines.append(f"{a.when}  {i:<20} {a.kind:<18} {a.subject}  {a.note}")
        for ack in st.acknowledgements:
            lines.append(f"{ack.when}  {i:<20} {'acknowledge':<18} {ack.ref}  {ack.justification}")
    lines.sort()
    return "\n".join(lines) if lines else "No researcher decisions recorded yet."


def explain_text(prog: Programme, entry_id: str) -> tuple[str, int]:
    """Walk claim -> criterion -> observed -> files. Returns (text, number of broken links)."""
    from . import memory as mem
    from .util import sha256_file

    rec = mem.find_entry(prog, entry_id)
    if rec is None:
        raise CraftError(f"no memory entry {entry_id}")
    out = [f"[{rec['kind']}] {entry_id}: {rec.get('claim') or rec.get('question')}",
           f"  investigation: {rec.get('investigation')}  closed: {rec.get('closed', '')[:10]}"]
    if rec.get("post_hoc"):
        out.append("  POST-HOC: the criterion was changed after registration; the label is the pre-registered one")
    lin = rec.get("lineage")
    if not lin:
        out.append("  (no evidence lineage: this entry is an open question or anomaly)")
        return "\n".join(out), 0
    broken = 0
    out.append(f"  criterion {lin['criterion']} in experiment {lin['experiment']}: observed {lin.get('observed')} vs threshold {lin.get('threshold')}")
    vf = prog.root / lin["verdict_file"]
    ok = vf.exists() and (lin.get("verdict_sha256") is None or sha256_file(vf) == lin["verdict_sha256"])
    broken += 0 if ok else 1
    out.append(f"  verdict file {lin['verdict_file']}: {'resolves' if ok else 'BROKEN'}")
    for e in lin.get("evidence", []):
        p = prog.root / e["path"]
        ok = p.exists() and sha256_file(p) == e["sha256"]
        broken += 0 if ok else 1
        out.append(f"  evidence {e['path']} (sha256 {e['sha256'][:12]}): {'resolves' if ok else 'BROKEN'}")
    hyp_rel = lin.get("hypothesis_file") or f"archive/{rec['investigation']}/hypothesis.md"  # archives in the earlier format
    hyp = prog.root / hyp_rel
    ok = hyp.exists() and (lin.get("hypothesis_sha256") is None or sha256_file(hyp) == lin["hypothesis_sha256"])
    broken += 0 if ok else 1
    out.append(f"  registered hypothesis {hyp_rel}: {'resolves' if ok else 'BROKEN'}")
    out.append(f"  env v{lin.get('env_version')}; seeds {lin.get('seeds')}; data {lin.get('data_ids')}")
    out.append("Every link resolves." if not broken else f"{broken} link(s) do not resolve.")
    return "\n".join(out), broken


def pick_investigation(prog: Programme, inv_id: str | None) -> str:
    if inv_id:
        if not prog.investigation_dir(inv_id).exists():
            raise CraftError(f"no open investigation '{inv_id}' (archived ones are read-only)")
        return inv_id
    invs = prog.list_investigations()
    if len(invs) == 1:
        return invs[0]
    if not invs:
        raise CraftError("no open investigation; create one with `craft new`")
    raise CraftError(f"several open investigations ({', '.join(invs)}); pass --inv <id>")
