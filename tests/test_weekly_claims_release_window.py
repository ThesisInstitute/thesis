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


def test_registered_windows_outside_the_schedule_only_shrink() -> None:
    """Records are immutable, so the drifted population is frozen history.

    Any registration that joins it means the derivation regressed.
    """

    waiver = json.loads((ROOT / "waivers.json").read_text())["waivers"][
        "weekly_claims_windows_off_schedule"
    ]
    off_schedule = set()
    for _name, contract in registered_weekly_claims_targets():
        release = register_targets.weekly_claims_release_day(
            contract["series"], contract["period"]
        )
        expected = {
            "start": (release - dt.timedelta(days=2)).isoformat(),
            "end": (release + dt.timedelta(days=2)).isoformat(),
        }
        if contract["sourceBinding"]["expectedReleaseWindow"] != expected:
            off_schedule.add(contract["dataPointId"])

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
