"""Read projections preserve native distributions and complete experiment coverage."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from time import perf_counter

import pytest
from fastapi.testclient import TestClient

from thesis_core.api import create_app
from thesis_core.canonical import canonical_bytes
from thesis_core.contracts import (
    Attempt,
    AttemptResult,
    EvaluationTask,
    Experiment,
    ForecasterVersion,
    TargetVersion,
)
from thesis_core.lab import display_quantiles
from thesis_core.pilot import prepare_replay
from thesis_core.resolution import capture_source, resolve_target
from thesis_core.scoring import build_interval_distribution
from thesis_core.worker import schedule_experiment, work_once

from .test_pilot import statcan_fixture


def setup_replay(store, *, execute=False, resolve=False):
    experiment = prepare_replay(store, fetch=statcan_fixture)
    if execute:
        schedule_experiment(store, experiment.id)
        result = work_once(store, kinds=("forecast",))
        assert result["run_id"], result
    if resolve:
        resolve_target(store, experiment.target_version_ids[0])
    return experiment


def test_cdf_display_uses_native_points_and_leftmost_plateau():
    distribution = build_interval_distribution(2, 0, 6)
    payload = distribution.model_dump(mode="json", by_alias=True)
    payload["summary"] = {
        "pointEstimate": 999,
        "median": 999,
        "interval80": {"lower": 900, "upper": 1000},
    }
    altered = type(distribution).model_validate_json(json.dumps(payload))
    assert display_quantiles(altered) == display_quantiles(distribution)
    assert altered.summary.median == 999
    plateau = payload | {
        "points": [
            {
                "value": float(i),
                "probability": i / 100
                if i < 50
                else 0.5
                if i < 151
                else 0.5 + (i - 150) / 100,
            }
            for i in range(201)
        ],
        "support": {"lower": 0, "upper": 200},
    }
    plateau_cdf = type(distribution).model_validate_json(json.dumps(plateau))
    assert display_quantiles(plateau_cdf)["q50"] == 50
    assert display_quantiles(plateau_cdf)["q90"] == 190


def test_empty_lab_is_distinct_from_unavailable(core_store, monkeypatch):
    client = TestClient(create_app(core_store))
    for route in ("forecasts", "experiments", "agents"):
        response = client.get(f"/lab/{route}")
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []
        assert response.json()["total"] == 0
        assert response.headers["cache-control"] == "no-store"
    monkeypatch.delenv("THESIS_CORE_DSN", raising=False)
    assert TestClient(create_app()).get("/lab/forecasts").status_code == 503


def test_complete_replay_pages_read_only_and_original_distribution(core_store):
    experiment = setup_replay(core_store, execute=True, resolve=True)
    target = experiment.target_version_ids[0]
    agent = experiment.forecaster_version_ids[0]
    task = experiment.task_ids[0]
    run = next(core_store.iter_records("forecast_run"))
    before = [r.id for r in core_store.iter_records()]
    jobs_before = core_store.jobs()
    client = TestClient(create_app(core_store))
    paths = [
        "/lab/forecasts",
        f"/lab/forecasts/{target}",
        f"/lab/forecasts/{target}/experiments",
        "/lab/experiments",
        f"/lab/experiments/{experiment.id}",
        f"/lab/experiments/{experiment.id}/matrix",
        f"/lab/experiments/{experiment.id}/results",
        "/lab/agents",
        f"/lab/agents/{agent}",
        f"/lab/agents/{agent}/experiments",
        f"/lab/tasks/{task}/attempts",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        assert response.json()["schema_version"] == "thesis_lab_v1"
    response = client.get(
        f"/lab/forecasts/{target}/comparisons", params={"experiment_id": experiment.id}
    )
    assert response.status_code == 200, response.text
    comparison = response.json()["items"][0]
    assert canonical_bytes(comparison["distribution"]) == canonical_bytes(
        run.distribution.model_dump(mode="json", by_alias=True)
    )
    assert comparison["execution"]["state"] == "succeeded"
    assert comparison["resolution"]["state"] == "resolved"
    assert comparison["score"]["crps"] is not None
    assert comparison["score"]["eligibility"] == {
        "state": "ineligible",
        "reason_codes": ["replay"],
        "ranking_allowed": False,
        "reward": None,
    }
    assert comparison["score"]["score"] is None  # GET computed, did not persist
    assert comparison["execution"]["cost"]["amount"] is None
    assert comparison["execution"]["elapsed_seconds"] >= 0
    assert {"stdout", "stderr", "raw_response", "prompt", "command", "code"} <= {
        item["role"] for item in comparison["evidence_links"]
    }
    summary = client.get("/lab/forecasts").json()["items"][0]
    assert summary["mode_counts"] == {"prospective": 0, "replay": 1, "live_pilot": 0}
    assert summary["coverage"]["declared_tasks"] == 1
    assert summary["coverage"]["succeeded_tasks"] == 1
    assert summary["coverage"]["eligible_tasks"] == 0
    assert [r.id for r in core_store.iter_records()] == before
    assert core_store.jobs() == jobs_before
    assert client.get("/experiments").json()["items"][0]["id"] == experiment.id


def test_unscheduled_and_queued_cells_are_not_lost(core_store):
    experiment = setup_replay(core_store)
    client = TestClient(create_app(core_store))
    path = f"/lab/experiments/{experiment.id}/matrix"
    cell = client.get(path).json()["rows"][0]["cells"][0]
    assert cell["execution"]["state"] == "not_scheduled"
    assert cell["task"] is not None and cell["selected_run"] is None
    schedule_experiment(core_store, experiment.id)
    cell = client.get(path).json()["rows"][0]["cells"][0]
    assert cell["execution"]["state"] == "queued"
    assert cell["resolution"]["state"] == "pending"


def test_invalid_declared_matrix_retains_absent_pair(core_store):
    experiment = setup_replay(core_store)
    baseline = core_store.get(experiment.baseline_forecaster_id)
    second = ForecasterVersion.model_validate_json(
        canonical_bytes(
            baseline.canonical_payload() | {"agent_version": "second-method"}
        )
    )
    core_store.put(second)
    original_task = core_store.get(experiment.task_ids[0])
    distinct_task = EvaluationTask.model_validate_json(
        canonical_bytes(original_task.canonical_payload() | {"max_attempts": 2})
    )
    core_store.put(distinct_task)
    invalid = Experiment.model_validate_json(
        canonical_bytes(
            experiment.canonical_payload()
            | {
                "task_ids": [distinct_task.id],
                "forecaster_version_ids": [
                    *experiment.forecaster_version_ids,
                    second.id,
                ],
            }
        )
    )
    core_store.put(invalid)
    response = TestClient(create_app(core_store)).get(
        f"/lab/experiments/{invalid.id}/matrix"
    )
    assert response.status_code == 200, response.text
    cells = response.json()["rows"][0]["cells"]
    assert len(cells) == 2
    assert all(c["execution"]["state"] == "invalid" for c in cells)
    absent = next(c for c in cells if c["forecaster_id"] == second.id)
    assert absent["task"] is None
    assert absent["execution"]["attempts_path"] is None
    assert absent["score"]["eligibility"]["reason_codes"] == ["invalid_contract"]
    client = TestClient(create_app(core_store))
    agents = client.get("/lab/agents").json()["items"]
    agent = next(item for item in agents if item["id"] == second.id)
    assert agent["experiment_count"] == 1
    assert agent["declared_task_count"] == 1
    assert agent["attempt_counts"]["total"] == 0
    detail = client.get(f"/lab/agents/{second.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["declared_task_count"] == 1


def test_collection_and_method_pagination_and_strict_queries(core_store):
    experiment = setup_replay(core_store)
    baseline = core_store.get(experiment.baseline_forecaster_id)
    others = []
    for number in range(3):
        other = ForecasterVersion.model_validate_json(
            canonical_bytes(
                baseline.canonical_payload() | {"agent_version": f"other-{number}"}
            )
        )
        core_store.put(other)
        others.append(other.id)
    original_task = core_store.get(experiment.task_ids[0])
    distinct_task = EvaluationTask.model_validate_json(
        canonical_bytes(original_task.canonical_payload() | {"max_attempts": 2})
    )
    core_store.put(distinct_task)
    expanded = Experiment.model_validate_json(
        canonical_bytes(
            experiment.canonical_payload()
            | {
                "task_ids": [distinct_task.id],
                "forecaster_version_ids": [*experiment.forecaster_version_ids, *others],
            }
        )
    )
    core_store.put(expanded)
    client = TestClient(create_app(core_store))
    first = client.get("/lab/agents?limit=2").json()
    second = client.get(
        "/lab/agents", params={"limit": 2, "after": first["next_cursor"]}
    ).json()
    assert first["total"] == second["total"] == 4
    assert len({item["id"] for page in (first, second) for item in page["items"]}) == 4
    matrix_path = f"/lab/experiments/{expanded.id}/matrix"
    first = client.get(matrix_path, params={"method_limit": 2}).json()
    second = client.get(
        matrix_path,
        params={"method_limit": 2, "method_after": first["next_method_cursor"]},
    ).json()
    assert first["total_methods"] == second["total_methods"] == 4
    assert (
        len(
            {
                col["forecaster_id"]
                for page in (first, second)
                for col in page["columns"]
            }
        )
        == 4
    )
    for query in (
        "limit=0",
        "limit=101",
        "limit=01",
        "limit=1&limit=2",
        "after=no",
        "wrong=x",
    ):
        assert client.get("/lab/forecasts?" + query).status_code == 422
    assert client.get(matrix_path + "?limit=21").status_code == 422
    assert client.get(matrix_path + "?method_limit=11").status_code == 422
    assert (
        client.get(
            f"/lab/forecasts/{experiment.target_version_ids[0]}/comparisons"
        ).status_code
        == 422
    )
    assert client.get("/lab/agents/" + "0" * 64).status_code == 404
    assert client.get(f"/lab/agents/{experiment.id}").status_code == 404
    assert client.post("/lab/forecasts").status_code == 405


def test_later_source_conflict_preserves_resolution_but_invalidates_value(core_store):
    experiment = setup_replay(core_store, execute=True, resolve=True)
    target = experiment.target_version_ids[0]
    original = next(core_store.iter_records("resolution"))

    # A later second retrieval of identical official vintage is not a conflict.
    # Inject a different official fixture value for the exact same dated vintage.
    def changed(request):
        response = statcan_fixture(request)
        payload = json.loads(response.body)
        # Preserve the source's complete wire structure while changing the final
        # current-index value used by the transformed target observation.
        payload[0]["object"]["vectorDataPoint"][-1]["value"] += 2
        return type(response)(json.dumps(payload).encode(), request.url)

    capture_source(core_store, "statcan-cpi-yoy", fetch=changed)
    response = TestClient(create_app(core_store)).get(f"/lab/forecasts/{target}")
    assert response.status_code == 200, response.text
    resolution = response.json()["resolution"]
    assert resolution["state"] == "invalid"
    assert resolution["value"] is None
    assert resolution["resolution"]["id"] == original.id
    assert core_store.get(original.id).canonical_bytes() == original.canonical_bytes()


def test_scoped_prerelease_capture_budget_stays_under_proxy_deadline(core_store):
    experiment = setup_replay(core_store)
    before = len(tuple(core_store.iter_records("observation")))
    for _ in range(96):
        result = capture_source(
            core_store,
            "statcan-cpi-yoy",
            measurement_period="2099-01",
            fetch=statcan_fixture,
        )
        assert result.observations == ()
    assert len(tuple(core_store.iter_records("observation"))) == before
    assert len(tuple(core_store.iter_records("source_exchange"))) == 97
    start = perf_counter()
    response = TestClient(create_app(core_store)).get("/lab/forecasts")
    elapsed = perf_counter() - start
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["coverage"]["declared_tasks"] == len(
        experiment.task_ids
    )
    assert elapsed < 5, f"lab list took {elapsed:.3f}s after96 polls"


def test_running_unknown_reconciled_failure_remain_in_coverage(core_store):
    from .test_store import attempt_factory, expire

    experiment = setup_replay(core_store)
    task = core_store.get(experiment.task_ids[0])
    schedule_experiment(core_store, experiment.id)
    core_store.deliver_outbox()
    claim = core_store.claim("PRIVATE-WORKER-SENTINEL", ("forecast",))
    attempt = core_store.start_attempt(
        claim, task.id, attempt_factory(core_store, task)
    )
    client = TestClient(create_app(core_store))
    path = f"/lab/experiments/{experiment.id}/matrix"
    cell = client.get(path).json()["rows"][0]["cells"][0]
    assert cell["execution"]["state"] == "running"
    assert cell["execution"]["elapsed_seconds"] is None
    expire(core_store, claim)
    core_store.recover_expired()
    cell = client.get(path).json()["rows"][0]["cells"][0]
    assert cell["execution"]["state"] == "unknown"
    assert cell["selected_run"] is None
    assert cell["execution"]["attempt_counts"]["unknown"] == 1
    core_store.reconcile_unknown(
        claim.job_id, actor="PRIVATE-ACTOR-SENTINEL", reason="PRIVATE-REASON-SENTINEL"
    )
    response = client.get(f"/lab/tasks/{task.id}/attempts")
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["id"] == attempt.id
    assert item["outcome"] == "failed" and item["selected"] is False
    assert item["elapsed_seconds"] is None and item["elapsed_basis"] is None
    assert [r["outcome"] for r in item["results"]] == ["unknown", "failed"]
    assert item["results"][1]["reconciliation_verified"] is True
    assert "PRIVATE-" not in response.text
    summary = client.get(f"/lab/experiments/{experiment.id}").json()
    assert summary["coverage"]["failed_tasks"] == 1
    results = client.get(f"/lab/experiments/{experiment.id}/results").json()["items"][0]
    assert results["attempt_counts"]["unknown_history"] == 1
    assert results["attempt_counts"]["reconciled"] == 1
    assert results["elapsed_sample_count"] == 0


def test_known_predispatch_failure_is_visible_without_attempt(core_store, monkeypatch):
    experiment = setup_replay(core_store)
    schedule_experiment(core_store, experiment.id)

    def refuse(*_args, **_kwargs):
        raise ValueError("PRIVATE-FAILURE-SENTINEL /private/operator/path")

    monkeypatch.setattr("thesis_core.execution.execute_forecast", refuse)
    result = work_once(core_store, kinds=("forecast",))
    assert result["status"] == "failed"
    response = TestClient(create_app(core_store)).get(
        f"/lab/experiments/{experiment.id}"
    )
    assert response.status_code == 200, response.text
    assert response.json()["coverage"]["failed_tasks"] == 1
    assert response.json()["coverage"]["declared_tasks"] == 1
    assert "PRIVATE-FAILURE" not in response.text
    assert "/private/operator" not in response.text


def test_operations_narrow_projection_and_missing_tables_refuse(core_store):
    experiment = setup_replay(core_store)
    schedule_experiment(core_store, experiment.id)
    core_store.deliver_outbox()
    claim = core_store.claim("PRIVATE-WORKER-SENTINEL", ("forecast",))
    client = TestClient(create_app(core_store))
    response = client.get("/lab/operations")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["polling"]["state"] == "not_scheduled"
    assert payload["polling"]["worker"]["status"] == "never_seen"
    assert payload["worker"]["state"] == "observed_active"
    assert payload["items"][0]["attention_codes"] == ["capture_not_scheduled"]
    assert "PRIVATE-" not in response.text
    assert core_store.schema not in response.text
    assert claim.lease_token not in response.text
    assert "postgres_version" not in response.text
    assert "payload" not in response.text
    with core_store.connection() as connection:
        connection.execute("DROP TABLE source_poll_worker")
    failed = client.get("/lab/operations")
    assert failed.status_code == 503
    assert failed.json() == {"error": {"code": "store_unavailable"}}


def test_invalid_scientific_contract_keeps_matrix_but_structural_loss_refuses(
    core_store, monkeypatch
):
    from dataclasses import replace

    import thesis_core.lab as lab_module

    experiment = setup_replay(core_store)
    original = lab_module.context_for_store

    def invalid_context(store):
        context = original(store)

        def refuse(_record):
            raise ValueError("PRIVATE-VALIDATION-SENTINEL")

        return replace(context, availability=refuse)

    monkeypatch.setattr(lab_module, "context_for_store", invalid_context)
    client = TestClient(create_app(core_store))
    path = f"/lab/experiments/{experiment.id}/matrix"
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["cells"][0]["execution"]["state"] == "invalid"
    assert "PRIVATE-VALIDATION" not in response.text

    def missing_context(store):
        context = original(store)
        records = dict(context.records)
        del records[experiment.target_version_ids[0]]
        return replace(context, records=records)

    monkeypatch.setattr(lab_module, "context_for_store", missing_context)
    response = client.get(path)
    assert response.status_code == 409
    assert response.json() == {"error": {"code": "scientific_integrity_failure"}}


def test_missing_declared_agent_artifact_is_not_empty_evidence(core_store):
    from .factories import digest

    experiment = setup_replay(core_store)
    baseline = core_store.get(experiment.baseline_forecaster_id)
    missing = ForecasterVersion.model_validate_json(
        canonical_bytes(
            baseline.canonical_payload()
            | {"prompt_template_hash": digest("not-archived")}
        )
    )
    # Storage admits the scientific reference; the read must not turn absent
    # artifact bytes into a successful empty download or fabricated metadata.
    core_store.put(missing)
    client = TestClient(create_app(core_store))
    response = client.get(f"/lab/agents/{missing.id}")
    assert response.status_code == 409
    assert response.json() == {"error": {"code": "scientific_integrity_failure"}}
    direct = client.get(f"/artifacts/{missing.prompt_template_hash}")
    assert direct.status_code == 404
    assert direct.json() == {"error": {"code": "artifact_not_found"}}


@pytest.mark.parametrize(
    "missing_kind", ["evidence_bundle", "normalization", "source_series", "observation"]
)
def test_transitive_scientific_reference_loss_refuses_before_validation(
    core_store, monkeypatch, missing_kind
):
    import thesis_core.lab as lab_module

    experiment = setup_replay(core_store)
    original = lab_module.context_for_store
    task = core_store.get(experiment.task_ids[0])
    bundle = core_store.get(task.evidence_bundle_id)
    target = core_store.get(task.target_version_id)
    # Capture also retains an outcome outside this unresolved cohort's closure.
    # Select the declared dependency, never the first record in hash order.
    missing_id = {
        "evidence_bundle": bundle.id,
        "normalization": experiment.normalization_ids[0],
        "source_series": target.source_series_id,
        "observation": bundle.observation_ids[0],
    }[missing_kind]

    def damaged_context(store):
        context = original(store)
        records = dict(context.records)
        del records[missing_id]
        return replace(context, records=records)

    monkeypatch.setattr(lab_module, "context_for_store", damaged_context)
    client = TestClient(create_app(core_store))
    for path in (
        f"/lab/experiments/{experiment.id}/matrix",
        f"/lab/experiments/{experiment.id}/results",
        "/lab/forecasts",
        f"/lab/agents/{experiment.baseline_forecaster_id}",
    ):
        response = client.get(path)
        assert response.status_code == 409, (path, response.text)
        assert response.json() == {"error": {"code": "scientific_integrity_failure"}}


def test_unreferenced_outcome_loss_does_not_corrupt_unresolved_cohort(
    core_store, monkeypatch
):
    import thesis_core.lab as lab_module

    experiment = setup_replay(core_store)
    task = core_store.get(experiment.task_ids[0])
    bundle = core_store.get(task.evidence_bundle_id)
    target = core_store.get(task.target_version_id)
    outcome = next(
        record
        for record in core_store.iter_records("observation")
        if record.measurement_period == target.measurement_period
    )
    assert outcome.id not in bundle.observation_ids
    assert outcome.id not in core_store.get(
        experiment.normalization_ids[0]
    ).observation_ids
    original = lab_module.context_for_store

    def without_unreferenced_outcome(store):
        context = original(store)
        records = dict(context.records)
        del records[outcome.id]
        return replace(context, records=records)

    monkeypatch.setattr(lab_module, "context_for_store", without_unreferenced_outcome)
    client = TestClient(create_app(core_store))
    for path in (
        f"/lab/experiments/{experiment.id}/matrix",
        f"/lab/experiments/{experiment.id}/results",
        "/lab/forecasts",
        f"/lab/agents/{experiment.baseline_forecaster_id}",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)


def test_cross_attempt_result_cannot_select_another_methods_run(
    core_store, monkeypatch
):
    import thesis_core.lab as lab_module

    experiment = setup_replay(core_store, execute=True)
    baseline = core_store.get(experiment.baseline_forecaster_id)
    baseline_task = core_store.get(experiment.task_ids[0])
    baseline_attempt = next(core_store.iter_records("attempt"))
    baseline_result = next(core_store.iter_records("attempt_result"))
    model = ForecasterVersion.model_validate_json(
        canonical_bytes(
            baseline.canonical_payload()
            | {
                "model_request": "another-model",
                "execution_policy": "operator_subprocess",
            }
        )
    )
    task = EvaluationTask.model_validate_json(
        canonical_bytes(
            baseline_task.canonical_payload()
            | {
                "forecaster_version_id": model.id,
                "execution_policy": "operator_subprocess",
            }
        )
    )
    expanded = Experiment.model_validate_json(
        canonical_bytes(
            experiment.canonical_payload()
            | {
                "task_ids": [baseline_task.id, task.id],
                "forecaster_version_ids": [baseline.id, model.id],
            }
        )
    )
    attempt = Attempt.model_validate_json(
        canonical_bytes(
            baseline_attempt.canonical_payload()
            | {"task_id": task.id, "execution_policy": "operator_subprocess"}
        )
    )
    # Every referenced kind exists, but the result borrows the baseline run.
    result = AttemptResult.model_validate_json(
        canonical_bytes(
            baseline_result.canonical_payload() | {"attempt_id": attempt.id}
        )
    )
    with core_store.transaction() as transaction:
        for record in (model, task):
            transaction.put(record)
    original = lab_module.context_for_store

    def expanded_context(store):
        context = original(store)
        return replace(
            context,
            records=dict(context.records)
            | {record.id: record for record in (expanded, attempt, result)},
        )

    # Inject corruption at the read boundary: the database correctly disallows
    # shared task membership and attempts without their allocated sequence.
    monkeypatch.setattr(lab_module, "context_for_store", expanded_context)
    client = TestClient(create_app(core_store))
    for path in (
        f"/lab/tasks/{task.id}/attempts",
        f"/lab/experiments/{expanded.id}/matrix",
        f"/lab/forecasts/{task.target_version_id}/comparisons?experiment_id={expanded.id}",
    ):
        response = client.get(path)
        assert response.status_code == 409, (path, response.text)
        assert response.json() == {"error": {"code": "scientific_integrity_failure"}}


@pytest.mark.parametrize("artifact_owner", ["source_exchange", "forecast_run"])
def test_missing_transitive_artifact_is_lab_integrity_failure(
    core_store, monkeypatch, artifact_owner
):
    from thesis_core.artifacts import ArtifactMissing

    experiment = setup_replay(core_store, execute=True)
    owner = next(core_store.iter_records(artifact_owner))
    digest = (
        owner.body.sha256 if artifact_owner == "source_exchange" else owner.stdout_hash
    )
    original = core_store.artifacts.read_bytes

    def missing(identity):
        if identity == digest:
            raise ArtifactMissing("PRIVATE-ARTIFACT-SENTINEL")
        return original(identity)

    monkeypatch.setattr(core_store.artifacts, "read_bytes", missing)
    response = TestClient(create_app(core_store)).get(
        f"/lab/experiments/{experiment.id}/matrix"
    )
    assert response.status_code == 409, response.text
    assert response.json() == {"error": {"code": "scientific_integrity_failure"}}
    assert "PRIVATE-" not in response.text


@pytest.mark.parametrize(
    "vintage_days,read_offset,expected",
    [(0, -1, False), (0, 0, True), (1, 60, False), (1, 172800, True)],
)
def test_operations_release_attention_uses_verified_bound_and_selected_vintage(
    core_store, monkeypatch, vintage_days, read_offset, expected
):
    from .test_polling import polling_target

    target = polling_target(core_store)
    release_at = datetime.fromisoformat(target.release_evidence.raw_value)
    if vintage_days:
        target = TargetVersion.model_validate_json(
            canonical_bytes(
                target.canonical_payload()
                | {
                    "vintage_date": (release_at + timedelta(days=vintage_days))
                    .date()
                    .isoformat()
                }
            )
        )
        core_store.put(target)
    monkeypatch.setattr(
        "thesis_core.lab.database_now",
        lambda _: release_at + timedelta(seconds=read_offset),
    )
    response = TestClient(create_app(core_store)).get("/lab/operations")
    assert response.status_code == 200, response.text
    row = next(row for row in response.json()["items"] if row["target_id"] == target.id)
    assert row["release"]["state"] == "verified"
    assert ("release_passed_unresolved" in row["attention_codes"]) is expected
    if expected:
        assert "inspect_capture" in row["recovery_action_codes"]


def test_operations_unknown_or_invalid_release_is_not_declared_overdue(
    core_store, monkeypatch
):
    import thesis_core.lab as lab_module

    from .test_polling import polling_target

    target = polling_target(core_store)
    original = lab_module.context_for_store

    for state in ("unknown", "invalid"):

        def unavailable(_target):
            if state == "invalid":
                raise ValueError("PRIVATE-INVALID-RELEASE")
            return None

        monkeypatch.setattr(
            lab_module,
            "context_for_store",
            lambda store: replace(original(store), target_availability=unavailable),
        )
        response = TestClient(create_app(core_store)).get("/lab/operations")
        assert response.status_code == 200, response.text
        row = next(
            row for row in response.json()["items"] if row["target_id"] == target.id
        )
        assert row["release"]["state"] == state
        assert "release_passed_unresolved" not in row["attention_codes"]


@pytest.mark.parametrize(
    "read_time,expected",
    [("2026-09-15T04:00:00+00:00", False), ("2026-09-16T04:00:00+00:00", True)],
)
def test_date_only_release_end_does_not_expire_next_days_selected_vintage(
    core_store, monkeypatch, read_time, expected
):
    from pathlib import Path

    from thesis_core.adapters import release_evidence_from_bytes
    from thesis_core.adapters.registry import get_source
    from thesis_core.adapters.timing import STATCAN_CPI_PORTAL_URL

    source = get_source("statcan-cpi-yoy")
    raw = (
        Path(__file__).parents[1] / "fixtures/core/statcan_cpi_portal_20260905.html"
    ).read_bytes()
    evidence = release_evidence_from_bytes(
        source, "2026-08", raw, STATCAN_CPI_PORTAL_URL, core_store.artifacts
    )
    target = TargetVersion(
        target_id="later-vintage-date-only-release",
        source_series_id=source.id,
        measurement_period="2026-08",
        unit=source.unit,
        resolution_policy="fixed_vintage",
        vintage_date="2026-09-15",
        resolution_rule="Exact selected vintage",
        submission_deadline=datetime.fromisoformat("2026-09-14T03:59:00+00:00"),
        release_evidence=evidence,
    )
    with core_store.transaction() as transaction:
        transaction.put(source)
        transaction.put(target)
    monkeypatch.setattr(
        "thesis_core.lab.database_now", lambda _: datetime.fromisoformat(read_time)
    )
    response = TestClient(create_app(core_store)).get("/lab/operations")
    assert response.status_code == 200, response.text
    row = response.json()["items"][0]
    assert row["release"]["upper"] == "2026-09-15T04:00:00Z"
    assert ("release_passed_unresolved" in row["attention_codes"]) is expected


def test_lab_schema_is_separate_and_reproducible():
    from thesis_core.lab_schema import generate, schema_document
    from thesis_core.schema import schema_document as scientific_schema

    before = canonical_bytes(scientific_schema())
    document = schema_document()
    assert "MatrixPage" in document["$defs"]
    assert "NumericCdf" in document["$defs"]
    generate(check=True)
    assert canonical_bytes(scientific_schema()) == before


def test_projection_dates_refuse_impossible_or_unzoned_values():
    import pytest
    from pydantic import TypeAdapter, ValidationError

    from thesis_core.lab_contracts import CalendarDate, Instant

    for value in (
        "2026-02-30T00:00:00Z",
        "2026-09-05T25:00:00Z",
        "2026-09-05T12:00:00",
        "2026-09-05T12:00:00+01:00",
    ):
        with pytest.raises(ValidationError):
            TypeAdapter(Instant).validate_python(value)
    for value in ("2026-02-30", "2026-1-1", "2026-09-05T00:00:00Z"):
        with pytest.raises(ValidationError):
            TypeAdapter(CalendarDate).validate_python(value)
    assert (
        TypeAdapter(Instant).validate_python("2026-09-05T12:00:00.123456Z")
        == "2026-09-05T12:00:00.123456Z"
    )
    assert TypeAdapter(CalendarDate).validate_python("2028-02-29") == "2028-02-29"
