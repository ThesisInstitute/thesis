#!/usr/bin/env python3
"""Move unprivileged docket output across the publication trust boundary."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import shutil
import stat
import subprocess
import sys
from typing import Any

from canonical_json import canonical_bytes
from register_targets import (
    REGISTRATION_SCHEMA,
    V2_REGISTRATION_SCHEMA,
    V3_REGISTRATION_CUTOVER_COMMIT,
    RegistrationError,
    parse_utc_instant,
    registration_content_hash,
    require_conditional_docket_template,
    validate_target_resolution_projection,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]

BUNDLE_SCHEMA = "thesis_docket_publication_bundle_v2"
ALLOWED_DATA_SUFFIXES = {".json", ".jsonl", ".log", ".md", ".txt"}
CODE_SUFFIXES = {
    ".cjs",
    ".js",
    ".jsx",
    ".mjs",
    ".py",
    ".sh",
    ".ts",
    ".tsx",
}
BATCH_RE = re.compile(
    r"^records/thesis-analyst/batches/(?P<day>\d{4}-\d{2}-\d{2})/"
    r"[a-z0-9][a-z0-9._-]*\.json$"
)
RUN_MANIFEST_RE = re.compile(
    r"^records/thesis-analyst/(?P<day>\d{4}-\d{2}-\d{2})/"
    r"(?P<run>\d{4}-\d{2}-\d{2}t\d{2}-\d{2}-\d{2}z-[a-z0-9][a-z0-9-]*)/"
    r"manifest\.json$"
)
TARGET_REGISTRATION_RE = re.compile(
    r"^records/targets/\d{4}-\d{2}-\d{2}-[0-9a-f]{64}\.json$"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_REGISTRATION_COMMIT_LAG = dt.timedelta(minutes=15)

SECRET_PATTERNS = {
    "GitHub token": re.compile(
        rb"(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{80,255})"
    ),
    "OpenAI API key": re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "AWS access key": re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    "Slack token": re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,}"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


class PublicationError(ValueError):
    """The generated publication bundle failed a trust-boundary check."""


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/number loose equality."""

    return canonical_bytes(left) == canonical_bytes(right)


def relative_repo_path(value: str) -> pathlib.PurePosixPath:
    path = pathlib.PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or "\\" in value
        or "\x00" in value
    ):
        raise PublicationError(f"unsafe repository path: {value!r}")
    return path


def path_in_scope(
    path: pathlib.PurePosixPath,
    exact: set[pathlib.PurePosixPath],
    prefixes: set[pathlib.PurePosixPath],
) -> bool:
    return path in exact or any(prefix in path.parents for prefix in prefixes)


def safe_join(root: pathlib.Path, relative: pathlib.PurePosixPath) -> pathlib.Path:
    root = root.resolve()
    path = root.joinpath(*relative.parts)
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise PublicationError(f"path escapes through a symlink: {relative}") from exc
    current = path
    while current != root:
        if current.is_symlink():
            raise PublicationError(f"symlink is not allowed in bundle path: {relative}")
        current = current.parent
    return path


def path_policy_error(
    path: pathlib.PurePosixPath,
    run_prefixes: set[pathlib.PurePosixPath] | None = None,
) -> str | None:
    lower_name = path.name.lower()
    if ".github" in path.parts:
        return "workflow/control paths are forbidden"
    if lower_name in {"chain_genesis.json", "chain_head.json"}:
        return "record-chain control files are forbidden"
    if re.fullmatch(r"digest(?:-[a-z0-9._-]+)?\.json", lower_name):
        return "record-chain digest files are forbidden"
    if re.fullmatch(
        r"(?:resolution|resolved)(?:[_-][a-z0-9._-]+)?"
        r"\.(?:jsonl?|log|md|txt)",
        lower_name,
    ):
        return "resolution markers are forbidden"
    if path.suffix.lower() in CODE_SUFFIXES:
        return "executable source code is forbidden"
    if path.suffix.lower() not in ALLOWED_DATA_SUFFIXES:
        return f"bundle file is not an allowed data type ({path.suffix or 'none'})"
    if lower_name == "custody_root.json" and not any(
        prefix in path.parents for prefix in (run_prefixes or set())
    ):
        return "custody roots are allowed only for this invocation's new runs"
    return None


def validate_batch_path(batch: str) -> pathlib.PurePosixPath:
    relative = relative_repo_path(batch)
    if not BATCH_RE.fullmatch(relative.as_posix()):
        raise PublicationError(f"batch path is not invocation-scoped: {relative}")
    return relative


def batch_scope(
    batch_relative: pathlib.PurePosixPath,
    batch: dict[str, Any],
) -> tuple[set[pathlib.PurePosixPath], set[pathlib.PurePosixPath]]:
    if batch.get("schemaVersion") != "thesis_batch_manifest_v1":
        raise PublicationError("unsupported batch manifest schema")
    results = batch.get("results")
    if not isinstance(results, list) or not all(
        isinstance(result, dict) for result in results
    ):
        raise PublicationError("batch results must be an object list")
    if type(batch.get("targets")) is not int or batch["targets"] != len(results):
        raise PublicationError("batch target count does not match result inventory")

    batch_match = BATCH_RE.fullmatch(batch_relative.as_posix())
    assert batch_match is not None
    batch_day = dt.date.fromisoformat(batch_match.group("day"))
    allowed_run_days = {batch_day, batch_day + dt.timedelta(days=1)}
    exact = {batch_relative}
    prefixes: set[pathlib.PurePosixPath] = set()
    for index, result in enumerate(results):
        target = result.get("target")
        if not isinstance(target, dict):
            raise PublicationError(f"result {index} has no target context")
        registration_value = target.get("targetRegistrationPath")
        if not registration_value:
            raise PublicationError(f"result {index} lacks targetRegistrationPath")
        registration = relative_repo_path(str(registration_value))
        if not TARGET_REGISTRATION_RE.fullmatch(registration.as_posix()):
            raise PublicationError(
                f"target registration is outside invocation scope: {registration}"
            )
        exact.add(registration)

        manifest_value = result.get("manifestPath")
        cells_value = result.get("cellsPath")
        if not manifest_value:
            if cells_value:
                raise PublicationError(f"result {index} has cells without a manifest")
            continue
        manifest = relative_repo_path(str(manifest_value))
        match = RUN_MANIFEST_RE.fullmatch(manifest.as_posix())
        if not match or not match.group("run").startswith(f"{match.group('day')}t"):
            raise PublicationError(
                f"run manifest is outside invocation scope: {manifest}"
            )
        if dt.date.fromisoformat(match.group("day")) not in allowed_run_days:
            raise PublicationError(
                f"run manifest day is outside the batch invocation: {manifest}"
            )
        run_prefix = manifest.parent
        prefixes.add(run_prefix)
        if cells_value:
            cells = relative_repo_path(str(cells_value))
            if cells != run_prefix / "cells.with_activity.json":
                raise PublicationError(
                    f"cells payload is outside its exact run scope: {cells}"
                )
    return exact, prefixes


def compare_trusted_targets(batch: dict[str, Any], trusted_path: str | None) -> None:
    if not trusted_path:
        return
    trusted = load_json(pathlib.Path(trusted_path), "trusted target registration")
    targets = trusted.get("targets") if isinstance(trusted, dict) else None
    if not isinstance(targets, list) or not all(
        isinstance(target, dict) for target in targets
    ):
        raise PublicationError("trusted targets must contain an object-list 'targets'")
    results = batch.get("results") or []
    if len(results) != len(targets):
        raise PublicationError("batch result inventory differs from trusted targets")
    trusted_by_slug = {target.get("catalogSlug"): target for target in targets}
    if len(trusted_by_slug) != len(targets) or None in trusted_by_slug:
        raise PublicationError("trusted targets contain duplicate or missing slugs")
    seen = set()
    for result in results:
        target = result.get("target")
        slug = target.get("catalogSlug") if isinstance(target, dict) else None
        if slug in seen or not canonical_equal(trusted_by_slug.get(slug), target):
            raise PublicationError(
                f"batch target does not match privileged registration: {slug}"
            )
        seen.add(slug)


def changed_paths(
    exact: set[pathlib.PurePosixPath], prefixes: set[pathlib.PurePosixPath]
) -> list[pathlib.PurePosixPath]:
    pathspecs = sorted({str(path) for path in exact | prefixes})
    command = [
        "git",
        "ls-files",
        "--modified",
        "--others",
        "--exclude-standard",
        "--",
        *pathspecs,
    ]
    output = subprocess.check_output(command, cwd=ROOT, text=True)
    paths = sorted({relative_repo_path(line) for line in output.splitlines() if line})
    deleted = subprocess.check_output(
        ["git", "diff", "--name-only", "--diff-filter=D", "--", *pathspecs],
        cwd=ROOT,
        text=True,
    ).splitlines()
    if deleted:
        raise PublicationError(
            "docket generation may not delete publication files: " + ", ".join(deleted)
        )
    return paths


def head_bytes(
    relative: pathlib.PurePosixPath,
    *,
    repo_root: str | pathlib.Path | None = None,
) -> bytes | None:
    checkout = pathlib.Path(repo_root).resolve() if repo_root is not None else ROOT
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{relative.as_posix()}"],
        cwd=checkout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if exists.returncode != 0:
        return None
    return subprocess.check_output(
        ["git", "show", f"HEAD:{relative.as_posix()}"], cwd=checkout
    )


def published_wave_collision_exclusion(
    repo: pathlib.Path,
    batch_relative: pathlib.PurePosixPath,
) -> pathlib.Path | None:
    """Return this batch's deterministic wave only after it is in ``HEAD``.

    The first publication must still collide with every existing catalog slug.
    A byte-identical retry or post-commit revalidation may ignore only the
    module deterministically generated for this exact committed batch; every
    other module remains part of the collision set.
    """

    batch_path = safe_join(repo, batch_relative)
    payload = batch_path.read_bytes()
    if head_bytes(batch_relative) != payload:
        return None
    match = BATCH_RE.fullmatch(batch_relative.as_posix())
    assert match is not None
    name = f"auto-{match.group('day')}-{hashlib.sha256(payload).hexdigest()}"
    return ROOT / "site" / "src" / "data" / "forecast-examples" / f"{name}.ts"


def assert_append_only(
    relative: pathlib.PurePosixPath,
    source: pathlib.Path,
    *,
    repo_root: str | pathlib.Path | None = None,
) -> None:
    checkout = pathlib.Path(repo_root).resolve() if repo_root is not None else ROOT
    committed = head_bytes(relative, repo_root=checkout)
    source_bytes = source.read_bytes()
    if committed is not None and committed != source_bytes:
        raise PublicationError(
            f"append-only publication may not overwrite HEAD path: {relative}"
        )
    destination = safe_join(checkout, relative)
    if source.resolve() == destination.resolve():
        return
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file():
            raise PublicationError(
                f"append-only destination is not a regular file: {relative}"
            )
        if destination.read_bytes() != source_bytes:
            raise PublicationError(
                f"append-only publication may not overwrite existing path: {relative}"
            )


def stage(args: argparse.Namespace) -> None:
    bundle = pathlib.Path(args.bundle_dir).resolve()
    if bundle.exists():
        shutil.rmtree(bundle)
    repo = bundle / "repo"
    repo.mkdir(parents=True)

    batch = validate_batch_path(args.batch)
    batch_path = safe_join(ROOT, batch)
    batch_payload = load_json(batch_path, "batch manifest")
    compare_trusted_targets(batch_payload, args.trusted_targets)
    exact, prefixes = batch_scope(batch, batch_payload)
    paths = changed_paths(exact, prefixes)
    if batch not in paths:
        raise PublicationError(
            f"batch manifest is not in the invocation delta: {batch}"
        )

    entries = []
    for relative in paths:
        policy_error = path_policy_error(relative, prefixes)
        if policy_error:
            raise PublicationError(f"forbidden bundle path {relative}: {policy_error}")
        if not path_in_scope(relative, exact, prefixes):
            raise PublicationError(
                f"path is outside this invocation's publication scope: {relative}"
            )
        source = safe_join(ROOT, relative)
        if source.is_symlink() or not source.is_file():
            raise PublicationError(
                f"publication artifact must be a regular file: {relative}"
            )
        if source.stat().st_mode & 0o111:
            raise PublicationError(f"executable bundle file is forbidden: {relative}")
        assert_append_only(relative, source)
        secret_hits = scan_bytes(source.read_bytes())
        if secret_hits:
            raise PublicationError(
                f"refusing to upload {relative}: possible " + ", ".join(secret_hits)
            )
        destination = repo.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        entries.append(
            {
                "path": str(relative),
                "bytes": source.stat().st_size,
                "sha256": sha256(source),
                "mode": stat.S_IMODE(source.stat().st_mode),
            }
        )

    manifest = {
        "schemaVersion": BUNDLE_SCHEMA,
        "batchManifest": str(batch),
        "files": entries,
    }
    (bundle / "bundle_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"staged {len(entries)} files in {bundle}")


def load_bundle(
    bundle: pathlib.Path,
    batch: str,
    trusted_targets: str | None = None,
    *,
    repo_root: str | pathlib.Path | None = None,
) -> tuple[pathlib.Path, dict[str, Any]]:
    checkout = pathlib.Path(repo_root).resolve() if repo_root is not None else ROOT
    bundle = bundle.resolve()
    repo = bundle / "repo"
    manifest_path = bundle / "bundle_manifest.json"
    if repo.is_symlink() or not repo.is_dir():
        raise PublicationError("bundle repo inventory is not a regular directory")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PublicationError("bundle manifest is not a regular file")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationError(f"invalid bundle manifest: {exc}") from exc
    if manifest.get("schemaVersion") != BUNDLE_SCHEMA:
        raise PublicationError("unsupported publication bundle schema")
    batch_relative = validate_batch_path(batch)
    if manifest.get("batchManifest") != batch_relative.as_posix():
        raise PublicationError("bundle does not contain the expected batch manifest")

    expected: set[pathlib.PurePosixPath] = set()
    entries = manifest.get("files")
    if not isinstance(entries, list) or not all(
        isinstance(entry, dict) for entry in entries
    ):
        raise PublicationError("bundle file inventory must be an object list")
    for entry in entries:
        relative = relative_repo_path(str(entry.get("path", "")))
        if relative in expected:
            raise PublicationError(f"duplicate bundle path: {relative}")
        # Apply context-independent denials before deriving scope so a chain or
        # TypeScript attack is reported as an explicit policy violation.
        policy_error = path_policy_error(relative)
        if policy_error and relative.name != "custody_root.json":
            raise PublicationError(f"forbidden bundle path {relative}: {policy_error}")
        expected.add(relative)
        path = safe_join(repo, relative)
        if path.is_symlink() or not path.is_file():
            raise PublicationError(f"bundle entry is not a regular file: {relative}")
        if path.stat().st_mode & 0o111:
            raise PublicationError(f"executable bundle file is forbidden: {relative}")
        mode = entry.get("mode")
        if not isinstance(mode, int) or mode & 0o111:
            raise PublicationError(f"bundle declares executable mode: {relative}")
        if path.stat().st_size != entry.get("bytes") or sha256(path) != entry.get(
            "sha256"
        ):
            raise PublicationError(f"bundle hash mismatch: {relative}")
        secret_hits = scan_bytes(path.read_bytes())
        if secret_hits:
            raise PublicationError(
                f"refusing to publish {relative}: possible " + ", ".join(secret_hits)
            )

    actual = {
        pathlib.PurePosixPath(path.relative_to(repo).as_posix())
        for path in repo.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != expected:
        raise PublicationError(
            f"bundle file inventory mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    if batch_relative not in expected:
        raise PublicationError("batch manifest is missing from bundle inventory")

    batch_path = safe_join(repo, batch_relative)
    batch_payload = load_json(batch_path, "batch manifest")
    compare_trusted_targets(batch_payload, trusted_targets)
    exact, prefixes = batch_scope(batch_relative, batch_payload)
    for relative in expected:
        policy_error = path_policy_error(relative, prefixes)
        if policy_error:
            raise PublicationError(f"forbidden bundle path {relative}: {policy_error}")
        if not path_in_scope(relative, exact, prefixes):
            raise PublicationError(
                f"path is outside this invocation's publication scope: {relative}"
            )
        assert_append_only(
            relative,
            safe_join(repo, relative),
            repo_root=checkout,
        )
    return repo, manifest


def load_json(path: pathlib.Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationError(f"invalid {label} {path}: {exc}") from exc


def parse_instant(value: Any, label: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublicationError(f"invalid {label}: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PublicationError(f"{label} lacks a UTC offset: {value!r}")
    return parsed.astimezone(dt.timezone.utc)


def verify_registration_commit(
    relative: pathlib.PurePosixPath,
    snapshot_bytes: bytes,
    snapshot: dict[str, Any],
    target: dict[str, Any],
    run_started_at: str,
) -> None:
    commit = str(target.get("registrationCommit") or "")
    if not COMMIT_RE.fullmatch(commit):
        raise PublicationError("target lacks a valid registrationCommit")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if ancestor.returncode != 0:
        raise PublicationError(
            f"registration commit is not an ancestor of HEAD: {commit}"
        )
    status = subprocess.check_output(
        [
            "git",
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-status",
            "-r",
            commit,
            "--",
            relative.as_posix(),
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()
    if status != [f"A\t{relative.as_posix()}"]:
        raise PublicationError(
            f"registrationCommit did not introduce snapshot {relative}: {status}"
        )
    try:
        committed = subprocess.check_output(
            ["git", "show", f"{commit}:{relative.as_posix()}"],
            cwd=ROOT,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        raise PublicationError(
            f"registration snapshot is absent from registrationCommit: {relative}"
        ) from exc
    if committed != snapshot_bytes:
        raise PublicationError(
            f"registrationCommit snapshot bytes differ from HEAD: {relative}"
        )

    registered_value = snapshot.get("registeredAtUtc")
    try:
        registered = parse_utc_instant(str(registered_value))
    except RegistrationError as exc:
        raise PublicationError(str(exc)) from exc
    if target.get("registeredAtUtc") != registered_value:
        raise PublicationError(f"target registeredAtUtc mismatch: {relative}")
    if relative.name[:10] != registered.date().isoformat():
        raise PublicationError(
            f"registration path date differs from registeredAtUtc: {relative}"
        )
    timestamps = subprocess.check_output(
        ["git", "show", "-s", "--format=%aI%n%cI", commit],
        cwd=ROOT,
        text=True,
    ).splitlines()
    if len(timestamps) != 2:
        raise PublicationError(f"could not read registration commit times: {commit}")
    author_time = parse_instant(timestamps[0], "registration author time")
    committer_time = parse_instant(timestamps[1], "registration committer time")
    run_start = parse_instant(run_started_at, "runStartedAt")
    for label, commit_time in (
        ("author", author_time),
        ("committer", committer_time),
    ):
        lag = commit_time - registered
        if lag < dt.timedelta(0) or lag > MAX_REGISTRATION_COMMIT_LAG:
            raise PublicationError(
                "registeredAtUtc is not contemporaneous with the privileged "
                f"commit {label} time: lag={lag}"
            )
    if committer_time >= run_start or author_time >= run_start:
        raise PublicationError(
            f"registration commit does not predate run start: {commit}"
        )


def validate_target_registration(
    repo: pathlib.Path,
    target: dict[str, Any],
    *,
    run_started_at: str | None = None,
    require_git_binding: bool = False,
    allow_pre_cutover_v2: bool = False,
) -> dict[str, Any]:
    path_value = target.get("targetRegistrationPath")
    content_hash = target.get("targetContentHash")
    if not path_value or not re.fullmatch(r"[0-9a-f]{64}", str(content_hash or "")):
        raise PublicationError("batch target lacks a hashed registration snapshot")
    relative = relative_repo_path(str(path_value))
    if pathlib.PurePosixPath("records/targets") not in relative.parents:
        raise PublicationError(
            f"target registration is outside records/targets: {relative}"
        )
    if not TARGET_REGISTRATION_RE.fullmatch(relative.as_posix()):
        raise PublicationError(f"invalid target registration path: {relative}")
    # Privileged docket publishers read the already-pushed snapshot from their
    # checkout. Non-binding validation can still inspect a bundle-local snapshot
    # for offline tooling, but it cannot establish Git chronology.
    bundle_path = safe_join(repo, relative)
    committed_path = safe_join(ROOT, relative)
    source = (
        committed_path
        if require_git_binding
        else bundle_path
        if bundle_path.is_file()
        else committed_path
    )
    snapshot = load_json(source, "target registration")
    try:
        actual_hash = registration_content_hash(snapshot)
    except RegistrationError as exc:
        raise PublicationError(str(exc)) from exc
    if actual_hash != content_hash or not relative.name.endswith(
        f"-{content_hash}.json"
    ):
        raise PublicationError(f"target registration hash mismatch: {relative}")
    contract = next(
        (
            row
            for row in snapshot.get("targets", [])
            if row.get("catalogSlug") == target.get("catalogSlug")
        ),
        None,
    )
    if not contract:
        raise PublicationError(
            f"target registration has no contract for {target.get('catalogSlug')}"
        )
    expected = {
        "series": target.get("series"),
        "period": target.get("period"),
        "catalogSlug": target.get("catalogSlug"),
        "dataPointId": target.get("dataPointId"),
        "country": target.get("country"),
        "unit": target.get("targetUnit"),
        "valueScale": target.get("valueScale"),
        "sourceBinding": target.get("sourceBinding"),
        # Conditional arms bake the legal-state text, condition identity,
        # and deadline into the registered contract; a batch target must
        # repeat them byte-for-byte (None for unconditional targets on
        # both sides).
        "conditional": target.get("conditional"),
        "conditionId": target.get("conditionId"),
        "conditionDeadline": target.get("conditionDeadline"),
    }
    try:
        validate_target_resolution_projection(
            contract, target, label=relative.as_posix()
        )
    except RegistrationError as exc:
        raise PublicationError(str(exc)) from exc
    for key, value in expected.items():
        if not canonical_equal(contract.get(key), value):
            raise PublicationError(
                f"target registration contract mismatch for {key}: "
                f"snapshot={contract.get(key)!r}, batch={value!r}"
            )
    if require_git_binding:
        schema = snapshot.get("schemaVersion")
        # The strategy comparison lane targets registrations that predate the
        # v3 cutover; those are trustworthy only because trusted history can
        # no longer mint v2 snapshots and the ancestry check below proves the
        # snapshot existed before the cutover. Everything else must be v3.
        pre_cutover_v2 = allow_pre_cutover_v2 and schema == V2_REGISTRATION_SCHEMA
        if schema != REGISTRATION_SCHEMA and not pre_cutover_v2:
            raise PublicationError(
                f"privileged publication requires {REGISTRATION_SCHEMA}: {relative}"
            )
        if len(snapshot.get("targets", [])) != 1:
            raise PublicationError(
                f"privileged registration must contain exactly one target: {relative}"
            )
        snapshot_bytes = source.read_bytes()
        if snapshot_bytes != canonical_bytes(snapshot) + b"\n":
            raise PublicationError(
                f"registration snapshot is not canonical: {relative}"
            )
        if not run_started_at:
            raise PublicationError("run manifest lacks runStartedAt")
        verify_registration_commit(
            relative,
            snapshot_bytes,
            snapshot,
            target,
            run_started_at,
        )
        # The publisher revalidates after EVERY rebase (including the final
        # push loop, which does not re-run the bind step), so the docket at
        # THIS checkout must still authorize a conditional contract — the
        # same total reauthentication the bind step performs. A concurrent
        # docket change absorbed by a late rebase fails closed here instead
        # of publishing under a registry that no longer generates the
        # contract.
        try:
            docket_entries = json.loads(
                (ROOT / "scripts" / "docket_series.json").read_text()
            )["series"]
        except FileNotFoundError:
            # No registry in this checkout: conditional contracts then fail
            # the exactly-one-committed-entry requirement below, and
            # unconditional targets keep their pre-registry behavior.
            docket_entries = []
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            raise PublicationError(
                f"cannot read the committed docket registry: {exc}"
            ) from exc
        template_matches = [
            entry
            for entry in docket_entries
            if isinstance(entry, dict) and entry.get("series") == contract.get("series")
        ]
        try:
            require_conditional_docket_template(
                contract,
                template_matches,
                snapshot["registeredAtUtc"],
                batch_target=target,
            )
        except RegistrationError as exc:
            raise PublicationError(str(exc)) from exc
        if pre_cutover_v2:
            require_pre_cutover_registration(
                str(target.get("registrationCommit") or ""), relative
            )
    return snapshot


def require_pre_cutover_registration(
    commit: str, relative: pathlib.PurePosixPath
) -> None:
    """A grandfathered v2 snapshot must strictly predate the v3 cutover."""

    cutover = V3_REGISTRATION_CUTOVER_COMMIT
    probe = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, cutover],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if commit == cutover or probe.returncode != 0:
        raise PublicationError(
            f"v2 registration does not strictly predate the v3 cutover: {relative}"
        )
    # Every grandfathered target announces itself in the publish log for as
    # long as the pre-v3 target set lives.
    print(
        f"grandfathered pre-v3 registration {relative} introduced at {commit}",
        file=sys.stderr,
    )


REGISTRATION_BINDING_FIELDS = (
    "registrationCommit",
    "targetContentHash",
    "targetRegistrationPath",
    "registeredAtUtc",
)


def validate_run_file_inventory(
    repo: pathlib.Path,
    manifest_relative: pathlib.PurePosixPath,
    manifest: dict[str, Any],
) -> None:
    run_prefix = manifest_relative.parent
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not all(
        isinstance(artifact, dict) for artifact in artifacts
    ):
        raise PublicationError(
            f"run manifest has no artifact inventory: {manifest_relative}"
        )
    declared = {run_prefix / "custody_root.json"}
    for artifact in artifacts:
        relative = relative_repo_path(str(artifact.get("path") or ""))
        if relative.parent != run_prefix or relative in declared:
            raise PublicationError(
                f"run artifact is duplicated or outside its run: {relative}"
            )
        declared.add(relative)
    run_dir = safe_join(repo, run_prefix)
    actual = {
        pathlib.PurePosixPath(path.relative_to(repo).as_posix())
        for path in run_dir.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != declared:
        raise PublicationError(
            f"run file inventory mismatch for {run_prefix}: "
            f"unreferenced={sorted(actual - declared)}, "
            f"missing={sorted(declared - actual)}"
        )


# Must equal TARGET_PREREGISTRATION_ORPHAN_GRACE_DAYS in
# site/src/data/ledger-targets.ts (pinned by test).
ORPHAN_GRACE_DAYS = 7


def require_run_within_grace(
    target: dict[str, Any],
    run_start: dt.datetime,
    cells: list[dict[str, Any]],
) -> None:
    """Refuse runs that started or sealed after the registration's grace.

    Selection-time grace approval (the retry lane's selector) cannot
    cover a generation job that runs long past the deadline; this is the
    trusted re-check at publication time, against the authenticated run
    manifest start and each sealed cell's runAt.
    """

    registered = parse_instant(target.get("registeredAtUtc"), "target registeredAtUtc")
    deadline = registered + dt.timedelta(days=ORPHAN_GRACE_DAYS)
    if run_start >= deadline:
        raise PublicationError(
            "run started after the registration's orphan grace deadline "
            f"({run_start.isoformat()} >= {deadline.isoformat()}); the "
            "honest terminal state is the expired-unforecast ratchet"
        )
    for cell in cells:
        cell_run_at = parse_instant(cell.get("runAt"), "cell runAt")
        if cell_run_at >= deadline:
            raise PublicationError(
                "cell sealed after the registration's orphan grace deadline"
            )


def validate_run_binding(
    repo: pathlib.Path,
    result: dict[str, Any],
    manifest: dict[str, Any],
    cells: list[dict[str, Any]],
    *,
    require_git_binding: bool,
    enforce_run_grace: bool = False,
) -> None:
    target = result["target"]
    if not require_git_binding:
        validate_target_registration(repo, target)
        return
    if manifest.get("schemaVersion") != "thesis_analyst_run_manifest_v1":
        raise PublicationError("unsupported run manifest schema")
    if not canonical_equal(manifest.get("targetContext"), target):
        raise PublicationError(
            "run manifest targetContext differs from trusted batch target"
        )
    run_started_at = manifest.get("runStartedAt")
    if manifest.get("createdAt") != run_started_at:
        raise PublicationError("run manifest createdAt/runStartedAt mismatch")
    for field in ("series", "period", "conditional"):
        if not canonical_equal(manifest.get(field), target.get(field)):
            raise PublicationError(f"run manifest target identity mismatch: {field}")
    run_start = parse_instant(run_started_at, "run manifest runStartedAt")
    if enforce_run_grace:
        require_run_within_grace(target, run_start, cells)
    manifest_relative = relative_repo_path(str(result.get("manifestPath") or ""))
    run_dir_stamp = manifest_relative.parent.name[:20]
    try:
        path_start = dt.datetime.strptime(run_dir_stamp, "%Y-%m-%dt%H-%M-%Sz").replace(
            tzinfo=dt.timezone.utc
        )
    except ValueError as exc:
        raise PublicationError(
            f"run directory lacks a canonical start timestamp: {manifest_relative}"
        ) from exc
    if path_start != run_start:
        raise PublicationError("run directory timestamp differs from runStartedAt")
    wrapper_start = parse_instant(result.get("startedAt"), "batch result startedAt")
    wrapper_finish = parse_instant(result.get("finishedAt"), "batch result finishedAt")
    if wrapper_finish < wrapper_start:
        raise PublicationError("batch result finishes before it starts")
    if wrapper_start > run_start or wrapper_finish < run_start:
        raise PublicationError("batch wrapper timestamps do not contain the run start")
    for field in REGISTRATION_BINDING_FIELDS:
        if not canonical_equal(manifest.get(field), target.get(field)):
            raise PublicationError(
                f"run manifest registration binding mismatch: {field}"
            )
    validate_target_registration(
        repo,
        target,
        run_started_at=str(run_started_at),
        require_git_binding=True,
    )
    for cell in cells:
        if cell.get("runStartedAt") != run_started_at:
            raise PublicationError("cell runStartedAt differs from run manifest")
        cell_run_at = parse_instant(cell.get("runAt"), "cell runAt")
        if cell_run_at < run_start:
            raise PublicationError("cell seal time predates run start")
        if cell_run_at > wrapper_finish:
            raise PublicationError("cell seal time postdates batch result finish")
        for field in REGISTRATION_BINDING_FIELDS:
            if not canonical_equal(cell.get(field), target.get(field)):
                raise PublicationError(f"cell registration binding mismatch: {field}")


def validate_cells(
    repo: pathlib.Path,
    batch_relative: str,
    *,
    require_git_binding: bool = False,
    enforce_run_grace: bool = False,
    collision_exclusion: pathlib.Path | None = None,
    publish_validated_at_utc: str | None = None,
) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from run_thesis_analyst import validate_cells as shared_validate_cells
        from verify_custody import CustodyError, verify_run
    finally:
        sys.path.pop(0)

    batch_path = safe_join(repo, relative_repo_path(batch_relative))
    batch = load_json(batch_path, "batch manifest")
    if batch.get("schemaVersion") != "thesis_batch_manifest_v1":
        raise PublicationError("unsupported batch manifest schema")
    prompt_mode = str(batch.get("promptMode", "full"))
    batch_started_at = parse_instant(batch.get("startedAt"), "batch startedAt")
    batch_finished_at = parse_instant(batch.get("finishedAt"), "batch finishedAt")
    if batch_finished_at < batch_started_at:
        raise PublicationError("batch finishes before it starts")
    publish_upper = (
        parse_instant(publish_validated_at_utc, "publishValidatedAtUtc")
        if publish_validated_at_utc
        else None
    )
    if require_git_binding and publish_upper is None:
        raise PublicationError(
            "privileged target validation requires publishValidatedAtUtc"
        )
    if publish_upper is not None and batch_finished_at > publish_upper:
        raise PublicationError("batch finishes after privileged publication validation")
    referenced_payloads: set[pathlib.PurePosixPath] = set()
    referenced_manifests: set[pathlib.PurePosixPath] = set()

    for index, result in enumerate(batch.get("results", [])):
        cells_value = result.get("cellsPath")
        manifest_value = result.get("manifestPath")
        expected_ok = result.get("ok") is True
        if expected_ok and (not cells_value or not manifest_value):
            raise PublicationError(
                f"passing result {index} lacks cells or manifest path"
            )
        target = result.get("target")
        if not isinstance(target, dict):
            raise PublicationError(f"result {index} has no target context")
        result_started_at = parse_instant(
            result.get("startedAt"), f"batch result {index} startedAt"
        )
        result_finished_at = parse_instant(
            result.get("finishedAt"), f"batch result {index} finishedAt"
        )
        if (
            result_started_at < batch_started_at
            or result_finished_at > batch_finished_at
            or result_finished_at < result_started_at
        ):
            raise PublicationError(f"batch timestamps do not contain result {index}")
        if require_git_binding and not manifest_value:
            raise PublicationError(
                f"result {index} lacks a registration-bound manifest"
            )
        manifest: dict[str, Any] | None = None
        manifest_path: pathlib.Path | None = None
        if manifest_value:
            manifest_relative = relative_repo_path(str(manifest_value))
            if manifest_relative in referenced_manifests:
                raise PublicationError(f"duplicate run manifest: {manifest_relative}")
            referenced_manifests.add(manifest_relative)
            manifest_path = safe_join(repo, manifest_relative)
            manifest = load_json(manifest_path, "run manifest")
            if bool(manifest.get("ok")) != expected_ok:
                raise PublicationError(
                    f"run manifest status mismatch: {manifest_relative}"
                )
            if manifest.get("cellsPath") != cells_value:
                raise PublicationError(
                    f"run manifest cellsPath mismatch: {manifest_relative}"
                )
            validate_run_file_inventory(repo, manifest_relative, manifest)
            try:
                verify_run(manifest_path.parent)
            except CustodyError as exc:
                raise PublicationError(f"custody verification failed: {exc}") from exc

        cells: list[dict[str, Any]] = []
        cells_relative: pathlib.PurePosixPath | None = None
        if cells_value:
            cells_relative = relative_repo_path(str(cells_value))
            if cells_relative in referenced_payloads:
                raise PublicationError(f"duplicate cells payload: {cells_relative}")
            referenced_payloads.add(cells_relative)
            cells_path = safe_join(repo, cells_relative)
            loaded_cells = load_json(cells_path, "cells payload")
            if not isinstance(loaded_cells, list) or not all(
                isinstance(cell, dict) for cell in loaded_cells
            ):
                raise PublicationError(
                    f"cells payload is not an object list: {cells_relative}"
                )
            cells = loaded_cells

        if manifest is not None:
            validate_run_binding(
                repo,
                result,
                manifest,
                cells,
                require_git_binding=require_git_binding,
                enforce_run_grace=enforce_run_grace,
            )
        else:
            validate_target_registration(repo, target)
        if not cells_value:
            continue

        agent = manifest.get("agent") if manifest is not None else None
        report = shared_validate_cells(
            cells,
            target_context=target,
            prompt_mode=prompt_mode,
            collision_exclusion=collision_exclusion,
            generation_ticket=(
                manifest.get("generationTicket") if manifest is not None else None
            ),
            agent_version=(
                agent.get("agentVersion") if isinstance(agent, dict) else None
            ),
            checkout_sha=(manifest.get("checkoutSha") if manifest else None),
            series=(manifest.get("series") if manifest else None),
            target_period=(manifest.get("period") if manifest else None),
            # The staged bundle is data, not authority and may not even be a
            # Git checkout. Read reviewed authorization from trusted code.
            history_registry_root=ROOT,
        )
        if bool(report.get("ok")) != expected_ok:
            raise PublicationError(
                f"validator status mismatch for {cells_relative}: "
                f"batch ok={expected_ok}, replay={report}"
            )

        if not manifest_value:
            raise PublicationError(
                f"cells payload has no run manifest: {cells_relative}"
            )
        print(
            f"validated {cells_relative} "
            f"({'passing' if expected_ok else 'retained failed trace'})"
        )

    bundled_payloads = {
        pathlib.PurePosixPath(path.relative_to(repo).as_posix())
        for path in repo.rglob("cells.with_activity.json")
    }
    if bundled_payloads != referenced_payloads:
        raise PublicationError(
            "batch/cell inventory mismatch: "
            f"unreferenced={sorted(bundled_payloads - referenced_payloads)}, "
            f"missing={sorted(referenced_payloads - bundled_payloads)}"
        )
    bundled_manifests = {
        pathlib.PurePosixPath(path.relative_to(repo).as_posix())
        for path in repo.glob("records/thesis-analyst/*/*/manifest.json")
    }
    if bundled_manifests != referenced_manifests:
        raise PublicationError(
            "batch/run-manifest inventory mismatch: "
            f"unreferenced={sorted(bundled_manifests - referenced_manifests)}, "
            f"missing={sorted(referenced_manifests - bundled_manifests)}"
        )


def apply_bundle(repo: pathlib.Path, manifest: dict[str, Any]) -> None:
    for entry in manifest["files"]:
        relative = relative_repo_path(entry["path"])
        source = safe_join(repo, relative)
        destination = safe_join(ROOT, relative)
        assert_append_only(relative, source)
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def validate(args: argparse.Namespace) -> None:
    bundle = pathlib.Path(args.bundle_dir)
    repo, manifest = load_bundle(
        bundle,
        args.batch,
        args.trusted_targets,
    )
    batch_relative = validate_batch_path(args.batch)
    collision_exclusion = (
        published_wave_collision_exclusion(repo, batch_relative)
        if args.allow_published_wave
        else None
    )
    validate_cells(
        repo,
        args.batch,
        require_git_binding=bool(args.trusted_targets),
        enforce_run_grace=bool(getattr(args, "enforce_run_grace", False)),
        collision_exclusion=collision_exclusion,
        publish_validated_at_utc=args.publish_validated_at_utc,
    )
    if args.apply:
        apply_bundle(repo, manifest)
        print("validated publication bundle applied to checkout")


def scan_bytes(data: bytes) -> list[str]:
    from evidence_secret_scan import INVALID_ENVELOPE, scan_evidence_bytes

    evidence_hits = scan_evidence_bytes(data, SECRET_PATTERNS)
    if evidence_hits is not None:
        if INVALID_ENVELOPE in evidence_hits:
            return evidence_hits + [
                name for name, pattern in SECRET_PATTERNS.items() if pattern.search(data)
            ]
        return evidence_hits
    return [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(data)]


def scan_staged(_: argparse.Namespace) -> None:
    output = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=ROOT,
    )
    paths = [path.decode() for path in output.split(b"\0") if path]
    findings = []
    for path in paths:
        data = subprocess.check_output(["git", "show", f":{path}"], cwd=ROOT)
        for kind in scan_bytes(data):
            findings.append(f"{path}: possible {kind}")
    if findings:
        raise PublicationError("secret scan failed:\n" + "\n".join(findings))
    print(f"secret scan passed for {len(paths)} staged files")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    stage_parser = subparsers.add_parser("stage")
    stage_parser.add_argument("--bundle-dir", required=True)
    stage_parser.add_argument("--batch", required=True)
    stage_parser.add_argument("--trusted-targets")
    stage_parser.set_defaults(func=stage)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--bundle-dir", required=True)
    validate_parser.add_argument("--batch", required=True)
    validate_parser.add_argument("--trusted-targets")
    validate_parser.add_argument("--publish-validated-at-utc")
    validate_parser.add_argument("--allow-published-wave", action="store_true")
    validate_parser.add_argument(
        "--enforce-run-grace",
        action="store_true",
        help=(
            "refuse any run that started or sealed after its registration's "
            "orphan grace deadline (the retry lane's trusted publication gate)"
        ),
    )
    validate_parser.add_argument("--apply", action="store_true")
    validate_parser.set_defaults(func=validate)

    scan_parser = subparsers.add_parser("scan-staged")
    scan_parser.set_defaults(func=scan_staged)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        args.func(args)
    except (PublicationError, subprocess.CalledProcessError) as exc:
        print(f"PUBLICATION BLOCKED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
