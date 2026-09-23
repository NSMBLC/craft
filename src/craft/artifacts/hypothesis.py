"""hypothesis.md: the pre-registration document (Journey 3). Freezes after review."""

from __future__ import annotations

import re
from pathlib import Path

from ..util import read_doc
from .common import Validation, nonempty

OPS = {"<", "<=", ">", ">=", "==", "!="}
REQUIRED_OUTCOMES = ("supported", "refuted", "inconclusive")


def validate_hypothesis(path: Path) -> Validation:
    v = Validation("hypothesis.md")
    fm, body = read_doc(path)

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


def criteria_table(fm: dict) -> dict[str, dict]:
    return {c["name"]: c for c in (fm.get("criteria") or []) if isinstance(c, dict) and c.get("name")}
