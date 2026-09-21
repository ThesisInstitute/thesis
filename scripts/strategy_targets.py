#!/usr/bin/env python3
"""Select and verify already-published targets for strategy comparisons.

The selector is trusted workflow code.  It admits only catalog targets whose
canonical one-target registration was introduced by an ancestor of the
selected source commit and whose generated ledger entry is already published.
Registrations are v3, or v2 introduced strictly before the v3 cutover commit
(trusted history can no longer mint v2 snapshots).  It also binds two
resolution-absence checks: the latest verified local record chain snapshot
and a pinned PolicyEngine ledger blob.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Any

from canonical_json import canonical_bytes, canonical_sha256
from generate_ledger_targets import (
    block_value,
    generated_entry_blocks,
    generated_entry_for,
)
from register_targets import (
    REGISTRATION_SCHEMA,
    V2_REGISTRATION_SCHEMA,
    V3_REGISTRATION_CUTOVER_COMMIT,
    RegistrationError,
    parse_utc_instant,
    registration_content_hash,
    validate_target_resolution_projection,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
GENERATED_TARGETS_RELATIVE = pathlib.PurePosixPath(
    "site/src/data/ledger-targets.generated.ts"
)
CHAIN_HEAD_RELATIVE = pathlib.PurePosixPath("records/CHAIN_HEAD.json")
SELECTION_SCHEMA = "thesis_strategy_selection_v1"
SUITES = {"ladder", "median3", "both"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
REGISTRATION_RE = re.compile(
    r"^records/targets/\d{4}-\d{2}-\d{2}-[0-9a-f]{64}\.json$"
)
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_ARTIFACT_LAG = dt.timedelta(minutes=15)
MAX_REGISTRATION_COMMIT_LAG = dt.timedelta(minutes=15)


class StrategyTargetError(ValueError):
    """A requested comparison target or its witness failed closed."""


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_utc(value: Any, label: str) -> dt.datetime:
    text = str(value)
    if not UTC_RE.fullmatch(text):
        raise StrategyTargetError(
            f"{label} must be a second-precision UTC instant: {text!r}"
        )
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StrategyTargetError(f"invalid {label}: {text!r}") from exc
    if parsed.utcoffset() != dt.timedelta(0):
        raise StrategyTargetError(f"{label} is not UTC: {text!r}")
    return parsed


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_object(path: pathlib.Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StrategyTargetError(f"invalid {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StrategyTargetError(f"{label} must be a JSON object: {path}")
    return value


def git_output(root: pathlib.Path, *args: str, binary: bool = False) -> str | bytes:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=root,
            text=not binary,
            stderr=subprocess.PIPE,
        ).strip()
    except subprocess.CalledProcessError as exc:
        detail = (
            exc.stderr.decode(errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        ).strip()
        raise StrategyTargetError(
            f"git {' '.join(args)} failed" + (f": {detail}" if detail else "")
        ) from exc


def resolve_commit(root: pathlib.Path, head: str) -> str:
    commit = str(git_output(root, "rev-parse", f"{head}^{{commit}}"))
    if not COMMIT_RE.fullmatch(commit):
        raise StrategyTargetError(f"invalid source commit: {commit!r}")
    return commit


def repo_path(root: pathlib.Path, value: str) -> pathlib.Path:
    logical = pathlib.PurePosixPath(value)
    if logical.is_absolute() or ".." in logical.parts or "\\" in value:
        raise StrategyTargetError(f"unsafe repository path: {value!r}")
    path = root.joinpath(*logical.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise StrategyTargetError(
            f"repository path escapes checkout: {value!r}"
        ) from exc
    return path


def known_catalog_slugs(generated_source: str) -> set[str]:
    return {
        str(slug)
        for match in generated_entry_blocks(generated_source)
        if (slug := block_value(match.group(0), "catalogSlug"))
    }


def require_pre_cutover_commit(root: pathlib.Path, commit: str) -> None:
    """A v2 registration must have been introduced strictly before the v3
    cutover; trusted history cannot mint v2 snapshots after it."""

    cutover = V3_REGISTRATION_CUTOVER_COMMIT
    probe = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, cutover],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if commit == cutover or probe.returncode != 0:
        raise StrategyTargetError(
            "v2 registration does not strictly predate the v3 cutover"
        )


def registrations_by_slug(root: pathlib.Path) -> dict[str, list[dict[str, Any]]]:
    registrations: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((root / "records" / "targets").glob("*.json")):
        snapshot = load_object(path, "target registration")
        if snapshot.get("schemaVersion") not in {
            REGISTRATION_SCHEMA,
            V2_REGISTRATION_SCHEMA,
        }:
            continue
        if path.read_bytes() != canonical_bytes(snapshot) + b"\n":
            raise StrategyTargetError(f"registration is not canonical: {path}")
        contracts = snapshot.get("targets")
        if not isinstance(contracts, list) or len(contracts) != 1:
            raise StrategyTargetError(
                f"comparison registration must contain one target: {path}"
            )
        contract = contracts[0]
        if not isinstance(contract, dict) or not contract.get("catalogSlug"):
            raise StrategyTargetError(f"registration lacks a catalog slug: {path}")
        content_hash = registration_content_hash(snapshot)
        relative = path.relative_to(root).as_posix()
        if not REGISTRATION_RE.fullmatch(relative) or not path.name.endswith(
            f"-{content_hash}.json"
        ):
            raise StrategyTargetError(f"registration path/hash mismatch: {relative}")
        parse_utc_instant(str(snapshot.get("registeredAtUtc") or ""))
        registrations.setdefault(str(contract["catalogSlug"]), []).append(
            {
                "path": path,
                "relative": relative,
                "snapshot": snapshot,
                "contract": contract,
                "targetContentHash": content_hash,
            }
        )
    return registrations


def introducing_commit(
    root: pathlib.Path,
    registration: dict[str, Any],
    head: str,
    *,
    selection_started_at: dt.datetime,
) -> str:
    relative = str(registration["relative"])
    commits = str(
        git_output(
            root,
            "log",
            head,
            "--diff-filter=A",
            "--format=%H",
            "--",
            relative,
        )
    ).splitlines()
    if len(commits) != 1 or not COMMIT_RE.fullmatch(commits[0]):
        raise StrategyTargetError(
            f"expected one introducing commit for {relative}, found {len(commits)}"
        )
    commit = commits[0]
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, head],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if ancestor.returncode != 0:
        raise StrategyTargetError(
            f"registration introducing commit is not an ancestor: {commit}"
        )
    status = str(
        git_output(
            root,
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-status",
            "-r",
            commit,
            "--",
            relative,
        )
    ).splitlines()
    if status != [f"A\t{relative}"]:
        raise StrategyTargetError(
            f"registration commit did not add exactly {relative}: {status}"
        )
    committed = git_output(root, "show", f"{commit}:{relative}", binary=True)
    # check_output(...).strip() is inappropriate for canonical file bytes, so
    # fetch the exact blob a second time without trimming.
    committed = subprocess.check_output(
        ["git", "show", f"{commit}:{relative}"], cwd=root, stderr=subprocess.PIPE
    )
    if committed != registration["path"].read_bytes():
        raise StrategyTargetError(
            f"introducing commit bytes differ from checkout: {relative}"
        )

    timestamps = str(
        git_output(root, "show", "-s", "--format=%aI%n%cI", commit)
    ).splitlines()
    if len(timestamps) != 2:
        raise StrategyTargetError(
            f"could not read registration commit timestamps: {commit}"
    )
    registered_at = parse_utc(
        registration["snapshot"].get("registeredAtUtc"), "registeredAtUtc"
    )
    for label, value in zip(("author", "committer"), timestamps):
        try:
            commit_time = dt.datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise StrategyTargetError(
                f"invalid registration commit {label} timestamp: {value!r}"
            ) from exc
        if commit_time.tzinfo is None or commit_time.utcoffset() is None:
            raise StrategyTargetError(
                f"registration commit {label} timestamp lacks an offset: {value!r}"
            )
        commit_time = commit_time.astimezone(dt.timezone.utc)
        lag = commit_time - registered_at
        if lag < dt.timedelta(0) or lag > MAX_REGISTRATION_COMMIT_LAG:
            raise StrategyTargetError(
                "registeredAtUtc is not contemporaneous with the privileged "
                f"commit {label} time: lag={lag}"
            )
        if commit_time >= selection_started_at:
            raise StrategyTargetError(
                "registration commit does not strictly predate strategy "
                f"selection: {commit}"
            )
    return commit


def published_target(
    root: pathlib.Path,
    slug: str,
    registrations: dict[str, list[dict[str, Any]]],
    generated_source: str,
    head: str,
    selection_started_at: dt.datetime,
) -> dict[str, Any]:
    candidates = registrations.get(slug, [])
    if len(candidates) != 1:
        raise StrategyTargetError(
            f"target is not backed by one unique published registration: {slug}"
        )
    registration = candidates[0]
    contract = registration["contract"]
    match = generated_entry_for(generated_source, str(contract["dataPointId"]))
    if match is None:
        raise StrategyTargetError(
            f"published target has no generated ledger entry: {slug}"
        )
    block = match.group(0)
    if block_value(block, "registrationState") != "published":
        raise StrategyTargetError(f"target is not published: {slug}")
    if contract.get("conditional") is not None:
        # Strategy suites elicit unconditional forecasts; selecting a
        # conditional arm would run a prompt without its registered
        # legal-state premise and the publisher would rightly reject the
        # batch afterwards. Refuse at selection time instead.
        raise StrategyTargetError(
            f"conditional targets are not selectable for strategy "
            f"comparisons: {slug}"
        )
    expected_registration = {
        "dataPointId": contract["dataPointId"],
        "unit": contract["unit"],
        "registeredAt": registration["snapshot"]["registeredAtUtc"],
        "targetContentHash": registration["targetContentHash"],
        "series": contract["series"],
        "period": contract["period"],
        "catalogSlug": contract["catalogSlug"],
        "country": contract["country"],
        "valueScale": contract["valueScale"],
        "sourceBinding": contract["sourceBinding"],
    }
    if "resolutionDateBasis" in contract:
        expected_registration["resolutionDateBasis"] = contract[
            "resolutionDateBasis"
        ]
    for key, expected in expected_registration.items():
        if canonical_bytes(block_value(block, key)) != canonical_bytes(expected):
            raise StrategyTargetError(
                f"published ledger entry differs from registration for {slug}: {key}"
            )
    commit = introducing_commit(
        root,
        registration,
        head,
        selection_started_at=selection_started_at,
    )
    if registration["snapshot"].get("schemaVersion") == V2_REGISTRATION_SCHEMA:
        require_pre_cutover_commit(root, commit)
    required_block_fields = (
        "country",
        "resolutionDate",
        "resolutionSource",
        "resolutionSourceUrl",
        "resolutionRule",
        "resolutionPolicy",
    )
    missing = [
        key
        for key in required_block_fields
        if block_value(block, key) in (None, "")
    ]
    if missing:
        raise StrategyTargetError(
            f"published target lacks final resolver fields for {slug}: {missing}"
        )
    published_date = block_value(block, "resolutionDate")
    target = {
        "series": contract["series"],
        "period": contract["period"],
        "catalogSlug": slug,
        "country": block_value(block, "country"),
        "dataPointId": contract["dataPointId"],
        "targetUnit": contract["unit"],
        "valueScale": contract["valueScale"],
        "sourceBinding": contract["sourceBinding"],
        # The published forecast's resolver date. Comparison cells are graded
        # against it, and selection orders and gates open targets by it. It
        # is deliberately NOT stored as `resolutionDate`: the publisher
        # requires a batch target to carry the registered contract's date
        # fields with exactly the snapshot's presence and value, and a
        # release-calendar contract omits resolutionDate. Copying the
        # published date into `resolutionDate` is what blocked the
        # 2026-09-20 strategy runs (35524670779, 35525381224).
        "publishedResolutionDate": published_date,
        "resolutionSource": block_value(block, "resolutionSource"),
        "resolutionSourceUrl": block_value(block, "resolutionSourceUrl"),
        "resolutionRule": block_value(block, "resolutionRule"),
        "resolutionPolicy": block_value(block, "resolutionPolicy"),
        "registeredAtUtc": registration["snapshot"]["registeredAtUtc"],
        "targetContentHash": registration["targetContentHash"],
        "targetRegistrationPath": registration["relative"],
        "registrationCommit": commit,
        "comparisonTarget": True,
    }
    # Project the registered contract's date-basis semantics exactly as the
    # docket lane's target context does (register_targets
    # ._target_registration_fields): resolutionDateBasis, resolutionDate and
    # the top-level expectedReleaseWindow appear iff the snapshot binds them.
    if "resolutionDateBasis" in contract:
        target["resolutionDateBasis"] = contract["resolutionDateBasis"]
    if "resolutionDate" in contract:
        if published_date != contract["resolutionDate"]:
            raise StrategyTargetError(
                f"published ledger entry differs from registration for {slug}: "
                "resolutionDate"
            )
        target["resolutionDate"] = contract["resolutionDate"]
    binding = contract.get("sourceBinding")
    if isinstance(binding, dict) and "expectedReleaseWindow" in binding:
        target["expectedReleaseWindow"] = binding["expectedReleaseWindow"]
    # Fail at selection time with the publisher's own projection check, so a
    # target the publisher would reject never reaches the paid generate job.
    try:
        validate_target_resolution_projection(
            contract, target, label=registration["relative"]
        )
    except RegistrationError as exc:
        raise StrategyTargetError(str(exc)) from exc
    return target


def published_resolution_date(target: dict[str, Any]) -> dt.date:
    """The published forecast's resolver date that orders and gates a target."""

    value = target.get("publishedResolutionDate")
    if not isinstance(value, str) or not value:
        raise StrategyTargetError(
            "comparison target lacks publishedResolutionDate: "
            f"{target.get('catalogSlug')}"
        )
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise StrategyTargetError(
            f"invalid publishedResolutionDate {value!r} for "
            f"{target.get('catalogSlug')}"
        ) from exc


def load_local_resolution_evidence(
    root: pathlib.Path, checked_at_utc: str
) -> tuple[dict[str, Any], set[str]]:
    head_path = root.joinpath(*CHAIN_HEAD_RELATIVE.parts)
    head_bytes = head_path.read_bytes()
    head = load_object(head_path, "record chain head")
    if head.get("schemaVersion") != "thesis_record_chain_head_v1":
        raise StrategyTargetError("unsupported local record chain head schema")
    snapshot_relative = str(head.get("snapshotPath") or "")
    snapshot_path = repo_path(root, snapshot_relative)
    snapshot_bytes = snapshot_path.read_bytes()
    snapshot_sha = sha256_bytes(snapshot_bytes)
    if snapshot_sha != head.get("snapshotSha256"):
        raise StrategyTargetError("local record chain head snapshot hash mismatch")
    snapshot = load_object(snapshot_path, "record chain snapshot")
    resolutions = snapshot.get("resolutions")
    if not isinstance(resolutions, list):
        raise StrategyTargetError("record chain snapshot has no resolution inventory")
    resolved = {
        str(row["dataPointId"])
        for row in resolutions
        if isinstance(row, dict) and row.get("dataPointId")
    }
    evidence = {
        "chainHeadPath": CHAIN_HEAD_RELATIVE.as_posix(),
        "chainHeadSha256": sha256_bytes(head_bytes),
        "snapshotPath": snapshot_relative,
        "snapshotSha256": snapshot_sha,
        "snapshotRecordedAt": snapshot.get("recordedAt"),
        "checkedAtUtc": checked_at_utc,
        "resolutionCount": len(resolutions),
        "resolvedDataPointIds": [],
    }
    return evidence, resolved


def ledger_data_point_ids(path: pathlib.Path) -> set[str]:
    rows: set[str] = set()
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise StrategyTargetError(f"cannot read official ledger {path}: {exc}") from exc
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StrategyTargetError(
                f"invalid official ledger JSONL line {index}: {exc}"
            ) from exc
        if not isinstance(row, dict) or not row.get("source_record_id"):
            raise StrategyTargetError(
                f"official ledger line {index} lacks source_record_id"
            )
        rows.add(str(row["source_record_id"]))
    return rows


def build_ledger_evidence(
    ledger_path: pathlib.Path,
    *,
    repository: str,
    branch: str,
    logical_path: str,
    repository_commit: str,
    blob_sha: str,
    checked_at_utc: str,
) -> tuple[dict[str, Any], set[str]]:
    if not COMMIT_RE.fullmatch(repository_commit):
        raise StrategyTargetError("official ledger repository commit is invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", blob_sha):
        raise StrategyTargetError("official ledger blob SHA is invalid")
    raw = ledger_path.read_bytes()
    evidence = {
        "repository": repository,
        "branch": branch,
        "path": logical_path,
        "repositoryCommit": repository_commit,
        "blobSha": blob_sha,
        "contentSha256": sha256_bytes(raw),
        "checkedAtUtc": checked_at_utc,
        "resolvedDataPointIds": [],
    }
    return evidence, ledger_data_point_ids(ledger_path)


def parse_catalog_slugs(values: list[str]) -> list[str]:
    slugs: list[str] = []
    for value in values:
        slugs.extend(part.strip() for part in re.split(r"[,\n]", value) if part.strip())
    if len(slugs) != len(set(slugs)):
        raise StrategyTargetError("requested catalog slugs contain duplicates")
    for slug in slugs:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
            raise StrategyTargetError(f"invalid catalog slug: {slug!r}")
    return sorted(slugs)


def selection_hash(payload: dict[str, Any]) -> str:
    value = dict(payload)
    value.pop("selectionSetHash", None)
    return canonical_sha256(value)


def select_targets(
    *,
    root: pathlib.Path,
    source_sha: str,
    selected_at_utc: str,
    workflow: dict[str, Any],
    requested_slugs: list[str],
    auto_select: bool,
    max_targets: int,
    suite: str,
    ladder_prompt_mode: str = "ladder",
    ledger_path: pathlib.Path,
    ledger_repository: str,
    ledger_branch: str,
    ledger_logical_path: str,
    ledger_repository_commit: str,
    ledger_blob_sha: str,
    checked_at_utc: str | None = None,
) -> dict[str, Any]:
    source_sha = resolve_commit(root, source_sha)
    selected_at = parse_utc(selected_at_utc, "selectedAtUtc")
    checked_at_utc = checked_at_utc or selected_at_utc
    parse_utc(checked_at_utc, "checkedAtUtc")
    if suite not in SUITES:
        raise StrategyTargetError(f"unsupported strategy suite: {suite!r}")
    if ladder_prompt_mode not in {"ladder", "ladder_v2"}:
        raise StrategyTargetError(
            f"unsupported ladder prompt mode: {ladder_prompt_mode!r}"
        )
    if type(max_targets) is not int or max_targets < 0:
        raise StrategyTargetError("maxTargets must be a nonnegative integer")
    if len(requested_slugs) > max_targets:
        raise StrategyTargetError("explicit catalog slugs exceed maxTargets")

    generated_source = root.joinpath(*GENERATED_TARGETS_RELATIVE.parts).read_text()
    known_slugs = known_catalog_slugs(generated_source)
    unknown = sorted(set(requested_slugs) - known_slugs)
    if unknown:
        raise StrategyTargetError(f"unknown catalog slug(s): {', '.join(unknown)}")
    registrations = registrations_by_slug(root)
    local_evidence, locally_resolved = load_local_resolution_evidence(
        root, checked_at_utc
    )
    ledger_evidence, ledger_resolved = build_ledger_evidence(
        ledger_path,
        repository=ledger_repository,
        branch=ledger_branch,
        logical_path=ledger_logical_path,
        repository_commit=ledger_repository_commit,
        blob_sha=ledger_blob_sha,
        checked_at_utc=checked_at_utc,
    )

    candidates: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    for slug in sorted(known_slugs):
        try:
            target = published_target(
                root,
                slug,
                registrations,
                generated_source,
                source_sha,
                selected_at,
            )
            release_day = published_resolution_date(target)
            if release_day <= selected_at.date():
                raise StrategyTargetError(
                    f"target is on or past its official release day: {slug}"
                )
            data_point_id = str(target["dataPointId"])
            if data_point_id in locally_resolved:
                raise StrategyTargetError(
                    f"target is resolved in the verified local chain: {slug}"
                )
            if data_point_id in ledger_resolved:
                raise StrategyTargetError(
                    f"target is resolved in the pinned official ledger: {slug}"
                )
            candidates[slug] = target
        except (StrategyTargetError, ValueError) as exc:
            failures[slug] = str(exc)

    selected: list[dict[str, Any]] = []
    for slug in requested_slugs:
        if slug not in candidates:
            raise StrategyTargetError(
                failures.get(slug, f"target is not eligible: {slug}")
            )
        selected.append(candidates[slug])
    if auto_select:
        remaining = sorted(
            (
                target
                for slug, target in candidates.items()
                if slug not in set(requested_slugs)
            ),
            key=lambda target: (
                target["publishedResolutionDate"],
                target["catalogSlug"],
            ),
        )
        selected.extend(remaining[: max_targets - len(selected)])
    selected.sort(key=lambda target: target["catalogSlug"])

    selected_ids = {str(target["dataPointId"]) for target in selected}
    local_evidence["resolvedDataPointIds"] = sorted(selected_ids & locally_resolved)
    ledger_evidence["resolvedDataPointIds"] = sorted(selected_ids & ledger_resolved)
    day = selected_at.date().isoformat()
    run_id = workflow.get("runId")
    run_attempt = workflow.get("runAttempt")
    if type(run_id) is not int or run_id < 1:
        raise StrategyTargetError("workflow runId must be a positive integer")
    if type(run_attempt) is not int or run_attempt < 1:
        raise StrategyTargetError("workflow runAttempt must be a positive integer")
    payload: dict[str, Any] = {
        "schemaVersion": SELECTION_SCHEMA,
        "sourceSha": source_sha,
        "selectedAtUtc": selected_at_utc,
        "selectionPath": (
            "records/thesis-analyst/strategy-selections/"
            f"{day}/strategy-{run_id}-a{run_attempt}.json"
        ),
        "workflow": workflow,
        "request": {
            "catalogSlugs": sorted(requested_slugs),
            "autoSelect": auto_select,
            "maxTargets": max_targets,
            "suite": suite,
            # Sparse by design: absent means the v1 ladder contract, so
            # pre-ladder_v2 selections re-verify byte-identically.
            **(
                {"ladderPromptMode": ladder_prompt_mode}
                if ladder_prompt_mode != "ladder"
                else {}
            ),
        },
        "localResolutionEvidence": local_evidence,
        "ledgerEvidence": ledger_evidence,
        "targets": selected,
    }
    payload["selectionSetHash"] = selection_hash(payload)
    return payload


def stamp_artifact(
    selection: dict[str, Any],
    *,
    artifact_id: int,
    artifact_name: str,
    artifact_digest: str,
    artifact_created_at_utc: str,
) -> dict[str, Any]:
    if selection.get("schemaVersion") != SELECTION_SCHEMA:
        raise StrategyTargetError("unsupported selection schema")
    created = parse_utc(artifact_created_at_utc, "artifactCreatedAtUtc")
    selected = parse_utc(selection.get("selectedAtUtc"), "selectedAtUtc")
    lag = created - selected
    if lag < dt.timedelta(0) or lag > MAX_ARTIFACT_LAG:
        raise StrategyTargetError(
            f"selection artifact is not contemporaneous: lag={lag}"
        )
    if type(artifact_id) is not int or artifact_id < 1:
        raise StrategyTargetError("artifactId must be a positive integer")
    if not artifact_name:
        raise StrategyTargetError("artifactName is required")
    if re.fullmatch(r"[0-9a-f]{64}", artifact_digest):
        artifact_digest = f"sha256:{artifact_digest}"
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_digest):
        raise StrategyTargetError("artifactDigest must be sha256:<hex>")
    stamped = json.loads(json.dumps(selection))
    stamped["workflow"].update(
        {
            "artifactId": artifact_id,
            "artifactName": artifact_name,
            "artifactDigest": artifact_digest,
            "artifactCreatedAtUtc": artifact_created_at_utc,
        }
    )
    stamped["selectionSetHash"] = selection_hash(stamped)
    return stamped


def verify_artifact(selection: dict[str, Any], artifact: dict[str, Any]) -> None:
    workflow = selection.get("workflow") or {}
    expected = {
        "id": workflow.get("artifactId"),
        "name": workflow.get("artifactName"),
        "digest": workflow.get("artifactDigest"),
        "created_at": workflow.get("artifactCreatedAtUtc"),
    }
    for key, value in expected.items():
        if artifact.get(key) != value:
            raise StrategyTargetError(
                f"GitHub artifact witness mismatch for {key}: "
                f"expected {value!r}, got {artifact.get(key)!r}"
            )
    if artifact.get("expired") is not False:
        raise StrategyTargetError(
            "selection witness artifact lacks an affirmative unexpired status"
        )
    workflow_run = artifact.get("workflow_run") or {}
    if workflow_run.get("id") != workflow.get("runId"):
        raise StrategyTargetError(
            "selection witness belongs to a different workflow run"
        )
    unstamped_workflow = {
        key: value
        for key, value in workflow.items()
        if not key.startswith("artifact")
    }
    stamp_artifact(
        {**selection, "workflow": unstamped_workflow},
        artifact_id=int(expected["id"]),
        artifact_name=str(expected["name"]),
        artifact_digest=str(expected["digest"]),
        artifact_created_at_utc=str(expected["created_at"]),
    )


def verify_selection(
    selection: dict[str, Any], *, root: pathlib.Path, ledger_path: pathlib.Path
) -> None:
    if selection.get("schemaVersion") != SELECTION_SCHEMA:
        raise StrategyTargetError("unsupported selection schema")
    if selection_hash(selection) != selection.get("selectionSetHash"):
        raise StrategyTargetError("selectionSetHash mismatch")
    evidence = selection.get("ledgerEvidence") or {}
    if sha256_bytes(ledger_path.read_bytes()) != evidence.get("contentSha256"):
        raise StrategyTargetError("pinned official ledger content hash mismatch")
    request = selection.get("request") or {}
    expected = select_targets(
        root=root,
        source_sha=str(selection.get("sourceSha") or ""),
        selected_at_utc=str(selection.get("selectedAtUtc") or ""),
        workflow=dict(selection.get("workflow") or {}),
        requested_slugs=list(request.get("catalogSlugs") or []),
        auto_select=request.get("autoSelect") is True,
        max_targets=request.get("maxTargets"),
        suite=str(request.get("suite") or ""),
        ladder_prompt_mode=str(request.get("ladderPromptMode") or "ladder"),
        ledger_path=ledger_path,
        ledger_repository=str(evidence.get("repository") or ""),
        ledger_branch=str(evidence.get("branch") or ""),
        ledger_logical_path=str(evidence.get("path") or ""),
        ledger_repository_commit=str(evidence.get("repositoryCommit") or ""),
        ledger_blob_sha=str(evidence.get("blobSha") or ""),
        checked_at_utc=str(evidence.get("checkedAtUtc") or ""),
    )
    if canonical_bytes(expected) != canonical_bytes(selection):
        raise StrategyTargetError("selection differs from trusted canonical resolution")


def ensure_open(
    selection: dict[str, Any],
    *,
    root: pathlib.Path,
    ledger_path: pathlib.Path,
    checked_at_utc: str,
) -> None:
    checked = parse_utc(checked_at_utc, "checkedAtUtc")
    _local_evidence, locally_resolved = load_local_resolution_evidence(
        root, checked_at_utc
    )
    ledger_resolved = ledger_data_point_ids(ledger_path)
    for target in selection.get("targets") or []:
        data_point_id = str(target.get("dataPointId") or "")
        slug = str(target.get("catalogSlug") or "")
        if data_point_id in locally_resolved:
            raise StrategyTargetError(
                f"target became resolved in the verified local chain: {slug}"
            )
        if data_point_id in ledger_resolved:
            raise StrategyTargetError(
                f"target became resolved in the official ledger: {slug}"
            )
        release_day = published_resolution_date(target)
        if release_day <= checked.date():
            raise StrategyTargetError(
                f"target reached its official release day before generation: {slug}"
            )


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)

    select = commands.add_parser("select")
    select.add_argument("--catalog-slug", action="append", default=[])
    select.add_argument("--catalog-slugs", action="append", default=[])
    select.add_argument("--auto-select", action="store_true")
    select.add_argument("--max-targets", type=int, required=True)
    select.add_argument("--suite", choices=sorted(SUITES), required=True)
    select.add_argument(
        "--ladder-prompt-mode",
        choices=["ladder", "ladder_v2"],
        default="ladder",
    )
    select.add_argument("--selected-at-utc", required=True)
    select.add_argument("--checked-at-utc")
    select.add_argument("--source-sha", required=True)
    select.add_argument("--workflow-repository", required=True)
    select.add_argument("--workflow-run-id", type=int, required=True)
    select.add_argument("--workflow-run-attempt", type=int, required=True)
    select.add_argument("--ledger-jsonl", type=pathlib.Path, required=True)
    select.add_argument("--ledger-repository", required=True)
    select.add_argument("--ledger-branch", required=True)
    select.add_argument("--ledger-path", required=True)
    select.add_argument("--ledger-repository-commit", required=True)
    select.add_argument("--ledger-blob-sha", required=True)
    select.add_argument("--out", type=pathlib.Path, required=True)

    stamp = commands.add_parser("stamp-artifact")
    stamp.add_argument("--selection", type=pathlib.Path, required=True)
    stamp.add_argument("--artifact-id", type=int, required=True)
    stamp.add_argument("--artifact-name", required=True)
    stamp.add_argument("--artifact-digest", required=True)
    stamp.add_argument("--artifact-created-at-utc", required=True)
    stamp.add_argument("--out", type=pathlib.Path)

    verify = commands.add_parser("verify")
    verify.add_argument("--selection", type=pathlib.Path, required=True)
    verify.add_argument("--ledger-jsonl", type=pathlib.Path, required=True)

    artifact = commands.add_parser("verify-artifact")
    artifact.add_argument("--selection", type=pathlib.Path, required=True)
    artifact.add_argument("--artifact-json", type=pathlib.Path, required=True)

    open_parser = commands.add_parser("ensure-open")
    open_parser.add_argument("--selection", type=pathlib.Path, required=True)
    open_parser.add_argument("--ledger-jsonl", type=pathlib.Path, required=True)
    open_parser.add_argument("--checked-at-utc", required=True)

    persist = commands.add_parser("persist")
    persist.add_argument("--selection", type=pathlib.Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    try:
        if args.command == "select":
            requested = parse_catalog_slugs([*args.catalog_slug, *args.catalog_slugs])
            payload = select_targets(
                root=root,
                source_sha=args.source_sha,
                selected_at_utc=args.selected_at_utc,
                checked_at_utc=args.checked_at_utc,
                workflow={
                    "repository": args.workflow_repository,
                    "runId": args.workflow_run_id,
                    "runAttempt": args.workflow_run_attempt,
                },
                requested_slugs=requested,
                auto_select=args.auto_select,
                max_targets=args.max_targets,
                suite=args.suite,
                ladder_prompt_mode=args.ladder_prompt_mode,
                ledger_path=args.ledger_jsonl,
                ledger_repository=args.ledger_repository,
                ledger_branch=args.ledger_branch,
                ledger_logical_path=args.ledger_path,
                ledger_repository_commit=args.ledger_repository_commit,
                ledger_blob_sha=args.ledger_blob_sha,
            )
            write_json(args.out, payload)
            print(
                json.dumps(
                    {
                        "count": len(payload["targets"]),
                        "selectionSetHash": payload["selectionSetHash"],
                        "selectionPath": payload["selectionPath"],
                    },
                    sort_keys=True,
                )
            )
        elif args.command == "stamp-artifact":
            selection = load_object(args.selection, "strategy selection")
            payload = stamp_artifact(
                selection,
                artifact_id=args.artifact_id,
                artifact_name=args.artifact_name,
                artifact_digest=args.artifact_digest,
                artifact_created_at_utc=args.artifact_created_at_utc,
            )
            write_json(args.out or args.selection, payload)
        elif args.command == "verify":
            verify_selection(
                load_object(args.selection, "strategy selection"),
                root=root,
                ledger_path=args.ledger_jsonl,
            )
            print("strategy selection verified")
        elif args.command == "verify-artifact":
            verify_artifact(
                load_object(args.selection, "strategy selection"),
                load_object(args.artifact_json, "GitHub artifact"),
            )
            print("selection artifact witness verified")
        elif args.command == "ensure-open":
            selection = load_object(args.selection, "strategy selection")
            if selection_hash(selection) != selection.get("selectionSetHash"):
                raise StrategyTargetError("selectionSetHash mismatch")
            ensure_open(
                selection,
                root=root,
                ledger_path=args.ledger_jsonl,
                checked_at_utc=args.checked_at_utc,
            )
            print("selected strategy targets remain open")
        elif args.command == "persist":
            selection = load_object(args.selection, "strategy selection")
            if selection_hash(selection) != selection.get("selectionSetHash"):
                raise StrategyTargetError("selectionSetHash mismatch")
            destination = repo_path(root, str(selection.get("selectionPath") or ""))
            payload = args.selection.read_bytes()
            if destination.exists():
                if destination.is_symlink() or destination.read_bytes() != payload:
                    raise StrategyTargetError(
                        f"selection witness would overwrite history: {destination}"
                    )
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(args.selection, destination)
            print(destination.relative_to(root))
    except (StrategyTargetError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"STRATEGY TARGETS BLOCKED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
