from __future__ import annotations

import base64
import datetime as dt
import gzip
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ledger_release_chain  # noqa: E402
import register_targets  # noqa: E402
import resolve_pending  # noqa: E402
from canonical_json import canonical_bytes, canonical_sha256  # noqa: E402
from verify_custody import verify_run  # noqa: E402


def _alfred_docket_entries() -> list[dict]:
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    return [
        entry
        for entry in docket["series"]
        if (entry.get("extras") or {}).get("sourceBinding", {}).get("adapter")
        == "alfred-fred"
    ]


@pytest.mark.parametrize(
    (
        "request_name",
        "series_id",
        "period",
        "observation_date",
        "vintage_date",
        "fixture_name",
        "byte_length",
        "sha256",
        "value",
    ),
    [
        (
            "bea-private-nonresidential-fixed-investment.json",
            "PNFI",
            "2025-Q2",
            "2025-04-01",
            "2025-07-30",
            "pnfi-2025-q2-first-print.csv",
            51,
            "9f550bc31dca1359e70ddf7e9588ef9b67c901ed3eed1c1da8b610aad37b890f",
            4203.220,
        ),
        (
            "bea-private-nonresidential-fixed-investment.json",
            "PNFI",
            "2025-Q3",
            "2025-07-01",
            "2025-12-23",
            "pnfi-2025-q3-first-print.csv",
            51,
            "b588e9e3e0735b6a145285c529c02344f037303249b175d33a301e39b7f38a52",
            4291.558,
        ),
        (
            "bea-private-nonresidential-fixed-investment.json",
            "PNFI",
            "2025-Q4",
            "2025-10-01",
            "2026-02-20",
            "pnfi-2025-q4-first-print.csv",
            51,
            "05b9718a7ab180b5f8aa5028dbdc04291f5e76c69ebacd0214239d5c57d4df92",
            4378.954,
        ),
        (
            "bea-research-and-development-fixed-investment.json",
            "Y006RC1Q027SBEA",
            "2025-Q2",
            "2025-04-01",
            "2025-07-30",
            "bea-rd-2025-q2-first-print.csv",
            61,
            "555e5af679223e3365edff09947b29e6d1e78e4ed978cd7553d15da3730ac61e",
            821.083,
        ),
        (
            "bea-research-and-development-fixed-investment.json",
            "Y006RC1Q027SBEA",
            "2025-Q3",
            "2025-07-01",
            "2025-12-23",
            "bea-rd-2025-q3-first-print.csv",
            61,
            "25499799f3ed33b75e0a715248a83fa7d865a5ff84c323fd4f5cfceff3cee2c6",
            855.863,
        ),
        (
            "bea-research-and-development-fixed-investment.json",
            "Y006RC1Q027SBEA",
            "2025-Q4",
            "2025-10-01",
            "2026-02-20",
            "bea-rd-2025-q4-first-print.csv",
            61,
            "1e7e49c3d4c3468182298f1ec511bb38cafbb1a96d0a83a3f62414b729de01f1",
            885.955,
        ),
    ],
)
def test_wave1_bea_first_print_fixtures_are_hash_pinned_and_parse(
    request_name: str,
    series_id: str,
    period: str,
    observation_date: str,
    vintage_date: str,
    fixture_name: str,
    byte_length: int,
    sha256: str,
    value: float,
) -> None:
    relative_fixture = f"tests/fixtures/ingestion_wave1/alfred/{fixture_name}"
    raw = (ROOT / relative_fixture).read_bytes()
    assert len(raw) == byte_length
    assert hashlib.sha256(raw).hexdigest() == sha256
    assert resolve_pending.parse_fred_vintage_csv(raw, series_id, vintage_date) == {
        observation_date: value
    }

    request = json.loads(
        (ROOT / "drafts" / "ledger-ingestion" / request_name).read_text()
    )
    anchors = request["verification"]["firstPrintAnchors"]
    assert len(anchors) == 3
    anchor = next(row for row in anchors if row["observationPeriod"] == period)
    assert anchor["observationDate"] == observation_date
    assert anchor["vintageDate"] == vintage_date
    assert anchor["fixture"] == relative_fixture
    assert anchor["byteLength"] == byte_length
    assert anchor["sha256"] == sha256
    assert anchor["fetchedValue"] == value
    assert anchor["priorDayObservationAbsent"] is True


@pytest.mark.parametrize(
    ("series", "expected"),
    [
        (
            "bea.private_nonresidential_fixed_investment",
            {
                "fred": "PNFI",
                "transform": "level",
                "unit": "usd_billions",
                "label": ("US private nonresidential fixed investment, nominal SAAR"),
                "source_name": "bea",
                "source_table": (
                    "Gross Domestic Product, Table 5.3.5 "
                    "(private fixed investment by type)"
                ),
                "concept_authority": "bea",
            },
        ),
        (
            "bea.research_and_development_fixed_investment",
            {
                "fred": "Y006RC1Q027SBEA",
                "transform": "level",
                "unit": "usd_billions",
                "label": (
                    "US private research and development fixed investment, nominal SAAR"
                ),
                "source_name": "bea",
                "source_table": (
                    "Gross Domestic Product, Table 5.6.5 (private R&D fixed investment)"
                ),
                "concept_authority": "bea",
            },
        ),
    ],
)
def test_wave1_bea_alfred_history_mirror_specs(
    series: str, expected: dict[str, object]
) -> None:
    assert resolve_pending.ALFRED_HISTORY_MIRRORS[series] == expected


def test_archives_raw_response_and_attaches_append_provenance(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    data_point_id = "us.dol.initial_claims.sa.week_2030-01-05"
    contract = {
        "dataPointId": data_point_id,
        "series": "us.dol.initial_claims.sa",
        "period": "2030-01-05",
        "unit": "thousands",
        "sourceBinding": {
            "releasePolicy": "advance_vintage",
            "table": "ALFRED graph CSV",
            "field": "ICSA",
            "transform": {"operation": "multiply", "factor": 0.001},
        },
    }
    snapshot = {
        "schemaVersion": "thesis_target_registration_v1",
        "targets": [contract],
    }
    content_hash = canonical_sha256(snapshot)
    records = tmp_path / "records" / "targets"
    records.mkdir(parents=True)
    (records / f"2030-01-01-{content_hash}.json").write_bytes(
        canonical_bytes(snapshot) + b"\n"
    )
    target_contracts = resolve_pending.registration_contracts(records)
    raw = b"observation_date,ICSA_20300110\n2030-01-05,245000\n"
    run_dir = tmp_path / "records" / "resolutions" / "2030-01-10" / "run"
    run_dir.mkdir(parents=True)
    row = {
        "source_record_id": data_point_id,
        "value": 245.0,
        "observed_at": "2030-01-10",
        "measure": {"concept": "us.dol.initial_claims.sa", "unit": "thousands"},
        "source": {"source_name": "dol_eta", "vintage": "advance"},
    }

    enriched = resolve_pending.attach_resolution_provenance(
        row,
        run_dir=run_dir,
        series_id="ICSA",
        vintage="2030-01-10",
        raw=raw,
        retrieved_at="2030-01-10T13:40:00Z",
        ledger_repo_sha="a" * 40,
        target_contracts=target_contracts,
    )

    archive = enriched["responseArchive"]
    assert enriched["targetContentHash"] == content_hash
    projection = enriched["sourceBindingProjection"]
    assert projection["unit"] == "thousands"
    assert projection["field"] == "ICSA"
    assert projection["responseSha256"] == archive["sha256"]
    assert enriched["assertionVersion"]["id"].startswith("av2:")
    assert enriched["assertionVersion"]["supersedes"] is None
    # The assertion version binds the archived response digest, so it must be
    # computed over the enriched row (with responseArchive), not the bare row.
    assert (
        enriched["assertionVersion"]["id"]
        == resolve_pending.assertion_version(enriched)["id"]
    )
    assert (
        enriched["assertionVersion"]["id"]
        != resolve_pending.assertion_version(row)["id"]
    )
    assert enriched["ledgerRepoSha"] == "a" * 40
    assert enriched["sourceVintage"] == "2030-01-10"
    assert enriched["retrievedAt"] == "2030-01-10T13:40:00Z"
    assert archive["contentEncoding"] == "gzip"
    assert gzip.decompress((tmp_path / archive["path"]).read_bytes()) == raw
    assert len(archive["sha256"]) == 64
    assert len(archive["gzipSha256"]) == 64

    manifest = resolve_pending.finalize_resolution_manifest(
        run_dir,
        {
            "schemaVersion": "thesis_resolution_run_v1",
            "retrievedAt": enriched["retrievedAt"],
            "ledgerRepo": "PolicyEngine/chronicle",
            "ledgerBranch": "facts",
            "ledgerRepoSha": enriched["ledgerRepoSha"],
            "facts": [
                {
                    "dataPointId": data_point_id,
                    "sourceVintage": enriched["sourceVintage"],
                    "retrievedAt": enriched["retrievedAt"],
                    "targetContentHash": enriched["targetContentHash"],
                    "responseArchive": archive,
                }
            ],
        },
    )
    result = verify_run(run_dir)
    assert manifest["custodyInventoryVersion"] == 2
    assert result.run_mode == "resolver"
    assert result.inventory_status == "complete"
    assert result.headline_eligible is False


def test_pending_claims_uses_recorded_release_date_not_a_fixed_offset() -> None:
    data_point_id = "us.dol.initial_claims.sa.week_2030-07-01"
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "initial-claims-week-2030-07-01",
                # Holiday-shift fixture: deliberately not week-ending + 5.
                "resolutionDate": "2030-07-05",
            }
        ],
        "resolutionLinks": [
            {
                "forecastSlug": "initial-claims-week-2030-07-01",
                "targetFactRef": data_point_id,
                "status": "pending",
            }
        ],
    }

    assert resolve_pending.pending_claims_refs(log) == [
        (data_point_id, "2030-07-01", "initial", "2030-07-05")
    ]


def test_ledger_state_pins_content_fetch_to_the_recorded_repo_sha(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if "/commits/" in command[2]:
            return SimpleNamespace(stdout="a" * 40 + "\n")
        return SimpleNamespace(stdout='{"sha":"blob-sha","content":"e30K"}')

    monkeypatch.setattr(resolve_pending.subprocess, "run", fake_run)

    content, blob_sha, repo_sha = resolve_pending.ledger_state(
        "PolicyEngine/chronicle", "facts", "ledger/facts.jsonl"
    )

    assert content == "{}\n"
    assert blob_sha == "blob-sha"
    assert repo_sha == "a" * 40
    assert calls[1][2].endswith(f"?ref={'a' * 40}")


def test_main_removes_signing_secret_before_any_resolver_work(
    monkeypatch, capsys
) -> None:
    signing_key = "generated-test-signing-key"
    monkeypatch.setenv(resolve_pending.PRODUCER_SIGNING_KEY_ENV, signing_key)

    def load_log(_url: str) -> dict:
        assert resolve_pending.PRODUCER_SIGNING_KEY_ENV not in os.environ
        return {"entries": [], "resolutionLinks": []}

    monkeypatch.setattr(resolve_pending, "load_thesis_log", load_log)
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py"])

    assert resolve_pending.main() == 0
    assert capsys.readouterr().out == "no pending adapter-covered cells\n"
    assert resolve_pending.PRODUCER_SIGNING_KEY_ENV not in os.environ


def test_main_gates_a_non_irs_bounded_adapter_before_network(
    monkeypatch, capsys
) -> None:
    ref = "agency.test.rate.2030-01.first_print"
    spec = {
        "fred": "TEST",
        "transform": "level",
        "unit": "percent",
        "label": "Agency test rate",
        "source_name": "agency",
        "source_table": "Table A",
        "concept_authority": "agency",
    }
    forecast = {"resolutionDate": "2030-03-31", "unit": "percent"}
    registration = {
        "contract": {
            "resolutionDateBasis": "resolve-by-bound",
            "sourceBinding": {
                "adapter": "alfred-fred",
                "expectedReleaseWindow": {
                    "start": "2030-02-01",
                    "end": "2030-03-31",
                },
            },
        }
    }
    monkeypatch.setattr(
        resolve_pending,
        "load_thesis_log",
        lambda _url: {"entries": [], "resolutionLinks": []},
    )
    monkeypatch.setattr(resolve_pending, "pending_claims_refs", lambda _log: [])
    monkeypatch.setattr(
        resolve_pending,
        "pending_adapter_refs",
        lambda _log: [
            (ref, "alfred", spec, "month", "2030-01", "2030-03-31", forecast)
        ],
    )
    monkeypatch.setattr(
        resolve_pending,
        "ledger_state",
        lambda *_args: ("", "blob", "a" * 40),
    )
    monkeypatch.setattr(
        resolve_pending, "registration_contracts", lambda: {ref: registration}
    )
    monkeypatch.setattr(resolve_pending, "utc_now", lambda: "2030-01-31T23:59:59Z")

    def unexpected_fetch(*_args, **_kwargs):
        raise AssertionError("bounded adapter fetched before its window opened")

    monkeypatch.setattr(resolve_pending, "fred_vintage_series", unexpected_fetch)
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])

    assert resolve_pending.main() == 0
    output = capsys.readouterr().out
    assert f"  RELEASE WINDOW NOT OPEN (deferring): {ref} — opens 2030-02-01" in output
    assert "nothing new to record" in output


def test_parse_ref_period_handles_all_dialects() -> None:
    cases = [
        (
            "bls.cps.unemployment_rate.june_2026.first_print",
            "bls.cps.unemployment_rate",
            ("month", "2026-06"),
        ),
        (
            "us.bea.core_pce.mom_sa.2026-05",
            "us.bea.core_pce.mom_sa",
            ("month", "2026-05"),
        ),
        (
            "bea.real_gdp.saar.q1_2026.third_estimate",
            "bea.real_gdp.saar",
            ("quarter", "2026-01"),
        ),
        (
            "bea.real_gdp.saar.2026_q3.advance_estimate",
            "bea.real_gdp.saar",
            ("quarter", "2026-07"),
        ),
        (
            "bls.cpi.u.annual_pct_change.2026",
            "bls.cpi.u.annual_pct_change",
            ("year", "2026"),
        ),
        (
            "census.official_poverty_rate.2025.first_print",
            "census.official_poverty_rate",
            ("year", "2025"),
        ),
    ]
    for ref, stem, expected in cases:
        assert resolve_pending.parse_ref_period(ref, stem) == expected
    assert (
        resolve_pending.parse_ref_period(
            "bls.cps.unemployment_rate.sometime", "bls.cps.unemployment_rate"
        )
        is None
    )


def test_parse_ref_period_handles_every_catalog_annual_id() -> None:
    # Inventory grep over the published registry/catalog as of this change.
    # New bare-year IDs deliberately make this ratchet fail until reviewed.
    expected = {
        "bea.gdpc1.q4q4.2026",
        "bls.cpi.u.annual_pct_change.2026",
        "census.acs.broadband_subscription_65_plus.share.2025.first_print",
        "census.asec.direct_purchase_coverage_rate.2025",
        "census.asec.median_household_income.2025",
        "census.asec.median_household_income.2026",
        "census.asec.uninsured_rate_under_65.2026",
        "census.asec.uninsured_rate_under_65.2028",
        "census.official_poverty_rate.2025",
        "census.spm.all_people_poverty_rate.2025",
        "census.spm.child_poverty_rate.2025",
        "census.spm.child_poverty_rate.2026",
        "census.spm.child_poverty_rate.2027",
        "census.spm.child_poverty_rate.2028",
        "census.spm.poverty_rate_65_plus.2025.first_print",
        "eia.ng.vented_flared.us.annual.2025.first_print",
        "hhs.aspe.poverty_guideline.household_size_4.48dc.2027",
        # Reviewed 2026-08-08: the three SBA custody-family fy2026 seeds
        # preregistered by the attested-lane mint; bare SBA years route
        # as fiscal_year through the registered contract
        # (test_bare_year_registration_routes_as_sba_fiscal_year).
        "sba.disaster.loan_program.charge_off_amount.2026.first_print",
        "sba.disaster.loan_program.charge_off_rate_upb.2026.first_print",
        ("sba.disaster.loan_program.post_charge_off_recovery.2026.first_print"),
        (
            "ssa.annual_statistical_supplement.table_6b5."
            "retired_worker_awards.share_claimed_age_62.2025.first_print"
        ),
        "ssa.cola.annual_adjustment.2027.first_print",
        "eia.ng.vented_flared.us.annual.2025.first_print",
    }
    generated = (
        ROOT / "site" / "src" / "data" / "ledger-targets.generated.ts"
    ).read_text()
    found = set(
        re.findall(
            r'dataPointId: "([^"]+\.\d{4}(?:\.first_print)?)"',
            generated,
        )
    )
    assert found == expected
    for ref in found:
        bare = re.sub(r"\.first_print$", "", ref)
        stem, year = bare.rsplit(".", 1)
        assert resolve_pending.parse_ref_period(ref, stem) == ("year", year)


def test_prior_period_date_supports_years_and_validates_shapes() -> None:
    assert resolve_pending.prior_period_date("2026", "year") == "2025"
    assert resolve_pending.prior_period_date("2026", "fiscal_year") == "2025"
    with pytest.raises(ValueError, match="must be YYYY"):
        resolve_pending.prior_period_date("2026-01", "year")


def test_apply_transform_level_diff_and_pct() -> None:
    rows = {"2026-05-01": 100.0, "2026-06-01": 102.0}
    assert (
        resolve_pending.apply_transform(
            rows, {"transform": "level"}, "month", "2026-06"
        )
        == 102.0
    )
    assert (
        resolve_pending.apply_transform(
            rows, {"transform": "mom_diff"}, "month", "2026-06"
        )
        == 2.0
    )
    assert (
        resolve_pending.apply_transform(
            rows, {"transform": "pct_change_1d"}, "month", "2026-06"
        )
        == 2.0
    )
    assert (
        resolve_pending.apply_transform(
            rows,
            {"transform": "level", "scale": 0.001, "round": 3},
            "month",
            "2026-06",
        )
        == 0.102
    )
    # Missing prior period fails closed rather than fabricating a change.
    assert (
        resolve_pending.apply_transform(
            {"2026-06-01": 102.0}, {"transform": "mom_diff"}, "month", "2026-06"
        )
        is None
    )


def test_value_plausibility_gate_blocks_scale_blunders() -> None:
    forecast = {"interval80": {"lower": 7.0, "upper": 8.0}}
    assert resolve_pending.value_plausible(7.5, forecast)
    assert resolve_pending.value_plausible(10.0, forecast)  # surprise, fine
    # thousands-vs-millions class: 1000x outside the interval is refused
    assert not resolve_pending.value_plausible(7594.0, forecast)
    assert resolve_pending.value_plausible(7594.0, {})  # no interval, no gate


def test_a19_parse_reads_current_month_column() -> None:
    # The real June 2026 table: each value is found by its headers (row,
    # "Total", "16 years and over", the later of two June headings), not by
    # its position. tests/test_a19_adapter.py covers the parser in depth.
    html = (
        ROOT / "tests/fixtures/a19/cpseea19-2026-06-wayback-20260710110509.table.html"
    ).read_text()
    values = resolve_pending.a19_values_from_html(html)
    assert values["healthcare_support"] == 5691.0
    assert values["production"] == 7759.0
    # A bare row of numbers names no month and no column: nothing is read.
    assert (
        resolve_pending.a19_values_from_html(
            "<table><tr><td>Production occupations</td><td>7,938</td>"
            "<td>7,759</td></tr></table>"
        )
        == {}
    )


def test_pending_adapter_refs_maps_and_gates_units() -> None:
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "a",
                "resolutionDate": "2026-07-02",
                "unit": "thousands",
                "interval80": {"lower": 35, "upper": 245},
            },
            {
                "kind": "prediction_recorded",
                "forecastSlug": "b",
                "resolutionDate": "2026-07-02",
                "unit": "percent",
                "interval80": {"lower": 4.1, "upper": 4.5},
            },
        ],
        "resolutionLinks": [
            {
                "status": "pending",
                "forecastSlug": "a",
                "targetFactRef": (
                    "bls.ces.total_nonfarm_payroll_change.june_2026.first_print"
                ),
            },
            {
                "status": "pending",
                "forecastSlug": "b",
                "targetFactRef": (
                    "bls.cps.employed_people_by_occupation.healthcare_support"
                    ".june_2026.first_print"
                ),
            },
            {
                "status": "pending",
                "forecastSlug": "b",
                "targetFactRef": "statcan.cpi.allitems.yoy.2026-05",
            },
        ],
    }
    todo = resolve_pending.pending_adapter_refs(log)
    refs = {item[0]: item for item in todo}
    assert "bls.ces.total_nonfarm_payroll_change.june_2026.first_print" in refs
    a19 = refs[
        "bls.cps.employed_people_by_occupation.healthcare_support.june_2026.first_print"
    ]
    assert a19[1] == "a19" and a19[4] == "2026-06"
    # International series route to the native-source adapters.
    intl = refs["statcan.cpi.allitems.yoy.2026-05"]
    assert intl[1] == "intl" and intl[4] == "2026-05"


def test_alfred_docket_templates_match_specs_and_route_by_cadence() -> None:
    entries = _alfred_docket_entries()
    # SOL-BRIEF's expansion should add roughly the size of the pre-existing
    # docket, not merely one or two token series.
    assert len(entries) >= 30

    forecasts = []
    links = []
    expected_periods = {}
    expected_specs = {}
    for index, entry in enumerate(entries):
        series = entry["series"]
        extras = entry["extras"]
        binding = extras["sourceBinding"]
        spec = resolve_pending.ALFRED_ADAPTERS[series]

        assert binding["sourceSeriesId"] == spec["fred"]
        assert binding["field"] == spec["fred"]
        assert binding["sourceUrl"] == (
            f"https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={spec['fred']}"
        )
        assert binding["table"] == spec["source_table"]
        assert binding["transform"] == {
            "operation": "multiply",
            "factor": spec.get("scale", 1),
        }
        assert extras.get("valueScale", 1) == spec.get("scale", 1)
        assert binding["releasePolicy"] == "first_print"
        assert extras["targetUnit"] == spec["unit"]

        cadence = entry["cadence"]
        assert cadence in {"monthly", "quarterly"}
        if cadence == "monthly":
            # This is the exact shape derive_data_point_id emits for a new
            # target whose registry period is 2030-06.
            ref = f"{series}.2030_06.first_print"
            expected_period = ("month", "2030-06")
        else:
            ref = f"{series}.2030_q2.first_print"
            expected_period = ("quarter", "2030-04")
        slug = f"alfred-docket-{index}"
        forecasts.append(
            {
                "kind": "prediction_recorded",
                "forecastSlug": slug,
                "resolutionDate": "2030-07-31",
                "unit": spec["unit"],
            }
        )
        links.append(
            {
                "status": "pending",
                "forecastSlug": slug,
                "targetFactRef": ref,
            }
        )
        expected_periods[ref] = expected_period
        expected_specs[ref] = spec

    routed = resolve_pending.pending_adapter_refs(
        {"entries": forecasts, "resolutionLinks": links}
    )
    assert len(routed) == len(entries)
    for ref, kind, spec, period_type, period, release_date, forecast in routed:
        assert kind == "alfred"
        assert (period_type, period) == expected_periods[ref]
        assert spec is expected_specs[ref]
        assert release_date == "2030-07-31"
        assert forecast["unit"] == spec["unit"]


def test_manifest_dedupes_shared_response_archives(tmp_path) -> None:
    original_root = resolve_pending.ROOT
    resolve_pending.ROOT = tmp_path
    try:
        run_dir = tmp_path / "records" / "resolutions" / "run"
        raw = b"date,value\n2026-05-01,1\n"
        archive = resolve_pending.archive_response(
            run_dir, series_id="PCEPILFE", vintage="2026-06-25", raw=raw
        )
        manifest = {
            "schemaVersion": "thesis_resolution_run_v1",
            "retrievedAt": "2026-07-10T12:00:00Z",
            "ledgerRepo": "PolicyEngine/chronicle",
            "ledgerBranch": "test",
            "ledgerRepoSha": "0" * 40,
            "facts": [
                {
                    "dataPointId": "bea.pce.core_mom.may_2026.first_print",
                    "sourceVintage": "2026-06-25",
                    "retrievedAt": "t",
                    "responseArchive": archive,
                },
                {
                    "dataPointId": "us.bea.core_pce.mom_sa.2026-05",
                    "sourceVintage": "2026-06-25",
                    "retrievedAt": "t",
                    "responseArchive": archive,
                },
            ],
        }
        sealed = resolve_pending.finalize_resolution_manifest(run_dir, manifest)
        responses = [
            ref
            for ref in sealed["artifacts"]
            if ref["artifactType"] == "resolver_response"
        ]
        assert len(responses) == 1
    finally:
        resolve_pending.ROOT = original_root


def test_write_side_rejects_a_fact_whose_unit_contradicts_its_contract() -> None:
    registration = {
        "targetContentHash": "a" * 64,
        "contract": {
            "dataPointId": "test.series.2030",
            "series": "test.series",
            "period": "2030",
            "unit": "thousands",
            "sourceBinding": {
                "releasePolicy": "advance_vintage",
                "table": "ALFRED graph CSV",
                "field": "TEST",
                "transform": {"operation": "multiply", "factor": 0.001},
            },
        },
        "ledgerPin": None,
    }
    row = {
        "source_record_id": "test.series.2030",
        "value": 1.5,
        "measure": {"concept": "test.series", "unit": "millions"},
    }

    try:
        resolve_pending.source_binding_projection(registration, row, b"raw")
    except ValueError as error:
        assert "millions" in str(error) and "thousands" in str(error)
    else:
        raise AssertionError("wrong-unit fact was not rejected at write time")


def test_write_side_rejects_a_fact_from_a_different_concept() -> None:
    # Finding 1: a row carrying the registered source_record_id but a
    # different measure concept (a different publisher/series) must not
    # stamp the registered projection.
    registration = {
        "targetContentHash": "a" * 64,
        "contract": {
            "dataPointId": "test.series.2030",
            "series": "test.series",
            "period": "2030",
            "unit": "thousands",
            "sourceBinding": {
                "releasePolicy": "advance_vintage",
                "table": "ALFRED graph CSV",
                "field": "TEST",
                "transform": {"operation": "multiply", "factor": 0.001},
                "allowedHosts": ["alfred.stlouisfed.org"],
            },
        },
        "ledgerPin": None,
    }
    wrong_concept = {
        "source_record_id": "test.series.2030",
        "value": 999.0,
        "measure": {"concept": "unrelated.other.series", "unit": "thousands"},
        "source": {"url": "https://alfred.stlouisfed.org/x"},
    }
    try:
        resolve_pending.source_binding_projection(registration, wrong_concept, b"x")
    except ValueError as error:
        assert "concept" in str(error)
    else:
        raise AssertionError("wrong-concept fact was not rejected")

    wrong_host = {
        "source_record_id": "test.series.2030",
        "value": 5.0,
        "measure": {"concept": "test.series", "unit": "thousands"},
        "source": {"url": "https://evil.example.com/x"},
    }
    try:
        resolve_pending.source_binding_projection(registration, wrong_host, b"x")
    except ValueError as error:
        assert "host" in str(error)
    else:
        raise AssertionError("novel-host fact was not rejected")


def test_registration_contracts_resolves_duplicates_to_published_hash(
    tmp_path,
) -> None:
    # Finding 9: two registrations for one dataPointId resolve to whichever
    # the published target committed, not lexical file order.
    records = tmp_path / "records" / "targets"
    records.mkdir(parents=True)
    dpid = "test.dup.series.2030"
    for series in ("a.series", "b.series"):
        contract = {
            "dataPointId": dpid,
            "series": series,
            "period": "2030",
            "unit": "count",
            "sourceBinding": {"releasePolicy": "first_print", "table": "t"},
        }
        snap = {"schemaVersion": "thesis_target_registration_v1", "targets": [contract]}
        ch = canonical_sha256(snap)
        (records / f"2030-01-01-{ch}.json").write_bytes(canonical_bytes(snap) + b"\n")
    # Determine the two hashes and publish the lexically-FIRST one.
    hashes = sorted(p.name[11:75] for p in records.glob("*.json"))
    published = hashes[0]
    generated = tmp_path / "generated.ts"
    generated.write_text(
        f'  {{\n    dataPointId: "{dpid}",\n'
        f'    targetContentHash: "{published}",\n  }},\n'
    )
    resolve_pending._PUBLISHED_TARGET_HASHES = None
    try:
        pub = resolve_pending.published_target_hashes(generated)
        resolve_pending._PUBLISHED_TARGET_HASHES = pub
        contracts = resolve_pending.registration_contracts(records)
    finally:
        resolve_pending._PUBLISHED_TARGET_HASHES = None
    assert contracts[dpid]["targetContentHash"] == published


def test_registration_contracts_scans_past_early_conflicts(tmp_path) -> None:
    # Supersede history retains every snapshot for a dataPointId, so the
    # published-matching registration can sort AFTER two non-matching ones
    # (production case: v1 + superseded v2 sorted before the published v3).
    # The pairwise scan must defer failure until the whole directory is read.
    records = tmp_path / "records" / "targets"
    records.mkdir(parents=True)
    dpid = "test.supersede.series.2030"
    hashes = []
    for day, series in (("01", "a.series"), ("01", "b.series"), ("02", "c.series")):
        contract = {
            "dataPointId": dpid,
            "series": series,
            "period": "2030",
            "unit": "count",
            "sourceBinding": {"releasePolicy": "first_print", "table": "t"},
        }
        snap = {"schemaVersion": "thesis_target_registration_v1", "targets": [contract]}
        ch = canonical_sha256(snap)
        hashes.append((f"2030-01-{day}-{ch}.json", ch))
        (records / hashes[-1][0]).write_bytes(canonical_bytes(snap) + b"\n")
    # Publish the file that sorts LAST.
    published = sorted(hashes)[-1][1]
    generated = tmp_path / "generated.ts"
    generated.write_text(
        f'  {{\n    dataPointId: "{dpid}",\n'
        f'    targetContentHash: "{published}",\n  }},\n'
    )
    resolve_pending._PUBLISHED_TARGET_HASHES = None
    try:
        pub = resolve_pending.published_target_hashes(generated)
        resolve_pending._PUBLISHED_TARGET_HASHES = pub
        contracts = resolve_pending.registration_contracts(records)
    finally:
        resolve_pending._PUBLISHED_TARGET_HASHES = None
    assert contracts[dpid]["targetContentHash"] == published


def test_registration_contracts_still_fails_closed_without_a_match(
    tmp_path,
) -> None:
    # If NO retained snapshot matches the published hash, the deferred check
    # must still refuse after the full scan.
    records = tmp_path / "records" / "targets"
    records.mkdir(parents=True)
    dpid = "test.orphaned.series.2030"
    for series in ("a.series", "b.series"):
        contract = {
            "dataPointId": dpid,
            "series": series,
            "period": "2030",
            "unit": "count",
            "sourceBinding": {"releasePolicy": "first_print", "table": "t"},
        }
        snap = {"schemaVersion": "thesis_target_registration_v1", "targets": [contract]}
        ch = canonical_sha256(snap)
        (records / f"2030-01-01-{ch}.json").write_bytes(canonical_bytes(snap) + b"\n")
    generated = tmp_path / "generated.ts"
    generated.write_text(
        f'  {{\n    dataPointId: "{dpid}",\n'
        f'    targetContentHash: "{"f" * 64}",\n  }},\n'
    )
    resolve_pending._PUBLISHED_TARGET_HASHES = None
    try:
        pub = resolve_pending.published_target_hashes(generated)
        resolve_pending._PUBLISHED_TARGET_HASHES = pub
        with pytest.raises(ValueError, match="neither registration"):
            resolve_pending.registration_contracts(records)
    finally:
        resolve_pending._PUBLISHED_TARGET_HASHES = None


BLS_DOD_PAYLOAD = {
    "status": "REQUEST_SUCCEEDED",
    "responseTime": 88,
    "message": [],
    "Results": {
        "series": [
            {
                "seriesID": "CES9091911001",
                "data": [
                    {
                        "year": "2026",
                        "period": "M05",
                        "periodName": "May",
                        "latest": "true",
                        "value": "476.2",
                        "footnotes": [{"code": "P", "text": "preliminary"}],
                    },
                    {
                        "year": "2026",
                        "period": "M04",
                        "periodName": "April",
                        "value": "476.6",
                        "footnotes": [{}],
                    },
                    {
                        "year": "2026",
                        "period": "M02",
                        "periodName": "February",
                        "value": "478.2",
                        "footnotes": [{}],
                    },
                    # Annual-average rows (M13) must never masquerade as
                    # a month.
                    {
                        "year": "2025",
                        "period": "M13",
                        "periodName": "Annual",
                        "value": "999.9",
                        "footnotes": [{}],
                    },
                    {
                        "year": "2025",
                        "period": "M12",
                        "periodName": "December",
                        "value": "490.1",
                        "footnotes": [{}],
                    },
                    {
                        "year": "2025",
                        "period": "M06",
                        "periodName": "June",
                        "value": "560.0",
                        "footnotes": [{}],
                    },
                ],
            }
        ]
    },
}


def test_bls_rows_parse_latest_and_preliminary_markers() -> None:
    import json as json_module

    raw = json_module.dumps(BLS_DOD_PAYLOAD).encode()
    rows = resolve_pending.bls_rows_from_payload(raw, "CES9091911001")

    assert rows["2026-05"] == {
        "value": 476.2,
        "latest": True,
        "preliminary": True,
    }
    assert rows["2026-04"] == {
        "value": 476.6,
        "latest": False,
        "preliminary": False,
    }
    assert "2025-13" not in rows and len(rows) == 5


def test_bls_rows_fail_closed_on_errors_and_wrong_series() -> None:
    import json as json_module

    raw = json_module.dumps(BLS_DOD_PAYLOAD).encode()
    assert resolve_pending.bls_rows_from_payload(raw, "CES3133640001") == {}
    error = json_module.dumps(
        {"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold"]}
    ).encode()
    assert resolve_pending.bls_rows_from_payload(error, "CES9091911001") == {}
    assert resolve_pending.bls_rows_from_payload(b"not json", "X") == {}


def test_bls_first_print_defers_absent_and_refuses_revised() -> None:
    rows = {
        "2026-05": {"value": 476.2, "latest": True, "preliminary": True},
        "2026-04": {"value": 476.6, "latest": False, "preliminary": False},
    }
    # June absent: not yet published, defer without refusing.
    assert resolve_pending.bls_first_print(rows, "2026-06") == (None, None)
    # May is the latest preliminary print: capture.
    value, refusal = resolve_pending.bls_first_print(rows, "2026-05")
    assert value == 476.2 and refusal is None
    # April is published but revised: refusing is the only honest option.
    value, refusal = resolve_pending.bls_first_print(rows, "2026-04")
    assert value is None and "first-print window" in refusal
    # An absent target stops deferring once a later period appears. This
    # distinguishes "not published yet" from a permanently missed/omitted
    # target and prevents a pending cell from rotting forever.
    later = {
        "2026-07": {
            "value": 477.0,
            "latest": True,
            "preliminary": True,
        }
    }
    value, refusal = resolve_pending.bls_first_print(later, "2026-06")
    assert value is None and "later period 2026-07" in refusal


def test_bls_anchor_gate_tolerates_revisions_but_not_wrong_series() -> None:
    anchors = {"2026-02": 478.2, "2026-04": 474.9}
    # CES revised April's first print 474.9 -> 476.6 (+0.36%): tolerated.
    revised = {
        "2026-02": {"value": 478.2, "latest": False, "preliminary": False},
        "2026-04": {"value": 476.6, "latest": False, "preliminary": False},
    }
    assert resolve_pending.bls_anchor_mismatches(revised, anchors) == []
    # A different series' history is far outside publication tolerance.
    wrong_series = {
        "2026-02": {"value": 579.9, "latest": False, "preliminary": False},
        "2026-04": {"value": 585.4, "latest": False, "preliminary": False},
    }
    problems = resolve_pending.bls_anchor_mismatches(wrong_series, anchors)
    assert len(problems) == 2
    # A missing anchor period is a mismatch, never silently skipped.
    assert resolve_pending.bls_anchor_mismatches({}, anchors) != []


@pytest.mark.parametrize(
    ("stem", "series_id"),
    [
        (
            "bls.ces.aerospace_product_and_parts_employment",
            "CES3133640001",
        ),
        (
            "bls.ces.ship_and_boat_building_employment",
            "CES3133660001",
        ),
        (
            "bls.ces.federal_department_of_defense_employment",
            "CES9091911001",
        ),
    ],
)
def test_pending_adapter_refs_maps_bls_defense_cells(stem: str, series_id: str) -> None:
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "dod",
                "resolutionDate": "2026-07-02",
                "unit": "thousands",
                "interval80": {"lower": 452, "upper": 501},
            },
        ],
        "resolutionLinks": [
            {
                "status": "pending",
                "forecastSlug": "dod",
                "targetFactRef": f"{stem}.june_2026.first_print",
            },
        ],
    }

    todo = resolve_pending.pending_adapter_refs(log)

    assert len(todo) == 1
    ref, kind, spec, period_type, period, release_date, forecast = todo[0]
    assert kind == "bls_api"
    assert spec["series_id"] == series_id
    # The main loop's unit-mismatch gate compares these two operands.
    assert spec["unit"] == forecast["unit"] == "thousands"
    assert (period_type, period) == ("month", "2026-06")
    assert release_date == "2026-07-02"


def _bls_rows_from_annual_averages(
    averages: dict[str, float],
) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for year, average in averages.items():
        for month in range(1, 13):
            rows[f"{year}-{month:02d}"] = {
                "value": average,
                "latest": False,
                "preliminary": False,
            }
    latest = max(rows)
    rows[latest]["latest"] = True
    return rows


def test_bls_annual_cpi_reproduces_official_anchors() -> None:
    # Live BLS annual-average index levels (also recorded in
    # docs/anchor-verifications.md).
    rows = _bls_rows_from_annual_averages(
        {
            "2021": 270.970,
            "2022": 292.655,
            "2023": 304.702,
            "2024": 313.689,
            "2025": 321.943,
        }
    )
    anchors = {"2022": 8.0, "2023": 4.1, "2024": 2.9, "2025": 2.6}
    assert resolve_pending.bls_annual_anchor_mismatches(rows, anchors) == []
    for year, expected in anchors.items():
        assert resolve_pending.bls_annual_average_pct_change(rows, year) == expected


def test_bls_annual_first_print_window_requires_complete_target_year() -> None:
    rows = _bls_rows_from_annual_averages({"2025": 321.943, "2026": 330.0})
    expected = round((330.0 / 321.943 - 1) * 100, 1)
    assert resolve_pending.bls_annual_first_print(rows, "2026") == (
        expected,
        None,
    )

    before_december = dict(rows)
    before_december.pop("2026-12")
    assert resolve_pending.bls_annual_first_print(before_december, "2026") == (
        None,
        None,
    )

    incomplete = dict(rows)
    incomplete.pop("2025-06")
    value, refusal = resolve_pending.bls_annual_first_print(incomplete, "2026")
    assert value is None and "24-month window is incomplete" in refusal

    after_window = {
        **rows,
        "2027-01": {
            "value": 331.0,
            "latest": True,
            "preliminary": False,
        },
    }
    value, refusal = resolve_pending.bls_annual_first_print(after_window, "2026")
    assert value is None and "2027-01 is now published" in refusal


def test_pending_adapter_refs_maps_annual_cpi_and_rejects_ces_year() -> None:
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "cpi",
                "resolutionDate": "2027-01-15",
                "unit": "percent",
            },
            {
                "kind": "prediction_recorded",
                "forecastSlug": "bad-ces",
                "resolutionDate": "2027-01-15",
                "unit": "thousands",
            },
        ],
        "resolutionLinks": [
            {
                "status": "pending",
                "forecastSlug": "cpi",
                "targetFactRef": "bls.cpi.u.annual_pct_change.2026",
            },
            {
                "status": "pending",
                "forecastSlug": "bad-ces",
                "targetFactRef": (
                    "bls.ces.federal_department_of_defense_employment.2026"
                ),
            },
        ],
    }

    todo = resolve_pending.pending_adapter_refs(log)

    assert len(todo) == 1
    ref, kind, spec, period_type, period, release_date, _ = todo[0]
    assert ref == "bls.cpi.u.annual_pct_change.2026"
    assert kind == "bls_api"
    assert spec["series_id"] == "CUUR0000SA0"
    assert spec["unit"] == "percent"
    assert (period_type, period) == ("year", "2026")
    assert release_date == "2027-01-15"


def test_generic_fact_preserves_calendar_year_period() -> None:
    ref = "bls.cpi.u.annual_pct_change.2026"
    spec = resolve_pending.BLS_API_ADAPTERS["bls.cpi.u.annual_pct_change"]
    fact = resolve_pending.generic_fact(
        ref,
        spec,
        "year",
        "2026",
        2.7,
        dt.date(2027, 1, 15),
        "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0",
        "timeseries/data (BLS Public Data API v2)",
    )
    assert fact["period"] == {"type": "year", "value": "2026"}


QCEW_AIRCRAFT_CSV = (
    '"area_fips","own_code","industry_code","agglvl_code","size_code",'
    '"year","qtr","disclosure_code","qtrly_estabs","month1_emplvl"\n'
    '"US000","0","336411","18","0","2025","3","","420","600000"\n'
    '"US000","5","336411","18","0","2025","3","","391","580000"\n'
    '"01000","5","336411","58","0","2025","3","N","7","10000"\n'
).encode()


def test_qcew_parser_selects_exact_national_private_aircraft_row() -> None:
    spec = resolve_pending.QCEW_ADAPTERS[
        "bls.qcew.aircraft_manufacturing.establishments"
    ]
    value, refusal = resolve_pending.qcew_value_from_csv(
        QCEW_AIRCRAFT_CSV, spec, "2025-07"
    )
    assert value == 391
    assert refusal is None
    assert resolve_pending.qcew_api_url(spec, "2025-07") == (
        "https://data.bls.gov/cew/data/api/2025/3/industry/336411.csv"
    )
    assert resolve_pending.qcew_source_series_id(spec, "2026-01") == (
        "area_fips=US000;own_code=5;industry_code=336411;size_code=0;year=2026;qtr=1"
    )


def test_qcew_parser_fails_closed_on_ambiguous_suppressed_or_bad_rows() -> None:
    spec = resolve_pending.QCEW_ADAPTERS[
        "bls.qcew.aircraft_manufacturing.establishments"
    ]
    duplicate = QCEW_AIRCRAFT_CSV + (
        b'"US000","5","336411","18","0","2025","3","","392","580000"\n'
    )
    value, refusal = resolve_pending.qcew_value_from_csv(duplicate, spec, "2025-07")
    assert value is None and "found 2" in refusal

    suppressed = QCEW_AIRCRAFT_CSV.replace(
        b'"US000","5","336411","18","0","2025","3","","391"',
        b'"US000","5","336411","18","0","2025","3","N","391"',
    )
    value, refusal = resolve_pending.qcew_value_from_csv(suppressed, spec, "2025-07")
    assert value is None and "not disclosed" in refusal

    unknown_disclosure = QCEW_AIRCRAFT_CSV.replace(
        b'"US000","5","336411","18","0","2025","3","","391"',
        b'"US000","5","336411","18","0","2025","3","X","391"',
    )
    value, refusal = resolve_pending.qcew_value_from_csv(
        unknown_disclosure, spec, "2025-07"
    )
    assert value is None and "disclosure_code='X'" in refusal

    non_integer = QCEW_AIRCRAFT_CSV.replace(b',"391",', b',"391.5",')
    value, refusal = resolve_pending.qcew_value_from_csv(non_integer, spec, "2025-07")
    assert value is None and "nonnegative integer" in refusal

    negative = QCEW_AIRCRAFT_CSV.replace(b',"391",', b',"-1",')
    value, refusal = resolve_pending.qcew_value_from_csv(negative, spec, "2025-07")
    assert value is None and "nonnegative integer" in refusal


def test_qcew_anchor_gate_requires_three_verified_values() -> None:
    assert resolve_pending.qcew_anchor_mismatches(
        {"2025-01": 388.0, "2025-04": 390.0},
        {"2025-01": 388.0, "2025-04": 390.0},
    ) == ["only 2 verified anchors; at least 3 required"]
    anchors = {"2025-01": 388.0, "2025-04": 390.0, "2025-07": 391.0}
    assert resolve_pending.qcew_anchor_mismatches(anchors, anchors) == []
    assert resolve_pending.qcew_anchor_mismatches(
        {**anchors, "2025-07": 999.0}, anchors
    ) == ["2025-07=999.0 (official 391.0)"]


def test_qcew_target_maps_and_the_anchor_gate_is_armed() -> None:
    ref = "bls.qcew.aircraft_manufacturing.establishments.2026_q1.first_print"
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "qcew-aircraft",
                "resolutionDate": "2026-08-28",
                "unit": "count",
            }
        ],
        "resolutionLinks": [
            {
                "status": "pending",
                "forecastSlug": "qcew-aircraft",
                "targetFactRef": ref,
            }
        ],
    }

    todo = resolve_pending.pending_adapter_refs(log)

    assert len(todo) == 1
    _, kind, spec, period_type, period, release_date, _ = todo[0]
    assert kind == "qcew"
    assert (period_type, period) == ("quarter", "2026-01")
    assert release_date == "2026-08-28"
    # Armed 2026-07-25: three live-verified anchors (see docs/anchor-verifications.md);
    # the runtime still re-fetches and re-compares them every run.
    assert resolve_pending.qcew_adapter_verified(spec)
    assert spec["anchor_status"] == "VERIFIED"
    assert len(spec["anchors"]) >= 3


def test_committed_qcew_aircraft_registration_projects_legacy_fact_end_to_end(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    ref = "bls.qcew.aircraft_manufacturing.establishments.2026_q1.first_print"
    series = "bls.qcew.aircraft_manufacturing.establishments"
    spec = resolve_pending.QCEW_ADAPTERS[series]
    registrations = resolve_pending.registration_contracts()
    registration = registrations[ref]
    binding = registration["contract"]["sourceBinding"]
    fetched_url = resolve_pending.qcew_api_url(spec, "2026-01")
    fact, archive_series_id = resolve_pending.qcew_resolution_fact(
        ref,
        spec,
        "quarter",
        "2026-01",
        395.0,
        dt.date(2026, 8, 28),
        binding,
        fetched_url,
    )
    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    run_dir = tmp_path / "records" / "resolutions" / "2026-08-28" / "run"
    run_dir.mkdir(parents=True)
    enriched = resolve_pending.attach_resolution_provenance(
        fact,
        run_dir=run_dir,
        series_id=archive_series_id,
        vintage="2026-08-28",
        raw=QCEW_AIRCRAFT_CSV,
        retrieved_at="2026-08-28T12:00:00Z",
        ledger_repo_sha="a" * 40,
        target_contracts={ref: registration},
    )

    assert fact["measure"]["concept"] == series
    assert fact["source"]["url"] == spec["source_page"]
    assert fact["source"]["source_file"] == fetched_url
    assert fact["filters"] == {}
    assert archive_series_id == "QCEW-US000-5-336411-0"
    assert enriched["sourceBindingProjection"]["concept"] == series
    assert enriched["sourceBindingProjection"]["sourceUrl"] == spec["source_page"]
    archive_path = tmp_path / enriched["responseArchive"]["path"]
    assert enriched["responseArchive"]["path"] == (
        "records/resolutions/2026-08-28/run/responses/"
        "qcew-us000-5-336411-0-2026-08-28-8ccce2d861809422.csv.gz"
    )
    assert gzip.decompress(archive_path.read_bytes()) == QCEW_AIRCRAFT_CSV


def test_qcew_legacy_aircraft_registration_remains_exactly_supported() -> None:
    path = ROOT / (
        "records/targets/2026-07-15-"
        "4ba53e4d70d019614a40a1f6457f28261d01d46e5b05373f661a5c9566864d09.json"
    )
    snapshot = json.loads(path.read_text())
    contract = snapshot["targets"][0]
    spec = resolve_pending.QCEW_ADAPTERS[
        "bls.qcew.aircraft_manufacturing.establishments"
    ]
    binding = contract["sourceBinding"]

    assert resolve_pending.qcew_binding_matches_spec(
        binding, spec, "2026-01", dt.date(2026, 8, 28)
    )
    tampered = json.loads(json.dumps(binding))
    tampered["field"] = "month1_emplvl"
    assert not resolve_pending.qcew_binding_matches_spec(
        tampered, spec, "2026-01", dt.date(2026, 8, 28)
    )


@pytest.mark.parametrize("variant", ["aircraft", "annual"])
def test_main_qcew_branch_builds_and_projects_the_registered_fact(
    variant: str,
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    if variant == "aircraft":
        ref = "bls.qcew.aircraft_manufacturing.establishments.2026_q1.first_print"
        series = "bls.qcew.aircraft_manufacturing.establishments"
        period_type, period = "quarter", "2026-01"
        release_date, value = "2026-08-28", 1400.0
        registration = resolve_pending.registration_contracts()[ref]
        raw = QCEW_AIRCRAFT_CSV
        expected_url = "https://www.bls.gov/cew/downloadable-data-files.htm"
        expected_filters = {}
        expected_archive_stem = "qcew-us000-5-336411-0-"
    else:
        series = "bls.qcew.child_day_care_services.annual_avg_employment"
        ref = f"{series}.2025.first_print"
        period_type, period = "year", "2025"
        release_date, value = "2026-06-02", 991735.0
        docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())[
            "series"
        ]
        entry = next(item for item in docket if item["series"] == series)
        target = {
            "series": series,
            "period": period,
            "seedPeriod": period,
            "catalogSlug": "us-private-child-day-care-2025",
            **entry["extras"],
            "expectedReleaseDate": release_date,
            "releaseCalendarUrl": entry["releaseCalendarUrl"],
        }
        contract = register_targets.build_contract(target, dt.date(2026, 6, 1))
        registration = {
            "targetContentHash": "b" * 64,
            "contract": contract,
            "ledgerPin": None,
        }
        raw = (
            ROOT
            / "tests"
            / "fixtures"
            / "qcew"
            / "child_day_care_services_2025_annual.csv"
        ).read_bytes()
        expected_url = resolve_pending.qcew_api_url(
            resolve_pending.QCEW_ADAPTERS[series], period
        )
        expected_filters = {
            "area_fips": "US000",
            "own_code": "5",
            "industry_code": "624410",
            "agglvl_code": "18",
            "size_code": "0",
            "qtr": "A",
        }
        expected_archive_stem = "qcew-us000-5-624410-18-0-annual_avg_emplvl-"

    spec = resolve_pending.QCEW_ADAPTERS[series]
    registrations = {ref: registration}
    forecast = {"unit": "count", "resolutionDate": release_date}
    docket_payload = {
        "series": [
            {
                "series": series,
                "releaseCalendarUrl": spec.get("release_calendar_url"),
                "releaseDates": {period: release_date},
            }
        ]
    }
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "docket_series.json").write_text(json.dumps(docket_payload))

    real_date = dt.date

    class ReleaseDate(real_date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(release_date)

    def fake_qcew_fetch(fetch_spec, fetch_period):
        fetched_value = fetch_spec["anchors"].get(fetch_period, value)
        return (
            float(fetched_value),
            raw,
            resolve_pending.qcew_api_url(fetch_spec, fetch_period),
            f"{release_date}T12:00:00Z",
            None,
        )

    appended: dict[str, str] = {}

    def fake_propose(
        _repo,
        _branch,
        _path,
        content,
        _blob_sha,
        _base_sha,
        _added,
        **_kwargs,
    ):
        appended["content"] = content
        return "d" * 40

    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    monkeypatch.setattr(resolve_pending.dt, "date", ReleaseDate)
    monkeypatch.setattr(
        resolve_pending,
        "load_thesis_log",
        lambda _url: {"entries": [], "resolutionLinks": []},
    )
    monkeypatch.setattr(resolve_pending, "pending_claims_refs", lambda _log: [])
    monkeypatch.setattr(
        resolve_pending,
        "pending_adapter_refs",
        lambda _log: [
            (
                ref,
                "qcew",
                spec,
                period_type,
                period,
                release_date,
                forecast,
            )
        ],
    )
    monkeypatch.setattr(
        resolve_pending,
        "ledger_state",
        lambda *_args: ("", "blob", "c" * 40),
    )
    monkeypatch.setattr(
        resolve_pending, "registration_contracts", lambda: registrations
    )
    monkeypatch.setattr(resolve_pending, "qcew_fetch_period", fake_qcew_fetch)
    monkeypatch.setattr(
        resolve_pending,
        "utc_now",
        lambda: f"{release_date}T12:00:00Z",
    )
    monkeypatch.setattr(resolve_pending, "propose_ledger_append", fake_propose)
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py"])

    assert resolve_pending.main() == 0
    rows = [
        json.loads(line) for line in appended["content"].splitlines() if line.strip()
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["source"]["url"] == expected_url
    assert row["measure"]["concept_evidence_url"] == expected_url
    assert row["sourceBindingProjection"]["sourceUrl"] == expected_url
    assert row["filters"] == expected_filters
    archive_name = pathlib.PurePosixPath(row["responseArchive"]["path"]).name
    assert archive_name.startswith(expected_archive_stem)


def test_main_qcew_branch_refuses_registered_window_drift_before_side_effects(
    tmp_path: pathlib.Path,
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    series = "bls.qcew.child_day_care_services.annual_avg_employment"
    ref = f"{series}.2025.first_print"
    period = "2025"
    release_date = "2026-06-02"
    spec = resolve_pending.QCEW_ADAPTERS[series]
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = next(item for item in docket["series"] if item["series"] == series)
    target = {
        "series": series,
        "period": period,
        "seedPeriod": period,
        "catalogSlug": "us-private-child-day-care-2025",
        **entry["extras"],
        "expectedReleaseDate": release_date,
        "releaseCalendarUrl": entry["releaseCalendarUrl"],
    }
    contract = register_targets.build_contract(target, dt.date(2026, 6, 1))
    contract["sourceBinding"]["expectedReleaseWindow"] = {
        "start": "2026-06-03",
        "end": "2026-06-03",
    }
    snapshot = {
        "schemaVersion": register_targets.V2_REGISTRATION_SCHEMA,
        "registeredAtUtc": "2026-06-01T12:00:00Z",
        "targets": [contract],
    }
    content_hash = register_targets.registration_content_hash(snapshot)
    targets_dir = tmp_path / "records" / "targets"
    targets_dir.mkdir(parents=True)
    (targets_dir / f"2026-06-01-{content_hash}.json").write_bytes(
        canonical_bytes(snapshot) + b"\n"
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "docket_series.json").write_text(
        json.dumps({"series": [entry]})
    )

    real_date = dt.date

    class ReleaseDate(real_date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(release_date)

    def unexpected_side_effect(*_args, **_kwargs):
        pytest.fail(
            "registered-window refusal must precede fetch, fact construction, "
            "archive, and append"
        )

    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    monkeypatch.setattr(resolve_pending.dt, "date", ReleaseDate)
    monkeypatch.setattr(
        resolve_pending,
        "load_thesis_log",
        lambda _url: {"entries": [], "resolutionLinks": []},
    )
    monkeypatch.setattr(resolve_pending, "pending_claims_refs", lambda _log: [])
    monkeypatch.setattr(
        resolve_pending,
        "pending_adapter_refs",
        lambda _log: [
            (
                ref,
                "qcew",
                spec,
                "year",
                period,
                release_date,
                {"unit": "count", "resolutionDate": release_date},
            )
        ],
    )
    monkeypatch.setattr(
        resolve_pending,
        "ledger_state",
        lambda *_args: ("", "blob", "c" * 40),
    )
    monkeypatch.setattr(resolve_pending, "qcew_fetch_period", unexpected_side_effect)
    monkeypatch.setattr(resolve_pending, "qcew_resolution_fact", unexpected_side_effect)
    monkeypatch.setattr(resolve_pending, "archive_response", unexpected_side_effect)
    monkeypatch.setattr(
        resolve_pending, "propose_ledger_append", unexpected_side_effect
    )
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py"])

    assert resolve_pending.main() == 0
    output = capsys.readouterr().out
    assert f"BINDING/ADAPTER MISMATCH (refusing, registry drift?): {ref}" in output
    assert "nothing new to record" in output
    assert f"resolve {ref} ->" not in output
    assert not (tmp_path / "records" / "resolutions").exists()


def test_main_qcew_branch_refuses_next_day_completed_fetch(
    tmp_path: pathlib.Path,
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    series = "bls.qcew.child_day_care_services.annual_avg_employment"
    ref = f"{series}.2025.first_print"
    period = "2025"
    release_date = "2026-06-02"
    completed_at = "2026-06-03T00:00:01Z"
    spec = resolve_pending.QCEW_ADAPTERS[series]
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = next(item for item in docket["series"] if item["series"] == series)
    target = {
        "series": series,
        "period": period,
        "seedPeriod": period,
        "catalogSlug": "us-private-child-day-care-2025",
        **entry["extras"],
        "expectedReleaseDate": release_date,
        "releaseCalendarUrl": entry["releaseCalendarUrl"],
    }
    contract = register_targets.build_contract(target, dt.date(2026, 6, 1))
    registrations = {
        ref: {
            "targetContentHash": "b" * 64,
            "contract": contract,
            "ledgerPin": None,
        }
    }
    raw = (
        ROOT / "tests" / "fixtures" / "qcew" / "child_day_care_services_2025_annual.csv"
    ).read_bytes()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "docket_series.json").write_text(
        json.dumps({"series": [entry]})
    )

    real_date = dt.date

    class ReleaseDate(real_date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(release_date)

    fetched_periods: list[str] = []

    def fake_qcew_fetch(fetch_spec, fetch_period):
        fetched_periods.append(fetch_period)
        return (
            float(fetch_spec["anchors"][fetch_period]),
            raw,
            resolve_pending.qcew_api_url(fetch_spec, fetch_period),
            completed_at,
            None,
        )

    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    monkeypatch.setattr(resolve_pending.dt, "date", ReleaseDate)
    monkeypatch.setattr(
        resolve_pending,
        "load_thesis_log",
        lambda _url: {"entries": [], "resolutionLinks": []},
    )
    monkeypatch.setattr(resolve_pending, "pending_claims_refs", lambda _log: [])
    monkeypatch.setattr(
        resolve_pending,
        "pending_adapter_refs",
        lambda _log: [
            (
                ref,
                "qcew",
                spec,
                "year",
                period,
                release_date,
                {"unit": "count", "resolutionDate": release_date},
            )
        ],
    )
    monkeypatch.setattr(
        resolve_pending,
        "ledger_state",
        lambda *_args: ("", "blob", "c" * 40),
    )
    monkeypatch.setattr(
        resolve_pending, "registration_contracts", lambda: registrations
    )
    monkeypatch.setattr(resolve_pending, "qcew_fetch_period", fake_qcew_fetch)
    monkeypatch.setattr(resolve_pending, "utc_now", lambda: completed_at)
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])

    assert resolve_pending.main() == 0
    output = capsys.readouterr().out
    assert fetched_periods == list(spec["anchors"])
    assert (
        f"FIRST-PRINT WINDOW MISSED (refusing): {ref} — QCEW response "
        "completed on 2026-06-03, after registered release day 2026-06-02"
    ) in output
    assert "nothing new to record" in output
    assert "dry-run: would append" not in output


def test_main_qcew_branch_refuses_joint_calendar_page_and_date_drift(
    tmp_path: pathlib.Path,
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    series = "bls.qcew.child_day_care_services.annual_avg_employment"
    ref = f"{series}.2025.first_print"
    period = "2025"
    release_date = "2026-06-03"
    spec = resolve_pending.QCEW_ADAPTERS[series]
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    canonical_entry = next(
        item for item in docket["series"] if item["series"] == series
    )
    entry = json.loads(json.dumps(canonical_entry))
    entry["period"] = entry["seedPeriod"] = period
    entry["releaseCalendarUrl"] = "https://www.bls.gov/schedule/news_release/cewqtr.htm"
    entry["releaseDates"][period] = release_date
    target = {
        "series": series,
        "period": period,
        "seedPeriod": period,
        "catalogSlug": "us-private-child-day-care-2025",
        **entry["extras"],
        "expectedReleaseDate": release_date,
        "releaseCalendarUrl": entry["releaseCalendarUrl"],
    }
    contract = register_targets.build_contract(target, dt.date(2026, 6, 1))
    registration = {
        "targetContentHash": "b" * 64,
        "contract": contract,
        "ledgerPin": None,
    }
    binding = contract["sourceBinding"]
    assert resolve_pending.qcew_binding_matches_spec(
        binding, spec, period, dt.date.fromisoformat(release_date)
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "docket_series.json").write_text(
        json.dumps({"series": [entry]})
    )

    real_date = dt.date

    class ReleaseDate(real_date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(release_date)

    def unexpected_qcew_fetch(*_args, **_kwargs):
        pytest.fail("calendar-authority refusal must happen before any QCEW fetch")

    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    monkeypatch.setattr(resolve_pending.dt, "date", ReleaseDate)
    monkeypatch.setattr(
        resolve_pending,
        "load_thesis_log",
        lambda _url: {"entries": [], "resolutionLinks": []},
    )
    monkeypatch.setattr(resolve_pending, "pending_claims_refs", lambda _log: [])
    monkeypatch.setattr(
        resolve_pending,
        "pending_adapter_refs",
        lambda _log: [
            (
                ref,
                "qcew",
                spec,
                "year",
                period,
                release_date,
                {"unit": "count", "resolutionDate": release_date},
            )
        ],
    )
    monkeypatch.setattr(
        resolve_pending,
        "ledger_state",
        lambda *_args: ("", "blob", "c" * 40),
    )
    monkeypatch.setattr(
        resolve_pending, "registration_contracts", lambda: {ref: registration}
    )
    monkeypatch.setattr(resolve_pending, "qcew_fetch_period", unexpected_qcew_fetch)
    monkeypatch.setattr(
        resolve_pending,
        "utc_now",
        lambda: f"{release_date}T12:00:00Z",
    )
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])

    assert resolve_pending.main() == 0
    output = capsys.readouterr().out
    assert f"BINDING/ADAPTER MISMATCH (refusing, registry drift?): {ref}" in output
    assert "nothing new to record" in output


def test_projection_refusal_writes_no_orphan_archive_in_a_mixed_run(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    run_dir = tmp_path / "records" / "resolutions" / "2030-01-02" / "run"
    run_dir.mkdir(parents=True)

    def registration(ref: str, series: str) -> dict:
        return {
            "targetContentHash": "a" * 64,
            "contract": {
                "dataPointId": ref,
                "series": series,
                "period": "2030",
                "unit": "count",
                "sourceBinding": {
                    "allowedHosts": ["official.example"],
                    "releasePolicy": "first_print",
                    "table": "Official table",
                    "field": "value",
                    "transform": {"operation": "identity", "factor": 1},
                },
            },
            "ledgerPin": None,
        }

    good_ref = "test.good.2030.first_print"
    bad_ref = "test.bad.2030.first_print"
    contracts = {
        good_ref: registration(good_ref, "test.good"),
        bad_ref: registration(bad_ref, "test.bad"),
    }
    good_row = {
        "source_record_id": good_ref,
        "measure": {"concept": "test.good", "unit": "count"},
        "source": {"url": "https://official.example/good.csv"},
    }
    bad_row = {
        "source_record_id": bad_ref,
        "measure": {"concept": "test.bad", "unit": "count"},
        "source": {"url": "https://wrong.example/bad.csv"},
    }
    good = resolve_pending.attach_resolution_provenance(
        good_row,
        run_dir=run_dir,
        series_id="good",
        vintage="2030-01-02",
        raw=b"good\n",
        retrieved_at="2030-01-02T12:00:00Z",
        ledger_repo_sha="b" * 40,
        target_contracts=contracts,
    )
    with pytest.raises(ValueError, match="wrong.example"):
        resolve_pending.attach_resolution_provenance(
            bad_row,
            run_dir=run_dir,
            series_id="bad",
            vintage="2030-01-02",
            raw=b"bad\n",
            retrieved_at="2030-01-02T12:00:01Z",
            ledger_repo_sha="b" * 40,
            target_contracts=contracts,
        )

    response_paths = list((run_dir / "responses").glob("*"))
    assert response_paths == [tmp_path / good["responseArchive"]["path"]]
    manifest = resolve_pending.finalize_resolution_manifest(
        run_dir,
        {
            "schemaVersion": "thesis_resolution_run_v1",
            "retrievedAt": "2030-01-02T12:00:00Z",
            "ledgerRepo": "PolicyEngine/chronicle",
            "ledgerBranch": "test",
            "ledgerRepoSha": "b" * 40,
            "facts": [
                {
                    "dataPointId": good_ref,
                    "sourceVintage": good["sourceVintage"],
                    "retrievedAt": good["retrievedAt"],
                    "targetContentHash": good["targetContentHash"],
                    "responseArchive": good["responseArchive"],
                }
            ],
        },
    )
    assert manifest["ok"] is True
    assert verify_run(run_dir).inventory_status == "complete"


def test_bls_json_archive_passes_custody_verification(tmp_path) -> None:
    import json as json_module

    original_root = resolve_pending.ROOT
    resolve_pending.ROOT = tmp_path
    try:
        run_dir = tmp_path / "records" / "resolutions" / "run"
        raw = json_module.dumps(BLS_DOD_PAYLOAD).encode()
        archive = resolve_pending.archive_response(
            run_dir,
            series_id="CES9091911001",
            vintage="2026-08-07",
            raw=raw,
            extension="json",
        )
        assert archive["path"].endswith(".json.gz")
        manifest = resolve_pending.finalize_resolution_manifest(
            run_dir,
            {
                "schemaVersion": "thesis_resolution_run_v1",
                "retrievedAt": "2026-08-07T13:40:00Z",
                "ledgerRepo": "PolicyEngine/chronicle",
                "ledgerBranch": "test",
                "ledgerRepoSha": "0" * 40,
                "facts": [
                    {
                        "dataPointId": (
                            "bls.ces.federal_department_of_defense_employment"
                            ".june_2026.first_print"
                        ),
                        "sourceVintage": "2026-08-07",
                        "retrievedAt": "2026-08-07T13:40:00Z",
                        "responseArchive": archive,
                    }
                ],
            },
        )
        result = verify_run(run_dir)
        assert result.inventory_status == "complete"
        assert manifest["ok"] is True
    finally:
        resolve_pending.ROOT = original_root


def test_assertion_version_changes_when_the_value_changes() -> None:
    row = {
        "source_record_id": "test.series.2030",
        "value": 1.5,
        "observed_at": "2030-01-10",
        "period": {"type": "month", "value": "2030-01"},
        "measure": {"concept": "test.series", "unit": "millions"},
        "source": {"source_name": "test", "vintage": "advance"},
    }

    original = resolve_pending.assertion_version(row)
    corrected = resolve_pending.assertion_version({**row, "value": 2.5})

    assert original["id"].startswith("av2:")
    assert original["id"] != corrected["id"]


def _local_timestamp_requester(
    tsa_root: pathlib.Path,
    *,
    signer_overrides: dict[str, str] | None = None,
):
    endpoint_slots = {
        endpoint: slot for slot, endpoint in resolve_pending.TSA_ENDPOINTS.items()
    }
    counter = 0

    def request(endpoint: str, query: bytes, _timeout_seconds: float) -> bytes:
        nonlocal counter
        counter += 1
        slot = endpoint_slots[endpoint]
        signer = (signer_overrides or {}).get(slot, slot)
        query_path = tsa_root / f"request-{counter}.tsq"
        receipt_path = tsa_root / f"response-{counter}.tsr"
        query_path.write_bytes(query)
        subprocess.run(
            [
                "openssl",
                "ts",
                "-reply",
                "-config",
                "openssl-ts.cnf",
                "-queryfile",
                str(query_path),
                "-out",
                str(receipt_path),
            ],
            cwd=tsa_root / signer,
            check=True,
            capture_output=True,
            text=True,
        )
        return receipt_path.read_bytes()

    return request


def _generate_test_producer_keypair(
    root: pathlib.Path,
) -> tuple[pathlib.Path, str]:
    private_key = root / "producer-test-private.pem"
    public_key = root / "anchors" / "producer-ed25519.pub"
    subprocess.run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "ED25519",
            "-out",
            str(private_key),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return private_key, private_key.read_text()


def _sign_test_manifest(
    root: pathlib.Path,
    private_key: pathlib.Path,
    manifest: bytes,
) -> bytes:
    manifest_path = root / "producer-genesis-manifest.json"
    signature_path = root / "producer-genesis.sig"
    manifest_path.write_bytes(manifest)
    subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-inkey",
            str(private_key),
            "-rawin",
            "-in",
            str(manifest_path),
            "-out",
            str(signature_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return signature_path.read_bytes()


def _fake_catalog_generator() -> bytes:
    return b"""#!/usr/bin/env python3
import hashlib
import json
import pathlib
import sys

# Mirror the real generator's import topology: build_series_catalog imports
# check_thesis_facts_append, which imports the consumer-owned receipt_pins.
# A staging omission of either module must fail these tests the way it would
# fail a real witnessed append.
sys.path.insert(0, str(pathlib.Path.cwd() / "scripts"))
import check_thesis_facts_append  # noqa: F401

root = pathlib.Path.cwd()
ledger = (root / "ledger" / "official_observations.jsonl").read_bytes()
registry = (root / "ledger" / "series_uuid_registry.jsonl").read_bytes()
# The real generator reads the docket seed unconditionally; a staging
# omission must fail here the way it would fail a real append.
(root / "ledger" / "seeds" / "thesis_docket_series.json").read_bytes()
catalog_path = root / "ledger" / "series_catalog.json"
catalog = json.loads(catalog_path.read_text())
catalog["observations_sha256"] = hashlib.sha256(ledger).hexdigest()
catalog["observation_rows"] = len(
    [line for line in ledger.splitlines() if line.strip()]
)
catalog["uuid_registry_sha256"] = hashlib.sha256(registry).hexdigest()
catalog_path.write_text(json.dumps(catalog, sort_keys=True) + "\\n")
print("minted=0 superseded=0")
"""


def _release_fixture_tree(
    tmp_path: pathlib.Path,
) -> tuple[
    resolve_pending.RepositoryTree,
    pathlib.Path,
    resolve_pending.TimestampRequester,
    str,
]:
    tsa_root = tmp_path / "release_tsa"
    shutil.copytree(ROOT / "tests" / "fixtures" / "release_tsa", tsa_root)
    anchor_dir = tsa_root / "anchors"
    producer_private_key, signing_key_pem = _generate_test_producer_keypair(tsa_root)
    requester = _local_timestamp_requester(tsa_root)
    ledger = b'{"source_record_id":"fixture.base","value":0}\n'
    registry = b'{"uuid":"00000000-0000-4000-8000-000000000001"}\n'
    catalog = (
        json.dumps(
            {
                "generator_version": 3,
                "observations_sha256": hashlib.sha256(ledger).hexdigest(),
                "observation_rows": 1,
                "uuid_registry_sha256": hashlib.sha256(registry).hexdigest(),
                "series": [],
            },
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    immutable_prefix = b'{"prefixLineCount":0}\n'
    created_at = (
        (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=2))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    manifest = {
        "schemaVersion": "thesis_ledger_release_v1",
        "releaseIndex": 0,
        "previousManifestSha256": None,
        "state": {
            "path": "ledger/official_observations.jsonl",
            "jsonlSha256": hashlib.sha256(ledger).hexdigest(),
            "lineCount": 1,
            "immutablePrefixSha256": hashlib.sha256(immutable_prefix).hexdigest(),
        },
        "append": None,
        "createdAtUtc": created_at,
        "producer": {"repo": "PolicyEngine/chronicle", "branch": "fixture"},
    }
    manifest_raw = canonical_bytes(manifest) + b"\n"
    manifest_name = ledger_release_chain.manifest_filename(0, manifest_raw)
    producer_signature = _sign_test_manifest(
        tsa_root,
        producer_private_key,
        manifest_raw,
    )
    query = resolve_pending._build_timestamp_query(manifest_raw, 10)
    receipts = {
        slot: requester(endpoint, query, 10)
        for slot, endpoint in resolve_pending.TSA_ENDPOINTS.items()
    }
    manifest_path = f"releases/manifests/{manifest_name}"
    files = {
        "ledger/official_observations.jsonl": ledger,
        "ledger/immutable_prefix.json": immutable_prefix,
        "ledger/series_uuid_registry.jsonl": registry,
        "ledger/series_catalog.json": catalog,
        "scripts/build_series_catalog.py": _fake_catalog_generator(),
        "scripts/check_thesis_facts_append.py": (
            b"import receipt_pins  # noqa: F401  (real gate reads pin config)\n"
        ),
        "scripts/receipt_pins.py": b"APPEND_GATE_SPEC = None\nLEDGER_SPEC = None\n",
        "ledger/seeds/thesis_docket_series.json": b"[]\n",
        manifest_path: manifest_raw,
        **{
            f"releases/manifests/{pathlib.PurePosixPath(manifest_name).stem}."
            f"{slot}.tsr": receipt
            for slot, receipt in receipts.items()
        },
        (
            "releases/manifests/"
            f"{pathlib.PurePosixPath(manifest_name).stem}.producer.sig"
        ): producer_signature,
        **{
            f"releases/anchors/{anchor.name}": anchor.read_bytes()
            for anchor in anchor_dir.iterdir()
        },
    }
    return (
        resolve_pending.RepositoryTree(
            tree_sha="1" * 40,
            files=files,
            modes={relative: "100644" for relative in files},
            blob_shas={relative: "a" * 40 for relative in files},
        ),
        anchor_dir,
        requester,
        signing_key_pem,
    )


def _pre_genesis_tree() -> resolve_pending.RepositoryTree:
    path = "ledger/official_observations.jsonl"
    files = {path: b'{"source_record_id":"fixture.base","value":0}\n'}
    return resolve_pending.RepositoryTree(
        tree_sha="1" * 40,
        files=files,
        modes={path: "100644"},
        blob_shas={path: "a" * 40},
    )


def _proposal_api_stub(
    gate_conclusion: str,
    calls: list[tuple[tuple[str, ...], dict | None]],
    *,
    fail_ref_creation: bool = False,
    fail_pr_creation: bool = False,
    recover_pr_number: int | None = None,
    merge_payload: dict | None = None,
):
    merged = False

    def api(*args: str, input_body=None) -> str:
        nonlocal merged
        calls.append((args, input_body))
        joined = " ".join(args)
        if "/git/refs" in joined and "POST" in args:
            if fail_ref_creation:
                raise RuntimeError("simulated ref creation failure")
            return "{}"
        if "/git/ref/heads/" in joined:
            return json.dumps({"object": {"sha": "c" * 40}})
        if "/pulls?state=open" in joined:
            return json.dumps(
                [] if recover_pr_number is None else [{"number": recover_pr_number}]
            )
        if joined.endswith("/pulls") and "POST" in args:
            if fail_pr_creation:
                raise RuntimeError("simulated PR creation failure")
            return json.dumps({"number": 7})
        if "/check-runs" in joined:
            return json.dumps(
                {
                    "check_runs": [
                        {
                            "name": "Append gate",
                            "status": "completed",
                            "conclusion": gate_conclusion,
                        }
                    ]
                }
            )
        if "/merge" in joined:
            result = (
                merge_payload
                if merge_payload is not None
                else {"merged": True, "sha": "d" * 40}
            )
            if type(result) is dict and result.get("merged") is True:
                merged = True
            return json.dumps(result)
        if joined.endswith("/pulls/7") and "PATCH" not in args:
            return json.dumps(
                {
                    "merged": merged,
                    "merge_commit_sha": "d" * 40 if merged else None,
                    "head": {"sha": "c" * 40},
                    "base": {
                        "ref": "codex/thesis-ledger-facts",
                        "sha": "b" * 40,
                    },
                }
            )
        if "PATCH" in args or "DELETE" in args:
            return "{}"
        raise AssertionError(f"unexpected gh call: {joined}")

    return api


def _install_proposal_transport(
    monkeypatch,
    tree: resolve_pending.RepositoryTree,
    calls: list[tuple[tuple[str, ...], dict | None]],
    *,
    gate_conclusion: str = "success",
    fail_ref_creation: bool = False,
    fail_pr_creation: bool = False,
    recover_pr_number: int | None = None,
    merge_payload: dict | None = None,
    published: list[dict[str, bytes]] | None = None,
) -> None:
    monkeypatch.setattr(resolve_pending, "_fetch_repository_tree", lambda *_: tree)

    def publish(*_args, changes, **_kwargs):
        if published is not None:
            published.append(dict(changes))
        return "c" * 40

    monkeypatch.setattr(resolve_pending, "_publish_proposal_commit", publish)
    monkeypatch.setattr(resolve_pending, "_branch_head", lambda *_: "b" * 40)
    monkeypatch.setattr(
        resolve_pending,
        "_verify_remote_proposal_state",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        resolve_pending,
        "_gh_api",
        _proposal_api_stub(
            gate_conclusion,
            calls,
            fail_ref_creation=fail_ref_creation,
            fail_pr_creation=fail_pr_creation,
            recover_pr_number=recover_pr_number,
            merge_payload=merge_payload,
        ),
    )


def test_append_proposal_builds_byte_correct_verified_release(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    tree, anchor_dir, requester, signing_key_pem = _release_fixture_tree(tmp_path)
    monkeypatch.setenv(resolve_pending.PRODUCER_SIGNING_KEY_ENV, signing_key_pem)
    calls: list[tuple[tuple[str, ...], dict | None]] = []
    published: list[dict[str, bytes]] = []
    _install_proposal_transport(monkeypatch, tree, calls, published=published)
    real_verify = resolve_pending.verify_release_chain
    real_verify_signature = resolve_pending.verify_producer_signature_bytes
    verify_calls: list[dict] = []
    signature_anchor_checks: list[bytes] = []

    def tracking_verify(*args, **kwargs):
        verify_calls.append(dict(kwargs))
        # Test keys intentionally do not match production code pins. Keeping
        # anchor_dir unset in the proposal call exercises the production path:
        # the anchor must come from the staged immutable base tree.
        kwargs["enforce_production_pins"] = False
        return real_verify(*args, **kwargs)

    def tracking_signature_verify(*args, **kwargs):
        selected_anchor = kwargs["anchor_dir"] / "producer-ed25519.pub"
        signature_anchor_checks.append(selected_anchor.read_bytes())
        assert kwargs["anchor_dir"] != anchor_dir
        kwargs["enforce_production_pin"] = False
        return real_verify_signature(*args, **kwargs)

    monkeypatch.setattr(resolve_pending, "verify_release_chain", tracking_verify)
    monkeypatch.setattr(
        resolve_pending,
        "verify_producer_signature_bytes",
        tracking_signature_verify,
    )
    appended = b'{"source_record_id":"test.series.2030","value":1}\n'
    candidate = tree.files["ledger/official_observations.jsonl"] + appended

    release_now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=2)
    merged = resolve_pending.propose_ledger_append(
        "PolicyEngine/chronicle",
        "codex/thesis-ledger-facts",
        "ledger/official_observations.jsonl",
        candidate.decode(),
        "a" * 40,
        "b" * 40,
        1,
        poll_seconds=0,
        poll_attempts=1,
        timestamp_requester=requester,
        release_now=release_now,
    )

    assert merged == "d" * 40
    assert len(published) == 1
    changes = published[0]
    assert changes["ledger/official_observations.jsonl"] == candidate
    assert "ledger/series_uuid_registry.jsonl" not in changes
    regenerated_catalog = json.loads(changes["ledger/series_catalog.json"])
    assert (
        regenerated_catalog["observations_sha256"]
        == hashlib.sha256(candidate).hexdigest()
    )
    assert regenerated_catalog["observation_rows"] == 2
    assert (
        regenerated_catalog["uuid_registry_sha256"]
        == hashlib.sha256(tree.files["ledger/series_uuid_registry.jsonl"]).hexdigest()
    )
    release_paths = [path for path in changes if path.startswith("releases/")]
    assert len(release_paths) == 4
    manifest_path = next(path for path in release_paths if path.endswith(".json"))
    producer_signature_path = next(
        path for path in release_paths if path.endswith(".producer.sig")
    )
    assert producer_signature_path == (
        f"releases/manifests/{pathlib.PurePosixPath(manifest_path).stem}.producer.sig"
    )
    assert len(changes[producer_signature_path]) == 64
    manifest_raw = changes[manifest_path]
    manifest = json.loads(manifest_raw)
    assert manifest_raw == canonical_bytes(manifest) + b"\n"
    assert pathlib.PurePosixPath(manifest_path).name == (
        ledger_release_chain.manifest_filename(1, manifest_raw)
    )
    assert (
        manifest["previousManifestSha256"]
        == hashlib.sha256(
            next(
                payload
                for path, payload in tree.files.items()
                if path.startswith("releases/manifests/") and path.endswith(".json")
            )
        ).hexdigest()
    )
    assert manifest["append"] == {
        "previousLineCount": 1,
        "appendedRowCount": 1,
        "appendedBytesSha256": hashlib.sha256(appended).hexdigest(),
    }
    assert manifest["createdAtUtc"] == release_now.isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    assert manifest["producer"] == {
        "repo": "PolicyEngine/chronicle",
        "branch": "codex/thesis-ledger-facts",
    }
    assert manifest["state"] == {
        "path": "ledger/official_observations.jsonl",
        "jsonlSha256": hashlib.sha256(candidate).hexdigest(),
        "lineCount": 2,
        "immutablePrefixSha256": hashlib.sha256(
            tree.files["ledger/immutable_prefix.json"]
        ).hexdigest(),
    }
    assert len(verify_calls) == 2
    assert all(call["require_chain"] is True for call in verify_calls)
    assert all(call["verify_state"] is True for call in verify_calls)
    assert signature_anchor_checks == [
        tree.files["releases/anchors/producer-ed25519.pub"]
    ]
    assert resolve_pending.PRODUCER_SIGNING_KEY_ENV not in os.environ
    assert not any("/contents/" in " ".join(args) for args, _ in calls)
    merge_call = next(
        (args, body) for args, body in calls if "/merge" in " ".join(args)
    )
    assert merge_call[1] == {"merge_method": "rebase", "sha": "c" * 40}


def test_append_proposal_catalog_generator_failure_is_closed(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    tree, anchor_dir, requester, signing_key_pem = _release_fixture_tree(tmp_path)
    tree.files["scripts/build_series_catalog.py"] = b"raise SystemExit(17)\n"
    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.generator-fail","value":1}\n'
    )

    with pytest.raises(
        resolve_pending.LedgerProposalError,
        match="series-catalog generator failed with exit code 17",
    ):
        resolve_pending._prepare_release_files(
            tree,
            path="ledger/official_observations.jsonl",
            candidate_ledger=candidate,
            added=1,
            requester=requester,
            timeout_seconds=10,
            clock_skew_seconds=resolve_pending.DEFAULT_CLOCK_SKEW_SECONDS,
            anchor_dir=anchor_dir,
            now=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=2),
            producer_signing_key=signing_key_pem,
        )


def test_catalog_regeneration_inputs_cover_the_fixture_stage(
    tmp_path: pathlib.Path,
) -> None:
    # The staged generator can only see files _fetch_repository_tree actually
    # fetched. Every non-release file the witnessed fixture stages must be the
    # ledger itself, the immutable prefix, or a declared regeneration input —
    # otherwise these tests pass against a stage the real fetch would never
    # populate (the fixture-fidelity gap behind the 8/14 coherence break).
    assert resolve_pending.CATALOG_REGENERATION_INPUTS == (
        "scripts/build_series_catalog.py",
        "scripts/check_thesis_facts_append.py",
        "scripts/receipt_pins.py",
        "ledger/series_catalog.json",
        "ledger/series_uuid_registry.jsonl",
        "ledger/seeds/thesis_docket_series.json",
    )
    tree, _anchor_dir, _requester, _signing_key = _release_fixture_tree(tmp_path)
    allowed = {
        "ledger/official_observations.jsonl",
        "ledger/immutable_prefix.json",
        *resolve_pending.CATALOG_REGENERATION_INPUTS,
    }
    unfetched = {
        path
        for path in tree.files
        if not path.startswith("releases/") and path not in allowed
    }
    assert unfetched == set()


def test_append_proposal_catalog_generator_cannot_mint_series(
    tmp_path: pathlib.Path,
) -> None:
    tree, anchor_dir, requester, signing_key_pem = _release_fixture_tree(tmp_path)
    tree.files["scripts/build_series_catalog.py"] = b"""import pathlib
path = pathlib.Path("ledger/series_uuid_registry.jsonl")
path.write_bytes(path.read_bytes() + b'{"uuid":"new"}\\n')
"""
    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.minted","value":1}\n'
    )

    with pytest.raises(
        resolve_pending.LedgerProposalError,
        match="minted or superseded series identities",
    ):
        resolve_pending._prepare_release_files(
            tree,
            path="ledger/official_observations.jsonl",
            candidate_ledger=candidate,
            added=1,
            requester=requester,
            timeout_seconds=10,
            clock_skew_seconds=resolve_pending.DEFAULT_CLOCK_SKEW_SECONDS,
            anchor_dir=anchor_dir,
            now=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=2),
            producer_signing_key=signing_key_pem,
        )


@pytest.mark.parametrize("signing_key", [None, ""])
def test_append_proposal_missing_signing_key_has_no_remote_mutation(
    tmp_path: pathlib.Path,
    monkeypatch,
    signing_key: str | None,
) -> None:
    tree, anchor_dir, _requester, _valid_key = _release_fixture_tree(tmp_path)
    if signing_key is None:
        monkeypatch.delenv(resolve_pending.PRODUCER_SIGNING_KEY_ENV, raising=False)
    else:
        monkeypatch.setenv(resolve_pending.PRODUCER_SIGNING_KEY_ENV, signing_key)
    monkeypatch.setattr(resolve_pending, "_fetch_repository_tree", lambda *_: tree)
    mutations: list[str] = []
    timestamp_calls: list[str] = []
    monkeypatch.setattr(
        resolve_pending,
        "_publish_proposal_commit",
        lambda *_args, **_kwargs: mutations.append("publish"),
    )

    def unexpected_timestamp(endpoint: str, *_args) -> bytes:
        timestamp_calls.append(endpoint)
        return b"unexpected"

    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.no-key","value":1}\n'
    )
    with pytest.raises(
        resolve_pending.LedgerProposalError,
        match=resolve_pending.PRODUCER_SIGNING_KEY_ENV,
    ):
        resolve_pending.propose_ledger_append(
            "PolicyEngine/chronicle",
            "codex/thesis-ledger-facts",
            "ledger/official_observations.jsonl",
            candidate.decode(),
            "a" * 40,
            "b" * 40,
            1,
            timestamp_requester=unexpected_timestamp,
            release_anchor_dir=anchor_dir,
        )

    assert mutations == []
    assert timestamp_calls == []
    assert resolve_pending.PRODUCER_SIGNING_KEY_ENV not in os.environ


def test_append_proposal_signing_failure_erases_key_and_has_no_remote_mutation(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    tree, anchor_dir, _requester, signing_key_pem = _release_fixture_tree(tmp_path)
    monkeypatch.setenv(resolve_pending.PRODUCER_SIGNING_KEY_ENV, signing_key_pem)
    monkeypatch.setattr(resolve_pending, "_fetch_repository_tree", lambda *_: tree)
    mutations: list[str] = []
    timestamp_calls: list[str] = []
    monkeypatch.setattr(
        resolve_pending,
        "_publish_proposal_commit",
        lambda *_args, **_kwargs: mutations.append("publish"),
    )

    real_open = resolve_pending.os.open
    key_open: dict[str, object] = {}

    def tracking_open(path, flags, mode=0o777, *, dir_fd=None):
        if pathlib.Path(path).name == "producer-private.pem":
            key_open.update(path=pathlib.Path(path), flags=flags, mode=mode)
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    real_run = resolve_pending.subprocess.run

    def failing_sign(command, **kwargs):
        if command[:3] == ["openssl", "pkeyutl", "-sign"]:
            key_path = pathlib.Path(command[command.index("-inkey") + 1])
            assert key_path.read_text() == signing_key_pem
            assert key_path.stat().st_mode & 0o777 == 0o600
            assert resolve_pending.PRODUCER_SIGNING_KEY_ENV not in kwargs["env"]
            assert signing_key_pem not in " ".join(command)
            return SimpleNamespace(
                returncode=23,
                stdout="",
                # A hostile diagnostic must not be propagated, even in part.
                stderr=signing_key_pem[:40],
            )
        return real_run(command, **kwargs)

    monkeypatch.setattr(resolve_pending.os, "open", tracking_open)
    monkeypatch.setattr(resolve_pending.subprocess, "run", failing_sign)

    def unexpected_timestamp(endpoint: str, *_args) -> bytes:
        timestamp_calls.append(endpoint)
        return b"unexpected"

    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.sign-fail","value":1}\n'
    )
    with pytest.raises(
        resolve_pending.LedgerProposalError,
        match="producer signing failed with exit code 23",
    ) as caught:
        resolve_pending.propose_ledger_append(
            "PolicyEngine/chronicle",
            "codex/thesis-ledger-facts",
            "ledger/official_observations.jsonl",
            candidate.decode(),
            "a" * 40,
            "b" * 40,
            1,
            timestamp_requester=unexpected_timestamp,
            release_anchor_dir=anchor_dir,
        )

    assert signing_key_pem not in str(caught.value)
    assert signing_key_pem[:40] not in str(caught.value)
    assert key_open["flags"] & os.O_EXCL
    assert key_open["mode"] == 0o600
    key_path = key_open["path"]
    assert isinstance(key_path, pathlib.Path)
    assert not key_path.exists()
    assert not key_path.parent.exists()
    assert mutations == []
    assert timestamp_calls == []
    assert resolve_pending.PRODUCER_SIGNING_KEY_ENV not in os.environ


def test_append_proposal_self_verify_failure_precedes_tsa_and_remote_mutation(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    tree, anchor_dir, _requester, _valid_key = _release_fixture_tree(tmp_path)
    wrong_root = tmp_path / "wrong_producer"
    (wrong_root / "anchors").mkdir(parents=True)
    _wrong_key_path, wrong_key_pem = _generate_test_producer_keypair(wrong_root)
    monkeypatch.setenv(resolve_pending.PRODUCER_SIGNING_KEY_ENV, wrong_key_pem)
    monkeypatch.setattr(resolve_pending, "_fetch_repository_tree", lambda *_: tree)
    mutations: list[str] = []
    timestamp_calls: list[str] = []
    monkeypatch.setattr(
        resolve_pending,
        "_publish_proposal_commit",
        lambda *_args, **_kwargs: mutations.append("publish"),
    )

    def unexpected_timestamp(endpoint: str, *_args) -> bytes:
        timestamp_calls.append(endpoint)
        return b"unexpected"

    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.wrong-key","value":1}\n'
    )
    with pytest.raises(
        ledger_release_chain.ReleaseChainError,
        match="producer Ed25519 signature verification failed",
    ):
        resolve_pending.propose_ledger_append(
            "PolicyEngine/chronicle",
            "codex/thesis-ledger-facts",
            "ledger/official_observations.jsonl",
            candidate.decode(),
            "a" * 40,
            "b" * 40,
            1,
            timestamp_requester=unexpected_timestamp,
            release_anchor_dir=anchor_dir,
        )

    assert mutations == []
    assert timestamp_calls == []
    assert resolve_pending.PRODUCER_SIGNING_KEY_ENV not in os.environ


def test_append_proposal_bad_receipt_has_no_remote_mutation(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    tree, anchor_dir, _requester, signing_key_pem = _release_fixture_tree(tmp_path)
    monkeypatch.setenv(resolve_pending.PRODUCER_SIGNING_KEY_ENV, signing_key_pem)
    bad_requester = _local_timestamp_requester(
        anchor_dir.parent,
        signer_overrides={"digicert": "freetsa"},
    )
    monkeypatch.setattr(resolve_pending, "_fetch_repository_tree", lambda *_: tree)
    mutations: list[str] = []
    monkeypatch.setattr(
        resolve_pending,
        "_publish_proposal_commit",
        lambda *_args, **_kwargs: mutations.append("publish"),
    )
    appended = b'{"source_record_id":"test.series.bad","value":1}\n'
    candidate = tree.files["ledger/official_observations.jsonl"] + appended

    with pytest.raises(ledger_release_chain.ReleaseChainError):
        resolve_pending.propose_ledger_append(
            "PolicyEngine/chronicle",
            "codex/thesis-ledger-facts",
            "ledger/official_observations.jsonl",
            candidate.decode(),
            "a" * 40,
            "b" * 40,
            1,
            timestamp_requester=bad_requester,
            release_anchor_dir=anchor_dir,
        )

    assert mutations == []


def test_append_proposal_tsa_failure_has_no_remote_mutation(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    tree, anchor_dir, _requester, signing_key_pem = _release_fixture_tree(tmp_path)
    monkeypatch.setenv(resolve_pending.PRODUCER_SIGNING_KEY_ENV, signing_key_pem)
    monkeypatch.setattr(resolve_pending, "_fetch_repository_tree", lambda *_: tree)
    mutations: list[str] = []
    monkeypatch.setattr(
        resolve_pending,
        "_publish_proposal_commit",
        lambda *_args, **_kwargs: mutations.append("publish"),
    )
    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.tsa","value":1}\n'
    )

    def fail_tsa(*_args):
        raise OSError("TSA unavailable")

    with pytest.raises(resolve_pending.LedgerProposalError, match="timestamp request"):
        resolve_pending.propose_ledger_append(
            "PolicyEngine/chronicle",
            "codex/thesis-ledger-facts",
            "ledger/official_observations.jsonl",
            candidate.decode(),
            "a" * 40,
            "b" * 40,
            1,
            timestamp_requester=fail_tsa,
            release_anchor_dir=anchor_dir,
        )

    assert mutations == []


def test_postmerge_state_is_fully_reverified(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    base_tree, anchor_dir, requester, signing_key_pem = _release_fixture_tree(tmp_path)
    monkeypatch.setenv(resolve_pending.PRODUCER_SIGNING_KEY_ENV, signing_key_pem)
    path = "ledger/official_observations.jsonl"
    candidate = (
        base_tree.files[path]
        + b'{"source_record_id":"test.series.postmerge","value":1}\n'
    )
    release_files = resolve_pending._prepare_release_files(
        base_tree,
        path=path,
        candidate_ledger=candidate,
        added=1,
        requester=requester,
        timeout_seconds=10,
        clock_skew_seconds=resolve_pending.DEFAULT_CLOCK_SKEW_SECONDS,
        anchor_dir=anchor_dir,
        now=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=2),
        producer_signing_key=signing_key_pem,
    )
    files = {**base_tree.files, path: candidate, **release_files}
    merged_tree = resolve_pending.RepositoryTree(
        tree_sha="9" * 40,
        files=files,
        modes={relative: "100644" for relative in files},
        blob_shas={relative: "8" * 40 for relative in files},
    )
    monkeypatch.setattr(
        resolve_pending,
        "_fetch_repository_tree",
        lambda *_args: merged_tree,
    )

    resolve_pending._verify_remote_proposal_state(
        "PolicyEngine/chronicle",
        "d" * 40,
        path=path,
        candidate_ledger=candidate,
        release_files=release_files,
        clock_skew_seconds=resolve_pending.DEFAULT_CLOCK_SKEW_SECONDS,
        anchor_dir=anchor_dir,
    )

    old_receipt = next(
        relative
        for relative in files
        if relative.endswith(".digicert.tsr") and relative not in release_files
    )
    files[old_receipt] = b"tampered historical receipt"
    with pytest.raises(ledger_release_chain.ReleaseChainError):
        resolve_pending._verify_remote_proposal_state(
            "PolicyEngine/chronicle",
            "d" * 40,
            path=path,
            candidate_ledger=candidate,
            release_files=release_files,
            clock_skew_seconds=resolve_pending.DEFAULT_CLOCK_SKEW_SECONDS,
            anchor_dir=anchor_dir,
        )


def test_pre_genesis_append_emits_no_release_files_or_tsa(monkeypatch) -> None:
    tree = _pre_genesis_tree()
    calls: list[tuple[tuple[str, ...], dict | None]] = []
    published: list[dict[str, bytes]] = []
    _install_proposal_transport(monkeypatch, tree, calls, published=published)
    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.legacy","value":1}\n'
    )

    def unexpected_tsa(*_args):
        raise AssertionError("pre-genesis proposal contacted a TSA")

    assert (
        resolve_pending._prepare_release_files(
            tree,
            path="ledger/official_observations.jsonl",
            candidate_ledger=candidate,
            added=1,
            requester=unexpected_tsa,
            timeout_seconds=10,
            clock_skew_seconds=resolve_pending.DEFAULT_CLOCK_SKEW_SECONDS,
            anchor_dir=None,
            now=None,
            producer_signing_key=None,
        )
        == {}
    )
    merged = resolve_pending.propose_ledger_append(
        "PolicyEngine/chronicle",
        "codex/thesis-ledger-facts",
        "ledger/official_observations.jsonl",
        candidate.decode(),
        "a" * 40,
        "b" * 40,
        1,
        poll_seconds=0,
        poll_attempts=1,
        timestamp_requester=unexpected_tsa,
    )

    assert merged == "d" * 40
    assert list(published[0]) == ["ledger/official_observations.jsonl"]


def test_append_proposal_refuses_to_merge_and_cleans_gate_failure(
    monkeypatch,
) -> None:
    tree = _pre_genesis_tree()
    calls: list[tuple[tuple[str, ...], dict | None]] = []
    _install_proposal_transport(
        monkeypatch,
        tree,
        calls,
        gate_conclusion="failure",
    )
    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.gate","value":1}\n'
    )

    with pytest.raises(resolve_pending.LedgerProposalError, match="append gate"):
        resolve_pending.propose_ledger_append(
            "PolicyEngine/chronicle",
            "codex/thesis-ledger-facts",
            "ledger/official_observations.jsonl",
            candidate.decode(),
            "a" * 40,
            "b" * 40,
            1,
            poll_seconds=0,
            poll_attempts=1,
        )

    joined = [" ".join(args) for args, _ in calls]
    assert not any("/merge" in call for call in joined)
    assert any("PATCH" in call and "/pulls/7" in call for call in joined)
    assert any("DELETE" in call and "/git/refs/heads/" in call for call in joined)


def test_append_proposal_cleans_pr_and_branch_when_merge_is_refused(
    monkeypatch,
) -> None:
    tree = _pre_genesis_tree()
    calls: list[tuple[tuple[str, ...], dict | None]] = []
    _install_proposal_transport(
        monkeypatch,
        tree,
        calls,
        merge_payload={"merged": False, "message": "base moved"},
    )
    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.merge","value":1}\n'
    )

    with pytest.raises(resolve_pending.LedgerProposalError, match="did not merge"):
        resolve_pending.propose_ledger_append(
            "PolicyEngine/chronicle",
            "codex/thesis-ledger-facts",
            "ledger/official_observations.jsonl",
            candidate.decode(),
            "a" * 40,
            "b" * 40,
            1,
            poll_seconds=0,
            poll_attempts=1,
        )

    joined = [" ".join(args) for args, _ in calls]
    assert any("/merge" in call for call in joined)
    assert any("PATCH" in call and "/pulls/7" in call for call in joined)
    assert any("DELETE" in call and "/git/refs/heads/" in call for call in joined)


def test_append_proposal_refuses_if_base_moves_during_gate_poll(
    monkeypatch,
) -> None:
    tree = _pre_genesis_tree()
    calls: list[tuple[tuple[str, ...], dict | None]] = []
    _install_proposal_transport(monkeypatch, tree, calls)
    heads = iter(["b" * 40, "e" * 40])
    monkeypatch.setattr(resolve_pending, "_branch_head", lambda *_: next(heads))
    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.race","value":1}\n'
    )

    with pytest.raises(
        resolve_pending.LedgerProposalError,
        match="moved while proposal awaited the append gate",
    ):
        resolve_pending.propose_ledger_append(
            "PolicyEngine/chronicle",
            "codex/thesis-ledger-facts",
            "ledger/official_observations.jsonl",
            candidate.decode(),
            "a" * 40,
            "b" * 40,
            1,
            poll_seconds=0,
            poll_attempts=1,
        )

    joined = [" ".join(args) for args, _ in calls]
    assert not any("/merge" in call for call in joined)
    assert any("PATCH" in call and "/pulls/7" in call for call in joined)
    assert any("DELETE" in call and "/git/refs/heads/" in call for call in joined)


def test_append_proposal_recovers_ambiguous_successful_merge(monkeypatch) -> None:
    tree = _pre_genesis_tree()
    calls: list[tuple[tuple[str, ...], dict | None]] = []
    _install_proposal_transport(monkeypatch, tree, calls)
    base_api = resolve_pending._gh_api
    merge_attempted = False

    def ambiguous_api(*args: str, input_body=None) -> str:
        nonlocal merge_attempted
        joined = " ".join(args)
        if "/merge" in joined:
            merge_attempted = True
            raise RuntimeError("merge response lost after server success")
        if merge_attempted and joined.endswith("/pulls/7") and "PATCH" not in args:
            return json.dumps(
                {
                    "merged": True,
                    "merge_commit_sha": "d" * 40,
                    "head": {"sha": "c" * 40},
                    "base": {"ref": "codex/thesis-ledger-facts"},
                }
            )
        return base_api(*args, input_body=input_body)

    verified: list[str] = []
    monkeypatch.setattr(resolve_pending, "_gh_api", ambiguous_api)
    monkeypatch.setattr(
        resolve_pending,
        "_verify_remote_proposal_state",
        lambda _repo, sha, **_kwargs: verified.append(sha),
    )
    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.ambiguous","value":1}\n'
    )

    merged = resolve_pending.propose_ledger_append(
        "PolicyEngine/chronicle",
        "codex/thesis-ledger-facts",
        "ledger/official_observations.jsonl",
        candidate.decode(),
        "a" * 40,
        "b" * 40,
        1,
        poll_seconds=0,
        poll_attempts=1,
    )

    assert merged == "d" * 40
    assert verified == ["d" * 40]


def test_append_proposal_rejects_retarget_after_normal_merge_response(
    monkeypatch,
) -> None:
    tree = _pre_genesis_tree()
    calls: list[tuple[tuple[str, ...], dict | None]] = []
    _install_proposal_transport(monkeypatch, tree, calls)
    base_api = resolve_pending._gh_api
    pr_reads = 0

    def retargeting_api(*args: str, input_body=None) -> str:
        nonlocal pr_reads
        joined = " ".join(args)
        if joined.endswith("/pulls/7") and "PATCH" not in args:
            pr_reads += 1
            if pr_reads >= 2:
                return json.dumps(
                    {
                        "merged": True,
                        "merge_commit_sha": "d" * 40,
                        "head": {"sha": "c" * 40},
                        "base": {"ref": "attacker-retarget", "sha": "b" * 40},
                    }
                )
        return base_api(*args, input_body=input_body)

    verified: list[str] = []
    monkeypatch.setattr(resolve_pending, "_gh_api", retargeting_api)
    monkeypatch.setattr(
        resolve_pending,
        "_verify_remote_proposal_state",
        lambda _repo, sha, **_kwargs: verified.append(sha),
    )
    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.retarget","value":1}\n'
    )

    with pytest.raises(
        resolve_pending.LedgerProposalError,
        match="expected proposal head and base",
    ):
        resolve_pending.propose_ledger_append(
            "PolicyEngine/chronicle",
            "codex/thesis-ledger-facts",
            "ledger/official_observations.jsonl",
            candidate.decode(),
            "a" * 40,
            "b" * 40,
            1,
            poll_seconds=0,
            poll_attempts=1,
        )

    assert any("/merge" in " ".join(args) for args, _body in calls)
    assert verified == []


def test_append_proposal_rejects_merge_response_sha_disagreement(monkeypatch) -> None:
    tree = _pre_genesis_tree()
    calls: list[tuple[tuple[str, ...], dict | None]] = []
    _install_proposal_transport(
        monkeypatch,
        tree,
        calls,
        merge_payload={"merged": True, "sha": "e" * 40},
    )
    verified: list[str] = []
    monkeypatch.setattr(
        resolve_pending,
        "_verify_remote_proposal_state",
        lambda _repo, sha, **_kwargs: verified.append(sha),
    )
    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.sha-mismatch","value":1}\n'
    )

    with pytest.raises(
        resolve_pending.LedgerProposalError,
        match="SHA disagrees with pull-request state",
    ):
        resolve_pending.propose_ledger_append(
            "PolicyEngine/chronicle",
            "codex/thesis-ledger-facts",
            "ledger/official_observations.jsonl",
            candidate.decode(),
            "a" * 40,
            "b" * 40,
            1,
            poll_seconds=0,
            poll_attempts=1,
        )

    assert verified == []


def test_merge_recovery_rejects_retargeted_pull_request(monkeypatch) -> None:
    monkeypatch.setattr(
        resolve_pending,
        "_gh_api",
        lambda *_args, **_kwargs: json.dumps(
            {
                "merged": True,
                "merge_commit_sha": "d" * 40,
                "head": {"sha": "e" * 40},
                "base": {"ref": "other-branch"},
            }
        ),
    )

    with pytest.raises(
        resolve_pending.LedgerProposalError,
        match="expected proposal head and base",
    ):
        resolve_pending._merged_proposal_sha(
            "PolicyEngine/chronicle",
            7,
            expected_head_sha="c" * 40,
            expected_base="codex/thesis-ledger-facts",
        )


def test_append_proposal_recovers_and_cleans_ambiguous_ref_creation(
    monkeypatch,
) -> None:
    tree = _pre_genesis_tree()
    calls: list[tuple[tuple[str, ...], dict | None]] = []
    _install_proposal_transport(
        monkeypatch,
        tree,
        calls,
        fail_ref_creation=True,
    )
    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.ref","value":1}\n'
    )

    with pytest.raises(RuntimeError, match="ref creation"):
        resolve_pending.propose_ledger_append(
            "PolicyEngine/chronicle",
            "codex/thesis-ledger-facts",
            "ledger/official_observations.jsonl",
            candidate.decode(),
            "a" * 40,
            "b" * 40,
            1,
        )

    joined = [" ".join(args) for args, _ in calls]
    assert any("/git/ref/heads/" in call for call in joined)
    assert any("DELETE" in call and "/git/refs/heads/" in call for call in joined)
    assert not any("/pulls" in call for call in joined)


def test_append_proposal_recovers_and_cleans_ambiguous_pr_creation(
    monkeypatch,
) -> None:
    tree = _pre_genesis_tree()
    calls: list[tuple[tuple[str, ...], dict | None]] = []
    _install_proposal_transport(
        monkeypatch,
        tree,
        calls,
        fail_pr_creation=True,
        recover_pr_number=7,
    )
    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.pr","value":1}\n'
    )

    with pytest.raises(RuntimeError, match="PR creation"):
        resolve_pending.propose_ledger_append(
            "PolicyEngine/chronicle",
            "codex/thesis-ledger-facts",
            "ledger/official_observations.jsonl",
            candidate.decode(),
            "a" * 40,
            "b" * 40,
            1,
        )

    joined = [" ".join(args) for args, _ in calls]
    assert any("DELETE" in call and "/git/refs/heads/" in call for call in joined)
    assert any("PATCH" in call and "/pulls/7" in call for call in joined)


def test_publish_proposal_uses_one_tree_and_one_commit(monkeypatch) -> None:
    calls: list[tuple[tuple[str, ...], dict | None]] = []
    blob_number = 0

    def api(*args: str, input_body=None) -> str:
        nonlocal blob_number
        calls.append((args, input_body))
        endpoint = args[-1]
        if endpoint.endswith("/git/blobs"):
            blob_number += 1
            return json.dumps({"sha": f"{blob_number:040x}"})
        if endpoint.endswith("/git/trees"):
            return json.dumps({"sha": "e" * 40})
        if endpoint.endswith("/git/commits"):
            return json.dumps({"sha": "f" * 40})
        raise AssertionError(endpoint)

    monkeypatch.setattr(resolve_pending, "_gh_api", api)
    changes = {
        "ledger/official_observations.jsonl": b"ledger\n",
        "releases/manifests/0001-a.json": b"manifest\n",
        "releases/manifests/0001-a.freetsa.tsr": b"one",
        "releases/manifests/0001-a.digicert.tsr": b"two",
        "releases/manifests/0001-a.producer.sig": b"signature",
    }

    commit = resolve_pending._publish_proposal_commit(
        "PolicyEngine/chronicle",
        base_sha="b" * 40,
        base_tree_sha="c" * 40,
        message="test",
        changes=changes,
    )

    assert commit == "f" * 40
    blob_calls = [call for call in calls if call[0][-1].endswith("/git/blobs")]
    tree_calls = [call for call in calls if call[0][-1].endswith("/git/trees")]
    commit_calls = [call for call in calls if call[0][-1].endswith("/git/commits")]
    assert len(blob_calls) == len(changes)
    assert len(tree_calls) == 1
    assert len(commit_calls) == 1
    assert tree_calls[0][1]["base_tree"] == "c" * 40
    assert {entry["path"] for entry in tree_calls[0][1]["tree"]} == set(changes)
    assert commit_calls[0][1]["parents"] == ["b" * 40]


def test_fetch_git_blob_binds_response_and_bytes_to_requested_sha(monkeypatch) -> None:
    raw = b"tree-bound blob bytes"
    requested_sha = hashlib.sha1(
        f"blob {len(raw)}\0".encode("ascii") + raw,
        usedforsecurity=False,
    ).hexdigest()
    payload = {
        "sha": requested_sha,
        "encoding": "base64",
        "content": base64.b64encode(raw).decode("ascii"),
        "size": len(raw),
    }
    monkeypatch.setattr(resolve_pending, "_gh_api", lambda *_args: json.dumps(payload))

    assert (
        resolve_pending._fetch_git_blob("PolicyEngine/chronicle", requested_sha) == raw
    )

    payload["sha"] = "0" * 40
    with pytest.raises(resolve_pending.LedgerProposalError, match="requested blob"):
        resolve_pending._fetch_git_blob("PolicyEngine/chronicle", requested_sha)

    payload["sha"] = requested_sha
    payload["content"] = base64.b64encode(b"same reported size!!").decode("ascii")
    payload["size"] = len(b"same reported size!!")
    with pytest.raises(resolve_pending.LedgerProposalError, match="do not match"):
        resolve_pending._fetch_git_blob("PolicyEngine/chronicle", requested_sha)


def test_fetch_repository_tree_binds_commit_trees_and_blobs(monkeypatch) -> None:
    repo = "PolicyEngine/chronicle"
    commit_sha = "a" * 40
    ledger_path = "ledger/official_observations.jsonl"
    blobs = {
        "immutable_prefix.json": b"{}\n",
        "official_observations.jsonl": b'{"source_record_id":"base"}\n',
    }
    blob_shas = {
        name: hashlib.sha1(
            f"blob {len(raw)}\0".encode("ascii") + raw,
            usedforsecurity=False,
        ).hexdigest()
        for name, raw in blobs.items()
    }
    ledger_entries = [
        {"path": name, "mode": "100644", "type": "blob", "sha": blob_shas[name]}
        for name in sorted(blobs)
    ]
    ledger_tree_sha = resolve_pending._git_tree_object_sha(ledger_entries)
    root_entries = [
        {
            "path": "ledger",
            "mode": "040000",
            "type": "tree",
            "sha": ledger_tree_sha,
        }
    ]
    root_tree_sha = resolve_pending._git_tree_object_sha(root_entries)

    def api(*args: str, input_body=None) -> str:
        del input_body
        endpoint = args[-1]
        if endpoint.endswith(f"/git/commits/{commit_sha}"):
            return json.dumps({"sha": commit_sha, "tree": {"sha": root_tree_sha}})
        if endpoint.endswith(f"/git/trees/{root_tree_sha}"):
            return json.dumps(
                {"sha": root_tree_sha, "tree": root_entries, "truncated": False}
            )
        if endpoint.endswith(f"/git/trees/{ledger_tree_sha}"):
            return json.dumps(
                {
                    "sha": ledger_tree_sha,
                    "tree": ledger_entries,
                    "truncated": False,
                }
            )
        for name, blob_sha in blob_shas.items():
            if endpoint.endswith(f"/git/blobs/{blob_sha}"):
                raw = blobs[name]
                return json.dumps(
                    {
                        "sha": blob_sha,
                        "encoding": "base64",
                        "content": base64.b64encode(raw).decode(),
                        "size": len(raw),
                    }
                )
        raise AssertionError(endpoint)

    monkeypatch.setattr(resolve_pending, "_gh_api", api)

    tree = resolve_pending._fetch_repository_tree(repo, commit_sha, ledger_path)

    assert tree.tree_sha == root_tree_sha
    assert tree.files == {
        ledger_path: blobs["official_observations.jsonl"],
        "ledger/immutable_prefix.json": blobs["immutable_prefix.json"],
    }


def test_fetch_repository_tree_rejects_swapped_commit_response(monkeypatch) -> None:
    monkeypatch.setattr(
        resolve_pending,
        "_gh_api",
        lambda *_args: json.dumps({"sha": "b" * 40, "tree": {"sha": "c" * 40}}),
    )

    with pytest.raises(resolve_pending.LedgerProposalError, match="requested commit"):
        resolve_pending._fetch_repository_tree(
            "PolicyEngine/chronicle",
            "a" * 40,
            "ledger/official_observations.jsonl",
        )


def test_fetch_repository_tree_rejects_partial_tree_with_claimed_sha(
    monkeypatch,
) -> None:
    commit_sha = "a" * 40
    claimed_tree_sha = "c" * 40

    def api(*args: str, input_body=None) -> str:
        del input_body
        if "/git/commits/" in args[-1]:
            return json.dumps({"sha": commit_sha, "tree": {"sha": claimed_tree_sha}})
        return json.dumps({"sha": claimed_tree_sha, "tree": [], "truncated": False})

    monkeypatch.setattr(resolve_pending, "_gh_api", api)

    with pytest.raises(resolve_pending.LedgerProposalError, match="partial base state"):
        resolve_pending._fetch_repository_tree(
            "PolicyEngine/chronicle",
            commit_sha,
            "ledger/official_observations.jsonl",
        )


def test_append_proposal_rejects_unwitnessed_base_state(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    tree, anchor_dir, requester, _signing_key_pem = _release_fixture_tree(tmp_path)
    path = "ledger/official_observations.jsonl"
    tree.files[path] += b'{"source_record_id":"unwitnessed","value":1}\n'
    monkeypatch.setattr(resolve_pending, "_fetch_repository_tree", lambda *_: tree)
    mutations: list[str] = []
    monkeypatch.setattr(
        resolve_pending,
        "_publish_proposal_commit",
        lambda *_args, **_kwargs: mutations.append("publish"),
    )
    candidate = tree.files[path] + b'{"source_record_id":"next","value":2}\n'

    with pytest.raises(ledger_release_chain.ReleaseChainError, match="HEAD release"):
        resolve_pending.propose_ledger_append(
            "PolicyEngine/chronicle",
            "codex/thesis-ledger-facts",
            path,
            candidate.decode(),
            "a" * 40,
            "b" * 40,
            1,
            timestamp_requester=requester,
            release_anchor_dir=anchor_dir,
        )

    assert mutations == []


def test_assertion_version_binds_measure_mapping_and_lineage() -> None:
    # Finding 6: av2 must change when concept mapping, authority, source
    # file/digest, lineage, or the response digest change — not only value.
    base = {
        "source_record_id": "test.series.2030",
        "value": 1.5,
        "observed_at": "2030-01-10",
        "period": {"type": "month", "value": "2030-01"},
        "measure": {
            "concept": "test.series",
            "unit": "millions",
            "source_concept": "SRC",
            "concept_authority": "auth",
        },
        "source": {"source_name": "test", "vintage": "advance", "source_file": "a.csv"},
        "source_row_keys": ["r1"],
        "responseArchive": {"sha256": "d" * 64},
    }
    base_id = resolve_pending.assertion_version(base)["id"]
    variants = [
        {"measure": {**base["measure"], "source_concept": "OTHER"}},
        {"measure": {**base["measure"], "concept_authority": "other"}},
        {"source": {**base["source"], "source_file": "b.csv"}},
        {"source_row_keys": ["r2"]},
        {"responseArchive": {"sha256": "e" * 64}},
    ]
    for override in variants:
        changed = resolve_pending.assertion_version({**base, **override})["id"]
        assert changed != base_id, f"av2 did not change for {override}"


# --------------------------------------------------------------------------
# International native-source adapters


def test_parse_ref_period_handles_international_dialects() -> None:
    rolled_ref = register_targets.derive_data_point_id(
        {
            "series": "statcan.cpi.allitems.yoy",
            "period": "2026-07",
            "sourceBinding": {"releasePolicy": "first_print"},
        },
        None,
    )
    assert rolled_ref == "statcan.cpi.allitems.yoy.2026_07.first_print"
    cases = [
        (
            "statcan.cpi.all_items_annual_rate.canada.may_2026.first_print",
            "statcan.cpi.all_items_annual_rate.canada",
            ("month", "2026-05"),
        ),
        (
            "statcan.cpi.allitems.yoy.2026-05",
            "statcan.cpi.allitems.yoy",
            ("month", "2026-05"),
        ),
        (
            "statcan.36-10-0434-01.all_industries.month_to_month_percent_change"
            ".2026-05.first_print",
            "statcan.36-10-0434-01.all_industries.month_to_month_percent_change",
            ("month", "2026-05"),
        ),
        (
            "eurostat.hicp.all_items_annual_rate.euro_area.june_2026.flash",
            "eurostat.hicp.all_items_annual_rate.euro_area",
            ("month", "2026-06"),
        ),
        (
            rolled_ref,
            "statcan.cpi.allitems.yoy",
            ("month", "2026-07"),
        ),
    ]
    for ref, stem, expected in cases:
        assert resolve_pending.parse_ref_period(ref, stem) == expected
    # A final-first-print dialect is NOT silently claimed as the flash.
    assert (
        resolve_pending.parse_ref_period(
            "eurostat.hicp.all_items_annual_rate.euro_area.may_2026.final_first_print",
            "eurostat.hicp.all_items_annual_rate.euro_area",
        )
        is None
    )
    assert (
        resolve_pending.parse_ref_period(
            "statcan.cpi.allitems.yoy.2026_13.first_print",
            "statcan.cpi.allitems.yoy",
        )
        is None
    )


def test_pending_adapter_refs_claims_international_stems_with_units() -> None:
    def entry(slug, unit):
        return {
            "kind": "prediction_recorded",
            "forecastSlug": slug,
            "resolutionDate": "2026-07-01",
            "unit": unit,
            "interval80": {"lower": 0, "upper": 10},
        }

    refs_and_units = [
        ("statcan.cpi.all_items_annual_rate.canada.may_2026.first_print", "percent"),
        ("statcan.cpi.allitems.yoy.2026-05", "percent"),
        (
            "statcan.gdp_by_industry.monthly_growth.april_2026.first_print",
            "percent_growth",
        ),
        ("abs.cpi.all_groups.yoy.2026-06.first_print", "percent"),
        ("abs.labour.unemployment_rate.australia.may_2026.first_print", "percent"),
        ("eurostat.hicp.all_items_annual_rate.euro_area.june_2026.flash", "percent"),
        ("eurostat.ea.hicp.flash.yoy.2026-06", "percent"),
    ]
    blocked_refs = [
        "statcan.employment_insurance.regular_beneficiaries.canada"
        ".may_2026.first_print",
        "abs.labour.employment_change.australia.may_2026.first_print",
        "abs.building_approvals.total_dwellings_mom.australia.may_2026.first_print",
        "statjp.cpi.tokyo_all_items_annual_rate.june_2026.preliminary",
        "eurostat.unemployment_rate.euro_area.may_2026.first_print",
        "ons.cpi.annual_rate.may_2026.first_print",
        # The admitted sources are monthly. A quarterly-looking tail must not
        # be claimed and transformed with monthly prior-period arithmetic.
        "statcan.cpi.allitems.yoy.2026_q2.first_print",
    ]
    log = {
        "entries": [
            entry(f"cell-{i}", unit) for i, (_, unit) in enumerate(refs_and_units)
        ],
        "resolutionLinks": [
            {"status": "pending", "forecastSlug": f"cell-{i}", "targetFactRef": ref}
            for i, (ref, _) in enumerate(refs_and_units)
        ]
        + [
            {
                "status": "pending",
                "forecastSlug": "cell-0",
                "targetFactRef": ref,
            }
            for ref in blocked_refs
        ]
        + [
            # Belgium is owned by its own lane; the euro-area stems must
            # not claim it.
            {
                "status": "pending",
                "forecastSlug": "cell-0",
                "targetFactRef": "eurostat.une_rt_m.unemployment_rate.belgium.2026_06"
                ".first_print",
            },
        ],
    }
    todo = resolve_pending.pending_adapter_refs(log)
    claimed = {item[0]: item for item in todo}
    for ref, unit in refs_and_units:
        assert ref in claimed, ref
        _, kind, spec, period_type, _, _, _ = claimed[ref]
        assert kind == "intl"
        assert period_type == "month"
        # The adapter's declared unit must equal the cell's recorded unit;
        # the resolution loop refuses on any mismatch.
        assert spec["unit"] == unit, ref
    assert (
        "eurostat.une_rt_m.unemployment_rate.belgium.2026_06.first_print" not in claimed
    )
    assert not set(blocked_refs) & set(claimed)


def _international_fixture(name: str) -> bytes:
    return (ROOT / "tests" / "fixtures" / "international" / name).read_bytes()


def test_recorded_international_fixtures_reproduce_admitted_anchors() -> None:
    unique_specs = {
        spec["series_id"]: spec for spec in resolve_pending.INTL_ADAPTERS.values()
    }
    for spec in unique_specs.values():
        raw = _international_fixture(spec["admission_fixture"])
        flags: dict[str, str] = {}
        if spec["kind"] == "statcan":
            series = resolve_pending.statcan_series_from_payload(raw, spec["vector"])
        elif spec["kind"] == "abs":
            series = resolve_pending.abs_series_from_payload(
                raw, spec["flow"], spec["key"]
            )
        elif spec["kind"] == "eurostat":
            series, flags = resolve_pending.eurostat_series_from_payload(
                raw, spec["dataset"], spec["key"]
            )
        else:
            raise AssertionError(f"unhandled admitted kind {spec['kind']}")
        got = {
            period: resolve_pending.intl_transformed_value(spec, series, period)
            for period in spec["verified_anchors"]
        }
        assert got == spec["verified_anchors"]
        if spec["kind"] == "eurostat":
            assert flags == {"2026-06": "e"}


def test_international_parsers_refuse_wrong_source_identity() -> None:
    statcan_spec = resolve_pending.INTL_ADAPTERS["statcan.cpi.allitems.yoy"]
    statcan_payload = json.loads(
        _international_fixture(statcan_spec["admission_fixture"])
    )
    statcan_payload[0]["object"]["vectorId"] = 999
    with pytest.raises(ValueError, match="returned vector"):
        resolve_pending.statcan_series_from_payload(
            json.dumps(statcan_payload).encode(), statcan_spec["vector"]
        )

    abs_spec = resolve_pending.INTL_ADAPTERS["abs.labour.unemployment_rate"]
    abs_raw = _international_fixture(abs_spec["admission_fixture"])
    with pytest.raises(ValueError, match="not dataflow"):
        resolve_pending.abs_series_from_payload(abs_raw, "CPI", abs_spec["key"])
    with pytest.raises(ValueError, match="returned key"):
        resolve_pending.abs_series_from_payload(
            abs_raw, abs_spec["flow"], "M13.3.1599.20.NSW.M"
        )

    eurostat_spec = resolve_pending.INTL_ADAPTERS["eurostat.hicp.flash.yoy"]
    eurostat_raw = _international_fixture(eurostat_spec["admission_fixture"])
    with pytest.raises(ValueError, match="returned dataset"):
        resolve_pending.eurostat_series_from_payload(
            eurostat_raw, "une_rt_m", eurostat_spec["key"]
        )
    with pytest.raises(ValueError, match="dimension geo"):
        resolve_pending.eurostat_series_from_payload(
            eurostat_raw,
            eurostat_spec["dataset"],
            "M.RCH_A.TOTAL.DE",
        )


def test_admitted_international_specs_have_three_anchors_and_calendars() -> None:
    unique_specs = {id(spec): spec for spec in resolve_pending.INTL_ADAPTERS.values()}
    assert len(unique_specs) == 5
    fixture_root = ROOT / "tests" / "fixtures" / "international"
    for spec in unique_specs.values():
        assert len(spec["verified_anchors"]) >= 3
        assert (fixture_root / spec["admission_fixture"]).is_file()
        assert spec["release_calendar_url"].startswith("https://")
        # Fixture anchors are permanent admission evidence. Bounded latest-N
        # live responses must not acquire a fixed historical dependency that
        # makes a recurring adapter expire when those periods age out.
        assert spec.get("anchors") == {}
        assert set(resolve_pending.intl_binding_template(spec)) == (
            resolve_pending.INTL_BINDING_KEYS
        )
        assert spec["allowed_hosts"]
    for spec in {
        id(spec): spec for spec in resolve_pending.INTL_BLOCKED_ADAPTERS.values()
    }.values():
        assert "verified_anchors" not in spec
        assert "admission_fixture" not in spec


def test_only_reviewed_legacy_international_contract_gets_native_executor(
    monkeypatch,
) -> None:
    content_hash, contract = next(
        iter(resolve_pending.LEGACY_INTL_EXECUTOR_CONTRACTS.items())
    )
    registration = {
        "targetContentHash": content_hash,
        "contract": contract,
    }
    spec = resolve_pending.INTL_ADAPTERS["abs.labour.unemployment_rate.australia"]
    execution = resolve_pending.intl_execution_spec(registration, spec)
    assert execution is not None
    assert execution["request_url"] == contract["sourceBinding"]["sourceUrl"]
    assert execution["target_series"] == contract["series"]

    raw = _international_fixture(spec["admission_fixture"])
    calls: list[str] = []

    def fake_http_get(url, *, allowed_hosts, timeout=120):
        calls.append(url)
        assert set(allowed_hosts) == set(contract["sourceBinding"]["allowedHosts"])
        return raw, "2026-08-20T01:30:00Z", url

    monkeypatch.setattr(resolve_pending, "http_get", fake_http_get)
    series, flags, got_raw, source_url, retrieved_at = resolve_pending.intl_fetch(
        execution, "2026-07", {}
    )
    assert calls == [contract["sourceBinding"]["sourceUrl"]]
    assert series["2026-05"] == pytest.approx(4.35594887)
    assert flags == {}
    assert got_raw == raw
    assert source_url == calls[0]
    assert retrieved_at == "2026-08-20T01:30:00Z"

    altered = json.loads(json.dumps(contract))
    altered["sourceBinding"]["field"] = "neighboring-series"
    assert (
        resolve_pending.intl_execution_spec(
            {"targetContentHash": content_hash, "contract": altered}, spec
        )
        is None
    )
    assert (
        resolve_pending.intl_execution_spec(
            {"targetContentHash": "0" * 64, "contract": contract}, spec
        )
        is None
    )


def test_current_native_executor_requires_exact_registry_series_spec_pair() -> None:
    spec = resolve_pending.INTL_REGISTRY_ADAPTERS["abs.labour.unemployment_rate"]
    binding = {
        **json.loads(json.dumps(resolve_pending.intl_binding_template(spec))),
        "allowedHosts": list(spec["allowed_hosts"]),
        "expectedReleaseWindow": {
            "start": "2026-09-24",
            "end": "2026-09-24",
        },
    }
    registration = {
        "targetContentHash": "0" * 64,
        "contract": {
            "series": "abs.labour.unemployment_rate",
            "sourceBinding": binding,
        },
    }
    assert resolve_pending.intl_execution_spec(registration, spec) is not None

    borrowed = json.loads(json.dumps(registration))
    borrowed["contract"]["series"] = "unrelated.other.series"
    assert resolve_pending.intl_execution_spec(borrowed, spec) is None


def _routed_intl_spec(ref: str) -> dict:
    """The spec exactly as the resolver's router hands it to the main loop."""
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "routed-target",
                "resolutionDate": "2026-09-14",
            }
        ],
        "resolutionLinks": [
            {
                "status": "pending",
                "targetFactRef": ref,
                "forecastSlug": "routed-target",
            }
        ],
    }
    ((got_ref, kind, spec, *_rest),) = resolve_pending.pending_adapter_refs(log)
    assert (got_ref, kind) == (ref, "intl")
    return spec


def _current_intl_registration(series: str) -> dict:
    spec = resolve_pending.INTL_REGISTRY_ADAPTERS[series]
    binding = {
        **json.loads(json.dumps(resolve_pending.intl_binding_template(spec))),
        "allowedHosts": list(spec["allowed_hosts"]),
        "expectedReleaseWindow": {"start": "2026-09-14", "end": "2026-09-14"},
    }
    return {
        "targetContentHash": "0" * 64,
        "contract": {"series": series, "sourceBinding": binding},
    }


def test_routed_international_spec_reaches_its_native_executor() -> None:
    """The router copies the adapter (`{**spec, "period_type": ...,
    "target_series": stem}`), so an identity test against the registry
    refused every registered international target: both StatCan CPI cells
    of summer 2026 printed "BINDING/ADAPTER MISMATCH (refusing, registry
    drift?): ... — " with no mismatch named, and their first-print windows
    closed unresolved. The direct-spec tests above could not see it."""
    ref = "statcan.cpi.allitems.yoy.2026_08.first_print"
    routed = _routed_intl_spec(ref)
    canonical = resolve_pending.INTL_REGISTRY_ADAPTERS["statcan.cpi.allitems.yoy"]
    assert routed is not canonical  # the router hands over a copy
    assert resolve_pending.intl_registry_origin(routed) is canonical

    registration = _current_intl_registration("statcan.cpi.allitems.yoy")
    binding = registration["contract"]["sourceBinding"]
    assert resolve_pending.intl_binding_mismatches(routed, binding) == []
    execution = resolve_pending.intl_execution_spec(registration, routed)
    assert execution is not None
    assert execution["target_series"] == "statcan.cpi.allitems.yoy"


def test_routed_spec_still_cannot_borrow_another_series_contract() -> None:
    """What the identity test was for: the parser that runs must be the
    canonical one for the series the immutable contract names."""
    routed = _routed_intl_spec("statcan.cpi.allitems.yoy.2026_08.first_print")
    borrowed = _current_intl_registration("statcan.cpi.allitems.yoy")
    borrowed["contract"]["series"] = "statcan.gdp_by_industry.monthly_growth"
    assert resolve_pending.intl_execution_spec(borrowed, routed) is None
    unknown = _current_intl_registration("statcan.cpi.allitems.yoy")
    unknown["contract"]["series"] = "unrelated.other.series"
    assert resolve_pending.intl_execution_spec(unknown, routed) is None


def test_altered_routed_spec_has_no_origin() -> None:
    routed = _routed_intl_spec("statcan.cpi.allitems.yoy.2026_08.first_print")
    registration = _current_intl_registration("statcan.cpi.allitems.yoy")
    for tampered in (
        {**routed, "series_id": "v00000000"},  # a different vector
        {**routed, "extra_transform": "anything"},  # an added key
        {k: v for k, v in routed.items() if k != "allowed_hosts"},  # a dropped key
        {**routed, "target_series": "abs.cpi.all_groups.yoy"},  # another stem
        {**routed, "target_series": "not.an.adapter"},
    ):
        assert resolve_pending.intl_registry_origin(tampered) is None
        assert resolve_pending.intl_execution_spec(registration, tampered) is None


def test_existing_legacy_international_targets_fail_closed_except_reviewed_one() -> (
    None
):
    expected = {
        "abs.cpi.all_groups.yoy.2026-07.first_print": False,
        ("abs.cpi.all_groups_annual_rate.australia.june_2026.first_print"): False,
        ("abs.labour.unemployment_rate.australia.july_2026.first_print"): True,
        (
            "statcan.36-10-0434-01.all_industries."
            "month_to_month_percent_change.2026-06.first_print"
        ): False,
        (
            "statcan.36-10-0434-01.all_industries."
            "month_to_month_percent_change.2026-07.first_print"
        ): False,
    }
    registrations = resolve_pending.registration_contracts()
    for data_point_id, admitted in expected.items():
        stem = resolve_pending.longest_adapter_stem(
            data_point_id, resolve_pending.INTL_ADAPTERS
        )
        assert stem is not None
        execution = resolve_pending.intl_execution_spec(
            registrations[data_point_id],
            resolve_pending.INTL_ADAPTERS[stem],
        )
        assert (execution is not None) is admitted


def test_docket_and_admitted_adapter_bindings_are_byte_identical() -> None:
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())["series"]
    registered = {
        entry["series"]: entry["extras"]["sourceBinding"]
        for entry in docket
        if (entry.get("extras") or {}).get("sourceBinding", {}).get("adapter")
        in {
            "abs-data-api",
            "abs-release-page",
            "eurostat-api",
            "ons-timeseries",
            "statcan-wds",
        }
    }
    assert set(registered) == set(resolve_pending.INTL_REGISTRY_ADAPTERS)
    for series, spec in resolve_pending.INTL_REGISTRY_ADAPTERS.items():
        assert canonical_bytes(registered[series]) == canonical_bytes(
            resolve_pending.intl_binding_template(spec)
        )


def test_international_unit_host_binding_and_window_refusals() -> None:
    spec = resolve_pending.INTL_ADAPTERS["abs.labour.unemployment_rate"]
    assert resolve_pending.adapter_unit_matches(spec, {"unit": "percent"})
    assert not resolve_pending.adapter_unit_matches(spec, {"unit": "percentage_points"})
    assert not resolve_pending.adapter_unit_matches(spec, None)
    assert resolve_pending.intl_value_valid(spec, 4.4)
    assert not resolve_pending.intl_value_valid(spec, 4400)

    resolve_pending._require_allowed_host(
        "https://data.api.abs.gov.au/rest/data/LF/example",
        spec["allowed_hosts"],
    )
    with pytest.raises(ValueError, match="allowlist"):
        resolve_pending._require_allowed_host(
            "https://evil.example/rest/data/LF/example",
            spec["allowed_hosts"],
        )
    with pytest.raises(ValueError, match="HTTPS"):
        resolve_pending._require_allowed_host(
            "http://data.api.abs.gov.au/rest/data/LF/example",
            spec["allowed_hosts"],
        )
    redirects = resolve_pending._PinnedRedirectHandler(spec["allowed_hosts"])
    request = resolve_pending.urllib.request.Request(
        "https://data.api.abs.gov.au/rest/data/LF/example"
    )
    with pytest.raises(ValueError, match="allowlist"):
        redirects.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://evil.example/redirected",
        )
    with pytest.raises(ValueError, match="HTTPS"):
        redirects.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "http://data.api.abs.gov.au/redirected",
        )

    binding = {
        **resolve_pending.intl_binding_template(spec),
        "allowedHosts": spec["allowed_hosts"],
    }
    assert resolve_pending.intl_binding_mismatches(spec, binding) == []
    assert "field" in resolve_pending.intl_binding_mismatches(
        spec, {**binding, "field": "neighboring-series"}
    )
    window = {"start": "2026-07-23", "end": "2026-07-23"}
    assert (
        resolve_pending.snapshot_window_state(dt.date(2026, 7, 22), window) == "pending"
    )
    assert resolve_pending.snapshot_window_state(dt.date(2026, 7, 23), window) == "open"
    assert (
        resolve_pending.snapshot_window_state(dt.date(2026, 7, 24), window) == "missed"
    )


def test_unverified_international_candidates_are_not_executable() -> None:
    blocked = resolve_pending.INTL_BLOCKED_ADAPTERS
    for stem in [
        "statcan.lfs.unemployment_rate.canada",
        "statcan.lfs.employment_change.canada",
        "statcan.employment_insurance.regular_beneficiaries",
        "abs.labour.employment_change.australia",
        "abs.building_approvals.total_dwellings_mom.australia",
        "eurostat.unemployment_rate",
        "eurostat.construction.production_index",
        "ons.cpi.annual_rate",
        "ons.labour.claimant_count",
        "ons.retail_sales.volume_mom",
        "ons.pusf.j5ii.public_sector_net_borrowing_ex_banks",
    ]:
        assert stem in blocked
        assert stem not in resolve_pending.INTL_ADAPTERS


def test_intl_transforms_reproduce_published_rounding() -> None:
    # YoY from rounded index, one decimal — how StatCan publishes 12-month
    # CPI changes.
    spec = {"transform": "yoy_from_index", "round": 1}
    series = {"2025-05": 164.3, "2026-05": 169.6}
    assert resolve_pending.intl_transformed_value(spec, series, "2026-05") == 3.2
    # MoM percent from SA levels, one decimal (StatCan monthly GDP).
    spec = {"transform": "mom_pct", "round": 1}
    series = {"2026-03": 2340099.0, "2026-04": 2352903.0}
    assert resolve_pending.intl_transformed_value(spec, series, "2026-04") == 0.5
    # MoM diff in thousands, one decimal (ABS employment change).
    spec = {"transform": "mom_diff", "round": 1}
    series = {"2026-04": 14698.4961423, "2026-05": 14738.83914046}
    assert resolve_pending.intl_transformed_value(spec, series, "2026-05") == 40.3
    # Level with persons->thousands scaling (StatCan EI beneficiaries).
    spec = {"transform": "level", "scale": 0.001, "round": 2}
    series = {"2026-04": 544440.0}
    assert resolve_pending.intl_transformed_value(spec, series, "2026-04") == 544.44
    # Missing prior periods fail closed rather than fabricating a change.
    spec = {"transform": "yoy_from_index", "round": 1}
    assert (
        resolve_pending.intl_transformed_value(spec, {"2026-05": 169.6}, "2026-05")
        is None
    )
    # A declared quarterly adapter steps back three months, not one.
    spec = {
        "transform": "mom_diff",
        "period_type": "quarter",
        "round": 1,
    }
    assert (
        resolve_pending.intl_transformed_value(
            spec,
            {"2026-01": 95.0, "2026-03": 98.0, "2026-04": 100.0},
            "2026-04",
        )
        == 5.0
    )


def test_ons_parser_handles_real_three_letter_month_labels() -> None:
    # Values and field shape mirror the official D7G7 time-series response;
    # this is a parser unit test, not an admission fixture.
    raw = json.dumps(
        {
            "months": [
                {"date": "2026 JUN", "value": "2.6"},
                {"date": "2026 MAY", "value": "2.8"},
                {"date": "not a month", "value": "99"},
                {"date": "2026 APR", "value": ".."},
            ]
        }
    ).encode()
    assert resolve_pending.ons_series_from_payload(raw, "D7G7") == {
        "2026-05": 2.8,
        "2026-06": 2.6,
    }
    with pytest.raises(ValueError, match="no numeric monthly observations"):
        resolve_pending.ons_series_from_payload(
            json.dumps({"months": [{"date": "2026 APR", "value": ".."}]}).encode(),
            "D7G7",
        )


def test_intl_anchor_gate_refuses_series_that_cannot_reproduce_history() -> None:
    spec = {
        "transform": "level",
        "round": 1,
        "anchors": {"2026-03": 4.3, "2026-04": 4.5},
        "anchor_tolerance": 0.15,
    }
    good = {"2026-03": 4.27841116, "2026-04": 4.48133963, "2026-05": 4.35594887}
    assert resolve_pending.intl_anchor_failures(spec, good) == []
    # A neighboring series (participation rate ~66.7) cannot reproduce the
    # recorded unemployment-rate history and must be refused.
    wrong_series = {"2026-03": 66.8, "2026-04": 66.7, "2026-05": 66.7}
    failures = resolve_pending.intl_anchor_failures(spec, wrong_series)
    assert len(failures) == 2
    # A missing anchor period is a failure, never a silent pass.
    assert resolve_pending.intl_anchor_failures(spec, {"2026-04": 4.5}) != []
    # raw_level anchors pin the fetched series itself (ABS employment).
    raw_spec = {
        "transform": "mom_diff",
        "round": 1,
        "anchor_transform": "raw_level",
        "anchors": {"2026-05": 14738.8},
        "anchor_tolerance": 60.0,
    }
    assert (
        resolve_pending.intl_anchor_failures(
            raw_spec, good | {"2026-05": 14738.83914046}
        )
        == []
    )
    assert (
        resolve_pending.intl_anchor_failures(raw_spec, {"2026-05": 14698.5 - 200}) != []
    )


def test_intl_plausibility_gate_blocks_per_adapter_scale_blunders() -> None:
    # Canada CPI cell (percent): the index level must never resolve the
    # YoY cell.
    forecast = {"interval80": {"lower": 2.1, "upper": 3.3}}
    assert not resolve_pending.value_plausible(169.6, forecast)
    assert resolve_pending.value_plausible(3.2, forecast)
    # EI beneficiaries cell (thousands): raw persons must be refused.
    forecast = {"interval80": {"lower": 520, "upper": 557}}
    assert not resolve_pending.value_plausible(544440.0, forecast)
    assert resolve_pending.value_plausible(544.44, forecast)
    # ABS employment change cell (thousands): the level is not the change.
    forecast = {"interval80": {"lower": -35, "upper": 75}}
    assert not resolve_pending.value_plausible(14738.8, forecast)
    assert resolve_pending.value_plausible(40.3, forecast)
    # Euro retail MoM (percent_growth): a YoY-style 12-month rate of the
    # wrong magnitude class is caught by the interval gate.
    forecast = {"interval80": {"lower": -0.8, "upper": 0.9}}
    assert not resolve_pending.value_plausible(12.0, forecast)
    assert resolve_pending.value_plausible(0.2, forecast)


def test_eurostat_flash_flag_gate() -> None:
    spec = {"require_flag": True}
    # June still flagged as estimate: the flash vintage is retrievable.
    assert not resolve_pending.flash_vintage_missing(spec, {"2026-06": "e"}, "2026-06")
    # Finals published: the flag is gone and the flash must not resolve
    # from this endpoint anymore.
    assert resolve_pending.flash_vintage_missing(spec, {}, "2026-06")
    # Non-flash specs are unaffected.
    assert not resolve_pending.flash_vintage_missing({}, {}, "2026-06")


def test_release_page_headline_parsers_sign_and_month_binding() -> None:
    retail = (
        "<h1>Volume of retail trade up by 0.2% in the euro area and by "
        "0.5% in the EU</h1><p>In May 2026, compared with April 2026, the "
        "seasonally adjusted retail trade volume increased by 0.2% in the "
        "euro area and by 0.5% in the EU.</p>"
    ).encode()
    assert resolve_pending.eurostat_retail_headline(retail, "2026-05") == 0.2
    # The parser binds to the page's own reference month: asking the May
    # page for April returns nothing rather than the wrong month's print.
    assert resolve_pending.eurostat_retail_headline(retail, "2026-04") is None
    falling = retail.replace(b"increased", b"decreased")
    assert resolve_pending.eurostat_retail_headline(falling, "2026-05") == -0.2

    approvals = (
        "<h2>Key statistics</h2><p>The May 2026 seasonally adjusted "
        "estimate:</p><ul><li>Total dwellings approved fell 1.1% to "
        "17,019.</li></ul>"
    ).encode()
    assert resolve_pending.abs_ba_headline(approvals, "2026-05") == -1.1
    assert resolve_pending.abs_ba_headline(approvals, "2026-04") is None
    rising = approvals.replace(b"fell 1.1%", b"rose 3.4%")
    assert resolve_pending.abs_ba_headline(rising, "2026-05") == 3.4


def test_intl_fact_rows_carry_country_geography_and_concept() -> None:
    spec = resolve_pending.INTL_ADAPTERS["statcan.cpi.allitems.yoy"]
    row = resolve_pending.generic_fact(
        "statcan.cpi.allitems.yoy.2026-05",
        spec,
        "month",
        "2026-05",
        3.2,
        __import__("datetime").date(2026, 6, 22),
        "https://www150.statcan.gc.ca/t1/wds/rest/example",
        spec["source_file"],
    )
    assert row["geography"]["id"] == "CA"
    assert row["geography"]["name"] == "Canada"
    assert row["measure"]["concept"] == "statcan.cpi.allitems.yoy.2026-05"
    assert row["measure"]["unit"] == "percent"
    assert row["source_row_keys"] == ["2026-05", "2025-05"]

    gdp_spec = resolve_pending.INTL_ADAPTERS["statcan.gdp_by_industry.monthly_growth"]
    gdp_row = resolve_pending.generic_fact(
        "statcan.gdp_by_industry.monthly_growth.2026-04.first_print",
        gdp_spec,
        "month",
        "2026-04",
        0.5,
        __import__("datetime").date(2026, 6, 30),
        "https://www150.statcan.gc.ca/t1/wds/rest/example",
        gdp_spec["source_file"],
    )
    assert gdp_row["source_row_keys"] == ["2026-04", "2026-03"]

    flash_spec = resolve_pending.INTL_ADAPTERS["eurostat.ea.hicp.flash.yoy"]
    row = resolve_pending.generic_fact(
        "eurostat.hicp.all_items_annual_rate.euro_area.june_2026.flash",
        flash_spec,
        "month",
        "2026-06",
        2.8,
        __import__("datetime").date(2026, 7, 1),
        "https://ec.europa.eu/eurostat/api/example",
        flash_spec["source_file"],
    )
    assert row["geography"]["id"] == "EA21"
    # The euro area must use a level the ledger's arch fact schema admits
    # (the append gate rejected "area"; regression for PolicyEngine/chronicle#90).
    assert row["geography"]["level"] == "region"
    # The print-kind suffix is stripped from the measure concept.
    assert row["measure"]["concept"] == (
        "eurostat.hicp.all_items_annual_rate.euro_area.june_2026"
    )
    # US adapters keep the existing geography.
    us_row = resolve_pending.generic_fact(
        "bls.cps.unemployment_rate.june_2026.first_print",
        resolve_pending.ALFRED_ADAPTERS["bls.cps.unemployment_rate"],
        "month",
        "2026-06",
        4.1,
        __import__("datetime").date(2026, 7, 2),
        "https://alfred.stlouisfed.org/example",
        "alfredgraph.csv",
    )
    assert us_row["geography"]["id"] == "0100000US"


def test_intl_dialects_share_one_spec_so_dialects_share_archives() -> None:
    adapters = resolve_pending.INTL_ADAPTERS
    assert (
        adapters["statcan.cpi.all_items_annual_rate.canada"]
        is (adapters["statcan.cpi.allitems.yoy"])
    )
    assert (
        adapters["eurostat.hicp.all_items_annual_rate.euro_area"]
        is (adapters["eurostat.ea.hicp.flash.yoy"])
    )
    assert (
        adapters["abs.cpi.all_groups_annual_rate.australia"]
        is (adapters["abs.cpi_indicator.allgroups.yoy"])
    )
    assert (
        adapters["statcan.gdp_by_industry.monthly_growth"]
        is (
            adapters[
                "statcan.36-10-0434-01.all_industries.month_to_month_percent_change"
            ]
        )
    )


def test_pending_adapter_refs_maps_cms_provider_data_cells() -> None:
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "nh-staffing",
                "resolutionDate": "2026-07-29",
                "unit": "ratio",
                "interval80": {"lower": 3.8, "upper": 3.95},
            },
        ],
        "resolutionLinks": [
            {
                "status": "pending",
                "forecastSlug": "nh-staffing",
                "targetFactRef": (
                    "cms.nursing_home_compare"
                    ".reported_total_nurse_staffing_hprd_us"
                    ".2026-07.first_print"
                ),
            },
        ],
    }

    todo = resolve_pending.pending_adapter_refs(log)

    assert len(todo) == 1
    ref, kind, spec, period_type, period, release_date, forecast = todo[0]
    assert kind == "cms_provider_data"
    assert spec["state_row"] == "NATION"
    assert spec["unit"] == forecast["unit"] == "ratio"
    assert (period_type, period) == ("month", "2026-07")
    assert release_date == "2026-07-29"


def test_cms_provider_data_gate_windows() -> None:
    gate = resolve_pending.cms_provider_data_gate
    assert gate("2026-07", "2026-06-01").startswith("pending")
    assert gate("2026-07", "2026-07-01") is None
    assert gate("2026-07", "2026-07-31") is None
    assert gate("2026-07", "2026-08-01").startswith("missed")
    # December window rolls into the next year.
    assert gate("2026-12", "2026-12-15") is None
    assert gate("2026-12", "2027-01-01").startswith("missed")


CMS_SPEC = resolve_pending.CMS_PROVIDER_DATA_ADAPTERS[
    "cms.nursing_home_compare.reported_total_nurse_staffing_hprd_us"
]

CMS_CSV = (
    '"State or Nation","Overall Rating",'
    '"Reported Total Nurse Staffing Hours per Resident per Day",'
    '"Processing Date"\n'
    "NATION,3.0,3.87157,2026-07-01\n"
    "AK,3.3,6.92970,2026-07-01\n"
).encode()


def test_cms_provider_data_value_reads_nation_row() -> None:
    value, refusal = resolve_pending.cms_provider_data_value(
        CMS_CSV, CMS_SPEC, "2026-07-01"
    )
    assert refusal is None
    assert value == 3.872


def test_cms_provider_data_value_fails_closed() -> None:
    # Missing value column.
    broken = CMS_CSV.replace(b"Reported Total Nurse Staffing", b"Renamed")
    value, refusal = resolve_pending.cms_provider_data_value(
        broken, CMS_SPEC, "2026-07-01"
    )
    assert value is None and "not both present" in refusal

    # File Processing Date disagreeing with the metastore vintage.
    value, refusal = resolve_pending.cms_provider_data_value(
        CMS_CSV, CMS_SPEC, "2026-08-01"
    )
    assert value is None and "disagrees" in refusal

    # Value outside the fail-closed sanity range (wrong row/column class).
    silly = CMS_CSV.replace(b"3.87157", b"387.157")
    value, refusal = resolve_pending.cms_provider_data_value(
        silly, CMS_SPEC, "2026-07-01"
    )
    assert value is None and "sanity range" in refusal


CMS_OCC_SPEC = resolve_pending.CMS_PROVIDER_DATA_ADAPTERS[
    "cms.care_compare.nursing_home_occupancy_pct"
]

CMS_PROVIDER_CSV = (
    '"Federal Provider Number","Number of Certified Beds",'
    '"Average Number of Residents per Day","Processing Date"\n'
    "015009,100,80.0,2026-07-01\n"
    "015010,50,45.5,2026-07-01\n"
    "015011,,not reported,2026-07-01\n"
    "015012,200,150.5,2026-07-01\n"
).encode()


def test_cms_provider_data_value_aggregate_sum_ratio() -> None:
    spec = {**CMS_OCC_SPEC, "aggregate": {**CMS_OCC_SPEC["aggregate"], "min_rows": 3}}
    value, refusal = resolve_pending.cms_provider_data_value(
        CMS_PROVIDER_CSV, spec, "2026-07-01"
    )
    assert refusal is None
    # (80 + 45.5 + 150.5) / (100 + 50 + 200) * 100 = 78.857...
    assert value == 78.86


def test_cms_provider_data_value_aggregate_fails_closed() -> None:
    spec = {**CMS_OCC_SPEC, "aggregate": {**CMS_OCC_SPEC["aggregate"], "min_rows": 3}}
    # Truncated download: fewer usable rows than the floor.
    truncated = b"\n".join(CMS_PROVIDER_CSV.split(b"\n")[:3]) + b"\n"
    value, refusal = resolve_pending.cms_provider_data_value(
        truncated, spec, "2026-07-01"
    )
    assert value is None and "usable rows" in refusal

    # Processing Date drift on the first row.
    value, refusal = resolve_pending.cms_provider_data_value(
        CMS_PROVIDER_CSV, spec, "2026-08-01"
    )
    assert value is None and "disagrees" in refusal

    # Renamed denominator column.
    renamed = CMS_PROVIDER_CSV.replace(b"Number of Certified Beds", b"Beds")
    value, refusal = resolve_pending.cms_provider_data_value(
        renamed, spec, "2026-07-01"
    )
    assert value is None and "not both present" in refusal


def test_write_side_accepts_the_intl_period_suffixed_concept_exactly() -> None:
    """International ledger rows (abs/eurostat/statjp, immutable precedent)
    carry concept == dataPointId minus the release-policy token. Only that
    identity-derived form is accepted; wrong periods, whole record ids, and
    unrelated series still refuse (the 2026-07-23/24 resolution outage)."""

    registration = {
        "targetContentHash": "a" * 64,
        "contract": {
            "dataPointId": (
                "abs.labour.employment_change.australia.june_2026.first_print"
            ),
            "series": "abs.labour.employment_change.australia",
            "period": "2026-06",
            "unit": "thousands of persons",
            "sourceBinding": {
                "releasePolicy": "first_print",
                "table": "ABS Labour Force, Australia",
                "field": "employment_change",
                "transform": {"operation": "multiply", "factor": 0.001},
            },
        },
        "ledgerPin": None,
    }

    def row(concept: str) -> dict:
        return {
            "source_record_id": (
                "abs.labour.employment_change.australia.june_2026.first_print"
            ),
            "value": 25.4,
            "measure": {"concept": concept, "unit": "thousands of persons"},
        }

    ok = resolve_pending.source_binding_projection(
        registration,
        row("abs.labour.employment_change.australia.june_2026"),
        b"raw",
    )
    assert ok["series"] == "abs.labour.employment_change.australia"

    for bad in [
        # Wrong period: not a prefix of THIS record id.
        "abs.labour.employment_change.australia.may_2026",
        # The whole record id (policy token included) is not a concept.
        "abs.labour.employment_change.australia.june_2026.first_print",
        # Unrelated series never passes, suffixed or not.
        "abs.labour.unemployment_rate.australia.june_2026",
    ]:
        try:
            resolve_pending.source_binding_projection(registration, row(bad), b"x")
        except ValueError as error:
            assert "concept" in str(error)
        else:
            raise AssertionError(f"malformed concept accepted: {bad}")


def test_binding_adapter_mismatch_guards_family_routing() -> None:
    """A registration's binding adapter is authoritative: a generic-url
    registration (the prospect miner's) must never be resolved by a
    series-stem family that shares the series name (the 2026-07-25
    new-home-sales collision), while matching and legacy registrations
    pass through."""

    def reg(adapter):
        return {"contract": {"sourceBinding": {"adapter": adapter}}}

    mismatch = resolve_pending.binding_adapter_mismatch
    assert mismatch("alfred", reg("generic-url")) == "generic-url"
    assert mismatch("alfred", reg("alfred-fred")) is None
    assert mismatch("usaspending", reg("usaspending-api")) is None
    assert mismatch("usaspending", reg("generic-url")) == "generic-url"
    # Legacy targets without registrations or bindings stay resolvable.
    assert mismatch("alfred", None) is None
    assert mismatch("alfred", {"contract": {}}) is None
    # Families without a declared adapter set are not constrained here.
    assert mismatch("intl", reg("generic-url")) is None


# ---------------------------------------------------------------------------
# Aging/disability batch (2026-08-23): BLS CPS/CES/LAUS, SSA official pages,
# VA MMWR, SSA hearings.

AGING_FIXTURES = ROOT / "tests" / "fixtures" / "ssa_official"


def _aging_log() -> dict:
    cells = [
        (
            "va-pending",
            "va.vba.mmwr.claims_inventory.week_2026-07-13.first_print",
            "2026-07-13",
            "thousands",
            597.8,
            609.6,
        ),
        (
            "ssi-65",
            "ssa.ssi.recipients_aged_65_plus.2026_06.first_print",
            "2026-07-31",
            "thousands",
            2496.2,
            2510.0,
        ),
        (
            "ssdi",
            "ssa.oasdi.disabled_worker_beneficiaries.2026-06.first_print",
            "2026-07-31",
            "thousands",
            7002.0,
            7017.0,
        ),
        (
            "hearings",
            "ssa.hearings.average_processing_time_days.2026-06.first_print",
            "2026-07-31",
            "count",
            322.0,
            330.0,
        ),
        (
            "lfpr",
            "bls.cps.lfpr_55_plus.2026-07.first_print",
            "2026-08-07",
            "percent",
            37.0,
            37.2,
        ),
        (
            "epop",
            "bls.cps.LNU02374597.2026-07.first_print",
            "2026-08-07",
            "percent",
            20.9,
            22.3,
        ),
        (
            "hhc",
            "bls.ces.home_health_care_services.employment.2026-07.first_print",
            "2026-08-07",
            "thousands",
            1881.5,
            1896.1,
        ),
        (
            "co-ssi",
            "ssa.ssi.recipients.colorado.2026-07.first_print",
            "2026-08-31",
            "thousands",
            66.181,
            66.581,
        ),
        (
            "co-ssi-65",
            "ssa.ssi.recipients.colorado.aged_65_plus.2026-07.first_print",
            "2026-08-31",
            "count",
            23024.0,
            23096.0,
        ),
        (
            "ssi-total",
            "ssa.ssi.total_recipients.2026-07.first_print",
            "2026-08-31",
            "millions",
            7.28,
            7.338,
        ),
        (
            "co-lf",
            "bls.laus.colorado.labor_force.2026-07.first_print",
            "2026-08-21",
            "thousands",
            3179.0,
            3185.4,
        ),
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


def test_pending_adapter_refs_maps_the_aging_disability_batch() -> None:
    todo = {
        ref: item
        for item in resolve_pending.pending_adapter_refs(_aging_log())
        for ref in [item[0]]
    }
    assert len(todo) == 11

    def claim(ref):
        _ref, kind, spec, period_type, period, release, forecast = todo[ref]
        assert resolve_pending.adapter_unit_matches(spec, forecast), ref
        return kind, spec, period_type, period

    kind, spec, period_type, period = claim(
        "va.vba.mmwr.claims_inventory.week_2026-07-13.first_print"
    )
    assert (kind, period_type, period) == ("va_mmwr", "week", "2026-07-13")
    assert spec["anchors"] == {
        "2026-06-22": 593770,
        "2026-06-29": 589026,
        "2026-07-06": 601630,
    }
    kind, spec, period_type, period = claim(
        "ssa.ssi.recipients_aged_65_plus.2026_06.first_print"
    )
    assert (kind, spec["reader"], period) == ("ssa_official", "ssi_table1", "2026-06")
    # Longest stem wins: the 65+ Colorado cell is not the Colorado total.
    kind, spec, _, _ = claim(
        "ssa.ssi.recipients.colorado.aged_65_plus.2026-07.first_print"
    )
    assert (spec["reader"], spec["column"], spec["unit"]) == (
        "ssi_table4",
        "65 or older",
        "count",
    )
    kind, spec, _, _ = claim("ssa.ssi.recipients.colorado.2026-07.first_print")
    assert (spec["column"], spec["unit"], spec["scale"]) == (
        "Total",
        "thousands",
        0.001,
    )
    kind, spec, _, _ = claim("ssa.ssi.total_recipients.2026-07.first_print")
    assert (spec["reader"], spec["unit"]) == ("ssi_table2", "millions")
    kind, spec, _, _ = claim(
        "ssa.oasdi.disabled_worker_beneficiaries.2026-06.first_print"
    )
    assert (spec["reader"], spec["row"]) == ("snapshot_table2", "Disabled workers")
    kind, spec, _, _ = claim(
        "ssa.hearings.average_processing_time_days.2026-06.first_print"
    )
    assert (kind, spec["reader"]) == ("ssa_official", "oho_workload_xml")
    for ref, series_id, gate in [
        ("bls.cps.lfpr_55_plus.2026-07.first_print", "LNS11324230", "latest_month"),
        ("bls.cps.LNU02374597.2026-07.first_print", "LNU02374597", "latest_month"),
        (
            "bls.ces.home_health_care_services.employment.2026-07.first_print",
            "CES6562160001",
            "latest_preliminary",
        ),
        (
            "bls.laus.colorado.labor_force.2026-07.first_print",
            "LASST080000000000006",
            "latest_preliminary",
        ),
    ]:
        kind, spec, period_type, period = claim(ref)
        assert (kind, spec["series_id"], period) == ("bls_api", series_id, "2026-07")
        assert spec.get("first_print_gate", "latest_preliminary") == gate
        assert len(spec["anchors"]) >= 3
    laus = resolve_pending.BLS_API_ADAPTERS["bls.laus.colorado.labor_force"]
    assert (laus["scale"], laus["round"]) == (0.001, 1)
    # Every aging family is bound to a named binding adapter, and a
    # generic-url registration stays out of it.
    mismatch = resolve_pending.binding_adapter_mismatch
    generic = {"contract": {"sourceBinding": {"adapter": "generic-url"}}}
    assert mismatch("ssa_official", generic) == "generic-url"
    assert mismatch("va_mmwr", generic) == "generic-url"
    assert (
        mismatch(
            "ssa_official",
            {"contract": {"sourceBinding": {"adapter": "ssa-official-page"}}},
        )
        is None
    )


def test_bls_cps_latest_month_gate_and_preliminary_gate_disagree_on_cps_rows() -> None:
    # CPS rows never carry the preliminary footnote (live API, 2026-08-23).
    rows = {
        "2026-07": {"value": 36.9, "latest": True, "preliminary": False},
        "2026-06": {"value": 37.1, "latest": False, "preliminary": False},
    }
    assert resolve_pending.bls_first_print(rows, "2026-07", "latest_month") == (
        36.9,
        None,
    )
    value, refusal = resolve_pending.bls_first_print(rows, "2026-06", "latest_month")
    assert value is None and "no longer the latest month" in refusal
    assert resolve_pending.bls_first_print(rows, "2026-08", "latest_month") == (
        None,
        None,
    )
    # The default gate would refuse CPS forever; the specs opt out explicitly.
    value, refusal = resolve_pending.bls_first_print(rows, "2026-07")
    assert value is None and "latest preliminary" in refusal
    with pytest.raises(ValueError, match="unknown BLS first-print gate"):
        resolve_pending.bls_first_print(rows, "2026-07", "whenever")
    notes = resolve_pending.BLS_API_ADAPTERS["bls.cps.lfpr_55_plus"]["evidence_notes"]
    assert "not to revise previous months" in notes


class _FakeCapture:
    """Stand-in for official_browser_fetch.BrowserCapture."""

    def __init__(
        self, url: str, body: bytes, retrieved_at: str = "2026-08-23T14:00:00Z"
    ):
        self.url = url
        self.final_url = url
        self.status = 200
        self.headers = {"content-type": "text/html; charset=UTF-8"}
        self.body = body
        self.retrieved_at = retrieved_at
        self.user_agent = (
            "HeadlessChrome/151 thesis-resolver/1.0 (+https://app.thesisinstitute.org)"
        )
        self.engine = "chromium 151 (playwright 1.62.0)"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    def transport_record(self):
        return {
            "kind": "headless-browser",
            "engine": self.engine,
            "userAgent": self.user_agent,
            "redirectsAccepted": False,
        }

    def response_record(self):
        return {
            "url": self.url,
            "finalUrl": self.final_url,
            "status": self.status,
            "headers": dict(self.headers),
            "retrievedAt": self.retrieved_at,
            "bytes": len(self.body),
            "sha256": self.sha256,
        }


def _ssa_fixture_pages() -> dict[str, bytes]:
    base = "https://www.ssa.gov/policy/docs"
    return {
        f"{base}/statcomps/ssi_monthly/2026-06/table01.html": (
            AGING_FIXTURES / "ssi_2026-06_table01.html"
        ).read_bytes(),
        f"{base}/statcomps/ssi_monthly/2026-05/table01.html": (
            AGING_FIXTURES / "ssi_2026-05_table01.html"
        ).read_bytes(),
        f"{base}/quickfacts/stat_snapshot/2026-06.html": (
            AGING_FIXTURES / "stat_snapshot_2026-06.html"
        ).read_bytes(),
        f"{base}/quickfacts/stat_snapshot/2026-05.html": (
            AGING_FIXTURES / "stat_snapshot_2026-05.html"
        ).read_bytes(),
        "https://www.ssa.gov/appeals/DataSets/02_HO_Workload_Data.xml": (
            AGING_FIXTURES / "ho_workload_2026-06-26.xml"
        ).read_bytes(),
    }


def _install_aging_main(
    monkeypatch, refs: list[str], *, utc_now="2026-08-23T14:05:00Z"
):
    import official_browser_fetch

    log = _aging_log()
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
    monkeypatch.setattr(resolve_pending, "utc_now", lambda: utc_now)
    pages = _ssa_fixture_pages()
    fetched: list[str] = []
    pages_box = {"pages": pages}

    def fake_browser_fetch(url, *, allowed_hosts=None, timeout_seconds=90.0):
        pages = pages_box["pages"]
        fetched.append(url)
        if url not in pages:
            raise official_browser_fetch.BrowserFetchError(f"HTTP 404 for {url}")
        return _FakeCapture(url, pages[url])

    monkeypatch.setattr(official_browser_fetch, "browser_fetch", fake_browser_fetch)
    envelopes: dict[str, bytes] = {}
    real_envelope = resolve_pending.ssa_capture_envelope

    def record_envelope(**kwargs):
        raw = real_envelope(**kwargs)
        envelopes[kwargs["period"] + ":" + kwargs["spec"]["reader"]] = raw
        return raw

    monkeypatch.setattr(resolve_pending, "ssa_capture_envelope", record_envelope)
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])
    return fetched, envelopes, pages


def test_main_ssa_official_leg_resolves_editions_through_the_browser_transport(
    monkeypatch, capsys
) -> None:
    refs = [
        "ssa.ssi.recipients_aged_65_plus.2026_06.first_print",
        "ssa.oasdi.disabled_worker_beneficiaries.2026-06.first_print",
    ]
    fetched, envelopes, _pages = _install_aging_main(monkeypatch, refs)
    snapshot_url = (
        "https://www.ssa.gov/policy/docs/quickfacts/stat_snapshot/2026-06.html"
    )

    def fake_wayback(url: str) -> bytes:
        if "cdx/search" in url:
            if "stat_snapshot/2026-06.html" in url:
                return (AGING_FIXTURES / "cdx_stat_snapshot_2026-06.json").read_bytes()
            return b"[]"
        assert url.endswith(snapshot_url)
        return (
            AGING_FIXTURES / "stat_snapshot_2026-06.wayback-20260711204033.html"
        ).read_bytes()

    monkeypatch.setattr(resolve_pending, "ssa_wayback_fetch", fake_wayback)

    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert (
        "  resolve ssa.ssi.recipients_aged_65_plus.2026_06.first_print"
        " -> 2505.847 thousands" in out
    )
    assert (
        "  resolve ssa.oasdi.disabled_worker_beneficiaries.2026-06.first_print"
        " -> 7006.0 thousands" in out
    )
    assert "dry-run: would append 2 row(s)" in out
    # Anchors (prior editions) were re-read before the target pages.
    assert fetched.index(
        "https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2026-05/table01.html"
    ) < fetched.index(
        "https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2026-06/table01.html"
    )
    envelope = json.loads(envelopes["2026-06:snapshot_table2"])
    assert envelope["schemaVersion"] == "ssa_official_page_capture_v1"
    assert envelope["transport"]["kind"] == "headless-browser"
    assert envelope["wayback"]["status"] == "parsed"
    assert envelope["wayback"]["corroboratingCapture"]["timestamp"] == "20260711204033"
    assert envelope["wayback"]["corroboratingCapture"]["value"] == 7006
    assert envelope["anchors"][0]["period"] == "2026-05"
    assert envelope["anchors"][0]["observed"] == 7029
    assert (
        envelope["derived"]["rawValue"] == 7006
        and envelope["derived"]["value"] == 7006.0
    )
    table1 = json.loads(envelopes["2026-06:ssi_table1"])
    assert table1["wayback"]["status"] == "none"
    assert table1["derived"]["identities"][0].startswith("Total: Under 18 + 18-64")


def test_main_ssa_official_leg_refuses_a_disagreeing_wayback_capture(
    monkeypatch, capsys
) -> None:
    refs = ["ssa.oasdi.disabled_worker_beneficiaries.2026-06.first_print"]
    _install_aging_main(monkeypatch, refs)
    archived = (
        AGING_FIXTURES / "stat_snapshot_2026-06.wayback-20260711204033.html"
    ).read_bytes()
    # Same page, different first print: a 1-unit change in every DI cell
    # keeps the identities valid but moves the target.
    tampered = (
        archived.replace(b">7,006<", b">7,007<")
        .replace(b">8,008<", b">8,009<")
        .replace(b">71,255<", b">71,256<")
    )

    def fake_wayback(url: str) -> bytes:
        if "cdx/search" in url:
            return (AGING_FIXTURES / "cdx_stat_snapshot_2026-06.json").read_bytes()
        return tampered

    monkeypatch.setattr(resolve_pending, "ssa_wayback_fetch", fake_wayback)
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert "WAYBACK CAPTURE DISAGREES (refusing, page revised in place?)" in out
    assert "live 7006 vs capture 20260711204033 7007" in out
    assert "nothing new to record" in out


def test_main_ssa_official_leg_refuses_anchor_drift_before_the_target(
    monkeypatch, capsys
) -> None:
    refs = ["ssa.ssi.recipients_aged_65_plus.2026_06.first_print"]
    fetched, _envelopes, _pages = _install_aging_main(monkeypatch, refs)
    monkeypatch.setitem(
        resolve_pending.SSA_OFFICIAL_ADAPTERS["ssa.ssi.recipients_aged_65_plus"],
        "anchors",
        {"2026-05": 2501548},
    )
    monkeypatch.setattr(resolve_pending, "ssa_wayback_fetch", lambda _u: b"[]")
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert "ANCHOR MISMATCH (refusing, wrong SSA table cell?)" in out
    assert "anchor 2026-05=2501549 (recorded 2501548)" in out
    assert not any(url.endswith("2026-06/table01.html") for url in fetched)


def test_main_ssa_hearings_leg_refuses_because_the_source_has_no_national_row(
    monkeypatch, capsys
) -> None:
    refs = ["ssa.hearings.average_processing_time_days.2026-06.first_print"]
    _install_aging_main(monkeypatch, refs)
    monkeypatch.setattr(resolve_pending, "ssa_wayback_fetch", lambda _u: b"[]")
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert "SOURCE PUBLISHES NO NATIONAL AGGREGATE (refusing)" in out
    assert "RPTG_PRD_ENDT 06/26/2026, 165 hearing-office rows" in out
    assert "nothing new to record" in out


def test_main_survives_a_refused_wayback_refetch_and_resolves_the_rest(
    monkeypatch, capsys
) -> None:
    """2026-09-01, 09-02 and 09-06: web.archive.org refused one connection
    and the uncaught URLError ended the run, so nothing resolved that day
    was appended. The hearings target must defer and the run must go on."""
    import urllib.error

    hearings = "ssa.hearings.average_processing_time_days.2026-06.first_print"
    other = "ssa.oasdi.disabled_worker_beneficiaries.2026-06.first_print"
    _fetched, _envelopes, pages = _install_aging_main(monkeypatch, [hearings, other])
    archived = (AGING_FIXTURES / "ho_workload_2026-06-26.xml").read_bytes()
    (workload_url,) = [url for url, body in pages.items() if body == archived]
    # The live file has rolled on to July, so June survives only in Wayback.
    pages[workload_url] = archived.replace(b"06/26/2026", b"07/31/2026")
    snapshot_capture = (
        AGING_FIXTURES / "stat_snapshot_2026-06.wayback-20260711204033.html"
    ).read_bytes()
    capture_reads = {"workload": 0}

    def fake_wayback(url: str) -> bytes:
        if "cdx/search" in url:
            if "stat_snapshot/2026-06.html" in url:
                return (AGING_FIXTURES / "cdx_stat_snapshot_2026-06.json").read_bytes()
            if workload_url.split("://", 1)[1] in url:
                return (
                    b'[["timestamp","statuscode","digest","length"],'
                    b'["20260701120000","200","AAAA","1000"]]'
                )
            return b"[]"
        if url.endswith(workload_url):
            capture_reads["workload"] += 1
            if capture_reads["workload"] == 1:
                return archived  # the corroboration's own guarded read
            raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
        return snapshot_capture

    monkeypatch.setattr(resolve_pending, "ssa_wayback_fetch", fake_wayback)

    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert capture_reads["workload"] == 2
    assert f"  WAYBACK FETCH FAILED (deferring): {hearings}" in out
    assert "::warning title=Resolver source unreachable::" in out
    assert f"  resolve {other} -> 7006.0 thousands" in out
    assert "dry-run: would append 1 row(s)" in out


def test_main_ssa_official_leg_treats_a_missing_engine_as_fatal(
    monkeypatch, capsys
) -> None:
    import official_browser_fetch

    refs = ["ssa.ssi.recipients_aged_65_plus.2026_06.first_print"]
    _install_aging_main(monkeypatch, refs)

    def no_engine(url, **_kwargs):
        raise official_browser_fetch.BrowserFetchUnavailableError("playwright missing")

    monkeypatch.setattr(official_browser_fetch, "browser_fetch", no_engine)
    assert resolve_pending.main() == 1
    out = capsys.readouterr().out
    assert "SSA BROWSER ENVIRONMENT FAILURE (fatal)" in out
    assert "environment failures left admitted references unresolvable" in out


def _va_workbook_server(
    monkeypatch, *, target_modified="Mon, 13 Jul 2026 17:30:32 GMT"
):
    sys.path.insert(0, str(ROOT / "tests"))
    from va_mmwr_fixtures import build_workbook

    landing = (
        ROOT / "tests" / "fixtures" / "va_mmwr" / "detailed_claims_data_excerpt.html"
    ).read_bytes()
    books = {
        "MMWR-06-20-2026.xlsx": (
            593770,
            70879,
            "Reporting through June 20, 2026",
            "Mon, 22 Jun 2026 15:42:38 GMT",
        ),
        "MMWR-06-27-2026.xlsx": (
            589026,
            68207,
            "Reporting through June 27, 2026",
            "Mon, 29 Jun 2026 14:06:57 GMT",
        ),
        "MMWR-07-04-2026.xlsx": (
            601630,
            69193,
            "Reporting through July 04, 2026",
            "Tue, 07 Jul 2026 19:33:23 GMT",
        ),
        "MMWR-07-11-2026.xlsx": (
            600878,
            69481,
            "Reporting through July 11, 2026",
            target_modified,
        ),
    }
    served: list[str] = []

    def fake_get(url: str):
        served.append(url)
        if url == resolve_pending.va_mmwr.LANDING_URL:
            return landing, {"content-type": "text/html"}, "2026-08-23T14:00:00Z", url
        name = url.rsplit("/", 1)[-1]
        pending, over, through, modified = books[name]
        raw = build_workbook(pending=pending, over_125=over, through=through)
        headers = {
            "content-type": (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            "last-modified": modified,
            "etag": f'"{name}"',
        }
        return raw, headers, "2026-08-23T14:00:01Z", url

    monkeypatch.setattr(resolve_pending, "va_mmwr_http_get", fake_get)
    return served


def test_main_va_mmwr_leg_resolves_the_report_week_with_anchors(
    monkeypatch, capsys
) -> None:
    ref = "va.vba.mmwr.claims_inventory.week_2026-07-13.first_print"
    _install_aging_main(monkeypatch, [ref])
    served = _va_workbook_server(monkeypatch)
    rows: list[dict] = []
    real_fact = resolve_pending.generic_fact

    def record(*args, **kwargs):
        row = real_fact(*args, **kwargs)
        rows.append(row)
        return row

    monkeypatch.setattr(resolve_pending, "generic_fact", record)
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  resolve {ref} -> 600.878 thousands" in out
    # One landing read, four workbooks (three anchors + target), each once.
    assert served.count(resolve_pending.va_mmwr.LANDING_URL) == 1
    assert sorted(u.rsplit("/", 1)[-1] for u in served[1:]) == [
        "MMWR-06-20-2026.xlsx",
        "MMWR-06-27-2026.xlsx",
        "MMWR-07-04-2026.xlsx",
        "MMWR-07-11-2026.xlsx",
    ]
    row = rows[0]
    assert row["period"] == {"type": "week_ending", "value": "2026-07-11"}
    assert row["observed_at"] == "2026-07-13"
    assert row["source"]["url"].endswith("/REPORTS/mmwr/2026/MMWR-07-11-2026.xlsx")
    assert (
        "Last-Modified header placed its posting"
        in row["measure"]["concept_evidence_notes"]
    )


def test_main_va_mmwr_leg_refuses_a_reposted_workbook_and_anchor_drift(
    monkeypatch, capsys
) -> None:
    ref = "va.vba.mmwr.claims_inventory.week_2026-07-13.first_print"
    _install_aging_main(monkeypatch, [ref])
    _va_workbook_server(monkeypatch, target_modified="Tue, 01 Sep 2026 09:00:00 GMT")
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert "FIRST-PRINT WINDOW MISSED (refusing)" in out and "re-post" in out
    # Anchor drift refuses before the target is even read.
    monkeypatch.setitem(
        resolve_pending.VA_MMWR_ADAPTERS["va.vba.mmwr.claims_inventory"],
        "anchors",
        {"2026-06-22": 593771},
    )
    _va_workbook_server(monkeypatch)
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert "ANCHOR MISMATCH (refusing, wrong VA workbook cell?)" in out
    assert "anchor 2026-06-22=593770 (recorded 593771)" in out


def test_main_defers_ssa_edition_pages_on_404_but_not_on_the_by_date(
    monkeypatch, capsys
) -> None:
    # The Colorado cells' resolutionDate (2026-08-31) is a by-date; the
    # edition page is the release evidence, so a 404 defers and a present
    # page resolves even before that date.
    ref = "ssa.ssi.recipients.colorado.2026-07.first_print"
    _fetched, _envelopes, pages = _install_aging_main(
        monkeypatch, [ref], utc_now="2026-08-23T14:05:00Z"
    )
    base = "https://www.ssa.gov/policy/docs/statcomps/ssi_monthly"
    # The prior edition (anchor) is posted; the target edition is not yet.
    pages[f"{base}/2026-06/table04.html"] = (
        AGING_FIXTURES / "ssi_2026-06_table04.html"
    ).read_bytes()
    monkeypatch.setattr(resolve_pending, "ssa_wayback_fetch", lambda _u: b"[]")
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert "release 2026-08-31 not reached" not in out
    assert "not yet published (deferring)" in out and "HTTP 404" in out
    # Once the edition is posted, the same run resolves before the by-date.
    pages[f"{base}/2026-07/table04.html"] = (
        AGING_FIXTURES / "ssi_2026-07_table04.html"
    ).read_bytes()
    assert resolve_pending.main() == 0
    out = capsys.readouterr().out
    assert f"  resolve {ref} -> 66.284 thousands" in out


# ---------------------------------------------------------------------------
# Registry growth: appends may mint their own first observations, nothing else
# (the 2026-08-17 byte-compare guard overshot — no series could ever take its
# first observation; resolve-loop failures 2026-08-18..22, issues #202-#206).


def _registry_line(**fields) -> bytes:
    return json.dumps(fields).encode() + b"\n"


BASE_REGISTRY = _registry_line(
    concept="dol.eta.continued_claims.sa",
    geography={"level": "country", "id": "0100000US", "vintage": "current"},
    entity={"name": "person", "role": "ui_claimant"},
    uuid="00000000-0000-4000-8000-000000000001",
) + _registry_line(
    concept="census.housing.completions_saar",
    geography=None,
    entity=None,
    uuid="00000000-0000-4000-8000-000000000002",
)
FULL_IDENTITY = {
    "geography": {"level": "country", "id": "0100000US", "vintage": "current"},
    "entity": {"name": "economy", "role": "aggregate"},
}


def test_registry_growth_allows_own_mints_and_placeholder_enrichment() -> None:
    refusal = resolve_pending._registry_growth_refusal
    rows = [
        "va.vba.mmwr.claims_inventory.week_2026-07-13.first_print",
        "census.housing.completions_saar.2026_07.first_print",
    ]
    grown = (
        BASE_REGISTRY
        + _registry_line(
            concept="census.housing.completions_saar",
            geography=None,
            entity=None,
            uuid="00000000-0000-4000-8000-000000000002",
            retired=True,
            note="docket placeholder enriched by first observed identity",
        )
        + _registry_line(
            concept="census.housing.completions_saar",
            **FULL_IDENTITY,
            uuid="00000000-0000-4000-8000-000000000002",
            succeeds={
                "concept": "census.housing.completions_saar",
                "geography": None,
                "entity": None,
            },
        )
        + _registry_line(
            concept="va.vba.mmwr.claims_inventory",
            **FULL_IDENTITY,
            uuid="00000000-0000-4000-8000-000000000003",
        )
    )
    assert refusal(BASE_REGISTRY, grown, rows) is None
    assert refusal(BASE_REGISTRY, BASE_REGISTRY, rows) is None


def test_registry_growth_refuses_everything_beyond_the_appended_rows() -> None:
    refusal = resolve_pending._registry_growth_refusal
    rows = ["va.vba.mmwr.claims_inventory.week_2026-07-13.first_print"]
    mint = dict(concept="va.vba.mmwr.claims_inventory", **FULL_IDENTITY)
    # Rewriting committed lines is never an append.
    assert "rewrites committed lines" in refusal(
        BASE_REGISTRY, BASE_REGISTRY[:-2] + b"x\n", rows
    )
    # An identity that belongs to no appended observation.
    assert "belongs to no observation" in refusal(
        BASE_REGISTRY,
        BASE_REGISTRY
        + _registry_line(
            concept="bea.gdp.advance",
            **FULL_IDENTITY,
            uuid="00000000-0000-4000-8000-000000000009",
        ),
        rows,
    )
    # Single-segment concepts never qualify.
    assert "belongs to no observation" in refusal(
        BASE_REGISTRY,
        BASE_REGISTRY
        + _registry_line(
            concept="va", **FULL_IDENTITY, uuid="00000000-0000-4000-8000-000000000009"
        ),
        rows,
    )
    # Supersede/revive/reclaim events stay chronicle-side.
    assert "['supersedes']" in refusal(
        BASE_REGISTRY,
        BASE_REGISTRY
        + _registry_line(
            **mint,
            uuid="00000000-0000-4000-8000-000000000009",
            supersedes="00000000-0000-4000-8000-000000000001",
            note="x",
        ),
        rows,
    )
    # UUID reuse outside the sanctioned enrichment.
    assert "reuses UUID" in refusal(
        BASE_REGISTRY,
        BASE_REGISTRY
        + _registry_line(**mint, uuid="00000000-0000-4000-8000-000000000001"),
        rows,
    )
    # Appends may not mint placeholders.
    assert "placeholder identity" in refusal(
        BASE_REGISTRY,
        BASE_REGISTRY
        + _registry_line(
            concept="va.vba.mmwr.claims_inventory",
            geography=None,
            entity=None,
            uuid="00000000-0000-4000-8000-000000000009",
        ),
        rows,
    )
    # Retiring anything but a committed placeholder is refused.
    assert "non-placeholder" in refusal(
        BASE_REGISTRY,
        BASE_REGISTRY
        + _registry_line(
            **mint,
            uuid="00000000-0000-4000-8000-000000000009",
            retired=True,
            note="x",
        ),
        rows,
    )
    assert "matches no committed docket placeholder" in refusal(
        BASE_REGISTRY,
        BASE_REGISTRY
        + _registry_line(
            concept="va.vba.mmwr.claims_inventory",
            geography=None,
            entity=None,
            uuid="00000000-0000-4000-8000-000000000009",
            retired=True,
            note="x",
        ),
        ["va.vba.mmwr.claims_inventory.week_2026-07-13.first_print"],
    )
    # A succeeds-mint needs its placeholder retire in the same append.
    assert "without its placeholder retire" in refusal(
        BASE_REGISTRY,
        BASE_REGISTRY
        + _registry_line(
            concept="census.housing.completions_saar",
            **FULL_IDENTITY,
            uuid="00000000-0000-4000-8000-000000000002",
            succeeds={
                "concept": "census.housing.completions_saar",
                "geography": None,
                "entity": None,
            },
        ),
        ["census.housing.completions_saar.2026_07.first_print"],
    )
    # Junk lines fail closed.
    assert "not JSON" in refusal(BASE_REGISTRY, BASE_REGISTRY + b"not json\n", rows)
    assert "lacks concept/uuid" in refusal(
        BASE_REGISTRY, BASE_REGISTRY + b'{"uuid":"new"}\n', rows
    )


def test_append_proposal_accepts_the_generators_own_first_observation_mint(
    tmp_path: pathlib.Path,
) -> None:
    """A staged generator minting exactly the appended row's identity passes."""
    tree, anchor_dir, requester, signing_key_pem = _release_fixture_tree(tmp_path)
    minted_line = json.dumps(
        {
            "concept": "test.series.minted",
            "geography": {"level": "country", "id": "0100000US", "vintage": "current"},
            "entity": {"name": "economy", "role": "aggregate"},
            "uuid": "00000000-0000-4000-8000-00000000aaaa",
        }
    )
    tree.files["scripts/build_series_catalog.py"] = tree.files[
        "scripts/build_series_catalog.py"
    ].replace(
        b"import check_thesis_facts_append  # noqa: F401",
        b"import check_thesis_facts_append  # noqa: F401\n"
        b"import json as json_module\n"
        b"registry_path = pathlib.Path('ledger/series_uuid_registry.jsonl')\n"
        b"registry_path.write_bytes(registry_path.read_bytes() + "
        + repr(minted_line + "\n").encode()
        + b".encode())",
    )
    candidate = (
        tree.files["ledger/official_observations.jsonl"]
        + b'{"source_record_id":"test.series.minted.2026-07.first_print","value":1}\n'
    )
    changes = resolve_pending._prepare_release_files(
        tree,
        path="ledger/official_observations.jsonl",
        candidate_ledger=candidate,
        added=1,
        requester=requester,
        timeout_seconds=10,
        clock_skew_seconds=resolve_pending.DEFAULT_CLOCK_SKEW_SECONDS,
        anchor_dir=anchor_dir,
        now=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=2),
        producer_signing_key=signing_key_pem,
    )
    regenerated = changes["ledger/series_uuid_registry.jsonl"]
    assert regenerated.endswith(minted_line.encode() + b"\n")
    assert regenerated.startswith(tree.files["ledger/series_uuid_registry.jsonl"])
