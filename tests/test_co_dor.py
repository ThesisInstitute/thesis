"""Colorado DOR General Fund Net Collections workbook: the reader, and the
one line the resolver's DOR leg prints. The leg never records a value.

Official fixture (``tests/fixtures/co_dor``, see its README): the workbook
downloaded 2026-10-09, whose publish-date line says September 2026, byte for
byte. Synthetic workbooks (``tests/co_fixtures.py``) vary one fact at a time.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import pathlib
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import co_dor  # noqa: E402
import resolve_pending  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from co_fixtures import (  # noqa: E402
    corrupt_member_crc,
    dor_figures,
    dor_workbook,
    shift,
)

FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "co_dor"
    / "general_fund_net_collections_published_2026-09.xlsx"
)
OFFICIAL = FIXTURE.read_bytes()
REF = "co.dor.individual_income_tax.net_collections.2026_07.first_print"
# The Last-Modified the download carried on 2026-10-09, and the cell's
# resolution date.
OFFICIAL_HEADERS = {"last-modified": "Mon, 28 Sep 2026 21:09:16 GMT"}
RESOLUTION_DAY = dt.date(2026, 8, 31)
BEFORE = {"last-modified": "Fri, 28 Aug 2026 16:00:00 GMT"}


def verdict(
    period: str,
    raw: bytes,
    headers: dict[str, str] | None = None,
    resolution_day: dt.date = RESOLUTION_DAY,
) -> str:
    return resolve_pending.co_dor_verdict(
        REF,
        period,
        raw,
        OFFICIAL_HEADERS if headers is None else headers,
        resolution_day,
    )


# --- the official workbook ---------------------------------------------------


def test_official_workbook_is_the_download_of_2026_10_09() -> None:
    assert hashlib.sha256(OFFICIAL).hexdigest() == (
        "476df20fbc29e80bb95e4eff369cd3f2d01cb403b422a192b5c969ee1ce05f19"
    )
    workbook = co_dor.read_collections(OFFICIAL)
    assert (workbook.newest, workbook.months[-1]) == ("2026-08", "2019-07")
    assert len(workbook.months) == 86
    assert workbook.publish_period == "2026-09"


def test_official_workbook_prints_these_july_2026_lines() -> None:
    """What this download prints for July 2026, in $ thousands. It is the row
    the forecast names; when DOR first published it is not established."""
    july = co_dor.read_collections(OFFICIAL).net_individual_income("2026-07")
    assert (july.net, july.gross, july.refunds, july.adjustments) == (
        984764,
        1054468,
        71719,
        2015,
    )
    assert july.components == (981204, 31177, 42087)


def test_official_workbook_rows_add_up_in_every_month() -> None:
    """Net is gross plus the listed adjustments less refunds, exactly, in all
    86 months. The component sum differs from gross by one thousand in 28 of
    them and by nothing in the rest; ``check_identities`` allows one."""
    workbook = co_dor.read_collections(OFFICIAL)
    off_by_one = 0
    for period in workbook.months:
        figure = workbook.net_individual_income(period)
        co_dor.check_identities(figure)
        assert figure.gross + figure.adjustments - figure.refunds == figure.net
        difference = abs(sum(figure.components) - figure.gross)
        assert difference <= 1
        off_by_one += difference == 1
    assert off_by_one == 28


def test_the_leg_refuses_july_2026_because_the_file_changed_after_its_date() -> None:
    """The download's Last-Modified (2026-09-28) is after the cell's
    resolution date (2026-08-31), so the bytes a capture on that date would
    have read cannot be shown to be these."""
    line = verdict("2026-07", OFFICIAL)
    assert line == (
        f"  FIRST-PRINT WINDOW MISSED (refusing): {REF} — the workbook was last "
        "modified 2026-09-28 21:09 UTC, after the cell's resolution date "
        "2026-08-31; the bytes a capture on 2026-08-31 would have read cannot "
        "be shown to be these"
    )
    # Never the figure itself: the leg records nothing and prints no value.
    assert "984" not in line


def test_with_a_header_before_the_resolution_date_it_still_records_nothing() -> None:
    line = verdict("2026-07", OFFICIAL, BEFORE)
    assert line.startswith(f"  CO DOR ADAPTER UNVERIFIED (refusing): {REF} — ")
    assert "no later than the cell's resolution date 2026-08-31" in line
    assert "records no value" in line


# --- synthetic workbooks -----------------------------------------------------


def test_synthetic_workbook_reads_like_the_official_one() -> None:
    workbook = co_dor.read_collections(dor_workbook("2026-08", 4))
    assert workbook.months == ("2026-08", "2026-07", "2026-06", "2026-05")
    assert workbook.publish_period == "2026-09"
    figures = dor_figures(1)
    july = workbook.net_individual_income("2026-07")
    assert (july.net, july.gross, july.refunds) == (
        figures["net"],
        figures["gross"],
        figures["refunds"],
    )
    co_dor.check_identities(july)
    with pytest.raises(co_dor.CoDorError, match="no 2019-01 column"):
        workbook.net_individual_income("2019-01")
    assert (
        co_dor.read_collections(dor_workbook("2026-08", publish=None)).publish_period
        is None
    )


@pytest.mark.parametrize(
    ("raw", "refusal"),
    [
        (b"<html>Just a moment...</html>", "not an OOXML workbook"),
        (dor_workbook("2026-08", sheet_name="Sheet1"), "exactly one 'Report' sheet"),
        (
            dor_workbook("2026-08", net_label="Total Net Corporate Income"),
            "exactly one 'Total Net Individual Income' cell .* found 0",
        ),
        (
            dor_workbook("2026-08", net_label="Fiduciary Estimated Payments"),
            "exactly one 'Total Net Individual Income' cell .* found 0",
        ),
        (corrupt_member_crc(OFFICIAL, "xl/workbook.xml"), "BadZipFile"),
        (OFFICIAL[: len(OFFICIAL) // 2], "collections workbook"),
    ],
    ids=[
        "challenge-page",
        "renamed-sheet",
        "renamed-row",
        "row-replaced",
        "bad-crc",
        "truncated",
    ],
)
def test_a_restructured_or_damaged_workbook_is_refused(
    raw: bytes, refusal: str
) -> None:
    """Every failure is a ``CoDorError``, and the leg turns it into one
    refusal line instead of an exception that would stop the run."""
    with pytest.raises(co_dor.CoDorError, match=refusal):
        co_dor.read_collections(raw)
    assert verdict("2026-07", raw).startswith(
        f"  CO DOR PARSE REFUSAL (refusing): {REF} — "
    )


@pytest.mark.parametrize(
    "months",
    [
        ["2026-08", "2026-06", "2026-05"],  # a month is missing
        ["2026-07", "2026-08"],  # oldest first
        ["2026-08", "2026-08"],  # a month twice
    ],
    ids=["gap", "oldest-first", "repeated"],
)
def test_a_header_whose_months_do_not_run_newest_first_is_refused(months) -> None:
    """The newest month is read off the first column, so the order is
    checked, not assumed."""
    raw = dor_workbook("2026-08", months=months)
    with pytest.raises(co_dor.CoDorError, match="not consecutive, newest first"):
        co_dor.read_collections(raw)


def test_components_that_are_not_the_three_rows_above_gross_are_refused() -> None:
    raw = dor_workbook("2026-08", cash_row=3)
    with pytest.raises(co_dor.CoDorError, match="not the three rows above the gross"):
        co_dor.read_collections(raw)


def test_a_month_whose_lines_do_not_add_up_is_refused() -> None:
    figures = dor_figures(1)
    for key, delta, refusal in [
        ("net", 1, "not the net line"),
        ("refunds", -1, "not the net line"),
        ("adjustment_1", 1, "not the net line"),
        ("withholding", 2, "not the gross line"),
    ]:
        raw = dor_workbook(
            "2026-08", overrides={"2026-07": {key: figures[key] + delta}}
        )
        july = co_dor.read_collections(raw).net_individual_income("2026-07")
        with pytest.raises(co_dor.CoDorError, match=refusal):
            co_dor.check_identities(july)
        # The leg checks the lines only where the custody rule would allow a
        # read, so the header here is before the resolution date.
        assert verdict("2026-07", raw, BEFORE).startswith(
            f"  CO DOR PARSE REFUSAL (refusing): {REF} — "
        )
    # A component sum one thousand off gross, as in 28 official months, passes.
    rounded = dor_workbook(
        "2026-08",
        overrides={"2026-07": {"withholding": figures["withholding"] + 1}},
    )
    co_dor.check_identities(
        co_dor.read_collections(rounded).net_individual_income("2026-07")
    )


def test_a_month_holding_text_is_refused_only_when_it_is_asked_for() -> None:
    raw = dor_workbook("2026-08", overrides={"2026-06": {"net": "n/a"}})
    workbook = co_dor.read_collections(raw)
    co_dor.check_identities(workbook.net_individual_income("2026-07"))
    with pytest.raises(co_dor.CoDorError, match="2026-06: .* holds 'n/a'"):
        workbook.net_individual_income("2026-06")


def test_the_leg_prints_one_line_for_each_state() -> None:
    raw = dor_workbook("2026-08")
    assert verdict("2026-09", raw) == (
        f"  MONTH NOT IN WORKBOOK (deferring): {REF} — the workbook's newest "
        "month is August 2026 (its publish-date line says September 2026)"
    )
    assert verdict("2026-07", raw).startswith(
        f"  FIRST-PRINT WINDOW MISSED (refusing): {REF} — the workbook was last "
        "modified 2026-09-28 21:09 UTC"
    )
    assert verdict("2026-07", raw, BEFORE).startswith(
        f"  CO DOR ADAPTER UNVERIFIED (refusing): {REF} — "
    )
    assert verdict("2026-07", raw, {}) == (
        f"  CO DOR CUSTODY UNKNOWN (refusing): {REF} — the workbook response "
        "carries no Last-Modified header"
    )
    assert verdict("2026-01", raw) == (
        f"  CO DOR PARSE REFUSAL (refusing): {REF} — the workbook has no 2026-01 "
        "column (its oldest month is 2026-03)"
    )
    unstated = dor_workbook("2026-08", publish=None)
    assert "(it has no publish-date line)" in verdict("2026-09", unstated)


# --- properties --------------------------------------------------------------


@settings(max_examples=150, deadline=None)
@given(
    newest=st.integers(2019 * 12 + 6, 2040 * 12),
    count=st.integers(1, 12),
    offset=st.integers(-15, 15),
    hours=st.integers(-24 * 60, 24 * 60),
)
def test_every_month_gets_exactly_one_line_and_none_records_a_value(
    newest, count, offset, hours
) -> None:
    """The line is decided by where the month falls against the workbook's
    columns and by the header against the end of the resolution date (UTC);
    no input yields a ``resolve`` line."""
    newest_period = f"{newest // 12:04d}-{newest % 12 + 1:02d}"
    asked = shift(newest_period, offset)
    resolution_day = dt.date(newest // 12, newest % 12 + 1, 15)
    end = dt.datetime.combine(
        resolution_day + dt.timedelta(days=1), dt.time(), tzinfo=dt.timezone.utc
    )
    modified = end + dt.timedelta(hours=hours) - dt.timedelta(seconds=1)
    headers = {"last-modified": modified.strftime("%a, %d %b %Y %H:%M:%S GMT")}
    line = verdict(asked, dor_workbook(newest_period, count), headers, resolution_day)
    if offset > 0:
        head = "MONTH NOT IN WORKBOOK (deferring)"
    elif offset <= -count:
        head = "CO DOR PARSE REFUSAL (refusing)"
    elif modified >= end:
        head = "FIRST-PRINT WINDOW MISSED (refusing)"
    else:
        head = "CO DOR ADAPTER UNVERIFIED (refusing)"
    assert line.startswith(f"  {head}: {REF} — "), line
    assert not line.lstrip().startswith("resolve")
