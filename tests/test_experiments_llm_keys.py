"""API keys for brier.experiments.llm: the environment wins, then `agent-secret get`."""

import subprocess

import pytest

from brier.experiments import llm


class FakeRun:
    def __init__(self, stdout="", returncode=0, exc=None):
        self.calls = []
        self.stdout, self.returncode, self.exc = stdout, returncode, exc

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(
            args, self.returncode, stdout=self.stdout, stderr=""
        )


@pytest.mark.parametrize(
    "loader,name",
    [
        (llm._load_anthropic_key, "ANTHROPIC_API_KEY"),
        (llm._load_openai_key, "OPENAI_API_KEY"),
    ],
)
def test_env_wins_without_a_subprocess(monkeypatch, loader, name):
    monkeypatch.setenv(name, "from-env")
    fake = FakeRun(stdout="from-keychain\n")
    monkeypatch.setattr(llm.subprocess, "run", fake)
    assert loader() == "from-env"
    assert fake.calls == []


@pytest.mark.parametrize(
    "loader,name",
    [
        (llm._load_anthropic_key, "ANTHROPIC_API_KEY"),
        (llm._load_openai_key, "OPENAI_API_KEY"),
    ],
)
def test_falls_back_to_agent_secret(monkeypatch, loader, name):
    monkeypatch.delenv(name, raising=False)
    fake = FakeRun(stdout="from-keychain\n")
    monkeypatch.setattr(llm.subprocess, "run", fake)
    assert loader() == "from-keychain"
    assert fake.calls == [["agent-secret", "get", name]]


@pytest.mark.parametrize(
    "fake",
    [
        FakeRun(returncode=44),
        FakeRun(stdout="  \n"),
        FakeRun(exc=FileNotFoundError()),
        FakeRun(exc=subprocess.TimeoutExpired("agent-secret", 30)),
    ],
)
def test_missing_key_names_agent_secret(monkeypatch, fake):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(llm.subprocess, "run", fake)
    with pytest.raises(RuntimeError, match="agent-secret set ANTHROPIC_API_KEY"):
        llm._load_anthropic_key()
