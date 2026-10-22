"""POLICYENGINE.md §0.2: an uncertified PolicyEngine run is inadmissible for a
published number. These tests pin the rule end to end, offline:

  - certification_note certifies exactly the measured, validated, manifest-
    matching stack (Hypothesis property over small version pools);
  - the publication gate (attach_compute.publishable_compute_row, mirrored by
    the site's isPublishableCompute) agrees with the shared fixture and with
    compute_block's own certification (differential);
  - the attach registry cannot carry a certification its run artifacts did not
    emit, and every committed bill row is exactly a registered, verified row;
  - the Modal driver reports versions it measured in the container, not its pins.
"""

from __future__ import annotations

import ast
import copy
import importlib
import json
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "tools"))
pe = importlib.import_module("policyengine")
attach = importlib.import_module("attach_compute")

FIXTURE = ROOT / "tests" / "fixtures" / "compute_publishability_cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
REFORM = {"gov.irs.credits.ctc.refundable.phase_in.threshold": {"2026-01-01.2100-12-31": 0}}

VERSIONS = st.sampled_from([None, "", "1.764.6", "1.784.3"])
CORES = st.sampled_from([None, "3.26.11", "3.23.6"])
SOURCES = st.sampled_from([None, "", "metadata-api", "structural-only",
                           "policyengine-us@1.764.6", "policyengine-us@1.784.3",
                           "policyengine-us@unknown"])
STACKS = st.one_of(
    st.none(),
    st.fixed_dictionaries({"policyengine-us": st.sampled_from(["1.764.6", "1.784.3"]),
                           "policyengine-core": st.sampled_from([None, "3.26.11"])}),
)


# --------------------------------------------------------------------------- #
# shared oracle                                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_gate_matches_shared_fixture(case):
    assert attach.publishable_compute_row(case["row"]) is case["publishable"]


def test_fixture_covers_both_verdicts_and_the_july_rows():
    verdicts = {c["publishable"] for c in CASES}
    assert verdicts == {True, False}
    names = " ".join(c["name"] for c in CASES)
    assert "July 2026" in names and "prb4" in names


# --------------------------------------------------------------------------- #
# certification_note: certified <=> the full rule                              #
# --------------------------------------------------------------------------- #
@settings(max_examples=400, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(stack=STACKS, running=VERSIONS, core=CORES, validated=SOURCES)
def test_certified_iff_measured_validated_and_manifest_matching(
        monkeypatch, stack, running, core, validated):
    monkeypatch.setattr(pe, "certified_stack", lambda build=None: stack)
    note = pe.certification_note("build-x", running, running_core_version=core,
                                 validated_against=validated)
    expected = (
        stack is not None
        and running is not None
        and running == stack["policyengine-us"]
        and (stack["policyengine-core"] is None or core == stack["policyengine-core"])
        and validated == f"policyengine-us@{running}"
    )
    assert note["certified"] is expected
    # Every refusal says why; a certification never carries a warning.
    assert (note["warning"] is None) is expected
    assert note["build"] == "build-x"


# --------------------------------------------------------------------------- #
# differential: gate(compute_block row) == compute_block certification         #
# --------------------------------------------------------------------------- #
@settings(max_examples=400, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(stack=STACKS, running=VERSIONS, core=CORES, source=SOURCES,
       checked=st.booleans(), engine=st.sampled_from(["modal", "local", "api"]))
def test_gate_agrees_with_compute_block_certification(
        monkeypatch, stack, running, core, source, checked, engine):
    monkeypatch.setattr(pe, "certified_stack", lambda build=None: stack)
    run = pe.EconomyRun("ok", 2026, "us", "us", REFORM, None, 2,
                        impact={"budgetary_impact": -1.0e9}, engine=engine,
                        dataset="build-x", pe_us_version=running, pe_core_version=core,
                        param_source=source or "", checked_existence=checked)
    row = pe.compute_block(run)
    assert attach.publishable_compute_row(row) is row["certification"]["certified"]
    if engine == "api":
        assert row["certification"]["certified"] is False


def test_gate_withholds_every_non_ok_status(monkeypatch):
    monkeypatch.setattr(pe, "certified_stack", lambda build=None:
                        {"policyengine-us": "1.764.6", "policyengine-core": "3.26.11"})
    for status in ("pending", "error"):
        run = pe.EconomyRun(status, 2026, "us", "us", REFORM, None, 2, engine="modal",
                            dataset="build-x", pe_us_version="1.764.6",
                            pe_core_version="3.26.11",
                            param_source="policyengine-us@1.764.6", checked_existence=True)
        assert not attach.publishable_compute_row(pe.compute_block(run))


# --------------------------------------------------------------------------- #
# the record: committed rows == registry rows == run artifacts                 #
# --------------------------------------------------------------------------- #
def _bill_rows():
    for path in sorted((ROOT / "bills").glob("*.json")):
        if path.name.endswith(".mapped.json"):
            continue
        bill = json.loads(path.read_text(encoding="utf-8"))
        for index, provision in enumerate(bill.get("provisions", [])):
            if provision.get("compute"):
                yield path.stem, index, provision["compute"]


def test_every_committed_compute_row_is_a_registered_row():
    seen = list(_bill_rows())
    assert seen, "expected at least the S.3596 compute row"
    for slug, index, rows in seen:
        assert (slug, index) in attach.ROWS, f"{slug}[{index}] compute rows bypass the registry"
        assert rows == attach.ROWS[(slug, index)], (
            f"{slug}[{index}] differs from its registry rows — rows reach bills/*.json "
            "only through scripts/tools/attach_compute.py")


@pytest.mark.parametrize("key", sorted(attach.ROWS), ids=lambda k: f"{k[0]}[{k[1]}]")
def test_registry_rows_verify_against_their_run_artifacts(key):
    rows = attach.ROWS[key]
    attach._check_certification_claims(rows)
    attach._verify_against_artifacts(key[0], key[1], rows)


def test_s3596_row_is_publishable_at_exact_runtime():
    (row,) = attach.ROWS[("s3596-119", 0)]
    assert attach.publishable_compute_row(row)
    cert = row["certification"]
    assert cert["running_model_version"] == cert["certified_model_version"] == "1.764.6"
    assert cert["running_core_version"] == cert["certified_core_version"] == "3.26.11"
    assert cert["validated_against"] == "policyengine-us@1.764.6"
    artifacts = attach.GROUNDING[("s3596-119", 0)]
    econ = json.loads(artifacts["economy"].read_text(encoding="utf-8"))
    sweep = json.loads(artifacts["sweep"].read_text(encoding="utf-8"))
    assert econ["versions_measured_in_container"] is True
    assert sweep["versions_measured_in_container"] is True
    assert sweep["certification"]["certified"] is True
    assert "claimed-tier" not in json.dumps(row)


def _mutated(mutate):
    rows = copy.deepcopy(attach.ROWS[("s3596-119", 0)])
    mutate(rows[0])
    return rows


@pytest.mark.parametrize("mutate", [
    lambda r: r["certification"].__setitem__("certified", False),
    lambda r: r["certification"].__setitem__("validated_against", "policyengine-us@1.784.3"),
    lambda r: r["certification"].pop("running_core_version"),
    lambda r: r.__setitem__("param_source", "policyengine-us@1.784.3"),
    lambda r: r.__setitem__("pe_us_version", "1.784.3"),
    lambda r: r.__setitem__("pe_core_version", "3.23.6"),
    lambda r: r.__setitem__("budgetary_impact", r["budgetary_impact"] * 1.01),
    lambda r: r.__setitem__("ten_year_budgetary_impact", r["ten_year_budgetary_impact"] * 1.01),
], ids=["flip-certified", "off-version-validation", "drop-core", "param-source",
        "model-version", "core-version", "2026-figure", "ten-year-figure"])
def test_hand_edited_registry_rows_are_refused(mutate):
    rows = _mutated(mutate)
    with pytest.raises(SystemExit):
        attach._check_certification_claims(rows)
        attach._verify_against_artifacts("s3596-119", 0, rows)


def test_certified_claim_without_consistent_provenance_is_refused():
    rows = _mutated(lambda r: r["certification"].pop("validated_against"))
    with pytest.raises(SystemExit, match="claims certified: true"):
        attach._check_certification_claims(rows)


def test_uncertified_rows_may_attach_and_are_withheld(tmp_path, monkeypatch):
    bills = tmp_path / "bills"
    bills.mkdir()
    (bills / "x.json").write_text(json.dumps({"provisions": [{"title": "s"}]}))
    monkeypatch.setattr(attach, "BILLS_DIR", bills)
    row = copy.deepcopy(CASES[0]["row"])
    row["certification"]["certified"] = False
    row["certification"]["warning"] = "UNCERTIFIED PAIRING: test"
    attach.attach("x", 0, [row])
    stored = json.loads((bills / "x.json").read_text())["provisions"][0]["compute"]
    assert stored == [row] and not attach.publishable_compute_row(stored[0])


# --------------------------------------------------------------------------- #
# the driver: measured in-container, never the pin constants                   #
# --------------------------------------------------------------------------- #
DRIVER = ast.parse((ROOT / "scripts" / "tools" / "modal_economy.py").read_text(encoding="utf-8"))


def _function(name):
    (fn,) = [n for n in ast.walk(DRIVER) if isinstance(n, ast.FunctionDef) and n.name == name]
    return fn


def _calls(fn):
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call)]


def _call_name(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def test_container_measures_and_validates_before_any_microsim():
    fn = _function("economy")
    lines = {}
    for call in _calls(fn):
        lines.setdefault(_call_name(call), []).append(call.lineno)
    first_sim = min(lines["Microsimulation"])
    assert min(lines["require_runtime_stack"]) < first_sim
    assert min(lines["validate_reform"]) < first_sim


def test_container_reports_measured_versions_not_pins():
    fn = _function("economy")
    returns = [n.value for n in ast.walk(fn) if isinstance(n, ast.Return)]
    (result,) = [r for r in returns if isinstance(r, ast.Dict)
                 and any(isinstance(k, ast.Constant) and k.value == "pe_us_version" for k in r.keys)]
    fields = {k.value: v for k, v in zip(result.keys, result.values) if isinstance(k, ast.Constant)}
    for key in ("pe_us_version", "pe_core_version"):
        names = {n.id for n in ast.walk(fields[key]) if isinstance(n, ast.Name)}
        assert "stack" in names and not names & {"PE_US", "PE_CORE"}, key
    assert isinstance(fields["versions_measured_in_container"], ast.Constant)
    assert fields["versions_measured_in_container"].value is True
    assert "validation" in fields


def test_entrypoints_record_only_measured_results():
    for name in ("_record", "sweep"):
        assert "_measured" in {_call_name(c) for c in _calls(_function(name))}, name
    # No recorded artifact may take its versions from the install pins.
    for name in ("_record", "sweep", "main"):
        names = {n.id for n in ast.walk(_function(name)) if isinstance(n, ast.Name)}
        assert not names & {"PE_US", "PE_CORE"}, name
