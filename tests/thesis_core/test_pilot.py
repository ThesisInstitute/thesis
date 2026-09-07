"""Real PostgreSQL + official archived bytes + real persistence execution."""

from pathlib import Path

import pytest

from thesis_core.adapters import HttpResponse
from thesis_core.pilot import prepare_replay
from thesis_core.resolution import capture_source, resolve_target, validate_resolution
from thesis_core.service import evaluate_experiment
from thesis_core.worker import schedule_experiment, work_once

FIXTURES = Path(__file__).parents[1] / "fixtures"


def statcan_fixture(request):
    return HttpResponse(
        (FIXTURES / "international/statcan_cpi_v41690973.json").read_bytes(),
        request.url,
    )


def test_persistence_full_replay_flow(core_store):
    experiment = prepare_replay(core_store, fetch=statcan_fixture)
    assert experiment.mode == "replay"
    assert len(experiment.task_ids) == 1
    task = core_store.get(experiment.task_ids[0])
    bundle = core_store.get(task.evidence_bundle_id)
    history = [core_store.get(identity) for identity in bundle.observation_ids]
    assert [observation.value for observation in history] == [1.8, 2.4, 2.8]
    assert schedule_experiment(core_store, experiment.id) == 1
    result = work_once(core_store, kinds=("forecast",))
    assert result.get("run_id"), result
    run = core_store.get(result["run_id"])
    assert len(run.distribution.points) == 201
    assert run.distribution.summary.median == 2.8
    resolution = resolve_target(core_store, experiment.target_version_ids[0])
    assert resolution is not None
    assert core_store.get(resolution.observation_id).value == 3.2
    assert (
        resolve_target(core_store, experiment.target_version_ids[0]).id == resolution.id
    )
    assessments = evaluate_experiment(core_store, experiment.id)
    assert len(assessments) == 1
    assert assessments[0].score.eligibility == "replay"
    assert assessments[0].score.crps is not None
    # Repeating scheduling never executes the baseline twice after a valid run.
    assert schedule_experiment(core_store, experiment.id) == 0


def test_failed_capture_commits_exchange_without_observation(core_store):
    result = capture_source(
        core_store,
        "statcan-cpi-yoy",
        fetch=lambda request: HttpResponse(b"broken source", request.url),
    )
    assert result.status == "failed"
    assert core_store.get(result.exchanges[0].id) == result.exchanges[0]
    assert core_store.committed_at(result.exchanges[0].id) is not None
    assert list(core_store.iter_records("observation")) == []


def test_replay_refuses_unknown_abs_historical_timing(core_store):
    def fetch(request):
        return HttpResponse(
            (FIXTURES / "international/abs_lfs_unemployment_rate.json").read_bytes(),
            request.url,
        )

    with pytest.raises(ValueError, match="authenticated target publication"):
        prepare_replay(core_store, "abs-labour-unemployment", fetch=fetch)


def test_resolution_rechecks_validation_version(core_store):
    experiment = prepare_replay(core_store, fetch=statcan_fixture)
    target = core_store.get(experiment.target_version_ids[0])
    resolution = resolve_target(core_store, target.id)
    observation = core_store.get(resolution.observation_id)
    assert not validate_resolution(
        core_store,
        resolution.model_copy(update={"validation_version": "caller-asserted"}),
        target,
        observation,
    )
