"""problem.md: the Journey 1 gate artifact.

Required shape (frontmatter):
  studying, to_find_out, so_that.reader, so_that.understands, cost_of_not_answering,
  kill_criteria[] (each: id, condition; optionally metric/op/value for mechanical checks, and
    `from: [H1:C1, ...]` to judge it from those recorded verdicts, with `of: point|ci_low|ci_high` and
    `combine: all|any`),
  memory_acknowledgements[] (filled by `craft new`).
Body: at most `limits.problem_max_words` words (one page).
"""

from __future__ import annotations

from pathlib import Path

from ..util import read_doc, word_count
from .common import Validation, looks_weak, nonempty

OPS = {"<", "<=", ">", ">=", "==", "!="}
KILL_OF = ("point", "ci_low", "ci_high")
KILL_COMBINE = ("all", "any")


def validate_problem(path: Path, max_words: int = 600) -> Validation:
    v = Validation("problem.md")
    fm, body = read_doc(path)

    for key in ("studying", "to_find_out", "cost_of_not_answering"):
        if not nonempty(fm.get(key)):
            v.error(key, "missing — the question needs the three-clause shape plus the cost of leaving it unanswered")
    so_that = fm.get("so_that") or {}
    if not isinstance(so_that, dict):
        v.error("so_that", "must be a mapping with `reader` and `understands`")
        so_that = {}
    reader = so_that.get("reader")
    if not nonempty(reader):
        v.error("so_that.reader", "name the reader who changes their mind if this is answered")
    else:
        weak = looks_weak(str(reader))
        if weak:
            v.error("so_that.reader", f"'{weak}' is not a named reader; who specifically acts differently?")
    if not nonempty(so_that.get("understands")):
        v.error("so_that.understands", "state what the named reader will understand or do differently")
    for key in ("to_find_out", "cost_of_not_answering"):
        weak = looks_weak(str(fm.get(key, "")))
        if weak:
            v.error(key, f"'{weak}' is not an acceptable answer; be concrete")

    kills = fm.get("kill_criteria")
    if not nonempty(kills) or not isinstance(kills, list):
        v.error("kill_criteria", "missing — state at least one condition under which this investigation is abandoned early")
    else:
        for i, k in enumerate(kills):
            if not isinstance(k, dict):
                v.error(f"kill_criteria[{i}]", "each kill criterion is a mapping with `id` and `condition`")
                continue
            if not nonempty(k.get("id")):
                v.error(f"kill_criteria[{i}].id", "missing id (e.g. K1)")
            if not nonempty(k.get("condition")):
                v.error(f"kill_criteria[{i}].condition", "missing human-readable condition")
            structured = [k.get("metric"), k.get("op"), k.get("value")]
            if any(s is not None for s in structured):
                if not all(s is not None for s in structured):
                    v.error(f"kill_criteria[{i}]", "metric/op/value must be given together for a mechanically checkable criterion")
                elif k.get("op") not in OPS:
                    v.error(f"kill_criteria[{i}].op", f"op must be one of {sorted(OPS)}")
            else:
                v.warn(f"kill_criteria[{i}]", "no metric/op/value: this criterion cannot be checked mechanically by `craft verdict`")
            if k.get("from") is not None:
                src = k.get("from")
                if not isinstance(src, list) or not src or not all(isinstance(x, str) and x.count(":") in (1, 2) for x in src):
                    v.error(f"kill_criteria[{i}].from", "a list of recorded criteria to judge it from, e.g. [H1:C1, H2:C1] "
                                                        "(or exp-a:H1:C1 when several experiments judged one)")
                if any(s is None for s in structured):
                    v.error(f"kill_criteria[{i}].from", "needs metric/op/value: the value each cited verdict is compared with")
            if k.get("of", "point") not in KILL_OF:
                v.error(f"kill_criteria[{i}].of", f"which recorded value is compared: one of {', '.join(KILL_OF)}")
            if k.get("combine", "all") not in KILL_COMBINE:
                v.error(f"kill_criteria[{i}].combine", "`all` (met when every cited result meets it) or `any` (when one does)")

    wc = word_count(body)
    if wc == 0:
        v.error("body", "the one-page prose statement is empty")
    elif wc > max_words:
        v.error("body", f"{wc} words exceeds the one-page limit of {max_words}; the researcher reads this in three minutes")
    return v


def kill_criteria(fm: dict) -> list[dict]:
    out = []
    for k in fm.get("kill_criteria") or []:
        if isinstance(k, dict) and all(k.get(x) is not None for x in ("metric", "op", "value")):
            out.append(k)
    return out
