"""A failed roll's alert names the recovery that fits how the run failed."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "roll-docket.yml"


def _jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def _step(job: str, name: str) -> dict:
    return next(step for step in _jobs()[job]["steps"] if step.get("name") == name)


def test_register_reports_its_push_before_anything_else_can_fail() -> None:
    outputs = _jobs()["register"]["outputs"]
    assert outputs["committed"] == "${{ steps.registration_commit.outputs.committed }}"
    assert outputs["pushed"] == "${{ steps.sync.outputs.pushed }}"
    sync = _step("register", "Synchronize, push, and bind registration commits")
    script = sync["run"]
    marker = 'echo "pushed=1" >> "$GITHUB_OUTPUT"'
    assert script.count(marker) == 1
    pushed = script.index(marker)
    assert script.index("push origin main") < pushed
    assert script.index('if [ "$REMOTE" = "$LOCAL" ]; then') < pushed
    assert pushed < script.index("install -m 0644")


def test_the_alert_reads_the_run_only_through_its_environment() -> None:
    alert = _step("publish", "Alert on failure")
    assert alert["if"] == "failure()"
    assert "${{" not in alert["run"]
    assert alert["env"]["REGISTRATIONS_PUSHED"] == (
        "${{ needs.register.outputs.committed == '1' && "
        "needs.register.outputs.pushed == '1' }}"
    )


def _alert_body(tmp_path: pathlib.Path, **state: str) -> str:
    script = tmp_path / "alert.sh"
    script.write_text(_step("publish", "Alert on failure")["run"])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'if [ "$1 $2" = "issue create" ]; then\n'
        '  while [ "$#" -gt 0 ]; do\n'
        '    if [ "$1" = "--body-file" ]; then cp "$2" "$ALERT_OUT"; fi\n'
        "    shift\n"
        "  done\n"
        "fi\n"
    )
    fake_gh.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "ALERT_OUT": str(tmp_path / "body.md"),
        "GH_TOKEN": "token",
        "GH_REPO": "owner/repo",
        "RUN_URL": "https://github.example/owner/repo/actions/runs/7",
        "RUN_ID": "7",
        "REGISTER_RESULT": "success",
        "GENERATE_RESULT": "success",
        "REGISTERED_COUNT": "3",
        "REGISTRATIONS_PUSHED": "true",
        "RETRY_BATCH": "",
        **state,
    }
    subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        env=env,
        check=True,
        timeout=60,
    )
    return (tmp_path / "body.md").read_text()


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize(
    ("state", "says", "never_says"),
    [
        (
            {},
            ["gh run rerun 7 --failed", "That publishes the same batch."],
            ["starts afresh"],
        ),
        (
            {"GENERATE_RESULT": "failure"},
            ["gh run rerun 7 --failed", "a fix on main does not reach it"],
            ["publishes the same batch", "starts afresh"],
        ),
        (
            {"REGISTER_RESULT": "failure", "GENERATE_RESULT": "skipped"},
            [
                "refuses these targets as already registered",
                "expired-unforecast-registrations.ts",
            ],
            ["gh run rerun", "starts afresh"],
        ),
        (
            {
                "REGISTER_RESULT": "failure",
                "GENERATE_RESULT": "skipped",
                "REGISTRATIONS_PUSHED": "false",
            },
            ["nothing persisted and the next roll starts afresh"],
            ["gh run rerun", "already registered"],
        ),
        (
            {"GENERATE_RESULT": "skipped", "REGISTERED_COUNT": "0"},
            ["registered nothing, so no target waits on a rerun"],
            ["gh run rerun"],
        ),
        (
            {
                "REGISTER_RESULT": "failure",
                "GENERATE_RESULT": "skipped",
                "REGISTRATIONS_PUSHED": "false",
                "RETRY_BATCH": "records/thesis-analyst/batches/2026-11-02/x.json",
            },
            ["retried records/thesis-analyst/batches/2026-11-02/x.json"],
            ["starts afresh"],
        ),
    ],
    ids=[
        "publish-failed",
        "generate-failed",
        "register-failed-after-push",
        "register-failed-before-push",
        "nothing-registered",
        "retry",
    ],
)
def test_the_alert_names_the_recovery_for_each_way_a_run_fails(
    tmp_path: pathlib.Path,
    state: dict[str, str],
    says: list[str],
    never_says: list[str],
) -> None:
    body = _alert_body(tmp_path, **state)
    assert body.startswith(
        "The auto-roll loop failed: https://github.example/owner/repo/actions/runs/7."
    )
    for text in says:
        assert text in body
    for text in never_says:
        assert text not in body
