"""Recoverable local orchestration; scientific operations stay in their modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .contracts import Experiment, PublicationManifest
from .evaluation import select_first_valid, validate_experiment
from .store import AcknowledgementPending, JobSpec, LeaseLost

if TYPE_CHECKING:
    from .store import Store


def schedule_experiment(
    store: Store, experiment_id: str, *, cohort_proof_id: str | None = None
) -> int:
    """Idempotently queue the next authorized attempt, never an unknown attempt."""
    from .publication import verify_cohort_for_dispatch
    from .resolution import scientific_followups
    from .service import context_for_store

    experiment = store.get(experiment_id)
    if not isinstance(experiment, Experiment):
        raise ValueError("Expected experiment")
    context = context_for_store(store)
    tasks = validate_experiment(experiment, context)
    queued = 0
    for task in tasks:
        attempts = tuple(store.iter_records("attempt", links={"task": task.id}))
        selection = select_first_valid(task, context)
        if (
            selection.run_id
            or selection.reason == "unresolved_attempt"
            or len(attempts) >= task.max_attempts
        ):
            continue
        if experiment.mode == "prospective":
            if cohort_proof_id is None:
                raise ValueError("Prospective dispatch requires a prior cohort proof")
            verify_cohort_for_dispatch(store, task, experiment_id, cohort_proof_id)
        payload = {"experiment_id": experiment_id, "cohort_proof_id": cohort_proof_id}
        store.enqueue(
            "forecast",
            task.id,
            payload,
            idempotency_key=f"forecast:{task.id}:{len(attempts) + 1}",
        )
        queued += 1
    with store.transaction() as transaction:
        for job in scientific_followups(store, experiment):
            transaction.enqueue(
                job.kind,
                job.subject_id,
                job.payload,
                idempotency_key=job.idempotency_key,
            )
    return queued


def repair_followups(store: Store) -> int:
    """A crash after a sealed run can only repeat publication, never generation."""
    queued = 0
    for run in store.iter_records("forecast_run"):
        task = store.get(store.get(run.attempt_id).task_id)
        experiments = tuple(store.iter_records("experiment", links={"task": task.id}))
        if len(experiments) != 1:
            continue
        store.enqueue(
            "publish_run",
            run.id,
            {"experiment_id": experiments[0].id},
            idempotency_key=f"publish-run:{run.id}",
        )
        queued += 1
    return queued


def _run_manifest(store: Store, experiment_id: str, run_id: str) -> PublicationManifest:
    from .publication import create_manifest

    existing = tuple(store.iter_records("publication_manifest", links={"run": run_id}))
    for manifest in existing:
        if manifest.experiment_id == experiment_id:
            return manifest
    return create_manifest(store, experiment_id, run_id=run_id)


def work_once(
    store: Store,
    *,
    worker_id: str = "local",
    kinds: tuple[str, ...] | None = None,
    timeout_seconds: float = 120,
) -> dict | None:
    """Process one leased job. Failed publication remains independently retryable."""
    store.repair_acceptances()
    store.recover_expired()
    store.deliver_outbox()
    claim = store.claim(worker_id, kinds, lease_seconds=max(60, timeout_seconds + 30))
    if claim is None:
        return None
    try:
        completion_followups = ()
        if claim.kind == "forecast":
            from .execution import execute_forecast
            from .publication import verify_cohort_for_dispatch

            def verify_cohort_proof(*, experiment_id, cohort_proof_id, task_id):
                return verify_cohort_for_dispatch(
                    store, store.get(task_id), experiment_id, cohort_proof_id
                ).token_hash

            def publication_followups(run):
                from .resolution import scientific_followups

                return (
                    JobSpec(
                        "publish_run",
                        run.id,
                        f"publish-run:{run.id}",
                        {"experiment_id": claim.payload["experiment_id"]},
                    ),
                    *scientific_followups(store, run),
                )

            run = execute_forecast(
                store,
                claim,
                timeout_seconds=timeout_seconds,
                lease_seconds=max(60, timeout_seconds + 30),
                verify_cohort_proof=verify_cohort_proof,
                followups=publication_followups,
            )
            return {
                "job_id": claim.job_id,
                "kind": claim.kind,
                "run_id": run.id if run else None,
            }
        if claim.kind == "publish_run":
            from .publication import publish_manifest, verify_proof
            from .resolution import scientific_followups

            manifest = _run_manifest(
                store, claim.payload["experiment_id"], claim.subject_id
            )
            existing = tuple(
                store.iter_records("publication_proof", links={"manifest": manifest.id})
            )
            verified = [proof for proof in existing if verify_proof(store, proof)]
            if not verified:
                verified = [publish_manifest(store, manifest.id)]
            completion_followups = tuple(
                job for proof in verified for job in scientific_followups(store, proof)
            )
        elif claim.kind == "publish":
            from .publication import publish_manifest
            from .resolution import scientific_followups

            proof = publish_manifest(store, claim.subject_id)
            completion_followups = scientific_followups(store, proof)
        elif claim.kind == "resolve":
            from .resolution import resolve_target

            if resolve_target(store, claim.subject_id) is None:
                raise ValueError("Target has no matching captured outcome yet")
        elif claim.kind == "evaluate":
            from .service import evaluate_experiment

            evaluate_experiment(store, claim.subject_id)
        else:
            raise ValueError(f"Unknown worker job kind: {claim.kind}")
        store.finish(claim, outcome="succeeded", followups=completion_followups)
        return {"job_id": claim.job_id, "kind": claim.kind, "status": "succeeded"}
    except AcknowledgementPending as exc:
        # The scientific transaction is already durable. Never compensate it.
        return {
            "job_id": claim.job_id,
            "status": "acknowledgement_pending",
            "record_ids": list(exc.record_ids),
        }
    except LeaseLost:
        return {"job_id": claim.job_id, "status": "lease_lost"}
    except Exception as exc:
        from .diagnostics import safe_exception_text

        failure = {
            "job_id": claim.job_id,
            "kind": claim.kind,
            "error": safe_exception_text(exc),
            "artifact_hash": getattr(exc, "artifact_hash", None),
        }
        # Only the executor can attest an observed terminal model outcome.
        # A transport, database, or sealing exception after dispatch is uncertain,
        # even if this worker is still alive. Recovery will persist unknown when
        # the lease expires. Never manufacture a failure that authorizes retry.
        try:
            job = store.job(claim.job_id)
        except Exception:
            return {**failure, "status": "state_unavailable"}
        if job is None:
            return {**failure, "status": "state_unavailable"}
        if job["state"] in {"complete", "failed", "unknown"}:
            return {**failure, "status": job["state"]}
        if job["dispatched_attempt_id"] is not None:
            return {
                **failure,
                "status": "execution_uncertain",
                "attempt_id": job["dispatched_attempt_id"],
            }
        try:
            store.finish(claim, outcome="failed")
        except (LeaseLost, AcknowledgementPending):
            pass
        return {**failure, "status": "failed"}
