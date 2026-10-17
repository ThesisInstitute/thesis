"""The containment gate and the docket stamper must pick the same pin.

The gate re-derives every docket pin with its own copy of the stamper's
rules, deliberately by duplication, so it never imports the tool it audits.
Copies drift: on 2026-08-01 the stamper learned ``fiscal_year`` and the gate
did not, and on 2026-10-17 the five DoD USAspending FY2026 snapshots turned
the gate red. These properties hold the two copies to one semantics.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import roll_docket  # noqa: E402
import stamp_docket_ledger_refs as stamper  # noqa: E402

from tests.test_docket_ledger_containment import (  # noqa: E402
    CADENCE_MAP,
    DOCKET_CADENCES,
    _derive_expected_pin,
    _observed_cadence,
)

CONCEPT = "usaspending.parity.series"
CADENCE_DRAWS = ["weekly", "monthly", "quarterly", "annual", "fiscal_year", "daily"]
CATALOG_CADENCES = ["week_ending", "month", "quarter", "year", "fiscal_year", None]
PERIODS: list[object] = [
    None,
    "2026",
    "FY2026",
    "fy_2026",
    "Fy2027",
    "fy2026x",
    "2026-05",
    "26",
    "CY2026",
    "2025-2026",
    "FY_2026",
    "fy__2026",
    "_2027",
    "²⁰²⁷",
    "fy_²⁰²⁷",
    2026,
    True,
    ["2026"],
]
POLICIES = [None, "registered_query_snapshot", "first_print"]
UNITS = [None, "percent", "millions", "thousands", "billions USD"]
GEOGRAPHY_IDS = ["0100000US", "CA", "GB"]
COUNTRIES = [None, "US", "CA", "ZZ"]
SOURCES = ["a", "b"]
FIRSTS = [None, "2025", "2026"]


@st.composite
def entries(draw: st.DrawFn) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    policy = draw(st.sampled_from(POLICIES))
    source = draw(st.sampled_from([None, *SOURCES]))
    if policy is not None or source is not None:
        binding: dict[str, Any] = {}
        if policy is not None:
            binding["releasePolicy"] = policy
        if source is not None:
            binding["sourceSeriesId"] = source
        extras["sourceBinding"] = binding
    unit = draw(st.sampled_from(UNITS))
    if unit is not None:
        extras["targetUnit"] = unit
    if draw(st.booleans()):
        extras["valueScale"] = draw(st.sampled_from([0.001, 1e-6, 1e-9]))
    country = draw(st.sampled_from(COUNTRIES))
    if country is not None:
        extras["country"] = country
    entry: dict[str, Any] = {
        "series": CONCEPT,
        "cadence": draw(st.sampled_from(CADENCE_DRAWS)),
        "slug": "s",
    }
    period = draw(st.sampled_from(PERIODS))
    if period is not None:
        entry["period"] = period
    if extras or draw(st.booleans()):
        entry["extras"] = extras
    return entry


@st.composite
def catalog_rows(draw: st.DrawFn) -> list[dict[str, Any]]:
    count = draw(st.integers(min_value=1, max_value=4))
    rows = []
    for index in range(count):
        placeholder = draw(st.booleans())
        rows.append(
            {
                "uuid": f"00000000-0000-4000-8000-{index:012d}",
                "concept": CONCEPT,
                "status": "docket-only" if placeholder else "observed",
                "cadence": draw(st.sampled_from(CATALOG_CADENCES)),
                "unit": draw(st.sampled_from(UNITS)),
                "geography": {
                    "level": draw(st.sampled_from(["country", "state"])),
                    "id": draw(st.sampled_from(GEOGRAPHY_IDS)),
                    "vintage": "current",
                },
                "entity": None if placeholder else {"name": "e", "role": "r"},
                "source_concepts": draw(
                    st.lists(st.sampled_from(SOURCES), unique=True, max_size=2)
                ),
                "first_observed_period": (
                    None if placeholder else draw(st.sampled_from(FIRSTS))
                ),
                "aliases": [],
            }
        )
    return rows


def _is_fiscal_year_snapshot(entry: dict[str, Any]) -> bool:
    """An independent spelling of the rule's period grammar, for C1 below.

    A fiscal-year period is four decimal digits (what ``\\d`` matches, i.e.
    ``str.isdecimal``), optionally after a case-insensitive ``fy`` prefix,
    which may itself be followed by one underscore.
    """

    extras = entry.get("extras")
    binding = extras.get("sourceBinding") if isinstance(extras, dict) else None
    if not isinstance(binding, dict):
        return False
    if binding.get("releasePolicy") != "registered_query_snapshot":
        return False
    period = entry.get("period")
    if not isinstance(period, str):
        return False
    rest = period
    if rest[:2].lower() == "fy":
        rest = rest[2:]
        if rest[:1] == "_":
            rest = rest[1:]
    return len(rest) == 4 and rest.isdecimal()


@settings(max_examples=2000, deadline=None)
@given(entries())
def test_only_annual_fiscal_year_snapshots_change_cadence(
    entry: dict[str, Any],
) -> None:
    docket_cadence = CADENCE_MAP.get(entry["cadence"])
    if entry["cadence"] == "annual" and _is_fiscal_year_snapshot(entry):
        assert _observed_cadence(entry) == "fiscal_year"
    else:
        assert _observed_cadence(entry) == docket_cadence


EXTRAS_SHAPES: list[object] = [
    "absent",
    None,
    {},
    "policy",
    "binding-list",
    [1],
    "x",
]


def _entry(cadence: object, period: object, policy: object, shape: object) -> dict:
    entry: dict[str, Any] = {"series": CONCEPT, "cadence": cadence}
    if period is not None:
        entry["period"] = period
    if shape == "policy":
        entry["extras"] = {"sourceBinding": {"releasePolicy": policy}}
    elif shape == "binding-list":
        entry["extras"] = {"sourceBinding": [policy]}
    elif shape != "absent":
        entry["extras"] = shape
    return entry


def test_gate_and_stamper_expect_the_same_cadence() -> None:
    # Exhaustive over cadence x period x release policy x extras shape,
    # including non-string cadences and periods and non-dict extras and
    # bindings. Also checks the rule against the independent oracle.
    assert CADENCE_MAP == stamper.CADENCE_TO_PERIOD_TYPE
    cadences: list[object] = [*CADENCE_DRAWS, None, ["annual"]]
    checked = 0
    for cadence in cadences:
        for period in PERIODS:
            for policy in POLICIES:
                for shape in EXTRAS_SHAPES:
                    entry = _entry(cadence, period, policy, shape)
                    gate = _observed_cadence(entry)
                    assert gate == stamper.observed_period_type(entry), entry
                    if cadence == "annual" and _is_fiscal_year_snapshot(entry):
                        assert gate == "fiscal_year", entry
                    elif isinstance(cadence, str):
                        assert gate == CADENCE_MAP.get(cadence), entry
                    else:
                        assert gate is None, entry
                    checked += 1
    assert checked == len(cadences) * len(PERIODS) * len(POLICIES) * len(EXTRAS_SHAPES)


def test_gate_docket_cadences_are_the_ones_the_roller_rolls() -> None:
    sample = {
        "weekly": "week_2026-10-05",
        "monthly": "2026-10",
        "quarterly": "2026-Q3",
        "annual": "2026",
        "fiscal_year": "2026",
    }
    rolled = {
        cadence
        for cadence, period in sample.items()
        if roll_docket.period_key(period, cadence) is not None
    }
    assert DOCKET_CADENCES == rolled
    assert set(DOCKET_CADENCES) < set(CADENCE_MAP)


@settings(max_examples=3000, deadline=None)
@given(entries(), catalog_rows())
def test_gate_and_stamper_pick_the_same_pin(
    entry: dict[str, Any], rows: list[dict[str, Any]]
) -> None:
    gate_row, _ = _derive_expected_pin(entry, {CONCEPT: rows})
    stamped_row, _ = stamper._resolve_concept_candidates(entry, rows)
    gate_uuid = gate_row["uuid"] if gate_row else None
    stamped_uuid = stamped_row["uuid"] if stamped_row else None
    assert gate_uuid == stamped_uuid
