"""Explicit, immutable public snapshots of recorded conditional read models.

This export does not run forecasts, change the store, or establish publication
timing evidence. Only selected attempts, their revision closure and referenced
artifact bytes are copied. Destination installation is atomic and never replaces
an existing path (supported on Linux and macOS).
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import ArtifactCorrupt
from .conditional_contracts import contract_id, shared_evidence_id, validate_response
from .conditionals import conditional_detail
from .contracts import ArtifactRef
from .lab_contracts import ConditionalDetail

MAX_ATTEMPTS = 100
MAX_ARTIFACTS = 2048
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_TOTAL_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_DETAIL_BYTES = 2 * 1024 * 1024
MAX_TOTAL_DETAIL_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
SCHEMA_VERSION = "thesis_conditional_snapshot_v1"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")


def _json(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _artifact_refs(value):
    """Find both ArtifactRef and ArtifactLink, including nested annotation links."""
    if isinstance(value, dict):
        if "sha256" in value:
            ref = ArtifactRef.model_validate_json(
                _json(
                    {key: value.get(key) for key in ("sha256", "bytes", "media_type")}
                )
            )
            if "download_path" in value and value["download_path"] != (
                "/artifacts/" + ref.sha256
            ):
                raise ValueError("artifact download path differs from its identity")
            yield ref
        elif "download_path" in value:
            raise ValueError("artifact download path has no identity")
        for child in value.values():
            yield from _artifact_refs(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _artifact_refs(child)


def _install_directory(staging: Path, destination: Path) -> None:
    """Use the kernel's exclusive rename, including against concurrent writers."""
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = library.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        arguments = (os.fsencode(staging), os.fsencode(destination), 0x00000004)
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        rename = library.renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        arguments = (-100, os.fsencode(staging), -100, os.fsencode(destination), 1)
    else:
        raise OSError(errno.ENOTSUP, "atomic no-replace directory rename unavailable")
    rename.restype = ctypes.c_int
    if rename(*arguments) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def _verify_closure(details):
    for identity, detail in details.items():
        history_ids = [entry.attempt_id for entry in detail.revision_history]
        if identity not in history_ids or len(set(history_ids)) != len(history_ids):
            raise ValueError("revision history must contain each attempt exactly once")
        for review in detail.reviews:
            if (
                review.attempt_id != identity
                or review.record_artifact.sha256 != review.id
            ):
                raise ValueError("review record identity does not match its attempt")
        for entry in detail.revision_history:
            other = details[entry.attempt_id]
            if set(history_ids) != {item.attempt_id for item in other.revision_history}:
                raise ValueError("revision histories disagree across the snapshot")
            for field in (
                "contract_id",
                "shared_evidence_id",
                "started_at",
                "execution_state",
                "requested_model",
                "provider_metadata",
                "arm_quantiles",
            ):
                if getattr(entry, field) != getattr(other, field):
                    raise ValueError(
                        "revision history disagrees with its attempt detail"
                    )
            if entry.parent_attempt_id is not None:
                parent = details[entry.parent_attempt_id]
                if (
                    entry.parent_attempt_id not in history_ids
                    or entry.triggering_review_id
                    not in {item.id for item in parent.reviews}
                    or entry.feedback is None
                    or entry.association_artifact is None
                ):
                    raise ValueError(
                        "revision has a dangling parent, review or artifact"
                    )


def export_conditionals(
    store,
    attempt_ids: Iterable[str],
    destination: Path | str,
    *,
    code_revision: str,
) -> dict:
    """Export verified real read projections and their exact CAS dependencies.

    The caller supplies a full Git object ID naming the exporter/read-model code;
    it is a disclosed operator assertion, not an automatically verified checkout.
    The local export time is likewise not an independently witnessed timestamp.
    """
    if not isinstance(code_revision, str) or not _REVISION.fullmatch(code_revision):
        raise ValueError("code_revision must be a full lowercase Git object ID")
    if isinstance(attempt_ids, (str, bytes)):
        raise ValueError("attempt_ids must be a collection of full content identities")
    selected = set()
    for index, identity in enumerate(attempt_ids):
        if index >= MAX_ATTEMPTS:
            raise ValueError("a snapshot accepts at most 100 attempt IDs")
        if not isinstance(identity, str) or not _DIGEST.fullmatch(identity):
            raise ValueError("attempt identity must be a lowercase SHA-256 digest")
        if identity in selected:
            raise ValueError("duplicate selected attempt identity")
        selected.add(identity)
    if not selected:
        raise ValueError("a snapshot requires at least one attempt")

    destination = Path(destination).expanduser().absolute()
    if os.path.lexists(destination):
        raise FileExistsError(destination)
    if not destination.parent.is_dir():
        raise FileNotFoundError(destination.parent)
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    details = {}
    pending = set(selected)
    while pending:
        identity = min(pending)
        pending.remove(identity)
        if len(details) >= MAX_ATTEMPTS:
            raise ValueError("revision closure exceeds 100 attempts")
        original = conditional_detail(store, identity)
        detail = ConditionalDetail.model_validate_json(original.model_dump_json())
        if (
            detail.id != identity
            or detail.contract_id != contract_id(detail.contract)
            or detail.shared_evidence_id != shared_evidence_id(detail.contract)
        ):
            raise ValueError("conditional detail has a mismatched content identity")
        if detail.response is not None:
            validate_response(detail.contract, detail.response)
        # generated_at describes this read projection's publication snapshot.
        # All recorded attempt/source/review timestamps remain unchanged.
        details[identity] = detail.model_copy(update={"generated_at": generated_at})
        for entry in detail.revision_history:
            for linked in (entry.attempt_id, entry.parent_attempt_id):
                if linked is not None and linked not in details:
                    pending.add(linked)
    _verify_closure(details)

    blobs: dict[str, bytes] = {}
    artifacts: dict[str, dict] = {}
    attempts = []
    artifact_bytes = 0
    detail_bytes = 0
    for identity, detail in sorted(details.items()):
        # Match FastAPI's public wire shape and the generated TypeScript schema.
        # NumericCdf's internal snake_case names have camelCase JSON aliases.
        data = detail.model_dump(mode="json", by_alias=True)
        for ref in _artifact_refs(data):
            if ref.bytes > MAX_ARTIFACT_BYTES:
                raise ValueError("snapshot artifact exceeds 32 MiB")
            if ref.sha256 not in artifacts:
                artifact_bytes += ref.bytes
                if (
                    len(artifacts) >= MAX_ARTIFACTS
                    or artifact_bytes > MAX_TOTAL_ARTIFACT_BYTES
                ):
                    raise ValueError(
                        "snapshot exceeds artifact count or total byte limit"
                    )
            raw = blobs.get(ref.sha256)
            if raw is None:
                raw = store.artifacts.read_bytes(ref.sha256)
            if (
                not isinstance(raw, bytes)
                or len(raw) != ref.bytes
                or hashlib.sha256(raw).hexdigest() != ref.sha256
            ):
                raise ArtifactCorrupt("snapshot artifact differs from its commitment")
            blobs[ref.sha256] = raw
            metadata = ref.model_dump(mode="json")
            if ref.sha256 in artifacts and artifacts[ref.sha256]["media_type"] != (
                ref.media_type
            ):
                # The v1 public manifest has exactly one media type per object.
                raise ValueError(
                    "snapshot artifact has conflicting contextual media types"
                )
            artifacts[ref.sha256] = metadata
        raw = _json(data)
        detail_bytes += len(raw)
        if len(raw) > MAX_DETAIL_BYTES or detail_bytes > MAX_TOTAL_DETAIL_BYTES:
            raise ValueError("snapshot exceeds detail byte limit")
        digest = hashlib.sha256(raw).hexdigest()
        blobs[digest] = raw
        attempts.append(
            {"id": identity, "detail": {"sha256": digest, "bytes": len(raw)}}
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "code_revision": code_revision,
        "attempts": attempts,
        "artifacts": [artifacts[digest] for digest in sorted(artifacts)],
    }
    manifest_raw = _json(manifest)
    if len(manifest_raw) > MAX_MANIFEST_BYTES:
        raise ValueError("snapshot manifest exceeds 1 MiB")
    staging = Path(
        tempfile.mkdtemp(prefix=".conditional-export-", dir=destination.parent)
    )
    try:
        (staging / "blobs").mkdir()
        for digest, raw in sorted(blobs.items()):
            with (staging / "blobs" / digest).open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        with (staging / "manifest.json").open("xb") as stream:
            stream.write(manifest_raw)
            stream.flush()
            os.fsync(stream.fileno())
        _install_directory(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return manifest
