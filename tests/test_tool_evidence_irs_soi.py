"""Captured IRS workbook extraction must replay the registered total series.

The 2018/2019 files are newly fetched source fixtures, with provenance beside
them. They are not reconstructed evidence from any earlier forecast attempt.
No test makes a network request or invokes forecast generation.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolve_pending as resolver  # noqa: E402
import tool_evidence as evidence  # noqa: E402
import tool_evidence_mcp as mcp  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "irs_soi_pub1304"
SERIES = "irs.actc.total_claims"
SPEC = resolver.IRS_SOI_PUB1304_ADAPTERS[SERIES]
TOTAL_RETURNS = {
    "2018": (20450468, 20.450468),
    "2019": (19867646, 19.867646),
    "2020": (19119249, 19.119249),
    "2021": (37771612, 37.771612),
    "2022": (18076696, 18.076696),
    "2023": (17626084, 17.626084),
}


def workbook(year="2018"):
    return (FIXTURES / f"{year[-2:]}in33ar.xls").read_bytes()


def official_url(year="2018"):
    return f"https://www.irs.gov/pub/irs-soi/{year[-2:]}in33ar.xls"


def response(body, url, *, status=200):
    return {
        "url": url,
        "status": status,
        "headers": [["content-type", "application/vnd.ms-excel"]],
        "bodyBase64": base64.b64encode(body).decode("ascii"),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }


def recorder_with_source(tmp_path, *, year="2018", body=None, url=None, status=200):
    raw = workbook(year) if body is None else body
    url = official_url(year) if url is None else url
    recorder = evidence.EvidenceRecorder(
        tmp_path / "evidence.json",
        fetcher=lambda fetched: response(raw, fetched, status=status),
    )
    source = recorder.call("fetch_source", {"url": url})
    return recorder, source


def extract(recorder, source, *, year="2018", **overrides):
    arguments = {
        "sourceCallId": source["callId"],
        "seriesId": SERIES,
        "year": year,
        **overrides,
    }
    return recorder.call("extract_irs_soi", arguments)


def assert_retained_failure(recorder, call):
    assert call["status"] == "failed"
    assert call["result"] is None
    assert call["error"]
    assert evidence.load_evidence(recorder.output)["calls"][-1] == call
    report = evidence.verify_evidence(recorder.payload)
    assert report["valid"], report["errors"]
    assert report["failedCount"] >= 1


@pytest.mark.parametrize("year", ["2018", "2019"])
def test_new_workbook_fixtures_are_exact_official_bytes_with_provenance(year):
    provenance = json.loads((FIXTURES / "2018-2019-provenance.json").read_text())
    source = next(item for item in provenance["sources"] if item["taxYear"] == year)
    raw = workbook(year)
    assert len(raw) == source["bytes"]
    assert hashlib.sha256(raw).hexdigest() == source["sha256"]
    assert source["url"] == official_url(year)
    grid, refusal = resolver.irs_soi_pub1304_grid(raw, SPEC)
    assert refusal is None
    assert "tax year " + year in grid[0][0].lower()
    assert grid[9][0] == "All returns, total"
    assert grid[4][38] == "Additional child tax credit"
    assert " ".join(grid[6][38].split()) == "Number of returns"
    assert grid[8][38] == 38
    assert grid[9][38] == source["returns"]
    assert source["returns"] != source["excludedRefundablePortionReturns"]


@pytest.mark.parametrize("year", list(TOTAL_RETURNS))
def test_actual_workbook_capture_replays_total_claimants_and_units(tmp_path, year):
    recorder, source = recorder_with_source(tmp_path, year=year)
    call = extract(recorder, source, year=year)
    raw_count, millions = TOTAL_RETURNS[year]
    assert call["status"] == "succeeded", call
    assert call["result"] == {
        "value": millions,
        "sourceCallId": source["callId"],
        "sourceSha256": hashlib.sha256(workbook(year)).hexdigest(),
        "sourceUrl": official_url(year),
        "seriesId": SERIES,
        "year": year,
        "rawValue": raw_count,
        "unit": "millions",
        "transform": {"operation": "multiply", "factor": 1e-6},
    }
    report = evidence.verify_evidence(evidence.load_evidence(recorder.output))
    assert report["valid"], report["errors"]
    assert report["checks"][-1] == {
        "callId": call["callId"],
        "status": "replayed",
        "checks": ["irs_soi_workbook_replay"],
    }
    if year in SPEC["anchors"]:
        assert raw_count == SPEC["anchors"][year]


def test_calculation_uses_captured_extraction_value_not_literal_claim(tmp_path):
    recorder, source = recorder_with_source(tmp_path)
    call = extract(recorder, source)
    calculated = recorder.call(
        "calculate",
        {"expression": "x * 2", "inputs": {"x": {"callId": call["callId"]}}},
    )
    assert calculated["status"] == "succeeded", calculated
    assert calculated["result"] == {
        "value": 40.900936,
        "resolvedInputs": {"x": 20.450468},
    }
    assert evidence.verify_evidence(recorder.payload)["valid"]
    tampered = copy.deepcopy(recorder.payload)
    tampered["calls"][-1]["result"]["resolvedInputs"]["x"] = 19.528542
    assert not evidence.verify_evidence(tampered)["valid"]


@pytest.mark.parametrize(
    ("year", "wrong_raw", "wrong_value"),
    [("2018", 19528542, 19.528542), ("2019", 19011027, 19.011027)],
)
def test_refundable_portion_subset_cannot_masquerade_as_total(
    tmp_path, year, wrong_raw, wrong_value
):
    recorder, source = recorder_with_source(tmp_path, year=year)
    extract(recorder, source, year=year)
    tampered = copy.deepcopy(recorder.payload)
    tampered["calls"][-1]["result"].update(rawValue=wrong_raw, value=wrong_value)
    report = evidence.verify_evidence(tampered)
    assert not report["valid"]
    assert any("does not match replay" in error for error in report["errors"])


@pytest.mark.parametrize(
    "changes",
    [
        {"sourceCallId": "call-9999"},
        {"sourceCallId": "call-0002"},
        {"sourceCallId": 1},
        {"seriesId": "unknown.series"},
        {"seriesId": None},
        {"year": 2018},
        {"year": True},
        {"year": "18"},
        {"year": "2018 "},
        {"year": "../2018"},
        {"year": "2019"},
        {"value": 20.450468},
        {"column": "CW"},
    ],
)
def test_wrong_or_untrusted_extraction_arguments_are_recorded_failures(
    tmp_path, changes
):
    recorder, source = recorder_with_source(tmp_path)
    assert_retained_failure(recorder, extract(recorder, source, **changes))


@pytest.mark.parametrize("missing", ["sourceCallId", "seriesId", "year"])
def test_missing_argument_fails_without_inventing_defaults(tmp_path, missing):
    recorder, source = recorder_with_source(tmp_path)
    args = {"sourceCallId": source["callId"], "seriesId": SERIES, "year": "2018"}
    del args[missing]
    assert_retained_failure(recorder, recorder.call("extract_irs_soi", args))


@pytest.mark.parametrize(
    "url",
    [
        "https://example.gov/pub/irs-soi/18in33ar.xls",
        "https://irs.gov/pub/irs-soi/18in33ar.xls",
        "https://www.irs.gov/pub/irs-soi/18in33ar.xls?download=1",
        "https://www.irs.gov/pub/irs-soi/18in33ar.xls#table",
        "https://www.irs.gov/pub/irs-soi/19in33ar.xls",
        "https://www.irs.gov/pub/irs-soi/18in33ar.xlsx",
        "https://www.irs.gov/pub/irs-soi/%31%38in33ar.xls",
    ],
)
def test_valid_workbook_at_nonexact_url_cannot_supply_registered_source(tmp_path, url):
    recorder, source = recorder_with_source(tmp_path, url=url)
    assert_retained_failure(recorder, extract(recorder, source))


def test_correct_filename_with_wrong_workbook_tax_year_refuses(tmp_path):
    recorder, source = recorder_with_source(tmp_path, body=workbook("2019"))
    assert source["status"] == "succeeded"
    assert_retained_failure(recorder, extract(recorder, source))


@pytest.mark.parametrize("status", [301, 404, 500])
def test_failed_http_body_never_becomes_successful_extraction(tmp_path, status):
    recorder, source = recorder_with_source(tmp_path, status=status)
    assert source["status"] == "failed"
    assert base64.b64decode(source["response"]["bodyBase64"]) == workbook()
    assert_retained_failure(recorder, extract(recorder, source))


def test_nonfetch_source_call_cannot_supply_workbook_bytes(tmp_path):
    recorder = evidence.EvidenceRecorder(tmp_path / "evidence.json", allow_fetch=False)
    source = recorder.call("calculate", {"expression": "20450468", "inputs": {}})
    assert_retained_failure(recorder, extract(recorder, source))


@pytest.mark.parametrize(
    "body", [b"", b"not a workbook", b"<html>temporarily unavailable</html>"]
)
def test_malformed_workbook_is_a_preserved_failure(tmp_path, body):
    recorder, source = recorder_with_source(tmp_path, body=body)
    assert source["status"] == "succeeded"
    assert_retained_failure(recorder, extract(recorder, source))


def test_missing_xls_dependency_refuses_and_retains_fetch(tmp_path, monkeypatch):
    recorder, source = recorder_with_source(tmp_path)
    monkeypatch.setitem(sys.modules, "xlrd", None)
    call = extract(recorder, source)
    assert_retained_failure(recorder, call)
    assert "xlrd" in call["error"].lower()
    assert len(recorder.payload["calls"]) == 2


@pytest.mark.parametrize(
    "layout", ["subset_only", "ambiguous", "wrong_units", "wrong_title"]
)
def test_reviewed_adapter_layout_guards_remain_fail_closed(
    tmp_path, monkeypatch, layout
):
    grid, refusal = resolver.irs_soi_pub1304_grid(workbook(), SPEC)
    assert refusal is None
    if layout == "subset_only":
        grid[4][38] = "Additional child tax credit refundable portion"
    elif layout == "ambiguous":
        grid[4][40] = "Additional child tax credit"
    elif layout == "wrong_units":
        grid[6][38] = "Amount"
    else:
        grid[0][0] = "Table 3.3 Tax Year 2017"
    monkeypatch.setattr(
        resolver, "irs_soi_pub1304_grid", lambda raw, spec, **kwargs: (grid, None)
    )
    recorder, source = recorder_with_source(tmp_path)
    assert_retained_failure(recorder, extract(recorder, source))


def test_response_size_limit_precedes_any_workbook_parse(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "MAX_RESPONSE_BYTES", 64)
    recorder, source = recorder_with_source(tmp_path)
    assert source["status"] == "failed"
    assert "response" not in source
    assert_retained_failure(recorder, extract(recorder, source))


@pytest.mark.parametrize("limit", ["MAX_IRS_SOI_ROWS", "MAX_IRS_SOI_COLUMNS"])
def test_workbook_dimensions_are_bounded_before_grid_allocation(
    tmp_path, monkeypatch, limit
):
    monkeypatch.setattr(evidence, limit, 10)
    recorder, source = recorder_with_source(tmp_path)
    call = extract(recorder, source)
    assert_retained_failure(recorder, call)
    assert "dimension limit" in call["error"].lower()


@pytest.mark.parametrize("over_limit", ["rows", "columns", "sheets"])
def test_bounded_loader_refuses_before_materializing_cells(
    monkeypatch, capsys, over_limit
):
    import xlrd

    read_cells = []
    options_seen = {}

    class Sheet:
        nrows = 513 if over_limit == "rows" else 52
        ncols = 513 if over_limit == "columns" else 117

        def cell_value(self, row, column):
            read_cells.append((row, column))
            return ""

    class Book:
        nsheets = 17 if over_limit == "sheets" else 1
        released = False

        def sheet_names(self):
            return ["TBL33"]

        def sheet_by_name(self, name):
            assert name == "TBL33"
            return Sheet()

        def release_resources(self):
            self.released = True

    book = Book()

    def open_workbook(**options):
        options_seen.update(options)
        return book

    monkeypatch.setattr(xlrd, "open_workbook", open_workbook)
    grid, refusal = resolver.irs_soi_pub1304_grid(
        workbook(),
        SPEC,
        max_rows=512,
        max_columns=512,
        max_sheets=16,
        quiet=True,
    )
    assert grid is None
    assert "limit" in refusal
    assert read_cells == []
    assert book.released
    assert options_seen["on_demand"] is True
    assert options_seen["file_contents"] == workbook()
    assert "logfile" in options_seen
    assert options_seen["logfile"].write("workbook diagnostic") == 19
    options_seen["logfile"].flush()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize(
    "tamper",
    [
        "body_hash",
        "body_bytes",
        "result_hash",
        "result_value",
        "raw_value",
        "year",
        "url",
        "series",
        "unit",
        "transform",
        "source_ref",
        "forward_ref",
    ],
)
def test_offline_replay_rejects_tampered_successful_workbook_extraction(
    tmp_path, tamper
):
    recorder, source = recorder_with_source(tmp_path)
    extract(recorder, source)
    payload = copy.deepcopy(recorder.payload)
    fetch, call = payload["calls"]
    if tamper == "body_hash":
        fetch["response"]["sha256"] = "0" * 64
    elif tamper == "body_bytes":
        fetch["response"]["bytes"] += 1
    elif tamper == "result_hash":
        call["result"]["sourceSha256"] = "0" * 64
    elif tamper == "result_value":
        call["result"]["value"] = 18.528360
    elif tamper == "raw_value":
        call["result"]["rawValue"] = 18528360
    elif tamper == "year":
        call["result"]["year"] = "2019"
    elif tamper == "url":
        call["result"]["sourceUrl"] = official_url("2019")
    elif tamper == "series":
        call["result"]["seriesId"] = "irs.actc.total_credit_amount"
    elif tamper == "unit":
        call["result"]["unit"] = "thousands"
    elif tamper == "transform":
        call["result"]["transform"]["factor"] = 1e-3
    elif tamper == "source_ref":
        call["result"]["sourceCallId"] = "call-0002"
    else:
        call["arguments"]["sourceCallId"] = "call-0002"
    assert not evidence.verify_evidence(payload)["valid"]


def test_replay_reads_only_captured_bytes_without_network(tmp_path, monkeypatch):
    recorder, source = recorder_with_source(tmp_path)
    extract(recorder, source)

    def network_refused(*_args, **_kwargs):
        pytest.fail("offline workbook replay attempted network access")

    monkeypatch.setattr(evidence, "fetch_public_https", network_refused)
    monkeypatch.setattr(resolver, "http_get", network_refused)
    report = evidence.verify_evidence(evidence.load_evidence(recorder.output))
    assert report["valid"], report["errors"]
    assert report["succeededCount"] == 2


def test_mcp_reply_binds_actual_extraction_and_excludes_source_bytes(tmp_path):
    recorder, source = recorder_with_source(tmp_path)
    arguments = {
        "sourceCallId": source["callId"],
        "seriesId": SERIES,
        "year": "2018",
    }
    reply = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "extract_irs_soi", "arguments": arguments},
        },
        recorder,
    )
    call = recorder.payload["calls"][-1]
    assert call["status"] == "succeeded", call
    terminal = evidence.terminal_call(call)
    assert reply["result"]["structuredContent"] == terminal
    assert json.loads(reply["result"]["content"][0]["text"]) == terminal
    assert reply["result"]["isError"] is False
    assert terminal["arguments"] == arguments
    assert terminal["result"]["value"] == 20.450468
    assert "response" not in terminal
    assert "bodyBase64" not in json.dumps(terminal)
    assert "extract_irs_soi" in {
        tool["name"] for tool in mcp.tool_definitions(allow_fetch=False)
    }
