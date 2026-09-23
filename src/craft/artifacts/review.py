"""Review rounds: schemas, prescriptive-language lint, and round bookkeeping."""

from __future__ import annotations

import re

from ..util import CraftError

CATEGORIES = ["design", "statistics", "confound", "measurement", "scope", "reproducibility", "novelty", "other"]

ROUND1_SCHEMA = {
    "type": "object",
    "properties": {
        "no_blocking_objections": {"type": "boolean"},
        "summary": {"type": "string"},
        "objections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "severity": {"type": "string", "enum": ["blocking", "advisory"]},
                    "target": {
                        "type": "object",
                        "properties": {"document": {"type": "string"}, "section": {"type": "string"}},
                        "required": ["document", "section"],
                    },
                    "statement": {"type": "string"},
                    "adequate_answer": {"type": "string"},
                },
                "required": ["id", "category", "severity", "target", "statement", "adequate_answer"],
            },
        },
    },
    "required": ["no_blocking_objections", "objections", "summary"],
}

ROUND2_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "judgements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "decision": {"type": "string", "enum": ["accepted", "unresolved"]},
                    "reason": {"type": "string"},
                },
                "required": ["id", "decision", "reason"],
            },
        },
    },
    "required": ["judgements", "summary"],
}

PRESCRIPTIVE_RE = re.compile(
    r"\b(you should|we recommend|recommend(ed)? (that|using)|instead,? use|consider using|fix (this )?by|"
    r"the authors should|should (be )?(use|add|adopt|switch|replace))\b",
    re.I,
)


def check_round1(data: dict) -> list[str]:
    """Structural + etiquette problems in a round-1 review. Empty list = acceptable."""
    problems = []
    if not isinstance(data, dict):
        return ["review is not a JSON object"]
    for k in ("no_blocking_objections", "objections", "summary"):
        if k not in data:
            problems.append(f"missing field {k}")
    ids = set()
    for o in data.get("objections", []):
        oid = o.get("id", "?")
        if oid in ids:
            problems.append(f"duplicate objection id {oid}")
        ids.add(oid)
        for k in ("category", "severity", "target", "statement", "adequate_answer"):
            if k not in o:
                problems.append(f"objection {oid} missing {k}")
        if o.get("severity") not in ("blocking", "advisory"):
            problems.append(f"objection {oid} has invalid severity")
        tgt = o.get("target") or {}
        if not tgt.get("document") or not tgt.get("section"):
            problems.append(f"objection {oid} does not target a document and section")
        text = f"{o.get('statement', '')} {o.get('adequate_answer', '')}"
        m = PRESCRIPTIVE_RE.search(text)
        if m:
            problems.append(f"objection {oid} prescribes a fix ('{m.group(0)}'); finding is the referee's job, fixing is the author's")
    blocking = [o for o in data.get("objections", []) if o.get("severity") == "blocking"]
    if data.get("no_blocking_objections") and blocking:
        problems.append("no_blocking_objections is true but blocking objections are listed")
    if data.get("no_blocking_objections") is False and not blocking:
        problems.append("no_blocking_objections is false but no blocking objection is listed")
    return problems


def check_round2(data: dict, expected_ids: list[str]) -> list[str]:
    problems = []
    if not isinstance(data, dict) or "judgements" not in data:
        return ["round-2 review lacks judgements"]
    seen = {}
    for j in data["judgements"]:
        if j.get("decision") not in ("accepted", "unresolved"):
            problems.append(f"judgement {j.get('id')} has invalid decision")
        seen[j.get("id")] = j
        m = PRESCRIPTIVE_RE.search(j.get("reason", ""))
        if m:
            problems.append(f"judgement {j.get('id')} prescribes a fix ('{m.group(0)}')")
    for oid in expected_ids:
        if oid not in seen:
            problems.append(f"no judgement for blocking objection {oid}")
    return problems


def ensure_responses(open_ids: list[str], responses: dict[str, dict]) -> None:
    missing = [i for i in open_ids if i not in responses]
    if missing:
        raise CraftError(
            "every blocking objection must be answered before the next round: missing responses for "
            + ", ".join(missing)
            + ". Use `craft review respond <id> --pointer <doc#section> --note ...`."
        )
