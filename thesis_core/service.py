"""Application queries over the core. HTTP callers use only the read-only paths."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from functools import lru_cache
from statistics import mean
from typing import TYPE_CHECKING, Any

from .artifacts import ArtifactError
from .contracts import (
    RECORD_TYPES,
    Attempt,
    AttemptResult,
    EvaluationTask,
    Experiment,
    ForecastRun,
    ObservationVintage,
    Resolution,
    ScientificRecord,
    SourceExchange,
    SourceSeries,
    TargetVersion,
)
from .evaluation import (
    EvaluationContext,
    OutcomeAvailabilityUnknown,
    RunAssessment,
    assess_run,
    build_leaderboard,
    record_available_as_of,
    validate_experiment,
)

if TYPE_CHECKING:
    from .store import Store


class ExperimentNotFoundError(ValueError):
    """A query does not name an experiment, rather than a corrupt experiment."""


def context_for_store(store: Store) -> EvaluationContext:
    """Only adapter replay, raw receipt verification and DB facts supply authority."""
    from .adapters.registry import (
        observation_availability,
        target_release_availability,
        validate_source,
    )
    from .publication import verify_proof
    from .resolution import validate_resolution

    records = {
        record.id: record
        for kind in RECORD_TYPES
        for record in store.iter_records(kind)
    }
    exchanges = {
        key: record
        for key, record in records.items()
        if isinstance(record, SourceExchange)
    }

    @lru_cache(maxsize=None)
    def source_for_id(source_series_id: str) -> SourceSeries:
        source = records.get(source_series_id)
        if not isinstance(source, SourceSeries):
            raise ValueError("missing registered source")
        validate_source(source)
        return source

    @lru_cache(maxsize=None)
    def availability_for_id(record_id: str):
        record = records[record_id]
        if isinstance(record, ObservationVintage):
            return observation_availability(
                record,
                source_for_id(record.source_series_id),
                exchanges,
                store.artifacts,
            )
        if isinstance(record, SourceSeries):
            source_for_id(record.id)
        return None

    @lru_cache(maxsize=None)
    def target_availability_for_id(target_id: str):
        target = records[target_id]
        return target_release_availability(
            target, source_for_id(target.source_series_id), store.artifacts
        )

    @lru_cache(maxsize=None)
    def resolution_valid_for_ids(resolution_id, target_id, observation_id):
        try:
            return validate_resolution(
                store,
                records[resolution_id],
                records[target_id],
                records[observation_id],
            )
        except (ValueError, KeyError, OSError, ArtifactError):
            return False

    @lru_cache(maxsize=None)
    def artifact_exists(digest):
        try:
            store.artifacts.read_bytes(digest)
            return True
        except (ValueError, KeyError, OSError, ArtifactError):
            return False

    @lru_cache(maxsize=None)
    def reconciliation_valid_for_id(result_id: str) -> bool:
        result = records[result_id]
        events = store.attempt_events(result.attempt_id)
        matches = [event for event in events if event["event"] == "reconciled"]
        if len(matches) != 1 or matches[0]["result_id"] != result.id:
            return False
        previous = records.get(result.reconciles_result_id)
        # The current store commits valid run+finish atomically. Unknown attempts
        # therefore reconcile only to no_sealed_result, never an uploaded replacement.
        return (
            isinstance(previous, AttemptResult)
            and previous.outcome == "unknown"
            and previous.attempt_id == result.attempt_id
            and result.outcome == "failed"
            and result.reconciliation_method == "no_sealed_result"
        )

    @lru_cache(maxsize=None)
    def publication_for_id(proof_id: str):
        return verify_proof(store, records[proof_id])

    # These caches live only as long as this graph snapshot. Every HTTP request
    # builds a new context and reopens source bytes, receipts and acknowledgements.
    return EvaluationContext(
        records=records,
        committed_at=lru_cache(maxsize=None)(store.committed_at),
        publication=lambda proof: publication_for_id(proof.id),
        availability=lambda record: availability_for_id(record.id),
        target_availability=lambda target: target_availability_for_id(target.id),
        artifact_exists=artifact_exists,
        resolution_valid=lambda resolution, target, observation: (
            resolution_valid_for_ids(resolution.id, target.id, observation.id)
        ),
        reconciliation_valid=lambda result: reconciliation_valid_for_id(result.id),
    )


def evaluate_experiment(
    store: Store,
    experiment_id: str,
    *,
    persist: bool = True,
    _context: EvaluationContext | None = None,
) -> list[RunAssessment]:
    context = _context if _context is not None else context_for_store(store)
    experiment = context.records.get(experiment_id)
    if not isinstance(experiment, Experiment):
        raise ExperimentNotFoundError("unknown experiment")
    assessments = []
    for record in context.records.values():
        if not isinstance(record, ForecastRun):
            continue
        attempt = context.records.get(record.attempt_id)
        if (
            not isinstance(attempt, Attempt)
            or attempt.task_id not in experiment.task_ids
        ):
            continue
        task = context.records.get(attempt.task_id)
        if not isinstance(task, EvaluationTask):
            continue
        resolutions = [
            r
            for r in context.records.values()
            if isinstance(r, Resolution)
            and r.target_version_id == task.target_version_id
        ]
        for resolution in sorted(resolutions, key=lambda r: r.id):
            assessment = assess_run(record, resolution, experiment, context)
            if persist:
                store.put(assessment.score)
            assessments.append(assessment)
    return assessments


def record_view(record: ScientificRecord, store: Store | None = None) -> dict[str, Any]:
    payload = record.canonical_payload() | {"id": record.id}
    if store is not None:
        acknowledged = store.committed_at(record.id)
        payload["committed_at"] = acknowledged.isoformat() if acknowledged else None
    return payload


def pending_targets(store: Store) -> list[dict[str, Any]]:
    context = context_for_store(store)
    resolved = set()
    for record in context.records.values():
        if isinstance(record, Resolution):
            target = context.records.get(record.target_version_id)
            observation = context.records.get(record.observation_id)
            if (
                isinstance(target, TargetVersion)
                and isinstance(observation, ObservationVintage)
                and context.resolution_valid(record, target, observation)
            ):
                resolved.add(target.id)
    return [
        record_view(record, store)
        for record in context.records.values()
        if isinstance(record, TargetVersion) and record.id not in resolved
    ]


def _experiments(store: Store, experiment_id: str | None):
    if experiment_id is not None:
        experiment = store.get(experiment_id)
        if not isinstance(experiment, Experiment):
            raise ExperimentNotFoundError("unknown experiment")
        return [experiment]
    return list(store.iter_records(kind="experiment"))


def reward_rows(
    store: Store, experiment_id: str | None = None, as_of: datetime | None = None
) -> list[dict[str, Any]]:
    """Reverify current evidence; never trust a previously eligible score row."""
    context = context_for_store(store)
    output = []
    for experiment in _experiments(store, experiment_id):
        for assessment in evaluate_experiment(
            store, experiment.id, persist=False, _context=context
        ):
            score = assessment.score
            if as_of is not None and not record_available_as_of(score, as_of, context):
                continue
            run = context.records[score.run_id]
            attempt = context.records[run.attempt_id]
            task = context.records[attempt.task_id]
            cutoff = assessment.declared_information_cutoff
            freeze = assessment.effective_information_boundary
            frozen_text = freeze.isoformat() if freeze else None
            row = score.canonical_payload() | {
                "id": score.id,
                "mode": experiment.mode,
                "forecaster_id": task.forecaster_version_id,
                "target_version_id": task.target_version_id,
                "task_id": task.id,
                "declared_information_cutoff": cutoff.isoformat() if cutoff else None,
                "effective_information_boundary": frozen_text,
                "evidence_frozen_at": frozen_text,
                # Assessment details are operator diagnostics and may contain
                # filesystem or transport error text. Public rows use only the
                # closed scientific eligibility vocabulary.
                "exclusions": (
                    []
                    if assessment.eligibility == "eligible"
                    else [assessment.eligibility]
                ),
            }
            output.append(row)
    return output


def _attempt_summary(
    experiment: Experiment, forecaster_id: str, context: EvaluationContext
) -> dict[str, Any]:
    task_ids = {
        task.id
        for task in context.records.values()
        if isinstance(task, EvaluationTask)
        and task.id in experiment.task_ids
        and task.forecaster_version_id == forecaster_id
    }
    counts = dict.fromkeys(
        (
            "total",
            "succeeded",
            "failed",
            "unknown",
            "pending",
            "reconciled",
            "unknown_history",
        ),
        0,
    )
    latencies = []
    for attempt in context.records.values():
        if not isinstance(attempt, Attempt) or attempt.task_id not in task_ids:
            continue
        counts["total"] += 1
        results = [
            result
            for result in context.records.values()
            if isinstance(result, AttemptResult) and result.attempt_id == attempt.id
        ]
        original = [result for result in results if result.reconciles_result_id is None]
        revised = [
            result for result in results if result.reconciles_result_id is not None
        ]
        if not original and not revised:
            counts["pending"] += 1
            continue
        if any(result.outcome == "unknown" for result in original):
            counts["unknown_history"] += 1
        if len(original) != 1 or len(revised) > 1:
            counts["unknown"] += 1
            continue
        result = original[0]
        if revised:
            replacement = revised[0]
            if (
                result.outcome != "unknown"
                or replacement.reconciles_result_id != result.id
                or not context.reconciliation_valid(replacement)
            ):
                counts["unknown"] += 1
                continue
            counts["reconciled"] += 1
            result = replacement
        counts[result.outcome] += 1
        # Reconciliation time is not observed provider execution duration.
        if not revised and result.completed_at is not None:
            elapsed = (result.completed_at - attempt.started_at).total_seconds()
            if elapsed >= 0:
                latencies.append(elapsed)
    return {
        "attempt_counts": counts,
        "mean_latency_seconds": mean(latencies) if latencies else None,
    }


def leaderboard_rows(
    store: Store, experiment_id: str | None = None
) -> list[dict[str, Any]]:
    context = context_for_store(store)
    output = []
    for experiment in _experiments(store, experiment_id):
        assessments = evaluate_experiment(
            store, experiment.id, persist=False, _context=context
        )
        try:
            validate_experiment(experiment, context)
            rows = build_leaderboard(
                experiment, [assessment.score for assessment in assessments], context
            )
        except (ValueError, KeyError, OSError, ArtifactError) as exc:
            rows = [
                {
                    "forecaster_id": fid,
                    "rank": None,
                    "rank_eligible": False,
                    "paired_coverage": 0,
                    "targets": len(experiment.target_version_ids),
                    "mean_normalized_crps": None,
                    "mode": experiment.mode,
                    "exclusions": [
                        "outcome_availability_unknown"
                        if isinstance(exc, OutcomeAvailabilityUnknown)
                        else "invalid_contract"
                    ],
                }
                for fid in experiment.forecaster_version_ids
            ]
        for row in rows:
            fid = row["forecaster_id"]
            statuses = Counter()
            for assessment in assessments:
                run = context.records[assessment.score.run_id]
                task = context.records[context.records[run.attempt_id].task_id]
                if (
                    task.forecaster_version_id == fid
                    and assessment.eligibility != "eligible"
                ):
                    statuses[assessment.eligibility] += 1
            row.update(
                experiment_id=experiment.id,
                coverage={"eligible": row["paired_coverage"], "total": row["targets"]},
            )
            row.setdefault("exclusions", dict(statuses))
            row["evidence_frozen_at"] = row.get("effective_information_boundary")
            row.update(_attempt_summary(experiment, fid, context))
            output.append(row)
    return output
