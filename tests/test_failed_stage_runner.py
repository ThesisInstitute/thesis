"""A run that fails for any reason other than cell validation is a failed
trace the publisher retains.

The publisher replays the cell validator on every sealed cells payload and
refuses the whole batch when the replay disagrees with the run's status
("validator status mismatch"). A run whose stage failed (nonzero exit,
timeout, ticket stream-binding refusal, tool evidence, workspace mutation)
used to seal ok:false beside cells that validate, so one such run refused
every other forecast in its batch. These tests run the real runner, custody,
and publisher on each such failure, check the invariants over every
stage-outcome combination, and check that custody refuses forged records.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_thesis_analyst as runner  # noqa: E402
from verify_custody import CustodyError, verify_run  # noqa: E402

from tests.test_thesis_analyst_runner import (  # noqa: E402
    generation_ticket_context,
    review_test_cell,
    write_fake_codex,
)

RUNNER = ROOT / "scripts/run_thesis_analyst.py"
RUN_RELATIVE = "records/thesis-analyst/2030-01-10/2030-01-10t12-00-00z-failed-stage"
VALID_CELL = review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9)
# Parses, normalizes and seals, then fails trace-depth validation.
SHALLOW_CELL = {**VALID_CELL, "reasoning": VALID_CELL["reasoning"][:2]}
OUTPUTS = {
    "valid": json.dumps(VALID_CELL),
    "invalid": json.dumps(SHALLOW_CELL),
    "unparseable": "No forecast today.",
}
REVIEW = json.dumps(
    {
        "summary": "Publishable as drafted.",
        "requiredFixes": [],
        "optionalSuggestions": [],
    }
)
POST_PARSE_ARTIFACTS = (
    "parsed_cells.json",
    "normalized_cells.json",
    "distribution.json",
    "validation.json",
    "cells.with_activity.json",
)
STAGE_PREFIXES = ("draft_", "pre_submit_review_", "")


def _command(tmp_path: Path, name: str, *, text: str, exit_code: int = 0, **kw) -> str:
    """A fake agent command. It prints ``revision_text`` and exits
    ``revision_exit`` when given the revision prompt, and can hang after
    printing so the runner's timeout fires."""

    script = tmp_path / f"{name}.py"
    script.write_text(
        "\n".join(
            [
                "import sys, time",
                "revision = 'Pre-submit review loop' in sys.stdin.read()",
                f"print({kw.get('revision_text', text)!r} if revision else {text!r},"
                " flush=True)",
                f"if {kw.get('hang', False)!r}:",
                "    time.sleep(30)",
                f"sys.exit({kw.get('revision_exit', exit_code)} if revision"
                f" else {exit_code})",
            ]
        )
        + "\n"
    )
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"


def _codex_env(tmp_path: Path, extra_lines: list[str]) -> dict[str, str]:
    auth = tmp_path / "auth"
    auth.mkdir(exist_ok=True)
    (auth / "auth.json").write_text("{}\n")
    codex = tmp_path / "codex"
    write_fake_codex(codex, VALID_CELL, extra_lines=extra_lines)
    return {"THESIS_CODEX_BIN": str(codex), "CODEX_HOME": str(auth)}


def _run(
    out_dir: Path, args: list[str], env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            *args,
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        timeout=300,
    )


def _publish_one(monkeypatch, staged: Path, manifest: dict[str, Any], ok: bool):
    """Run the real publisher validation on a one-result batch.

    Registration binding and the repo-relative file inventory need a
    registered target and repo-relative artifact paths (these runs live
    outside the checkout); custody and the validator replay stay real.
    """

    import docket_publication

    batch_relative = "records/thesis-analyst/batches/2030-01-10/run.json"
    batch_path = staged / batch_relative
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_batch_manifest_v1",
                "promptMode": manifest["promptMode"],
                "startedAt": "2030-01-10T12:00:00Z",
                "finishedAt": "2030-01-10T12:02:00Z",
                "results": [
                    {
                        "ok": ok,
                        "cellsPath": manifest["cellsPath"],
                        "manifestPath": f"{RUN_RELATIVE}/manifest.json",
                        "target": {},
                        "startedAt": "2030-01-10T12:00:00Z",
                        "finishedAt": "2030-01-10T12:01:00Z",
                    }
                ],
            }
        )
        + "\n"
    )
    monkeypatch.setattr(
        docket_publication, "validate_run_file_inventory", lambda *_args: None
    )
    monkeypatch.setattr(
        docket_publication, "validate_run_binding", lambda *_args, **_kwargs: None
    )
    docket_publication.validate_cells(staged, batch_relative)


def _publisher_replay_ok(out_dir: Path, manifest: dict[str, Any]) -> bool:
    """What the publisher's validator replay says about a sealed payload,
    called with the arguments docket_publication.validate_cells passes."""

    cells = json.loads((out_dir / "cells.with_activity.json").read_text())
    agent = manifest.get("agent") or {}
    report = runner.validate_cells(
        cells,
        target_context=manifest.get("targetContext") or {},
        prompt_mode=manifest["promptMode"],
        generation_ticket=manifest.get("generationTicket"),
        agent_version=agent.get("agentVersion"),
        checkout_sha=manifest.get("checkoutSha"),
        series=manifest.get("series"),
        target_period=manifest.get("period"),
        history_registry_root=ROOT,
    )
    return bool(report["ok"])


# --- End to end: each failure is a failed trace the publisher retains -------

PROBE = f"hygiene-probe-{uuid.uuid4().hex}.txt"
# 100 levels of this name is a path longer than PATH_MAX on Linux and macOS.
DEEP = "d" * 60


def _hygiene_case(*lines: str) -> dict[str, Any]:
    return {
        "codex": list(lines),
        "args": ["--codex-model", "test-model", "--codex-sandbox", "workspace-write"],
        "phase": "workspace_hygiene",
    }


CASES: dict[str, dict[str, Any]] = {
    "codex-exits-nonzero-after-output": {
        "codex": [
            "import atexit, os",
            "atexit.register(lambda: (sys.stdout.flush(), os._exit(3)))",
        ],
        "args": ["--codex-model", "test-model"],
        "phase": "command",
        "message": "agent command exited 3",
    },
    "ticket-stream-binding-refused": {
        # The -o last message holds valid cells; the stream ends on another
        # message, so ticket mode refuses the stage.
        "codex": [
            "import atexit",
            "atexit.register(lambda: print(json.dumps({'type': 'item.completed',"
            " 'item': {'type': 'agent_message', 'text': 'a later message'}})))",
        ],
        "args": ["--codex-model", "test-model", "--ticket"],
        "phase": "command",
        "message": "agent command exited 1: ticket mode refused successful Codex "
        "stage because raw JSONL and the codex_last_message artifact disagree",
    },
    "command-exits-nonzero-after-output": {
        "forecaster": {"exit_code": 2},
        "phase": "command",
        "message": "agent command exited 2",
    },
    "command-times-out-after-output": {
        "forecaster": {"hang": True},
        "args": ["--timeout-seconds", "2"],
        "phase": "command",
        "message": "agent command exited 124 after timing out",
    },
    "draft-fails-after-output": {
        "forecaster": {"exit_code": 2},
        "reviewer": 0,
        "phase": "command",
        "message": "draft forecaster exited 2",
    },
    "reviewer-fails": {
        "forecaster": {},
        "reviewer": 1,
        "phase": "command",
        "message": "pre-submit reviewer exited 1",
    },
    "revision-fails-after-output": {
        "forecaster": {"revision_exit": 4},
        "reviewer": 0,
        "phase": "command",
        "message": "revision forecaster exited 4",
    },
    "workspace-tree-mutated": _hygiene_case(
        f"pathlib.Path({str(ROOT / PROBE)!r}).write_text('agent wrote this')"
    ),
    "run-dir-file-planted": _hygiene_case(
        "(last_message.parent / 'planted.txt').write_text('agent wrote this')"
    ),
    "run-dir-artifact-tampered": _hygiene_case(
        "prompt_md = last_message.parent / 'prompt.md'",
        "prompt_md.write_text(prompt_md.read_text() + 'tampered')",
    ),
    "run-dir-artifact-made-executable": _hygiene_case(
        "(last_message.parent / 'prompt.md').chmod(0o755)",
    ),
    "run-dir-locked-down": _hygiene_case(
        # A directory the runner cannot list, inside a run dir it cannot
        # write, both left behind once the agent's last message is written.
        "import atexit",
        "junk = last_message.parent / 'junk'",
        "junk.mkdir()",
        "(junk / 'inner.txt').write_text('x')",
        "junk.chmod(0)",
        "atexit.register(lambda: last_message.parent.chmod(0o555))",
    ),
    "run-dir-removed": _hygiene_case(
        # The whole run dir, last message included, gone once the stage ends:
        # a guard violation, not a missing codex CLI.
        "import atexit, shutil",
        "atexit.register(lambda: shutil.rmtree(last_message.parent))",
    ),
    "run-dir-link-planted-under-artifact-name": _hygiene_case(
        # A link where the runner will write stdout.txt: without the guard
        # putting the run dir back, the runner writes through it.
        "outside = last_message.parent.parents[4] / 'outside.txt'",
        "(last_message.parent / 'stdout.txt').symlink_to(outside)",
    ),
    "plant-then-exit-nonzero": _hygiene_case(
        # Both a mutation and a failed exit: the mutation is what is recorded.
        "(last_message.parent / 'planted.txt').write_text('agent wrote this')",
        "import atexit, os",
        "atexit.register(lambda: (sys.stdout.flush(), os._exit(3)))",
    ),
    "reviewed-draft-mutates": {
        # The flow stops at the stage that mutated: the reviewer never runs on
        # top of what the draft left.
        **_hygiene_case(
            "(last_message.parent / 'planted.txt').write_text('agent wrote this')"
        ),
        "reviewer": 0,
        "absent": [
            "pre_submit_review_prompt.md",
            "pre_submit_review_command.json",
            "command.json",
        ],
    },
    "run-dir-replaced-by-link": {
        # The run dir becomes a link to a directory outside it. The guard
        # rebuilds a real run dir and never writes or removes through the link.
        **_hygiene_case(
            "import atexit, shutil",
            "sibling = last_message.parent.parents[4] / 'sibling'",
            "def swap():",
            "    sibling.mkdir()",
            "    (sibling / 'keep.txt').write_text('untouched')",
            "    shutil.rmtree(last_message.parent)",
            "    last_message.parent.symlink_to(sibling)",
            "atexit.register(swap)",
        ),
        "mutation": "run directory replaced or removed during agent stage",
        "sibling": ["keep.txt"],
    },
    "last-message-not-plain": {
        # A stage output the runner could not rewrite as its own is not kept.
        **_hygiene_case(
            "import atexit",
            "atexit.register(lambda: last_message.chmod(0o500))",
        ),
        "mutation": "stage output is not a plain readable file after agent stage: "
        "codex_last_message.txt",
    },
    "capture-files-deleted-beside-a-link": {
        # The stage removes the runner's stdout/stderr captures (TMPDIR is
        # writable to it) and plants a link: the guard still runs.
        **_hygiene_case(
            "import os",
            "def capture_path(fd):",
            "    proc = f'/proc/self/fd/{fd}'",
            "    if os.path.exists(proc):",
            "        return os.readlink(proc)",
            "    import fcntl",
            "    return fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))"
            ".split(b'\\0')[0].decode()",
            "for fd in (1, 2):",
            "    os.unlink(capture_path(fd))",
            "outside = last_message.parent.parents[4] / 'outside.txt'",
            "(last_message.parent / 'stdout.txt').symlink_to(outside)",
        ),
        "mutation": "unexpected file created in run dir during agent stage: stdout.txt",
    },
    "run-dir-chain-past-path-max": {
        # Deeper than any path the runner could name: it is removed through
        # descriptors, not paths, so the rebuild still completes.
        **_hygiene_case(
            "import os",
            "fd = os.open(last_message.parent, os.O_RDONLY)",
            "for _ in range(100):",
            f"    os.mkdir({DEEP!r}, dir_fd=fd)",
            f"    child = os.open({DEEP!r}, os.O_RDONLY, dir_fd=fd)",
            "    os.close(fd)",
            "    fd = child",
            "os.close(fd)",
        ),
        "mutation": f"unexpected file created in run dir during agent stage: {DEEP}",
    },
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_failed_stage_is_a_failed_trace_the_publisher_retains(
    tmp_path, monkeypatch, name
):
    case = CASES[name]
    staged = tmp_path / "staged"
    out_dir = staged / RUN_RELATIVE
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched\n")
    args = list(case.get("args", []))
    env = _codex_env(tmp_path, case["codex"]) if "codex" in case else None
    if "--ticket" in args:
        ticket = generation_ticket_context()
        args.remove("--ticket")
        args += ["--ticket-id", ticket["ticketId"], "--ticket-path"]
        args += [ticket["ticketPath"], "--ticket-nonce", ticket["nonce"]]
    if "forecaster" in case:
        forecaster = case["forecaster"]
        args += [
            "--command",
            _command(tmp_path, "agent", text=OUTPUTS["valid"], **forecaster),
        ]
    if "reviewer" in case:
        args += [
            "--pre-submit-review-command",
            _command(tmp_path, "reviewer", text=REVIEW, exit_code=case["reviewer"]),
        ]
    try:
        completed = _run(out_dir, args, env)
    finally:
        (ROOT / PROBE).unlink(missing_ok=True)
    assert completed.returncode == 1, completed.stderr[-2000:]

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    assert manifest["cellsPath"] is None
    assert manifest["validation"] is None
    error = manifest["error"]
    assert error["phase"] == case["phase"]
    if case["phase"] == "workspace_hygiene":
        mutations = manifest["workspaceHygiene"]["mutations"]
        assert mutations
        assert error["message"] == (
            f"agent stage mutated the workspace ({len(mutations)} violation(s)): "
            f"{mutations[0]}"
        )
        assert case.get("mutation", mutations[0]) in mutations
    else:
        assert error["message"] == case["message"]
    # The stage's output survives as the raw response, cells and all; nothing
    # downstream of parsing is sealed.
    raw = (out_dir / "raw_response.txt").read_text()
    assert runner.extract_json_payload(raw) == [VALID_CELL]
    for artifact in POST_PARSE_ARTIFACTS:
        assert not (out_dir / artifact).exists(), artifact
    # The run dir is exactly what the runner wrote: the agent's plants are
    # gone, its edits undone, and nothing was written through a link.
    assert out_dir.is_dir() and not out_dir.is_symlink()
    assert not (out_dir / "planted.txt").exists()
    assert not (out_dir / DEEP).exists()
    assert not (out_dir / "prompt.md").read_text().endswith("tampered")
    assert not os.access(out_dir / "prompt.md", os.X_OK)
    assert not (out_dir / "stdout.txt").is_symlink()
    assert outside.read_text() == "untouched\n"
    # Nothing of the stage's tree is left beside the run dir either.
    assert not [name for name in os.listdir(out_dir.parent) if ".stage-" in name]
    for name in case.get("absent", []):
        assert not (out_dir / name).exists(), name
    if "sibling" in case:
        sibling = tmp_path / "sibling"
        assert sorted(os.listdir(sibling)) == case["sibling"]
        assert (sibling / "keep.txt").read_text() == "untouched"

    verification = verify_run(out_dir)
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is False
    assert not verification.headline_eligible
    _publish_one(monkeypatch, staged, manifest, ok=False)


def test_run_dir_whose_path_changed_ends_with_no_record(tmp_path):
    """The stage swaps the run dir's parent for a link elsewhere. The runner
    cannot put the run dir back where its path leads, so it writes nothing
    more anywhere and exits 1 with no manifest."""

    out_dir = tmp_path / "day" / "run"
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "run").mkdir(parents=True)
    (elsewhere / "run" / "keep.txt").write_text("untouched")
    env = _codex_env(
        tmp_path,
        [
            "import atexit",
            "day = last_message.parent.parent",
            "def swap():",
            "    day.rename(day.with_name('moved'))",
            f"    day.symlink_to({str(elsewhere)!r})",
            "atexit.register(swap)",
        ],
    )
    args = ["--codex-model", "test-model", "--codex-sandbox", "workspace-write"]
    completed = _run(out_dir, args, env)

    assert completed.returncode == 1
    assert (
        "run directory unsafe after agent stage: the path to the run directory "
        "changed during the stage"
    ) in completed.stderr
    assert sorted(os.listdir(elsewhere / "run")) == ["keep.txt"]
    assert (elsewhere / "run" / "keep.txt").read_text() == "untouched"
    moved = tmp_path / "moved" / "run"
    assert (moved / "prompt.md").is_file()
    for name in ("manifest.json", "error.json", "command.json", "raw_response.txt"):
        assert not (moved / name).exists(), name


@pytest.mark.skipif(os.geteuid() == 0, reason="root opens any directory")
def test_stage_that_takes_read_permission_from_the_parent_ends_with_no_record(
    tmp_path,
):
    """The draft stage takes read permission from the run dir's parent. The
    guard cannot fingerprint the run dir before the revision stage, so the
    run ends with no record, as for an unsafe run dir, not a traceback."""

    day = tmp_path / "day"
    out_dir = day / "run"
    env = _codex_env(
        tmp_path,
        [
            "import atexit, os",
            "if last_message.name.startswith('draft_'):",
            "    atexit.register(os.chmod, last_message.parent.parent, 0o300)",
        ],
    )
    args = [
        "--codex-model",
        "test-model",
        "--codex-sandbox",
        "workspace-write",
        "--pre-submit-review-command",
        _command(tmp_path, "reviewer", text=REVIEW),
    ]
    try:
        completed = _run(out_dir, args, env)
    finally:
        if day.exists():
            day.chmod(0o755)

    assert completed.returncode == 1
    assert (
        "run directory unsafe after agent stage: run directory could not be "
        "fingerprinted before agent stage: "
    ) in completed.stderr
    assert "Traceback" not in completed.stderr
    assert (out_dir / "draft_command.json").is_file()
    assert not (out_dir / "manifest.json").exists()


# Agent output Python's decoder cannot take, or nested past the runner's depth
# limit. Each case but the 300-deep object used to crash the runner before it
# wrote a record, which refused the whole batch; that one decoded and failed
# at normalize. Each is now a recorded parse failure.
# name: (codex lines, or None for a --command run; a Python expression for
# the --command agent's output; the message prefixes it may record)
UNDECODABLE: dict[str, tuple[list[str] | None, str, tuple[str, ...]]] = {
    "bare-integer-past-digit-limit": (
        None,
        "'1' * 5000",
        ("No JSON object or array found in agent output",),
    ),
    "integer-past-digit-limit-in-array": (
        None,
        "'[' + '1' * 5000 + ']'",
        ("agent output holds JSON the decoder cannot represent: ",),
    ),
    "array-nested-past-the-decoder": (
        None,
        "'[' * 1_000_000 + ']' * 1_000_000",
        (
            "agent output nests JSON too deeply to decode",
            # An interpreter whose decoder takes it still bounds the depth.
            f"agent output nests JSON more than {runner.AGENT_JSON_MAX_DEPTH} "
            "levels deep",
        ),
    ),
    "object-nested-past-the-depth-limit": (
        None,
        "'{\"a\":' * 300 + '1' + '}' * 300",
        (
            f"agent output nests JSON more than {runner.AGENT_JSON_MAX_DEPTH} "
            "levels deep",
        ),
    ),
    "codex-last-message-integer-past-digit-limit": (
        ["text = '1' * 5000"],
        "",
        ("No JSON object or array found in agent output",),
    ),
}


@pytest.mark.parametrize("name", sorted(UNDECODABLE))
def test_undecodable_agent_output_is_a_parse_failure_the_publisher_retains(
    tmp_path, monkeypatch, name
):
    codex_lines, output, messages = UNDECODABLE[name]
    staged = tmp_path / "staged"
    out_dir = staged / RUN_RELATIVE
    if codex_lines is None:
        agent = tmp_path / "agent.py"
        agent.write_text(
            f"import sys\nsys.stdin.read()\nsys.stdout.write({output} + '\\n')\n"
        )
        args = ["--command", f"{shlex.quote(sys.executable)} {shlex.quote(str(agent))}"]
        env = None
    else:
        args = ["--codex-model", "test-model"]
        env = _codex_env(tmp_path, codex_lines)
    completed = _run(out_dir, args, env)
    assert completed.returncode == 1, completed.stderr[-2000:]

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    assert manifest["cellsPath"] is None
    assert manifest["error"]["phase"] == "parse"
    assert manifest["error"]["message"].startswith(messages), manifest["error"]
    assert (out_dir / "raw_response.txt").stat().st_size > 0
    verification = verify_run(out_dir)
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is False
    _publish_one(monkeypatch, staged, manifest, ok=False)


def test_undecodable_review_falls_back_to_its_summary():
    """The reviewer's output goes through the same extraction; one it cannot
    decode is a review with no fixes, not a crash."""

    for text in ("[" + "1" * 5000 + "]", "[" * 1_000_000 + "]" * 1_000_000):
        review = runner.parse_review_payload(text)
        assert review["requiredFixes"] == []
        assert review["summary"] == text[:240]


# Agent output bytes that are not UTF-8. Decoding a --command stage's output
# used to raise past every failure path, so the runner wrote no record. Each
# such byte is now replaced and the run is recorded on its merits.
# name: (statements the --command agent runs, the failure phase or None)
NON_UTF8: dict[str, tuple[str, str | None]] = {
    "latin-1-stderr-beside-a-valid-cell": (
        "sys.stderr.buffer.write(b'caf\\xe9\\n')\n"
        "sys.stdout.buffer.write(CELL + b'\\n')",
        None,
    ),
    "stray-byte-after-a-valid-cell": (
        "sys.stdout.buffer.write(CELL + b'\\n\\xff\\n')",
        None,
    ),
    "only-undecodable-bytes": ("sys.stdout.buffer.write(b'\\xff\\xfe\\n')", "parse"),
}


@pytest.mark.parametrize("name", sorted(NON_UTF8))
def test_non_utf8_agent_output_is_recorded(tmp_path, monkeypatch, name):
    statements, phase = NON_UTF8[name]
    staged = tmp_path / "staged"
    out_dir = staged / RUN_RELATIVE
    agent = tmp_path / "agent.py"
    agent.write_text(
        "import sys\n"
        "sys.stdin.read()\n"
        f"CELL = {json.dumps(VALID_CELL).encode()!r}\n"
        f"{statements}\n"
    )
    args = ["--command", f"{shlex.quote(sys.executable)} {shlex.quote(str(agent))}"]
    completed = _run(out_dir, args)

    manifest = json.loads((out_dir / "manifest.json").read_text())
    ok = phase is None
    assert completed.returncode == int(not ok), completed.stderr[-2000:]
    assert manifest["ok"] is ok
    assert (manifest.get("error") or {}).get("phase") == phase
    captured = (out_dir / "stdout.txt").read_text() + (
        out_dir / "stderr.txt"
    ).read_text()
    assert "�" in captured
    verification = verify_run(out_dir)
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is ok
    if manifest["cellsPath"] is not None:
        assert _publisher_replay_ok(out_dir, manifest) is ok
    else:
        _publish_one(monkeypatch, staged, manifest, ok=ok)


# The runner's own reads and writes in the run dir, failed from outside the
# guard's view (as file flags, ACLs or a full disk would fail them).
IO_FAILURES = [
    ("write_bytes", "command.json", "write command.json"),
    ("write_bytes", "manifest.json", "write manifest.json"),
    ("read_bytes", "parsed_cells.json", "read parsed_cells.json"),
]


@pytest.mark.parametrize(("method", "name", "expected"), IO_FAILURES)
def test_run_dir_io_failure_ends_with_no_record(tmp_path, method, name, expected):
    """The runner cannot record a run in a run dir it cannot read or write:
    it exits 1 with no manifest and says why, as for an unsafe run dir."""

    wrapper = tmp_path / "runner_with_io_failure.py"
    wrapper.write_text(
        "\n".join(
            [
                "import pathlib, runpy, sys",
                f"sys.path.insert(0, {str(RUNNER.parent)!r})",
                f"real = pathlib.Path.{method}",
                "def failing(self, *args, **kwargs):",
                f"    if self.name == {name!r}:",
                "        raise PermissionError(1, 'not permitted', str(self))",
                "    return real(self, *args, **kwargs)",
                f"pathlib.Path.{method} = failing",
                f"sys.argv[0] = {str(RUNNER)!r}",
                f"runpy.run_path({str(RUNNER)!r}, run_name='__main__')",
            ]
        )
        + "\n"
    )
    out_dir = tmp_path / "run"
    agent = _command(tmp_path, "agent", text=OUTPUTS["valid"])
    completed = subprocess.run(
        [
            sys.executable,
            str(wrapper),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--command",
            agent,
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert completed.returncode == 1
    assert f"run directory I/O failed: {expected}: " in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (out_dir / "manifest.json").exists()


def test_rebuild_that_cannot_remove_the_stage_tree_names_what_is_left(
    tmp_path, monkeypatch
):
    """When the stage's tree cannot be removed, the run ends unsafe and the
    error names the directory left beside the run dir."""

    monkeypatch.setattr(runner, "git_porcelain_lines", lambda _out_dir: [])
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "prompt.md").write_text("p")
    pre = runner.workspace_guard_snapshot(out_dir)
    try:
        (out_dir / "planted.txt").write_text("x")
        assert runner.workspace_guard_violations(pre, out_dir, {ALLOWED})

        def cannot_remove(_parent_fd, name):
            raise PermissionError(1, "Operation not permitted", name)

        monkeypatch.setattr(runner, "_remove_tree_at", cannot_remove)
        with pytest.raises(runner.UnsafeRunDirError) as raised:
            runner.restore_run_dir(pre, out_dir, {ALLOWED})
    finally:
        runner.close_workspace_guard(pre)
    left = [name for name in os.listdir(tmp_path) if name.startswith(".run.stage-")]
    assert len(left) == 1
    assert str(raised.value).endswith(
        f"; the stage's tree is left at {tmp_path / left[0]}"
    )
    assert (tmp_path / left[0] / "planted.txt").read_text() == "x"


MACOS_LOCKS = {
    # Neither file flags nor ACLs are in the guard's fingerprint: the stage
    # passes the guard and the runner's next write into the run dir fails.
    "last-message-immutable": "os.chflags(last_message, stat.UF_IMMUTABLE)",
    "run-dir-immutable": "os.chflags(last_message.parent, stat.UF_IMMUTABLE)",
    "run-dir-acl-denies-new-files": (
        "subprocess.run(['/bin/chmod', '+a', 'everyone deny add_file', "
        "str(last_message.parent)], check=True)"
    ),
}


@pytest.mark.skipif(
    sys.platform != "darwin", reason="macOS file flags and ACLs (chflags, chmod +a)"
)
@pytest.mark.parametrize("name", sorted(MACOS_LOCKS))
def test_stage_that_locks_the_run_dir_on_macos_ends_with_no_record(tmp_path, name):
    out_dir = tmp_path / "day" / "run"
    env = _codex_env(
        tmp_path,
        [
            "import atexit, os, stat, subprocess",
            f"atexit.register(lambda: {MACOS_LOCKS[name]})",
        ],
    )
    args = ["--codex-model", "test-model", "--codex-sandbox", "workspace-write"]
    try:
        completed = _run(out_dir, args, env)
    finally:
        _clear_macos_locks(out_dir.parent)

    assert completed.returncode == 1
    assert "run directory I/O failed: write " in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not (out_dir / "manifest.json").exists()


def _clear_macos_locks(root: Path) -> None:
    """Clear the file flags and ACLs a stage set anywhere under ``root``,
    including a stage tree the runner moved aside, so pytest can remove it."""

    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        for name in [".", *dirnames, *filenames]:
            os.chflags(os.path.join(dirpath, name), 0, follow_symlinks=False)
    subprocess.run(["/bin/chmod", "-RN", str(root)], check=True)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS ACLs (chmod +a)")
def test_stage_that_makes_the_tool_evidence_spool_undeletable_is_recorded(
    tmp_path,
):
    """The tool-evidence spool lives in TMPDIR, which the stage can write.
    A stage that denies the spool's deletion leaves it behind; the run is
    recorded as usual."""

    out_dir = tmp_path / "staged" / RUN_RELATIVE
    record = tmp_path / "spool.txt"
    env = _codex_env(
        tmp_path,
        [
            "import subprocess",
            "spool = next(",
            "    pathlib.Path(json.loads(arg.split('=', 1)[1])[2]).parent",
            "    for arg in args",
            "    if '.args=' in arg and 'thesis-tool-evidence-' in arg",
            ")",
            f"pathlib.Path({str(record)!r}).write_text(str(spool))",
            "subprocess.run(",
            "    ['/bin/chmod', '+a', 'everyone deny delete', str(spool)], check=True",
            ")",
        ],
    )
    try:
        completed = _run(out_dir, ["--codex-model", "test-model"], env)
    finally:
        if record.exists() and Path(record.read_text()).exists():
            spool = Path(record.read_text())
            subprocess.run(["/bin/chmod", "-RN", str(spool)], check=True)
            shutil.rmtree(spool)

    assert record.exists(), completed.stderr[-2000:]
    assert completed.returncode == 0, completed.stderr[-2000:]
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is True
    assert verify_run(out_dir).inventory_status == "complete"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS ACLs (chmod +a)")
def test_stage_that_denies_stat_on_new_run_files_is_recorded(tmp_path):
    """The stage leaves an inherited ACL on the run dir that denies reading
    the attributes of every file created there afterwards. The runner can
    still read what it writes, and sizes its refs from those bytes."""

    staged = tmp_path / "staged"
    out_dir = staged / RUN_RELATIVE
    agent = tmp_path / "agent.py"
    agent.write_text(
        "\n".join(
            [
                "import os, subprocess, sys",
                "sys.stdin.read()",
                "subprocess.run(['/bin/chmod', '+a',"
                " 'everyone deny readattr,file_inherit,only_inherit',"
                " os.path.dirname(sys.argv[1])], check=True)",
                f"print({json.dumps(VALID_CELL)!r})",
            ]
        )
        + "\n"
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(agent))} {{prompt_path}}"
    try:
        completed = _run(out_dir, ["--command", command])
        # Path.exists() stats, so a file the ACL covers looks missing.
        hidden = not (out_dir / "normalized_cells.json").exists()
    finally:
        _clear_macos_locks(staged)

    assert completed.returncode == 0, completed.stderr[-2000:]
    assert hidden and (out_dir / "normalized_cells.json").is_file()
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is True
    verification = verify_run(out_dir)
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is True
    assert _publisher_replay_ok(out_dir, manifest) is True


# --- Invariants over every stage-outcome combination ------------------------

FLOWS = {
    # name: (forecaster kwargs, reviewer exit or None, failed?)
    "single-ok": ({}, None, False),
    "single-fails": ({"exit_code": 2}, None, True),
    "draft-fails": ({"exit_code": 2}, 0, True),
    "reviewer-fails": ({}, 1, True),
    "revision-fails": ({"revision_exit": 4}, 0, True),
    "reviewed-ok": ({}, 0, False),
}


@pytest.mark.parametrize("output", sorted(OUTPUTS))
@pytest.mark.parametrize("flow", sorted(FLOWS))
def test_a_failed_run_is_never_a_validator_status_mismatch(
    tmp_path, monkeypatch, flow, output
):
    """Exhaustive over the finite space of stage outcomes and output kinds.

    I1  the runner exits 0 exactly when the manifest is ok;
    I2  a run that seals cells has exactly its validation status, and the
        publisher's validator replay agrees with it;
    I3  a run with a failed stage seals no cells and records phase command;
    I4  only a run whose stages all succeeded with valid output is ok;
    I5  custody verifies every outcome with a complete inventory;
    I6  the publisher retains every outcome that seals no cells.
    """

    forecaster, reviewer, stage_failed = FLOWS[flow]
    staged = tmp_path / "staged"
    out_dir = staged / RUN_RELATIVE
    args = [
        "--command",
        _command(tmp_path, "agent", text=OUTPUTS[output], **forecaster),
    ]
    if reviewer is not None:
        args += [
            "--pre-submit-review-command",
            _command(tmp_path, "reviewer", text=REVIEW, exit_code=reviewer),
        ]
    completed = _run(out_dir, args)
    manifest = json.loads((out_dir / "manifest.json").read_text())

    assert (completed.returncode == 0) is manifest["ok"]  # I1
    if manifest["cellsPath"] is not None:  # I2
        assert manifest["ok"] is manifest["validation"]["ok"]
        assert _publisher_replay_ok(out_dir, manifest) is manifest["ok"]
    if stage_failed:  # I3
        assert manifest["cellsPath"] is None
        assert manifest["error"]["phase"] == "command"
    assert manifest["ok"] is (not stage_failed and output == "valid")  # I4
    verification = verify_run(out_dir)  # I5
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is manifest["ok"]
    if manifest["cellsPath"] is None:  # I6
        _publish_one(monkeypatch, staged, manifest, ok=manifest["ok"])


@settings(max_examples=300, deadline=None)
@given(
    return_code=st.integers(min_value=-15, max_value=255),
    timed_out=st.booleans(),
    evidence_failure=st.one_of(st.none(), st.text(min_size=1)),
    mutations=st.lists(st.text(min_size=1), max_size=3),
    review_status=st.sampled_from(
        [None, "draft_failed", "review_failed", "revision_failed", "completed"]
    ),
    last_error=st.one_of(st.none(), st.text()),
)
def test_stage_failure_records_every_non_validation_failure(
    return_code, timed_out, evidence_failure, mutations, review_status, last_error
):
    """A run may parse its output exactly when no stage failed, and the phase
    follows a fixed precedence: tool evidence, workspace, command."""

    result: dict[str, Any] = {
        "returnCode": return_code,
        "timedOut": timed_out,
        "codexTrace": {"lastError": last_error},
    }
    if evidence_failure is not None:
        result["toolEvidenceFailure"] = evidence_failure
    failure = runner.stage_failure(result, mutations, review_status)
    clean = evidence_failure is None and not mutations and return_code == 0
    assert (failure is None) is clean
    if evidence_failure is not None:
        assert failure == ("tool_evidence", evidence_failure)
    elif mutations:
        assert failure[0] == "workspace_hygiene"
        assert failure[1].endswith(f"({len(mutations)} violation(s)): {mutations[0]}")
    elif failure is not None:
        label = runner.FAILED_STAGE_LABELS.get(review_status or "", "agent command")
        expected = f"{label} exited {return_code}"
        expected += " after timing out" if timed_out else ""
        expected += f": {last_error}" if last_error else ""
        assert failure == ("command", expected)
    assert runner.stage_failure(None, [], review_status) is None


# --- The guard sees and undoes every run-dir mutation -----------------------

ARTIFACTS = ("prompt.md", "stdout.txt", "command.json", "draft_stdout.txt")
ALLOWED = "codex_last_message.txt"
NAMES = (*ARTIFACTS, ALLOWED, "planted.txt", "nested", ".")
OPS = [
    "write",
    "mkdir",
    "link_out",
    "link_in",
    "hardlink",
    "delete",
    "chmod",
    "nested",
    "lock",
    "relink",
]
MUTATION = st.tuples(
    st.sampled_from(OPS),
    st.sampled_from(NAMES),
    st.binary(max_size=8),
    st.sampled_from([0o000, 0o200, 0o500, 0o600, 0o644, 0o755]),
)


def _remove(path: Path) -> None:
    """Remove path the way an agent would, links themselves and not their
    targets. The guard's own remover is what is under test."""

    if path.is_symlink() or not path.is_dir():
        path.unlink()
        return
    path.chmod(0o700)
    for child in path.iterdir():
        _remove(child)
    path.rmdir()


def _mutate(out_dir: Path, outside: Path, op: str, name: str, data: bytes, mode: int):
    """One agent write. A write the agent's own permissions refuse is a
    no-op, as it would be in the sandbox."""

    path = out_dir / name
    try:
        if name == ".":
            real_run_dir = out_dir.is_dir() and not out_dir.is_symlink()
            moved = out_dir.with_name("moved")
            if op == "delete" and (out_dir.is_symlink() or out_dir.exists()):
                _remove(out_dir)
            elif op == "relink" and real_run_dir and not moved.exists():
                # The run dir becomes a link to the directory it was.
                out_dir.rename(moved)
                out_dir.symlink_to(moved)
            elif op == "lock" and real_run_dir:
                out_dir.chmod(mode & 0o700)
            return
        real_dir = path.is_dir() and not path.is_symlink()
        if op in {"mkdir", "link_out", "link_in", "hardlink"} and (
            path.is_symlink() or path.exists()
        ):
            _remove(path)
        prompt_md = out_dir / "prompt.md"
        if op == "write" and not real_dir:
            path.unlink(missing_ok=True)
            path.write_bytes(data)
        elif op == "mkdir":
            path.mkdir()
        elif op == "link_out":
            path.symlink_to(outside)
        elif op == "link_in":
            path.symlink_to(prompt_md)
        elif op == "hardlink" and prompt_md.is_file() and not prompt_md.is_symlink():
            os.link(prompt_md, path)
        elif op == "delete" and (path.is_symlink() or path.exists()):
            _remove(path)
        elif op == "chmod" and path.is_file() and not path.is_symlink():
            path.chmod(mode)
        elif op == "nested" and real_dir:
            (path / "inner.txt").write_bytes(data)
        elif op == "lock" and real_dir:
            path.chmod(mode & 0o700)
    except OSError:
        pass


def _observe(path: Path) -> Any:
    """What is at path, by the test's own lstat walk that never follows a
    link: a link's target; a file's mode, size, link count and bytes (None
    when unreadable); a directory's mode and everything below it."""

    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    mode = stat.S_IMODE(info.st_mode)
    if stat.S_ISLNK(info.st_mode):
        return ("link", os.readlink(path))
    if stat.S_ISREG(info.st_mode):
        try:
            content = path.read_bytes()
        except PermissionError:
            content = None
        return ("file", mode, info.st_size, info.st_nlink, content)
    if not stat.S_ISDIR(info.st_mode):
        return ("other", stat.S_IFMT(info.st_mode))
    path.chmod(0o700)  # list everything, then put the mode back
    try:
        children = {child.name: _observe(child) for child in path.iterdir()}
    finally:
        path.chmod(mode)
    return ("dir", mode, children)


def _judged(observed: Any) -> Any:
    """The run dir as the guard must judge it: a stage output that is a plain
    file the runner can read and rewrite as its own is allowed."""

    if observed is None or observed[0] != "dir":
        return observed
    children = dict(observed[2])
    output = children.get(ALLOWED)
    if (
        output is not None
        and output[0] == "file"
        and output[4] is not None
        and output[3] == 1
        and output[1] & 0o600 == 0o600
    ):
        del children[ALLOWED]
    return ("dir", observed[1], children)


@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    contents=st.dictionaries(
        st.sampled_from(ARTIFACTS), st.binary(max_size=16), min_size=1
    ),
    mutations=st.lists(MUTATION, max_size=6),
)
@example(
    # A stage output the runner could read but not rewrite.
    contents={"prompt.md": b"p"},
    mutations=[("write", ALLOWED, b"x", 0o600), ("chmod", ALLOWED, b"", 0o500)],
)
@example(
    # The run dir replaced by a link to the directory it was, then written
    # through.
    contents={"prompt.md": b"p"},
    mutations=[("relink", ".", b"", 0o600), ("write", "planted.txt", b"x", 0o600)],
)
@example(
    # A second name for a runner artifact.
    contents={"prompt.md": b"p"},
    mutations=[("hardlink", ALLOWED, b"", 0o600)],
)
@example(
    # A write inside a new subdirectory, then that subdirectory locked.
    contents={"prompt.md": b"p"},
    mutations=[
        ("mkdir", "nested", b"", 0o600),
        ("nested", "nested", b"x", 0o600),
        ("lock", "nested", b"", 0o000),
    ],
)
@example(
    # A plain stage output beside a plant: rebuilt, and the output kept.
    contents={"prompt.md": b"p"},
    mutations=[
        ("write", ALLOWED, b"cells", 0o600),
        ("write", "planted.txt", b"x", 0o600),
    ],
)
def test_guard_sees_and_undoes_every_run_dir_mutation(
    tmp_path_factory, monkeypatch, contents, mutations
):
    """For any run dir and any sequence of agent writes, links, hard links,
    permission changes and replacements of the run dir itself: the guard
    reports a violation exactly when the run dir differs from the runner's
    pre-stage state plus a plain stage output file, and rebuilding returns
    it to exactly that state: the stage output kept, as a plain file the
    runner owns, exactly when it was plain. The rebuild never writes, chmods
    or removes through a link, and leaves nothing of its own beside the run
    dir."""

    monkeypatch.setattr(runner, "git_porcelain_lines", lambda _out_dir: [])
    root = tmp_path_factory.mktemp("guard")
    out_dir = root / "run"
    out_dir.mkdir()
    outside = root / "outside.txt"
    outside.write_bytes(b"untouched")
    for name, data in contents.items():
        (out_dir / name).write_bytes(data)
    pristine = _observe(out_dir)
    pre = runner.workspace_guard_snapshot(out_dir)
    try:
        for mutation in mutations:
            _mutate(out_dir, outside, *mutation)
        moved = _observe(root / "moved")
        after = _observe(out_dir)
        changed = _judged(after) != pristine
        output = after[2].get(ALLOWED) if after and after[0] == "dir" else None
        plain_output = (
            _judged(("dir", 0, {ALLOWED: output}))[2] == {} if output else False
        )
        violations = runner.workspace_guard_violations(pre, out_dir, {ALLOWED})
        assert bool(violations) is changed, violations
        if violations:
            runner.restore_run_dir(pre, out_dir, {ALLOWED})
    finally:
        runner.close_workspace_guard(pre)
    assert _judged(_observe(out_dir)) == pristine
    if violations:
        assert _observe(out_dir / ALLOWED) == (
            ("file", 0o644, output[2], 1, output[4]) if plain_output else None
        )
    assert _observe(root / "moved") == moved
    assert outside.read_bytes() == b"untouched"
    expected = {"run", "outside.txt", *(["moved"] if moved is not None else [])}
    assert set(os.listdir(root)) == expected
    _remove(root)


# --- Custody refuses forged stage-failure records ---------------------------


PLANT = "(last_message.parent / 'planted.txt').write_text('x')"
EXIT_3 = [
    "import atexit, os",
    "atexit.register(lambda: (sys.stdout.flush(), os._exit(3)))",
]
# kind: (codex lines, or None for a --command run; the phase it records, or
# None for a run that parsed: "valid" seals ok, "invalid" fails validation)
FAILED_RUNS: dict[str, tuple[list[str] | None, str | None]] = {
    "valid": (None, None),
    "invalid": (None, None),
    "command": (None, "command"),
    "review_failed": (None, "command"),
    "reviewed_parse": (None, "parse"),
    "workspace_hygiene": ([PLANT], "workspace_hygiene"),
    "hygiene_exit": ([PLANT, *EXIT_3], "workspace_hygiene"),
    "guarded_exit": (EXIT_3, "command"),
}


def _failed_run(root: Path, kind: str) -> Path:
    """A freshly sealed run of one of the FAILED_RUNS kinds. Sealed paths
    outside the checkout are absolute, so each forgery seals its own."""

    out_dir = root / "run"
    codex_lines, phase = FAILED_RUNS[kind]
    env = None
    if codex_lines is not None:
        env = _codex_env(root, codex_lines)
        args = ["--codex-model", "test-model", "--codex-sandbox", "workspace-write"]
    elif kind in {"valid", "invalid", "command"}:
        output = "invalid" if kind == "invalid" else "valid"
        exit_code = 2 if kind == "command" else 0
        agent = _command(root, "agent", text=OUTPUTS[output], exit_code=exit_code)
        args = ["--command", agent]
    else:
        agent = _command(
            root,
            "agent",
            text=OUTPUTS["valid"],
            revision_text=OUTPUTS["unparseable"],
        )
        reviewer = _command(
            root, "reviewer", text=REVIEW, exit_code=int(kind == "review_failed")
        )
        args = ["--command", agent, "--pre-submit-review-command", reviewer]
    completed = _run(out_dir, args, env)
    assert completed.returncode == int(kind != "valid"), completed.stderr[-2000:]
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert (manifest.get("error") or {}).get("phase") == phase
    return out_dir


def _reseal(out_dir: Path, edit) -> None:
    """Apply ``edit(out_dir, manifest, artifacts, refs)`` and re-seal
    hash-consistently, so
    the semantic guard, not an integrity mismatch, is what refuses it.
    ``artifacts`` maps a filename to its parsed JSON for rewriting."""

    manifest = json.loads((out_dir / "manifest.json").read_text())
    manifest.pop("custodyRootSha256", None)
    refs = [
        ref
        for ref in manifest["artifacts"]
        if Path(str(ref["path"])).name != "manifest.json"
    ]
    artifacts: dict[str, Any] = {}
    edit(out_dir, manifest, artifacts, refs)
    for filename, payload in artifacts.items():
        ref = runner.write_artifact(
            out_dir,
            next(
                str(r["artifactType"])
                for r in refs
                if Path(str(r["path"])).name == filename
            ),
            filename,
            json.dumps(payload, indent=2),
            manifest["runStartedAt"],
        )
        refs = [r if Path(str(r["path"])).name != filename else ref for r in refs]
    manifest["artifacts"] = refs
    runner.finalize_manifest(out_dir, manifest["runStartedAt"], manifest, refs)


def _set_phase(phase: str):
    def edit(_out_dir, manifest, artifacts, _refs):
        manifest["error"]["phase"] = phase
        artifacts["error.json"] = manifest["error"]

    edit.__name__ = f"relabelled_{phase}"
    return edit


def _presents_complete(_out_dir, manifest, _artifacts, _refs):
    manifest["ok"] = True
    manifest["validation"] = {"ok": True}


def _post_parse_artifact(out_dir, manifest, _artifacts, refs):
    refs.append(
        runner.write_artifact(
            out_dir,
            "parsed_cell",
            "parsed_cells.json",
            "[]\n",
            manifest["runStartedAt"],
        )
    )


def _stage_succeeded(out_dir, _manifest, artifacts, _refs):
    command = json.loads((out_dir / "command.json").read_text())
    command["returnCode"] = 0
    artifacts["command.json"] = command


def _mutations_rewritten(_out_dir, manifest, _artifacts, _refs):
    manifest["workspaceHygiene"]["mutations"] = ["a mutation no stage recorded"]


def _hygiene_fabricated(_out_dir, manifest, _artifacts, _refs):
    manifest["workspaceHygiene"] = {
        "guarded": True,
        "mutations": ["a mutation no stage recorded"],
    }


def _error_timed_out(_out_dir, manifest, artifacts, _refs):
    manifest["error"]["command"]["timedOut"] = True
    artifacts["error.json"] = manifest["error"]


def _error_command_dropped(_out_dir, manifest, artifacts, _refs):
    manifest["error"]["command"] = None
    artifacts["error.json"] = manifest["error"]


def _earlier_stage_failed(out_dir, _manifest, artifacts, _refs):
    command = json.loads((out_dir / "draft_command.json").read_text())
    command["returnCode"] = 2
    artifacts["draft_command.json"] = command


_NO_RETURN_CODE = object()


def _last_stage_exit(value: Any, name: str):
    """Record ``value`` as a parsed run's last-stage exit."""

    def edit(out_dir, manifest, artifacts, refs):
        command = json.loads((out_dir / "command.json").read_text())
        if value is _NO_RETURN_CODE:
            del command["returnCode"]
        else:
            command["returnCode"] = value
        index = next(
            i
            for i, ref in enumerate(refs)
            if Path(str(ref["path"])).name == "command.json"
        )
        refs[index] = runner.write_artifact(
            out_dir,
            str(refs[index]["artifactType"]),
            "command.json",
            json.dumps(command, indent=2),
            manifest["runStartedAt"],
        )
        # The cells expose every earlier artifact ref as their activity log,
        # so the forger rewrites that log too; otherwise the activity check,
        # not the exit rule, is what refuses the edit.
        activity = [
            ref
            for ref in refs
            if ref.get("artifactType") not in {"cells_with_activity", "manifest"}
        ]
        cells = json.loads((out_dir / "cells.with_activity.json").read_text())
        artifacts["cells.with_activity.json"] = [
            {**cell, "activityLog": activity} for cell in cells
        ]

    edit.__name__ = f"last_stage_{name}"
    return edit


FINAL_STAGE = ("command.json", "stdout.txt", "stderr.txt", "revision_prompt.md")


def _final_stage_dropped(out_dir, _manifest, _artifacts, refs):
    for name in FINAL_STAGE:
        (out_dir / name).unlink()
    refs[:] = [ref for ref in refs if Path(str(ref["path"])).name not in FINAL_STAGE]


PARSED_RUN_EXIT = "a parsed run's last invocation stage exited nonzero"
FORGERIES = [
    ("command", _presents_complete, "does not present as failed"),
    (
        "command",
        _post_parse_artifact,
        "command-failure inventory contains post-parse artifacts",
    ),
    (
        "command",
        _stage_succeeded,
        "command-failure error disagrees with its failed invocation stage",
    ),
    (
        "command",
        _set_phase("workspace_hygiene"),
        "workspace_hygiene-failure manifest disagrees with the stages' recorded",
    ),
    ("workspace_hygiene", _presents_complete, "does not present as failed"),
    (
        "workspace_hygiene",
        _post_parse_artifact,
        "workspace_hygiene-failure inventory contains post-parse artifacts",
    ),
    (
        "workspace_hygiene",
        _mutations_rewritten,
        "workspace_hygiene-failure manifest disagrees with the stages' recorded",
    ),
    (
        # Relabelling a workspace mutation as a mere command failure would
        # hide it; a command failure cannot sit beside recorded mutations.
        "workspace_hygiene",
        _set_phase("command"),
        "command-failure error disagrees with its failed invocation stage",
    ),
    (
        # The same relabel when the mutating stage also exited nonzero: its
        # return code fits a command failure, its recorded mutations do not.
        "hygiene_exit",
        _set_phase("command"),
        "stage workspace mutations disagree with the run's failure phase",
    ),
    (
        "workspace_hygiene",
        _set_phase("parse"),
        "stage workspace mutations disagree with the run's failure phase",
    ),
    (
        # A guarded stage that exited nonzero and mutated nothing.
        "guarded_exit",
        _set_phase("workspace_hygiene"),
        "workspace_hygiene-failure manifest disagrees with the stages' recorded",
    ),
    (
        "command",
        _hygiene_fabricated,
        "manifest workspaceHygiene disagrees with the stages' recorded workspace",
    ),
    (
        "command",
        _error_timed_out,
        "command-failure error disagrees with its last invocation stage",
    ),
    (
        "workspace_hygiene",
        _error_command_dropped,
        "workspace_hygiene-failure error disagrees with its last invocation stage",
    ),
    (
        # The runner never runs a stage after one that failed.
        "review_failed",
        _earlier_stage_failed,
        "invocation stages disagree with the order the runner runs them in",
    ),
    (
        # A reviewed run cut back to its clean reviewer stage: the runner
        # stops early only at a stage that failed.
        "reviewed_parse",
        _final_stage_dropped,
        "invocation stages disagree with the order the runner runs them in",
    ),
    *[
        # A run that parsed presented as one whose stage failed: the runner
        # parses only once the last stage exited 0.
        (kind, _last_stage_exit(2, "exited_2"), PARSED_RUN_EXIT)
        for kind in ("valid", "invalid")
    ],
    *[
        # A process stage always records its exit as an int, so a parsed
        # run's last exit recorded as anything else is forged.
        ("valid", _last_stage_exit(value, name), PARSED_RUN_EXIT)
        for value, name in [
            (True, "exit_true"),
            (2.0, "exit_float"),
            ("2", "exit_string"),
            (None, "exit_null"),
            (_NO_RETURN_CODE, "exit_missing"),
        ]
    ],
]


@pytest.mark.parametrize(
    ("kind", "forge", "expected"),
    FORGERIES,
    ids=[f"{kind}-{forge.__name__.strip('_')}" for kind, forge, _ in FORGERIES],
)
def test_custody_refuses_a_forged_stage_failure(tmp_path, kind, forge, expected):
    out_dir = _failed_run(tmp_path, kind)
    verify_run(out_dir)
    # Re-sealing without an edit still verifies: the harness is sound.
    _reseal(out_dir, lambda *_args: None)
    verify_run(out_dir)
    _reseal(out_dir, forge)
    with pytest.raises(CustodyError, match=expected):
        verify_run(out_dir)
