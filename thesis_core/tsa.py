#!/usr/bin/env python3
"""Standalone RFC 3161 timestamping against this repository's pinned anchors.

This module is the public timestamp adapter for Thesis core.  It depends on
the standard library and :mod:`thesis_core.record_chain` only, so it can be
imported without Pydantic, a database driver, an HTTP framework or a records
checkout.

Two entry points:

``request_and_verify(subject, recorded_at, *, anchor_id=...)``
    Builds a real OpenSSL RFC 3161 query over ``subject``, POSTs it to the
    endpoint that the code-pinned trust bundle names for ``anchor_id``, and
    verifies the reply against the same pinned root, signer identities,
    policy OIDs and time rules the record-chain verifier enforces.

``verify_receipt(subject, response, *, anchor_id=...)``
    Replays an archived reply offline against those same pins.  Given the
    raw subject bytes and the raw response bytes, anybody can reproduce the
    verification without network access and without this repository's
    records tree.

Both return a :class:`VerifiedReceipt` carrying the request and response
bytes, the verified token evidence, and the signed accuracy.  A failure
raises :class:`TsaError`, which carries the same bytes so a failed attempt
can be archived as faithfully as a successful one.

What this module deliberately does not do: it never writes to ``records/``,
never decides publication eligibility, and never invents a verification
result.  There is no ``verified`` flag to set and no way to inject a trust
root -- the accepted anchors come from
:data:`thesis_core.record_chain.CODE_PINNED_TRUST_BUNDLES` and the packaged
copies of the public trust assets, and a packaged copy that disagrees with
the code pin fails closed.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import json
import os
import tempfile
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from thesis_core import record_chain
from thesis_core.record_chain import ChainError, TokenEvidence, TstInfo

UTC = timezone.utc

#: Public trust assets shipped inside the distribution, byte-for-byte copies
#: of ``records/trust/``.  Patched only by tests, which supply synthetic
#: roots; no shipped configuration ever names a test root.
TRUST_ASSET_DIR = Path(__file__).resolve().parent / "trust"
TRUST_LOGICAL_PREFIX = "records/trust/"
TRUST_BUNDLE_LOGICAL_PATH = "records/trust/tsa-anchors-v2.json"
DEFAULT_ANCHOR_ID = "freetsa-root-2016"
DEFAULT_TIMEOUT_SECONDS = 45.0
MAX_RESPONSE_BYTES = 1024 * 1024
ALLOWED_ENDPOINT_SCHEMES = frozenset({"http", "https"})
USER_AGENT = "Thesis-Core-RFC3161/1"

#: Logical directory holding the subject and its token inside the isolated
#: verification layout.  It exists only in a temporary directory; the real
#: ``records/`` tree is never touched.
SUBJECT_LOGICAL_DIR = "witness"
SUBJECT_FILENAME = "subject.json"

#: ``(endpoint, query, timeout_seconds) -> response bytes``
Transport = Callable[[str, bytes, float], bytes]


class TsaError(RuntimeError):
    """A timestamp request or its verification failed.

    ``request_der`` and ``response_der`` carry whatever bytes existed when the
    failure happened, so the caller can archive the evidence of a failed
    attempt exactly as it would archive a successful one.
    """

    def __init__(
        self,
        message: str,
        *,
        anchor_id: str | None = None,
        endpoint: str | None = None,
        request_der: bytes | None = None,
        response_der: bytes | None = None,
    ) -> None:
        super().__init__(message)
        self.anchor_id = anchor_id
        self.endpoint = endpoint
        self.request_der = request_der
        self.response_der = response_der


@dataclass(frozen=True)
class TimestampQuery:
    """The fields of an RFC 3161 ``TimeStampReq`` this module checks."""

    version: int
    imprint_algorithm_oid: str
    hashed_message: bytes
    req_policy_oid: str | None = None
    nonce: int | None = None
    cert_req: bool = False


@dataclass(frozen=True)
class VerifiedReceipt:
    """One RFC 3161 receipt that verified against the pinned trust anchors.

    Everything needed to reproduce the verification is present:
    ``subject_bytes`` plus ``response_der`` replay offline through
    :func:`verify_receipt`, and ``request_der`` (when the receipt was
    obtained by this module) proves which query produced it.
    """

    anchor_id: str
    endpoint: str
    trust_bundle_id: str
    trust_bundle_path: str
    trust_bundle_sha256: str
    subject_sha256: str
    subject_bytes: bytes
    recorded_at: datetime
    response_der: bytes
    token_sha256: str
    evidence: TokenEvidence
    request_der: bytes | None = None
    query: TimestampQuery | None = None

    @property
    def tst_info(self) -> TstInfo:
        """The signed ``TSTInfo`` the pinned CMS verification authenticated."""

        info = self.evidence.tst_info
        if info is None:  # Defended by verify_timestamp_token.
            raise TsaError(
                "verified receipt is missing its parsed TSTInfo",
                anchor_id=self.anchor_id,
                endpoint=self.endpoint,
            )
        return info

    @property
    def gen_time(self) -> datetime:
        """The signed ``genTime``, exactly as the TSA stated it."""

        return self.tst_info.gen_time

    @property
    def gen_time_text(self) -> str:
        """``genTime`` rendered as RFC 3339 UTC."""

        return self.evidence.gen_time

    @property
    def accuracy_micros(self) -> int | None:
        """Signed accuracy in microseconds, or ``None`` when the TSA omitted it.

        Neither pinned anchor emits an ``Accuracy`` field today, so this is
        ``None`` for every currently published receipt.  It is not zero: an
        absent accuracy is an absent statement, and no pinned TSA policy
        supplies a substitute bound.
        """

        return self.tst_info.accuracy_micros

    @property
    def witness_upper_bound(self) -> datetime | None:
        """Latest instant the token can attest to, or ``None`` when unknown.

        RFC 3161 section 2.4.2 makes ``Accuracy`` a symmetric bound around
        ``genTime``; the upper end is ``genTime + seconds + millis + micros``.
        Callers ordering a witness against a deadline must treat ``None`` as
        unknown ordering rather than substituting ``genTime``.
        """

        return self.tst_info.upper_bound

    @property
    def nonce(self) -> int | None:
        """The nonce the TSA echoed, or ``None`` when the token carries none."""

        return self.tst_info.nonce

    @property
    def policy_oid(self) -> str:
        return self.evidence.policy_oid

    @property
    def imprint_algorithm_oid(self) -> str:
        return self.evidence.imprint_algorithm_oid

    @property
    def tsa_subject(self) -> str:
        return self.evidence.tsa_subject

    @property
    def tsa_certificate_sha256(self) -> str:
        return self.evidence.tsa_certificate_sha256

    @property
    def tsa_spki_sha256(self) -> str:
        return self.evidence.tsa_spki_sha256


# --------------------------------------------------------------------------
# Pinned trust configuration
# --------------------------------------------------------------------------


def _asset_source(logical: str) -> Path:
    """Map one ``records/trust/...`` logical path onto its packaged copy."""

    if not logical.startswith(TRUST_LOGICAL_PREFIX):
        raise TsaError(
            f"trust asset is outside the packaged trust directory: {logical!r}"
        )
    relative = Path(logical[len(TRUST_LOGICAL_PREFIX) :])
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise TsaError(f"unsafe trust asset path: {logical!r}")
    return TRUST_ASSET_DIR / relative


def read_trust_asset(logical: str) -> bytes:
    """Return the packaged bytes of one ``records/trust/...`` trust asset.

    A publication proof commits the exact trust configuration it verified
    under, so a verifier needs the bytes, not just the path.
    """

    source = _asset_source(logical)
    try:
        return source.read_bytes()
    except OSError as exc:
        raise TsaError(f"cannot read packaged trust asset {logical}: {exc}") from exc


#: Historic private spelling of :func:`read_trust_asset`, kept because
#: ``thesis_core.publication`` already calls it.
_read_asset = read_trust_asset


def trust_bundle_reference(logical: str | None = None) -> dict[str, Any]:
    """Select the current or recorded bundle exclusively from verifier code pins."""

    logical = TRUST_BUNDLE_LOGICAL_PATH if logical is None else logical
    reference = record_chain.CODE_PINNED_TRUST_BUNDLES.get(logical)
    if reference is None:
        raise TsaError(f"trust bundle is not pinned by verifier code: {logical}")
    return dict(reference)


def _pinned_bundle(
    logical: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the code pin and the parsed packaged bundle that matches it."""

    reference = trust_bundle_reference(logical)
    logical = str(reference["path"])
    raw = read_trust_asset(logical)
    if hashlib.sha256(raw).hexdigest() != reference.get("sha256") or len(
        raw
    ) != reference.get("size"):
        raise TsaError(
            f"packaged TSA trust bundle does not match the verifier code pin: {logical}"
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TsaError(f"packaged TSA trust bundle is not JSON: {logical}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("anchors"), list):
        raise TsaError(f"packaged TSA trust bundle is malformed: {logical}")
    return reference, payload


def anchor_ids() -> tuple[str, ...]:
    """Return every anchor ID the pinned bundle authorizes, in bundle order."""

    _reference, payload = _pinned_bundle()
    return tuple(str(anchor["id"]) for anchor in payload["anchors"])


def anchor(anchor_id: str) -> dict[str, Any]:
    """Return the pinned definition of one anchor, endpoint included."""

    _reference, payload = _pinned_bundle()
    return dict(_select_anchor(payload, anchor_id))


def _select_anchor(payload: dict[str, Any], anchor_id: str) -> dict[str, Any]:
    matches = [
        candidate
        for candidate in payload["anchors"]
        if isinstance(candidate, dict) and candidate.get("id") == anchor_id
    ]
    if len(matches) != 1:
        available = ", ".join(str(item.get("id")) for item in payload["anchors"])
        raise TsaError(
            f"unknown TSA anchor {anchor_id!r}; the pinned bundle allows: {available}",
            anchor_id=anchor_id,
        )
    selected = matches[0]
    endpoint = selected.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        raise TsaError(f"pinned TSA anchor {anchor_id!r} lacks an endpoint")
    scheme = urlsplit(endpoint).scheme
    if scheme not in ALLOWED_ENDPOINT_SCHEMES:
        raise TsaError(
            f"pinned TSA endpoint scheme {scheme!r} is not allowed for {anchor_id!r}",
            anchor_id=anchor_id,
            endpoint=endpoint,
        )
    return selected


# --------------------------------------------------------------------------
# Isolated records layout
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Layout:
    records: Path
    subject_path: Path
    token_path: Path
    token_logical: str


@contextlib.contextmanager
def _isolated_layout(
    subject: bytes, payload: dict[str, Any], anchor_id: str, bundle_path: str
) -> Iterator[_Layout]:
    """Materialize a throwaway records tree holding the packaged trust assets.

    The shared verifier resolves every trust reference relative to a records
    root, so the packaged copies are laid out under their original logical
    paths in a temporary directory.  The real ``records/`` tree is never read
    or written here, which is what makes the verification standalone.
    """

    with tempfile.TemporaryDirectory(prefix="thesis-core-tsa-") as temporary:
        records = Path(temporary) / "records"
        needed = [bundle_path]
        for candidate in payload["anchors"]:
            root = candidate.get("rootCertificate")
            if not isinstance(root, dict) or not isinstance(root.get("path"), str):
                raise TsaError(
                    f"pinned anchor {candidate.get('id')!r} lacks a root certificate"
                )
            needed.append(str(root["path"]))
        for logical in needed:
            destination = records / Path(logical).relative_to("records")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(read_trust_asset(logical))

        subject_directory = records / SUBJECT_LOGICAL_DIR
        subject_directory.mkdir(parents=True, exist_ok=True)
        subject_path = subject_directory / SUBJECT_FILENAME
        subject_path.write_bytes(subject)
        token_path = subject_directory / f"{subject_path.stem}.{anchor_id}.tsr"
        yield _Layout(
            records=records,
            subject_path=subject_path,
            token_path=token_path,
            token_logical=(f"records/{SUBJECT_LOGICAL_DIR}/{token_path.name}"),
        )


# --------------------------------------------------------------------------
# Query construction and parsing
# --------------------------------------------------------------------------


def build_query(subject_path: Path) -> bytes:
    """Build a real OpenSSL RFC 3161 query over one file's exact bytes.

    ``-cert`` asks the TSA to embed its signing certificate, which the pinned
    CMS verification needs; OpenSSL adds a random nonce, which
    :func:`verify_receipt` requires the reply to echo.
    """

    query_path = subject_path.with_name(f"{subject_path.name}.tsq")
    record_chain._run_openssl(
        [
            "ts",
            "-query",
            "-config",
            os.devnull,
            "-data",
            str(subject_path),
            "-sha256",
            "-cert",
            "-out",
            str(query_path),
        ]
    )
    try:
        return query_path.read_bytes()
    finally:
        query_path.unlink(missing_ok=True)


def parse_timestamp_query(data: bytes) -> TimestampQuery:
    """Decode a ``TimeStampReq`` far enough to bind it to a reply."""

    read = record_chain._read_der_tlv
    try:
        tag, sequence, end = read(data, 0)
        if tag != 0x30 or end != len(data):
            raise ChainError("TimeStampReq is not one complete DER sequence")
        offset = 0
        tag, version_bytes, offset = read(sequence, offset)
        if tag != 0x02:
            raise ChainError("TimeStampReq lacks a version")
        version = record_chain._decode_der_integer(version_bytes, "TimeStampReq")
        tag, message_imprint, offset = read(sequence, offset)
        if tag != 0x30:
            raise ChainError("TimeStampReq lacks a message imprint")
        algorithm_oid, hashed_message = record_chain.parse_message_imprint(
            message_imprint
        )

        req_policy_oid: str | None = None
        nonce: int | None = None
        cert_req = False
        if offset < len(sequence):
            tag, content, next_offset = read(sequence, offset)
            if tag == 0x06:
                req_policy_oid = record_chain._decode_oid(content)
                offset = next_offset
        if offset < len(sequence):
            tag, content, next_offset = read(sequence, offset)
            if tag == 0x02:
                nonce = record_chain._decode_der_integer(content, "TimeStampReq nonce")
                offset = next_offset
        if offset < len(sequence):
            tag, content, next_offset = read(sequence, offset)
            if tag == 0x01:
                if len(content) != 1 or content[0] not in {0x00, 0xFF}:
                    raise ChainError("invalid TimeStampReq certReq boolean")
                cert_req = content[0] == 0xFF
                offset = next_offset
        while offset < len(sequence):
            tag, _content, offset = read(sequence, offset)
            if tag != 0xA0:  # extensions [0] IMPLICIT
                raise ChainError(f"unexpected TimeStampReq field tag 0x{tag:02x}")
    except ChainError as exc:
        raise TsaError(f"timestamp query is malformed: {exc}") from exc

    return TimestampQuery(
        version=version,
        imprint_algorithm_oid=record_chain._decode_oid(algorithm_oid),
        hashed_message=hashed_message,
        req_policy_oid=req_policy_oid,
        nonce=nonce,
        cert_req=cert_req,
    )


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse to follow a redirect away from the pinned endpoint.

    A redirect cannot forge a token -- the reply is verified against a pinned
    root either way -- but it would send the subject's digest to a host the
    trust bundle never named.  Returning ``None`` leaves the redirect
    unhandled, so urllib raises instead of hopping.
    """

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def post_timestamp_query(endpoint: str, query: bytes, timeout_seconds: float) -> bytes:
    """POST one query to one endpoint, bounded in time and response size."""

    request = urllib.request.Request(
        endpoint,
        data=query,
        headers={
            "Content-Type": "application/timestamp-query",
            "Accept": "application/timestamp-reply",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    opener = urllib.request.build_opener(_RefuseRedirects)
    with opener.open(request, timeout=timeout_seconds) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if not body:
        raise TsaError("TSA returned an empty response", endpoint=endpoint)
    if len(body) > MAX_RESPONSE_BYTES:
        raise TsaError(
            f"TSA response exceeds {MAX_RESPONSE_BYTES} bytes", endpoint=endpoint
        )
    return body


# --------------------------------------------------------------------------
# Subject claims
# --------------------------------------------------------------------------


def _subject_recorded_at(subject: bytes) -> datetime:
    """Return the subject's own top-level ``recordedAt`` creation claim.

    The shared verifier compares the signed ``genTime`` against exactly this
    claim (and every nested dependency claim), so the subject must be the
    complete JSON object whose bytes are being timestamped.
    """

    try:
        payload = json.loads(subject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TsaError(f"subject is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TsaError("subject must be a JSON object with a top-level recordedAt")
    try:
        return record_chain._parse_rfc3339(payload.get("recordedAt"), "recordedAt")
    except ChainError as exc:
        raise TsaError(f"subject lacks a usable recordedAt: {exc}") from exc


def _require_aware(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TsaError(f"{label} must be a timezone-aware datetime")
    return value.astimezone(UTC)


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------


def _verify_in_layout(
    layout: _Layout,
    *,
    reference: dict[str, Any],
    anchor_definition: dict[str, Any],
    subject: bytes,
    recorded_at: datetime,
    response: bytes,
    request: bytes | None,
    now: datetime | None,
) -> VerifiedReceipt:
    anchor_id = str(anchor_definition["id"])
    endpoint = str(anchor_definition["endpoint"])
    subject_sha256 = hashlib.sha256(subject).hexdigest()
    token_sha256 = hashlib.sha256(response).hexdigest()
    claim = {
        "status": "available",
        "tsa": endpoint,
        "tsaAnchorId": anchor_id,
        "trustBundleId": reference["bundleId"],
        "trustBundlePath": reference["path"],
        "trustBundleSha256": reference["sha256"],
        "tokenPath": layout.token_logical,
        "tokenSha256": token_sha256,
    }
    try:
        evidence = record_chain.verify_timestamp_token(
            layout.subject_path,
            claim,
            reference,
            records=layout.records,
            now=now,
        )
    except ChainError as exc:
        raise TsaError(
            f"pinned RFC 3161 verification failed: {exc}",
            anchor_id=anchor_id,
            endpoint=endpoint,
            request_der=request,
            response_der=response,
        ) from exc

    info = evidence.tst_info
    if info is None:  # Defended by verify_timestamp_token.
        raise TsaError(
            "verified token carries no parsed TSTInfo",
            anchor_id=anchor_id,
            endpoint=endpoint,
            request_der=request,
            response_der=response,
        )
    # ``openssl ts -verify -data`` already bound the imprint to the subject
    # file; restating it here keeps the guarantee visible in this module and
    # independent of that command's option handling.
    if info.hashed_message != hashlib.sha256(subject).digest():
        raise TsaError(
            "RFC 3161 message imprint does not cover the exact subject bytes",
            anchor_id=anchor_id,
            endpoint=endpoint,
            request_der=request,
            response_der=response,
        )

    query: TimestampQuery | None = None
    if request is not None:
        query = parse_timestamp_query(request)
        if query.hashed_message != hashlib.sha256(subject).digest():
            raise TsaError(
                "archived timestamp query does not cover the exact subject bytes",
                anchor_id=anchor_id,
                endpoint=endpoint,
                request_der=request,
                response_der=response,
            )
        if query.nonce is not None and info.nonce != query.nonce:
            raise TsaError(
                "RFC 3161 token does not echo the query nonce: "
                f"expected {query.nonce}, got {info.nonce}",
                anchor_id=anchor_id,
                endpoint=endpoint,
                request_der=request,
                response_der=response,
            )

    return VerifiedReceipt(
        anchor_id=anchor_id,
        endpoint=endpoint,
        trust_bundle_id=str(reference["bundleId"]),
        trust_bundle_path=str(reference["path"]),
        trust_bundle_sha256=str(reference["sha256"]),
        subject_sha256=subject_sha256,
        subject_bytes=subject,
        recorded_at=recorded_at,
        response_der=response,
        token_sha256=token_sha256,
        evidence=evidence,
        request_der=request,
        query=query,
    )


def verify_receipt(
    subject: bytes,
    response: bytes,
    *,
    anchor_id: str = DEFAULT_ANCHOR_ID,
    now: datetime | None = None,
    request: bytes | None = None,
    trust_bundle_path: str | None = None,
) -> VerifiedReceipt:
    """Replay one archived RFC 3161 reply offline against the pinned anchors.

    ``subject`` must be the exact bytes that were timestamped -- a complete
    JSON object carrying a top-level ``recordedAt``.  ``response`` is the raw
    ``TimeStampResp`` as the TSA returned it.  Supplying ``request`` adds two
    checks: the query must cover the same subject digest, and, when the query
    carried a nonce, the token must echo it.

    ``now`` overrides the wall clock the shared verifier compares ``genTime``
    against; it does not relax any pin.

    ``trust_bundle_path`` replays a recorded, still code-pinned bundle after
    the default changes. It never accepts a caller-supplied trust configuration.
    """

    if not isinstance(subject, (bytes, bytearray)) or not subject:
        raise TsaError("subject must be non-empty bytes", anchor_id=anchor_id)
    if not isinstance(response, (bytes, bytearray)) or not response:
        raise TsaError("response must be non-empty bytes", anchor_id=anchor_id)
    subject = bytes(subject)
    response = bytes(response)
    recorded_at = _subject_recorded_at(subject)
    reference, payload = _pinned_bundle(trust_bundle_path)
    anchor_definition = _select_anchor(payload, anchor_id)
    with _isolated_layout(subject, payload, anchor_id, reference["path"]) as layout:
        layout.token_path.write_bytes(response)
        return _verify_in_layout(
            layout,
            reference=reference,
            anchor_definition=anchor_definition,
            subject=subject,
            recorded_at=recorded_at,
            response=response,
            request=None if request is None else bytes(request),
            now=now,
        )


def request_and_verify(
    subject: bytes,
    recorded_at: datetime,
    *,
    anchor_id: str = DEFAULT_ANCHOR_ID,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    now: datetime | None = None,
    transport: Transport | None = None,
) -> VerifiedReceipt:
    """Timestamp ``subject`` at one pinned anchor and verify the reply.

    ``subject`` is the complete canonical JSON payload being witnessed, and
    ``recorded_at`` is the caller's authoritative creation instant.  It must
    equal the subject's own top-level ``recordedAt``; a disagreement means
    the caller and the bytes claim different things, so the request is
    refused before any network call.

    The endpoint is never supplied by the caller: it comes from the anchor
    the code-pinned trust bundle names.  Requests are bounded in time and
    response size and do not follow redirects.

    On failure the raised :class:`TsaError` carries the query and whatever
    response arrived, so the attempt can still be archived.
    """

    if not isinstance(subject, (bytes, bytearray)) or not subject:
        raise TsaError("subject must be non-empty bytes", anchor_id=anchor_id)
    subject = bytes(subject)
    recorded_at = _require_aware(recorded_at, "recorded_at")
    subject_recorded_at = _subject_recorded_at(subject)
    if subject_recorded_at != recorded_at:
        raise TsaError(
            "recorded_at disagrees with the subject's own recordedAt: "
            f"{record_chain._format_utc(recorded_at)} vs "
            f"{record_chain._format_utc(subject_recorded_at)}",
            anchor_id=anchor_id,
        )

    reference, payload = _pinned_bundle()
    anchor_definition = _select_anchor(payload, anchor_id)
    endpoint = str(anchor_definition["endpoint"])
    send = transport if transport is not None else post_timestamp_query

    with _isolated_layout(subject, payload, anchor_id, reference["path"]) as layout:
        query = build_query(layout.subject_path)
        parsed_query = parse_timestamp_query(query)
        if parsed_query.nonce is None:
            raise TsaError(
                "OpenSSL produced a timestamp query without a nonce",
                anchor_id=anchor_id,
                endpoint=endpoint,
                request_der=query,
            )
        try:
            response = send(endpoint, query, timeout_seconds)
        except TsaError as exc:
            exc.anchor_id = exc.anchor_id or anchor_id
            exc.endpoint = exc.endpoint or endpoint
            exc.request_der = exc.request_der or query
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise TsaError(
                f"timestamp request failed: {exc}",
                anchor_id=anchor_id,
                endpoint=endpoint,
                request_der=query,
            ) from exc
        if not isinstance(response, (bytes, bytearray)) or not response:
            raise TsaError(
                "TSA returned an empty response",
                anchor_id=anchor_id,
                endpoint=endpoint,
                request_der=query,
            )
        response = bytes(response)
        if len(response) > MAX_RESPONSE_BYTES:
            raise TsaError(
                f"TSA response exceeds {MAX_RESPONSE_BYTES} bytes",
                anchor_id=anchor_id,
                endpoint=endpoint,
                request_der=query,
                response_der=response,
            )
        layout.token_path.write_bytes(response)
        return _verify_in_layout(
            layout,
            reference=reference,
            anchor_definition=anchor_definition,
            subject=subject,
            recorded_at=recorded_at,
            response=response,
            request=query,
            now=now,
        )
