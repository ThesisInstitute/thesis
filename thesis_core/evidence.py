"""One inclusive cutoff rule for archived data and derived evidence.

Collector clocks never authorize admission. ``committed_at`` must be the store's
post-commit DB acknowledgement lookup, and a witness lookup must verify the
receipt before returning a bound. Neither is read from scientific JSON claims.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .adapters.registry import observation_availability, validate_source
from .artifacts import ArtifactStore
from .contracts import (
    ArtifactRef,
    EvidenceBundle,
    ObservationVintage,
    SourceExchange,
    SourceSeries,
)

if TYPE_CHECKING:
    from .evaluation import Availability


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("availability requires an aware timestamp")
    return value.astimezone(timezone.utc)


def established_upper(
    *,
    committed_at: datetime | None,
    official: Availability | None = None,
    witnessed_upper: datetime | None = None,
) -> datetime | None:
    """Minimum independently established upper; missing acknowledgement refuses.

    Keeping the acknowledgement requirement here prevents publication metadata
    from bypassing a crash between scientific commit and acknowledgement.
    """
    if committed_at is None:
        return None
    from .evaluation import Availability
    from .evaluation import established_upper as calculate_upper

    witness = (
        Availability(_utc(witnessed_upper), _utc(witnessed_upper))
        if witnessed_upper is not None
        else None
    )
    return calculate_upper(_utc(committed_at), official, witness)


def observation_eligible(
    observation: ObservationVintage,
    source: SourceSeries,
    exchanges: Mapping[str, SourceExchange],
    artifacts: ArtifactStore,
    *,
    information_cutoff: datetime,
    mode: str,
    committed_at: Callable[[str], datetime | None],
    witnessed_upper: Callable[[str], datetime | None] | None = None,
) -> bool:
    if mode not in {"prospective", "replay"}:
        raise ValueError("unknown evidence mode")
    cutoff = _utc(information_cutoff)
    official = observation_availability(observation, source, exchanges, artifacts)
    identities = (source.id, *observation.source_exchange_ids, observation.id)
    acknowledgements = [committed_at(identity) for identity in identities]
    if any(value is None for value in acknowledgements):
        return False
    if mode == "prospective" and any(
        _utc(value) > cutoff for value in acknowledgements
    ):
        return False
    upper = established_upper(
        committed_at=acknowledgements[-1],
        official=official,
        witnessed_upper=witnessed_upper(observation.id) if witnessed_upper else None,
    )
    return upper is not None and upper <= cutoff


def build_evidence_bundle(
    source: SourceSeries,
    observations: Iterable[ObservationVintage],
    exchanges: Mapping[str, SourceExchange],
    artifacts: ArtifactStore,
    *,
    information_cutoff: datetime,
    mode: str,
    committed_at: Callable[[str], datetime | None],
    witnessed_upper: Callable[[str], datetime | None] | None = None,
) -> EvidenceBundle:
    """Freeze exact eligible vintages; never substitute today's revised history.

    More than one eligible vintage for a period refuses. Callers must choose an
    explicit immutable vintage policy before constructing a series history.
    The returned bundle is not accepted until the caller commits it normally.
    """
    validate_source(source)
    selected = []
    for observation in observations:
        if observation_eligible(
            observation,
            source,
            exchanges,
            artifacts,
            information_cutoff=information_cutoff,
            mode=mode,
            committed_at=committed_at,
            witnessed_upper=witnessed_upper,
        ):
            selected.append(observation)
    selected.sort(
        key=lambda observation: (observation.measurement_period, observation.id)
    )
    if len({o.measurement_period for o in selected}) != len(selected):
        raise ValueError(
            "multiple eligible vintages for one period require an explicit selection"
        )
    refs: dict[str, ArtifactRef] = {}
    for observation in selected:
        for identity in observation.source_exchange_ids:
            exchange = exchanges[identity]
            for ref in (exchange.body, exchange.request_body):
                if ref is not None:
                    raw = artifacts.read_bytes(ref.sha256)
                    if len(raw) != ref.bytes:
                        raise ValueError("evidence artifact size mismatch")
                    refs[ref.sha256] = ref
    bundle = EvidenceBundle(
        source_series_id=source.id,
        observation_ids=tuple(o.id for o in selected),
        artifact_refs=tuple(refs[k] for k in sorted(refs)),
        information_cutoff=information_cutoff,
        mode=mode,
    )
    artifacts.put_bytes(bundle.canonical_bytes())
    return bundle


def available_as_of(
    record_ids: Iterable[str],
    *,
    cutoff: datetime,
    committed_at: Callable[[str], datetime | None],
    dependencies: Callable[[str], Iterable[str]],
    official: Callable[[str], Availability | None] | None = None,
    witnessed_upper: Callable[[str], datetime | None] | None = None,
) -> bool:
    """Check an entire exported closure, including registrations and receipts."""
    cutoff = _utc(cutoff)
    pending = list(record_ids)
    visited: set[str] = set()
    while pending:
        identity = pending.pop()
        if identity in visited:
            continue
        visited.add(identity)
        acknowledged = committed_at(identity)
        if acknowledged is None or _utc(acknowledged) > cutoff:
            return False
        upper = established_upper(
            committed_at=acknowledged,
            official=official(identity) if official else None,
            witnessed_upper=witnessed_upper(identity) if witnessed_upper else None,
        )
        if upper is None or upper > cutoff:
            return False
        pending.extend(dependencies(identity))
    return True
