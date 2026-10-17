"""Every unit the Python side can write must be one the site accepts.

2026-10-17: the resolver appended a ledger row in the registered unit
"billions USD" and every production build at that pin failed, because the
site's ledger-fact check kept its own unit list. The site now reads one list,
``site/src/data/units.ts``; these tests hold the resolver and the cell
generator to it.
"""

from __future__ import annotations

import pathlib
import re
import sys
from typing import Any, Iterator

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolve_pending  # noqa: E402
import spawned_cells_to_ts  # noqa: E402

UNITS_TS = ROOT / "site" / "src" / "data" / "units.ts"
RESOLVER = ROOT / "scripts" / "resolve_pending.py"


def site_units() -> set[str]:
    source = UNITS_TS.read_text()
    block = re.search(r"export const UNITS = \[(.*?)\] as const;", source, re.S)
    assert block, "UNITS literal not found in units.ts"
    code = "\n".join(line.split("//", 1)[0] for line in block.group(1).splitlines())
    units = re.findall(r'"([^"]+)"', code)
    assert len(units) == len(set(units)), "units.ts lists a unit twice"
    return set(units)


def unit_values(value: Any, seen: set[int]) -> Iterator[tuple[str, str]]:
    if id(value) in seen:
        return
    if isinstance(value, dict):
        seen.add(id(value))
        unit = value.get("unit")
        if isinstance(unit, str):
            yield unit, repr(value.get("label", value.get("series_id", "")))
        for child in value.values():
            yield from unit_values(child, seen)
    elif isinstance(value, (list, tuple)):
        seen.add(id(value))
        for child in value:
            yield from unit_values(child, seen)


def test_site_units_parse_includes_the_registered_dod_spelling() -> None:
    units = site_units()
    assert "billions USD" in units
    assert "usd_billions" in units
    assert "index_points" in units


def test_every_unit_literal_in_the_resolver_is_a_site_unit() -> None:
    literals = set(re.findall(r'"unit": "([^"]+)"', RESOLVER.read_text()))
    assert literals, "no unit literals found; the pattern is stale"
    assert literals <= site_units(), sorted(literals - site_units())


def test_every_unit_in_the_resolver_tables_is_a_site_unit() -> None:
    seen: set[int] = set()
    found = [
        (name, unit, where)
        for name, value in vars(resolve_pending).items()
        if name.lstrip("_").isupper()
        for unit, where in unit_values(value, seen)
    ]
    assert any(unit == "billions USD" for _, unit, _ in found)
    missing = [entry for entry in found if entry[1] not in site_units()]
    assert not missing, missing


def test_the_cell_generator_allows_only_site_units() -> None:
    allowed = set(spawned_cells_to_ts.ALLOWED_UNITS)
    assert allowed <= site_units(), sorted(allowed - site_units())
