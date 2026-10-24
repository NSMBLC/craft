"""The recommended acceptance run: one investigation through all eight journeys.

Tests run in file order and share one programme (module-scoped fixture). Each test is
marked with the checkpoints it demonstrates; conftest writes checkpoints.md from the marks.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import sys
from pathlib import Path

import pytest

from craft.util import read_jsonl, sha256_file, split_frontmatter

from .fake_referee import CYCLE_1, CYCLE_2, PRESCRIPTIVE
from ..conftest import Craft

pytestmark = pytest.mark.usefixtures("arc")

TOPIC = "does method A's accuracy advantage over baseline B hold on larger inputs"
INV = "inv-001"

PROBLEM_OK = """---
id: inv-001
title: Does method A's advantage over baseline B survive large inputs?
studying: method A versus baseline B on inputs above one million tokens
to_find_out: whether A's accuracy advantage persists, shrinks, or reverses as input size grows
so_that:
  reader: the platform team lead deciding the Q4 default retriever
  understands: whether adopting A for the large-document tier is justified by evidence rather than small-input results
cost_of_not_answering: the team ships A to the large tier on faith and, if the advantage reverses, loses a quarter of tuning work
kill_criteria:
  - id: K1
    condition: pilot loss on the 1e6-token slice exceeds 5.0, meaning the data regime is unusable
    metric: pilot_loss
    op: ">"
    value: 5.0
memory_acknowledgements:
  - ref: R-0001
    entry: method A's accuracy advantage over baseline B holds on inputs larger than 1e6 tokens
    justification: the new 2026 corpus has 10x longer documents so the 2025 refutation on short-document data does not apply
---

# inv-001

We study method A against baseline B on inputs above one million tokens, to find out whether
A's accuracy advantage persists, so that the platform team lead deciding the Q4 default
retriever knows whether to adopt A for the large-document tier. Leaving it unanswered means
shipping on faith.
"""

HYP_ONE_RIVAL = """---
claim: Method A's accuracy gain over baseline B on inputs above 1e6 tokens is at least 1.5 points.
warrant: Accuracy gain on the held-out large slice is the quantity the platform decision depends on, and the slice is drawn from the target distribution.
criteria:
  - name: C1
    metric: accuracy_gain
    op: ">="
    threshold: 1.5
    conditions: 5 seeds, inputs >= 1e6 tokens, 2026 corpus snapshot
  - name: C2
    metric: latency_ratio
    op: "<="
    threshold: 1.2
    conditions: same runs as C1, p50 latency of A over B
  - name: C3
    metric: recall_at_10
    op: ">="
    threshold: 0.80
    conditions: same runs as C1
outcome_rule:
  supported: every criterion's 95% interval lies on the passing side of its threshold
  refuted: any criterion's 95% interval lies entirely on the failing side
  inconclusive: any criterion's interval spans its threshold and none fails
rivals:
  - explanation: A benefits from more tuning attention than B
    discriminator: equal tuning budget for both arms
predictions:
  if_true: accuracy_gain interval above 1.5 on all seeds, latency within 1.2x
  if_false: accuracy_gain interval below 1.5 or reversed on the large slice
power:
  effect_size: 1.5
  n_runs: 5
  method: paired comparison across seeds
  detectable: yes, assuming seed variance below 0.3 points
---

# Hypothesis H1 — inv-001
"""

HYP_TWO_RIVALS = HYP_ONE_RIVAL.replace(
    "    discriminator: equal tuning budget for both arms\n",
    "    discriminator: equal tuning budget for both arms\n"
    "  - explanation: the large slice is easier for any retriever, inflating both arms\n"
    "    discriminator: report absolute scores of B alongside the gain\n",
)

HYP_FIXED_O1 = HYP_TWO_RIVALS.replace(
    "    conditions: 5 seeds, inputs >= 1e6 tokens, 2026 corpus snapshot\n",
    "    conditions: 5 seeds, inputs >= 1e6 tokens, 2026 corpus snapshot, identical 40-trial tuning budget for A and B\n",
)

HYP_FIXED_O2 = HYP_FIXED_O1.replace(
    "  detectable: yes, assuming seed variance below 0.3 points\n",
    "  detectable: pilot seed standard deviation is 0.21 points; with n=5 the 95% half-width is 0.26, so a 1.5-point effect is detected with margin\n"
    "  pilot_sd: 0.21\n",
)


@pytest.fixture(scope="module")
def arc(tmp_path_factory) -> Craft:
    root = tmp_path_factory.mktemp("arc") / "prog"
    root.mkdir()
    c = Craft(root)
    assert c("init", "--path", str(root)).code == 0
    # seed memory as if an investigation was refuted eight months ago
    from craft import memory as mem
    from craft.paths import Programme
    from craft.util import append_jsonl
    prog = Programme(root)
    append_jsonl(prog.memory_file("refuted"), {
        "id": "R-0001", "claim": "method A's accuracy advantage over baseline B holds on inputs larger than 1e6 tokens",
        "investigation": "inv-000", "closed": "2026-01-14T10:00:00+00:00", "keywords": ["method", "advantage", "baseline", "large", "input"],
    })
    mem.build_index(prog)
    scripts = root.parent / "referee"
    scripts.mkdir()
    (scripts / "cycle1.json").write_text(json.dumps(CYCLE_1))
    (scripts / "cycle2.json").write_text(json.dumps(CYCLE_2))
    (scripts / "prescriptive.json").write_text(json.dumps(PRESCRIPTIVE))
    c.scripts = scripts  # type: ignore[attr-defined]
    return c


def fake(c: Craft, name: str) -> dict:
    return {"CRAFT_REFEREE_BACKEND": "fake", "CRAFT_FAKE_REFEREE": str(c.scripts / name)}  # type: ignore[attr-defined]


H2_CLAIM = "Method A keeps an accuracy gain of at least 1.5 points over baseline B when its index is rebuilt for each corpus snapshot."
H2_IDEA = f"""---
claim: {H2_CLAIM}
origin: agent
derived_from: lit:kim2024
---
"""
H2_FULL = HYP_FIXED_O2.replace(
    "claim: Method A's accuracy gain over baseline B on inputs above 1e6 tokens is at least 1.5 points.\n",
    f"claim: {H2_CLAIM}\norigin: agent\nderived_from: experiments/exp1/verdict-H1-C1.md\n",
)
H3_IDEA = """---
claim: The latency penalty of A comes from index construction, not from query time.
origin: researcher
---
"""
H4_FULL = HYP_FIXED_O2.replace(
    "claim: Method A's accuracy gain over baseline B on inputs above 1e6 tokens is at least 1.5 points.\n",
    "claim: Method A's accuracy gain over baseline B holds at 1.5 points on the 2025 corpus as well.\n",
)


def deny_reason(r) -> str:
    assert r.code == 2, r.text
    return json.loads(r.out.splitlines()[0])["hookSpecificOutput"]["permissionDecisionReason"]


def evidence(values: list[float], metric: str, **extra) -> str:
    return json.dumps({"metric": metric, "values": values, "seeds": [1, 2, 3, 4, 5], "data_id": "corpus-2026-09-snapshot", **extra})


def board(c: Craft) -> dict:
    return json.loads(c("status", "--json").out)[INV]


# ---------------------------------------------------------------- Journey 1

@pytest.mark.checkpoint("1.1", "7.3")
def test_01_memory_collision_surfaces_before_anything_exists(arc: Craft):
    r = arc("recall", "I keep wondering if method A's advantage holds on larger inputs")
    assert r.code == 0 and "R-0001" in r.out and "refuted" in r.out
    # unprompted: the UserPromptSubmit hook injects it on the researcher's first message
    r = arc.hook_event("user-prompt-submit", prompt="I keep wondering if method A's advantage holds on larger inputs")
    assert r.code == 0 and "R-0001" in r.out and "REFUTED" in r.out
    # and creation is refused until acknowledged
    r = arc("new", INV, "--topic", TOPIC)
    assert r.code != 0 and "R-0001" in r.err and "acknowledged" in r.err
    assert not (arc.root / "investigations" / INV).exists()


@pytest.mark.checkpoint("1.2")
def test_02_justification_recorded_in_framing(arc: Craft):
    r = arc("new", INV, "--topic", TOPIC, "--acknowledge", "R-0001", "--justification",
            "the new 2026 corpus has 10x longer documents so the 2025 refutation on short-document data does not apply")
    assert r.code == 0, r.text
    fm, _ = split_frontmatter((arc.root / "investigations" / INV / "problem.md").read_text())
    assert fm["memory_acknowledgements"][0]["ref"] == "R-0001"
    assert "10x longer" in fm["memory_acknowledgements"][0]["justification"]


@pytest.mark.checkpoint("1.3", "1.4")
def test_03_weak_reader_and_missing_kill_criteria_rejected(arc: Craft):
    weak = PROBLEM_OK.replace("reader: the platform team lead deciding the Q4 default retriever", "reader: the community") \
                     .replace("to_find_out: whether A's accuracy advantage persists, shrinks, or reverses as input size grows",
                              "to_find_out: it would be good to know if A still wins")
    import re
    weak = re.sub(r"kill_criteria:.*?memory_acknowledgements:", "kill_criteria: []\nmemory_acknowledgements:", weak, flags=re.S)
    arc.write(f"investigations/{INV}/problem.md", weak)
    r = arc("validate", "problem")
    assert r.code != 0
    assert "so_that.reader" in r.out and "named reader" in r.out
    assert "good to know" in r.out
    assert "kill_criteria" in r.out
    # approval is refused while incomplete, even by the researcher
    r = arc("approve", "problem", human=True)
    assert r.code != 0 and "not complete" in r.err


@pytest.mark.checkpoint("1.5", "1.6")
def test_04_one_page_statement_advances_only_on_human_approval(arc: Craft):
    arc.write(f"investigations/{INV}/problem.md", PROBLEM_OK)
    assert arc("validate", "problem").code == 0
    # the agent cannot approve: hook denies the command, and the CLI refuses inside an agent tool call
    assert arc.hook("Bash", command="craft approve problem").code == 2
    r = arc("approve", "problem")  # default env simulates the agent's Bash tool (CLAUDECODE set)
    assert r.code != 0 and "researcher decision" in r.err
    assert board(arc)["phase"] == "framing"
    # the agent cannot trigger the prompt hook itself either
    assert arc.hook("Bash", command="echo '{\"prompt\":\"craft approve problem\"}' | craft hook user-prompt-submit").code == 2
    # a natural-language request is not a decision: nothing happens
    r = arc.hook_event("user-prompt-submit", prompt="please approve the problem statement", hook_event_name="UserPromptSubmit")
    assert "<craft-decision>" not in r.out
    assert board(arc)["phase"] == "framing"
    # evidence cannot exist before the researcher has looked
    ev = arc.root / "investigations" / INV / "experiments" / "pilot" / "evidence" / "p.json"
    assert "approved" in deny_reason(arc.hook("Write", file_path=str(ev), content="{}"))
    # status tells the researcher it is their turn
    r = arc.hook_event("user-prompt-submit", prompt="/craft-status", hook_event_name="UserPromptSubmit")
    assert "Waiting on the researcher: /craft-approve" in r.out
    # the researcher reads it (one page) and types the command as a message: the hook executes it
    r = arc.hook_event("user-prompt-submit", prompt="/craft-approve", hook_event_name="UserPromptSubmit")
    assert r.code == 0 and "<craft-decision>" in r.out and "Approved" in r.out and "Do NOT run the command yourself" in r.out
    assert "WAIT for the researcher" in r.out and "hypotheses/H1.md draft created" in r.out
    assert board(arc)["phase"] == "open"
    assert (arc.root / "investigations" / INV / "hypotheses" / "H1.md").exists()
    # a second approval is refused with the reason
    r = arc.hook_event("user-prompt-submit", prompt="craft approve", hook_event_name="UserPromptSubmit")
    assert "REFUSED" in r.out and "nothing awaits your approve" in r.out
    # read-only queries are answered by the hook, without the model
    r = arc.hook_event("user-prompt-submit", prompt="/craft-help", hook_event_name="UserPromptSubmit")
    assert "<craft-info>" in r.out and "/craft-approve" in r.out and "/craft-resolve" in r.out
    # the approved statement stays editable; a change waits for the researcher to read it again
    p = arc.root / "investigations" / INV / "problem.md"
    assert os.access(p, os.W_OK)
    assert arc.hook("Edit", file_path=str(p), old_string="a", new_string="b").code == 0
    p.write_text(p.read_text().replace("loses a quarter of tuning work", "loses a quarter of tuning work on the wrong retriever"))
    st = board(arc)
    assert st["problem_changed"] and st["next"]["who"] == "researcher" and st["next"]["command"] == "/craft-approve"
    r = arc.hook_event("user-prompt-submit", prompt="/craft-approve", hook_event_name="UserPromptSubmit")
    assert "Changed problem statement" in r.out and "Approved" in r.out
    assert not board(arc)["problem_changed"]


@pytest.mark.checkpoint("1.7")
def test_05_predrafted_statement_validated_not_rewritten(arc: Craft):
    r = arc("new", "inv-002", "--topic", "does cosine warmup reduce gradient variance in tiny transformers")
    assert r.code == 0, r.text
    import re
    predrafted = PROBLEM_OK.replace("id: inv-001", "id: inv-002")
    predrafted = re.sub(r"kill_criteria:.*?memory_acknowledgements:", "memory_acknowledgements:", predrafted, flags=re.S)
    p = arc.write("investigations/inv-002/problem.md", predrafted)
    before = sha256_file(p)
    r = arc("validate", "problem", "--inv", "inv-002")
    assert r.code != 0
    errors = [l for l in r.out.splitlines() if "[error]" in l]
    assert len(errors) == 1 and "kill_criteria" in errors[0]
    assert sha256_file(p) == before  # nothing rewritten


# ---------------------------------------------------------------- Journey 2

@pytest.mark.checkpoint("2.1", "2.2", "2.3")
def test_06_literature_used_vs_rejected(arc: Craft):
    r = arc("lit", "add", "zhao2025", "--title", "Long-context retrieval", "--abstract-only", "--inv", INV)
    assert r.code != 0 and "--reason" in r.err
    r = arc("lit", "add", "zhao2025", "--title", "Long-context retrieval", "--abstract-only", "--reason", "paywalled; abstract only", "--inv", INV)
    assert r.code == 0
    r = arc("lit", "add", "kim2024", "--title", "Retriever scaling", "--fulltext", str(arc.root / "missing.pdf"), "--inv", INV)
    assert r.code != 0 and "full text" in r.err
    ft = arc.write("papers/kim2024.txt", "full text of kim2024 " * 50)
    r = arc("lit", "add", "kim2024", "--title", "Retriever scaling", "--fulltext", str(ft),
            "--claims", "A beats B up to 1e5 tokens", "--method", "5-seed benchmark", "--relation", "supports",
            "--does-not-cover", "inputs above 1e5 tokens", "--inv", INV)
    assert r.code == 0, r.text
    r = arc("validate", "literature", "--inv", INV)
    assert r.code != 0 and "closest_prior_work" in r.out
    r = arc("lit", "closest", "kim2024", "--delta", "kim2024 stops at 1e5 tokens; we extend the same protocol to 1e6+ with equal tuning budgets.", "--inv", INV)
    assert r.code == 0
    assert arc("validate", "literature", "--inv", INV).code == 0
    from craft.util import read_yaml
    data = read_yaml(arc.root / "investigations" / INV / "literature" / "sources.yaml")
    by = {s["key"]: s for s in data["sources"]}
    assert by["zhao2025"]["status"] == "rejected" and by["kim2024"]["status"] == "used"
    assert by["kim2024"]["does_not_cover"] and by["kim2024"]["fulltext_sha256"] and by["kim2024"]["added"]


@pytest.mark.checkpoint("2.4")
def test_07_bare_priority_claim_flagged(arc: Craft):
    doc = arc.write(f"investigations/{INV}/literature/map.md", "No prior work addresses this regime.\n")
    r = arc("lint", str(doc), "--inv", INV)
    assert r.code != 0 and "kim2024" in r.out
    arc.write(f"investigations/{INV}/literature/map.md", "kim2024 stops at 1e5 tokens; this investigation extends the protocol to 1e6+.\n")
    assert arc("lint", str(doc), "--inv", INV).code == 0


# ---------------------------------------------------------------- Journey 3

@pytest.mark.checkpoint("3.1", "3.2")
def test_08_hypothesis_with_one_rival_is_incomplete_and_still_a_draft(arc: Craft):
    p = arc.write(f"investigations/{INV}/hypotheses/H1.md", HYP_ONE_RIVAL)
    r = arc("validate", "H1", "--inv", INV)
    assert r.code != 0 and "INCOMPLETE" in r.out and "rivals" in r.out and "at least two" in r.out
    # review refuses an incomplete draft
    r = arc("review", "--hyp", "H1", "--inv", INV, env=fake(arc, "cycle1.json"))
    assert r.code != 0 and "not complete" in r.err
    # a one-line idea is parked next to it; `craft validate` lists it as an idea without failing on it
    arc.write(f"investigations/{INV}/hypotheses/H2.md", H2_IDEA)
    r = arc("validate", "--inv", INV)
    assert "hypotheses/H2.md: incomplete draft" in r.out
    # draft: editable, not binding
    assert arc.hook("Edit", file_path=str(p), old_string="a", new_string="b").code == 0
    assert board(arc)["hypotheses"]["H1"]["status"] == "draft"


# ---------------------------------------------------------------- Journey 5 (early) + 4

@pytest.mark.checkpoint("5.1")
def test_09_evidence_refused_before_review(arc: Craft):
    arc.write(f"investigations/{INV}/experiments/exp1/plan.md",
              "---\ndescription: 5-seed run of A and B on the 1e6-token slice\ntests: [H1:C1, H1:C2]\n---\n")
    ev = arc.root / "investigations" / INV / "experiments" / "exp1" / "evidence" / "c1.json"
    reason = deny_reason(arc.hook("Write", file_path=str(ev), content="{}"))
    assert "H1" in reason and "not been reviewed" in reason and "exploratory" in reason
    assert not ev.exists()
    # the shell route is screened too
    assert arc.hook("Bash", command=f"echo '{{}}' > {ev}").code == 2
    # exploration is never blocked
    expl = arc.root / "investigations" / INV / "experiments" / "exp1" / "exploratory" / "try.json"
    assert arc.hook("Write", file_path=str(expl), content="{}").code == 0


@pytest.mark.checkpoint("4.1")
def test_10_referee_sees_only_files(arc: Craft, monkeypatch):
    from craft.paths import InvestigationPaths
    from craft.referee import build_round1_prompt, _claude
    arc.write(f"investigations/{INV}/hypotheses/H1.md", HYP_TWO_RIVALS)
    inv = InvestigationPaths(arc.root / "investigations" / INV)
    sys_p, user_p = build_round1_prompt(inv, "H1")
    assert "problem.md" in user_p and "hypotheses/H1.md" in user_p and "sources.yaml" in user_p
    assert H2_CLAIM not in user_p  # one hypothesis at a time
    assert "deadline" not in user_p and "chat" not in user_p.lower()
    # the claude backend is invoked with no tools, no settings sources, no session, from an empty cwd
    captured = {}

    def fake_run(args, **kw):
        captured["args"] = args
        captured["cwd"] = kw.get("cwd")
        captured["env"] = kw.get("env")
        class P:
            returncode = 0
            stdout = json.dumps({"type": "result", "structured_output": CYCLE_2["1"]})
            stderr = ""
        return P()

    monkeypatch.setattr("craft.referee.subprocess.run", fake_run)
    monkeypatch.setattr("craft.referee.shutil.which", lambda x: "/usr/bin/claude")
    out = _claude({"model": "opus"}, sys_p, user_p, {}, )
    a = captured["args"]
    assert a[a.index("--tools") + 1] == "" and a[a.index("--setting-sources") + 1] == ""
    assert "--no-session-persistence" in a and "--system-prompt" in a
    assert captured["cwd"] != str(arc.root) and "CLAUDECODE" not in captured["env"]
    assert out["no_blocking_objections"] is True


@pytest.mark.checkpoint("4.2", "4.3")
def test_11_round1_structured_blocking_objections_without_fixes(arc: Craft):
    # a referee that prescribes fixes is rejected (twice -> error)
    r = arc("review", "--inv", INV, env=fake(arc, "prescriptive.json"))
    assert r.code != 0 and "prescribes a fix" in r.err
    h1 = board(arc)["hypotheses"]["H1"]
    assert h1["rounds"] == 0 and h1["status"] == "draft"
    r = arc("review", "--inv", INV, env=fake(arc, "cycle1.json"))
    assert r.code == 0, r.text
    assert "Not reviewed — H2" in r.out  # the parked idea is skipped, not an error
    rdir = arc.root / "investigations" / INV / "review" / "H1"
    data = json.loads((rdir / "round-1.json").read_text())
    o1 = next(o for o in data["objections"] if o["id"] == "O1")
    assert o1["severity"] == "blocking" and "tuning" in o1["statement"]
    assert o1["target"] == {"document": "hypothesis.md", "section": "criteria"}
    assert all({"id", "category", "severity", "target", "statement", "adequate_answer"} <= set(o) for o in data["objections"])
    from craft.artifacts.review import check_round1
    assert check_round1(data) == []
    # what the referee saw is kept, and no review file is the agent's to write
    assert "kim2024" in (rdir / "round-1.prompt.md").read_text()
    assert "4.1" in deny_reason(arc.hook("Write", file_path=str(rdir / "round-1.json"), content="{}"))


@pytest.mark.checkpoint("5.2")
def test_12_evidence_refused_while_blocking_open(arc: Craft):
    ev = arc.root / "investigations" / INV / "experiments" / "exp1" / "evidence" / "c1.json"
    reason = deny_reason(arc.hook("Write", file_path=str(ev), content="x"))
    assert "O1" in reason and "O2" in reason and "respond" in reason
    assert not ev.exists()


@pytest.mark.checkpoint("4.4")
def test_13_round2_accepts_fixes_escalates_handwave(arc: Craft):
    p = arc.root / "investigations" / INV / "hypotheses" / "H1.md"
    assert arc.hook("Edit", file_path=str(p), old_string="a", new_string="b").code == 0  # editable while in review
    arc.write(f"investigations/{INV}/hypotheses/H1.md", HYP_FIXED_O1)
    r = arc("review", "--hyp", "H1", "--inv", INV, env=fake(arc, "cycle1.json"))
    assert r.code != 0 and "missing responses for H1:O1, H1:O2" in r.err
    assert arc("review", "respond", "O1", "--pointer", "hypotheses/H1.md#criteria", "--note", "equal 40-trial budget in every criterion's conditions; rival added", "--inv", INV).code == 0
    assert arc("review", "respond", "H1:O2", "--pointer", "hypotheses/H1.md#power", "--note", "we believe this is negligible", "--inv", INV).code == 0
    r = arc("review", "--inv", INV, env=fake(arc, "cycle1.json"))
    assert r.code == 0, r.text
    h1 = board(arc)["hypotheses"]["H1"]
    assert h1["status"] == "in review" and h1["open_blocking"] == ["O2"] and h1["rounds"] == 2


@pytest.mark.checkpoint("4.5")
def test_14_no_third_round(arc: Craft):
    r = arc("review", "--inv", INV, env=fake(arc, "cycle1.json"))
    assert r.code != 0 and "capped at 2 rounds" in r.err and "genuinely fixed" in r.err
    h1 = board(arc)["hypotheses"]["H1"]
    assert h1["rounds"] == 2 and h1["exhausted"]
    nxt = board(arc)["next"]
    assert nxt["who"] == "agent" and "new review cycle" in nxt["why"]
    # arguing does not help: responses are closed once the cap is reached
    r = arc("review", "respond", "H1:O2", "--pointer", "x", "--note", "really negligible", "--inv", INV)
    assert r.code != 0 and "capped" in r.err
    # /craft-reopen is retired: nothing is frozen, so the researcher has nothing to reopen
    r = arc.hook_event("user-prompt-submit", prompt="/craft-reopen review", hook_event_name="UserPromptSubmit")
    assert "Nothing to reopen" in r.out


@pytest.mark.checkpoint("4.6", "4.7")
def test_15_clean_pass_registers(arc: Craft):
    p = arc.write(f"investigations/{INV}/hypotheses/H1.md", HYP_FIXED_O2)
    r = arc("review", "--inv", INV, env=fake(arc, "cycle2.json"))
    assert r.code == 0, r.text
    assert "starting review cycle 2" in r.out
    assert "no blocking objections" in r.out and "2 advisory" in r.out and "REGISTERED" in r.out
    h1 = board(arc)["hypotheses"]["H1"]
    assert h1["status"] == "registered" and h1["registered_at"] and h1["cycles"] == 1
    rdir = arc.root / "investigations" / INV / "review" / "H1"
    assert (rdir / "cycle-1" / "round-2.json").exists()
    assert (rdir / "registered.md").read_text() == HYP_FIXED_O2
    data = json.loads((rdir / "round-1.json").read_text())
    assert data["no_blocking_objections"] is True and len(data["objections"]) == 2
    assert os.access(p, os.W_OK)  # registration records, it does not lock


@pytest.mark.checkpoint("5.3")
def test_16_evidence_now_simply_succeeds(arc: Craft):
    ev = arc.root / "investigations" / INV / "experiments" / "exp1" / "evidence" / "c1.json"
    assert arc.hook("Write", file_path=str(ev), content="{}").code == 0


@pytest.mark.checkpoint("5.5")
def test_17_registered_record_is_never_edited(arc: Craft):
    reg = arc.root / "investigations" / INV / "review" / "H1" / "registered.md"
    reason = deny_reason(arc.hook("Edit", file_path=str(reg), old_string="threshold: 1.5", new_string="threshold: 1.4"))
    assert "registered" in reason and "post-hoc" in reason
    assert arc.hook("Bash", command=f"sed -i '' 's/1.5/1.4/' {reg}").code == 2
    assert arc.hook("Bash", command=f"echo x >> {arc.root / 'investigations' / INV / 'state.json'}").code == 2
    # the hypothesis file itself is editable (what happens then is test_21)
    h1 = arc.root / "investigations" / INV / "hypotheses" / "H1.md"
    assert arc.hook("Edit", file_path=str(h1), old_string="1.5", new_string="1.4").code == 0
    assert arc("verify").code == 0


@pytest.mark.checkpoint("5.6")
def test_18_memory_only_through_closing(arc: Craft):
    f = arc.root / "memory" / "findings.jsonl"
    r = arc.hook("Write", file_path=str(f), content='{"id":"F-9"}')
    assert r.code == 2 and "closing of an investigation" in r.out
    assert arc.hook("Bash", command=f"echo '{{}}' >> {f}").code == 2
    assert read_jsonl(f) == []


# ---------------------------------------------------------------- Journey 6

@pytest.mark.checkpoint("6.1")
def test_19_env_change_halts_until_approved(arc: Craft):
    ev = arc.write(f"investigations/{INV}/experiments/exp1/evidence/c1.json", evidence([1.38, 1.42, 1.40, 1.41, 1.39], "accuracy_gain"))
    lock = arc.root / "investigations" / INV / "env.lock"
    assert arc.hook("Edit", file_path=str(lock), old_string="a", new_string="b").code == 2
    r = arc("propose", "package", "faiss-gpu", "--reason", "exp1 needs GPU index build", "--inv", INV)
    assert r.code == 0 and "halted" in r.out
    r = arc("verdict", "exp1", "--criterion", "H1:C1", "--evidence", str(ev), "--inv", INV)
    assert r.code != 0 and "halted" in r.err
    r = arc("approve", "package", "--inv", INV)
    assert r.code != 0  # agent cannot
    r = arc.hook_event("user-prompt-submit", prompt=f"/craft-approve --inv {INV}", hook_event_name="UserPromptSubmit")
    assert "<craft-decision>" in r.out and "v2" in r.out
    assert board(arc)["env_version"] == 2


@pytest.mark.checkpoint("5.4", "6.2", "6.4")
def test_20_verdict_at_1_4_against_registered_1_5_is_refuted(arc: Craft):
    # undo test_17's exploratory edit so this verdict is a plain one
    arc.write(f"investigations/{INV}/hypotheses/H1.md", HYP_FIXED_O2)
    ev = arc.root / "investigations" / INV / "experiments" / "exp1" / "evidence" / "c1.json"
    r = arc("verdict", "exp1", "--criterion", "H1:C1", "--evidence", str(ev), "--inv", INV)
    assert r.code == 0, r.text
    assert "REFUTED" in r.out and "POST-HOC" not in r.out
    assert "Propose up to three follow-ups" in r.out and "derived_from: experiments/exp1/verdict-H1-C1.md" in r.out
    vf = arc.root / "investigations" / INV / "experiments" / "exp1" / "verdict-H1-C1.md"
    fm, body = split_frontmatter(vf.read_text())
    assert fm["label"] == "refuted" and fm["threshold"] == 1.5 and abs(fm["observed"] - 1.40) < 1e-9
    assert fm["ci95"][0] < 1.40 < fm["ci95"][1] < 1.5
    assert fm["evidence"][0]["sha256"] == sha256_file(ev)
    assert fm["seeds"] == [1, 2, 3, 4, 5] and fm["data_ids"] == ["corpus-2026-09-snapshot"]
    assert fm["env_version"] == 2 and fm["hypothesis_registered_sha256"] and fm["post_hoc"] is None
    # the label cannot be edited, and neither can the evidence it cites
    assert "6.2" in deny_reason(arc.hook("Edit", file_path=str(vf), old_string="refuted", new_string="supported"))
    assert "cites" in deny_reason(arc.hook("Edit", file_path=str(ev), old_string="1.38", new_string="1.58"))


@pytest.mark.checkpoint("8.4")
def test_21_threshold_lowered_after_data_is_post_hoc(arc: Craft):
    h1 = arc.root / "investigations" / INV / "hypotheses" / "H1.md"
    # "lower the threshold to 1.3, it's basically there": the edit is allowed...
    assert arc.hook("Edit", file_path=str(h1), old_string="threshold: 1.5", new_string="threshold: 1.3").code == 0
    h1.write_text(h1.read_text().replace("threshold: 1.5", "threshold: 1.3"))
    # ...but the verdict keeps the pre-registered label and says what the change would have concluded
    ev = arc.root / "investigations" / INV / "experiments" / "exp1" / "evidence" / "c1.json"
    r = arc("verdict", "exp1", "--criterion", "H1:C1", "--evidence", str(ev), "--inv", INV)
    assert r.code == 0, r.text
    assert "REFUTED" in r.out and "POST-HOC" in r.out and "1.5 -> 1.3" in r.out and "would be SUPPORTED" in r.out
    fm, body = split_frontmatter((arc.root / "investigations" / INV / "experiments" / "exp1" / "verdict-H1-C1.md").read_text())
    assert fm["label"] == "refuted" and fm["threshold"] == 1.5
    assert fm["post_hoc"]["changed"] and fm["post_hoc"]["label_under_changed_criterion"] == "supported"
    h = board(arc)["hypotheses"]["H1"]
    assert h["post_hoc"] and h["status"] == "refuted"
    # and the changed version cannot be passed off as a fresh pre-registration
    r = arc("review", "--hyp", "H1", "--inv", INV, env=fake(arc, "cycle2.json"))
    assert r.code != 0 and "changed after evidence" in r.err and "new hypothesis" in r.err


@pytest.mark.checkpoint("6.3")
def test_22_exploratory_numbers_never_become_evidence(arc: Craft):
    expl = arc.write(f"investigations/{INV}/experiments/exp1/exploratory/sweep.json", evidence([0.9, 0.95, 0.92, 0.91, 0.93], "latency_ratio"))
    r = arc("verdict", "exp1", "--criterion", "H1:C2", "--evidence", str(expl), "--inv", INV)
    assert r.code != 0 and "exploratory" in r.err and "never evidence" in r.err
    ev = arc.write(f"investigations/{INV}/experiments/exp1/evidence/c2.json", evidence([1.05, 1.08, 1.06, 1.07, 1.04], "latency_ratio"))
    r = arc("verdict", "exp1", "--criterion", "H1:C2", "--evidence", str(ev), "--exploratory", str(expl), "--inv", INV)
    assert r.code == 0, r.text
    fm, body = split_frontmatter((arc.root / "investigations" / INV / "experiments" / "exp1" / "verdict-H1-C2.md").read_text())
    assert fm["label"] == "supported" and abs(fm["observed"] - 1.06) < 1e-9
    assert fm["exploratory_links"] == ["experiments/exp1/exploratory/sweep.json"]
    assert "are evidence for any criterion" in fm["exploratory_note"] and "none" in fm["exploratory_note"]
    assert "0.9" not in json.dumps({k: v for k, v in fm.items() if k not in ("exploratory_links",)})
    # an experiment planned as exploratory cannot produce evidence at all
    arc.write(f"investigations/{INV}/experiments/sweep/plan.md", "---\ndescription: tuning sweep\nexploratory: true\n---\n")
    assert "6.3" in deny_reason(arc.hook("Write", file_path=str(arc.root / "investigations" / INV / "experiments" / "sweep" / "evidence" / "x.json"), content="{}"))


# ---------------------------------------------------------------- Journey 8

@pytest.mark.checkpoint("8.1", "8.2")
def test_23_second_hypothesis_registered_and_tested_independently(arc: Craft):
    # the agent's suggestion after the H1 verdict: flesh out the parked idea, traced to that result
    arc.write(f"investigations/{INV}/hypotheses/H2.md", H2_FULL)
    arc.write(f"investigations/{INV}/hypotheses/H3.md", H3_IDEA)
    r = arc("review", "--inv", INV, env=fake(arc, "cycle2.json"))
    assert r.code == 0, r.text
    assert "H2 is now REGISTERED" in r.out and "Not reviewed — H3" in r.out and "Not reviewed — H1" in r.out
    arc.write(f"investigations/{INV}/experiments/exp3/plan.md",
              "---\ndescription: per-snapshot index rebuild, 5 seeds\ntests: [H2:C1]\norigin: agent\n"
              "derived_from: experiments/exp1/verdict-H1-C1.md\n---\n")
    ev = arc.write(f"investigations/{INV}/experiments/exp3/evidence/c1.json", evidence([1.72, 1.81, 1.77, 1.79, 1.75], "accuracy_gain"))
    r = arc("verdict", "exp3", "--criterion", "C1", "--evidence", str(ev), "--inv", INV)
    assert r.code != 0 and "several hypotheses (H1, H2)" in r.err
    r = arc("verdict", "exp3", "--criterion", "H1:C1", "--evidence", str(ev), "--inv", INV)
    assert r.code != 0 and "tests H2:C1, not H1:C1" in r.err
    r = arc("verdict", "exp3", "--criterion", "H2:C1", "--evidence", str(ev), "--inv", INV)
    assert r.code == 0, r.text
    assert "SUPPORTED" in r.out
    st = board(arc)
    assert st["hypotheses"]["H1"]["criteria"] == {"C1": "refuted", "C2": "supported"}
    assert st["hypotheses"]["H2"]["criteria"] == {"C1": "supported"} and st["hypotheses"]["H2"]["status"] == "registered"
    assert st["hypotheses"]["H2"]["origin"] == "agent"
    assert st["hypotheses"]["H2"]["derived_from"] == "experiments/exp1/verdict-H1-C1.md"
    assert st["experiments"]["exp3"]["status"] == "done"


@pytest.mark.checkpoint("8.5")
def test_24_evidence_that_predates_registration_cannot_back_it(arc: Craft):
    # results produced before H4 existed (unplanned, so the gate let the file through)...
    ev = arc.write(f"investigations/{INV}/experiments/exp4/evidence/old.json", evidence([1.6, 1.7, 1.65, 1.68, 1.62], "accuracy_gain"))
    hour_ago = time.time() - 3600
    os.utime(ev, (hour_ago, hour_ago))
    # ...then a hypothesis written to fit them, and registered
    arc.write(f"investigations/{INV}/hypotheses/H4.md", H4_FULL)
    assert arc("review", "--hyp", "H4", "--inv", INV, env=fake(arc, "cycle2.json")).code == 0
    r = arc("verdict", "exp4", "--criterion", "H4:C1", "--evidence", str(ev), "--inv", INV)
    assert r.code != 0 and "produced before H4 was registered" in r.err and "exploratory" in r.err


@pytest.mark.checkpoint("8.6", "8.3")
def test_25_board_reflects_every_state(arc: Craft):
    arc.write(f"investigations/{INV}/questions.md",
              "# Parked questions\n\n- does A's advantage depend on the tokenizer?\n")
    r = arc.hook_event("user-prompt-submit", prompt="/craft-status", hook_event_name="UserPromptSubmit")
    out = r.out
    assert "<craft-info>" in out
    for needle in ("H1", "refuted", "post-hoc", "H2", "registered", "origin agent <- experiments/exp1/verdict-H1-C1.md",
                   "H3", "draft (idea)", "H4", "exp1", "done", "exp3", "sweep", "Open questions (questions.md): 1",
                   "tokenizer"):
        assert needle in out, needle
    st = board(arc)
    assert st["hypotheses"]["H3"]["status"] == "draft" and not st["hypotheses"]["H3"]["complete"]
    assert st["experiments"]["exp1"]["status"] == "done" and st["experiments"]["exp4"]["status"] == "run"
    assert st["questions"] == ["does A's advantage depend on the tokenizer?"]


@pytest.mark.checkpoint("8.7")
def test_26_literature_stays_open_and_review_record_is_kept(arc: Craft):
    prompt = arc.root / "investigations" / INV / "review" / "H1" / "round-1.prompt.md"
    before = prompt.read_text()
    ft = arc.write("papers/lee2026.txt", "full text of lee2026 " * 50)
    r = arc("lit", "add", "lee2026", "--title", "Million-token retrieval", "--fulltext", str(ft),
            "--claims", "dense retrievers degrade past 1e6 tokens", "--method", "3 corpora", "--relation", "conflicts",
            "--does-not-cover", "equal tuning budgets", "--inv", INV)
    assert r.code == 0, r.text
    assert "lee2026" in (arc.root / "investigations" / INV / "literature" / "sources.yaml").read_text()
    assert prompt.read_text() == before and "lee2026" not in before
    assert arc("verify").code == 0


@pytest.mark.checkpoint("6.5")
def test_27_kill_criterion_halts_and_routes_to_closure(arc: Craft):
    # a kill criterion can be checked directly from pilot evidence; not met -> work continues
    pilot = arc.write(f"investigations/{INV}/experiments/pilot/evidence/pilot.json", evidence([4.1, 4.3, 4.0, 4.2, 4.4], "pilot_loss"))
    r = arc("verdict", "pilot", "--criterion", "K1", "--evidence", str(pilot), "--inv", INV)
    assert r.code == 0, r.text
    assert "NOT met" in r.out
    fm, _ = split_frontmatter((arc.root / "investigations" / INV / "experiments" / "pilot" / "verdict-K1.md").read_text())
    assert fm["kind"] == "kill-criterion" and fm["label"] == "kill-not-met" and fm["value"] == 5.0
    assert board(arc)["phase"] == "open"
    r = arc("verdict", "pilot", "--criterion", "K9", "--evidence", str(pilot), "--inv", INV)
    assert r.code != 0 and "neither a criterion" in r.err
    arc.write(f"investigations/{INV}/experiments/exp2/plan.md", "---\ndescription: recall on the largest slice\ntests: [H1:C3]\n---\n")
    arc.write(f"investigations/{INV}/hypotheses/H1.md", HYP_FIXED_O2.replace("threshold: 1.5", "threshold: 1.3"))
    ev = arc.write(f"investigations/{INV}/experiments/exp2/evidence/c3.json", json.dumps({
        "metrics": {"recall_at_10": {"values": [0.70, 0.72, 0.71, 0.69, 0.73]},
                    "pilot_loss": {"values": [6.1, 6.3, 6.0, 6.2, 6.4]}},
        "seeds": [1, 2, 3, 4, 5], "data_id": "corpus-2026-09-snapshot"}))
    r = arc("verdict", "exp2", "--criterion", "H1:C3", "--evidence", str(ev), "--inv", INV)
    assert r.code == 0, r.text
    assert "KILL CRITERION K1 MET" in r.out and "halted" in r.out and "closure" in r.out
    st = board(arc)
    assert st["phase"] == "closing" and st["kill"]["triggered"] and st["kill"]["criterion"] == "K1"
    # no more evidence is accepted
    assert arc.hook("Write", file_path=str(arc.root / "investigations" / INV / "experiments" / "exp5" / "evidence" / "x.json"), content="{}").code == 2


# ---------------------------------------------------------------- Journey 7

@pytest.mark.checkpoint("7.1", "8.3")
def test_28_close_routes_mixed_outcome_and_open_threads(arc: Craft):
    arc.write(f"investigations/{INV}/closure.md",
              "---\nanomalies:\n  - question: why does latency improve on the largest slice while recall collapses?\n    context: exp2 seeds 1-5\nnotes: closed after kill\n---\n# Closure\n")
    r = arc("close", "--inv", INV, "--note", "kill K1 met")
    assert r.code != 0  # the agent cannot close
    r = arc("close", "--inv", INV, "--note", "kill K1 met", human=True)
    assert r.code == 0, r.text
    findings = read_jsonl(arc.root / "memory" / "findings.jsonl")
    refuted = read_jsonl(arc.root / "memory" / "refuted.jsonl")
    open_q = read_jsonl(arc.root / "memory" / "open-questions.jsonl")
    assert [f["lineage"]["criterion"] for f in findings] == ["H1:C2", "H2:C1"]
    assert findings[1]["origin"] == "agent" and findings[1]["derived_from"] == "experiments/exp1/verdict-H1-C1.md"
    assert [r["id"] for r in refuted] == ["R-0001", "R-0002", "R-0003"]
    by_crit = {r["lineage"]["criterion"]: r for r in refuted[1:]}
    assert set(by_crit) == {"H1:C1", "H1:C3"}
    assert by_crit["H1:C1"]["post_hoc"] is True and by_crit["H1:C1"]["lineage"]["threshold"] == 1.5
    qs = [q["question"] for q in open_q]
    assert any("latency improve" in q for q in qs) and any(q.startswith("killed by K1") for q in qs)
    assert any(q.startswith("untested idea H3") for q in qs)                  # parked idea
    assert any(q.startswith("untested H4") for q in qs)                       # registered, never judged
    assert any("tokenizer" in q for q in qs)                                  # questions.md
    assert any(q.startswith("untested H2") and "C2" in q for q in qs)        # registered, partly judged
    assert not (arc.root / "investigations" / INV).exists()
    arch = arc.root / "archive" / INV
    assert (arch / "review" / "H1" / "registered.md").exists() and (arch / "experiments" / "exp1" / "verdict-H1-C1.md").exists()
    assert os.access(arch / "hypotheses" / "H1.md", os.W_OK)  # no file modes: hashes are the guarantee
    assert arc.hook("Edit", file_path=str(arch / "hypotheses" / "H1.md"), old_string="a", new_string="b").code == 2
    assert findings[0]["lineage"]["verdict_file"].startswith(f"archive/{INV}/")
    assert arc("verify").code == 0


@pytest.mark.checkpoint("7.2")
def test_29_fresh_session_explains_every_link(arc: Craft):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CRAFT_PROGRAMME")}
    r = subprocess.run([sys.executable, "-m", "craft.cli", "explain", "F-0001"], cwd=arc.root, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Every link resolves" in r.stdout and r.stdout.count("resolves") >= 4
    r2 = arc.hook_event("user-prompt-submit", prompt="/craft-explain F-0001", hook_event_name="UserPromptSubmit")
    assert "<craft-info>" in r2.out and "Every link resolves" in r2.out
    assert "H1:C2" in r.stdout and "archive/inv-001/experiments/exp1/evidence/c2.json" in r.stdout
    assert "archive/inv-001/review/H1/registered.md: resolves" in r.stdout
    r3 = subprocess.run([sys.executable, "-m", "craft.cli", "explain", "R-0002"], cwd=arc.root, capture_output=True, text=True, env=env)
    assert "POST-HOC" in r3.stdout


@pytest.mark.checkpoint("7.3")
def test_30_fresh_session_refutation_blocks_new_work(arc: Craft):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CRAFT_PROGRAMME")}
    r = subprocess.run([sys.executable, "-m", "craft.cli", "new", "inv-003", "--topic", "method A accuracy advantage over baseline B on large inputs"],
                       cwd=arc.root, capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "R-0002" in r.stderr and "acknowledged" in r.stderr
    assert not (arc.root / "investigations" / "inv-003").exists()
    r = subprocess.run([sys.executable, "-m", "craft.cli", "recall", "collaborator suggests method A beats baseline B on large inputs"],
                       cwd=arc.root, capture_output=True, text=True, env=env)
    assert "R-0001" in r.stdout and "R-0002" in r.stdout


@pytest.mark.checkpoint("8.7")
def test_31_fresh_clone_verifies_and_still_detects_edits(arc: Craft, tmp_path):
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "programme"]):
        subprocess.run(git + cmd, cwd=arc.root, check=True, capture_output=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(arc.root), str(clone)], check=True, capture_output=True)
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CRAFT_PROGRAMME")}
    r = subprocess.run([sys.executable, "-m", "craft.cli", "verify"], cwd=clone, capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "All recorded files intact" in r.stdout, r.stdout + r.stderr
    vf = clone / "archive" / INV / "experiments" / "exp1" / "verdict-H1-C1.md"
    vf.write_text(vf.read_text().replace("label: refuted", "label: supported"))
    r = subprocess.run([sys.executable, "-m", "craft.cli", "verify"], cwd=clone, capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "verdict-H1-C1.md was modified outside `craft`" in r.stdout


@pytest.mark.checkpoint("7.4")
def test_32_researcher_attention_is_only_decisions(arc: Craft):
    r = arc("decisions", "--inv", INV)
    assert r.code == 0, r.text
    kinds = {line.split()[2] for line in r.out.splitlines() if line.strip()}
    assert kinds == {"acknowledge", "approve-problem", "approve-env", "close"}


def test_33_all_checkpoints_covered(request):
    missing = getattr(request.config, "_craft_missing", None)
    assert missing == [], f"checkpoints without a test: {missing}"
