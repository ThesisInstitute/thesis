#!/usr/bin/env python3
"""Retain a strategy attempt for diagnosis without granting publication authority.

This copies only the generation checkout's analyst-record delta. It deliberately
does not require valid cells, manifests or custody: those may be the failure
being investigated. The privileged publisher never consumes this archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import stat
import subprocess
from typing import Any

from docket_publication import scan_bytes

ROOT = pathlib.Path(__file__).resolve().parents[1]
PREFIX = ("records", "thesis-analyst")


def changed_paths(root: pathlib.Path) -> list[str]:
    paths: set[str] = set()
    for args in (
        ["diff", "--name-only", "-z", "HEAD", "--", "records/thesis-analyst"],
        ["ls-files", "--others", "--exclude-standard", "-z", "--", "records/thesis-analyst"],
    ):
        raw = subprocess.check_output(["git", *args], cwd=root)
        paths.update(value.decode("utf-8") for value in raw.split(b"\0") if value)
    return sorted(paths)


def archive_attempt(
    root: pathlib.Path,
    selection_path: pathlib.Path,
    output: pathlib.Path,
    run_id: int,
    run_attempt: int,
    execution_attempt: int = 1,
) -> dict[str, Any]:
    selection_raw = selection_path.read_bytes()
    selection = json.loads(selection_raw)
    workflow = selection.get("workflow") or {}
    if (
        type(run_id) is not int
        or type(run_attempt) is not int
        or run_id < 1
        or run_attempt < 1
        or type(execution_attempt) is not int
        or execution_attempt < 1
        or workflow.get("runId") != run_id
        or workflow.get("runAttempt") != run_attempt
    ):
        raise ValueError("diagnostic archive invocation differs from selection")
    checkout = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    if selection.get("sourceSha") != checkout:
        raise ValueError("diagnostic archive checkout differs from selection")
    if scan_bytes(selection_raw):
        raise ValueError("diagnostic selection may contain a secret")
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("diagnostic archive must be outside the checkout")
    output.mkdir(parents=True, exist_ok=False)
    (output / "selection.json").write_bytes(selection_raw)
    manifest: dict[str, Any] = {
        "schemaVersion": "thesis_strategy_attempt_diagnostic_v1",
        "publishable": False,
        "workflowRunId": run_id,
        "workflowRunAttempt": run_attempt,
        "executionAttempt": execution_attempt,
        "sourceSha": checkout,
        "selectionSha256": hashlib.sha256(selection_raw).hexdigest(),
        "selectionSetHash": selection.get("selectionSetHash"),
        "files": [],
        "omitted": [],
    }
    for name in changed_paths(root):
        relative = pathlib.PurePosixPath(name)
        reason = None
        if (
            relative.is_absolute()
            or relative.parts[:2] != PREFIX
            or ".." in relative.parts
            or relative.as_posix() != name
        ):
            reason = "outside analyst-record scope"
        source = root.joinpath(*relative.parts)
        # Check every component before reading, including parent symlinks.
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                reason = "symlink"
                break
        if reason is None:
            if not source.exists():
                reason = "deleted"
            elif not stat.S_ISREG(source.stat().st_mode):
                reason = "not a regular file"
            elif source.stat().st_mode & 0o111:
                reason = "executable file"
        if reason is not None:
            manifest["omitted"].append({"path": name, "reason": reason})
            continue
        raw = source.read_bytes()
        if scan_bytes(raw):
            manifest["omitted"].append({"path": name, "reason": "possible secret"})
            continue
        destination = output / "files" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        manifest["files"].append(
            {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        )
    (output / "attempt_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--execution-attempt", type=int, required=True)
    args = parser.parse_args()
    manifest = archive_attempt(
        ROOT, args.selection, args.out, args.run_id, args.run_attempt, args.execution_attempt
    )
    print(f"Retained {len(manifest['files'])} diagnostic files; {len(manifest['omitted'])} omitted")


if __name__ == "__main__":
    main()
