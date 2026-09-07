"""Closed official-source registry, archived transport, and reproducible parsing."""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from thesis_core.artifacts import ArtifactStore
from thesis_core.canonical import canonical_bytes
from thesis_core.contracts import (
    ArtifactRef,
    ObservationVintage,
    PublicationTimingEvidence,
    ReleaseEvidence,
    SourceExchange,
    SourceSeries,
    TargetVersion,
)

from .parsers import (
    _ABS_UR_SPEC,
    _STATCAN_CPI_SPEC,
    BEA_ITABLE_DATA_URL,
    BEA_RELEASE_ADAPTERS,
    abs_series_from_payload,
    bea_advance_release_url,
    bea_itable_request_body,
    bea_itable_value,
    intl_transformed_value,
    statcan_series_from_payload,
)
from .timing import (
    BEA_CALENDAR_PARSER,
    BEA_CALENDAR_URL,
    BEA_RELEASE_PARSER,
    STATCAN_CPI_PORTAL_URL,
    STATCAN_CPI_RELEASE_PARSER,
    STATCAN_PUBLICATION_PARSER,
    bea_calendar_publication,
    bea_embargo_publication,
    quarter_start,
    statcan_cpi_next_release,
    statcan_publication,
)

VERSION = "official-fixtures-v1"
BEA_TABLE_PARSER = "bea-nipa-535-revision-v1"
STATCAN_URL = (
    "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
)
ABS_URL = (
    "https://data.api.abs.gov.au/rest/data/LF/M13.3.1599.20.AUS.M?lastNObservations=30"
)
BEA_SPEC = BEA_RELEASE_ADAPTERS["bea.private_nonresidential_fixed_investment"]
# Credential fields are metadata, never scientific binding dimensions.
CREDENTIAL_QUERY_FIELDS = (
    "UserID",
    "api_key",
    "api-key",
    "apikey",
    "access_token",
    "token",
)
CREDENTIAL_HEADERS = (
    "Authorization",
    "Proxy-Authorization",
    "X-API-Key",
    "Cookie",
    "Set-Cookie",
)


def registered_sources() -> dict[str, SourceSeries]:
    return {
        "abs-labour-unemployment": SourceSeries(
            adapter_id="abs-labour-unemployment",
            adapter_version=VERSION,
            name="Australia unemployment rate (SA)",
            unit="percent",
            binding={
                "flow": "LF",
                "key": "M13.3.1599.20.AUS.M",
                "transform": "level_round_1",
                "source_url": ABS_URL,
            },
            vintage_policies=("current_unverified",),
        ),
        "statcan-cpi-yoy": SourceSeries(
            adapter_id="statcan-cpi-yoy",
            adapter_version=VERSION,
            name="Canada CPI all-items, year-on-year (NSA)",
            unit="percent",
            binding={
                "vector": 41690973,
                "product": "18-10-0004-01",
                "transform": "yoy_from_index_round_1",
                "source_url": STATCAN_URL,
            },
            vintage_policies=("fixed_vintage",),
        ),
        "bea-fixed-investment": SourceSeries(
            adapter_id="bea-fixed-investment",
            adapter_version=VERSION,
            name="US private nonresidential fixed investment, nominal SAAR",
            unit="usd_billions",
            binding={
                "table": "T50305",
                "line": "2",
                "row": "Nonresidential",
                "frequency": "Q",
                "scale": 0.001,
                "source_url": BEA_ITABLE_DATA_URL,
            },
            vintage_policies=("fixed_vintage",),
        ),
    }


def get_source(adapter_id: str) -> SourceSeries:
    try:
        return registered_sources()[adapter_id]
    except KeyError as exc:
        raise ValueError(f"unregistered source adapter: {adapter_id}") from exc


def validate_source(source: SourceSeries) -> None:
    if source.canonical_bytes() != get_source(source.adapter_id).canonical_bytes():
        raise ValueError(
            "source version, binding, unit or policy differs from registered adapter"
        )


@dataclass(frozen=True)
class HttpRequest:
    url: str
    method: str = "GET"
    body: bytes | None = None
    headers: Mapping[str, str] | None = None
    role: str = "data"


@dataclass(frozen=True)
class HttpResponse:
    body: bytes
    url: str
    status_code: int = 200
    headers: Mapping[str, str] | None = None
    retrieved_at: dt.datetime | None = None


@dataclass(frozen=True)
class CaptureResult:
    source: SourceSeries
    exchanges: tuple[SourceExchange, ...]
    observations: tuple[ObservationVintage, ...]
    status: str
    errors: tuple[str, ...] = ()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("official transport redirects require an adapter revision")


def _fetch(request: HttpRequest) -> HttpResponse:
    # URLs come exclusively from the closed registry. Disable ambient proxies.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    req = Request(
        request.url,
        data=request.body,
        headers=dict(request.headers or {}),
        method=request.method,
    )
    with opener.open(req, timeout=30) as response:
        body = response.read(20_000_001)
        if len(body) > 20_000_000:
            raise ValueError("official response exceeds adapter size limit")
        return HttpResponse(
            body,
            response.url,
            response.status,
            dict(response.headers),
            dt.datetime.now(dt.timezone.utc),
        )


def _artifact(artifacts: ArtifactStore, raw: bytes, media_type: str) -> ArtifactRef:
    return ArtifactRef(
        sha256=artifacts.put_bytes(raw), bytes=len(raw), media_type=media_type
    )


def _read(artifacts: ArtifactStore, ref: ArtifactRef) -> bytes:
    raw = artifacts.read_bytes(ref.sha256)
    if len(raw) != ref.bytes:
        raise ValueError("artifact byte count does not match immutable reference")
    return raw


def _archive(source, request, response, artifacts, mode, fallback_time):
    from thesis_core.security import redact_headers, redact_url, redact_value

    if response.url != request.url:
        raise ValueError(
            "response URL differs from registered request (redirect refused)"
        )
    # Raw public data is archived before any parsing. Metadata is scrubbed before
    # canonicalization and before it can become a CAS object or a DB record.
    body = _artifact(
        artifacts,
        response.body,
        "text/calendar"
        if request.url == BEA_CALENDAR_URL
        else ("text/html" if request.role == "release" else "application/json"),
    )
    request_body = None
    if request.body is not None:
        request_body = _artifact(
            artifacts,
            canonical_bytes(redact_value(json.loads(request.body))),
            "application/json",
        )
    exchange = SourceExchange(
        source_series_id=source.id,
        url=redact_url(response.url, credential_params=CREDENTIAL_QUERY_FIELDS),
        retrieved_at=response.retrieved_at or fallback_time,
        status_code=response.status_code,
        body=body,
        response_headers=redact_headers(
            dict(response.headers or {}), credential_headers=CREDENTIAL_HEADERS
        ),
        request_method=request.method,
        request_body=request_body,
        role=request.role,
        mode=mode,
    )
    artifacts.put_bytes(exchange.canonical_bytes())
    return exchange


def _requests(adapter_id, measurement_period, release_date):
    if adapter_id == "abs-labour-unemployment":
        return (
            HttpRequest(
                ABS_URL,
                headers={"Accept": "application/vnd.sdmx.data+json;version=2.0"},
            ),
        )
    if adapter_id == "statcan-cpi-yoy":
        return (
            HttpRequest(
                STATCAN_URL,
                "POST",
                canonical_bytes([{"vectorId": 41690973, "latestN": 48}]),
                {"Content-Type": "application/json"},
            ),
        )
    if not measurement_period or not release_date:
        raise ValueError(
            "BEA capture requires an exact measurement_period and release_date"
        )
    period = quarter_start(measurement_period)
    return (
        HttpRequest(bea_advance_release_url(period, release_date), role="release"),
        HttpRequest(
            BEA_ITABLE_DATA_URL,
            "POST",
            canonical_bytes(bea_itable_request_body(BEA_SPEC, period)),
            {"Content-Type": "application/json", "User-Agent": "Thesis/1.0"},
        ),
    )


def capture(
    adapter_id: str,
    artifacts: ArtifactStore,
    *,
    measurement_period: str | None = None,
    release_date: dt.date | None = None,
    mode: str = "live",
    fetch: Callable[[HttpRequest], HttpResponse] | None = None,
    retrieved_at: dt.datetime | None = None,
    accepted_at: dt.datetime | None = None,
) -> CaptureResult:
    source = get_source(adapter_id)
    when = retrieved_at or dt.datetime.now(dt.timezone.utc)
    accepted = accepted_at or when
    exchanges = []
    try:
        for request in _requests(adapter_id, measurement_period, release_date):
            response = (fetch or _fetch)(request)
            exchange = _archive(source, request, response, artifacts, mode, when)
            exchanges.append(exchange)
            if response.status_code != 200:
                raise ValueError(
                    f"official source returned HTTP {response.status_code}"
                )
        observations = _parse(
            source, tuple(exchanges), artifacts, measurement_period, accepted
        )
        return CaptureResult(
            source,
            tuple(exchanges),
            observations,
            "captured" if observations else "deferred",
            () if observations else ("requested observation unavailable",),
        )
    except Exception as exc:
        # Errors can contain URLs from transports; scrub them before persistence.
        from thesis_core.diagnostics import safe_exception_text

        return CaptureResult(
            source, tuple(exchanges), (), "failed", (safe_exception_text(exc),)
        )


def _bea_revision(raw: bytes) -> str:
    response = json.loads(raw)
    if isinstance(response, str):
        response = json.loads(response)
    prompts = [
        p
        for p in response["Prompts"]
        if p.get("Name") == "TheTable" and p.get("UIControl") == "Table"
    ]
    if len(prompts) != 1:
        raise ValueError("expected one BEA table")
    table = json.loads(json.loads(prompts[0]["PromtData"])["Table"])
    match = re.match(
        r"Last Revised on: ([A-Za-z]+ \d{1,2}, \d{4})(?:\D|$)", table["Description"]
    )
    if not match:
        raise ValueError("unsupported BEA table revision date")
    return dt.datetime.strptime(match[1], "%B %d, %Y").date().isoformat()


def _parse(source, exchanges, artifacts, measurement_period, accepted_at):
    validate_source(source)
    for exchange in exchanges:
        if exchange.source_series_id != source.id or exchange.status_code != 200:
            raise ValueError("exchange does not bind a successful registered source")
    data = [e for e in exchanges if e.role == "data"]
    if len(data) != 1:
        raise ValueError("adapter requires exactly one data exchange")
    exchange = data[0]
    raw = _read(artifacts, exchange.body)
    if source.adapter_id == "bea-fixed-investment":
        if not measurement_period or exchange.url != BEA_ITABLE_DATA_URL:
            raise ValueError("BEA period or source URL mismatch")
        expected = canonical_bytes(
            bea_itable_request_body(BEA_SPEC, quarter_start(measurement_period))
        )
        if (
            exchange.request_method != "POST"
            or not exchange.request_body
            or _read(artifacts, exchange.request_body) != expected
        ):
            raise ValueError("BEA request does not bind exact table and period")
        revision = _bea_revision(raw)
        day = dt.date.fromisoformat(revision)
        releases = [e for e in exchanges if e.role == "release"]
        if len(releases) != 1 or releases[0].url != bea_advance_release_url(
            quarter_start(measurement_period), day
        ):
            raise ValueError("BEA release exchange mismatch")
        publication = bea_embargo_publication(
            _read(artifacts, releases[0].body), measurement_period
        )
        if publication[:10] != revision:
            raise ValueError("BEA table revision and advance release differ")
        value, refusal = bea_itable_value(
            raw, BEA_SPEC, quarter_start(measurement_period), day
        )
        if refusal:
            raise ValueError(refusal)
        values = {measurement_period: value}
    else:
        expected_url = (
            ABS_URL if source.adapter_id == "abs-labour-unemployment" else STATCAN_URL
        )
        if exchange.url != expected_url:
            raise ValueError("source URL differs from registered adapter")
        if source.adapter_id == "abs-labour-unemployment":
            if exchange.request_method != "GET" or exchange.request_body is not None:
                raise ValueError("ABS request mismatch")
            values = abs_series_from_payload(raw, "LF", "M13.3.1599.20.AUS.M")
            spec = _ABS_UR_SPEC
        else:
            expected = canonical_bytes([{"vectorId": 41690973, "latestN": 48}])
            if (
                exchange.request_method != "POST"
                or not exchange.request_body
                or _read(artifacts, exchange.request_body) != expected
            ):
                raise ValueError("StatCan request mismatch")
            payload = json.loads(raw)
            points = payload[0]["object"]["vectorDataPoint"]
            periods = [str(p["refPer"])[:7] for p in points]
            if len(periods) != len(set(periods)) or any(
                p.get("scalarFactorCode") != 0
                or p.get("frequencyCode") != 6
                or p.get("statusCode") != 0
                for p in points
            ):
                raise ValueError(
                    "StatCan duplicate period, unit, frequency or status drift"
                )
            values = statcan_series_from_payload(raw, 41690973)
            spec = _STATCAN_CPI_SPEC
        values = {
            period: intl_transformed_value(spec, values, period)
            for period in sorted(values)
        }
    observations = []
    for period, value in values.items():
        if value is None or (
            measurement_period is not None and period != measurement_period
        ):
            continue
        if not math.isfinite(value):
            raise ValueError("non-finite source observation")
        proof = None
        if source.adapter_id == "statcan-cpi-yoy":
            from thesis_core.evaluation import source_availability_interval

            publication = statcan_publication(raw, 41690973, period)
            prior_period = f"{int(period[:4]) - 1}-{period[5:]}"
            prior_publication = statcan_publication(raw, 41690973, prior_period)
            inputs = (publication, prior_publication)
            intervals = [
                source_availability_interval(value, "America/Toronto")
                if value is not None
                else None
                for value in inputs
            ]
            if all(interval is not None for interval in intervals):
                # A correction to the prior-year denominator creates a later
                # exact YOY vintage, even when the current index is unchanged.
                latest = max(range(2), key=lambda index: intervals[index].upper)
                proof = PublicationTimingEvidence(
                    raw_value=inputs[latest],
                    timezone="America/Toronto",
                    source_url=exchange.url,
                    parser_version=STATCAN_PUBLICATION_PARSER,
                    artifact=exchange.body,
                )
        elif source.adapter_id == "bea-fixed-investment":
            proof = PublicationTimingEvidence(
                raw_value=revision,
                timezone="America/New_York",
                source_url=exchange.url,
                parser_version=BEA_TABLE_PARSER,
                artifact=exchange.body,
            )
        observations.append(
            ObservationVintage(
                source_series_id=source.id,
                measurement_period=period,
                value=float(value),
                unit=source.unit,
                source_exchange_ids=tuple(e.id for e in exchanges),
                retrieved_at=max(e.retrieved_at for e in exchanges),
                accepted_at=accepted_at,
                parser_version=VERSION,
                vintage_policy=source.vintage_policies[0],
                publication_evidence=proof,
            )
        )
    return tuple(observations)


def validate_observation(
    observation: ObservationVintage,
    source: SourceSeries,
    exchanges: Mapping[str, SourceExchange],
    artifacts: ArtifactStore,
) -> None:
    backing = tuple(exchanges[identity] for identity in observation.source_exchange_ids)
    if any(
        e.id != identity
        for e, identity in zip(backing, observation.source_exchange_ids, strict=True)
    ):
        raise ValueError("exchange identity mismatch")
    parsed = _parse(
        source,
        backing,
        artifacts,
        observation.measurement_period,
        observation.accepted_at,
    )
    if len(parsed) != 1 or parsed[0].canonical_bytes() != observation.canonical_bytes():
        raise ValueError(
            "observation or publication claim differs from registered raw parse"
        )


def observation_availability(
    observation: ObservationVintage,
    source: SourceSeries,
    exchanges: Mapping[str, SourceExchange],
    artifacts: ArtifactStore,
):
    from thesis_core.evaluation import Availability, source_availability_interval

    validate_observation(observation, source, exchanges, artifacts)
    proof = observation.publication_evidence
    if proof is None:
        return None
    interval = source_availability_interval(proof.raw_value, proof.timezone)
    if source.adapter_id == "statcan-cpi-yoy":
        # YOY depends on two index values. The later publication of either input
        # limits when the derived exact value could have been available.
        period = observation.measurement_period
        prior = f"{int(period[:4]) - 1}-{period[5:]}"
        raw = _read(artifacts, proof.artifact)
        current_time = statcan_publication(raw, 41690973, period)
        prior_time = statcan_publication(raw, 41690973, prior)
        interval = (
            source_availability_interval(current_time, proof.timezone)
            if current_time
            else None
        )
        prior_interval = (
            source_availability_interval(prior_time, proof.timezone)
            if prior_time
            else None
        )
        if interval is None or prior_interval is None:
            return None
        interval = Availability(
            max(interval.lower, prior_interval.lower),
            max(interval.upper, prior_interval.upper),
        )
    return interval


def release_evidence_from_bytes(
    source: SourceSeries,
    measurement_period: str,
    raw: bytes,
    source_url: str,
    artifacts: ArtifactStore,
) -> ReleaseEvidence:
    validate_source(source)
    if source.adapter_id == "statcan-cpi-yoy":
        if source_url != STATCAN_CPI_PORTAL_URL:
            raise ValueError("release proof URL is not the exact official CPI portal")
        return ReleaseEvidence(
            raw_value=statcan_cpi_next_release(raw, measurement_period),
            timezone="America/Toronto",
            source_url=source_url,
            parser_version=STATCAN_CPI_RELEASE_PARSER,
            artifact=_artifact(artifacts, raw, "text/html"),
        )
    if source.adapter_id != "bea-fixed-investment":
        raise ValueError(
            "this adapter has no supported first-print release-evidence parser"
        )
    if source_url == BEA_CALENDAR_URL:
        timestamp = bea_calendar_publication(raw, measurement_period)
        parser, media = BEA_CALENDAR_PARSER, "text/calendar"
    else:
        timestamp = bea_embargo_publication(raw, measurement_period)
        if source_url != bea_advance_release_url(
            quarter_start(measurement_period), dt.date.fromisoformat(timestamp[:10])
        ):
            raise ValueError(
                "release proof URL is not the exact official advance-release page"
            )
        parser, media = BEA_RELEASE_PARSER, "text/html"
    return ReleaseEvidence(
        raw_value=timestamp,
        timezone="America/New_York",
        source_url=source_url,
        parser_version=parser,
        artifact=_artifact(artifacts, raw, media),
    )


def capture_release_evidence(
    adapter_id: str,
    measurement_period: str,
    artifacts: ArtifactStore,
    *,
    fetch: Callable[[HttpRequest], HttpResponse] | None = None,
    mode: str = "live",
) -> tuple[SourceExchange, ReleaseEvidence]:
    source = get_source(adapter_id)
    calendars = {
        "bea-fixed-investment": BEA_CALENDAR_URL,
        "statcan-cpi-yoy": STATCAN_CPI_PORTAL_URL,
    }
    if adapter_id not in calendars:
        raise ValueError("future release capture is unsupported for this source")
    request = HttpRequest(calendars[adapter_id], role="release")
    response = (fetch or _fetch)(request)
    exchange = _archive(
        source, request, response, artifacts, mode, dt.datetime.now(dt.timezone.utc)
    )
    if response.status_code != 200:
        raise ValueError(
            "official release calendar unavailable; response remains in CAS"
        )
    proof = release_evidence_from_bytes(
        source,
        measurement_period,
        _read(artifacts, exchange.body),
        exchange.url,
        artifacts,
    )
    return exchange, proof


def target_release_availability(
    target: TargetVersion, source: SourceSeries, artifacts: ArtifactStore
):
    from thesis_core.evaluation import source_availability_interval

    validate_source(source)
    if target.source_series_id != source.id or target.unit != source.unit:
        raise ValueError("target source or unit mismatch")
    proof = target.release_evidence
    if proof is None:
        return None
    parsed = release_evidence_from_bytes(
        source,
        target.measurement_period,
        _read(artifacts, proof.artifact),
        proof.source_url,
        artifacts,
    )
    if parsed != proof:
        raise ValueError("target release claim differs from registered official parse")
    return source_availability_interval(proof.raw_value, proof.timezone)


def validate_resolution(
    target: TargetVersion,
    observation: ObservationVintage,
    source: SourceSeries,
    exchanges: Mapping[str, SourceExchange],
    artifacts: ArtifactStore,
) -> bool:
    """Mechanical exact-series/period/unit/vintage rule, never free-text matching."""
    validate_observation(observation, source, exchanges, artifacts)
    if (
        target.source_series_id != source.id
        or target.unit != source.unit
        or target.measurement_period != observation.measurement_period
    ):
        return False
    if (
        target.resolution_policy != observation.vintage_policy
        or target.resolution_policy not in source.vintage_policies
    ):
        return False
    if target.resolution_policy == "fixed_vintage":
        proof = observation.publication_evidence
        return proof is not None and proof.raw_value[:10] == target.vintage_date
    return target.resolution_policy == "current_unverified"
