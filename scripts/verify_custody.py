#!/usr/bin/env python3
"""Verify versioned, complete artifact custody for Thesis run modes."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import re
import stat
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from canonical_json import canonical_bytes, canonical_sha256

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_VERSION = 2
INVENTORY_STATUS_COMPLETE = "complete"
INVENTORY_STATUS_LEGACY = "legacy-incomplete"
DERIVED_ENSEMBLE_SCHEMA = "thesis_derived_ensemble_manifest_v1"
DERIVED_ENSEMBLE_ALGORITHM = "pointwise_median_cdf_v1"
LEGACY_DERIVED_AT = "2026-07-08T03:03:42Z"
LEGACY_DERIVED_DIRS = {
    "bls-ppi-final-demand-monthly-change-june-2026-median3-2026-07-08t03-03-42z",
    "census-housing-starts-saar-june-2026-median3-2026-07-08t03-03-42z",
    "continued-claims-week-2026-06-27-median3-2026-07-08t03-03-42z",
    "initial-claims-week-2026-07-04-median3-2026-07-08t03-03-42z",
    "us-core-cpi-mom-june-2026-median3-2026-07-08t03-03-42z",
    "us-cpi-u-mom-june-2026-median3-2026-07-08t03-03-42z",
}

ANALYST_COMPLETED_INVENTORY = {
    "prompt.md": "prompt",
    "raw_response.txt": "raw_response",
    "parsed_cells.json": "parsed_cell",
    "normalized_cells.json": "normalized_cell",
    "distribution.json": "run_distribution",
    "validation.json": "validation_report",
    "cells.with_activity.json": "cells_with_activity",
}
CODEX_STAGE_INVENTORY = {
    "codex_stdout.jsonl": "codex_stdout_jsonl",
    "codex_stderr.log": "codex_stderr_log",
    "codex_events.jsonl": "codex_events_jsonl",
    "codex_last_message.txt": "codex_last_message",
    "codex_trace.json": "codex_trace",
}
GEMINI_STAGE_INVENTORY = {
    "gemini_stdout.jsonl": "gemini_stdout_jsonl",
    "gemini_events.jsonl": "gemini_events_jsonl",
    "gemini_last_message.txt": "gemini_last_message",
    "gemini_trace.json": "gemini_trace",
}
REVIEWED_STAGE_INVENTORY = {
    "pre_submit_review_prompt.md": "review_prompt",
    "revision_prompt.md": "revision_prompt",
}
RESOLVER_RESPONSE_RE = re.compile(
    # One archived source response per fetched document: a lowercase series
    # or page identifier, the first-print vintage date, and a content-hash
    # prefix. CSV for ALFRED vintage fetches, HTML for archived source
    # pages (e.g. the Wayback snapshot of BLS Table A-19 and the Eurostat/
    # ABS release-day pages), JSON for API captures (BLS Public Data API,
    # StatCan WDS, ABS Data API, Eurostat SDMX), XLSX for e-Stat release
    # workbooks, and ZIP for witnessed SBA PDF bundles whose member lineage
    # remains on the fact row.
    r"responses/[a-z0-9._-]+-\d{4}-\d{2}-\d{2}-[0-9a-f]{16}"
    r"\.(?:csv|html|json|xlsx|zip)\.gz"
)
LEDGER_WITNESS_ARCHIVE_RE = re.compile(r"upstream/[a-z0-9][a-z0-9._-]*\.gz")
ARCHIVE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
LEDGER_WITNESS_V1 = "thesis_ledger_witness_run_v1"
LEDGER_WITNESS_V2 = "thesis_ledger_witness_run_v2"
LEDGER_RELEASE_ARCHIVE_V1 = "thesis_ledger_release_archive_v1"
SBA_PDF_WITNESS_V1 = "thesis_sba_pdf_witness_run_v1"
SBA_PDF_FETCH_EVENT_V1 = "thesis_sba_pdf_fetch_event_v1"
LEDGER_REPO = "PolicyEngine/chronicle"
# The upstream repository was renamed from PolicyEngine/ledger to
# PolicyEngine/chronicle on 2026-08-07. It is the same repository —
# GitHub preserves identity, commit SHAs, and redirects — so records
# witnessed before the rename legitimately store URLs under the old
# slug. Verification accepts either alias in STORED records while all
# new URL construction uses the canonical LEDGER_REPO above.
LEDGER_REPO_ALIASES = ("PolicyEngine/chronicle", "PolicyEngine/ledger")


def same_ledger_repo(left: object, right: object) -> bool:
    """Closed-set equivalence across the 2026-08-07 rename.

    Two repo slugs denote the same upstream iff they are equal or both
    members of the documented alias set. Anything outside the set never
    unifies with anything.
    """

    if left == right:
        return True
    return left in LEDGER_REPO_ALIASES and right in LEDGER_REPO_ALIASES


LEDGER_BRANCH = "codex/thesis-ledger-facts"
LEDGER_JSONL_PATH = "ledger/official_observations.jsonl"
LEDGER_CATALOG_PATH = "ledger/series_catalog.json"
LEDGER_RELEASE_DIRECTORY = "releases/manifests"
LEDGER_RELEASE_TREE_ROLES = {
    "commit": "ledger_commit_tree_api",
    "releases": "ledger_releases_tree_api",
    "manifests": "ledger_release_manifests_tree_api",
}
RECORDER_REQUIRED_SURFACES = {
    "log": "log.json.gz",
    "ledger": "ledger.json.gz",
    "targets": "targets.json.gz",
    "reward": "reward.json.gz",
    "build": "build.json.gz",
    "apiBuild": "api-build.json.gz",
    "ledgerCommitApi": "ledger-commit.json.gz",
}
RECORDER_REQUIRED_LIVE = {
    "spm-child-poverty-2025": "live/spm-child-poverty-2025.json.gz",
    "cpi-u-annual-2026": "live/cpi-u-annual-2026.json.gz",
    "ctc-expansion-cost-ty2026": "live/ctc-expansion-cost-ty2026.json.gz",
    "ctc-current-law-outlays-ty2026": "live/ctc-current-law-outlays-ty2026.json.gz",
}


class CustodyError(ValueError):
    pass


@dataclass(frozen=True)
class CustodyVerification:
    run_mode: str
    custody_inventory_version: int
    inventory_status: str
    custody_root_sha256: str
    artifact_count: int
    run_succeeded: bool

    @property
    def headline_eligible(self) -> bool:
        return (
            self.run_mode == "analyst"
            and self.inventory_status == INVENTORY_STATUS_COMPLETE
            and self.run_succeeded
        )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def _json_bytes_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CustodyError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CustodyError(f"{label} must be a JSON object")
    return value


def _exact_object(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CustodyError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise CustodyError(
            f"{label} keys mismatch: missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )
    return value


def _git_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or GIT_SHA_RE.fullmatch(value) is None:
        raise CustodyError(f"{label} must be a 40-character lowercase Git SHA")
    return value


def _sha256_value(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise CustodyError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _optional_git_sha(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _git_sha(value, label)


def _tree_entries_from_archive(
    raw: bytes, expected_sha: str, label: str
) -> dict[str, dict[str, str]]:
    payload = _json_bytes_object(raw, label)
    actual_sha = _git_sha(payload.get("sha"), f"{label} SHA")
    if actual_sha != expected_sha:
        raise CustodyError(
            f"{label} identifies tree {actual_sha}, expected {expected_sha}"
        )
    if payload.get("truncated") is not False:
        raise CustodyError(f"{label} is truncated or lacks a completeness flag")
    raw_entries = payload.get("tree")
    if not isinstance(raw_entries, list):
        raise CustodyError(f"{label} lacks a tree entry list")
    entries: dict[str, dict[str, str]] = {}
    for number, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            raise CustodyError(f"{label} entry {number} is not an object")
        path = raw_entry.get("path")
        if not isinstance(path, str) or not path or path in {".", ".."} or "/" in path:
            raise CustodyError(
                f"{label} entry {number} is not a direct child: {path!r}"
            )
        if path in entries:
            raise CustodyError(f"{label} contains duplicate path {path!r}")
        object_type = raw_entry.get("type")
        mode = raw_entry.get("mode")
        if not isinstance(object_type, str) or not isinstance(mode, str):
            raise CustodyError(f"{label} entry {path!r} lacks type or mode")
        entries[path] = {
            "path": path,
            "mode": mode,
            "type": object_type,
            "sha": _git_sha(raw_entry.get("sha"), f"{label} entry {path!r} SHA"),
        }
    body = bytearray()
    for entry in entries.values():
        path = entry["path"]
        if "\0" in path:
            raise CustodyError(f"{label} contains a NUL path")
        mode = entry["mode"].lstrip("0") or "0"
        body.extend(f"{mode} {path}\0".encode("utf-8"))
        body.extend(bytes.fromhex(entry["sha"]))
    header = f"tree {len(body)}\0".encode("ascii")
    computed_sha = hashlib.sha1(header + body, usedforsecurity=False).hexdigest()
    if computed_sha != expected_sha:
        raise CustodyError(
            f"{label} entries hash to Git tree {computed_sha}, expected {expected_sha}"
        )
    return entries


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CustodyError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CustodyError(f"JSON record must be an object: {path}")
    return value


def _safe_relative(value: str) -> PurePosixPath:
    if not value or "\\" in value:
        raise CustodyError(f"invalid artifact path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise CustodyError(f"unsafe artifact path: {value!r}")
    if path.as_posix() != value:
        raise CustodyError(f"non-normalized artifact path: {value!r}")
    return path


def _safe_artifact_path(run_dir: Path, relative: str) -> Path:
    logical = _safe_relative(relative)
    path = run_dir.joinpath(*logical.parts)
    try:
        path.resolve().relative_to(run_dir.resolve())
    except ValueError as exc:
        raise CustodyError(f"artifact path escapes run directory: {relative}") from exc
    return path


def _manifest_relative(run_dir: Path, value: str, *, legacy: bool) -> str:
    segments = value.split("/")
    if (
        not value
        or "\\" in value
        or value.endswith("/")
        or any(segment in {".", ".."} for segment in segments)
        or any(not segment for segment in segments[1:])
    ):
        raise CustodyError(f"unsafe manifest artifact path: {value!r}")
    source = Path(value)
    candidates = []
    if source.is_absolute():
        candidates.append(source)
    else:
        candidates.extend([Path.cwd() / source, REPOSITORY_ROOT / source])
        candidates.extend(
            ancestor.parent / source
            for ancestor in run_dir.parents
            if ancestor.name == "records"
        )
        if not source.parts or source.parts[0] != "records":
            candidates.append(run_dir / source)
    for candidate in candidates:
        try:
            relative = candidate.resolve().relative_to(run_dir.resolve())
        except ValueError:
            continue
        return _safe_relative(relative.as_posix()).as_posix()
    if legacy:
        for index, part in enumerate(source.parts):
            if part != run_dir.name or index + 1 >= len(source.parts):
                continue
            relative = PurePosixPath(*source.parts[index + 1 :])
            candidate = run_dir.joinpath(*relative.parts)
            if candidate.exists():
                return _safe_relative(relative.as_posix()).as_posix()
        return _safe_relative(source.name).as_posix()
    raise CustodyError(f"manifest artifact path does not resolve inside run: {value!r}")


def _self_hash_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(manifest)
    payload.pop("custodyRootSha256", None)
    payload["artifacts"] = [
        artifact
        for artifact in payload.get("artifacts", [])
        if artifact.get("artifactType") != "manifest"
    ]
    return payload


def _regular_files(root: Path) -> set[str]:
    discovered: set[str] = set()
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        relative = path.relative_to(root).as_posix()
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode) or path.is_symlink():
            raise CustodyError(f"run contains a symlink or special file: {relative}")
        discovered.add(relative)
    return discovered


def _repository_artifact_path(run_dir: Path, value: str) -> Path:
    """Resolve a repository-relative cross-run reference beside ``run_dir``."""

    logical = _safe_relative(value)
    candidates = [REPOSITORY_ROOT.joinpath(*logical.parts)]
    candidates.extend(
        ancestor.parent.joinpath(*logical.parts)
        for ancestor in run_dir.parents
        if ancestor.name == "records"
    )
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise CustodyError(f"referenced repository artifact is missing: {value}")


def _instant(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CustodyError(f"invalid {label}: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CustodyError(f"{label} lacks a UTC offset: {value!r}")
    return parsed.astimezone(timezone.utc)


def _required(entries: list[dict[str, Any]], required: dict[str, str]) -> None:
    actual = {(str(entry["path"]), str(entry["artifactType"])) for entry in entries}
    absent = [
        f"{path} ({artifact_type})"
        for path, artifact_type in required.items()
        if (path, artifact_type) not in actual
    ]
    if absent:
        raise CustodyError(
            "run is missing required inventory artifacts: " + ", ".join(absent)
        )


def _command_backend(run_dir: Path, prefix: str = "") -> str:
    command = _load_object(run_dir / f"{prefix}command.json")
    backend = command.get("backend")
    if backend not in {
        "codex",
        "gemini_cli",
        "external_command",
        "response_file",
        "mock",
    }:
        raise CustodyError(f"v2 analyst command.json has invalid backend: {backend!r}")
    return str(backend)


def _prefixed(inventory: dict[str, str], prefix: str) -> dict[str, str]:
    return {
        f"{prefix}{path}": artifact_type for path, artifact_type in inventory.items()
    }


def _require_invocation_stage(
    run_dir: Path,
    entries: list[dict[str, Any]],
    *,
    prefix: str,
    stdout_artifact_type: str,
) -> set[str]:
    base = {
        f"{prefix}command.json": "command",
        f"{prefix}stdout.txt": stdout_artifact_type,
        f"{prefix}stderr.txt": "stderr",
    }
    _required(entries, base)
    codex = _prefixed(CODEX_STAGE_INVENTORY, prefix)
    gemini = _prefixed(GEMINI_STAGE_INVENTORY, prefix)
    paths = {str(entry["path"]) for entry in entries}
    backend = _command_backend(run_dir, prefix)
    if backend == "codex":
        _required(entries, codex)
        unexpected_gemini = sorted(paths & set(gemini))
        if unexpected_gemini:
            raise CustodyError(
                "Codex invocation contains Gemini trace artifacts: "
                + ", ".join(unexpected_gemini)
            )
        return {*base, *codex}
    if backend == "gemini_cli":
        _required(entries, gemini)
        unexpected_codex = sorted(paths & set(codex))
        if unexpected_codex:
            raise CustodyError(
                "Gemini invocation contains Codex trace artifacts: "
                + ", ".join(unexpected_codex)
            )
        return {*base, *gemini}
    unexpected_codex = sorted(paths & set(codex))
    if unexpected_codex:
        raise CustodyError(
            "non-Codex invocation contains Codex trace artifacts: "
            + ", ".join(unexpected_codex)
        )
    unexpected_gemini = sorted(paths & set(gemini))
    if unexpected_gemini:
        raise CustodyError(
            "non-Gemini invocation contains Gemini trace artifacts: "
            + ", ".join(unexpected_gemini)
        )
    return set(base)


def _verify_invocation_stages(
    run_dir: Path,
    manifest: dict[str, Any],
    entries: list[dict[str, Any]],
) -> set[str]:
    paths = {str(entry["path"]) for entry in entries}
    stage_suffixes = {
        "command.json",
        "stdout.txt",
        "stderr.txt",
        *CODEX_STAGE_INVENTORY,
        *GEMINI_STAGE_INVENTORY,
    }

    def has_stage(prefix: str) -> bool:
        return any(f"{prefix}{suffix}" in paths for suffix in stage_suffixes)

    has_draft = has_stage("draft_")
    has_review = has_stage("pre_submit_review_")
    has_final = has_stage("")
    if not any((has_draft, has_review, has_final)):
        raise CustodyError("analyst inventory contains no invocation stage")
    if has_review and not has_draft:
        raise CustodyError("reviewed inventory has reviewer stage without draft")
    if has_draft and has_final and not has_review:
        raise CustodyError("reviewed inventory has final stage without reviewer")
    allowed: set[str] = set()
    if has_draft:
        allowed.update(
            _require_invocation_stage(
                run_dir,
                entries,
                prefix="draft_",
                stdout_artifact_type="draft_forecast",
            )
        )
    if has_review:
        _required(entries, {"pre_submit_review_prompt.md": "review_prompt"})
        allowed.add("pre_submit_review_prompt.md")
        allowed.update(
            _require_invocation_stage(
                run_dir,
                entries,
                prefix="pre_submit_review_",
                stdout_artifact_type="pre_submit_review",
            )
        )
    if has_final:
        allowed.update(
            _require_invocation_stage(
                run_dir,
                entries,
                prefix="",
                stdout_artifact_type="stdout",
            )
        )
    if has_review and has_final:
        _required(entries, {"revision_prompt.md": "revision_prompt"})
        allowed.add("revision_prompt.md")
    if "pre_submit_review_prompt.md" in paths and not has_review:
        raise CustodyError("review prompt exists without a reviewer invocation")
    if "revision_prompt.md" in paths and not (has_review and has_final):
        raise CustodyError(
            "revision prompt exists without review and final invocations"
        )
    review = manifest.get("preSubmitReview")
    if isinstance(review, dict):
        status = review.get("status")
        expected = {
            "draft_failed": (True, False, False),
            "review_failed": (True, True, False),
            "revision_failed": (True, True, True),
            "completed": (True, True, True),
        }.get(status)
        if expected is None:
            raise CustodyError(f"unknown pre-submit review status: {status!r}")
        if (has_draft, has_review, has_final) != expected:
            raise CustodyError(
                f"pre-submit review stages disagree with status {status!r}"
            )
        if status in {"revision_failed", "completed"}:
            _required(entries, REVIEWED_STAGE_INVENTORY)
    # Parse-failure manifests are sealed before compact review metadata is
    # built; when metadata is absent, the rooted stage filenames are the
    # authoritative record of how far the invocation progressed.
    return allowed


def _verify_cells_activity(
    run_dir: Path, manifest_entries: list[dict[str, Any]], entries: list[dict[str, Any]]
) -> None:
    cells_path = run_dir / "cells.with_activity.json"
    try:
        cells = json.loads(cells_path.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CustodyError(f"invalid cells.with_activity.json: {exc}") from exc
    if not isinstance(cells, list) or not cells:
        raise CustodyError("cells.with_activity.json must be a nonempty list")
    expected = [
        ref
        for ref in manifest_entries
        if ref.get("artifactType") not in {"cells_with_activity", "manifest"}
    ]
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict) or cell.get("activityLog") != expected:
            raise CustodyError(
                f"cells.with_activity.json cell {index} does not expose the "
                "complete rooted activity prefix"
            )
    entry_paths = {str(entry["path"]) for entry in entries}
    if "cells.with_activity.json" not in entry_paths:
        raise CustodyError("cells.with_activity.json is not in the custody root")


def _verify_analyst_v2(
    run_dir: Path,
    manifest: dict[str, Any],
    manifest_entries: list[dict[str, Any]],
    entries: list[dict[str, Any]],
) -> None:
    if manifest.get("schemaVersion") != "thesis_analyst_run_manifest_v1":
        raise CustodyError("analyst custody mode has the wrong manifest schema")
    error_obj = manifest.get("error")
    declared_phase = (
        error_obj.get("phase") if isinstance(error_obj, dict) else None
    )
    presents_as_failed = (
        manifest.get("ok") is False
        and "validation" in manifest
        and manifest["validation"] is None
        and "cellsPath" in manifest
        and manifest["cellsPath"] is None
    )
    if declared_phase in {"parse", "normalize", "seal", "validate"}:
        # A failure phase on a run that otherwise presents as complete
        # would route it through the lighter failure inventories and let
        # it read as succeeded downstream. write_failure_manifest always
        # sets explicit ok:false / validation:null / cellsPath:null;
        # anything else — including omitted keys — is forgery or
        # corruption. The error artifact must also byte-agree with the
        # manifest under canonical encoding (Python == treats true and 1
        # as equal).
        if not presents_as_failed:
            raise CustodyError(
                "failure phase on a run that does not present as failed"
            )
        error_artifact = run_dir / "error.json"
        if not error_artifact.is_file() or canonical_bytes(
            json.loads(error_artifact.read_text())
        ) != canonical_bytes(manifest["error"]):
            raise CustodyError(
                f"{declared_phase}-failure error artifact disagrees with "
                "the manifest"
            )
    parse_failed = declared_phase == "parse"
    if parse_failed:
        base = {
            "prompt.md": "prompt",
            "raw_response.txt": "raw_response",
            "error.json": "error",
        }
        _required(entries, base)
        forbidden = {
            "parsed_cells.json",
            "normalized_cells.json",
            "distribution.json",
            "validation.json",
            "cells.with_activity.json",
        }
        present = {str(entry["path"]) for entry in entries}
        if forbidden & present:
            raise CustodyError("parse-failure inventory contains post-parse artifacts")
        allowed = {*base, *_verify_invocation_stages(run_dir, manifest, entries)}
        unexpected = sorted(present - allowed)
        if unexpected:
            raise CustodyError(
                "parse-failure inventory contains unexpected artifacts: "
                + ", ".join(unexpected)
            )
        return

    post_parse_failure = declared_phase in {"normalize", "seal", "validate"}
    if post_parse_failure:
        # A run whose agent produced parseable output that failed a later
        # harness stage must still be custody-verifiable: without these
        # inventories, registration-bound failure manifests were rejected
        # here and whole-wave publication blocked (the B1 rescue shape).
        # Each phase allows exactly the artifacts its stage had written.
        phase = manifest["error"]["phase"]
        base = {
            "prompt.md": "prompt",
            "raw_response.txt": "raw_response",
            "parsed_cells.json": "parsed_cell",
            "error.json": "error",
        }
        # Each phase REQUIRES exactly the artifacts its stage had
        # written, with their artifact types — pathname-only allowances
        # let a seal failure omit the normalized cells or relabel them.
        phase_required = {
            "normalize": {},
            "seal": {"normalized_cells.json": "normalized_cell"},
            "validate": {
                "normalized_cells.json": "normalized_cell",
                "distribution.json": "run_distribution",
            },
        }[phase]
        required = {**base, **phase_required}
        _required(entries, required)
        forbidden = {
            "cells.with_activity.json",
            "validation.json",
            "normalized_cells.json",
            "distribution.json",
        } - set(phase_required)
        present = {str(entry["path"]) for entry in entries}
        if forbidden & present:
            raise CustodyError(
                f"{phase}-failure inventory contains artifacts from later "
                "stages"
            )
        allowed = {
            *required,
            *_verify_invocation_stages(run_dir, manifest, entries),
        }
        unexpected = sorted(present - allowed)
        if unexpected:
            raise CustodyError(
                f"{phase}-failure inventory contains unexpected artifacts: "
                + ", ".join(unexpected)
            )
        return

    if manifest.get("validation") is None:
        raise CustodyError(
            "analyst v2 run is neither parse-failed nor validation-complete"
        )
    _required(entries, ANALYST_COMPLETED_INVENTORY)
    allowed = {
        *ANALYST_COMPLETED_INVENTORY,
        *_verify_invocation_stages(run_dir, manifest, entries),
    }
    review = manifest.get("preSubmitReview")
    if isinstance(review, dict) and review.get("status") == "completed":
        _required(entries, REVIEWED_STAGE_INVENTORY)
    if (
        manifest.get("ok")
        and isinstance(review, dict)
        and review.get("status") != "completed"
    ):
        raise CustodyError(
            "successful reviewed analyst run lacks a completed review inventory"
        )
    unexpected = sorted({str(entry["path"]) for entry in entries} - allowed)
    if unexpected:
        raise CustodyError(
            "completed analyst inventory contains unexpected artifacts: "
            + ", ".join(unexpected)
        )
    _verify_cells_activity(run_dir, manifest_entries, entries)


def _verify_resolver_v2(
    run_dir: Path, manifest: dict[str, Any], entries: list[dict[str, Any]]
) -> None:
    if manifest.get("schemaVersion") != "thesis_resolution_run_v1":
        raise CustodyError("resolver custody mode has the wrong manifest schema")
    facts = manifest.get("facts")
    if not isinstance(facts, list) or not facts:
        raise CustodyError("resolver inventory requires at least one fact")
    rooted_responses = {
        str(entry["path"])
        for entry in entries
        if RESOLVER_RESPONSE_RE.fullmatch(str(entry["path"]))
    }
    invalid_entries = [
        f"{entry['artifactType']}:{entry['path']}"
        for entry in entries
        if entry["artifactType"] != "resolver_response"
        or not RESOLVER_RESPONSE_RE.fullmatch(str(entry["path"]))
    ]
    if invalid_entries:
        raise CustodyError(
            "resolver inventory contains non-response artifacts: "
            + ", ".join(invalid_entries)
        )
    manifest_responses: set[str] = set()
    manifest_response_claims: dict[str, tuple] = {}
    for fact in facts:
        archive = fact.get("responseArchive") if isinstance(fact, dict) else None
        if not isinstance(archive, dict):
            raise CustodyError("resolver fact lacks responseArchive")
        declared = str(archive.get("path", ""))
        relative = _manifest_relative(run_dir, declared, legacy=False)
        if not RESOLVER_RESPONSE_RE.fullmatch(relative):
            raise CustodyError(
                "invalid resolver response archive path: "
                f"declared={declared!r}, resolved={relative!r}"
            )
        if relative in manifest_responses:
            # Several facts may share one archived response (two dataPointId
            # dialects of the same series resolve from the same vintage
            # bytes) — but every reference must declare identical hashes.
            prior = manifest_response_claims.get(relative)
            claim = (
                archive.get("sha256"),
                archive.get("gzipSha256"),
                archive.get("bytes"),
                archive.get("gzipBytes"),
            )
            if prior != claim:
                raise CustodyError(
                    f"conflicting resolver response declarations: {relative}"
                )
            continue
        if archive.get("contentEncoding") != "gzip":
            raise CustodyError(f"resolver response is not declared gzip: {relative}")
        path = _safe_artifact_path(run_dir, relative)
        compressed = path.read_bytes()
        if _sha256(compressed) != archive.get("gzipSha256") or len(
            compressed
        ) != archive.get("gzipBytes"):
            raise CustodyError(f"resolver compressed response mismatch: {relative}")
        try:
            raw = gzip.decompress(compressed)
        except (OSError, EOFError) as exc:
            raise CustodyError(
                f"invalid resolver gzip response {relative}: {exc}"
            ) from exc
        if _sha256(raw) != archive.get("sha256") or len(raw) != archive.get("bytes"):
            raise CustodyError(f"resolver decompressed response mismatch: {relative}")
        manifest_responses.add(relative)
        manifest_response_claims[relative] = (
            archive.get("sha256"),
            archive.get("gzipSha256"),
            archive.get("bytes"),
            archive.get("gzipBytes"),
        )
    if rooted_responses != manifest_responses:
        raise CustodyError(
            "resolver response inventory mismatch: "
            f"rooted={sorted(rooted_responses)}, "
            f"manifest={sorted(manifest_responses)}"
        )


def _named_ledger_archive(
    archives_by_name: dict[str, tuple[dict[str, Any], bytes, str]],
    name: str,
    role: str,
    label: str,
) -> tuple[dict[str, Any], bytes, str]:
    archived = archives_by_name.get(name)
    if archived is None:
        raise CustodyError(f"{label} archive {name!r} is missing")
    record, _raw, _relative = archived
    if record.get("role") != role:
        raise CustodyError(
            f"{label} archive {name!r} has role {record.get('role')!r}, "
            f"expected {role!r}"
        )
    return archived


def _require_ledger_tree_url(record: dict[str, Any], tree_sha: str, label: str) -> None:
    expected = {
        f"https://api.github.com/repos/{repo}/git/trees/{tree_sha}"
        for repo in LEDGER_REPO_ALIASES
    }
    if record.get("url") not in expected:
        raise CustodyError(f"{label} URL is not the exact immutable Git-tree URL")


def _verify_ledger_release_archive(
    manifest: dict[str, Any],
    archives_by_name: dict[str, tuple[dict[str, Any], bytes, str]],
    archives_by_role: dict[str, list[tuple[dict[str, Any], bytes, str]]],
) -> None:
    release_archive = _exact_object(
        manifest.get("releaseArchive"),
        {
            "schemaVersion",
            "directory",
            "commitTreeSha",
            "releasesTreeSha",
            "manifestsTreeSha",
            "treeArchiveNames",
            "fileCount",
            "files",
        },
        "ledger releaseArchive",
    )
    if release_archive["schemaVersion"] != LEDGER_RELEASE_ARCHIVE_V1:
        raise CustodyError(
            "ledger releaseArchive has unsupported schema "
            f"{release_archive['schemaVersion']!r}"
        )
    if release_archive["directory"] != LEDGER_RELEASE_DIRECTORY:
        raise CustodyError(
            f"ledger releaseArchive directory must be {LEDGER_RELEASE_DIRECTORY!r}"
        )

    commit_tree_sha = _git_sha(
        release_archive["commitTreeSha"], "releaseArchive commitTreeSha"
    )
    releases_tree_sha = _optional_git_sha(
        release_archive["releasesTreeSha"], "releaseArchive releasesTreeSha"
    )
    manifests_tree_sha = _optional_git_sha(
        release_archive["manifestsTreeSha"], "releaseArchive manifestsTreeSha"
    )
    tree_names = _exact_object(
        release_archive["treeArchiveNames"],
        {"commit", "releases", "manifests"},
        "releaseArchive treeArchiveNames",
    )
    for key, value in tree_names.items():
        if value is not None and (
            not isinstance(value, str) or ARCHIVE_NAME_RE.fullmatch(value) is None
        ):
            raise CustodyError(
                f"releaseArchive treeArchiveNames.{key} is not a safe archive name"
            )
    if not isinstance(tree_names["commit"], str):
        raise CustodyError("releaseArchive must name its commit-tree archive")

    branch_candidates = archives_by_role.get("ledger_branch_commit_api", [])
    if len(branch_candidates) != 1:
        raise CustodyError("ledger releaseArchive lacks one branch commit archive")
    branch_commit = _json_bytes_object(
        branch_candidates[0][1], "ledger branch commit archive"
    )
    commit = branch_commit.get("commit")
    commit_tree = commit.get("tree") if isinstance(commit, dict) else None
    claimed_commit_tree_sha = _git_sha(
        commit_tree.get("sha") if isinstance(commit_tree, dict) else None,
        "ledger branch commit tree SHA",
    )
    if claimed_commit_tree_sha != commit_tree_sha:
        raise CustodyError(
            "releaseArchive commitTreeSha does not match the archived branch commit"
        )

    expected_tree_counts = {
        LEDGER_RELEASE_TREE_ROLES["commit"]: 1,
        LEDGER_RELEASE_TREE_ROLES["releases"]: int(releases_tree_sha is not None),
        LEDGER_RELEASE_TREE_ROLES["manifests"]: int(manifests_tree_sha is not None),
    }
    for role, expected_count in expected_tree_counts.items():
        actual_count = len(archives_by_role.get(role, []))
        if actual_count != expected_count:
            raise CustodyError(
                f"ledger releaseArchive role {role!r} count is {actual_count}, "
                f"expected {expected_count}"
            )

    commit_record, commit_tree_raw, _ = _named_ledger_archive(
        archives_by_name,
        tree_names["commit"],
        LEDGER_RELEASE_TREE_ROLES["commit"],
        "commit tree",
    )
    if commit_record.get("gitTreeSha") != commit_tree_sha:
        raise CustodyError("commit-tree archive metadata SHA mismatch")
    _require_ledger_tree_url(commit_record, commit_tree_sha, "commit-tree archive")
    commit_entries = _tree_entries_from_archive(
        commit_tree_raw, commit_tree_sha, "archived commit tree"
    )

    releases_entry = commit_entries.get("releases")
    releases_entries: dict[str, dict[str, str]] = {}
    if releases_tree_sha is None:
        if releases_entry is not None:
            raise CustodyError(
                "releaseArchive omits the releases tree present in the commit tree"
            )
        if tree_names["releases"] is not None:
            raise CustodyError("releaseArchive names a nonexistent releases tree")
    else:
        if (
            releases_entry is None
            or releases_entry["type"] != "tree"
            or releases_entry["mode"] != "040000"
            or releases_entry["sha"] != releases_tree_sha
        ):
            raise CustodyError(
                "releaseArchive releasesTreeSha is not the commit tree's releases child"
            )
        if not isinstance(tree_names["releases"], str):
            raise CustodyError("releaseArchive omits the releases-tree archive name")
        releases_record, releases_raw, _ = _named_ledger_archive(
            archives_by_name,
            tree_names["releases"],
            LEDGER_RELEASE_TREE_ROLES["releases"],
            "releases tree",
        )
        if releases_record.get("gitTreeSha") != releases_tree_sha:
            raise CustodyError("releases-tree archive metadata SHA mismatch")
        _require_ledger_tree_url(
            releases_record,
            releases_tree_sha,
            "releases-tree archive",
        )
        releases_entries = _tree_entries_from_archive(
            releases_raw, releases_tree_sha, "archived releases tree"
        )

    manifests_entry = releases_entries.get("manifests")
    manifest_entries: dict[str, dict[str, str]] = {}
    if manifests_tree_sha is None:
        if manifests_entry is not None:
            raise CustodyError(
                "releaseArchive omits the manifests tree present in releases"
            )
        if tree_names["manifests"] is not None:
            raise CustodyError("releaseArchive names a nonexistent manifests tree")
    else:
        if releases_tree_sha is None:
            raise CustodyError("releaseArchive has manifests without a releases tree")
        if (
            manifests_entry is None
            or manifests_entry["type"] != "tree"
            or manifests_entry["mode"] != "040000"
            or manifests_entry["sha"] != manifests_tree_sha
        ):
            raise CustodyError(
                "releaseArchive manifestsTreeSha is not the releases tree's "
                "manifests child"
            )
        if not isinstance(tree_names["manifests"], str):
            raise CustodyError("releaseArchive omits the manifests-tree archive name")
        manifests_record, manifests_raw, _ = _named_ledger_archive(
            archives_by_name,
            tree_names["manifests"],
            LEDGER_RELEASE_TREE_ROLES["manifests"],
            "release manifests tree",
        )
        if manifests_record.get("gitTreeSha") != manifests_tree_sha:
            raise CustodyError("manifests-tree archive metadata SHA mismatch")
        _require_ledger_tree_url(
            manifests_record,
            manifests_tree_sha,
            "manifests-tree archive",
        )
        manifest_entries = _tree_entries_from_archive(
            manifests_raw, manifests_tree_sha, "archived release manifests tree"
        )

    raw_files = release_archive["files"]
    file_count = release_archive["fileCount"]
    if type(file_count) is not int or file_count < 0:
        raise CustodyError("releaseArchive fileCount must be a non-negative integer")
    if not isinstance(raw_files, list) or len(raw_files) != file_count:
        raise CustodyError("releaseArchive files do not match fileCount")

    files_by_basename: dict[str, dict[str, Any]] = {}
    archive_names: set[str] = set()
    paths: list[str] = []
    for number, raw_file in enumerate(raw_files, start=1):
        file_record = _exact_object(
            raw_file,
            {"path", "gitBlobSha", "sha256", "bytes", "archiveName"},
            f"releaseArchive file {number}",
        )
        source_path = file_record["path"]
        if not isinstance(source_path, str):
            raise CustodyError(f"releaseArchive file {number} path must be a string")
        source = PurePosixPath(source_path)
        expected_source_path = f"{LEDGER_RELEASE_DIRECTORY}/{source.name}"
        if (
            source_path != expected_source_path
            or "\\" in source_path
            or "\x00" in source_path
            or source.name in {"", ".", ".."}
        ):
            raise CustodyError(
                f"releaseArchive file {number} is not a canonical direct manifest child"
            )
        basename = source.name
        if basename in files_by_basename:
            raise CustodyError(f"duplicate releaseArchive file {source_path!r}")
        _git_sha(
            file_record["gitBlobSha"],
            f"releaseArchive file {source_path} Git SHA",
        )
        _sha256_value(
            file_record["sha256"],
            f"releaseArchive file {source_path} SHA-256",
        )
        if type(file_record["bytes"]) is not int or file_record["bytes"] < 0:
            raise CustodyError(
                f"releaseArchive file {source_path} bytes must be non-negative"
            )
        archive_name = file_record["archiveName"]
        if (
            not isinstance(archive_name, str)
            or ARCHIVE_NAME_RE.fullmatch(archive_name) is None
            or archive_name in archive_names
        ):
            raise CustodyError(
                f"releaseArchive file {source_path} has an invalid archiveName"
            )
        archive_names.add(archive_name)
        files_by_basename[basename] = file_record
        paths.append(source_path)
    if paths != sorted(paths):
        raise CustodyError("releaseArchive files must be sorted by source path")
    if set(files_by_basename) != set(manifest_entries):
        raise CustodyError(
            "releaseArchive file inventory does not equal the manifests Git tree"
        )

    branch_sha = str(manifest.get("ledgerBranchSha", ""))
    repo = str(manifest.get("ledgerRepo", ""))
    for basename, entry in manifest_entries.items():
        if entry["type"] != "blob" or entry["mode"] not in {"100644", "100755"}:
            raise CustodyError(
                f"release manifests tree entry {basename!r} is not a regular blob"
            )
        file_record = files_by_basename[basename]
        source_path = file_record["path"]
        if file_record["gitBlobSha"] != entry["sha"]:
            raise CustodyError(
                f"releaseArchive Git blob SHA mismatch for {source_path}"
            )
        archive_name = file_record["archiveName"]
        upstream_record, raw, _ = _named_ledger_archive(
            archives_by_name,
            archive_name,
            "ledger_release_file",
            f"release file {source_path}",
        )
        if (
            upstream_record.get("sourcePath") != source_path
            or upstream_record.get("gitBlobSha") != entry["sha"]
        ):
            raise CustodyError(
                f"release file archive metadata mismatch for {source_path}"
            )
        expected_url = (
            f"https://raw.githubusercontent.com/{repo}/{branch_sha}/"
            f"{urllib.parse.quote(source_path, safe='/')}"
        )
        if upstream_record.get("url") != expected_url:
            raise CustodyError(
                f"release file URL is not pinned to the branch SHA: {source_path}"
            )
        if (
            _git_blob_sha(raw) != entry["sha"]
            or _sha256(raw) != file_record["sha256"]
            or len(raw) != file_record["bytes"]
        ):
            raise CustodyError(f"release file bytes mismatch for {source_path}")

    actual_release_archives = {
        str(record.get("name"))
        for record, _raw, _relative in archives_by_role.get("ledger_release_file", [])
    }
    if actual_release_archives != archive_names:
        raise CustodyError(
            "ledger release file archives do not equal releaseArchive inventory"
        )


def _verify_ledger_witness_v2(
    run_dir: Path, manifest: dict[str, Any], entries: list[dict[str, Any]]
) -> None:
    schema_version = manifest.get("schemaVersion")
    if schema_version not in {LEDGER_WITNESS_V1, LEDGER_WITNESS_V2}:
        raise CustodyError("ledger witness custody mode has the wrong manifest schema")
    if schema_version == LEDGER_WITNESS_V2 and "releaseArchive" not in manifest:
        raise CustodyError("ledger witness v2 manifest lacks releaseArchive")
    if schema_version == LEDGER_WITNESS_V2:
        if manifest.get("ledgerRepo") not in LEDGER_REPO_ALIASES:
            raise CustodyError(
                f"ledger witness v2 repo must be one of {LEDGER_REPO_ALIASES!r}"
            )
        if manifest.get("ledgerBranch") != LEDGER_BRANCH:
            raise CustodyError(
                f"ledger witness v2 branch must be exactly {LEDGER_BRANCH!r}"
            )
        branch_sha = _git_sha(
            manifest.get("ledgerBranchSha"), "ledger witness branch SHA"
        )
        main_sha = _git_sha(manifest.get("ledgerMainSha"), "ledger witness main SHA")
    else:
        branch_sha = str(manifest.get("ledgerBranchSha", ""))
        main_sha = str(manifest.get("ledgerMainSha", ""))
    upstream = manifest.get("upstream")
    if not isinstance(upstream, list) or not upstream:
        raise CustodyError("ledger witness inventory requires an upstream archive")
    invalid_entries = [
        f"{entry['artifactType']}:{entry['path']}"
        for entry in entries
        if entry["artifactType"] != "upstream_archive"
        or not LEDGER_WITNESS_ARCHIVE_RE.fullmatch(str(entry["path"]))
    ]
    if invalid_entries:
        raise CustodyError(
            "ledger witness inventory contains non-upstream artifacts: "
            + ", ".join(invalid_entries)
        )
    rooted_archives = {str(entry["path"]) for entry in entries}
    jsonl_claim = manifest.get("jsonl")
    if not isinstance(jsonl_claim, dict):
        raise CustodyError("ledger witness manifest lacks a jsonl commitment")
    catalog_declared = "catalog" in manifest
    catalog_claim: dict[str, Any] | None = None
    if catalog_declared:
        catalog_claim = _exact_object(
            manifest.get("catalog"),
            {"sha256", "bytes"},
            "ledger witness catalog commitment",
        )
        _sha256_value(
            catalog_claim["sha256"],
            "ledger witness catalog commitment SHA-256",
        )
        if type(catalog_claim["bytes"]) is not int or catalog_claim["bytes"] < 0:
            raise CustodyError(
                "ledger witness catalog bytes must be a non-negative integer"
            )
    manifest_archives: set[str] = set()
    observations_witnessed = False
    catalog_witnessed = False
    roles_seen: dict[str, int] = {}
    archives_by_name: dict[str, tuple[dict[str, Any], bytes, str]] = {}
    archives_by_role: dict[str, list[tuple[dict[str, Any], bytes, str]]] = {}
    for record in upstream:
        archive = record.get("archive") if isinstance(record, dict) else None
        if not isinstance(archive, dict):
            raise CustodyError("ledger witness record lacks an archive")
        declared = str(archive.get("path", ""))
        relative = _manifest_relative(run_dir, declared, legacy=False)
        if not LEDGER_WITNESS_ARCHIVE_RE.fullmatch(relative):
            raise CustodyError(
                "invalid ledger witness archive path: "
                f"declared={declared!r}, resolved={relative!r}"
            )
        if relative in manifest_archives:
            raise CustodyError(f"duplicate ledger witness archive: {relative}")
        if archive.get("contentEncoding") != "gzip":
            raise CustodyError(
                f"ledger witness archive is not declared gzip: {relative}"
            )
        path = _safe_artifact_path(run_dir, relative)
        compressed = path.read_bytes()
        if _sha256(compressed) != archive.get("gzipSha256") or len(
            compressed
        ) != archive.get("gzipBytes"):
            raise CustodyError(
                f"ledger witness compressed archive mismatch: {relative}"
            )
        try:
            raw = gzip.decompress(compressed)
        except (OSError, EOFError) as exc:
            raise CustodyError(
                f"invalid ledger witness gzip archive {relative}: {exc}"
            ) from exc
        if _sha256(raw) != archive.get("sha256") or len(raw) != archive.get("bytes"):
            raise CustodyError(
                f"ledger witness decompressed archive mismatch: {relative}"
            )
        name = record.get("name")
        if (
            not isinstance(name, str)
            or ARCHIVE_NAME_RE.fullmatch(name) is None
            or name in archives_by_name
        ):
            raise CustodyError(
                f"invalid or duplicate ledger witness archive name: {name!r}"
            )
        role = str(record.get("role", ""))
        roles_seen[role] = roles_seen.get(role, 0) + 1
        archived = (record, raw, relative)
        archives_by_name[name] = archived
        archives_by_role.setdefault(role, []).append(archived)
        # The archived commit-API responses must actually identify the SHAs
        # the manifest claims, and the observations archive must be the file
        # at the branch SHA — otherwise a witness can hash an internally
        # consistent but contradictory bundle (finding 11).
        if role == "ledger_branch_commit_api":
            _require_commit_response(raw, branch_sha, relative)
            if schema_version == LEDGER_WITNESS_V2 and record.get("url") not in {
                f"https://api.github.com/repos/{repo}/commits/{branch_sha}"
                for repo in LEDGER_REPO_ALIASES
            }:
                raise CustodyError(
                    "ledger witness branch-commit URL is not the exact "
                    "immutable API URL"
                )
        elif role == "ledger_main_commit_api":
            _require_commit_response(raw, main_sha, relative)
            if schema_version == LEDGER_WITNESS_V2 and record.get("url") not in {
                f"https://api.github.com/repos/{repo}/commits/{main_sha}"
                for repo in LEDGER_REPO_ALIASES
            }:
                raise CustodyError(
                    "ledger witness main-commit URL is not the exact immutable API URL"
                )
        elif role == "official_observations_jsonl":
            url = str(record.get("url", ""))
            expected_urls = {
                f"https://raw.githubusercontent.com/{repo}/{branch_sha}/"
                f"{LEDGER_JSONL_PATH}"
                for repo in LEDGER_REPO_ALIASES
            }
            if schema_version == LEDGER_WITNESS_V2 and url not in expected_urls:
                raise CustodyError(
                    "ledger witness observations URL is not the exact immutable URL: "
                    f"{url!r}"
                )
            if (
                schema_version != LEDGER_WITNESS_V2
                and branch_sha
                and branch_sha not in url
            ):
                raise CustodyError(
                    "ledger witness observations URL does not pin the branch "
                    f"SHA {branch_sha}: {url!r}"
                )
        elif role == "series_catalog_json":
            url = str(record.get("url", ""))
            expected_urls = {
                f"https://raw.githubusercontent.com/{repo}/{branch_sha}/"
                f"{LEDGER_CATALOG_PATH}"
                for repo in LEDGER_REPO_ALIASES
            }
            if schema_version == LEDGER_WITNESS_V2 and url not in expected_urls:
                raise CustodyError(
                    "ledger witness catalog URL is not the exact immutable URL: "
                    f"{url!r}"
                )
            if (
                schema_version != LEDGER_WITNESS_V2
                and branch_sha
                and branch_sha not in url
            ):
                raise CustodyError(
                    "ledger witness catalog URL does not pin the branch "
                    f"SHA {branch_sha}: {url!r}"
                )
        if record.get("role") == "official_observations_jsonl":
            observations_witnessed = True
            lines = [line for line in raw.decode("utf-8").splitlines() if line.strip()]
            if type(jsonl_claim.get("bytes")) is not int or jsonl_claim["bytes"] < 0:
                raise CustodyError(
                    "ledger witness jsonl bytes must be a non-negative integer"
                )
            if len(raw) != jsonl_claim["bytes"]:
                raise CustodyError(
                    "ledger witness jsonl byte count mismatch: "
                    f"expected {jsonl_claim['bytes']}, got {len(raw)}"
                )
            if len(lines) != jsonl_claim.get("lineCount"):
                raise CustodyError(
                    "ledger witness jsonl line count mismatch: "
                    f"expected {jsonl_claim.get('lineCount')}, got {len(lines)}"
                )
            if _sha256(raw) != jsonl_claim.get("sha256"):
                raise CustodyError("ledger witness jsonl commitment hash mismatch")
            seen_ids: set[str] = set()
            for number, line in enumerate(lines, start=1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise CustodyError(
                        f"ledger witness jsonl line {number} is invalid: {exc}"
                    ) from exc
                record_id = (
                    row.get("source_record_id") if isinstance(row, dict) else None
                )
                if not record_id:
                    raise CustodyError(
                        f"ledger witness jsonl line {number} lacks source_record_id"
                    )
                seen_ids.add(str(record_id))
            if len(seen_ids) != jsonl_claim.get("sourceRecordIdCount"):
                raise CustodyError(
                    "ledger witness jsonl source_record_id count mismatch: "
                    f"expected {jsonl_claim.get('sourceRecordIdCount')}, "
                    f"got {len(seen_ids)}"
                )
        elif record.get("role") == "series_catalog_json":
            if catalog_claim is None:
                raise CustodyError(
                    "ledger witness catalog archive lacks a manifest commitment"
                )
            catalog_witnessed = True
            if len(raw) != catalog_claim["bytes"]:
                raise CustodyError(
                    "ledger witness catalog byte count mismatch: "
                    f"expected {catalog_claim['bytes']}, got {len(raw)}"
                )
            if _sha256(raw) != catalog_claim["sha256"]:
                raise CustodyError("ledger witness catalog commitment hash mismatch")
            catalog_payload = _json_bytes_object(raw, "ledger series catalog")
            if not isinstance(catalog_payload.get("series"), list):
                raise CustodyError("ledger series catalog lacks a series array")
            if catalog_payload.get("observations_sha256") != jsonl_claim.get("sha256"):
                raise CustodyError(
                    "ledger series catalog observations_sha256 does not match "
                    "the witnessed JSONL"
                )
            if type(
                catalog_payload.get("observation_rows")
            ) is not int or catalog_payload["observation_rows"] != jsonl_claim.get(
                "lineCount"
            ):
                raise CustodyError(
                    "ledger series catalog observation_rows does not match "
                    "the witnessed JSONL"
                )
        manifest_archives.add(relative)
    if not observations_witnessed:
        raise CustodyError(
            "ledger witness run does not witness official_observations.jsonl"
        )
    if catalog_declared and not catalog_witnessed:
        raise CustodyError("ledger witness run does not witness series_catalog.json")
    expected_role_counts = {
        "official_observations_jsonl": 1,
        "ledger_branch_commit_api": 1,
        "ledger_main_commit_api": 1,
        "series_catalog_json": int(catalog_declared),
    }
    for required_role, expected_count in expected_role_counts.items():
        if roles_seen.get(required_role, 0) != expected_count:
            raise CustodyError(
                f"ledger witness must carry exactly {expected_count} "
                f"{required_role} archive(s), found "
                f"{roles_seen.get(required_role, 0)}"
            )
    if rooted_archives != manifest_archives:
        raise CustodyError(
            "ledger witness archive inventory mismatch: "
            f"rooted={sorted(rooted_archives)}, "
            f"manifest={sorted(manifest_archives)}"
        )
    if schema_version == LEDGER_WITNESS_V2 or "releaseArchive" in manifest:
        _verify_ledger_release_archive(
            manifest,
            archives_by_name,
            archives_by_role,
        )


def _require_commit_response(raw: bytes, expected_sha: str, relative: str) -> None:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CustodyError(
            f"ledger witness commit archive {relative} is not JSON: {exc}"
        ) from exc
    actual = str(payload.get("sha", "")) if isinstance(payload, dict) else ""
    if not expected_sha or actual != expected_sha:
        raise CustodyError(
            f"ledger witness commit archive {relative} identifies {actual!r}, "
            f"not the manifest's claimed SHA {expected_sha!r}"
        )


def _verify_sba_fetch_record(
    value: Any,
    *,
    label: str,
    expected_url: str | None,
) -> dict[str, Any]:
    from witness_sba_pdf import ALLOWED_HOSTS, SbaCaptureError, _official_url

    record = _exact_object(
        value,
        {
            "requestedUrl",
            "redirects",
            "finalUrl",
            "status",
            "contentType",
            "headers",
            "outcome",
            "bodySha256",
            "bodyBytes",
            "error",
        },
        label,
    )
    requested = record["requestedUrl"]
    if not isinstance(requested, str) or (
        expected_url is not None and requested != expected_url
    ):
        raise CustodyError(f"{label} requested URL mismatch: {requested!r}")
    try:
        _official_url(requested, label=f"{label} requested URL")
    except SbaCaptureError as exc:
        raise CustodyError(str(exc)) from exc

    headers = record["headers"]
    if not isinstance(headers, dict) or not all(
        isinstance(name, str) and isinstance(item, str)
        for name, item in headers.items()
    ):
        raise CustodyError(f"{label} headers must be a string map")
    allowed_headers = {
        "Date",
        "Location",
        "Content-Type",
        "Content-Length",
        "ETag",
        "Last-Modified",
    }
    if not set(headers).issubset(allowed_headers):
        raise CustodyError(f"{label} contains unapproved retained headers")
    if record["contentType"] != headers.get("Content-Type"):
        raise CustodyError(f"{label} contentType disagrees with retained headers")

    redirects = record["redirects"]
    if not isinstance(redirects, list) or len(redirects) > 10:
        raise CustodyError(f"{label} redirects must be a bounded list")
    current = requested
    escaped = False
    for index, raw_hop in enumerate(redirects):
        if escaped:
            raise CustodyError(f"{label} continued fetching after a host escape")
        hop = _exact_object(
            raw_hop,
            {"sourceUrl", "status", "location", "targetUrl", "headers"},
            f"{label} redirect {index}",
        )
        if hop["sourceUrl"] != current or hop["status"] not in {
            301,
            302,
            303,
            307,
            308,
        }:
            raise CustodyError(f"{label} redirect {index} breaks the recorded chain")
        if not isinstance(hop["location"], str) or not isinstance(
            hop["targetUrl"], str
        ):
            raise CustodyError(f"{label} redirect {index} URL fields are invalid")
        target = urllib.parse.urljoin(current, hop["location"])
        if target != hop["targetUrl"]:
            raise CustodyError(f"{label} redirect {index} target mismatch")
        hop_headers = hop["headers"]
        if not isinstance(hop_headers, dict) or not all(
            isinstance(name, str) and isinstance(item, str)
            for name, item in hop_headers.items()
        ):
            raise CustodyError(f"{label} redirect {index} headers are invalid")
        if not set(hop_headers).issubset(allowed_headers):
            raise CustodyError(f"{label} redirect {index} contains unapproved headers")
        try:
            _official_url(target, label=f"{label} redirect target")
        except SbaCaptureError:
            escaped = True
            if index != len(redirects) - 1:
                raise CustodyError(
                    f"{label} continued redirecting after an off-host target"
                )
        current = target

    outcome = record["outcome"]
    if outcome not in {"success", "failed"}:
        raise CustodyError(f"{label} has invalid outcome {outcome!r}")
    final_url = record["finalUrl"]
    if final_url is not None and not isinstance(final_url, str):
        raise CustodyError(f"{label} final URL must be a string or null")
    if final_url != current:
        raise CustodyError(f"{label} final URL disagrees with the redirect chain")
    status = record["status"]
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        raise CustodyError(f"{label} HTTP status is invalid")
    body_sha = record["bodySha256"]
    body_bytes = record["bodyBytes"]
    if (body_sha is None) != (body_bytes is None):
        raise CustodyError(f"{label} body hash and byte count must appear together")
    if body_sha is not None:
        _sha256_value(body_sha, f"{label} body SHA-256")
        if type(body_bytes) is not int or body_bytes < 0:
            raise CustodyError(f"{label} body byte count is invalid")
    error = record["error"]
    if error is not None and (not isinstance(error, str) or not error):
        raise CustodyError(f"{label} error must be a nonempty string or null")
    if outcome == "success":
        if escaped or status != 200 or error is not None or body_sha is None:
            raise CustodyError(f"{label} success claim is internally inconsistent")
        try:
            assert final_url is not None
            parsed = _official_url(final_url, label=f"{label} final URL")
        except (AssertionError, SbaCaptureError) as exc:
            raise CustodyError(f"{label} final URL is not approved") from exc
        if parsed.hostname not in ALLOWED_HOSTS:
            raise CustodyError(f"{label} final URL host is not approved")
    elif error is None:
        raise CustodyError(f"{label} failed outcome lacks an error")
    if escaped and (
        outcome != "failed" or "outside the SBA allowlist" not in str(error)
    ):
        raise CustodyError(f"{label} host escape was not recorded as a refusal")
    return record


def _verify_sba_archive(
    run_dir: Path,
    value: Any,
    *,
    expected_path: str,
    label: str,
) -> tuple[bytes, bytes]:
    archive = _exact_object(
        value,
        {
            "path",
            "rawSha256",
            "rawBytes",
            "gzipSha256",
            "gzipBytes",
            "contentEncoding",
        },
        label,
    )
    if archive["path"] != expected_path or archive["contentEncoding"] != "gzip":
        raise CustodyError(f"{label} has the wrong path or content encoding")
    compressed = _safe_artifact_path(run_dir, expected_path).read_bytes()
    if (
        _sha256(compressed) != archive["gzipSha256"]
        or len(compressed) != archive["gzipBytes"]
    ):
        raise CustodyError(f"{label} deterministic-gzip commitment mismatch")
    try:
        raw = gzip.decompress(compressed)
    except (OSError, EOFError) as exc:
        raise CustodyError(f"{label} is not valid gzip") from exc
    if _sha256(raw) != archive["rawSha256"] or len(raw) != archive["rawBytes"]:
        raise CustodyError(f"{label} raw-byte commitment mismatch")
    if (
        len(compressed) < 10
        or compressed[:3] != b"\x1f\x8b\x08"
        or compressed[3] != 0
        or compressed[4:8] != b"\x00\x00\x00\x00"
    ):
        raise CustodyError(f"{label} lacks the reviewed zero-mtime gzip header")
    return raw, compressed


def _verify_sba_event_archive(
    run_dir: Path,
    fetch: dict[str, Any],
    *,
    path: str,
    label: str,
) -> bytes:
    compressed = _safe_artifact_path(run_dir, path).read_bytes()
    try:
        raw = gzip.decompress(compressed)
    except (OSError, EOFError) as exc:
        raise CustodyError(f"{label} is not valid gzip") from exc
    if (
        len(compressed) < 10
        or compressed[:3] != b"\x1f\x8b\x08"
        or compressed[3] != 0
        or compressed[4:8] != b"\x00\x00\x00\x00"
    ):
        raise CustodyError(f"{label} lacks the reviewed zero-mtime gzip header")
    if _sha256(raw) != fetch["bodySha256"] or len(raw) != fetch["bodyBytes"]:
        raise CustodyError(f"{label} disagrees with its structured fetch event")
    return raw


def _verify_sba_pdf_witness_v2(
    run_dir: Path, manifest: dict[str, Any], entries: list[dict[str, Any]]
) -> None:
    from witness_sba_pdf import (
        _REPORT_PREFIXES,
        _RUN_RE,
        ALLOWED_HOSTS,
        CAPTURE_REFUSAL,
        ENTRY_URL,
        PARSER_CONTRACT,
        SbaCaptureError,
        _captured_bundle,
        _inspect_bundle,
        _linked_bundle,
        _period_coverage,
    )

    _exact_object(
        manifest,
        {
            "schemaVersion",
            "retrievedAt",
            "source",
            "outcome",
            "ok",
            "fetchEventPath",
            "bundle",
            "previousCompleteCapture",
            "failure",
            "custodyInventoryVersion",
            "runMode",
            "manifestHashSemantics",
            "artifacts",
            "custodyRootSha256",
        },
        "SBA PDF witness manifest",
    )
    if manifest["schemaVersion"] != SBA_PDF_WITNESS_V1:
        raise CustodyError("SBA PDF witness custody mode has the wrong schema")
    retrieved_at = str(manifest["retrievedAt"])
    retrieved = _instant(retrieved_at, "SBA PDF witness retrievedAt")
    expected_run_name = retrieved.strftime("%Y%m%dT%H%M%SZ-sba-pdf-witness")
    if (
        _RUN_RE.fullmatch(run_dir.name) is None
        or run_dir.name != expected_run_name
        or run_dir.parent.name != retrieved.date().isoformat()
    ):
        raise CustodyError("SBA PDF witness run path disagrees with retrievedAt")
    source = _exact_object(
        manifest["source"],
        {"entryUrl", "allowedHosts", "requiredSeries", "parserContract"},
        "SBA PDF witness source",
    )
    if source != {
        "entryUrl": ENTRY_URL,
        "allowedHosts": list(ALLOWED_HOSTS),
        "requiredSeries": list(_REPORT_PREFIXES),
        "parserContract": PARSER_CONTRACT,
    }:
        raise CustodyError("SBA PDF witness source contract mismatch")
    if manifest["fetchEventPath"] != "fetch_event.json":
        raise CustodyError("SBA PDF witness has the wrong fetch-event path")
    event = _json_bytes_object(
        (run_dir / "fetch_event.json").read_bytes(), "SBA PDF fetch event"
    )
    event = _exact_object(
        event,
        {"schemaVersion", "attemptedAt", "outcome", "landing", "asset", "failure"},
        "SBA PDF fetch event",
    )
    if (
        event["schemaVersion"] != SBA_PDF_FETCH_EVENT_V1
        or event["attemptedAt"] != retrieved_at
        or event["outcome"] != manifest["outcome"]
        or event["failure"] != manifest["failure"]
    ):
        raise CustodyError("SBA PDF fetch event disagrees with its manifest")
    landing = _verify_sba_fetch_record(
        event["landing"], label="SBA landing fetch", expected_url=ENTRY_URL
    )
    asset = (
        _verify_sba_fetch_record(
            event["asset"], label="SBA asset fetch", expected_url=None
        )
        if event["asset"] is not None
        else None
    )

    outcome = manifest["outcome"]
    if outcome not in {"bootstrap", "changed", "unchanged", "failed"}:
        raise CustodyError(f"invalid SBA PDF witness outcome {outcome!r}")
    expected_artifacts = {"fetch_event.json": "fetch_event"}
    landing_raw: bytes | None = None
    if landing["bodySha256"] is not None:
        expected_artifacts["upstream/landing-page.html.gz"] = "landing_archive"
        landing_raw = _verify_sba_event_archive(
            run_dir,
            landing,
            path="upstream/landing-page.html.gz",
            label="SBA landing event archive",
        )
    retained_failed_bundle = outcome == "failed" and isinstance(
        manifest["bundle"], dict
    )
    if outcome in {"bootstrap", "changed"} or retained_failed_bundle:
        expected_artifacts["upstream/loan-program-performance.zip.gz"] = (
            "bundle_archive"
        )
    actual_artifacts = {
        str(entry["path"]): str(entry["artifactType"]) for entry in entries
    }
    if actual_artifacts != expected_artifacts:
        raise CustodyError(
            "SBA PDF witness artifact inventory mismatch: "
            f"expected={expected_artifacts}, got={actual_artifacts}"
        )

    if outcome in {"bootstrap", "changed"}:
        if manifest["ok"] is not True or manifest["failure"] is not None:
            raise CustodyError("complete SBA capture has an invalid success state")
        if manifest["previousCompleteCapture"] is not None:
            raise CustodyError("complete SBA capture must not embed a prior reference")
        if (
            landing["outcome"] != "success"
            or asset is None
            or asset["outcome"] != "success"
        ):
            raise CustodyError("complete SBA capture requires two successful fetches")
        bundle = _exact_object(
            manifest["bundle"],
            {
                "label",
                "fiscalYear",
                "quarter",
                "assetUrl",
                "rawSha256",
                "rawBytes",
                "periodCoverage",
                "reportAsOf",
                "memberInventory",
                "reports",
                "parserContract",
                "landingArchive",
                "zipArchive",
            },
            "SBA complete bundle",
        )
        archived_landing_raw, _ = _verify_sba_archive(
            run_dir,
            bundle["landingArchive"],
            expected_path="upstream/landing-page.html.gz",
            label="SBA landing archive",
        )
        zip_raw, _ = _verify_sba_archive(
            run_dir,
            bundle["zipArchive"],
            expected_path="upstream/loan-program-performance.zip.gz",
            label="SBA ZIP archive",
        )
        if (
            landing_raw is None
            or archived_landing_raw != landing_raw
            or asset["bodySha256"] != _sha256(zip_raw)
            or asset["bodyBytes"] != len(zip_raw)
        ):
            raise CustodyError("SBA fetch event body commitments do not replay")
        assert isinstance(landing["finalUrl"], str)
        try:
            identity = _linked_bundle(landing_raw, page_url=landing["finalUrl"])
            if asset["requestedUrl"] != identity.linked_url:
                raise CustodyError(
                    "SBA ZIP was not fetched from the archived page link"
                )
            replayed = _inspect_bundle(zip_raw, identity=identity)
        except SbaCaptureError as exc:
            raise CustodyError(f"SBA bundle replay refused: {exc}") from exc
        claimed = {
            name: value
            for name, value in bundle.items()
            if name not in {"landingArchive", "zipArchive"}
        }
        if claimed != replayed:
            raise CustodyError("SBA bundle manifest does not match strict replay")
    elif outcome == "unchanged":
        if (
            manifest["ok"] is not True
            or manifest["failure"] is not None
            or landing["outcome"] != "success"
            or asset is None
            or asset["outcome"] != "success"
        ):
            raise CustodyError("unchanged SBA capture has an invalid success state")
        bundle = _exact_object(
            manifest["bundle"],
            {
                "label",
                "fiscalYear",
                "quarter",
                "assetUrl",
                "rawSha256",
                "rawBytes",
                "periodCoverage",
                "reportAsOf",
                "parserContract",
            },
            "SBA unchanged bundle",
        )
        previous = _exact_object(
            manifest["previousCompleteCapture"],
            {
                "runDirectory",
                "custodyRootPath",
                "custodyRootSha256",
                "bundleSha256",
                "bundleBytes",
                "bundleLabel",
                "reportAsOf",
            },
            "SBA prior complete capture",
        )
        root_path = _repository_artifact_path(run_dir, str(previous["custodyRootPath"]))
        expected_run = _safe_relative(str(previous["runDirectory"]))
        records_root = next(
            (ancestor for ancestor in run_dir.parents if ancestor.name == "records"),
            None,
        )
        if records_root is None:
            raise CustodyError("SBA run directory is not beneath records")
        current_run = (
            PurePosixPath("records") / run_dir.relative_to(records_root).as_posix()
        )
        if (
            not expected_run.parts
            or expected_run.parts[0] != "records"
            or str(previous["custodyRootPath"])
            != f"{expected_run.as_posix()}/custody_root.json"
            or root_path.parent.name != expected_run.name
        ):
            raise CustodyError("SBA prior run directory disagrees with its root path")
        if expected_run.as_posix() >= current_run.as_posix():
            raise CustodyError(
                "SBA prior complete capture does not precede the current run"
            )
        prior_verification = verify_run(root_path.parent)
        prior_manifest = _load_object(root_path.parent / "manifest.json")
        prior_bundle = prior_manifest.get("bundle")
        prior_retrieved = _instant(
            prior_manifest.get("retrievedAt"), "SBA prior capture retrievedAt"
        )
        if prior_retrieved >= retrieved:
            raise CustodyError(
                "SBA prior complete capture does not precede the current run"
            )
        if (
            prior_manifest.get("schemaVersion") != SBA_PDF_WITNESS_V1
            or prior_manifest.get("outcome") not in {"bootstrap", "changed"}
            or not isinstance(prior_bundle, dict)
            or prior_verification.custody_root_sha256 != previous["custodyRootSha256"]
            or prior_bundle.get("rawSha256") != previous["bundleSha256"]
            or prior_bundle.get("rawBytes") != previous["bundleBytes"]
            or prior_bundle.get("label") != previous["bundleLabel"]
            or prior_bundle.get("reportAsOf") != previous["reportAsOf"]
        ):
            raise CustodyError("SBA prior complete capture reference does not verify")
        if landing_raw is None or not isinstance(landing["finalUrl"], str):
            raise CustodyError("SBA unchanged capture lacks its archived landing page")
        try:
            identity = _linked_bundle(landing_raw, page_url=landing["finalUrl"])
        except SbaCaptureError as exc:
            raise CustodyError(f"SBA unchanged landing replay refused: {exc}") from exc
        if (
            bundle["label"] != identity.label
            or bundle["fiscalYear"] != identity.fiscal_year
            or bundle["quarter"] != identity.quarter
            or bundle["periodCoverage"] != _period_coverage(identity)
            or bundle["parserContract"] != PARSER_CONTRACT
            or bundle["rawSha256"] != asset["bodySha256"]
            or bundle["rawBytes"] != asset["bodyBytes"]
            or bundle["rawSha256"] != previous["bundleSha256"]
            or bundle["rawBytes"] != previous["bundleBytes"]
            or bundle["label"] != previous["bundleLabel"]
            or bundle["reportAsOf"] != previous["reportAsOf"]
            or bundle["assetUrl"] != identity.linked_url
            or asset["requestedUrl"] != bundle["assetUrl"]
        ):
            raise CustodyError("SBA unchanged observation disagrees with prior bytes")
    else:
        failure = _exact_object(
            manifest["failure"], {"stage", "reason"}, "SBA capture failure"
        )
        if (
            manifest["ok"] is not False
            or manifest["previousCompleteCapture"] is not None
            or not isinstance(failure["stage"], str)
            or not failure["stage"]
            or not isinstance(failure["reason"], str)
            or not failure["reason"].startswith(CAPTURE_REFUSAL)
        ):
            raise CustodyError("failed SBA capture has an invalid refusal state")
        stage = failure["stage"]
        if (stage == "bundle validation") != retained_failed_bundle:
            raise CustodyError(
                "failed SBA bundle retention disagrees with its failure stage"
            )
        state_matches = (
            (
                stage == "landing fetch"
                and landing["outcome"] == "failed"
                and asset is None
            )
            or (
                stage == "landing validation"
                and landing["outcome"] == "success"
                and asset is None
            )
            or (
                stage == "asset fetch"
                and landing["outcome"] == "success"
                and asset is not None
                and asset["outcome"] == "failed"
            )
            or (
                stage in {"asset validation", "bundle validation"}
                and landing["outcome"] == "success"
                and asset is not None
                and asset["outcome"] == "success"
            )
        )
        if not state_matches:
            raise CustodyError("SBA capture failure stage disagrees with fetch state")
        if retained_failed_bundle:
            assert asset is not None
            bundle = _exact_object(
                manifest["bundle"],
                {
                    "label",
                    "fiscalYear",
                    "quarter",
                    "assetUrl",
                    "rawSha256",
                    "rawBytes",
                    "periodCoverage",
                    "parserContract",
                    "landingArchive",
                    "zipArchive",
                },
                "SBA retained failed bundle",
            )
            archived_landing_raw, _ = _verify_sba_archive(
                run_dir,
                bundle["landingArchive"],
                expected_path="upstream/landing-page.html.gz",
                label="SBA failed landing archive",
            )
            zip_raw, _ = _verify_sba_archive(
                run_dir,
                bundle["zipArchive"],
                expected_path="upstream/loan-program-performance.zip.gz",
                label="SBA failed ZIP archive",
            )
            if (
                landing_raw is None
                or archived_landing_raw != landing_raw
                or asset["bodySha256"] != _sha256(zip_raw)
                or asset["bodyBytes"] != len(zip_raw)
            ):
                raise CustodyError(
                    "SBA failed fetch-event body commitments do not replay"
                )
            assert isinstance(landing["finalUrl"], str)
            try:
                identity = _linked_bundle(landing_raw, page_url=landing["finalUrl"])
            except SbaCaptureError as exc:
                raise CustodyError(f"SBA failed landing replay refused: {exc}") from exc
            if asset["requestedUrl"] != identity.linked_url:
                raise CustodyError(
                    "SBA failed ZIP was not fetched from the archived page link"
                )
            claimed = {
                name: value
                for name, value in bundle.items()
                if name not in {"landingArchive", "zipArchive"}
            }
            if claimed != _captured_bundle(zip_raw, identity=identity):
                raise CustodyError(
                    "SBA retained failed bundle identity does not match replay"
                )
            try:
                _inspect_bundle(zip_raw, identity=identity)
            except SbaCaptureError as exc:
                replayed_reason = f"{CAPTURE_REFUSAL} {exc}"
            else:
                raise CustodyError("SBA retained failed bundle passes strict replay")
            if failure["reason"] != replayed_reason:
                raise CustodyError(
                    "SBA retained failed bundle refusal does not match replay"
                )


def _verified_constituent_runs(
    run_dir: Path,
    manifest: dict[str, Any],
    references: Any,
    *,
    require_complete: bool,
) -> list[dict[str, Any]]:
    if (
        not isinstance(references, list)
        or len(references) != 3
        or not all(isinstance(reference, dict) for reference in references)
    ):
        raise CustodyError("derived ensemble requires exactly 3 constituent runs")
    paths: set[str] = set()
    roots: set[str] = set()
    normalized: list[dict[str, Any]] = []
    target = manifest.get("targetContext")
    for reference in references:
        logical = _safe_relative(str(reference.get("manifestPath") or "")).as_posix()
        root_sha = str(reference.get("custodyRootSha256") or "")
        manifest_sha = str(reference.get("manifestSha256") or "")
        manifest_bytes = reference.get("manifestBytes")
        if (
            logical in paths
            or root_sha in roots
            or not re.fullmatch(r"[0-9a-f]{64}", root_sha)
            or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha)
            or type(manifest_bytes) is not int
            or manifest_bytes < 1
        ):
            raise CustodyError(
                "derived ensemble requires 3 distinct, fully hashed constituent roots"
            )
        parent_path = _repository_artifact_path(run_dir, logical)
        raw = parent_path.read_bytes()
        if _sha256(raw) != manifest_sha or len(raw) != manifest_bytes:
            raise CustodyError(f"constituent manifest integrity mismatch: {logical}")
        parent = _load_object(parent_path)
        if parent.get("custodyRootSha256") != root_sha:
            raise CustodyError(f"constituent custody root mismatch: {logical}")
        verification = verify_run(parent_path.parent)
        if verification.run_mode != "analyst" or not verification.run_succeeded:
            raise CustodyError(
                f"constituent is not a successful analyst run: {logical}"
            )
        if (
            require_complete
            and verification.inventory_status != INVENTORY_STATUS_COMPLETE
        ):
            raise CustodyError(f"constituent is not a complete v2 run: {logical}")
        if parent.get("promptMode") != "fast" or canonical_bytes(
            parent.get("targetContext")
        ) != canonical_bytes(target):
            raise CustodyError(f"constituent target or prompt mode mismatch: {logical}")
        parent_cells_path = _repository_artifact_path(
            run_dir, str(parent.get("cellsPath") or "")
        )
        try:
            parent_cells = json.loads(parent_cells_path.read_bytes())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CustodyError(f"invalid constituent cells: {logical}: {exc}") from exc
        if not isinstance(parent_cells, list) or len(parent_cells) != 1:
            raise CustodyError(f"constituent must contain exactly one cell: {logical}")
        parent_run_at = str(parent_cells[0].get("runAt") or "")
        if reference.get("runAt") != parent_run_at:
            raise CustodyError(f"constituent runAt mismatch: {logical}")
        paths.add(logical)
        roots.add(root_sha)
        normalized.append({**reference, "manifestPath": logical})
    return normalized


def _verify_derived_ensemble_v2(
    run_dir: Path,
    manifest: dict[str, Any],
    entries: list[dict[str, Any]],
    custody: dict[str, Any],
) -> None:
    if (
        manifest.get("schemaVersion") != DERIVED_ENSEMBLE_SCHEMA
        or manifest.get("aggregationAlgorithmVersion") != DERIVED_ENSEMBLE_ALGORITHM
        or manifest.get("promptMode") != "median3"
        or manifest.get("ok") is not True
    ):
        raise CustodyError("invalid derived ensemble manifest contract")
    if manifest.get("createdAt") != manifest.get("runStartedAt"):
        raise CustodyError("derived manifest createdAt/runStartedAt mismatch")
    target = manifest.get("targetContext")
    if not isinstance(target, dict) or any(
        canonical_bytes(manifest.get(field)) != canonical_bytes(target.get(field))
        for field in ("series", "period")
    ):
        raise CustodyError("derived manifest target identity mismatch")
    if (
        _manifest_relative(run_dir, str(manifest.get("cellsPath") or ""), legacy=False)
        != "cells.with_activity.json"
    ):
        raise CustodyError("derived manifest cellsPath is outside its run")
    actual_inventory = [
        (str(entry["artifactType"]), str(entry["path"])) for entry in entries
    ]
    if actual_inventory != [
        ("derived_distribution", "distribution.json"),
        ("cells_with_activity", "cells.with_activity.json"),
    ]:
        raise CustodyError("derived ensemble has an invalid local artifact inventory")

    references = _verified_constituent_runs(
        run_dir,
        manifest,
        manifest.get("constituentRuns"),
        require_complete=True,
    )
    if canonical_bytes(custody.get("constituentCustodyRoots")) != canonical_bytes(
        references
    ):
        raise CustodyError("custody root constituent chain differs from manifest")
    if manifest.get("constituentManifests") != [
        reference["manifestPath"] for reference in references
    ]:
        raise CustodyError("derived constituent manifest list is inconsistent")

    start = _instant(manifest.get("runStartedAt"), "derived runStartedAt")
    for reference in references:
        if _instant(reference.get("runAt"), "constituent runAt") > start:
            raise CustodyError("derived run starts before a constituent was sealed")

    cells_path = run_dir / "cells.with_activity.json"
    distribution_path = run_dir / "distribution.json"
    try:
        cells = json.loads(cells_path.read_bytes())
        distribution = json.loads(distribution_path.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CustodyError(f"invalid derived JSON artifact: {exc}") from exc
    if not isinstance(cells, list) or len(cells) != 1 or not isinstance(cells[0], dict):
        raise CustodyError("derived cells payload must contain exactly one cell")
    cell = cells[0]
    if (
        cell.get("runStartedAt") != manifest.get("runStartedAt")
        or _instant(cell.get("runAt"), "derived cell runAt") < start
        or cell.get("aggregationAlgorithmVersion") != DERIVED_ENSEMBLE_ALGORITHM
        or canonical_bytes(cell.get("constituentRuns")) != canonical_bytes(references)
        or cell.get("slug") != (manifest.get("targetContext") or {}).get("catalogSlug")
    ):
        raise CustodyError("derived cell metadata differs from its manifest")
    for field in (
        "registrationCommit",
        "targetContentHash",
        "targetRegistrationPath",
        "registeredAtUtc",
    ):
        target_value = (manifest.get("targetContext") or {}).get(field)
        if target_value not in (None, "") and (
            manifest.get(field) != target_value or cell.get(field) != target_value
        ):
            raise CustodyError(f"derived registration binding mismatch: {field}")

    summary = distribution.get("summary") if isinstance(distribution, dict) else None
    interval = summary.get("interval80") if isinstance(summary, dict) else None
    if (
        distribution.get("format") != "numeric_cdf_v1"
        or not isinstance(interval, dict)
        or canonical_bytes(summary.get("pointEstimate"))
        != canonical_bytes(cell.get("pointEstimate"))
        or canonical_bytes(interval.get("lower")) != canonical_bytes(cell.get("ciLow"))
        or canonical_bytes(interval.get("upper")) != canonical_bytes(cell.get("ciHigh"))
    ):
        raise CustodyError("derived distribution summary differs from its cell")

    activity = cell.get("activityLog")
    if not isinstance(activity, list) or len(activity) != 4:
        raise CustodyError(
            "derived activity log must expose 3 parents and distribution"
        )
    for activity_ref, reference in zip(activity[:3], references):
        expected = {
            "artifactType": "constituent_manifest",
            "path": reference["manifestPath"],
            "sha256": reference["manifestSha256"],
            "bytes": reference["manifestBytes"],
            "custodyRootSha256": reference["custodyRootSha256"],
            "createdAt": manifest["runStartedAt"],
        }
        if canonical_bytes(activity_ref) != canonical_bytes(expected):
            raise CustodyError("derived activity log has a mismatched constituent")
    distribution_ref = next(
        ref
        for ref in manifest["artifacts"]
        if ref.get("artifactType") == "derived_distribution"
    )
    if canonical_bytes(activity[3]) != canonical_bytes(distribution_ref):
        raise CustodyError("derived activity log has a mismatched distribution")


def _verify_legacy_derived_without_root(
    run_dir: Path, manifest: dict[str, Any]
) -> CustodyVerification:
    """Verify the six immutable July-8 median runs as incomplete legacy data."""

    if (
        manifest.get("schemaVersion") != DERIVED_ENSEMBLE_SCHEMA
        or manifest.get("createdAt") != LEGACY_DERIVED_AT
        or manifest.get("promptMode") != "median3"
        or manifest.get("aggregationAlgorithmVersion")
        not in {None, DERIVED_ENSEMBLE_ALGORITHM}
        or manifest.get("ok") is not True
        or manifest.get("runMode") is not None
        or manifest.get("custodyInventoryVersion") is not None
        or manifest.get("custodyRootSha256") is not None
        or run_dir.parent.name != "2026-07-08"
        or run_dir.name not in LEGACY_DERIVED_DIRS
    ):
        raise CustodyError(f"missing custody root: {run_dir / 'custody_root.json'}")
    discovered = _regular_files(run_dir)
    expected_files = {"cells.with_activity.json", "distribution.json", "manifest.json"}
    if discovered != expected_files:
        raise CustodyError("legacy derived run has an unexpected file inventory")
    references = manifest.get("constituentManifests")
    artifacts = manifest.get("artifacts")
    if (
        not isinstance(references, list)
        or len(references) != 3
        or len(set(references)) != 3
        or not isinstance(artifacts, list)
        or len(artifacts) != 4
    ):
        raise CustodyError("legacy derived run has an invalid constituent inventory")
    parent_entries = [
        entry
        for entry in artifacts
        if isinstance(entry, dict)
        and entry.get("artifactType") == "constituent_manifest"
    ]
    distribution_entries = [
        entry
        for entry in artifacts
        if isinstance(entry, dict)
        and entry.get("artifactType") == "derived_distribution"
    ]
    if [entry.get("path") for entry in parent_entries] != references or len(
        distribution_entries
    ) != 1:
        raise CustodyError("legacy derived artifacts do not match constituent list")
    parent_hashes: set[str] = set()
    for entry in parent_entries:
        parent_path = _repository_artifact_path(run_dir, str(entry["path"]))
        raw = parent_path.read_bytes()
        if _sha256(raw) != entry.get("sha256") or len(raw) != entry.get("bytes"):
            raise CustodyError("legacy constituent manifest integrity mismatch")
        parent_hashes.add(str(entry.get("sha256")))
    if len(parent_hashes) != 3:
        raise CustodyError("legacy derived run lacks 3 distinct constituent manifests")
    distribution_path = _repository_artifact_path(
        run_dir, str(distribution_entries[0]["path"])
    )
    raw_distribution = distribution_path.read_bytes()
    if (
        distribution_path.parent != run_dir
        or _sha256(raw_distribution) != distribution_entries[0].get("sha256")
        or len(raw_distribution) != distribution_entries[0].get("bytes")
    ):
        raise CustodyError("legacy derived distribution integrity mismatch")
    cells_path = _repository_artifact_path(
        run_dir, str(manifest.get("cellsPath") or "")
    )
    try:
        cells = json.loads(cells_path.read_bytes())
        distribution = json.loads(raw_distribution)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CustodyError(f"invalid legacy derived JSON: {exc}") from exc
    if not isinstance(cells, list) or len(cells) != 1:
        raise CustodyError("legacy derived cells must contain exactly one cell")
    summary = distribution.get("summary") or {}
    interval = summary.get("interval80") or {}
    cell = cells[0]
    if (
        cell.get("runAt") != LEGACY_DERIVED_AT
        or cell.get("aggregationAlgorithmVersion")
        not in {None, DERIVED_ENSEMBLE_ALGORITHM}
        or canonical_bytes(cell.get("pointEstimate"))
        != canonical_bytes(summary.get("pointEstimate"))
        or canonical_bytes(cell.get("ciLow")) != canonical_bytes(interval.get("lower"))
        or canonical_bytes(cell.get("ciHigh")) != canonical_bytes(interval.get("upper"))
    ):
        raise CustodyError("legacy derived cells differ from distribution")
    return CustodyVerification(
        run_mode="derived_ensemble",
        custody_inventory_version=1,
        inventory_status=INVENTORY_STATUS_LEGACY,
        custody_root_sha256=_sha256((run_dir / "manifest.json").read_bytes()),
        artifact_count=len(artifacts),
        run_succeeded=True,
    )


def verify_run(run_dir: Path) -> CustodyVerification:
    run_dir = run_dir.resolve()
    root_path = run_dir / "custody_root.json"
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise CustodyError(f"missing manifest: {manifest_path}")
    manifest = _load_object(manifest_path)
    if not root_path.is_file():
        return _verify_legacy_derived_without_root(run_dir, manifest)
    custody = _load_object(root_path)
    if custody.get("schemaVersion") != "thesis_custody_root_v1":
        raise CustodyError(
            f"unsupported custody schema: {custody.get('schemaVersion')!r}"
        )

    custody_version = custody.get("custodyInventoryVersion")
    manifest_version = manifest.get("custodyInventoryVersion")
    legacy = custody_version is None and manifest_version is None
    if legacy:
        version = 1
        run_mode = (
            "analyst"
            if manifest.get("schemaVersion") == "thesis_analyst_run_manifest_v1"
            else "unknown"
        )
    else:
        if (
            custody_version != INVENTORY_VERSION
            or manifest_version != INVENTORY_VERSION
        ):
            raise CustodyError(
                "custody inventory version mismatch: "
                f"root={custody_version!r}, manifest={manifest_version!r}"
            )
        version = INVENTORY_VERSION
        run_mode = str(custody.get("runMode"))
        if run_mode != manifest.get("runMode") or run_mode not in {
            "analyst",
            "resolver",
            "derived_ensemble",
            "ledger_witness",
            "sba_pdf_witness",
        }:
            raise CustodyError(
                "custody run mode mismatch: "
                f"root={run_mode!r}, manifest={manifest.get('runMode')!r}"
            )

    entries = custody.get("artifacts")
    if not isinstance(entries, list):
        raise CustodyError("custody_root.json artifacts must be a list")
    seen_identities: set[tuple[str, str]] = set()
    seen_paths: set[str] = set()
    normalized_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise CustodyError("custody artifact entry is not an object")
        artifact_type = str(entry.get("artifactType"))
        relative = _safe_relative(str(entry.get("path"))).as_posix()
        if relative in {"manifest.json", "custody_root.json"}:
            raise CustodyError(
                f"control file appears as ordinary custody artifact: {relative}"
            )
        identity = (artifact_type, relative)
        if identity in seen_identities or relative in seen_paths:
            raise CustodyError(
                f"duplicate custody artifact path: {artifact_type} {relative}"
            )
        seen_identities.add(identity)
        seen_paths.add(relative)
        path = _safe_artifact_path(run_dir, relative)
        if not path.is_file() or path.is_symlink():
            raise CustodyError(
                f"missing or non-regular artifact {artifact_type}: {relative}"
            )
        raw = path.read_bytes()
        actual_sha = _sha256(raw)
        if actual_sha != entry.get("sha256"):
            raise CustodyError(
                f"raw SHA-256 mismatch for {artifact_type} {relative}: "
                f"expected {entry.get('sha256')}, got {actual_sha}"
            )
        if len(raw) != entry.get("bytes"):
            raise CustodyError(
                f"byte-count mismatch for {artifact_type} {relative}: "
                f"expected {entry.get('bytes')}, got {len(raw)}"
            )
        if not legacy and path.suffix == ".json" and "canonicalJsonSha256" not in entry:
            raise CustodyError(
                f"v2 JSON custody artifact lacks canonical hash: {relative}"
            )
        if "canonicalJsonSha256" in entry:
            try:
                value = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise CustodyError(
                    f"artifact marked as JSON is invalid: {relative}: {exc}"
                ) from exc
            actual_canonical = canonical_sha256(value)
            if actual_canonical != entry["canonicalJsonSha256"]:
                raise CustodyError(
                    "canonical JSON SHA-256 mismatch for "
                    f"{artifact_type} {relative}: "
                    f"expected {entry['canonicalJsonSha256']}, "
                    f"got {actual_canonical}"
                )
        normalized_entries.append(
            {**entry, "artifactType": artifact_type, "path": relative}
        )

    manifest_entries = manifest.get("artifacts")
    if not isinstance(manifest_entries, list):
        raise CustodyError("manifest artifacts must be a list")
    normalized_manifest: list[tuple[str, str]] = []
    normalized_manifest_refs: list[dict[str, Any]] = []
    manifest_paths: set[str] = set()
    for ref in manifest_entries:
        if not isinstance(ref, dict):
            raise CustodyError("manifest artifact entry is not an object")
        artifact_type = str(ref.get("artifactType"))
        relative = _manifest_relative(run_dir, str(ref.get("path")), legacy=legacy)
        if relative in manifest_paths:
            raise CustodyError(
                f"manifest references an artifact path more than once: {relative}"
            )
        manifest_paths.add(relative)
        normalized_manifest.append((artifact_type, relative))
        normalized_manifest_refs.append(
            {**ref, "artifactType": artifact_type, "path": relative}
        )
    rooted_order = [
        (str(entry["artifactType"]), str(entry["path"])) for entry in normalized_entries
    ]
    referenced_without_manifest = [
        item for item in normalized_manifest if item[0] != "manifest"
    ]
    if legacy:
        if set(rooted_order) != set(referenced_without_manifest):
            raise CustodyError(
                "custody artifact coverage mismatch: "
                f"rooted={sorted(rooted_order)}, "
                f"referenced={sorted(referenced_without_manifest)}"
            )
    elif rooted_order != referenced_without_manifest:
        raise CustodyError(
            "v2 custody artifacts must match manifest artifacts one-to-one and in order"
        )
    if not legacy:
        nonself_refs = [
            ref for ref in normalized_manifest_refs if ref["artifactType"] != "manifest"
        ]
        for ref, entry in zip(nonself_refs, normalized_entries):
            for field in ("sha256", "bytes"):
                if ref.get(field) != entry.get(field):
                    raise CustodyError(
                        "manifest/custody integrity mismatch for "
                        f"{entry['path']} field {field}: "
                        f"manifest={ref.get(field)!r}, custody={entry.get(field)!r}"
                    )
            if "canonicalJsonSha256" in ref and ref["canonicalJsonSha256"] != entry.get(
                "canonicalJsonSha256"
            ):
                raise CustodyError(
                    f"manifest/custody canonical JSON mismatch for {entry['path']}"
                )

    if legacy and manifest.get("ok"):
        required_types = {"prompt", "command", "normalized_cell", "cells_with_activity"}
        present_types = {artifact_type for artifact_type, _ in rooted_order}
        absent = sorted(required_types - present_types)
        if absent:
            raise CustodyError(
                "successful legacy run is missing required custody artifact types: "
                + ", ".join(absent)
            )

    manifest_without_root = copy.deepcopy(manifest)
    manifest_without_root.pop("custodyRootSha256", None)
    manifest_commitment = custody.get("manifestWithoutCustodyRoot") or {}
    actual_manifest_sha = canonical_sha256(manifest_without_root)
    if actual_manifest_sha != manifest_commitment.get("canonicalJsonSha256"):
        raise CustodyError(
            "manifest-without-root canonical SHA-256 mismatch: expected "
            f"{manifest_commitment.get('canonicalJsonSha256')}, "
            f"got {actual_manifest_sha}"
        )
    self_refs = [
        ref for ref in manifest_entries if ref.get("artifactType") == "manifest"
    ]
    if len(self_refs) != 1:
        raise CustodyError(
            "manifest must contain exactly one self artifact entry, "
            f"got {len(self_refs)}"
        )
    if (
        _manifest_relative(run_dir, str(self_refs[0].get("path")), legacy=legacy)
        != "manifest.json"
    ):
        raise CustodyError("manifest self artifact does not point to manifest.json")
    self_bytes = canonical_bytes(_self_hash_payload(manifest))
    self_sha = _sha256(self_bytes)
    if self_sha != self_refs[0].get("sha256"):
        raise CustodyError(
            "manifest self-entry SHA-256 mismatch: "
            f"expected {self_refs[0].get('sha256')}, got {self_sha}"
        )
    if len(self_bytes) != self_refs[0].get("bytes"):
        raise CustodyError(
            "manifest self-entry byte-count mismatch: "
            f"expected {self_refs[0].get('bytes')}, got {len(self_bytes)}"
        )
    actual_root_sha = canonical_sha256(custody)
    if actual_root_sha != manifest.get("custodyRootSha256"):
        raise CustodyError(
            "custody root SHA-256 mismatch: "
            f"expected {manifest.get('custodyRootSha256')}, got {actual_root_sha}"
        )

    if not legacy:
        discovered = _regular_files(run_dir)
        expected_files = {*manifest_paths, "custody_root.json"}
        if discovered != expected_files:
            raise CustodyError(
                "v2 run directory inventory mismatch: "
                f"unreferenced={sorted(discovered - expected_files)}, "
                f"missing={sorted(expected_files - discovered)}"
            )
        if run_mode == "analyst":
            _verify_analyst_v2(run_dir, manifest, manifest_entries, normalized_entries)
        elif run_mode == "resolver":
            _verify_resolver_v2(run_dir, manifest, normalized_entries)
        elif run_mode == "ledger_witness":
            _verify_ledger_witness_v2(run_dir, manifest, normalized_entries)
        elif run_mode == "sba_pdf_witness":
            _verify_sba_pdf_witness_v2(run_dir, manifest, normalized_entries)
        elif run_mode == "derived_ensemble":
            _verify_derived_ensemble_v2(run_dir, manifest, normalized_entries, custody)
        else:
            raise CustodyError(f"unsupported custody run mode: {run_mode}")

    return CustodyVerification(
        run_mode=run_mode,
        custody_inventory_version=version,
        inventory_status=INVENTORY_STATUS_LEGACY
        if legacy
        else INVENTORY_STATUS_COMPLETE,
        custody_root_sha256=actual_root_sha,
        artifact_count=len(entries),
        run_succeeded=(
            (
                run_mode == "analyst"
                and manifest.get("ok") is True
                and isinstance(manifest.get("validation"), dict)
                and manifest["validation"].get("ok") is True
            )
            or (run_mode == "derived_ensemble" and manifest.get("ok") is True)
            or (run_mode == "sba_pdf_witness" and manifest.get("ok") is True)
        ),
    )


def _recorder_archive(
    records_root: Path, record: dict[str, Any], expected_body_root: Path
) -> tuple[str, Any]:
    logical = str(record.get("archivePath", ""))
    if not logical.startswith("records/"):
        raise CustodyError(f"recorder archive path is not logical: {logical!r}")
    relative = _safe_relative(logical).parts[1:]
    path = records_root.joinpath(*relative)
    try:
        body_relative = (
            path.resolve().relative_to(expected_body_root.resolve()).as_posix()
        )
    except ValueError as exc:
        raise CustodyError(
            f"recorder archive escapes its body directory: {logical}"
        ) from exc
    if not path.is_file() or path.is_symlink():
        raise CustodyError(f"recorder archive is missing: {logical}")
    compressed = path.read_bytes()
    if _sha256(compressed) != record.get("archiveSha256") or len(
        compressed
    ) != record.get("archiveBytes"):
        raise CustodyError(f"recorder compressed archive mismatch: {logical}")
    try:
        raw = gzip.decompress(compressed)
        payload = json.loads(raw)
    except (OSError, EOFError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CustodyError(
            f"invalid recorder JSON gzip archive {logical}: {exc}"
        ) from exc
    if _sha256(raw) != record.get("sha256") or len(raw) != record.get("bytes"):
        raise CustodyError(f"recorder decompressed archive mismatch: {logical}")
    return body_relative, payload


def verify_recorder_snapshot(snapshot_path: Path) -> CustodyVerification:
    snapshot_path = snapshot_path.resolve()
    payload = _load_object(snapshot_path)
    if (
        payload.get("schemaVersion") != "thesis_record_snapshot_v2"
        or payload.get("snapshotKind") != "recorder_run"
    ):
        raise CustodyError("file is not a recorder snapshot")
    version = payload.get("custodyInventoryVersion")
    legacy = version is None
    if not legacy and (
        version != INVENTORY_VERSION or payload.get("runMode") != "recorder"
    ):
        raise CustodyError("unsupported recorder custody inventory version or mode")
    records_root = snapshot_path.parents[1]
    run_id = str(payload.get("runId", ""))
    body_root = snapshot_path.parent / f"bodies-{run_id}"
    referenced: set[str] = set()
    surfaces = payload.get("surfaces")
    if not isinstance(surfaces, dict):
        raise CustodyError("recorder snapshot lacks surfaces")
    if not legacy:
        missing_surfaces = sorted(set(RECORDER_REQUIRED_SURFACES) - set(surfaces))
        if missing_surfaces:
            raise CustodyError(
                "recorder is missing required surfaces: " + ", ".join(missing_surfaces)
            )
    surface_payloads: dict[str, Any] = {}
    for key, record in surfaces.items():
        if not isinstance(record, dict):
            raise CustodyError(f"recorder surface {key} is not an object")
        relative, archive_payload = _recorder_archive(records_root, record, body_root)
        surface_payloads[str(key)] = archive_payload
        if not legacy and RECORDER_REQUIRED_SURFACES.get(str(key)) != relative:
            raise CustodyError(
                f"recorder surface {key} has unexpected archive path {relative}"
            )
        if relative in referenced:
            raise CustodyError(f"duplicate recorder archive path: {relative}")
        referenced.add(relative)
    live = payload.get("liveForecasts") or {}
    if not isinstance(live, dict):
        raise CustodyError("recorder liveForecasts must be an object")
    if not legacy and set(live) != set(RECORDER_REQUIRED_LIVE):
        raise CustodyError(
            "recorder live forecast inventory is not the required exact set"
        )
    for key, record in live.items():
        relative, _archive_payload = _recorder_archive(records_root, record, body_root)
        if not legacy and RECORDER_REQUIRED_LIVE.get(str(key)) != relative:
            raise CustodyError(
                f"recorder live forecast {key} has unexpected archive path {relative}"
            )
        if relative in referenced:
            raise CustodyError(f"duplicate recorder archive path: {relative}")
        referenced.add(relative)
    chunks = payload.get("logChunks") or {}
    if not isinstance(chunks, dict):
        raise CustodyError("recorder logChunks must be an object")
    chunk_payloads: dict[str, Any] = {}
    chunk_relatives: dict[str, str] = {}
    for key, record in chunks.items():
        relative, archive_payload = _recorder_archive(records_root, record, body_root)
        chunk_payloads[str(key)] = archive_payload
        chunk_relatives[str(key)] = relative
        if relative in referenced:
            raise CustodyError(f"duplicate recorder archive path: {relative}")
        referenced.add(relative)
    if not legacy:
        log_manifest = surface_payloads["log"]
        if log_manifest.get("schemaVersion") == "thesis_log_v3":
            expected_chunks: dict[str, dict[str, Any]] = {}
            collections = log_manifest.get("collections")
            if not isinstance(collections, dict):
                raise CustodyError("recorder v3 log manifest lacks collections")
            for collection, collection_manifest in collections.items():
                references = (
                    collection_manifest.get("chunks")
                    if isinstance(collection_manifest, dict)
                    else None
                )
                if not isinstance(references, list):
                    raise CustodyError(
                        f"recorder v3 log collection {collection} lacks chunks"
                    )
                for expected_index, reference in enumerate(references):
                    if (
                        not isinstance(reference, dict)
                        or reference.get("index") != expected_index
                    ):
                        raise CustodyError(
                            f"recorder v3 {collection} chunk indexes are invalid"
                        )
                    expected_chunks[f"{collection}:{expected_index}"] = reference
            if set(chunks) != set(expected_chunks):
                raise CustodyError(
                    "recorder v3 log chunk inventory differs from its manifest"
                )
            for key, reference in expected_chunks.items():
                record = chunks[key]
                chunk = chunk_payloads[key]
                expected_collection, expected_index_text = key.split(":", 1)
                expected_index = int(expected_index_text)
                expected_url = f"/log/{expected_collection}/{expected_index}.json"
                if reference.get("url") != expected_url:
                    raise CustodyError(
                        f"recorder v3 chunk {key} has invalid manifest URL"
                    )
                expected_relative = f"{expected_url.lstrip('/')}.gz"
                if chunk_relatives[key] != expected_relative:
                    raise CustodyError(
                        f"recorder v3 chunk {key} archive path mismatch: "
                        f"expected {expected_relative}, got {chunk_relatives[key]}"
                    )
                if record.get("manifestSha256") != reference.get("sha256"):
                    raise CustodyError(
                        f"recorder v3 chunk {key} manifest hash link mismatch"
                    )
                expected_fields = {
                    "schemaVersion": "thesis_log_chunk_v1",
                    "logSchemaVersion": "thesis_log_v3",
                    "collection": expected_collection,
                    "chunkIndex": expected_index,
                    "count": reference.get("count"),
                }
                if any(
                    chunk.get(name) != value for name, value in expected_fields.items()
                ):
                    raise CustodyError(f"recorder v3 chunk {key} metadata mismatch")
                if len(chunk.get("rows", [])) != reference.get("count"):
                    raise CustodyError(f"recorder v3 chunk {key} row count mismatch")
                if canonical_sha256(chunk) != reference.get("sha256"):
                    raise CustodyError(
                        f"recorder v3 chunk {key} canonical hash mismatch"
                    )
        elif chunks:
            raise CustodyError("non-v3 recorder log unexpectedly has log chunks")
        discovered = _regular_files(body_root)
        if discovered != referenced:
            raise CustodyError(
                "recorder body inventory mismatch: "
                f"unreferenced={sorted(discovered - referenced)}, "
                f"missing={sorted(referenced - discovered)}"
            )
    return CustodyVerification(
        run_mode="recorder",
        custody_inventory_version=1 if legacy else INVENTORY_VERSION,
        inventory_status=INVENTORY_STATUS_LEGACY
        if legacy
        else INVENTORY_STATUS_COMPLETE,
        custody_root_sha256=_sha256(snapshot_path.read_bytes()),
        artifact_count=len(referenced) + 1,
        run_succeeded=False,
    )


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: verify_custody.py <run-dir|recorder-digest.json>", file=sys.stderr
        )
        return 2
    target = Path(sys.argv[1])
    try:
        result = (
            verify_run(target) if target.is_dir() else verify_recorder_snapshot(target)
        )
    except CustodyError as exc:
        print(f"CUSTODY BROKEN: {exc}", file=sys.stderr)
        return 1
    print(
        f"custody OK: {target} mode={result.run_mode} "
        f"inventory=v{result.custody_inventory_version} "
        f"status={result.inventory_status} artifacts={result.artifact_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
