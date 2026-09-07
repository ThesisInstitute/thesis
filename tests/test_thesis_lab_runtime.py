"""Install collision and durable stop semantics without touching real launchd."""

import json
import subprocess
from pathlib import Path

import pytest

from scripts import thesis_lab_runtime as runtime


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.setattr(runtime.os, "getuid", lambda: 501)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # Use a short socket root even on deeply nested pytest temporary paths.
    root = Path("/tmp/thesis-runtime-unit")
    return tmp_path, root


def test_service_collision_precedes_any_database_mutation(environment, monkeypatch):
    home, root = environment
    plists = home / "Library/LaunchAgents"
    plists.mkdir(parents=True)
    (plists / f"org.thesis.{root.name}.api.plist").write_text("existing service")
    monkeypatch.setattr(runtime, "loaded", lambda *args: False)
    monkeypatch.setattr(runtime, "run", lambda *args, **kwargs: pytest.fail("mutation"))
    with pytest.raises(SystemExit) as error:
        runtime.main(["install", "--root", str(root)])
    assert error.value.code == 2
    assert (
        plists / f"org.thesis.{root.name}.api.plist"
    ).read_text() == "existing service"


def test_loaded_label_without_plist_also_refuses(environment, monkeypatch):
    _, root = environment
    monkeypatch.setattr(runtime, "loaded", lambda *args: True)
    monkeypatch.setattr(runtime, "run", lambda *args, **kwargs: pytest.fail("mutation"))
    with pytest.raises(SystemExit):
        runtime.main(["install", "--root", str(root)])


def test_stop_disables_each_service_before_unloading(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.setattr(runtime.os, "getuid", lambda: 501)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = tmp_path / "runtime"
    root.mkdir()
    roles = ("postgres", "api", "site", "poll")
    labels = {role: f"org.thesis.runtime.{role}" for role in roles}
    payload = json.dumps({"root": str(root.resolve()), "labels": labels})
    (root / "runtime.json").write_text(payload)
    (root / "scientific-data").write_bytes(b"preserve")
    calls = []

    def fake(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(runtime, "run", fake)
    monkeypatch.setattr(runtime.subprocess, "run", fake)
    monkeypatch.setattr(runtime, "loaded", lambda *args: False)
    # This test never constructs a real socket; permit pytest's longer directory.
    assert runtime.main(["stop", "--root", str(root)]) == 0
    for index, role in enumerate(reversed(roles)):
        assert calls[index * 2] == ["launchctl", "disable", f"gui/501/{labels[role]}"]
        assert calls[index * 2 + 1] == [
            "launchctl",
            "bootout",
            f"gui/501/{labels[role]}",
        ]
    assert (root / "scientific-data").read_bytes() == b"preserve"
    assert (root / "runtime.json").read_text() == payload
