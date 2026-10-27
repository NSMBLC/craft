import json


def test_init_strips_stale_write_rules_and_is_idempotent(tmp_path):
    from tests.conftest import Craft
    root = tmp_path / "p"
    root.mkdir()
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text(json.dumps({
        "permissions": {"deny": ["Write(./memory/**)", "Edit(./memory/**)", "Bash(rm -rf *)"]},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}]},
    }))
    c = Craft(root)
    assert c("init", "--path", str(root)).code == 0
    s = json.loads((root / ".claude" / "settings.json").read_text())
    deny = s["permissions"]["deny"]
    assert not any(r.startswith("Write(") for r in deny)
    assert "Bash(rm -rf *)" in deny and "Edit(./.claude/**)" in deny and "Edit(./memory/**)" in deny
    assert "Bash(craft status:*)" in s["permissions"]["allow"] and "Edit(./investigations/**)" in s["permissions"]["allow"] and "Bash(craft approve:*)" not in s["permissions"]["allow"]
    cmds = [h["command"] for g in s["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert "echo mine" in cmds and cmds.count("craft hook pre-tool-use") == 2
    r = c("init", "--path", str(root))
    assert "nothing to do" in r.out


def test_init_refreshes_claude_md_block_but_keeps_user_text(tmp_path):
    from tests.conftest import Craft
    root = tmp_path / "p"
    root.mkdir()
    (root / "CLAUDE.md").write_text("# My notes\nkeep me\n\n<!-- craft:begin -->\nold playbook\n<!-- craft:end -->\n\n# After\nalso keep\n")
    c = Craft(root)
    r = c("init", "--path", str(root))
    assert "refreshed CRAFT block" in r.out
    text = (root / "CLAUDE.md").read_text()
    assert "keep me" in text and "also keep" in text and "old playbook" not in text and "Kill criteria" in text
    assert text.count("<!-- craft:begin -->") == 1
    assert "nothing to do" in c("init", "--path", str(root)).out


def test_init_installs_decision_skills(tmp_path):
    from tests.conftest import Craft
    root = tmp_path / "p"; root.mkdir()
    c = Craft(root)
    assert c("init", "--path", str(root)).code == 0
    for name in ("craft", "craft-approve", "craft-reject", "craft-close", "craft-reopen", "craft-resolve", "craft-status", "craft-help", "craft-decisions", "craft-explain"):
        assert (root / ".claude" / "skills" / name / "SKILL.md").exists(), name
    assert "nothing to do" in c("init", "--path", str(root)).out


def test_init_stamps_the_version_and_reports_where_it_came_from(tmp_path):
    from craft import __version__
    from tests.conftest import Craft
    root = tmp_path / "p"
    root.mkdir()
    c = Craft(root)
    assert c("--version").out.strip() == f"craft {__version__}"
    assert c("init", "--path", str(root)).code == 0
    cfg = root / "craft.yaml"
    assert f'craft_version: "{__version__}"' in cfg.read_text()
    cfg.write_text(cfg.read_text().replace(f'"{__version__}"', '"0.0.1"') + "# mine\n")
    r = c("init", "--path", str(root))
    assert f"from CRAFT 0.0.1 to {__version__}" in r.out and "# mine" in cfg.read_text()
    assert cfg.read_text().count("craft_version:") == 1
    assert "nothing to do" in c("init", "--path", str(root)).out
