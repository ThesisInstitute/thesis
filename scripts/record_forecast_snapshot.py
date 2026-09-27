#!/usr/bin/env python3
"""Create one immutable, body-archiving forecast-surface snapshot."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any

from canonical_json import canonical_sha256
from ingest_challenge_submissions import ingest_challenge_submissions
from thesis_log_client import load_thesis_log_from_directory
from verify_custody import (
    RECORDER_REQUIRED_LIVE,
    verify_recorder_snapshot,
    verify_run,
)
from verify_record_chain import (
    ChainError,
    ChainVerification,
    _load_trust_bundle,
    logical_path,
    trust_bundle_updates_for_snapshot,
    verify_chain,
)

SURFACES = {
    "log": ("log.json", "https://app.thesisinstitute.org/log.json"),
    "ledger": ("ledger.json", "https://app.thesisinstitute.org/ledger.json"),
    "targets": ("targets.json", "https://app.thesisinstitute.org/targets.json"),
    "reward": ("reward.json", "https://app.thesisinstitute.org/brier/reward.json"),
    "build": ("build.json", "https://app.thesisinstitute.org/build.json"),
    "apiBuild": (
        "api-build.json",
        "https://api.thesisinstitute.org/build.json",
    ),
    "ledgerCommitApi": (
        "ledger-commit.json",
        "https://api.github.com/repos/PolicyEngine/chronicle/commits/"
        "codex/thesis-ledger-facts",
    ),
}

MODEL_PREDICTION_FIELDS = (
    "forecastSlug",
    "pointEstimate",
    "interval80",
    "resolutionDate",
    "recordedAt",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def archive_body(source: Path, destination: Path) -> dict[str, Any]:
    raw = source.read_bytes()
    json.loads(raw)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite archive: {destination}")
    with destination.open("xb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as zipped:
            zipped.write(raw)
    compressed = destination.read_bytes()
    return {
        "sha256": sha256(raw),
        "bytes": len(raw),
        "archivePath": str(destination),
        "archiveSha256": sha256(compressed),
        "archiveBytes": len(compressed),
        "contentEncoding": "gzip",
    }


def exclusive_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def add_trust_bundle_updates(
    payload: dict[str, Any], verification: ChainVerification
) -> None:
    updates = trust_bundle_updates_for_snapshot(verification)
    if updates:
        payload["trustBundleUpdates"] = updates


def require_published_trust_bundles(
    records: Path, verification: ChainVerification
) -> None:
    """Refuse to mint a snapshot that would introduce an unpublished bundle.

    The snapshot names every code-approved bundle the chain has not seen yet.
    ``scripts/publish_trust_bundles.py`` must have written those files first,
    or the witness step would reject the snapshot after it already exists.
    """

    for reference in trust_bundle_updates_for_snapshot(verification):
        try:
            _load_trust_bundle(records.resolve(), reference)
        except ChainError as error:
            raise SystemExit(
                f"cannot introduce {reference['path']}: {error}. Run "
                "scripts/publish_trust_bundles.py before recording."
            ) from error


def current_artifact_commitments(records: Path) -> dict[str, list[dict[str, Any]]]:
    records = records.resolve()
    repository = records.parent
    custody_roots: list[dict[str, Any]] = []
    for root_path in sorted(records.glob("**/custody_root.json")):
        run_dir = root_path.parent
        result = verify_run(run_dir)
        manifest_path = run_dir / "manifest.json"
        custody_roots.append(
            {
                "runDirectory": run_dir.relative_to(repository).as_posix(),
                "custodyRootPath": root_path.relative_to(repository).as_posix(),
                "custodyRootSha256": result.custody_root_sha256,
                "custodyRootFileSha256": sha256(root_path.read_bytes()),
                "custodyRootSize": root_path.stat().st_size,
                "custodyInventoryVersion": result.custody_inventory_version,
                "manifestPath": manifest_path.relative_to(repository).as_posix(),
                "manifestSha256": sha256(manifest_path.read_bytes()),
                "manifestSize": manifest_path.stat().st_size,
            }
        )
    registration_snapshots: list[dict[str, Any]] = []
    for path in sorted((records / "targets").glob("*.json")):
        raw = path.read_bytes()
        payload = json.loads(raw)
        registration_snapshots.append(
            {
                "path": path.relative_to(repository).as_posix(),
                "sha256": sha256(raw),
                "size": len(raw),
                "canonicalJsonSha256": canonical_sha256(payload),
            }
        )
    return {
        "custodyRoots": custody_roots,
        "registrationSnapshots": registration_snapshots,
    }


def build_snapshot_predictions(
    recorded: list[dict[str, Any]],
    challenge_predictions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project model log entries, then append adapter-owned challenge rows."""

    model_predictions = [
        {key: entry.get(key) for key in MODEL_PREDICTION_FIELDS} for entry in recorded
    ]
    return model_predictions + challenge_predictions


def validate_deployment_identity(
    *,
    site_build: dict[str, Any],
    api_build: dict[str, Any],
    site_deployment_url: str,
    api_deployment_url: str,
    expected_sha: str | None,
    ancestry_distance: int,
) -> None:
    if ancestry_distance < 0:
        raise ValueError("deployment ancestry distance must be non-negative")
    if expected_sha and not re.fullmatch(r"[0-9a-fA-F]{40}", expected_sha):
        raise ValueError("expected SHA must be a full commit SHA")
    deployment_pattern = re.compile(r"https://[A-Za-z0-9-]+\.vercel\.app")
    if not deployment_pattern.fullmatch(site_deployment_url):
        raise ValueError("site deployment URL must be an immutable Vercel URL")
    if not deployment_pattern.fullmatch(api_deployment_url):
        raise ValueError("API deployment URL must be an immutable Vercel URL")
    for label, build in (("site", site_build), ("API", api_build)):
        if not re.fullmatch(r"[0-9a-fA-F]{40}", str(build.get("commit") or "")):
            raise ValueError(f"{label} build commit must be a full commit SHA")
    if expected_sha and site_build.get("commit") != expected_sha:
        raise ValueError(
            "site build commit does not exactly match expected SHA: "
            f"{site_build.get('commit')} != {expected_sha}"
        )
    if f"https://{site_build.get('deploymentUrl')}" != site_deployment_url:
        raise ValueError("site build deploymentUrl does not match pinned URL")
    if f"https://{api_build.get('deploymentUrl')}" != api_deployment_url:
        raise ValueError("API build deploymentUrl does not match pinned URL")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, default=Path("records"))
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--recorded-at", required=True)
    parser.add_argument("--repo-sha", required=True)
    parser.add_argument("--ledger-sha", required=True)
    parser.add_argument("--site-deployment-url", required=True)
    parser.add_argument("--api-deployment-url", required=True)
    parser.add_argument("--deployment-ancestry-distance", type=int, required=True)
    parser.add_argument("--expected-sha")
    parser.add_argument("--challenge-inbox", type=Path)
    parser.add_argument("--target-registrations", type=Path)
    args = parser.parse_args()

    if (args.challenge_inbox is None) != (args.target_registrations is None):
        raise SystemExit(
            "--challenge-inbox and --target-registrations must be provided together"
        )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.run_id):
        raise SystemExit(
            "run-id may contain only letters, digits, dot, underscore, dash"
        )
    try:
        build_payload = json.loads((args.source_dir / "build.json").read_text())
        api_build_payload = json.loads((args.source_dir / "api-build.json").read_text())
        validate_deployment_identity(
            site_build=build_payload,
            api_build=api_build_payload,
            site_deployment_url=args.site_deployment_url,
            api_deployment_url=args.api_deployment_url,
            expected_sha=args.expected_sha,
            ancestry_distance=args.deployment_ancestry_distance,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    live_source = args.source_dir / "live"
    live_names = (
        {path.stem for path in live_source.glob("*.json")}
        if live_source.is_dir()
        else set()
    )
    if live_names != set(RECORDER_REQUIRED_LIVE):
        raise SystemExit(
            "source live forecast inventory differs from recorder custody v2: "
            f"missing={sorted(set(RECORDER_REQUIRED_LIVE) - live_names)}, "
            f"extra={sorted(live_names - set(RECORDER_REQUIRED_LIVE))}"
        )
    repo_root = args.records.resolve().parent
    challenge_predictions = (
        ingest_challenge_submissions(
            inbox_dir=args.challenge_inbox,
            targets_dir=args.target_registrations,
            repo_root=repo_root,
        )
        if args.challenge_inbox is not None and args.target_registrations is not None
        else []
    )
    verification = verify_chain(args.records)
    require_published_trust_bundles(args.records, verification)
    previous = verification.ordered[-1]
    day = args.recorded_at[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise SystemExit("recorded-at must begin with an ISO UTC date")

    day_dir = args.records / day
    digest_path = day_dir / f"digest-{args.run_id}.json"
    body_dir = day_dir / f"bodies-{args.run_id}"
    surface_records: dict[str, Any] = {}
    for name, (filename, url) in SURFACES.items():
        source = args.source_dir / filename
        if not source.is_file():
            raise SystemExit(f"missing fetched response body: {source}")
        destination = body_dir / f"{filename}.gz"
        record = archive_body(source, destination)
        record["archivePath"] = str(destination.resolve().relative_to(repo_root))
        record["url"] = url
        if name == "ledgerCommitApi":
            record["fetchedUrl"] = url
        elif name == "apiBuild":
            record["fetchedUrl"] = f"{args.api_deployment_url.rstrip('/')}/build.json"
        else:
            record["fetchedUrl"] = f"{args.site_deployment_url.rstrip('/')}/{filename}"
        surface_records[name] = record

    log_chunk_records: dict[str, Any] = {}
    log_manifest = json.loads((args.source_dir / "log.json").read_text())
    if log_manifest.get("schemaVersion") == "thesis_log_v3":
        for collection, collection_manifest in log_manifest["collections"].items():
            for reference in collection_manifest["chunks"]:
                expected_url = f"/log/{collection}/{reference['index']}.json"
                if reference.get("url") != expected_url:
                    raise SystemExit(
                        f"invalid {collection} log chunk URL: {reference.get('url')!r}"
                    )
                relative = Path(expected_url.lstrip("/"))
                source = args.source_dir / relative
                destination = body_dir / Path(f"{relative}.gz")
                record = archive_body(source, destination)
                record["archivePath"] = str(
                    destination.resolve().relative_to(repo_root)
                )
                record["url"] = urllib.parse.urljoin(
                    "https://app.thesisinstitute.org/log.json", reference["url"]
                )
                record["fetchedUrl"] = urllib.parse.urljoin(
                    f"{args.site_deployment_url.rstrip('/')}/log.json",
                    reference["url"],
                )
                record["manifestSha256"] = reference["sha256"]
                log_chunk_records[f"{collection}:{reference['index']}"] = record

    live_records: dict[str, Any] = {}
    if live_source.is_dir():
        for source in sorted(live_source.glob("*.json")):
            destination = body_dir / "live" / f"{source.name}.gz"
            record = archive_body(source, destination)
            record["archivePath"] = str(destination.resolve().relative_to(repo_root))
            record["fetchedUrl"] = (
                f"{args.api_deployment_url.rstrip('/')}/forecasts/{source.stem}/stream"
            )
            live_records[source.stem] = record

    log = load_thesis_log_from_directory(args.source_dir)
    entries = log.get("entries", [])
    recorded = [
        entry for entry in entries if entry.get("kind") == "prediction_recorded"
    ]
    resolved = [
        entry for entry in entries if entry.get("kind") == "prediction_resolved"
    ]
    predictions = build_snapshot_predictions(recorded, challenge_predictions)
    payload = {
        "schemaVersion": "thesis_record_snapshot_v2",
        "snapshotKind": "recorder_run",
        "custodyInventoryVersion": 2,
        "runMode": "recorder",
        "runId": args.run_id,
        "recordedAt": args.recorded_at,
        "chain": {
            "prevDigestPath": logical_path(args.records.resolve(), previous),
            "prevDigestSha256": sha256(previous.read_bytes()),
        },
        "dependencies": {
            "recorderRepositoryCommit": args.repo_sha,
            "liveDeploymentCommit": build_payload.get("commit"),
            "forecastApiDeploymentCommit": api_build_payload.get("commit"),
            "expectedDeploymentCommit": args.expected_sha,
            "deploymentAncestryDistance": args.deployment_ancestry_distance,
            "siteDeploymentUrl": args.site_deployment_url,
            "forecastApiDeploymentUrl": args.api_deployment_url,
            "ledgerRepository": "PolicyEngine/chronicle",
            "ledgerBranch": "codex/thesis-ledger-facts",
            "ledgerBranchCommit": args.ledger_sha,
            "liveBuildCanary": build_payload,
        },
        "surfaces": surface_records,
        "logChunks": log_chunk_records,
        "liveForecasts": live_records,
        "counts": {"recorded": len(predictions), "resolved": len(resolved)},
        "predictions": predictions,
        "resolutions": resolved,
        "artifactCommitments": current_artifact_commitments(args.records),
    }
    add_trust_bundle_updates(payload, verification)
    exclusive_json_write(digest_path, payload)
    verify_recorder_snapshot(digest_path)

    index_path = day_dir / "index.json"
    snapshots = sorted(
        path.name
        for path in day_dir.glob("digest-*.json")
        if not path.name.endswith(".witness.json")
    )
    index_path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_record_day_index_v1",
                "integrityNote": "informational only; chain links are authoritative",
                "snapshots": snapshots,
            },
            indent=2,
        )
        + "\n"
    )
    print(digest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
