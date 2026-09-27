#!/usr/bin/env python3
"""Witness the upstream fact ledger's exact bytes into the record chain.

The recorder archives the site's DERIVED ledger.json, but the upstream
``official_observations.jsonl`` on PolicyEngine/chronicle's thesis-facts branch
remained mutable history: nothing in Thesis's witnessed records held the raw
bytes. This run archives, custody-rooted and chain-committed by the next
recorder digest:

- the observation JSONL bytes at one immutable commit SHA (never a branch);
- the optional series catalog bytes at that same immutable commit SHA;
- the GitHub commit API responses for the thesis-facts branch head and the
  ledger main head, binding both SHAs to their commit metadata;
- the complete direct ``releases/manifests`` Git tree at that commit, including
  the exact manifest JSON and binary RFC 3161 receipt bytes;
- optional extra upstream artifacts (``--extra name=path-or-url``), e.g. the
  populace consumer-artifact bytes a population release was built from.

Ledger mutability stops mattering for history once these bytes are inside
brier's witnessed chain.

Usage:
    python3 scripts/witness_upstream_ledger.py [--ledger-sha SHA]
        [--expect-line-count N] [--expect-jsonl-sha256 HEX]
        [--require-catalog] [--expect-catalog-sha256 HEX]
        [--expect-catalog-bytes N]
        [--extra name=path-or-url ...] [--note TEXT]
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import gzip
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from canonical_json import canonical_bytes, canonical_sha256
from verify_custody import verify_run

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEDGER_REPO = "PolicyEngine/chronicle"
LEDGER_BRANCH = "codex/thesis-ledger-facts"
LEDGER_JSONL_PATH = "ledger/official_observations.jsonl"
LEDGER_CATALOG_PATH = "ledger/series_catalog.json"
LEDGER_RELEASE_DIRECTORY = "releases/manifests"
ARCHIVE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
RELEASE_ARCHIVE_SCHEMA = "thesis_ledger_release_archive_v1"
WITNESS_SCHEMA = "thesis_ledger_witness_run_v2"


@dataclass(frozen=True)
class ArchiveInput:
    name: str
    raw: bytes
    role: str
    url: str | None
    metadata: dict[str, Any] | None = None


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "thesis-witness"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _commit_api(ref: str) -> tuple[str, bytes]:
    raw = _fetch(f"https://api.github.com/repos/{LEDGER_REPO}/commits/{ref}")
    sha = str(json.loads(raw).get("sha", ""))
    if GIT_SHA_RE.fullmatch(sha) is None:
        raise ValueError(f"ledger commit API returned a non-commit value: {sha!r}")
    return sha, raw


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def _git_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or GIT_SHA_RE.fullmatch(value) is None:
        raise ValueError(f"{label} is not a 40-character lowercase Git SHA")
    return value


def _commit_tree_sha(commit_raw: bytes) -> str:
    payload = _json_object(commit_raw, "ledger commit API response")
    commit = payload.get("commit")
    tree = commit.get("tree") if isinstance(commit, dict) else None
    value = tree.get("sha") if isinstance(tree, dict) else None
    return _git_sha(value, "ledger commit tree SHA")


def _tree_entries(payload: dict[str, Any], label: str) -> dict[str, dict[str, str]]:
    if payload.get("truncated") is not False:
        raise ValueError(f"{label} is truncated or lacks an explicit completeness flag")
    raw_entries = payload.get("tree")
    if not isinstance(raw_entries, list):
        raise ValueError(f"{label} lacks a tree entry list")
    entries: dict[str, dict[str, str]] = {}
    for number, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            raise ValueError(f"{label} entry {number} is not an object")
        path = raw_entry.get("path")
        if not isinstance(path, str) or not path or path in {".", ".."} or "/" in path:
            raise ValueError(f"{label} entry {number} is not a direct child: {path!r}")
        if path in entries:
            raise ValueError(f"{label} contains duplicate path {path!r}")
        object_type = raw_entry.get("type")
        mode = raw_entry.get("mode")
        if not isinstance(object_type, str) or not isinstance(mode, str):
            raise ValueError(f"{label} entry {path!r} lacks type or mode")
        entries[path] = {
            "path": path,
            "mode": mode,
            "type": object_type,
            "sha": _git_sha(raw_entry.get("sha"), f"{label} entry {path!r} SHA"),
        }
    return entries


def _git_tree_sha(entries: dict[str, dict[str, str]]) -> str:
    body = bytearray()
    for entry in entries.values():
        path = entry["path"]
        if "\0" in path:
            raise ValueError("Git tree path contains NUL")
        mode = entry["mode"].lstrip("0") or "0"
        body.extend(f"{mode} {path}\0".encode("utf-8"))
        body.extend(bytes.fromhex(entry["sha"]))
    header = f"tree {len(body)}\0".encode("ascii")
    return hashlib.sha1(header + body, usedforsecurity=False).hexdigest()


def _fetch_git_tree(tree_sha: str, label: str) -> tuple[dict[str, Any], bytes, str]:
    url = f"https://api.github.com/repos/{LEDGER_REPO}/git/trees/{tree_sha}"
    raw = _fetch(url)
    payload = _json_object(raw, label)
    actual_sha = _git_sha(payload.get("sha"), f"{label} response SHA")
    if actual_sha != tree_sha:
        raise ValueError(
            f"{label} response identifies {actual_sha}, expected {tree_sha}"
        )
    entries = _tree_entries(payload, label)
    computed_sha = _git_tree_sha(entries)
    if computed_sha != tree_sha:
        raise ValueError(
            f"{label} entries hash to Git tree {computed_sha}, expected {tree_sha}"
        )
    return payload, raw, url


def _child_tree_sha(
    entries: dict[str, dict[str, str]], child: str, label: str
) -> str | None:
    entry = entries.get(child)
    if entry is None:
        return None
    if entry["type"] != "tree" or entry["mode"] != "040000":
        raise ValueError(f"{label} {child!r} is not a regular Git tree")
    return entry["sha"]


def _git_blob_sha(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw, usedforsecurity=False).hexdigest()


def _release_archive_inputs(
    branch_sha: str, branch_commit_raw: bytes
) -> tuple[dict[str, Any], list[ArchiveInput]]:
    """Fetch a complete, commit-tree-bound snapshot of release manifest files."""

    commit_tree_sha = _commit_tree_sha(branch_commit_raw)
    root, root_raw, root_url = _fetch_git_tree(commit_tree_sha, "commit tree")
    root_entries = _tree_entries(root, "commit tree")
    tree_names: dict[str, str | None] = {
        "commit": "ledger-commit-tree.json",
        "releases": None,
        "manifests": None,
    }
    inputs = [
        ArchiveInput(
            name=tree_names["commit"],
            raw=root_raw,
            role="ledger_commit_tree_api",
            url=root_url,
            metadata={"gitTreeSha": commit_tree_sha},
        )
    ]

    releases_tree_sha = _child_tree_sha(root_entries, "releases", "commit tree")
    manifests_tree_sha: str | None = None
    manifest_entries: dict[str, dict[str, str]] = {}
    if releases_tree_sha is not None:
        releases, releases_raw, releases_url = _fetch_git_tree(
            releases_tree_sha, "releases tree"
        )
        releases_entries = _tree_entries(releases, "releases tree")
        tree_names["releases"] = "ledger-releases-tree.json"
        inputs.append(
            ArchiveInput(
                name=tree_names["releases"],
                raw=releases_raw,
                role="ledger_releases_tree_api",
                url=releases_url,
                metadata={"gitTreeSha": releases_tree_sha},
            )
        )
        manifests_tree_sha = _child_tree_sha(
            releases_entries, "manifests", "releases tree"
        )
    if manifests_tree_sha is not None:
        manifests, manifests_raw, manifests_url = _fetch_git_tree(
            manifests_tree_sha, "release manifests tree"
        )
        manifest_entries = _tree_entries(manifests, "release manifests tree")
        tree_names["manifests"] = "ledger-release-manifests-tree.json"
        inputs.append(
            ArchiveInput(
                name=tree_names["manifests"],
                raw=manifests_raw,
                role="ledger_release_manifests_tree_api",
                url=manifests_url,
                metadata={"gitTreeSha": manifests_tree_sha},
            )
        )

    files: list[dict[str, Any]] = []
    for basename, entry in sorted(manifest_entries.items()):
        if entry["type"] != "blob" or entry["mode"] not in {"100644", "100755"}:
            raise ValueError(
                f"release manifests entry {basename!r} is not a regular Git blob"
            )
        source_path = f"{LEDGER_RELEASE_DIRECTORY}/{basename}"
        encoded_path = urllib.parse.quote(source_path, safe="/")
        url = (
            f"https://raw.githubusercontent.com/{LEDGER_REPO}/{branch_sha}/"
            f"{encoded_path}"
        )
        raw = _fetch(url)
        actual_blob_sha = _git_blob_sha(raw)
        if actual_blob_sha != entry["sha"]:
            raise ValueError(
                f"release file {source_path} has Git blob SHA {actual_blob_sha}, "
                f"expected {entry['sha']}"
            )
        archive_name = (
            "ledger-release-" + hashlib.sha256(source_path.encode("utf-8")).hexdigest()
        )
        raw_sha256 = hashlib.sha256(raw).hexdigest()
        files.append(
            {
                "path": source_path,
                "gitBlobSha": entry["sha"],
                "sha256": raw_sha256,
                "bytes": len(raw),
                "archiveName": archive_name,
            }
        )
        inputs.append(
            ArchiveInput(
                name=archive_name,
                raw=raw,
                role="ledger_release_file",
                url=url,
                metadata={"sourcePath": source_path, "gitBlobSha": entry["sha"]},
            )
        )

    release_archive = {
        "schemaVersion": RELEASE_ARCHIVE_SCHEMA,
        "directory": LEDGER_RELEASE_DIRECTORY,
        "commitTreeSha": commit_tree_sha,
        "releasesTreeSha": releases_tree_sha,
        "manifestsTreeSha": manifests_tree_sha,
        "treeArchiveNames": tree_names,
        "fileCount": len(files),
        "files": files,
    }
    return release_archive, inputs


def _archive(
    run_dir: pathlib.Path, name: str, raw: bytes, *, role: str, url: str | None
) -> dict[str, Any]:
    if not ARCHIVE_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid witness archive name: {name!r}")
    compressed = gzip.compress(raw, mtime=0)
    path = run_dir / "upstream" / f"{name}.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite witness archive: {path}")
    path.write_bytes(compressed)
    record: dict[str, Any] = {
        "name": name,
        "role": role,
        "archive": {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "gzipSha256": hashlib.sha256(compressed).hexdigest(),
            "gzipBytes": len(compressed),
            "contentEncoding": "gzip",
        },
    }
    if url:
        record["url"] = url
    return record


def _validate_jsonl(raw: bytes) -> dict[str, Any]:
    # Newline-only splitting, matching pin_ledger._lines and the custody
    # verifier: str.splitlines() also breaks on U+0085/U+2028/U+2029, which
    # JSON leaves unescaped inside strings, and would make the witnessed
    # lineCount disagree with the pinned one for such a row.
    lines = [line for line in raw.decode("utf-8").split("\n") if line.strip()]
    seen: set[str] = set()
    for number, line in enumerate(lines, start=1):
        row = json.loads(line)
        if not isinstance(row, dict) or not row.get("source_record_id"):
            raise ValueError(f"jsonl line {number} lacks source_record_id")
        seen.add(str(row["source_record_id"]))
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "lineCount": len(lines),
        "sourceRecordIdCount": len(seen),
    }


def _validate_catalog(raw: bytes, jsonl: dict[str, Any]) -> dict[str, Any]:
    """Validate and commit the catalog generated from the witnessed JSONL."""

    catalog = _json_object(raw, "ledger series catalog")
    if not isinstance(catalog.get("series"), list):
        raise ValueError("ledger series catalog lacks a series array")
    if catalog.get("observations_sha256") != jsonl["sha256"]:
        raise ValueError(
            "ledger series catalog observations_sha256 does not match "
            "official_observations.jsonl"
        )
    if (
        type(catalog.get("observation_rows")) is not int
        or catalog["observation_rows"] != jsonl["lineCount"]
    ):
        raise ValueError(
            "ledger series catalog observation_rows does not match "
            "official_observations.jsonl"
        )
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _catalog_at(sha: str) -> tuple[bytes, str] | None:
    """Fetch the optional catalog at ``sha``; only a real 404 means absent."""

    url = f"https://raw.githubusercontent.com/{LEDGER_REPO}/{sha}/{LEDGER_CATALOG_PATH}"
    try:
        return _fetch(url), url
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _seal(run_dir: pathlib.Path, manifest: dict[str, Any]) -> None:
    """Seal the witness inventory exactly like the resolver custody flow."""

    created_at = str(manifest["retrievedAt"])
    refs: list[dict[str, Any]] = []
    rooted: list[dict[str, Any]] = []
    for record in manifest["upstream"]:
        archive = record["archive"]
        path = ROOT / archive["path"]
        relative = path.resolve().relative_to(run_dir.resolve()).as_posix()
        ref = {
            "artifactType": "upstream_archive",
            "path": path.resolve().relative_to(ROOT).as_posix(),
            "sha256": archive["gzipSha256"],
            "bytes": archive["gzipBytes"],
            "createdAt": created_at,
        }
        refs.append(ref)
        rooted.append({**ref, "path": relative})
    manifest.update(
        {
            "custodyInventoryVersion": 2,
            "runMode": "ledger_witness",
            "ok": True,
            "manifestHashSemantics": (
                "canonical-json-v1; exclude artifacts where "
                "artifactType=manifest and exclude custodyRootSha256"
            ),
            "artifacts": refs,
        }
    )
    self_payload = copy.deepcopy(manifest)
    self_payload.pop("custodyRootSha256", None)
    self_bytes = canonical_bytes(self_payload)
    manifest_ref = {
        "artifactType": "manifest",
        "path": (run_dir / "manifest.json").resolve().relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(self_bytes).hexdigest(),
        "bytes": len(self_bytes),
        "createdAt": created_at,
        "hashMode": manifest["manifestHashSemantics"],
    }
    manifest["artifacts"] = [*refs, manifest_ref]
    custody = {
        "schemaVersion": "thesis_custody_root_v1",
        "custodyInventoryVersion": 2,
        "runMode": "ledger_witness",
        "hashAlgorithm": "sha256",
        "canonicalJson": (
            "UTF-16 code-unit key order; ECMAScript JSON number/string encoding"
        ),
        "artifacts": rooted,
        "manifestWithoutCustodyRoot": {
            "path": "manifest.json",
            "excludedField": "custodyRootSha256",
            "canonicalJsonSha256": canonical_sha256(manifest),
        },
    }
    (run_dir / "custody_root.json").write_text(json.dumps(custody, indent=2) + "\n")
    manifest["custodyRootSha256"] = canonical_sha256(custody)
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    verify_run(run_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ledger-sha", help="witness this exact commit (default: branch head)"
    )
    parser.add_argument("--expect-line-count", type=int)
    parser.add_argument("--expect-jsonl-sha256")
    parser.add_argument(
        "--require-catalog",
        action="store_true",
        help="fail when series_catalog.json is absent at the selected SHA",
    )
    parser.add_argument("--expect-catalog-sha256")
    parser.add_argument("--expect-catalog-bytes", type=int)
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        metavar="NAME=PATH_OR_URL",
        help="additional upstream artifact to witness alongside the ledger",
    )
    parser.add_argument("--note")
    args = parser.parse_args()

    retrieved_at = utc_now()
    branch_sha, branch_commit_raw = _commit_api(args.ledger_sha or LEDGER_BRANCH)
    if args.ledger_sha and branch_sha != args.ledger_sha:
        raise SystemExit(
            f"ledger commit API resolved {branch_sha}, expected {args.ledger_sha}"
        )
    main_sha, main_commit_raw = _commit_api("main")

    jsonl_url = (
        f"https://raw.githubusercontent.com/{LEDGER_REPO}/{branch_sha}/"
        f"{LEDGER_JSONL_PATH}"
    )
    jsonl_raw = _fetch(jsonl_url)
    jsonl = _validate_jsonl(jsonl_raw)
    expected_count = args.expect_line_count
    if expected_count is not None and jsonl["lineCount"] != expected_count:
        raise SystemExit(
            f"jsonl has {jsonl['lineCount']} rows, expected {expected_count}"
        )
    if args.expect_jsonl_sha256 and jsonl["sha256"] != args.expect_jsonl_sha256:
        raise SystemExit(
            f"jsonl sha256 {jsonl['sha256']} != expected {args.expect_jsonl_sha256}"
        )

    catalog_result = _catalog_at(branch_sha)
    catalog_raw: bytes | None = None
    catalog_url: str | None = None
    catalog: dict[str, Any] | None = None
    catalog_expected = (
        args.require_catalog
        or args.expect_catalog_sha256 is not None
        or args.expect_catalog_bytes is not None
    )
    if catalog_result is None:
        if catalog_expected:
            raise SystemExit(
                f"required {LEDGER_CATALOG_PATH} is absent at {branch_sha}"
            )
    else:
        catalog_raw, catalog_url = catalog_result
        catalog = _validate_catalog(catalog_raw, jsonl)
        if (
            args.expect_catalog_sha256 is not None
            and catalog["sha256"] != args.expect_catalog_sha256
        ):
            raise SystemExit(
                f"catalog sha256 {catalog['sha256']} != expected "
                f"{args.expect_catalog_sha256}"
            )
        if (
            args.expect_catalog_bytes is not None
            and catalog["bytes"] != args.expect_catalog_bytes
        ):
            raise SystemExit(
                f"catalog has {catalog['bytes']} bytes, expected "
                f"{args.expect_catalog_bytes}"
            )

    release_archive, release_inputs = _release_archive_inputs(
        branch_sha, branch_commit_raw
    )
    archive_inputs = [
        ArchiveInput(
            name="official-observations.jsonl",
            raw=jsonl_raw,
            role="official_observations_jsonl",
            url=jsonl_url,
        ),
        *(
            [
                ArchiveInput(
                    name="series-catalog.json",
                    raw=catalog_raw,
                    role="series_catalog_json",
                    url=catalog_url,
                )
            ]
            if catalog_raw is not None
            else []
        ),
        ArchiveInput(
            name="ledger-branch-commit.json",
            raw=branch_commit_raw,
            role="ledger_branch_commit_api",
            url=f"https://api.github.com/repos/{LEDGER_REPO}/commits/{branch_sha}",
        ),
        ArchiveInput(
            name="ledger-main-commit.json",
            raw=main_commit_raw,
            role="ledger_main_commit_api",
            url=f"https://api.github.com/repos/{LEDGER_REPO}/commits/{main_sha}",
        ),
        *release_inputs,
    ]
    for extra in args.extra:
        name, _, location = extra.partition("=")
        if not location:
            raise SystemExit(f"--extra needs NAME=PATH_OR_URL, got {extra!r}")
        if location.startswith("https://"):
            raw = _fetch(location)
            url: str | None = location
        else:
            raw = pathlib.Path(location).read_bytes()
            url = None
        archive_inputs.append(
            ArchiveInput(
                name=name,
                raw=raw,
                role="extra_upstream",
                url=url,
            )
        )
    archive_names = [item.name for item in archive_inputs]
    invalid_names = [
        name for name in archive_names if ARCHIVE_NAME_RE.fullmatch(name) is None
    ]
    if invalid_names:
        raise ValueError(f"invalid witness archive names: {invalid_names}")
    if len(set(archive_names)) != len(archive_names):
        raise ValueError("witness archive names must be unique")

    stamp = retrieved_at.lower().replace(":", "-")
    run_dir = ROOT / "records" / retrieved_at[:10] / f"{stamp}-ledger-witness"
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        upstream: list[dict[str, Any]] = []
        for item in archive_inputs:
            record = _archive(
                run_dir,
                item.name,
                item.raw,
                role=item.role,
                url=item.url,
            )
            if item.metadata:
                record.update(item.metadata)
            upstream.append(record)

        manifest: dict[str, Any] = {
            "schemaVersion": WITNESS_SCHEMA,
            "retrievedAt": retrieved_at,
            "ledgerRepo": LEDGER_REPO,
            "ledgerBranch": LEDGER_BRANCH,
            "ledgerBranchSha": branch_sha,
            "ledgerMainSha": main_sha,
            "jsonl": jsonl,
            **({"catalog": catalog} if catalog is not None else {}),
            "releaseArchive": release_archive,
            "upstream": upstream,
        }
        if args.note:
            manifest["note"] = args.note
        _seal(run_dir, manifest)
    except BaseException:
        shutil.rmtree(run_dir)
        raise
    print(run_dir / "manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
