"""Deterministic referee scripts for the acceptance arc."""

CYCLE_1 = {
    "1": {
        "no_blocking_objections": False,
        "summary": "Two blocking design flaws and one advisory note.",
        "objections": [
            {
                "id": "O1", "category": "design", "severity": "blocking",
                "target": {"document": "hypothesis.md", "section": "criteria"},
                "statement": "The proposed method's hyperparameters are tuned on a 40-trial budget while the baseline is run at defaults; the criterion C1 conditions do not equalise tuning effort, so any advantage is confounded with tuning attention.",
                "adequate_answer": "The conditions of every criterion state an equal tuning budget for method and baseline, and the rival explanations include tuning asymmetry with a discriminator that the design actually implements.",
            },
            {
                "id": "O2", "category": "statistics", "severity": "blocking",
                "target": {"document": "hypothesis.md", "section": "power"},
                "statement": "The power section asserts detectability of a 1.5 effect with 5 runs without a variance estimate; nothing shows 5 runs suffice.",
                "adequate_answer": "A variance estimate from pilot data or literature and a computation showing the planned runs detect the claimed effect at the stated confidence.",
            },
            {
                "id": "A1", "category": "scope", "severity": "advisory",
                "target": {"document": "problem.md", "section": "so_that"},
                "statement": "The named reader is plausible but the cost of not answering is stated in months rather than in a decision the reader would take.",
                "adequate_answer": "A decision the reader would take differently.",
            },
        ],
    },
    "2": {
        "summary": "O1 fixed in the design; O2 answered by assertion only.",
        "judgements": [
            {"id": "O1", "decision": "accepted", "reason": "Criteria conditions now fix an equal 40-trial tuning budget for both arms and a rival with a real discriminator was added."},
            {"id": "O2", "decision": "unresolved", "reason": "The response asserts the variance is negligible; no estimate or computation was added to the power section."},
        ],
    },
}

CYCLE_2 = {
    "1": {
        "no_blocking_objections": True,
        "summary": "The design is sound; two advisory notes.",
        "objections": [
            {"id": "A1", "category": "scope", "severity": "advisory",
             "target": {"document": "problem.md", "section": "cost_of_not_answering"},
             "statement": "The cost is stated as a delay rather than a decision.",
             "adequate_answer": "A decision the reader would take differently."},
            {"id": "A2", "category": "reproducibility", "severity": "advisory",
             "target": {"document": "hypothesis.md", "section": "criteria"},
             "statement": "Seeds are named but the data snapshot identifier is not fixed in the conditions.",
             "adequate_answer": "A data snapshot identifier in the conditions."},
        ],
    }
}

PRESCRIPTIVE = {
    "1": {
        "no_blocking_objections": False, "summary": "x",
        "objections": [{"id": "O1", "category": "design", "severity": "blocking",
                        "target": {"document": "hypothesis.md", "section": "criteria"},
                        "statement": "Tuning is asymmetric. You should use equal budgets.",
                        "adequate_answer": "Equal budgets."}],
    },
    "2": {"summary": "x", "judgements": []},
}
