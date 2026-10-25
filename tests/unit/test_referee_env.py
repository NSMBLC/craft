"""The claude referee uses the researcher's login, not an API key that happens to be in the environment."""

import json
import subprocess

import pytest

from craft import referee


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def fake_run(args, **kw):
        seen["env"] = kw["env"]
        out = json.dumps({"structured_output": {"objections": []}})
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")

    monkeypatch.setattr(referee.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(referee.subprocess, "run", fake_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-test")
    monkeypatch.setenv("CLAUDECODE", "1")
    return seen


def test_api_keys_stripped_by_default(captured):
    referee._claude({}, "sys", "user", {})
    env = captured["env"]
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env
    assert "CLAUDECODE" not in env


def test_api_key_kept_when_opted_in(captured):
    referee._claude({"use_api_key": True}, "sys", "user", {})
    assert captured["env"]["ANTHROPIC_API_KEY"] == "sk-test"


def test_credential_note_only_when_billing_a_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert referee.credential_note({}, "claude") is None
    assert "billed" in referee.credential_note({"use_api_key": True}, "claude")
    assert referee.credential_note({"use_api_key": True}, "fake") is None
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert referee.credential_note({"use_api_key": True}, "claude") is None


def test_failure_hints_at_ignored_key(monkeypatch):
    monkeypatch.setattr(referee.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(referee.subprocess, "run",
                        lambda args, **kw: subprocess.CompletedProcess(args, 1, stdout="", stderr="not logged in"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with pytest.raises(referee.CraftError, match="use_api_key"):
        referee._claude({}, "sys", "user", {})
