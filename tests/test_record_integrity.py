from __future__ import annotations

import gzip
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import producer_signing_pins as producer_pins  # noqa: E402
import verify_record_chain as record_chain  # noqa: E402


@pytest.fixture(autouse=True)
def _dormant_producer_signing(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Synthetic-chain fixtures never contain the real activation snapshot;
    they exercise enumeration/witness/integrity properties, so producer
    signing is dormant for them. Tests marked ``live_records`` verify the
    REAL tree, which has carried producer signatures since the first signed
    snapshot (2026-07-22, digest-29881445405-1) and must run under the
    committed armed pins. Armed-state signature coverage lives in
    tests/test_producer_signing.py."""

    if request.node.get_closest_marker("live_records"):
        return
    monkeypatch.setattr(producer_pins, "PRODUCER_SPKI_SHA256", None)
    monkeypatch.setattr(producer_pins, "ACTIVATION_SNAPSHOT", None)
import witnessed_timeline as timeline_module  # noqa: E402
from canonical_json import (  # noqa: E402
    canonical_bytes,
    canonical_sha256,
    canonical_stringify,
)
from record_forecast_snapshot import validate_deployment_identity  # noqa: E402
from run_thesis_analyst import finalize_manifest, write_artifact  # noqa: E402
from verify_custody import (  # noqa: E402
    RECORDER_REQUIRED_LIVE,
    RECORDER_REQUIRED_SURFACES,
    CustodyError,
    verify_recorder_snapshot,
    verify_run,
)
from verify_record_chain import (  # noqa: E402
    ChainError,
    validate_token_time,
    verify_chain,
    verify_records,
    verify_witness,
)
from witnessed_timeline import extract_timeline  # noqa: E402


def deployment_build(commit: str, deployment: str) -> dict[str, str]:
    return {"commit": commit, "deploymentUrl": deployment}


def test_recorder_requires_exact_expected_sha_and_pinned_deployments() -> None:
    commit = "a" * 40
    site_deployment = "brier-abc123.vercel.app"
    api_deployment = "thesis-api-def456.vercel.app"
    kwargs = {
        "site_build": deployment_build(commit, site_deployment),
        "api_build": deployment_build("b" * 40, api_deployment),
        "site_deployment_url": f"https://{site_deployment}",
        "api_deployment_url": f"https://{api_deployment}",
        "expected_sha": commit,
        "ancestry_distance": 0,
    }
    validate_deployment_identity(**kwargs)

    with pytest.raises(ValueError, match="does not exactly match"):
        validate_deployment_identity(**{**kwargs, "expected_sha": "c" * 40})
    with pytest.raises(ValueError, match="site build deploymentUrl"):
        validate_deployment_identity(
            **{
                **kwargs,
                "site_deployment_url": "https://another.vercel.app",
            }
        )


def test_recorder_workflow_uses_the_multi_tsa_witness_writer() -> None:
    workflow = (ROOT / ".github/workflows/record-forecasts.yml").read_text()
    # The witness writer imports the chain verifier, which needs receipt now
    # that producer signing is armed, so it runs under the locked custody env.
    assert (
        "uv run --locked --extra custody python scripts/witness_snapshot.py"
    ) in workflow
    assert "python3 scripts/witness_snapshot.py" not in workflow
    assert "thesis_rfc3161_witness_v1" not in workflow


def write_json(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def add_witness(snapshot: pathlib.Path) -> None:
    write_json(
        snapshot.with_suffix(".witness.json"),
        {
            "schemaVersion": "thesis_rfc3161_witness_v1",
            "status": "unavailable",
            "digestSha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            "reason": "synthetic test fixture",
        },
    )


@pytest.fixture
def synthetic_chain(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    records = tmp_path / "records"
    legacy = records / "2026-01-01" / "digest.json"
    write_json(legacy, {"legacy": True})
    first = records / "2026-01-02" / "digest-genesis.json"
    write_json(
        first,
        {
            "schemaVersion": "thesis_record_snapshot_v2",
            "snapshotKind": "chain_genesis_cutover",
            "runId": "genesis",
            "recordedAt": "2026-01-02T00:00:00Z",
            "dependencies": {"recorderRepositoryCommit": "a" * 40},
            "legacyTip": {
                "path": "records/2026-01-01/digest.json",
                "sha256": hashlib.sha256(legacy.read_bytes()).hexdigest(),
            },
        },
    )
    add_witness(first)
    second = records / "2026-01-03" / "digest-100.json"
    write_json(
        second,
        {
            "schemaVersion": "thesis_record_snapshot_v2",
            "snapshotKind": "recorder_run",
            "runId": "100",
            "recordedAt": "2026-01-03T00:00:00Z",
            "chain": {
                "prevDigestPath": "records/2026-01-02/digest-genesis.json",
                "prevDigestSha256": hashlib.sha256(first.read_bytes()).hexdigest(),
            },
        },
    )
    add_witness(second)
    write_json(
        records / "CHAIN_GENESIS.json",
        {
            "schemaVersion": "thesis_record_chain_genesis_v1",
            "firstSnapshot": "records/2026-01-02/digest-genesis.json",
            "legacyDigests": [
                {
                    "path": "records/2026-01-01/digest.json",
                    "sha256": hashlib.sha256(legacy.read_bytes()).hexdigest(),
                }
            ],
        },
    )
    write_json(
        records / "CHAIN_HEAD.json",
        {
            "schemaVersion": "thesis_record_chain_head_v1",
            "snapshotPath": "records/2026-01-03/digest-100.json",
            "snapshotSha256": hashlib.sha256(second.read_bytes()).hexdigest(),
        },
    )
    return records, second


def test_record_chain_fails_when_a_post_genesis_link_is_deleted(
    synthetic_chain: tuple[pathlib.Path, pathlib.Path],
) -> None:
    records, second = synthetic_chain
    assert len(verify_records(records, allow_pre_enumeration=True)) == 2

    payload = json.loads(second.read_text())
    del payload["chain"]
    write_json(second, payload)

    with pytest.raises(ChainError, match="missing chain block after genesis"):
        verify_records(records, allow_pre_enumeration=True)


def test_record_chain_rejects_rollback_before_enumeration_cutover(
    synthetic_chain: tuple[pathlib.Path, pathlib.Path],
) -> None:
    records, _second = synthetic_chain
    with pytest.raises(ChainError, match="mandatory complete genesis enumeration"):
        verify_records(records)


def test_record_chain_fails_when_a_linked_snapshot_is_missing(
    synthetic_chain: tuple[pathlib.Path, pathlib.Path],
) -> None:
    records, second = synthetic_chain
    third = records / "2026-01-04" / "digest-101.json"
    write_json(
        third,
        {
            "schemaVersion": "thesis_record_snapshot_v2",
            "snapshotKind": "recorder_run",
            "runId": "101",
            "recordedAt": "2026-01-04T00:00:00Z",
            "chain": {
                "prevDigestPath": "records/2026-01-03/digest-100.json",
                "prevDigestSha256": hashlib.sha256(second.read_bytes()).hexdigest(),
            },
        },
    )
    add_witness(third)
    write_json(
        records / "CHAIN_HEAD.json",
        {
            "schemaVersion": "thesis_record_chain_head_v1",
            "snapshotPath": "records/2026-01-04/digest-101.json",
            "snapshotSha256": hashlib.sha256(third.read_bytes()).hexdigest(),
        },
    )
    second.unlink()
    second.with_suffix(".witness.json").unlink()

    with pytest.raises(ChainError, match="missing predecessor"):
        verify_records(records, allow_pre_enumeration=True)


def test_record_chain_head_detects_deleted_tail(
    synthetic_chain: tuple[pathlib.Path, pathlib.Path],
) -> None:
    records, second = synthetic_chain
    second.unlink()
    second.with_suffix(".witness.json").unlink()

    with pytest.raises(ChainError, match="chain head path mismatch"):
        verify_records(records, allow_pre_enumeration=True)


def add_enumeration_cutover(
    records: pathlib.Path,
    previous: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[pathlib.Path, pathlib.Path]:
    extra = records / "legacy-extra.txt"
    extra.write_text("legacy bytes\n")
    legacy = records / "2026-01-01" / "digest.json"
    entries = []
    for path in sorted([legacy, extra]):
        raw = path.read_bytes()
        entries.append(
            {
                "path": f"records/{path.relative_to(records).as_posix()}",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }
        )
    enumeration = {
        "schemaVersion": "thesis_legacy_record_enumeration_v1",
        "sourceCommit": "a" * 40,
        "entryCount": len(entries),
        "totalSize": sum(entry["size"] for entry in entries),
        "entries": entries,
    }
    enumeration_path = records / "GENESIS_RECORDS.json"
    enumeration_path.write_bytes(canonical_bytes(enumeration))
    enumeration_ref = {
        "path": "records/GENESIS_RECORDS.json",
        "sha256": hashlib.sha256(enumeration_path.read_bytes()).hexdigest(),
        "canonicalJsonSha256": canonical_sha256(enumeration),
        "size": enumeration_path.stat().st_size,
        "entryCount": len(entries),
        "totalSize": enumeration["totalSize"],
        "sourceCommit": "a" * 40,
    }
    shutil.copytree(ROOT / "records" / "trust", records / "trust")
    cutover = records / "2026-01-04" / "digest-enumeration-cutover.json"
    genesis_path = records / "CHAIN_GENESIS.json"
    genesis = json.loads(genesis_path.read_text())
    genesis["legacyEnumeration"] = enumeration_ref
    trust_path = records / "trust" / "tsa-anchors-v1.json"
    trust = json.loads(trust_path.read_text())
    trust_ref = {
        "bundleId": trust["bundleId"],
        "path": "records/trust/tsa-anchors-v1.json",
        "sha256": hashlib.sha256(trust_path.read_bytes()).hexdigest(),
        "size": trust_path.stat().st_size,
        "canonicalJsonSha256": canonical_sha256(trust),
    }
    genesis["tsaTrustBundle"] = trust_ref
    genesis["enumerationCutoverSnapshot"] = (
        "records/2026-01-04/digest-enumeration-cutover.json"
    )
    write_json(genesis_path, genesis)
    monkeypatch.setattr(
        record_chain,
        "CODE_PINNED_GENESIS_ENUMERATIONS",
        {"records/GENESIS_RECORDS.json": enumeration_ref},
    )
    write_json(
        cutover,
        {
            "schemaVersion": "thesis_record_snapshot_v2",
            "snapshotKind": "genesis_enumeration_cutover",
            "runId": "enumeration-cutover",
            "recordedAt": "2026-01-04T00:00:00Z",
            "chain": {
                "prevDigestPath": f"records/{previous.relative_to(records).as_posix()}",
                "prevDigestSha256": hashlib.sha256(previous.read_bytes()).hexdigest(),
            },
            "genesisCommitments": {
                "legacyEnumeration": enumeration_ref,
                "chainGenesis": {
                    "path": "records/CHAIN_GENESIS.json",
                    "sha256": hashlib.sha256(genesis_path.read_bytes()).hexdigest(),
                    "size": genesis_path.stat().st_size,
                    "canonicalJsonSha256": canonical_sha256(genesis),
                },
                "tsaTrustBundle": trust_ref,
            },
        },
    )
    add_witness(cutover)
    write_json(
        records / "CHAIN_HEAD.json",
        {
            "schemaVersion": "thesis_record_chain_head_v1",
            "snapshotPath": "records/2026-01-04/digest-enumeration-cutover.json",
            "snapshotSha256": hashlib.sha256(cutover.read_bytes()).hexdigest(),
        },
    )
    return enumeration_path, extra


def test_record_chain_rejects_tampered_enumerated_file(
    synthetic_chain: tuple[pathlib.Path, pathlib.Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records, previous = synthetic_chain
    _enumeration, extra = add_enumeration_cutover(records, previous, monkeypatch)
    assert len(verify_records(records)) == 3
    extra.write_text("tampered bytes\n")
    with pytest.raises(
        ChainError, match="enumerated legacy record (size|hash) mismatch"
    ):
        verify_records(records)


def test_record_chain_rejects_missing_committed_enumeration(
    synthetic_chain: tuple[pathlib.Path, pathlib.Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records, previous = synthetic_chain
    enumeration, _extra = add_enumeration_cutover(records, previous, monkeypatch)
    enumeration.unlink()
    with pytest.raises(ChainError, match="committed genesis enumeration is absent"):
        verify_records(records)


def test_record_chain_rejects_incomplete_replacement_enumeration(
    synthetic_chain: tuple[pathlib.Path, pathlib.Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records, previous = synthetic_chain
    enumeration_path, _extra = add_enumeration_cutover(records, previous, monkeypatch)
    enumeration = json.loads(enumeration_path.read_text())
    enumeration["entries"] = enumeration["entries"][:-1]
    enumeration["entryCount"] = len(enumeration["entries"])
    enumeration["totalSize"] = sum(entry["size"] for entry in enumeration["entries"])
    enumeration_path.write_bytes(canonical_bytes(enumeration))
    replacement_ref = {
        "path": "records/GENESIS_RECORDS.json",
        "sha256": hashlib.sha256(enumeration_path.read_bytes()).hexdigest(),
        "canonicalJsonSha256": canonical_sha256(enumeration),
        "size": enumeration_path.stat().st_size,
        "entryCount": enumeration["entryCount"],
        "totalSize": enumeration["totalSize"],
        "sourceCommit": "a" * 40,
    }
    genesis_path = records / "CHAIN_GENESIS.json"
    genesis = json.loads(genesis_path.read_text())
    genesis["legacyEnumeration"] = replacement_ref
    write_json(genesis_path, genesis)
    cutover = records / "2026-01-04/digest-enumeration-cutover.json"
    digest = json.loads(cutover.read_text())
    digest["genesisCommitments"]["legacyEnumeration"] = replacement_ref
    digest["genesisCommitments"]["chainGenesis"] = {
        "path": "records/CHAIN_GENESIS.json",
        "sha256": hashlib.sha256(genesis_path.read_bytes()).hexdigest(),
        "size": genesis_path.stat().st_size,
        "canonicalJsonSha256": canonical_sha256(genesis),
    }
    write_json(cutover, digest)
    add_witness(cutover)
    write_json(
        records / "CHAIN_HEAD.json",
        {
            "schemaVersion": "thesis_record_chain_head_v1",
            "snapshotPath": "records/2026-01-04/digest-enumeration-cutover.json",
            "snapshotSha256": hashlib.sha256(cutover.read_bytes()).hexdigest(),
        },
    )
    with pytest.raises(ChainError, match="not independently pinned"):
        verify_records(records)


def test_record_chain_rejects_second_genesis_cutover(
    synthetic_chain: tuple[pathlib.Path, pathlib.Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records, previous = synthetic_chain
    add_enumeration_cutover(records, previous, monkeypatch)
    first_cutover = records / "2026-01-04/digest-enumeration-cutover.json"
    second_cutover = records / "2026-01-05/digest-second-cutover.json"
    first_payload = json.loads(first_cutover.read_text())
    write_json(
        second_cutover,
        {
            "schemaVersion": "thesis_record_snapshot_v2",
            "snapshotKind": "genesis_enumeration_cutover",
            "runId": "second-cutover",
            "recordedAt": "2026-01-05T00:00:00Z",
            "chain": {
                "prevDigestPath": (
                    "records/2026-01-04/digest-enumeration-cutover.json"
                ),
                "prevDigestSha256": hashlib.sha256(
                    first_cutover.read_bytes()
                ).hexdigest(),
            },
            "genesisCommitments": first_payload["genesisCommitments"],
        },
    )
    add_witness(second_cutover)
    write_json(
        records / "CHAIN_HEAD.json",
        {
            "schemaVersion": "thesis_record_chain_head_v1",
            "snapshotPath": "records/2026-01-05/digest-second-cutover.json",
            "snapshotSha256": hashlib.sha256(second_cutover.read_bytes()).hexdigest(),
        },
    )
    with pytest.raises(ChainError, match="more than one genesis cutover"):
        verify_records(records)


def test_witness_rejects_self_consistent_unapproved_trust_bundle(
    tmp_path: pathlib.Path,
) -> None:
    records = tmp_path / "records"
    trust_dir = records / "trust"
    trust_dir.mkdir(parents=True)
    source = ROOT / "records/trust/tsa-anchors-v1.json"
    rogue_path = trust_dir / "tsa-anchors-v99.json"
    rogue_path.write_bytes(source.read_bytes())
    rogue_payload = json.loads(rogue_path.read_text())
    rogue_payload["bundleId"] = "tsa-anchors-v99"
    rogue_path.write_bytes(canonical_bytes(rogue_payload) + b"\n")
    rogue_ref = {
        "bundleId": "tsa-anchors-v99",
        "path": "records/trust/tsa-anchors-v99.json",
        "sha256": hashlib.sha256(rogue_path.read_bytes()).hexdigest(),
        "size": rogue_path.stat().st_size,
        "canonicalJsonSha256": canonical_sha256(rogue_payload),
    }
    write_json(
        records / "CHAIN_GENESIS.json",
        {
            "schemaVersion": "thesis_record_chain_genesis_v1",
            "tsaTrustBundle": rogue_ref,
        },
    )
    snapshot = records / "2026-01-01/digest-unapproved.json"
    write_json(snapshot, {"recordedAt": "2026-01-01T00:00:00Z"})
    token = snapshot.with_suffix(".tsr")
    token.write_bytes(b"not a token")
    write_json(
        snapshot.with_suffix(".witness.json"),
        {
            "schemaVersion": "thesis_rfc3161_witness_v1",
            "status": "available",
            "digestSha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            "tsa": "https://freetsa.org/tsr",
            "tsaAnchorId": "freetsa-root-2016",
            "trustBundleId": rogue_ref["bundleId"],
            "trustBundlePath": rogue_ref["path"],
            "trustBundleSha256": rogue_ref["sha256"],
            "tokenPath": "records/2026-01-01/digest-unapproved.tsr",
            "tokenSha256": hashlib.sha256(token.read_bytes()).hexdigest(),
        },
    )
    with pytest.raises(ChainError, match="not independently pinned"):
        verify_witness(snapshot, records=records)


def test_code_pinned_v2_bundle_loads_both_independent_anchors() -> None:
    reference = record_chain.CODE_PINNED_TRUST_BUNDLES[
        "records/trust/tsa-anchors-v2.json"
    ]
    _path, bundle = record_chain._load_trust_bundle(ROOT / "records", reference)
    assert [anchor["id"] for anchor in bundle["anchors"]] == [
        "freetsa-root-2016",
        "digicert-trusted-root-g4",
    ]
    assert (
        bundle["anchors"][0]
        == json.loads((ROOT / "records/trust/tsa-anchors-v1.json").read_text())[
            "anchors"
        ][0]
    )
    assert bundle["anchors"][1]["allowedPolicyOids"] == ["2.16.840.1.114412.7.1"]
    for anchor in bundle["anchors"]:
        assert (
            record_chain._select_anchor(
                ROOT / "records",
                {"tsaAnchorId": anchor["id"], "tsa": anchor["endpoint"]},
                bundle,
            )
            == anchor
        )


@pytest.mark.live_records
def test_real_tokens_use_pinned_freetsa_identity_and_expose_times() -> None:
    # Real tokens are always in the past, so the actual clock is the right
    # verification time; a frozen instant broke on every new recording.
    verification = verify_chain(ROOT / "records", now=datetime.now(timezone.utc))
    # The chain PREFIX is immutable history; the tail grows with each
    # recorded wave.
    assert [path.name for path in verification.ordered][:5] == [
        "digest-f4f3-genesis.json",
        "digest-29052158922-1.json",
        "digest-29053314493-1.json",
        "digest-29054049741-1.json",
        "digest-genesis-enumeration-v1.json",
    ]
    available = [
        verification.witnesses[path]
        for path in verification.ordered
        if verification.witnesses[path].status == "available"
    ]
    gen_times = [evidence.gen_time for evidence in available]
    assert gen_times[:4] == [
        "2026-07-09T21:41:11Z",
        "2026-07-09T22:02:56Z",
        "2026-07-09T22:17:19Z",
        "2026-07-10T04:29:34Z",
    ]
    assert gen_times == sorted(gen_times)
    historical = available[:4]
    assert {evidence.policy_oid for evidence in historical} == {"1.2.3.4.1"}
    assert {evidence.imprint_algorithm_oid for evidence in historical} == {
        "2.16.840.1.101.3.4.2.1"
    }
    assert {evidence.trust_bundle_id for evidence in historical} == {"tsa-anchors-v1"}
    assert {evidence.anchor_id for evidence in historical} == {"freetsa-root-2016"}
    assert {evidence.tsa_spki_sha256 for evidence in historical} == {
        "fa02bd555e3e483d62b4e70be6218692068d2b0b0a7525db58dcbf2901cdb072"
    }
    assert all(evidence.tokens for evidence in available)
    assert all(
        token.trust_bundle_path in record_chain.CODE_PINNED_TRUST_BUNDLES
        for evidence in available
        for token in evidence.tokens
    )
    # The genesis-enumeration cutover carries its external witness now.
    assert verification.enumeration_cutover is not None
    assert (
        verification.witnesses[verification.enumeration_cutover].status == "available"
    )


def test_token_time_rejects_future_and_impossibly_early_values() -> None:
    payload = {
        "schemaVersion": "thesis_record_snapshot_v2",
        "recordedAt": "2026-01-01T12:00:00Z",
    }
    with pytest.raises(ChainError, match="postdates verification time"):
        validate_token_time(
            payload,
            datetime(2026, 1, 1, 13, tzinfo=timezone.utc),
            now=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
            max_future_seconds=0,
            max_token_lead_seconds=300,
        )
    with pytest.raises(ChainError, match="impossibly precedes"):
        validate_token_time(
            payload,
            datetime(2026, 1, 1, 11, tzinfo=timezone.utc),
            now=datetime(2026, 1, 1, 13, tzinfo=timezone.utc),
            max_future_seconds=300,
            max_token_lead_seconds=300,
        )


# Keep this test well away from
# test_current_witnessed_timeline_does_not_backdate_unwitnessed_roots. The two
# take most of the suite's time, and xdist queues up to two more tests behind
# the one a worker is running, so as neighbours they can share a worker and
# run one after the other.
@pytest.mark.live_records
def test_timeline_extracts_direct_and_transitive_cutover_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verification = verify_chain(ROOT / "records")
    cutover = verification.enumeration_cutover
    assert cutover is not None
    witnesses = dict(verification.witnesses)
    witnesses[cutover] = replace(
        witnesses[cutover],
        status="available",
        gen_time="2026-07-10T03:34:00Z",
    )
    witnessed = replace(verification, witnesses=witnesses)
    monkeypatch.setattr(timeline_module, "verify_chain", lambda _records: witnessed)

    timeline = timeline_module.extract_timeline(ROOT / "records")
    # The real records tree grows with every recorded wave; assert the
    # invariants, floored at the state fixed by the enumeration cutover
    # (218 runs / 8 roots / 2 registrations existed then).
    assert len(timeline["runs"]) >= 218
    assert len(timeline["custodyRoots"]) >= 8
    assert len(timeline["registrationSnapshots"]) >= 2
    for proof in timeline["custodyRoots"].values():
        assert proof["coverage"] in {"direct", "transitive"}
        if proof["inventoryStatus"] == "legacy-incomplete":
            assert proof["headlineEligible"] is False
        if proof["headlineEligible"]:
            assert proof["inventoryStatus"] == "complete"
    explicit_runs = {
        commitment["runDirectory"]
        for commitment in json.loads(cutover.read_text())["artifactCommitments"][
            "custodyRoots"
        ]
    }
    assert all(
        timeline["runs"][run]["coverage"] == "transitive" for run in explicit_runs
    )
    assert any(run.startswith("records/brier-judges/") for run in timeline["runs"])
    assert any("median3" in run for run in timeline["runs"])


@pytest.fixture
def synthetic_custody_run(tmp_path: pathlib.Path) -> pathlib.Path:
    run_dir = tmp_path / "run"
    created_at = "2026-01-01T00:00:00Z"
    refs = [
        write_artifact(run_dir, "prompt", "prompt.md", "forecast prompt\n", created_at),
        write_artifact(
            run_dir,
            "command",
            "command.json",
            json.dumps({"backend": "external_command", "argv": ["agent"]}, indent=2),
            created_at,
        ),
        write_artifact(run_dir, "stdout", "stdout.txt", "model output\n", created_at),
        write_artifact(run_dir, "stderr", "stderr.txt", "", created_at),
        write_artifact(
            run_dir, "raw_response", "raw_response.txt", "model output\n", created_at
        ),
        write_artifact(
            run_dir,
            "parsed_cell",
            "parsed_cells.json",
            json.dumps([{"slug": "synthetic", "pointEstimate": 1.5}], indent=2),
            created_at,
        ),
        write_artifact(
            run_dir,
            "normalized_cell",
            "normalized_cells.json",
            json.dumps([{"slug": "synthetic", "pointEstimate": 1.5}], indent=2),
            created_at,
        ),
        write_artifact(
            run_dir,
            "run_distribution",
            "distribution.json",
            json.dumps({"format": "numeric_cdf_v1", "points": []}, indent=2),
            created_at,
        ),
        write_artifact(
            run_dir,
            "validation_report",
            "validation.json",
            json.dumps({"ok": True, "cells": []}, indent=2),
            created_at,
        ),
    ]
    cells = [{"slug": "synthetic", "pointEstimate": 1.5, "activityLog": refs}]
    refs.append(
        write_artifact(
            run_dir,
            "cells_with_activity",
            "cells.with_activity.json",
            json.dumps(cells, indent=2),
            created_at,
        )
    )
    manifest = {
        "schemaVersion": "thesis_analyst_run_manifest_v1",
        "createdAt": created_at,
        "ok": True,
        "preSubmitReview": None,
        "cellsPath": str(run_dir / "cells.with_activity.json"),
        "artifacts": refs,
        "validation": {"ok": True, "cells": []},
    }
    finalize_manifest(run_dir, created_at, manifest, refs)
    return run_dir


def test_custody_verifier_accepts_fixture_and_rejects_changed_scored_cells(
    synthetic_custody_run: pathlib.Path,
) -> None:
    verify_run(synthetic_custody_run)
    cells = synthetic_custody_run / "cells.with_activity.json"
    cells.write_text(cells.read_text().replace("1.5", "9.5"))

    with pytest.raises(CustodyError, match="raw SHA-256 mismatch"):
        verify_run(synthetic_custody_run)


def four_file_v2_run(tmp_path: pathlib.Path) -> pathlib.Path:
    run_dir = tmp_path / "four-file-run"
    created_at = "2026-01-01T00:00:00Z"
    refs = [
        write_artifact(run_dir, "prompt", "prompt.md", "prompt\n", created_at),
        write_artifact(
            run_dir,
            "command",
            "command.json",
            json.dumps({"backend": "external_command", "argv": ["agent"]}),
            created_at,
        ),
        write_artifact(
            run_dir,
            "normalized_cell",
            "normalized_cells.json",
            json.dumps([{"slug": "synthetic"}]),
            created_at,
        ),
        write_artifact(
            run_dir,
            "cells_with_activity",
            "cells.with_activity.json",
            json.dumps([{"slug": "synthetic"}]),
            created_at,
        ),
    ]
    manifest = {
        "schemaVersion": "thesis_analyst_run_manifest_v1",
        "createdAt": created_at,
        "ok": True,
        "preSubmitReview": None,
        "cellsPath": str(run_dir / "cells.with_activity.json"),
        "artifacts": refs,
        "validation": {"ok": True, "cells": []},
    }
    finalize_manifest(run_dir, created_at, manifest, refs)
    return run_dir


def test_new_inventory_rejects_synthetic_four_file_run(
    tmp_path: pathlib.Path,
) -> None:
    run_dir = four_file_v2_run(tmp_path)
    with pytest.raises(CustodyError, match="missing required inventory artifacts"):
        verify_run(run_dir)


def test_new_inventory_rejects_unreferenced_extra_file(
    synthetic_custody_run: pathlib.Path,
) -> None:
    (synthetic_custody_run / "debug.tmp").write_text("not rooted\n")
    with pytest.raises(CustodyError, match="unreferenced=.*debug.tmp"):
        verify_run(synthetic_custody_run)


def _refinalize_with_refs(run_dir: pathlib.Path, refs: list[dict]) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    manifest.pop("custodyRootSha256", None)
    manifest["artifacts"] = refs
    return finalize_manifest(run_dir, manifest["createdAt"], manifest, refs)


def test_new_inventory_rejects_manifest_artifact_hash_mismatch(
    synthetic_custody_run: pathlib.Path,
) -> None:
    manifest = json.loads((synthetic_custody_run / "manifest.json").read_text())
    refs = [
        dict(ref) for ref in manifest["artifacts"] if ref["artifactType"] != "manifest"
    ]
    refs[0]["sha256"] = "0" * 64
    _refinalize_with_refs(synthetic_custody_run, refs)
    with pytest.raises(CustodyError, match="manifest/custody integrity mismatch"):
        verify_run(synthetic_custody_run)


def test_new_inventory_requires_canonical_hash_for_json(
    synthetic_custody_run: pathlib.Path,
) -> None:
    root_path = synthetic_custody_run / "custody_root.json"
    root = json.loads(root_path.read_text())
    json_entry = next(
        entry for entry in root["artifacts"] if entry["path"].endswith(".json")
    )
    json_entry.pop("canonicalJsonSha256")
    root_path.write_text(json.dumps(root, indent=2) + "\n")
    manifest_path = synthetic_custody_run / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["custodyRootSha256"] = canonical_sha256(root)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(CustodyError, match="lacks canonical hash"):
        verify_run(synthetic_custody_run)


def test_new_inventory_rejects_orphan_review_artifact(
    synthetic_custody_run: pathlib.Path,
) -> None:
    manifest = json.loads((synthetic_custody_run / "manifest.json").read_text())
    refs = [
        dict(ref) for ref in manifest["artifacts"] if ref["artifactType"] != "manifest"
    ]
    refs.append(
        write_artifact(
            synthetic_custody_run,
            "review_prompt",
            "pre_submit_review_prompt.md",
            "orphan review\n",
            manifest["createdAt"],
        )
    )
    _refinalize_with_refs(synthetic_custody_run, refs)
    with pytest.raises(CustodyError, match="review prompt exists without"):
        verify_run(synthetic_custody_run)


def test_complete_but_failed_v2_run_is_not_headline_eligible(
    synthetic_custody_run: pathlib.Path,
) -> None:
    manifest = json.loads((synthetic_custody_run / "manifest.json").read_text())
    refs = [
        dict(ref) for ref in manifest["artifacts"] if ref["artifactType"] != "manifest"
    ]
    manifest["ok"] = False
    manifest["validation"] = {"ok": False, "cells": []}
    manifest.pop("custodyRootSha256", None)
    finalize_manifest(synthetic_custody_run, manifest["createdAt"], manifest, refs)
    result = verify_run(synthetic_custody_run)
    assert result.inventory_status == "complete"
    assert result.run_succeeded is False
    assert result.headline_eligible is False


def test_real_pre_cutover_custody_root_verifies_but_is_labeled_legacy() -> None:
    run_dir = (
        ROOT
        / "records/thesis-analyst/2026-07-09"
        / "2026-07-09t22-34-49z-us-dol-initial-claims-sa-week-2026-07-11"
    )
    result = verify_run(run_dir)
    assert result.custody_inventory_version == 1
    assert result.inventory_status == "legacy-incomplete"
    assert result.headline_eligible is False


def test_real_recorder_snapshot_is_labeled_legacy() -> None:
    result = verify_recorder_snapshot(
        ROOT / "records/2026-07-09/digest-29054049741-1.json"
    )
    assert result.run_mode == "recorder"
    assert result.inventory_status == "legacy-incomplete"


def test_writer_shaped_recorder_v2_inventory_verifies(
    tmp_path: pathlib.Path,
) -> None:
    records = tmp_path / "records"
    day_dir = records / "2030-01-01"
    run_id = "recorder-v2"
    body_dir = day_dir / f"bodies-{run_id}"

    def archive(relative: str, payload: object) -> dict:
        raw = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        compressed = gzip.compress(raw, mtime=0)
        path = body_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(compressed)
        return {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "archivePath": f"records/2030-01-01/bodies-{run_id}/{relative}",
            "archiveSha256": hashlib.sha256(compressed).hexdigest(),
            "archiveBytes": len(compressed),
            "contentEncoding": "gzip",
        }

    chunk = {
        "schemaVersion": "thesis_log_chunk_v1",
        "logSchemaVersion": "thesis_log_v3",
        "collection": "runs",
        "chunkIndex": 0,
        "count": 1,
        "rows": [{"run": "one"}],
    }
    chunk_hash = canonical_sha256(chunk)
    log_manifest = {
        "schemaVersion": "thesis_log_v3",
        "collections": {
            "runs": {
                "chunks": [
                    {
                        "index": 0,
                        "url": "/log/runs/0.json",
                        "count": 1,
                        "sha256": chunk_hash,
                    }
                ]
            }
        },
    }
    surfaces = {
        key: archive(relative, log_manifest if key == "log" else {})
        for key, relative in RECORDER_REQUIRED_SURFACES.items()
    }
    live = {
        key: archive(relative, {"forecastSlug": key})
        for key, relative in RECORDER_REQUIRED_LIVE.items()
    }
    snapshot = day_dir / f"digest-{run_id}.json"
    write_json(
        snapshot,
        {
            "schemaVersion": "thesis_record_snapshot_v2",
            "snapshotKind": "recorder_run",
            "custodyInventoryVersion": 2,
            "runMode": "recorder",
            "runId": run_id,
            "recordedAt": "2030-01-01T00:00:00Z",
            "trustBundleUpdates": [
                record_chain.CODE_PINNED_TRUST_BUNDLES[
                    "records/trust/tsa-anchors-v2.json"
                ]
            ],
            "surfaces": surfaces,
            "logChunks": {
                "runs:0": {
                    **archive("log/runs/0.json.gz", chunk),
                    "manifestSha256": chunk_hash,
                }
            },
            "liveForecasts": live,
        },
    )
    result = verify_recorder_snapshot(snapshot)
    assert result.run_mode == "recorder"
    assert result.inventory_status == "complete"
    assert result.headline_eligible is False

    payload = json.loads(snapshot.read_text())
    original = body_dir / "log/runs/0.json.gz"
    misplaced = body_dir / "junk/runs-0.json.gz"
    misplaced.parent.mkdir(parents=True)
    original.rename(misplaced)
    payload["logChunks"]["runs:0"][
        "archivePath"
    ] = f"records/2030-01-01/bodies-{run_id}/junk/runs-0.json.gz"
    write_json(snapshot, payload)
    with pytest.raises(CustodyError, match="archive path mismatch"):
        verify_recorder_snapshot(snapshot)


def run_openssl(*arguments: str) -> None:
    env = os.environ.copy()
    env["OPENSSL_CONF"] = "/dev/null"
    subprocess.run(
        ["openssl", *arguments],
        check=True,
        capture_output=True,
        env=env,
    )


def test_token_signed_by_rogue_self_signed_tsa_fails_pinned_verification(
    tmp_path: pathlib.Path,
) -> None:
    records = tmp_path / "records"
    shutil.copytree(ROOT / "records" / "trust", records / "trust")
    bootstrap = json.loads((ROOT / "records/CHAIN_GENESIS.json").read_text())[
        "tsaTrustBundle"
    ]
    write_json(
        records / "CHAIN_GENESIS.json",
        {
            "schemaVersion": "thesis_record_chain_genesis_v1",
            "tsaTrustBundle": bootstrap,
        },
    )
    snapshot = records / "2026-01-01" / "digest-rogue.json"
    write_json(
        snapshot,
        {
            "schemaVersion": "thesis_record_snapshot_v2",
            "snapshotKind": "recorder_run",
            "runId": "rogue",
            "recordedAt": "2026-01-01T00:00:00Z",
        },
    )
    key = tmp_path / "rogue.key"
    certificate = tmp_path / "rogue.crt"
    run_openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "30",
        "-subj",
        "/CN=Rogue Timestamp Authority",
        "-addext",
        "basicConstraints=critical,CA:FALSE",
        "-addext",
        "keyUsage=critical,digitalSignature,nonRepudiation",
        "-addext",
        "extendedKeyUsage=critical,timeStamping",
        "-keyout",
        str(key),
        "-out",
        str(certificate),
    )
    serial = tmp_path / "serial"
    serial.write_text("01\n")
    config = tmp_path / "tsa.cnf"
    config.write_text(
        "\n".join(
            [
                "[tsa]",
                "default_tsa = tsa_config",
                "[tsa_config]",
                f"serial = {serial}",
                f"signer_cert = {certificate}",
                f"signer_key = {key}",
                "signer_digest = sha256",
                "default_policy = 1.2.3.4.1",
                "other_policies = 1.2.3.4.1",
                "digests = sha256",
                "accuracy = secs:1",
                "clock_precision_digits = 0",
                "ordering = yes",
                "tsa_name = yes",
                "ess_cert_id_chain = no",
            ]
        )
        + "\n"
    )
    query = tmp_path / "request.tsq"
    token = snapshot.with_suffix(".tsr")
    run_openssl(
        "ts",
        "-query",
        "-config",
        "/dev/null",
        "-data",
        str(snapshot),
        "-sha256",
        "-cert",
        "-out",
        str(query),
    )
    run_openssl(
        "ts",
        "-reply",
        "-config",
        str(config),
        "-section",
        "tsa_config",
        "-queryfile",
        str(query),
        "-out",
        str(token),
    )
    write_json(
        snapshot.with_suffix(".witness.json"),
        {
            "schemaVersion": "thesis_rfc3161_witness_v1",
            "status": "available",
            "digestSha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            "tsa": "https://freetsa.org/tsr",
            "tsaAnchorId": "freetsa-root-2016",
            "trustBundleId": bootstrap["bundleId"],
            "trustBundlePath": bootstrap["path"],
            "trustBundleSha256": bootstrap["sha256"],
            "tokenPath": "records/2026-01-01/digest-rogue.tsr",
            "tokenSha256": hashlib.sha256(token.read_bytes()).hexdigest(),
        },
    )
    with pytest.raises(ChainError, match="OpenSSL command failed"):
        verify_witness(
            snapshot,
            records=records,
            now=datetime(2100, 1, 1, tzinfo=timezone.utc),
        )


@pytest.mark.live_records
def test_current_witnessed_timeline_does_not_backdate_unwitnessed_roots() -> None:
    timeline = extract_timeline(ROOT / "records")
    assert (ROOT / "records/witnessed-timeline.json").read_bytes() == (
        canonical_bytes(timeline) + b"\n"
    )
    # The site's publication-proof chronology tier (re-audit N1) joins
    # against a bundled copy of the custody-root rows; a stale bundle would
    # silently misclassify witnessed runs as unproven.
    assert (
        ROOT / "site/src/data/witnessed-timeline.generated.ts"
    ).read_bytes() == timeline_module.render_site_timeline_module(timeline)
    verification = verify_chain(ROOT / "records")
    available_digests = {
        f"records/{path.relative_to(ROOT / 'records').as_posix()}"
        for path, evidence in verification.witnesses.items()
        if evidence.status == "available"
    }
    for collection in (
        timeline["runs"],
        timeline["custodyRoots"],
        timeline["registrationSnapshots"],
    ):
        assert all(
            proof["witnessDigest"] in available_digests for proof in collection.values()
        )


def test_python_canonical_json_uses_true_utf16_key_order() -> None:
    value = {"\ue000": 3, "😀": 2, "\ud7ff": 1, "nested": {"z": -0.0, "a": 1e-7}}
    assert canonical_stringify(value) == (
        '{"nested":{"a":1e-7,"z":0},"\ud7ff":1,"😀":2,"\ue000":3}'
    )
