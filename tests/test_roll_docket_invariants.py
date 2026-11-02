"""What the docket roller must hold on every docket date.

The October 2026 rolls failed on every run: cap slots went to series the
registrar could not build, the calendar had run out for most monthly series,
and weekly claims sat on a week whose window had already opened. These tests
run the real roller, the real resolver gate and the real registrar over the
committed docket, so a date or walker change that breaks one of them shows up
here rather than on a Friday roll.
"""

from __future__ import annotations

import calendar
import collections
import datetime as dt
import json
import pathlib
import re
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import register_targets  # noqa: E402
import roll_docket  # noqa: E402
from register_targets import (  # noqa: E402
    SERIES_BINDINGS,
    WEEKLY_CLAIMS_WINDOW_HALF_WIDTH_DAYS,
    weekly_claims_release_day,
)

REGISTRY = json.loads((ROOT / "scripts" / "docket_series.json").read_text())["series"]
ENTRIES = {entry["series"]: entry for entry in REGISTRY}
DATED = [
    entry
    for entry in REGISTRY
    if isinstance(entry.get("releaseDates"), dict) and entry["releaseDates"]
]
# These calendar pages list several releases, so series on one page can print
# on different days for one period. Every other page lists a single release.
MULTI_RELEASE_CALENDARS = frozenset(
    {
        "https://www.bea.gov/news/schedule",
        "https://www.census.gov/construction/soc/schedule.html",
        "https://www.census.gov/economic-indicators/calendar-listview-2026.html",
        "https://www150.statcan.gc.ca/n1/release-diffusion/2026-eng.pdf",
    }
)
# The three series the 2026-10 rolls selected, with the September contracts the
# live log held for them. No adapter or calendar serves them, so the next period
# has no official window.
OCTOBER_WEDGE = {
    "nbb.business_barometer.overall": (
        "belgium-nbb-business-barometer-september-2026",
        {
            "country": "BE",
            "unit": "index_points",
            "dataPointId": "nbb.business_barometer.overall.2026-09.first_print",
            "resolutionDate": "2026-09-24",
            "resolutionSourceUrl": (
                "https://www.nbb.be/en/statistics/business-surveys/business-survey"
            ),
        },
    ),
    "nbb.consumer_confidence.indicator": (
        "belgium-consumer-confidence-september-2026",
        {
            "country": "BE",
            "unit": "index_points",
            "dataPointId": "nbb.consumer_confidence.indicator.2026-09.first_print",
            "resolutionDate": "2026-09-25",
            "resolutionSourceUrl": (
                "https://www.nbb.be/en/statistics/business-surveys/consumer-survey"
            ),
        },
    ),
    "statjp.cpi.tokyo_all_items_yoy": (
        "japan-tokyo-cpi-annual-rate-september-2026-prelim",
        {
            "country": "JP",
            "unit": "percent",
            "dataPointId": (
                "statjp.cpi.tokyo_all_items_annual_rate.september_2026.preliminary"
            ),
            "resolutionDate": "2026-10-02",
            "resolutionSourceUrl": (
                "https://www.stat.go.jp/data/cpi/sokuhou/tsuki/index-t.html"
            ),
        },
    ),
}
OCTOBER_SLUGS = {slug for slug, _ in OCTOBER_WEDGE.values()}
OCTOBER_FORECASTS = {slug: contract for slug, contract in OCTOBER_WEDGE.values()}


@pytest.fixture
def resolver_admits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        roll_docket, "execution_plan_refusal", lambda registration: None
    )


def fixed_date(day: dt.date) -> type[dt.date]:
    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> dt.date:
            return cls(day.year, day.month, day.day)

    return FixedDate


def roll(
    monkeypatch: pytest.MonkeyPatch,
    workdir: pathlib.Path,
    today: dt.date,
    entries: list[dict],
    published: set[str],
    *args: str,
    forecasts: dict[str, dict] | None = None,
) -> tuple[int, list[dict]]:
    registry = workdir / "docket_series.json"
    registry.write_text(json.dumps({"series": entries}))
    output = workdir / "targets.json"
    output.unlink(missing_ok=True)
    monkeypatch.setattr(roll_docket, "REGISTRY", registry)
    monkeypatch.setattr(roll_docket, "RECORDS", workdir / "records")
    monkeypatch.setattr(roll_docket.dt, "date", fixed_date(today))
    monkeypatch.setattr(
        roll_docket, "live_catalog", lambda: (published, forecasts or {}, set())
    )
    monkeypatch.setattr(sys, "argv", ["roll_docket.py", "--out", str(output), *args])
    exit_code = roll_docket.main()
    targets = json.loads(output.read_text())["targets"] if output.exists() else []
    return exit_code, targets


def fixture_entry(series: str, slug: str, releases: dict[str, str]) -> dict:
    return {
        "series": series,
        "cadence": "monthly",
        "slug": slug,
        "releaseCalendarUrl": "https://agency.example/release-calendar",
        "releaseDates": releases,
        "extras": {
            "targetUnit": "percent",
            "sourceBinding": {
                "adapter": "alfred-fred",
                "sourceUrl": "https://api.stlouisfed.org/fred/series/observations",
                "sourceSeriesId": "FIXTURE",
                "field": "FIXTURE",
                "table": "Fixture release",
                "transform": {"operation": "identity", "factor": 1},
                "releasePolicy": "first_print",
            },
        },
    }


@pytest.mark.parametrize(
    "today",
    [dt.date(2026, 10, 23), dt.date(2026, 10, 26), dt.date(2026, 10, 30)],
)
def test_the_october_selection_now_exits_clean_with_the_reason_on_the_log(
    today: dt.date,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, targets = roll(
        monkeypatch,
        tmp_path,
        today,
        [ENTRIES[series] for series in OCTOBER_WEDGE],
        OCTOBER_SLUGS,
        forecasts=OCTOBER_FORECASTS,
    )

    assert exit_code == 0
    assert targets == []
    out = capsys.readouterr().out
    for slug in (
        "belgium-nbb-business-barometer-october-2026",
        "belgium-consumer-confidence-october-2026",
        "japan-tokyo-cpi-annual-rate-october-2026-prelim",
    ):
        assert f"skip {slug}: no executable resolution plan" in out
    # The registrar's reason on each of those runs, now on the roller's log.
    assert "expected release window must start after the registration date" in out


def test_the_registrar_still_refuses_a_selection_of_only_unbindable_targets(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The raise stays: since the roller drops these first, it now means the
    # roller and the registrar disagree, which a green roll must not hide.
    generated = tmp_path / "ledger-targets.generated.ts"
    generated.write_text(
        "export const GENERATED_FORECAST_TARGETS = [\n"
        "] satisfies TargetRegisteredLedgerEntry[];\n"
    )
    monkeypatch.setattr(register_targets, "ROOT", tmp_path)
    monkeypatch.setattr(register_targets, "GENERATED_TARGETS", generated)
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "series": "nbb.business_barometer.overall",
                        "period": "2026-10",
                        "catalogSlug": "belgium-nbb-business-barometer-october-2026",
                        **ENTRIES["nbb.business_barometer.overall"]["extras"],
                    }
                ]
            }
        )
    )

    with pytest.raises(
        register_targets.RegistrationError, match="no bindable targets in this roll"
    ):
        register_targets.register(
            targets_path, dt.date(2026, 10, 30), "2026-10-30T20:57:52Z", True
        )


def test_an_unbuildable_series_takes_no_cap_slot(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payrolls = ENTRIES["bls.ces.nonfarm_payrolls.change"]
    published = {
        *OCTOBER_SLUGS,
        roll_docket.format_slug(payrolls["slug"], "2026-10", payrolls["cadence"]),
    }

    exit_code, targets = roll(
        monkeypatch,
        tmp_path,
        dt.date(2026, 11, 2),
        [*(ENTRIES[series] for series in OCTOBER_WEDGE), payrolls],
        published,
        "--max-targets",
        "1",
        forecasts=OCTOBER_FORECASTS,
    )

    assert exit_code == 0
    assert [target["catalogSlug"] for target in targets] == [
        "nonfarm-payrolls-november-2026"
    ]


@pytest.mark.usefixtures("resolver_admits")
def test_the_cap_keeps_the_nearest_print_not_the_lowest_period_string(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A quarterly period string sorts before any monthly string of its year,
    # and a slow monthly release sorts before a fast one a month later, so
    # ordering by period can spend the cap on the print furthest away.
    slow = fixture_entry(
        "fixture.slow", "slow-{month}-{year}", {"2026-09": "2026-12-20"}
    )
    fast = fixture_entry(
        "fixture.fast", "fast-{month}-{year}", {"2026-10": "2026-11-10"}
    )

    exit_code, targets = roll(
        monkeypatch,
        tmp_path,
        dt.date(2026, 11, 2),
        [slow, fast],
        {"slow-august-2026", "fast-september-2026"},
        "--max-targets",
        "1",
    )

    assert exit_code == 0
    assert [target["catalogSlug"] for target in targets] == ["fast-october-2026"]


def test_weekly_claims_step_past_a_week_whose_window_opened(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry = ENTRIES["us.dol.initial_claims.sa"]
    published = {
        roll_docket.format_slug(entry["slug"], "week_2026-09-19", entry["cadence"])
    }

    exit_code, targets = roll(
        monkeypatch, tmp_path, dt.date(2026, 11, 2), [entry], published
    )

    assert exit_code == 0
    [target] = targets
    # The print for week 2026-10-31 comes on 2026-11-05, and its window opens
    # on 2026-11-03: the first one still ahead of the docket date.
    assert target["period"] == "week_2026-10-31"
    assert "its release window opens 2026-10-27" in capsys.readouterr().err


def test_weekly_claims_keep_thanksgivings_listed_release_day() -> None:
    entry = ENTRIES["us.dol.initial_claims.sa"]
    assert weekly_claims_release_day(entry["series"], "week_2026-11-21") == dt.date(
        2026, 11, 25
    )
    assert (
        roll_docket.advance_past_opened_weekly_claims_windows(
            entry, "week_2026-11-21", dt.date(2026, 11, 22)
        )
        == "week_2026-11-21"
    )
    # The window opens on the 23rd, so that day's docket moves to the next week.
    assert (
        roll_docket.advance_past_opened_weekly_claims_windows(
            entry, "week_2026-11-21", dt.date(2026, 11, 23)
        )
        == "week_2026-11-28"
    )


def test_weekly_claims_skip_an_unlisted_holiday_with_a_warning(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(register_targets, "WEEKLY_CLAIMS_RELEASE_EXCEPTIONS", {})
    entry = ENTRIES["us.dol.initial_claims.sa"]
    assert (
        roll_docket.advance_past_opened_weekly_claims_windows(
            entry, "week_2026-11-21", dt.date(2026, 11, 20)
        )
        is None
    )
    assert "federal holiday" in capsys.readouterr().err


CLAIMS_SERIES = st.sampled_from(sorted(SERIES_BINDINGS))
# Saturdays in the range the holiday table covers.
CLAIMS_WEEKS = st.integers(0, 52).map(
    lambda weeks: dt.date(2026, 9, 5) + dt.timedelta(days=7 * weeks)
)
WALKER_DATES = st.dates(dt.date(2026, 9, 1), dt.date(2027, 9, 30))


def _week(day: dt.date) -> str:
    return f"week_{day.isoformat()}"


def _window_start(series: str, day: dt.date) -> dt.date:
    return weekly_claims_release_day(series, _week(day)) - dt.timedelta(
        days=WEEKLY_CLAIMS_WINDOW_HALF_WIDTH_DAYS
    )


@settings(max_examples=300, deadline=None)
@given(CLAIMS_SERIES, CLAIMS_WEEKS, WALKER_DATES)
def test_claims_walker_returns_the_first_week_with_an_unopened_window(
    series: str, start: dt.date, today: dt.date
) -> None:
    entry = ENTRIES[series]
    result = roll_docket.advance_past_opened_weekly_claims_windows(
        entry, _week(start), today
    )
    if result is None:
        # Only the horizon ends the walk here: every week until it has opened.
        day = start
        while roll_docket.not_too_far_ahead(_week(day), "weekly", today):
            assert _window_start(series, day) <= today
            day += dt.timedelta(days=7)
        assert day > today + dt.timedelta(days=7)
        return
    chosen = dt.date.fromisoformat(result.removeprefix("week_"))
    assert chosen.weekday() == 5
    assert chosen >= start
    assert _window_start(series, chosen) > today
    if chosen != start:
        assert roll_docket.not_too_far_ahead(result, "weekly", today)
    day = start
    while day < chosen:
        assert _window_start(series, day) <= today
        day += dt.timedelta(days=7)


@settings(max_examples=300, deadline=None)
@given(CLAIMS_SERIES, CLAIMS_WEEKS, WALKER_DATES, WALKER_DATES)
def test_claims_walker_never_moves_back_as_the_docket_date_moves_on(
    series: str, start: dt.date, first: dt.date, second: dt.date
) -> None:
    earlier, later = sorted((first, second))
    entry = ENTRIES[series]
    before = roll_docket.advance_past_opened_weekly_claims_windows(
        entry, _week(start), earlier
    )
    after = roll_docket.advance_past_opened_weekly_claims_windows(
        entry, _week(start), later
    )
    if before is not None and after is not None:
        assert after >= before


@settings(max_examples=400, deadline=None)
@given(
    st.sampled_from(DATED),
    st.integers(0, 30),
    st.dates(dt.date(2026, 6, 1), dt.date(2027, 8, 31)),
)
def test_calendar_walker_never_returns_a_period_whose_print_is_known(
    entry: dict, offset: int, today: dt.date
) -> None:
    periods = sorted(entry["releaseDates"])
    start = periods[min(offset, len(periods) - 1)]
    result = roll_docket.advance_past_released_native_periods(entry, start, today)
    if result is None:
        return
    gated = (entry.get("extras") or {}).get("sourceBinding", {}).get(
        "adapter"
    ) in roll_docket.CALENDAR_GATED_SOURCE_ADAPTERS
    print_date = entry["releaseDates"].get(result)
    if gated and print_date is not None:
        assert dt.date.fromisoformat(print_date) > today


def _published_catalog(
    month: str, quarter: str, week: dt.date, unpublished: frozenset[str]
) -> set[str]:
    cursors = {"monthly": month, "quarterly": quarter, "weekly": _week(week)}
    return {
        roll_docket.format_slug(
            entry["slug"], cursors[entry["cadence"]], entry["cadence"]
        )
        for entry in REGISTRY
        if entry["cadence"] in cursors
        and entry["series"] not in unpublished
        and "conditionalPair" not in entry
    }


@settings(max_examples=25, deadline=None)
@given(
    today=st.dates(dt.date(2026, 10, 19), dt.date(2027, 3, 31)),
    month=st.sampled_from(["2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]),
    quarter=st.sampled_from(["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]),
    weeks=st.integers(0, 12),
    unpublished=st.frozensets(st.sampled_from(sorted(ENTRIES)), max_size=8),
    cap=st.sampled_from([1, 3, 10, 200]),
)
def test_the_registrar_accepts_every_target_the_roller_selects(
    today: dt.date,
    month: str,
    quarter: str,
    weeks: int,
    unpublished: frozenset[str],
    cap: int,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    # A differential: the roller and the registrar judge one contract in two
    # places. Any target the roller selects and the registrar prunes can bring
    # back a roll that fails on "no bindable targets" or spends a cap slot on
    # nothing.
    workdir = tmp_path_factory.mktemp("roll")
    published = _published_catalog(
        month,
        quarter,
        dt.date(2026, 9, 5) + dt.timedelta(days=7 * weeks),
        unpublished,
    )
    with pytest.MonkeyPatch.context() as patch:
        exit_code, targets = roll(
            patch,
            workdir,
            today,
            REGISTRY,
            published,
            "--max-targets",
            str(cap),
        )
        assert exit_code == 0
        assert len(targets) <= cap
        assert not {target["catalogSlug"] for target in targets} & published

        expired = roll_docket.expired_unforecast_registrations(ROOT)
        registered = frozenset(
            roll_docket.load_registered_targets(ROOT / "records" / "targets")
        )
        for target in targets:
            contract = register_targets.build_contract(target, today)
            assert contract["dataPointId"] not in expired
            assert contract["dataPointId"] not in registered
            window = contract["sourceBinding"]["expectedReleaseWindow"]
            assert dt.date.fromisoformat(window["start"]) > today
            entry = ENTRIES[target["series"]]
            if isinstance(entry.get("releaseDates"), dict):
                register_targets.validate_committed_calendar_contract(
                    contract, target, entry
                )

        generated = workdir / "ledger-targets.generated.ts"
        generated.write_text(
            'import type { TargetRegisteredLedgerEntry } from "./ledger-targets";\n'
            "export const GENERATED_FORECAST_TARGETS = [\n"
            "] satisfies TargetRegisteredLedgerEntry[];\n"
        )
        patch.setattr(register_targets, "ROOT", workdir)
        patch.setattr(register_targets, "GENERATED_TARGETS", generated)
        targets_path = workdir / "targets.json"
        registrations = register_targets.register(
            targets_path, today, f"{today.isoformat()}T16:30:00Z", True
        )
    assert sorted(row["contract"]["catalogSlug"] for row in registrations) == sorted(
        target["catalogSlug"] for target in targets
    )


def _registered_contracts() -> dict[str, dict]:
    """The contract each docket series last registered, by catalog slug."""

    latest: dict[str, dict] = {}
    for path in sorted((ROOT / "records" / "targets").glob("*.json")):
        for contract in json.loads(path.read_text()).get("targets", []):
            entry = ENTRIES.get(contract.get("series"))
            if entry is None or "catalogSlug" not in contract:
                continue
            key = roll_docket.period_key(str(contract.get("period")), entry["cadence"])
            if key is None:
                continue
            current = latest.get(entry["series"])
            current_key = (
                roll_docket.period_key(str(current["period"]), entry["cadence"])
                if current
                else None
            )
            if current_key is None or key > current_key:
                latest[entry["series"]] = contract
    return {contract["catalogSlug"]: contract for contract in latest.values()}


REGISTERED_CONTRACTS = _registered_contracts()


@settings(max_examples=25, deadline=None)
@given(
    today=st.dates(dt.date(2026, 10, 19), dt.date(2027, 3, 31)),
    cap=st.sampled_from([3, 10, 200]),
)
def test_the_registrar_accepts_successors_of_the_registered_contracts(
    today: dt.date, cap: int, tmp_path_factory: pytest.TempPathFactory
) -> None:
    # The same differential with real previous contracts on the cursor, so the
    # registrar's inherited-binding and previous-target checks run too.
    workdir = tmp_path_factory.mktemp("roll")
    with pytest.MonkeyPatch.context() as patch:
        exit_code, targets = roll(
            patch,
            workdir,
            today,
            REGISTRY,
            set(REGISTERED_CONTRACTS),
            "--max-targets",
            str(cap),
            forecasts=REGISTERED_CONTRACTS,
        )
        assert exit_code == 0
        assert len(targets) <= cap
        generated = workdir / "ledger-targets.generated.ts"
        generated.write_text(
            'import type { TargetRegisteredLedgerEntry } from "./ledger-targets";\n'
            "export const GENERATED_FORECAST_TARGETS = [\n"
            "] satisfies TargetRegisteredLedgerEntry[];\n"
        )
        patch.setattr(register_targets, "ROOT", workdir)
        patch.setattr(register_targets, "GENERATED_TARGETS", generated)
        registrations = register_targets.register(
            workdir / "targets.json", today, f"{today.isoformat()}T16:30:00Z", True
        )
    assert sorted(row["contract"]["catalogSlug"] for row in registrations) == sorted(
        target["catalogSlug"] for target in targets
    )


def _period_end(period: str, cadence: str) -> dt.date:
    if cadence == "annual":
        return dt.date(int(period), 12, 31)
    if cadence == "quarterly":
        year, quarter = period.split("-Q")
        month = int(quarter) * 3
        return dt.date(int(year), month, calendar.monthrange(int(year), month)[1])
    year, month = map(int, period.split("-"))
    return dt.date(year, month, calendar.monthrange(year, month)[1])


@pytest.mark.parametrize("entry", DATED, ids=lambda entry: entry["series"])
def test_a_dated_entry_holds_a_well_formed_calendar(entry: dict) -> None:
    assert str(entry.get("releaseCalendarUrl", "")).startswith("https://")
    previous: dt.date | None = None
    for period in sorted(entry["releaseDates"]):
        assert roll_docket.period_key(period, entry["cadence"]) is not None, period
        release = dt.date.fromisoformat(entry["releaseDates"][period])
        assert release.isoformat() == entry["releaseDates"][period]
        # A flash estimate can print on the last day of its reference month.
        assert release >= _period_end(period, entry["cadence"]), period
        if previous is not None:
            assert release > previous, period
        previous = release


def test_series_on_one_release_calendar_agree_on_every_shared_period() -> None:
    by_calendar: dict[str, dict[str, set[str]]] = collections.defaultdict(
        lambda: collections.defaultdict(set)
    )
    for entry in DATED:
        url = entry["releaseCalendarUrl"]
        if url in MULTI_RELEASE_CALENDARS:
            continue
        for period, release in entry["releaseDates"].items():
            by_calendar[url][period].add(release)
    disagreements = {
        (url, period): sorted(releases)
        for url, periods in by_calendar.items()
        for period, releases in periods.items()
        if len(releases) > 1
    }
    assert disagreements == {}


def test_the_census_housing_series_share_their_calendar_column() -> None:
    starts, permits, completions = (
        ENTRIES[series]["releaseDates"]
        for series in (
            "census.housing_starts.saar",
            "census.housing.permits_saar",
            "census.housing.completions_saar",
        )
    )
    for period in starts.keys() & permits.keys() & completions.keys():
        assert starts[period] == permits[period] == completions[period], period


def test_every_multi_release_exemption_still_earns_its_place() -> None:
    # An exemption with one series, or with no disagreement, would only hide a
    # typo from the agreement test above.
    for url in MULTI_RELEASE_CALENDARS:
        rows = [entry for entry in DATED if entry["releaseCalendarUrl"] == url]
        periods: dict[str, set[str]] = collections.defaultdict(set)
        for entry in rows:
            for period, release in entry["releaseDates"].items():
                periods[period].add(release)
        assert len(rows) == 1 or any(len(dates) > 1 for dates in periods.values()), url


# The last period each family's calendar may reach before the anchors must be
# re-verified: January data brings the February CPI seasonal revision and the
# CES benchmark, and December data brings the year-end CPS revision.
BLS_API_CALENDAR_LIMITS = {
    "bls.cpi.": "2026-12",
    "bls.ces.": "2026-12",
    "bls.cps.": "2026-11",
}


@pytest.mark.parametrize(
    "entry",
    [
        entry
        for entry in DATED
        if (entry.get("extras") or {}).get("sourceBinding", {}).get("adapter")
        == "bls-api"
        and entry["series"].startswith(tuple(BLS_API_CALENDAR_LIMITS))
    ],
    ids=lambda entry: entry["series"],
)
def test_no_bls_api_calendar_crosses_an_annual_revision(entry: dict) -> None:
    # A latest_month print cannot be recovered once the next release lands, so
    # bls-api series bind their anchors. docs/anchor-verifications.md requires
    # re-verifying those anchors in the change that extends a calendar across
    # the series' annual revision. Move a limit here only in that change.
    limit = next(
        limit
        for prefix, limit in BLS_API_CALENDAR_LIMITS.items()
        if entry["series"].startswith(prefix)
    )
    assert max(entry["releaseDates"]) <= limit


def test_the_calendar_url_on_every_dated_entry_is_not_a_single_month_page() -> None:
    # A page for one month goes stale on the first date past it, as the G.19
    # entries' 2026-august.htm did.
    for entry in DATED:
        assert not re.search(
            r"/20\d\d-[a-z]+\.htm$", entry["releaseCalendarUrl"]
        ), entry["series"]
