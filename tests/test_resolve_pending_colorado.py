"""The resolver's two Colorado legs, end to end through ``main()``.

HCPF Medicaid caseload replays the official files committed under
``tests/fixtures/co_hcpf`` (landing page, the caseload page of four report
PDFs with their ``pdftotext`` text, the September 2026 workbook) with the
``Last-Modified`` headers the live site sent on 2026-10-09. DOR net
individual income tax collections replays the workbook DOR published in
September 2026. No test touches the network or needs poppler.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import pathlib
import posixpath
import sys
from decimal import Decimal
from urllib.parse import unquote, urlparse

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import co_dor  # noqa: E402
import co_hcpf  # noqa: E402
import resolution_status  # noqa: E402
import resolve_pending  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from co_fixtures import (  # noqa: E402
    dor_workbook,
    hcpf_landing,
    hcpf_pdf_text,
    hcpf_rows,
    hcpf_workbook,
)

HCPF_FIXTURES = ROOT / "tests" / "fixtures" / "co_hcpf"
DOR_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "co_dor"
    / "general_fund_net_collections_published_2026-09.xlsx"
)
HCPF = "co.hcpf.medicaid.total_caseload.2026-08.first_print"
HCPF_NEXT = "co.hcpf.medicaid.total_caseload.2026-09.first_print"
DOR = "co.dor.individual_income_tax.net_collections.2026_07.first_print"
DOR_NEWEST = "co.dor.individual_income_tax.net_collections.2026_08.first_print"
DOR_NEXT = "co.dor.individual_income_tax.net_collections.2026_09.first_print"
# Last-Modified of each report PDF as served 2026-10-09 (report month -> header).
OFFICIAL_MODIFIED = {
    "2026-06": "Mon, 15 Jun 2026 20:20:16 GMT",
    "2026-07": "Wed, 15 Jul 2026 18:53:51 GMT",
    "2026-08": "Mon, 17 Aug 2026 18:00:45 GMT",
    "2026-09": "Mon, 14 Sep 2026 17:35:17 GMT",
}
SYNTHETIC_PDF = b"%PDF-synthetic\n"


def _log() -> dict:
    """The two published cells, and later months of each series."""
    cells = [
        # slug, ref, resolutionDate, unit, 80% interval (as published)
        ("co-medicaid", HCPF, "2026-09-15", "thousands", 1225.6, 1268.6),
        ("co-medicaid-next", HCPF_NEXT, "2026-10-01", "thousands", 1225.6, 1268.6),
        ("co-income-tax", DOR, "2026-08-31", "usd_billions", 0.42, 1.54),
        ("co-income-tax-newest", DOR_NEWEST, "2026-09-30", "usd_billions", 0.4, 1.5),
        ("co-income-tax-next", DOR_NEXT, "2026-10-01", "usd_billions", 0.4, 1.5),
    ]
    return {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": slug,
                "resolutionDate": release,
                "unit": unit,
                "interval80": {"lower": lower, "upper": upper},
            }
            for slug, _ref, release, unit, lower, upper in cells
        ],
        "resolutionLinks": [
            {"status": "pending", "forecastSlug": slug, "targetFactRef": ref}
            for slug, ref, *_ in cells
        ],
    }


def _official_page(report_period: str) -> bytes:
    return (HCPF_FIXTURES / f"report_{report_period}_caseload_page.pdf").read_bytes()


def _official_text(report_period: str) -> str:
    name = f"report_{report_period}_caseload_page.pdftotext.txt"
    return (HCPF_FIXTURES / name).read_text(encoding="utf-8")


def _synthetic_pdf(text: str) -> bytes:
    return SYNTHETIC_PDF + text.encode()


def _install(
    monkeypatch,
    refs: list[str],
    *,
    landing: bytes | None = None,
    pdfs: dict[str, bytes] | None = None,
    modified: dict[str, str | None] | None = None,
    workbook: bytes | Exception | None = None,
    dor: bytes | Exception | None = None,
    pdftotext: bool = True,
    no_pdftotext_for: frozenset[str] = frozenset(),
    content_types: dict[str, str] | None = None,
    landed: dict[str, str] | None = None,
) -> list[str]:
    """Wire ``main()`` to the fixtures; returns the list of URLs it fetched.

    Defaults replay the official files. ``pdfs`` and ``modified`` replace
    single report PDFs and their Last-Modified headers by report month;
    ``workbook`` replaces the report workbook (an exception makes the fetch
    fail); ``dor`` replaces the DOR workbook the same way. ``content_types``
    and ``landed`` replace a report PDF's Content-Type and the URL its
    request ends on; ``no_pdftotext_for`` makes ``pdftotext`` unavailable for
    those reports only.
    """
    log = _log()
    monkeypatch.setattr(resolve_pending, "load_thesis_log", lambda _url: log)
    monkeypatch.setattr(resolve_pending, "pending_claims_refs", lambda _log: [])
    full = resolve_pending.pending_adapter_refs
    monkeypatch.setattr(
        resolve_pending,
        "pending_adapter_refs",
        lambda log_: [item for item in full(log_) if item[0] in refs],
    )
    monkeypatch.setattr(
        resolve_pending, "ledger_state", lambda *_a: ("", "blob", "a" * 40)
    )
    monkeypatch.setattr(resolve_pending, "registration_contracts", lambda: {})
    monkeypatch.setattr(resolve_pending, "utc_now", lambda: "2026-10-09T23:57:45Z")
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])
    landing = (
        (HCPF_FIXTURES / "landing_2026-10-09.html").read_bytes()
        if landing is None
        else landing
    )
    workbook = (
        (HCPF_FIXTURES / "report_2026-09.xlsx").read_bytes()
        if workbook is None
        else workbook
    )
    dor = DOR_FIXTURE.read_bytes() if dor is None else dor
    texts = {
        hashlib.sha256(_official_page(period)).hexdigest(): _official_text(period)
        for period in OFFICIAL_MODIFIED
    }
    served: list[str] = []

    def hcpf_get(url: str):
        served.append(url)
        if url == co_hcpf.LANDING_URL:
            return landing, {"content-type": "text/html"}, "2026-10-09T23:57:45Z", url
        name = unquote(posixpath.basename(urlparse(url).path))
        match = co_hcpf.REPORT_FILE.fullmatch(name)
        assert match, f"unexpected HCPF request {url}"
        month = co_hcpf.MONTH_NAMES.index(match.group("month")) + 1
        report_period = f"{match.group('year')}-{month:02d}"
        if match.group("ext") == "xlsx":
            if isinstance(workbook, Exception):
                raise workbook
            return (
                workbook,
                {
                    "content-type": "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet",
                    "last-modified": OFFICIAL_MODIFIED["2026-09"],
                },
                "2026-10-09T23:57:47Z",
                url,
            )
        raw = (pdfs or {}).get(report_period) or _official_page(report_period)
        headers = {
            "content-type": (content_types or {}).get(report_period, "application/pdf")
        }
        stamp = {**OFFICIAL_MODIFIED, **(modified or {})}.get(report_period)
        if stamp:
            headers["last-modified"] = stamp
        final_url = (landed or {}).get(report_period, url)
        return raw, headers, "2026-10-09T23:57:46Z", final_url

    unreadable = {
        hashlib.sha256(_official_page(period)).hexdigest()
        for period in no_pdftotext_for
    }

    def pdf_text(raw: bytes):
        if not pdftotext or hashlib.sha256(raw).hexdigest() in unreadable:
            return None, "pdftotext is unavailable in the bare-Python resolver runtime"
        if raw.startswith(SYNTHETIC_PDF):
            return raw[len(SYNTHETIC_PDF) :].decode(), None
        return texts[hashlib.sha256(raw).hexdigest()], None

    def dor_get(url: str):
        served.append(url)
        assert url == co_dor.WORKBOOK_URL
        if isinstance(dor, Exception):
            raise dor
        return dor, {"last-modified": "Mon, 28 Sep 2026 21:09:16 GMT"}, "t", url

    monkeypatch.setattr(resolve_pending, "co_hcpf_http_get", hcpf_get)
    monkeypatch.setattr(resolve_pending, "co_hcpf_pdf_text", pdf_text)
    monkeypatch.setattr(resolve_pending, "co_dor_http_get", dor_get)
    return served


def _capture(monkeypatch) -> tuple[list[dict], list[dict]]:
    """(fact rows, capture envelopes) the run builds."""
    rows: list[dict] = []
    envelopes: list[dict] = []
    real_fact = resolve_pending.generic_fact
    real_envelope = resolve_pending.co_hcpf_capture_envelope

    def record_fact(*args, **kwargs):
        rows.append(real_fact(*args, **kwargs))
        return rows[-1]

    def record_envelope(**kwargs):
        raw = real_envelope(**kwargs)
        envelopes.append(json.loads(raw))
        return raw

    monkeypatch.setattr(resolve_pending, "generic_fact", record_fact)
    monkeypatch.setattr(resolve_pending, "co_hcpf_capture_envelope", record_envelope)
    return rows, envelopes


# --- routing -----------------------------------------------------------------


def test_router_claims_the_two_colorado_cells_and_nothing_else_of_theirs() -> None:
    todo = {item[0]: item for item in resolve_pending.pending_adapter_refs(_log())}
    _ref, kind, spec, period_type, period, release, forecast = todo[HCPF]
    assert (kind, period_type, period, release) == (
        "co_hcpf",
        "month",
        "2026-08",
        "2026-09-15",
    )
    assert resolve_pending.adapter_unit_matches(spec, forecast)
    assert len(spec["anchors"]) == 3
    # The DOR cell spells its month with an underscore.
    _ref, kind, spec, period_type, period, _release, forecast = todo[DOR]
    assert (kind, period_type, period) == ("co_dor", "month", "2026-07")
    assert resolve_pending.adapter_unit_matches(spec, forecast)
    # Another period shape under either stem is claimed by no family.
    log = _log()
    log["resolutionLinks"][0]["targetFactRef"] = (
        "co.hcpf.medicaid.total_caseload.fy2026.first_print"
    )
    log["resolutionLinks"][2]["targetFactRef"] = (
        "co.dor.individual_income_tax.net_collections.q3_2026.first_print"
    )
    refs = {item[0] for item in resolve_pending.pending_adapter_refs(log)}
    assert not {ref for ref in refs if "fy2026" in ref or "q3_2026" in ref}


@pytest.mark.parametrize(
    ("kind", "ref", "unit", "adapter"),
    [
        ("co_hcpf", HCPF, "thousands", "co-hcpf-premiums-report"),
        ("co_dor", DOR, "usd_billions", "co-dor-collections-workbook"),
    ],
)
def test_no_new_registration_can_bind_either_colorado_family(
    kind: str, ref: str, unit: str, adapter: str
) -> None:
    """Both legs serve only the cells published before they had an executor."""
    assert kind in resolve_pending.EXECUTION_PLAN_UNREGISTRABLE_FAMILIES
    assert kind not in resolve_pending.EXECUTION_PLAN_FAMILY_CHECKS
    mismatch = resolve_pending.binding_adapter_mismatch
    generic = {"contract": {"sourceBinding": {"adapter": "generic-url"}}}
    assert mismatch(kind, generic) == "generic-url"
    assert mismatch(kind, {"contract": {"sourceBinding": {"adapter": adapter}}}) is None

    def refusal(binding_adapter: str) -> str:
        contract = {
            "catalogSlug": "colorado-cell",
            "dataPointId": ref,
            "resolutionDate": "2026-09-15",
            "unit": unit,
            "sourceBinding": {
                "adapter": binding_adapter,
                "allowedHosts": ["hcpf.colorado.gov"],
                "expectedReleaseWindow": {"start": "2026-09-01", "end": "2026-09-15"},
            },
        }
        return resolve_pending.execution_plan_refusal({"contract": contract}) or ""

    assert "names a page, not an executor" in refusal("generic-url")
    assert "no registration-time admission predicate" in refusal(adapter)


# --- HCPF: the official files ------------------------------------------------


def test_main_resolves_the_august_2026_caseload_from_the_official_files(
    monkeypatch, capsys
) -> None:
    served = _install(monkeypatch, [HCPF])
    rows, envelopes = _capture(monkeypatch)
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  resolve {HCPF} -> 1247.588 thousands" in out
    assert "dry-run: would append 1 row(s)" in out
    # One landing read, the three anchor reports, the target, its workbook.
    files = "https://hcpf.colorado.gov/sites/hcpf/files/2026%20"
    tail = "%2C%20Joint%20Budget%20Committee%20Monthly%20Premiums%20Report"
    assert served == [
        co_hcpf.LANDING_URL,
        f"{files}June{tail}.pdf",
        f"{files}July{tail}.pdf",
        f"{files}August{tail}.pdf",
        f"{files}September{tail}.pdf",
        f"{files}September{tail}.xlsx",
    ]
    (row,) = rows
    assert row["value"] == 1247.588
    assert row["period"] == {"type": "month", "value": "2026-08"}
    # The publisher's date is the day the PDF was posted, not the fetch day
    # and not the forecast's by-date.
    assert row["observed_at"] == "2026-09-14"
    assert row["geography"] == {
        "level": "state",
        "id": "0400000US08",
        "vintage": "current",
        "name": "Colorado",
    }
    assert row["entity"] == {"name": "person", "role": "medicaid_beneficiary"}
    assert row["measure"]["concept"] == "co.hcpf.medicaid.total_caseload"
    assert row["measure"]["unit"] == "thousands"
    assert row["source"]["url"] == f"{files}September{tail}.pdf"
    assert row["source"]["source_file"] == (
        "2026 September, Joint Budget Committee Monthly Premiums Report.pdf"
    )
    notes = row["measure"]["concept_evidence_notes"]
    assert "Report dated September 2026" in notes
    assert "Last-Modified header (Mon, 14 Sep 2026 17:35:17 GMT)" in notes
    assert "prints the same TOTAL" in notes
    assert "{" not in notes
    (envelope,) = envelopes
    assert envelope["schemaVersion"] == "co_hcpf_premiums_report_capture_v1"
    assert envelope["derived"] == {
        "period": "2026-08",
        "sourceSeriesId": "co-hcpf-premiums-report-medicaid-caseload-total",
        "unit": "thousands",
        "value": 1247.588,
    }
    assert envelope["landingPage"]["reportsListed"] == [
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
    ]
    report = envelope["report"]
    assert report["reading"] == {
        "table": "MEDICAID CASELOAD WITHOUT RETROACTIVITY",
        "newestMonth": "2026-08",
        "populatedMonths": 50,
        "total": 1247588,
    }
    # The archived bytes are the bytes that were read.
    body = base64.b64decode(report["bodyBase64"])
    assert hashlib.sha256(body).hexdigest() == report["sha256"]
    assert body == _official_page("2026-09")
    assert (envelope["workbook"]["status"], envelope["workbook"]["total"]) == (
        "agrees",
        1247588,
    )
    assert [(a["period"], a["reading"]["total"]) for a in envelope["anchors"]] == [
        ("2026-05", 1238720),
        ("2026-06", 1237772),
        ("2026-07", 1242335),
    ]
    assert all("bodyBase64" not in anchor for anchor in envelope["anchors"])


def test_main_defers_a_month_whose_report_the_page_does_not_list_yet(
    monkeypatch, capsys
) -> None:
    _install(monkeypatch, [HCPF_NEXT])
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  not yet published (deferring): {HCPF_NEXT} — " in out
    assert "October 2026 report, found 0" in out
    assert "nothing new to record" in out


# --- HCPF: what it refuses -----------------------------------------------------


def test_main_refuses_a_reposted_report_as_a_missed_first_print(
    monkeypatch, capsys
) -> None:
    _install(monkeypatch, [HCPF], modified={"2026-09": "Thu, 15 Oct 2026 16:00:00 GMT"})
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  FIRST-PRINT WINDOW MISSED (refusing): {HCPF} — " in out
    assert "modified 2026-10-15" in out and "re-post" in out
    assert "resolve " not in out


@pytest.mark.parametrize(
    ("modified", "says"),
    [
        (None, "no Last-Modified header"),
        ("Mon, 31 Aug 2026 23:00:00 GMT", "before September 2026"),
    ],
)
def test_main_refuses_a_report_whose_posting_cannot_be_placed(
    monkeypatch, capsys, modified, says
) -> None:
    _install(monkeypatch, [HCPF], modified={"2026-09": modified})
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  CO HCPF PARSE REFUSAL (refusing): {HCPF} — " in out and says in out
    assert "resolve " not in out


def test_main_refuses_a_report_that_first_prints_another_month(
    monkeypatch, capsys
) -> None:
    """The file the page links for September must itself lead with August:
    here it is the August report (newest month July) under September's name."""
    _install(monkeypatch, [HCPF], pdfs={"2026-09": _official_page("2026-08")})
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  CO HCPF PARSE REFUSAL (refusing): {HCPF} — " in out
    assert "newest caseload month is 2026-07, not 2026-08" in out
    # And a report that already carries the following month is a restatement
    # of the one asked for.
    later = hcpf_pdf_text(hcpf_rows("2026-09", [1_242_335, 1_247_000, 1_250_000]))
    _install(monkeypatch, [HCPF], pdfs={"2026-09": _synthetic_pdf(later)})
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert "newest caseload month is 2026-09, not 2026-08" in out
    assert "resolve " not in out


def test_main_refuses_when_an_anchor_report_no_longer_reads_as_recorded(
    monkeypatch, capsys
) -> None:
    served = _install(monkeypatch, [HCPF])
    monkeypatch.setitem(
        resolve_pending.CO_HCPF_ADAPTERS["co.hcpf.medicaid.total_caseload"],
        "anchors",
        {"2026-05": 1238721},
    )
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert "ANCHOR MISMATCH (refusing, wrong HCPF report table?)" in out
    assert "anchor 2026-05=1238720 (recorded 1238721)" in out
    # The target report is not even fetched.
    assert not [url for url in served if "September" in url]
    # An anchor report that fails its own gate is the same refusal.
    monkeypatch.undo()
    _install(monkeypatch, [HCPF], modified={"2026-07": "Thu, 15 Oct 2026 16:00:00 GMT"})
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert "ANCHOR MISMATCH (refusing, wrong HCPF report table?)" in out
    assert "anchor 2026-06: report file was modified 2026-10-15" in out


def test_main_refuses_a_total_outside_the_sanity_range(monkeypatch, capsys) -> None:
    tiny = hcpf_pdf_text(hcpf_rows("2026-08", [1_240_000, 1_242_335, 1_247]))
    _install(monkeypatch, [HCPF], pdfs={"2026-09": _synthetic_pdf(tiny)})
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  CO HCPF PARSE REFUSAL (refusing): {HCPF} — TOTAL 1247 outside" in out


@pytest.mark.parametrize(
    "install",
    [{"pdftotext": False}, {"no_pdftotext_for": frozenset({"2026-09"})}],
    ids=["at-the-first-anchor", "at-the-target"],
)
def test_main_treats_a_missing_pdftotext_as_fatal(monkeypatch, capsys, install) -> None:
    """A missing parser is the runner's fault, not a state of the source: the
    run must go red, wherever in the leg the parser is first needed."""
    _install(monkeypatch, [HCPF], **install)
    assert resolve_pending.main() == 1
    out = capsys.readouterr().out
    assert f"  CO HCPF ENVIRONMENT FAILURE (fatal): {HCPF} — pdftotext" in out
    assert "environment failures left admitted references unresolvable" in out
    assert f"  fatal: {HCPF}: pdftotext is unavailable" in out


@pytest.mark.parametrize(
    ("install", "says"),
    [
        (
            {"content_types": {"2026-09": "text/html; charset=UTF-8"}},
            "report response is 'text/html; charset=UTF-8', not a PDF",
        ),
        (
            {"landed": {"2026-09": "https://hcpf.colorado.gov/page-not-found"}},
            "landed on https://hcpf.colorado.gov/page-not-found",
        ),
    ],
    ids=["html-answer", "redirected"],
)
def test_main_refuses_an_answer_that_is_not_the_report_the_page_links(
    monkeypatch, capsys, install, says
) -> None:
    _install(monkeypatch, [HCPF], **install)
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  CO HCPF PARSE REFUSAL (refusing): {HCPF} — " in out and says in out
    assert "resolve " not in out


def test_main_defers_when_the_site_cannot_be_reached(monkeypatch, capsys) -> None:
    _install(monkeypatch, [HCPF])

    def down(url: str):
        raise OSError("connection reset")

    monkeypatch.setattr(resolve_pending, "co_hcpf_http_get", down)
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  CO HCPF landing page fetch failed (deferring): {HCPF} — " in out
    assert "nothing new to record" in out


# --- HCPF: the workbook never decides ------------------------------------------


@pytest.mark.parametrize(
    ("workbook", "status", "note"),
    [
        (
            hcpf_workbook(hcpf_rows("2026-08", [1_242_335, 1_247_600])),
            "disagrees",
            "prints 1247600; the PDF controls",
        ),
        (
            hcpf_workbook(hcpf_rows("2026-09", [1_247_588, 1_250_000])),
            "unreadable",
            "could not be read; the PDF controls",
        ),
        (b"<html>not found</html>", "unreadable", "could not be read"),
        (OSError("timed out"), "unreadable", "could not be read"),
    ],
    ids=["another-total", "another-newest-month", "not-a-workbook", "unreachable"],
)
def test_main_records_the_pdf_whatever_the_workbook_says(
    monkeypatch, capsys, workbook, status, note
) -> None:
    """The forecast's rule: the PDF is the citable print when they differ."""
    _install(monkeypatch, [HCPF], workbook=workbook)
    rows, envelopes = _capture(monkeypatch)
    assert resolve_pending.main() == 0
    assert f"  resolve {HCPF} -> 1247.588 thousands" in capsys.readouterr().out
    assert rows[0]["value"] == 1247.588
    assert note in rows[0]["measure"]["concept_evidence_notes"]
    assert envelopes[0]["workbook"]["status"] == status


def test_main_resolves_from_a_page_that_links_no_workbook(monkeypatch, capsys) -> None:
    landing = hcpf_landing(
        ["2026-06", "2026-07", "2026-08", "2026-09"], workbooks=False
    )
    served = _install(monkeypatch, [HCPF], landing=landing)
    rows, envelopes = _capture(monkeypatch)
    assert resolve_pending.main() == 0
    assert f"  resolve {HCPF} -> 1247.588 thousands" in capsys.readouterr().out
    assert not [url for url in served if url.endswith(".xlsx")]
    assert envelopes[0]["workbook"] == {"status": "absent"}
    assert "links no workbook" in rows[0]["measure"]["concept_evidence_notes"]


# --- DOR: a leg that only reports ----------------------------------------------


def test_main_refuses_the_july_2026_collections_as_a_missed_first_print(
    monkeypatch, capsys
) -> None:
    served = _install(monkeypatch, [DOR, DOR_NEWEST, DOR_NEXT])
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert (
        f"  FIRST-PRINT WINDOW MISSED (refusing): {DOR} — the workbook's newest "
        "month is August 2026 (publish date September 2026)"
    ) in out
    # August is the newest month, and the leg still records nothing.
    assert f"  CO DOR ADAPTER UNVERIFIED (refusing): {DOR_NEWEST} — " in out
    assert f"  not yet published (deferring): {DOR_NEXT} — " in out
    assert "resolve " not in out and "nothing new to record" in out
    # One read of the one workbook serves every DOR cell.
    assert served == [co_dor.WORKBOOK_URL]


def test_main_defers_or_refuses_when_the_dor_workbook_cannot_be_read(
    monkeypatch, capsys
) -> None:
    _install(monkeypatch, [DOR], dor=OSError("HTTP Error 403: Forbidden"))
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  CO DOR workbook fetch failed (deferring): {DOR} — " in out
    # Drive can answer HTTP 200 with a sign-in or interstitial page: the
    # source is not being served, which is a deferral, not a verdict on it.
    _install(monkeypatch, [DOR], dor=b"<html>Sign in</html>")
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  CO DOR workbook fetch failed (deferring): {DOR} — Drive answered" in out
    assert "FIRST-PRINT WINDOW MISSED" not in out
    # A workbook that is served but restructured is refused.
    _install(monkeypatch, [DOR], dor=dor_workbook("2026-08", sheet_name="Sheet1"))
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  CO DOR PARSE REFUSAL (refusing): {DOR} — " in out
    # Even a workbook in which July is the newest month records nothing.
    _install(monkeypatch, [DOR], dor=dor_workbook("2026-07"))
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  CO DOR ADAPTER UNVERIFIED (refusing): {DOR} — July 2026 is" in out
    assert "resolve " not in out


# --- what the status page will say ---------------------------------------------


def test_the_status_page_reads_both_cells_verdicts(monkeypatch, capsys) -> None:
    _install(monkeypatch, [HCPF, DOR])
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    targets, _run = resolution_status.parse_resolver_log(out, {HCPF, DOR})
    assert targets[HCPF]["state"] == "resolved_this_run"
    assert (targets[DOR]["state"], targets[DOR]["code"]) == (
        "refused",
        "FIRST_PRINT_WINDOW_MISSED",
    )
    # The page reprints the whole reason, not a cut-off one.
    assert targets[DOR]["detail"].endswith("cannot be shown to be the first print")


@pytest.mark.parametrize(
    ("install", "ref", "state", "code"),
    [
        (
            {"modified": {"2026-09": "Thu, 15 Oct 2026 16:00:00 GMT"}},
            HCPF,
            "refused",
            "FIRST_PRINT_WINDOW_MISSED",
        ),
        (
            {"pdfs": {"2026-09": _official_page("2026-08")}},
            HCPF,
            "refused",
            "UNCLASSIFIED",
        ),
        ({"pdftotext": False}, HCPF, "fetch_failed", "ENVIRONMENT_FAILURE"),
        ({}, HCPF_NEXT, "deferred", "NOT_YET_PUBLISHED"),
        ({}, DOR_NEWEST, "refused", "UNCLASSIFIED"),
        ({}, DOR_NEXT, "deferred", "NOT_YET_PUBLISHED"),
        ({"dor": OSError("reset")}, DOR, "fetch_failed", "SOURCE_UNREACHABLE"),
    ],
    ids=[
        "hcpf-repost",
        "hcpf-other-month",
        "hcpf-no-pdftotext",
        "hcpf-not-listed",
        "dor-newest-month",
        "dor-not-published",
        "dor-unreachable",
    ],
)
def test_every_other_verdict_is_read_in_the_state_it_was_printed_in(
    monkeypatch, capsys, install, ref, state, code
) -> None:
    _install(monkeypatch, [ref], **install)
    resolve_pending.main()
    targets, _run = resolution_status.parse_resolver_log(capsys.readouterr().out, {ref})
    assert (targets[ref]["state"], targets[ref]["code"]) == (state, code)


# --- properties --------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(total=st.integers(500_000, 3_000_000))
def test_members_to_thousands_is_exact_at_three_decimals(total: int) -> None:
    """Whole members divided by 1,000 need exactly three decimals; the
    recorded float is that decimal, with nothing rounded away."""
    spec = resolve_pending.CO_HCPF_ADAPTERS["co.hcpf.medicaid.total_caseload"]
    value = round(total * spec["scale"], spec["round"]) + 0.0
    assert Decimal(repr(value)) == Decimal(total) / 1000


@settings(max_examples=60, deadline=None)
@given(
    newest=st.integers(2024 * 12, 2030 * 12),
    asked=st.integers(2024 * 12, 2030 * 12),
    posted_day=st.integers(1, 28),
    posted_month_offset=st.integers(-2, 2),
    total=st.integers(600_000, 2_900_000),
)
def test_a_value_is_recorded_only_for_the_newest_month_of_a_report_posted_in_its_month(
    newest, asked, posted_day, posted_month_offset, total
) -> None:
    """The first-print discipline as one statement: ``co_hcpf_capture_report``
    returns a figure exactly when the report dated the month after ``asked``
    is listed, leads with ``asked``, and was last modified in that month."""

    def period(index: int) -> str:
        return f"{index // 12:04d}-{index % 12 + 1:02d}"

    newest_period, asked_period = period(newest), period(asked)
    listed_report = period(newest + 1)
    posted = newest + 1 + posted_month_offset
    stamp = dt.datetime(
        posted // 12, posted % 12 + 1, posted_day, 18, tzinfo=dt.timezone.utc
    ).strftime("%a, %d %b %Y %H:%M:%S GMT")
    text = hcpf_pdf_text(hcpf_rows(newest_period, [total - 5, total]))
    files = {
        co_hcpf.landing_report_links(
            hcpf_landing([listed_report]), listed_report
        ).pdf_url: (
            _synthetic_pdf(text),
            {"content-type": "application/pdf", "last-modified": stamp},
            "2026-10-09T23:57:46Z",
        )
    }
    cache = {url: (*parts, url) for url, parts in files.items()}
    original = resolve_pending.co_hcpf_pdf_text
    resolve_pending.co_hcpf_pdf_text = lambda raw: (
        raw[len(SYNTHETIC_PDF) :].decode(),
        None,
    )
    try:
        capture, refusal = resolve_pending.co_hcpf_capture_report(
            hcpf_landing([listed_report]), asked_period, cache, read_workbook=False
        )
    finally:
        resolve_pending.co_hcpf_pdf_text = original
    should_read = asked == newest and posted_month_offset == 0
    assert (capture is not None) == should_read, refusal
    assert (refusal is None) == should_read
    if capture is not None:
        assert (capture.total, capture.newest_month) == (total, asked_period)
