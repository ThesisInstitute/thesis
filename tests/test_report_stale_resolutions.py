from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import report_stale_resolutions as stale_report  # noqa: E402


def _log(*cells: tuple[str, str, str, str]) -> dict:
    """Build a log from (slug, ref, resolutionDate, status) tuples."""
    return {
        "schemaVersion": "thesis_log_v2",
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": slug,
                "resolutionDate": due,
            }
            for slug, _ref, due, _status in cells
        ],
        "resolutionLinks": [
            {"forecastSlug": slug, "targetFactRef": ref, "status": status}
            for slug, ref, _due, status in cells
        ],
    }


TODAY = dt.date(2026, 7, 31)


def test_matured_pending_cells_are_reported_with_their_age() -> None:
    log = _log(
        ("a", "bls.ces.aerospace.june_2026.first_print", "2026-07-02", "pending"),
        ("b", "ons.labour.claimant_count.2026_06.first_print", "2026-07-14", "pending"),
    )
    stale = stale_report.stale_pending(log, TODAY, grace_days=7)
    assert [row["daysOverdue"] for row in stale] == [29, 17]
    # Sorted oldest-first so triage starts with the worst.
    assert stale[0]["ref"].startswith("bls.ces.aerospace")
    assert stale[0]["agency"] == "bls"


def test_resolved_and_not_yet_due_cells_are_not_stale() -> None:
    log = _log(
        # Resolved: not pending, however old.
        ("a", "bls.x.2026-01.first_print", "2026-01-05", "resolved"),
        # Pending but not yet due.
        ("b", "bls.y.2026-09.first_print", "2026-09-05", "pending"),
        # Pending, due today.
        ("c", "bls.z.2026-07.first_print", "2026-07-31", "pending"),
    )
    assert stale_report.stale_pending(log, TODAY, grace_days=7) == []


def test_grace_window_covers_routine_agency_slippage() -> None:
    """A release a few days late must not alarm; a fortnight late must."""
    log = _log(("a", "bea.pce.2026-06.first_print", "2026-07-26", "pending"))
    assert stale_report.stale_pending(log, TODAY, grace_days=7) == []  # 5 days

    log = _log(("a", "bea.pce.2026-06.first_print", "2026-07-16", "pending"))
    stale = stale_report.stale_pending(log, TODAY, grace_days=7)  # 15 days
    assert len(stale) == 1 and stale[0]["daysOverdue"] == 15


def test_boundary_is_strictly_beyond_the_grace_window() -> None:
    exactly = _log(("a", "bls.x.2026-06.first_print", "2026-07-24", "pending"))
    assert stale_report.stale_pending(exactly, TODAY, grace_days=7) == []
    beyond = _log(("a", "bls.x.2026-06.first_print", "2026-07-23", "pending"))
    assert len(stale_report.stale_pending(beyond, TODAY, grace_days=7)) == 1


def test_cells_without_a_resolution_date_are_left_to_the_registration_gates() -> None:
    log = {
        "schemaVersion": "thesis_log_v2",
        "entries": [{"kind": "prediction_recorded", "forecastSlug": "a"}],
        "resolutionLinks": [
            {"forecastSlug": "a", "targetFactRef": "bls.x", "status": "pending"}
        ],
    }
    assert stale_report.stale_pending(log, TODAY, grace_days=7) == []


def test_an_unhydrated_v3_manifest_never_reports_a_false_all_clear() -> None:
    """The live-caught failure: log.json alone carries no `entries`.

    Every maturity test needs the forecast's resolutionDate, so an
    unhydrated log would skip all 598 pending links and print OK.
    """

    unhydrated = {
        "schemaVersion": "thesis_log_v3",
        "resolutionLinks": [
            {
                "forecastSlug": "a",
                "targetFactRef": "bls.x.2026-06.first_print",
                "status": "pending",
            }
        ],
    }
    with pytest.raises(stale_report.StaleReportError, match="not hydrated"):
        stale_report.stale_pending(unhydrated, TODAY, grace_days=7)


def test_a_fully_resolved_log_without_entries_is_a_genuine_all_clear() -> None:
    """The guard must key on PENDING links, not on entries being absent."""

    log = {
        "schemaVersion": "thesis_log_v2",
        "resolutionLinks": [
            {"forecastSlug": "a", "targetFactRef": "bls.x", "status": "resolved"}
        ],
    }
    assert stale_report.stale_pending(log, TODAY, grace_days=7) == []


def test_malformed_resolution_date_does_not_crash_the_report() -> None:
    log = _log(("a", "bls.x.2026-06.first_print", "not-a-date", "pending"))
    assert stale_report.stale_pending(log, TODAY, grace_days=7) == []


def test_a_log_without_resolution_links_fails_loudly() -> None:
    with pytest.raises(stale_report.StaleReportError, match="resolutionLinks"):
        stale_report.stale_pending({"entries": []}, TODAY, grace_days=7)


def test_age_buckets_partition_the_backlog() -> None:
    stale = [
        {"daysOverdue": 5},
        {"daysOverdue": 20},
        {"daysOverdue": 45},
        {"daysOverdue": 90},
    ]
    assert stale_report.age_buckets(stale) == {
        "<=14d": 1,
        "15-30d": 1,
        "31-60d": 1,
        ">60d": 1,
    }


def test_render_states_the_all_clear_and_the_backlog() -> None:
    assert "stale resolutions OK" in stale_report.render([], 12, 7)
    text = stale_report.render(
        [
            {
                "ref": "bls.ces.aerospace.june_2026.first_print",
                "slug": "a",
                "resolutionDate": "2026-07-02",
                "daysOverdue": 29,
                "agency": "bls",
            }
        ],
        12,
        7,
    )
    assert "1 of 12 pending" in text
    assert "29d overdue" in text
    assert "bls=1" in text


def test_cli_reports_and_can_fail_closed_for_alarms(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_file = tmp_path / "log.json"
    log_file.write_text(
        json.dumps(
            _log(
                (
                    "a",
                    "bls.ces.aerospace.june_2026.first_print",
                    "2026-07-02",
                    "pending",
                )
            )
        )
    )
    base = [
        "report_stale_resolutions.py",
        "--log-file", str(log_file),
        "--today", "2026-07-31",
    ]

    # Reporting alone never fails a build: a late agency is not a bad build.
    monkeypatch.setattr(sys, "argv", base)
    assert stale_report.main() == 0
    assert "29d overdue" in capsys.readouterr().out

    # An alarm lane opts in to a nonzero exit.
    monkeypatch.setattr(sys, "argv", base + ["--fail-on-stale"])
    assert stale_report.main() == 1
    capsys.readouterr()

    # JSON for machine consumers.
    monkeypatch.setattr(sys, "argv", base + ["--json"])
    assert stale_report.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["graceDays"] == 7
    assert payload["stale"][0]["daysOverdue"] == 29
