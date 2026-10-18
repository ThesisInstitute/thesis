"""The weekly claims leg records a first print or nothing.

DOL revises a week's figure in the release that first prints the following
reference week. The claims leg reads the ALFRED vintage dated the forecast's
published resolutionDate, so a resolutionDate a release or more late returns
the revised figure. Registered windows drifted late from 2026-08-12
(docs/weekly-claims-release-window-drift.md on the companion change), and the
append-only ledger cannot take a wrong observation back.

The ALFRED rows below are the last rows of the real ALFRED responses for ICSA
at vintages 2026-09-03, 2026-09-09, 2026-09-10 and 2026-09-11, fetched
2026-09-20, trimmed of earlier history. The two tests on future dates build
SYNTHETIC rows; their values are placeholders, not DOL figures.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolution_status  # noqa: E402
import resolve_pending  # noqa: E402

REF = "us.dol.initial_claims.sa.week_2026-08-29"
WEEK = "2026-08-29"
ALFRED = {
    # First print of week 2026-08-29: 206,000.
    "2026-09-03": "2026-08-15,207000\n2026-08-22,204000\n2026-08-29,206000\n",
    # Six days later, the day before DOL's next release: still the first print.
    "2026-09-09": "2026-08-15,207000\n2026-08-22,204000\n2026-08-29,206000\n",
    # The next release: week 2026-09-05 appears and 2026-08-29 becomes 207,000.
    "2026-09-10": "2026-08-22,204000\n2026-08-29,207000\n2026-09-05,206000\n",
    "2026-09-11": "2026-08-22,204000\n2026-08-29,207000\n2026-09-05,206000\n",
}


def alfred_csv(series_id: str, vintage: str) -> bytes:
    header = f"observation_date,{series_id}_{vintage.replace('-', '')}\n"
    return (header + ALFRED[vintage]).encode()


@pytest.fixture
def alfred(monkeypatch):
    calls: list[tuple[str, str, str]] = []

    def fake(series_id: str, week: str, vintage: str):
        calls.append((series_id, week, vintage))
        raw = alfred_csv(series_id, vintage)
        rows = resolve_pending.parse_fred_vintage_csv(raw, series_id, vintage)
        return rows.get(week), raw, f"https://alfred.example/{vintage}", "t"

    monkeypatch.setattr(resolve_pending, "fred_advance_value", fake)
    return calls


@pytest.mark.parametrize("vintage", ["2026-09-03", "2026-09-09"])
def test_first_print_vintage_resolves(alfred, vintage, capsys) -> None:
    fetched = resolve_pending.resolve_claims_ref(
        REF, WEEK, "initial", vintage, dt.date(2026, 9, 20)
    )

    assert fetched is not None
    row, series_id, recorded_vintage, raw, _retrieved_at, kind = fetched
    assert row["value"] == 206.0
    assert row["observed_at"] == vintage
    assert (series_id, recorded_vintage, kind) == ("ICSA", vintage, "csv")
    assert raw == alfred_csv("ICSA", vintage)
    assert "resolve" in capsys.readouterr().out


@pytest.mark.parametrize("vintage", ["2026-09-10", "2026-09-11"])
def test_a_later_release_is_refused_and_left_pending(alfred, vintage, capsys) -> None:
    # 2026-09-11 is the live case: the forecast's published resolutionDate,
    # eight days after DOL's 2026-09-03 print. Unguarded, 207.0 is recorded.
    fetched = resolve_pending.resolve_claims_ref(
        REF, WEEK, "initial", vintage, dt.date(2026, 9, 20)
    )

    assert fetched is None
    out = capsys.readouterr().out
    assert f"FIRST-PRINT WINDOW MISSED (refusing): {REF}" in out
    assert "left pending" in out
    assert "resolve us.dol" not in out
    # The status surface must name the refusal, not report the target silent.
    targets, _summary = resolution_status.parse_resolver_log(out, {REF})
    assert targets[REF]["state"] == "refused"
    assert targets[REF]["code"] == "FIRST_PRINT_WINDOW_MISSED"
    assert "left pending" in targets[REF]["detail"]


def test_guard_reads_the_vintage_not_an_offset_from_the_week() -> None:
    # Holiday-shift fixture: a Wednesday print holding only its own week is a
    # first print whatever its distance from the reference week.
    # SYNTHETIC values: 2026-11-25 has not happened.
    raw = b"observation_date,ICSA_20261125\n2026-11-14,210000\n2026-11-21,215000\n"
    assert not resolve_pending.claims_vintage_holds_next_week(
        raw, "ICSA", "2026-11-21", dt.date(2026, 11, 25)
    )
    # The same bytes are a later release for the week before.
    assert resolve_pending.claims_vintage_holds_next_week(
        raw, "ICSA", "2026-11-14", dt.date(2026, 11, 25)
    )


def test_continued_claims_use_the_same_rule() -> None:
    # SYNTHETIC values: 2026-10-09 has not happened.
    raw = b"observation_date,CCSA_20261009\n2026-09-19,1761000\n2026-09-26,1755000\n"
    assert resolve_pending.claims_vintage_holds_next_week(
        raw, "CCSA", "2026-09-19", dt.date(2026, 10, 9)
    )
    assert not resolve_pending.claims_vintage_holds_next_week(
        raw, "CCSA", "2026-09-26", dt.date(2026, 10, 9)
    )


def test_unreached_and_unpublished_cells_still_wait(alfred, capsys) -> None:
    assert (
        resolve_pending.resolve_claims_ref(
            REF, WEEK, "initial", "2026-09-11", dt.date(2026, 9, 10)
        )
        is None
    )
    assert alfred == []
    assert "not reached" in capsys.readouterr().out

    assert (
        resolve_pending.resolve_claims_ref(
            "us.dol.initial_claims.sa.week_2026-09-12",
            "2026-09-12",
            "initial",
            "2026-09-11",
            dt.date(2026, 9, 20),
        )
        is None
    )
    assert "not yet published" in capsys.readouterr().out


def test_unrelated_malformed_history_does_not_raise() -> None:
    # SYNTHETIC: a malformed value in an unrelated historical row. The guard
    # reads only the following week's cell, as fred_advance_value reads only
    # the target's.
    raw = (
        b"observation_date,ICSA_20260903\n2026-08-22,not-a-number\n2026-08-29,206000\n"
    )
    assert not resolve_pending.claims_vintage_holds_next_week(
        raw, "ICSA", "2026-08-29", dt.date(2026, 9, 3)
    )
    assert resolve_pending.claims_vintage_holds_next_week(
        raw + b"2026-09-05,1\n", "ICSA", "2026-08-29", dt.date(2026, 9, 3)
    )
