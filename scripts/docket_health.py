#!/usr/bin/env python3
"""Report a docket that has stalled while its roll stays green.

A roll with nothing to register exits 0, which is right on a quiet day. These
things can then go wrong with no failed run to show for it:

- Registrations stop. The roll registers weekly claims on every run, so a gap
  over STALL_DAYS means it has stopped working or stopped running.
- A series' release dates run out, or skip a period. Nothing refreshes
  scripts/docket_series.json: someone reads the agency's calendar and commits
  the dates by a reviewed edit. The roller stops at the first period with no
  date and says so on a log nobody reads, which left most monthly series
  unregistered through October 2026.
- A series with no published forecast misses its seed. The roller registers a
  reviewed seed only before its print, so the series never starts.
- A registered target gets no forecast. Inside its orphan grace the batch can
  sometimes still be recovered. Past grace, the site suite's "forecasts every
  registered ledger target" fails every later publish until the id goes on
  site/src/data/expired-unforecast-registrations.ts.

The job reads state and writes only its report and issue body. Findings leave
the exit code at 0: .github/workflows/docket-health.yml turns them into one
standing issue. A nonzero exit means the check could not read its state.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import dataclasses
import datetime as dt
import hashlib
import io
import json
import pathlib
import re
import subprocess
import sys
from collections.abc import Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import roll_docket  # noqa: E402
from docket_publication import ORPHAN_GRACE_DAYS  # noqa: E402

STALL_DAYS = 10
# A release calendar that ends this soon needs a read while the next period's
# print can still register.
RUNWAY_DAYS = 21
# A healthy roll forecasts and publishes on the day it registers, so a target
# one day old with no forecast has already left the normal path.
UNFORECAST_WARNING_AGE = dt.timedelta(days=1)

STALL = "registration-stall"
CALENDAR = "calendar-runway"
GAP = "calendar-gap"
SEED = "seed-missed"
IN_GRACE = "unforecast-in-grace"
PAST_GRACE = "unforecast-past-grace"

REGISTRATION_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-[0-9a-f]{64}\.json$")


@dataclasses.dataclass(frozen=True)
class Finding:
    kind: str
    subject: str
    detail: str


def registration_stall(names: Iterable[str], today: dt.date) -> Finding | None:
    days = [
        dt.date.fromisoformat(match.group(1))
        for match in map(REGISTRATION_NAME.match, names)
        if match
    ]
    if not days:
        return Finding(STALL, "records/targets", "No registration exists.")
    newest = max(days)
    age = (today - newest).days
    if age <= STALL_DAYS:
        return None
    return Finding(
        STALL,
        "records/targets",
        f"The newest registration dates from {newest}, {age} days ago. The roll "
        "registers weekly claims on every run, so it has stopped registering.",
    )


def _gated_rolling_entry(entry: dict) -> bool:
    extras = entry.get("extras")
    if not isinstance(extras, dict):
        return False
    binding = extras.get("sourceBinding")
    return (
        isinstance(binding, dict)
        and binding.get("adapter") in roll_docket.CALENDAR_GATED_SOURCE_ADAPTERS
        and extras.get("resolutionDateBasis") != "resolve-by-bound"
        and entry.get("cadence") in {"monthly", "quarterly"}
        and not isinstance(entry.get("conditionalPair"), dict)
    )


def successor_refusal(
    entry: dict,
    period: str,
    today: dt.date,
    published_forecasts: dict[str, dict],
    published: tuple[str, str] | None,
) -> str | None:
    """Why a date alone would not let this period register.

    The answer comes from the roller's own gate, given a placeholder date held
    in memory. Refused series, such as those on a registration hold, stay out of
    the alarm: a new date cannot help them. A series with no published period
    is judged as the seed it would need.
    """

    probe = copy.deepcopy(entry)
    probe["releaseDates"] = {period: (today + dt.timedelta(days=45)).isoformat()}
    probe.setdefault("releaseCalendarUrl", "https://calendar.invalid/placeholder")
    extras = roll_docket.target_extras_for_period(probe, period)
    if extras is None:
        return "the entry has no calendar-gated contract"
    target = {
        "series": entry["series"],
        "period": period,
        "catalogSlug": roll_docket.format_slug(entry["slug"], period, entry["cadence"]),
        **extras,
    }
    if published is None:
        target["seedPeriod"] = period
    else:
        published_period, published_slug = published
        previous = published_forecasts.get(published_slug)
        if previous:
            target["previousTarget"] = roll_docket.previous_target_block(
                previous, published_period
            )
    return roll_docket.roll_execution_plan_refusal(target)


def _release_dates(entry: dict) -> dict:
    dates = entry.get("releaseDates")
    return dates if isinstance(dates, dict) else {}


def _dated(value: object) -> bool:
    """Whether target_extras_for_period would accept this committed date."""

    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _calendar(entry: dict) -> str:
    return f"Calendar: {entry.get('releaseCalendarUrl', 'none recorded')}"


def runway_shortfall(
    entry: dict, published_period: str, today: dt.date
) -> tuple[str, str] | None:
    """The period past a committed calendar that ends inside the runway."""

    cadence = entry["cadence"]
    dates = {
        period: value
        for period, value in _release_dates(entry).items()
        if _dated(value)
    }
    last_print = max(map(dt.date.fromisoformat, dates.values()), default=None)
    if last_print is not None and last_print - today >= dt.timedelta(days=RUNWAY_DAYS):
        return None
    last_period = max(
        [published_period, *dates],
        key=lambda period: roll_docket.period_key(period, cadence) or (),
    )
    following = roll_docket.step_period(last_period, cadence)
    if following is None:
        return None
    ends = (
        "It has no committed date"
        if last_print is None
        else f"Its committed calendar ends {last_print}, "
        f"{(last_print - today).days} days from now"
    )
    return following, f"{ends}, and {following} has no date. {_calendar(entry)}"


def undated_periods(entry: dict, published_period: str) -> list[str]:
    """Periods past the cursor that the calendar skips before its last date.

    The roller never steps past a period with no date, so the first of these
    holds the series however far the later dates run, and the runway check
    cannot see it.
    """

    cadence = entry["cadence"]
    dates = _release_dates(entry)
    dated_keys = [
        roll_docket.period_key(period, cadence)
        for period, value in dates.items()
        if _dated(value)
    ]
    last = max((key for key in dated_keys if key is not None), default=None)
    skipped: list[str] = []
    period = roll_docket.step_period(published_period, cadence)
    while last is not None and period is not None:
        key = roll_docket.period_key(period, cadence)
        if key is None or key >= last:
            break
        if not _dated(dates.get(period)):
            skipped.append(period)
        period = roll_docket.step_period(period, cadence)
    return skipped


def roller_period(
    entry: dict,
    published_slugs: set[str],
    observed_slugs: set[str] | frozenset[str],
    today: dt.date,
) -> str | None:
    """The period roll_docket.main tries for this series today."""

    chosen = roll_docket.next_roll_period(
        entry, published_slugs, set(observed_slugs), today
    )
    if chosen is None:
        return None
    with contextlib.redirect_stderr(io.StringIO()):
        return roll_docket.advance_past_released_native_periods(entry, chosen[0], today)


def seed_shortfall(
    entry: dict,
    published_slugs: set[str],
    today: dt.date,
    expired_ids: frozenset[str],
) -> tuple[str, str] | None:
    """The seed of a series with no published period, when it cannot register.

    Such a series rolls only from its reviewed seed, and the roller registers a
    seed only before its print. A series with no seed waits on a reviewed edit
    to give it one, which is a choice and not a stall, so it stays quiet.
    """

    period = entry.get("seedPeriod")
    if not isinstance(period, str):
        return None
    release = _release_dates(entry).get(period)
    if not _dated(release):
        problem = f"Its seed {period} has no committed date"
    elif dt.date.fromisoformat(release) <= today:
        problem = f"Its seed {period} printed {release} with no published forecast"
    else:
        with contextlib.redirect_stderr(io.StringIO()):
            seed = roll_docket.recurring_seed_target(entry, published_slugs, today)
        if seed is None or (
            roll_docket.derive_data_point_id(seed, None) not in expired_ids
        ):
            return None
        problem = f"Its seed {period} registered, went unforecast and expired"
    return period, (
        f"{problem}, so the series has no published period to roll from. "
        f"{_calendar(entry)}"
    )


def calendar_findings(
    registry: list[dict],
    published_slugs: set[str],
    published_forecasts: dict[str, dict],
    today: dt.date,
    *,
    observed_slugs: set[str] | frozenset[str] = frozenset(),
    expired_ids: frozenset[str] = frozenset(),
) -> tuple[list[Finding], dict[str, str]]:
    """Series the roller cannot carry forward, and those a date cannot help."""

    findings: list[Finding] = []
    refused: dict[str, str] = {}
    for entry in registry:
        if not _gated_rolling_entry(entry):
            continue
        published = roll_docket.latest_published_period(entry, published_slugs)
        alarms: list[tuple[str, str, str]] = []
        if published is None:
            seed = seed_shortfall(entry, published_slugs, today, expired_ids)
            if seed is not None:
                alarms.append((SEED, *seed))
        else:
            shortfall = runway_shortfall(entry, published[0], today)
            if shortfall is not None:
                alarms.append((CALENDAR, *shortfall))
            skipped = undated_periods(entry, published[0])
            if skipped:
                stopped = (
                    roller_period(entry, published_slugs, observed_slugs, today)
                    == skipped[0]
                )
                where = (
                    f"has stopped at {skipped[0]}"
                    if stopped
                    else f"stops at {skipped[0]} when it gets there"
                )
                alarms.append(
                    (
                        GAP,
                        skipped[0],
                        f"The committed calendar skips {', '.join(skipped)} "
                        "though it dates later periods, and the roller cannot "
                        f"pass an undated period, so the series {where}. "
                        f"{_calendar(entry)}",
                    )
                )
        for kind, period, detail in alarms:
            refusal = successor_refusal(
                entry, period, today, published_forecasts, published
            )
            if refusal is not None:
                refused[entry["series"]] = refusal
                continue
            findings.append(Finding(kind, entry["series"], detail))
    return findings, refused


def unforecast_rows(now: dt.datetime) -> list[dict]:
    """Registered targets with no forecast cell, from the site's own rule."""

    completed = subprocess.run(
        ["bun", str(ROOT / "scripts" / "dump_unforecast_targets.ts"), _utc(now)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=300,
        check=True,
    )
    rows = json.loads(completed.stdout)
    if not isinstance(rows, list):
        raise ValueError("dump_unforecast_targets.ts emitted a non-list")
    return rows


def unforecast_findings(rows: list[dict], now: dt.datetime) -> list[Finding]:
    grace = dt.timedelta(days=ORPHAN_GRACE_DAYS)
    findings: list[Finding] = []
    for row in rows:
        subject = str(row["dataPointId"])
        registered_value = row.get("registeredAt")
        if not row["withinGrace"]:
            findings.append(
                Finding(
                    PAST_GRACE,
                    subject,
                    f"Registered {registered_value} with no forecast, past its "
                    "grace. The site suite fails every publish until this id "
                    "goes on the expired-unforecast list.",
                )
            )
            continue
        registered = dt.datetime.fromisoformat(
            str(registered_value).replace("Z", "+00:00")
        )
        if now - registered >= UNFORECAST_WARNING_AGE:
            findings.append(
                Finding(
                    IN_GRACE,
                    subject,
                    f"Registered {registered_value} with no forecast. Its grace "
                    f"ends {_utc(registered + grace)}.",
                )
            )
    return findings


def _utc(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def fingerprint(findings: list[Finding]) -> str:
    """Stable while the same things stay wrong, though their day counts move."""

    keys = sorted(f"{finding.kind}:{finding.subject}" for finding in findings)
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()[:16]


def render_issue(findings: list[Finding], now: dt.datetime, run_url: str) -> str:
    print_key = fingerprint(findings)
    lines = [
        f"<!-- docket-health:{print_key} -->",
        f"Checked {_utc(now)} by [this run]({run_url}).",
        "",
    ]
    sections = (
        (
            STALL,
            "Registrations stopped",
            "Read the `register` log of the latest Roll the docket run. It "
            "names each series it skipped and why.",
        ),
        (
            PAST_GRACE,
            "Past grace with no forecast",
            "These fail the publish gate. Add each id to "
            "`site/src/data/expired-unforecast-registrations.ts` by a reviewed "
            "change. No run can forecast them now.",
        ),
        (
            IN_GRACE,
            "Inside grace with no forecast",
            "Find the roll that registered them with "
            "`gh run list --workflow roll-docket.yml --created <date>`. If its "
            "`generate` job passed and `publish` failed, fix the cause on main "
            "and run `gh run rerun <run id> --failed`: publish checks out main, "
            "and the batch stays in the run's artifact for 7 days, the same "
            "length as the grace. If `generate` failed, the same command runs it "
            "again from the registration commit, so a fix on main does not reach "
            "it. A target that failed inside a published batch has no such path: "
            "the workflow's `retry_batch` input refuses every batch row with an "
            "`expectedReleaseDate`, and the roller gives one to every "
            "calendar-gated target.",
        ),
        (
            SEED,
            "Seeds that can no longer register",
            "A series with no published forecast rolls only from its reviewed "
            "seed, and the roller registers a seed only before its print. Pick a "
            "period whose print is still ahead, read its date from the official "
            "calendar, and set `seedPeriod` and that date in "
            "`scripts/docket_series.json` by a reviewed edit, recording the read "
            "in `docs/seed-verifications.md`.",
        ),
        (
            GAP,
            "Release calendars that skip a period",
            "Read the official calendar for each skipped period and add its date "
            "to `scripts/docket_series.json` by a reviewed edit, recording the "
            "read in `docs/seed-verifications.md`. Never infer a date from "
            "cadence. A period the agency will never print needs a reviewed fix "
            "to the entry, because nothing moves the roller past it.",
        ),
        (
            CALENDAR,
            "Release calendars running out",
            "Read each official calendar and add the later dates to "
            "`scripts/docket_series.json` by a reviewed edit, recording the "
            "read in `docs/seed-verifications.md`. Never infer a date from "
            "cadence. A `bls-api` calendar that crosses an annual revision also "
            "needs its anchors re-verified: see `docs/anchor-verifications.md`. "
            "An agency that has not posted a date yet leaves nothing to do but "
            "wait, and this entry stays until it does.",
        ),
    )
    for kind, heading, action in sections:
        rows = [finding for finding in findings if finding.kind == kind]
        if not rows:
            continue
        lines += [f"## {heading}", ""]
        lines += [f"- `{row.subject}`: {row.detail}" for row in rows]
        lines += ["", action, ""]
    return "\n".join(lines)


def collect(
    *,
    registry: list[dict],
    registration_names: Iterable[str],
    published_slugs: set[str],
    published_forecasts: dict[str, dict],
    observed_slugs: set[str],
    expired_ids: frozenset[str],
    unforecast: list[dict],
    now: dt.datetime,
) -> tuple[list[Finding], dict[str, str]]:
    today = now.date()
    findings: list[Finding] = []
    stall = registration_stall(registration_names, today)
    if stall is not None:
        findings.append(stall)
    findings += unforecast_findings(unforecast, now)
    calendars, refused = calendar_findings(
        registry,
        published_slugs,
        published_forecasts,
        today,
        observed_slugs=observed_slugs,
        expired_ids=expired_ids,
    )
    return findings + calendars, refused


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=pathlib.Path, required=True)
    parser.add_argument("--issue-body", type=pathlib.Path, required=True)
    parser.add_argument("--run-url", default="")
    args = parser.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    published_slugs, published_forecasts, observed_slugs = roll_docket.live_catalog()
    findings, refused = collect(
        registry=json.loads(roll_docket.REGISTRY.read_text())["series"],
        registration_names=[
            path.name for path in roll_docket.TARGET_REGISTRATIONS.glob("*.json")
        ],
        published_slugs=published_slugs,
        published_forecasts=published_forecasts,
        observed_slugs=observed_slugs,
        expired_ids=roll_docket.expired_unforecast_registrations(ROOT),
        unforecast=unforecast_rows(now),
        now=now,
    )
    for finding in findings:
        print(f"{finding.kind} {finding.subject}: {finding.detail}")
    for series, refusal in sorted(refused.items()):
        print(f"no alarm for {series}: a date cannot help: {refusal}")
    print(f"{len(findings)} finding(s)")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {
                "checkedAt": _utc(now),
                "fingerprint": fingerprint(findings),
                "findings": [dataclasses.asdict(finding) for finding in findings],
                "refused": refused,
            },
            indent=2,
        )
        + "\n"
    )
    args.issue_body.parent.mkdir(parents=True, exist_ok=True)
    args.issue_body.write_text(render_issue(findings, now, args.run_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
