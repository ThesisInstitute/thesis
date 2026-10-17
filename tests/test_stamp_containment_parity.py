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

import stamp_docket_ledger_refs as stamper  # noqa: E402

from tests.test_docket_ledger_containment import (  # noqa: E402
    CADENCE_MAP,
    _derive_expected_pin,
    _observed_cadence,
)

CONCEPT = "usaspending.parity.series"
DOCKET_CADENCES = ["weekly", "monthly", "quarterly", "annual", "fiscal_year", "daily"]
CATALOG_CADENCES = ["week_ending", "month", "quarter", "year", "fiscal_year", None]
PERIODS = [
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
        "cadence": draw(st.sampled_from(DOCKET_CADENCES)),
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
    """An independent spelling of the rule, for the property below."""

    binding = (entry.get("extras") or {}).get("sourceBinding") or {}
    period = entry.get("period")
    if binding.get("releasePolicy") != "registered_query_snapshot":
        return False
    if not isinstance(period, str):
        return False
    digits = period.lower().removeprefix("fy").removeprefix("_")
    return len(digits) == 4 and digits.isdigit()


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


def test_gate_and_stamper_expect_the_same_cadence() -> None:
    # Exhaustive over every cadence x period x release policy x extras shape.
    assert CADENCE_MAP == stamper.CADENCE_TO_PERIOD_TYPE
    checked = 0
    for cadence in DOCKET_CADENCES:
        for period in PERIODS:
            for policy in POLICIES:
                for extras in (None, {}, {"sourceBinding": {"releasePolicy": policy}}):
                    entry: dict[str, Any] = {"series": CONCEPT, "cadence": cadence}
                    if period is not None:
                        entry["period"] = period
                    if extras is not None:
                        entry["extras"] = extras
                    assert _observed_cadence(entry) == stamper.observed_period_type(
                        entry
                    ), entry
                    checked += 1
    assert checked == len(DOCKET_CADENCES) * len(PERIODS) * len(POLICIES) * 3


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
