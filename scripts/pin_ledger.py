#!/usr/bin/env python3
"""Pin the fact ledger to one immutable commit and index row acceptance.

The site build must consume the thesis-facts observation file at an exact
commit SHA whose bytes are committed here as a pin, never at a branch name a
writer can move. Row eligibility at a cutoff must mean "the ledger contained
this row then" — acceptance into the append-only file, derived from the
branch's own commit history — never the publisher's ``observed_at``, which a
backfill can predate (review finding N5).

Two committed outputs:

- ``site/src/data/ledger-pin.json`` — the exact state the site build fetches
  and verifies byte-for-byte.
- ``records/ledger/availability.json`` (+ a generated TypeScript mirror) —
  per-row ``acceptedSequence``/``acceptedAtUtc``/``acceptedCommit`` with a
  custody flag; rows whose content changed after introduction are marked
  ``rewritten_in_place``, never silently adopted. The legacy quarantine
  boundary freezes the row count at first indexing: earlier rows predate
  contract binding and are flagged wherever they grade forecasts.

Refreshes verify every intermediate commit extends the previous version
line-for-line. A rewritten or truncated upstream state refuses to advance the
pin; adopting one requires deliberate ``--rebuild-from-history``, which
re-derives custody flags rather than blessing the rewrite.

Usage:
    python3 scripts/pin_ledger.py [--require-catalog]   # incremental refresh
    python3 scripts/pin_ledger.py --rebuild-from-history --ledger-git PATH \
        [--require-catalog]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from canonical_json import canonical_bytes, canonical_sha256
from ledger_release_chain import (
    DEFAULT_CLOCK_SKEW_SECONDS,
    MANIFEST_RE,
    PRODUCER_SIGNATURE_RE,
    RECEIPT_RE,
    ChainVerification,
    ReleaseChainError,
    git_tree_entries,
    jsonl_line_offsets,
    materialize_base_tree,
    verify_release_chain,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "site" / "src" / "data" / "ledger-pin.json"
AVAILABILITY_PATH = ROOT / "records" / "ledger" / "availability.json"
GENERATED_PATH = ROOT / "site" / "src" / "data" / "ledger-availability.generated.ts"
LEDGER_REPO = "PolicyEngine/ledger"
LEDGER_BRANCH = "codex/thesis-ledger-facts"
LEDGER_JSONL_PATH = "ledger/official_observations.jsonl"
LEDGER_CATALOG_PATH = "ledger/series_catalog.json"
LEDGER_REGISTRY_PATH = "ledger/series_uuid_registry.jsonl"
LEDGER_PREFIX_PATH = "ledger/immutable_prefix.json"
PIN_SCHEMA = "thesis_ledger_pin_v1"
AVAILABILITY_SCHEMA = "thesis_ledger_availability_v1"
STRICT_UTC_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:"
    r"[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z\Z"
)
PIN_BASE_KEYS = {
    "schemaVersion",
    "repo",
    "branch",
    "sha",
    "jsonlSha256",
    "jsonlBytes",
    "lineCount",
    "pinnedAtUtc",
}
PIN_CATALOG_KEYS = {"catalogSha256", "catalogBytes"}
RELEASE_HEAD_KEYS = {
    "index",
    "manifestSha256",
    "freetsaGenTimeUtc",
    "digicertGenTimeUtc",
}
RELEASE_WINDOW_KEYS = {
    "witnessedInReleaseIndex",
    "witnessedInReleaseFreetsaGenTimeUtc",
    "witnessedInReleaseDigicertGenTimeUtc",
    "lastExcludedReleaseIndex",
    "lastExcludedReleaseFreetsaGenTimeUtc",
    "lastExcludedReleaseDigicertGenTimeUtc",
}


class PinError(ValueError):
    """The upstream ledger state cannot be adopted."""


@dataclass(frozen=True)
class VerifiedReleaseState:
    """A same-commit release chain checked before any pin output is written."""

    verification: ChainVerification | None
    release_head: dict[str, Any] | None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _utc_instant(value: str) -> str:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise PinError(f"commit timestamp lacks a timezone: {value!r}")
    return (
        parsed.astimezone(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _strict_utc_datetime(value: Any, label: str) -> dt.datetime:
    if type(value) is not str or STRICT_UTC_RE.fullmatch(value) is None:
        raise PinError(f"{label} must be a strict UTC timestamp ending in Z")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PinError(f"{label} is not a real UTC time: {value!r}") from exc
    return parsed.astimezone(dt.timezone.utc)


def _format_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_release_head(value: Any, label: str = "releaseHead") -> dict[str, Any]:
    if type(value) is not dict or set(value) != RELEASE_HEAD_KEYS:
        actual = set(value) if type(value) is dict else set()
        raise PinError(
            f"{label} keys are not closed-world: "
            f"missing={sorted(RELEASE_HEAD_KEYS - actual)}, "
            f"unknown={sorted(actual - RELEASE_HEAD_KEYS)}"
        )
    if type(value["index"]) is not int or value["index"] < 0 or value["index"] > 9_999:
        raise PinError(
            f"{label}.index must be a non-negative integer no greater than 9999"
        )
    if type(value["manifestSha256"]) is not str or not re.fullmatch(
        r"[0-9a-f]{64}", value["manifestSha256"]
    ):
        raise PinError(f"{label}.manifestSha256 must be a SHA-256 digest")
    _strict_utc_datetime(value["freetsaGenTimeUtc"], f"{label}.freetsaGenTimeUtc")
    _strict_utc_datetime(value["digicertGenTimeUtc"], f"{label}.digicertGenTimeUtc")
    return value


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "thesis-pin"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _api(path: str) -> Any:
    return json.loads(_fetch(f"https://api.github.com/repos/{LEDGER_REPO}/{path}"))


def _jsonl_at(sha: str) -> bytes:
    return _raw_file_at(sha, LEDGER_JSONL_PATH)


def _raw_file_at(sha: str, path: str) -> bytes:
    encoded_path = quote(path, safe="/")
    return _fetch(
        f"https://raw.githubusercontent.com/{LEDGER_REPO}/{sha}/{encoded_path}"
    )


def _git_blob_sha1(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()


def _git_tree_sha(entries: dict[str, dict[str, Any]]) -> str:
    body = bytearray()
    for entry in entries.values():
        mode = str(entry["mode"]).lstrip("0") or "0"
        body.extend(f"{mode} {entry['path']}\0".encode("utf-8"))
        body.extend(bytes.fromhex(str(entry["sha"])))
    header = f"tree {len(body)}\0".encode("ascii")
    return hashlib.sha1(header + body, usedforsecurity=False).hexdigest()


def _tree_entries_at(tree_sha: str) -> dict[str, dict[str, Any]]:
    if not re.fullmatch(r"[0-9a-f]{40}", tree_sha):
        raise PinError(f"GitHub returned a non-tree SHA: {tree_sha!r}")
    payload = _api(f"git/trees/{tree_sha}")
    if payload.get("sha") != tree_sha:
        raise PinError(f"GitHub tree response does not match requested tree {tree_sha}")
    if payload.get("truncated") is not False:
        raise PinError(f"GitHub tree {tree_sha} is truncated; refusing partial state")
    raw_entries = payload.get("tree")
    if not isinstance(raw_entries, list):
        raise PinError(f"GitHub tree {tree_sha} has no entry list")
    entries: dict[str, dict[str, Any]] = {}
    for entry in raw_entries:
        if not isinstance(entry, dict):
            raise PinError(f"GitHub tree {tree_sha} contains a non-object entry")
        name = entry.get("path")
        if (
            type(name) is not str
            or not name
            or "/" in name
            or name in {".", ".."}
            or "\x00" in name
        ):
            raise PinError(f"GitHub tree {tree_sha} has unsafe entry path {name!r}")
        if name in entries:
            raise PinError(f"GitHub tree {tree_sha} has duplicate entry {name!r}")
        mode = entry.get("mode")
        object_type = entry.get("type")
        object_id = entry.get("sha")
        if type(mode) is not str or type(object_type) is not str:
            raise PinError(f"GitHub tree {tree_sha} entry {name!r} lacks mode/type")
        if type(object_id) is not str or not re.fullmatch(r"[0-9a-f]{40}", object_id):
            raise PinError(
                f"GitHub tree {tree_sha} entry {name!r} has invalid object ID"
            )
        entries[name] = {
            "path": name,
            "mode": mode,
            "type": object_type,
            "sha": object_id,
        }
    computed_sha = _git_tree_sha(entries)
    if computed_sha != tree_sha:
        raise PinError(
            f"GitHub tree entries hash to {computed_sha}, expected {tree_sha}; "
            "refusing incomplete same-commit state"
        )
    return entries


def _require_tree_entry(
    entries: dict[str, dict[str, Any]], name: str, *, label: str
) -> dict[str, Any]:
    entry = entries.get(name)
    if entry is None:
        raise PinError(f"same-commit tree is missing {label}")
    if entry.get("type") != "tree" or entry.get("mode") != "040000":
        raise PinError(f"same-commit {label} is not a regular Git tree")
    if not re.fullmatch(r"[0-9a-f]{40}", str(entry.get("sha", ""))):
        raise PinError(f"same-commit {label} has an invalid tree object ID")
    return entry


def _require_blob_entry(
    entries: dict[str, dict[str, Any]], name: str, *, label: str
) -> dict[str, Any]:
    entry = entries.get(name)
    if entry is None:
        raise PinError(f"same-commit tree is missing {label}")
    if entry.get("type") != "blob" or entry.get("mode") not in {"100644", "100755"}:
        raise PinError(f"same-commit {label} is not a regular Git blob")
    if not re.fullmatch(r"[0-9a-f]{40}", str(entry.get("sha", ""))):
        raise PinError(f"same-commit {label} has an invalid blob object ID")
    return entry


def _verified_remote_blob(sha: str, path: str, entry: dict[str, Any]) -> bytes:
    raw = _raw_file_at(sha, path)
    object_id = _git_blob_sha1(raw)
    if object_id != entry["sha"]:
        raise PinError(
            f"same-commit blob bytes for {path} hash to {object_id}, "
            f"tree requires {entry['sha']}"
        )
    return raw


def _collect_remote_tree_files(
    sha: str, tree_sha: str, prefix: pathlib.PurePosixPath
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    entries = _tree_entries_at(tree_sha)
    for name in sorted(entries):
        entry = entries[name]
        relative = prefix / name
        entry_type = entry.get("type")
        if entry_type == "tree":
            if entry.get("mode") != "040000":
                raise PinError(f"same-commit tree has invalid mode at {relative}")
            child_sha = str(entry.get("sha", ""))
            child = _collect_remote_tree_files(sha, child_sha, relative)
            overlap = set(files) & set(child)
            if overlap:
                raise PinError(
                    f"same-commit tree has duplicate paths: {sorted(overlap)}"
                )
            files.update(child)
            continue
        if entry_type != "blob" or entry.get("mode") not in {"100644", "100755"}:
            raise PinError(
                f"same-commit release entry is not a regular blob: {relative}"
            )
        object_id = str(entry.get("sha", ""))
        if not re.fullmatch(r"[0-9a-f]{40}", object_id):
            raise PinError(
                f"same-commit release blob has invalid object ID: {relative}"
            )
        path = relative.as_posix()
        files[path] = _verified_remote_blob(sha, path, entry)
    return files


def _remote_commit_entries(
    sha: str,
    commit_payload: dict[str, Any],
    expected_jsonl: bytes,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Bind JSONL bytes and the ledger subtree to one exact commit object."""

    if type(commit_payload) is not dict or commit_payload.get("sha") != sha:
        raise PinError(f"commit response does not describe requested SHA {sha}")
    commit = commit_payload.get("commit")
    tree = commit.get("tree") if isinstance(commit, dict) else None
    root_tree_sha = tree.get("sha") if isinstance(tree, dict) else None
    if not re.fullmatch(r"[0-9a-f]{40}", str(root_tree_sha or "")):
        raise PinError(f"commit {sha} has no valid root tree SHA")
    root_entries = _tree_entries_at(str(root_tree_sha))

    ledger_entry = _require_tree_entry(root_entries, "ledger", label="ledger/")
    ledger_entries = _tree_entries_at(str(ledger_entry["sha"]))
    jsonl_name = pathlib.PurePosixPath(LEDGER_JSONL_PATH).name
    jsonl_entry = _require_blob_entry(
        ledger_entries, jsonl_name, label=LEDGER_JSONL_PATH
    )
    if _git_blob_sha1(expected_jsonl) != jsonl_entry["sha"]:
        raise PinError("branch head JSONL bytes disagree with the same-commit Git tree")
    return root_entries, ledger_entries


def _remote_catalog_at_commit(
    sha: str,
    commit_payload: dict[str, Any],
    expected_jsonl: bytes,
    *,
    required: bool,
) -> bytes | None:
    """Read and Git-tree-bind the optional catalog at one exact commit.

    Historical ledger commits legitimately predate ``series_catalog.json``.
    Callers opt into the forward presence gate with ``required``; when the file
    exists, its bytes are always fetched at ``sha`` and checked against that
    commit's reconstructed ``ledger/`` tree, even in legacy-compatible mode.
    """

    _, ledger_entries = _remote_commit_entries(sha, commit_payload, expected_jsonl)
    catalog_name = pathlib.PurePosixPath(LEDGER_CATALOG_PATH).name
    catalog_entry = ledger_entries.get(catalog_name)
    if catalog_entry is None:
        if required:
            raise PinError(
                f"same-commit tree is missing required {LEDGER_CATALOG_PATH}"
            )
        return None
    catalog_entry = _require_blob_entry(
        ledger_entries, catalog_name, label=LEDGER_CATALOG_PATH
    )
    return _verified_remote_blob(sha, LEDGER_CATALOG_PATH, catalog_entry)


def _remote_registry_at_commit(
    sha: str,
    commit_payload: dict[str, Any],
    expected_jsonl: bytes,
) -> bytes | None:
    """Read and Git-tree-bind the optional UUID registry at one commit.

    Presence is never forced here: whether the registry must exist is a
    property of the same-commit catalog (a catalog declaring
    ``uuid_registry_sha256`` requires it), enforced by
    ``_validate_catalog_and_registry``.
    """

    _, ledger_entries = _remote_commit_entries(sha, commit_payload, expected_jsonl)
    registry_name = pathlib.PurePosixPath(LEDGER_REGISTRY_PATH).name
    registry_entry = ledger_entries.get(registry_name)
    if registry_entry is None:
        return None
    registry_entry = _require_blob_entry(
        ledger_entries, registry_name, label=LEDGER_REGISTRY_PATH
    )
    return _verified_remote_blob(sha, LEDGER_REGISTRY_PATH, registry_entry)


def _validated_manifest_inventory(
    entries: dict[str, dict[str, Any]],
    *,
    label: str,
    require_complete_siblings: bool,
) -> dict[str, str]:
    """Parse a closed inventory; require four siblings only for the final tree."""

    if not entries:
        return {}
    manifests: dict[int, str] = {}
    receipts: dict[str, set[str]] = {}
    producer_signatures: set[str] = set()
    for name in sorted(entries):
        _require_blob_entry(entries, name, label=f"{label}/{name}")
        manifest_match = MANIFEST_RE.fullmatch(name)
        if manifest_match is not None:
            index = int(manifest_match.group("index"))
            if index in manifests:
                raise PinError(
                    f"{label} has duplicate release index {index}: "
                    f"{manifests[index]}, {name}"
                )
            manifests[index] = name
            continue
        receipt_match = RECEIPT_RE.fullmatch(name)
        if receipt_match is not None:
            receipts.setdefault(receipt_match.group("stem"), set()).add(
                receipt_match.group("tsa")
            )
            continue
        signature_match = PRODUCER_SIGNATURE_RE.fullmatch(name)
        if signature_match is not None:
            producer_signatures.add(signature_match.group("stem"))
            continue
        raise PinError(f"{label} has unknown closed-world file {name!r}")

    if not manifests:
        raise PinError(
            "releases/manifests contains artifacts but no valid genesis manifest"
        )
    indices = sorted(manifests)
    if indices != list(range(indices[-1] + 1)):
        raise PinError(
            f"{label} release indices are not contiguous from genesis: {indices}"
        )
    manifest_stems = {pathlib.PurePosixPath(name).stem for name in manifests.values()}
    orphan_receipts = sorted(set(receipts) - manifest_stems)
    if orphan_receipts:
        raise PinError(f"{label} has orphan receipt stems: {orphan_receipts}")
    orphan_signatures = sorted(producer_signatures - manifest_stems)
    if orphan_signatures:
        raise PinError(
            f"{label} has orphan producer signature stems: {orphan_signatures}"
        )
    if require_complete_siblings:
        for name in manifests.values():
            stem = pathlib.PurePosixPath(name).stem
            if receipts.get(stem, set()) != {"freetsa", "digicert"}:
                raise PinError(
                    f"{label}/{name} must have exactly freetsa and digicert receipts"
                )
            if stem not in producer_signatures:
                raise PinError(f"{label}/{name} is missing its producer signature")
    return {
        name: f"{entries[name]['mode']}:{entries[name]['sha']}"
        for name in sorted(entries)
    }


def _remote_release_inventory_at_commit(
    sha: str,
    commit_payload: dict[str, Any],
    expected_jsonl: bytes,
    *,
    require_complete_siblings: bool,
) -> tuple[dict[str, str], bytes | None]:
    """Read the exact same-commit manifest inventory without verifying TSA tokens."""

    root_entries, ledger_entries = _remote_commit_entries(
        sha, commit_payload, expected_jsonl
    )
    release_entry = root_entries.get("releases")
    if release_entry is None:
        return {}, None
    if release_entry.get("type") != "tree" or release_entry.get("mode") != "040000":
        raise PinError("same-commit releases/ is not a regular Git tree")
    release_entries = _tree_entries_at(str(release_entry.get("sha", "")))
    manifest_entry = release_entries.get("manifests")
    if manifest_entry is None:
        return {}, None
    manifest_entry = _require_tree_entry(
        release_entries, "manifests", label="releases/manifests/"
    )
    entries = _tree_entries_at(str(manifest_entry["sha"]))
    inventory = _validated_manifest_inventory(
        entries,
        label="releases/manifests",
        require_complete_siblings=require_complete_siblings,
    )
    prefix_name = pathlib.PurePosixPath(LEDGER_PREFIX_PATH).name
    prefix_entry = _require_blob_entry(
        ledger_entries, prefix_name, label=LEDGER_PREFIX_PATH
    )
    prefix = _verified_remote_blob(sha, LEDGER_PREFIX_PATH, prefix_entry)
    return inventory, prefix


def _local_release_inventory_at_commit(
    ledger_git: pathlib.Path,
    sha: str,
    *,
    require_complete_siblings: bool,
) -> tuple[dict[str, str], bytes | None]:
    """Read a commit's manifest inventory directly from local Git objects."""

    try:
        raw_entries = git_tree_entries(ledger_git, sha, "releases/manifests")
    except ReleaseChainError as exc:
        raise PinError(f"cannot enumerate release manifests at {sha}: {exc}") from exc
    if not raw_entries:
        return {}, None
    entries: dict[str, dict[str, Any]] = {}
    directory = pathlib.PurePosixPath("releases/manifests")
    for relative, entry in raw_entries.items():
        path = pathlib.PurePosixPath(relative)
        if path.parent != directory:
            raise PinError(
                f"releases/manifests contains a nested entry at {sha}: {relative}"
            )
        entries[path.name] = {
            "path": path.name,
            "mode": entry.mode,
            "type": entry.object_type,
            "sha": entry.object_id,
        }
    inventory = _validated_manifest_inventory(
        entries,
        label=f"releases/manifests at {sha}",
        require_complete_siblings=require_complete_siblings,
    )
    try:
        prefix = subprocess.check_output(
            ["git", "show", f"{sha}:{LEDGER_PREFIX_PATH}"], cwd=ledger_git
        )
    except subprocess.CalledProcessError as exc:
        raise PinError(f"cannot read {LEDGER_PREFIX_PATH} at {sha}") from exc
    return inventory, prefix


def _require_inventory_progress(
    previous: dict[str, str],
    candidate: dict[str, str],
    final: dict[str, str],
    *,
    label: str,
) -> None:
    """Require a monotonic prefix-subset of the verified final inventory."""

    candidate_manifests = sorted(
        name for name in candidate if MANIFEST_RE.fullmatch(name)
    )
    final_manifests = sorted(name for name in final if MANIFEST_RE.fullmatch(name))

    for name, object_id in candidate.items():
        if final.get(name) != object_id:
            raise PinError(
                f"{label} release artifact {name} is absent or changed in the "
                "verified final tree; release chain is absent after witnessed "
                "genesis or its history was rewritten"
            )
    if candidate_manifests != final_manifests[: len(candidate_manifests)]:
        raise PinError(
            f"{label} release manifest stems are not a prefix of the verified "
            "final chain"
        )
    for name, object_id in previous.items():
        if candidate.get(name) != object_id:
            raise PinError(
                f"{label} deletes or replaces witnessed release artifact {name}"
            )


def _require_inventory_head_witnesses_state(
    inventory: dict[str, str],
    verification: ChainVerification | None,
    jsonl: bytes,
    immutable_prefix: bytes | None,
    *,
    label: str,
) -> None:
    """Bind every chain-bearing commit to its complete, finally verified head."""

    if not inventory:
        return
    if verification is None or immutable_prefix is None:
        raise PinError(
            f"{label} has a release chain absent from the verified final tree"
        )
    manifest_names = [name for name in inventory if MANIFEST_RE.fullmatch(name)]
    head_name = max(
        manifest_names,
        key=lambda name: int(MANIFEST_RE.fullmatch(name).group("index")),
    )
    match = MANIFEST_RE.fullmatch(head_name)
    assert match is not None
    index = int(match.group("index"))
    if index >= len(verification.releases):
        raise PinError(f"{label} release head {index} exceeds the verified final chain")
    record = verification.releases[index]
    if record.path.name != head_name:
        raise PinError(
            f"{label} release head {head_name} disagrees with verified release {index}"
        )
    try:
        line_count = len(jsonl_line_offsets(jsonl, LEDGER_JSONL_PATH)) - 1
    except ReleaseChainError as exc:
        raise PinError(f"{label} JSONL is invalid: {exc}") from exc
    state = record.manifest["state"]
    if state["lineCount"] != line_count or state["jsonlSha256"] != sha256_hex(jsonl):
        raise PinError(
            f"{label} advances through an unwitnessed JSONL state; release "
            f"{index} does not match the same-commit bytes"
        )
    if state["immutablePrefixSha256"] != sha256_hex(immutable_prefix):
        raise PinError(
            f"{label} release {index} does not match the same-commit immutable prefix"
        )


def _compare_commits(base: str, head: str) -> list[dict[str, Any]]:
    """Every commit base..head, paginated past GitHub's 250-commit page cap."""
    first = _api(f"compare/{base}...{head}?per_page=100&page=1")
    if type(first) is not dict:
        raise PinError(f"compare {base[:12]}..{head[:12]} returned a non-object")
    merge_base = first.get("merge_base_commit")
    merge_base_sha = merge_base.get("sha") if isinstance(merge_base, dict) else None
    if first.get("status") != "ahead" or merge_base_sha != base:
        raise PinError(
            f"ledger head {head[:12]} is not a strict descendant of pinned "
            f"commit {base[:12]}; refusing rewritten Git history"
        )
    total = first.get("total_commits")
    if not isinstance(total, int):
        raise PinError(f"compare {base[:12]}..{head[:12]} has no total_commits")
    first_commits = first.get("commits")
    if not isinstance(first_commits, list):
        raise PinError(f"compare {base[:12]}..{head[:12]} has no commit list")
    commits = list(first_commits)
    page = 2
    while len(commits) < total:
        payload = _api(f"compare/{base}...{head}?per_page=100&page={page}")
        if type(payload) is not dict or not isinstance(payload.get("commits"), list):
            raise PinError(f"compare {base[:12]}..{head[:12]} page {page} is malformed")
        batch = payload["commits"]
        if not batch:
            break
        commits.extend(batch)
        page += 1
    if len(commits) != total:
        raise PinError(
            f"compare {base[:12]}..{head[:12]} returned {len(commits)} of "
            f"{total} commits; refusing to advance the pin on a partial history"
        )
    if not commits:
        raise PinError(f"cannot enumerate commits {base[:12]}..{head[:12]}")
    commit_shas: list[str] = []
    for index, commit in enumerate(commits):
        commit_sha = commit.get("sha") if isinstance(commit, dict) else None
        if not re.fullmatch(r"[0-9a-f]{40}", str(commit_sha or "")):
            raise PinError(
                f"compare {base[:12]}..{head[:12]} commit {index} has invalid SHA"
            )
        commit_shas.append(str(commit_sha))
    if len(set(commit_shas)) != len(commit_shas):
        raise PinError(f"compare {base[:12]}..{head[:12]} contains duplicate commits")
    if commit_shas[-1] != head:
        raise PinError(
            f"compare {base[:12]}..{head[:12]} ends at {commit_shas[-1][:12]}"
        )
    return commits


def _require_walk_parent(
    commit_payload: Any,
    commit_sha: str,
    expected_parent: str,
    visited: set[str],
) -> bool:
    """Admit a commit into the pin walk; True when it is a merge commit.

    Ledger appends stay strictly linear: a single-parent commit must
    continue the walk exactly. A multi-parent commit is traversable only
    when the walk predecessor is among its parents and every other parent
    was already walked (or is the pinned base), so a merge can reconcile
    branch-internal history — a gate-class PR merged with a merge commit —
    but can never splice in unwalked foreign history. The caller enforces
    the companion content rule: a merge must leave the ledger bytes
    exactly as its walk predecessor left them; appends arrive only on
    single-parent commits.
    """
    if type(commit_payload) is not dict or commit_payload.get("sha") != commit_sha:
        raise PinError(f"commit response does not describe requested SHA {commit_sha}")
    parents = commit_payload.get("parents")
    if (
        type(parents) is not list
        or not parents
        or any(type(parent) is not dict for parent in parents)
    ):
        raise PinError(
            f"commit {commit_sha[:12]} is not on a linear single-parent history"
        )
    parent_shas = [str(parent.get("sha")) for parent in parents]
    if len(parents) == 1:
        if parent_shas[0] != expected_parent:
            raise PinError(
                f"commit history skips or reorders a parent at {commit_sha[:12]}: "
                f"expected {expected_parent[:12]}, found {parent_shas[0][:12]}"
            )
        return False
    if expected_parent not in parent_shas:
        raise PinError(
            f"merge commit {commit_sha[:12]} does not continue the walk from "
            f"{expected_parent[:12]}"
        )
    strangers = [
        sha for sha in parent_shas if sha != expected_parent and sha not in visited
    ]
    if strangers:
        raise PinError(
            f"merge commit {commit_sha[:12]} pulls in unwalked history "
            f"({strangers[0][:12]}); refusing to advance the pin"
        )
    return True


def _lines(raw: bytes) -> list[str]:
    return [line for line in raw.decode("utf-8").split("\n") if line.strip()]


def _validate_catalog_binding(
    catalog_raw: bytes,
    jsonl_raw: bytes,
    *,
    label: str,
    registry_raw: bytes | None = None,
) -> None:
    """Require the catalog's top-level input commitments to match the tree.

    The observation commitment (digest + row count) must match the
    same-commit JSONL. From catalog generator v3, the catalog also commits
    to the append-only UUID registry via ``uuid_registry_sha256``; a
    declaring catalog requires the same-commit registry bytes to hash to
    exactly that digest, and an undeclared catalog must not be accompanied
    by a registry file at all — either direction of drift breaks the pin.
    """

    try:
        catalog = json.loads(catalog_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PinError(f"{label} is not valid JSON: {exc}") from exc
    if type(catalog) is not dict:
        raise PinError(f"{label} must be a JSON object")
    expected_digest = sha256_hex(jsonl_raw)
    if catalog.get("observations_sha256") != expected_digest:
        raise PinError(
            f"{label} observations_sha256 does not match same-commit "
            f"{LEDGER_JSONL_PATH}"
        )
    expected_rows = len(_lines(jsonl_raw))
    if (
        type(catalog.get("observation_rows")) is not int
        or catalog["observation_rows"] != expected_rows
    ):
        raise PinError(
            f"{label} observation_rows does not match same-commit "
            f"{LEDGER_JSONL_PATH} line count {expected_rows}"
        )
    declared_registry = catalog.get("uuid_registry_sha256")
    generator_version = catalog.get("generator_version")
    if type(generator_version) is not int or generator_version < 1:
        # A string/bool/missing version is not a legacy catalog, it is a
        # malformed one — and the rollback trick rides on exactly that
        # ambiguity.
        raise PinError(
            f"{label} generator_version must be a positive integer, got "
            f"{generator_version!r}"
        )
    if generator_version >= 3 and declared_registry is None:
        # Generator v3 made the registry the UUID authority; a v3+ catalog
        # without the declaration is a coordinated downgrade, not a legacy
        # commit.
        raise PinError(
            f"{label} is generator v{generator_version} but does not "
            "declare uuid_registry_sha256 — registry binding cannot be "
            "downgraded away"
        )
    if declared_registry is not None:
        if type(declared_registry) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", declared_registry
        ):
            raise PinError(f"{label} uuid_registry_sha256 must be a SHA-256 digest")
        if registry_raw is None:
            raise PinError(
                f"{label} declares uuid_registry_sha256 but same-commit "
                f"{LEDGER_REGISTRY_PATH} is missing"
            )
        if sha256_hex(registry_raw) != declared_registry:
            raise PinError(
                f"{label} uuid_registry_sha256 does not match same-commit "
                f"{LEDGER_REGISTRY_PATH}"
            )
    elif registry_raw is not None:
        raise PinError(
            f"same-commit {LEDGER_REGISTRY_PATH} exists but {label} does "
            "not declare uuid_registry_sha256"
        )


def _declares_registry(catalog_raw: bytes | None) -> bool:
    if catalog_raw is None:
        return False
    try:
        catalog = json.loads(catalog_raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(catalog, dict) and (
        catalog.get("uuid_registry_sha256") is not None
    )


def _validate_catalog_and_registry(
    catalog_raw: bytes | None,
    registry_raw: bytes | None,
    jsonl_raw: bytes,
    *,
    label: str,
    registry_expected: bool = False,
) -> None:
    """Couple the catalog and UUID-registry commitments at one commit.

    ``registry_expected`` is the monotonic ratchet: once the pinned
    lineage has declared a registry, every later head must keep
    declaring one — a version rollback that drops both the declaration
    and the file is a downgrade, never a legacy state.
    """

    if catalog_raw is None:
        if registry_raw is not None:
            raise PinError(
                f"same-commit {LEDGER_REGISTRY_PATH} exists without "
                f"{LEDGER_CATALOG_PATH}"
            )
        if registry_expected:
            raise PinError(
                f"{label}: the pinned lineage declared a UUID registry "
                "but this commit has no catalog at all — registry binding "
                "cannot be downgraded away"
            )
        return
    if registry_expected and not _declares_registry(catalog_raw):
        raise PinError(
            f"{label}: the pinned lineage declared a UUID registry but "
            "this catalog does not — registry binding cannot be "
            "downgraded away"
        )
    _validate_catalog_binding(
        catalog_raw, jsonl_raw, label=label, registry_raw=registry_raw
    )


def _source_record_id(line: str, index: int) -> str:
    row = json.loads(line)
    record_id = row.get("source_record_id") if isinstance(row, dict) else None
    if not record_id:
        raise PinError(f"ledger line {index + 1} lacks source_record_id")
    return str(record_id)


def _require_extension(previous: list[str], current: list[str], *, label: str) -> None:
    if len(current) < len(previous):
        raise PinError(
            f"{label} truncates the ledger: {len(previous)} -> {len(current)} rows"
        )
    for index, line in enumerate(previous):
        if current[index] != line:
            raise PinError(
                f"{label} rewrites ledger line {index + 1} "
                f"({_source_record_id(line, index)}); refusing to advance the pin"
            )


def _row(
    index: int, line: str, accepted_at: str, commit: str, custody: str
) -> dict[str, Any]:
    return {
        "sourceRecordId": _source_record_id(line, index),
        "acceptedSequence": index,
        "acceptedAtUtc": accepted_at,
        "acceptedCommit": commit,
        "lineSha256": sha256_hex(line.encode("utf-8")),
        "custody": custody,
    }


def _release_head(verification: ChainVerification) -> dict[str, Any]:
    head = verification.head
    if head is None:
        raise PinError("cannot derive a release head from an empty chain")
    try:
        value = {
            "index": head.release_index,
            "manifestSha256": head.sha256,
            "freetsaGenTimeUtc": _format_utc(head.receipt_times["freetsa"]),
            "digicertGenTimeUtc": _format_utc(head.receipt_times["digicert"]),
        }
    except KeyError as exc:
        raise PinError(f"verified release head lacks receipt time {exc}") from exc
    return _validate_release_head(value)


def _require_checkpoint_continuity(
    verification: ChainVerification | None,
    previous_release_head: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if previous_release_head is not None:
        previous_release_head = _validate_release_head(previous_release_head)
    if verification is None:
        if previous_release_head is not None:
            raise PinError(
                "release chain is absent after witnessed genesis; refusing pin advance"
            )
        return None

    candidate_head = _release_head(verification)
    if previous_release_head is None:
        return candidate_head
    index = int(previous_release_head["index"])
    if index >= len(verification.releases):
        raise PinError(
            f"candidate release chain ends before pinned checkpoint index {index}"
        )
    checkpoint = verification.releases[index]
    candidate_checkpoint = {
        "index": checkpoint.release_index,
        "manifestSha256": checkpoint.sha256,
        "freetsaGenTimeUtc": _format_utc(checkpoint.receipt_times["freetsa"]),
        "digicertGenTimeUtc": _format_utc(checkpoint.receipt_times["digicert"]),
    }
    for key in RELEASE_HEAD_KEYS:
        expected = previous_release_head[key]
        actual = candidate_checkpoint[key]
        if key.endswith("GenTimeUtc"):
            expected = _strict_utc_datetime(expected, f"releaseHead.{key}")
            actual = _strict_utc_datetime(actual, f"candidate release.{key}")
        if actual != expected:
            raise PinError(
                f"candidate release chain does not extend pinned checkpoint "
                f"index {index}: {key} changed"
            )
    return candidate_head


def _verify_materialized_release_state(
    root: pathlib.Path,
    *,
    previous_release_head: dict[str, Any] | None,
) -> VerifiedReleaseState:
    try:
        verification = verify_release_chain(
            root,
            require_chain=True,
            verify_state=True,
            enforce_production_pins=True,
            clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
        )
    except (OSError, ReleaseChainError) as exc:
        raise PinError(f"release chain verification failed: {exc}") from exc
    head = _require_checkpoint_continuity(verification, previous_release_head)
    return VerifiedReleaseState(verification=verification, release_head=head)


def _remote_release_state_at_commit(
    sha: str,
    commit_payload: dict[str, Any],
    expected_jsonl: bytes,
    *,
    previous_release_head: dict[str, Any] | None,
) -> VerifiedReleaseState:
    root_entries, ledger_entries = _remote_commit_entries(
        sha, commit_payload, expected_jsonl
    )
    prefix_name = pathlib.PurePosixPath(LEDGER_PREFIX_PATH).name

    release_entry = root_entries.get("releases")
    if release_entry is None:
        head = _require_checkpoint_continuity(None, previous_release_head)
        return VerifiedReleaseState(verification=None, release_head=head)
    if release_entry.get("type") != "tree" or release_entry.get("mode") != "040000":
        raise PinError("same-commit releases/ is not a regular Git tree")
    release_tree_sha = str(release_entry.get("sha", ""))
    release_files = _collect_remote_tree_files(
        sha, release_tree_sha, pathlib.PurePosixPath("releases")
    )
    manifest_files = [
        path
        for path in release_files
        if pathlib.PurePosixPath(path).parent
        == pathlib.PurePosixPath("releases/manifests")
        and MANIFEST_RE.fullmatch(pathlib.PurePosixPath(path).name)
    ]
    if not manifest_files:
        manifest_artifacts = [
            path
            for path in release_files
            if pathlib.PurePosixPath("releases/manifests")
            in pathlib.PurePosixPath(path).parents
        ]
        if manifest_artifacts:
            raise PinError(
                "releases/manifests contains artifacts but no valid genesis manifest"
            )
        head = _require_checkpoint_continuity(None, previous_release_head)
        return VerifiedReleaseState(verification=None, release_head=head)

    prefix_entry = _require_blob_entry(
        ledger_entries, prefix_name, label=LEDGER_PREFIX_PATH
    )
    prefix_raw = _verified_remote_blob(sha, LEDGER_PREFIX_PATH, prefix_entry)
    with tempfile.TemporaryDirectory(prefix="thesis-pin-release-") as name:
        root = pathlib.Path(name)
        for path, raw in release_files.items():
            output = root / pathlib.PurePosixPath(path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(raw)
        jsonl_output = root / LEDGER_JSONL_PATH
        jsonl_output.parent.mkdir(parents=True, exist_ok=True)
        jsonl_output.write_bytes(expected_jsonl)
        (root / LEDGER_PREFIX_PATH).write_bytes(prefix_raw)
        return _verify_materialized_release_state(
            root,
            previous_release_head=previous_release_head,
        )


def _local_release_state_at_commit(
    ledger_git: pathlib.Path,
    sha: str,
    *,
    previous_release_head: dict[str, Any] | None,
) -> VerifiedReleaseState:
    try:
        release_entries = git_tree_entries(ledger_git, sha, "releases")
    except ReleaseChainError as exc:
        raise PinError(f"cannot enumerate releases at {sha}: {exc}") from exc
    if not release_entries:
        head = _require_checkpoint_continuity(None, previous_release_head)
        return VerifiedReleaseState(verification=None, release_head=head)
    manifest_files = [
        path
        for path in release_entries
        if pathlib.PurePosixPath(path).parent
        == pathlib.PurePosixPath("releases/manifests")
        and MANIFEST_RE.fullmatch(pathlib.PurePosixPath(path).name)
    ]
    if not manifest_files:
        manifest_artifacts = [
            path
            for path in release_entries
            if pathlib.PurePosixPath("releases/manifests")
            in pathlib.PurePosixPath(path).parents
        ]
        if manifest_artifacts:
            raise PinError(
                "releases/manifests contains artifacts but no valid genesis manifest"
            )
        head = _require_checkpoint_continuity(None, previous_release_head)
        return VerifiedReleaseState(verification=None, release_head=head)
    with tempfile.TemporaryDirectory(prefix="thesis-pin-local-release-") as name:
        root = pathlib.Path(name)
        try:
            materialize_base_tree(ledger_git, sha, root, release_entries)
        except ReleaseChainError as exc:
            raise PinError(f"cannot materialize releases at {sha}: {exc}") from exc
        return _verify_materialized_release_state(
            root,
            previous_release_head=previous_release_head,
        )


def _local_release_history_state(
    ledger_git: pathlib.Path,
    head_sha: str,
    *,
    previous_release_head: dict[str, Any] | None,
) -> VerifiedReleaseState:
    """Bind every first-parent state to one fully verified final release chain."""

    commits = _git(
        ledger_git,
        "rev-list",
        "--first-parent",
        "--reverse",
        head_sha,
    ).splitlines()
    if not commits:
        raise PinError(f"cannot enumerate first-parent history for {head_sha}")
    state = _local_release_state_at_commit(
        ledger_git,
        head_sha,
        previous_release_head=previous_release_head,
    )
    final_inventory, _ = _local_release_inventory_at_commit(
        ledger_git,
        head_sha,
        require_complete_siblings=True,
    )
    previous_inventory: dict[str, str] = {}
    for commit in commits:
        inventory, immutable_prefix = _local_release_inventory_at_commit(
            ledger_git,
            commit,
            require_complete_siblings=False,
        )
        _require_inventory_progress(
            previous_inventory,
            inventory,
            final_inventory,
            label=f"commit {commit[:12]}",
        )
        if inventory:
            try:
                jsonl = subprocess.check_output(
                    ["git", "show", f"{commit}:{LEDGER_JSONL_PATH}"],
                    cwd=ledger_git,
                )
            except subprocess.CalledProcessError as exc:
                raise PinError(f"cannot read {LEDGER_JSONL_PATH} at {commit}") from exc
            _require_inventory_head_witnesses_state(
                inventory,
                state.verification,
                jsonl,
                immutable_prefix,
                label=f"commit {commit[:12]}",
            )
        previous_inventory = inventory
    if previous_inventory != final_inventory:
        raise PinError(
            f"first-parent history does not end at release inventory for {head_sha}"
        )
    return state


def _null_release_window() -> dict[str, Any]:
    return {key: None for key in RELEASE_WINDOW_KEYS}


def _release_window(included: Any, excluded: Any | None) -> dict[str, Any]:
    value = {
        "witnessedInReleaseIndex": included.release_index,
        "witnessedInReleaseFreetsaGenTimeUtc": _format_utc(
            included.receipt_times["freetsa"]
        ),
        "witnessedInReleaseDigicertGenTimeUtc": _format_utc(
            included.receipt_times["digicert"]
        ),
        "lastExcludedReleaseIndex": None,
        "lastExcludedReleaseFreetsaGenTimeUtc": None,
        "lastExcludedReleaseDigicertGenTimeUtc": None,
    }
    if excluded is not None:
        value.update(
            {
                "lastExcludedReleaseIndex": excluded.release_index,
                "lastExcludedReleaseFreetsaGenTimeUtc": _format_utc(
                    excluded.receipt_times["freetsa"]
                ),
                "lastExcludedReleaseDigicertGenTimeUtc": _format_utc(
                    excluded.receipt_times["digicert"]
                ),
            }
        )
    return value


def _rows_with_release_windows(
    rows: list[dict[str, Any]], verification: ChainVerification | None
) -> list[dict[str, Any]]:
    if verification is None:
        return [{**row, **_null_release_window()} for row in rows]
    releases = verification.releases
    release_cursor = 0
    excluded = None
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        while (
            release_cursor < len(releases)
            and int(releases[release_cursor].manifest["state"]["lineCount"]) <= index
        ):
            excluded = releases[release_cursor]
            release_cursor += 1
        if release_cursor >= len(releases):
            raise PinError(f"no verified release witnesses ledger row {index}")
        included = releases[release_cursor]
        window = _release_window(included, excluded)
        if excluded is not None:
            accepted_at = _strict_utc_datetime(
                row.get("acceptedAtUtc"), f"row {index}.acceptedAtUtc"
            )
            last_excluded = max(excluded.receipt_times.values())
            if accepted_at < last_excluded - dt.timedelta(
                seconds=DEFAULT_CLOCK_SKEW_SECONDS
            ):
                raise PinError(
                    f"row {index} acceptedAtUtc {row['acceptedAtUtc']} predates "
                    f"last excluding release {excluded.release_index} beyond "
                    f"{DEFAULT_CLOCK_SKEW_SECONDS}s skew"
                )
        result.append({**row, **window})
    return result


def _pin_has_catalog(pin: dict[str, Any]) -> bool:
    return PIN_CATALOG_KEYS.issubset(pin)


def load_pin() -> dict[str, Any] | None:
    if not PIN_PATH.exists():
        return None
    pin = json.loads(PIN_PATH.read_text())
    if type(pin) is not dict:
        raise PinError("ledger pin must be a JSON object")
    if pin.get("schemaVersion") != PIN_SCHEMA:
        raise PinError(f"unsupported pin schema: {pin.get('schemaVersion')!r}")
    allowed = PIN_BASE_KEYS | PIN_CATALOG_KEYS | {"releaseHead"}
    missing = PIN_BASE_KEYS - set(pin)
    unknown = set(pin) - allowed
    if missing or unknown:
        raise PinError(
            f"pin keys are not closed-world: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )
    catalog_keys = set(pin) & PIN_CATALOG_KEYS
    if catalog_keys and catalog_keys != PIN_CATALOG_KEYS:
        raise PinError(
            "pin catalog commitment must contain catalogSha256 and catalogBytes "
            "together"
        )
    if pin["repo"] != LEDGER_REPO or pin["branch"] != LEDGER_BRANCH:
        raise PinError("pin repo/branch does not match the configured ledger")
    if type(pin["sha"]) is not str or not re.fullmatch(r"[0-9a-f]{40}", pin["sha"]):
        raise PinError("pin sha is not a commit SHA")
    if type(pin["jsonlSha256"]) is not str or not re.fullmatch(
        r"[0-9a-f]{64}", pin["jsonlSha256"]
    ):
        raise PinError("pin jsonlSha256 is not a SHA-256 digest")
    for key in ("jsonlBytes", "lineCount"):
        if type(pin[key]) is not int or pin[key] < 0:
            raise PinError(f"pin {key} must be a non-negative integer")
    if _pin_has_catalog(pin):
        if type(pin["catalogSha256"]) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", pin["catalogSha256"]
        ):
            raise PinError("pin catalogSha256 is not a SHA-256 digest")
        if type(pin["catalogBytes"]) is not int or pin["catalogBytes"] < 0:
            raise PinError("pin catalogBytes must be a non-negative integer")
    _strict_utc_datetime(pin["pinnedAtUtc"], "pin.pinnedAtUtc")
    release_head = pin.get("releaseHead")
    if release_head is not None:
        _validate_release_head(release_head)
    return pin


def load_availability() -> dict[str, Any] | None:
    if not AVAILABILITY_PATH.exists():
        return None
    snapshot = json.loads(AVAILABILITY_PATH.read_text())
    if snapshot.get("schemaVersion") != AVAILABILITY_SCHEMA:
        raise PinError(
            f"unsupported availability schema: {snapshot.get('schemaVersion')!r}"
        )
    if AVAILABILITY_PATH.read_bytes() != canonical_bytes(snapshot) + b"\n":
        raise PinError("availability snapshot is not canonical JSON")
    return snapshot


def _write_outputs(
    *,
    sha: str,
    raw: bytes,
    catalog_raw: bytes | None,
    rows: list[dict[str, Any]],
    quarantine_count: int,
    anomalies: list[dict[str, Any]],
    pinned_at: str,
    release_state: VerifiedReleaseState,
) -> None:
    lines = _lines(raw)
    if len(rows) != len(lines):
        raise PinError(f"availability covers {len(rows)} of {len(lines)} rows")
    derived_head = (
        _release_head(release_state.verification)
        if release_state.verification is not None
        else None
    )
    if canonical_bytes(derived_head) != canonical_bytes(release_state.release_head):
        raise PinError("verified release state and releaseHead disagree")
    rows = _rows_with_release_windows(rows, release_state.verification)
    for index, (row, line) in enumerate(zip(rows, lines)):
        if row["acceptedSequence"] != index:
            raise PinError(f"availability sequence gap at {index}")
        if row["lineSha256"] != sha256_hex(line.encode("utf-8")):
            raise PinError(f"availability hash mismatch at line {index + 1}")
    _strict_utc_datetime(pinned_at, "pinnedAtUtc")
    pin = {
        "schemaVersion": PIN_SCHEMA,
        "repo": LEDGER_REPO,
        "branch": LEDGER_BRANCH,
        "sha": sha,
        "jsonlSha256": sha256_hex(raw),
        "jsonlBytes": len(raw),
        **(
            {
                "catalogSha256": sha256_hex(catalog_raw),
                "catalogBytes": len(catalog_raw),
            }
            if catalog_raw is not None
            else {}
        ),
        "lineCount": len(lines),
        "pinnedAtUtc": pinned_at,
        "releaseHead": release_state.release_head,
    }
    availability = {
        "schemaVersion": AVAILABILITY_SCHEMA,
        "repo": LEDGER_REPO,
        "branch": LEDGER_BRANCH,
        "headSha": sha,
        "jsonlSha256": pin["jsonlSha256"],
        **({"catalogSha256": pin["catalogSha256"]} if catalog_raw is not None else {}),
        "legacyQuarantineLineCount": quarantine_count,
        "historyAnomalies": anomalies,
        "rows": rows,
    }
    body = ",\n".join("  " + json.dumps(row, separators=(",", ":")) for row in rows)
    generated = (
        "// Generated by scripts/pin_ledger.py from the thesis-facts branch\n"
        "// history. Do not edit: acceptance times witness when each row\n"
        "// entered the append-only ledger, independent of publisher dates.\n"
        "// Release receipt genTimes prove exclusion or state existence; they\n"
        "// do not timestamp the later Git acceptance event.\n"
        "export interface LedgerAvailabilityRow {\n"
        "  sourceRecordId: string;\n"
        "  acceptedSequence: number;\n"
        "  acceptedAtUtc: string;\n"
        "  acceptedCommit: string;\n"
        "  lineSha256: string;\n"
        '  custody: "append_derived" | "rewritten_in_place";\n'
        "  witnessedInReleaseIndex: number | null;\n"
        "  witnessedInReleaseFreetsaGenTimeUtc: string | null;\n"
        "  witnessedInReleaseDigicertGenTimeUtc: string | null;\n"
        "  lastExcludedReleaseIndex: number | null;\n"
        "  lastExcludedReleaseFreetsaGenTimeUtc: string | null;\n"
        "  lastExcludedReleaseDigicertGenTimeUtc: string | null;\n"
        "}\n\n"
        f"export const LEDGER_AVAILABILITY_HEAD_SHA = {json.dumps(sha)};\n"
        "export const LEDGER_LEGACY_QUARANTINE_LINE_COUNT = "
        f"{quarantine_count};\n\n"
        "export const LEDGER_AVAILABILITY: readonly LedgerAvailabilityRow[] = [\n"
        f"{body}\n"
        "];\n"
    )
    payloads = {
        AVAILABILITY_PATH: canonical_bytes(availability) + b"\n",
        GENERATED_PATH: generated.encode("utf-8"),
        # The pin is replaced last. If a local filesystem failure interrupts
        # publication, no committed pin can name a state whose supporting
        # availability outputs were not already written.
        PIN_PATH: (json.dumps(pin, indent=2) + "\n").encode("utf-8"),
    }
    staged: dict[pathlib.Path, pathlib.Path] = {}
    try:
        for path, payload in payloads.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                output.write(payload)
                staged[path] = pathlib.Path(output.name)
            staged[path].chmod(0o644)
        for path in (AVAILABILITY_PATH, GENERATED_PATH, PIN_PATH):
            os.replace(staged[path], path)
            staged.pop(path)
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)
    availability_hash = canonical_sha256(availability)
    catalog_disposition = (
        f", catalog {pin['catalogSha256'][:16]}…/{pin['catalogBytes']} bytes"
        if catalog_raw is not None
        else ""
    )
    print(
        f"pinned {sha} ({len(lines)} rows, jsonl {pin['jsonlSha256'][:16]}…"
        f"{catalog_disposition})"
    )
    print(f"availability {availability_hash[:16]}… quarantine<{quarantine_count}")


def _git(ledger_git: pathlib.Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ledger_git, text=True).strip()


def _local_catalog_at_commit(
    ledger_git: pathlib.Path,
    sha: str,
    *,
    required: bool,
) -> bytes | None:
    """Read the optional catalog from one local commit and bind its Git blob."""

    try:
        listing = subprocess.check_output(
            ["git", "ls-tree", "-z", sha, "--", LEDGER_CATALOG_PATH],
            cwd=ledger_git,
        )
    except subprocess.CalledProcessError as exc:
        raise PinError(f"cannot inspect {LEDGER_CATALOG_PATH} at {sha}") from exc
    records = [record for record in listing.split(b"\0") if record]
    if not records:
        if required:
            raise PinError(f"commit {sha} is missing required {LEDGER_CATALOG_PATH}")
        return None
    if len(records) != 1 or b"\t" not in records[0]:
        raise PinError(f"cannot identify {LEDGER_CATALOG_PATH} at {sha}")
    metadata, raw_path = records[0].split(b"\t", 1)
    try:
        mode, object_type, object_id = metadata.decode("ascii").split(" ")
        path = raw_path.decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise PinError(
            f"cannot parse {LEDGER_CATALOG_PATH} tree entry at {sha}"
        ) from exc
    if (
        path != LEDGER_CATALOG_PATH
        or object_type != "blob"
        or mode not in {"100644", "100755"}
        or re.fullmatch(r"[0-9a-f]{40}", object_id) is None
    ):
        raise PinError(f"{LEDGER_CATALOG_PATH} at {sha} is not a regular Git blob")
    try:
        raw = subprocess.check_output(
            ["git", "show", f"{sha}:{LEDGER_CATALOG_PATH}"], cwd=ledger_git
        )
    except subprocess.CalledProcessError as exc:
        raise PinError(f"cannot read {LEDGER_CATALOG_PATH} at {sha}") from exc
    actual_object_id = _git_blob_sha1(raw)
    if actual_object_id != object_id:
        raise PinError(
            f"local catalog bytes hash to {actual_object_id}, tree requires {object_id}"
        )
    return raw


def _local_registry_at_commit(ledger_git: pathlib.Path, sha: str) -> bytes | None:
    """Read the optional UUID registry from one local commit, blob-bound."""

    try:
        listing = subprocess.check_output(
            ["git", "ls-tree", "-z", sha, "--", LEDGER_REGISTRY_PATH],
            cwd=ledger_git,
        )
    except subprocess.CalledProcessError as exc:
        raise PinError(f"cannot inspect {LEDGER_REGISTRY_PATH} at {sha}") from exc
    records = [record for record in listing.split(b"\0") if record]
    if not records:
        return None
    if len(records) != 1 or b"\t" not in records[0]:
        raise PinError(f"cannot identify {LEDGER_REGISTRY_PATH} at {sha}")
    metadata, raw_path = records[0].split(b"\t", 1)
    try:
        mode, object_type, object_id = metadata.decode("ascii").split(" ")
        path = raw_path.decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise PinError(
            f"cannot parse {LEDGER_REGISTRY_PATH} tree entry at {sha}"
        ) from exc
    if (
        path != LEDGER_REGISTRY_PATH
        or object_type != "blob"
        or mode not in {"100644", "100755"}
        or re.fullmatch(r"[0-9a-f]{40}", object_id) is None
    ):
        raise PinError(f"{LEDGER_REGISTRY_PATH} at {sha} is not a regular Git blob")
    try:
        raw = subprocess.check_output(
            ["git", "show", f"{sha}:{LEDGER_REGISTRY_PATH}"], cwd=ledger_git
        )
    except subprocess.CalledProcessError as exc:
        raise PinError(f"cannot read {LEDGER_REGISTRY_PATH} at {sha}") from exc
    actual_object_id = _git_blob_sha1(raw)
    if actual_object_id != object_id:
        raise PinError(
            f"local registry bytes hash to {actual_object_id}, "
            f"tree requires {object_id}"
        )
    return raw


def _walked_lineage_declares_registry(ledger_git: pathlib.Path, head_sha: str) -> bool:
    """Whether any ancestor catalog of ``head_sha`` ever declared a UUID
    registry — and refuse an undeclared head once one did.

    Operator recovery must not become a laundering path, and merge
    topology cannot be trusted to expose one: branch names are not part
    of history, so a walk along any single parent line cannot tell "a
    side branch offered a declaration we declined" apart from "we were
    declared, an undeclared branch swallowed us with ``-s ours``, and the
    ref fast-forwarded onto the merge" — the DAGs are identical, only the
    ref movements differ. The ratchet is therefore existential over the
    FULL ancestry: every commit that touched the catalog (``rev-list
    --full-history``, no parent restriction, so neither history
    simplification nor second-parent placement can hide one) is read, and
    if any version declared ``uuid_registry_sha256``, the catalog at
    ``head_sha`` itself must still declare it. Fail-closed by design: a
    declaration merged in from an abandoned side branch binds the head
    even if its content was never adopted — re-declaring is the recovery,
    silently shedding custody is not.

    A shallow clone is refused outright: git treats the shallow boundary
    as a root, so ``rev-list`` silently omits everything behind it and an
    ancestor declaration would vanish without any error — fail open.
    """
    shallow = _git(ledger_git, "rev-parse", "--is-shallow-repository")
    if shallow.strip() == "true":
        raise PinError(
            "ledger clone is shallow — the shallow boundary poses as a "
            "root, so the ancestry scan cannot prove the registry "
            "ratchet; run `git fetch --unshallow` first"
        )
    listing = _git(
        ledger_git,
        "rev-list",
        "--full-history",
        head_sha,
        "--",
        LEDGER_CATALOG_PATH,
    )
    declaring_commit = None
    for commit in [line for line in listing.splitlines() if line]:
        catalog_raw = _local_catalog_at_commit(ledger_git, commit, required=False)
        if _declares_registry(catalog_raw):
            declaring_commit = commit
            break
    if declaring_commit is None:
        return False
    head_catalog = _local_catalog_at_commit(ledger_git, head_sha, required=False)
    if not _declares_registry(head_catalog):
        raise PinError(
            f"catalog at {head_sha} lacks the UUID registry declaration "
            f"although ancestor commit {declaring_commit} established one "
            "— registry binding cannot be downgraded away, even through "
            "rebuild_from_history"
        )
    return True


def rebuild_from_history(
    ledger_git: pathlib.Path,
    head: str | None,
    *,
    require_catalog: bool = False,
) -> None:
    """Derive per-row acceptance from the branch's full commit history."""

    ref = head or f"origin/{LEDGER_BRANCH}"
    head_sha = _git(ledger_git, "rev-parse", f"{ref}^{{commit}}")
    commit_list = _git(
        ledger_git,
        "log",
        "--reverse",
        "--format=%H %cI",
        head_sha,
        "--",
        LEDGER_JSONL_PATH,
    ).splitlines()
    if not commit_list:
        raise PinError(f"no history for {LEDGER_JSONL_PATH} at {head_sha}")

    previous_lines: list[str] = []
    lineage_declared = _walked_lineage_declares_registry(ledger_git, head_sha)
    accepted: list[tuple[str, str]] = []  # per index: (acceptedAtUtc, commit)
    introduced: list[str] = []  # per index: first content seen
    rewritten: set[int] = set()
    anomalies: list[dict[str, Any]] = []
    for entry in commit_list:
        commit, _, stamp = entry.partition(" ")
        accepted_at = _utc_instant(stamp)
        raw = subprocess.check_output(
            ["git", "show", f"{commit}:{LEDGER_JSONL_PATH}"], cwd=ledger_git
        )
        lines = _lines(raw)
        if len(lines) < len(previous_lines):
            anomalies.append(
                {
                    "kind": "truncation",
                    "commit": commit,
                    "fromRows": len(previous_lines),
                    "toRows": len(lines),
                }
            )
            del accepted[len(lines) :]
            del introduced[len(lines) :]
            rewritten = {index for index in rewritten if index < len(lines)}
        for index, line in enumerate(lines):
            if index >= len(accepted):
                accepted.append((accepted_at, commit))
                introduced.append(line)
            elif index < len(previous_lines) and previous_lines[index] != line:
                rewritten.add(index)
                accepted[index] = (accepted_at, commit)
                anomalies.append(
                    {
                        "kind": "in_place_rewrite",
                        "commit": commit,
                        "line": index + 1,
                        "sourceRecordId": _source_record_id(line, index),
                    }
                )
        previous_lines = lines

    raw = subprocess.check_output(
        ["git", "show", f"{head_sha}:{LEDGER_JSONL_PATH}"], cwd=ledger_git
    )
    lines = _lines(raw)
    rows = [
        _row(
            index,
            line,
            accepted[index][0],
            accepted[index][1],
            "rewritten_in_place" if index in rewritten else "append_derived",
        )
        for index, line in enumerate(lines)
    ]
    existing = load_availability()
    existing_pin = load_pin()
    catalog_required = require_catalog or (
        existing_pin is not None and _pin_has_catalog(existing_pin)
    )
    catalog_raw = _local_catalog_at_commit(
        ledger_git,
        head_sha,
        required=catalog_required,
    )
    quarantine_count = (
        int(existing["legacyQuarantineLineCount"]) if existing else len(lines)
    )
    release_state = _local_release_history_state(
        ledger_git,
        head_sha,
        previous_release_head=(
            existing_pin.get("releaseHead") if existing_pin is not None else None
        ),
    )
    _validate_catalog_and_registry(
        catalog_raw,
        _local_registry_at_commit(ledger_git, head_sha),
        raw,
        label=f"{LEDGER_CATALOG_PATH} at {head_sha}",
        registry_expected=lineage_declared,
    )
    _write_outputs(
        sha=head_sha,
        raw=raw,
        catalog_raw=catalog_raw,
        rows=rows,
        quarantine_count=quarantine_count,
        anomalies=anomalies,
        pinned_at=utc_now(),
        release_state=release_state,
    )


def refresh(*, require_catalog: bool = False) -> None:
    """Advance the pin to the branch head, verifying append-only extension."""

    pin = load_pin()
    availability = load_availability()
    if pin is None or availability is None:
        raise PinError(
            "no committed pin/availability; run --rebuild-from-history first"
        )
    if (
        availability.get("headSha") != pin["sha"]
        or availability.get("jsonlSha256") != pin["jsonlSha256"]
        # The pin is published last. A legacy pin may therefore temporarily
        # see a catalog-bearing availability file after an interrupted first
        # migration; same-SHA refresh safely re-fetches and repairs it. Once
        # the pin itself carries catalog metadata, equality is mandatory.
        or (
            _pin_has_catalog(pin)
            and availability.get("catalogSha256") != pin["catalogSha256"]
        )
    ):
        raise PinError(
            "committed availability does not match the current pin; "
            "refusing to build on partial local outputs"
        )
    head = _api(f"commits/{LEDGER_BRANCH}")
    head_sha = str(head.get("sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise PinError(f"ledger API returned a non-commit value: {head_sha!r}")

    old_raw = _jsonl_at(pin["sha"])
    if sha256_hex(old_raw) != pin["jsonlSha256"]:
        raise PinError(
            "pinned bytes no longer match the pin — upstream history changed"
        )
    old_lines = _lines(old_raw)
    catalog_required = require_catalog or _pin_has_catalog(pin)
    pinned_commit = head if head_sha == pin["sha"] else _api(f"commits/{pin['sha']}")
    old_catalog = _remote_catalog_at_commit(
        pin["sha"],
        pinned_commit,
        old_raw,
        required=(
            catalog_required if head_sha == pin["sha"] else _pin_has_catalog(pin)
        ),
    )
    old_registry = _remote_registry_at_commit(pin["sha"], pinned_commit, old_raw)
    if _pin_has_catalog(pin) and (
        old_catalog is None
        or sha256_hex(old_catalog) != pin["catalogSha256"]
        or len(old_catalog) != pin["catalogBytes"]
    ):
        raise PinError(
            "pinned catalog bytes no longer match the pin — upstream history changed"
        )
    if _pin_has_catalog(pin) and head_sha != pin["sha"]:
        assert old_catalog is not None
        _validate_catalog_binding(
            old_catalog,
            old_raw,
            label=f"{LEDGER_CATALOG_PATH} at {pin['sha']}",
            registry_raw=old_registry,
        )
    if head_sha == pin["sha"]:
        # Reverify and regenerate even without a remote move. This migrates a
        # legacy pin already at a witnessed commit and repairs/refuses any
        # interrupted pin-last output publication instead of returning early.
        release_state = _remote_release_state_at_commit(
            head_sha,
            head,
            old_raw,
            previous_release_head=pin.get("releaseHead"),
        )
        _validate_catalog_and_registry(
            old_catalog,
            old_registry,
            old_raw,
            label=f"{LEDGER_CATALOG_PATH} at {head_sha}",
        )
        _write_outputs(
            sha=head_sha,
            raw=old_raw,
            catalog_raw=old_catalog,
            rows=list(availability["rows"]),
            quarantine_count=int(availability["legacyQuarantineLineCount"]),
            anomalies=list(availability["historyAnomalies"]),
            pinned_at=str(pin["pinnedAtUtc"]),
            release_state=release_state,
        )
        print(f"pin already at {head_sha}; state reverified")
        return

    # Verify the exact final commit once with production trust anchors. Every
    # crossed commit below must expose an immutable prefix-subset of these exact,
    # authenticated release-artifact Git objects and its release head must
    # witness that commit's own JSONL bytes. This preserves the stronger
    # no-unwitnessed-intermediate guarantee without re-running OpenSSL over the
    # growing chain at every commit.
    head_raw = _jsonl_at(head_sha)
    head_catalog = _remote_catalog_at_commit(
        head_sha,
        head,
        head_raw,
        required=catalog_required,
    )
    head_registry = _remote_registry_at_commit(head_sha, head, head_raw)
    release_state = _remote_release_state_at_commit(
        head_sha,
        head,
        head_raw,
        previous_release_head=pin.get("releaseHead"),
    )
    final_inventory, _ = _remote_release_inventory_at_commit(
        head_sha,
        head,
        head_raw,
        require_complete_siblings=True,
    )
    previous_inventory, old_prefix = _remote_release_inventory_at_commit(
        pin["sha"],
        pinned_commit,
        old_raw,
        require_complete_siblings=False,
    )
    _require_inventory_progress(
        {},
        previous_inventory,
        final_inventory,
        label=f"pinned commit {pin['sha'][:12]}",
    )
    _require_inventory_head_witnesses_state(
        previous_inventory,
        release_state.verification,
        old_raw,
        old_prefix,
        label=f"pinned commit {pin['sha'][:12]}",
    )

    # Every intermediate commit must extend its parent line-for-line, so a
    # rewrite-then-restore between refreshes cannot hide. GitHub's compare
    # endpoint caps its commit list at 250 and paginates beyond that; taking
    # one page would skip the omitted middle, so a rewrite-then-restore in
    # that gap could pass (finding 10). Page until every advertised commit
    # is present and assert the count matches total_commits.
    commits = _compare_commits(pin["sha"], head_sha)

    rows = list(availability["rows"])
    previous_lines = old_lines
    previous_raw = old_raw
    expected_parent = pin["sha"]
    visited: set[str] = {pin["sha"]}
    # The registry ratchet must hold across the CROSSED commits too, not
    # just the two endpoints: a declaration committed and then removed
    # between refreshes would otherwise advance the pin straight over the
    # downgrade. Once a declaration is seen the flag latches and no
    # further catalog fetches are needed.
    declared_seen = _declares_registry(old_catalog)
    for commit in commits:
        commit_sha = str(commit["sha"])
        commit_payload = (
            head if commit_sha == head_sha else _api(f"commits/{commit_sha}")
        )
        is_merge = _require_walk_parent(
            commit_payload, commit_sha, expected_parent, visited
        )
        visited.add(commit_sha)
        raw = _jsonl_at(commit_sha)
        if not declared_seen and _declares_registry(
            _remote_catalog_at_commit(
                commit_sha,
                commit_payload,
                raw,
                required=False,
            )
        ):
            declared_seen = True
        lines = _lines(raw)
        if is_merge and raw != previous_raw:
            raise PinError(
                f"merge commit {commit_sha[:12]} changes ledger bytes; "
                "appends must arrive on single-parent commits"
            )
        if lines != previous_lines:
            _require_extension(
                previous_lines,
                lines,
                label=f"commit {commit_sha[:12]}",
            )
            accepted_at = _utc_instant(str(commit["commit"]["committer"]["date"]))
            for index in range(len(previous_lines), len(lines)):
                rows.append(
                    _row(
                        index,
                        lines[index],
                        accepted_at,
                        commit_sha,
                        "append_derived",
                    )
                )
        inventory, immutable_prefix = _remote_release_inventory_at_commit(
            commit_sha,
            commit_payload,
            raw,
            require_complete_siblings=False,
        )
        _require_inventory_progress(
            previous_inventory,
            inventory,
            final_inventory,
            label=f"commit {commit_sha[:12]}",
        )
        _require_inventory_head_witnesses_state(
            inventory,
            release_state.verification,
            raw,
            immutable_prefix,
            label=f"commit {commit_sha[:12]}",
        )
        previous_inventory = inventory
        expected_parent = commit_sha
        previous_lines = lines
        previous_raw = raw

    if head_raw != previous_raw or _lines(head_raw) != previous_lines:
        raise PinError("branch head bytes disagree with its own commit history")
    if previous_inventory != final_inventory:
        raise PinError("branch history does not end at the verified release inventory")
    _validate_catalog_and_registry(
        head_catalog,
        head_registry,
        head_raw,
        label=f"{LEDGER_CATALOG_PATH} at {head_sha}",
        registry_expected=declared_seen,
    )
    _write_outputs(
        sha=head_sha,
        raw=head_raw,
        catalog_raw=head_catalog,
        rows=rows,
        quarantine_count=int(availability["legacyQuarantineLineCount"]),
        anomalies=list(availability["historyAnomalies"]),
        pinned_at=utc_now(),
        release_state=release_state,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-from-history", action="store_true")
    parser.add_argument(
        "--ledger-git",
        type=pathlib.Path,
        help="local clone of PolicyEngine/ledger with the thesis-facts branch",
    )
    parser.add_argument(
        "--head", help="pin this commit instead of the branch head (rebuild only)"
    )
    parser.add_argument(
        "--require-catalog",
        action="store_true",
        help=(
            "require ledger/series_catalog.json at the selected SHA; once a pin "
            "records catalog metadata, later refreshes require it automatically"
        ),
    )
    args = parser.parse_args()
    try:
        if args.rebuild_from_history:
            if not args.ledger_git:
                raise PinError("--rebuild-from-history requires --ledger-git")
            rebuild_from_history(
                args.ledger_git,
                args.head,
                require_catalog=args.require_catalog,
            )
        else:
            refresh(require_catalog=args.require_catalog)
    except (PinError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"ledger pin failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
