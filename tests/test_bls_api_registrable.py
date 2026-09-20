"""The six registrable BLS Public Data API docket series.

Fixture bytes are official keyless API responses captured 2026-09-20 (see
``tests/fixtures/bls_api/README.md``). They prove the parser, the transforms
and the binding; they are never resolution evidence.
"""

from __future__ import annotations

import copy
import datetime as dt
import glob
import hashlib
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import register_targets  # noqa: E402
import resolve_pending  # noqa: E402
import roll_docket  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "bls_api"

# series -> (fixture file, sha256 of the captured bytes, the latest month in
# the capture, the value BLS's own release printed for that month first).
CAPTURES = {
    "bls.cps.unemployment_rate": (
        "LNS14000000-2026-2026.json",
        "8a990a8d0a5d513c13e5423ad8aeed8aba6446b551625d53fe2328f9cb7110d3",
        "2026-08",
        4.1,
    ),
    "bls.cpi.u.headline_mom": (
        "CUSR0000SA0-2025-2026.json",
        "18afe3d6ac49e1db380d18fb657c0e0479ab03a8ce47b5ecfe982ed079aa3d5a",
        "2026-08",
        0.4,
    ),
    "bls.cpi.u.core_mom": (
        "CUSR0000SA0L1E-2026-2026.json",
        "1aa489932a6895a1f0309744717a4b434350db3ffe7a2ddc9d8e94f6ce66cb1d",
        "2026-08",
        0.3,
    ),
    "bls.jolts.job_openings": (
        "JTS000000000000000JOL-2026-2026.json",
        "5dea3ebccdaa2bafd965272a8843d04035df48ee69bafcab817a797e00a0e0b0",
        "2026-07",
        7.271,
    ),
    "bls.jolts.quits_rate": (
        "JTS000000000000000QUR-2026-2026.json",
        "4aea5ae03362fe9f36160ac62574f1eccfbcdea65f777c9949f8157a022cdf71",
        "2026-07",
        1.9,
    ),
    "bls.ces.nonfarm_payrolls.change": (
        "CES0000000001-2026-2026.json",
        "d0c8d0236ccc51b4bcc7e0dbb3dba73cb6fd834446d722301b43a399cbe0afd3",
        "2026-08",
        162.0,
    ),
}
REGISTRABLE = sorted(CAPTURES)


def _rows(series: str) -> dict[str, dict]:
    name, digest, _, _ = CAPTURES[series]
    raw = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    spec = resolve_pending.BLS_API_ADAPTERS[series]
    rows = resolve_pending.bls_rows_from_payload(raw, spec["series_id"])
    assert rows
    return rows


def _gate(series: str) -> str:
    return resolve_pending.BLS_API_ADAPTERS[series].get(
        "first_print_gate", "latest_preliminary"
    )


def test_the_registrable_set_is_exactly_the_specs_with_a_binding() -> None:
    declared = sorted(
        stem
        for stem, spec in resolve_pending.BLS_API_ADAPTERS.items()
        if resolve_pending.bls_api_binding_template(spec) is not None
    )
    assert declared == REGISTRABLE


@pytest.mark.parametrize("series", REGISTRABLE)
def test_anchors_reproduce_exactly_from_captured_official_bytes(series: str) -> None:
    spec = resolve_pending.BLS_API_ADAPTERS[series]
    rows = _rows(series)
    assert len(spec["anchors"]) >= resolve_pending.BLS_API_MIN_ANCHORS
    assert spec["anchor_unit"] == "emitted"
    for period, expected in spec["anchors"].items():
        # Zero tolerance at admission: the runtime tolerance exists only for
        # BLS's later annual revisions.
        assert resolve_pending.bls_transformed_value(rows, spec, period) == (
            expected,
            None,
        )
    assert resolve_pending.bls_spec_anchor_mismatches(rows, spec) == []


@pytest.mark.parametrize("series", REGISTRABLE)
def test_latest_month_resolves_to_the_published_first_print(series: str) -> None:
    spec = resolve_pending.BLS_API_ADAPTERS[series]
    rows = _rows(series)
    _, _, latest, published = CAPTURES[series]
    assert max(rows) == latest
    gated, refusal = resolve_pending.bls_first_print(rows, latest, _gate(series))
    assert refusal is None and gated is not None
    assert resolve_pending.bls_transformed_value(rows, spec, latest) == (
        published,
        None,
    )


@pytest.mark.parametrize("series", REGISTRABLE)
def test_a_month_that_is_no_longer_latest_is_refused(series: str) -> None:
    rows = _rows(series)
    revised = sorted(rows)[-2]
    value, refusal = resolve_pending.bls_first_print(rows, revised, _gate(series))
    assert value is None
    assert "first-print window was missed" in (refusal or "")


def test_the_api_no_longer_serves_a_revised_first_print() -> None:
    # BLS printed June 2026 openings as 7,359 (release of 2026-08-04) and July
    # 2026 payrolls as -23 (2026-08-07). One release later the API serves the
    # revisions, which is why no anchor is a first print.
    openings = resolve_pending.BLS_API_ADAPTERS["bls.jolts.job_openings"]
    assert resolve_pending.bls_transformed_value(
        _rows("bls.jolts.job_openings"), openings, "2026-06"
    ) == (7.182, None)
    payrolls = resolve_pending.BLS_API_ADAPTERS["bls.ces.nonfarm_payrolls.change"]
    assert resolve_pending.bls_transformed_value(
        _rows("bls.ces.nonfarm_payrolls.change"), payrolls, "2026-07"
    ) == (21.0, None)


def test_preliminary_gate_needs_the_footnote_and_cps_cpi_rows_have_none() -> None:
    for series in ("bls.cps.unemployment_rate", "bls.cpi.u.headline_mom"):
        rows = _rows(series)
        assert not any(state["preliminary"] for state in rows.values())
        assert _gate(series) == "latest_month"
        _, refusal = resolve_pending.bls_first_print(
            rows, max(rows), "latest_preliminary"
        )
        assert refusal is not None
    payroll_rows = _rows("bls.ces.nonfarm_payrolls.change")
    # CES flags its latest TWO months; only the latest passes the gate.
    assert [p for p, s in sorted(payroll_rows.items()) if s["preliminary"]] == [
        "2026-07",
        "2026-08",
    ]


def test_a_change_across_an_unpublished_month_is_refused() -> None:
    spec = resolve_pending.BLS_API_ADAPTERS["bls.cpi.u.headline_mom"]
    rows = _rows("bls.cpi.u.headline_mom")
    # Official bytes: BLS published no October 2025 CPI (value "-").
    assert "2025-10" not in rows and "2025-09" in rows and "2025-11" in rows
    value, refusal = resolve_pending.bls_transformed_value(rows, spec, "2025-11")
    assert value is None
    assert "2025-10 has no served value" in (refusal or "")
    # An absent TARGET month defers instead.
    assert resolve_pending.bls_transformed_value(rows, spec, "2026-09") == (
        None,
        None,
    )


def test_a_rounded_negative_zero_is_emitted_as_zero() -> None:
    spec = resolve_pending.BLS_API_ADAPTERS["bls.cpi.u.core_mom"]
    value, _ = resolve_pending.bls_transformed_value(
        _rows("bls.cpi.u.core_mom"), spec, "2026-06"
    )
    # 336.065 / 336.121 rounds to -0.0; BLS printed "unchanged".
    assert value == 0.0 and json.dumps(value) == "0.0"


def test_emitted_anchor_check_catches_a_wrong_scale_and_a_missing_month() -> None:
    spec = resolve_pending.BLS_API_ADAPTERS["bls.jolts.job_openings"]
    rows = _rows("bls.jolts.job_openings")
    unscaled = {**spec, "scale": 1}
    assert len(resolve_pending.bls_spec_anchor_mismatches(rows, unscaled)) == 3
    without_may = {p: s for p, s in rows.items() if p != "2026-05"}
    problems = resolve_pending.bls_spec_anchor_mismatches(without_may, spec)
    assert problems == ["2026-05=missing (not served; verified 7.537)"]


def test_legacy_specs_keep_the_served_level_anchor_check() -> None:
    spec = resolve_pending.BLS_API_ADAPTERS["bls.laus.colorado.labor_force"]
    assert "anchor_unit" not in spec
    rows = {
        p: {"value": v, "latest": False, "preliminary": False}
        for p, v in spec["anchors"].items()
    }
    assert resolve_pending.bls_spec_anchor_mismatches(rows, spec) == []
    # And the transform still scales persons to one-decimal thousands.
    assert resolve_pending.bls_transformed_value(rows, spec, "2026-06") == (
        3193.3,
        None,
    )


# --- registration ---------------------------------------------------------


def _target(series: str, *, period: str = "2030-01") -> dict:
    spec = resolve_pending.BLS_API_ADAPTERS[series]
    return {
        "series": series,
        "period": period,
        "catalogSlug": f"{roll_docket.slugify_series(series)}-{period}",
        "targetUnit": spec["unit"],
        "valueScale": spec.get("scale", 1),
        "sourceBinding": resolve_pending.bls_api_binding_template(spec),
        "expectedReleaseDate": "2030-02-08",
        "releaseCalendarUrl": "https://www.bls.gov/schedule/news_release/empsit.htm",
        "previousTarget": {
            "period": "2029-12",
            # The payroll series' real previous targets carry this alias.
            "dataPointId": (
                "bls.ces.total_nonfarm.payroll_employment.change.sa.2029-12.first_print"
            ),
            "country": "US",
            "unit": spec["unit"],
            "resolutionDate": "2030-01-10",
            "resolutionSource": "Employment Situation",
            "resolutionSourceUrl": "https://www.bls.gov/news.release/empsit.nr0.htm",
            "sourceContext": ["https://fred.stlouisfed.org/series/PAYEMS"],
        },
    }


def _contract(series: str) -> dict:
    return register_targets.build_contract(_target(series), dt.date(2030, 1, 2))


def _refusal(contract: dict) -> str | None:
    return resolve_pending.execution_plan_refusal(
        {"contract": contract, "targetContentHash": None}
    )


@pytest.mark.parametrize("series", REGISTRABLE)
def test_registrar_builds_the_contract_the_executor_admits(series: str) -> None:
    contract = _contract(series)
    binding = contract["sourceBinding"]
    # Canonical id, not an edit of the previous target's alias.
    assert contract["dataPointId"] == f"{series}.2030_01.first_print"
    # The previous forecast's research hosts do not widen custody.
    assert binding["allowedHosts"] == ["api.bls.gov"]
    assert binding["expectedReleaseWindow"] == {
        "start": "2030-02-08",
        "end": "2030-02-08",
    }
    spec = resolve_pending.BLS_API_ADAPTERS[series]
    assert resolve_pending.bls_api_binding_matches_spec(binding, spec)
    assert _refusal(contract) is None
    assert _refusal(json.loads(json.dumps(contract))) is None


def test_the_appended_fact_would_bind_to_the_registered_contract() -> None:
    series = "bls.ces.nonfarm_payrolls.change"
    contract = _contract(series)
    spec = resolve_pending.BLS_API_ADAPTERS[series]
    url = resolve_pending.BLS_API_URL.format(
        series=spec["series_id"], start=2026, end=2030
    )
    row = resolve_pending.generic_fact(
        contract["dataPointId"],
        spec,
        "month",
        "2030-01",
        162.0,
        dt.date(2030, 2, 8),
        url,
        "timeseries/data (BLS Public Data API v2)",
    )
    # A one-month change consumes two served rows.
    assert row["source_row_keys"] == ["2030-01", "2029-12"]
    projection = resolve_pending.source_binding_projection(
        {"contract": contract}, row, b"{}"
    )
    assert projection["series"] == series
    assert projection["transform"] == {
        "operation": "difference_previous_period",
        "factor": 1,
    }


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda c: c["sourceBinding"]["transform"].update(round=2),
            "not the reviewed BLS API template",
        ),
        (
            lambda c: c["sourceBinding"].update(
                allowedHosts=["api.bls.gov", "www.bls.gov"]
            ),
            "not the reviewed BLS API template",
        ),
        (
            lambda c: c["sourceBinding"].update(sourceSeriesId="CUUR0000SA0"),
            "not the reviewed BLS API template",
        ),
        (
            lambda c: c["sourceBinding"]["expectedReleaseWindow"].update(
                end="2030-02-16"
            ),
            "is not a one-day window",
        ),
        (lambda c: c.update(unit="percent"), "the bls_api executor emits"),
        (
            # Both families claim this stem and the registered adapter decides,
            # so an ALFRED-bound contract is judged by the ALFRED predicate.
            lambda c: c["sourceBinding"].update(adapter="alfred-fred"),
            "is not the ALFRED series 'CPIAUCSL'",
        ),
        (lambda c: c["sourceBinding"].update(adapter="generic-url"), "generic-url"),
    ],
)
def test_contract_drift_is_refused(mutate, expected: str) -> None:
    contract = _contract("bls.cpi.u.headline_mom")
    mutate(contract)
    assert expected in (_refusal(contract) or "")


def test_a_stem_only_this_family_claims_refuses_another_adapter() -> None:
    contract = _contract("bls.jolts.quits_rate")
    contract["sourceBinding"]["adapter"] = "alfred-fred"
    assert "is not one the bls_api family resolves" in (_refusal(contract) or "")


def test_a_legacy_stem_cannot_register_under_the_bls_api_adapter() -> None:
    contract = _contract("bls.jolts.quits_rate")
    stem = "bls.ces.home_health_care_services.employment"
    contract.update(
        series=stem, dataPointId=f"{stem}.2030_01.first_print", unit="thousands"
    )
    assert "no reviewed registrable binding" in (_refusal(contract) or "")


def test_too_few_anchors_refuse_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    series = "bls.jolts.quits_rate"
    spec = copy.deepcopy(resolve_pending.BLS_API_ADAPTERS[series])
    spec["anchors"] = {"2026-04": 1.9, "2026-05": 2.0}
    monkeypatch.setitem(resolve_pending.BLS_API_ADAPTERS, series, spec)
    assert "fewer than three verified anchors" in (_refusal(_contract(series)) or "")


# --- routing ----------------------------------------------------------------


def _route(ref: str, registration: dict | None) -> list[str]:
    log = {
        "entries": [
            {
                "kind": "prediction_recorded",
                "forecastSlug": "slug",
                "resolutionDate": "2030-02-08",
                "unit": "percent",
            }
        ],
        "resolutionLinks": [
            {"status": "pending", "targetFactRef": ref, "forecastSlug": "slug"}
        ],
    }
    registrations = {} if registration is None else {ref: registration}
    return [
        route[1]
        for route in resolve_pending.pending_adapter_refs(
            log, registrations=registrations
        )
    ]


def test_a_stem_both_families_claim_routes_by_the_registered_adapter() -> None:
    series = "bls.cps.unemployment_rate"
    assert series in resolve_pending.ALFRED_ADAPTERS
    contract = _contract(series)
    ref = contract["dataPointId"]
    assert _route(ref, {"contract": contract}) == ["bls_api"]
    # An existing generic-url registration and a cell that predates bindings
    # keep the ALFRED route they had before this family became registrable.
    generic = copy.deepcopy(contract)
    generic["sourceBinding"]["adapter"] = "generic-url"
    assert _route(ref, {"contract": generic}) == ["alfred"]
    assert _route(ref, None) == ["alfred"]


def test_a_stem_only_this_family_claims_routes_here() -> None:
    series = "bls.jolts.quits_rate"
    assert series not in resolve_pending.ALFRED_ADAPTERS
    assert _route(f"{series}.2030_01.first_print", None) == ["bls_api"]


# --- docket -----------------------------------------------------------------


def _bls_api_docket_entries() -> list[dict]:
    registry = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    return [
        entry
        for entry in registry["series"]
        if (entry.get("extras") or {}).get("sourceBinding", {}).get("adapter")
        == resolve_pending.BLS_API_BINDING_ADAPTER
    ]


def test_docket_templates_are_the_executor_templates() -> None:
    entries = _bls_api_docket_entries()
    assert sorted(entry["series"] for entry in entries) == REGISTRABLE
    for entry in entries:
        spec = resolve_pending.BLS_API_ADAPTERS[entry["series"]]
        extras = entry["extras"]
        assert extras["sourceBinding"] == resolve_pending.bls_api_binding_template(spec)
        assert extras["targetUnit"] == spec["unit"]
        assert extras.get("valueScale", 1) == spec.get("scale", 1)
        assert entry["releaseCalendarUrl"].startswith(
            "https://www.bls.gov/schedule/news_release/"
        )


def test_docket_templates_pass_the_prospector_binding_schema() -> None:
    # A later proposal for the series carries this binding as its
    # previousTarget.sourceBinding, and the prospector accepts only its own
    # adapter list and an exact {operation, factor} transform.
    import prospect_targets

    for entry in _bls_api_docket_entries():
        binding = entry["extras"]["sourceBinding"]
        assert prospect_targets._source_binding_errors(binding) == []


def test_docket_calendar_never_covers_an_already_registered_period() -> None:
    # The immutable generic-url registrations for these series stay as they
    # are. The roller skips a calendar-gated period without a committed date,
    # so leaving those periods out means this adapter cannot mint a second
    # target for one of them.
    registered: dict[str, set[str]] = {}
    for path in glob.glob(str(ROOT / "records" / "targets" / "*.json")):
        for contract in json.loads(pathlib.Path(path).read_text()).get("targets", []):
            registered.setdefault(contract["series"], set()).add(contract["period"])
    for entry in _bls_api_docket_entries():
        assert entry["releaseDates"]
        overlap = set(entry["releaseDates"]) & registered.get(entry["series"], set())
        assert not overlap, (entry["series"], sorted(overlap))


def test_roller_rolls_only_a_period_with_an_official_date(
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry = next(
        e for e in _bls_api_docket_entries() if e["series"] == "bls.cpi.u.core_mom"
    )
    assert roll_docket.target_extras_for_period(entry, "2026-09") is None
    assert "no valid explicit official release date" in capsys.readouterr().err
    extras = roll_docket.target_extras_for_period(entry, "2026-10")
    assert extras is not None
    assert extras["expectedReleaseDate"] == "2026-11-10"
    assert extras["releaseCalendarUrl"] == entry["releaseCalendarUrl"]
