#!/usr/bin/env python3
"""Stamp docket series with canonical PolicyEngine Ledger catalog references.

Catalog v3 keys identity by (concept, geography, entity), so one concept may
legitimately own several rows (state splits of a national series; entity-
metadata drift between prints). Canonical concept matches take precedence
over aliases; an alias-only docket match must be unique. When a concept
match yields several rows, the docket entry is resolved through a
deterministic pipeline — every filter is a property the containment gate
re-verifies forever after:

1. geography: docket targets are national releases, so only country-level
   rows survive; an entry's ``extras.country`` further requires the matching
   country id (US uses the Census id ``0100000US``).
2. cadence: the row's cadence must equal the docket cadence's ledger period
   type.
3. unit: the row's unit must agree with the docket ``targetUnit`` modulo the
   entry's declared ``valueScale`` transform (see ``units_agree``).
4. source binding: when the entry declares
   ``extras.sourceBinding.sourceSeriesId`` (or ``field``) and exactly one
   candidate row carries that label in ``source_concepts``, that row wins —
   the docket's own feed binding is authoritative about which lineage it
   observes.
5. earliest lineage: if several rows still qualify — the ledger's entity-
   metadata drift produces sibling lineages of one series — the row with the
   strictly earliest ``first_observed_period`` wins. That choice is
   append-invariant (later prints never change it), and it names the lineage
   a future ledger-side curation merge would keep as survivor. A tie is a
   hard error: resolve it by hand in the docket file.

Missing and ambiguous matches are reported together before the docket file
is changed.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DOCKET = ROOT / "scripts" / "docket_series.json"

CADENCE_TO_PERIOD_TYPE = {
    "weekly": "week_ending",
    "monthly": "month",
    "quarterly": "quarter",
    "annual": "year",
    "fiscal_year": "fiscal_year",
}

# Country codes as the docket spells them -> catalog geography ids.
COUNTRY_IDS = {
    "US": "0100000US",
    "CA": "CA",
    "GB": "GB",
    "AU": "AU",
    "JP": "JP",
    "BE": "BE",
}

# Pure magnitude units and their scale relative to one unit. Kept in sync,
# deliberately by duplication, with tests/test_docket_ledger_containment.py:
# the containment gate must not import the tool it audits.
UNIT_SCALE = {"units": 1.0, "thousands": 1e3, "millions": 1e6, "billions": 1e9}


class StampError(ValueError):
    """The docket cannot be mapped uniquely into the ledger catalog."""


def units_agree(
    target_unit: object, catalog_unit: object, value_scale: object
) -> bool:
    """Whether a docket targetUnit is the catalog unit modulo valueScale.

    Identical units always agree (``valueScale`` describes the transform
    from the publisher's raw feed, whose frame varies by entry). Differing
    units agree only when both are pure magnitude units and the declared
    ``valueScale`` converts catalog-unit values into target-unit values:
    value_in_target = value_in_catalog * valueScale, i.e.
    scale(target) == scale(catalog) / valueScale.
    """
    if target_unit is None or catalog_unit is None:
        return True
    if target_unit == catalog_unit:
        return True
    if type(value_scale) not in (int, float) or not value_scale:
        return False
    target_scale = UNIT_SCALE.get(target_unit)
    catalog_scale = UNIT_SCALE.get(catalog_unit)
    if target_scale is None or catalog_scale is None:
        return False
    return abs(target_scale - catalog_scale / value_scale) < 1e-9


def _object(path: pathlib.Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StampError(f"cannot read {label} {path}: {exc}") from exc
    if type(value) is not dict:
        raise StampError(f"{label} must be a JSON object: {path}")
    return value


def _resolve_concept_candidates(
    entry: dict[str, Any], candidates: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a multi-row concept match; (row, note) or (None, problem)."""

    name = entry["series"]

    # A docket-only placeholder is this docket's own seeded row: it has no
    # observations, so the observed-lineage filters (cadence, unit source
    # bindings) cannot apply. Pin it directly after checking the declared
    # country agrees; observed candidates always take the full pipeline.
    observed = [
        row for row in candidates if row.get("status") != "docket-only"
    ]
    if not observed:
        country = (entry.get("extras") or {}).get("country")
        if country is not None and country not in COUNTRY_IDS:
            return None, (
                f"{name}: unmapped docket country {country!r} — extend "
                "COUNTRY_IDS or fix the entry"
            )
        expected_id = COUNTRY_IDS.get(country) if country else None
        compatible = [
            row
            for row in candidates
            if expected_id is None
            or (row.get("geography") or {}).get("id") == expected_id
        ]
        if len(compatible) == 1:
            return compatible[0], None
        return None, (
            f"{name}: {len(compatible)} docket-only placeholders match "
            "after the country check — curate the catalog"
        )
    candidates = observed

    def describe(rows: list[dict[str, Any]]) -> str:
        return ", ".join(
            f"{row['uuid']} ({(row.get('entity') or {}).get('role')}, "
            f"{(row.get('geography') or {}).get('id')}, "
            f"first {row.get('first_observed_period')})"
            for row in rows
        )

    national = [
        row
        for row in candidates
        if (row.get("geography") or {}).get("level") == "country"
    ]
    country = (entry.get("extras") or {}).get("country")
    if country is not None:
        expected_id = COUNTRY_IDS.get(country)
        if expected_id is None:
            return None, f"{name}: unmapped docket country {country!r}"
        national = [
            row
            for row in national
            if (row.get("geography") or {}).get("id") == expected_id
        ]
    expected_cadence = CADENCE_TO_PERIOD_TYPE.get(entry.get("cadence"))
    if expected_cadence is not None:
        national = [
            row for row in national if row.get("cadence") == expected_cadence
        ]
    extras = entry.get("extras") or {}
    national = [
        row
        for row in national
        if units_agree(
            extras.get("targetUnit"), row.get("unit"), extras.get("valueScale")
        )
    ]
    if not national:
        return None, (
            f"{name}: no candidate survives geography/cadence/unit filters "
            f"among {describe(candidates)}"
        )

    binding = extras.get("sourceBinding") or {}
    source_id = binding.get("sourceSeriesId") or binding.get("field")
    if source_id is not None:
        bound = [
            row
            for row in national
            if source_id in (row.get("source_concepts") or [])
        ]
        if len(bound) == 1:
            row = bound[0]
            note = None
            if len(candidates) > 1:
                note = (
                    f"source binding pick: {name} -> {row['uuid']} "
                    f"(source {source_id}, entity "
                    f"{(row.get('entity') or {}).get('role')}; "
                    f"{len(candidates)} rows share this concept)"
                )
            return row, note
        if len(bound) > 1:
            return None, (
                f"{name}: source binding {source_id!r} matches several "
                f"rows: {describe(bound)}"
            )
        if len(national) > 1:
            # The binding was NEEDED to disambiguate siblings and failed:
            # silently falling back to another rule would pin a row the
            # docket's own feed declaration contradicts.
            return None, (
                f"{name}: declared source binding {source_id!r} matches no "
                f"candidate among {describe(national)} — fix the binding "
                "or the catalog before stamping"
            )
        # One candidate passed every filter; the declared feed label has
        # simply not appeared among its observed source labels yet.
        return national[0], (
            f"binding not yet observed: {name} declares {source_id!r}; "
            f"sole candidate {national[0]['uuid']} carries "
            f"{national[0].get('source_concepts')}"
        )

    if len(national) == 1:
        return national[0], None

    firsts = [row.get("first_observed_period") for row in national]
    if any(type(first) is not str for first in firsts):
        return None, (
            f"{name}: cannot rank lineages without first_observed_period "
            f"among {describe(national)}"
        )
    earliest = min(firsts)
    winners = [
        row
        for row in national
        if row["first_observed_period"] == earliest
    ]
    if len(winners) != 1:
        return None, (
            f"{name}: earliest-lineage tie at {earliest} among "
            f"{describe(national)} — pin the ledger uuid by hand"
        )
    row = winners[0]
    note = (
        f"lineage pick: {name} -> {row['uuid']} "
        f"(entity {(row.get('entity') or {}).get('role')}, "
        f"first {row['first_observed_period']}; "
        f"{len(candidates)} rows share this concept)"
    )
    return row, note


def stamp_docket(
    catalog: dict[str, Any], docket: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Return a stamped docket and human-readable match notes."""

    catalog_rows = catalog.get("series")
    docket_rows = docket.get("series")
    if type(catalog_rows) is not list:
        raise StampError("catalog.series must be a list")
    if type(docket_rows) is not list:
        raise StampError("docket.series must be a list")

    concepts: dict[str, list[dict[str, Any]]] = {}
    aliases: dict[str, list[dict[str, Any]]] = {}
    uuids: dict[str, str] = {}
    catalog_errors: list[str] = []
    for index, row in enumerate(catalog_rows):
        if type(row) is not dict:
            catalog_errors.append(f"catalog series[{index}] is not an object")
            continue
        concept = row.get("concept")
        uuid = row.get("uuid")
        row_aliases = row.get("aliases")
        if type(concept) is not str or not concept:
            catalog_errors.append(f"catalog series[{index}] has no concept")
            continue
        if type(uuid) is not str or not uuid:
            catalog_errors.append(f"catalog concept {concept!r} has no uuid")
            continue
        if uuid in uuids:
            catalog_errors.append(
                f"duplicate catalog uuid {uuid} ({uuids[uuid]!r}, {concept!r})"
            )
            continue
        if type(row_aliases) is not list or any(
            type(alias) is not str for alias in row_aliases
        ):
            catalog_errors.append(
                f"catalog concept {concept!r} aliases must be a string list"
            )
            continue
        uuids[uuid] = concept
        concepts.setdefault(concept, []).append(row)
        for alias in row_aliases:
            aliases.setdefault(alias, []).append(row)
    if catalog_errors:
        raise StampError("invalid catalog:\n- " + "\n- ".join(catalog_errors))

    missing: list[str] = []
    ambiguous: list[str] = []
    notes: list[str] = []
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for index, entry in enumerate(docket_rows):
        if type(entry) is not dict or type(entry.get("series")) is not str:
            missing.append(f"series[{index}] has no string series identifier")
            continue
        name = entry["series"]
        concept_rows = concepts.get(name)
        if concept_rows:
            row, note = _resolve_concept_candidates(entry, concept_rows)
            if row is None:
                ambiguous.append(note)
                continue
            if note:
                notes.append(note)
        else:
            candidates = aliases.get(name, [])
            if not candidates:
                missing.append(name)
                continue
            if len(candidates) != 1:
                candidate_names = sorted(
                    str(item["concept"]) for item in candidates
                )
                ambiguous.append(f"{name}: {', '.join(candidate_names)}")
                continue
            row, note = _resolve_concept_candidates(entry, candidates)
            if row is None:
                ambiguous.append(note)
                continue
            notes.append(f"alias match: {name} -> {row['concept']}")
            if note:
                notes.append(note)
        matches.append((entry, row))

    problems: list[str] = []
    if missing:
        problems.append("no catalog row:\n- " + "\n- ".join(sorted(missing)))
    if ambiguous:
        problems.append(
            "ambiguous catalog match:\n- " + "\n- ".join(sorted(ambiguous))
        )
    if problems:
        raise StampError("cannot stamp docket:\n" + "\n".join(problems))

    for entry, row in matches:
        entry["ledger"] = {"uuid": row["uuid"], "concept": row["concept"]}
    return docket, notes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True, type=pathlib.Path)
    parser.add_argument("--docket", type=pathlib.Path, default=DEFAULT_DOCKET)
    args = parser.parse_args()

    try:
        catalog = _object(args.catalog, "catalog")
        docket = _object(args.docket, "docket")
        stamped, notes = stamp_docket(catalog, docket)
        output = json.dumps(stamped, indent=2) + "\n"
        previous = args.docket.read_text()
        if output != previous:
            args.docket.write_text(output)
            disposition = "updated"
        else:
            disposition = "unchanged"
    except StampError as exc:
        print(f"docket ledger stamping failed: {exc}", file=sys.stderr)
        return 1

    print(f"{disposition} {args.docket}: {len(stamped['series'])} ledger references")
    for note in notes:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
