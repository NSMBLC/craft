"""experiments/<name>/plan.md: what an experiment tests, written before it runs.

Frontmatter: `description`, `tests` (list of `H1:C1`, or `H1` for all of H1's criteria),
optionally `exploratory: true`, `origin`, `derived_from`, `abandoned: <reason>`.
Status (planned / run / done / abandoned) is derived, never set by hand.
"""

from __future__ import annotations

from ..paths import InvestigationPaths
from ..state import InvestigationState
from ..util import read_doc
from .common import Validation, nonempty
from .fields import unrecognised


def validate_plan(inv: InvestigationPaths, state: InvestigationState, name: str) -> Validation:
    from .. import registry

    v = Validation(f"experiments/{name}/plan.md")
    fm, _ = read_doc(inv.experiment_plan(name))
    for field_, msg in unrecognised(fm, "plan"):
        v.warn(field_, msg)
    if not nonempty(fm.get("description")):
        v.error("description", "missing — one or two lines on what is run and how")
    view = registry.exp_view(inv, state, name)
    if view.exploratory and view.tests:
        v.error("tests", "an exploratory experiment tests nothing; drop `tests` or `exploratory`")
    if not view.exploratory and not view.tests:
        v.warn("tests", "tests no criterion: its evidence can only check kill criteria")
    for key in view.tests:
        hid, _, cname = key.partition(":")
        hv = registry.hyp_view(inv, state, hid)
        if not hv.exists:
            v.error("tests", f"{key}: no hypotheses/{hid}.md")
        elif cname == "*":
            v.error("tests", f"{hid} has no criteria yet; list them once the hypothesis is drafted")
        elif cname not in hv.criteria:
            v.error("tests", f"{key}: {hid} has no criterion {cname} ({', '.join(hv.criteria) or 'none'})")
    return v
