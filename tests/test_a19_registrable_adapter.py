"""BLS CPS Table A-19 as a registrable adapter, ``bls-cps-a19``.

tests/test_a19_adapter.py covers the executor: the unit contract, the capture's
identity, the first-print window. This file covers admission: the adapter is
offered wherever a registration passes, a rolled target registers BLS's own
release day plus a reviewed capture margin, the execution-plan gate admits
exactly that contract, and the 18 contracts registered as ``generic-url``
before the adapter existed stay executable and stay unregistrable.

Nothing here touches the network; the Archive is a stand-in.
"""

from __future__ import annotations

import calendar
import copy
import datetime as dt
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import prospect_targets  # noqa: E402
import register_targets  # noqa: E402
import resolve_pending  # noqa: E402
import roll_docket  # noqa: E402
from register_targets import RegistrationError  # noqa: E402

from tests.test_a19_adapter import (  # noqa: E402
    cdx,
    fixture,
    identity_url,
    registration,
    routed_spec,
    run_main,
)

ADAPTER = "bls-cps-a19"
MARGIN = register_targets.CALENDAR_CAPTURE_MARGIN_DAYS[ADAPTER]
BLS_HOST = "www.bls.gov"


def docket() -> list[dict]:
    return json.loads((ROOT / "scripts" / "docket_series.json").read_text())["series"]


def a19_entries() -> list[dict]:
    entries = [
        entry
        for entry in docket()
        if entry["series"].startswith(resolve_pending.A19_STEM + ".")
    ]
    assert len(entries) == 6
    return entries


DATED = [
    pytest.param(entry, period, id=f"{entry['series'].rsplit('.', 1)[1]}-{period}")
    for entry in a19_entries()
    for period in sorted(entry["releaseDates"])
]


def rolled_target(entry: dict, period: str, previous: dict | None = None) -> dict:
    """The target the roller builds for ``period``, as roll_docket.main does."""

    extras = roll_docket.target_extras_for_period(entry, period)
    assert extras is not None
    target = {
        "series": entry["series"],
        "period": period,
        "catalogSlug": roll_docket.format_slug(entry["slug"], period, "monthly"),
        **extras,
    }
    if previous:
        target["previousTarget"] = dict(previous)
    return target


def built(entry: dict, period: str, previous: dict | None = None) -> dict:
    release_day = dt.date.fromisoformat(entry["releaseDates"][period])
    return register_targets.build_contract(
        rolled_target(entry, period, previous), release_day - dt.timedelta(days=20)
    )


def refusal(contract: dict) -> str | None:
    return resolve_pending.execution_plan_refusal(
        {"contract": contract, "targetContentHash": None}
    )


@pytest.fixture
def contract() -> dict:
    entry = next(e for e in a19_entries() if e["series"].endswith(".production"))
    return built(entry, min(entry["releaseDates"]))


# -- the adapter is offered wherever a registration passes --------------------


def test_adapter_is_offered_wherever_a_registration_passes() -> None:
    assert resolve_pending.A19_BINDING_ADAPTER == ADAPTER
    assert ADAPTER in register_targets.SOURCE_ADAPTERS
    assert ADAPTER in register_targets.CALENDAR_GATED_SOURCE_ADAPTERS
    assert ADAPTER in roll_docket.OFFICIAL_CALENDAR_ADAPTERS
    assert resolve_pending.FAMILY_ADAPTERS["a19"] == {ADAPTER}
    # The prospect miner's allowlist is a separate literal, and it accepts a
    # transform only as exactly {"operation", "factor"}; a later proposal
    # carries each template as its previousTarget binding.
    for entry in a19_entries():
        template = entry["extras"]["sourceBinding"]
        assert set(template) == prospect_targets.SOURCE_BINDING_FIELDS
        assert prospect_targets._source_binding_errors(template) == []
    assert prospect_targets._source_binding_errors(
        {**template, "adapter": "bls-cps-a20"}
    ) == ["bad previousTarget source adapter"]


def test_the_two_calendar_gated_sets_agree() -> None:
    # register_targets gates the window; roll_docket gates the roll. They are
    # separate literals, and an adapter in only one of them would either roll
    # from cadence or fail to bind what it rolled.
    assert set(register_targets.CALENDAR_GATED_SOURCE_ADAPTERS) == set(
        roll_docket.CALENDAR_GATED_SOURCE_ADAPTERS
    )


def test_a19_left_the_unregistrable_set_for_a_predicate() -> None:
    assert "a19" not in resolve_pending.EXECUTION_PLAN_UNREGISTRABLE_FAMILIES
    assert (
        resolve_pending.EXECUTION_PLAN_FAMILY_CHECKS["a19"] is resolve_pending._plan_a19
    )


# -- the window: BLS's release day plus a reviewed margin ---------------------


def test_only_a_listed_adapter_gets_a_capture_margin() -> None:
    day = dt.date(2026, 11, 6)
    assert register_targets.CALENDAR_CAPTURE_MARGIN_DAYS == {ADAPTER: 14}
    for adapter in register_targets.CALENDAR_GATED_SOURCE_ADAPTERS - {ADAPTER}:
        assert register_targets.calendar_release_window(adapter, day) == {
            "start": "2026-11-06",
            "end": "2026-11-06",
        }, adapter
    assert register_targets.calendar_release_window(ADAPTER, day) == {
        "start": "2026-11-06",
        "end": "2026-11-20",
    }
    # A margin is only meaningful on the calendar-gated path.
    assert set(register_targets.CALENDAR_CAPTURE_MARGIN_DAYS) <= set(
        register_targets.CALENDAR_GATED_SOURCE_ADAPTERS
    )


def test_docket_entries_are_the_executors_template_and_blss_calendar() -> None:
    for entry in a19_entries():
        row = entry["series"].rsplit(".", 1)[1]
        assert entry["releaseCalendarUrl"] == resolve_pending.A19_RELEASE_CALENDAR_URL
        assert entry["extras"]["sourceBinding"] == {
            "adapter": ADAPTER,
            "sourceUrl": resolve_pending.A19_SOURCE_URL,
            "sourceSeriesId": entry["series"],
            "field": resolve_pending.A19_ROW_LABELS[row],
            "table": resolve_pending.A19_REGISTERED_TABLE,
            "transform": {"operation": "multiply", "factor": 0.001},
            "releasePolicy": "first_print",
        }
        assert (entry["extras"]["targetUnit"], entry["extras"]["valueScale"]) == (
            "millions",
            0.001,
        )
        assert entry["releaseDates"], "an undated series cannot mint a target"
    # One schedule serves all six rows of the one table.
    assert (
        len({json.dumps(e["releaseDates"], sort_keys=True) for e in a19_entries()}) == 1
    )


def test_committed_release_dates_are_plausible_and_leave_room_for_the_margin() -> None:
    for entry in a19_entries():
        dated = sorted(
            (period, dt.date.fromisoformat(value))
            for period, value in entry["releaseDates"].items()
        )
        for period, release_day in dated:
            assert entry["releaseDates"][period] == release_day.isoformat()
            year, month = (int(part) for part in period.split("-"))
            month_end = dt.date(year, month, calendar.monthrange(year, month)[1])
            # The Employment Situation for a month follows that month. A date
            # filed under the wrong period is the error this catches.
            assert release_day > month_end, (entry["series"], period)
        # The window must close before the next Employment Situation replaces
        # the page. Releases are NOT reliably four weeks apart (BLS's schedule
        # has 2026-02-11 then 2026-03-06, 23 days), so this is checked against
        # the committed dates, not assumed.
        for (_, release_day), (_, following) in zip(dated, dated[1:]):
            assert release_day + dt.timedelta(days=MARGIN) < following


# BLS's "Schedule of Releases for the Employment Situation", every row of the
# page as read on 2026-09-20 (docs/anchor-verifications.md). Past rows are
# history and do not change; the last row was the end of the schedule that day.
BLS_EMPSIT_SCHEDULE_READ_2026_09_20 = {
    "2025-11": "2025-12-16",
    "2025-12": "2026-01-09",
    "2026-01": "2026-02-11",
    "2026-02": "2026-03-06",
    "2026-03": "2026-04-03",
    "2026-04": "2026-05-08",
    "2026-05": "2026-06-05",
    "2026-06": "2026-07-02",
    "2026-07": "2026-08-07",
    "2026-08": "2026-09-04",
    "2026-09": "2026-10-02",
    "2026-10": "2026-11-06",
    "2026-11": "2026-12-04",
}


def test_margin_is_far_inside_the_shortest_gap_bls_has_scheduled() -> None:
    # The committed docket can only ever compare a month with the ones dated
    # after it, and the newest month has no successor to compare with. What
    # protects that month is how far apart BLS schedules these releases.
    days = [
        dt.date.fromisoformat(value)
        for _, value in sorted(BLS_EMPSIT_SCHEDULE_READ_2026_09_20.items())
    ]
    gaps = [(later - earlier).days for earlier, later in zip(days, days[1:])]
    # 2026-02-11 to 2026-03-06, after the delayed January release: not the
    # four weeks one might assume.
    assert min(gaps) == 23
    # The window must close more than a week before the next release could
    # replace the page, even at the shortest gap BLS has scheduled.
    assert MARGIN + 7 < min(gaps)
    # The docket's dates are a second hand copy of the same page. Where the
    # two overlap they must agree, so editing one prompts a look at the other.
    for entry in a19_entries():
        for period, value in entry["releaseDates"].items():
            if period in BLS_EMPSIT_SCHEDULE_READ_2026_09_20:
                assert value == BLS_EMPSIT_SCHEDULE_READ_2026_09_20[period]


@pytest.mark.parametrize(("entry", "period"), DATED)
def test_rolled_target_registers_release_day_plus_margin_and_is_admitted(
    entry: dict, period: str
) -> None:
    target = rolled_target(entry, period)
    release_day = dt.date.fromisoformat(entry["releaseDates"][period])
    assert target["expectedReleaseDate"] == release_day.isoformat()
    assert target["releaseCalendarUrl"] == resolve_pending.A19_RELEASE_CALENDAR_URL

    contract = built(entry, period)
    binding = contract["sourceBinding"]
    assert binding["expectedReleaseWindow"] == {
        "start": release_day.isoformat(),
        "end": (release_day + dt.timedelta(days=MARGIN)).isoformat(),
    }
    assert binding["allowedHosts"] == [BLS_HOST]
    assert (contract["unit"], contract["valueScale"]) == ("millions", 0.001)
    # The id routes to this family, for this month and row.
    spec = routed_spec(contract["dataPointId"], "millions")
    assert spec["a19_row"] == entry["series"].rsplit(".", 1)[1]
    # Registration, the roller and the bind step all accept it.
    assert refusal(contract) is None
    assert roll_docket.roll_execution_plan_refusal(target) is None
    register_targets.validate_committed_calendar_contract(contract, target, entry)


@pytest.mark.parametrize(
    "entry", a19_entries(), ids=lambda e: e["series"].rsplit(".", 1)[1]
)
def test_the_next_month_rolls_from_the_registered_september_contract(
    entry: dict,
) -> None:
    # The real roll: each series steps from its registered September 2026
    # contract, which names generic-url and a month-name id.
    contracts = resolve_pending.registration_contracts()
    previous = next(
        reg["contract"]
        for reg in contracts.values()
        if reg["contract"]["series"] == entry["series"]
        and reg["contract"]["period"] == "2026-09"
    )
    assert previous["sourceBinding"]["adapter"] == "generic-url"
    period = min(entry["releaseDates"])
    contract = built(
        entry,
        period,
        {
            "country": previous["country"],
            "unit": previous["unit"],
            "dataPointId": previous["dataPointId"],
            "period": previous["period"],
            "resolutionDate": "2026-10-02",
            "resolutionSourceUrl": previous["sourceBinding"]["sourceUrl"],
        },
    )
    # The ledger append requires the record id to start with the contract's
    # series, and the id must route back to this family for this month.
    month = dt.date.fromisoformat(f"{period}-01").strftime("%B").lower()
    assert contract["dataPointId"] == (
        f"{entry['series']}.{month}_{period[:4]}.first_print"
    )
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "slug",
                "resolutionDate": entry["releaseDates"][period],
                "unit": contract["unit"],
            }
        ],
        "resolutionLinks": [
            {
                "status": "pending",
                "targetFactRef": contract["dataPointId"],
                "forecastSlug": "slug",
            }
        ],
    }
    ((_, kind, _, _, routed_period, *_),) = resolve_pending.pending_adapter_refs(log)
    assert (kind, routed_period) == ("a19", period)
    # The new contract takes the adapter from the docket, not its predecessor.
    assert contract["sourceBinding"]["adapter"] == ADAPTER
    assert refusal(contract) is None


def test_roller_never_infers_a_date_the_schedule_does_not_give() -> None:
    entry = a19_entries()[0]
    assert "2031-01" not in entry["releaseDates"]
    assert roll_docket.target_extras_for_period(entry, "2031-01") is None


def test_a_predecessors_research_links_do_not_widen_custody() -> None:
    # The September 2026 cells cite these hosts. Inherited into allowedHosts
    # they would make every October contract fail the executor's host pin, so
    # the gate would refuse it and the series would stop minting.
    entry = a19_entries()[0]
    period = min(entry["releaseDates"])
    previous = {
        "country": "US",
        "unit": "millions",
        "dataPointId": f"{entry['series']}.september_2026.first_print",
        "period": "2026-09",
        "resolutionDate": "2026-10-02",
        "resolutionSourceUrl": "https://www.bls.gov/web/empsit/cpseea19.htm",
        "sourceContext": [
            "https://fred.stlouisfed.org/series/LNU02032204",
            "https://api.bls.gov/publicAPI/v2/timeseries/data/LNU02032204",
            "https://web.archive.org/web/2026/https://www.bls.gov/",
        ],
    }
    contract = built(entry, period, previous)
    assert contract["sourceBinding"]["allowedHosts"] == [BLS_HOST]
    assert refusal(contract) is None

    # The inheritance this adapter opts out of is real: the same target under
    # the legacy name takes every one of those hosts.
    legacy = rolled_target(entry, period, previous)
    legacy["sourceBinding"] = {**legacy["sourceBinding"], "adapter": "generic-url"}
    legacy.pop("expectedReleaseDate")
    widened = register_targets.build_contract(legacy, dt.date(2026, 10, 10))
    assert "fred.stlouisfed.org" in widened["sourceBinding"]["allowedHosts"]
    assert "differs in allowedHosts" in (
        refusal(
            {
                **contract,
                "sourceBinding": {
                    **contract["sourceBinding"],
                    "allowedHosts": widened["sourceBinding"]["allowedHosts"],
                },
            }
        )
        or ""
    )


def test_bind_step_rederives_the_margin_and_keeps_every_other_adapter_one_day() -> None:
    entry = a19_entries()[0]
    period = min(entry["releaseDates"])
    target = rolled_target(entry, period)
    contract = built(entry, period)
    register_targets.validate_committed_calendar_contract(contract, target, entry)

    one_day = copy.deepcopy(contract)
    window = one_day["sourceBinding"]["expectedReleaseWindow"]
    window["end"] = window["start"]
    with pytest.raises(RegistrationError, match="disagrees with the committed docket"):
        register_targets.validate_committed_calendar_contract(one_day, target, entry)

    noncanonical = copy.deepcopy(entry)
    noncanonical["releaseDates"][period] = entry["releaseDates"][period].replace(
        "-", ""
    )
    # 3.11+ parses "20261106" and the canonical check refuses it; on 3.10
    # fromisoformat refuses it first. Either way the docket date is refused.
    with pytest.raises(RegistrationError, match="canonical ISO date|invalid ISO date"):
        register_targets.validate_committed_calendar_contract(
            contract, target, noncanonical
        )

    # The margin did not leak: a one-day adapter still refuses a wider window.
    native = next(
        e
        for e in docket()
        if (e.get("extras") or {}).get("sourceBinding", {}).get("adapter")
        == "statcan-wds"
    )
    native_period = max(native["releaseDates"])
    native_day = dt.date.fromisoformat(native["releaseDates"][native_period])
    native_target = {
        "series": native["series"],
        "period": native_period,
        "catalogSlug": roll_docket.format_slug(
            native["slug"], native_period, "monthly"
        ),
        **roll_docket.target_extras_for_period(native, native_period),
        # This series takes its unit from the cell it rolls from.
        "previousTarget": {"unit": "percent"},
    }
    native_contract = register_targets.build_contract(
        native_target, native_day - dt.timedelta(days=20)
    )
    assert native_contract["sourceBinding"]["expectedReleaseWindow"] == {
        "start": native_day.isoformat(),
        "end": native_day.isoformat(),
    }
    native_contract["sourceBinding"]["expectedReleaseWindow"]["end"] = (
        native_day + dt.timedelta(days=MARGIN)
    ).isoformat()
    with pytest.raises(RegistrationError, match="disagrees with the committed docket"):
        register_targets.validate_committed_calendar_contract(
            native_contract, native_target, native
        )


# -- the gate admits exactly that contract ------------------------------------


def _shift(window: dict, start: int, end: int) -> dict:
    return {
        "start": (
            dt.date.fromisoformat(window["start"]) + dt.timedelta(days=start)
        ).isoformat(),
        "end": (
            dt.date.fromisoformat(window["end"]) + dt.timedelta(days=end)
        ).isoformat(),
    }


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        # The window must be the release day plus the margin: no narrower, no
        # wider, and never shifted. The second case is the six July 2026
        # cells, whose window closed the day before BLS published.
        (
            lambda c: c["sourceBinding"].update(
                expectedReleaseWindow=_shift(
                    c["sourceBinding"]["expectedReleaseWindow"], 0, -MARGIN
                )
            ),
            "is not BLS's release day plus the reviewed capture margin",
        ),
        (
            lambda c: c["sourceBinding"].update(
                expectedReleaseWindow=_shift(
                    c["sourceBinding"]["expectedReleaseWindow"], -9, -MARGIN - 1
                )
            ),
            "is not BLS's release day plus the reviewed capture margin",
        ),
        (
            lambda c: c["sourceBinding"].update(
                expectedReleaseWindow=_shift(
                    c["sourceBinding"]["expectedReleaseWindow"], 0, 14
                )
            ),
            "is not BLS's release day plus the reviewed capture margin",
        ),
        # A month BLS's schedule does not date cannot be registered.
        (
            lambda c: c.update(
                period="2031-01",
                dataPointId=f"{c['series']}.january_2031.first_print",
            ),
            "does not date 2031-01",
        ),
        (
            lambda c: c["sourceBinding"].update(adapter="generic-url"),
            "names a page, not an executor",
        ),
        (
            lambda c: c["sourceBinding"].update(adapter="alfred-fred"),
            "differs in adapter",
        ),
        (
            lambda c: c["sourceBinding"].update(
                allowedHosts=["fred.stlouisfed.org", BLS_HOST]
            ),
            "differs in allowedHosts",
        ),
        (
            lambda c: c["sourceBinding"].update(field="Sales and related occupations"),
            "differs in field",
        ),
        (
            lambda c: c["sourceBinding"].update(
                sourceUrl="https://fred.stlouisfed.org/series/LNU02032204"
            ),
            "differs in sourceUrl",
        ),
        (lambda c: c["sourceBinding"].update(table="Table A-13"), "differs in table"),
        (
            lambda c: c["sourceBinding"].update(releasePolicy="advance_vintage"),
            "differs in releasePolicy",
        ),
        (lambda c: c["sourceBinding"].update(extra=1), "differs in sourceBinding keys"),
        (lambda c: c.update(unit="billions"), "differs in unit"),
        (lambda c: c.update(valueScale=1.0), "differs in valueScale"),
    ],
)
def test_gate_refuses_everything_but_the_reviewed_contract(
    contract: dict, mutate, expected: str
) -> None:
    assert refusal(contract) is None
    mutate(contract)
    assert expected in (refusal(contract) or "")


def test_gate_selects_the_unit_contract_before_it_compares_units(
    contract: dict,
) -> None:
    # The table prints thousands and the router's spec says so. Compared with
    # a millions contract before the registration selects the scale, every
    # docket contract would be refused for a unit the executor does emit. Once
    # the registration has selected the scale the gate's unit comparison cannot
    # fail for A-19 (its forecast unit is the contract's own), so this proves
    # the order, not the comparison; A19_REGISTERED_SCALES decides the unit.
    assert routed_spec(contract["dataPointId"], "millions")["unit"] == "thousands"
    assert contract["unit"] == "millions" and refusal(contract) is None
    # The other reviewed unit contract is admitted too; nothing else is.
    contract.update(unit="thousands", valueScale=1.0)
    contract["sourceBinding"]["transform"] = {"operation": "multiply", "factor": 1.0}
    assert refusal(contract) is None


def test_gate_refuses_a_contract_whose_period_is_not_the_month_its_id_routes_to(
    contract: dict,
) -> None:
    # The executor reads the month the dataPointId routes to. A contract that
    # says another dated month would otherwise be judged against the wrong row
    # of the calendar, or against none.
    entry = next(e for e in a19_entries() if e["series"] == contract["series"])
    other = max(entry["releaseDates"])
    assert other != contract["period"]
    contract["period"] = other
    assert "is not the month its dataPointId routes to" in (refusal(contract) or "")


def test_gate_refuses_an_a19_contract_on_the_resolve_by_bound_basis() -> None:
    # registration accepts this contract: an explicit window that happens to
    # equal the margin window, with resolutionDate at its end. main() would
    # refuse it the day after the window closes, before the A-19 leg could read
    # a capture requested on the last day.
    entry = next(e for e in a19_entries() if e["series"].endswith(".production"))
    period = min(entry["releaseDates"])
    window = register_targets.calendar_release_window(
        ADAPTER, dt.date.fromisoformat(entry["releaseDates"][period])
    )
    target = {
        **rolled_target(entry, period),
        "resolutionDateBasis": "resolve-by-bound",
        "resolutionDate": window["end"],
        "expectedReleaseWindow": window,
    }
    bounded = register_targets.build_contract(
        target, dt.date.fromisoformat(window["start"]) - dt.timedelta(days=20)
    )
    assert bounded["resolutionDateBasis"] == "resolve-by-bound"
    assert bounded["sourceBinding"]["expectedReleaseWindow"] == window
    assert "resolves on the 'release-calendar' basis" in (refusal(bounded) or "")


def _plan(contract: dict, **kwargs: object) -> str | None:
    """``_plan_a19`` itself, as a later caller might reach it."""

    return resolve_pending._plan_a19(
        {"contract": contract, "targetContentHash": None},
        routed_spec(contract["dataPointId"], contract["unit"]),
        contract["period"],
        **kwargs,
    )


def test_the_predicate_stands_alone_if_it_is_reached_another_way(
    contract: dict,
) -> None:
    # execution_plan_refusal refuses generic-url and a drifted binding before
    # it consults any family, so through the gate these two checks never fire.
    # They are what keeps the predicate safe if that order ever changes.
    assert _plan(contract) is None
    legacy = copy.deepcopy(contract)
    legacy["sourceBinding"]["adapter"] = "generic-url"
    assert "must bind 'bls-cps-a19', not 'generic-url'" in (_plan(legacy) or "")
    drifted = copy.deepcopy(contract)
    drifted["sourceBinding"]["table"] = "Table A-13"
    assert "differs in table" in (_plan(drifted) or "")


@pytest.mark.parametrize(
    ("rewrite", "why"),
    [
        (
            lambda e: e.update(
                releaseCalendarUrl="https://fred.stlouisfed.org/releases/calendar"
            ),
            "another calendar",
        ),
        (lambda e: e.pop("releaseCalendarUrl"), "no calendar"),
        (lambda e: e.update(releaseDates={}), "no dates"),
        (lambda e: e.update(releaseDates=None), "malformed dates"),
        (
            lambda e: e["releaseDates"].update(
                {k: v.replace("-", "") for k, v in e["releaseDates"].items()}
            ),
            "non-canonical date",
        ),
    ],
)
def test_calendar_authority_is_blss_schedule_in_the_committed_docket(
    contract: dict, rewrite, why: str
) -> None:
    entries = copy.deepcopy(docket())
    series, period = contract["series"], contract["period"]
    assert resolve_pending.a19_committed_release_day(series, period, entries) == (
        dt.date.fromisoformat(
            contract["sourceBinding"]["expectedReleaseWindow"]["start"]
        )
    )
    rewrite(next(e for e in entries if e["series"] == series))
    assert resolve_pending.a19_committed_release_day(series, period, entries) is None, (
        why
    )
    spec = routed_spec(contract["dataPointId"], "millions")
    assert "does not date" in (
        resolve_pending._plan_a19(
            {"contract": contract, "targetContentHash": None},
            spec,
            period,
            docket_entries=entries,
        )
        or ""
    )


def test_calendar_authority_needs_exactly_one_docket_entry(contract: dict) -> None:
    entries = docket()
    series, period = contract["series"], contract["period"]
    owner = next(e for e in entries if e["series"] == series)
    assert resolve_pending.a19_committed_release_day(series, period, []) is None
    assert (
        resolve_pending.a19_committed_release_day(series, period, [owner, owner])
        is None
    )
    assert resolve_pending.a19_committed_release_day(series, period, [owner])


# -- contracts registered before the adapter existed --------------------------


def test_every_a19_registration_on_disk_stays_executable_and_unregistrable() -> None:
    contracts = resolve_pending.registration_contracts()
    legacy = {
        ref: reg
        for ref, reg in contracts.items()
        if ref.startswith(resolve_pending.A19_STEM)
        and reg["contract"]["sourceBinding"]["adapter"] == "generic-url"
    }
    # July, August and September 2026, six rows each. Immutable, so the count
    # can only be this.
    assert len(legacy) == 18
    for ref, reg in legacy.items():
        spec = routed_spec(ref, reg["contract"]["unit"])
        executed, drifted = resolve_pending.a19_execution_spec(spec, reg)
        assert drifted is None and executed["unit"] == "millions", ref
        # The one thing main() forgives, and only for this family's spec.
        assert (
            resolve_pending.binding_adapter_mismatch("a19", reg)
            == executed["legacy_binding_adapter"]
            == "generic-url"
        ), ref
        # And it could never be registered again.
        assert "names a page, not an executor" in (refusal(reg["contract"]) or ""), ref


def test_main_resolves_a_legacy_and_a_new_contract_to_the_same_print(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    legacy = registration()
    renamed = registration(
        dataPointId=(
            f"{resolve_pending.A19_STEM}.healthcare_support.august_2026.first_print"
        ),
        catalogSlug="cps-healthcare-support-employment-august-2026",
        series=f"{resolve_pending.A19_STEM}.healthcare_support",
    )
    # August's cadence window under the new adapter NAME: not a contract the
    # gate would register, only proof that main() executes the name.
    renamed["contract"]["sourceBinding"].update(
        adapter=ADAPTER,
        field="Healthcare support occupations",
        sourceSeriesId=f"{resolve_pending.A19_STEM}.healthcare_support",
    )
    output, _ = run_main(monkeypatch, capsys, [legacy, renamed])
    assert "BINDING/ADAPTER MISMATCH" not in output
    assert f"resolve {legacy['contract']['dataPointId']} -> 7.716 millions" in output
    assert f"resolve {renamed['contract']['dataPointId']} -> 5.709 millions" in output
    assert "dry-run: would append 2 row(s)" in output


def test_main_still_refuses_another_familys_adapter_on_an_a19_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    borrowed = registration()
    borrowed["contract"]["sourceBinding"]["adapter"] = "alfred-fred"
    output, _ = run_main(monkeypatch, capsys, [borrowed])
    assert "registered A-19 contract differs in adapter" in output
    assert "nothing new to record" in output


# -- the month labels the new adapter will meet first -------------------------

# Real captures, read 2026-09-21 through the resolver's own reader
# (a19_read_capture, the Archive's stored ``id_`` response) and kept as their
# table element (tests/fixtures/a19/README.md). October is the first month
# ``bls-cps-a19`` resolves, and "Oct." and "May" were the two header labels no
# capture had confirmed. Values are the printed current-month thousands.
REAL_LABEL_CAPTURES = {
    "2023-10": (
        "20231130070442",
        "Oct.",
        {
            "business_financial_operations": 9855.0,
            "computer_mathematical": 6763.0,
            "healthcare_support": 5159.0,
            "office_administrative_support": 15665.0,
            "production": 8072.0,
            "transportation_material_moving": 11668.0,
        },
    ),
    "2026-05": (
        "20260613101041",
        "May",
        {
            "business_financial_operations": 10033.0,
            "computer_mathematical": 6903.0,
            "healthcare_support": 5786.0,
            "office_administrative_support": 16335.0,
            "production": 7912.0,
            "transportation_material_moving": 12120.0,
        },
    ),
}


def real_capture(period: str) -> str:
    stamp = REAL_LABEL_CAPTURES[period][0]
    return (
        ROOT
        / "tests"
        / "fixtures"
        / "a19"
        / f"cpseea19-{period}-wayback-{stamp}.table.html"
    ).read_text()


@pytest.mark.parametrize("period", sorted(REAL_LABEL_CAPTURES))
def test_a_real_capture_prints_the_label_and_the_six_rows(period: str) -> None:
    _, label, printed = REAL_LABEL_CAPTURES[period]
    table = real_capture(period)
    assert f">{label}<br" in table
    assert resolve_pending.a19_snapshot_period(table) == period
    assert resolve_pending.a19_values_from_html(table) == printed


def test_the_synthetic_october_pages_spell_the_month_as_bls_does() -> None:
    # The main() tests below build an October page by relabelling August's.
    # On their own they would only assert the parser's table against itself;
    # this ties that spelling to what a real October capture prints.
    header = re.compile(r"<th\b[^>]*>\s*([A-Za-z]+\.?)\s*<br")
    real = set(header.findall(real_capture("2023-10")))
    synthetic = set(header.findall(fixture("2026-08").replace("Aug.", "Oct.")))
    assert real == synthetic == {"Oct."}


# -- why the window is not one day --------------------------------------------

OCTOBER = ("2026-11-06", "2026-11-20")


def october(window: tuple[str, str] = OCTOBER) -> dict:
    reg = registration("2026-10", window)
    reg["contract"]["sourceBinding"]["adapter"] = ADAPTER
    return reg


def october_archive() -> dict[str, str]:
    printed = fixture("2026-08")
    return {
        # 13:45 UTC on release day is fifteen minutes after an 08:30 EST
        # release; this capture still serves September's table.
        "20261106134500": printed.replace("Aug.", "Sept."),
        "20261109140000": printed.replace("Aug.", "Oct."),
        "20261112090000": printed.replace("Aug.", "Oct."),
    }


def test_main_resolves_from_the_earliest_capture_inside_the_margin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = october_archive()
    reg = october()
    output, calls = run_main(
        monkeypatch,
        capsys,
        [reg],
        today="2026-11-10",
        archive=archive,
        index=cdx(*[(stamp, "200") for stamp in archive]),
    )
    assert f"resolve {reg['contract']['dataPointId']} -> 7.716 millions" in output
    # The stale release-day capture was read and passed over for its header;
    # the first capture that prints October was used, not the later one.
    assert identity_url("20261106134500") in calls
    assert identity_url("20261109140000") in calls
    assert identity_url("20261112090000") not in calls
    assert '"observed_at": "2026-11-09"' in output
    assert not any("/save/" in call for call in calls)


def test_a_requested_capture_is_read_by_a_later_run_even_after_the_window_closes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The window judges the CAPTURE's date, not the day the resolver runs. A
    # run never reads the capture it has just asked for, so the run that
    # resolves is a later one, and it may come after the window has closed.
    # This is also all a one-day window can ever do: one request on the day,
    # read the next morning, with nothing to fall back on if it fails.
    reg = october(("2026-11-06", "2026-11-06"))
    output, calls = run_main(monkeypatch, capsys, [reg], today="2026-11-06", archive={})
    assert resolve_pending.A19_CAPTURE_REQUESTED in output
    assert "nothing new to record" in output

    archive = {"20261106150000": fixture("2026-08").replace("Aug.", "Oct.")}
    output, calls = run_main(
        monkeypatch,
        capsys,
        [reg],
        today="2026-11-07",
        archive=archive,
        index=cdx(("20261106150000", "200")),
    )
    assert f"resolve {reg['contract']['dataPointId']} -> 7.716 millions" in output
    assert '"observed_at": "2026-11-06"' in output
    assert not any("/save/" in call for call in calls)


def test_a_one_day_window_would_have_lost_the_same_target(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The counterfactual the margin exists for: same Archive, same day, and
    # the only release-day capture predates the page's update. The gate would
    # not register this window; main() judges only the capture against it.
    archive = october_archive()
    reg = october(("2026-11-06", "2026-11-06"))
    assert "is not BLS's release day plus" in (refusal(reg["contract"]) or "")
    output, calls = run_main(
        monkeypatch,
        capsys,
        [reg],
        today="2026-11-10",
        archive=archive,
        index=cdx(("20261106134500", "200")),
    )
    assert "A-19 FIRST-PRINT WINDOW MISSED (refusing)" in output
    assert "nothing new to record" in output
    assert identity_url("20261109140000") not in calls


@pytest.mark.parametrize(
    ("today", "asks"),
    [
        ("2026-11-05", False),  # the window has not opened
        ("2026-11-06", True),
        ("2026-11-13", True),
        ("2026-11-20", True),  # its last day
        ("2026-11-21", False),  # closed: nothing left to ask for
    ],
)
def test_main_asks_for_a_capture_on_each_day_the_margin_window_is_open(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    today: str,
    asks: bool,
) -> None:
    output, calls = run_main(monkeypatch, capsys, [october()], today=today, archive={})
    assert any("/save/" in call for call in calls) is asks
    assert (resolve_pending.A19_CAPTURE_REQUESTED in output) is asks
    assert "nothing new to record" in output
    if today == "2026-11-21":
        assert "A-19 FIRST-PRINT WINDOW MISSED (refusing)" in output


def test_a_capture_after_the_margin_is_never_custody(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    late = {"20261121120000": fixture("2026-08").replace("Aug.", "Oct.")}
    output, calls = run_main(
        monkeypatch,
        capsys,
        [october()],
        today="2026-11-27",
        archive=late,
        # The index is asked only for the window, but an Archive that answered
        # with a later row must still not be believed.
        index=cdx(("20261121120000", "200")),
    )
    assert "A-19 FIRST-PRINT WINDOW MISSED (refusing)" in output
    assert identity_url("20261121120000") not in calls


def test_a_release_bls_delays_past_the_margin_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A registered window is immutable. If BLS publishes October later than it
    # had scheduled (it delayed a release by a month in the 2025 shutdown),
    # every capture inside the window still prints September. The header check
    # passes each one over, so the target is missed; it is never resolved to
    # the previous month's number.
    september = fixture("2026-08").replace("Aug.", "Sept.")
    archive = {
        "20261106140000": september,
        "20261110140000": september,
        "20261121140000": fixture("2026-08").replace("Aug.", "Oct."),
    }
    output, calls = run_main(
        monkeypatch,
        capsys,
        [october()],
        today="2026-11-25",
        archive=archive,
        index=cdx(("20261106140000", "200"), ("20261110140000", "200")),
    )
    assert (
        "A-19 FIRST-PRINT WINDOW MISSED (refusing): the Archive's index lists 2 "
        "capture(s) dated inside the registered window" in output
    )
    assert "and none of those prints 2026-10" in output
    assert "nothing new to record" in output
    assert identity_url("20261121140000") not in calls
