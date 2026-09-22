#!/usr/bin/env python3
"""Move strategy-comparison runs across the publication trust boundary.

Authority comes only from a trusted selection and one exact strategy-suite
manifest.  The suite names every analyst batch and derived median run that may
cross the boundary; caller-provided path prefixes are never accepted.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import shutil
import stat
import subprocess
import sys
from typing import Any

import docket_publication as docket
import median_rollout_ensemble as median_builder
from canonical_json import canonical_bytes, canonical_sha256
from strategy_targets import (
    StrategyTargetError,
    conditional_comparison_context,
    require_bill_target_set,
    require_conditional_open,
)
from verify_custody import CustodyError, verify_run

ROOT = pathlib.Path(__file__).resolve().parents[1]
SELECTION_SCHEMA = "thesis_strategy_selection_v1"
SUITE_SCHEMA = "thesis_strategy_suite_v1"
BUNDLE_SCHEMA = "thesis_strategy_publication_bundle_v1"
SUITE_RE = re.compile(
    r"^records/thesis-analyst/strategy-suites/(?P<day>\d{4}-\d{2}-\d{2})/"
    r"[a-z0-9][a-z0-9._-]*\.json$"
)
SELECTION_RE = re.compile(
    r"^records/thesis-analyst/strategy-selections/(?P<day>\d{4}-\d{2}-\d{2})/"
    r"strategy-[1-9][0-9]*-a[1-9][0-9]*\.json$"
)
MAX_ARTIFACT_STAMP_LAG = dt.timedelta(minutes=15)
RESOLVER_FIELDS = (
    "catalogSlug",
    "country",
    "dataPointId",
    "targetUnit",
    # The published forecast's resolver date. A trusted target never stores
    # it as `resolutionDate`: that key must mirror the registered contract
    # with the snapshot's exact presence, and release-calendar contracts omit
    # it (see strategy_targets.published_target).
    "publishedResolutionDate",
    "resolutionSource",
    "resolutionSourceUrl",
    "resolutionRule",
    "resolutionPolicy",
)
REGISTRATION_FIELDS = (
    "registrationCommit",
    "targetContentHash",
    "targetRegistrationPath",
    "registeredAtUtc",
)


class StrategyPublicationError(ValueError):
    """A strategy bundle failed a publication-boundary check."""


def _load_object(path: pathlib.Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StrategyPublicationError(f"invalid {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StrategyPublicationError(f"{label} must be a JSON object: {path}")
    return value


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _instant(value: Any, label: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise StrategyPublicationError(f"invalid {label}: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StrategyPublicationError(f"{label} lacks a UTC offset: {value!r}")
    return parsed.astimezone(dt.timezone.utc)


def _require_claimed_run_window(
    lower: dt.datetime,
    run_start: dt.datetime,
    run_at: dt.datetime,
    upper: dt.datetime,
    label: str,
) -> None:
    if not (lower <= run_start <= run_at <= upper):
        raise StrategyPublicationError(
            f"{label} claimed runAt is outside the witnessed window"
        )


def _suite_path(value: str) -> pathlib.PurePosixPath:
    relative = docket.relative_repo_path(value)
    if not SUITE_RE.fullmatch(relative.as_posix()):
        raise StrategyPublicationError(
            f"strategy suite path is not invocation-scoped: {relative}"
        )
    return relative


def _repo_file(repo: pathlib.Path, relative: pathlib.PurePosixPath) -> pathlib.Path:
    try:
        return docket.safe_join(repo, relative)
    except docket.PublicationError as exc:
        raise StrategyPublicationError(str(exc)) from exc


def _validate_selection(
    selection_path: pathlib.Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dt.datetime]:
    selection = _load_object(selection_path, "trusted strategy selection")
    if selection.get("schemaVersion") != SELECTION_SCHEMA:
        raise StrategyPublicationError("unsupported strategy selection schema")
    expected_hash = selection.get("selectionSetHash")
    payload = dict(selection)
    payload.pop("selectionSetHash", None)
    if expected_hash != canonical_sha256(payload):
        raise StrategyPublicationError("trusted selection set hash mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", str(selection.get("sourceSha") or "")):
        raise StrategyPublicationError("trusted selection has an invalid sourceSha")
    selected_at = _instant(selection.get("selectedAtUtc"), "selectedAtUtc")
    selection_logical = str(selection.get("selectionPath") or "")
    selection_match = SELECTION_RE.fullmatch(selection_logical)
    if (
        not selection_match
        or selection_match.group("day") != selected_at.date().isoformat()
    ):
        raise StrategyPublicationError("trusted selectionPath is not invocation-scoped")
    workflow = selection.get("workflow")
    if not isinstance(workflow, dict):
        raise StrategyPublicationError("trusted selection lacks workflow evidence")
    artifact_at = _instant(
        workflow.get("artifactCreatedAtUtc"), "artifact server createdAt"
    )
    lag = artifact_at - selected_at
    if lag < dt.timedelta(0) or lag > MAX_ARTIFACT_STAMP_LAG:
        raise StrategyPublicationError(
            "artifact server createdAt is not contemporaneous with selection: "
            f"lag={lag}"
        )
    for key in ("runId", "runAttempt", "artifactId"):
        if type(workflow.get(key)) is not int or workflow[key] < 1:
            raise StrategyPublicationError(f"workflow {key} must be a positive integer")
    targets = selection.get("targets")
    if (
        not isinstance(targets, list)
        or not targets
        or not all(isinstance(target, dict) for target in targets)
    ):
        raise StrategyPublicationError(
            "trusted selection targets must be nonempty objects"
        )
    targets_by_slug = {target.get("catalogSlug"): target for target in targets}
    if len(targets_by_slug) != len(targets) or None in targets_by_slug:
        raise StrategyPublicationError(
            "trusted selection has duplicate or missing slugs"
        )
    for slug, target in targets_by_slug.items():
        if target.get("comparisonTarget") is not True:
            raise StrategyPublicationError(
                f"target is not comparison-authorized: {slug}"
            )
        missing = [
            field
            for field in (*RESOLVER_FIELDS, *REGISTRATION_FIELDS)
            if target.get(field) in (None, "")
        ]
        if missing:
            raise StrategyPublicationError(
                f"trusted comparison target {slug} lacks {', '.join(missing)}"
            )
    try:
        require_bill_target_set(selection)
    except StrategyTargetError as exc:
        raise StrategyPublicationError(str(exc)) from exc
    return selection, targets_by_slug, artifact_at


def _validate_source_sha(source_sha: str, *, exact: bool) -> None:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if exact:
        if head != source_sha:
            raise StrategyPublicationError(
                f"generation checkout {head} differs from selected source {source_sha}"
            )
        return
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_sha, "HEAD"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if ancestor.returncode != 0:
        raise StrategyPublicationError(
            f"selected source is not an ancestor of publisher HEAD: {source_sha}"
        )


def _validate_suite_shape(
    suite: dict[str, Any],
    suite_relative: pathlib.PurePosixPath,
    selection: dict[str, Any],
    selection_path: pathlib.Path,
    targets_by_slug: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    if suite.get("schemaVersion") != SUITE_SCHEMA:
        raise StrategyPublicationError("unsupported strategy suite schema")
    if suite.get("sourceSha") != selection.get("sourceSha"):
        raise StrategyPublicationError("suite sourceSha differs from trusted selection")
    if suite.get("selectionPath") != selection.get("selectionPath"):
        raise StrategyPublicationError("suite selectionPath differs from selection")
    if suite.get("selectionSha256") != _sha256(selection_path):
        raise StrategyPublicationError("suite selection SHA-256 mismatch")
    if suite.get("selectionSetHash") != selection.get("selectionSetHash"):
        raise StrategyPublicationError("suite selection set hash mismatch")
    workflow = selection.get("workflow") or {}
    run_id = workflow.get("runId")
    run_attempt = workflow.get("runAttempt")
    invocation = f"strategy-{run_id}-a{run_attempt}"
    requested_suite = (selection.get("request") or {}).get("suite")
    suite_name = suite.get("suite")
    if suite_name not in {"ladder", "median3", "both"} or suite_name != requested_suite:
        raise StrategyPublicationError("suite selector differs from trusted request")
    if suite_relative.parent.name != str(suite.get("createdAt") or "")[:10]:
        raise StrategyPublicationError("suite path day differs from createdAt")
    if suite_relative.name != f"{invocation}.json":
        raise StrategyPublicationError(
            "suite path differs from the trusted workflow invocation"
        )
    lanes = suite.get("lanes")
    if not isinstance(lanes, dict) or set(lanes) != {"ladder", "rollouts", "median3"}:
        raise StrategyPublicationError("suite lanes have an invalid shape")
    ladder = lanes["ladder"]
    rollouts = lanes["rollouts"]
    medians = lanes["median3"]
    if not isinstance(rollouts, list) or not isinstance(medians, list):
        raise StrategyPublicationError("suite rollout and median lanes must be lists")
    expected_ladder_mode = str(
        (selection.get("request") or {}).get("ladderPromptMode") or "ladder"
    )
    if expected_ladder_mode not in {"ladder", "ladder_v2"}:
        raise StrategyPublicationError(
            "trusted selection carries an unsupported ladder prompt mode"
        )
    if suite_name in {"ladder", "both"}:
        # The lane may record its promptMode (suite runners do from
        # ladder_v2 on); when recorded it must equal the TRUSTED selection's
        # mode, and a non-default trusted mode requires the recording — a
        # bare lane under a ladder_v2 selection means the runner ignored
        # the requested contract.
        if not isinstance(ladder, dict) or set(ladder) not in (
            {"batchManifest"},
            {"batchManifest", "promptMode"},
        ):
            raise StrategyPublicationError(
                "ladder suite lacks its exact batch manifest"
            )
        recorded_mode = ladder.get("promptMode")
        if recorded_mode is not None and recorded_mode != expected_ladder_mode:
            raise StrategyPublicationError(
                "ladder lane prompt mode differs from trusted selection"
            )
        if recorded_mode is None and expected_ladder_mode != "ladder":
            raise StrategyPublicationError(
                "ladder lane does not record the trusted non-default prompt mode"
            )
        _require_invocation_batch(
            ladder["batchManifest"], selection, f"{invocation}-ladder.json"
        )
    elif ladder is not None:
        raise StrategyPublicationError(
            "median3-only suite unexpectedly has a ladder lane"
        )
    if suite_name in {"median3", "both"}:
        if [row.get("index") for row in rollouts if isinstance(row, dict)] != [1, 2, 3]:
            raise StrategyPublicationError(
                "median3 suite requires rollout indices 1,2,3"
            )
        if any(set(row) != {"index", "batchManifest"} for row in rollouts):
            raise StrategyPublicationError("rollout lane entry has unexpected fields")
        for row in rollouts:
            _require_invocation_batch(
                row["batchManifest"],
                selection,
                f"{invocation}-rollout-{row['index']}.json",
            )
        median_slugs = [
            row.get("catalogSlug") for row in medians if isinstance(row, dict)
        ]
        if sorted(median_slugs) != sorted(targets_by_slug) or len(median_slugs) != len(
            medians
        ):
            raise StrategyPublicationError(
                "median lane does not cover the selected targets"
            )
        for row in medians:
            if set(row) != {"catalogSlug", "ok", "manifestPath", "error"}:
                raise StrategyPublicationError(
                    "median lane entry has unexpected fields"
                )
            if type(row["ok"]) is not bool:
                raise StrategyPublicationError("median lane status must be boolean")
            if row["ok"] and (not row["manifestPath"] or row["error"] is not None):
                raise StrategyPublicationError(
                    "passing median entry lacks its manifest"
                )
            if not row["ok"] and (row["manifestPath"] is not None or not row["error"]):
                raise StrategyPublicationError("failed median entry lacks its error")
    elif rollouts or medians:
        raise StrategyPublicationError("ladder-only suite has median3 lane data")
    return ladder, rollouts, medians


def _require_invocation_batch(
    value: Any, selection: dict[str, Any], expected_name: str
) -> None:
    relative = _batch_relative(value)
    selected_day = str(selection.get("selectedAtUtc") or "")[:10]
    expected = pathlib.PurePosixPath(
        "records", "thesis-analyst", "batches", selected_day, expected_name
    )
    if relative != expected:
        raise StrategyPublicationError(
            f"strategy batch path differs from its trusted lane: {relative}"
        )


def _batch_relative(value: Any) -> pathlib.PurePosixPath:
    try:
        return docket.validate_batch_path(str(value or ""))
    except docket.PublicationError as exc:
        raise StrategyPublicationError(str(exc)) from exc


def _run_relative(value: Any) -> pathlib.PurePosixPath:
    relative = docket.relative_repo_path(str(value or ""))
    match = docket.RUN_MANIFEST_RE.fullmatch(relative.as_posix())
    if not match or not match.group("run").startswith(f"{match.group('day')}t"):
        raise StrategyPublicationError(
            f"run manifest is outside exact scope: {relative}"
        )
    return relative


def _target_map(
    results: Any, targets_by_slug: dict[str, dict[str, Any]], label: str
) -> dict[str, dict[str, Any]]:
    if not isinstance(results, list) or not all(
        isinstance(row, dict) for row in results
    ):
        raise StrategyPublicationError(f"{label} batch results must be objects")
    mapped: dict[str, dict[str, Any]] = {}
    for result in results:
        target = result.get("target")
        slug = target.get("catalogSlug") if isinstance(target, dict) else None
        if slug in mapped or canonical_bytes(
            targets_by_slug.get(slug)
        ) != canonical_bytes(target):
            raise StrategyPublicationError(
                f"{label} batch contains an unauthorized target: {slug}"
            )
        mapped[str(slug)] = result
    if set(mapped) != set(targets_by_slug):
        raise StrategyPublicationError(
            f"{label} batch target set differs from selection"
        )
    return mapped


def _resolver_equal(cell: dict[str, Any], target: dict[str, Any]) -> None:
    premise = target.get("conditional")
    if canonical_bytes(cell.get("conditionalOn")) != canonical_bytes(premise):
        raise StrategyPublicationError(
            "cell conditionalOn differs from trusted target premise"
        )
    if premise is not None and cell.get("type") != "conditional":
        raise StrategyPublicationError(
            "conditional comparison cell must have type conditional"
        )
    if premise is None and cell.get("type") == "conditional":
        raise StrategyPublicationError(
            "unconditional comparison cannot carry conditional type"
        )
    cell_keys = {
        "catalogSlug": "slug",
        "targetUnit": "unit",
        # Comparison cells are graded against the published forecast's
        # resolver, so their resolutionDate must equal its published date.
        "publishedResolutionDate": "resolutionDate",
    }
    for field in RESOLVER_FIELDS:
        # resolutionPolicy is target-architecture metadata; forecast cells carry
        # the substantive rule/source/date but do not duplicate this field.
        if field == "resolutionPolicy":
            continue
        cell_field = cell_keys.get(field, field)
        if canonical_bytes(cell.get(cell_field)) != canonical_bytes(target.get(field)):
            raise StrategyPublicationError(
                f"cell resolver {cell_field} differs from trusted target "
                f"field {field}"
            )
    for field in REGISTRATION_FIELDS:
        if canonical_bytes(cell.get(field)) != canonical_bytes(target.get(field)):
            raise StrategyPublicationError(
                f"cell registration differs from trusted target field {field}"
            )


def _validate_manifest_identity(
    manifest: dict[str, Any],
    target: dict[str, Any],
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        if canonical_bytes(manifest.get(field)) != canonical_bytes(target.get(field)):
            raise StrategyPublicationError(
                f"run manifest target identity mismatch: {field}"
            )


def _validate_analyst_result(
    repo: pathlib.Path,
    result: dict[str, Any],
    *,
    prompt_mode: str,
    lower: dt.datetime,
    upper: dt.datetime,
) -> tuple[pathlib.PurePosixPath, str | None]:
    target = result["target"]
    manifest_relative = _run_relative(result.get("manifestPath"))
    manifest_path = _repo_file(repo, manifest_relative)
    manifest = _load_object(manifest_path, "strategy run manifest")
    if manifest.get("schemaVersion") != "thesis_analyst_run_manifest_v1":
        raise StrategyPublicationError("strategy batch contains a non-analyst manifest")
    if manifest.get("promptMode") != prompt_mode:
        raise StrategyPublicationError("strategy run prompt mode differs from its lane")
    if canonical_bytes(manifest.get("targetContext")) != canonical_bytes(target):
        raise StrategyPublicationError("run targetContext differs from trusted target")
    _validate_manifest_identity(manifest, target, ("series", "period", "conditional"))
    expected_ok = result.get("ok") is True
    if manifest.get("ok") is not expected_ok:
        raise StrategyPublicationError("batch and run success status differ")
    docket.validate_run_file_inventory(repo, manifest_relative, manifest)
    try:
        verification = verify_run(manifest_path.parent)
    except CustodyError as exc:
        raise StrategyPublicationError(
            f"run custody verification failed: {exc}"
        ) from exc
    if (
        verification.inventory_status != "complete"
        or verification.run_mode != "analyst"
    ):
        raise StrategyPublicationError(
            "new strategy analyst run lacks complete v2 custody"
        )
    if verification.run_succeeded != expected_ok:
        raise StrategyPublicationError("run custody success status differs from batch")
    run_start = _instant(manifest.get("runStartedAt"), "runStartedAt")
    if manifest.get("createdAt") != manifest.get("runStartedAt"):
        raise StrategyPublicationError("run createdAt/runStartedAt mismatch")
    path_stamp = manifest_relative.parent.name[:20]
    try:
        path_start = dt.datetime.strptime(path_stamp, "%Y-%m-%dt%H-%M-%Sz").replace(
            tzinfo=dt.timezone.utc
        )
    except ValueError as exc:
        raise StrategyPublicationError(
            "run directory lacks canonical timestamp"
        ) from exc
    result_start = _instant(result.get("startedAt"), "result startedAt")
    result_finish = _instant(result.get("finishedAt"), "result finishedAt")
    if not (lower <= result_start <= run_start == path_start <= result_finish <= upper):
        raise StrategyPublicationError(
            "strategy analyst run is outside witnessed window"
        )
    for field in REGISTRATION_FIELDS:
        if manifest.get(field) != target.get(field):
            raise StrategyPublicationError(
                f"run registration binding mismatch: {field}"
            )
    try:
        # Comparison targets are pre-existing registrations by design; v2
        # snapshots introduced strictly before the v3 cutover stay eligible.
        docket.validate_target_registration(
            repo,
            conditional_comparison_context(ROOT, target),
            run_started_at=str(manifest.get("runStartedAt")),
            require_git_binding=True,
            allow_pre_cutover_v2=True,
        )
    except (docket.PublicationError, StrategyTargetError) as exc:
        raise StrategyPublicationError(str(exc)) from exc
    cells_value = result.get("cellsPath")
    if manifest.get("cellsPath") != cells_value:
        raise StrategyPublicationError("run cellsPath differs from batch")
    sealed_at: str | None = None
    if cells_value:
        cells_relative = docket.relative_repo_path(str(cells_value))
        if cells_relative != manifest_relative.parent / "cells.with_activity.json":
            raise StrategyPublicationError("cells payload is outside its exact run")
        cells = json.loads(_repo_file(repo, cells_relative).read_text())
        if not isinstance(cells, list) or len(cells) != 1:
            raise StrategyPublicationError("strategy run must contain exactly one cell")
        cell = cells[0]
        if expected_ok:
            _resolver_equal(cell, target)
        # A failed model response may itself violate the target premise or
        # resolver. Preserve that failure under the authenticated run context;
        # below, the trusted validator must reproduce its failed status, and
        # failed results never become comparison augments.
        seal = _instant(cell.get("runAt"), "cell runAt")
        if cell.get("runStartedAt") != manifest.get("runStartedAt"):
            raise StrategyPublicationError("cell start differs from its manifest")
        _require_claimed_run_window(
            lower, run_start, seal, min(result_finish, upper), "analyst"
        )
        if seal > result_finish:
            raise StrategyPublicationError("cell seal is outside its result wrapper")
        sealed_at = str(cell["runAt"])
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from run_thesis_analyst import validate_cells as validate_forecast_cells
        finally:
            sys.path.pop(0)
        report = validate_forecast_cells(
            cells,
            allow_existing_slug=True,
            target_context=target,
            prompt_mode=prompt_mode,
            agent_version=(
                manifest.get("agent", {}).get("agentVersion")
                if isinstance(manifest.get("agent"), dict)
                else None
            ),
            checkout_sha=manifest.get("checkoutSha"),
            series=manifest.get("series"),
            target_period=manifest.get("period"),
            # The staged bundle is data, not authority and may not even be a
            # Git checkout. Read reviewed authorization from trusted code.
            history_registry_root=ROOT,
        )
        if bool(report.get("ok")) != expected_ok:
            raise StrategyPublicationError(
                "trusted validator disagrees with run status"
            )
        if expected_ok and prompt_mode in {"ladder", "ladder_v2"}:
            review = manifest.get("preSubmitReview")
            if not isinstance(review, dict) or review.get("status") != "completed":
                raise StrategyPublicationError(
                    "passing ladder run lacks completed review"
                )
        if expected_ok and prompt_mode == "fast" and manifest.get("preSubmitReview"):
            raise StrategyPublicationError(
                "fast rollout unexpectedly used pre-submit review"
            )
    elif expected_ok:
        raise StrategyPublicationError("passing strategy result lacks cells")
    return manifest_relative, sealed_at


def _validate_batch(
    repo: pathlib.Path,
    relative: pathlib.PurePosixPath,
    targets_by_slug: dict[str, dict[str, Any]],
    *,
    prompt_mode: str,
    lower: dt.datetime,
    upper: dt.datetime,
) -> tuple[dict[str, dict[str, Any]], set[pathlib.PurePosixPath], dt.datetime]:
    batch = _load_object(_repo_file(repo, relative), "strategy batch")
    if batch.get("schemaVersion") != "thesis_batch_manifest_v1":
        raise StrategyPublicationError("unsupported strategy batch schema")
    if batch.get("promptMode") != prompt_mode:
        raise StrategyPublicationError("strategy batch prompt mode differs from lane")
    batch_start = _instant(batch.get("startedAt"), "batch startedAt")
    batch_finish = _instant(batch.get("finishedAt"), "batch finishedAt")
    if not (lower <= batch_start <= batch_finish <= upper):
        raise StrategyPublicationError("strategy batch is outside witnessed window")
    results = _target_map(batch.get("results"), targets_by_slug, prompt_mode)
    if type(batch.get("targets")) is not int or batch["targets"] != len(results):
        raise StrategyPublicationError("strategy batch target count mismatch")
    passed = sum(result.get("ok") is True for result in results.values())
    if (
        type(batch.get("ok")) is not int
        or type(batch.get("failed")) is not int
        or batch["ok"] != passed
        or batch["failed"] != len(results) - passed
    ):
        raise StrategyPublicationError("strategy batch success counters mismatch")
    prefixes: set[pathlib.PurePosixPath] = set()
    for result in results.values():
        result_start = _instant(result.get("startedAt"), "result startedAt")
        result_finish = _instant(result.get("finishedAt"), "result finishedAt")
        if result_start < batch_start or result_finish > batch_finish:
            raise StrategyPublicationError("batch timestamps do not contain a result")
        manifest_relative, _ = _validate_analyst_result(
            repo,
            result,
            prompt_mode=prompt_mode,
            lower=lower,
            upper=upper,
        )
        prefixes.add(manifest_relative.parent)
    return results, prefixes, batch_finish


def _claim_run_prefixes(
    claimed: set[pathlib.PurePosixPath],
    additions: set[pathlib.PurePosixPath],
) -> None:
    overlap = claimed & additions
    if overlap:
        raise StrategyPublicationError(
            "strategy lanes reuse analyst run directories: "
            + ", ".join(str(path) for path in sorted(overlap))
        )
    claimed.update(additions)


def _validate_medians(
    repo: pathlib.Path,
    medians: list[dict[str, Any]],
    targets_by_slug: dict[str, dict[str, Any]],
    rollout_results: dict[int, dict[str, dict[str, Any]]],
    *,
    lower: dt.datetime,
    upper: dt.datetime,
) -> tuple[set[pathlib.PurePosixPath], list[dt.datetime]]:
    prefixes: set[pathlib.PurePosixPath] = set()
    seals: list[dt.datetime] = []
    for row in medians:
        slug = row["catalogSlug"]
        parents = [rollout_results[index][slug] for index in (1, 2, 3)]
        expected_ok = all(parent.get("ok") is True for parent in parents)
        if row["ok"] is not expected_ok:
            raise StrategyPublicationError(
                f"median status does not follow rollout statuses: {slug}"
            )
        if not expected_ok:
            continue
        relative = _run_relative(row["manifestPath"])
        manifest_path = _repo_file(repo, relative)
        manifest = _load_object(manifest_path, "median3 manifest")
        docket.validate_run_file_inventory(repo, relative, manifest)
        try:
            verification = verify_run(manifest_path.parent)
        except CustodyError as exc:
            raise StrategyPublicationError(f"median3 custody failed: {exc}") from exc
        if (
            verification.run_mode != "derived_ensemble"
            or verification.inventory_status != "complete"
            or not verification.run_succeeded
        ):
            raise StrategyPublicationError("new median3 run lacks complete v2 custody")
        target = targets_by_slug[slug]
        if canonical_bytes(manifest.get("targetContext")) != canonical_bytes(target):
            raise StrategyPublicationError("median3 target differs from selection")
        _validate_manifest_identity(manifest, target, ("series", "period"))
        expected_parent_paths = {
            str(parent["manifestPath"])
            for parent in parents
            if parent.get("ok") is True
        }
        actual_parent_paths = {
            str(parent.get("manifestPath"))
            for parent in manifest.get("constituentRuns", [])
            if isinstance(parent, dict)
        }
        if actual_parent_paths != expected_parent_paths:
            raise StrategyPublicationError("median3 parents differ from rollout lanes")
        cells_relative = docket.relative_repo_path(str(manifest.get("cellsPath") or ""))
        if cells_relative != relative.parent / "cells.with_activity.json":
            raise StrategyPublicationError("median3 cells payload is outside its run")
        cells = json.loads(_repo_file(repo, cells_relative).read_text())
        if not isinstance(cells, list) or len(cells) != 1:
            raise StrategyPublicationError("median3 must contain exactly one cell")
        _resolver_equal(cells[0], target)
        parent_cells = []
        for parent_result in parents:
            parent_cells_path = docket.relative_repo_path(
                str(parent_result.get("cellsPath") or "")
            )
            loaded = json.loads(_repo_file(repo, parent_cells_path).read_text())
            if not isinstance(loaded, list) or len(loaded) != 1:
                raise StrategyPublicationError(
                    "median3 parent must contain exactly one cell"
                )
            parent_cells.append(loaded[0])
        expected_distribution = median_builder.median_distribution(parent_cells)
        precision = max(
            max(
                median_builder.decimal_places(cell["pointEstimate"]),
                median_builder.decimal_places(cell["ciLow"]),
                median_builder.decimal_places(cell["ciHigh"]),
            )
            for cell in parent_cells
        )
        q10 = round(
            median_builder.quantile_from_points(expected_distribution["points"], 0.10),
            precision,
        )
        q50 = round(
            median_builder.quantile_from_points(expected_distribution["points"], 0.50),
            precision,
        )
        q90 = round(
            median_builder.quantile_from_points(expected_distribution["points"], 0.90),
            precision,
        )
        expected_distribution["summary"] = {
            "pointEstimate": q50,
            "median": q50,
            "interval80": {"lower": q10, "upper": q90},
        }
        expected_distribution["provenance"] = "agent_reported"
        distribution_ref = next(
            (
                artifact
                for artifact in manifest.get("artifacts", [])
                if artifact.get("artifactType") == "derived_distribution"
            ),
            None,
        )
        if not isinstance(distribution_ref, dict):
            raise StrategyPublicationError("median3 lacks its derived distribution")
        distribution_path = docket.relative_repo_path(
            str(distribution_ref.get("path") or "")
        )
        actual_distribution = json.loads(
            _repo_file(repo, distribution_path).read_text()
        )
        if canonical_bytes(actual_distribution) != canonical_bytes(
            expected_distribution
        ):
            raise StrategyPublicationError(
                "median3 distribution is not the deterministic parent median"
            )
        start = _instant(manifest.get("runStartedAt"), "median3 runStartedAt")
        seal = _instant(cells[0].get("runAt"), "median3 runAt")
        parent_seals = []
        for parent in manifest["constituentRuns"]:
            parent_seals.append(_instant(parent.get("runAt"), "constituent runAt"))
        _require_claimed_run_window(lower, start, seal, upper, "median3")
        if max(parent_seals) > start:
            raise StrategyPublicationError("median3 is outside witnessed parent window")
        prefixes.add(relative.parent)
        seals.append(seal)
    return prefixes, seals


def validate_tree(
    repo: pathlib.Path,
    suite_relative: pathlib.PurePosixPath,
    selection_path: pathlib.Path,
    *,
    publish_validated_at: str,
    exact_source: bool,
) -> tuple[set[pathlib.PurePosixPath], set[pathlib.PurePosixPath]]:
    selection, targets_by_slug, lower = _validate_selection(selection_path)
    upper = _instant(publish_validated_at, "publishValidatedAtUtc")
    if upper < lower:
        raise StrategyPublicationError("publish validation predates selection witness")
    if selection.get("billSelection") is not None:
        from bill_forecast_plan import require_open_bill_selection

        try:
            require_open_bill_selection(ROOT, selection["billSelection"], upper)
            for target in targets_by_slug.values():
                require_conditional_open(target, upper)
        except ValueError as exc:
            raise StrategyPublicationError(str(exc)) from exc
    _validate_source_sha(str(selection["sourceSha"]), exact=exact_source)
    suite = _load_object(_repo_file(repo, suite_relative), "strategy suite")
    ladder, rollout_lanes, medians = _validate_suite_shape(
        suite, suite_relative, selection, selection_path, targets_by_slug
    )
    suite_created = _instant(suite.get("createdAt"), "suite createdAt")
    if not (lower <= suite_created <= upper):
        raise StrategyPublicationError("suite createdAt is outside witnessed window")
    exact = {suite_relative}
    prefixes: set[pathlib.PurePosixPath] = set()
    finishes: list[dt.datetime] = []
    expected_ladder_mode = str(
        (selection.get("request") or {}).get("ladderPromptMode") or "ladder"
    )
    if ladder:
        relative = _batch_relative(ladder["batchManifest"])
        exact.add(relative)
        _, batch_prefixes, finished = _validate_batch(
            repo,
            relative,
            targets_by_slug,
            prompt_mode=expected_ladder_mode,
            lower=lower,
            upper=upper,
        )
        _claim_run_prefixes(prefixes, batch_prefixes)
        finishes.append(finished)
    rollout_results: dict[int, dict[str, dict[str, Any]]] = {}
    for lane in rollout_lanes:
        relative = _batch_relative(lane["batchManifest"])
        if relative in exact:
            raise StrategyPublicationError("suite references a batch more than once")
        exact.add(relative)
        results, batch_prefixes, finished = _validate_batch(
            repo,
            relative,
            targets_by_slug,
            prompt_mode="fast",
            lower=lower,
            upper=upper,
        )
        rollout_results[lane["index"]] = results
        _claim_run_prefixes(prefixes, batch_prefixes)
        finishes.append(finished)
    median_prefixes, median_seals = _validate_medians(
        repo,
        medians,
        targets_by_slug,
        rollout_results,
        lower=lower,
        upper=upper,
    )
    _claim_run_prefixes(prefixes, median_prefixes)
    if any(value > suite_created for value in [*finishes, *median_seals]):
        raise StrategyPublicationError(
            "suite was created before a strategy run finished"
        )
    return exact, prefixes


def _changed_paths(
    exact: set[pathlib.PurePosixPath], prefixes: set[pathlib.PurePosixPath]
) -> list[pathlib.PurePosixPath]:
    pathspecs = sorted(str(path) for path in exact | prefixes)
    output = subprocess.check_output(
        [
            "git",
            "ls-files",
            "--modified",
            "--others",
            "--exclude-standard",
            "--",
            *pathspecs,
        ],
        cwd=ROOT,
        text=True,
    )
    deleted = subprocess.check_output(
        ["git", "diff", "--name-only", "--diff-filter=D", "--", *pathspecs],
        cwd=ROOT,
        text=True,
    ).splitlines()
    if deleted:
        raise StrategyPublicationError("strategy generation may not delete files")
    return sorted(
        {docket.relative_repo_path(line) for line in output.splitlines() if line}
    )


def _path_error(
    relative: pathlib.PurePosixPath,
    run_prefixes: set[pathlib.PurePosixPath],
) -> str | None:
    if pathlib.PurePosixPath("records/targets") in relative.parents:
        return "target registration snapshots are forbidden"
    return docket.path_policy_error(relative, run_prefixes)


def _head_bytes(relative: pathlib.PurePosixPath) -> bytes | None:
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{relative.as_posix()}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if exists.returncode:
        return None
    return subprocess.check_output(
        ["git", "show", f"HEAD:{relative.as_posix()}"], cwd=ROOT
    )


def _assert_append_only(relative: pathlib.PurePosixPath, source: pathlib.Path) -> None:
    raw = source.read_bytes()
    committed = _head_bytes(relative)
    if committed is not None and committed != raw:
        raise StrategyPublicationError(
            f"append-only overwrite of HEAD path: {relative}"
        )
    destination = _repo_file(ROOT, relative)
    if source.resolve() == destination.resolve():
        return
    if destination.exists() and destination.read_bytes() != raw:
        raise StrategyPublicationError(
            f"append-only overwrite of checkout path: {relative}"
        )


def stage(args: argparse.Namespace) -> None:
    suite_relative = _suite_path(args.suite_manifest)
    selection_path = pathlib.Path(args.trusted_selection)
    selection, _, lower = _validate_selection(selection_path)
    # Generation-side validation uses the current trusted clock only as a
    # staging upper bound; the privileged publisher supplies the authoritative
    # upper bound again before apply.
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    exact, prefixes = validate_tree(
        ROOT,
        suite_relative,
        selection_path,
        publish_validated_at=max(now, lower).isoformat().replace("+00:00", "Z"),
        exact_source=True,
    )
    paths = _changed_paths(exact, prefixes)
    if not exact.issubset(set(paths)):
        raise StrategyPublicationError("suite or component batch is absent from delta")
    bundle = pathlib.Path(args.bundle_dir).resolve()
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle_repo = bundle / "repo"
    bundle_repo.mkdir(parents=True)
    entries = []
    for relative in paths:
        if not docket.path_in_scope(relative, exact, prefixes):
            raise StrategyPublicationError(
                f"path is outside exact suite scope: {relative}"
            )
        error = _path_error(relative, prefixes)
        if error:
            raise StrategyPublicationError(
                f"forbidden strategy path {relative}: {error}"
            )
        source = _repo_file(ROOT, relative)
        if source.is_symlink() or not source.is_file() or source.stat().st_mode & 0o111:
            raise StrategyPublicationError(
                f"strategy artifact is not inert data: {relative}"
            )
        _assert_append_only(relative, source)
        secret_hits = docket.scan_bytes(source.read_bytes())
        if secret_hits:
            raise StrategyPublicationError(
                f"strategy artifact may contain {', '.join(secret_hits)}: {relative}"
            )
        destination = _repo_file(bundle_repo, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        entries.append(
            {
                "path": relative.as_posix(),
                "bytes": source.stat().st_size,
                "sha256": _sha256(source),
                "mode": stat.S_IMODE(source.stat().st_mode),
            }
        )
    manifest = {
        "schemaVersion": BUNDLE_SCHEMA,
        "publicationKind": "strategy_comparison",
        "suiteManifest": suite_relative.as_posix(),
        "sourceSha": selection["sourceSha"],
        "selectionSha256": _sha256(selection_path),
        "selectionSetHash": selection["selectionSetHash"],
        "files": entries,
    }
    (bundle / "bundle_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"staged {len(entries)} strategy files in {bundle}")


def _load_bundle(
    bundle: pathlib.Path,
    suite_relative: pathlib.PurePosixPath,
    selection_path: pathlib.Path,
    publish_validated_at: str,
) -> tuple[pathlib.Path, dict[str, Any]]:
    bundle = bundle.resolve()
    repo = bundle / "repo"
    manifest_path = bundle / "bundle_manifest.json"
    if repo.is_symlink() or not repo.is_dir():
        raise StrategyPublicationError(
            "strategy bundle repo inventory is not a regular directory"
        )
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise StrategyPublicationError("strategy bundle manifest is not a regular file")
    manifest = _load_object(manifest_path, "strategy bundle manifest")
    selection, _, _ = _validate_selection(selection_path)
    expected_header = {
        "schemaVersion": BUNDLE_SCHEMA,
        "publicationKind": "strategy_comparison",
        "suiteManifest": suite_relative.as_posix(),
        "sourceSha": selection["sourceSha"],
        "selectionSha256": _sha256(selection_path),
        "selectionSetHash": selection["selectionSetHash"],
    }
    for key, value in expected_header.items():
        if manifest.get(key) != value:
            raise StrategyPublicationError(f"strategy bundle header mismatch: {key}")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not all(
        isinstance(row, dict) for row in entries
    ):
        raise StrategyPublicationError("strategy bundle files must be an object list")
    expected: set[pathlib.PurePosixPath] = set()
    for entry in entries:
        relative = docket.relative_repo_path(str(entry.get("path") or ""))
        if relative in expected:
            raise StrategyPublicationError(
                f"duplicate strategy bundle path: {relative}"
            )
        expected.add(relative)
        path = _repo_file(repo, relative)
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o111:
            raise StrategyPublicationError(
                f"bundle entry is not inert data: {relative}"
            )
        mode = entry.get("mode")
        if type(mode) is not int or mode & 0o111:
            raise StrategyPublicationError(
                f"bundle declares executable mode: {relative}"
            )
        if path.stat().st_size != entry.get("bytes") or _sha256(path) != entry.get(
            "sha256"
        ):
            raise StrategyPublicationError(f"strategy bundle hash mismatch: {relative}")
        if docket.scan_bytes(path.read_bytes()):
            raise StrategyPublicationError(
                f"strategy bundle secret scan failed: {relative}"
            )
    actual = {
        pathlib.PurePosixPath(path.relative_to(repo).as_posix())
        for path in repo.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != expected:
        raise StrategyPublicationError(
            f"strategy bundle inventory mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    exact, prefixes = validate_tree(
        repo,
        suite_relative,
        selection_path,
        publish_validated_at=publish_validated_at,
        exact_source=False,
    )
    if not exact.issubset(expected):
        raise StrategyPublicationError("bundle omits suite or component batch")
    for relative in expected:
        if not docket.path_in_scope(relative, exact, prefixes):
            raise StrategyPublicationError(
                f"bundle path is outside exact scope: {relative}"
            )
        error = _path_error(relative, prefixes)
        if error:
            raise StrategyPublicationError(
                f"forbidden strategy path {relative}: {error}"
            )
        _assert_append_only(relative, _repo_file(repo, relative))
    return repo, manifest


def _apply(repo: pathlib.Path, manifest: dict[str, Any]) -> None:
    for entry in manifest["files"]:
        relative = docket.relative_repo_path(entry["path"])
        source = _repo_file(repo, relative)
        _assert_append_only(relative, source)
        destination = _repo_file(ROOT, relative)
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def validate(args: argparse.Namespace) -> None:
    suite_relative = _suite_path(args.suite_manifest)
    repo, manifest = _load_bundle(
        pathlib.Path(args.bundle_dir),
        suite_relative,
        pathlib.Path(args.trusted_selection),
        args.publish_validated_at_utc,
    )
    if args.apply:
        _apply(repo, manifest)
        print("validated strategy publication bundle applied to checkout")
    else:
        print("validated strategy publication bundle")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    stage_parser = subparsers.add_parser("stage")
    stage_parser.add_argument("--bundle-dir", required=True)
    stage_parser.add_argument("--suite-manifest", required=True)
    stage_parser.add_argument("--trusted-selection", required=True)
    stage_parser.set_defaults(func=stage)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--bundle-dir", required=True)
    validate_parser.add_argument("--suite-manifest", required=True)
    validate_parser.add_argument("--trusted-selection", required=True)
    validate_parser.add_argument("--publish-validated-at-utc", required=True)
    validate_parser.add_argument("--apply", action="store_true")
    validate_parser.set_defaults(func=validate)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        args.func(args)
    except (
        StrategyPublicationError,
        docket.PublicationError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"STRATEGY PUBLICATION BLOCKED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
