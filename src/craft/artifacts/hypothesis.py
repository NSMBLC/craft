"""hypotheses/<id>.md: one pre-registration document per hypothesis (Journey 3).

Registered (snapshotted and hashed) when review concludes clean; the file itself stays editable.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..util import read_doc
from .common import Validation, nonempty
from .fields import unrecognised
from .verdict import JUDGED_ON, judging_problems

OPS = {"<", "<=", ">", ">=", "==", "!="}
REQUIRED_OUTCOMES = ("supported", "refuted", "inconclusive")
_JUDGING_WORDS = re.compile(r"\b(?:upper|lower) (?:bound|end|limit)\b|\bpoint estimate\b", re.I)
_WHOLE_INTERVAL = re.compile(r"\b(?:whole|entire|full)\b[^.;]{0,20}\binterval\b|\binterval lies\b", re.I)
_METHOD_WORDS = re.compile(r"\bbootstrap|\bpermutation|\bre-?draws?\b|\bresampl|\border[- ]statistic|\bquantile interval\b"
                           r"|\bwilson\b|\bclopper|\bexact binomial\b|\bjackknife\b", re.I)


def validate_hypothesis(path: Path, drafting: bool = True) -> Validation:
    """`drafting` False for a registered hypothesis: hints about how to write a criterion are left out there,
    because acting on them would change a registered criterion."""
    v = Validation(f"hypotheses/{path.name}")
    fm, body = read_doc(path)
    for field_, msg in unrecognised(fm, "hypothesis"):
        v.warn(field_, msg)

    claim = fm.get("claim")
    if not nonempty(claim):
        v.error("claim", "missing — one falsifiable claim")
    else:
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", str(claim).strip()) if s]
        if len(sentences) > 1:
            v.error("claim", f"{len(sentences)} sentences; state exactly one falsifiable claim")
        if re.search(r"\b(may|might|could|possibly|perhaps)\b", str(claim), re.I):
            v.warn("claim", "hedged wording (may/might/could) weakens falsifiability")

    if not nonempty(fm.get("warrant")):
        v.error("warrant", "missing — explain why the planned evidence bears on the claim")

    criteria = fm.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        v.error("criteria", "missing — at least one row with name, metric, op, threshold, conditions")
    else:
        names = set()
        for i, c in enumerate(criteria):
            if not isinstance(c, dict):
                v.error(f"criteria[{i}]", "each criterion is a mapping")
                continue
            for key in ("name", "metric", "op", "threshold", "conditions"):
                if not nonempty(c.get(key)) and c.get(key) is None:
                    v.error(f"criteria[{i}].{key}", "missing")
            if c.get("op") is not None and c.get("op") not in OPS:
                v.error(f"criteria[{i}].op", f"must be one of {sorted(OPS)}")
            if c.get("threshold") is not None and not isinstance(c.get("threshold"), (int, float)):
                v.error(f"criteria[{i}].threshold", "must be a number")
            if "deterministic" in c and not nonempty(c.get("deterministic")):
                v.error(f"criteria[{i}].deterministic", "say why the metric has no spread (e.g. exact enumeration on fixed inputs), or remove it")
            for field_, msg in judging_problems(c):
                v.error(f"criteria[{i}].{field_}", msg)
            if drafting and c.get("judged_on") is None and not c.get("deterministic"):
                rule = fm.get("outcome_rule") if isinstance(fm.get("outcome_rule"), dict) else {}
                texts = [c.get("conditions"), c.get("notes")]  # the rule's branches only where they name this criterion
                texts += [b for b in rule.values() if isinstance(b, str)
                          and (len(criteria) == 1 or re.search(rf"\b{re.escape(str(c.get('name')))}\b", b))]
                text = " ".join(str(x or "") for x in texts)
                said = _JUDGING_WORDS.search(text)
                if said and not _WHOLE_INTERVAL.search(text):  # a bound that only picks what is reported is fine
                    v.warn(f"criteria[{i}].judged_on", f"the text speaks of the {said.group(0).lower()}, but "
                           f"{c.get('name') or 'this criterion'} is judged on its whole interval; set `judged_on:` "
                           f"({', '.join(JUDGED_ON)}) so CRAFT judges it as written. `judged_on: interval` states the "
                           "default and never touches a registration")
            if drafting and not c.get("deterministic") and not c.get("interval_method"):
                named = _METHOD_WORDS.search(" ".join(str(c.get(k) or "") for k in ("conditions", "notes")))
                if named:
                    v.warn(f"criteria[{i}].interval_method", f"the conditions name an interval method ({named.group(0)}...); "
                           "state it as `interval_method:` so the verdict checks the evidence used it (on a registered "
                           "criterion this is a criterion change)")
            if c.get("name") in names:
                v.error(f"criteria[{i}].name", "duplicate criterion name")
            names.add(c.get("name"))

    outcome = fm.get("outcome_rule")
    if not isinstance(outcome, dict):
        v.error("outcome_rule", "missing — map every outcome to supported / refuted / inconclusive")
    else:
        for k in REQUIRED_OUTCOMES:
            if not nonempty(outcome.get(k)):
                v.error(f"outcome_rule.{k}", "missing")
            elif re.search(r"\b(branch|see|as (?:in|per|above|below)|mapping in)\b", str(outcome.get(k)), re.I):
                v.warn(f"outcome_rule.{k}", "refers elsewhere; state the condition in words, because the board and "
                       "memory quote this branch next to the label")
        if "mechanical" in outcome and not isinstance(outcome.get("mechanical"), bool):
            v.error("outcome_rule.mechanical", "true or false: true says the rule is exactly CRAFT's roll-up "
                    "(all criteria supported -> supported; any refuted -> refuted; otherwise inconclusive)")

    rivals = fm.get("rivals")
    if not isinstance(rivals, list) or len(rivals) < 2:
        n = len(rivals) if isinstance(rivals, list) else 0
        v.error("rivals", f"{n} rival explanation(s); at least two are required, each with the design feature that discriminates it")
    else:
        for i, r in enumerate(rivals):
            if not isinstance(r, dict) or not nonempty(r.get("explanation")):
                v.error(f"rivals[{i}].explanation", "missing")
            if not isinstance(r, dict) or not nonempty(r.get("discriminator")):
                v.error(f"rivals[{i}].discriminator", "missing — which design feature rules this rival out?")

    pred = fm.get("predictions")
    if not isinstance(pred, dict):
        v.error("predictions", "missing — what the evidence looks like if the claim is true, and if false")
    else:
        for k in ("if_true", "if_false"):
            if not nonempty(pred.get(k)):
                v.error(f"predictions.{k}", "missing")

    power = fm.get("power")
    if not isinstance(power, dict):
        v.error("power", "missing — show the planned runs can detect the effect claimed")
    else:
        for k in ("effect_size", "n_runs", "method", "detectable"):
            if power.get(k) is None or (isinstance(power.get(k), str) and not power.get(k).strip()):
                v.error(f"power.{k}", "missing")
        if power.get("detectable") is False:
            v.error("power.detectable", "the planned runs cannot detect the claimed effect; change the design")
    return v


DESIGN_FIELDS = ("warrant", "criteria", "outcome_rule", "rivals", "predictions", "power")
_LABEL_KEYS = {"name", "op"}  # template defaults, not content


def _filled(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, dict):
        return any(_filled(x) for k, x in v.items() if k not in _LABEL_KEYS)
    if isinstance(v, list):
        return any(_filled(x) for x in v)
    return v is not None


def is_idea(fm: dict) -> bool:
    """A parked idea: a claim and nothing of the design yet. Valid as an idea; review needs a full draft."""
    return nonempty(fm.get("claim")) and not any(_filled(fm.get(k)) for k in DESIGN_FIELDS)


def criteria_table(fm: dict) -> dict[str, dict]:
    return {c["name"]: c for c in (fm.get("criteria") or []) if isinstance(c, dict) and c.get("name")}
