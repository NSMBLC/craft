from pathlib import PurePosixPath

import pytest

from craft.gate import decide_bash, decide_investigation_write, decide_write
from craft.paths import Programme
from craft.state import Phase, new_state


def st(phase: Phase, records=None):
    s = new_state("inv-1", "t")
    s.phase = phase
    s.records.update(records or {})
    return s


def gate(state, path, inv=None):
    return decide_investigation_write(state, PurePosixPath(path), inv)


@pytest.mark.parametrize("path", [
    "problem.md", "hypotheses/H1.md", "hypotheses/H9.md", "experiments/e1/plan.md", "experiments/e1/exploratory/x.json",
    "literature/sources.yaml", "literature/map.md", "questions.md", "closure.md", "tasks.md", "notes/idea.md", "src/run.py",
])
@pytest.mark.parametrize("phase", [Phase.FRAMING, Phase.OPEN, Phase.CLOSING])
def test_plans_stay_writable_until_closed(phase, path):
    assert gate(st(phase), path).allow, (phase, path)
    assert not gate(st(Phase.CLOSED), path).allow


def test_records_are_never_writable():
    s = st(Phase.OPEN, {"experiments/e1/evidence/c1.json": "x", "review/H1/round-1-responses.md": "y"})
    for p in ("state.json", "review/H1/round-1.json", "review/H1/round-1.prompt.md", "review/H1/registered.md",
              "review/H1/round-1-responses.md", "experiments/e1/verdict-H1-C1.md", "experiments/e1/verdict-K1.md",
              "env.lock", "env.proposal.yaml", "experiments/e1/evidence/c1.json"):
        assert not gate(s, p).allow, p
    assert "post-hoc" in gate(s, "review/H1/registered.md").reason
    assert "cites" in gate(s, "experiments/e1/evidence/c1.json").reason
    # uncited evidence for an unplanned experiment (e.g. a kill-criterion pilot) is fine
    assert gate(s, "experiments/e1/evidence/c2.json").allow


def test_evidence_gate_follows_the_plan(tmp_path):
    from craft.paths import InvestigationPaths
    from craft.state import ReviewRound

    inv = InvestigationPaths(tmp_path)
    (tmp_path / "hypotheses").mkdir()
    (tmp_path / "hypotheses" / "H1.md").write_text("---\nclaim: x\ncriteria:\n  - {name: C1, metric: m, op: '>=', threshold: 1, conditions: c}\n---\n")
    plan = tmp_path / "experiments" / "e1" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ndescription: d\ntests: [H1]\n---\n")
    s = st(Phase.OPEN)
    d = gate(s, "experiments/e1/evidence/c1.json", inv)
    assert not d.allow and "draft" in d.reason and d.checkpoint == "5.1"
    s.hyp("H1").rounds.append(ReviewRound(n=1, when="x", backend="fake", hypothesis_sha256="h", blocking_open=["O1"]))
    d = gate(s, "experiments/e1/evidence/c1.json", inv)
    assert not d.allow and "O1" in d.reason and d.checkpoint == "5.2"
    s.hyp("H1").registered_sha256 = "abc"
    assert gate(s, "experiments/e1/evidence/c1.json", inv).allow
    assert not gate(st(Phase.FRAMING), "experiments/e1/evidence/c1.json", inv).allow
    assert not gate(st(Phase.CLOSING), "experiments/e1/evidence/c1.json", inv).allow
    plan.write_text("---\ndescription: d\nexploratory: true\n---\n")
    assert gate(s, "experiments/e1/evidence/c1.json", inv).checkpoint == "6.3"


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


def test_bash_screen_matches_decision_subcommands_not_words(tmp_path):
    (tmp_path / "craft.yaml").write_text("version: 1\n")
    prog = Programme(tmp_path)
    for cmd in ("craft correct Q-0001 --note x", "uv run craft close", "python -m craft.cli resolve --note x",
                "craft 'approve' problem", "cd x; craft reject --note y"):
        assert not decide_bash(prog, cmd, tmp_path).allow, cmd
    for cmd in ('craft propose package scipy --reason "the old build would reject float128"',
                'craft limitation exp1 --criterion H1:C1 --text "close to the threshold; correct only in simulation" --source x',
                "grep -n approve docs/journeys.md"):
        assert decide_bash(prog, cmd, tmp_path).allow, cmd


def test_bash_screen_reads_open_modes_not_paths(tmp_path):
    from craft.gate import HARMLESS_REDIRECT_RE, MUTATION_RE

    def writes(cmd):
        return bool(MUTATION_RE.search(HARMLESS_REDIRECT_RE.sub(" ", cmd)))

    for cmd in ("python -c \"print(open('archive/x/verdict.md').read())\"",
                "python -c \"json.load(open('investigations/i/experiments/e/evidence/a.json'))\"",
                "python -c \"open('weights.csv', 'rb').read()\"", "python -c \"open(p, encoding='utf-8')\"",
                "python -c \"Path('a.json').open()\""):
        assert not writes(cmd), cmd
    for cmd in ("python -c \"open('x.json', 'w')\"", "python -c \"open(p, mode='a')\"", "python -c \"open(p, 'r+')\"",
                "python -c \"Path(p).open('wb')\"", "python -c \"open(p, 'x')\""):
        assert writes(cmd), cmd


def test_bash_screen_copy_reads_sources_writes_destination(tmp_path):
    root = tmp_path.resolve()
    (root / "craft.yaml").write_text("version: 1\n")
    (root / "archive").mkdir()
    prog = Programme(root)
    assert decide_bash(prog, "mkdir -p notes/lit && cp archive/inv-1/literature/kim.pdf notes/lit/", root).allow
    assert decide_bash(prog, "rsync -a archive/inv-1/literature/ notes/lit/", root).allow
    assert decide_bash(prog, "cp -t notes/lit archive/inv-1/a.pdf archive/inv-1/b.pdf", root).allow
    assert not decide_bash(prog, "cp notes/x.json archive/inv-1/verdict.md", root).allow
    assert not decide_bash(prog, "cp -t archive/inv-1 notes/x.json", root).allow
    assert not decide_bash(prog, "cp a.txt b.txt > memory/findings.jsonl", root).allow
    assert not decide_bash(prog, "mv archive/inv-1/a.pdf notes/", root).allow  # mv removes its source
    for cmd in ('for f in archive/inv-1/literature/*.pdf; do cp "$f" notes/lit/; done',
                "find archive/inv-1/literature -name '*.pdf' -exec cp {} notes/lit/ \\;",
                "ls archive/inv-1/literature/*.pdf | xargs -I {} cp {} notes/lit/",
                "ls archive/inv-1/*.pdf | xargs cp -t notes/lit",
                "cd archive/inv-1 && cp literature/kim.pdf ../../notes/lit/",
                "cp archive/inv-1/literature/kim.pdf notes/lit/ && ls archive/inv-1/literature"):
        assert decide_bash(prog, cmd, root).allow, cmd
    for cmd in ('for f in archive/inv-1/*.md; do rm "$f"; done', "ls archive/inv-1/*.md | xargs rm",
                "cd archive/inv-1 && rm verdict.md", "cd archive && echo x > inv-1/a.md",
                "find archive/inv-1 -name '*.md' -exec rm {} \\;", "ls notes | xargs cp archive/inv-1",
                "cp notes/a.md notes/b.md && mv notes/b.md archive/inv-1/"):
        assert not decide_bash(prog, cmd, root).allow, cmd


def test_bash_screen_reads_inline_python_and_heredocs(tmp_path):
    root = tmp_path.resolve()
    (root / "craft.yaml").write_text("version: 1\n")
    (root / "archive").mkdir()
    (root / "notes").mkdir()
    prog = Programme(root)
    allowed = [
        "mkdir -p notes/lit && python3 - <<'EOF'\nimport yaml, shutil\nfrom pathlib import Path\n"
        "src = Path('archive/inv-1/literature')\ndst = Path('notes/lit')\n"
        "for s in yaml.safe_load(open(src / 'sources.yaml'))['sources']:\n"
        "    shutil.copy2(src / s['file'], dst / Path(s['file']).name)\nEOF",
        "python3 -c \"import json; d=json.load(open('archive/inv-1/x.json')); open('notes/o.json','w').write(str(d))\"",
        "cat > notes/readme.md <<EOF\nwe will mv archive/inv-1/verdict.md later; craft approve\nEOF",
        "uv run python - <<EOF\nprint(open('archive/inv-1/x.md').read().replace('a', 'b'))\nEOF",
        "grep -ln accuracy archive/inv-1/experiments/*/verdict-*.md",
        "echo x > notes/a.txt && cat craft.yaml",
    ]
    for cmd in allowed:
        assert decide_bash(prog, cmd, root).allow, cmd
    refused = [
        "python3 - <<'EOF'\nopen('archive/inv-1/verdict.md', 'w').write('x')\nEOF",
        "python3 -c \"import shutil; shutil.copy('notes/a.md', 'archive/inv-1/a.md')\"",
        "python3 - <<'EOF'\nimport os, sys\nos.remove(sys.argv[1] if len(sys.argv) > 1 else 'archive/inv-1/x.md')\nEOF",
        "bash <<'EOF'\nrm archive/inv-1/x.md\nEOF",
        "python3 - <<'EOF'\nfrom pathlib import Path\nfor p in Path('archive/inv-1').glob('*.md'):\n    p.write_text('')\nEOF",
        "bash <<'EOF'\ncraft approve\nEOF",
    ]
    for cmd in refused:
        assert not decide_bash(prog, cmd, root).allow, cmd


def test_bash_screen_reads_each_line_as_its_own_command(tmp_path):
    root = tmp_path.resolve()
    (root / "craft.yaml").write_text("version: 1\n")
    (root / "archive").mkdir()
    prog = Programme(root)
    for cmd in ("rm notes/tmp.txt\ncat archive/inv-1/verdict.md",
                "# tidy up, then read archive/inv-1\nrm -f notes/tmp.txt\nls archive/inv-1",
                "cp archive/inv-1/a.pdf \\\n   notes/lit/\nwc -l archive/inv-1/b.md",
                "python3 -c 'import json\nprint(json.load(open(\"archive/inv-1/x.json\")))'\nrm notes/tmp.txt"):
        assert decide_bash(prog, cmd, root).allow, cmd
    for cmd in ("ls archive\nrm archive/inv-1/verdict.md", "echo x \\\n  > archive/inv-1/a.md",
                "cat notes/a.md\nmv notes/a.md archive/inv-1/", "echo '#not a comment' > memory/findings.jsonl"):
        assert not decide_bash(prog, cmd, root).allow, cmd


def test_inline_python_traces_writes_through_functions():
    from craft.pyscan import write_targets

    code = ("import shutil\nfrom pathlib import Path\n"
            "def save(text, path):\n    Path(path).write_text(text)\n"
            "save(Path('archive/inv-1/a.md').read_text(), 'notes/a.md')\n")
    assert write_targets(code) == ["notes/a.md"]
    code = "def out(p='notes/o.json'):\n    open(p, 'w').write('x')\nout()\n"
    assert write_targets(code) == ["notes/o.json"]
    # untraced target: only paths held in names or in the target itself count, never an inline read
    code = "import sys\nsrc = 'notes/in.md'\nt = open('archive/inv-1/a.md').read()\nopen(sys.argv[1], 'w').write(t)\n"
    assert write_targets(code) == ["notes/in.md"]
    code = "import os\nos.remove(os.environ.get('X', 'archive/inv-1/x.md'))\n"
    assert "archive/inv-1/x.md" in write_targets(code)
