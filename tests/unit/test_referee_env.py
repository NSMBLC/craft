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


def test_credential_note(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert referee.credential_note({}, "claude") is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert "ignored" in referee.credential_note({}, "claude")
    assert "billed" in referee.credential_note({"use_api_key": True}, "claude")
    assert referee.credential_note({}, "fake") is None
