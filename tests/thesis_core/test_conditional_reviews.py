"""Real-PostgreSQL review/revision history and provider response binding."""

import json

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.thesis_core.test_conditionals import contract, response_data
from thesis_core.api import create_app
from thesis_core.conditional_reviews import (
    create_review,
    link_revision,
    response_artifact,
)
from thesis_core.conditionals import (
    conditional_detail,
    conditional_page,
    finish_attempt,
    start_attempt,
)


def complete(
    store, *, model="model-a", feedback=b"", changed=False, mutate_envelope=None
):
    spec = contract(store.artifacts.put_bytes(b"official"))
    if changed:
        spec = spec.model_copy(update={"title": "Changed contract"})
    command = {"argv": ["codex"]}
    if model.startswith("gemini"):
        command = {
            "transport": "gemini_rest_operator_v1",
            "requested_model": model,
            "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/"
            + model
            + ":generateContent",
        }
    attempt = start_attempt(
        store,
        spec,
        prompt=b"Frozen prompt\n" + feedback,
        command=json.dumps(command).encode(),
        code=b"public code",
        requested_model=model,
        timeout_seconds=60,
    )
    raw = json.dumps(response_data(spec)).encode()
    stdout = b"normal trace"
    if model.startswith("gemini"):
        envelope = {
            "candidates": [
                {"finishReason": "STOP", "content": {"parts": [{"text": raw.decode()}]}}
            ],
            "modelVersion": model + "-reported",
            "responseId": "response-1",
            "usageMetadata": {
                "promptTokenCount": 40,
                "candidatesTokenCount": 50,
                "totalTokenCount": 95,
                "thoughtsTokenCount": 5,
            },
        }
        if mutate_envelope:
            mutate_envelope(envelope)
        stdout = json.dumps(envelope).encode()
    result = finish_attempt(store, attempt.id, stdout=stdout, stderr=b"", response=raw)
    return attempt, result


def review(store, attempt_id, **updates):
    data = dict(
        attempt_id=attempt_id,
        expected_response_sha256=response_artifact(store, attempt_id).sha256,
        reviewer="Operator source review",
        report=b"# Source review\nAn unsupported extrapolation remains.",
        findings=[
            {
                "id": "extrapolation",
                "title": "Unsupported extrapolation",
                "detail": "The cited source does not establish a national effect.",
                "source_ids": ["official"],
                "response_location": "arms[0].reasoning",
            }
        ],
        outcome="issues_remaining",
    )
    data.update(updates)
    return create_review(store, **data)


def test_provider_metadata_retains_null_observed_identity_and_links_raw_bytes(
    core_store,
):
    attempt, detail = complete(core_store, model="gemini-test")
    metadata = detail.provider_metadata
    assert detail.observed_model is None
    assert metadata.reported_model == "gemini-test-reported"
    assert metadata.provider == "google"
    assert metadata.usage.total_tokens == 95
    assert metadata.verification == "matched_recorded_response"
    raw = core_store.artifacts.read_bytes(metadata.source_artifact.sha256)
    assert json.loads(raw)["modelVersion"] == metadata.reported_model
    assert detail.revision_history[0].attempt_id == attempt.id
    assert detail.revision_history[0].association_basis is None


@pytest.mark.parametrize(
    "change", ["candidate", "token", "parts", "candidate_shape", "usage_shape"]
)
def test_provider_metadata_refuses_foreign_or_malformed_envelope(core_store, change):
    def mutate(envelope):
        if change == "candidate":
            envelope["candidates"][0]["content"]["parts"][0]["text"] = "{}"
        elif change == "token":
            envelope["usageMetadata"]["promptTokenCount"] = True
        elif change == "parts":
            envelope["candidates"][0]["content"]["parts"] = [None]
        elif change == "candidate_shape":
            envelope["candidates"] = ["bad"]
        else:
            envelope["usageMetadata"] = []

    with pytest.raises(ValueError, match="provider"):
        complete(core_store, model="gemini-test", mutate_envelope=mutate)


def test_reviews_are_bound_append_only_and_preserve_original_response(core_store):
    attempt, original = complete(core_store)
    response_before = response_artifact(core_store, attempt.id)
    identity = review(core_store, attempt.id)
    assert review(core_store, attempt.id) == identity
    detail = conditional_detail(core_store, attempt.id)
    assert len(detail.reviews) == 1
    assert detail.reviews[0].outcome == "issues_remaining"
    assert detail.reviews[0].response_sha256 == response_before.sha256
    assert detail.reviews[0].record_artifact.sha256 == identity
    stored_review = json.loads(core_store.artifacts.read_bytes(identity))
    assert stored_review["response_sha256"] == response_before.sha256
    assert detail.response == original.response
    assert detail.reviews[0].recorded_at > detail.finished_at
    with pytest.raises(psycopg.Error):
        with core_store.connection() as connection:
            connection.execute(
                "DELETE FROM conditional_reviews WHERE id=%s", (identity,)
            )
    with core_store.connection() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == 0
        )


@pytest.mark.parametrize("change", ["response", "source", "outcome", "secret"])
def test_review_refuses_stale_response_unknown_source_or_unsafe_metadata(
    core_store, change
):
    attempt, _ = complete(core_store)
    updates = {}
    if change == "response":
        updates["expected_response_sha256"] = "a" * 64
    elif change == "source":
        updates["findings"] = [
            {
                "id": "bad",
                "title": "Bad",
                "detail": "Bad source",
                "source_ids": ["missing"],
                "response_location": "reference_reasoning",
            }
        ]
    elif change == "outcome":
        updates["outcome"] = "no_actionable_findings"
    else:
        updates["report"] = b"API_KEY=synthetic-secret"
    with pytest.raises(ValueError):
        review(core_store, attempt.id, **updates)


def test_revision_retains_both_attempts_feedback_and_retrospective_timing(core_store):
    parent, _ = complete(core_store, model="gemini-test")
    review_id = review(core_store, parent.id)
    feedback = b"Review the same sources and revisit the unsupported extrapolation."
    child, _ = complete(core_store, model="gemini-test", feedback=feedback)
    identity = link_revision(
        core_store,
        parent_attempt_id=parent.id,
        revision_attempt_id=child.id,
        triggering_review_id=review_id,
        feedback=feedback,
    )
    assert (
        link_revision(
            core_store,
            parent_attempt_id=parent.id,
            revision_attempt_id=child.id,
            triggering_review_id=review_id,
            feedback=feedback,
        )
        == identity
    )
    history = conditional_detail(core_store, child.id).revision_history
    assert [entry.attempt_id for entry in history] == [parent.id, child.id]
    assert history[1].parent_attempt_id == parent.id
    assert history[1].contract_id == history[0].contract_id
    assert history[1].association_basis == "retrospective_association"
    assert history[1].association_artifact.sha256 == identity
    assert history[1].linked_at > history[1].started_at
    assert core_store.artifacts.read_bytes(history[1].feedback.sha256) == feedback
    assert conditional_detail(core_store, parent.id).revision_history == history
    with pytest.raises(psycopg.Error):
        with core_store.connection() as connection:
            connection.execute(
                "DELETE FROM conditional_revisions WHERE id=%s", (identity,)
            )


@pytest.mark.parametrize("change", ["feedback", "contract", "review_parent", "reverse"])
def test_revision_rejects_unmatched_feedback_cross_contract_or_wrong_parent(
    core_store, change
):
    parent, _ = complete(core_store)
    review_id = review(core_store, parent.id)
    feedback = b"Some exact feedback"
    child, _ = complete(core_store, feedback=feedback, changed=change == "contract")
    if change == "review_parent":
        review_id = review(core_store, child.id)
    if change == "reverse":
        parent, child = child, parent
        review_id = review(core_store, parent.id)
    with pytest.raises(ValueError):
        link_revision(
            core_store,
            parent_attempt_id=parent.id,
            revision_attempt_id=child.id,
            triggering_review_id=review_id,
            feedback=b"different" if change == "feedback" else feedback,
        )


def test_requested_model_filter_precedes_pagination_and_lists_global_options(
    core_store,
):
    first, _ = complete(core_store, model="model-a")
    second, _ = complete(core_store, model="model-a")
    complete(core_store, model="model-b")
    page = conditional_page(core_store, requested_model="model-a", limit=1)
    assert page.total == 2
    assert page.requested_models == ["model-a", "model-b"]
    assert page.next_cursor is not None
    next_page = conditional_page(
        core_store, requested_model="model-a", limit=1, after=page.next_cursor
    )
    assert {page.items[0].id, next_page.items[0].id} == {first.id, second.id}
    assert next_page.total == 2 and next_page.next_cursor is None
    assert conditional_page(core_store, requested_model="missing").total == 0
    client = TestClient(create_app(core_store))
    assert client.get("/lab/conditionals?requested_model=model-a").json()["total"] == 2
    for value in ("", "bad%20model", "bad%0amodel", "a" * 201):
        assert (
            client.get("/lab/conditionals?requested_model=" + value).status_code == 422
        )
    assert (
        client.get("/lab/conditionals?requested_model=a&requested_model=b").status_code
        == 422
    )


def test_corrupt_review_remains_integrity_failure(core_store):
    attempt, _ = complete(core_store)
    identity = review(core_store, attempt.id)
    (core_store.artifacts.root / identity[:2] / identity).write_bytes(b"corrupt")
    client = TestClient(create_app(core_store))
    assert client.get("/lab/conditionals/" + attempt.id).status_code == 409


def test_child_cannot_acquire_a_second_parent(core_store):
    first, _ = complete(core_store)
    second, _ = complete(core_store)
    first_review = review(core_store, first.id)
    second_review = review(core_store, second.id)
    feedback = b"Shared feedback"
    child, _ = complete(core_store, feedback=feedback)
    link_revision(
        core_store,
        parent_attempt_id=first.id,
        revision_attempt_id=child.id,
        triggering_review_id=first_review,
        feedback=feedback,
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        link_revision(
            core_store,
            parent_attempt_id=second.id,
            revision_attempt_id=child.id,
            triggering_review_id=second_review,
            feedback=feedback,
        )
    assert len(conditional_detail(core_store, child.id).revision_history) == 2
