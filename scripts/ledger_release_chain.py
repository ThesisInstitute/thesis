# Vendored byte-for-byte from PolicyEngine/chronicle (then named
# PolicyEngine/ledger) scripts/verify_release_chain.py
# (witnessed-journal). Do not edit here; update from upstream.
#!/usr/bin/env python3
"""Offline verification for the witnessed thesis-ledger release chain.

The verifier treats manifest, signature, and receipt bytes as an append-only
journal. It does not trust manifest provenance or timestamps supplied by the
producer: each manifest is canonical and content-addressed, every state and
append digest is recomputed from the current append-only JSONL, every manifest
has a valid signature from the pinned producer key, and both RFC 3161 receipts
are verified against separate, committed trust anchors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from canonical_json import canonical_bytes

try:
    from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
        load_pem_public_key,
    )
except ImportError:  # Bare pre-sync CI falls back to the OpenSSL 3 CLI below.
    CRYPTOGRAPHY_AVAILABLE = False
else:
    CRYPTOGRAPHY_AVAILABLE = True

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_RELATIVE = pathlib.PurePosixPath("releases/manifests")
LEDGER_RELATIVE = pathlib.PurePosixPath("ledger/official_observations.jsonl")
PREFIX_RELATIVE = pathlib.PurePosixPath("ledger/immutable_prefix.json")
STATE_PATH = LEDGER_RELATIVE.as_posix()
SCHEMA_VERSION = "thesis_ledger_release_v1"
MAX_RELEASE_INDEX = 9_999
DEFAULT_CLOCK_SKEW_SECONDS = 300
MAX_FUTURE_SECONDS = 300
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MANIFEST_RE = re.compile(r"(?P<index>[0-9]{4})-(?P<digest>[0-9a-f]{16})\.json\Z")
RECEIPT_RE = re.compile(
    r"(?P<stem>[0-9]{4}-[0-9a-f]{16})"
    r"\.(?P<tsa>freetsa|digicert)\.tsr\Z"
)
PRODUCER_SIGNATURE_RE = re.compile(
    r"(?P<stem>[0-9]{4}-[0-9a-f]{16})\.producer\.sig\Z"
)
PRODUCER_PUBLIC_KEY_FILENAME = "producer-ed25519.pub"
PRODUCER_SPKI_SHA256 = (
    "4a90eff40455ce0d853d4bab1608efbdae1efaf8c06054ead6e396c5b0c4846e"
)
PRODUCER_SIGNATURE_BYTES = 64
STRICT_UTC_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:"
    r"[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z\Z"
)
TIME_STAMP_RE = re.compile(
    r"(?P<month>[A-Z][a-z]{2})\s+"
    r"(?P<day>[0-9]{1,2})\s+"
    r"(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):"
    r"(?P<second>[0-9]{2})(?P<fraction>\.[0-9]+)?\s+"
    r"(?P<year>[0-9]{4})\s+GMT\Z"
)


@dataclass(frozen=True)
class PinnedSigner:
    """One TSA responder certificate this verifier accepts.

    The certificate hash and the SPKI hash are pinned as a pair. A receipt
    must match both halves of the same entry: a certificate from one entry
    with the key of another is a certificate nobody reviewed.
    """

    label: str
    certificate_sha256: str
    spki_sha256: str


@dataclass(frozen=True)
class AnchorSpec:
    filename: str
    pem_sha256: str
    policy_oid: str
    # Every responder certificate accepted under this root, oldest first.
    # TSAs replace their responder certificate about once a year, and the
    # releases already in the journal stay signed by the old one, so the
    # pin is a reviewed set rather than a single certificate. Membership
    # is the whole rule: `openssl cms -verify -attime <genTime>` has
    # already required the certificate to chain to the pinned root and to
    # be valid at the signed time, so an entry cannot vouch for a receipt
    # from outside its own validity period. No ordering across releases
    # is imposed, because a TSA may serve two responders during a
    # changeover. Adding an entry is a trust decision; see
    # docs/tsa-signer-rotation.md for the check to run first.
    signers: tuple[PinnedSigner, ...]


ANCHORS = {
    "freetsa": AnchorSpec(
        filename="freetsa-root-2016.pem",
        pem_sha256=("2151b61137ffa86bf664691ba67e7da0b19f98c758e3d228d5d8ebf27e044438"),
        policy_oid="1.2.3.4.1",
        signers=(
            PinnedSigner(
                label="www.freetsa.org",
                certificate_sha256=(
                    "32e841a95cc1164101ffde41298ef2fc75c1c4372ef095e88a6bbd47dfb191fc"
                ),
                spki_sha256=(
                    "fa02bd555e3e483d62b4e70be6218692068d2b0b0a7525db58dcbf2901cdb072"
                ),
            ),
        ),
    ),
    "digicert": AnchorSpec(
        filename="digicert-trusted-root-g4.pem",
        pem_sha256=("ce7d6b44f5d510391be98c8d76b18709400a30cd87659bfebe1c6f97ff5181ee"),
        policy_oid="2.16.840.1.114412.7.1",
        signers=(
            # Signed ledger releases 0001-0020 (through 2026-09-03).
            PinnedSigner(
                label="DigiCert timestamp responder in service through 2026-09-03",
                certificate_sha256=(
                    "4aa03fa22cd75c84c55c938f828e676b9caecab33fe36d269aa334f146110a33"
                ),
                spki_sha256=(
                    "7abda95ed7301ac94bded350babc319903d0b4f16c4e7e39346dba5f9e992b72"
                ),
            ),
            # Served by timestamp.digicert.com from 2026-09-09 at the
            # latest: serial 084FDC334F7E454EDBC30F8FF9921835, valid
            # 2026-08-05 to 2037-11-04, EKU critical timeStamping, issued
            # by "DigiCert Trusted G4 TimeStamping RSA4096 SHA256 2025
            # CA1", which chains to the pinned Trusted Root G4. Hashes
            # taken from a receipt requested on 2026-09-19; they equal the
            # certificate hash the resolver refused on ten consecutive
            # daily runs.
            PinnedSigner(
                label="DigiCert SHA256 RSA4096 Timestamp Responder 2026 1",
                certificate_sha256=(
                    "2da09da7f4131f9fe72db6c5e6e9c9656755af043f1ea742cc0d2120e141ebfc"
                ),
                spki_sha256=(
                    "753596b60a629061144cbd312017bbfb77510eac20b7eadc5fafb7cabe142fd5"
                ),
            ),
        ),
    ),
}


class ReleaseChainError(ValueError):
    """The release journal is malformed, inconsistent, or untrusted."""


@dataclass(frozen=True)
class GitEntry:
    mode: str
    object_type: str
    object_id: str
    path: str


@dataclass(frozen=True)
class ReleaseRecord:
    path: pathlib.Path
    raw: bytes
    sha256: str
    manifest: dict[str, Any]
    receipt_paths: dict[str, pathlib.Path]
    receipt_times: dict[str, datetime]
    producer_signature_path: pathlib.Path

    @property
    def release_index(self) -> int:
        return int(self.manifest["releaseIndex"])


@dataclass(frozen=True)
class ChainVerification:
    releases: tuple[ReleaseRecord, ...]

    @property
    def head(self) -> ReleaseRecord | None:
        return self.releases[-1] if self.releases else None


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fail_json_constant(value: str) -> None:
    raise ReleaseChainError(f"manifest contains non-JSON number {value!r}")


def _object_without_duplicates(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseChainError(f"manifest has duplicate key {key!r}")
        result[key] = value
    return result


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ReleaseChainError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ReleaseChainError(
            f"{label} keys are not closed-world: missing={missing}, unknown={unknown}"
        )
    return value


def _strict_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int:
        raise ReleaseChainError(f"{label} must be an integer, not a boolean")
    if value < minimum:
        raise ReleaseChainError(f"{label} must be >= {minimum}")
    return value


def _strict_string(value: Any, label: str, *, nonempty: bool = True) -> str:
    if type(value) is not str or (nonempty and not value):
        suffix = " and non-empty" if nonempty else ""
        raise ReleaseChainError(f"{label} must be a string{suffix}")
    return value


def _sha256(value: Any, label: str) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise ReleaseChainError(
            f"{label} must be exactly 64 lowercase hexadecimal characters"
        )
    return value


def parse_created_at(value: Any, label: str = "createdAtUtc") -> datetime:
    text = _strict_string(value, label)
    if STRICT_UTC_RE.fullmatch(text) is None:
        raise ReleaseChainError(f"{label} must be a strict UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ReleaseChainError(f"{label} is not a real UTC time: {text!r}") from exc
    return parsed.astimezone(timezone.utc)


def validate_manifest_schema(manifest: Any) -> dict[str, Any]:
    """Validate the closed-world ``thesis_ledger_release_v1`` schema."""

    payload = _exact_keys(
        manifest,
        {
            "schemaVersion",
            "releaseIndex",
            "previousManifestSha256",
            "state",
            "append",
            "createdAtUtc",
            "producer",
        },
        "manifest",
    )
    if payload["schemaVersion"] != SCHEMA_VERSION:
        raise ReleaseChainError(
            f"unsupported manifest schema {payload['schemaVersion']!r}"
        )
    index = _strict_int(payload["releaseIndex"], "releaseIndex")
    if index > MAX_RELEASE_INDEX:
        raise ReleaseChainError(
            f"releaseIndex {index} exceeds the four-digit filename limit"
        )

    previous = payload["previousManifestSha256"]
    if index == 0:
        if previous is not None:
            raise ReleaseChainError("genesis previousManifestSha256 must be null")
    else:
        _sha256(previous, "previousManifestSha256")

    state = _exact_keys(
        payload["state"],
        {
            "path",
            "jsonlSha256",
            "lineCount",
            "immutablePrefixSha256",
        },
        "state",
    )
    if state["path"] != STATE_PATH:
        raise ReleaseChainError(f"state.path must be exactly {STATE_PATH!r}")
    _sha256(state["jsonlSha256"], "state.jsonlSha256")
    _strict_int(state["lineCount"], "state.lineCount")
    _sha256(
        state["immutablePrefixSha256"],
        "state.immutablePrefixSha256",
    )

    append = payload["append"]
    if index == 0:
        if append is not None:
            raise ReleaseChainError("genesis append must be null")
    else:
        append_block = _exact_keys(
            append,
            {
                "previousLineCount",
                "appendedRowCount",
                "appendedBytesSha256",
            },
            "append",
        )
        _strict_int(
            append_block["previousLineCount"],
            "append.previousLineCount",
        )
        _strict_int(
            append_block["appendedRowCount"],
            "append.appendedRowCount",
            minimum=1,
        )
        _sha256(
            append_block["appendedBytesSha256"],
            "append.appendedBytesSha256",
        )

    parse_created_at(payload["createdAtUtc"])
    producer = _exact_keys(payload["producer"], {"repo", "branch"}, "producer")
    _strict_string(producer["repo"], "producer.repo")
    _strict_string(producer["branch"], "producer.branch")
    return payload


def load_manifest(path: pathlib.Path) -> tuple[dict[str, Any], bytes, str]:
    if path.is_symlink() or not path.is_file():
        raise ReleaseChainError(f"manifest is not a regular file: {path}")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseChainError(f"manifest is not UTF-8: {path}") from exc
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_fail_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise ReleaseChainError(f"manifest is not valid JSON: {path}: {exc}") from exc
    payload = validate_manifest_schema(parsed)
    expected = canonical_bytes(payload) + b"\n"
    if raw != expected:
        raise ReleaseChainError(
            f"manifest bytes are not canonical JSON plus one newline: {path}"
        )
    return payload, raw, sha256_bytes(raw)


def manifest_filename(index: int, raw: bytes) -> str:
    _strict_int(index, "releaseIndex")
    if index > MAX_RELEASE_INDEX:
        raise ReleaseChainError(
            f"releaseIndex {index} exceeds the four-digit filename limit"
        )
    return f"{index:04d}-{sha256_bytes(raw)[:16]}.json"


def receipt_paths_for_manifest(path: pathlib.Path) -> dict[str, pathlib.Path]:
    stem = path.stem
    return {tsa: path.with_name(f"{stem}.{tsa}.tsr") for tsa in ANCHORS}


def producer_signature_path_for_manifest(path: pathlib.Path) -> pathlib.Path:
    return path.with_name(f"{path.stem}.producer.sig")


def _enumerate_manifest_files(
    root: pathlib.Path,
) -> list[tuple[pathlib.Path, dict[str, pathlib.Path], pathlib.Path]]:
    directory = root / MANIFEST_RELATIVE
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise ReleaseChainError(
            f"release manifest path is not a regular directory: {directory}"
        )

    manifests: dict[str, pathlib.Path] = {}
    receipts: dict[str, dict[str, pathlib.Path]] = {}
    producer_signatures: dict[str, pathlib.Path] = {}
    for entry in directory.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise ReleaseChainError(
                f"release manifest directory contains a non-regular entry: {entry}"
            )
        manifest_match = MANIFEST_RE.fullmatch(entry.name)
        if manifest_match is not None:
            manifests[entry.stem] = entry
            continue
        receipt_match = RECEIPT_RE.fullmatch(entry.name)
        if receipt_match is not None:
            stem = receipt_match.group("stem")
            tsa = receipt_match.group("tsa")
            receipts.setdefault(stem, {})[tsa] = entry
            continue
        signature_match = PRODUCER_SIGNATURE_RE.fullmatch(entry.name)
        if signature_match is not None:
            producer_signatures[signature_match.group("stem")] = entry
            continue
        raise ReleaseChainError(
            f"unknown file in closed release manifest directory: {entry.name}"
        )

    orphan_receipts = sorted(set(receipts) - set(manifests))
    if orphan_receipts:
        raise ReleaseChainError(
            f"orphan release receipts for manifest stems: {orphan_receipts}"
        )
    orphan_signatures = sorted(set(producer_signatures) - set(manifests))
    if orphan_signatures:
        raise ReleaseChainError(
            "orphan producer signatures for manifest stems: "
            f"{orphan_signatures}"
        )
    result: list[
        tuple[pathlib.Path, dict[str, pathlib.Path], pathlib.Path]
    ] = []
    seen_indices: dict[int, str] = {}
    for stem, path in manifests.items():
        match = MANIFEST_RE.fullmatch(path.name)
        assert match is not None
        index = int(match.group("index"))
        if index in seen_indices:
            raise ReleaseChainError(
                f"duplicate release index {index}: {seen_indices[index]}, {path.name}"
            )
        seen_indices[index] = path.name
        actual_receipts = receipts.get(stem, {})
        if set(actual_receipts) != set(ANCHORS):
            raise ReleaseChainError(
                f"manifest {path.name} must have exactly freetsa and digicert "
                f"receipts; found={sorted(actual_receipts)}"
            )
        producer_signature = producer_signatures.get(stem)
        if producer_signature is None:
            raise ReleaseChainError(
                f"manifest {path.name} is missing its producer signature "
                f"{stem}.producer.sig"
            )
        result.append((path, actual_receipts, producer_signature))
    return sorted(
        result,
        key=lambda item: int(MANIFEST_RE.fullmatch(item[0].name).group("index")),
    )


def _openssl_environment(empty_ca_dir: pathlib.Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "LC_ALL": "C",
            "OPENSSL_CONF": "/dev/null",
            "SSL_CERT_DIR": str(empty_ca_dir),
            "SSL_CERT_FILE": "/dev/null",
        }
    )
    return environment


def _command_error(completed: subprocess.CompletedProcess[str]) -> str:
    details = (completed.stderr or completed.stdout).strip()
    return details[-1000:] if details else "no OpenSSL diagnostic"


def _parse_receipt_text(output: str, receipt: pathlib.Path) -> tuple[datetime, str]:
    status_lines = [
        line.strip() for line in output.splitlines() if line.startswith("Status:")
    ]
    if status_lines != ["Status: Granted."]:
        raise ReleaseChainError(
            f"RFC 3161 receipt is not granted for {receipt}: {status_lines}"
        )
    hash_lines = [
        line.split(":", 1)[1].strip()
        for line in output.splitlines()
        if line.startswith("Hash Algorithm:")
    ]
    if hash_lines != ["sha256"]:
        raise ReleaseChainError(
            f"RFC 3161 receipt does not use SHA-256 for {receipt}: {hash_lines}"
        )
    policy_lines = [
        line.split(":", 1)[1].strip()
        for line in output.splitlines()
        if line.startswith("Policy OID:")
    ]
    if len(policy_lines) != 1:
        raise ReleaseChainError(
            f"RFC 3161 receipt has no unique policy OID for {receipt}"
        )
    time_lines = [
        line.split(":", 1)[1].strip()
        for line in output.splitlines()
        if line.startswith("Time stamp:")
    ]
    if len(time_lines) != 1:
        raise ReleaseChainError(f"RFC 3161 receipt has no unique genTime for {receipt}")
    match = TIME_STAMP_RE.fullmatch(time_lines[0])
    if match is None:
        raise ReleaseChainError(
            f"unsupported RFC 3161 genTime for {receipt}: {time_lines[0]!r}"
        )
    timestamp = (
        f"{match.group('month')} {match.group('day')} "
        f"{match.group('hour')}:{match.group('minute')}:"
        f"{match.group('second')} {match.group('year')} GMT"
    )
    try:
        parsed = datetime.strptime(timestamp, "%b %d %H:%M:%S %Y GMT").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ReleaseChainError(
            f"invalid RFC 3161 genTime for {receipt}: {timestamp!r}"
        ) from exc
    fraction = match.group("fraction")
    if fraction:
        parsed = parsed.replace(microsecond=int((fraction[1:] + "000000")[:6]))
    return parsed, policy_lines[0]


def _openssl_binary(
    arguments: list[str],
    *,
    environment: dict[str, str],
    label: str,
) -> bytes:
    try:
        completed = subprocess.run(
            ["openssl", *arguments],
            check=False,
            capture_output=True,
            env=environment,
        )
    except FileNotFoundError as exc:
        raise ReleaseChainError(
            "openssl is required for RFC 3161 verification"
        ) from exc
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout).decode(
            "utf-8", errors="replace"
        )
        raise ReleaseChainError(
            f"OpenSSL {label} failed (exit {completed.returncode}): "
            f"{diagnostic.strip()[-1000:]}"
        )
    return completed.stdout


def _producer_openssl_binary(
    arguments: list[str],
    *,
    environment: dict[str, str],
    label: str,
) -> bytes:
    try:
        completed = subprocess.run(
            ["openssl", *arguments],
            check=False,
            capture_output=True,
            env=environment,
        )
    except FileNotFoundError as exc:
        raise ReleaseChainError(
            "producer signature verification requires cryptography or OpenSSL 3"
        ) from exc
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout).decode(
            "utf-8", errors="replace"
        )
        raise ReleaseChainError(
            f"OpenSSL producer {label} failed (exit {completed.returncode}): "
            f"{diagnostic.strip()[-1000:]}"
        )
    return completed.stdout


def _verify_producer_signature_with_openssl(
    manifest: bytes,
    signature: bytes,
    public_key_pem: bytes,
    *,
    enforce_production_pin: bool,
    label: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="thesis-release-producer-") as name:
        temporary = pathlib.Path(name)
        empty_ca_dir = temporary / "empty-ca"
        empty_ca_dir.mkdir()
        environment = _openssl_environment(empty_ca_dir)
        manifest_path = temporary / "manifest.json"
        signature_path = temporary / "producer.sig"
        public_key_path = temporary / PRODUCER_PUBLIC_KEY_FILENAME
        manifest_path.write_bytes(manifest)
        signature_path.write_bytes(signature)
        public_key_path.write_bytes(public_key_pem)

        spki_der = _producer_openssl_binary(
            [
                "pkey",
                "-pubin",
                "-in",
                str(public_key_path),
                "-outform",
                "DER",
            ],
            environment=environment,
            label=f"public-key decoding for {label}",
        )
        if enforce_production_pin:
            spki_sha256 = sha256_bytes(spki_der)
            if spki_sha256 != PRODUCER_SPKI_SHA256:
                raise ReleaseChainError(
                    "producer public-key SPKI is not code-pinned: "
                    f"{spki_sha256}"
                )

        try:
            _producer_openssl_binary(
                [
                    "pkeyutl",
                    "-verify",
                    "-pubin",
                    "-inkey",
                    str(public_key_path),
                    "-rawin",
                    "-in",
                    str(manifest_path),
                    "-sigfile",
                    str(signature_path),
                ],
                environment=environment,
                label=f"Ed25519 signature verification for {label}",
            )
        except ReleaseChainError as exc:
            raise ReleaseChainError(
                f"producer Ed25519 signature verification failed for {label}"
            ) from exc


def verify_producer_signature_bytes(
    manifest: bytes,
    signature: bytes,
    *,
    anchor_dir: pathlib.Path,
    enforce_production_pin: bool,
    label: str,
) -> None:
    """Verify one raw Ed25519 signature over exact manifest bytes."""

    if type(manifest) is not bytes:
        raise ReleaseChainError("producer-signed manifest payload must be bytes")
    if type(signature) is not bytes or len(signature) != PRODUCER_SIGNATURE_BYTES:
        actual = len(signature) if isinstance(signature, bytes) else "non-bytes"
        raise ReleaseChainError(
            f"producer signature for {label} must be exactly "
            f"{PRODUCER_SIGNATURE_BYTES} raw bytes; found={actual}"
        )
    public_key_path = anchor_dir / PRODUCER_PUBLIC_KEY_FILENAME
    if public_key_path.is_symlink() or not public_key_path.is_file():
        raise ReleaseChainError(
            f"missing or non-regular producer public key: {public_key_path}"
        )
    public_key_pem = public_key_path.read_bytes()

    if not CRYPTOGRAPHY_AVAILABLE:
        _verify_producer_signature_with_openssl(
            manifest,
            signature,
            public_key_pem,
            enforce_production_pin=enforce_production_pin,
            label=label,
        )
        return

    try:
        public_key = load_pem_public_key(public_key_pem)
    except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
        raise ReleaseChainError(
            f"cannot decode producer Ed25519 public key: {public_key_path}"
        ) from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise ReleaseChainError(
            f"producer public key is not Ed25519: {public_key_path}"
        )
    spki_der = public_key.public_bytes(
        Encoding.DER,
        PublicFormat.SubjectPublicKeyInfo,
    )
    if enforce_production_pin:
        spki_sha256 = sha256_bytes(spki_der)
        if spki_sha256 != PRODUCER_SPKI_SHA256:
            raise ReleaseChainError(
                f"producer public-key SPKI is not code-pinned: {spki_sha256}"
            )
    try:
        public_key.verify(signature, manifest)
    except InvalidSignature as exc:
        raise ReleaseChainError(
            f"producer Ed25519 signature verification failed for {label}"
        ) from exc


def verify_producer_signature(
    manifest: bytes,
    signature_path: pathlib.Path,
    *,
    anchor_dir: pathlib.Path,
    enforce_production_pin: bool,
) -> None:
    if signature_path.is_symlink() or not signature_path.is_file():
        raise ReleaseChainError(
            f"missing or non-regular producer signature: {signature_path}"
        )
    verify_producer_signature_bytes(
        manifest,
        signature_path.read_bytes(),
        anchor_dir=anchor_dir,
        enforce_production_pin=enforce_production_pin,
        label=signature_path.name,
    )


_LOG_SAFE_RE = re.compile(r"[^A-Za-z0-9 =,.()/_+@'\\-]")


def _log_safe(text: str, *, limit: int = 200) -> str:
    """Certificate text made safe to print into a GitHub Actions log.

    A certificate's subject is chosen by whoever obtained it, and this
    verifier prints it precisely when it does NOT trust the certificate.
    The Actions runner treats `##[command]` anywhere in a line, and
    `::command::` at the start of one, as instructions. Everything outside
    a small allowlist becomes "?", which removes "#", "[", "]", ":", "%"
    and line breaks; an ordinary distinguished name survives intact apart
    from the "subject=" colon-free prefix it already has.
    """
    return _LOG_SAFE_RE.sub("?", text.strip())[:limit]


def _verify_production_signer(
    receipt: pathlib.Path,
    anchor: pathlib.Path,
    spec: AnchorSpec,
    gen_time: datetime,
    temporary: pathlib.Path,
    environment: dict[str, str],
) -> None:
    token = temporary / "token.der"
    signer = temporary / "signer.pem"
    content = temporary / "tst-info.der"
    _openssl_binary(
        [
            "ts",
            "-reply",
            "-config",
            "/dev/null",
            "-in",
            str(receipt),
            "-token_out",
            "-out",
            str(token),
        ],
        environment=environment,
        label=f"token extraction for {receipt.name}",
    )
    _openssl_binary(
        [
            "cms",
            "-verify",
            "-inform",
            "DER",
            "-in",
            str(token),
            "-CAfile",
            str(anchor),
            "-no-CApath",
            "-no-CAstore",
            "-purpose",
            "timestampsign",
            "-attime",
            str(int(gen_time.timestamp())),
            "-signer",
            str(signer),
            "-out",
            str(content),
        ],
        environment=environment,
        label=f"signer extraction for {receipt.name}",
    )
    certificate_der = _openssl_binary(
        ["x509", "-in", str(signer), "-outform", "DER"],
        environment=environment,
        label=f"signer certificate decoding for {receipt.name}",
    )
    public_key_pem = _openssl_binary(
        ["x509", "-in", str(signer), "-pubkey", "-noout"],
        environment=environment,
        label=f"signer public-key extraction for {receipt.name}",
    )
    public_key = temporary / "signer-public-key.pem"
    public_key.write_bytes(public_key_pem)
    public_key_der = _openssl_binary(
        ["pkey", "-pubin", "-in", str(public_key), "-outform", "DER"],
        environment=environment,
        label=f"signer SPKI decoding for {receipt.name}",
    )
    certificate_sha256 = sha256_bytes(certificate_der)
    spki_sha256 = sha256_bytes(public_key_der)
    if any(
        signer.certificate_sha256 == certificate_sha256
        and signer.spki_sha256 == spki_sha256
        for signer in spec.signers
    ):
        return
    # Name what was seen. The bare hash in this message is what let the
    # 2026-09 DigiCert rotation be matched against a fresh receipt; the
    # subject says at a glance whether it is a rotation or something else.
    # It is a convenience only: if it cannot be read, the refusal below
    # must still be the error that surfaces, not an OpenSSL failure.
    try:
        subject = _log_safe(
            _openssl_binary(
                [
                    "x509",
                    "-in",
                    str(signer),
                    "-noout",
                    "-subject",
                    "-nameopt",
                    "RFC2253",
                ],
                environment=environment,
                label=f"signer subject for {receipt.name}",
            ).decode("utf-8", "replace")
        )
    except (ReleaseChainError, OSError):
        subject = "subject unavailable"
    if any(s.certificate_sha256 == certificate_sha256 for s in spec.signers):
        raise ReleaseChainError(
            f"RFC 3161 signer SPKI is not pinned for {receipt.name}: {spki_sha256}"
            f" ({subject})"
        )
    raise ReleaseChainError(
        f"RFC 3161 signer certificate is not pinned for {receipt.name}: "
        f"{certificate_sha256} (SPKI {spki_sha256}; {subject}). If the TSA "
        "replaced its responder certificate, follow docs/tsa-signer-rotation.md"
    )


def verify_receipt(
    manifest_digest: str,
    receipt: pathlib.Path,
    tsa: str,
    *,
    anchor_dir: pathlib.Path,
    enforce_production_pins: bool,
    now: datetime | None = None,
) -> datetime:
    """Cryptographically verify one receipt and return its signed genTime."""

    if tsa not in ANCHORS:
        raise ReleaseChainError(f"unknown TSA receipt kind {tsa!r}")
    _sha256(manifest_digest, "manifest digest")
    if receipt.is_symlink() or not receipt.is_file():
        raise ReleaseChainError(f"missing or non-regular RFC 3161 receipt: {receipt}")
    spec = ANCHORS[tsa]
    anchor = anchor_dir / spec.filename
    if anchor.is_symlink() or not anchor.is_file():
        raise ReleaseChainError(f"missing or non-regular TSA anchor: {anchor}")
    if enforce_production_pins:
        anchor_digest = sha256_bytes(anchor.read_bytes())
        if anchor_digest != spec.pem_sha256:
            raise ReleaseChainError(
                f"production TSA anchor bytes are not code-pinned for {tsa}: "
                f"{anchor_digest}"
            )

    with tempfile.TemporaryDirectory(prefix="thesis-release-tsa-") as name:
        temporary = pathlib.Path(name)
        empty_ca_dir = temporary / "empty-ca"
        empty_ca_dir.mkdir()
        environment = _openssl_environment(empty_ca_dir)
        try:
            text_result = subprocess.run(
                [
                    "openssl",
                    "ts",
                    "-reply",
                    "-config",
                    "/dev/null",
                    "-in",
                    str(receipt),
                    "-text",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
        except FileNotFoundError as exc:
            raise ReleaseChainError(
                "openssl is required for RFC 3161 verification"
            ) from exc
        if text_result.returncode != 0:
            raise ReleaseChainError(
                f"cannot inspect RFC 3161 receipt {receipt} "
                f"(exit {text_result.returncode}): {_command_error(text_result)}"
            )
        gen_time, policy_oid = _parse_receipt_text(text_result.stdout, receipt)
        if enforce_production_pins and policy_oid != spec.policy_oid:
            raise ReleaseChainError(
                f"RFC 3161 policy is not pinned for {tsa}: {policy_oid!r}"
            )
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if gen_time > current + timedelta(seconds=MAX_FUTURE_SECONDS):
            raise ReleaseChainError(
                f"RFC 3161 genTime {gen_time.isoformat()} for {receipt.name} "
                f"postdates verifier time {current.isoformat()}"
            )

        verify_result = subprocess.run(
            [
                "openssl",
                "ts",
                "-verify",
                "-config",
                "/dev/null",
                "-digest",
                manifest_digest,
                "-in",
                str(receipt),
                "-CAfile",
                str(anchor),
                "-CApath",
                str(empty_ca_dir),
                "-attime",
                str(int(gen_time.timestamp())),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        if verify_result.returncode != 0:
            raise ReleaseChainError(
                f"RFC 3161 verification failed for {receipt.name} "
                f"(exit {verify_result.returncode}): "
                f"{_command_error(verify_result)}"
            )
        if enforce_production_pins:
            _verify_production_signer(
                receipt,
                anchor,
                spec,
                gen_time,
                temporary,
                environment,
            )
    return gen_time


def verify_release_receipts(
    manifest: dict[str, Any],
    manifest_digest: str,
    receipt_paths: dict[str, pathlib.Path],
    *,
    anchor_dir: pathlib.Path,
    enforce_production_pins: bool,
    clock_skew_seconds: int,
    previous_times: dict[str, datetime] | None = None,
    now: datetime | None = None,
) -> dict[str, datetime]:
    """Verify both receipts and their chronology for one manifest."""

    if set(receipt_paths) != set(ANCHORS):
        raise ReleaseChainError(
            "release must have exactly freetsa and digicert receipt paths"
        )
    receipt_times = {
        tsa: verify_receipt(
            manifest_digest,
            receipt_path,
            tsa,
            anchor_dir=anchor_dir,
            enforce_production_pins=enforce_production_pins,
            now=now,
        )
        for tsa, receipt_path in receipt_paths.items()
    }
    created_at = parse_created_at(manifest["createdAtUtc"])
    earliest_allowed = created_at - timedelta(seconds=clock_skew_seconds)
    release_index = manifest["releaseIndex"]
    for tsa, gen_time in receipt_times.items():
        if gen_time < earliest_allowed:
            raise ReleaseChainError(
                f"release {release_index} {tsa} genTime "
                f"{gen_time.isoformat()} impossibly precedes createdAtUtc "
                f"{created_at.isoformat()}"
            )
    if previous_times is not None:
        lower_bound = max(previous_times.values()) - timedelta(
            seconds=clock_skew_seconds
        )
        current_earliest = min(receipt_times.values())
        if current_earliest < lower_bound:
            raise ReleaseChainError(
                f"release {release_index} receipt chronology regresses: "
                f"earliest current genTime {current_earliest.isoformat()} "
                f"precedes latest prior genTime "
                f"{max(previous_times.values()).isoformat()} beyond "
                f"{clock_skew_seconds}s skew"
            )
    return receipt_times


def jsonl_line_offsets(payload: bytes, label: str) -> list[int]:
    """Return exact byte offsets after each non-empty LF-terminated row."""

    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseChainError(f"{label} is not UTF-8") from exc
    if not payload.endswith(b"\n"):
        raise ReleaseChainError(
            f"{label} must end with exactly one LF after its final JSONL row"
        )
    rows = payload.split(b"\n")
    if rows[-1] != b"":
        raise AssertionError("split invariant")
    rows = rows[:-1]
    offsets = [0]
    position = 0
    for number, row in enumerate(rows, start=1):
        if not row.strip():
            raise ReleaseChainError(f"{label} row {number} is blank")
        if row.endswith(b"\r"):
            raise ReleaseChainError(f"{label} row {number} uses CRLF, not exact LF")
        position += len(row) + 1
        offsets.append(position)
    return offsets


def _regular_file_bytes(root: pathlib.Path, relative: pathlib.PurePosixPath) -> bytes:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise ReleaseChainError(
            f"required state file is missing or non-regular: {path}"
        )
    return path.read_bytes()


def _verify_state_history(
    records: list[ReleaseRecord],
    root: pathlib.Path,
    *,
    require_head_current: bool,
) -> None:
    ledger = _regular_file_bytes(root, LEDGER_RELATIVE)
    prefix = _regular_file_bytes(root, PREFIX_RELATIVE)
    offsets = jsonl_line_offsets(ledger, STATE_PATH)
    total_lines = len(offsets) - 1
    prefix_digest = sha256_bytes(prefix)

    previous_line_count: int | None = None
    for record in records:
        state = record.manifest["state"]
        line_count = int(state["lineCount"])
        if line_count > total_lines:
            raise ReleaseChainError(
                f"release {record.release_index} lineCount {line_count} exceeds "
                f"working-tree line count {total_lines}"
            )
        historical_bytes = ledger[: offsets[line_count]]
        historical_digest = sha256_bytes(historical_bytes)
        if historical_digest != state["jsonlSha256"]:
            raise ReleaseChainError(
                f"release {record.release_index} state.jsonlSha256 does not "
                "match the exact historical JSONL prefix"
            )
        if state["immutablePrefixSha256"] != prefix_digest:
            raise ReleaseChainError(
                f"release {record.release_index} immutablePrefixSha256 does "
                "not match ledger/immutable_prefix.json"
            )

        if previous_line_count is not None:
            append = record.manifest["append"]
            assert isinstance(append, dict)
            if line_count <= previous_line_count:
                raise ReleaseChainError(
                    f"release {record.release_index} lineCount must strictly increase"
                )
            if append["previousLineCount"] != previous_line_count:
                raise ReleaseChainError(
                    f"release {record.release_index} append.previousLineCount "
                    "does not match the previous manifest"
                )
            row_delta = line_count - previous_line_count
            if append["appendedRowCount"] != row_delta:
                raise ReleaseChainError(
                    f"release {record.release_index} appendedRowCount "
                    f"{append['appendedRowCount']} does not match line delta "
                    f"{row_delta}"
                )
            suffix = ledger[offsets[previous_line_count] : offsets[line_count]]
            suffix_digest = sha256_bytes(suffix)
            if append["appendedBytesSha256"] != suffix_digest:
                raise ReleaseChainError(
                    f"release {record.release_index} appendedBytesSha256 does "
                    "not match the exact byte suffix"
                )
        previous_line_count = line_count

    if require_head_current:
        head = records[-1]
        if head.manifest["state"]["lineCount"] != total_lines:
            raise ReleaseChainError(
                f"HEAD release lineCount {head.manifest['state']['lineCount']} "
                f"does not match working-tree line count {total_lines}"
            )
        if head.manifest["state"]["jsonlSha256"] != sha256_bytes(ledger):
            raise ReleaseChainError(
                "HEAD release state.jsonlSha256 does not match working-tree bytes"
            )


def verify_release_chain(
    root: pathlib.Path = ROOT,
    *,
    anchor_dir: pathlib.Path | None = None,
    require_chain: bool = True,
    verify_state: bool = True,
    allow_pending_append: bool = False,
    enforce_production_pins: bool | None = None,
    clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS,
    now: datetime | None = None,
) -> ChainVerification:
    """Verify all manifests, signatures, receipts, links, and state bytes."""

    root = root.resolve()
    default_anchor_dir = root / "releases" / "anchors"
    selected_anchors = (anchor_dir or default_anchor_dir).resolve()
    if enforce_production_pins is None:
        enforce_production_pins = selected_anchors == default_anchor_dir
    if type(clock_skew_seconds) is not int or clock_skew_seconds < 0:
        raise ReleaseChainError("clock_skew_seconds must be a non-negative integer")

    enumerated = _enumerate_manifest_files(root)
    if not enumerated:
        if require_chain:
            raise ReleaseChainError("release chain is absent; genesis is required")
        return ChainVerification(())

    records: list[ReleaseRecord] = []
    previous_hash: str | None = None
    previous_times: dict[str, datetime] | None = None
    verification_now = now or datetime.now(timezone.utc)
    for expected_index, (path, receipt_paths, producer_signature_path) in enumerate(
        enumerated
    ):
        manifest, raw, digest = load_manifest(path)
        filename_match = MANIFEST_RE.fullmatch(path.name)
        assert filename_match is not None
        filename_index = int(filename_match.group("index"))
        if filename_index != expected_index:
            raise ReleaseChainError(
                f"release indices are not contiguous from 0: expected "
                f"{expected_index:04d}, found {filename_index:04d}"
            )
        if manifest["releaseIndex"] != expected_index:
            raise ReleaseChainError(
                f"manifest releaseIndex {manifest['releaseIndex']} does not "
                f"match filename index {expected_index}"
            )
        if filename_match.group("digest") != digest[:16]:
            raise ReleaseChainError(
                f"manifest filename hash does not match exact file bytes: {path.name}"
            )
        if manifest["previousManifestSha256"] != previous_hash:
            raise ReleaseChainError(
                f"release {expected_index} previousManifestSha256 does not "
                "match the previous manifest file bytes"
            )
        verify_producer_signature(
            raw,
            producer_signature_path,
            anchor_dir=selected_anchors,
            enforce_production_pin=enforce_production_pins,
        )
        if records:
            previous_line_count = records[-1].manifest["state"]["lineCount"]
            line_count = manifest["state"]["lineCount"]
            append = manifest["append"]
            assert isinstance(append, dict)
            if line_count <= previous_line_count:
                raise ReleaseChainError(
                    f"release {expected_index} lineCount must strictly increase"
                )
            if append["previousLineCount"] != previous_line_count:
                raise ReleaseChainError(
                    f"release {expected_index} append.previousLineCount does "
                    "not match the previous manifest"
                )
            row_delta = line_count - previous_line_count
            if append["appendedRowCount"] != row_delta:
                raise ReleaseChainError(
                    f"release {expected_index} appendedRowCount "
                    f"{append['appendedRowCount']} does not match line delta "
                    f"{row_delta}"
                )

        receipt_times = verify_release_receipts(
            manifest,
            digest,
            receipt_paths,
            anchor_dir=selected_anchors,
            enforce_production_pins=enforce_production_pins,
            clock_skew_seconds=clock_skew_seconds,
            previous_times=previous_times,
            now=verification_now,
        )

        records.append(
            ReleaseRecord(
                path=path,
                raw=raw,
                sha256=digest,
                manifest=manifest,
                receipt_paths=receipt_paths,
                receipt_times=receipt_times,
                producer_signature_path=producer_signature_path,
            )
        )
        previous_hash = digest
        previous_times = receipt_times

    if type(allow_pending_append) is not bool:
        raise ReleaseChainError("allow_pending_append must be a boolean")
    if allow_pending_append and not verify_state:
        raise ReleaseChainError(
            "allow_pending_append requires historical state verification"
        )
    if verify_state:
        _verify_state_history(
            records,
            root,
            require_head_current=not allow_pending_append,
        )
    return ChainVerification(tuple(records))


def _git_run(
    root: pathlib.Path,
    arguments: list[str],
    *,
    text: bool = False,
) -> subprocess.CompletedProcess[Any]:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=False,
            capture_output=True,
            text=text,
        )
    except FileNotFoundError as exc:
        raise ReleaseChainError("git is required for --base-ref verification") from exc


def resolve_base_commit(root: pathlib.Path, base_ref: str) -> str:
    completed = _git_run(
        root,
        ["rev-parse", "--verify", "--end-of-options", f"{base_ref}^{{commit}}"],
        text=True,
    )
    if completed.returncode != 0:
        raise ReleaseChainError(
            f"cannot resolve base ref {base_ref!r} to a commit: "
            f"{completed.stderr.strip()}"
        )
    commit = completed.stdout.strip()
    ancestor = _git_run(root, ["merge-base", "--is-ancestor", commit, "HEAD"])
    if ancestor.returncode != 0:
        raise ReleaseChainError(f"base commit {commit} is not an ancestor of HEAD")
    return commit


def git_tree_entries(
    root: pathlib.Path, commit: str, pathspec: str
) -> dict[str, GitEntry]:
    completed = _git_run(
        root,
        ["ls-tree", "-r", "-z", "--full-tree", commit, "--", pathspec],
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseChainError(
            f"cannot enumerate {pathspec} at base {commit}: {diagnostic}"
        )
    entries: dict[str, GitEntry] = {}
    for record in completed.stdout.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ReleaseChainError(
                f"cannot parse git tree entry under {pathspec}"
            ) from exc
        if path in entries:
            raise ReleaseChainError(f"duplicate git tree entry for {path}")
        entries[path] = GitEntry(mode, object_type, object_id, path)
    return entries


def git_blob_bytes(root: pathlib.Path, entry: GitEntry) -> bytes:
    if entry.object_type != "blob":
        raise ReleaseChainError(
            f"base release entry is not a blob: {entry.path} ({entry.object_type})"
        )
    completed = _git_run(root, ["cat-file", "blob", entry.object_id])
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseChainError(f"cannot read base blob for {entry.path}: {diagnostic}")
    return completed.stdout


def git_file_entry(root: pathlib.Path, commit: str, path: str) -> GitEntry:
    entries = git_tree_entries(root, commit, path)
    entry = entries.get(path)
    if entry is None:
        raise ReleaseChainError(f"required file {path} is absent at base {commit}")
    return entry


def _working_release_files(root: pathlib.Path) -> dict[str, pathlib.Path]:
    release_root = root / "releases"
    if not release_root.exists():
        return {}
    if release_root.is_symlink() or not release_root.is_dir():
        raise ReleaseChainError("releases must be a real directory, not a symlink")
    files: dict[str, pathlib.Path] = {}
    for path in release_root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ReleaseChainError(f"release path is a symlink: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ReleaseChainError(f"release path is not regular: {relative}")
        files[relative] = path
    return files


def verify_release_history_immutable(
    root: pathlib.Path, base_ref: str
) -> tuple[str, set[str], dict[str, GitEntry]]:
    """Compare every base ``releases/`` file byte and mode to the candidate."""

    root = root.resolve()
    commit = resolve_base_commit(root, base_ref)
    base_entries = git_tree_entries(root, commit, "releases")
    current_files = _working_release_files(root)
    for relative, entry in base_entries.items():
        if entry.mode not in {"100644", "100755"}:
            raise ReleaseChainError(
                f"base release entry has non-regular git mode {entry.mode}: {relative}"
            )
        current = current_files.get(relative)
        if current is None:
            raise ReleaseChainError(
                f"existing release file was deleted relative to {commit}: {relative}"
            )
        candidate_mode = "100755" if current.stat().st_mode & 0o111 else "100644"
        if candidate_mode != entry.mode:
            raise ReleaseChainError(
                f"existing release file mode changed relative to {commit}: "
                f"{relative} ({entry.mode} -> {candidate_mode})"
            )
        if current.read_bytes() != git_blob_bytes(root, entry):
            raise ReleaseChainError(
                f"existing release file bytes changed relative to {commit}: {relative}"
            )
    return commit, set(current_files) - set(base_entries), base_entries


def materialize_base_tree(
    root: pathlib.Path,
    commit: str,
    destination: pathlib.Path,
    release_entries: dict[str, GitEntry],
) -> None:
    entries = dict(release_entries)
    for relative in (LEDGER_RELATIVE.as_posix(), PREFIX_RELATIVE.as_posix()):
        entries[relative] = git_file_entry(root, commit, relative)
    for relative, entry in entries.items():
        if entry.mode not in {"100644", "100755"}:
            raise ReleaseChainError(
                f"base tree entry has non-regular mode {entry.mode}: {relative}"
            )
        output = destination / pathlib.PurePosixPath(relative)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(git_blob_bytes(root, entry))


def verify_base_release_chain(
    root: pathlib.Path,
    commit: str,
    release_entries: dict[str, GitEntry],
    *,
    anchor_dir: pathlib.Path | None = None,
    enforce_production_pins: bool = True,
    clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS,
) -> ChainVerification:
    with tempfile.TemporaryDirectory(prefix="thesis-release-base-") as name:
        base_root = pathlib.Path(name)
        materialize_base_tree(root, commit, base_root, release_entries)
        base_anchor_dir = anchor_dir or (base_root / "releases" / "anchors")
        return verify_release_chain(
            base_root,
            anchor_dir=base_anchor_dir,
            require_chain=True,
            verify_state=True,
            enforce_production_pins=enforce_production_pins,
            clock_skew_seconds=clock_skew_seconds,
        )


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="verify the offline thesis-ledger release journal"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="require a genesis-to-HEAD chain and exact working-tree state",
    )
    parser.add_argument(
        "--base-ref",
        help="also reject any changed/deleted existing releases file vs this ref",
    )
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=ROOT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--anchor-dir",
        type=pathlib.Path,
        help="override releases/anchors (intended for offline test fixtures)",
    )
    parser.add_argument(
        "--clock-skew-seconds",
        type=int,
        default=DEFAULT_CLOCK_SKEW_SECONDS,
    )
    args = parser.parse_args()

    root = args.root.resolve()
    anchor_dir = args.anchor_dir.resolve() if args.anchor_dir else None
    enforce_pins = anchor_dir is None
    try:
        if args.base_ref:
            verify_release_history_immutable(root, args.base_ref)
        verification = verify_release_chain(
            root,
            anchor_dir=anchor_dir,
            require_chain=args.full or bool(args.base_ref),
            verify_state=True,
            enforce_production_pins=enforce_pins,
            clock_skew_seconds=args.clock_skew_seconds,
        )
    except (OSError, ReleaseChainError) as exc:
        print(f"release chain verification failed: {exc}", file=sys.stderr)
        return 1
    if not verification.releases:
        print("release chain absent (legacy pre-genesis state)")
        return 0
    head = verification.releases[-1]
    receipt_summary = ", ".join(
        f"{tsa}={_format_time(value)}"
        for tsa, value in sorted(head.receipt_times.items())
    )
    print(
        f"release chain OK: {len(verification.releases)} releases, "
        f"HEAD={head.path.name}, {receipt_summary}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
