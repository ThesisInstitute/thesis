"""Colorado DOR General Fund Net Collections workbook: is a month's first
print still the one being served?

Official fixture (``tests/fixtures/co_dor``, see its README): the workbook
DOR published in September 2026, byte for byte. Synthetic workbooks
(``tests/co_fixtures.py``) vary one fact at a time.
"""

from __future__ import annotations

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
from co_fixtures import dor_figures, dor_workbook, shift  # noqa: E402

FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "co_dor"
    / "general_fund_net_collections_published_2026-09.xlsx"
)
OFFICIAL = FIXTURE.read_bytes()
REF = "co.dor.individual_income_tax.net_collections.2026_07.first_print"


def test_official_workbook_is_the_september_2026_publication() -> None:
    assert hashlib.sha256(OFFICIAL).hexdigest() == (
        "476df20fbc29e80bb95e4eff369cd3f2d01cb403b422a192b5c969ee1ce05f19"
    )
    workbook = co_dor.read_collections(OFFICIAL)
    assert (workbook.newest, workbook.months[-1]) == ("2026-08", "2019-07")
    assert len(workbook.months) == 86
    assert workbook.publish_period == "2026-09"


def test_official_workbook_no_longer_first_prints_july_2026() -> None:
    """The forecast's month is one column behind the newest: whatever DOR
    first published for July 2026 has been replaced by this file."""
    workbook = co_dor.read_collections(OFFICIAL)
    assert co_dor.first_print_status(workbook, "2026-08") == "first_print"
    assert co_dor.first_print_status(workbook, "2026-07") == "overwritten"
    assert co_dor.first_print_status(workbook, "2019-07") == "overwritten"
    assert co_dor.first_print_status(workbook, "2026-09") == "not_yet_published"
    with pytest.raises(co_dor.CoDorError, match="not YYYY-MM"):
        co_dor.first_print_status(workbook, "2026_07")
    # What this publication prints for July 2026, in $ thousands. It is the
    # row the forecast names, and it is not known to be the first print.
    july = workbook.net_individual_income("2026-07")
    assert (july.net, july.gross, july.refunds, july.adjustments) == (
        984764,
        1054468,
        71719,
        2015,
    )
    assert july.components == (981204, 31177, 42087)


def test_official_workbook_rows_add_up_in_every_month() -> None:
    """Net is gross plus the listed adjustments less refunds, exactly, in all
    86 months; the three separately rounded components are within one
    thousand of gross. That is what pins the row the leg reads."""
    workbook = co_dor.read_collections(OFFICIAL)
    off_by_one = 0
    for period in workbook.months:
        figure = workbook.net_individual_income(period)
        co_dor.check_identities(figure)
        assert figure.gross + figure.adjustments - figure.refunds == figure.net
        off_by_one += sum(figure.components) != figure.gross
    assert off_by_one == 28


def test_the_leg_reports_the_official_workbook_as_a_missed_first_print() -> None:
    line = resolve_pending.co_dor_verdict(REF, "2026-07", OFFICIAL)
    assert line.startswith(f"  FIRST-PRINT WINDOW MISSED (refusing): {REF} — ")
    assert "newest month is August 2026 (publish date September 2026)" in line
    assert "July 2026 figure cannot be shown to be the first print" in line
    # Never the figure itself: the leg records nothing and prints no value.
    assert "984" not in line


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
    ],
    ids=["challenge-page", "renamed-sheet", "renamed-row", "row-replaced"],
)
def test_a_restructured_workbook_is_refused(raw: bytes, refusal: str) -> None:
    with pytest.raises(co_dor.CoDorError, match=refusal):
        co_dor.read_collections(raw)
    line = resolve_pending.co_dor_verdict(REF, "2026-07", raw)
    assert line.startswith(f"  CO DOR PARSE REFUSAL (refusing): {REF} — ")


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
        assert "CO DOR PARSE REFUSAL (refusing)" in resolve_pending.co_dor_verdict(
            REF, "2026-07", raw
        )
    # One thousand of rounding between the components and gross is how DOR
    # prints 28 of its 86 months; it is not a restructuring.
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


def test_the_leg_prints_one_verdict_per_state_of_the_first_print() -> None:
    raw = dor_workbook("2026-08")
    verdict = resolve_pending.co_dor_verdict
    assert verdict(REF, "2026-09", raw) == (
        f"  not yet published (deferring): {REF} — the workbook's newest month "
        "is August 2026 (publish date September 2026)"
    )
    assert verdict(REF, "2026-08", raw).startswith(
        f"  CO DOR ADAPTER UNVERIFIED (refusing): {REF} — August 2026 is the "
        "workbook's newest month"
    )
    assert verdict(REF, "2026-07", raw).startswith(
        f"  FIRST-PRINT WINDOW MISSED (refusing): {REF} — "
    )
    unstated = dor_workbook("2026-08", publish=None)
    assert "(no publish date)" in verdict(REF, "2026-07", unstated)


# --- properties --------------------------------------------------------------

_HEADS = (
    "  not yet published (deferring): ",
    "  FIRST-PRINT WINDOW MISSED (refusing): ",
    "  CO DOR ADAPTER UNVERIFIED (refusing): ",
)


@settings(max_examples=120, deadline=None)
@given(
    newest=st.integers(2019 * 12 + 6, 2040 * 12),
    count=st.integers(1, 12),
    offset=st.integers(-15, 15),
)
def test_every_month_is_in_exactly_one_state_and_none_records_a_value(
    newest, count, offset
) -> None:
    """Trichotomy on the newest month, and the leg never resolves."""
    newest_period = f"{newest // 12:04d}-{newest % 12 + 1:02d}"
    asked = shift(newest_period, offset)
    raw = dor_workbook(newest_period, count)
    workbook = co_dor.read_collections(raw)
    status = co_dor.first_print_status(workbook, asked)
    assert status == (
        "first_print"
        if offset == 0
        else "not_yet_published"
        if offset > 0
        else "overwritten"
    )
    line = resolve_pending.co_dor_verdict(REF, asked, raw)
    in_range = -count < offset
    if in_range:
        assert line.startswith(_HEADS[(offset <= 0) + (offset == 0)] + REF + " — ")
        # The status page reprints at most 240 characters of the detail.
        assert len(line.split(" — ", 1)[1]) <= 240
    else:
        # Older than the workbook's first column: nothing to judge it by.
        assert line.startswith(f"  CO DOR PARSE REFUSAL (refusing): {REF} — ")
    assert not line.lstrip().startswith("resolve")
