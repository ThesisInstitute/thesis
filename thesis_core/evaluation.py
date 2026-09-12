"""Pure evaluation over a validated graph and independently verified evidence.

Callbacks are trusted adapter boundaries, not flags deserialized from records.
The default context denies proof, resolution and reconciliation eligibility.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .artifacts import ArtifactError
from .contracts import (
    Attempt,
    AttemptResult,
    Eligibility,
    EvaluationTask,
    EvidenceBundle,
    Experiment,
    ForecasterVersion,
    ForecastRun,
    Mode,
    NormalizationRecord,
    ObservationVintage,
    PublicationManifest,
    PublicationProof,
    Resolution,
    ScientificRecord,
    ScoreRecord,
    SourceSeries,
    TargetVersion,
    record_artifact_hashes,
    record_links,
)
from .scoring import round_distribution_number, score_numeric_cdf_distribution

UTC = timezone.utc


class OutcomeAvailabilityUnknown(ValueError):  # noqa: N818 - typed eligibility reason
    """The earliest outcome boundary cannot be independently established."""

    def __init__(self) -> None:
        super().__init__("outcome_availability_unknown")


@dataclass(frozen=True)
class Availability:
    lower: datetime
    upper: datetime

    def __post_init__(self) -> None:
        if self.lower.tzinfo is None or self.upper.tzinfo is None:
            raise ValueError("availability bounds require timezones")
        if self.lower > self.upper:
            raise ValueError("contradictory availability interval")
        object.__setattr__(self, "lower", self.lower.astimezone(UTC))
        object.__setattr__(self, "upper", self.upper.astimezone(UTC))


def _local_instants(value: datetime, zone: ZoneInfo) -> tuple[datetime, ...]:
    candidates = set()
    for fold in (0, 1):
        aware = value.replace(tzinfo=zone, fold=fold)
        instant = aware.astimezone(UTC)
        if instant.astimezone(zone).replace(tzinfo=None) == value:
            candidates.add(instant)
    return tuple(sorted(candidates))


def source_availability_interval(raw_value: str, timezone: str) -> Availability | None:
    """Bound an authenticated source value; this does not authenticate it."""
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_value):
            zone = ZoneInfo(timezone)
            day = date.fromisoformat(raw_value)
            start = _local_instants(datetime.combine(day, time.min), zone)
            end = _local_instants(
                datetime.combine(day + timedelta(days=1), time.min), zone
            )
            return Availability(min(start), max(end)) if start and end else None
        if "T" not in raw_value and " " not in raw_value:
            return None
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return Availability(parsed, parsed)
        values = _local_instants(parsed, ZoneInfo(timezone))
        return Availability(min(values), max(values)) if values else None
    except (ValueError, ZoneInfoNotFoundError, OverflowError):
        return None


def earliest_source_instant(raw_value: str, timezone: str) -> datetime | None:
    interval = source_availability_interval(raw_value, timezone)
    return interval.lower if interval else None


def established_upper(
    acknowledgement: datetime | None,
    publication: Availability | None = None,
    witness: Availability | None = None,
) -> datetime | None:
    """One minimum rule. An acknowledgement is still required by every consumer."""
    candidates = [
        x
        for x in (
            acknowledgement,
            publication.upper if publication else None,
            witness.upper if witness else None,
        )
        if x is not None
    ]
    if not candidates:
        return None
    upper = min(candidates)
    if publication is not None and publication.lower > upper:
        raise ValueError("capture/publication bounds contradict each other")
    return upper


def available_by(
    cutoff: datetime,
    acknowledgement: datetime | None,
    publication: Availability | None = None,
    witness: Availability | None = None,
    *,
    mode: Mode = "prospective",
    as_of: bool = False,
) -> bool:
    if acknowledgement is None:
        return False
    upper = established_upper(acknowledgement, publication, witness)
    return (
        upper is not None
        and upper <= cutoff
        and ((mode == "replay" and not as_of) or acknowledgement <= cutoff)
    )


@dataclass(frozen=True)
class VerifiedPublication:
    proof_id: str
    manifest_id: str
    token_hash: str
    interval: Availability | None
    trust_class: Literal["production", "test", "legacy_claimed"] = "production"


@dataclass(frozen=True)
class EvaluationContext:
    records: Mapping[str, ScientificRecord]
    committed_at: Callable[[str], datetime | None]
    publication: Callable[[PublicationProof], VerifiedPublication | None] = lambda _: (
        None
    )
    availability: Callable[[ScientificRecord], Availability | None] = lambda _: None
    target_availability: Callable[[TargetVersion], Availability | None] = lambda _: None
    artifact_exists: Callable[[str], bool] = lambda _: False
    resolution_valid: Callable[
        [Resolution, TargetVersion, ObservationVintage], bool
    ] = lambda *_: False
    reconciliation_valid: Callable[[AttemptResult], bool] = lambda _: False


T = TypeVar("T", bound=ScientificRecord)


def _get(context: EvaluationContext, record_id: str, cls: type[T]) -> T:
    record = context.records.get(record_id)
    if not isinstance(record, cls) or record.id != record_id:
        raise ValueError(f"missing or wrong-kind record {record_id}")
    return record


def dependency_closure(
    record: ScientificRecord, context: EvaluationContext
) -> tuple[ScientificRecord, ...]:
    done: dict[str, ScientificRecord] = {}
    active: set[str] = set()

    def visit(current: ScientificRecord) -> None:
        if current.id in active:
            raise ValueError("cyclic scientific dependencies")
        if current.id in done:
            return
        active.add(current.id)
        for link in record_links(current):
            child = context.records.get(link.target_id)
            if (
                child is None
                or child.kind != link.target_kind
                or child.id != link.target_id
            ):
                raise ValueError(f"missing dependency {link.field_path}")
            visit(child)
        active.remove(current.id)
        done[current.id] = current

    visit(record)
    return tuple(done[key] for key in sorted(done))


def _verified(
    proof: PublicationProof, context: EvaluationContext
) -> VerifiedPublication | None:
    result = context.publication(proof)
    if (
        result is None
        or result.proof_id != proof.id
        or result.manifest_id != proof.manifest_id
        or result.token_hash != proof.token_hash
    ):
        return None
    return result


def _upper(record: ScientificRecord, context: EvaluationContext) -> datetime | None:
    witness = None
    if isinstance(record, PublicationProof):
        verified = _verified(record, context)
        witness = verified.interval if verified else None
    return established_upper(
        context.committed_at(record.id), context.availability(record), witness
    )


def record_available_as_of(
    record: ScientificRecord, cutoff: datetime, context: EvaluationContext
) -> bool:
    """All transitive dependencies, not just the outcome, must have existed locally."""
    try:
        return all(
            context.committed_at(item.id) is not None
            and context.committed_at(item.id) <= cutoff
            and _upper(item, context) is not None
            and _upper(item, context) <= cutoff
            and all(context.artifact_exists(h) for h in record_artifact_hashes(item))
            for item in dependency_closure(record, context)
        )
    except (ValueError, KeyError, TypeError, OSError, ArtifactError):
        return False


def training_export(
    records: Sequence[ScientificRecord], *, as_of: datetime, context: EvaluationContext
) -> tuple[ScientificRecord, ...]:
    return tuple(
        record for record in records if record_available_as_of(record, as_of, context)
    )


def _historical_available(
    record: ScientificRecord, cutoff: datetime, mode: Mode, context: EvaluationContext
) -> bool:
    for dependency in dependency_closure(record, context):
        acknowledgement = context.committed_at(dependency.id)
        if acknowledgement is None or (
            mode == "prospective" and acknowledgement > cutoff
        ):
            return False
    return available_by(
        cutoff, context.committed_at(record.id), context.availability(record), mode=mode
    )


def build_normalization(
    target: TargetVersion,
    observations: Sequence[ObservationVintage],
    information_cutoff: datetime,
    *,
    mode: Mode,
    context: EvaluationContext,
) -> NormalizationRecord:
    ordered = sorted(observations, key=lambda o: (o.measurement_period, o.id))
    periods = [o.measurement_period for o in ordered]
    if len(set(periods)) != len(periods):
        raise ValueError(
            "normalization needs exactly one pinned vintage per historical period"
        )
    for observation in ordered:
        if (
            observation.source_series_id != target.source_series_id
            or observation.unit != target.unit
        ):
            raise ValueError("normalization series/unit mismatch")
        if not _historical_available(observation, information_cutoff, mode, context):
            raise ValueError("normalization observation unavailable at cutoff")
        if any(
            context.committed_at(item.id) is None
            for item in dependency_closure(observation, context)
        ):
            raise ValueError("normalization dependency lacks commit acknowledgement")
    values = [o.value for o in ordered]
    scale, reason = None, "fewer_than_three_observations"
    if len(values) >= 3:
        changes = [b - a for a, b in zip(values, values[1:])]
        calculated = (
            statistics.stdev(changes)
            if all(math.isfinite(change) for change in changes)
            else math.inf
        )
        floor = 1e-12 * max(1.0, *(abs(x) for x in values))
        if math.isfinite(calculated) and calculated > floor:
            scale, reason = calculated, None
        else:
            reason = "dispersion_below_versioned_floor"
    return NormalizationRecord(
        target_version_id=target.id,
        source_series_id=target.source_series_id,
        observation_ids=tuple(o.id for o in ordered),
        information_cutoff=information_cutoff,
        scale=scale,
        unavailable_reason=reason,
    )


def validate_normalization(
    normalization: NormalizationRecord,
    target: TargetVersion,
    mode: Mode,
    context: EvaluationContext,
) -> None:
    observations = [
        _get(context, oid, ObservationVintage) for oid in normalization.observation_ids
    ]
    expected = build_normalization(
        target,
        observations,
        normalization.information_cutoff,
        mode=mode,
        context=context,
    )
    if expected.id != normalization.id:
        raise ValueError("normalization scale differs from exact pinned observations")


def outcome_boundary(
    target: TargetVersion, context: EvaluationContext
) -> datetime | None:
    bounds = []
    try:
        calendar = context.target_availability(target)
        if calendar:
            bounds.append(calendar.lower)
        for record in context.records.values():
            if (
                isinstance(record, ObservationVintage)
                and record.source_series_id == target.source_series_id
                and record.measurement_period == target.measurement_period
            ):
                interval = context.availability(record)
                if interval:
                    established_upper(context.committed_at(record.id), interval)
                    bounds.append(interval.lower)
    except (ValueError, KeyError, OSError, ArtifactError) as exc:
        # Skipping a non-replaying observation could select a later print or
        # calendar time. Refuse the whole boundary with a stable typed reason;
        # retain the adapter failure as the cause for internal diagnostics.
        raise OutcomeAvailabilityUnknown() from exc
    return min(bounds) if bounds else None


def validate_experiment(
    experiment: Experiment, context: EvaluationContext
) -> tuple[EvaluationTask, ...]:
    tasks = tuple(_get(context, tid, EvaluationTask) for tid in experiment.task_ids)
    if len({task.information_cutoff for task in tasks}) != 1:
        raise ValueError("experiment members must share one information cutoff")
    expected_pairs = {
        (t, f)
        for t in experiment.target_version_ids
        for f in experiment.forecaster_version_ids
    }
    pairs = [(task.target_version_id, task.forecaster_version_id) for task in tasks]
    if len(set(pairs)) != len(pairs) or set(pairs) != expected_pairs:
        raise ValueError(
            "cohort must contain exactly one task per declared target/forecaster pair"
        )
    for other in context.records.values():
        if (
            isinstance(other, Experiment)
            and other.id != experiment.id
            and set(other.task_ids).intersection(experiment.task_ids)
        ):
            raise ValueError("task already belongs to another experiment")
    for task in tasks:
        target = _get(context, task.target_version_id, TargetVersion)
        source = _get(context, target.source_series_id, SourceSeries)
        # Replaying the closed registry is mandatory even for an empty bundle.
        context.availability(source)
        if (
            target.unit != source.unit
            or target.resolution_policy not in source.vintage_policies
        ):
            raise ValueError("target source unit or vintage policy mismatch")
        forecaster = _get(context, task.forecaster_version_id, ForecasterVersion)
        bundle = _get(context, task.evidence_bundle_id, EvidenceBundle)
        if (
            task.mode != experiment.mode
            or bundle.mode != experiment.mode
            or task.execution_policy != forecaster.execution_policy
        ):
            raise ValueError("task mode/execution policy mismatch")
        if (
            bundle.source_series_id != target.source_series_id
            or bundle.information_cutoff != task.information_cutoff
            or task.submission_deadline > target.submission_deadline
        ):
            raise ValueError("task evidence/target contract mismatch")
        baseline = next(
            t
            for t in tasks
            if t.target_version_id == task.target_version_id
            and t.forecaster_version_id == experiment.baseline_forecaster_id
        )
        if (
            baseline.evidence_bundle_id != task.evidence_bundle_id
            or baseline.information_cutoff != task.information_cutoff
            or baseline.submission_deadline != task.submission_deadline
        ):
            raise ValueError(
                "baseline and model must share evidence, cutoff and deadline"
            )
        if context.committed_at(bundle.id) is None:
            raise ValueError("bundle has no authoritative freeze acknowledgement")
        if experiment.mode == "prospective":
            boundary = outcome_boundary(target, context)
            if boundary is None:
                raise OutcomeAvailabilityUnknown()
            if (
                target.resolution_policy == "fixed_vintage"
                and context.target_availability(target) is None
            ):
                raise ValueError(
                    "prospective fixed vintage needs first-print release evidence"
                )
            if context.committed_at(bundle.id) >= min(
                task.information_cutoff, boundary
            ):
                raise ValueError("bundle frozen after its prospective boundary")
        for oid in bundle.observation_ids:
            observation = _get(context, oid, ObservationVintage)
            if (
                observation.source_series_id != target.source_series_id
                or observation.unit != target.unit
                or not _historical_available(
                    observation, task.information_cutoff, task.mode, context
                )
            ):
                raise ValueError("bundle contains unavailable or wrong-series evidence")
    return tasks


@dataclass(frozen=True)
class Selection:
    run_id: str | None
    reason: str | None
    result_ids: tuple[str, ...] = ()
    reconciliation_times: tuple[datetime, ...] = ()


def select_first_valid(task: EvaluationTask, context: EvaluationContext) -> Selection:
    attempts = sorted(
        (
            r
            for r in context.records.values()
            if isinstance(r, Attempt) and r.task_id == task.id
        ),
        key=lambda r: r.sequence,
    )
    if (
        len({a.sequence for a in attempts}) != len(attempts)
        or any(a.sequence != i + 1 for i, a in enumerate(attempts))
        or len(attempts) > task.max_attempts
    ):
        return Selection(None, "unresolved_attempt")
    consulted: list[str] = []
    reconciliations: list[datetime] = []
    for attempt in attempts:
        results = [
            r
            for r in context.records.values()
            if isinstance(r, AttemptResult) and r.attempt_id == attempt.id
        ]
        original = [r for r in results if r.reconciles_result_id is None]
        revised = [r for r in results if r.reconciles_result_id is not None]
        if len(original) != 1 or len(revised) > 1:
            return Selection(None, "unresolved_attempt", tuple(consulted))
        result = original[0]
        consulted.append(result.id)
        if revised:
            replacement = revised[0]
            if (
                result.outcome != "unknown"
                or replacement.reconciles_result_id != result.id
                or not context.reconciliation_valid(replacement)
            ):
                return Selection(None, "unresolved_attempt", tuple(consulted))
            consulted.append(replacement.id)
            acknowledgement = context.committed_at(replacement.id)
            if acknowledgement is None:
                return Selection(None, "unresolved_attempt", tuple(consulted))
            reconciliations.append(acknowledgement)
            result = replacement
        if result.outcome == "unknown":
            return Selection(None, "unresolved_attempt", tuple(consulted))
        if result.outcome == "succeeded":
            return Selection(
                result.run_id, None, tuple(consulted), tuple(reconciliations)
            )
    return Selection(None, "not_selected", tuple(consulted), tuple(reconciliations))


@dataclass(frozen=True)
class RunAssessment:
    score: ScoreRecord
    details: tuple[str, ...]
    declared_information_cutoff: datetime | None
    effective_information_boundary: datetime | None

    @property
    def eligibility(self) -> Eligibility:
        return self.score.eligibility


def assess_run(
    run: ForecastRun,
    resolution: Resolution,
    experiment: Experiment,
    context: EvaluationContext,
) -> RunAssessment:
    eligibility: Eligibility = "invalid_contract"
    details: list[str] = []
    cutoff = frozen = None
    normalization = None
    run_proof = None
    selection = Selection(None, None)
    raw = None
    normalized = None
    try:
        attempt = _get(context, run.attempt_id, Attempt)
        task = _get(context, attempt.task_id, EvaluationTask)
        target = _get(context, task.target_version_id, TargetVersion)
        observation = _get(context, resolution.observation_id, ObservationVintage)
        cutoff, frozen = (
            task.information_cutoff,
            context.committed_at(task.evidence_bundle_id),
        )
        raw = score_numeric_cdf_distribution(run.distribution, observation.value)
        if (
            resolution.target_version_id != target.id
            or observation.source_series_id != target.source_series_id
            or observation.measurement_period != target.measurement_period
            or observation.unit != target.unit
            or resolution.resolution_policy != target.resolution_policy
            or not context.resolution_valid(resolution, target, observation)
        ):
            eligibility = "invalid_resolution"
            raise ValueError("resolution does not replay the registered contract")
        tasks = validate_experiment(experiment, context)
        if task.id not in experiment.task_ids:
            raise ValueError("run task is not a cohort member")
        if (
            run.prompt_hash != attempt.prompt_hash
            or run.execution_policy != attempt.execution_policy
            or attempt.execution_policy != task.execution_policy
            or run.completed_at < attempt.started_at
        ):
            eligibility = "execution_policy_mismatch"
            raise ValueError(
                "execution metadata differs from the committed task/attempt"
            )
        forecaster = _get(context, task.forecaster_version_id, ForecasterVersion)
        if (
            forecaster.observed_model is not None
            and forecaster.observed_model != run.observed_model
        ):
            eligibility = "execution_policy_mismatch"
            raise ValueError("observed model differs from the frozen forecaster")
        selection = select_first_valid(task, context)
        if selection.reason:
            eligibility = selection.reason
            raise ValueError(selection.reason)
        if selection.run_id != run.id:
            eligibility = "not_selected"
            raise ValueError("a lower durable attempt is the selected submission")
        closure = {
            r.id: r
            for r in dependency_closure(experiment, context)
            + dependency_closure(run, context)
            + dependency_closure(resolution, context)
        }
        for rid in selection.result_ids:
            for item in dependency_closure(_get(context, rid, AttemptResult), context):
                closure[item.id] = item
        if any(context.committed_at(rid) is None for rid in closure):
            eligibility = "missing_acknowledgement"
            raise ValueError("scientific dependency lacks a commit acknowledgement")
        if any(
            not context.artifact_exists(h)
            for record in closure.values()
            for h in record_artifact_hashes(record)
        ):
            eligibility = "missing_artifact"
            raise ValueError("artifact closure is incomplete or corrupted")
        matches = [
            _get(context, nid, NormalizationRecord)
            for nid in experiment.normalization_ids
            if _get(context, nid, NormalizationRecord).target_version_id == target.id
        ]
        if len(matches) > 1:
            eligibility = "invalid_normalization"
            raise ValueError("multiple normalizations for one target")
        if matches:
            normalization = matches[0]
            if normalization.information_cutoff != cutoff:
                eligibility = "invalid_normalization"
                raise ValueError("normalization cutoff differs from task")
            try:
                validate_normalization(normalization, target, task.mode, context)
            except ValueError:
                eligibility = "invalid_normalization"
                raise
            if normalization.scale is not None:
                candidate_score = raw.crps / normalization.scale
                if not math.isfinite(candidate_score):
                    eligibility = "invalid_normalization"
                    raise ValueError("normalized score exceeds finite numeric range")
                normalized = round_distribution_number(candidate_score)
        if experiment.mode == "replay":
            eligibility = "replay"
        else:
            boundary = outcome_boundary(target, context)
            if boundary is None:
                eligibility = "outcome_availability_unknown"
                raise ValueError("no authenticated first-print lower boundary")
            if any(t >= boundary for t in selection.reconciliation_times):
                eligibility = "late_attempt_reconciliation"
                raise ValueError(
                    "selection depends on reconciliation after outcome availability"
                )
            if attempt.cohort_proof_id is None:
                eligibility = "missing_cohort_proof"
                raise ValueError(
                    "attempt does not commit an independent cohort receipt"
                )
            proof = _get(context, attempt.cohort_proof_id, PublicationProof)
            manifest = _get(context, proof.manifest_id, PublicationManifest)
            cohort = _verified(proof, context)
            if (
                cohort is None
                or cohort.interval is None
                or cohort.trust_class != "production"
                or manifest.manifest_type != "cohort"
                or manifest.experiment_id != experiment.id
                or proof.token_hash != attempt.cohort_token_hash
            ):
                eligibility = "invalid_cohort"
                raise ValueError("cohort receipt cannot be independently verified")
            boundaries = [
                outcome_boundary(
                    _get(context, t.target_version_id, TargetVersion), context
                )
                for t in tasks
            ]
            if any(x is None for x in boundaries):
                eligibility = "outcome_availability_unknown"
                raise ValueError("cohort member lacks an outcome boundary")
            cohort_deadline = min(
                experiment.registration_deadline,
                *(t.information_cutoff for t in tasks),
                *(t.submission_deadline for t in tasks),
                *boundaries,
            )
            effective = max(context.committed_at(t.evidence_bundle_id) for t in tasks)
            if (
                cohort.interval.upper >= cohort_deadline
                or cohort.interval.upper >= attempt.started_at
                or effective >= cohort.interval.lower
                or manifest.effective_information_boundary != effective
                or manifest.declared_information_cutoff != cutoff
            ):
                eligibility = "late_cohort"
                raise ValueError(
                    "cohort/freeze/declared boundaries are not strictly ordered"
                )
            if normalization:
                for oid in normalization.observation_ids:
                    upper = _upper(_get(context, oid, ObservationVintage), context)
                    if upper is None or upper >= cohort.interval.lower:
                        eligibility = "invalid_normalization"
                        raise ValueError(
                            "normalization was not frozen before cohort witness"
                        )
            candidates = []
            for item in context.records.values():
                if not isinstance(item, PublicationProof):
                    continue
                candidate_manifest = context.records.get(item.manifest_id)
                if (
                    not isinstance(candidate_manifest, PublicationManifest)
                    or candidate_manifest.run_id != run.id
                    or candidate_manifest.experiment_id != experiment.id
                ):
                    continue
                verified = _verified(item, context)
                if (
                    verified
                    and verified.interval
                    and verified.trust_class == "production"
                    and candidate_manifest.code_hash == attempt.code_hash
                    and candidate_manifest.attempt_result_ids == selection.result_ids
                    and candidate_manifest.cohort_proof_id == proof.id
                    and candidate_manifest.cohort_token_hash == proof.token_hash
                    and candidate_manifest.declared_information_cutoff == cutoff
                    and candidate_manifest.effective_information_boundary == frozen
                ):
                    run_ack = context.committed_at(run.id)
                    if (
                        cohort.interval.upper >= verified.interval.lower
                        or run.completed_at >= verified.interval.lower
                        or run_ack is None
                        or run_ack >= verified.interval.lower
                    ):
                        continue
                    candidates.append((verified.interval.upper, item))
            if not candidates:
                eligibility = "invalid_publication"
                raise ValueError(
                    "run lacks a verified manifest committing its prior cohort receipt"
                )
            witness_upper, run_proof = min(candidates, key=lambda pair: pair[0])
            witness = _verified(run_proof, context)
            if any(t >= witness.interval.lower for t in selection.reconciliation_times):
                eligibility = "late_attempt_reconciliation"
                raise ValueError("reconciliation did not precede the run witness")
            if any(
                context.committed_at(rid) >= witness.interval.lower
                for rid in selection.result_ids
            ):
                eligibility = "invalid_publication"
                raise ValueError("selection result was not committed before witness")
            if witness_upper >= min(task.submission_deadline, boundary):
                eligibility = "late_publication"
                raise ValueError(
                    "run witness overlaps submission or first-print boundary"
                )
            eligibility = "eligible"
    except OutcomeAvailabilityUnknown as exc:
        eligibility = "outcome_availability_unknown"
        details.append(str(exc))
    except (ValueError, KeyError, TypeError, OSError, ArtifactError) as exc:
        details.append(str(exc))
    score = ScoreRecord(
        run_id=run.id,
        resolution_id=resolution.id,
        experiment_id=experiment.id,
        normalization_id=normalization.id if normalization else None,
        publication_proof_id=run_proof.id if run_proof else None,
        attempt_result_ids=selection.result_ids,
        eligibility=eligibility,
        crps=raw.crps if raw else None,
        pit=raw.pit if raw else None,
        normalized_crps=normalized,
        reward=-normalized
        if normalized is not None and eligibility == "eligible"
        else None,
    )
    return RunAssessment(score, tuple(details), cutoff, frozen)


def build_leaderboard(
    experiment: Experiment, scores: Sequence[ScoreRecord], context: EvaluationContext
) -> list[dict[str, object]]:
    tasks = validate_experiment(experiment, context)
    by_pair: dict[tuple[str, str], ScoreRecord] = {}
    duplicates: set[tuple[str, str]] = set()
    for score in scores:
        if (
            score.experiment_id != experiment.id
            or score.eligibility != "eligible"
            or score.normalized_crps is None
        ):
            continue
        run = _get(context, score.run_id, ForecastRun)
        attempt = _get(context, run.attempt_id, Attempt)
        task = _get(context, attempt.task_id, EvaluationTask)
        if task.id not in experiment.task_ids:
            continue
        pair = (task.target_version_id, task.forecaster_version_id)
        if pair in by_pair and by_pair[pair].id != score.id:
            duplicates.add(pair)
        by_pair[pair] = score
    result = []
    for fid in experiment.forecaster_version_ids:
        paired = [
            by_pair[(tid, fid)]
            for tid in experiment.target_version_ids
            if (tid, fid) in by_pair
            and (tid, experiment.baseline_forecaster_id) in by_pair
            and (tid, fid) not in duplicates
            and (tid, experiment.baseline_forecaster_id) not in duplicates
        ]
        complete = (
            len(paired) == len(experiment.target_version_ids)
            and experiment.mode == "prospective"
        )
        member_tasks = [t for t in tasks if t.forecaster_version_id == fid]
        result.append(
            {
                "forecaster_id": fid,
                "targets": len(experiment.target_version_ids),
                "paired_coverage": len(paired),
                "mean_normalized_crps": statistics.mean(
                    s.normalized_crps for s in paired
                )
                if paired
                else None,
                "rank": None,
                "rank_eligible": complete,
                "declared_information_cutoff": tasks[0].information_cutoff.isoformat(),
                "effective_information_boundary": max(
                    context.committed_at(t.evidence_bundle_id) for t in member_tasks
                ).isoformat(),
                "mode": experiment.mode,
            }
        )
    eligible = sorted(
        (r for r in result if r["rank_eligible"]),
        key=lambda r: (r["mean_normalized_crps"], r["forecaster_id"]),
    )
    for rank, row in enumerate(eligible, start=1):
        row["rank"] = rank
    return sorted(
        result, key=lambda r: (r["rank"] is None, r["rank"] or 0, r["forecaster_id"])
    )
