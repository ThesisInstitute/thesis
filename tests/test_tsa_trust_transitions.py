from __future__ import annotations

import copy
import hashlib
import http.client
import json
import os
import pathlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import producer_signing_pins as producer_pins  # noqa: E402
import verify_record_chain as record_chain  # noqa: E402


@pytest.fixture(autouse=True)
def _dormant_producer_signing(monkeypatch: pytest.MonkeyPatch) -> None:
    """These fixtures build synthetic chains that never contain the real
    activation snapshot; they exercise enumeration/witness/integrity
    properties, so producer signing is explicitly dormant here. Armed-state
    coverage lives in tests/test_producer_signing.py."""

    monkeypatch.setattr(producer_pins, "PRODUCER_SPKI_SHA256", None)
    monkeypatch.setattr(producer_pins, "ACTIVATION_SNAPSHOT", None)
import witness_snapshot as witness_module  # noqa: E402
from canonical_json import canonical_bytes, canonical_sha256  # noqa: E402
from record_forecast_snapshot import add_trust_bundle_updates  # noqa: E402
from verify_record_chain import (  # noqa: E402
    ChainError,
    ChainVerification,
    verify_chain,
    verify_witness,
)
from witness_snapshot import witness_targets  # noqa: E402

FAR_FUTURE = datetime(2100, 1, 1, tzinfo=timezone.utc)
SHA256_OID = "2.16.840.1.101.3.4.2.1"


@dataclass(frozen=True)
class SyntheticAuthority:
    anchor_id: str
    endpoint: str
    policy_oid: str
    root_certificate: pathlib.Path
    signer_certificate: pathlib.Path
    signer_key: pathlib.Path
    tsa_config: pathlib.Path


@dataclass(frozen=True)
class TrustEnvironment:
    records: pathlib.Path
    authorities: dict[str, SyntheticAuthority]
    bundle_payloads: dict[str, dict[str, Any]]
    bundle_references: dict[str, dict[str, Any]]


def _write_json(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def _write_canonical_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_openssl(*arguments: str) -> None:
    environment = os.environ.copy()
    environment["OPENSSL_CONF"] = "/dev/null"
    completed = subprocess.run(
        ["openssl", *arguments],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(
            f"OpenSSL failed ({' '.join(arguments)}): {completed.stderr}"
        )


def _make_authority(
    directory: pathlib.Path,
    *,
    anchor_id: str,
    endpoint: str,
    policy_oid: str,
    certificate_serial: int,
) -> SyntheticAuthority:
    directory.mkdir(parents=True, exist_ok=True)
    root_key = directory / "root.key"
    root_certificate = directory / "root.pem"
    signer_key = directory / "signer.key"
    signer_request = directory / "signer.csr"
    signer_certificate = directory / "signer.pem"
    signer_extensions = directory / "signer-extensions.cnf"
    serial = directory / "tsa-serial"
    tsa_config = directory / "tsa.cnf"

    _run_openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-sha256",
        "-days",
        "3650",
        "-subj",
        f"/CN={anchor_id} Root",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
        "-keyout",
        str(root_key),
        "-out",
        str(root_certificate),
    )
    _run_openssl(
        "req",
        "-new",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-sha256",
        "-subj",
        f"/CN={anchor_id} Timestamp Signer",
        "-keyout",
        str(signer_key),
        "-out",
        str(signer_request),
    )
    signer_extensions.write_text(
        "\n".join(
            [
                "[tsa_signer]",
                "basicConstraints=critical,CA:FALSE",
                "keyUsage=critical,digitalSignature,nonRepudiation",
                "extendedKeyUsage=critical,timeStamping",
                "subjectKeyIdentifier=hash",
                "authorityKeyIdentifier=keyid,issuer",
            ]
        )
        + "\n"
    )
    _run_openssl(
        "x509",
        "-req",
        "-in",
        str(signer_request),
        "-CA",
        str(root_certificate),
        "-CAkey",
        str(root_key),
        "-set_serial",
        str(certificate_serial),
        "-days",
        "3650",
        "-sha256",
        "-extfile",
        str(signer_extensions),
        "-extensions",
        "tsa_signer",
        "-out",
        str(signer_certificate),
    )
    _run_openssl(
        "verify",
        "-CAfile",
        str(root_certificate),
        "-purpose",
        "timestampsign",
        str(signer_certificate),
    )
    serial.write_text("01\n")
    tsa_config.write_text(
        "\n".join(
            [
                "[tsa]",
                "default_tsa=tsa_config",
                "[tsa_config]",
                f"serial={serial}",
                f"signer_cert={signer_certificate}",
                f"signer_key={signer_key}",
                "signer_digest=sha256",
                f"default_policy={policy_oid}",
                f"other_policies={policy_oid}",
                "digests=sha256",
                "accuracy=secs:1",
                "clock_precision_digits=0",
                "ordering=yes",
                "tsa_name=yes",
                "ess_cert_id_chain=no",
            ]
        )
        + "\n"
    )
    return SyntheticAuthority(
        anchor_id=anchor_id,
        endpoint=endpoint,
        policy_oid=policy_oid,
        root_certificate=root_certificate,
        signer_certificate=signer_certificate,
        signer_key=signer_key,
        tsa_config=tsa_config,
    )


@pytest.fixture(scope="module")
def authority_material(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, SyntheticAuthority]:
    base = tmp_path_factory.mktemp("synthetic-tsas")
    return {
        "alpha": _make_authority(
            base / "alpha",
            anchor_id="synthetic-alpha",
            endpoint="https://alpha.invalid/tsa",
            policy_oid="1.2.3.4.1",
            certificate_serial=101,
        ),
        "beta": _make_authority(
            base / "beta",
            anchor_id="synthetic-beta",
            endpoint="https://beta.invalid/tsa",
            policy_oid="1.2.3.4.1",
            certificate_serial=102,
        ),
        "rogue": _make_authority(
            base / "rogue",
            anchor_id="synthetic-rogue",
            endpoint="https://rogue.invalid/tsa",
            policy_oid="1.2.3.4.1",
            certificate_serial=103,
        ),
    }


def _anchor_payload(
    records: pathlib.Path,
    authority: SyntheticAuthority,
) -> dict[str, Any]:
    root_path = records / "trust" / f"{authority.anchor_id}-root.pem"
    shutil.copyfile(authority.root_certificate, root_path)
    root_identity = record_chain._certificate_identity(root_path)
    signer_identity = record_chain._certificate_identity(authority.signer_certificate)
    return {
        "allowedImprintAlgorithmOids": [SHA256_OID],
        "allowedPolicyOids": [authority.policy_oid],
        "allowedSigners": [signer_identity],
        "endpoint": authority.endpoint,
        "id": authority.anchor_id,
        "maxFutureSeconds": 0,
        "maxTokenLeadSeconds": 300,
        "rootCertificate": {
            **root_identity,
            "path": f"records/trust/{root_path.name}",
            "pemSha256": _sha256(root_path),
        },
    }


def _bundle_reference(path: pathlib.Path, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "bundleId": payload["bundleId"],
        "path": f"records/trust/{path.name}",
        "sha256": _sha256(path),
        "size": path.stat().st_size,
        "canonicalJsonSha256": canonical_sha256(payload),
    }


@pytest.fixture
def trust_environment(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    authority_material: dict[str, SyntheticAuthority],
) -> TrustEnvironment:
    records = tmp_path / "records"
    (records / "trust").mkdir(parents=True)
    alpha = _anchor_payload(records, authority_material["alpha"])
    beta = _anchor_payload(records, authority_material["beta"])
    payloads = {
        "v1": {
            "anchors": [alpha],
            "bundleId": "tsa-anchors-v1",
            "schemaVersion": "thesis_tsa_trust_bundle_v1",
        },
        "v2": {
            "anchors": [alpha, beta],
            "bundleId": "tsa-anchors-v2",
            "schemaVersion": "thesis_tsa_trust_bundle_v1",
        },
    }
    references: dict[str, dict[str, Any]] = {}
    for version, payload in payloads.items():
        path = records / "trust" / f"tsa-anchors-{version}.json"
        _write_canonical_json(path, payload)
        references[version] = _bundle_reference(path, payload)

    code_identities: dict[str, dict[str, dict[str, Any]]] = {}
    for version, payload in payloads.items():
        code_identities[payload["bundleId"]] = {
            anchor["id"]: {
                "rootSpkiSha256": anchor["rootCertificate"]["spkiSha256"],
                "signerSpkiSha256": {
                    signer["spkiSha256"] for signer in anchor["allowedSigners"]
                },
            }
            for anchor in payload["anchors"]
        }
    monkeypatch.setattr(
        record_chain,
        "CODE_PINNED_TRUST_BUNDLES",
        {reference["path"]: reference for reference in references.values()},
    )
    monkeypatch.setattr(
        record_chain,
        "CODE_PINNED_TSA_IDENTITIES",
        code_identities,
    )
    return TrustEnvironment(
        records=records,
        authorities=authority_material,
        bundle_payloads=payloads,
        bundle_references=references,
    )


def _new_snapshot(
    environment: TrustEnvironment,
    name: str,
    *,
    previous: pathlib.Path | None = None,
    trust_updates: list[dict[str, Any]] | None = None,
) -> pathlib.Path:
    day = 1 if previous is None else int(previous.parent.name[-2:]) + 1
    snapshot = environment.records / f"2020-01-{day:02d}" / f"digest-{name}.json"
    payload: dict[str, Any] = {
        "schemaVersion": "thesis_record_snapshot_v2",
        "snapshotKind": "recorder_run",
        "runId": name,
        "recordedAt": f"2020-01-{day:02d}T00:00:00Z",
    }
    if previous is not None:
        payload["chain"] = {
            "prevDigestPath": (
                f"records/{previous.relative_to(environment.records).as_posix()}"
            ),
            "prevDigestSha256": _sha256(previous),
        }
    if trust_updates is not None:
        payload["trustBundleUpdates"] = trust_updates
    _write_json(snapshot, payload)
    return snapshot


def _make_token(
    authority: SyntheticAuthority,
    snapshot: pathlib.Path,
    token: pathlib.Path,
) -> None:
    query = token.with_suffix(".tsq")
    _run_openssl(
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
    _run_openssl(
        "ts",
        "-reply",
        "-config",
        str(authority.tsa_config),
        "-section",
        "tsa_config",
        "-queryfile",
        str(query),
        "-out",
        str(token),
    )


def _available_outcome(
    environment: TrustEnvironment,
    snapshot: pathlib.Path,
    claimed_authority: SyntheticAuthority,
    *,
    signing_authority: SyntheticAuthority | None = None,
    supplemental_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signer = signing_authority or claimed_authority
    token = snapshot.with_name(
        f"{snapshot.stem}.{claimed_authority.anchor_id}-by-{signer.anchor_id}.tsr"
    )
    _make_token(signer, snapshot, token)
    outcome: dict[str, Any] = {
        "status": "available",
        "tsa": claimed_authority.endpoint,
        "tsaAnchorId": claimed_authority.anchor_id,
        "tokenPath": f"records/{token.relative_to(environment.records).as_posix()}",
        "tokenSha256": _sha256(token),
    }
    if supplemental_bundle is not None:
        outcome.update(
            {
                "role": "pending_trust_bundle",
                "trustBundleId": supplemental_bundle["bundleId"],
                "trustBundlePath": supplemental_bundle["path"],
                "trustBundleSha256": supplemental_bundle["sha256"],
            }
        )
    return outcome


def _unavailable_outcome(
    authority: SyntheticAuthority,
    *,
    supplemental_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "status": "unavailable",
        "tsa": authority.endpoint,
        "tsaAnchorId": authority.anchor_id,
        "reason": "synthetic endpoint outage",
    }
    if supplemental_bundle is not None:
        outcome.update(
            {
                "role": "pending_trust_bundle",
                "trustBundleId": supplemental_bundle["bundleId"],
                "trustBundlePath": supplemental_bundle["path"],
                "trustBundleSha256": supplemental_bundle["sha256"],
            }
        )
    return outcome


def _write_v2_witness(
    snapshot: pathlib.Path,
    bundle: dict[str, Any],
    anchor_outcomes: list[dict[str, Any]],
    *,
    supplemental_outcomes: list[dict[str, Any]] | None = None,
) -> None:
    status = (
        "available"
        if any(outcome["status"] == "available" for outcome in anchor_outcomes)
        else "unavailable"
    )
    marker: dict[str, Any] = {
        "schemaVersion": "thesis_rfc3161_witness_v2",
        "status": status,
        "digestSha256": _sha256(snapshot),
        "trustBundleId": bundle["bundleId"],
        "trustBundlePath": bundle["path"],
        "trustBundleSha256": bundle["sha256"],
        "anchorOutcomes": anchor_outcomes,
        "supplementalOutcomes": supplemental_outcomes or [],
    }
    if status == "unavailable":
        marker["reason"] = "all synthetic TSA requests failed"
    _write_json(snapshot.with_suffix(".witness.json"), marker)


def _active_bundles(
    environment: TrustEnvironment, *versions: str
) -> dict[str, dict[str, Any]]:
    return {
        environment.bundle_references[version]["path"]: (
            environment.bundle_references[version]
        )
        for version in versions
    }


def _initialize_chain(environment: TrustEnvironment, first: pathlib.Path) -> None:
    _write_json(
        environment.records / "CHAIN_GENESIS.json",
        {
            "schemaVersion": "thesis_record_chain_genesis_v1",
            "firstSnapshot": (
                f"records/{first.relative_to(environment.records).as_posix()}"
            ),
            "legacyDigests": [],
            "tsaTrustBundle": environment.bundle_references["v1"],
        },
    )
    _set_chain_head(environment, first)


def _set_chain_head(environment: TrustEnvironment, snapshot: pathlib.Path) -> None:
    _write_json(
        environment.records / "CHAIN_HEAD.json",
        {
            "schemaVersion": "thesis_record_chain_head_v1",
            "snapshotPath": (
                f"records/{snapshot.relative_to(environment.records).as_posix()}"
            ),
            "snapshotSha256": _sha256(snapshot),
        },
    )


def test_multi_token_witness_accepts_two_valid_tokens(
    trust_environment: TrustEnvironment,
) -> None:
    environment = trust_environment
    snapshot = _new_snapshot(environment, "both-valid")
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    _write_v2_witness(
        snapshot,
        environment.bundle_references["v2"],
        [
            _available_outcome(environment, snapshot, alpha),
            _available_outcome(environment, snapshot, beta),
        ],
    )

    evidence = verify_witness(
        snapshot,
        records=environment.records,
        trusted_bundles=_active_bundles(environment, "v1", "v2"),
        now=FAR_FUTURE,
    )

    assert evidence.status == "available"
    assert {token.anchor_id for token in evidence.tokens} == {
        alpha.anchor_id,
        beta.anchor_id,
    }


def test_multi_token_witness_accepts_valid_plus_explicit_unavailable(
    trust_environment: TrustEnvironment,
) -> None:
    environment = trust_environment
    snapshot = _new_snapshot(environment, "degraded")
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    _write_v2_witness(
        snapshot,
        environment.bundle_references["v2"],
        [
            _available_outcome(environment, snapshot, alpha),
            _unavailable_outcome(beta),
        ],
    )

    evidence = verify_witness(
        snapshot,
        records=environment.records,
        trusted_bundles=_active_bundles(environment, "v1", "v2"),
        now=FAR_FUTURE,
    )

    assert evidence.status == "available"
    assert [token.anchor_id for token in evidence.tokens] == [alpha.anchor_id]


def test_multi_token_witness_rejects_rogue_as_only_listed_token(
    trust_environment: TrustEnvironment,
) -> None:
    environment = trust_environment
    snapshot = _new_snapshot(environment, "rogue-only")
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    rogue = environment.authorities["rogue"]
    _write_v2_witness(
        snapshot,
        environment.bundle_references["v2"],
        [
            _available_outcome(
                environment,
                snapshot,
                alpha,
                signing_authority=rogue,
            ),
            _unavailable_outcome(beta),
        ],
    )

    with pytest.raises(ChainError, match="OpenSSL command failed"):
        verify_witness(
            snapshot,
            records=environment.records,
            trusted_bundles=_active_bundles(environment, "v1", "v2"),
            now=FAR_FUTURE,
        )


def test_multi_token_witness_rejects_rogue_beside_genuine_token(
    trust_environment: TrustEnvironment,
) -> None:
    environment = trust_environment
    snapshot = _new_snapshot(environment, "genuine-and-rogue")
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    rogue = environment.authorities["rogue"]
    _write_v2_witness(
        snapshot,
        environment.bundle_references["v2"],
        [
            _available_outcome(environment, snapshot, alpha),
            _available_outcome(
                environment,
                snapshot,
                beta,
                signing_authority=rogue,
            ),
        ],
    )

    with pytest.raises(ChainError, match="OpenSSL command failed"):
        verify_witness(
            snapshot,
            records=environment.records,
            trusted_bundles=_active_bundles(environment, "v1", "v2"),
            now=FAR_FUTURE,
        )


def test_chain_rejects_v2_witness_before_old_bundle_transition(
    trust_environment: TrustEnvironment,
) -> None:
    environment = trust_environment
    transition = _new_snapshot(
        environment,
        "self-authorizing-v2",
        trust_updates=[environment.bundle_references["v2"]],
    )
    _initialize_chain(environment, transition)
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    _write_v2_witness(
        transition,
        environment.bundle_references["v2"],
        [
            _available_outcome(environment, transition, alpha),
            _available_outcome(environment, transition, beta),
        ],
    )

    with pytest.raises(ChainError, match="newest active TSA trust bundle"):
        verify_chain(
            environment.records,
            allow_pre_enumeration=True,
            now=FAR_FUTURE,
        )


def test_unavailable_transition_does_not_activate_v2(
    trust_environment: TrustEnvironment,
) -> None:
    environment = trust_environment
    v2 = environment.bundle_references["v2"]
    transition = _new_snapshot(
        environment,
        "unavailable-transition",
        trust_updates=[v2],
    )
    _initialize_chain(environment, transition)
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    _write_v2_witness(
        transition,
        environment.bundle_references["v1"],
        [_unavailable_outcome(alpha)],
        supplemental_outcomes=[_unavailable_outcome(beta, supplemental_bundle=v2)],
    )

    verification = verify_chain(
        environment.records,
        allow_pre_enumeration=True,
        now=FAR_FUTURE,
    )
    assert set(verification.active_trust_bundles) == {
        environment.bundle_references["v1"]["path"]
    }
    assert verification.pending_trust_bundle_updates == (v2,)

    successor = _new_snapshot(
        environment,
        "premature-v2",
        previous=transition,
    )
    _write_v2_witness(successor, v2, [])
    _set_chain_head(environment, successor)

    with pytest.raises(ChainError, match="newest active TSA trust bundle"):
        verify_chain(
            environment.records,
            allow_pre_enumeration=True,
            now=FAR_FUTURE,
        )


def test_available_old_bundle_transition_activates_v2(
    trust_environment: TrustEnvironment,
) -> None:
    environment = trust_environment
    v2 = environment.bundle_references["v2"]
    transition = _new_snapshot(
        environment,
        "available-transition",
        trust_updates=[v2],
    )
    _initialize_chain(environment, transition)
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    _write_v2_witness(
        transition,
        environment.bundle_references["v1"],
        [_available_outcome(environment, transition, alpha)],
        supplemental_outcomes=[
            _available_outcome(
                environment,
                transition,
                beta,
                supplemental_bundle=v2,
            )
        ],
    )

    transition_verification = verify_chain(
        environment.records,
        allow_pre_enumeration=True,
        now=FAR_FUTURE,
    )
    assert set(transition_verification.active_trust_bundles) == {
        environment.bundle_references["v1"]["path"],
        v2["path"],
    }
    assert transition_verification.pending_trust_bundle_updates == ()

    successor = _new_snapshot(
        environment,
        "v2-active",
        previous=transition,
    )
    _write_v2_witness(
        successor,
        v2,
        [
            _available_outcome(environment, successor, alpha),
            _available_outcome(environment, successor, beta),
        ],
    )
    _set_chain_head(environment, successor)

    verification = verify_chain(
        environment.records,
        allow_pre_enumeration=True,
        now=FAR_FUTURE,
    )
    assert len(verification.witnesses[successor].tokens) == 2


def test_transition_rejects_rogue_supplemental_beside_genuine_old_token(
    trust_environment: TrustEnvironment,
) -> None:
    environment = trust_environment
    v2 = environment.bundle_references["v2"]
    transition = _new_snapshot(
        environment,
        "rogue-supplemental",
        trust_updates=[v2],
    )
    _initialize_chain(environment, transition)
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    rogue = environment.authorities["rogue"]
    _write_v2_witness(
        transition,
        environment.bundle_references["v1"],
        [_available_outcome(environment, transition, alpha)],
        supplemental_outcomes=[
            _available_outcome(
                environment,
                transition,
                beta,
                signing_authority=rogue,
                supplemental_bundle=v2,
            )
        ],
    )

    with pytest.raises(ChainError, match="OpenSSL command failed"):
        verify_chain(
            environment.records,
            allow_pre_enumeration=True,
            now=FAR_FUTURE,
        )


def test_chain_rejects_v2_bundle_byte_and_pin_mismatch(
    trust_environment: TrustEnvironment,
) -> None:
    environment = trust_environment
    v2 = environment.bundle_references["v2"]
    transition = _new_snapshot(
        environment,
        "mismatched-v2",
        trust_updates=[v2],
    )
    _initialize_chain(environment, transition)
    changed = copy.deepcopy(environment.bundle_payloads["v2"])
    changed["anchors"][1]["endpoint"] = "https://changed.invalid/tsa"
    _write_canonical_json(
        environment.records / "trust" / "tsa-anchors-v2.json", changed
    )

    with pytest.raises(ChainError, match="commitment mismatch"):
        verify_chain(
            environment.records,
            allow_pre_enumeration=True,
            now=FAR_FUTURE,
        )


def test_transition_producer_emits_v2_once_then_stops(
    trust_environment: TrustEnvironment,
) -> None:
    environment = trust_environment
    v1 = environment.bundle_references["v1"]
    v2 = environment.bundle_references["v2"]

    before = ChainVerification(
        ordered=(),
        witnesses={},
        enumeration_cutover=None,
        active_trust_bundles={v1["path"]: v1},
        pending_trust_bundle_updates=(),
    )
    transition_payload: dict[str, Any] = {}
    add_trust_bundle_updates(transition_payload, before)
    assert transition_payload["trustBundleUpdates"] == [v2]

    pending = ChainVerification(
        ordered=(),
        witnesses={},
        enumeration_cutover=None,
        active_trust_bundles={v1["path"]: v1},
        pending_trust_bundle_updates=(v2,),
    )
    pending_payload: dict[str, Any] = {}
    add_trust_bundle_updates(pending_payload, pending)
    assert "trustBundleUpdates" not in pending_payload

    active = ChainVerification(
        ordered=(),
        witnesses={},
        enumeration_cutover=None,
        active_trust_bundles={v1["path"]: v1, v2["path"]: v2},
        pending_trust_bundle_updates=(),
    )
    active_payload: dict[str, Any] = {}
    add_trust_bundle_updates(active_payload, active)
    assert "trustBundleUpdates" not in active_payload


def test_witness_targets_use_old_bundle_for_transition_then_v2(
    trust_environment: TrustEnvironment,
) -> None:
    environment = trust_environment
    v1 = environment.bundle_references["v1"]
    v2 = environment.bundle_references["v2"]
    before = ChainVerification(
        ordered=(),
        witnesses={},
        enumeration_cutover=None,
        active_trust_bundles={v1["path"]: v1},
        pending_trust_bundle_updates=(),
    )

    evidence_bundle, targets, updates = witness_targets(
        environment.records,
        before,
        {"trustBundleUpdates": [v2]},
    )
    assert evidence_bundle == v1
    assert updates == [v2]
    assert [(target.anchor["id"], target.supplemental) for target in targets] == [
        (environment.authorities["alpha"].anchor_id, False),
        (environment.authorities["beta"].anchor_id, True),
    ]

    active = ChainVerification(
        ordered=(),
        witnesses={},
        enumeration_cutover=None,
        active_trust_bundles={v1["path"]: v1, v2["path"]: v2},
        pending_trust_bundle_updates=(),
    )
    evidence_bundle, targets, updates = witness_targets(
        environment.records,
        active,
        {},
    )
    assert evidence_bundle == v2
    assert updates == []
    assert [(target.anchor["id"], target.supplemental) for target in targets] == [
        (environment.authorities["alpha"].anchor_id, False),
        (environment.authorities["beta"].anchor_id, False),
    ]


def _patch_writer_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        witness_module,
        "verify_recorder_snapshot",
        lambda _snapshot: None,
    )

    def verify_synthetic_chain(
        records: pathlib.Path,
        **kwargs: Any,
    ) -> ChainVerification:
        return verify_chain(
            records,
            allow_pre_enumeration=True,
            now=FAR_FUTURE,
            **kwargs,
        )

    monkeypatch.setattr(witness_module, "verify_chain", verify_synthetic_chain)


def test_witness_writer_activates_transition_when_both_requests_succeed(
    trust_environment: TrustEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = trust_environment
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    v1 = environment.bundle_references["v1"]
    v2 = environment.bundle_references["v2"]

    first = _new_snapshot(environment, "v1-head")
    _initialize_chain(environment, first)
    _write_v2_witness(
        first,
        v1,
        [_available_outcome(environment, first, alpha)],
    )
    transition = _new_snapshot(
        environment,
        "writer-transition",
        previous=first,
        trust_updates=[v2],
    )
    _patch_writer_verification(monkeypatch)
    response_dir = environment.records.parent / "writer-responses"
    response_dir.mkdir()
    by_endpoint = {alpha.endpoint: alpha, beta.endpoint: beta}

    def requester(endpoint: str, query: bytes, _timeout: float) -> bytes:
        authority = by_endpoint[endpoint]
        query_path = response_dir / f"{authority.anchor_id}.tsq"
        response_path = response_dir / f"{authority.anchor_id}.tsr"
        query_path.write_bytes(query)
        _run_openssl(
            "ts",
            "-reply",
            "-config",
            str(authority.tsa_config),
            "-section",
            "tsa_config",
            "-queryfile",
            str(query_path),
            "-out",
            str(response_path),
        )
        return response_path.read_bytes()

    witness_path = witness_module.witness_snapshot(
        environment.records,
        transition,
        requester=requester,
        timeout_seconds=1,
    )

    marker = json.loads(witness_path.read_text())
    assert marker["status"] == "available"
    assert marker["trustBundlePath"] == v1["path"]
    assert [outcome["status"] for outcome in marker["anchorOutcomes"]] == ["available"]
    assert [outcome["status"] for outcome in marker["supplementalOutcomes"]] == [
        "available"
    ]
    assert marker["supplementalOutcomes"][0]["trustBundlePath"] == v2["path"]
    head = json.loads((environment.records / "CHAIN_HEAD.json").read_text())
    assert head["snapshotPath"] == (
        f"records/{transition.relative_to(environment.records).as_posix()}"
    )
    assert head["snapshotSha256"] == _sha256(transition)

    verification = verify_chain(
        environment.records,
        allow_pre_enumeration=True,
        now=FAR_FUTURE,
    )
    assert v2["path"] in verification.active_trust_bundles
    assert verification.witnesses[transition].status == "available"


def test_witness_writer_records_both_failures_and_preserves_valid_chain(
    trust_environment: TrustEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = trust_environment
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    v1 = environment.bundle_references["v1"]
    v2 = environment.bundle_references["v2"]

    transition = _new_snapshot(
        environment,
        "active-v2-head",
        trust_updates=[v2],
    )
    _initialize_chain(environment, transition)
    _write_v2_witness(
        transition,
        v1,
        [_available_outcome(environment, transition, alpha)],
        supplemental_outcomes=[
            _available_outcome(
                environment,
                transition,
                beta,
                supplemental_bundle=v2,
            )
        ],
    )
    pending = _new_snapshot(
        environment,
        "writer-both-unavailable",
        previous=transition,
    )
    _patch_writer_verification(monkeypatch)
    requested_endpoints: list[str] = []

    def requester(endpoint: str, _query: bytes, _timeout: float) -> bytes:
        requested_endpoints.append(endpoint)
        raise TimeoutError(f"synthetic timeout at {endpoint}")

    witness_path = witness_module.witness_snapshot(
        environment.records,
        pending,
        requester=requester,
        timeout_seconds=1,
    )

    marker = json.loads(witness_path.read_text())
    assert requested_endpoints == [alpha.endpoint, beta.endpoint]
    assert marker["status"] == "unavailable"
    assert marker["reason"] == (
        "all active-bundle TSA requests or verifications failed"
    )
    assert marker["trustBundlePath"] == v2["path"]
    assert marker["supplementalOutcomes"] == []
    assert [outcome["tsaAnchorId"] for outcome in marker["anchorOutcomes"]] == [
        alpha.anchor_id,
        beta.anchor_id,
    ]
    assert all(
        outcome["status"] == "unavailable"
        and outcome["reason"].startswith("timestamp request failed:")
        for outcome in marker["anchorOutcomes"]
    )
    assert not list(pending.parent.glob(f"{pending.stem}.*.tsr"))
    head = json.loads((environment.records / "CHAIN_HEAD.json").read_text())
    assert head["snapshotPath"] == (
        f"records/{pending.relative_to(environment.records).as_posix()}"
    )
    assert head["snapshotSha256"] == _sha256(pending)

    verification = verify_chain(
        environment.records,
        allow_pre_enumeration=True,
        now=FAR_FUTURE,
    )
    assert verification.ordered[-1] == pending
    assert verification.witnesses[pending].status == "unavailable"
    assert v2["path"] in verification.active_trust_bundles


def test_witness_writer_continues_after_one_read_error(
    trust_environment: TrustEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = trust_environment
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    v1 = environment.bundle_references["v1"]
    v2 = environment.bundle_references["v2"]

    transition = _new_snapshot(
        environment,
        "read-error-v2-head",
        trust_updates=[v2],
    )
    _initialize_chain(environment, transition)
    _write_v2_witness(
        transition,
        v1,
        [_available_outcome(environment, transition, alpha)],
        supplemental_outcomes=[
            _available_outcome(
                environment,
                transition,
                beta,
                supplemental_bundle=v2,
            )
        ],
    )
    pending = _new_snapshot(environment, "writer-read-error", previous=transition)
    _patch_writer_verification(monkeypatch)
    response_dir = environment.records.parent / "read-error-responses"
    response_dir.mkdir()

    def requester(endpoint: str, query: bytes, _timeout: float) -> bytes:
        if endpoint == alpha.endpoint:
            raise http.client.IncompleteRead(b"partial", 100)
        query_path = response_dir / "beta.tsq"
        response_path = response_dir / "beta.tsr"
        query_path.write_bytes(query)
        _run_openssl(
            "ts",
            "-reply",
            "-config",
            str(beta.tsa_config),
            "-section",
            "tsa_config",
            "-queryfile",
            str(query_path),
            "-out",
            str(response_path),
        )
        return response_path.read_bytes()

    witness_path = witness_module.witness_snapshot(
        environment.records,
        pending,
        requester=requester,
        timeout_seconds=1,
    )

    marker = json.loads(witness_path.read_text())
    assert marker["status"] == "available"
    assert [outcome["status"] for outcome in marker["anchorOutcomes"]] == [
        "unavailable",
        "available",
    ]
    assert marker["anchorOutcomes"][0]["reason"].startswith("timestamp request failed:")
    verification = verify_chain(
        environment.records,
        allow_pre_enumeration=True,
        now=FAR_FUTURE,
    )
    assert [token.anchor_id for token in verification.witnesses[pending].tokens] == [
        beta.anchor_id
    ]


# --- Signer rotation: same anchor, same root, new responder key --------------
#
# v1 -> v2 above adds an authority. The cases below replay the other kind of
# transition, the one tsa-anchors-v3 makes: an authority already in the active
# bundle replaces its responder certificate, and the next bundle re-pins that
# anchor. Real-pin coverage of v3 itself lives in tests/test_tsa_anchors_v3.py.


def _rotated_authority(
    authority: SyntheticAuthority,
    directory: pathlib.Path,
    *,
    certificate_serial: int,
) -> SyntheticAuthority:
    """The same root, endpoint and policy with a new responder certificate."""

    directory.mkdir(parents=True, exist_ok=True)
    root_key = authority.root_certificate.parent / "root.key"
    signer_key = directory / "signer.key"
    signer_request = directory / "signer.csr"
    signer_certificate = directory / "signer.pem"
    signer_extensions = directory / "signer-extensions.cnf"
    serial = directory / "tsa-serial"
    tsa_config = directory / "tsa.cnf"
    _run_openssl(
        "req",
        "-new",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-sha256",
        "-subj",
        f"/CN={authority.anchor_id} Timestamp Signer {certificate_serial}",
        "-keyout",
        str(signer_key),
        "-out",
        str(signer_request),
    )
    signer_extensions.write_text(
        "\n".join(
            [
                "[tsa_signer]",
                "basicConstraints=critical,CA:FALSE",
                "keyUsage=critical,digitalSignature,nonRepudiation",
                "extendedKeyUsage=critical,timeStamping",
                "subjectKeyIdentifier=hash",
                "authorityKeyIdentifier=keyid,issuer",
            ]
        )
        + "\n"
    )
    _run_openssl(
        "x509",
        "-req",
        "-in",
        str(signer_request),
        "-CA",
        str(authority.root_certificate),
        "-CAkey",
        str(root_key),
        "-set_serial",
        str(certificate_serial),
        "-days",
        "3650",
        "-sha256",
        "-extfile",
        str(signer_extensions),
        "-extensions",
        "tsa_signer",
        "-out",
        str(signer_certificate),
    )
    serial.write_text("01\n")
    tsa_config.write_text(
        "\n".join(
            [
                "[tsa]",
                "default_tsa=tsa_config",
                "[tsa_config]",
                f"serial={serial}",
                f"signer_cert={signer_certificate}",
                f"signer_key={signer_key}",
                "signer_digest=sha256",
                f"default_policy={authority.policy_oid}",
                f"other_policies={authority.policy_oid}",
                "digests=sha256",
                "accuracy=secs:1",
                "clock_precision_digits=0",
                "ordering=yes",
                "tsa_name=yes",
                "ess_cert_id_chain=no",
            ]
        )
        + "\n"
    )
    return SyntheticAuthority(
        anchor_id=authority.anchor_id,
        endpoint=authority.endpoint,
        policy_oid=authority.policy_oid,
        root_certificate=authority.root_certificate,
        signer_certificate=signer_certificate,
        signer_key=signer_key,
        tsa_config=tsa_config,
    )


@pytest.fixture(scope="module")
def rotated_beta(
    tmp_path_factory: pytest.TempPathFactory,
    authority_material: dict[str, SyntheticAuthority],
) -> SyntheticAuthority:
    return _rotated_authority(
        authority_material["beta"],
        tmp_path_factory.mktemp("synthetic-beta-rotated"),
        certificate_serial=202,
    )


@pytest.fixture
def rotation_environment(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    authority_material: dict[str, SyntheticAuthority],
    rotated_beta: SyntheticAuthority,
) -> TrustEnvironment:
    """v1 = alpha; v2 = alpha + beta; v3 = alpha + beta's new responder only."""

    records = tmp_path / "records"
    (records / "trust").mkdir(parents=True)
    alpha = _anchor_payload(records, authority_material["alpha"])
    beta = _anchor_payload(records, authority_material["beta"])
    beta_rotated = _anchor_payload(records, rotated_beta)
    assert {key: value for key, value in beta.items() if key != "allowedSigners"} == {
        key: value for key, value in beta_rotated.items() if key != "allowedSigners"
    }
    assert beta["allowedSigners"] != beta_rotated["allowedSigners"]
    payloads = {
        version: {
            "anchors": anchors,
            "bundleId": f"tsa-anchors-{version}",
            "schemaVersion": "thesis_tsa_trust_bundle_v1",
        }
        for version, anchors in {
            "v1": [alpha],
            "v2": [alpha, beta],
            "v3": [alpha, beta_rotated],
        }.items()
    }
    references: dict[str, dict[str, Any]] = {}
    for version, payload in payloads.items():
        path = records / "trust" / f"tsa-anchors-{version}.json"
        _write_canonical_json(path, payload)
        references[version] = _bundle_reference(path, payload)
    monkeypatch.setattr(
        record_chain,
        "CODE_PINNED_TRUST_BUNDLES",
        {reference["path"]: reference for reference in references.values()},
    )
    monkeypatch.setattr(
        record_chain,
        "CODE_PINNED_TSA_IDENTITIES",
        {
            payload["bundleId"]: {
                anchor["id"]: {
                    "rootSpkiSha256": anchor["rootCertificate"]["spkiSha256"],
                    "signerSpkiSha256": {
                        signer["spkiSha256"] for signer in anchor["allowedSigners"]
                    },
                }
                for anchor in payload["anchors"]
            }
            for payload in payloads.values()
        },
    )
    return TrustEnvironment(
        records=records,
        authorities={**authority_material, "beta_rotated": rotated_beta},
        bundle_payloads=payloads,
        bundle_references=references,
    )


def _signer_spki(authority: SyntheticAuthority) -> str:
    return record_chain._certificate_identity(authority.signer_certificate)[
        "spkiSha256"
    ]


def _refused_outcome(authority: SyntheticAuthority) -> dict[str, Any]:
    return {
        **_unavailable_outcome(authority),
        "reason": "pinned timestamp verification failed: RFC 3161 token signer "
        "is not pinned for TSA anchor",
    }


def _chain_through_rotation(environment: TrustEnvironment) -> pathlib.Path:
    """v2 active, one snapshot both responders witnessed, then the rotation.

    Returns the head: a v2-era snapshot that only alpha witnessed, because
    beta's endpoint now answers with a responder v2 does not pin.
    """

    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    v1 = environment.bundle_references["v1"]
    v2 = environment.bundle_references["v2"]
    introduce_v2 = _new_snapshot(environment, "introduce-v2", trust_updates=[v2])
    _initialize_chain(environment, introduce_v2)
    _write_v2_witness(
        introduce_v2,
        v1,
        [_available_outcome(environment, introduce_v2, alpha)],
        supplemental_outcomes=[
            _available_outcome(environment, introduce_v2, beta, supplemental_bundle=v2)
        ],
    )
    before = _new_snapshot(environment, "before-rotation", previous=introduce_v2)
    _write_v2_witness(
        before,
        v2,
        [
            _available_outcome(environment, before, alpha),
            _available_outcome(environment, before, beta),
        ],
    )
    after = _new_snapshot(environment, "after-rotation", previous=before)
    _write_v2_witness(
        after,
        v2,
        [_available_outcome(environment, after, alpha), _refused_outcome(beta)],
    )
    _set_chain_head(environment, after)
    return after


def _introduce_v3(
    environment: TrustEnvironment, previous: pathlib.Path
) -> pathlib.Path:
    return _new_snapshot(
        environment,
        "introduce-v3",
        previous=previous,
        trust_updates=[environment.bundle_references["v3"]],
    )


def _verify_synthetic(environment: TrustEnvironment) -> ChainVerification:
    return verify_chain(environment.records, allow_pre_enumeration=True, now=FAR_FUTURE)


def test_signer_rotation_replays_from_the_old_responder_to_the_new(
    rotation_environment: TrustEnvironment,
) -> None:
    environment = rotation_environment
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    rotated = environment.authorities["beta_rotated"]
    v2 = environment.bundle_references["v2"]
    v3 = environment.bundle_references["v3"]

    head = _chain_through_rotation(environment)
    transition = _introduce_v3(environment, head)
    _write_v2_witness(
        transition,
        v2,
        [_available_outcome(environment, transition, alpha), _refused_outcome(beta)],
    )
    successor = _new_snapshot(environment, "v3-active", previous=transition)
    _write_v2_witness(
        successor,
        v3,
        [
            _available_outcome(environment, successor, alpha),
            _available_outcome(environment, successor, beta, signing_authority=rotated),
        ],
    )
    _set_chain_head(environment, successor)

    verification = _verify_synthetic(environment)

    assert set(verification.active_trust_bundles) == {
        reference["path"] for reference in environment.bundle_references.values()
    }
    assert verification.pending_trust_bundle_updates == ()
    by_name = {path.name: evidence for path, evidence in verification.witnesses.items()}
    # Tokens from the retired responder keep verifying under the bundle their
    # marker names.
    before = by_name["digest-before-rotation.json"]
    assert {token.trust_bundle_id for token in before.tokens} == {"tsa-anchors-v2"}
    assert _signer_spki(beta) in {token.tsa_spki_sha256 for token in before.tokens}
    # One old-bundle token is what authorizes v3; a re-pinned anchor has no
    # supplemental lane.
    introduced = by_name["digest-introduce-v3.json"]
    assert [token.anchor_id for token in introduced.tokens] == [alpha.anchor_id]
    assert introduced.supplemental_tokens == ()
    after = by_name["digest-v3-active.json"]
    assert {token.trust_bundle_id for token in after.tokens} == {"tsa-anchors-v3"}
    assert {token.tsa_spki_sha256 for token in after.tokens} == {
        _signer_spki(alpha),
        _signer_spki(rotated),
    }


def test_new_responder_token_is_refused_under_the_old_bundle(
    rotation_environment: TrustEnvironment,
) -> None:
    environment = rotation_environment
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    rotated = environment.authorities["beta_rotated"]
    head = _chain_through_rotation(environment)
    claimed = _new_snapshot(environment, "claims-new-responder", previous=head)
    _write_v2_witness(
        claimed,
        environment.bundle_references["v2"],
        [
            _available_outcome(environment, claimed, alpha),
            _available_outcome(environment, claimed, beta, signing_authority=rotated),
        ],
    )
    _set_chain_head(environment, claimed)

    with pytest.raises(ChainError, match="token signer is not pinned"):
        _verify_synthetic(environment)


def _chain_with_v3_active(environment: TrustEnvironment) -> pathlib.Path:
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    head = _chain_through_rotation(environment)
    transition = _introduce_v3(environment, head)
    _write_v2_witness(
        transition,
        environment.bundle_references["v2"],
        [_available_outcome(environment, transition, alpha), _refused_outcome(beta)],
    )
    _set_chain_head(environment, transition)
    assert environment.bundle_references["v3"]["path"] in (
        _verify_synthetic(environment).active_trust_bundles
    )
    return transition


def test_retired_responder_token_is_refused_once_v3_is_active(
    rotation_environment: TrustEnvironment,
) -> None:
    environment = rotation_environment
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    transition = _chain_with_v3_active(environment)
    successor = _new_snapshot(environment, "retired-key", previous=transition)
    _write_v2_witness(
        successor,
        environment.bundle_references["v3"],
        [
            _available_outcome(environment, successor, alpha),
            _available_outcome(environment, successor, beta),
        ],
    )
    _set_chain_head(environment, successor)

    with pytest.raises(ChainError, match="token signer is not pinned"):
        _verify_synthetic(environment)


def test_witness_cannot_fall_back_to_v2_once_v3_is_active(
    rotation_environment: TrustEnvironment,
) -> None:
    environment = rotation_environment
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    transition = _chain_with_v3_active(environment)
    successor = _new_snapshot(environment, "downgrade", previous=transition)
    _write_v2_witness(
        successor,
        environment.bundle_references["v2"],
        [
            _available_outcome(environment, successor, alpha),
            _available_outcome(environment, successor, beta),
        ],
    )
    _set_chain_head(environment, successor)

    with pytest.raises(ChainError, match="newest active TSA trust bundle"):
        _verify_synthetic(environment)


def test_rotation_transition_cannot_be_witnessed_under_its_own_bundle(
    rotation_environment: TrustEnvironment,
) -> None:
    environment = rotation_environment
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    rotated = environment.authorities["beta_rotated"]
    head = _chain_through_rotation(environment)
    transition = _introduce_v3(environment, head)
    _write_v2_witness(
        transition,
        environment.bundle_references["v3"],
        [
            _available_outcome(environment, transition, alpha),
            _available_outcome(
                environment, transition, beta, signing_authority=rotated
            ),
        ],
    )
    _set_chain_head(environment, transition)

    with pytest.raises(ChainError, match="newest active TSA trust bundle"):
        _verify_synthetic(environment)


def test_rotation_transition_has_no_supplemental_lane(
    rotation_environment: TrustEnvironment,
) -> None:
    environment = rotation_environment
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    rotated = environment.authorities["beta_rotated"]
    v1 = environment.bundle_references["v1"]
    v2 = environment.bundle_references["v2"]
    v3 = environment.bundle_references["v3"]

    # The writer asks only the active bundle's anchors: both v3 anchor IDs are
    # already active, so nothing is requested on the pending bundle's behalf.
    evidence_bundle, targets, updates = witness_targets(
        environment.records,
        ChainVerification(
            ordered=(),
            witnesses={},
            enumeration_cutover=None,
            active_trust_bundles={v1["path"]: v1, v2["path"]: v2},
            pending_trust_bundle_updates=(),
        ),
        {"trustBundleUpdates": [v3]},
    )
    assert evidence_bundle == v2
    assert updates == [v3]
    assert [
        (target.anchor["id"], target.bundle_reference["bundleId"], target.supplemental)
        for target in targets
    ] == [
        (alpha.anchor_id, "tsa-anchors-v2", False),
        (beta.anchor_id, "tsa-anchors-v2", False),
    ]

    # And the verifier refuses a marker that claims one anyway.
    head = _chain_through_rotation(environment)
    transition = _introduce_v3(environment, head)
    _write_v2_witness(
        transition,
        v2,
        [_available_outcome(environment, transition, alpha), _refused_outcome(beta)],
        supplemental_outcomes=[
            _available_outcome(
                environment,
                transition,
                beta,
                signing_authority=rotated,
                supplemental_bundle=v3,
            )
        ],
    )
    _set_chain_head(environment, transition)
    with pytest.raises(ChainError, match="not introduced by a pending"):
        _verify_synthetic(environment)


def test_unwitnessed_rotation_transition_keeps_v3_pending(
    rotation_environment: TrustEnvironment,
) -> None:
    environment = rotation_environment
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    rotated = environment.authorities["beta_rotated"]
    v2 = environment.bundle_references["v2"]
    v3 = environment.bundle_references["v3"]
    head = _chain_through_rotation(environment)
    transition = _introduce_v3(environment, head)
    _write_v2_witness(
        transition, v2, [_unavailable_outcome(alpha), _refused_outcome(beta)]
    )
    _set_chain_head(environment, transition)

    pending = _verify_synthetic(environment)
    assert v3["path"] not in pending.active_trust_bundles
    assert pending.pending_trust_bundle_updates == (v3,)
    # The recorder does not name the bundle a second time.
    payload: dict[str, Any] = {}
    add_trust_bundle_updates(payload, pending)
    assert payload == {}

    # A snapshot cannot use v3 while it is pending...
    premature = _new_snapshot(environment, "premature-v3", previous=transition)
    _write_v2_witness(
        premature,
        v3,
        [
            _available_outcome(environment, premature, alpha),
            _available_outcome(environment, premature, beta, signing_authority=rotated),
        ],
    )
    _set_chain_head(environment, premature)
    with pytest.raises(ChainError, match="newest active TSA trust bundle"):
        _verify_synthetic(environment)

    # ...and the next old-bundle witness is what activates it.
    premature.with_suffix(".witness.json").unlink()
    _write_v2_witness(
        premature,
        v2,
        [_available_outcome(environment, premature, alpha), _refused_outcome(beta)],
    )
    activated = _verify_synthetic(environment)
    assert v3["path"] in activated.active_trust_bundles
    assert activated.pending_trust_bundle_updates == ()


def test_witness_writer_carries_a_signer_rotation_through_v3(
    rotation_environment: TrustEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = rotation_environment
    alpha = environment.authorities["alpha"]
    beta = environment.authorities["beta"]
    rotated = environment.authorities["beta_rotated"]
    v2 = environment.bundle_references["v2"]
    v3 = environment.bundle_references["v3"]
    head = _chain_through_rotation(environment)
    transition = _introduce_v3(environment, head)
    _patch_writer_verification(monkeypatch)
    response_dir = environment.records.parent / "writer-responses"
    response_dir.mkdir()
    # beta's endpoint now answers with the new responder, as DigiCert's does.
    by_endpoint = {alpha.endpoint: alpha, beta.endpoint: rotated}
    calls: list[str] = []

    def requester(endpoint: str, query: bytes, _timeout: float) -> bytes:
        authority = by_endpoint[endpoint]
        calls.append(endpoint)
        query_path = response_dir / f"{len(calls)}.tsq"
        response_path = response_dir / f"{len(calls)}.tsr"
        query_path.write_bytes(query)
        _run_openssl(
            "ts",
            "-reply",
            "-config",
            str(authority.tsa_config),
            "-section",
            "tsa_config",
            "-queryfile",
            str(query_path),
            "-out",
            str(response_path),
        )
        return response_path.read_bytes()

    marker = json.loads(
        witness_module.witness_snapshot(
            environment.records, transition, requester=requester, timeout_seconds=1
        ).read_text()
    )
    assert marker["status"] == "available"
    assert marker["trustBundlePath"] == v2["path"]
    assert [outcome["status"] for outcome in marker["anchorOutcomes"]] == [
        "available",
        "unavailable",
    ]
    assert "token signer is not pinned" in marker["anchorOutcomes"][1]["reason"]
    assert marker["supplementalOutcomes"] == []
    assert calls == [alpha.endpoint, beta.endpoint]
    # The refused token is not left beside the snapshot.
    assert sorted(path.name for path in transition.parent.glob("*.tsr")) == [
        f"{transition.stem}.{alpha.anchor_id}.tsr"
    ]
    assert v3["path"] in _verify_synthetic(environment).active_trust_bundles

    successor = _new_snapshot(environment, "v3-active", previous=transition)
    marker = json.loads(
        witness_module.witness_snapshot(
            environment.records, successor, requester=requester, timeout_seconds=1
        ).read_text()
    )
    assert marker["status"] == "available"
    assert marker["trustBundlePath"] == v3["path"]
    assert [outcome["status"] for outcome in marker["anchorOutcomes"]] == [
        "available",
        "available",
    ]
    assert marker["anchorOutcomes"][1]["tsaSignerSpkiSha256"] == _signer_spki(rotated)
    assert marker["supplementalOutcomes"] == []
    verification = _verify_synthetic(environment)
    assert len(verification.witnesses[successor].tokens) == 2
