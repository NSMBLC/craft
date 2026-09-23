"""Helpers shared by the CLI and hooks: integrity verification and status text."""

from __future__ import annotations

from .envlock import verify_lock
from .freeze import check_hash
from .paths import InvestigationPaths, Programme
from .state import InvestigationState, Phase
from .util import CraftError


def verify_investigation(prog: Programme, inv_id: str, taint: bool = True) -> list[str]:
    root = prog.investigation_dir(inv_id)
    try:
        state = InvestigationState.load(root)
    except CraftError as e:
        return [f"{inv_id}: {e}"]
    inv = InvestigationPaths(root)
    problems = []
    if state.problem_sha256:
        p = check_hash(inv.problem, state.problem_sha256)
        if p:
            problems.append(f"{inv_id}: {p}")
    if state.review.frozen_sha256:
        p = check_hash(inv.hypothesis, state.review.frozen_sha256)
        if p:
            problems.append(f"{inv_id}: {p}")
    for n, rnd in enumerate(state.review.rounds, start=1):
        rp = inv.review_round(rnd.n)
        if not rp.exists():
            problems.append(f"{inv_id}: review/round-{rnd.n}.json is missing")
    lp = verify_lock(inv, state)
    if lp:
        problems.append(f"{inv_id}: {lp}")
    for v in state.verdicts:
        if not (root / v.file).exists():
            problems.append(f"{inv_id}: verdict file {v.file} is missing")
    if problems and taint and not state.tainted:
        for p in problems:
            state.taint(p)
        state.save(root)
    return problems


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
    problems += verify_memory(prog)
    return problems


def status_text(prog: Programme) -> str:
    lines = []
    invs = prog.list_investigations()
    if not invs:
        lines.append("No open investigations. The agent starts one with `craft recall` then `craft new <id> --topic ...`.")
    for inv_id in invs:
        try:
            st = InvestigationState.load(prog.investigation_dir(inv_id))
        except CraftError as e:
            lines.append(f"- {inv_id}: {e}")
            continue
        who, cmd, why = st.next_action()
        hold = " [INTEGRITY HOLD]" if st.tainted else ""
        lines.append(f"- {inv_id} — phase {st.phase.value}{hold}")
        lines.append(f"    {why}.")
        if who != "nobody":
            lines.append(f"    Waiting on the {who}: {cmd}")
        if st.phase == Phase.RESPONDING and st.open_blocking:
            lines.append(f"    open blocking objections: {', '.join(st.open_blocking)}")
    archived = prog.list_archived()
    if archived:
        lines.append(f"Archived investigations: {', '.join(archived)}")
    return "\n".join(lines)


RESEARCHER_HELP = """Your commands (type them as messages; CRAFT executes them before the agent sees them):
  /craft-approve                 approve what the agent is waiting on: the one-page problem
                                 statement (framing) or a proposed package (execution)
  /craft-reject --note "why"     refuse a proposed package; execution continues as is
  /craft-close                   close the investigation: outcomes go to memory, files to archive
  /craft-reopen problem|review   withdraw an approval (problem) or restart review after a real fix
  /craft-resolve --note "..."    clear an integrity hold after you have reviewed what happened
  /craft-status                  where each investigation stands and whose turn it is
  /craft-decisions               the log of your decisions
  /craft-explain <id>            walk a finding's evidence chain (e.g. F-0001, R-0002)
  /craft-help                    this list
Add --inv <id> when more than one investigation is open. Everything else is the agent's job."""


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
    hyp = prog.archive_dir / rec["investigation"] / "hypothesis.md"
    ok = hyp.exists() and (lin.get("hypothesis_sha256") is None or sha256_file(hyp) == lin["hypothesis_sha256"])
    broken += 0 if ok else 1
    out.append(f"  frozen hypothesis archive/{rec['investigation']}/hypothesis.md: {'resolves' if ok else 'BROKEN'}")
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
