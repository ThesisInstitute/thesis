#!/usr/bin/env python3
"""Forecast one catalog target with a System One model as a Noul ladder.

A System One model answers named typed questions about a state and returns
calibrated probabilities without generating text.  This runner turns one
already-published Thesis target into 15 independent yes/no (Noul) questions
of the form "the first print will be at or below t", records the request and
the raw response verbatim, monotonizes the answers into a CDF, and seals the
result as a complete v2 custody inventory under run mode ``system_one``.

The lane is a comparison lane.  It never carries a headline forecast, and it
is scored beside thesis.analyst and the persistence baseline by the existing
CRPS reward pipeline.

Backends:

* ``typesafe``       the real System One model through typesafe-sdk
* ``adapter``        the same interface emulated over an LLM provider
* ``response_file``  replay a saved SystemOneResponse JSON
* ``mock``           a deterministic offline ladder for tests and smoke runs

Only the first two import the optional ``system-one`` extra, and they import
it lazily, so ``--backend mock`` and ``--backend response_file`` run against
the repository's base environment.

Usage:
  python3 scripts/run_system_one_forecast.py \
      --target-json /tmp/target.json \
      --ledger-jsonl /tmp/official_observations.jsonl \
      --backend mock

  python3 scripts/run_system_one_forecast.py \
      --target-json /tmp/target.json \
      --primary-cell records/thesis-analyst/<day>/<run>/cells.with_activity.json \
      --backend adapter --provider openai --model gpt-5.5 \
      --records-root /tmp/system-one-smoke
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import math
import os
import pathlib
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import Any

import stamp_docket_ledger_refs
from canonical_json import canonical_bytes, canonical_sha256
from run_thesis_analyst import (
    CUSTODY_INVENTORY_VERSION,
    MANIFEST_HASH_MODE,
    custody_artifact_entry,
    decimal_places,
    ladder_distribution,
    ladder_interpolate,
    manifest_self_hash_payload,
    sha256_bytes,
    slugify,
    write_artifact,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_RECORDS_ROOT = ROOT / "records"

RUN_MODE = "system_one"
MANIFEST_SCHEMA = "thesis_system_one_run_manifest_v1"
STATE_SCHEMA = "thesis_system_one_state_v1"
QUESTIONS_SCHEMA = "thesis_system_one_questions_v1"
REQUEST_SCHEMA = "thesis_system_one_request_v1"
PROMPT_MODE = "system_one_noul_ladder"
AGENT_NAME = "thesis.system_one"
AGENT_VERSION = "0.1.0"
MONOTONIZATION = "pav_v1"
BACKENDS = ("typesafe", "adapter", "response_file", "mock")

LADDER_RUNG_COUNT = 15
MIN_LADDER_OBSERVATIONS = 3
MIN_DISTINCT_THRESHOLDS = 5
LADDER_SPAN_SIGMAS = 3.0
# The dispersion statistic is an 80% half-width (the 80th percentile of
# absolute one-step changes, the persistence-baseline convention in
# docs/brier-lab.md).  Dividing by the standard normal 80% quantile turns it
# into a sigma so the ladder spans a fixed number of sigmas either side.
P80_TO_SIGMA = 1.2816
SCALE_FLOOR = 1e-9
DISPERSION_QUANTILE = 0.8

QUESTION_TEMPLATE = (
    "The official first print of {title} for {period} will be at or below "
    "{value}."
)

# Every forecast-bearing field of the published primary cell.  The state is
# built from an explicit allowlist rather than by deleting these, so this
# tuple is both the documented redaction and the assertion the runner and its
# tests check the serialized state and questions against.
REDACTED_CELL_FIELDS = (
    "pointEstimate",
    "ciLow",
    "ciHigh",
    "confidence",
    "drivers",
    "reasoning",
    "predictionDistribution",
    "thresholdLadder",
    "preSubmitReview",
    "activityLog",
    "model",
    "runAt",
)

# Hashed into agent.toolPolicyHash.  The policy is per backend because the
# backends are not the same mechanism.  Only ``typesafe`` is the System One
# interface, where TypeSafe states that every question is evaluated
# independently and in isolation and no text is generated.  The adapter
# emulates that interface over a general LLM: system-one-adapter 0.1.3
# serializes the state once and sends all fifteen questions in a single
# structured-output request, and the provider model may reason before it
# emits the probabilities.  A run must never claim the isolation it did not
# get, so the claim lives in the hashed policy and in the cell narrative.
BACKEND_POLICY_BASE = {
    "schemaVersion": "thesis_system_one_backend_policy_v2",
    "tools": [],
    "webAccess": False,
    "questionTypes": ["noul"],
    "statePreResolutionOnly": True,
    "redactedPrimaryCellFields": list(REDACTED_CELL_FIELDS),
}
BACKEND_POLICIES = {
    "typesafe": {
        "elicitation": "system_one_native",
        "questionIsolation": "vendor_asserted_independent",
        "chainOfThought": "none",
        "generatesText": False,
    },
    "adapter": {
        "elicitation": "llm_structured_output_emulation",
        "questionIsolation": "single_request_all_questions",
        "chainOfThought": "provider_default",
        "generatesText": True,
    },
    "response_file": {
        "elicitation": "recorded_response_replay",
        "questionIsolation": "inherited_from_recorded_run",
        "chainOfThought": "inherited_from_recorded_run",
        "generatesText": False,
    },
    "mock": {
        "elicitation": "deterministic_offline_ladder",
        "questionIsolation": "not_a_model",
        "chainOfThought": "none",
        "generatesText": False,
    },
}


def backend_policy(backend: str) -> dict[str, Any]:
    """The canonical policy JSON hashed into agent.toolPolicyHash."""

    if backend not in BACKEND_POLICIES:
        raise SystemOneInputError(f"unsupported backend: {backend!r}")
    return {**BACKEND_POLICY_BASE, "backend": backend, **BACKEND_POLICIES[backend]}

LADDER_POLICY = {
    "schemaVersion": "thesis_system_one_ladder_policy_v1",
    "questionTemplate": QUESTION_TEMPLATE,
    "rungCount": LADDER_RUNG_COUNT,
    "minObservations": MIN_LADDER_OBSERVATIONS,
    "minDistinctThresholds": MIN_DISTINCT_THRESHOLDS,
    "spanSigmas": LADDER_SPAN_SIGMAS,
    "p80ToSigma": P80_TO_SIGMA,
    "dispersionQuantile": DISPERSION_QUANTILE,
    "scaleFloor": SCALE_FLOOR,
    "monotonization": MONOTONIZATION,
    "bases": ["ledger_dispersion", "history_dispersion"],
}

PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
FISCAL_YEAR_RE = re.compile(r"FY[-_ ]?(\d{4})", re.IGNORECASE)
# Catalog geography ids per country code, taken from the map
# scripts/stamp_docket_ledger_refs.py already binds docket series with; a
# country it does not name spells its own ISO code in the ledger.  A row for
# another geography is not this target's series.
COUNTRY_GEOGRAPHY_IDS = dict(stamp_docket_ledger_refs.COUNTRY_IDS)
TYPESAFE_KEY_ENV = "TYPESAFE_API_KEY"
DEFAULT_ADAPTER_PROVIDER = "openai"
DEFAULT_ADAPTER_MODEL = "gpt-5.5"

SUCCESS_INVENTORY = (
    ("system_one_state", "state.json"),
    ("system_one_questions", "questions.json"),
    ("system_one_request", "request.json"),
    ("system_one_response", "response.json"),
    ("command", "command.json"),
    ("normalized_cell", "normalized_cells.json"),
    ("run_distribution", "distribution.json"),
    ("validation_report", "validation.json"),
    ("cells_with_activity", "cells.with_activity.json"),
)
FAILURE_INVENTORIES = {
    "state": (
        ("system_one_state", "state.json"),
        ("error", "error.json"),
    ),
    "backend": (
        ("system_one_state", "state.json"),
        ("system_one_questions", "questions.json"),
        ("system_one_request", "request.json"),
        ("command", "command.json"),
        ("error", "error.json"),
    ),
    "ladder": (
        ("system_one_state", "state.json"),
        ("system_one_questions", "questions.json"),
        ("system_one_request", "request.json"),
        ("system_one_response", "response.json"),
        ("command", "command.json"),
        ("error", "error.json"),
    ),
    "validate": (
        ("system_one_state", "state.json"),
        ("system_one_questions", "questions.json"),
        ("system_one_request", "request.json"),
        ("system_one_response", "response.json"),
        ("command", "command.json"),
        ("normalized_cell", "normalized_cells.json"),
        ("run_distribution", "distribution.json"),
        ("error", "error.json"),
    ),
}

RESOLVER_CELL_FIELDS = (
    ("slug", "catalogSlug"),
    ("country", "country"),
    ("resolutionDate", "resolutionDate"),
    ("resolutionSource", "resolutionSource"),
    ("resolutionSourceUrl", "resolutionSourceUrl"),
    ("resolutionRule", "resolutionRule"),
    ("dataPointId", "dataPointId"),
)
REGISTRATION_FIELDS = (
    "registrationCommit",
    "targetContentHash",
    "targetRegistrationPath",
    "registeredAtUtc",
)


def target_unit(target: dict[str, Any]) -> str | None:
    """Trusted selection targets carry targetUnit; registration snapshots
    carry unit. Either names the registered scoring unit."""

    return target.get("targetUnit") or target.get("unit") or None


class SystemOneInputError(ValueError):
    """Bad inputs, refused before any run directory exists."""


class SystemOneRunError(RuntimeError):
    """A sealed failure: the run directory keeps a phase inventory."""

    def __init__(self, phase: str, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.phase = phase
        self.message = message
        self.detail = detail


# --- small helpers ----------------------------------------------------------


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def repo_relative(path: pathlib.Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def run_stamp(run_at: str) -> str:
    """The timestamp-first directory stamp median_rollout_ensemble.py builds."""

    return run_at.lower().replace(":", "-").replace("+00-00", "z")


def quantile(values: list[float], probability: float) -> float:
    """Port of the quantile in site/src/data/time-series-priors.ts."""

    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        return 0.0
    if len(finite) == 1:
        return finite[0]
    index = (len(finite) - 1) * probability
    lower_index = math.floor(index)
    upper_index = math.ceil(index)
    lower = finite[lower_index]
    upper = finite[upper_index]
    if lower_index == upper_index:
        return lower
    return lower + (upper - lower) * (index - lower_index)


def pav_monotone(values: list[float]) -> list[float]:
    """Pool adjacent violators: the least-squares non-decreasing fit."""

    blocks: list[list[float]] = []
    for value in values:
        blocks.append([float(value), 1.0])
        while (
            len(blocks) > 1
            and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]
        ):
            total, weight = blocks.pop()
            blocks[-1][0] += total
            blocks[-1][1] += weight
    monotone: list[float] = []
    for total, weight in blocks:
        monotone.extend([total / weight] * int(weight))
    return monotone


def clamp_unit(values: list[float]) -> list[float]:
    return [min(max(value, 0.0), 1.0) for value in values]


def round_probability(value: float) -> float:
    return round(value, 10) + 0.0


def period_phrase(period: str) -> str:
    if period.startswith("week_"):
        return f"week ending {period[len('week_'):]}"
    return period


def load_json(path: pathlib.Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SystemOneInputError(f"invalid {label} {path}: {exc}") from exc


def package_version(name: str) -> str | None:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - importlib.metadata is stdlib
        return None
    try:
        return version(name)
    except PackageNotFoundError:
        return None


# --- evidence boundary ------------------------------------------------------


def target_contract(target: dict[str, Any], primary_cell: dict[str, Any]) -> dict:
    """The public, pre-resolution contract the model is allowed to see."""

    return {
        "catalogSlug": target.get("catalogSlug"),
        "title": primary_cell.get("title"),
        "question": primary_cell.get("question"),
        "unit": target_unit(target),
        "country": target.get("country"),
        "series": target.get("series"),
        "period": target.get("period"),
        "dataPointId": target.get("dataPointId"),
        "resolutionDate": target.get("resolutionDate"),
        "resolutionRule": target.get("resolutionRule"),
        "resolutionSource": target.get("resolutionSource"),
        "resolutionSourceUrl": target.get("resolutionSourceUrl"),
    }


def history_rows(primary_cell: dict[str, Any]) -> list[dict[str, Any]]:
    """The primary cell's historicalContext as {label, value, period} rows."""

    rows: list[dict[str, Any]] = []
    for entry in primary_cell.get("historicalContext") or []:
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        rows.append(
            {
                "label": entry.get("label"),
                "value": value,
                "period": entry.get("period"),
            }
        )
    return rows


def period_identity(period: Any) -> tuple[str, str] | None:
    """A comparable (type, value) identity for a canonical period object.

    Ledger rows spell an annual or fiscal-year period as a number
    (``{"type": "fiscal_year", "value": 2025}``), so the value is coerced to
    its decimal string rather than dropped.
    """

    if isinstance(period, dict):
        kind = period.get("type")
        value = period.get("value")
        if not isinstance(kind, str):
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return (kind, str(value))
        if isinstance(value, float) and value.is_integer():
            return (kind, str(int(value)))
        if isinstance(value, str) and value:
            return (kind, value)
        return None
    if isinstance(period, str) and period:
        return (period_kind(period), period)
    return None


def period_kind(value: str) -> str:
    if value.startswith("week_"):
        return "week_ending"
    body = value
    if len(body) == 7 and body[4] == "-":
        return "month"
    if len(body) == 7 and body[4:6] == "-Q":
        return "quarter"
    if len(body) == 10 and body[4] == "-" and body[7] == "-":
        return "week_ending"
    if len(body) == 4:
        return "year"
    return "other"


def target_period_identity(target: dict[str, Any]) -> tuple[str, str]:
    period = str(target.get("period") or "")
    if period.startswith("week_"):
        return ("week_ending", period[len("week_") :])
    fiscal = FISCAL_YEAR_RE.fullmatch(period)
    if fiscal:
        # Docket targets spell a fiscal year FY2026; the ledger spells the
        # same period {"type": "fiscal_year", "value": 2026}.
        return ("fiscal_year", fiscal.group(1))
    return (period_kind(period), period)


def geography_identity(target: dict[str, Any]) -> str | None:
    """The catalog geography id a same-series ledger row must carry.

    Docket targets are national releases.  The ledger keys identity by
    (concept, geography, entity), so one concept legitimately owns one row
    per state as well as the national row; matching on concept and unit
    alone pools them.  The country ids are the ones
    scripts/stamp_docket_ledger_refs.py already binds docket series with.
    """

    country = target.get("country")
    if not isinstance(country, str) or not country:
        return None
    return COUNTRY_GEOGRAPHY_IDS.get(country, country)


def ledger_selection(
    target: dict[str, Any],
    ledger_rows: list[dict[str, Any]],
    run_started_at: str,
) -> dict[str, Any]:
    """Same-series official observations strictly before the target period.

    Match rule: measure.concept or measure.source_concept equals the target's
    sourceBinding.sourceSeriesId or series, unit equals targetUnit, the row's
    geography is the target country's national geography, the observation's
    period precedes the target period at the same granularity, and observed_at
    precedes this run's start instant.

    The ledger keys identity by (concept, geography, entity), so the same
    concept owns one row per state as well as the national row, and one
    concept can carry sibling entity lineages.  Both would silently pool into
    one series here, so geography is part of the key and, when the surviving
    rows disagree about entity, only the lineage of the most recent
    observation is kept.  Everything dropped is counted and recorded in the
    state, so a fallback to the history basis is never silent.
    """

    binding = target.get("sourceBinding") or {}
    identifiers = {
        str(value)
        for value in (binding.get("sourceSeriesId"), target.get("series"))
        if value
    }
    unit = target_unit(target)
    target_kind, target_value = target_period_identity(target)
    geography_id = geography_identity(target)

    matched: list[dict[str, Any]] = []
    rejected = {"geography": 0, "period": 0, "observedAt": 0, "value": 0}
    for row in ledger_rows:
        if not isinstance(row, dict):
            continue
        measure = row.get("measure")
        if not isinstance(measure, dict):
            continue
        concepts = {
            str(value)
            for value in (measure.get("concept"), measure.get("source_concept"))
            if value
        }
        if not concepts & identifiers:
            continue
        if measure.get("unit") != unit:
            continue
        geography = row.get("geography")
        if isinstance(geography, dict):
            if (
                geography.get("level") != "country"
                or str(geography.get("id")) != str(geography_id)
            ):
                rejected["geography"] += 1
                continue
        elif geography is not None:
            rejected["geography"] += 1
            continue
        identity = period_identity(row.get("period"))
        if identity is None or identity[0] != target_kind:
            rejected["period"] += 1
            continue
        if identity[1] >= target_value:
            continue
        observed_at = str(row.get("observed_at") or "")
        if not observed_at or not observed_before(observed_at, run_started_at):
            rejected["observedAt"] += 1
            continue
        value = row.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            rejected["value"] += 1
            continue
        matched.append(
            {
                "label": row.get("label"),
                "value": value,
                "period": {"type": identity[0], "value": identity[1]},
                "unit": measure.get("unit"),
                "observedAt": observed_at,
                "sourceRecordId": row.get("source_record_id"),
                "_entity": canonical_bytes(row.get("entity")).decode(),
            }
        )
    matched.sort(key=lambda row: (row["period"]["value"], row["observedAt"]))
    lineage: str | None = None
    if matched:
        lineage = matched[-1]["_entity"]
        kept = [row for row in matched if row["_entity"] == lineage]
        rejected["entity"] = len(matched) - len(kept)
        matched = kept
    else:
        rejected["entity"] = 0
    for row in matched:
        del row["_entity"]
    return {
        "rows": matched,
        "geographyId": geography_id,
        "entityLineage": json.loads(lineage) if lineage is not None else None,
        "rejectedRows": rejected,
    }


def observed_before(observed_at: str, run_started_at: str) -> bool:
    """observed_at strictly precedes the run start instant.

    Both are ISO-8601 UTC as the ledger and the runner write them, so the
    comparison is lexical on the full instant.  A date-only observed_at is
    treated as that day's start.
    """

    if len(observed_at) == 10:
        observed_at = f"{observed_at}T00:00:00Z"
    return observed_at < run_started_at


def ledger_matches(
    target: dict[str, Any],
    ledger_rows: list[dict[str, Any]],
    run_started_at: str,
) -> list[dict[str, Any]]:
    """The matched rows alone; see ledger_selection for the full rule."""

    return ledger_selection(target, ledger_rows, run_started_at)["rows"]


def read_ledger(path: pathlib.Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise SystemOneInputError(f"unreadable ledger {path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemOneInputError(
                f"invalid ledger line {number} in {path}: {exc}"
            ) from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


def source_context(primary_cell: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for url in primary_cell.get("sourceContext") or []:
        if isinstance(url, str) and url and url not in urls:
            urls.append(url)
    return urls


def build_state(
    *,
    target: dict[str, Any],
    primary_cell: dict[str, Any],
    primary_provenance: dict[str, Any],
    ledger: dict[str, Any],
    run_started_at: str,
) -> dict[str, Any]:
    """The evidence state, rebuildable from trusted inputs alone.

    Every field is a pure function of the trusted target, the published
    primary cell, and the pinned ledger, so the publication boundary
    recomputes this whole object and compares it byte for byte.
    """

    binding = target.get("sourceBinding") or {}
    return {
        "schemaVersion": STATE_SCHEMA,
        "generatedAt": run_started_at,
        "target": target_contract(target, primary_cell),
        "historicalContext": {
            "provenance": "agent_reported",
            "note": (
                "Reported by the published thesis.analyst run for this target, "
                "not re-fetched here."
            ),
            "rows": history_rows(primary_cell),
        },
        "ledgerObservations": {
            "provenance": "official_ledger",
            "note": (
                "Same-series official first prints pinned from the ledger "
                "before this run started."
            ),
            "matchRule": {
                "seriesIdentifiers": sorted(
                    {
                        str(value)
                        for value in (
                            binding.get("sourceSeriesId"),
                            target.get("series"),
                        )
                        if value
                    }
                ),
                "unit": target_unit(target),
                "geographyId": ledger.get("geographyId"),
                "entityLineage": ledger.get("entityLineage"),
                "periodBefore": target.get("period"),
                "observedBefore": run_started_at,
            },
            "rejectedRows": ledger.get("rejectedRows"),
            "rows": ledger.get("rows") or [],
        },
        "sourceContext": {
            "provenance": "agent_reported",
            "note": "Listed for context only; no URL is fetched by this lane.",
            "urls": source_context(primary_cell),
        },
        "redaction": {
            "cellFields": list(REDACTED_CELL_FIELDS),
            "note": (
                "The state is assembled from an allowlist of contract and "
                "history fields. No forecast field of the primary cell is "
                "read, so none can reach the model."
            ),
        },
        "primaryCellProvenance": primary_provenance,
    }


def redaction_violations(
    primary_cell: dict[str, Any], payloads: list[Any]
) -> list[str]:
    """Redacted keys, and distinctive redacted strings, must be absent."""

    violations: list[str] = []
    for payload in payloads:
        for key in sorted(_all_keys(payload)):
            if key in REDACTED_CELL_FIELDS:
                violations.append(f"redacted key {key} appears in the state")
    serialized = "\n".join(
        json.dumps(payload, sort_keys=True, default=str) for payload in payloads
    )
    # Text the state is allowed to carry: every string under a non-redacted
    # primary-cell field (title, question, resolution rule, source URLs,
    # historical context labels). A reasoning heading or driver that merely
    # repeats the target's own title is not a leak, so redacted text that is
    # contained in an allowed string is exempt from the value scan.
    allowed = {
        text
        for key, value in primary_cell.items()
        if key not in REDACTED_CELL_FIELDS
        for text in _all_strings(value)
    }
    # Prose only. Public URLs, record paths and digests legitimately appear on
    # both sides (the state pins the primary cell's own custody path), so the
    # value scan looks for multi-word text of real length: driver phrases,
    # reasoning steps and review findings, which have no business in a state
    # the model reads.
    for field in REDACTED_CELL_FIELDS:
        if field not in primary_cell:
            continue
        for text in sorted(_all_strings(primary_cell[field])):
            if len(text) < 24 or " " not in text or text not in serialized:
                continue
            if any(text in allowed_text for allowed_text in allowed):
                continue
            violations.append(
                f"redacted {field} content appears in the state: {text[:40]!r}"
            )
    return sorted(set(violations))


def _all_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys |= _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _all_keys(item)
    return keys


def _all_strings(value: Any) -> set[str]:
    strings: set[str] = set()
    if isinstance(value, str):
        strings.add(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            strings.add(str(key))
            strings |= _all_strings(item)
    elif isinstance(value, list):
        for item in value:
            strings |= _all_strings(item)
    return strings


# --- ladder construction ----------------------------------------------------


def dispersion_scale(values: list[float]) -> float:
    changes = [abs(later - earlier) for earlier, later in zip(values, values[1:])]
    return max(quantile(changes, DISPERSION_QUANTILE), SCALE_FLOOR)


def build_ladder(
    *,
    ledger_observations: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Center, scale and 15 rounded thresholds, or a closed failure."""

    ordered_history, history_refusal = history_series(history)
    if len(ledger_observations) >= MIN_LADDER_OBSERVATIONS:
        basis = "ledger_dispersion"
        rows = ledger_observations
    elif history_refusal is None and len(ordered_history) >= MIN_LADDER_OBSERVATIONS:
        basis = "history_dispersion"
        rows = ordered_history
    else:
        reason = history_refusal or "insufficient_history"
        raise SystemOneRunError(
            "state",
            reason,
            {
                "reason": reason,
                "ledgerObservations": len(ledger_observations),
                "historicalContextRows": len(history),
                "datedHistoryRows": len(ordered_history),
                "required": MIN_LADDER_OBSERVATIONS,
            },
        )

    values = [float(row["value"]) for row in rows]
    center = values[-1]
    scale = dispersion_scale(values)
    sigma = scale / P80_TO_SIGMA
    half_width = LADDER_SPAN_SIGMAS * sigma
    precision = max(decimal_places(value) for value in values)
    step = (2 * half_width) / (LADDER_RUNG_COUNT - 1)
    raw = [center - half_width + step * index for index in range(LADDER_RUNG_COUNT)]
    thresholds: list[float] = []
    for value in raw:
        rounded = round(value, precision) + 0.0
        if not thresholds or rounded > thresholds[-1]:
            thresholds.append(rounded)
    if len(thresholds) < MIN_DISTINCT_THRESHOLDS:
        raise SystemOneRunError(
            "state",
            "ladder_collapsed_under_rounding",
            {
                "reason": "ladder_collapsed_under_rounding",
                "ladderBasis": basis,
                "center": center,
                "scale": scale,
                "precision": precision,
                "distinctThresholds": len(thresholds),
                "required": MIN_DISTINCT_THRESHOLDS,
            },
        )
    return {
        "ladderBasis": basis,
        "center": center,
        "scale": scale,
        "scaleMethod": "p80_absolute_successive_change",
        "sigma": sigma,
        "precision": precision,
        "observationCount": len(values),
        "thresholds": thresholds,
    }


MONTH_NUMBERS = {
    name: number
    for number, name in enumerate(
        (
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ),
        start=1,
    )
}
LABEL_PERIOD_PATTERNS = (
    ("week_ending", re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")),
    ("quarter", re.compile(r"(?<!\w)(\d{4})[-\s_]?[Qq]([1-4])(?!\d)")),
    ("quarter", re.compile(r"(?<!\w)[Qq]([1-4])[-\s_](\d{4})(?!\d)")),
    ("month", re.compile(r"(?<!\d)(\d{4})-(0[1-9]|1[0-2])(?!\d)")),
    (
        "month",
        re.compile(
            r"(?<![A-Za-z])(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"[A-Za-z]*\.?[\s_-]+(\d{4})(?!\d)",
            re.IGNORECASE,
        ),
    ),
    ("fiscal_year", re.compile(r"(?<!\w)FY[\s_-]?(\d{4})(?!\d)", re.IGNORECASE)),
    ("year", re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")),
)


def label_period_identity(label: Any) -> tuple[str, str] | None:
    """Read a period out of a history row label.

    Most published cells report historicalContext rows with a null period and
    the period only in the label ("May 2026 real AHE MoM, Table A-1").  The
    ladder needs an order, and the reported order is not one, so the label is
    parsed rather than trusted.  Nothing is guessed: a row whose label names
    no period is dropped, and history that does not resolve to one dated
    series is refused outright.
    """

    if not isinstance(label, str) or not label:
        return None
    for kind, pattern in LABEL_PERIOD_PATTERNS:
        match = pattern.search(label)
        if not match:
            continue
        if kind == "week_ending":
            return (kind, match.group(1))
        if kind == "quarter":
            first, second = match.group(1), match.group(2)
            year, quarter = (first, second) if len(first) == 4 else (second, first)
            return (kind, f"{year}-Q{quarter}")
        if kind == "month":
            first, second = match.group(1), match.group(2)
            if first.isdigit() and len(first) == 4:
                return (kind, f"{first}-{second}")
            return (kind, f"{second}-{MONTH_NUMBERS[first[:3].lower()]:02d}")
        return (kind, match.group(1))
    return None


def history_identity(row: dict[str, Any]) -> tuple[str, str] | None:
    identity = period_identity(row.get("period"))
    if identity is not None:
        return identity
    return label_period_identity(row.get("label"))


def history_series(
    history: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    """Order agent-reported history as one dated series, or say why not.

    Published cells mix series in one historicalContext list: a four-week
    average beside its weekly prints, a CPI row beside the real-earnings rows
    it explains, a second program beside the target program.  Read in the
    reported order they look like a series and they are not, so the rows are
    ordered by their own period and the list is refused when the periods
    repeat (two lineages) or disagree about granularity.  Undated rows are
    dropped, never reordered into the series.
    """

    dated: list[tuple[tuple[str, str], dict[str, Any]]] = []
    for row in history:
        identity = history_identity(row)
        if identity is None:
            continue
        dated.append((identity, row))
    kinds = {identity[0] for identity, _row in dated}
    values = [identity[1] for identity, _row in dated]
    if len(kinds) > 1:
        return ([], "history_period_kinds_differ")
    if len(set(values)) != len(values):
        return ([], "history_periods_repeat")
    ordered = [row for _identity, row in sorted(dated, key=lambda pair: pair[0][1])]
    return (ordered, None)


def question_title(title: str, period: str) -> str:
    """Drop a period the title already repeats.

    Published titles often end with the period ("US initial claims, week
    ending 2026-09-19"), and the question template names the period itself.
    Trimming the duplicate keeps the template exactly as specified and the
    sentence readable; the trim is a suffix match, never a rewrite.
    """

    stripped = title.strip()
    if period and stripped.lower().endswith(period.lower()):
        trimmed = stripped[: len(stripped) - len(period)].rstrip(" ,;:-")
        if trimmed:
            return trimmed
    return stripped


LADDER_QUESTION_FIELDS = (
    "ladderBasis",
    "center",
    "scale",
    "scaleMethod",
    "sigma",
    "precision",
    "observationCount",
    "thresholds",
)


def build_questions(
    *,
    ladder: dict[str, Any],
    payloads: dict[str, dict[str, str]],
    ledger_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """questions.json: the ladder geometry and the questions as sent.

    Like the state, it is a pure function of trusted inputs, so the
    publication boundary rebuilds it and compares it byte for byte instead
    of trusting the thresholds the run happened to seal.
    """

    return {
        "schemaVersion": QUESTIONS_SCHEMA,
        "questionType": "noul",
        "questionTemplate": QUESTION_TEMPLATE,
        "monotonization": MONOTONIZATION,
        **{key: ladder[key] for key in LADDER_QUESTION_FIELDS},
        "ledgerSourceRecordIds": [
            row.get("sourceRecordId") for row in ledger_observations
        ],
        "questions": payloads,
    }


def question_payloads(
    *, contract: dict[str, Any], thresholds: list[float], precision: int
) -> dict[str, dict[str, str]]:
    period = period_phrase(str(contract.get("period") or ""))
    title = question_title(
        str(contract.get("title") or contract.get("catalogSlug") or "the series"),
        period,
    )
    unit = contract.get("unit") or ""
    payloads: dict[str, dict[str, str]] = {}
    for index, threshold in enumerate(thresholds, start=1):
        payloads[f"rung_{index:02d}"] = {
            "type": "noul",
            "instructions": QUESTION_TEMPLATE.format(
                title=title,
                period=period,
                value=f"{threshold:.{precision}f}" + (f" {unit}" if unit else ""),
            ),
        }
    return payloads


# --- backends ---------------------------------------------------------------


def mock_probability(name: str, threshold: float, center: float, sigma: float) -> float:
    """A deterministic offline answer: a normal CDF with a fixed per-rung tilt.

    The tilt is a function of the question name alone, so a mock run is
    reproducible across targets, and it is small enough that the ladder keeps
    its mass on the rungs while still giving the monotonization something to
    correct.
    """

    z = (threshold - center) / max(sigma, SCALE_FLOOR)
    base = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    digest = sha256_bytes(name.encode())
    tilt = (int(digest[:2], 16) / 255.0 - 0.5) * 0.02
    return min(max(base + tilt, 0.0), 1.0)


def call_mock(
    *, payloads: dict[str, dict[str, str]], ladder: dict[str, Any]
) -> dict[str, Any]:
    answers = {}
    for (name, _payload), threshold in zip(payloads.items(), ladder["thresholds"]):
        answers[name] = {
            "type": "noul",
            "noul": round_probability(
                mock_probability(
                    name, float(threshold), ladder["center"], ladder["sigma"]
                )
            ),
        }
    return {
        "model": "mock",
        "usage": {"input_tokens": None, "output_tokens": None},
        "answers": answers,
    }


def call_response_file(path: pathlib.Path) -> dict[str, Any]:
    payload = load_json(path, "system one response file")
    if not isinstance(payload, dict):
        raise SystemOneInputError("response file must be a JSON object")
    if not isinstance(payload.get("model"), str):
        raise SystemOneInputError("response file lacks a model string")
    answers = payload.get("answers")
    if not isinstance(answers, dict) or not answers:
        raise SystemOneInputError("response file lacks an answers object")
    usage = payload.get("usage")
    if usage is not None and not isinstance(usage, dict):
        raise SystemOneInputError("response file usage must be an object or null")
    return {
        "model": payload["model"],
        "usage": usage if isinstance(usage, dict) else {},
        "answers": answers,
        **(
            {"debug": payload["debug"]}
            if isinstance(payload.get("debug"), dict)
            else {}
        ),
    }


@contextlib.contextmanager
def backend_phase(label: str):
    """Seal anything raised inside as a backend-phase failure.

    Only the exception class name is recorded. A client constructor or an
    SDK error can carry request text, and the lane never writes anything a
    key could travel in.
    """

    try:
        yield
    except SystemOneRunError:
        raise
    except Exception as exc:  # noqa: BLE001 - class name only, never the text
        raise SystemOneRunError(
            "backend",
            f"{label} failed: {type(exc).__name__}",
            {"exception": type(exc).__name__},
        ) from exc


def call_typesafe(
    *,
    state: dict[str, Any],
    payloads: dict[str, dict[str, str]],
    model: str | None,
) -> dict[str, Any]:
    try:
        import msgspec
        from typesafe_sdk import Noul, TypeSafeClient
    except ImportError as exc:  # pragma: no cover - needs the extra absent
        raise SystemOneRunError(
            "backend",
            "typesafe backend requires the system-one extra "
            "(uv sync --extra system-one)",
            {"exception": type(exc).__name__},
        ) from exc
    with backend_phase("typesafe setup"):
        questions = {
            name: Noul(instructions=payload["instructions"])
            for name, payload in payloads.items()
        }
        _assert_request_fidelity(msgspec, questions, payloads)
        client = TypeSafeClient(model=model)
    with backend_phase("system_one call"):
        return msgspec.to_builtins(client.system_one(state, questions))


def call_adapter(
    *,
    state: dict[str, Any],
    payloads: dict[str, dict[str, str]],
    provider: str,
    model: str,
) -> dict[str, Any]:
    try:
        import msgspec
        from system_one_adapter import Noul, SystemOneAdapterClient
    except ImportError as exc:  # pragma: no cover - needs the extra absent
        raise SystemOneRunError(
            "backend",
            "adapter backend requires the system-one extra "
            "(uv sync --extra system-one)",
            {"exception": type(exc).__name__},
        ) from exc
    with backend_phase("adapter setup"):
        questions = {
            name: Noul(instructions=payload["instructions"])
            for name, payload in payloads.items()
        }
        _assert_request_fidelity(msgspec, questions, payloads)
        client = SystemOneAdapterClient(
            structured_outputs=True,
            llm_answer_mode="probabilities",
            normalize_probabilities=True,
            provider=provider,
            model=model,
        )
    with backend_phase("system_one call"):
        return msgspec.to_builtins(client.system_one(state, questions))


def _assert_request_fidelity(msgspec_module, questions, payloads) -> None:
    """request.json must be the questions that were actually sent."""

    encoded = msgspec_module.to_builtins(questions)
    if encoded != payloads:
        raise SystemOneRunError(
            "backend",
            "recorded request does not match the SDK question objects",
            {"reason": "request_fidelity"},
        )


def noul_probabilities(response: dict[str, Any], names: list[str]) -> list[float]:
    answers = response.get("answers")
    if not isinstance(answers, dict):
        raise SystemOneRunError(
            "ladder", "response has no answers object", {"reason": "no_answers"}
        )
    missing = [name for name in names if name not in answers]
    extra = [name for name in answers if name not in names]
    if missing or extra:
        raise SystemOneRunError(
            "ladder",
            "response question names do not match the ladder",
            {"reason": "question_mismatch", "missing": missing, "unexpected": extra},
        )
    probabilities: list[float] = []
    for name in names:
        answer = answers[name]
        if not isinstance(answer, dict) or "noul" not in answer:
            raise SystemOneRunError(
                "ladder",
                f"answer {name} is not a Noul answer",
                {"reason": "not_noul", "question": name},
            )
        value = answer["noul"]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise SystemOneRunError(
                "ladder",
                f"answer {name} is not numeric",
                {"reason": "not_numeric", "question": name},
            )
        probabilities.append(float(value))
    return probabilities


# --- lane identity ----------------------------------------------------------

SYSTEM_ONE_LABEL = "System One threshold ladder"
EVIDENCE_SENTENCE = (
    "The evidence state carries the target contract, the reported historical "
    "prints, and the same-series official observations pinned before this run "
    "started, with every forecast field of the published cell withheld."
)


def backend_descriptor(backend: str, model: str | None) -> str:
    """How the run names its own machinery.

    ``model`` is the manifest agent's model: the identifier the model
    returned for typesafe, and ``provider/model`` for the adapter.
    """

    if backend in ("adapter", "typesafe") and model:
        return f"{backend}: {model}"
    return backend


def lane_label(backend: str, model: str | None) -> str:
    """The label a reader sees on the cell and in the comparison list.

    Only the typesafe backend is a System One run.  Every other backend
    emulates the interface, and the label says which one did it, so a reader
    never has to infer the mechanism from a footnote.
    """

    if backend == "typesafe":
        return SYSTEM_ONE_LABEL
    return f"System One emulation ({backend_descriptor(backend, model)})"


def lane_narrative(*, backend: str, model: str | None, rungs: int) -> str:
    """What actually happened, stated per backend.

    Verified 2026-09-16 against system-one-adapter 0.1.3 (_client.py
    _prepare_evaluation and providers/openai.py _responses_request_kwargs):
    the adapter serializes the state once and sends every question in one
    request, with the provider's default reasoning setting.
    """

    if backend == "typesafe":
        return (
            f"A System One model answered {rungs} independent yes/no questions "
            "about one fixed evidence state, one question per ladder rung. It "
            "used no tools, no search, and no chain of thought, and it wrote "
            "no text: each answer is a probability returned in isolation. "
            + EVIDENCE_SENTENCE
        )
    if backend == "adapter":
        return (
            "This run emulates the System One interface rather than using it. "
            f"A general language model ({model}) received the same "
            f"fixed evidence state and all {rungs} threshold questions in one "
            "structured-output request and returned one probability per rung. "
            "The answers are therefore not isolated from one another, and the "
            "model may reason internally before it emits them, so its output "
            "tokens can include reasoning tokens. It used no tools and no "
            "search. " + EVIDENCE_SENTENCE
        )
    if backend == "response_file":
        return (
            "This run replays a System One response recorded earlier; no "
            f"model was called here. The {rungs} rung probabilities below are "
            "that recorded response, monotonized and interpolated by this "
            "runner. " + EVIDENCE_SENTENCE
        )
    return (
        "This run is a deterministic offline stand-in, not a model: the "
        f"{rungs} rung probabilities are computed from the evidence state by a "
        "fixed formula in the runner so the record can be exercised end to "
        "end. " + EVIDENCE_SENTENCE
    )


# --- cell assembly ----------------------------------------------------------


def build_cell(
    *,
    target: dict[str, Any],
    primary_cell: dict[str, Any],
    ladder: dict[str, Any],
    raw_probabilities: list[float],
    monotone: list[float],
    quantiles: dict[str, float],
    run_started_at: str,
    sealed_at: str,
    agent: dict[str, Any],
    latency_ms: int,
    usage: dict[str, Any],
) -> dict[str, Any]:
    thresholds = ladder["thresholds"]
    precision = ladder["precision"]
    rungs = ", ".join(
        f"P(X <= {threshold:.{precision}f}) = {probability:.4f}"
        for threshold, probability in zip(thresholds, monotone)
    )
    cell = {
        "slug": target.get("catalogSlug"),
        "country": target.get("country"),
        "type": "data",
        "title": primary_cell.get("title"),
        "question": primary_cell.get("question"),
        "unit": target_unit(target),
        "pointEstimate": quantiles["q50"],
        "ciLow": quantiles["q10"],
        "ciHigh": quantiles["q90"],
        "confidence": 0.8,
        "resolutionDate": target.get("resolutionDate"),
        "resolutionSource": target.get("resolutionSource"),
        "resolutionSourceUrl": target.get("resolutionSourceUrl"),
        "resolutionRule": target.get("resolutionRule"),
        "dataPointId": target.get("dataPointId"),
        "historicalContext": primary_cell.get("historicalContext") or [],
        "drivers": [],
        "sourceContext": source_context(primary_cell),
        "runStartedAt": run_started_at,
        "runAt": sealed_at,
        "promptMode": PROMPT_MODE,
        "thresholdLadder": {
            "thresholds": thresholds,
            "cumulativeProbabilities": monotone,
            "rawCumulativeProbabilities": raw_probabilities,
            "monotonization": MONOTONIZATION,
            "ladderBasis": ladder["ladderBasis"],
        },
        "reasoning": [
            {
                "kind": "heading",
                "text": lane_label(str(agent.get("backend")), agent.get("model")),
            },
            {
                "kind": "text",
                "text": lane_narrative(
                    backend=str(agent.get("backend")),
                    model=agent.get("model"),
                    rungs=len(thresholds),
                ),
            },
            {
                "kind": "tool",
                "tool": "system_one.noul_ladder",
                "call": (
                    "system_one.noul_ladder({"
                    f"backend: {agent.get('backend')!r}, "
                    f"provider: {agent.get('provider')!r}, "
                    f"model: {agent.get('model')!r}, "
                    f"questions: {len(thresholds)}"
                    "})"
                ),
                "result": (
                    f"{{latencyMs: {latency_ms}, "
                    f"inputTokens: {usage.get('input_tokens')}, "
                    f"outputTokens: {usage.get('output_tokens')}}}"
                ),
            },
            {
                "kind": "math",
                "text": (
                    f"Ladder: {rungs}. Interpolating the monotone ladder gives "
                    f"the 10th percentile at {quantiles['q10']}, the median at "
                    f"{quantiles['q50']}, and the 90th percentile at "
                    f"{quantiles['q90']}."
                ),
            },
            {
                "kind": "forecast",
                "point": quantiles["q50"],
                "ciLow": quantiles["q10"],
                "ciHigh": quantiles["q90"],
            },
        ],
    }
    for field in REGISTRATION_FIELDS:
        if target.get(field) not in (None, ""):
            cell[field] = target[field]
    return cell


def quantiles_from_ladder(
    thresholds: list[float], monotone: list[float], precision: int
) -> dict[str, float]:
    quantile_values: dict[str, float] = {}
    for key, probability in (("q10", 0.10), ("q50", 0.50), ("q90", 0.90)):
        value = ladder_interpolate(thresholds, monotone, probability)
        if value is None:
            raise SystemOneRunError(
                "ladder",
                f"monotone ladder does not span cumulative {probability}",
                {"reason": "off_ladder_mass", "quantile": probability},
            )
        quantile_values[key] = round(value, precision) + 0.0
    return quantile_values


def validate_run(
    *,
    cell: dict[str, Any],
    target: dict[str, Any],
    state: dict[str, Any],
    questions: dict[str, Any],
    primary_cell: dict[str, Any],
    raw_probabilities: list[float],
    monotone: list[float],
    distribution: dict[str, Any] | None,
) -> dict[str, Any]:
    errors: list[str] = []
    thresholds = list(cell["thresholdLadder"]["thresholds"])

    for cell_key, target_key in RESOLVER_CELL_FIELDS:
        expected = target.get(target_key)
        if expected not in (None, "") and cell.get(cell_key) != expected:
            errors.append(f"{cell_key} does not equal the trusted target {target_key}")
    if cell.get("unit") != target_unit(target):
        errors.append("unit does not equal the registered targetUnit")
    for field in REGISTRATION_FIELDS:
        expected = target.get(field)
        if expected not in (None, "") and cell.get(field) != expected:
            errors.append(f"{field} does not equal the trusted target")

    run_at = str(cell.get("runAt") or "")
    resolution_date = str(cell.get("resolutionDate") or "")
    if not run_at or not resolution_date or run_at[:10] >= resolution_date:
        errors.append("runAt is not strictly before resolutionDate")
    if run_at < str(cell.get("runStartedAt") or ""):
        errors.append("runAt precedes runStartedAt")

    if any(later <= earlier for earlier, later in zip(thresholds, thresholds[1:])):
        errors.append("thresholds are not strictly increasing")
    if any(later < earlier for earlier, later in zip(monotone, monotone[1:])):
        errors.append("cumulative probabilities are not non-decreasing")
    if len(monotone) != len(thresholds) or len(raw_probabilities) != len(thresholds):
        errors.append("ladder arrays have unequal length")
    if len(questions.get("questions") or {}) != len(thresholds):
        errors.append("question count does not match the threshold count")
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not 0.0 <= float(value) <= 1.0
        for value in raw_probabilities
    ):
        errors.append("raw probabilities are outside [0, 1]")
    if monotone and (monotone[0] > 0.10 or monotone[-1] < 0.90):
        errors.append("monotone ladder leaves the 80% interval off the rungs")

    if not (
        float(cell["ciLow"]) < float(cell["pointEstimate"]) < float(cell["ciHigh"])
    ):
        errors.append("ciLow < pointEstimate < ciHigh does not hold")
    if distribution is None or distribution.get("format") != "numeric_cdf_v1":
        errors.append("the threshold ladder did not materialize a distribution")

    errors.extend(redaction_violations(primary_cell, [state, questions]))

    return {
        "ok": not errors,
        "cells": [
            {
                "slug": cell.get("slug"),
                "ok": not errors,
                "errors": errors,
            }
        ],
        "rubric": "thesis_system_one_validation_v1",
    }


# --- sealing ----------------------------------------------------------------


def seal(
    *,
    out_dir: pathlib.Path,
    run_started_at: str,
    manifest: dict[str, Any],
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest["custodyInventoryVersion"] = CUSTODY_INVENTORY_VERSION
    manifest["runMode"] = RUN_MODE
    manifest["manifestHashSemantics"] = MANIFEST_HASH_MODE
    self_bytes = canonical_bytes(manifest_self_hash_payload(manifest))
    manifest["artifacts"] = [
        *refs,
        {
            "artifactType": "manifest",
            "path": repo_relative(out_dir / "manifest.json"),
            "sha256": sha256_bytes(self_bytes),
            "bytes": len(self_bytes),
            "createdAt": run_started_at,
            "hashMode": MANIFEST_HASH_MODE,
        },
    ]
    custody_root = {
        "schemaVersion": "thesis_custody_root_v1",
        "custodyInventoryVersion": CUSTODY_INVENTORY_VERSION,
        "runMode": RUN_MODE,
        "hashAlgorithm": "sha256",
        "canonicalJson": (
            "UTF-16 code-unit key order; ECMAScript JSON number/string encoding"
        ),
        "artifacts": [custody_artifact_entry(out_dir, ref) for ref in refs],
        "manifestWithoutCustodyRoot": {
            "path": "manifest.json",
            "excludedField": "custodyRootSha256",
            "canonicalJsonSha256": canonical_sha256(manifest),
        },
    }
    (out_dir / "custody_root.json").write_text(
        json.dumps(custody_root, indent=2) + "\n"
    )
    manifest["custodyRootSha256"] = canonical_sha256(custody_root)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def base_manifest(
    *,
    target: dict[str, Any],
    agent: dict[str, Any],
    run_started_at: str,
    sealed_at: str,
) -> dict[str, Any]:
    manifest = {
        "schemaVersion": MANIFEST_SCHEMA,
        "createdAt": run_started_at,
        "runStartedAt": run_started_at,
        "sealedAt": sealed_at,
        "series": target.get("series"),
        "period": target.get("period"),
        "targetContext": target,
        "promptMode": PROMPT_MODE,
        "agent": agent,
    }
    for field in REGISTRATION_FIELDS:
        if target.get(field) not in (None, ""):
            manifest[field] = target[field]
    return manifest


def phase_for_refs(refs: list[dict[str, Any]]) -> str | None:
    """The failure phase whose inventory is exactly what has been written."""

    written = [str(ref.get("artifactType")) for ref in refs]
    for phase, inventory in FAILURE_INVENTORIES.items():
        expected = [artifact_type for artifact_type, _name in inventory[:-1]]
        if written == expected:
            return phase
    return None


def remove_partial_run(out_dir: pathlib.Path, run_started_at: str) -> None:
    """Delete a run directory this invocation created and cannot seal."""

    if out_dir.name.startswith(run_stamp(run_started_at)) and out_dir.is_dir():
        shutil.rmtree(out_dir, ignore_errors=True)


def write_failure(
    *,
    out_dir: pathlib.Path,
    target: dict[str, Any],
    agent: dict[str, Any],
    run_started_at: str,
    refs: list[dict[str, Any]],
    phase: str,
    message: str,
    detail: Any,
) -> dict[str, Any]:
    sealed_at = max(utc_now(), run_started_at)
    error = {"phase": phase, "message": message, "detail": detail}
    refs = list(refs)
    refs.append(
        write_artifact(
            out_dir, "error", "error.json", json.dumps(error, indent=2), run_started_at
        )
    )
    manifest = base_manifest(
        target=target,
        agent=agent,
        run_started_at=run_started_at,
        sealed_at=sealed_at,
    )
    manifest.update(
        {
            "ok": False,
            "cellsPath": None,
            "validation": None,
            "error": error,
            "artifacts": refs,
        }
    )
    return seal(
        out_dir=out_dir,
        run_started_at=run_started_at,
        manifest=manifest,
        refs=refs,
    )


# --- primary cell discovery -------------------------------------------------


def load_primary_cell(
    *,
    explicit: pathlib.Path | None,
    slug: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the published primary cell and its custody provenance.

    The published catalog decides which run is this target's primary cell.
    An explicit --primary-cell is a local convenience (a scratch records
    root, a slug the catalog does not carry); when the catalog does bind the
    slug, the explicit path must be that same file, so an operator can never
    quietly feed the lane a different run's evidence.
    """

    catalog_path = catalog_primary_cell(slug)
    if explicit is None:
        if catalog_path is None:
            raise SystemOneInputError(
                "no published catalog cell binds a recorded run for "
                f"{slug}; pass --primary-cell to name the primary cell"
            )
        path = catalog_path
    else:
        path = explicit
        if catalog_path is not None and not _same_file(path, catalog_path):
            raise SystemOneInputError(
                f"--primary-cell is not the published primary cell for {slug}: "
                f"{repo_relative(path)} != {repo_relative(catalog_path)}"
            )
    if not path.is_file():
        raise SystemOneInputError(f"primary cell is not a file: {path}")
    payload = load_json(path, "primary cell")
    if isinstance(payload, list):
        cells = payload
    elif isinstance(payload, dict):
        cells = [payload]
    else:
        raise SystemOneInputError(f"primary cell must be an object or list: {path}")
    matching = [
        cell for cell in cells if isinstance(cell, dict) and cell.get("slug") == slug
    ]
    if not matching:
        raise SystemOneInputError(f"primary cell file has no cell for slug {slug}")
    cell = matching[0]
    manifest_path = path.parent / "manifest.json"
    provenance = {
        "cellPath": repo_relative(path),
        "cellSha256": sha256_bytes(path.read_bytes()),
        "manifestPath": (
            repo_relative(manifest_path) if manifest_path.is_file() else None
        ),
        "manifestSha256": (
            sha256_bytes(manifest_path.read_bytes())
            if manifest_path.is_file()
            else None
        ),
    }
    return cell, provenance


def _same_file(left: pathlib.Path, right: pathlib.Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:  # pragma: no cover - resolve only fails on broken links
        return False


# The catalog the site publishes.  Generated modules carry the cells as JSON
# array literals annotated ForecastCell[]; the hand-written modules build
# their cells from prediction series and carry no recorded run, so they name
# no primary cell and are skipped.
CATALOG_DIR = "site/src/data/forecast-examples"
CATALOG_ARRAY_RE = re.compile(r":\s*ForecastCell\[\]\s*=\s*\[")
RECORD_RUN_RE = re.compile(r"^records/thesis-analyst/\d{4}-\d{2}-\d{2}/[^/]+$")
_CATALOG_CACHE: dict[str, dict[str, str]] = {}


def _json_literal(text: str, start: int) -> str | None:
    """The bracket-balanced literal that begins at text[start]."""

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
        elif character in "]}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _without_trailing_commas(text: str) -> str:
    """Formatter trailing commas are TypeScript, not JSON; drop them."""

    out: list[str] = []
    index = 0
    length = len(text)
    in_string = False
    escaped = False
    while index < length:
        character = text[index]
        if in_string:
            out.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            out.append(character)
            index += 1
            continue
        if character == ",":
            ahead = index + 1
            while ahead < length and text[ahead] in " \t\r\n":
                ahead += 1
            if ahead < length and text[ahead] in "]}":
                index += 1
                continue
        out.append(character)
        index += 1
    return "".join(out)


def catalog_run_directories(root: pathlib.Path | None = None) -> dict[str, str]:
    """Map every published catalog slug to the run directory it cites.

    The site publishes one cell per slug, and a generated cell carries its
    own activity log: every artifact path is inside the recorded run that
    produced it.  That run, not the newest run in the records tree, is this
    target's primary cell; comparison-lane runs for the same slug live beside
    it and must never be mistaken for it.
    """

    base = root or ROOT
    key = str(base.resolve()) if base.exists() else str(base)
    cached = _CATALOG_CACHE.get(key)
    if cached is not None:
        return cached
    directories: dict[str, str] = {}
    catalog_dir = base / CATALOG_DIR
    if catalog_dir.is_dir():
        for module in sorted(catalog_dir.glob("*.ts")):
            try:
                text = module.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for match in CATALOG_ARRAY_RE.finditer(text):
                literal = _json_literal(text, match.end() - 1)
                if literal is None:
                    continue
                try:
                    cells = json.loads(_without_trailing_commas(literal))
                except json.JSONDecodeError:
                    continue
                if not isinstance(cells, list):
                    continue
                for cell in cells:
                    if not isinstance(cell, dict):
                        continue
                    slug = cell.get("slug")
                    run_dir = _cell_run_directory(cell)
                    if not isinstance(slug, str) or run_dir is None:
                        continue
                    if directories.get(slug) not in (None, run_dir):
                        # Two published cells for one slug cannot both be the
                        # primary cell; refuse rather than pick one.
                        directories[slug] = ""
                        continue
                    directories[slug] = run_dir
    _CATALOG_CACHE[key] = directories
    return directories


def _cell_run_directory(cell: dict[str, Any]) -> str | None:
    """The one recorded run directory a published cell's activity log cites."""

    activity = (cell.get("predictionRun") or {}).get("activityLog")
    if not isinstance(activity, list) or not activity:
        return None
    directories = set()
    for artifact in activity:
        if not isinstance(artifact, dict):
            return None
        path = artifact.get("path")
        if not isinstance(path, str) or not path.startswith("records/"):
            return None
        directory = path.rsplit("/", 1)[0]
        if not RECORD_RUN_RE.fullmatch(directory):
            return None
        directories.add(directory)
    if len(directories) != 1:
        return None
    return directories.pop()


def catalog_primary_cell(
    slug: str, root: pathlib.Path | None = None
) -> pathlib.Path | None:
    """The published primary cell file for this slug, or None."""

    base = root or ROOT
    run_dir = catalog_run_directories(base).get(slug)
    if not run_dir:
        return None
    return base / run_dir / "cells.with_activity.json"


# --- runner -----------------------------------------------------------------


def preflight_backend(backend: str, provider: str | None) -> None:
    """Refuse a backend we cannot reach before any run directory exists.

    The SDKs strip whitespace out of a key and then raise from their own
    constructors, so a blank key counts as missing here rather than as a
    backend failure sealed halfway through a run.
    """

    if backend == "typesafe" and not os.environ.get(TYPESAFE_KEY_ENV, "").strip():
        raise SystemOneInputError(
            f"the typesafe backend requires {TYPESAFE_KEY_ENV} in the environment"
        )
    if backend == "adapter":
        env_name = PROVIDER_KEY_ENV.get(str(provider))
        if env_name is None:
            raise SystemOneInputError(
                f"unsupported adapter provider: {provider!r}; "
                f"known providers are {sorted(PROVIDER_KEY_ENV)}"
            )
        if not os.environ.get(env_name, "").strip():
            raise SystemOneInputError(
                f"the adapter backend with provider {provider} requires "
                f"{env_name} in the environment"
            )


def agent_block(
    *,
    backend: str,
    provider: str | None,
    model: str | None,
    response: dict[str, Any] | None,
) -> dict[str, Any]:
    """The manifest agent block.

    ``model`` is what the run asked for; the block records what answered.
    A typesafe run that never received a response has no answering model, and
    it records null rather than the backend name, so a failed run can never
    be tallied as a model that spoke.
    """

    if backend == "typesafe":
        resolved = str(response.get("model")) if response else model
    elif backend == "adapter":
        resolved = f"{provider}/{model}"
    else:
        resolved = backend
    return {
        "agent": AGENT_NAME,
        "model": resolved,
        "agentVersion": AGENT_VERSION,
        "promptHash": canonical_sha256(LADDER_POLICY),
        "toolPolicyHash": canonical_sha256(backend_policy(backend)),
        "backend": backend,
        "provider": provider,
    }


def run_forecast(
    *,
    target: dict[str, Any],
    backend: str,
    records_root: pathlib.Path,
    primary_cell_path: pathlib.Path | None = None,
    ledger_path: pathlib.Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    response_file: pathlib.Path | None = None,
    run_at: str | None = None,
) -> tuple[dict[str, Any], pathlib.Path]:
    """Run one target and return (manifest, manifest path)."""

    if backend not in BACKENDS:
        raise SystemOneInputError(f"unsupported backend: {backend!r}")
    slug = target.get("catalogSlug")
    if not isinstance(slug, str) or not slug:
        raise SystemOneInputError("target has no catalogSlug")
    if backend == "response_file":
        if response_file is None:
            raise SystemOneInputError(
                "the response_file backend requires --response-file"
            )
        # Read and shape-check the replay before the run directory exists, so
        # an unreadable file is a refused input and never a half-written run.
        call_response_file(response_file)
    preflight_backend(backend, provider)

    run_started_at = run_at or utc_now()
    primary_cell, primary_provenance = load_primary_cell(
        explicit=primary_cell_path, slug=slug
    )
    out_dir = (
        records_root
        / "thesis-analyst"
        / run_started_at[:10]
        / f"{run_stamp(run_started_at)}-system-one-{slugify(slug)}"
    )
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemOneInputError(f"run directory already exists: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    agent = agent_block(backend=backend, provider=provider, model=model, response=None)
    refs: list[dict[str, Any]] = []

    ledger = ledger_selection(target, read_ledger(ledger_path), run_started_at)
    ledger_observations = ledger["rows"]
    state = build_state(
        target=target,
        primary_cell=primary_cell,
        primary_provenance=primary_provenance,
        ledger=ledger,
        run_started_at=run_started_at,
    )
    refs.append(
        write_artifact(
            out_dir,
            "system_one_state",
            "state.json",
            json.dumps(state, indent=2) + "\n",
            run_started_at,
        )
    )

    try:
        return _run_sealed(
            out_dir=out_dir,
            refs=refs,
            target=target,
            primary_cell=primary_cell,
            state=state,
            ledger_observations=ledger_observations,
            backend=backend,
            provider=provider,
            model=model,
            response_file=response_file,
            run_started_at=run_started_at,
            agent=agent,
        )
    except SystemOneRunError as exc:
        manifest = write_failure(
            out_dir=out_dir,
            target=target,
            agent=agent,
            run_started_at=run_started_at,
            refs=refs,
            phase=exc.phase,
            message=exc.message,
            detail=exc.detail,
        )
        return manifest, out_dir / "manifest.json"
    except Exception as exc:  # noqa: BLE001 - class name only, never the text
        # Anything the phases did not anticipate still leaves a sealed,
        # custody-verifiable record when the artifacts written so far are
        # exactly one phase inventory.  When they are not, there is no honest
        # inventory to seal, so the partial directory is removed and the run
        # reports a refused input: nothing was recorded.
        phase = phase_for_refs(refs)
        if phase is None:
            remove_partial_run(out_dir, run_started_at)
            raise SystemOneInputError(
                f"{type(exc).__name__} before the run could be sealed"
            ) from exc
        manifest = write_failure(
            out_dir=out_dir,
            target=target,
            agent=agent,
            run_started_at=run_started_at,
            refs=refs,
            phase=phase,
            message=f"{type(exc).__name__} in the {phase} phase",
            detail={"exception": type(exc).__name__},
        )
        return manifest, out_dir / "manifest.json"


def _run_sealed(
    *,
    out_dir: pathlib.Path,
    refs: list[dict[str, Any]],
    target: dict[str, Any],
    primary_cell: dict[str, Any],
    state: dict[str, Any],
    ledger_observations: list[dict[str, Any]],
    backend: str,
    provider: str | None,
    model: str | None,
    response_file: pathlib.Path | None,
    run_started_at: str,
    agent: dict[str, Any],
) -> tuple[dict[str, Any], pathlib.Path]:
    ladder = build_ladder(
        ledger_observations=ledger_observations,
        history=history_rows(primary_cell),
    )
    payloads = question_payloads(
        contract=state["target"],
        thresholds=ladder["thresholds"],
        precision=ladder["precision"],
    )
    questions = build_questions(
        ladder=ladder,
        payloads=payloads,
        ledger_observations=ledger_observations,
    )
    violations = redaction_violations(primary_cell, [state, questions])
    if violations:
        raise SystemOneRunError(
            "state",
            "redacted primary-cell content reached the model state",
            {"reason": "redaction", "violations": violations},
        )
    refs.append(
        write_artifact(
            out_dir,
            "system_one_questions",
            "questions.json",
            json.dumps(questions, indent=2) + "\n",
            run_started_at,
        )
    )
    request = {
        "schemaVersion": REQUEST_SCHEMA,
        "backend": backend,
        "provider": provider,
        "model": model,
        "state": state,
        "questions": payloads,
    }
    refs.append(
        write_artifact(
            out_dir,
            "system_one_request",
            "request.json",
            json.dumps(request, indent=2) + "\n",
            run_started_at,
        )
    )

    started_at = utc_now()
    started = time.monotonic()
    response: dict[str, Any] | None = None
    failure: SystemOneRunError | None = None
    try:
        # Anything the call raises is a backend-phase failure, sealed with
        # the command below, so an unanticipated exception still leaves a
        # custody-verifiable record instead of a traceback.
        with backend_phase("backend call"):
            if backend == "mock":
                response = call_mock(payloads=payloads, ladder=ladder)
            elif backend == "response_file":
                assert response_file is not None
                response = call_response_file(response_file)
            elif backend == "typesafe":
                response = call_typesafe(state=state, payloads=payloads, model=model)
            else:
                response = call_adapter(
                    state=state,
                    payloads=payloads,
                    provider=str(provider),
                    model=str(model),
                )
    except SystemOneRunError as exc:
        failure = exc
    latency_ms = int(round((time.monotonic() - started) * 1000))
    finished_at = utc_now()

    if response is not None:
        refs.append(
            write_artifact(
                out_dir,
                "system_one_response",
                "response.json",
                json.dumps(response, indent=2) + "\n",
                run_started_at,
            )
        )
    command = {
        "backend": backend,
        "provider": provider,
        "model": model,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "latencyMs": latency_ms,
        "returnCode": 0 if failure is None else 1,
        "sdkVersions": {
            "typesafe-sdk": package_version("typesafe-sdk"),
            "system-one-adapter": package_version("system-one-adapter"),
        },
        "responseFile": (
            {
                "name": response_file.name,
                "sha256": sha256_bytes(response_file.read_bytes()),
            }
            if backend == "response_file" and response_file is not None
            else None
        ),
    }
    refs.append(
        write_artifact(
            out_dir,
            "command",
            "command.json",
            json.dumps(command, indent=2) + "\n",
            run_started_at,
        )
    )
    if failure is not None:
        raise failure
    assert response is not None

    # Mutate in place: run_forecast holds this dict for the failure writer, so
    # a later ladder or validate failure still records the model that answered.
    agent.update(
        agent_block(backend=backend, provider=provider, model=model, response=response)
    )
    names = list(payloads)
    raw_probabilities = [
        round_probability(value) for value in noul_probabilities(response, names)
    ]
    monotone = [
        round_probability(value)
        for value in clamp_unit(pav_monotone(raw_probabilities))
    ]
    if monotone[0] > 0.10 or monotone[-1] < 0.90:
        raise SystemOneRunError(
            "ladder",
            "monotone ladder leaves the 80% interval off the rungs",
            {
                "reason": "off_ladder_mass",
                "thresholds": ladder["thresholds"],
                "rawCumulativeProbabilities": raw_probabilities,
                "cumulativeProbabilities": monotone,
            },
        )
    quantile_values = quantiles_from_ladder(
        ladder["thresholds"], monotone, ladder["precision"]
    )

    sealed_at = max(utc_now(), run_started_at)
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    cell = build_cell(
        target=target,
        primary_cell=primary_cell,
        ladder=ladder,
        raw_probabilities=raw_probabilities,
        monotone=monotone,
        quantiles=quantile_values,
        run_started_at=run_started_at,
        sealed_at=sealed_at,
        agent=agent,
        latency_ms=latency_ms,
        usage=usage,
    )
    distribution = ladder_distribution(cell)
    normalized = copy.deepcopy(cell)
    if distribution is not None:
        normalized["predictionDistribution"] = distribution
    refs.append(
        write_artifact(
            out_dir,
            "normalized_cell",
            "normalized_cells.json",
            json.dumps([normalized], indent=2) + "\n",
            run_started_at,
        )
    )
    refs.append(
        write_artifact(
            out_dir,
            "run_distribution",
            "distribution.json",
            json.dumps(distribution, indent=2) + "\n",
            run_started_at,
        )
    )

    try:
        validation = validate_run(
            cell=normalized,
            target=target,
            state=state,
            questions=questions,
            primary_cell=primary_cell,
            raw_probabilities=raw_probabilities,
            monotone=monotone,
            distribution=distribution,
        )
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise SystemOneRunError(
            "validate",
            f"{type(exc).__name__} while validating the sealed cell",
            {"exception": type(exc).__name__},
        ) from exc
    refs.append(
        write_artifact(
            out_dir,
            "validation_report",
            "validation.json",
            json.dumps(validation, indent=2) + "\n",
            run_started_at,
        )
    )

    cell_with_activity = {
        **normalized,
        "model": agent["model"],
        "activityLog": list(refs),
    }
    cells_path = out_dir / "cells.with_activity.json"
    cells_path.write_text(json.dumps([cell_with_activity], indent=2) + "\n")
    refs.append(
        {
            "artifactType": "cells_with_activity",
            "path": repo_relative(cells_path),
            "sha256": sha256_bytes(cells_path.read_bytes()),
            "bytes": cells_path.stat().st_size,
            "createdAt": run_started_at,
        }
    )

    manifest = base_manifest(
        target=target,
        agent=agent,
        run_started_at=run_started_at,
        sealed_at=sealed_at,
    )
    manifest.update(
        {
            "ok": bool(validation["ok"]),
            "cellsPath": repo_relative(cells_path),
            "validation": validation,
            "error": None,
            "artifacts": refs,
        }
    )
    manifest = seal(
        out_dir=out_dir,
        run_started_at=run_started_at,
        manifest=manifest,
        refs=refs,
    )
    return manifest, out_dir / "manifest.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-json", required=True, type=pathlib.Path)
    parser.add_argument("--primary-cell", type=pathlib.Path)
    parser.add_argument("--ledger-jsonl", type=pathlib.Path)
    parser.add_argument("--backend", choices=list(BACKENDS), required=True)
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--response-file", type=pathlib.Path)
    parser.add_argument(
        "--records-root",
        type=pathlib.Path,
        default=DEFAULT_RECORDS_ROOT,
        help="records tree to write the run into (default: repository records/)",
    )
    parser.add_argument("--run-at", help="fixed run start; tests only")
    parser.add_argument("--out-manifest", type=pathlib.Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    provider = args.provider
    model = args.model
    if args.backend == "adapter":
        provider = provider or DEFAULT_ADAPTER_PROVIDER
        model = model or DEFAULT_ADAPTER_MODEL
    try:
        target = load_json(args.target_json, "target")
        if not isinstance(target, dict):
            raise SystemOneInputError("target JSON must be one target object")
        manifest, manifest_path = run_forecast(
            target=target,
            backend=args.backend,
            records_root=args.records_root,
            primary_cell_path=args.primary_cell,
            ledger_path=args.ledger_jsonl,
            provider=provider,
            model=model,
            response_file=args.response_file,
            run_at=args.run_at,
        )
    except SystemOneInputError as exc:
        print(f"system_one: {exc}", file=sys.stderr)
        return 2
    if args.out_manifest:
        args.out_manifest.parent.mkdir(parents=True, exist_ok=True)
        args.out_manifest.write_text(repo_relative(manifest_path) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0 if manifest.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
