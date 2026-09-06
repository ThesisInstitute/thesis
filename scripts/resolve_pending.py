#!/usr/bin/env python3
"""Resolve pending forecast cells whose official numbers have published.

Adapter-based: each adapter claims a family of targetFactRefs from the live
catalog's resolutionLinks, checks whether the official first print exists
yet, and emits a PolicyEngine-Ledger fact row (the JSONL schema the site's
build fetches and joins on source_record_id == targetFactRef). Appending a
row is what resolves a cell: the next site build scores it.

First adapters: DOL UI weekly claims (initial + continued, seasonally
adjusted), read from FRED's ICSA/CCSA series — the advance vintage named by
the cells' own resolver rules. BLS CES detailed-industry cells (the defense
batch) resolve straight from the BLS Public Data API v2 series their
resolutionSourceUrls bind, under a temporal first-print gate and runtime
anchor verification (see BLS_API_ADAPTERS).

Aging/disability batch (2026-08-23): BLS CPS series (no preliminary
footnote; latest-month gate), CES home health care, LAUS Colorado (BLS API);
the VA VBA Monday Morning Workload Report workbook (VA_MMWR_ADAPTERS,
Last-Modified first-posting gate); SSA SSI Monthly Statistics / Monthly
Statistical Snapshot editions and the OHO workload XML
(SSA_OFFICIAL_ADAPTERS) through a declared headless-browser transport
(scripts/official_browser_fetch.py) with Wayback corroboration, because
ssa.gov refuses every non-browser client. See docs/anchor-verifications.md.

Usage:
    python3 scripts/resolve_pending.py [--dry-run]
        [--ledger-repo PolicyEngine/chronicle]
        [--ledger-branch codex/thesis-ledger-facts]
        [--ledger-path ledger/official_observations.jsonl]

Requires `gh` auth with write access to the ledger repo unless --dry-run.
Idempotent: refs already present in the ledger are skipped.
"""

from __future__ import annotations

# Shared parsers also work when invoked as an absolute checkout script.
import sys as _bootstrap_sys
from pathlib import Path as _BootstrapPath

_bootstrap_sys.path.insert(0, str(_BootstrapPath(__file__).resolve().parent))
_bootstrap_sys.path.insert(0, str(_BootstrapPath(__file__).resolve().parents[1]))

from thesis_core.adapters.parsers import (  # noqa: E402, F401 - legacy re-exports
    BEA_ITABLE_DATA_URL,
    BEA_ITABLE_PAGE_URL,
    BEA_ITA_ITABLE_PAGE_URL,
    BEA_RELEASE_ADAPTERS,
    BEA_RELEASE_ALLOWED_HOSTS,
    BEA_RELEASE_BINDING_DERIVED_KEYS,
    BEA_RELEASE_BINDING_TEMPLATE_KEYS,
    BEA_RELEASE_REQUIRED_HOSTS,
    INTL_BINDING_KEYS,
    _ABS_UR_SPEC,
    _STATCAN_CPI_SPEC,
    _bea_cell_value,
    _bea_quarter,
    _bea_release_title,
    _bea_row_label,
    _install_intl_binding,
    abs_series_from_payload,
    bea_advance_release_url,
    bea_itable_request_body,
    bea_itable_value,
    bea_release_binding_matches_spec,
    bea_release_binding_template,
    bea_release_page_refusal,
    bea_release_snapshot_envelope,
    intl_binding_mismatches,
    intl_binding_template,
    intl_transformed_value,
    normalize_sdmx_period,
    prior_period_date,
    statcan_series_from_payload,
)

import argparse
import base64
import copy
import csv
import datetime as dt
import gzip
import hashlib
import html.parser as html_parser
import http.client
import io
import json
import math
import os
import pathlib
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import ssa_official_pages
import va_mmwr
import verify_records_attestations as records_provenance
from canonical_json import canonical_bytes, canonical_sha256
from ledger_release_chain import (
    DEFAULT_CLOCK_SKEW_SECONDS,
    LEDGER_RELATIVE,
    MANIFEST_RELATIVE,
    PREFIX_RELATIVE,
    SCHEMA_VERSION,
    ChainVerification,
    jsonl_line_offsets,
    manifest_filename,
    producer_signature_path_for_manifest,
    receipt_paths_for_manifest,
    sha256_bytes,
    validate_manifest_schema,
    verify_producer_signature_bytes,
    verify_release_chain,
)
from pin_ledger import PinError, _validate_catalog_binding
from register_targets import (
    LEGACY_BOUNDED_CONDITIONAL_IDS,
    RegistrationError,
    registration_content_hash,
)
from sba_loan_performance import (
    CHARGE_OFF_AMOUNT_SERIES,
    CHARGE_OFF_RATE_SERIES,
    COMPLETION_COMPLETED,
    COMPLETION_PARTIAL,
    POST_CHARGE_OFF_RECOVERY_SERIES,
    SBA_REPORT_SPECS,
    SbaLoanPerformanceCell,
    parse_sba_loan_performance_pdf,
)
from sba_loan_performance import (
    LAYOUT_REFUSAL as SBA_LAYOUT_REFUSAL,
)
from sba_loan_performance import (
    PARSER_REFUSAL as SBA_PARSER_REFUSAL,
)
from sba_loan_performance import (
    PARTIAL_REFUSAL as SBA_PARTIAL_REFUSAL,
)
from thesis_log_client import load_thesis_log
from verify_custody import CustodyError, verify_run
from witnessed_timeline import TimelineError, extract_timeline

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOG_URL = "https://app.thesisinstitute.org/log.json"
# ALFRED with a vintage date pins the ADVANCE print (what the resolver rules
# name); plain FRED would silently hand back revised values on backfills.
FRED_CSV = (
    "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
    "?id={series}&vintage_date={vintage}"
)

MAX_TIMESTAMP_TOKEN_BYTES = 1024 * 1024
DEFAULT_TIMESTAMP_TIMEOUT_SECONDS = 45.0
PRODUCER_SIGNING_KEY_ENV = "LEDGER_PRODUCER_SIGNING_KEY"

SBA_CUSTODY_ABSENT = "SBA CUSTODY ABSENT (refusing):"
SBA_CUSTODY_UNWITNESSED = "SBA CUSTODY UNWITNESSED (refusing):"
SBA_CUSTODY_UNATTESTED = "SBA CUSTODY UNATTESTED (refusing):"
SBA_CUSTODY_INVALID = "SBA CUSTODY INVALID (refusing):"
SBA_EARLIEST_CAPTURE_AMBIGUOUS = "SBA EARLIEST CAPTURE AMBIGUOUS (refusing):"
SBA_WITNESS_SCHEMA = "thesis_sba_pdf_witness_run_v1"
SBA_WITNESS_RUN_MODE = "sba_pdf_witness"
SBA_WITNESS_WORKFLOW = ".github/workflows/witness-sba-pdf.yml"
SBA_PARSER_CONTRACT = "scripts/sba_loan_performance.py:SBA_REPORT_SPECS:v3"
SBA_ENTRY_URL = (
    "https://www.sba.gov/document/"
    "report-small-business-administration-loan-program-performance"
)
# The registration binding's sourceUrl doubles as the resolve-by-bound
# ANNOUNCEMENT page, which the attested lane fetches through the
# no-redirect announcement MCP. www.sba.gov 302-redirects this document
# to legacy.sba.gov, so the binding names the redirect-free page; the
# witness capture keeps entering at SBA_ENTRY_URL and records the
# redirect chain as evidence.
SBA_ANNOUNCEMENT_URL = (
    "https://legacy.sba.gov/document/"
    "report-small-business-administration-loan-program-performance"
)
SBA_BINDING_ADAPTER = "sba-loan-program-performance-pdf"
SBA_ARCHIVE_SERIES_ID = "sba-loan-program-performance"
SBA_BINDING_TEMPLATE_KEYS = {
    "adapter",
    "sourceUrl",
    "sourceSeriesId",
    "field",
    "table",
    "transform",
    "releasePolicy",
}
SBA_BINDING_DERIVED_KEYS = {"allowedHosts", "expectedReleaseWindow"}

SBA_PDF_ADAPTERS: dict[str, dict[str, Any]] = {
    CHARGE_OFF_AMOUNT_SERIES: {
        "series_id": CHARGE_OFF_AMOUNT_SERIES,
        "label": "SBA Disaster loan-program charge-off amount",
        "unit": "usd",
        "source_name": "sba_loan_program_performance",
        "source_table": SBA_REPORT_SPECS[CHARGE_OFF_AMOUNT_SERIES].title,
        "field": "Disaster / Disaster",
        "valid_range": (0, math.inf),
    },
    CHARGE_OFF_RATE_SERIES: {
        "series_id": CHARGE_OFF_RATE_SERIES,
        "label": "SBA Disaster loan-program charge-off rate / UPB",
        "unit": "percent",
        "source_name": "sba_loan_program_performance",
        "source_table": SBA_REPORT_SPECS[CHARGE_OFF_RATE_SERIES].title,
        "field": "Disaster / Disaster",
        "valid_range": (0, 100),
    },
    POST_CHARGE_OFF_RECOVERY_SERIES: {
        "series_id": POST_CHARGE_OFF_RECOVERY_SERIES,
        "label": "SBA Disaster post-charge-off recovery amount",
        "unit": "usd",
        "source_name": "sba_loan_program_performance",
        "source_table": SBA_REPORT_SPECS[POST_CHARGE_OFF_RECOVERY_SERIES].title,
        "field": "Disaster / Disaster",
        "valid_range": (0, math.inf),
    },
}


@dataclass(frozen=True)
class SbaPdfResolution:
    value: int | float
    unit: str
    raw_bundle: bytes
    run_directory: str
    source_url: str
    member_path: str
    provenance: dict[str, Any]


@dataclass(frozen=True)
class _SbaPdfCandidate:
    run_dir: pathlib.Path
    run_directory: str
    manifest: dict[str, Any]
    custody_root_sha256: str
    proof: dict[str, Any] | None
    partial_only: bool
    introducing_commit: str | None = None
    attestation_signer: str | None = None


TSA_ENDPOINTS = {
    "freetsa": "https://freetsa.org/tsr",
    # DigiCert's documented RFC 3161 endpoint is plain HTTP (its TLS endpoint
    # does not answer timestamp queries). The signed token is verified against
    # the separately pinned trust anchor before the proposal branch exists.
    "digicert": "http://timestamp.digicert.com",
}
TimestampRequester = Callable[[str, bytes, float], bytes]


class LedgerProposalError(RuntimeError):
    """A witnessed ledger proposal could not be constructed or published."""


@dataclass(frozen=True)
class RepositoryTree:
    tree_sha: str
    files: dict[str, bytes]
    modes: dict[str, str]
    blob_shas: dict[str, str]


def _validate_timestamp_timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LedgerProposalError("timeout_seconds must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise LedgerProposalError("timeout_seconds must be a finite positive number")
    return result


def request_timestamp(endpoint: str, query: bytes, timeout_seconds: float) -> bytes:
    """POST one DER RFC 3161 query and return a size-bounded response."""

    if endpoint not in TSA_ENDPOINTS.values():
        raise LedgerProposalError(f"refusing unapproved TSA endpoint: {endpoint!r}")
    if type(query) is not bytes or not query:
        raise LedgerProposalError("RFC 3161 query must be non-empty bytes")
    timeout = _validate_timestamp_timeout(timeout_seconds)
    request = urllib.request.Request(
        endpoint,
        data=query,
        headers={
            "Content-Type": "application/timestamp-query",
            "User-Agent": "Thesis-Ledger-Release-Witness/1",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        token = response.read(MAX_TIMESTAMP_TOKEN_BYTES + 1)
    if not token:
        raise LedgerProposalError(f"TSA returned an empty response: {endpoint}")
    if len(token) > MAX_TIMESTAMP_TOKEN_BYTES:
        raise LedgerProposalError(
            f"TSA response exceeds the one-megabyte limit: {endpoint}"
        )
    return token


def _build_timestamp_query(manifest: bytes, timeout_seconds: float) -> bytes:
    """Build the DER query whose SHA-256 imprint covers exact manifest bytes."""

    with tempfile.TemporaryDirectory(prefix="thesis-release-query-") as name:
        temporary = pathlib.Path(name)
        manifest_path = temporary / "manifest.json"
        query_path = temporary / "request.tsq"
        manifest_path.write_bytes(manifest)
        try:
            completed = subprocess.run(
                [
                    "openssl",
                    "ts",
                    "-query",
                    "-config",
                    "/dev/null",
                    "-data",
                    str(manifest_path),
                    "-sha256",
                    "-cert",
                    "-out",
                    str(query_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env={**os.environ, "LC_ALL": "C", "OPENSSL_CONF": "/dev/null"},
            )
        except FileNotFoundError as exc:
            raise LedgerProposalError(
                "openssl is required to construct the RFC 3161 query"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LedgerProposalError(
                "OpenSSL timestamp-query construction timed out"
            ) from exc
        if completed.returncode != 0:
            diagnostic = (completed.stderr or completed.stdout).strip()
            raise LedgerProposalError(
                "OpenSSL timestamp-query construction failed: "
                f"{diagnostic[-1000:] or 'no diagnostic'}"
            )
        try:
            query = query_path.read_bytes()
        except FileNotFoundError as exc:
            raise LedgerProposalError(
                "OpenSSL did not produce the RFC 3161 query"
            ) from exc
    if not query or len(query) > MAX_TIMESTAMP_TOKEN_BYTES:
        raise LedgerProposalError("OpenSSL produced an invalid-sized RFC 3161 query")
    return query


def _sign_release_manifest(
    manifest: bytes,
    signing_key: str | None,
    timeout_seconds: float,
) -> bytes:
    """Materialize the PEM for OpenSSL without parsing or logging its contents."""

    if type(manifest) is not bytes:
        raise LedgerProposalError("producer-signed manifest payload must be bytes")
    if type(signing_key) is not str or not signing_key.strip():
        raise LedgerProposalError(
            f"{PRODUCER_SIGNING_KEY_ENV} must contain a non-empty PEM private key"
        )
    timeout = _validate_timestamp_timeout(timeout_seconds)

    with tempfile.TemporaryDirectory(prefix="thesis-release-signature-") as name:
        temporary = pathlib.Path(name)
        # TemporaryDirectory is private by default; make that property explicit
        # before materializing secret bytes and use exclusive creation below.
        temporary.chmod(0o700)
        key_path = temporary / "producer-private.pem"
        manifest_path = temporary / "manifest.json"
        signature_path = temporary / "producer.sig"
        descriptor = -1
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(key_path, flags, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                descriptor = -1
                stream.write(signing_key)

            manifest_path.write_bytes(manifest)
            environment = os.environ.copy()
            environment.pop(PRODUCER_SIGNING_KEY_ENV, None)
            environment.update({"LC_ALL": "C", "OPENSSL_CONF": "/dev/null"})
            try:
                completed = subprocess.run(
                    [
                        "openssl",
                        "pkeyutl",
                        "-sign",
                        "-inkey",
                        str(key_path),
                        "-rawin",
                        "-in",
                        str(manifest_path),
                        "-out",
                        str(signature_path),
                    ],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout,
                    env=environment,
                )
            except FileNotFoundError as exc:
                raise LedgerProposalError(
                    "OpenSSL 3 is required for Ed25519 producer signing"
                ) from exc
            except subprocess.TimeoutExpired:
                raise LedgerProposalError(
                    "OpenSSL producer signing timed out"
                ) from None
            if completed.returncode != 0:
                raise LedgerProposalError(
                    "OpenSSL producer signing failed "
                    f"with exit code {completed.returncode}"
                )
            try:
                signature = signature_path.read_bytes()
            except FileNotFoundError as exc:
                raise LedgerProposalError(
                    "OpenSSL producer signing did not emit a signature"
                ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            # Do not rely only on TemporaryDirectory cleanup for key erasure:
            # unlink as soon as OpenSSL is done, including every failure path.
            try:
                key_path.unlink()
            except FileNotFoundError:
                pass
    if len(signature) != 64:
        raise LedgerProposalError(
            "OpenSSL producer signing did not emit a 64-byte raw Ed25519 signature"
        )
    return signature


def _request_timestamp_receipts(
    query: bytes,
    *,
    requester: TimestampRequester,
    timeout_seconds: float,
) -> dict[str, bytes]:
    receipts: dict[str, bytes] = {}
    for tsa, endpoint in TSA_ENDPOINTS.items():
        try:
            token = requester(endpoint, query, timeout_seconds)
        except (
            http.client.HTTPException,
            OSError,
            LedgerProposalError,
            urllib.error.URLError,
        ) as exc:
            raise LedgerProposalError(f"{tsa} timestamp request failed: {exc}") from exc
        except Exception as exc:
            raise LedgerProposalError(f"{tsa} timestamp request failed: {exc}") from exc
        if type(token) is not bytes or not token:
            raise LedgerProposalError(f"{tsa} TSA must return non-empty bytes")
        if len(token) > MAX_TIMESTAMP_TOKEN_BYTES:
            raise LedgerProposalError(
                f"{tsa} TSA response exceeds the one-megabyte limit"
            )
        receipts[tsa] = token
    return receipts


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def fred_advance_value(
    series_id: str, week: str, vintage: str
) -> tuple[float | None, bytes | None, str, str]:
    """The series value for `week` as printed on `vintage` (advance print)."""
    url = FRED_CSV.format(series=series_id, vintage=vintage)
    retrieved_at = utc_now()
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            raw = r.read()
    except urllib.error.HTTPError:
        return None, None, url, retrieved_at
    text = raw.decode()
    for row in csv.DictReader(io.StringIO(text)):
        date = row.get("observation_date") or row.get("DATE")
        value = row.get(f"{series_id}_{vintage.replace('-', '')}") or row.get(series_id)
        if date == week and value not in (None, "", "."):
            return float(value), raw, url, retrieved_at
    return None, raw, url, retrieved_at


def parse_fred_vintage_csv(
    raw: bytes, series_id: str, vintage: str
) -> dict[str, float]:
    """Parse a vintage CSV response, including date-constrained fixtures."""
    rows: dict[str, float] = {}
    for row in csv.DictReader(io.StringIO(raw.decode())):
        date = row.get("observation_date") or row.get("DATE")
        value = row.get(f"{series_id}_{vintage.replace('-', '')}") or row.get(series_id)
        if date and value not in (None, "", "."):
            rows[date] = float(value)
    return rows


def fred_vintage_series(
    series_id: str, vintage: str
) -> tuple[dict[str, float], bytes | None, str, str]:
    """Every dated value of `series_id` as printed on `vintage`."""
    url = FRED_CSV.format(series=series_id, vintage=vintage)
    retrieved_at = utc_now()
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            raw = r.read()
    except urllib.error.HTTPError:
        return {}, None, url, retrieved_at
    rows = parse_fred_vintage_csv(raw, series_id, vintage)
    return rows, raw, url, retrieved_at


# Generic ALFRED adapters for monthly/quarterly first prints, one entry per
# dataPointId series stem. Every mapping was verified against the cell's own
# published history at each anchor's FIRST-PRINT vintage before being added
# (2026-07-10; e.g. all six BEA April anchors matched to the 0.1 at the
# 2026-06-05 vintage) — a candidate series that cannot reproduce the cell's
# recorded history must never resolve it. Transforms:
#   level         — the period's value as printed
#   mom_diff      — period minus prior period, same vintage (payroll change
#                   as BLS headlines it)
#   pct_change_1d — percent change from prior period, one decimal (how BEA
#                   headlines PCE price changes)
ALFRED_ADAPTERS: dict[str, dict[str, Any]] = {
    "bls.ces.total_nonfarm_payroll_change": {
        "fred": "PAYEMS",
        "transform": "mom_diff",
        "unit": "thousands",
        "label": "US nonfarm payroll change",
        "source_name": "bls_ces",
        "source_table": "Employment Situation, Table B-1 (total nonfarm)",
        "concept_authority": "bls",
    },
    "bls.cps.unemployment_rate": {
        "fred": "UNRATE",
        "transform": "level",
        "unit": "percent",
        "label": "US unemployment rate",
        "source_name": "bls_cps",
        "source_table": "Employment Situation, Table A-1",
        "concept_authority": "bls",
    },
    "bls.jolts.job_openings_total": {
        "fred": "JTSJOL",
        "transform": "level",
        "unit": "thousands",
        "label": "US job openings, total nonfarm",
        "source_name": "bls_jolts",
        "source_table": "JOLTS news release, Table 1",
        "concept_authority": "bls",
    },
    "bls.jolts.job_openings": {
        "fred": "JTSJOL",
        "transform": "level",
        "unit": "millions",
        "scale": 0.001,
        "round": 3,
        "label": "US job openings, total nonfarm",
        "source_name": "bls_jolts",
        "source_table": "JOLTS news release, Table 1",
        "concept_authority": "bls",
    },
    "bls.cpi.u.core_mom": {
        "fred": "CPILFESL",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US core CPI-U, monthly change",
        "source_name": "bls_cpi",
        "source_table": "Consumer Price Index news release",
        "concept_authority": "bls",
    },
    "bls.cpi.u.headline_mom": {
        "fred": "CPIAUCSL",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US CPI-U all items, monthly change",
        "source_name": "bls_cpi",
        "source_table": "Consumer Price Index news release",
        "concept_authority": "bls",
    },
    "bea.pce.core_mom": {
        "fred": "PCEPILFE",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US core PCE price index, monthly change",
        "source_name": "bea",
        "source_table": "Personal Income and Outlays",
        "concept_authority": "bea",
    },
    "us.bea.core_pce.mom_sa": {
        "fred": "PCEPILFE",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US core PCE price index, monthly change",
        "source_name": "bea",
        "source_table": "Personal Income and Outlays",
        "concept_authority": "bea",
    },
    "bea.pce_price_index.monthly_change": {
        "fred": "PCEPI",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US PCE price index, monthly change",
        "source_name": "bea",
        "source_table": "Personal Income and Outlays",
        "concept_authority": "bea",
    },
    "bea.real_gdp.saar": {
        "fred": "A191RL1Q225SBEA",
        "transform": "level",
        "unit": "percent_growth",
        "label": "US real GDP, SAAR percent change",
        "source_name": "bea",
        "source_table": "Gross Domestic Product news release",
        "concept_authority": "bea",
    },
    "bea.disposable_personal_income.level": {
        "fred": "DSPI",
        "transform": "level",
        "unit": "usd_billions",
        "label": "US disposable personal income, SAAR level",
        "source_name": "bea",
        "source_table": "Personal Income and Outlays, Table 1",
        "concept_authority": "bea",
    },
    "bea.government_social_benefits.level": {
        "fred": "A063RC1",
        "transform": "level",
        "unit": "usd_billions",
        "label": "US government social benefits to persons, SAAR level",
        "source_name": "bea",
        "source_table": "Personal Income and Outlays, Table 1",
        "concept_authority": "bea",
    },
    "bea.government_social_benefits.social_security": {
        "fred": "W823RC1",
        "transform": "level",
        "unit": "usd_billions",
        "label": "US social security benefits, SAAR level",
        "source_name": "bea",
        "source_table": "Personal Income and Outlays, Table 1",
        "concept_authority": "bea",
    },
    "bea.government_social_benefits.medicare": {
        "fred": "W824RC1",
        "transform": "level",
        "unit": "usd_billions",
        "label": "US Medicare benefits, SAAR level",
        "source_name": "bea",
        "source_table": "Personal Income and Outlays, Table 1",
        "concept_authority": "bea",
    },
    "bea.government_social_benefits.medicaid": {
        "fred": "W729RC1",
        "transform": "level",
        "unit": "usd_billions",
        "label": "US Medicaid benefits, SAAR level",
        "source_name": "bea",
        "source_table": "Personal Income and Outlays, Table 1",
        "concept_authority": "bea",
    },
    "bea.wages_and_salaries.level": {
        "fred": "A576RC1",
        "transform": "level",
        "unit": "usd_billions",
        "label": "US wages and salaries, SAAR level",
        "source_name": "bea",
        "source_table": "Personal Income and Outlays, Table 1",
        "concept_authority": "bea",
    },
    "bea.personal_current_taxes.level": {
        "fred": "W055RC1",
        "transform": "level",
        "unit": "usd_billions",
        "label": "US personal current taxes, SAAR level",
        "source_name": "bea",
        "source_table": "Personal Income and Outlays, Table 1",
        "concept_authority": "bea",
    },
    # US docket expansion (drafted 2026-07-24, anchor-verified 2026-07-25
    # through the alfredgraph vintage transport — three anchors per series,
    # recorded in docs/anchor-verifications.md; six carry one flagged
    # late-vintage anchor).
    "fed.g17.industrial_production.total_index_mom": {
        "fred": "INDPRO",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US industrial production, monthly change",
        "source_name": "federal_reserve_g17",
        "source_table": (
            "G.17 Industrial Production and Capacity Utilization, "
            "monthly seasonally adjusted"
        ),
        "concept_authority": "federal_reserve",
    },
    "fed.g17.manufacturing_production_mom": {
        "fred": "IPMAN",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US manufacturing industrial production, monthly change",
        "source_name": "federal_reserve_g17",
        "source_table": (
            "G.17 Industrial Production and Capacity Utilization, "
            "monthly seasonally adjusted"
        ),
        "concept_authority": "federal_reserve",
    },
    "fed.g17.capacity_utilization.total_industry": {
        "fred": "TCU",
        "transform": "level",
        "unit": "percent",
        "round": 1,
        "label": "US total industry capacity utilization",
        "source_name": "federal_reserve_g17",
        "source_table": (
            "G.17 Industrial Production and Capacity Utilization, "
            "monthly seasonally adjusted"
        ),
        "concept_authority": "federal_reserve",
    },
    "fed.g17.capacity_utilization.manufacturing": {
        "fred": "MCUMFN",
        "transform": "level",
        "unit": "percent",
        "round": 1,
        "label": "US manufacturing capacity utilization",
        "source_name": "federal_reserve_g17",
        "source_table": (
            "G.17 Industrial Production and Capacity Utilization, "
            "monthly seasonally adjusted"
        ),
        "concept_authority": "federal_reserve",
    },
    "census.housing_starts.saar": {
        "fred": "HOUST",
        "transform": "level",
        "unit": "millions",
        "scale": 0.001,
        "round": 3,
        "label": "US housing starts, seasonally adjusted annual rate",
        "source_name": "census_housing",
        "source_table": (
            "New Residential Construction, seasonally adjusted annual rates"
        ),
        "concept_authority": "census",
    },
    "census.housing.permits_saar": {
        "fred": "PERMIT",
        "transform": "level",
        "unit": "thousands",
        "round": 0,
        "label": "US building permits, seasonally adjusted annual rate",
        "source_name": "census_housing",
        "source_table": (
            "New Residential Construction, seasonally adjusted annual rates"
        ),
        "concept_authority": "census",
    },
    "census.housing.completions_saar": {
        "fred": "COMPUTSA",
        "transform": "level",
        "unit": "thousands",
        "round": 0,
        "label": "US housing completions, seasonally adjusted annual rate",
        "source_name": "census_housing",
        "source_table": (
            "New Residential Construction, seasonally adjusted annual rates"
        ),
        "concept_authority": "census",
    },
    "census.new_residential_sales.new_single_family_houses_sold_saar": {
        "fred": "HSN1F",
        "transform": "level",
        "unit": "thousands",
        "round": 0,
        "label": "US new single-family home sales, seasonally adjusted annual rate",
        "source_name": "census_new_home_sales",
        "source_table": "New Residential Sales, Table 1",
        "concept_authority": "census",
    },
    "census.m3.durable_goods_new_orders_mom": {
        "fred": "DGORDER",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US durable goods new orders, monthly change",
        "source_name": "census_m3",
        "source_table": (
            "Advance Report on Durable Goods Manufacturers' Shipments, "
            "Inventories, and Orders"
        ),
        "concept_authority": "census",
    },
    "census.m3.durable_goods_shipments_mom": {
        "fred": "AMDMVS",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US durable goods shipments, monthly change",
        "source_name": "census_m3",
        "source_table": (
            "Advance Report on Durable Goods Manufacturers' Shipments, "
            "Inventories, and Orders"
        ),
        "concept_authority": "census",
    },
    "census.construction_spending.total_mom": {
        "fred": "TTLCONS",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US total construction spending, monthly change",
        "source_name": "census_construction",
        "source_table": "Value of Construction Put in Place Survey",
        "concept_authority": "census",
    },
    "census.mtis.total_business_inventories_level": {
        "fred": "BUSINV",
        "transform": "level",
        "unit": "usd_billions",
        "scale": 0.001,
        "round": 1,
        "label": "US manufacturing and trade inventories",
        "source_name": "census_business_inventories",
        "source_table": "Manufacturing and Trade Inventories and Sales",
        "concept_authority": "census",
    },
    "bea.trade.goods_services_deficit": {
        "fred": "BOPGSTB",
        "transform": "level",
        "unit": "usd_billions",
        "scale": -0.001,
        "round": 1,
        "label": "US international trade deficit in goods and services",
        "source_name": "bea_census_trade",
        "source_table": ("U.S. International Trade in Goods and Services, Exhibit 1"),
        "concept_authority": "bea",
    },
    "bls.import_price_index.all_imports_mom": {
        "fred": "IR",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US all-commodities import prices, monthly change",
        "source_name": "bls_import_export_prices",
        "source_table": "U.S. Import Price Indexes, Table 1",
        "concept_authority": "bls",
    },
    "bls.export_prices.all_commodities_mom": {
        "fred": "IQ",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US all-commodities export prices, monthly change",
        "source_name": "bls_import_export_prices",
        "source_table": "U.S. Export Price Indexes, Table 2",
        "concept_authority": "bls",
    },
    "bls.ppi.final_demand_monthly_change": {
        "fred": "PPIFIS",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US PPI final demand, monthly change",
        "source_name": "bls_ppi",
        "source_table": "Producer Price Index, final demand, seasonally adjusted",
        "concept_authority": "bls",
    },
    "bls.eci.total_compensation_private_industry_qoq": {
        "fred": "ECICOM",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": (
            "US employment cost index, private-industry total compensation, "
            "quarterly change"
        ),
        "source_name": "bls_eci",
        "source_table": "Employment Cost Index, Table 1",
        "concept_authority": "bls",
    },
    "bls.eci.private_wages_salaries_qoq": {
        "fred": "ECIWAG",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": (
            "US employment cost index, private wages and salaries, quarterly change"
        ),
        "source_name": "bls_eci",
        "source_table": "Employment Cost Index, Table 2",
        "concept_authority": "bls",
    },
    "bls.productivity.nonfarm_unit_labor_costs_qoq_prelim": {
        "fred": "PRS85006112",
        "transform": "level",
        "unit": "percent_growth",
        "round": 1,
        "label": (
            "US nonfarm business unit labor costs, quarterly change at "
            "seasonally adjusted annual rate"
        ),
        "source_name": "bls_productivity",
        "source_table": "Productivity and Costs, nonfarm business sector",
        "concept_authority": "bls",
    },
    "fed.g19.consumer_credit_total_annual_rate": {
        "fred": "TOTALSLAR",
        "transform": "level",
        "unit": "percent_growth",
        "round": 1,
        "label": "US total consumer credit, annual rate of change",
        "source_name": "federal_reserve_g19",
        "source_table": ("G.19 Consumer Credit, outstanding, seasonally adjusted"),
        "concept_authority": "federal_reserve",
    },
    "fed.g19.consumer_credit_revolving_annual_rate": {
        "fred": "REVOLSLAR",
        "transform": "level",
        "unit": "percent_growth",
        "round": 1,
        "label": "US revolving consumer credit, annual rate of change",
        "source_name": "federal_reserve_g19",
        "source_table": ("G.19 Consumer Credit, outstanding, seasonally adjusted"),
        "concept_authority": "federal_reserve",
    },
    "fed.g19.consumer_credit_nonrevolving_annual_rate": {
        "fred": "NONREVSLAR",
        "transform": "level",
        "unit": "percent_growth",
        "round": 1,
        "label": "US nonrevolving consumer credit, annual rate of change",
        "source_name": "federal_reserve_g19",
        "source_table": ("G.19 Consumer Credit, outstanding, seasonally adjusted"),
        "concept_authority": "federal_reserve",
    },
    "bls.cpi.shelter_mom": {
        "fred": "CUSR0000SAH1",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US CPI shelter, monthly change",
        "source_name": "bls_cpi",
        "source_table": (
            "Consumer Price Index, U.S. city average, monthly seasonally adjusted"
        ),
        "concept_authority": "bls",
    },
    "bls.cpi.rent_primary_residence_mom": {
        "fred": "CUSR0000SEHA",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US CPI rent of primary residence, monthly change",
        "source_name": "bls_cpi",
        "source_table": (
            "Consumer Price Index, U.S. city average, monthly seasonally adjusted"
        ),
        "concept_authority": "bls",
    },
    "bls.cpi.owners_equivalent_rent_mom": {
        "fred": "CUSR0000SEHC",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US CPI owners' equivalent rent, monthly change",
        "source_name": "bls_cpi",
        "source_table": (
            "Consumer Price Index, U.S. city average, monthly seasonally adjusted"
        ),
        "concept_authority": "bls",
    },
    "bls.cpi.services_less_energy_mom": {
        "fred": "CUSR0000SASLE",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US CPI services less energy services, monthly change",
        "source_name": "bls_cpi",
        "source_table": (
            "Consumer Price Index, U.S. city average, monthly seasonally adjusted"
        ),
        "concept_authority": "bls",
    },
    "bls.cpi.services_less_rent_shelter_mom": {
        "fred": "CUSR0000SASL2RS",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US CPI services less rent of shelter, monthly change",
        "source_name": "bls_cpi",
        "source_table": (
            "Consumer Price Index, U.S. city average, monthly seasonally adjusted"
        ),
        "concept_authority": "bls",
    },
    "bls.jolts.hires_rate": {
        "fred": "JTSHIR",
        "transform": "level",
        "unit": "percent",
        "round": 1,
        "label": "US hires rate, total nonfarm",
        "source_name": "bls_jolts",
        "source_table": "JOLTS news release, Table 1",
        "concept_authority": "bls",
    },
    "bls.ces.average_hourly_earnings_private": {
        "fred": "CES0500000003",
        "transform": "pct_change_1d",
        "unit": "percent_growth",
        "label": "US average hourly earnings, monthly change",
        "source_name": "bls_ces",
        "source_table": "Employment Situation, Table B-3",
        "concept_authority": "bls",
    },
    "bls.lns11300000": {
        "fred": "CIVPART",
        "transform": "level",
        "unit": "percent",
        "round": 1,
        "label": "US labor force participation rate",
        "source_name": "bls_cps",
        "source_table": "Employment Situation, Table A-1",
        "concept_authority": "bls",
    },
    "bls.cps.u6_underemployment_rate": {
        "fred": "U6RATE",
        "transform": "level",
        "unit": "percent",
        "round": 1,
        "label": "US U-6 underemployment rate",
        "source_name": "bls_cps",
        "source_table": "Employment Situation, Table A-15",
        "concept_authority": "bls",
    },
}

# These ALFRED series are evidence mirrors only. They preserve dated
# historical vintages for forecast history and anchor tests, but they are not
# eligible runtime resolvers: current outcomes for both series come from the
# official BEA GDP advance release and its NIPA table below.
ALFRED_HISTORY_MIRRORS: dict[str, dict[str, Any]] = {
    "bea.private_nonresidential_fixed_investment": {
        "fred": "PNFI",
        "transform": "level",
        "unit": "usd_billions",
        "label": "US private nonresidential fixed investment, nominal SAAR",
        "source_name": "bea",
        "source_table": (
            "Gross Domestic Product, Table 5.3.5 (private fixed investment by type)"
        ),
        "concept_authority": "bea",
    },
    "bea.research_and_development_fixed_investment": {
        "fred": "Y006RC1Q027SBEA",
        "transform": "level",
        "unit": "usd_billions",
        "label": ("US private research and development fixed investment, nominal SAAR"),
        "source_name": "bea",
        "source_table": (
            "Gross Domestic Product, Table 5.6.5 (private R&D fixed investment)"
        ),
        "concept_authority": "bea",
    },
}
















def bea_ita_release_url(period: str, release_day: dt.date) -> str:
    """Exact official ITA/IIP release-page URL for a quarterly period.

    Q1 and Q4 suffixes come from the combined 2026 notices. The ordinary
    quarter suffix comes from BEA's canonical Q2 2025 ITA notice; Q1 2026
    authenticates the new combined stem and names the next combined Q2 title.
    A future alias is accepted only when the final URL is exact, so it fails
    closed until BEA publishes that exact URL:
    https://www.bea.gov/news/2026/us-international-transactions-and-investment-position-1st-quarter-2026-and-annual-update
    https://www.bea.gov/news/2026/us-international-transactions-and-investment-position-4th-quarter-and-year-2025
    https://www.bea.gov/news/2025/us-international-transactions-2nd-quarter-2025
    """

    year, quarter = _bea_quarter(period)
    ordinal = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}[quarter]
    suffix = f"{ordinal}-quarter-{year}"
    if quarter == 1:
        suffix += "-and-annual-update"
    elif quarter == 4:
        suffix = f"{ordinal}-quarter-and-year-{year}"
    return (
        f"https://www.bea.gov/news/{release_day.year}/"
        f"us-international-transactions-and-investment-position-{suffix}"
    )


def _bea_ita_release_title(period: str) -> str:
    year, quarter = _bea_quarter(period)
    ordinal = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}[quarter]
    title = (
        "U.S. International Transactions and Investment Position, "
        f"{ordinal} Quarter {year}"
    )
    if quarter == 1:
        title += " and Annual Update"
    elif quarter == 4:
        title = (
            "U.S. International Transactions and Investment Position, "
            f"{ordinal} Quarter and Year {year}"
        )
    return title


def bea_ita_release_page_refusal(
    raw: bytes, period: str, release_day: dt.date
) -> str | None:
    """Authenticate an ITA/IIP notice's title and exact embargo line.

    The expected 8:30 a.m. Eastern shape is taken from BEA's Q1 2026 notice:
    https://www.bea.gov/news/2026/us-international-transactions-and-investment-position-1st-quarter-2026-and-annual-update
    """

    try:
        page = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "ITA release response is not UTF-8 HTML"
    page = re.sub(r"<script\b[^>]*>.*?</script>", " ", page, flags=re.I | re.S)
    page = re.sub(r"<style\b[^>]*>.*?</style>", " ", page, flags=re.I | re.S)
    visible = " ".join(unescape(re.sub(r"<[^>]+>", " ", page)).split())
    title = _bea_ita_release_title(period)
    if title not in visible:
        return f"ITA release page does not contain expected title {title!r}"
    embargo_local = dt.datetime(
        release_day.year,
        release_day.month,
        release_day.day,
        8,
        30,
        tzinfo=ZoneInfo("America/New_York"),
    )
    expected_embargo = (
        "EMBARGOED UNTIL RELEASE AT 8:30 a.m. "
        f"{embargo_local.tzname()}, {release_day.strftime('%A, %B')} "
        f"{release_day.day}, {release_day.year}"
    )
    if expected_embargo not in visible:
        return (
            "ITA release page does not contain exact registered embargo line "
            f"{expected_embargo!r}"
        )
    return None


def bea_ita_capture_timing_refusal(
    retrieved_at: Mapping[str, str], release_day: dt.date
) -> str | None:
    """Refuse any ITA source fetch started before BEA's embargo instant."""

    embargo_utc = dt.datetime(
        release_day.year,
        release_day.month,
        release_day.day,
        8,
        30,
        tzinfo=ZoneInfo("America/New_York"),
    ).astimezone(dt.timezone.utc)
    for label, timestamp in retrieved_at.items():
        try:
            captured = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            return f"ITA {label} fetch has invalid retrieval timestamp {timestamp!r}"
        if captured.tzinfo is None:
            return f"ITA {label} fetch has naive retrieval timestamp {timestamp!r}"
        if captured.astimezone(dt.timezone.utc) < embargo_utc:
            return (
                f"ITA {label} fetch started at {timestamp}, before embargo "
                f"{embargo_utc.isoformat().replace('+00:00', 'Z')}"
            )
    return None


def _bea_ita_response(raw: bytes) -> tuple[dict[str, Any] | None, str | None]:
    """Authenticate the GetStep envelope for BEA's official ITA iTable.

    This authenticates the returned application/step identity, not Product=1:
    GetStep does not echo Product and returns byte-identical table bytes for a
    live Product=5 request. Product custody is the sealed outbound request.

    https://apps.bea.gov/iTable/?ReqID=62&step=6&isuri=1&tablelist=62&product=1
    """

    try:
        response = json.loads(raw.decode("utf-8"))
        if isinstance(response, str):
            response = json.loads(response)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "ITA iTable response is not complete UTF-8 JSON"
    expected_identity = {
        "Id": 6206,
        "AppId": 62,
        "Number": 6,
        "Name": "Selected Table",
        "Description": "Table Display from IIP and ITA",
        "IsTable": 1,
    }
    if not isinstance(response, dict) or any(
        response.get(key) != expected for key, expected in expected_identity.items()
    ):
        return None, "ITA iTable response has the wrong application or step identity"
    return response, None


def _bea_ita_prompt_rows(
    response: Mapping[str, Any], name: str
) -> tuple[list[dict[str, Any]] | None, str | None]:
    prompts = response.get("Prompts")
    if not isinstance(prompts, list):
        return None, "ITA iTable response has no prompt list"
    matches = [
        prompt
        for prompt in prompts
        if isinstance(prompt, dict)
        and prompt.get("Name") == name
        and prompt.get("UIControl") == "ListMultiple"
    ]
    if len(matches) != 1:
        return None, f"expected one ITA {name} selector prompt, found {len(matches)}"
    try:
        prompt_data = json.loads(matches[0]["PromtData"])
        rows = prompt_data["Table"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return None, f"ITA {name} selector prompt is not parseable"
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return None, f"ITA {name} selector prompt is not a row list"
    if any(
        set(row) != {"ListKey", "ListDisplayValue"}
        or type(row["ListKey"]) is not int
        or row["ListKey"] < 0
        or type(row["ListDisplayValue"]) is not str
        or not row["ListDisplayValue"].strip()
        for row in rows
    ):
        return None, f"ITA {name} selector row has the wrong key/display schema"
    keys = [row["ListKey"] for row in rows]
    if len(keys) != len(set(keys)):
        return None, f"ITA {name} selector keys are not globally unique"
    return rows, None


def bea_ita_prompt_selection(
    raw: bytes, spec: Mapping[str, Any], period: str
) -> tuple[str | None, str | None]:
    """Derive the current year key and authenticate every selected prompt."""

    response, refusal = _bea_ita_response(raw)
    if refusal:
        return None, refusal
    assert response is not None
    year, _quarter = _bea_quarter(period)
    year_rows, refusal = _bea_ita_prompt_rows(response, "Filter_#1")
    if refusal:
        return None, refusal
    frequency_rows, refusal = _bea_ita_prompt_rows(response, "Filter_#2")
    if refusal:
        return None, refusal
    line_rows, refusal = _bea_ita_prompt_rows(response, "Filter_#3")
    if refusal:
        return None, refusal
    assert year_rows is not None
    assert frequency_rows is not None
    assert line_rows is not None

    year_matches = [
        row
        for row in year_rows
        if row["ListKey"] > 0 and row["ListDisplayValue"].strip() == str(year)
    ]
    if len(year_matches) != 1:
        return None, (
            f"expected one ITA prompt key for year {year}, found {len(year_matches)}"
        )
    year_key = year_matches[0]["ListKey"]
    frequency_key = int(spec["frequency_key"])
    frequency_label_matches = [
        row
        for row in frequency_rows
        if row["ListDisplayValue"].strip() == spec["frequency_label"]
    ]
    if (
        len(frequency_label_matches) != 1
        or frequency_label_matches[0]["ListKey"] != frequency_key
    ):
        return None, "ITA prompt catalog does not authenticate the QSA selector"
    line_key = int(spec["line_number"])
    line_label_matches = [
        row
        for row in line_rows
        if _bea_row_label(row["ListDisplayValue"])
        == f"{spec['line_number']} {spec['row_label']}"
    ]
    if len(line_label_matches) != 1 or line_label_matches[0]["ListKey"] != line_key:
        return None, (
            "ITA prompt catalog does not authenticate line 18 Personal transfers"
        )
    return str(year_key), None


def bea_ita_prompt_catalog_selection(
    raw: bytes, spec: Mapping[str, Any], period: str
) -> tuple[str | None, str | None]:
    """Authenticate the unfiltered prompt-catalog response and year key.

    BEA does not echo the request in GetStep responses, so prompt selectors
    alone cannot distinguish the 84,950-byte unfiltered catalog from the
    16,089-byte selected-table response.  Bind this archive role to the full
    Table 5.1 shape as well as to its selector metadata.
    """

    year_key, refusal = bea_ita_prompt_selection(raw, spec, period)
    if refusal:
        return None, refusal
    response, refusal = _bea_ita_response(raw)
    if refusal:
        return None, refusal
    assert response is not None
    table, refusal = _bea_ita_table(response, spec)
    if refusal:
        return None, refusal
    assert table is not None
    try:
        row_count = int(table["Number_Of_Rows"])
        column_count = int(table["Number_Of_Columns"])
    except (KeyError, TypeError, ValueError):
        return None, "ITA prompt catalog has invalid table dimensions"
    cells = table.get("TD")
    if (
        row_count != 28
        or column_count != 7
        or not isinstance(cells, list)
        or len(cells) != row_count * column_count
    ):
        return None, ("ITA prompt catalog does not have the unfiltered Table 5.1 shape")
    return year_key, None


def bea_ita_prompt_catalog_request_body(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "appid": spec["application_id"],
        "stepnum": spec["step_number"],
        "data": [
            ["Product", spec["product_id"]],
            ["TableList", spec["table_list"]],
        ],
    }


def bea_ita_itable_request_body(
    spec: Mapping[str, Any], period: str, year_key: str
) -> dict[str, Any]:
    _bea_quarter(period)
    return {
        "appid": spec["application_id"],
        "stepnum": spec["step_number"],
        "data": [
            ["Product", spec["product_id"]],
            ["TableList", spec["table_list"]],
            ["Filter_#1", year_key],
            ["Filter_#2", spec["frequency_key"]],
            ["Filter_#3", spec["line_number"]],
        ],
    }










def _bea_ita_table(
    response: Mapping[str, Any], spec: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    prompts = response.get("Prompts")
    if not isinstance(prompts, list):
        return None, "ITA iTable response has no prompt list"
    matches = [
        prompt
        for prompt in prompts
        if isinstance(prompt, dict)
        and prompt.get("Name") == spec["prompt_name"]
        and prompt.get("UIControl") == "Table"
    ]
    if len(matches) != 1:
        return None, f"expected one ITA table prompt, found {len(matches)}"
    try:
        prompt_data = json.loads(matches[0]["PromtData"])
        table = json.loads(prompt_data["Table"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return None, "ITA prompt does not contain a parseable table"
    if not isinstance(table, dict):
        return None, "ITA payload is not a table object"
    return table, None


def _bea_ita_cell_text(value: Any) -> str:
    return " ".join(unescape(str(value or "")).split())


def bea_ita_itable_value(
    raw: bytes,
    spec: Mapping[str, Any],
    period: str,
    release_day: dt.date,
    *,
    expected_year_key: str | None = None,
) -> tuple[float | None, str | None]:
    """Read and authenticate Table 5.1's exact QSA line-18 cell.

    The selected response shape and labels were verified against BEA's live
    Table 5.1 endpoint linked by the official June 24, 2026 release:
    https://apps.bea.gov/iTable/?ReqID=62&step=6&isuri=1&tablelist=62&product=1
    """

    response, refusal = _bea_ita_response(raw)
    if refusal:
        return None, refusal
    assert response is not None
    selected_year_key, refusal = bea_ita_prompt_selection(raw, spec, period)
    if refusal:
        return None, refusal
    if expected_year_key is not None and selected_year_key != expected_year_key:
        return None, (
            "ITA selected response year-key mapping changed between prompt and "
            f"table fetch: expected {expected_year_key!r}, got {selected_year_key!r}"
        )
    table, refusal = _bea_ita_table(response, spec)
    if refusal:
        return None, refusal
    assert table is not None
    if table.get("Title") != spec["table_title"]:
        return None, f"unexpected ITA iTable title {table.get('Title')!r}"
    if table.get("Sub_Title") != "[Millions of dollars]":
        return None, f"unexpected ITA iTable unit subtitle {table.get('Sub_Title')!r}"
    release_text = (
        f"Release Date: {release_day.strftime('%B')} "
        f"{release_day.day}, {release_day.year}"
    )
    description = str(table.get("Description") or "")
    if not description.startswith(release_text):
        return None, (
            f"ITA iTable release stamp {description!r} does not start with "
            f"registered release stamp {release_text!r}"
        )
    if (
        str(table.get("Number_Of_Header_Rows")) != "3"
        or str(table.get("Number_Of_Locked_Columns")) != "1,2"
    ):
        return None, "ITA iTable has unexpected header or locked-column metadata"
    try:
        row_count = int(table["Number_Of_Rows"])
        column_count = int(table["Number_Of_Columns"])
    except (KeyError, TypeError, ValueError):
        return None, "ITA iTable has invalid row or column dimensions"
    cells = table.get("TD")
    if (
        row_count != 6
        or column_count != 3
        or not isinstance(cells, list)
        or len(cells) != row_count * column_count
    ):
        return None, ("ITA selected iTable does not have the requested Table 5.1 shape")
    grid: dict[tuple[int, int], str] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            return None, "ITA iTable TD contains a non-cell value"
        try:
            coordinate = (int(cell["Row_ID"]), int(cell["Column_ID"]))
        except (KeyError, TypeError, ValueError):
            return None, "ITA iTable TD contains an invalid coordinate"
        if (
            coordinate in grid
            or not 1 <= coordinate[0] <= row_count
            or not 1 <= coordinate[1] <= column_count
        ):
            return None, "ITA iTable TD contains a duplicate or out-of-range coordinate"
        grid[coordinate] = _bea_ita_cell_text(cell.get("Cell_Value"))
    if len(grid) != row_count * column_count:
        return None, "ITA iTable TD coordinate grid is incomplete"

    year, quarter = _bea_quarter(period)
    columns = [
        column
        for column in range(3, column_count + 1)
        if grid[(1, column)] == spec["header_basis"]
        and grid[(2, column)] == str(year)
        and grid[(3, column)] == f"Q{quarter}"
    ]
    if len(columns) != 1:
        return None, (
            f"expected one ITA QSA {year} Q{quarter} column, found {len(columns)}"
        )
    rows = [
        row
        for row in range(4, row_count + 1)
        if grid[(row, 1)] == str(spec["line_number"])
        and _bea_row_label(grid[(row, 2)]) == spec["row_label"]
    ]
    if len(rows) != 1:
        return None, (
            f"expected one exact ITA line {spec['line_number']} "
            f"{spec['row_label']!r} row, found {len(rows)}"
        )
    printed_cell = grid[(rows[0], columns[0])].strip()
    if re.fullmatch(r"(?:0|[1-9]\d{0,2}(?:,\d{3})*)", printed_cell) is None:
        return None, (
            f"exact ITA iTable cell is not a printed whole number: {printed_cell!r}"
        )
    printed = printed_cell.replace(",", "")
    try:
        value = float(printed)
    except ValueError:
        return None, f"exact ITA iTable cell is not numeric: {printed!r}"
    if not math.isfinite(value) or value < 0:
        return None, (
            f"exact ITA iTable cell is not a nonnegative finite value: {value}"
        )
    expected_transform = {
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
    }
    if spec.get("value_transform") != expected_transform:
        return None, (
            f"unsupported BEA ITA value transform {spec.get('value_transform')!r}"
        )
    return value + 0.0, None


def fetch_bea_release_page(
    period: str, release_day: dt.date
) -> tuple[bytes | None, str, str]:
    url = bea_advance_release_url(period, release_day)
    retrieved_at = utc_now()
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html",
            "User-Agent": "thesis-resolver/1 (app.thesisinstitute.org)",
        },
    )
    try:
        raw, retrieved_at, final_url = http_request(
            request,
            allowed_hosts=tuple(sorted(BEA_RELEASE_REQUIRED_HOSTS)),
        )
        return raw, final_url, retrieved_at
    except (OSError, ValueError, urllib.error.HTTPError, urllib.error.URLError):
        return None, url, retrieved_at


def fetch_bea_ita_release_page(
    period: str, release_day: dt.date
) -> tuple[bytes | None, str, str]:
    url = bea_ita_release_url(period, release_day)
    retrieved_at = utc_now()
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html",
            "User-Agent": "thesis-resolver/1 (app.thesisinstitute.org)",
        },
    )
    try:
        raw, retrieved_at, final_url = http_request(
            request,
            allowed_hosts=tuple(sorted(BEA_RELEASE_REQUIRED_HOSTS)),
        )
        return raw, final_url, retrieved_at
    except (OSError, ValueError, urllib.error.HTTPError, urllib.error.URLError):
        return None, url, retrieved_at


def fetch_bea_itable_table(
    spec: Mapping[str, Any], period: str
) -> tuple[bytes | None, str, dict[str, Any], str]:
    body = bea_itable_request_body(spec, period)
    retrieved_at = utc_now()
    request = urllib.request.Request(
        BEA_ITABLE_DATA_URL,
        data=canonical_bytes(body),
        headers={
            "Accept": "application/json, text/plain",
            "Content-Type": "application/json",
            "User-Agent": "thesis-resolver/1 (app.thesisinstitute.org)",
        },
        method="POST",
    )
    try:
        raw, retrieved_at, final_url = http_request(
            request,
            allowed_hosts=tuple(sorted(BEA_RELEASE_REQUIRED_HOSTS)),
        )
        return raw, final_url, body, retrieved_at
    except (OSError, ValueError, urllib.error.HTTPError, urllib.error.URLError):
        return None, BEA_ITABLE_DATA_URL, body, retrieved_at


def _fetch_bea_ita_body(
    body: dict[str, Any],
) -> tuple[bytes | None, str, dict[str, Any], str]:
    retrieved_at = utc_now()
    request = urllib.request.Request(
        BEA_ITABLE_DATA_URL,
        data=canonical_bytes(body),
        headers={
            "Accept": "application/json, text/plain",
            "Content-Type": "application/json",
            "User-Agent": "thesis-resolver/1 (app.thesisinstitute.org)",
        },
        method="POST",
    )
    try:
        raw, retrieved_at, final_url = http_request(
            request,
            allowed_hosts=tuple(sorted(BEA_RELEASE_REQUIRED_HOSTS)),
        )
        return raw, final_url, body, retrieved_at
    except (OSError, ValueError, urllib.error.HTTPError, urllib.error.URLError):
        return None, BEA_ITABLE_DATA_URL, body, retrieved_at


def fetch_bea_ita_prompt_catalog(
    spec: Mapping[str, Any],
) -> tuple[bytes | None, str, dict[str, Any], str]:
    return _fetch_bea_ita_body(bea_ita_prompt_catalog_request_body(spec))


def fetch_bea_ita_itable_table(
    spec: Mapping[str, Any], period: str, year_key: str
) -> tuple[bytes | None, str, dict[str, Any], str]:
    return _fetch_bea_ita_body(bea_ita_itable_request_body(spec, period, year_key))




def bea_ita_release_snapshot_envelope(
    *,
    spec: Mapping[str, Any],
    period: str,
    value: float,
    release_url: str,
    release_raw: bytes,
    release_retrieved_at: str,
    catalog_url: str,
    catalog_body: Mapping[str, Any],
    catalog_raw: bytes,
    catalog_retrieved_at: str,
    table_url: str,
    table_body: Mapping[str, Any],
    table_raw: bytes,
    table_retrieved_at: str,
) -> bytes:
    """Archive the notice, prompt catalog, selected table, and exact parse."""

    envelope = {
        "schemaVersion": "bea_ita_release_snapshot_v1",
        "release": {
            "url": release_url,
            "retrievedAt": release_retrieved_at,
            "sha256": hashlib.sha256(release_raw).hexdigest(),
            "bodyBase64": base64.b64encode(release_raw).decode("ascii"),
        },
        "promptCatalog": {
            "url": catalog_url,
            "landingPageUrl": spec["source_url"],
            "request": catalog_body,
            "retrievedAt": catalog_retrieved_at,
            "sha256": hashlib.sha256(catalog_raw).hexdigest(),
            "bodyBase64": base64.b64encode(catalog_raw).decode("ascii"),
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


# CPS Table A-19 detail rows have no FRED mirror, so they resolve from an
# immutable Wayback Machine snapshot of the cells' OWN bound source page
# (bls.gov blocks non-browser fetches; web.archive.org serves the exact
# bytes and independently timestamps them). One snapshot per data month,
# captured right after the Employment Situation release. The three rows
# that DO have FRED mirrors (office/admin, production, transport) were
# cross-checked against ALFRED at the release vintage and matched exactly.
A19_SNAPSHOT_URLS: dict[str, str] = {
    "2026-06": (
        "https://web.archive.org/web/20260710110509/"
        "https://www.bls.gov/web/empsit/cpseea19.htm"
    ),
}
A19_ROW_LABELS: dict[str, str] = {
    "business_financial_operations": "Business and financial operations occupations",
    "computer_mathematical": "Computer and mathematical occupations",
    "healthcare_support": "Healthcare support occupations",
    "office_administrative_support": ("Office and administrative support occupations"),
    "production": "Production occupations",
    "transportation_material_moving": (
        "Transportation and material moving occupations"
    ),
}
A19_STEM = "bls.cps.employed_people_by_occupation"

# BLS CES detailed-industry cells (defense batch: aerospace product and
# parts, ship and boat building, federal Department of Defense) resolve
# directly from the BLS Public Data API v2 series their resolutionSourceUrls
# bind — two of the three have no FRED mirror. The API serves CURRENT
# estimates only (no ALFRED-style vintage archive), so first-print
# discipline is temporal: a period is captured only while it is still the
# series' latest published month AND still carries BLS's preliminary "P"
# footnote — the window between the Employment Situation release that first
# prints it and the next one (~4 weeks; the daily resolver cron lands on
# day one). A period found outside that window has been revised and is
# refused rather than recorded as a first print.
#
# Detailed industries print one month behind headline CES: June 2026 was
# not in the 2026-07-02 release the cells' resolutionDate names (verified
# live 2026-07-10: May 2026 was the latest print), so the adapter defers
# ("not yet published") until it lands — expected with the 2026-08-07
# Employment Situation.
#
# Anchors are the cells' own recorded history, i.e. FIRST prints, while the
# API returns current estimates, so anchor equality is tolerance-based:
# CES monthly recalculations move detailed first prints by a few tenths of
# a percent (observed while wiring this adapter: DoD April 2026 printed
# 474.9, read 476.6 at the 2026-07-10 vintage, +0.36%), and annual
# benchmarking can move levels by low single digits. 2% relative slack is
# publication-appropriate and still orders of magnitude tighter than the
# wrong-series/wrong-unit failures the gate exists to catch; if a later
# benchmark pushes an anchor past it, the refusal forces manual review
# rather than silently resolving from a redefined series.
BLS_API_URL = (
    "https://api.bls.gov/publicAPI/v2/timeseries/data/{series}"
    "?startyear={start}&endyear={end}"
)
BLS_ANCHOR_TOLERANCE = 0.02
BLS_API_ADAPTERS: dict[str, dict[str, Any]] = {
    "bls.ces.aerospace_product_and_parts_employment": {
        "series_id": "CES3133640001",
        "period_type": "month",
        "unit": "thousands",
        "label": "US aerospace product and parts employment (SA)",
        "source_name": "bls_ces",
        "source_table": (
            "Current Employment Statistics, all employees, aerospace "
            "product and parts manufacturing (SA)"
        ),
        "concept_authority": "bls",
        "source_concept": "CES3133640001",
        "anchor_start_year": 2025,
        "anchors": {
            "2025-06": 566.8,
            "2025-12": 577.6,
            "2026-02": 579.9,
            "2026-04": 585.4,
        },
    },
    "bls.ces.ship_and_boat_building_employment": {
        "series_id": "CES3133660001",
        "period_type": "month",
        "unit": "thousands",
        "label": "US ship and boat building employment (SA)",
        "source_name": "bls_ces",
        "source_table": (
            "Current Employment Statistics, all employees, ship and boat building (SA)"
        ),
        "concept_authority": "bls",
        "source_concept": "CES3133660001",
        "anchor_start_year": 2024,
        "anchors": {
            "2024-06": 153.2,
            "2025-06": 149.4,
            "2025-12": 148.8,
            "2026-04": 148.5,
        },
    },
    "bls.ces.federal_department_of_defense_employment": {
        "series_id": "CES9091911001",
        "period_type": "month",
        "unit": "thousands",
        "label": "US federal Department of Defense employment (SA)",
        "source_name": "bls_ces",
        "source_table": (
            "Current Employment Statistics, all employees, federal "
            "government, Department of Defense (SA)"
        ),
        "concept_authority": "bls",
        "source_concept": "CES9091911001",
        "anchor_start_year": 2025,
        "anchors": {
            "2025-06": 560.0,
            "2025-12": 490.1,
            "2026-02": 478.2,
            "2026-04": 474.9,
        },
    },
    "bls.cpi.u.annual_pct_change": {
        "series_id": "CUUR0000SA0",
        "period_type": "year",
        "transform": "annual_average_pct_change",
        "unit": "percent",
        "round": 1,
        "label": "US CPI-U annual-average inflation",
        "source_name": "bls_cpi",
        "source_table": (
            "Consumer Price Index for All Urban Consumers, US city average, all items"
        ),
        "concept_authority": "bls",
        "source_concept": "CUUR0000SA0",
        # The target and prior year require 24 monthly observations. Fetch one
        # year past the target as well: otherwise a query capped at target
        # December could falsely look current after January has published.
        "anchor_start_year": 2021,
        "fetch_end_year_offset": 1,
        "anchors": {
            "2022": 8.0,
            "2023": 4.1,
            "2024": 2.9,
            "2025": 2.6,
        },
    },
    # Aging/disability batch (wired 2026-08-23). CPS household-survey series
    # never carry BLS's preliminary "P" footnote (verified live: every
    # LNS11324230 and LNU02374597 row has empty footnotes), so their
    # first-print gate is purely temporal (`first_print_gate: latest_month`):
    # a period is captured only while it is still the series' latest
    # published month, i.e. before the next Employment Situation. BLS's
    # stated policy makes that window a first-print window: "BLS policy is to
    # not revise previous months' official seasonally adjusted CPS estimates
    # as new data become available during the year. Instead, revisions are
    # introduced for the most recent 5 years of data at the end of each
    # year" (bls.gov/cps/seasonal-adjustment-methodology.htm, read
    # 2026-08-23). LAUS state series carry "P" on the latest month and use
    # the default gate; the API serves persons, so that spec scales to the
    # catalog's thousands. Anchors reproduce the cells' own recorded
    # histories (docs/anchor-verifications.md).
    "bls.cps.lfpr_55_plus": {
        "series_id": "LNS11324230",
        "period_type": "month",
        "unit": "percent",
        "label": "US labor force participation rate, 55 years and over (SA)",
        "source_name": "bls_cps",
        "source_table": (
            "Current Population Survey, labor force participation rate, "
            "55 years and over, seasonally adjusted"
        ),
        "concept_authority": "bls",
        "source_concept": "LNS11324230",
        "first_print_gate": "latest_month",
        "anchor_start_year": 2025,
        "anchors": {
            "2025-06": 38.0,
            "2025-12": 37.9,
            "2026-04": 37.1,
            "2026-06": 37.1,
        },
    },
    "bls.cps.LNU02374597": {
        "series_id": "LNU02374597",
        "period_type": "month",
        "unit": "percent",
        "label": (
            "US employment-population ratio, persons with a disability, "
            "16 years and over (NSA)"
        ),
        "source_name": "bls_cps",
        "source_table": (
            "Current Population Survey, employment-population ratio, persons "
            "with a disability, 16 years and over, not seasonally adjusted "
            "(Employment Situation Table A-6)"
        ),
        "concept_authority": "bls",
        "source_concept": "LNU02374597",
        "first_print_gate": "latest_month",
        "anchor_start_year": 2025,
        "anchors": {
            "2025-06": 22.7,
            "2025-12": 23.4,
            "2026-04": 21.8,
            "2026-06": 21.8,
        },
    },
    "bls.ces.home_health_care_services.employment": {
        "series_id": "CES6562160001",
        "period_type": "month",
        "unit": "thousands",
        "label": "US home health care services employment (SA)",
        "source_name": "bls_ces",
        "source_table": (
            "Current Employment Statistics, all employees, home health care "
            "services (NAICS 6216), seasonally adjusted"
        ),
        "concept_authority": "bls",
        "source_concept": "CES6562160001",
        "anchor_start_year": 2025,
        "anchors": {
            "2025-06": 1778.8,
            "2025-12": 1830.3,
            "2026-04": 1868.0,
            "2026-05": 1878.0,
        },
    },
    "bls.laus.colorado.labor_force": {
        "series_id": "LASST080000000000006",
        "period_type": "month",
        "unit": "thousands",
        "scale": 0.001,
        "round": 1,
        "label": "Colorado civilian labor force (SA)",
        "source_name": "bls_laus",
        "source_table": (
            "Local Area Unemployment Statistics, Colorado, civilian labor "
            "force, seasonally adjusted (State Employment and Unemployment, "
            "Table 1)"
        ),
        "concept_authority": "bls",
        "source_concept": "LASST080000000000006",
        "anchor_start_year": 2025,
        # API units are persons; the ledger value is scaled to thousands.
        "anchors": {
            "2025-06": 3258203,
            "2025-12": 3254073,
            "2026-04": 3215558,
            "2026-06": 3193312,
        },
    },
}
for _spec in BLS_API_ADAPTERS.values():
    if _spec.get("first_print_gate") == "latest_month":
        _spec["evidence_notes"] = (
            "First print for {period} captured from {source_url} (BLS Public "
            "Data API v2, current estimates only) inside the first-print "
            "window: at capture the value was still the series' latest "
            "published month. CPS household-survey rows carry no preliminary "
            "footnote, and BLS policy is not to revise previous months' "
            "official seasonally adjusted CPS estimates during the year "
            "(annual end-of-year revision of the latest 5 years), so the value "
            "served before the next Employment Situation is the first print."
        )
    elif _spec["period_type"] == "month":
        _spec["evidence_notes"] = (
            "First print for {period} captured from {source_url} (BLS Public "
            "Data API v2, current estimates only) inside the first-print "
            "window: at capture the value was still the series' latest "
            "published month and still carried BLS's preliminary footnote."
        )
    else:
        _spec["evidence_notes"] = (
            "Annual-average percent change for {period}, calculated from all "
            "12 monthly CPI-U observations in {period} and the prior year "
            "from {source_url}; captured while December was still the API's "
            "latest month."
        )

# QCEW open-data preparation. Every admitted slice carries at least three
# values reproduced from the live official endpoint and recorded in
# docs/anchor-verifications.md. Resolution re-fetches those same slices and
# refuses on drift before trusting the target response; a repository fixture
# or forecast is never an observation.
QCEW_API_URL = (
    "https://data.bls.gov/cew/data/api/{year}/{api_period}/industry/{industry}.csv"
)
# Exact ordered annual-average layout published by BLS:
# https://www.bls.gov/cew/additional-resources/open-data/csv-data-slices.htm
QCEW_ANNUAL_CSV_FIELDS = (
    "area_fips",
    "own_code",
    "industry_code",
    "agglvl_code",
    "size_code",
    "year",
    "qtr",
    "disclosure_code",
    "annual_avg_estabs",
    "annual_avg_emplvl",
    "total_annual_wages",
    "taxable_annual_wages",
    "annual_contributions",
    "annual_avg_wkly_wage",
    "avg_annual_pay",
    "lq_disclosure_code",
    "lq_annual_avg_estabs",
    "lq_annual_avg_emplvl",
    "lq_total_annual_wages",
    "lq_taxable_annual_wages",
    "lq_annual_contributions",
    "lq_annual_avg_wkly_wage",
    "lq_avg_annual_pay",
    "oty_disclosure_code",
    "oty_annual_avg_estabs_chg",
    "oty_annual_avg_estabs_pct_chg",
    "oty_annual_avg_emplvl_chg",
    "oty_annual_avg_emplvl_pct_chg",
    "oty_total_annual_wages_chg",
    "oty_total_annual_wages_pct_chg",
    "oty_taxable_annual_wages_chg",
    "oty_taxable_annual_wages_pct_chg",
    "oty_annual_contributions_chg",
    "oty_annual_contributions_pct_chg",
    "oty_annual_avg_wkly_wage_chg",
    "oty_annual_avg_wkly_wage_pct_chg",
    "oty_avg_annual_pay_chg",
    "oty_avg_annual_pay_pct_chg",
)
QCEW_ADAPTERS: dict[str, dict[str, Any]] = {
    "bls.qcew.aircraft_manufacturing.establishments": {
        # Live-verified 2026-07-25 against data.bls.gov/cew/data/api
        # (US000, own_code 5, agglvl 18, size 0, NAICS 336411,
        # field qtrly_estabs); the runtime gate re-fetches and re-compares
        # every anchor before trusting the adapter.
        "anchor_status": "VERIFIED",
        "anchors": {"2024-07": 1314, "2024-10": 1332, "2025-01": 1379},
        "period_type": "quarter",
        "area_fips": "US000",
        "own_code": "5",
        "industry_code": "336411",
        "agglvl_code": "18",
        "size_code": "0",
        "field": "qtrly_estabs",
        "unit": "count",
        "label": "US private aircraft manufacturing establishments",
        "measure_concept": "bls.qcew.aircraft_manufacturing.establishments",
        "source_name": "bls_qcew",
        "source_table": (
            "QCEW NAICS-based quarterly industry CSV, private ownership, "
            "NAICS 336411 Aircraft manufacturing"
        ),
        # One already-published registration predates the named bls-qcew
        # adapter. Preserve only its exact immutable generic-url contract;
        # no other generic registration may enter this family.
        "legacy_binding_adapter": "generic-url",
        "legacy_source_table": (
            "QCEW NAICS-Based Quarterly CSV Files, 2026 quarterly by industry, "
            "private ownership, NAICS 336411 Aircraft manufacturing"
        ),
        "concept_authority": "bls",
        "source_concept": (
            "area_fips=US000;own_code=5;industry_code=336411;"
            "size_code=0;field=qtrly_estabs"
        ),
        # Keep the reviewed www.bls.gov landing page in the registration
        # binding and legacy fact URL. source_file and the response archive
        # bind the exact fetched data.bls.gov endpoint and bytes.
        "source_page": "https://www.bls.gov/cew/downloadable-data-files.htm",
    },
    "bls.qcew.child_day_care_services.annual_avg_employment": {
        # Live-fetched from the official annual industry slices on
        # 2026-08-12 UTC. The runtime gate re-fetches all three values before
        # trusting a target print; see docs/anchor-verifications.md.
        "anchor_status": "VERIFIED",
        "anchors": {"2023": 954796, "2024": 983412, "2025": 991735},
        "period_type": "year",
        "area_fips": "US000",
        "own_code": "5",
        "industry_code": "624410",
        "agglvl_code": "18",
        "size_code": "0",
        "field": "annual_avg_emplvl",
        "unit": "count",
        "label": "US private child day care services annual-average employment",
        "measure_concept": ("bls.qcew.child_day_care_services.annual_avg_employment"),
        "source_name": "bls_qcew",
        "source_table": (
            "QCEW NAICS-based annual averages industry CSV, U.S. total, "
            "private ownership, NAICS 624410 Child care services"
        ),
        "concept_authority": "bls",
        "source_concept": (
            "area_fips=US000;own_code=5;industry_code=624410;"
            "agglvl_code=18;size_code=0;qtr=A;field=annual_avg_emplvl"
        ),
        "source_series_id_includes_agglvl": True,
        # This identifies the recurring annual slice. The target contract's
        # period and exact fetched URL bind the year, so future dated rolls do
        # not inherit a stale year literal from the docket template.
        "source_series_id_includes_period": False,
        "source_page": "https://www.bls.gov/cew/downloadable-data-files.htm",
        "release_calendar_url": "https://www.bls.gov/cew/release-calendar.htm",
        "evidence_notes": (
            "First BLS QCEW preliminary annual-average employment print for "
            "{period}, captured from {source_url} on the exact Q4 full-data "
            "release day authenticated by the official QCEW calendar. The "
            "selector is U.S. total, private ownership, NAICS 624410, and "
            "field annual_avg_emplvl; later revisions are excluded."
        ),
        "filters": {
            "area_fips": "US000",
            "own_code": "5",
            "industry_code": "624410",
            "agglvl_code": "18",
            "size_code": "0",
            "qtr": "A",
        },
    },
}

# EIA DNav annual-history preparation. The API equivalent is key-gated, while
# the reviewed DNav page and its linked BIFF workbook are recurring, keyless
# official artifacts. DNav rewrites the workbook on its monthly publishing
# cycle even when the annual series has not advanced, so neither Last-Modified
# nor the workbook's generic "Next Release Date" establishes an annual print.
# Resolution requires the requested annual row inside the registered bounded
# Natural Gas Annual window, authenticates the page -> workbook link plus the
# workbook's sourcekey/header/unit, and archives both exact responses together.
EIA_DNAV_ADAPTERS: dict[str, dict[str, Any]] = {
    "eia.ng.vented_flared.us.annual": {
        "resolution_date_basis": "resolve-by-bound",
        "anchor_status": "VERIFIED",
        # Live-fetched 2026-08-13 from N9040US2a.xls. These are the exact
        # annual MMcf cells, not sums of the preliminary monthly series.
        "anchors": {"2022": 271682, "2023": 324207, "2024": 335163},
        "source_url": "https://www.eia.gov/dnav/ng/hist/n9040us2a.htm",
        "workbook_url": ("https://www.eia.gov/dnav/ng/hist_xls/N9040US2a.xls"),
        # The byte-pinned official page uses this one relative spelling. Treat
        # it as a sealed source token, never as a generally accepted relative
        # path: it must match before any URL parser or resolver sees it.
        "workbook_href": "../hist_xls/N9040US2a.xls",
        "workbook_link_text": "Download Data (XLS File)",
        "allowed_hosts": ("www.eia.gov",),
        "series_id": "N9040US2",
        "field": "annual_value_mmcf",
        "source_table": (
            "EIA DNav U.S. Natural Gas Vented and Flared annual history "
            "workbook, Data 1 sheet"
        ),
        "sheet_name": "Data 1",
        "first_year": 1936,
        "series_title": "U.S. Natural Gas Vented and Flared (MMcf)",
        "page_title": ("U.S. Natural Gas Vented and Flared (Million Cubic Feet)"),
        "unit": "million_cubic_feet",
        "country": "US",
        "label": "U.S. natural gas vented and flared",
        "measure_concept": "eia.ng.vented_flared.us.annual",
        "source_name": "eia_dnav",
        "concept_authority": "eia",
        "source_concept": "N9040US2",
        "evidence_notes": (
            "EIA N9040US2 annual value for {period}, read from the Data 1 "
            "sheet of the exact DNav workbook linked by {source_url}. The "
            "DNav HTML and workbook bytes are archived together; a monthly "
            "file refresh without the requested annual row never resolves."
        ),
        "filters": {
            "geography": "United States",
            "frequency": "annual",
            "sourcekey": "N9040US2",
        },
    }
}

# FSA CRP monthly-summary preparation. The official statistics landing page
# exposes a Month/Year table whose Summary cell links to a dated document page;
# that page links the PDF. This family pins all three URL path classes, refuses
# redirects, extracts the PDF's layout text with the runner image's
# ``pdftotext`` binary, and reads only the TOTAL CRP row's Acres column.
FSA_CRP_LANDING_URL = (
    "https://www.fsa.usda.gov/tools/informational/reports/conservation-statistics/crp"
)
FSA_CRP_STALE_LANDING_URL = (
    "https://www.fsa.usda.gov/resources/programs/"
    "conservation-reserve-program/statistics"
)
FSA_CRP_USER_AGENT = "Mozilla/5.0 (compatible; thesis-resolver/1.0)"

FSA_CRP_ADAPTERS: dict[str, dict[str, Any]] = {
    "usda.fsa.crp.enrolled_acres_total": {
        "resolution_date_basis": "resolve-by-bound",
        "anchor_status": "VERIFIED",
        # Integrator-verified 2026-08-13 against the recovered official path
        # (printed TOTAL CRP Acres cell, page-1 sign-up-type table — never
        # derived sums: March's components cross-foot one acre under the
        # printed total because FSA totals sum unrounded acreage).
        "anchors": {
            "2025-11": 26317011,
            "2026-03": 26203615,
            "2026-04": 26182019,
        },
        "source_url": FSA_CRP_LANDING_URL,
        "allowed_hosts": ("www.fsa.usda.gov",),
        "series_id": "usda.fsa.crp.enrolled_acres_total",
        "field": "enrolled_acres_total",
        "source_table": (
            "USDA FSA Conservation Reserve Program Statistics, CRP Monthly "
            "Summary, total row"
        ),
        "row_label": "TOTAL CRP",
        "column_label": "Acres",
        "unit": "count",
        "label": "US Conservation Reserve Program total enrolled acres",
        "measure_concept": "usda.fsa.crp.enrolled_acres_total",
        "source_name": "usda_fsa",
        "concept_authority": "usda_fsa",
        "source_concept": "CRP Monthly Summary; TOTAL CRP row; Acres column",
        "evidence_notes": (
            "Total CRP enrolled acres for {period}, read from the TOTAL CRP "
            "row's Acres column in the dated CRP Monthly Summary PDF selected "
            "from {source_url}; the fetched PDF bytes are archived."
        ),
    },
}

# Census's 2026-07-17 statement authenticates the revised SPM methodology's
# identity and says it will publish revised 2019--2024 estimates in September
# 2026; it does not establish the registered target's release window or
# deadline. Until those revised prints exist, current-method history is not a
# valid parser/calibration anchor for the new series. Keep ``anchors`` ABSENT
# (not placeholders) and refuse resolution before network access until an
# integrator verifies all six revised 2019--2024 official prints, including
# transition-discriminating 2019 and 2020 values. The parser and discovery path
# are committed now so the registered CY2027 pair has a mechanically
# resolvable source contract.
CENSUS_SPM_ADAPTERS: dict[str, dict[str, Any]] = {
    "census.spm.child_poverty_rate": {
        "resolution_date_basis": "resolve-by-bound",
        "anchor_status": "PENDING_REVISED_PRINT",
        "source_url": (
            "https://www.census.gov/newsroom/press-releases/2026/"
            "statement-on-supplemental-poverty-measure.html"
        ),
        "publications_url": (
            "https://www.census.gov/topics/income-poverty/library/publications.html"
        ),
        "allowed_hosts": ("www.census.gov", "www2.census.gov"),
        "series_id": "census.spm.child_poverty_rate",
        "field": "under_18_percent_in_poverty",
        "source_table": (
            "Poverty in the United States annual income-and-poverty release, "
            "revised-methodology Supplemental Poverty Measure Table B-2, "
            "ALL RACES year row, Under 18 years / Below Poverty / Percent "
            "column"
        ),
        "report_title_template": "Poverty in the United States: {year}",
        "table_filename": "tableB-2.xlsx",
        "sheet_name": "TableB-2",
        # Census has corrected SPM releases in place before. Bound capture
        # close to the official publication date, as the other mutable
        # first-print adapters do, rather than assuming a P60 URL is immutable.
        "first_print_window_days": 21,
        "section_label": "ALL RACES",
        "header_path": ("Under 18 years", "Below Poverty", "Percent"),
        "total_header_path": ("Under 18 years", "Total"),
        "poverty_count_header_path": (
            "Under 18 years",
            "Below Poverty",
            "Number",
        ),
        "unit": "percent",
        "label": "US child supplemental poverty measure rate",
        "measure_concept": "census.spm.child_poverty_rate",
        "source_name": "census",
        "concept_authority": "census",
        "source_concept": (
            "Supplemental Poverty Measure Table B-2; Under 18 years; Percent in poverty"
        ),
        "evidence_notes": (
            "CY{period} child Supplemental Poverty Measure rate under the "
            "revised methodology whose identity is authenticated by the "
            "Census 2026-07-17 announcement, read without scaling or "
            "rounding from the ALL RACES year row and "
            "Table B-2's 'Under 18 years / Below Poverty / Percent' column "
            "in the first annual "
            "income-and-poverty release; the fetched workbook bytes are "
            "archived. Announcement: {source_url}."
        ),
    },
}

# IRS SOI Individual Income Tax Returns Complete Report (Publication 1304)
# Table 3.3 adapter (2026-08-01, thesis#106). Table 3.3 publishes one .xls
# per tax year at https://www.irs.gov/pub/irs-soi/{yy}in33ar.xls roughly two
# calendar years after the tax year. That URL is neither versioned nor a
# release-time witness: the resolver may treat its bytes as the first print
# only when it captures them inside the registered release window. After the
# window closes, resolution fails closed until independently witnessed custody
# exists; current bytes must never be relabeled as the first print.
# Each reviewed spec authenticates one exact concept header, subcolumn, and
# transform at the "All returns, total" row. Pending references may be plain
# annual ids or condition-suffixed conditional-arm ids; every arm of a pair
# resolves to the same official print, and the site's condition registry
# gates which arm is scored.
IRS_SOI_PUB1304_ADAPTERS: dict[str, dict[str, Any]] = {
    "irs.actc.total_claims": {
        # Published IRS target snapshots predate the contract property. This
        # reviewed adapter declaration is their legacy fallback; new snapshots
        # carry the same value explicitly and disagreement fails closed.
        "resolution_date_basis": "resolve-by-bound",
        "anchor_status": "VERIFIED",
        # Integrator-verified 2026-08-01 against the official Table 3.3
        # workbooks (20in33ar.xls, 21in33ar.xls, 22in33ar.xls, 23in33ar.xls):
        # the printed whole-return counts at the "All returns, total" row,
        # "Number of returns" column of the refundable child tax credit /
        # additional child tax credit concept — never derived sums. Values
        # are whole-return counts; the recorded observation divides by
        # 1,000,000 per the registered transform.
        "anchors": {
            "2020": 19119249,
            "2021": 37771612,
            "2022": 18076696,
            "2023": 17626084,
        },
        "source_url": (
            "https://www.irs.gov/statistics/soi-tax-stats-individual-income-"
            "tax-returns-complete-report-publication-1304"
        ),
        "file_url_template": "https://www.irs.gov/pub/irs-soi/{yy}in33ar.{ext}",
        "allowed_hosts": ("www.irs.gov",),
        "series_id": "irs.actc.total_claims",
        "field": "refundable_child_tax_credit_returns",
        "source_table": (
            "IRS SOI Individual Income Tax Returns Complete Report "
            "(Publication 1304), Table 3.3, all returns total row, refundable "
            "child tax credit or additional child tax credit, number of returns"
        ),
        "sheet_name": "TBL33",
        "row_label": "all returns, total",
        "column_labels": (
            "refundable child tax credit or additional child tax credit",
            "additional child tax credit",
        ),
        "subcolumn_label": "number of returns",
        "subcolumn_offset": 0,
        "value_transform": {"operation": "multiply", "factor": 1e-06},
        "unit": "millions",
        "label": "US refundable child tax credit or ACTC claimant returns",
        "measure_concept": "irs.actc.total_claims",
        "source_name": "irs_soi",
        "concept_authority": "irs",
        "source_concept": (
            "Publication 1304 Table 3.3; All returns, total; Refundable "
            "child tax credit or additional child tax credit; Number of "
            "returns"
        ),
        "evidence_notes": (
            "TY{period} refundable child tax credit or additional child tax "
            "credit claimant returns, read from the 'All returns, total' "
            "row's 'Number of returns' column in the official Publication "
            "1304 Table 3.3 workbook linked from {source_url}; the fetched "
            "workbook bytes are archived. The recorded value is exactly the "
            "registered transform of the published whole-return count "
            "(multiplied by 1e-06), with no further rounding."
        ),
    },
    "irs.actc.total_credit_amount": {
        "resolution_date_basis": "resolve-by-bound",
        "anchor_status": "VERIFIED",
        "anchors": {
            "2020": 33664804,
            "2021": 115869125,
            "2022": 34843071,
            "2023": 34533251,
        },
        "source_url": (
            "https://www.irs.gov/statistics/soi-tax-stats-individual-income-"
            "tax-returns-complete-report-publication-1304"
        ),
        "file_url_template": "https://www.irs.gov/pub/irs-soi/{yy}in33ar.{ext}",
        "allowed_hosts": ("www.irs.gov",),
        "series_id": "irs.actc.total_credit_amount",
        "field": "refundable_child_tax_credit_amount",
        "source_table": (
            "IRS SOI Individual Income Tax Returns Complete Report "
            "(Publication 1304), Table 3.3, all returns total row, refundable "
            "child tax credit or additional child tax credit, amount"
        ),
        "sheet_name": "TBL33",
        "row_label": "all returns, total",
        "column_labels": (
            "refundable child tax credit or additional child tax credit",
            "additional child tax credit",
        ),
        "subcolumn_label": "amount",
        "subcolumn_offset": 1,
        "required_scale_marker": (
            "(All figures are estimates based on samples—money amounts are "
            "in thousands of dollars)"
        ),
        "scale_marker_cell": (1, 0),
        "value_transform": {"operation": "multiply", "factor": 0.001},
        "unit": "usd_millions",
        "label": "US refundable child tax credit or ACTC total credit amount",
        "measure_concept": "irs.actc.total_credit_amount",
        "source_name": "irs_soi",
        "concept_authority": "irs",
        "source_concept": (
            "Publication 1304 Table 3.3; All returns, total; Refundable "
            "child tax credit or additional child tax credit; Amount"
        ),
        "evidence_notes": (
            "TY{period} refundable child tax credit or additional child tax "
            "credit amount, read from the 'All returns, total' row's 'Amount' "
            "column in the official Publication 1304 Table 3.3 workbook "
            "linked from {source_url}; the fetched workbook bytes are "
            "archived. The workbook states that money amounts are in "
            "thousands of dollars. The recorded value is the published "
            "whole-thousand-dollar amount multiplied by 0.001 to produce "
            "USD millions, with no further rounding."
        ),
    },
    "irs.soi.credit_30d.total_claims": {
        "resolution_date_basis": "resolve-by-bound",
        "anchor_status": "VERIFIED",
        "anchors": {
            "2020": 61793,
            "2021": 166244,
            "2022": 248052,
            "2023": 493953,
        },
        "source_url": (
            "https://www.irs.gov/statistics/soi-tax-stats-individual-income-"
            "tax-returns-complete-report-publication-1304"
        ),
        "file_url_template": "https://www.irs.gov/pub/irs-soi/{yy}in33ar.{ext}",
        "allowed_hosts": ("www.irs.gov",),
        "series_id": "irs.soi.credit_30d.total_claims",
        "field": "clean_vehicle_credit_returns",
        "source_table": (
            "IRS SOI Individual Income Tax Returns Complete Report "
            "(Publication 1304), Table 3.3, all returns total row, clean "
            "vehicle credit or qualified plug-in electric vehicle credit, "
            "number of returns"
        ),
        "sheet_name": "TBL33",
        "row_label": "all returns, total",
        "column_labels": (
            "clean vehicle credit",
            "qualified plug-in electric vehicle credit",
        ),
        "subcolumn_label": "number of returns",
        "subcolumn_offset": 0,
        "value_transform": {"operation": "multiply", "factor": 1},
        "unit": "count",
        "label": "US clean vehicle credit claimant returns",
        "measure_concept": "irs.soi.credit_30d.total_claims",
        "source_name": "irs_soi",
        "concept_authority": "irs",
        "source_concept": (
            "Publication 1304 Table 3.3; All returns, total; Clean vehicle "
            "credit or qualified plug-in electric vehicle credit; Number "
            "of returns"
        ),
        "evidence_notes": (
            "TY{period} clean vehicle credit claimant returns, read from "
            "the 'All returns, total' row's 'Number of returns' column in "
            "the official Publication 1304 Table 3.3 workbook linked from "
            "{source_url}; the fetched workbook bytes are archived. The "
            "recorded value is the published whole-return count with an "
            "identity transform and no rounding."
        ),
    },
    "irs.soi.credit_30d.total_credit_amount": {
        "resolution_date_basis": "resolve-by-bound",
        "anchor_status": "VERIFIED",
        "anchors": {
            "2020": 313118,
            "2021": 1037358,
            "2022": 1652554,
            "2023": 3231102,
        },
        "source_url": (
            "https://www.irs.gov/statistics/soi-tax-stats-individual-income-"
            "tax-returns-complete-report-publication-1304"
        ),
        "file_url_template": "https://www.irs.gov/pub/irs-soi/{yy}in33ar.{ext}",
        "allowed_hosts": ("www.irs.gov",),
        "series_id": "irs.soi.credit_30d.total_credit_amount",
        "field": "clean_vehicle_credit_amount",
        "source_table": (
            "IRS SOI Individual Income Tax Returns Complete Report "
            "(Publication 1304), Table 3.3, all returns total row, clean "
            "vehicle credit or qualified plug-in electric vehicle credit, "
            "amount"
        ),
        "sheet_name": "TBL33",
        "row_label": "all returns, total",
        "column_labels": (
            "clean vehicle credit",
            "qualified plug-in electric vehicle credit",
        ),
        "subcolumn_label": "amount",
        "subcolumn_offset": 1,
        "required_scale_marker": (
            "(All figures are estimates based on samples—money amounts are "
            "in thousands of dollars)"
        ),
        "scale_marker_cell": (1, 0),
        "value_transform": {"operation": "multiply", "factor": 0.001},
        "unit": "usd_millions",
        "label": "US clean vehicle credit total credit amount",
        "measure_concept": "irs.soi.credit_30d.total_credit_amount",
        "source_name": "irs_soi",
        "concept_authority": "irs",
        "source_concept": (
            "Publication 1304 Table 3.3; All returns, total; Clean vehicle "
            "credit or qualified plug-in electric vehicle credit; Amount"
        ),
        "evidence_notes": (
            "TY{period} clean vehicle credit amount, read from the 'All "
            "returns, total' row's 'Amount' column in the official "
            "Publication 1304 Table 3.3 workbook linked from {source_url}; "
            "the fetched workbook bytes are archived. The workbook states "
            "that money amounts are in thousands of dollars. The recorded "
            "value is the published whole-thousand-dollar amount multiplied "
            "by 0.001 to produce USD millions, with no further rounding."
        ),
    },
}

# ---------------------------------------------------------------------------
# CMS provider-data (Care Compare) adapters (2026-07-20). Each monthly
# refresh REPLACES the published CSV in place, so the first print for a
# refresh is only capturable while that refresh is the live file. The
# metastore item is the release ledger: `modified` stamps the refresh's
# processing vintage (the first of the refresh month) and the distribution
# URL rotates per refresh, so the adapter reads the metastore first, gates
# on the modified month matching the cell's period, and only then downloads
# the CSV. A capture attempted after the next refresh replaces the file
# fails closed ("window missed") rather than resolving a later vintage.
CMS_PROVIDER_DATA_ADAPTERS: dict[str, dict[str, Any]] = {
    "cms.nursing_home_compare.reported_total_nurse_staffing_hprd_us": {
        "metastore_url": (
            "https://data.cms.gov/provider-data/api/1/metastore/schemas/"
            "dataset/items/xcdc-v8bm"
        ),
        "state_row": "NATION",
        "row_column": "State or Nation",
        "value_column": ("Reported Total Nurse Staffing Hours per Resident per Day"),
        "processing_date_column": "Processing Date",
        "unit": "ratio",
        "round": 3,
        "label": (
            "US nursing home reported total nurse staffing hours per "
            "resident per day (Care Compare national average)"
        ),
        "source_name": "cms_provider_data",
        "source_table": (
            "Nursing home Care Compare provider data, State US Averages "
            "(NH_StateUSAverages)"
        ),
        "concept_authority": "cms",
        "source_concept": ("Reported Total Nurse Staffing Hours per Resident per Day"),
        # Fail-closed sanity range: reported national total nurse staffing
        # HPRD has printed in the high-3s for years; anything outside this
        # band is a wrong column, wrong row, or upstream restructuring.
        "sanity_range": (2.0, 6.0),
        "evidence_notes": (
            "First print for {period} captured from {source_url}: the CMS "
            "provider-data metastore's modified date placed the live "
            "NH_StateUSAverages file inside the {period} refresh window at "
            "capture, and the file's own Processing Date column agreed."
        ),
    },
    # Computed metric: national occupancy = sum(residents/day) over
    # sum(certified beds) across every facility row in the Provider
    # Information file — one division over one official file, per the
    # cell's registered resolution rule.
    "cms.care_compare.nursing_home_occupancy_pct": {
        "metastore_url": (
            "https://data.cms.gov/provider-data/api/1/metastore/schemas/"
            "dataset/items/4pq5-n9py"
        ),
        "aggregate": {
            "numerator_column": "Average Number of Residents per Day",
            "denominator_column": "Number of Certified Beds",
            "scale": 100.0,
            # A truncated download would silently bias a sum ratio; the
            # file has carried ~14k-15k certified facilities for years.
            "min_rows": 10000,
        },
        "processing_date_column": "Processing Date",
        "unit": "percent",
        "round": 2,
        "label": (
            "US nursing home occupancy, average residents per day as a "
            "share of certified beds (Care Compare provider file)"
        ),
        "source_name": "cms_provider_data",
        "source_table": (
            "Nursing home Care Compare provider data, Provider Information "
            "(NH_ProviderInfo)"
        ),
        "concept_authority": "cms",
        "source_concept": (
            "Average Number of Residents per Day / Number of Certified Beds"
        ),
        "sanity_range": (60.0, 95.0),
        "evidence_notes": (
            "First print for {period} captured from {source_url}: the CMS "
            "provider-data metastore's modified date placed the live "
            "NH_ProviderInfo file inside the {period} refresh window at "
            "capture; occupancy computed as sum of Average Number of "
            "Residents per Day over sum of Number of Certified Beds across "
            "all facility rows with both fields populated."
        ),
    },
}


def cms_provider_data_metastore(
    spec: dict[str, Any],
) -> tuple[str, str, str]:
    """(modified_date, download_url, retrieved_at) from the metastore item."""
    request = urllib.request.Request(
        spec["metastore_url"],
        headers={"User-Agent": INTL_USER_AGENT},
    )
    retrieved_at = utc_now()
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode())
    modified = str(payload.get("modified") or "")
    distributions = payload.get("distribution") or []
    download_url = ""
    for distribution in distributions:
        candidate = str(distribution.get("downloadURL") or "")
        if candidate.lower().endswith(".csv"):
            download_url = candidate
            break
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", modified) or not download_url:
        raise ValueError(
            f"metastore item missing modified/downloadURL: {spec['metastore_url']}"
        )
    return modified, download_url, retrieved_at


def cms_provider_data_gate(period: str, modified: str) -> str | None:
    """None when `modified` is inside the period's refresh window, else the
    reason the capture must defer ("pending") or refuse ("missed")."""
    window_start = f"{period}-01"
    year, month = int(period[:4]), int(period[5:7])
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    window_end = f"{year}-{month:02d}-01"
    if modified < window_start:
        return (
            f"pending: metastore modified {modified} still before the "
            f"{period} refresh window"
        )
    if modified >= window_end:
        return (
            f"missed: metastore modified {modified} is past the {period} "
            f"refresh window; the first print is no longer the live file"
        )
    return None


def cms_provider_data_value(
    csv_bytes: bytes, spec: dict[str, Any], modified: str
) -> tuple[float | None, str | None]:
    """(value, refusal_reason) for the spec's metric in the live CSV.

    Two modes: a single row/column read (`state_row` + `value_column`), or
    an `aggregate` sum-ratio across every row (numerator over denominator,
    rows with either field unparseable skipped). Both cross-check the
    file's Processing Date against the metastore vintage and fail closed
    on restructured columns or out-of-band results.
    """
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig")))
    fieldnames = reader.fieldnames or []
    processing_column = spec.get("processing_date_column")

    def processing_date_mismatch(row: dict[str, Any]) -> str | None:
        if processing_column and row.get(processing_column) not in (
            None,
            "",
            modified,
        ):
            return (
                f"file Processing Date {row.get(processing_column)!r} "
                f"disagrees with metastore modified {modified!r}"
            )
        return None

    aggregate = spec.get("aggregate")
    if aggregate:
        numerator_column = aggregate["numerator_column"]
        denominator_column = aggregate["denominator_column"]
        if numerator_column not in fieldnames or (denominator_column not in fieldnames):
            return None, (
                f"columns {numerator_column!r}/{denominator_column!r} not "
                "both present; upstream file restructured"
            )
        numerator_total = 0.0
        denominator_total = 0.0
        rows_used = 0
        first_row_checked = False
        for row in reader:
            if not first_row_checked:
                first_row_checked = True
                mismatch = processing_date_mismatch(row)
                if mismatch:
                    return None, mismatch
            try:
                numerator = float((row.get(numerator_column) or "").strip())
                denominator = float((row.get(denominator_column) or "").strip())
            except ValueError:
                continue
            numerator_total += numerator
            denominator_total += denominator
            rows_used += 1
        min_rows = aggregate.get("min_rows", 1)
        if rows_used < min_rows:
            return None, (
                f"only {rows_used} usable rows (< {min_rows}); truncated "
                "download or upstream restructuring"
            )
        if denominator_total <= 0:
            return None, "denominator sum is not positive"
        value = numerator_total / denominator_total * aggregate.get("scale", 1.0)
    else:
        row_column = spec["row_column"]
        value_column = spec["value_column"]
        if row_column not in fieldnames or value_column not in fieldnames:
            return None, (
                f"columns {row_column!r}/{value_column!r} not both present; "
                "upstream file restructured"
            )
        target_row = next(
            (row for row in reader if row.get(row_column) == spec["state_row"]),
            None,
        )
        if target_row is None:
            return None, f"row {spec['state_row']!r} not found"
        mismatch = processing_date_mismatch(target_row)
        if mismatch:
            return None, mismatch
        raw_value = (target_row.get(value_column) or "").strip()
        try:
            value = float(raw_value)
        except ValueError:
            return None, f"non-numeric value {raw_value!r} in {value_column!r}"
    low, high = spec["sanity_range"]
    if not (low <= value <= high):
        return None, (
            f"value {value} outside sanity range [{low}, {high}]; wrong "
            "row/column or upstream restructuring"
        )
    return round(value, spec.get("round", 4)), None


# ---------------------------------------------------------------------------
# VA VBA Monday Morning Workload Report (weekly rating-bundle inventory).
#
# The cell family binds the VBA Detailed Claims Data page; the resolvable
# artifact is the weekly MMWR workbook that page links under each Monday
# report date (the file is named by the preceding Saturday's data-through
# date: report 07/13/2026 -> MMWR-07-11-2026.xlsx). The national
# "Compensation and Pension Rating Bundle" "# Pending" cell of the
# Transformation sheet is the page's headline "Pending Claims" status card.
# First-posting evidence is the workbook's Last-Modified header: every
# observed 2026 report was modified on its report Monday (07/06, a holiday
# week, on the Tuesday), so a file modified more than
# VA_MMWR_POSTING_WINDOW_DAYS after its report date is a re-post and is
# refused. Anchors are reproduced from the official workbooks at wiring time
# and re-verified from the live files at every run; the forecasting cell's
# own recorded history is deliberately NOT used as an anchor source here —
# three of its four "fetched" historical values do not exist in any VA
# workbook (see docs/anchor-verifications.md).
VA_MMWR_ALLOWED_HOSTS = ("www.benefits.va.gov", "benefits.va.gov")
VA_MMWR_POSTING_WINDOW_DAYS = 7
VA_MMWR_ENVELOPE_SCHEMA = "va_mmwr_workbook_capture_v1"
VA_MMWR_ADAPTERS: dict[str, dict[str, Any]] = {
    "va.vba.mmwr.claims_inventory": {
        "series_id": "va-vba-mmwr-rating-bundle-pending",
        "unit": "thousands",
        "scale": 0.001,
        "round": 3,
        "label": (
            "VA VBA Monday Morning Workload Report, Compensation and Pension "
            "Rating Bundle pending claims (national)"
        ),
        "source_name": "va_vba_mmwr",
        "source_table": (
            "Monday Morning Workload Report workbook, Transformation sheet, "
            "Compensation and Pension Rating Bundle Metrics (National View), "
            "# Pending, Compensation and Pension Rating Bundle / Total row"
        ),
        "concept_authority": "va_vba",
        "source_concept": "Compensation and Pension Rating Bundle: # Pending",
        "source_url": va_mmwr.LANDING_URL,
        # Report Mondays -> whole pending claims reproduced 2026-08-23 from
        # the official workbooks the landing page links for those dates.
        "anchors": {
            "2026-06-22": 593770,
            "2026-06-29": 589026,
            "2026-07-06": 601630,
        },
        "sanity_range": (100_000, 2_000_000),
        "evidence_notes": (
            "First print for the {period} report captured from the VBA "
            "Detailed Claims Data page's own link for that report date "
            "({source_url}): the linked MMWR workbook's Transformation sheet, "
            "Compensation and Pension Rating Bundle / Total, # Pending (cached "
            "value of the data_only read), whose Last-Modified header placed "
            "its posting inside the first-posting window after the report "
            "date; the workbook's 'Reporting through' cell matched the file's "
            "data-through date and its cached percent reproduced the counts."
        ),
    },
}


def parse_va_mmwr_ref(ref: str, stem: str) -> str | None:
    """``<stem>.week_YYYY-MM-DD.first_print`` -> ``YYYY-MM-DD`` (report date)."""
    match = re.fullmatch(
        rf"{re.escape(stem)}\.week_(\d{{4}}-\d{{2}}-\d{{2}})(?:\.first_print)?", ref
    )
    if not match:
        return None
    try:
        dt.date.fromisoformat(match.group(1))
    except ValueError:
        return None
    return match.group(1)


def va_mmwr_http_get(url: str) -> tuple[bytes, dict[str, str], str, str]:
    """(body, lower-cased headers, retrievedAt, finalUrl) with host pinning."""
    _require_allowed_host(url, VA_MMWR_ALLOWED_HOSTS)
    request = urllib.request.Request(url, headers={"User-Agent": INTL_USER_AGENT})
    retrieved_at = utc_now()
    opener = urllib.request.build_opener(_PinnedRedirectHandler(VA_MMWR_ALLOWED_HOSTS))
    with opener.open(request, timeout=300) as response:
        final_url = response.geturl()
        _require_allowed_host(final_url, VA_MMWR_ALLOWED_HOSTS)
        headers = {key.lower(): value for key, value in response.headers.items()}
        return response.read(), headers, retrieved_at, final_url


@dataclass(frozen=True)
class VaMmwrCapture:
    report_date: dt.date
    href: str
    workbook_url: str
    file_date: dt.date
    raw: bytes
    headers: dict[str, str]
    retrieved_at: str
    last_modified: dt.datetime
    reading: va_mmwr.RatingBundleReading


def va_mmwr_capture_report(
    landing_raw: bytes,
    report_date: dt.date,
    workbook_cache: dict[str, tuple[bytes, dict[str, str], str, str]],
) -> tuple[VaMmwrCapture | None, str | None]:
    """Resolve one report date to its workbook and parsed rating-bundle cell.

    (capture, refusal): identity refusals (no or several links, a file date
    far from the report date, a non-workbook body, a failed posting gate, a
    restructured sheet) come back as text; transport failures propagate.
    """
    try:
        href = va_mmwr.landing_workbook_href(landing_raw, report_date)
        file_date = va_mmwr.workbook_file_date(href)
        va_mmwr.require_file_date_near_report(file_date, report_date)
    except va_mmwr.VaMmwrError as exc:
        return None, str(exc)
    url = va_mmwr.workbook_url(href)
    if url not in workbook_cache:
        workbook_cache[url] = va_mmwr_http_get(url)
    raw, headers, retrieved_at, final_url = workbook_cache[url]
    if final_url != url:
        return None, f"workbook request for {url} landed on {final_url}"
    content_type = headers.get("content-type", "")
    if "spreadsheetml" not in content_type and "ms-excel" not in content_type:
        return None, (
            f"workbook response is {content_type!r}, not a spreadsheet (the VA "
            "site answers missing files with an HTML page and HTTP 200)"
        )
    last_modified, gate = va_mmwr.posting_gate(
        headers.get("last-modified"),
        file_date=file_date,
        report_date=report_date,
        window_days=VA_MMWR_POSTING_WINDOW_DAYS,
    )
    if gate:
        return None, gate
    assert last_modified is not None
    try:
        reading = va_mmwr.read_rating_bundle_pending(raw, expected_through=file_date)
    except va_mmwr.VaMmwrError as exc:
        return None, str(exc)
    return (
        VaMmwrCapture(
            report_date=report_date,
            href=href,
            workbook_url=url,
            file_date=file_date,
            raw=raw,
            headers=headers,
            retrieved_at=retrieved_at,
            last_modified=last_modified,
            reading=reading,
        ),
        None,
    )


def va_mmwr_capture_envelope(
    *,
    spec: Mapping[str, Any],
    landing_raw: bytes,
    landing_retrieved_at: str,
    target: VaMmwrCapture,
    anchors: list[VaMmwrCapture],
    value: float,
) -> bytes:
    """Archive every response that authenticated the weekly first print."""

    def capture_block(capture: VaMmwrCapture, *, include_body: bool) -> dict[str, Any]:
        block: dict[str, Any] = {
            "reportDate": capture.report_date.isoformat(),
            "href": capture.href,
            "url": capture.workbook_url,
            "dataThroughDate": capture.file_date.isoformat(),
            "retrievedAt": capture.retrieved_at,
            "lastModified": capture.headers.get("last-modified"),
            "etag": capture.headers.get("etag"),
            "contentType": capture.headers.get("content-type"),
            "bytes": len(capture.raw),
            "sha256": hashlib.sha256(capture.raw).hexdigest(),
            "reading": {
                "sheet": capture.reading.sheet,
                "cell": capture.reading.cell,
                "pending": capture.reading.pending,
                "pendingOver125": capture.reading.pending_over_125,
                "pctOver125": capture.reading.pct_over_125,
                "reportingThrough": capture.reading.reporting_through.isoformat(),
            },
        }
        if include_body:
            block["bodyBase64"] = base64.b64encode(capture.raw).decode()
        return block

    return canonical_bytes(
        {
            "schemaVersion": VA_MMWR_ENVELOPE_SCHEMA,
            "landingPage": {
                "url": va_mmwr.LANDING_URL,
                "retrievedAt": landing_retrieved_at,
                "bytes": len(landing_raw),
                "sha256": hashlib.sha256(landing_raw).hexdigest(),
                "bodyBase64": base64.b64encode(landing_raw).decode(),
            },
            "workbook": capture_block(target, include_body=True),
            "anchors": [
                capture_block(anchor, include_body=False) for anchor in anchors
            ],
            "derived": {
                "sourceSeriesId": spec["series_id"],
                "reportDate": target.report_date.isoformat(),
                "unit": spec["unit"],
                "value": value,
                "postingWindowDays": VA_MMWR_POSTING_WINDOW_DAYS,
            },
        }
    )


# ---------------------------------------------------------------------------
# SSA official statistical pages (SSI Monthly Statistics, Monthly Statistical
# Snapshot) and the OHO Hearing Office Workload Data XML.
#
# Transport: ssa.gov sits behind Akamai Bot Manager and answers every
# non-browser TLS client with HTTP 403 (verified 2026-08-23: curl/urllib with
# browser headers, from a laptop and from a GitHub Actions runner; the
# Wayback Machine's Save Page Now also fails on these URLs). A real headless
# Chromium, with an honest User-Agent suffix naming this resolver, is served
# normally; robots.txt disallows none of these paths. The family therefore
# fetches through scripts/official_browser_fetch.py and records the engine,
# UA, headers, and hashes in every capture envelope. The Wayback Machine is
# used only as corroboration: when a capture of the same URL exists, its
# parsed value must agree with the live page.
#
# First-print discipline: SSI Monthly Statistics and Monthly Statistical
# Snapshot editions live at per-period URLs (…/ssi_monthly/2026-06/table01
# .html, …/stat_snapshot/2026-06.html). Overlapping months are identical
# across editions (verified 2026-08-23: May 2026 total recipients 7,322,937
# in the May, June, and July editions' Table 2; the July edition's June row
# equals June's Table 1; Table 4 "All areas" equals Table 2's month), so a
# capture of an edition page reproduces its first print. The OHO workload
# XML is a rolling URL that is overwritten monthly, so its period must be
# authenticated from RPTG_PRD_ENDT, falling back to the earliest Wayback
# capture that carries the target period once the live file has rolled.
SSA_ALLOWED_HOSTS = ("www.ssa.gov",)
SSA_CAPTURE_SCHEMA = "ssa_official_page_capture_v1"
SSA_SSI_MONTHLY_URL = (
    "https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/{period}/{table}.html"
)
SSA_SNAPSHOT_URL = (
    "https://www.ssa.gov/policy/docs/quickfacts/stat_snapshot/{period}.html"
)
SSA_OHO_WORKLOAD_XML_URL = (
    "https://www.ssa.gov/appeals/DataSets/02_HO_Workload_Data.xml"
)
SSA_OFFICIAL_ADAPTERS: dict[str, dict[str, Any]] = {
    "ssa.ssi.recipients_aged_65_plus": {
        "reader": "ssi_table1",
        "release_evidence": "edition_page",
        "row": "Total",
        "column": "65 or older",
        "url_template": SSA_SSI_MONTHLY_URL,
        "table": "table01",
        "series_id": "ssa-ssi-monthly-table01-total-65-plus",
        "unit": "thousands",
        "scale": 0.001,
        "round": 3,
        "label": (
            "US SSI recipients aged 65 or older, all federally administered payments"
        ),
        "source_name": "ssa_ssi_monthly",
        "source_table": (
            "SSI Monthly Statistics, Table 1 (All Federally Administered "
            "Payments), Number of recipients, Total row, Age 65 or older"
        ),
        "concept_authority": "ssa",
        "source_concept": "Table 1: Number of recipients, Total, 65 or older",
        "anchors": {"2026-05": 2501549},
        "sanity_range": (1_500_000, 4_000_000),
    },
    "ssa.ssi.recipients.colorado.aged_65_plus": {
        "reader": "ssi_table4",
        "release_evidence": "edition_page",
        "state": "Colorado",
        "column": "65 or older",
        "url_template": SSA_SSI_MONTHLY_URL,
        "table": "table04",
        "series_id": "ssa-ssi-monthly-table04-colorado-65-plus",
        "unit": "count",
        "label": (
            "Colorado SSI recipients aged 65 or older, all federally "
            "administered payments"
        ),
        "source_name": "ssa_ssi_monthly",
        "source_table": (
            "SSI Monthly Statistics, Table 4 (All Federally Administered "
            "Payments), Colorado row, Age 65 or older"
        ),
        "concept_authority": "ssa",
        "source_concept": "Table 4: Number of recipients, Colorado, 65 or older",
        "anchors": {"2026-06": 23063},
        "sanity_range": (10_000, 60_000),
    },
    "ssa.ssi.recipients.colorado": {
        "reader": "ssi_table4",
        "release_evidence": "edition_page",
        "state": "Colorado",
        "column": "Total",
        "url_template": SSA_SSI_MONTHLY_URL,
        "table": "table04",
        "series_id": "ssa-ssi-monthly-table04-colorado-total",
        "unit": "thousands",
        "scale": 0.001,
        "round": 3,
        "label": "Colorado SSI recipients, all federally administered payments",
        "source_name": "ssa_ssi_monthly",
        "source_table": (
            "SSI Monthly Statistics, Table 4 (All Federally Administered "
            "Payments), Colorado row, Total"
        ),
        "concept_authority": "ssa",
        "source_concept": "Table 4: Number of recipients, Colorado, Total",
        "anchors": {"2026-06": 66417},
        "sanity_range": (30_000, 150_000),
    },
    "ssa.ssi.total_recipients": {
        "reader": "ssi_table2",
        "release_evidence": "edition_page",
        "url_template": SSA_SSI_MONTHLY_URL,
        "table": "table02",
        "series_id": "ssa-ssi-monthly-table02-total-recipients",
        "unit": "millions",
        "scale": 0.000001,
        "round": 6,
        "label": "US SSI recipients, all federally administered payments",
        "source_name": "ssa_ssi_monthly",
        "source_table": (
            "SSI Monthly Statistics, Table 2 (All Federally Administered "
            "Payments), Number of recipients, Total, the edition's own month"
        ),
        "concept_authority": "ssa",
        "source_concept": "Table 2: Number of recipients, Total",
        "anchors": {"2026-06": 7323731},
        "sanity_range": (5_000_000, 10_000_000),
    },
    "ssa.oasdi.disabled_worker_beneficiaries": {
        "reader": "snapshot_table2",
        "release_evidence": "edition_page",
        "group": "Disability Insurance",
        "row": "Disabled workers",
        "url_template": SSA_SNAPSHOT_URL,
        "series_id": "ssa-stat-snapshot-table02-disabled-workers",
        "unit": "thousands",
        "label": (
            "US disabled-worker beneficiaries in current-payment status "
            "(Monthly Statistical Snapshot)"
        ),
        "source_name": "ssa_stat_snapshot",
        "source_table": (
            "Monthly Statistical Snapshot, Table 2 (Social Security benefits), "
            "Disability Insurance, Disabled workers, Beneficiaries Number "
            "(thousands)"
        ),
        "concept_authority": "ssa",
        "source_concept": (
            "Table 2: Disability Insurance, Disabled workers, Number (thousands)"
        ),
        "anchors": {"2026-05": 7029},
        "sanity_range": (5_000, 10_000),
    },
    "ssa.hearings.average_processing_time_days": {
        "reader": "oho_workload_xml",
        "url_template": SSA_OHO_WORKLOAD_XML_URL,
        "series_id": "ssa-oho-hearing-office-workload-national-apt",
        "unit": "count",
        "label": (
            "SSA hearings national fiscal-year-to-date average processing time (days)"
        ),
        "source_name": "ssa_oho_public_data",
        "source_table": (
            "Office of Hearings Operations, Hearing Office Workload Data "
            "(02_HO_Workload_Data.xml), national Average Processing Time"
        ),
        "concept_authority": "ssa",
        "source_concept": "DSPN_AVGPT (national)",
        "anchors": {},
        "sanity_range": (100, 1_000),
    },
}


def ssa_period_url(spec: Mapping[str, Any], period: str) -> str:
    return str(spec["url_template"]).format(period=period, table=spec.get("table", ""))


def ssa_read_value(
    spec: Mapping[str, Any], raw: bytes, period: str
) -> ssa_official_pages.SsaTableReading:
    """Dispatch to the reviewed reader for ``spec``; raises SsaPageError."""
    reader = spec["reader"]
    if reader == "ssi_table1":
        return ssa_official_pages.ssi_table1_count(
            raw, period, row=spec["row"], column=spec["column"]
        )
    if reader == "ssi_table4":
        return ssa_official_pages.ssi_table4_count(
            raw, period, state=spec["state"], column=spec["column"]
        )
    if reader == "ssi_table2":
        return ssa_official_pages.ssi_table2_total_recipients(raw, period)
    if reader == "snapshot_table2":
        return ssa_official_pages.snapshot_table2_thousands(
            raw, period, group=spec["group"], row=spec["row"]
        )
    raise ValueError(f"no table reader for {reader!r}")


def ssa_scaled_value(spec: Mapping[str, Any], raw_value: int) -> float:
    value = raw_value * spec.get("scale", 1)
    digits = spec.get("round")
    if digits is not None:
        value = round(value, digits)
    return round(value, 9) + 0.0


def ssa_wayback_fetch(url: str) -> bytes:
    raw, _retrieved_at, _final = http_get(
        url, allowed_hosts=("web.archive.org",), timeout=90
    )
    return raw


def ssa_wayback_corroboration(
    url: str,
    parse: Callable[[bytes], int],
    *,
    fetch: Callable[[str], bytes] | None = None,
) -> dict[str, Any]:
    """Compare the live parsed value with the earliest parseable Wayback capture.

    Never a hard dependency: an unreachable CDX or no capture records
    ``status: unavailable`` / ``none``. A capture that parses to a different
    value is reported (``corroboratingCapture.value``) and the caller refuses.
    ``fetch`` defaults to the module-level ``ssa_wayback_fetch`` looked up at
    call time so tests can substitute it.
    """
    fetch = fetch or ssa_wayback_fetch
    try:
        captures = ssa_official_pages.wayback_captures(url, fetch)
    except Exception as exc:  # noqa: BLE001 - corroboration is best effort
        return {"status": "unavailable", "error": str(exc)[:300], "captures": []}
    summary = [
        {
            "timestamp": c["timestamp"],
            "digest": c.get("digest"),
            "length": c.get("length"),
        }
        for c in captures
    ]
    for capture in captures:
        try:
            body = ssa_official_pages.wayback_capture_body(
                capture["timestamp"], url, fetch
            )
            value = parse(body)
        except Exception as exc:  # noqa: BLE001 - try the next capture
            summary_entry = next(
                s for s in summary if s["timestamp"] == capture["timestamp"]
            )
            summary_entry["parse_error"] = str(exc)[:200]
            continue
        return {
            "status": "parsed",
            "captures": summary,
            "corroboratingCapture": {
                "timestamp": capture["timestamp"],
                "capturedAt": ssa_official_pages.wayback_timestamp_to_iso(
                    capture["timestamp"]
                ),
                "url": ssa_official_pages.wayback_raw_url(capture["timestamp"], url),
                "sha256": hashlib.sha256(body).hexdigest(),
                "value": value,
            },
        }
    return {"status": "none" if not captures else "unparseable", "captures": summary}


def ssa_capture_envelope(
    *,
    spec: Mapping[str, Any],
    period: str,
    capture: Any,
    reading: ssa_official_pages.SsaTableReading | None,
    raw_value: int | None,
    value: float | None,
    anchors: list[dict[str, Any]],
    wayback: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> bytes:
    """Archive the browser capture plus everything that authenticated it."""
    derived: dict[str, Any] = {
        "sourceSeriesId": spec["series_id"],
        "reader": spec["reader"],
        "period": period,
        "unit": spec["unit"],
        "rawValue": raw_value,
        "value": value,
    }
    if reading is not None:
        derived.update(
            {
                "row": reading.row,
                "column": reading.column,
                "tableCaption": reading.table_caption,
                "identities": list(reading.identities),
            }
        )
    if extra:
        derived.update(extra)
    return canonical_bytes(
        {
            "schemaVersion": SSA_CAPTURE_SCHEMA,
            "transport": capture.transport_record(),
            "page": {
                **capture.response_record(),
                "bodyBase64": base64.b64encode(capture.body).decode(),
            },
            "anchors": anchors,
            "wayback": wayback,
            "derived": derived,
        }
    )


MONTH_NUMBERS = {
    name: number
    for number, name in enumerate(
        "january february march april may june july august september "
        "october november december".split(),
        start=1,
    )
}
MONTH_ABBREVIATION_NUMBERS = {
    name[:3]: number for name, number in MONTH_NUMBERS.items()
}

# ---------------------------------------------------------------------------
# International native-source adapters (2026-07-10). ALFRED has no vintage
# coverage for these series, so each adapter binds the official national
# source the cells' resolver rules name. Every mapping below reproduced the
# cells' OWN recorded historicalContext anchors before becoming executable.
# Captured fixtures establish admission; live response identity, units,
# release windows, and status flags reject source drift at execution. Fixed
# historical anchors are deliberately not required to remain in bounded
# latest-N live responses: fixture reproduction is the immutable admission
# gate, while response identity is the durable recurring-execution gate.
# Candidate specs that lack three captured checks remain in
# INTL_BLOCKED_ADAPTERS and are never claimed. Where a recorded anchor and the
# official record disagreed, the official release-day artifact adjudicated.
#
# First-print discipline per source (anchors are FIRST prints; live APIs
# serve revised values on backfills):
#   - Sources whose published series are not revised (StatCan CPI and ABS
#     monthly CPI original) resolve from the current value fetched between
#     releases: that value IS the first print when
#     captured before the next release (the exact response bytes plus
#     retrievedAt are archived, so the vintage claim is auditable).
#   - Revision-prone series (LFS-style surveys, monthly GDP, EI counts)
#     additionally carry `first_print_window_days`: they resolve only while
#     the fetch instant is provably inside the window between the naming
#     release and the next one; after that the first print is no longer
#     retrievable from the live endpoint and the cell defers loudly.
#   - Series whose first prints are replaced on the SAME endpoint within
#     days (Eurostat retail benchmark revisions, ABS Building Approvals'
#     two-releases-per-month cycle) resolve only from immutable Wayback
#     snapshots of the month's own release page, pinned per period like
#     A19_SNAPSHOT_URLS. Eurostat HICP flash additionally requires the
#     target period to still carry its provisional/estimated status flag,
#     so a post-final fetch can never masquerade as the flash print.
INTL_USER_AGENT = (
    "Mozilla/5.0 (compatible; thesis-resolver/1.0; +https://app.thesisinstitute.org)"
)

US_GEOGRAPHY = {
    "level": "country",
    "id": "0100000US",
    "vintage": "current",
    "name": "United States",
}
INTL_GEOGRAPHY = {
    "CA": {"level": "country", "id": "CA", "vintage": "current", "name": "Canada"},
    "AU": {"level": "country", "id": "AU", "vintage": "current", "name": "Australia"},
    "UK": {
        "level": "country",
        "id": "UK",
        "vintage": "current",
        "name": "United Kingdom",
    },
    # "region" is the arch fact schema's level for supranational scopes
    # (ALLOWED_GEOGRAPHY_LEVELS in PolicyEngine/chronicle arch/core.py).
    "EA": {
        "level": "region",
        "id": "EA21",
        "vintage": "current",
        "name": "Euro area",
    },
}

STATCAN_WDS_LATEST = (
    "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
)
ABS_DATA_URL = (
    "https://data.api.abs.gov.au/rest/data/{flow}/{key}"
    "?lastNObservations={last_n}&format=jsondata"
)
EUROSTAT_DATA_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/{dataset}/{key}"
    "?format=JSON&lastNObservations={last_n}"
)
ONS_DATA_URL = "https://api.beta.ons.gov.uk/v1/data?uri={uri}"

# Pinned immutable snapshots per data month, one URL list per period tried
# in order (same custody model as A19_SNAPSHOT_URLS: web.archive.org serves
# exact bytes and independently timestamps them).
#
# Eurostat retail trade (euro area, volume, MoM SCA): the live sts_trtu_m /
# ei_isrr_m endpoints already serve benchmark-revised back months (Feb/Mar/
# Apr 2026 first prints 0.3/-0.1/-0.4 now read -0.4/0.8/-0.3), so only the
# release-day page witnesses the first print. Verified 2026-07-10: the
# 2026-06-04 release page headlines April at -0.4 (exact anchor match) and
# itself shows March already revised to 0.8, matching today's API; the
# 2026-07-06 release-day snapshot headlines May at +0.2, which the API
# still serves unrevised.
EUROSTAT_RETAIL_SNAPSHOT_URLS: dict[str, list[str]] = {
    "2026-05": [
        "https://web.archive.org/web/20260706201910/"
        "https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/4-06072026-bp",
    ],
}

# ABS Building Approvals (total dwellings, MoM % SA): the national SA
# series is not carried by the ABS Data API (BA_GCCSA serves Original
# only), and since May 2026 each month gets a first release then an update
# ~7 days later on the same page slug, so first prints must come from the
# release-day snapshot. Verified 2026-07-10: the apr-2026 page (released
# 2026-06-02) says "Total dwellings approved fell 3.4%, to 16,710" (exact
# anchor match) and the may-2026 release-day snapshot (2026-07-01, before
# the 7/08 update) says "Total dwellings approved fell 1.1% to 17,019".
ABS_BA_SNAPSHOT_URLS: dict[str, list[str]] = {
    "2026-05": [
        "https://web.archive.org/web/20260701030516/"
        "https://www.abs.gov.au/statistics/industry/building-and-construction/"
        "building-approvals-australia/may-2026",
    ],
}

# One spec per dataPointId stem; dataPointId dialects of the same fact share
# a spec dict (and therefore one cached fetch and one archived response).
# `verified_anchors` are immutable fixture-backed admission checks. `anchors`
# is reserved for a live sentinel only when a source supplies a durable
# invariant that cannot age out of its bounded response; none of the admitted
# recurring international APIs currently does.
_STATCAN_GDP_SPEC = {
    "kind": "statcan",
    "series_id": "statcan-v65201210",
    "admission_fixture": "statcan_gdp_v65201210.json",
    "source_file": "getDataFromVectorsAndLatestNPeriods (WDS JSON)",
    "extension": "json",
    "vector": 65201210,
    "latest_n": 36,
    "product": "36-10-0434-01",
    "transform": "mom_pct",
    "round": 1,
    "unit": "percent_growth",
    "label": "Canada real GDP by industry, all industries, MoM change (SA)",
    "source_name": "statcan",
    "source_table": (
        "GDP by industry, Table 36-10-0434-01 (all industries, chained "
        "2017 dollars, SA at annual rates)"
    ),
    "concept_authority": "statcan",
    "source_concept": "v65201210",
    "country": "CA",
    "valid_range": (-10.0, 10.0),
    "release_calendar_url": (
        "https://www150.statcan.gc.ca/n1/release-diffusion/2026-eng.pdf"
    ),
    # Monthly GDP levels are revised at each release, moving back-month MoM
    # changes by ~0.1pp per step (recorded first prints Nov25 0.0, Dec25
    # 0.2, Jan 0.1 currently read 0.1, 0.1, -0.0). The three most recent
    # published months reproduced their recorded first prints exactly on
    # 2026-07-10 (Feb 0.2, Mar -0.1, Apr 0.5); the tolerance absorbs one
    # revision step while still refusing transform mistakes (April YoY
    # would read ~1.5, a 1.0pp miss).
    # Admission evidence is immutable; these revision-prone back months are
    # not live sentinels. Response vector identity and the first-print window
    # are the runtime drift/vintage gates.
    "anchors": {},
    "verified_anchors": {
        "2026-02": 0.2,
        "2026-03": -0.1,
        "2026-04": 0.5,
    },
    "anchor_tolerance": 0.25,
    # The next monthly GDP release (~31 days later) revises the target
    # month itself, so the first print is only retrievable live until then.
    "first_print_window_days": 24,
}
_STATCAN_EI_SPEC = {
    "kind": "statcan",
    "series_id": "statcan-v64549350",
    "source_file": "getDataFromVectorsAndLatestNPeriods (WDS JSON)",
    "extension": "json",
    "vector": 64549350,
    "latest_n": 36,
    "product": "14-10-0011-01",
    "transform": "level",
    "scale": 0.001,
    "round": 2,
    "unit": "thousands",
    "label": "Canada EI regular beneficiaries (SA)",
    "source_name": "statcan",
    "source_table": (
        "Employment insurance beneficiaries, Table 14-10-0011-01 "
        "(regular benefits, Canada, SA)"
    ),
    "concept_authority": "statcan",
    "source_concept": "v64549350",
    "country": "CA",
    "valid_range": (100.0, 2000.0),
    "release_calendar_url": "https://www.statcan.gc.ca/o1/en/calendar",
    "entity": {"name": "person", "role": "ei_beneficiary"},
    # EI counts are administrative and re-seasonally-adjusted each release:
    # the latest month held exactly (Apr 544.44 recorded = 544.44 today),
    # the prior month drifted 0.56k in one release (Mar first print 548.0
    # -> 547.44), and February drifted ~8k over three releases, so only
    # the two freshest anchors are checked, at a tolerance wide enough for
    # documented SA refits but far below any wrong-series miss.
    # Back months revise, so first-print anchors are checked against captured
    # release payloads in tests/fixtures and docs/anchor-verifications.md,
    # not against today's
    # mutable table.
    "anchors": {},
    "candidate_anchors": {
        "2026-02": 542.11,
        "2026-03": 548.0,
        "2026-04": 544.44,
        "2026-05": 543.69,
    },
    "anchor_tolerance": 0.01,
    "first_print_window_days": 24,
}
_STATCAN_LFS_UR_SPEC = {
    "kind": "statcan",
    "series_id": "statcan-v2062815",
    "source_file": "getDataFromVectorsAndLatestNPeriods (WDS JSON)",
    "extension": "json",
    "vector": 2062815,
    "latest_n": 36,
    "product": "14-10-0287-01",
    "transform": "level",
    "round": 1,
    "unit": "percent",
    "label": "Canada unemployment rate (SA)",
    "source_name": "statcan",
    "source_table": (
        "Labour Force Survey, Table 14-10-0287-01 (unemployment rate, Canada, SA)"
    ),
    "concept_authority": "statcan",
    "source_concept": "v2062815",
    "country": "CA",
    "valid_range": (0.0, 25.0),
    "release_calendar_url": (
        "https://www150.statcan.gc.ca/n1/release-diffusion/2026-eng.pdf"
    ),
    "anchors": {
        "2026-03": 6.7,
        "2026-04": 6.9,
        "2026-05": 6.6,
        "2026-06": 6.5,
    },
    "candidate_anchors": {
        "2026-03": 6.7,
        "2026-04": 6.9,
        "2026-05": 6.6,
        "2026-06": 6.5,
    },
    "anchor_tolerance": 0.1,
    "first_print_window_days": 18,
}
_STATCAN_LFS_EMP_SPEC = {
    "kind": "statcan",
    "series_id": "statcan-v2062811",
    "source_file": "getDataFromVectorsAndLatestNPeriods (WDS JSON)",
    "extension": "json",
    "vector": 2062811,
    "latest_n": 36,
    "product": "14-10-0287-01",
    "transform": "mom_diff",
    "round": 0,
    "unit": "thousands",
    "label": "Canada employment change (SA)",
    "source_name": "statcan",
    "source_table": (
        "Labour Force Survey, Table 14-10-0287-01 "
        "(employment, Canada, SA; month-over-month change)"
    ),
    "concept_authority": "statcan",
    "source_concept": "v2062811",
    "country": "CA",
    "entity": {"name": "person", "role": "employed"},
    "valid_range": (-1000.0, 1000.0),
    "release_calendar_url": (
        "https://www150.statcan.gc.ca/n1/release-diffusion/2026-eng.pdf"
    ),
    # LFS levels rebenchmark; release-vintage fixtures carry the first-print
    # history and the live request is admitted only inside its registered
    # release window.
    "anchors": {},
    "candidate_anchors": {
        "2026-03": 14.0,
        "2026-04": -18.0,
        "2026-05": 88.0,
        "2026-06": 18.0,
    },
    "anchor_tolerance": 0.1,
    "first_print_window_days": 18,
}
_ABS_CPI_SPEC = {
    "kind": "abs",
    "series_id": "abs-cpi-allgroups-yoy",
    "admission_fixture": "abs_cpi_all_groups_yoy.json",
    "source_file": "ABS Data API SDMX-JSON",
    "extension": "json",
    "flow": "CPI",
    "key": "3.10001.10.50.M",
    "latest_n": 30,
    "transform": "level",
    "round": 1,
    "unit": "percent",
    "label": "Australia monthly CPI, all groups, annual change",
    "source_name": "abs",
    "source_table": (
        "Monthly Consumer Price Index (complete monthly CPI, dataflow CPI: "
        "annual change, all groups, original, weighted average of eight "
        "capital cities)"
    ),
    "concept_authority": "abs",
    "source_concept": "CPI/3.10001.10.50.M",
    "country": "AU",
    "valid_range": (-5.0, 25.0),
    "release_calendar_url": (
        "https://www.abs.gov.au/statistics/economy/"
        "price-indexes-and-inflation/consumer-price-index-australia"
    ),
    # Australia moved from the CPI_M indicator (final observation 2025-09)
    # to the complete monthly CPI published under dataflow CPI with
    # FREQ=M; the recorded anchors match the complete CPI exactly and
    # differ from the retired indicator (2025-09: 3.6 vs 3.5), so the
    # cells' series is the complete CPI. Original-series annual rates are
    # not revised; verified 2026-07-10 with six exact anchor matches
    # (Nov25 3.4, Dec25 3.8, Jan 3.8, Feb 3.7, Mar 4.6, Apr 4.2).
    "anchors": {},
    "verified_anchors": {
        "2026-02": 3.7,
        "2026-03": 4.6,
        "2026-04": 4.2,
        "2026-05": 4.0,
    },
    "anchor_tolerance": 0.1,
}
_ABS_EMP_SPEC = {
    "kind": "abs",
    "series_id": "abs-lf-employed-persons",
    "source_file": "ABS Data API SDMX-JSON",
    "extension": "json",
    "flow": "LF",
    "key": "M3.3.1599.20.AUS.M",
    "latest_n": 30,
    "transform": "mom_diff",
    "round": 1,
    "unit": "thousands",
    "label": "Australia employment change (SA)",
    "source_name": "abs",
    "source_table": (
        "Labour Force, Australia (dataflow LF: employed persons, seasonally "
        "adjusted, Australia; month-over-month change)"
    ),
    "concept_authority": "abs",
    "source_concept": "LF/M3.3.1599.20.AUS.M",
    "country": "AU",
    "entity": {"name": "person", "role": "employed"},
    "valid_range": (-1000.0, 1000.0),
    "release_calendar_url": (
        "https://www.abs.gov.au/statistics/labour/employment-and-unemployment/"
        "labour-force-australia"
    ),
    # ABS headlines the SA change against the prior month AS REVISED IN THE
    # SAME RELEASE, so the first print equals the level diff only at the
    # release's own vintage (the 2026-06-25 release page prints 14,698,500
    # -> 14,738,800 = +40,300, matching the live diff on 2026-07-10).
    # Historical level anchors are useless here — LFS rebenchmarks moved
    # the recorded April level (14,737.4) to 14,698.5 in one release — so
    # the anchor pins the latest release's own level, and the window keeps
    # the fetch inside the vintage that headlined the target change.
    "anchors": {},
    "candidate_anchors": {
        "2026-03": 17.9,
        "2026-04": -18.6,
        "2026-05": 40.3,
        "2026-06": 76.3,
    },
    "anchor_tolerance": 0.1,
    "first_print_window_days": 18,
}
_ABS_BA_SPEC = {
    "kind": "abs_ba_release",
    "series_id": "abs-building-approvals-release",
    "source_file": "building-approvals-australia release page (Wayback snapshot)",
    "extension": "html",
    "snapshots": ABS_BA_SNAPSHOT_URLS,
    "live_url_template": (
        "https://www.abs.gov.au/statistics/industry/"
        "building-and-construction/building-approvals-australia/{period_slug}"
    ),
    "unit": "percent_growth",
    "label": "Australia building approvals, total dwellings, MoM change (SA)",
    "source_name": "abs",
    "source_table": "Building Approvals, Australia (release page, key statistics)",
    "concept_authority": "abs",
    "source_concept": "building-approvals-australia release page",
    "country": "AU",
    "valid_range": (-100.0, 100.0),
    "release_calendar_url": (
        "https://www.abs.gov.au/statistics/industry/"
        "building-and-construction/building-approvals-australia"
    ),
    "anchors": {},
    "candidate_anchors": {
        "2026-02": 29.7,
        "2026-03": -10.5,
        "2026-04": -3.4,
        "2026-05": -1.1,
    },
    "anchor_tolerance": 0.1,
}
_EUROSTAT_HICP_SPEC = {
    "kind": "eurostat",
    "series_id": "eurostat-prc-hicp-minr-ea",
    "admission_fixture": "eurostat_hicp_flash.json",
    "source_file": "Eurostat dissemination API JSON-stat",
    "extension": "json",
    "dataset": "prc_hicp_minr",
    "key": "M.RCH_A.TOTAL.EA21",
    "latest_n": 36,
    "require_flag": True,
    "accepted_flags": ["e"],
    "unit": "percent",
    "label": "Euro area HICP all-items flash estimate, annual rate",
    "source_name": "eurostat",
    "source_table": (
        "HICP (ECOICOP ver.2) monthly rates, prc_hicp_minr (all-items "
        "annual rate, euro area)"
    ),
    "concept_authority": "eurostat",
    "source_concept": "prc_hicp_minr/M.RCH_A.TOTAL.EA21",
    "country": "EA",
    "valid_range": (-5.0, 25.0),
    "release_calendar_url": (
        "https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar"
    ),
    # Eurostat loads the euro-area flash into prc_hicp_minr on release
    # morning flagged as an estimate; finals (~2 weeks later) replace the
    # value and drop the flag, so `require_flag` refuses any fetch that
    # can no longer see the flash vintage. Verified 2026-07-10: seven
    # exact anchor matches (Nov25 2.1 ... May26 3.2) and 2026-06 = 2.8
    # still flagged, matching the 2026-07-01 release headline "Euro area
    # annual inflation down to 2.8%". The pre-2026 dataset (prc_hicp_manr)
    # was frozen at 2025-12 by the ECOICOP-2 migration.
    # The mutable current table already revised March from the 2.5 flash to
    # 2.6. The status-flag gate, registered release window, and captured
    # release fixtures enforce flash vintage instead of tolerating that.
    "anchors": {},
    "verified_anchors": {
        "2026-04": 3.0,
        "2026-05": 3.2,
        "2026-06": 2.8,
    },
    "anchor_tolerance": 0.1,
}
_EUROSTAT_UNEMP_SPEC = {
    "kind": "eurostat",
    "series_id": "eurostat-une-rt-m-ea",
    "source_file": "Eurostat dissemination API JSON-stat",
    "extension": "json",
    "dataset": "une_rt_m",
    "key": "M.SA.TOTAL.PC_ACT.T.EA21",
    "latest_n": 36,
    "require_flag": False,
    "unit": "percent",
    "label": "Euro area unemployment rate (SA)",
    "source_name": "eurostat",
    "source_table": "Unemployment by sex and age, une_rt_m (euro area, SA, total)",
    "concept_authority": "eurostat",
    "source_concept": "une_rt_m/M.SA.TOTAL.PC_ACT.T.EA21",
    "country": "EA",
    "valid_range": (0.0, 30.0),
    "release_calendar_url": (
        "https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar"
    ),
    # une_rt_m updates only on its monthly release day and revises back
    # months by <=0.2pp (ei_lm_m_vtg carries the documented vintages).
    # Verified 2026-07-10: the four freshest recorded first prints match
    # exactly (Feb 6.4, Mar 6.3, Apr 6.2, May 6.2; dataset updated
    # 2026-07-02, the May release day). An older recorded January anchor
    # (6.1) now reads 6.3 — documented revision drift, excluded.
    "anchors": {},
    "candidate_anchors": {
        "2026-02": 6.2,
        "2026-03": 6.2,
        "2026-04": 6.3,
        "2026-05": 6.2,
    },
    "anchor_tolerance": 0.1,
    "first_print_window_days": 21,
}
_EUROSTAT_CONSTRUCTION_SPEC = {
    "kind": "eurostat",
    "series_id": "eurostat-sts-copr-m-ea21",
    "source_file": "Eurostat dissemination API JSON-stat",
    "extension": "json",
    "dataset": "sts_copr_m",
    "key": "M.I21.SCA.PRD.F.EA21",
    "latest_n": 36,
    "transform": "level",
    "round": 1,
    "unit": "index_points",
    "label": "Euro area construction production index (SCA, 2021=100)",
    "source_name": "eurostat",
    "source_table": (
        "Production in construction, sts_copr_m "
        "(2021=100, SCA, total construction, EA21)"
    ),
    "concept_authority": "eurostat",
    "source_concept": "sts_copr_m/M.I21.SCA.PRD.F.EA21",
    "country": "EA",
    "valid_range": (20.0, 300.0),
    "release_calendar_url": (
        "https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar"
    ),
    "anchors": {},
    "candidate_anchors": {
        "2026-02": 103.3,
        "2026-03": 103.6,
        "2026-04": 105.5,
        "2026-05": 105.0,
    },
    "anchor_tolerance": 0.1,
    "first_print_window_days": 21,
}
_ONS_CPI_SPEC = {
    "kind": "ons",
    "series_id": "ons-d7g7-mm23",
    "source_file": "ONS v1 time-series JSON",
    "extension": "json",
    "uri": "/economy/inflationandpriceindices/timeseries/d7g7/mm23",
    "transform": "level",
    "round": 1,
    "unit": "percent",
    "label": "UK CPI annual rate",
    "source_name": "ons",
    "source_table": "MM23 consumer price inflation time series, D7G7",
    "concept_authority": "ons",
    "source_concept": "D7G7/MM23",
    "country": "UK",
    "valid_range": (-5.0, 25.0),
    "release_calendar_url": "https://www.ons.gov.uk/releasecalendar",
    "anchors": {
        "2026-03": 3.3,
        "2026-04": 2.8,
        "2026-05": 2.8,
        "2026-06": 2.6,
    },
    "candidate_anchors": {
        "2026-03": 3.3,
        "2026-04": 2.8,
        "2026-05": 2.8,
        "2026-06": 2.6,
    },
    "anchor_tolerance": 0.1,
}
_ONS_CLAIMANT_SPEC = {
    "kind": "ons",
    "series_id": "ons-bcjd-unem",
    "source_file": "ONS v1 time-series JSON",
    "extension": "json",
    "uri": (
        "/employmentandlabourmarket/peoplenotinwork/outofworkbenefits/"
        "timeseries/bcjd/unem"
    ),
    "transform": "level",
    "round": 1,
    "unit": "thousands",
    "label": "UK Claimant Count, people aged 16+, SA",
    "source_name": "ons",
    "source_table": "UNEM claimant count time series, BCJD",
    "concept_authority": "ons",
    "source_concept": "BCJD/UNEM",
    "country": "UK",
    "entity": {"name": "person", "role": "claimant"},
    "valid_range": (0.0, 10000.0),
    "release_calendar_url": "https://www.ons.gov.uk/releasecalendar",
    "anchors": {},
    "candidate_anchors": {
        "2026-03": 1694.3,
        "2026-05": 1711.9,
        "2026-06": 1688.6,
    },
    "anchor_tolerance": 0.1,
    "first_print_window_days": 24,
}
_ONS_RETAIL_SPEC = {
    "kind": "ons",
    "series_id": "ons-j5ec-drsi",
    "source_file": "ONS v1 time-series JSON",
    "extension": "json",
    "uri": ("/businessindustryandtrade/retailindustry/timeseries/j5ec/drsi"),
    "transform": "level",
    "round": 1,
    "unit": "percent_growth",
    "label": "Great Britain retail sales volume, MoM (SA)",
    "source_name": "ons",
    "source_table": "DRSI retail sales index time series, J5EC",
    "concept_authority": "ons",
    "source_concept": "J5EC/DRSI",
    "country": "UK",
    "valid_range": (-30.0, 30.0),
    "release_calendar_url": "https://www.ons.gov.uk/releasecalendar",
    "anchors": {},
    "candidate_anchors": {
        "2026-03": 0.7,
        "2026-04": -1.3,
        "2026-05": 1.2,
        "2026-06": 1.0,
    },
    "anchor_tolerance": 0.1,
    "first_print_window_days": 24,
}
_ONS_PSNB_SPEC = {
    "kind": "ons",
    "series_id": "ons-j5ii-pusf",
    "source_file": "ONS v1 time-series JSON",
    "extension": "json",
    "uri": (
        "/economy/governmentpublicsectorandtaxes/publicsectorfinance/"
        "timeseries/j5ii/pusf"
    ),
    "transform": "level",
    "scale": -0.001,
    "round": 1,
    "unit": "gbp_billions",
    "label": "UK public sector net borrowing excluding public sector banks",
    "source_name": "ons",
    "source_table": "PUSF public sector finances time series, J5II",
    "concept_authority": "ons",
    "source_concept": "J5II/PUSF",
    "country": "UK",
    "valid_range": (-100.0, 300.0),
    "release_calendar_url": "https://www.ons.gov.uk/releasecalendar",
    "anchors": {},
    "candidate_anchors": {
        "2026-03": 12.6,
        "2026-04": 24.3,
        "2026-05": 23.3,
        "2026-06": 16.0,
    },
    "anchor_tolerance": 0.1,
    "first_print_window_days": 24,
}
_EUROSTAT_RETAIL_SPEC = {
    "kind": "eurostat_release",
    "series_id": "eurostat-retail-trade-release",
    "source_file": "Euro indicators news release page (Wayback snapshot)",
    "extension": "html",
    "snapshots": EUROSTAT_RETAIL_SNAPSHOT_URLS,
    "unit": "percent_growth",
    "label": "Euro area retail trade volume, MoM change (SCA)",
    "source_name": "eurostat",
    "source_table": "Euro indicators news release, volume of retail trade",
    "concept_authority": "eurostat",
    "source_concept": "products-euro-indicators release page (euro area headline)",
    "country": "EA",
    "anchors": {},
    "anchor_tolerance": 0.0,
}




for _spec in (_STATCAN_CPI_SPEC,):
    _install_intl_binding(
        _spec,
        adapter="statcan-wds",
        source_url=STATCAN_WDS_LATEST,
        source_series_id=f"v{_spec['vector']}",
        field=f"v{_spec['vector']}",
        operation="percent_change_year_ago",
    )
for _spec in (_STATCAN_GDP_SPEC,):
    _install_intl_binding(
        _spec,
        adapter="statcan-wds",
        source_url=STATCAN_WDS_LATEST,
        source_series_id=f"v{_spec['vector']}",
        field=f"v{_spec['vector']}",
        operation="percent_change_previous_period",
    )
for _spec in (_STATCAN_EI_SPEC,):
    _install_intl_binding(
        _spec,
        adapter="statcan-wds",
        source_url=STATCAN_WDS_LATEST,
        source_series_id=f"v{_spec['vector']}",
        field=f"v{_spec['vector']}",
        operation="multiply",
        factor=0.001,
    )
for _spec in (_STATCAN_LFS_UR_SPEC,):
    _install_intl_binding(
        _spec,
        adapter="statcan-wds",
        source_url=STATCAN_WDS_LATEST,
        source_series_id=f"v{_spec['vector']}",
        field=f"v{_spec['vector']}",
        operation="identity",
    )
for _spec in (_STATCAN_LFS_EMP_SPEC,):
    _install_intl_binding(
        _spec,
        adapter="statcan-wds",
        source_url=STATCAN_WDS_LATEST,
        source_series_id=f"v{_spec['vector']}",
        field=f"v{_spec['vector']}",
        operation="difference_previous_period",
    )

for _spec in (_ABS_CPI_SPEC, _ABS_UR_SPEC):
    _source_id = f"{_spec['flow']}/{_spec['key']}"
    _install_intl_binding(
        _spec,
        adapter="abs-data-api",
        source_url=ABS_DATA_URL.format(
            flow=_spec["flow"],
            key=_spec["key"],
            last_n=_spec["latest_n"],
        ),
        source_series_id=_source_id,
        field=_source_id,
        operation="identity",
    )
_install_intl_binding(
    _ABS_EMP_SPEC,
    adapter="abs-data-api",
    source_url=ABS_DATA_URL.format(
        flow=_ABS_EMP_SPEC["flow"],
        key=_ABS_EMP_SPEC["key"],
        last_n=_ABS_EMP_SPEC["latest_n"],
    ),
    source_series_id=f"{_ABS_EMP_SPEC['flow']}/{_ABS_EMP_SPEC['key']}",
    field=f"{_ABS_EMP_SPEC['flow']}/{_ABS_EMP_SPEC['key']}",
    operation="difference_previous_period",
)
_install_intl_binding(
    _ABS_BA_SPEC,
    adapter="abs-release-page",
    source_url=_ABS_BA_SPEC["live_url_template"],
    source_series_id="building-approvals-australia.total-dwellings.sa",
    field="Total dwellings approved, seasonally adjusted, monthly change",
    operation="identity",
)
for _spec in (
    _EUROSTAT_HICP_SPEC,
    _EUROSTAT_UNEMP_SPEC,
    _EUROSTAT_CONSTRUCTION_SPEC,
):
    _source_id = f"{_spec['dataset']}/{_spec['key']}"
    _install_intl_binding(
        _spec,
        adapter="eurostat-api",
        source_url=EUROSTAT_DATA_URL.format(
            dataset=_spec["dataset"],
            key=_spec["key"],
            last_n=_spec["latest_n"],
        ),
        source_series_id=_source_id,
        field=_source_id,
        operation="identity",
    )
for _spec, _operation, _factor in (
    (_ONS_CPI_SPEC, "identity", 1),
    (_ONS_CLAIMANT_SPEC, "identity", 1),
    (_ONS_RETAIL_SPEC, "identity", 1),
    (_ONS_PSNB_SPEC, "multiply", -0.001),
):
    _source_id = _spec["source_concept"]
    _install_intl_binding(
        _spec,
        adapter="ons-timeseries",
        source_url=ONS_DATA_URL.format(uri=_spec["uri"]),
        source_series_id=_source_id,
        field=_source_id.split("/", 1)[0],
        operation=_operation,
        factor=_factor,
    )

# Network destinations are part of each adapter contract. The request helper
# validates both the requested URL and the final URL after redirects.
for _spec in (
    _STATCAN_CPI_SPEC,
    _STATCAN_GDP_SPEC,
    _STATCAN_EI_SPEC,
    _STATCAN_LFS_UR_SPEC,
    _STATCAN_LFS_EMP_SPEC,
):
    _spec["allowed_hosts"] = ["www150.statcan.gc.ca"]
for _spec in (_ABS_CPI_SPEC, _ABS_UR_SPEC, _ABS_EMP_SPEC):
    _spec["allowed_hosts"] = ["data.api.abs.gov.au"]
_ABS_BA_SPEC["allowed_hosts"] = ["www.abs.gov.au", "web.archive.org"]
for _spec in (
    _EUROSTAT_HICP_SPEC,
    _EUROSTAT_UNEMP_SPEC,
    _EUROSTAT_CONSTRUCTION_SPEC,
):
    _spec["allowed_hosts"] = ["ec.europa.eu"]
_EUROSTAT_RETAIL_SPEC["allowed_hosts"] = ["ec.europa.eu", "web.archive.org"]
for _spec in (
    _ONS_CPI_SPEC,
    _ONS_CLAIMANT_SPEC,
    _ONS_RETAIL_SPEC,
    _ONS_PSNB_SPEC,
):
    _spec["allowed_hosts"] = ["api.beta.ons.gov.uk"]

USASPENDING_API_ROOT = "https://api.usaspending.gov/api/v2"

# Registered-query snapshot family: USAspending revises continuously, so a
# target's outcome is the value its pinned query returns on the registered
# capture date (expectedReleaseWindow.start), never a source first print.
# Each spec mirrors the series' committed 7-key template in
# scripts/docket_series.json; the executor refuses on any drift between the
# registered binding and this table.
USASPENDING_ADAPTERS: dict[str, dict[str, Any]] = {
    "usaspending.dod.prime_award_obligations": {
        "url_template": (
            f"{USASPENDING_API_ROOT}/agency/097/awards/?fiscal_year={{fiscal_year}}"
        ),
        "field": "obligations",
        "series_id": "usaspending.agency.097.awards.obligations",
        "label": "US DoD prime award obligations, fiscal year to date",
        "unit": "billions USD",
        "scale": 1e-9,
        "round": 1,
        "transform": {"operation": "multiply", "factor": 1e-9},
        "source_name": "usaspending_api",
        "source_table": (
            "USAspending API v2, agency 097 (DoD) award summary, prime award "
            "obligations, fiscal year to date"
        ),
        "concept_authority": "usaspending",
        "source_concept": "obligations",
    },
    "usaspending.dod.prime_contract_obligations": {
        "url_template": (
            f"{USASPENDING_API_ROOT}/agency/097/obligations_by_award_category/"
            "?fiscal_year={fiscal_year}"
        ),
        "field": "results[category=contracts].aggregated_amount",
        "series_id": ("usaspending.agency.097.obligations_by_award_category.contracts"),
        "label": "US DoD prime contract obligations, fiscal year to date",
        "unit": "billions USD",
        "scale": 1e-9,
        "round": 1,
        "transform": {"operation": "multiply", "factor": 1e-9},
        "source_name": "usaspending_api",
        "source_table": (
            "USAspending API v2, agency 097 (DoD) obligations by award "
            "category, contracts row, fiscal year to date"
        ),
        "concept_authority": "usaspending",
        "source_concept": "results[category=contracts].aggregated_amount",
    },
    "usaspending.dod.new_prime_awards": {
        "url_template": (
            f"{USASPENDING_API_ROOT}/agency/097/awards/new/count/"
            "?fiscal_year={fiscal_year}"
        ),
        "field": "new_award_count",
        "series_id": "usaspending.agency.097.awards.new_award_count",
        "label": "US DoD new prime awards, fiscal year to date",
        "unit": "millions",
        "scale": 1e-6,
        "round": 3,
        "transform": {"operation": "multiply", "factor": 1e-6},
        "source_name": "usaspending_api",
        "source_table": (
            "USAspending API v2, agency 097 (DoD) new award count, fiscal year to date"
        ),
        "concept_authority": "usaspending",
        "source_concept": "new_award_count",
    },
    "usaspending.dod.prime_award_transactions": {
        "url_template": (
            f"{USASPENDING_API_ROOT}/agency/097/awards/?fiscal_year={{fiscal_year}}"
        ),
        "field": "transaction_count",
        "series_id": "usaspending.agency.097.awards.transaction_count",
        "label": "US DoD prime award transactions, fiscal year to date",
        "unit": "millions",
        "scale": 1e-6,
        "round": 3,
        "transform": {"operation": "multiply", "factor": 1e-6},
        "source_name": "usaspending_api",
        "source_table": (
            "USAspending API v2, agency 097 (DoD) award summary, transaction "
            "count, fiscal year to date"
        ),
        "concept_authority": "usaspending",
        "source_concept": "transaction_count",
    },
    "usaspending.dod.unique_prime_contract_recipients": {
        "url_template": (
            f"{USASPENDING_API_ROOT}/search/spending_by_category/recipient/"
        ),
        "field": "results[].recipient_id",
        "series_id": (
            "usaspending.search.spending_by_category.recipient.dod.contracts.distinct"
        ),
        "label": (
            "Unique identifiable recipients of US DoD prime-contract "
            "obligations, fiscal year to date"
        ),
        "unit": "thousands",
        "scale": 1e-3,
        "round": 3,
        "query_kind": "paginated_distinct_count",
        "transform": {
            "operation": "count_distinct",
            "requestMethod": "POST",
            "fiscalYear": "{fiscal_year}",
            "spendingLevel": "transactions",
            "agency": {
                "type": "awarding",
                "tier": "toptier",
                "name": "Department of Defense",
            },
            "awardTypeCodes": ["A", "B", "C", "D"],
            "identityField": "recipient_id",
            "excludeNullIdentity": True,
            "pageSize": 100,
            "factor": 1e-3,
        },
        "source_name": "usaspending_api",
        "source_table": (
            "USAspending API v2 advanced search, DoD prime-contract "
            "obligations grouped by recipient, fiscal year to date"
        ),
        "concept_authority": "usaspending",
        "source_concept": "distinct non-null recipient_id",
    },
    "usaspending.dod.small_business_contract_obligation_share": {
        "url_template": f"{USASPENDING_API_ROOT}/search/spending_over_time/",
        "field": ("results[time_period.fiscal_year={fiscal_year}].aggregated_amount"),
        "series_id": (
            "usaspending.search.spending_over_time.dod.contracts."
            "small_business_obligation_share"
        ),
        "label": (
            "Small-business share of US DoD prime-contract obligations, "
            "fiscal year to date"
        ),
        "unit": "percent",
        "scale": 1,
        "round": 2,
        "query_kind": "ratio_percent",
        "transform": {
            "operation": "ratio_percent",
            "requestMethod": "POST",
            "fiscalYear": "{fiscal_year}",
            "group": "fiscal_year",
            "spendingLevel": "transactions",
            "agency": {
                "type": "awarding",
                "tier": "toptier",
                "name": "Department of Defense",
            },
            "awardTypeCodes": ["A", "B", "C", "D"],
            "numeratorRecipientTypeNames": ["small_business"],
            "denominatorRecipientTypeNames": [],
            "factor": 1,
        },
        "source_name": "usaspending_api",
        "source_table": (
            "USAspending API v2 advanced search, small-business share of "
            "DoD prime-contract obligations, fiscal year to date"
        ),
        "concept_authority": "usaspending",
        "source_concept": (
            "100 * small_business contract obligations / all contract obligations"
        ),
    },
    "usaspending.cdfi.assistance_transaction_obligations": {
        "url_template": f"{USASPENDING_API_ROOT}/search/spending_over_time/",
        "field": ("results[time_period.fiscal_year={fiscal_year}].aggregated_amount"),
        "series_id": ("usaspending.search.spending_over_time.cdfi.program_obligations"),
        "label": (
            "CDFI Fund financial-assistance award-transaction obligations, "
            "fiscal year total"
        ),
        "unit": "usd_millions",
        "scale": 1e-6,
        "round": 8,
        "query_kind": "fiscal_year_post_scalar",
        "transform": {
            "operation": "multiply",
            "factor": 1e-6,
            "requestMethod": "POST",
            "fiscalYear": "{fiscal_year}",
            "group": "fiscal_year",
            "spendingLevel": "transactions",
            "agency": {
                "name": "Community Development Financial Institutions Fund",
                "tier": "subtier",
                "type": "awarding",
            },
            "awardTypeCodes": [
                "02",
                "03",
                "04",
                "05",
                "06",
                "07",
                "08",
                "09",
                "10",
                "11",
            ],
        },
        "source_name": "usaspending_api",
        "source_table": (
            "USAspending API v2 advanced search, CDFI Fund awarding-subagency "
            "financial-assistance award transactions, obligations by fiscal year"
        ),
        "concept_authority": "usaspending",
        "source_concept": (
            "signed net federal_action_obligation across prime financial-assistance "
            "award transactions whose awarding subtier is Community Development "
            "Financial Institutions Fund"
        ),
        "evidence_notes": (
            "Registered-query snapshot for {period} captured from {source_url} "
            "inside the preregistered snapshot window. USAspending revises "
            "continuously, so the outcome is the value the pinned query returned "
            "on the registered capture date; the full response bytes are archived. "
            "Scope is signed net federal_action_obligation across prime "
            "financial-assistance award transactions whose awarding subtier is the "
            "Community Development Financial Institutions Fund. It excludes "
            "non-award financial-account obligations and outlays and does not "
            "identify purchases, guarantees, loan-loss reserves, or any "
            "bill-specific amended-section-113 activity; it says nothing "
            "about CDFI loan originations, liquidity, competitiveness, or "
            "other downstream outcomes."
        ),
    },
    "usaspending.ondcp.hidta_al95001_obligations": {
        "url_template": f"{USASPENDING_API_ROOT}/search/spending_over_time/",
        "field": ("results[time_period.fiscal_year={fiscal_year}].aggregated_amount"),
        "series_id": (
            "usaspending.search.spending_over_time.ondcp.hidta_program_obligations"
        ),
        "label": (
            "HIDTA Assistance Listing 95.001 financial-assistance "
            "award-transaction obligations, fiscal year total"
        ),
        "unit": "usd_millions",
        "scale": 1e-6,
        "round": 8,
        "query_kind": "fiscal_year_post_scalar",
        "transform": {
            "operation": "multiply",
            "factor": 1e-6,
            "requestMethod": "POST",
            "fiscalYear": "{fiscal_year}",
            "group": "fiscal_year",
            "spendingLevel": "transactions",
            "awardTypeCodes": [
                "02",
                "03",
                "04",
                "05",
                "06",
                "07",
                "08",
                "09",
                "10",
                "11",
            ],
            "programNumbers": ["95.001"],
        },
        "source_name": "usaspending_api",
        "source_table": (
            "USAspending API v2 advanced search, financial-assistance award "
            "transactions filtered to Assistance Listing 95.001, obligations "
            "by fiscal year"
        ),
        "concept_authority": "usaspending",
        "source_concept": (
            "signed net federal_action_obligation across prime financial-assistance "
            "award transactions whose Assistance Listing is 95.001, grouped by "
            "action-date federal fiscal year"
        ),
        "evidence_notes": (
            "Registered-query snapshot for {period} captured from {source_url} "
            "inside the preregistered snapshot window. USAspending revises "
            "continuously, so the outcome is the value the pinned query returned "
            "on the registered capture date; the full response bytes are archived. "
            "Scope is the whole Assistance Listing 95.001 signed net "
            "award-transaction aggregate; no awarding-subagency filter is applied. "
            "It does not isolate section 707(s) supplemental competitive grants or "
            "spending under any newly permitted purpose, and it does not measure "
            "all HIDTA financial-account obligations, outlays, appropriations, "
            "budget authority, authorization, or bill-caused spending."
        ),
    },
    "usaspending.ntia.broadband_al11038_obligations": {
        "url_template": f"{USASPENDING_API_ROOT}/search/spending_over_time/",
        "field": ("results[time_period.fiscal_year={fiscal_year}].aggregated_amount"),
        "series_id": (
            "usaspending.search.spending_over_time.ntia.broadband_program_obligations"
        ),
        "label": (
            "Assistance Listing 11.038 Public Wireless Supply Chain Innovation "
            "Fund financial-assistance award-transaction obligations, fiscal "
            "year total"
        ),
        "unit": "usd_millions",
        "scale": 1e-6,
        "round": 8,
        "query_kind": "fiscal_year_post_scalar",
        "transform": {
            "operation": "multiply",
            "factor": 1e-6,
            "requestMethod": "POST",
            "fiscalYear": "{fiscal_year}",
            "group": "fiscal_year",
            "spendingLevel": "transactions",
            "awardTypeCodes": [
                "02",
                "03",
                "04",
                "05",
                "06",
                "07",
                "08",
                "09",
                "10",
                "11",
            ],
            "programNumbers": ["11.038"],
        },
        "source_name": "usaspending_api",
        "source_table": (
            "USAspending API v2 advanced search, financial-assistance award "
            "transactions filtered to Assistance Listing 11.038, obligations "
            "by fiscal year"
        ),
        "concept_authority": "usaspending",
        "source_concept": (
            "signed net federal_action_obligation across prime financial-assistance "
            "award transactions whose Assistance Listing is 11.038, grouped by "
            "action-date federal fiscal year"
        ),
        "evidence_notes": (
            "Registered-query snapshot for {period} captured from {source_url} "
            "inside the preregistered snapshot window. USAspending revises "
            "continuously, so the outcome is the value the pinned query returned "
            "on the registered capture date; the full response bytes are archived. "
            "Scope is the whole Assistance Listing 11.038 signed net "
            "award-transaction aggregate; no awarding-agency, awarding-subagency, "
            "Treasury-account, title-text, description-text, broadband-program-union, "
            "or FCC filter is applied. This preexisting advanced-wireless grant "
            "aggregate is context only. It does not measure establishment, "
            "membership, work, draft or final reports, the public-comment process, "
            "recommendations, or outcomes of the proposed 6G Task Force; spending "
            "caused or authorized by H.R. 2449; all NTIA, NIST, Commerce, or FCC "
            "obligations; or all obligations or outlays of federal account "
            "013-0565. It also excludes non-award financial-account obligations, "
            "appropriations, budget authority, and outlays."
        ),
    },
    "usaspending.usfs.minnesota_place_of_performance_obligations": {
        "url_template": f"{USASPENDING_API_ROOT}/search/spending_over_time/",
        "field": ("results[time_period.fiscal_year={fiscal_year}].aggregated_amount"),
        "series_id": (
            "usaspending.search.spending_over_time.usfs.minnesota_obligations"
        ),
        "label": (
            "Minnesota-wide Forest Service award-transaction obligations "
            "(context only), fiscal year total"
        ),
        "unit": "usd_millions",
        "scale": 1e-6,
        "round": 8,
        "query_kind": "fiscal_year_post_scalar",
        "transform": {
            "operation": "multiply",
            "factor": 1e-6,
            "requestMethod": "POST",
            "fiscalYear": "{fiscal_year}",
            "group": "fiscal_year",
            "spendingLevel": "transactions",
            "agency": {
                "name": "Forest Service",
                "tier": "subtier",
                "toptier_name": "Department of Agriculture",
                "type": "awarding",
            },
            "awardTypeCodes": [
                "02",
                "03",
                "04",
                "05",
                "06",
                "07",
                "08",
                "09",
                "10",
                "11",
                "A",
                "B",
                "C",
                "D",
                "IDV_A",
                "IDV_B",
                "IDV_B_A",
                "IDV_B_B",
                "IDV_B_C",
                "IDV_C",
                "IDV_D",
                "IDV_E",
            ],
            "placeOfPerformanceLocations": [{"country": "USA", "state": "MN"}],
        },
        "source_name": "usaspending_api",
        "source_table": (
            "USAspending API v2 advanced search, prime award transactions "
            "filtered to the Forest Service awarding subagency and Minnesota "
            "place of performance, obligations by fiscal year"
        ),
        "concept_authority": "usaspending",
        "source_concept": (
            "signed net federal_action_obligation across prime award transactions "
            "whose awarding subtier is Forest Service and whose reported place of "
            "performance has country USA and state MN, grouped by action-date "
            "federal fiscal year"
        ),
        "evidence_notes": (
            "Registered-query snapshot for {period} captured from {source_url} "
            "inside the preregistered snapshot window. USAspending revises "
            "continuously, so the outcome is the value the pinned query returned "
            "on the registered capture date; the full response bytes are archived. "
            "Scope is signed net federal_action_obligation across prime award "
            "transactions whose awarding subtier is Forest Service and whose "
            "reported place of performance has country=USA and state=MN. This is "
            "Minnesota-wide spending context only, not Superior National Forest "
            "obligations or activity confined to H.R. 978's covered forest lands. "
            "No value is attributed to H.R. 978. The series excludes an exact "
            "named-land-unit or forest-boundary filter; withdrawal-order status, "
            "mine-plan reviews, permits, mineral leases, prospecting permits, "
            "preference-right leases, or deadline compliance; all Forest Service "
            "financial-account obligations, appropriations, budget authority, and "
            "outlays; awards outside Minnesota or without Minnesota as their "
            "reported state; and bill-caused spending."
        ),
    },
    "usaspending.dhs.title_vi.award_transaction_obligations": {
        "url_template": f"{USASPENDING_API_ROOT}/search/spending_over_time/",
        "field": ("results[time_period.fiscal_year={fiscal_year}].aggregated_amount"),
        "series_id": (
            "usaspending.search.spending_over_time.dhs.title_vi."
            "award_transaction_obligations"
        ),
        "label": ("DHS Title VI award-transaction obligations, fiscal year total"),
        "unit": "usd",
        "scale": 1,
        "round": 2,
        "query_kind": "fiscal_year_post_scalar",
        "transform": {
            "operation": "multiply",
            "factor": 1,
            "requestMethod": "POST",
            "fiscalYear": "{fiscal_year}",
            "group": "fiscal_year",
            "spendingLevel": "transactions",
            "awardTypeCodes": [
                "02",
                "03",
                "04",
                "05",
                "06",
                "07",
                "08",
                "09",
                "10",
                "11",
                "A",
                "B",
                "C",
                "D",
                "IDV_A",
                "IDV_B",
                "IDV_B_A",
                "IDV_B_B",
                "IDV_B_C",
                "IDV_C",
                "IDV_D",
                "IDV_E",
            ],
            "treasuryAccountComponents": [
                {
                    "aid": "070",
                    "bpoa": "2025",
                    "epoa": "2029",
                    "main": "0530",
                    "sub": "000",
                },
                {
                    "aid": "070",
                    "bpoa": "2025",
                    "epoa": "2029",
                    "main": "0532",
                    "sub": "000",
                },
                {
                    "aid": "070",
                    "bpoa": "2025",
                    "epoa": "2029",
                    "main": "0509",
                    "sub": "000",
                },
                {
                    "aid": "070",
                    "bpoa": "2025",
                    "epoa": "2029",
                    "main": "0510",
                    "sub": "000",
                },
                {
                    "aid": "070",
                    "bpoa": "2025",
                    "epoa": "2029",
                    "main": "0413",
                    "sub": "000",
                },
                {"aid": "070", "main": "0722"},
            ],
        },
        "source_name": "usaspending_api",
        "source_table": (
            "USAspending API v2 advanced search, DHS Title VI award "
            "transactions filtered to named Treasury accounts, obligations "
            "by fiscal year"
        ),
        "concept_authority": "usaspending",
        "source_concept": (
            "aggregated_amount of award transactions for the registered union "
            "of five 2025/2029 Title VI TAS components and dedicated account "
            "070-0722"
        ),
    },
}
for _spec in USASPENDING_ADAPTERS.values():
    _spec.setdefault(
        "evidence_notes",
        "Registered-query snapshot for {period} captured from {source_url} "
        "inside the preregistered snapshot window. USAspending revises "
        "continuously, so the outcome is defined as the value the pinned "
        "query returned on the registered capture date; the full response "
        "bytes are archived as evidence.",
    )

USASPENDING_BINDING_TEMPLATE_KEYS = {
    "adapter",
    "sourceUrl",
    "sourceSeriesId",
    "field",
    "table",
    "transform",
    "releasePolicy",
}
USASPENDING_BINDING_DERIVED_KEYS = {"expectedReleaseWindow", "allowedHosts"}


def usaspending_binding_template(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete reviewed seven-key binding represented by a spec."""

    return {
        "adapter": "usaspending-api",
        "sourceUrl": spec["url_template"],
        "sourceSeriesId": spec["series_id"],
        "field": spec["field"],
        "table": spec["source_table"],
        "transform": spec["transform"],
        "releasePolicy": "registered_query_snapshot",
    }


def usaspending_binding_matches_spec(
    binding: Any,
    spec: Mapping[str, Any],
) -> bool:
    """Require all seven registered query keys to match the executor spec."""

    if not isinstance(binding, dict):
        return False
    if (
        set(binding) - USASPENDING_BINDING_DERIVED_KEYS
        != USASPENDING_BINDING_TEMPLATE_KEYS
    ):
        return False
    projection = {key: binding[key] for key in USASPENDING_BINDING_TEMPLATE_KEYS}
    return canonical_bytes(projection) == canonical_bytes(
        usaspending_binding_template(spec)
    )


def extract_json_field(payload: Any, selector: str) -> float | None:
    """Resolve a dotted selector with [key=value] list matches to a number.

    "results[category=contracts].aggregated_amount" walks payload["results"],
    picks the item whose "category" equals "contracts", then reads
    "aggregated_amount". Returns None when any hop is missing or the leaf is
    not a plain number, so the caller refuses instead of guessing.
    """
    current: Any = payload
    for segment in selector.split("."):
        match = re.fullmatch(r"([A-Za-z_]\w*)\[(\w+)=([^\]]+)\]", segment)
        if match:
            name, key, expected = match.groups()
            if not isinstance(current, dict):
                return None
            items = current.get(name)
            if not isinstance(items, list):
                return None
            current = next(
                (
                    item
                    for item in items
                    if isinstance(item, dict) and str(item.get(key)) == expected
                ),
                None,
            )
        else:
            if not isinstance(current, dict):
                return None
            current = current.get(segment)
        if current is None:
            return None
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        return None
    return float(current)


def usaspending_fiscal_year_dates(fiscal_year: str) -> tuple[str, str]:
    """Expand a four-digit US fiscal year to its inclusive action-date range."""

    if not re.fullmatch(r"\d{4}", fiscal_year):
        raise ValueError(f"invalid fiscal year: {fiscal_year!r}")
    year = int(fiscal_year)
    return f"{year - 1}-10-01", f"{year}-09-30"


def usaspending_fiscal_year_post_body(
    fiscal_year: str,
    transform: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one bound spending-over-time request for a registered scope."""

    award_codes = transform.get("awardTypeCodes")
    components = transform.get("treasuryAccountComponents")
    agency = transform.get("agency")
    program_numbers = transform.get("programNumbers")
    place_of_performance_locations = transform.get("placeOfPerformanceLocations")
    factor = transform.get("factor")
    common_keys = {
        "operation",
        "factor",
        "requestMethod",
        "fiscalYear",
        "group",
        "spendingLevel",
        "awardTypeCodes",
    }
    scope_keys = {
        key
        for key, value in (
            ("treasuryAccountComponents", components),
            ("agency", agency),
            ("programNumbers", program_numbers),
        )
        if value is not None
    }
    location_keys = (
        {"placeOfPerformanceLocations"}
        if place_of_performance_locations is not None
        else set()
    )
    if (
        transform.get("operation") != "multiply"
        or isinstance(factor, bool)
        or not isinstance(factor, (int, float))
        or not math.isfinite(float(factor))
        or factor <= 0
        or transform.get("requestMethod") != "POST"
        or transform.get("fiscalYear") != "{fiscal_year}"
        or transform.get("group") != "fiscal_year"
        or transform.get("spendingLevel") != "transactions"
        or not isinstance(award_codes, list)
        or not award_codes
        or not all(isinstance(code, str) and code for code in award_codes)
        or len(set(award_codes)) != len(award_codes)
        or len(scope_keys) != 1
        or (place_of_performance_locations is not None and agency is None)
        or set(transform) != common_keys | scope_keys | location_keys
    ):
        raise ValueError("registered USAspending fiscal-year POST plan is malformed")

    if agency is not None:
        if (
            not isinstance(agency, dict)
            or set(agency)
            not in (
                {"type", "tier", "name"},
                {"type", "tier", "name", "toptier_name"},
            )
            or agency.get("type") != "awarding"
            or agency.get("tier") != "subtier"
            or not isinstance(agency.get("name"), str)
            or not agency["name"]
            or (
                "toptier_name" in agency
                and (
                    not isinstance(agency["toptier_name"], str)
                    or not agency["toptier_name"]
                )
            )
        ):
            raise ValueError("registered USAspending awarding-subtier is malformed")
        filters = _usaspending_advanced_filters(fiscal_year, transform)
        return {
            "filters": filters,
            "group": "fiscal_year",
            "spending_level": "transactions",
        }

    if program_numbers is not None:
        if (
            not isinstance(program_numbers, list)
            or not program_numbers
            or not all(
                isinstance(program_number, str)
                and re.fullmatch(r"\d{2}\.\d{3}", program_number)
                for program_number in program_numbers
            )
            or len(set(program_numbers)) != len(program_numbers)
        ):
            raise ValueError("registered USAspending program numbers are malformed")
        start, end = usaspending_fiscal_year_dates(fiscal_year)
        return {
            "filters": {
                "award_type_codes": list(award_codes),
                "program_numbers": list(program_numbers),
                "time_period": [{"end_date": end, "start_date": start}],
            },
            "group": "fiscal_year",
            "spending_level": "transactions",
        }

    if not isinstance(components, list) or not components:
        raise ValueError("registered USAspending TAS plan is malformed")

    normalized_components: list[dict[str, str]] = []
    for component in components:
        if not isinstance(component, dict) or set(component) not in (
            {"aid", "main"},
            {"aid", "bpoa", "epoa", "main", "sub"},
        ):
            raise ValueError("registered USAspending TAS component is malformed")
        if not all(isinstance(value, str) for value in component.values()):
            raise ValueError("registered USAspending TAS component is malformed")
        if not re.fullmatch(r"\d{3}", component["aid"]) or not re.fullmatch(
            r"\d{4}", component["main"]
        ):
            raise ValueError("registered USAspending TAS component is malformed")
        if "bpoa" in component and (
            not re.fullmatch(r"\d{4}", component["bpoa"])
            or not re.fullmatch(r"\d{4}", component["epoa"])
            or int(component["bpoa"]) > int(component["epoa"])
            or not re.fullmatch(r"\d{3}", component["sub"])
        ):
            raise ValueError("registered USAspending TAS component is malformed")
        normalized_components.append(copy.deepcopy(component))
    if len({canonical_bytes(item) for item in normalized_components}) != len(
        normalized_components
    ):
        raise ValueError("registered USAspending TAS plan repeats a component")

    start, end = usaspending_fiscal_year_dates(fiscal_year)
    return {
        "filters": {
            "award_type_codes": list(award_codes),
            "time_period": [{"end_date": end, "start_date": start}],
            "treasury_account_components": normalized_components,
        },
        "group": "fiscal_year",
        "spending_level": "transactions",
    }


def _usaspending_advanced_filters(
    fiscal_year: str,
    transform: Mapping[str, Any],
    recipient_type_names: Any = None,
) -> dict[str, Any]:
    """Expand the registered query-plan transform into API filters."""

    if transform.get("fiscalYear") != "{fiscal_year}":
        raise ValueError("registered USAspending plan has an invalid fiscalYear")
    agency = transform.get("agency")
    award_codes = transform.get("awardTypeCodes")
    if (
        not isinstance(agency, dict)
        or set(agency)
        not in (
            {"type", "tier", "name"},
            {"type", "tier", "name", "toptier_name"},
        )
        or not isinstance(award_codes, list)
        or not award_codes
        or not all(isinstance(code, str) and code for code in award_codes)
    ):
        raise ValueError("registered USAspending plan has malformed filters")
    start, end = usaspending_fiscal_year_dates(fiscal_year)
    filters: dict[str, Any] = {
        "agencies": [copy.deepcopy(agency)],
        "award_type_codes": list(award_codes),
        "time_period": [{"end_date": end, "start_date": start}],
    }
    if recipient_type_names is not None:
        if not isinstance(recipient_type_names, list) or not all(
            isinstance(name, str) and name for name in recipient_type_names
        ):
            raise ValueError(
                "registered USAspending plan has malformed recipient types"
            )
        if recipient_type_names:
            filters["recipient_type_names"] = list(recipient_type_names)
    place_of_performance_locations = transform.get("placeOfPerformanceLocations")
    if place_of_performance_locations is not None:
        if (
            not isinstance(place_of_performance_locations, list)
            or not place_of_performance_locations
            or not all(
                isinstance(location, dict)
                and set(location) == {"country", "state"}
                and isinstance(location.get("country"), str)
                and re.fullmatch(r"[A-Z]{3}", location["country"])
                and isinstance(location.get("state"), str)
                and re.fullmatch(r"[A-Z]{2}", location["state"])
                for location in place_of_performance_locations
            )
            or len(
                {
                    canonical_bytes(location)
                    for location in place_of_performance_locations
                }
            )
            != len(place_of_performance_locations)
        ):
            raise ValueError(
                "registered USAspending place-of-performance locations are malformed"
            )
        filters["place_of_performance_locations"] = copy.deepcopy(
            place_of_performance_locations
        )
    return filters


def usaspending_recipient_page_body(
    fiscal_year: str,
    transform: Mapping[str, Any],
    page: int,
) -> dict[str, Any]:
    """Build one bound recipient-grouping page request."""

    if (
        transform.get("operation") != "count_distinct"
        or transform.get("requestMethod") != "POST"
        or transform.get("identityField") != "recipient_id"
        or transform.get("excludeNullIdentity") is not True
        or type(transform.get("pageSize")) is not int
        or not 1 <= transform["pageSize"] <= 100
        or type(page) is not int
        or page < 1
    ):
        raise ValueError("invalid registered recipient-count query plan")
    spending_level = transform.get("spendingLevel")
    if spending_level != "transactions":
        raise ValueError("invalid recipient-count spending level")
    return {
        "category": "recipient",
        "filters": _usaspending_advanced_filters(fiscal_year, transform),
        "limit": transform["pageSize"],
        "page": page,
        "spending_level": spending_level,
    }


def usaspending_share_bodies(
    fiscal_year: str,
    transform: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build denominator and numerator requests from the registered ratio plan."""

    if (
        transform.get("operation") != "ratio_percent"
        or transform.get("requestMethod") != "POST"
        or transform.get("group") != "fiscal_year"
        or transform.get("spendingLevel") != "transactions"
        or transform.get("denominatorRecipientTypeNames") != []
    ):
        raise ValueError("invalid registered obligation-share query plan")
    denominator = {
        "filters": _usaspending_advanced_filters(fiscal_year, transform),
        "group": transform["group"],
        "spending_level": transform["spendingLevel"],
    }
    numerator = {
        "filters": _usaspending_advanced_filters(
            fiscal_year,
            transform,
            transform.get("numeratorRecipientTypeNames"),
        ),
        "group": transform["group"],
        "spending_level": transform["spendingLevel"],
    }
    return denominator, numerator


def usaspending_distinct_recipient_count(
    pages: list[Any],
    transform: Mapping[str, Any],
) -> int | None:
    """Count distinct non-null recipient IDs from a complete page sequence."""

    identity_field = transform.get("identityField")
    if identity_field != "recipient_id" or not pages:
        return None
    identities: set[str] = set()
    for index, payload in enumerate(pages, start=1):
        if not isinstance(payload, dict):
            return None
        results = payload.get("results")
        metadata = payload.get("page_metadata")
        if not isinstance(results, list) or not isinstance(metadata, dict):
            return None
        has_next = metadata.get("hasNext")
        if (
            type(metadata.get("page")) is not int
            or metadata.get("page") != index
            or not isinstance(has_next, bool)
            or has_next != (index < len(pages))
        ):
            return None
        for result in results:
            if not isinstance(result, dict) or identity_field not in result:
                return None
            identity = result[identity_field]
            if identity is None and transform.get("excludeNullIdentity") is True:
                continue
            if not isinstance(identity, str) or not identity:
                return None
            identities.add(identity)
    return len(identities)


def usaspending_fiscal_year_amount(
    payload: Any,
    fiscal_year: str,
) -> float | None:
    """Select one finite spending-over-time amount for a fiscal year."""

    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return None
    matches = []
    for result in payload["results"]:
        if not isinstance(result, dict):
            continue
        period = result.get("time_period")
        if (
            not isinstance(period, dict)
            or str(period.get("fiscal_year")) != fiscal_year
        ):
            continue
        amount = result.get("aggregated_amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            return None
        amount = float(amount)
        if not math.isfinite(amount):
            return None
        matches.append(amount)
    return matches[0] if len(matches) == 1 else None


def usaspending_ratio_percent(
    numerator_payload: Any,
    denominator_payload: Any,
    fiscal_year: str,
) -> float | None:
    """Derive a finite percentage from two same-scope registered snapshots."""

    numerator = usaspending_fiscal_year_amount(numerator_payload, fiscal_year)
    denominator = usaspending_fiscal_year_amount(denominator_payload, fiscal_year)
    if (
        numerator is None
        or denominator is None
        or denominator <= 0
        or numerator < 0
        or numerator > denominator
    ):
        return None
    value = 100 * numerator / denominator
    return value if math.isfinite(value) else None


def usaspending_snapshot_envelope(
    source_url: str,
    exchanges: list[tuple[dict[str, Any], bytes, str]],
    derived: Mapping[str, Any],
) -> bytes:
    """Archive every exact POST body and raw response in one evidence artifact."""

    evidence = {
        "schemaVersion": "usaspending_registered_query_snapshot_v1",
        "sourceUrl": source_url,
        "exchanges": [
            {
                "method": "POST",
                "requestBody": body,
                "retrievedAt": retrieved_at,
                "responseBodyUtf8": raw.decode("utf-8"),
                "responseSha256": hashlib.sha256(raw).hexdigest(),
            }
            for body, raw, retrieved_at in exchanges
        ],
        "derived": dict(derived),
    }
    return canonical_bytes(evidence) + b"\n"


def fetch_usaspending_json(
    source_url: str,
    body: dict[str, Any] | None = None,
) -> tuple[Any, bytes, str]:
    """Fetch one GET or canonical-JSON POST response from USAspending."""

    retrieved_at = utc_now()
    headers = {
        "Accept": "application/json",
        "User-Agent": "thesis-resolver/1 (app.thesisinstitute.org)",
    }
    data = None
    method = "GET"
    if body is not None:
        data = canonical_bytes(body)
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(
        source_url,
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8")), raw, retrieved_at


def snapshot_window_state(today: dt.date, window: Any) -> str:
    """ "pending" | "open" | "missed" | "invalid" for a snapshot window."""
    if not isinstance(window, dict):
        return "invalid"
    try:
        start = dt.date.fromisoformat(str(window.get("start")))
        end = dt.date.fromisoformat(str(window.get("end")))
    except (TypeError, ValueError):
        return "invalid"
    if start > end:
        return "invalid"
    if today < start:
        return "pending"
    if today > end:
        return "missed"
    return "open"


RESOLUTION_DATE_BASES = {"release-calendar", "resolve-by-bound"}
DEFAULT_RESOLUTION_DATE_BASIS = "release-calendar"


def effective_resolution_date_basis(
    ref: str,
    registration: Mapping[str, Any] | None,
    spec: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    """Authenticate release-day versus resolve-by gating semantics.

    The content-hashed registration wins. Absence means release-calendar.
    Only the two immutable IRS-SOI registrations minted immediately before
    ``resolutionDateBasis`` existed may inherit their reviewed adapter's
    bounded declaration, and only when their registered adapter identity also
    matches. When both declarations are present they must agree.
    """

    contract = (registration or {}).get("contract") or {}
    registered_present = "resolutionDateBasis" in contract
    registered = contract.get("resolutionDateBasis")
    declared_present = "resolution_date_basis" in spec
    declared = spec.get("resolution_date_basis")
    for label, present, value in (
        ("registered", registered_present, registered),
        ("adapter", declared_present, declared),
    ):
        if present and (
            not isinstance(value, str) or value not in RESOLUTION_DATE_BASES
        ):
            return None, f"unsupported {label} basis {value!r}"
    if registered_present and declared_present and registered != declared:
        return None, (
            f"registered basis {registered!r} disagrees with adapter basis {declared!r}"
        )
    if registered_present:
        return str(registered), None
    if declared == "resolve-by-bound":
        binding = contract.get("sourceBinding") or {}
        if (
            ref in LEGACY_BOUNDED_CONDITIONAL_IDS
            and contract.get("dataPointId") == ref
            and isinstance(binding, Mapping)
            and binding.get("adapter") == "irs-soi-pub1304"
        ):
            return "resolve-by-bound", None
        return None, (
            "absent registered basis defaults to 'release-calendar'; adapter "
            "basis 'resolve-by-bound' may be inherited only by the two legacy "
            "IRS-SOI targets with adapter 'irs-soi-pub1304': "
            f"{ref}"
        )
    return DEFAULT_RESOLUTION_DATE_BASIS, None


def bounded_resolution_window_gate(
    ref: str,
    today: dt.date,
    window: Any,
) -> tuple[str, str | None]:
    """Return the shared resolve-by window state and fail-closed verdict."""

    state = snapshot_window_state(today, window)
    if state == "invalid":
        return state, f"  NO REGISTERED RELEASE WINDOW (refusing): {ref}"
    if state == "pending":
        return state, (
            f"  RELEASE WINDOW NOT OPEN (deferring): {ref} — opens {window['start']}"
        )
    if state == "missed":
        return state, (
            f"  FIRST-PRINT WINDOW MISSED (refusing): {ref} — registered "
            f"window closed {window['end']}; no release-time witnessed or "
            "versioned first-print custody is registered"
        )
    return state, None


INTL_ADAPTER_CANDIDATES: dict[str, dict[str, Any]] = {
    # Canada (two CPI dataPointId dialects name the same fact)
    "statcan.cpi.all_items_annual_rate.canada": _STATCAN_CPI_SPEC,
    "statcan.cpi.allitems.yoy": _STATCAN_CPI_SPEC,
    "statcan.gdp_by_industry.monthly_growth": _STATCAN_GDP_SPEC,
    "statcan.36-10-0434-01.all_industries.month_to_month_percent_change": (
        _STATCAN_GDP_SPEC
    ),
    "statcan.employment_insurance.regular_beneficiaries.canada": _STATCAN_EI_SPEC,
    "statcan.employment_insurance.regular_beneficiaries": _STATCAN_EI_SPEC,
    "statcan.lfs.unemployment_rate.canada": _STATCAN_LFS_UR_SPEC,
    "statcan.lfs.employment_change.canada": _STATCAN_LFS_EMP_SPEC,
    # Australia (three CPI dialects: recorded wave, live-comparison, docket)
    "abs.cpi.all_groups_annual_rate.australia": _ABS_CPI_SPEC,
    "abs.cpi_indicator.allgroups.yoy": _ABS_CPI_SPEC,
    "abs.cpi.all_groups.yoy": _ABS_CPI_SPEC,
    "abs.labour.unemployment_rate.australia": _ABS_UR_SPEC,
    "abs.labour.unemployment_rate": _ABS_UR_SPEC,
    "abs.labour.employment_change.australia": _ABS_EMP_SPEC,
    "abs.building_approvals.total_dwellings_mom.australia": _ABS_BA_SPEC,
    # Euro area (two flash HICP dialects name the same fact)
    "eurostat.hicp.all_items_annual_rate.euro_area": _EUROSTAT_HICP_SPEC,
    "eurostat.ea.hicp.flash.yoy": _EUROSTAT_HICP_SPEC,
    "eurostat.hicp.flash.yoy": _EUROSTAT_HICP_SPEC,
    "eurostat.unemployment_rate.euro_area": _EUROSTAT_UNEMP_SPEC,
    "eurostat.unemployment_rate": _EUROSTAT_UNEMP_SPEC,
    "eurostat.construction.production_index": _EUROSTAT_CONSTRUCTION_SPEC,
    "eurostat.retail_trade.volume_mom.euro_area": _EUROSTAT_RETAIL_SPEC,
    # United Kingdom
    "ons.cpi.annual_rate": _ONS_CPI_SPEC,
    "ons.labour.claimant_count": _ONS_CLAIMANT_SPEC,
    "ons.retail_sales.volume_mom": _ONS_RETAIL_SPEC,
    "ons.pusf.j5ii.public_sector_net_borrowing_ex_banks": _ONS_PSNB_SPEC,
}

# Only pairs that reproduced at least three official first prints from real
# captured payload bytes are executable. The remaining fully specified
# candidates stay visible for audit and future admission once their immutable
# release payloads are captured; they are deliberately not claimed.
_INTL_ADMITTED_STEMS = {
    "abs.cpi.all_groups_annual_rate.australia",
    "abs.cpi.all_groups.yoy",
    "abs.cpi_indicator.allgroups.yoy",
    "abs.labour.unemployment_rate",
    "abs.labour.unemployment_rate.australia",
    "eurostat.ea.hicp.flash.yoy",
    "eurostat.hicp.all_items_annual_rate.euro_area",
    "eurostat.hicp.flash.yoy",
    "statcan.36-10-0434-01.all_industries.month_to_month_percent_change",
    "statcan.cpi.all_items_annual_rate.canada",
    "statcan.cpi.allitems.yoy",
    "statcan.gdp_by_industry.monthly_growth",
}
INTL_ADAPTERS: dict[str, dict[str, Any]] = {
    stem: spec
    for stem, spec in INTL_ADAPTER_CANDIDATES.items()
    if stem in _INTL_ADMITTED_STEMS
}
INTL_BLOCKED_ADAPTERS: dict[str, dict[str, Any]] = {
    stem: spec
    for stem, spec in INTL_ADAPTER_CANDIDATES.items()
    if stem not in _INTL_ADMITTED_STEMS
}
INTL_REGISTRY_ADAPTERS: dict[str, dict[str, Any]] = {
    "abs.cpi.all_groups.yoy": _ABS_CPI_SPEC,
    "abs.labour.unemployment_rate": _ABS_UR_SPEC,
    "eurostat.hicp.flash.yoy": _EUROSTAT_HICP_SPEC,
    "statcan.cpi.allitems.yoy": _STATCAN_CPI_SPEC,
    "statcan.gdp_by_industry.monthly_growth": _STATCAN_GDP_SPEC,
}

# One legacy registration is safe to execute with a native parser even though
# it predates the adapter enum: its immutable contract already pins the exact
# ABS dataflow/key URL, field family, identity transform, unit, host set, and
# first-print window. The complete contract and target hash are both checked,
# so this is not a generic-url compatibility escape hatch. Other legacy
# international registrations remain refused unless individually reviewed and
# added here.
LEGACY_INTL_EXECUTOR_CONTRACTS: dict[str, dict[str, Any]] = {
    "cf3a2f76bb15d9f5eb9f5ae19d2e96b55111cf6842a1c8c8412b915ae614a85b": {
        "catalogSlug": "australia-unemployment-rate-july-2026",
        "country": "AU",
        "dataPointId": ("abs.labour.unemployment_rate.australia.july_2026.first_print"),
        "period": "2026-07",
        "series": "abs.labour.unemployment_rate",
        "sourceBinding": {
            "adapter": "generic-url",
            "allowedHosts": ["data.api.abs.gov.au", "www.abs.gov.au"],
            "expectedReleaseWindow": {
                "end": "2026-08-27",
                "start": "2026-08-19",
            },
            "field": "M13",
            "releasePolicy": "first_print",
            "sourceSeriesId": "LF/M13.3.1599.20.AUS.M",
            "sourceUrl": (
                "https://data.api.abs.gov.au/rest/data/"
                "LF/M13.3.1599.20.AUS.M?format=jsondata"
            ),
            "table": (
                "Labour Force, Australia (dataflow LF): unemployment rate, "
                "persons, seasonally adjusted; first print captured on "
                "release day"
            ),
            "transform": {"factor": 1, "operation": "multiply"},
        },
        "unit": "percent",
        "valueScale": 1,
    },
}


def longest_adapter_stem(ref: str, adapters: dict[str, dict[str, Any]]) -> str | None:
    """Return the most-specific matching stem, independent of dict order."""
    matches = [stem for stem in adapters if ref.startswith(stem + ".")]
    return max(matches, key=len, default=None)








def intl_execution_spec(
    registration: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any] | None:
    """Return a native execution spec for an exact current or legacy contract.

    Current registrations must byte-match the committed seven-key adapter
    template. A legacy registration is executable only when both its canonical
    content hash and its complete contract match a reviewed fingerprint.
    """
    contract = registration.get("contract")
    if not isinstance(contract, dict):
        return None
    binding = contract.get("sourceBinding")
    if not isinstance(binding, dict):
        return None
    # A matching seven-key binding is not enough on its own: the immutable
    # contract must also name the canonical registry series for this exact
    # parser spec. Otherwise an unrelated target could borrow a valid binding
    # and be resolved by the wrong series implementation.
    registry_spec = INTL_REGISTRY_ADAPTERS.get(str(contract.get("series")))
    if registry_spec is not spec:
        return None
    if not intl_binding_mismatches(spec, binding):
        return {**spec, "target_series": contract.get("series")}

    content_hash = registration.get("targetContentHash")
    legacy_contract = LEGACY_INTL_EXECUTOR_CONTRACTS.get(str(content_hash))
    if (
        legacy_contract is None
        or contract != legacy_contract
        or spec.get("series_id") != _ABS_UR_SPEC["series_id"]
    ):
        return None
    return {
        **spec,
        "target_series": contract["series"],
        "request_url": binding["sourceUrl"],
        "allowed_hosts": tuple(binding["allowedHosts"]),
        "legacy_target_content_hash": content_hash,
    }


def adapter_unit_matches(
    spec: dict[str, Any], forecast_entry: dict[str, Any] | None
) -> bool:
    unit = (forecast_entry or {}).get("unit")
    return unit == spec["unit"]


def sba_pdf_binding_template(spec: Mapping[str, Any]) -> dict[str, Any]:
    """The exact reviewed registration binding for one SBA PDF series."""

    return {
        "adapter": SBA_BINDING_ADAPTER,
        "sourceUrl": SBA_ANNOUNCEMENT_URL,
        "sourceSeriesId": spec["series_id"],
        "field": spec["field"],
        "table": spec["source_table"],
        "transform": {"operation": "identity", "factor": 1},
        "releasePolicy": "first_print",
    }


def sba_pdf_binding_matches_spec(
    binding: Mapping[str, Any], spec: Mapping[str, Any]
) -> bool:
    """Reject adapter-name matches whose source/table/cell contract drifted."""

    if not isinstance(binding, dict):
        return False
    if set(binding) - SBA_BINDING_DERIVED_KEYS != SBA_BINDING_TEMPLATE_KEYS:
        return False
    projected = {key: binding[key] for key in SBA_BINDING_TEMPLATE_KEYS}
    return canonical_bytes(projected) == canonical_bytes(sba_pdf_binding_template(spec))


def _sba_refusal(prefix: str, reason: str) -> tuple[None, str]:
    return None, f"{prefix} {reason}"


def _sba_capture_directories(records: pathlib.Path) -> list[pathlib.Path]:
    if not records.is_dir():
        return []
    return sorted(records.glob("*/*-sba-pdf-witness"))


def _sba_manifest(run_dir: pathlib.Path) -> dict[str, Any]:
    if run_dir.is_symlink():
        raise ValueError(f"capture directory is a symlink: {run_dir}")
    manifest_path = run_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"capture manifest cannot be read: {run_dir}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"capture manifest is not an object: {run_dir}")
    if (
        manifest.get("schemaVersion") != SBA_WITNESS_SCHEMA
        or manifest.get("runMode") != SBA_WITNESS_RUN_MODE
    ):
        raise ValueError(f"capture manifest identity drifted: {run_dir}")
    return manifest


def _sba_capture_introducing_commit(
    records: pathlib.Path,
    run_dir: pathlib.Path,
) -> str:
    """Bind the current custody run to the sole commit that introduced it."""

    repo_root = records.resolve().parent
    try:
        run_relative = run_dir.resolve().relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise ValueError("capture directory is outside the repository") from exc
    manifest_relative = f"{run_relative}/manifest.json"
    completed = subprocess.run(
        [
            "git",
            "log",
            "--full-history",
            "--diff-filter=A",
            "--format=%H",
            "HEAD",
            "--",
            manifest_relative,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"git exited {completed.returncode}"
        raise ValueError(f"cannot inspect capture history: {detail}")
    commits = [line for line in completed.stdout.splitlines() if line]
    if len(commits) != 1 or not re.fullmatch(r"[0-9a-f]{40}", commits[0]):
        raise ValueError(
            "capture manifest must have exactly one introducing commit on "
            f"HEAD history; found {len(commits)}"
        )
    introducing_commit = commits[0]

    committed = subprocess.run(
        ["git", "show", f"{introducing_commit}:{manifest_relative}"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if committed.returncode != 0:
        detail = committed.stderr.decode(errors="replace").strip()
        raise ValueError(f"cannot read introducing capture manifest: {detail}")
    try:
        current_manifest = (run_dir / "manifest.json").read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read current capture manifest: {exc}") from exc
    if committed.stdout != current_manifest:
        raise ValueError("current capture manifest differs from its introducing commit")

    unchanged = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            introducing_commit,
            "HEAD",
            "--",
            run_relative,
        ],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if unchanged.returncode == 1:
        raise ValueError("capture run changed after its introducing commit")
    if unchanged.returncode != 0:
        detail = unchanged.stderr.decode(errors="replace").strip()
        raise ValueError(f"cannot compare capture history: {detail}")
    return introducing_commit


def _sba_verify_capture_attestation(commit: str) -> str:
    """Require the SBA witness workflow's attestation for one exact commit."""

    repository = records_provenance.repository_slug()
    era = records_provenance.era_repository(commit, repository)
    return records_provenance.verify_commit(
        commit,
        repository,
        era,
        allowed_workflows={SBA_WITNESS_WORKFLOW},
    )


def _sba_proof_time(proof: Mapping[str, Any]) -> dt.datetime:
    earliest = proof.get("earliestWitnessedAt")
    tsa_time = proof.get("tsaGenTime")
    if not isinstance(earliest, str) or earliest != tsa_time:
        raise ValueError("timeline proof has inconsistent witnessed times")
    try:
        parsed = dt.datetime.fromisoformat(earliest.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timeline proof has an invalid witnessed time") from exc
    if parsed.tzinfo is None:
        raise ValueError("timeline proof witnessed time is not timezone-aware")
    if not isinstance(proof.get("witnessDigest"), str) or not isinstance(
        proof.get("coverage"), str
    ):
        raise ValueError("timeline proof is missing witness identity")
    return parsed


def _sba_candidate_proof(
    timeline: Mapping[str, Any],
    *,
    run_directory: str,
    custody_root_sha256: str,
) -> dict[str, Any] | None:
    runs = timeline.get("runs")
    roots = timeline.get("custodyRoots")
    if not isinstance(runs, Mapping) or not isinstance(roots, Mapping):
        raise ValueError("witnessed timeline lacks run/root indexes")
    run_proof = runs.get(run_directory)
    root_proof = roots.get(custody_root_sha256)
    if run_proof is None and root_proof is None:
        return None
    if not isinstance(run_proof, Mapping) or not isinstance(root_proof, Mapping):
        raise ValueError("witnessed timeline covers only part of a custody run")
    _sba_proof_time(run_proof)
    _sba_proof_time(root_proof)
    identity_keys = ("earliestWitnessedAt", "witnessDigest", "tsaGenTime")
    if any(run_proof.get(key) != root_proof.get(key) for key in identity_keys):
        raise ValueError("run and custody-root witness proofs disagree")
    return dict(run_proof)


def _sba_archive_path(run_dir: pathlib.Path, logical: Any) -> pathlib.Path:
    if not isinstance(logical, str) or not logical:
        raise ValueError("capture archive path is absent")
    path = (run_dir / logical).resolve()
    try:
        path.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError("capture archive path escapes its run") from exc
    if path.is_symlink() or not path.is_file():
        raise ValueError("capture archive is missing or symlinked")
    return path


def _sba_bundle_period_coverage(
    bundle: Mapping[str, Any],
) -> tuple[set[int], set[int]]:
    """Validate filename-derived coverage without consulting parsed PDF cells."""

    bundle_year = bundle.get("fiscalYear")
    quarter = bundle.get("quarter")
    if (
        type(bundle_year) is not int
        or type(quarter) is not int
        or quarter not in range(1, 5)
    ):
        raise ValueError("capture has an unrecognized bundle identity")
    displayed = list(range(bundle_year - 9, bundle_year + 1))
    completed_stop = bundle_year + 1 if quarter == 4 else bundle_year
    possible_completed = list(range(bundle_year - 9, completed_stop))
    expected = {
        "periodType": "fiscal_year",
        "displayedFiscalYears": displayed,
        "possibleCompletedFiscalYears": possible_completed,
    }
    if bundle.get("periodCoverage") != expected:
        raise ValueError("capture period coverage disagrees with its bundle identity")
    return set(displayed), set(possible_completed)


def _sba_report_completed_years(
    bundle: Mapping[str, Any],
    *,
    series: str,
    displayed: set[int],
    possible_completed: set[int],
) -> tuple[set[int], str]:
    """Refine pre-parse coverage with one successfully parsed report footer."""

    reports = bundle.get("reports")
    matching = (
        [report for report in reports if report.get("series") == series]
        if isinstance(reports, list)
        and all(isinstance(report, dict) for report in reports)
        else []
    )
    if len(matching) != 1:
        raise ValueError(f"capture has {len(matching)} report entries for {series}")
    report = matching[0]
    header_years = report.get("headerYears")
    if (
        not isinstance(header_years, list)
        or not all(type(year) is int for year in header_years)
        or header_years != sorted(displayed)
    ):
        raise ValueError("parsed report header coverage disagrees with its bundle")
    completion_status = report.get("completionStatus")
    partial_fiscal_year = report.get("partialFiscalYear")
    if completion_status == COMPLETION_PARTIAL:
        if partial_fiscal_year != header_years[-1]:
            raise ValueError(
                "parsed report partial fiscal year disagrees with its header"
            )
        completed = set(header_years[:-1])
    elif completion_status == COMPLETION_COMPLETED:
        if partial_fiscal_year is not None:
            raise ValueError(
                "parsed completed report unexpectedly names a partial fiscal year"
            )
        completed = set(header_years)
    else:
        raise ValueError("parsed report has an unrecognized completion status")
    if not completed <= possible_completed:
        raise ValueError(
            "parsed report completion status exceeds filename-derived coverage"
        )
    return completed, completion_status


def _replay_sba_candidate(
    candidate: _SbaPdfCandidate,
    *,
    series: str,
    fiscal_year: int,
) -> tuple[SbaPdfResolution | None, str | None]:
    bundle = candidate.manifest.get("bundle")
    if not isinstance(bundle, dict):
        return _sba_refusal(SBA_CUSTODY_INVALID, "complete capture lacks a bundle")
    source = candidate.manifest.get("source")
    if not isinstance(source, dict):
        return _sba_refusal(SBA_CUSTODY_INVALID, "capture source identity is absent")
    if source.get("entryUrl") != SBA_ENTRY_URL:
        return _sba_refusal(SBA_CUSTODY_INVALID, "capture landing URL drifted")
    if (
        source.get("parserContract") != SBA_PARSER_CONTRACT
        or bundle.get("parserContract") != SBA_PARSER_CONTRACT
    ):
        return _sba_refusal(SBA_CUSTODY_INVALID, "capture parser identity drifted")
    archive = bundle.get("zipArchive")
    if not isinstance(archive, dict):
        return _sba_refusal(
            SBA_CUSTODY_INVALID, "complete capture lacks its ZIP archive reference"
        )
    try:
        archive_path = _sba_archive_path(candidate.run_dir, archive.get("path"))
        raw_bundle = gzip.decompress(archive_path.read_bytes())
    except (OSError, EOFError, gzip.BadGzipFile, ValueError) as exc:
        return _sba_refusal(SBA_CUSTODY_INVALID, f"ZIP archive replay failed: {exc}")
    if hashlib.sha256(raw_bundle).hexdigest() != archive.get("rawSha256") or len(
        raw_bundle
    ) != archive.get("rawBytes"):
        return _sba_refusal(
            SBA_CUSTODY_INVALID, "replayed ZIP bytes disagree with the manifest"
        )

    if candidate.manifest.get("outcome") == "failed":
        failure = candidate.manifest.get("failure")
        reason = failure.get("reason") if isinstance(failure, dict) else None
        if not isinstance(reason, str):
            return _sba_refusal(
                SBA_CUSTODY_INVALID,
                "retained failed capture lacks its replayed refusal",
            )
        for prefix in (SBA_LAYOUT_REFUSAL, SBA_PARTIAL_REFUSAL, SBA_PARSER_REFUSAL):
            if prefix in reason:
                return None, reason[reason.index(prefix) :]
        return _sba_refusal(
            SBA_CUSTODY_INVALID,
            "earliest covered capture failed strict bundle validation: " + reason,
        )

    reports = bundle.get("reports")
    matching = (
        [report for report in reports if report.get("series") == series]
        if isinstance(reports, list)
        and all(isinstance(report, dict) for report in reports)
        else []
    )
    if len(matching) != 1:
        return _sba_refusal(
            SBA_CUSTODY_INVALID,
            f"capture has {len(matching)} report entries for {series}",
        )
    report = matching[0]
    try:
        displayed, possible_completed = _sba_bundle_period_coverage(bundle)
        completed_years, completion_status = _sba_report_completed_years(
            bundle,
            series=series,
            displayed=displayed,
            possible_completed=possible_completed,
        )
    except ValueError as exc:
        return _sba_refusal(SBA_CUSTODY_INVALID, str(exc))
    member_path = report.get("memberPath")
    if not isinstance(member_path, str):
        return _sba_refusal(SBA_CUSTODY_INVALID, "report member path is absent")
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bundle)) as archive_zip:
            member = archive_zip.read(member_path)
    except (KeyError, OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        return _sba_refusal(SBA_CUSTODY_INVALID, f"PDF member replay failed: {exc}")
    if hashlib.sha256(member).hexdigest() != report.get("memberSha256") or len(
        member
    ) != report.get("memberBytes"):
        return _sba_refusal(
            SBA_CUSTODY_INVALID, "replayed PDF bytes disagree with the manifest"
        )

    cell, refusal = parse_sba_loan_performance_pdf(
        member, series=series, fiscal_year=fiscal_year
    )
    if refusal:
        if not refusal.startswith(
            (SBA_LAYOUT_REFUSAL, SBA_PARTIAL_REFUSAL, SBA_PARSER_REFUSAL)
        ):
            return _sba_refusal(
                SBA_CUSTODY_INVALID,
                f"strict parser returned an unknown refusal: {refusal}",
            )
        return None, refusal
    if not isinstance(cell, SbaLoanPerformanceCell):
        return _sba_refusal(SBA_CUSTODY_INVALID, "strict parser returned no cell")
    if (
        fiscal_year not in completed_years
        or cell.completion_status != completion_status
    ):
        return _sba_refusal(
            SBA_CUSTODY_INVALID,
            "replayed report completion status disagrees with the manifest",
        )

    normalized_unit = "usd" if cell.unit == "USD" else cell.unit
    spec = SBA_PDF_ADAPTERS[series]
    if normalized_unit != spec["unit"]:
        return _sba_refusal(
            SBA_CUSTODY_INVALID,
            f"parsed unit {cell.unit!r} does not match {spec['unit']!r}",
        )
    proof = candidate.proof
    if proof is None:
        return _sba_refusal(
            SBA_CUSTODY_UNWITNESSED, "capture lacks an available timeline proof"
        )
    if candidate.introducing_commit is None or candidate.attestation_signer is None:
        return _sba_refusal(
            SBA_CUSTODY_INVALID,
            "capture reached replay without its commit attestation binding",
        )

    fetch_path = _sba_archive_path(
        candidate.run_dir, candidate.manifest.get("fetchEventPath")
    )
    try:
        fetch_event = json.loads(fetch_path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _sba_refusal(SBA_CUSTODY_INVALID, f"fetch event replay failed: {exc}")
    landing = fetch_event.get("landing") if isinstance(fetch_event, dict) else None
    landing_final = landing.get("finalUrl") if isinstance(landing, dict) else None

    provenance = {
        "custodyMode": "earliest_witnessed_capture",
        "runDirectory": candidate.run_directory,
        "landingUrl": source.get("entryUrl"),
        "landingFinalUrl": landing_final,
        "assetUrl": bundle.get("assetUrl"),
        "zipSha256": archive.get("rawSha256"),
        "memberPath": member_path,
        "memberSha256": report.get("memberSha256"),
        "custodyRootSha256": candidate.custody_root_sha256,
        "introducingCommit": candidate.introducing_commit,
        "attestationSigner": candidate.attestation_signer,
        "witnessDigest": proof.get("witnessDigest"),
        "earliestWitnessedAt": proof.get("earliestWitnessedAt"),
        "tsaGenTime": proof.get("tsaGenTime"),
        "witnessCoverage": proof.get("coverage"),
        "tableTitle": cell.table_title,
        "section": "Disaster",
        "row": "Disaster",
        "fiscalYear": fiscal_year,
        "printedValue": cell.printed_value,
        "unit": normalized_unit,
        "reportCompletionStatus": cell.completion_status,
        "partialFiscalYear": cell.partial_fiscal_year,
        "parserContract": source.get("parserContract"),
    }
    source_url = bundle.get("assetUrl")
    if not isinstance(source_url, str):
        return _sba_refusal(SBA_CUSTODY_INVALID, "capture asset URL is absent")
    return (
        SbaPdfResolution(
            value=cell.value,
            unit=normalized_unit,
            raw_bundle=raw_bundle,
            run_directory=candidate.run_directory,
            source_url=source_url,
            member_path=member_path,
            provenance=provenance,
        ),
        None,
    )


def resolve_sba_pdf_first_print(
    records: pathlib.Path,
    *,
    series: str,
    fiscal_year: int,
    timeline: Mapping[str, Any] | None = None,
) -> tuple[SbaPdfResolution | None, str | None]:
    """Replay the earliest witnessed covered SBA ZIP, never later/live bytes."""

    if series not in SBA_PDF_ADAPTERS:
        raise ValueError(f"unsupported SBA loan-performance series {series!r}")
    if type(fiscal_year) is not int:
        raise TypeError("fiscal_year must be an integer")
    records = records.resolve()
    if timeline is None:
        try:
            timeline = extract_timeline(records)
        except (OSError, TimelineError, ValueError) as exc:
            return _sba_refusal(
                SBA_CUSTODY_INVALID,
                f"witnessed record timeline does not verify: {exc}",
            )
    run_dirs = _sba_capture_directories(records)
    if not run_dirs:
        return _sba_refusal(
            SBA_CUSTODY_ABSENT,
            f"no dedicated capture exists for {series} fiscal year {fiscal_year}",
        )

    physical: list[_SbaPdfCandidate] = []
    for run_dir in run_dirs:
        try:
            manifest = _sba_manifest(run_dir)
            verification = verify_run(run_dir)
        except (CustodyError, OSError, ValueError) as exc:
            if SBA_PARSER_REFUSAL in str(exc):
                return None, str(exc)[str(exc).index(SBA_PARSER_REFUSAL) :]
            return _sba_refusal(
                SBA_CUSTODY_INVALID, f"capture verification failed: {run_dir}: {exc}"
            )
        if verification.run_mode != SBA_WITNESS_RUN_MODE:
            continue
        outcome = manifest.get("outcome")
        successful_bundle = outcome in {"bootstrap", "changed"} and (
            manifest.get("ok") is True
        )
        failure = manifest.get("failure")
        retained_failed_bundle = (
            outcome == "failed"
            and manifest.get("ok") is False
            and isinstance(failure, dict)
            and failure.get("stage") == "bundle validation"
            and isinstance(manifest.get("bundle"), dict)
        )
        if not successful_bundle and not retained_failed_bundle:
            continue
        bundle = manifest.get("bundle")
        if not isinstance(bundle, dict):
            return _sba_refusal(SBA_CUSTODY_INVALID, "covered capture lacks a bundle")
        try:
            displayed, possible_completed = _sba_bundle_period_coverage(bundle)
            completed = (
                _sba_report_completed_years(
                    bundle,
                    series=series,
                    displayed=displayed,
                    possible_completed=possible_completed,
                )[0]
                if successful_bundle
                else possible_completed
            )
        except ValueError as exc:
            return _sba_refusal(SBA_CUSTODY_INVALID, str(exc))
        if fiscal_year not in displayed:
            continue
        run_directory = run_dir.relative_to(records.parent).as_posix()
        physical.append(
            _SbaPdfCandidate(
                run_dir=run_dir,
                run_directory=run_directory,
                manifest=manifest,
                custody_root_sha256=verification.custody_root_sha256,
                proof=None,
                partial_only=fiscal_year not in completed,
            )
        )
    if not physical:
        return _sba_refusal(
            SBA_CUSTODY_ABSENT,
            f"no retained capture covers {series} fiscal year {fiscal_year}",
        )

    candidates: list[_SbaPdfCandidate] = []
    try:
        for candidate in physical:
            proof = _sba_candidate_proof(
                timeline,
                run_directory=candidate.run_directory,
                custody_root_sha256=candidate.custody_root_sha256,
            )
            candidates.append(
                _SbaPdfCandidate(
                    run_dir=candidate.run_dir,
                    run_directory=candidate.run_directory,
                    manifest=candidate.manifest,
                    custody_root_sha256=candidate.custody_root_sha256,
                    proof=proof,
                    partial_only=candidate.partial_only,
                )
            )
    except ValueError as exc:
        return _sba_refusal(SBA_CUSTODY_INVALID, f"timeline proof is invalid: {exc}")

    complete = [candidate for candidate in candidates if not candidate.partial_only]
    witnessed = [candidate for candidate in complete if candidate.proof is not None]
    if not witnessed:
        if complete:
            return _sba_refusal(
                SBA_CUSTODY_UNWITNESSED,
                "complete capture exists without an available proof for "
                f"fiscal year {fiscal_year}",
            )
        witnessed = [
            candidate for candidate in candidates if candidate.proof is not None
        ]
        if not witnessed:
            return _sba_refusal(
                SBA_CUSTODY_UNWITNESSED,
                "matching capture bytes lack an available proof for "
                f"fiscal year {fiscal_year}",
            )

    try:
        earliest_time = min(
            _sba_proof_time(candidate.proof or {}) for candidate in witnessed
        )
        earliest = [
            candidate
            for candidate in witnessed
            if _sba_proof_time(candidate.proof or {}) == earliest_time
        ]
    except ValueError as exc:
        return _sba_refusal(SBA_CUSTODY_INVALID, f"timeline proof is invalid: {exc}")

    attested_earliest: list[_SbaPdfCandidate] = []
    for candidate in sorted(earliest, key=lambda item: item.run_directory):
        try:
            introducing_commit = _sba_capture_introducing_commit(
                records, candidate.run_dir
            )
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return _sba_refusal(
                SBA_CUSTODY_INVALID,
                f"capture introducing-commit binding failed: {exc}",
            )
        try:
            signer = _sba_verify_capture_attestation(introducing_commit)
        except (
            OSError,
            records_provenance.ProvenanceError,
            subprocess.SubprocessError,
            ValueError,
        ):
            return _sba_refusal(
                SBA_CUSTODY_UNATTESTED,
                f"capture introducing commit is not attested by {SBA_WITNESS_WORKFLOW}",
            )
        attested_earliest.append(
            replace(
                candidate,
                introducing_commit=introducing_commit,
                attestation_signer=signer,
            )
        )

    replayed: list[SbaPdfResolution] = []
    for candidate in attested_earliest:
        resolution, refusal = _replay_sba_candidate(
            candidate, series=series, fiscal_year=fiscal_year
        )
        if refusal:
            return None, refusal
        assert resolution is not None
        replayed.append(resolution)
    normalized = {(item.value, item.unit) for item in replayed}
    if len(normalized) != 1:
        return _sba_refusal(
            SBA_EARLIEST_CAPTURE_AMBIGUOUS,
            f"{len(replayed)} earliest captures disagree for fiscal year {fiscal_year}",
        )

    chosen = min(
        replayed,
        key=lambda item: (str(item.provenance["zipSha256"]), item.run_directory),
    )
    provenance = {
        **chosen.provenance,
        "equivalentCaptures": [
            {
                key: item.provenance[key]
                for key in (
                    "runDirectory",
                    "zipSha256",
                    "memberSha256",
                    "custodyRootSha256",
                    "introducingCommit",
                    "attestationSigner",
                    "witnessDigest",
                )
            }
            for item in replayed
        ],
    }
    return (
        SbaPdfResolution(
            value=chosen.value,
            unit=chosen.unit,
            raw_bundle=chosen.raw_bundle,
            run_directory=chosen.run_directory,
            source_url=chosen.source_url,
            member_path=chosen.member_path,
            provenance=provenance,
        ),
        None,
    )


def intl_value_valid(spec: dict[str, Any], value: float) -> bool:
    """Schema/unit-scale gate independent of the forecast being scored."""
    if not math.isfinite(value):
        return False
    lower, upper = spec.get("valid_range", (-math.inf, math.inf))
    return lower <= value <= upper


def _url_host(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ValueError(f"source URL must use HTTPS: {url!r}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError(f"source URL has no host: {url!r}")
    return host


def _require_allowed_host(url: str, allowed_hosts: list[str] | tuple[str, ...]) -> None:
    host = _url_host(url)
    if host not in allowed_hosts:
        raise ValueError(
            f"source host {host!r} is not in adapter allowlist "
            f"{sorted(allowed_hosts)!r}"
        )


class _PinnedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validate every redirect destination before urllib connects to it."""

    def __init__(self, allowed_hosts: list[str] | tuple[str, ...]) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        _require_allowed_host(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_request(
    request: urllib.request.Request,
    *,
    allowed_hosts: list[str] | tuple[str, ...],
    timeout: int = 120,
) -> tuple[bytes, str, str]:
    """Fetch raw bytes while pinning both request and redirect destinations."""
    _require_allowed_host(request.full_url, allowed_hosts)
    retrieved_at = utc_now()
    opener = urllib.request.build_opener(_PinnedRedirectHandler(allowed_hosts))
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        _require_allowed_host(final_url, allowed_hosts)
        return response.read(), retrieved_at, final_url


def http_get(
    url: str,
    *,
    allowed_hosts: list[str] | tuple[str, ...],
    timeout: int = 120,
) -> tuple[bytes, str, str]:
    """Fetch raw bytes with the resolver UA and a pinned host allowlist."""
    request = urllib.request.Request(url, headers={"User-Agent": INTL_USER_AGENT})
    return http_request(request, allowed_hosts=allowed_hosts, timeout=timeout)


def fetch_first(
    urls: list[str], *, allowed_hosts: list[str] | tuple[str, ...]
) -> tuple[bytes, str, str]:
    """Try pinned URLs in order; returns (bytes, url, retrievedAt)."""
    last_error: Exception | None = None
    for url in urls:
        try:
            raw, retrieved_at, final_url = http_get(url, allowed_hosts=allowed_hosts)
            return raw, final_url, retrieved_at
        except Exception as exc:  # noqa: BLE001 - next pin is the fallback
            last_error = exc
    raise RuntimeError(f"all pinned URLs failed (last: {last_error})")




def statcan_series(
    vector: int,
    *,
    latest_n: int,
    allowed_hosts: list[str] | tuple[str, ...],
) -> tuple[dict[str, float], bytes, str, str]:
    """StatCan WDS latest-N POST; archive its vector-identifying response."""
    body = json.dumps(
        [{"vectorId": int(vector), "latestN": int(latest_n)}],
        separators=(",", ":"),
    ).encode()
    request = urllib.request.Request(
        STATCAN_WDS_LATEST,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": INTL_USER_AGENT,
        },
        method="POST",
    )
    raw, retrieved_at, url = http_request(request, allowed_hosts=allowed_hosts)
    return statcan_series_from_payload(raw, vector), raw, url, retrieved_at






def abs_series(
    flow: str,
    key: str,
    *,
    latest_n: int,
    allowed_hosts: list[str] | tuple[str, ...],
) -> tuple[dict[str, float], bytes, str, str]:
    """ABS Data API (SDMX-JSON 2.0) single-series values."""
    url = ABS_DATA_URL.format(flow=flow, key=key, last_n=latest_n)
    raw, retrieved_at, final_url = http_get(url, allowed_hosts=allowed_hosts)
    series = abs_series_from_payload(raw, flow, key)
    return series, raw, final_url, retrieved_at


def eurostat_series_from_payload(
    raw: bytes, dataset: str, key: str
) -> tuple[dict[str, float], dict[str, str]]:
    """Parse Eurostat JSON-stat values and per-period status flags."""
    payload = json.loads(raw.decode())
    if "dimension" not in payload:
        raise ValueError(f"eurostat {dataset}/{key}: {str(payload)[:160]}")
    extension = payload.get("extension")
    response_dataset = extension.get("id") if isinstance(extension, dict) else None
    if str(response_dataset or "").lower() != dataset.lower():
        raise ValueError(
            f"Eurostat returned dataset {response_dataset!r}, expected {dataset!r}"
        )
    dimension_ids = payload.get("id")
    if not isinstance(dimension_ids, list) or "time" not in dimension_ids:
        raise ValueError(f"Eurostat {dataset}/{key}: dimension ids drifted")
    series_dimension_ids = [
        dimension_id for dimension_id in dimension_ids if dimension_id != "time"
    ]
    key_parts = key.split(".")
    if len(series_dimension_ids) != len(key_parts):
        raise ValueError(f"Eurostat {dataset}/{key}: key shape drifted")
    for dimension_id, expected in zip(series_dimension_ids, key_parts, strict=True):
        index = (
            payload["dimension"].get(dimension_id, {}).get("category", {}).get("index")
        )
        if not isinstance(index, dict) or set(index) != {expected}:
            actual = sorted(index) if isinstance(index, dict) else index
            raise ValueError(
                f"Eurostat {dataset}/{key}: dimension {dimension_id} "
                f"is {actual!r}, expected {[expected]!r}"
            )
    index_to_period = {
        v: k for k, v in payload["dimension"]["time"]["category"]["index"].items()
    }
    series = {
        normalize_sdmx_period(index_to_period[int(flat)]): float(value)
        for flat, value in payload["value"].items()
    }
    status = payload.get("status")
    flags: dict[str, str] = {}
    if isinstance(status, dict):
        flags = {
            normalize_sdmx_period(index_to_period[int(flat)]): str(flag)
            for flat, flag in status.items()
            if int(flat) in index_to_period
        }
    return series, flags


def eurostat_series(
    dataset: str,
    key: str,
    *,
    latest_n: int,
    allowed_hosts: list[str] | tuple[str, ...],
) -> tuple[dict[str, float], dict[str, str], bytes, str, str]:
    """Eurostat dissemination API JSON-stat values and status flags."""
    url = EUROSTAT_DATA_URL.format(dataset=dataset, key=key, last_n=latest_n)
    raw, retrieved_at, final_url = http_get(url, allowed_hosts=allowed_hosts)
    series, flags = eurostat_series_from_payload(raw, dataset, key)
    return series, flags, raw, final_url, retrieved_at


def ons_series_from_payload(raw: bytes, series_id: str) -> dict[str, float]:
    """Parse the monthly observations returned by the keyless ONS v1 API."""
    payload = json.loads(raw.decode())
    months = payload.get("months")
    if not isinstance(months, list):
        raise ValueError(f"ONS {series_id}: response has no months array")
    series: dict[str, float] = {}
    for point in months:
        if not isinstance(point, dict):
            continue
        date_label = str(point.get("date") or "").strip().upper()
        match = re.fullmatch(r"(\d{4}) ([A-Z]{3})", date_label)
        if not match or match.group(2).lower() not in MONTH_ABBREVIATION_NUMBERS:
            continue
        raw_value = point.get("value")
        if raw_value in (None, "", ".."):
            continue
        series[
            f"{match.group(1)}-{MONTH_ABBREVIATION_NUMBERS[match.group(2).lower()]:02d}"
        ] = float(str(raw_value).replace(",", ""))
    if not series:
        raise ValueError(f"ONS {series_id}: no numeric monthly observations")
    return series


def ons_series(
    uri: str,
    series_id: str,
    *,
    allowed_hosts: list[str] | tuple[str, ...],
) -> tuple[dict[str, float], bytes, str, str]:
    """Fetch one keyless ONS v1 time-series JSON document."""
    url = ONS_DATA_URL.format(uri=uri)
    raw, retrieved_at, final_url = http_get(url, allowed_hosts=allowed_hosts)
    return ons_series_from_payload(raw, series_id), raw, final_url, retrieved_at


MONTH_NAMES = {number: name.capitalize() for name, number in MONTH_NUMBERS.items()}


def eurostat_retail_headline(raw: bytes, period: str) -> float | None:
    """Signed euro-area MoM % from a retail-trade release page snapshot."""
    text = re.sub(r"<[^>]+>", " ", raw.decode("utf-8", errors="replace"))
    text = re.sub(r"(&nbsp;|&#160;|\s)+", " ", text)
    month_label = f"{MONTH_NAMES[int(period[5:7])]} {period[:4]}"
    match = re.search(
        rf"In {month_label}, compared with [A-Za-z]+ \d{{4}},? the seasonally "
        rf"adjusted retail trade volume (increased|decreased) by ([\d.]+)% "
        rf"in the euro area",
        text,
    )
    if not match:
        return None
    value = float(match.group(2))
    return value if match.group(1) == "increased" else -value


def abs_ba_headline(raw: bytes, period: str) -> float | None:
    """Signed SA total-dwellings MoM % from an ABS approvals release page."""
    text = re.sub(r"<[^>]+>", " ", raw.decode("utf-8", errors="replace"))
    text = re.sub(r"(&nbsp;|&#160;|\s)+", " ", text)
    month_label = f"{MONTH_NAMES[int(period[5:7])]} {period[:4]}"
    match = re.search(
        rf"The {month_label} seasonally adjusted estimate:?\s*Total dwellings "
        rf"approved (rose|fell) ([\d.]+)%",
        text,
    )
    if not match:
        return None
    value = float(match.group(2))
    return value if match.group(1) == "rose" else -value




def intl_anchor_failures(spec: dict[str, Any], series: dict[str, float]) -> list[str]:
    """Anchor periods whose recorded first prints the fetch cannot reproduce.

    Failing closed here is the core safety property: a candidate series that
    cannot reproduce the cell's own recorded history must never resolve it.
    """
    failures = []
    for anchor_period, expected in (spec.get("anchors") or {}).items():
        if spec.get("anchor_transform") == "raw_level":
            # Anchors stated on the fetched series itself (used where the
            # published headline is a same-release diff whose historical
            # values are not stable enough to anchor on).
            actual = series.get(anchor_period)
        else:
            actual = intl_transformed_value(spec, series, anchor_period)
        if actual is None or abs(actual - expected) > spec["anchor_tolerance"]:
            failures.append(f"{anchor_period}: expected {expected}, got {actual}")
    return failures


def flash_vintage_missing(
    spec: dict[str, Any], flags: dict[str, str], period: str
) -> bool:
    """True when a flash-print spec can no longer see the flash vintage.

    Eurostat drops the provisional/estimated flag when finals replace the
    flash value on the same endpoint; resolving past that point would record
    the final as if it were the flash first print.
    """
    accepted = set(spec.get("accepted_flags") or ("e", "p"))
    return bool(spec.get("require_flag")) and flags.get(period) not in accepted


def intl_fetch(
    spec: dict[str, Any],
    period: str,
    cache: dict[Any, tuple],
) -> tuple[dict[str, float], dict[str, str], bytes, str, str]:
    """Fetch + parse one adapter artifact, cached so dialects share bytes.

    Returns (series keyed YYYY-MM, status flags, raw bytes, url,
    retrievedAt). For single-print page artifacts the series carries just
    the periods the page itself prints.
    """
    kind = spec["kind"]
    if kind == "statcan":
        cache_key = ("statcan", spec["vector"])
        if cache_key not in cache:
            series, raw, url, retrieved_at = statcan_series(
                spec["vector"],
                latest_n=spec.get("latest_n", 36),
                allowed_hosts=spec["allowed_hosts"],
            )
            cache[cache_key] = (series, {}, raw, url, retrieved_at)
    elif kind == "abs":
        request_url = spec.get("request_url")
        cache_key = ("abs", spec["flow"], spec["key"], request_url)
        if cache_key not in cache:
            if request_url:
                raw, retrieved_at, url = http_get(
                    str(request_url), allowed_hosts=spec["allowed_hosts"]
                )
                series = abs_series_from_payload(raw, spec["flow"], spec["key"])
            else:
                series, raw, url, retrieved_at = abs_series(
                    spec["flow"],
                    spec["key"],
                    latest_n=spec.get("latest_n", 30),
                    allowed_hosts=spec["allowed_hosts"],
                )
            cache[cache_key] = (series, {}, raw, url, retrieved_at)
    elif kind == "eurostat":
        cache_key = ("eurostat", spec["dataset"], spec["key"])
        if cache_key not in cache:
            series, flags, raw, url, retrieved_at = eurostat_series(
                spec["dataset"],
                spec["key"],
                latest_n=spec.get("latest_n", 36),
                allowed_hosts=spec["allowed_hosts"],
            )
            cache[cache_key] = (series, flags, raw, url, retrieved_at)
    elif kind == "ons":
        cache_key = ("ons", spec["uri"])
        if cache_key not in cache:
            series, raw, url, retrieved_at = ons_series(
                spec["uri"],
                spec["series_id"],
                allowed_hosts=spec["allowed_hosts"],
            )
            cache[cache_key] = (series, {}, raw, url, retrieved_at)
    elif kind in ("eurostat_release", "abs_ba_release"):
        # Approvals' two-release cycle and retail's numbered release slugs
        # resolve exclusively from pinned URLs.
        urls: list[str] = []
        if spec.get("live_url_template"):
            month = dt.date.fromisoformat(f"{period}-01")
            urls.append(
                spec["live_url_template"].format(
                    period_slug=month.strftime("%b-%Y").lower()
                )
            )
        urls.extend(spec["snapshots"].get(period) or [])
        if not urls:
            raise LookupError(f"no pinned artifact registered for {period}")
        cache_key = (kind, spec["series_id"], period)
        if cache_key not in cache:
            failures: list[str] = []
            for url in urls:
                try:
                    raw, retrieved_at, final_url = http_get(
                        url, allowed_hosts=spec["allowed_hosts"]
                    )
                    if kind == "eurostat_release":
                        value = eurostat_retail_headline(raw, period)
                        series = {} if value is None else {period: value}
                    else:
                        value = abs_ba_headline(raw, period)
                        series = {} if value is None else {period: value}
                    cache[cache_key] = (
                        series,
                        {},
                        raw,
                        final_url,
                        retrieved_at,
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - try the next pin
                    failures.append(f"{url}: {exc}")
            if cache_key not in cache:
                raise ValueError(
                    "no pinned artifact parsed cleanly: " + "; ".join(failures)
                )
    else:
        raise ValueError(f"unknown intl adapter kind {kind!r}")
    return cache[cache_key]


def parse_ref_period(ref: str, stem: str) -> tuple[str, str] | None:
    """Parse a dataPointId period tail to ``(period_type, canonical value)``.

    Month and quarter values use their canonical starting month (``YYYY-MM``);
    calendar and fiscal years use ``YYYY``.
    """
    tail = ref[len(stem) + 1 :]
    tail = re.sub(
        r"\.(first_print|registered_query_snapshot|advance|second|third|flash"
        r"|preliminary)_?(estimate)?$",
        "",
        tail,
    )
    m = re.fullmatch(r"([a-z]+)_(\d{4})", tail)
    if m and m.group(1) in MONTH_NUMBERS:
        return "month", f"{m.group(2)}-{MONTH_NUMBERS[m.group(1)]:02d}"
    # Registration canonicalizes a bare YYYY-MM target period to YYYY_MM.
    # Keep accepting older hyphenated IDs as well.
    m = re.fullmatch(r"(\d{4})[-_](\d{2})", tail)
    if m and 1 <= int(m.group(2)) <= 12:
        return "month", f"{m.group(1)}-{m.group(2)}"
    m = re.fullmatch(r"q([1-4])_(\d{4})", tail)
    if m:
        return "quarter", f"{m.group(2)}-{(int(m.group(1)) - 1) * 3 + 1:02d}"
    m = re.fullmatch(r"(\d{4})_q([1-4])", tail)
    if m:
        return "quarter", f"{m.group(1)}-{(int(m.group(2)) - 1) * 3 + 1:02d}"
    m = re.fullmatch(r"fy_?(\d{4})", tail)
    if m:
        return "fiscal_year", m.group(1)
    m = re.fullmatch(r"(\d{4})", tail)
    if m:
        return "year", m.group(1)
    return None


def parse_usaspending_ref_fiscal_year(ref: str, stem: str) -> str | None:
    """Parse one exact registered-query snapshot id to a fiscal year.

    Conditional arms append a legal-state token after the release-policy
    token, so the generic trailing-policy parser cannot see it. Mirror the
    IRS conditional-family treatment while accepting the existing ``fy2026``
    spelling and the reviewed pair's bare ``2027`` spelling. Other release
    policies fail closed instead of being claimed by the USAspending adapter.
    """

    match = re.fullmatch(
        rf"{re.escape(stem)}\.(?:fy_?)?(\d{{4}})"
        r"\.registered_query_snapshot(?:\.[a-z0-9_]+)?",
        ref,
    )
    return match.group(1) if match else None


def _registered_sba_fiscal_year(
    ref: str,
    stem: str,
    spec: Mapping[str, Any],
    registration: Mapping[str, Any] | None,
) -> str | None:
    """Recover SBA's annual period semantics from its registered contract.

    A normal annual registration emits a bare ``.<YYYY>.first_print`` suffix,
    which is intentionally ambiguous to the generic reference parser.  The
    immutable contract supplies the missing meaning: this SBA series' annual
    period is a fiscal year.  Keep explicit ``fy_YYYY`` legacy references on
    the generic-parser path, and require the registered identity and period to
    agree before reclassifying a bare year.
    """

    contract = (registration or {}).get("contract")
    if not isinstance(contract, Mapping):
        return None
    period = contract.get("period")
    binding = contract.get("sourceBinding")
    if (
        contract.get("dataPointId") != ref
        or contract.get("series") != stem
        or not isinstance(period, str)
        or re.fullmatch(r"\d{4}", period) is None
        or not isinstance(binding, Mapping)
        or not sba_pdf_binding_matches_spec(binding, spec)
    ):
        return None
    parsed = parse_ref_period(ref, stem)
    if parsed != ("year", period):
        return None
    return period




def apply_transform(
    rows: dict[str, float], spec: dict[str, Any], period_type: str, period: str
) -> float | None:
    key = f"{period}-01"
    prior_key = f"{prior_period_date(period, period_type)}-01"
    if rows.get(key) is None:
        return None
    transform = spec["transform"]
    if transform == "level":
        value = rows[key]
    elif transform == "mom_diff":
        if rows.get(prior_key) is None:
            return None
        value = rows[key] - rows[prior_key]
    elif transform == "pct_change_1d":
        if rows.get(prior_key) is None:
            return None
        value = round((rows[key] / rows[prior_key] - 1) * 100, 1)
    else:
        raise ValueError(f"unknown transform {transform!r}")
    value *= spec.get("scale", 1)
    digits = spec.get("round")
    if digits is not None:
        value = round(value, digits)
    # IEEE -0.0 survives round() and splits Python's json ("-0.0") from
    # JSON.stringify ("0") downstream; normalize before the value enters
    # any ledger row (same guard as the spawn intake).
    return round(value, 4) + 0.0


def value_plausible(value: float, forecast_entry: dict[str, Any] | None) -> bool:
    """Bounded unit-scale gate: a fetched value wildly outside the cell's
    own interval means a wrong series or transform (thousands-vs-millions
    class), never a legitimate outcome. Bounded at 4 interval-widths so a
    genuine surprise still resolves and grades."""
    interval = (forecast_entry or {}).get("interval80") or {}
    lower, upper = interval.get("lower"), interval.get("upper")
    if lower is None or upper is None:
        return True
    width = max(upper - lower, abs(upper) * 0.05, 1e-9)
    return (lower - 4 * width) <= value <= (upper + 4 * width)


def generic_fact(
    ref: str,
    spec: dict[str, Any],
    period_type: str,
    period: str,
    value: float,
    release_day: dt.date,
    source_url: str,
    source_file: str,
) -> dict:
    source_periods = [period]
    transform = spec.get("transform", "level")
    if transform in ("mom_diff", "mom_pct"):
        source_periods.append(prior_period_date(period, period_type))
    elif transform == "yoy_from_index":
        source_periods.append(f"{int(period[:4]) - 1}-{period[5:7]}")
    return {
        "source_record_id": ref,
        "label": f"{spec['label']}, {period}",
        "value": value,
        "observed_at": release_day.isoformat(),
        "period": {"type": period_type, "value": period},
        "domain": spec.get("domain", "economy"),
        "geography": INTL_GEOGRAPHY.get(spec.get("country", ""), US_GEOGRAPHY),
        "entity": spec.get("entity", {"name": "economy", "role": "aggregate"}),
        "measure": {
            "concept": spec.get("measure_concept")
            or spec.get("target_series")
            or re.sub(
                r"\.(first_print|registered_query_snapshot|flash|preliminary)$",
                "",
                ref,
            ),
            "unit": spec["unit"],
            "source_concept": spec.get("fred", spec.get("source_concept", "")),
            "concept_relation": "source_label",
            "concept_authority": spec["concept_authority"],
            "concept_evidence_url": source_url,
            "concept_evidence_notes": spec.get(
                "evidence_notes",
                "First print for {period} captured from {source_url} on the "
                "official release date named by the cell's resolver.",
            ).format(period=period, source_url=source_url),
        },
        "aggregation": {"method": "level"},
        "filters": copy.deepcopy(spec.get("filters", {})),
        "source": {
            "source_name": spec["source_name"],
            "source_table": spec["source_table"],
            "source_file": source_file,
            "url": source_url,
            "vintage": "first_print",
            "extracted_at": dt.date.today().isoformat(),
            "extraction_method": (
                "Automated first-print capture by scripts/resolve_pending.py "
                "(anchor-verified adapter)"
            ),
        },
        # Derived changes consume both observations; preserve that lineage
        # instead of pretending the target month's row alone produced them.
        "source_row_keys": source_periods,
        "source_cell_keys": [spec.get("fred", spec.get("source_concept", ""))],
    }


def sba_pdf_fact(
    ref: str,
    spec: Mapping[str, Any],
    fiscal_year: str,
    resolution: SbaPdfResolution,
) -> dict[str, Any]:
    """Build a fact that calls this value the earliest witnessed capture."""

    witnessed_at = str(resolution.provenance["earliestWitnessedAt"])
    observed_at = witnessed_at[:10]
    source_file = posixpath.basename(urlparse(resolution.source_url).path)
    if not source_file:
        raise ValueError("SBA custody asset URL has no source filename")
    return {
        "source_record_id": ref,
        "label": f"{spec['label']}, fiscal year {fiscal_year}",
        "value": resolution.value,
        "observed_at": observed_at,
        "period": {"type": "fiscal_year", "value": fiscal_year},
        "domain": "economy",
        "geography": US_GEOGRAPHY,
        "entity": {
            "name": "SBA Disaster Loan Program",
            "role": "federal_program",
        },
        "measure": {
            "concept": spec["series_id"],
            "unit": resolution.unit,
            "source_concept": spec["series_id"],
            "concept_relation": "exact_official_table_cell",
            "concept_authority": "U.S. Small Business Administration",
            "concept_evidence_url": SBA_ENTRY_URL,
            "concept_evidence_notes": (
                "Earliest externally witnessed, hash-pinned capture that "
                "strictly parses the completed fiscal-year Disaster cell; "
                "this does not claim SBA's historically first publication."
            ),
        },
        "aggregation": {"method": "level"},
        "filters": {"program": "Disaster"},
        # The complete proof remains part of the ledger row (and therefore
        # the signed ledger release), while responseArchive below binds the
        # exact upstream ZIP bytes rather than a locally synthesized wrapper.
        "custodyProvenance": resolution.provenance,
        "source": {
            "source_name": spec["source_name"],
            "source_table": resolution.provenance["tableTitle"],
            "source_file": source_file,
            "url": resolution.source_url,
            "vintage": "earliest_witnessed_capture",
            "source_sha256": resolution.provenance["zipSha256"],
            "extracted_at": dt.date.today().isoformat(),
            "extraction_method": (
                "Strict replay of a committed SBA PDF custody capture selected "
                "by the verified recorder-chain TSA timeline"
            ),
        },
        "source_row_keys": ["section:Disaster", "row:Disaster"],
        "source_cell_keys": [f"{resolution.member_path}::Fiscal Year {fiscal_year}"],
    }


def a19_values_from_html(html: str) -> dict[str, float]:
    """June-style A-19 parse: each row label followed by year-ago then
    current-month totals; the CURRENT month (second number) is the print."""
    text = re.sub(r"<[^>]+>", "|", html)
    text = re.sub(r"[\s|]+", " ", text)
    out: dict[str, float] = {}
    for key, label in A19_ROW_LABELS.items():
        m = re.search(re.escape(label) + r"\s+([0-9,]+)\s+([0-9,]+)", text)
        if m:
            out[key] = float(m.group(2).replace(",", ""))
    return out


def bls_rows_from_payload(raw: bytes, series_id: str) -> dict[str, dict[str, Any]]:
    """Monthly rows keyed YYYY-MM with the latest/preliminary markers the
    temporal first-print gate needs. Only a successful response for exactly
    `series_id` yields rows; anything else fails closed to empty."""
    try:
        payload = json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if payload.get("status") != "REQUEST_SUCCEEDED":
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for series in (payload.get("Results") or {}).get("series") or []:
        if series.get("seriesID") != series_id:
            continue
        for row in series.get("data") or []:
            match = re.fullmatch(r"M(0[1-9]|1[0-2])", str(row.get("period")))
            if not match:
                continue
            try:
                value = float(row["value"])
            except (KeyError, TypeError, ValueError):
                continue
            rows[f"{row.get('year')}-{match.group(1)}"] = {
                "value": value,
                "latest": str(row.get("latest", "")).lower() == "true",
                "preliminary": any(
                    footnote.get("code") == "P"
                    for footnote in row.get("footnotes") or []
                    if isinstance(footnote, dict)
                ),
            }
    return rows


def bls_series_rows(
    series_id: str, start_year: int, end_year: int
) -> tuple[dict[str, dict[str, Any]], bytes | None, str, str]:
    """Every monthly value of `series_id` as the BLS API currently serves it,
    fetched keylessly from the cell's own bound resolutionSourceUrl."""
    url = BLS_API_URL.format(series=series_id, start=start_year, end=end_year)
    retrieved_at = utc_now()
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            raw = r.read()
    except urllib.error.HTTPError:
        return {}, None, url, retrieved_at
    rows = bls_rows_from_payload(raw, series_id)
    if not rows:
        # An error payload (rate limit, unknown series) must not archive as
        # if it were a print; surface it as a failed fetch instead.
        return {}, None, url, retrieved_at
    return rows, raw, url, retrieved_at


def bls_anchor_mismatches(
    rows: dict[str, dict[str, Any]], anchors: dict[str, float]
) -> list[str]:
    """Anchor periods whose fetched values cannot reproduce the cell's own
    recorded history within BLS_ANCHOR_TOLERANCE (see the adapter note on
    first prints vs current estimates)."""
    problems = []
    for anchor_period, expected in sorted(anchors.items()):
        state = rows.get(anchor_period)
        if state is None:
            problems.append(f"{anchor_period}=missing (recorded {expected})")
            continue
        if abs(state["value"] - expected) > BLS_ANCHOR_TOLERANCE * abs(expected):
            problems.append(
                f"{anchor_period}={state['value']} (recorded first print {expected})"
            )
    return problems


def bls_annual_average_pct_change(
    rows: dict[str, dict[str, Any]], year: str
) -> float | None:
    """Annual-average percent change from two complete calendar years.

    BLS's keyless API does not include the optional M13 annual-average row.
    Computing from M01--M12 keeps the resolver keyless and makes completeness
    explicit.
    """
    if not re.fullmatch(r"\d{4}", year):
        raise ValueError(f"annual BLS period must be YYYY, got {year!r}")
    prior = str(int(year) - 1)
    target_states = [rows.get(f"{year}-{month:02d}") for month in range(1, 13)]
    prior_states = [rows.get(f"{prior}-{month:02d}") for month in range(1, 13)]
    if any(state is None for state in [*target_states, *prior_states]):
        return None
    target_average = sum(state["value"] for state in target_states if state) / 12
    prior_average = sum(state["value"] for state in prior_states if state) / 12
    if prior_average == 0:
        return None
    return round((target_average / prior_average - 1) * 100, 1) + 0.0


def bls_annual_anchor_mismatches(
    rows: dict[str, dict[str, Any]], anchors: dict[str, float]
) -> list[str]:
    """Derived annual anchors that do not reproduce official BLS values."""
    problems = []
    for year, expected in sorted(anchors.items()):
        got = bls_annual_average_pct_change(rows, year)
        if got is None:
            problems.append(f"{year}=missing/incomplete (official {expected})")
        elif got != expected:
            problems.append(f"{year}={got} (official {expected})")
    return problems


def bls_annual_first_print(
    rows: dict[str, dict[str, Any]], year: str
) -> tuple[float | None, str | None]:
    """Capture an annual CPI value only while target December is latest."""
    target_december = f"{year}-12"
    latest_period = max(rows, default=None)
    if latest_period is None or latest_period < target_december:
        return None, None
    if latest_period > target_december:
        return None, (
            f"{year} is complete but {latest_period} is now published; the "
            "annual first-print window was missed — resolve manually from an "
            "archived vintage"
        )
    value = bls_annual_average_pct_change(rows, year)
    if value is None:
        return None, (
            f"{year} December is latest but the target/prior 24-month window "
            "is incomplete; refusing a partial annual average"
        )
    return value, None


BLS_FIRST_PRINT_GATES = {"latest_preliminary", "latest_month"}


def bls_first_print(
    rows: dict[str, dict[str, Any]],
    period: str,
    gate: str = "latest_preliminary",
) -> tuple[float | None, str | None]:
    """(value, refusal): a value only while `period` is still the series'
    latest print; a present-but-revised period is refused, an absent one
    defers.

    ``gate="latest_preliminary"`` (CES, LAUS, every series BLS flags) also
    requires the preliminary "P" footnote. ``gate="latest_month"`` is for CPS
    household-survey series, which BLS never flags preliminary and does not
    revise between Employment Situation releases: the period must simply
    still be the latest published month.
    """
    if gate not in BLS_FIRST_PRINT_GATES:
        raise ValueError(f"unknown BLS first-print gate {gate!r}")
    latest_period = max(rows, default=None)
    state = rows.get(period)
    if state is None:
        if latest_period is not None and latest_period > period:
            return None, (
                f"{period} is absent although later period {latest_period} "
                "is published; the first-print window was missed or the "
                "target period was not published"
            )
        return None, None
    is_latest = period == latest_period and state["latest"]
    if gate == "latest_month":
        if not is_latest:
            return None, (
                f"{period} is published but no longer the latest month; the "
                "first-print window was missed — resolve manually from an "
                "archived vintage"
            )
        return state["value"], None
    if not (is_latest and state["preliminary"]):
        return None, (
            f"{period} is published but no longer the latest preliminary "
            "print; the first-print window was missed — resolve manually "
            "from an archived vintage"
        )
    return state["value"], None


FSA_CRP_BINDING_TEMPLATE_KEYS = {
    "adapter",
    "sourceUrl",
    "sourceSeriesId",
    "field",
    "table",
    "transform",
    "releasePolicy",
}
FSA_CRP_BINDING_DERIVED_KEYS = {"expectedReleaseWindow", "allowedHosts"}


def fsa_crp_binding_template(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete reviewed seven-key FSA CRP source binding."""

    return {
        "adapter": "fsa-crp-monthly-summary",
        "sourceUrl": spec["source_url"],
        "sourceSeriesId": spec["series_id"],
        "field": spec["field"],
        "table": spec["source_table"],
        "transform": {"operation": "identity", "factor": 1},
        "releasePolicy": "first_print",
    }


def fsa_crp_binding_matches_spec(binding: Any, spec: Mapping[str, Any]) -> bool:
    """Require the registered seven keys to match the executor exactly."""

    if not isinstance(binding, dict):
        return False
    if set(binding) - FSA_CRP_BINDING_DERIVED_KEYS != FSA_CRP_BINDING_TEMPLATE_KEYS:
        return False
    allowed_hosts = binding.get("allowedHosts")
    if allowed_hosts is not None and (
        not isinstance(allowed_hosts, list)
        or sorted(allowed_hosts) != sorted(spec["allowed_hosts"])
    ):
        return False
    projection = {key: binding[key] for key in FSA_CRP_BINDING_TEMPLATE_KEYS}
    return canonical_bytes(projection) == canonical_bytes(
        fsa_crp_binding_template(spec)
    )


class _FsaCrpLinkParser(HTMLParser):
    """Collect anchor hrefs and their visible text from an FSA document page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self._href = next(
            (value for name, value in attrs if name.lower() == "href" and value),
            None,
        )
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text)))
            self._href = None
            self._text = []


class _FsaCrpTableParser(HTMLParser):
    """Preserve table cells and their links for structural Summary selection."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict[str, Any]]]] = []
        self._table: list[list[dict[str, Any]]] | None = None
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None
        self._href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table" and self._table is None:
            self._table = []
        elif tag == "tr" and self._table is not None and self._row is None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None and self._cell is None:
            self._cell = {"tag": tag, "text": [], "links": []}
        elif tag == "a" and self._cell is not None:
            self._href = next(
                (value for name, value in attrs if name.lower() == "href" and value),
                None,
            )
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)
        if self._href is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._cell is not None and self._href is not None:
            self._cell["links"].append((self._href, " ".join(self._anchor_text)))
            self._href = None
            self._anchor_text = []
        elif tag in {"th", "td"} and self._row is not None and self._cell is not None:
            self._cell["text"] = " ".join(self._cell["text"])
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._table is not None and self._row is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


def _fsa_crp_normalized_text(value: str) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        urllib.parse.unquote(value).lower(),
    ).strip()


def _fsa_crp_compact_path(url: str) -> str:
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    return re.sub(r"[^a-z0-9]+", "", path.lower())


def _fsa_crp_period_tokens(period: str) -> tuple[str, set[str]]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise ValueError(f"FSA CRP period must be YYYY-MM, got {period!r}")
    year, month_number = period.split("-")
    month_date = dt.date(int(year), int(month_number), 1)
    month_name = month_date.strftime("%B").lower()
    month_abbreviation = month_date.strftime("%b").lower()
    return month_name, {
        f"{month_name}{year}",
        f"{month_abbreviation}{year}",
        f"{year}{month_name}",
        f"{year}{month_abbreviation}",
    }


_FSA_CRP_RAW_URL_RE = re.compile(r"https://[A-Za-z0-9.-]+/[A-Za-z0-9/._-]+")
_FSA_CRP_RAW_HREF_RE = re.compile(r"(?:https://[A-Za-z0-9.-]+)?/[A-Za-z0-9/._-]+")


def _require_fsa_crp_raw_url(raw: str, kind: str) -> None:
    """Refuse a noncanonical URL BEFORE any parser touches it.

    urlparse is lossy: it silently strips embedded TAB/LF/CR and
    tolerates empty ;/?/#/port components, so checks that run on its
    output validate a different string than the transport would use
    (2026-08-13 round-2 review: TAB, LF, and CR probes reached the
    mocked transport). The raw string must already BE the canonical
    form — scheme, host, and a path drawn from the reviewed character
    set — or this hop refuses with no parsing and no network.
    """

    if not _FSA_CRP_RAW_URL_RE.fullmatch(raw):
        raise ValueError(f"FSA CRP {kind} URL is not in canonical form: {raw!r}")


def _require_fsa_crp_raw_href(href: str, kind: str) -> None:
    """Refuse a noncanonical href BEFORE urljoin normalizes it.

    urljoin resolves dot segments and strips TAB/LF/CR, so a hostile
    href can normalize into a clean URL that passes every post-join
    check while never itself being the reviewed link shape. Only two
    raw shapes are reviewed: an absolute https URL or an absolute path,
    both over the canonical character set with no empty or dot
    segments.
    """

    if not _FSA_CRP_RAW_HREF_RE.fullmatch(href):
        raise ValueError(f"FSA CRP {kind} href is not in canonical form: {href!r}")
    if href.startswith("https://"):
        path = "/" + href.removeprefix("https://").split("/", 1)[1]
    else:
        path = href
    segments = path.split("/")
    if any(seg in ("", ".", "..") for seg in segments[1:]):
        raise ValueError(
            f"FSA CRP {kind} href contains empty or dot segments: {href!r}"
        )


def _require_fsa_crp_url_kind(
    url: str,
    kind: str,
    allowed_hosts: list[str] | tuple[str, ...],
) -> None:
    """Pin one FSA hop to its reviewed host and path class."""

    _require_fsa_crp_raw_url(url, kind)
    parsed = urllib.parse.urlparse(url)
    _require_allowed_host(url, allowed_hosts)
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        # parsed.params is the ;-delimited path-parameter component
        # urlparse splits off the last segment — it never appears in
        # parsed.path, so without this refusal a ";download" suffix
        # would validate as the clean path yet ride along in the fetch.
        raise ValueError(
            f"FSA CRP {kind} URL must not contain credentials, a port, "
            f"path parameters, query, or fragment: {url!r}"
        )
    # The registered contract promises EXACT paths, so the raw path is
    # matched with no decoding at all: any percent escape, path
    # parameter, backslash, control character, dot segment, empty
    # segment, or case variation is noncanonical and refuses before any
    # network access. A second decoder downstream can therefore never
    # reveal traversal or separators this check did not see (2026-08-13
    # review: %252e%252e%252f traversal, ";download", and /SITES/ all
    # passed the old single-decode IGNORECASE match).
    raw_path = parsed.path
    if not re.fullmatch(r"[A-Za-z0-9/._-]+", raw_path):
        raise ValueError(
            f"FSA CRP {kind} path contains characters outside the "
            f"reviewed canonical set: {raw_path!r}"
        )
    segments = raw_path.split("/")
    if any(seg in ("", ".", "..") for seg in segments[1:]):
        raise ValueError(
            f"FSA CRP {kind} path contains empty or dot segments: {raw_path!r}"
        )
    if kind == "landing":
        expected = urllib.parse.urlparse(FSA_CRP_LANDING_URL).path
        if raw_path != expected:
            raise ValueError(
                f"FSA CRP landing path {raw_path!r} is not the exact "
                f"reviewed path {expected!r}"
            )
        return
    if kind == "document":
        if not re.fullmatch(r"/documents/[a-z0-9][a-z0-9-]*", raw_path):
            raise ValueError(
                f"FSA CRP document path is outside the reviewed class: {raw_path!r}"
            )
        return
    if kind == "artifact":
        if not re.fullmatch(
            r"/sites/default/files/\d{4}-\d{2}/[A-Za-z0-9._-]+\.pdf",
            raw_path,
        ):
            raise ValueError(
                f"FSA CRP artifact path is outside the reviewed class: {raw_path!r}"
            )
        return
    raise ValueError(f"unknown FSA CRP URL kind {kind!r}")


def _require_fsa_crp_document_identity(url: str, period: str) -> None:
    _, period_tokens = _fsa_crp_period_tokens(period)
    compact = _fsa_crp_compact_path(url)
    if (
        "crp" not in compact
        or "onepager" in compact
        or not any(token in compact for token in period_tokens)
    ):
        raise ValueError(
            f"FSA CRP document URL does not authenticate target month {period}: {url!r}"
        )


def _require_fsa_crp_artifact_identity(url: str, period: str) -> None:
    _, period_tokens = _fsa_crp_period_tokens(period)
    compact = _fsa_crp_compact_path(url)
    if (
        "crpmonthly" not in compact
        or "onepager" in compact
        or not any(token in compact for token in period_tokens)
    ):
        raise ValueError(
            f"FSA CRP artifact URL does not authenticate target month {period}: {url!r}"
        )


class _FsaCrpNoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects after validating the destination's path class."""

    def __init__(
        self,
        kind: str,
        allowed_hosts: list[str] | tuple[str, ...],
    ) -> None:
        super().__init__()
        self.kind = kind
        self.allowed_hosts = allowed_hosts

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        _require_fsa_crp_url_kind(newurl, self.kind, self.allowed_hosts)
        raise ValueError(
            f"FSA CRP {self.kind} redirects are not allowed: "
            f"{req.full_url!r} -> {newurl!r}"
        )


def fsa_crp_http_get(
    url: str,
    *,
    kind: str,
    allowed_hosts: list[str] | tuple[str, ...],
    timeout: int = 120,
) -> tuple[bytes, str, str]:
    """Fetch one redirect-free FSA hop with its working transparent UA."""

    _require_fsa_crp_url_kind(url, kind, allowed_hosts)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": FSA_CRP_USER_AGENT},
    )
    retrieved_at = utc_now()
    opener = urllib.request.build_opener(_FsaCrpNoRedirectHandler(kind, allowed_hosts))
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        _require_fsa_crp_url_kind(final_url, kind, allowed_hosts)
        if final_url != url:
            raise ValueError(
                f"FSA CRP {kind} final URL changed without an accepted "
                f"identity transition: {url!r} -> {final_url!r}"
            )
        return response.read(), retrieved_at, final_url


def fsa_crp_summary_document_url(
    raw_html: bytes,
    period: str,
    *,
    landing_url: str,
    allowed_hosts: list[str] | tuple[str, ...],
) -> tuple[str | None, str | None]:
    """Select the target row's unique Summary document link."""

    month_name, _ = _fsa_crp_period_tokens(period)
    try:
        _require_fsa_crp_url_kind(landing_url, "landing", allowed_hosts)
    except ValueError as exc:
        return None, str(exc)
    try:
        html = raw_html.decode("utf-8")
    except UnicodeDecodeError:
        return None, "FSA statistics landing page is not UTF-8 HTML"
    parser = _FsaCrpTableParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - malformed upstream HTML
        return None, f"FSA statistics landing page did not parse: {exc}"

    year = period[:4]
    target_label = f"{month_name} {year}"
    table_matches: list[tuple[list[list[dict[str, Any]]], int, int]] = []
    for table in parser.tables:
        for row_index, row in enumerate(table):
            headers = [_fsa_crp_normalized_text(str(cell["text"])) for cell in row[:3]]
            if headers == ["month year", "summary", "one pager"]:
                table_matches.append((table, row_index, 1))
    if len(table_matches) != 1:
        return None, (
            "expected one FSA Monthly Summaries table with Month/Year, "
            f"Summary, and One-pager columns; found {len(table_matches)}"
        )
    table, header_index, summary_index = table_matches[0]
    target_rows = [
        row
        for row in table[header_index + 1 :]
        if row and _fsa_crp_normalized_text(str(row[0]["text"])) == target_label
    ]
    if not target_rows:
        return None, None
    if len(target_rows) != 1:
        return None, (
            f"expected one {month_name.title()} {year} row in the FSA Monthly "
            f"Summaries table, found {len(target_rows)}"
        )
    row = target_rows[0]
    if summary_index >= len(row):
        return None, "FSA target-month row has no Summary cell"
    matches: set[str] = set()
    for href, _label in row[summary_index]["links"]:
        try:
            _require_fsa_crp_raw_href(href, "document")
            url = urllib.parse.urljoin(landing_url, href)
            _require_fsa_crp_url_kind(url, "document", allowed_hosts)
            _require_fsa_crp_document_identity(url, period)
        except ValueError as exc:
            return None, str(exc)
        matches.add(url)
    if len(matches) != 1:
        return None, (
            f"expected one {month_name.title()} {year} CRP Summary document "
            f"link, found {len(matches)}"
        )
    return next(iter(matches)), None


def fsa_crp_document_pdf_url(
    raw_html: bytes,
    period: str,
    *,
    document_url: str,
    allowed_hosts: list[str] | tuple[str, ...],
) -> tuple[str | None, str | None]:
    """Select one target-month PDF from the authenticated document page."""

    _fsa_crp_period_tokens(period)
    try:
        _require_fsa_crp_url_kind(document_url, "document", allowed_hosts)
        _require_fsa_crp_document_identity(document_url, period)
    except ValueError as exc:
        return None, str(exc)
    try:
        html = raw_html.decode("utf-8")
    except UnicodeDecodeError:
        return None, "FSA CRP document page is not UTF-8 HTML"
    parser = _FsaCrpLinkParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - malformed upstream HTML
        return None, f"FSA CRP document page did not parse: {exc}"

    _, period_tokens = _fsa_crp_period_tokens(period)
    matches: set[str] = set()
    for href, label in parser.links:
        # Filter on RAW strings only — no urljoin/urlparse/unquote may
        # touch an unvalidated href. Parsing before filtering meant all
        # unrelated page links reached urljoin, and one malformed
        # navigation href (e.g. "https://[broken") raised an
        # unstructured ValueError outside the refusal envelope
        # (round-3 review). Unrelated links are filtered out untouched;
        # only CRP-monthly PDF candidates proceed, and each must pass
        # the raw guard BEFORE it is ever joined.
        compact = re.sub(r"[^a-z0-9]+", "", f"{label} {href}".lower())
        if "crpmonthly" not in compact or "onepager" in compact:
            continue
        if not any(token in compact for token in period_tokens):
            continue
        if not href.lower().endswith(".pdf"):
            continue
        try:
            _require_fsa_crp_raw_href(href, "artifact")
            url = urllib.parse.urljoin(document_url, href)
            _require_fsa_crp_url_kind(url, "artifact", allowed_hosts)
            _require_fsa_crp_artifact_identity(url, period)
        except ValueError as exc:
            return None, str(exc)
        matches.add(url)
    if len(matches) != 1:
        month_name, _ = _fsa_crp_period_tokens(period)
        year = period[:4]
        return None, (
            f"expected one {month_name.title()} {year} CRP Monthly Summary "
            f"PDF on the FSA document page, found {len(matches)}"
        )
    return next(iter(matches)), None


def fsa_crp_value_from_text(text: str, period: str) -> tuple[float | None, str | None]:
    """Read the page-1 TOTAL CRP row's Acres column from preserved text."""

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise ValueError(f"FSA CRP period must be YYYY-MM, got {period!r}")
    # Later pages contain state tables with their own TOTAL CRP rows. The
    # registered measure is the national sign-up-type table printed on page 1.
    first_page = text.split("\f", 1)[0]
    if not re.search(
        r"\b(?:CRP|CONSERVATION\s+RESERVE\s+PROGRAM)\b[\s\S]{0,120}?"
        r"\bMONTHLY\s+SUMMARY\b",
        first_page,
        re.IGNORECASE,
    ):
        # The published header spells out the program name on its own line
        # above "MONTHLY SUMMARY — <MONTH> <YEAR>"; the acronym form is
        # accepted for robustness but the real PDFs use the spelled form.
        return None, "PDF text is not labeled CRP Monthly Summary"
    year, month_number = period.split("-")
    month_date = dt.date(int(year), int(month_number), 1)
    month_pattern = re.compile(
        rf"\b(?:{month_date.strftime('%B')}|{month_date.strftime('%b')})"
        rf"\s+{year}\b",
        re.IGNORECASE,
    )
    if not month_pattern.search(first_page):
        return None, f"PDF text does not identify target month {period}"

    rows: list[tuple[int, list[str]]] = []
    lines = first_page.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    for index, line in enumerate(lines):
        cells = re.split(r"\s{2,}", line.strip()) if line.strip() else []
        if cells and _fsa_crp_normalized_text(cells[0]) == "total crp":
            rows.append((index, cells))
    if len(rows) != 1:
        return None, f"expected one TOTAL CRP row, found {len(rows)}"
    row_index, row = rows[0]

    header_matches: list[tuple[int, list[str]]] = []
    for index in range(max(0, row_index - 30), row_index):
        cells = re.split(r"\s{2,}", lines[index].strip())
        if "acres" in {_fsa_crp_normalized_text(cell) for cell in cells}:
            header_matches.append((index, cells))
    if len(header_matches) != 1:
        return None, (
            "expected one table header with an exact Acres column before "
            f"TOTAL CRP, found {len(header_matches)}"
        )
    _, header = header_matches[0]
    acres_indices = [
        index
        for index, cell in enumerate(header)
        if _fsa_crp_normalized_text(cell) == "acres"
    ]
    if len(acres_indices) != 1 or acres_indices[0] >= len(row):
        return None, "TOTAL CRP row does not align with one Acres column"
    raw_value = row[acres_indices[0]].strip()
    if not re.fullmatch(r"\d{1,3}(?:,\d{3})*|\d+", raw_value):
        return None, (f"TOTAL CRP Acres value is not an integer: {raw_value!r}")
    value = float(raw_value.replace(",", ""))
    if not math.isfinite(value) or value <= 0 or not value.is_integer():
        return None, "TOTAL CRP Acres value is not a positive integer"
    return value, None


def fsa_crp_pdf_text(raw: bytes) -> tuple[str | None, str | None]:
    """Extract PDF text with the runner's external tool, failing closed."""

    if not raw.startswith(b"%PDF-"):
        return None, "CRP Monthly Summary response is not a PDF"
    executable = shutil.which("pdftotext")
    if executable is None:
        return (
            None,
            "pdftotext is unavailable in the bare-Python resolver runtime",
        )
    try:
        completed = subprocess.run(
            [executable, "-layout", "-enc", "UTF-8", "-", "-"],
            input=raw,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"pdftotext failed: {exc}"
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        return (
            None,
            f"pdftotext exited {completed.returncode}: {detail[:200]}",
        )
    try:
        text = completed.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None, "pdftotext output is not UTF-8"
    if not text.strip():
        return None, "pdftotext returned no text"
    return text, None


def fsa_crp_verified_anchors(
    spec: Mapping[str, Any],
) -> dict[str, float] | None:
    """Return admitted positive-integer anchors or None while unarmed."""

    anchors = spec.get("anchors")
    if (
        spec.get("anchor_status") != "VERIFIED"
        or not isinstance(anchors, dict)
        or len(anchors) < 3
    ):
        return None
    verified: dict[str, float] = {}
    for period, expected in anchors.items():
        if not isinstance(period, str) or not re.fullmatch(
            r"\d{4}-(0[1-9]|1[0-2])", period
        ):
            return None
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            return None
        value = float(expected)
        if not math.isfinite(value) or value <= 0 or not value.is_integer():
            return None
        verified[period] = value
    return verified


def fsa_crp_anchor_mismatches(
    values: Mapping[str, float | None], anchors: Mapping[str, float]
) -> list[str]:
    """Compare every live-retrieved FSA anchor exactly."""

    if len(anchors) < 3:
        return [f"only {len(anchors)} verified anchors; at least 3 required"]
    problems = []
    for period, expected in sorted(anchors.items()):
        got = values.get(period)
        if got is None:
            problems.append(f"{period}=missing (official {expected})")
        elif got != expected:
            problems.append(f"{period}={got} (official {expected})")
    return problems


def fsa_crp_fetch_period(
    spec: Mapping[str, Any], period: str
) -> tuple[float | None, bytes | None, str, str, str | None]:
    """Fetch landing, document, and PDF hops, then parse the printed total."""

    landing_url = str(spec["source_url"])
    try:
        _require_fsa_crp_url_kind(
            landing_url,
            "landing",
            spec["allowed_hosts"],
        )
        landing_raw, landing_retrieved_at, _ = fsa_crp_http_get(
            landing_url,
            kind="landing",
            allowed_hosts=spec["allowed_hosts"],
        )
    except (OSError, ValueError) as exc:
        return (
            None,
            None,
            landing_url,
            utc_now(),
            f"landing fetch failed: {exc}",
        )
    document_url, refusal = fsa_crp_summary_document_url(
        landing_raw,
        period,
        landing_url=landing_url,
        allowed_hosts=spec["allowed_hosts"],
    )
    if refusal:
        return None, None, landing_url, landing_retrieved_at, refusal
    if document_url is None:
        return None, None, landing_url, landing_retrieved_at, None
    try:
        document_raw, document_retrieved_at, _ = fsa_crp_http_get(
            document_url,
            kind="document",
            allowed_hosts=spec["allowed_hosts"],
        )
    except (OSError, ValueError) as exc:
        return (
            None,
            None,
            document_url,
            utc_now(),
            f"document fetch failed: {exc}",
        )
    pdf_url, refusal = fsa_crp_document_pdf_url(
        document_raw,
        period,
        document_url=document_url,
        allowed_hosts=spec["allowed_hosts"],
    )
    if refusal or pdf_url is None:
        return None, None, document_url, document_retrieved_at, refusal
    try:
        raw, retrieved_at, final_url = fsa_crp_http_get(
            pdf_url,
            kind="artifact",
            allowed_hosts=spec["allowed_hosts"],
        )
    except (OSError, ValueError) as exc:
        return None, None, pdf_url, utc_now(), f"PDF fetch failed: {exc}"
    text, refusal = fsa_crp_pdf_text(raw)
    if refusal or text is None:
        return None, raw, final_url, retrieved_at, refusal
    value, refusal = fsa_crp_value_from_text(text, period)
    return value, raw, final_url, retrieved_at, refusal


CENSUS_SPM_BINDING_TEMPLATE_KEYS = {
    "adapter",
    "sourceUrl",
    "sourceSeriesId",
    "field",
    "table",
    "transform",
    "releasePolicy",
}
CENSUS_SPM_BINDING_DERIVED_KEYS = {"expectedReleaseWindow", "allowedHosts"}
CENSUS_SPM_TRANSFORM = {"operation": "identity", "factor": 1}


def census_spm_binding_template(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete reviewed seven-key Census SPM binding."""

    return {
        "adapter": "census-spm-annual-report",
        "sourceUrl": spec["source_url"],
        "sourceSeriesId": spec["series_id"],
        "field": spec["field"],
        "table": spec["source_table"],
        "transform": dict(CENSUS_SPM_TRANSFORM),
        "releasePolicy": "first_print",
    }


def census_spm_binding_matches_spec(binding: Any, spec: Mapping[str, Any]) -> bool:
    """Require the registered Census SPM binding to match the executor."""

    if not isinstance(binding, dict):
        return False
    if (
        set(binding) - CENSUS_SPM_BINDING_DERIVED_KEYS
        != CENSUS_SPM_BINDING_TEMPLATE_KEYS
    ):
        return False
    allowed_hosts = binding.get("allowedHosts")
    if allowed_hosts is not None and (
        not isinstance(allowed_hosts, list)
        or sorted(allowed_hosts) != sorted(spec["allowed_hosts"])
    ):
        return False
    projected = {key: binding[key] for key in CENSUS_SPM_BINDING_TEMPLATE_KEYS}
    return canonical_bytes(projected) == canonical_bytes(
        census_spm_binding_template(spec)
    )


class _CensusSpmPageParser(HTMLParser):
    """Collect visible page text and links without trusting script content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.text: list[str] = []
        self._href: str | None = None
        self._link_text: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"}:
            self._ignored_depth += 1
            return
        if lowered != "a" or self._ignored_depth:
            return
        self._href = next(
            (value for name, value in attrs if name.lower() == "href" and value),
            None,
        )
        self._link_text = []

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        self.text.append(data)
        if self._href is not None:
            self._link_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if lowered == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._link_text)))
            self._href = None
            self._link_text = []


def _census_spm_page(raw_html: bytes) -> tuple[_CensusSpmPageParser | None, str | None]:
    try:
        html = raw_html.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "Census page is not UTF-8 HTML"
    parser = _CensusSpmPageParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - malformed upstream HTML
        return None, f"Census page did not parse: {exc}"
    return parser, None


def _census_spm_normalized_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _census_spm_report_identity(
    report_url: str, year: str
) -> tuple[tuple[int, str] | None, str | None]:
    """Bind a report title year to its actual P60 publication path."""

    if not re.fullmatch(r"\d{4}", year):
        return None, f"Census SPM period must be YYYY, got {year!r}"
    parsed = urllib.parse.urlparse(report_url)
    match = re.fullmatch(
        r"/library/publications/(\d{4})/demo/p60-(\d+)\.html",
        parsed.path,
        re.IGNORECASE,
    )
    if match is None or parsed.params or parsed.query or parsed.fragment:
        return None, f"report URL is not the reviewed P60 path: {report_url!r}"
    publication_year = int(match.group(1))
    earliest_publication_year = int(year) + 1
    if publication_year < earliest_publication_year:
        return None, (
            f"report URL publication year {publication_year} predates the "
            f"earliest valid year {earliest_publication_year} for the {year} "
            f"outcome: {report_url!r}"
        )
    return (publication_year, match.group(2)), None


def census_spm_report_url(
    raw_html: bytes,
    year: str,
    *,
    publications_url: str,
    allowed_hosts: list[str] | tuple[str, ...],
    require_latest: bool = False,
) -> tuple[str | None, str | None]:
    """Select exactly one annual ``Poverty in the United States`` report.

    With ``require_latest``, a later report on the index proves the target's
    first-print capture window was missed. Historical reports remain usable
    for runtime anchor checks and analyst base-rate retrieval.
    """

    if not re.fullmatch(r"\d{4}", year):
        raise ValueError(f"Census SPM period must be YYYY, got {year!r}")
    parser, refusal = _census_spm_page(raw_html)
    if refusal or parser is None:
        return None, refusal

    reports: dict[int, set[str]] = {}
    title_pattern = re.compile(r"\bpoverty in the united states (\d{4})\b")
    for href, label in parser.links:
        url = urllib.parse.urljoin(publications_url, href)
        match = title_pattern.search(_census_spm_normalized_text(label))
        if match is None:
            continue
        report_year = int(match.group(1))
        _identity, identity_refusal = _census_spm_report_identity(url, str(report_year))
        if identity_refusal:
            return None, (
                "Census annual report link does not match the reviewed "
                f"P60 publication path for {report_year}: {identity_refusal}"
            )
        try:
            _require_allowed_host(url, allowed_hosts)
        except ValueError as exc:
            return None, str(exc)
        reports.setdefault(report_year, set()).add(url)

    target_year = int(year)
    matches = reports.get(target_year, set())
    later = sorted(report_year for report_year in reports if report_year > target_year)
    if require_latest and later:
        return None, (
            f"Census report for {year} is no longer the latest annual print "
            f"(found {later[-1]}); the first-print window was missed"
        )
    if not matches:
        return None, None
    if len(matches) != 1:
        return None, (
            f"expected one 'Poverty in the United States: {year}' report, "
            f"found {len(matches)}"
        )
    return next(iter(matches)), None


def census_spm_table_url(
    raw_html: bytes,
    year: str,
    *,
    report_url: str,
    allowed_hosts: list[str] | tuple[str, ...],
    table_filename: str = "tableB-2.xlsx",
) -> tuple[str | None, str | None]:
    """Select the report's one official Table B-2 XLSX artifact."""

    if not re.fullmatch(r"\d{4}", year):
        return None, f"Census SPM period must be YYYY, got {year!r}"
    parser, refusal = _census_spm_page(raw_html)
    if refusal or parser is None:
        return None, refusal
    page_text = _census_spm_normalized_text(" ".join(parser.text))
    expected_title = _census_spm_normalized_text(
        f"Poverty in the United States: {year}"
    )
    if expected_title not in page_text:
        return None, (
            f"report page does not identify {expected_title!r}; wrong annual artifact"
        )

    matches: set[str] = set()
    wrong_formats: set[str] = set()
    expected_name = table_filename.lower()
    try:
        _require_allowed_host(report_url, allowed_hosts)
    except ValueError as exc:
        return None, str(exc)
    report_identity, refusal = _census_spm_report_identity(report_url, year)
    if refusal or report_identity is None:
        return None, refusal
    _publication_year, report_number = report_identity
    expected_path = (
        f"/programs-surveys/demo/tables/p60/{report_number}/{table_filename}"
    )
    for href, label in parser.links:
        url = urllib.parse.urljoin(report_url, href)
        parsed = urllib.parse.urlparse(url)
        filename = parsed.path.rsplit("/", 1)[-1]
        descriptor = _census_spm_normalized_text(f"{label} {filename}")
        is_table_b2 = "table b 2" in descriptor
        if not is_table_b2:
            continue
        try:
            _require_allowed_host(url, allowed_hosts)
        except ValueError as exc:
            return None, str(exc)
        if (
            filename.lower() == expected_name
            and parsed.path.lower() == expected_path.lower()
            and (parsed.hostname or "").lower() == "www2.census.gov"
            and not (parsed.params or parsed.query or parsed.fragment)
        ):
            matches.add(url)
        else:
            wrong_formats.add(url)
    if len(matches) == 1:
        return next(iter(matches)), None
    if len(matches) > 1:
        return None, f"expected one Table B-2 XLSX, found {len(matches)}"
    if wrong_formats:
        return None, (
            "Census published a Table B-2 link but not the reviewed "
            f"{table_filename!r} artifact; extend the adapter"
        )
    return None, (
        "Census annual report page has no reviewed Table B-2 XLSX link; "
        "the publication is incomplete or its layout changed"
    )


_CENSUS_SPM_MONTHS = {
    month.lower(): index
    for index, month in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}


def census_spm_report_publication_date(
    raw_html: bytes, year: str, *, report_url: str
) -> tuple[dt.date | None, str | None]:
    """Bind the title's adjacent publication date to its P60 path year."""

    if not re.fullmatch(r"\d{4}", year):
        return None, f"Census SPM period must be YYYY, got {year!r}"
    report_identity, refusal = _census_spm_report_identity(report_url, year)
    if refusal or report_identity is None:
        return None, refusal
    publication_year, _report_number = report_identity
    parser, refusal = _census_spm_page(raw_html)
    if refusal or parser is None:
        return None, refusal
    expected_title = _census_spm_normalized_text(
        f"Poverty in the United States: {year}"
    )
    month_pattern = "|".join(_CENSUS_SPM_MONTHS)
    date_pattern = re.compile(rf"({month_pattern}) ([0-3]?\d) (\d{{4}})")
    visible = [text.strip() for text in parser.text if text.strip()]
    candidates: set[dt.date] = set()
    for index, text in enumerate(visible):
        if _census_spm_normalized_text(text) != expected_title:
            continue
        # Census renders the publication date directly beneath the content
        # title. Joining a few adjacent text nodes tolerates harmless markup
        # around the month/day/year while excluding footer revision dates.
        following = visible[index + 1 : index + 9]
        for width in range(1, min(3, len(following)) + 1):
            normalized = _census_spm_normalized_text(" ".join(following[:width]))
            match = date_pattern.fullmatch(normalized)
            if match is None:
                continue
            try:
                candidates.add(
                    dt.date(
                        int(match.group(3)),
                        _CENSUS_SPM_MONTHS[match.group(1)],
                        int(match.group(2)),
                    )
                )
            except ValueError:
                return None, f"invalid Census report publication date: {normalized!r}"
    if len(candidates) != 1:
        return None, (
            "expected exactly one publication date directly beneath "
            f"'Poverty in the United States: {year}', found "
            f"{len(candidates)}"
        )
    publication_day = next(iter(candidates))
    if publication_day.year != publication_year:
        return None, (
            f"Census report publication date year {publication_day.year} "
            f"does not match P60 URL publication year {publication_year}: "
            f"{report_url!r}"
        )
    return publication_day, None


def census_spm_first_print_gate(
    publication_day: dt.date,
    capture_day: dt.date,
    window_days: int,
) -> str | None:
    """Bound mutable P60 capture to the reviewed first-print window."""

    if capture_day < publication_day:
        return (
            f"capture day {capture_day} predates the official report "
            f"publication day {publication_day}"
        )
    last_day = publication_day + dt.timedelta(days=window_days)
    if capture_day > last_day:
        return (
            f"report published {publication_day}, but capture {capture_day} "
            f"missed the {window_days}-day first-print window ending {last_day}"
        )
    return None


def census_spm_effective_capture_day(
    retrieved_at: str,
) -> tuple[dt.date | None, str | None]:
    """Return a post-response day so midnight straddles fail closed."""

    decision_at = utc_now()
    try:
        retrieved_day = dt.date.fromisoformat(retrieved_at[:10])
        decision_day = dt.date.fromisoformat(decision_at[:10])
    except ValueError:
        return None, (
            "invalid Census capture timestamp: "
            f"retrievedAt={retrieved_at!r}, decisionAt={decision_at!r}"
        )
    return max(retrieved_day, decision_day), None


def _xlsx_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xlsx_column_index(letters: str) -> int:
    column = 0
    for letter in letters:
        column = column * 26 + ord(letter) - ord("A") + 1
    return column - 1


def _xlsx_cell_coordinates(reference: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Z]+)([1-9]\d*)", reference)
    if match is None:
        raise ValueError(f"invalid XLSX cell reference {reference!r}")
    return int(match.group(2)) - 1, _xlsx_column_index(match.group(1))


def _xlsx_range_coordinates(
    reference: str,
) -> tuple[int, int, int, int]:
    parts = reference.split(":")
    if len(parts) not in {1, 2}:
        raise ValueError(f"invalid XLSX range reference {reference!r}")
    start_row, start_column = _xlsx_cell_coordinates(parts[0])
    end_row, end_column = _xlsx_cell_coordinates(parts[-1])
    if start_row > end_row or start_column > end_column:
        raise ValueError(f"reversed XLSX range reference {reference!r}")
    return start_row, start_column, end_row, end_column


def _xlsx_xml(archive: zipfile.ZipFile, name: str, *, limit: int = 10_000_000):
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise ValueError(f"workbook is missing {name}") from exc
    if info.file_size > limit:
        raise ValueError(f"workbook XML member {name} exceeds size limit")
    try:
        return ET.fromstring(archive.read(info))
    except ET.ParseError as exc:
        raise ValueError(f"workbook XML member {name} did not parse: {exc}") from exc


def census_spm_xlsx_grid(
    raw: bytes, spec: Mapping[str, Any]
) -> tuple[list[list[Any]] | None, str | None]:
    """Extract the reviewed Table B-2 sheet using only OOXML primitives."""

    if len(raw) > 25_000_000:
        return None, "Census workbook exceeds the 25 MB adapter limit"
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (OSError, zipfile.BadZipFile) as exc:
        return None, f"workbook parse failed: {exc}"
    try:
        with archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(names) != len(set(names)):
                return None, "Census workbook contains duplicate ZIP members"
            if any(member.flag_bits & 0x1 for member in members):
                return None, "Census workbook contains encrypted ZIP members"
            if sum(member.file_size for member in members) > 50_000_000:
                return None, "Census workbook expands beyond the 50 MB limit"
            for name in names:
                member_path = pathlib.PurePosixPath(name)
                if (
                    "\\" in name
                    or member_path.is_absolute()
                    or ".." in member_path.parts
                ):
                    return None, (
                        f"Census workbook contains an unsafe ZIP member path: {name!r}"
                    )
            workbook = _xlsx_xml(archive, "xl/workbook.xml")
            relationships = _xlsx_xml(archive, "xl/_rels/workbook.xml.rels")
            accepted_name = _census_spm_normalized_text(spec["sheet_name"])
            sheets = [
                sheet
                for sheet in workbook.iter()
                if _xlsx_local_name(sheet.tag) == "sheet"
                and _census_spm_normalized_text(sheet.attrib.get("name", ""))
                == accepted_name
            ]
            if len(sheets) != 1:
                names = [
                    sheet.attrib.get("name")
                    for sheet in workbook.iter()
                    if _xlsx_local_name(sheet.tag) == "sheet"
                ]
                return None, (
                    "expected exactly one Table B-2 sheet, found "
                    f"{len(sheets)} (sheets: {names!r}); extend the adapter"
                )
            relationship_id = next(
                (
                    value
                    for key, value in sheets[0].attrib.items()
                    if _xlsx_local_name(key) == "id"
                ),
                None,
            )
            relationship = [
                item
                for item in relationships.iter()
                if _xlsx_local_name(item.tag) == "Relationship"
                and item.attrib.get("Id") == relationship_id
            ]
            if len(relationship) != 1:
                return None, "Table B-2 sheet relationship is missing or ambiguous"
            if relationship[0].attrib.get("TargetMode") == "External":
                return None, "Table B-2 sheet relationship is external"
            target = relationship[0].attrib.get("Target", "")
            if target.startswith("/"):
                sheet_path = target.lstrip("/")
            else:
                sheet_path = posixpath.normpath(posixpath.join("xl", target))
            if sheet_path.startswith("../") or not sheet_path.startswith("xl/"):
                return None, "Table B-2 sheet relationship leaves xl/"
            worksheet = _xlsx_xml(archive, sheet_path)

            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared = _xlsx_xml(archive, "xl/sharedStrings.xml")
                for item in shared.iter():
                    if _xlsx_local_name(item.tag) != "si":
                        continue
                    shared_strings.append(
                        "".join(
                            node.text or ""
                            for node in item.iter()
                            if _xlsx_local_name(node.tag) == "t"
                        )
                    )

            cells: dict[tuple[int, int], Any] = {}
            max_row = max_column = -1
            for cell in worksheet.iter():
                if _xlsx_local_name(cell.tag) != "c":
                    continue
                reference = cell.attrib.get("r", "")
                try:
                    row_index, column_index = _xlsx_cell_coordinates(reference)
                except ValueError as exc:
                    return None, str(exc)
                if row_index >= 10_000 or column_index >= 512:
                    return None, "Table B-2 sheet dimensions exceed adapter limits"
                key = (row_index, column_index)
                if key in cells:
                    return None, f"duplicate XLSX cell reference {reference!r}"
                if any(_xlsx_local_name(node.tag) == "f" for node in cell):
                    return None, (
                        f"formula cell {reference!r} is not admissible in "
                        "resolution data"
                    )
                value_node = next(
                    (node for node in cell if _xlsx_local_name(node.tag) == "v"),
                    None,
                )
                cell_type = cell.attrib.get("t")
                text = value_node.text if value_node is not None else None
                try:
                    if cell_type == "s":
                        value: Any = shared_strings[int(str(text))]
                    elif cell_type == "inlineStr":
                        value = "".join(
                            node.text or ""
                            for node in cell.iter()
                            if _xlsx_local_name(node.tag) == "t"
                        )
                    elif cell_type in {"str", "e"}:
                        value = text or ""
                    elif cell_type == "b":
                        value = text == "1"
                    elif text in {None, ""}:
                        value = ""
                    else:
                        value = float(text)
                except (IndexError, TypeError, ValueError) as exc:
                    return None, (f"invalid value in XLSX cell {reference!r}: {exc}")
                cells[key] = value
                max_row = max(max_row, row_index)
                max_column = max(max_column, column_index)

            # Census encodes every header ancestor as a merged OOXML range:
            # e.g. G4:K4 = Under 18 years and H5:K5 = Below Poverty.
            # Propagate each top-left label across its range so the pure grid
            # parser can authenticate the complete column path rather than a
            # hard-coded letter.
            for merge in worksheet.iter():
                if _xlsx_local_name(merge.tag) != "mergeCell":
                    continue
                reference = merge.attrib.get("ref", "")
                try:
                    start_row, start_column, end_row, end_column = (
                        _xlsx_range_coordinates(reference)
                    )
                except ValueError as exc:
                    return None, str(exc)
                if end_row >= 10_000 or end_column >= 512:
                    return None, "Table B-2 merged range exceeds adapter limits"
                source = cells.get((start_row, start_column), "")
                if source == "":
                    return None, (
                        f"merged XLSX range {reference!r} has no top-left value"
                    )
                for row_index in range(start_row, end_row + 1):
                    for column_index in range(start_column, end_column + 1):
                        existing = cells.get((row_index, column_index), "")
                        if existing not in {"", source}:
                            return None, (
                                f"merged XLSX range {reference!r} overlaps a "
                                "different cell value"
                            )
                        cells[(row_index, column_index)] = source
                max_row = max(max_row, end_row)
                max_column = max(max_column, end_column)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return None, f"workbook parse failed: {exc}"

    if max_row < 0 or max_column < 0:
        return None, "Table B-2 sheet has no cells"
    grid = [
        [cells.get((row, column), "") for column in range(max_column + 1)]
        for row in range(max_row + 1)
    ]
    return grid, None


_CENSUS_SPM_SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_CENSUS_SPM_REQUIRED_ANCHOR_YEARS = {str(year) for year in range(2019, 2025)}
_CENSUS_SPM_LEGACY_TRANSITION_VALUES = {
    "2019": {12.5, 12.6},
    "2020": {9.7},
}


def _census_spm_year_cell(value: Any) -> tuple[int, str | None] | None:
    """Return a year and optional footnote from one standalone cell."""

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric.is_integer() and 1900 <= numeric <= 2200:
            return int(numeric), None
        return None
    text = str(value).strip().translate(_CENSUS_SPM_SUPERSCRIPT_DIGITS)
    text = re.sub(r"\s+", "", text)
    match = re.fullmatch(r"(\d{4})(?:\[?(\d{1,2})\]?|(\*{1,2}))?", text)
    if match is None:
        return None
    year = int(match.group(1))
    if not 1900 <= year <= 2200:
        return None
    return year, match.group(2) or match.group(3)


def _census_spm_revised_methodology_footnotes(
    grid: list[list[Any]],
) -> set[str]:
    """Identify footnotes that explicitly authenticate revised SPM rows."""

    footnotes: set[str] = set()
    pattern = re.compile(
        r"^(\d{1,2}) estimates reflect the implementation of revised "
        r"supplemental poverty measure methodology\b"
    )
    for row in grid:
        for cell in row:
            if not isinstance(cell, str):
                continue
            match = pattern.search(_census_spm_normalized_text(cell))
            if match is not None:
                footnotes.add(match.group(1))
    return footnotes


def census_spm_rate_from_grid(
    grid: list[list[Any]],
    year: str,
    spec: Mapping[str, Any],
    *,
    report_year: str | None = None,
) -> tuple[float | None, str | None]:
    """Read ALL RACES x child / below-poverty / percent, failing closed."""

    if not re.fullmatch(r"\d{4}", year):
        return None, f"Census SPM period must be YYYY, got {year!r}"
    report_year = report_year or year
    if not re.fullmatch(r"\d{4}", report_year):
        return None, f"Census SPM report year must be YYYY, got {report_year!r}"
    title_candidates = [
        _census_spm_normalized_text(cell)
        for row in grid[:7]
        for cell in row
        if isinstance(cell, str)
        and "supplemental poverty measure" in _census_spm_normalized_text(cell)
    ]
    if len(set(title_candidates)) != 1:
        return None, (
            "expected exactly one Supplemental Poverty Measure title cell, "
            f"found {len(set(title_candidates))}"
        )
    title = title_candidates[0]
    if (
        "table b 2" not in title
        or re.search(rf"\bto {re.escape(report_year)}(?: ?\d{{1,2}})?$", title) is None
    ):
        return None, (
            "Table B-2 title is not the Supplemental Poverty Measure range "
            f"ending in report year {report_year}; wrong or later workbook"
        )

    section_label = _census_spm_normalized_text(spec["section_label"])
    section_hits: dict[int, list[int]] = {}
    for row_index, row in enumerate(grid):
        columns = [
            column_index
            for column_index, cell in enumerate(row)
            if isinstance(cell, str)
            and _census_spm_normalized_text(cell) == section_label
        ]
        if columns:
            section_hits[row_index] = columns
    if len(section_hits) != 1:
        return None, (
            f"expected exactly one {spec['section_label']!r} section row, "
            f"found {len(section_hits)} at {sorted(section_hits)!r}"
        )
    section_row, section_columns = next(iter(section_hits.items()))
    # Census merges the section heading across the table width. The grid
    # reader intentionally propagates merged labels, so authenticate one row
    # and recover the original label column from its leftmost occurrence.
    label_column = min(section_columns)

    column_count = max((len(row) for row in grid[:section_row]), default=0)

    def unique_header_column(
        path_key: str, description: str
    ) -> tuple[int | None, str | None]:
        header_path = {_census_spm_normalized_text(label) for label in spec[path_key]}
        candidate_columns: list[int] = []
        for column_index in range(column_count):
            column_headers = {
                _census_spm_normalized_text(row[column_index])
                for row in grid[:section_row]
                if column_index < len(row) and isinstance(row[column_index], str)
            }
            if header_path.issubset(column_headers):
                candidate_columns.append(column_index)
        if len(candidate_columns) != 1:
            return None, (
                f"expected exactly one {description} column, found "
                f"{len(candidate_columns)} at {candidate_columns!r}"
            )
        return candidate_columns[0], None

    percent_column, refusal = unique_header_column(
        "header_path", "Under 18 years / Below Poverty / Percent"
    )
    if refusal or percent_column is None:
        return None, refusal
    total_column, refusal = unique_header_column(
        "total_header_path", "Under 18 years / Total"
    )
    if refusal or total_column is None:
        return None, refusal
    poverty_count_column, refusal = unique_header_column(
        "poverty_count_header_path",
        "Under 18 years / Below Poverty / Number",
    )
    if refusal or poverty_count_column is None:
        return None, refusal

    row_hits: list[tuple[int, str | None]] = []
    for row_index in range(section_row + 1, len(grid)):
        row = grid[row_index]
        label = row[label_column] if label_column < len(row) else ""
        year_cell = _census_spm_year_cell(label)
        if year_cell is not None:
            row_year, footnote = year_cell
            if row_year == int(year):
                row_hits.append((row_index, footnote))
            continue
        if _census_spm_normalized_text(label):
            break
    if len(row_hits) > 1:
        methodology_footnotes = _census_spm_revised_methodology_footnotes(grid)
        authenticated = [
            row_index
            for row_index, footnote in row_hits
            if footnote in methodology_footnotes
        ]
        if len(authenticated) == 1:
            data_row = authenticated[0]
        else:
            return None, (
                f"expected exactly one {year} row inside ALL RACES, found "
                f"{len(row_hits)}; duplicate transition rows require exactly "
                "one row carrying an authenticated revised-methodology "
                f"footnote, found {len(authenticated)}"
            )
    elif len(row_hits) == 1:
        data_row = row_hits[0][0]
    else:
        return None, (f"expected exactly one {year} row inside ALL RACES, found 0")
    required_column = max(percent_column, total_column, poverty_count_column)
    if required_column >= len(grid[data_row]):
        return None, "ALL RACES year row is shorter than the required child columns"
    value = grid[data_row][percent_column]
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 <= float(value) <= 100
    ):
        return None, f"child SPM percent cell is not in [0, 100]: {value!r}"
    total = grid[data_row][total_column]
    poverty_count = grid[data_row][poverty_count_column]
    if (
        isinstance(total, bool)
        or not isinstance(total, (int, float))
        or not math.isfinite(float(total))
        or float(total) <= 0
    ):
        return None, f"child population total is not positive: {total!r}"
    if (
        isinstance(poverty_count, bool)
        or not isinstance(poverty_count, (int, float))
        or not math.isfinite(float(poverty_count))
        or not 0 <= float(poverty_count) <= float(total)
    ):
        return None, (
            "child below-poverty count is not between zero and the child "
            f"population total: {poverty_count!r}"
        )
    implied_percent = 100 * float(poverty_count) / float(total)
    if abs(float(value) - implied_percent) > 0.15:
        return None, (
            "child SPM percent fails the Table B-2 arithmetic cross-check: "
            f"published {float(value)}, implied {implied_percent:.6g} from "
            f"{float(poverty_count):g}/{float(total):g}"
        )
    return float(value), None


def census_spm_fetch_year(
    spec: Mapping[str, Any], year: str, *, require_latest: bool = False
) -> tuple[float | None, bytes | None, str, str, str | None]:
    """Fetch one annual report's Table B-2 and parse the child SPM rate."""

    if not re.fullmatch(r"\d{4}", year):
        return (
            None,
            None,
            str(spec["source_url"]),
            utc_now(),
            (f"Census SPM period must be YYYY, got {year!r}"),
        )
    publications_url = str(spec["publications_url"])
    try:
        index_raw, index_retrieved_at, index_url = http_get(
            publications_url, allowed_hosts=spec["allowed_hosts"]
        )
    except (OSError, ValueError) as exc:
        return (
            None,
            None,
            publications_url,
            utc_now(),
            (f"Census publications index fetch failed: {exc}"),
        )
    report_url, refusal = census_spm_report_url(
        index_raw,
        year,
        publications_url=index_url,
        allowed_hosts=spec["allowed_hosts"],
        require_latest=require_latest,
    )
    if refusal:
        return None, None, index_url, index_retrieved_at, refusal
    if report_url is None:
        return None, None, index_url, index_retrieved_at, None
    try:
        report_raw, report_retrieved_at, final_report_url = http_get(
            report_url, allowed_hosts=spec["allowed_hosts"]
        )
    except (OSError, ValueError) as exc:
        return (
            None,
            None,
            report_url,
            utc_now(),
            (f"Census annual report page fetch failed: {exc}"),
        )
    if final_report_url != report_url:
        return (
            None,
            None,
            final_report_url,
            report_retrieved_at,
            (
                "Census annual report fetch redirected away from the exact "
                f"indexed P60 artifact: {report_url!r} -> {final_report_url!r}"
            ),
        )
    publication_day, refusal = census_spm_report_publication_date(
        report_raw, year, report_url=final_report_url
    )
    if refusal or publication_day is None:
        return None, None, final_report_url, report_retrieved_at, refusal
    report_capture_day, refusal = census_spm_effective_capture_day(report_retrieved_at)
    if refusal or report_capture_day is None:
        return None, None, final_report_url, report_retrieved_at, refusal
    refusal = census_spm_first_print_gate(
        publication_day,
        report_capture_day,
        int(spec["first_print_window_days"]),
    )
    if refusal:
        return None, None, final_report_url, report_retrieved_at, refusal
    table_url, refusal = census_spm_table_url(
        report_raw,
        year,
        report_url=final_report_url,
        allowed_hosts=spec["allowed_hosts"],
        table_filename=str(spec["table_filename"]),
    )
    if refusal:
        return None, None, final_report_url, report_retrieved_at, refusal
    if table_url is None:
        return None, None, final_report_url, report_retrieved_at, None
    try:
        raw, retrieved_at, final_url = http_get(
            table_url, allowed_hosts=spec["allowed_hosts"]
        )
    except (OSError, ValueError) as exc:
        return (
            None,
            None,
            table_url,
            utc_now(),
            (f"Census Table B-2 fetch failed: {exc}"),
        )
    final_name = urllib.parse.urlparse(final_url).path.rsplit("/", 1)[-1]
    if final_url != table_url:
        return (
            None,
            raw,
            final_url,
            retrieved_at,
            (
                "Census Table B-2 fetch redirected away from the reviewed exact "
                f"artifact URL: {table_url!r} -> {final_url!r}"
            ),
        )
    table_capture_day, refusal = census_spm_effective_capture_day(retrieved_at)
    if refusal or table_capture_day is None:
        return None, raw, final_url, retrieved_at, refusal
    refusal = census_spm_first_print_gate(
        publication_day,
        table_capture_day,
        int(spec["first_print_window_days"]),
    )
    if refusal:
        return None, raw, final_url, retrieved_at, refusal
    if final_name.lower() != str(spec["table_filename"]).lower():
        return (
            None,
            raw,
            final_url,
            retrieved_at,
            (
                f"fetched filename {final_name!r} is not the reviewed "
                f"{spec['table_filename']!r}"
            ),
        )
    grid, refusal = census_spm_xlsx_grid(raw, spec)
    if refusal or grid is None:
        return None, raw, final_url, retrieved_at, refusal
    value, refusal = census_spm_rate_from_grid(grid, year, spec)
    return value, raw, final_url, retrieved_at, refusal


def census_spm_verified_anchors(
    spec: Mapping[str, Any],
) -> dict[str, float] | None:
    """Return revised-methodology anchors, or None while deliberately unarmed."""

    anchors = spec.get("anchors")
    if (
        spec.get("anchor_status") != "VERIFIED_REVISED_METHODOLOGY"
        or not isinstance(anchors, dict)
        or set(anchors) != _CENSUS_SPM_REQUIRED_ANCHOR_YEARS
    ):
        return None
    verified: dict[str, float] = {}
    for year, expected in anchors.items():
        if (
            not isinstance(year, str)
            or not re.fullmatch(r"\d{4}", year)
            or year not in _CENSUS_SPM_REQUIRED_ANCHOR_YEARS
        ):
            return None
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            return None
        value = float(expected)
        if not math.isfinite(value) or not 0 <= value <= 100:
            return None
        verified[year] = value
    if any(
        verified[year] in legacy_values
        for year, legacy_values in _CENSUS_SPM_LEGACY_TRANSITION_VALUES.items()
    ):
        return None
    return verified


def census_spm_anchor_mismatches(
    values: Mapping[str, float | None], anchors: Mapping[str, float]
) -> list[str]:
    """Compare all live revised-methodology anchors exactly."""

    if set(anchors) != _CENSUS_SPM_REQUIRED_ANCHOR_YEARS:
        return [
            f"verified anchors must cover exactly 2019-2024; got {sorted(anchors)!r}"
        ]
    problems = []
    for year, expected in sorted(anchors.items()):
        got = values.get(year)
        if got is None:
            problems.append(f"{year}=missing (official {expected})")
        elif got != expected:
            problems.append(f"{year}={got} (official {expected})")
    return problems


IRS_SOI_PUB1304_BINDING_TEMPLATE_KEYS = {
    "adapter",
    "sourceUrl",
    "sourceSeriesId",
    "field",
    "table",
    "transform",
    "releasePolicy",
}
IRS_SOI_PUB1304_BINDING_DERIVED_KEYS = {"expectedReleaseWindow", "allowedHosts"}
# Backward-compatible name for the original ACTC claimant-count spec. New
# Table 3.3 series carry their transform in the reviewed per-series spec.
IRS_SOI_PUB1304_TRANSFORM = {"operation": "multiply", "factor": 1e-06}


def irs_soi_pub1304_binding_template(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "adapter": "irs-soi-pub1304",
        "sourceUrl": spec["source_url"],
        "sourceSeriesId": spec["series_id"],
        "field": spec["field"],
        "table": spec["source_table"],
        "transform": dict(spec["value_transform"]),
        "releasePolicy": "first_print",
    }


def irs_soi_pub1304_binding_matches_spec(
    binding: Mapping[str, Any], spec: Mapping[str, Any]
) -> bool:
    """Require the registered binding to be exactly the adapter's template."""

    if not isinstance(binding, dict):
        return False
    if (
        set(binding) - IRS_SOI_PUB1304_BINDING_DERIVED_KEYS
        != IRS_SOI_PUB1304_BINDING_TEMPLATE_KEYS
    ):
        return False
    projected = {key: binding[key] for key in IRS_SOI_PUB1304_BINDING_TEMPLATE_KEYS}
    return canonical_bytes(projected) == canonical_bytes(
        irs_soi_pub1304_binding_template(spec)
    )


def _irs_soi_normalized_text(value: Any) -> str:
    """Collapse whitespace, lowercase, and strip footnote markers."""

    text = " ".join(str(value).split()).lower()
    text = re.sub(r"\s*\[\d+\]\s*$", "", text)
    return text.strip().rstrip(":").strip()


def irs_soi_pub1304_grid(raw: bytes, spec: Mapping[str, Any]):
    """Extract the Table 3.3 sheet as a row grid, failing closed.

    Returns ``(grid, refusal)``. The workbook boundary is xlrd (the only
    parser for IRS's legacy BIFF .xls prints); everything after the grid is
    pure logic so tests can arm both real workbooks and synthetic grids.
    """

    try:
        import xlrd  # noqa: PLC0415 - optional resolver dependency
    except ImportError:
        return None, (
            "xlrd is unavailable; install the resolver extra "
            "(xlrd==2.0.1) to parse IRS SOI .xls prints"
        )
    try:
        book = xlrd.open_workbook(file_contents=raw)
    except Exception as exc:  # noqa: BLE001 - any parse failure fails closed
        return None, f"workbook parse failed: {exc}"
    sheet_name = str(spec["sheet_name"])
    if sheet_name not in book.sheet_names():
        return None, (
            f"sheet {sheet_name!r} not found (sheets: {book.sheet_names()!r}); "
            "IRS changed the workbook layout — extend the adapter"
        )
    sheet = book.sheet_by_name(sheet_name)
    grid = [
        [sheet.cell_value(row, col) for col in range(sheet.ncols)]
        for row in range(sheet.nrows)
    ]
    return grid, None


def irs_soi_pub1304_count_from_grid(
    grid: list[list[Any]], spec: Mapping[str, Any]
) -> tuple[float | None, str | None]:
    """Read one reviewed nonnegative-integer value from an extracted grid.

    Fails closed on ambiguity: the concept header, requested subheader, and
    all-returns row must each match exactly once. Amount specs also authenticate
    the workbook's printed unit marker before any transform is applied.
    """

    required_scale_marker = spec.get("required_scale_marker")
    if required_scale_marker is not None:
        marker = _irs_soi_normalized_text(required_scale_marker)
        marker_cell = spec.get("scale_marker_cell")
        if (
            not isinstance(marker_cell, (list, tuple))
            or len(marker_cell) != 2
            or any(
                isinstance(index, bool) or not isinstance(index, int)
                for index in marker_cell
            )
            or any(index < 0 for index in marker_cell)
        ):
            return None, f"invalid reviewed scale marker cell: {marker_cell!r}"
        marker_row, marker_column = marker_cell
        actual_marker = (
            grid[marker_row][marker_column]
            if marker_row < len(grid) and marker_column < len(grid[marker_row])
            else None
        )
        if (
            not isinstance(actual_marker, str)
            or _irs_soi_normalized_text(actual_marker) != marker
        ):
            return None, (
                f"expected exact workbook scale declaration {marker!r} at "
                f"cell ({marker_row}, {marker_column}); found "
                f"{actual_marker!r}"
            )

    accepted = {_irs_soi_normalized_text(label) for label in spec["column_labels"]}
    header_hits: list[tuple[int, int]] = []
    for row_index, row in enumerate(grid[:12]):
        for col_index, cell in enumerate(row):
            if isinstance(cell, str) and _irs_soi_normalized_text(cell) in accepted:
                header_hits.append((row_index, col_index))
    if len(header_hits) != 1:
        return None, (
            f"expected exactly one concept header cell, found "
            f"{len(header_hits)} at {header_hits!r}"
        )
    header_row, header_column = header_hits[0]
    offset = spec.get("subcolumn_offset", 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return None, f"invalid reviewed subcolumn offset: {offset!r}"
    column = header_column + offset
    subcolumn = _irs_soi_normalized_text(spec["subcolumn_label"])
    subcolumn_display = str(spec["subcolumn_label"])
    subcolumn_display = subcolumn_display[:1].upper() + subcolumn_display[1:]
    if not any(
        len(grid[row]) > column
        and isinstance(grid[row][column], str)
        and _irs_soi_normalized_text(grid[row][column]) == subcolumn
        for row in range(header_row + 1, min(header_row + 5, len(grid)))
    ):
        return None, (
            f"concept header offset {offset} has no {subcolumn_display!r} "
            "subheader within four rows; IRS changed the column layout"
        )
    row_label = _irs_soi_normalized_text(spec["row_label"])
    row_hits = [
        row_index
        for row_index, row in enumerate(grid)
        if row and _irs_soi_normalized_text(row[0]) == row_label
    ]
    if len(row_hits) != 1:
        return None, (
            f"expected exactly one {spec['row_label']!r} row, found {len(row_hits)}"
        )
    row_values = grid[row_hits[0]]
    if len(row_values) <= column:
        return None, "all-returns row is shorter than the concept column"
    value = row_values[column]
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
        or not float(value).is_integer()
    ):
        return None, (
            f"published value cell is not a nonnegative whole number: {value!r}"
        )
    return float(value), None


def irs_soi_pub1304_apply_transform(
    spec: Mapping[str, Any], value: float | None
) -> float | None:
    """Apply the exact reviewed per-series transform without extra rounding."""

    if value is None:
        return None
    transform = spec.get("value_transform")
    if not isinstance(transform, dict) or transform.get("operation") != "multiply":
        raise ValueError("IRS SOI spec requires a multiply transform")
    factor = transform.get("factor")
    if isinstance(factor, bool) or not isinstance(factor, (int, float)):
        raise ValueError("IRS SOI transform factor must be numeric")
    numeric_factor = float(factor)
    if not math.isfinite(numeric_factor) or numeric_factor <= 0:
        raise ValueError("IRS SOI transform factor must be positive and finite")
    # The registered factors are decimal unit conversions. Apply their exact
    # decimal spellings so JSON output does not expose binary-float artifacts
    # such as 34533.251000000004 for a thousand-to-million conversion.
    return float(Decimal(str(value)) * Decimal(str(factor)))


def irs_soi_pub1304_identity_refusal(
    grid: list[list[Any]], final_url: str, year: str
) -> str | None:
    """Refuse a workbook that is not THIS tax year's Table 3.3 print.

    Headers, anchors, and integer checks cannot tell one year's workbook
    from another's — a redirect or mirror serving the wrong file would
    otherwise grade the wrong tax year. The printed title names the tax
    year and the official filename encodes it; require both.
    """

    expected_name = f"{int(year) % 100:02d}in33ar.xls"
    final_name = urllib.parse.urlparse(final_url).path.rsplit("/", 1)[-1]
    if final_name != expected_name:
        return (
            f"fetched filename {final_name!r} is not the tax year's "
            f"official {expected_name!r}"
        )
    title_cells = [
        _irs_soi_normalized_text(cell)
        for row in grid[:3]
        for cell in row[:3]
        if isinstance(cell, str) and cell.strip()
    ]
    token = f"tax year {year}"
    if not any(token in cell for cell in title_cells):
        return f"workbook title does not name {token!r}; wrong or relabeled print"
    return None


def irs_soi_pub1304_fetch_year(
    spec: Mapping[str, Any], year: str
) -> tuple[float | None, bytes | None, str, str, str | None]:
    """Fetch the tax year's Table 3.3 workbook and parse its reviewed cell.

    Returns the positive integer printed in the workbook (the raw anchor
    unit); callers apply the registered per-series transform. A missing .xls
    with no .xlsx sibling defers as not-yet-published; a present .xlsx sibling
    refuses instead of guessing at an unparsed format.
    """

    if not re.fullmatch(r"\d{4}", year):
        return (
            None,
            None,
            str(spec["source_url"]),
            utc_now(),
            (f"tax year must be YYYY, got {year!r}"),
        )
    template = str(spec["file_url_template"])
    yy = int(year) % 100
    xls_url = template.format(yy=f"{yy:02d}", ext="xls")
    try:
        raw, retrieved_at, final_url = http_get(
            xls_url, allowed_hosts=spec["allowed_hosts"]
        )
    except (OSError, ValueError):
        xlsx_url = template.format(yy=f"{yy:02d}", ext="xlsx")
        try:
            http_get(xlsx_url, allowed_hosts=spec["allowed_hosts"])
        except (OSError, ValueError):
            # Neither format exists: the print is not yet published.
            return None, None, xls_url, utc_now(), None
        return (
            None,
            None,
            xlsx_url,
            utc_now(),
            ("IRS published Table 3.3 as .xlsx; extend the adapter before resolving"),
        )
    grid, refusal = irs_soi_pub1304_grid(raw, spec)
    if refusal or grid is None:
        return None, raw, final_url, retrieved_at, refusal
    refusal = irs_soi_pub1304_identity_refusal(grid, final_url, year)
    if refusal:
        return None, raw, final_url, retrieved_at, refusal
    value, refusal = irs_soi_pub1304_count_from_grid(grid, spec)
    return value, raw, final_url, retrieved_at, refusal


def irs_soi_pub1304_fetch_normalized_year(
    spec: Mapping[str, Any], year: str
) -> tuple[float | None, bytes | None, str, str, str | None]:
    """Fetch one year and return its value in the registered target unit."""

    value, raw, url, retrieved_at, refusal = irs_soi_pub1304_fetch_year(spec, year)
    if refusal:
        return None, raw, url, retrieved_at, refusal
    return (
        irs_soi_pub1304_apply_transform(spec, value),
        raw,
        url,
        retrieved_at,
        None,
    )


def irs_soi_pub1304_verified_anchors(
    spec: Mapping[str, Any],
) -> dict[str, float] | None:
    """Return admitted positive-integer anchors or None while unarmed."""

    anchors = spec.get("anchors")
    if (
        spec.get("anchor_status") != "VERIFIED"
        or not isinstance(anchors, dict)
        or len(anchors) < 3
    ):
        return None
    verified: dict[str, float] = {}
    for year, expected in anchors.items():
        if not isinstance(year, str) or not re.fullmatch(r"\d{4}", year):
            return None
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            return None
        value = float(expected)
        if not math.isfinite(value) or value <= 0 or not value.is_integer():
            return None
        verified[year] = value
    return verified


def irs_soi_pub1304_anchor_mismatches(
    values: Mapping[str, float | None], anchors: Mapping[str, float]
) -> list[str]:
    """Compare every live-retrieved Table 3.3 anchor exactly."""

    if len(anchors) < 3:
        return [f"only {len(anchors)} verified anchors; at least 3 required"]
    problems = []
    for year, expected in sorted(anchors.items()):
        got = values.get(year)
        if got is None:
            problems.append(f"{year}=missing (official {expected})")
        elif got != expected:
            problems.append(f"{year}={got} (official {expected})")
    return problems


EIA_DNAV_BINDING_TEMPLATE_KEYS = {
    "adapter",
    "sourceUrl",
    "sourceSeriesId",
    "field",
    "table",
    "transform",
    "releasePolicy",
}
EIA_DNAV_BINDING_DERIVED_KEYS = {"expectedReleaseWindow", "allowedHosts"}
EIA_DNAV_ENVELOPE_SCHEMA = "eia_dnav_annual_xls_capture_v1"


def eia_dnav_binding_template(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "adapter": "eia-dnav-xls",
        "sourceUrl": spec["source_url"],
        "sourceSeriesId": spec["series_id"],
        "field": spec["field"],
        "table": spec["source_table"],
        "transform": {"operation": "identity", "factor": 1},
        "releasePolicy": "first_print",
    }


def eia_dnav_binding_matches_spec(
    binding: Mapping[str, Any], spec: Mapping[str, Any]
) -> bool:
    """Require the registered seven-key binding to match the reviewed spec."""

    if not isinstance(binding, dict):
        return False
    if set(binding) - EIA_DNAV_BINDING_DERIVED_KEYS != EIA_DNAV_BINDING_TEMPLATE_KEYS:
        return False
    projected = {key: binding[key] for key in EIA_DNAV_BINDING_TEMPLATE_KEYS}
    if canonical_bytes(projected) != canonical_bytes(eia_dnav_binding_template(spec)):
        return False
    expected_hosts = set(spec["allowed_hosts"])
    allowed_hosts = binding.get("allowedHosts")
    return isinstance(allowed_hosts, list) and set(allowed_hosts) == expected_hosts


def eia_dnav_verified_anchors(
    spec: Mapping[str, Any],
) -> dict[str, float] | None:
    anchors = spec.get("anchors")
    if (
        spec.get("anchor_status") != "VERIFIED"
        or not isinstance(anchors, dict)
        or len(anchors) < 3
    ):
        return None
    verified: dict[str, float] = {}
    for year, expected in anchors.items():
        if not isinstance(year, str) or re.fullmatch(r"\d{4}", year) is None:
            return None
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            return None
        value = float(expected)
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            return None
        verified[year] = value
    return verified


def _eia_dnav_normalized_text(value: Any) -> str:
    return " ".join(str(value).split()).strip()


def _eia_dnav_raw_hrefs(start_tag_text: str) -> list[str | None]:
    """Return every raw href occurrence without entity decoding.

    Use the same quote-aware token boundaries as ``HTMLParser`` itself. A
    global regex can mistake href-looking bytes inside another attribute's
    quoted value for the active anchor href. Bare/boolean occurrences are
    represented by ``None`` so duplicate-attribute ambiguity cannot disappear.
    """

    tag = html_parser.tagfind_tolerant.match(start_tag_text, 1)
    if tag is None:
        return []
    raw_hrefs: list[str | None] = []
    position = tag.end()
    while position < len(start_tag_text):
        attribute = html_parser.attrfind_tolerant.match(start_tag_text, position)
        if attribute is None:
            break
        name, assignment, raw_value = attribute.group(1, 2, 3)
        if name.lower() == "href":
            if assignment is None:
                raw_hrefs.append(None)
            else:
                raw_value = raw_value or ""
                if raw_value[:1] in {"'", '"'} and raw_value[-1:] == raw_value[:1]:
                    raw_value = raw_value[1:-1]
                raw_hrefs.append(raw_value)
        position = attribute.end()
    return raw_hrefs


class _EiaDnavPageParser(HTMLParser):
    """Collect visible text and document-active anchors from one DNav page."""

    _HTML_VOID_ELEMENTS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[tuple[str | None, tuple[str | None, ...], str]] = []
        self._href: str | None = None
        self._raw_hrefs: tuple[str | None, ...] = ()
        self._anchor_text: list[str] = []
        self._anchor_open = False
        self._template_depth = 0
        self.ambiguous_html_seen = False
        self.unauthenticatable_href_seen = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"base", "frameset", "math", "noscript", "select", "svg"}:
            # ``template`` is inert only in the HTML namespace. Rather than
            # misclassify active foreign-content anchors or anchors suppressed
            # by HTML5's select insertion mode, refuse constructs absent from
            # the reviewed official DNav fixture.
            self.ambiguous_html_seen = True
            return
        if tag == "template":
            self._template_depth += 1
            return
        if self._template_depth or tag != "a":
            return
        # HTML5 closes an active anchor when another ``<a>`` start tag begins.
        # Preserve that first candidate instead of overwriting its ambiguity.
        self._finish_anchor()
        # HTMLParser decodes character references in ``attrs``. Recover the
        # href spelling from this structurally identified anchor's original
        # start-tag text so identity is checked against the untouched token.
        raw_hrefs = tuple(_eia_dnav_raw_hrefs(self.get_starttag_text()))
        parsed_hrefs = [value for name, value in attrs if name.lower() == "href"]
        self._href = None
        href_is_authenticatable = len(raw_hrefs) == 1 and len(parsed_hrefs) == 1
        if href_is_authenticatable:
            raw_href = raw_hrefs[0]
            parsed_href = parsed_hrefs[0]
            href_is_authenticatable = bool(raw_href and parsed_href)
        if href_is_authenticatable:
            self._href = raw_hrefs[0]
        elif raw_hrefs or parsed_hrefs:
            # An href-bearing anchor whose sole browser-active token cannot be
            # proven is a page-level refusal. That ambiguity must not disappear
            # through HTML5/Python differences in anchor text or end-tag repair.
            self.unauthenticatable_href_seen = True
        self._raw_hrefs = raw_hrefs
        self._anchor_text = []
        self._anchor_open = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in self._HTML_VOID_ELEMENTS:
            # HTML5 ignores ``/>`` on non-void HTML elements, whereas
            # ``HTMLParser`` synthesizes an end tag. Reject the ambiguous page
            # rather than exposing anchors that a browser may keep nested in
            # raw-text, RCDATA, select, or other non-void content.
            self.ambiguous_html_seen = True
        super().handle_startendtag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._template_depth:
            return
        self.text.append(data)
        if self._anchor_open:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "template":
            if self._template_depth:
                self._template_depth -= 1
            return
        if self._template_depth or tag != "a" or not self._anchor_open:
            return
        self._finish_anchor()

    def close(self) -> None:
        super().close()
        # HTML5 retains an unclosed anchor through EOF. Record it so a malformed
        # candidate cannot disappear merely because its explicit end tag did.
        self._finish_anchor()

    def _finish_anchor(self) -> None:
        if not self._anchor_open:
            return
        self.links.append((self._href, self._raw_hrefs, " ".join(self._anchor_text)))
        self._anchor_open = False
        self._href = None
        self._raw_hrefs = ()
        self._anchor_text = []


_EIA_DNAV_RAW_URL_RE = re.compile(r"https://[A-Za-z0-9.-]+/[A-Za-z0-9/._-]+")
_EIA_DNAV_RAW_HREF_RE = re.compile(r"[A-Za-z0-9/._-]+")


def _require_eia_dnav_raw_url(raw: str, kind: str) -> None:
    """Refuse a noncanonical transport URL before a parser touches it."""

    if not _EIA_DNAV_RAW_URL_RE.fullmatch(raw):
        raise ValueError(f"EIA DNav {kind} URL is not in canonical form: {raw!r}")


def _require_eia_dnav_url(
    url: str,
    *,
    expected_url: str,
    kind: str,
    allowed_hosts: list[str] | tuple[str, ...],
) -> None:
    """Pin one raw DNav transport hop to its exact reviewed identity."""

    _require_eia_dnav_raw_url(url, kind)
    parsed = urllib.parse.urlparse(url)
    _require_allowed_host(url, allowed_hosts)
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"EIA DNav {kind} URL must not contain credentials, a port, "
            f"path parameters, query, or fragment: {url!r}"
        )
    raw_path = parsed.path
    if not re.fullmatch(r"[A-Za-z0-9/._-]+", raw_path):
        raise ValueError(
            f"EIA DNav {kind} path contains characters outside the "
            f"reviewed canonical set: {raw_path!r}"
        )
    if any(segment in ("", ".", "..") for segment in raw_path.split("/")[1:]):
        raise ValueError(
            f"EIA DNav {kind} path contains empty or dot segments: {raw_path!r}"
        )
    if url != expected_url:
        raise ValueError(
            f"EIA DNav {kind} URL is not the exact reviewed URL: "
            f"{url!r} != {expected_url!r}"
        )


def _require_eia_dnav_workbook_href(href: str, spec: Mapping[str, Any]) -> None:
    """Authenticate the untouched official href before any resolution.

    EIA's byte-pinned page currently spells this link with one leading ``..``
    segment. That exact reviewed literal is the sole exception to the normal
    absolute-href shape: no other relative, dot-segment, absolute, or
    scheme-relative spelling is accepted or passed to ``urljoin``.
    """

    if not _EIA_DNAV_RAW_HREF_RE.fullmatch(href):
        raise ValueError(f"EIA DNav workbook href is not in canonical form: {href!r}")
    expected_href = str(spec["workbook_href"])
    if href != expected_href:
        raise ValueError(
            "EIA DNav workbook href is not the exact reviewed raw literal: "
            f"{href!r} != {expected_href!r}"
        )


def eia_dnav_values_from_xls(
    raw: bytes, spec: Mapping[str, Any]
) -> tuple[dict[str, float] | None, str | None]:
    """Authenticate N9040US2 and return its annual workbook cells."""

    try:
        import xlrd  # noqa: PLC0415 - optional resolver dependency
    except ImportError:
        return None, (
            "xlrd is unavailable; install the resolver extra "
            "(xlrd==2.0.1) to parse EIA DNav .xls prints"
        )
    try:
        book = xlrd.open_workbook(file_contents=raw)
    except Exception as exc:  # noqa: BLE001 - fail closed on any BIFF drift
        return None, f"workbook parse failed: {exc}"
    sheet_name = str(spec["sheet_name"])
    if book.sheet_names() != ["Contents", sheet_name]:
        return None, (
            f"expected exact EIA sheet inventory ['Contents', {sheet_name!r}], "
            f"found {book.sheet_names()!r}"
        )
    contents = book.sheet_by_name("Contents")
    sheet = book.sheet_by_name(sheet_name)
    if contents.nrows != 15 or contents.ncols != 6:
        return None, (
            f"EIA contents sheet shape changed to {contents.nrows}x{contents.ncols}"
        )
    if sheet.nrows < 4 or sheet.ncols != 2:
        return None, f"EIA data sheet shape changed to {sheet.nrows}x{sheet.ncols}"
    expected_title = str(spec["series_title"])
    expected_filename = posixpath.basename(
        urlparse(str(spec["workbook_url"])).path
    ).lower()
    identity_checks = (
        (sheet.cell_value(0, 0), "Back to Contents"),
        (sheet.cell_value(0, 1), f"Data 1: {expected_title}"),
        (sheet.cell_value(1, 0), "Sourcekey"),
        (sheet.cell_value(1, 1), spec["series_id"]),
        (sheet.cell_value(2, 0), "Date"),
        (sheet.cell_value(2, 1), expected_title),
        (contents.cell_value(2, 1), expected_title),
        (contents.cell_value(6, 1), sheet_name),
        (contents.cell_value(6, 2), expected_title),
        (contents.cell_value(6, 3), 1.0),
        (contents.cell_value(6, 4), "Annual"),
        (str(contents.cell_value(10, 2)).lower(), expected_filename),
    )
    for actual, expected in identity_checks:
        if _eia_dnav_normalized_text(actual) != _eia_dnav_normalized_text(expected):
            return None, (
                f"EIA workbook identity mismatch: expected {expected!r}, "
                f"found {actual!r}"
            )
    values: dict[str, float] = {}
    previous_year = None
    for row in range(3, sheet.nrows):
        date_value = sheet.cell_value(row, 0)
        value = sheet.cell_value(row, 1)
        if (
            isinstance(date_value, bool)
            or not isinstance(date_value, (int, float))
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
            or not float(value).is_integer()
        ):
            return None, f"invalid EIA annual row {row}: {date_value!r}, {value!r}"
        try:
            stamp = xlrd.xldate_as_datetime(date_value, book.datemode)
        except (OverflowError, TypeError, ValueError) as exc:
            return None, f"invalid EIA annual date at row {row}: {exc}"
        if (stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second) != (
            6,
            30,
            0,
            0,
            0,
        ):
            return None, f"EIA annual row {row} is not dated June 30: {stamp!r}"
        year = str(stamp.year)
        if previous_year is not None and stamp.year != previous_year + 1:
            return None, f"EIA annual rows are not contiguous at {year}"
        if year in values:
            return None, f"duplicate EIA annual row for {year}"
        values[year] = float(value)
        previous_year = stamp.year
    first_year = int(min(values))
    if first_year != spec["first_year"]:
        return None, (
            f"EIA first annual row changed from {spec['first_year']} to {first_year}"
        )
    latest_year = int(max(values))
    latest_marker = contents.cell_value(6, 5)
    if (
        isinstance(latest_marker, bool)
        or not isinstance(latest_marker, (int, float))
        or not float(latest_marker).is_integer()
        or int(latest_marker) != latest_year
    ):
        return None, (
            f"EIA latest-data marker {latest_marker!r} disagrees with "
            f"last annual row {latest_year}"
        )
    return values, None


def eia_dnav_workbook_link(html: bytes, spec: Mapping[str, Any]) -> str | None:
    """Authenticate the page and its untouched, structurally active XLS href."""

    try:
        text = html.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = html.decode("windows-1252")
        except UnicodeDecodeError:
            return None
    parser = _EiaDnavPageParser()
    parser.feed(text)
    parser.close()
    if parser.ambiguous_html_seen or parser.unauthenticatable_href_seen:
        return None
    normalized = _eia_dnav_normalized_text(" ".join(parser.text))
    expected_page_title = str(spec["page_title"])
    if expected_page_title not in normalized:
        return None
    expected_filename = posixpath.basename(urlparse(str(spec["workbook_url"])).path)
    expected_link_text = _eia_dnav_normalized_text(spec["workbook_link_text"])
    workbook_hrefs: list[str | None] = [
        href
        for href, raw_hrefs, link_text in parser.links
        if any(
            raw_href is not None and expected_filename.lower() in raw_href.lower()
            for raw_href in raw_hrefs
        )
        or _eia_dnav_normalized_text(link_text) == expected_link_text
    ]
    if len(workbook_hrefs) != 1 or workbook_hrefs[0] is None:
        return None
    try:
        _require_eia_dnav_workbook_href(workbook_hrefs[0], spec)
    except ValueError:
        return None
    # Identity is established by the exact raw source token above. Do not
    # normalize it: return the separately reviewed canonical transport URL.
    return str(spec["workbook_url"])


def eia_dnav_anchor_mismatches(
    values: Mapping[str, float], anchors: Mapping[str, float]
) -> list[str]:
    problems = []
    for year, expected in sorted(anchors.items()):
        got = values.get(year)
        if got is None:
            problems.append(f"{year}=missing (official {expected})")
        elif got != expected:
            problems.append(f"{year}={got} (official {expected})")
    return problems


def eia_dnav_capture_envelope(
    *,
    page_url: str,
    page_raw: bytes,
    page_retrieved_at: str,
    workbook_url: str,
    workbook_raw: bytes,
    workbook_retrieved_at: str,
    period: str,
    value: float,
    source_series_id: str,
    unit: str,
) -> bytes:
    """Archive every response that authenticated the mutable annual print."""

    return canonical_bytes(
        {
            "schemaVersion": EIA_DNAV_ENVELOPE_SCHEMA,
            "page": {
                "url": page_url,
                "retrievedAt": page_retrieved_at,
                "bytes": len(page_raw),
                "sha256": hashlib.sha256(page_raw).hexdigest(),
                "bodyBase64": base64.b64encode(page_raw).decode(),
            },
            "workbook": {
                "url": workbook_url,
                "retrievedAt": workbook_retrieved_at,
                "bytes": len(workbook_raw),
                "sha256": hashlib.sha256(workbook_raw).hexdigest(),
                "bodyBase64": base64.b64encode(workbook_raw).decode(),
            },
            "derived": {
                "sourceSeriesId": source_series_id,
                "period": period,
                "unit": unit,
                "value": value,
            },
        }
    )


class _EiaDnavNoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validate a redirect target's raw identity, then refuse every redirect."""

    def __init__(
        self,
        *,
        expected_url: str,
        kind: str,
        allowed_hosts: list[str] | tuple[str, ...],
    ) -> None:
        super().__init__()
        self.expected_url = expected_url
        self.kind = kind
        self.allowed_hosts = allowed_hosts

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        _require_eia_dnav_url(
            newurl,
            expected_url=self.expected_url,
            kind=self.kind,
            allowed_hosts=self.allowed_hosts,
        )
        raise ValueError(
            f"EIA DNav {self.kind} redirects are not allowed: "
            f"{req.full_url!r} -> {newurl!r}"
        )


def eia_dnav_http_get(
    url: str,
    *,
    expected_url: str,
    kind: str,
    allowed_hosts: list[str] | tuple[str, ...],
    timeout: int = 120,
) -> tuple[bytes, str, str]:
    """Fetch one exact, redirect-free DNav hop and timestamp its full read."""

    _require_eia_dnav_url(
        url,
        expected_url=expected_url,
        kind=kind,
        allowed_hosts=allowed_hosts,
    )
    request = urllib.request.Request(url, headers={"User-Agent": INTL_USER_AGENT})
    opener = urllib.request.build_opener(
        _EiaDnavNoRedirectHandler(
            expected_url=expected_url,
            kind=kind,
            allowed_hosts=allowed_hosts,
        )
    )
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        _require_eia_dnav_url(
            final_url,
            expected_url=expected_url,
            kind=kind,
            allowed_hosts=allowed_hosts,
        )
        if final_url != url:
            raise ValueError(
                f"EIA DNav {kind} final URL changed without an accepted "
                f"identity transition: {url!r} -> {final_url!r}"
            )
        raw = response.read()
    # DNav URLs are mutable, so first-print custody needs the time all response
    # bytes were actually in hand; this also lets the post-fetch gate reject a
    # read that straddles the registered window's UTC boundary.
    return raw, utc_now(), final_url


def eia_dnav_fetch_year(
    spec: Mapping[str, Any], year: str
) -> tuple[float | None, bytes | None, str, str, str | None]:
    """Fetch/authenticate the DNav page and linked workbook for one year."""

    if re.fullmatch(r"\d{4}", year) is None:
        return None, None, str(spec["source_url"]), utc_now(), "period must be YYYY"
    try:
        page_raw, page_retrieved_at, page_url = eia_dnav_http_get(
            str(spec["source_url"]),
            expected_url=str(spec["source_url"]),
            kind="page",
            allowed_hosts=spec["allowed_hosts"],
        )
    except (http.client.IncompleteRead, OSError, ValueError) as exc:
        return (
            None,
            None,
            str(spec["source_url"]),
            utc_now(),
            f"page fetch failed: {exc}",
        )
    if page_url != spec["source_url"]:
        return (
            None,
            page_raw,
            page_url,
            page_retrieved_at,
            ("EIA DNav page redirected away from the registered exact URL"),
        )
    workbook_url = eia_dnav_workbook_link(page_raw, spec)
    if workbook_url is None:
        return (
            None,
            page_raw,
            page_url,
            page_retrieved_at,
            ("EIA DNav page did not authenticate the exact N9040US2 XLS sibling"),
        )
    try:
        workbook_raw, workbook_retrieved_at, final_workbook_url = eia_dnav_http_get(
            workbook_url,
            expected_url=str(spec["workbook_url"]),
            kind="workbook",
            allowed_hosts=spec["allowed_hosts"],
        )
    except (http.client.IncompleteRead, OSError, ValueError) as exc:
        return None, None, workbook_url, utc_now(), f"workbook fetch failed: {exc}"
    if final_workbook_url != workbook_url:
        return (
            None,
            workbook_raw,
            final_workbook_url,
            workbook_retrieved_at,
            ("EIA workbook redirected away from the page-linked exact URL"),
        )
    values, refusal = eia_dnav_values_from_xls(workbook_raw, spec)
    if refusal or values is None:
        return None, workbook_raw, workbook_url, workbook_retrieved_at, refusal
    value = values.get(year)
    if value is None:
        # A monthly DNav refresh without the target annual row is not a parse
        # failure and never a first print; leave the target pending.
        return None, None, workbook_url, workbook_retrieved_at, None
    envelope = eia_dnav_capture_envelope(
        page_url=page_url,
        page_raw=page_raw,
        page_retrieved_at=page_retrieved_at,
        workbook_url=workbook_url,
        workbook_raw=workbook_raw,
        workbook_retrieved_at=workbook_retrieved_at,
        period=year,
        value=value,
        source_series_id=str(spec["series_id"]),
        unit=str(spec["unit"]),
    )
    return value, envelope, workbook_url, workbook_retrieved_at, None


def qcew_period_parts(spec: Mapping[str, Any], period: str) -> tuple[str, str, str]:
    """Return ``(year, qtr, API path token)`` for one admitted QCEW variant."""

    period_type = spec.get("period_type")
    if period_type == "quarter":
        if not re.fullmatch(r"\d{4}-(01|04|07|10)", period):
            raise ValueError(f"QCEW period must be a quarter start, got {period!r}")
        quarter = str((int(period[5:7]) - 1) // 3 + 1)
        return period[:4], quarter, quarter
    if period_type == "year":
        if not re.fullmatch(r"\d{4}", period):
            raise ValueError(f"annual QCEW period must be YYYY, got {period!r}")
        return period, "A", "a"
    raise ValueError(f"unsupported QCEW period type {period_type!r}")


def qcew_api_url(spec: dict[str, Any], period: str) -> str:
    """Official quarterly or annual QCEW industry-slice URL."""
    year, _qtr, api_period = qcew_period_parts(spec, period)
    return QCEW_API_URL.format(
        year=year,
        api_period=api_period,
        industry=spec["industry_code"],
    )


def qcew_source_series_id(spec: dict[str, Any], period: str) -> str:
    year, qtr, _api_period = qcew_period_parts(spec, period)
    parts = [
        f"area_fips={spec['area_fips']}",
        f"own_code={spec['own_code']}",
        f"industry_code={spec['industry_code']}",
    ]
    if spec.get("source_series_id_includes_agglvl"):
        parts.append(f"agglvl_code={spec['agglvl_code']}")
    parts.append(f"size_code={spec['size_code']}")
    if spec.get("source_series_id_includes_period", True):
        parts.append(f"year={year}")
    parts.append(f"qtr={qtr}")
    return ";".join(parts)


def qcew_value_from_csv(
    raw: bytes, spec: dict[str, Any], period: str
) -> tuple[float | None, str | None]:
    """Extract one disclosed, exact QCEW row; ambiguous input fails closed."""
    year, qtr, _api_period = qcew_period_parts(spec, period)
    expected = {
        "area_fips": spec["area_fips"],
        "own_code": spec["own_code"],
        "industry_code": spec["industry_code"],
        "agglvl_code": spec["agglvl_code"],
        "size_code": spec["size_code"],
        "year": year,
        "qtr": qtr,
    }
    if not raw.endswith(b"\n"):
        return None, "QCEW CSV response is truncated (missing terminal newline)"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "response is not UTF-8 CSV"
    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as exc:
        return None, f"QCEW CSV is malformed ({exc})"
    if not rows:
        return None, "QCEW CSV is empty"
    parsed_fieldnames = rows[0]
    fieldnames = [name.strip() for name in parsed_fieldnames]
    if not fieldnames or any(not name for name in fieldnames):
        return None, "QCEW CSV has an empty column name"
    if len(fieldnames) != len(set(fieldnames)):
        return None, "QCEW CSV has duplicate column names"
    if spec.get("period_type") == "year":
        if parsed_fieldnames != list(QCEW_ANNUAL_CSV_FIELDS):
            return None, (
                "QCEW CSV does not match the official ordered 38-column annual layout"
            )
    else:
        required = {*expected, "disclosure_code", spec["field"]}
        if not required.issubset(set(fieldnames)):
            return None, "QCEW CSV is missing required columns"
    matches: list[dict[str, str]] = []
    for line_number, values in enumerate(rows[1:], start=2):
        if len(values) != len(fieldnames):
            return None, (
                f"QCEW CSV row {line_number} has {len(values)} fields; "
                f"expected {len(fieldnames)} (truncated or malformed response)"
            )
        row = {key: str(value).strip() for key, value in zip(fieldnames, values)}
        if all(row.get(key) == value for key, value in expected.items()):
            matches.append(row)
    if len(matches) != 1:
        return None, f"expected one exact QCEW row, found {len(matches)}"
    row = matches[0]
    disclosure_code = row.get("disclosure_code", "")
    if disclosure_code:
        return None, (
            f"exact QCEW row is not disclosed (disclosure_code={disclosure_code!r})"
        )
    try:
        value = float(row[spec["field"]])
    except (KeyError, TypeError, ValueError):
        return None, f"{spec['field']} is not numeric"
    if not math.isfinite(value) or not value.is_integer() or value < 0:
        return None, f"{spec['field']} is not a nonnegative integer count"
    return value, None


def qcew_anchor_mismatches(
    values: dict[str, float | None], anchors: dict[str, float]
) -> list[str]:
    """Require and compare at least three live-retrieved historical values."""
    if len(anchors) < 3:
        return [f"only {len(anchors)} verified anchors; at least 3 required"]
    problems = []
    for period, expected in sorted(anchors.items()):
        got = values.get(period)
        if got is None:
            problems.append(f"{period}=missing (official {expected})")
        elif got != expected:
            problems.append(f"{period}={got} (official {expected})")
    return problems


def qcew_adapter_verified(spec: dict[str, Any]) -> bool:
    """Whether the adapter has passed the mandatory live-anchor gate."""
    anchors = spec.get("anchors")
    if spec.get("anchor_status") != "VERIFIED" or not isinstance(anchors, dict):
        return False
    pattern = r"\d{4}" if spec.get("period_type") == "year" else r"\d{4}-(01|04|07|10)"
    return len(anchors) >= 3 and all(
        isinstance(period, str)
        and re.fullmatch(pattern, period)
        and not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value).is_integer()
        and float(value) >= 0
        for period, value in anchors.items()
    )


def qcew_cache_key(spec: dict[str, Any], period: str) -> tuple[str, str, str]:
    """Cache by full slice identity, not only NAICS and period."""

    return (
        qcew_api_url(spec, period),
        qcew_source_series_id(spec, period),
        str(spec["field"]),
    )


def qcew_binding_matches_spec(
    binding: Mapping[str, Any],
    spec: Mapping[str, Any],
    period: str,
    release_day: dt.date,
) -> bool:
    """Authenticate every QCEW registration field against trusted code."""

    adapter = binding.get("adapter")
    legacy = qcew_is_legacy_binding(binding, spec)
    if adapter != "bls-qcew" and not legacy:
        return False
    expected_keys = {
        "adapter",
        "sourceUrl",
        "sourceSeriesId",
        "field",
        "table",
        "transform",
        "releasePolicy",
        "expectedReleaseWindow",
        "allowedHosts",
    }
    if set(binding) != expected_keys:
        return False
    api_host = urlparse(qcew_api_url(dict(spec), period)).hostname
    page_host = urlparse(str(spec["source_page"])).hostname
    expected_hosts = [page_host] if legacy else sorted({api_host, page_host})
    expected_table = (
        spec.get("legacy_source_table") if legacy else spec.get("source_table")
    )
    expected_window = {
        "start": release_day.isoformat(),
        "end": release_day.isoformat(),
    }
    return (
        binding.get("sourceUrl") == spec.get("source_page")
        and binding.get("sourceSeriesId") == qcew_source_series_id(dict(spec), period)
        and binding.get("field") == spec.get("field")
        and binding.get("table") == expected_table
        and binding.get("transform") == {"operation": "identity", "factor": 1}
        and binding.get("releasePolicy") == "first_print"
        and binding.get("expectedReleaseWindow") == expected_window
        and binding.get("allowedHosts") == expected_hosts
    )


def qcew_is_legacy_binding(binding: Mapping[str, Any], spec: Mapping[str, Any]) -> bool:
    """Recognize only an explicitly declared, nonempty legacy adapter."""

    legacy_adapter = spec.get("legacy_binding_adapter")
    return (
        isinstance(legacy_adapter, str)
        and bool(legacy_adapter)
        and binding.get("adapter") == legacy_adapter
    )


def qcew_calendar_authority_matches_spec(
    spec: Mapping[str, Any],
    period: str,
    release_day: dt.date,
    docket_entries: list[Mapping[str, Any]] | None = None,
) -> bool:
    """Bind dated QCEW targets to the one trusted BLS calendar authority."""

    expected_calendar = spec.get("release_calendar_url")
    if expected_calendar is None:
        # The immutable legacy aircraft registration predates the recurring
        # docket and keeps its original one-day window unchanged.
        return True
    if not isinstance(expected_calendar, str) or not expected_calendar:
        return False
    if docket_entries is None:
        try:
            payload = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
        except (OSError, json.JSONDecodeError):
            return False
        loaded_entries = payload.get("series") if isinstance(payload, dict) else None
        if not isinstance(loaded_entries, list):
            return False
        docket_entries = loaded_entries
    matches = [
        entry
        for entry in docket_entries
        if entry.get("series") == spec.get("measure_concept")
    ]
    if len(matches) != 1:
        return False
    entry = matches[0]
    release_dates = entry.get("releaseDates")
    return (
        entry.get("releaseCalendarUrl") == expected_calendar
        and isinstance(release_dates, Mapping)
        and release_dates.get(period) == release_day.isoformat()
    )


def qcew_registration_matches_spec(
    binding: Mapping[str, Any],
    spec: Mapping[str, Any],
    period: str,
    release_day: dt.date,
    docket_entries: list[Mapping[str, Any]] | None = None,
) -> bool:
    """Authenticate both the QCEW source binding and calendar authority."""

    return qcew_binding_matches_spec(binding, spec, period, release_day) and (
        qcew_calendar_authority_matches_spec(
            spec,
            period,
            release_day,
            docket_entries,
        )
    )


def qcew_fact_source_url(
    binding: Mapping[str, Any], spec: Mapping[str, Any], fetched_url: str
) -> str:
    """Preserve the legacy landing-page fact URL; expose new CSV fetches."""

    if qcew_is_legacy_binding(binding, spec):
        return str(binding["sourceUrl"])
    return fetched_url


def qcew_resolution_fact(
    ref: str,
    spec: dict[str, Any],
    period_type: str,
    period: str,
    value: float,
    release_day: dt.date,
    binding: Mapping[str, Any],
    fetched_url: str,
) -> tuple[dict[str, Any], str]:
    """Build the production QCEW fact and its stable archive series id."""

    row = generic_fact(
        ref,
        spec,
        period_type,
        period,
        value,
        release_day,
        qcew_fact_source_url(binding, spec, fetched_url),
        fetched_url,
    )
    if qcew_is_legacy_binding(binding, spec):
        # Preserve the exact pre-generalization aircraft archive identity.
        series_id = (
            f"QCEW-{spec['area_fips']}-{spec['own_code']}-"
            f"{spec['industry_code']}-{spec['size_code']}"
        )
    else:
        series_id = (
            f"QCEW-{spec['area_fips']}-{spec['own_code']}-"
            f"{spec['industry_code']}-{spec['agglvl_code']}-"
            f"{spec['size_code']}-{spec['field']}"
        )
    return row, series_id


def qcew_fetch_period(
    spec: dict[str, Any], period: str
) -> tuple[float | None, bytes | None, str, str, str | None]:
    """Fetch and parse one official QCEW quarterly or annual industry slice."""
    url = qcew_api_url(spec, period)
    retrieved_at = utc_now()
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/csv",
            "User-Agent": "thesis-resolver/1 (app.thesisinstitute.org)",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            final_url = response.geturl()
            content_type = response.headers.get_content_type()
            declared_length = response.headers.get("Content-Length")
            # Timestamp the completed read. Stable QCEW URLs are mutable, so
            # request start is not sufficient first-print custody.
            retrieved_at = utc_now()
    except (http.client.IncompleteRead, urllib.error.HTTPError, urllib.error.URLError):
        return None, None, url, retrieved_at, None
    if final_url != url:
        return None, raw, url, retrieved_at, "QCEW fetch redirected off exact URL"
    if content_type != "text/csv":
        return (
            None,
            raw,
            url,
            retrieved_at,
            (f"QCEW response has unexpected content type {content_type!r}"),
        )
    if declared_length is not None:
        try:
            expected_length = int(declared_length)
        except ValueError:
            return None, raw, url, retrieved_at, "QCEW Content-Length is malformed"
        if expected_length != len(raw):
            return (
                None,
                raw,
                url,
                retrieved_at,
                (
                    f"QCEW response length {len(raw)} differs from Content-Length "
                    f"{expected_length}"
                ),
            )
    value, refusal = qcew_value_from_csv(raw, spec, period)
    return value, raw, url, retrieved_at, refusal


def qcew_postfetch_window_refusal(
    retrieved_at: str,
    release_day: dt.date,
    decision_at: str | None = None,
) -> str | None:
    """Refuse a mutable QCEW response completed after its one-day window."""

    try:
        fetched_day = dt.date.fromisoformat(retrieved_at[:10])
        decision_day = dt.date.fromisoformat((decision_at or utc_now())[:10])
    except ValueError:
        return "QCEW retrieval timestamp is malformed"
    effective_day = max(fetched_day, decision_day)
    if effective_day > release_day:
        return (
            f"QCEW response completed on {effective_day}, after registered "
            f"release day {release_day}"
        )
    return None


def claims_fact(
    ref: str, week: str, raw: float, kind: str, release_day: dt.date
) -> dict:
    """Build a ledger fact row for a weekly claims first print."""
    if kind == "initial":
        value, unit = round(raw / 1_000, 1), "thousands"
        concept = "us.dol.initial_claims.sa"
        fred_id, label = "ICSA", "US initial claims (SA, advance)"
    else:
        value, unit = round(raw / 1_000_000, 3), "millions"
        concept = "dol.eta.continued_claims.sa"
        fred_id, label = "CCSA", "US insured unemployment (SA, advance)"
    source_url = FRED_CSV.format(series=fred_id, vintage=release_day.isoformat())
    return {
        "source_record_id": ref,
        "label": f"{label}, week ending {week}",
        "value": value,
        "observed_at": release_day.isoformat(),
        "period": {"type": "week_ending", "value": week},
        "domain": "labor",
        "geography": {
            "level": "country",
            "id": "0100000US",
            "vintage": "current",
            "name": "United States",
        },
        "entity": {"name": "person", "role": "ui_claimant"},
        "measure": {
            "concept": concept,
            "unit": unit,
            "source_concept": fred_id,
            "concept_relation": "source_label",
            "concept_authority": "dol_eta",
            "concept_evidence_url": source_url,
            "concept_evidence_notes": (
                f"DOL ETA UI Weekly Claims news release, advance seasonally "
                f"adjusted figure for the week ending {week}, read from FRED "
                f"{fred_id} (advance vintage) as the cell's resolver names."
            ),
        },
        "aggregation": {"method": "level"},
        "filters": {},
        "source": {
            "source_name": "dol_eta",
            "source_table": "Unemployment Insurance Weekly Claims (advance)",
            "source_file": "fredgraph.csv",
            "url": source_url,
            "vintage": "advance",
            "extracted_at": dt.date.today().isoformat(),
            "extraction_method": (
                "Automated first-print capture via FRED series "
                f"{fred_id} by scripts/resolve_pending.py"
            ),
        },
        "source_row_keys": [week],
        "source_cell_keys": [fred_id],
    }


def pending_claims_refs(log: dict) -> list[tuple[str, str, str, str]]:
    """(ref, week, kind, verified release date) for pending claims cells."""
    forecasts = {
        entry["forecastSlug"]: entry
        for entry in log.get("entries", [])
        if entry.get("kind") == "prediction_recorded"
        and entry.get("forecastSlug")
        and entry.get("resolutionDate")
    }
    out = []
    for link in log["resolutionLinks"]:
        if link.get("status") != "pending":
            continue
        ref = link.get("targetFactRef")
        if not ref:
            continue
        forecast = forecasts.get(link.get("forecastSlug"))
        if not forecast:
            raise ValueError(
                f"pending target {ref} has no recorded, verified resolutionDate"
            )
        release_date = str(forecast["resolutionDate"])
        dt.date.fromisoformat(release_date)
        m = re.match(r"us\.dol\.initial_claims\.sa\.week_(\d{4}-\d{2}-\d{2})$", ref)
        if m:
            out.append((ref, m.group(1), "initial", release_date))
            continue
        m = re.match(
            r"dol\.eta\.continued_claims\.sa\.week_(\d{4}-\d{2}-\d{2})(\.first_print)?$",
            ref,
        )
        if m:
            out.append((ref, m.group(1), "continued", release_date))
    return out


def pending_adapter_refs(
    log: dict,
) -> list[tuple[str, str, dict[str, Any], str, str, str, dict[str, Any]]]:
    """(ref, kind, spec, period_type, period, release_date, forecast_entry)
    for pending cells covered by the generic adapters."""
    forecasts = {
        entry["forecastSlug"]: entry
        for entry in log.get("entries", [])
        if entry.get("kind") == "prediction_recorded" and entry.get("forecastSlug")
    }
    out = []
    sba_registrations: dict[str, dict[str, Any]] | None = None
    for link in log["resolutionLinks"]:
        if link.get("status") != "pending":
            continue
        ref = link.get("targetFactRef")
        if not ref:
            continue
        forecast = forecasts.get(link.get("forecastSlug")) or {}
        release_date = str(forecast.get("resolutionDate") or "")
        if not release_date:
            continue
        sba_stem = longest_adapter_stem(ref, SBA_PDF_ADAPTERS)
        if sba_stem:
            parsed = parse_ref_period(ref, sba_stem)
            if parsed and parsed[0] == "year":
                if sba_registrations is None:
                    sba_registrations = registration_contracts()
                fiscal_year = _registered_sba_fiscal_year(
                    ref,
                    sba_stem,
                    SBA_PDF_ADAPTERS[sba_stem],
                    sba_registrations.get(ref),
                )
                if fiscal_year is not None:
                    parsed = ("fiscal_year", fiscal_year)
            if parsed and parsed[0] == "fiscal_year":
                out.append(
                    (
                        ref,
                        "sba_pdf",
                        SBA_PDF_ADAPTERS[sba_stem],
                        parsed[0],
                        parsed[1],
                        release_date,
                        forecast,
                    )
                )
            continue
        intl_stem = longest_adapter_stem(ref, INTL_ADAPTERS)
        if intl_stem:
            parsed = parse_ref_period(ref, intl_stem)
            spec = INTL_ADAPTERS[intl_stem]
            if parsed and parsed[0] == spec.get("period_type", "month"):
                out.append(
                    (
                        ref,
                        "intl",
                        {
                            **spec,
                            "period_type": parsed[0],
                            "target_series": intl_stem,
                        },
                        parsed[0],
                        parsed[1],
                        release_date,
                        forecast,
                    )
                )
            continue
        usaspending_stem = next(
            (stem for stem in USASPENDING_ADAPTERS if ref.startswith(stem + ".")),
            None,
        )
        if usaspending_stem:
            fiscal_year = parse_usaspending_ref_fiscal_year(ref, usaspending_stem)
            if fiscal_year is not None:
                out.append(
                    (
                        ref,
                        "usaspending",
                        {
                            **USASPENDING_ADAPTERS[usaspending_stem],
                            "target_series": usaspending_stem,
                        },
                        "fiscal_year",
                        fiscal_year,
                        release_date,
                        forecast,
                    )
                )
            continue
        if ref.startswith(A19_STEM + "."):
            occupation = ref[len(A19_STEM) + 1 :].split(".")[0]
            parsed = parse_ref_period(ref, f"{A19_STEM}.{occupation}")
            if occupation in A19_ROW_LABELS and parsed:
                spec = {
                    "label": f"CPS employed, {A19_ROW_LABELS[occupation]}",
                    "unit": "thousands",
                    "source_name": "bls_cps",
                    "source_table": "Employment Situation, Table A-19",
                    "concept_authority": "bls",
                    "source_concept": A19_ROW_LABELS[occupation],
                    "a19_row": occupation,
                }
                out.append(
                    (ref, "a19", spec, parsed[0], parsed[1], release_date, forecast)
                )
            continue
        va_mmwr_stem = longest_adapter_stem(ref, VA_MMWR_ADAPTERS)
        if va_mmwr_stem:
            report_date = parse_va_mmwr_ref(ref, va_mmwr_stem)
            if report_date is not None:
                out.append(
                    (
                        ref,
                        "va_mmwr",
                        VA_MMWR_ADAPTERS[va_mmwr_stem],
                        "week",
                        report_date,
                        release_date,
                        forecast,
                    )
                )
            continue
        ssa_stem = longest_adapter_stem(ref, SSA_OFFICIAL_ADAPTERS)
        if ssa_stem:
            parsed = parse_ref_period(ref, ssa_stem)
            if parsed and parsed[0] == "month":
                out.append(
                    (
                        ref,
                        "ssa_official",
                        SSA_OFFICIAL_ADAPTERS[ssa_stem],
                        parsed[0],
                        parsed[1],
                        release_date,
                        forecast,
                    )
                )
            continue
        bls_stem = next(
            (stem for stem in BLS_API_ADAPTERS if ref.startswith(stem + ".")),
            None,
        )
        if bls_stem:
            parsed = parse_ref_period(ref, bls_stem)
            spec = BLS_API_ADAPTERS[bls_stem]
            if parsed and parsed[0] == spec["period_type"]:
                out.append(
                    (
                        ref,
                        "bls_api",
                        spec,
                        parsed[0],
                        parsed[1],
                        release_date,
                        forecast,
                    )
                )
            continue
        fsa_crp_stem = next(
            (stem for stem in FSA_CRP_ADAPTERS if ref.startswith(stem + ".")),
            None,
        )
        if fsa_crp_stem:
            # Conditional-pair ids append a legal-state token after the
            # release policy; both arms still resolve against one monthly
            # FSA print.
            arm = re.fullmatch(
                rf"{re.escape(fsa_crp_stem)}\.(\d{{4}})[-_](\d{{2}})"
                r"\.first_print(?:\.[a-z0-9_]+)?",
                ref,
            )
            parsed = parse_ref_period(ref, fsa_crp_stem)
            if arm and 1 <= int(arm.group(2)) <= 12:
                period = f"{arm.group(1)}-{arm.group(2)}"
            elif parsed and parsed[0] == "month":
                period = parsed[1]
            else:
                period = None
            if period is not None:
                out.append(
                    (
                        ref,
                        "fsa_crp",
                        FSA_CRP_ADAPTERS[fsa_crp_stem],
                        "month",
                        period,
                        release_date,
                        forecast,
                    )
                )
            continue
        census_spm_stem = next(
            (stem for stem in CENSUS_SPM_ADAPTERS if ref.startswith(stem + ".")),
            None,
        )
        if census_spm_stem:
            # Both legal-condition arms resolve against the same CY annual
            # Table B-2 print; the suffix only controls which arm scores.
            arm = re.fullmatch(
                rf"{re.escape(census_spm_stem)}\.(\d{{4}})\.first_print"
                r"(?:\.[a-z0-9_]+)?",
                ref,
            )
            if arm:
                out.append(
                    (
                        ref,
                        "census_spm",
                        CENSUS_SPM_ADAPTERS[census_spm_stem],
                        "year",
                        arm.group(1),
                        release_date,
                        forecast,
                    )
                )
            continue
        irs_soi_stem = next(
            (stem for stem in IRS_SOI_PUB1304_ADAPTERS if ref.startswith(stem + ".")),
            None,
        )
        if irs_soi_stem:
            # Conditional-arm ids carry a condition token after the release
            # policy (irs.actc.total_claims.2027.first_print.current_law);
            # every arm of a pair resolves against the same tax-year print.
            arm = re.fullmatch(
                rf"{re.escape(irs_soi_stem)}\.(\d{{4}})\.first_print"
                r"(?:\.[a-z0-9_]+)?",
                ref,
            )
            if arm:
                out.append(
                    (
                        ref,
                        "irs_soi_pub1304",
                        IRS_SOI_PUB1304_ADAPTERS[irs_soi_stem],
                        "year",
                        arm.group(1),
                        release_date,
                        forecast,
                    )
                )
            continue
        qcew_stem = next(
            (stem for stem in QCEW_ADAPTERS if ref.startswith(stem + ".")),
            None,
        )
        if qcew_stem:
            parsed = parse_ref_period(ref, qcew_stem)
            spec = QCEW_ADAPTERS[qcew_stem]
            if parsed and parsed[0] == spec["period_type"]:
                out.append(
                    (
                        ref,
                        "qcew",
                        spec,
                        parsed[0],
                        parsed[1],
                        release_date,
                        forecast,
                    )
                )
            continue
        eia_dnav_stem = next(
            (stem for stem in EIA_DNAV_ADAPTERS if ref.startswith(stem + ".")),
            None,
        )
        if eia_dnav_stem:
            parsed = parse_ref_period(ref, eia_dnav_stem)
            if parsed and parsed[0] == "year":
                out.append(
                    (
                        ref,
                        "eia_dnav",
                        EIA_DNAV_ADAPTERS[eia_dnav_stem],
                        "year",
                        parsed[1],
                        release_date,
                        forecast,
                    )
                )
            continue
        cms_stem = next(
            (stem for stem in CMS_PROVIDER_DATA_ADAPTERS if ref.startswith(stem + ".")),
            None,
        )
        if cms_stem:
            parsed = parse_ref_period(ref, cms_stem)
            if parsed and parsed[0] == "month":
                out.append(
                    (
                        ref,
                        "cms_provider_data",
                        CMS_PROVIDER_DATA_ADAPTERS[cms_stem],
                        parsed[0],
                        parsed[1],
                        release_date,
                        forecast,
                    )
                )
            continue
        bea_release_stem = longest_adapter_stem(ref, BEA_RELEASE_ADAPTERS)
        if bea_release_stem:
            parsed = parse_ref_period(ref, bea_release_stem)
            if parsed and parsed[0] == "quarter":
                out.append(
                    (
                        ref,
                        "bea_release",
                        BEA_RELEASE_ADAPTERS[bea_release_stem],
                        parsed[0],
                        parsed[1],
                        release_date,
                        forecast,
                    )
                )
            continue
        for stem, spec in ALFRED_ADAPTERS.items():
            if not ref.startswith(stem + "."):
                continue
            parsed = parse_ref_period(ref, stem)
            if parsed:
                out.append(
                    (
                        ref,
                        "alfred",
                        spec,
                        parsed[0],
                        parsed[1],
                        release_date,
                        forecast,
                    )
                )
            break
    return out


def _created_at_utc(now: dt.datetime | None) -> str:
    current = now or dt.datetime.now(dt.timezone.utc)
    if (
        not isinstance(current, dt.datetime)
        or current.tzinfo is None
        or current.utcoffset() is None
    ):
        raise LedgerProposalError("now must be a timezone-aware datetime")
    try:
        current_utc = current.astimezone(dt.timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise LedgerProposalError("now cannot be represented as UTC") from exc
    return current_utc.isoformat(timespec="seconds").replace("+00:00", "Z")


def _build_next_release_manifest(
    ledger: bytes,
    immutable_prefix: bytes,
    existing: ChainVerification,
    *,
    now: dt.datetime | None,
) -> tuple[dict[str, Any], bytes]:
    """Construct the exact next non-genesis manifest from a verified base."""

    head = existing.head
    if head is None:
        raise LedgerProposalError("cannot build a release before witnessed genesis")
    offsets = jsonl_line_offsets(ledger, LEDGER_RELATIVE.as_posix())
    line_count = len(offsets) - 1
    previous_count = head.manifest["state"]["lineCount"]
    if previous_count >= line_count:
        raise LedgerProposalError(
            "proposed ledger has no rows after the witnessed base HEAD"
        )
    witnessed_prefix = ledger[: offsets[previous_count]]
    if sha256_bytes(witnessed_prefix) != head.manifest["state"]["jsonlSha256"]:
        raise LedgerProposalError(
            "proposed ledger does not begin with the exact state committed by "
            "the witnessed base HEAD"
        )
    immutable_digest = sha256_bytes(immutable_prefix)
    if immutable_digest != head.manifest["state"]["immutablePrefixSha256"]:
        raise LedgerProposalError(
            "ledger/immutable_prefix.json differs from the witnessed base HEAD"
        )
    suffix = ledger[offsets[previous_count] :]
    manifest: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "releaseIndex": head.release_index + 1,
        "previousManifestSha256": head.sha256,
        "state": {
            "path": LEDGER_RELATIVE.as_posix(),
            "jsonlSha256": sha256_bytes(ledger),
            "lineCount": line_count,
            "immutablePrefixSha256": immutable_digest,
        },
        "append": {
            "previousLineCount": previous_count,
            "appendedRowCount": line_count - previous_count,
            "appendedBytesSha256": sha256_bytes(suffix),
        },
        "createdAtUtc": _created_at_utc(now),
        "producer": {
            "repo": "PolicyEngine/chronicle",
            "branch": "codex/thesis-ledger-facts",
        },
    }
    validate_manifest_schema(manifest)
    return manifest, canonical_bytes(manifest) + b"\n"


def _validated_repository_path(value: str) -> pathlib.PurePosixPath:
    if type(value) is not str or not value or value.startswith("/"):
        raise LedgerProposalError(f"invalid repository path: {value!r}")
    path = pathlib.PurePosixPath(value)
    if path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
        raise LedgerProposalError(f"invalid repository path: {value!r}")
    return path


def _materialize_repository_tree(
    root: pathlib.Path,
    tree: RepositoryTree,
) -> None:
    for relative, payload in tree.files.items():
        path = _validated_repository_path(relative)
        mode = tree.modes.get(relative)
        if mode not in {"100644", "100755"}:
            raise LedgerProposalError(
                f"base tree entry has non-regular mode {mode}: {relative}"
            )
        output = root / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        output.chmod(0o755 if mode == "100755" else 0o644)


def _base_has_release_chain(tree: RepositoryTree) -> bool:
    prefix = MANIFEST_RELATIVE.as_posix() + "/"
    return any(relative.startswith(prefix) for relative in tree.files)


REGISTRY_FORBIDDEN_EVENT_FIELDS = ("reclaimed", "revived", "supersedes")


def _identity_belongs_to_rows(concept: str, appended_row_ids: list[str]) -> bool:
    """True when the concept's segments are an in-order subsequence of one
    appended observation's dataPointId (the generator derives concepts from
    row ids by dropping period segments, wherever they sit)."""
    segments = concept.split(".")
    if len(segments) < 2 or not all(segments):
        return False
    for row_id in appended_row_ids:
        remaining = iter(str(row_id).split("."))
        if all(segment in remaining for segment in segments):
            return True
    return False


def _registry_growth_refusal(
    base_registry: bytes,
    regenerated_registry: bytes,
    appended_row_ids: list[str],
) -> str | None:
    """Why the regenerated UUID registry exceeds this append's own lifecycle.

    ``None`` when every registry change is the sanctioned first-observation
    lifecycle for a row this proposal appends: append-only growth whose new
    lines are plain mints of full identities with fresh UUIDs, or the
    generator's documented docket-placeholder enrichment (a ``retired``
    line for the committed placeholder followed by a ``succeeds`` mint that
    keeps its UUID and concept). Anything else — rewritten committed lines,
    supersedes/revive/reclaim events, identities that belong to no appended
    row, placeholder mints, UUID reuse — is named and refused, preserving
    the 2026-08-17 invariant that appends never rewrite series identities
    while unblocking the lifecycle it overshot: without this allowance no
    series could ever take its first observation (fresh identities cannot
    be pre-minted in chronicle — its generator retires bindings that no
    observation backs — and a seeded placeholder's first observation is
    exactly the enrichment the byte-compare refused; resolve loop failures
    2026-08-18 through 2026-08-22, issues #202-#206).
    """

    if not regenerated_registry.startswith(base_registry):
        return "the regenerated registry rewrites committed lines"
    base_entries: list[dict[str, Any]] = []
    for line in base_registry.decode("utf-8", "replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            base_entries.append(entry)
    base_uuids = {entry.get("uuid") for entry in base_entries}
    committed_placeholders = {
        (entry.get("concept"), entry.get("uuid"))
        for entry in base_entries
        if entry.get("geography") is None
        and entry.get("entity") is None
        and not any(
            marker in entry
            for marker in (*REGISTRY_FORBIDDEN_EVENT_FIELDS, "retired", "succeeds")
        )
    }
    retired_here: set[tuple[Any, Any]] = set()
    minted_here: set[Any] = set()
    tail = regenerated_registry[len(base_registry) :]
    for line in tail.decode("utf-8", "replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return f"appended registry line is not JSON: {line[:120]!r}"
        if not isinstance(entry, dict):
            return f"appended registry line is not an object: {line[:120]!r}"
        concept, uuid = entry.get("concept"), entry.get("uuid")
        if not isinstance(concept, str) or not isinstance(uuid, str):
            return f"appended registry line lacks concept/uuid: {line[:120]!r}"
        if not _identity_belongs_to_rows(concept, appended_row_ids):
            return (
                f"appended identity {concept!r} belongs to no observation in "
                "this append"
            )
        forbidden = [
            marker for marker in REGISTRY_FORBIDDEN_EVENT_FIELDS if marker in entry
        ]
        if forbidden:
            return f"appended registry line carries {forbidden} for {concept!r}"
        if entry.get("retired") is True:
            if entry.get("geography") is not None or entry.get("entity") is not None:
                return f"append retires a non-placeholder identity {concept!r}"
            if (concept, uuid) not in committed_placeholders:
                return f"retire of {concept!r} matches no committed docket placeholder"
            retired_here.add((concept, uuid))
            continue
        if entry.get("geography") is None or entry.get("entity") is None:
            return f"append mints a placeholder identity for {concept!r}"
        if "succeeds" in entry:
            if (concept, uuid) not in retired_here:
                return (
                    f"succeeds-mint for {concept!r} without its placeholder "
                    "retire in this append"
                )
            continue
        if uuid in base_uuids or uuid in minted_here:
            return f"mint for {concept!r} reuses UUID {uuid}"
        minted_here.add(uuid)
    return None


def _regenerate_series_catalog(
    stage: pathlib.Path,
    *,
    candidate_ledger: bytes,
    base_registry: bytes,
    appended_row_ids: list[str] | None = None,
) -> bytes:
    """Regenerate and validate the catalog using the staged base's generator."""

    generator = stage / "scripts" / "build_series_catalog.py"
    if not generator.is_file():
        raise LedgerProposalError(
            "base commit is missing series-catalog generator "
            "scripts/build_series_catalog.py"
        )
    completed = subprocess.run(
        [sys.executable, str(generator)],
        cwd=stage,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        suffix = f": {detail[:500]}" if detail else ""
        raise LedgerProposalError(
            "staged series-catalog generator failed with exit code "
            f"{completed.returncode}{suffix}"
        )

    registry_path = stage / "ledger" / "series_uuid_registry.jsonl"
    try:
        regenerated_registry = registry_path.read_bytes()
    except OSError as exc:
        raise LedgerProposalError(
            "staged series-catalog generator removed the UUID registry"
        ) from exc
    if regenerated_registry != base_registry:
        growth_refusal = _registry_growth_refusal(
            base_registry, regenerated_registry, appended_row_ids or []
        )
        if growth_refusal:
            raise LedgerProposalError(
                "staged series-catalog generator minted or superseded series "
                f"identities beyond this append's own first observations: "
                f"{growth_refusal}"
            )

    catalog_path = stage / "ledger" / "series_catalog.json"
    try:
        catalog = catalog_path.read_bytes()
    except OSError as exc:
        raise LedgerProposalError(
            "staged series-catalog generator did not write ledger/series_catalog.json"
        ) from exc
    try:
        # Keep proposal-time checks identical to the same-commit predicate used
        # by pin_ledger before Thesis accepts a chronicle commit.
        _validate_catalog_binding(
            catalog,
            candidate_ledger,
            label="regenerated ledger/series_catalog.json",
            registry_raw=regenerated_registry,
        )
    except PinError as exc:
        raise LedgerProposalError(str(exc)) from exc
    return catalog


def _prepare_release_files(
    tree: RepositoryTree,
    *,
    path: str,
    candidate_ledger: bytes,
    added: int,
    requester: TimestampRequester,
    timeout_seconds: float,
    clock_skew_seconds: int,
    anchor_dir: pathlib.Path | None,
    now: dt.datetime | None,
    producer_signing_key: str | None,
) -> dict[str, bytes]:
    """Build and locally verify the release files before any visible push."""

    base_ledger = tree.files.get(path)
    if base_ledger is None:
        raise LedgerProposalError(f"base commit is missing ledger file {path}")
    base_offsets = jsonl_line_offsets(base_ledger, path)
    candidate_offsets = jsonl_line_offsets(candidate_ledger, path)
    if not candidate_ledger.startswith(base_ledger):
        raise LedgerProposalError(
            "proposed ledger is not an exact byte append to the base commit"
        )
    row_delta = len(candidate_offsets) - len(base_offsets)
    if row_delta <= 0:
        raise LedgerProposalError("proposed ledger does not append any rows")
    if type(added) is not int or added != row_delta:
        raise LedgerProposalError(
            f"proposal row delta is {row_delta}, but added={added!r}"
        )

    # Until the ledger's separately reviewed genesis lands, preserve the
    # existing legacy append path. In particular, the automated consumer must
    # not race that migration by inventing genesis itself.
    if not _base_has_release_chain(tree):
        return {}
    if path != LEDGER_RELATIVE.as_posix():
        raise LedgerProposalError(
            f"witnessed releases require ledger path {LEDGER_RELATIVE.as_posix()}"
        )
    prefix_path = PREFIX_RELATIVE.as_posix()
    immutable_prefix = tree.files.get(prefix_path)
    if immutable_prefix is None:
        raise LedgerProposalError(
            f"base commit is missing immutable-prefix file {prefix_path}"
        )

    timeout = _validate_timestamp_timeout(timeout_seconds)
    if type(clock_skew_seconds) is not int or clock_skew_seconds < 0:
        raise LedgerProposalError("clock_skew_seconds must be a non-negative integer")
    with tempfile.TemporaryDirectory(prefix="thesis-ledger-proposal-") as name:
        stage = pathlib.Path(name)
        _materialize_repository_tree(stage, tree)
        selected_anchors = anchor_dir or (stage / "releases" / "anchors")
        enforce_production_pins = anchor_dir is None

        # The base is verified strictly, with HEAD required to witness its
        # entire JSONL. Allowing a pending append here would permit a proposer
        # to advance an already-unwitnessed state.
        base_verification = verify_release_chain(
            stage,
            anchor_dir=selected_anchors,
            require_chain=True,
            verify_state=True,
            enforce_production_pins=enforce_production_pins,
            clock_skew_seconds=clock_skew_seconds,
        )
        registry_path = "ledger/series_uuid_registry.jsonl"
        base_registry = tree.files.get(registry_path)
        if base_registry is None:
            raise LedgerProposalError(
                f"base commit is missing UUID registry {registry_path}"
            )
        (stage / LEDGER_RELATIVE).write_bytes(candidate_ledger)
        appended_row_ids: list[str] = []
        for appended_line in candidate_ledger[len(base_ledger) :].splitlines():
            if not appended_line.strip():
                continue
            try:
                appended_row = json.loads(appended_line)
            except json.JSONDecodeError:
                appended_row = None
            if isinstance(appended_row, dict):
                appended_row_ids.append(str(appended_row.get("source_record_id", "")))
        catalog = _regenerate_series_catalog(
            stage,
            candidate_ledger=candidate_ledger,
            base_registry=base_registry,
            appended_row_ids=appended_row_ids,
        )
        manifest, manifest_raw = _build_next_release_manifest(
            candidate_ledger,
            immutable_prefix,
            base_verification,
            now=now,
        )
        filename = manifest_filename(manifest["releaseIndex"], manifest_raw)
        manifest_path = stage / MANIFEST_RELATIVE / filename
        if manifest_path.exists():
            raise LedgerProposalError(
                f"refusing to overwrite release manifest {manifest_path.name}"
            )
        producer_signature_path = producer_signature_path_for_manifest(manifest_path)
        producer_signature = _sign_release_manifest(
            manifest_raw,
            producer_signing_key,
            timeout,
        )
        # Verify against the public key materialized from the immutable base
        # tree (or the explicit test-only anchor override), never this checkout.
        verify_producer_signature_bytes(
            manifest_raw,
            producer_signature,
            anchor_dir=selected_anchors,
            enforce_production_pin=enforce_production_pins,
            label=producer_signature_path.name,
        )
        query = _build_timestamp_query(manifest_raw, timeout)
        receipts = _request_timestamp_receipts(
            query,
            requester=requester,
            timeout_seconds=timeout,
        )

        manifest_path.write_bytes(manifest_raw)
        receipt_paths = receipt_paths_for_manifest(manifest_path)
        for tsa, token in receipts.items():
            receipt_paths[tsa].write_bytes(token)
        producer_signature_path.write_bytes(producer_signature)
        verify_release_chain(
            stage,
            anchor_dir=selected_anchors,
            require_chain=True,
            verify_state=True,
            enforce_production_pins=enforce_production_pins,
            clock_skew_seconds=clock_skew_seconds,
        )
        changes = {
            (stage_path.relative_to(stage).as_posix()): stage_path.read_bytes()
            for stage_path in (
                manifest_path,
                *receipt_paths.values(),
                producer_signature_path,
            )
        } | {"ledger/series_catalog.json": catalog}
        regenerated_registry = (stage / registry_path).read_bytes()
        if regenerated_registry != base_registry:
            # The catalog binds the registry it was generated against; a
            # first-observation mint the growth gate accepted must ship in
            # the same proposal commit or the merged state is incoherent.
            changes[registry_path] = regenerated_registry
        return changes


def ledger_state(repo: str, branch: str, path: str) -> tuple[str, str, str]:
    """Return (content, blob_sha, repository HEAD sha) for the ledger."""
    repo_sha = subprocess.run(
        ["gh", "api", f"repos/{repo}/commits/{branch}", "--jq", ".sha"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    raw = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repo}/contents/{path}?ref={repo_sha}",
            "--jq",
            "{sha: .sha, content: .content}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    payload = json.loads(raw)
    import base64

    return base64.b64decode(payload["content"]).decode(), payload["sha"], repo_sha


def _gh_api(*args: str, input_body: dict[str, Any] | None = None) -> str:
    # Without `--input -` gh ignores stdin and sends an empty request body
    # (GitHub answers 422 "nil is not an object"); the flag precedes the
    # endpoint so callers' path arguments stay the trailing tokens.
    body_flags = ["--input", "-"] if input_body is not None else []
    command = ["gh", "api", *body_flags, *args]
    completed = subprocess.run(
        command,
        input=json.dumps(input_body) if input_body is not None else None,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"gh api {' '.join(args)} failed: {completed.stderr.strip()[:500]}"
        )
    return completed.stdout


def _git_object_sha(value: Any, label: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise LedgerProposalError(f"GitHub returned an invalid {label}: {value!r}")
    return value


def _fetch_git_blob(repo: str, sha: str) -> bytes:
    sha = _git_object_sha(sha, "requested blob SHA")
    payload = json.loads(_gh_api(f"repos/{repo}/git/blobs/{sha}"))
    response_sha = _git_object_sha(payload.get("sha"), "returned blob SHA")
    if response_sha != sha:
        raise LedgerProposalError(
            f"GitHub returned blob {response_sha} for requested blob {sha}"
        )
    if payload.get("encoding") != "base64" or type(payload.get("content")) is not str:
        raise LedgerProposalError(f"GitHub blob {sha} is not base64 encoded")
    try:
        encoded = "".join(payload["content"].split())
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise LedgerProposalError(f"GitHub blob {sha} has invalid base64") from exc
    size = payload.get("size")
    if type(size) is not int or size != len(raw):
        raise LedgerProposalError(
            f"GitHub blob {sha} size mismatch: reported={size!r}, actual={len(raw)}"
        )
    header = f"blob {len(raw)}\0".encode("ascii")
    actual_sha = hashlib.sha1(
        header + raw,
        usedforsecurity=False,
    ).hexdigest()
    if actual_sha != sha:
        raise LedgerProposalError(
            f"GitHub blob bytes do not match tree object {sha}: {actual_sha}"
        )
    return raw


def _git_tree_object_sha(entries: list[dict[str, str]]) -> str:
    body = bytearray()
    for entry in entries:
        mode = entry["mode"].lstrip("0") or "0"
        body.extend(f"{mode} {entry['path']}\0".encode("utf-8"))
        body.extend(bytes.fromhex(entry["sha"]))
    header = f"tree {len(body)}\0".encode("ascii")
    return hashlib.sha1(header + body, usedforsecurity=False).hexdigest()


def _fetch_git_tree(
    repo: str,
    tree_sha: str,
    cache: dict[str, dict[str, dict[str, str]]],
) -> dict[str, dict[str, str]]:
    tree_sha = _git_object_sha(tree_sha, "requested tree SHA")
    if tree_sha in cache:
        return cache[tree_sha]
    payload = json.loads(_gh_api(f"repos/{repo}/git/trees/{tree_sha}"))
    if type(payload) is not dict:
        raise LedgerProposalError(f"GitHub tree {tree_sha} response is not an object")
    response_sha = _git_object_sha(payload.get("sha"), "returned tree SHA")
    if response_sha != tree_sha:
        raise LedgerProposalError(
            f"GitHub returned tree {response_sha} for requested tree {tree_sha}"
        )
    if payload.get("truncated") is not False:
        raise LedgerProposalError(
            f"GitHub returned a truncated tree for object {tree_sha}"
        )
    raw_entries = payload.get("tree")
    if type(raw_entries) is not list:
        raise LedgerProposalError(f"GitHub tree {tree_sha} has no entry list")
    entries: dict[str, dict[str, str]] = {}
    ordered: list[dict[str, str]] = []
    for raw_entry in raw_entries:
        if type(raw_entry) is not dict:
            raise LedgerProposalError(f"GitHub tree {tree_sha} has a malformed entry")
        path = raw_entry.get("path")
        mode = raw_entry.get("mode")
        object_type = raw_entry.get("type")
        if (
            type(path) is not str
            or not path
            or "/" in path
            or path in {".", ".."}
            or "\0" in path
            or type(mode) is not str
            or type(object_type) is not str
        ):
            raise LedgerProposalError(
                f"GitHub tree {tree_sha} has an unsafe direct entry"
            )
        valid_kind = (
            (object_type == "tree" and mode == "040000")
            or (object_type == "blob" and mode in {"100644", "100755", "120000"})
            or (object_type == "commit" and mode == "160000")
        )
        if not valid_kind:
            raise LedgerProposalError(
                f"GitHub tree {tree_sha} has invalid type/mode for {path}: "
                f"{object_type}/{mode}"
            )
        if path in entries:
            raise LedgerProposalError(
                f"GitHub tree {tree_sha} contains duplicate path {path!r}"
            )
        entry = {
            "path": path,
            "mode": mode,
            "type": object_type,
            "sha": _git_object_sha(raw_entry.get("sha"), f"object SHA for {path}"),
        }
        entries[path] = entry
        ordered.append(entry)
    computed_sha = _git_tree_object_sha(ordered)
    if computed_sha != tree_sha:
        raise LedgerProposalError(
            f"GitHub tree entries hash to {computed_sha}, expected {tree_sha}; "
            "refusing partial base state"
        )
    cache[tree_sha] = entries
    return entries


def _repository_blob_at_path(
    repo: str,
    root_entries: dict[str, dict[str, str]],
    path: str,
    cache: dict[str, dict[str, dict[str, str]]],
    *,
    required: bool,
) -> tuple[bytes, str, str] | None:
    relative = _validated_repository_path(path)
    entries = root_entries
    for component in relative.parts[:-1]:
        entry = entries.get(component)
        if entry is None:
            if required:
                raise LedgerProposalError(f"base commit is missing {path}")
            return None
        if entry["type"] != "tree" or entry["mode"] != "040000":
            raise LedgerProposalError(
                f"base path component is not a regular tree: {component}"
            )
        entries = _fetch_git_tree(repo, entry["sha"], cache)
    entry = entries.get(relative.name)
    if entry is None:
        if required:
            raise LedgerProposalError(f"base commit is missing {path}")
        return None
    if entry["type"] != "blob" or entry["mode"] not in {"100644", "100755"}:
        raise LedgerProposalError(f"base tree entry is not a regular file: {path}")
    return _fetch_git_blob(repo, entry["sha"]), entry["mode"], entry["sha"]


def _collect_release_tree_files(
    repo: str,
    tree_sha: str,
    prefix: pathlib.PurePosixPath,
    cache: dict[str, dict[str, dict[str, str]]],
    files: dict[str, bytes],
    modes: dict[str, str],
    blob_shas: dict[str, str],
) -> None:
    entries = _fetch_git_tree(repo, tree_sha, cache)
    for name, entry in entries.items():
        relative = prefix / name
        if entry["type"] == "tree":
            _collect_release_tree_files(
                repo,
                entry["sha"],
                relative,
                cache,
                files,
                modes,
                blob_shas,
            )
            continue
        if entry["type"] != "blob" or entry["mode"] not in {"100644", "100755"}:
            raise LedgerProposalError(
                f"base release entry is not a regular file: {relative}"
            )
        path = _validated_repository_path(relative.as_posix()).as_posix()
        files[path] = _fetch_git_blob(repo, entry["sha"])
        modes[path] = entry["mode"]
        blob_shas[path] = entry["sha"]


# Same-commit inputs the staged catalog regeneration needs beyond the ledger
# itself: the generator, the gate module it imports, and the generator's three
# data inputs (prior catalog for identity carry-over, UUID registry, docket
# seed). _prepare_release_files refuses the witnessed append when any of these
# is absent from the base commit, so dropping one here fails closed rather
# than silently skipping regeneration.
CATALOG_REGENERATION_INPUTS = (
    "scripts/build_series_catalog.py",
    "scripts/check_thesis_facts_append.py",
    "scripts/receipt_pins.py",
    "ledger/series_catalog.json",
    "ledger/series_uuid_registry.jsonl",
    "ledger/seeds/thesis_docket_series.json",
)


def _fetch_repository_tree(
    repo: str, commit_sha: str, ledger_path: str
) -> RepositoryTree:
    """Fetch the exact ledger/release subset from one immutable commit tree."""

    commit_sha = _git_object_sha(commit_sha, "commit SHA")
    commit = json.loads(_gh_api(f"repos/{repo}/git/commits/{commit_sha}"))
    if type(commit) is not dict:
        raise LedgerProposalError(
            f"GitHub commit {commit_sha} response is not an object"
        )
    response_sha = _git_object_sha(commit.get("sha"), "returned commit SHA")
    if response_sha != commit_sha:
        raise LedgerProposalError(
            f"GitHub returned commit {response_sha} for requested commit {commit_sha}"
        )
    tree_payload = commit.get("tree")
    if type(tree_payload) is not dict:
        raise LedgerProposalError(f"GitHub commit {commit_sha} has no tree")
    tree_sha = _git_object_sha(tree_payload.get("sha"), "tree SHA")
    cache: dict[str, dict[str, dict[str, str]]] = {}
    root_entries = _fetch_git_tree(repo, tree_sha, cache)
    files: dict[str, bytes] = {}
    modes: dict[str, str] = {}
    blob_shas: dict[str, str] = {}
    for wanted, required in (
        (ledger_path, True),
        (PREFIX_RELATIVE.as_posix(), False),
        *((path, False) for path in CATALOG_REGENERATION_INPUTS),
    ):
        blob = _repository_blob_at_path(
            repo, root_entries, wanted, cache, required=required
        )
        if blob is not None:
            payload, mode, blob_sha = blob
            files[wanted] = payload
            modes[wanted] = mode
            blob_shas[wanted] = blob_sha
    releases = root_entries.get("releases")
    if releases is not None:
        if releases["type"] != "tree" or releases["mode"] != "040000":
            raise LedgerProposalError("base releases path is not a regular tree")
        _collect_release_tree_files(
            repo,
            releases["sha"],
            pathlib.PurePosixPath("releases"),
            cache,
            files,
            modes,
            blob_shas,
        )
    return RepositoryTree(
        tree_sha=tree_sha,
        files=files,
        modes=modes,
        blob_shas=blob_shas,
    )


def _upload_git_blob(repo: str, payload: bytes) -> str:
    response = json.loads(
        _gh_api(
            "-X",
            "POST",
            f"repos/{repo}/git/blobs",
            input_body={
                "content": base64.b64encode(payload).decode("ascii"),
                "encoding": "base64",
            },
        )
    )
    return _git_object_sha(response.get("sha"), "created blob SHA")


def _publish_proposal_commit(
    repo: str,
    *,
    base_sha: str,
    base_tree_sha: str,
    message: str,
    changes: Mapping[str, bytes],
) -> str:
    """Create one unreferenced commit containing every proposal change."""

    if not changes:
        raise LedgerProposalError("proposal commit has no changes")
    tree_entries: list[dict[str, str]] = []
    for relative, payload in sorted(changes.items()):
        relative = _validated_repository_path(relative).as_posix()
        if type(payload) is not bytes:
            raise LedgerProposalError(f"proposal payload is not bytes: {relative}")
        tree_entries.append(
            {
                "path": relative,
                "mode": "100644",
                "type": "blob",
                "sha": _upload_git_blob(repo, payload),
            }
        )
    tree_response = json.loads(
        _gh_api(
            "-X",
            "POST",
            f"repos/{repo}/git/trees",
            input_body={"base_tree": base_tree_sha, "tree": tree_entries},
        )
    )
    candidate_tree_sha = _git_object_sha(tree_response.get("sha"), "created tree SHA")
    commit_response = json.loads(
        _gh_api(
            "-X",
            "POST",
            f"repos/{repo}/git/commits",
            input_body={
                "message": message,
                "tree": candidate_tree_sha,
                "parents": [base_sha],
            },
        )
    )
    return _git_object_sha(commit_response.get("sha"), "proposal commit SHA")


def _branch_head(repo: str, branch: str) -> str:
    value = _gh_api(f"repos/{repo}/commits/{branch}", "--jq", ".sha").strip()
    return _git_object_sha(value, f"{branch} branch HEAD")


def _is_github_not_found(error: Exception) -> bool:
    diagnostic = str(error).lower()
    return "http 404" in diagnostic or "(404)" in diagnostic


def _proposal_ref_sha(repo: str, proposal: str) -> str | None:
    try:
        payload = json.loads(_gh_api(f"repos/{repo}/git/ref/heads/{proposal}"))
    except RuntimeError as exc:
        if _is_github_not_found(exc):
            return None
        raise
    target = payload.get("object")
    if type(target) is not dict:
        raise LedgerProposalError(f"proposal ref {proposal} has no target object")
    return _git_object_sha(target.get("sha"), f"target of proposal ref {proposal}")


def _find_open_proposal_pr(repo: str, proposal: str) -> int | None:
    owner, separator, _name = repo.partition("/")
    if not separator or not owner:
        raise LedgerProposalError(f"invalid GitHub repository name: {repo!r}")
    head = quote(f"{owner}:{proposal}", safe="")
    payload = json.loads(
        _gh_api(f"repos/{repo}/pulls?state=open&head={head}&per_page=10")
    )
    if type(payload) is not list:
        raise LedgerProposalError("GitHub open-PR recovery response is not a list")
    numbers = [entry.get("number") for entry in payload if type(entry) is dict]
    if any(type(number) is not int for number in numbers):
        raise LedgerProposalError("GitHub open-PR recovery returned an invalid number")
    if len(numbers) > 1:
        raise LedgerProposalError(
            f"multiple open PRs unexpectedly use proposal branch {proposal}"
        )
    return numbers[0] if numbers else None


def _proposal_pr_identity(
    repo: str,
    pr_number: int,
    *,
    expected_head_sha: str,
    expected_base: str,
    expected_base_sha: str | None = None,
) -> dict[str, Any]:
    payload = json.loads(_gh_api(f"repos/{repo}/pulls/{pr_number}"))
    if type(payload) is not dict:
        raise LedgerProposalError("GitHub pull-request response is not an object")
    head = payload.get("head")
    base = payload.get("base")
    matches = (
        type(head) is dict
        and head.get("sha") == expected_head_sha
        and type(base) is dict
        and base.get("ref") == expected_base
    )
    if expected_base_sha is not None:
        matches = matches and base.get("sha") == expected_base_sha
    if not matches:
        raise LedgerProposalError(
            "pull request no longer has the expected proposal head and base"
        )
    return payload


def _merged_proposal_sha(
    repo: str,
    pr_number: int,
    *,
    expected_head_sha: str,
    expected_base: str,
) -> str | None:
    """Recover a merge that may have succeeded despite a lost response."""

    payload = _proposal_pr_identity(
        repo,
        pr_number,
        expected_head_sha=expected_head_sha,
        expected_base=expected_base,
    )
    if payload.get("merged") is not True:
        return None
    return _git_object_sha(
        payload.get("merge_commit_sha"),
        f"merged commit SHA for pull request {pr_number}",
    )


def _cleanup_proposal(
    repo: str,
    proposal: str,
    *,
    ref_created: bool,
    ref_creation_attempted: bool,
    proposal_commit: str,
    pr_number: int | None,
    pr_creation_attempted: bool,
    merged: bool,
) -> list[str]:
    failures: list[str] = []
    if pr_number is None and pr_creation_attempted and not merged:
        try:
            pr_number = _find_open_proposal_pr(repo, proposal)
        except Exception as exc:
            failures.append(f"locate possibly-created PR: {exc}")
    if pr_number is not None and not merged:
        try:
            _gh_api(
                "-X",
                "PATCH",
                f"repos/{repo}/pulls/{pr_number}",
                input_body={"state": "closed"},
            )
        except Exception as exc:
            failures.append(f"close PR #{pr_number}: {exc}")
    should_delete_ref = ref_created
    if not ref_created and ref_creation_attempted:
        try:
            recovered_sha = _proposal_ref_sha(repo, proposal)
            if recovered_sha is not None and recovered_sha != proposal_commit:
                failures.append(
                    f"ref {proposal} points to unexpected commit {recovered_sha}; "
                    "refusing to delete it"
                )
            else:
                should_delete_ref = recovered_sha is not None
        except Exception as exc:
            failures.append(f"locate possibly-created branch {proposal}: {exc}")
    if should_delete_ref:
        try:
            _gh_api("-X", "DELETE", f"repos/{repo}/git/refs/heads/{proposal}")
        except Exception as exc:
            failures.append(f"delete branch {proposal}: {exc}")
    return failures


def _verify_remote_proposal_state(
    repo: str,
    commit_sha: str,
    *,
    path: str,
    candidate_ledger: bytes,
    release_files: Mapping[str, bytes],
    clock_skew_seconds: int,
    anchor_dir: pathlib.Path | None,
) -> None:
    """Re-fetch and fully verify the exact merged repository state."""

    tree = _fetch_repository_tree(repo, commit_sha, path)
    if tree.files.get(path) != candidate_ledger:
        raise LedgerProposalError(
            "merged commit ledger bytes do not equal the verified proposal"
        )
    for relative, expected in release_files.items():
        if tree.files.get(relative) != expected:
            raise LedgerProposalError(
                f"merged commit release bytes differ from proposal: {relative}"
            )
    with tempfile.TemporaryDirectory(prefix="thesis-ledger-merged-") as name:
        stage = pathlib.Path(name)
        _materialize_repository_tree(stage, tree)
        has_chain = _base_has_release_chain(tree)
        selected_anchors = anchor_dir or (stage / "releases" / "anchors")
        verification = verify_release_chain(
            stage,
            anchor_dir=selected_anchors,
            require_chain=has_chain,
            verify_state=True,
            enforce_production_pins=anchor_dir is None,
            clock_skew_seconds=clock_skew_seconds,
        )
        if release_files and verification.head is None:
            raise LedgerProposalError("merged release chain unexpectedly has no HEAD")


def append_gate_verdict(gate_runs: list[dict]) -> bool:
    """True when the append gate genuinely passed on a proposal head.

    The gate workflow fires on several events, so the same head carries one
    real "Append gate" run per delivering event plus skipped twins from the
    events whose job-level condition did not match. A skipped twin is not a
    verdict: the gate passed when at least one run concluded success and
    none concluded against the proposal.
    """
    conclusions = [run.get("conclusion") for run in gate_runs]
    if any(c not in ("success", "skipped", "neutral") for c in conclusions):
        return False
    return "success" in conclusions


def propose_ledger_append(
    repo: str,
    branch: str,
    path: str,
    content: str,
    blob_sha: str,
    base_sha: str,
    added: int,
    *,
    poll_seconds: int = 20,
    poll_attempts: int = 30,
    timestamp_requester: TimestampRequester | None = None,
    timestamp_timeout_seconds: float = DEFAULT_TIMESTAMP_TIMEOUT_SECONDS,
    clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS,
    release_anchor_dir: pathlib.Path | None = None,
    release_now: dt.datetime | None = None,
    producer_signing_key: str | None = None,
) -> str:
    """Publish one fully witnessed commit through the reviewed append gate."""

    environment_signing_key = os.environ.pop(PRODUCER_SIGNING_KEY_ENV, None)
    if producer_signing_key is None:
        producer_signing_key = environment_signing_key
    candidate_ledger = content.encode("utf-8")
    base_tree = _fetch_repository_tree(repo, base_sha, path)
    if base_tree.blob_shas.get(path) != blob_sha:
        raise LedgerProposalError(
            "base ledger blob differs from the state used to build the append"
        )
    release_files = _prepare_release_files(
        base_tree,
        path=path,
        candidate_ledger=candidate_ledger,
        added=added,
        requester=timestamp_requester or request_timestamp,
        timeout_seconds=timestamp_timeout_seconds,
        clock_skew_seconds=clock_skew_seconds,
        anchor_dir=release_anchor_dir,
        now=release_now,
        producer_signing_key=producer_signing_key,
    )
    message = f"Record {added} first-print observation(s) via resolve_pending.py"
    changes = {path: candidate_ledger, **release_files}
    proposal_commit = _publish_proposal_commit(
        repo,
        base_sha=base_sha,
        base_tree_sha=base_tree.tree_sha,
        message=message,
        changes=changes,
    )
    current_base = _branch_head(repo, branch)
    if current_base != base_sha:
        raise LedgerProposalError(
            f"ledger branch moved while proposal was prepared: {base_sha} -> "
            f"{current_base}; retry against the new trusted state"
        )

    stamp = utc_now().lower().replace(":", "-").replace("t", "-")
    proposal = f"thesis-facts-append/{stamp}-{time.time_ns():x}"
    ref_created = False
    ref_creation_attempted = False
    pr_number: int | None = None
    pr_creation_attempted = False
    merged = False
    try:
        ref_creation_attempted = True
        _gh_api(
            "-X",
            "POST",
            f"repos/{repo}/git/refs",
            input_body={
                "ref": f"refs/heads/{proposal}",
                "sha": proposal_commit,
            },
        )
        ref_created = True
        pr_creation_attempted = True
        pr = json.loads(
            _gh_api(
                "-X",
                "POST",
                f"repos/{repo}/pulls",
                input_body={
                    "title": message,
                    "head": proposal,
                    "base": branch,
                    "body": (
                        "Automated witnessed append proposal from "
                        f"resolve_pending.py: {added} first-print observation(s) "
                        f"built against {base_sha}. The proposal commit contains "
                        "the ledger append and its complete four-sibling release, "
                        "and "
                        "merges only after the thesis-facts append gate passes."
                    ),
                },
            )
        )
        if type(pr.get("number")) is not int:
            raise LedgerProposalError("GitHub did not return a pull-request number")
        pr_number = pr["number"]

        gate_passed = False
        for _ in range(poll_attempts):
            runs = json.loads(
                _gh_api(f"repos/{repo}/commits/{proposal_commit}/check-runs")
            ).get("check_runs", [])
            gate_runs = [run for run in runs if run.get("name") == "Append gate"]
            if gate_runs and all(run.get("status") == "completed" for run in gate_runs):
                gate_passed = append_gate_verdict(gate_runs)
                break
            time.sleep(poll_seconds)
        if not gate_passed:
            raise LedgerProposalError(
                f"append gate did not pass for {repo}#{pr_number}; refusing to "
                "leave a failed proposal branch or PR"
            )

        current_base = _branch_head(repo, branch)
        if current_base != base_sha:
            raise LedgerProposalError(
                f"ledger branch moved while proposal awaited the append gate: "
                f"{base_sha} -> {current_base}; refusing to rebase a release "
                "built against stale state"
            )

        pr_state = _proposal_pr_identity(
            repo,
            pr_number,
            expected_head_sha=proposal_commit,
            expected_base=branch,
            expected_base_sha=base_sha,
        )
        if pr_state.get("merged") is True:
            raise LedgerProposalError(
                f"pull request {repo}#{pr_number} merged before the controlled merge"
            )

        ambiguous_merge_error: BaseException | None = None
        merge_response: Any = None
        try:
            merge_raw = _gh_api(
                "-X",
                "PUT",
                f"repos/{repo}/pulls/{pr_number}/merge",
                input_body={
                    "merge_method": "rebase",
                    "sha": proposal_commit,
                },
            )
        except RuntimeError as exc:
            ambiguous_merge_error = exc
        else:
            try:
                merge_response = json.loads(merge_raw)
            except json.JSONDecodeError as exc:
                ambiguous_merge_error = exc
            if type(merge_response) is not dict:
                ambiguous_merge_error = LedgerProposalError(
                    "GitHub merge response is not an object"
                )

        if ambiguous_merge_error is not None:
            recovered_sha = _merged_proposal_sha(
                repo,
                pr_number,
                expected_head_sha=proposal_commit,
                expected_base=branch,
            )
            if recovered_sha is None:
                raise ambiguous_merge_error
            merged_sha = recovered_sha
        else:
            assert isinstance(merge_response, dict)
            if merge_response.get("merged") is not True:
                raise LedgerProposalError(
                    f"GitHub did not merge {repo}#{pr_number}: "
                    f"{merge_response.get('message', 'no diagnostic')}"
                )
            response_merged_sha = _git_object_sha(
                merge_response.get("sha"), "merged commit SHA"
            )
            confirmed_sha = _merged_proposal_sha(
                repo,
                pr_number,
                expected_head_sha=proposal_commit,
                expected_base=branch,
            )
            if confirmed_sha is None:
                raise LedgerProposalError(
                    "GitHub merge response was not confirmed by pull-request state"
                )
            if confirmed_sha != response_merged_sha:
                raise LedgerProposalError(
                    "GitHub merge response SHA disagrees with pull-request state: "
                    f"{response_merged_sha} != {confirmed_sha}"
                )
            merged_sha = confirmed_sha
        merged = True
        _verify_remote_proposal_state(
            repo,
            merged_sha,
            path=path,
            candidate_ledger=candidate_ledger,
            release_files=release_files,
            clock_skew_seconds=clock_skew_seconds,
            anchor_dir=release_anchor_dir,
        )
        _gh_api("-X", "DELETE", f"repos/{repo}/git/refs/heads/{proposal}")
        ref_created = False
        return merged_sha
    except BaseException as exc:
        cleanup_failures = _cleanup_proposal(
            repo,
            proposal,
            ref_created=ref_created,
            ref_creation_attempted=ref_creation_attempted,
            proposal_commit=proposal_commit,
            pr_number=pr_number,
            pr_creation_attempted=pr_creation_attempted,
            merged=merged,
        )
        if cleanup_failures:
            raise LedgerProposalError(
                f"proposal failed ({exc}); cleanup also failed: "
                + "; ".join(cleanup_failures)
            ) from exc
        raise


def registration_contracts(
    records_dir: pathlib.Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Map preregistered dataPointIds to their verified contracts.

    Snapshot content hashes deliberately exclude the operational
    ``registeredAtUtc`` (v2+), so verification must use the schema-aware
    ``registration_content_hash``, never a whole-file canonical hash.
    """
    records_dir = records_dir or ROOT / "records" / "targets"
    contracts: dict[str, dict[str, Any]] = {}
    unresolved_published: set[str] = set()
    if not records_dir.exists():
        return contracts
    for path in sorted(records_dir.glob("*.json")):
        match = re.fullmatch(r"\d{4}-\d{2}-\d{2}-([0-9a-f]{64})\.json", path.name)
        if not match:
            continue
        try:
            snapshot = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        try:
            content_hash = registration_content_hash(snapshot)
        except RegistrationError as exc:
            raise ValueError(f"invalid target registration {path}: {exc}") from exc
        if content_hash != match.group(1):
            raise ValueError(f"target registration hash mismatch: {path}")
        for target in snapshot.get("targets", []):
            data_point_id = target.get("dataPointId")
            if not data_point_id:
                continue
            key = str(data_point_id)
            entry = {
                "targetContentHash": content_hash,
                "contract": target,
                "ledgerPin": snapshot.get("ledgerPin"),
            }
            existing = contracts.get(key)
            if existing is None:
                contracts[key] = entry
                continue
            # A dataPointId can be registered in more than one snapshot (a
            # per-target snapshot plus a later batch set). Lexicographic file
            # order used to silently pick whichever sorted last, so an
            # appended fact could carry a valid-but-wrong contract hash and
            # then be excluded by the site's target-hash check (finding 9).
            # Resolve to whichever registration the PUBLISHED target actually
            # committed; identical duplicates are fine; a conflict the
            # published set does not disambiguate fails closed.
            if existing["targetContentHash"] == content_hash and (
                canonical_bytes(existing["contract"]) == canonical_bytes(target)
            ):
                continue
            published = published_target_hashes().get(key)
            if published is None:
                # An unpublished (prospect/registered-not-yet-scored)
                # dataPointId is never looked up during resolution — the
                # resolver only appends to published pending cells — so a
                # duplicate here cannot mis-score. Pick deterministically by
                # the freshest registration rather than lexical file order.
                if _registered_at(target) >= _registered_at(existing["contract"]):
                    contracts[key] = entry
                continue
            # For a PUBLISHED target the fact must carry the exact hash its
            # cell committed, or the site excludes the score. Resolve to the
            # published registration; a conflict the published set does not
            # contain fails closed (finding 9).
            if content_hash == published:
                contracts[key] = entry
                unresolved_published.discard(key)
            elif existing["targetContentHash"] != published:
                # Neither candidate seen so far matches the published hash.
                # Supersede history retains every snapshot for a dataPointId,
                # and file order is date-lexicographic, so the matching
                # snapshot may simply not have been scanned yet. Defer the
                # fail-closed decision to the end of the scan.
                unresolved_published.add(key)
    for key in sorted(unresolved_published):
        published = published_target_hashes().get(key)
        if contracts[key]["targetContentHash"] != published:
            raise ValueError(
                f"neither registration for published dataPointId {key} "
                f"matches its target hash {(published or '')[:16]}…; resolve "
                "the duplicate before appending"
            )
    return contracts


def _registered_at(contract: dict[str, Any]) -> str:
    return str(contract.get("registeredAtUtc") or contract.get("registeredAt") or "")


_PUBLISHED_TARGET_HASHES: dict[str, str] | None = None


def published_target_hashes(
    generated_path: pathlib.Path | None = None,
) -> dict[str, str]:
    """Map each published dataPointId to the target hash its cell committed.

    The generated target module is what the site actually scores against, so
    it is the authority for which registration a duplicate dataPointId
    resolves to.
    """
    global _PUBLISHED_TARGET_HASHES
    if _PUBLISHED_TARGET_HASHES is not None and generated_path is None:
        return _PUBLISHED_TARGET_HASHES
    path = generated_path or (
        ROOT / "site" / "src" / "data" / "ledger-targets.generated.ts"
    )
    mapping: dict[str, str] = {}
    if path.exists():
        # Each entry names its dataPointId before its targetContentHash; only
        # preregistered v2/v3 targets carry a hash (the hardcoded legacy
        # targets do not), so map each hash to the nearest preceding id.
        current: str | None = None
        for line in path.read_text().splitlines():
            dpid = re.search(r'dataPointId:\s*"([^"]+)"', line)
            if dpid:
                current = dpid.group(1)
                continue
            thash = re.search(r'targetContentHash:\s*"([0-9a-f]{64})"', line)
            if thash and current is not None:
                mapping[current] = thash.group(1)
    if generated_path is None:
        _PUBLISHED_TARGET_HASHES = mapping
    return mapping


ASSERTION_CONTENT_KEYS = (
    "source_record_id",
    "value",
    "observed_at",
    "period",
    "geography",
    "entity",
    "aggregation",
    "filters",
    "domain",
)


def assertion_version_projection(row: dict[str, Any]) -> dict[str, Any]:
    """The canonical projection that content-addresses an assertion (av2).

    Committed to everything that changes what the assertion MEANS —
    identity, value, timing, population, the FULL measure (concept mapping
    and authority, not just concept/unit), exact publisher provenance
    including source file and byte digest, source row/cell lineage, and the
    archived response digest. Two assertions that differ in any of these
    get different IDs; a correction must supersede explicitly (finding 3).
    Kept byte-identical with the ledger append gate's recomputation.
    """
    measure = row.get("measure") or {}
    source = row.get("source") or {}
    projection = {key: row.get(key) for key in ASSERTION_CONTENT_KEYS}
    projection["measure"] = {
        "concept": measure.get("concept"),
        "unit": measure.get("unit"),
        "source_concept": measure.get("source_concept"),
        "concept_relation": measure.get("concept_relation"),
        "concept_authority": measure.get("concept_authority"),
        "legal_vintage": measure.get("legal_vintage"),
    }
    projection["source"] = {
        "source_name": source.get("source_name"),
        "source_table": source.get("source_table"),
        "source_file": source.get("source_file"),
        "url": source.get("url"),
        "vintage": source.get("vintage"),
        "source_sha256": source.get("source_sha256"),
    }
    projection["lineage"] = {
        "source_row_keys": row.get("source_row_keys"),
        "source_cell_keys": row.get("source_cell_keys"),
    }
    projection["responseArchiveSha256"] = (row.get("responseArchive") or {}).get(
        "sha256"
    )
    return projection


def assertion_version(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"av2:{canonical_sha256(assertion_version_projection(row))}",
        "supersedes": None,
    }


def source_binding_projection(
    registration: dict[str, Any], row: dict[str, Any], raw: bytes
) -> dict[str, Any]:
    """Bind the appended fact to the registered resolver contract.

    The projection is derived from the ROW's own content, then each derived
    field is checked against the registration; a mismatch fails the append.
    Copying the registration's fields wholesale would make the site's
    contract check tautological — a row from a different publisher, period,
    or concept would still "match". Deriving from the row and rejecting on
    mismatch is what actually binds the appended fact to its target
    (finding 1). The archived-response digest binds the bytes; a trusted
    parse proof that the value came FROM those bytes is the resolver's job
    (it built both row and archive from the same fetch) and remains the
    step-5 hardening for an untrusted writer.
    """
    contract = registration["contract"]
    binding = contract.get("sourceBinding") or {}
    measure = row.get("measure") or {}
    row_source = row.get("source") or {}
    record_id = row.get("source_record_id")

    row_unit = measure.get("unit")
    row_concept = measure.get("concept")
    # Direct field equalities that need no fragile period re-tokenization: a
    # row from a different publisher carries a different measure concept, and
    # the registration lookup already keyed on the row's source_record_id, so
    # the period is pinned by identity. unit + concept + publisher host close
    # the "unrelated row scores as contract_bound" hole (finding 1).
    if row_unit != contract.get("unit"):
        raise ValueError(
            f"fact unit {row_unit!r} does not match registered unit "
            f"{contract.get('unit')!r} for {record_id}"
        )
    registered_series = contract.get("series")
    if registered_series is not None and row_concept != registered_series:
        # International ledger rows carry the period-suffixed concept
        # convention (concept == dataPointId minus its release-policy
        # token: abs.labour.employment_change.australia.june_2026 for
        # ...june_2026.first_print — every pre-existing abs/eurostat/
        # statjp row is immutable precedent). Accept EXACTLY that
        # identity-derived form: a strict dot-prefix of the row's own
        # record id that strictly extends the registered series, which
        # binds the series AND the period. Anything else still refuses.
        suffixed_form = (
            isinstance(row_concept, str)
            and isinstance(record_id, str)
            and record_id.startswith(f"{registered_series}.")
            and record_id.startswith(f"{row_concept}.")
            and len(row_concept) > len(registered_series)
        )
        if not suffixed_form:
            raise ValueError(
                f"fact measure concept {row_concept!r} does not match the "
                f"registered series {registered_series!r} for {record_id}"
            )
    allowed_hosts = binding.get("allowedHosts")
    row_url = row_source.get("url") or measure.get("concept_evidence_url")
    if allowed_hosts and row_url:
        host = urlparse(str(row_url)).hostname
        if host not in allowed_hosts:
            raise ValueError(
                f"fact source host {host!r} is not in the registered "
                f"allowedHosts {allowed_hosts} for {record_id}"
            )
    return {
        "series": registered_series,
        "concept": row_concept,
        "period": contract.get("period"),
        "releasePolicy": binding.get("releasePolicy"),
        "table": binding.get("table"),
        "field": binding.get("field"),
        "transform": binding.get("transform"),
        "unit": row_unit,
        "sourceUrl": str(row_url) if row_url else None,
        "responseSha256": hashlib.sha256(raw).hexdigest(),
    }


def archive_response(
    run_dir: pathlib.Path,
    *,
    series_id: str,
    vintage: str,
    raw: bytes,
    extension: str = "csv",
) -> dict[str, Any]:
    """Write one deterministic gzip archive and return its hash reference."""
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    compressed = gzip.compress(raw, mtime=0)
    gzip_sha256 = hashlib.sha256(compressed).hexdigest()
    name = f"{series_id.lower()}-{vintage}-{raw_sha256[:16]}.{extension}.gz"
    path = run_dir / "responses" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(compressed)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": raw_sha256,
        "bytes": len(raw),
        "gzipSha256": gzip_sha256,
        "gzipBytes": len(compressed),
        "contentEncoding": "gzip",
    }


def attach_resolution_provenance(
    row: dict[str, Any],
    *,
    run_dir: pathlib.Path,
    series_id: str,
    vintage: str,
    raw: bytes,
    retrieved_at: str,
    ledger_repo_sha: str,
    target_contracts: dict[str, dict[str, Any]],
    extension: str = "csv",
) -> dict[str, Any]:
    registration = target_contracts.get(str(row["source_record_id"]))
    projection = None
    if registration:
        # Projection is a refusal gate. Run it before writing any response so
        # a rejected row cannot leave an orphan archive in a mixed run.
        projection = source_binding_projection(registration, row, raw)
    response_archive = archive_response(
        run_dir,
        series_id=series_id,
        vintage=vintage,
        raw=raw,
        extension=extension,
    )
    output = {
        **row,
        "ledgerRepoSha": ledger_repo_sha,
        "sourceVintage": vintage,
        "retrievedAt": retrieved_at,
        "responseArchive": response_archive,
    }
    output["assertionVersion"] = assertion_version(output)
    if registration:
        output["targetContentHash"] = registration["targetContentHash"]
        output["sourceBindingProjection"] = projection
    return output


FAMILY_ADAPTERS = {
    # The registration's binding adapter is authoritative for HOW a target
    # resolves. A family leg may only resolve targets whose registered
    # adapter belongs to it (or that predate bindings entirely); most
    # notably, a generic-url registration (the prospect miner's binding)
    # must never be resolved by a series-stem family that happens to share
    # the series name — the 2026-07-25 new-home-sales collision, where a
    # 2026-07-10 generic-url registration met a newly added ALFRED stem.
    "alfred": {"alfred-fred"},
    "bea_release": {"bea-release", "bea-ita-itable"},
    "bls_api": {"bls-api"},
    "census_spm": {"census-spm-annual-report"},
    "eia_dnav": {"eia-dnav-xls"},
    "fsa_crp": {"fsa-crp-monthly-summary"},
    "irs_soi_pub1304": {"irs-soi-pub1304"},
    "qcew": {"bls-qcew"},
    "sba_pdf": {SBA_BINDING_ADAPTER},
    "ssa_official": {"ssa-official-page"},
    "usaspending": {"usaspending-api"},
    "va_mmwr": {"va-mmwr-workbook"},
}


def binding_adapter_mismatch(
    kind: str, registration: dict[str, Any] | None
) -> str | None:
    """The registered adapter name if this family must not resolve it."""

    if not registration:
        return None
    binding = (registration.get("contract") or {}).get("sourceBinding") or {}
    adapter = binding.get("adapter")
    if not adapter:
        return None
    allowed = FAMILY_ADAPTERS.get(kind)
    if allowed is None:
        return None
    return None if adapter in allowed else str(adapter)


def resolution_run_dir(retrieved_at: str) -> pathlib.Path:
    stamp = retrieved_at.lower().replace(":", "-")
    return (
        ROOT
        / "records"
        / "resolutions"
        / retrieved_at[:10]
        / f"{stamp}-resolve-pending"
    )


def finalize_resolution_manifest(
    run_dir: pathlib.Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    """Seal the exact resolver-response inventory and verify it immediately."""

    created_at = str(manifest["retrievedAt"])
    repository = ROOT.resolve()
    refs: list[dict[str, Any]] = []
    rooted: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for fact in manifest["facts"]:
        archive = fact["responseArchive"]
        path = repository / archive["path"]
        relative = path.resolve().relative_to(run_dir.resolve()).as_posix()
        ref = {
            "artifactType": "resolver_response",
            "path": path.resolve().relative_to(repository).as_posix(),
            "sha256": archive["gzipSha256"],
            "bytes": archive["gzipBytes"],
            "createdAt": created_at,
        }
        # Several facts can legitimately share one archived response (two
        # dataPointId dialects of the same series resolve from the same
        # vintage bytes); the inventory lists each archive exactly once.
        if ref["path"] in seen_paths:
            continue
        seen_paths.add(ref["path"])
        refs.append(ref)
        rooted.append({**ref, "path": relative})
    manifest.update(
        {
            "custodyInventoryVersion": 2,
            "runMode": "resolver",
            "ok": True,
            "manifestHashSemantics": (
                "canonical-json-v1; exclude artifacts where "
                "artifactType=manifest and exclude custodyRootSha256"
            ),
            "artifacts": refs,
        }
    )
    self_payload = copy.deepcopy(manifest)
    self_payload.pop("custodyRootSha256", None)
    self_bytes = canonical_bytes(self_payload)
    manifest_ref = {
        "artifactType": "manifest",
        "path": (run_dir / "manifest.json")
        .resolve()
        .relative_to(repository)
        .as_posix(),
        "sha256": hashlib.sha256(self_bytes).hexdigest(),
        "bytes": len(self_bytes),
        "createdAt": created_at,
        "hashMode": manifest["manifestHashSemantics"],
    }
    manifest["artifacts"] = [*refs, manifest_ref]
    custody = {
        "schemaVersion": "thesis_custody_root_v1",
        "custodyInventoryVersion": 2,
        "runMode": "resolver",
        "hashAlgorithm": "sha256",
        "canonicalJson": (
            "UTF-16 code-unit key order; ECMAScript JSON number/string encoding"
        ),
        "artifacts": rooted,
        "manifestWithoutCustodyRoot": {
            "path": "manifest.json",
            "excludedField": "custodyRootSha256",
            "canonicalJsonSha256": canonical_sha256(manifest),
        },
    }
    (run_dir / "custody_root.json").write_text(json.dumps(custody, indent=2) + "\n")
    manifest["custodyRootSha256"] = canonical_sha256(custody)
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    verify_run(run_dir)
    return manifest


def main() -> int:
    # Remove the secret before any network client or subprocess can inherit it.
    # The value remains only as an in-memory string until proposal signing.
    producer_signing_key = os.environ.pop(PRODUCER_SIGNING_KEY_ENV, None)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ledger-repo", default="PolicyEngine/chronicle")
    parser.add_argument("--ledger-branch", default="codex/thesis-ledger-facts")
    parser.add_argument("--ledger-path", default="ledger/official_observations.jsonl")
    args = parser.parse_args()

    log = load_thesis_log(LOG_URL)
    todo = pending_claims_refs(log)
    adapter_todo = pending_adapter_refs(log)
    if not todo and not adapter_todo:
        print("no pending adapter-covered cells")
        return 0

    content, sha, ledger_repo_sha = ledger_state(
        args.ledger_repo, args.ledger_branch, args.ledger_path
    )
    existing_ids = {
        json.loads(line)["source_record_id"]
        for line in content.splitlines()
        if line.strip()
    }

    fetched_rows: list[tuple[dict[str, Any], str, str, bytes, str, str]] = []
    today = dt.date.today()
    for ref, week, kind, source_vintage in todo:
        if ref in existing_ids:
            print(f"  already recorded: {ref}")
            continue
        release_day = dt.date.fromisoformat(source_vintage)
        if release_day > today:
            print(f"  release {release_day} not reached: {ref}")
            continue
        series_id = "ICSA" if kind == "initial" else "CCSA"
        value, raw, _source_url, retrieved_at = fred_advance_value(
            series_id, week, release_day.isoformat()
        )
        if value is None or raw is None:
            print(f"  not yet published: {ref}")
            continue
        row = claims_fact(ref, week, value, kind, release_day)
        fetched_rows.append(
            (row, series_id, release_day.isoformat(), raw, retrieved_at, "csv")
        )
        print(f"  resolve {ref} -> {row['value']} {row['measure']['unit']}")

    # Generic adapters: official BEA current releases, ALFRED vintage series,
    # BLS API series, A-19 snapshot rows, international native sources, and
    # witnessed SBA PDF custody. Shared official responses are cached so
    # multiple cells from one release archive the same bytes.
    alfred_cache: dict[tuple[str, str], tuple[dict, bytes | None, str, str]] = {}
    bea_release_page_cache: dict[str, tuple[bytes | None, str, str]] = {}
    bea_itable_cache: dict[bytes, tuple[bytes | None, str, dict[str, Any], str]] = {}
    usaspending_cache: dict[
        tuple[str, bytes | None], tuple[Any, bytes | None, str]
    ] = {}
    usaspending_contracts: dict[str, dict[str, Any]] | None = None
    bls_cache: dict[tuple[str, int, int], tuple[dict, bytes | None, str, str]] = {}
    fsa_crp_cache: dict[
        str,
        tuple[float | None, bytes | None, str, str, str | None],
    ] = {}
    census_spm_cache: dict[
        tuple[str, bool],
        tuple[float | None, bytes | None, str, str, str | None],
    ] = {}
    irs_soi_cache: dict[
        tuple[str, str],
        tuple[float | None, bytes | None, str, str, str | None],
    ] = {}
    # Missing-parser (or similar) environment failures must fail the run
    # loudly instead of deferring forever behind green exits.
    environment_failures: list[str] = []
    qcew_cache: dict[
        tuple[str, str, str],
        tuple[float | None, bytes | None, str, str, str | None],
    ] = {}
    eia_dnav_cache: dict[
        tuple[str, str],
        tuple[float | None, bytes | None, str, str, str | None],
    ] = {}
    qcew_contracts: dict[str, dict[str, Any]] | None = None
    a19_cache: dict[str, tuple[dict[str, float], bytes | None, str, str]] = {}
    intl_cache: dict[Any, tuple] = {}
    # International requests are checked against the immutable registered
    # contract before any network call. Existing registrations whose source
    # templates predate a native adapter fail closed and require a future
    # registration rather than silently changing source semantics.
    target_contracts = registration_contracts()
    # CMS provider-data: one metastore read per dataset item and one CSV
    # download per distribution URL, shared across cells on the same file.
    cms_metastore_cache: dict[str, tuple[str, str, str] | None] = {}
    cms_csv_cache: dict[str, bytes | None] = {}
    # VA MMWR: one landing-page read per run; workbooks cached per URL so
    # anchors and targets that share a week download once.
    va_landing: tuple[bytes, str] | None = None
    va_landing_failed = False
    va_workbook_cache: dict[str, tuple[bytes, dict[str, str], str, str]] = {}
    # SSA official pages: one headless-browser capture per URL per run.
    ssa_capture_cache: dict[str, Any] = {}
    ssa_browser_unavailable: str | None = None
    sba_timeline_cache: Mapping[str, Any] | None = None
    sba_timeline_error: str | None = None
    sba_timeline_loaded = False
    loop_contracts = registration_contracts()
    for ref, kind, spec, period_type, period, source_vintage, forecast in adapter_todo:
        qcew_row: dict[str, Any] | None = None
        if ref in existing_ids:
            print(f"  already recorded: {ref}")
            continue
        release_day = dt.date.fromisoformat(source_vintage)
        registration = loop_contracts.get(ref)
        resolution_date_basis, basis_refusal = effective_resolution_date_basis(
            ref, registration, spec
        )
        if basis_refusal:
            print(
                f"  RESOLUTION-DATE BASIS MISMATCH (refusing): {ref} — {basis_refusal}"
            )
            continue
        contract = (registration or {}).get("contract") or {}
        source_binding = contract.get("sourceBinding") or {}
        is_registered_query_snapshot = (
            kind == "usaspending"
            and source_binding.get("releasePolicy") == "registered_query_snapshot"
        )
        # A resolve-by date is an outer bound, not a claimed release day. Its
        # family leg gates on the immutable expectedReleaseWindow instead.
        # A registered-query snapshot likewise uses resolutionDate as the
        # window's conservative end; its USAspending leg must be allowed to
        # capture the first snapshot from the registered window's start.
        # SSA editions are per-period pages: the edition's existence is the
        # release evidence and the cells' resolutionDate is a declared
        # outer by-date, so the family may capture as soon as the edition
        # is posted (a missing edition defers on HTTP 404).
        is_edition_page = (
            kind == "ssa_official" and spec.get("release_evidence") == "edition_page"
        )
        if (
            release_day > today
            and resolution_date_basis == DEFAULT_RESOLUTION_DATE_BASIS
            and not is_registered_query_snapshot
            and not is_edition_page
        ):
            print(f"  release {release_day} not reached: {ref}")
            continue
        unit = (forecast or {}).get("unit")
        if not adapter_unit_matches(spec, forecast):
            print(
                f"  UNIT MISMATCH (refusing): {ref} cell={unit!r} "
                f"adapter={spec['unit']!r}"
            )
            continue
        mismatched = binding_adapter_mismatch(kind, loop_contracts.get(ref))
        if kind == "qcew" and mismatched == spec.get("legacy_binding_adapter"):
            legacy_binding = ((registration or {}).get("contract") or {}).get(
                "sourceBinding"
            ) or {}
            if qcew_binding_matches_spec(legacy_binding, spec, period, release_day):
                mismatched = None
        if mismatched:
            print(
                f"  BINDING/ADAPTER MISMATCH (skipping, registered "
                f"adapter={mismatched!r} is not a {kind} family): {ref}"
            )
            continue
        irs_verified_anchors: dict[str, float] | None = None
        if kind == "irs_soi_pub1304":
            # Preserve the pre-generalization refusal order byte-for-byte:
            # authenticate the reviewed adapter and all seven binding keys
            # before a still-pending window can defer the target.
            irs_verified_anchors = irs_soi_pub1304_verified_anchors(spec)
            if irs_verified_anchors is None:
                print(
                    f"  IRS SOI ADAPTER UNVERIFIED (refusing): {ref} — "
                    "three live official-source anchors are required"
                )
                continue
            registered_contract = (registration or {}).get("contract") or {}
            binding = registered_contract.get("sourceBinding") or {}
            if not irs_soi_pub1304_binding_matches_spec(binding, spec):
                print(
                    "  BINDING/ADAPTER MISMATCH (refusing, full seven-key "
                    f"registry drift?): {ref}"
                )
                continue
        if kind == "sba_pdf":
            registered_contract = (registration or {}).get("contract") or {}
            binding = registered_contract.get("sourceBinding") or {}
            if not sba_pdf_binding_matches_spec(binding, spec):
                print(
                    "  BINDING/ADAPTER MISMATCH (refusing, full SBA PDF "
                    f"registry drift?): {ref}"
                )
                continue
        if kind == "eia_dnav":
            verified_anchors = eia_dnav_verified_anchors(spec)
            if verified_anchors is None:
                print(
                    f"  EIA DNAV ADAPTER UNVERIFIED (refusing): {ref} — "
                    "three live official-workbook anchors are required"
                )
                continue
            registered_contract = (registration or {}).get("contract") or {}
            binding = registered_contract.get("sourceBinding") or {}
            if not eia_dnav_binding_matches_spec(binding, spec):
                print(
                    "  BINDING/ADAPTER MISMATCH (refusing, full EIA DNav "
                    f"registry drift?): {ref}"
                )
                continue
        bounded_window = None
        if resolution_date_basis == "resolve-by-bound":
            contract = (registration or {}).get("contract") or {}
            binding = contract.get("sourceBinding") or {}
            bounded_window = binding.get("expectedReleaseWindow")
            # Every bounded target defers until its immutable window opens.
            # Once it closes, resolution requires release-time witnessed or
            # versioned custody; only explicitly reviewed family legs may
            # supply that stronger evidence.
            # Use the UTC decision day to preserve midnight boundary behavior.
            window_state, window_verdict = bounded_resolution_window_gate(
                ref,
                dt.date.fromisoformat(utc_now()[:10]),
                bounded_window,
            )
            # A closed bound normally proves that a mutable live fetch can no
            # longer establish the first print. SBA is the reviewed exception:
            # this leg never fetches live bytes and may resolve after the bound
            # only from versioned, externally witnessed custody.
            if window_verdict and not (kind == "sba_pdf" and window_state == "missed"):
                print(window_verdict)
                continue
        sba_resolution: SbaPdfResolution | None = None
        archive_vintage = release_day.isoformat()
        if kind == "sba_pdf":
            if not sba_timeline_loaded:
                try:
                    sba_timeline_cache = extract_timeline(ROOT / "records")
                except (OSError, TimelineError, ValueError) as exc:
                    sba_timeline_error = str(exc)
                sba_timeline_loaded = True
            if sba_timeline_error is not None:
                print(
                    f"  {SBA_CUSTODY_INVALID} witnessed record timeline does "
                    f"not verify: {sba_timeline_error}"
                )
                continue
            assert sba_timeline_cache is not None
            sba_resolution, refusal = resolve_sba_pdf_first_print(
                ROOT / "records",
                series=spec["series_id"],
                fiscal_year=int(period),
                timeline=sba_timeline_cache,
            )
            if refusal:
                if refusal.startswith(SBA_PARSER_REFUSAL):
                    environment_failures.append(f"{ref}: {refusal}")
                print(f"  {refusal}")
                continue
            assert sba_resolution is not None
            value = sba_resolution.value
            raw = sba_resolution.raw_bundle
            source_url = sba_resolution.source_url
            source_file = posixpath.basename(urlparse(source_url).path)
            series_id = SBA_ARCHIVE_SERIES_ID
            retrieved_at = utc_now()
            archive_vintage = str(sba_resolution.provenance["earliestWitnessedAt"])[:10]
            extension = "zip"
        elif kind == "intl":
            registration = target_contracts.get(ref)
            if registration:
                contract = registration["contract"]
                binding = contract.get("sourceBinding") or {}
                mismatches = intl_binding_mismatches(spec, binding)
                execution_spec = intl_execution_spec(registration, spec)
                if execution_spec is None:
                    print(
                        "  BINDING/ADAPTER MISMATCH (refusing, registry "
                        f"drift?): {ref} — {', '.join(mismatches)}"
                    )
                    continue
                release_window = binding.get("expectedReleaseWindow")
                if snapshot_window_state(release_day, release_window) != "open":
                    print(
                        "  FORECAST/REGISTERED RELEASE DATE MISMATCH "
                        f"(refusing): {ref} — forecast {release_day} is outside "
                        f"{release_window!r}"
                    )
                    continue
                window_state = snapshot_window_state(today, release_window)
                if window_state != "open":
                    print(
                        f"  FIRST-PRINT WINDOW {window_state.upper()} (refusing): {ref}"
                    )
                    continue
                spec = execution_spec
            else:
                window = spec.get("first_print_window_days")
                if window is not None and today > release_day + dt.timedelta(
                    days=window
                ):
                    print(
                        f"  FIRST-PRINT WINDOW ELAPSED (deferring, needs a "
                        f"pinned vintage): {ref} released {release_day}, "
                        f"window {window}d"
                    )
                    continue
            try:
                series, flags, raw, source_url, retrieved_at = intl_fetch(
                    spec, period, intl_cache
                )
            except LookupError as exc:
                print(f"  {exc}: {ref}")
                continue
            except Exception as exc:  # noqa: BLE001 - defer, don't crash run
                print(f"  fetch/parse failed (deferring): {ref} — {exc}")
                continue
            anchor_failures = intl_anchor_failures(spec, series)
            if anchor_failures:
                print(
                    f"  ANCHOR MISMATCH (refusing, wrong series/vintage?): "
                    f"{ref} — {'; '.join(anchor_failures)}"
                )
                continue
            if flash_vintage_missing(spec, flags, period):
                print(
                    f"  FLASH VINTAGE NO LONGER SERVED (deferring): {ref} — "
                    f"{period} carries no provisional flag, finals likely "
                    f"published"
                )
                continue
            value = intl_transformed_value(spec, series, period)
            series_id = spec["series_id"]
            source_file = spec["source_file"]
            extension = spec["extension"]
        elif kind == "bea_release":
            contract = (registration or {}).get("contract") or {}
            binding = contract.get("sourceBinding") or {}
            if not bea_release_binding_matches_spec(binding, spec):
                print(
                    "  BINDING/ADAPTER MISMATCH (refusing, full seven-key "
                    f"registry drift?): {ref}"
                )
                continue
            expected_window = {
                "start": release_day.isoformat(),
                "end": release_day.isoformat(),
            }
            if binding.get("expectedReleaseWindow") != expected_window:
                print(
                    "  FORECAST/REGISTERED RELEASE DATE MISMATCH "
                    f"(refusing): {ref} — forecast {release_day} is outside "
                    f"{binding.get('expectedReleaseWindow')!r}"
                )
                continue
            # BEA says current ITA links are superseded at the next release and
            # moves original data to its archive, so capture only on the
            # registered day:
            # https://www.bea.gov/news/2026/us-international-transactions-and-investment-position-1st-quarter-2026-and-annual-update
            bea_start_day = dt.date.fromisoformat(utc_now()[:10])
            if bea_start_day < release_day:
                print(f"  release {release_day} not reached: {ref}")
                continue
            if bea_start_day > release_day:
                print(
                    f"  FIRST-PRINT WINDOW MISSED (refusing): {ref} — "
                    f"registered release day was {release_day}"
                )
                continue
            is_ita = spec.get("variant") == "ita-itable"
            release_url = (
                bea_ita_release_url(period, release_day)
                if is_ita
                else bea_advance_release_url(period, release_day)
            )
            if release_url not in bea_release_page_cache:
                fetch_release = (
                    fetch_bea_ita_release_page if is_ita else fetch_bea_release_page
                )
                bea_release_page_cache[release_url] = fetch_release(period, release_day)
            release_raw, fetched_release_url, release_retrieved_at = (
                bea_release_page_cache[release_url]
            )
            if release_raw is None:
                print(f"  BEA RELEASE fetch failed (deferring): {ref}")
                continue
            if is_ita and fetched_release_url != release_url:
                print(
                    "  BEA ITA RELEASE PAGE REFUSAL (refusing): "
                    f"{ref} — expected exact URL {release_url!r}, got "
                    f"{fetched_release_url!r}"
                )
                continue
            release_refusal = (
                bea_ita_release_page_refusal(release_raw, period, release_day)
                if is_ita
                else bea_release_page_refusal(release_raw, period, release_day)
            )
            if release_refusal:
                print(
                    f"  BEA RELEASE PAGE REFUSAL (refusing): {ref} — {release_refusal}"
                )
                continue
            if is_ita:
                timing_refusal = bea_ita_capture_timing_refusal(
                    {"release page": release_retrieved_at}, release_day
                )
                if timing_refusal:
                    print(
                        "  BEA ITA RELEASE TIMING REFUSAL (refusing): "
                        f"{ref} — {timing_refusal}"
                    )
                    continue

            catalog_raw: bytes | None = None
            catalog_url = ""
            catalog_body: dict[str, Any] = {}
            catalog_retrieved_at = ""
            year_key: str | None = None
            if is_ita:
                catalog_body = bea_ita_prompt_catalog_request_body(spec)
                catalog_cache_key = canonical_bytes(catalog_body)
                if catalog_cache_key not in bea_itable_cache:
                    bea_itable_cache[catalog_cache_key] = fetch_bea_ita_prompt_catalog(
                        spec
                    )
                (
                    catalog_raw,
                    catalog_url,
                    fetched_catalog_body,
                    catalog_retrieved_at,
                ) = bea_itable_cache[catalog_cache_key]
                if catalog_raw is None:
                    print(f"  BEA ITA PROMPT CATALOG fetch failed (deferring): {ref}")
                    continue
                if catalog_url != BEA_ITABLE_DATA_URL:
                    print(
                        "  BEA ITA PROMPT CATALOG REFUSAL (refusing): "
                        f"{ref} — unexpected final URL {catalog_url!r}"
                    )
                    continue
                if fetched_catalog_body != catalog_body:
                    print(
                        "  BEA ITA PROMPT CATALOG REFUSAL (refusing): "
                        f"{ref} — request body drift"
                    )
                    continue
                year_key, catalog_refusal = bea_ita_prompt_catalog_selection(
                    catalog_raw, spec, period
                )
                if catalog_refusal:
                    print(
                        "  BEA ITA PROMPT CATALOG REFUSAL (refusing): "
                        f"{ref} — {catalog_refusal}"
                    )
                    continue
                assert year_key is not None

            table_body = (
                bea_ita_itable_request_body(spec, period, year_key)
                if is_ita and year_key is not None
                else bea_itable_request_body(spec, period)
            )
            table_cache_key = canonical_bytes(table_body)
            if table_cache_key not in bea_itable_cache:
                bea_itable_cache[table_cache_key] = (
                    fetch_bea_ita_itable_table(spec, period, year_key)
                    if is_ita and year_key is not None
                    else fetch_bea_itable_table(spec, period)
                )
            table_raw, table_url, fetched_table_body, table_retrieved_at = (
                bea_itable_cache[table_cache_key]
            )
            if table_raw is None:
                print(f"  BEA iTABLE fetch failed (deferring): {ref}")
                continue
            if is_ita and table_url != BEA_ITABLE_DATA_URL:
                print(
                    f"  BEA ITA iTABLE REFUSAL (refusing): {ref} — "
                    f"unexpected final URL {table_url!r}"
                )
                continue
            if is_ita and fetched_table_body != table_body:
                print(
                    f"  BEA ITA iTABLE REFUSAL (refusing): {ref} — request body drift"
                )
                continue
            if is_ita:
                timing_refusal = bea_ita_capture_timing_refusal(
                    {
                        "prompt catalog": catalog_retrieved_at,
                        "selected table": table_retrieved_at,
                    },
                    release_day,
                )
                if timing_refusal:
                    print(
                        "  BEA ITA iTABLE TIMING REFUSAL (refusing): "
                        f"{ref} — {timing_refusal}"
                    )
                    continue
            effective_capture_day = max(
                release_retrieved_at[:10],
                catalog_retrieved_at[:10] if is_ita else release_retrieved_at[:10],
                table_retrieved_at[:10],
                utc_now()[:10],
            )
            if effective_capture_day > release_day.isoformat():
                print(
                    f"  FIRST-PRINT WINDOW MISSED (refusing): {ref} — "
                    f"capture completed {effective_capture_day} after "
                    f"registered release day {release_day}"
                )
                continue
            value, table_refusal = (
                bea_ita_itable_value(
                    table_raw,
                    spec,
                    period,
                    release_day,
                    expected_year_key=year_key,
                )
                if is_ita
                else bea_itable_value(table_raw, spec, period, release_day)
            )
            if table_refusal:
                print(f"  BEA iTABLE PARSE REFUSAL (refusing): {ref} — {table_refusal}")
                continue
            assert value is not None
            if is_ita:
                assert catalog_raw is not None
                raw = bea_ita_release_snapshot_envelope(
                    spec=spec,
                    period=period,
                    value=value,
                    release_url=fetched_release_url,
                    release_raw=release_raw,
                    release_retrieved_at=release_retrieved_at,
                    catalog_url=catalog_url,
                    catalog_body=catalog_body,
                    catalog_raw=catalog_raw,
                    catalog_retrieved_at=catalog_retrieved_at,
                    table_url=table_url,
                    table_body=fetched_table_body,
                    table_raw=table_raw,
                    table_retrieved_at=table_retrieved_at,
                )
            else:
                raw = bea_release_snapshot_envelope(
                    spec=spec,
                    period=period,
                    value=value,
                    release_url=fetched_release_url,
                    release_raw=release_raw,
                    release_retrieved_at=release_retrieved_at,
                    table_url=table_url,
                    table_body=fetched_table_body,
                    table_raw=table_raw,
                    table_retrieved_at=table_retrieved_at,
                )
            source_url = fetched_release_url
            source_file = (
                "ITA/IIP release HTML + ITA Table 5.1 prompt and table JSON"
                if is_ita
                else "GDP advance release HTML + NIPA Table 5.3.5 iTable JSON"
            )
            series_id = str(spec["series_id"]).replace(":", "-")
            retrieved_at = max(
                release_retrieved_at,
                catalog_retrieved_at if is_ita else release_retrieved_at,
                table_retrieved_at,
            )
            extension = "json"
        elif kind == "alfred":
            cache_key = (spec["fred"], release_day.isoformat())
            if cache_key not in alfred_cache:
                alfred_cache[cache_key] = fred_vintage_series(*cache_key)
            rows, raw, source_url, retrieved_at = alfred_cache[cache_key]
            value = apply_transform(rows, spec, period_type, period)
            series_id = spec["fred"]
            source_file = "alfredgraph.csv"
            extension = "csv"
        elif kind == "bls_api":
            series_id = spec["series_id"]
            bls_key = (
                series_id,
                spec["anchor_start_year"],
                int(period[:4]) + spec.get("fetch_end_year_offset", 0),
            )
            if bls_key not in bls_cache:
                bls_cache[bls_key] = bls_series_rows(*bls_key)
            rows, raw, source_url, retrieved_at = bls_cache[bls_key]
            if raw is None:
                print(f"  BLS API fetch failed: {ref}")
                continue
            if period_type == "year":
                mismatches = bls_annual_anchor_mismatches(rows, spec["anchors"])
            else:
                mismatches = bls_anchor_mismatches(rows, spec["anchors"])
            if mismatches:
                print(
                    f"  ANCHOR MISMATCH (refusing, wrong series?): {ref} "
                    + "; ".join(mismatches)
                )
                continue
            if period_type == "year":
                value, refusal = bls_annual_first_print(rows, period)
            else:
                value, refusal = bls_first_print(
                    rows,
                    period,
                    spec.get("first_print_gate", "latest_preliminary"),
                )
            if refusal:
                print(f"  FIRST-PRINT WINDOW MISSED (refusing): {ref} — {refusal}")
                continue
            if value is not None and ("scale" in spec or "round" in spec):
                # LAUS serves persons for a catalog in thousands; rounding
                # follows the cell's resolver (one decimal thousand).
                value = round(value * spec.get("scale", 1), spec.get("round", 4)) + 0.0
            # The API has no vintage archive, so the capture day IS the
            # source vintage; the latest+preliminary gate above bounds it
            # inside the first-print window.
            release_day = dt.date.fromisoformat(retrieved_at[:10])
            source_file = "timeseries/data (BLS Public Data API v2)"
            extension = "json"
        elif kind == "fsa_crp":
            verified_anchors = fsa_crp_verified_anchors(spec)
            if verified_anchors is None:
                print(
                    f"  FSA CRP ADAPTER UNVERIFIED (refusing): {ref} — "
                    "three live official-source anchors are required"
                )
                continue
            registration = loop_contracts.get(ref) or {}
            binding = (registration.get("contract") or {}).get("sourceBinding") or {}
            if not fsa_crp_binding_matches_spec(binding, spec):
                print(
                    "  BINDING/ADAPTER MISMATCH (refusing, full seven-key "
                    f"registry drift?): {ref}"
                )
                continue
            anchor_values: dict[str, float | None] = {}
            anchor_fetch_failed = False
            for anchor_period in verified_anchors:
                if anchor_period not in fsa_crp_cache:
                    fsa_crp_cache[anchor_period] = fsa_crp_fetch_period(
                        spec, anchor_period
                    )
                anchor_value, anchor_raw, _, _, anchor_refusal = fsa_crp_cache[
                    anchor_period
                ]
                if anchor_raw is None or anchor_refusal:
                    anchor_fetch_failed = True
                anchor_values[anchor_period] = anchor_value
            if anchor_fetch_failed:
                print(f"  FSA CRP anchor fetch/parse failed (deferring): {ref}")
                continue
            mismatches = fsa_crp_anchor_mismatches(anchor_values, verified_anchors)
            if mismatches:
                print(
                    f"  ANCHOR MISMATCH (refusing, wrong FSA CRP row?): {ref} — "
                    + "; ".join(mismatches)
                )
                continue
            if period not in fsa_crp_cache:
                fsa_crp_cache[period] = fsa_crp_fetch_period(spec, period)
            value, raw, fetched_url, retrieved_at, refusal = fsa_crp_cache[period]
            if refusal:
                print(f"  FSA CRP PARSE REFUSAL (refusing): {ref} — {refusal}")
                continue
            if raw is not None and resolution_date_basis == "resolve-by-bound":
                release_day = dt.date.fromisoformat(retrieved_at[:10])
                effective_capture_date = max(retrieved_at[:10], utc_now()[:10])
                _capture_state, capture_verdict = bounded_resolution_window_gate(
                    ref,
                    dt.date.fromisoformat(effective_capture_date),
                    bounded_window,
                )
                if capture_verdict:
                    print(capture_verdict)
                    continue
            source_url = spec["source_url"]
            source_file = fetched_url
            series_id = spec["series_id"]
            extension = "pdf"
        elif kind == "census_spm":
            verified_anchors = census_spm_verified_anchors(spec)
            if verified_anchors is None:
                # Deliberately before any Census request: the revised 2019--24
                # prints do not exist yet, and legacy annual reports cannot
                # authenticate the corrected-methodology target.
                print(
                    f"  CENSUS SPM ADAPTER UNVERIFIED (refusing): {ref} — "
                    "all six 2019-2024 official-source anchors, with "
                    "transition-discriminating 2019 and 2020 values, are "
                    "required"
                )
                continue
            registration = registration or {}
            binding = (registration.get("contract") or {}).get("sourceBinding") or {}
            if not census_spm_binding_matches_spec(binding, spec):
                print(
                    "  BINDING/ADAPTER MISMATCH (refusing, full seven-key "
                    f"registry drift?): {ref}"
                )
                continue
            cache_key = (period, True)
            if cache_key not in census_spm_cache:
                census_spm_cache[cache_key] = census_spm_fetch_year(
                    spec, period, require_latest=True
                )
            value, raw, fetched_url, retrieved_at, refusal = census_spm_cache[cache_key]
            if refusal:
                print(f"  CENSUS SPM PARSE REFUSAL (refusing): {ref} — {refusal}")
                continue
            if raw is not None:
                grid, grid_refusal = census_spm_xlsx_grid(raw, spec)
                if grid_refusal or grid is None:
                    print(
                        f"  CENSUS SPM PARSE REFUSAL (refusing): {ref} — {grid_refusal}"
                    )
                    continue
                anchor_values = {
                    anchor_year: census_spm_rate_from_grid(
                        grid,
                        anchor_year,
                        spec,
                        report_year=period,
                    )[0]
                    for anchor_year in verified_anchors
                }
                mismatches = census_spm_anchor_mismatches(
                    anchor_values, verified_anchors
                )
                if mismatches:
                    print(
                        "  ANCHOR MISMATCH (refusing, wrong revised SPM "
                        f"table/methodology?): {ref} — " + "; ".join(mismatches)
                    )
                    continue
                release_day = dt.date.fromisoformat(retrieved_at[:10])
                window = bounded_window
                effective_capture_date = max(retrieved_at[:10], utc_now()[:10])
                _capture_state, capture_verdict = bounded_resolution_window_gate(
                    ref,
                    dt.date.fromisoformat(effective_capture_date),
                    window,
                )
                if capture_verdict:
                    print(capture_verdict)
                    continue
            source_url = spec["source_url"]
            source_file = fetched_url
            series_id = spec["series_id"]
            extension = "xlsx"
        elif kind == "irs_soi_pub1304":
            verified_anchors = irs_verified_anchors or {}
            # The generalized basis gate above already deferred until the
            # registered window opened and refused runs that began after it.
            # Recheck after the fetch so a request that straddles the boundary
            # cannot publish post-window bytes as the first print.
            window = bounded_window
            anchor_counts: dict[str, float | None] = {}
            anchor_fetch_failed = False
            anchor_env_failure = None
            for anchor_year in verified_anchors:
                cache_key = (str(spec["series_id"]), anchor_year)
                if cache_key not in irs_soi_cache:
                    irs_soi_cache[cache_key] = irs_soi_pub1304_fetch_year(
                        spec, anchor_year
                    )
                anchor_value, anchor_raw, _, _, anchor_refusal = irs_soi_cache[
                    cache_key
                ]
                if anchor_raw is None or anchor_refusal:
                    anchor_fetch_failed = True
                if anchor_refusal and "xlrd is unavailable" in anchor_refusal:
                    anchor_env_failure = anchor_refusal
                anchor_counts[anchor_year] = anchor_value
            if anchor_env_failure:
                # A missing parser is an environment failure, not a data
                # state: deferring quietly would leave every IRS target
                # pending forever behind a green run.
                print(
                    f"  IRS SOI ENVIRONMENT FAILURE (fatal): {ref} — "
                    f"{anchor_env_failure}"
                )
                environment_failures.append(f"{ref}: {anchor_env_failure}")
                continue
            if anchor_fetch_failed:
                print(f"  IRS SOI anchor fetch/parse failed (deferring): {ref}")
                continue
            mismatches = irs_soi_pub1304_anchor_mismatches(
                anchor_counts, verified_anchors
            )
            if mismatches:
                print(
                    "  ANCHOR MISMATCH (refusing, wrong Table 3.3 "
                    f"row/column?): {ref} — " + "; ".join(mismatches)
                )
                continue
            cache_key = (str(spec["series_id"]), period)
            if cache_key not in irs_soi_cache:
                irs_soi_cache[cache_key] = irs_soi_pub1304_fetch_year(spec, period)
            raw_value, raw, fetched_url, retrieved_at, refusal = irs_soi_cache[
                cache_key
            ]
            if refusal and "xlrd is unavailable" in refusal:
                print(f"  IRS SOI ENVIRONMENT FAILURE (fatal): {ref} — {refusal}")
                environment_failures.append(f"{ref}: {refusal}")
                continue
            if refusal:
                print(f"  IRS SOI PARSE REFUSAL (refusing): {ref} — {refusal}")
                continue
            # The observation is exactly the registered per-series transform
            # of the published integer, with no additional rounding. Any
            # display convention lives in the forecast's resolution rule.
            value = irs_soi_pub1304_apply_transform(spec, raw_value)
            # The workbook URL has no vintage archive, so the capture day is
            # the source vintage. Judge the window on the retrieval stamp OR
            # the present decision moment, whichever is later: the stamp
            # precedes the response read, and a request straddling midnight
            # past the window end must fail closed.
            if raw is not None and resolution_date_basis == "resolve-by-bound":
                release_day = dt.date.fromisoformat(retrieved_at[:10])
                # The effective capture date is the later of the request
                # stamp (taken before the response read) and the decision
                # moment, so a straddle fails against a coherent cutoff date.
                effective_capture_date = max(retrieved_at[:10], utc_now()[:10])
                _capture_state, capture_verdict = bounded_resolution_window_gate(
                    ref,
                    dt.date.fromisoformat(effective_capture_date),
                    window,
                )
                if capture_verdict:
                    print(capture_verdict)
                    continue
            source_url = spec["source_url"]
            source_file = fetched_url
            series_id = spec["series_id"]
            extension = "xls"
        elif kind == "qcew":
            if not qcew_adapter_verified(spec):
                print(
                    f"  QCEW ADAPTER UNVERIFIED (refusing): {ref} — "
                    "three live official-source anchors are required"
                )
                continue
            # QCEW slices are mutable current files. The registered release
            # window is one day, so a later run must not relabel a revision as
            # the first print.
            if today > release_day:
                print(
                    f"  FIRST-PRINT WINDOW MISSED (refusing): {ref} — "
                    f"registered release day was {release_day}"
                )
                continue
            if qcew_contracts is None:
                qcew_contracts = registration_contracts()
            registration = qcew_contracts.get(ref) or {}
            contract = registration.get("contract") or {}
            binding = contract.get("sourceBinding") or {}
            if not qcew_registration_matches_spec(binding, spec, period, release_day):
                print(f"  BINDING/ADAPTER MISMATCH (refusing, registry drift?): {ref}")
                continue
            anchor_values: dict[str, float | None] = {}
            anchor_fetch_failed = False
            for anchor_period in spec["anchors"]:
                cache_key = qcew_cache_key(spec, anchor_period)
                if cache_key not in qcew_cache:
                    qcew_cache[cache_key] = qcew_fetch_period(spec, anchor_period)
                anchor_value, anchor_raw, _, _, anchor_refusal = qcew_cache[cache_key]
                if anchor_raw is None or anchor_refusal:
                    anchor_fetch_failed = True
                anchor_values[anchor_period] = anchor_value
            if anchor_fetch_failed:
                print(f"  QCEW anchor fetch/parse failed (deferring): {ref}")
                continue
            mismatches = qcew_anchor_mismatches(anchor_values, spec["anchors"])
            if mismatches:
                print(
                    f"  ANCHOR MISMATCH (refusing, wrong QCEW row?): {ref} — "
                    + "; ".join(mismatches)
                )
                continue
            cache_key = qcew_cache_key(spec, period)
            if cache_key not in qcew_cache:
                qcew_cache[cache_key] = qcew_fetch_period(spec, period)
            value, raw, fetched_url, retrieved_at, refusal = qcew_cache[cache_key]
            if refusal:
                print(f"  QCEW PARSE REFUSAL (refusing): {ref} — {refusal}")
                continue
            window_refusal = qcew_postfetch_window_refusal(retrieved_at, release_day)
            if window_refusal:
                print(
                    f"  FIRST-PRINT WINDOW MISSED (refusing): {ref} — {window_refusal}"
                )
                continue
            qcew_row, series_id = qcew_resolution_fact(
                ref,
                spec,
                period_type,
                period,
                value,
                release_day,
                binding,
                fetched_url,
            )
            extension = "csv"
        elif kind == "eia_dnav":
            cache_key = (str(spec["series_id"]), period)
            if cache_key not in eia_dnav_cache:
                eia_dnav_cache[cache_key] = eia_dnav_fetch_year(spec, period)
            value, raw, fetched_url, retrieved_at, refusal = eia_dnav_cache[cache_key]
            if refusal and "xlrd is unavailable" in refusal:
                print(f"  EIA DNAV ENVIRONMENT FAILURE (fatal): {ref} — {refusal}")
                environment_failures.append(f"{ref}: {refusal}")
                continue
            if refusal:
                print(f"  EIA DNAV PARSE REFUSAL (refusing): {ref} — {refusal}")
                continue
            if raw is not None:
                # Re-parse the workbook stored inside the envelope so the
                # anchor gate covers the exact bytes about to be archived.
                try:
                    envelope = json.loads(raw)
                    workbook_raw = base64.b64decode(
                        envelope["workbook"]["bodyBase64"], validate=True
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    print(f"  EIA DNAV ENVELOPE REFUSAL (refusing): {ref} — {exc}")
                    continue
                values, identity_refusal = eia_dnav_values_from_xls(workbook_raw, spec)
                if identity_refusal or values is None:
                    print(
                        f"  EIA DNAV PARSE REFUSAL (refusing): {ref} — "
                        f"{identity_refusal}"
                    )
                    continue
                mismatches = eia_dnav_anchor_mismatches(values, verified_anchors)
                if mismatches:
                    print(
                        f"  ANCHOR MISMATCH (refusing, wrong EIA series?): {ref} — "
                        + "; ".join(mismatches)
                    )
                    continue
                effective_capture_date = max(retrieved_at[:10], utc_now()[:10])
                _capture_state, capture_verdict = bounded_resolution_window_gate(
                    ref,
                    dt.date.fromisoformat(effective_capture_date),
                    bounded_window,
                )
                if capture_verdict:
                    print(capture_verdict)
                    continue
                release_day = dt.date.fromisoformat(retrieved_at[:10])
            source_url = spec["source_url"]
            source_file = fetched_url
            series_id = spec["series_id"]
            extension = "json"
        elif kind == "va_mmwr":
            report_date = dt.date.fromisoformat(period)
            if va_landing is None and not va_landing_failed:
                try:
                    landing_raw, _headers, landing_retrieved_at, _final = (
                        va_mmwr_http_get(va_mmwr.LANDING_URL)
                    )
                    va_landing = (landing_raw, landing_retrieved_at)
                except Exception as exc:  # noqa: BLE001 - defer, don't crash
                    print(
                        "  VA MMWR landing page fetch failed (deferring): "
                        f"{ref} — {exc}"
                    )
                    va_landing_failed = True
            if va_landing is None:
                continue
            landing_raw, landing_retrieved_at = va_landing
            anchor_captures: list[VaMmwrCapture] = []
            anchor_problem: str | None = None
            for anchor_date, expected in sorted(spec["anchors"].items()):
                try:
                    anchor_capture, anchor_refusal = va_mmwr_capture_report(
                        landing_raw,
                        dt.date.fromisoformat(anchor_date),
                        va_workbook_cache,
                    )
                except Exception as exc:  # noqa: BLE001 - defer, don't crash
                    anchor_problem = f"anchor {anchor_date} fetch failed: {exc}"
                    break
                if anchor_refusal or anchor_capture is None:
                    anchor_problem = f"anchor {anchor_date}: {anchor_refusal}"
                    break
                if anchor_capture.reading.pending != expected:
                    anchor_problem = (
                        f"anchor {anchor_date}={anchor_capture.reading.pending} "
                        f"(recorded {expected})"
                    )
                    break
                anchor_captures.append(anchor_capture)
            if anchor_problem:
                print(
                    f"  ANCHOR MISMATCH (refusing, wrong VA workbook cell?): {ref} — "
                    f"{anchor_problem}"
                )
                continue
            try:
                target_capture, target_refusal = va_mmwr_capture_report(
                    landing_raw, report_date, va_workbook_cache
                )
            except Exception as exc:  # noqa: BLE001 - defer, don't crash
                print(f"  VA MMWR workbook fetch failed (deferring): {ref} — {exc}")
                continue
            if target_refusal or target_capture is None:
                if (
                    target_refusal
                    and "expected exactly one report link" in target_refusal
                ):
                    print(f"  not yet published (deferring): {ref} — {target_refusal}")
                elif target_refusal and "re-post" in target_refusal:
                    print(
                        "  FIRST-PRINT WINDOW MISSED (refusing): "
                        f"{ref} — {target_refusal}"
                    )
                else:
                    print(
                        f"  VA MMWR PARSE REFUSAL (refusing): {ref} — {target_refusal}"
                    )
                continue
            low, high = spec["sanity_range"]
            if not low <= target_capture.reading.pending <= high:
                print(
                    f"  VA MMWR PARSE REFUSAL (refusing): {ref} — pending "
                    f"{target_capture.reading.pending} outside sanity range "
                    f"[{low}, {high}]"
                )
                continue
            value = (
                round(target_capture.reading.pending * spec["scale"], spec["round"])
                + 0.0
            )
            raw = va_mmwr_capture_envelope(
                spec=spec,
                landing_raw=landing_raw,
                landing_retrieved_at=landing_retrieved_at,
                target=target_capture,
                anchors=anchor_captures,
                value=value,
            )
            # The workbook's Last-Modified (UTC day) is the posting vintage
            # the gate just authenticated as first; the capture stamp is the
            # fetch time.
            release_day = target_capture.last_modified.astimezone(
                dt.timezone.utc
            ).date()
            source_url = target_capture.workbook_url
            source_file = posixpath.basename(target_capture.href)
            series_id = spec["series_id"]
            retrieved_at = target_capture.retrieved_at
            extension = "json"
            period_type, period = "week_ending", target_capture.file_date.isoformat()
            spec = {
                **spec,
                "evidence_notes": spec["evidence_notes"].replace(
                    "{period}", report_date.isoformat()
                ),
            }
        elif kind == "ssa_official":
            if ssa_browser_unavailable:
                print(
                    "  SSA BROWSER ENVIRONMENT FAILURE (fatal): "
                    f"{ref} — {ssa_browser_unavailable}"
                )
                environment_failures.append(f"{ref}: {ssa_browser_unavailable}")
                continue
            try:
                from official_browser_fetch import (
                    BrowserFetchError,
                    BrowserFetchUnavailableError,
                    browser_fetch,
                )
            except ImportError as exc:  # pragma: no cover - module ships with the repo
                ssa_browser_unavailable = f"official_browser_fetch import failed: {exc}"
                print(
                    "  SSA BROWSER ENVIRONMENT FAILURE (fatal): "
                    f"{ref} — {ssa_browser_unavailable}"
                )
                environment_failures.append(f"{ref}: {ssa_browser_unavailable}")
                continue

            def ssa_capture(url: str) -> tuple[Any | None, str | None]:
                """(capture, refusal) from the per-run browser cache."""
                nonlocal ssa_browser_unavailable
                if url in ssa_capture_cache:
                    return ssa_capture_cache[url], None
                try:
                    capture = browser_fetch(url, allowed_hosts=SSA_ALLOWED_HOSTS)
                except BrowserFetchUnavailableError as exc:
                    ssa_browser_unavailable = str(exc)
                    return None, f"environment: {exc}"
                except BrowserFetchError as exc:
                    return None, f"fetch failed: {exc}"
                ssa_capture_cache[url] = capture
                return capture, None

            if spec["reader"] == "oho_workload_xml":
                # Rolling URL: authenticate the reporting period from the
                # file itself, falling back to the earliest Wayback capture
                # that carries the target period once the live file rolled.
                url = ssa_period_url(spec, period)
                capture, capture_refusal = ssa_capture(url)
                if capture is None:
                    if capture_refusal and capture_refusal.startswith("environment"):
                        print(
                            "  SSA BROWSER ENVIRONMENT FAILURE (fatal): "
                            f"{ref} — {capture_refusal}"
                        )
                        environment_failures.append(f"{ref}: {capture_refusal}")
                    else:
                        print(
                            "  SSA OHO fetch failed (deferring): "
                            f"{ref} — {capture_refusal}"
                        )
                    continue
                try:
                    workload = ssa_official_pages.oho_workload_file(capture.body)
                except ssa_official_pages.SsaPageError as exc:
                    print(f"  SSA OHO PARSE REFUSAL (refusing): {ref} — {exc}")
                    continue
                period_end = workload.reporting_period_end
                witnessed: dict[str, Any] = {"status": "live", "captures": []}
                if period_end.strftime("%Y-%m") != period:
                    if period_end.strftime("%Y-%m") < period:
                        print(
                            f"  not yet published (deferring): {ref} — live workload "
                            f"file still reports through {period_end}"
                        )
                        continue

                    # Rolled past the target: the first print survives only
                    # as an external capture.
                    def _period_capture(body: bytes) -> int:
                        candidate = ssa_official_pages.oho_workload_file(body)
                        if candidate.reporting_period_end.strftime("%Y-%m") != period:
                            raise ssa_official_pages.SsaPageError(
                                "capture reports through "
                                f"{candidate.reporting_period_end}"
                            )
                        return int(candidate.reporting_period_end.strftime("%Y%m%d"))

                    witnessed = ssa_wayback_corroboration(url, _period_capture)
                    corroborating = witnessed.get("corroboratingCapture")
                    if not corroborating:
                        print(
                            f"  FIRST-PRINT WINDOW MISSED (refusing): {ref} — the live "
                            f"workload file now reports through {period_end} and no "
                            f"Wayback capture carries the {period} reporting period "
                            f"(status {witnessed.get('status')})"
                        )
                        continue
                    body = ssa_official_pages.wayback_capture_body(
                        corroborating["timestamp"], url, ssa_wayback_fetch
                    )
                    workload = ssa_official_pages.oho_workload_file(body)
                    witnessed["resolvedFrom"] = {
                        "timestamp": corroborating["timestamp"],
                        "url": corroborating["url"],
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "bodyBase64": base64.b64encode(body).decode(),
                    }
                national, national_note = (
                    ssa_official_pages.oho_national_average_processing_time(workload)
                )
                if national is None:
                    print(
                        f"  SOURCE PUBLISHES NO NATIONAL AGGREGATE (refusing): {ref} — "
                        f"{national_note}; the cell's resolver names a figure its "
                        "bound "
                        "source does not print, so it cannot resolve mechanically"
                    )
                    continue
                low, high = spec["sanity_range"]
                if not low <= national <= high:
                    print(
                        f"  SSA OHO PARSE REFUSAL (refusing): {ref} — national APT "
                        f"{national} outside sanity range [{low}, {high}]"
                    )
                    continue
                value = float(national)
                raw = ssa_capture_envelope(
                    spec=spec,
                    period=period,
                    capture=capture,
                    reading=None,
                    raw_value=national,
                    value=value,
                    anchors=[],
                    wayback=witnessed,
                    extra={
                        "reportingPeriodEnd": period_end.isoformat(),
                        "created": workload.created,
                        "rows": len(workload.rows),
                    },
                )
                release_day = dt.date.fromisoformat(capture.retrieved_at[:10])
                source_url = url
                source_file = posixpath.basename(urlparse(url).path)
                series_id = spec["series_id"]
                retrieved_at = capture.retrieved_at
                extension = "json"
            else:
                anchor_records: list[dict[str, Any]] = []
                anchor_problem = None
                for anchor_period, expected in sorted(spec["anchors"].items()):
                    anchor_url = ssa_period_url(spec, anchor_period)
                    anchor_capture, anchor_refusal = ssa_capture(anchor_url)
                    if anchor_capture is None:
                        anchor_problem = f"anchor {anchor_period}: {anchor_refusal}"
                        break
                    try:
                        anchor_reading = ssa_read_value(
                            spec, anchor_capture.body, anchor_period
                        )
                    except ssa_official_pages.SsaPageError as exc:
                        anchor_problem = f"anchor {anchor_period} unreadable: {exc}"
                        break
                    if anchor_reading.value != expected:
                        anchor_problem = (
                            f"anchor {anchor_period}={anchor_reading.value} "
                            f"(recorded {expected})"
                        )
                        break
                    anchor_records.append(
                        {
                            "period": anchor_period,
                            **anchor_capture.response_record(),
                            "expected": expected,
                            "observed": anchor_reading.value,
                            "identities": list(anchor_reading.identities),
                        }
                    )
                if anchor_problem:
                    if "environment" in anchor_problem:
                        print(
                            "  SSA BROWSER ENVIRONMENT FAILURE (fatal): "
                            f"{ref} — {anchor_problem}"
                        )
                        environment_failures.append(f"{ref}: {anchor_problem}")
                    elif "fetch failed" in anchor_problem:
                        print(
                            "  SSA anchor fetch failed (deferring): "
                            f"{ref} — {anchor_problem}"
                        )
                    else:
                        print(
                            "  ANCHOR MISMATCH (refusing, wrong SSA table cell?): "
                            f"{ref} — "
                            f"{anchor_problem}"
                        )
                    continue
                url = ssa_period_url(spec, period)
                capture, capture_refusal = ssa_capture(url)
                if capture is None:
                    if capture_refusal and capture_refusal.startswith("environment"):
                        print(
                            "  SSA BROWSER ENVIRONMENT FAILURE (fatal): "
                            f"{ref} — {capture_refusal}"
                        )
                        environment_failures.append(f"{ref}: {capture_refusal}")
                    elif capture_refusal and "HTTP 404" in capture_refusal:
                        print(
                            "  not yet published (deferring): "
                            f"{ref} — {capture_refusal}"
                        )
                    else:
                        print(
                            "  SSA page fetch failed (deferring): "
                            f"{ref} — {capture_refusal}"
                        )
                    continue
                try:
                    reading = ssa_read_value(spec, capture.body, period)
                except ssa_official_pages.SsaPageError as exc:
                    print(f"  SSA PAGE PARSE REFUSAL (refusing): {ref} — {exc}")
                    continue
                low, high = spec["sanity_range"]
                if not low <= reading.value <= high:
                    print(
                        f"  SSA PAGE PARSE REFUSAL (refusing): {ref} — {reading.value} "
                        f"outside sanity range [{low}, {high}]"
                    )
                    continue
                wayback = ssa_wayback_corroboration(
                    url, lambda body: ssa_read_value(spec, body, period).value
                )
                corroborating = wayback.get("corroboratingCapture")
                if corroborating and corroborating["value"] != reading.value:
                    print(
                        "  WAYBACK CAPTURE DISAGREES (refusing, page revised in "
                        "place?): "
                        f"{ref} — live {reading.value} vs capture "
                        f"{corroborating['timestamp']} {corroborating['value']}"
                    )
                    continue
                value = ssa_scaled_value(spec, reading.value)
                raw = ssa_capture_envelope(
                    spec=spec,
                    period=period,
                    capture=capture,
                    reading=reading,
                    raw_value=reading.value,
                    value=value,
                    anchors=anchor_records,
                    wayback=wayback,
                )
                release_day = dt.date.fromisoformat(capture.retrieved_at[:10])
                source_url = url
                source_file = posixpath.basename(urlparse(url).path)
                series_id = spec["series_id"]
                retrieved_at = capture.retrieved_at
                extension = "json"
                corroboration_note = (
                    f"the earliest Wayback Machine capture of the same page "
                    f"({corroborating['capturedAt']}) reads the same value"
                    if corroborating
                    else "no Wayback Machine capture of the page exists to corroborate"
                )
                spec = {
                    **spec,
                    "evidence_notes": (
                        "First print for {period} captured from the edition's own "
                        "page {source_url} through a declared headless-browser "
                        "transport (ssa.gov refuses non-browser clients); the page "
                        "title and table caption name the edition, the parsed row "
                        "and column are label-anchored, the table's own row/column "
                        "sums reproduce the published totals, and the prior "
                        "edition's anchor value was re-read from its page at capture "
                        f"time; {corroboration_note}."
                    ),
                }
        elif kind == "cms_provider_data":
            metastore_key = spec["metastore_url"]
            if metastore_key not in cms_metastore_cache:
                try:
                    cms_metastore_cache[metastore_key] = cms_provider_data_metastore(
                        spec
                    )
                except Exception as exc:  # noqa: BLE001 - defer, don't crash
                    print(f"  CMS metastore fetch failed (deferring): {ref} — {exc}")
                    cms_metastore_cache[metastore_key] = None
            metastore = cms_metastore_cache[metastore_key]
            if metastore is None:
                continue
            modified, download_url, retrieved_at = metastore
            gate = cms_provider_data_gate(period, modified)
            if gate:
                if gate.startswith("missed"):
                    print(f"  FIRST-PRINT WINDOW MISSED (refusing): {ref} — {gate}")
                else:
                    print(f"  refresh not posted yet (deferring): {ref} — {gate}")
                continue
            if download_url not in cms_csv_cache:
                request = urllib.request.Request(
                    download_url, headers={"User-Agent": INTL_USER_AGENT}
                )
                try:
                    with urllib.request.urlopen(request, timeout=300) as r:
                        cms_csv_cache[download_url] = r.read()
                except Exception as exc:  # noqa: BLE001 - defer, don't crash
                    print(f"  CMS CSV fetch failed (deferring): {ref} — {exc}")
                    cms_csv_cache[download_url] = None
            raw = cms_csv_cache[download_url]
            if raw is None:
                continue
            value, refusal = cms_provider_data_value(raw, spec, modified)
            if refusal:
                print(f"  CMS PARSE REFUSAL (refusing): {ref} — {refusal}")
                continue
            # The live file IS the refresh's first print while the gate
            # holds; the capture day is the source vintage.
            release_day = dt.date.fromisoformat(retrieved_at[:10])
            source_url = download_url
            series_id = spec.get("state_row", "ALL_FACILITIES")
            source_file = download_url.rsplit("/", 1)[-1]
            extension = "csv"
        elif kind == "usaspending":
            if usaspending_contracts is None:
                usaspending_contracts = registration_contracts()
            registration = usaspending_contracts.get(ref)
            contract = (registration or {}).get("contract") or {}
            binding = contract.get("sourceBinding") or {}
            window_state = snapshot_window_state(
                dt.date.fromisoformat(utc_now()[:10]),
                binding.get("expectedReleaseWindow"),
            )
            if registration is None or window_state == "invalid":
                print(f"  NO REGISTERED SNAPSHOT WINDOW (refusing): {ref}")
                continue
            if window_state == "pending":
                print(
                    f"  SNAPSHOT WINDOW NOT OPEN (deferring): {ref} — opens "
                    f"{binding['expectedReleaseWindow']['start']}"
                )
                continue
            if window_state == "missed":
                print(
                    f"  SNAPSHOT WINDOW MISSED (refusing): {ref} — closed "
                    f"{binding['expectedReleaseWindow']['end']}"
                )
                continue
            if not usaspending_binding_matches_spec(binding, spec):
                print(
                    "  BINDING/ADAPTER MISMATCH (refusing, full seven-key "
                    f"registry drift?): {ref}"
                )
                continue
            snapshot_url = spec["url_template"].format(fiscal_year=period)
            allowed = binding.get("allowedHosts") or []
            host = urllib.parse.urlparse(snapshot_url).hostname
            if host not in allowed:
                print(f"  HOST NOT IN REGISTERED ALLOWLIST (refusing): {ref} — {host}")
                continue

            def cached_usaspending_request(
                body: dict[str, Any] | None = None,
            ) -> tuple[Any, bytes | None, str]:
                key = (
                    snapshot_url,
                    canonical_bytes(body) if body is not None else None,
                )
                if key in usaspending_cache:
                    return usaspending_cache[key]
                try:
                    usaspending_cache[key] = fetch_usaspending_json(
                        snapshot_url,
                        body,
                    )
                except (
                    urllib.error.URLError,
                    json.JSONDecodeError,
                    UnicodeDecodeError,
                    OSError,
                    ValueError,
                ) as exc:
                    print(f"  USAspending fetch failed ({exc}): {ref}")
                    usaspending_cache[key] = (None, None, utc_now())
                return usaspending_cache[key]

            query_kind = spec.get("query_kind", "scalar")
            source_url = snapshot_url
            if query_kind == "scalar":
                payload, raw, retrieved_at = cached_usaspending_request()
                if raw is None:
                    continue
                raw_value = extract_json_field(payload, spec["field"])
                if raw_value is None:
                    print(
                        f"  FIELD NOT FOUND IN RESPONSE (refusing): {ref} — "
                        f"{spec['field']}"
                    )
                    continue
            elif query_kind == "fiscal_year_post_scalar":
                try:
                    body = usaspending_fiscal_year_post_body(
                        period,
                        binding["transform"],
                    )
                except ValueError as exc:
                    print(f"  REGISTERED QUERY PLAN INVALID (refusing): {ref} — {exc}")
                    continue
                payload, response_raw, retrieved_at = cached_usaspending_request(body)
                if response_raw is None:
                    continue
                raw_value = usaspending_fiscal_year_amount(payload, period)
                if raw_value is None:
                    print(
                        f"  FIELD NOT FOUND IN RESPONSE (refusing): {ref} — "
                        f"{spec['field']}"
                    )
                    continue
                raw = usaspending_snapshot_envelope(
                    snapshot_url,
                    [(body, response_raw, retrieved_at)],
                    {
                        "operation": "select_fiscal_year_amount",
                        "fiscalYear": period,
                        "aggregatedAmount": raw_value,
                    },
                )
            elif query_kind == "paginated_distinct_count":
                pages: list[Any] = []
                exchanges: list[tuple[dict[str, Any], bytes, str]] = []
                malformed_page = False
                for page_number in range(1, 10_001):
                    try:
                        body = usaspending_recipient_page_body(
                            period,
                            binding["transform"],
                            page_number,
                        )
                    except ValueError as exc:
                        print(
                            f"  REGISTERED QUERY PLAN INVALID (refusing): {ref} — {exc}"
                        )
                        malformed_page = True
                        break
                    payload, page_raw, page_retrieved_at = cached_usaspending_request(
                        body
                    )
                    if page_raw is None:
                        malformed_page = True
                        break
                    metadata = (
                        payload.get("page_metadata")
                        if isinstance(payload, dict)
                        else None
                    )
                    has_next = (
                        metadata.get("hasNext") if isinstance(metadata, dict) else None
                    )
                    if (
                        not isinstance(metadata, dict)
                        or type(metadata.get("page")) is not int
                        or metadata.get("page") != page_number
                        or not isinstance(has_next, bool)
                    ):
                        print(f"  MALFORMED PAGINATION RESPONSE (refusing): {ref}")
                        malformed_page = True
                        break
                    pages.append(payload)
                    exchanges.append((body, page_raw, page_retrieved_at))
                    if not has_next:
                        break
                else:
                    print(f"  PAGINATION LIMIT EXCEEDED (refusing): {ref}")
                    malformed_page = True
                if malformed_page:
                    continue
                recipient_count = usaspending_distinct_recipient_count(
                    pages,
                    binding["transform"],
                )
                if recipient_count is None:
                    print(f"  RECIPIENT COUNT DERIVATION FAILED (refusing): {ref}")
                    continue
                raw_value = float(recipient_count)
                retrieved_at = exchanges[0][2]
                raw = usaspending_snapshot_envelope(
                    snapshot_url,
                    exchanges,
                    {
                        "operation": "count_distinct",
                        "fiscalYear": period,
                        "distinctRecipientCount": recipient_count,
                    },
                )
            elif query_kind == "ratio_percent":
                try:
                    denominator_body, numerator_body = usaspending_share_bodies(
                        period,
                        binding["transform"],
                    )
                except ValueError as exc:
                    print(f"  REGISTERED QUERY PLAN INVALID (refusing): {ref} — {exc}")
                    continue
                ratio_exchanges: list[tuple[dict[str, Any], bytes, str]] = []
                ratio_payloads: list[Any] = []
                ratio_fetch_failed = False
                for body in (denominator_body, numerator_body):
                    payload, response_raw, response_retrieved_at = (
                        cached_usaspending_request(body)
                    )
                    if response_raw is None:
                        ratio_fetch_failed = True
                        break
                    ratio_payloads.append(payload)
                    ratio_exchanges.append((body, response_raw, response_retrieved_at))
                if ratio_fetch_failed:
                    continue
                denominator_payload, numerator_payload = ratio_payloads
                raw_value = usaspending_ratio_percent(
                    numerator_payload,
                    denominator_payload,
                    period,
                )
                if raw_value is None:
                    print(f"  OBLIGATION SHARE DERIVATION FAILED (refusing): {ref}")
                    continue
                numerator_amount = usaspending_fiscal_year_amount(
                    numerator_payload,
                    period,
                )
                denominator_amount = usaspending_fiscal_year_amount(
                    denominator_payload,
                    period,
                )
                retrieved_at = ratio_exchanges[0][2]
                raw = usaspending_snapshot_envelope(
                    snapshot_url,
                    ratio_exchanges,
                    {
                        "operation": "ratio_percent",
                        "fiscalYear": period,
                        "numeratorObligations": numerator_amount,
                        "denominatorObligations": denominator_amount,
                        "percent": raw_value,
                    },
                )
            else:
                print(
                    f"  UNKNOWN REGISTERED QUERY KIND (refusing): {ref} — {query_kind}"
                )
                continue
            value = round(raw_value * spec.get("scale", 1), spec.get("round", 4))
            # The registered capture day IS the outcome's vintage: the
            # window gate above bounds it inside the preregistered
            # snapshot window.
            release_day = dt.date.fromisoformat(retrieved_at[:10])
            series_id = spec["series_id"]
            source_file = "registered query snapshot (USAspending API v2)"
            extension = "json"
        else:
            snapshot_url = A19_SNAPSHOT_URLS.get(period)
            if not snapshot_url:
                print(f"  no A-19 snapshot registered for {period}: {ref}")
                continue
            if period not in a19_cache:
                retrieved_at = utc_now()
                try:
                    with urllib.request.urlopen(snapshot_url, timeout=120) as r:
                        raw_html = r.read()
                    a19_cache[period] = (
                        a19_values_from_html(raw_html.decode()),
                        raw_html,
                        snapshot_url,
                        retrieved_at,
                    )
                except urllib.error.HTTPError as exc:
                    print(f"  A-19 snapshot fetch failed ({exc}): {ref}")
                    a19_cache[period] = ({}, None, snapshot_url, retrieved_at)
            values, raw, source_url, retrieved_at = a19_cache[period]
            value = values.get(spec["a19_row"])
            series_id = f"cpseea19-{spec['a19_row']}"
            source_file = "cpseea19.htm (Wayback snapshot)"
            extension = "html"
        if value is None or raw is None:
            print(f"  not yet published: {ref}")
            continue
        if kind in {"intl", "sba_pdf"}:
            plausible = intl_value_valid(spec, value)
        else:
            plausible = value_plausible(value, forecast)
        if not plausible:
            print(
                f"  IMPLAUSIBLE VALUE (refusing, wrong series/transform?): "
                f"{ref} -> {value}"
            )
            continue
        if kind == "sba_pdf":
            assert sba_resolution is not None
            row = sba_pdf_fact(ref, spec, period, sba_resolution)
        elif kind == "qcew":
            assert qcew_row is not None
            row = qcew_row
        else:
            row = generic_fact(
                ref,
                spec,
                period_type,
                period,
                value,
                release_day,
                source_url,
                source_file,
            )
            if kind == "va_mmwr":
                # The cell is keyed by the Monday report date; the workbook
                # by its Saturday data-through date. Name both.
                row["label"] = (
                    f"{spec['label']}, report {report_date.isoformat()} "
                    f"(data through {period})"
                )
                row["source_row_keys"] = [report_date.isoformat(), period]
        fetched_rows.append(
            (
                row,
                series_id,
                archive_vintage if kind == "sba_pdf" else release_day.isoformat(),
                raw,
                retrieved_at,
                extension,
            )
        )
        print(f"  resolve {ref} -> {row['value']} {row['measure']['unit']}")

    if environment_failures:
        print(
            "environment failures left admitted references unresolvable "
            "(fix the runner, do not wait):"
        )
        for line in environment_failures:
            print(f"  fatal: {line}")
        return 1
    if not fetched_rows:
        print("nothing new to record")
        return 0
    if args.dry_run:
        print(f"dry-run: would append {len(fetched_rows)} row(s)")
        for row, *_ in fetched_rows:
            print(json.dumps(row)[:200])
        return 0

    run_retrieved_at = min(item[4] for item in fetched_rows)
    run_dir = resolution_run_dir(run_retrieved_at)
    run_dir.mkdir(parents=True, exist_ok=False)
    target_contracts = registration_contracts()
    new_rows = []
    provenance_refusals: list[str] = []
    for row, series_id, vintage, raw, retrieved_at, extension in fetched_rows:
        try:
            new_rows.append(
                attach_resolution_provenance(
                    row,
                    run_dir=run_dir,
                    series_id=series_id,
                    vintage=vintage,
                    raw=raw,
                    retrieved_at=retrieved_at,
                    ledger_repo_sha=ledger_repo_sha,
                    target_contracts=target_contracts,
                    extension=extension,
                )
            )
        except ValueError as exc:
            # One target's contract refusal must not hold every other
            # resolution hostage (the 2026-07-23/25 outages): append the
            # sound rows, report the refusal loudly, and fail the run at
            # the end so the alarm still fires.
            ref = str(row.get("source_record_id", "?"))
            provenance_refusals.append(f"{ref}: {exc}")
            print(f"  PROVENANCE REFUSED (excluded from append): {ref} — {exc}")
    if not new_rows:
        print("every fetched row was refused; nothing to append")
        for line in provenance_refusals:
            print(f"  refused: {line}")
        return 1

    updated = (
        content.rstrip("\n")
        + "\n"
        + "\n".join(json.dumps(row, separators=(",", ":")) for row in new_rows)
        + "\n"
    )
    finalize_resolution_manifest(
        run_dir,
        {
            "schemaVersion": "thesis_resolution_run_v1",
            "retrievedAt": run_retrieved_at,
            "ledgerRepo": args.ledger_repo,
            "ledgerBranch": args.ledger_branch,
            "ledgerRepoSha": ledger_repo_sha,
            "facts": [
                {
                    "dataPointId": row["source_record_id"],
                    "sourceVintage": row["sourceVintage"],
                    "retrievedAt": row["retrievedAt"],
                    "targetContentHash": row.get("targetContentHash"),
                    "responseArchive": row["responseArchive"],
                }
                for row in new_rows
            ],
        },
    )
    merged_sha = propose_ledger_append(
        args.ledger_repo,
        args.ledger_branch,
        args.ledger_path,
        updated,
        sha,
        ledger_repo_sha,
        len(new_rows),
        producer_signing_key=producer_signing_key,
    )
    print(
        f"appended {len(new_rows)} observation(s) to "
        f"{args.ledger_repo}@{args.ledger_branch}:{args.ledger_path} "
        f"via reviewed proposal (merged at {merged_sha})"
    )
    if provenance_refusals:
        print(
            f"{len(provenance_refusals)} row(s) refused contract binding; "
            "appended the rest — fix the registrations above"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
