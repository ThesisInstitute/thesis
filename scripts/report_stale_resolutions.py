#!/usr/bin/env python3
"""Report forecasts that matured but never resolved.

The resolve loop only alarms when the WORKFLOW fails. A cell whose adapter
quietly returns nothing -- or a cell whose series has no adapter at all, so
`pending_adapter_refs` never enumerates it -- stays `pending` forever while
every run stays green. The Brier surfaces cannot see it either: the split is
computed as `if (!resolved) return "unresolved"`, with no notion of age, so a
cell 29 days past its release sits in the same bucket as one due next month.

A forecast that never resolves yields no score, no reward row, and no
calibration signal, which is the one outcome the lab exists to prevent. This
reports the backlog by age so it is visible instead of silent.

Measured 2026-07-31 against the published log: 37 of 192 matured cells (19%)
had no official observation, 19 of them more than 14 days past due, the
oldest three (BLS CES industry employment for June 2026) at 29 days.

Deliberately read-only: it fetches the published log, resolves nothing, and
writes nothing. Wire it into a workflow to alarm; run it by hand to triage.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from thesis_log_client import LOG_URL, load_thesis_log  # noqa: E402

# Agencies miss their own calendars by a day or two often enough that a
# zero-day grace would cry wolf every release morning. A week is past any
# routine slip while still catching the multi-week failures that matter.
DEFAULT_GRACE_DAYS = 7


class StaleReportError(RuntimeError):
    """The log could not be read or did not carry the expected shape."""


def load_log(url: str, path: str | None) -> dict:
    """Hydrate the log through the shared client, never by hand.

    log.json is a thesis_log_v3 MANIFEST: `entries` lives in separate
    chunk files listed under `collections`. Reading the manifest directly
    yields zero entries, so every pending link loses its resolutionDate and
    the report silently prints an all-clear -- the exact false negative this
    script exists to prevent (caught 2026-07-31 against the live log).
    load_thesis_log also canonical-hash checks each chunk.
    """

    manifest = (
        json.loads(pathlib.Path(path).read_text(encoding="utf-8")) if path else None
    )
    try:
        return load_thesis_log(url, manifest=manifest)
    except ValueError as error:
        raise StaleReportError(str(error)) from error


def forecast_index(log: dict) -> dict[str, dict]:
    """forecastSlug -> its prediction_recorded entry."""
    return {
        entry["forecastSlug"]: entry
        for entry in log.get("entries", [])
        if entry.get("kind") == "prediction_recorded" and entry.get("forecastSlug")
    }


def stale_pending(log: dict, today: dt.date, grace_days: int) -> list[dict]:
    """Pending resolution links whose forecast matured more than grace ago.

    Mirrors how the resolver reads the log (`resolutionLinks` filtered to
    status == "pending", joined to the forecast for its resolutionDate) so
    this reports on exactly the population the resolver is responsible for
    -- plus the cells it never enumerates because they have no adapter.
    """

    forecasts = forecast_index(log)
    links = log.get("resolutionLinks")
    if links is None:
        raise StaleReportError("log has no resolutionLinks")

    # Fail loudly rather than report a false all-clear. Every maturity test
    # below needs the forecast's resolutionDate, so an unhydrated log makes
    # each link skip and the backlog print as empty. A log with pending
    # links but no forecasts is broken, not clean.
    if any(link.get("status") == "pending" for link in links) and not forecasts:
        raise StaleReportError(
            "log carries pending resolutionLinks but no prediction_recorded "
            "entries; the v3 collections were not hydrated, so maturity "
            "cannot be judged"
        )

    stale: list[dict] = []
    for link in links:
        if link.get("status") != "pending":
            continue
        forecast = forecasts.get(link.get("forecastSlug")) or {}
        release = str(forecast.get("resolutionDate") or "")
        if not release:
            # No resolutionDate means nothing can judge maturity; the
            # registration gates own that case, not this report.
            continue
        try:
            due = dt.date.fromisoformat(release)
        except ValueError:
            continue
        overdue = (today - due).days
        if overdue <= grace_days:
            continue
        stale.append(
            {
                "ref": link.get("targetFactRef") or "",
                "slug": link.get("forecastSlug") or "",
                "resolutionDate": release,
                "daysOverdue": overdue,
                "agency": (link.get("targetFactRef") or "?").split(".")[0],
            }
        )
    stale.sort(key=lambda row: (-row["daysOverdue"], row["ref"]))
    return stale


def age_buckets(stale: list[dict]) -> dict[str, int]:
    buckets: collections.Counter[str] = collections.Counter()
    for row in stale:
        days = row["daysOverdue"]
        if days > 60:
            buckets[">60d"] += 1
        elif days > 30:
            buckets["31-60d"] += 1
        elif days > 14:
            buckets["15-30d"] += 1
        else:
            buckets["<=14d"] += 1
    return dict(buckets)


def render(stale: list[dict], pending_total: int, grace_days: int) -> str:
    if not stale:
        return (
            f"stale resolutions OK: no pending cell is more than "
            f"{grace_days} days past its resolutionDate "
            f"({pending_total} pending overall)"
        )
    lines = [
        f"stale resolutions: {len(stale)} of {pending_total} pending cells "
        f"matured more than {grace_days} days ago and never resolved",
        "",
        "  by age:    "
        + ", ".join(f"{k}={v}" for k, v in sorted(age_buckets(stale).items())),
    ]
    agencies = collections.Counter(row["agency"] for row in stale)
    lines.append(
        "  by agency: "
        + ", ".join(f"{k}={v}" for k, v in agencies.most_common())
    )
    lines.append("")
    for row in stale:
        lines.append(
            f"  {row['resolutionDate']}  {row['daysOverdue']:>4}d overdue  "
            f"{row['ref']}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-url", default=LOG_URL)
    parser.add_argument(
        "--log-file", default=None, help="read a local log.json instead of fetching"
    )
    parser.add_argument("--grace-days", type=int, default=DEFAULT_GRACE_DAYS)
    parser.add_argument(
        "--today", default=None, help="ISO date to age against (default: today)"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the backlog as JSON"
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="exit 1 when the backlog is non-empty (for workflow alarms)",
    )
    args = parser.parse_args()

    if args.grace_days < 0:
        raise StaleReportError("--grace-days must not be negative")
    today = (
        dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    )

    log = load_log(args.log_url, args.log_file)
    pending_total = sum(
        1
        for link in (log.get("resolutionLinks") or [])
        if link.get("status") == "pending"
    )
    stale = stale_pending(log, today, args.grace_days)

    if args.json:
        print(json.dumps({"graceDays": args.grace_days, "stale": stale}, indent=2))
    else:
        print(render(stale, pending_total, args.grace_days))

    return 1 if (stale and args.fail_on_stale) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except StaleReportError as error:
        print(f"stale resolution report failed: {error}", file=sys.stderr)
        sys.exit(2)
