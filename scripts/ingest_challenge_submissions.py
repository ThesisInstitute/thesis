#!/usr/bin/env python3
"""Adapt merged challenge-inbox cells into recorder forecast records.

The adapter is deliberately read-only. It returns (or, as a standalone
command, prints) normalized records for the established forecast-snapshot
writer to include. A malformed submission is isolated to that file and
reported on stderr so one challenger cannot stop the daily recorder batch.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

SUBMISSION_SCHEMA_VERSION = "thesis_challenge_submission_v1"
EXPECTED_QUANTILE_PS = (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)
SYSTEM_TYPES = {"ai", "human", "hybrid"}

LOGGER = logging.getLogger(__name__)
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40,64}\Z")


class ChallengeSubmissionError(ValueError):
    """A single challenge submission cannot be published."""


@dataclass(frozen=True)
class RegisteredTarget:
    data_point_id: str
    catalog_slug: str
    release_at: datetime


@dataclass(frozen=True)
class SubmissionContent:
    """A submission's fields, validated from its bytes alone."""

    challenger: str
    system_type: str
    system_name: str
    data_point_id: str
    point_estimate: int | float
    quantiles: list[dict[str, Any]]
    generated_value: str
    generated_at: datetime
    notes: str | None

    @property
    def key(self) -> tuple[str, str]:
        # One shot per (challenger, dataPointId), case-insensitive on the
        # challenger because GitHub logins are.
        return (self.challenger.lower(), self.data_point_id)


def parse_utc_datetime(value: Any, *, field: str, allow_date: bool = False) -> datetime:
    """Parse an offset-aware ISO instant and normalize it to UTC.

    Target registrations currently carry release windows as dates. A date
    is conservatively interpreted as the first instant of that UTC day: a
    day-granularity registration cannot prove that a same-day forecast came
    before the release.
    """

    if not isinstance(value, str) or not value:
        raise ChallengeSubmissionError(f"{field} must be an ISO-8601 string")
    candidate = value
    if allow_date and _DATE_RE.fullmatch(candidate):
        candidate = f"{candidate}T00:00:00+00:00"
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except (OverflowError, ValueError) as error:
        raise ChallengeSubmissionError(
            f"{field} is not a valid ISO-8601 datetime: {value!r}"
        ) from error
    if parsed.tzinfo is None:
        raise ChallengeSubmissionError(
            f"{field} must include an explicit UTC offset: {value!r}"
        )
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError) as error:
        raise ChallengeSubmissionError(
            f"{field} is outside the supported UTC datetime range: {value!r}"
        ) from error


def _utc_string(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ChallengeSubmissionError(f"{field} must be a non-empty string")
    return value


def _finite_number(value: Any, *, field: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ChallengeSubmissionError(f"{field} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError as error:
        raise ChallengeSubmissionError(f"{field} must be a finite number") from error
    if not finite:
        raise ChallengeSubmissionError(f"{field} must be a finite number")
    return value


EXPIRED_REGISTRATIONS_TS = Path("site/src/data/expired-unforecast-registrations.ts")


def expired_unforecast_registrations(repo_root: Path) -> frozenset[str]:
    """The terminal expired-registration ratchet, shared with the site.

    A registration on this list crossed its orphan grace with no
    forecast; admitting one afterward would break the chronology the
    grace window protects. The site suite enforces this for published
    catalogs, but challenge rows reach the recorder without that suite,
    so this adapter must refuse expired ids itself.
    """

    try:
        text = (repo_root / EXPIRED_REGISTRATIONS_TS).read_text()
    except (OSError, UnicodeError) as error:
        raise ChallengeSubmissionError(
            f"cannot read {EXPIRED_REGISTRATIONS_TS}: {error}"
        ) from error
    match = re.search(
        r"EXPIRED_UNFORECAST_REGISTRATIONS\s*=\s*\[(.*?)\]\s*as\s*const",
        text,
        flags=re.S,
    )
    if match is None:
        raise ChallengeSubmissionError(
            f"could not parse {EXPIRED_REGISTRATIONS_TS} for the expired set"
        )
    # Line-anchored: an entry is a line holding exactly one quoted id and
    # a trailing comma. Quoted text inside // comments must not expire an
    # id. Every other nonblank line is corruption: accepting the valid
    # subset would silently revive whichever terminal ids failed to parse.
    parsed_ids: list[str] = []
    for line_number, line in enumerate(match.group(1).splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        entry_match = re.fullmatch(r'"([^"]+)",', stripped)
        if entry_match is None:
            raise ChallengeSubmissionError(
                f"could not parse {EXPIRED_REGISTRATIONS_TS}: invalid expired "
                f"entry on array line {line_number}"
            )
        entry = entry_match.group(1)
        # This parser reads raw characters; the TypeScript runtime decodes
        # string escapes. An escape-spelled entry (\u0066…, \x66…, \") would
        # therefore mean different ids to the two consumers, so any entry
        # that is not plain unescaped id text refuses outright — the list
        # is repo-controlled and every legitimate id is bare ASCII.
        if "\\" in entry or not re.fullmatch(r"[A-Za-z0-9._-]+", entry):
            raise ChallengeSubmissionError(
                f"could not parse {EXPIRED_REGISTRATIONS_TS}: expired entry "
                f"on array line {line_number} is not plain unescaped id text"
            )
        parsed_ids.append(entry)
    ids = frozenset(parsed_ids)
    if not ids:
        raise ChallengeSubmissionError(
            f"parsed an empty expired set from {EXPIRED_REGISTRATIONS_TS}"
        )
    if len(ids) != len(parsed_ids):
        raise ChallengeSubmissionError(
            f"parsed duplicate ids from {EXPIRED_REGISTRATIONS_TS}"
        )
    return ids


def load_registered_targets(targets_dir: Path) -> dict[str, RegisteredTarget]:
    """Index every recorded target registration by dataPointId.

    Registrations are append-only snapshots, so an ID may legitimately occur
    more than once. The earliest recorded release instant is the conservative
    chronology boundary and makes duplicate handling deterministic.
    """

    if not targets_dir.is_dir():
        raise ChallengeSubmissionError(
            f"registered-target directory does not exist: {targets_dir}"
        )

    registered: dict[str, RegisteredTarget] = {}
    for snapshot_path in sorted(targets_dir.glob("*.json")):
        try:
            payload = json.loads(snapshot_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ChallengeSubmissionError(
                f"cannot read target registration {snapshot_path}: {error}"
            ) from error
        targets = payload.get("targets") if isinstance(payload, dict) else None
        if not isinstance(targets, list):
            raise ChallengeSubmissionError(
                f"target registration has no targets array: {snapshot_path}"
            )
        for target in targets:
            if not isinstance(target, dict):
                continue
            data_point_id = target.get("dataPointId")
            catalog_slug = target.get("catalogSlug")
            source_binding = target.get("sourceBinding")
            release_window = (
                source_binding.get("expectedReleaseWindow")
                if isinstance(source_binding, dict)
                else None
            )
            release_value = (
                release_window.get("start")
                if isinstance(release_window, dict)
                else None
            )
            if not isinstance(data_point_id, str) or not data_point_id:
                continue
            if not isinstance(catalog_slug, str) or not catalog_slug:
                continue
            try:
                release_at = parse_utc_datetime(
                    release_value,
                    field=(
                        "expectedReleaseWindow.start for registered target "
                        f"{data_point_id}"
                    ),
                    allow_date=True,
                )
            except ChallengeSubmissionError as error:
                LOGGER.warning(
                    "Skipping registered target in %s: %s",
                    snapshot_path,
                    error,
                )
                continue

            candidate = RegisteredTarget(data_point_id, catalog_slug, release_at)
            current = registered.get(data_point_id)
            if current is None or (
                candidate.release_at,
                candidate.catalog_slug,
            ) < (current.release_at, current.catalog_slug):
                registered[data_point_id] = candidate
    return registered


def validate_quantiles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the required seven-rung grid without rewriting it."""

    quantiles = payload.get("quantiles")
    if not isinstance(quantiles, list):
        raise ChallengeSubmissionError("quantiles must be an array")
    probabilities: list[int | float] = []
    values: list[int | float] = []
    for index, quantile in enumerate(quantiles):
        if not isinstance(quantile, dict):
            raise ChallengeSubmissionError(f"quantiles[{index}] must be an object")
        probabilities.append(
            _finite_number(quantile.get("p"), field=f"quantiles[{index}].p")
        )
        values.append(
            _finite_number(quantile.get("value"), field=f"quantiles[{index}].value")
        )
    if tuple(probabilities) != EXPECTED_QUANTILE_PS:
        raise ChallengeSubmissionError(
            "quantile probabilities must be exactly "
            f"{list(EXPECTED_QUANTILE_PS)} in increasing order"
        )
    if any(left >= right for left, right in zip(values, values[1:])):
        raise ChallengeSubmissionError("quantile values must be strictly increasing")
    return quantiles


def parse_submission_bytes(raw: bytes) -> Any:
    """Decode one submission's bytes exactly as the intake reads them.

    The current-tree adapter and the history walk both parse through here
    so they cannot disagree about which bytes are JSON at all. They did
    (2026-09-24 review): the walk's json.loads(bytes) sniffed UTF-16 and
    stripped a UTF-8 BOM while the adapter's text read refused both, so
    bytes the intake never accepted could still become canonical. Decoding
    is strict UTF-8. Every parser failure is a submission error, never a
    batch abort: pathological nesting raises RecursionError, and an
    integer past CPython's int-digit limit raises a bare ValueError that
    is not a JSONDecodeError — either escaping would stop the recorder.
    """

    try:
        return json.loads(raw.decode("utf-8"))
    except (RecursionError, ValueError) as error:
        # ValueError covers JSONDecodeError and UnicodeDecodeError too.
        raise ChallengeSubmissionError(
            f"submission is not readable JSON: {error}"
        ) from error


def validate_submission_content(payload: Any) -> SubmissionContent:
    """Run every check that depends only on the submission's bytes.

    Pure: no registry, ratchet, release window, path, or clock. The
    history walk canonicalizes on this alone, and adapt_submission layers
    the state-dependent checks on top, so "valid content" means the same
    thing on both paths.
    """

    if not isinstance(payload, dict):
        raise ChallengeSubmissionError("submission must be a JSON object")
    if payload.get("schemaVersion") != SUBMISSION_SCHEMA_VERSION:
        raise ChallengeSubmissionError(
            "schemaVersion must be " + SUBMISSION_SCHEMA_VERSION
        )

    challenger = _required_string(payload, "challenger")
    system_type = _required_string(payload, "systemType")
    if system_type not in SYSTEM_TYPES:
        raise ChallengeSubmissionError(
            f"systemType must be one of {sorted(SYSTEM_TYPES)}"
        )
    system_name = _required_string(payload, "systemName")
    data_point_id = _required_string(payload, "dataPointId")

    point_estimate = _finite_number(payload.get("pointEstimate"), field="pointEstimate")
    quantiles = validate_quantiles(payload)
    # ciLow/ciHigh and the 0.1/0.9 rungs describe the same 80% band; a
    # submission that disagrees with itself is refused rather than
    # silently resolved in favor of the grid.
    ci_low = _finite_number(payload.get("ciLow"), field="ciLow")
    ci_high = _finite_number(payload.get("ciHigh"), field="ciHigh")
    if ci_low != quantiles[1]["value"] or ci_high != quantiles[5]["value"]:
        raise ChallengeSubmissionError(
            "ciLow/ciHigh must equal the 0.1 and 0.9 quantile values"
        )
    generated_value = _required_string(payload, "generatedAtUtc")
    generated_at = parse_utc_datetime(generated_value, field="generatedAtUtc")

    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ChallengeSubmissionError("notes must be a string when present")
    return SubmissionContent(
        challenger=challenger,
        system_type=system_type,
        system_name=system_name,
        data_point_id=data_point_id,
        point_estimate=point_estimate,
        quantiles=quantiles,
        generated_value=generated_value,
        generated_at=generated_at,
        notes=notes,
    )


def forecaster_id(challenger: str, system_name: str) -> str:
    """Build a reversible competing-system identity from both declared parts."""

    return f"{challenger}::{system_name}"


def submission_path(path: Path, repo_root: Path) -> str:
    try:
        return (
            path.resolve(strict=True)
            .relative_to(repo_root.resolve(strict=True))
            .as_posix()
        )
    except (OSError, ValueError) as error:
        raise ChallengeSubmissionError(
            f"submission path is not inside the repository: {path}"
        ) from error


def _is_submission_name(name: str) -> bool:
    # Sigstore sidecars also end in .json but are provenance for a cell,
    # not forecast submissions themselves.
    return name.endswith(".json") and not name.endswith(".sigstore.json")


def first_accepted_content(
    inbox_dir: Path, repo_root: Path
) -> dict[tuple[str, str], tuple[bytes, str]]:
    """Map each (challenger, dataPointId) to its first-accepted bytes and path.

    One shot per target binds the CONTENT, not a pathname. Walking the
    first-parent history oldest-first, a key's canonical content is the
    first blob, at a path the intake reads (inbox/<dir>/<name>.json,
    sidecars excluded), that passes parse_submission_bytes and
    validate_submission_content — every check that depends only on the
    bytes. An edit, a rename, or a delete-and-readd after that leaves the
    canonical bytes unchanged, so any current file whose bytes differ is
    refused. Content the intake refuses on its bytes alone (unparseable,
    or parseable but invalid: a broken quantile grid, an offset-less
    timestamp) was never an accepted forecast and does not define
    canonical content. The 2026-09-24 review caught this walk
    canonicalizing the first merely PARSEABLE file, so an invalid first
    merge locked its challenger out of the target forever.

    The state-dependent checks (target registration, the expiry ratchet,
    generatedAtUtc before the release) are deliberately excluded.
    Registrations are append-only snapshots and the earliest release
    instant can move earlier, so a state-dependent predicate could flip
    which historical content is canonical and hand a challenger a second
    shot; content-intrinsic validity is a pure function of the bytes, so
    the canonical choice for a key never changes as repository state
    evolves. Registration existence and expiry are per-key (every content
    of a key shares its dataPointId), so excluding them cannot change
    which content wins. The release check is per-content: a post-release
    first shot therefore binds its key even though adapt_submission
    refuses it, and a backdated re-submission cannot replace it.
    """

    inbox_rel = (
        inbox_dir.resolve(strict=True)
        .relative_to(repo_root.resolve(strict=True))
        .as_posix()
    )
    inbox_parts = PurePosixPath(inbox_rel).parts
    try:
        # Acceptance order is the FIRST-PARENT chain: content counts as
        # accepted when it lands on the mainline, whether by a direct
        # commit or inside a merge result (-m diffs merges against their
        # first parent). Every change type is walked — not just
        # additions — because the first ACCEPTED FORECAST for a key may
        # arrive as a modification (e.g. an invalid file later fixed in
        # place); filtering to additions would leave such keys with no
        # canonical content and one-shot fail-open. Plain --reverse
        # would walk the whole DAG, letting a stale side branch merged
        # later pre-date the true first forecast. -z because the default
        # output C-quotes any path holding non-ASCII, '"' or '\\'
        # ("jos\303\251.json"), and a quoted path never matched a .json
        # suffix, so such files never bound one shot. --relative prints
        # paths against repo_root (the cwd) rather than the git toplevel,
        # matching the adapter's provenance paths when repo_root sits
        # below the toplevel.
        log = subprocess.run(
            [
                "git",
                "log",
                "--reverse",
                "--first-parent",
                "-m",
                "-z",
                "--relative",
                "--format=%H",
                "--name-status",
                "--",
                inbox_rel,
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ChallengeSubmissionError(
            f"cannot walk the inbox history for {inbox_rel}: {error}"
        ) from error
    canonical: dict[tuple[str, str], tuple[bytes, str]] = {}
    commit = ""
    tokens = log.stdout.split(b"\0")
    index = 0
    while index < len(tokens):
        # -z output is "<commit>\0\n<status>\0<path>\0[<path>\0]..." —
        # the newline ending each commit header lands on the next token.
        token = tokens[index].lstrip(b"\n").decode("ascii", "replace")
        index += 1
        if not token:
            continue
        if _COMMIT_RE.fullmatch(token):
            commit = token
            continue
        status = token[0]
        if status not in "ACDMRT" or not commit:
            # A desynchronized parse could read paths as statuses and
            # skip real submissions — fail-open — so refuse instead.
            raise ChallengeSubmissionError(
                f"unexpected git log entry {token!r} walking {inbox_rel}"
            )
        # A/M/T/D carry one path; renames (R) and copies (C) carry two
        # and land the content at their DESTINATION path.
        width = 2 if status in "RC" else 1
        if index + width > len(tokens):
            raise ChallengeSubmissionError(
                f"truncated git log entry {token!r} walking {inbox_rel}"
            )
        landed = os.fsdecode(tokens[index + width - 1])
        index += width
        if status == "D":
            continue
        relative = PurePosixPath(landed).parts
        if (
            relative[: len(inbox_parts)] != inbox_parts
            or len(relative) != len(inbox_parts) + 2
            or not _is_submission_name(relative[-1])
        ):
            # The intake reads exactly inbox/<dir>/<name>.json; a file it
            # never reads was never an accepted forecast.
            continue
        try:
            raw = subprocess.run(
                # "./" resolves the path against the cwd, like --relative.
                ["git", "show", f"{commit}:./{landed}"],
                cwd=repo_root,
                check=True,
                capture_output=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            continue
        try:
            content = validate_submission_content(parse_submission_bytes(raw))
        except ChallengeSubmissionError:
            # Content refused on its bytes was never an accepted
            # forecast; it must not define canonical content or abort
            # the batch.
            continue
        canonical.setdefault(content.key, (raw, landed))
    return canonical


def merge_commit_for(path: Path, repo_root: Path) -> str:
    """Return the exact commit requested by the challenge provenance contract."""

    relative = submission_path(path, repo_root)
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", relative],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ChallengeSubmissionError(
            f"cannot resolve merge commit with git log for {relative}: {error}"
        ) from error
    commit = result.stdout.strip()
    if not _COMMIT_RE.fullmatch(commit):
        raise ChallengeSubmissionError(
            f"git log returned no full merge commit for {relative}"
        )
    return commit


def adapt_submission(
    path: Path,
    *,
    registered_targets: dict[str, RegisteredTarget],
    repo_root: Path,
    expired_registrations: frozenset[str],
) -> dict[str, Any]:
    """Validate and adapt one inbox JSON file into a snapshot prediction row.

    The bytes pass the same parse and content-intrinsic validation the
    history walk canonicalizes on; only then do the state-dependent
    checks (registration, expiry ratchet, release boundary) run.
    """

    if path.is_symlink() or not path.is_file():
        raise ChallengeSubmissionError("submission must be a regular file")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ChallengeSubmissionError(
            f"submission is not readable JSON: {error}"
        ) from error
    content = validate_submission_content(parse_submission_bytes(raw))

    data_point_id = content.data_point_id
    target = registered_targets.get(data_point_id)
    if target is None:
        raise ChallengeSubmissionError(f"unregistered dataPointId: {data_point_id}")
    if data_point_id in expired_registrations:
        # The registration crossed orphan grace with no forecast and is
        # terminally ratcheted; a pre-release timestamp does not revive it.
        raise ChallengeSubmissionError(
            f"registration {data_point_id} expired unforecast; "
            "post-grace submissions are refused"
        )
    if content.generated_at >= target.release_at:
        raise ChallengeSubmissionError(
            f"generatedAtUtc {content.generated_value} does not precede release "
            f"{_utc_string(target.release_at)}"
        )

    relative = submission_path(path, repo_root)
    quantiles = content.quantiles
    record: dict[str, Any] = {
        "forecastSlug": target.catalog_slug,
        "dataPointId": data_point_id,
        "forecasterId": forecaster_id(content.challenger, content.system_name),
        "challenger": content.challenger,
        "systemType": content.system_type,
        "systemName": content.system_name,
        "pointEstimate": content.point_estimate,
        "interval80": {
            "lower": quantiles[1]["value"],
            "upper": quantiles[5]["value"],
        },
        # Keep the submitted rungs and values exactly as parsed; do not sort,
        # interpolate, or materialize a replacement distribution here.
        "quantiles": quantiles,
        "generatedAtUtc": content.generated_value,
        "recordedAt": content.generated_value,
        "resolutionDate": target.release_at.date().isoformat(),
        "provenance": {
            "submissionPath": relative,
            "mergeCommit": merge_commit_for(path, repo_root),
            "schemaVersion": SUBMISSION_SCHEMA_VERSION,
        },
    }
    if content.notes is not None:
        record["notes"] = content.notes
    return record


def ingest_challenge_submissions(
    *,
    inbox_dir: Path,
    targets_dir: Path,
    repo_root: Path,
) -> list[dict[str, Any]]:
    """Return valid challenge rows while isolating every invalid inbox file."""

    if not inbox_dir.is_dir():
        raise ChallengeSubmissionError(
            f"challenge inbox directory does not exist: {inbox_dir}"
        )
    registered_targets = load_registered_targets(targets_dir)
    # Loaded once, outside the per-file guard: an unreadable ratchet is
    # repo corruption and must abort the whole ingest, not skip rows.
    expired_registrations = expired_unforecast_registrations(repo_root)
    records: list[dict[str, Any]] = []
    # The history walk in first_accepted_content applies this same path
    # shape; the two must agree on which files are submissions at all.
    for path in sorted(inbox_dir.glob("*/*.json")):
        if not _is_submission_name(path.name):
            continue
        try:
            record = adapt_submission(
                path,
                registered_targets=registered_targets,
                repo_root=repo_root,
                expired_registrations=expired_registrations,
            )
        except ChallengeSubmissionError as error:
            try:
                display_path = path.relative_to(repo_root).as_posix()
            except ValueError:
                display_path = str(path)
            LOGGER.warning("Skipping challenge submission %s: %s", display_path, error)
            continue
        records.append(record)
    canonical = first_accepted_content(inbox_dir, repo_root)
    records = _reject_replaced_content(records, canonical, repo_root)
    return _reject_duplicate_targets(records, canonical)


def _reject_replaced_content(
    records: list[dict[str, Any]],
    canonical: dict[tuple[str, str], tuple[bytes, str]],
    repo_root: Path,
) -> list[dict[str, Any]]:
    """Refuse any record whose bytes differ from the first-accepted bytes
    for its (challenger, dataPointId) — edits, renames, and
    delete-and-readd games all land here."""

    kept: list[dict[str, Any]] = []
    for record in records:
        key = (
            str(record.get("challenger")).lower(),
            str(record.get("dataPointId")),
        )
        relative = str(record.get("provenance", {}).get("submissionPath", ""))
        current = (repo_root / relative).read_bytes()
        entry = canonical.get(key)
        if entry is not None and current != entry[0]:
            LOGGER.warning(
                "Rejecting %s: content differs from the first accepted "
                "submission for %s / %s; one shot per target is final",
                relative,
                record.get("challenger"),
                record.get("dataPointId"),
            )
            continue
        kept.append(record)
    return kept


def _reject_duplicate_targets(
    records: list[dict[str, Any]],
    canonical: dict[tuple[str, str], tuple[bytes, str]],
) -> list[dict[str, Any]]:
    """Enforce one shot per (challenger, dataPointId).

    Records reaching here are byte-identical to the first-accepted
    content for their key, so duplicates are surplus copies: exactly one
    survives — the file at the first-accepted path when it still exists,
    else the lexicographically first path — and the rest reject with a
    warning. Keys are case-insensitive on the challenger because GitHub
    logins are.
    """

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (
            str(record.get("challenger")).lower(),
            str(record.get("dataPointId")),
        )
        groups.setdefault(key, []).append(record)
    kept: list[dict[str, Any]] = []
    for key, group in groups.items():
        if len(group) == 1:
            kept.extend(group)
            continue

        def _path(record: dict[str, Any]) -> str:
            return str(record.get("provenance", {}).get("submissionPath", ""))

        first_path = canonical.get(key, (b"", ""))[1]
        chosen = next(
            (record for record in group if _path(record) == first_path),
            min(group, key=_path),
        )
        for record in group:
            if record is chosen:
                continue
            LOGGER.warning(
                "Rejecting surplus copy %s for %s / %s: one shot per target",
                _path(record),
                record.get("challenger"),
                record.get("dataPointId"),
            )
        kept.append(chosen)
    kept.sort(
        key=lambda record: str(record.get("provenance", {}).get("submissionPath", ""))
    )
    return kept


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and print merged challenge forecast records"
    )
    default_root = Path(__file__).resolve().parent.parent
    parser.add_argument("--repo-root", type=Path, default=default_root)
    parser.add_argument("--inbox", type=Path)
    parser.add_argument("--targets", type=Path)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    repo_root = args.repo_root.resolve()
    records = ingest_challenge_submissions(
        inbox_dir=args.inbox or repo_root / "challenge" / "inbox",
        targets_dir=args.targets or repo_root / "records" / "targets",
        repo_root=repo_root,
    )
    json.dump(records, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
