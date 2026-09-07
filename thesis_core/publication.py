"""Publish and independently replay manifests over the complete artifact graph."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from . import tsa
from .artifacts import ArtifactError
from .canonical import canonical_bytes
from .contracts import (
    EvaluationTask,
    Experiment,
    ForecastRun,
    PublicationManifest,
    PublicationProof,
    record_artifact_hashes,
)
from .evaluation import Availability, VerifiedPublication
from .store import StoreError

if TYPE_CHECKING:
    from .store import Store

VERIFICATION_VERSION = "pinned_rfc3161_manifest_v1"


def database_now(store: Store) -> datetime:
    with store.connection() as connection:
        return connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]


def archive_code(store: Store) -> str:
    """Archive the actual installed core source, including public trust assets."""
    root = Path(__file__).parent
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".sql", ".json", ".pem"}:
            files[str(path.relative_to(root))] = path.read_bytes().hex()
    return store.artifacts.put_bytes(
        canonical_bytes({"format": "thesis_core_source_v1", "files": files})
    )


def _closure_artifacts(
    store: Store,
    experiment_id: str,
    run_id: str | None,
    code_hash: str,
    attempt_result_ids: tuple[str, ...] = (),
) -> tuple[str, ...]:
    records = {r.id: r for r in store.dependency_closure(experiment_id)}
    if run_id:
        records.update((r.id, r) for r in store.dependency_closure(run_id))
    for identity in attempt_result_ids:
        records.update((r.id, r) for r in store.dependency_closure(identity))
    hashes = {code_hash}
    for record in records.values():
        if store.committed_at(record.id) is None:
            raise ValueError("Manifest dependency lacks a postcommit acknowledgement")
        hashes.add(record.id)
        hashes.update(record_artifact_hashes(record))
    for digest in hashes:
        store.artifacts.read_bytes(digest)
    return tuple(sorted(hashes))


def _boundaries(
    store: Store, experiment: Experiment, run_id: str | None
) -> tuple[datetime, datetime]:
    tasks = [store.get(tid) for tid in experiment.task_ids]
    if len({task.information_cutoff for task in tasks}) != 1:
        raise ValueError("Experiment must have one declared information cutoff")
    if run_id:
        run = store.get(run_id)
        if not isinstance(run, ForecastRun):
            raise ValueError("Run manifest requires a forecast run")
        task_id = store.get(run.attempt_id).task_id
        if task_id not in experiment.task_ids:
            raise ValueError("Run does not belong to experiment")
        tasks = [store.get(task_id)]
    freezes = [store.committed_at(task.evidence_bundle_id) for task in tasks]
    if not all(freezes):
        raise ValueError("Evidence bundle has no authoritative freeze acknowledgement")
    return tasks[0].information_cutoff, max(freezes)


def _selection_results(store: Store, run_id: str | None) -> tuple[str, ...]:
    if run_id is None:
        return ()
    from .evaluation import select_first_valid
    from .service import context_for_store

    attempt = store.get(store.get(run_id).attempt_id)
    selection = select_first_valid(store.get(attempt.task_id), context_for_store(store))
    if selection.run_id != run_id or selection.reason:
        raise ValueError("Run is not the first valid resolved attempt")
    return selection.result_ids


def create_manifest(
    store: Store, experiment_id: str, *, run_id: str | None = None
) -> PublicationManifest:
    from .evaluation import validate_experiment
    from .service import context_for_store

    experiment = store.get(experiment_id)
    if not isinstance(experiment, Experiment):
        raise ValueError("Expected an experiment")
    validate_experiment(experiment, context_for_store(store))
    cutoff, freeze = _boundaries(store, experiment, run_id)
    cohort_id = cohort_token = None
    if run_id:
        attempt = store.get(store.get(run_id).attempt_id)
        cohort_id, cohort_token = attempt.cohort_proof_id, attempt.cohort_token_hash
    code_hash = (
        store.get(store.get(run_id).attempt_id).code_hash
        if run_id
        else archive_code(store)
    )
    result_ids = _selection_results(store, run_id)
    manifest = PublicationManifest(
        manifest_type="run" if run_id else "cohort",
        experiment_id=experiment_id,
        run_id=run_id,
        artifacts=_closure_artifacts(
            store, experiment_id, run_id, code_hash, result_ids
        ),
        attempt_result_ids=result_ids,
        code_hash=code_hash,
        recorded_at=database_now(store),
        cohort_proof_id=cohort_id,
        cohort_token_hash=cohort_token,
        declared_information_cutoff=cutoff,
        effective_information_boundary=freeze,
    )
    store.put(manifest)
    return manifest


def subject_bytes(manifest: PublicationManifest) -> bytes:
    # The shared custody verifier authenticates this exact top-level creation claim.
    return canonical_bytes(
        {
            "format": "thesis_core_manifest_v1",
            "manifestId": manifest.id,
            "recordedAt": manifest.recorded_at.isoformat().replace("+00:00", "Z"),
            "manifest": manifest.canonical_payload(),
        }
    )


def publish_manifest(
    store: Store, manifest_id: str, *, anchor_id: str = tsa.DEFAULT_ANCHOR_ID
) -> PublicationProof:
    manifest = store.get(manifest_id)
    if not isinstance(manifest, PublicationManifest):
        raise ValueError("Expected a publication manifest")
    _validate_manifest(store, manifest)
    subject = subject_bytes(manifest)
    store.artifacts.put_bytes(subject)
    try:
        receipt = tsa.request_and_verify(
            subject, manifest.recorded_at, anchor_id=anchor_id
        )
    except tsa.TsaError as exc:
        from .diagnostics import safe_exception_text

        request_hash = (
            store.artifacts.put_bytes(exc.request_der) if exc.request_der else None
        )
        response_hash = (
            store.artifacts.put_bytes(exc.response_der) if exc.response_der else None
        )
        error_hash = store.artifacts.put_bytes(
            canonical_bytes(
                {
                    "manifest_id": manifest_id,
                    "request_hash": request_hash,
                    "response_hash": response_hash,
                    "error": safe_exception_text(exc),
                }
            )
        )
        if hasattr(store, "log_publication_attempt"):
            store.log_publication_attempt(
                manifest_id,
                request_hash=request_hash,
                response_hash=response_hash,
                error_hash=error_hash,
            )
        exc.artifact_hash = error_hash
        raise
    if receipt.request_der is None:
        raise ValueError("Timestamp adapter did not archive its query")
    proof = PublicationProof(
        manifest_id=manifest.id,
        request_hash=store.artifacts.put_bytes(receipt.request_der),
        token_hash=store.artifacts.put_bytes(receipt.response_der),
        subject_hash=store.artifacts.put_bytes(subject),
        trust_bundle_path=receipt.trust_bundle_path,
        trust_bundle_hash=store.artifacts.put_bytes(
            tsa._read_asset(receipt.trust_bundle_path)
        ),
        trust_anchor_id=receipt.anchor_id,
        gen_time=receipt.gen_time,
        accuracy_micros=receipt.accuracy_micros,
        signer_identity=receipt.tsa_spki_sha256,
        policy_oid=receipt.policy_oid,
        verification_version=VERIFICATION_VERSION,
        verified_at=database_now(store),
    )
    from .resolution import scientific_followups

    followups = scientific_followups(store, proof)
    with store.transaction() as transaction:
        transaction.put(proof)
        for job in followups:
            transaction.enqueue(
                job.kind,
                job.subject_id,
                job.payload,
                idempotency_key=job.idempotency_key,
            )
    if hasattr(store, "log_publication_attempt"):
        store.log_publication_attempt(
            manifest_id,
            request_hash=proof.request_hash,
            response_hash=proof.token_hash,
            error_hash=None,
        )
    return proof


def _validate_manifest(store: Store, manifest: PublicationManifest) -> None:
    experiment = store.get(manifest.experiment_id)
    if not isinstance(experiment, Experiment):
        raise ValueError("Manifest experiment is invalid")
    cutoff, freeze = _boundaries(store, experiment, manifest.run_id)
    if (
        manifest.declared_information_cutoff,
        manifest.effective_information_boundary,
    ) != (cutoff, freeze):
        raise ValueError("Manifest information boundaries differ from stored evidence")
    expected = _closure_artifacts(
        store,
        experiment.id,
        manifest.run_id,
        manifest.code_hash,
        manifest.attempt_result_ids,
    )
    if manifest.attempt_result_ids != _selection_results(store, manifest.run_id):
        raise ValueError(
            "Manifest does not bind the exact first-valid selection evidence"
        )
    if manifest.artifacts != expected:
        raise ValueError(
            "Manifest does not enumerate the exact dependency artifact closure"
        )
    if manifest.run_id:
        attempt = store.get(store.get(manifest.run_id).attempt_id)
        if manifest.code_hash != attempt.code_hash:
            raise ValueError("Run manifest changed the code frozen before dispatch")
        if (manifest.cohort_proof_id, manifest.cohort_token_hash) != (
            attempt.cohort_proof_id,
            attempt.cohort_token_hash,
        ):
            raise ValueError("Run manifest substituted its prior cohort receipt")


def verify_proof(store: Store, proof: PublicationProof) -> VerifiedPublication | None:
    """Raw bytes and pinned policy decide validity; metadata never grants trust."""
    try:
        manifest = store.get(proof.manifest_id)
        if not isinstance(manifest, PublicationManifest):
            return None
        _validate_manifest(store, manifest)
        if (
            store.committed_at(proof.id) is None
            or store.committed_at(manifest.id) is None
        ):
            return None
        subject = store.artifacts.read_bytes(proof.subject_hash)
        if subject != subject_bytes(manifest):
            return None
        receipt = tsa.verify_receipt(
            subject,
            store.artifacts.read_bytes(proof.token_hash),
            request=store.artifacts.read_bytes(proof.request_hash),
            anchor_id=proof.trust_anchor_id,
            trust_bundle_path=proof.trust_bundle_path,
        )
        if (
            receipt.trust_bundle_path,
            receipt.trust_bundle_sha256,
            receipt.gen_time,
            receipt.accuracy_micros,
            receipt.tsa_spki_sha256,
            receipt.policy_oid,
        ) != (
            proof.trust_bundle_path,
            proof.trust_bundle_hash,
            proof.gen_time,
            proof.accuracy_micros,
            proof.signer_identity,
            proof.policy_oid,
        ):
            return None
        if proof.verification_version != VERIFICATION_VERSION:
            return None
        if store.artifacts.read_bytes(proof.trust_bundle_hash) != tsa._read_asset(
            proof.trust_bundle_path
        ):
            return None
        interval = None
        if receipt.accuracy_micros is not None:
            accuracy = timedelta(microseconds=receipt.accuracy_micros)
            interval = Availability(
                receipt.gen_time - accuracy, receipt.gen_time + accuracy
            )
        return VerifiedPublication(proof.id, manifest.id, proof.token_hash, interval)
    except (ValueError, KeyError, OSError, ArtifactError, StoreError, tsa.TsaError):
        return None


def verify_cohort_for_dispatch(
    store: Store, task: EvaluationTask, experiment_id: str, proof_id: str
) -> PublicationProof:
    """Refuse prospective invocation unless an independent prior cohort is ordered."""
    from .evaluation import outcome_boundary, validate_experiment
    from .service import context_for_store

    experiment = store.get(experiment_id)
    proof = store.get(proof_id)
    if not isinstance(experiment, Experiment) or not isinstance(
        proof, PublicationProof
    ):
        raise ValueError("Invalid dispatch cohort")
    context = context_for_store(store)
    tasks = validate_experiment(experiment, context)
    if task.id not in experiment.task_ids:
        raise ValueError("Task is outside dispatch cohort")
    verified = verify_proof(store, proof)
    manifest = store.get(proof.manifest_id)
    if (
        verified is None
        or verified.interval is None
        or manifest.manifest_type != "cohort"
        or manifest.experiment_id != experiment.id
    ):
        raise ValueError("Cohort lacks an independently ordered receipt")
    boundaries = [
        outcome_boundary(store.get(t.target_version_id), context) for t in tasks
    ]
    if any(t is None for t in boundaries):
        raise ValueError("Cohort outcome availability is unknown")
    cutoff, freeze = _boundaries(store, experiment, None)
    deadline = min(
        experiment.registration_deadline,
        cutoff,
        *(t.submission_deadline for t in tasks),
        *boundaries,
    )
    now = database_now(store)
    if (
        not freeze
        < verified.interval.lower
        <= verified.interval.upper
        < min(deadline, now)
    ):
        raise ValueError("Cohort/freeze/dispatch boundaries are not strictly ordered")
    if now >= min(
        task.submission_deadline,
        outcome_boundary(store.get(task.target_version_id), context),
    ):
        raise ValueError("Task dispatch is too late")
    return proof
