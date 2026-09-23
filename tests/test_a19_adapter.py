"""BLS CPS Table A-19: registered unit, capture identity, first-print window.

The fixtures are the table element of three real Internet Archive captures
of https://www.bls.gov/web/empsit/cpseea19.htm (tests/fixtures/a19/README.md).
"""

from __future__ import annotations

import base64
import copy
import datetime as dt
import gzip
import hashlib
import json
import pathlib
import sys
import urllib.error

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolve_pending  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "a19"
CAPTURES = {
    "2026-06": "20260710110509",
    "2026-07": "20260819191418",
    "2026-08": "20260904170006",
}
# Printed thousands, read off the captured tables. The June row is what the
# ledger already records for the six cells resolved from this capture.
ANCHORS = {
    "2026-06": {
        "business_financial_operations": 9720.0,
        "computer_mathematical": 6950.0,
        "healthcare_support": 5691.0,
        "office_administrative_support": 16184.0,
        "production": 7759.0,
        "transportation_material_moving": 12010.0,
    },
    "2026-07": {
        "business_financial_operations": 9835.0,
        "computer_mathematical": 6924.0,
        "healthcare_support": 5797.0,
        "office_administrative_support": 16457.0,
        "production": 8121.0,
        "transportation_material_moving": 12223.0,
    },
    "2026-08": {
        "business_financial_operations": 10167.0,
        "computer_mathematical": 7010.0,
        "healthcare_support": 5709.0,
        "office_administrative_support": 16154.0,
        "production": 7716.0,
        "transportation_material_moving": 12011.0,
    },
}
SERIES = "bls.cps.employed_people_by_occupation.production"
LABEL = "Production occupations"


def fixture(period: str) -> str:
    return (
        FIXTURES / f"cpseea19-{period}-wayback-{CAPTURES[period]}.table.html"
    ).read_text()


def capture_url(period: str) -> str:
    return (
        f"https://web.archive.org/web/{CAPTURES[period]}/"
        f"{resolve_pending.A19_SOURCE_URL}"
    )


def registration(
    period: str = "2026-08",
    window: tuple[str, str] = ("2026-09-02", "2026-09-10"),
    **contract_overrides: object,
) -> dict:
    month = dt.date.fromisoformat(f"{period}-01").strftime("%B").lower()
    contract = {
        "catalogSlug": f"cps-production-employment-{month}-{period[:4]}",
        "country": "US",
        "dataPointId": f"{SERIES}.{month}_{period[:4]}.first_print",
        "period": period,
        "series": SERIES,
        "sourceBinding": {
            "adapter": "generic-url",
            "allowedHosts": ["www.bls.gov"],
            "expectedReleaseWindow": {"start": window[0], "end": window[1]},
            "field": LABEL,
            "releasePolicy": "first_print",
            "sourceSeriesId": SERIES,
            "sourceUrl": "https://www.bls.gov/web/empsit/cpseea19.htm",
            "table": (
                "CPS Employment Situation Table A-19, employed persons by "
                "occupation, not seasonally adjusted (thousands)"
            ),
            "transform": {"factor": 0.001, "operation": "multiply"},
        },
        "unit": "millions",
        "valueScale": 0.001,
    }
    contract.update(contract_overrides)
    return {"contract": contract, "targetContentHash": "c" * 64}


def routed_spec(ref: str, unit: str) -> dict:
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "slug",
                "resolutionDate": "2026-09-10",
                "unit": unit,
            }
        ],
        "resolutionLinks": [
            {"status": "pending", "targetFactRef": ref, "forecastSlug": "slug"}
        ],
    }
    ((_, kind, spec, *_),) = resolve_pending.pending_adapter_refs(log)
    assert kind == "a19"
    return spec


# -- the capture says which month it prints -----------------------------------


@pytest.mark.parametrize("period", sorted(CAPTURES))
def test_capture_period_and_printed_rows(period: str) -> None:
    html = fixture(period)
    assert resolve_pending.a19_snapshot_period(html) == period
    assert resolve_pending.a19_values_from_html(html) == ANCHORS[period]


def test_every_pin_archives_the_bound_page_and_matches_its_fixture() -> None:
    assert set(resolve_pending.A19_SNAPSHOT_URLS) == set(CAPTURES)
    for period, url in resolve_pending.A19_SNAPSHOT_URLS.items():
        assert url == capture_url(period)
        captured, original = resolve_pending.a19_capture(url)
        assert original == resolve_pending.A19_SOURCE_URL
        assert f"{captured:%Y%m%d%H%M%S}" == CAPTURES[period]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bls.gov/web/empsit/cpseea19.htm",
        "http://web.archive.org/web/20260904170006/https://www.bls.gov/x",
        "https://web.archive.org/web/2026090417/https://www.bls.gov/x",
        "https://web.archive.org/web/20261304170006/https://www.bls.gov/x",
        "https://web.archive.org/web/20260904170006/http://www.bls.gov/x",
    ],
)
def test_capture_url_fails_closed(url: str) -> None:
    assert resolve_pending.a19_capture(url) is None


def test_the_full_page_the_resolver_archived_in_july_reads_the_same() -> None:
    # The fixtures are table elements; this is the whole page, Archive
    # toolbar and all, as the resolver archived it on 2026-07-10.
    archived = next(
        (ROOT / "records" / "resolutions" / "2026-07-10").glob(
            "*/responses/cpseea19-production-*.html.gz"
        )
    )
    raw = gzip.decompress(archived.read_bytes())
    assert len(raw) == 125_026  # the figure docs/anchor-verifications.md cites
    html = raw.decode(errors="replace")
    assert resolve_pending.a19_table(html) == ("2026-06", ANCHORS["2026-06"])


def test_implicitly_closed_cells_parse_and_only_a_nested_cell_refuses() -> None:
    html = fixture("2026-08")
    expected = ("2026-08", ANCHORS["2026-08"])
    # HTML lets </td> and </th> be omitted: the next cell or row closes them.
    assert resolve_pending.a19_table(html.replace("</td>", "")) == expected
    assert resolve_pending.a19_table(html.replace("</th>", "")) == expected
    # A sloppy table elsewhere on the page is not this table's business.
    assert (
        resolve_pending.a19_table("<table><tr><td>a<tr><td>b</table>" + html)
        == expected
    )
    # A table nested in a cell with rows but no cells loses no text.
    assert (
        resolve_pending.a19_table(
            html.replace(">7,716<", "><table><tr></tr></table>7,716<", 1)
        )
        == expected
    )
    # Header ids elsewhere on the page that merely share this table's prefix
    # collide with nothing.
    assert (
        resolve_pending.a19_table(
            '<table><tr><th id="cps_eande_m19.navigation">Navigation</th></tr>'
            "</table>" + html
        )
        == expected
    )


def test_only_the_a19_table_is_read() -> None:
    html = fixture("2026-08")
    expected = ("2026-08", ANCHORS["2026-08"])
    # Wrapped in a layout table's cell, as a site template might do.
    wrapped = "<table><tr><td>layout" + html + "</td></tr></table>"
    assert resolve_pending.a19_table(wrapped) == expected
    # Another table on the page with a reused id, a same-named row header,
    # and a table nested in a cell: none of it is this table's business.
    chrome = (
        '<table><tr><th id="x">Production occupations</th><th id="x">y</th></tr>'
        "<tr><td><table><tr><td>z</td></tr></table></td></tr></table>"
    )
    assert resolve_pending.a19_table(chrome + html) == expected
    # Without the table's id nothing is read.
    assert (
        resolve_pending.a19_table(html.replace('id="cps_eande_m19"', 'id="x"', 1))
        is None
    )
    # Two tables with this id: neither can be told to be the one.
    assert resolve_pending.a19_table(html + html) is None
    assert (
        resolve_pending.a19_table(html.replace("Production", "Crafts") + html) is None
    )
    # One of this table's ids defined elsewhere on the page first: a browser
    # would bind the cell to that header, so the page is not identified.
    assert (
        resolve_pending.a19_table(
            '<table><tr><th id="cps_eande_m19.r.6.1">Crafts</th></tr></table>' + html
        )
        is None
    )


def test_a_value_is_found_by_its_headers_not_its_position() -> None:
    html = fixture("2026-08")
    assert resolve_pending.a19_table(html) == ("2026-08", ANCHORS["2026-08"])
    # Markup around a label does not hide it.
    wrapped = html.replace("Aug.<br/>", "<span>Aug.</span><br/>")
    assert resolve_pending.a19_table(wrapped) == ("2026-08", ANCHORS["2026-08"])
    # Relabel the Total pair so the 2026 heading sits over the FIRST column:
    # the value read is the one headed 2026 (7,482), not the second number.
    relabeled = html.replace("Aug.<br/>2025", "<span>Aug.</span><br/>2026", 1).replace(
        "Aug.<br/>2026", "<span>Aug.</span><br/>2025", 1
    )
    period, values = resolve_pending.a19_table(relabeled)
    assert (period, values["production"]) == ("2026-08", 7482.0)


@pytest.mark.parametrize(
    "damage",
    [
        lambda html: "",
        lambda html: "<html><body>503 Service Unavailable</body></html>",
        # One occupation row missing.
        lambda html: html.replace("Production occupations", "Crafts"),
        # A third dated column under Total / 16 years and over.
        lambda html: html.replace(
            'id="cps_eande_m19.h.3.4">Aug.', 'id="cps_eande_m19.h.3.4">Sept.', 1
        ).replace(
            "cps_eande_m19.h.1.4 cps_eande_m19.h.2.4 cps_eande_m19.h.3.4",
            "cps_eande_m19.h.1.2 cps_eande_m19.h.2.2 cps_eande_m19.h.3.4",
        ),
        # A printed cell that is not a number.
        lambda html: html.replace(">7,716<", ">(1)<", 1),
        # Two headings a year apart but different months.
        lambda html: html.replace("Aug.<br/>2025", "July<br/>2025", 1),
        # A reused header id.
        lambda html: html.replace(
            'id="cps_eande_m19.h.3.3"', 'id="cps_eande_m19.h.3.2"', 1
        ),
        # Same month, two years apart (the Total year-ago heading).
        lambda html: html.replace("Aug.<br/>2025", "Aug.<br/>2024", 1),
        # A month label BLS does not print.
        lambda html: html.replace("Aug.<br/>", "Agosto<br/>"),
        # The Total current heading without its year.
        lambda html: html.replace("Aug.<br/>2026", "Aug.", 1),
        # A cell inside a cell: the old parser read the inner 999 as the
        # production value and lost the outer cell without an error.
        lambda html: html.replace(
            ">7,716<",
            '><table><tr><td headers="cps_eande_m19.r.6.1 cps_eande_m19.h.1.2 '
            'cps_eande_m19.h.2.2 cps_eande_m19.h.3.3">999</td></tr></table>7,716<',
            1,
        ),
        # Not a table at all.
        lambda html: "<th>Aug.<br/>2025</th><th>Aug.<br/>2026</th>",
        # A row start mid-value closes the cell early: "7" of "7,716" would be
        # read, and the rest would sit in the table outside any cell.
        lambda html: html.replace(">7,716<", ">7<tr><td>x</td></tr>,716<", 1),
        # The same through a table end: the later cells of this table then
        # sit outside it.
        lambda html: html.replace(
            ">7,716<", ">7<table/><tr><td>x</td></tr></table>,716<", 1
        ),
        # Text in a table nested inside a value cell, even in its caption,
        # would otherwise drop out of the value: "7" instead of 7,716.
        lambda html: html.replace(
            ">7,716<", ">7<table><caption>,716</caption></table><", 1
        ),
        lambda html: html.replace(">7,716<", ">7<table>,716</table><", 1),
        # The table never closes: cut after the last value, or drop </table>.
        lambda html: html[: html.rindex("</table>")],
        lambda html: html[: html.index("12,011") + len("12,011</td>")],
    ],
)
def test_a_page_that_cannot_be_identified_yields_nothing(damage) -> None:
    html = damage(fixture("2026-08"))
    assert resolve_pending.a19_table(html) is None
    assert resolve_pending.a19_snapshot_period(html) is None
    assert resolve_pending.a19_values_from_html(html) == {}


# -- the registered unit selects the spec -------------------------------------


def test_unregistered_cell_keeps_the_tables_thousands() -> None:
    spec = routed_spec(f"{SERIES}.june_2026.first_print", "thousands")
    assert resolve_pending.a19_execution_spec(spec, None) == (spec, None)
    assert spec["unit"] == "thousands" and "scale" not in spec


def test_registered_millions_contract_executes_in_millions() -> None:
    spec = routed_spec(f"{SERIES}.august_2026.first_print", "millions")
    executed, refusal = resolve_pending.a19_execution_spec(spec, registration())
    assert refusal is None
    assert (executed["unit"], executed["scale"], executed["round"]) == (
        "millions",
        0.001,
        3,
    )
    assert resolve_pending.adapter_unit_matches(executed, {"unit": "millions"})
    # The forecast's unit alone never selects the scale: a millions forecast
    # against a thousands contract still refuses at the unit ladder.
    thousands = registration(unit="thousands", valueScale=1.0)
    thousands["contract"]["sourceBinding"]["transform"] = {
        "operation": "multiply",
        "factor": 1.0,
    }
    executed, refusal = resolve_pending.a19_execution_spec(spec, thousands)
    assert refusal is None and executed["unit"] == "thousands"
    assert not resolve_pending.adapter_unit_matches(executed, {"unit": "millions"})


@pytest.mark.parametrize(
    ("mutate", "named"),
    [
        (lambda c: c.update(unit="billions"), "unit"),
        (lambda c: c.update(valueScale=1), "valueScale"),
        (
            lambda c: c["sourceBinding"].update(
                transform={"operation": "multiply", "factor": 1}
            ),
            "transform",
        ),
        (
            lambda c: c["sourceBinding"].update(
                transform={"operation": "identity", "factor": 0.001}
            ),
            "transform",
        ),
        (lambda c: c["sourceBinding"].update(field="Sales occupations"), "field"),
        (
            lambda c: c["sourceBinding"].update(
                sourceUrl="https://www.bls.gov/news.release/empsit.t19.htm"
            ),
            "sourceUrl",
        ),
        (
            lambda c: c["sourceBinding"].update(releasePolicy="advance_vintage"),
            "releasePolicy",
        ),
        # The reviewed exceptions this one joins (ABS by hash, QCEW, SBA, IRS)
        # pin the whole binding; so does this.
        (lambda c: c["sourceBinding"].update(adapter="alfred-fred"), "adapter"),
        (lambda c: c["sourceBinding"].update(table="Some other table"), "table"),
        (
            lambda c: c["sourceBinding"].update(allowedHosts=["evil.example.com"]),
            "allowedHosts",
        ),
        (lambda c: c["sourceBinding"].update(sourceSeriesId="other.series"), "series"),
        (lambda c: c.update(series="other.series"), "series"),
        (lambda c: c["sourceBinding"].update(extraKey=1), "sourceBinding keys"),
        (lambda c: c["sourceBinding"].pop("table"), "sourceBinding keys"),
    ],
)
def test_registered_contract_that_is_not_this_table_refuses(mutate, named) -> None:
    spec = routed_spec(f"{SERIES}.august_2026.first_print", "millions")
    drifted = registration()
    mutate(drifted["contract"])
    executed, refusal = resolve_pending.a19_execution_spec(spec, drifted)
    assert executed is None and named in refusal.split(", ")


def test_a19_is_a_constrained_family() -> None:
    assert resolve_pending.FAMILY_ADAPTERS["a19"] == {"generic-url"}
    drifted = registration()
    drifted["contract"]["sourceBinding"]["adapter"] = "alfred-fred"
    assert resolve_pending.binding_adapter_mismatch("a19", drifted) == "alfred-fred"
    assert resolve_pending.binding_adapter_mismatch("a19", registration()) is None


def test_every_registered_a19_contract_on_disk_selects_millions() -> None:
    contracts = resolve_pending.registration_contracts()
    refs = [ref for ref in contracts if ref.startswith(resolve_pending.A19_STEM)]
    assert len(refs) >= 12
    for ref in refs:
        unit = contracts[ref]["contract"]["unit"]
        executed, refusal = resolve_pending.a19_execution_spec(
            routed_spec(ref, unit), contracts[ref]
        )
        assert refusal is None, ref
        assert (executed["unit"], executed["scale"]) == ("millions", 0.001), ref


# -- the fact names the publisher and keeps the capture -----------------------


def test_fact_passes_the_registered_host_check_and_keeps_the_capture() -> None:
    spec = routed_spec(f"{SERIES}.august_2026.first_print", "millions")
    executed, _ = resolve_pending.a19_execution_spec(spec, registration())
    reg = registration()
    row = resolve_pending.a19_fact(
        reg["contract"]["dataPointId"],
        executed,
        "month",
        "2026-08",
        7.716,
        dt.date(2026, 9, 10),
        capture_url("2026-08"),
        "cpseea19.htm (Wayback capture 20260904170006)",
    )
    assert row["source"]["url"] == resolve_pending.A19_SOURCE_URL
    assert "first-print" not in row["source"]["extraction_method"]
    assert "Internet Archive capture" in row["source"]["extraction_method"]
    assert row["measure"]["concept_evidence_url"] == capture_url("2026-08")
    assert capture_url("2026-08") in row["measure"]["concept_evidence_notes"]
    assert row["measure"]["unit"] == "millions" and row["value"] == 7.716
    projection = resolve_pending.source_binding_projection(reg, row, b"bytes")
    assert projection["sourceUrl"] == resolve_pending.A19_SOURCE_URL
    assert projection["unit"] == "millions"
    # The transport alone would not have passed: that is why the fact must
    # name the publisher, and why the pin is checked to archive its page.
    row["source"]["url"] = capture_url("2026-08")
    with pytest.raises(ValueError, match="not in the registered allowedHosts"):
        resolve_pending.source_binding_projection(reg, row, b"bytes")


# -- the Archive must serve the capture that was asked for ---------------------


def identity_url(stamp: str) -> str:
    return f"https://web.archive.org/web/{stamp}id_/{resolve_pending.A19_SOURCE_URL}"


def replay_url(stamp: str) -> str:
    return f"https://web.archive.org/web/{stamp}/{resolve_pending.A19_SOURCE_URL}"


URL = "https://www.bls.gov/web/empsit/cpseea19.htm"
HEADER = ["timestamp", "original", "statuscode", "digest"]


def digest(name: str) -> str:
    """A content digest of the form the index uses (32 base-32 characters)."""

    return base64.b32encode(hashlib.sha1(name.encode()).digest()).decode()


def cdx(*rows: tuple[str, ...]) -> bytes:
    """An index body: rows are (stamp, status[, original[, digest]]).

    The digest defaults to one per stamp, i.e. every capture's bytes differ.
    """

    return json.dumps(
        [
            HEADER,
            *[
                [
                    row[0],
                    row[2] if len(row) > 2 and row[2] else URL,
                    row[1],
                    row[3] if len(row) > 3 else digest(row[0]),
                ]
                for row in rows
            ],
        ]
    ).encode()


def reader(index: bytes, pages: dict[str, str], calls: list[str]):
    """An Archive stand-in: ``pages`` maps a capture stamp to the table it holds."""

    def read(url: str) -> tuple[bytes, str]:
        calls.append(url)
        if url.startswith("https://web.archive.org/cdx/"):
            return index, url
        if url.startswith("https://web.archive.org/save/"):
            return b"saved", url
        for stamp, html in pages.items():
            if url == identity_url(stamp):
                return html.encode(), url
        raise urllib.error.HTTPError(url, 404, "no capture", None, None)

    return read


def test_read_capture_returns_the_bytes_of_exactly_that_capture() -> None:
    calls: list[str] = []
    stamp = CAPTURES["2026-08"]
    raw = resolve_pending.a19_read_capture(
        capture_url("2026-08"), reader(b"", {stamp: fixture("2026-08")}, calls)
    )
    assert raw == fixture("2026-08").encode()
    # The identity form: the stored response, not the replay wrapper.
    assert calls == [identity_url(stamp)]


def test_read_capture_gunzips_what_the_archive_passes_through() -> None:
    body = gzip.compress(fixture("2026-08").encode())

    def read(url: str) -> tuple[bytes, str]:
        return body, url

    assert resolve_pending.a19_read_capture(capture_url("2026-08"), read) == (
        fixture("2026-08").encode()
    )


def test_read_capture_refuses_the_nearest_capture_substitution() -> None:
    # Observed 2026-09-20: asked for 20260901000000, the Archive answered
    # HTTP 200 with the 20260904170006 capture and rewrote the path.
    served = identity_url("20260904170006")

    def read(url: str) -> tuple[bytes, str]:
        return fixture("2026-08").encode(), served

    with pytest.raises(resolve_pending.A19CaptureError, match="was served"):
        resolve_pending.a19_read_capture(replay_url("20260901000000"), read)
    # The same stamp over plain http is the same stored response.
    assert (
        resolve_pending.a19_read_capture(
            capture_url("2026-08"),
            lambda url: (b"x", served.replace("https://web", "http://web")),
        )
        == b"x"
    )
    # The replay form of the same stamp is NOT: its body carries the
    # Archive's toolbar and rewritten links, and the hash must cover BLS's.
    with pytest.raises(resolve_pending.A19CaptureError, match="was served"):
        resolve_pending.a19_read_capture(
            capture_url("2026-08"), lambda url: (b"x", capture_url("2026-08"))
        )


# -- discovery inside the registered window -----------------------------------

WINDOW = {"start": "2026-09-02", "end": "2026-09-10"}


def test_window_captures_keeps_only_good_captures_inside_the_window() -> None:
    calls: list[str] = []
    index = cdx(
        ("20260910235959", "200"),
        ("20260819191418", "200"),  # before the window
        ("20260904170006", "200"),
        ("20260904170006", "200"),  # listed twice
        ("20260904170006", "-"),  # and once more without a status
        ("20260905000000", "403"),
        ("20260907000000", "-", "", digest("x")),  # a row without a status
        ("20260908000000", "-", "", "-"),  # and one without a digest either
        ("20260911000000", "200"),  # after the window
    )
    index = resolve_pending.a19_window_captures(WINDOW, reader(index, {}, calls))
    assert index.captures == [
        replay_url("20260904170006"),
        replay_url("20260910235959"),
    ]
    assert [(row.stamp, row.digest) for row in index.revisits] == [
        ("20260907000000", digest("x")),
        ("20260908000000", None),
    ]
    assert [row.stamp for row in index.rows] == [
        "20260904170006",
        "20260907000000",
        "20260908000000",
        "20260910235959",
    ]
    assert (index.listed, index.other_status, index.other_form) == (5, 1, 0)
    # The counts are disjoint and add up.
    assert index.listed == len(index.rows) + index.other_status + index.other_form
    assert index.describe(WINDOW).endswith(
        "5 capture(s) dated inside the registered window "
        f"{WINDOW!r}, 2 of them HTTP 200 for this exact URL; "
        "2 without a status, 1 with another status"
    )
    assert "from=20260902000000" in calls[0] and "to=20260910235959" in calls[0]
    assert "fl=timestamp,original,statuscode,digest" in calls[0]
    assert "filter=" not in calls[0]


def test_a_stamp_listed_with_two_statuses_or_two_digests_is_ambiguous() -> None:
    # Whichever row came first must not decide; the index is unusable.
    for rows in (
        [("20260904170006", "403"), ("20260904170006", "200")],
        [("20260904170006", "200"), ("20260904170006", "403")],
        [
            ("20260904170006", "200", "", digest("a")),
            ("20260904170006", "200", "", digest("b")),
        ],
        [
            ("20260904170006", "-", "", digest("a")),
            ("20260904170006", "200", "", digest("b")),
        ],
    ):
        with pytest.raises(ValueError, match="lists 20260904170006 with"):
            resolve_pending.a19_window_captures(WINDOW, reader(cdx(*rows), {}, []))
    # A row without a status or without a digest fills in, in either order.
    for rows in (
        [("20260904170006", "-", "", digest("a")), ("20260904170006", "200", "", "-")],
        [("20260904170006", "200", "", "-"), ("20260904170006", "-", "", digest("a"))],
    ):
        index = resolve_pending.a19_window_captures(WINDOW, reader(cdx(*rows), {}, []))
        assert [(r.status, r.digest) for r in index.rows] == [("200", digest("a"))]


def test_a_capture_stored_under_another_form_of_the_url_is_counted_not_used() -> None:
    index = cdx(
        ("20260904170006", "200", "http://www.bls.gov/web/empsit/cpseea19.htm"),
        ("20260905000000", "200", "https://bls.gov/web/empsit/cpseea19.htm"),
        ("20260906000000", "200"),
    )
    index = resolve_pending.a19_window_captures(WINDOW, reader(index, {}, []))
    assert index.captures == [replay_url("20260906000000")]
    assert (index.listed, index.other_status, index.other_form) == (3, 0, 2)
    assert index.describe(WINDOW).endswith(
        "3 capture(s) dated inside the registered window "
        f"{WINDOW!r}, 1 of them HTTP 200 for this exact URL; "
        "2 under another form of the URL"
    )


def test_a_closed_window_with_unread_captures_under_another_form_defers() -> None:
    calls: list[str] = []
    index = cdx(
        ("20260904170006", "200", "http://www.bls.gov/web/empsit/cpseea19.htm"),
        ("20260905000000", "200"),
    )
    pages = {"20260905000000": fixture("2026-07")}
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, calls)
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("WINDOW OUTCOME UNKNOWN (deferring)")
    assert "1 of them HTTP 200 for this exact URL; 1 under another form" in verdict
    assert "all 1 HTTP 200 capture(s) were read and none prints 2026-08" in verdict
    assert "1 row(s) under another form of the URL were not read" in verdict
    assert "WINDOW MISSED" not in verdict
    assert identity_url("20260904170006") not in calls


def test_a_closed_window_whose_only_rows_are_403s_is_missed() -> None:
    # A stored 403 holds no table; nothing readable, nothing unknown.
    index = cdx(("20260904170006", "403"), ("20260905000000", "403"))
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, {}, [])
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("FIRST-PRINT WINDOW MISSED (refusing)")
    assert "0 of them HTTP 200 for this exact URL; 2 with another status" in verdict
    assert "all 0 HTTP 200 capture(s) were read and none prints 2026-08" in verdict


def test_a_row_without_a_status_is_read_or_accounted_for_by_its_digest() -> None:
    # A row without a status is asked for at its own timestamp like any
    # other. When the Archive does not serve it there, a read capture with
    # the same digest says what it printed: the same bytes.
    calls: list[str] = []
    index = cdx(
        ("20260903010101", "200", "", digest("july")),
        ("20260903120000", "-", "", digest("july")),
        ("20260904170006", "200", "", digest("aug")),
    )
    pages = {
        "20260903010101": fixture("2026-07"),
        CAPTURES["2026-08"]: fixture("2026-08"),
    }
    found = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, calls)
    )
    assert (found.url, found.verdict, found.witness) == (
        capture_url("2026-08"),
        "",
        None,
    )
    assert identity_url("20260903120000") in calls
    # A later row without a status never holds a resolution back, and is
    # not asked for.
    calls.clear()
    index = cdx(
        ("20260904170006", "200", "", digest("aug")),
        ("20260906000000", "-", "", digest("z")),
    )
    url, _, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, calls)
    )
    assert (url, verdict) == (capture_url("2026-08"), "")
    assert identity_url("20260906000000") not in calls
    # Served at its own timestamp and printing the month, it IS the
    # earliest capture.
    calls.clear()
    index = cdx(
        ("20260903120000", "-", "", digest("aug")),
        ("20260904170006", "200", "", digest("aug")),
    )
    served = {"20260903120000": fixture("2026-08"), **pages}
    found = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, served, calls)
    )
    assert (found.url, found.witness) == (replay_url("20260903120000"), None)
    assert found.raw == fixture("2026-08").encode()
    assert identity_url("20260904170006") not in calls


def test_an_unserved_earlier_row_with_the_same_digest_is_the_witness() -> None:
    # The Archive lists Sep 3 with the digest of the Sep 4 capture but does
    # not serve Sep 3 at its own timestamp. Sep 3 is the earliest print; Sep
    # 4 supplied its bytes, and the result says so.
    calls: list[str] = []
    index = cdx(
        ("20260903120000", "-", "", digest("aug")),
        ("20260904170006", "200", "", digest("aug")),
    )
    pages = {CAPTURES["2026-08"]: fixture("2026-08")}
    found = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, calls)
    )
    assert (found.url, found.verdict) == (capture_url("2026-08"), "")
    assert found.witness == "20260903120000"
    assert found.raw == fixture("2026-08").encode()
    assert identity_url("20260903120000") in calls
    # The same through the main loop: the fact names both.
    url, raw, verdict = found
    assert (url, raw, verdict) == (found.url, found.raw, "")


def test_a_later_capture_can_account_for_an_earlier_unserved_row() -> None:
    # Sep 3 (no status, digest J) is not served; Sep 4 prints August; Sep 5
    # carries digest J and prints July. Sep 3 therefore printed July, and
    # Sep 4 is the earliest August print. The walk reads on to find that
    # out instead of deferring.
    calls: list[str] = []
    index = cdx(
        ("20260903120000", "-", "", digest("j")),
        ("20260904170006", "200", "", digest("aug")),
        ("20260905000000", "200", "", digest("j")),
    )
    pages = {
        CAPTURES["2026-08"]: fixture("2026-08"),
        "20260905000000": fixture("2026-07"),
    }
    found = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, calls)
    )
    assert (found.url, found.verdict, found.witness) == (
        capture_url("2026-08"),
        "",
        None,
    )
    assert identity_url("20260905000000") in calls
    # When the later capture with that digest prints August too, the
    # earliest August print is Sep 3, and its bytes are Sep 5's.
    pages["20260905000000"] = fixture("2026-08")
    found = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, [])
    )
    assert (found.url, found.witness) == (
        replay_url("20260905000000"),
        "20260903120000",
    )


def test_a_missing_digest_is_unknown_not_a_match() -> None:
    # The index may list "-" where it has no digest. Two such rows are not
    # the same bytes, so an unserved row without a digest is never accounted
    # for: a closed window stays unknown, and a later August capture cannot
    # resolve past it.
    index = cdx(
        ("20260903120000", "-", "", "-"),
        ("20260904170006", "200", "", "-"),
    )
    pages = {CAPTURES["2026-08"]: fixture("2026-07")}
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, [])
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("WINDOW OUTCOME UNKNOWN (deferring)")
    assert "1 remain unknown" in verdict
    index = cdx(
        ("20260903120000", "-", "", "-"),
        ("20260904170006", "200", "", "-"),
        ("20260905000000", "200", "", "-"),
    )
    pages["20260905000000"] = fixture("2026-08")
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, [])
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("EARLIER ROW UNREAD (deferring)")


def test_an_earlier_unaccounted_row_without_a_status_defers() -> None:
    calls: list[str] = []
    index = cdx(
        ("20260903120000", "-", "", digest("unknown")),
        ("20260904170006", "200", "", digest("aug")),
    )
    pages = {CAPTURES["2026-08"]: fixture("2026-08")}
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, calls)
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("EARLIER ROW UNREAD (deferring)")
    assert "20260903120000" in verdict
    assert "could not be read or identified at their own timestamp" in verdict
    # It was asked for; the Archive did not serve it.
    assert identity_url("20260903120000") in calls
    # Served but unidentifiable at its own timestamp: the same.
    served = {"20260903120000": "<html>Archive error</html>", **pages}
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, served, [])
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("EARLIER ROW UNREAD (deferring)")


def test_a_closed_window_with_an_unaccounted_row_without_a_status_is_unknown() -> None:
    index = cdx(
        ("20260903120000", "-", "", digest("unknown")), ("20260905000000", "200")
    )
    pages = {"20260905000000": fixture("2026-07")}
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, [])
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("WINDOW OUTCOME UNKNOWN (deferring)")
    assert "1 without a status" in verdict
    assert (
        "of 1 row(s) without a status, 0 were served at their own timestamp and "
        "read, 0 share the digest of a read capture, 1 remain unknown" in verdict
    )
    # While the window is open the same rows still get a capture request,
    # and the verdict does not claim the month is unprinted, only unread.
    calls: list[str] = []
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 6), reader(index, pages, calls)
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("none of the rows read inside the registered window")
    assert "1 remain unknown" in verdict
    assert resolve_pending.A19_CAPTURE_REQUESTED in verdict
    assert any("/save/" in call for call in calls)


def test_window_missed_reports_what_the_index_listed_but_could_not_use() -> None:
    # bls.gov answers non-browser clients with 403, so an Archive crawl can
    # be stored as one. "No capture" and "no usable capture" are different
    # findings, and the ruling on a closed window rests on the difference.
    calls: list[str] = []
    index = cdx(("20260904170006", "403"), ("20260905000000", "200"))
    pages = {"20260905000000": fixture("2026-07")}
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, calls)
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith(
        "FIRST-PRINT WINDOW MISSED (refusing): the Archive's index lists 2 "
        "capture(s) dated inside the registered window"
    )
    assert "1 of them HTTP 200 for this exact URL; 1 with another status" in verdict
    assert "all 1 HTTP 200 capture(s) were read and none prints 2026-08" in verdict
    assert identity_url("20260904170006") not in calls


@pytest.mark.parametrize(
    "body",
    [
        b'{"error":"Blocked Site Error"}',
        b"429",
        b"null",
        b'[["timestamp","original","statuscode","digest"], 5, null]',
        b"<html>429 Too Many Requests</html>",
        # A table that is not the one requested.
        b'[["timestamp","statuscode"],["20260904170006","200"]]',
        b'[["timestamp","original","statuscode"],["20260904170006","https://www.bls.gov/web/empsit/cpseea19.htm","200"]]',
        b'[["error","blocked"]]',
        b'[["20260904170006","https://www.bls.gov/web/empsit/cpseea19.htm","200","X"]]',
        # Row-level damage must not read as "the window holds no capture".
        b'[["timestamp","original","statuscode","digest"],["20260904170006","https://www.bls.gov/web/empsit/cpseea19.htm","200"]]',
        b'[["timestamp","original","statuscode","digest"],["2026090417","https://www.bls.gov/web/empsit/cpseea19.htm","200","X"]]',
        b'[["timestamp","original","statuscode","digest"],[20260904170006,"https://www.bls.gov/web/empsit/cpseea19.htm","200","X"]]',
        b'[["timestamp","original","statuscode","digest"],["20260904170006","","200","X"]]',
        b'[["timestamp","original","statuscode","digest"],["20260904170006","https://www.bls.gov/web/empsit/cpseea19.htm","200",""]]',
        # An empty body, an impossible date and statuses that are neither
        # three digits nor "-".
        b"",
        b'[["timestamp","original","statuscode","digest"],["20260900170006","https://www.bls.gov/web/empsit/cpseea19.htm","200","X"]]',
        b'[["timestamp","original","statuscode","digest"],["20260904170006","https://www.bls.gov/web/empsit/cpseea19.htm","blocked","X"]]',
        b'[["timestamp","original","statuscode","digest"],["20260904170006","https://www.bls.gov/web/empsit/cpseea19.htm","-200","X"]]',
        b'[["timestamp","original","statuscode","digest"],["20260904170006","https://www.bls.gov/web/empsit/cpseea19.htm","20","X"]]',
        # One stamp, two statuses.
        b'[["timestamp","original","statuscode","digest"],["20260904170006","https://www.bls.gov/web/empsit/cpseea19.htm","403","X"],["20260904170006","https://www.bls.gov/web/empsit/cpseea19.htm","200","X"]]',
    ],
)
def test_a_malformed_index_defers_and_never_escapes(body: bytes) -> None:
    calls: list[str] = []
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(body, {}, calls)
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("WAYBACK INDEX FETCH FAILED (deferring)")


def test_only_the_json_empty_list_is_an_empty_index() -> None:
    empty = resolve_pending.a19_window_captures(WINDOW, reader(b"[]", {}, []))
    assert (empty.captures, empty.listed) == ([], 0)
    header_only = json.dumps([HEADER]).encode()
    assert (
        resolve_pending.a19_window_captures(
            WINDOW, reader(header_only, {}, [])
        ).captures
        == []
    )


def test_discovery_takes_the_earliest_capture_that_prints_the_month() -> None:
    calls: list[str] = []
    index = cdx(
        ("20260903010101", "200"),
        ("20260904170006", "200"),
        ("20260909090909", "200"),
    )
    pages = {
        "20260903010101": fixture("2026-07"),  # before the release: still July
        "20260904170006": fixture("2026-08"),
        "20260909090909": fixture("2026-08"),
    }
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, calls)
    )
    assert (url, verdict) == (capture_url("2026-08"), "")
    assert resolve_pending.a19_values_from_html(raw.decode()) == ANCHORS["2026-08"]
    assert identity_url("20260909090909") not in calls
    assert not any("/save/" in call for call in calls)


def test_discovery_defers_before_the_window_without_touching_the_network() -> None:
    calls: list[str] = []
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 1), reader(cdx(), {}, calls)
    )
    assert (url, raw, calls) == (None, None, [])
    assert "opens 2026-09-02 (deferring)" in verdict


def test_discovery_asks_for_a_capture_while_the_window_is_open() -> None:
    calls: list[str] = []
    index = cdx(("20260903010101", "200"))
    pages = {"20260903010101": fixture("2026-07")}
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 3), reader(index, pages, calls)
    )
    assert (url, raw) == (None, None)
    assert resolve_pending.A19_CAPTURE_REQUESTED in verdict
    assert verdict.endswith("(deferring)")
    assert "the Archive's index lists 1 capture(s)" in verdict
    assert "all 1 HTTP 200 capture(s) were read and none prints 2026-08" in verdict
    assert [call for call in calls if "/save/" in call] == [
        f"https://web.archive.org/save/{resolve_pending.A19_SOURCE_URL}"
    ]
    # A second window of the same run does not ask again.
    calls.clear()
    _, _, quiet = resolve_pending.a19_registered_capture(
        "2026-08",
        WINDOW,
        dt.date(2026, 9, 3),
        reader(index, pages, calls),
        request_capture=False,
    )
    assert not any("/save/" in call for call in calls)
    assert quiet.endswith("(deferring)")


def test_a_failed_save_request_still_counts_as_the_runs_request() -> None:
    # 2026-09-21: three save requests were answered HTTP 500 and a capture
    # appeared in the index anyway. The verdict must not call that a failure,
    # and the run must not ask again for its other windows.
    saves: list[str] = []

    def read(url: str) -> tuple[bytes, str]:
        if url.startswith("https://web.archive.org/cdx/"):
            return cdx(), url
        saves.append(url)
        raise urllib.error.HTTPError(url, 500, "Internal Server Error", None, None)

    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 3), read
    )
    assert (url, raw) == (None, None)
    assert resolve_pending.A19_CAPTURE_REQUESTED in verdict
    assert "outcome unknown" in verdict and "failed" not in verdict
    assert verdict.endswith("(deferring)")
    assert len(saves) == 1


def test_window_missed_means_the_whole_index_was_read_and_nothing_prints_it() -> None:
    calls: list[str] = []
    july_window = {"start": "2026-07-29", "end": "2026-08-06"}
    index = cdx(("20260801120000", "200"))
    pages = {"20260801120000": fixture("2026-06")}
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-07", july_window, dt.date(2026, 9, 20), reader(index, pages, calls)
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith(
        "FIRST-PRINT WINDOW MISSED (refusing): the Archive's index lists 1 "
        "capture(s) dated inside the registered window"
    )
    assert "; all 1 HTTP 200 capture(s) were read and none prints 2026-07" in verdict
    assert not any("/save/" in call for call in calls)


def test_an_unread_earlier_capture_defers_instead_of_being_skipped() -> None:
    # The first capture 404s and the second prints August. Taking the second
    # would break "earliest": the unread one may print August too.
    calls: list[str] = []
    index = cdx(("20260904170006", "200"), ("20260905050505", "200"))
    pages = {"20260905050505": fixture("2026-08")}
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, calls)
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("CAPTURE READ FAILED (deferring)")
    assert "20260904170006" in verdict and "WINDOW MISSED" not in verdict
    assert identity_url("20260905050505") not in calls


def test_an_unidentified_earlier_capture_defers_instead_of_being_skipped() -> None:
    # An error page is not "a different month". Skipping it would let a later
    # capture stand in for the earliest, or leave a closed window "missed".
    index = cdx(("20260904170006", "200"), ("20260905050505", "200"))
    for body in ("", "<html><body>Archive error</body></html>", "\udcff"):
        calls: list[str] = []
        pages = {"20260904170006": body, "20260905050505": fixture("2026-08")}

        def read(url: str, pages=pages, calls=calls) -> tuple[bytes, str]:
            calls.append(url)
            if url.startswith("https://web.archive.org/cdx/"):
                return index, url
            stamp = url.split("/web/")[1][:14]
            return pages[stamp].encode(errors="surrogateescape"), url

        url, raw, verdict = resolve_pending.a19_registered_capture(
            "2026-08", WINDOW, dt.date(2026, 9, 20), read
        )
        assert (url, raw) == (None, None)
        assert verdict.startswith("CAPTURE UNIDENTIFIED (deferring)")
        assert identity_url("20260905050505") not in calls


def test_a_corrupt_gzip_capture_defers_and_never_escapes() -> None:
    corrupt = bytes.fromhex("1f8b0800000000000000") + b"\x07" + b"\x00" * 8

    def read(url: str) -> tuple[bytes, str]:
        if url.startswith("https://web.archive.org/cdx/"):
            return cdx(("20260904170006", "200")), url
        return corrupt, url

    with pytest.raises(resolve_pending.A19CaptureError, match="not valid gzip"):
        resolve_pending.a19_read_capture(capture_url("2026-08"), read)
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), read
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("CAPTURE READ FAILED (deferring)")


def test_a_capped_scan_is_not_reported_as_a_missed_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(resolve_pending, "A19_MAX_WINDOW_CAPTURES", 2)
    stamps = ["20260903010101", "20260903020202", "20260904170006"]
    pages = {
        stamps[0]: fixture("2026-07"),
        stamps[1]: fixture("2026-07"),
        stamps[2]: fixture("2026-08"),
    }
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08",
        WINDOW,
        dt.date(2026, 9, 20),
        reader(cdx(*[(stamp, "200") for stamp in stamps]), pages, []),
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith(
        "CAPTURE SCAN LIMIT REACHED (deferring): the first 2 of 3"
    )
    assert "WINDOW MISSED" not in verdict
    # Rows without a status count toward the cap too: they are read.
    index = cdx((stamps[0], "-"), (stamps[1], "200"), (stamps[2], "200"))
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, [])
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith(
        "CAPTURE SCAN LIMIT REACHED (deferring): the first 2 of 3"
    )


def test_discovery_defers_when_the_index_is_unreachable() -> None:
    def read(url: str) -> tuple[bytes, str]:
        raise urllib.error.URLError("connection refused")

    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), read
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("WAYBACK INDEX FETCH FAILED (deferring)")


# -- through the main loop ----------------------------------------------------


class _Response:
    def __init__(self, body: bytes, url: str) -> None:
        self._body = body
        self._url = url

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url


def run_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    registrations: list[dict],
    *,
    today: str = "2026-09-20",
    archive: dict[str, str] | None = None,
    index: bytes = b"[]",
    served_as: dict[str, str] | None = None,
    resolution_dates: dict[str, str] | None = None,
    save_status: int | None = None,
    unregistered_first: list[tuple[str, str, str]] | None = None,
    fail_first_read_of: str | None = None,
) -> tuple[str, list[str]]:
    """Run the resolver dry against a stand-in Archive.

    ``archive`` maps capture stamps to tables (default: the three real
    captures). ``served_as`` makes the Archive answer one stamp with another.
    """

    pages = (
        archive
        if archive is not None
        else {stamp: fixture(period) for period, stamp in CAPTURES.items()}
    )
    if index == b"[]":
        index = cdx(*[(stamp, "200") for stamp in sorted(pages)])
    year, month, day = (int(part) for part in today.split("-"))

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(year, month, day)

    contracts = {reg["contract"]["dataPointId"]: reg for reg in registrations}
    log = {"entries": [], "resolutionLinks": []}
    for ref, unit, resolution_date in unregistered_first or []:
        log["entries"].append(
            {
                "kind": "prediction_recorded",
                "forecastSlug": ref,
                "resolutionDate": resolution_date,
                "unit": unit,
                "pointEstimate": 7700,
            }
        )
        log["resolutionLinks"].append(
            {"status": "pending", "targetFactRef": ref, "forecastSlug": ref}
        )
    failed: set[str] = set()
    for ref, reg in contracts.items():
        slug = reg["contract"]["catalogSlug"]
        window = reg["contract"]["sourceBinding"]["expectedReleaseWindow"]
        log["entries"].append(
            {
                "kind": "prediction_recorded",
                "forecastSlug": slug,
                "resolutionDate": (resolution_dates or {}).get(ref, window["end"]),
                "unit": reg["contract"]["unit"],
                "pointEstimate": 7.7,
            }
        )
        log["resolutionLinks"].append(
            {"status": "pending", "targetFactRef": ref, "forecastSlug": slug}
        )
    calls: list[str] = []

    def fake_urlopen(request, timeout: int = 120):
        url = request if isinstance(request, str) else request.full_url
        calls.append(url)
        if url.startswith("https://web.archive.org/cdx/"):
            return _Response(index, url)
        if url.startswith("https://web.archive.org/save/"):
            if save_status is not None:
                raise urllib.error.HTTPError(url, save_status, "error", None, None)
            return _Response(b"saved", url)
        for stamp, html in pages.items():
            if url == identity_url(stamp):
                if stamp == fail_first_read_of and stamp not in failed:
                    failed.add(stamp)
                    raise urllib.error.HTTPError(url, 503, "offline", None, None)
                final = identity_url((served_as or {}).get(stamp, stamp))
                return _Response(html.encode(), final)
        raise urllib.error.HTTPError(url, 404, "no capture", None, None)

    monkeypatch.setattr(resolve_pending.dt, "date", FixedDate)
    monkeypatch.setattr(resolve_pending, "utc_now", lambda: f"{today}T13:40:00Z")
    monkeypatch.setattr(resolve_pending, "load_thesis_log", lambda _url: log)
    monkeypatch.setattr(
        resolve_pending, "ledger_state", lambda *_args: ("", "blob", "b" * 40)
    )
    monkeypatch.setattr(resolve_pending, "registration_contracts", lambda: contracts)
    monkeypatch.setattr(resolve_pending.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])
    assert resolve_pending.main() == 0
    return capsys.readouterr().out, calls


def test_main_resolves_august_in_millions_and_refuses_the_july_window(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    august = registration()
    # Registered 2026-07-29..2026-08-06; BLS published July on 2026-08-07, so
    # no capture of the July table can fall inside this window. The 2026-07
    # pin is dated outside it and is never read for this cell.
    july = registration("2026-07", ("2026-07-29", "2026-08-06"))
    output, calls = run_main(monkeypatch, capsys, [august, july])

    assert f"resolve {august['contract']['dataPointId']} -> 7.716 millions" in output
    assert "UNIT MISMATCH" not in output
    assert (
        "A-19 FIRST-PRINT WINDOW MISSED (refusing): the Archive's index lists 0 "
        "capture(s) dated inside the registered window" in output
    )
    assert july["contract"]["dataPointId"] in output
    assert "dry-run: would append 1 row(s)" in output
    assert identity_url(CAPTURES["2026-07"]) not in calls
    # The publisher date the row vouches for is the capture's, not the
    # forecast's resolutionDate (the window's end, 2026-09-10).
    assert '"observed_at": "2026-09-04"' in output


def test_main_names_the_unserved_earlier_row_the_fact_rests_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    index = cdx(
        ("20260903120000", "-", "", digest("aug")),
        (CAPTURES["2026-08"], "200", "", digest("aug")),
    )
    facts: list[dict] = []
    real_fact = resolve_pending.a19_fact

    def spy(*args: object) -> dict:
        facts.append(real_fact(*args))
        return facts[-1]

    monkeypatch.setattr(resolve_pending, "a19_fact", spy)
    output, calls = run_main(
        monkeypatch,
        capsys,
        [registration()],
        archive={CAPTURES["2026-08"]: fixture("2026-08")},
        index=index,
    )
    assert "-> 7.716 millions" in output
    assert [fact["source"]["source_file"] for fact in facts] == [
        "cpseea19.htm (Wayback capture 20260904170006; the Archive's index lists "
        "the same digest at 20260903120000, not served at that timestamp)"
    ]
    # The day the row vouches for is the capture whose bytes were read.
    assert '"observed_at": "2026-09-04"' in output
    assert identity_url("20260903120000") in calls


def test_main_takes_the_earliest_capture_even_when_a_pin_names_a_later_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # An earlier in-window capture that already prints August exists. A
    # registered cell never reads the pin; it walks the index in order.
    earlier = "20260904130000"
    archive = {earlier: fixture("2026-08"), CAPTURES["2026-08"]: fixture("2026-08")}
    output, calls = run_main(monkeypatch, capsys, [registration()], archive=archive)
    assert "-> 7.716 millions" in output
    assert identity_url(earlier) in calls
    assert identity_url(CAPTURES["2026-08"]) not in calls


def test_main_does_no_archive_io_before_a_registered_window_opens(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output, calls = run_main(monkeypatch, capsys, [registration()], today="2026-09-01")
    assert "release window opens 2026-09-02 (deferring)" in output
    assert calls == []


def test_main_discovers_a_capture_for_a_month_with_no_pin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Two September cells with different registered windows, as on disk. BLS
    # publishes September on 2026-10-02; the table below stands in for it.
    early = registration("2026-09", ("2026-09-30", "2026-10-08"))
    late = registration(
        "2026-09",
        ("2026-10-06", "2026-10-14"),
        dataPointId=f"{SERIES.replace('production', 'healthcare_support')}"
        ".september_2026.first_print",
        catalogSlug="cps-healthcare-support-employment-september-2026",
        series=SERIES.replace("production", "healthcare_support"),
    )
    late["contract"]["sourceBinding"].update(
        field="Healthcare support occupations",
        sourceSeriesId=SERIES.replace("production", "healthcare_support"),
    )
    september = fixture("2026-08").replace("Aug.", "Sept.")
    archive = {
        "20261001120000": fixture("2026-08"),  # before the release
        "20261003120000": september,
        "20261007120000": september,
    }
    index = cdx(*[(stamp, "200") for stamp in archive])

    # Inside the first window, before the second opens, and days before the
    # forecasts' resolutionDate: the first cell resolves from the earliest
    # capture that prints September; the second defers.
    output, calls = run_main(
        monkeypatch,
        capsys,
        [early, late],
        today="2026-10-04",
        archive=archive,
        index=index,
    )
    assert f"resolve {early['contract']['dataPointId']} -> 7.716 millions" in output
    assert "release window opens 2026-10-06 (deferring): " in output
    # The earliest capture that prints September, not the later one, and not
    # the pre-release capture that still printed August.
    assert identity_url("20261003120000") in calls
    assert identity_url("20261007120000") not in calls
    assert not any("/save/" in call for call in calls)


def test_main_asks_for_one_capture_per_run_while_windows_are_open(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = registration("2026-09", ("2026-09-30", "2026-10-08"))
    second = registration(
        "2026-09",
        ("2026-10-01", "2026-10-09"),
        dataPointId=f"{SERIES.replace('production', 'healthcare_support')}"
        ".september_2026.first_print",
        catalogSlug="cps-healthcare-support-employment-september-2026",
        series=SERIES.replace("production", "healthcare_support"),
    )
    second["contract"]["sourceBinding"].update(
        field="Healthcare support occupations",
        sourceSeriesId=SERIES.replace("production", "healthcare_support"),
    )
    output, calls = run_main(
        monkeypatch, capsys, [first, second], today="2026-10-02", archive={}
    )
    assert output.count(resolve_pending.A19_CAPTURE_REQUESTED) == 1
    assert len([call for call in calls if "/save/" in call]) == 1
    assert "nothing new to record" in output

    # The same when the save endpoint answers 500: still one request.
    output, calls = run_main(
        monkeypatch,
        capsys,
        [first, second],
        today="2026-10-02",
        archive={},
        save_status=500,
    )
    assert output.count(resolve_pending.A19_CAPTURE_REQUESTED) == 1
    assert "outcome unknown" in output
    assert len([call for call in calls if "/save/" in call]) == 1


def test_main_defers_when_the_archive_answers_with_another_capture(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    listed = "20260905000000"
    output, _ = run_main(
        monkeypatch,
        capsys,
        [registration()],
        archive={listed: fixture("2026-08")},
        served_as={listed: CAPTURES["2026-08"]},
    )
    assert "A-19 CAPTURE READ FAILED (deferring)" in output
    assert "was served" in output
    assert "nothing new to record" in output


def test_main_refuses_a_pin_whose_capture_prints_another_month(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Pins serve only cells that predate registration. A wrong pin (the June
    # key pointing at the July table) must refuse, not record July as June.
    ref = f"{SERIES}.june_2026.first_print"
    pins = dict(resolve_pending.A19_SNAPSHOT_URLS)
    pins["2026-06"] = replay_url(CAPTURES["2026-07"])
    monkeypatch.setattr(resolve_pending, "A19_SNAPSHOT_URLS", pins)

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(2026, 9, 20)

    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "june",
                "resolutionDate": "2026-07-02",
                "unit": "thousands",
                "pointEstimate": 7700,
            }
        ],
        "resolutionLinks": [
            {"status": "pending", "targetFactRef": ref, "forecastSlug": "june"}
        ],
    }

    def fake_urlopen(request, timeout: int = 120):
        url = request.full_url
        assert url == identity_url(CAPTURES["2026-07"])
        return _Response(fixture("2026-07").encode(), url)

    monkeypatch.setattr(resolve_pending.dt, "date", FixedDate)
    monkeypatch.setattr(resolve_pending, "load_thesis_log", lambda _url: log)
    monkeypatch.setattr(
        resolve_pending, "ledger_state", lambda *_args: ("", "blob", "b" * 40)
    )
    monkeypatch.setattr(resolve_pending, "registration_contracts", lambda: {})
    monkeypatch.setattr(resolve_pending.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])
    assert resolve_pending.main() == 0
    output = capsys.readouterr().out
    assert "A-19 SNAPSHOT PERIOD MISMATCH (refusing)" in output
    assert "the capture prints 2026-07, not 2026-06" in output
    assert "nothing new to record" in output


def test_a_failed_pin_fetch_does_not_poison_a_registered_cells_discovery(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # An unregistered August cell fails to fetch the pinned capture; a
    # registered August cell then discovers and reads the same capture. The
    # verified bytes must replace the failed cache entry, not be discarded.
    august = registration()
    output, _ = run_main(
        monkeypatch,
        capsys,
        [august],
        unregistered_first=[
            (
                f"{SERIES.replace('production', 'healthcare_support')}"
                ".august_2026.first_print",
                "thousands",
                "2026-09-04",
            )
        ],
        fail_first_read_of=CAPTURES["2026-08"],
    )
    assert "A-19 snapshot fetch failed (deferring)" in output
    assert f"resolve {august['contract']['dataPointId']} -> 7.716 millions" in output


def test_a_capture_shared_by_a_pin_cell_and_a_registered_cell_is_read_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    august = registration()
    output, calls = run_main(
        monkeypatch,
        capsys,
        [august],
        unregistered_first=[
            (
                f"{SERIES.replace('production', 'healthcare_support')}"
                ".august_2026.first_print",
                "thousands",
                "2026-09-04",
            )
        ],
    )
    assert "-> 5709.0 thousands" in output
    assert f"resolve {august['contract']['dataPointId']} -> 7.716 millions" in output
    assert calls.count(identity_url(CAPTURES["2026-08"])) == 1


def test_main_refuses_a_registered_contract_with_a_drifted_transform(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drifted = registration()
    drifted["contract"]["sourceBinding"]["transform"] = {
        "operation": "multiply",
        "factor": 0.01,
    }
    output, _ = run_main(monkeypatch, capsys, [copy.deepcopy(drifted)])
    assert "registered A-19 contract differs in transform" in output
    assert "nothing new to record" in output


def test_main_leaves_an_unregistered_cell_in_thousands_on_its_pin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = f"{SERIES}.june_2026.first_print"

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(2026, 9, 20)

    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "june",
                "resolutionDate": "2026-07-02",
                "unit": "thousands",
                "pointEstimate": 7700,
            }
        ],
        "resolutionLinks": [
            {"status": "pending", "targetFactRef": ref, "forecastSlug": "june"}
        ],
    }

    def fake_urlopen(request, timeout: int = 120):
        url = request.full_url
        assert url == identity_url(CAPTURES["2026-06"])
        return _Response(fixture("2026-06").encode(), url)

    monkeypatch.setattr(resolve_pending.dt, "date", FixedDate)
    monkeypatch.setattr(resolve_pending, "load_thesis_log", lambda _url: log)
    monkeypatch.setattr(
        resolve_pending, "ledger_state", lambda *_args: ("", "blob", "b" * 40)
    )
    monkeypatch.setattr(resolve_pending, "registration_contracts", lambda: {})
    monkeypatch.setattr(resolve_pending.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])
    assert resolve_pending.main() == 0
    output = capsys.readouterr().out
    assert f"resolve {ref} -> 7759.0 thousands" in output
    assert '"observed_at": "2026-07-02"' in output
