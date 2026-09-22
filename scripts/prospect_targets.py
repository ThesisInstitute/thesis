#!/usr/bin/env python3
"""Validate and combine untrusted prospect target proposals.

The prospect workflow has two proposal sources: a Codex web-research pass and
trusted ledger-gap mining. Both run in an unprivileged job. This module gives
that job a filtering pass and the privileged registrar an independent strict
replay against its fresh checkout before any target registration is written.
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import math
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from canonical_json import canonical_bytes
from register_targets import (
    LEGACY_REGISTRATION_SCHEMAS,
    REGISTRATION_SCHEMA,
    RegistrationError,
    build_contract,
    execution_plan_refusal,
    parse_utc_instant,
    registration_content_hash,
)
from spawned_cells_to_ts import (
    ALLOWED_COUNTRIES,
    ALLOWED_UNITS,
    SLUG_RE,
    existing_slugs,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "scripts" / "docket_series.json"
DENYLIST = ROOT / "scripts" / "docket_denylist.json"

PROPOSAL_SCHEMA = "thesis_prospect_proposals_v1"
ORIGINS = {"codex", "ledger_gap"}
SERIES_RE = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)+$")
MAX_RELEASE_HORIZON = dt.timedelta(days=75)
MAX_REGISTRATION_COMMIT_LAG = dt.timedelta(minutes=15)

REGISTRATION_OWNED_FIELDS = {
    "dataPointId",
    "registeredAt",
    "registeredAtUtc",
    "registrationCommit",
    "registrationState",
    "sourceBinding",
    "targetContentHash",
    "targetRegistrationPath",
}
COMMON_TARGET_FIELDS = {
    "series",
    "period",
    "catalogSlug",
    "country",
    "targetUnit",
    "resolutionSourceUrl",
}
CODEX_TARGET_FIELDS = COMMON_TARGET_FIELDS | {
    "expectedReleaseDate",
    "sourceSeriesId",
    "sourceField",
    "sourceTable",
    "transform",
}
LEDGER_GAP_TARGET_FIELDS = COMMON_TARGET_FIELDS | {"previousTarget"}
PREVIOUS_TARGET_FIELDS = {
    "period",
    "dataPointId",
    "country",
    "unit",
    "resolutionDate",
    "resolutionSource",
    "resolutionSourceUrl",
    "sourceBinding",
}
SOURCE_BINDING_FIELDS = {
    "adapter",
    "sourceUrl",
    "sourceSeriesId",
    "field",
    "table",
    "transform",
    "releasePolicy",
}
TRANSFORM_FIELDS = {"operation", "factor"}

GENERIC_TOKENS = (
    {
        "rate",
        "annual",
        "monthly",
        "weekly",
        "total",
        "index",
        "yoy",
        "mom",
        "us",
        "uk",
        "euro",
        "area",
        "japan",
        "canada",
        "australia",
        "belgium",
        "week",
        "prelim",
        "flash",
        "sa",
    }
    | {
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
    | {str(year) for year in range(2024, 2032)}
)


class ProspectValidationError(ValueError):
    """A proposal artifact cannot cross the registration boundary."""


@dataclass(frozen=True)
class ValidationState:
    registry_series: frozenset[str]
    catalog_slugs: frozenset[str]
    denied: frozenset[tuple[str, str]]


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def write_canonical(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def proposal_envelope(origin: str, targets: list[dict[str, Any]]) -> dict[str, Any]:
    if origin not in ORIGINS:
        raise ProspectValidationError(f"unsupported proposal origin {origin!r}")
    return {
        "schemaVersion": PROPOSAL_SCHEMA,
        "proposals": [
            {"origin": origin, "target": target}
            for target in sorted(targets, key=lambda row: row["catalogSlug"])
        ],
    }


def write_proposal_envelope(
    path: pathlib.Path, origin: str, targets: list[dict[str, Any]]
) -> None:
    write_canonical(path, proposal_envelope(origin, targets))


def load_denylist(path: pathlib.Path = DENYLIST) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    payload = json.loads(path.read_text())
    if set(payload) != {"comment", "targets"} or not isinstance(
        payload.get("targets"), list
    ):
        raise ProspectValidationError("invalid docket denylist schema")
    denied: set[tuple[str, str]] = set()
    for index, row in enumerate(payload["targets"]):
        if not isinstance(row, dict) or not {
            "series",
            "period",
            "reason",
        }.issubset(row):
            raise ProspectValidationError(f"invalid denylist target {index}")
        denied.add((str(row["series"]), str(row["period"])))
    return denied


def load_validation_state(root: pathlib.Path = ROOT) -> ValidationState:
    registry_path = root / "scripts" / "docket_series.json"
    registry = json.loads(registry_path.read_text())
    rows = registry.get("series") if isinstance(registry, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ProspectValidationError("invalid docket registry schema")
    registry_series = frozenset(str(row.get("series") or "") for row in rows)
    if "" in registry_series:
        raise ProspectValidationError("docket registry entry lacks a series")
    site_data = root / "site" / "src" / "data"
    catalog = existing_slugs(
        site_data, root / "__prospect_validator__.ts"
    )
    # Generated wave modules use JSON-quoted property names, while the shared
    # collision helper historically matched only ``slug:`` TypeScript syntax.
    # Include both representations at this privileged boundary.
    catalog_paths = [
        *site_data.glob("forecast-examples/*.ts"),
        site_data / "forecast-cells.ts",
    ]
    for path in catalog_paths:
        catalog.update(
            re.findall(r'(?:"slug"|slug):\s*"([^"]+)"', path.read_text())
        )
    return ValidationState(
        registry_series=registry_series,
        catalog_slugs=frozenset(catalog),
        denied=frozenset(load_denylist(root / "scripts" / "docket_denylist.json")),
    )


def near_duplicate(slug: str, existing: set[str] | frozenset[str]) -> str | None:
    """Return an existing slug that appears to describe the same quantity."""

    tokens = {token for token in slug.split("-") if _specific_token(token)}
    if not tokens:
        return None
    for other in sorted(existing):
        other_tokens = {
            token for token in other.split("-") if _specific_token(token)
        }
        if len(tokens & other_tokens) >= 2 or (
            len(tokens & other_tokens) == 1 and tokens <= other_tokens
        ):
            return other
    return None


def _specific_token(token: str) -> bool:
    return token not in GENERIC_TOKENS and not token.isdigit()


def _period_error(value: Any) -> str | None:
    period = str(value or "")
    month = re.fullmatch(r"(\d{4})-(\d{2})", period)
    if month:
        return None if 1 <= int(month.group(2)) <= 12 else "bad period"
    if re.fullmatch(r"\d{4}-Q[1-4]", period):
        return None
    if re.fullmatch(r"\d{4}", period):
        return None
    week = re.fullmatch(r"week_(\d{4}-\d{2}-\d{2})", period)
    if week:
        try:
            dt.date.fromisoformat(week.group(1))
        except ValueError:
            return "bad period"
        return None
    return "bad period"


def _public_https_error(value: Any, label: str) -> str | None:
    try:
        parsed = urlparse(str(value or ""))
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return f"bad {label}"
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return f"bad {label}"
    lower = host.rstrip(".").lower()
    if lower == "localhost" or lower.endswith((".localhost", ".local")):
        return f"non-public {label}"
    try:
        address = ipaddress.ip_address(lower.strip("[]"))
    except ValueError:
        if "." not in lower:
            return f"non-public {label}"
    else:
        if not address.is_global:
            return f"non-public {label}"
    return None


def _nonempty_string_error(value: Any, label: str) -> str | None:
    return None if isinstance(value, str) and value.strip() else f"missing {label}"


def _transform_errors(value: Any, label: str = "transform") -> list[str]:
    if not isinstance(value, dict) or set(value) != TRANSFORM_FIELDS:
        return [f"bad {label} schema"]
    operation = value.get("operation")
    factor = value.get("factor")
    errors = []
    if operation not in {
        "difference_previous_period",
        "identity",
        "multiply",
        "percent_change_previous_period",
        "percent_change_year_ago",
    }:
        errors.append(f"bad {label} operation")
    if type(factor) not in {int, float} or not math.isfinite(float(factor)):
        errors.append(f"bad {label} factor")
    return errors


def _source_binding_errors(value: Any) -> list[str]:
    if not isinstance(value, dict) or set(value) != SOURCE_BINDING_FIELDS:
        return ["bad previousTarget sourceBinding schema"]
    errors = []
    if value.get("adapter") not in {
        "abs-data-api",
        "abs-release-page",
        "alfred-fred",
        "bea-ita-itable",
        "bea-release",
        "bls-qcew",
        "census-spm-annual-report",
        "eia-dnav-xls",
        "eurostat-api",
        "fsa-crp-monthly-summary",
        "generic-url",
        "irs-soi-pub1304",
        "ons-timeseries",
        "statcan-wds",
        "usaspending-api",
    }:
        errors.append("bad previousTarget source adapter")
    if value.get("releasePolicy") not in {
        "first_print",
        "advance_vintage",
        "registered_query_snapshot",
    }:
        errors.append("bad previousTarget release policy")
    url_error = _public_https_error(value.get("sourceUrl"), "sourceBinding URL")
    if url_error:
        errors.append(url_error)
    for key in ("sourceSeriesId", "field", "table"):
        error = _nonempty_string_error(value.get(key), f"sourceBinding {key}")
        if error:
            errors.append(error)
    if value.get("adapter") == "bea-ita-itable":
        expected_transform = {
            "operation": "identity",
            "factor": 1,
            "applicationId": 62,
            "productId": "1",
            "tableList": "62",
            "lineNumber": "18",
            "rowLabel": "Personal transfers",
            "basis": "QSA",
            "unit": "usd_millions",
            "cadence": "quarterly",
        }
        if value.get("transform") != expected_transform:
            errors.append("bad BEA ITA sourceBinding transform")
    else:
        errors.extend(
            _transform_errors(value.get("transform"), "sourceBinding transform")
        )
    return errors


def _previous_target_errors(value: Any, target: dict[str, Any]) -> list[str]:
    if not isinstance(value, dict) or set(value) != PREVIOUS_TARGET_FIELDS:
        return ["bad previousTarget schema"]
    errors = []
    if _period_error(value.get("period")):
        errors.append("bad previousTarget period")
    for key in ("dataPointId", "resolutionSource"):
        error = _nonempty_string_error(value.get(key), f"previousTarget {key}")
        if error:
            errors.append(error)
    try:
        dt.date.fromisoformat(str(value.get("resolutionDate") or ""))
    except ValueError:
        errors.append("bad previousTarget resolutionDate")
    url_error = _public_https_error(
        value.get("resolutionSourceUrl"), "previousTarget resolution source URL"
    )
    if url_error:
        errors.append(url_error)
    if value.get("country") != target.get("country"):
        errors.append("previousTarget country differs from target")
    if value.get("unit") != target.get("targetUnit"):
        errors.append("previousTarget unit differs from target")
    errors.extend(_source_binding_errors(value.get("sourceBinding")))
    binding = (
        value.get("sourceBinding")
        if isinstance(value.get("sourceBinding"), dict)
        else {}
    )
    if binding.get("sourceUrl") != value.get("resolutionSourceUrl"):
        errors.append("previousTarget source URL differs from sourceBinding")
    if target.get("resolutionSourceUrl") != value.get("resolutionSourceUrl"):
        errors.append("target source URL differs from previousTarget")
    return errors


def validate_codex_raw_proposal(
    proposal: Any,
    *,
    today: dt.date,
    existing_slugs: set[str] | frozenset[str],
    registry_series: set[str] | frozenset[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Sanitize one raw model proposal into the versioned target shape."""

    if not isinstance(proposal, dict):
        return None, ["proposal is not an object"]
    allowed = CODEX_TARGET_FIELDS | {"rationale"}
    problems = []
    extra = set(proposal) - allowed
    if extra:
        problems.append(f"unexpected fields: {sorted(extra)}")
    target = {key: proposal.get(key) for key in CODEX_TARGET_FIELDS}
    problems.extend(
        _common_target_errors(
            target,
            origin="codex",
            today=today,
            existing_slugs=existing_slugs,
            registry_series=registry_series,
            denied=frozenset(),
        )
    )
    if problems:
        return None, problems
    return target, []


def _common_target_errors(
    target: Any,
    *,
    origin: str,
    today: dt.date,
    existing_slugs: set[str] | frozenset[str],
    registry_series: set[str] | frozenset[str],
    denied: set[tuple[str, str]] | frozenset[tuple[str, str]],
) -> list[str]:
    if not isinstance(target, dict):
        return ["target is not an object"]
    errors = []
    expected_fields = (
        CODEX_TARGET_FIELDS if origin == "codex" else LEDGER_GAP_TARGET_FIELDS
    )
    if set(target) != expected_fields:
        errors.append(
            "target schema differs: "
            f"missing={sorted(expected_fields - set(target))}, "
            f"extra={sorted(set(target) - expected_fields)}"
        )
    injected = set(target) & REGISTRATION_OWNED_FIELDS
    if injected:
        errors.append(f"registration-owned fields are forbidden: {sorted(injected)}")
    series = target.get("series")
    period = target.get("period")
    slug = target.get("catalogSlug")
    if not isinstance(series, str) or not SERIES_RE.fullmatch(series):
        errors.append("bad series id")
    if series in registry_series:
        errors.append("series already in registry")
    period_error = _period_error(period)
    if period_error:
        errors.append(period_error)
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        errors.append("bad slug")
    elif slug in existing_slugs:
        errors.append("slug exists")
    if target.get("country") not in ALLOWED_COUNTRIES:
        errors.append("bad country")
    if target.get("targetUnit") not in ALLOWED_UNITS:
        errors.append("bad unit")
    if (series, period) in denied:
        errors.append("target is denylisted")
    url_error = _public_https_error(
        target.get("resolutionSourceUrl"), "resolution source URL"
    )
    if url_error:
        errors.append(url_error)
    if origin == "codex":
        overlap = near_duplicate(str(slug or ""), existing_slugs)
        if overlap:
            errors.append(f"same quantity as existing {overlap}")
        try:
            release = dt.date.fromisoformat(
                str(target.get("expectedReleaseDate") or "")
            )
            if not (today < release <= today + MAX_RELEASE_HORIZON):
                errors.append("release outside (today, +75d]")
        except ValueError:
            errors.append("bad release date")
        for key in ("sourceSeriesId", "sourceField", "sourceTable"):
            error = _nonempty_string_error(target.get(key), key)
            if error:
                errors.append(error)
        errors.extend(_transform_errors(target.get("transform")))
    else:
        errors.extend(_previous_target_errors(target.get("previousTarget"), target))
    return errors


def _parse_envelope(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or set(payload) != {"schemaVersion", "proposals"}:
        raise ProspectValidationError("proposal artifact has an invalid envelope")
    if payload.get("schemaVersion") != PROPOSAL_SCHEMA:
        raise ProspectValidationError("unsupported proposal artifact schema")
    proposals = payload.get("proposals")
    if not isinstance(proposals, list):
        raise ProspectValidationError("proposal artifact proposals must be a list")
    return proposals


def load_envelope(
    path: pathlib.Path, *, require_canonical: bool = True
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectValidationError(
            f"invalid proposal artifact {path}: {exc}"
        ) from exc
    _parse_envelope(payload)
    if require_canonical and path.read_bytes() != canonical_bytes(payload) + b"\n":
        raise ProspectValidationError(f"proposal artifact is not canonical: {path}")
    return payload


def _git_output(root: pathlib.Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=root, text=True, stderr=subprocess.PIPE
        ).strip()
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise ProspectValidationError(
            f"git {' '.join(args)} failed" + (f": {detail}" if detail else "")
        ) from exc


def _verify_retry_snapshot(
    root: pathlib.Path,
    path: pathlib.Path,
    snapshot: dict[str, Any],
    contract: dict[str, Any],
) -> None:
    if snapshot.get("schemaVersion") != REGISTRATION_SCHEMA:
        raise ProspectValidationError(
            f"existing target is not a {REGISTRATION_SCHEMA} registration"
        )
    if canonical_bytes(snapshot.get("targets")) != canonical_bytes([contract]):
        raise ProspectValidationError("existing target registration contract differs")
    try:
        registered = parse_utc_instant(str(snapshot.get("registeredAtUtc") or ""))
        content_hash = registration_content_hash(snapshot)
    except (RegistrationError, TypeError, ValueError) as exc:
        raise ProspectValidationError(str(exc)) from exc
    relative = path.relative_to(root).as_posix()
    if path.name != f"{registered.date().isoformat()}-{content_hash}.json":
        raise ProspectValidationError("existing target registration path/hash differs")
    snapshot_bytes = canonical_bytes(snapshot) + b"\n"
    if path.read_bytes() != snapshot_bytes:
        raise ProspectValidationError("existing target registration is not canonical")
    commits = _git_output(
        root,
        "log",
        "HEAD",
        "--diff-filter=A",
        "--format=%H",
        "--",
        relative,
    ).splitlines()
    if len(commits) != 1:
        raise ProspectValidationError(
            "existing target lacks one introducing registration commit"
        )
    commit = commits[0]
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ProspectValidationError("registration commit is not an ancestor of HEAD")
    status = _git_output(
        root,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-status",
        "-r",
        commit,
        "--",
        relative,
    ).splitlines()
    if status != [f"A\t{relative}"]:
        raise ProspectValidationError("registration commit did not introduce snapshot")
    committed = subprocess.check_output(
        ["git", "show", f"{commit}:{relative}"], cwd=root
    )
    if committed != snapshot_bytes:
        raise ProspectValidationError("registration commit snapshot bytes differ")
    timestamps = _git_output(
        root, "show", "-s", "--format=%aI%n%cI", commit
    ).splitlines()
    if len(timestamps) != 2:
        raise ProspectValidationError("registration commit timestamps are missing")
    for label, value in zip(("author", "committer"), timestamps, strict=True):
        try:
            commit_time = dt.datetime.fromisoformat(value).astimezone(dt.timezone.utc)
        except ValueError as exc:
            raise ProspectValidationError(
                f"invalid registration {label} timestamp"
            ) from exc
        lag = commit_time - registered
        if lag < dt.timedelta(0) or lag > MAX_REGISTRATION_COMMIT_LAG:
            raise ProspectValidationError(
                "existing target registration is not contemporaneous with its "
                f"{label} commit time"
            )


def _validate_existing_registration(
    root: pathlib.Path, contract: dict[str, Any]
) -> bool:
    """Whether this exact contract is already a current, retryable registration."""

    targets_root = root / "records" / "targets"
    if not targets_root.exists():
        return False
    related: list[tuple[pathlib.Path, dict[str, Any], dict[str, Any]]] = []
    for path in sorted(targets_root.glob("*.json")):
        try:
            snapshot = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ProspectValidationError(
                f"invalid registration snapshot {path}"
            ) from exc
        rows = snapshot.get("targets") if isinstance(snapshot, dict) else None
        if not isinstance(rows, list):
            raise ProspectValidationError(f"invalid registration snapshot {path}")
        for row in rows:
            if not isinstance(row, dict):
                raise ProspectValidationError(f"invalid registration target {path}")
            if (
                row.get("catalogSlug") == contract["catalogSlug"]
                or row.get("dataPointId") == contract["dataPointId"]
                or (
                    row.get("series") == contract["series"]
                    and row.get("period") == contract["period"]
                )
            ):
                related.append((path, snapshot, row))
    exact_current = [
        (path, snapshot)
        for path, snapshot, row in related
        if snapshot.get("schemaVersion") == REGISTRATION_SCHEMA
        and canonical_bytes(row) == canonical_bytes(contract)
        and len(snapshot.get("targets", [])) == 1
    ]
    if exact_current:
        if len(exact_current) != 1:
            raise ProspectValidationError(
                f"multiple exact {REGISTRATION_SCHEMA} registrations exist"
            )
        _verify_retry_snapshot(
            root, exact_current[0][0], exact_current[0][1], contract
        )
        return True
    if any(
        snapshot.get("schemaVersion") in LEGACY_REGISTRATION_SCHEMAS
        and canonical_bytes(row) == canonical_bytes(contract)
        for _, snapshot, row in related
    ):
        # Pre-v3 registrations are read-only history: never retried, never
        # rewritten. The series advances to a fresh target period instead.
        raise ProspectValidationError(
            "existing pre-v3 registration is not retryable; "
            "advance the series to a fresh period"
        )
    if related:
        raise ProspectValidationError(
            "target was already attempted or conflicts with an existing registration"
        )
    return False


def validate_proposals(
    payload: Any,
    *,
    today: dt.date,
    root: pathlib.Path = ROOT,
    state: ValidationState | None = None,
    strict: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a canonical filtered envelope and batch targets projection."""

    proposals = _parse_envelope(payload)
    state = state or load_validation_state(root)
    accepted: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    seen_series_periods: set[tuple[str, str]] = set()
    seen_ids: set[str] = set()
    errors: list[str] = []
    for index, proposal in enumerate(proposals):
        row_errors = []
        if not isinstance(proposal, dict) or set(proposal) != {"origin", "target"}:
            row_errors.append("proposal entry has an invalid schema")
            origin = "?"
            target: Any = proposal.get("target") if isinstance(proposal, dict) else None
        else:
            origin = proposal.get("origin")
            target = proposal.get("target")
            if origin not in ORIGINS:
                row_errors.append(f"unsupported proposal origin {origin!r}")
        if origin in ORIGINS:
            row_errors.extend(
                _common_target_errors(
                    target,
                    origin=origin,
                    today=today,
                    existing_slugs=state.catalog_slugs | seen_slugs,
                    registry_series=state.registry_series,
                    denied=state.denied,
                )
            )
        contract = None
        if not row_errors:
            try:
                contract = build_contract(target, today)
                window = contract["sourceBinding"]["expectedReleaseWindow"]
                window_end = dt.date.fromisoformat(str(window["end"]))
                if not (today < window_end <= today + MAX_RELEASE_HORIZON):
                    row_errors.append("bound release window ends outside (today, +75d]")
            except (KeyError, TypeError, ValueError, RegistrationError) as exc:
                row_errors.append(f"target is not bindable: {exc}")
        if contract is not None and not row_errors:
            slug = str(contract["catalogSlug"])
            series_period = (str(contract["series"]), str(contract["period"]))
            data_point_id = str(contract["dataPointId"])
            if slug in seen_slugs:
                row_errors.append("duplicate catalogSlug")
            if series_period in seen_series_periods:
                row_errors.append("duplicate series/period")
            if data_point_id in seen_ids:
                row_errors.append("duplicate dataPointId")
            already_registered = False
            try:
                already_registered = _validate_existing_registration(root, contract)
            except ProspectValidationError as exc:
                row_errors.append(str(exc))
            # Bindable is not resolvable: a proposal becomes a registration,
            # so it needs the same executable plan registration demands. The
            # retry of an existing registration is not a new one. The
            # post-commit replay sees the snapshot it just wrote and takes
            # that branch, so both passes accept the same set.
            if not row_errors and not already_registered:
                try:
                    refusal = execution_plan_refusal(
                        {"contract": contract, "targetContentHash": None}
                    )
                except (AttributeError, KeyError, TypeError, ValueError) as exc:
                    refusal = f"the resolver could not judge the contract: {exc}"
                if refusal:
                    row_errors.append(f"no executable resolution plan: {refusal}")
        if row_errors:
            slug = target.get("catalogSlug", "?") if isinstance(target, dict) else "?"
            detail = f"proposal {index} ({slug}): {'; '.join(row_errors)}"
            errors.append(detail)
            if not strict:
                print(f"  reject {slug}: {'; '.join(row_errors)}", file=sys.stderr)
            continue
        assert contract is not None
        accepted.append({"origin": origin, "target": target})
        targets.append(target)
        seen_slugs.add(str(contract["catalogSlug"]))
        seen_series_periods.add((str(contract["series"]), str(contract["period"])))
        seen_ids.add(str(contract["dataPointId"]))
    if strict and errors:
        raise ProspectValidationError(
            "proposal validation failed:\n" + "\n".join(errors)
        )
    accepted.sort(key=lambda row: (row["target"]["catalogSlug"], row["origin"]))
    targets.sort(key=lambda row: row["catalogSlug"])
    return (
        {"schemaVersion": PROPOSAL_SCHEMA, "proposals": accepted},
        {"targets": targets},
    )


def combine(inputs: list[pathlib.Path], output: pathlib.Path, today: dt.date) -> None:
    proposals = []
    for path in inputs:
        if not path.exists():
            continue
        proposals.extend(_parse_envelope(load_envelope(path))[::])
    filtered, _ = validate_proposals(
        {"schemaVersion": PROPOSAL_SCHEMA, "proposals": proposals},
        today=today,
        strict=False,
    )
    write_canonical(output, filtered)
    print(f"{len(filtered['proposals'])} combined proposals")


def strict_replay(
    input_path: pathlib.Path, targets_out: pathlib.Path, today: dt.date
) -> None:
    payload = load_envelope(input_path)
    replayed, targets = validate_proposals(payload, today=today, strict=True)
    if canonical_bytes(replayed) != canonical_bytes(payload):
        raise ProspectValidationError("strict replay would rewrite proposal artifact")
    write_canonical(targets_out, targets)
    print(f"validated {len(targets['targets'])} prospect targets")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    filter_parser = subparsers.add_parser("filter")
    filter_parser.add_argument(
        "--input", action="append", type=pathlib.Path, default=[]
    )
    filter_parser.add_argument("--out", type=pathlib.Path, required=True)
    filter_parser.add_argument("--today", type=dt.date.fromisoformat)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--input", type=pathlib.Path, required=True)
    validate_parser.add_argument("--targets-out", type=pathlib.Path, required=True)
    validate_parser.add_argument("--today", type=dt.date.fromisoformat)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    today = args.today or utc_today()
    try:
        if args.command == "filter":
            combine(args.input, args.out, today)
        else:
            strict_replay(args.input, args.targets_out, today)
    except (
        OSError,
        json.JSONDecodeError,
        ProspectValidationError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"prospect validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
