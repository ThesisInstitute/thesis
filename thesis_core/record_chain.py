#!/usr/bin/env python3
"""Fail-closed verification for the forecast record chain and RFC 3161 proofs.

This is the shared implementation.  ``scripts/verify_record_chain.py`` is a
compatibility shim that aliases this module under its historic name, so the
legacy CLI, the publisher scripts and the existing tests keep working against
one module object.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from thesis_core import producer_signing_pins as producer_pins
from thesis_core.canonical import canonical_bytes, canonical_sha256

SNAPSHOT_RE = re.compile(r"digest-[A-Za-z0-9][A-Za-z0-9._-]*\.json$")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
TRUST_BUNDLE_RE = re.compile(r"records/trust/tsa-anchors-v[1-9][0-9]*\.json")
UTC = timezone.utc
SHA256_OID = "2.16.840.1.101.3.4.2.1"
CODE_PINNED_TRUST_BUNDLES: dict[str, dict[str, Any]] = {
    "records/trust/tsa-anchors-v1.json": {
        "bundleId": "tsa-anchors-v1",
        "path": "records/trust/tsa-anchors-v1.json",
        "sha256": "737bc9a149726f375edaebcd39b34116d90a5d29e9a043bcb0437998928e5791",
        "size": 1049,
        "canonicalJsonSha256": (
            "9930588eb27ba631446416cf0d2bdac80785e73cf1d32e1d2ed70b0bb49f3d39"
        ),
    },
    "records/trust/tsa-anchors-v2.json": {
        "bundleId": "tsa-anchors-v2",
        "path": "records/trust/tsa-anchors-v2.json",
        "sha256": "b8ece84adcc354f413f10f1b3999ac99679196b9391d76a9967369047b7d7716",
        "size": 1916,
        "canonicalJsonSha256": (
            "036737fdd779f5add77b79262d9967e4bac450ff3ab7132eb929dbf893a4c396"
        ),
    },
}
CODE_PINNED_TSA_IDENTITIES = {
    "tsa-anchors-v1": {
        "freetsa-root-2016": {
            "rootSpkiSha256": (
                "52c54ba340885605314daa1857c8763b94087d05c636092938d4e2d1818e99b5"
            ),
            "signerSpkiSha256": {
                "fa02bd555e3e483d62b4e70be6218692068d2b0b0a7525db58dcbf2901cdb072"
            },
        }
    },
    "tsa-anchors-v2": {
        "freetsa-root-2016": {
            "rootSpkiSha256": (
                "52c54ba340885605314daa1857c8763b94087d05c636092938d4e2d1818e99b5"
            ),
            "signerSpkiSha256": {
                "fa02bd555e3e483d62b4e70be6218692068d2b0b0a7525db58dcbf2901cdb072"
            },
        },
        "digicert-trusted-root-g4": {
            "rootSpkiSha256": (
                "59df317bfa9f4f0ab7ca514d7772296aa2c765b87664d08b96e57399e364729c"
            ),
            "signerSpkiSha256": {
                "7abda95ed7301ac94bded350babc319903d0b4f16c4e7e39346dba5f9e992b72"
            },
        },
    },
}
CODE_PINNED_GENESIS_ENUMERATIONS: dict[str, dict[str, Any]] = {
    "records/GENESIS_RECORDS.json": {
        "path": "records/GENESIS_RECORDS.json",
        "sha256": "b4d3d7033e3c5f81cbaf31c76ae1b029746f53803edbae228935899826a59f5d",
        "canonicalJsonSha256": (
            "b4d3d7033e3c5f81cbaf31c76ae1b029746f53803edbae228935899826a59f5d"
        ),
        "size": 1057414,
        "entryCount": 4754,
        "totalSize": 635115664,
        "sourceCommit": "0a57bfc58ea3578cf3c43b3edd2d414813566ce8",
    }
}


class ChainError(ValueError):
    pass


@dataclass(frozen=True)
class TokenEvidence:
    anchor_id: str
    trust_bundle_id: str
    trust_bundle_path: str
    token_path: str
    token_sha256: str
    policy_oid: str
    imprint_algorithm_oid: str
    gen_time: str
    tsa_subject: str
    tsa_certificate_sha256: str
    tsa_spki_sha256: str
    # Populated from the same TSTInfo octets the pinned CMS verification
    # authenticated.  Defaulted so historic construction sites keep working.
    tst_info: "TstInfo | None" = None

    @property
    def accuracy_micros(self) -> int | None:
        """Signed accuracy in microseconds, or ``None`` when the TSA omitted it."""

        return None if self.tst_info is None else self.tst_info.accuracy_micros

    @property
    def upper_bound(self) -> datetime | None:
        """``genTime`` plus signed accuracy, or ``None`` when unknown."""

        return None if self.tst_info is None else self.tst_info.upper_bound


@dataclass(frozen=True)
class WitnessEvidence:
    status: str
    digest_sha256: str
    tokens: tuple[TokenEvidence, ...] = ()
    supplemental_tokens: tuple[TokenEvidence, ...] = ()
    anchor_id: str | None = None
    trust_bundle_id: str | None = None
    trust_bundle_path: str | None = None
    policy_oid: str | None = None
    imprint_algorithm_oid: str | None = None
    gen_time: str | None = None
    tsa_subject: str | None = None
    tsa_certificate_sha256: str | None = None
    tsa_spki_sha256: str | None = None


@dataclass(frozen=True)
class ChainVerification:
    ordered: tuple[Path, ...]
    witnesses: dict[Path, WitnessEvidence]
    enumeration_cutover: Path | None
    active_trust_bundles: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_trust_bundle_updates: tuple[dict[str, Any], ...] = ()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def logical_path(records: Path, path: Path) -> str:
    return (Path("records") / path.relative_to(records)).as_posix()


def physical_path(records: Path, value: str) -> Path:
    logical = Path(value)
    if (
        logical.is_absolute()
        or ".." in logical.parts
        or "\\" in value
        or not logical.parts
    ):
        raise ChainError(f"unsafe record path in genesis/chain: {value!r}")
    if logical.parts[0] == "records":
        logical = Path(*logical.parts[1:])
    path = records / logical
    try:
        path.resolve().relative_to(records.resolve())
    except ValueError as exc:
        raise ChainError(f"record path escapes records root: {value!r}") from exc
    return path


def ensure_regular_records_file(
    records: Path,
    path: Path,
    *,
    message: str,
) -> None:
    """Reject files reached through symlinks or outside the records root."""

    try:
        relative = path.relative_to(records)
    except ValueError as exc:
        raise ChainError(message) from exc
    if not relative.parts:
        raise ChainError(message)

    cursor = records
    for index, part in enumerate(relative.parts):
        cursor /= part
        try:
            mode = cursor.lstat().st_mode
        except OSError as exc:
            raise ChainError(message) from exc
        final = index == len(relative.parts) - 1
        if final:
            if not stat.S_ISREG(mode):
                raise ChainError(message)
        elif not stat.S_ISDIR(mode):
            raise ChainError(message)

    try:
        path.resolve().relative_to(records.resolve())
    except (OSError, ValueError) as exc:
        raise ChainError(message) from exc


def snapshot_paths(records: Path) -> list[Path]:
    return sorted(
        path
        for path in records.glob("????-??-??/digest-*.json")
        if SNAPSHOT_RE.fullmatch(path.name) and not path.name.endswith(".witness.json")
    )


def producer_signature_path(snapshot: Path) -> Path:
    """Return the producer-signature sibling for one snapshot."""

    return snapshot.with_suffix(producer_pins.SIGNATURE_SUFFIX)


def _producer_signature_paths(records: Path) -> list[Path]:
    return sorted(records.rglob(f"*{producer_pins.SIGNATURE_SUFFIX}"))


def _verify_producer_signatures(records: Path, ordered: list[Path]) -> None:
    try:
        active = producer_pins.producer_signing_active()
    except ValueError as exc:
        raise ChainError(str(exc)) from exc

    discovered = _producer_signature_paths(records)
    if not active:
        if discovered:
            raise ChainError(
                "producer signature is present while producer signing is dormant: "
                f"{logical_path(records, discovered[0])}"
            )
        return

    activation_logical = producer_pins.ACTIVATION_SNAPSHOT
    if activation_logical is None:  # Defended by producer_signing_active().
        raise ChainError("producer signing pins are half-armed")
    activation = physical_path(records, activation_logical)
    if activation not in ordered:
        raise ChainError(
            "producer signing activation snapshot is absent from the reachable "
            f"chain: {activation_logical}"
        )
    activation_index = ordered.index(activation)

    discovered_set = set(discovered)
    for snapshot in ordered[: activation_index + 1]:
        signature = producer_signature_path(snapshot)
        if signature in discovered_set:
            raise ChainError(
                "producer signature is forbidden at or before activation: "
                f"{logical_path(records, signature)}"
            )

    signed_snapshots = ordered[activation_index + 1 :]
    expected = {producer_signature_path(snapshot) for snapshot in signed_snapshots}
    orphaned = sorted(discovered_set - expected)
    if orphaned:
        raise ChainError(
            "orphan producer signature is not a post-activation snapshot sibling: "
            f"{logical_path(records, orphaned[0])}"
        )

    for signature in sorted(expected):
        ensure_regular_records_file(
            records,
            signature,
            message=(
                "missing or non-regular producer signature: "
                f"{logical_path(records, signature)}"
            ),
        )

    public_key_logical = Path(producer_pins.PUBLIC_KEY_RELPATH)
    if public_key_logical.parts[:1] == ("records",):
        public_key_logical = Path(*public_key_logical.parts[1:])
    public_key_candidate = records / public_key_logical
    ensure_regular_records_file(
        records,
        public_key_candidate,
        message=(
            "missing or non-regular producer public key: "
            f"{producer_pins.PUBLIC_KEY_RELPATH}"
        ),
    )
    public_key = physical_path(records, producer_pins.PUBLIC_KEY_RELPATH)

    try:
        from receipt.sign import SignError, spki_sha256, verify_signature_bytes
    except ImportError as exc:
        raise ChainError(
            "producer signing is active but the receipt package is not installed"
        ) from exc

    try:
        public_key_pem = public_key.read_bytes()
    except OSError as exc:
        raise ChainError(
            f"cannot read producer public key "
            f"{producer_pins.PUBLIC_KEY_RELPATH}: {exc}"
        ) from exc
    spki_pin = producer_pins.PRODUCER_SPKI_SHA256
    if spki_pin is None:  # Defended by producer_signing_active().
        raise ChainError("producer signing pins are half-armed")
    try:
        computed_spki = spki_sha256(public_key_pem)
    except SignError as exc:
        raise ChainError(
            f"producer public key is invalid: {producer_pins.PUBLIC_KEY_RELPATH}: "
            f"{exc}"
        ) from exc
    if computed_spki != spki_pin:
        raise ChainError(
            "producer public-key SPKI is not code-pinned for "
            f"{producer_pins.PUBLIC_KEY_RELPATH}: {computed_spki}"
        )
    for snapshot in signed_snapshots:
        signature = producer_signature_path(snapshot)
        signature_logical = logical_path(records, signature)
        try:
            signature_bytes = signature.read_bytes()
        except OSError as exc:
            raise ChainError(
                f"cannot read producer signature {signature_logical}: {exc}"
            ) from exc
        if len(signature_bytes) != 64:
            raise ChainError(
                f"producer signature for {signature_logical} must be exactly "
                f"64 raw bytes; found={len(signature_bytes)}"
            )
        snapshot_logical = logical_path(records, snapshot)
        try:
            snapshot_bytes = snapshot.read_bytes()
        except OSError as exc:
            raise ChainError(
                "cannot read snapshot for producer signature verification: "
                f"{snapshot_logical}: {exc}"
            ) from exc
        try:
            verify_signature_bytes(
                producer_pins.SIGNATURE_DOMAIN + snapshot_bytes,
                signature_bytes,
                public_key_pem,
                public_key_filename=producer_pins.PUBLIC_KEY_RELPATH,
                spki_sha256=spki_pin,
                label=signature_logical,
            )
        except SignError as exc:
            raise ChainError(str(exc)) from exc


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChainError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ChainError(f"record must be a JSON object: {path}")
    return value


def _run_openssl(
    arguments: list[str],
    *,
    input_bytes: bytes | None = None,
    binary: bool = False,
    env: dict[str, str] | None = None,
) -> bytes | str:
    command = ["openssl", *arguments]
    process_env = os.environ.copy()
    process_env.update({"OPENSSL_CONF": os.devnull, "LC_ALL": "C"})
    if env:
        process_env.update(env)
    try:
        completed = subprocess.run(
            command,
            input=input_bytes,
            capture_output=True,
            check=False,
            env=process_env,
        )
    except FileNotFoundError as exc:
        raise ChainError("openssl is required to verify RFC 3161 tokens") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).decode(errors="replace").strip()
        raise ChainError(f"OpenSSL command failed ({' '.join(command)}): {detail}")
    if binary:
        return completed.stdout
    return completed.stdout.decode(errors="strict")


def _certificate_identity(path: Path) -> dict[str, str]:
    certificate_der = _run_openssl(
        ["x509", "-in", str(path), "-outform", "DER"], binary=True
    )
    assert isinstance(certificate_der, bytes)
    public_key_pem = _run_openssl(
        ["x509", "-in", str(path), "-pubkey", "-noout"], binary=True
    )
    assert isinstance(public_key_pem, bytes)
    public_key_der = _run_openssl(
        ["pkey", "-pubin", "-outform", "DER"],
        input_bytes=public_key_pem,
        binary=True,
    )
    assert isinstance(public_key_der, bytes)
    description = _run_openssl(
        [
            "x509",
            "-in",
            str(path),
            "-noout",
            "-serial",
            "-subject",
            "-nameopt",
            "RFC2253",
        ]
    )
    assert isinstance(description, str)
    fields: dict[str, str] = {}
    for line in description.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            fields[key] = value
    return {
        "certificateSha256": hashlib.sha256(certificate_der).hexdigest(),
        "spkiSha256": hashlib.sha256(public_key_der).hexdigest(),
        "serial": fields.get("serial", "").upper(),
        "subject": fields.get("subject", ""),
    }


def _read_der_tlv(data: bytes, offset: int) -> tuple[int, bytes, int]:
    if offset >= len(data):
        raise ChainError("truncated DER value in RFC 3161 TSTInfo")
    tag = data[offset]
    offset += 1
    if offset >= len(data):
        raise ChainError("truncated DER length in RFC 3161 TSTInfo")
    first = data[offset]
    offset += 1
    if first & 0x80:
        count = first & 0x7F
        if count == 0 or count > 4 or offset + count > len(data):
            raise ChainError("invalid DER length in RFC 3161 TSTInfo")
        length = int.from_bytes(data[offset : offset + count], "big")
        offset += count
    else:
        length = first
    end = offset + length
    if end > len(data):
        raise ChainError("truncated DER content in RFC 3161 TSTInfo")
    return tag, data[offset:end], end


def _decode_oid(data: bytes) -> str:
    if not data:
        raise ChainError("empty policy OID in RFC 3161 token")
    first = data[0]
    values = [min(first // 40, 2), first - min(first // 40, 2) * 40]
    current = 0
    continuation = False
    for byte in data[1:]:
        current = (current << 7) | (byte & 0x7F)
        continuation = bool(byte & 0x80)
        if not continuation:
            values.append(current)
            current = 0
    if continuation:
        raise ChainError("truncated policy OID in RFC 3161 token")
    return ".".join(str(value) for value in values)


def _parse_generalized_time(value: str) -> datetime:
    match = re.fullmatch(r"(\d{14})(?:\.(\d+))?Z", value)
    if not match:
        raise ChainError(f"unsupported RFC 3161 genTime: {value!r}")
    parsed = datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    fraction = match.group(2)
    if fraction:
        parsed = parsed.replace(microsecond=int((fraction + "000000")[:6]))
    return parsed


def _format_utc(value: datetime) -> str:
    """Render one instant as RFC 3339 UTC, trimming trailing fraction zeros.

    The fraction is trimmed *before* the ``Z`` designator is appended.  An
    earlier version trimmed zeros from the fully rendered offset form, so
    ``2026-09-04T12:00:00.123000+00:00`` lost the two trailing zeros of the
    ``+00:00`` offset instead of the fraction and produced the malformed
    ``2026-09-04T12:00:00.123000+00:``.  Whole-second values, which is every
    published TSA genTime to date, rendered identically then and now.
    """

    value = value.astimezone(UTC).replace(tzinfo=None)
    text = value.isoformat(timespec="seconds")
    if value.microsecond:
        text += "." + f"{value.microsecond:06d}".rstrip("0")
    return text + "Z"


def _decode_der_integer(data: bytes, label: str) -> int:
    """Decode one DER INTEGER content octet string."""

    if not data:
        raise ChainError(f"empty DER integer in RFC 3161 {label}")
    if len(data) > 1 and (
        (data[0] == 0x00 and not data[1] & 0x80) or (data[0] == 0xFF and data[1] & 0x80)
    ):
        raise ChainError(f"non-minimal DER integer in RFC 3161 {label}")
    return int.from_bytes(data, "big", signed=True)


@dataclass(frozen=True)
class TstAccuracy:
    """Signed RFC 3161 ``Accuracy``, in the units the TSA actually emitted.

    RFC 3161 section 2.4.2 defines the accuracy as a symmetric bound: the
    real time lies in ``genTime - accuracy .. genTime + accuracy``.  Only the
    upper end matters for witness ordering, so :attr:`total_micros` is the
    quantity callers combine with ``genTime``.
    """

    seconds: int = 0
    millis: int | None = None
    micros: int | None = None

    @property
    def total_micros(self) -> int:
        return (
            self.seconds * 1_000_000 + (self.millis or 0) * 1_000 + (self.micros or 0)
        )


@dataclass(frozen=True)
class TstInfo:
    """Every field of a signed ``TSTInfo`` this repository interprets."""

    version: int
    policy_oid: str
    imprint_algorithm_oid: str
    hashed_message: bytes
    serial_number: int
    gen_time: datetime
    accuracy: TstAccuracy | None = None
    ordering: bool = False
    nonce: int | None = None

    @property
    def accuracy_micros(self) -> int | None:
        """Signed accuracy in microseconds, or ``None`` when absent.

        A token without an ``Accuracy`` field carries no signed statement
        about its own precision.  This repository pins no TSA policy that
        supplies a substitute bound, so the answer is unknown rather than
        zero; fabricating ``0`` would silently widen every ordering claim.
        """

        return None if self.accuracy is None else self.accuracy.total_micros

    @property
    def upper_bound(self) -> datetime | None:
        """``genTime`` plus signed accuracy, or ``None`` when unknown."""

        micros = self.accuracy_micros
        if micros is None:
            return None
        return self.gen_time + timedelta(microseconds=micros)


def _parse_accuracy(data: bytes) -> TstAccuracy:
    offset = 0
    seconds = 0
    millis: int | None = None
    micros: int | None = None
    if offset < len(data):
        tag, content, next_offset = _read_der_tlv(data, offset)
        if tag == 0x02:
            seconds = _decode_der_integer(content, "accuracy seconds")
            if seconds < 0:
                raise ChainError("RFC 3161 accuracy seconds must be non-negative")
            offset = next_offset
    if offset < len(data):
        tag, content, next_offset = _read_der_tlv(data, offset)
        if tag == 0x80:
            millis = _decode_der_integer(content, "accuracy millis")
            if not 1 <= millis <= 999:
                raise ChainError("RFC 3161 accuracy millis must be 1..999")
            offset = next_offset
    if offset < len(data):
        tag, content, next_offset = _read_der_tlv(data, offset)
        if tag == 0x81:
            micros = _decode_der_integer(content, "accuracy micros")
            if not 1 <= micros <= 999:
                raise ChainError("RFC 3161 accuracy micros must be 1..999")
            offset = next_offset
    if offset != len(data):
        raise ChainError("unsupported trailing data in RFC 3161 Accuracy")
    if seconds == 0 and millis is None and micros is None:
        raise ChainError("RFC 3161 Accuracy is present but empty")
    return TstAccuracy(seconds=seconds, millis=millis, micros=micros)


def parse_message_imprint(data: bytes) -> tuple[bytes, bytes]:
    """Decode a ``MessageImprint`` body into its algorithm OID and digest.

    ``data`` is the content of the ``MessageImprint`` SEQUENCE, which appears
    identically in a ``TimeStampReq`` and in a signed ``TSTInfo``.  The
    algorithm OID is returned in encoded form for :func:`_decode_oid`.
    """

    offset = 0
    tag, algorithm_identifier, offset = _read_der_tlv(data, offset)
    if tag != 0x30:
        raise ChainError("RFC 3161 message imprint lacks AlgorithmIdentifier")
    algorithm_offset = 0
    tag, algorithm_oid, algorithm_offset = _read_der_tlv(
        algorithm_identifier, algorithm_offset
    )
    if tag != 0x06:
        raise ChainError("RFC 3161 message imprint lacks an algorithm OID")
    if algorithm_offset < len(algorithm_identifier):
        tag, parameters, algorithm_offset = _read_der_tlv(
            algorithm_identifier, algorithm_offset
        )
        if tag != 0x05 or parameters:
            raise ChainError("unsupported RFC 3161 imprint algorithm parameters")
    if algorithm_offset != len(algorithm_identifier):
        raise ChainError("trailing RFC 3161 imprint AlgorithmIdentifier data")
    tag, hashed_message, offset = _read_der_tlv(data, offset)
    if tag != 0x04 or offset != len(data):
        raise ChainError("invalid RFC 3161 hashed message")
    return algorithm_oid, hashed_message


def parse_tst_info(data: bytes) -> TstInfo:
    """Parse one complete signed ``TSTInfo`` DER structure.

    Callers must hand over TSTInfo octets that a pinned CMS verification
    already authenticated; nothing here checks a signature.
    """

    tag, sequence, end = _read_der_tlv(data, 0)
    if tag != 0x30 or end != len(data):
        raise ChainError("RFC 3161 TSTInfo is not one complete DER sequence")
    offset = 0
    tag, version_bytes, offset = _read_der_tlv(sequence, offset)
    if tag != 0x02:
        raise ChainError("RFC 3161 TSTInfo lacks a version")
    version = _decode_der_integer(version_bytes, "TSTInfo version")
    tag, policy, offset = _read_der_tlv(sequence, offset)
    if tag != 0x06:
        raise ChainError("RFC 3161 TSTInfo lacks a policy OID")
    tag, message_imprint, offset = _read_der_tlv(sequence, offset)
    if tag != 0x30:
        raise ChainError("RFC 3161 TSTInfo lacks a message imprint")
    algorithm_oid, hashed_message = parse_message_imprint(message_imprint)
    tag, serial, offset = _read_der_tlv(sequence, offset)
    if tag != 0x02:
        raise ChainError("RFC 3161 TSTInfo lacks a serial number")
    tag, gen_time, offset = _read_der_tlv(sequence, offset)
    if tag != 0x18:
        raise ChainError("RFC 3161 TSTInfo lacks a genTime")
    try:
        gen_time_text = gen_time.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ChainError("RFC 3161 genTime is not ASCII") from exc

    # Everything after genTime is optional; each field appears at most once
    # and only in the ASN.1 order below.  Unknown tags fall through to the
    # trailing-data check rather than being skipped silently.
    accuracy: TstAccuracy | None = None
    ordering = False
    nonce: int | None = None
    if offset < len(sequence):
        tag, content, next_offset = _read_der_tlv(sequence, offset)
        if tag == 0x30:
            accuracy = _parse_accuracy(content)
            offset = next_offset
    if offset < len(sequence):
        tag, content, next_offset = _read_der_tlv(sequence, offset)
        if tag == 0x01:
            # DER omits a DEFAULT FALSE, but an explicitly encoded FALSE is
            # accepted here: this repository never reads ``ordering``, and
            # rejecting the redundant encoding would fail closed on an
            # otherwise sound token for no security gain.
            if len(content) != 1 or content[0] not in {0x00, 0xFF}:
                raise ChainError("invalid RFC 3161 TSTInfo ordering boolean")
            ordering = content[0] == 0xFF
            offset = next_offset
    if offset < len(sequence):
        tag, content, next_offset = _read_der_tlv(sequence, offset)
        if tag == 0x02:
            nonce = _decode_der_integer(content, "TSTInfo nonce")
            offset = next_offset
    while offset < len(sequence):
        # ``tsa [0] EXPLICIT GeneralName`` and ``extensions [1] IMPLICIT``
        # are carried but not interpreted here.
        tag, _content, offset = _read_der_tlv(sequence, offset)
        if tag not in {0xA0, 0xA1}:
            raise ChainError(f"unexpected RFC 3161 TSTInfo field tag 0x{tag:02x}")

    return TstInfo(
        version=version,
        policy_oid=_decode_oid(policy),
        imprint_algorithm_oid=_decode_oid(algorithm_oid),
        hashed_message=hashed_message,
        serial_number=_decode_der_integer(serial, "TSTInfo serial number"),
        gen_time=_parse_generalized_time(gen_time_text),
        accuracy=accuracy,
        ordering=ordering,
        nonce=nonce,
    )


def _parse_tst_info(data: bytes) -> tuple[str, str, bytes, datetime]:
    """Historic four-tuple view of :func:`parse_tst_info`."""

    info = parse_tst_info(data)
    return (
        info.policy_oid,
        info.imprint_algorithm_oid,
        info.hashed_message,
        info.gen_time,
    )


def _parse_rfc3339(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ChainError(f"missing or invalid timestamp claim {label}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ChainError(f"invalid timestamp claim {label}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ChainError(f"timestamp claim lacks a timezone {label}: {value!r}")
    return parsed.astimezone(UTC)


def _creation_claims(payload: dict[str, Any]) -> list[tuple[str, datetime]]:
    claims: list[tuple[str, datetime]] = []
    for key in ("recordedAt", "createdAt"):
        if key in payload:
            claims.append((key, _parse_rfc3339(payload[key], key)))
    dependencies = payload.get("dependencies")
    if isinstance(dependencies, dict):
        stack: list[tuple[str, dict[str, Any]]] = [("dependencies", dependencies)]
        while stack:
            prefix, current = stack.pop()
            for key, value in current.items():
                label = f"{prefix}.{key}"
                if isinstance(value, dict):
                    stack.append((label, value))
                elif key in {"builtAt", "createdAt", "recordedAt", "fetchedAt"}:
                    claims.append((label, _parse_rfc3339(value, label)))
    if not any(label == "recordedAt" for label, _ in claims):
        raise ChainError("snapshot lacks top-level recordedAt creation claim")
    return claims


def validate_token_time(
    payload: dict[str, Any],
    gen_time: datetime,
    *,
    now: datetime,
    max_future_seconds: int,
    max_token_lead_seconds: int,
) -> None:
    """Validate signed time against wall time and internal creation claims."""

    current = now.astimezone(UTC)
    if gen_time > current + timedelta(seconds=max_future_seconds):
        raise ChainError(
            f"RFC 3161 genTime {_format_utc(gen_time)} postdates verification "
            f"time {_format_utc(current)}"
        )
    for label, claim in _creation_claims(payload):
        if gen_time < claim - timedelta(seconds=max_token_lead_seconds):
            raise ChainError(
                f"RFC 3161 genTime {_format_utc(gen_time)} impossibly precedes "
                f"{label}={_format_utc(claim)}"
            )


def _trust_bundle_reference(
    records: Path, path: Path, payload: dict[str, Any]
) -> dict[str, Any]:
    return {
        "bundleId": payload.get("bundleId"),
        "path": logical_path(records, path),
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
        "canonicalJsonSha256": canonical_sha256(payload),
    }


def _load_trust_bundle(
    records: Path, reference: dict[str, Any]
) -> tuple[Path, dict[str, Any]]:
    logical = reference.get("path")
    if not isinstance(logical, str) or not TRUST_BUNDLE_RE.fullmatch(logical):
        raise ChainError(
            f"TSA trust bundle path is not immutable/versioned: {logical!r}"
        )
    if CODE_PINNED_TRUST_BUNDLES.get(logical) != reference:
        raise ChainError(
            f"TSA trust bundle is not independently pinned by verifier code: {logical}"
        )
    path = physical_path(records, logical)
    if not path.is_file() or path.is_symlink():
        raise ChainError(f"TSA trust bundle is missing or not regular: {path}")
    payload = load_json(path)
    if payload.get("schemaVersion") != "thesis_tsa_trust_bundle_v1":
        raise ChainError(
            f"unsupported TSA trust schema: {payload.get('schemaVersion')!r}"
        )
    if not isinstance(payload.get("bundleId"), str) or not payload["bundleId"]:
        raise ChainError(f"TSA trust bundle lacks bundleId: {path}")
    if path.read_bytes() not in {
        canonical_bytes(payload),
        canonical_bytes(payload) + b"\n",
    }:
        raise ChainError(f"TSA trust configuration is not canonical JSON: {path}")
    anchors = payload.get("anchors")
    if not isinstance(anchors, list) or not anchors:
        raise ChainError("TSA trust bundle must contain at least one anchor")
    anchor_ids: set[str] = set()
    endpoints: set[str] = set()
    for anchor in anchors:
        if not isinstance(anchor, dict):
            raise ChainError("TSA trust bundle anchor is not an object")
        anchor_id = anchor.get("id")
        endpoint = anchor.get("endpoint")
        if not isinstance(anchor_id, str) or not anchor_id:
            raise ChainError("TSA trust bundle anchor lacks an ID")
        if not isinstance(endpoint, str) or not endpoint:
            raise ChainError(f"TSA anchor {anchor_id!r} lacks an endpoint")
        if anchor_id in anchor_ids:
            raise ChainError(f"duplicate TSA anchor ID in trust bundle: {anchor_id}")
        if endpoint in endpoints:
            raise ChainError(f"duplicate TSA endpoint in trust bundle: {endpoint}")
        anchor_ids.add(anchor_id)
        endpoints.add(endpoint)
    actual_reference = _trust_bundle_reference(records, path, payload)
    if reference != actual_reference:
        raise ChainError(
            f"TSA trust bundle commitment mismatch for {logical}: "
            f"expected {reference}, got {actual_reference}"
        )
    return path, payload


def _bootstrap_trust_bundles(
    records: Path, genesis: dict[str, Any], *, required: bool
) -> dict[str, dict[str, Any]]:
    reference = genesis.get("tsaTrustBundle")
    if reference is None and not required:
        return {}
    if not isinstance(reference, dict):
        raise ChainError("chain genesis lacks the pinned TSA trust bundle")
    path, _payload = _load_trust_bundle(records, reference)
    return {logical_path(records, path): reference}


def _trust_bundle_updates(
    records: Path, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    updates = payload.get("trustBundleUpdates", [])
    if not isinstance(updates, list):
        raise ChainError("snapshot trustBundleUpdates must be a list")
    validated: list[dict[str, Any]] = []
    for reference in updates:
        if not isinstance(reference, dict):
            raise ChainError("snapshot trust bundle update is not an object")
        _load_trust_bundle(records, reference)
        validated.append(reference)
    return validated


def _activate_trust_bundles(
    active: dict[str, dict[str, Any]], updates: list[dict[str, Any]]
) -> None:
    ids = {str(reference.get("bundleId")): path for path, reference in active.items()}
    for reference in updates:
        path = str(reference["path"])
        bundle_id = str(reference["bundleId"])
        if path in active and active[path] != reference:
            raise ChainError(f"TSA trust bundle path was reused with new bytes: {path}")
        if bundle_id in ids and ids[bundle_id] != path:
            raise ChainError(
                f"TSA trust bundle ID was reused at a new path: {bundle_id}"
            )
        active[path] = reference
        ids[bundle_id] = path


def trust_bundle_updates_for_snapshot(
    verification: ChainVerification,
) -> list[dict[str, Any]]:
    """Return code-pinned bundles not already active or replay-pending."""

    introduced = set(verification.active_trust_bundles)
    introduced.update(
        str(reference["path"])
        for reference in verification.pending_trust_bundle_updates
    )
    return [
        dict(reference)
        for path, reference in CODE_PINNED_TRUST_BUNDLES.items()
        if path not in introduced
    ]


def preferred_active_trust_bundle(
    active: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Select the highest immutable bundle version already authorized."""

    candidates: list[tuple[int, dict[str, Any]]] = []
    for path, reference in active.items():
        match = re.fullmatch(r"records/trust/tsa-anchors-v([1-9][0-9]*)\.json", path)
        if match:
            candidates.append((int(match.group(1)), reference))
    if not candidates:
        raise ChainError("verified chain has no active versioned TSA trust bundle")
    return dict(max(candidates, key=lambda item: item[0])[1])


def _select_anchor(
    records: Path, witness: dict[str, Any], trust: dict[str, Any]
) -> dict[str, Any]:
    anchor_id = witness.get("tsaAnchorId")
    endpoint = witness.get("tsa")
    candidates = [
        anchor
        for anchor in trust["anchors"]
        if isinstance(anchor, dict)
        and (
            (anchor_id and anchor.get("id") == anchor_id)
            or (not anchor_id and endpoint and anchor.get("endpoint") == endpoint)
        )
    ]
    if len(candidates) != 1:
        raise ChainError(
            "witness does not select exactly one pinned TSA anchor: "
            f"id={anchor_id!r}, endpoint={endpoint!r}"
        )
    anchor = candidates[0]
    if anchor_id and endpoint != anchor.get("endpoint"):
        raise ChainError("witness TSA endpoint does not match its pinned anchor")
    root = anchor.get("rootCertificate")
    if not isinstance(root, dict):
        raise ChainError(f"TSA anchor {anchor.get('id')!r} lacks rootCertificate")
    root_path = physical_path(records, str(root.get("path", "")))
    if not root_path.is_file() or root_path.is_symlink():
        raise ChainError(
            f"pinned TSA root is missing or not a regular file: {root_path}"
        )
    if sha256_file(root_path) != root.get("pemSha256"):
        raise ChainError(f"pinned TSA root PEM hash mismatch: {root_path}")
    identity = _certificate_identity(root_path)
    if identity["certificateSha256"] != root.get("certificateSha256"):
        raise ChainError(f"pinned TSA root certificate hash mismatch: {root_path}")
    if identity["spkiSha256"] != root.get("spkiSha256"):
        raise ChainError(f"pinned TSA root SPKI hash mismatch: {root_path}")
    bundle_id = str(trust.get("bundleId"))
    code_identity = CODE_PINNED_TSA_IDENTITIES.get(bundle_id, {}).get(
        str(anchor.get("id"))
    )
    if not isinstance(code_identity, dict):
        raise ChainError(
            f"TSA identity is not independently pinned in verifier code: "
            f"{bundle_id}/{anchor.get('id')}"
        )
    if identity["spkiSha256"] != code_identity.get("rootSpkiSha256"):
        raise ChainError("TSA root SPKI differs from the verifier code pin")
    configured_signers = anchor.get("allowedSigners")
    configured_spkis = (
        {
            signer.get("spkiSha256")
            for signer in configured_signers
            if isinstance(signer, dict)
        }
        if isinstance(configured_signers, list)
        else set()
    )
    if configured_spkis != code_identity.get("signerSpkiSha256"):
        raise ChainError("TSA signer SPKIs differ from the verifier code pins")
    return anchor


def _bundle_for_claim(
    records: Path,
    claim: dict[str, Any],
    trusted_bundles: dict[str, dict[str, Any]],
    *,
    active_required: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle_path = claim.get("trustBundlePath")
    if not isinstance(bundle_path, str):
        raise ChainError("witness lacks a TSA trust-bundle path")
    if active_required:
        bundle_reference = trusted_bundles.get(bundle_path)
        if bundle_reference is None:
            raise ChainError(
                f"witness selects an untrusted TSA bundle: {bundle_path!r}"
            )
    else:
        bundle_reference = CODE_PINNED_TRUST_BUNDLES.get(bundle_path)
        if bundle_reference is None:
            raise ChainError(
                f"witness selects a bundle absent from verifier code pins: "
                f"{bundle_path!r}"
            )
    if claim.get("trustBundleSha256") != bundle_reference.get("sha256"):
        raise ChainError("witness TSA trust-bundle hash mismatch")
    _trust_path, trust = _load_trust_bundle(records, bundle_reference)
    if claim.get("trustBundleId") != trust.get("bundleId"):
        raise ChainError("witness TSA trust-bundle ID mismatch")
    return bundle_reference, trust


def verify_timestamp_token(
    path: Path,
    token_claim: dict[str, Any],
    bundle_reference: dict[str, Any],
    *,
    records: Path,
    now: datetime | None = None,
) -> TokenEvidence:
    """Verify one claimed RFC 3161 token against one code-pinned anchor."""

    bundle_path = str(bundle_reference["path"])
    expected_bundle_claims = {
        "trustBundleId": bundle_reference["bundleId"],
        "trustBundlePath": bundle_path,
        "trustBundleSha256": bundle_reference["sha256"],
    }
    for key, expected in expected_bundle_claims.items():
        if token_claim.get(key) != expected:
            raise ChainError(f"timestamp token {key} does not match its bundle pin")
    _trust_path, trust = _load_trust_bundle(records, bundle_reference)
    anchor = _select_anchor(records, token_claim, trust)
    token_logical = token_claim.get("tokenPath")
    if not isinstance(token_logical, str):
        raise ChainError("witness token lacks tokenPath")
    token_path = physical_path(records, token_logical)
    if not token_path.is_file() or token_path.is_symlink():
        raise ChainError(f"witness token is missing for {path}: {token_path}")
    token_sha256 = sha256_file(token_path)
    if token_sha256 != token_claim.get("tokenSha256"):
        raise ChainError(f"witness token hash mismatch for {path}")
    root_path = physical_path(records, str(anchor["rootCertificate"]["path"]))

    with tempfile.TemporaryDirectory(prefix="thesis-tsa-") as temporary:
        temp = Path(temporary)
        token_der = temp / "token.der"
        tst_info = temp / "tst-info.der"
        signer = temp / "signer.pem"
        empty_ca_dir = temp / "empty-ca"
        empty_ca_dir.mkdir()
        _run_openssl(
            [
                "ts",
                "-reply",
                "-config",
                os.devnull,
                "-in",
                str(token_path),
                "-token_out",
                "-out",
                str(token_der),
            ]
        )
        _run_openssl(
            [
                "cms",
                "-verify",
                "-inform",
                "DER",
                "-in",
                str(token_der),
                "-noverify",
                "-nosigs",
                "-binary",
                "-out",
                str(tst_info),
            ]
        )
        policy_oid, imprint_algorithm_oid, hashed_message, gen_time = _parse_tst_info(
            tst_info.read_bytes()
        )

        allowed_policies = anchor.get("allowedPolicyOids")
        if not isinstance(allowed_policies, list) or policy_oid not in allowed_policies:
            raise ChainError(
                f"RFC 3161 policy {policy_oid!r} is not allowed for TSA anchor "
                f"{anchor.get('id')!r}"
            )
        allowed_imprints = anchor.get("allowedImprintAlgorithmOids")
        if (
            not isinstance(allowed_imprints, list)
            or imprint_algorithm_oid not in allowed_imprints
        ):
            raise ChainError(
                f"RFC 3161 imprint algorithm {imprint_algorithm_oid!r} is not "
                f"allowed for TSA anchor {anchor.get('id')!r}"
            )
        if imprint_algorithm_oid != SHA256_OID or len(hashed_message) != 32:
            raise ChainError(
                "RFC 3161 witness must use a 32-byte SHA-256 message imprint"
            )
        payload = load_json(path)
        validate_token_time(
            payload,
            gen_time,
            now=now or datetime.now(UTC),
            max_future_seconds=int(anchor.get("maxFutureSeconds", 300)),
            max_token_lead_seconds=int(anchor.get("maxTokenLeadSeconds", 300)),
        )

        verification_env = {
            "SSL_CERT_DIR": str(empty_ca_dir),
            "SSL_CERT_FILE": os.devnull,
        }
        verification_time = str(int(gen_time.timestamp()))
        # No -CAstore here: OpenSSL loads default trust locations only when
        # NO CA option is given, so the pinned -CAfile plus an empty -CApath
        # already excludes them — and ubuntu's OpenSSL 3.0 rejects the
        # "file:/dev/null" store URI outright (live-caught 2026-07-10 in the
        # register job; macOS OpenSSL accepted it).
        _run_openssl(
            [
                "ts",
                "-verify",
                "-config",
                os.devnull,
                "-data",
                str(path),
                "-in",
                str(token_path),
                "-CAfile",
                str(root_path),
                "-CApath",
                str(empty_ca_dir),
                "-attime",
                verification_time,
            ],
            env=verification_env,
        )
        _run_openssl(
            [
                "cms",
                "-verify",
                "-inform",
                "DER",
                "-in",
                str(token_der),
                "-CAfile",
                str(root_path),
                "-no-CApath",
                "-no-CAstore",
                "-purpose",
                "timestampsign",
                "-attime",
                verification_time,
                "-signer",
                str(signer),
                "-out",
                str(tst_info),
            ],
            env=verification_env,
        )
        signer_identity = _certificate_identity(signer)
        # Re-read the eContent the *signature-verified* CMS run just wrote, so
        # every reported TSTInfo field (accuracy, nonce, serial) derives from
        # octets the pinned root authenticated rather than from the earlier
        # ``-nosigs`` extraction.  Both extractions read the same SignedData,
        # so a disagreement is a decoder anomaly and fails closed.
        tst_info_detail = parse_tst_info(tst_info.read_bytes())

    if (
        tst_info_detail.policy_oid,
        tst_info_detail.imprint_algorithm_oid,
        tst_info_detail.hashed_message,
        tst_info_detail.gen_time,
    ) != (policy_oid, imprint_algorithm_oid, hashed_message, gen_time):
        raise ChainError(
            "verified RFC 3161 TSTInfo disagrees with its pre-verification parse"
        )

    allowed_signers = anchor.get("allowedSigners")
    if not isinstance(allowed_signers, list) or signer_identity not in allowed_signers:
        raise ChainError(
            "RFC 3161 token signer is not pinned for TSA anchor "
            f"{anchor.get('id')!r}: {signer_identity}"
        )
    declared = {
        "tsaPolicyOid": policy_oid,
        "tsaImprintAlgorithmOid": imprint_algorithm_oid,
        "tsaGenTime": _format_utc(gen_time),
        "tsaSignerCertificateSha256": signer_identity["certificateSha256"],
        "tsaSignerSpkiSha256": signer_identity["spkiSha256"],
    }
    for key, actual in declared.items():
        if key in token_claim and token_claim[key] != actual:
            raise ChainError(
                f"witness {key} mismatch for {path}: expected {actual}, "
                f"got {token_claim[key]}"
            )
    return TokenEvidence(
        anchor_id=str(anchor["id"]),
        trust_bundle_id=str(trust["bundleId"]),
        trust_bundle_path=bundle_path,
        token_path=token_logical,
        token_sha256=token_sha256,
        policy_oid=policy_oid,
        imprint_algorithm_oid=imprint_algorithm_oid,
        gen_time=_format_utc(gen_time),
        tsa_subject=signer_identity["subject"],
        tsa_certificate_sha256=signer_identity["certificateSha256"],
        tsa_spki_sha256=signer_identity["spkiSha256"],
        tst_info=tst_info_detail,
    )


_TOKEN_EVIDENCE_FIELDS = {
    "tokenPath",
    "tokenSha256",
    "tsaPolicyOid",
    "tsaImprintAlgorithmOid",
    "tsaGenTime",
    "tsaSignerCertificateSha256",
    "tsaSignerSpkiSha256",
}


def _unavailable_outcome(outcome: dict[str, Any], *, label: str) -> None:
    reason = outcome.get("reason")
    if not isinstance(reason, str) or not reason:
        raise ChainError(f"{label} unavailable outcome lacks a reason")
    forbidden = sorted(_TOKEN_EVIDENCE_FIELDS.intersection(outcome))
    if forbidden:
        raise ChainError(
            f"{label} unavailable outcome contains token evidence: {forbidden}"
        )


def _summarize_witness(
    *,
    status: str,
    digest_sha256: str,
    tokens: list[TokenEvidence],
    supplemental_tokens: list[TokenEvidence] | None = None,
) -> WitnessEvidence:
    if not tokens:
        return WitnessEvidence(
            status=status,
            digest_sha256=digest_sha256,
            supplemental_tokens=tuple(supplemental_tokens or ()),
        )
    earliest = min(
        tokens,
        key=lambda token: (
            _parse_rfc3339(token.gen_time, "token genTime"),
            token.anchor_id,
        ),
    )
    return WitnessEvidence(
        status=status,
        digest_sha256=digest_sha256,
        tokens=tuple(tokens),
        supplemental_tokens=tuple(supplemental_tokens or ()),
        anchor_id=earliest.anchor_id,
        trust_bundle_id=earliest.trust_bundle_id,
        trust_bundle_path=earliest.trust_bundle_path,
        policy_oid=earliest.policy_oid,
        imprint_algorithm_oid=earliest.imprint_algorithm_oid,
        gen_time=earliest.gen_time,
        tsa_subject=earliest.tsa_subject,
        tsa_certificate_sha256=earliest.tsa_certificate_sha256,
        tsa_spki_sha256=earliest.tsa_spki_sha256,
    )


def _v1_witness_evidence(
    path: Path,
    witness: dict[str, Any],
    *,
    records: Path,
    digest_sha256: str,
    trusted_bundles: dict[str, dict[str, Any]],
    now: datetime | None,
) -> WitnessEvidence:
    status = witness.get("status")
    if status not in {"available", "unavailable"}:
        raise ChainError(f"invalid witness status for {path}: {status!r}")
    if status == "unavailable":
        if not witness.get("reason"):
            raise ChainError(f"unavailable witness lacks a reason for {path}")
        return WitnessEvidence(status=status, digest_sha256=digest_sha256)
    bundle_reference, _trust = _bundle_for_claim(
        records, witness, trusted_bundles, active_required=True
    )
    token = verify_timestamp_token(
        path,
        witness,
        bundle_reference,
        records=records,
        now=now,
    )
    return _summarize_witness(
        status=status,
        digest_sha256=digest_sha256,
        tokens=[token],
    )


def _active_anchor_ids(
    records: Path, trusted_bundles: dict[str, dict[str, Any]]
) -> set[str]:
    active: set[str] = set()
    for reference in trusted_bundles.values():
        _path, trust = _load_trust_bundle(records, reference)
        active.update(str(anchor["id"]) for anchor in trust["anchors"])
    return active


def _supplemental_candidates(
    records: Path,
    trusted_bundles: dict[str, dict[str, Any]],
    transition_bundle_updates: list[dict[str, Any]],
) -> dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]]:
    active_ids = _active_anchor_ids(records, trusted_bundles)
    candidates: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for reference in transition_bundle_updates:
        bundle_path = str(reference["path"])
        if bundle_path in trusted_bundles:
            continue
        _path, trust = _load_trust_bundle(records, reference)
        for anchor in trust["anchors"]:
            anchor_id = str(anchor["id"])
            if anchor_id not in active_ids:
                candidates[(bundle_path, anchor_id)] = (reference, anchor)
    return candidates


def _v2_witness_evidence(
    path: Path,
    witness: dict[str, Any],
    *,
    records: Path,
    digest_sha256: str,
    trusted_bundles: dict[str, dict[str, Any]],
    transition_bundle_updates: list[dict[str, Any]],
    now: datetime | None,
) -> WitnessEvidence:
    status = witness.get("status")
    if status not in {"available", "unavailable"}:
        raise ChainError(f"invalid witness status for {path}: {status!r}")
    preferred = preferred_active_trust_bundle(trusted_bundles)
    if witness.get("trustBundlePath") != preferred["path"]:
        raise ChainError(
            "multi-token witness does not use the newest active TSA trust bundle"
        )
    bundle_reference, trust = _bundle_for_claim(
        records, witness, trusted_bundles, active_required=True
    )
    outcomes = witness.get("anchorOutcomes")
    if not isinstance(outcomes, list):
        raise ChainError("multi-token witness anchorOutcomes must be a list")
    expected_anchor_ids = {str(anchor["id"]) for anchor in trust["anchors"]}
    seen_anchor_ids: set[str] = set()
    tokens: list[TokenEvidence] = []
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            raise ChainError("multi-token witness outcome is not an object")
        anchor = _select_anchor(records, outcome, trust)
        anchor_id = str(anchor["id"])
        if anchor_id in seen_anchor_ids:
            raise ChainError(f"duplicate TSA anchor outcome: {anchor_id}")
        seen_anchor_ids.add(anchor_id)
        outcome_status = outcome.get("status")
        if outcome_status == "available":
            claim = {**witness, **outcome}
            tokens.append(
                verify_timestamp_token(
                    path,
                    claim,
                    bundle_reference,
                    records=records,
                    now=now,
                )
            )
        elif outcome_status == "unavailable":
            _unavailable_outcome(outcome, label=f"TSA anchor {anchor_id}")
        else:
            raise ChainError(
                f"invalid TSA anchor outcome status for {anchor_id}: {outcome_status!r}"
            )
    if seen_anchor_ids != expected_anchor_ids:
        raise ChainError(
            "multi-token witness anchor outcome mismatch: "
            f"missing={sorted(expected_anchor_ids - seen_anchor_ids)}, "
            f"extra={sorted(seen_anchor_ids - expected_anchor_ids)}"
        )

    candidates = _supplemental_candidates(
        records, trusted_bundles, transition_bundle_updates
    )
    supplemental = witness.get("supplementalOutcomes", [])
    if not isinstance(supplemental, list):
        raise ChainError("multi-token witness supplementalOutcomes must be a list")
    seen_supplemental: set[tuple[str, str]] = set()
    supplemental_tokens: list[TokenEvidence] = []
    for outcome in supplemental:
        if not isinstance(outcome, dict):
            raise ChainError("supplemental TSA outcome is not an object")
        if outcome.get("role") != "pending_trust_bundle":
            raise ChainError("supplemental TSA outcome has the wrong role")
        bundle_path = outcome.get("trustBundlePath")
        anchor_id = outcome.get("tsaAnchorId")
        key = (str(bundle_path), str(anchor_id))
        if key in seen_supplemental:
            raise ChainError(f"duplicate supplemental TSA outcome: {key}")
        seen_supplemental.add(key)
        candidate = candidates.get(key)
        if candidate is None:
            raise ChainError(
                "supplemental TSA outcome is not introduced by a pending "
                f"trust transition: {key}"
            )
        reference, trust_anchor = candidate
        _reference, pending_trust = _bundle_for_claim(
            records, outcome, trusted_bundles, active_required=False
        )
        selected = _select_anchor(records, outcome, pending_trust)
        if selected != trust_anchor:
            raise ChainError(f"supplemental TSA anchor mismatch: {key}")
        outcome_status = outcome.get("status")
        if outcome_status == "available":
            supplemental_tokens.append(
                verify_timestamp_token(
                    path,
                    outcome,
                    reference,
                    records=records,
                    now=now,
                )
            )
        elif outcome_status == "unavailable":
            _unavailable_outcome(outcome, label=f"supplemental TSA anchor {anchor_id}")
        else:
            raise ChainError(
                f"invalid supplemental TSA outcome status: {outcome_status!r}"
            )
    if seen_supplemental != set(candidates):
        raise ChainError(
            "supplemental TSA outcome mismatch: "
            f"missing={sorted(set(candidates) - seen_supplemental)}, "
            f"extra={sorted(seen_supplemental - set(candidates))}"
        )

    expected_status = "available" if tokens else "unavailable"
    if status != expected_status:
        raise ChainError(
            f"multi-token witness status {status!r} disagrees with verified "
            f"token evidence {expected_status!r}"
        )
    if status == "unavailable" and not witness.get("reason"):
        raise ChainError(f"unavailable witness lacks a reason for {path}")
    return _summarize_witness(
        status=status,
        digest_sha256=digest_sha256,
        tokens=tokens,
        supplemental_tokens=supplemental_tokens,
    )


def verify_witness(
    path: Path,
    *,
    records: Path | None = None,
    now: datetime | None = None,
    trusted_bundles: dict[str, dict[str, Any]] | None = None,
    transition_bundle_updates: list[dict[str, Any]] | None = None,
) -> WitnessEvidence:
    records = (records or path.parents[1]).resolve()
    digest_sha = sha256_file(path)
    witness_path = path.with_suffix(".witness.json")
    if not witness_path.is_file():
        raise ChainError(f"missing explicit witness marker for {path}")
    witness = load_json(witness_path)
    if witness.get("digestSha256") != digest_sha:
        raise ChainError(
            f"witness digest mismatch for {path}: expected {digest_sha}, "
            f"got {witness.get('digestSha256')}"
        )
    if trusted_bundles is None:
        genesis = load_json(records / "CHAIN_GENESIS.json")
        trusted_bundles = _bootstrap_trust_bundles(records, genesis, required=True)
    if transition_bundle_updates is None:
        transition_bundle_updates = _trust_bundle_updates(records, load_json(path))
    schema = witness.get("schemaVersion")
    if schema == "thesis_rfc3161_witness_v1":
        preferred = (
            preferred_active_trust_bundle(trusted_bundles) if trusted_bundles else None
        )
        if transition_bundle_updates or (
            preferred is not None and preferred["bundleId"] != "tsa-anchors-v1"
        ):
            raise ChainError(
                "legacy witness schema cannot cover a TSA trust transition "
                "or a chain with v2 active"
            )
        return _v1_witness_evidence(
            path,
            witness,
            records=records,
            digest_sha256=digest_sha,
            trusted_bundles=trusted_bundles,
            now=now,
        )
    if schema == "thesis_rfc3161_witness_v2":
        return _v2_witness_evidence(
            path,
            witness,
            records=records,
            digest_sha256=digest_sha,
            trusted_bundles=trusted_bundles,
            transition_bundle_updates=transition_bundle_updates,
            now=now,
        )
    raise ChainError(f"unsupported witness schema for {path}")


def _verify_enumeration_against_git(
    records: Path, source_commit: str, entries: list[dict[str, Any]]
) -> None:
    """Bind the enumeration to the named Git tree when repository data exists."""

    repository = records.parent
    if not (repository / ".git").exists():
        return
    completed = subprocess.run(
        [
            "git",
            "ls-tree",
            "-r",
            "-z",
            "--long",
            source_commit,
            "--",
            "records",
        ],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ChainError(
            "cannot inspect genesis enumeration source Git tree: "
            + completed.stderr.decode(errors="replace").strip()
        )
    tree: list[tuple[str, str, int]] = []
    for item in completed.stdout.split(b"\0"):
        if not item:
            continue
        metadata, separator, path_bytes = item.partition(b"\t")
        if not separator:
            raise ChainError("unexpected git ls-tree output for genesis enumeration")
        fields = metadata.decode().split()
        if len(fields) != 4:
            raise ChainError("unexpected git ls-tree metadata for genesis enumeration")
        mode, object_type, object_id, size_text = fields
        try:
            logical = path_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ChainError("genesis Git tree contains a non-UTF-8 path") from exc
        if mode != "100644" or object_type != "blob":
            raise ChainError(f"genesis Git tree contains non-regular record: {logical}")
        tree.append((logical, object_id, int(size_text)))
    enumerated_paths = [str(entry["path"]) for entry in entries]
    tree_paths = [logical for logical, _object_id, _size in tree]
    if enumerated_paths != tree_paths:
        raise ChainError(
            "genesis enumeration membership differs from its source Git tree: "
            f"unlisted={sorted(set(tree_paths) - set(enumerated_paths))}, "
            f"extra={sorted(set(enumerated_paths) - set(tree_paths))}"
        )
    for entry, (_logical, _object_id, tree_size) in zip(entries, tree):
        if entry["size"] != tree_size:
            raise ChainError(
                f"genesis enumeration size differs from Git tree: {entry['path']}"
            )
        if "\n" in entry["path"] or "\r" in entry["path"]:
            raise ChainError("genesis enumeration path contains a line break")
    hash_process = subprocess.run(
        ["git", "hash-object", "--stdin-paths"],
        cwd=repository,
        input=("\n".join(enumerated_paths) + "\n").encode(),
        capture_output=True,
        check=False,
    )
    if hash_process.returncode != 0:
        raise ChainError(
            "cannot hash genesis enumeration worktree files: "
            + hash_process.stderr.decode(errors="replace").strip()
        )
    worktree_ids = hash_process.stdout.decode().splitlines()
    tree_ids = [object_id for _logical, object_id, _size in tree]
    if worktree_ids != tree_ids:
        mismatch = next(
            (
                logical
                for logical, expected, actual in zip(tree_paths, tree_ids, worktree_ids)
                if expected != actual
            ),
            "<unknown>",
        )
        raise ChainError(
            f"enumerated worktree record differs from source Git tree: {mismatch}"
        )


def _verify_enumeration(
    records: Path, genesis: dict[str, Any], cutover: dict[str, Any]
) -> None:
    reference = genesis.get("legacyEnumeration")
    commitments = cutover.get("genesisCommitments")
    if not isinstance(reference, dict) or not isinstance(commitments, dict):
        raise ChainError("enumeration cutover lacks genesis commitments")
    reference_path = reference.get("path")
    if CODE_PINNED_GENESIS_ENUMERATIONS.get(str(reference_path)) != reference:
        raise ChainError(
            "genesis enumeration is not independently pinned by verifier code"
        )
    committed = commitments.get("legacyEnumeration")
    if committed != reference:
        raise ChainError("cutover legacy enumeration commitment differs from genesis")
    enumeration_path = physical_path(records, str(reference.get("path", "")))
    if not enumeration_path.is_file() or enumeration_path.is_symlink():
        raise ChainError(f"committed genesis enumeration is absent: {enumeration_path}")
    raw = enumeration_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference.get("sha256"):
        raise ChainError("genesis enumeration raw SHA-256 mismatch")
    if len(raw) != reference.get("size"):
        raise ChainError("genesis enumeration size mismatch")
    enumeration = load_json(enumeration_path)
    if enumeration_path.read_bytes() != canonical_bytes(enumeration):
        raise ChainError("genesis enumeration is not canonical JSON")
    if canonical_sha256(enumeration) != reference.get("canonicalJsonSha256"):
        raise ChainError("genesis enumeration canonical SHA-256 mismatch")
    if enumeration.get("schemaVersion") != "thesis_legacy_record_enumeration_v1":
        raise ChainError("unsupported genesis enumeration schema")
    if enumeration.get("sourceCommit") != reference.get("sourceCommit"):
        raise ChainError("genesis enumeration source commit mismatch")
    entries = enumeration.get("entries")
    if not isinstance(entries, list) or len(entries) != reference.get("entryCount"):
        raise ChainError("genesis enumeration entry count mismatch")
    if enumeration.get("entryCount") != len(entries):
        raise ChainError("genesis enumeration self-declared entry count mismatch")
    previous_path = ""
    listed: set[str] = set()
    total_size = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size"}:
            raise ChainError("invalid genesis enumeration entry")
        logical = entry.get("path")
        digest = entry.get("sha256")
        size = entry.get("size")
        if not isinstance(logical, str) or not logical.startswith("records/"):
            raise ChainError(f"invalid genesis enumeration path: {logical!r}")
        if logical <= previous_path or logical in listed:
            raise ChainError(
                "genesis enumeration paths are not strictly sorted and unique"
            )
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ChainError(f"invalid genesis enumeration hash for {logical}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ChainError(f"invalid genesis enumeration size for {logical}")
        path = physical_path(records, logical)
        if not path.is_file() or path.is_symlink():
            raise ChainError(f"enumerated legacy record is missing: {logical}")
        raw_file = path.read_bytes()
        if len(raw_file) != size:
            raise ChainError(
                f"enumerated legacy record size mismatch for {logical}: "
                f"expected {size}, got {len(raw_file)}"
            )
        actual = hashlib.sha256(raw_file).hexdigest()
        if actual != digest:
            raise ChainError(
                f"enumerated legacy record hash mismatch for {logical}: "
                f"expected {digest}, got {actual}"
            )
        listed.add(logical)
        previous_path = logical
        total_size += size
    if total_size != enumeration.get("totalSize") or total_size != reference.get(
        "totalSize"
    ):
        raise ChainError("genesis enumeration total size mismatch")
    _verify_enumeration_against_git(
        records, str(enumeration.get("sourceCommit", "")), entries
    )

    genesis_commitment = commitments.get("chainGenesis")
    if not isinstance(genesis_commitment, dict):
        raise ChainError("cutover lacks CHAIN_GENESIS commitment")
    genesis_path = records / "CHAIN_GENESIS.json"
    if genesis_commitment != {
        "path": "records/CHAIN_GENESIS.json",
        "sha256": sha256_file(genesis_path),
        "size": genesis_path.stat().st_size,
        "canonicalJsonSha256": canonical_sha256(genesis),
    }:
        raise ChainError("cutover CHAIN_GENESIS commitment mismatch")

    trust_reference = genesis.get("tsaTrustBundle")
    trust_commitment = commitments.get("tsaTrustBundle")
    if not isinstance(trust_reference, dict) or trust_commitment != trust_reference:
        raise ChainError("cutover TSA trust-bundle commitment mismatch")
    _load_trust_bundle(records, trust_reference)

    legacy_entries = genesis.get("legacyDigests")
    if not isinstance(legacy_entries, list):
        raise ChainError("genesis legacyDigests must be a list")
    enumeration_by_path = {entry["path"]: entry for entry in entries}
    for entry in legacy_entries:
        if not isinstance(entry, dict):
            raise ChainError("legacy digest entry must be an object")
        enumerated = enumeration_by_path.get(entry.get("path"))
        if not enumerated or enumerated["sha256"] != entry.get("sha256"):
            raise ChainError(
                "legacy digest is not identically committed by the full "
                f"enumeration: {entry.get('path')}"
            )


def verify_chain(
    records: Path,
    *,
    now: datetime | None = None,
    allow_pre_enumeration: bool = False,
    bootstrap_trust_bundle: dict[str, Any] | None = None,
    pending_snapshot: Path | None = None,
) -> ChainVerification:
    records = records.resolve()
    pending_snapshot = pending_snapshot.resolve() if pending_snapshot else None
    genesis_path = records / "CHAIN_GENESIS.json"
    if not genesis_path.is_file():
        raise ChainError(f"missing chain genesis: {genesis_path}")
    genesis = load_json(genesis_path)
    if genesis.get("schemaVersion") != "thesis_record_chain_genesis_v1":
        raise ChainError(
            f"unsupported genesis schema: {genesis.get('schemaVersion')!r}"
        )
    if not allow_pre_enumeration and (
        "legacyEnumeration" not in genesis
        or "enumerationCutoverSnapshot" not in genesis
    ):
        raise ChainError(
            "chain lacks the mandatory complete genesis enumeration cutover"
        )

    legacy_entries = genesis.get("legacyDigests")
    if not isinstance(legacy_entries, list):
        raise ChainError("genesis legacyDigests must be a list")
    listed_legacy: set[str] = set()
    for entry in legacy_entries:
        if not isinstance(entry, dict):
            raise ChainError("legacy digest entry must be an object")
        logical = str(entry.get("path"))
        if logical in listed_legacy:
            raise ChainError(f"duplicate legacy digest in genesis: {logical}")
        listed_legacy.add(logical)
        path = physical_path(records, logical)
        if not path.is_file():
            raise ChainError(f"genesis-listed legacy digest is missing: {logical}")
        actual = sha256_file(path)
        if actual != entry.get("sha256"):
            raise ChainError(
                f"legacy digest hash mismatch for {logical}: "
                f"expected {entry.get('sha256')}, got {actual}"
            )
    discovered_legacy = {
        logical_path(records, path) for path in records.glob("????-??-??/digest.json")
    }
    if discovered_legacy != listed_legacy:
        raise ChainError(
            "legacy digest enumeration mismatch: "
            f"unlisted={sorted(discovered_legacy - listed_legacy)}, "
            f"missing={sorted(listed_legacy - discovered_legacy)}"
        )

    snapshots = snapshot_paths(records)
    for path in snapshots:
        ensure_regular_records_file(
            records,
            path,
            message=(
                "missing or non-regular record snapshot: "
                f"{logical_path(records, path)}"
            ),
        )
    first_logical = genesis.get("firstSnapshot")
    if not isinstance(first_logical, str) or not first_logical:
        raise ChainError("genesis firstSnapshot must name one snapshot")
    first = physical_path(records, first_logical)
    if first not in snapshots:
        raise ChainError(f"genesis snapshot is missing or malformed: {first_logical}")

    snapshot_set = set(snapshots)
    successors: dict[Path, list[Path]] = {path: [] for path in snapshots}
    payloads: dict[Path, dict[str, Any]] = {}
    for path in snapshots:
        payload = load_json(path)
        payloads[path] = payload
        if payload.get("schemaVersion") != "thesis_record_snapshot_v2":
            raise ChainError(f"unsupported snapshot schema in {path}")
        _creation_claims(payload)
        chain = payload.get("chain")
        if path == first:
            if chain is not None:
                raise ChainError(
                    f"genesis snapshot must not have a chain block: {path}"
                )
        else:
            if not isinstance(chain, dict):
                raise ChainError(f"missing chain block after genesis: {path}")
            previous_logical = chain.get("prevDigestPath")
            if not isinstance(previous_logical, str):
                raise ChainError(f"missing chain.prevDigestPath in {path}")
            previous = physical_path(records, previous_logical)
            if previous not in snapshot_set:
                raise ChainError(f"missing predecessor for {path}: {previous_logical}")
            expected_sha = sha256_file(previous)
            if chain.get("prevDigestSha256") != expected_sha:
                raise ChainError(
                    f"predecessor hash mismatch in {path}: expected {expected_sha}, "
                    f"got {chain.get('prevDigestSha256')}"
                )
            successors[previous].append(path)
    ordered = [first]
    visited = {first}
    cursor = first
    while successors[cursor]:
        children = successors[cursor]
        if len(children) != 1:
            raise ChainError(
                f"fork after {logical_path(records, cursor)}: "
                + ", ".join(logical_path(records, child) for child in children)
            )
        cursor = children[0]
        if cursor in visited:
            raise ChainError(f"cycle at {logical_path(records, cursor)}")
        visited.add(cursor)
        ordered.append(cursor)
    if visited != snapshot_set:
        raise ChainError(
            "orphaned snapshot(s) not reachable from genesis: "
            + ", ".join(
                logical_path(records, path) for path in sorted(snapshot_set - visited)
            )
        )
    _verify_producer_signatures(records, ordered)
    verified_order = ordered
    if pending_snapshot is not None:
        if pending_snapshot != ordered[-1] or len(ordered) < 2:
            raise ChainError(
                "pending snapshot must be the unique uncommitted chain tail"
            )
        if pending_snapshot.with_suffix(".witness.json").exists():
            raise ChainError("pending snapshot already has a witness marker")
        _trust_bundle_updates(records, payloads[pending_snapshot])
        verified_order = ordered[:-1]

    commitment_snapshots = [
        path for path in ordered if "genesisCommitments" in payloads[path]
    ]
    cutover_kind_snapshots = [
        path
        for path in ordered
        if payloads[path].get("snapshotKind") == "genesis_enumeration_cutover"
    ]
    if len(commitment_snapshots) > 1 or len(cutover_kind_snapshots) > 1:
        raise ChainError("record chain contains more than one genesis cutover")
    if commitment_snapshots != cutover_kind_snapshots:
        raise ChainError(
            "genesisCommitments may appear only on the unique enumeration cutover"
        )

    if bootstrap_trust_bundle is not None:
        if not allow_pre_enumeration or "tsaTrustBundle" in genesis:
            raise ChainError(
                "explicit trust bootstrap is only allowed for a pre-enumeration chain"
            )
        bundle_path, _bundle = _load_trust_bundle(records, bootstrap_trust_bundle)
        active_bundles = {logical_path(records, bundle_path): bootstrap_trust_bundle}
    else:
        active_bundles = _bootstrap_trust_bundles(
            records,
            genesis,
            required=not allow_pre_enumeration or "tsaTrustBundle" in genesis,
        )
    pending_updates: list[dict[str, Any]] = []
    witnesses: dict[Path, WitnessEvidence] = {}
    for path in verified_order:
        current_updates = _trust_bundle_updates(records, payloads[path])
        evidence = verify_witness(
            path,
            records=records,
            now=now,
            trusted_bundles=active_bundles,
            transition_bundle_updates=[*pending_updates, *current_updates],
        )
        witnesses[path] = evidence
        pending_updates.extend(current_updates)
        # A trust-set transition becomes authoritative only after an external
        # witness made with an already-active bundle covers the transition.
        # Therefore a snapshot can never bootstrap the bundle used by its own
        # token; unavailable markers leave updates pending for a later old-key
        # witness.
        if evidence.status == "available":
            _activate_trust_bundles(active_bundles, pending_updates)
            pending_updates.clear()

    cutover_logical = genesis.get("enumerationCutoverSnapshot")
    cutover_path: Path | None = None
    if "legacyEnumeration" in genesis or cutover_logical is not None:
        if not isinstance(cutover_logical, str):
            raise ChainError("genesis enumeration cutover path is missing")
        cutover_path = physical_path(records, cutover_logical)
        if cutover_path not in visited:
            raise ChainError(
                "genesis enumeration cutover is absent from the reachable chain"
            )
        if payloads[cutover_path].get("snapshotKind") != "genesis_enumeration_cutover":
            raise ChainError(
                "named genesis enumeration cutover has the wrong snapshot kind"
            )
        if commitment_snapshots != [cutover_path]:
            raise ChainError(
                "named genesis enumeration cutover is not the unique committed cutover"
            )
        _verify_enumeration(records, genesis, payloads[cutover_path])
        legacy_tip = payloads[first].get("legacyTip")
        if not isinstance(legacy_tip, dict) or legacy_tip != legacy_entries[-1]:
            raise ChainError(
                "first chained snapshot legacyTip differs from CHAIN_GENESIS"
            )
        first_dependencies = payloads[first].get("dependencies")
        recorder_commit = (
            first_dependencies.get("recorderRepositoryCommit")
            if isinstance(first_dependencies, dict)
            else None
        )
        source_commit = genesis["legacyEnumeration"].get("sourceCommit")
        if source_commit != recorder_commit:
            raise ChainError(
                "genesis enumeration source commit differs from the first "
                "snapshot recorderRepositoryCommit"
            )
    elif not allow_pre_enumeration:
        raise ChainError(
            "chain lacks the mandatory complete genesis enumeration cutover"
        )

    head_path = records / "CHAIN_HEAD.json"
    if not head_path.is_file():
        raise ChainError(f"missing chain head commitment: {head_path}")
    head = load_json(head_path)
    if head.get("schemaVersion") != "thesis_record_chain_head_v1":
        raise ChainError(
            f"unsupported chain head schema: {head.get('schemaVersion')!r}"
        )
    expected_head_path = logical_path(records, verified_order[-1])
    expected_head_sha = sha256_file(verified_order[-1])
    if head.get("snapshotPath") != expected_head_path:
        raise ChainError(
            f"chain head path mismatch: expected {expected_head_path}, "
            f"got {head.get('snapshotPath')}"
        )
    if head.get("snapshotSha256") != expected_head_sha:
        raise ChainError(
            f"chain head hash mismatch: expected {expected_head_sha}, "
            f"got {head.get('snapshotSha256')}"
        )
    return ChainVerification(
        ordered=tuple(verified_order),
        witnesses=witnesses,
        enumeration_cutover=cutover_path,
        active_trust_bundles={
            path: dict(reference) for path, reference in active_bundles.items()
        },
        pending_trust_bundle_updates=tuple(
            dict(reference) for reference in pending_updates
        ),
    )


def verify_records(
    records: Path,
    *,
    now: datetime | None = None,
    allow_pre_enumeration: bool = False,
) -> list[Path]:
    """Compatibility wrapper returning the ordered snapshot paths."""

    return list(
        verify_chain(
            records,
            now=now,
            allow_pre_enumeration=allow_pre_enumeration,
        ).ordered
    )


def main() -> int:
    records = Path(sys.argv[1] if len(sys.argv) > 1 else "records")
    try:
        verification = verify_chain(records)
    except ChainError as exc:
        print(f"CHAIN BROKEN: {exc}", file=sys.stderr)
        return 1
    available = [
        (path, evidence)
        for path, evidence in verification.witnesses.items()
        if evidence.status == "available"
    ]
    for path, evidence in available:
        anchors = ",".join(token.anchor_id for token in evidence.tokens)
        policies = ",".join(token.policy_oid for token in evidence.tokens)
        print(
            "witness OK: "
            f"{logical_path(records.resolve(), path)} genTime={evidence.gen_time} "
            f"policies={policies} anchors={anchors}"
        )
    active_bundle_ids = sorted(
        str(reference["bundleId"])
        for reference in verification.active_trust_bundles.values()
    )
    pending_bundle_ids = sorted(
        str(reference["bundleId"])
        for reference in verification.pending_trust_bundle_updates
    )
    print(
        f"chain OK: {len(verification.ordered)} snapshot(s), "
        f"availableWitnesses={len(available)}, "
        f"activeTrustBundles={active_bundle_ids}, "
        f"pendingTrustBundles={pending_bundle_ids}, "
        f"head={verification.ordered[-1]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
