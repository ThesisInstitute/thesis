"""Public API errors remain typed even when underlying diagnostics are private."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from thesis_core import api, service
from thesis_core.artifacts import ArtifactMissing

from .factories import add_resolution, add_run, make_graph


@pytest.mark.parametrize("route", ["leaderboard", "rewards"])
def test_wrong_kind_experiment_id_is_a_missing_experiment(monkeypatch, route):
    graph = make_graph()
    monkeypatch.setattr(service, "context_for_store", lambda _: graph.context())
    store = SimpleNamespace(get=graph.records.__getitem__)
    response = TestClient(api.create_app(store)).get(
        f"/{route}", params={"experiment_id": graph.source.id}
    )
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "experiment_not_found"}}


@pytest.mark.parametrize("route", ["leaderboard", "rewards"])
@pytest.mark.parametrize("mode", ["replay", "prospective"])
def test_evaluation_errors_never_enter_public_exclusion_rows(monkeypatch, route, mode):
    graph = make_graph(mode=mode)
    add_run(graph)
    add_resolution(graph)

    def unavailable(_record):
        raise OSError(13, "Permission denied", "/private/operator/artifacts")

    # Use the real assessment and HTTP projection paths. Only source replay is
    # injected so an error after context hydration can be tested deterministically.
    context = graph.context(availability=unavailable)
    monkeypatch.setattr(service, "context_for_store", lambda _: context)
    store = SimpleNamespace(get=graph.records.__getitem__)
    response = TestClient(api.create_app(store)).get(
        f"/{route}", params={"experiment_id": graph.experiment.id}
    )
    assert response.status_code == 200
    assert response.json()["items"]
    assert all(
        row["exclusions"] == ["invalid_contract"] for row in response.json()["items"]
    )
    assert "private" not in response.text
    assert "Permission denied" not in response.text


@pytest.mark.parametrize("route", ["leaderboard", "rewards"])
def test_outcome_availability_error_keeps_its_public_reason(monkeypatch, route):
    graph = make_graph(mode="prospective")
    add_run(graph)
    add_resolution(graph)

    def unavailable(_target):
        raise OSError("private calendar path")

    context = graph.context(target_availability=unavailable)
    monkeypatch.setattr(service, "context_for_store", lambda _: context)
    store = SimpleNamespace(get=graph.records.__getitem__)
    response = TestClient(api.create_app(store)).get(
        f"/{route}", params={"experiment_id": graph.experiment.id}
    )
    assert response.status_code == 200
    assert response.json()["items"]
    assert all(
        row["exclusions"] == ["outcome_availability_unknown"]
        for row in response.json()["items"]
    )
    assert "private" not in response.text


@pytest.mark.parametrize(
    "route",
    ["experiments", "leaderboard", "rewards", "pending", "records/" + "a" * 64],
)
def test_backend_failures_use_the_same_bounded_envelope(route):
    def unavailable(*_args, **_kwargs):
        raise OSError("private database path")

    store = SimpleNamespace(list=unavailable, iter_records=unavailable, get=unavailable)
    response = TestClient(api.create_app(store)).get(f"/{route}")
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "store_unavailable"}}


@pytest.mark.parametrize(
    "route,status,code",
    [
        ("/artifacts/" + "a" * 64, 404, "artifact_not_found"),
        ("/rewards?as_of=bad", 422, "invalid_as_of"),
        ("/experiments?limit=0", 422, "invalid_request"),
        ("/records/not-a-hash", 422, "invalid_request"),
        ("/not-a-route", 404, "not_found"),
    ],
)
def test_request_errors_share_the_error_envelope(route, status, code):
    def missing(_digest):
        raise ArtifactMissing("private artifact path")

    store = SimpleNamespace(artifacts=SimpleNamespace(read_bytes=missing))
    response = TestClient(api.create_app(store)).get(route)
    assert response.status_code == status
    assert response.json() == {"error": {"code": code}}


def test_unconfigured_api_uses_the_error_envelope(monkeypatch):
    monkeypatch.delenv("THESIS_CORE_DSN", raising=False)
    response = TestClient(api.create_app()).get("/experiments")
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "core_unconfigured"}}
