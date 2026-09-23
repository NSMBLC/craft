"""The recommended acceptance run: one investigation through all seven journeys.

Tests run in file order and share one programme (module-scoped fixture). Each test is
marked with the checkpoints it demonstrates; conftest writes checkpoints.md from the marks.
"""

from __future__ import annotations

import json
import os
import subprocess
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
status: draft
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

# Hypothesis — inv-001
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
    assert not json.loads(arc.hook("Bash", command="craft approve problem").out.splitlines()[0])["hookSpecificOutput"]["permissionDecision"] == "allow"
    r = arc("approve", "problem")  # default env simulates the agent's Bash tool (CLAUDECODE set)
    assert r.code != 0 and "researcher decision" in r.err
    st = json.loads(arc("status", "--json").out)[INV]
    assert st["phase"] == "framing"
    # the agent cannot trigger the prompt hook itself either
    assert arc.hook("Bash", command="echo '{\"prompt\":\"craft approve problem\"}' | craft hook user-prompt-submit").code == 2
    # a natural-language request is not a decision: nothing happens
    r = arc.hook_event("user-prompt-submit", prompt="please approve the problem statement", hook_event_name="UserPromptSubmit")
    assert "<craft-decision>" not in r.out
    assert json.loads(arc("status", "--json").out)[INV]["phase"] == "framing"
    # status tells the researcher it is their turn
    r = arc.hook_event("user-prompt-submit", prompt="/craft-status", hook_event_name="UserPromptSubmit")
    assert "Waiting on the researcher: /craft-approve" in r.out
    # the researcher reads it (one page) and types the command as a message: the hook executes it
    r = arc.hook_event("user-prompt-submit", prompt="/craft-approve", hook_event_name="UserPromptSubmit")
    assert r.code == 0 and "<craft-decision>" in r.out and "Approved" in r.out and "Do NOT run the command yourself" in r.out
    assert "WAIT for the researcher" in r.out
    st = json.loads(arc("status", "--json").out)[INV]
    assert st["phase"] == "designing"
    # a second approval is refused with the phase reason
    r = arc.hook_event("user-prompt-submit", prompt="craft approve", hook_event_name="UserPromptSubmit")
    assert "REFUSED" in r.out and "nothing awaits your approve" in r.out and "designing" in r.out
    # read-only queries are answered by the hook, without the model
    r = arc.hook_event("user-prompt-submit", prompt="/craft-status", hook_event_name="UserPromptSubmit")
    assert "<craft-info>" in r.out and "Waiting on the agent: craft review" in r.out
    r = arc.hook_event("user-prompt-submit", prompt="/craft-help", hook_event_name="UserPromptSubmit")
    assert "<craft-info>" in r.out and "/craft-approve" in r.out and "/craft-resolve" in r.out
    p = arc.root / "investigations" / INV / "problem.md"
    assert not os.access(p, os.W_OK)
    # a hook-mediated edit of the approved statement is refused
    assert arc.hook("Edit", file_path=str(p), old_string="a", new_string="b").code == 2


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
    assert by["kim2024"]["does_not_cover"] and by["kim2024"]["fulltext_sha256"]


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
    p = arc.write(f"investigations/{INV}/hypothesis.md", HYP_ONE_RIVAL)
    r = arc("validate", "hypothesis", "--inv", INV)
    assert r.code != 0 and "INCOMPLETE" in r.out and "rivals" in r.out and "at least two" in r.out
    # review refuses an incomplete draft
    r = arc("review", "--inv", INV, env=fake(arc, "cycle1.json"))
    assert r.code != 0 and "not complete" in r.err
    # draft: editable, not binding
    assert arc.hook("Edit", file_path=str(p), old_string="a", new_string="b").code == 0
    assert os.access(p, os.W_OK)


# ---------------------------------------------------------------- Journey 5 (early) + 4

@pytest.mark.checkpoint("5.1")
def test_09_tasks_refused_before_review(arc: Craft):
    tasks = arc.root / "investigations" / INV / "tasks.md"
    r = arc.hook("Write", file_path=str(tasks), content="- [ ] run everything")
    assert r.code == 2
    out = json.loads(r.out.splitlines()[0])["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "review" in out["permissionDecisionReason"]
    assert not tasks.exists()
    # the shell route is screened too
    assert arc.hook("Bash", command=f"echo '- [ ] x' > {tasks}").code == 2


@pytest.mark.checkpoint("4.1")
def test_10_referee_sees_only_files(arc: Craft, monkeypatch):
    from craft.paths import InvestigationPaths
    from craft.referee import build_round1_prompt, _claude
    arc.write(f"investigations/{INV}/hypothesis.md", HYP_TWO_RIVALS)
    inv = InvestigationPaths(arc.root / "investigations" / INV)
    sys_p, user_p = build_round1_prompt(inv)
    assert "problem.md" in user_p and "hypothesis.md" in user_p and "sources.yaml" in user_p
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
    st = json.loads(arc("status", "--json").out)[INV]
    assert st["rounds"] == 0 and st["phase"] == "designing"
    r = arc("review", "--inv", INV, env=fake(arc, "cycle1.json"))
    assert r.code == 0, r.text
    rp = arc.root / "investigations" / INV / "review" / "round-1.json"
    data = json.loads(rp.read_text())
    o1 = next(o for o in data["objections"] if o["id"] == "O1")
    assert o1["severity"] == "blocking" and "tuning" in o1["statement"]
    assert o1["target"] == {"document": "hypothesis.md", "section": "criteria"}
    assert all({"id", "category", "severity", "target", "statement", "adequate_answer"} <= set(o) for o in data["objections"])
    from craft.artifacts.review import check_round1
    assert check_round1(data) == []
    assert not os.access(rp, os.W_OK)
    assert arc.hook("Write", file_path=str(rp), content="{}").code == 2


@pytest.mark.checkpoint("5.2")
def test_12_tasks_refused_while_blocking_open(arc: Craft):
    tasks = arc.root / "investigations" / INV / "tasks.md"
    r = arc.hook("Write", file_path=str(tasks), content="x")
    assert r.code == 2
    reason = json.loads(r.out.splitlines()[0])["hookSpecificOutput"]["permissionDecisionReason"]
    assert "O1" in reason and "O2" in reason and "respond" in reason
    assert not tasks.exists()


@pytest.mark.checkpoint("4.4")
def test_13_round2_accepts_fixes_escalates_handwave(arc: Craft):
    p = arc.root / "investigations" / INV / "hypothesis.md"
    assert arc.hook("Edit", file_path=str(p), old_string="a", new_string="b").code == 0  # editable while responding
    arc.write(f"investigations/{INV}/hypothesis.md", HYP_FIXED_O1)
    r = arc("review", "--inv", INV, env=fake(arc, "cycle1.json"))
    assert r.code != 0 and "missing responses for O1, O2" in r.err
    assert arc("review", "respond", "O1", "--pointer", "hypothesis.md#criteria", "--note", "equal 40-trial budget in every criterion's conditions; rival added", "--inv", INV).code == 0
    assert arc("review", "respond", "O2", "--pointer", "hypothesis.md#power", "--note", "we believe this is negligible", "--inv", INV).code == 0
    r = arc("review", "--inv", INV, env=fake(arc, "cycle1.json"))
    assert r.code == 0, r.text
    st = json.loads(arc("status", "--json").out)[INV]
    assert st["phase"] == "responding" and st["open_blocking"] == ["O2"] and st["rounds"] == 2


@pytest.mark.checkpoint("4.5")
def test_14_no_third_round(arc: Craft):
    r = arc("review", "--inv", INV, env=fake(arc, "cycle1.json"))
    assert r.code != 0 and "capped at 2 rounds" in r.err and "reopen review" in r.err
    st = json.loads(arc("status", "--json").out)[INV]
    assert st["rounds"] == 2 and st["phase"] == "responding"
    # reopen requires a genuine change, and is the researcher's
    r = arc("reopen", "review", "--note", "power fixed", "--inv", INV, human=True)
    assert r.code != 0 and "has not changed" in r.err
    arc.write(f"investigations/{INV}/hypothesis.md", HYP_FIXED_O2)
    r = arc("reopen", "review", "--note", "power fixed", "--inv", INV)
    assert r.code != 0 and "researcher decision" in r.err
    r = arc("reopen", "review", "--note", "power section now has a variance estimate", "--inv", INV, human=True)
    assert r.code == 0, r.text
    assert (arc.root / "investigations" / INV / "review" / "history-1" / "round-1.json").exists()


@pytest.mark.checkpoint("4.6", "4.7")
def test_15_clean_pass_freezes(arc: Craft):
    p = arc.root / "investigations" / INV / "hypothesis.md"
    r = arc("review", "--inv", INV, env=fake(arc, "cycle2.json"))
    assert r.code == 0, r.text
    assert "No blocking objections" in r.out and "2 advisory" in r.out and "FROZEN" in r.out
    st = json.loads(arc("status", "--json").out)[INV]
    assert st["phase"] == "frozen" and st["frozen_at"]
    assert not os.access(p, os.W_OK)
    data = json.loads((arc.root / "investigations" / INV / "review" / "round-1.json").read_text())
    assert data["no_blocking_objections"] is True and len(data["objections"]) == 2


@pytest.mark.checkpoint("5.3")
def test_16_tasks_now_simply_succeed(arc: Craft):
    tasks = arc.root / "investigations" / INV / "tasks.md"
    assert arc.hook("Write", file_path=str(tasks), content="- [ ] run C1..C3").code == 0
    arc.write(f"investigations/{INV}/tasks.md", "# Tasks\n- [ ] exp1: C1, C2\n- [ ] exp2: C3\n")
    st = json.loads(arc("status", "--json").out)[INV]
    assert st["phase"] == "executing"


@pytest.mark.checkpoint("5.5")
def test_17_frozen_document_cannot_be_modified_at_all(arc: Craft):
    p = arc.root / "investigations" / INV / "hypothesis.md"
    r = arc.hook("Edit", file_path=str(p), old_string="threshold: 1.5", new_string="threshold: 1.4")
    assert r.code == 2
    reason = json.loads(r.out.splitlines()[0])["hookSpecificOutput"]["permissionDecisionReason"]
    assert "frozen" in reason and "typo" in reason and "new investigation" in reason
    assert arc.hook("Bash", command=f"sed -i '' 's/1.5/1.4/' {p}").code == 2
    assert arc.hook("Bash", command=f"chmod 644 {p} && echo x >> {p}").code == 2
    with pytest.raises(PermissionError):
        p.write_text("tampered")
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
    ev = arc.write(f"investigations/{INV}/experiments/exp1/evidence/c1.json", json.dumps({
        "metric": "accuracy_gain", "values": [1.38, 1.42, 1.40, 1.41, 1.39], "seeds": [1, 2, 3, 4, 5], "data_id": "corpus-2026-09-snapshot"}))
    lock = arc.root / "investigations" / INV / "env.lock"
    assert arc.hook("Edit", file_path=str(lock), old_string="a", new_string="b").code == 2
    r = arc("propose", "package", "faiss-gpu", "--reason", "exp1 needs GPU index build", "--inv", INV)
    assert r.code == 0 and "halted" in r.out
    r = arc("verdict", "exp1", "--criterion", "C1", "--evidence", str(ev), "--inv", INV)
    assert r.code != 0 and "halted" in r.err
    r = arc("approve", "package", "--inv", INV)
    assert r.code != 0  # agent cannot
    r = arc.hook_event("user-prompt-submit", prompt=f"/craft-approve --inv {INV}", hook_event_name="UserPromptSubmit")
    assert "<craft-decision>" in r.out and "v2" in r.out
    st = json.loads(arc("status", "--json").out)[INV]
    assert st["env_version"] == 2


@pytest.mark.checkpoint("5.4", "6.2", "6.4")
def test_20_verdict_at_1_4_against_frozen_1_5_is_refuted(arc: Craft):
    ev = arc.root / "investigations" / INV / "experiments" / "exp1" / "evidence" / "c1.json"
    r = arc("verdict", "exp1", "--criterion", "C1", "--evidence", str(ev), "--inv", INV)
    assert r.code == 0, r.text
    assert "REFUTED" in r.out
    vf = arc.root / "investigations" / INV / "experiments" / "exp1" / "verdict-C1.md"
    fm, body = split_frontmatter(vf.read_text())
    assert fm["label"] == "refuted" and fm["threshold"] == 1.5 and abs(fm["observed"] - 1.40) < 1e-9
    assert fm["ci95"][0] < 1.40 < fm["ci95"][1] < 1.5
    assert fm["evidence"][0]["sha256"] == sha256_file(ev)
    assert fm["seeds"] == [1, 2, 3, 4, 5] and fm["data_ids"] == ["corpus-2026-09-snapshot"]
    assert fm["env_version"] == 2 and fm["hypothesis_sha256"]
    assert not os.access(vf, os.W_OK)
    # the label cannot be edited, and the threshold cannot be lowered
    assert arc.hook("Edit", file_path=str(vf), old_string="refuted", new_string="supported").code == 2
    hyp = arc.root / "investigations" / INV / "hypothesis.md"
    assert arc.hook("Edit", file_path=str(hyp), old_string="1.5", new_string="1.4").code == 2


@pytest.mark.checkpoint("6.3")
def test_21_exploratory_numbers_never_become_evidence(arc: Craft):
    expl = arc.write(f"investigations/{INV}/experiments/exp1/exploratory/sweep.json", json.dumps({
        "metric": "latency_ratio", "values": [0.9, 0.95, 0.92, 0.91, 0.93], "seeds": [1, 2, 3, 4, 5], "data_id": "corpus-2026-09-snapshot"}))
    r = arc("verdict", "exp1", "--criterion", "C2", "--evidence", str(expl), "--inv", INV)
    assert r.code != 0 and "exploratory" in r.err and "never evidence" in r.err
    ev = arc.write(f"investigations/{INV}/experiments/exp1/evidence/c2.json", json.dumps({
        "metric": "latency_ratio", "values": [1.05, 1.08, 1.06, 1.07, 1.04], "seeds": [1, 2, 3, 4, 5], "data_id": "corpus-2026-09-snapshot"}))
    r = arc("verdict", "exp1", "--criterion", "C2", "--evidence", str(ev), "--exploratory", str(expl), "--inv", INV)
    assert r.code == 0, r.text
    fm, body = split_frontmatter((arc.root / "investigations" / INV / "experiments" / "exp1" / "verdict-C2.md").read_text())
    assert fm["label"] == "supported" and abs(fm["observed"] - 1.06) < 1e-9
    assert fm["exploratory_links"] == ["experiments/exp1/exploratory/sweep.json"]
    assert "are evidence for any criterion" in fm["exploratory_note"] and "none" in fm["exploratory_note"]
    assert "0.9" not in json.dumps({k: v for k, v in fm.items() if k not in ("exploratory_links",)})


@pytest.mark.checkpoint("6.5")
def test_22_kill_criterion_halts_and_routes_to_closure(arc: Craft):
    ev = arc.write(f"investigations/{INV}/experiments/exp2/evidence/c3.json", json.dumps({
        "metrics": {"recall_at_10": {"values": [0.70, 0.72, 0.71, 0.69, 0.73]},
                    "pilot_loss": {"values": [6.1, 6.3, 6.0, 6.2, 6.4]}},
        "seeds": [1, 2, 3, 4, 5], "data_id": "corpus-2026-09-snapshot"}))
    r = arc("verdict", "exp2", "--criterion", "C3", "--evidence", str(ev), "--inv", INV)
    assert r.code == 0, r.text
    assert "KILL CRITERION K1 MET" in r.out and "halted" in r.out and "closure" in r.out
    st = json.loads(arc("status", "--json").out)[INV]
    assert st["phase"] == "closing" and st["kill"]["triggered"] and st["kill"]["criterion"] == "K1"
    # no more evidence is accepted
    assert arc.hook("Write", file_path=str(arc.root / "investigations" / INV / "experiments" / "exp3" / "evidence" / "x.json"), content="{}").code == 2


# ---------------------------------------------------------------- Journey 7

@pytest.mark.checkpoint("7.1")
def test_23_close_routes_mixed_outcome(arc: Craft):
    arc.write(f"investigations/{INV}/closure.md",
              "---\nanomalies:\n  - question: why does latency improve on the largest slice while recall collapses?\n    context: exp2 seeds 1-5\nnotes: closed after kill\n---\n# Closure\n")
    r = arc("close", "--inv", INV, "--note", "kill K1 met; C1 refuted, C2 supported")
    assert r.code != 0  # the agent cannot close
    r = arc("close", "--inv", INV, "--note", "kill K1 met; C1 refuted, C2 supported", human=True)
    assert r.code == 0, r.text
    findings = read_jsonl(arc.root / "memory" / "findings.jsonl")
    refuted = read_jsonl(arc.root / "memory" / "refuted.jsonl")
    open_q = read_jsonl(arc.root / "memory" / "open-questions.jsonl")
    assert [f["lineage"]["criterion"] for f in findings] == ["C2"]
    assert [r["id"] for r in refuted] == ["R-0001", "R-0002", "R-0003"]
    assert {r["lineage"]["criterion"] for r in refuted[1:]} == {"C1", "C3"}
    assert any("latency improve" in q["question"] for q in open_q) and any(q["question"].startswith("killed by K1") for q in open_q)
    assert not (arc.root / "investigations" / INV).exists()
    arch = arc.root / "archive" / INV
    assert (arch / "hypothesis.md").exists() and (arch / "experiments" / "exp1" / "verdict-C1.md").exists()
    assert not os.access(arch / "hypothesis.md", os.W_OK)
    assert findings[0]["lineage"]["verdict_file"].startswith(f"archive/{INV}/")


@pytest.mark.checkpoint("7.2")
def test_24_fresh_session_explains_every_link(arc: Craft):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CRAFT_PROGRAMME")}
    r = subprocess.run([sys.executable, "-m", "craft.cli", "explain", "F-0001"], cwd=arc.root, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Every link resolves" in r.stdout and r.stdout.count("resolves") >= 4
    r2 = arc.hook_event("user-prompt-submit", prompt="/craft-explain F-0001", hook_event_name="UserPromptSubmit")
    assert "<craft-info>" in r2.out and "Every link resolves" in r2.out
    assert "C2" in r.stdout and "archive/inv-001/experiments/exp1/evidence/c2.json" in r.stdout


@pytest.mark.checkpoint("7.3")
def test_25_fresh_session_refutation_blocks_new_work(arc: Craft):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CRAFT_PROGRAMME")}
    r = subprocess.run([sys.executable, "-m", "craft.cli", "new", "inv-003", "--topic", "method A accuracy advantage over baseline B on large inputs"],
                       cwd=arc.root, capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "R-0002" in r.stderr and "acknowledged" in r.stderr
    assert not (arc.root / "investigations" / "inv-003").exists()
    r = subprocess.run([sys.executable, "-m", "craft.cli", "recall", "collaborator suggests method A beats baseline B on large inputs"],
                       cwd=arc.root, capture_output=True, text=True, env=env)
    assert "R-0001" in r.stdout and "R-0002" in r.stdout


@pytest.mark.checkpoint("7.4")
def test_26_researcher_attention_is_only_decisions(arc: Craft):
    r = arc("decisions", "--inv", INV)
    assert r.code == 0, r.text
    kinds = {line.split()[2] for line in r.out.splitlines() if line.strip()}
    assert kinds == {"acknowledge", "approve-problem", "approve-env", "reopen", "close"}


def test_27_all_checkpoints_covered(request):
    missing = getattr(request.config, "_craft_missing", None)
    assert missing == [], f"checkpoints without a test: {missing}"
