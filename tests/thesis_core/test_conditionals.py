"""Exploratory pairing, durable attempts, and exclusion from scientific records."""

import json
import time
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient

from thesis_core.api import create_app
from thesis_core.conditional_contracts import (
    ConditionalContract,
    PairedModelResponse,
    contract_id,
    shared_evidence_id,
    validate_response,
)
from thesis_core.conditionals import (
    conditional_detail,
    conditional_page,
    finish_attempt,
    recover_attempts,
    start_attempt,
)


def contract_data(artifact="a" * 64):
    return {
        "title": "Paired public outcome",
        "question": "What is the score under the two specified policy states?",
        "outcome": {
            "name": "Public score",
            "country": "US",
            "geography": "national",
            "population": "public schools grade 8",
            "measure": "average mathematics scale score",
            "measurement_period": "2030",
            "unit": "scale points",
            "resolution_rule": "First official release, no inferred release date.",
            "resolution_source_url": "https://example.gov/score",
            "release_date": None,
        },
        "arms": [
            {
                "id": "enacted",
                "label": "Enacted",
                "condition": "Bill enacted by deadline",
                "assumptions": [],
            },
            {
                "id": "neither",
                "label": "Neither enacted",
                "condition": "Neither bill enacted by deadline",
                "assumptions": [],
            },
        ],
        "reference_description": "One shared reference forecast from public history",
        "condition_deadline": "2029-01-01T00:00:00Z",
        "condition_resolution_note": "No mechanical condition resolver is registered.",
        "exhaustive": False,
        "shared_history": [{"period": "2024", "value": 272, "source_id": "official"}],
        "sources": [
            {
                "id": "official",
                "title": "Official source",
                "url": "https://example.gov/score",
                "retrieved_at": "2026-01-01T00:00:00Z",
                "artifact": {
                    "sha256": artifact,
                    "bytes": 8,
                    "media_type": "text/plain",
                },
            }
        ],
        "shared_evidence": [
            {"claim": "2024 score was 272", "source_ids": ["official"]}
        ],
        "limitations": ["Exploratory; no registered condition or scoring path."],
    }


def contract(artifact="a" * 64):
    return ConditionalContract.model_validate_json(json.dumps(contract_data(artifact)))


def cdf(shift=0):
    return {
        "format": "numeric_cdf_v1",
        "pointCount": 201,
        "support": {"lower": 170 + shift, "upper": 370 + shift},
        "points": [
            {"value": 170 + index + shift, "probability": index / 200}
            for index in range(201)
        ],
        "summary": {
            "pointEstimate": 270 + shift,
            "median": 270 + shift,
            "interval80": {"lower": 190 + shift, "upper": 350 + shift},
        },
        "provenance": "agent_reported",
        "transformVersion": "native_conditional_v1",
    }


def response_data(spec):
    return {
        "contract_id": contract_id(spec),
        "shared_evidence_id": shared_evidence_id(spec),
        "reference": cdf(),
        "reference_reasoning": "Same frozen history",
        "arms": [
            {
                "id": "enacted",
                "baseline_delta": 1,
                "distribution": cdf(1),
                "reasoning": "Mechanism and uncertainty",
            },
            {
                "id": "neither",
                "baseline_delta": 0,
                "distribution": cdf(),
                "reasoning": "Reference policy state",
            },
        ],
    }


def start(store, *, timeout=60):
    source = store.artifacts.put_bytes(b"official")
    spec = contract(source)
    attempt = start_attempt(
        store,
        spec,
        prompt=b"Frozen public prompt",
        command=b'{"argv":["codex"]}',
        code=b"print('transport')",
        requested_model="requested-model",
        timeout_seconds=timeout,
    )
    return spec, attempt


@pytest.mark.parametrize(
    "model", ["", "model name", "model+preview", "model@provider", "model#1", "x" * 201]
)
def test_invalid_requested_model_cannot_poison_existing_listing(core_store, model):
    spec, existing = start(core_store)
    with pytest.raises(ValueError, match="requested model"):
        start_attempt(
            core_store,
            spec,
            prompt=b"Frozen prompt",
            command=b"arbitrary public command",
            code=b"transport",
            requested_model=model,
        )
    page = conditional_page(core_store)
    assert page.total == 1
    assert page.items[0].id == existing.id
    assert page.requested_models == ["requested-model"]


def test_requested_model_accepts_provider_qualified_name(core_store):
    spec, _ = start(core_store)
    model = "provider/model_v2.1:preview-2026"
    attempt = start_attempt(
        core_store,
        spec,
        prompt=b"Frozen prompt",
        command=b"arbitrary public command",
        code=b"transport",
        requested_model=model,
    )
    page = conditional_page(core_store, requested_model=model)
    assert page.total == 1
    assert page.items[0].id == attempt.id
    assert model in page.requested_models


def test_pair_contract_accepts_real_knots_and_matching_deltas():
    spec = contract()
    response = PairedModelResponse.model_validate_json(json.dumps(response_data(spec)))
    validate_response(spec, response)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "reorder",
        "extra",
        "history",
        "evidence",
        "delta",
        "interval",
        "seeded",
        "nonfinite",
    ],
)
def test_entire_pair_refuses_structural_or_distribution_drift(change):
    spec = contract()
    data = response_data(spec)
    if change == "missing":
        data["arms"].pop()
    elif change == "reorder":
        data["arms"].reverse()
    elif change == "extra":
        data["arms"].append(data["arms"][0])
    elif change == "history":
        data["arms"][0]["historicalContext"] = [999]
    elif change == "evidence":
        data["shared_evidence_id"] = "f" * 64
    elif change == "delta":
        data["arms"][0]["baseline_delta"] = 99
    elif change == "interval":
        data["reference"]["summary"]["interval80"]["lower"] = 200
    elif change == "seeded":
        data["reference"]["provenance"] = "interval_seeded"
    else:
        data["arms"][0]["baseline_delta"] = float("inf")
    with pytest.raises(ValueError):
        validate_response(
            spec, PairedModelResponse.model_validate_json(json.dumps(data))
        )


def test_success_is_atomic_immutable_and_outside_science(core_store):
    spec, attempt = start(core_store)
    assert conditional_detail(core_store, attempt.id).execution_state == "running"
    detail = finish_attempt(
        core_store,
        attempt.id,
        stdout=b"event stream",
        stderr=b"",
        response=json.dumps(response_data(spec)).encode(),
    )
    assert detail.execution_state == "succeeded"
    assert detail.reference_quantiles.q50 == 270
    assert detail.arm_quantiles[0].q50 == 271
    assert detail.scoring_status == "not_registered"
    assert detail.observed_model is None
    assert {a.role for a in detail.artifacts} >= {
        "prompt",
        "code",
        "command",
        "stdout",
        "stderr",
        "response",
        "validation",
        "source:official",
    }
    with pytest.raises(ValueError, match="terminal"):
        finish_attempt(core_store, attempt.id, stdout=b"", stderr=b"", response=None)
    with core_store.connection() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == 0
        )
        assert connection.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 0
    with pytest.raises(psycopg.Error):
        with core_store.connection() as connection:
            connection.execute(
                "DELETE FROM conditional_attempts WHERE id=%s", (attempt.id,)
            )


@pytest.mark.parametrize(
    "raw", [b"broken JSON", b'{"contract_id":"a","contract_id":"b"}', b"{}"]
)
def test_invalid_response_remains_visible_with_trace(core_store, raw):
    _, attempt = start(core_store)
    detail = finish_attempt(
        core_store, attempt.id, stdout=b"trace", stderr=b"diagnostic", response=raw
    )
    assert detail.execution_state == "failed"
    assert detail.error_code == "invalid_response"
    assert detail.response is None
    assert conditional_page(core_store).items[0].execution_state == "failed"


def test_expired_dispatch_is_unknown_and_never_rerun(core_store):
    spec, attempt = start(core_store, timeout=1)
    time.sleep(1.1)
    assert conditional_detail(core_store, attempt.id).execution_state == "unknown"
    detail = finish_attempt(
        core_store,
        attempt.id,
        stdout=b"late trace",
        stderr=b"",
        response=json.dumps(response_data(spec)).encode(),
    )
    assert detail.response is None
    assert detail.execution_state == "unknown"
    assert any(item.role == "stdout" for item in detail.artifacts)
    assert recover_attempts(core_store) == 0
    detail = conditional_detail(core_store, attempt.id)
    assert detail.execution_state == "unknown"
    assert detail.finished_at is not None


def test_missing_source_and_late_contract_refuse_dispatch(core_store):
    with pytest.raises(Exception):
        start_attempt(
            core_store,
            contract(),
            prompt=b"x",
            command=b"y",
            code=b"z",
            requested_model="test",
        )
    raw = contract_data(core_store.artifacts.put_bytes(b"official"))
    raw["condition_deadline"] = (
        datetime.now(timezone.utc) + timedelta(seconds=10)
    ).isoformat()
    spec = ConditionalContract.model_validate_json(json.dumps(raw))
    with pytest.raises(ValueError, match="deadline"):
        start_attempt(
            core_store,
            spec,
            prompt=b"x",
            command=b"y",
            code=b"z",
            requested_model="test",
            timeout_seconds=60,
        )


def test_api_identity_pagination_queries_and_artifact_corruption(core_store):
    _, attempt = start(core_store)
    client = TestClient(create_app(core_store))
    page = client.get("/lab/conditionals")
    assert page.status_code == 200, page.text
    assert page.json()["items"][0]["id"] == attempt.id
    assert client.get("/lab/conditionals/" + attempt.id).status_code == 200
    assert client.get("/lab/conditionals/" + "a" * 64).status_code == 404
    for path in (
        "/lab/conditionals?limit=0",
        "/lab/conditionals?limit=1&limit=2",
        "/lab/conditionals?unknown=1",
        "/lab/conditionals?after=no",
        "/lab/conditionals/" + attempt.id + "?limit=1",
    ):
        assert client.get(path).status_code == 422
    assert client.get("/lab/forecasts").json()["items"] == []
    digest = attempt.artifacts[1].artifact.sha256
    original = core_store.artifacts.read_bytes
    core_store.artifacts.read_bytes = lambda identity: (
        b"bad" if identity == digest else original(identity)
    )
    assert client.get("/lab/conditionals/" + attempt.id).status_code == 409


def test_trusted_source_code_is_archived_exactly(core_store):
    from thesis_core.security import redact_stream_text

    code = b'example = "API_KEY=not-a-real-credential"'
    assert redact_stream_text(code.decode()).encode() != code
    spec = contract(core_store.artifacts.put_bytes(b"official"))
    attempt = start_attempt(
        core_store,
        spec,
        prompt=b"public prompt",
        command=b"codex",
        code=code,
        requested_model="test",
    )
    code_artifact = next(
        item.artifact for item in attempt.artifacts if item.role == "code"
    )
    assert core_store.artifacts.read_bytes(code_artifact.sha256) == code


def test_prompt_secret_is_refused_before_dispatch(core_store):
    spec = contract(core_store.artifacts.put_bytes(b"official"))
    with pytest.raises(ValueError, match="unsafe"):
        start_attempt(
            core_store,
            spec,
            prompt=b"API_KEY=synthetic-secret",
            command=b"codex",
            code=b"public code",
            requested_model="test",
        )
    assert conditional_page(core_store).total == 0


def test_schema_generator_preserves_exact_pair_tuples():
    from thesis_core.schema import _typescript

    rendered = _typescript(
        {
            "type": "array",
            "prefixItems": [
                {"$ref": "#/$defs/ConditionalArmSpec"},
                {"$ref": "#/$defs/ConditionalArmSpec"},
            ],
            "minItems": 2,
            "maxItems": 2,
        }
    )
    assert rendered == "readonly [ConditionalArmSpec, ConditionalArmSpec]"


def test_concurrent_finishes_seal_only_one_result(core_store):
    from concurrent.futures import ThreadPoolExecutor

    spec, attempt = start(core_store)
    response = json.dumps(response_data(spec)).encode()

    def finish():
        try:
            return finish_attempt(
                core_store,
                attempt.id,
                stdout=b"one trace",
                stderr=b"",
                response=response,
            ).execution_state
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        states = list(executor.map(lambda _: finish(), range(2)))
    assert states.count("succeeded") == 1
    assert sum("terminal" in state for state in states) == 1
    with core_store.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM conditional_results"
            ).fetchone()["n"]
            == 1
        )


def test_expired_finish_racing_recovery_cannot_create_success(core_store):
    from concurrent.futures import ThreadPoolExecutor

    spec, attempt = start(core_store, timeout=1)
    time.sleep(1.1)

    def finish():
        try:
            return finish_attempt(
                core_store,
                attempt.id,
                stdout=b"late",
                stderr=b"",
                response=json.dumps(response_data(spec)).encode(),
            ).execution_state
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        late = executor.submit(finish)
        recovery = executor.submit(recover_attempts, core_store)
        assert late.result() in ("unknown", "conditional attempt is already terminal")
        assert recovery.result() in (0, 1)
    detail = conditional_detail(core_store, attempt.id)
    assert detail.execution_state == "unknown"
    assert detail.response is None
    with core_store.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM conditional_results"
            ).fetchone()["n"]
            == 1
        )


@pytest.mark.parametrize("member", ["reference", 0, 1])
def test_each_distribution_requires_the_native_transform_version(member):
    spec = contract()
    data = response_data(spec)
    distribution = (
        data["reference"]
        if member == "reference"
        else data["arms"][member]["distribution"]
    )
    distribution["transformVersion"] = "interval_seeded_v1"
    response = PairedModelResponse.model_validate_json(json.dumps(data))
    with pytest.raises(ValueError, match="transform version"):
        validate_response(spec, response)


def test_corrupt_recovery_candidate_does_not_rollback_other_attempt(core_store, caplog):
    from thesis_core.artifacts import ArtifactCorrupt

    _, first = start(core_store, timeout=1)
    _, second = start(core_store, timeout=1)
    bad, good = sorted((first, second), key=lambda attempt: attempt.id)
    with core_store.connection() as connection:
        digest = connection.execute(
            "SELECT attempt_hash FROM conditional_attempts WHERE id=%s", (bad.id,)
        ).fetchone()["attempt_hash"]
    path = core_store.artifacts.root / digest[:2] / digest
    path.write_bytes(b"CORRUPT-PRIVATE-CONTENT")
    time.sleep(1.1)
    with caplog.at_level("WARNING", logger="thesis_core.conditionals"):
        assert recover_attempts(core_store) == 1
    assert bad.id in caplog.text
    assert "CORRUPT-PRIVATE-CONTENT" not in caplog.text
    assert conditional_detail(core_store, good.id).execution_state == "unknown"
    assert conditional_detail(core_store, good.id).finished_at is not None
    with pytest.raises(ArtifactCorrupt):
        conditional_detail(core_store, bad.id)
    with core_store.connection() as connection:
        results = connection.execute(
            "SELECT attempt_id FROM conditional_results"
        ).fetchall()
    assert [item["attempt_id"] for item in results] == [good.id]
    client = TestClient(create_app(core_store))
    assert client.get("/lab/conditionals/" + bad.id).status_code == 409
