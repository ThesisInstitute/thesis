#!/usr/bin/env python3
"""Write the fixture that checks the site's port of receipt's current view.

The site grades forecasts on the supersede-aware current view of the Chronicle
ledger (site/src/data/ledger-current-view.ts), a TypeScript port of receipt
0.6.2's ``expected_assertion_version_id``, ``_effective_assertion_id`` and
``effective_current_rows``, plus the assertion-version part of ``check_rows``.
This script runs receipt itself over seeded ledgers and records what it
returned, so a Vitest can hold the port to it:

* every row's effective assertion id (or that receipt raised),
* every ledger's ``effective_current_rows`` (or that it raised), and
* whether ``check_rows`` accepts each ledger whose rows pass its
  non-assertion checks.

The rows come from three places: real rows from the pinned Chronicle ledger
(tests/fixtures/chronicle_rows_598f394d.json), gated ledgers built as valid
append sequences with corrections (each one accepted by ``check_rows``), and
arbitrary ledgers composed from shape variants receipt must also handle:
missing, null, empty, non-object and non-string ``assertionVersion`` parts,
dangling and self supersedes, duplicated rows, and non-object ``measure``,
``source`` and ``responseArchive``. Values and text cover the canonical-JSON
edge cases: negative zero, both float-format thresholds, integers above 2**53,
astral and lone-surrogate text, control characters and UTF-16 key order.

The output is deterministic. ``--check`` regenerates it in memory and exits 1
if the committed fixture differs, which tests/test_receipt_current_view_fixture.py
runs in CI.

    uv run --extra custody python \
        scripts/generate_receipt_current_view_fixture.py [--check]
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import random
import re
import sys
from dataclasses import dataclass
from importlib.metadata import version as package_version
from typing import Any

from receipt.append_gate import (
    _effective_assertion_id,
    check_rows,
    effective_current_rows,
    expected_assertion_version_id,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "site" / "src" / "__tests__" / "fixtures" / "receipt-current-view.json"
CHRONICLE_ROWS = ROOT / "tests" / "fixtures" / "chronicle_rows_598f394d.json"
SEED = 20260929
SCHEMA_VERSION = "thesis_receipt_current_view_fixture_v1"
RECEIPT_VERSION = "0.6.2"

# PolicyEngine/chronicle scripts/receipt_pins.py APPEND_GATE_SPEC
# .assertion_content_keys at 598f394d. The resolver's writer
# (resolve_pending.ASSERTION_CONTENT_KEYS) must agree; the pytest checks it.
CHRONICLE_ASSERTION_CONTENT_KEYS = (
    "source_record_id",
    "value",
    "observed_at",
    "period",
    "geography",
    "entity",
    "aggregation",
    "filters",
    "domain",
)

# The units the site's ledger parser admits (thesis-log.ts isUnit).
SITE_UNITS = (
    "percent",
    "count",
    "gbp_billions",
    "usd",
    "usd_millions",
    "usd_billions",
    "usd_monthly",
    "thousands",
    "millions",
    "million_cubic_feet",
    "per_1000_live_births",
    "ratio",
    "percent_growth",
)

VALUES = (
    0,
    -0.0,
    1,
    1.0,
    3.0,
    2.5,
    -3.75,
    0.1,
    4.2,
    226,
    1.814,
    1e-6,
    1e-7,
    123456.789,
    1e20,
    1e21,
    1.5e300,
    9007199254740991,
    9007199254740993,
    12345678901234567890,
)

TEXT = (
    "",
    "plain",
    "Ünïcødé",
    "astral 😀",
    "\ue000 private use",
    "line\u2028separator",
    "tab\there",
    'quote"back\\slash',
    "\u0001control\u001f",
    "lone \ud800 surrogate",
    "0",
)

PERIODS = (
    {"type": "month", "value": "2026-06"},
    {"type": "month", "value": "2026-07"},
    {"type": "year", "value": 2026},
    {"type": "quarter", "value": "2026-Q2"},
    {"type": "week", "value": "2026-06-13"},
    {"type": "month", "value": "2026-06", "😀": 1, "\ue000": 2, "a": 3},
)

DATES = ("2026-06-18", "2026-07-09", "2026-09-01")

# Non-object shapes for measure/source/responseArchive. Falsy ones read as an
# empty mapping; the truthy ones make receipt raise AttributeError.
FALSY_SHAPES = (None, {}, [], 0, "", False)
TRUTHY_NON_OBJECTS = ("str", [1], 5)


@dataclass(frozen=True)
class _ContentKeys:
    """The one AppendGateSpec field the three receipt functions read."""

    assertion_content_keys: tuple[str, ...]


SPEC = _ContentKeys(CHRONICLE_ASSERTION_CONTENT_KEYS)


def _dumps(row: Any) -> str:
    # Chronicle writes rows with json.dumps defaults; lone surrogates only
    # survive the ASCII escape form.
    return json.dumps(row, ensure_ascii=True)


def _content_address(row: Any) -> str | None:
    try:
        return expected_assertion_version_id(row, SPEC)
    except Exception:
        return None


def _effective_id(row: Any) -> str | None:
    try:
        return _effective_assertion_id(row, SPEC)
    except Exception:
        return None


def _supersedes(row: Any) -> str | None:
    version = row.get("assertionVersion") if isinstance(row, dict) else None
    if isinstance(version, dict) and version.get("supersedes"):
        return str(version["supersedes"])
    return None


def _port_refuses(row: Any) -> bool:
    """receipt would str()-coerce a truthy non-string id or supersedes."""

    version = row.get("assertionVersion") if isinstance(row, dict) else None
    if not isinstance(version, dict):
        return False
    return any(
        version.get(field) and not isinstance(version[field], str)
        for field in ("id", "supersedes")
    )


def _base_valid(row: Any) -> bool:
    """Whether check_rows's non-assertion checks pass for this row.

    Mirrors check_rows's row validation, except that the record id must be a
    string: the site keys records by string and refuses any other type.
    """

    if not isinstance(row, dict):
        return False
    record_id = row.get("source_record_id")
    if not isinstance(record_id, str) or not record_id:
        return False
    if not isinstance(row.get("value"), (int, float)):
        return False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("observed_at", ""))):
        return False
    measure = row.get("measure")
    return isinstance(measure, dict) and bool(measure.get("unit"))


def _site_parseable(row: Any) -> bool:
    """Whether thesis-log.ts's ledger parser maps this row."""

    return (
        _base_valid(row)
        and not isinstance(row["value"], bool)
        and row["measure"]["unit"] in SITE_UNITS
        and isinstance(row.get("source"), dict)
        and isinstance(row.get("period"), dict)
    )


class Pool:
    """Distinct JSONL lines with receipt's per-row answers."""

    def __init__(self) -> None:
        self.lines: list[dict[str, Any]] = []
        self._index: dict[str, int] = {}

    def add(self, line: str, origin: str) -> int:
        if line in self._index:
            return self._index[line]
        row = json.loads(line)
        self._index[line] = len(self.lines)
        self.lines.append(
            {
                "line": line,
                "origin": origin,
                "isObject": isinstance(row, dict),
                "contentAddress": _content_address(row),
                "effectiveId": _effective_id(row),
                "supersedes": _supersedes(row),
                "portRefuses": _port_refuses(row),
                "baseValid": _base_valid(row),
                "siteParseable": _site_parseable(row),
            }
        )
        return self._index[line]

    def row(self, index: int) -> Any:
        return json.loads(self.lines[index]["line"])


def _base_row(rng: random.Random, record_id: str) -> dict[str, Any]:
    measure: dict[str, Any] = {"unit": rng.choice(SITE_UNITS)}
    for key in (
        "concept",
        "source_concept",
        "concept_relation",
        "concept_authority",
        "legal_vintage",
        "concept_evidence_notes",
    ):
        if rng.random() < 0.3:
            measure[key] = rng.choice(TEXT + (None,))
    source: dict[str, Any] = {
        "source_name": rng.choice(("bls", "statcan", "ons", None)),
        "source_table": rng.choice(TEXT),
        "url": rng.choice(("https://www.bls.gov/x", "https://example.gov/😀")),
    }
    for key in ("source_file", "vintage", "source_sha256", "extracted_at"):
        if rng.random() < 0.3:
            source[key] = rng.choice(TEXT + (None,))
    row: dict[str, Any] = {
        "source_record_id": record_id,
        "value": rng.choice(VALUES),
        "observed_at": rng.choice(DATES),
        "period": copy.deepcopy(rng.choice(PERIODS)),
        "measure": measure,
        "source": source,
    }
    for key in ("geography", "entity", "aggregation", "domain", "label"):
        if rng.random() < 0.3:
            row[key] = rng.choice(TEXT + (None,))
    if rng.random() < 0.5:
        row["filters"] = rng.choice(
            (None, [], {}, {"b": 1, "a": [1.0, "x"]}, [{"😀": -0.0}])
        )
    for key in ("source_row_keys", "source_cell_keys"):
        if rng.random() < 0.4:
            row[key] = rng.choice(([], ["r1", "r2"], [["a", 1]], None))
    if rng.random() < 0.5:
        row["responseArchive"] = {
            "path": "archive/x.gz",
            "sha256": rng.choice(("a" * 64, "b" * 64, None, "")),
        }
    return row


def _versioned(row: dict[str, Any], supersedes: str | None) -> dict[str, Any]:
    row = dict(row)
    row.pop("assertionVersion", None)
    row["assertionVersion"] = {
        "id": expected_assertion_version_id(row, SPEC),
        "supersedes": supersedes,
    }
    return row


def _correction_of(rng: random.Random, row: dict[str, Any]) -> dict[str, Any]:
    """A new assertion for the same record: new value, unit or source."""

    fixed = copy.deepcopy(row)
    fixed.pop("assertionVersion", None)
    choice = rng.randrange(3)
    if choice == 0:
        fixed["value"] = rng.choice([v for v in VALUES if v != row.get("value")])
    elif choice == 1:
        fixed["measure"] = dict(fixed.get("measure") or {})
        fixed["measure"]["unit"] = rng.choice(
            [u for u in SITE_UNITS if u != fixed["measure"].get("unit")]
        )
    else:
        fixed["source"] = dict(fixed.get("source") or {})
        fixed["source"]["url"] = f"https://example.gov/corrected/{rng.randrange(10**6)}"
    return fixed


def _gated_ledger(
    rng: random.Random, seeds: list[dict[str, Any]], size: int
) -> list[dict[str, Any]]:
    """A valid append sequence: new records, pre-versioning rows, corrections."""

    rows: list[dict[str, Any]] = []
    active: dict[str, str] = {}
    latest: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    names = iter(f"rid.{rng.randrange(10**9):09d}.{n}" for n in range(10**6))
    while len(rows) < size:
        if active and rng.random() < 0.45:
            record_id = rng.choice(sorted(active))
            for _ in range(20):
                candidate = _versioned(
                    _correction_of(rng, latest[record_id]), active[record_id]
                )
                if candidate["assertionVersion"]["id"] not in seen:
                    break
            else:
                continue
        else:
            if seeds:
                candidate = copy.deepcopy(seeds.pop(rng.randrange(len(seeds))))
                if candidate["source_record_id"] in active:
                    continue
            else:
                candidate = _base_row(rng, next(names))
            if rng.random() < 0.5:
                candidate.pop("assertionVersion", None)
                if rng.random() < 0.3:
                    candidate["assertionVersion"] = None
            else:
                candidate = _versioned(candidate, None)
        effective = _effective_assertion_id(candidate, SPEC)
        if effective in seen:
            continue
        seen.add(effective)
        record_id = candidate["source_record_id"]
        active[record_id] = effective
        latest[record_id] = candidate
        rows.append(candidate)
    lines = [_dumps(row) for row in rows]
    check_rows(lines, len(lines), SPEC)  # every gated ledger must pass the gate
    return rows


def _variants(rng: random.Random, row: dict[str, Any], ids: list[str]) -> list[Any]:
    """Shape variants of one row that receipt must also read."""

    out: list[Any] = []
    for version in (
        [],
        "av2:not-an-object",
        5,
        {},
        {"id": ""},
        {"id": None},
        {"id": 0},
        {"id": []},
        {"id": {}},
        {"id": "custom-id"},
        {"id": rng.choice(ids)},
        {"supersedes": rng.choice(ids)},
        {"id": "custom-id", "supersedes": ""},
        {"id": "custom-id", "supersedes": 0},
        {"supersedes": []},
        {"id": 7},
        {"id": True},
        {"supersedes": 7},
        {"id": "self-named", "supersedes": "self-named"},
    ):
        variant = copy.deepcopy(row)
        variant["assertionVersion"] = version
        out.append(variant)
    # Shape variants are pre-versioning, so their effective id is the
    # recomputed content address and a non-object shape makes receipt raise.
    unversioned = copy.deepcopy(row)
    unversioned.pop("assertionVersion", None)
    for field in ("measure", "source", "responseArchive"):
        for shape in FALSY_SHAPES + TRUTHY_NON_OBJECTS:
            variant = copy.deepcopy(unversioned)
            variant[field] = shape
            out.append(variant)
        variant = copy.deepcopy(unversioned)
        variant.pop(field, None)
        out.append(variant)
    for key in CHRONICLE_ASSERTION_CONTENT_KEYS:
        variant = copy.deepcopy(unversioned)
        variant.pop(key, None)
        out.append(variant)
    out.append(["a", "row", "that", "is", "not", "an", "object"])
    return out


def _receipt_current(rows: list[Any]) -> list[int] | None:
    try:
        current = effective_current_rows(rows, SPEC)
    except Exception:
        return None
    positions = {id(row): position for position, row in enumerate(rows)}
    return [positions[id(row)] for row in current]


def _receipt_check_rows(lines: list[str]) -> str:
    try:
        check_rows(lines, len(lines), SPEC)
    except Exception:
        return "refuse"
    return "accept"


def _ledger_entry(pool: Pool, kind: str, indices: list[int]) -> dict[str, Any]:
    lines = [pool.lines[index]["line"] for index in indices]
    rows = [json.loads(line) for line in lines]  # one distinct object per position
    base_valid = all(pool.lines[index]["baseValid"] for index in indices)
    return {
        "kind": kind,
        "lines": indices,
        "current": _receipt_current(rows),
        "checkRows": _receipt_check_rows(lines) if base_valid else None,
        "siteParseable": all(pool.lines[index]["siteParseable"] for index in indices),
    }


def build_fixture() -> dict[str, Any]:
    installed = package_version("receipt")
    if installed != RECEIPT_VERSION:
        raise SystemExit(
            f"receipt {installed} is installed but the fixture records "
            f"{RECEIPT_VERSION}; the site port targets that version"
        )
    rng = random.Random(SEED)
    pool = Pool()
    chronicle = json.loads(CHRONICLE_ROWS.read_text())
    seeds: list[dict[str, Any]] = []
    for number, line in sorted(chronicle["lines"].items(), key=lambda kv: int(kv[0])):
        pool.add(line, f"chronicle@{chronicle['sha'][:8]}:L{number}")
        seeds.append(json.loads(line))

    ledgers: list[dict[str, Any]] = []
    # One ledger of the real rows as they sit in Chronicle.
    real = [index for index, line in enumerate(pool.lines)]
    ledgers.append(_ledger_entry(pool, "chronicle", real))

    # The first ledgers correct real rows, pre-versioning ones included (the
    # case the site's recomputed content address exists for); the rest use
    # generated rows, which are smaller.
    for number in range(60):
        real_seeds = [seeds[number]] if number < len(seeds) else []
        rows = _gated_ledger(rng, real_seeds, rng.randrange(1, 7))
        indices = [pool.add(_dumps(row), "gated") for row in rows]
        ledgers.append(_ledger_entry(pool, "gated", indices))

    ids = sorted({line["effectiveId"] for line in pool.lines if line["effectiveId"]})
    # Variants build on generated rows; the real ones are ~2 KB each.
    bases = [
        pool.row(index)
        for index, line in enumerate(pool.lines)
        if line["origin"] == "gated" and len(line["line"]) < 700
    ]
    for base in rng.sample(bases, 4):
        for variant in _variants(rng, base, ids):
            pool.add(_dumps(variant), "variant")

    # A hand-written number lexeme the Python writer never emits.
    lexeme = _dumps(seeds[0]).replace(
        f'"value": {json.dumps(seeds[0]["value"])}', '"value": 1.72E2', 1
    )
    pool.add(lexeme, "lexeme")

    by_effective: dict[str, list[int]] = {}
    for index, line in enumerate(pool.lines):
        if line["effectiveId"]:
            by_effective.setdefault(line["effectiveId"], []).append(index)
    naming: dict[str, list[int]] = {}
    for index, line in enumerate(pool.lines):
        if line["supersedes"]:
            naming.setdefault(line["supersedes"], []).append(index)

    for _ in range(160):
        indices = [rng.randrange(len(pool.lines)) for _ in range(rng.randrange(0, 7))]
        # Pull in rows that supersede (or are superseded by) what was drawn, so
        # most ledgers exercise the drop, in either order.
        for index in list(indices):
            line = pool.lines[index]
            if line["effectiveId"] in naming and rng.random() < 0.7:
                indices.append(rng.choice(naming[line["effectiveId"]]))
            if line["supersedes"] in by_effective and rng.random() < 0.7:
                indices.append(rng.choice(by_effective[line["supersedes"]]))
        rng.shuffle(indices)
        ledgers.append(_ledger_entry(pool, "arbitrary", indices))

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generator": "scripts/generate_receipt_current_view_fixture.py",
        "receiptVersion": RECEIPT_VERSION,
        "seed": SEED,
        "chronicle": {
            key: chronicle[key] for key in ("repo", "sha", "path", "jsonlSha256")
        },
        "assertionContentKeys": list(CHRONICLE_ASSERTION_CONTENT_KEYS),
        "lines": pool.lines,
        "ledgers": ledgers,
    }


def render(fixture: dict[str, Any]) -> str:
    """One pool line or ledger per text line, so a regeneration diffs by row."""

    def dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))

    parts = []
    for key, value in fixture.items():
        if key in ("lines", "ledgers"):
            items = ",\n".join(f"  {dump(item)}" for item in value)
            parts.append(f"{dump(key)}:[\n{items}\n]")
        else:
            parts.append(f"{dump(key)}:{dump(value)}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the committed fixture differs from a fresh build",
    )
    args = parser.parse_args(argv)
    text = render(build_fixture())
    if args.check:
        if not FIXTURE.exists() or FIXTURE.read_text() != text:
            print(
                f"{FIXTURE.relative_to(ROOT)} is stale; regenerate it with "
                "scripts/generate_receipt_current_view_fixture.py",
                file=sys.stderr,
            )
            return 1
        return 0
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(text)
    print(f"wrote {FIXTURE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
