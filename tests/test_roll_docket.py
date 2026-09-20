from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import register_targets  # noqa: E402
import roll_docket  # noqa: E402
from adopt_proven_series import cadence_of, slug_template  # noqa: E402
from register_targets import (  # noqa: E402
    RegistrationError,
    build_contract,
    validate_native_calendar_contract,
)
from roll_docket import (  # noqa: E402
    OFFICIAL_CALENDAR_ADAPTERS,
    advance_past_released_native_periods,
    bounded_annual_first_print_seed_target,
    latest_published_period,
    next_roll_period,
    not_too_far_ahead,
    recurring_seed_target,
    snapshot_seed_target,
    step_period,
    target_extras_for_period,
    template_regex,
)


@pytest.fixture
def resolver_admits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the resolver's verdict for tests that use a fictional series.

    No resolver leg executes a fixture series, so the execution-plan gate
    would refuse it before the mechanics under test run. The gate is tested
    against the real resolver in tests/test_execution_plan_gate.py.
    """

    monkeypatch.setattr(
        roll_docket, "execution_plan_refusal", lambda registration: None
    )


def registry_entry(cadence: str, slug: str) -> dict[str, str]:
    return {"series": "fixture.series", "cadence": cadence, "slug": slug}


def recurring_seed_entry() -> dict:
    return {
        "series": "fixture.series",
        "cadence": "monthly",
        "slug": "fixture-{month}-{year}",
        "seedPeriod": "2026-07",
        "releaseCalendarUrl": "https://agency.example/release-calendar",
        "releaseDates": {"2026-07": "2026-08-20"},
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


def configure_roll_exclusion_state(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    expired_ids: list[str],
) -> None:
    repo_root = tmp_path / "repo"
    expired_path = (
        repo_root / "site" / "src" / "data" / "expired-unforecast-registrations.ts"
    )
    expired_path.parent.mkdir(parents=True)
    entries = "".join(f'  "{data_point_id}",\n' for data_point_id in expired_ids)
    expired_path.write_text(
        f"export const EXPIRED_UNFORECAST_REGISTRATIONS = [\n{entries}] as const;\n"
    )
    target_registrations = repo_root / "records" / "targets"
    target_registrations.mkdir(parents=True)
    monkeypatch.setattr(roll_docket, "ROOT", repo_root)
    monkeypatch.setattr(
        roll_docket,
        "TARGET_REGISTRATIONS",
        target_registrations,
    )


def test_recurring_seed_is_admitted_with_an_exact_registration_window() -> None:
    entry = recurring_seed_entry()

    target = recurring_seed_target(entry, set(), dt.date(2026, 7, 25))

    assert target == {
        "series": "fixture.series",
        "period": "2026-07",
        "seedPeriod": "2026-07",
        "catalogSlug": "fixture-july-2026",
        **entry["extras"],
        "expectedReleaseDate": "2026-08-20",
        "releaseCalendarUrl": "https://agency.example/release-calendar",
    }
    contract = register_targets.build_contract(target, dt.date(2026, 7, 25))
    assert contract["sourceBinding"]["expectedReleaseWindow"] == {
        "start": "2026-08-20",
        "end": "2026-08-20",
    }
    assert contract["seedPeriod"] == "2026-07"


def test_recurring_seed_never_reappears_after_publication() -> None:
    entry = recurring_seed_entry()
    slug = "fixture-july-2026"

    assert (
        recurring_seed_target(
            entry,
            {slug},
            dt.date(2026, 7, 25),
        )
        is None
    )
    assert next_roll_period(
        entry,
        {slug},
        set(),
        dt.date(2026, 8, 25),
    ) == ("2026-08", slug)


@pytest.mark.parametrize(
    ("mutation", "warning"),
    [
        ("malformed-period", "requires a canonical monthly seedPeriod"),
        ("future-period", "period is outside the normal roll horizon"),
        ("missing-date", "requires an explicit ISO releaseDates"),
        ("past-date", "is not after docket date"),
        ("far-date", "outside the 75-day roll horizon"),
        ("missing-calendar", "requires an HTTPS releaseCalendarUrl"),
        ("malformed-calendar", "requires an HTTPS releaseCalendarUrl"),
        ("positional-slug", "malformed recurring slug template"),
    ],
)
def test_recurring_seed_refuses_unreviewable_release_metadata(
    mutation: str,
    warning: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry = recurring_seed_entry()
    if mutation == "malformed-period":
        entry["seedPeriod"] = "2026-7"
    elif mutation == "future-period":
        entry["seedPeriod"] = "2026-08"
        entry["releaseDates"] = {"2026-08": "2026-08-20"}
    elif mutation == "missing-date":
        entry["releaseDates"] = {}
    elif mutation == "past-date":
        entry["releaseDates"]["2026-07"] = "2026-07-25"
    elif mutation == "far-date":
        entry["releaseDates"]["2026-07"] = "2026-10-09"
    elif mutation == "missing-calendar":
        entry.pop("releaseCalendarUrl")
    elif mutation == "malformed-calendar":
        entry["releaseCalendarUrl"] = "https://["
    else:
        entry["slug"] = "fixture-{}"

    assert recurring_seed_target(entry, set(), dt.date(2026, 7, 25)) is None
    assert warning in capsys.readouterr().err


def test_recurring_seed_refuses_an_existing_catalog_slug() -> None:
    entry = recurring_seed_entry()

    assert (
        recurring_seed_target(
            entry,
            {"fixture-july-2026"},
            dt.date(2026, 7, 25),
        )
        is None
    )


@pytest.mark.parametrize(
    ("cadence", "slug", "period"),
    [
        ("weekly", "fixture-{period}", "week_2026-7-25"),
        ("quarterly", "fixture-q{quarter}-{year}", "2026-q2"),
    ],
)
def test_recurring_seed_requires_canonical_period_spelling(
    cadence: str,
    slug: str,
    period: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry = recurring_seed_entry()
    entry.update(
        {
            "cadence": cadence,
            "slug": slug,
            "seedPeriod": period,
            "releaseDates": {period: "2026-08-20"},
        }
    )

    assert recurring_seed_target(entry, set(), dt.date(2026, 7, 25)) is None
    assert f"requires a canonical {cadence} seedPeriod" in capsys.readouterr().err


def test_real_recurring_seeds_are_reviewable_and_register_exact_dates() -> None:
    registry = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entries = [
        entry
        for entry in registry["series"]
        if entry.get("seedPeriod")
        and (entry.get("extras") or {}).get("resolutionDateBasis") != "resolve-by-bound"
    ]

    assert len(entries) == 25
    undated = {
        entry["series"]
        for entry in entries
        if entry["seedPeriod"] not in entry.get("releaseDates", {})
    }
    assert undated == {"bls.qcew.child_day_care_services.annual_avg_employment"}
    for entry in entries:
        # Evaluate each seed the day before its own pinned release: valid
        # whenever the registry is re-seeded (a fixed review date broke on
        # the 2026-07-31 ECI Q3 re-seed — release outside the roll horizon
        # from a frozen 2026-07-25; data-state-literal disease #8).
        period = entry["seedPeriod"]
        # A calendar-gated admission may intentionally wait for the agency
        # to date its next annual release. That is reviewable but not yet a
        # selectable seed.
        if period not in entry.get("releaseDates", {}):
            assert entry["series"] in undated
            assert entry["cadence"] == "annual"
            assert entry["seedPeriod"] == "2026"
            assert entry["releaseDates"] == {"2025": "2026-06-02"}
            assert entry["extras"]["sourceBinding"]["adapter"] == "bls-qcew"
            assert recurring_seed_target(entry, set(), dt.date.today()) is None
            continue
        docket_day = dt.date.fromisoformat(
            entry["releaseDates"][period]
        ) - dt.timedelta(days=1)
        target = recurring_seed_target(entry, set(), docket_day)
        assert target is not None
        assert target["period"] == period
        assert target["expectedReleaseDate"] == entry["releaseDates"][period]
        assert target["releaseCalendarUrl"] == entry["releaseCalendarUrl"]

        contract = register_targets.build_contract(
            target,
            docket_day,
        )
        assert contract["sourceBinding"]["expectedReleaseWindow"] == {
            "start": entry["releaseDates"][period],
            "end": entry["releaseDates"][period],
        }
        assert contract["seedPeriod"] == period


def test_wave1_pnfi_registry_pins_the_reviewed_bea_release() -> None:
    registry = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = next(
        item
        for item in registry["series"]
        if item["series"] == "bea.private_nonresidential_fixed_investment"
    )

    assert entry["seedPeriod"] == "2026-Q3"
    assert entry["releaseDates"] == {"2026-Q3": "2026-10-29"}
    assert entry["releaseCalendarUrl"] == "https://www.bea.gov/news/schedule"
    # The seed becomes selectable on the first day inside the 75-day horizon.
    target = recurring_seed_target(entry, set(), dt.date(2026, 8, 15))
    assert target is not None
    assert target["expectedReleaseDate"] == "2026-10-29"


def test_wave1_bea_rd_registry_pins_the_reviewed_bea_release() -> None:
    registry = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = next(
        item
        for item in registry["series"]
        if item["series"] == "bea.research_and_development_fixed_investment"
    )

    assert entry["seedPeriod"] == "2026-Q3"
    assert entry["releaseDates"] == {"2026-Q3": "2026-10-29"}
    assert entry["releaseCalendarUrl"] == "https://www.bea.gov/news/schedule"
    # The seed becomes selectable on the first day inside the 75-day horizon.
    target = recurring_seed_target(entry, set(), dt.date(2026, 8, 15))
    assert target is not None
    assert target["expectedReleaseDate"] == "2026-10-29"


def test_waveb_bea_ita_registry_pins_the_reviewed_release_and_anchor() -> None:
    registry = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = next(
        item
        for item in registry["series"]
        if item["series"] == "bea.ita.personal_transfer_payments"
    )

    assert entry["seedPeriod"] == "2026-Q2"
    assert entry["releaseDates"] == {"2026-Q2": "2026-09-24"}
    assert entry["releaseCalendarUrl"] == "https://www.bea.gov/news/schedule"
    assert entry["extras"]["anchors"] == {"2026-Q1": 18511}
    assert "resolutionDate" not in entry["extras"]
    target = recurring_seed_target(entry, set(), dt.date(2026, 8, 12))
    assert target is not None
    assert target["expectedReleaseDate"] == "2026-09-24"


def bounded_annual_seed_entry() -> dict:
    return {
        "series": "irs.soi.credit_30d.total_claims",
        "cadence": "annual",
        "period": "2027",
        "seedPeriod": "2027",
        "slug": "clean-vehicle-credit-total-claims-ty{period}",
        "extras": {
            "targetUnit": "count",
            "valueScale": 1,
            "resolutionDate": "2030-12-31",
            "resolutionDateBasis": "resolve-by-bound",
            "expectedReleaseWindow": {
                "start": "2029-01-01",
                "end": "2030-12-31",
            },
            "anchors": {"2023": 493953},
            "sourceBinding": {
                "adapter": "irs-soi-pub1304",
                "sourceUrl": "https://www.irs.gov/statistics/irs-table",
                "sourceSeriesId": "irs.soi.credit_30d.total_claims",
                "field": "clean_vehicle_credit_returns",
                "table": "Publication 1304 Table 3.3",
                "transform": {"operation": "multiply", "factor": 1},
                "releasePolicy": "first_print",
            },
        },
    }


def test_bounded_annual_first_print_seed_is_exact_and_one_shot() -> None:
    entry = bounded_annual_seed_entry()
    target = bounded_annual_first_print_seed_target(entry, set(), dt.date(2026, 8, 6))

    assert target == {
        "series": entry["series"],
        "period": "2027",
        "seedPeriod": "2027",
        "catalogSlug": "clean-vehicle-credit-total-claims-ty2027",
        **entry["extras"],
    }
    contract = register_targets.build_contract(target, dt.date(2026, 8, 6))
    assert contract["resolutionDateBasis"] == "resolve-by-bound"
    assert contract["resolutionDate"] == "2030-12-31"
    assert contract["sourceBinding"]["expectedReleaseWindow"] == {
        "start": "2029-01-01",
        "end": "2030-12-31",
    }
    batch_target = {
        **target,
        "country": contract["country"],
        "dataPointId": contract["dataPointId"],
    }
    validate_native_calendar_contract(contract, target, entry)
    register_targets.require_seed_docket_template(
        contract,
        [entry],
        "2026-08-06T00:00:00Z",
        batch_target=batch_target,
    )
    for key, value in (
        ("catalogSlug", "unauthorized-slug"),
        ("unit", "percentage_points"),
        ("valueScale", 999),
    ):
        drifted_contract = copy.deepcopy(contract)
        drifted_contract[key] = value
        with pytest.raises(
            RegistrationError, match="no longer regenerates the registered"
        ):
            register_targets.require_seed_docket_template(
                drifted_contract,
                [entry],
                "2026-08-06T00:00:00Z",
                batch_target=batch_target,
            )
    drifted_entry = copy.deepcopy(entry)
    drifted_entry["extras"]["anchors"]["2023"] = 999
    with pytest.raises(RegistrationError, match="batch target's run context"):
        register_targets.require_seed_docket_template(
            contract,
            [drifted_entry],
            "2026-08-06T00:00:00Z",
            batch_target=batch_target,
        )
    for key, value in (("period", "2028"), ("cadence", "monthly")):
        drifted_entry = copy.deepcopy(entry)
        drifted_entry[key] = value
        with pytest.raises(RegistrationError, match="annual YYYY period"):
            register_targets.require_seed_docket_template(
                contract,
                [drifted_entry],
                "2026-08-06T00:00:00Z",
                batch_target=batch_target,
            )
    for key in ("resolutionRule", "resolutionSourceUrl"):
        injected_target = copy.deepcopy(batch_target)
        injected_target[key] = "unauthorized analyst-visible context"
        with pytest.raises(RegistrationError, match="batch target's run context"):
            register_targets.require_seed_docket_template(
                contract,
                [entry],
                "2026-08-06T00:00:00Z",
                batch_target=injected_target,
            )
    drifted = copy.deepcopy(contract)
    drifted["sourceBinding"]["expectedReleaseWindow"]["start"] = "2029-02-01"
    with pytest.raises(RegistrationError, match="bounded seed release window"):
        validate_native_calendar_contract(drifted, target, entry)
    assert (
        bounded_annual_first_print_seed_target(
            entry,
            {"clean-vehicle-credit-total-claims-ty2027"},
            dt.date(2026, 8, 6),
        )
        is None
    )
    assert (
        bounded_annual_first_print_seed_target(entry, set(), dt.date(2029, 1, 1))
        is None
    )


@pytest.mark.parametrize(
    ("mutation", "warning"),
    [
        ("period", "requires a YYYY period"),
        ("seed-period", "seedPeriod must equal period"),
        ("basis", "requires a first_print binding and resolve-by-bound basis"),
        ("policy", "requires a first_print binding and resolve-by-bound basis"),
        ("window", "requires an exact expectedReleaseWindow"),
        ("resolution", "resolutionDate must equal the window end"),
        ("slug", "malformed bounded annual slug template"),
    ],
)
def test_bounded_annual_first_print_seed_refuses_drift(
    mutation: str,
    warning: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry = bounded_annual_seed_entry()
    if mutation == "period":
        entry["period"] = "FY2027"
    elif mutation == "seed-period":
        entry["seedPeriod"] = "2028"
    elif mutation == "basis":
        entry["extras"]["resolutionDateBasis"] = "release-calendar"
    elif mutation == "policy":
        entry["extras"]["sourceBinding"]["releasePolicy"] = "revision"
    elif mutation == "window":
        entry["extras"]["expectedReleaseWindow"] = {"start": "2029-01-01"}
    elif mutation == "resolution":
        entry["extras"]["resolutionDate"] = "2029-12-30"
    else:
        entry["slug"] = "clean-vehicle-credit-{}"

    assert (
        bounded_annual_first_print_seed_target(entry, set(), dt.date(2026, 8, 6))
        is None
    )
    assert warning in capsys.readouterr().err


def test_real_bounded_annual_seeds_are_reviewable_and_bound_to_docket() -> None:
    registry = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entries = [
        entry
        for entry in registry["series"]
        if entry.get("seedPeriod")
        and (entry.get("extras") or {}).get("resolutionDateBasis") == "resolve-by-bound"
        and not isinstance(entry.get("conditionalPair"), dict)
    ]

    assert {entry["series"] for entry in entries} == {
        "irs.soi.credit_30d.total_claims",
        "irs.soi.credit_30d.total_credit_amount",
        "irs.actc.total_credit_amount",
        # EIA DNav first print, admitted 2026-08-13 against the bounded
        # October Natural Gas Annual publication month.
        "eia.ng.vented_flared.us.annual",
        # SBA custody family, admitted 2026-08-08 (no release calendar;
        # bounded basis is the selector requirement for annual seeds).
        "sba.disaster.loan_program.charge_off_amount",
        "sba.disaster.loan_program.charge_off_rate_upb",
        "sba.disaster.loan_program.post_charge_off_recovery",
    }
    for entry in entries:
        target = bounded_annual_first_print_seed_target(
            entry, set(), dt.date(2026, 8, 6)
        )
        assert target is not None
        contract = register_targets.build_contract(target, dt.date(2026, 8, 6))
        validate_native_calendar_contract(contract, target, entry)
        batch_target = {
            **target,
            "country": contract["country"],
            "dataPointId": contract["dataPointId"],
        }
        register_targets.require_seed_docket_template(
            contract,
            [entry],
            "2026-08-06T00:00:00Z",
            batch_target=batch_target,
        )


@pytest.mark.usefixtures("resolver_admits")
def test_main_prioritizes_dated_seeds_before_a_capped_cursor_target(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    urgent = recurring_seed_entry()
    urgent.update(
        {
            "series": "fixture.seed.urgent",
            "slug": "urgent-{month}-{year}",
            "releaseDates": {"2026-07": "2026-07-27"},
        }
    )
    later = copy.deepcopy(urgent)
    later.update(
        {
            "series": "fixture.seed.later",
            "slug": "later-{month}-{year}",
            "releaseDates": {"2026-07": "2026-08-20"},
        }
    )
    weekly = {
        "series": "fixture.cursor.weekly",
        "cadence": "weekly",
        "slug": "cursor-{period}",
        "extras": {"targetUnit": "count"},
    }
    registry = tmp_path / "docket_series.json"
    registry.write_text(json.dumps({"series": [later, weekly, urgent]}))
    output = tmp_path / "targets.json"

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(2026, 7, 25)

    monkeypatch.setattr(roll_docket, "REGISTRY", registry)
    monkeypatch.setattr(roll_docket, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(roll_docket.dt, "date", FixedDate)
    monkeypatch.setattr(
        roll_docket,
        "live_catalog",
        lambda: ({"cursor-2026-07-18"}, {}, set()),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "roll_docket.py",
            "--max-targets",
            "2",
            "--out",
            str(output),
        ],
    )

    assert roll_docket.main() == 0

    targets = json.loads(output.read_text())["targets"]
    assert [target["series"] for target in targets] == [
        "fixture.seed.urgent",
        "fixture.seed.later",
    ]
    assert all(target["seedPeriod"] == target["period"] for target in targets)


@pytest.mark.usefixtures("resolver_admits")
def test_main_skips_expired_seed_before_cap_without_affecting_nonlisted_seed(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expired = recurring_seed_entry()
    expired.update(
        {
            "series": "fixture.seed.expired",
            "slug": "expired-{month}-{year}",
            "releaseDates": {"2026-07": "2026-07-27"},
        }
    )
    healthy = copy.deepcopy(expired)
    healthy.update(
        {
            "series": "fixture.seed.healthy",
            "slug": "healthy-{month}-{year}",
            "releaseDates": {"2026-07": "2026-08-20"},
        }
    )
    expired_id = "fixture.seed.expired.2026_07.first_print"
    configure_roll_exclusion_state(tmp_path, monkeypatch, [expired_id])
    registry = tmp_path / "docket_series.json"
    registry.write_text(json.dumps({"series": [expired, healthy]}))
    output = tmp_path / "targets.json"

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(2026, 7, 25)

    monkeypatch.setattr(roll_docket, "REGISTRY", registry)
    monkeypatch.setattr(roll_docket, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(roll_docket.dt, "date", FixedDate)
    monkeypatch.setattr(roll_docket, "live_catalog", lambda: (set(), {}, set()))
    monkeypatch.setattr(
        sys,
        "argv",
        ["roll_docket.py", "--max-targets", "1", "--out", str(output)],
    )

    assert roll_docket.main() == 0

    assert [
        target["catalogSlug"] for target in json.loads(output.read_text())["targets"]
    ] == ["healthy-july-2026"]
    stdout = capsys.readouterr().out
    assert (
        f"  skip expired-july-2026: dataPointId {expired_id} is "
        "terminally expired-unforecast\n"
    ) in stdout
    assert "capped:" not in stdout


def test_main_refuses_an_unparseable_expired_registration_list(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_roll_exclusion_state(
        tmp_path,
        monkeypatch,
        ["fixture.seed.expired.2026_07.first_print"],
    )
    expired_path = (
        roll_docket.ROOT
        / "site"
        / "src"
        / "data"
        / "expired-unforecast-registrations.ts"
    )
    expired_path.write_text(
        "export const EXPIRED_UNFORECAST_REGISTRATIONS = [\n"
        '  "fixture.seed.expired.2026_07.first_print",\n'
        '  "fixture.seed.silently-dropped.2026_07.first_print"\n'
        "] as const;\n"
    )
    registry = tmp_path / "docket_series.json"
    registry.write_text(json.dumps({"series": [recurring_seed_entry()]}))
    output = tmp_path / "targets.json"
    monkeypatch.setattr(roll_docket, "REGISTRY", registry)
    monkeypatch.setattr(
        roll_docket,
        "live_catalog",
        lambda: pytest.fail("catalog fetch must not run with an unreadable ratchet"),
    )
    monkeypatch.setattr(sys, "argv", ["roll_docket.py", "--out", str(output)])

    assert roll_docket.main() == 1
    assert not output.exists()
    assert "could not parse" in capsys.readouterr().err


def test_fresh_eci_registration_prevents_another_seed_registration(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry_data = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = next(
        row
        for row in registry_data["series"]
        if row["series"] == "bls.eci.total_compensation_private_industry_qoq"
    )
    registry = tmp_path / "docket_series.json"
    registry.write_text(json.dumps({"series": [entry]}))
    output = tmp_path / "targets.json"
    records = tmp_path / "records"
    (
        records
        / "2026-08-14"
        / (
            "2026-08-14t17-30-00z-"
            "bls-eci-total-compensation-private-industry-qoq-2026-q3"
        )
    ).mkdir(parents=True)
    published_slug = roll_docket.format_slug(entry["slug"], "2026-Q2", entry["cadence"])

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(2026, 8, 14)

    monkeypatch.setattr(roll_docket, "REGISTRY", registry)
    monkeypatch.setattr(roll_docket, "RECORDS", records)
    monkeypatch.setattr(roll_docket.dt, "date", FixedDate)
    monkeypatch.setattr(
        roll_docket,
        "live_catalog",
        lambda: ({published_slug}, {}, set()),
    )
    monkeypatch.setattr(sys, "argv", ["roll_docket.py", "--out", str(output)])

    assert roll_docket.main() == 0
    assert json.loads(output.read_text()) == {"targets": []}
    stdout = capsys.readouterr().out
    assert (
        "  pending bls.eci.total_compensation_private_industry_qoq 2026-Q3: "
        "an attempt for 2026-q3 was recorded but never published\n"
    ) in stdout
    assert "  retry " not in stdout
    # The 2026-08-14 re-registration lapsed through orphan grace and was
    # terminated on 2026-08-23, so the live exclusion state now refuses on
    # the terminal record first (gate order: expired before registered).
    assert (
        "bls.eci.total_compensation_private_industry_qoq.2026_q3.first_print "
        "is terminally expired-unforecast"
    ) in stdout
    # The immutable-registration guard still stands on its own: with the
    # terminal record out of the picture, the same roll refuses on the
    # existing registration rather than re-registering.
    monkeypatch.setattr(
        roll_docket, "expired_unforecast_registrations", lambda _root: frozenset()
    )
    assert roll_docket.main() == 0
    assert json.loads(output.read_text()) == {"targets": []}
    stdout = capsys.readouterr().out
    assert (
        "bls.eci.total_compensation_private_industry_qoq.2026_q3.first_print "
        "already has an immutable registration; refusing to re-register"
    ) in stdout


@pytest.mark.usefixtures("resolver_admits")
def test_main_hands_a_published_seed_back_to_the_ordinary_cursor(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = recurring_seed_entry()
    entry["releaseDates"]["2026-08"] = "2026-09-10"
    registry = tmp_path / "docket_series.json"
    registry.write_text(json.dumps({"series": [entry]}))
    output = tmp_path / "targets.json"
    published_slug = "fixture-july-2026"

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(2026, 8, 25)

    monkeypatch.setattr(roll_docket, "REGISTRY", registry)
    monkeypatch.setattr(roll_docket, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(roll_docket.dt, "date", FixedDate)
    monkeypatch.setattr(
        roll_docket,
        "live_catalog",
        lambda: ({published_slug}, {}, set()),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["roll_docket.py", "--out", str(output)],
    )

    assert roll_docket.main() == 0

    [target] = json.loads(output.read_text())["targets"]
    assert target["catalogSlug"] == "fixture-august-2026"
    assert "seedPeriod" not in target
    assert target["expectedReleaseDate"] == "2026-09-10"


@pytest.mark.parametrize(
    "series",
    [
        "bea.private_nonresidential_fixed_investment",
        "bea.research_and_development_fixed_investment",
    ],
)
def test_main_skips_bea_post_seed_successor_without_official_slot_literal(
    series: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry_data = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = next(row for row in registry_data["series"] if row["series"] == series)
    registry = tmp_path / "docket_series.json"
    registry.write_text(json.dumps({"series": [entry]}))
    output = tmp_path / "targets.json"
    published_slug = roll_docket.format_slug(entry["slug"], "2026-Q3", entry["cadence"])

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(2026, 11, 1)

    monkeypatch.setattr(roll_docket, "REGISTRY", registry)
    monkeypatch.setattr(roll_docket, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(roll_docket.dt, "date", FixedDate)
    monkeypatch.setattr(
        roll_docket,
        "live_catalog",
        lambda: ({published_slug}, {}, set()),
    )
    monkeypatch.setattr(sys, "argv", ["roll_docket.py", "--out", str(output)])

    assert roll_docket.main() == 0

    assert json.loads(output.read_text()) == {"targets": []}
    assert capsys.readouterr().err == (
        f"  warning: skip {series} 2026-Q4: calendar-gated adapter has no "
        "valid explicit official release date and releaseCalendarUrl in the "
        "docket registry\n"
    )


def test_main_reports_a_published_cursor_without_an_eligible_successor(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry_data = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = next(
        row for row in registry_data["series"] if row["series"] == "bls.lns11300000"
    )
    registry = tmp_path / "docket_series.json"
    registry.write_text(json.dumps({"series": [entry]}))
    output = tmp_path / "targets.json"

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(2026, 7, 25)

    monkeypatch.setattr(roll_docket, "REGISTRY", registry)
    monkeypatch.setattr(roll_docket, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(roll_docket.dt, "date", FixedDate)
    monkeypatch.setattr(
        roll_docket,
        "live_catalog",
        lambda: ({"labor-force-participation-dec-2026"}, {}, set()),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["roll_docket.py", "--out", str(output)],
    )

    assert roll_docket.main() == 0

    assert json.loads(output.read_text()) == {"targets": []}
    stdout = capsys.readouterr().out
    assert "no eligible successor within horizon" in stdout
    assert "no published cell" not in stdout


def test_template_regex_supports_repeated_tokens_without_duplicate_groups() -> None:
    template = "fixture-{year}-{month}-{year}-{month}"
    pattern = template_regex(template, "monthly")

    assert pattern.fullmatch("fixture-2026-may-2026-may")
    assert not pattern.fullmatch("fixture-2026-may-2027-may")
    assert latest_published_period(
        registry_entry("monthly", template),
        {"fixture-2026-may-2026-may"},
    ) == ("2026-05", "fixture-2026-may-2026-may")


def test_abbreviated_month_template_recovers_legacy_published_cursor() -> None:
    entry = registry_entry("monthly", "labor-force-participation-{month_abbr}-{year}")

    assert latest_published_period(entry, {"labor-force-participation-dec-2026"}) == (
        "2026-12",
        "labor-force-participation-dec-2026",
    )
    assert (
        roll_docket.format_slug(entry["slug"], "2027-01", "monthly")
        == "labor-force-participation-jan-2027"
    )


@pytest.mark.parametrize(
    ("cadence", "template", "slug"),
    [
        ("weekly", "fixture-{period}", "fixture-2026-02-30"),
        ("monthly", "fixture-{month}-{year}", "fixture-notamonth-2026"),
        ("quarterly", "fixture-q{quarter}-{year}", "fixture-q5-2026"),
    ],
)
def test_invalid_captured_periods_are_rejected(
    cadence: str,
    template: str,
    slug: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert latest_published_period(registry_entry(cadence, template), {slug}) is None
    assert "invalid captured period" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("cadence", "period"),
    [
        ("weekly", "week_2026-02-30"),
        ("monthly", "2026-13"),
        ("quarterly", "2026-Q9"),
    ],
)
def test_malformed_period_helpers_warn_and_never_raise(
    cadence: str,
    period: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert step_period(period, cadence) is None
    assert not not_too_far_ahead(period, cadence, dt.date(2026, 3, 15))
    assert "warning: skip malformed" in capsys.readouterr().err


def test_far_future_rogue_slug_recovers_earliest_eligible_gap() -> None:
    entry = registry_entry("monthly", "fixture-{month}-{year}")
    existing = {
        "fixture-january-2026",
        "fixture-february-2026",
        "fixture-december-2099",
    }

    assert next_roll_period(
        entry,
        existing,
        {"fixture-january-2026"},
        dt.date(2026, 3, 15),
    ) == ("2026-03", "fixture-february-2026")


def test_native_registry_date_becomes_exact_registration_window() -> None:
    registry = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = next(
        row for row in registry["series"] if row["series"] == "abs.cpi.all_groups.yoy"
    )
    extras = target_extras_for_period(entry, "2026-08")

    assert extras is not None
    assert extras["expectedReleaseDate"] == "2026-09-30"
    assert extras["releaseCalendarUrl"].startswith("https://www.abs.gov.au/")

    target = {
        "series": entry["series"],
        "period": "2026-08",
        "catalogSlug": "australia-cpi-annual-rate-august-2026",
        "country": "AU",
        "targetUnit": "percent",
        **extras,
    }
    contract = build_contract(target, dt.date(2026, 7, 25))
    assert contract["sourceBinding"]["expectedReleaseWindow"] == {
        "start": "2026-09-30",
        "end": "2026-09-30",
    }
    validate_native_calendar_contract(contract, target, entry)
    tampered = json.loads(json.dumps(contract))
    tampered["sourceBinding"]["expectedReleaseWindow"]["end"] = "2026-10-01"
    with pytest.raises(RegistrationError, match="committed docket calendar"):
        validate_native_calendar_contract(tampered, target, entry)
    with pytest.raises(RegistrationError, match="releaseCalendarUrl"):
        validate_native_calendar_contract(
            contract,
            {**target, "releaseCalendarUrl": "https://evil.example/calendar"},
            entry,
        )


def test_all_native_docket_series_commit_official_calendar_dates() -> None:
    registry = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    native_entries = [
        entry
        for entry in registry["series"]
        if entry.get("extras", {}).get("sourceBinding", {}).get("adapter")
        in OFFICIAL_CALENDAR_ADAPTERS
    ]

    assert {entry["series"] for entry in native_entries} == {
        "abs.cpi.all_groups.yoy",
        "abs.labour.unemployment_rate",
        "bls.qcew.child_day_care_services.annual_avg_employment",
        "eurostat.hicp.flash.yoy",
        "statcan.cpi.allitems.yoy",
        "statcan.gdp_by_industry.monthly_growth",
    }
    for entry in native_entries:
        assert entry["releaseCalendarUrl"].startswith("https://")
        assert entry["releaseDates"]
        for period, release_date in entry["releaseDates"].items():
            assert period[:4] in {"2025", "2026", "2027"}
            dt.date.fromisoformat(release_date)


def test_native_roll_skips_period_without_an_official_date(
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry = {
        "series": "fixture.native",
        "releaseCalendarUrl": "https://agency.example/releases",
        "releaseDates": {"2026-07": "2026-08-20"},
        "extras": {"sourceBinding": {"adapter": "abs-data-api"}},
    }

    assert target_extras_for_period(entry, "2026-08") is None
    warning = capsys.readouterr().err
    assert "warning: skip fixture.native 2026-08" in warning
    assert "no valid explicit official release date" in warning


def test_native_roll_never_forecasts_an_already_published_outcome(
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = next(
        row for row in registry["series"] if row["series"] == "statcan.cpi.allitems.yoy"
    )

    # June was released on 20 July before this docket date. The first eligible
    # still-unknown period is July, whose official print is due 17 August.
    assert (
        advance_past_released_native_periods(entry, "2026-06", dt.date(2026, 7, 25))
        == "2026-07"
    )
    warning = capsys.readouterr().err
    assert "official release 2026-07-20 is not after docket date 2026-07-25" in (
        warning
    )


def test_slug_template_replaces_month_names_only_at_token_boundaries() -> None:
    assert (
        slug_template("mayor-may-index-2026", "2026-05", "monthly")
        == "mayor-{month}-index-{year}"
    )
    assert (
        slug_template("may-report-may-2026", "2026-05", "monthly")
        == "may-report-{month}-{year}"
    )


@pytest.mark.parametrize(
    "period",
    ["week_2026-02-30", "2026-00", "2026-13", "2026-Q0", "2026-Q5"],
)
def test_adoption_rejects_semantically_invalid_periods(period: str) -> None:
    assert cadence_of(period) is None


def apel_snapshot_entries() -> list[dict]:
    registry = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    return [
        entry
        for entry in registry["series"]
        if entry["series"].startswith("usaspending.")
    ]


def test_real_apel_seeds_build_eleven_preregistered_snapshot_contracts() -> None:
    entries = apel_snapshot_entries()
    assert len(entries) == 12
    snapshot_entries = [
        entry for entry in entries if not isinstance(entry.get("conditionalPair"), dict)
    ]
    pair_entries = [
        entry for entry in entries if isinstance(entry.get("conditionalPair"), dict)
    ]
    assert len(snapshot_entries) == 11
    assert len(pair_entries) == 1

    for entry in snapshot_entries:
        assert entry["cadence"] == "annual"
        assert entry["period"] == "FY2026"
        assert entry["extras"]["expectedReleaseWindow"] == {
            "start": "2026-10-15",
            "end": "2026-10-22",
        }

        target = snapshot_seed_target(
            entry,
            set(),
            dt.date(2026, 8, 1),
        )
        assert target is not None
        assert target["catalogSlug"] == entry["slug"].format(period="fy2026")
        assert "previousTarget" not in target

        contract = register_targets.build_contract(
            target,
            dt.date(2026, 8, 1),
        )
        assert contract["series"] == entry["series"]
        assert contract["period"] == "FY2026"
        assert contract["dataPointId"] == (
            f"{entry['series']}.fy2026.registered_query_snapshot"
        )
        assert (
            contract["sourceBinding"]["expectedReleaseWindow"]
            == (entry["extras"]["expectedReleaseWindow"])
        )
        assert contract["sourceBinding"]["allowedHosts"] == ["api.usaspending.gov"]

    pair_entry = pair_entries[0]
    assert pair_entry["series"] == "usaspending.dod.prime_award_obligations"
    assert pair_entry["period"] == "2027"
    assert pair_entry["extras"]["expectedReleaseWindow"] == {
        "start": "2027-10-15",
        "end": "2027-10-22",
    }
    targets = roll_docket.conditional_pair_seed_targets(
        pair_entry,
        set(),
        dt.date(2026, 8, 1),
    )
    assert len(targets) == 2
    assert [target["dataPointId"] for target in targets] == [
        "usaspending.dod.prime_award_obligations.2027."
        "registered_query_snapshot.fy27_ndaa_enacted",
        "usaspending.dod.prime_award_obligations.2027."
        "registered_query_snapshot.no_fy27_ndaa",
    ]
    for target, arm in zip(targets, pair_entry["conditionalPair"]["arms"]):
        assert target["period"] == "2027"
        assert target["catalogSlug"] == arm["catalogSlug"]
        assert target["conditional"] == arm["conditional"]
        assert target["conditionId"] == arm["conditionId"]
        assert target["conditionDeadline"] == "2026-12-31"
        contract = register_targets.build_contract(target, dt.date(2026, 8, 1))
        assert contract["dataPointId"] == arm["dataPointId"]
        assert contract["conditional"] == arm["conditional"]
        assert contract["conditionId"] == arm["conditionId"]
        assert contract["conditionDeadline"] == "2026-12-31"
        assert contract["sourceBinding"]["releasePolicy"] == (
            "registered_query_snapshot"
        )
        assert contract["sourceBinding"]["expectedReleaseWindow"] == {
            "start": "2027-10-15",
            "end": "2027-10-22",
        }
        assert contract["sourceBinding"]["allowedHosts"] == ["api.usaspending.gov"]


def test_wave_b1_apel_seeds_bind_chronicle_identities_and_scaled_anchors() -> None:
    expected = {
        "usaspending.cdfi.assistance_transaction_obligations": (
            "69834e1f-1fbf-432c-9913-6b391321b3a8",
            319.455176,
            "CDFI Fund awarding-subagency financial-assistance award transactions",
        ),
        "usaspending.ondcp.hidta_al95001_obligations": (
            "02662bfc-b77d-48f3-938b-7a5b2f9e5c73",
            271.6576756,
            "Assistance Listing 95.001",
        ),
        "usaspending.ntia.broadband_al11038_obligations": (
            "f37307e0-91c6-49ee-afc7-2021e33ea863",
            409.85240647,
            "Assistance Listing 11.038",
        ),
        "usaspending.usfs.minnesota_place_of_performance_obligations": (
            "720be189-a4a5-4b0c-a25c-49233ff388a4",
            46.83255679,
            "Minnesota place of performance",
        ),
    }
    entries = {entry["series"]: entry for entry in apel_snapshot_entries()}

    for series, (uuid, anchor, scope_text) in expected.items():
        entry = entries[series]
        extras = entry["extras"]
        binding = extras["sourceBinding"]
        assert entry["ledger"] == {"uuid": uuid, "concept": series}
        assert extras["targetUnit"] == "usd_millions"
        assert extras["valueScale"] == 1e-6
        assert extras["anchors"] == {"2025": anchor}
        assert binding["transform"]["factor"] == 1e-6
        assert scope_text in binding["table"]
        assert "resolutionDate" not in extras


@pytest.mark.parametrize(
    ("today", "eligible"),
    [
        (dt.date(2026, 7, 31), False),  # 76 days before the capture date.
        (dt.date(2026, 8, 1), True),  # Exact 75-day horizon boundary.
        (dt.date(2026, 10, 14), True),
        (dt.date(2026, 10, 15), False),  # Never forecast on capture day.
        (dt.date(2026, 10, 16), False),
    ],
)
def test_snapshot_seed_uses_strict_precapture_start_boundary(
    today: dt.date,
    eligible: bool,
) -> None:
    entry = apel_snapshot_entries()[0]
    target = snapshot_seed_target(entry, set(), today)
    assert (target is not None) is eligible


def test_snapshot_seed_is_one_shot_and_never_steps_the_fiscal_year() -> None:
    entry = apel_snapshot_entries()[0]
    slug = entry["slug"].format(period="fy2026")

    assert (
        snapshot_seed_target(
            entry,
            {slug},
            dt.date(2026, 8, 1),
        )
        is None
    )
    assert entry["period"] == "FY2026"
    assert "FY2027" not in json.dumps(entry)


@pytest.mark.parametrize(
    "mutation",
    [
        "malformed-period",
        "missing-window",
        "reversed-window",
        "wrong-policy",
    ],
)
def test_snapshot_seed_rejects_unreviewable_annual_entries(
    mutation: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry = copy.deepcopy(apel_snapshot_entries()[0])
    if mutation == "malformed-period":
        entry["period"] = "2026"
    elif mutation == "missing-window":
        entry["extras"].pop("expectedReleaseWindow")
    elif mutation == "reversed-window":
        entry["extras"]["expectedReleaseWindow"] = {
            "start": "2026-10-22",
            "end": "2026-10-15",
        }
    else:
        entry["extras"]["sourceBinding"]["releasePolicy"] = "first_print"

    assert (
        snapshot_seed_target(
            entry,
            set(),
            dt.date(2026, 8, 1),
        )
        is None
    )
    assert "warning: skip" in capsys.readouterr().err


def conditional_pair_entry() -> dict:
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    return copy.deepcopy(
        next(
            entry
            for entry in docket["series"]
            if entry["series"] == "irs.actc.total_claims"
        )
    )


def ndaa_conditional_pair_entry() -> dict:
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    return copy.deepcopy(
        next(
            entry
            for entry in docket["series"]
            if entry["series"] == "usaspending.dod.prime_award_obligations"
            and isinstance(entry.get("conditionalPair"), dict)
        )
    )


def test_conditional_pair_emits_both_arms_before_the_deadline() -> None:
    entry = conditional_pair_entry()
    targets = roll_docket.conditional_pair_seed_targets(
        entry, set(), dt.date(2026, 8, 1)
    )
    assert [target["catalogSlug"] for target in targets] == [
        "additional-child-tax-credit-total-claims-ty2027-threshold-one-dollar",
        "additional-child-tax-credit-total-claims-ty2027-current-law",
    ]
    for target, arm in zip(targets, entry["conditionalPair"]["arms"]):
        assert target["series"] == "irs.actc.total_claims"
        assert target["period"] == "2027"
        assert target["conditional"] == arm["conditional"]
        assert target["dataPointId"] == arm["dataPointId"]
        assert target["conditionId"] == arm["conditionId"]
        assert target["conditionDeadline"] == "2027-12-31"
        # Extras ride into the target context: binding template, window,
        # canonical resolution by-date, and spawn-time history anchors.
        assert target["sourceBinding"]["adapter"] == "irs-soi-pub1304"
        assert target["resolutionDate"] == "2029-12-31"
        assert target["resolutionDateBasis"] == "resolve-by-bound"
        assert target["expectedReleaseWindow"] == {
            "start": "2029-01-01",
            "end": "2029-12-31",
        }
        assert target["anchors"]["2023"] == 17.626
        assert target["targetUnit"] == "millions"
    # Both arms register as one wave: distinct slugs and dataPointIds.
    build_contract(targets[0], dt.date(2026, 8, 1))
    build_contract(targets[1], dt.date(2026, 8, 1))


def test_main_routes_bounded_pairs_only_to_ticket_selection(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = tmp_path / "docket_series.json"
    registry.write_text(json.dumps({"series": [conditional_pair_entry()]}))
    output = tmp_path / "targets.json"

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(2026, 8, 1)

    monkeypatch.setattr(roll_docket, "REGISTRY", registry)
    monkeypatch.setattr(roll_docket.dt, "date", FixedDate)
    monkeypatch.setattr(roll_docket, "live_catalog", lambda: (set(), {}, set()))
    monkeypatch.setattr(sys, "argv", ["roll_docket.py", "--out", str(output)])

    assert roll_docket.main() == 0
    assert json.loads(output.read_text()) == {"targets": []}
    assert capsys.readouterr().out == (
        "  skip irs.actc.total_claims: resolve-by-bound target requires "
        "the attested generation-ticket lane\n"
        "0 targets\n"
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["roll_docket.py", "--include-bounded", "--out", str(output)],
    )
    assert roll_docket.main() == 0
    targets = json.loads(output.read_text())["targets"]
    assert [target["catalogSlug"] for target in targets] == [
        "additional-child-tax-credit-total-claims-ty2027-threshold-one-dollar",
        "additional-child-tax-credit-total-claims-ty2027-current-law",
    ]


def test_main_skips_every_conditional_arm_when_one_id_is_expired(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry = conditional_pair_entry()
    [expired_arm, healthy_arm] = entry["conditionalPair"]["arms"]
    expired_id = expired_arm["dataPointId"]
    configure_roll_exclusion_state(tmp_path, monkeypatch, [expired_id])
    registry = tmp_path / "docket_series.json"
    registry.write_text(json.dumps({"series": [entry]}))
    output = tmp_path / "targets.json"

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(2026, 8, 1)

    monkeypatch.setattr(roll_docket, "REGISTRY", registry)
    monkeypatch.setattr(roll_docket.dt, "date", FixedDate)
    monkeypatch.setattr(roll_docket, "live_catalog", lambda: (set(), {}, set()))
    monkeypatch.setattr(
        sys,
        "argv",
        ["roll_docket.py", "--include-bounded", "--out", str(output)],
    )

    assert roll_docket.main() == 0
    assert json.loads(output.read_text()) == {"targets": []}
    stdout = capsys.readouterr().out
    assert (
        f"  skip {expired_arm['catalogSlug']}: dataPointId {expired_id} is "
        "terminally expired-unforecast\n"
    ) in stdout
    assert (
        f"  skip {healthy_arm['catalogSlug']}: conditional pair-mate "
        f"dataPointId {expired_id} is terminally expired-unforecast\n"
    ) in stdout


def test_conditional_pair_stops_when_release_window_opens_literally(
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry = conditional_pair_entry()
    start = entry["extras"]["expectedReleaseWindow"]["start"]

    assert (
        roll_docket.conditional_pair_seed_targets(
            entry, set(), dt.date.fromisoformat(start)
        )
        == []
    )
    assert capsys.readouterr().err == (
        "  warning: skip irs.actc.total_claims: conditional pair forecast "
        f"generation must precede release window start {start}\n"
    )


# The CRP pair block as it stood in the docket through 2026-08-10. Preserve
# this exact terminated identity for the calendar-side resolutionDate incident
# regression even though the live docket now carries a fresh bounded pair.
CRP_INCIDENT_PAIR_BLOCK = {
    "conditionDeadline": "2027-09-30",
    "arms": [
        {
            "catalogSlug": "us-crp-enrolled-acres-september-2027-ceiling-27-million",
            "dataPointId": (
                "usda.fsa.crp.enrolled_acres_total.2027_09.first_print"
                ".ceiling_27_million"
            ),
            "conditionId": "cond.crp-acreage-ceiling-fy2027-31.enacted",
            "conditional": (
                "an enacted farm bill sets the CRP acreage ceiling at "
                "27,000,000 acres for FY2027-31"
            ),
        },
        {
            "catalogSlug": "us-crp-enrolled-acres-september-2027-no-fy2027-31-ceiling",
            "dataPointId": (
                "usda.fsa.crp.enrolled_acres_total.2027_09.first_print"
                ".no_fy2027_31_ceiling"
            ),
            "conditionId": "cond.crp-acreage-ceiling-fy2027-31.current-law",
            "conditional": (
                "No farm bill enacted by 2027-09-30 sets a CRP acreage "
                "ceiling for fiscal years 2027 through 2031; current law "
                "holds."
            ),
        },
    ],
}


def crp_fresh_pair_entry() -> dict:
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = copy.deepcopy(
        next(
            row
            for row in docket["series"]
            if row["series"] == "usda.fsa.crp.enrolled_acres_total"
        )
    )
    assert isinstance(entry.get("conditionalPair"), dict)
    return entry


def crp_incident_pair_entry() -> dict:
    entry = crp_fresh_pair_entry()
    entry["conditionalPair"] = copy.deepcopy(CRP_INCIDENT_PAIR_BLOCK)
    entry.pop("comment", None)
    entry["extras"].pop("resolutionDate", None)
    entry["extras"].pop("resolutionDateBasis", None)
    entry["extras"]["sourceBinding"]["sourceUrl"] = (
        "https://www.fsa.usda.gov/resources/programs/"
        "conservation-reserve-program/statistics"
    )
    return entry


def test_crp_monthly_conditional_pair_routes_the_policy_snapshot() -> None:
    entry = crp_fresh_pair_entry()

    targets = roll_docket.conditional_pair_seed_targets(
        entry, set(), dt.date(2026, 8, 13)
    )

    assert len(targets) == 2
    assert {target["period"] for target in targets} == {"2027-09"}
    assert [target["dataPointId"] for target in targets] == [
        (
            "usda.fsa.crp.enrolled_acres_total.2027_09.first_print."
            "ceiling_27_million_source_recovered_2026_08_13"
        ),
        (
            "usda.fsa.crp.enrolled_acres_total.2027_09.first_print."
            "no_fy2027_31_ceiling_source_recovered_2026_08_13"
        ),
    ]
    assert not {arm["dataPointId"] for arm in CRP_INCIDENT_PAIR_BLOCK["arms"]} & {
        target["dataPointId"] for target in targets
    }
    assert all(
        target["expectedReleaseWindow"] == {"start": "2027-12-01", "end": "2027-12-31"}
        for target in targets
    )
    assert all(target["conditionDeadline"] == "2027-09-30" for target in targets)
    assert all(target["country"] == "US" for target in targets)
    assert all(target["resolutionDate"] == "2027-12-31" for target in targets)
    assert all(
        target["resolutionDateBasis"] == "resolve-by-bound" for target in targets
    )
    contracts = [build_contract(target, dt.date(2026, 8, 13)) for target in targets]
    assert all(
        contract["sourceBinding"]["adapter"] == "fsa-crp-monthly-summary"
        for contract in contracts
    )
    assert all(
        contract["sourceBinding"]["sourceUrl"]
        == "https://www.fsa.usda.gov/tools/informational/reports/conservation-statistics/crp"
        for contract in contracts
    )
    assert all(
        contract["resolutionDateBasis"] == "resolve-by-bound"
        and contract["resolutionDate"] == "2027-12-31"
        for contract in contracts
    )


def test_docket_never_pins_resolution_date_on_calendar_entries() -> None:
    # build_contract writes resolutionDate only for resolve-by-bound targets;
    # the bind step then requires presence parity with the batch projection.
    # A calendar entry carrying extras.resolutionDate therefore registers
    # cleanly but deterministically fails --bind-registration-commits (the
    # 2026-08-10 roll-docket outage: the CRP pair's pre-basis leftover).
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    offenders = [
        entry["slug"]
        for entry in docket["series"]
        if isinstance(entry.get("extras"), dict)
        and "resolutionDate" in entry["extras"]
        and entry["extras"].get("resolutionDateBasis") != "resolve-by-bound"
    ]
    assert offenders == []


def test_calendar_pair_with_pinned_resolution_date_fails_bind_projection() -> None:
    # The exact incident shape, kept as a tripwire: re-pin the CRP entry's
    # old calendar-side resolutionDate and the roll projection diverges from
    # the registered contract at the bind step's presence check.
    entry = crp_incident_pair_entry()
    entry["extras"]["resolutionDate"] = "2027-12-31"

    targets = roll_docket.conditional_pair_seed_targets(
        entry, set(), dt.date(2026, 8, 2)
    )
    assert targets and all(
        target["resolutionDate"] == "2027-12-31" for target in targets
    )
    for target in targets:
        contract = build_contract(target, dt.date(2026, 8, 2))
        assert "resolutionDate" not in contract
        with pytest.raises(
            RegistrationError, match="contract mismatch for resolutionDate"
        ):
            register_targets.validate_target_resolution_projection(
                contract, target, label="repro"
            )


def test_conditional_pair_skips_published_arms_and_closed_deadlines() -> None:
    entry = conditional_pair_entry()
    published = {"additional-child-tax-credit-total-claims-ty2027-threshold-one-dollar"}
    targets = roll_docket.conditional_pair_seed_targets(
        entry, published, dt.date(2026, 8, 1)
    )
    assert [target["catalogSlug"] for target in targets] == [
        "additional-child-tax-credit-total-claims-ty2027-current-law"
    ]

    both = published | {"additional-child-tax-credit-total-claims-ty2027-current-law"}
    assert (
        roll_docket.conditional_pair_seed_targets(entry, both, dt.date(2026, 8, 1))
        == []
    )
    assert (
        roll_docket.conditional_pair_seed_targets(entry, set(), dt.date(2027, 12, 31))
        == []
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda entry: entry.update(cadence="monthly"),
        lambda entry: entry.update(period="FY2027"),
        lambda entry: entry["conditionalPair"].pop("conditionDeadline"),
        lambda entry: entry["extras"].pop("expectedReleaseWindow"),
        lambda entry: entry["extras"].update(
            expectedReleaseWindow={"start": "2029-12-31", "end": "2029-01-01"}
        ),
        # The release window must open only after the condition deadline.
        lambda entry: entry["extras"].update(
            expectedReleaseWindow={"start": "2027-06-01", "end": "2029-12-31"}
        ),
        lambda entry: entry["conditionalPair"]["arms"].pop(),
        lambda entry: entry["conditionalPair"]["arms"][0].pop("conditional"),
        lambda entry: entry["conditionalPair"]["arms"][0].pop("conditionId"),
        lambda entry: entry["conditionalPair"]["arms"][0].update(
            dataPointId=entry["conditionalPair"]["arms"][1]["dataPointId"]
        ),
        lambda entry: entry["conditionalPair"]["arms"][0].update(
            conditional=entry["conditionalPair"]["arms"][1]["conditional"]
        ),
        lambda entry: entry.pop("extras"),
    ],
)
def test_conditional_pair_fails_closed_on_malformed_registry(mutate) -> None:
    entry = conditional_pair_entry()
    mutate(entry)
    assert (
        roll_docket.conditional_pair_seed_targets(entry, set(), dt.date(2026, 8, 1))
        == []
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda entry: entry["extras"].update(
                resolutionDateBasis="not-a-real-basis"
            ),
            "  warning: skip irs.actc.total_claims: conditional pair has "
            "unsupported resolutionDateBasis 'not-a-real-basis'\n",
        ),
        (
            lambda entry: entry["extras"].update(
                resolutionDateBasis=["resolve-by-bound"]
            ),
            "  warning: skip irs.actc.total_claims: conditional pair has "
            "unsupported resolutionDateBasis ['resolve-by-bound']\n",
        ),
        (
            lambda entry: entry["extras"].update(resolutionDate="2029-12-30"),
            "  warning: skip irs.actc.total_claims: conditional pair "
            "resolve-by-bound requires resolutionDate to equal window end\n",
        ),
    ],
)
def test_conditional_pair_basis_refusals_are_literal(
    mutate, message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    entry = conditional_pair_entry()
    mutate(entry)

    assert (
        roll_docket.conditional_pair_seed_targets(entry, set(), dt.date(2026, 8, 1))
        == []
    )
    assert capsys.readouterr().err == message


def test_conditional_pair_rejects_extras_restating_arm_identity() -> None:
    entry = conditional_pair_entry()
    entry["extras"]["conditional"] = "override both arms"
    assert (
        roll_docket.conditional_pair_seed_targets(entry, set(), dt.date(2026, 8, 1))
        == []
    )
    entry = conditional_pair_entry()
    entry["extras"]["dataPointId"] = "irs.actc.total_claims.2028.first_print.x"
    assert (
        roll_docket.conditional_pair_seed_targets(entry, set(), dt.date(2026, 8, 1))
        == []
    )


def test_conditional_pair_rejects_mislabeled_data_point_year() -> None:
    entry = conditional_pair_entry()
    entry["conditionalPair"]["arms"][0]["dataPointId"] = (
        "irs.actc.total_claims.2028.first_print.threshold_one_dollar"
    )
    assert (
        roll_docket.conditional_pair_seed_targets(entry, set(), dt.date(2026, 8, 1))
        == []
    )


@pytest.mark.parametrize("mutation", ["arm-token", "policy", "missing-policy"])
def test_conditional_pair_refuses_release_policy_token_mismatch(
    mutation: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry = ndaa_conditional_pair_entry()
    if mutation == "arm-token":
        arm = entry["conditionalPair"]["arms"][0]
        arm["dataPointId"] = arm["dataPointId"].replace(
            ".registered_query_snapshot.", ".first_print."
        )
        expected_policy = "registered_query_snapshot"
        expected_token = "registered_query_snapshot"
    elif mutation == "policy":
        entry = conditional_pair_entry()
        entry["extras"]["sourceBinding"]["releasePolicy"] = "registered_query_snapshot"
        expected_policy = "registered_query_snapshot"
        expected_token = "registered_query_snapshot"
    else:
        entry["extras"]["sourceBinding"].pop("releasePolicy")
        expected_policy = None
        expected_token = "first_print"

    assert (
        roll_docket.conditional_pair_seed_targets(entry, set(), dt.date(2026, 8, 1))
        == []
    )
    warning = capsys.readouterr().err
    assert f"does not match sourceBinding.releasePolicy {expected_policy!r}" in warning
    assert f".{expected_token}.<condition_token>" in warning


def test_capped_selection_never_splits_a_pair_unit() -> None:
    pair = [{"catalogSlug": "arm-a"}, {"catalogSlug": "arm-b"}]
    singles = [(3, f"2026-0{n}", {"catalogSlug": f"single-{n}"}) for n in (1, 2, 3)]
    candidates = [(2, "2027-12-31", pair), *singles]

    # The pair fits: both arms selected together.
    targets, dropped = roll_docket.select_capped_targets(candidates, 3)
    assert [t["catalogSlug"] for t in targets] == ["arm-a", "arm-b", "single-1"]
    assert dropped == 2

    # The pair does not fit under the cap: selection stops rather than
    # splitting it or skipping ahead past it.
    targets, dropped = roll_docket.select_capped_targets(candidates, 1)
    assert targets == []
    assert dropped == 5

    # A retry with one arm already published is a singleton unit.
    targets, dropped = roll_docket.select_capped_targets(
        [(2, "2027-12-31", [{"catalogSlug": "arm-b"}]), *singles], 1
    )
    assert [t["catalogSlug"] for t in targets] == ["arm-b"]
    assert dropped == 3
