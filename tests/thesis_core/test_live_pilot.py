"""Real PostgreSQL, immutable pilot contracts, local clocks and fixture sources."""

import json
import os
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from thesis_core.adapters.registry import get_source, release_evidence_from_bytes
from thesis_core.adapters.timing import (
    STATCAN_CPI_PORTAL_URL,
    statcan_cpi_next_release,
)
from thesis_core.contracts import Experiment, ScoreRecord, parse_record
from thesis_core.evaluation import assess_run, outcome_boundary, validate_experiment
from thesis_core.execution import execute_forecast
from thesis_core.live import PilotDeadlineError, validate_live_dispatch
from thesis_core.pilot import prepare_live_pilot
from thesis_core.resolution import capture_source, resolve_target
from thesis_core.service import (
    context_for_store,
    evaluate_experiment,
    leaderboard_rows,
    reward_rows,
)
from thesis_core.worker import schedule_experiment, work_once

from .live_fixtures import PORTAL, future_fetch, future_outcome, future_period
from .test_tsa import authorities, pinned_tsa  # noqa: F401


def test_official_cpi_portal_date_and_toronto_boundary(core_store):
    source = get_source("statcan-cpi-yoy")
    release = release_evidence_from_bytes(
        source,
        "2026-08",
        PORTAL.read_bytes(),
        STATCAN_CPI_PORTAL_URL,
        core_store.artifacts,
    )
    from thesis_core.evaluation import source_availability_interval

    assert release.raw_value == "2026-09-14"
    assert release.timezone == "America/Toronto"
    boundary = source_availability_interval(release.raw_value, release.timezone)
    assert boundary.lower.isoformat() == "2026-09-14T04:00:00+00:00"
    assert boundary.upper.isoformat() == "2026-09-15T04:00:00+00:00"
    with pytest.raises(ValueError, match="exact official"):
        release_evidence_from_bytes(
            source,
            "2026-08",
            PORTAL.read_bytes(),
            STATCAN_CPI_PORTAL_URL + "?copy=1",
            core_store.artifacts,
        )


@pytest.mark.parametrize(
    "old,new,period",
    [
        (b"Monday, September 14", b"Tuesday, September 14", "2026-08"),
        (b"(July 2026)", b"(August 2026)", "2026-08"),
        (b"(July 2026)", b"(July 2025)", "2026-08"),
        (b"2026-08-17", b"2025-08-17", "2026-08"),
        (b"for August", b"for September", "2026-08"),
        (b"Next release", b"Archived release", "2026-08"),
        (b"Consumer Price Index<span", b"Annual Average CPI<span", "2026-08"),
        (b"(July 2026)", b"(December 2026)", "2027-01"),
        (b"(July 2026)", b"(November 2026)", "2026-12"),
    ],
)
def test_portal_refuses_ambiguous_stale_or_conflicting_claim(old, new, period):
    with pytest.raises(ValueError):
        statcan_cpi_next_release(PORTAL.read_bytes().replace(old, new), period)


def test_portal_rejects_duplicate_notice_and_accepts_scoped_markup_variation():
    raw = PORTAL.read_bytes()
    duplicate = raw + (
        b"<h3>Next release</h3><p>The CPI for August will be released on "
        b"Monday, September 14.</p>"
    )
    with pytest.raises(ValueError, match="exactly one"):
        statcan_cpi_next_release(duplicate, "2026-08")
    varied = raw.replace(b"The CPI for August", b"The <strong>CPI</strong> for August")
    assert statcan_cpi_next_release(varied, "2026-08") == "2026-09-14"


def prepared(core_store, argv=None):
    return prepare_live_pilot(
        core_store, future_period(), fetch=future_fetch, argv=argv
    )


def resolve_fixture(core_store, experiment, monkeypatch):
    result = capture_source(
        core_store,
        "statcan-cpi-yoy",
        measurement_period=future_period(),
        fetch=future_outcome,
    )
    assert result.status == "captured"
    # A synthetic future outcome needs a synthetic post-release read clock.
    # Production acknowledgements remain untouched; only this store instance's
    # read seam advances for the new outcome, never the preregistration/run.
    from thesis_core.evaluation import source_availability_interval

    original = core_store.committed_at
    overrides = {
        observation.id: source_availability_interval(
            observation.publication_evidence.raw_value,
            observation.publication_evidence.timezone,
        ).upper
        + timedelta(seconds=1)
        for observation in result.observations
    }
    monkeypatch.setattr(
        core_store, "committed_at", lambda key: overrides.get(key) or original(key)
    )
    return resolve_target(core_store, experiment.target_version_ids[0])


def test_live_baseline_pending_then_resolution_stays_unranked(core_store, monkeypatch):
    experiment = prepared(core_store)
    assert experiment.mode == "live_pilot"
    assert experiment.ranking_policy == "unranked_live_pilot_v1"
    assert list(core_store.iter_records("attempt")) == []
    assert resolve_target(core_store, experiment.target_version_ids[0]) is None
    assert schedule_experiment(core_store, experiment.id) == 1
    result = work_once(core_store, kinds=("forecast",))
    assert result["run_id"], result
    resolution = resolve_fixture(core_store, experiment, monkeypatch)
    assert (
        resolve_target(core_store, experiment.target_version_ids[0]).id == resolution.id
    )
    assessments = evaluate_experiment(core_store, experiment.id)
    assert len(assessments) == 1
    score = assessments[0].score
    assert score.eligibility == "live_pilot"
    assert (
        score.crps is not None
        and score.pit is not None
        and score.normalized_crps is not None
    )
    assert score.reward is None
    assert reward_rows(core_store, experiment.id)[0]["reward"] is None
    rows = leaderboard_rows(core_store, experiment.id)
    assert all(row["rank"] is None and not row["rank_eligible"] for row in rows)
    assert schedule_experiment(core_store, experiment.id) == 0
    with pytest.raises(ValueError, match="training reward"):
        ScoreRecord(**(score.model_dump() | {"reward": 1.0}))


def test_mode_policy_pairs_preserve_existing_defaults(core_store):
    experiment = prepared(core_store)
    payload = experiment.model_dump()
    with pytest.raises(ValueError, match="unranked"):
        Experiment(**(payload | {"mode": "prospective"}))
    with pytest.raises(ValueError, match="unranked"):
        Experiment(
            **(payload | {"ranking_policy": "complete_paired_normalized_crps_v1"})
        )
    old = Experiment(
        **(
            payload
            | {"mode": "replay", "ranking_policy": "complete_paired_normalized_crps_v1"}
        )
    )
    assert parse_record(old.kind, old.canonical_payload()).id == old.id


def test_pilot_registration_rejects_late_dependency_ack(core_store):
    experiment = prepared(core_store)
    task = core_store.get(experiment.task_ids[0])
    context = context_for_store(core_store)
    for identity in (
        experiment.id,
        experiment.normalization_ids[0],
        task.evidence_bundle_id,
    ):
        context_late = replace(
            context,
            committed_at=lambda key: (
                task.information_cutoff
                if key == identity
                else context.committed_at(key)
            ),
        )
        with pytest.raises(ValueError, match="frozen|boundary"):
            validate_experiment(experiment, context_late)


def test_live_refuses_proof_missing_experiment_and_late_queue(core_store):
    experiment = prepared(core_store)
    task = core_store.get(experiment.task_ids[0])
    with pytest.raises(ValueError, match="cohort proof"):
        schedule_experiment(core_store, experiment.id, cohort_proof_id="a" * 64)
    with pytest.raises(PilotDeadlineError):
        validate_live_dispatch(
            core_store, task, experiment.id, now=task.information_cutoff
        )
    core_store.enqueue("forecast", task.id, {}, idempotency_key="direct-no-experiment")
    core_store.deliver_outbox()
    claim = core_store.claim("direct", ("forecast",))
    with pytest.raises(ValueError, match="registered experiment"):
        execute_forecast(core_store, claim)
    assert list(core_store.iter_records("attempt")) == []


def test_pilot_late_sealing_has_closed_reason(core_store, monkeypatch):
    experiment = prepared(core_store)
    schedule_experiment(core_store, experiment.id)
    result = work_once(core_store, kinds=("forecast",))
    run = core_store.get(result["run_id"])
    resolution = resolve_fixture(core_store, experiment, monkeypatch)
    task = core_store.get(experiment.task_ids[0])
    context = context_for_store(core_store)
    late = replace(
        context,
        committed_at=lambda key: (
            task.information_cutoff if key == run.id else context.committed_at(key)
        ),
    )
    assert (
        assess_run(run, resolution, experiment, late).score.eligibility
        == "late_pilot_execution"
    )
    attempt = core_store.get(run.attempt_id)
    registration_late = replace(
        context,
        committed_at=lambda key: (
            attempt.started_at if key == experiment.id else context.committed_at(key)
        ),
    )
    assert (
        assess_run(run, resolution, experiment, registration_late).score.eligibility
        == "late_pilot_execution"
    )
    boundary = outcome_boundary(core_store.get(task.target_version_id), context)
    assert boundary.hour == 4  # The later WDS 08:30 cannot weaken the date-only notice.


def test_pilot_deadline_crossing_after_allocation_archives_marker(
    core_store, monkeypatch
):
    experiment = prepared(core_store)
    schedule_experiment(core_store, experiment.id)
    import thesis_core.live as live

    original = live.validate_live_dispatch
    budget_calls = []

    def delayed(*args, **kwargs):
        if kwargs.get("budget_seconds"):
            budget_calls.append(kwargs)
            raise PilotDeadlineError("PILOT_DEADLINE_BEFORE_SPAWN")
        return original(*args, **kwargs)

    monkeypatch.setattr(live, "validate_live_dispatch", delayed)
    result = work_once(core_store, kinds=("forecast",))
    assert result["run_id"] is None
    assert budget_calls
    failures = list(core_store.iter_records("attempt_result"))
    assert len(failures) == 1 and failures[0].outcome == "failed"
    assert (
        core_store.artifacts.read_bytes(failures[0].stderr_hash)
        == b"PILOT_DEADLINE_BEFORE_SPAWN\n"
    )


def test_short_remaining_time_seals_actual_effective_budget(core_store, monkeypatch):
    experiment = prepared(core_store)
    task = core_store.get(experiment.task_ids[0])
    schedule_experiment(core_store, experiment.id)
    import thesis_core.execution as execution

    sampled = task.information_cutoff - timedelta(seconds=11)
    original = execution._database_now
    calls = []

    def clock(store):
        calls.append(1)
        return sampled if len(calls) == 1 else original(store)

    monkeypatch.setattr(execution, "_database_now", clock)
    result = work_once(core_store, kinds=("forecast",), timeout_seconds=120)
    assert result["run_id"], result
    attempt = next(core_store.iter_records("attempt"))
    command = json.loads(core_store.artifacts.read_bytes(attempt.command_hash))
    assert command["timeoutSeconds"] == 10.0


def test_real_path_wrapper_paired_pilot_and_changed_bytes_refusal(
    core_store, tmp_path, monkeypatch
):
    wrapper = tmp_path / "fixture-forecaster"
    wrapper.write_text(
        "#!/usr/bin/env python3\nimport json,sys\n"
        "from thesis_core.execution import persistence_distribution\n"
        "from thesis_core.contracts import ObservationVintage\n"
        "from pathlib import Path\n"
        "rows=json.loads(Path('evidence/observations.json').read_text())\n"
        "obs=[ObservationVintage.model_validate_json(json.dumps(r)) for r in rows]\n"
        "distribution=persistence_distribution(obs).model_dump(mode='json',by_alias=True)\n"
        "sys.stdout.write(json.dumps({'distribution':distribution}))\n"
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv(
        "PATH", f"{tmp_path}:{Path(sys.executable).parent}:{os.environ['PATH']}"
    )
    experiment = prepared(core_store, argv=("fixture-forecaster",))
    assert schedule_experiment(core_store, experiment.id) == 2
    first = work_once(core_store, kinds=("forecast",))
    second = work_once(core_store, kinds=("forecast",))
    assert first["run_id"] and second["run_id"], (first, second)
    resolve_fixture(core_store, experiment, monkeypatch)
    scores = evaluate_experiment(core_store, experiment.id)
    assert len(scores) == 2 and all(a.score.eligibility == "live_pilot" for a in scores)
    # The pin verifies actual PATH selection, not just the named executable.
    from thesis_core.live import verify_wrapper

    model = next(
        core_store.get(fid)
        for fid in experiment.forecaster_version_ids
        if core_store.get(fid).execution_policy == "operator_subprocess"
    )
    wrapper.write_text(wrapper.read_text() + "\n# changed\n")
    with pytest.raises(ValueError, match="frozen wrapper"):
        verify_wrapper(core_store, model, ("fixture-forecaster",))


def test_valid_accuracy_receipt_cannot_promote_pilot(
    core_store,
    pinned_tsa,  # noqa: F811
    monkeypatch,
):
    from thesis_core import publication, tsa

    experiment = prepared(core_store)
    schedule_experiment(core_store, experiment.id)
    run = core_store.get(work_once(core_store, kinds=("forecast",))["run_id"])
    manifest = publication.create_manifest(core_store, experiment.id, run_id=run.id)
    monkeypatch.setattr(
        tsa, "post_timestamp_query", pinned_tsa.transport(accuracy="millisecs:500")
    )
    proof = publication.publish_manifest(
        core_store, manifest.id, anchor_id=pinned_tsa.anchor_id
    )
    verified = publication.verify_proof(core_store, proof)
    assert verified is not None and verified.interval is not None
    resolve_fixture(core_store, experiment, monkeypatch)
    score = evaluate_experiment(core_store, experiment.id)[0].score
    assert score.eligibility == "live_pilot" and score.reward is None
    assert all(
        not row["rank_eligible"] for row in leaderboard_rows(core_store, experiment.id)
    )


def test_live_observation_cannot_take_replay_late_capture_exception(core_store):
    from thesis_core.evidence import observation_eligible

    experiment = prepared(core_store)
    task = core_store.get(experiment.task_ids[0])
    bundle = core_store.get(task.evidence_bundle_id)
    observation = core_store.get(bundle.observation_ids[0])
    source = core_store.get(bundle.source_series_id)
    exchanges = {key: core_store.get(key) for key in observation.source_exchange_ids}
    for delayed_id in (source.id, observation.id, *observation.source_exchange_ids):

        def ack(identity):
            return (
                task.information_cutoff + timedelta(seconds=1)
                if identity == delayed_id
                else core_store.committed_at(identity)
            )

        kwargs = dict(information_cutoff=task.information_cutoff, committed_at=ack)
        assert not observation_eligible(
            observation,
            source,
            exchanges,
            core_store.artifacts,
            mode="live_pilot",
            **kwargs,
        )
        assert observation_eligible(
            observation,
            source,
            exchanges,
            core_store.artifacts,
            mode="replay",
            **kwargs,
        )


def test_delayed_worker_refuses_before_allocating_attempt(core_store, monkeypatch):
    experiment = prepared(core_store)
    task = core_store.get(experiment.task_ids[0])
    schedule_experiment(core_store, experiment.id)
    monkeypatch.setattr(
        "thesis_core.live.database_now", lambda _: task.information_cutoff
    )
    result = work_once(core_store, kinds=("forecast",))
    assert result["status"] == "failed"
    assert list(core_store.iter_records("attempt")) == []


def test_pre_spawn_deadline_refusal_never_launches_operator(
    core_store, tmp_path, monkeypatch
):
    wrapper = tmp_path / "refusal-fixture"
    wrapper.write_text(
        "#!/usr/bin/env python3\nraise AssertionError('must not launch')\n"
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    experiment = prepared(core_store, argv=("refusal-fixture",))
    task = next(
        core_store.get(tid)
        for tid in experiment.task_ids
        if core_store.get(tid).execution_policy == "operator_subprocess"
    )
    core_store.enqueue(
        "forecast",
        task.id,
        {"experiment_id": experiment.id},
        idempotency_key="prespawn-model",
    )
    import thesis_core.live as live

    original = live.validate_live_dispatch
    calls = []

    def delayed(*args, **kwargs):
        if kwargs.get("budget_seconds"):
            calls.append(1)
            if len(calls) == 2:
                raise PilotDeadlineError("PILOT_DEADLINE_BEFORE_SPAWN")
        return original(*args, **kwargs)

    monkeypatch.setattr(live, "validate_live_dispatch", delayed)
    monkeypatch.setattr(
        "thesis_core.execution.subprocess.Popen",
        lambda *a, **k: pytest.fail("operator launched after boundary"),
    )
    result = work_once(core_store, kinds=("forecast",))
    assert result["run_id"] is None and len(calls) == 2
    failure = next(core_store.iter_records("attempt_result"))
    assert (
        core_store.artifacts.read_bytes(failure.stderr_hash)
        == b"PILOT_DEADLINE_BEFORE_SPAWN\n"
    )


@pytest.mark.parametrize(
    "argv",
    [("/tmp/private-wrapper",), ("codex", "--file=/tmp/private"), ("../wrapper",)],
)
def test_live_wrapper_refuses_local_argv_paths(core_store, argv):
    with pytest.raises(ValueError, match="PATH|absolute paths"):
        prepared(core_store, argv=argv)
    assert list(core_store.iter_records("experiment")) == []


def test_old_source_ids_remain_exact():
    expected = {
        "abs-labour-unemployment": (
            "fe1828b99b30db4b1947f3e4062e38bb11c34e3fbf3e4f9e18746240656a7997"
        ),
        "statcan-cpi-yoy": (
            "3a1218540e534284f32c2977d97bffa785fa00fcfb5af1195ca95fd5dc72103b"
        ),
        "bea-fixed-investment": (
            "245368b802b7442a249c79246dd3ff53f56bdce71c66b3ec96c0c0a1e9459e36"
        ),
    }
    assert {adapter: get_source(adapter).id for adapter in expected} == expected


def test_december_notice_cannot_guess_following_year_release():
    raw = PORTAL.read_bytes().replace(b"(July 2026)", b"(November 2026)")
    raw = raw.replace(b"2026-08-17", b"2026-12-17").replace(
        b"The CPI for August will be released on Monday, September 14.",
        b"The CPI for December will be released on Thursday, January 14.",
    )
    with pytest.raises(ValueError, match="date/weekday|year"):
        statcan_cpi_next_release(raw, "2026-12")
