import pytest

from craft import registry
from craft.artifacts.hypothesis import is_idea
from craft.artifacts.verdict import extract, label_for, missing_fields
from craft.paths import InvestigationPaths
from craft.state import new_state
from craft.util import CraftError, read_doc


def test_idea_vs_draft(tmp_path):
    assert is_idea({"claim": "x", "origin": "agent", "derived_from": "lit:kim2024"})
    assert not is_idea({"claim": "x", "warrant": "because"})
    # the template a new investigation starts from is an empty draft, not an idea with content
    from importlib import resources
    tmpl = resources.files("craft.templates").joinpath("hypothesis.md").read_text().replace('claim: ""', "claim: y")
    p = tmp_path / "H1.md"
    p.write_text(tmpl)
    assert is_idea(read_doc(p)[0])


def test_questions_answered_forms(tmp_path):
    inv = InvestigationPaths(tmp_path)
    inv.questions.write_text("- open one?\n- [x] checked only?\n- done? answered: experiments/e/verdict-H1-C1.md\n"
                             "- also done? — answered by: lit:kim2024\n")
    qs = registry.parked_questions(inv)
    assert [(q.text, q.answered, q.pointer) for q in qs] == [
        ("open one?", False, ""), ("checked only?", True, ""),
        ("done?", True, "experiments/e/verdict-H1-C1.md"), ("also done?", True, "lit:kim2024")]
    assert registry.questions(inv) == ["open one?"]


def test_deterministic_extraction():
    m = extract({"metric": "k", "value": 3}, "k", "exact enumeration")
    assert m.source == "deterministic" and label_for(m, ">=", 3)[0] == "supported"
    assert label_for(m, ">", 3)[0] == "refuted"  # never inconclusive
    with pytest.raises(CraftError, match="values vary"):
        extract({"metric": "k", "values": [3, 4]}, "k", "exact enumeration")
    with pytest.raises(CraftError, match="interval"):
        extract({"metric": "k", "value": 3, "ci": [2, 4]}, "k", "exact enumeration")
    with pytest.raises(CraftError, match="uncertainty"):
        extract({"metric": "k", "value": 3}, "k")


def test_missing_fields_all_at_once():
    probs = missing_fields({"metric": "k", "value": 3}, "k", [], [])
    assert len(probs) == 3 and probs[0].startswith("uncertainty") and probs[1].startswith("seeds") and probs[2].startswith("data_id")
    assert missing_fields({"metric": "k", "values": [1, 2], "seeds": "1-200", "data_id": "d"}, "k", [], []) == []
    assert missing_fields({}, "k", ["1"], ["d"])[0].startswith("metric 'k'")


def test_unreadable_evidence_counts_as_bearing(tmp_path):
    inv = InvestigationPaths(tmp_path)
    inv.hypotheses_dir.mkdir()
    s = new_state("i", "t")
    inv.hypothesis("H1").write_text("---\nclaim: c\ncriteria:\n  - {name: C1, metric: gain, op: '>=', threshold: 1, conditions: c}\n---\n")
    d = inv.evidence_dir("e")
    d.mkdir(parents=True)
    (d / "k.json").write_text('{"metric": "pilot_loss", "values": [1, 2]}')
    assert registry.evidence_for(inv, s, "H1") == []
    (d / "raw.bin").write_bytes(b"\x00\x01")
    assert registry.evidence_for(inv, s, "H1") == ["experiments/e/evidence/raw.bin"]


def test_outcome_branch_that_points_elsewhere_is_flagged(tmp_path):
    from craft.artifacts.hypothesis import validate_hypothesis
    p = tmp_path / "H1.md"
    p.write_text("---\nclaim: c\noutcome_rule:\n  supported: every criterion passes\n  refuted: Branch (a) of the mapping in supported\n"
                 "  inconclusive: anything else\n---\n")
    found = [f for f in validate_hypothesis(p).findings if f.field == "outcome_rule.refuted"]
    assert found and found[0].severity == "warning" and "state the condition in words" in found[0].problem
