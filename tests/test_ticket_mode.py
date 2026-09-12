from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generation_tickets  # noqa: E402
import run_thesis_batch as batch_runner  # noqa: E402

NONCE = "a" * 64
MINTED_AT = "2030-01-10T12:00:00Z"
RUN_NOW = datetime(2030, 1, 11, 12, 0, tzinfo=timezone.utc)


def git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def commit(repo: pathlib.Path, message: str, *, allow_empty: bool = False) -> str:
    argv = [
        "git",
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        message,
    ]
    if allow_empty:
        argv.append("--allow-empty")
    subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()


def sample_policy(
    *, network: bool = False, sandbox: str = "read-only"
) -> dict[str, Any]:
    return {
        "promptMode": "fast",
        "codexModel": "gpt-ticket-test",
        "codexReasoningEffort": "high",
        "codexSandbox": sandbox,
        "codexNetwork": network,
        "reviewCodexModel": "gpt-ticket-review",
        "reviewCodexSearch": True,
        "timeoutSeconds": 540,
    }


def sample_target(
    registration_commit: str,
    *,
    suffix: str = "primary",
) -> dict[str, Any]:
    digest = ("b" if suffix == "primary" else "c") * 64
    return {
        "series": "canary.synthetic.series",
        "period": "2030-Q1",
        "catalogSlug": f"synthetic-series-2030-q1-{suffix}",
        "registrationCommit": registration_commit,
        "targetContentHash": digest,
        "targetRegistrationPath": f"records/targets/2030-01-10-{digest}.json",
        "registeredAtUtc": "2030-01-10T10:00:00Z",
        "resolutionDate": "2030-02-01",
        "sourceBinding": {
            "expectedReleaseWindow": {
                "start": "2030-02-01",
                "end": "2030-02-01",
            }
        },
        "conditional": f"Synthetic condition {suffix}.",
    }


def build_ticket_repo(
    root: pathlib.Path,
    *,
    expires_hours: int = 168,
    targets_count: int = 1,
) -> dict[str, Any]:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "README.md").write_text("scratch ticket checkout\n")
    git(repo, "add", "README.md")
    base_sha = commit(repo, "Base")
    targets = [sample_target(base_sha)]
    if targets_count > 1:
        targets.append(sample_target(base_sha, suffix="secondary"))
    ticket = generation_tickets.mint_ticket(
        targets,
        sample_policy(),
        nonce=NONCE,
        minted_at_utc=MINTED_AT,
        expires_hours=expires_hours,
        attempt=1,
        registration_set_hash="d" * 64,
    )
    relative = generation_tickets.ticket_record_path(ticket["ticketId"])
    ticket_path = repo.joinpath(*relative.parts)
    ticket_path.parent.mkdir(parents=True)
    ticket_path.write_text(json.dumps(ticket, sort_keys=True) + "\n")
    git(repo, "add", relative.as_posix())
    ticket_sha = commit(repo, "Mint ticket")
    return {
        "repo": repo,
        "ticket": ticket,
        "ticketPath": ticket_path,
        "ticketRelative": relative,
        "ticketSha": ticket_sha,
    }


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--target", "series:period"),
        ("--targets-file", "targets.json"),
        ("--max-targets", "1"),
        ("--skip", "1"),
        ("--max-failures", "1"),
        ("--command", "codex exec"),
        ("--codex-model", "gpt-override"),
        ("--gemini-model", "gemini-3.7-flash"),
        ("--codex-reasoning-effort", "low"),
        ("--no-codex-search", None),
        ("--codex-sandbox", "workspace-write"),
        ("--codex-network", None),
        ("--prompt-mode", "full"),
        ("--pre-submit-review-codex-model", "gpt-review-override"),
        ("--no-pre-submit-review", None),
        ("--pre-submit-review-codex-search", None),
        ("--timeout-seconds", "60"),
        ("--out", "batch.json"),
    ],
)
def test_ticket_mode_refuses_each_overlapping_flag_literally(
    option: str, value: str | None
) -> None:
    argv = ["--ticket", "ticket.json", option]
    if value is not None:
        argv.append(value)

    with pytest.raises(batch_runner.BatchRunError) as error:
        batch_runner.refuse_ticket_conflicts(argv)

    assert str(error.value) == (
        f"ticket mode refuses {option}: generation policy and target scope "
        "come from the ticket"
    )


def test_ticket_mode_refuses_equals_form_conflict_literally() -> None:
    with pytest.raises(batch_runner.BatchRunError) as error:
        batch_runner.refuse_ticket_conflicts(
            ["--ticket=ticket.json", "--prompt-mode=fast"]
        )

    assert str(error.value) == (
        "ticket mode refuses --prompt-mode: generation policy and target scope "
        "come from the ticket"
    )


@pytest.mark.parametrize("abbreviation", ["--tick=ticket.json", "--prom=full"])
def test_ticket_mode_does_not_accept_abbreviated_long_options(
    abbreviation: str,
) -> None:
    argv = ["--ticket", "ticket.json", abbreviation]
    if abbreviation.startswith("--tick="):
        argv = [abbreviation]

    with pytest.raises(SystemExit) as error:
        batch_runner.parse_args(argv)

    assert error.value.code == 2


def test_prepare_ticket_mode_returns_exact_context(tmp_path: pathlib.Path) -> None:
    fixture = build_ticket_repo(tmp_path)

    ticket, context, checkout_sha = batch_runner.prepare_ticket_mode(
        fixture["ticketRelative"],
        repo_root=fixture["repo"],
        now_utc=RUN_NOW,
    )

    assert ticket == fixture["ticket"]
    assert context == {
        "ticketId": ticket["ticketId"],
        "ticketPath": fixture["ticketRelative"].as_posix(),
        "nonce": NONCE,
    }
    assert checkout_sha == fixture["ticketSha"]


def test_ticket_mode_refuses_expired_ticket_literally(tmp_path: pathlib.Path) -> None:
    fixture = build_ticket_repo(tmp_path, expires_hours=24)

    with pytest.raises(batch_runner.BatchRunError) as error:
        batch_runner.prepare_ticket_mode(
            fixture["ticketPath"],
            repo_root=fixture["repo"],
            now_utc=RUN_NOW,
        )

    assert str(error.value) == (
        f"generation ticket {fixture['ticket']['ticketId']} expired at "
        "2030-01-11T12:00:00Z"
    )


def test_ticket_mode_refuses_consumed_before_checkout_mismatch(
    tmp_path: pathlib.Path,
) -> None:
    fixture = build_ticket_repo(tmp_path)
    consumption = (
        fixture["repo"]
        / "records"
        / "thesis-analyst"
        / "batches"
        / "2030-01-11"
        / f"attested-{fixture['ticket']['ticketId']}.json"
    )
    consumption.parent.mkdir(parents=True)
    consumption.write_text("{}\n")
    git(fixture["repo"], "add", consumption.relative_to(fixture["repo"]).as_posix())
    commit(fixture["repo"], "Consume ticket")

    with pytest.raises(batch_runner.BatchRunError) as error:
        batch_runner.prepare_ticket_mode(
            fixture["ticketPath"],
            repo_root=fixture["repo"],
            now_utc=RUN_NOW,
        )

    relative = consumption.relative_to(fixture["repo"]).as_posix()
    assert str(error.value) == (
        f"generation ticket {fixture['ticket']['ticketId']} was already consumed "
        f"by {relative}"
    )


def test_ticket_mode_refuses_superseded_before_checkout_mismatch(
    tmp_path: pathlib.Path,
) -> None:
    fixture = build_ticket_repo(tmp_path)
    successor = generation_tickets.mint_ticket(
        fixture["ticket"]["targets"],
        sample_policy(),
        nonce="e" * 64,
        minted_at_utc="2030-01-11T11:00:00Z",
        expires_hours=168,
        attempt=2,
        supersedes=fixture["ticket"]["ticketId"],
        superseded_outcome={"outcome": "failed", "reason": "agent failed"},
        registration_set_hash="d" * 64,
        predecessor_ticket=fixture["ticket"],
    )
    relative = generation_tickets.ticket_record_path(successor["ticketId"])
    successor_path = fixture["repo"].joinpath(*relative.parts)
    successor_path.parent.mkdir(parents=True, exist_ok=True)
    successor_path.write_text(json.dumps(successor, sort_keys=True) + "\n")
    git(fixture["repo"], "add", relative.as_posix())
    commit(fixture["repo"], "Supersede ticket")

    with pytest.raises(batch_runner.BatchRunError) as error:
        batch_runner.prepare_ticket_mode(
            fixture["ticketPath"],
            repo_root=fixture["repo"],
            now_utc=RUN_NOW,
        )

    assert str(error.value) == (
        f"generation ticket {fixture['ticket']['ticketId']} was superseded by "
        f"{relative.as_posix()}"
    )


def test_ticket_mode_refuses_dirty_checkout_literally(tmp_path: pathlib.Path) -> None:
    fixture = build_ticket_repo(tmp_path)
    (fixture["repo"] / "dirty.txt").write_text("dirty\n")

    with pytest.raises(batch_runner.BatchRunError) as error:
        batch_runner.prepare_ticket_mode(
            fixture["ticketPath"],
            repo_root=fixture["repo"],
            now_utc=RUN_NOW,
        )

    assert str(error.value) == (
        "ticket mode requires a clean checkout; git status begins: ?? dirty.txt"
    )


def test_ticket_mode_refuses_head_mismatch_with_both_shas(
    tmp_path: pathlib.Path,
) -> None:
    fixture = build_ticket_repo(tmp_path)
    later_sha = commit(fixture["repo"], "Later", allow_empty=True)

    with pytest.raises(batch_runner.BatchRunError) as error:
        batch_runner.prepare_ticket_mode(
            fixture["ticketPath"],
            repo_root=fixture["repo"],
            now_utc=RUN_NOW,
        )

    assert str(error.value) == (
        f"ticket checkout mismatch: HEAD {later_sha} != ticket introducing commit "
        f"{fixture['ticketSha']}"
    )


def test_ticket_mode_derives_every_policy_argument_and_batch_path(
    tmp_path: pathlib.Path,
) -> None:
    fixture = build_ticket_repo(tmp_path)
    args = batch_runner.parse_args(["--ticket", str(fixture["ticketPath"])])

    batch_runner.apply_ticket_policy(args, fixture["ticket"])

    assert args.prompt_mode == "fast"
    assert args.codex_model == "gpt-ticket-test"
    assert args.gemini_model is None
    assert args.codex_reasoning_effort == "high"
    assert args.codex_sandbox == "read-only"
    assert args.codex_network is False
    assert args.no_codex_search is False
    assert args.command is None
    assert args.pre_submit_review_codex_model == "gpt-ticket-review"
    assert args.pre_submit_review_codex_search is True
    assert args.no_pre_submit_review is False
    assert args.timeout_seconds == 540
    assert batch_runner.ticket_batch_path(
        fixture["repo"], "2030-01-12T00:00:01Z", fixture["ticket"]
    ) == (
        fixture["repo"]
        / "records"
        / "thesis-analyst"
        / "batches"
        / "2030-01-12"
        / f"attested-{fixture['ticket']['ticketId']}.json"
    )


def test_ticket_run_one_uses_only_ticket_native_codex_policy(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_ticket_repo(tmp_path)
    args = batch_runner.parse_args(["--ticket", str(fixture["ticketPath"])])
    batch_runner.apply_ticket_policy(args, fixture["ticket"])
    context = {
        "ticketId": fixture["ticket"]["ticketId"],
        "ticketPath": fixture["ticketRelative"].as_posix(),
        "nonce": NONCE,
    }
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        manifest = {"ok": True, "cellsPath": "cells.json", "artifacts": []}
        return subprocess.CompletedProcess(argv, 0, json.dumps(manifest), "")

    monkeypatch.setenv("THESIS_AGENT_COMMAND", "forbidden custom command")
    monkeypatch.setenv("THESIS_CODEX_MODEL", "forbidden-env-model")
    monkeypatch.setenv("THESIS_GEMINI_MODEL", "forbidden-gemini-model")
    monkeypatch.setattr(batch_runner.subprocess, "run", fake_run)

    result = batch_runner.run_one(fixture["ticket"]["targets"][0], args, context)

    argv = seen["argv"]
    assert result["ok"] is True
    assert "--command" not in argv
    assert "forbidden custom command" not in argv
    assert argv[argv.index("--codex-model") + 1] == "gpt-ticket-test"
    assert "forbidden-env-model" not in argv
    assert "--gemini-model" not in argv
    assert "forbidden-gemini-model" not in argv
    assert argv[argv.index("--codex-reasoning-effort") + 1] == "high"
    assert argv[argv.index("--codex-sandbox") + 1] == "read-only"
    assert argv[argv.index("--pre-submit-review-codex-model") + 1] == (
        "gpt-ticket-review"
    )
    assert "--pre-submit-review-codex-search" in argv
    assert argv[argv.index("--timeout-seconds") + 1] == "540"
    assert argv[argv.index("--ticket-id") + 1] == context["ticketId"]
    assert argv[argv.index("--ticket-path") + 1] == context["ticketPath"]
    assert argv[argv.index("--ticket-nonce") + 1] == NONCE


@pytest.mark.parametrize("from_environment", [False, True])
def test_non_ticket_run_one_passes_gemini_model_from_flag_or_env(
    monkeypatch: pytest.MonkeyPatch,
    from_environment: bool,
) -> None:
    model = "gemini-3.7-flash"
    args = batch_runner.parse_args(
        [] if from_environment else ["--gemini-model", model]
    )
    args.no_pre_submit_review = True
    if from_environment:
        monkeypatch.setenv("THESIS_GEMINI_MODEL", model)
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["argv"] = argv
        manifest = {"ok": True, "cellsPath": "cells.json", "artifacts": []}
        return subprocess.CompletedProcess(argv, 0, json.dumps(manifest), "")

    monkeypatch.setattr(batch_runner.subprocess, "run", fake_run)
    result = batch_runner.run_one(
        {"series": "test.gemini", "period": "2030-01"}, args
    )

    argv = seen["argv"]
    assert result["ok"] is True
    assert argv[argv.index("--gemini-model") + 1] == model
    assert "--codex-model" not in argv
    assert "--codex-reasoning-effort" not in argv
    assert "--codex-sandbox" not in argv
    assert "--codex-network" not in argv


def test_non_ticket_batch_refuses_ambiguous_backend_selection() -> None:
    args = batch_runner.parse_args(
        ["--codex-model", "gpt-5.5", "--gemini-model", "gemini-3.7-flash"]
    )

    with pytest.raises(
        batch_runner.BatchRunError,
        match="non-ticket batch forecast backend is ambiguous",
    ):
        batch_runner.resolve_agent_backend(args)


def test_ticket_batch_manifest_records_policy_binding_and_checkout(
    tmp_path: pathlib.Path,
) -> None:
    fixture = build_ticket_repo(tmp_path)
    args = batch_runner.parse_args(["--ticket", str(fixture["ticketPath"])])
    batch_runner.apply_ticket_policy(args, fixture["ticket"])
    context = {
        "ticketId": fixture["ticket"]["ticketId"],
        "ticketPath": fixture["ticketRelative"].as_posix(),
        "nonce": NONCE,
    }
    out = tmp_path / "batch.json"
    results = [{"ok": True}]

    batch_runner.write_batch_manifest(
        out,
        "2030-01-11T12:00:00Z",
        "2030-01-11T12:05:00Z",
        args,
        results,
        context,
        fixture["ticketSha"],
    )

    manifest = json.loads(out.read_text())
    assert manifest["promptMode"] == "fast"
    assert manifest["codexModel"] == "gpt-ticket-test"
    assert manifest["codexReasoningEffort"] == "high"
    assert manifest["codexSandbox"] == "read-only"
    assert manifest["codexNetwork"] is False
    assert manifest["reviewCodexModel"] == "gpt-ticket-review"
    assert manifest["reviewCodexSearch"] is True
    assert manifest["timeoutSeconds"] == 540
    assert manifest["generationTicket"] == {
        "ticketId": fixture["ticket"]["ticketId"],
        "ticketPath": fixture["ticketRelative"].as_posix(),
        "nonceSha256": hashlib.sha256(NONCE.encode()).hexdigest(),
    }
    assert manifest["checkoutSha"] == fixture["ticketSha"]


def test_ticket_main_uses_actual_start_day_and_runs_every_target(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_ticket_repo(tmp_path, targets_count=2)
    calls: list[str] = []

    original_parse_args = batch_runner.parse_args

    def parse_with_one_failure(argv: list[str] | None = None) -> Any:
        args = original_parse_args(argv)
        args.max_failures = 1
        return args

    def fake_run_one(
        target: dict[str, Any],
        args: Any,
        ticket_context: dict[str, str] | None,
    ) -> dict[str, Any]:
        calls.append(target["catalogSlug"])
        ok = len(calls) > 1
        return {
            "target": target,
            "startedAt": "2030-01-12T00:00:01Z",
            "finishedAt": "2030-01-12T00:00:02Z",
            "returnCode": 0 if ok else 1,
            "ok": ok,
            "manifestPath": None,
            "cellsPath": None,
            "stdoutTail": "",
            "stderrTail": "",
            "validationErrors": [],
        }

    monkeypatch.setattr(batch_runner, "parse_args", parse_with_one_failure)
    monkeypatch.setattr(batch_runner, "run_one", fake_run_one)
    monkeypatch.setattr(batch_runner, "utc_now", lambda: "2030-01-12T00:00:01Z")

    assert (
        batch_runner.main(
            ["--ticket", str(fixture["ticketPath"])],
            repo_root=fixture["repo"],
            now_utc=RUN_NOW,
        )
        == 1
    )

    assert calls == [
        "synthetic-series-2030-q1-primary",
        "synthetic-series-2030-q1-secondary",
    ]
    out = (
        fixture["repo"]
        / "records"
        / "thesis-analyst"
        / "batches"
        / "2030-01-12"
        / f"attested-{fixture['ticket']['ticketId']}.json"
    )
    manifest = json.loads(out.read_text())
    assert manifest["startedAt"] == "2030-01-12T00:00:01Z"
    assert manifest["targets"] == 2
    assert len(manifest["results"]) == 2


def test_ticket_main_reports_conflict_without_loading_ticket(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        batch_runner.main(["--ticket", "missing.json", "--timeout-seconds", "60"]) == 1
    )
    assert capsys.readouterr().err == (
        "batch run refused: ticket mode refuses --timeout-seconds: generation "
        "policy and target scope come from the ticket\n"
    )
