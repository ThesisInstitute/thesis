"""Real-pin coverage for the tsa-anchors-v3 bundle and how it gets published.

The synthetic-authority replay of a signer rotation lives in
tests/test_tsa_trust_transitions.py. These tests use the committed pins, the
staged bundle bytes, and real DigiCert tokens from both responders.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys
from datetime import datetime, timezone
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_trust_bundles as publisher  # noqa: E402
import record_forecast_snapshot as recorder  # noqa: E402
import verify_record_chain as record_chain  # noqa: E402
from canonical_json import canonical_bytes, canonical_sha256  # noqa: E402
from verify_record_chain import ChainError, ChainVerification  # noqa: E402

V1_PATH = "records/trust/tsa-anchors-v1.json"
V2_PATH = "records/trust/tsa-anchors-v2.json"
V3_PATH = "records/trust/tsa-anchors-v3.json"
STAGED_V3 = ROOT / "scripts/staged_trust_bundles/tsa-anchors-v3.json"
FIXTURES = ROOT / "tests/fixtures/tsa_anchors_v3"
DIGICERT = "digicert-trusted-root-g4"
FREETSA = "freetsa-root-2016"
RESPONDER_2025_SPKI = "7abda95ed7301ac94bded350babc319903d0b4f16c4e7e39346dba5f9e992b72"
RESPONDER_2026 = {
    "certificateSha256": (
        "2da09da7f4131f9fe72db6c5e6e9c9656755af043f1ea742cc0d2120e141ebfc"
    ),
    "serial": "084FDC334F7E454EDBC30F8FF9921835",
    "spkiSha256": "753596b60a629061144cbd312017bbfb77510eac20b7eadc5fafb7cabe142fd5",
    "subject": (
        "CN=DigiCert SHA256 RSA4096 Timestamp Responder 2026 1,O=DigiCert\\, Inc.,C=US"
    ),
}
# The last recorder snapshot DigiCert's 2025 responder witnessed. Records are
# immutable, so the path is stable.
LAST_2025_RESPONDER_SNAPSHOT = "2026-09-03/digest-33786852779-1.json"


def _reference(path: str) -> dict[str, Any]:
    return record_chain.CODE_PINNED_TRUST_BUNDLES[path]


def _trust_only_records(tmp_path: pathlib.Path, *, with_v3: bool) -> pathlib.Path:
    """A records root holding the real trust directory and nothing else."""

    records = tmp_path / "records"
    shutil.copytree(ROOT / "records" / "trust", records / "trust")
    v3 = records / "trust" / "tsa-anchors-v3.json"
    if with_v3 and not v3.exists():
        shutil.copyfile(STAGED_V3, v3)
    if not with_v3:
        v3.unlink(missing_ok=True)
    return records


def _token_claim(
    records: pathlib.Path,
    snapshot: pathlib.Path,
    token: pathlib.Path,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "available",
        "tsa": "http://timestamp.digicert.com",
        "tsaAnchorId": DIGICERT,
        "trustBundleId": bundle["bundleId"],
        "trustBundlePath": bundle["path"],
        "trustBundleSha256": bundle["sha256"],
        "tokenPath": f"records/{token.relative_to(records).as_posix()}",
        "tokenSha256": hashlib.sha256(token.read_bytes()).hexdigest(),
    }


def _install(
    records: pathlib.Path, day: str, snapshot: pathlib.Path, token: pathlib.Path
) -> tuple[pathlib.Path, pathlib.Path]:
    (records / day).mkdir(parents=True)
    return (
        pathlib.Path(shutil.copyfile(snapshot, records / day / snapshot.name)),
        pathlib.Path(shutil.copyfile(token, records / day / token.name)),
    )


def test_staged_v3_bundle_matches_its_code_pin() -> None:
    reference = _reference(V3_PATH)
    raw = STAGED_V3.read_bytes()
    payload = json.loads(raw)
    assert reference == {
        "bundleId": "tsa-anchors-v3",
        "path": V3_PATH,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
        "canonicalJsonSha256": canonical_sha256(payload),
    }
    assert raw == canonical_bytes(payload) + b"\n"
    published = ROOT / V3_PATH
    if published.exists():
        assert published.read_bytes() == raw


def test_every_code_pinned_bundle_is_published_or_staged() -> None:
    staging = publisher.STAGING_DIR
    for logical, reference in record_chain.CODE_PINNED_TRUST_BUNDLES.items():
        name = pathlib.Path(logical).name
        candidates = [
            path for path in (ROOT / logical, staging / name) if path.is_file()
        ]
        assert candidates, f"{logical} is pinned but the recorder cannot publish it"
        for path in candidates:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == reference["sha256"]
    pinned_names = {
        pathlib.Path(logical).name for logical in record_chain.CODE_PINNED_TRUST_BUNDLES
    }
    staged_names = {path.name for path in staging.iterdir()}
    assert staged_names - {publisher.STAGING_README} <= pinned_names


def test_v3_differs_from_v2_only_in_the_digicert_responder() -> None:
    v2 = json.loads((ROOT / V2_PATH).read_text())
    v3 = json.loads(STAGED_V3.read_text())
    assert [anchor["id"] for anchor in v3["anchors"]] == [FREETSA, DIGICERT]
    assert v3["anchors"][0] == v2["anchors"][0]
    assert v3["anchors"][1]["allowedSigners"] == [RESPONDER_2026]
    assert RESPONDER_2025_SPKI in {
        signer["spkiSha256"] for signer in v2["anchors"][1]["allowedSigners"]
    }

    def without_signers(bundle: dict[str, Any]) -> dict[str, Any]:
        anchors = [
            {key: value for key, value in anchor.items() if key != "allowedSigners"}
            for anchor in bundle["anchors"]
        ]
        return {**bundle, "anchors": anchors, "bundleId": "same"}

    assert without_signers(v3) == without_signers(v2)

    code_v2 = record_chain.CODE_PINNED_TSA_IDENTITIES["tsa-anchors-v2"]
    code_v3 = record_chain.CODE_PINNED_TSA_IDENTITIES["tsa-anchors-v3"]
    assert code_v3[FREETSA] == code_v2[FREETSA]
    assert code_v3[DIGICERT]["rootSpkiSha256"] == code_v2[DIGICERT]["rootSpkiSha256"]
    assert code_v3[DIGICERT]["signerSpkiSha256"] == {RESPONDER_2026["spkiSha256"]}
    assert code_v2[DIGICERT]["signerSpkiSha256"] == {RESPONDER_2025_SPKI}


def test_code_pinned_v3_bundle_loads_and_selects_both_anchors(
    tmp_path: pathlib.Path,
) -> None:
    records = _trust_only_records(tmp_path, with_v3=True)
    _path, bundle = record_chain._load_trust_bundle(records, _reference(V3_PATH))
    for anchor in bundle["anchors"]:
        assert (
            record_chain._select_anchor(
                records,
                {"tsaAnchorId": anchor["id"], "tsa": anchor["endpoint"]},
                bundle,
            )
            == anchor
        )


def test_real_2026_responder_token_verifies_under_v3_and_not_under_v2(
    tmp_path: pathlib.Path,
) -> None:
    records = _trust_only_records(tmp_path, with_v3=True)
    snapshot, token = _install(
        records,
        "2026-09-19",
        FIXTURES / "digest-digicert-2026-responder.json",
        FIXTURES / "digest-digicert-2026-responder.digicert-trusted-root-g4.tsr",
    )
    now = datetime.now(timezone.utc)

    v3 = _reference(V3_PATH)
    evidence = record_chain.verify_timestamp_token(
        snapshot,
        _token_claim(records, snapshot, token, v3),
        v3,
        records=records,
        now=now,
    )
    assert evidence.trust_bundle_id == "tsa-anchors-v3"
    assert evidence.anchor_id == DIGICERT
    assert evidence.policy_oid == "2.16.840.1.114412.7.1"
    assert evidence.gen_time == "2026-09-19T18:36:13Z"
    assert evidence.tsa_subject == RESPONDER_2026["subject"]
    assert evidence.tsa_certificate_sha256 == RESPONDER_2026["certificateSha256"]
    assert evidence.tsa_spki_sha256 == RESPONDER_2026["spkiSha256"]

    # The symptom every marker has recorded since 2026-09-04.
    v2 = _reference(V2_PATH)
    with pytest.raises(ChainError, match="token signer is not pinned"):
        record_chain.verify_timestamp_token(
            snapshot,
            _token_claim(records, snapshot, token, v2),
            v2,
            records=records,
            now=now,
        )


def test_real_2025_responder_token_verifies_under_v2_and_not_under_v3(
    tmp_path: pathlib.Path,
) -> None:
    records = _trust_only_records(tmp_path, with_v3=True)
    source = ROOT / "records" / LAST_2025_RESPONDER_SNAPSHOT
    snapshot, token = _install(
        records,
        source.parent.name,
        source,
        source.with_name(f"{source.stem}.{DIGICERT}.tsr"),
    )
    now = datetime.now(timezone.utc)

    v2 = _reference(V2_PATH)
    evidence = record_chain.verify_timestamp_token(
        snapshot,
        _token_claim(records, snapshot, token, v2),
        v2,
        records=records,
        now=now,
    )
    assert evidence.tsa_spki_sha256 == RESPONDER_2025_SPKI

    # v3 retires that key: no witness made after v3 activates may carry it.
    v3 = _reference(V3_PATH)
    with pytest.raises(ChainError, match="token signer is not pinned"):
        record_chain.verify_timestamp_token(
            snapshot,
            _token_claim(records, snapshot, token, v3),
            v3,
            records=records,
            now=now,
        )


def test_publisher_writes_the_pinned_bytes_once(tmp_path: pathlib.Path) -> None:
    records = _trust_only_records(tmp_path, with_v3=False)
    before = {path.name: path.read_bytes() for path in (records / "trust").iterdir()}

    published = publisher.publish_trust_bundles(records)

    target = records / "trust" / "tsa-anchors-v3.json"
    assert published == [target.resolve()]
    assert target.read_bytes() == STAGED_V3.read_bytes()
    after = {path.name: path.read_bytes() for path in (records / "trust").iterdir()}
    assert {name: after[name] for name in before} == before
    assert set(after) - set(before) == {"tsa-anchors-v3.json"}
    assert publisher.publish_trust_bundles(records) == []


def test_publisher_refuses_staged_bytes_that_differ_from_the_pin(
    tmp_path: pathlib.Path,
) -> None:
    records = _trust_only_records(tmp_path, with_v3=False)
    staging = tmp_path / "staging"
    staging.mkdir()
    changed = json.loads(STAGED_V3.read_text())
    changed["anchors"][1]["endpoint"] = "http://timestamp.invalid"
    (staging / "tsa-anchors-v3.json").write_bytes(canonical_bytes(changed) + b"\n")

    with pytest.raises(ChainError, match="differs from its verifier code pin"):
        publisher.publish_trust_bundles(records, staging=staging)
    assert not (records / "trust" / "tsa-anchors-v3.json").exists()


def test_publisher_refuses_an_approved_bundle_that_is_not_staged(
    tmp_path: pathlib.Path,
) -> None:
    records = _trust_only_records(tmp_path, with_v3=False)
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(ChainError, match="neither published nor staged"):
        publisher.publish_trust_bundles(records, staging=staging)

    (staging / "tsa-anchors-v3.json").symlink_to(STAGED_V3)
    with pytest.raises(ChainError, match="neither published nor staged"):
        publisher.publish_trust_bundles(records, staging=staging)


def test_publisher_refuses_a_staged_file_that_code_does_not_pin(
    tmp_path: pathlib.Path,
) -> None:
    records = _trust_only_records(tmp_path, with_v3=False)
    staging = tmp_path / "staging"
    shutil.copytree(publisher.STAGING_DIR, staging)
    shutil.copyfile(STAGED_V3, staging / "tsa-anchors-v99.json")

    with pytest.raises(ChainError, match="not approved by verifier code"):
        publisher.publish_trust_bundles(records, staging=staging)
    assert not (records / "trust" / "tsa-anchors-v3.json").exists()


def test_publisher_never_rewrites_a_published_bundle(tmp_path: pathlib.Path) -> None:
    records = _trust_only_records(tmp_path, with_v3=False)
    target = records / "trust" / "tsa-anchors-v3.json"
    tampered = json.loads(STAGED_V3.read_text())
    tampered["anchors"][1]["allowedSigners"].append(
        json.loads((ROOT / V2_PATH).read_text())["anchors"][1]["allowedSigners"][0]
    )
    target.write_bytes(canonical_bytes(tampered) + b"\n")
    original = target.read_bytes()

    with pytest.raises(ChainError, match="commitment mismatch"):
        publisher.publish_trust_bundles(records)
    assert target.read_bytes() == original


def test_publisher_refuses_a_symlinked_bundle(tmp_path: pathlib.Path) -> None:
    records = _trust_only_records(tmp_path, with_v3=False)
    target = records / "trust" / "tsa-anchors-v3.json"
    target.symlink_to(STAGED_V3)
    with pytest.raises(ChainError, match="escapes records root"):
        publisher.publish_trust_bundles(records)

    # A link that stays inside the records root is refused as well.
    target.unlink()
    inside = records / "trust" / "copy-of-v3.json"
    shutil.copyfile(STAGED_V3, inside)
    target.symlink_to(inside)
    with pytest.raises(ChainError, match="missing or not regular"):
        publisher.publish_trust_bundles(records)
    assert target.is_symlink()


def test_publisher_leaves_nothing_behind_when_an_anchor_root_is_absent(
    tmp_path: pathlib.Path,
) -> None:
    records = _trust_only_records(tmp_path, with_v3=False)
    # v2 names the same root, so check the new bundle alone.
    (records / "trust" / "tsa-anchors-v2.json").unlink()
    (records / "trust" / "digicert-trusted-root-g4.pem").unlink()
    only_v3 = {V1_PATH: _reference(V1_PATH), V3_PATH: _reference(V3_PATH)}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(publisher, "CODE_PINNED_TRUST_BUNDLES", only_v3)
        with pytest.raises(ChainError, match="pinned TSA root is missing"):
            publisher.publish_trust_bundles(records)
    assert not (records / "trust" / "tsa-anchors-v3.json").exists()


def _verification(*active: str, pending: tuple[str, ...] = ()) -> ChainVerification:
    return ChainVerification(
        ordered=(),
        witnesses={},
        enumeration_cutover=None,
        active_trust_bundles={path: _reference(path) for path in active},
        pending_trust_bundle_updates=tuple(_reference(path) for path in pending),
    )


def test_recorder_introduces_v3_once_under_the_real_pins() -> None:
    payload: dict[str, Any] = {}
    recorder.add_trust_bundle_updates(payload, _verification(V1_PATH, V2_PATH))
    assert payload == {"trustBundleUpdates": [_reference(V3_PATH)]}

    for later in (
        _verification(V1_PATH, V2_PATH, pending=(V3_PATH,)),
        _verification(V1_PATH, V2_PATH, V3_PATH),
    ):
        payload = {}
        recorder.add_trust_bundle_updates(payload, later)
        assert payload == {}


def test_recorder_refuses_to_introduce_an_unpublished_bundle(
    tmp_path: pathlib.Path,
) -> None:
    records = _trust_only_records(tmp_path, with_v3=False)
    before_transition = _verification(V1_PATH, V2_PATH)
    with pytest.raises(SystemExit, match="publish_trust_bundles.py"):
        recorder.require_published_trust_bundles(records, before_transition)

    publisher.publish_trust_bundles(records)
    recorder.require_published_trust_bundles(records, before_transition)
    # Nothing to introduce once the chain has seen the bundle.
    recorder.require_published_trust_bundles(
        _trust_only_records(tmp_path / "later", with_v3=False),
        _verification(V1_PATH, V2_PATH, V3_PATH),
    )


def test_recorder_workflow_publishes_bundles_before_minting_the_snapshot() -> None:
    workflow = (ROOT / ".github/workflows/record-forecasts.yml").read_text()
    publish = "uv run --locked --extra custody python scripts/publish_trust_bundles.py"
    ordered = [
        publish,
        "scripts/record_forecast_snapshot.py",
        "scripts/witness_snapshot.py",
        "scripts/verify_record_chain.py records",
        "git add records/",
        "uses: ./.github/actions/attest-records-push",
    ]
    positions = [workflow.index(marker) for marker in ordered]
    assert positions == sorted(positions)
    assert workflow.count(publish) == 1
    # Unconditional: every recorder run publishes whatever code has approved.
    step = workflow[workflow.index("- name: Publish code-approved TSA trust bundles") :]
    step = step[: step.index("- name: Fetch and attest")]
    assert "if:" not in step
