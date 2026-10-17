"""Exact legacy registrations reviewed for release-capture execution.

These fingerprints are a run-time disposition for named historical targets,
not an admission path for new generic-url registrations. Archive execution is
held for founder decision d1633; this table does not change any registration,
docket, waiver, or record. No target-window capture was read to build it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from canonical_json import canonical_bytes, canonical_sha256


def _entry(
    contract: dict[str, Any],
    parser: str,
    schema_version: str,
    ledger_pin: dict[str, Any] | None = None,
    *,
    stem: str | None = None,
) -> dict[str, Any]:
    # v3 hashes bind the Ledger pin as well as the target; v2 binds only the
    # schema and target. Retain that authenticated payload in trusted code so
    # execution checks the reviewed content hash without loading any records.
    payload: dict[str, Any] = {"schemaVersion": schema_version, "targets": [contract]}
    if ledger_pin is not None:
        payload["ledgerPin"] = ledger_pin
    entry = {"contract": contract, "parser": parser, "hashPayload": payload}
    if stem is not None:
        entry["stem"] = stem
    return entry


LEGACY_RELEASE_CAPTURE_CONTRACTS: dict[str, dict[str, Any]] = {
    "c51aedd86599c0c9163b11528a567965d96f5338af58949f3b77221f8f502bfc": _entry(
        {
            "catalogSlug": "us-cpi-u-mom-august-2026",
            "country": "US",
            "dataPointId": "bls.cpi.u.headline_mom.august_2026.first_print",
            "period": "2026-08",
            "series": "bls.cpi.u.headline_mom",
            "sourceBinding": {
                "adapter": "generic-url",
                "allowedHosts": ["www.bls.gov"],
                "expectedReleaseWindow": {"end": "2026-09-16", "start": "2026-09-08"},
                "field": "bls.cpi.u.headline_mom",
                "releasePolicy": "first_print",
                "sourceSeriesId": "bls.cpi.u.headline_mom",
                "sourceUrl": "https://www.bls.gov/news.release/cpi.nr0.htm",
                "table": "U.S. Bureau of Labor Statistics Consumer Price Index news "
                "release",
                "transform": {"factor": 1, "operation": "multiply"},
            },
            "unit": "percent_growth",
            "valueScale": 1,
        },
        "cpi_headline_mom",
        "thesis_target_registration_v3",
        {
            "branch": "codex/thesis-ledger-facts",
            "jsonlSha256": (
                "b0c29d7cb2aee323a5d30f8196eb59f62aa396066070131c5048740659d5e241"
            ),
            "lineCount": 171,
            "repo": "PolicyEngine/chronicle",
            "sha": "661467ed79412edd8fda4be472f9f7faf98c924e",
        },
    ),
    "c5c7ee4179242c4b5e0dbac49e81072b8f6c4db8b77f7caab6da662e8f65255f": _entry(
        {
            "catalogSlug": "us-cpi-u-mom-september-2026",
            "country": "US",
            "dataPointId": "bls.cpi.u.headline_mom.september_2026.first_print",
            "period": "2026-09",
            "series": "bls.cpi.u.headline_mom",
            "sourceBinding": {
                "adapter": "generic-url",
                "allowedHosts": ["www.bls.gov"],
                "expectedReleaseWindow": {"end": "2026-10-15", "start": "2026-10-07"},
                "field": "bls.cpi.u.headline_mom",
                "releasePolicy": "first_print",
                "sourceSeriesId": "bls.cpi.u.headline_mom",
                "sourceUrl": "https://www.bls.gov/news.release/cpi.nr0.htm",
                "table": "U.S. Bureau of Labor Statistics Consumer Price Index news "
                "release",
                "transform": {"factor": 1, "operation": "multiply"},
            },
            "unit": "percent_growth",
            "valueScale": 1,
        },
        "cpi_headline_mom",
        "thesis_target_registration_v3",
        {
            "branch": "codex/thesis-ledger-facts",
            "catalogBytes": 203542,
            "catalogSha256": (
                "77753f23363f6c430ae08cc101436da2ab5d120f0d7427a497270400da13f750"
            ),
            "jsonlSha256": (
                "d4fe16b9072cc8493f3f47b1554ee96a96e89183952941dc111345480717b1e5"
            ),
            "lineCount": 216,
            "repo": "PolicyEngine/chronicle",
            "sha": "d77afe26d83827331d633f63bb50575078b11710",
        },
    ),
    "7f06e063b1a3cfb4fc7b99061e8dd2223e358084787c4cee16f470e22eaf5e12": _entry(
        {
            "catalogSlug": "us-core-cpi-mom-august-2026",
            "country": "US",
            "dataPointId": "bls.cpi.u.core_mom.august_2026.first_print",
            "period": "2026-08",
            "series": "bls.cpi.u.core_mom",
            "sourceBinding": {
                "adapter": "generic-url",
                "allowedHosts": ["www.bls.gov"],
                "expectedReleaseWindow": {"end": "2026-09-16", "start": "2026-09-08"},
                "field": "bls.cpi.u.core_mom",
                "releasePolicy": "first_print",
                "sourceSeriesId": "bls.cpi.u.core_mom",
                "sourceUrl": "https://www.bls.gov/news.release/cpi.nr0.htm",
                "table": "U.S. Bureau of Labor Statistics Consumer Price Index news "
                "release",
                "transform": {"factor": 1, "operation": "multiply"},
            },
            "unit": "percent_growth",
            "valueScale": 1,
        },
        "cpi_core_mom",
        "thesis_target_registration_v3",
        {
            "branch": "codex/thesis-ledger-facts",
            "jsonlSha256": (
                "b0c29d7cb2aee323a5d30f8196eb59f62aa396066070131c5048740659d5e241"
            ),
            "lineCount": 171,
            "repo": "PolicyEngine/chronicle",
            "sha": "661467ed79412edd8fda4be472f9f7faf98c924e",
        },
    ),
    "666261cec19a56b9b6ecf64c9af43bfa61c5ba5cc0df43fdb99d3830912c1d37": _entry(
        {
            "catalogSlug": "us-core-cpi-mom-september-2026",
            "country": "US",
            "dataPointId": "bls.cpi.u.core_mom.september_2026.first_print",
            "period": "2026-09",
            "series": "bls.cpi.u.core_mom",
            "sourceBinding": {
                "adapter": "generic-url",
                "allowedHosts": ["www.bls.gov"],
                "expectedReleaseWindow": {"end": "2026-10-15", "start": "2026-10-07"},
                "field": "bls.cpi.u.core_mom",
                "releasePolicy": "first_print",
                "sourceSeriesId": "bls.cpi.u.core_mom",
                "sourceUrl": "https://www.bls.gov/news.release/cpi.nr0.htm",
                "table": "U.S. Bureau of Labor Statistics Consumer Price Index news "
                "release",
                "transform": {"factor": 1, "operation": "multiply"},
            },
            "unit": "percent_growth",
            "valueScale": 1,
        },
        "cpi_core_mom",
        "thesis_target_registration_v3",
        {
            "branch": "codex/thesis-ledger-facts",
            "catalogBytes": 203542,
            "catalogSha256": (
                "77753f23363f6c430ae08cc101436da2ab5d120f0d7427a497270400da13f750"
            ),
            "jsonlSha256": (
                "d4fe16b9072cc8493f3f47b1554ee96a96e89183952941dc111345480717b1e5"
            ),
            "lineCount": 216,
            "repo": "PolicyEngine/chronicle",
            "sha": "d77afe26d83827331d633f63bb50575078b11710",
        },
    ),
    "ee40ca45dbbd92d41117ea4d5d678fe815ae3a21d5db698050b009e0f27fa0e4": _entry(
        {
            "catalogSlug": "unemployment-rate-august-2026",
            "country": "US",
            "dataPointId": "bls.cps.unemployment_rate.august_2026.first_print",
            "period": "2026-08",
            "series": "bls.cps.unemployment_rate",
            "sourceBinding": {
                "adapter": "generic-url",
                "allowedHosts": ["www.bls.gov"],
                "expectedReleaseWindow": {"end": "2026-09-11", "start": "2026-09-03"},
                "field": "bls.cps.unemployment_rate",
                "releasePolicy": "first_print",
                "sourceSeriesId": "bls.cps.unemployment_rate",
                "sourceUrl": "https://www.bls.gov/news.release/empsit.nr0.htm",
                "table": "U.S. Bureau of Labor Statistics, Employment Situation "
                "(Current Population Survey)",
                "transform": {"factor": 1, "operation": "multiply"},
            },
            "unit": "percent",
            "valueScale": 1,
        },
        "empsit_unemployment_rate",
        "thesis_target_registration_v3",
        {
            "branch": "codex/thesis-ledger-facts",
            "jsonlSha256": (
                "b0c29d7cb2aee323a5d30f8196eb59f62aa396066070131c5048740659d5e241"
            ),
            "lineCount": 171,
            "repo": "PolicyEngine/chronicle",
            "sha": "661467ed79412edd8fda4be472f9f7faf98c924e",
        },
    ),
    "4f9351e9599bb007177abdf8c158ee801328243b30407e6ff10d9b25084c2d8a": _entry(
        {
            "catalogSlug": "unemployment-rate-september-2026",
            "country": "US",
            "dataPointId": "bls.cps.unemployment_rate.september_2026.first_print",
            "period": "2026-09",
            "series": "bls.cps.unemployment_rate",
            "sourceBinding": {
                "adapter": "generic-url",
                "allowedHosts": ["www.bls.gov"],
                "expectedReleaseWindow": {"end": "2026-10-08", "start": "2026-09-30"},
                "field": "bls.cps.unemployment_rate",
                "releasePolicy": "first_print",
                "sourceSeriesId": "bls.cps.unemployment_rate",
                "sourceUrl": "https://www.bls.gov/news.release/empsit.nr0.htm",
                "table": "U.S. Bureau of Labor Statistics Employment Situation "
                "(Current Population Survey)",
                "transform": {"factor": 1, "operation": "multiply"},
            },
            "unit": "percent",
            "valueScale": 1,
        },
        "empsit_unemployment_rate",
        "thesis_target_registration_v3",
        {
            "branch": "codex/thesis-ledger-facts",
            "catalogBytes": 203542,
            "catalogSha256": (
                "77753f23363f6c430ae08cc101436da2ab5d120f0d7427a497270400da13f750"
            ),
            "jsonlSha256": (
                "d4fe16b9072cc8493f3f47b1554ee96a96e89183952941dc111345480717b1e5"
            ),
            "lineCount": 216,
            "repo": "PolicyEngine/chronicle",
            "sha": "d77afe26d83827331d633f63bb50575078b11710",
        },
    ),
    "54376e2b403296fbe00a7087626388a7b47b6967974cb1856a1d50f1ce4cdda2": _entry(
        {
            "catalogSlug": "nonfarm-payrolls-august-2026",
            "country": "US",
            "dataPointId": (
                "bls.ces.total_nonfarm.payroll_employment.change.sa.2026-08.first_print"
            ),
            "period": "2026-08",
            "series": "bls.ces.nonfarm_payrolls.change",
            "sourceBinding": {
                "adapter": "generic-url",
                "allowedHosts": ["www.bls.gov"],
                "expectedReleaseWindow": {"end": "2026-09-11", "start": "2026-09-03"},
                "field": "bls.ces.nonfarm_payrolls.change",
                "releasePolicy": "first_print",
                "sourceSeriesId": "bls.ces.nonfarm_payrolls.change",
                "sourceUrl": "https://www.bls.gov/news.release/empsit.nr0.htm",
                "table": "Official agency release",
                "transform": {"factor": 1, "operation": "multiply"},
            },
            "unit": "thousands",
            "valueScale": 1,
        },
        "empsit_payroll_change",
        "thesis_target_registration_v3",
        {
            "branch": "codex/thesis-ledger-facts",
            "jsonlSha256": (
                "b0c29d7cb2aee323a5d30f8196eb59f62aa396066070131c5048740659d5e241"
            ),
            "lineCount": 171,
            "repo": "PolicyEngine/chronicle",
            "sha": "661467ed79412edd8fda4be472f9f7faf98c924e",
        },
    ),
    "588ebf8cdde209f7bb4aa76660059207951e0786ee12bfecf197ab6d18af34f6": _entry(
        {
            "catalogSlug": "nonfarm-payrolls-september-2026",
            "country": "US",
            "dataPointId": (
                "bls.ces.total_nonfarm.payroll_employment.change.sa.2026-09.first_print"
            ),
            "period": "2026-09",
            "series": "bls.ces.nonfarm_payrolls.change",
            "sourceBinding": {
                "adapter": "generic-url",
                "allowedHosts": ["www.bls.gov"],
                "expectedReleaseWindow": {"end": "2026-10-08", "start": "2026-09-30"},
                "field": "bls.ces.nonfarm_payrolls.change",
                "releasePolicy": "first_print",
                "sourceSeriesId": "bls.ces.nonfarm_payrolls.change",
                "sourceUrl": "https://www.bls.gov/news.release/empsit.nr0.htm",
                "table": "Official agency release",
                "transform": {"factor": 1, "operation": "multiply"},
            },
            "unit": "thousands",
            "valueScale": 1,
        },
        "empsit_payroll_change",
        "thesis_target_registration_v3",
        {
            "branch": "codex/thesis-ledger-facts",
            "catalogBytes": 203542,
            "catalogSha256": (
                "77753f23363f6c430ae08cc101436da2ab5d120f0d7427a497270400da13f750"
            ),
            "jsonlSha256": (
                "d4fe16b9072cc8493f3f47b1554ee96a96e89183952941dc111345480717b1e5"
            ),
            "lineCount": 216,
            "repo": "PolicyEngine/chronicle",
            "sha": "d77afe26d83827331d633f63bb50575078b11710",
        },
    ),
    "21e06e0656e420fc38e5db6513825baad3becf73234e1df0a074fcadcc13535f": _entry(
        {
            "catalogSlug": "jolts-openings-july-2026",
            "country": "US",
            "dataPointId": "bls.jolts.job_openings.july_2026.first_print",
            "period": "2026-07",
            "series": "bls.jolts.job_openings",
            "sourceBinding": {
                "adapter": "generic-url",
                "allowedHosts": ["www.bls.gov"],
                "expectedReleaseWindow": {"end": "2026-09-08", "start": "2026-08-31"},
                "field": "bls.jolts.job_openings",
                "releasePolicy": "first_print",
                "sourceSeriesId": "bls.jolts.job_openings",
                "sourceUrl": "https://www.bls.gov/news.release/jolts.nr0.htm",
                "table": "U.S. Bureau of Labor Statistics, Job Openings and Labor "
                "Turnover Survey",
                "transform": {"factor": 0.001, "operation": "multiply"},
            },
            "unit": "millions",
            "valueScale": 0.001,
        },
        "jolts_job_openings",
        "thesis_target_registration_v2",
    ),
    "66a38cce6c472dec90f4d80d7b32fa5be061746652b89c5733473d64ef4b6218": _entry(
        {
            "catalogSlug": "jolts-openings-august-2026",
            "country": "US",
            "dataPointId": "bls.jolts.job_openings.august_2026.first_print",
            "period": "2026-08",
            "series": "bls.jolts.job_openings",
            "sourceBinding": {
                "adapter": "generic-url",
                "allowedHosts": ["www.bls.gov"],
                "expectedReleaseWindow": {"end": "2026-10-05", "start": "2026-09-27"},
                "field": "bls.jolts.job_openings",
                "releasePolicy": "first_print",
                "sourceSeriesId": "bls.jolts.job_openings",
                "sourceUrl": "https://www.bls.gov/news.release/jolts.nr0.htm",
                "table": "U.S. Bureau of Labor Statistics, Job Openings and Labor "
                "Turnover Survey",
                "transform": {"factor": 0.001, "operation": "multiply"},
            },
            "unit": "millions",
            "valueScale": 0.001,
        },
        "jolts_job_openings",
        "thesis_target_registration_v3",
        {
            "branch": "codex/thesis-ledger-facts",
            "jsonlSha256": (
                "b0c29d7cb2aee323a5d30f8196eb59f62aa396066070131c5048740659d5e241"
            ),
            "lineCount": 171,
            "repo": "PolicyEngine/chronicle",
            "sha": "661467ed79412edd8fda4be472f9f7faf98c924e",
        },
    ),
    "53d574820f5ef4c802754d8b06524a23672358e5dc546c4db118d3e3e5406ec7": _entry(
        {
            "catalogSlug": "jolts-quits-rate-july-2026",
            "country": "US",
            "dataPointId": "bls.jolts.quits_rate.2026-07.first_print",
            "period": "2026-07",
            "series": "bls.jolts.quits_rate",
            "sourceBinding": {
                "adapter": "generic-url",
                "allowedHosts": ["www.bls.gov"],
                "expectedReleaseWindow": {"end": "2026-09-08", "start": "2026-08-31"},
                "field": "bls.jolts.quits_rate",
                "releasePolicy": "first_print",
                "sourceSeriesId": "bls.jolts.quits_rate",
                "sourceUrl": "https://www.bls.gov/news.release/jolts.t04.htm",
                "table": "U.S. Bureau of Labor Statistics Job Openings and Labor "
                "Turnover Survey Table 4",
                "transform": {"factor": 1, "operation": "multiply"},
            },
            "unit": "percent",
            "valueScale": 1,
        },
        "jolts_quits_rate",
        "thesis_target_registration_v2",
    ),
    "918146c0e3bb21526c56eb23c225d8c6f3541e00414806667c0a943eb10a6b6f": _entry(
        {
            "catalogSlug": "jolts-quits-rate-august-2026",
            "country": "US",
            "dataPointId": "bls.jolts.quits_rate.2026-08.first_print",
            "period": "2026-08",
            "series": "bls.jolts.quits_rate",
            "sourceBinding": {
                "adapter": "generic-url",
                "allowedHosts": ["www.bls.gov"],
                "expectedReleaseWindow": {"end": "2026-10-05", "start": "2026-09-27"},
                "field": "bls.jolts.quits_rate",
                "releasePolicy": "first_print",
                "sourceSeriesId": "bls.jolts.quits_rate",
                "sourceUrl": "https://www.bls.gov/news.release/jolts.t04.htm",
                "table": "U.S. Bureau of Labor Statistics Job Openings and Labor "
                "Turnover Survey Table 4",
                "transform": {"factor": 1, "operation": "multiply"},
            },
            "unit": "percent",
            "valueScale": 1,
        },
        "jolts_quits_rate",
        "thesis_target_registration_v3",
        {
            "branch": "codex/thesis-ledger-facts",
            "jsonlSha256": (
                "b0c29d7cb2aee323a5d30f8196eb59f62aa396066070131c5048740659d5e241"
            ),
            "lineCount": 171,
            "repo": "PolicyEngine/chronicle",
            "sha": "661467ed79412edd8fda4be472f9f7faf98c924e",
        },
    ),
}


LEGACY_RELEASE_ALFRED_CONTRACTS: dict[str, dict[str, Any]] = {
    "7753f0f1a5d658edcefcd448d480f21171af349f95e6902b968abb25deb8d3b4": _entry(
        {
            "catalogSlug": "bls-ppi-final-demand-monthly-change-july-2026",
            "country": "US",
            "dataPointId": "bls.wp.WPSFD4.2026-07.first_print",
            "period": "2026-07",
            "series": "bls.ppi.final_demand_monthly_change",
            "sourceBinding": {
                "adapter": "alfred-fred",
                "allowedHosts": ["alfred.stlouisfed.org", "www.bls.gov"],
                "expectedReleaseWindow": {"end": "2026-08-19", "start": "2026-08-11"},
                "field": "PPIFIS",
                "releasePolicy": "first_print",
                "sourceSeriesId": "PPIFIS",
                "sourceUrl": (
                    "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=PPIFIS"
                ),
                "table": "Producer Price Index, final demand, seasonally adjusted",
                "transform": {"factor": 1, "operation": "multiply"},
            },
            "unit": "percent_growth",
            "valueScale": 1,
        },
        "alfred",
        "thesis_target_registration_v3",
        {
            "branch": "codex/thesis-ledger-facts",
            "jsonlSha256": (
                "f2e59e53ded8b13e2e62b1970867b87c91262382fd4c949a78052489c7c9f262"
            ),
            "lineCount": 156,
            "repo": "PolicyEngine/ledger",
            "sha": "37c3ac4b12c115f7f21261b1edbd7b4e0fa5e37d",
        },
        stem="bls.ppi.final_demand_monthly_change",
    ),
}


def _contract_differences(actual: Any, expected: Any, prefix: str = "") -> list[str]:
    if isinstance(actual, dict) and isinstance(expected, dict):
        differences: list[str] = []
        for key in sorted(set(actual) | set(expected)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in actual or key not in expected:
                differences.append(path)
            else:
                differences.extend(
                    _contract_differences(actual[key], expected[key], path)
                )
        return differences
    try:
        equal = canonical_bytes(actual) == canonical_bytes(expected)
    except (TypeError, ValueError):
        equal = False
    return [] if equal else [prefix or "contract"]


def legacy_release_contract_mismatches(
    registration: Mapping[str, Any], entry: Mapping[str, Any]
) -> list[str]:
    """Name every differing contract key, including missing and added keys.

    A hash match cannot authorize a changed contract. Conversely, a matching
    contract with an unreviewed hash cannot borrow this legacy exception.
    Numeric equality follows the same canonical JSON used by registrations;
    in particular, booleans cannot compare equal to numeric one or zero.
    """
    differences = _contract_differences(registration.get("contract"), entry["contract"])
    expected_hash = canonical_sha256(entry["hashPayload"])
    if registration.get("targetContentHash") != expected_hash:
        differences.append("targetContentHash")
    return differences
