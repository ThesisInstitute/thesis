from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from thesis_core.adapters import (
    HttpResponse,
    capture,
    get_source,
    observation_availability,
    release_evidence_from_bytes,
    target_release_availability,
    validate_observation,
    validate_resolution,
    validate_source,
)
from thesis_core.adapters.registry import HttpRequest, _archive
from thesis_core.adapters.timing import BEA_CALENDAR_URL, bea_calendar_publication
from thesis_core.artifacts import LocalArtifactStore
from thesis_core.contracts import TargetVersion
from thesis_core.evaluation import source_availability_interval
from thesis_core.evidence import (
    available_as_of,
    build_evidence_bundle,
    established_upper,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = dt.datetime(2026, 9, 4, 12, tzinfo=dt.timezone.utc)


@pytest.fixture
def artifacts(tmp_path):
    return LocalArtifactStore(tmp_path / "cas")


def captured(artifacts, adapter="statcan-cpi-yoy", **kwargs):
    def fetch(request):
        if adapter == "bea-fixed-investment":
            name = (
                "gdp-advance-2026-q2.html"
                if request.role == "release"
                else "nipa-table-5-3-5-2026-q2.json"
            )
            raw = (FIXTURES / "ingestion_wave1" / "bea" / name).read_bytes()
        else:
            name = (
                "statcan_cpi_v41690973.json"
                if adapter == "statcan-cpi-yoy"
                else "abs_lfs_unemployment_rate.json"
            )
            raw = (FIXTURES / "international" / name).read_bytes()
        return HttpResponse(
            raw, request.url, headers={"Date": "Mon, 01 Jan 1990 00:00:00 GMT"}
        )

    if adapter == "bea-fixed-investment":
        kwargs.update(measurement_period="2026-Q2", release_date=dt.date(2026, 7, 30))
    return capture(
        adapter, artifacts, mode="replay", fetch=fetch, retrieved_at=NOW, **kwargs
    )


@pytest.mark.parametrize(
    "adapter,expected",
    [
        ("abs-labour-unemployment", [4.3, 4.5, 4.4]),
        ("statcan-cpi-yoy", [1.8, 2.4, 2.8, 3.2]),
        ("bea-fixed-investment", [4623.657]),
    ],
)
def test_exact_official_fixture_values(artifacts, adapter, expected):
    result = captured(artifacts, adapter)
    assert result.status == "captured", result.errors
    assert [o.value for o in result.observations] == expected
    exchanges = {e.id: e for e in result.exchanges}
    for observation in result.observations:
        validate_observation(observation, result.source, exchanges, artifacts)
        with pytest.raises(ValueError):
            validate_observation(
                observation.model_copy(update={"value": 999.0}),
                result.source,
                exchanges,
                artifacts,
            )


def test_binding_drift_refuses(artifacts):
    source = get_source("statcan-cpi-yoy")
    with pytest.raises(ValueError):
        validate_source(source.model_copy(update={"unit": "usd_billions"}))


def test_parser_failure_retains_archived_response(artifacts):
    result = capture(
        "statcan-cpi-yoy",
        artifacts,
        fetch=lambda request: HttpResponse(b"not json", request.url),
    )
    assert result.status == "failed"
    assert len(result.exchanges) == 1
    assert artifacts.read_bytes(result.exchanges[0].body.sha256) == b"not json"


def test_secondary_fetch_failure_retains_bea_release(artifacts):
    def fetch(request):
        if request.role == "data":
            raise TimeoutError("official table unavailable")
        return HttpResponse(b"archived release even if malformed", request.url)

    result = capture(
        "bea-fixed-investment",
        artifacts,
        measurement_period="2026-Q2",
        release_date=dt.date(2026, 7, 30),
        fetch=fetch,
    )
    assert result.status == "failed"
    assert len(result.exchanges) == 1
    assert (
        artifacts.read_bytes(result.exchanges[0].body.sha256)
        == b"archived release even if malformed"
    )


def test_metadata_credentials_scrubbed_before_cas(artifacts):
    source = get_source("bea-fixed-investment")
    url = "https://apps.bea.gov/iTablecore/data/app/GetStep?UserID=secret-one&API-key=secret-two"
    request = HttpRequest(url, "POST", b'{"api_key":"secret-three","table":"T50305"}')
    response = HttpResponse(
        b"{}",
        url,
        headers={
            "Authorization": "Bearer secret-four",
            "Set-Cookie": "secret-five",
            "Content-Type": "application/json",
        },
    )
    exchange = _archive(source, request, response, artifacts, "replay", NOW)
    persisted = exchange.canonical_bytes() + artifacts.read_bytes(
        exchange.request_body.sha256
    )
    for secret in (
        b"secret-one",
        b"secret-two",
        b"secret-three",
        b"secret-four",
        b"secret-five",
    ):
        assert secret not in persisted


def test_http_date_never_establishes_publication(artifacts):
    result = captured(artifacts, "abs-labour-unemployment")
    observation = result.observations[-1]
    assert (
        observation_availability(
            observation, result.source, {e.id: e for e in result.exchanges}, artifacts
        )
        is None
    )
    assert observation.publication_evidence is None


def test_future_bea_release_binds_quarter_and_dtstart(artifacts):
    raw = (
        FIXTURES / "thesis_core" / "bea-release-schedule-2026-09-04.ics"
    ).read_bytes()
    source = get_source("bea-fixed-investment")
    proof = release_evidence_from_bytes(
        source, "2026-Q3", raw, BEA_CALENDAR_URL, artifacts
    )
    assert proof.raw_value == "2026-10-29T12:30:00Z"
    target = TargetVersion(
        target_id="bea-q3",
        source_series_id=source.id,
        measurement_period="2026-Q3",
        unit=source.unit,
        resolution_policy="fixed_vintage",
        vintage_date="2026-10-29",
        resolution_rule="exact official revision date",
        submission_deadline=dt.datetime(2026, 10, 28, tzinfo=dt.timezone.utc),
        release_evidence=proof,
    )
    assert target_release_availability(target, source, artifacts).lower == dt.datetime(
        2026, 10, 29, 12, 30, tzinfo=dt.timezone.utc
    )
    with pytest.raises(ValueError):
        target_release_availability(
            target.model_copy(update={"measurement_period": "2026-Q4"}),
            source,
            artifacts,
        )
    # File generation is not publication. Changing DTSTAMP cannot change proof.
    assert (
        bea_calendar_publication(raw.replace(b"DTSTAMP:", b"X-IGNORED:"), "2026-Q3")
        == proof.raw_value
    )
    with pytest.raises(ValueError):
        bea_calendar_publication(
            raw.replace(b"DTSTART:20261029T123000Z", b"DTSTART:20261029T083000"),
            "2026-Q3",
        )


def test_exact_fixed_vintage_resolution(artifacts):
    result = captured(artifacts, "bea-fixed-investment")
    target = TargetVersion(
        target_id="bea-q2",
        source_series_id=result.source.id,
        measurement_period="2026-Q2",
        unit=result.source.unit,
        resolution_policy="fixed_vintage",
        vintage_date="2026-07-30",
        resolution_rule="exact official revision date",
        submission_deadline=NOW,
    )
    observation = result.observations[0]
    exchanges = {e.id: e for e in result.exchanges}
    assert validate_resolution(target, observation, result.source, exchanges, artifacts)
    assert not validate_resolution(
        target.model_copy(update={"vintage_date": "2026-08-27"}),
        observation,
        result.source,
        exchanges,
        artifacts,
    )
    # The table is dated, not individually timestamped at the GDP embargo hour.
    interval = observation_availability(
        observation, result.source, exchanges, artifacts
    )
    assert interval.lower == dt.datetime(2026, 7, 30, 4, tzinfo=dt.timezone.utc)
    assert interval.upper == dt.datetime(2026, 7, 31, 4, tzinfo=dt.timezone.utc)


def test_prior_year_cpi_correction_creates_a_later_derived_vintage(artifacts):
    payload = json.loads(
        (FIXTURES / "international/statcan_cpi_v41690973.json").read_bytes()
    )
    prior = next(
        point
        for point in payload[0]["object"]["vectorDataPoint"]
        if point["refPer"] == "2025-05-01"
    )
    prior.update(value=163.0, releaseTime="2026-09-01T08:30")
    result = capture(
        "statcan-cpi-yoy",
        artifacts,
        measurement_period="2026-05",
        mode="replay",
        fetch=lambda request: HttpResponse(json.dumps(payload).encode(), request.url),
    )
    observation = result.observations[0]
    assert observation.publication_evidence.raw_value == "2026-09-01T08:30"
    target = TargetVersion(
        target_id="cpi-may",
        source_series_id=result.source.id,
        measurement_period="2026-05",
        unit=result.source.unit,
        resolution_policy="fixed_vintage",
        vintage_date="2026-06-22",
        resolution_rule="exact official vintage date",
        submission_deadline=NOW,
    )
    assert not validate_resolution(
        target,
        observation,
        result.source,
        {exchange.id: exchange for exchange in result.exchanges},
        artifacts,
    )


def test_replay_late_ack_uses_authenticated_historical_upper(artifacts):
    result = captured(artifacts)
    cutoff = dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc)
    args = (
        result.source,
        result.observations,
        {e.id: e for e in result.exchanges},
        artifacts,
    )
    replay = build_evidence_bundle(
        *args, information_cutoff=cutoff, mode="replay", committed_at=lambda _: NOW
    )
    assert len(replay.observation_ids) == 3
    prospective = build_evidence_bundle(
        *args, information_cutoff=cutoff, mode="prospective", committed_at=lambda _: NOW
    )
    assert not prospective.observation_ids
    missing = build_evidence_bundle(
        *args,
        information_cutoff=NOW,
        mode="replay",
        committed_at=lambda identity: (
            None if identity == result.exchanges[0].id else NOW
        ),
    )
    assert not missing.observation_ids


def test_date_only_capture_tightens_upper_and_inclusive_cutoffs():
    official = source_availability_interval("2026-07-30", "America/New_York")
    noon = dt.datetime(2026, 7, 30, 16, tzinfo=dt.timezone.utc)
    assert established_upper(committed_at=noon, official=official) == noon
    assert established_upper(committed_at=None, official=official) is None
    with pytest.raises(ValueError):
        established_upper(
            committed_at=dt.datetime(2026, 7, 29, tzinfo=dt.timezone.utc),
            official=official,
        )
    assert available_as_of(
        ["score"],
        cutoff=noon,
        committed_at=lambda _: noon,
        dependencies=lambda identity: ["forecast"] if identity == "score" else [],
    )
    assert not available_as_of(
        ["score"],
        cutoff=noon,
        committed_at=lambda identity: (
            noon if identity == "score" else noon + dt.timedelta(seconds=1)
        ),
        dependencies=lambda identity: ["forecast"] if identity == "score" else [],
    )


def test_duplicate_eligible_vintages_refuse(artifacts):
    result = captured(artifacts)
    duplicate = result.observations[0].model_copy(
        update={"accepted_at": NOW + dt.timedelta(seconds=1)}
    )
    # Reconstruct rather than bypassing strict immutable snapshot validation.
    duplicate = type(duplicate).model_validate_json(duplicate.model_dump_json())
    with pytest.raises(ValueError, match="multiple eligible vintages"):
        build_evidence_bundle(
            result.source,
            (*result.observations, duplicate),
            {e.id: e for e in result.exchanges},
            artifacts,
            information_cutoff=NOW,
            mode="replay",
            committed_at=lambda _: NOW,
        )
