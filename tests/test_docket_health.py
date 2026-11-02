"""The docket health check names a stall that no failed run would show."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import shutil
import subprocess
import sys

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import docket_health  # noqa: E402
import roll_docket  # noqa: E402
import verify_records_attestations as provenance  # noqa: E402
from docket_health import (  # noqa: E402
    CALENDAR,
    IN_GRACE,
    PAST_GRACE,
    RUNWAY_DAYS,
    STALL,
    STALL_DAYS,
    Finding,
    calendar_findings,
    fingerprint,
    registration_stall,
    render_issue,
    unforecast_findings,
)

WORKFLOW_PATH = ".github/workflows/docket-health.yml"
TODAY = dt.date(2026, 11, 2)
NOW = dt.datetime(2026, 11, 2, 12, 15, tzinfo=dt.timezone.utc)
HASH = "0" * 64
REGISTRY = json.loads((ROOT / "scripts" / "docket_series.json").read_text())["series"]


@pytest.fixture
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> dt.date:
            return cls(TODAY.year, TODAY.month, TODAY.day)

    monkeypatch.setattr(roll_docket.dt, "date", FixedDate)


@pytest.fixture
def resolver_admits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        roll_docket, "execution_plan_refusal", lambda registration: None
    )


def gated_entry(**overrides: object) -> dict:
    return {
        "series": "fixture.series",
        "cadence": "monthly",
        "slug": "fixture-{month}-{year}",
        "releaseCalendarUrl": "https://agency.example/release-calendar",
        "releaseDates": {"2026-09": "2026-10-15", "2026-10": "2026-11-15"},
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
        **overrides,
    }


def _name(day: dt.date) -> str:
    return f"{day.isoformat()}-{HASH}.json"


def test_a_registration_gap_alarms_only_past_the_stall_line() -> None:
    edge = TODAY - dt.timedelta(days=STALL_DAYS)
    assert registration_stall([_name(edge)], TODAY) is None
    finding = registration_stall(
        [_name(edge - dt.timedelta(days=1)), "README.md"], TODAY
    )
    assert finding is not None
    assert finding.kind == STALL
    assert f"{STALL_DAYS + 1} days ago" in finding.detail


def test_no_registration_at_all_alarms() -> None:
    finding = registration_stall(["README.md"], TODAY)
    assert finding is not None
    assert finding.detail == "No registration exists."


def test_the_october_stall_would_have_alarmed_a_week_in() -> None:
    newest = dt.date(2026, 10, 2)
    assert registration_stall([_name(newest)], dt.date(2026, 10, 12)) is None
    assert registration_stall([_name(newest)], dt.date(2026, 10, 13)) is not None


@settings(max_examples=200, deadline=None)
@given(
    st.lists(st.dates(dt.date(2026, 1, 1), dt.date(2027, 12, 31)), min_size=1),
    st.dates(dt.date(2026, 1, 1), dt.date(2028, 6, 30)),
)
def test_the_stall_check_reads_only_the_newest_registration(
    days: list[dt.date], today: dt.date
) -> None:
    finding = registration_stall(map(_name, days), today)
    assert (finding is not None) == ((today - max(days)).days > STALL_DAYS)


@pytest.mark.usefixtures("fixed_today", "resolver_admits")
def test_a_calendar_alarms_inside_the_runway_and_not_before() -> None:
    edge = TODAY + dt.timedelta(days=RUNWAY_DAYS)
    entry = gated_entry(releaseDates={"2026-10": edge.isoformat()})
    published = {"fixture-september-2026"}
    assert calendar_findings([entry], published, {}, TODAY) == ([], {})

    inside = edge - dt.timedelta(days=1)
    entry = gated_entry(releaseDates={"2026-10": inside.isoformat()})
    [finding], refused = calendar_findings([entry], published, {}, TODAY)
    assert refused == {}
    assert finding.kind == CALENDAR
    assert finding.subject == "fixture.series"
    assert f"ends {inside}, {RUNWAY_DAYS - 1} days from now" in finding.detail
    assert "2026-11 has no date" in finding.detail
    assert "https://agency.example/release-calendar" in finding.detail


@pytest.mark.usefixtures("fixed_today", "resolver_admits")
def test_a_calendar_with_no_dates_alarms_from_the_published_cursor() -> None:
    entry = gated_entry(releaseDates={})
    [finding], _ = calendar_findings([entry], {"fixture-september-2026"}, {}, TODAY)
    assert finding.detail.startswith("It has no committed date, and 2026-10 has")


@pytest.mark.usefixtures("fixed_today")
def test_a_series_a_date_cannot_help_stays_out_of_the_alarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        roll_docket, "execution_plan_refusal", lambda registration: "on hold"
    )
    findings, refused = calendar_findings(
        [gated_entry()], {"fixture-september-2026"}, {}, TODAY
    )
    assert findings == []
    assert refused == {"fixture.series": "on hold"}


@pytest.mark.usefixtures("fixed_today", "resolver_admits")
@pytest.mark.parametrize(
    "entry",
    [
        gated_entry(cadence="annual"),
        gated_entry(cadence="weekly"),
        gated_entry(conditionalPair={"conditionDeadline": "2026-12-01"}),
        gated_entry(
            extras={
                **gated_entry()["extras"],
                "resolutionDateBasis": "resolve-by-bound",
            }
        ),
        gated_entry(
            extras={
                "targetUnit": "percent",
                "sourceBinding": {"adapter": "generic-url"},
            }
        ),
    ],
    ids=["annual", "weekly", "conditional", "bounded", "not-calendar-gated"],
)
def test_only_recurring_calendar_gated_series_can_alarm(entry: dict) -> None:
    assert calendar_findings([entry], {"fixture-september-2026"}, {}, TODAY) == ([], {})


@pytest.mark.usefixtures("fixed_today", "resolver_admits")
def test_a_series_with_no_published_cursor_cannot_alarm() -> None:
    assert calendar_findings([gated_entry()], set(), {}, TODAY) == ([], {})


@pytest.mark.usefixtures("fixed_today")
def test_the_gate_judges_a_successor_from_its_published_contract() -> None:
    # Producer prices keep a legacy id stem on the published contract, and no
    # resolver family routes it, so new dates would not let the series register.
    entry = next(
        row
        for row in REGISTRY
        if row["series"] == "bls.ppi.final_demand_monthly_change"
    )
    slug = roll_docket.format_slug(entry["slug"], "2026-07", entry["cadence"])
    previous = {
        "country": "US",
        "unit": "percent",
        "dataPointId": "bls.wp.WPSFD4.2026-07.first_print",
        "resolutionDate": "2026-08-13",
    }
    findings, refused = calendar_findings([entry], {slug}, {slug: previous}, TODAY)
    assert findings == []
    assert "no resolver family routes" in refused[entry["series"]]


def test_targets_inside_grace_warn_after_a_day() -> None:
    fresh = {
        "dataPointId": "fresh",
        "registeredAt": "2026-11-02T00:00:00Z",
        "withinGrace": True,
    }
    aging = {
        "dataPointId": "aging",
        "registeredAt": "2026-11-01T12:15:00Z",
        "withinGrace": True,
    }
    [finding] = unforecast_findings([fresh, aging], NOW)
    assert finding.kind == IN_GRACE
    assert finding.subject == "aging"
    assert "grace ends 2026-11-08T12:15:00Z" in finding.detail


def test_targets_past_grace_say_they_block_every_publish() -> None:
    row = {
        "dataPointId": "bls.cpi.u.headline_mom.2026_10.first_print",
        "registeredAt": "2026-10-19T21:11:01Z",
        "withinGrace": False,
    }
    [finding] = unforecast_findings([row], NOW)
    assert finding.kind == PAST_GRACE
    assert "fails every publish" in finding.detail


def test_a_target_with_no_registration_time_counts_as_past_grace() -> None:
    row = {"dataPointId": "legacy", "registeredAt": None, "withinGrace": False}
    [finding] = unforecast_findings([row], NOW)
    assert finding.kind == PAST_GRACE


@pytest.mark.skipif(shutil.which("bun") is None, reason="needs bun on PATH")
@pytest.mark.parametrize(
    "instant", ["2026-07-01T00:00:00Z", "2026-11-02T00:00:00Z", "2030-01-01T00:00:00Z"]
)
def test_the_site_rule_reports_grace_as_registeredat_implies(instant: str) -> None:
    moment = dt.datetime.fromisoformat(instant.replace("Z", "+00:00"))
    rows = docket_health.unforecast_rows(moment)
    grace = dt.timedelta(days=docket_health.ORPHAN_GRACE_DAYS)
    for row in rows:
        assert isinstance(row["dataPointId"], str)
        assert isinstance(row["withinGrace"], bool)
        if row["withinGrace"]:
            registered = dt.datetime.fromisoformat(
                row["registeredAt"].replace("Z", "+00:00")
            )
            assert dt.timedelta(0) <= moment - registered <= grace


@pytest.mark.skipif(shutil.which("bun") is None, reason="needs bun on PATH")
def test_the_site_rule_refuses_an_unreadable_instant() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run(
            ["bun", str(ROOT / "scripts" / "dump_unforecast_targets.ts"), "soon"],
            capture_output=True,
            cwd=ROOT,
            timeout=300,
            check=True,
        )


def test_the_fingerprint_holds_while_only_day_counts_move() -> None:
    today = [Finding(CALENDAR, "a", "ends in 20 days"), Finding(STALL, "b", "11 days")]
    tomorrow = [Finding(STALL, "b", "12 days"), Finding(CALENDAR, "a", "ends in 19")]
    assert fingerprint(today) == fingerprint(tomorrow)
    assert fingerprint(today) != fingerprint(today[:1])


def test_the_issue_carries_its_marker_and_says_what_to_do() -> None:
    findings = [
        Finding(STALL, "records/targets", "Fourteen days."),
        Finding(PAST_GRACE, "x.past", "Past."),
        Finding(IN_GRACE, "x.grace", "Inside."),
        Finding(CALENDAR, "x.calendar", "Ends."),
    ]
    body = render_issue(findings, NOW, "https://github.example/run/1")
    assert body.startswith(f"<!-- docket-health:{fingerprint(findings)} -->\n")
    assert "https://github.example/run/1" in body
    for heading, action in (
        ("## Registrations stopped", "`register` log"),
        ("## Past grace with no forecast", "expired-unforecast-registrations.ts"),
        ("## Inside grace with no forecast", "gh run rerun <run id> --failed"),
        ("## Release calendars running out", "Never infer a date from cadence"),
    ):
        assert heading in body
        assert action in body


def test_the_issue_leaves_out_sections_with_nothing_to_report() -> None:
    body = render_issue([Finding(CALENDAR, "x", "Ends.")], NOW, "https://run")
    assert "## Registrations stopped" not in body
    assert "## Release calendars running out" in body


def _workflow() -> dict:
    parsed = yaml.safe_load((ROOT / WORKFLOW_PATH).read_text())
    assert isinstance(parsed, dict)
    return parsed


def test_the_health_workflow_cannot_write_records() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read", "issues": "write"}
    assert WORKFLOW_PATH not in provenance.ALLOWED_WORKFLOWS
    job = workflow["jobs"]["check"]
    assert "permissions" not in job
    source = (ROOT / WORKFLOW_PATH).read_text()
    assert "git push" not in source
    assert "attest" not in job
    checkout = next(
        step for step in job["steps"] if "actions/checkout" in step.get("uses", "")
    )
    assert checkout["with"] == {"ref": "main", "persist-credentials": False}
    assert workflow["concurrency"]["group"] != "docket-writers"


def test_the_health_workflow_runs_daily_and_on_dispatch() -> None:
    workflow = _workflow()
    trigger = workflow.get("on", workflow.get(True))
    assert trigger["schedule"] == [{"cron": "15 12 * * *"}]
    assert "workflow_dispatch" in trigger


def test_a_check_that_cannot_run_raises_its_own_alert() -> None:
    steps = _workflow()["jobs"]["check"]["steps"]
    alert = next(step for step in steps if step.get("if") == "failure()")
    assert "could not run" in alert["run"]
    assert 'if [ -f "$report" ]' in alert["run"]
