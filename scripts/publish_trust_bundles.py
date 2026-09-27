#!/usr/bin/env python3
"""Publish code-approved TSA trust bundles into records/trust.

Only allowlisted workflows write ``records/**``, so the pull request that
approves a new trust bundle cannot also add the file. It carries the exact
bytes under ``scripts/staged_trust_bundles/`` and pins their hash in
``verify_record_chain.CODE_PINNED_TRUST_BUNDLES`` instead. The recorder
workflow runs this script before it mints a snapshot. The snapshot then names
the bundle in ``trustBundleUpdates``, and the new file, the snapshot and its
witness land in one attested records push.

Publishing a file grants it no authority. Replay activates a bundle only after
a witness made under an already active bundle covers the snapshot that
introduces it.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
from typing import Any

from verify_record_chain import (
    CODE_PINNED_TRUST_BUNDLES,
    ChainError,
    _load_trust_bundle,
    _select_anchor,
    ensure_regular_records_file,
    physical_path,
)

STAGING_DIR = Path(__file__).resolve().parent / "staged_trust_bundles"
STAGING_README = "README.md"


def _verify_bundle(records: Path, reference: dict[str, Any]) -> None:
    """Load one bundle and every anchor exactly as the chain verifier will."""

    path, trust = _load_trust_bundle(records, reference)
    ensure_regular_records_file(
        records,
        path,
        message=f"TSA trust bundle is reached through a symlink: {reference['path']}",
    )
    for anchor in trust["anchors"]:
        _select_anchor(
            records,
            {"tsaAnchorId": anchor["id"], "tsa": anchor["endpoint"]},
            trust,
        )


def _staged_bytes(staging: Path, reference: dict[str, Any]) -> bytes:
    logical = str(reference["path"])
    staged = staging / Path(logical).name
    if staged.is_symlink() or not staged.is_file():
        raise ChainError(
            f"TSA trust bundle {logical} is approved in verifier code but is "
            f"neither published nor staged at {staged}"
        )
    raw = staged.read_bytes()
    if (
        hashlib.sha256(raw).hexdigest() != reference["sha256"]
        or len(raw) != reference["size"]
    ):
        raise ChainError(
            f"staged TSA trust bundle differs from its verifier code pin: {staged}"
        )
    return raw


def _reject_unapproved_staged_files(staging: Path) -> None:
    if not staging.is_dir():
        return
    approved = {Path(logical).name for logical in CODE_PINNED_TRUST_BUNDLES}
    for entry in sorted(staging.iterdir()):
        if entry.name == STAGING_README:
            continue
        if entry.name not in approved:
            raise ChainError(
                f"staged TSA trust bundle is not approved by verifier code: {entry}"
            )


def publish_trust_bundles(records: Path, *, staging: Path = STAGING_DIR) -> list[Path]:
    """Write every approved bundle that records/trust lacks; verify all of them.

    Returns the paths written. A published file is never rewritten: one that
    exists must already match its code pin, or this raises.
    """

    records = records.resolve()
    _reject_unapproved_staged_files(staging)
    published: list[Path] = []
    for logical, reference in CODE_PINNED_TRUST_BUNDLES.items():
        destination = physical_path(records, logical)
        if os.path.lexists(destination):
            _verify_bundle(records, reference)
            continue
        raw = _staged_bytes(staging, reference)
        trust_dir = destination.parent
        if trust_dir.is_symlink() or not trust_dir.is_dir():
            raise ChainError(f"records trust directory is not a directory: {trust_dir}")
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        try:
            _verify_bundle(records, reference)
        except ChainError:
            destination.unlink()
            raise
        published.append(destination)
    return published


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--records", type=Path, default=Path("records"))
    parser.add_argument("--staging", type=Path, default=STAGING_DIR)
    args = parser.parse_args()
    try:
        published = publish_trust_bundles(args.records, staging=args.staging)
    except (ChainError, OSError) as exc:
        raise SystemExit(f"cannot publish TSA trust bundles: {exc}") from exc
    records = args.records.resolve()
    for path in published:
        print(f"published records/{path.relative_to(records).as_posix()}")
    if not published:
        print("every code-approved TSA trust bundle is already published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
