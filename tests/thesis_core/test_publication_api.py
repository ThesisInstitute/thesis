"""Real DB application boundaries and cryptographic manifest replay."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from thesis_core import publication, tsa
from thesis_core.api import create_app
from thesis_core.contracts import PublicationProof, record_artifact_hashes
from thesis_core.pilot import prepare_replay
from thesis_core.resolution import resolve_target
from thesis_core.service import evaluate_experiment
from thesis_core.worker import schedule_experiment, work_once

from .test_pilot import statcan_fixture
from .test_tsa import authorities, pinned_tsa, rotate_test_bundle  # noqa: F401


def completed_pilot(store):
    experiment = prepare_replay(store, fetch=statcan_fixture)
    schedule_experiment(store, experiment.id)
    result = work_once(store, kinds=("forecast",))
    assert result["run_id"], result
    return experiment, store.get(result["run_id"])


def test_manifest_closure_and_real_signed_receipt(core_store, pinned_tsa, monkeypatch):  # noqa: F811
    experiment, run = completed_pilot(core_store)
    manifest = publication.create_manifest(core_store, experiment.id, run_id=run.id)
    attempt = core_store.get(run.attempt_id)
    assert manifest.code_hash == attempt.code_hash
    for record in core_store.dependency_closure(run.id):
        assert record.id in manifest.artifacts
        assert set(record_artifact_hashes(record)) <= set(manifest.artifacts)
    monkeypatch.setattr(tsa, "post_timestamp_query", pinned_tsa.transport())
    proof = publication.publish_manifest(
        core_store, manifest.id, anchor_id=pinned_tsa.anchor_id
    )
    verified = publication.verify_proof(core_store, proof)
    assert verified is not None
    assert verified.interval is None  # omitted signed accuracy never becomes zero
    with core_store.connection() as connection:
        queued = connection.execute(
            "SELECT kind,subject_id FROM outbox WHERE idempotency_key=%s",
            (f"evaluate:{experiment.id}:publication_proof:{proof.id}",),
        ).fetchone()
    assert queued == {"kind": "evaluate", "subject_id": experiment.id}
    assert (
        core_store.publication_attempts(manifest.id)[0]["response_hash"]
        == proof.token_hash
    )
    # The proof artifact set explicitly includes the exact subject bytes.
    assert proof.subject_hash in record_artifact_hashes(proof)
    payload = proof.canonical_payload() | {"policy_oid": "0.0.0"}
    altered = PublicationProof.model_validate_json(publication.canonical_bytes(payload))
    core_store.put(altered)
    assert publication.verify_proof(core_store, altered) is None


def test_failed_timestamp_archives_request_and_error(core_store, monkeypatch):
    experiment, run = completed_pilot(core_store)
    manifest = publication.create_manifest(core_store, experiment.id, run_id=run.id)

    def unavailable(*_args):
        raise OSError("test endpoint unavailable")

    monkeypatch.setattr(tsa, "post_timestamp_query", unavailable)
    with pytest.raises(tsa.TsaError):
        publication.publish_manifest(core_store, manifest.id)
    attempts = core_store.publication_attempts(manifest.id)
    assert len(attempts) == 1
    assert core_store.artifacts.read_bytes(attempts[0]["request_hash"])
    assert core_store.artifacts.read_bytes(attempts[0]["error_hash"])
    assert attempts[0]["response_hash"] is None
    assert len(tuple(core_store.iter_records("forecast_run"))) == 1


def test_proof_replays_recorded_bundle_after_rotation(
    core_store,
    pinned_tsa,  # noqa: F811
    monkeypatch,
):
    experiment, run = completed_pilot(core_store)
    manifest = publication.create_manifest(core_store, experiment.id, run_id=run.id)
    monkeypatch.setattr(
        tsa, "post_timestamp_query", pinned_tsa.transport(accuracy="millisecs:500")
    )
    proof = publication.publish_manifest(
        core_store, manifest.id, anchor_id=pinned_tsa.anchor_id
    )
    original_bytes = proof.canonical_bytes()
    original = publication.verify_proof(core_store, proof)
    assert original is not None and original.interval is not None
    new_path = rotate_test_bundle(monkeypatch)
    assert publication.verify_proof(core_store, proof) == original
    assert core_store.get(proof.id).canonical_bytes() == original_bytes

    # Claiming an unpinned path or a different archived bundle hash cannot add trust.
    for changes in (
        {"trust_bundle_path": "records/trust/tsa-anchors-v999.json"},
        {
            "trust_bundle_hash": core_store.artifacts.put_bytes(
                tsa.read_trust_asset(new_path)
            )
        },
    ):
        altered = PublicationProof.model_validate(proof.model_dump() | changes)
        core_store.put(altered)
        assert publication.verify_proof(core_store, altered) is None

    packaged = tsa.TRUST_ASSET_DIR / proof.trust_bundle_path.rsplit("/", 1)[1]
    packaged.write_bytes(packaged.read_bytes() + b" ")
    assert publication.verify_proof(core_store, proof) is None


def test_api_replay_score_export_and_read_only(core_store):
    before = publication.database_now(core_store)
    experiment, run = completed_pilot(core_store)
    resolve_target(core_store, experiment.target_version_ids[0])
    evaluate_experiment(core_store, experiment.id)
    client = TestClient(create_app(core_store))
    assert client.get("/health").status_code == 200
    response = client.get("/experiments").json()
    assert response["items"][0]["id"] == experiment.id
    assert response["items"][0]["mode"] == "replay"
    assert response["items"][0]["effective_information_boundary"]
    assert client.get("/runs?limit=0").status_code == 422
    assert client.get("/runs?after=not-a-digest").status_code == 422
    assert client.post("/experiments", json={}).status_code == 405
    assert client.get("/pending").json()["items"] == []
    reward = client.get("/rewards").json()["items"][0]
    assert reward["eligibility"] == "replay"
    assert reward["reward"] is None
    assert (
        client.get("/rewards", params={"as_of": before.isoformat()}).json()["items"]
        == []
    )
    after = publication.database_now(core_store) + timedelta(seconds=1)
    assert (
        len(client.get("/rewards", params={"as_of": after.isoformat()}).json()["items"])
        == 1
    )
    leaderboard = client.get("/leaderboard").json()["items"][0]
    assert leaderboard["rank"] is None
    assert leaderboard["coverage"] == {"eligible": 0, "total": 1}
    assert client.get(
        f"/artifacts/{run.prompt_hash}"
    ).content == core_store.artifacts.read_bytes(run.prompt_hash)
    assert client.get("/records/" + "0" * 64).status_code == 404


def test_api_unconfigured_import_and_bounded_error(monkeypatch):
    monkeypatch.delenv("THESIS_CORE_DSN", raising=False)
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 503
    assert "core_unconfigured" in response.text
