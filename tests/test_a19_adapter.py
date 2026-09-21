"""BLS CPS Table A-19: registered unit, capture identity, first-print window.

The fixtures are the table element of three real Internet Archive captures
of https://www.bls.gov/web/empsit/cpseea19.htm (tests/fixtures/a19/README.md).
"""

from __future__ import annotations

import copy
import datetime as dt
import gzip
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
    "html",
    [
        "",
        "<table><tr><th>Occupation</th></tr></table>",
        # One header only: not the year-apart pair the table prints.
        "<th>July<br/>2026</th>",
        # Two different months: a page in transition, or not this table.
        "<th>July<br/>2025</th><th>Aug.<br/>2026</th>",
        # Same month, two years apart.
        "<th>July<br/>2024</th><th>July<br/>2026</th>",
        # A month label BLS does not print.
        "<th>Julio<br/>2025</th><th>Julio<br/>2026</th>",
    ],
)
def test_capture_period_fails_closed(html: str) -> None:
    assert resolve_pending.a19_snapshot_period(html) is None


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
    # The family's one adapter is the registrable ``bls-cps-a19``. The
    # contracts registered before it existed name generic-url, which is
    # deliberately NOT a family adapter, so the registration gate can never
    # mistake it for one; main() resolves them through the legacy exception
    # (tests/test_a19_registrable_adapter.py) once a19_execution_spec has
    # pinned every other field.
    assert resolve_pending.FAMILY_ADAPTERS["a19"] == {"bls-cps-a19"}
    drifted = registration()
    drifted["contract"]["sourceBinding"]["adapter"] = "alfred-fred"
    assert resolve_pending.binding_adapter_mismatch("a19", drifted) == "alfred-fred"
    assert (
        resolve_pending.binding_adapter_mismatch("a19", registration())
        == resolve_pending.A19_LEGACY_BINDING_ADAPTER
        == "generic-url"
    )
    admitted = registration()
    admitted["contract"]["sourceBinding"]["adapter"] = "bls-cps-a19"
    assert resolve_pending.binding_adapter_mismatch("a19", admitted) is None


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


def cdx(*rows: tuple[str, str]) -> bytes:
    return json.dumps(
        [["timestamp", "statuscode"], *[list(row) for row in rows]]
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
    # The toolbar form of the same capture, and http, are the same capture.
    assert (
        resolve_pending.a19_read_capture(
            capture_url("2026-08"),
            lambda url: (
                b"x",
                served.replace("id_", "").replace("https://web", "http://web"),
            ),
        )
        == b"x"
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
        ("20260905000000", "403"),
        ("20260911000000", "200"),  # after the window
        ("2026090417", "200"),  # malformed
    )
    captures = resolve_pending.a19_window_captures(WINDOW, reader(index, {}, calls))
    assert captures == [replay_url("20260904170006"), replay_url("20260910235959")]
    assert "from=20260902000000" in calls[0] and "to=20260910235959" in calls[0]


@pytest.mark.parametrize(
    "body",
    [
        b'{"error":"Blocked Site Error"}',
        b"429",
        b"null",
        b'[["timestamp","statuscode"], 5, null]',
        b"<html>429 Too Many Requests</html>",
    ],
)
def test_a_malformed_index_defers_and_never_escapes(body: bytes) -> None:
    calls: list[str] = []
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(body, {}, calls)
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("WAYBACK INDEX FETCH FAILED (deferring)")


def test_an_empty_index_body_is_an_empty_index() -> None:
    assert resolve_pending.a19_window_captures(WINDOW, reader(b"", {}, [])) == []


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
    assert verdict.startswith("FIRST-PRINT WINDOW MISSED (refusing): none of the 1")
    assert not any("/save/" in call for call in calls)


def test_an_unreadable_capture_is_not_reported_as_a_missed_window() -> None:
    calls: list[str] = []
    index = cdx(("20260904170006", "200"), ("20260905050505", "200"))
    pages = {"20260905050505": fixture("2026-07")}  # the first one 404s
    url, raw, verdict = resolve_pending.a19_registered_capture(
        "2026-08", WINDOW, dt.date(2026, 9, 20), reader(index, pages, calls)
    )
    assert (url, raw) == (None, None)
    assert verdict.startswith("CAPTURE READ FAILED (deferring): 1 of 2")
    assert "WINDOW MISSED" not in verdict


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
    assert verdict.startswith("CAPTURE SCAN LIMIT REACHED (refusing): the first 2 of 3")
    assert "WINDOW MISSED" not in verdict


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
    year, month, day = (int(part) for part in today.split("-"))

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(year, month, day)

    contracts = {reg["contract"]["dataPointId"]: reg for reg in registrations}
    log = {"entries": [], "resolutionLinks": []}
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
        "A-19 FIRST-PRINT WINDOW MISSED (refusing): none of the 0 Internet "
        "Archive capture(s) dated inside the registered window" in output
    )
    assert july["contract"]["dataPointId"] in output
    assert "dry-run: would append 1 row(s)" in output
    assert identity_url(CAPTURES["2026-07"]) not in calls
    # The publisher date the row vouches for is the capture's, not the
    # forecast's resolutionDate (the window's end, 2026-09-10).
    assert '"observed_at": "2026-09-04"' in output


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


def test_main_refuses_a_pin_the_archive_answers_with_another_capture(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pins = dict(resolve_pending.A19_SNAPSHOT_URLS)
    pins["2026-08"] = replay_url("20260905000000")  # inside the window, no capture
    monkeypatch.setattr(resolve_pending, "A19_SNAPSHOT_URLS", pins)
    output, _ = run_main(
        monkeypatch,
        capsys,
        [registration()],
        archive={"20260905000000": fixture("2026-08")},
        served_as={"20260905000000": CAPTURES["2026-08"]},
    )
    assert "A-19 snapshot fetch failed (deferring)" in output
    assert "was served" in output
    assert "nothing new to record" in output


def test_main_refuses_a_pin_whose_capture_prints_another_month(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pins = dict(resolve_pending.A19_SNAPSHOT_URLS)
    # A wrong pin: the August key pointing at a capture inside August's window
    # that is really the July table.
    pins["2026-08"] = replay_url("20260903010101")
    monkeypatch.setattr(resolve_pending, "A19_SNAPSHOT_URLS", pins)
    output, _ = run_main(
        monkeypatch,
        capsys,
        [registration()],
        archive={"20260903010101": fixture("2026-07")},
    )
    assert "A-19 SNAPSHOT PERIOD MISMATCH (refusing)" in output
    assert "the capture prints 2026-07, not 2026-08" in output
    assert "nothing new to record" in output


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
