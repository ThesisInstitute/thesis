"""Correctness tests for the PolicyEngine tool (issue #45).

Three tiers, so repo CI stays offline and fast:
  - offline: structural validation, result normalization, compute-block shape
    (parameter source is monkeypatched — no network, no model).
  - local-model: real parameter existence checks (skipped unless policyengine-us
    is importable, i.e. the `tax` group is installed).
  - live-API: policy creation + household calc (skipped unless PE_LIVE=1).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "tools"))
pe = importlib.import_module("policyengine")

CTC_THRESHOLD = "gov.irs.credits.ctc.refundable.phase_in.threshold"
GOOD_REFORM = {CTC_THRESHOLD: {"2026-01-01.2100-12-31": 0}}


# --------------------------------------------------------------------------- #
# offline: validation is structural + existence, existence source mocked       #
# --------------------------------------------------------------------------- #
@pytest.fixture
def mock_params(monkeypatch):
    known = {CTC_THRESHOLD, "gov.irs.credits.eitc.max"}
    monkeypatch.setattr(pe, "known_parameters", lambda country="us": (known, "policyengine-us@test"))
    return known


def test_base_param_strips_bracket():
    assert pe._base_param("gov.irs.credits.eitc.max[0].amount") == "gov.irs.credits.eitc.max"
    assert pe._base_param("gov.irs.credits.ctc.refundable.phase_in.threshold") == CTC_THRESHOLD


def test_valid_reform_passes(mock_params):
    r = pe.validate_reform(GOOD_REFORM)
    assert r.ok and not [p for p in r.problems if not p.startswith("WARNING")]
    assert r.checked_existence and r.param_source == "policyengine-us@test"


def test_unknown_parameter_flagged(mock_params):
    r = pe.validate_reform({"gov.irs.credits.ctc.made_up": {"2026-01-01.2026-12-31": 1}})
    assert not r.ok
    assert any("unknown parameter" in p for p in r.problems)


def test_bad_date_and_string_value_flagged(mock_params):
    r = pe.validate_reform({CTC_THRESHOLD: {"2026": "lots"}})
    assert not r.ok
    assert any("bad date range" in p for p in r.problems)
    assert any("value must be number/bool" in p for p in r.problems)


def test_boolean_value_allowed(mock_params, monkeypatch):
    monkeypatch.setattr(pe, "known_parameters",
                        lambda country="us": ({"gov.contrib.x.in_effect"}, "policyengine-us@test"))
    r = pe.validate_reform({"gov.contrib.x.in_effect": {"2026-01-01.2100-12-31": True}})
    assert r.ok


def test_empty_reform_rejected():
    assert not pe.validate_reform({}).ok


def test_unverifiable_existence_REFUSES_by_default(monkeypatch):
    # FAIL-CLOSED (review finding, #64): a PE failure must refuse, not validate.
    monkeypatch.setattr(pe, "known_parameters", lambda country="us": (None, "structural-only"))
    r = pe.validate_reform(GOOD_REFORM)
    assert not r.ok and not r.checked_existence
    assert any(p.startswith("REFUSED") for p in r.problems)


def test_unverifiable_existence_passes_only_with_explicit_override(monkeypatch):
    monkeypatch.setattr(pe, "known_parameters", lambda country="us": (None, "structural-only"))
    r = pe.validate_reform(GOOD_REFORM, allow_unverified=True)
    assert r.ok and not r.checked_existence
    assert any("allow_unverified" in p for p in r.problems)


BUILD_P_STACK = {"policyengine-us": "1.764.6", "policyengine-core": "3.26.11"}


def test_certification_refuses_when_manifest_unreachable(monkeypatch):
    monkeypatch.setattr(pe, "certified_stack", lambda build=None: None)
    note = pe.certification_note("some-build", "1.764.6", running_core_version="3.26.11",
                                 validated_against="policyengine-us@1.764.6")
    assert note["certified"] is False
    assert note["warning"] and "CANNOT CERTIFY" in note["warning"]


def test_certification_refuses_when_running_version_unknown(monkeypatch):
    monkeypatch.setattr(pe, "certified_stack", lambda build=None: BUILD_P_STACK)
    note = pe.certification_note("some-build", None, running_core_version="3.26.11")
    assert note["certified"] is False
    assert note["warning"] and "CANNOT CERTIFY" in note["warning"]


def test_certification_certifies_only_the_measured_validated_stack(monkeypatch):
    monkeypatch.setattr(pe, "certified_stack", lambda build=None: BUILD_P_STACK)
    note = pe.certification_note("some-build", "1.764.6", running_core_version="3.26.11",
                                 validated_against="policyengine-us@1.764.6")
    assert note["certified"] is True and note["warning"] is None
    assert note["validated_against"] == "policyengine-us@1.764.6"
    assert note["running_core_version"] == note["certified_core_version"] == "3.26.11"


def test_certification_refuses_validation_against_another_model(monkeypatch):
    # prb4 round 3 (2026-07-31): the S.3596 evidence validated against
    # policyengine-us@1.784.3 while the run was 1.764.6 — not certified.
    monkeypatch.setattr(pe, "certified_stack", lambda build=None: BUILD_P_STACK)
    note = pe.certification_note("some-build", "1.764.6", running_core_version="3.26.11",
                                 validated_against="policyengine-us@1.784.3")
    assert note["certified"] is False
    assert "validated against policyengine-us@1.784.3" in note["warning"]


def test_certification_refuses_wrong_or_unknown_core(monkeypatch):
    monkeypatch.setattr(pe, "certified_stack", lambda build=None: BUILD_P_STACK)
    for core in ("3.23.6", None):
        note = pe.certification_note("some-build", "1.764.6", running_core_version=core,
                                     validated_against="policyengine-us@1.764.6")
        assert note["certified"] is False and "policyengine-core" in note["warning"]


def test_certification_skips_core_when_manifest_pins_none(monkeypatch):
    monkeypatch.setattr(pe, "certified_stack",
                        lambda build=None: {"policyengine-us": "1.764.6", "policyengine-core": None})
    note = pe.certification_note("some-build", "1.764.6",
                                 validated_against="policyengine-us@1.764.6")
    assert note["certified"] is True


def test_exact_pin_rejects_ranges_and_missing_specifiers():
    assert pe._exact_pin([{"name": "policyengine-us", "specifier": "==1.764.6"}]) == "1.764.6"
    for packages in (None, [], [{}], [{"specifier": ">=1.764"}], [{"specifier": "=="}],
                     [{"specifier": "~=1.764.6"}], [None]):
        assert pe._exact_pin(packages) is None


def test_runtime_stack_measures_package_metadata(monkeypatch):
    import importlib.metadata as md

    versions = {"policyengine-us": "1.764.6"}

    def fake_version(name):
        if name not in versions:
            raise md.PackageNotFoundError(name)
        return versions[name]

    monkeypatch.setattr(md, "version", fake_version)
    assert pe.runtime_stack() == {"policyengine-us": "1.764.6", "policyengine-core": None}
    with pytest.raises(pe.PolicyEngineError, match="policyengine-core expected 3.26.11, running not installed"):
        pe.require_runtime_stack(BUILD_P_STACK)
    versions["policyengine-core"] = "3.26.11"
    assert pe.require_runtime_stack(BUILD_P_STACK) == BUILD_P_STACK
    versions["policyengine-us"] = "1.784.3"
    with pytest.raises(pe.PolicyEngineError, match="policyengine-us expected 1.764.6, running 1.784.3"):
        pe.require_runtime_stack(BUILD_P_STACK)


# --------------------------------------------------------------------------- #
# offline: result normalization + compute block                                #
# --------------------------------------------------------------------------- #
RAW = {
    "budget": {"budgetary_impact": -1.6e9, "tax_revenue_impact": -1.6e9,
               "benefit_spending_impact": 0.0, "households": 1.3e8},
    "poverty": {
        "poverty": {"all": {"baseline": 0.10, "reform": 0.099},
                    "child": {"baseline": 0.20, "reform": 0.199}},
        "deep_poverty": {"child": {"baseline": 0.05, "reform": 0.0499}},
    },
    "decile": {"average": {str(i): i * 10.0 for i in range(1, 11)}, "relative": {}},
    "intra_decile": {"all": {"Gain more than 5%": 0.06}},
}


def test_normalize_economy_shape_and_pct_change():
    n = pe.normalize_economy(RAW)
    assert n["budgetary_impact"] == -1.6e9
    assert n["poverty"]["child"]["baseline"] == 0.20
    # -0.5% child poverty change from 0.20 -> 0.199
    assert n["poverty"]["child"]["pct_change"] == pytest.approx(-0.005, rel=1e-6)
    assert n["decile_average_change"]["10"] == 100.0
    assert n["winners_losers"] == {"Gain more than 5%": 0.06}


def test_normalize_tolerates_missing_keys():
    n = pe.normalize_economy({})  # empty result must not raise
    assert n["budgetary_impact"] is None
    assert n["poverty"]["child"]["pct_change"] is None


def test_compute_block_ok():
    run = pe.EconomyRun("ok", 2026, "us", "us", GOOD_REFORM, 85587, 2,
                        impact=pe.normalize_economy(RAW))
    block = pe.compute_block(run, provision_title="strike $2,500 -> $1")
    assert block["model"] == "policyengine-us"
    assert block["reform"] == GOOD_REFORM
    assert block["budgetary_impact"] == -1.6e9
    assert "budgetary impact" in block["result_summary"]
    assert block["provision_title"] == "strike $2,500 -> $1"


def test_compute_block_modal_engine_certifies_with_model_version(monkeypatch):
    # Regression (review follow-up): modal runs measure their model version and
    # must certify against it; the summary must not claim "hosted API".
    monkeypatch.setattr(pe, "certified_stack", lambda build=None: BUILD_P_STACK)
    run = pe.EconomyRun("ok", 2026, "us", "us", GOOD_REFORM, None, 2,
                        impact=pe.normalize_economy(RAW), engine="modal",
                        dataset="some-build", pe_us_version="1.764.6",
                        pe_core_version="3.26.11", param_source="policyengine-us@1.764.6",
                        checked_existence=True)
    block = pe.compute_block(run)
    assert block["certification"]["certified"] is True
    assert block["pe_core_version"] == "3.26.11"
    assert "engine=modal" in block["result_summary"]
    assert "hosted API" not in block["result_summary"]


def test_compute_block_modal_engine_refuses_off_version_validation(monkeypatch):
    # The S.3596 July run: measured 1.764.6, validated on the laptop's 1.784.3.
    monkeypatch.setattr(pe, "certified_stack", lambda build=None: BUILD_P_STACK)
    run = pe.EconomyRun("ok", 2026, "us", "us", GOOD_REFORM, None, 2,
                        impact=pe.normalize_economy(RAW), engine="modal",
                        dataset="some-build", pe_us_version="1.764.6",
                        pe_core_version="3.26.11", param_source="policyengine-us@1.784.3",
                        checked_existence=True)
    assert pe.compute_block(run)["certification"]["certified"] is False


def test_compute_block_refuses_unchecked_existence(monkeypatch):
    monkeypatch.setattr(pe, "certified_stack", lambda build=None: BUILD_P_STACK)
    run = pe.EconomyRun("ok", 2026, "us", "us", GOOD_REFORM, None, 2,
                        impact=pe.normalize_economy(RAW), engine="modal",
                        dataset="some-build", pe_us_version="1.764.6",
                        pe_core_version="3.26.11", param_source="policyengine-us@1.764.6",
                        checked_existence=False)
    cert = pe.compute_block(run)["certification"]
    assert cert["certified"] is False and cert["validated_against"] is None


def test_compute_block_api_engine_refuses_certification(monkeypatch):
    # api_version is the service version, not the model — certification must
    # refuse explicitly rather than conflate the two.
    monkeypatch.setattr(pe, "certified_stack", lambda build=None: BUILD_P_STACK)
    run = pe.EconomyRun("ok", 2026, "us", "us", GOOD_REFORM, 85587, 2,
                        impact=pe.normalize_economy(RAW), engine="api",
                        dataset="some-build", api_version="3.2.1")
    block = pe.compute_block(run)
    assert block["certification"]["certified"] is False
    assert "CANNOT CERTIFY" in block["certification"]["warning"]


def test_api_run_records_no_model_version(monkeypatch, tmp_path):
    # The hosted service priced it; this process's installed policyengine-us
    # did not, so it must not appear as the run's model version.
    monkeypatch.setattr(pe, "validate_reform",
                        lambda reform, country="us": pe.ValidationResult(True, [], "policyengine-us@9.9.9", True))
    monkeypatch.setattr(pe, "create_policy", lambda reform, country="us", validate=True: 123)
    monkeypatch.setattr(pe, "_get", lambda path, timeout=120: (200, {"status": "ok", "result": RAW}))
    monkeypatch.setattr(pe, "policyengine_us_version", lambda: "9.9.9")
    run = pe.economy_impact(GOOD_REFORM, 2026, log_dir=tmp_path)
    assert run.status == "ok" and run.engine == "api"
    assert run.pe_us_version is None and run.pe_core_version is None


def test_compute_block_pending_widens():
    run = pe.EconomyRun("pending", 2026, "us", "us", GOOD_REFORM, 85587, 2,
                        message="still computing")
    block = pe.compute_block(run)
    assert block["status"] == "pending"
    assert "pending" in block["result_summary"]


# --------------------------------------------------------------------------- #
# local-model: real parameter existence (needs the certified stack)            #
# --------------------------------------------------------------------------- #
_HAS_MODEL = importlib.util.find_spec("policyengine_us") is not None
local_only = pytest.mark.skipif(not _HAS_MODEL, reason="policyengine-us not installed (see scripts/tools/requirements-tax.txt)")


@local_only
def test_local_parameters_include_ctc_threshold():
    params, source = pe.known_parameters("us")
    assert params is not None and CTC_THRESHOLD in params
    assert source.startswith("policyengine-us@")


@local_only
def test_real_reform_validates_and_garbage_fails():
    assert pe.validate_reform(GOOD_REFORM).ok
    assert not pe.validate_reform({"gov.irs.credits.ctc.not_real": {"2026-01-01.2026-12-31": 0}}).ok


# --------------------------------------------------------------------------- #
# live-API: policy + household (needs network; opt in with PE_LIVE=1)           #
# --------------------------------------------------------------------------- #
live_only = pytest.mark.skipif(not os.environ.get("PE_LIVE"), reason="set PE_LIVE=1 for live API tests")


@live_only
def test_create_policy_returns_id():
    pid = pe.create_policy(GOOD_REFORM, validate=True)
    assert isinstance(pid, int) and pid > 0


@live_only
def test_household_ctc_phase_in_point_check():
    # A single parent, 1 child, $2,000 earnings. Baseline CTC phase-in starts at
    # $2,500 of earnings, so refundable CTC is ~$0; striking the threshold to $0
    # phases in from the first dollar -> refundable CTC > baseline.
    hh = {
        "people": {"a": {"age": {"2026": 30}, "employment_income": {"2026": 2000}},
                   "c": {"age": {"2026": 4}}},
        # /calculate only returns variables present in the payload — request the
        # output by seeding it null.
        "tax_units": {"t": {"members": ["a", "c"], "refundable_ctc": {"2026": None}}},
        "spm_units": {"s": {"members": ["a", "c"]}},
        "households": {"h": {"members": ["a", "c"], "state_name": {"2026": "TX"}}},
    }
    base = pe.household_under(hh, None, baseline=True)
    reform = pe.household_under(hh, GOOD_REFORM)
    b = base["tax_units"]["t"]["refundable_ctc"]["2026"]
    r = reform["tax_units"]["t"]["refundable_ctc"]["2026"]
    assert r > b  # phasing in from the first dollar raises the refundable CTC
