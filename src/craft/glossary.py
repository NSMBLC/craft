"""The words CRAFT uses, one line each: what it means, and what happens to it at closure.

The board, the messages and the playbook use exactly these words. `craft glossary [term]` and
`/craft-glossary` print them.
"""

from __future__ import annotations

from .util import CraftError

# (group, term, meaning, at closure)
GLOSSARY: list[tuple[str, str, str, str]] = [
    ("Hypothesis", "idea", "a hypothesis file with only a claim; parked, valid as an idea", "open question"),
    ("Hypothesis", "draft", "being written; not yet reviewed, not binding", "open question"),
    ("Hypothesis", "in review", "the referee left blocking objections; they are answered by changing the design", "open question"),
    ("Hypothesis", "registered", "passed review: its criteria are binding and evidence may be produced for it",
     "open question for each criterion never judged"),
    ("Hypothesis", "not being tested", "registered, but deferred by the researcher or every experiment testing it was abandoned",
     "open question, with the reason"),
    ("Hypothesis", "supported / refuted / inconclusive", "the label of a judged criterion, from its 95% interval against the "
     "registered threshold (whole interval passes / whole interval fails / spans it); a hypothesis's label rolls these up",
     "findings / refuted / open questions, one entry per criterion"),
    ("Experiment", "planned", "plan.md written, no output yet", "open question (planned but never run)"),
    ("Experiment", "run", "has evidence (an exploratory one: has output in exploratory/), not every tested criterion judged",
     "open question (run but not judged); exploratory: exploratory work"),
    ("Experiment", "done", "every criterion it tests has a verdict", "its verdicts are routed"),
    ("Experiment", "exploratory", "an experiment whose output can inform designs but never backs a criterion",
     "exploratory work, if it ran"),
    ("Stopping", "dropped", "a hypothesis no longer worth asking (`dropped: <reason>` in its file)", "nothing in memory; kept in the archive"),
    ("Stopping", "deferred", "a registered hypothesis held back by the researcher's decision; still open (`deferred: <reason>`)",
     "open question, with the reason"),
    ("Stopping", "abandoned", "an experiment stopped (`abandoned: <reason>` in its plan)", "nothing of its own; kept in the archive"),
    ("Fixing the record", "limitation", "found after a verdict: what it does not show (`craft limitation`); the label never changes",
     "travels with the verdict's memory entry"),
    ("Fixing the record", "correction", "the researcher's correction of a memory entry (`/craft-correct`); the entry stays as written",
     "already in memory; shown wherever the entry is"),
    ("Fixing the record", "answered", "a parked question settled, with what settled it (`answered: <pointer>` on its bullet)",
     "answered question"),
    ("Fixing the record", "post-hoc", "a criterion changed after registration; the verdict keeps the pre-registered label and says "
     "what the changed one would conclude", "tagged post_hoc"),
    ("Declared in files", "deterministic", "a criterion whose metric has no run-to-run spread, declared before review; judged on one value",
     "as its label"),
    ("Declared in files", "mechanical", "an outcome rule that is exactly CRAFT's roll-up (all supported, any refuted, else "
     "inconclusive); the label is then the rule's", "as its label"),
    ("Declared in files", "origin / derived_from", "who proposed it, and the verdict, experiment, source or question that prompted it; "
     "editing them never touches a registration", "kept on the memory entry"),
    ("Records and holds", "kill criterion", "a condition in problem.md under which the question is dead; met, it halts everything",
     "open question (killed by ...)"),
    ("Records and holds", "recorded data", "input data recorded by hash (`craft data add`); a change is held for the researcher",
     "its hash stays with each verdict"),
    ("Records and holds", "integrity hold", "a recorded file changed outside `craft`; work stops until the researcher types "
     "`/craft-resolve`", "closing is refused while it lasts"),
]


def glossary_text(term: str | None = None) -> str:
    rows = GLOSSARY
    if term:
        t = term.strip().lower()
        rows = [r for r in GLOSSARY if t in r[1].lower()]
        if not rows:
            raise CraftError(f"no glossary entry for '{term}' (entries: {', '.join(r[1] for r in GLOSSARY)})")
    lines, group = [], None
    for g, name, meaning, closure in rows:
        if g != group:
            lines.append(f"{g}:")
            group = g
        lines.append(f"  {name}: {meaning}. At closure: {closure}.")
    return "\n".join(lines)
