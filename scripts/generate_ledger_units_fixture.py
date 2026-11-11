#!/usr/bin/env python3
"""Write the fixture that holds the site's unit conversion to the resolver's.

The resolver converts a scaled value to base units with
``scripts/ledger_units.py``, and the site checks that conversion with
``site/src/data/ledger-units.ts``. This script records what the Python copy
returns over the table, real ledger values, seeded decimals of every length a
double can print, and values neither copy can store. A Vitest replays the record
against the TypeScript copy.

The output is deterministic. ``--check`` regenerates it in memory and exits 1 if
the committed fixture differs, which tests/test_ledger_units.py runs in CI.

    python3 scripts/generate_ledger_units_fixture.py [--check]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
from typing import Any

import ledger_units

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "site" / "src" / "__tests__" / "fixtures" / "ledger-units.json"

# Values the ledger holds, the three that keep cents among them.
REAL_VALUES: list[int | float] = [
    172,
    3189.0,
    395.1,
    7.716,
    0.1,
    -7.91746189,
    54.57249153,
    -30.07719821,
]
# Zeros, values that stop being exact, and values past what either copy stores.
EDGE_VALUES: list[int | float] = [
    0,
    0.0,
    -0.0,
    1,
    1.1,
    0.30000000000000004,
    1.0000000000000002,
    9007199254740.991,
    9007199254740.992,
    9007199254740991,
    4503599627370495.5,
    1e15,
    1e-7,
    1.5e300,
    1.5e308,
    5e-324,
]


def seeded_values() -> list[float]:
    seeded = random.Random(20261103)
    values = []
    for length in range(1, 18):
        for exponent in (-9, -3, 0, 3):
            digits = seeded.randrange(10 ** (length - 1), 10**length)
            sign = seeded.choice(("", "-"))
            values.append(float(f"{sign}{digits}e{exponent}"))
    return values


def build_fixture() -> dict[str, Any]:
    cases = []
    values = [*REAL_VALUES, *EDGE_VALUES, *seeded_values()]
    for unit in ledger_units.SCALED_UNITS:
        for value in values:
            try:
                result: int | float | None = ledger_units.to_base(value, unit)
            except ledger_units.LedgerUnitError:
                result = None
            cases.append({"value": value, "unit": unit, "result": result})
    return {
        "table": {
            unit: {"base": base, "power": power}
            for unit, (base, power) in ledger_units.SCALED_UNITS.items()
        },
        "cases": cases,
    }


def render(fixture: dict[str, Any]) -> str:
    table = ",\n".join(
        f"    {json.dumps(unit)}: {json.dumps(scale)}"
        for unit, scale in fixture["table"].items()
    )
    cases = ",\n".join(f"    {json.dumps(case)}" for case in fixture["cases"])
    return f'{{\n  "table": {{\n{table}\n  }},\n  "cases": [\n{cases}\n  ]\n}}\n'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render(build_fixture())
    if args.check:
        if not FIXTURE.exists() or FIXTURE.read_text() != rendered:
            print(f"{FIXTURE} is stale; rerun this script", file=sys.stderr)
            return 1
        return 0
    FIXTURE.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
