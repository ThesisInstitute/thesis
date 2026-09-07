"""Diagnostic redaction failures preserve the original operation's outcome."""

import json
from datetime import date

import pytest

from thesis_core import publication, tsa
from thesis_core.adapters import HttpResponse
from thesis_core.diagnostics import (
    MAX_DIAGNOSTIC_CHARACTERS,
    OMITTED_DIAGNOSTIC,
    safe_exception_text,
)
from thesis_core.pilot import prepare_replay
from thesis_core.resolution import capture_source
from thesis_core.security import RedactionError, redact_value
from thesis_core.worker import schedule_experiment, work_once

from .test_pilot import statcan_fixture
from .test_publication_api import completed_pilot

UNSAFE_MESSAGE = 'transport diagnostic: "password": {\n"value": "planted-secret"'


def test_unredactable_diagnostic_uses_a_fixed_safe_marker():
    with pytest.raises(RedactionError):
        redact_value(UNSAFE_MESSAGE)
    assert safe_exception_text(OSError(UNSAFE_MESSAGE)) == OMITTED_DIAGNOSTIC
    assert safe_exception_text(ValueError("ordinary parser failure")) == (
        "ordinary parser failure"
    )
    text = safe_exception_text(OSError("https://example.test/?api_key=planted-secret"))
    assert "planted-secret" not in text and "[REDACTED]" in text


def test_unformattable_or_oversized_diagnostic_is_withheld():
    class BrokenDiagnosticError(ValueError):
        def __str__(self):
            raise ValueError("cannot format exception")

    assert safe_exception_text(BrokenDiagnosticError()) == OMITTED_DIAGNOSTIC
    assert safe_exception_text(ValueError("x" * (MAX_DIAGNOSTIC_CHARACTERS + 1))) == (
        OMITTED_DIAGNOSTIC
    )


def test_capture_retains_archived_exchange_when_error_redaction_refuses(core_store):
    release = b"already archived release response"

    def fetch(request):
        if request.role == "release":
            return HttpResponse(release, request.url)
        raise OSError(UNSAFE_MESSAGE)

    result = capture_source(
        core_store,
        "bea-fixed-investment",
        measurement_period="2026-Q2",
        release_date=date(2026, 7, 30),
        fetch=fetch,
    )
    assert result.status == "failed"
    assert result.errors == (OMITTED_DIAGNOSTIC,)
    assert not result.observations
    assert len(result.exchanges) == 1
    exchange = result.exchanges[0]
    assert core_store.get(exchange.id) == exchange
    assert core_store.committed_at(exchange.id) is not None
    assert core_store.artifacts.read_bytes(exchange.body.sha256) == release


def test_publication_archives_safe_failure_and_preserves_tsa_exception(
    core_store, monkeypatch
):
    experiment, run = completed_pilot(core_store)
    manifest = publication.create_manifest(core_store, experiment.id, run_id=run.id)

    def unavailable(*_args):
        raise OSError(UNSAFE_MESSAGE)

    monkeypatch.setattr(tsa, "post_timestamp_query", unavailable)
    with pytest.raises(tsa.TsaError) as failure:
        publication.publish_manifest(core_store, manifest.id)
    attempts = core_store.publication_attempts(manifest.id)
    assert len(attempts) == 1
    assert core_store.artifacts.read_bytes(attempts[0]["request_hash"])
    assert attempts[0]["response_hash"] is None
    assert failure.value.artifact_hash == attempts[0]["error_hash"]
    error_bytes = core_store.artifacts.read_bytes(attempts[0]["error_hash"])
    assert json.loads(error_bytes)["error"] == OMITTED_DIAGNOSTIC
    assert b"planted-secret" not in error_bytes
    assert len(tuple(core_store.iter_records("forecast_run"))) == 1


def test_worker_keeps_known_publication_failure_when_redaction_refuses(
    core_store, monkeypatch
):
    _experiment, run = completed_pilot(core_store)

    def unavailable(*_args, **_kwargs):
        raise OSError(UNSAFE_MESSAGE)

    monkeypatch.setattr(publication, "publish_manifest", unavailable)
    result = work_once(core_store, kinds=("publish_run",))
    assert result["status"] == "failed"
    assert result["error"] == OMITTED_DIAGNOSTIC
    assert core_store.job(result["job_id"])["state"] == "failed"
    assert core_store.get(run.id) == run


def test_worker_keeps_uncertain_dispatched_state_when_error_redaction_refuses(
    core_store, monkeypatch
):
    experiment = prepare_replay(core_store, fetch=statcan_fixture)
    schedule_experiment(core_store, experiment.id)

    def unavailable(*_args, **_kwargs):
        raise OSError(UNSAFE_MESSAGE)

    # The baseline really dispatches and returns; inability to persist its
    # result is uncertain and must not be converted into an authorized retry.
    monkeypatch.setattr(core_store, "finish", unavailable)
    result = work_once(core_store, kinds=("forecast",))
    assert result["status"] == "execution_uncertain", result
    assert result["error"] == OMITTED_DIAGNOSTIC
    job = core_store.job(result["job_id"])
    assert job["state"] == "leased"
    assert job["dispatched_attempt_id"] == result["attempt_id"]
    assert core_store.get(result["attempt_id"]).kind == "attempt"
