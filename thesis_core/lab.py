"""Read-only, current-evidence projections for the forecasting lab.

Every request owns one graph/verification context. Operational facts describe a
read, never a historical export or a scientific acknowledgement.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import mean
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from . import lab_contracts as dto
from .artifacts import ArtifactCorrupt, ArtifactError, ArtifactMissing
from .contracts import (
    RECORD_TYPES,
    Attempt,
    EvaluationTask,
    EvidenceBundle,
    Experiment,
    ForecasterVersion,
    ForecastRun,
    NumericCdf,
    ObservationVintage,
    ScientificRecord,
    SourceExchange,
    SourceSeries,
    TargetVersion,
    record_artifact_hashes,
    record_links,
)
from .evaluation import (
    OutcomeAvailabilityUnknown,
    build_leaderboard,
    select_first_valid,
    validate_experiment,
)
from .publication import database_now
from .service import context_for_store, evaluate_experiment

T = TypeVar("T", bound=ScientificRecord)
EMPTY_COST = {"amount": None, "currency": None, "state": "not_reported"}
ATTEMPT_KEYS = (
    "total",
    "succeeded",
    "failed",
    "unknown",
    "pending",
    "reconciled",
    "unknown_history",
)


class LabNotFound(ValueError):  # noqa: N818
    """A requested public resource does not exist or has another kind."""


class LabIntegrityError(ValueError):
    """The graph cannot support a truthful structural projection."""


def timestamp(value: datetime | None) -> str | None:
    return (
        value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if value
        else None
    )


def link(record: ScientificRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "kind": record.kind,
        "record_path": f"/records/{record.id}",
    }


def display_quantiles(distribution: NumericCdf) -> dict[str, Any]:
    """Generalized inverse of original piecewise-linear points, display only."""

    def inverse(probability):
        points = distribution.points
        for index, point in enumerate(points):
            if point.probability >= probability:
                if index == 0 or point.probability == probability:
                    return point.value
                previous = points[index - 1]
                return previous.value + (point.value - previous.value) * (
                    (probability - previous.probability)
                    / (point.probability - previous.probability)
                )
        raise LabIntegrityError("CDF has no upper endpoint")

    return {
        "method": "inverse_piecewise_linear_cdf_v1",
        "q10": inverse(0.1),
        "q50": inverse(0.5),
        "q90": inverse(0.9),
    }


def _page_ids(ids, limit, after):
    ordered = sorted(set(ids))
    remaining = [identity for identity in ordered if after is None or identity > after]
    selected = remaining[:limit]
    return selected, (selected[-1] if len(remaining) > limit else None), len(ordered)


class Lab:
    def __init__(self, store):
        self.store = store
        self.now = database_now(store)
        try:
            self.context = context_for_store(store)
        except (ArtifactMissing, ArtifactCorrupt) as exc:
            raise LabIntegrityError("record artifact integrity failure") from exc
        self.records = self.context.records
        self.by_kind = defaultdict(list)
        for record in self.records.values():
            self.by_kind[record.kind].append(record)
        self._jobs = None
        self._validity = {}
        self._assessments = {}
        self._results = {}
        self._resolutions = {}
        self._releases = {}
        self._attempts = {}
        self._selections = {}
        self._artifact_metadata = {}
        self._structural = set()

    @property
    def envelope(self):
        return {"schema_version": "thesis_lab_v1", "generated_at": timestamp(self.now)}

    @property
    def jobs(self):
        if self._jobs is None:
            jobs = list(self.store.jobs())
            # Scheduling first persists the outbox. Reading must not deliver it,
            # but undelivered forecast work is already queued, not unscheduled.
            with self.store.connection() as connection:
                pending = connection.execute(
                    "SELECT o.kind,o.subject_id,o.created_at FROM outbox o "
                    "WHERE NOT EXISTS (SELECT 1 FROM jobs j WHERE j.outbox_id=o.id)"
                ).fetchall()
            jobs.extend(
                dict(
                    row,
                    state="pending",
                    lease_expires_at=None,
                    updated_at=row["created_at"],
                )
                for row in pending
            )
            self._jobs = tuple(jobs)
        return self._jobs

    def get(self, identity: str, cls: type[T], *, public=False) -> T:
        record = self.records.get(identity)
        if not isinstance(record, cls):
            raise (LabNotFound if public else LabIntegrityError)("record kind mismatch")
        return record

    def page(self, ids, project, model, *, limit=20, after=None):
        selected, cursor, total = _page_ids(ids, limit, after)
        return model.model_validate(
            self.envelope
            | {
                "items": [project(identity) for identity in selected],
                "total": total,
                "next_cursor": cursor,
            }
        )

    def artifact(self, digest, role, *, size=None, media_type=None):
        if digest not in self._artifact_metadata:
            try:
                payload = self.store.artifacts.read_bytes(digest)
            except (ArtifactMissing, ArtifactCorrupt) as exc:
                raise LabIntegrityError(
                    "referenced artifact integrity failure"
                ) from exc
            self._artifact_metadata[digest] = len(payload)
        measured = self._artifact_metadata[digest]
        if size is not None and measured != size:
            raise LabIntegrityError("artifact byte count mismatch")
        return {
            "sha256": digest,
            "bytes": measured,
            "media_type": media_type,
            "role": role,
            "download_path": f"/artifacts/{digest}",
        }

    def artifacts(self, record):
        output = []
        refs = {}
        roles = defaultdict(list)
        for field in record.artifact_fields:
            value = getattr(record, field)
            values = value if isinstance(value, (tuple, list)) else [value]
            for digest in values:
                if isinstance(digest, str):
                    roles[digest].append(field.removesuffix("_hash"))
        if isinstance(record, SourceExchange):
            refs[record.body.sha256] = record.body
            roles[record.body.sha256].append(f"source_{record.role}")
            if record.request_body:
                refs[record.request_body.sha256] = record.request_body
                roles[record.request_body.sha256].append("source_request")
        if isinstance(record, EvidenceBundle):
            refs.update({ref.sha256: ref for ref in record.artifact_refs})
        for digest in record_artifact_hashes(record):
            ref = refs.get(digest)
            for role in roles[digest] or [record.kind]:
                output.append(
                    self.artifact(
                        digest,
                        role,
                        size=ref.bytes if ref else None,
                        media_type=ref.media_type if ref else None,
                    )
                )
        return output

    def structural_closure(self, record):
        """Check declared transitive joins before scientific validation can refuse.

        A scientifically invalid release/membership remains displayable. A
        declared reference whose record or bytes vanished cannot be projected.
        """
        pending = [record]
        while pending:
            item = pending.pop()
            if item.id in self._structural:
                continue
            self.artifacts(item)
            self._structural.add(item.id)
            pending.extend(
                self.get(edge.target_id, RECORD_TYPES[edge.target_kind])
                for edge in record_links(item)
            )

    def agent_identity(self, identity):
        agent = self.get(identity, ForecasterVersion)
        self.structural_closure(agent)
        return {
            "id": agent.id,
            "label": f"{agent.model_request} · {agent.agent_version}",
            "provider": agent.provider,
            "model_request": agent.model_request,
            "observed_model": agent.observed_model,
            "agent_version": agent.agent_version,
            "harness_version": agent.harness_version,
        }

    def target_title(self, target):
        source = self.get(target.source_series_id, SourceSeries)
        return f"{source.name} · {target.measurement_period}"

    def experiment_title(self, experiment):
        titles = [
            self.target_title(self.get(tid, TargetVersion))
            for tid in experiment.target_version_ids
        ]
        title = (
            titles[0]
            if len(titles) == 1
            else f"{titles[0]} + {len(titles) - 1} targets"
        )
        return f"{title} · {len(experiment.forecaster_version_ids)} methods"

    def experiment_tasks(self, experiment):
        # Missing declared references are corruption; missing Cartesian membership
        # is a scientific invalidity retained as an explicit matrix cell.
        self.structural_closure(experiment)
        tasks = [self.get(tid, EvaluationTask) for tid in experiment.task_ids]
        for identity in experiment.target_version_ids:
            self.get(identity, TargetVersion)
        for identity in experiment.forecaster_version_ids:
            self.get(identity, ForecasterVersion)
        pairs = [(task.target_version_id, task.forecaster_version_id) for task in tasks]
        if len(set(pairs)) != len(pairs):
            raise LabIntegrityError("duplicate experiment pair")
        return {
            (task.target_version_id, task.forecaster_version_id): task for task in tasks
        }

    def validity(self, experiment):
        if experiment.id not in self._validity:
            self.experiment_tasks(experiment)
            try:
                validate_experiment(experiment, self.context)
                reason = None
            except OutcomeAvailabilityUnknown:
                reason = "outcome_availability_unknown"
            except (ValueError, KeyError, OSError, ArtifactError):
                reason = "invalid_contract"
            self._validity[experiment.id] = reason
        return self._validity[experiment.id]

    def assessments(self, experiment):
        if experiment.id not in self._assessments:
            self._assessments[experiment.id] = evaluate_experiment(
                self.store, experiment.id, persist=False, _context=self.context
            )
        return self._assessments[experiment.id]

    def selection(self, task):
        if task.id not in self._selections:
            self.structural_closure(task)
            # Selection must never expose a run before its ownership and trace
            # joins have been checked, including on matrix/comparison routes.
            for attempt in self.task_attempts(task):
                self.attempt_state(attempt)
            self._selections[task.id] = select_first_valid(task, self.context)
        return self._selections[task.id]

    def attempt_state(self, attempt):
        if attempt.id in self._attempts:
            return self._attempts[attempt.id]
        self.structural_closure(attempt)
        results = [
            r for r in self.by_kind["attempt_result"] if r.attempt_id == attempt.id
        ]
        originals = [r for r in results if r.reconciles_result_id is None]
        revised = [r for r in results if r.reconciles_result_id is not None]
        if len(originals) > 1 or len(revised) > 1 or (revised and not originals):
            raise LabIntegrityError("contradictory attempt results")
        for result in results:
            self.structural_closure(result)
            if (
                result.run_id is not None
                and self.get(result.run_id, ForecastRun).attempt_id != attempt.id
            ):
                raise LabIntegrityError("result names another attempt's run")
        if revised and revised[0].reconciles_result_id != originals[0].id:
            raise LabIntegrityError("reconciliation names another original result")
        effective = originals[0] if originals else None
        verified = None
        if revised:
            verified = bool(
                effective.outcome == "unknown"
                and revised[0].reconciles_result_id == effective.id
                and self.context.reconciliation_valid(revised[0])
            )
            if verified:
                effective = revised[0]
        duration = None
        if effective and not revised and effective.completed_at is not None:
            elapsed = (effective.completed_at - attempt.started_at).total_seconds()
            if elapsed >= 0:
                duration = elapsed
        outcome = effective.outcome if effective else "pending"
        state = {
            "results": originals + revised,
            "effective": effective,
            "reconciliation_verified": verified,
            "outcome": outcome,
            "elapsed": duration,
            "reconciled": bool(revised and verified),
            "unknown_history": any(r.outcome == "unknown" for r in originals),
        }
        self._attempts[attempt.id] = state
        return state

    def task_attempts(self, task):
        return sorted(
            (a for a in self.by_kind["attempt"] if a.task_id == task.id),
            key=lambda a: a.sequence,
        )

    def counts(self, tasks):
        counts = dict.fromkeys(ATTEMPT_KEYS, 0)
        durations = []
        ids = {task.id for task in tasks}
        for attempt in self.by_kind["attempt"]:
            if attempt.task_id not in ids:
                continue
            state = self.attempt_state(attempt)
            counts["total"] += 1
            counts[state["outcome"]] += 1
            counts["reconciled"] += int(state["reconciled"])
            counts["unknown_history"] += int(state["unknown_history"])
            if state["elapsed"] is not None:
                durations.append(state["elapsed"])
        return counts, durations

    def execution(self, task, *, invalid=False):
        if task is None:
            counts, durations = dict.fromkeys(ATTEMPT_KEYS, 0), []
            state, path = "invalid", None
        else:
            counts, durations = self.counts([task])
            attempts = self.task_attempts(task)
            active_jobs = [
                j
                for j in self.jobs
                if j["subject_id"] == task.id and j["kind"] == "forecast"
            ]
            selection = self.selection(task)
            if invalid:
                state = "invalid"
            elif any(self.attempt_state(a)["outcome"] == "unknown" for a in attempts):
                state = "unknown"
            elif any(self.attempt_state(a)["outcome"] == "pending" for a in attempts):
                state = (
                    "running"
                    if any(
                        j["state"] == "leased" and j["lease_expires_at"] > self.now
                        for j in active_jobs
                    )
                    else "unknown"
                )
            elif counts["succeeded"]:
                state = "succeeded"
            elif any(j["state"] in {"pending", "leased"} for j in active_jobs):
                state = (
                    "running"
                    if any(
                        j["state"] == "leased" and j["lease_expires_at"] > self.now
                        for j in active_jobs
                    )
                    else "queued"
                )
            elif counts["failed"] or any(j["state"] == "failed" for j in active_jobs):
                state = "failed"
            elif any(j["state"] == "unknown" for j in active_jobs):
                state = "unknown"
            else:
                state = "not_scheduled"
            # A blocked selection does not erase the actual observed outcomes.
            duration = None
            if selection.run_id is not None:
                run = self.get(selection.run_id, ForecastRun)
                duration = self.attempt_state(self.get(run.attempt_id, Attempt))[
                    "elapsed"
                ]
            elif len(attempts) == 1:
                duration = self.attempt_state(attempts[0])["elapsed"]
            durations = [] if duration is None else [duration]
            path = f"/lab/tasks/{task.id}/attempts"
        elapsed = durations[0] if durations else None
        return {
            "state": state,
            "attempt_counts": counts,
            "elapsed_seconds": elapsed,
            "elapsed_basis": "recorded_attempt_elapsed"
            if elapsed is not None
            else None,
            "cost": EMPTY_COST,
            "attempts_path": path,
        }

    def release(self, target):
        if target.id in self._releases:
            return self._releases[target.id]
        self.structural_closure(target)
        evidence = target.release_evidence
        interval = None
        try:
            interval = self.context.target_availability(target)
            state = "verified" if interval else "unknown"
        except (ValueError, KeyError, OSError, ArtifactError):
            state = "invalid"
        artifact = None
        if evidence:
            # Verification failure keeps declared evidence inspectable without
            # claiming its bytes establish an official time.
            artifact = {
                "sha256": evidence.artifact.sha256,
                "bytes": evidence.artifact.bytes,
                "media_type": evidence.artifact.media_type,
                "role": "release",
                "download_path": f"/artifacts/{evidence.artifact.sha256}",
            }
        result = {
            "state": state,
            "lower": timestamp(interval.lower) if interval else None,
            "upper": timestamp(interval.upper) if interval else None,
            "raw_value": evidence.raw_value if evidence else None,
            "timezone": evidence.timezone if evidence else None,
            "official_url": evidence.source_url if evidence else None,
            "evidence": artifact,
        }
        self._releases[target.id] = result
        return result

    def resolution(self, target):
        if target.id in self._resolutions:
            return self._resolutions[target.id]
        self.structural_closure(target)
        rows = [
            r for r in self.by_kind["resolution"] if r.target_version_id == target.id
        ]
        if len(rows) > 1:
            raise LabIntegrityError("multiple resolutions for one target")
        row = rows[0] if rows else None
        if row:
            self.structural_closure(row)
        observation = self.get(row.observation_id, ObservationVintage) if row else None
        valid = bool(row and self.context.resolution_valid(row, target, observation))
        result = {
            "state": ("resolved" if valid else "invalid") if row else "pending",
            "resolution": link(row) if row else None,
            "observation": link(observation) if observation else None,
            "value": observation.value if valid else None,
            "unit": target.unit,
            "recorded_at": timestamp(row.recorded_at) if row else None,
            "reason_code": "invalid_resolution" if row and not valid else None,
        }
        self._resolutions[target.id] = result
        return result

    def empty_score(self, mode, reason=None):
        if reason is None:
            reason = (
                "replay"
                if mode == "replay"
                else "live_pilot"
                if mode == "live_pilot"
                else "awaiting_resolution"
            )
        return {
            "score": None,
            "crps": None,
            "normalized_crps": None,
            "pit": None,
            "scoring_version": None,
            "eligibility": {
                "state": "not_assessed"
                if reason in {"awaiting_resolution", "no_selected_run"}
                else "ineligible",
                "reason_codes": [reason],
                "ranking_allowed": False,
                "reward": None,
            },
        }

    def score(self, experiment, task, *, invalid=None):
        if invalid:
            return self.empty_score(experiment.mode, invalid)
        selection = self.selection(task)
        if selection.run_id is None:
            reason = selection.reason if self.task_attempts(task) else None
            return self.empty_score(
                experiment.mode,
                reason
                or ("no_selected_run" if experiment.mode == "prospective" else None),
            )
        assessments = [
            a
            for a in self.assessments(experiment)
            if a.score.run_id == selection.run_id
        ]
        if not assessments:
            return self.empty_score(experiment.mode)
        if len(assessments) != 1:
            raise LabIntegrityError("ambiguous selected run assessment")
        scored = assessments[0].score
        result = self.results(experiment)[task.forecaster_version_id]
        return {
            "score": link(scored) if scored.id in self.records else None,
            "crps": scored.crps,
            "normalized_crps": scored.normalized_crps,
            "pit": scored.pit,
            "scoring_version": scored.scoring_version,
            "eligibility": {
                "state": "eligible"
                if scored.eligibility == "eligible"
                else "ineligible",
                "reason_codes": []
                if scored.eligibility == "eligible"
                else [scored.eligibility],
                "ranking_allowed": result["rank_eligible"],
                "reward": scored.reward,
            },
        }

    def results(self, experiment):
        if experiment.id in self._results:
            return self._results[experiment.id]
        invalid = self.validity(experiment)
        assessments = self.assessments(experiment)
        if invalid:
            rows = [
                {
                    "forecaster_id": fid,
                    "rank": None,
                    "rank_eligible": False,
                    "paired_coverage": 0,
                    "targets": len(experiment.target_version_ids),
                    "mean_normalized_crps": None,
                }
                for fid in experiment.forecaster_version_ids
            ]
        else:
            rows = build_leaderboard(
                experiment, [a.score for a in assessments], self.context
            )
        output = {}
        tasks = list(self.experiment_tasks(experiment).values())
        for row in rows:
            fid = row["forecaster_id"]
            counts, durations = self.counts(
                [task for task in tasks if task.forecaster_version_id == fid]
            )
            exclusions = set()
            if invalid:
                exclusions.add(invalid)
            else:
                for assessment in assessments:
                    run = self.get(assessment.score.run_id, ForecastRun)
                    task = self.get(
                        self.get(run.attempt_id, Attempt).task_id, EvaluationTask
                    )
                    if (
                        task.forecaster_version_id == fid
                        and assessment.eligibility != "eligible"
                    ):
                        exclusions.add(assessment.eligibility)
                if experiment.mode in {"replay", "live_pilot"}:
                    exclusions.add(experiment.mode)
            output[fid] = {
                "experiment_id": experiment.id,
                "experiment_title": self.experiment_title(experiment),
                "forecaster_id": fid,
                "agent": self.agent_identity(fid),
                "is_baseline": fid == experiment.baseline_forecaster_id,
                "mode": experiment.mode,
                "rank": row["rank"],
                "rank_eligible": row["rank_eligible"],
                "paired_coverage": row["paired_coverage"],
                "targets": row["targets"],
                "mean_normalized_crps": row["mean_normalized_crps"],
                "attempt_counts": counts,
                "mean_elapsed_seconds": mean(durations) if durations else None,
                "elapsed_sample_count": len(durations),
                "cost": EMPTY_COST,
                "exclusions": sorted(exclusions),
            }
        self._results[experiment.id] = output
        return output

    def coverage(self, experiments, targets):
        counts = dict.fromkeys(dto.Coverage.model_fields, 0)
        target_ids = set(targets)
        paired = set()
        counts["declared_targets"] = len(target_ids)
        for experiment in experiments:
            tasks = self.experiment_tasks(experiment)
            invalid = self.validity(experiment)
            for tid in target_ids.intersection(experiment.target_version_ids):
                eligible_methods = set()
                for fid in experiment.forecaster_version_ids:
                    task = tasks.get((tid, fid))
                    counts["declared_tasks"] += 1
                    execution = self.execution(task, invalid=bool(invalid))
                    counts[execution["state"] + "_tasks"] += 1
                    if task and self.selection(task).run_id:
                        counts["selected_tasks"] += 1
                    if (
                        task
                        and self.score(experiment, task, invalid=invalid)[
                            "eligibility"
                        ]["state"]
                        == "eligible"
                    ):
                        counts["eligible_tasks"] += 1
                        eligible_methods.add(fid)
                # The overview counts distinct fully paired targets in the
                # displayed scope. Per-agent pairing remains in core results.
                if eligible_methods == set(experiment.forecaster_version_ids):
                    paired.add(tid)
        counts["paired_targets"] = len(paired)
        counts["resolved_targets"] = sum(
            self.resolution(self.get(tid, TargetVersion))["state"] == "resolved"
            for tid in target_ids
        )
        return counts

    def forecast_summary(self, identity):
        target = self.get(identity, TargetVersion)
        self.structural_closure(target)
        source = self.get(target.source_series_id, SourceSeries)
        experiments = [
            e for e in self.by_kind["experiment"] if identity in e.target_version_ids
        ]
        modes = {mode: 0 for mode in ("prospective", "replay", "live_pilot")}
        for experiment in experiments:
            modes[experiment.mode] += 1
        return {
            "id": target.id,
            "title": self.target_title(target),
            "source": {
                "id": source.id,
                "name": source.name,
                "adapter_id": source.adapter_id,
            },
            "measurement_period": target.measurement_period,
            "unit": target.unit,
            "mode_counts": modes,
            "experiment_count": len(experiments),
            "coverage": self.coverage(experiments, [identity]),
            "resolution": self.resolution(target),
            "release": self.release(target),
        }

    def forecast_detail(self, identity):
        target = self.get(identity, TargetVersion, public=True)
        return dto.ForecastDetail.model_validate(
            self.envelope
            | self.forecast_summary(identity)
            | {
                "target": link(target),
                "target_label": target.target_id,
                "resolution_rule": target.resolution_rule,
                "resolution_policy": target.resolution_policy,
                "vintage_date": target.vintage_date,
                "submission_deadline": timestamp(target.submission_deadline),
                "source_record": link(self.get(target.source_series_id, SourceSeries)),
                "experiments_path": f"/lab/forecasts/{identity}/experiments",
                "comparisons_path": f"/lab/forecasts/{identity}/comparisons",
                "evidence_links": [self.release(target)["evidence"]]
                if target.release_evidence
                else [],
            }
        )

    def experiment_summary(self, identity):
        experiment = self.get(identity, Experiment)
        return {
            "id": experiment.id,
            "title": self.experiment_title(experiment),
            "hypothesis": None,
            "mode": experiment.mode,
            "baseline": self.agent_identity(experiment.baseline_forecaster_id),
            "target_count": len(experiment.target_version_ids),
            "agent_count": len(experiment.forecaster_version_ids),
            "registration_deadline": timestamp(experiment.registration_deadline),
            "coverage": self.coverage([experiment], experiment.target_version_ids),
            "rank_eligible_agent_count": sum(
                row["rank_eligible"] for row in self.results(experiment).values()
            ),
        }

    def experiment_detail(self, identity):
        experiment = self.get(identity, Experiment, public=True)
        tasks = list(self.experiment_tasks(experiment).values())
        cutoffs = {task.information_cutoff for task in tasks}
        freezes = [self.context.committed_at(task.evidence_bundle_id) for task in tasks]
        return dto.ExperimentDetail.model_validate(
            self.envelope
            | self.experiment_summary(identity)
            | {
                "record": link(experiment),
                "ranking_policy": experiment.ranking_policy,
                "declared_information_cutoff": timestamp(next(iter(cutoffs)))
                if len(cutoffs) == 1
                else None,
                "effective_information_boundary": timestamp(max(freezes))
                if freezes and all(freezes)
                else None,
                "matrix_path": f"/lab/experiments/{identity}/matrix",
                "results_path": f"/lab/experiments/{identity}/results",
            }
        )

    def comparison(self, experiment, task):
        target = self.get(task.target_version_id, TargetVersion)
        invalid = self.validity(experiment)
        selection = self.selection(task)
        run = self.get(selection.run_id, ForecastRun) if selection.run_id else None
        evidence = self.get(task.evidence_bundle_id, EvidenceBundle)
        artifacts = self.artifacts(evidence)
        if run:
            artifacts += self.artifacts(
                self.get(run.attempt_id, Attempt)
            ) + self.artifacts(run)
        # Canonical records carry the exact history list and all further links.
        artifacts.append(
            self.artifact(evidence.id, "evidence_bundle", media_type="application/json")
        )
        for manifest in self.by_kind["publication_manifest"]:
            if manifest.experiment_id == experiment.id and manifest.run_id == (
                run.id if run else None
            ):
                artifacts.append(
                    self.artifact(
                        manifest.id,
                        "publication_manifest",
                        media_type="application/json",
                    )
                )
                for proof in self.by_kind["publication_proof"]:
                    if proof.manifest_id == manifest.id:
                        artifacts += self.artifacts(proof)
        resolution = self.resolution(target)
        if resolution["observation"]:
            observation = self.get(resolution["observation"]["id"], ObservationVintage)
            artifacts.append(
                self.artifact(
                    observation.id, "observation", media_type="application/json"
                )
            )
            for eid in observation.source_exchange_ids:
                artifacts += self.artifacts(self.get(eid, SourceExchange))
        return {
            "task": link(task),
            "target_id": target.id,
            "experiment_id": experiment.id,
            "agent": self.agent_identity(task.forecaster_version_id),
            "is_baseline": task.forecaster_version_id
            == experiment.baseline_forecaster_id,
            "mode": experiment.mode,
            "execution": self.execution(task, invalid=bool(invalid)),
            "selected_run": link(run) if run else None,
            "distribution": run.distribution if run else None,
            "quantiles": display_quantiles(run.distribution) if run else None,
            "resolution": resolution,
            "score": self.score(experiment, task, invalid=invalid),
            "declared_information_cutoff": timestamp(task.information_cutoff),
            "effective_information_boundary": timestamp(
                self.context.committed_at(evidence.id)
            ),
            "submission_deadline": timestamp(task.submission_deadline),
            "evidence_links": list(
                {(a["sha256"], a["role"]): a for a in artifacts}.values()
            ),
        }

    def matrix(
        self, identity, *, limit=20, after=None, method_limit=10, method_after=None
    ):
        experiment = self.get(identity, Experiment, public=True)
        tasks = self.experiment_tasks(experiment)
        invalid = self.validity(experiment)
        tids, cursor, total = _page_ids(experiment.target_version_ids, limit, after)
        fids, method_cursor, methods = _page_ids(
            experiment.forecaster_version_ids, method_limit, method_after
        )
        rows = []
        for tid in tids:
            target = self.get(tid, TargetVersion)
            cells = []
            for fid in fids:
                task = tasks.get((tid, fid))
                selected = self.selection(task).run_id if task else None
                run = self.get(selected, ForecastRun) if selected else None
                cells.append(
                    {
                        "target_id": tid,
                        "forecaster_id": fid,
                        "task": link(task) if task else None,
                        "mode": experiment.mode,
                        "execution": self.execution(task, invalid=bool(invalid)),
                        "selected_run": link(run) if run else None,
                        "quantiles": display_quantiles(run.distribution)
                        if run
                        else None,
                        "resolution": self.resolution(target),
                        "score": self.score(experiment, task, invalid=invalid)
                        if task
                        else self.empty_score(
                            experiment.mode, invalid or "invalid_contract"
                        ),
                        "declared_information_cutoff": timestamp(
                            task.information_cutoff
                        )
                        if task
                        else None,
                        "effective_information_boundary": timestamp(
                            self.context.committed_at(task.evidence_bundle_id)
                        )
                        if task
                        else None,
                        "submission_deadline": timestamp(task.submission_deadline)
                        if task
                        else None,
                        "comparison_path": (
                            f"/lab/forecasts/{tid}/comparisons?experiment_id={identity}"
                        ),
                    }
                )
            rows.append(
                {
                    "target_id": tid,
                    "title": self.target_title(target),
                    "measurement_period": target.measurement_period,
                    "unit": target.unit,
                    "forecast_path": f"/lab/forecasts/{tid}",
                    "cells": cells,
                }
            )
        return dto.MatrixPage.model_validate(
            self.envelope
            | {
                "experiment_id": identity,
                "experiment_title": self.experiment_title(experiment),
                "mode": experiment.mode,
                "columns": [
                    {
                        "forecaster_id": fid,
                        "agent": self.agent_identity(fid),
                        "is_baseline": fid == experiment.baseline_forecaster_id,
                    }
                    for fid in fids
                ],
                "rows": rows,
                "total_targets": total,
                "total_methods": methods,
                "next_cursor": cursor,
                "next_method_cursor": method_cursor,
            }
        )

    def attempt_item(self, identity):
        attempt = self.get(identity, Attempt)
        task = self.get(attempt.task_id, EvaluationTask)
        state = self.attempt_state(attempt)
        selection = self.selection(task)
        run_id = state["effective"].run_id if state["effective"] else None
        run = self.get(run_id, ForecastRun) if run_id else None
        selected = bool(run and selection.run_id == run.id)
        results = []
        for result in state["results"]:
            results.append(
                {
                    "record": link(result),
                    "outcome": result.outcome,
                    "recorded_at": timestamp(result.recorded_at),
                    "completed_at": timestamp(result.completed_at),
                    "exit_code": result.exit_code,
                    "run": link(self.get(result.run_id, ForecastRun))
                    if result.run_id
                    else None,
                    "reconciles_result_id": result.reconciles_result_id,
                    "reconciliation_method": result.reconciliation_method,
                    "reconciliation_verified": state["reconciliation_verified"]
                    if result.reconciles_result_id
                    else None,
                    "evidence_links": self.artifacts(result),
                }
            )
        return {
            "id": attempt.id,
            "record": link(attempt),
            "task_id": task.id,
            "sequence": attempt.sequence,
            "started_at": timestamp(attempt.started_at),
            "execution_policy": attempt.execution_policy,
            "outcome": state["outcome"],
            "selected": selected,
            "selected_run": link(run) if selected else None,
            "observed_model": run.observed_model if run else None,
            "elapsed_seconds": state["elapsed"],
            "elapsed_basis": "recorded_attempt_elapsed"
            if state["elapsed"] is not None
            else None,
            "cost": EMPTY_COST,
            "results": results,
            "evidence_links": self.artifacts(attempt),
        }

    def agent_summary(self, identity):
        experiments = [
            e
            for e in self.by_kind["experiment"]
            if identity in e.forecaster_version_ids
        ]
        for experiment in experiments:
            self.structural_closure(experiment)
        task_ids = {tid for experiment in experiments for tid in experiment.task_ids}
        tasks = [
            self.get(tid, EvaluationTask)
            for tid in task_ids
            if self.get(tid, EvaluationTask).forecaster_version_id == identity
        ]
        counts, _ = self.counts(tasks)
        return self.agent_identity(identity) | {
            "experiment_count": len(experiments),
            # Declared coverage comes from cohort membership, including pairs
            # whose task record is missing. Attempts still use actual tasks.
            "declared_task_count": sum(
                len(experiment.target_version_ids) for experiment in experiments
            ),
            "attempt_counts": counts,
        }

    def agent_detail(self, identity):
        agent = self.get(identity, ForecasterVersion, public=True)
        return dto.AgentDetail.model_validate(
            self.envelope
            | self.agent_summary(identity)
            | {
                "record": link(agent),
                "inference_settings": agent.inference_settings,
                "execution_policy": agent.execution_policy,
                "aggregation": agent.aggregation,
                "retry_policy": agent.retry_policy,
                "prompt_template": self.artifact(
                    agent.prompt_template_hash, "prompt_template"
                ),
                "system_prompt": self.artifact(
                    agent.system_prompt_hash, "system_prompt"
                ),
                "briefing": self.artifact(agent.briefing_hash, "briefing")
                if agent.briefing_hash
                else None,
                "tool_policy": self.artifact(agent.tool_policy_hash, "tool_policy"),
                "experiments_path": f"/lab/agents/{identity}/experiments",
            }
        )

    def operations(self, *, limit=20, after=None):
        # Missing module/tables are unavailable, not an empty successful setup.
        from .polling import public_status

        polling = public_status(self.store)
        schedules = polling["schedules"]
        worker = polling["worker"]
        by_target = {row["target_id"]: row for row in schedules}
        targets = {t.id: t for t in self.by_kind["target_version"]}
        for identity in by_target:
            self.get(identity, TargetVersion)
        ids, cursor, total = _page_ids(targets, limit, after)
        counts = dict.fromkeys(
            ("pending", "leased", "complete", "failed", "unknown", "expired_leases"), 0
        )
        live_forecast_leases, old_forecast_leases = [], []
        for job in self.jobs:
            counts[job["state"]] += 1
            if job["state"] == "leased":
                expired = job["lease_expires_at"] <= self.now
                counts["expired_leases"] += int(expired)
                if job["kind"] == "forecast":
                    (old_forecast_leases if expired else live_forecast_leases).append(
                        job["updated_at"]
                    )
        items = []
        for identity in ids:
            target, schedule = targets[identity], by_target.get(identity)
            resolution = self.resolution(target)
            release = self.release(target)
            attention, recovery = [], []
            if schedule is None and resolution["state"] != "resolved":
                attention.append("capture_not_scheduled")
                recovery.append("schedule_capture")
            if schedule and schedule["state"] == "overdue":
                attention.append("capture_stale")
                recovery.append("inspect_capture")
            if release["state"] == "verified" and resolution["state"] == "pending":
                upper = datetime.fromisoformat(release["upper"])
                selected_vintage_passed = True
                if target.resolution_policy == "fixed_vintage":
                    zone = ZoneInfo(target.release_evidence.timezone)
                    vintage = date.fromisoformat(target.vintage_date)
                    lower = datetime.fromisoformat(release["lower"])
                    # A first-print calendar is not an intraday release promise
                    # for a later revision. Wait until that selected date ends.
                    selected_vintage_passed = (
                        vintage <= lower.astimezone(zone).date()
                        or vintage < self.now.astimezone(zone).date()
                    )
                if upper <= self.now and selected_vintage_passed:
                    attention.append("release_passed_unresolved")
                    if "inspect_capture" not in recovery:
                        recovery.append("inspect_capture")
            if resolution["state"] == "invalid":
                attention.append("resolution_invalid")
                recovery.append("inspect_resolution")
            related = {
                task.id
                for task in self.by_kind["evaluation_task"]
                if task.target_version_id == identity
            }
            if any(
                j["state"] == "failed"
                and (j["subject_id"] in related or j["subject_id"] == identity)
                for j in self.jobs
            ):
                attention.append("job_failed")
                recovery.append("inspect_jobs")
            if any(
                self.attempt_state(a)["outcome"] == "unknown"
                for a in self.by_kind["attempt"]
                if a.task_id in related
            ):
                attention.append("attempt_unknown")
                recovery.append("reconcile_attempt")
            items.append(
                {
                    "target_id": identity,
                    "title": self.target_title(target),
                    "release": release,
                    "resolution": resolution,
                    "polling_state": schedule["state"] if schedule else "not_scheduled",
                    "next_poll_at": schedule["next_poll_at"] if schedule else None,
                    "last_success_at": schedule["last_success_at"]
                    if schedule
                    else None,
                    "attention_codes": attention,
                    "recovery_action_codes": recovery,
                }
            )
        active = [s for s in schedules if s["state"] == "active"]
        next_times = [s["next_poll_at"] for s in active if s["next_poll_at"]]
        success_times = [
            s["last_success_at"] for s in schedules if s["last_success_at"]
        ]
        freshness = live_forecast_leases or old_forecast_leases
        return dto.OperationsSummary.model_validate(
            self.envelope
            | {
                "database": {"state": "available", "checked_at": timestamp(self.now)},
                "jobs": counts,
                "worker": {
                    "state": "observed_active"
                    if live_forecast_leases
                    else "stale"
                    if old_forecast_leases
                    else "unknown",
                    "last_activity_at": timestamp(max(freshness))
                    if freshness
                    else None,
                    "basis": "job_lease_observation" if freshness else "not_reported",
                },
                "polling": {
                    "state": "not_scheduled"
                    if not schedules
                    else "stale"
                    if worker["status"] == "stale"
                    else "scheduled",
                    "scheduled_sources": len(
                        {targets[s["target_id"]].source_series_id for s in schedules}
                    ),
                    "next_poll_at": min(next_times) if next_times else None,
                    "last_success_at": max(success_times) if success_times else None,
                    "worker": worker,
                },
                "items": items,
                "total": total,
                "next_cursor": cursor,
            }
        )


def mount_routes(application, current_store):
    """Mount a closed GET/query surface without changing any legacy endpoint."""
    import re

    from fastapi import HTTPException, Request, Response
    from fastapi.responses import JSONResponse

    from .store import StoreError

    @application.exception_handler(LabNotFound)
    async def missing_lab(_request, _error):
        return JSONResponse({"error": {"code": "lab_not_found"}}, status_code=404)

    def request_options(request, names, *, matrix=False):
        values = {}
        for name in request.query_params:
            if name not in names or len(request.query_params.getlist(name)) != 1:
                raise HTTPException(422, detail={"code": "invalid_request"})
            value = request.query_params[name]
            if name in {"limit", "method_limit"}:
                bound = (20 if name == "limit" else 10) if matrix else 100
                if (
                    re.fullmatch(r"[1-9][0-9]{0,2}", value) is None
                    or int(value) > bound
                ):
                    raise HTTPException(422, detail={"code": "invalid_request"})
                values[name] = int(value)
            elif re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise HTTPException(422, detail={"code": "invalid_request"})
            else:
                values[name] = value
        return values

    def identity(value):
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise HTTPException(422, detail={"code": "invalid_request"})
        return value

    def project(request, response, names=(), *, matrix=False):
        options = request_options(request, names, matrix=matrix)
        response.headers["Cache-Control"] = "no-store"
        return Lab(current_store()), options

    # Request/Response annotations must be in module globals for FastAPI's
    # annotation resolver even though optional web imports stay lazy.
    globals().update(Request=Request, Response=Response)

    @application.get("/lab/forecasts", response_model=dto.ForecastPage)
    def forecasts(request: Request, response: Response):
        lab, options = project(request, response, ("limit", "after"))
        return lab.page(
            [t.id for t in lab.by_kind["target_version"]],
            lab.forecast_summary,
            dto.ForecastPage,
            **options,
        )

    @application.get("/lab/forecasts/{target_id}", response_model=dto.ForecastDetail)
    def forecast(target_id: str, request: Request, response: Response):
        identity(target_id)
        lab, _ = project(request, response)
        return lab.forecast_detail(target_id)

    @application.get(
        "/lab/forecasts/{target_id}/experiments", response_model=dto.ExperimentPage
    )
    def forecast_experiments(target_id: str, request: Request, response: Response):
        identity(target_id)
        lab, options = project(request, response, ("limit", "after"))
        lab.get(target_id, TargetVersion, public=True)
        return lab.page(
            [
                e.id
                for e in lab.by_kind["experiment"]
                if target_id in e.target_version_ids
            ],
            lab.experiment_summary,
            dto.ExperimentPage,
            **options,
        )

    @application.get(
        "/lab/forecasts/{target_id}/comparisons", response_model=dto.ComparisonPage
    )
    def comparisons(target_id: str, request: Request, response: Response):
        identity(target_id)
        lab, options = project(request, response, ("experiment_id", "limit", "after"))
        lab.get(target_id, TargetVersion, public=True)
        experiment_id = options.pop("experiment_id", None)
        if experiment_id is None:
            raise HTTPException(422, detail={"code": "invalid_request"})
        experiment = lab.get(experiment_id, Experiment, public=True)
        if target_id not in experiment.target_version_ids:
            raise LabNotFound("target is outside experiment")
        tasks = lab.experiment_tasks(experiment)
        return lab.page(
            [t.id for (tid, _), t in tasks.items() if tid == target_id],
            lambda task_id: lab.comparison(
                experiment, lab.get(task_id, EvaluationTask)
            ),
            dto.ComparisonPage,
            **options,
        )

    @application.get("/lab/experiments", response_model=dto.ExperimentPage)
    def experiments(request: Request, response: Response):
        lab, options = project(request, response, ("limit", "after"))
        return lab.page(
            [e.id for e in lab.by_kind["experiment"]],
            lab.experiment_summary,
            dto.ExperimentPage,
            **options,
        )

    @application.get(
        "/lab/experiments/{experiment_id}", response_model=dto.ExperimentDetail
    )
    def experiment(experiment_id: str, request: Request, response: Response):
        identity(experiment_id)
        lab, _ = project(request, response)
        return lab.experiment_detail(experiment_id)

    @application.get(
        "/lab/experiments/{experiment_id}/matrix", response_model=dto.MatrixPage
    )
    def matrix(experiment_id: str, request: Request, response: Response):
        identity(experiment_id)
        lab, options = project(
            request,
            response,
            ("limit", "after", "method_limit", "method_after"),
            matrix=True,
        )
        return lab.matrix(experiment_id, **options)

    @application.get(
        "/lab/experiments/{experiment_id}/results",
        response_model=dto.ExperimentResultPage,
    )
    def experiment_results(experiment_id: str, request: Request, response: Response):
        identity(experiment_id)
        lab, options = project(request, response, ("limit", "after"))
        record = lab.get(experiment_id, Experiment, public=True)
        return lab.page(
            record.forecaster_version_ids,
            lambda fid: lab.results(record)[fid],
            dto.ExperimentResultPage,
            **options,
        )

    @application.get("/lab/tasks/{task_id}/attempts", response_model=dto.AttemptPage)
    def attempts(task_id: str, request: Request, response: Response):
        identity(task_id)
        lab, options = project(request, response, ("limit", "after"))
        task = lab.get(task_id, EvaluationTask, public=True)
        return lab.page(
            [a.id for a in lab.task_attempts(task)],
            lab.attempt_item,
            dto.AttemptPage,
            **options,
        )

    @application.get("/lab/agents", response_model=dto.AgentPage)
    def agents(request: Request, response: Response):
        lab, options = project(request, response, ("limit", "after"))
        return lab.page(
            [a.id for a in lab.by_kind["forecaster_version"]],
            lab.agent_summary,
            dto.AgentPage,
            **options,
        )

    @application.get("/lab/agents/{forecaster_id}", response_model=dto.AgentDetail)
    def agent(forecaster_id: str, request: Request, response: Response):
        identity(forecaster_id)
        lab, _ = project(request, response)
        return lab.agent_detail(forecaster_id)

    @application.get(
        "/lab/agents/{forecaster_id}/experiments",
        response_model=dto.ExperimentResultPage,
    )
    def agent_experiments(forecaster_id: str, request: Request, response: Response):
        identity(forecaster_id)
        lab, options = project(request, response, ("limit", "after"))
        lab.get(forecaster_id, ForecasterVersion, public=True)
        ids = [
            e.id
            for e in lab.by_kind["experiment"]
            if forecaster_id in e.forecaster_version_ids
        ]
        return lab.page(
            ids,
            lambda eid: lab.results(lab.get(eid, Experiment))[forecaster_id],
            dto.ExperimentResultPage,
            **options,
        )

    @application.get("/lab/operations", response_model=dto.OperationsSummary)
    def operations(request: Request, response: Response):
        lab, options = project(request, response, ("limit", "after"))
        try:
            return lab.operations(**options)
        except ImportError as exc:
            raise StoreError("polling state unavailable") from exc
