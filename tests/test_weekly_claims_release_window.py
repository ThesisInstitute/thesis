"""Weekly claims release windows derive from the reference week, not the roll.

Observed on origin/main 2026-09-20: every roll of the two weekly
SERIES_BINDINGS series copied the previous published forecast's
``resolutionDate`` into ``previousTarget`` and registered
``previous.resolutionDate + 7 days +/- 2``. The published ``resolutionDate``
has equalled the registered window END since the week_2026-08-08 initial
claims cell, so each roll moved the window end by 9 days while DOL's release
moved by 7: +2 days of drift per week, 12 days by week_2026-09-26.

DOL's Office of Unemployment Insurance states the schedule this file pins:
the UI Weekly Claims news release is published every Thursday at 8:30am
Eastern, except when Thursday is a federal holiday, and it lists each
off-Thursday date (https://oui.doleta.gov/unemploy/claims_arch.asp, read
2026-09-20: one exception, Wednesday 2026-11-25).
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import register_targets  # noqa: E402

INITIAL = "us.dol.initial_claims.sa"
CONTINUED = "dol.eta.continued_claims.sa"
SLUGS = {INITIAL: "initial-claims-week-{}", CONTINUED: "continued-claims-week-{}"}
UNITS = {INITIAL: ("thousands", 0.001), CONTINUED: ("millions", 0.001)}
LAGS = {INITIAL: 5, CONTINUED: 12}


def weekly_target(series: str, week: str, previous_resolution_date: str | None) -> dict:
    unit, scale = UNITS[series]
    target = {
        "series": series,
        "period": f"week_{week}",
        "catalogSlug": SLUGS[series].format(week),
        "targetUnit": unit,
        "valueScale": scale,
    }
    if previous_resolution_date is not None:
        # The exact key set roll_docket.py copies from the published forecast.
        target["previousTarget"] = {
            "country": "US",
            "unit": unit,
            "dataPointId": f"{series}.week_previous",
            "resolutionDate": previous_resolution_date,
            "resolutionSource": "ALFRED graph CSV",
            "resolutionSourceUrl": "https://alfred.stlouisfed.org/graph/alfredgraph.csv",
            "period": "week_previous",
        }
    return target


def window_for(target: dict, registration_date: dt.date) -> dict[str, str]:
    contract = register_targets.build_contract(target, registration_date)
    return contract["sourceBinding"]["expectedReleaseWindow"]


@pytest.mark.parametrize(
    ("series", "week", "previous_resolution_date", "registration_date", "release_day"),
    [
        # The live 2026-09-20 registration: previous forecast resolutionDate
        # 2026-10-08 produced 2026-10-13..2026-10-17 for a 2026-10-01 print.
        (INITIAL, "2026-09-26", "2026-10-08", dt.date(2026, 9, 20), "2026-10-01"),
        # The live 2026-09-14 registration: 2026-09-30 produced
        # 2026-10-05..2026-10-09 for a 2026-10-01 print.
        (CONTINUED, "2026-09-19", "2026-09-30", dt.date(2026, 9, 14), "2026-10-01"),
    ],
)
def test_window_ignores_the_previous_forecast_resolution_date(
    series, week, previous_resolution_date, registration_date, release_day
) -> None:
    window = window_for(
        weekly_target(series, week, previous_resolution_date), registration_date
    )

    release = dt.date.fromisoformat(release_day)
    assert window == {
        "start": (release - dt.timedelta(days=2)).isoformat(),
        "end": (release + dt.timedelta(days=2)).isoformat(),
    }


@pytest.mark.parametrize("series", [INITIAL, CONTINUED])
def test_windows_do_not_drift_when_each_forecast_resolves_at_the_window_end(
    series,
) -> None:
    """Replay the live ratchet: resolutionDate := registered window end."""

    week = dt.date(2026, 8, 8)
    previous_resolution_date = None
    offsets = []
    for _ in range(12):
        registration_date = week - dt.timedelta(days=5)
        window = window_for(
            weekly_target(series, week.isoformat(), previous_resolution_date),
            registration_date,
        )
        release = week + dt.timedelta(days=LAGS[series])
        assert release.weekday() == 3
        offsets.append((dt.date.fromisoformat(window["start"]) - release).days)
        assert window["start"] <= release.isoformat() <= window["end"]
        previous_resolution_date = window["end"]
        week += dt.timedelta(days=7)

    assert offsets == [-2] * 12


def test_derivation_is_identical_with_and_without_a_previous_target() -> None:
    for series in (INITIAL, CONTINUED):
        seeded = window_for(
            weekly_target(series, "2030-01-05", None), dt.date(2030, 1, 6)
        )
        rolled = window_for(
            weekly_target(series, "2030-01-05", "2030-02-20"), dt.date(2030, 1, 6)
        )
        assert rolled == seeded


def test_dol_published_off_thursday_release_moves_the_window() -> None:
    # Thanksgiving 2026-11-26: DOL lists Wednesday 2026-11-25 for the release
    # carrying initial claims for week 2026-11-21 and continued claims for
    # week 2026-11-14.
    assert window_for(
        weekly_target(INITIAL, "2026-11-21", "2026-11-19"), dt.date(2026, 11, 15)
    ) == {"start": "2026-11-23", "end": "2026-11-27"}
    assert window_for(
        weekly_target(CONTINUED, "2026-11-14", "2026-11-19"), dt.date(2026, 11, 8)
    ) == {"start": "2026-11-23", "end": "2026-11-27"}


def test_unlisted_federal_holiday_thursday_fails_closed() -> None:
    # Veterans Day 2027-11-11 is a Thursday. DOL has not published the 2027
    # exception list, so the release day is unknown: refuse rather than guess.
    with pytest.raises(register_targets.RegistrationError, match="federal holiday"):
        window_for(weekly_target(INITIAL, "2027-11-06", None), dt.date(2027, 10, 31))
    # Thanksgiving is always a Thursday.
    with pytest.raises(register_targets.RegistrationError, match="federal holiday"):
        window_for(weekly_target(CONTINUED, "2027-11-13", None), dt.date(2027, 11, 7))


def test_reference_week_must_end_on_a_saturday() -> None:
    with pytest.raises(register_targets.RegistrationError, match="Saturday"):
        window_for(weekly_target(INITIAL, "2026-09-25", None), dt.date(2026, 9, 20))


def test_explicit_window_still_wins_so_registered_retries_stay_byte_identical() -> None:
    """rebuild_registered_target() replays a snapshot's stored window.

    The drifted registrations are immutable; a retry must reproduce them
    exactly rather than re-derive them under the corrected rule.
    """

    target = weekly_target(INITIAL, "2026-09-26", "2026-10-08")
    target["expectedReleaseWindow"] = {"start": "2026-10-13", "end": "2026-10-17"}
    assert window_for(target, dt.date(2026, 9, 20)) == {
        "start": "2026-10-13",
        "end": "2026-10-17",
    }


def registered_weekly_claims_targets() -> list[tuple[str, dict]]:
    rows = []
    for path in sorted((ROOT / "records" / "targets").glob("*.json")):
        for contract in json.loads(path.read_text()).get("targets", []):
            if contract.get("series") in LAGS:
                rows.append((path.name, contract))
    return rows


def window_is_on_schedule(contract: dict) -> bool:
    """The derived +/- 2-day window, or an exact window on the scheduled day.

    A reviewed seed or calendar path may register the exact official day
    (expectedReleaseDate), which is as correct as the derived window.
    """

    release = register_targets.weekly_claims_release_day(
        contract["series"], contract["period"]
    )
    window = contract["sourceBinding"]["expectedReleaseWindow"]
    derived = {
        "start": (release - dt.timedelta(days=2)).isoformat(),
        "end": (release + dt.timedelta(days=2)).isoformat(),
    }
    exact = {"start": release.isoformat(), "end": release.isoformat()}
    return window in (derived, exact)


def test_an_exact_scheduled_day_window_is_on_schedule() -> None:
    target = weekly_target(INITIAL, "2026-10-17", None)
    target["expectedReleaseDate"] = "2026-10-22"
    contract = register_targets.build_contract(target, dt.date(2026, 10, 12))
    assert contract["sourceBinding"]["expectedReleaseWindow"] == {
        "start": "2026-10-22",
        "end": "2026-10-22",
    }
    assert window_is_on_schedule(contract)
    late = weekly_target(INITIAL, "2026-10-17", None)
    late["expectedReleaseDate"] = "2026-10-23"
    assert not window_is_on_schedule(
        register_targets.build_contract(late, dt.date(2026, 10, 12))
    )


def test_registered_windows_outside_the_schedule_only_shrink() -> None:
    """Records are immutable, so the drifted population is frozen history.

    Any registration that joins it means the derivation regressed.
    """

    waiver = json.loads((ROOT / "waivers.json").read_text())["waivers"][
        "weekly_claims_windows_off_schedule"
    ]
    off_schedule = {
        contract["dataPointId"]
        for _name, contract in registered_weekly_claims_targets()
        if not window_is_on_schedule(contract)
    }

    joined = sorted(off_schedule - set(waiver["members"]))
    assert not joined, (
        "weekly claims registration(s) whose expectedReleaseWindow is not the "
        f"scheduled DOL release day +/- 2 days: {joined}. The window must "
        "derive from the reference week (register_targets."
        "weekly_claims_release_day), never from a previous forecast."
    )
    assert sorted(off_schedule) == sorted(waiver["members"]), (
        "records/targets is append-only, so the frozen off-schedule "
        "population cannot shrink either"
    )


# Invariants, executed for every input in a bounded domain rather than sampled.
# The domain is every Saturday from 2026 through 2030 for both series.
def every_saturday(start: dt.date, end: dt.date):
    day = start + dt.timedelta(days=(5 - start.weekday()) % 7)
    while day <= end:
        yield day
        day += dt.timedelta(days=7)


SATURDAYS = list(every_saturday(dt.date(2026, 1, 1), dt.date(2030, 12, 31)))


def scheduled_thursday(series: str, week: dt.date) -> dt.date:
    return week + dt.timedelta(days=LAGS[series])


@pytest.mark.parametrize("series", [INITIAL, CONTINUED])
def test_every_week_gets_a_centred_window_or_a_named_holiday_refusal(series) -> None:
    exceptions = register_targets.WEEKLY_CLAIMS_RELEASE_EXCEPTIONS
    derived = 0
    for week in SATURDAYS:
        thursday = scheduled_thursday(series, week)
        holiday = register_targets._thursday_federal_holiday(thursday)
        registration_date = week - dt.timedelta(days=5)
        target = weekly_target(series, week.isoformat(), None)
        if holiday and thursday.isoformat() not in exceptions:
            with pytest.raises(register_targets.RegistrationError, match=holiday):
                window_for(target, registration_date)
            continue
        window = window_for(target, registration_date)
        start = dt.date.fromisoformat(window["start"])
        end = dt.date.fromisoformat(window["end"])
        release = start + dt.timedelta(days=2)
        # Width: always the reviewed +/- 2 days.
        assert (end - start).days == 4
        # Center: DOL's Thursday, or exactly the day DOL lists instead.
        assert release.isoformat() == exceptions.get(
            thursday.isoformat(), thursday.isoformat()
        )
        # A print can never precede the end of its own reference week.
        assert release > week
        derived += 1
    # The holiday refusals are the exception, not the rule.
    assert derived >= len(SATURDAYS) - 5 * 3


@pytest.mark.parametrize("series", [INITIAL, CONTINUED])
def test_window_is_independent_of_any_previous_resolution_date(series) -> None:
    for week in SATURDAYS[:60]:
        if register_targets._thursday_federal_holiday(scheduled_thursday(series, week)):
            continue
        registration_date = week - dt.timedelta(days=5)
        seeded = window_for(
            weekly_target(series, week.isoformat(), None), registration_date
        )
        for offset in (-30, -1, 0, 1, 2, 9, 16, 365):
            previous = (week + dt.timedelta(days=offset)).isoformat()
            rolled = window_for(
                weekly_target(series, week.isoformat(), previous), registration_date
            )
            assert rolled == seeded, (week, previous)


def test_one_release_carries_initial_week_w_and_continued_week_w_minus_7() -> None:
    """Differential: the two series are two columns of the same DOL release."""

    for week in SATURDAYS[1:]:
        thursday = scheduled_thursday(INITIAL, week)
        if register_targets._thursday_federal_holiday(thursday) and (
            thursday.isoformat()
            not in register_targets.WEEKLY_CLAIMS_RELEASE_EXCEPTIONS
        ):
            continue
        assert register_targets.weekly_claims_release_day(
            INITIAL, f"week_{week.isoformat()}"
        ) == register_targets.weekly_claims_release_day(
            CONTINUED, f"week_{(week - dt.timedelta(days=7)).isoformat()}"
        )


# Differential against the source: the first ALFRED vintage holding each week
# in the Chronicle ledger, found 2026-10-12 by bisecting
# alfred.stlouisfed.org/graph/alfredgraph.csv?id={ICSA,CCSA}&vintage_date=...
# (the earliest vintage whose CSV holds the week; presence is monotone).
ALFRED_FIRST_VINTAGES = [
    (CONTINUED, "2026-06-27", "2026-07-09"),
    (CONTINUED, "2026-07-04", "2026-07-16"),
    (CONTINUED, "2026-07-11", "2026-07-23"),
    (CONTINUED, "2026-07-18", "2026-07-30"),
    (CONTINUED, "2026-07-25", "2026-08-06"),
    (CONTINUED, "2026-08-01", "2026-08-13"),
    (CONTINUED, "2026-08-08", "2026-08-20"),
    (CONTINUED, "2026-08-15", "2026-08-27"),
    (CONTINUED, "2026-08-22", "2026-09-03"),
    (CONTINUED, "2026-08-29", "2026-09-10"),
    (CONTINUED, "2026-09-05", "2026-09-17"),
    (CONTINUED, "2026-09-12", "2026-09-24"),
    (CONTINUED, "2026-09-19", "2026-10-01"),
    (INITIAL, "2026-06-13", "2026-06-18"),
    (INITIAL, "2026-06-20", "2026-06-25"),
    (INITIAL, "2026-07-04", "2026-07-09"),
    (INITIAL, "2026-07-11", "2026-07-16"),
    (INITIAL, "2026-07-18", "2026-07-23"),
    (INITIAL, "2026-07-25", "2026-07-30"),
    (INITIAL, "2026-08-01", "2026-08-06"),
    (INITIAL, "2026-08-08", "2026-08-13"),
    (INITIAL, "2026-08-15", "2026-08-20"),
    (INITIAL, "2026-08-22", "2026-08-27"),
    (INITIAL, "2026-08-29", "2026-09-03"),
    (INITIAL, "2026-09-05", "2026-09-10"),
    (INITIAL, "2026-09-12", "2026-09-17"),
    (INITIAL, "2026-09-19", "2026-09-24"),
]


@pytest.mark.parametrize(("series", "week", "first_vintage"), ALFRED_FIRST_VINTAGES)
def test_derived_release_day_is_alfreds_first_vintage(
    series, week, first_vintage
) -> None:
    assert (
        register_targets.weekly_claims_release_day(series, f"week_{week}").isoformat()
        == first_vintage
    )


def federal_holidays(year: int) -> dict[dt.date, str]:
    """Independent oracle: every 5 U.S.C. 6103 holiday in `year`, by rule."""

    def nth_weekday(month: int, weekday: int, n: int) -> dt.date:
        day = dt.date(year, month, 1)
        day += dt.timedelta(days=(weekday - day.weekday()) % 7)
        return day + dt.timedelta(weeks=n - 1)

    def last_weekday(month: int, weekday: int) -> dt.date:
        day = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
        return day - dt.timedelta(days=(day.weekday() - weekday) % 7)

    holidays = {
        dt.date(year, 1, 1): "New Year's Day",
        nth_weekday(1, 0, 3): "Birthday of Martin Luther King, Jr.",
        nth_weekday(2, 0, 3): "Washington's Birthday",
        last_weekday(5, 0): "Memorial Day",
        dt.date(year, 6, 19): "Juneteenth",
        dt.date(year, 7, 4): "Independence Day",
        nth_weekday(9, 0, 1): "Labor Day",
        nth_weekday(10, 0, 2): "Columbus Day",
        dt.date(year, 11, 11): "Veterans Day",
        nth_weekday(11, 3, 4): "Thanksgiving",
        dt.date(year, 12, 25): "Christmas Day",
    }
    if year % 4 == 1:  # the January after a presidential election
        holidays[dt.date(year, 1, 20)] = "Inauguration Day"
    return holidays


def test_holiday_helper_agrees_with_an_independent_oracle_on_every_thursday() -> None:
    """Differential: the helper flags exactly the oracle's Thursday holidays."""

    day = dt.date(2026, 1, 1)
    day += dt.timedelta(days=(3 - day.weekday()) % 7)
    flagged = 0
    while day.year <= 2060:
        expected = federal_holidays(day.year).get(day)
        assert register_targets._thursday_federal_holiday(day) == expected, day
        flagged += expected is not None
        day += dt.timedelta(days=7)
    # Five fixed-date holidays each fall on a Thursday about once in seven
    # years, plus 35 Thanksgivings and two Thursday Inauguration Days.
    assert flagged > 35 + 2


@pytest.mark.parametrize("series", [INITIAL, CONTINUED])
def test_a_thursday_inauguration_day_refuses_until_dol_lists_a_date(series) -> None:
    # 2033-01-20 is a Thursday Inauguration Day.
    week = dt.date(2033, 1, 20) - dt.timedelta(days=LAGS[series])
    with pytest.raises(register_targets.RegistrationError, match="Inauguration Day"):
        window_for(
            weekly_target(series, week.isoformat(), None), week - dt.timedelta(days=5)
        )
