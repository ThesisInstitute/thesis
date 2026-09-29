from __future__ import annotations

import copy
import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_thesis_analyst as runner  # noqa: E402
import run_thesis_batch as batch  # noqa: E402
import strategy_generation as generation  # noqa: E402
from canonical_json import canonical_sha256  # noqa: E402

URL = "https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-returns-complete-report-publication-1304"
RELATIVE = pathlib.PurePosixPath(
    "records/thesis-analyst/2026-09-22/2026-09-22t05-10-34z-irs-actc-total-claims-2027"
)


def target():
    return {
        "catalogSlug": "actc-claims-conditional",
        "comparisonTarget": True,
        "conditional": "The reviewed threshold premise holds.",
        "resolutionDateBasis": "resolve-by-bound",
        "sourceBinding": {"sourceUrl": URL},
    }


def write_native_stage(tmp_path, *, prefix="draft_"):
    checkout = pathlib.PurePosixPath("/home/runner/work/thesis/thesis")
    python = str(checkout / ".venv/bin/python3")
    argv = [
        "codex",
        "--search",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "-o",
        str(checkout / RELATIVE / f"{prefix}codex_last_message.txt"),
        "-m",
        "gpt-5.5",
        "-c",
        'reasoning_effort="low"',
    ]
    configs = runner.tool_evidence_mcp_config(
        pathlib.Path("/tmp/thesis-tool-evidence-fixture/tool_evidence.json"),
        checkout_root=checkout,
        python_executable=python,
        allow_fetch=True,
    ) + runner.announcement_mcp_config(
        URL, checkout_root=checkout, python_executable=python
    )
    for config in configs:
        argv.extend(["-c", config])
    argv.extend(["-C", str(checkout), "-s", "read-only", "<prompt>"])
    command = {"backend": "codex", "returnCode": 0, "argv": argv}
    event = {
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": runner.ANNOUNCEMENT_MCP_SERVER,
            "tool": runner.ANNOUNCEMENT_MCP_TOOL,
            "status": "completed",
            "error": None,
            "arguments": {"url": URL},
            "result": {
                "content": [],
                "structured_content": {
                    "requestedUrl": URL,
                    "finalUrl": URL,
                    "statusCode": 200,
                    "responseSha256": "a" * 64,
                },
            },
        },
    }
    final = '{"forecast": "fixture"}'
    events = [
        event,
        {"type": "item.completed", "item": {"type": "agent_message", "text": final}},
    ]

    def write():
        (tmp_path / f"{prefix}command.json").write_text(json.dumps(command))
        (tmp_path / f"{prefix}codex_stdout.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n"
        )
        (tmp_path / f"{prefix}codex_last_message.txt").write_text(final)
        (tmp_path / f"{prefix}stdout.txt").write_text(final)

    write()
    return command, events, write


@pytest.mark.parametrize("prefix", ["draft_", ""])
def test_bounded_strategy_accepts_native_exact_announcement_fetch(tmp_path, prefix):
    write_native_stage(tmp_path, prefix=prefix)
    assert (
        generation.bounded_strategy_evidence_errors(tmp_path, RELATIVE, target()) == []
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "failed",
        "redirect",
        "other_url",
        "wrong_server",
        "late",
        "fake_command",
        "different_output",
        "review_only",
        "stderr_only",
    ],
)
def test_bounded_strategy_rejects_unauthenticated_announcement(tmp_path, mutation):
    command, events, write = write_native_stage(tmp_path)
    item = events[0]["item"]
    structured = item["result"]["structured_content"]
    if mutation == "failed":
        structured["statusCode"] = 403
    elif mutation == "redirect":
        structured["finalUrl"] = URL + "/elsewhere"
    elif mutation == "other_url":
        item["arguments"]["url"] = URL + "/elsewhere"
    elif mutation == "wrong_server":
        item["server"] = "agent_claimed_source"
    elif mutation == "late":
        events.reverse()
    elif mutation == "fake_command":
        command["argv"][0] = "agent-script"
    write()
    if mutation == "different_output":
        (tmp_path / "draft_codex_last_message.txt").write_text("a different forecast")
    elif mutation in {"review_only", "stderr_only"}:
        raw = (tmp_path / "draft_codex_stdout.jsonl").read_text()
        (tmp_path / "draft_codex_stdout.jsonl").write_text(
            json.dumps(events[-1]) + "\n"
        )
        destination = (
            "pre_submit_review_codex_stdout.jsonl"
            if mutation == "review_only"
            else "draft_codex_stderr.log"
        )
        (tmp_path / destination).write_text(raw)
    errors = generation.bounded_strategy_evidence_errors(tmp_path, RELATIVE, target())
    assert (
        len(errors) == 1 and "successful authenticated announcement fetch" in errors[0]
    )


def test_bounded_strategy_requires_the_ci_checkout_interpreter(tmp_path):
    command, _events, write = write_native_stage(tmp_path)
    command["argv"] = [
        arg.replace(
            "/home/runner/work/thesis/thesis/.venv/bin/python3", "/usr/bin/python3"
        )
        for arg in command["argv"]
    ]
    write()
    assert generation.bounded_strategy_evidence_errors(tmp_path, RELATIVE, target())


def test_strategy_context_authenticates_exact_target_and_witness(tmp_path, monkeypatch):
    payload = {
        "sourceSha": "a" * 40,
        "selectedAtUtc": "2026-09-22T05:09:00Z",
        "workflow": {"artifactCreatedAtUtc": "2026-09-22T05:10:00Z"},
        "targets": [target()],
        "billSelection": {"billSlug": "s3596-119"},
    }
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(payload))
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("")
    calls = []
    monkeypatch.setattr(
        generation.subprocess, "check_output", lambda *_a, **_k: "a" * 40
    )
    monkeypatch.setattr(
        generation,
        "verify_selection",
        lambda value, **kwargs: calls.append(("verify", value, kwargs)),
    )
    monkeypatch.setattr(
        generation,
        "ensure_open",
        lambda value, **kwargs: calls.append(("open", value, kwargs)),
    )
    kwargs = dict(
        root=tmp_path,
        selection_path=path,
        ledger_path=ledger,
        target=target(),
        run_started_at="2026-09-22T05:11:00Z",
    )
    assert generation.authenticate_strategy_target(**kwargs) == target()
    assert [row[0] for row in calls] == ["verify", "open"]
    assert calls[0][2]["ledger_path"] == ledger
    with pytest.raises(ValueError, match="prompt mode differs"):
        generation.authenticate_strategy_target(**kwargs, prompt_mode="ladder_v2")
    payload["request"] = {"ladderPromptMode": "ladder_v2"}
    path.write_text(json.dumps(payload))
    assert (
        generation.authenticate_strategy_target(**kwargs, prompt_mode="ladder_v2")
        == target()
    )
    path.write_text(json.dumps({**payload, "request": {}}))
    with pytest.raises(ValueError, match="differs from its reviewed selection"):
        generation.authenticate_strategy_target(
            **{**kwargs, "target": {**target(), "conditional": "Fabricated premise"}}
        )
    with pytest.raises(ValueError, match="selection witness"):
        generation.authenticate_strategy_target(
            **{**kwargs, "run_started_at": "2026-09-22T05:09:30Z"}
        )
    monkeypatch.setattr(
        generation.subprocess, "check_output", lambda *_a, **_k: "b" * 40
    )
    with pytest.raises(ValueError, match="checkout differs"):
        generation.authenticate_strategy_target(**kwargs)


def test_strategy_authentication_does_not_trust_fabricated_selection_hash(
    tmp_path, monkeypatch
):
    path = tmp_path / "selection.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_strategy_selection_v1",
                "sourceSha": "a" * 40,
                "selectionSetHash": "b" * 64,
            }
        )
    )
    monkeypatch.setattr(
        generation.subprocess, "check_output", lambda *_a, **_k: "a" * 40
    )
    with pytest.raises(ValueError, match="selectionSetHash mismatch"):
        generation.authenticate_strategy_target(
            root=tmp_path,
            selection_path=path,
            ledger_path=tmp_path / "ledger",
            target=target(),
            run_started_at="2026-09-22T05:11:00Z",
        )


def test_strategy_authentication_checks_pinned_ledger_before_reconstruction(
    tmp_path, monkeypatch
):
    path = tmp_path / "selection.json"
    payload = {
        "schemaVersion": "thesis_strategy_selection_v1",
        "sourceSha": "a" * 40,
        "ledgerEvidence": {"contentSha256": "b" * 64},
    }
    payload["selectionSetHash"] = canonical_sha256(payload)
    path.write_text(json.dumps(payload))
    ledger = tmp_path / "ledger"
    ledger.write_text("forged absence evidence")
    monkeypatch.setattr(
        generation.subprocess, "check_output", lambda *_a, **_k: "a" * 40
    )
    with pytest.raises(
        ValueError, match="pinned official ledger content hash mismatch"
    ):
        generation.authenticate_strategy_target(
            root=tmp_path,
            selection_path=path,
            ledger_path=ledger,
            target=target(),
            run_started_at="2026-09-22T05:11:00Z",
        )


def test_runner_strategy_mode_requires_real_native_lane(tmp_path, monkeypatch):
    args = SimpleNamespace(
        strategy_selection=tmp_path / "selection",
        strategy_ledger_jsonl=tmp_path / "ledger",
        command=None,
        response_file=None,
        mock_cell=False,
        pre_submit_review_command=None,
        codex_model="gpt-5.5",
        pre_submit_review_codex_model="gpt-5.5",
        prompt_mode="ladder",
        codex_sandbox="read-only",
        codex_network=False,
        no_codex_search=False,
        codex_reasoning_effort="low",
    )
    monkeypatch.setattr(
        generation, "authenticate_strategy_target", lambda **_kwargs: target()
    )
    kwargs = dict(run_started_at="2026-09-22T05:11:00Z", generation_ticket=None)
    assert (
        runner.parse_strategy_generation_context(args, target(), **kwargs) == target()
    )
    for field, value in (
        ("command", "python fake.py"),
        ("response_file", "fake.json"),
        ("mock_cell", True),
        ("pre_submit_review_command", "fake-review"),
        ("no_codex_search", True),
    ):
        bad = copy.copy(args)
        setattr(bad, field, value)
        with pytest.raises(SystemExit, match="reviewed native Codex ladder lane"):
            runner.parse_strategy_generation_context(bad, target(), **kwargs)


def test_batch_passes_selection_authority_only_for_bounded_strategy(
    tmp_path, monkeypatch
):
    args = batch.parse_args(
        [
            "--targets-file",
            str(tmp_path / "selection"),
            "--strategy-ledger-jsonl",
            str(tmp_path / "ledger"),
        ]
    )
    observed = []
    monkeypatch.delenv("THESIS_AGENT_COMMAND", raising=False)
    monkeypatch.setattr(
        batch.subprocess,
        "run",
        lambda argv, **_kwargs: observed.append(argv)
        or SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    bounded = {**target(), "series": "irs.actc.total_claims", "period": "2027"}
    batch.run_one(bounded, args)
    argv = observed[-1]
    assert argv[argv.index("--strategy-selection") + 1] == str(tmp_path / "selection")
    assert argv[argv.index("--strategy-ledger-jsonl") + 1] == str(tmp_path / "ledger")
    batch.run_one({**bounded, "resolutionDateBasis": "release-calendar"}, args)
    assert "--strategy-selection" not in observed[-1]
