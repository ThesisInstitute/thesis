"""The append guard admits exactly the docket-placeholder enrichment Chronicle's
generator writes, including placeholders whose geography is already known.

Chronicle's scripts/build_series_catalog.py (`_plan_enrichment`, since a93fa9d3
on 2026-08-02) enriches a docket-only row with no entity when its geography is
unknown, or has the observed identity's level and id with no vintage or the
same one. It writes a retire of the placeholder and a succeeds-mint that keeps
the UUID. Until 2026-10-16 `_registry_growth_refusal` admitted only placeholders
with neither geography nor entity. The resolve run of that day
(resolve-and-rebuild 38962977031) aborted on
usaspending.cdfi.assistance_transaction_obligations, whose placeholder already
carries country/0100000US.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolve_pending  # noqa: E402

refusal = resolve_pending._registry_growth_refusal

NOTE = "docket placeholder enriched by first observed identity"
OBSERVED_ENTITY = {"name": "economy", "role": "aggregate"}
US_CURRENT = {"level": "country", "id": "0100000US", "vintage": "current"}
US_NO_VINTAGE = {"level": "country", "id": "0100000US", "vintage": None}

# Chronicle ledger/series_uuid_registry.jsonl line 233 at 8c4a0f86, verbatim.
CDFI = "usaspending.cdfi.assistance_transaction_obligations"
CDFI_UUID = "69834e1f-1fbf-432c-9913-6b391321b3a8"
CDFI_LINE = (
    b'{"concept": "usaspending.cdfi.assistance_transaction_obligations", '
    b'"geography": {"level": "country", "id": "0100000US", "vintage": null}, '
    b'"entity": null, "uuid": "69834e1f-1fbf-432c-9913-6b391321b3a8"}\n'
)
CDFI_ROW = f"{CDFI}.fy2026.registered_query_snapshot"


def _line(**fields) -> bytes:
    return json.dumps(fields).encode() + b"\n"


def _enrichment(
    concept: str,
    uuid: str,
    placeholder_geography: dict | None,
    observed_geography: dict,
    observed_entity: dict = OBSERVED_ENTITY,
) -> bytes:
    """The retire + succeeds pair `_plan_enrichment` writes: both events come
    from `_registry_event`, whose geography is `_identity_geography`
    (level, id, vintage) of the catalog row and of the observation."""
    return _line(
        concept=concept,
        geography=placeholder_geography,
        entity=None,
        uuid=uuid,
        retired=True,
        note=NOTE,
    ) + _line(
        concept=concept,
        geography=observed_geography,
        entity=observed_entity,
        uuid=uuid,
        succeeds={
            "concept": concept,
            "geography": placeholder_geography,
            "entity": None,
        },
    )


def test_the_cdfi_placeholder_takes_its_first_observation() -> None:
    """The production refusal of 2026-10-16, now admitted."""
    base = (
        _line(
            concept="dol.eta.continued_claims.sa",
            geography=US_CURRENT,
            entity={"name": "person", "role": "ui_claimant"},
            uuid="00000000-0000-4000-8000-000000000001",
        )
        + CDFI_LINE
    )
    grown = base + _enrichment(CDFI, CDFI_UUID, US_NO_VINTAGE, US_CURRENT)
    assert refusal(base, grown, [CDFI_ROW]) is None


def test_a_placeholder_enriched_once_can_be_enriched_again() -> None:
    """usaspending.dod.prime_award_obligations went from neither geography nor
    entity to a known geography (registry lines 196, 249, 250). Its live
    binding is that geography-only identity, so it is the placeholder now; the
    old geography-free one is retired and cannot be retired again."""
    concept = "usaspending.dod.prime_award_obligations"
    uuid = "a2649fd9-f382-4003-ba70-01030bc93b5e"
    row = f"{concept}.fy2026.registered_query_snapshot"
    base = (
        _line(concept=concept, geography=None, entity=None, uuid=uuid)
        + _line(
            concept=concept,
            geography=None,
            entity=None,
            uuid=uuid,
            retired=True,
            note=NOTE,
        )
        + _line(
            concept=concept,
            geography=US_NO_VINTAGE,
            entity=None,
            uuid=uuid,
            succeeds={"concept": concept, "geography": None, "entity": None},
        )
    )
    assert (
        refusal(
            base, base + _enrichment(concept, uuid, US_NO_VINTAGE, US_CURRENT), [row]
        )
        is None
    )
    assert "matches no committed docket placeholder" in refusal(
        base, base + _enrichment(concept, uuid, None, US_CURRENT), [row]
    )


def test_geography_free_placeholders_still_enrich() -> None:
    concept = "census.housing.completions_saar"
    uuid = "00000000-0000-4000-8000-000000000002"
    base = _line(concept=concept, geography=None, entity=None, uuid=uuid)
    grown = base + _enrichment(concept, uuid, None, US_CURRENT)
    assert refusal(base, grown, [f"{concept}.2026_07.first_print"]) is None


def _cdfi_refusal(tail: bytes) -> str | None:
    return refusal(CDFI_LINE, CDFI_LINE + tail, [CDFI_ROW])


@pytest.mark.parametrize(
    ("tail", "diagnostic"),
    [
        pytest.param(
            _enrichment(
                CDFI,
                CDFI_UUID,
                US_NO_VINTAGE,
                {"level": "country", "id": "0400000US06", "vintage": "current"},
            ),
            "does not admit",
            id="different-id",
        ),
        pytest.param(
            _enrichment(
                CDFI,
                CDFI_UUID,
                US_NO_VINTAGE,
                {"level": "state", "id": "0100000US", "vintage": "current"},
            ),
            "does not admit",
            id="different-level",
        ),
        pytest.param(
            _enrichment(
                CDFI,
                CDFI_UUID,
                {"level": "country", "id": "0100000US", "vintage": "2020"},
                US_CURRENT,
            ),
            "matches no committed docket placeholder",
            id="retire-names-another-geography",
        ),
        pytest.param(
            _line(
                concept=CDFI,
                geography=US_NO_VINTAGE,
                entity=None,
                uuid=CDFI_UUID,
                retired=True,
                note=NOTE,
            ),
            "without its succeeds-mint",
            id="lone-retire",
        ),
        pytest.param(
            _line(
                concept=CDFI,
                geography=US_NO_VINTAGE,
                entity=None,
                uuid=CDFI_UUID,
                retired=True,
                note=NOTE,
            )
            + _line(
                concept=CDFI,
                geography=US_CURRENT,
                entity=OBSERVED_ENTITY,
                uuid=CDFI_UUID,
                succeeds={"concept": CDFI, "geography": None, "entity": None},
            ),
            "names a predecessor other than the placeholder",
            id="succeeds-names-another-predecessor",
        ),
        pytest.param(
            _enrichment(CDFI, CDFI_UUID, US_NO_VINTAGE, US_CURRENT)
            + _line(
                concept=CDFI,
                geography=US_CURRENT,
                entity=OBSERVED_ENTITY,
                uuid=CDFI_UUID,
                succeeds={"concept": CDFI, "geography": US_NO_VINTAGE, "entity": None},
            ),
            "enriches the placeholder",
            id="second-succeeds",
        ),
        pytest.param(
            _line(
                concept=CDFI,
                geography=US_NO_VINTAGE,
                entity=None,
                uuid=CDFI_UUID,
                retired=True,
                note=NOTE,
            )
            + _enrichment(CDFI, CDFI_UUID, US_NO_VINTAGE, US_CURRENT),
            "retires the placeholder",
            id="second-retire",
        ),
        pytest.param(
            _enrichment(
                CDFI,
                "00000000-0000-4000-8000-0000000000ff",
                US_NO_VINTAGE,
                US_CURRENT,
            ),
            "matches no committed docket placeholder",
            id="retire-under-another-uuid",
        ),
        pytest.param(
            _line(
                concept=CDFI,
                geography=US_NO_VINTAGE,
                entity=OBSERVED_ENTITY,
                uuid=CDFI_UUID,
                retired=True,
                note=NOTE,
            ),
            "non-placeholder",
            id="retire-with-entity",
        ),
        pytest.param(
            _enrichment(CDFI, CDFI_UUID, US_NO_VINTAGE, US_CURRENT, None),
            "mints a placeholder identity",
            id="succeeds-without-entity",
        ),
    ],
)
def test_every_other_shape_is_refused(tail: bytes, diagnostic: str) -> None:
    result = _cdfi_refusal(tail)
    assert result is not None
    assert diagnostic in result


def test_an_observed_identity_is_never_a_placeholder() -> None:
    """A live binding with an entity is a full identity; an append may not
    retire it, whatever its geography."""
    base = _line(
        concept=CDFI, geography=US_CURRENT, entity=OBSERVED_ENTITY, uuid=CDFI_UUID
    )
    grown = base + _line(
        concept=CDFI,
        geography=US_CURRENT,
        entity=OBSERVED_ENTITY,
        uuid=CDFI_UUID,
        retired=True,
        note=NOTE,
    )
    assert "non-placeholder" in refusal(base, grown, [CDFI_ROW])


# Property tests. The reference below restates Chronicle's predicate
# (`_plan_enrichment`, `enrichment_shaped`, geography clause) independently of
# `_placeholder_geography_admits`, so the two are checked against each other.


def _chronicle_admits(placeholder: dict | None, observed: dict) -> bool:
    if placeholder is None:
        return True
    same_place = (placeholder["level"], placeholder["id"]) == (
        observed["level"],
        observed["id"],
    )
    return same_place and placeholder["vintage"] in (None, observed["vintage"])


LEVELS = st.sampled_from(["country", "state", "county"])
IDS = st.sampled_from(["0100000US", "0400000US06", "0500000US06037"])
VINTAGES = st.sampled_from([None, "current", "2020", "2023"])
OBSERVED_GEOGRAPHIES = st.fixed_dictionaries(
    {"level": LEVELS, "id": IDS, "vintage": st.sampled_from(["current", "2020"])}
)
PLACEHOLDER_GEOGRAPHIES = st.none() | st.fixed_dictionaries(
    {"level": LEVELS, "id": IDS, "vintage": VINTAGES}
)
ENTITIES = st.fixed_dictionaries(
    {
        "name": st.sampled_from(["economy", "person", "household"]),
        "role": st.sampled_from(["aggregate", "civilian_labor_force"]),
    }
)
CONCEPTS = st.sampled_from(
    [
        CDFI,
        "irs.actc.total_claims",
        "nbb.gdp.flash_qoq",
        "census.spm.child_poverty_rate",
    ]
)
UUIDS = st.uuids(version=4).map(str)


@settings(max_examples=300, deadline=None)
@given(
    concept=CONCEPTS,
    uuid=UUIDS,
    placeholder=PLACEHOLDER_GEOGRAPHIES,
    observed=OBSERVED_GEOGRAPHIES,
    entity=ENTITIES,
    neighbours=st.lists(
        st.tuples(UUIDS, PLACEHOLDER_GEOGRAPHIES), max_size=3, unique_by=lambda t: t[0]
    ),
)
def test_the_guard_admits_an_enrichment_exactly_when_chronicle_would(
    concept: str,
    uuid: str,
    placeholder: dict | None,
    observed: dict,
    entity: dict,
    neighbours: list[tuple[str, dict | None]],
) -> None:
    """Differential: for the pair the generator writes, the guard agrees with
    Chronicle's geography rule on every placeholder/observation combination,
    and unrelated committed placeholders never change the verdict."""
    base = b"".join(
        _line(
            concept=f"other.series_{index}",
            geography=geography,
            entity=None,
            uuid=other,
        )
        for index, (other, geography) in enumerate(neighbours)
        if other != uuid
    ) + _line(concept=concept, geography=placeholder, entity=None, uuid=uuid)
    grown = base + _enrichment(concept, uuid, placeholder, observed, entity)
    result = refusal(base, grown, [f"{concept}.fy2026.first_print"])
    if _chronicle_admits(placeholder, observed):
        assert result is None
    else:
        assert result is not None and "does not admit" in result


MUTATIONS = [
    "retire_uuid",
    "retire_geography",
    "retire_entity",
    "succeeds_uuid",
    "succeeds_concept",
    "succeeds_predecessor",
    "drop_succeeds",
    "drop_retire",
    "duplicate_retire",
]


@settings(max_examples=300, deadline=None)
@given(
    uuid=UUIDS,
    other_uuid=UUIDS,
    placeholder=PLACEHOLDER_GEOGRAPHIES,
    observed=OBSERVED_GEOGRAPHIES,
    mutation=st.sampled_from(MUTATIONS),
)
def test_any_departure_from_the_generators_pair_is_refused(
    uuid: str,
    other_uuid: str,
    placeholder: dict | None,
    observed: dict,
    mutation: str,
) -> None:
    """Soundness: change any one thing about an admitted pair and the guard
    refuses it. (Admission itself is the differential test above.)"""
    if not _chronicle_admits(placeholder, observed) or other_uuid == uuid:
        return
    concept = "irs.actc.total_claims"
    base = _line(concept=concept, geography=placeholder, entity=None, uuid=uuid)
    retire = dict(
        concept=concept,
        geography=placeholder,
        entity=None,
        uuid=uuid,
        retired=True,
        note=NOTE,
    )
    succeeds = dict(
        concept=concept,
        geography=observed,
        entity=OBSERVED_ENTITY,
        uuid=uuid,
        succeeds={"concept": concept, "geography": placeholder, "entity": None},
    )
    lines = [retire, succeeds]
    if mutation == "retire_uuid":
        retire["uuid"] = other_uuid
    elif mutation == "retire_geography":
        retire["geography"] = (
            {"level": "county", "id": "0500000US06037", "vintage": "2023"}
            if placeholder is None
            else None
        )
    elif mutation == "retire_entity":
        retire["entity"] = OBSERVED_ENTITY
    elif mutation == "succeeds_uuid":
        succeeds["uuid"] = other_uuid
    elif mutation == "succeeds_concept":
        succeeds["concept"] = "irs.actc.total_credit_amount"
    elif mutation == "succeeds_predecessor":
        succeeds["succeeds"] = {
            "concept": concept,
            "geography": None if placeholder is not None else US_NO_VINTAGE,
            "entity": None,
        }
    elif mutation == "drop_succeeds":
        lines = [retire]
    elif mutation == "drop_retire":
        lines = [succeeds]
    elif mutation == "duplicate_retire":
        lines = [retire, retire, succeeds]
    grown = base + b"".join(_line(**line) for line in lines)
    rows = ["irs.actc.total_claims.ty2025", "irs.actc.total_credit_amount.ty2025"]
    assert refusal(base, grown, rows) is not None
