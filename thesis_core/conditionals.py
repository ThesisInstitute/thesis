"""Append-only exploratory paired attempts, isolated from scientific scoring."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import timedelta, timezone
from typing import Literal

from fastapi import Request

from .artifacts import ArtifactError
from .canonical import canonical_bytes, canonical_sha256
from .conditional_contracts import (
    ConditionalArtifact,
    ConditionalAttempt,
    ConditionalContract,
    PairedModelResponse,
    contract_id,
    shared_evidence_id,
    validate_response,
)
from .contracts import ArtifactRef, FrozenModel, Sha256
from .security import RedactionError, redact_response_text, redact_stream_text

LOGGER = logging.getLogger(__name__)

ERROR_CODES = frozenset(
    (
        "spawn_failed",
        "timeout",
        "output_too_large",
        "nonzero_exit",
        "missing_response",
        "invalid_response",
        "unsafe_output",
        "interrupted",
        "lease_expired",
    )
)


class ConditionalResult(FrozenModel):
    attempt_id: Sha256
    execution_state: Literal["succeeded", "failed", "unknown"]
    response: PairedModelResponse | None
    error_code: str | None
    artifacts: tuple[ConditionalArtifact, ...]


def _json(model):
    return canonical_bytes(model.model_dump(mode="json", by_alias=True))


def _archive(store, role, raw, media_type="application/json"):
    digest = store.artifacts.put_bytes(raw)
    return ConditionalArtifact(
        role=role,
        artifact=ArtifactRef(sha256=digest, bytes=len(raw), media_type=media_type),
    )


def _check_artifact(store, artifact):
    if len(store.artifacts.read_bytes(artifact.sha256)) != artifact.bytes:
        raise ValueError("conditional artifact size mismatch")


def _timestamp(value):
    return (
        value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if value
        else None
    )


def start_attempt(
    store,
    contract: ConditionalContract,
    *,
    prompt: bytes,
    command: bytes,
    code: bytes,
    requested_model: str,
    timeout_seconds: int = 600,
) -> ConditionalAttempt:
    """Commit durable dispatch before the caller invokes any model."""
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
        raise ValueError("conditional timeout must be 1..600 seconds")
    for source in contract.sources:
        _check_artifact(store, source.artifact)
    artifacts = [_archive(store, "contract", _json(contract))]
    for role, raw in (("prompt", prompt), ("command", command)):
        redacted = redact_stream_text(raw.decode("utf-8"))
        if redacted.encode() != raw:
            raise ValueError("conditional inputs contain unsafe public content")
        artifacts.append(_archive(store, role, raw, "text/plain"))
    # The runner assembles these bytes from the public installed package.
    # Redacting source literals would break the exact code identity.
    artifacts.append(_archive(store, "code", code, "text/plain"))
    with store.connection() as connection:
        now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        expires = now + timedelta(seconds=timeout_seconds)
        if contract.condition_deadline <= expires:
            raise ValueError("conditional execution reaches its condition deadline")
        if any(source.retrieved_at > now for source in contract.sources):
            raise ValueError("conditional source capture is in the future")
        identity = canonical_sha256(
            {
                "nonce": uuid.uuid4().hex,
                "contract_id": contract_id(contract),
                "started_at": _timestamp(now),
            }
        )
        attempt = ConditionalAttempt(
            id=identity,
            contract_id=contract_id(contract),
            shared_evidence_id=shared_evidence_id(contract),
            requested_model=requested_model,
            started_at=now,
            expires_at=expires,
            artifacts=tuple(artifacts),
        )
        digest = store.artifacts.put_bytes(_json(attempt))
        connection.execute(
            "INSERT INTO "
            "conditional_attempts(id,contract_id,attempt_hash,started_at,expires_at) "
            "VALUES (%s,%s,%s,%s,%s)",
            (identity, attempt.contract_id, digest, now, expires),
        )
    return attempt


def _load(store, row):
    attempt = ConditionalAttempt.model_validate_json(
        store.artifacts.read_bytes(row["attempt_hash"])
    )
    if (
        attempt.id != row["id"]
        or attempt.contract_id != row["contract_id"]
        or attempt.started_at != row["started_at"]
        or attempt.expires_at != row["expires_at"]
    ):
        raise ValueError("conditional attempt index disagrees with frozen content")
    contract = ConditionalContract.model_validate_json(
        store.artifacts.read_bytes(attempt.contract_id)
    )
    if (
        contract_id(contract) != attempt.contract_id
        or shared_evidence_id(contract) != attempt.shared_evidence_id
    ):
        raise ValueError("conditional frozen contract identity mismatch")
    for source in contract.sources:
        _check_artifact(store, source.artifact)
    for item in attempt.artifacts:
        _check_artifact(store, item.artifact)
    return attempt, contract


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError("nonfinite JSON number")


def finish_attempt(
    store,
    attempt_id: str,
    *,
    stdout: bytes,
    stderr: bytes,
    response: bytes | None,
    error_code: str | None = None,
):
    """Seal exactly one complete success/failure; never replace or retry."""
    if error_code is not None and error_code not in ERROR_CODES - {"lease_expired"}:
        raise ValueError("unknown conditional error code")
    with store.connection() as connection:
        row = connection.execute(
            "SELECT * FROM conditional_attempts WHERE id=%s FOR UPDATE", (attempt_id,)
        ).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        if connection.execute(
            "SELECT 1 FROM conditional_results WHERE attempt_id=%s", (attempt_id,)
        ).fetchone():
            raise ValueError("conditional attempt is already terminal")
        attempt, contract = _load(store, row)
        artifacts = []
        parsed = None
        for role, raw in (
            ("stdout", stdout),
            ("stderr", stderr),
            ("response", response),
        ):
            if raw is None:
                continue
            try:
                text = raw.decode("utf-8")
                safe = (
                    redact_response_text if role == "response" else redact_stream_text
                )(text)
            except (UnicodeDecodeError, RedactionError):
                error_code = "unsafe_output"
                safe = "Output could not be safely archived."
            artifacts.append(_archive(store, role, safe.encode(), "text/plain"))
            if role == "response" and error_code is None:
                try:
                    payload = json.loads(
                        safe, object_pairs_hook=_unique, parse_constant=_nonfinite
                    )
                    parsed = PairedModelResponse.model_validate_json(
                        json.dumps(payload)
                    )
                    validate_response(contract, parsed)
                except (ValueError, TypeError):
                    error_code = "invalid_response"
        if parsed is None and error_code is None:
            error_code = "missing_response"
        now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        expired = now >= attempt.expires_at or now >= contract.condition_deadline
        if expired:
            error_code = "lease_expired"
        if error_code:
            parsed = None
        artifacts.append(
            _archive(
                store,
                "validation",
                canonical_bytes(
                    {"valid": error_code is None, "error_code": error_code}
                ),
            )
        )
        result = ConditionalResult(
            attempt_id=attempt_id,
            execution_state="unknown"
            if expired
            else "failed"
            if error_code
            else "succeeded",
            response=parsed,
            error_code=error_code,
            artifacts=tuple(artifacts),
        )
        digest = store.artifacts.put_bytes(_json(result))
        connection.execute(
            "INSERT INTO conditional_results(attempt_id,result_hash,execution_state) "
            "VALUES (%s,%s,%s)",
            (attempt_id, digest, result.execution_state),
        )
    return conditional_detail(store, attempt_id)


def recover_attempts(store) -> int:
    """Close expired dispatches independently; corruption never masks other work."""
    with store.connection() as connection:
        candidates = connection.execute(
            "SELECT a.id FROM conditional_attempts a WHERE a.expires_at <= "
            "clock_timestamp() AND NOT EXISTS (SELECT 1 FROM conditional_results r "
            "WHERE r.attempt_id=a.id) ORDER BY a.id"
        ).fetchall()
    recovered = 0
    for candidate in candidates:
        try:
            with store.connection() as connection:
                row = connection.execute(
                    "SELECT a.* FROM conditional_attempts a WHERE a.id=%s AND "
                    "a.expires_at <= clock_timestamp() AND NOT EXISTS (SELECT 1 "
                    "FROM conditional_results r WHERE r.attempt_id=a.id) "
                    "FOR UPDATE OF a SKIP LOCKED",
                    (candidate["id"],),
                ).fetchone()
                if row is None:
                    continue
                _load(store, row)
                result = ConditionalResult(
                    attempt_id=row["id"],
                    execution_state="unknown",
                    response=None,
                    error_code="lease_expired",
                    artifacts=(),
                )
                digest = store.artifacts.put_bytes(_json(result))
                connection.execute(
                    "INSERT INTO conditional_results "
                    "(attempt_id,result_hash,execution_state) "
                    "VALUES (%s,%s,'unknown')",
                    (row["id"], digest),
                )
            recovered += 1
        except (ArtifactError, ValueError):
            # The DB constrains this identity to exactly 64 hexadecimal bytes.
            # Exception details may contain unsafe raw artifact content.
            LOGGER.warning(
                "Conditional recovery skipped %s due to artifact integrity failure",
                candidate["id"],
            )
    return recovered


def conditional_detail(store, identity):
    from .lab import display_quantiles
    from .lab_contracts import ConditionalDetail

    with store.connection() as connection:
        row = connection.execute(
            "SELECT a.*, "
            "r.result_hash,r.execution_state,r.finished_at,clock_timestamp() AS now "
            "FROM conditional_attempts a LEFT JOIN conditional_results r ON "
            "r.attempt_id=a.id WHERE a.id=%s",
            (identity,),
        ).fetchone()
    if row is None:
        raise KeyError(identity)
    attempt, contract = _load(store, row)
    state, error, parsed = "running", None, None
    result = None
    artifacts = list(attempt.artifacts)
    if row["result_hash"]:
        result = ConditionalResult.model_validate_json(
            store.artifacts.read_bytes(row["result_hash"])
        )
        if (
            result.attempt_id != identity
            or result.execution_state != row["execution_state"]
        ):
            raise ValueError("conditional result index disagrees with frozen content")
        state, error, parsed = (
            result.execution_state,
            result.error_code,
            result.response,
        )
        if (state == "succeeded") != (parsed is not None) or (state == "succeeded") != (
            error is None
        ):
            raise ValueError("conditional result is inconsistent")
        if parsed:
            validate_response(contract, parsed)
        artifacts.extend(result.artifacts)
    elif row["now"] >= attempt.expires_at:
        state, error = "unknown", "lease_expired"
    links = []
    artifacts.extend(
        ConditionalArtifact(role="source:" + source.id, artifact=source.artifact)
        for source in contract.sources
    )
    artifacts.append(
        ConditionalArtifact(
            role="attempt",
            artifact=ArtifactRef(
                sha256=row["attempt_hash"],
                bytes=len(store.artifacts.read_bytes(row["attempt_hash"])),
                media_type="application/json",
            ),
        )
    )
    if row["result_hash"]:
        artifacts.append(
            ConditionalArtifact(
                role="result",
                artifact=ArtifactRef(
                    sha256=row["result_hash"],
                    bytes=len(store.artifacts.read_bytes(row["result_hash"])),
                    media_type="application/json",
                ),
            )
        )
    for item in artifacts:
        _check_artifact(store, item.artifact)
        links.append(
            dict(
                sha256=item.artifact.sha256,
                bytes=item.artifact.bytes,
                media_type=item.artifact.media_type,
                role=item.role,
                download_path="/artifacts/" + item.artifact.sha256,
            )
        )
    from .conditional_reviews import provider_metadata, review_views, revision_history

    return ConditionalDetail(
        schema_version="thesis_lab_v1",
        generated_at=_timestamp(row["now"]),
        id=identity,
        title=contract.title,
        question=contract.question,
        unit=contract.outcome.unit,
        measurement_period=contract.outcome.measurement_period,
        requested_model=attempt.requested_model,
        provider_metadata=provider_metadata(store, attempt, result),
        reviews=review_views(store, identity),
        revision_history=revision_history(store, identity),
        execution_state=state,
        started_at=_timestamp(attempt.started_at),
        finished_at=_timestamp(row["finished_at"]),
        error_code=error,
        contract_id=attempt.contract_id,
        shared_evidence_id=attempt.shared_evidence_id,
        contract=contract,
        response=parsed,
        reference_quantiles=display_quantiles(parsed.reference) if parsed else None,
        arm_quantiles=tuple(display_quantiles(arm.distribution) for arm in parsed.arms)
        if parsed
        else (),
        artifacts=tuple(links),
        expires_at=_timestamp(attempt.expires_at),
    )


def valid_requested_model(value):
    import re

    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", value) is not None
    )


def conditional_page(store, *, limit=20, after=None, requested_model=None):
    from .lab_contracts import ConditionalPage, ConditionalSummary

    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("conditional page limit must be 1..100")
    if requested_model is not None and not valid_requested_model(requested_model):
        raise ValueError("invalid requested model filter")
    with store.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM conditional_attempts ORDER BY id"
        ).fetchall()
        now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    # Model labels live in the immutable attempt artifacts. Inspect their small
    # manifests across the collection so filtering precedes pagination.
    indexed = []
    models = set()
    for row in rows:
        attempt = ConditionalAttempt.model_validate_json(
            store.artifacts.read_bytes(row["attempt_hash"])
        )
        if attempt.id != row["id"] or attempt.contract_id != row["contract_id"]:
            raise ValueError("conditional model index disagrees with frozen content")
        models.add(attempt.requested_model)
        if requested_model is None or attempt.requested_model == requested_model:
            indexed.append(row["id"])
    total = len(indexed)
    remaining = [identity for identity in indexed if after is None or identity > after]
    items = []
    for identity in remaining[:limit]:
        detail = conditional_detail(store, identity)
        items.append(
            ConditionalSummary.model_validate(
                {
                    name: getattr(detail, name)
                    for name in ConditionalSummary.model_fields
                }
            )
        )
    return ConditionalPage(
        schema_version="thesis_lab_v1",
        generated_at=_timestamp(now),
        items=items,
        total=total,
        requested_models=sorted(models),
        next_cursor=remaining[limit - 1] if len(remaining) > limit else None,
    )


def mount_routes(application, current_store):
    from fastapi import HTTPException

    from .lab_contracts import ConditionalDetail, ConditionalPage

    def options(request):
        import re

        pairs = list(request.query_params.multi_items())
        if len({key for key, _ in pairs}) != len(pairs) or any(
            key not in ("limit", "after", "requested_model") for key, _ in pairs
        ):
            raise HTTPException(422, detail={"code": "invalid_request"})
        after = request.query_params.get("after")
        limit = request.query_params.get("limit", "20")
        if (
            not re.fullmatch(r"[1-9][0-9]{0,2}", limit)
            or int(limit) > 100
            or (after is not None and not re.fullmatch(r"[0-9a-f]{64}", after))
        ):
            raise HTTPException(422, detail={"code": "invalid_request"})
        requested_model = request.query_params.get("requested_model")
        if requested_model is not None and not valid_requested_model(requested_model):
            raise HTTPException(422, detail={"code": "invalid_request"})
        return dict(limit=int(limit), after=after, requested_model=requested_model)

    @application.get("/lab/conditionals", response_model=ConditionalPage)
    def page(request: Request):
        return conditional_page(current_store(), **options(request))

    @application.get("/lab/conditionals/{attempt_id}", response_model=ConditionalDetail)
    def detail(attempt_id: str, request: Request):
        import re

        if request.query_params or not re.fullmatch(r"[0-9a-f]{64}", attempt_id):
            raise HTTPException(422, detail={"code": "invalid_request"})
        return conditional_detail(current_store(), attempt_id)
