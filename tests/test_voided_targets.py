"""Targets a recorded ruling voided (scripts/voided_targets.py).

Invariants:
- each void names exactly the registration on disk (dataPointId and hash);
- no voided target is one the legacy release leg resolves;
- each reason states facts the registration itself shows, wherever the
  repository holds the evidence: the BEA vintage date against its window,
  the SSA table month against the period, the page and window of a
  no-custody void, and the Archive's index for that window, replayed
  through the leg's own discovery;
- no resolver family routes a voided reference, for any pending log;
- the status file reports an overdue voided target as VOIDED with its
  ruling, whatever the resolver printed about it, and the register changes
  no other row (a differential against an empty register);
- the committed status file already holds those VOIDED rows.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import posixpath
import re
import sys
import urllib.parse

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolution_status as rs  # noqa: E402
import resolve_pending  # noqa: E402
import voided_targets  # noqa: E402
from legacy_release_contracts import (  # noqa: E402
    LEGACY_RELEASE_ALFRED_CONTRACTS,
    LEGACY_RELEASE_CAPTURE_CONTRACTS,
)
from voided_targets import VOIDED_TARGETS  # noqa: E402

REGISTRATIONS = resolve_pending.registration_contracts()
VOIDED = sorted(VOIDED_TARGETS)

# Ruling d1633 (2026-10-22): 8 BEA June frozen-vintage cells, SSI August,
# real earnings July and August, telework August and September.
D1633_VOIDS = {
    "bea.disposable_personal_income.level.june_2026.first_print",
    "bea.government_social_benefits.level.june_2026.first_print",
    "bea.government_social_benefits.medicaid.june_2026.first_print",
    "bea.government_social_benefits.medicare.june_2026.first_print",
    "bea.government_social_benefits.social_security.june_2026.first_print",
    "bea.pce.core_mom.june_2026.first_print",
    "bea.pce_price_index.monthly_change.june_2026.first_print",
    "bea.personal_current_taxes.level.june_2026.first_print",
    "ssa.ssi.total_recipients.2026-08.first_print",
    "bls.real_earnings.avg_hourly_mom.2026-07.first_print",
    "bls.real_earnings.avg_hourly_mom.2026-08.first_print",
    "bls.cps.telework_share.2026-08.first_print",
    "bls.cps.telework_share.2026-09.first_print",
}


def _binding(ref: str) -> dict:
    return REGISTRATIONS[ref]["contract"]["sourceBinding"]


def test_the_register_is_exactly_the_d1633_void_list() -> None:
    assert set(VOIDED_TARGETS) == D1633_VOIDS
    assert {(v.ruling, v.ruled_on) for v in VOIDED_TARGETS.values()} == {
        ("d1633", "2026-10-22")
    }


@pytest.mark.parametrize("ref", VOIDED)
def test_each_void_names_its_registration_exactly(ref: str) -> None:
    registration = REGISTRATIONS[ref]
    assert registration["contract"]["dataPointId"] == ref
    assert registration["targetContentHash"] == VOIDED_TARGETS[ref].target_content_hash
    assert VOIDED_TARGETS[ref].reason.strip()


def test_no_voided_target_is_one_the_legacy_release_leg_resolves() -> None:
    resolved = {
        entry["contract"]["dataPointId"]
        for entry in (
            *LEGACY_RELEASE_CAPTURE_CONTRACTS.values(),
            *LEGACY_RELEASE_ALFRED_CONTRACTS.values(),
        )
    }
    hashes = set(LEGACY_RELEASE_CAPTURE_CONTRACTS) | set(
        LEGACY_RELEASE_ALFRED_CONTRACTS
    )
    assert not resolved & set(VOIDED_TARGETS)
    assert not hashes & {v.target_content_hash for v in VOIDED_TARGETS.values()}


def _window(ref: str) -> tuple[str, str]:
    window = _binding(ref)["expectedReleaseWindow"]
    return window["start"], window["end"]


@pytest.mark.parametrize(
    "ref", [r for r in VOIDED if r.startswith("bea.")], ids=lambda r: r.split(".")[1]
)
def test_a_bea_void_registers_a_vintage_older_than_its_own_window(ref: str) -> None:
    url = _binding(ref)["sourceUrl"]
    vintage = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["vintage_date"]
    start, end = _window(ref)
    assert vintage == ["2026-06-25"]
    assert dt.date.fromisoformat(vintage[0]) < dt.date.fromisoformat(start)
    assert REGISTRATIONS[ref]["contract"]["period"] == "2026-06"
    reason = VOIDED_TARGETS[ref].reason
    assert reason == voided_targets._BEA_JUNE_FROZEN_VINTAGE
    for date in (vintage[0], start, end):
        assert date in reason


def test_the_ssi_void_registers_another_months_table() -> None:
    ref = "ssa.ssi.total_recipients.2026-08.first_print"
    url = _binding(ref)["sourceUrl"]
    month = re.search(r"/ssi_monthly/(\d{4}-\d{2})/", url)
    assert month is not None and month.group(1) == "2026-07"
    assert REGISTRATIONS[ref]["contract"]["period"] == "2026-08"
    assert "ssi_monthly/2026-07/table02.html" in url
    assert "ssi_monthly/2026-07/table02.html" in VOIDED_TARGETS[ref].reason


@pytest.mark.parametrize(
    "ref",
    [
        "bls.real_earnings.avg_hourly_mom.2026-07.first_print",
        "bls.real_earnings.avg_hourly_mom.2026-08.first_print",
        "bls.cps.telework_share.2026-08.first_print",
    ],
)
def test_a_no_custody_void_names_its_registered_page_and_window(ref: str) -> None:
    page = posixpath.basename(urllib.parse.urlparse(_binding(ref)["sourceUrl"]).path)
    start, end = _window(ref)
    assert VOIDED_TARGETS[ref].reason == voided_targets._no_custody(page, start, end)


_NO_CUSTODY = sorted(
    ref
    for ref, voided in VOIDED_TARGETS.items()
    if "has no Internet Archive capture" in voided.reason
)
_INDEX_READS = ROOT / "tests" / "fixtures" / "release_capture" / "cdx"


def test_every_no_custody_void_has_its_index_read() -> None:
    assert len(_NO_CUSTODY) == 3
    assert len(list(_INDEX_READS.glob("*.json"))) == len(_NO_CUSTODY)


@pytest.mark.parametrize("ref", _NO_CUSTODY)
def test_the_archive_index_lists_no_capture_in_a_no_custody_window(ref: str) -> None:
    """Replays the saved index read through the leg's own discovery."""
    binding = _binding(ref)
    window = binding["expectedReleaseWindow"]
    start, end = (dt.date.fromisoformat(window[key]) for key in ("start", "end"))
    page = posixpath.basename(urllib.parse.urlparse(binding["sourceUrl"]).path)
    read = json.loads(
        (
            _INDEX_READS
            / f"{page.removesuffix('.htm')}-{start:%Y%m%d}-{end:%Y%m%d}.json"
        ).read_text()
    )
    query = resolve_pending.WAYBACK_CDX_URL.format(
        url=urllib.parse.quote(binding["sourceUrl"], safe=""),
        start=f"{start:%Y%m%d}000000",
        end=f"{end:%Y%m%d}235959",
    )
    assert (read["sourceUrl"], read["query"], read["httpStatus"]) == (
        binding["sourceUrl"],
        query,
        200,
    )

    def served(url: str) -> tuple[bytes, str]:
        assert url == query, url
        return read["body"].encode(), url

    index = resolve_pending.a19_window_captures(
        window, served, source_url=binding["sourceUrl"]
    )
    assert (index.listed, index.rows, index.captures) == (0, [], [])
    assert read["readOnUtc"] in VOIDED_TARGETS[ref].reason


def _pending_log(refs: list[str]) -> dict:
    return {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": f"slug-{i}",
                "resolutionDate": "2026-09-30",
                "unit": REGISTRATIONS[ref]["contract"].get("unit"),
            }
            for i, ref in enumerate(refs)
        ],
        "resolutionLinks": [
            {"status": "pending", "targetFactRef": ref, "forecastSlug": f"slug-{i}"}
            for i, ref in enumerate(refs)
        ],
    }


_ROUTED_REFS = sorted(
    {
        entry["contract"]["dataPointId"]
        for entry in LEGACY_RELEASE_CAPTURE_CONTRACTS.values()
    }
)


@settings(max_examples=50, deadline=None)
@given(
    voided=st.lists(st.sampled_from(VOIDED), unique=True),
    routed=st.lists(st.sampled_from(_ROUTED_REFS), unique=True),
)
def test_no_resolver_family_routes_a_voided_reference(
    voided: list[str], routed: list[str]
) -> None:
    log = _pending_log([*voided, *routed])
    adapter = {item[0] for item in resolve_pending.pending_adapter_refs(log)}
    claims = {item[0] for item in resolve_pending.pending_claims_refs(log)}
    assert not (adapter | claims) & set(VOIDED_TARGETS)
    # The register removes only voided references.
    assert adapter == set(routed)


def test_without_the_register_some_voided_reference_would_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The routing filter is load-bearing: the BEA and SSA stems would route."""
    monkeypatch.setattr(resolve_pending, "VOIDED_TARGETS", {})
    routed = {
        item[0] for item in resolve_pending.pending_adapter_refs(_pending_log(VOIDED))
    }
    assert routed & set(VOIDED_TARGETS)


_LINES = (
    "  resolve {ref} -> 1.0 percent",
    "  BINDING/ADAPTER MISMATCH (skipping, registered adapter='generic-url' is "
    "not a bea_release family): {ref}",
    "  not yet published: {ref}",
    "  BLS API fetch failed: {ref}",
    "",
)
AS_OF = dt.date(2026, 10, 22)


def _status(log: dict, text: str, voided: dict | None = None) -> dict:
    targets, run = rs.parse_resolver_log(text)
    return rs.build_status(
        log,
        targets,
        run,
        claimed_refs=set(),
        registrations=REGISTRATIONS,
        as_of=AS_OF,
        **({} if voided is None else {"voided_targets": voided}),
    )


@settings(max_examples=50, deadline=None)
@given(ref=st.sampled_from(VOIDED), line=st.sampled_from(_LINES))
def test_an_overdue_voided_target_reports_voided_with_its_ruling(
    ref: str, line: str
) -> None:
    text = (line.format(ref=ref) + "\n" if line else "") + (
        "resolution loop complete: 1 reference(s) examined\n"
        "resolver finished with exit code 0\n"
    )
    row = _status(_pending_log([ref]), text)["targets"][ref]
    voided = VOIDED_TARGETS[ref]
    assert row["state"] == "voided"
    assert row["code"] == "VOIDED"
    assert row["reason"] == rs.REASONS["VOIDED"]
    assert row["ruling"] == f"{voided.reason} Voided by ruling on {voided.ruled_on}."
    assert row["ruling"] == rs.voided_ruling(voided)
    assert "detail" not in row and "registration" not in row


def test_the_committed_status_file_agrees_with_the_register() -> None:
    """A void ships with its row: the site never shows a void as overdue.

    The resolver workflow rewrites this file after each run, from the same
    register, so a void that lands without its rows would show "Overdue"
    until then. Each row the file holds for a voided target must already be
    the VOIDED row build_status writes, and no other row may be VOIDED.
    """
    status = json.loads(
        (ROOT / "site" / "src" / "data" / "resolution-status.json").read_text()
    )
    rows = status["targets"]
    voided_rows = {ref for ref, row in rows.items() if row["code"] == "VOIDED"}
    assert voided_rows, "no VOIDED row in the committed status file"
    assert voided_rows == set(rows) & set(VOIDED_TARGETS)
    for ref in voided_rows:
        row = rows[ref]
        assert {key: row[key] for key in ("state", "code", "reason", "ruling")} == {
            "state": "voided",
            "code": "VOIDED",
            "reason": rs.reason_for("VOIDED", "voided"),
            "ruling": rs.voided_ruling(VOIDED_TARGETS[ref]),
        }, ref
        assert set(row) == {
            "forecastSlug",
            "resolutionDate",
            "state",
            "code",
            "reason",
            "ruling",
        }, ref
    for ref, row in rows.items():
        assert ("ruling" in row) is (ref in voided_rows), ref


_OTHER_REFS = sorted(
    ref
    for ref in REGISTRATIONS
    if ref not in VOIDED_TARGETS and ref.endswith(".first_print")
)[:40]


@settings(max_examples=50, deadline=None)
@given(
    voided=st.lists(st.sampled_from(VOIDED), unique=True),
    others=st.lists(st.sampled_from(_OTHER_REFS), unique=True, max_size=8),
    line=st.sampled_from(_LINES),
)
def test_the_register_changes_no_other_row(
    voided: list[str], others: list[str], line: str
) -> None:
    refs = [*voided, *others]
    text = "".join(line.format(ref=ref) + "\n" for ref in refs if line)
    with_register = _status(_pending_log(refs), text)["targets"]
    without = _status(_pending_log(refs), text, voided={})["targets"]
    assert set(with_register) == set(without) == set(refs)
    for ref in others:
        assert with_register[ref] == without[ref]
    for ref in voided:
        assert with_register[ref]["code"] == "VOIDED"
        assert without[ref]["code"] != "VOIDED"
