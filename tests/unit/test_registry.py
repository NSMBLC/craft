import json

from craft import registry
from craft.paths import InvestigationPaths
from craft.state import InvestigationState, Phase, VerdictRef, new_state

HYP = """---
claim: A beats B.
criteria:
  - {name: C1, metric: gain, op: ">=", threshold: 1.5, conditions: c}
  - {name: C2, metric: lat, op: "<=", threshold: 1.2, conditions: c}
outcome_rule: {supported: s, refuted: r, inconclusive: i}
---
"""


def _inv(tmp_path):
    inv = InvestigationPaths(tmp_path)
    inv.hypotheses_dir.mkdir()
    return inv


def test_statuses_are_derived(tmp_path):
    inv = _inv(tmp_path)
    s = new_state("i", "t")
    s.phase = Phase.OPEN
    inv.hypothesis("H1").write_text(HYP)
    inv.hypothesis("H2").write_text("---\nclaim: an idea\n---\n")
    inv.hypothesis("H3").write_text("---\nclaim: gone\ndropped: superseded by H1\n---\n")
    views = {h.id: h for h in registry.all_hypotheses(inv, s)}
    assert views["H1"].status == "draft" and not views["H1"].complete
    assert views["H2"].status == "draft" and views["H3"].status == "dropped"
    # registration snapshot: criteria come from it, edits are detected
    reg = inv.registered("H1")
    reg.parent.mkdir(parents=True)
    reg.write_text(HYP)
    from craft.util import sha256_file
    s.hyp("H1").registered_sha256 = sha256_file(inv.hypothesis("H1"))
    assert registry.hyp_view(inv, s, "H1").status == "registered"
    inv.hypothesis("H1").write_text(HYP.replace("threshold: 1.5", "threshold: 1.3"))
    v = registry.hyp_view(inv, s, "H1")
    assert v.post_hoc and v.changed_since_registration and v.criteria["C1"]["threshold"] == 1.5
    inv.hypothesis("H1").write_text(HYP.replace("A beats B.", "A beats B clearly."))
    v = registry.hyp_view(inv, s, "H1")
    assert v.changed_since_registration and not v.post_hoc


def test_outcome_roll_up(tmp_path):
    inv = _inv(tmp_path)
    s = new_state("i", "t")
    inv.hypothesis("H1").write_text(HYP)
    (inv.hyp_review_dir("H1")).mkdir(parents=True)
    inv.registered("H1").write_text(HYP)
    s.hyp("H1").registered_sha256 = "x"

    def label(*pairs):
        s.verdicts = [VerdictRef(experiment="e", criterion=f"H1:{c}", label=lbl, file="f", when="w") for c, lbl in pairs]
        return registry.hyp_view(inv, s, "H1").status

    assert label(("C1", "supported")) == "registered"
    assert label(("C1", "supported"), ("C2", "supported")) == "supported"
    assert label(("C1", "supported"), ("C2", "inconclusive")) == "inconclusive"
    assert label(("C1", "refuted")) == "refuted"


def test_plan_tests_and_experiment_status(tmp_path):
    inv = _inv(tmp_path)
    s = new_state("i", "t")
    inv.hypothesis("H1").write_text(HYP)
    plan = inv.experiment_plan("e1")
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ndescription: d\ntests: [H1]\n---\n")
    e = registry.exp_view(inv, s, "e1")
    assert e.tests == ["H1:C1", "H1:C2"] and e.status == "planned"
    ev = inv.evidence_dir("e1") / "a.json"
    ev.parent.mkdir()
    ev.write_text("{}")
    assert registry.exp_view(inv, s, "e1").status == "run"
    s.verdicts = [VerdictRef(experiment="e1", criterion=c, label="supported", file="f", when="w") for c in ("H1:C1", "H1:C2")]
    assert registry.exp_view(inv, s, "e1").status == "done"
    plan.write_text("---\ndescription: d\ntests: [H1]\nabandoned: no GPU\n---\n")
    assert registry.exp_view(inv, s, "e1").status == "abandoned"


def test_questions_bullets(tmp_path):
    inv = _inv(tmp_path)
    inv.questions.write_text("# Q\n\nintro line\n- first?\n* second?\n- [ ] third?\n  - nested?\n")
    assert registry.questions(inv) == ["first?", "second?", "third?", "nested?"]


def test_v1_archived_state_still_loads(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({
        "id": "old", "topic": "t", "created": "2026-01-01T00:00:00+00:00", "phase": "executing",
        "review": {"rounds": [], "frozen_sha256": "abc"},
    }))
    st = InvestigationState.load(tmp_path)
    assert st.phase == Phase.OPEN and st.hypotheses == {}
