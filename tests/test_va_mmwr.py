"""VA MMWR workbook reader and landing-page mapping: label-anchored, fail-closed.

The synthetic workbook (``tests/va_mmwr_fixtures.py``) mirrors the official
``Transformation`` sheet layout; the official files are ~3 MB each and stay
out of the repo. The landing-page excerpt is cut from the live Detailed Claims Data page
(2026-08-23): report-date labels linking Saturday-named workbooks.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import va_mmwr  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from va_mmwr_fixtures import build_workbook  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "va_mmwr"
LANDING = (FIXTURES / "detailed_claims_data_excerpt.html").read_bytes()


def test_landing_page_binds_report_date_label_to_saturday_workbook() -> None:
    href = va_mmwr.landing_workbook_href(LANDING, dt.date(2026, 7, 13))
    assert href == "/REPORTS/mmwr/2026/MMWR-07-11-2026.xlsx"
    assert va_mmwr.workbook_file_date(href) == dt.date(2026, 7, 11)
    va_mmwr.require_file_date_near_report(dt.date(2026, 7, 11), dt.date(2026, 7, 13))
    assert va_mmwr.workbook_url(href) == (
        "https://www.benefits.va.gov/REPORTS/mmwr/2026/MMWR-07-11-2026.xlsx"
    )
    # Not yet listed: refuse rather than guess a file name from cadence.
    with pytest.raises(va_mmwr.VaMmwrError, match="exactly one report link"):
        va_mmwr.landing_workbook_href(LANDING, dt.date(2026, 9, 14))
    with pytest.raises(va_mmwr.VaMmwrError, match="days before report"):
        va_mmwr.require_file_date_near_report(dt.date(2026, 7, 4), dt.date(2026, 7, 13))
    with pytest.raises(va_mmwr.VaMmwrError, match="not an MMWR workbook path"):
        va_mmwr.landing_workbook_href(
            LANDING.replace(
                b'href="/REPORTS/mmwr/2026/MMWR-07-11-2026.xlsx#"',
                b'href="https://example.com/MMWR-07-11-2026.xlsx"',
            ),
            dt.date(2026, 7, 13),
        )


def test_posting_gate_accepts_report_week_and_refuses_reposts() -> None:
    file_date, report_date = dt.date(2026, 7, 11), dt.date(2026, 7, 13)
    modified, refusal = va_mmwr.posting_gate(
        "Mon, 13 Jul 2026 17:30:32 GMT",
        file_date=file_date,
        report_date=report_date,
        window_days=7,
    )
    assert refusal is None and modified.date() == report_date
    # Holiday week: the 07/06 report was modified on the Tuesday. Still in.
    assert (
        va_mmwr.posting_gate(
            "Tue, 07 Jul 2026 19:33:23 GMT",
            file_date=dt.date(2026, 7, 4),
            report_date=dt.date(2026, 7, 6),
            window_days=7,
        )[1]
        is None
    )
    assert (
        "re-post"
        in va_mmwr.posting_gate(
            "Tue, 01 Sep 2026 17:30:32 GMT",
            file_date=file_date,
            report_date=report_date,
            window_days=7,
        )[1]
    )
    assert (
        "no Last-Modified"
        in va_mmwr.posting_gate(
            None, file_date=file_date, report_date=report_date, window_days=7
        )[1]
    )
    assert (
        "precedes"
        in va_mmwr.posting_gate(
            "Fri, 10 Jul 2026 00:00:00 GMT",
            file_date=file_date,
            report_date=report_date,
            window_days=7,
        )[1]
    )


def test_rating_bundle_reader_uses_labels_and_cached_formula_values() -> None:
    reading = va_mmwr.read_rating_bundle_pending(
        build_workbook(), expected_through=dt.date(2026, 7, 11)
    )
    assert reading.pending == 600_878
    assert reading.pending_over_125 == 69_481
    assert reading.cell == "J5"
    assert reading.reporting_through == dt.date(2026, 7, 11)


def test_rating_bundle_reader_fails_closed() -> None:
    through = dt.date(2026, 7, 11)
    with pytest.raises(va_mmwr.VaMmwrError, match="reports through"):
        va_mmwr.read_rating_bundle_pending(
            build_workbook(through="Reporting through July 18, 2026"),
            expected_through=through,
        )
    with pytest.raises(va_mmwr.VaMmwrError, match="cached percent"):
        va_mmwr.read_rating_bundle_pending(
            build_workbook(pct=0.5), expected_through=through
        )
    with pytest.raises(va_mmwr.VaMmwrError, match="exactly one 'Transformation'"):
        va_mmwr.read_rating_bundle_pending(
            build_workbook(sheet_name="Transformed"), expected_through=through
        )
    with pytest.raises(va_mmwr.VaMmwrError, match="exactly one"):
        va_mmwr.read_rating_bundle_pending(
            build_workbook(title="Rating Bundle Metrics (old layout)"),
            expected_through=through,
        )
    duplicate_row = (
        '<row r="9"><c r="D9" t="s"><v>5</v></c><c r="I9" t="s"><v>6</v></c>'
        '<c r="J9"><f>X</f><v>1</v></c><c r="K9"><f>X</f><v>1</v></c>'
        '<c r="L9"><f>X</f><v>1</v></c></row>'
    )
    with pytest.raises(va_mmwr.VaMmwrError, match="exactly one 'Compensation"):
        va_mmwr.read_rating_bundle_pending(
            build_workbook(extra_rows=duplicate_row), expected_through=through
        )
    with pytest.raises(va_mmwr.VaMmwrError, match="not an OOXML workbook"):
        va_mmwr.read_rating_bundle_pending(
            b"<html>Page Not Found</html>", expected_through=through
        )
