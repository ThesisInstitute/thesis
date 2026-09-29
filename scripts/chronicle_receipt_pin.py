#!/usr/bin/env python3
"""Refuse to run Chronicle's code under a receipt Chronicle did not lock.

Every witnessed append proposal stages a copy of Chronicle's ledger branch and
runs that branch's own ``scripts/build_series_catalog.py`` with this
interpreter. The generator imports ``check_thesis_facts_append``, which imports
``receipt_pins``, and both import the ``receipt`` package. So Chronicle's code
runs under the receipt thesis installed, while Chronicle has tested it only
under the receipt its own ``uv.lock`` names (its CI and append gate install
with ``uv sync --locked``).

When the two differ, the generator can fail on an import after the whole
capture pass has already run. That happened on 2026-09-28: Chronicle's ledger
branch locked receipt 0.6.2, whose ``receipt.release_chain.PinnedSigner`` 0.6.1
lacks, and resolver run 36503673388 failed while proposing the append. A newer
receipt could also import cleanly and then behave differently from the one
Chronicle tested.

This module compares three things: the receipt installed for this
interpreter, the receipt thesis's ``uv.lock`` names, and the receipt
Chronicle's ``uv.lock`` names at one commit. When they disagree it says which
one to fix. It never picks a receipt itself. Thesis's own lock decides what
is installed, because thesis's code in the same resolver process imports
``receipt.sign`` too (``witnessed_timeline`` -> ``verify_record_chain``), and
that code should run under the version thesis's suite ran.

Run it directly to compare thesis's lock with Chronicle's ledger branch;
``.github/workflows/receipt-pin-drift.yml`` does so on a schedule. With
``--installed-only`` it makes no network request and checks only that this
interpreter has the receipt thesis's lock names. ``docs/receipt-pin.md`` has
the bump checklist.

Usage:
    python3 scripts/chronicle_receipt_pin.py [--ledger-repo R] \
        [--ledger-branch B | --ledger-sha SHA] [--check-installed]
    python3 scripts/chronicle_receipt_pin.py --installed-only
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import importlib.metadata
import json
import pathlib
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]
THESIS_LOCK = ROOT / "uv.lock"
LOCK_PATH = "uv.lock"
RECEIPT = "receipt"
DEFAULT_LEDGER_REPO = "PolicyEngine/chronicle"
DEFAULT_LEDGER_BRANCH = "codex/thesis-ledger-facts"
# The bump checklist, and the last pull request that followed it.
BUMP_DOC = "docs/receipt-pin.md"
BUMP_EXAMPLE = "https://github.com/ThesisInstitute/thesis/pull/302"
_SHA_RE = re.compile(r"[0-9a-f]{40}")

GhApi = Callable[..., str]


class ReceiptPinError(ValueError):
    """A lock that does not name exactly one hash-pinned receipt."""


@dataclass(frozen=True)
class LockedPin:
    """One package as a uv.lock names it."""

    version: str
    # "sha256:<hex>" for every sdist and wheel the lock accepts.
    artifacts: frozenset[str]


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_pin(lock: bytes, *, label: str, name: str = RECEIPT) -> LockedPin | None:
    """The one ``name`` entry in a uv.lock, or ``None`` when it locks none.

    Two entries (a lock forked by environment markers) are refused: nothing
    would say which one the staged generator runs under. An entry without
    artifact hashes (a git or path source) is refused too, since its bytes
    cannot be compared.
    """

    try:
        import tomllib
    except ModuleNotFoundError as exc:  # Python 3.10; receipt needs 3.11 too
        raise ReceiptPinError(f"reading {label} needs Python 3.11+") from exc
    try:
        data = tomllib.loads(lock.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ReceiptPinError(f"{label} is not a readable uv.lock: {exc}") from exc
    packages = data.get("package")
    if not isinstance(packages, list):
        raise ReceiptPinError(f"{label} has no [[package]] entries")
    entries = [
        entry
        for entry in packages
        if isinstance(entry, dict)
        and isinstance(entry.get("name"), str)
        and _normalized(entry["name"]) == _normalized(name)
    ]
    if not entries:
        return None
    if len(entries) > 1:
        versions = ", ".join(str(entry.get("version")) for entry in entries)
        raise ReceiptPinError(
            f"{label} locks {len(entries)} {name} entries ({versions}), so it "
            f"does not say which {name} its code runs under"
        )
    entry = entries[0]
    version = entry.get("version")
    if not isinstance(version, str) or not version:
        raise ReceiptPinError(f"{label} locks {name} without a version")
    artifacts: set[str] = set()
    sdist = entry.get("sdist")
    if isinstance(sdist, dict) and isinstance(sdist.get("hash"), str):
        artifacts.add(sdist["hash"])
    wheels = entry.get("wheels")
    for wheel in wheels if isinstance(wheels, list) else []:
        if isinstance(wheel, dict) and isinstance(wheel.get("hash"), str):
            artifacts.add(wheel["hash"])
    if not artifacts:
        raise ReceiptPinError(f"{label} locks {name} {version} without artifact hashes")
    return LockedPin(version=version, artifacts=frozenset(artifacts))


def installed_version(name: str = RECEIPT) -> str | None:
    """The version installed for this interpreter, or ``None``."""

    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


_UNCHECKED = object()


def receipt_pin_refusal(
    chronicle_lock: bytes | None,
    *,
    chronicle_label: str,
    thesis_lock: bytes,
    installed: str | None | object = _UNCHECKED,
) -> str | None:
    """Why Chronicle's staged code must not run here, or ``None`` when it may.

    Pass ``installed`` (from :func:`installed_version`) to also require this
    interpreter's receipt; leave it out to compare the two locks only.
    """

    if chronicle_lock is None:
        return (
            f"{chronicle_label} has no {LOCK_PATH}, so nothing says which "
            f"{RECEIPT} its series-catalog generator was tested with"
        )
    try:
        chronicle = locked_pin(chronicle_lock, label=f"{chronicle_label} {LOCK_PATH}")
        thesis = locked_pin(thesis_lock, label=f"thesis's {LOCK_PATH}")
    except ReceiptPinError as exc:
        return str(exc)
    if chronicle is None:
        # Chronicle's code might then vendor receipt, or not need it; either
        # way thesis stages only named files, so the generator would import
        # thesis's receipt under a lock that never named it. Refuse.
        return (
            f"{chronicle_label} {LOCK_PATH} locks no {RECEIPT}, so nothing says "
            f"which {RECEIPT} its series-catalog generator was tested with"
        )
    if thesis is None:
        return (
            f"{chronicle_label} locks {RECEIPT} {chronicle.version}, but thesis's "
            f"{LOCK_PATH} locks no {RECEIPT}; add it to the custody extra at "
            f"{chronicle.version}"
        )
    if thesis.version != chronicle.version:
        return (
            f"thesis locks {RECEIPT} {thesis.version} but {chronicle_label} locks "
            f"{RECEIPT} {chronicle.version}. The resolver runs Chronicle's staged "
            f"series-catalog generator under thesis's {RECEIPT}, and Chronicle has "
            f"tested that code only under {chronicle.version}. Make the two locks "
            f"name the same {RECEIPT} before the resolver runs again. When "
            f"Chronicle moved first, pin the custody extra in pyproject.toml to "
            f"{RECEIPT}=={chronicle.version} and run `uv lock --upgrade-package "
            f"{RECEIPT}` ({BUMP_DOC} has the checklist; {BUMP_EXAMPLE} is the "
            f"last bump)"
        )
    if thesis.artifacts != chronicle.artifacts:
        only_thesis = sorted(thesis.artifacts - chronicle.artifacts)
        only_chronicle = sorted(chronicle.artifacts - thesis.artifacts)
        return (
            f"thesis and {chronicle_label} both lock {RECEIPT} {thesis.version} "
            f"but name different files (only thesis: {only_thesis or 'none'}; "
            f"only Chronicle: {only_chronicle or 'none'}), so the bytes thesis "
            f"installs may not be the bytes Chronicle tested. Re-lock the stale "
            f"side from PyPI"
        )
    if installed is _UNCHECKED:
        return None
    if installed is None:
        return (
            f"{RECEIPT} is not installed for {sys.executable}; thesis and "
            f"{chronicle_label} both lock {RECEIPT} {thesis.version}. Install the "
            f"resolver runtime from thesis's {LOCK_PATH} first "
            f"(.github/actions/install-resolver-python)"
        )
    if installed != thesis.version:
        return (
            f"{sys.executable} has {RECEIPT} {installed}, but thesis and "
            f"{chronicle_label} both lock {RECEIPT} {thesis.version}. Reinstall "
            f"the resolver runtime from thesis's {LOCK_PATH} "
            f"(.github/actions/install-resolver-python)"
        )
    return None


def installed_refusal(thesis_lock: bytes, installed: str | None) -> str | None:
    """Why this interpreter's receipt is not the one thesis's lock names."""

    try:
        thesis = locked_pin(thesis_lock, label=f"thesis's {LOCK_PATH}")
    except ReceiptPinError as exc:
        return str(exc)
    if thesis is None:
        return f"thesis's {LOCK_PATH} locks no {RECEIPT}"
    if installed != thesis.version:
        found = f"{RECEIPT} {installed}" if installed else f"no {RECEIPT}"
        return (
            f"{sys.executable} has {found}, but thesis's {LOCK_PATH} locks "
            f"{RECEIPT} {thesis.version}"
        )
    return None


def _gh_api(*args: str) -> str:
    completed = subprocess.run(
        ["gh", "api", *args], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise ReceiptPinError(
            f"gh api {' '.join(args)} failed: {completed.stderr.strip()[:500]}"
        )
    return completed.stdout


def _commit_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise ReceiptPinError(f"GitHub returned an invalid {label}: {value!r}")
    return value


def branch_head(repo: str, branch: str, *, gh: GhApi = _gh_api) -> str:
    """The commit a branch points at now."""

    return _commit_sha(
        gh(f"repos/{repo}/commits/{branch}", "--jq", ".sha").strip(),
        f"head of {repo}@{branch}",
    )


def fetch_lock(repo: str, commit_sha: str, *, gh: GhApi = _gh_api) -> bytes | None:
    """``uv.lock`` at one commit, checked against its git blob id.

    ``None`` means the commit's root tree has no ``uv.lock``.
    """

    commit_sha = _commit_sha(commit_sha, "commit SHA")
    commit = json.loads(gh(f"repos/{repo}/git/commits/{commit_sha}"))
    if not isinstance(commit, dict) or commit.get("sha") != commit_sha:
        raise ReceiptPinError(f"GitHub did not return commit {commit_sha}")
    tree = commit.get("tree")
    tree_sha = _commit_sha(
        tree.get("sha") if isinstance(tree, dict) else None, "tree SHA"
    )
    listing = json.loads(gh(f"repos/{repo}/git/trees/{tree_sha}"))
    entries = listing.get("tree") if isinstance(listing, dict) else None
    if not isinstance(entries, list) or listing.get("truncated") is not False:
        raise ReceiptPinError(f"GitHub returned no complete root tree {tree_sha}")
    matches = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("path") == LOCK_PATH
    ]
    if not matches:
        return None
    entry = matches[0]
    if entry.get("type") != "blob" or entry.get("mode") not in {"100644", "100755"}:
        raise ReceiptPinError(f"{repo}@{commit_sha} {LOCK_PATH} is not a regular file")
    blob_sha = _commit_sha(entry.get("sha"), f"{LOCK_PATH} blob SHA")
    blob = json.loads(gh(f"repos/{repo}/git/blobs/{blob_sha}"))
    if not isinstance(blob, dict) or blob.get("encoding") != "base64":
        raise ReceiptPinError(f"GitHub blob {blob_sha} is not base64 encoded")
    try:
        raw = base64.b64decode("".join(str(blob.get("content")).split()), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ReceiptPinError(f"GitHub blob {blob_sha} has invalid base64") from exc
    actual = hashlib.sha1(
        f"blob {len(raw)}\0".encode("ascii") + raw, usedforsecurity=False
    ).hexdigest()
    if actual != blob_sha:
        raise ReceiptPinError(
            f"GitHub blob bytes hash to {actual}, not tree entry {blob_sha}"
        )
    return raw


def chronicle_label(repo: str, commit_sha: str, branch: str | None = None) -> str:
    where = f" ({branch})" if branch else ""
    return f"{repo}@{commit_sha[:12]}{where}"


def main(argv: list[str] | None = None, *, gh: GhApi = _gh_api) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--ledger-repo", default=DEFAULT_LEDGER_REPO)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--ledger-branch", default=DEFAULT_LEDGER_BRANCH)
    target.add_argument("--ledger-sha")
    parser.add_argument(
        "--check-installed",
        action="store_true",
        help="also require this interpreter's receipt to be the locked one",
    )
    parser.add_argument(
        "--installed-only",
        action="store_true",
        help="skip Chronicle; check this interpreter against thesis's lock",
    )
    parser.add_argument("--thesis-lock", type=pathlib.Path, default=THESIS_LOCK)
    args = parser.parse_args(argv)
    thesis_lock = args.thesis_lock.read_bytes()

    if args.installed_only:
        installed = installed_version()
        refusal = installed_refusal(thesis_lock, installed)
        if refusal:
            print(f"RECEIPT PIN REFUSED: {refusal}")
            return 1
        print(f"{sys.executable} has {RECEIPT} {installed}, as thesis's lock names")
        return 0

    try:
        if args.ledger_sha:
            sha = _commit_sha(args.ledger_sha, "--ledger-sha")
            label = chronicle_label(args.ledger_repo, sha)
        else:
            sha = branch_head(args.ledger_repo, args.ledger_branch, gh=gh)
            label = chronicle_label(args.ledger_repo, sha, args.ledger_branch)
        chronicle_lock = fetch_lock(args.ledger_repo, sha, gh=gh)
    except (ReceiptPinError, json.JSONDecodeError) as exc:
        print(f"cannot read Chronicle's lock: {exc}")
        return 2
    kwargs = {"installed": installed_version()} if args.check_installed else {}
    refusal = receipt_pin_refusal(
        chronicle_lock, chronicle_label=label, thesis_lock=thesis_lock, **kwargs
    )
    if refusal:
        print(f"RECEIPT PIN REFUSED: {refusal}")
        return 1
    # A missing lock, or one without receipt, is a refusal above.
    chronicle = locked_pin(chronicle_lock or b"", label=label)
    assert chronicle is not None
    print(
        f"thesis and {label} both lock {RECEIPT} {chronicle.version} "
        f"({len(chronicle.artifacts)} identical artifact hashes)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
