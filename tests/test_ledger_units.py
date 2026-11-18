"""The resolver's base-unit conversion, and the fixture that holds the site to it."""

from __future__ import annotations

import json
import pathlib
import sys
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_ledger_units_fixture as fixture_gen  # noqa: E402
import ledger_units  # noqa: E402
import mine_ledger_gaps  # noqa: E402
import stamp_docket_ledger_refs as stamper  # noqa: E402

from tests.test_docket_ledger_containment import (  # noqa: E402
    BASE_UNIT as GATE_BASE_UNIT,
)
from tests.test_docket_ledger_containment import _units_agree  # noqa: E402

UNITS = sorted(ledger_units.SCALED_UNITS)

# Every decimal of at most 15 significant digits reads back from a double.
short_decimals = st.builds(
    lambda digits, exponent: float(f"{digits}e{exponent}"),
    st.integers(min_value=-(10**15) + 1, max_value=10**15 - 1),
    st.integers(min_value=-12, max_value=0),
)


def test_committed_fixture_is_what_this_copy_returns() -> None:
    assert fixture_gen.FIXTURE.read_text() == fixture_gen.render(
        fixture_gen.build_fixture()
    ), "site/src/__tests__/fixtures/ledger-units.json is stale; rerun the generator"


def test_the_fixture_refuses_and_converts() -> None:
    cases = json.loads(fixture_gen.FIXTURE.read_text())["cases"]
    assert any(case["result"] is None for case in cases)
    assert sum(case["result"] is not None for case in cases) > len(cases) / 2


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (172, "thousands", 172000),
        (3189.0, "thousands", 3189000),
        (7.716, "millions", 7716000),
        (395.1, "billions USD", 395100000000),
        (395.1, "usd_billions", 395100000000),
        (-7.91746189, "usd_millions", -7917461.89),
        (54.57249153, "usd_millions", 54572491.53),
        (1.1, "thousands", 1100),
        (2.5, "gbp_billions", 2500000000),
        (0.25, "million_cubic_feet", 250000),
        (0, "thousands", 0),
        (-0.0, "millions", 0),
    ],
)
def test_converts_ledger_values_exactly(
    value: float, unit: str, expected: float
) -> None:
    result = ledger_units.to_base(value, unit)
    assert result == expected
    assert type(result) is type(expected)


@pytest.mark.parametrize(
    "value",
    [
        True,
        None,
        "172",
        float("nan"),
        float("inf"),
        10**400,
        2**53,
        1e300,
        0.30000000000000004,
    ],
)
def test_refuses_what_has_no_exact_form(value: object) -> None:
    with pytest.raises(ledger_units.LedgerUnitError):
        ledger_units.to_base(value, "thousands")


def test_base_unit_reads_only_the_table() -> None:
    assert ledger_units.base_unit("thousands") == "count"
    assert ledger_units.base_unit("billions USD") == "usd"
    for other in ("count", "usd", "percent", "units", "", None, 3, ["thousands"]):
        assert ledger_units.base_unit(other) is None


@given(short_decimals, st.sampled_from(UNITS))
def test_short_decimals_convert_exactly_and_back(value: float, unit: str) -> None:
    power = ledger_units.SCALED_UNITS[unit][1]
    exact = Decimal(repr(value)).scaleb(power)
    if abs(exact) > ledger_units.MAX_SAFE_INTEGER:
        with pytest.raises(ledger_units.LedgerUnitError):
            ledger_units.to_base(value, unit)
        return
    result = ledger_units.to_base(value, unit)
    assert Decimal(repr(result)) == exact
    assert ledger_units.shift_decimal(result, -power) == value


@given(st.floats(allow_nan=False, allow_infinity=False), st.sampled_from(UNITS))
def test_any_result_prints_the_decimal_it_claims(value: float, unit: str) -> None:
    power = ledger_units.SCALED_UNITS[unit][1]
    try:
        result = ledger_units.to_base(value, unit)
    except ledger_units.LedgerUnitError:
        return
    assert Decimal(repr(float(result))) == Decimal(repr(value)).scaleb(power)
    assert abs(result) <= ledger_units.MAX_SAFE_INTEGER


def test_the_docket_copies_hold_the_table() -> None:
    table = {unit: base for unit, (base, _) in ledger_units.SCALED_UNITS.items()}
    assert stamper.BASE_UNIT == table
    assert GATE_BASE_UNIT == table


@pytest.mark.parametrize("agree", [stamper.units_agree, _units_agree])
def test_a_scaled_target_agrees_with_the_base_unit_it_stores_in(agree) -> None:
    for unit, (base, _) in ledger_units.SCALED_UNITS.items():
        assert agree(unit, base, None)
        assert agree(unit, base, 0.001)
    # The rule runs one way, and only within a base unit.
    assert not agree("count", "thousands", None)
    assert not agree("usd_billions", "count", None)
    assert not agree("thousands", "usd", None)
    assert not agree("percent", "count", None)
    assert not agree(["thousands"], "count", None)
    # The older rule still reads a catalog that holds scaled units.
    assert agree("millions", "thousands", 0.001)
    assert not agree("millions", "thousands", None)


def test_the_gap_miner_registers_the_unit_the_feed_prints() -> None:
    assert (
        mine_ledger_gaps.registrable_unit(
            {
                "measure": {"unit": "count"},
                "source": {"recorded_value": 172, "recorded_unit": "thousands"},
            }
        )
        == "thousands"
    )
    assert (
        mine_ledger_gaps.registrable_unit(
            {"measure": {"unit": "percent"}, "source": {}}
        )
        == "percent"
    )
    assert mine_ledger_gaps.registrable_unit({"measure": {"unit": "count"}}) == "count"
    assert mine_ledger_gaps.registrable_unit({}) is None
