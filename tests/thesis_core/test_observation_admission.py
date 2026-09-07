"""Native observation admission and prospective outcome-boundary refusals."""

from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from thesis_core import cli, publication
from thesis_core.adapters import capture, release_evidence_from_bytes
from thesis_core.adapters.timing import BEA_CALENDAR_URL
from thesis_core.artifacts import ArtifactCorrupt
from thesis_core.contracts import (
    EvaluationTask,
    Experiment,
    TargetVersion,
    parse_record,
)
from thesis_core.evaluation import (
    OutcomeAvailabilityUnknown,
    assess_run,
    outcome_boundary,
    validate_experiment,
)
from thesis_core.evidence import build_evidence_bundle
from thesis_core.service import context_for_store
from thesis_core.worker import schedule_experiment

from .factories import at, make_forecaster
from .test_adapters_evidence import captured
from .test_domain import _prospective
from .test_pilot import statcan_fixture


@pytest.mark.parametrize(
    "tamper", ["value", "publication_evidence", "source_kind", "exchange_kind"]
)
def test_native_observation_replays_before_scientific_commit(
    core_store, tmp_path, tamper
):
    result = capture(
        "statcan-cpi-yoy",
        core_store.artifacts,
        fetch=statcan_fixture,
        mode="replay",
    )
    assert result.status == "captured", result.errors
    with core_store.transaction() as transaction:
        for record in (result.source, *result.exchanges):
            transaction.put(record)
    genuine = result.observations[-1]
    payload = genuine.canonical_payload()
    if tamper == "value":
        payload["value"] += 1.0
    elif tamper == "publication_evidence":
        payload["publication_evidence"]["raw_value"] = "2020-01-01T08:30"
    elif tamper == "source_kind":
        payload["source_series_id"] = result.exchanges[0].id
    else:
        payload["source_exchange_ids"] = [result.source.id]
    malformed = parse_record("observation", payload)
    path = tmp_path / "observation.json"
    path.write_bytes(malformed.canonical_bytes())
    args = cli.parser().parse_args(["register", str(path), "--kind", "observation"])
    records_before = {record.id for record in core_store.iter_records()}
    with pytest.raises(ValueError, match="raw parse|wrong kind"):
        cli._dispatch(args, core_store)
    assert {record.id for record in core_store.iter_records()} == records_before
    assert not core_store.artifacts.exists(malformed.id)
    assert core_store.committed_at(malformed.id) is None

    # A valid new observation still enters through exactly the same CLI path.
    path.write_bytes(genuine.canonical_bytes())
    assert cli._dispatch(args, core_store) == {"id": genuine.id}
    assert core_store.get(genuine.id) == genuine
    assert core_store.committed_at(genuine.id) is not None


def test_real_prospective_cohort_refuses_a_nonreplaying_peer(core_store):
    # Use the real BEA adapter, archived fixtures and PostgreSQL acknowledgements.
    # Move the fixture calendar's release into the future to keep this timing
    # regression independent of the day the suite runs; no source is fetched.
    result = captured(core_store.artifacts, "bea-fixed-investment")
    assert result.status == "captured", result.errors
    with core_store.transaction() as transaction:
        for record in (result.source, *result.exchanges, *result.observations):
            transaction.put(record)
    release = (
        core_store.health()["database_time"].astimezone(timezone.utc)
        + timedelta(days=30)
    ).replace(microsecond=0)
    raw = (
        Path(__file__).parents[1]
        / "fixtures/thesis_core/bea-release-schedule-2026-09-04.ics"
    ).read_bytes()
    assert b"DTSTART:20261029T123000Z" in raw
    raw = raw.replace(
        b"DTSTART:20261029T123000Z",
        release.strftime("DTSTART:%Y%m%dT%H%M%SZ").encode(),
    )
    proof = release_evidence_from_bytes(
        result.source, "2026-Q3", raw, BEA_CALENDAR_URL, core_store.artifacts
    )
    cutoff = release - timedelta(minutes=10)
    target = TargetVersion(
        target_id="prospective-outcome-boundary-regression",
        source_series_id=result.source.id,
        measurement_period="2026-Q3",
        unit=result.source.unit,
        resolution_policy="fixed_vintage",
        vintage_date=release.date().isoformat(),
        resolution_rule="Exact registered BEA table and vintage",
        submission_deadline=release - timedelta(minutes=5),
        release_evidence=proof,
    )
    bundle = build_evidence_bundle(
        result.source,
        result.observations,
        {exchange.id: exchange for exchange in result.exchanges},
        core_store.artifacts,
        information_cutoff=cutoff,
        mode="prospective",
        committed_at=core_store.committed_at,
    )
    prompt = core_store.artifacts.put_bytes(b"Prospective test baseline policy")
    forecaster = make_forecaster(
        baseline=True,
        prompt_template_hash=prompt,
        system_prompt_hash=prompt,
        tool_policy_hash=prompt,
    )
    task = EvaluationTask(
        target_version_id=target.id,
        forecaster_version_id=forecaster.id,
        evidence_bundle_id=bundle.id,
        information_cutoff=cutoff,
        submission_deadline=target.submission_deadline,
        execution_policy="baseline",
        mode="prospective",
    )
    experiment = Experiment(
        task_ids=(task.id,),
        target_version_ids=(target.id,),
        forecaster_version_ids=(forecaster.id,),
        baseline_forecaster_id=forecaster.id,
        registration_deadline=cutoff - timedelta(minutes=1),
        mode="prospective",
    )
    with core_store.transaction() as transaction:
        for record in (target, bundle, forecaster, task, experiment):
            transaction.put(record)
    context = context_for_store(core_store)
    assert outcome_boundary(target, context) == release
    assert validate_experiment(experiment, context) == (task,)
    publication.create_manifest(core_store, experiment.id)

    # Simulate a malformed observation already in immutable storage. Its old
    # publication claim cannot be ignored in favor of the later valid calendar.
    malformed = parse_record(
        "observation",
        result.observations[0].canonical_payload()
        | {"measurement_period": target.measurement_period, "value": -1.0},
    )
    core_store.put(malformed)
    context = context_for_store(core_store)
    assert context.target_availability(target).lower == release
    for operation in (
        lambda: outcome_boundary(target, context),
        lambda: validate_experiment(experiment, context),
        lambda: publication.create_manifest(core_store, experiment.id),
        lambda: schedule_experiment(core_store, experiment.id),
    ):
        with pytest.raises(
            OutcomeAvailabilityUnknown, match="^outcome_availability_unknown$"
        ) as error:
            operation()
        assert isinstance(error.value.__cause__, ValueError)
    assert core_store.jobs() == ()


@pytest.mark.parametrize(
    "failure",
    ["observation", "artifact", "calendar", "contradictory_time", "missing_time"],
)
def test_prospective_assessment_preserves_outcome_availability_reason(failure):
    graph, run, baseline, resolution, context, _ = _prospective()
    assert (
        assess_run(run, resolution, graph.experiment, context).eligibility == "eligible"
    )

    def unavailable(_):
        raise ValueError("adapter replay detail")

    if failure in {"observation", "artifact", "contradictory_time"}:
        genuine = graph.records[resolution.observation_id]
        peer = graph.add(
            parse_record("observation", genuine.canonical_payload() | {"value": -1.0}),
            at(502),
        )

        def availability(record):
            if record.id == peer.id:
                if failure == "artifact":
                    raise ArtifactCorrupt("private diagnostic path")
                if failure == "observation":
                    return unavailable(record)
                return graph.official[genuine.id]
            return graph.official.get(record.id)

        if failure == "contradictory_time":
            graph.acknowledgements[peer.id] = at(400)
        context = replace(context, availability=availability)
    elif failure == "calendar":
        context = replace(context, target_availability=unavailable)
    else:
        context = replace(
            context, target_availability=lambda _: None, availability=lambda _: None
        )
    with pytest.raises(OutcomeAvailabilityUnknown):
        validate_experiment(graph.experiment, context)
    for candidate in (run, baseline):
        assessment = assess_run(candidate, resolution, graph.experiment, context)
        assert assessment.eligibility == "outcome_availability_unknown"
        assert assessment.details == ("outcome_availability_unknown",)
        assert assessment.score.reward is None


def test_unrelated_prospective_contract_error_keeps_its_diagnostic():
    graph, run, _, resolution, context, _ = _prospective()
    graph.acknowledgements[graph.evidence.id] = graph.task.information_cutoff
    assessment = assess_run(run, resolution, graph.experiment, context)
    assert assessment.eligibility == "invalid_contract"
    assert assessment.details == ("bundle frozen after its prospective boundary",)
