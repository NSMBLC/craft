"""Derived views: hypothesis and experiment statuses, whose turn it is, and the board.

Nothing here is stored. Statuses come from the editable files (hypotheses/, experiments/*/plan.md,
questions.md) combined with what `craft` recorded in state.json (review rounds, registrations,
verdicts). The researcher never sets a status by hand.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .artifacts.hypothesis import criteria_table, validate_hypothesis
from .paths import InvestigationPaths, natural_key
from .state import HypothesisRecord, InvestigationState, Phase
from .util import CraftError, read_doc, sha256_file, split_frontmatter

OUTCOMES = ("supported", "refuted", "inconclusive")


def _fm(path: Path) -> dict:
    try:
        return read_doc(path)[0]
    except CraftError:
        return {}


def criteria_signature(fm: dict) -> str:
    """What pre-registration protects: the criteria table and the outcome rule."""
    crit = sorted((dict(c) for c in criteria_table(fm).values()), key=lambda c: c["name"])
    return json.dumps({"criteria": crit, "outcome_rule": fm.get("outcome_rule")}, sort_keys=True, default=str)


def parse_iso(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


# ------------------------------------------------------------------ hypotheses

@dataclass
class HypView:
    id: str
    path: Path
    exists: bool
    fm: dict
    rec: HypothesisRecord
    status: str                    # draft | in review | registered | supported | refuted | inconclusive | dropped
    complete: bool                 # the draft passes `craft validate`
    registered_fm: dict = field(default_factory=dict)
    criteria_labels: dict[str, str] = field(default_factory=dict)  # registered criterion name -> label
    post_hoc: bool = False         # criteria/outcome rule changed since registration
    changed_since_registration: bool = False

    @property
    def claim(self) -> str:
        return str((self.registered_fm or self.fm).get("claim") or "").strip()

    @property
    def origin(self) -> str:
        return str(self.fm.get("origin") or "researcher")

    @property
    def derived_from(self) -> str:
        return str(self.fm.get("derived_from") or "")

    @property
    def criteria(self) -> dict[str, dict]:
        """The binding criteria: as registered when registered, else as currently drafted."""
        return criteria_table(self.registered_fm if self.registered_fm else self.fm)

    @property
    def untested(self) -> list[str]:
        return [c for c in self.criteria if c not in self.criteria_labels]


def hyp_view(inv: InvestigationPaths, state: InvestigationState, hid: str) -> HypView:
    path = inv.hypothesis(hid)
    rec = state.hypotheses.get(hid) or HypothesisRecord()
    exists = path.exists()
    fm = _fm(path) if exists else {}
    complete = exists and validate_hypothesis(path).ok
    reg_fm = _fm(inv.registered(hid)) if rec.registered_sha256 and inv.registered(hid).exists() else {}
    v = HypView(hid, path, exists, fm, rec, "draft", complete, reg_fm)
    for vr in state.verdicts:
        h, _, c = vr.criterion.partition(":")
        if h == hid and c:
            v.criteria_labels[c] = vr.label
    if not exists or fm.get("dropped"):
        v.status = "dropped"
        return v
    if rec.registered_sha256:
        v.changed_since_registration = sha256_file(path) != rec.registered_sha256
        v.post_hoc = criteria_signature(fm) != criteria_signature(reg_fm)
        v.status = outcome(v) or "registered"
    elif rec.rounds and rec.open_blocking:
        v.status = "in review"
    return v


def outcome(v: HypView) -> str | None:
    """Mechanical roll-up of criterion labels: any refuted -> refuted; all supported -> supported;
    all judged otherwise -> inconclusive; not all judged -> None."""
    labels = [v.criteria_labels.get(c) for c in v.criteria]
    if not labels or any(lbl is None for lbl in labels):
        return "refuted" if "refuted" in labels else None
    if "refuted" in labels:
        return "refuted"
    if all(lbl == "supported" for lbl in labels):
        return "supported"
    return "inconclusive"


def all_hypotheses(inv: InvestigationPaths, state: InvestigationState) -> list[HypView]:
    ids = set(inv.hypothesis_ids()) | set(state.hypotheses)
    return [hyp_view(inv, state, h) for h in sorted(ids, key=natural_key)]


def registered_ids(inv: InvestigationPaths, state: InvestigationState) -> set[str]:
    return {h for h, r in state.hypotheses.items() if r.registered_sha256}


# ------------------------------------------------------------------ experiments

@dataclass
class ExpView:
    name: str
    plan: dict
    has_plan: bool
    tests: list[str]               # "H1:C1" keys
    exploratory: bool
    abandoned: str
    evidence: list[str]            # paths relative to the investigation
    verdicts: dict[str, str]       # criterion key -> label
    status: str                    # planned | run | done | abandoned

    @property
    def description(self) -> str:
        return str(self.plan.get("description") or self.plan.get("title") or "").strip()


def plan_tests(inv: InvestigationPaths, state: InvestigationState, plan: dict) -> list[str]:
    """Normalise `tests:` entries. `H1` alone means every criterion of H1."""
    out: list[str] = []
    raw = plan.get("tests") or []
    if isinstance(raw, str):
        raw = [raw]
    for t in raw:
        t = str(t).strip()
        if not t:
            continue
        if ":" in t:
            out.append(t)
            continue
        hv = hyp_view(inv, state, t)
        crits = list(hv.criteria) or []
        out += [f"{t}:{c}" for c in crits] if crits else [f"{t}:*"]
    return out


def exp_view(inv: InvestigationPaths, state: InvestigationState, name: str) -> ExpView:
    plan_path = inv.experiment_plan(name)
    has_plan = plan_path.exists()
    plan = _fm(plan_path) if has_plan else {}
    ev_dir = inv.evidence_dir(name)
    evidence = sorted(inv.rel(p) for p in ev_dir.rglob("*") if p.is_file()) if ev_dir.exists() else []
    verdicts = {v.criterion: v.label for v in state.verdicts_for(name)}
    tests = plan_tests(inv, state, plan)
    abandoned = str(plan.get("abandoned") or "")
    if abandoned:
        status = "abandoned"
    elif tests and all(t in verdicts for t in tests):
        status = "done"
    elif not tests and verdicts:
        status = "done"
    elif evidence:
        status = "run"
    else:
        status = "planned"
    return ExpView(name, plan, has_plan, tests, bool(plan.get("exploratory")), abandoned, evidence, verdicts, status)


def all_experiments(inv: InvestigationPaths, state: InvestigationState) -> list[ExpView]:
    names = set(inv.experiment_names()) | {v.experiment for v in state.verdicts}
    views = [exp_view(inv, state, n) for n in sorted(names, key=natural_key)]
    return [e for e in views if e.has_plan or e.evidence or e.verdicts]


def evidence_exists_for(inv: InvestigationPaths, state: InvestigationState, hid: str) -> bool:
    """Has any data been produced that bears on `hid`? After that, criteria changes are post-hoc."""
    for e in all_experiments(inv, state):
        if any(t.split(":")[0] == hid for t in list(e.tests) + list(e.verdicts)) and e.evidence:
            return True
    return False


# ------------------------------------------------------------------ questions

_BULLET_RE = re.compile(r"^\s*[-*]\s+(?:\[[ xX]\]\s+)?(.+?)\s*$")


def questions(inv: InvestigationPaths) -> list[str]:
    """Bullets in questions.md: parked questions, each routed to open questions on closure."""
    if not inv.questions.exists():
        return []
    _, body = split_frontmatter(inv.questions.read_text(encoding="utf-8"))
    return [m.group(1) for line in body.splitlines() if (m := _BULLET_RE.match(line))]


# ------------------------------------------------------------------ whose turn

def problem_changed(inv: InvestigationPaths, state: InvestigationState) -> bool:
    return bool(state.problem_sha256) and inv.problem.exists() and sha256_file(inv.problem) != state.problem_sha256


def next_action(inv: InvestigationPaths, state: InvestigationState) -> tuple[str, str, str]:
    """(who, command, sentence): whose turn it is, the exact command they type, and why.

    `who` is "researcher", "agent", or "nobody" (closed). Researcher commands are given in slash
    form; agent commands in `craft ...` form.
    """
    if state.tainted:
        return ("researcher", "/craft-resolve --note \"...\"",
                "the investigation is on integrity hold: " + ("; ".join(state.taint_reasons) or "a recorded file changed"))
    ph = state.phase
    if ph == Phase.FRAMING:
        return ("researcher", "/craft-approve",
                "the one-page problem statement awaits the researcher's reading and approval "
                "(the agent first fills it in and runs `craft validate problem`)")
    if ph == Phase.CLOSING:
        return ("researcher", "/craft-close",
                f"kill criterion {state.kill.criterion} was met, so no new evidence is accepted; the agent writes "
                "closure.md (anomalies -> open questions), then the researcher closes")
    if ph == Phase.CLOSED:
        return ("nobody", "", "closed and archived")
    if state.env.pending_proposal:
        return ("researcher", "/craft-approve",
                f"the agent proposed adding '{state.env.pending_proposal['package']}' to the locked environment; "
                "verdicts are halted until approved (or `/craft-reject --note`)")
    if problem_changed(inv, state):
        return ("researcher", "/craft-approve",
                "problem.md changed since the researcher approved it; the change is recorded once they read and approve it")
    hyps = [h for h in all_hypotheses(inv, state) if h.status != "dropped"]
    for h in hyps:
        if h.status == "in review" and h.rec.exhausted:
            last = h.rec.rounds[-1]
            return ("agent", f"craft review --hyp {h.id}",
                    f"{h.id}'s review reached the 2-round cap with {', '.join(last.blocking_open)} unresolved; change "
                    f"{h.id} genuinely, then `craft review --hyp {h.id}` starts a new review cycle")
    for h in hyps:
        if h.status == "in review":
            last = h.rec.rounds[-1]
            missing = [o for o in last.blocking_open if o not in last.responses]
            if missing:
                return ("agent", f"craft review respond {h.id}:{missing[0]} --pointer <doc#section> --note \"...\"",
                        f"{h.id} has open blocking objections ({', '.join(missing)}); change the design and answer each")
            return ("agent", "craft review", f"every blocking objection on {h.id} is answered; request the next round")
    ready = [h.id for h in hyps if h.status == "draft" and h.complete]
    if ready:
        return ("agent", "craft review", f"draft(s) {', '.join(ready)} are complete; request the independent review")
    running = [h for h in hyps if h.status == "registered" and h.untested]
    if running:
        what = "; ".join(f"{h.id} ({', '.join(h.untested)})" for h in running)
        return ("agent", "craft verdict <exp> --criterion <H:C> --evidence <file>",
                f"registered criteria still need evidence: {what}. Run the experiments, file verdicts, and propose follow-ups")
    if not hyps:
        return ("agent", "write hypotheses/H1.md",
                "no hypotheses yet: draft one (or several, or park one-line ideas) in hypotheses/")
    drafts = [h.id for h in hyps if h.status == "draft"]
    tail = f"; draft ideas parked: {', '.join(drafts)}" if drafts else ""
    return ("researcher", "/craft-close",
            "every registered hypothesis has its verdicts" + tail + ". The researcher picks what to pursue next "
            "(the agent drafts it), or closes the investigation")


def blocked_reason(inv: InvestigationPaths, state: InvestigationState) -> str:
    who, cmd, why = next_action(inv, state)
    if who == "nobody":
        return "Closed."
    return f"{why}. Waiting on the {who}: `{cmd}`."


# ------------------------------------------------------------------ board

def _short(text: str, n: int = 60) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def board_text(inv: InvestigationPaths, state: InvestigationState) -> str:
    who, cmd, why = next_action(inv, state)
    hold = " [INTEGRITY HOLD]" if state.tainted else ""
    lines = [f"- {state.id} — {state.phase.value}{hold}", f"    {why}."]
    if who != "nobody":
        lines.append(f"    Waiting on the {who}: {cmd}")
    if state.phase == Phase.FRAMING:
        return "\n".join(lines)
    hyps = all_hypotheses(inv, state)
    lines.append("    Hypotheses:" if hyps else "    Hypotheses: none yet")
    for h in hyps:
        status = h.status
        if status == "draft" and not h.complete:
            status = "draft (idea)"
        if status == "in review":
            status = f"in review (round {len(h.rec.rounds)}, open {', '.join(h.rec.open_blocking)})"
        crits = ", ".join(f"{c} {h.criteria_labels.get(c, '—')}" for c in h.criteria) if h.rec.registered_sha256 else ""
        flags = []
        if h.post_hoc:
            flags.append("criteria changed after registration (post-hoc)")
        elif h.changed_since_registration:
            flags.append("edited since registration")
        src = f"{h.origin}" + (f" <- {h.derived_from}" if h.derived_from else "")
        lines.append(f"      {h.id:<6} {status:<14} {_short(h.claim)}")
        detail = "; ".join(x for x in [crits, *flags, f"origin {src}"] if x)
        lines.append(f"             {detail}")
    exps = all_experiments(inv, state)
    if exps:
        lines.append("    Experiments:")
    for e in exps:
        tests = [t.replace(":*", " (no criteria yet)") for t in e.tests]
        what = "exploratory" if e.exploratory else ("tests " + ", ".join(tests) if tests else "")
        judged = ", ".join(f"{k} {v}" for k, v in e.verdicts.items())
        extra = "; ".join(x for x in [what, judged, f"{len(e.evidence)} evidence file(s)" if e.evidence else "",
                                       f"abandoned: {e.abandoned}" if e.abandoned else ""] if x)
        lines.append(f"      {e.name:<14} {e.status:<9} {extra}")
    qs = questions(inv)
    if qs:
        lines.append(f"    Open questions (questions.md): {len(qs)}")
        for q in qs[:5]:
            lines.append(f"      - {_short(q, 80)}")
    return "\n".join(lines)


def public(inv: InvestigationPaths, state: InvestigationState) -> dict:
    """Compact machine-readable view for `craft status --json`."""
    who, cmd, why = next_action(inv, state)
    return {
        "id": state.id,
        "phase": state.phase.value,
        "tainted": state.tainted,
        "env_version": state.env.version,
        "pending_env_proposal": bool(state.env.pending_proposal),
        "problem_changed": problem_changed(inv, state),
        "hypotheses": {
            h.id: {
                "status": h.status, "complete": h.complete, "rounds": len(h.rec.rounds),
                "cycles": len(h.rec.cycles), "open_blocking": h.rec.open_blocking, "exhausted": h.rec.exhausted,
                "registered_at": h.rec.registered_at, "criteria": h.criteria_labels, "post_hoc": h.post_hoc,
                "origin": h.origin, "derived_from": h.derived_from,
            } for h in all_hypotheses(inv, state)
        },
        "experiments": {e.name: {"status": e.status, "tests": e.tests, "verdicts": e.verdicts, "evidence": len(e.evidence)}
                        for e in all_experiments(inv, state)},
        "questions": questions(inv),
        "verdicts": [v.model_dump() for v in state.verdicts],
        "kill": state.kill.model_dump(),
        "next": {"who": who, "command": cmd, "why": why},
        "blocked": blocked_reason(inv, state),
    }
