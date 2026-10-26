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

from .artifacts.hypothesis import criteria_table, is_idea, validate_hypothesis
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


# What review judges and registration fixes. Everything else in a hypothesis file (origin, derived_from,
# dropped, notes in the body) is provenance or commentary: editing it never touches the registration.
JUDGED_FIELDS = ("claim", "warrant", "criteria", "outcome_rule", "rivals", "predictions", "power")


def judged_signature(fm: dict) -> str:
    return json.dumps({k: fm.get(k) for k in JUDGED_FIELDS}, sort_keys=True, default=str)


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
    changed_since_registration: bool = False  # a judged field changed (provenance and notes do not count)
    idea: bool = False             # a claim only: parked, valid as an idea

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

    @property
    def outcome_rule(self) -> dict:
        rule = (self.registered_fm or self.fm).get("outcome_rule")
        return rule if isinstance(rule, dict) else {}

    @property
    def rule_is_mechanical(self) -> bool:
        """The registered rule says it is exactly CRAFT's roll-up, so the label *is* the rule's."""
        return self.outcome_rule.get("mechanical") is True

    def label_basis(self) -> str:
        """Where the hypothesis-level label comes from, said plainly next to the label."""
        if self.status not in OUTCOMES:
            return ""
        if self.rule_is_mechanical:
            return "by the registered outcome rule (mechanical)"
        text = str(self.outcome_rule.get(self.status) or "").strip()
        return (f"by CRAFT's roll-up of criterion labels, not the registered outcome rule, which is free text and "
                f"governs; it says {self.status} means: \"{text}\"")


def hyp_view(inv: InvestigationPaths, state: InvestigationState, hid: str) -> HypView:
    path = inv.hypothesis(hid)
    rec = state.hypotheses.get(hid) or HypothesisRecord()
    exists = path.exists()
    fm = _fm(path) if exists else {}
    complete = exists and validate_hypothesis(path).ok
    reg_fm = _fm(inv.registered(hid)) if rec.registered_sha256 and inv.registered(hid).exists() else {}
    v = HypView(hid, path, exists, fm, rec, "draft", complete, reg_fm, idea=exists and is_idea(fm))
    for vr in state.verdicts:
        h, _, c = vr.criterion.partition(":")
        if h == hid and c:
            v.criteria_labels[c] = vr.label
    if not exists or fm.get("dropped"):
        v.status = "dropped"
        return v
    if rec.registered_sha256:
        v.changed_since_registration = sha256_file(path) != rec.registered_sha256 and judged_signature(fm) != judged_signature(reg_fm)
        v.post_hoc = criteria_signature(fm) != criteria_signature(reg_fm)
        v.status = outcome(v) or "registered"
    elif rec.rounds and rec.open_blocking:
        v.status = "in review"
    return v


def outcome(v: HypView) -> str | None:
    """Mechanical roll-up of criterion labels: any refuted -> refuted; all supported -> supported;
    all judged otherwise -> inconclusive; not all judged -> None. It is the hypothesis's label only
    when the registered outcome rule says `mechanical: true`; otherwise it is shown with that caveat."""
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
    explored: list[str] = field(default_factory=list)  # files under exploratory/ (never evidence)

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
    ex_dir = inv.exploratory_dir(name)
    explored = sorted(inv.rel(p) for p in ex_dir.rglob("*") if p.is_file()) if ex_dir.exists() else []
    verdicts = {v.criterion: v.label for v in state.verdicts_for(name)}
    tests = plan_tests(inv, state, plan)
    abandoned = str(plan.get("abandoned") or "")
    if abandoned:
        status = "abandoned"
    elif tests and all(t in verdicts for t in tests):
        status = "done"
    elif not tests and verdicts:
        status = "done"
    elif evidence or (plan.get("exploratory") and explored):
        status = "run"  # an exploratory experiment has run once its exploratory/ area has output
    else:
        status = "planned"
    return ExpView(name, plan, has_plan, tests, bool(plan.get("exploratory")), abandoned, evidence, verdicts, status, explored)


def all_experiments(inv: InvestigationPaths, state: InvestigationState) -> list[ExpView]:
    names = set(inv.experiment_names()) | {v.experiment for v in state.verdicts}
    views = [exp_view(inv, state, n) for n in sorted(names, key=natural_key)]
    return [e for e in views if e.has_plan or e.evidence or e.verdicts or e.explored]


def not_tested_reason(inv: InvestigationPaths, state: InvestigationState, h: HypView,
                      exps: list[ExpView] | None = None) -> str:
    """Why a registered hypothesis with unjudged criteria is not pending work, or "" when it is.

    Deferred by the researcher's decision (`deferred: <reason>` in its file), or every experiment that
    tests it was abandoned. Either way it closes as an open question; planning a new experiment (or
    removing `deferred`) makes it pending again. A hypothesis with no experiment yet is pending work.
    """
    if h.status != "registered" or not h.untested:
        return ""
    if str(h.fm.get("deferred") or "").strip():
        return f"deferred: {str(h.fm['deferred']).strip()}"
    testing = [e for e in (exps if exps is not None else all_experiments(inv, state))
               if any(t.split(":")[0] == h.id for t in e.tests)]
    if testing and all(e.status == "abandoned" for e in testing):
        names = "; ".join(f"{e.name} ({e.abandoned})" for e in testing)
        return f"experiments abandoned: {names}"
    return ""


def evidence_for(inv: InvestigationPaths, state: InvestigationState, hid: str) -> list[str]:
    """Evidence files that bear on `hid`'s own criteria; once one exists, criteria changes are post-hoc.

    A file bears on it when a verdict on one of its criteria cites it, or when it reports a metric that
    the registered or the current version of `hid` judges (data seen before the criteria were fixed).
    Evidence that reports only other metrics (a kill-criterion pilot, another hypothesis) does not.
    A file that cannot be read counts as bearing: when in doubt, the record stays conservative.
    """
    from .artifacts.verdict import load_evidence

    hv = hyp_view(inv, state, hid)
    metrics = {str(c.get("metric")) for fm in (hv.registered_fm, hv.fm) for c in criteria_table(fm).values() if c.get("metric")}
    cited = set()
    for v in state.verdicts:
        if v.criterion.split(":")[0] == hid:
            vfile = inv.root / v.file
            vfm = split_frontmatter(vfile.read_text(encoding="utf-8"))[0] if vfile.exists() else {}
            cited |= {e.get("path") for e in vfm.get("evidence", []) if isinstance(e, dict)}
    out = []
    for e in all_experiments(inv, state):
        for rel in e.evidence:
            if rel in cited:
                out.append(rel)
                continue
            try:
                data = load_evidence(inv.root / rel)
            except (CraftError, ValueError, OSError):
                out.append(rel)
                continue
            if metrics & _reported_metrics(data):
                out.append(rel)
    return out


def unjudged_evidence(inv: InvestigationPaths, state: InvestigationState,
                      exps: list[ExpView] | None = None) -> dict[str, list[tuple[str, str]]]:
    """Criteria that have evidence but no verdict: "H1:C1" -> [(experiment, evidence path), ...].

    An evidence file counts for a criterion when its experiment's plan tests the criterion and the
    file reports the criterion's registered metric. "Not judged yet" is a different fact from "never
    tested", so the board, the kill message and closure name these criteria.
    """
    from .artifacts.verdict import load_evidence

    out: dict[str, list[tuple[str, str]]] = {}
    hyps: dict[str, HypView] = {}
    for e in exps if exps is not None else all_experiments(inv, state):
        if e.exploratory or e.status == "abandoned" or not e.evidence:
            continue
        reported = {}
        for rel in e.evidence:
            try:
                reported[rel] = _reported_metrics(load_evidence(inv.root / rel))
            except (CraftError, ValueError, OSError):
                reported[rel] = set()
        for key in e.tests:
            hid, _, cname = key.partition(":")
            if key in e.verdicts or cname == "*":
                continue
            hv = hyps.setdefault(hid, hyp_view(inv, state, hid))
            if not hv.rec.registered_sha256 or cname in hv.criteria_labels:
                continue
            metric = str(hv.criteria.get(cname, {}).get("metric") or "")
            files = [rel for rel, names in reported.items() if metric and metric in names]
            if files:
                out.setdefault(key, []).extend((e.name, rel) for rel in files)
    return out


def unjudged_text(found: dict[str, list[tuple[str, str]]]) -> str:
    return "; ".join(f"{k} ({', '.join(f'{exp}: {rel}' for exp, rel in v)})" for k, v in found.items())


def _reported_metrics(data: dict) -> set[str]:
    names = set()
    if isinstance(data.get("metrics"), dict):
        names |= {str(k) for k in data["metrics"]}
    if data.get("metric"):
        names.add(str(data["metric"]))
    for k, v in data.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            names.add(str(k))
        elif isinstance(v, list) and k.endswith("_values"):
            names.add(str(k)[: -len("_values")])
    return names


# ------------------------------------------------------------------ questions

_BULLET_RE = re.compile(r"^\s*[-*]\s+(?:\[([ xX])\]\s+)?(.+?)\s*$")
_ANSWERED_RE = re.compile(r"\s*[—–-]?\s*\banswered(?:\s+by)?\s*:\s*(.*)$", re.I)


@dataclass
class Question:
    text: str
    answered: bool = False
    pointer: str = ""  # what answered it: a verdict file, experiment, source (lit:<key>) or note


def parked_questions(inv: InvestigationPaths, state: InvestigationState | None = None) -> list[Question]:
    """Bullets in questions.md. `answered: <pointer>` (or a checked box) marks one answered, and so does a
    limitation recorded with `--question` (given `state`); on closure answered questions are recorded as
    answered, the rest as open questions."""
    if not inv.questions.exists():
        return []
    settled = {}
    for v in (state.verdicts if state is not None else []):
        for lim in v.limitations:
            if lim.get("question"):
                settled[lim["question"]] = inv.rel(inv.verdict_limitations(v.experiment, v.criterion))
    _, body = split_frontmatter(inv.questions.read_text(encoding="utf-8"))
    out = []
    for line in body.splitlines():
        m = _BULLET_RE.match(line)
        if not m:
            continue
        text, pointer = m.group(2), ""
        a = _ANSWERED_RE.search(text)
        if a:
            text, pointer = text[: a.start()].strip(), a.group(1).strip()
        q = Question(text, bool(a) or m.group(1) in ("x", "X"), pointer)
        if not q.answered and text in settled:
            q.answered, q.pointer = True, settled[text]
        out.append(q)
    return out


def questions(inv: InvestigationPaths, state: InvestigationState | None = None) -> list[str]:
    """The parked questions still open."""
    return [q.text for q in parked_questions(inv, state) if not q.answered]


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
        if found := unjudged_evidence(inv, state):
            return ("agent", "craft verdict <exp> --criterion <H:C> --evidence <file>",
                    f"kill criterion {state.kill.criterion} was met, so nothing new can run; evidence produced before it "
                    f"still has no verdict: {unjudged_text(found)}. Judge it, then the researcher closes")
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
    exps = all_experiments(inv, state)
    parked = {h.id: r for h in hyps if (r := not_tested_reason(inv, state, h, exps))}
    running = [h for h in hyps if h.status == "registered" and h.untested and h.id not in parked]
    if running:
        found = unjudged_evidence(inv, state, exps)
        what = "; ".join(f"{h.id} ({', '.join(h.untested)})" for h in running)
        have = f" Evidence without a verdict: {unjudged_text(found)}." if found else ""
        return ("agent", "craft verdict <exp> --criterion <H:C> --evidence <file>",
                f"registered criteria still need evidence: {what}.{have} Run the experiments, file verdicts, and propose follow-ups")
    if not hyps:
        return ("agent", "write hypotheses/H1.md",
                "no hypotheses yet: draft one (or several, or park one-line ideas) in hypotheses/")
    drafts = [h.id for h in hyps if h.status == "draft"]
    if not any(h.rec.registered_sha256 for h in hyps):
        ideas = [h.id for h in hyps if h.status == "draft" and h.idea]
        started = [h.id for h in hyps if h.status == "draft" and not h.idea]
        what = "; ".join(x for x in [f"drafts in progress: {', '.join(started)}" if started else "",
                                     f"ideas parked: {', '.join(ideas)}" if ideas else ""] if x)
        return ("researcher", "/craft-close",
                "no hypothesis is registered yet" + (f" ({what})" if what else "") + ". The researcher picks one for the "
                "agent to complete and send to review, or closes the investigation")
    tail = f"; draft ideas parked: {', '.join(drafts)}" if drafts else ""
    if parked:
        tail += "; not being tested (each closes as an open question): " + "; ".join(f"{k} ({v})" for k, v in parked.items())
    return ("researcher", "/craft-close",
            "every registered hypothesis being tested has its verdicts" + tail + ". The researcher picks what to "
            "pursue next (the agent drafts it), or closes the investigation")


def blocked_reason(inv: InvestigationPaths, state: InvestigationState) -> str:
    who, cmd, why = next_action(inv, state)
    if who == "nobody":
        return "Closed."
    return f"{why}. Waiting on the {who}: `{cmd}`."


# ------------------------------------------------------------------ board

def _short(text: str, n: int = 60) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def board_text(inv: InvestigationPaths, state: InvestigationState, typed=None) -> str:
    """`typed` rewrites a researcher command as it must be typed (adds --inv when several are open)."""
    who, cmd, why = next_action(inv, state)
    if who == "researcher" and typed is not None:
        cmd = typed(cmd)
    hold = " [INTEGRITY HOLD]" if state.tainted else ""
    lines = [f"- {state.id} — {state.phase.value}{hold}", f"    {why}."]
    if who != "nobody":
        lines.append(f"    Waiting on the {who}: {cmd}")
    if state.phase == Phase.FRAMING:
        return "\n".join(lines)
    hyps = all_hypotheses(inv, state)
    exps = all_experiments(inv, state)
    waiting = unjudged_evidence(inv, state, exps)
    lines.append("    Hypotheses:" if hyps else "    Hypotheses: none yet")
    for h in hyps:
        status = h.status
        parked = not_tested_reason(inv, state, h, exps)
        if parked:
            status = "registered (not being tested)"
        if status == "draft" and not h.complete:
            status = "draft (idea)" if h.idea else "draft (incomplete)"
        if status == "in review":
            status = f"in review (round {len(h.rec.rounds)}, open {', '.join(h.rec.open_blocking)})"
        limited = {v.criterion.split(":", 1)[1] for v in state.verdicts if v.limitations and v.criterion.startswith(f"{h.id}:")}
        crits = ", ".join(f"{c} {h.criteria_labels.get(c, 'evidence, not judged' if f'{h.id}:{c}' in waiting else '—')}"
                          + (" (limitation)" if c in limited else "")
                          for c in h.criteria) if h.rec.registered_sha256 else ""
        flags = []
        if parked:
            flags.append(f"{parked}; closes as an open question unless a new experiment is planned"
                         + (" or `deferred` is removed" if parked.startswith("deferred") else ""))
        from .artifacts.fields import unrecognised

        odd = [f for f, _ in unrecognised(h.fm, "hypothesis")]
        if odd:
            flags.append("fields CRAFT does not read: " + ", ".join(odd))
        if h.post_hoc:
            flags.append("criteria changed after registration (post-hoc)")
        elif h.changed_since_registration:
            flags.append("edited since registration")
        src = f"{h.origin}" + (f" <- {h.derived_from}" if h.derived_from else "")
        lines.append(f"      {h.id:<6} {status:<14} {_short(h.claim)}")
        detail = "; ".join(x for x in [crits, *flags, f"origin {src}"] if x)
        lines.append(f"             {detail}")
        if h.status in OUTCOMES and not h.rule_is_mechanical:  # the rule branch in full: it governs, the label is a roll-up
            lines.append(f"             label by CRAFT roll-up; the registered rule for {h.status} says: "
                         f"\"{' '.join(str(h.outcome_rule.get(h.status, '')).split())}\"")
    if exps:
        lines.append("    Experiments:")
    for e in exps:
        tests = [t.replace(":*", " (no criteria yet)") for t in e.tests]
        what = "exploratory" if e.exploratory else ("tests " + ", ".join(tests) if tests else "")
        lims = {v.criterion: len(v.limitations) for v in state.verdicts_for(e.name) if v.limitations}
        judged = ", ".join(f"{k} {v}" + (f" ({lims[k]} limitation{'s' if lims[k] > 1 else ''})" if k in lims else "")
                           for k, v in e.verdicts.items())
        from .artifacts.fields import unrecognised

        odd = [f for f, _ in unrecognised(e.plan, "plan")]
        unjudged = [k for k in waiting if any(x == e.name for x, _ in waiting[k])]
        extra = "; ".join(x for x in [what, judged, f"{len(e.evidence)} evidence file(s)" if e.evidence else "",
                                       "evidence, not judged: " + ", ".join(unjudged) if unjudged else "",
                                       "fields CRAFT does not read: " + ", ".join(odd) if odd else "",
                                       f"{len(e.explored)} exploratory file(s)" if e.explored else "",
                                       f"abandoned: {e.abandoned}" if e.abandoned else ""] if x)
        lines.append(f"      {e.name:<14} {e.status:<9} {extra}")
    if state.data:
        from .data import shown_hash

        lines.append("    Input data: " + "; ".join(f"{d} ({r['path']}, {shown_hash(r)})" for d, r in state.data.items()))
    pq = parked_questions(inv, state)
    qs = [q for q in pq if not q.answered]
    done = [q for q in pq if q.answered]
    if pq:
        tail = f" ({len(done)} answered)" if done else ""
        lines.append(f"    Open questions (questions.md): {len(qs)}{tail}")
        for q in qs[:5]:
            lines.append(f"      - {_short(q.text, 80)}")
        for q in done[:3]:
            lines.append(f"      - answered: {_short(q.text, 60)} <- {q.pointer or '(no pointer given)'}")
        if qs:
            lines.append("      (when one is answered, add `answered: <pointer>` to its bullet)")
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
                "label_basis": "rule" if h.rule_is_mechanical else ("roll-up" if h.status in OUTCOMES else None),
                "not_tested": not_tested_reason(inv, state, h) or None,
            } for h in all_hypotheses(inv, state)
        },
        "experiments": {e.name: {"status": e.status, "tests": e.tests, "verdicts": e.verdicts, "evidence": len(e.evidence),
                                 "exploratory": e.exploratory, "exploratory_files": len(e.explored)}
                        for e in all_experiments(inv, state)},
        "questions": questions(inv, state),
        "answered_questions": [{"question": q.text, "pointer": q.pointer} for q in parked_questions(inv, state) if q.answered],
        "verdicts": [v.model_dump() for v in state.verdicts],
        "kill": state.kill.model_dump(),
        "next": {"who": who, "command": cmd, "why": why},
        "blocked": blocked_reason(inv, state),
    }
