"""Local mutation commands and read-only service entry point."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp must include a timezone")
    return result


def _print(value) -> None:
    print(
        json.dumps(
            value,
            default=lambda x: (
                x.isoformat()
                if isinstance(x, (date, datetime))
                else x.canonical_payload()
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="thesis-core", description=__doc__)
    p.add_argument("--dsn", default=os.environ.get("THESIS_CORE_DSN"))
    p.add_argument(
        "--artifacts",
        default=os.environ.get("THESIS_CORE_ARTIFACTS", ".thesis-core/artifacts"),
    )
    p.add_argument(
        "--schema", default=os.environ.get("THESIS_CORE_SCHEMA", "thesis_core")
    )
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Apply PostgreSQL migrations")
    commands.add_parser("health")
    commands.add_parser("sources", help="List exact registered source bindings")
    artifact = commands.add_parser(
        "artifact", help="Archive a local file and print its SHA256"
    )
    artifact.add_argument("file", type=Path)
    register = commands.add_parser(
        "register", help="Validate and commit canonical scientific JSON"
    )
    register.add_argument("file", type=Path)
    register.add_argument("--kind", required=True)
    register.add_argument("--expected-id")
    legacy = commands.add_parser(
        "import-legacy",
        help="Copy a custody-verified sealed run without upgrading trust",
    )
    legacy.add_argument("run_directory", type=Path)
    legacy.add_argument("--trusted-checkout", required=True, type=Path)
    capture = commands.add_parser(
        "capture", help="Capture official raw data before parsing"
    )
    capture.add_argument("adapter_id")
    capture.add_argument("--measurement-period")
    capture.add_argument("--release-date", type=date.fromisoformat)
    capture.add_argument("--mode", choices=("live", "replay"), default="live")
    release = commands.add_parser("release-evidence")
    release.add_argument("adapter_id")
    release.add_argument("measurement_period")
    replay = commands.add_parser(
        "prepare-replay", help="Create an explicitly historical pilot cohort"
    )
    replay.add_argument("--adapter-id", default="statcan-cpi-yoy")
    replay.add_argument(
        "--argv-json", help="Exact model argv JSON vector; omit for baseline only"
    )
    live = commands.add_parser(
        "prepare-live-pilot", help="Preregister a future, permanently unranked pilot"
    )
    live.add_argument("measurement_period")
    live.add_argument("--adapter-id", default="statcan-cpi-yoy")
    live.add_argument(
        "--argv-json", help="PATH command argv JSON; omit for baseline only"
    )
    schedule = commands.add_parser("schedule")
    schedule.add_argument("experiment_id")
    schedule.add_argument("--cohort-proof-id")
    poll_schedule = commands.add_parser(
        "schedule-source", help="Register bounded official outcome polling for a target"
    )
    poll_schedule.add_argument("target_id")
    poll_schedule.add_argument("--interval", type=int, default=1800)
    poll_schedule.add_argument("--max-polls", type=int, default=96)
    poll_schedule.add_argument("--grace", type=int, default=86400)
    poll = commands.add_parser(
        "poll", help="Capture one due source and process only nonforecast follow-ups"
    )
    poll.add_argument("--max-jobs", type=int, default=20)
    commands.add_parser("poll-status", help="Show safe source polling status")
    manifest = commands.add_parser("manifest")
    manifest.add_argument("experiment_id")
    manifest.add_argument("--run-id")
    publish = commands.add_parser("publish")
    publish.add_argument("manifest_id")
    publish.add_argument("--anchor-id", default="freetsa-root-2016")
    verify = commands.add_parser("verify-proof")
    verify.add_argument("proof_id")
    work = commands.add_parser("work")
    work.add_argument("--worker-id", default="local")
    work.add_argument("--max-jobs", type=int, default=1)
    work.add_argument("--kind", action="append")
    work.add_argument("--timeout", type=float, default=120)
    commands.add_parser(
        "repair", help="Repair missing acknowledgements and publication outbox"
    )
    commands.add_parser("jobs")
    retry = commands.add_parser(
        "retry-job", help="Retry a failed non-attempt job, preserving the sealed result"
    )
    retry.add_argument("job_id", type=int)
    retry.add_argument("--actor", default="operator")
    retry.add_argument("--reason", default="Explicit retry")
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("job_id", type=int)
    reconcile.add_argument("--actor", required=True)
    reconcile.add_argument("--reason", required=True)
    reconcile.add_argument("--evidence-hash", action="append", default=[])
    resolve = commands.add_parser("resolve")
    resolve.add_argument("target_id")
    resolve.add_argument("--observation-id")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("experiment_id")
    export = commands.add_parser(
        "export", help="Export rewards with complete as-of dependency checks"
    )
    export.add_argument("--experiment-id")
    export.add_argument("--as-of", required=True, type=_time)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8100)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    # Help and package import remain usable without the optional core runtime.
    from .artifacts import LocalArtifactStore

    artifacts = LocalArtifactStore(args.artifacts)
    if args.command == "artifact":
        _print(
            {
                "sha256": artifacts.put_bytes(args.file.read_bytes()),
                "bytes": args.file.stat().st_size,
            }
        )
        return 0
    if args.command == "sources":
        from .adapters.registry import registered_sources

        _print(
            {
                key: {"id": value.id, "payload": value.canonical_payload()}
                for key, value in registered_sources().items()
            }
        )
        return 0
    if not args.dsn:
        parser().error("Set THESIS_CORE_DSN or pass --dsn")
    from .store import AcknowledgementPending, Store

    store = Store(args.dsn, artifacts, schema=args.schema)
    try:
        result = _dispatch(args, store)
        if result is not None:
            _print(result)
        return 0
    except AcknowledgementPending as exc:
        _print(
            {
                "status": "acknowledgement_pending",
                "record_ids": list(exc.record_ids),
                "next": (
                    "Run thesis-core repair; "
                    "the scientific operation already committed."
                ),
            }
        )
        return 2


def _dispatch(args, store):
    command = args.command
    if command == "init":
        store.migrate()
        return store.health()
    if command == "health":
        return store.health()
    if command == "register":
        from .contracts import (
            Experiment,
            ForecasterVersion,
            ObservationVintage,
            Resolution,
            SourceExchange,
            SourceSeries,
            TargetVersion,
            parse_record,
        )

        record = parse_record(args.kind, args.file.read_bytes())
        if isinstance(record, SourceSeries):
            from .adapters.registry import validate_source

            validate_source(record)
        if isinstance(record, ObservationVintage):
            from .adapters.registry import validate_observation

            source = store.get(record.source_series_id)
            exchanges = {
                identity: store.get(identity) for identity in record.source_exchange_ids
            }
            if not isinstance(source, SourceSeries) or any(
                not isinstance(exchange, SourceExchange)
                for exchange in exchanges.values()
            ):
                raise ValueError("observation source or exchange has wrong kind")
            validate_observation(record, source, exchanges, store.artifacts)
        if isinstance(record, ForecasterVersion):
            from .security import is_credential_key, redact_value

            payload = record.canonical_payload()
            registered_argv = record.inference_settings.get("argv", [])
            if redact_value(payload) != payload or (
                isinstance(registered_argv, list)
                and any(
                    isinstance(argument, str)
                    and argument.startswith("-")
                    and is_credential_key(argument.lstrip("-").split("=", 1)[0])
                    for argument in registered_argv
                )
            ):
                raise ValueError("forecaster configuration contains credential fields")
        if isinstance(record, Experiment):
            from .evaluation import validate_experiment
            from .service import context_for_store

            validate_experiment(record, context_for_store(store))
        if isinstance(record, Resolution):
            from .resolution import validate_resolution

            target = store.get(record.target_version_id)
            observation = store.get(record.observation_id)
            if (
                not isinstance(target, TargetVersion)
                or not isinstance(observation, ObservationVintage)
                or not validate_resolution(store, record, target, observation)
            ):
                raise ValueError(
                    "resolution does not match the registered source contract"
                )
        from .resolution import scientific_followups

        jobs = scientific_followups(store, record)
        with store.transaction() as transaction:
            identity = transaction.put(record, expected_id=args.expected_id)
            for job in jobs:
                transaction.enqueue(
                    job.kind,
                    job.subject_id,
                    job.payload,
                    idempotency_key=job.idempotency_key,
                )
        return {"id": identity}
    if command == "import-legacy":
        from .legacy import import_legacy_run

        imported = import_legacy_run(
            args.trusted_checkout, args.run_directory, store.artifacts
        )
        store.put(imported)
        return {"id": imported.id, "trust_class": imported.trust_class}
    if command == "capture":
        from .resolution import capture_source

        result = capture_source(
            store,
            args.adapter_id,
            measurement_period=args.measurement_period,
            release_date=args.release_date,
            mode=args.mode,
        )
        return {
            "source_id": result.source.id,
            "status": result.status,
            "observations": [r.id for r in result.observations],
            "exchanges": [r.id for r in result.exchanges],
            "errors": result.errors,
        }
    if command == "release-evidence":
        from .adapters.registry import capture_release_evidence, get_source

        exchange, evidence = capture_release_evidence(
            args.adapter_id, args.measurement_period, store.artifacts
        )
        with store.transaction() as transaction:
            transaction.put(get_source(args.adapter_id))
            transaction.put(exchange)
        return {
            "exchange_id": exchange.id,
            "release_evidence": evidence.model_dump(mode="json"),
        }
    if command in {"prepare-replay", "prepare-live-pilot"}:
        from .pilot import prepare_live_pilot, prepare_replay

        argv = json.loads(args.argv_json) if args.argv_json else None
        if argv is not None and (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(argument, str) and argument for argument in argv)
        ):
            raise ValueError("--argv-json must be a nonempty JSON string array")
        if command == "prepare-live-pilot":
            experiment = prepare_live_pilot(
                store, args.measurement_period, args.adapter_id, argv=argv
            )
            task = store.get(experiment.task_ids[0])
            target = store.get(experiment.target_version_ids[0])
            from .evaluation import source_availability_interval

            release = target.release_evidence
            boundary = source_availability_interval(release.raw_value, release.timezone)
            return {
                "experiment_id": experiment.id,
                "mode": experiment.mode,
                "ranking_policy": experiment.ranking_policy,
                "rank_eligible": False,
                "target_ids": experiment.target_version_ids,
                "information_cutoff": task.information_cutoff,
                "registration_deadline": experiment.registration_deadline,
                "submission_deadline": task.submission_deadline,
                "release_lower_boundary": boundary.lower,
                "poll_binding": {
                    "target_id": target.id,
                    "adapter_id": args.adapter_id,
                    "measurement_period": target.measurement_period,
                    "vintage_date": target.vintage_date,
                },
                "forecast_dispatched": False,
            }
        experiment = prepare_replay(store, args.adapter_id, argv=argv)
        return {
            "experiment_id": experiment.id,
            "mode": experiment.mode,
            "target_ids": experiment.target_version_ids,
        }
    if command == "schedule":
        from .worker import schedule_experiment

        return {
            "queued": schedule_experiment(
                store, args.experiment_id, cohort_proof_id=args.cohort_proof_id
            )
        }
    if command == "schedule-source":
        from .polling import schedule_source

        return schedule_source(
            store,
            args.target_id,
            interval_seconds=args.interval,
            max_polls=args.max_polls,
            grace_seconds=args.grace,
        )
    if command == "poll":
        from .polling import poll_once

        return poll_once(store, max_jobs=args.max_jobs)
    if command == "poll-status":
        from .polling import public_status

        return public_status(store)
    if command == "manifest":
        from .publication import create_manifest

        result = create_manifest(store, args.experiment_id, run_id=args.run_id)
        return {"manifest_id": result.id, "payload": result.canonical_payload()}
    if command == "publish":
        from .publication import publish_manifest

        result = publish_manifest(store, args.manifest_id, anchor_id=args.anchor_id)
        return {"proof_id": result.id, "payload": result.canonical_payload()}
    if command == "verify-proof":
        from .publication import verify_proof

        result = verify_proof(store, store.get(args.proof_id))
        return {
            "valid": result is not None,
            "ordered": result is not None and result.interval is not None,
        }
    if command == "work":
        from .worker import work_once

        if not 1 <= args.max_jobs <= 10000:
            raise ValueError("max-jobs must be in 1..10000")
        results = []
        for _ in range(args.max_jobs):
            result = work_once(
                store,
                worker_id=args.worker_id,
                kinds=tuple(args.kind) if args.kind else None,
                timeout_seconds=args.timeout,
            )
            if result is None:
                break
            results.append(result)
        return {"items": results}
    if command == "repair":
        from .resolution import repair_scientific_followups
        from .worker import repair_followups

        return {
            "acknowledgements": store.repair_acceptances(),
            "leases": store.recover_expired(),
            "publication_followups": repair_followups(store),
            "scientific_followups": repair_scientific_followups(store),
        }
    if command == "jobs":
        return {"items": store.jobs()}
    if command == "retry-job":
        return store.retry_job(args.job_id, actor=args.actor, reason=args.reason)
    if command == "reconcile":
        return store.reconcile_unknown(
            args.job_id,
            actor=args.actor,
            reason=args.reason,
            evidence_hashes=args.evidence_hash,
        )
    if command == "resolve":
        from .resolution import resolve_target

        result = resolve_target(store, args.target_id, args.observation_id)
        return {"resolution_id": result.id if result else None}
    if command == "evaluate":
        from .service import evaluate_experiment

        results = evaluate_experiment(store, args.experiment_id)
        return {
            "items": [
                {"score": r.score.canonical_payload(), "details": r.details}
                for r in results
            ]
        }
    if command == "export":
        from .service import reward_rows

        return {
            "as_of": args.as_of,
            "items": reward_rows(store, args.experiment_id, as_of=args.as_of),
        }
    if command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(store), host=args.host, port=args.port)
        return None
    raise ValueError(f"Unknown command {command}")
