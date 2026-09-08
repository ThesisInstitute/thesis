"""Verified read projections and append-only source reviews/revision history.

Annotation commit times describe this import, never when a review was authored
or whether it preceded model generation. Forecast bytes are never rewritten.
"""

from __future__ import annotations

import json
import re

from .canonical import canonical_bytes
from .conditional_contracts import PairedModelResponse, validate_response
from .conditional_review_contracts import ConditionalReview, ConditionalRevision
from .contracts import ArtifactRef
from .security import redact_stream_text


def _bytes(model):
    return canonical_bytes(model.model_dump(mode="json", by_alias=True))


def _json(raw):
    from .conditionals import _nonfinite, _unique

    return json.loads(raw, object_pairs_hook=_unique, parse_constant=_nonfinite)


def _gemini_command(raw):
    """Probe legacy commands without imposing the Gemini JSON contract on them."""

    class ObjectPairs(list):
        pass

    marker = "gemini_rest_operator_v1"
    try:
        command = json.loads(raw, object_pairs_hook=ObjectPairs)
    except ValueError:
        # A malformed explicit claim must not silently lose its verification.
        # Decode complete JSON string tokens so escaped markers count too, while
        # a marker merely quoted inside a shell argument is not a field claim.
        text = raw.decode("utf-8", errors="replace")
        if not re.match(r'\s*\{\s*"', text):
            return None
        tokens = list(re.finditer(r'"(?:[^"\\]|\\.)*"', text))
        for key, value in zip(tokens, tokens[1:]):
            if text[key.end() : value.start()].strip() != ":":
                continue
            try:
                claim = (json.loads(key[0]), json.loads(value[0]))
            except ValueError:
                continue
            if claim == ("transport", marker):
                raise ValueError("invalid provider command JSON") from None
        return None
    if not isinstance(command, ObjectPairs) or not any(
        key == "transport" and value == marker for key, value in command
    ):
        return None
    # Preserve all duplicate pairs in the probe: a later non-Gemini transport
    # value cannot hide an earlier Gemini claim from the strict parser.
    return _json(raw)


def _artifact(store, raw, media_type="text/plain"):
    text = raw.decode("utf-8")
    if not text.strip() or redact_stream_text(text).encode() != raw:
        raise ValueError("review artifacts must be nonempty safe public text")
    return ArtifactRef(
        sha256=store.artifacts.put_bytes(raw), bytes=len(raw), media_type=media_type
    )


def _link(store, artifact, role):
    from .conditionals import _check_artifact

    _check_artifact(store, artifact)
    return dict(
        sha256=artifact.sha256,
        bytes=artifact.bytes,
        media_type=artifact.media_type,
        role=role,
        download_path="/artifacts/" + artifact.sha256,
    )


def _record_link(store, identity, role):
    raw = store.artifacts.read_bytes(identity)
    return _link(
        store,
        ArtifactRef(sha256=identity, bytes=len(raw), media_type="application/json"),
        role,
    )


def _bound(store, identity):
    from .conditionals import ConditionalResult, _check_artifact, _load

    with store.connection() as connection:
        row = connection.execute(
            "SELECT "
            "a.*,r.result_hash,r.finished_at,r.execution_state,clock_timestamp() AS "
            "now "
            "FROM conditional_attempts a LEFT JOIN conditional_results r ON "
            "r.attempt_id=a.id WHERE a.id=%s",
            (identity,),
        ).fetchone()
    if row is None:
        raise KeyError(identity)
    attempt, contract = _load(store, row)
    result = None
    if row["result_hash"]:
        result = ConditionalResult.model_validate_json(
            store.artifacts.read_bytes(row["result_hash"])
        )
        if (
            result.attempt_id != identity
            or result.execution_state != row["execution_state"]
        ):
            raise ValueError("conditional annotation attempt/result binding mismatch")
        if (result.execution_state == "succeeded") != (result.response is not None) or (
            result.execution_state == "succeeded"
        ) != (result.error_code is None):
            raise ValueError("conditional annotated result is inconsistent")
        for item in result.artifacts:
            _check_artifact(store, item.artifact)
        if result.response is not None:
            validate_response(contract, result.response)
    return attempt, contract, result, row


def _role(items, role):
    matching = [item.artifact for item in items if item.role == role]
    if len(matching) != 1:
        raise ValueError("conditional artifact role is missing or ambiguous")
    return matching[0]


def response_artifact(store, attempt_id):
    """The exact model text artifact a review must explicitly pin."""
    _, _, result, _ = _bound(store, attempt_id)
    if (
        result is None
        or result.execution_state != "succeeded"
        or result.response is None
    ):
        raise ValueError("source review requires a succeeded response")
    artifact = _role(result.artifacts, "response")
    if (
        PairedModelResponse.model_validate_json(
            store.artifacts.read_bytes(artifact.sha256)
        )
        != result.response
    ):
        raise ValueError("recorded model text differs from its parsed response")
    return artifact


def _validate_review(store, review):
    artifact = response_artifact(store, review.attempt_id)
    if review.response_sha256 != artifact.sha256:
        raise ValueError("review pins a stale or foreign response")
    _, contract, _, _ = _bound(store, review.attempt_id)
    sources = {source.id for source in contract.sources}
    for finding in review.findings:
        if not set(finding.source_ids).issubset(sources):
            raise ValueError("review finding references an unknown source")
    _link(store, review.report, "source_review")


def create_review(
    store,
    *,
    attempt_id,
    expected_response_sha256,
    reviewer,
    report: bytes,
    findings,
    outcome="issues_remaining",
):
    """Append an operator assessment bound to exact existing forecast text."""
    report_artifact = _artifact(store, report, "text/markdown")
    payload = dict(
        attempt_id=attempt_id,
        response_sha256=expected_response_sha256,
        reviewer=reviewer,
        report=report_artifact.model_dump(mode="json"),
        findings=findings,
        outcome=outcome,
    )
    review = ConditionalReview.model_validate_json(json.dumps(payload))
    if redact_stream_text(_bytes(review).decode()).encode() != _bytes(review):
        raise ValueError("review metadata contains unsafe public text")
    _validate_review(store, review)
    digest = store.artifacts.put_bytes(_bytes(review))
    with store.connection() as connection:
        connection.execute(
            "INSERT INTO conditional_reviews(id,attempt_id) VALUES (%s,%s) ON "
            "CONFLICT(id) DO NOTHING",
            (digest, attempt_id),
        )
    return digest


def _read_review(store, identity):
    with store.connection() as connection:
        row = connection.execute(
            "SELECT * FROM conditional_reviews WHERE id=%s", (identity,)
        ).fetchone()
    if row is None:
        raise KeyError(identity)
    raw = store.artifacts.read_bytes(identity)
    review = ConditionalReview.model_validate_json(raw)
    if _bytes(review) != raw or review.attempt_id != row["attempt_id"]:
        raise ValueError("review index disagrees with immutable content")
    _validate_review(store, review)
    return review, row


def review_views(store, attempt_id):
    from .conditionals import _timestamp

    with store.connection() as connection:
        rows = connection.execute(
            "SELECT id FROM conditional_reviews WHERE attempt_id=%s ORDER BY "
            "recorded_at,id",
            (attempt_id,),
        ).fetchall()
    views = []
    for row in rows:
        review, index = _read_review(store, row["id"])
        views.append(
            dict(
                id=row["id"],
                attempt_id=review.attempt_id,
                response_sha256=review.response_sha256,
                recorded_at=_timestamp(index["recorded_at"]),
                reviewer=review.reviewer,
                review_basis=review.review_basis,
                outcome=review.outcome,
                findings=review.findings,
                report=_link(store, review.report, "source_review"),
                record_artifact=_record_link(store, row["id"], "review_record"),
            )
        )
    return tuple(views)


def _validate_revision(store, revision):
    parent, parent_contract, _, parent_row = _bound(store, revision.parent_attempt_id)
    child, child_contract, _, _ = _bound(store, revision.revision_attempt_id)
    if (
        parent.id == child.id
        or parent_row["finished_at"] is None
        or parent_row["finished_at"] >= child.started_at
    ):
        raise ValueError("revision must begin after its parent completed")
    if (
        parent.contract_id != child.contract_id
        or parent.shared_evidence_id != child.shared_evidence_id
        or revision.contract_id != parent.contract_id
        or revision.shared_evidence_id != parent.shared_evidence_id
    ):
        raise ValueError("revision changes the frozen contract or evidence")
    if parent_contract != child_contract:
        raise ValueError("revision contract bytes differ")
    review, _ = _read_review(store, revision.triggering_review_id)
    if review.attempt_id != parent.id:
        raise ValueError("revision trigger review belongs to a different parent")
    _link(store, revision.feedback, "revision_feedback")
    feedback = store.artifacts.read_bytes(revision.feedback.sha256)
    prompt = _role(child.artifacts, "prompt")
    if feedback not in store.artifacts.read_bytes(prompt.sha256):
        raise ValueError("revision feedback is absent from the archived child prompt")


def link_revision(
    store,
    *,
    parent_attempt_id,
    revision_attempt_id,
    triggering_review_id,
    feedback: bytes,
):
    parent, _, _, _ = _bound(store, parent_attempt_id)
    revision = ConditionalRevision(
        parent_attempt_id=parent_attempt_id,
        revision_attempt_id=revision_attempt_id,
        contract_id=parent.contract_id,
        shared_evidence_id=parent.shared_evidence_id,
        triggering_review_id=triggering_review_id,
        feedback=_artifact(store, feedback),
    )
    _validate_revision(store, revision)
    digest = store.artifacts.put_bytes(_bytes(revision))
    with store.connection() as connection:
        # One child has one immutable parent; competing associations fail closed.
        connection.execute(
            "INSERT INTO "
            "conditional_revisions(id,parent_attempt_id,revision_attempt_id,"
            "triggering_review_id) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
            (digest, parent_attempt_id, revision_attempt_id, triggering_review_id),
        )
    return digest


def _read_revision(store, row):
    raw = store.artifacts.read_bytes(row["id"])
    revision = ConditionalRevision.model_validate_json(raw)
    if _bytes(revision) != raw or any(
        getattr(revision, key) != row[key]
        for key in ("parent_attempt_id", "revision_attempt_id", "triggering_review_id")
    ):
        raise ValueError("revision index disagrees with immutable content")
    _validate_revision(store, revision)
    return revision


def provider_metadata(store, attempt, result):
    """Provider-reported fields from an envelope matching the stored model text."""
    if (
        result is None
        or result.response is None
        or result.execution_state != "succeeded"
    ):
        return None
    command = _gemini_command(
        store.artifacts.read_bytes(_role(attempt.artifacts, "command").sha256)
    )
    if command is None:
        return None
    endpoint_model = attempt.requested_model.removeprefix("models/")
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + endpoint_model
        + ":generateContent"
    )
    if (
        command.get("requested_model") != attempt.requested_model
        or command.get("endpoint") != endpoint
    ):
        raise ValueError("provider request identity disagrees with its attempt")
    artifact = _role(result.artifacts, "stdout")
    envelope = _json(store.artifacts.read_bytes(artifact.sha256))
    if not isinstance(envelope, dict):
        raise ValueError("provider envelope must be an object")
    candidates = envelope.get("candidates", [])
    if (
        not isinstance(candidates, list)
        or len(candidates) != 1
        or not isinstance(candidates[0], dict)
        or candidates[0].get("finishReason") != "STOP"
    ):
        raise ValueError("provider envelope has no unique completed candidate")
    content = candidates[0].get("content", {})
    if not isinstance(content, dict):
        raise ValueError("provider content must be an object")
    parts = content.get("parts", [])
    if (
        not isinstance(parts, list)
        or not parts
        or any(
            not isinstance(part, dict)
            or not isinstance(part.get("text"), str)
            or part.get("thought")
            for part in parts
        )
    ):
        raise ValueError("provider envelope contains unsupported candidate parts")
    raw_response = store.artifacts.read_bytes(
        _role(result.artifacts, "response").sha256
    )
    if "".join(part["text"] for part in parts).encode() != raw_response:
        raise ValueError("provider candidate differs from the recorded model text")
    if PairedModelResponse.model_validate_json(raw_response) != result.response:
        raise ValueError("provider candidate differs from the parsed forecast")
    model = envelope.get("modelVersion")
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        return None
    response_id = envelope.get("responseId")
    if response_id is not None and (
        not isinstance(response_id, str) or len(response_id) > 500
    ):
        raise ValueError("invalid provider response identifier")
    reported = envelope.get("usageMetadata", {})
    if not isinstance(reported, dict):
        raise ValueError("provider usage must be an object")
    usage = {}
    for name, field in (
        ("prompt_tokens", "promptTokenCount"),
        ("output_tokens", "candidatesTokenCount"),
        ("total_tokens", "totalTokenCount"),
        ("thought_tokens", "thoughtsTokenCount"),
    ):
        value = reported.get(field)
        if value is not None and (
            type(value) is not int or not 0 <= value <= 2**53 - 1
        ):
            raise ValueError("invalid provider token count")
        usage[name] = value
    return dict(
        provider="google",
        reported_model=model,
        response_id=response_id,
        usage=usage,
        source_artifact=_link(store, artifact, "provider_response"),
        verification="matched_recorded_response",
    )


def revision_history(store, attempt_id):
    from .conditionals import _timestamp
    from .lab import display_quantiles

    with store.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM conditional_revisions ORDER BY recorded_at,id"
        ).fetchall()
    members = {attempt_id}
    related = {}
    changed = True
    while changed:
        changed = False
        for row in rows:
            if (
                row["parent_attempt_id"] in members
                or row["revision_attempt_id"] in members
            ):
                before = len(members)
                members.update((row["parent_attempt_id"], row["revision_attempt_id"]))
                related[row["revision_attempt_id"]] = row
                changed |= len(members) != before
    links = {identity: _read_revision(store, row) for identity, row in related.items()}
    views = []
    start_times = {}
    for identity in members:
        attempt, _, result, row = _bound(store, identity)
        start_times[identity] = attempt.started_at
        revision = links.get(identity)
        state = (
            result.execution_state
            if result
            else "unknown"
            if row["now"] >= attempt.expires_at
            else "running"
        )
        views.append(
            dict(
                attempt_id=identity,
                contract_id=attempt.contract_id,
                shared_evidence_id=attempt.shared_evidence_id,
                parent_attempt_id=revision.parent_attempt_id if revision else None,
                started_at=_timestamp(attempt.started_at),
                execution_state=state,
                requested_model=attempt.requested_model,
                provider_metadata=provider_metadata(store, attempt, result),
                arm_quantiles=tuple(
                    display_quantiles(arm.distribution) for arm in result.response.arms
                )
                if result and result.response
                else (),
                feedback=_link(store, revision.feedback, "revision_feedback")
                if revision
                else None,
                triggering_review_id=revision.triggering_review_id
                if revision
                else None,
                linked_at=_timestamp(related[identity]["recorded_at"])
                if revision
                else None,
                association_basis=revision.association_basis if revision else None,
                association_artifact=_record_link(
                    store, related[identity]["id"], "revision_record"
                )
                if revision
                else None,
            )
        )
    return tuple(
        sorted(
            views,
            key=lambda item: (start_times[item["attempt_id"]], item["attempt_id"]),
        )
    )
