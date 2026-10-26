"""The fields CRAFT reads in hypotheses and plans. Anything else is flagged, never silently ignored:
a field CRAFT does not read looks like recorded intent while doing nothing."""

from __future__ import annotations

HYPOTHESIS_FIELDS = {"claim", "origin", "derived_from", "warrant", "criteria", "outcome_rule", "rivals",
                     "predictions", "power", "dropped", "deferred", "notes"}
CRITERION_FIELDS = {"name", "metric", "op", "threshold", "conditions", "deterministic", "unit", "notes"}
OUTCOME_RULE_FIELDS = {"supported", "refuted", "inconclusive", "mechanical"}
PLAN_FIELDS = {"description", "title", "tests", "exploratory", "origin", "derived_from", "abandoned", "notes"}

# Fields CRAFT once read and no longer does, with what replaced them.
RETIRED = {
    "waits_on": "was removed: CRAFT works out what blocks a hypothesis or experiment itself (review, registration, "
                "kill criteria, experiment output); write any intended order as prose in the body",
}


def unrecognised(fm: dict, kind: str) -> list[tuple[str, str]]:
    """(field, message) for each field in a hypothesis or plan frontmatter that CRAFT does not read."""
    known = HYPOTHESIS_FIELDS if kind == "hypothesis" else PLAN_FIELDS
    out = [(k, RETIRED.get(k, "is not a field CRAFT reads (`craft glossary` lists the words it uses)"))
           for k in fm if k not in known]
    if kind == "hypothesis":
        for c in fm.get("criteria") or []:
            if isinstance(c, dict):
                out += [(f"criteria[{c.get('name', '?')}].{k}", RETIRED.get(k, "is not a criterion field CRAFT reads"))
                        for k in c if k not in CRITERION_FIELDS]
        rule = fm.get("outcome_rule")
        if isinstance(rule, dict):
            out += [(f"outcome_rule.{k}", "is not an outcome-rule field CRAFT reads") for k in rule if k not in OUTCOME_RULE_FIELDS]
    return out
