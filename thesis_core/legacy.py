"""Explicit read-only bridge to a caller-trusted legacy verifier checkout.

The trusted checkout is configuration, never a path supplied by imported JSON.
Verified bytes are copied with authenticated hash/size checks; custody alone is
not an independent timestamp and cannot upgrade an imported forecast's class.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from .artifacts import ArtifactStore
from .canonical import canonical_bytes, canonical_sha256


class LegacyImportError(ValueError):
    pass


# Fixed program, not artifact-provided code. Retain the verifier's authenticated
# root, then validate every copied byte against that root in the parent process.
_VERIFY_RUN = r"""
import base64, dataclasses, hashlib, json, pathlib, subprocess, sys
checkout, run = map(pathlib.Path, sys.argv[1:])
sys.path.insert(0, str(checkout / "scripts"))
sys.path.insert(0, str(checkout))
import verify_custody
from canonical_json import canonical_sha256
root_raw = (run / "custody_root.json").read_bytes()
manifest_raw = (run / "manifest.json").read_bytes()
verifier_raw = (checkout / "scripts/verify_custody.py").read_bytes()
result = verify_custody.verify_run(run)
if result.custody_root_sha256 != canonical_sha256(json.loads(root_raw)):
    raise ValueError("verified root changed during verification")
if (root_raw != (run / "custody_root.json").read_bytes()
    or manifest_raw != (run / "manifest.json").read_bytes()):
    raise ValueError("control file changed during verification")
if verifier_raw != (checkout / "scripts/verify_custody.py").read_bytes():
    raise ValueError("verifier changed during verification")
code = {}
for module in tuple(sys.modules.values()):
    path = getattr(module, "__file__", None)
    if not path:
        continue
    path = pathlib.Path(path).resolve()
    if path.is_relative_to(checkout) and path.suffix == ".py":
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        code[str(path.relative_to(checkout))] = digest
revision = subprocess.run(
    ["git", "-C", str(checkout), "rev-parse", "HEAD"],
    check=True, capture_output=True, text=True).stdout.strip()
print(json.dumps({
    "verification": dataclasses.asdict(result),
    "root_base64": base64.b64encode(root_raw).decode(),
    "manifest_base64": base64.b64encode(manifest_raw).decode(),
    "verifier_code_base64": base64.b64encode(verifier_raw).decode(),
    "verifier_revision": revision, "loaded_code_hashes": code}))
"""

_VERIFY_REGISTRATION = r"""
import base64, hashlib, json, pathlib, re, subprocess, sys
checkout, path = map(pathlib.Path, sys.argv[1:])
sys.path.insert(0, str(checkout / "scripts"))
sys.path.insert(0, str(checkout))
from register_targets import registration_content_hash
raw = path.read_bytes()
digest = registration_content_hash(json.loads(raw))
if re.fullmatch(r"\d{4}-\d{2}-\d{2}-" + digest + r"\.json", path.name) is None:
    raise ValueError("registration filename does not equal verified content hash")
if raw != path.read_bytes():
    raise ValueError("registration changed during verification")
revision = subprocess.run(
    ["git", "-C", str(checkout), "rev-parse", "HEAD"],
    check=True, capture_output=True, text=True).stdout.strip()
code_hash = hashlib.sha256(
    (checkout / "scripts/register_targets.py").read_bytes()).hexdigest()
print(json.dumps({
    "content_hash": digest, "raw_base64": base64.b64encode(raw).decode(),
    "verifier_revision": revision, "verifier_code_hash": code_hash}))
"""


def _trusted_path(
    checkout: Path | str, path: Path | str, category: str = ""
) -> tuple[Path, Path]:
    checkout = Path(checkout).expanduser().resolve(strict=True)
    supplied = Path(path).expanduser()
    if not supplied.is_absolute():
        supplied = checkout / supplied
    if supplied.is_symlink():
        raise LegacyImportError("legacy import refuses symlink paths")
    path = supplied.resolve(strict=True)
    if not path.is_relative_to(checkout / "records" / category):
        raise LegacyImportError(
            f"legacy path must be inside trusted records/{category}"
        )
    return checkout, path


def _invoke(checkout: Path, path: Path, program: str) -> dict:
    # Python -I ignores PYTHONPATH/user site. No credentials or ambient runtime
    # options are inherited; legacy verification has no network operation.
    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", program, str(checkout), str(path)],
            cwd=checkout,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        if len(result.stdout) > 8_000_000:
            raise LegacyImportError("legacy verifier response exceeds size bound")
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        # Do not reflect raw subprocess output (which may contain source paths
        # or artifact contents) into public descriptors or external logs.
        raise LegacyImportError("trusted legacy verifier refused the import") from exc


def _copy_authenticated(run: Path, entry: dict, artifacts: ArtifactStore) -> str:
    relative = Path(entry["path"])
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {".", ".."} for part in relative.parts)
    ):
        raise LegacyImportError("unsafe authenticated artifact path")
    digest = entry.get("sha256")
    size = entry.get("bytes")
    if (
        not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or type(size) is not int
        or size < 0
    ):
        raise LegacyImportError("invalid authenticated artifact commitment")
    path = run / relative
    if any(
        parent.is_symlink() for parent in [path, *path.parents] if parent != run.parent
    ):
        raise LegacyImportError("symlink in authenticated artifact path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise LegacyImportError("authenticated artifact is not a regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read()
    finally:
        os.close(fd)
    # This check closes the read/verify/copy race even if a mutable checkout was
    # changed after the verifier returned. CAS storage then verifies each read.
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise LegacyImportError("artifact changed after custody verification")
    stored = artifacts.put_bytes(raw)
    if stored != digest or artifacts.read_bytes(stored) != raw:
        raise LegacyImportError("copied artifact differs from authenticated bytes")
    return stored


def import_legacy_run(
    trusted_checkout: Path | str, run_directory: Path | str, artifacts: ArtifactStore
):
    from .contracts import LegacyImport

    checkout, run = _trusted_path(trusted_checkout, run_directory)
    result = _invoke(checkout, run, _VERIFY_RUN)
    root_raw = base64.b64decode(result["root_base64"], validate=True)
    manifest_raw = base64.b64decode(result["manifest_base64"], validate=True)
    verifier_raw = base64.b64decode(result["verifier_code_base64"], validate=True)
    root = json.loads(root_raw)
    manifest = json.loads(manifest_raw)
    if canonical_sha256(root) != result["verification"]["custody_root_sha256"]:
        raise LegacyImportError("authenticated root hash mismatch")
    without_root = {
        key: value for key, value in manifest.items() if key != "custodyRootSha256"
    }
    if (
        canonical_sha256(without_root)
        != root["manifestWithoutCustodyRoot"]["canonicalJsonSha256"]
    ):
        raise LegacyImportError("copied manifest differs from verified root commitment")
    copied = tuple(
        _copy_authenticated(run, entry, artifacts) for entry in root["artifacts"]
    )
    root_hash, manifest_hash, code_hash = (
        artifacts.put_bytes(raw) for raw in (root_raw, manifest_raw, verifier_raw)
    )
    descriptor = {
        "schema_version": 1,
        "trust_class": "legacy_custody_verified",
        "prospective_eligible": False,
        "source_run": str(run.relative_to(checkout)),
        "verification": result["verification"],
        "verifier_revision": result["verifier_revision"],
        "verifier_code_hash": code_hash,
        "loaded_code_hashes": result["loaded_code_hashes"],
        "custody_root_hash": root_hash,
        "manifest_hash": manifest_hash,
        "artifacts": root["artifacts"],
        "claimed_source_provenance": manifest.get("provenance"),
        "custody_semantics": (
            "byte integrity and inventory verified; original timing claims "
            "and proof class preserved"
        ),
    }
    descriptor_hash = artifacts.put_bytes(canonical_bytes(descriptor))
    imported = LegacyImport(
        trust_class="legacy_custody_verified",
        verifier_revision=result["verifier_revision"],
        verifier_code_hash=code_hash,
        custody_root_hash=root_hash,
        manifest_hash=manifest_hash,
        descriptor_hash=descriptor_hash,
        artifact_hashes=copied,
    )
    artifacts.put_bytes(imported.canonical_bytes())
    return imported


def import_legacy_registration(
    trusted_checkout: Path | str,
    registration_path: Path | str,
    artifacts: ArtifactStore,
) -> dict:
    checkout, path = _trusted_path(trusted_checkout, registration_path, "targets")
    result = _invoke(checkout, path, _VERIFY_REGISTRATION)
    raw = base64.b64decode(result.pop("raw_base64"), validate=True)
    # The verifier returns the exact bytes on which it computed the immutable
    # content hash, so no second read of a mutable registration is necessary.
    result.update(
        {
            "artifact_hash": artifacts.put_bytes(raw),
            "bytes": len(raw),
            "trust_class": "legacy_registered_contract",
            "prospective_eligible": False,
        }
    )
    result["descriptor_hash"] = artifacts.put_bytes(canonical_bytes(result))
    return result
