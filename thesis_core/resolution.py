"""Application boundary for independent capture and exact vintage resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .adapters import capture
from .adapters.registry import validate_observation as validate_source_observation
from .adapters.registry import validate_resolution as validate_source_resolution
from .artifacts import ArtifactError
from .contracts import (
    AttemptResult,
    Experiment,
    ForecastRun,
    ObservationVintage,
    PublicationProof,
    Resolution,
    SourceExchange,
    SourceSeries,
    TargetVersion,
)
from .store import JobSpec

if TYPE_CHECKING:
    from .store import Store

VALIDATION_VERSION = "registered-source-vintage-v1"


def capture_source(store: Store, adapter_id: str, **kwargs):
    """Persist every captured exchange, including evidence from failed parsing."""
    result = capture(adapter_id, store.artifacts, **kwargs)
    with store.transaction() as transaction:
        transaction.put(result.source)
        for exchange in result.exchanges:
            transaction.put(exchange)
        for observation in result.observations:
            transaction.put(observation)
        for target in store.iter_records(
            "target_version", links={"source_series": result.source.id}
        ):
            jobs = _resolution_jobs(
                store,
                target,
                observations=result.observations,
                source=result.source,
                exchanges={exchange.id: exchange for exchange in result.exchanges},
            )
            jobs += _observation_evaluation_jobs(
                store,
                target,
                result.observations,
                source=result.source,
                exchanges={exchange.id: exchange for exchange in result.exchanges},
            )
            _enqueue(transaction, jobs)
    return result


def _enqueue(transaction, jobs):
    for job in jobs:
        transaction.enqueue(
            job.kind, job.subject_id, job.payload, idempotency_key=job.idempotency_key
        )


def _resolution_jobs(
    store, target, *, observations=None, source=None, exchanges=None
) -> tuple[JobSpec, ...]:
    """Queue only source-verified candidates; the worker rechecks all vintages."""
    if tuple(store.iter_records("resolution", links={"target_version": target.id})):
        return ()
    candidates = (
        observations
        if observations is not None
        else store.iter_records(
            "observation", links={"source_series": target.source_series_id}
        )
    )
    jobs = []
    for observation in candidates:
        if observation.measurement_period != target.measurement_period:
            continue
        try:
            matches = (
                validate_source_resolution(
                    target, observation, source, exchanges, store.artifacts
                )
                if source is not None
                else _matches(store, target, observation)
            )
        except (ValueError, KeyError, OSError, ArtifactError):
            matches = False
        if matches:
            jobs.append(
                JobSpec("resolve", target.id, f"resolve:{target.id}:{observation.id}")
            )
    return tuple(jobs)


def _observation_evaluation_jobs(
    store, target, observations, *, source=None, exchanges=None
) -> tuple[JobSpec, ...]:
    """New official evidence can change eligibility without replacing a resolution."""
    if not tuple(store.iter_records("resolution", links={"target_version": target.id})):
        return ()
    experiments = tuple(
        store.iter_records("experiment", links={"target_version": target.id})
    )
    jobs = []
    for observation in observations:
        if (
            observation.source_series_id != target.source_series_id
            or observation.measurement_period != target.measurement_period
        ):
            continue
        try:
            binding = (
                source if source is not None else store.get(target.source_series_id)
            )
            backing = (
                exchanges
                if exchanges is not None
                else {
                    identity: store.get(identity)
                    for identity in observation.source_exchange_ids
                }
            )
            validate_source_observation(observation, binding, backing, store.artifacts)
        except (ValueError, KeyError, OSError, ArtifactError):
            continue
        jobs.extend(
            JobSpec(
                "evaluate",
                experiment.id,
                f"evaluate:{experiment.id}:observation:{observation.id}",
            )
            for experiment in experiments
        )
    return tuple(jobs)


def scientific_followups(store: Store, record) -> tuple[JobSpec, ...]:
    """Reconstruct work from immutable trigger identities, without polling keys."""
    jobs = []
    if isinstance(record, TargetVersion):
        return _resolution_jobs(store, record)
    if isinstance(record, ObservationVintage):
        for target in store.iter_records(
            "target_version", links={"source_series": record.source_series_id}
        ):
            jobs.extend(_resolution_jobs(store, target, observations=(record,)))
            jobs.extend(_observation_evaluation_jobs(store, target, (record,)))
        return tuple(jobs)
    if isinstance(record, Experiment):
        experiments = (record,)
        for target_id in record.target_version_ids:
            jobs.extend(_resolution_jobs(store, store.get(target_id)))
    elif isinstance(record, Resolution):
        experiments = store.iter_records(
            "experiment", links={"target_version": record.target_version_id}
        )
    elif isinstance(record, (ForecastRun, AttemptResult)):
        task_id = store.get(record.attempt_id).task_id
        experiments = store.iter_records("experiment", links={"task": task_id})
    elif isinstance(record, PublicationProof):
        manifest = store.get(record.manifest_id)
        experiments = (store.get(manifest.experiment_id),)
    else:
        return ()
    for experiment in experiments:
        jobs.append(
            JobSpec(
                "evaluate",
                experiment.id,
                f"evaluate:{experiment.id}:{record.kind}:{record.id}",
            )
        )
    return tuple(jobs)


def repair_scientific_followups(store: Store) -> int:
    """Idempotently backfill work after registration, capture, or a missed edge."""
    count = 0
    for kind in (
        "target_version",
        "observation",
        "experiment",
        "resolution",
        "forecast_run",
        "publication_proof",
        "attempt_result",
    ):
        for record in store.iter_records(kind):
            if (
                isinstance(record, AttemptResult)
                and record.reconciles_result_id is None
            ):
                continue
            jobs = scientific_followups(store, record)
            if jobs:
                with store.transaction() as transaction:
                    _enqueue(transaction, jobs)
                count += len(jobs)
    return count


def _matches(store, target, observation):
    source = store.get(target.source_series_id)
    if not isinstance(source, SourceSeries):
        raise ValueError("target source record is missing or wrong kind")
    exchanges = {
        identity: store.get(identity) for identity in observation.source_exchange_ids
    }
    if any(not isinstance(exchange, SourceExchange) for exchange in exchanges.values()):
        raise ValueError("observation exchange record has wrong kind")
    return validate_source_resolution(
        target, observation, source, exchanges, store.artifacts
    )


def _validated_candidates(
    store: Store, target: TargetVersion, requested_id: str | None = None
) -> tuple[ObservationVintage, ...]:
    observations = list(
        store.iter_records(
            "observation", links={"source_series": target.source_series_id}
        )
    )
    if requested_id is not None and all(o.id != requested_id for o in observations):
        observations.append(store.get(requested_id))
    matches = []
    for observation in observations:
        if not isinstance(observation, ObservationVintage):
            raise ValueError("resolution observation has wrong kind")
        if observation.measurement_period != target.measurement_period:
            continue
        try:
            matches_contract = _matches(store, target, observation)
        except (ValueError, KeyError, OSError, ArtifactError):
            if observation.id == requested_id:
                raise
            continue
        if matches_contract and store.committed_at(observation.id) is not None:
            matches.append(observation)
    if len({observation.value for observation in matches}) > 1:
        raise ValueError(
            "conflicting values for the registered vintage "
            "require a narrower versioned policy"
        )
    if requested_id is not None and all(o.id != requested_id for o in matches):
        raise ValueError("requested observation does not match the registered vintage")
    return tuple(matches)


def validate_resolution(
    store: Store,
    resolution: Resolution,
    target: TargetVersion,
    observation: ObservationVintage,
) -> bool:
    if (
        resolution.target_version_id != target.id
        or resolution.observation_id != observation.id
        or resolution.resolution_policy != target.resolution_policy
        or resolution.validation_version != VALIDATION_VERSION
    ):
        return False
    # Recheck the entire acknowledged candidate set even for an already stored
    # resolution. A later ambiguity invalidates eligibility, never rewrites it.
    return any(
        candidate.id == observation.id
        for candidate in _validated_candidates(store, target, observation.id)
    )


def resolve_target(
    store: Store, target_id: str, observation_id: str | None = None
) -> Resolution | None:
    target = store.get(target_id)
    if not isinstance(target, TargetVersion):
        raise ValueError("resolution requires an exact TargetVersion identity")
    existing = tuple(
        store.iter_records("resolution", links={"target_version": target.id})
    )
    if existing:
        if len(existing) != 1:
            raise ValueError("target already has conflicting resolution records")
        resolution = existing[0]
        observation = store.get(resolution.observation_id)
        if observation_id is not None and observation_id != resolution.observation_id:
            raise ValueError("target already resolved to a different exact observation")
        if not validate_resolution(store, resolution, target, observation):
            raise ValueError("stored resolution failed source validation")
        with store.transaction() as transaction:
            _enqueue(transaction, scientific_followups(store, resolution))
        return resolution
    matches = _validated_candidates(store, target, observation_id)
    if not matches:
        return None
    # Repeated captures of identical values cannot select a favorable revision.
    # Use the earliest acknowledged equivalent capture, with ID as stable tie.
    observation = (
        next(o for o in matches if o.id == observation_id)
        if observation_id is not None
        else min(matches, key=lambda o: (store.committed_at(o.id), o.id))
    )
    with store.transaction() as transaction:
        transaction.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"resolve:{target.id}",)
        )
        existing = tuple(
            store.iter_records("resolution", links={"target_version": target.id})
        )
        if existing:
            resolution = existing[0]
            prior = store.get(resolution.observation_id)
            if observation_id is not None and observation_id != prior.id:
                raise ValueError(
                    "target already resolved to a different exact observation"
                )
            if not validate_resolution(store, resolution, target, prior):
                raise ValueError("stored resolution failed source validation")
        else:
            now = transaction.connection.execute(
                "SELECT clock_timestamp() AS now"
            ).fetchone()["now"]
            resolution = Resolution(
                target_version_id=target.id,
                observation_id=observation.id,
                resolution_policy=target.resolution_policy,
                validation_version=VALIDATION_VERSION,
                recorded_at=now,
            )
            transaction.put(resolution)
        _enqueue(transaction, scientific_followups(store, resolution))
    return resolution
