from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient

from thesis_core import api, cli
from thesis_core.artifacts import ArtifactCorrupt, ArtifactError, ArtifactMissing
from thesis_core.store import IdentityConflict, RecordMissing, StoreError


@pytest.mark.parametrize(
    "error,status,code",
    [
        (StoreError("secret DB configuration"), 503, "store_unavailable"),
        (
            psycopg.OperationalError("secret connection string"),
            503,
            "store_unavailable",
        ),
        (ArtifactError("secret local path"), 503, "store_unavailable"),
        (ArtifactCorrupt("secret source bytes"), 409, "scientific_integrity_failure"),
        (
            IdentityConflict("secret record payload"),
            409,
            "scientific_integrity_failure",
        ),
        (ArtifactMissing("secret local path"), 404, "artifact_not_found"),
        (RecordMissing("secret identity"), 404, "record_not_found"),
    ],
)
def test_every_api_collection_bounds_backend_failures(error, status, code):
    def unavailable(*args, **kwargs):
        raise error

    store = SimpleNamespace(list=unavailable)
    response = TestClient(api.create_app(store)).get("/experiments")
    assert response.status_code == status
    assert response.json() == {"error": {"code": code}}
    assert "secret" not in response.text


def test_configured_api_respects_schema_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "THESIS_CORE_DSN", "postgresql://thesis_core@localhost/thesis_core"
    )
    monkeypatch.setenv("THESIS_CORE_SCHEMA", "separate_pilot")
    monkeypatch.setenv("THESIS_CORE_ARTIFACTS", str(tmp_path / "cas"))
    assert api.configured_store().schema == "separate_pilot"


@pytest.mark.parametrize("argv", ['"python"', '{"python":"driver.py"}', "[]", "[1]"])
def test_cli_refuses_nonvector_model_argv(argv):
    args = cli.parser().parse_args(["prepare-replay", "--argv-json", argv])
    with pytest.raises(ValueError, match="JSON string array"):
        cli._dispatch(args, SimpleNamespace())


def test_cli_legacy_import_has_explicit_trusted_checkout(core_store):
    from .test_legacy_bridge import ROOT, RUN

    args = cli.parser().parse_args(
        ["import-legacy", str(RUN), "--trusted-checkout", str(ROOT)]
    )
    result = cli._dispatch(args, core_store)
    imported = core_store.get(result["id"])
    assert imported.kind == "legacy_import"
    assert result["trust_class"] == "legacy_custody_verified"


def test_cli_retry_preserves_operator_audit_fields():
    received = {}

    def retry(job_id, **kwargs):
        received.update(job_id=job_id, **kwargs)
        return {"id": job_id, "state": "pending"}

    args = cli.parser().parse_args(
        ["retry-job", "4", "--actor", "operator", "--reason", "TSA recovered"]
    )
    result = cli._dispatch(args, SimpleNamespace(retry_job=retry))
    assert result == {"id": 4, "state": "pending"}
    assert received == {"job_id": 4, "actor": "operator", "reason": "TSA recovered"}


@pytest.mark.parametrize("tamper", ["validation_version", "observation"])
def test_cli_resolution_validation_precedes_the_unique_target_slot(
    core_store, tmp_path, tamper
):
    from datetime import datetime, timezone

    from thesis_core.contracts import Resolution, parse_record
    from thesis_core.pilot import prepare_replay
    from thesis_core.resolution import VALIDATION_VERSION, resolve_target

    from .test_pilot import statcan_fixture

    experiment = prepare_replay(core_store, fetch=statcan_fixture)
    target = core_store.get(experiment.target_version_ids[0])
    genuine = next(
        observation
        for observation in core_store.iter_records("observation")
        if observation.measurement_period == target.measurement_period
    )
    observation = genuine
    if tamper == "observation":
        observation = parse_record(
            "observation", genuine.canonical_payload() | {"value": genuine.value + 1.0}
        )
        core_store.put(observation)
    invalid = Resolution(
        target_version_id=target.id,
        observation_id=observation.id,
        resolution_policy=target.resolution_policy,
        validation_version="caller-asserted"
        if tamper == "validation_version"
        else VALIDATION_VERSION,
        recorded_at=datetime.now(timezone.utc),
    )
    path = tmp_path / "invalid-resolution.json"
    path.write_bytes(invalid.canonical_bytes())
    args = cli.parser().parse_args(["register", str(path), "--kind", "resolution"])
    with pytest.raises(ValueError):
        cli._dispatch(args, core_store)
    assert tuple(core_store.iter_records("resolution")) == ()
    assert not core_store.artifacts.exists(invalid.id)
    resolution = resolve_target(core_store, target.id)
    assert resolution.observation_id == genuine.id
    assert len(tuple(core_store.iter_records("resolution"))) == 1
