#!/usr/bin/env python3
"""Compute the next docket targets for every registry series.

For recurring registry entries, the docket cursor is the latest PUBLISHED
period (recovered from the live catalog by inverting the slug template):
failed or unpublished attempts keep the cursor in place. Once a target has an
immutable registration, ordinary rolls leave it to the explicit in-grace retry
lane rather than re-registering it (F10). A recurring entry with no published
cell may declare one reviewed, explicitly dated seed period.
Reviewed annual snapshot entries are separate one-shot seeds with an explicit
fiscal year and capture window. The records/ directories still provide
attempt visibility, and the live catalog's slug set is the final duplicate
guard.

Usage:
    python3 scripts/roll_docket.py [--cadence weekly|monthly|quarterly|annual]
        [--max-targets N] [--out targets.json] [--dry-run] [--include-bounded]

Emits a run_thesis_batch.py-compatible targets file. Reviewed recurring seeds
sort first by exact release date so the capped scheduler cannot defer them
past their finite forecasting window. Weekly targets follow (they resolve
fastest), then reviewed one-shot snapshot seeds and earliest next-period
first. Exits 0 with an empty targets list when there is nothing to roll —
idempotent by construction, so the schedule can fire as often as it likes.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import pathlib
import re
import sys
import urllib.parse

from ingest_challenge_submissions import (
    ChallengeSubmissionError,
    expired_unforecast_registrations,
    load_registered_targets,
)
from register_targets import (
    build_contract,
    derive_data_point_id,
    execution_plan_refusal,
)
from thesis_log_client import load_thesis_log

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "scripts" / "docket_series.json"
RECORDS = ROOT / "records" / "thesis-analyst"
TARGET_REGISTRATIONS = ROOT / "records" / "targets"
LOG_URL = "https://app.thesisinstitute.org/log.json"
ROLL_HORIZON_DAYS = 75
SNAPSHOT_SEED_HORIZON_DAYS = ROLL_HORIZON_DAYS

MONTH_NAMES = [m.lower() for m in calendar.month_name]
MONTH_ABBREVIATIONS = [m.lower() for m in calendar.month_abbr]
OFFICIAL_CALENDAR_ADAPTERS = frozenset(
    {
        "abs-data-api",
        "abs-release-page",
        "bls-qcew",
        "eurostat-api",
        "ons-timeseries",
        "statcan-wds",
    }
)
CALENDAR_GATED_SOURCE_ADAPTERS = OFFICIAL_CALENDAR_ADAPTERS | {
    "alfred-fred",
    "bea-ita-itable",
    "bea-release",
}


def slugify_series(series: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", series.lower()).strip("-")


def latest_recorded_period(series: str, cadence: str) -> str | None:
    """Latest period attempted for a series, from run directory names.

    Run dirs look like 2026-07-07t13-48-08z-{series-slug}-{period-slug};
    period slugs are 2026-04, 2026-q2, or week-2026-07-04 (period
    underscores become hyphens in the dir name).
    """
    marker = f"-{slugify_series(series)}-"
    periods: list[str] = []
    if not RECORDS.exists():
        return None
    for day_dir in RECORDS.iterdir():
        if not day_dir.is_dir():
            continue
        for run_dir in day_dir.iterdir():
            name = run_dir.name
            idx = name.find(marker)
            if idx < 0:
                continue
            period = name[idx + len(marker) :].replace("week-", "week_")
            # A shorter series name can match inside a longer one's dir
            # (eurostat.unemployment_rate vs ...unemployment_rate.belgium);
            # only accept strings that look like periods.
            if period_key(period, cadence) is not None:
                periods.append(period)
    if not periods:
        return None
    return max(periods, key=lambda period: period_key(period, cadence) or ())


def period_key(period: str, cadence: str) -> tuple[int, ...] | None:
    """Return a semantic sort key, rejecting impossible captured periods."""
    try:
        if cadence == "weekly":
            match = re.fullmatch(r"week_(\d{4}-\d{2}-\d{2})", period)
            if not match:
                return None
            day = dt.date.fromisoformat(match.group(1))
            return (day.toordinal(),)
        if cadence == "monthly":
            match = re.fullmatch(r"(\d{4})-(\d{2})", period)
            if not match:
                return None
            year, month = int(match.group(1)), int(match.group(2))
            if month < 1 or month > 12:
                return None
            return (year, month)
        if cadence == "quarterly":
            match = re.fullmatch(r"(\d{4})-[Qq]([1-4])", period)
            if not match:
                return None
            return (int(match.group(1)), int(match.group(2)))
        if cadence == "annual":
            match = re.fullmatch(r"(\d{4})", period)
            if not match:
                return None
            return (int(match.group(1)),)
    except ValueError:
        return None
    return None


def warn_malformed_period(operation: str, period: str, cadence: str) -> None:
    print(
        f"  warning: skip malformed {cadence} period {period!r} during {operation}",
        file=sys.stderr,
    )


def step_period(period: str, cadence: str) -> str | None:
    key = period_key(period, cadence)
    if key is None:
        warn_malformed_period("step", period, cadence)
        return None
    if cadence == "weekly":
        day = dt.date.fromordinal(key[0])
        return f"week_{day + dt.timedelta(days=7)}"
    if cadence == "monthly":
        year, month = key
        month += 1
        if month == 13:
            year, month = year + 1, 1
        return f"{year}-{month:02d}"
    if cadence == "quarterly":
        year, quarter = key[0], key[1] + 1
        if quarter == 5:
            year, quarter = year + 1, 1
        return f"{year}-Q{quarter}"
    if cadence == "annual":
        return str(key[0] + 1)
    warn_malformed_period("step", period, cadence)
    return None


def format_slug(template: str, period: str, cadence: str) -> str:
    if period_key(period, cadence) is None:
        raise ValueError(f"malformed {cadence} period: {period}")
    if cadence == "weekly":
        return template.format(period=period.removeprefix("week_"))
    if cadence == "monthly":
        year, month = period[:4], int(period[5:7])
        return template.format(
            month=MONTH_NAMES[month],
            month_abbr=MONTH_ABBREVIATIONS[month],
            year=year,
        )
    if cadence == "annual":
        return template.format(year=period, period=period.lower())
    m = re.fullmatch(r"(\d{4})-Q(\d)", period)
    return template.format(quarter=m.group(2), year=m.group(1))


def not_too_far_ahead(period: str, cadence: str, today: dt.date) -> bool:
    """Don't forecast periods that haven't meaningfully begun."""
    key = period_key(period, cadence)
    if key is None:
        warn_malformed_period("horizon check", period, cadence)
        return False
    if cadence == "weekly":
        day = dt.date.fromordinal(key[0])
        return day <= today + dt.timedelta(days=7)
    if cadence == "monthly":
        year, month = key
        return (year, month) <= (today.year, today.month)
    if cadence == "quarterly":
        quarter = (today.month - 1) // 3 + 1
        return key <= (today.year, quarter)
    if cadence == "annual":
        return key <= (today.year,)
    warn_malformed_period("horizon check", period, cadence)
    return False


def live_catalog() -> tuple[set[str], dict[str, dict], set[str]]:
    """Published slugs and their latest recorded target contract."""
    log = load_thesis_log(LOG_URL)
    links = {
        link["forecastSlug"]: link
        for link in log["resolutionLinks"]
        if link.get("forecastSlug")
    }
    forecasts: dict[str, dict] = {}
    for entry in log.get("entries", []):
        if entry.get("kind") != "prediction_recorded":
            continue
        slug = entry.get("forecastSlug")
        if not slug or slug not in links:
            continue
        current = forecasts.get(slug)
        if current is None or str(entry.get("recordedAt") or "") > str(
            current.get("recordedAt") or ""
        ):
            forecasts[slug] = entry
    for slug, link in links.items():
        if slug in forecasts and link.get("targetFactRef"):
            forecasts[slug]["dataPointId"] = link["targetFactRef"]
    observed_slugs = {
        entry["forecastSlug"]
        for entry in log.get("entries", [])
        if entry.get("kind") == "prediction_resolved" and entry.get("forecastSlug")
    }
    return set(links), forecasts, observed_slugs


def template_regex(template: str, cadence: str) -> re.Pattern[str]:
    """Invert a registry slug template into a period-extracting regex."""
    token_specs = {
        "weekly": {"period": ("date", r"\d{4}-\d{2}-\d{2}")},
        "monthly": {
            "month": ("month", r"[a-z]+"),
            "month_abbr": ("month_abbr", r"[a-z]{3}"),
            "year": ("year", r"\d{4}"),
        },
        "quarterly": {
            "quarter": ("quarter", r"\d+"),
            "year": ("year", r"\d{4}"),
        },
        "annual": {
            "period": ("year", r"\d{4}"),
            "year": ("year", r"\d{4}"),
        },
    }.get(cadence, {})
    token_pattern = re.compile(r"\{([a-z_]+)\}")
    parts: list[str] = []
    seen_groups: set[str] = set()
    cursor = 0
    for match in token_pattern.finditer(template):
        parts.append(re.escape(template[cursor : match.start()]))
        token = match.group(1)
        spec = token_specs.get(token)
        if spec is None:
            parts.append(re.escape(match.group(0)))
        else:
            group, value_pattern = spec
            if group in seen_groups:
                parts.append(f"(?P={group})")
            else:
                parts.append(f"(?P<{group}>{value_pattern})")
                seen_groups.add(group)
        cursor = match.end()
    parts.append(re.escape(template[cursor:]))
    return re.compile(f"^{''.join(parts)}$")


def captured_period(match: re.Match[str], cadence: str) -> str | None:
    """Build and semantically validate a period captured from a slug."""
    try:
        if cadence == "weekly":
            period = f"week_{match.group('date')}"
        elif cadence == "monthly":
            groups = match.groupdict()
            month_name = groups.get("month")
            month_abbr = groups.get("month_abbr")
            if month_name is not None:
                month_values = MONTH_NAMES
                month_value = month_name
            else:
                month_values = MONTH_ABBREVIATIONS
                month_value = month_abbr
            if month_value not in month_values:
                return None
            month = month_values.index(month_value)
            period = f"{match.group('year')}-{month:02d}"
        elif cadence == "quarterly":
            period = f"{match.group('year')}-Q{match.group('quarter')}"
        elif cadence == "annual":
            period = match.group("year")
        else:
            return None
    except (IndexError, ValueError):
        return None
    return period if period_key(period, cadence) is not None else None


def published_periods(entry: dict, catalog_slugs: set[str]) -> list[tuple[str, str]]:
    pattern = template_regex(entry["slug"], entry["cadence"])
    periods: list[tuple[str, str]] = []
    for slug in catalog_slugs:
        match = pattern.match(slug)
        if not match:
            continue
        period = captured_period(match, entry["cadence"])
        if period is None:
            print(
                f"  warning: skip slug with invalid captured period: {slug}",
                file=sys.stderr,
            )
            continue
        periods.append((period, slug))
    return periods


def latest_published_period(
    entry: dict, catalog_slugs: set[str]
) -> tuple[str, str] | None:
    """Latest period with a PUBLISHED cell in the live catalog.

    The docket cursor advances only past published work: a run that
    failed validation, tests, or deployment keeps the cursor in place.
    Registered failures are retried against their existing snapshot by
    retry_batch_targets.py rather than silently vanishing or being
    re-registered (review finding F10).
    """
    periods = published_periods(entry, catalog_slugs)
    if not periods:
        return None
    return max(
        periods,
        key=lambda item: period_key(item[0], entry["cadence"]) or (),
    )


def next_roll_period(
    entry: dict,
    catalog_slugs: set[str],
    observed_slugs: set[str],
    today: dt.date,
) -> tuple[str, str] | None:
    """Choose the normal successor or recover the earliest eligible gap.

    A syntactically valid far-future published slug must not freeze a series.
    If its successor is beyond the horizon, scan forward from the last
    ledger-observed period and select the earliest unpublished, eligible gap
    before the maximum published period.
    """
    periods = published_periods(entry, catalog_slugs)
    if not periods:
        return None
    cadence = entry["cadence"]
    latest, latest_slug = max(
        periods, key=lambda item: period_key(item[0], cadence) or ()
    )
    successor = step_period(latest, cadence)
    if successor is None:
        return None
    if not_too_far_ahead(successor, cadence, today):
        return successor, latest_slug

    observed_periods = published_periods(entry, catalog_slugs & observed_slugs)
    if not observed_periods:
        return None
    last_observed, _ = max(
        observed_periods, key=lambda item: period_key(item[0], cadence) or ()
    )
    max_key = period_key(latest, cadence)
    cursor = last_observed
    while max_key is not None:
        candidate = step_period(cursor, cadence)
        if candidate is None:
            return None
        candidate_key = period_key(candidate, cadence)
        if candidate_key is None or candidate_key >= max_key:
            return None
        if not not_too_far_ahead(candidate, cadence, today):
            return None
        slug = format_slug(entry["slug"], candidate, cadence)
        if slug not in catalog_slugs:
            earlier = [
                item
                for item in periods
                if (period_key(item[0], cadence) or ()) < candidate_key
            ]
            previous_slug = max(
                earlier, key=lambda item: period_key(item[0], cadence) or ()
            )[1]
            print(
                f"  recover {entry['series']} gap {candidate}: "
                f"max published period {latest} is beyond the horizon"
            )
            return candidate, previous_slug
        cursor = candidate
    return None


def snapshot_seed_target(
    entry: dict,
    catalog_slugs: set[str],
    today: dt.date,
    *,
    horizon_days: int = SNAPSHOT_SEED_HORIZON_DAYS,
) -> dict | None:
    """Admit one reviewed annual registered-query snapshot seed.

    Annual snapshots deliberately do not use the normal published-period
    cursor: their capture date cannot be inferred from cadence. The registry
    must instead pin both the fiscal-year period and the capture window. Once
    that concrete slug is published, this helper never steps it to another
    fiscal year; a future seed requires another reviewed registry change.
    """

    if entry.get("cadence") != "annual":
        return None
    extras = entry.get("extras")
    binding = extras.get("sourceBinding") if isinstance(extras, dict) else None
    if not isinstance(binding, dict) or (
        binding.get("releasePolicy") != "registered_query_snapshot"
    ):
        print(
            f"  warning: skip {entry.get('series', '?')}: annual seed is not "
            "a registered_query_snapshot",
            file=sys.stderr,
        )
        return None
    period = entry.get("period")
    if not isinstance(period, str) or not re.fullmatch(r"FY\d{4}", period):
        print(
            f"  warning: skip {entry.get('series', '?')}: malformed annual "
            f"snapshot period {period!r}",
            file=sys.stderr,
        )
        return None
    window = extras.get("expectedReleaseWindow")
    if not isinstance(window, dict) or set(window) != {"start", "end"}:
        print(
            f"  warning: skip {entry.get('series', '?')}: annual snapshot "
            "requires an exact expectedReleaseWindow",
            file=sys.stderr,
        )
        return None
    try:
        if not all(isinstance(window[key], str) for key in ("start", "end")):
            raise ValueError
        start = dt.date.fromisoformat(window["start"])
        end = dt.date.fromisoformat(window["end"])
    except ValueError:
        print(
            f"  warning: skip {entry.get('series', '?')}: malformed annual "
            "snapshot window",
            file=sys.stderr,
        )
        return None
    if start > end:
        print(
            f"  warning: skip {entry.get('series', '?')}: annual snapshot "
            "window ends before it starts",
            file=sys.stderr,
        )
        return None
    if not (today < start <= today + dt.timedelta(days=horizon_days)):
        return None
    try:
        slug = entry["slug"].format(period=period.lower())
    except (IndexError, KeyError, TypeError, ValueError):
        print(
            f"  warning: skip {entry.get('series', '?')}: malformed annual "
            "snapshot slug template",
            file=sys.stderr,
        )
        return None
    if slug in catalog_slugs:
        return None
    return {
        "series": entry["series"],
        "period": period,
        "catalogSlug": slug,
        **extras,
    }


def bounded_annual_first_print_seed_target(
    entry: dict,
    catalog_slugs: set[str],
    today: dt.date,
) -> dict | None:
    """Admit one reviewed annual first-print seed with a bounded window.

    IRS Publication 1304 does not publish a future exact-day calendar slot.
    This selector therefore accepts only a registry-authored YYYY period,
    resolve-by bound, exact expected window, and first-print binding. It never
    infers any date from annual cadence and never emits after the window opens.
    """

    if entry.get("cadence") != "annual":
        return None
    period = entry.get("period")
    if not isinstance(period, str) or not re.fullmatch(r"\d{4}", period):
        print(
            f"  warning: skip {entry.get('series', '?')}: bounded annual "
            f"seed requires a YYYY period, got {period!r}",
            file=sys.stderr,
        )
        return None
    if entry.get("seedPeriod") != period:
        print(
            f"  warning: skip {entry.get('series', '?')}: bounded annual "
            "seedPeriod must equal period",
            file=sys.stderr,
        )
        return None
    extras = entry.get("extras")
    binding = extras.get("sourceBinding") if isinstance(extras, dict) else None
    if (
        not isinstance(binding, dict)
        or binding.get("releasePolicy") != "first_print"
        or extras.get("resolutionDateBasis") != "resolve-by-bound"
    ):
        print(
            f"  warning: skip {entry.get('series', '?')}: bounded annual "
            "seed requires a first_print binding and resolve-by-bound basis",
            file=sys.stderr,
        )
        return None
    window = extras.get("expectedReleaseWindow")
    if not isinstance(window, dict) or set(window) != {"start", "end"}:
        print(
            f"  warning: skip {entry.get('series', '?')}: bounded annual "
            "seed requires an exact expectedReleaseWindow",
            file=sys.stderr,
        )
        return None
    try:
        if not all(isinstance(window[key], str) for key in ("start", "end")):
            raise ValueError
        start = dt.date.fromisoformat(window["start"])
        end = dt.date.fromisoformat(window["end"])
        resolution_date = dt.date.fromisoformat(str(extras.get("resolutionDate")))
    except ValueError:
        print(
            f"  warning: skip {entry.get('series', '?')}: malformed bounded "
            "annual dates",
            file=sys.stderr,
        )
        return None
    if start > end or resolution_date != end:
        print(
            f"  warning: skip {entry.get('series', '?')}: bounded annual "
            "resolutionDate must equal the window end",
            file=sys.stderr,
        )
        return None
    if today >= start:
        return None
    try:
        slug = entry["slug"].format(period=period.lower())
    except (IndexError, KeyError, TypeError, ValueError):
        print(
            f"  warning: skip {entry.get('series', '?')}: malformed bounded "
            "annual slug template",
            file=sys.stderr,
        )
        return None
    if slug in catalog_slugs:
        return None
    return {
        "series": entry["series"],
        "period": period,
        "seedPeriod": period,
        "catalogSlug": slug,
        **extras,
    }


def conditional_pair_seed_targets(
    entry: dict,
    catalog_slugs: set[str],
    today: dt.date,
) -> list[dict]:
    """Admit the reviewed one-shot conditional-pair arms still unpublished.

    A conditional pair forecasts one official print under two mutually
    exclusive legal-state conditions (a legislated provision holding vs
    current law). Its forecasting window is bounded by the CONDITION
    deadline, not by the release date: the arms must be preregistered and
    published while the legislative outcome is open, even though the
    official print that resolves them may be years away. The registry must
    pin everything — the exact period, both arm slugs, distinct
    dataPointIds, the byte-exact conditional texts, and an explicit
    expectedReleaseWindow — so nothing here is inferred from cadence. An
    arm whose catalog slug is already published is never re-emitted; a
    registered failed arm keeps its slot and uses the explicit in-grace retry
    lane instead of receiving a new registration (F10).
    """

    pair = entry.get("conditionalPair")
    if not isinstance(pair, dict):
        return []
    series = entry.get("series", "?")

    def skip(reason: str) -> list[dict]:
        print(
            f"  warning: skip {series}: conditional pair {reason}",
            file=sys.stderr,
        )
        return []

    cadence = entry.get("cadence")
    if cadence not in {"annual", "monthly"}:
        return skip("requires annual or monthly cadence")
    period = entry.get("period")
    period_pattern = r"\d{4}" if cadence == "annual" else r"\d{4}-(0[1-9]|1[0-2])"
    period_shape = "YYYY" if cadence == "annual" else "YYYY-MM"
    if not isinstance(period, str) or not re.fullmatch(period_pattern, period):
        return skip(f"requires an explicit {period_shape} period, got {period!r}")
    try:
        deadline = dt.date.fromisoformat(str(pair.get("conditionDeadline")))
    except (TypeError, ValueError):
        return skip("requires an ISO conditionDeadline")
    extras = entry.get("extras")
    if not isinstance(extras, dict) or not isinstance(
        extras.get("sourceBinding"), dict
    ):
        return skip("requires committed extras with a sourceBinding template")
    window = extras.get("expectedReleaseWindow")
    if not isinstance(window, dict) or set(window) != {"start", "end"}:
        return skip("requires an exact expectedReleaseWindow")
    try:
        start = dt.date.fromisoformat(str(window["start"]))
        end = dt.date.fromisoformat(str(window["end"]))
    except (TypeError, ValueError):
        return skip("has a malformed expectedReleaseWindow")
    if start > end:
        return skip("window ends before it starts")
    basis = extras.get("resolutionDateBasis", "release-calendar")
    if not isinstance(basis, str) or basis not in {
        "release-calendar",
        "resolve-by-bound",
    }:
        return skip(f"has unsupported resolutionDateBasis {basis!r}")
    if basis == "resolve-by-bound":
        if extras.get("resolutionDate") != window["end"]:
            return skip("resolve-by-bound requires resolutionDate to equal window end")
    if start <= deadline:
        return skip("release window must open after the condition deadline")
    if today >= start:
        return skip(f"forecast generation must precede release window start {start}")
    if today >= deadline:
        return skip(f"condition deadline {deadline} has passed")
    arms = pair.get("arms")
    if not isinstance(arms, list) or len(arms) != 2:
        return skip("requires exactly two arms")
    # The reviewed arm identity fields are authoritative; a registry extras
    # block must never be able to restate them (extras spread first, arm
    # fields last, and the reserved keys are rejected outright).
    reserved = {
        "series",
        "period",
        "catalogSlug",
        "dataPointId",
        "conditional",
        "conditionId",
        "conditionDeadline",
    }
    clashing = reserved & set(extras)
    if clashing:
        return skip(f"extras restate reserved target keys {sorted(clashing)}")
    seen_slugs: set[str] = set()
    seen_ids: set[str] = set()
    seen_conditionals: set[str] = set()
    targets: list[dict] = []
    period_token = period.replace("-", "_")
    for arm in arms:
        if not isinstance(arm, dict):
            return skip("has a non-object arm")
        slug = arm.get("catalogSlug")
        data_point_id = arm.get("dataPointId")
        conditional = arm.get("conditional")
        condition_id = arm.get("conditionId")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (slug, data_point_id, conditional, condition_id)
        ):
            return skip(
                "arms require catalogSlug, dataPointId, conditional, and conditionId"
            )
        # Every arm resolves under the binding's declared release policy for
        # THIS period. Registered-query snapshots carry that policy token in
        # their ids; every other conditional-pair family retains the
        # first_print spelling. A mismatch would route the resolver under
        # different vintage semantics than the committed source binding.
        binding = extras["sourceBinding"]
        release_policy = binding.get("releasePolicy")
        resolution_token = (
            "registered_query_snapshot"
            if release_policy == "registered_query_snapshot"
            else "first_print"
        )
        if not re.fullmatch(
            rf"{re.escape(entry['series'])}\.{re.escape(period_token)}"
            rf"\.{re.escape(resolution_token)}\.[a-z0-9_]+",
            data_point_id,
        ):
            return skip(
                f"arm dataPointId {data_point_id!r} does not match "
                f"sourceBinding.releasePolicy {release_policy!r}; expected "
                f"{entry['series']}.{period}.{resolution_token}."
                "<condition_token>"
            )
        seen_slugs.add(slug)
        seen_ids.add(data_point_id)
        seen_conditionals.add(conditional)
        if slug in catalog_slugs:
            continue
        targets.append(
            {
                **extras,
                "series": entry["series"],
                "period": period,
                "catalogSlug": slug,
                "dataPointId": data_point_id,
                "conditional": conditional,
                "conditionId": condition_id,
                "conditionDeadline": pair["conditionDeadline"],
            }
        )
    if len(seen_slugs) != 2 or len(seen_ids) != 2 or len(seen_conditionals) != 2:
        return skip("arms must have distinct slugs, ids, and conditionals")
    return targets


def recurring_seed_target(
    entry: dict,
    catalog_slugs: set[str],
    today: dt.date,
    *,
    horizon_days: int = ROLL_HORIZON_DAYS,
) -> dict | None:
    """Admit one reviewed seed for a recurring series with no public cursor.

    The seed period and its release date are immutable registry inputs. This
    helper never cadence-steps either value: after the seed slug is published,
    the normal published-period cursor owns all future rolls. If the seed is
    registered but remains unpublished, main's candidate guard leaves that
    immutable registration to the explicit retry or terminal-expiry flow.
    """

    cadence = entry.get("cadence")
    if cadence not in {"weekly", "monthly", "quarterly", "annual"}:
        return None
    if latest_published_period(entry, catalog_slugs) is not None:
        return None

    period = entry.get("seedPeriod")
    canonical_pattern = {
        "weekly": r"week_\d{4}-\d{2}-\d{2}",
        "monthly": r"\d{4}-\d{2}",
        "quarterly": r"\d{4}-Q[1-4]",
        "annual": r"\d{4}",
    }[cadence]
    if (
        not isinstance(period, str)
        or re.fullmatch(canonical_pattern, period) is None
        or period_key(period, cadence) is None
    ):
        print(
            f"  warning: skip {entry.get('series', '?')}: recurring seed "
            f"requires a canonical {cadence} seedPeriod",
            file=sys.stderr,
        )
        return None
    if not not_too_far_ahead(period, cadence, today):
        print(
            f"  warning: skip {entry.get('series', '?')} seed {period}: "
            "period is outside the normal roll horizon",
            file=sys.stderr,
        )
        return None

    release_dates = entry.get("releaseDates")
    release_value = (
        release_dates.get(period) if isinstance(release_dates, dict) else None
    )
    try:
        if not isinstance(release_value, str):
            raise ValueError
        release_day = dt.date.fromisoformat(release_value)
    except ValueError:
        print(
            f"  warning: skip {entry.get('series', '?')} seed {period}: "
            f"requires an explicit ISO releaseDates[{period!r}]",
            file=sys.stderr,
        )
        return None
    if release_day <= today:
        print(
            f"  warning: skip {entry.get('series', '?')} seed {period}: "
            f"official release {release_day} is not after docket date {today}",
            file=sys.stderr,
        )
        return None
    if release_day > today + dt.timedelta(days=horizon_days):
        print(
            f"  warning: skip {entry.get('series', '?')} seed {period}: "
            f"official release {release_day} is outside the "
            f"{horizon_days}-day roll horizon",
            file=sys.stderr,
        )
        return None

    calendar_url = entry.get("releaseCalendarUrl")
    try:
        parsed_calendar = (
            urllib.parse.urlparse(calendar_url)
            if isinstance(calendar_url, str)
            else None
        )
    except ValueError:
        parsed_calendar = None
    if (
        parsed_calendar is None
        or parsed_calendar.scheme.lower() != "https"
        or not parsed_calendar.hostname
    ):
        print(
            f"  warning: skip {entry.get('series', '?')} seed {period}: "
            "requires an HTTPS releaseCalendarUrl",
            file=sys.stderr,
        )
        return None

    try:
        slug = format_slug(entry["slug"], period, cadence)
    except (IndexError, KeyError, TypeError, ValueError):
        print(
            f"  warning: skip {entry.get('series', '?')} seed {period}: "
            "malformed recurring slug template",
            file=sys.stderr,
        )
        return None
    if slug in catalog_slugs:
        print(
            f"  warning: skip {entry.get('series', '?')} seed {period}: "
            f"catalog slug {slug!r} already exists",
            file=sys.stderr,
        )
        return None

    extras = entry.get("extras")
    return {
        "series": entry["series"],
        "period": period,
        "seedPeriod": period,
        "catalogSlug": slug,
        **(extras if isinstance(extras, dict) else {}),
        "expectedReleaseDate": release_day.isoformat(),
        "releaseCalendarUrl": calendar_url,
    }


def target_extras_for_period(entry: dict, period: str) -> dict | None:
    """Return target extras, requiring a dated slot for calendar-gated sources.

    A previous target's resolution date is not evidence for the next official
    release date. Calendar-gated adapters therefore roll only when the
    committed registry maps the exact reference period to an agency-published
    date and records the calendar used to verify it. Neither a mirror nor a
    mutable current table supplies the publisher's future release calendar.
    """
    extras = entry.get("extras") or {}
    binding = extras.get("sourceBinding") if isinstance(extras, dict) else None
    adapter = binding.get("adapter") if isinstance(binding, dict) else None
    if adapter not in CALENDAR_GATED_SOURCE_ADAPTERS:
        return dict(extras)

    release_dates = entry.get("releaseDates")
    release_date = (
        release_dates.get(period) if isinstance(release_dates, dict) else None
    )
    calendar_url = entry.get("releaseCalendarUrl")
    try:
        if not isinstance(release_date, str):
            raise ValueError("missing date")
        dt.date.fromisoformat(release_date)
        if not isinstance(calendar_url, str) or not calendar_url.startswith("https://"):
            raise ValueError("missing HTTPS calendar URL")
    except ValueError:
        print(
            f"  warning: skip {entry.get('series', '?')} {period}: "
            "calendar-gated adapter has no valid explicit official release date "
            "and releaseCalendarUrl in the docket registry",
            file=sys.stderr,
        )
        return None

    return {
        **extras,
        "expectedReleaseDate": release_date,
        "releaseCalendarUrl": calendar_url,
    }


def advance_past_released_native_periods(
    entry: dict, period: str, today: dt.date
) -> str | None:
    """Advance over never-forecast periods whose official print is now known.

    The normal docket cursor advances only through published forecasts. A
    newly adopted series can therefore point at a missed historical period.
    Committed calendar metadata lets us skip that known outcome without ever
    generating a post-release forecast, then select the first still-unreleased
    period that has meaningfully begun.
    """
    extras = entry.get("extras") or {}
    binding = extras.get("sourceBinding") if isinstance(extras, dict) else None
    adapter = binding.get("adapter") if isinstance(binding, dict) else None
    if adapter not in CALENDAR_GATED_SOURCE_ADAPTERS:
        return period

    candidate = period
    release_dates = entry.get("releaseDates")
    while True:
        release_value = (
            release_dates.get(candidate) if isinstance(release_dates, dict) else None
        )
        try:
            release_day = dt.date.fromisoformat(str(release_value))
        except ValueError:
            # target_extras_for_period emits the precise missing-date warning.
            return candidate
        if release_day > today:
            return candidate
        print(
            f"  skip {entry.get('series', '?')} {candidate}: official "
            f"release {release_day} is not after docket date {today}",
            file=sys.stderr,
        )
        following = step_period(candidate, entry["cadence"])
        if following is None or not not_too_far_ahead(
            following, entry["cadence"], today
        ):
            return None
        candidate = following


def select_capped_targets(
    candidates: list[tuple[int, str, dict | list[dict]]],
    max_targets: int,
) -> tuple[list[dict], int]:
    """Admit whole candidate units in priority order under the cap.

    A conditional pair's unpublished arms are one unit: selection stops at
    the first unit that does not fit rather than splitting it (or skipping
    ahead past it), so the cap can never register or forecast one arm of a
    pair without its sibling.
    """

    ordered = sorted(candidates, key=lambda item: (item[0], item[1]))
    targets: list[dict] = []
    dropped = 0
    capped = False
    for _, _, unit in ordered:
        group = unit if isinstance(unit, list) else [unit]
        if capped or len(targets) + len(group) > max_targets:
            capped = True
            dropped += len(group)
            continue
        targets.extend(group)
    return targets, dropped


def roll_execution_plan_refusal(target: dict) -> str | None:
    """Why registration would refuse this candidate for lack of an executor.

    A target whose contract cannot even be built returns None and keeps its
    cap slot, as it always has: registration's ``--skip-unbindable`` report
    names the binding error. A contract that builds but that the resolver
    cannot judge is a refusal here, as it is in prospect validation.
    """

    try:
        contract = build_contract(target, dt.date.today())
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    try:
        return execution_plan_refusal({"contract": contract, "targetContentHash": None})
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return f"the resolver could not judge the contract: {exc}"


def append_roll_candidate(
    candidates: list[tuple[int, str, dict | list[dict]]],
    priority: int,
    sort_key: str,
    unit: dict | list[dict],
    *,
    expired_data_point_ids: frozenset[str],
    registered_data_point_ids: frozenset[str],
    allow_registered_bounded: bool = False,
) -> None:
    """Append an eligible target unit without reviving or re-registering ids.

    Conditional arms are one chronological unit. If either arm is terminally
    expired or already registered, both arms stay out of the candidate pool and
    each skipped arm is reported before cap selection. The attested bounded
    lane may deliberately reuse an existing resolve-by-bound registration, but
    it can never reuse a terminally expired id.
    """

    group = unit if isinstance(unit, list) else [unit]
    target_ids = [
        derive_data_point_id(target, target.get("previousTarget")) for target in group
    ]
    expired_in_unit = sorted(expired_data_point_ids.intersection(target_ids))
    reuses_bounded_registration = allow_registered_bounded and all(
        target.get("resolutionDateBasis") == "resolve-by-bound" for target in group
    )
    registered_in_unit = (
        []
        if reuses_bounded_registration
        else sorted(registered_data_point_ids.intersection(target_ids))
    )
    if not expired_in_unit and not registered_in_unit:
        # A series the resolver cannot execute must not spend the cap, and
        # must not mint another target: the cursor steps from the latest
        # PUBLISHED period, so nothing else stops it. An id that is already
        # registered is an existing contract and is not re-judged.
        unexecutable = [
            (target, refusal)
            for target, data_point_id in zip(group, target_ids)
            if data_point_id not in registered_data_point_ids
            and (refusal := roll_execution_plan_refusal(target)) is not None
        ]
        if not unexecutable:
            candidates.append((priority, sort_key, unit))
            return
        for target, refusal in unexecutable:
            print(
                f"  skip {target.get('catalogSlug', '?')}: no executable "
                f"resolution plan — {refusal}"
            )
        for target in group:
            if all(target is not refused for refused, _ in unexecutable):
                print(
                    f"  skip {target.get('catalogSlug', '?')}: conditional "
                    "pair-mate has no executable resolution plan; refusing to "
                    "split the pair"
                )
        return

    for target, data_point_id in zip(group, target_ids):
        slug = target.get("catalogSlug", "?")
        if data_point_id in expired_data_point_ids:
            reason = f"dataPointId {data_point_id} is terminally expired-unforecast"
        elif expired_in_unit:
            reason = (
                "conditional pair-mate dataPointId "
                f"{expired_in_unit[0]} is terminally expired-unforecast"
            )
        elif data_point_id in registered_data_point_ids:
            reason = (
                f"dataPointId {data_point_id} already has an immutable "
                "registration; refusing to re-register"
            )
        else:
            reason = (
                "conditional pair-mate dataPointId "
                f"{registered_in_unit[0]} already has an immutable registration; "
                "refusing to split the pair"
            )
        print(f"  skip {slug}: {reason}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cadence", choices=["weekly", "monthly", "quarterly", "annual"]
    )
    parser.add_argument(
        "--series",
        help=(
            "Roll only this exact registry series. The dispatch-level "
            "selector for one-shot targets (reviewed conditional pairs, "
            "seeds) whose treatment must not drag the rest of the due "
            "docket through the same prompt mode and model."
        ),
    )
    parser.add_argument("--max-targets", type=int, default=12)
    parser.add_argument("--out")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--include-bounded",
        action="store_true",
        help=(
            "Include resolve-by-bound targets for the attested generation-ticket "
            "selector. Ordinary auto-roll must leave this disabled."
        ),
    )
    args = parser.parse_args()

    registry = json.loads(REGISTRY.read_text())["series"]
    if args.series and not any(
        entry.get("series") == args.series for entry in registry
    ):
        print(f"unknown registry series: {args.series}", file=sys.stderr)
        return 1
    try:
        expired_data_point_ids = expired_unforecast_registrations(ROOT)
        registered_data_point_ids = frozenset(
            load_registered_targets(TARGET_REGISTRATIONS)
        )
    except ChallengeSubmissionError as error:
        print(f"cannot load roll exclusion state: {error}", file=sys.stderr)
        return 1

    existing, published_forecasts, observed_slugs = live_catalog()
    today = dt.date.today()

    candidates: list[tuple[int, str, dict | list[dict]]] = []
    for entry in registry:
        if args.series and entry.get("series") != args.series:
            continue
        if args.cadence and entry["cadence"] != args.cadence:
            continue
        extras = entry.get("extras")
        if (
            isinstance(extras, dict)
            and extras.get("resolutionDateBasis") == "resolve-by-bound"
            and not args.include_bounded
        ):
            print(
                f"  skip {entry['series']}: resolve-by-bound target requires "
                "the attested generation-ticket lane"
            )
            continue
        if isinstance(entry.get("conditionalPair"), dict):
            pair_targets = conditional_pair_seed_targets(entry, existing, today)
            if not pair_targets:
                print(f"  skip {entry['series']}: no eligible conditional-pair arm")
                continue
            # Unpublished arms of a pair are one atomic unit: registering
            # or forecasting one arm ahead of its sibling would let the
            # later arm run with extra information.
            deadline = entry["conditionalPair"]["conditionDeadline"]
            append_roll_candidate(
                candidates,
                2,
                deadline,
                pair_targets,
                expired_data_point_ids=expired_data_point_ids,
                registered_data_point_ids=registered_data_point_ids,
                allow_registered_bounded=args.include_bounded,
            )
            continue
        if entry["cadence"] == "annual":
            extras = entry.get("extras")
            binding = extras.get("sourceBinding") if isinstance(extras, dict) else None
            calendar_gated_annual = (
                isinstance(binding, dict)
                and binding.get("adapter") in CALENDAR_GATED_SOURCE_ADAPTERS
            )
            if (
                isinstance(binding, dict)
                and binding.get("releasePolicy") == "registered_query_snapshot"
            ):
                target = snapshot_seed_target(entry, existing, today)
                sort_key = (
                    target["expectedReleaseWindow"]["start"]
                    if target is not None
                    else ""
                )
            elif (
                calendar_gated_annual
                and latest_published_period(entry, existing) is not None
            ):
                # Unlike annual snapshots and bounded seeds, an official
                # calendar series is recurring. Its published seed joins the
                # normal cursor below; an undated successor still fails at
                # target_extras_for_period rather than being cadence-inferred.
                target = None
                sort_key = ""
            elif calendar_gated_annual:
                target = recurring_seed_target(entry, existing, today)
                sort_key = target["expectedReleaseDate"] if target is not None else ""
            else:
                target = bounded_annual_first_print_seed_target(entry, existing, today)
                sort_key = (
                    target["expectedReleaseWindow"]["start"]
                    if target is not None
                    else ""
                )
            if target is None and not (
                calendar_gated_annual
                and latest_published_period(entry, existing) is not None
            ):
                print(f"  skip {entry['series']}: no eligible reviewed annual seed")
                continue
            if target is not None:
                append_roll_candidate(
                    candidates,
                    2,
                    sort_key,
                    target,
                    expired_data_point_ids=expired_data_point_ids,
                    registered_data_point_ids=registered_data_point_ids,
                    allow_registered_bounded=args.include_bounded,
                )
                continue
        latest = latest_published_period(entry, existing)
        if latest is None:
            target = recurring_seed_target(entry, existing, today)
            if target is None:
                print(
                    f"  skip {entry['series']}: no published cell and no "
                    "eligible reviewed seed"
                )
                continue
            append_roll_candidate(
                candidates,
                0,
                target["expectedReleaseDate"],
                target,
                expired_data_point_ids=expired_data_point_ids,
                registered_data_point_ids=registered_data_point_ids,
                allow_registered_bounded=args.include_bounded,
            )
            continue
        next_result = next_roll_period(entry, existing, observed_slugs, today)
        if next_result is None:
            print(f"  skip {entry['series']}: no eligible successor within horizon")
            continue
        nxt, latest_slug = next_result
        nxt = advance_past_released_native_periods(entry, nxt, today)
        if nxt is None:
            continue
        previous_period = next(
            period
            for period, published_slug in published_periods(entry, existing)
            if published_slug == latest_slug
        )
        attempted = latest_recorded_period(entry["series"], entry["cadence"])
        if (
            latest
            and attempted is not None
            and (period_key(attempted, entry["cadence"]) or ())
            > (period_key(latest[0], entry["cadence"]) or ())
        ):
            print(
                f"  pending {entry['series']} {nxt}: an attempt for "
                f"{attempted} was recorded but never published"
            )
        slug = format_slug(entry["slug"], nxt, entry["cadence"])
        if slug in existing:
            continue
        extras = target_extras_for_period(entry, nxt)
        if extras is None:
            continue
        target = {
            "series": entry["series"],
            "period": nxt,
            "catalogSlug": slug,
            **extras,
        }
        previous = published_forecasts.get(latest_slug)
        if previous:
            target["previousTarget"] = {
                key: previous[key]
                for key in (
                    "country",
                    "unit",
                    "dataPointId",
                    "resolutionDate",
                    "resolutionSource",
                    "resolutionSourceUrl",
                    "resolutionRule",
                    "resolutionPolicy",
                    "sourceContext",
                )
                if previous.get(key) not in (None, "")
            }
            target["previousTarget"]["period"] = previous_period
        # One-shot snapshots get the middle lane so a permanently busy
        # monthly docket cannot starve their finite preregistration window.
        priority = 1 if entry["cadence"] == "weekly" else 3
        append_roll_candidate(
            candidates,
            priority,
            nxt,
            target,
            expired_data_point_ids=expired_data_point_ids,
            registered_data_point_ids=registered_data_point_ids,
            allow_registered_bounded=args.include_bounded,
        )

    targets, dropped = select_capped_targets(candidates, args.max_targets)
    if dropped > 0:
        print(f"  capped: {dropped} further targets deferred to the next run")

    for target in targets:
        print(f"  roll {target['catalogSlug']} ({target['series']} {target['period']})")
    print(f"{len(targets)} targets")

    if args.out and not args.dry_run:
        pathlib.Path(args.out).write_text(
            json.dumps({"targets": targets}, indent=1) + "\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
