from pathlib import PurePosixPath

import pytest

from craft.gate import decide_bash, decide_investigation_write, decide_write
from craft.paths import Programme
from craft.state import Phase, new_state


def st(phase: Phase, blocking=None):
    s = new_state("inv-1", "t")
    s.phase = phase
    if blocking:
        from craft.state import ReviewRound
        s.review.rounds.append(ReviewRound(n=1, when="x", backend="fake", hypothesis_sha256="h", blocking_open=blocking))
    return s


@pytest.mark.parametrize("phase,allowed", [
    (Phase.FRAMING, False), (Phase.DESIGNING, False), (Phase.RESPONDING, False),
    (Phase.FROZEN, True), (Phase.EXECUTING, True), (Phase.CLOSING, True), (Phase.CLOSED, False),
])
def test_tasks_gate(phase, allowed):
    d = decide_investigation_write(st(phase, ["O1"] if phase == Phase.RESPONDING else None), PurePosixPath("tasks.md"))
    assert d.allow is allowed
    if phase == Phase.DESIGNING:
        assert "review" in d.reason
    if phase == Phase.RESPONDING:
        assert "O1" in d.reason and "respond" in d.reason


@pytest.mark.parametrize("phase,allowed", [
    (Phase.FRAMING, False), (Phase.DESIGNING, True), (Phase.RESPONDING, True),
    (Phase.FROZEN, False), (Phase.EXECUTING, False),
])
def test_hypothesis_gate(phase, allowed):
    d = decide_investigation_write(st(phase), PurePosixPath("hypothesis.md"))
    assert d.allow is allowed
    if phase >= Phase.FROZEN:
        assert "frozen" in d.reason.lower() and "typo" in d.reason


def test_never_writable_paths():
    for p in ("state.json", "review/round-1.json", "experiments/e1/verdict-C1.md", "env.lock"):
        assert not decide_investigation_write(st(Phase.EXECUTING), PurePosixPath(p)).allow, p


def test_programme_level_paths(tmp_path):
    (tmp_path / "craft.yaml").write_text("version: 1\n")
    prog = Programme(tmp_path)
    assert not decide_write(prog, tmp_path / "memory" / "findings.jsonl").allow
    assert not decide_write(prog, tmp_path / "archive" / "x" / "a.md").allow
    assert not decide_write(prog, tmp_path / ".claude" / "settings.json").allow
    assert not decide_write(prog, tmp_path / "craft.yaml").allow
    assert decide_write(prog, tmp_path / "src" / "model.py").allow
    assert decide_write(prog, tmp_path.parent / "elsewhere.txt").allow


def test_bash_screen(tmp_path):
    (tmp_path / "craft.yaml").write_text("version: 1\n")
    prog = Programme(tmp_path)
    assert not decide_bash(prog, "craft approve problem", tmp_path).allow
    assert not decide_bash(prog, "cd x && craft  approve package", tmp_path).allow
    assert not decide_bash(prog, "craft resolve --note x", tmp_path).allow
    assert not decide_bash(prog, "CRAFT_ALLOW_NON_TTY=1 craft close", tmp_path).allow
    assert not decide_bash(prog, "echo {} | craft hook user-prompt-submit", tmp_path).allow
    assert not decide_bash(prog, "python -c 'import craft.hooks'", tmp_path).allow
    assert not decide_bash(prog, "echo '{}' >> memory/findings.jsonl", tmp_path).allow
    assert not decide_bash(prog, "sed -i '' 's/1.5/1.4/' investigations/inv-1/hypothesis.md", tmp_path).allow
    assert not decide_bash(prog, "chmod 644 investigations/inv-1/hypothesis.md", tmp_path).allow
    assert decide_bash(prog, "cat memory/findings.jsonl", tmp_path).allow
    assert decide_bash(prog, "craft status && craft recall 'x'", tmp_path).allow
    assert decide_bash(prog, "python train.py --out results/run1.json", tmp_path).allow


def test_bash_screen_ignores_harmless_redirects(tmp_path):
    (tmp_path / "craft.yaml").write_text("version: 1\n")
    prog = Programme(tmp_path)
    assert decide_bash(prog, "ls -la .claude 2>&1 | head", tmp_path).allow
    assert decide_bash(prog, "cat .claude/settings.json 2>/dev/null", tmp_path).allow
    assert decide_bash(prog, "craft verify >/dev/null 2>&1; cat memory/findings.jsonl", tmp_path).allow
    assert not decide_bash(prog, "echo x > .claude/settings.json 2>&1", tmp_path).allow
    assert not decide_bash(prog, "cat x >> memory/findings.jsonl", tmp_path).allow


def test_bash_screen_ignores_emails_and_arrows(tmp_path):
    (tmp_path / "craft.yaml").write_text("version: 1\n")
    prog = Programme(tmp_path.resolve())
    cmd = ('git add .claude CLAUDE.md craft.yaml memory && git commit -q -m "Initialize CRAFT scaffolding\n\n'
           'Co-Authored-By: Claude <noreply@anthropic.com>" && git log --oneline --stat | head -30')
    assert decide_bash(prog, cmd, tmp_path.resolve()).allow
    assert decide_bash(prog, 'git commit -m "craft init -> scaffolding; a => b" craft.yaml', tmp_path.resolve()).allow
    d = decide_bash(prog, "echo x > craft.yaml", tmp_path.resolve())
    assert not d.allow and "looked like a write because of `>`" in d.reason
