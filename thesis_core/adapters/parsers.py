"""Shared pure official parsers; legacy resolver imports this implementation.

These helpers intentionally require only the Python standard library. Admission
fixtures and exact transformations are preserved from the reviewed resolver.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import math
import re
from collections.abc import Mapping
from html import unescape
from typing import Any

from thesis_core.canonical import canonical_bytes

BEA_ITABLE_PAGE_URL = (
    "https://apps.bea.gov/iTable/?ReqID=19&step=3&isuri=1&"
    "nipa_table_list=145&categories=survey"
)

BEA_ITA_ITABLE_PAGE_URL = (
    "https://apps.bea.gov/iTable/?ReqID=62&step=6&isuri=1&tablelist=62&product=1"
)

BEA_ITABLE_DATA_URL = "https://apps.bea.gov/iTablecore/data/app/GetStep"

BEA_RELEASE_REQUIRED_HOSTS = {"apps.bea.gov", "www.bea.gov"}

BEA_RELEASE_ALLOWED_HOSTS = {
    *BEA_RELEASE_REQUIRED_HOSTS,
    "alfred.stlouisfed.org",
}

BEA_RELEASE_ADAPTERS: dict[str, dict[str, Any]] = {
    "bea.private_nonresidential_fixed_investment": {
        "table_key": "145",
        "table_id": "T50305",
        "line_number": "2",
        "row_label": "Nonresidential",
        "source_url": BEA_ITABLE_PAGE_URL,
        "series_id": "T50305:L2",
        "field": "Line 2: Nonresidential",
        "transform": "level",
        "value_transform": {"operation": "multiply", "factor": 0.001},
        "unit": "usd_billions",
        "label": "US private nonresidential fixed investment, nominal SAAR",
        "source_name": "bea",
        "source_table": (
            "Gross Domestic Product advance release, NIPA Table 5.3.5, "
            "line 2 (Nonresidential)"
        ),
        "concept_authority": "bea",
        "source_concept": "T50305:L2",
        "measure_concept": "bea.private_nonresidential_fixed_investment",
        "history_mirror": {"adapter": "alfred-fred", "series_id": "PNFI"},
    },
    "bea.research_and_development_fixed_investment": {
        "table_key": "145",
        "table_id": "T50305",
        "line_number": "18",
        "row_label": "Research and development",
        "source_url": BEA_ITABLE_PAGE_URL,
        "series_id": "T50305:L18",
        "field": "Line 18: Research and development",
        "transform": "level",
        "value_transform": {"operation": "multiply", "factor": 0.001},
        "unit": "usd_billions",
        "label": ("US private research and development fixed investment, nominal SAAR"),
        "source_name": "bea",
        "source_table": (
            "Gross Domestic Product advance release, NIPA Table 5.3.5, "
            "line 18 (Research and development)"
        ),
        "concept_authority": "bea",
        "source_concept": "T50305:L18",
        "measure_concept": "bea.research_and_development_fixed_investment",
        "history_mirror": {
            "adapter": "alfred-fred",
            "series_id": "Y006RC1Q027SBEA",
        },
    },
    "bea.ita.personal_transfer_payments": {
        "variant": "ita-itable",
        "binding_adapter": "bea-ita-itable",
        "application_id": 62,
        "step_number": 2,
        # Product is outbound-request custody only: live Product=5 requests
        # return byte-identical responses to Product=1, and the GetStep
        # response does not echo the requested product.  The adapter tests
        # therefore pin the canonical Product=1 request templates themselves.
        "product_id": "1",
        "table_list": "62",
        "prompt_name": "TheTableFlexibleIipIta",
        "frequency_key": "1",
        "frequency": "QSA",
        "frequency_label": "Quarterly seasonally adjusted",
        "header_basis": "Seasonally adjusted",
        "line_number": "18",
        "row_label": "Personal transfers",
        "table_title": "Table 5.1. U.S. International Transactions in Secondary Income",
        "source_url": BEA_ITA_ITABLE_PAGE_URL,
        "series_id": "ITA:T5.1:L18:QSA",
        "field": "Line 18: Personal transfers (QSA)",
        "value_transform": {
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
        "unit": "usd_millions",
        "label": "U.S. personal-transfer payments, quarterly seasonally adjusted",
        "source_name": "bea",
        "source_table": (
            "U.S. International Transactions, Table 5.1, line 18 "
            "(Personal transfers), quarterly seasonally adjusted"
        ),
        "concept_authority": "bea",
        "source_concept": "ITA:T5.1:L18:QSA",
        "measure_concept": "bea.ita.personal_transfer_payments",
    },
}

BEA_RELEASE_BINDING_TEMPLATE_KEYS = {
    "adapter",
    "sourceUrl",
    "sourceSeriesId",
    "field",
    "table",
    "transform",
    "releasePolicy",
}

BEA_RELEASE_BINDING_DERIVED_KEYS = {"expectedReleaseWindow", "allowedHosts"}


def bea_release_binding_template(spec: Mapping[str, Any]) -> dict[str, Any]:
    """The reviewed seven-key binding for an official BEA release parser."""

    return {
        "adapter": spec.get("binding_adapter", "bea-release"),
        "sourceUrl": spec["source_url"],
        "sourceSeriesId": spec["series_id"],
        "field": spec["field"],
        "table": spec["source_table"],
        "transform": spec["value_transform"],
        "releasePolicy": "first_print",
    }


def bea_release_binding_matches_spec(binding: Any, spec: Mapping[str, Any]) -> bool:
    """Authenticate the complete binding before touching either BEA host."""

    if not isinstance(binding, dict):
        return False
    if (
        set(binding) - BEA_RELEASE_BINDING_DERIVED_KEYS
        != BEA_RELEASE_BINDING_TEMPLATE_KEYS
    ):
        return False
    allowed_hosts = binding.get("allowedHosts")
    if not isinstance(allowed_hosts, list):
        return False
    host_set = set(allowed_hosts)
    if (
        len(host_set) != len(allowed_hosts)
        or not BEA_RELEASE_REQUIRED_HOSTS <= host_set
        or not host_set <= BEA_RELEASE_ALLOWED_HOSTS
        or (
            spec.get("variant") == "ita-itable"
            and host_set != BEA_RELEASE_REQUIRED_HOSTS
        )
    ):
        return False
    projection = {key: binding[key] for key in BEA_RELEASE_BINDING_TEMPLATE_KEYS}
    return canonical_bytes(projection) == canonical_bytes(
        bea_release_binding_template(spec)
    )


def _bea_quarter(period: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})-(01|04|07|10)", period)
    if match is None:
        raise ValueError(f"BEA period must be a quarter start, got {period!r}")
    return int(match.group(1)), (int(match.group(2)) - 1) // 3 + 1


def bea_advance_release_url(period: str, release_day: dt.date) -> str:
    """Exact official GDP advance-release page for a quarterly period."""

    year, quarter = _bea_quarter(period)
    ordinal = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}[quarter]
    suffix = f"{ordinal}-quarter-{year}"
    if quarter == 4:
        suffix = f"{ordinal}-quarter-and-year-{year}"
    return f"https://www.bea.gov/news/{release_day.year}/gdp-advance-estimate-{suffix}"


def _bea_release_title(period: str) -> str:
    year, quarter = _bea_quarter(period)
    ordinal = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}[quarter]
    if quarter == 4:
        return f"GDP (Advance Estimate), {ordinal} Quarter and Year {year}"
    return f"GDP (Advance Estimate), {ordinal} Quarter {year}"


def bea_release_page_refusal(
    raw: bytes, period: str, release_day: dt.date
) -> str | None:
    """Verify that fetched BEA HTML names this period's advance release."""

    try:
        page = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "release response is not UTF-8 HTML"
    page = re.sub(r"<script\b[^>]*>.*?</script>", " ", page, flags=re.I | re.S)
    page = re.sub(r"<style\b[^>]*>.*?</style>", " ", page, flags=re.I | re.S)
    visible = " ".join(unescape(re.sub(r"<[^>]+>", " ", page)).split())
    title = _bea_release_title(period)
    date_text = f"{release_day.strftime('%B')} {release_day.day}, {release_day.year}"
    if title not in visible:
        return f"release page does not contain expected title {title!r}"
    embargo = re.search(
        r"EMBARGOED UNTIL RELEASE AT\s+.{1,100}?" + re.escape(date_text),
        visible,
        flags=re.I,
    )
    if embargo is None:
        return (
            f"release page embargo line does not contain registered date {date_text!r}"
        )
    return None


def bea_itable_request_body(spec: Mapping[str, Any], period: str) -> dict[str, Any]:
    year, _quarter = _bea_quarter(period)
    return {
        "appid": 19,
        "stepnum": 3,
        "data": [
            ["Categories", "Survey"],
            ["NIPA_Table_List", str(spec["table_key"])],
            ["First_Year", str(year)],
            ["Last_Year", str(year)],
            ["Scale", "-6"],
            ["Series", "Q"],
            ["Select_all_years", "0"],
        ],
    }


def _bea_cell_value(cell: Any) -> str:
    return str(cell.get("CV") or "") if isinstance(cell, dict) else ""


def _bea_row_label(value: str) -> str:
    value = re.sub(r"<sup\b[^>]*>.*?</sup>", "", value, flags=re.I | re.S)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split())


def bea_itable_value(
    raw: bytes,
    spec: Mapping[str, Any],
    period: str,
    release_day: dt.date,
) -> tuple[float | None, str | None]:
    """Read one exact quarterly row from BEA's official iTable response."""

    try:
        response = json.loads(raw.decode("utf-8"))
        # The live iTable endpoint double-encodes: the HTTP body is a JSON
        # string whose contents are the response object. Unwrap exactly one
        # string layer; anything else still refuses below.
        if isinstance(response, str):
            response = json.loads(response)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "iTable response is not UTF-8 JSON"
    if not isinstance(response, dict) or response.get("Number") != 3:
        return None, "iTable response is not the interactive-data table step"
    prompts = response.get("Prompts")
    if not isinstance(prompts, list):
        return None, "iTable response has no prompt list"
    table_prompts = [
        prompt
        for prompt in prompts
        if isinstance(prompt, dict)
        and prompt.get("Name") == "TheTable"
        and prompt.get("UIControl") == "Table"
    ]
    if len(table_prompts) != 1:
        return None, f"expected one iTable table prompt, found {len(table_prompts)}"
    try:
        prompt_data = json.loads(table_prompts[0]["PromtData"])
        table = json.loads(prompt_data["Table"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return None, "iTable prompt does not contain a parseable table"
    if not isinstance(table, dict):
        return None, "iTable payload is not a table object"
    if table.get("Title") != "Table 5.3.5. Private Fixed Investment by Type":
        return None, f"unexpected iTable title {table.get('Title')!r}"
    revision_text = (
        f"Last Revised on: {release_day.strftime('%B')} "
        f"{release_day.day}, {release_day.year}"
    )
    description = str(table.get("Description") or "")
    if not description.startswith(revision_text):
        return None, (
            f"iTable revision stamp {description!r} does not start with "
            f"registered release stamp {revision_text!r}"
        )
    subtitle = str(table.get("Sub_Title") or "")
    if (
        "[Millions of dollars]" not in subtitle
        or "Seasonally adjusted at annual rates" not in subtitle
    ):
        return None, f"unexpected iTable unit/basis subtitle {subtitle!r}"
    rows = table.get("Data_Rows")
    if (
        not isinstance(rows, list)
        or len(rows) < 3
        or not isinstance(rows[0], list)
        or not isinstance(rows[1], list)
    ):
        return None, "iTable response is missing quarterly headers and rows"
    year, quarter = _bea_quarter(period)
    year_cells = [_bea_cell_value(cell) for cell in rows[0]]
    quarter_cells = [_bea_cell_value(cell) for cell in rows[1]]
    columns = [
        index
        for index in range(2, min(len(year_cells), len(quarter_cells)))
        if year_cells[index] == str(year) and quarter_cells[index] == f"Q{quarter}"
    ]
    if len(columns) != 1:
        return None, (
            f"expected one {year} Q{quarter} iTable column, found {len(columns)}"
        )
    matches = []
    for row in rows[2:]:
        if not isinstance(row, list) or len(row) < 2:
            continue
        if _bea_cell_value(row[0]) != str(spec["line_number"]):
            continue
        if _bea_row_label(_bea_cell_value(row[1])) != spec["row_label"]:
            continue
        matches.append(row)
    if len(matches) != 1:
        return None, (
            f"expected one exact line {spec['line_number']} "
            f"{spec['row_label']!r} row, found {len(matches)}"
        )
    column = columns[0]
    if column >= len(matches[0]):
        return None, "exact iTable row is shorter than its quarter headers"
    printed = _bea_cell_value(matches[0][column]).replace(",", "").strip()
    try:
        value = float(printed)
    except ValueError:
        return None, f"exact iTable cell is not numeric: {printed!r}"
    if not math.isfinite(value) or value < 0:
        return None, f"exact iTable cell is not a nonnegative finite value: {value}"
    transform = spec.get("value_transform")
    if transform != {"operation": "multiply", "factor": 0.001}:
        return None, f"unsupported BEA value transform {transform!r}"
    return round(value * 0.001, 4) + 0.0, None


def bea_release_snapshot_envelope(
    *,
    spec: Mapping[str, Any],
    period: str,
    value: float,
    release_url: str,
    release_raw: bytes,
    release_retrieved_at: str,
    table_url: str,
    table_body: Mapping[str, Any],
    table_raw: bytes,
    table_retrieved_at: str,
) -> bytes:
    """Archive both official responses and the deterministic table parse."""

    envelope = {
        "schemaVersion": "bea_release_snapshot_v1",
        "release": {
            "url": release_url,
            "retrievedAt": release_retrieved_at,
            "sha256": hashlib.sha256(release_raw).hexdigest(),
            "bodyBase64": base64.b64encode(release_raw).decode("ascii"),
        },
        "table": {
            "url": table_url,
            "landingPageUrl": spec["source_url"],
            "request": table_body,
            "retrievedAt": table_retrieved_at,
            "sha256": hashlib.sha256(table_raw).hexdigest(),
            "bodyBase64": base64.b64encode(table_raw).decode("ascii"),
        },
        "derived": {
            "period": period,
            "sourceSeriesId": spec["series_id"],
            "value": value,
        },
    }
    return canonical_bytes(envelope) + b"\n"


_STATCAN_CPI_SPEC = {
    "kind": "statcan",
    "series_id": "statcan-v41690973",
    "admission_fixture": "statcan_cpi_v41690973.json",
    "source_file": "getDataFromVectorsAndLatestNPeriods (WDS JSON)",
    "extension": "json",
    "vector": 41690973,
    "latest_n": 48,
    "product": "18-10-0004-01",
    "transform": "yoy_from_index",
    "round": 1,
    "unit": "percent",
    "label": "Canada CPI all-items, 12-month change (NSA)",
    "source_name": "statcan",
    "source_table": "Consumer Price Index, Table 18-10-0004-01 (all-items, Canada)",
    "concept_authority": "statcan",
    "source_concept": "v41690973",
    "country": "CA",
    "valid_range": (-5.0, 25.0),
    "release_calendar_url": (
        "https://www150.statcan.gc.ca/n1/release-diffusion/2026-eng.pdf"
    ),
    # StatCan CPI indexes are not revised after publication (corrections
    # only), and the published 12-month change is computed from rounded
    # index values — verified 2026-07-10: computed YoY reproduced all six
    # recorded anchors exactly (Nov25 2.2, Dec25 2.4, Jan 2.3, Feb 1.8,
    # Mar 2.4, Apr 2.8). May 2026 was released 2026-06-22 on the updated
    # basket (weights effective 2026-06-15), which chain-links within the
    # same index series.
    "anchors": {},
    "verified_anchors": {
        "2026-02": 1.8,
        "2026-03": 2.4,
        "2026-04": 2.8,
        "2026-05": 3.2,
    },
    "anchor_tolerance": 0.1,
}

_ABS_UR_SPEC = {
    "kind": "abs",
    "series_id": "abs-lf-unemployment-rate",
    "admission_fixture": "abs_lfs_unemployment_rate.json",
    "source_file": "ABS Data API SDMX-JSON",
    "extension": "json",
    "flow": "LF",
    "key": "M13.3.1599.20.AUS.M",
    "latest_n": 30,
    "transform": "level",
    "round": 1,
    "unit": "percent",
    "label": "Australia unemployment rate (SA)",
    "source_name": "abs",
    "source_table": (
        "Labour Force, Australia (dataflow LF: unemployment rate, persons, "
        "total age, seasonally adjusted, Australia)"
    ),
    "concept_authority": "abs",
    "source_concept": "LF/M13.3.1599.20.AUS.M",
    "country": "AU",
    "valid_range": (0.0, 25.0),
    "release_calendar_url": (
        "https://www.abs.gov.au/statistics/labour/employment-and-unemployment/"
        "labour-force-australia"
    ),
    # The Data API serves unrounded rates; rounding to one decimal (as ABS
    # headlines) reproduced three recorded first prints in the real
    # 2026-07-10 response (Mar 4.278->4.3, Apr 4.481->4.5, May
    # 4.356->4.4, the May release-day page confirming "decreased by
    # 0.1ppts to 4.4%"). SA rates revise by ~0.1pp at later releases,
    # hence the window and tolerance. The July sandbox could not recapture
    # real API bytes after June was published, so June is not an anchor.
    # The first-print checks below are admission evidence, not mutable live
    # sentinels. Exact flow/key dimensions plus the registered release window
    # gate recurring execution after ABS revises historical SA rates.
    "anchors": {},
    "verified_anchors": {
        "2026-03": 4.3,
        "2026-04": 4.5,
        "2026-05": 4.4,
    },
    "anchor_tolerance": 0.15,
    "first_print_window_days": 18,
}


def _install_intl_binding(
    spec: dict[str, Any],
    *,
    adapter: str,
    source_url: str,
    source_series_id: str,
    field: str,
    operation: str,
    factor: float = 1,
) -> None:
    spec["binding"] = {
        "adapter": adapter,
        "sourceUrl": source_url,
        "sourceSeriesId": source_series_id,
        "field": field,
        "table": spec["source_table"],
        "transform": {"operation": operation, "factor": factor},
        "releasePolicy": "first_print",
    }


INTL_BINDING_KEYS = {
    "adapter",
    "sourceUrl",
    "sourceSeriesId",
    "field",
    "table",
    "transform",
    "releasePolicy",
}


def intl_binding_template(spec: dict[str, Any]) -> dict[str, Any]:
    """The byte-significant seven-key registry template for an adapter."""
    binding = spec.get("binding")
    if not isinstance(binding, dict) or set(binding) != INTL_BINDING_KEYS:
        raise ValueError(
            f"{spec.get('series_id', 'international adapter')} has no exact "
            "seven-key registry binding"
        )
    return binding


def intl_binding_mismatches(spec: dict[str, Any], binding: dict[str, Any]) -> list[str]:
    """Return registry/adapter drift before any source request is made."""
    try:
        expected = intl_binding_template(spec)
    except ValueError:
        return ["adapterTemplate"]
    mismatches = [
        key for key in sorted(INTL_BINDING_KEYS) if binding.get(key) != expected[key]
    ]
    allowed = set(binding.get("allowedHosts") or [])
    if not set(spec["allowed_hosts"]).issubset(allowed):
        mismatches.append("allowedHosts")
    return mismatches


def statcan_series_from_payload(raw: bytes, vector: int) -> dict[str, float]:
    """Parse one vector from a StatCan latest-N WDS JSON response."""
    payload = json.loads(raw.decode())
    if (
        not isinstance(payload, list)
        or len(payload) != 1
        or payload[0].get("status") != "SUCCESS"
    ):
        raise ValueError(f"WDS status not SUCCESS for vector {vector}")
    response_object = payload[0].get("object")
    if (
        not isinstance(response_object, dict)
        or response_object.get("vectorId") != vector
    ):
        got = (
            response_object.get("vectorId")
            if isinstance(response_object, dict)
            else None
        )
        raise ValueError(f"WDS returned vector {got!r}, expected {vector}")
    points = response_object.get("vectorDataPoint")
    if not isinstance(points, list):
        raise ValueError(f"WDS vector {vector} has no data points")
    return {
        str(p["refPer"])[:7]: float(p["value"])
        for p in points
        if isinstance(p, dict) and p.get("value") is not None
    }


def normalize_sdmx_period(period: str) -> str:
    """Normalize monthly/quarterly SDMX periods to the ledger's YYYY-MM key."""
    quarter = re.fullmatch(r"(\d{4})-Q([1-4])", period)
    if quarter:
        return f"{quarter.group(1)}-{(int(quarter.group(2)) - 1) * 3 + 1:02d}"
    if re.fullmatch(r"\d{4}-\d{2}", period):
        return period
    raise ValueError(f"unsupported SDMX period {period!r}")


def abs_series_from_payload(raw: bytes, flow: str, key: str) -> dict[str, float]:
    """Parse one ABS SDMX-JSON 2.0 series."""
    payload = json.loads(raw.decode())
    data = payload["data"]
    structure = data["structures"][0]
    data_sets = data.get("dataSets")
    if not isinstance(data_sets, list) or len(data_sets) != 1:
        raise ValueError(f"ABS key {flow}/{key}: response has no single dataset")
    dataset = data_sets[0]
    links = dataset.get("links") or []
    expected_urn_part = f"DataStructure=ABS:{flow}("
    if not any(
        expected_urn_part in str(link.get("urn") or "")
        for link in links
        if isinstance(link, dict)
    ):
        raise ValueError(f"ABS response is not dataflow {flow}")
    all_series = dataset.get("series")
    if not isinstance(all_series, dict):
        raise ValueError(f"ABS key {flow}/{key}: response has no series map")
    if len(all_series) != 1:
        raise ValueError(f"ABS key {flow}/{key} matched {len(all_series)} series")
    series_index, series_payload = next(iter(all_series.items()))
    series_dimensions = structure["dimensions"].get("series")
    indexes = series_index.split(":")
    if not isinstance(series_dimensions, list) or len(series_dimensions) != len(
        indexes
    ):
        raise ValueError(f"ABS key {flow}/{key}: series dimensions drifted")
    actual_key_parts: list[str] = []
    for dimension, index in zip(series_dimensions, indexes, strict=True):
        values = dimension.get("values")
        try:
            actual_key_parts.append(str(values[int(index)]["id"]))
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"ABS key {flow}/{key}: invalid series dimension index"
            ) from exc
    actual_key = ".".join(actual_key_parts)
    if actual_key != key:
        raise ValueError(f"ABS returned key {actual_key!r}, expected {key!r}")
    time_dimensions = [
        dim
        for dim in structure["dimensions"].get("observation") or []
        if dim.get("id") == "TIME_PERIOD"
    ]
    if len(time_dimensions) != 1:
        raise ValueError(f"ABS key {flow}/{key}: TIME_PERIOD dimension drifted")
    times = [value["id"] for value in time_dimensions[0]["values"]]
    observations = series_payload["observations"]
    return {
        normalize_sdmx_period(times[int(index)]): float(values[0])
        for index, values in observations.items()
        if values and values[0] is not None
    }


def intl_transformed_value(
    spec: dict[str, Any], series: dict[str, float], period: str
) -> float | None:
    """Apply the spec's transform over normalized monthly/quarterly keys."""
    transform = spec.get("transform", "level")
    if period not in series:
        return None
    if transform == "level":
        value = series[period]
    elif transform == "mom_diff":
        prior = prior_period_date(period, spec.get("period_type", "month"))
        if prior not in series:
            return None
        value = series[period] - series[prior]
    elif transform == "mom_pct":
        prior = prior_period_date(period, spec.get("period_type", "month"))
        if prior not in series or not series[prior]:
            return None
        value = (series[period] / series[prior] - 1) * 100
    elif transform == "yoy_from_index":
        prior = f"{int(period[:4]) - 1}-{period[5:7]}"
        if prior not in series or not series[prior]:
            return None
        value = (series[period] / series[prior] - 1) * 100
    else:
        raise ValueError(f"unknown intl transform {transform!r}")
    value *= spec.get("scale", 1)
    digits = spec.get("round")
    if digits is not None:
        value = round(value, digits)
    # IEEE -0.0 survives round() and splits Python's json ("-0.0") from
    # JSON.stringify ("0") downstream; normalize before the value enters
    # any ledger row (same guard as the spawn intake).
    return round(value, 4) + 0.0


def prior_period_date(period_date: str, period_type: str) -> str:
    if period_type in {"year", "fiscal_year"}:
        if not re.fullmatch(r"\d{4}", period_date):
            raise ValueError(f"{period_type} period must be YYYY, got {period_date!r}")
        return str(int(period_date) - 1)
    if not re.fullmatch(r"\d{4}-\d{2}", period_date):
        raise ValueError(f"{period_type} period must be YYYY-MM, got {period_date!r}")
    year, month = int(period_date[:4]), int(period_date[5:7])
    step = 3 if period_type == "quarter" else 1
    month -= step
    if month < 1:
        month += 12
        year -= 1
    return f"{year}-{month:02d}"
