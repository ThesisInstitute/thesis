"""Synthetic release layouts; these are not claimed Archive-capture fixtures.

Values for CPI/employment/JOLTS are from the permitted historical releases,
never the target months. Prose/table checks here exercise parser selection
only. Real Archive captures are tested in test_release_capture_real_fixtures.py.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from legacy_release_parsers import SPECS, parse_release  # noqa: E402

IDS = tuple(SPECS)
EXPECTED = {
    "cpi_headline_mom": ("2026-07", 0.1),
    "cpi_core_mom": ("2026-07", 0.2),
    "empsit_unemployment_rate": ("2026-07", 4.1),
    "empsit_payroll_change": ("2026-07", -23.0),
    "jolts_job_openings": ("2026-06", 7359.0),
    "jolts_quits_rate": ("2026-06", 2.0),
}


def _cell(value: object, target: bool = False) -> str:
    return f'<td data-test="{"target" if target else "other"}">{value}</td>'


def _fixture(parser_id: str) -> str:
    """Small synthetic HTML preserving the pinned historical table semantics."""
    period, value = EXPECTED[parser_id]
    month = "June" if period.endswith("06") else "July"
    prior = "May" if month == "June" else "June"
    title = ""
    table_id = ""
    if parser_id.startswith("cpi_"):
        title = "Consumer Price Index Summary"
        table_id = "cpi_pressa"
        caption = (
            "Table A. Percent changes in CPI for All Urban Consumers (CPI-U): "
            "U.S. city average"
        )
        header = (
            '<tr><th rowspan="2">Expenditure category</th><th colspan="2">'
            "Seasonally adjusted changes from preceding month</th>"
            '<th rowspan="2">Un-adjusted 12-mos. ended July 2026</th></tr>'
            "<tr><th>June 2026</th><th>July 2026</th></tr>"
        )
        body = ""
        for row, printed, key in (
            ("All items", "0.1", "cpi_headline_mom"),
            ("All items less food and energy", "0.2", "cpi_core_mom"),
        ):
            body += f'<tr data-row="{key}"><th>{row}</th>'
            body += _cell("0.8") + _cell(printed, parser_id == key) + _cell("3.4")
            body += "</tr>"
    elif parser_id.startswith("empsit_"):
        title = "Employment Situation Summary"
        is_rate = parser_id.endswith("rate")
        caption = (
            "Summary table A. Household data, seasonally adjusted [Numbers in "
            "thousands]"
            if is_rate
            else "Summary table B. Establishment data, seasonally adjusted"
        )
        marker = "" if is_rate else "(p)"
        header = (
            "<tr><th>Category</th><th>July 2025</th><th>June 2026</th>"
            f"<th>July 2026{marker}</th>"
            + ("<th>Change from: June 2026-July 2026</th>" if is_rate else "")
            + "</tr>"
        )
        if is_rate:
            body = (
                '<tr><th colspan="5">Employment status</th></tr>'
                '<tr data-row="empsit_unemployment_rate"><th>Unemployment rate</th>'
                + _cell("4.3")
                + _cell("4.2")
                + _cell(value, True)
                + _cell("-0.1")
                + "</tr>"
            )
        else:
            body = (
                '<tr><th colspan="4">EMPLOYMENT BY SELECTED INDUSTRY '
                "(Over-the-month change, in thousands)</th></tr>"
                '<tr data-row="empsit_payroll_change"><th>Total nonfarm</th>'
                + _cell("64")
                + _cell("20")
                + _cell(value, True)
                + "</tr>"
                '<tr><th colspan="4">(3-month average change, in thousands)</th></tr>'
                "<tr><th>Total nonfarm</th>"
                + _cell("19")
                + _cell("77")
                + _cell("20")
                + "</tr>"
            )
    elif parser_id == "jolts_job_openings":
        title = "Job Openings and Labor Turnover Summary"
        caption = (
            "Table A. Job openings, hires, and total separations by industry, "
            "seasonally adjusted"
        )
        header = (
            '<tr><th rowspan="2">Industry</th>'
            '<th colspan="3">Job openings</th>'
            '<th colspan="3">Hires</th>'
            '<th colspan="3">Total separations</th></tr>'
            + "<tr>"
            + "<th>April 2026</th><th>May 2026</th><th>June 2026(P)</th>" * 3
            + "</tr>"
        )
        body = (
            '<tr><th colspan="10">LEVELS BY INDUSTRY (in thousands)</th></tr>'
            '<tr data-row="jolts_job_openings"><th>Total</th>'
            + _cell("7190")
            + _cell("7537")
            + _cell("7,359", True)
            + "".join(_cell(number) for number in (5100, 5200, 5300, 4900, 5000, 5100))
            + "</tr>"
            '<tr><th colspan="10">RATES BY INDUSTRY (percent)</th></tr>'
            '<tr data-row="jolts_openings_rate"><th>Total</th>'
            + "".join(
                _cell(number) for number in (4.3, 4.5, 4.4, 3.1, 3.2, 3.3, 3, 3.1, 3.2)
            )
            + "</tr>"
        )
    elif parser_id == "jolts_quits_rate":
        title = (
            "Table 4. Quits levels and rates by industry and region, "
            "seasonally adjusted"
        )
        caption = title + " (1)"
        header = (
            '<tr><th rowspan="2">Industry and region</th>'
            '<th colspan="3">Levels (in thousands)</th>'
            '<th colspan="3">Rates(2)</th></tr>'
            "<tr><th>May 2026</th><th>June 2026(P)</th>"
            "<th>Change from: May 2026-June 2026(P)</th>"
            "<th>May 2026</th><th>June 2026(P)</th>"
            "<th>Change from: May 2026-June 2026(P)</th></tr>"
        )
        body = '<tr data-row="jolts_quits_rate"><th>Total</th>'
        body += _cell("7537") + _cell("3,232") + _cell("79")
        body += _cell("4.5") + _cell(value, True) + _cell("0.0") + "</tr>"
    else:
        raise AssertionError(f"no synthetic layout for {parser_id}")
    return (
        f"<html><head><title>{title} - {period[:4]} M{period[-2:]} Results</title>"
        f"</head><body><p>Synthetic independent prose: {value} for {month}; "
        f'prior month {prior} is a decoy.</p><table id="{table_id}">'
        f"<caption>{caption}</caption>{header}{body}</table></body></html>"
    )


@pytest.mark.parametrize("parser_id", IDS)
@pytest.mark.parametrize("mutation", ("title", "column", "delete_row", "duplicate_row"))
def test_identity_mutations_refuse(parser_id: str, mutation: str) -> None:
    html = _fixture(parser_id)
    if mutation == "title":
        html = html.replace("2026 M", "2025 M", 1)
    elif mutation == "column":
        target_month = "June 2026" if parser_id.startswith("jolts_") else "July 2026"
        # Change every current-month header, retaining title and row values.
        html = re.sub(
            r"(<th[^>]*>)" + target_month,
            r"\g<1>November 2025",
            html,
        )
    else:
        row = re.search(rf'<tr data-row="{parser_id}">.*?</tr>', html)
        assert row is not None
        html = html.replace(row[0], "" if mutation == "delete_row" else row[0] * 2)
    assert parse_release(html, parser_id) is None


@settings(max_examples=50, deadline=None)
@given(parser_id=st.sampled_from(IDS), decoy=st.integers(-100000, 100000))
def test_other_columns_values_never_leak(parser_id: str, decoy: int) -> None:
    html = re.sub(
        r'(<td data-test="other">)[^<]*(</td>)',
        lambda match: match[1] + str(decoy) + match[2],
        _fixture(parser_id),
    )
    assert parse_release(html, parser_id) == EXPECTED[parser_id]


@settings(max_examples=50, deadline=None)
@given(value=st.integers(-1000, 1000))
def test_cpi_headline_and_core_do_not_read_each_others_row(value: int) -> None:
    html = _fixture("cpi_headline_mom")
    core = re.search(r'<tr data-row="cpi_core_mom">.*?</tr>', html)[0]
    changed = core.replace(_cell("0.2"), _cell(value))
    html = html.replace(core, changed)
    assert parse_release(html, "cpi_headline_mom") == EXPECTED["cpi_headline_mom"]
    assert parse_release(html, "cpi_core_mom") == ("2026-07", float(value))


@pytest.mark.parametrize("parser_id", IDS)
@pytest.mark.parametrize(
    "printed", ("bad", "1.0(1)", "1.0(P)", "1e2", "NaN", "4<b>.</b>1")
)
def test_bad_numeric_or_unknown_footnote_refuses(parser_id: str, printed: str) -> None:
    html = re.sub(
        r'(<td data-test="target">)[^<]*(</td>)',
        rf"\g<1>{printed}\g<2>",
        _fixture(parser_id),
    )
    assert parse_release(html, parser_id) is None


@pytest.mark.parametrize("parser_id", IDS)
def test_duplicate_target_column_refuses(parser_id: str) -> None:
    html = _fixture(parser_id)
    month = "June" if parser_id.startswith("jolts_") else "July"
    header = re.search(rf"<th>{month} 2026(?:\([pP]\))?</th>", html)[0]
    html = html.replace(header, header * 2, 1)
    assert parse_release(html, parser_id) is None


@pytest.mark.parametrize("parser_id", IDS)
def test_duplicate_table_or_title_and_unclosed_table_refuse(parser_id: str) -> None:
    html = _fixture(parser_id)
    table = re.search(r"<table .*?</table>", html)[0]
    title = re.search(r"<title>.*?</title>", html)[0]
    for mutated in (html + table, html + title, html.replace("</table>", "")):
        assert parse_release(mutated, parser_id) is None


def test_payroll_never_uses_three_month_average_when_monthly_row_missing() -> None:
    html = _fixture("empsit_payroll_change")
    row = re.search(r'<tr data-row="empsit_payroll_change">.*?</tr>', html)[0]
    assert parse_release(html.replace(row, ""), "empsit_payroll_change") is None


def test_unknown_parser_refuses() -> None:
    assert parse_release(_fixture("cpi_headline_mom"), "unknown") is None


@pytest.mark.parametrize(
    "parser_id",
    ("cpi_headline_mom", "cpi_core_mom", "jolts_job_openings"),
)
def test_unknown_group_note_is_not_silently_stripped(parser_id: str) -> None:
    html = _fixture(parser_id)
    group = SPECS[parser_id].group
    assert group is not None
    assert parse_release(html.replace(group, group + "(2)"), parser_id) is None


@pytest.mark.parametrize(
    "parser_id", ("empsit_payroll_change", "jolts_job_openings", "jolts_quits_rate")
)
def test_only_known_preliminary_header_markers_strip(parser_id: str) -> None:
    html = _fixture(parser_id)
    assert parse_release(html.replace("(p)", "(P)"), parser_id) == EXPECTED[parser_id]
    html = html.replace("(p)", "(r)").replace("(P)", "(r)")
    assert parse_release(html, parser_id) is None


def _target_row(html: str, parser_id: str) -> str:
    match = re.search(rf'<tr data-row="{parser_id}">.*?</tr>', html)
    assert match is not None
    return match[0]


@pytest.mark.parametrize("parser_id", IDS)
@pytest.mark.parametrize(
    "mutation",
    (
        "label_colspan",
        "label_rowspan",
        "numeric_colspan",
        "numeric_rowspan",
        "duplicate_first_td",
        "delete_first_td",
        "label_colspan_and_delete_last_td",
    ),
)
def test_data_row_shape_cannot_shift_another_column_under_target_header(
    parser_id: str, mutation: str
) -> None:
    html = _fixture(parser_id)
    row = _target_row(html, parser_id)
    cells = re.findall(r"<td[^>]*>.*?</td>", row)
    assert cells
    if mutation.startswith("label_"):
        span = "rowspan" if mutation == "label_rowspan" else "colspan"
        changed = row.replace("<th>", f'<th {span}="2">', 1)
        if mutation.endswith("delete_last_td"):
            changed = changed.replace(cells[-1], "", 1)
    elif mutation.startswith("numeric_"):
        span = "rowspan" if mutation == "numeric_rowspan" else "colspan"
        changed = row.replace("<td ", f'<td {span}="2" ', 1)
    elif mutation == "duplicate_first_td":
        changed = row.replace(cells[0], cells[0] * 2, 1)
    else:
        changed = row.replace(cells[0], "", 1)
    assert parse_release(html.replace(row, changed), parser_id) is None


@pytest.mark.parametrize("parser_id", IDS)
def test_missing_target_column_header_cannot_leave_an_unauthenticated_column(
    parser_id: str,
) -> None:
    html = _fixture(parser_id)
    month = "June" if parser_id.startswith("jolts_") else "July"
    target_header = re.search(rf"<th>{month} 2026(?:\([pP]\))?</th>", html)
    assert target_header is not None
    assert parse_release(html.replace(target_header[0], "", 1), parser_id) is None


@pytest.mark.parametrize("parser_id", IDS)
@pytest.mark.parametrize("kind", ("contradictory", "duplicated", "unknown_footnote"))
def test_entire_semantic_header_path_must_match(parser_id: str, kind: str) -> None:
    html = _fixture(parser_id)
    row = _target_row(html, parser_id)
    columns = 1 + len(re.findall(r"<td\b", row))
    required = SPECS[parser_id].group or SPECS[parser_id].section
    assert required is not None
    label = {
        "contradictory": "Not seasonally adjusted",
        "duplicated": required,
        "unknown_footnote": required + "(99)",
    }[kind]
    added = f'<tr><th colspan="{columns}">{label}</th></tr>'
    assert (
        parse_release(html.replace("</caption>", "</caption>" + added, 1), parser_id)
        is None
    )


def test_one_group_header_repeated_by_rowspan_keeps_its_single_meaning() -> None:
    html = _fixture("cpi_headline_mom")
    html = html.replace(
        '<th rowspan="2">Expenditure category',
        '<th rowspan="3">Expenditure category',
        1,
    )
    html = html.replace(
        '<th colspan="2">Seasonally', '<th rowspan="2" colspan="2">Seasonally', 1
    )
    html = html.replace('<th rowspan="2">Un-adjusted', '<th rowspan="3">Un-adjusted', 1)
    html = html.replace(
        "</th></tr><tr><th>June 2026", "</th></tr><tr></tr><tr><th>June 2026", 1
    )
    assert parse_release(html, "cpi_headline_mom") == EXPECTED["cpi_headline_mom"]


@pytest.mark.parametrize("parser_id", IDS)
def test_numeric_overflow_refuses_instead_of_returning_infinity(parser_id: str) -> None:
    html = re.sub(
        r'(<td data-test="target">)[^<]*(</td>)',
        lambda match: match[1] + "9" * 400 + match[2],
        _fixture(parser_id),
    )
    assert parse_release(html, parser_id) is None


@pytest.mark.parametrize(
    "parser_id", ("empsit_unemployment_rate", "empsit_payroll_change")
)
def test_employment_section_can_occupy_only_the_stub_beside_blank_data_cells(
    parser_id: str,
) -> None:
    html = _fixture(parser_id)
    section = SPECS[parser_id].section
    assert section is not None
    row = _target_row(html, parser_id)
    columns = 1 + len(re.findall(r"<td\b", row))
    original = f'<tr><th colspan="{columns}">{section}</th></tr>'
    assert original in html
    # Both common forms are layout only: the section identity remains pinned
    # by row-selection state even when it is absent above numeric columns.
    for blank_cells in (
        f'<td colspan="{columns - 1}"></td>',
        "<td></td>" * (columns - 1),
    ):
        changed = f"<tr><th>{section}</th>{blank_cells}</tr>"
        assert (
            parse_release(html.replace(original, changed), parser_id)
            == EXPECTED[parser_id]
        )
        assert (
            parse_release(
                html.replace(original, changed.replace(section, "Unknown section")),
                parser_id,
            )
            is None
        )


def test_jolts_openings_never_uses_table_a_rate_row_if_level_row_is_missing() -> None:
    html = _fixture("jolts_job_openings")
    level_row = _target_row(html, "jolts_job_openings")
    assert parse_release(html.replace(level_row, ""), "jolts_job_openings") is None


def test_jolts_openings_requires_summary_table_a_not_full_release_table_1() -> None:
    # Full archived releases also contain Table 1. It is not the registered
    # nr0 summary's pinned table, even when it has a superficially valid cell.
    table_1 = (
        "<html><head><title>Job Openings and Labor Turnover Summary - "
        "2026 M06 Results</title></head><body><table>"
        "<caption>Table 1. Job openings levels and rates by industry and region, "
        "seasonally adjusted (1)</caption>"
        '<tr><th rowspan="2">Industry and region</th>'
        '<th colspan="2">Levels (in thousands)</th>'
        '<th colspan="2">Rates</th></tr>'
        "<tr><th>May 2026</th><th>June 2026(P)</th>"
        "<th>May 2026</th><th>June 2026(P)</th></tr>"
        "<tr><th>Total</th><td>7,537</td><td>7,359</td><td>4.5</td><td>4.4</td></tr>"
        "</table></body></html>"
    )
    assert parse_release(table_1, "jolts_job_openings") is None


@pytest.mark.parametrize("parser_id", IDS)
def test_a_release_of_another_kind_is_refused_by_its_title(parser_id: str) -> None:
    html = _fixture(parser_id)
    title = re.search(r"<title>(.*?) - \d{4} M\d{2} Results</title>", html)
    assert title is not None
    other = html.replace(title.group(1), "Producer Price Index Summary", 1)
    assert parse_release(other, parser_id) is None


@pytest.mark.parametrize("parser_id", [p for p in IDS if SPECS[p].table_id])
def test_a_table_with_another_id_is_refused(parser_id: str) -> None:
    html = _fixture(parser_id)
    table_id = SPECS[parser_id].table_id
    assert f'id="{table_id}"' in html
    assert (
        parse_release(html.replace(f'id="{table_id}"', 'id="other"'), parser_id) is None
    )


@pytest.mark.parametrize("parser_id", IDS)
def test_a_title_month_the_table_does_not_end_on_is_refused(parser_id: str) -> None:
    """The title must name the table's latest month (dates == [period])."""
    html = _fixture(parser_id)
    title = re.search(r"- (\d{4}) M(\d{2}) Results", html)
    assert title is not None
    month = int(title.group(2))
    shifted = f"- {title.group(1)} M{month % 12 + 1:02d} Results"
    assert parse_release(html.replace(title.group(0), shifted, 1), parser_id) is None


def test_the_rates_note_is_stripped_for_the_quits_table_only() -> None:
    quits = _fixture("jolts_quits_rate")
    assert "Rates(2)" in quits
    assert parse_release(quits, "jolts_quits_rate") == EXPECTED["jolts_quits_rate"]
    for parser_id in ("cpi_headline_mom", "jolts_job_openings"):
        html = _fixture(parser_id)
        group = SPECS[parser_id].group
        assert group is not None
        noted = html.replace(f">{group}<", f">{group}(2)<", 1)
        assert noted != html
        assert parse_release(noted, parser_id) is None


def test_a_column_under_two_months_is_refused() -> None:
    """A target column whose header path names another month as well (an
    extra dated header row above it) is not the target month's own column:
    dates must be exactly [period], not merely include it."""
    html = _fixture("cpi_headline_mom")
    html = html.replace(
        '<th rowspan="2">Expenditure category',
        '<th rowspan="3">Expenditure category',
        1,
    )
    html = html.replace('<th rowspan="2">Un-adjusted', '<th rowspan="3">Un-adjusted', 1)
    html = html.replace(
        "</th></tr><tr><th>June 2026",
        '</th></tr><tr><th colspan="2">June 2026</th></tr><tr><th>June 2026',
        1,
    )
    assert parse_release(html, "cpi_headline_mom") is None
