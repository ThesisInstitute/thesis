from __future__ import annotations

import datetime as dt
import json
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import bill_forecast_plan as plans  # noqa: E402


@pytest.fixture
def repo(tmp_path: pathlib.Path, monkeypatch) -> pathlib.Path:
    for relative in (
        "scripts/bill_forecast_bindings.json",
        "scripts/docket_series.json",
        "bills/s3596-119.json",
        "bills/raw/s3596-119.txt",
        "bills/raw/s3596-119.meta.json",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    docket = json.loads((tmp_path / "scripts/docket_series.json").read_text())
    rows = {}
    for entry in docket["series"]:
        pair = entry.get("conditionalPair")
        if not pair:
            continue
        for arm in pair["arms"]:
            row = rows.setdefault(
                arm["conditionId"],
                {
                    "conditionId": arm["conditionId"],
                    "status": "open",
                    "type": "recorded_status",
                    "resolvesBy": pair["conditionDeadline"],
                    "matchStrings": [],
                },
            )
            row["matchStrings"].append(arm["conditional"])
    monkeypatch.setattr(plans, "load_conditions", lambda _root: list(rows.values()))
    return tmp_path


def actc(repo: pathlib.Path) -> dict:
    return plans.build_bill_selection(repo, "s3596-119", "irs.actc.total_claims")


def condition_rows(plan: dict) -> list[dict]:
    return [
        {**contract, "status": "open"}
        for pair in plan["pairs"]
        for contract in pair["conditionContracts"]
    ]


def check(repo: pathlib.Path, plan: dict, date: str = "2026-09-21") -> None:
    plans.require_open_bill_selection(
        repo, plan, dt.datetime.fromisoformat(date + "T00:00:00+00:00")
    )


def test_bill_joins_source_reviewed_metric_chronicle_and_both_arms(repo, monkeypatch):
    plan = actc(repo)
    assert len(plan["catalogSlugs"]) == 2
    assert plan["pairs"][0]["ledgerUuid"] == "23396038-b31d-43cd-be08-4aa9fe916b56"
    assert plan["pairs"][0]["metricLocations"]
    assert plan["sourceTextSha256"]
    assert len(plans.build_bill_selection(repo, "s3596-119")["catalogSlugs"]) == 4
    monkeypatch.setattr(plans, "load_conditions", lambda _root: condition_rows(plan))
    check(repo, plan)


@pytest.mark.parametrize("slug", ["../s3596-119", "", "/tmp/bill", "not-reviewed"])
def test_bill_requires_reviewed_safe_identity(repo, slug):
    with pytest.raises(plans.BillSelectionError):
        plans.build_bill_selection(repo, slug)


def test_unreviewed_outcome_cannot_be_selected(repo):
    with pytest.raises(plans.BillSelectionError, match="not one reviewed"):
        plans.build_bill_selection(repo, "s3596-119", "bls.cps.unemployment_rate")


def test_malformed_review_registry_fails_closed(repo):
    path = repo / "scripts/bill_forecast_bindings.json"
    registry = json.loads(path.read_text())
    registry["bills"] = []
    path.write_text(json.dumps(registry))
    with pytest.raises(plans.BillSelectionError, match="malformed"):
        actc(repo)


@pytest.mark.parametrize(
    "relative",
    [
        "bills/s3596-119.json",
        "bills/raw/s3596-119.txt",
    ],
)
def test_changed_analysis_or_bill_text_requires_review(repo, relative):
    path = repo / relative
    path.write_text(path.read_text() + "\n")
    with pytest.raises(plans.BillSelectionError, match="changed|differs"):
        actc(repo)


def test_source_url_cannot_be_rebound(repo):
    path = repo / "bills/raw/s3596-119.meta.json"
    meta = json.loads(path.read_text())
    meta["source_url"] = "https://example.org/other-bill"
    path.write_text(json.dumps(meta))
    with pytest.raises(plans.BillSelectionError, match="source identity"):
        actc(repo)


@pytest.mark.parametrize("mutation", ["uuid", "missing_sibling", "duplicate_slug"])
def test_docket_mapping_requires_exact_series_identity_and_pair(repo, mutation):
    path = repo / "scripts/docket_series.json"
    docket = json.loads(path.read_text())
    entry = next(e for e in docket["series"] if e["series"] == "irs.actc.total_claims")
    if mutation == "uuid":
        entry["ledger"]["uuid"] = "different-series"
    elif mutation == "missing_sibling":
        entry["conditionalPair"]["arms"].pop()
    else:
        arms = entry["conditionalPair"]["arms"]
        arms[1]["catalogSlug"] = arms[0]["catalogSlug"]
    path.write_text(json.dumps(docket))
    with pytest.raises(plans.BillSelectionError):
        actc(repo)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "satisfied"),
        ("status", "failed"),
        ("matchStrings", ["different law"]),
        ("resolvesBy", "2028-12-31"),
    ],
)
def test_closed_or_drifted_condition_cannot_run(repo, monkeypatch, field, value):
    plan = actc(repo)
    conditions = condition_rows(plan)
    conditions[0][field] = value
    monkeypatch.setattr(plans, "load_conditions", lambda _root: conditions)
    with pytest.raises(
        plans.BillSelectionError, match="closed or differs|changed since"
    ):
        check(repo, plan)


def test_legal_meaning_cannot_change_during_generation(repo, monkeypatch):
    plan = actc(repo)
    conditions = condition_rows(plan)
    conditions[0]["statutoryTest"] = "A different provision becomes law"
    monkeypatch.setattr(plans, "load_conditions", lambda _root: conditions)
    with pytest.raises(plans.BillSelectionError, match="changed since selection"):
        check(repo, plan)


def test_deadline_is_exclusive_and_checked_in_utc(repo, monkeypatch):
    plan = actc(repo)
    monkeypatch.setattr(plans, "load_conditions", lambda _root: condition_rows(plan))
    check(repo, plan, "2027-12-30")
    with pytest.raises(plans.BillSelectionError, match="boundary reached"):
        check(repo, plan, "2027-12-31")
    with pytest.raises(plans.BillSelectionError, match="boundary reached"):
        plans.require_open_bill_selection(
            repo, plan, dt.datetime.fromisoformat("2027-12-30T23:30:00-05:00")
        )


def test_mapping_rechecked_after_selection(repo, monkeypatch):
    plan = actc(repo)
    monkeypatch.setattr(plans, "load_conditions", lambda _root: condition_rows(plan))
    path = repo / "scripts/bill_forecast_bindings.json"
    registry = json.loads(path.read_text())
    registry["bills"]["s3596-119"]["pairs"][0]["metricLabel"] = "Changed meaning"
    path.write_text(json.dumps(registry))
    with pytest.raises(plans.BillSelectionError, match="changed since selection"):
        check(repo, plan)


def test_plan_cannot_drop_a_sibling_after_selection(repo, monkeypatch):
    plan = actc(repo)
    monkeypatch.setattr(plans, "load_conditions", lambda _root: condition_rows(plan))
    plan["catalogSlugs"].pop()
    with pytest.raises(plans.BillSelectionError, match="changed since selection"):
        check(repo, plan)
