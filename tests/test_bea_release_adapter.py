from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import pathlib
import sys
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import prospect_targets  # noqa: E402
import register_targets  # noqa: E402
import resolve_pending  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "ingestion_wave1" / "bea"
RELEASE_DAY = dt.date(2026, 7, 30)
ITA_RELEASE_DAY = dt.date(2026, 6, 24)
ITA_SERIES = "bea.ita.personal_transfer_payments"
ITA_CATALOG_REQUEST_BYTES = (
    b'{"appid":62,"data":[["Product","1"],["TableList","62"]],"stepnum":2}'
)
ITA_SELECTED_REQUEST_BYTES = (
    b'{"appid":62,"data":[["Product","1"],["TableList","62"],'
    b'["Filter_#1","1"],["Filter_#2","1"],["Filter_#3","18"]],"stepnum":2}'
)


def _decoded_fixture(name: str) -> bytes:
    encoded = b"".join((FIXTURES / name).read_bytes().splitlines())
    return base64.b64decode(encoded, validate=True)


def _docket_entry(series: str) -> dict[str, Any]:
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    return next(row for row in docket["series"] if row["series"] == series)


def _registration(
    series: str,
    *,
    period: str = "2026-Q2",
    release_day: dt.date = RELEASE_DAY,
    registration_day: dt.date = dt.date(2026, 7, 1),
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    entry = _docket_entry(series)
    target = {
        **entry["extras"],
        "series": series,
        "period": period,
        "catalogSlug": f"unit4-{series.replace('.', '-')}",
        "releaseCalendarUrl": entry["releaseCalendarUrl"],
        "expectedReleaseDate": release_day.isoformat(),
    }
    contract = register_targets.build_contract(target, registration_day)
    ref = contract["dataPointId"]
    envelope = {
        "targetContentHash": "a" * 64,
        "contract": contract,
        "ledgerPin": None,
    }
    spec = resolve_pending.BEA_RELEASE_ADAPTERS[series]
    forecast = {
        "resolutionDate": release_day.isoformat(),
        "unit": spec["unit"],
    }
    return ref, envelope, spec, forecast


def test_real_bea_current_release_fixtures_are_hash_pinned_and_parse() -> None:
    release_raw = (FIXTURES / "gdp-advance-2026-q2.html").read_bytes()
    table_raw = (FIXTURES / "nipa-table-5-3-5-2026-q2.json").read_bytes()

    assert len(release_raw) == 52_640
    assert hashlib.sha256(release_raw).hexdigest() == (
        "4636dc341d7cd1a53196fdf0ad529143b0e8b2d0db874f6086ca9b8ebf23cf5d"
    )
    assert len(table_raw) == 46_905
    assert hashlib.sha256(table_raw).hexdigest() == (
        "59e5f1ab0eeaa76cdca566383c66eab7787214216ffcbe35aa4c1793a894750d"
    )
    assert (
        resolve_pending.bea_release_page_refusal(release_raw, "2026-04", RELEASE_DAY)
        is None
    )

    pnfi = resolve_pending.BEA_RELEASE_ADAPTERS[
        "bea.private_nonresidential_fixed_investment"
    ]
    research = resolve_pending.BEA_RELEASE_ADAPTERS[
        "bea.research_and_development_fixed_investment"
    ]
    assert resolve_pending.bea_itable_value(
        table_raw, pnfi, "2026-04", RELEASE_DAY
    ) == (4623.657, None)
    assert resolve_pending.bea_itable_value(
        table_raw, research, "2026-04", RELEASE_DAY
    ) == (937.772, None)


def test_bea_itable_posts_to_the_core_getstep_path() -> None:
    # The old /iTablecore/ path answered HTTP 200 with an HTML page on
    # 2026-11-05, so a fetch there succeeds and every parse refuses.
    url = resolve_pending.BEA_ITABLE_DATA_URL

    assert url == "https://apps.bea.gov/iTable/core/data/app/GetStep"
    assert resolve_pending.urlparse(url).hostname in (
        resolve_pending.BEA_RELEASE_REQUIRED_HOSTS
    )


def test_real_core_endpoint_response_parses_with_the_release_parser() -> None:
    # A live 2026-11-05 response from the /iTable/core/ endpoint to a
    # 2024-only request; see the fixture README. It carries the 2026-10-29
    # revision stamp, so it also proves the stamp check reads this endpoint's
    # body the way it read the old one.
    raw = (FIXTURES / "nipa-table-5-3-5-2024-core-endpoint.json").read_bytes()
    stamped_day = dt.date(2026, 10, 29)
    pnfi = resolve_pending.BEA_RELEASE_ADAPTERS[
        "bea.private_nonresidential_fixed_investment"
    ]
    research = resolve_pending.BEA_RELEASE_ADAPTERS[
        "bea.research_and_development_fixed_investment"
    ]

    assert len(raw) == 62_019
    assert hashlib.sha256(raw).hexdigest() == (
        "c9ea303119e3fc39ec412159f92494d9d32c9b4457f98ec48e0c6b944657daef"
    )
    assert resolve_pending.bea_itable_value(raw, pnfi, "2024-07", stamped_day) == (
        4143.523,
        None,
    )
    assert resolve_pending.bea_itable_value(raw, research, "2024-07", stamped_day) == (
        819.357,
        None,
    )
    value, refusal = resolve_pending.bea_itable_value(
        raw, pnfi, "2024-07", dt.date(2026, 10, 28)
    )
    assert value is None
    assert refusal is not None
    assert refusal.startswith("iTable revision stamp ")


HTML_ANSWER = (
    b'\n<!DOCTYPE html>\n<html lang="en"><head><title>BEA: Data Tools'
    b"</title></head><body></body></html>"
)


def test_bea_release_parser_names_an_html_answer() -> None:
    value, refusal = resolve_pending.bea_itable_value(
        HTML_ANSWER,
        resolve_pending.BEA_RELEASE_ADAPTERS[
            "bea.private_nonresidential_fixed_investment"
        ],
        "2026-04",
        RELEASE_DAY,
    )

    assert value is None
    assert refusal == (
        "iTable answered with an HTML page, not JSON; check that BEA still "
        "serves GetStep at https://apps.bea.gov/iTable/core/data/app/GetStep"
    )


@settings(max_examples=200, deadline=None)
@given(
    lead=st.sampled_from([b"", b"\n", b"  \r\n\t"]),
    tag=st.sampled_from([b"<!DOCTYPE html", b"<!doctype HTML", b"<html", b"<HTML"]),
    rest=st.binary(max_size=256),
)
def test_no_html_answer_yields_a_bea_value(
    lead: bytes, tag: bytes, rest: bytes
) -> None:
    # Invariant: an answer that opens as an HTML page never parses to a value,
    # in either parser, whatever follows the opening tag.
    raw = lead + tag + rest
    nipa = resolve_pending.bea_itable_value(
        raw,
        resolve_pending.BEA_RELEASE_ADAPTERS[
            "bea.private_nonresidential_fixed_investment"
        ],
        "2026-04",
        RELEASE_DAY,
    )
    ita = resolve_pending.bea_ita_itable_value(
        raw,
        resolve_pending.BEA_RELEASE_ADAPTERS[ITA_SERIES],
        "2026-01",
        ITA_RELEASE_DAY,
    )

    assert nipa[0] is None and nipa[1] is not None
    assert ita[0] is None and ita[1] is not None
    assert "answered with an HTML page" in nipa[1]
    assert "answered with an HTML page" in ita[1]


def test_bea_ita_parsers_name_an_html_answer() -> None:
    spec = resolve_pending.BEA_RELEASE_ADAPTERS[ITA_SERIES]
    expected = (
        "ITA iTable answered with an HTML page, not JSON; check that BEA still "
        "serves GetStep at https://apps.bea.gov/iTable/core/data/app/GetStep"
    )

    value, refusal = resolve_pending.bea_ita_itable_value(
        HTML_ANSWER, spec, "2026-01", ITA_RELEASE_DAY
    )
    assert value is None
    assert refusal == expected
    year_key, refusal = resolve_pending.bea_ita_prompt_catalog_selection(
        HTML_ANSWER, spec, "2026-01"
    )
    assert year_key is None
    assert refusal == expected


def _mutate_ita_table(raw: bytes, mutation: Any) -> bytes:
    outer = json.loads(raw)
    response = json.loads(outer) if isinstance(outer, str) else outer
    table_prompt = next(
        prompt
        for prompt in response["Prompts"]
        if prompt["Name"] == "TheTableFlexibleIipIta"
    )
    prompt_data = json.loads(table_prompt["PromtData"])
    table = json.loads(prompt_data["Table"])
    mutation(table)
    prompt_data["Table"] = json.dumps(table, separators=(",", ":"))
    table_prompt["PromtData"] = json.dumps(prompt_data, separators=(",", ":"))
    inner = json.dumps(response, separators=(",", ":"))
    return json.dumps(inner, separators=(",", ":")).encode()


def _mutate_ita_prompt_rows(raw: bytes, name: str, mutation: Any) -> bytes:
    outer = json.loads(raw)
    response = json.loads(outer) if isinstance(outer, str) else outer
    prompt = next(item for item in response["Prompts"] if item["Name"] == name)
    prompt_data = json.loads(prompt["PromtData"])
    mutation(prompt_data["Table"])
    prompt["PromtData"] = json.dumps(prompt_data, separators=(",", ":"))
    inner = json.dumps(response, separators=(",", ":"))
    return json.dumps(inner, separators=(",", ":")).encode()


def _ita_table_shape(raw: bytes) -> tuple[int, int, int]:
    outer = json.loads(raw)
    response = json.loads(outer) if isinstance(outer, str) else outer
    table_prompt = next(
        prompt
        for prompt in response["Prompts"]
        if prompt["Name"] == "TheTableFlexibleIipIta"
    )
    prompt_data = json.loads(table_prompt["PromtData"])
    table = json.loads(prompt_data["Table"])
    return (
        int(table["Number_Of_Rows"]),
        int(table["Number_Of_Columns"]),
        len(table["TD"]),
    )


def test_real_bea_ita_fixtures_are_hash_pinned_and_parse() -> None:
    # Live official replay on 2026-08-12 of the request documented at
    # https://apps.bea.gov/iTable/?ReqID=62&step=6&isuri=1&tablelist=62&product=1
    catalog_raw = _decoded_fixture("ita-prompt-catalog-2026-q1.json.base64")
    table_raw = _decoded_fixture("ita-table-5-1-2026-q1-qsa.json.base64")
    release_raw = _decoded_fixture("ita-iip-release-2026-q1.html.base64")
    spec = resolve_pending.BEA_RELEASE_ADAPTERS[ITA_SERIES]

    assert len(catalog_raw) == 84_950
    assert hashlib.sha256(catalog_raw).hexdigest() == (
        "9da6f369b0182f85102a9f5b83518ba0e0afaf6065f698f9cb69a5e319156b36"
    )
    assert _ita_table_shape(catalog_raw) == (28, 7, 196)
    assert len(table_raw) == 16_089
    assert hashlib.sha256(table_raw).hexdigest() == (
        "d482e10713b19c01824882b6e6f7ee01d06619222d35b27cb6f97fa95fdf0f35"
    )
    assert _ita_table_shape(table_raw) == (6, 3, 18)
    assert len(release_raw) == 58_604
    assert hashlib.sha256(release_raw).hexdigest() == (
        "617c9229ac39ded608b64a71bc30c3c10d713cb1885ee53344d6fb3bc4dd227d"
    )
    assert (
        resolve_pending.bea_ita_release_page_refusal(
            release_raw, "2026-01", ITA_RELEASE_DAY
        )
        is None
    )
    assert resolve_pending.bea_ita_prompt_catalog_selection(
        catalog_raw, spec, "2026-01"
    ) == ("1", None)
    assert resolve_pending.bea_ita_itable_value(
        table_raw, spec, "2026-01", ITA_RELEASE_DAY
    ) == (18_511.0, None)
    catalog_body = resolve_pending.bea_ita_prompt_catalog_request_body(spec)
    selected_body = resolve_pending.bea_ita_itable_request_body(
        spec, "2026-01", "1"
    )
    assert catalog_body == {
        "appid": 62,
        "stepnum": 2,
        "data": [["Product", "1"], ["TableList", "62"]],
    }
    assert selected_body == {
        "appid": 62,
        "stepnum": 2,
        "data": [
            ["Product", "1"],
            ["TableList", "62"],
            ["Filter_#1", "1"],
            ["Filter_#2", "1"],
            ["Filter_#3", "18"],
        ],
    }
    assert resolve_pending.canonical_bytes(catalog_body) == ITA_CATALOG_REQUEST_BYTES
    assert len(ITA_CATALOG_REQUEST_BYTES) == 68
    assert hashlib.sha256(ITA_CATALOG_REQUEST_BYTES).hexdigest() == (
        "18ea74bc5703892851fa9a21f85b34d616d1c9b19cee06a31da47d8775bd15ca"
    )
    assert resolve_pending.canonical_bytes(selected_body) == ITA_SELECTED_REQUEST_BYTES
    assert len(ITA_SELECTED_REQUEST_BYTES) == 123
    assert hashlib.sha256(ITA_SELECTED_REQUEST_BYTES).hexdigest() == (
        "752aff73c31aec17c829529964998148d805d2b060f48513ea9afbf7c290f3d9"
    )


def test_bea_ita_archive_roles_refuse_substituted_response_shape() -> None:
    catalog_raw = _decoded_fixture("ita-prompt-catalog-2026-q1.json.base64")
    table_raw = _decoded_fixture("ita-table-5-1-2026-q1-qsa.json.base64")
    spec = resolve_pending.BEA_RELEASE_ADAPTERS[ITA_SERIES]

    assert resolve_pending.bea_ita_prompt_catalog_selection(
        table_raw, spec, "2026-01"
    ) == (
        None,
        "ITA prompt catalog does not have the unfiltered Table 5.1 shape",
    )
    assert resolve_pending.bea_ita_itable_value(
        catalog_raw, spec, "2026-01", ITA_RELEASE_DAY
    ) == (
        None,
        "ITA selected iTable does not have the requested Table 5.1 shape",
    )


def test_bea_ita_snapshot_archives_all_authenticated_bytes_and_requests() -> None:
    # These are the live official bytes fetched on 2026-08-12 from the BEA
    # Table 5.1 and Q1 release URLs documented in the fixture README.
    catalog_raw = _decoded_fixture("ita-prompt-catalog-2026-q1.json.base64")
    table_raw = _decoded_fixture("ita-table-5-1-2026-q1-qsa.json.base64")
    release_raw = _decoded_fixture("ita-iip-release-2026-q1.html.base64")
    spec = resolve_pending.BEA_RELEASE_ADAPTERS[ITA_SERIES]
    value, refusal = resolve_pending.bea_ita_itable_value(
        table_raw, spec, "2026-01", ITA_RELEASE_DAY
    )
    assert refusal is None
    assert value is not None
    catalog_body = resolve_pending.bea_ita_prompt_catalog_request_body(spec)
    table_body = resolve_pending.bea_ita_itable_request_body(spec, "2026-01", "1")

    envelope = json.loads(
        resolve_pending.bea_ita_release_snapshot_envelope(
            spec=spec,
            period="2026-01",
            value=value,
            release_url=resolve_pending.bea_ita_release_url("2026-01", ITA_RELEASE_DAY),
            release_raw=release_raw,
            release_retrieved_at="2026-06-24T12:30:01Z",
            catalog_url=resolve_pending.BEA_ITABLE_DATA_URL,
            catalog_body=catalog_body,
            catalog_raw=catalog_raw,
            catalog_retrieved_at="2026-06-24T12:30:02Z",
            table_url=resolve_pending.BEA_ITABLE_DATA_URL,
            table_body=table_body,
            table_raw=table_raw,
            table_retrieved_at="2026-06-24T12:30:03Z",
        )
    )

    assert envelope["schemaVersion"] == "bea_ita_release_snapshot_v1"
    for key, expected_raw in (
        ("release", release_raw),
        ("promptCatalog", catalog_raw),
        ("table", table_raw),
    ):
        archived = envelope[key]
        assert base64.b64decode(archived["bodyBase64"], validate=True) == expected_raw
        assert archived["sha256"] == hashlib.sha256(expected_raw).hexdigest()
    assert envelope["promptCatalog"]["request"] == catalog_body
    assert envelope["table"]["request"] == table_body
    assert envelope["promptCatalog"]["sha256"] == (
        "9da6f369b0182f85102a9f5b83518ba0e0afaf6065f698f9cb69a5e319156b36"
    )
    assert envelope["table"]["sha256"] == (
        "d482e10713b19c01824882b6e6f7ee01d06619222d35b27cb6f97fa95fdf0f35"
    )
    assert envelope["derived"] == {
        "period": "2026-01",
        "sourceSeriesId": "ITA:T5.1:L18:QSA",
        "value": value,
    }


def test_bea_ita_release_urls_match_verified_quarter_specific_forms() -> None:
    assert resolve_pending.bea_ita_release_url("2026-01", ITA_RELEASE_DAY) == (
        "https://www.bea.gov/news/2026/us-international-transactions-and-"
        "investment-position-1st-quarter-2026-and-annual-update"
    )
    assert resolve_pending.bea_ita_release_url("2025-10", dt.date(2026, 3, 25)) == (
        "https://www.bea.gov/news/2026/us-international-transactions-and-"
        "investment-position-4th-quarter-and-year-2025"
    )
    assert resolve_pending.bea_ita_release_url("2026-04", dt.date(2026, 9, 24)) == (
        "https://www.bea.gov/news/2026/us-international-transactions-and-"
        "investment-position-2nd-quarter-2026"
    )


def test_bea_ita_release_page_refuses_wrong_title_date_and_embargo_time() -> None:
    raw = _decoded_fixture("ita-iip-release-2026-q1.html.base64")

    wrong_title = raw.replace(
        b"1st Quarter 2026 and Annual Update",
        b"2nd Quarter 2026 and Annual Update",
    )
    assert resolve_pending.bea_ita_release_page_refusal(
        wrong_title, "2026-01", ITA_RELEASE_DAY
    ) == (
        "ITA release page does not contain expected title 'U.S. International "
        "Transactions and Investment Position, 1st Quarter 2026 and Annual Update'"
    )
    wrong_date = raw.replace(b"June 24, 2026", b"June 25, 2026")
    assert resolve_pending.bea_ita_release_page_refusal(
        wrong_date, "2026-01", ITA_RELEASE_DAY
    ) == (
        "ITA release page does not contain exact registered embargo line "
        "'EMBARGOED UNTIL RELEASE AT 8:30 a.m. EDT, Wednesday, June 24, 2026'"
    )
    wrong_time = raw.replace(b"8:30 a.m. EDT", b"1:00 a.m. EDT")
    assert resolve_pending.bea_ita_release_page_refusal(
        wrong_time, "2026-01", ITA_RELEASE_DAY
    ) == (
        "ITA release page does not contain exact registered embargo line "
        "'EMBARGOED UNTIL RELEASE AT 8:30 a.m. EDT, Wednesday, June 24, 2026'"
    )


def test_bea_ita_prompt_catalog_refuses_missing_or_malformed_year_key() -> None:
    raw = _decoded_fixture("ita-table-5-1-2026-q1-qsa.json.base64")
    spec = resolve_pending.BEA_RELEASE_ADAPTERS[ITA_SERIES]

    def remove_key(rows: list[dict[str, Any]]) -> None:
        next(row for row in rows if row["ListDisplayValue"] == "2026").pop("ListKey")

    missing_key = _mutate_ita_prompt_rows(raw, "Filter_#1", remove_key)
    assert resolve_pending.bea_ita_prompt_selection(missing_key, spec, "2026-01") == (
        None,
        "ITA Filter_#1 selector row has the wrong key/display schema",
    )

    def stringify_key(rows: list[dict[str, Any]]) -> None:
        next(row for row in rows if row["ListDisplayValue"] == "2026")["ListKey"] = "1"

    malformed_key = _mutate_ita_prompt_rows(raw, "Filter_#1", stringify_key)
    assert resolve_pending.bea_ita_prompt_selection(malformed_key, spec, "2026-01") == (
        None,
        "ITA Filter_#1 selector row has the wrong key/display schema",
    )


@pytest.mark.parametrize(
    ("prompt_name", "collision", "expected_refusal"),
    [
        (
            "Filter_#1",
            {"ListKey": 1, "ListDisplayValue": "2025"},
            "ITA Filter_#1 selector keys are not globally unique",
        ),
        (
            "Filter_#2",
            {"ListKey": 1, "ListDisplayValue": "Quarterly not adjusted"},
            "ITA Filter_#2 selector keys are not globally unique",
        ),
        (
            "Filter_#3",
            {"ListKey": 18, "ListDisplayValue": "18 Conflicting concept"},
            "ITA Filter_#3 selector keys are not globally unique",
        ),
        (
            "Filter_#1",
            {"ListKey": "1", "ListDisplayValue": "2025"},
            "ITA Filter_#1 selector row has the wrong key/display schema",
        ),
        (
            "Filter_#2",
            {"ListKey": "1", "ListDisplayValue": "Quarterly not adjusted"},
            "ITA Filter_#2 selector row has the wrong key/display schema",
        ),
        (
            "Filter_#3",
            {"ListKey": "18", "ListDisplayValue": "18 Conflicting concept"},
            "ITA Filter_#3 selector row has the wrong key/display schema",
        ),
        (
            "Filter_#1",
            {"ListKey": 99, "ListDisplayValue": "2026"},
            "expected one ITA prompt key for year 2026, found 2",
        ),
        (
            "Filter_#2",
            {"ListKey": 99, "ListDisplayValue": "Quarterly seasonally adjusted"},
            "ITA prompt catalog does not authenticate the QSA selector",
        ),
        (
            "Filter_#3",
            {"ListKey": 99, "ListDisplayValue": "18 Personal transfers"},
            "ITA prompt catalog does not authenticate line 18 Personal transfers",
        ),
    ],
)
def test_bea_ita_prompt_catalog_refuses_selector_key_collisions(
    prompt_name: str,
    collision: dict[str, Any],
    expected_refusal: str,
) -> None:
    raw = _decoded_fixture("ita-table-5-1-2026-q1-qsa.json.base64")
    spec = resolve_pending.BEA_RELEASE_ADAPTERS[ITA_SERIES]
    collided = _mutate_ita_prompt_rows(
        raw, prompt_name, lambda rows: rows.append(collision)
    )

    assert resolve_pending.bea_ita_prompt_selection(collided, spec, "2026-01") == (
        None,
        expected_refusal,
    )


def test_bea_ita_capture_timing_refuses_pre_embargo_fetches() -> None:
    assert (
        resolve_pending.bea_ita_capture_timing_refusal(
            {"release page": "2026-06-24T12:29:59Z"}, ITA_RELEASE_DAY
        )
        == "ITA release page fetch started at 2026-06-24T12:29:59Z, before "
        "embargo 2026-06-24T12:30:00Z"
    )
    assert (
        resolve_pending.bea_ita_capture_timing_refusal(
            {"release page": "2026-06-24T12:30:00Z"}, ITA_RELEASE_DAY
        )
        is None
    )


def test_bea_ita_parser_refuses_wrong_line_and_wrong_basis() -> None:
    raw = _decoded_fixture("ita-table-5-1-2026-q1-qsa.json.base64")
    spec = resolve_pending.BEA_RELEASE_ADAPTERS[ITA_SERIES]

    wrong_line = _mutate_ita_table(
        raw,
        lambda table: next(
            cell
            for cell in table["TD"]
            if cell["Row_ID"] == "6" and cell["Column_ID"] == "1"
        ).update({"Cell_Value": "19"}),
    )
    value, refusal = resolve_pending.bea_ita_itable_value(
        wrong_line, spec, "2026-01", ITA_RELEASE_DAY
    )
    assert value is None
    assert refusal == "expected one exact ITA line 18 'Personal transfers' row, found 0"

    wrong_basis = _mutate_ita_table(
        raw,
        lambda table: next(
            cell
            for cell in table["TD"]
            if cell["Row_ID"] == "1" and cell["Column_ID"] == "3"
        ).update({"Cell_Value": "Not seasonally adjusted"}),
    )
    value, refusal = resolve_pending.bea_ita_itable_value(
        wrong_basis, spec, "2026-01", ITA_RELEASE_DAY
    )
    assert value is None
    assert refusal == "expected one ITA QSA 2026 Q1 column, found 0"


def test_bea_ita_parser_refuses_row_label_only_mutation() -> None:
    raw = _decoded_fixture("ita-table-5-1-2026-q1-qsa.json.base64")
    spec = resolve_pending.BEA_RELEASE_ADAPTERS[ITA_SERIES]

    def relabel_only(table: dict[str, Any]) -> None:
        value_cell = next(
            cell
            for cell in table["TD"]
            if cell["Row_ID"] == "6" and cell["Column_ID"] == "3"
        )
        assert value_cell["Cell_Value"] == "18,511"
        label_cell = next(
            cell
            for cell in table["TD"]
            if cell["Row_ID"] == "6" and cell["Column_ID"] == "2"
        )
        label_cell["Cell_Value"] = "Private transfer payments <sup>3</sup>"

    relabeled = _mutate_ita_table(raw, relabel_only)
    assert resolve_pending.bea_ita_itable_value(
        relabeled, spec, "2026-01", ITA_RELEASE_DAY
    ) == (
        None,
        "expected one exact ITA line 18 'Personal transfers' row, found 0",
    )


def test_bea_ita_parser_refuses_millions_scale_only_mutation() -> None:
    raw = _decoded_fixture("ita-table-5-1-2026-q1-qsa.json.base64")
    spec = resolve_pending.BEA_RELEASE_ADAPTERS[ITA_SERIES]

    def change_scale_only(table: dict[str, Any]) -> None:
        value_cell = next(
            cell
            for cell in table["TD"]
            if cell["Row_ID"] == "6" and cell["Column_ID"] == "3"
        )
        assert value_cell["Cell_Value"] == "18,511"
        table["Sub_Title"] = "[Billions of dollars]"

    wrong_scale = _mutate_ita_table(raw, change_scale_only)
    assert resolve_pending.bea_ita_itable_value(
        wrong_scale, spec, "2026-01", ITA_RELEASE_DAY
    ) == (
        None,
        "unexpected ITA iTable unit subtitle '[Billions of dollars]'",
    )


@pytest.mark.parametrize("raw", [b"not JSON", b'"{\\"AppId\\":62'])
def test_bea_ita_parser_refuses_non_json_and_truncated_response(raw: bytes) -> None:
    value, refusal = resolve_pending.bea_ita_itable_value(
        raw,
        resolve_pending.BEA_RELEASE_ADAPTERS[ITA_SERIES],
        "2026-01",
        ITA_RELEASE_DAY,
    )

    assert value is None
    assert refusal == "ITA iTable response is not complete UTF-8 JSON"


def test_bea_table_revision_stamp_must_equal_registered_release_day() -> None:
    raw = (FIXTURES / "nipa-table-5-3-5-2026-q2.json").read_bytes()
    response = json.loads(raw)
    # The raw fixture is the live double-encoded body: a JSON string
    # wrapping the response object. Unwrap it the way the parser does.
    if isinstance(response, str):
        response = json.loads(response)
    table_prompt = next(
        prompt for prompt in response["Prompts"] if prompt["Name"] == "TheTable"
    )
    prompt_data = json.loads(table_prompt["PromtData"])
    table = json.loads(prompt_data["Table"])
    table["Description"] = (
        "Last Revised on: August 26, 2026 - Next Release Date September 30, 2026"
    )
    prompt_data["Table"] = json.dumps(table, separators=(",", ":"))
    table_prompt["PromtData"] = json.dumps(prompt_data, separators=(",", ":"))
    mutated = json.dumps(response, separators=(",", ":")).encode()
    spec = resolve_pending.BEA_RELEASE_ADAPTERS[
        "bea.private_nonresidential_fixed_investment"
    ]

    value, refusal = resolve_pending.bea_itable_value(
        mutated, spec, "2026-04", RELEASE_DAY
    )

    assert value is None
    assert refusal == (
        "iTable revision stamp 'Last Revised on: August 26, 2026 - Next "
        "Release Date September 30, 2026' does not start with registered "
        "release stamp 'Last Revised on: July 30, 2026'"
    )


@pytest.mark.parametrize(
    ("series", "series_id", "field"),
    [
        (
            "bea.private_nonresidential_fixed_investment",
            "T50305:L2",
            "Line 2: Nonresidential",
        ),
        (
            "bea.research_and_development_fixed_investment",
            "T50305:L18",
            "Line 18: Research and development",
        ),
    ],
)
def test_bea_registry_binds_official_release_parser_and_keeps_alfred_as_mirror(
    series: str, series_id: str, field: str
) -> None:
    _ref, registration, spec, _forecast = _registration(series)
    binding = registration["contract"]["sourceBinding"]

    assert binding["adapter"] == "bea-release"
    assert binding["sourceUrl"] == resolve_pending.BEA_ITABLE_PAGE_URL
    assert binding["sourceSeriesId"] == series_id
    assert binding["field"] == field
    assert binding["transform"] == {"operation": "multiply", "factor": 0.001}
    assert binding["releasePolicy"] == "first_print"
    assert binding["expectedReleaseWindow"] == {
        "start": RELEASE_DAY.isoformat(),
        "end": RELEASE_DAY.isoformat(),
    }
    assert binding["allowedHosts"] == ["apps.bea.gov", "www.bea.gov"]
    assert resolve_pending.bea_release_binding_matches_spec(binding, spec)
    widened = {**binding, "allowedHosts": [*binding["allowedHosts"], "evil.example"]}
    duplicated = {
        **binding,
        "allowedHosts": [*binding["allowedHosts"], "www.bea.gov"],
    }
    assert not resolve_pending.bea_release_binding_matches_spec(widened, spec)
    assert not resolve_pending.bea_release_binding_matches_spec(duplicated, spec)
    assert (
        prospect_targets._source_binding_errors(
            resolve_pending.bea_release_binding_template(spec)
        )
        == []
    )
    assert spec["history_mirror"]["adapter"] == "alfred-fred"
    assert series in resolve_pending.ALFRED_HISTORY_MIRRORS
    assert series not in resolve_pending.ALFRED_ADAPTERS
    assert register_targets.is_calendar_gated_source("bea-release", series)


def test_bea_ita_registry_binds_every_reviewed_selector_without_a_mirror() -> None:
    ref, registration, spec, forecast = _registration(
        ITA_SERIES, release_day=dt.date(2026, 9, 24)
    )
    binding = registration["contract"]["sourceBinding"]

    assert ref == "bea.ita.personal_transfer_payments.2026_q2.first_print"
    assert forecast["unit"] == "usd_millions"
    assert binding == {
        "adapter": "bea-ita-itable",
        "sourceUrl": resolve_pending.BEA_ITA_ITABLE_PAGE_URL,
        "sourceSeriesId": "ITA:T5.1:L18:QSA",
        "field": "Line 18: Personal transfers (QSA)",
        "table": (
            "U.S. International Transactions, Table 5.1, line 18 "
            "(Personal transfers), quarterly seasonally adjusted"
        ),
        "transform": {
            "operation": "identity",
            "factor": 1,
            "applicationId": 62,
            "productId": "1",
            "tableList": "62",
            "lineNumber": "18",
            "rowLabel": "Personal transfers",
            "basis": "QSA",
            "unit": "usd_millions",
            "cadence": "quarterly",
        },
        "releasePolicy": "first_print",
        "expectedReleaseWindow": {"start": "2026-09-24", "end": "2026-09-24"},
        "allowedHosts": ["apps.bea.gov", "www.bea.gov"],
    }
    assert resolve_pending.bea_release_binding_matches_spec(binding, spec)
    assert not resolve_pending.bea_release_binding_matches_spec(
        {
            **binding,
            "allowedHosts": [*binding["allowedHosts"], "alfred.stlouisfed.org"],
        },
        spec,
    )
    assert (
        prospect_targets._source_binding_errors(
            resolve_pending.bea_release_binding_template(spec)
        )
        == []
    )
    for field, bad_value in (
        ("applicationId", 19),
        ("productId", "2"),
        ("tableList", "61"),
        ("lineNumber", "17"),
        ("rowLabel", "Private transfer payments"),
        ("basis", "QNSA"),
        ("unit", "usd_billions"),
        ("cadence", "annual"),
    ):
        drifted = json.loads(json.dumps(binding))
        drifted["transform"][field] = bad_value
        assert not resolve_pending.bea_release_binding_matches_spec(drifted, spec)
        template = {
            key: drifted[key]
            for key in resolve_pending.BEA_RELEASE_BINDING_TEMPLATE_KEYS
        }
        assert prospect_targets._source_binding_errors(template) == [
            "bad BEA ITA sourceBinding transform"
        ]
    assert "history_mirror" not in spec
    assert ITA_SERIES not in resolve_pending.ALFRED_HISTORY_MIRRORS
    assert ITA_SERIES not in resolve_pending.ALFRED_ADAPTERS
    assert register_targets.is_calendar_gated_source("bea-ita-itable", ITA_SERIES)


def test_pending_bea_ita_series_routes_to_official_release_family() -> None:
    ref, _envelope, spec, forecast = _registration(
        ITA_SERIES, release_day=dt.date(2026, 9, 24)
    )
    routed = resolve_pending.pending_adapter_refs(
        {
            "entries": [
                {
                    "kind": "prediction_recorded",
                    "forecastSlug": "bea-ita-release",
                    **forecast,
                }
            ],
            "resolutionLinks": [
                {
                    "status": "pending",
                    "forecastSlug": "bea-ita-release",
                    "targetFactRef": ref,
                }
            ],
        }
    )

    assert len(routed) == 1
    assert routed[0][1] == "bea_release"
    assert routed[0][2] == spec
    assert routed[0][3:5] == ("quarter", "2026-04")


def test_pending_bea_series_route_only_to_official_release_family() -> None:
    registrations = [
        _registration("bea.private_nonresidential_fixed_investment"),
        _registration("bea.research_and_development_fixed_investment"),
    ]
    entries = []
    links = []
    for index, (ref, _registration_envelope, spec, forecast) in enumerate(
        registrations
    ):
        slug = f"bea-release-{index}"
        entries.append(
            {
                "kind": "prediction_recorded",
                "forecastSlug": slug,
                **forecast,
            }
        )
        links.append(
            {
                "status": "pending",
                "forecastSlug": slug,
                "targetFactRef": ref,
            }
        )

    routed = resolve_pending.pending_adapter_refs(
        {"entries": entries, "resolutionLinks": links}
    )

    assert len(routed) == 2
    assert {row[1] for row in routed} == {"bea_release"}
    assert {row[3:5] for row in routed} == {("quarter", "2026-04")}
    assert {row[2]["series_id"] for row in routed} == {
        "T50305:L2",
        "T50305:L18",
    }


def test_main_resolves_both_bea_series_from_real_official_fixtures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registrations = [
        _registration("bea.private_nonresidential_fixed_investment"),
        _registration("bea.research_and_development_fixed_investment"),
    ]
    contracts = {ref: envelope for ref, envelope, _spec, _forecast in registrations}
    entries = []
    links = []
    for index, (ref, _envelope, _spec, forecast) in enumerate(registrations):
        slug = f"bea-release-main-{index}"
        entries.append(
            {
                "kind": "prediction_recorded",
                "forecastSlug": slug,
                **forecast,
            }
        )
        links.append(
            {
                "status": "pending",
                "forecastSlug": slug,
                "targetFactRef": ref,
            }
        )
    log = {"entries": entries, "resolutionLinks": links}
    release_raw = (FIXTURES / "gdp-advance-2026-q2.html").read_bytes()
    table_raw = (FIXTURES / "nipa-table-5-3-5-2026-q2.json").read_bytes()
    calls = {"release": 0, "table": 0}

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(2026, 7, 30)

    expected_release_url = resolve_pending.bea_advance_release_url(
        "2026-04", RELEASE_DAY
    )
    expected_table_body = resolve_pending.bea_itable_request_body(
        registrations[0][2], "2026-04"
    )

    def fake_http_request(
        request: Any,
        *,
        allowed_hosts: list[str] | tuple[str, ...],
        timeout: int = 120,
    ) -> tuple[bytes, str, str]:
        assert tuple(allowed_hosts) == ("apps.bea.gov", "www.bea.gov")
        assert timeout == 120
        if request.full_url == expected_release_url:
            calls["release"] += 1
            assert request.get_method() == "GET"
            assert request.data is None
            return release_raw, "2026-07-30T12:30:01Z", expected_release_url
        assert request.full_url == resolve_pending.BEA_ITABLE_DATA_URL
        calls["table"] += 1
        assert request.get_method() == "POST"
        assert json.loads(request.data) == expected_table_body
        assert request.get_header("Content-type") == "application/json"
        return (
            table_raw,
            "2026-07-30T12:30:02Z",
            resolve_pending.BEA_ITABLE_DATA_URL,
        )

    monkeypatch.setattr(resolve_pending.dt, "date", FixedDate)
    monkeypatch.setattr(resolve_pending, "utc_now", lambda: "2026-07-30T12:30:03Z")
    monkeypatch.setattr(resolve_pending, "load_thesis_log", lambda _url: log)
    monkeypatch.setattr(
        resolve_pending, "ledger_state", lambda *_args: ("", "blob", "b" * 40)
    )
    monkeypatch.setattr(resolve_pending, "registration_contracts", lambda: contracts)
    monkeypatch.setattr(resolve_pending, "http_request", fake_http_request)
    monkeypatch.setattr(
        resolve_pending,
        "fred_vintage_series",
        lambda *_args: pytest.fail("BEA resolution must not call ALFRED"),
    )
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])

    assert resolve_pending.main() == 0

    output = capsys.readouterr().out
    assert "-> 4623.657 usd_billions" in output
    assert "-> 937.772 usd_billions" in output
    assert "dry-run: would append 2 row(s)" in output
    assert calls == {"release": 1, "table": 1}


def test_main_resolves_bea_ita_from_authenticated_notice_catalog_and_table(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ref, envelope, spec, forecast = _registration(
        ITA_SERIES,
        period="2026-Q1",
        release_day=ITA_RELEASE_DAY,
        registration_day=dt.date(2026, 6, 1),
    )
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "bea-ita-main",
                **forecast,
            }
        ],
        "resolutionLinks": [
            {
                "status": "pending",
                "forecastSlug": "bea-ita-main",
                "targetFactRef": ref,
            }
        ],
    }
    release_raw = _decoded_fixture("ita-iip-release-2026-q1.html.base64")
    catalog_raw = _decoded_fixture("ita-prompt-catalog-2026-q1.json.base64")
    table_raw = _decoded_fixture("ita-table-5-1-2026-q1-qsa.json.base64")
    expected_release_url = resolve_pending.bea_ita_release_url(
        "2026-01", ITA_RELEASE_DAY
    )
    catalog_body = resolve_pending.bea_ita_prompt_catalog_request_body(spec)
    table_body = resolve_pending.bea_ita_itable_request_body(spec, "2026-01", "1")
    calls = {"release": 0, "catalog": 0, "table": 0}
    archived: dict[str, bytes] = {}
    real_snapshot = resolve_pending.bea_ita_release_snapshot_envelope

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(2026, 6, 24)

    def fake_http_request(
        request: Any,
        *,
        allowed_hosts: list[str] | tuple[str, ...],
        timeout: int = 120,
    ) -> tuple[bytes, str, str]:
        assert tuple(allowed_hosts) == ("apps.bea.gov", "www.bea.gov")
        assert timeout == 120
        if request.full_url == expected_release_url:
            calls["release"] += 1
            assert request.get_method() == "GET"
            return release_raw, "2026-06-24T12:30:01Z", expected_release_url
        assert request.full_url == resolve_pending.BEA_ITABLE_DATA_URL
        if request.data == ITA_CATALOG_REQUEST_BYTES:
            calls["catalog"] += 1
            return (
                catalog_raw,
                "2026-06-24T12:30:02Z",
                resolve_pending.BEA_ITABLE_DATA_URL,
            )
        assert request.data == ITA_SELECTED_REQUEST_BYTES
        calls["table"] += 1
        return (
            table_raw,
            "2026-06-24T12:30:03Z",
            resolve_pending.BEA_ITABLE_DATA_URL,
        )

    def capture_snapshot(**kwargs: Any) -> bytes:
        archived["catalog"] = kwargs["catalog_raw"]
        archived["table"] = kwargs["table_raw"]
        return real_snapshot(**kwargs)

    monkeypatch.setattr(resolve_pending.dt, "date", FixedDate)
    monkeypatch.setattr(resolve_pending, "utc_now", lambda: "2026-06-24T12:30:04Z")
    monkeypatch.setattr(resolve_pending, "load_thesis_log", lambda _url: log)
    monkeypatch.setattr(
        resolve_pending, "ledger_state", lambda *_args: ("", "blob", "b" * 40)
    )
    monkeypatch.setattr(
        resolve_pending, "registration_contracts", lambda: {ref: envelope}
    )
    monkeypatch.setattr(resolve_pending, "http_request", fake_http_request)
    monkeypatch.setattr(
        resolve_pending, "bea_ita_release_snapshot_envelope", capture_snapshot
    )
    monkeypatch.setattr(
        resolve_pending,
        "fred_vintage_series",
        lambda *_args: pytest.fail("BEA ITA resolution must not call ALFRED"),
    )
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])

    assert resolve_pending.main() == 0

    output = capsys.readouterr().out
    assert "-> 18511.0 usd_millions" in output
    assert "dry-run: would append 1 row(s)" in output
    assert calls == {"release": 1, "catalog": 1, "table": 1}
    assert archived == {"catalog": catalog_raw, "table": table_raw}
    assert resolve_pending.canonical_bytes(catalog_body) == ITA_CATALOG_REQUEST_BYTES
    assert resolve_pending.canonical_bytes(table_body) == ITA_SELECTED_REQUEST_BYTES


def test_main_refuses_bea_ita_release_redirect_from_exact_final_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ref, envelope, _spec, forecast = _registration(
        ITA_SERIES,
        period="2026-Q1",
        release_day=ITA_RELEASE_DAY,
        registration_day=dt.date(2026, 6, 1),
    )
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "bea-ita-final-url-refusal",
                **forecast,
            }
        ],
        "resolutionLinks": [
            {
                "status": "pending",
                "forecastSlug": "bea-ita-final-url-refusal",
                "targetFactRef": ref,
            }
        ],
    }
    release_raw = _decoded_fixture("ita-iip-release-2026-q1.html.base64")
    expected_url = resolve_pending.bea_ita_release_url(
        "2026-01", ITA_RELEASE_DAY
    )
    redirected_url = f"{expected_url}/alias"

    monkeypatch.setattr(resolve_pending, "utc_now", lambda: "2026-06-24T12:30:04Z")
    monkeypatch.setattr(resolve_pending, "load_thesis_log", lambda _url: log)
    monkeypatch.setattr(
        resolve_pending, "ledger_state", lambda *_args: ("", "blob", "b" * 40)
    )
    monkeypatch.setattr(
        resolve_pending, "registration_contracts", lambda: {ref: envelope}
    )
    monkeypatch.setattr(
        resolve_pending,
        "fetch_bea_ita_release_page",
        lambda *_args: (
            release_raw,
            redirected_url,
            "2026-06-24T12:30:01Z",
        ),
    )
    monkeypatch.setattr(
        resolve_pending,
        "fetch_bea_ita_prompt_catalog",
        lambda *_args: pytest.fail("wrong final release URL must stop later fetches"),
    )
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])

    assert resolve_pending.main() == 0

    output = capsys.readouterr().out
    assert (
        "BEA ITA RELEASE PAGE REFUSAL (refusing): "
        f"{ref} — expected exact URL {expected_url!r}, got {redirected_url!r}"
    ) in output
    assert "nothing new to record" in output


def test_main_refuses_bea_current_table_after_registered_release_day_literal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ref, envelope, _spec, forecast = _registration(
        "bea.private_nonresidential_fixed_investment"
    )
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "late-bea-release",
                **forecast,
            }
        ],
        "resolutionLinks": [
            {
                "status": "pending",
                "forecastSlug": "late-bea-release",
                "targetFactRef": ref,
            }
        ],
    }

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(2026, 7, 31)

    monkeypatch.setattr(resolve_pending.dt, "date", FixedDate)
    monkeypatch.setattr(resolve_pending, "utc_now", lambda: "2026-07-31T00:00:00Z")
    monkeypatch.setattr(resolve_pending, "load_thesis_log", lambda _url: log)
    monkeypatch.setattr(
        resolve_pending, "ledger_state", lambda *_args: ("", "blob", "b" * 40)
    )
    monkeypatch.setattr(
        resolve_pending, "registration_contracts", lambda: {ref: envelope}
    )
    monkeypatch.setattr(
        resolve_pending,
        "fetch_bea_release_page",
        lambda *_args: pytest.fail("late capture must fail before any fetch"),
    )
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])

    assert resolve_pending.main() == 0

    output = capsys.readouterr().out
    assert (
        f"  FIRST-PRINT WINDOW MISSED (refusing): {ref} — "
        "registered release day was 2026-07-30"
    ) in output
    assert "nothing new to record" in output


def test_main_refuses_bea_fetch_that_crosses_utc_window_end_literal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ref, envelope, _spec, forecast = _registration(
        "bea.private_nonresidential_fixed_investment"
    )
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "straddled-bea-release",
                **forecast,
            }
        ],
        "resolutionLinks": [
            {
                "status": "pending",
                "forecastSlug": "straddled-bea-release",
                "targetFactRef": ref,
            }
        ],
    }
    release_raw = (FIXTURES / "gdp-advance-2026-q2.html").read_bytes()
    table_raw = (FIXTURES / "nipa-table-5-3-5-2026-q2.json").read_bytes()

    class FixedDate(dt.date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(2026, 7, 30)

    monkeypatch.setattr(resolve_pending.dt, "date", FixedDate)
    monkeypatch.setattr(resolve_pending, "utc_now", lambda: "2026-07-30T23:59:58Z")
    monkeypatch.setattr(resolve_pending, "load_thesis_log", lambda _url: log)
    monkeypatch.setattr(
        resolve_pending, "ledger_state", lambda *_args: ("", "blob", "b" * 40)
    )
    monkeypatch.setattr(
        resolve_pending, "registration_contracts", lambda: {ref: envelope}
    )
    monkeypatch.setattr(
        resolve_pending,
        "fetch_bea_release_page",
        lambda period, day: (
            release_raw,
            resolve_pending.bea_advance_release_url(period, day),
            "2026-07-30T23:59:59Z",
        ),
    )
    monkeypatch.setattr(
        resolve_pending,
        "fetch_bea_itable_table",
        lambda adapter, period: (
            table_raw,
            resolve_pending.BEA_ITABLE_DATA_URL,
            resolve_pending.bea_itable_request_body(adapter, period),
            "2026-07-31T00:00:01Z",
        ),
    )
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])

    assert resolve_pending.main() == 0

    output = capsys.readouterr().out
    assert (
        f"  FIRST-PRINT WINDOW MISSED (refusing): {ref} — capture completed "
        "2026-07-31 after registered release day 2026-07-30"
    ) in output
    assert "nothing new to record" in output
