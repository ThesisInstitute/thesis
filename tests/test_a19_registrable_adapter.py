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
    # The prospect miner's allowlist is a separate literal.
    template = a19_entries()[0]["extras"]["sourceBinding"]
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
    assert register_targets.CALENDAR_CAPTURE_MARGIN_DAYS == {ADAPTER: 7}
    for adapter in register_targets.CALENDAR_GATED_SOURCE_ADAPTERS - {ADAPTER}:
        assert register_targets.calendar_release_window(adapter, day) == {
            "start": "2026-11-06",
            "end": "2026-11-06",
        }, adapter
    assert register_targets.calendar_release_window(ADAPTER, day) == {
        "start": "2026-11-06",
        "end": "2026-11-13",
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
        # put November 2025 on 2025-12-16 and December on 2026-01-09, 24 days),
        # so this is checked against the committed dates, not assumed.
        for (_, release_day), (_, following) in zip(dated, dated[1:]):
            assert release_day + dt.timedelta(days=MARGIN) < following


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
    with pytest.raises(RegistrationError, match="canonical ISO date"):
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
    # docket contract would be refused for a unit the executor does emit.
    assert routed_spec(contract["dataPointId"], "millions")["unit"] == "thousands"
    assert contract["unit"] == "millions" and refusal(contract) is None
    # The other reviewed unit contract is admitted too; nothing else is.
    contract.update(unit="thousands", valueScale=1.0)
    contract["sourceBinding"]["transform"] = {"operation": "multiply", "factor": 1.0}
    assert refusal(contract) is None


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
    admitted = registration(
        dataPointId=(
            f"{resolve_pending.A19_STEM}.healthcare_support.august_2026.first_print"
        ),
        catalogSlug="cps-healthcare-support-employment-august-2026",
        series=f"{resolve_pending.A19_STEM}.healthcare_support",
    )
    admitted["contract"]["sourceBinding"].update(
        adapter=ADAPTER,
        field="Healthcare support occupations",
        sourceSeriesId=f"{resolve_pending.A19_STEM}.healthcare_support",
    )
    output, _ = run_main(monkeypatch, capsys, [legacy, admitted])
    assert "BINDING/ADAPTER MISMATCH" not in output
    assert f"resolve {legacy['contract']['dataPointId']} -> 7.716 millions" in output
    assert f"resolve {admitted['contract']['dataPointId']} -> 5.709 millions" in output
    assert "dry-run: would append 2 row(s)" in output


def test_main_still_refuses_another_familys_adapter_on_an_a19_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    borrowed = registration()
    borrowed["contract"]["sourceBinding"]["adapter"] = "alfred-fred"
    output, _ = run_main(monkeypatch, capsys, [borrowed])
    assert "registered A-19 contract differs in adapter" in output
    assert "nothing new to record" in output


# -- why the window is not one day --------------------------------------------

OCTOBER = ("2026-11-06", "2026-11-13")


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
        ("2026-11-13", True),  # its last day
        ("2026-11-14", False),  # closed: nothing left to ask for
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
    if today == "2026-11-14":
        assert "A-19 FIRST-PRINT WINDOW MISSED (refusing)" in output


def test_a_capture_after_the_margin_is_never_custody(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    late = {"20261114120000": fixture("2026-08").replace("Aug.", "Oct.")}
    output, calls = run_main(
        monkeypatch,
        capsys,
        [october()],
        today="2026-11-20",
        archive=late,
        # The index is asked only for the window, but an Archive that answered
        # with a later row must still not be believed.
        index=cdx(("20261114120000", "200")),
    )
    assert "A-19 FIRST-PRINT WINDOW MISSED (refusing)" in output
    assert identity_url("20261114120000") not in calls
