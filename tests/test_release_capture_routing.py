"""Legacy routes use immutable metadata and synthetic responses only.

No target-window response or target-month outcome is read by this suite.
"""

from __future__ import annotations

import copy
import datetime as dt
import gzip
import pathlib
import sys
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolve_pending as rp  # noqa: E402

CAPTURE = rp.LEGACY_RELEASE_CAPTURE_CONTRACTS
ALFRED = rp.LEGACY_RELEASE_ALFRED_CONTRACTS
REVIEWED = {**CAPTURE, **ALFRED}


def registration(content_hash: str) -> dict[str, Any]:
    return {
        "targetContentHash": content_hash,
        "contract": copy.deepcopy(REVIEWED[content_hash]["contract"]),
    }


def log_for(reg: dict[str, Any], release_date: str | None = None) -> dict[str, Any]:
    contract = reg["contract"]
    return {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": contract["catalogSlug"],
                "unit": contract["unit"],
                "resolutionDate": release_date
                or contract["sourceBinding"]["expectedReleaseWindow"]["end"],
            }
        ],
        "resolutionLinks": [
            {
                "status": "pending",
                "forecastSlug": contract["catalogSlug"],
                "targetFactRef": contract["dataPointId"],
            }
        ],
    }


def install_main(monkeypatch, reg, release_date=None):
    ref = reg["contract"]["dataPointId"]
    monkeypatch.setattr(rp, "load_thesis_log", lambda _: log_for(reg, release_date))
    monkeypatch.setattr(rp, "ledger_state", lambda *_: ("", "blob", "a" * 40))
    monkeypatch.setattr(rp, "registration_contracts", lambda: {ref: reg})
    monkeypatch.setattr(rp, "utc_now", lambda: "2026-10-16T12:00:00Z")
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])

    def no_network(*_args, **_kwargs):
        pytest.fail("unexpected network request")

    monkeypatch.setattr(rp, "_wayback_read", no_network)
    monkeypatch.setattr(rp, "fred_vintage_series", no_network)


@pytest.mark.parametrize("content_hash", CAPTURE)
def test_each_of_twelve_refs_reaches_capture_leg(monkeypatch, capsys, content_hash):
    reg = registration(content_hash)
    install_main(monkeypatch, reg)
    contract = reg["contract"]
    period = contract["period"]
    binding = contract["sourceBinding"]
    stamp = binding["expectedReleaseWindow"]["start"].replace("-", "") + "120000"
    raw = b"synthetic local test response; no official outcome"
    calls = []

    def discover(actual_period, window, today, read, **kwargs):
        calls.append(kwargs)
        assert actual_period == period
        assert window == binding["expectedReleaseWindow"]
        assert today == dt.date(2026, 10, 16)
        assert kwargs["request_capture"] is False
        assert kwargs["require_digest"] is True
        assert kwargs["source_url"] == binding["sourceUrl"]
        assert kwargs["parser"]("synthetic") == (period, 1234.0)
        return rp.A19Discovery(
            f"https://web.archive.org/web/{stamp}/{binding['sourceUrl']}",
            raw,
            "",
            digest=rp.a19_digest(raw),
        )

    monkeypatch.setattr(rp, "a19_registered_capture", discover)
    monkeypatch.setattr(rp, "parse_release", lambda html, parser_id: (period, 1234.0))
    facts = []
    fact_builder = rp.legacy_release_capture_fact

    def capture_fact(*args):
        fact = fact_builder(*args)
        facts.append(fact)
        return fact

    monkeypatch.setattr(rp, "legacy_release_capture_fact", capture_fact)
    assert rp.main() == 0
    output = capsys.readouterr().out
    assert "BINDING/ADAPTER MISMATCH" not in output
    assert "dry-run: would append 1 row(s)" in output
    assert len(calls) == len(facts) == 1
    fact = facts[0]
    expected = 1.234 if binding["transform"]["factor"] == 0.001 else 1234.0
    assert fact["value"] == expected
    assert fact["source"]["url"] == binding["sourceUrl"]
    assert fact["measure"]["concept"] == contract["series"]
    assert fact["measure"]["unit"] == contract["unit"]
    assert fact["observed_at"] == binding["expectedReleaseWindow"]["start"]


def test_unreviewed_generic_url_keeps_existing_mismatch_line(monkeypatch, capsys):
    reg = registration(next(iter(CAPTURE)))
    reg["targetContentHash"] = "0" * 64
    install_main(monkeypatch, reg)
    assert rp.main() == 0
    output = capsys.readouterr().out
    assert (
        "BINDING/ADAPTER MISMATCH (skipping, registered adapter='generic-url' "
        "is not a alfred family)"
    ) in output


@pytest.mark.parametrize("content_hash,entry", REVIEWED.items())
def test_reviewed_route_authenticates_every_top_level_key_before_fetch(
    monkeypatch, capsys, content_hash, entry
):
    reg = registration(content_hash)
    ref = reg["contract"]["dataPointId"]
    log = log_for(reg)
    routed = rp.pending_adapter_refs(log, {ref: reg})
    for key in entry["contract"]:
        changed = registration(content_hash)
        changed["contract"][key] = None
        install_main(monkeypatch, changed)
        # Preserve the original published reference and trusted routing spec
        # while mutating exactly one registration key, including dataPointId.
        monkeypatch.setattr(rp, "load_thesis_log", lambda _: log)
        monkeypatch.setattr(rp, "registration_contracts", lambda: {ref: changed})
        monkeypatch.setattr(rp, "pending_adapter_refs", lambda _: routed)
        assert rp.main() == 0
        output = capsys.readouterr().out
        assert "registered legacy release contract differs in " + key in output
        assert "would append" not in output


def test_ces_does_not_claim_an_unreviewed_stem():
    for content_hash, entry in CAPTURE.items():
        if entry["parser"] != "empsit_payroll_change":
            continue
        reg = registration(content_hash)
        reg["targetContentHash"] = "0" * 64
        ref = reg["contract"]["dataPointId"]
        assert not rp.pending_adapter_refs(log_for(reg), {ref: reg})


def test_alfred_alias_uses_ppifis_and_a_registered_vintage(monkeypatch, capsys):
    content_hash = next(iter(ALFRED))
    reg = registration(content_hash)
    install_main(monkeypatch, reg, "2026-08-14")
    calls = []

    def vintage(series, day):
        calls.append((series, day))
        return (
            {"2026-06-01": 100.0, "2026-07-01": 101.0},
            b"synthetic ALFRED CSV, not an official outcome",
            rp.FRED_CSV.format(series=series, vintage=day),
            "2026-10-16T12:00:00Z",
        )

    monkeypatch.setattr(rp, "fred_vintage_series", vintage)
    assert rp.main() == 0
    assert calls == [("PPIFIS", "2026-08-14")]
    assert "dry-run: would append 1 row(s)" in capsys.readouterr().out


@pytest.mark.parametrize("day", ["2026-08-10", "2026-08-20"])
def test_alfred_alias_refuses_a_vintage_outside_registered_window(
    monkeypatch, capsys, day
):
    reg = registration(next(iter(ALFRED)))
    install_main(monkeypatch, reg, day)
    assert rp.main() == 0
    output = capsys.readouterr().out
    assert "FORECAST/REGISTERED RELEASE DATE MISMATCH" in output
    assert "would append" not in output


def test_capture_provenance_binds_publisher_host_and_verified_stored_digest(
    monkeypatch, tmp_path
):
    content_hash = next(iter(CAPTURE))
    reg = registration(content_hash)
    contract = reg["contract"]
    ref = contract["dataPointId"]
    _kind, spec = rp.legacy_release_spec(content_hash)
    raw = b"synthetic decoded HTML; no official outcome"
    digest = rp.a19_digest(gzip.compress(raw, mtime=0))
    stamp = "20260909120000"
    url = (
        f"https://web.archive.org/web/{stamp}/{contract['sourceBinding']['sourceUrl']}"
    )
    discovery = rp.A19Discovery(
        url,
        raw,
        "",
        witness="20260908120000",
        witness_reason="which is stored under another form of the URL and not read",
        digest=digest,
    )
    row = rp.legacy_release_capture_fact(ref, spec, contract["period"], 12.3, discovery)
    monkeypatch.setattr(rp, "ROOT", tmp_path)
    enriched = rp.attach_resolution_provenance(
        row,
        run_dir=tmp_path / "run",
        series_id="synthetic",
        vintage="2026-09-09",
        raw=raw,
        retrieved_at="2026-10-16T12:00:00Z",
        ledger_repo_sha="a" * 40,
        target_contracts={ref: reg},
        extension="html",
    )
    assert enriched["source"]["url"] == contract["sourceBinding"]["sourceUrl"]
    assert enriched["measure"]["concept_evidence_url"] == url
    assert enriched["captureProvenance"]["indexDigest"] == digest
    assert digest != rp.a19_digest(raw)
    assert stamp in enriched["source"]["source_file"]
    assert digest in enriched["source"]["source_file"]
    assert discovery.witness in enriched["source"]["source_file"]
    assert enriched["sourceVintage"] == "2026-09-09"
    assert enriched["responseArchive"]["path"].endswith(".html.gz")
    assert enriched["targetContentHash"] == content_hash
