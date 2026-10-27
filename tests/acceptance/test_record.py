"""Journey 9: keeping the record true. Each test builds its own small programme."""

from __future__ import annotations

import json
import re
import time

import pytest

from craft.util import read_jsonl, split_frontmatter

from ..conftest import Craft
from .fake_referee import CYCLE_2
from .test_arc import HYP_FIXED_O2, PROBLEM_OK

PROBLEM = re.sub(r"memory_acknowledgements:.*?(?=\n---\n)", "memory_acknowledgements: []", PROBLEM_OK, flags=re.S)


def typed(c: Craft, prompt: str, session: str = "t") -> str:
    return c.hook_event("user-prompt-submit", prompt=prompt, hook_event_name="UserPromptSubmit", session_id=session).out


def open_inv(c: Craft, inv: str = "inv-001", hyp: str = HYP_FIXED_O2, problem: str = PROBLEM) -> str:
    """A framed, approved investigation whose H1 is registered by a clean review."""
    assert c("new", inv, "--topic", "does method A's accuracy advantage hold on larger inputs").code == 0
    c.write(f"investigations/{inv}/problem.md", problem.replace("id: inv-001", f"id: {inv}"))
    assert "Approved" in typed(c, f"/craft-approve --inv {inv}")
    c.write(f"investigations/{inv}/hypotheses/H1.md", hyp)
    script = c.root.parent / "cycle2.json"
    script.write_text(json.dumps(CYCLE_2))
    r = c("review", "--inv", inv, env={"CRAFT_REFEREE_BACKEND": "fake", "CRAFT_FAKE_REFEREE": str(script)})
    assert "H1 is now REGISTERED" in r.out, r.text
    time.sleep(1.01)  # evidence must postdate the registration (second resolution)
    return inv


def ev(c: Craft, rel: str, metric: str, values=None, **extra) -> str:
    body = {"metric": metric, "seeds": [1, 2, 3, 4, 5], "data_id": "corpus-2026-09-snapshot", **extra}
    if values is not None:
        body["values"] = values
    return str(c.write(rel, json.dumps(body)))


def plan(c: Craft, inv: str, exp: str, front: str) -> None:
    c.write(f"investigations/{inv}/experiments/{exp}/plan.md", f"---\n{front}\n---\n")


def board(c: Craft, inv: str = "inv-001") -> dict:
    return json.loads(c("status", "--json").out)[inv]


def close(c: Craft, inv: str = "inv-001") -> str:
    out = typed(c, f"/craft-close --inv {inv}")
    assert "Closed." in out, out
    return out


def memory(c: Craft, kind: str) -> list[dict]:
    names = {"finding": "findings", "refuted": "refuted", "open": "open-questions",
             "answered": "answered-questions", "exploratory": "exploratory"}
    return read_jsonl(c.root / "memory" / f"{names[kind]}.jsonl")


@pytest.mark.checkpoint("9.1")
def test_exploratory_work_that_ran_is_recorded_as_run(programme: Craft):
    c = programme
    inv = open_inv(c)
    plan(c, inv, "sweep", "description: ring vs complete circuit, pick by the 2x rule\nexploratory: true")
    plan(c, inv, "never", "description: a sweep nobody ran\nexploratory: true")
    assert board(c)["experiments"]["sweep"]["status"] == "planned"
    c.write(f"investigations/{inv}/experiments/sweep/exploratory/results.json", "{}")
    b = board(c)
    assert b["experiments"]["sweep"]["status"] == "run" and b["experiments"]["never"]["status"] == "planned"
    assert "exploratory work recorded: sweep" in close(c)
    xs = memory(c, "exploratory")
    assert len(xs) == 1 and "sweep" in xs[0]["summary"] and xs[0]["files"][0].startswith("archive/inv-001/")
    qs = [q["question"] for q in memory(c, "open")]
    assert any("never was planned but never run" in q for q in qs) and not any("experiment sweep" in q for q in qs)


@pytest.mark.checkpoint("9.2")
def test_answered_questions_are_recorded_as_answered(programme: Craft):
    c = programme
    inv = open_inv(c)
    c.write(f"investigations/{inv}/questions.md",
            "# Questions\n- does the effect survive transpilation? answered: experiments/exp1/plan.md\n"
            "- is the gain driven by one crisis period?\n")
    plan(c, inv, "exp1", "description: d\ntests: [H1:C1]")
    b = board(c)
    assert b["questions"] == ["is the gain driven by one crisis period?"]
    assert b["answered_questions"] == [{"question": "does the effect survive transpilation?", "pointer": "experiments/exp1/plan.md"}]
    assert "Open questions (questions.md): 1 (1 answered)" in c("status").out
    close(c)
    ans = memory(c, "answered")
    assert ans[0]["question"] == "does the effect survive transpilation?"
    assert ans[0]["answered_by"] == "archive/inv-001/experiments/exp1/plan.md"
    assert not any("transpilation" in q["question"] for q in memory(c, "open"))
    assert "answered by: archive/inv-001/experiments/exp1/plan.md" in c("explain", ans[0]["id"]).out


@pytest.mark.checkpoint("9.3")
def test_limitation_travels_with_the_verdict(programme: Craft):
    c = programme
    inv = open_inv(c)
    plan(c, inv, "exp1", "description: d\ntests: [H1:C1]")
    e = ev(c, f"investigations/{inv}/experiments/exp1/evidence/c1.json", "accuracy_gain", [1.9, 2.0, 2.1, 2.0, 1.95])
    assert "SUPPORTED" in c("verdict", "exp1", "--criterion", "H1:C1", "--evidence", e, "--inv", inv).out
    vfile = c.root / "investigations" / inv / "experiments" / "exp1" / "verdict-H1-C1.md"
    before = vfile.read_text()
    c.write(f"investigations/{inv}/experiments/exp1/exploratory/hw-check.md", "the executable circuit falls to 1.4x")
    c.write(f"investigations/{inv}/questions.md", "- does the gain survive on executable circuits?\n- unrelated?\n")
    r = c("limitation", "exp1", "--criterion", "H1:C1", "--inv", inv, "--text",
          "simulation computed the mixer exactly; the executable circuit falls below the threshold",
          "--source", "experiments/exp1/exploratory/hw-check.md", "--question", "executable circuits")
    assert r.code == 0 and "stays SUPPORTED" in r.out and "now shows as answered" in r.out, r.text
    assert board(c)["answered_questions"] == [{"question": "does the gain survive on executable circuits?",
                                               "pointer": "experiments/exp1/verdict-H1-C1.limitations.md"}]
    assert vfile.read_text() == before  # the verdict itself never changes
    lim = c.root / "investigations" / inv / "experiments" / "exp1" / "verdict-H1-C1.limitations.md"
    assert c.hook("Edit", file_path=str(lim), old_string="a", new_string="b").code == 2
    assert "C1 supported (limitation)" in c("status").out and "1 limitation" in c("status").out
    assert c("verify").code == 0
    close(c)
    f = memory(c, "finding")[0]
    assert f["limitations"][0]["text"].startswith("simulation computed")
    assert "LIMITATION" in c("recall", "method accuracy advantage baseline").out
    x = c("explain", f["id"])
    assert x.code == 0 and "LIMITATION (found after the verdict" in x.out and "limitations archive/" in x.out


@pytest.mark.checkpoint("9.4")
def test_memory_correction_is_a_researcher_decision_shown_with_the_entry(programme: Craft):
    c = programme
    open_inv(c)
    plan(c, "inv-001", "sweep", "description: decisive exploratory study\nexploratory: true")
    close(c)
    q = memory(c, "open")
    target = next(x for x in q if "untested H1" in x["question"])
    c.write("notes/why.md", "H1 was superseded by H3 in the follow-on investigation")
    # the agent cannot record it
    assert c("correct", target["id"], "--note", "superseded by H3 in inv-002, not left untested").code != 0
    assert c.hook("Bash", command=f"craft correct {target['id']} --note x").code == 2
    assert c.hook("Write", file_path=str(c.root / "memory" / "corrections.jsonl"), content="{}").code == 2
    out = typed(c, f'/craft-correct {target["id"]} --note "superseded by H3 in inv-002, not left untested" --evidence notes/why.md')
    assert "Correction C-0001 recorded" in out, out
    assert read_jsonl(c.root / "memory" / "open-questions.jsonl") == q  # the entry itself is never rewritten
    assert "CORRECTED" in c("recall", "method accuracy advantage holds larger inputs").out
    x = c("explain", target["id"])
    assert "CORRECTED by the researcher" in x.out and "correction evidence notes/why.md: resolves" in x.out
    (c.root / "notes" / "why.md").write_text("changed")
    assert c("explain", target["id"]).code != 0


@pytest.mark.checkpoint("9.5")
def test_kill_check_evidence_does_not_block_reregistration(programme: Craft):
    c = programme
    inv = open_inv(c)
    plan(c, inv, "pilot", "description: pilot for K1 and H1\ntests: [H1:C1]")
    e = ev(c, f"investigations/{inv}/experiments/pilot/evidence/k1.json", "pilot_loss", [1.0, 1.1, 0.9, 1.0, 1.05])
    assert "NOT met" in c("verdict", "pilot", "--criterion", "K1", "--evidence", e, "--inv", inv).out
    h = c.root / "investigations" / inv / "hypotheses" / "H1.md"
    h.write_text(h.read_text().replace("threshold: 1.5", "threshold: 1.6"))
    script = c.root.parent / "cycle2.json"
    r = c("review", "--hyp", "H1", "--inv", inv, env={"CRAFT_REFEREE_BACKEND": "fake", "CRAFT_FAKE_REFEREE": str(script)})
    assert "H1 is now REGISTERED" in r.out, r.text
    # evidence reporting H1's own metric does block it
    time.sleep(1.01)
    ev(c, f"investigations/{inv}/experiments/pilot/evidence/c1.json", "accuracy_gain", [1.9, 2.0, 2.1, 2.0, 1.95])
    h.write_text(h.read_text().replace("threshold: 1.6", "threshold: 1.4"))
    r = c("review", "--hyp", "H1", "--inv", inv, env={"CRAFT_REFEREE_BACKEND": "fake", "CRAFT_FAKE_REFEREE": str(script)})
    assert r.code != 0 and "evidence bearing on its criteria" in r.err and "c1.json" in r.err


@pytest.mark.checkpoint("9.6")
def test_hypothesis_label_states_its_basis(programme: Craft):
    c = programme
    inv = open_inv(c)
    plan(c, inv, "exp1", "description: d\ntests: [H1:C1]")
    e = ev(c, f"investigations/{inv}/experiments/exp1/evidence/c1.json", "accuracy_gain", [1.38, 1.42, 1.40, 1.41, 1.39])
    r = c("verdict", "exp1", "--criterion", "H1:C1", "--evidence", e, "--inv", inv)
    assert "H1 is now refuted (by CRAFT's roll-up" in r.out and "the registered outcome rule, which is free text and governs" in r.out
    assert "any criterion's 95% interval lies entirely on the failing side" in r.out
    assert board(c)["hypotheses"]["H1"]["label_basis"] == "roll-up"
    assert "label by CRAFT roll-up" in c("status").out
    # a rule that says it is the mechanical roll-up is the label's basis
    c2 = Craft(c.root.parent / "prog2")
    c2.root.mkdir()
    assert c2("init", "--path", str(c2.root)).code == 0
    open_inv(c2, hyp=HYP_FIXED_O2.replace("outcome_rule:\n", "outcome_rule:\n  mechanical: true\n"))
    plan(c2, "inv-001", "exp1", "description: d\ntests: [H1:C1]")
    e = ev(c2, "investigations/inv-001/experiments/exp1/evidence/c1.json", "accuracy_gain", [1.38, 1.42, 1.40, 1.41, 1.39])
    r = c2("verdict", "exp1", "--criterion", "H1:C1", "--evidence", e)
    assert "H1 is now refuted (by the registered outcome rule (mechanical))" in r.out
    assert board(c2)["hypotheses"]["H1"]["label_basis"] == "rule"


@pytest.mark.checkpoint("9.7")
def test_deterministic_metric_is_declared_at_registration(programme: Craft):
    c = programme
    hyp = HYP_FIXED_O2.replace("    conditions: same runs as C1, p50 latency of A over B\n",
                               "    conditions: same runs as C1, p50 latency of A over B\n"
                               "    deterministic: exact enumeration of the latency model on fixed inputs\n")
    inv = open_inv(c, hyp=hyp)
    plan(c, inv, "exp1", "description: d\ntests: [H1:C1, H1:C2]")
    # C1 is not deterministic: a single value is refused, and every missing field is named at once
    e = c.write(f"investigations/{inv}/experiments/exp1/evidence/c1.json", json.dumps({"metric": "accuracy_gain", "value": 2.0}))
    r = c("verdict", "exp1", "--criterion", "H1:C1", "--evidence", str(e), "--inv", inv)
    assert r.code != 0 and "Everything missing" in r.err
    assert "uncertainty for 'accuracy_gain'" in r.err and "seeds: missing" in r.err and "data_id: missing" in r.err
    assert "declared on the criterion (`deterministic: <why>`) before registration" in r.err
    # the old route, a zero-width interval, still works, and the verdict says what it is
    e = ev(c, f"investigations/{inv}/experiments/exp1/evidence/c1b.json", "accuracy_gain", None, value=2.0, ci=[2.0, 2.0])
    r = c("verdict", "exp1", "--criterion", "H1:C1", "--evidence", e, "--inv", inv)
    assert r.code == 0 and "zero-width interval given; the criterion is not registered as deterministic" in r.out, r.text
    # C2 was registered as deterministic: one value suffices, and the verdict says so instead of an interval
    e = ev(c, f"investigations/{inv}/experiments/exp1/evidence/c2.json", "latency_ratio", None, value=1.1)
    r = c("verdict", "exp1", "--criterion", "H1:C2", "--evidence", e, "--inv", inv)
    assert r.code == 0 and "SUPPORTED" in r.out and "deterministic value 1.1" in r.out, r.text
    fm, body = split_frontmatter((c.root / "investigations" / inv / "experiments" / "exp1" / "verdict-H1-C2.md").read_text())
    assert fm["ci95"] is None and fm["deterministic"].startswith("exact enumeration") and "no interval" in body


@pytest.mark.checkpoint("9.8")
def test_input_data_is_recorded_and_a_change_is_held(programme: Craft):
    c = programme
    inv = open_inv(c)
    snap = c.write("data/prices/etf.csv", "date,spy\n2026-01-02,100\n")
    c.write("data/prices/meta.json", "{}")
    r = c("data", "add", "data/prices", "--id", "corpus-2026-09-snapshot", "--inv", inv)
    assert r.code == 0 and "manifest sha256" in r.out and "over 2 files" in r.out, r.text
    assert c.hook("Write", file_path=str(snap), content="x").code == 2
    assert c.hook("Bash", command=f"echo x >> {snap}").code == 2
    plan(c, inv, "exp1", "description: d\ntests: [H1:C1]")
    e = ev(c, f"investigations/{inv}/experiments/exp1/evidence/c1.json", "accuracy_gain", [1.9, 2.0, 2.1, 2.0, 1.95])
    assert c("verdict", "exp1", "--criterion", "H1:C1", "--evidence", e, "--inv", inv).code == 0
    fm, _ = split_frontmatter((c.root / "investigations" / inv / "experiments" / "exp1" / "verdict-H1-C1.md").read_text())
    assert fm["data_records"][0]["id"] == "corpus-2026-09-snapshot"
    # re-recording under the same id with different contents is refused
    snap.write_text("date,spy\n2026-01-02,101\n")
    r = c("verify")
    assert r.code != 0 and "recorded input data 'corpus-2026-09-snapshot' changed" in r.out
    assert board(c)["tainted"] and board(c)["next"]["command"].startswith("/craft-resolve")
    r = c("data", "add", "data/prices", "--id", "corpus-2026-09-snapshot", "--inv", inv)
    assert r.code != 0


@pytest.mark.checkpoint("9.9")
def test_environment_record_only_describes_an_environment(programme: Craft):
    c = programme
    inv = open_inv(c)
    data = c.write("data/prices.parquet", "PAR1")
    r = c("lock", str(data), "--inv", inv)
    assert r.code != 0 and "not an environment lock file" in r.err and "craft data add" in r.err
    lock = c.write("uv.lock", 'version = 1\n[[package]]\nname = "numpy"\n')
    assert "env.lock v2" in c("lock", str(lock), "--inv", inv).out  # versions move forward, never reset
    c("propose", "package", "scipy", "--reason", "covariance shrinkage", "--inv", inv)
    assert "v3" in typed(c, f"/craft-approve --inv {inv}")
    r = c("lock", str(lock), "--inv", inv)
    assert r.code != 0 and "does not contain scipy" in r.err
    lock.write_text(lock.read_text() + '[[package]]\nname = "scipy"\n')
    assert "env.lock v4" in c("lock", str(lock), "--inv", inv).out
    st = json.loads((c.root / "investigations" / inv / "state.json").read_text())
    assert [h["version"] for h in st["env"]["history"]] == [1, 2, 3, 4]


@pytest.mark.checkpoint("9.10")
def test_a_bare_decision_reaches_the_one_waiting_investigation(programme: Craft):
    c = programme
    open_inv(c, "inv-a")
    open_inv(c, "inv-b")
    c("propose", "package", "scipy", "--reason", "shrinkage", "--inv", "inv-b")
    st = c("status").out
    assert "/craft-approve" in st and "--inv inv-b" not in st  # unambiguous: the bare command works
    out = typed(c, "/craft-approve")
    assert "Proposal for inv-b" in out and "Environment is now" in out
    c("propose", "package", "numba", "--reason", "speed", "--inv", "inv-a")
    c("propose", "package", "polars", "--reason", "io", "--inv", "inv-b")
    assert "/craft-approve --inv inv-a" in c("status").out  # ambiguous: the board shows what to type
    out = typed(c, "/craft-approve")
    assert "REFUSED" in out and "2 of them are waiting" in out and "--inv inv-a" in out and "--inv inv-b" in out


@pytest.mark.checkpoint("9.11")
def test_a_parked_idea_validates_as_an_idea(programme: Craft):
    c = programme
    inv = open_inv(c)
    c.write(f"investigations/{inv}/hypotheses/H2.md", "---\nclaim: noise-aware angles recover the gap.\norigin: researcher\n---\n")
    r = c("validate", "H2", "--inv", inv)
    assert r.code == 0 and "a parked idea (claim only), valid as an idea" in r.out and "[error]" not in r.out
    r = c("validate", "H2", "--full", "--inv", inv)
    assert r.code != 0 and "INCOMPLETE" in r.out and "rivals" in r.out
    assert board(c)["hypotheses"]["H2"]["complete"] is False and "draft (idea)" in c("status").out


@pytest.mark.checkpoint("9.12")
def test_memory_is_not_repeated_within_a_session(programme: Craft):
    c = programme
    from craft import memory as mem
    from craft.paths import Programme
    from craft.util import append_jsonl
    prog = Programme(c.root)
    append_jsonl(prog.memory_file("refuted"), {"id": "R-0001", "claim": "min variance beats max drawdown portfolios out of sample",
                                               "investigation": "inv-000", "closed": "2026-01-14T10:00:00+00:00"})
    mem.build_index(prog)
    sid = f"s-{time.time_ns()}"
    first = typed(c, "can min variance portfolios beat max drawdown ones?", sid)
    assert "R-0001" in first and "REFUTED" in first
    assert "<craft-memory>" not in typed(c, "set up the env for the min variance max drawdown backtest", sid)
    assert "R-0001" in typed(c, "can min variance portfolios beat max drawdown ones?", sid + "-new")


@pytest.mark.checkpoint("9.13")
def test_provenance_and_notes_never_touch_a_registration(programme: Craft):
    c = programme
    inv = open_inv(c)
    h = c.root / "investigations" / inv / "hypotheses" / "H1.md"
    reg_before = json.loads((c.root / "investigations" / inv / "state.json").read_text())["hypotheses"]["H1"]["registered_sha256"]
    h.write_text(h.read_text().replace("claim:", "origin: agent\nderived_from: experiments/exp0/verdict-H0-C1.md\nclaim:", 1)
                 + "\nNote: the hardware stage depends on this result.\n")
    b = board(c)
    assert b["hypotheses"]["H1"]["status"] == "registered" and "edited since registration" not in c("status").out
    script = c.root.parent / "cycle2.json"
    r = c("review", "--hyp", "H1", "--inv", inv, env={"CRAFT_REFEREE_BACKEND": "fake", "CRAFT_FAKE_REFEREE": str(script)})
    assert r.code != 0 and "only provenance or notes changed" in r.err
    st = json.loads((c.root / "investigations" / inv / "state.json").read_text())["hypotheses"]["H1"]
    assert st["registered_sha256"] == reg_before and st["cycles"] == []
    # a judged field does count
    h.write_text(h.read_text().replace("paired comparison across seeds", "paired t-test across seeds"))
    assert "edited since registration" in c("status").out


@pytest.mark.checkpoint("9.14")
def test_abandoned_or_deferred_hypotheses_are_not_pending_work(programme: Craft):
    c = programme
    inv = open_inv(c)
    plan(c, inv, "noisy", "description: long noisy simulation\ntests: [H1]")
    assert board(c)["next"]["who"] == "agent"
    plan(c, inv, "noisy", "description: long noisy simulation\ntests: [H1]\nabandoned: a noise-free gate made it irrelevant")
    b = board(c)
    assert b["next"]["command"] == "/craft-close" and "not being tested" in b["next"]["why"]
    assert b["hypotheses"]["H1"]["not_tested"].startswith("experiments abandoned: noisy")
    out = c("status").out
    assert "registered (not being tested)" in out and "closes as an open question unless a new experiment is planned" in out
    # a new experiment makes it pending again; a decision to defer parks it with its reason
    plan(c, inv, "noisy2", "description: rerun at the new gate\ntests: [H1]")
    assert board(c)["next"]["who"] == "agent"
    h = c.root / "investigations" / inv / "hypotheses" / "H1.md"
    h.write_text(h.read_text().replace("claim:", "deferred: QPU time reserved for November\nclaim:", 1))
    b = board(c)
    assert b["hypotheses"]["H1"]["status"] == "registered" and b["hypotheses"]["H1"]["not_tested"] == "deferred: QPU time reserved for November"
    assert b["next"]["command"] == "/craft-close" and "edited since registration" not in c("status").out
    close(c)
    q = next(x for x in memory(c, "open") if x["question"].startswith("untested H1"))
    assert "not tested by decision (deferred: QPU time reserved for November)" in q["context"]


@pytest.mark.checkpoint("9.15")
def test_one_glossary_for_the_words_on_the_board(programme: Craft):
    c = programme
    inv = open_inv(c)
    assert "/craft-glossary" in c("status").out
    r = c("glossary", "deferred")
    assert r.code == 0 and "deferred:" in r.out and "At closure: open question, with the reason." in r.out
    out = typed(c, "/craft-glossary")
    assert "<craft-info>" in out and "Stopping:" in out and "Fixing the record:" in out and "limitation:" in out
    # every status word the board can show has an entry
    from craft.glossary import GLOSSARY
    terms = " ".join(t for _, t, _, _ in GLOSSARY)
    for word in ("idea", "draft", "in review", "registered", "not being tested", "supported", "refuted", "inconclusive",
                 "planned", "run", "done", "abandoned", "exploratory", "dropped", "deferred", "limitation",
                 "correction", "answered", "post-hoc", "deterministic", "mechanical"):
        assert word in terms, word


@pytest.mark.checkpoint("9.16")
def test_refresh_reports_changes_and_never_nests(programme: Craft):
    c = programme
    inv = open_inv(c)
    # inside an existing programme, init refuses and points at the root
    sub = c.root / "investigations" / inv / "experiments" / "pilot"
    sub.mkdir(parents=True)
    r = c("init", "--path", str(sub))
    assert r.code != 0 and "inside the CRAFT programme at" in r.err and not (sub / "craft.yaml").exists()
    # a refresh brings CRAFT's own files up to date, says what changed, and leaves the researcher's text alone
    cm = c.root / "CLAUDE.md"
    cm.write_text("# My notes\n\n" + cm.read_text().replace("## The hard rules", "## Old rules"))
    skill = c.root / ".claude" / "skills" / "craft" / "SKILL.md"
    skill.write_text("old")
    c.write(f"investigations/{inv}/hypotheses/H2.md", "---\nclaim: an idea.\nwaits_on: [H1]\n---\n")
    r = c("init", "--path", str(c.root))
    assert r.code == 0, r.text
    assert "refreshed CRAFT block" in r.out and "new sections: The hard rules" in r.out and "removed sections: Old rules" in r.out
    assert ".claude/skills/craft/SKILL.md (updated)" in r.out and skill.read_text() != "old"
    assert cm.read_text().startswith("# My notes")
    assert "hypotheses/H2.md: `waits_on` was removed" in r.out
    # retired and unknown fields are flagged in validation and on the board too
    v = c("validate", "H2", "--inv", inv)
    assert "[warning] waits_on: was removed" in v.out
    assert "fields CRAFT does not read: waits_on" in c("status").out


@pytest.mark.checkpoint("9.17")
def test_evidence_can_be_checked_before_the_real_run(programme: Craft):
    c = programme
    inv = open_inv(c)
    dry = c.write("scratch/synthetic.json", json.dumps({"metric": "accuracy_gain", "value": 1.2}))
    r = c("verdict", "exp1", "--criterion", "H1:C1", "--evidence", str(dry), "--dry-run", "--inv", inv)
    assert r.code != 0 and "would NOT be accepted" in r.out and "uncertainty for 'accuracy_gain'" in r.out and "seeds: missing" in r.out
    ev(c, "scratch/synthetic.json", "accuracy_gain", [1.0, 1.1, 0.9])
    r = c("verdict", "exp1", "--criterion", "H1:C1", "--evidence", str(dry), "--dry-run", "--inv", inv)
    assert r.code == 0 and "would be accepted" in r.out and "3 per-run values" in r.out
    assert "SUPPORTED" not in r.out and "REFUTED" not in r.out and "INCONCLUSIVE" not in r.out  # never a label
    st = json.loads((c.root / "investigations" / inv / "state.json").read_text())
    assert st["verdicts"] == [] and not any("scratch" in k for k in st["records"])
    # works for a criterion that is only drafted, and for kill criteria
    c.write(f"investigations/{inv}/hypotheses/H2.md", HYP_FIXED_O2)
    assert "as drafted; not registered yet" in c("verdict", "x", "--criterion", "H2:C1", "--evidence", str(dry), "--dry-run", "--inv", inv).out
    ev(c, "scratch/k1.json", "pilot_loss", [1.0, 1.2])
    assert c("verdict", "x", "--criterion", "K1", "--evidence", str(c.root / "scratch" / "k1.json"), "--dry-run", "--inv", inv).code == 0


def test_single_data_file_shows_its_own_hash(programme: Craft):
    import hashlib
    c = programme
    inv = open_inv(c)
    f = c.write("data/prices.csv", "date,spy\n2026-01-02,100\n")
    own = hashlib.sha256(f.read_bytes()).hexdigest()
    r = c("data", "add", "data/prices.csv", "--id", "prices", "--inv", inv)
    assert f"sha256 {own}" in r.out
    assert own in c("data", "list", "--inv", inv).out and f"sha256 {own}" in c("status").out


def test_an_investigation_with_nothing_registered_says_so(programme: Craft):
    c = programme
    assert c("new", "inv-p", "--topic", "a paused question about drawdowns").code == 0
    c.write("investigations/inv-p/problem.md", PROBLEM.replace("id: inv-001", "id: inv-p"))
    typed(c, "/craft-approve --inv inv-p")
    why = board(c, "inv-p")["next"]["why"]
    assert why.startswith("no hypothesis is registered yet") and "every registered hypothesis" not in why


@pytest.mark.checkpoint("9.18")
def test_a_kill_still_lets_existing_evidence_be_judged(programme: Craft):
    c = programme
    inv = open_inv(c)
    plan(c, inv, "run1", "description: one run feeding H1 and K1\ntests: [H1:C1, H1:C2]")
    d = f"investigations/{inv}/experiments/run1/evidence"
    e1 = ev(c, f"{d}/c1.json", "accuracy_gain", [1.9, 2.0, 2.1, 2.0, 1.95])
    k1 = ev(c, f"{d}/k1.json", "pilot_loss", [6.0, 6.1, 5.9, 6.0, 6.05])
    assert "C1 evidence, not judged" in c("status").out and "C2 —" in c("status").out
    r = c("verdict", "run1", "--criterion", "K1", "--evidence", k1, "--inv", inv)
    assert "KILL CRITERION K1 MET" in r.out and "still has no verdict" in r.out and "H1:C1 (run1:" in r.out, r.text
    assert board(c)["next"]["who"] == "agent"
    assert "SUPPORTED" in c("verdict", "run1", "--criterion", "H1:C1", "--evidence", e1, "--inv", inv).out
    time.sleep(1.01)
    late = ev(c, f"{d}/c1-late.json", "accuracy_gain", [1.9, 2.0, 2.1, 2.0, 1.95])
    r = c("verdict", "run1", "--criterion", "H1:C1", "--evidence", late, "--inv", inv)
    assert r.code != 0 and "produced after that" in r.err
    assert board(c)["next"]["command"].startswith("/craft-close")
    close(c)
    assert any("H1:C1" in f["lineage"]["criterion"] for f in memory(c, "finding"))
    qs = [q["question"] for q in memory(c, "open")]
    assert any("run1 was run; judged K1, H1:C1; no verdict for H1:C2" in q for q in qs), qs


@pytest.mark.checkpoint("9.19")
def test_how_data_were_derived_reaches_the_referee(programme: Craft):
    from craft.paths import InvestigationPaths
    from craft.referee import build_round1_prompt

    c = programme
    inv = open_inv(c)
    c.write("data/prices.csv", "date,spy\n2026-01-02,100\n")
    r = c("data", "add", "data/prices.csv", "--id", "prices", "--inv", inv)
    assert "No derivation recorded" in r.out
    how = "US-listed funds converted to CAD at the daily rate, so unhedged"
    assert c("data", "add", "data/prices.csv", "--id", "prices", "--inv", inv, "--derivation", how).code == 0
    r = c("data", "add", "data/prices.csv", "--id", "prices", "--inv", inv, "--derivation", "hedged")
    assert r.code != 0 and "not rewritten" in r.err
    assert how in c("data", "list", "--inv", inv).out
    _, user = build_round1_prompt(InvestigationPaths(c.root / "investigations" / inv), "H1")
    assert "recorded input data" in user and how in user


@pytest.mark.checkpoint("9.20")
def test_sources_carry_over_from_an_archived_investigation(programme: Craft):
    import yaml

    c = programme
    inv = open_inv(c)
    ft = c.write(f"investigations/{inv}/literature/kim2024.txt", "full text of kim2024 " * 50)
    assert c("lit", "add", "kim2024", "--title", "Retriever scaling", "--fulltext", str(ft), "--claims", "c",
             "--method", "m", "--relation", "supports", "--does-not-cover", "d", "--inv", inv).code == 0
    assert c("lit", "add", "lee2025", "--title", "Short note", "--abstract-only", "--reason", "paywalled", "--inv", inv).code == 0
    close(c)
    assert c("new", "inv-002", "--topic", "does the advantage hold on a second corpus").code == 0
    r = c("lit", "carry", inv, "--inv", "inv-002")
    assert r.code == 0 and "Carried 2 source(s)" in r.out, r.text
    lit = c.root / "investigations" / "inv-002" / "literature"
    by = {s["key"]: s for s in yaml.safe_load((lit / "sources.yaml").read_text())["sources"]}
    assert by["kim2024"]["fulltext"] == "investigations/inv-002/literature/kim2024.txt"
    assert (lit / "kim2024.txt").read_text() == "full text of kim2024 " * 50  # found in the archive by its hash
    assert by["kim2024"]["carried_from"]["investigation"] == inv and by["lee2025"]["status"] == "abstract-only"
    assert "already in this investigation" in c("lit", "carry", inv, "--inv", "inv-002").out
    # a full text whose contents no longer match its record is not carried
    (c.root / "archive" / inv / "literature" / "kim2024.txt").write_text("edited")
    assert c("new", "inv-003", "--topic", "a third question on retrieval scaling").code == 0
    r = c("lit", "carry", inv, "--key", "kim2024", "--inv", "inv-003")
    assert "Carried 0" in r.out and "not found with the recorded hash" in r.out
    assert c("lit", "carry", inv, "--key", "nope", "--inv", "inv-003").code != 0


@pytest.mark.checkpoint("9.21")
def test_closure_and_literature_are_validated(programme: Craft):
    c = programme
    inv = open_inv(c)
    c.write(f"investigations/{inv}/literature/stray.pdf", "downloaded, never read")
    r = c("validate", "literature", "--inv", inv)
    assert "literature/stray.pdf" in r.out and "no source records" in r.out
    plan(c, inv, "exp1", "description: d\ntests: [H1:C1]")
    assert "experiments/exp1/plan.md" in c("validate", "experiments", "--inv", inv).out
    assert "experiments/exp1/plan.md" in c("validate", "plans", "--inv", inv).out  # the old name still works
    c.write(f"investigations/{inv}/closure.md", "---\nanomalies:\n  - latency spiked on one node\nnotes: ''\n---\n")
    r = c("validate", "closure", "--inv", inv)
    assert r.code != 0 and "anomalies[1]" in r.out and "not plain text" in r.out
    out = typed(c, f"/craft-close --inv {inv}")
    assert "Closed." not in out and "would lose anomalies" in out, out
    c.write(f"investigations/{inv}/closure.md",
            "---\nanomalies:\n  - question: why did latency spike on one node?\n    context: exp1 logs\nnotes: ''\n---\n")
    assert c("validate", "closure", "--inv", inv).code == 0
    close(c)
    assert any("latency spike" in q["question"] for q in memory(c, "open"))


@pytest.mark.checkpoint("9.22")
def test_a_kill_criterion_is_judged_from_recorded_verdicts(programme: Craft):
    from craft.artifacts.problem import validate_problem

    c = programme
    k2 = ("  - id: K2\n    condition: under both runs the gain's upper bound stays below 0.5\n"
          "    metric: accuracy_gain\n    op: \"<\"\n    value: 0.5\n"
          "    from: [run1:H1:C1, run2:H1:C1]\n    of: ci_high\n    combine: all\n")
    problem = PROBLEM.replace("memory_acknowledgements: []", k2 + "memory_acknowledgements: []")
    bad = c.write("bad-problem.md", problem.replace("of: ci_high", "of: max"))
    assert any(e.field == "kill_criteria[1].of" for e in validate_problem(bad).errors)
    inv = open_inv(c, problem=problem)
    for run in ("run1", "run2"):
        plan(c, inv, run, f"description: {run} of H1:C1\ntests: [H1:C1]")
    d = f"investigations/{inv}/experiments"
    e1 = ev(c, f"{d}/run1/evidence/c1.json", "accuracy_gain", [0.1, 0.2, 0.15, 0.1, 0.2])
    e2 = ev(c, f"{d}/run2/evidence/c1.json", "accuracy_gain", [0.2, 0.1, 0.1, 0.15, 0.2])
    r = c("verdict", "run1", "--criterion", "H1:C1", "--evidence", e1, "--inv", inv)
    assert "REFUTED" in r.out and "KILL" not in r.out and "K2" not in r.out, r.text  # one result is not both runs
    r = c("verdict", "run2", "--criterion", "K2", "--dry-run", "--inv", inv)
    assert r.code != 0 and "not recorded yet: run2:H1:C1" in r.out, r.text
    r = c("verdict", "run2", "--criterion", "K2", "--inv", inv)
    assert r.code != 0 and "not recorded yet: run2:H1:C1" in r.err
    r = c("verdict", "run2", "--criterion", "H1:C1", "--evidence", e2, "--inv", inv)
    assert "`craft verdict run2 --criterion K2` (no --evidence)" in r.out, r.text
    r = c("verdict", "run2", "--criterion", "K2", "--evidence", e2, "--inv", inv)
    assert r.code != 0 and "drop --evidence" in r.err
    r = c("verdict", "run2", "--criterion", "K2", "--inv", inv)
    assert "KILL CRITERION K2 MET" in r.out and "run1:H1:C1" in r.out, r.text
    fm, body = split_frontmatter((c.root / d / "run2" / "verdict-K2.md").read_text())
    assert [x["path"] for x in fm["from_verdicts"]] == ["experiments/run1/verdict-H1-C1.md", "experiments/run2/verdict-H1-C1.md"]
    assert all(x["sha256"] and x["value"] < 0.5 for x in fm["from_verdicts"]) and "no evidence file" in body
    r = c("verdict", "run1", "--criterion", "H1:C1", "--evidence", e1, "--inv", inv)
    assert r.code != 0 and "judged from" in r.err and "not filed again" in r.err
    assert c("verify").code == 0
    cited = c.root / d / "run1" / "verdict-H1-C1.md"
    cited.write_text(cited.read_text() + "\nedited\n")
    out = c("verify").out
    assert "was judged from experiments/run1/verdict-H1-C1.md" in out, out
