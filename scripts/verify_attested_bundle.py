#!/usr/bin/env python3
"""Verify a locally assembled bundle against its trusted generation ticket.

This verifier is deliberately conservative about prompt reconstruction.  It
uses the trusted code in the current checkout, not code supplied by the
bundle.  A prompt-builder change after ticket minting therefore makes an old
bundle unverifiable unless the reconstructed bytes remain identical.

The ordinary docket publication battery remains a separate workflow step.
This module checks only the additional ticket, command, and derivation claims
made by the attested local generation lane. Passing proves post-mint assembly
and internal consistency of the published artifact set, plus eligibility for
one publication. It does not prove one execution, model authorship, trusted
local wall time, or the absence of inputs hidden from git status by ignore
rules.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

from canonical_json import canonical_sha256
from docket_publication import (
    BATCH_RE,
    PublicationError,
    load_bundle,
    load_json,
    relative_repo_path,
    safe_join,
)
from generation_tickets import (
    TicketError,
    earliest_resolution_boundary,
    find_ticket_consumption,
    find_ticket_successor,
    load_ticket,
    ticket_batch_filename,
    ticket_introducing_commit,
    ticket_manifest_binding,
    ticket_record_path,
)
from run_thesis_analyst import (
    ANNOUNCEMENT_MCP_SERVER,
    ANNOUNCEMENT_MCP_TOOL,
    announcement_mcp_config,
    attach_activity_log,
    build_pre_submit_review_metadata,
    build_pre_submit_review_prompt,
    build_revision_prompt,
    build_run_prompt,
    canonical_equal,
    extract_json_payload,
    normalize_cells,
    parse_codex_jsonl,
    parse_review_payload,
    seal_normalized_cells,
    stamp_runtime_invocation,
    tool_evidence_mcp_config,
    validate_cells,
)
from verify_custody import (
    TOOL_EVIDENCE_SERVER,
    CustodyError,
    verify_tool_evidence_stage,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
POLICY_FIELDS = {
    "promptMode": "promptMode",
    "codexModel": "codexModel",
    "codexReasoningEffort": "codexReasoningEffort",
    "codexSandbox": "codexSandbox",
    "codexNetwork": "codexNetwork",
    "reviewCodexModel": "reviewCodexModel",
    "reviewCodexSearch": "reviewCodexSearch",
    "timeoutSeconds": "timeoutSeconds",
}
FORBIDDEN_COMMAND_OPTIONS = (
    "--response-file",
    "--mock-cell",
    "--resume",
    "--continue",
)


class AttestedBundleError(ValueError):
    """The bundle failed an attested-lane-specific trust check."""


@dataclass(frozen=True)
class TicketContext:
    path: pathlib.Path
    relative: pathlib.PurePosixPath
    ticket: dict[str, Any]
    prompt_context: dict[str, str]
    manifest_binding: dict[str, str]


@dataclass(frozen=True)
class RunEnvelope:
    index: int
    result: dict[str, Any]
    target: dict[str, Any]
    manifest_relative: pathlib.PurePosixPath
    manifest_path: pathlib.Path
    manifest: dict[str, Any]

    @property
    def run_relative(self) -> pathlib.PurePosixPath:
        return self.manifest_relative.parent


@dataclass(frozen=True)
class PromptEvidence:
    runtime_meta: dict[str, Any]
    original_prompt: str
    draft_response: str
    draft_events: tuple[dict[str, Any], ...]
    review_response: str


@dataclass(frozen=True)
class CodexStageEvidence:
    last_message: str
    stdout_events: tuple[dict[str, Any], ...]


def _fail(phase: str, message: str) -> AttestedBundleError:
    return AttestedBundleError(f"{phase} check failed: {message}")


@contextlib.contextmanager
def _phase_guard(phase: str):
    """Keep malformed untrusted input inside the typed refusal contract."""

    try:
        yield
    except AttestedBundleError:
        raise
    except Exception as exc:
        raise _fail(
            phase,
            "verification could not safely inspect untrusted input "
            f"because it raised {type(exc).__name__}",
        ) from exc


def _parse_utc(value: Any, *, phase: str, label: str) -> dt.datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value
    ):
        raise _fail(phase, f"{label} must be a second-precision UTC instant")
    try:
        return dt.datetime.strptime(value, UTC_FORMAT).replace(tzinfo=dt.timezone.utc)
    except ValueError as exc:
        raise _fail(phase, f"{label} is not a valid UTC instant: {value!r}") from exc


def _normalize_now(now_utc: dt.datetime) -> dt.datetime:
    if (
        not isinstance(now_utc, dt.datetime)
        or now_utc.tzinfo is None
        or now_utc.utcoffset() != dt.timedelta(0)
    ):
        raise _fail("ticket", "now_utc must be timezone-aware UTC")
    return now_utc.astimezone(dt.timezone.utc)


def _load_ticket_context(
    ticket_path: str | pathlib.Path,
    *,
    repo_root: pathlib.Path,
    now_utc: dt.datetime,
) -> TicketContext:
    candidate = pathlib.Path(ticket_path)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    try:
        relative = pathlib.PurePosixPath(
            candidate.resolve().relative_to(repo_root).as_posix()
        )
    except ValueError as exc:
        raise _fail(
            "ticket", f"ticket path is outside the repository: {ticket_path}"
        ) from exc
    try:
        resolved = safe_join(repo_root, relative)
    except PublicationError as exc:
        raise _fail("ticket", str(exc)) from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise _fail("ticket", f"ticket is not a regular file: {relative}")
    try:
        ticket = load_ticket(resolved)
    except TicketError as exc:
        raise _fail("ticket", str(exc)) from exc
    expected = ticket_record_path(ticket["ticketId"])
    if relative != expected:
        raise _fail(
            "ticket",
            f"ticket path does not match its identity: {relative} != {expected}",
        )

    now = _normalize_now(now_utc)
    expires = _parse_utc(
        ticket["expiresAtUtc"], phase="ticket", label="ticket expiresAtUtc"
    )
    if now >= expires:
        raise _fail(
            "ticket",
            f"generation ticket {ticket['ticketId']} expired at "
            f"{ticket['expiresAtUtc']}",
        )
    boundary = _parse_utc(
        earliest_resolution_boundary(ticket["targets"]),
        phase="ticket",
        label="targets' resolution boundary",
    )
    if now >= boundary:
        raise _fail(
            "ticket",
            "verification time is at or past the targets' resolution boundary",
        )
    try:
        consumption = find_ticket_consumption(ticket["ticketId"], repo_root)
        if consumption is not None:
            raise _fail(
                "ticket",
                f"generation ticket {ticket['ticketId']} was already consumed by "
                f"{consumption}",
            )
        successor = find_ticket_successor(ticket["ticketId"], repo_root)
        if successor is not None:
            raise _fail(
                "ticket",
                f"generation ticket {ticket['ticketId']} was superseded by {successor}",
            )
    except TicketError as exc:
        raise _fail("ticket", str(exc)) from exc

    expected_set_hash = canonical_sha256({"targets": ticket["targets"]})
    if ticket["registrationSetHash"] != expected_set_hash:
        raise _fail(
            "ticket",
            "registrationSetHash does not match the ticket target set: "
            f"{ticket['registrationSetHash']} != {expected_set_hash}",
        )
    prompt_context = {
        "ticketId": ticket["ticketId"],
        "ticketPath": relative.as_posix(),
        "nonce": ticket["nonce"],
    }
    try:
        binding = ticket_manifest_binding(prompt_context)
    except TicketError as exc:
        raise _fail("ticket", str(exc)) from exc
    return TicketContext(resolved, relative, ticket, prompt_context, binding)


def _load_declared_batch(
    bundle_dir: pathlib.Path,
    ticket: dict[str, Any],
) -> tuple[pathlib.PurePosixPath, dict[str, Any]]:
    manifest_path = bundle_dir / "bundle_manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise _fail("bundle", "bundle manifest is not a regular file")
    try:
        bundle_manifest = json.loads(manifest_path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("bundle", f"invalid bundle manifest: {exc}") from exc
    if not isinstance(bundle_manifest, dict):
        raise _fail("bundle", "bundle manifest must be a JSON object")
    entries = bundle_manifest.get("files")
    if not isinstance(entries, list) or not all(
        isinstance(entry, dict) for entry in entries
    ):
        raise _fail("bundle", "bundle file inventory must be an object list")
    candidates: list[pathlib.PurePosixPath] = []
    for entry in entries:
        value = entry.get("path")
        if not isinstance(value, str):
            continue
        try:
            relative = relative_repo_path(value)
        except PublicationError:
            continue
        if BATCH_RE.fullmatch(relative.as_posix()):
            candidates.append(relative)
    if len(candidates) != 1:
        raise _fail(
            "bundle",
            f"bundle must declare exactly one batch manifest; found {len(candidates)}",
        )
    batch_relative = candidates[0]
    expected_name = ticket_batch_filename(ticket)
    if batch_relative.name != expected_name:
        raise _fail(
            "bundle",
            f"batch filename does not match generation ticket: "
            f"{batch_relative.name} != {expected_name}",
        )
    try:
        batch_path = safe_join(bundle_dir / "repo", batch_relative)
        batch = load_json(batch_path, "batch manifest")
    except PublicationError as exc:
        raise _fail("bundle", str(exc)) from exc
    if not isinstance(batch, dict):
        raise _fail("bundle", "batch manifest must be a JSON object")
    match = BATCH_RE.fullmatch(batch_relative.as_posix())
    assert match is not None
    started_at = _parse_utc(
        batch.get("startedAt"), phase="bundle", label="batch startedAt"
    )
    if match.group("day") != started_at.date().isoformat():
        raise _fail(
            "bundle",
            "batch path day does not match batch startedAt day: "
            f"{match.group('day')} != {started_at.date().isoformat()}",
        )
    return batch_relative, batch


def _load_runs(
    bundle_repo: pathlib.Path,
    batch: dict[str, Any],
    ticket: dict[str, Any],
) -> list[RunEnvelope]:
    results = batch.get("results")
    if not isinstance(results, list) or not all(
        isinstance(result, dict) for result in results
    ):
        raise _fail("bundle", "batch results must be an object list")
    if len(results) != len(ticket["targets"]):
        raise _fail(
            "bundle",
            "batch result inventory differs from ticket targets: "
            f"{len(results)} != {len(ticket['targets'])}",
        )
    seen: set[pathlib.PurePosixPath] = set()
    runs: list[RunEnvelope] = []
    for index, result in enumerate(results):
        target = result.get("target")
        if not isinstance(target, dict):
            raise _fail("bundle", f"result {index} has no target context")
        manifest_value = result.get("manifestPath")
        cells_value = result.get("cellsPath")
        if not isinstance(manifest_value, str) or not manifest_value:
            raise _fail("bundle", f"result {index} has no run manifest")
        if not isinstance(cells_value, str) or not cells_value:
            raise _fail("bundle", f"result {index} has no replayable cells payload")
        try:
            manifest_relative = relative_repo_path(manifest_value)
            manifest_path = safe_join(bundle_repo, manifest_relative)
            manifest = load_json(manifest_path, f"run manifest {index}")
        except PublicationError as exc:
            raise _fail("bundle", str(exc)) from exc
        if manifest_relative in seen:
            raise _fail("bundle", f"duplicate run manifest: {manifest_relative}")
        seen.add(manifest_relative)
        if not isinstance(manifest, dict):
            raise _fail("bundle", f"run manifest {index} must be a JSON object")
        expected_cells = manifest_relative.parent / "cells.with_activity.json"
        if cells_value != expected_cells.as_posix():
            raise _fail(
                "bundle",
                f"result {index} cells payload is outside its run: {cells_value}",
            )
        if manifest.get("cellsPath") != cells_value:
            raise _fail(
                "bundle", f"run manifest {index} cellsPath differs from its result"
            )
        runs.append(
            RunEnvelope(
                index,
                result,
                target,
                manifest_relative,
                manifest_path,
                manifest,
            )
        )
    return runs


def _check_policy(
    batch: dict[str, Any],
    ticket: dict[str, Any],
    runs: list[RunEnvelope],
) -> None:
    policy = ticket["policy"]
    for batch_field, policy_field in POLICY_FIELDS.items():
        actual = batch.get(batch_field)
        expected = policy[policy_field]
        if not canonical_equal(actual, expected):
            raise _fail(
                "policy",
                f"batch {batch_field} does not match ticket policy: "
                f"{actual!r} != {expected!r}",
            )
    for run in runs:
        if run.manifest.get("promptMode") != policy["promptMode"]:
            raise _fail(
                "policy",
                f"run {run.index} promptMode does not match ticket policy: "
                f"{run.manifest.get('promptMode')!r} != "
                f"{policy['promptMode']!r}",
            )


def _git_output(repo_root: pathlib.Path, *args: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=repo_root, stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode(errors="replace").strip()
        raise _fail(
            "binding",
            f"git {' '.join(args)} failed" + (f": {detail}" if detail else ""),
        ) from exc


def _check_bindings(
    state: TicketContext,
    batch: dict[str, Any],
    runs: list[RunEnvelope],
    *,
    repo_root: pathlib.Path,
) -> str:
    try:
        introducing = ticket_introducing_commit(state.relative, repo_root)
    except TicketError as exc:
        raise _fail("binding", str(exc)) from exc
    committed_ticket = _git_output(
        repo_root, "show", f"{introducing}:{state.relative.as_posix()}"
    )
    if committed_ticket != state.path.read_bytes():
        raise _fail(
            "binding", "current ticket bytes differ from its introducing commit"
        )
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", introducing, "HEAD"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if ancestor.returncode != 0:
        detail = ancestor.stderr.decode(errors="replace").strip()
        raise _fail(
            "binding",
            f"ticket introducing commit is not an ancestor of HEAD: {introducing}"
            + (f" ({detail})" if detail else ""),
        )
    if not canonical_equal(batch.get("generationTicket"), state.manifest_binding):
        raise _fail("binding", "batch generationTicket does not match the ticket")
    if batch.get("checkoutSha") != introducing:
        raise _fail(
            "binding",
            f"batch checkoutSha does not match ticket introducing commit: "
            f"{batch.get('checkoutSha')!r} != {introducing}",
        )
    # A transcript binding the nonce cannot predate mint, so the nonce proves
    # the published artifact set was assembled after mint. It does not prove
    # the forecasting work occurred then; these checks refuse CLAIMED clocks
    # that contradict the assembly boundary.
    minted = _parse_utc(
        state.ticket["mintedAtUtc"], phase="binding", label="ticket mintedAtUtc"
    )
    batch_started = _parse_utc(
        batch.get("startedAt"), phase="binding", label="batch startedAt"
    )
    if batch_started < minted:
        raise _fail(
            "binding",
            "batch startedAt predates ticket mint: "
            f"{batch.get('startedAt')} < {state.ticket['mintedAtUtc']}",
        )
    for run in runs:
        manifest = run.manifest
        if manifest.get("schemaVersion") != "thesis_analyst_run_manifest_v1":
            raise _fail(
                "binding", f"run {run.index} has an unsupported manifest schema"
            )
        run_started = _parse_utc(
            manifest.get("runStartedAt"),
            phase="binding",
            label=f"run {run.index} runStartedAt",
        )
        if run_started < minted:
            raise _fail(
                "binding",
                f"run {run.index} runStartedAt predates ticket mint: "
                f"{manifest.get('runStartedAt')} < {state.ticket['mintedAtUtc']}",
            )
        if not canonical_equal(
            manifest.get("generationTicket"), state.manifest_binding
        ):
            raise _fail(
                "binding", f"run {run.index} generationTicket does not match ticket"
            )
        if manifest.get("checkoutSha") != introducing:
            raise _fail(
                "binding",
                f"run {run.index} checkoutSha does not match ticket introducing "
                f"commit: {manifest.get('checkoutSha')!r} != {introducing}",
            )
        if not canonical_equal(manifest.get("targetContext"), run.target):
            raise _fail(
                "binding",
                f"run {run.index} targetContext differs from its ticket target",
            )
        for field in ("series", "period", "conditional"):
            if not canonical_equal(manifest.get(field), run.target.get(field)):
                raise _fail(
                    "binding",
                    f"run {run.index} target identity mismatch: {field}",
                )
    return introducing


def _artifact_ref(
    run: RunEnvelope,
    *,
    filename: str,
    artifact_type: str,
    phase: str,
) -> dict[str, Any]:
    artifacts = run.manifest.get("artifacts")
    if not isinstance(artifacts, list) or not all(
        isinstance(artifact, dict) for artifact in artifacts
    ):
        raise _fail(phase, f"run {run.index} has no artifact inventory")
    expected = (run.run_relative / filename).as_posix()
    matches = [
        artifact
        for artifact in artifacts
        if artifact.get("path") == expected
        and artifact.get("artifactType") == artifact_type
    ]
    if len(matches) != 1:
        raise _fail(
            phase,
            f"run {run.index} must declare exactly one {filename} "
            f"({artifact_type}); found {len(matches)}",
        )
    return matches[0]


def _artifact_bytes(
    bundle_repo: pathlib.Path,
    run: RunEnvelope,
    *,
    filename: str,
    artifact_type: str,
    phase: str,
) -> bytes:
    ref = _artifact_ref(
        run,
        filename=filename,
        artifact_type=artifact_type,
        phase=phase,
    )
    expected = (run.run_relative / filename).as_posix()
    try:
        path = safe_join(bundle_repo, pathlib.PurePosixPath(expected))
    except PublicationError as exc:
        raise _fail(phase, str(exc)) from exc
    if path.is_symlink() or not path.is_file():
        raise _fail(
            phase,
            f"run {run.index} artifact is not a regular file: {expected}",
        )
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if type(ref.get("bytes")) is not int or ref["bytes"] != len(raw):
        raise _fail(phase, f"run {run.index} artifact byte count mismatch: {filename}")
    if ref.get("sha256") != digest:
        raise _fail(phase, f"run {run.index} artifact hash mismatch: {filename}")
    return raw


def _json_artifact(
    bundle_repo: pathlib.Path,
    run: RunEnvelope,
    *,
    filename: str,
    artifact_type: str,
    phase: str,
) -> Any:
    raw = _artifact_bytes(
        bundle_repo,
        run,
        filename=filename,
        artifact_type=artifact_type,
        phase=phase,
    )
    try:
        return json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _fail(
            phase, f"run {run.index} artifact is invalid JSON: {filename}: {exc}"
        ) from exc


def _decode_artifact(
    raw: bytes,
    *,
    run: RunEnvelope,
    filename: str,
    phase: str,
) -> str:
    try:
        return raw.decode()
    except UnicodeError as exc:
        raise _fail(
            phase,
            f"run {run.index} artifact is not UTF-8: {filename}",
        ) from exc


def _replay_codex_stage(
    bundle_repo: pathlib.Path,
    run: RunEnvelope,
    *,
    prefix: str,
    stdout_artifact_type: str,
    model: str,
    search: bool,
    policy: dict[str, Any],
    phase: str,
) -> CodexStageEvidence:
    """Replay one successful runner-emitted Codex artifact family."""

    def stage_name(suffix: str) -> str:
        return f"{prefix}{suffix}"

    stdout_filename = stage_name("codex_stdout.jsonl")
    stderr_filename = stage_name("codex_stderr.log")
    stdout = _decode_artifact(
        _artifact_bytes(
            bundle_repo,
            run,
            filename=stdout_filename,
            artifact_type="codex_stdout_jsonl",
            phase=phase,
        ),
        run=run,
        filename=stdout_filename,
        phase=phase,
    )
    stderr = _decode_artifact(
        _artifact_bytes(
            bundle_repo,
            run,
            filename=stderr_filename,
            artifact_type="codex_stderr_log",
            phase=phase,
        ),
        run=run,
        filename=stderr_filename,
        phase=phase,
    )
    try:
        parsed = parse_codex_jsonl(stdout, stderr)
        stdout_parsed = parse_codex_jsonl(stdout, "")
    except Exception as exc:
        raise _fail(
            phase,
            f"run {run.index} {stdout_filename} could not be replayed: "
            f"{type(exc).__name__}",
        ) from exc

    last_filename = stage_name("codex_last_message.txt")
    last_raw = _artifact_bytes(
        bundle_repo,
        run,
        filename=last_filename,
        artifact_type="codex_last_message",
        phase=phase,
    )
    last_message = _decode_artifact(
        last_raw,
        run=run,
        filename=last_filename,
        phase=phase,
    )
    if stdout_parsed["lastAssistantText"] != last_message:
        stage_label = prefix.replace("_", " ") if prefix else ""
        raise _fail(
            phase,
            f"run {run.index} {stage_label}last assistant message differs "
            f"from {last_filename}",
        )

    response_filename = stage_name("stdout.txt")
    response_raw = _artifact_bytes(
        bundle_repo,
        run,
        filename=response_filename,
        artifact_type=stdout_artifact_type,
        phase=phase,
    )
    if response_raw != last_raw:
        raise _fail(
            phase,
            f"run {run.index} {response_filename} differs from {last_filename}",
        )

    events_filename = stage_name("codex_events.jsonl")
    events_raw = _artifact_bytes(
        bundle_repo,
        run,
        filename=events_filename,
        artifact_type="codex_events_jsonl",
        phase=phase,
    )
    if events_raw != parsed["eventsJsonl"].encode():
        raise _fail(
            phase,
            f"run {run.index} {events_filename} differs from raw-stream replay",
        )

    recorded_stderr_filename = stage_name("stderr.txt")
    recorded_stderr = _artifact_bytes(
        bundle_repo,
        run,
        filename=recorded_stderr_filename,
        artifact_type="stderr",
        phase=phase,
    )
    expected_stderr = (parsed["nonJsonStderr"] or stderr).encode()
    if recorded_stderr != expected_stderr:
        raise _fail(
            phase,
            f"run {run.index} {recorded_stderr_filename} differs from "
            "raw-stream replay",
        )

    trace_filename = stage_name("codex_trace.json")
    trace = _json_artifact(
        bundle_repo,
        run,
        filename=trace_filename,
        artifact_type="codex_trace",
        phase=phase,
    )
    if not isinstance(trace, dict):
        raise _fail(phase, f"run {run.index} {trace_filename} must be a JSON object")
    command_filename = stage_name("command.json")
    command = _json_artifact(
        bundle_repo,
        run,
        filename=command_filename,
        artifact_type="command",
        phase=phase,
    )
    if not isinstance(command, dict):
        raise _fail(phase, f"run {run.index} {command_filename} must be a JSON object")
    expected_trace = {
        "provider": "openai",
        "backend": "codex-exec",
        "auth": "codex-cli-subscription",
        "model": model,
        "searchEnabled": search,
        "sandbox": policy["codexSandbox"],
        "networkAccess": policy["codexNetwork"],
        "reasoningEffort": policy["codexReasoningEffort"],
        "timeoutSeconds": policy["timeoutSeconds"],
        "timedOut": command.get("timedOut"),
        "timeoutReason": command.get("timeoutReason"),
        "terminatedAfterOutput": command.get("terminatedAfterOutput"),
        "processReturnCode": command.get("processReturnCode"),
        "effectiveReturnCode": command.get("returnCode"),
        "usage": parsed["usage"],
        "eventCount": len(parsed["events"]),
        "lastError": parsed["lastError"],
    }
    for field, expected in expected_trace.items():
        if not canonical_equal(trace.get(field), expected):
            raise _fail(
                phase,
                f"run {run.index} {trace_filename} {field} does not match "
                "the ticket runner",
            )
    if "toolEvidence" in command:
        for suffix, artifact_type in (
            ("tool_evidence.json", "tool_evidence"),
            ("tool_evidence_verification.json", "tool_evidence_verification"),
        ):
            _json_artifact(
                bundle_repo,
                run,
                filename=stage_name(suffix),
                artifact_type=artifact_type,
                phase=phase,
            )
    try:
        verify_tool_evidence_stage(
            bundle_repo.joinpath(*run.run_relative.parts),
            [
                {
                    **entry,
                    "path": pathlib.PurePosixPath(entry["path"])
                    .relative_to(run.run_relative)
                    .as_posix(),
                }
                for entry in run.manifest["artifacts"]
            ],
            prefix=prefix,
            command=command,
            run_succeeded=run.manifest.get("ok") is True,
        )
    except (CustodyError, ValueError) as exc:
        raise _fail(phase, f"run {run.index} {exc}") from exc
    return CodexStageEvidence(
        last_message=last_message,
        stdout_events=tuple(stdout_parsed["events"]),
    )


def _check_prompts(
    state: TicketContext,
    bundle_repo: pathlib.Path,
    runs: list[RunEnvelope],
) -> dict[int, PromptEvidence]:
    policy = state.ticket["policy"]
    evidence: dict[int, PromptEvidence] = {}
    for run in runs:
        draft_command = _json_artifact(
            bundle_repo,
            run,
            filename="draft_command.json",
            artifact_type="command",
            phase="prompt reconstruction",
        )
        try:
            prompt, meta = build_run_prompt(
                run.target["series"],
                run.target["period"],
                run.target.get("conditional"),
                policy["promptMode"],
                run.target,
                ticket=state.prompt_context,
                network_tools=policy["codexNetwork"],
                tool_evidence=(
                    isinstance(draft_command, dict) and "toolEvidence" in draft_command
                ),
            )
        except (KeyError, TicketError, ValueError) as exc:
            raise _fail(
                "prompt reconstruction",
                f"run {run.index} prompt could not be rebuilt: {exc}",
            ) from exc
        expected = prompt.encode()
        raw = _artifact_bytes(
            bundle_repo,
            run,
            filename="prompt.md",
            artifact_type="prompt",
            phase="prompt reconstruction",
        )
        expected_hash = hashlib.sha256(expected).hexdigest()
        if hashlib.sha256(raw).hexdigest() != expected_hash or raw != expected:
            raise _fail(
                "prompt reconstruction",
                f"run {run.index} prompt bytes do not match trusted reconstruction",
            )
        runtime_meta = stamp_runtime_invocation(
            meta,
            {"argv": ["codex", "-m", policy["codexModel"]]},
        )
        if not canonical_equal(run.manifest.get("agent"), runtime_meta):
            raise _fail(
                "prompt reconstruction",
                f"run {run.index} agent metadata does not match trusted prompt "
                "metadata",
            )

        draft_stage = _replay_codex_stage(
            bundle_repo,
            run,
            prefix="draft_",
            stdout_artifact_type="draft_forecast",
            model=policy["codexModel"],
            search=True,
            policy=policy,
            phase="prompt reconstruction",
        )
        review_prompt = build_pre_submit_review_prompt(
            series=run.target["series"],
            period=run.target["period"],
            conditional=run.target.get("conditional"),
            target_context=run.target,
            original_prompt=prompt,
            draft_response=draft_stage.last_message,
        )
        recorded_review_prompt = _artifact_bytes(
            bundle_repo,
            run,
            filename="pre_submit_review_prompt.md",
            artifact_type="review_prompt",
            phase="prompt reconstruction",
        )
        if recorded_review_prompt != review_prompt.encode():
            raise _fail(
                "prompt reconstruction",
                f"run {run.index} pre-submit review prompt bytes do not match "
                "trusted reconstruction",
            )

        review_stage = _replay_codex_stage(
            bundle_repo,
            run,
            prefix="pre_submit_review_",
            stdout_artifact_type="pre_submit_review",
            model=policy["reviewCodexModel"],
            search=policy["reviewCodexSearch"],
            policy=policy,
            phase="prompt reconstruction",
        )
        revision_prompt = build_revision_prompt(
            original_prompt=prompt,
            draft_response=draft_stage.last_message,
            review_response=review_stage.last_message,
        )
        recorded_revision_prompt = _artifact_bytes(
            bundle_repo,
            run,
            filename="revision_prompt.md",
            artifact_type="revision_prompt",
            phase="prompt reconstruction",
        )
        if recorded_revision_prompt != revision_prompt.encode():
            raise _fail(
                "prompt reconstruction",
                f"run {run.index} revision prompt bytes do not match trusted "
                "reconstruction",
            )
        evidence[run.index] = PromptEvidence(
            runtime_meta=runtime_meta,
            original_prompt=prompt,
            draft_response=draft_stage.last_message,
            draft_events=draft_stage.stdout_events,
            review_response=review_stage.last_message,
        )
    return evidence


def _option_present(argv: list[str], option: str) -> bool:
    return any(value == option or value.startswith(f"{option}=") for value in argv)


def _consume(argv: list[str], index: int, expected: str, *, label: str) -> int:
    if index >= len(argv) or argv[index] != expected:
        actual = argv[index] if index < len(argv) else "<end>"
        raise ValueError(f"{label} expected {expected!r}, got {actual!r}")
    return index + 1


def _check_command_argv(
    argv: Any,
    *,
    run: RunEnvelope,
    filename: str,
    model: str,
    search: bool,
    policy: dict[str, Any],
    announcement_url: str | None,
    tool_evidence: bool = False,
) -> None:
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(value, str) for value in argv)
    ):
        raise _fail("command shape", f"run {run.index} {filename} argv is invalid")
    for option in FORBIDDEN_COMMAND_OPTIONS:
        if _option_present(argv, option):
            raise _fail(
                "command shape",
                f"run {run.index} {filename} contains forbidden option {option}",
            )
    if any(
        value in {"resume", "continue"}
        or value.startswith("--resume")
        or value.startswith("--continue")
        for value in argv
    ):
        raise _fail(
            "command shape",
            f"run {run.index} {filename} contains a forbidden resume-style argument",
        )
    if pathlib.PurePosixPath(argv[0]).name != "codex":
        raise _fail(
            "command shape",
            f"run {run.index} {filename} executable is not native codex: {argv[0]!r}",
        )

    try:
        index = 1
        if search:
            index = _consume(argv, index, "--search", label=filename)
        index = _consume(argv, index, "exec", label=filename)
        for token in (
            "--json",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "-o",
        ):
            index = _consume(argv, index, token, label=filename)
        if index >= len(argv):
            raise ValueError(f"{filename} lacks the -o path")
        output_path = pathlib.PurePosixPath(argv[index])
        index += 1
        index = _consume(argv, index, "-m", label=filename)
        index = _consume(argv, index, model, label=filename)
        index = _consume(argv, index, "-c", label=filename)
        index = _consume(
            argv,
            index,
            f'reasoning_effort="{policy["codexReasoningEffort"]}"',
            label=filename,
        )
        if policy["codexNetwork"]:
            index = _consume(argv, index, "-c", label=filename)
            index = _consume(
                argv,
                index,
                "sandbox_workspace_write.network_access=true",
                label=filename,
            )
        observed_evidence_config: list[str] = []
        if tool_evidence:
            config_count = len(
                tool_evidence_mcp_config(
                    pathlib.Path("/tmp/thesis-tool-evidence-check/tool_evidence.json"),
                    allow_fetch=search or policy["codexNetwork"],
                )
            )
            for _ in range(config_count):
                index = _consume(argv, index, "-c", label=filename)
                if index >= len(argv):
                    raise ValueError(
                        f"{filename} has an incomplete tool evidence MCP config"
                    )
                observed_evidence_config.append(argv[index])
                index += 1
        observed_mcp_config: list[str] = []
        if announcement_url is not None:
            for _ in range(len(announcement_mcp_config(announcement_url))):
                index = _consume(argv, index, "-c", label=filename)
                if index >= len(argv):
                    raise ValueError(f"{filename} has an incomplete MCP config")
                observed_mcp_config.append(argv[index])
                index += 1
        index = _consume(argv, index, "-C", label=filename)
        if index >= len(argv):
            raise ValueError(f"{filename} lacks the -C path")
        checkout_path = pathlib.PurePosixPath(argv[index])
        index += 1
        index = _consume(argv, index, "-s", label=filename)
        index = _consume(argv, index, policy["codexSandbox"], label=filename)
        index = _consume(argv, index, "<prompt>", label=filename)
        if index != len(argv):
            raise ValueError(f"{filename} has unexpected trailing argv: {argv[index:]}")

        if tool_evidence:
            command_prefix = f"mcp_servers.{TOOL_EVIDENCE_SERVER}.command="
            args_prefix = f"mcp_servers.{TOOL_EVIDENCE_SERVER}.args="
            if not observed_evidence_config[0].startswith(
                command_prefix
            ) or not observed_evidence_config[1].startswith(args_prefix):
                raise ValueError(f"{filename} tool evidence MCP config is invalid")
            try:
                mcp_python = json.loads(
                    observed_evidence_config[0][len(command_prefix) :]
                )
                mcp_args = json.loads(observed_evidence_config[1][len(args_prefix) :])
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{filename} tool evidence MCP config is invalid"
                ) from exc
            if not isinstance(mcp_python, str) or not isinstance(mcp_args, list):
                raise ValueError(f"{filename} tool evidence MCP config is invalid")
            python_path = pathlib.PurePosixPath(mcp_python)
            if (
                python_path.parent != checkout_path / ".venv" / "bin"
                or python_path.name not in {"python", "python3"}
            ):
                raise ValueError(
                    f"{filename} tool evidence MCP Python is not the checkout "
                    "virtual environment interpreter"
                )
            if len(mcp_args) < 3 or not isinstance(mcp_args[2], str):
                raise ValueError(f"{filename} tool evidence MCP output is invalid")
            spool = pathlib.PurePosixPath(mcp_args[2])
            if (
                not spool.is_absolute()
                or str(spool) != mcp_args[2]
                or ".." in spool.parts
                or spool.name != "tool_evidence.json"
                or not re.fullmatch(
                    r"thesis-tool-evidence-[A-Za-z0-9_-]+", spool.parent.name
                )
                or spool.is_relative_to(checkout_path)
            ):
                raise ValueError(
                    f"{filename} tool evidence MCP output is not an isolated spool"
                )
            expected_evidence_config = tool_evidence_mcp_config(
                spool,
                checkout_root=checkout_path,
                python_executable=mcp_python,
                allow_fetch=search or policy["codexNetwork"],
            )
            if observed_evidence_config != expected_evidence_config:
                raise ValueError(
                    f"{filename} tool evidence MCP config does not match "
                    "the trusted runner"
                )

        if announcement_url is not None:
            command_prefix = f"mcp_servers.{ANNOUNCEMENT_MCP_SERVER}.command="
            command_config = observed_mcp_config[0]
            if not command_config.startswith(command_prefix):
                raise ValueError(
                    f"{filename} announcement MCP command config is invalid"
                )
            try:
                mcp_python = json.loads(command_config[len(command_prefix) :])
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{filename} announcement MCP command config is invalid"
                ) from exc
            if not isinstance(mcp_python, str):
                raise ValueError(
                    f"{filename} announcement MCP command config is invalid"
                )
            python_path = pathlib.PurePosixPath(mcp_python)
            expected_python_parent = checkout_path / ".venv" / "bin"
            if python_path.parent != expected_python_parent or python_path.name not in {
                "python",
                "python3",
            }:
                raise ValueError(
                    f"{filename} announcement MCP Python is not the checkout "
                    "virtual environment interpreter"
                )
            expected_mcp_config = announcement_mcp_config(
                announcement_url,
                checkout_root=checkout_path,
                python_executable=mcp_python,
            )
            if observed_mcp_config != expected_mcp_config:
                raise ValueError(
                    f"{filename} announcement MCP config does not match the "
                    "authenticated target"
                )
    except ValueError as exc:
        raise _fail("command shape", f"run {run.index} {exc}") from exc

    expected_last = filename.removesuffix("command.json") + "codex_last_message.txt"
    expected_output = checkout_path.joinpath(*run.run_relative.parts, expected_last)
    if output_path != expected_output:
        raise _fail(
            "command shape",
            f"run {run.index} {filename} -o path does not target its run: "
            f"{output_path} != {expected_output}",
        )


def _check_commands(
    state: TicketContext,
    bundle_repo: pathlib.Path,
    runs: list[RunEnvelope],
) -> None:
    policy = state.ticket["policy"]
    expected_ticket = {
        "ticketId": state.ticket["ticketId"],
        "ticketPath": state.relative.as_posix(),
    }
    stages = (
        ("draft_command.json", policy["codexModel"], True, True),
        (
            "pre_submit_review_command.json",
            policy["reviewCodexModel"],
            policy["reviewCodexSearch"],
            False,
        ),
        ("command.json", policy["codexModel"], True, True),
    )
    for run in runs:
        minted = _parse_utc(
            state.ticket["mintedAtUtc"],
            phase="command shape",
            label="ticket mintedAtUtc",
        )
        sealed = _parse_utc(
            run.manifest.get("sealedAt"),
            phase="command shape",
            label=f"run {run.index} sealedAt",
        )
        result_started = _parse_utc(
            run.result.get("startedAt"),
            phase="command shape",
            label=f"run {run.index} batch result startedAt",
        )
        result_finished = _parse_utc(
            run.result.get("finishedAt"),
            phase="command shape",
            label=f"run {run.index} batch result finishedAt",
        )
        review = run.manifest.get("preSubmitReview")
        if not isinstance(review, dict) or review.get("status") != "completed":
            raise _fail(
                "command shape",
                f"run {run.index} does not contain a completed ticket review",
            )
        artifacts = run.manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise _fail("command shape", f"run {run.index} has no artifact inventory")
        actual_commands = sorted(
            str(artifact.get("path"))
            for artifact in artifacts
            if artifact.get("artifactType") == "command"
        )
        expected_commands = sorted(
            (run.run_relative / filename).as_posix()
            for filename, _model, _search, _fetch in stages
        )
        if actual_commands != expected_commands:
            raise _fail(
                "command shape",
                f"run {run.index} command artifact inventory differs from the "
                f"ticket runner: {actual_commands} != {expected_commands}",
            )
        stage_times: dict[str, tuple[dt.datetime, dt.datetime, Any, Any]] = {}
        evidence_modes: set[bool] = set()
        binding = run.target.get("sourceBinding")
        target_announcement_url = (
            binding.get("sourceUrl")
            if run.target.get("resolutionDateBasis", "release-calendar")
            == "resolve-by-bound"
            and isinstance(binding, dict)
            else None
        )
        for filename, model, search, fetch_announcement in stages:
            command = _json_artifact(
                bundle_repo,
                run,
                filename=filename,
                artifact_type="command",
                phase="command shape",
            )
            if not isinstance(command, dict):
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} must be a JSON object",
                )
            started = _parse_utc(
                command.get("startedAt"),
                phase="command shape",
                label=f"run {run.index} {filename} startedAt",
            )
            finished = _parse_utc(
                command.get("finishedAt"),
                phase="command shape",
                label=f"run {run.index} {filename} finishedAt",
            )
            stage_times[filename] = (
                started,
                finished,
                command.get("startedAt"),
                command.get("finishedAt"),
            )
            if command.get("backend") != "codex":
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} backend is not native codex",
                )
            evidence_modes.add("toolEvidence" in command)
            if not canonical_equal(command.get("generationTicket"), expected_ticket):
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} ticket binding does not match",
                )
            if not canonical_equal(
                command.get("networkAccess"), policy["codexNetwork"]
            ):
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} networkAccess does not match policy",
                )
            if (
                type(command.get("timeoutSeconds")) is not int
                or command["timeoutSeconds"] != policy["timeoutSeconds"]
            ):
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} timeoutSeconds does not match policy",
                )
            if type(command.get("returnCode")) is not int or command["returnCode"] != 0:
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} did not complete successfully",
                )
            timed_out = command.get("timedOut")
            terminated_after_output = command.get("terminatedAfterOutput")
            process_return_code = command.get("processReturnCode")
            if type(timed_out) is not bool:
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} timedOut must be a boolean",
                )
            if type(terminated_after_output) is not bool:
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} terminatedAfterOutput must be a "
                    "boolean",
                )
            if type(process_return_code) is not int:
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} processReturnCode must be an integer",
                )
            timeout_reason = command.get("timeoutReason")
            if timed_out and timeout_reason not in {"idle", "wall"}:
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} timeoutReason is invalid",
                )
            if not timed_out and timeout_reason is not None:
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} records a timeout reason without "
                    "a timeout",
                )
            if timed_out and terminated_after_output:
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} cannot be both timed out and "
                    "terminated after output",
                )
            if timed_out and process_return_code == 0:
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} timeout lacks a terminated process",
                )
            if (
                process_return_code != 0
                and not timed_out
                and not terminated_after_output
            ):
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} effective success is inconsistent "
                    "with its process return code",
                )
            if policy["codexSandbox"] == "read-only":
                if "workspaceMutations" in command:
                    raise _fail(
                        "command shape",
                        f"run {run.index} {filename} records unexpected workspace "
                        "guard output for the read-only sandbox",
                    )
            elif command.get("workspaceMutations") != []:
                raise _fail(
                    "command shape",
                    f"run {run.index} {filename} does not prove a clean guarded "
                    "workspace",
                )
            _check_command_argv(
                command.get("argv"),
                run=run,
                filename=filename,
                model=model,
                search=search,
                policy=policy,
                announcement_url=(
                    target_announcement_url if fetch_announcement else None
                ),
                tool_evidence="toolEvidence" in command,
            )
        if len(evidence_modes) != 1:
            raise _fail(
                "command shape",
                f"run {run.index} tool evidence capture was downgraded between stages",
            )
        draft_started, draft_finished, draft_started_raw, draft_finished_raw = (
            stage_times["draft_command.json"]
        )
        review_started, review_finished, review_started_raw, review_finished_raw = (
            stage_times["pre_submit_review_command.json"]
        )
        final_started, final_finished, final_started_raw, final_finished_raw = (
            stage_times["command.json"]
        )
        if draft_started < minted:
            raise _fail(
                "command shape",
                f"run {run.index} draft_command.json startedAt predates ticket "
                f"mint: {draft_started_raw} < {state.ticket['mintedAtUtc']}",
            )
        if draft_finished < draft_started:
            raise _fail(
                "command shape",
                f"run {run.index} draft_command.json finishedAt predates its "
                f"startedAt: {draft_finished_raw} < {draft_started_raw}",
            )
        if review_started < draft_finished:
            raise _fail(
                "command shape",
                f"run {run.index} pre_submit_review_command.json startedAt "
                f"predates draft_command.json finishedAt: {review_started_raw} < "
                f"{draft_finished_raw}",
            )
        if review_finished < review_started:
            raise _fail(
                "command shape",
                f"run {run.index} pre_submit_review_command.json finishedAt "
                f"predates its startedAt: {review_finished_raw} < "
                f"{review_started_raw}",
            )
        if final_started < review_finished:
            raise _fail(
                "command shape",
                f"run {run.index} command.json startedAt predates "
                f"pre_submit_review_command.json finishedAt: {final_started_raw} "
                f"< {review_finished_raw}",
            )
        if final_finished < final_started:
            raise _fail(
                "command shape",
                f"run {run.index} command.json finishedAt predates its startedAt: "
                f"{final_finished_raw} < {final_started_raw}",
            )
        if final_finished > sealed:
            raise _fail(
                "command shape",
                f"run {run.index} command.json finishedAt postdates run sealedAt: "
                f"{final_finished_raw} > {run.manifest.get('sealedAt')}",
            )
        if draft_started < result_started:
            raise _fail(
                "command shape",
                f"run {run.index} draft_command.json startedAt predates batch "
                f"result startedAt: {draft_started_raw} < "
                f"{run.result.get('startedAt')}",
            )
        if final_finished > result_finished:
            raise _fail(
                "command shape",
                f"run {run.index} command.json finishedAt postdates batch result "
                f"finishedAt: {final_finished_raw} > "
                f"{run.result.get('finishedAt')}",
            )
        expected_hygiene = (
            {"guarded": True, "mutations": []}
            if policy["codexSandbox"] != "read-only"
            else None
        )
        if not canonical_equal(run.manifest.get("workspaceHygiene"), expected_hygiene):
            raise _fail(
                "command shape",
                f"run {run.index} workspace hygiene does not match the ticket sandbox",
            )


def _stage_has_authenticated_announcement_fetch(
    events: tuple[dict[str, Any], ...],
    *,
    announcement_url: str,
) -> bool:
    final_message_index = max(
        (
            index
            for index, event in enumerate(events)
            if event.get("type") == "item.completed"
            and isinstance(event.get("item"), dict)
            and event["item"].get("type") == "agent_message"
        ),
        default=-1,
    )
    if final_message_index < 0:
        return False
    for event in events[:final_message_index]:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or (
            item.get("type") != "mcp_tool_call"
            or item.get("server") != ANNOUNCEMENT_MCP_SERVER
            or item.get("tool") != ANNOUNCEMENT_MCP_TOOL
            or item.get("status") != "completed"
            or item.get("error") not in (None, "")
        ):
            continue
        if not canonical_equal(item.get("arguments"), {"url": announcement_url}):
            continue
        result = item.get("result")
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("content"), list)
            or result.get("is_error") is True
        ):
            continue
        structured = result.get("structured_content")
        if not isinstance(structured, dict):
            continue
        status = structured.get("statusCode")
        if (
            structured.get("requestedUrl") != announcement_url
            or structured.get("finalUrl") != announcement_url
            or type(status) is not int
            or not 200 <= status < 300
            or not isinstance(structured.get("responseSha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", structured["responseSha256"]) is None
        ):
            continue
        return True
    return False


def _check_bounded_announcement_fetch(
    run: RunEnvelope,
    *,
    draft_events: tuple[dict[str, Any], ...],
    final_events: tuple[dict[str, Any], ...],
) -> None:
    if run.target.get("resolutionDateBasis", "release-calendar") != "resolve-by-bound":
        return
    binding = run.target.get("sourceBinding")
    announcement_url = binding.get("sourceUrl") if isinstance(binding, dict) else None
    if not isinstance(announcement_url, str) or not announcement_url:
        raise _fail(
            "derivation replay",
            f"run {run.index} resolve-by-bound target lacks an authenticated "
            "announcement URL",
        )
    if any(
        _stage_has_authenticated_announcement_fetch(
            events,
            announcement_url=announcement_url,
        )
        for events in (draft_events, final_events)
    ):
        return
    raise _fail(
        "derivation replay",
        f"run {run.index} resolve-by-bound target lacks a successful "
        f"authenticated announcement fetch for {announcement_url!r} in "
        "draft/final Codex stdout",
    )


def _check_replay(
    state: TicketContext,
    bundle_repo: pathlib.Path,
    batch: dict[str, Any],
    runs: list[RunEnvelope],
    prompt_evidence: dict[int, PromptEvidence],
) -> None:
    policy = state.ticket["policy"]
    trusted_checkout = state.path
    for _part in state.relative.parts:
        trusted_checkout = trusted_checkout.parent
    replayed_validations: list[dict[str, Any]] = []
    for run in runs:
        evidence = prompt_evidence[run.index]
        final_stage = _replay_codex_stage(
            bundle_repo,
            run,
            prefix="",
            stdout_artifact_type="stdout",
            model=policy["codexModel"],
            search=True,
            policy=policy,
            phase="derivation replay",
        )
        _check_bounded_announcement_fetch(
            run,
            draft_events=evidence.draft_events,
            final_events=final_stage.stdout_events,
        )
        last_message = final_stage.last_message
        last_message_raw = _artifact_bytes(
            bundle_repo,
            run,
            filename="codex_last_message.txt",
            artifact_type="codex_last_message",
            phase="derivation replay",
        )
        raw_response = _artifact_bytes(
            bundle_repo,
            run,
            filename="raw_response.txt",
            artifact_type="raw_response",
            phase="derivation replay",
        )
        if raw_response != last_message_raw:
            raise _fail(
                "derivation replay",
                f"run {run.index} raw_response.txt differs from the last message",
            )

        try:
            replayed_parsed = extract_json_payload(last_message)
        except ValueError as exc:
            raise _fail(
                "derivation replay",
                f"run {run.index} last message has no forecast JSON: {exc}",
            ) from exc
        recorded_parsed = _json_artifact(
            bundle_repo,
            run,
            filename="parsed_cells.json",
            artifact_type="parsed_cell",
            phase="derivation replay",
        )
        if not canonical_equal(replayed_parsed, recorded_parsed):
            raise _fail(
                "derivation replay",
                f"run {run.index} parsed cells differ from raw-stream replay",
            )

        with tempfile.TemporaryDirectory(prefix="thesis-attested-replay-") as temp:
            temp_root = pathlib.Path(temp)
            parsed_path = temp_root / "parsed_cells.json"
            normalized_path = temp_root / "normalized_cells.json"
            parsed_path.write_text(json.dumps(replayed_parsed, indent=2))
            try:
                normalize_cells(parsed_path, normalized_path)
                replayed_normalized = json.loads(normalized_path.read_text())
            except (OSError, RuntimeError, json.JSONDecodeError) as exc:
                raise _fail(
                    "derivation replay",
                    f"run {run.index} normalization replay failed: {exc}",
                ) from exc
        if not isinstance(replayed_normalized, list) or not all(
            isinstance(cell, dict) for cell in replayed_normalized
        ):
            raise _fail(
                "derivation replay",
                f"run {run.index} normalization did not produce an object list",
            )
        run_started_at = run.manifest.get("runStartedAt")
        sealed_at = run.manifest.get("sealedAt")
        if not isinstance(run_started_at, str) or not isinstance(sealed_at, str):
            raise _fail(
                "derivation replay",
                f"run {run.index} manifest lacks runStartedAt or sealedAt",
            )
        replayed_distribution = seal_normalized_cells(
            replayed_normalized,
            conditional=run.target.get("conditional"),
            run_started_at=run_started_at,
            sealed_at=sealed_at,
            prompt_mode=policy["promptMode"],
            target_context=run.target,
        )
        recorded_normalized = _json_artifact(
            bundle_repo,
            run,
            filename="normalized_cells.json",
            artifact_type="normalized_cell",
            phase="derivation replay",
        )
        if not canonical_equal(replayed_normalized, recorded_normalized):
            raise _fail(
                "derivation replay",
                f"run {run.index} normalized cells differ from replay",
            )
        recorded_distribution = _json_artifact(
            bundle_repo,
            run,
            filename="distribution.json",
            artifact_type="run_distribution",
            phase="derivation replay",
        )
        if not canonical_equal(replayed_distribution, recorded_distribution):
            raise _fail(
                "derivation replay",
                f"run {run.index} distribution differs from replay",
            )
        replayed_validation = validate_cells(
            replayed_normalized,
            True,
            run.target,
            policy["promptMode"],
            generation_ticket=state.manifest_binding,
            agent_version=evidence.runtime_meta.get("agentVersion"),
            checkout_sha=run.manifest.get("checkoutSha"),
            series=run.manifest.get("series"),
            target_period=run.manifest.get("period"),
            history_registry_root=trusted_checkout,
        )
        recorded_validation = _json_artifact(
            bundle_repo,
            run,
            filename="validation.json",
            artifact_type="validation_report",
            phase="derivation replay",
        )
        if not canonical_equal(replayed_validation, recorded_validation):
            raise _fail(
                "derivation replay",
                f"run {run.index} validation.json differs from replayed "
                "validation report",
            )
        if not canonical_equal(run.manifest.get("validation"), replayed_validation):
            raise _fail(
                "derivation replay",
                f"run {run.index} manifest validation differs from replayed "
                "validation report",
            )
        replayed_validations.append(replayed_validation)
        if not canonical_equal(run.result.get("ok"), replayed_validation["ok"]):
            raise _fail(
                "derivation replay",
                f"run {run.index} batch result ok differs from replayed "
                "validation report",
            )
        replayed_errors = [
            error for cell in replayed_validation["cells"] for error in cell["errors"]
        ]
        if not canonical_equal(run.result.get("validationErrors"), replayed_errors):
            raise _fail(
                "derivation replay",
                f"run {run.index} batch result validationErrors differs from "
                "replayed validation report",
            )
        review_command = _json_artifact(
            bundle_repo,
            run,
            filename="pre_submit_review_command.json",
            artifact_type="command",
            phase="derivation replay",
        )
        if not isinstance(review_command, dict):
            raise _fail(
                "derivation replay",
                f"run {run.index} reviewer command must be a JSON object",
            )
        review_metadata = build_pre_submit_review_metadata(
            status="completed",
            requested_at=run_started_at,
            review_result=review_command,
            review_payload=parse_review_payload(evidence.review_response),
            draft_ref=_artifact_ref(
                run,
                filename="draft_stdout.txt",
                artifact_type="draft_forecast",
                phase="derivation replay",
            ),
            review_ref=_artifact_ref(
                run,
                filename="pre_submit_review_stdout.txt",
                artifact_type="pre_submit_review",
                phase="derivation replay",
            ),
            revision_prompt_ref=_artifact_ref(
                run,
                filename="revision_prompt.md",
                artifact_type="revision_prompt",
                phase="derivation replay",
            ),
            normalized_cells=replayed_normalized,
        )
        if not canonical_equal(run.manifest.get("preSubmitReview"), review_metadata):
            raise _fail(
                "derivation replay",
                f"run {run.index} preSubmitReview metadata differs from replay",
            )
        artifacts = run.manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise _fail(
                "derivation replay",
                f"run {run.index} manifest lacks an artifact inventory",
            )
        activity_refs = [
            artifact
            for artifact in artifacts
            if artifact.get("artifactType") not in {"cells_with_activity", "manifest"}
        ]
        expected_cells = attach_activity_log(
            replayed_normalized,
            activity_refs,
            evidence.runtime_meta,
            review_metadata,
            force_model=True,
        )
        recorded_cells = _json_artifact(
            bundle_repo,
            run,
            filename="cells.with_activity.json",
            artifact_type="cells_with_activity",
            phase="derivation replay",
        )
        if not isinstance(recorded_cells, list) or not all(
            isinstance(cell, dict) for cell in recorded_cells
        ):
            raise _fail(
                "derivation replay",
                f"run {run.index} published cells must be an object list",
            )
        for cell_index, cell in enumerate(recorded_cells):
            if cell.get("model") != policy["codexModel"]:
                raise _fail(
                    "derivation replay",
                    f"run {run.index} published cell {cell_index} model does not "
                    "match the ticket",
                )
        if not canonical_equal(expected_cells, recorded_cells):
            raise _fail(
                "derivation replay",
                f"run {run.index} published cells differ from replayed cells",
            )

    replayed_aggregates = {
        "targets": len(replayed_validations),
        "ok": sum(1 for report in replayed_validations if report["ok"]),
        "failed": sum(1 for report in replayed_validations if not report["ok"]),
    }
    for field, expected in replayed_aggregates.items():
        if not canonical_equal(batch.get(field), expected):
            raise _fail(
                "derivation replay",
                f"batch {field} differs from replayed validation reports",
            )


def verify_attested_bundle(
    ticket_path: str | pathlib.Path,
    bundle_dir: str | pathlib.Path,
    *,
    repo_root: str | pathlib.Path,
    now_utc: dt.datetime,
) -> None:
    """Verify ticket-bound assembly and replay, not execution provenance."""

    with _phase_guard("ticket"):
        checkout = pathlib.Path(repo_root).resolve()
        state = _load_ticket_context(
            ticket_path,
            repo_root=checkout,
            now_utc=now_utc,
        )
    print(f"passed ticket check: {state.ticket['ticketId']}")

    with _phase_guard("bundle"):
        bundle = pathlib.Path(bundle_dir).resolve()
        batch_relative, preliminary_batch = _load_declared_batch(bundle, state.ticket)
        with tempfile.TemporaryDirectory(prefix="thesis-attested-targets-") as temp:
            trusted_targets = pathlib.Path(temp) / "trusted-targets.json"
            trusted_targets.write_text(
                json.dumps({"targets": state.ticket["targets"]}, indent=2) + "\n"
            )
            try:
                bundle_repo, _ = load_bundle(
                    bundle,
                    batch_relative.as_posix(),
                    str(trusted_targets),
                    repo_root=checkout,
                )
            except PublicationError as exc:
                raise _fail("bundle", str(exc)) from exc
        try:
            batch = load_json(
                safe_join(bundle_repo, batch_relative), "validated batch manifest"
            )
        except PublicationError as exc:
            raise _fail("bundle", str(exc)) from exc
        if not isinstance(batch, dict) or not canonical_equal(batch, preliminary_batch):
            raise _fail("bundle", "batch manifest changed while the bundle was loaded")
        runs = _load_runs(bundle_repo, batch, state.ticket)
    print(f"passed bundle check: {batch_relative}")

    with _phase_guard("policy"):
        _check_policy(batch, state.ticket, runs)
    print(f"passed policy check: {state.ticket['ticketId']}")

    with _phase_guard("binding"):
        introducing = _check_bindings(state, batch, runs, repo_root=checkout)
    print(f"passed binding check: {introducing}")

    with _phase_guard("prompt reconstruction"):
        prompt_evidence = _check_prompts(state, bundle_repo, runs)
    print(f"passed prompt reconstruction check: {len(runs)} run(s)")

    with _phase_guard("command shape"):
        _check_commands(state, bundle_repo, runs)
    print(f"passed command shape check: {len(runs)} run(s)")

    with _phase_guard("derivation replay"):
        _check_replay(state, bundle_repo, batch, runs, prompt_evidence)
    print(f"passed derivation replay check: {len(runs)} run(s)")


def _cli_now(value: str | None) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    return _parse_utc(value, phase="ticket", label="--now-utc")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--ticket-path", required=True)
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--now-utc")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        now = _cli_now(args.now_utc)
        verify_attested_bundle(
            args.ticket_path,
            args.bundle_dir,
            repo_root=args.repo_root,
            now_utc=now,
        )
    except AttestedBundleError as exc:
        print(f"ATTESTED BUNDLE BLOCKED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
