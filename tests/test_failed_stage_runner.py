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
from hypothesis import HealthCheck, given, settings
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
    "run-dir-link-planted-under-artifact-name": _hygiene_case(
        # A link where the runner will write stdout.txt: without the guard
        # putting the run dir back, the runner writes through it.
        "outside = last_message.parent.parents[4] / 'outside.txt'",
        "(last_message.parent / 'stdout.txt').symlink_to(outside)",
    ),
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
    assert not (out_dir / "planted.txt").exists()
    assert not (out_dir / "prompt.md").read_text().endswith("tampered")
    assert not os.access(out_dir / "prompt.md", os.X_OK)
    assert not (out_dir / "stdout.txt").is_symlink()
    assert outside.read_text() == "untouched\n"

    verification = verify_run(out_dir)
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is False
    assert not verification.headline_eligible
    _publish_one(monkeypatch, staged, manifest, ok=False)


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
OPS = ["write", "mkdir", "link_out", "link_in", "delete", "chmod", "nested", "lock"]
MUTATION = st.tuples(
    st.sampled_from(OPS),
    st.sampled_from(NAMES),
    st.binary(max_size=8),
    st.sampled_from([0o000, 0o200, 0o500, 0o600, 0o644, 0o755]),
)


def _mutate(out_dir: Path, outside: Path, op: str, name: str, data: bytes, mode: int):
    """One agent write. A write the agent's own permissions refuse is a
    no-op, as it would be in the sandbox."""

    path = out_dir / name
    real_dir = path.is_dir() and not path.is_symlink()
    if name == "." and op != "lock":
        return
    try:
        if op in {"mkdir", "link_out", "link_in"} and (
            path.is_symlink() or path.exists()
        ):
            runner._remove_run_dir_entry(path)
        if op == "write" and not real_dir:
            path.unlink(missing_ok=True)
            path.write_bytes(data)
        elif op == "mkdir":
            path.mkdir()
        elif op == "link_out":
            path.symlink_to(outside)
        elif op == "link_in":
            path.symlink_to(out_dir / "prompt.md")
        elif op == "delete" and (path.is_symlink() or path.exists()):
            runner._remove_run_dir_entry(path)
        elif op == "chmod" and path.is_file() and not path.is_symlink():
            path.chmod(mode)
        elif op == "nested" and real_dir:
            (path / "inner.txt").write_bytes(data)
        elif op == "lock" and real_dir:
            path.chmod(mode & 0o700)
    except PermissionError:
        pass


def _plain(entry: Any) -> bool:
    return entry is not None and entry[0] is not None and entry[1] & 0o600 == 0o600


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
def test_guard_sees_and_undoes_every_run_dir_mutation(
    tmp_path_factory, monkeypatch, contents, mutations
):
    """For any run dir and any sequence of agent writes, links and permission
    changes: the guard reports a violation exactly when the run dir differs
    from the runner's pre-stage state plus a plain stage output file, and
    restoring returns it to exactly that without writing through a link."""

    monkeypatch.setattr(runner, "git_porcelain_lines", lambda _out_dir: [])
    root = tmp_path_factory.mktemp("guard")
    out_dir = root / "run"
    out_dir.mkdir()
    outside = root / "outside.txt"
    outside.write_bytes(b"untouched")
    for name, data in contents.items():
        (out_dir / name).write_bytes(data)
    pre = runner.workspace_guard_snapshot(out_dir)
    for mutation in mutations:
        _mutate(out_dir, outside, *mutation)

    def state() -> tuple[int, dict[str, Any]]:
        mode = stat.S_IMODE(out_dir.stat().st_mode)
        out_dir.chmod(0o700)  # observe everything, then put the mode back
        try:
            visible = runner.run_dir_entries(out_dir)
        finally:
            out_dir.chmod(mode)
        if _plain(visible.get(ALLOWED)):
            del visible[ALLOWED]
        return mode, visible

    pristine = (pre["outDirMode"], pre["outDirEntries"])
    changed = state() != pristine
    violations = runner.workspace_guard_violations(pre, out_dir, {ALLOWED})
    assert bool(violations) is changed, violations
    runner.restore_run_dir(pre, out_dir, {ALLOWED})
    assert state() == pristine
    assert outside.read_bytes() == b"untouched"
    shutil.rmtree(root, ignore_errors=True)


# --- Custody refuses forged stage-failure records ---------------------------


def _failed_run(root: Path, kind: str) -> Path:
    """A freshly sealed command-failed or workspace-failed run. Sealed paths
    outside the checkout are absolute, so each forgery seals its own."""

    out_dir = root / "run"
    if kind == "command":
        agent = _command(root, "agent", text=OUTPUTS["valid"], exit_code=2)
        completed = _run(out_dir, ["--command", agent])
    else:
        env = _codex_env(
            root, ["(last_message.parent / 'planted.txt').write_text('x')"]
        )
        args = ["--codex-model", "test-model", "--codex-sandbox", "workspace-write"]
        completed = _run(out_dir, args, env)
    assert completed.returncode == 1, completed.stderr[-2000:]
    assert json.loads((out_dir / "manifest.json").read_text())["error"]["phase"] == kind
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
