"""SSA official-page readers: label-anchored, identity-checked, fail-closed.

Fixtures are raw captures of the live pages taken 2026-08-23 through the
resolver's headless-browser transport (ssa.gov answers non-browser clients
with 403), plus the 2026-07-11 Wayback capture of the June 2026 Monthly
Statistical Snapshot and the live OHO workload XML for the reporting period
ending 2026-06-26.
"""

from __future__ import annotations

import gzip
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ssa_official_pages as ssa  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "ssa_official"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_table1_reads_total_65_plus_and_checks_identities() -> None:
    reading = ssa.ssi_table1_count(
        fixture("ssi_2026-06_table01.html"),
        "2026-06",
        row="Total",
        column="65 or older",
    )
    assert reading.value == 2_505_847
    assert reading.row == "Total" and reading.column == "65 or older"
    assert reading.table_caption.endswith("June 2026")
    assert "Under 18 + 18-64 + 65 or older = 7323731" in reading.identities[0]
    # Footnote markers inside <sup> never leak into labels.
    assert (
        ssa.ssi_table1_count(
            fixture("ssi_2026-06_table01.html"),
            "2026-06",
            row="Total",
            column="Blind and disabled",
        ).value
        == 6_138_395
    )


def test_table1_refuses_wrong_edition_and_tampered_identity() -> None:
    raw = fixture("ssi_2026-06_table01.html")
    with pytest.raises(ssa.SsaPageError, match="title"):
        ssa.ssi_table1_count(raw, "2026-05", row="Total", column="65 or older")
    tampered = raw.replace(b"2,505,847", b"2,505,848")
    with pytest.raises(ssa.SsaPageError, match="identity"):
        ssa.ssi_table1_count(tampered, "2026-06", row="Total", column="65 or older")
    with pytest.raises(ssa.SsaPageError, match="no header cell"):
        ssa.ssi_table1_count(raw, "2026-06", row="Total", column="70 or older")


def test_table4_reads_colorado_cells_and_refuses_restructure() -> None:
    raw = fixture("ssi_2026-07_table04.html")
    total = ssa.ssi_table4_count(raw, "2026-07", state="Colorado", column="Total")
    aged = ssa.ssi_table4_count(raw, "2026-07", state="Colorado", column="65 or older")
    assert (total.value, aged.value) == (66_284, 23_094)
    assert total.identities[0] == "Colorado: Under 18 + 18-64 + 65 or older = 66284"
    national = ssa.ssi_table4_count(raw, "2026-07", state="All areas", column="Total")
    assert national.value == 7_300_297
    with pytest.raises(ssa.SsaPageError, match="exactly one row"):
        ssa.ssi_table4_count(raw, "2026-07", state="Colorado Springs", column="Total")
    restructured = raw.replace(b'scope="col">Aged<', b'scope="col">Elderly<')
    with pytest.raises(ssa.SsaPageError, match="restructured"):
        ssa.ssi_table4_count(restructured, "2026-07", state="Colorado", column="Total")


def test_table2_reads_the_editions_own_month_under_its_year_group() -> None:
    raw = fixture("ssi_2026-07_table02.html")
    reading = ssa.ssi_table2_total_recipients(raw, "2026-07")
    assert reading.value == 7_300_297
    assert reading.row == "July 2026"
    # The July 2025 row exists under the 2025 group; the 2026 group is used.
    tampered = raw.replace(b"<td>7,300,297</td>", b"<td>7,300,298</td>")
    with pytest.raises(ssa.SsaPageError, match="identity"):
        ssa.ssi_table2_total_recipients(tampered, "2026-07")
    with pytest.raises(ssa.SsaPageError, match="title"):
        ssa.ssi_table2_total_recipients(raw, "2026-06")


def test_snapshot_reads_disabled_workers_live_and_wayback_alike() -> None:
    live = ssa.snapshot_table2_thousands(
        fixture("stat_snapshot_2026-06.html"),
        "2026-06",
        group="Disability Insurance",
        row="Disabled workers",
    )
    archived = ssa.snapshot_table2_thousands(
        fixture("stat_snapshot_2026-06.wayback-20260711204033.html"),
        "2026-06",
        group="Disability Insurance",
        row="Disabled workers",
    )
    assert live.value == archived.value == 7_006
    assert live.identities[1] == "OASI + DI = 71255 (±2)"
    with pytest.raises(ssa.SsaPageError, match="not a component"):
        ssa.snapshot_table2_thousands(
            fixture("stat_snapshot_2026-06.html"),
            "2026-06",
            group="Disability Insurance",
            row="Retired workers",
        )


def test_oho_workload_xml_has_no_national_row() -> None:
    workload = ssa.oho_workload_file(fixture("ho_workload_2026-06-26.xml"))
    assert workload.reporting_period_end.isoformat() == "2026-06-26"
    assert workload.created == "07/10/2026"
    assert len(workload.rows) == 165
    value, note = ssa.oho_national_average_processing_time(workload)
    assert value is None
    assert "publishes no national aggregate row" in note
    # A national row, were SSA ever to publish one, is read as an integer.
    synthetic = fixture("ho_workload_2026-06-26.xml").replace(
        b"<OFFICE>AKRON OH</OFFICE>", b"<OFFICE>NATIONAL</OFFICE>", 1
    )
    value, note = ssa.oho_national_average_processing_time(
        ssa.oho_workload_file(synthetic)
    )
    assert (value, note) == (234, "national row present")


def test_oho_workload_xml_fails_closed_on_identity_drift() -> None:
    raw = fixture("ho_workload_2026-06-26.xml")
    with pytest.raises(ssa.SsaPageError, match="title"):
        ssa.oho_workload_file(raw.replace(b"Hearing Office Workload Data", b"Other"))
    with pytest.raises(ssa.SsaPageError, match="records"):
        ssa.oho_workload_file(raw.replace(b'records="165"', b'records="164"'))


def test_wayback_helpers_parse_cdx_and_decompress_bodies() -> None:
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        if "cdx/search" in url:
            return fixture("cdx_stat_snapshot_2026-06.json")
        return gzip.compress(
            fixture("stat_snapshot_2026-06.wayback-20260711204033.html")
        )

    url = "https://www.ssa.gov/policy/docs/quickfacts/stat_snapshot/2026-06.html"
    captures = ssa.wayback_captures(url, fetch)
    assert [c["timestamp"] for c in captures] == [
        "20260711204033",
        "20260802032502",
        "20260806225812",
    ]
    assert ssa.wayback_raw_url("20260711204033", url) == (
        "https://web.archive.org/web/20260711204033id_/" + url
    )
    body = ssa.wayback_capture_body("20260711204033", url, fetch)
    assert body[:9] == b"\xef\xbb\xbf<!doct" or body[:6] == b"<!doct"
    assert ssa.wayback_timestamp_to_iso("20260711204033") == "2026-07-11T20:40:33Z"
    # Only 200 captures count.
    rows = json.loads(fixture("cdx_stat_snapshot_2026-06.json"))
    rows.append(["20260805042050", "403", "X", "938"])
    assert len(ssa.wayback_captures(url, lambda _u: json.dumps(rows).encode())) == 3
