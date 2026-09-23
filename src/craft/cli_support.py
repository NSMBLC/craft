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
        lines.append("No open investigations. Start one with `craft new <id> --topic ...` (after `craft recall`).")
    for inv_id in invs:
        try:
            st = InvestigationState.load(prog.investigation_dir(inv_id))
        except CraftError as e:
            lines.append(f"- {inv_id}: {e}")
            continue
        flag = " [TAINTED]" if st.tainted else ""
        lines.append(f"- {inv_id} — phase {st.phase.value}{flag}: {st.blocked_reason()}")
        if st.phase == Phase.RESPONDING and st.open_blocking:
            lines.append(f"    open blocking objections: {', '.join(st.open_blocking)}")
        if st.env.pending_proposal:
            lines.append(f"    pending env proposal: {st.env.pending_proposal['package']}")
    archived = prog.list_archived()
    if archived:
        lines.append(f"Archived investigations: {', '.join(archived)}")
    return "\n".join(lines)


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
