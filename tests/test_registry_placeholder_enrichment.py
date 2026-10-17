"""The append guard admits exactly the docket-placeholder enrichment Chronicle's
generator writes, including placeholders whose geography is already known.

Chronicle's scripts/build_series_catalog.py (`_plan_enrichment`, since a93fa9d3
on 2026-08-02) enriches a docket-only row with no entity when its geography is
unknown, or has the observed identity's level and id with no vintage or the
same one. It writes a retire of the placeholder and a succeeds-mint that keeps
the UUID. Until 2026-10-17 `_registry_growth_refusal` admitted only placeholders
with neither geography nor entity. The resolve run of 2026-10-16
(resolve-and-rebuild 38962977031) aborted on
usaspending.cdfi.assistance_transaction_obligations, whose placeholder already
carries country/0100000US.

The fixtures under tests/fixtures/registry_enrichment/ are real generator
output at Chronicle 8c4a0f86; their README says how each was produced.
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
FIXTURES = ROOT / "tests" / "fixtures" / "registry_enrichment"

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


def _catalog(*rows: tuple[str, str, str]) -> bytes:
    """A base catalog holding (concept, uuid, status) rows without an entity."""
    return json.dumps(
        {
            "series": [
                {"concept": concept, "uuid": uuid, "status": status, "entity": None}
                for concept, uuid, status in rows
            ]
        }
    ).encode()


def _enrichment(
    concept: str,
    uuid: str,
    placeholder_geography: dict | None,
    observed_geography: dict,
    observed_entity: dict | None = OBSERVED_ENTITY,
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


# ---------------------------------------------------------------------------
# Real generator output at Chronicle 8c4a0f86.

BASE_REGISTRY = (FIXTURES / "base_registry.jsonl").read_bytes()
BASE_CATALOG = (FIXTURES / "base_catalog_docket_rows.json").read_bytes()


def test_the_fixture_registry_is_chronicles_at_8c4a0f86() -> None:
    import hashlib

    assert hashlib.sha256(BASE_REGISTRY).hexdigest().startswith("272d8fd6b2e82151")
    assert CDFI_LINE in BASE_REGISTRY.splitlines(keepends=True)


@pytest.mark.parametrize(
    ("tail_name", "rows"),
    [
        pytest.param("cdfi_tail.jsonl", [CDFI_ROW], id="cdfi"),
        pytest.param(
            "sweep_tail.jsonl",
            json.loads((FIXTURES / "sweep_rows.json").read_text()),
            id="all-25-geography-placeholders",
        ),
        pytest.param(
            "dod_tail.jsonl",
            [
                "usaspending.dod.prime_award_obligations.fy2026.registered_query_snapshot"
            ],
            id="dod-second-enrichment",
        ),
    ],
)
def test_real_generator_enrichments_are_admitted(tail_name: str, rows: list) -> None:
    """What Chronicle's generator wrote for these placeholders' first
    observations passes, with and without the base catalog."""
    tail = (FIXTURES / tail_name).read_bytes()
    grown = BASE_REGISTRY + tail
    assert refusal(BASE_REGISTRY, grown, rows) is None
    assert refusal(BASE_REGISTRY, grown, rows, BASE_CATALOG) is None


def test_the_sweep_holds_one_pair_per_placeholder() -> None:
    lines = [
        json.loads(line)
        for line in (FIXTURES / "sweep_tail.jsonl").read_text().splitlines()
    ]
    retires = [line for line in lines if line.get("retired") is True]
    succeeds = [line for line in lines if "succeeds" in line]
    assert len(retires) == len(succeeds) == 25 == len(lines) // 2
    assert {line["uuid"] for line in retires} == {line["uuid"] for line in succeeds}


# ---------------------------------------------------------------------------
# Examples.


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
    catalog = _catalog((CDFI, CDFI_UUID, "docket-only"))
    assert refusal(base, grown, [CDFI_ROW], catalog) is None


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
    grown = base + _enrichment(concept, uuid, US_NO_VINTAGE, US_CURRENT)
    assert refusal(base, grown, [row]) is None
    assert "matches no committed docket placeholder" in refusal(
        base, base + _enrichment(concept, uuid, None, US_CURRENT), [row]
    )


def test_geography_free_placeholders_still_enrich() -> None:
    concept = "census.housing.completions_saar"
    uuid = "00000000-0000-4000-8000-000000000002"
    base = _line(concept=concept, geography=None, entity=None, uuid=uuid)
    grown = base + _enrichment(concept, uuid, None, US_CURRENT)
    assert refusal(base, grown, [f"{concept}.2026_07.first_print"]) is None


def test_a_placeholder_written_without_a_vintage_key_is_the_same_identity() -> None:
    """Chronicle's registry accepts a geography without a vintage and keys it
    as vintage none; the generator then retires it with `vintage: null`."""
    base = _line(
        concept=CDFI,
        geography={"level": "country", "id": "0100000US"},
        entity=None,
        uuid=CDFI_UUID,
    )
    grown = base + _enrichment(CDFI, CDFI_UUID, US_NO_VINTAGE, US_CURRENT)
    assert refusal(base, grown, [CDFI_ROW]) is None


def test_an_unrelated_mint_between_the_pair_is_admitted() -> None:
    """The generator writes every placeholder retire, then the sorted mints,
    so a plain first-observation mint can sit between a retire and its
    succeeds."""
    pair = _enrichment(CDFI, CDFI_UUID, US_NO_VINTAGE, US_CURRENT).splitlines(
        keepends=True
    )
    other = _line(
        concept="usaspending.aaa.obligations",
        geography=US_CURRENT,
        entity=OBSERVED_ENTITY,
        uuid="00000000-0000-4000-8000-00000000aaaa",
    )
    grown = CDFI_LINE + pair[0] + other + pair[1]
    rows = [CDFI_ROW, "usaspending.aaa.obligations.fy2026.registered_query_snapshot"]
    assert refusal(CDFI_LINE, grown, rows) is None


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


def test_an_observed_series_without_an_entity_is_not_a_placeholder() -> None:
    """The registry alone cannot tell an observed series that has no entity
    from a docket placeholder; the base catalog can. The generator enriches
    only docket-only rows, so with the catalog the guard refuses the rest."""
    grown = CDFI_LINE + _enrichment(CDFI, CDFI_UUID, US_NO_VINTAGE, US_CURRENT)
    observed = _catalog((CDFI, CDFI_UUID, "observed"))
    assert "no docket-only row" in refusal(CDFI_LINE, grown, [CDFI_ROW], observed)
    other_uuid = _catalog((CDFI, "00000000-0000-4000-8000-0000000000ff", "docket-only"))
    assert "no docket-only row" in refusal(CDFI_LINE, grown, [CDFI_ROW], other_uuid)
    assert "does not list" in refusal(CDFI_LINE, grown, [CDFI_ROW], b"not json")
    assert "does not list" in refusal(CDFI_LINE, grown, [CDFI_ROW], b'{"rows": []}')


def _cdfi_refusal(tail: bytes) -> str | None:
    return refusal(CDFI_LINE, CDFI_LINE + tail, [CDFI_ROW])


CDFI_RETIRE = _line(
    concept=CDFI,
    geography=US_NO_VINTAGE,
    entity=None,
    uuid=CDFI_UUID,
    retired=True,
    note=NOTE,
)


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
        pytest.param(CDFI_RETIRE, "without its succeeds-mint", id="lone-retire"),
        pytest.param(
            CDFI_RETIRE
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
            CDFI_RETIRE
            + _line(
                concept=CDFI,
                geography=US_CURRENT,
                entity=OBSERVED_ENTITY,
                uuid=CDFI_UUID,
                succeeds={
                    "concept": CDFI,
                    "geography": US_NO_VINTAGE,
                    "entity": None,
                    "extra": 1,
                },
            ),
            "names a predecessor other than the placeholder",
            id="succeeds-predecessor-with-extra-field",
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
            CDFI_RETIRE + _enrichment(CDFI, CDFI_UUID, US_NO_VINTAGE, US_CURRENT),
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
            CDFI_RETIRE
            + _line(
                concept=CDFI,
                geography=US_CURRENT,
                entity=OBSERVED_ENTITY,
                uuid="00000000-0000-4000-8000-0000000000ff",
                succeeds={"concept": CDFI, "geography": US_NO_VINTAGE, "entity": None},
            ),
            "keeps no retired placeholder's UUID",
            id="succeeds-under-another-uuid",
        ),
        pytest.param(
            _enrichment(CDFI, CDFI_UUID, US_NO_VINTAGE, US_CURRENT).splitlines(
                keepends=True
            )[1]
            + CDFI_RETIRE,
            "without its placeholder retire",
            id="succeeds-before-retire",
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
            "without a geography or entity",
            id="succeeds-without-entity",
        ),
    ],
)
def test_every_other_shape_is_refused(tail: bytes, diagnostic: str) -> None:
    result = _cdfi_refusal(tail)
    assert result is not None
    assert diagnostic in result


# ---------------------------------------------------------------------------
# Properties. The reference below restates Chronicle's predicate
# (`_plan_enrichment`, `enrichment_shaped`, geography clause, with
# `prior.get("geography") or None` and `geography or {}`) from its source, not
# from `_placeholder_geography_admits`; the two are checked against each other.


def _chronicle_admits(placeholder: dict | None, observed: dict | None) -> bool:
    prior_geo = placeholder or None
    geo = observed or {}
    return prior_geo is None or (
        (prior_geo.get("level"), prior_geo.get("id"))
        == (geo.get("level"), geo.get("id"))
        and prior_geo.get("vintage") in (None, geo.get("vintage"))
    )


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
NEIGHBOURS = st.lists(
    st.tuples(
        UUIDS,
        st.booleans(),  # same concept as the placeholder?
        PLACEHOLDER_GEOGRAPHIES,
        st.none() | ENTITIES,
    ),
    max_size=4,
    unique_by=lambda neighbour: neighbour[0],
)


def _neighbour_lines(
    concept: str,
    uuid: str,
    placeholder: dict | None,
    neighbours: list,
) -> bytes:
    lines = []
    for index, (other, same_concept, geography, entity) in enumerate(neighbours):
        if other == uuid:
            continue
        if same_concept and _identity(concept, geography, entity) == _identity(
            concept, placeholder, None
        ):
            # One identity binds one UUID: Chronicle refuses a base that splits it.
            continue
        lines.append(
            _line(
                concept=concept if same_concept else f"other.series_{index}",
                geography=geography,
                entity=entity,
                uuid=other,
            )
        )
    return b"".join(lines)


def _identity(concept: str, geography: dict | None, entity: dict | None):
    return (concept, json.dumps(geography, sort_keys=True), json.dumps(entity))


@settings(max_examples=400, deadline=None)
@given(
    concept=CONCEPTS,
    uuid=UUIDS,
    placeholder=PLACEHOLDER_GEOGRAPHIES,
    observed=OBSERVED_GEOGRAPHIES,
    entity=ENTITIES,
    neighbours=NEIGHBOURS,
    with_catalog=st.booleans(),
)
def test_the_guard_admits_an_enrichment_exactly_when_chronicle_would(
    concept: str,
    uuid: str,
    placeholder: dict | None,
    observed: dict,
    entity: dict,
    neighbours: list,
    with_catalog: bool,
) -> None:
    """Differential: for the pair the generator writes, the guard agrees with
    Chronicle's geography rule on every placeholder/observation combination.
    Other committed identities (other concepts, or the same concept in other
    geographies, with or without an entity) never change the verdict."""
    base = _neighbour_lines(concept, uuid, placeholder, neighbours) + _line(
        concept=concept, geography=placeholder, entity=None, uuid=uuid
    )
    grown = base + _enrichment(concept, uuid, placeholder, observed, entity)
    catalog = _catalog((concept, uuid, "docket-only")) if with_catalog else None
    result = refusal(base, grown, [f"{concept}.fy2026.first_print"], catalog)
    if _chronicle_admits(placeholder, observed):
        assert result is None
    else:
        assert result is not None and "does not admit" in result


MUTATIONS = {
    # mutation: diagnostic the guard must give
    "retire_uuid": "matches no committed docket placeholder",
    "retire_geography": "matches no committed docket placeholder",
    "retire_entity": "non-placeholder",
    "both_uuid": "matches no committed docket placeholder",
    "both_placeholder_geography": "matches no committed docket placeholder",
    "succeeds_uuid": "keeps no retired placeholder's UUID",
    "succeeds_concept": "without its placeholder retire",
    "succeeds_predecessor": "names a predecessor other than the placeholder",
    "succeeds_entity_none": "without a geography or entity",
    "drop_succeeds": "without its succeeds-mint",
    "drop_retire": "without its placeholder retire",
    "duplicate_retire": "retires the placeholder",
    "duplicate_succeeds": "enriches the placeholder",
    "swap_order": "without its placeholder retire",
}


@settings(max_examples=400, deadline=None)
@given(
    uuid=UUIDS,
    other_uuid=UUIDS,
    placeholder=PLACEHOLDER_GEOGRAPHIES,
    observed=OBSERVED_GEOGRAPHIES,
    mutation=st.sampled_from(sorted(MUTATIONS)),
)
def test_any_departure_from_the_generators_pair_is_refused_by_name(
    uuid: str,
    other_uuid: str,
    placeholder: dict | None,
    observed: dict,
    mutation: str,
) -> None:
    """Soundness: change any one thing about an admitted pair, on one line or
    consistently on both, and the guard refuses it with the diagnostic for
    that change. (Admission itself is the differential test above.)"""
    if not _chronicle_admits(placeholder, observed) or other_uuid == uuid:
        return
    concept = "irs.actc.total_claims"
    base = _line(concept=concept, geography=placeholder, entity=None, uuid=uuid)
    moved_geography = (
        {"level": "county", "id": "0500000US06037", "vintage": "2023"}
        if placeholder is None
        else None
    )
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
        retire["geography"] = moved_geography
    elif mutation == "retire_entity":
        retire["entity"] = OBSERVED_ENTITY
    elif mutation == "both_uuid":
        retire["uuid"] = succeeds["uuid"] = other_uuid
    elif mutation == "both_placeholder_geography":
        retire["geography"] = moved_geography
        succeeds["succeeds"] = dict(succeeds["succeeds"], geography=moved_geography)
    elif mutation == "succeeds_uuid":
        succeeds["uuid"] = other_uuid
    elif mutation == "succeeds_concept":
        succeeds["concept"] = "irs.actc.total_credit_amount"
    elif mutation == "succeeds_predecessor":
        succeeds["succeeds"] = dict(succeeds["succeeds"], geography=moved_geography)
    elif mutation == "succeeds_entity_none":
        succeeds["entity"] = None
    elif mutation == "drop_succeeds":
        lines = [retire]
    elif mutation == "drop_retire":
        lines = [succeeds]
    elif mutation == "duplicate_retire":
        lines = [retire, retire, succeeds]
    elif mutation == "duplicate_succeeds":
        lines = [retire, succeeds, succeeds]
    elif mutation == "swap_order":
        lines = [succeeds, retire]
    grown = base + b"".join(_line(**line) for line in lines)
    rows = ["irs.actc.total_claims.ty2025", "irs.actc.total_credit_amount.ty2025"]
    result = refusal(base, grown, rows)
    assert result is not None
    assert MUTATIONS[mutation] in result, (mutation, result)


# ---------------------------------------------------------------------------
# The append path hands the guard the catalog as committed. The generator
# rewrites that file (an enriched row stops being docket-only), so it must be
# read before the generator runs.


def _stage(tmp_path: pathlib.Path, status: str) -> tuple[pathlib.Path, bytes]:
    stage = tmp_path / "stage"
    (stage / "scripts").mkdir(parents=True)
    (stage / "ledger").mkdir()
    (stage / "ledger" / "series_uuid_registry.jsonl").write_bytes(CDFI_LINE)
    (stage / "ledger" / "series_catalog.json").write_bytes(
        _catalog((CDFI, CDFI_UUID, status))
    )
    pair = _enrichment(CDFI, CDFI_UUID, US_NO_VINTAGE, US_CURRENT)
    rewritten = _catalog((CDFI, CDFI_UUID, "observed"))
    (stage / "scripts" / "build_series_catalog.py").write_text(
        "import pathlib\n"
        "registry = pathlib.Path('ledger/series_uuid_registry.jsonl')\n"
        f"registry.write_bytes(registry.read_bytes() + {pair!r})\n"
        "pathlib.Path('ledger/series_catalog.json').write_bytes("
        f"{rewritten!r})\n"
    )
    return stage, CDFI_LINE


def test_the_append_path_checks_the_committed_catalog_not_the_regenerated_one(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        resolve_pending, "_validate_catalog_binding", lambda *a, **k: None
    )
    stage, base = _stage(tmp_path, "docket-only")
    catalog = resolve_pending._regenerate_series_catalog(
        stage, candidate_ledger=b"", base_registry=base, appended_row_ids=[CDFI_ROW]
    )
    assert json.loads(catalog)["series"][0]["status"] == "observed"


def test_the_append_path_refuses_to_enrich_a_row_the_committed_catalog_observes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        resolve_pending, "_validate_catalog_binding", lambda *a, **k: None
    )
    stage, base = _stage(tmp_path, "observed")
    with pytest.raises(resolve_pending.LedgerProposalError, match="no docket-only row"):
        resolve_pending._regenerate_series_catalog(
            stage, candidate_ledger=b"", base_registry=base, appended_row_ids=[CDFI_ROW]
        )
