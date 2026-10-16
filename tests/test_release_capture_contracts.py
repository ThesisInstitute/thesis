"""Exact legacy fingerprints never admit a new generic-url registration.

Only immutable registration metadata is read. No capture, target-month value,
resolution record, or other outcome is fetched or inspected by these tests.
"""

from __future__ import annotations

import copy
import json
import pathlib
import socket
import sys
import urllib.request
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import register_targets  # noqa: E402
import resolve_pending  # noqa: E402
from canonical_json import canonical_bytes, canonical_sha256  # noqa: E402
from legacy_release_contracts import (  # noqa: E402
    LEGACY_RELEASE_ALFRED_CONTRACTS,
    LEGACY_RELEASE_CAPTURE_CONTRACTS,
    legacy_release_contract_mismatches,
)

REVIEWED = {
    **LEGACY_RELEASE_CAPTURE_CONTRACTS,
    **LEGACY_RELEASE_ALFRED_CONTRACTS,
}


def _registration(content_hash: str) -> dict[str, Any]:
    return {
        "targetContentHash": content_hash,
        "contract": copy.deepcopy(REVIEWED[content_hash]["contract"]),
    }


def _paths(
    value: dict[str, Any], prefix: tuple[str, ...] = ()
) -> list[tuple[str, ...]]:
    paths = []
    for key, child in value.items():
        path = (*prefix, key)
        paths.append(path)
        if isinstance(child, dict):
            paths.extend(_paths(child, path))
    return paths


def _at_path(value: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    for key in path[:-1]:
        value = value[key]
    return value


def _mutated(value: Any) -> Any:
    if isinstance(value, str):
        return value + " [unreviewed]"
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, list):
        return [*value, "unreviewed.example"]
    if isinstance(value, dict):
        return {**value, "unreviewed": True}
    raise AssertionError(f"unexpected contract field type {type(value)}")


def test_only_the_reviewed_twelve_capture_contracts_and_one_alfred_case() -> None:
    # Telework September (0bc190e7…) is not here: a build agent saw its target
    # figure on the live page before this assignment was committed (d1633).
    assert len(LEGACY_RELEASE_CAPTURE_CONTRACTS) == 12
    assert "0bc190e7fe95e2a7812ba70143f1394069f3cc59c61671e6021c2283181fc418" not in (
        LEGACY_RELEASE_CAPTURE_CONTRACTS
    )
    assert len(LEGACY_RELEASE_ALFRED_CONTRACTS) == 1
    assert {entry["parser"] for entry in LEGACY_RELEASE_CAPTURE_CONTRACTS.values()} == {
        "cpi_headline_mom",
        "cpi_core_mom",
        "empsit_unemployment_rate",
        "empsit_payroll_change",
        "jolts_job_openings",
        "jolts_quits_rate",
    }
    assert all(
        entry["contract"]["sourceBinding"]["adapter"] == "generic-url"
        for entry in LEGACY_RELEASE_CAPTURE_CONTRACTS.values()
    )
    (entry,) = LEGACY_RELEASE_ALFRED_CONTRACTS.values()
    assert entry["stem"] == "bls.ppi.final_demand_monthly_change"
    assert entry["contract"]["sourceBinding"]["adapter"] == "alfred-fred"
    assert entry["contract"]["sourceBinding"]["sourceSeriesId"] == "PPIFIS"


@pytest.mark.parametrize("content_hash,entry", REVIEWED.items())
def test_fingerprint_equals_committed_registration_and_its_canonical_hash(
    content_hash: str, entry: dict[str, Any]
) -> None:
    paths = list((ROOT / "records" / "targets").glob(f"*-{content_hash}.json"))
    assert len(paths) == 1
    snapshot = json.loads(paths[0].read_text())
    assert snapshot["targets"] == [entry["contract"]]
    payload = register_targets.registration_hash_payload(snapshot)
    assert canonical_bytes(entry["hashPayload"]) == canonical_bytes(payload)
    assert canonical_sha256(entry["hashPayload"]) == content_hash
    assert register_targets.registration_content_hash(snapshot) == content_hash
    assert not legacy_release_contract_mismatches(_registration(content_hash), entry)


@pytest.mark.parametrize(
    "content_hash,path",
    [
        (content_hash, path)
        for content_hash, entry in REVIEWED.items()
        for path in _paths(entry["contract"])
    ],
)
def test_changing_any_contract_key_refuses_and_names_that_key(
    content_hash: str, path: tuple[str, ...]
) -> None:
    registration = _registration(content_hash)
    parent = _at_path(registration["contract"], path)
    parent[path[-1]] = _mutated(parent[path[-1]])
    differences = legacy_release_contract_mismatches(
        registration, REVIEWED[content_hash]
    )
    assert differences
    assert any(
        key == ".".join(path) or key.startswith(".".join(path) + ".")
        for key in differences
    )


@pytest.mark.parametrize(
    "content_hash,path",
    [
        (content_hash, path)
        for content_hash, entry in REVIEWED.items()
        for path in _paths(entry["contract"])
    ],
)
def test_deleting_any_contract_key_refuses_and_names_that_key(
    content_hash: str, path: tuple[str, ...]
) -> None:
    registration = _registration(content_hash)
    del _at_path(registration["contract"], path)[path[-1]]
    assert ".".join(path) in legacy_release_contract_mismatches(
        registration, REVIEWED[content_hash]
    )


@given(
    content_hash=st.sampled_from(list(REVIEWED)),
    added_key=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20),
    nested=st.booleans(),
)
def test_added_unreviewed_keys_cannot_borrow_an_exact_hash(
    content_hash: str, added_key: str, nested: bool
) -> None:
    registration = _registration(content_hash)
    contract = registration["contract"]
    parent = contract["sourceBinding"] if nested else contract
    key = "unreviewed_" + added_key
    parent[key] = None
    expected = ("sourceBinding." if nested else "") + key
    assert expected in legacy_release_contract_mismatches(
        registration, REVIEWED[content_hash]
    )


@pytest.mark.parametrize("content_hash,entry", REVIEWED.items())
def test_matching_contract_cannot_borrow_an_unreviewed_hash(
    content_hash: str, entry: dict[str, Any]
) -> None:
    registration = _registration(content_hash)
    registration["targetContentHash"] = "0" * 64
    assert legacy_release_contract_mismatches(registration, entry) == [
        "targetContentHash"
    ]


def test_bool_is_not_a_byte_identical_numeric_transform() -> None:
    content_hash, entry = next(iter(LEGACY_RELEASE_CAPTURE_CONTRACTS.items()))
    registration = _registration(content_hash)
    registration["contract"]["sourceBinding"]["transform"]["factor"] = True
    assert "sourceBinding.transform.factor" in legacy_release_contract_mismatches(
        registration, entry
    )


def test_all_contract_differences_are_reported_together() -> None:
    content_hash, entry = next(iter(LEGACY_RELEASE_CAPTURE_CONTRACTS.items()))
    registration = _registration(content_hash)
    del registration["contract"]["country"]
    registration["contract"]["period"] = "2030-01"
    registration["contract"]["sourceBinding"]["extra"] = None
    registration["targetContentHash"] = None
    assert legacy_release_contract_mismatches(registration, entry) == [
        "country",
        "period",
        "sourceBinding.extra",
        "targetContentHash",
    ]


@pytest.mark.parametrize("content_hash", LEGACY_RELEASE_CAPTURE_CONTRACTS)
def test_new_generic_url_registration_stays_refused_without_network(
    content_hash: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("registration admission must not make a network request")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    registration = _registration(content_hash)
    assert "generic-url" in (resolve_pending.execution_plan_refusal(registration) or "")
    # The write gate re-judges even the exact old fingerprint when planning a
    # NEW snapshot. The run-time disposition has no grandfather power here.
    registration["existing"] = False
    with pytest.raises(register_targets.RegistrationError, match="generic-url"):
        register_targets.require_execution_plan(registration)
    registration["contract"]["period"] = "2030-01"
    registration["targetContentHash"] = None
    with pytest.raises(register_targets.RegistrationError, match="generic-url"):
        register_targets.require_execution_plan(registration)


def test_each_reference_quotes_its_own_forecast_question_verbatim() -> None:
    """QUESTIONS is the reviewed reading of what each forecast asked; it must
    be that forecast's own text, for every reference and no other."""
    from legacy_release_parsers import QUESTIONS

    parsers = {
        entry["contract"]["dataPointId"]: entry["parser"]
        for entry in LEGACY_RELEASE_CAPTURE_CONTRACTS.values()
    }
    assert set(QUESTIONS) == set(parsers)
    texts = [
        path.read_text(errors="replace")
        for path in (ROOT / "site" / "src" / "data" / "forecast-examples").glob("*.ts")
    ]
    for ref, (parser_id, question) in QUESTIONS.items():
        assert parser_id == parsers[ref], ref
        assert any(ref in text and question in text for text in texts), ref
