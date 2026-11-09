#!/usr/bin/env python3
"""Chronicle's base units: what each scaled unit measures and how many it holds.

Chronicle stores plain numbers, so a current fact's ``measure.unit`` holds no
scale word, while a registered forecast contract keeps the unit it registered.
``site/src/data/ledger-units.ts`` holds the same table and the same conversion;
``scripts/generate_ledger_units_fixture.py`` records what this copy returns, and
a Vitest holds that copy to the record.
"""

from __future__ import annotations

import math
from decimal import Decimal, localcontext

SCALED_UNITS: dict[str, tuple[str, int]] = {
    "thousands": ("count", 3),
    "millions": ("count", 6),
    "usd_millions": ("usd", 6),
    "usd_billions": ("usd", 9),
    # The spelling the DoD USAspending registrations carry (units.ts).
    "billions USD": ("usd", 9),
    "gbp_billions": ("gbp", 9),
    "million_cubic_feet": ("cubic_feet", 6),
}

MAX_SAFE_INTEGER = 2**53 - 1


class LedgerUnitError(ValueError):
    """A value has no exact form in the unit asked for."""


def base_unit(unit: object) -> str | None:
    """The base unit of a scaled unit, or None for any other value."""

    if isinstance(unit, str) and unit in SCALED_UNITS:
        return SCALED_UNITS[unit][0]
    return None


def shift_decimal(value: object, power: int) -> int | float:
    """The number whose shortest decimal is ``value``'s, moved ``power`` places.

    Refuses a result that would store a different decimal, and an integer past
    2**53 - 1, which a JSON reader built on doubles cannot read back. An exact
    integer result comes back as an int, so it prints with no ``.0``.
    """

    if not (
        (type(value) is float and math.isfinite(value))
        or (type(value) is int and abs(value) <= MAX_SAFE_INTEGER)
    ):
        raise LedgerUnitError(f"{value!r} has no decimal value to shift")
    if value == 0:
        return 0
    with localcontext() as context:
        # A double prints at most 17 digits, and a scale moves them, so 40 holds
        # every result whose digits could store.
        context.prec = 40
        exact = Decimal(repr(value)).scaleb(power)
        shifted = int(exact) if exact == exact.to_integral_value() else float(exact)
        stored = float(shifted) if abs(shifted) <= MAX_SAFE_INTEGER else None
        if stored is None or stored == 0 or Decimal(repr(stored)) != exact:
            raise LedgerUnitError(
                f"{value!r} moved {power} places does not store exactly"
            )
    return shifted


def to_base(value: object, unit: str) -> int | float:
    """This value in its unit's base unit, exactly, or a refusal."""

    return shift_decimal(value, SCALED_UNITS[unit][1])
