"""A new registration needs a resolver that can execute it.

These tests run the real resolver (``resolve_pending.execution_plan_refusal``)
against real registered contracts from ``records/targets`` and mutations of
them. Nothing here touches the network; one test proves it.
"""

from __future__ import annotations

import copy
import datetime as dt
import inspect
import json
import pathlib
import re
import socket
import subprocess
import sys
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import prospect_targets  # noqa: E402
import register_targets  # noqa: E402
import resolve_pending  # noqa: E402
import roll_docket  # noqa: E402
from canonical_json import canonical_bytes  # noqa: E402

# Registrations that predate the gate and that the resolver refuses at run
# time for a reason other than ``generic-url``. The gate reproduces each
# refusal. This is a census of history the registrar never reads, not an
# allowlist: none of these could be registered again.
# A tree carries the gate exactly when it carries this file.
GATE_MARKER = "tests/test_execution_plan_gate.py"
KNOWN_UNEXECUTABLE_NATIVE = {
    # ALFRED-bound, but no resolver stem routes this id.
    "bls.wp.WPSFD4.2026-07.first_print": "no resolver family routes",
    # Census SPM is unarmed until the revised-methodology anchors are verified.
    "census.spm.child_poverty_rate.2027.first_print.current_law": "unarmed",
    "census.spm.child_poverty_rate.2027.first_print.threshold_one_dollar": "unarmed",
    # Registered without a resolutionDateBasis, which this resolve-by-bound
    # family requires (and against FSA's retired statistics URL besides).
    "usda.fsa.crp.enrolled_acres_total.2027_09.first_print.ceiling_27_million": (
        "resolution-date basis mismatch"
    ),
    "usda.fsa.crp.enrolled_acres_total.2027_09.first_print.no_fy2027_31_ceiling": (
        "resolution-date basis mismatch"
    ),
}


@pytest.fixture(scope="module")
def registered() -> dict[str, dict]:
    return resolve_pending.registration_contracts()


def _registration(contract: dict) -> dict:
    return {"contract": contract, "targetContentHash": None}


def _refusal(contract: dict) -> str | None:
    return resolve_pending.execution_plan_refusal(_registration(contract))


def _first(registered: dict[str, dict], adapter: str, prefix: str = "") -> dict:
    for ref, registration in sorted(registered.items()):
        contract = registration["contract"]
        if contract["sourceBinding"]["adapter"] == adapter and ref.startswith(prefix):
            if resolve_pending.execution_plan_refusal(registration) is None:
                return copy.deepcopy(contract)
    raise AssertionError(f"no executable {adapter} registration under {prefix!r}")


# -- the census ---------------------------------------------------------------


def test_every_existing_registration_gets_the_verdict_the_resolver_gives(
    registered: dict[str, dict],
) -> None:
    admitted_adapters: set[str] = set()
    for ref, registration in registered.items():
        adapter = registration["contract"]["sourceBinding"]["adapter"]
        refusal = resolve_pending.execution_plan_refusal(registration)
        if adapter == "generic-url":
            assert refusal is not None and "generic-url" in refusal, ref
        elif refusal is None:
            admitted_adapters.add(adapter)
        else:
            assert ref in KNOWN_UNEXECUTABLE_NATIVE, f"{ref}: {refusal}"
            assert KNOWN_UNEXECUTABLE_NATIVE[ref] in refusal, f"{ref}: {refusal}"
    # The census is not vacuous: every registrable family the resolver
    # executes today has at least one admitted contract.
    assert admitted_adapters >= {
        "abs-data-api",
        "alfred-fred",
        "bea-ita-itable",
        "bea-release",
        "eia-dnav-xls",
        "fsa-crp-monthly-summary",
        "irs-soi-pub1304",
        "sba-loan-program-performance-pdf",
        "statcan-wds",
        "usaspending-api",
    }


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def test_no_tree_that_had_the_gate_registered_a_target_without_an_executor() -> None:
    """The gate is the only writer of snapshots; this trips if that stops.

    Self-anchoring, like the records-provenance epoch: a registration commit
    is judged only if its own tree already carried the gate, so targets that
    main minted before this merged are history, whatever the merge date or
    strategy. No id is ever allowlisted.
    """

    try:
        if _git("rev-parse", "--is-shallow-repository").strip() != "false":
            pytest.skip("needs full history (CI checks out fetch-depth 0)")
        added = _git(
            "log",
            "--diff-merges=first-parent",
            "--diff-filter=AM",
            "--name-only",
            "--format=commit %H",
            "--since=2026-09-19",
            "--",
            "records/targets",
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git history unavailable")
    late = []
    commit = ""
    gated: dict[str, bool] = {}
    for line in added.splitlines():
        if line.startswith("commit "):
            commit = line.split()[1]
            continue
        if not re.fullmatch(r"records/targets/[^/]+\.json", line):
            continue
        if commit not in gated:
            gated[commit] = (
                subprocess.run(
                    ["git", "cat-file", "-e", f"{commit}:{GATE_MARKER}"],
                    cwd=ROOT,
                    capture_output=True,
                ).returncode
                == 0
            )
        if not gated[commit]:
            continue
        # The bytes that commit wrote, not today's worktree: a snapshot later
        # deleted, or an id another snapshot also registers, is still judged.
        snapshot = json.loads(_git("show", f"{commit}:{line}"))
        for contract in snapshot["targets"]:
            refusal = _refusal(contract)
            if refusal:
                late.append(
                    f"{commit[:12]} {line} {contract['dataPointId']}: {refusal}"
                )
    assert not late, "registered without an executable plan:\n" + "\n".join(late)


def test_every_family_the_router_names_has_a_registration_verdict() -> None:
    source = inspect.getsource(resolve_pending.pending_adapter_refs)
    kinds = set(re.findall(r'\(\s*ref,\s*"([a-z0-9_]+)"', source))
    assert kinds, "router source shape changed; update this extraction"
    decided = set(resolve_pending.EXECUTION_PLAN_FAMILY_CHECKS) | set(
        resolve_pending.EXECUTION_PLAN_UNREGISTRABLE_FAMILIES
    )
    assert kinds == decided, (
        "a resolver family was added or removed without deciding whether new "
        f"registrations may bind to it: {sorted(kinds ^ decided)}"
    )
    assert not set(resolve_pending.EXECUTION_PLAN_FAMILY_CHECKS) & set(
        resolve_pending.EXECUTION_PLAN_UNREGISTRABLE_FAMILIES
    )


# -- the pure verdict ---------------------------------------------------------


def test_native_contract_is_admitted_as_built_and_as_serialized(
    registered: dict[str, dict],
) -> None:
    for adapter in ("alfred-fred", "statcan-wds", "usaspending-api"):
        contract = _first(registered, adapter)
        assert _refusal(contract) is None
        # A registration is judged again after a JSON round trip in the
        # workflow; an identity check on adapter objects must not matter.
        assert _refusal(json.loads(canonical_bytes(contract))) is None


def test_generic_url_is_refused_even_on_a_stem_a_family_claims(
    registered: dict[str, dict],
) -> None:
    contract = _first(registered, "alfred-fred", "census.")
    contract["sourceBinding"]["adapter"] = "generic-url"
    assert "generic-url" in (_refusal(contract) or "")


def test_unknown_series_is_refused() -> None:
    contract = register_targets.build_contract(
        {
            "series": "agency.test.rate",
            "period": "2030-01",
            "catalogSlug": "agency-test-rate-january-2030",
            "targetUnit": "percent",
            "resolutionSourceUrl": "https://data.example.gov/table-a",
            "sourceBinding": {"adapter": "alfred-fred", "sourceSeriesId": "X"},
            "expectedReleaseDate": "2030-02-15",
            "releaseCalendarUrl": "https://data.example.gov/calendar",
        },
        dt.date(2030, 1, 10),
    )
    assert "no resolver family routes" in (_refusal(contract) or "")


def test_alfred_adapter_with_an_unrouted_id_is_refused(
    registered: dict[str, dict],
) -> None:
    contract = registered["bls.wp.WPSFD4.2026-07.first_print"]["contract"]
    assert contract["sourceBinding"]["adapter"] == "alfred-fred"
    assert "no resolver family routes" in (_refusal(contract) or "")


def test_wrong_unit_is_refused(registered: dict[str, dict]) -> None:
    contract = _first(registered, "alfred-fred")
    contract["unit"] = "bananas"
    assert "executor emits" in (_refusal(contract) or "")


def test_alfred_binding_must_name_the_series_the_executor_reads(
    registered: dict[str, dict],
) -> None:
    contract = _first(registered, "alfred-fred", "census.")
    contract["sourceBinding"]["sourceSeriesId"] = "UNRATE"
    assert "is not the ALFRED series" in (_refusal(contract) or "")


def test_native_template_drift_is_refused(registered: dict[str, dict]) -> None:
    for adapter, family in (
        ("statcan-wds", "international"),
        ("usaspending-api", "USAspending"),
        ("irs-soi-pub1304", "IRS SOI"),
        ("eia-dnav-xls", "EIA dnav"),
        # SBA recovers its fiscal-year period from the registered binding,
        # so a drifted binding does not even route.
        ("sba-loan-program-performance-pdf", "no resolver family routes"),
        ("bea-release", "BEA release"),
        ("fsa-crp-monthly-summary", "FSA CRP"),
    ):
        contract = _first(registered, adapter)
        contract["sourceBinding"]["field"] = "some other cell"
        assert family in (_refusal(contract) or ""), adapter


def test_bounded_family_needs_its_registered_resolution_date_basis(
    registered: dict[str, dict],
) -> None:
    # The main loop's first refusal. A resolve-by-bound family executes only
    # a contract that registers that basis; build_contract writes the key only
    # when the target supplies it, so an omission is a well-formed contract.
    checked = 0
    for adapter in ("eia-dnav-xls", "fsa-crp-monthly-summary", "irs-soi-pub1304"):
        contract = _first(registered, adapter)
        if contract.get("resolutionDateBasis") != "resolve-by-bound":
            continue
        checked += 1
        omitted = copy.deepcopy(contract)
        del omitted["resolutionDateBasis"]
        assert "resolution-date basis mismatch" in (_refusal(omitted) or ""), adapter
        wrong = copy.deepcopy(contract)
        wrong["resolutionDateBasis"] = "release-calendar"
        assert "resolution-date basis mismatch" in (_refusal(wrong) or ""), adapter
    assert checked >= 2


def test_weekly_claims_plan(registered: dict[str, dict]) -> None:
    contract = _first(registered, "alfred-fred", "us.dol.initial_claims.sa.")
    assert _refusal(contract) is None
    wrong_unit = copy.deepcopy(contract)
    wrong_unit["unit"] = "millions"
    assert "claims executor emits" in (_refusal(wrong_unit) or "")
    wrong_series = copy.deepcopy(contract)
    wrong_series["sourceBinding"]["sourceSeriesId"] = "CCSA"
    assert "claims executor reads ALFRED ICSA" in (_refusal(wrong_series) or "")


def test_reviewed_legacy_exceptions_are_not_inherited_by_new_contracts(
    registered: dict[str, dict],
) -> None:
    # The resolver executes two reviewed generic-url contracts at run time:
    # one ABS registration by exact content hash, and the legacy QCEW
    # binding. Neither exception admits a NEW registration.
    ((legacy_hash, legacy_abs),) = (
        resolve_pending.LEGACY_INTL_EXECUTOR_CONTRACTS.items()
    )
    successor = copy.deepcopy(legacy_abs)
    successor["period"] = "2026-10"
    successor["dataPointId"] = (
        "abs.labour.unemployment_rate.australia.october_2026.first_print"
    )
    assert "generic-url" in (_refusal(successor) or "")
    # Even the byte-identical legacy contract is refused as a new
    # registration; the run-time exception stays a run-time exception.
    assert "generic-url" in (
        resolve_pending.execution_plan_refusal(
            {"contract": legacy_abs, "targetContentHash": legacy_hash}
        )
        or ""
    )
    assert (
        resolve_pending.intl_execution_spec(
            {"contract": legacy_abs, "targetContentHash": legacy_hash},
            resolve_pending.INTL_REGISTRY_ADAPTERS["abs.labour.unemployment_rate"],
        )
        is not None
    ), "the existing run-time exception must keep working"


def test_a19_cannot_take_new_registrations_under_any_adapter(
    registered: dict[str, dict],
) -> None:
    ref = next(
        ref for ref in sorted(registered) if ref.startswith(resolve_pending.A19_STEM)
    )
    contract = copy.deepcopy(registered[ref]["contract"])
    assert "generic-url" in (_refusal(contract) or "")
    contract["sourceBinding"]["adapter"] = "alfred-fred"
    contract["unit"] = "thousands"
    # Whichever refusal comes first: the family has no admission predicate,
    # and (once A-19 gains a FAMILY_ADAPTERS entry) ALFRED is not its adapter.
    refusal = _refusal(contract) or ""
    assert (
        "no registration-time admission predicate" in refusal
        or "is not one the a19 family resolves" in refusal
    )


def test_unregistrable_family_refuses_whatever_the_adapter(
    registered: dict[str, dict],
) -> None:
    contract = _first(registered, "alfred-fred")
    stem = next(iter(resolve_pending.BLS_API_ADAPTERS))
    spec = resolve_pending.BLS_API_ADAPTERS[stem]
    assert spec["period_type"] == "month"
    contract.update(
        series=stem,
        dataPointId=f"{stem}.2030_01.first_print",
        unit=spec["unit"],
    )
    assert "is not one the bls_api family resolves" in (_refusal(contract) or "")


def test_census_spm_is_refused_while_unarmed(registered: dict[str, dict]) -> None:
    contract = registered["census.spm.child_poverty_rate.2027.first_print.current_law"][
        "contract"
    ]
    assert "unarmed" in (_refusal(contract) or "")


def test_a_family_without_a_predicate_fails_closed(
    registered: dict[str, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = _first(registered, "alfred-fred")
    checks = dict(resolve_pending.EXECUTION_PLAN_FAMILY_CHECKS)
    del checks["alfred"]
    monkeypatch.setattr(resolve_pending, "EXECUTION_PLAN_FAMILY_CHECKS", checks)
    assert "no registration-time admission predicate" in (_refusal(contract) or "")


def test_the_verdict_never_touches_the_network_or_records(
    registered: dict[str, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    contracts = [registration["contract"] for registration in registered.values()]

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("execution_plan_refusal must stay offline")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(resolve_pending, "registration_contracts", refuse)
    for contract in contracts:
        _refusal(contract)


def test_malformed_registrations_are_refused_not_raised() -> None:
    for registration in (
        {},
        {"contract": None},
        {"contract": {"sourceBinding": None}},
        {"contract": {"sourceBinding": {"adapter": "alfred-fred"}}},
        {
            "contract": {
                "dataPointId": "x.y.2030_01.first_print",
                "sourceBinding": {"adapter": "alfred-fred"},
            }
        },
    ):
        assert resolve_pending.execution_plan_refusal(registration)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("expectedReleaseWindow", "2026-13-45"),
        ("expectedReleaseWindow", 7),
        ("expectedReleaseWindow", True),
        ("expectedReleaseWindow", ["2026-10-01", "2026-10-02"]),
        ("allowedHosts", "www.bls.gov"),
        ("allowedHosts", 7),
        ("allowedHosts", True),
        ("allowedHosts", [7]),
        ("allowedHosts", None),
    ],
)
def test_malformed_binding_shapes_refuse_for_every_family(
    registered: dict[str, dict], key: str, value: object
) -> None:
    for adapter in ("alfred-fred", "statcan-wds", "usaspending-api", "bls-qcew"):
        try:
            contract = _first(registered, adapter)
        except AssertionError:
            continue
        contract["sourceBinding"][key] = value
        assert _refusal(contract), (adapter, key, value)


# -- the registrar ------------------------------------------------------------


def _configure_root(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generated = tmp_path / "ledger-targets.generated.ts"
    generated.write_text(
        'import type { TargetRegisteredLedgerEntry } from "./ledger-targets";\n'
        "export const GENERATED_FORECAST_TARGETS = [\n"
        "] satisfies TargetRegisteredLedgerEntry[];\n"
    )
    monkeypatch.setattr(register_targets, "ROOT", tmp_path)
    monkeypatch.setattr(register_targets, "GENERATED_TARGETS", generated)


def _generic_target() -> dict:
    return {
        "series": "bls.cps.unemployment_rate",
        "period": "2030-01",
        "catalogSlug": "unemployment-rate-january-2030",
        "targetUnit": "percent",
        "valueScale": 1,
        "previousTarget": {
            "period": "2029-12",
            "dataPointId": "bls.cps.unemployment_rate.2029_12.first_print",
            "country": "US",
            "unit": "percent",
            "resolutionDate": "2030-01-10",
            "resolutionSource": "Employment Situation",
            "resolutionSourceUrl": "https://www.bls.gov/news.release/empsit.nr0.htm",
        },
    }


def _claims_target() -> dict:
    return {
        "series": "us.dol.initial_claims.sa",
        "period": "week_2030-01-12",
        "catalogSlug": "initial-claims-week-2030-01-12",
        "targetUnit": "thousands",
        "valueScale": 0.001,
    }


REGISTERED_AT = ("2030-01-02", "2030-01-02T14:00:00Z")


def _register(path: pathlib.Path, **kwargs: object) -> list[dict]:
    return register_targets.register(
        path, dt.date.fromisoformat(REGISTERED_AT[0]), REGISTERED_AT[1], **kwargs
    )


def test_register_refuses_a_new_target_without_a_plan_and_writes_nothing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_root(tmp_path, monkeypatch)
    generated_before = register_targets.GENERATED_TARGETS.read_text()
    targets_path = tmp_path / "targets.json"
    # An executable target in the same file must not be half-registered.
    payload = {"targets": [_claims_target(), _generic_target()]}
    targets_path.write_text(json.dumps(payload))

    with pytest.raises(
        register_targets.RegistrationError,
        match="unemployment-rate-january-2030 has no executable resolution plan",
    ):
        _register(targets_path)

    assert not (tmp_path / "records").exists()
    assert register_targets.GENERATED_TARGETS.read_text() == generated_before
    assert json.loads(targets_path.read_text()) == payload


def test_templateless_series_waiver_does_not_waive_the_plan(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waivers = json.loads((ROOT / "waivers.json").read_text())["waivers"]
    target = _generic_target()
    assert target["series"] in waivers["templateless_docket_series"]["members"]
    _configure_root(tmp_path, monkeypatch)
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps({"targets": [target]}))
    with pytest.raises(
        register_targets.RegistrationError, match="no executable resolution plan"
    ):
        _register(targets_path)
    # The gate has no grandfather set to edit.
    for function in (
        register_targets.require_execution_plan,
        register_targets.execution_plan_refusal,
        resolve_pending.execution_plan_refusal,
    ):
        assert "waiver" not in inspect.getsource(function).replace(
            "``waivers.json``", ""
        )


def test_skip_unbindable_registers_the_executable_and_reports_the_rest(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_root(tmp_path, monkeypatch)
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps({"targets": [_generic_target(), _claims_target()]})
    )

    registrations = _register(targets_path, skip_unbindable=True)

    assert [row["contract"]["catalogSlug"] for row in registrations] == [
        "initial-claims-week-2030-01-12"
    ]
    assert len(list((tmp_path / "records" / "targets").glob("*.json"))) == 1
    assert [
        row["catalogSlug"] for row in json.loads(targets_path.read_text())["targets"]
    ] == ["initial-claims-week-2030-01-12"]
    err = capsys.readouterr().err
    assert "skipping unbindable target unemployment-rate-january-2030" in err
    assert "no executable resolution plan" in err


def test_skip_unbindable_with_only_unexecutable_targets_registers_nothing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_root(tmp_path, monkeypatch)
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps({"targets": [_generic_target()]}))
    with pytest.raises(
        register_targets.RegistrationError, match="no bindable targets in this roll"
    ):
        _register(targets_path, skip_unbindable=True)
    assert not (tmp_path / "records").exists()


def test_skip_unbindable_never_downgrades_a_snapshot_integrity_error(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_root(tmp_path, monkeypatch)
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps({"targets": [_claims_target()]}))
    (registration,) = _register(targets_path)
    # Tamper with the committed snapshot: same content hash, not canonical.
    registration["path"].write_text(
        json.dumps(json.loads(registration["path"].read_text()), indent=4)
    )
    for kwargs in ({}, {"skip_unbindable": True}):
        targets_path.write_text(json.dumps({"targets": [_claims_target()]}))
        with pytest.raises(
            register_targets.RegistrationError, match="snapshot is not canonical"
        ):
            _register(targets_path, **kwargs)


def test_reuse_existing_only_keeps_its_own_refusal_for_an_unregistered_target(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_root(tmp_path, monkeypatch)
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps({"targets": [_generic_target()]}))
    with pytest.raises(
        register_targets.RegistrationError,
        match="--reuse-existing-only refused target",
    ):
        _register(targets_path, reuse_existing_only=True)
    assert not (tmp_path / "records").exists()


def test_a_contract_the_resolver_cannot_judge_is_refused_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(registration: dict) -> str | None:
        raise TypeError("unhashable type: 'list'")

    monkeypatch.setattr(register_targets, "execution_plan_refusal", explode)
    registration = {
        "existing": False,
        "contract": {"catalogSlug": "slug", "series": "agency.test.rate"},
    }
    with pytest.raises(
        register_targets.RegistrationError,
        match="the resolver could not judge the contract: unhashable",
    ):
        register_targets.require_execution_plan(registration)
    # An existing snapshot is never judged at all.
    register_targets.require_execution_plan({**registration, "existing": True})


def test_an_existing_generic_registration_is_reused_not_rejudged(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_root(tmp_path, monkeypatch)
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps({"targets": [_generic_target()]}))
    # History: this snapshot was written before the gate existed.
    with monkeypatch.context() as patch:
        patch.setattr(
            register_targets, "execution_plan_refusal", lambda registration: None
        )
        (before,) = _register(targets_path)
    snapshot_bytes = before["path"].read_bytes()

    targets_path.write_text(json.dumps({"targets": [_generic_target()]}))
    (after,) = _register(targets_path, reuse_existing_only=True)

    assert after["existing"] is True
    assert after["path"] == before["path"]
    assert before["path"].read_bytes() == snapshot_bytes


# -- the roller and the prospect validator ------------------------------------


def _append(unit: dict | list[dict], registered_ids: frozenset[str]) -> list:
    candidates: list = []
    roll_docket.append_roll_candidate(
        candidates,
        3,
        "2030-01",
        unit,
        expired_data_point_ids=frozenset(),
        registered_data_point_ids=registered_ids,
    )
    return candidates


def test_roller_drops_an_unexecutable_series_before_the_cap(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _append(_generic_target(), frozenset()) == []
    assert "no executable resolution plan" in capsys.readouterr().out
    claims = _claims_target()
    assert _append(claims, frozenset()) == [(3, "2030-01", claims)]


def test_roller_never_splits_a_pair_whose_arm_has_no_plan(
    capsys: pytest.CaptureFixture[str],
) -> None:
    pair = [_claims_target(), _generic_target()]
    assert _append(pair, frozenset()) == []
    out = capsys.readouterr().out
    assert "unemployment-rate-january-2030: no executable resolution plan" in out
    assert "initial-claims-week-2030-01-12: conditional pair-mate has no" in out


def test_roller_leaves_an_unbuildable_target_to_registration() -> None:
    target = {"series": "agency.test.rate", "period": "2030-01", "catalogSlug": "x"}
    assert roll_docket.roll_execution_plan_refusal(target) is None


def test_prospect_validation_refuses_a_proposal_without_a_plan(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    def verdict(registration: dict) -> str | None:
        calls.append(registration)
        return "sourceBinding.adapter is 'generic-url'"

    monkeypatch.setattr(prospect_targets, "execution_plan_refusal", verdict)
    monkeypatch.setattr(prospect_targets, "_common_target_errors", lambda *a, **k: [])
    payload = {
        "schemaVersion": prospect_targets.PROPOSAL_SCHEMA,
        "proposals": [{"origin": "ledger_gap", "target": _generic_target()}],
    }
    state = prospect_targets.ValidationState(
        catalog_slugs=frozenset(), registry_series=frozenset(), denied=frozenset()
    )
    with pytest.raises(
        prospect_targets.ProspectValidationError,
        match="no executable resolution plan: sourceBinding.adapter is 'generic-url'",
    ):
        prospect_targets.validate_proposals(
            payload,
            today=dt.date(2030, 1, 2),
            root=tmp_path,
            state=state,
            strict=True,
        )
    assert calls and calls[0]["contract"]["series"] == "bls.cps.unemployment_rate"
    envelope, batch = prospect_targets.validate_proposals(
        payload, today=dt.date(2030, 1, 2), root=tmp_path, state=state, strict=False
    )
    assert envelope["proposals"] == [] and batch == {"targets": []}
