#!/usr/bin/env python3
"""Write the fixture that holds the site's restatement reader to the writer.

``scripts/resolve_pending.py --restate-base-units`` appends one row for each
current Chronicle row in a scaled unit, and the site reads those rows with
site/src/data/ledger-restatements.ts. Before it proposes them, the resolver
runs ``check_restatements``, its port of the site's checks. This script runs
the resolver's own writer over real Chronicle rows and records:

* ``lines``: every line a case uses. The first are the sample, exact lines of
  the ledger at the pin (tests/fixtures/chronicle_rows_fd83eec2.json): every
  shape a current scaled row takes there, the two rows that two of them
  correct, and an unscaled row.
* ``writer``: the lines ``restatement_rows`` writes for the sample, in the
  order a restatement run appends them.
* ``cases``: ledgers built from the sample, the writer's lines and copies of
  them with one or two things changed. A copy with two defects holds the
  site and the port to the same first refusal. In one row the defects pin
  the order of a restatement's own checks. Across two rows they pin each
  step of the site's order: every row's relation, and the supersedes of a
  row that restates nothing; then every recorded pair; then the fold, which
  checks each restatement's supersedes and content. Each case records what
  the port returned, the id
  each restatement it accepted supersedes or its refusal, and whether
  Chronicle's append gate (receipt 0.6.2 ``check_rows`` and
  ``check_binding_shapes``) accepts the ledger.

site/src/__tests__/ledger-restatement-fixture.test.ts replays every case
through the site's reader, which must refuse exactly the cases the port
refuses. ``--check`` rebuilds the fixture in memory and exits 1 if the
committed one differs; tests/test_restate_base_units.py runs it.

    uv run python scripts/generate_ledger_restatement_fixture.py [--check]
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import sys
from collections.abc import Callable
from typing import Any

import ledger_units
import resolve_pending
from generate_receipt_current_view_fixture import SPEC
from receipt.append_gate import check_binding_shapes, check_rows

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "site" / "src" / "__tests__" / "fixtures" / "ledger-restatements.json"
CHRONICLE_ROWS = ROOT / "tests" / "fixtures" / "chronicle_rows_fd83eec2.json"
SCHEMA_VERSION = "thesis_ledger_restatement_fixture_v1"
RETRIEVED_AT = "2026-11-04T00:00:00Z"

# Sample rows the changed copies start from, by ledger line: a versioned row
# with a source-binding projection and a value that keeps cents (usd_millions),
# and a row written before assertion versioning whose method notes name its
# scale (millions).
PROJECTED_LINE = 246
UNVERSIONED_LINE = 30
# A claims row a correction already superseded, a versioned row with a
# projection that a correction can follow, a row written before versioning
# whose base form stays a scaled row's source, and an unscaled row.
SUPERSEDED_LINE = 233
CORRECTED_LINE = 144
BASE_ROW_LINE = 109
UNSCALED_LINE = 2


class Lines:
    """Each distinct line once, so cases refer to lines by index."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._index: dict[str, int] = {}

    def refs(self, lines: list[str]) -> list[int]:
        for line in lines:
            if line not in self._index:
                self._index[line] = len(self.lines)
                self.lines.append(line)
        return [self._index[line] for line in lines]


def _reversioned(row: dict[str, Any]) -> dict[str, Any]:
    """The row's id recomputed from its content, as the writer sets it.

    A changed copy keeps a valid id, so the site's assertion-version checks
    pass and the restatement checks decide the case.
    """

    version = row.get("assertionVersion") or {}
    row["assertionVersion"] = {
        **version,
        "id": resolve_pending.assertion_version(row)["id"],
    }
    return row


def _port(lines: list[str]) -> dict[str, Any]:
    try:
        restatements = resolve_pending.check_restatements(lines)
    except ValueError as exc:
        return {"refuses": str(exc)}
    return {"restates": [row["assertionVersion"]["supersedes"] for row in restatements]}


def _gate(lines: list[str], prefix: int) -> str:
    try:
        check_rows(lines, prefix, SPEC)
        check_binding_shapes(lines, prefix)
    except Exception:  # receipt raises several types; any one refuses
        return "refuse"
    return "accept"


def _restatement_of(prior: dict[str, Any], prior_line: str) -> dict[str, Any]:
    """A restatement of any row, scaled or not, built as the writer builds one.

    ``restatement_row`` refuses a row that holds no scale, so the cases that
    restate one build it here.
    """

    unit = (prior.get("measure") or {}).get("unit")
    base = ledger_units.base_unit(unit) or unit
    run_dir = resolve_pending.resolution_run_dir(RETRIEVED_AT)
    vintage = str(prior.get("sourceVintage") or prior["observed_at"])
    archive, _ = resolve_pending.response_archive_reference(
        run_dir,
        series_id=str(prior["source_record_id"]),
        vintage=vintage,
        raw=prior_line.encode("utf-8"),
        extension="json",
    )
    row = copy.deepcopy(prior)
    row["measure"]["unit"] = base
    row.setdefault("source", {}).update(
        {"recorded_value": prior["value"], "recorded_unit": unit}
    )
    row["ledgerRepoSha"] = "0" * 40
    row["sourceVintage"] = vintage
    row["retrievedAt"] = RETRIEVED_AT
    row["responseArchive"] = archive
    row["assertionVersion"] = {
        "id": None,
        "supersedes": resolve_pending.effective_assertion_id(prior),
        "relation": resolve_pending.UNIT_RESTATEMENT,
    }
    return _reversioned(row)


def _base_row(prior: dict[str, Any], record_id: str) -> dict[str, Any]:
    """A new print in base units, as the resolver writes one once migrated."""

    row = copy.deepcopy(prior)
    row["source_record_id"] = record_id
    row.pop("assertionVersion", None)
    row = resolve_pending.base_unit_row(row)
    row["ledgerRepoSha"] = "0" * 40
    row["sourceVintage"] = str(row["observed_at"])
    row["retrievedAt"] = RETRIEVED_AT
    archive, _ = resolve_pending.response_archive_reference(
        resolve_pending.resolution_run_dir(RETRIEVED_AT),
        series_id=record_id,
        vintage=row["sourceVintage"],
        raw=f"{record_id}\n".encode(),
    )
    row["responseArchive"] = archive
    if "sourceBindingProjection" in row:
        row["sourceBindingProjection"] = {
            **row["sourceBindingProjection"],
            "unit": row["measure"]["unit"],
            "responseSha256": archive["sha256"],
        }
    row["assertionVersion"] = resolve_pending.assertion_version(row)
    return row


def build_fixture() -> dict[str, Any]:
    source = json.loads(CHRONICLE_ROWS.read_text())
    numbers = sorted(source["lines"], key=int)
    sample = [source["lines"][number] for number in numbers]
    line_of = {int(number): line for number, line in source["lines"].items()}
    row_of = {number: json.loads(line) for number, line in line_of.items()}
    built = resolve_pending.restatement_rows(
        sample, retrieved_at=RETRIEVED_AT, ledger_repo_sha=source["sha"]
    )
    writer = [resolve_pending.ledger_line(row) for row, _ in built]
    restated = {
        row["assertionVersion"]["supersedes"]: index
        for index, (row, _) in enumerate(built)
    }

    def writer_row(line_number: int) -> tuple[int, dict[str, Any]]:
        index = restated[resolve_pending.effective_assertion_id(row_of[line_number])]
        return index, json.loads(writer[index])

    table = Lines()
    sample_refs = table.refs(sample)
    writer_refs = table.refs(writer)
    cases: list[dict[str, Any]] = []

    def case(name: str, lines: list[str], *, prefix: int | None = None) -> None:
        cases.append(
            {
                "name": name,
                "lines": table.refs(lines),
                "port": _port(lines),
                "gate": _gate(lines, len(sample) if prefix is None else prefix),
            }
        )

    def changed(
        name: str,
        line_number: int,
        change: Callable[[dict[str, Any]], None],
        *,
        reversion: bool = True,
    ) -> None:
        index, row = writer_row(line_number)
        change(row)
        if reversion:
            _reversioned(row)
        lines = list(writer)
        lines[index] = resolve_pending.ledger_line(row)
        case(name, sample + lines)

    case("sample", sample)
    case("writer", sample + writer)

    projected = row_of[PROJECTED_LINE]

    def set_value(value: Any) -> Callable[[dict[str, Any]], None]:
        return lambda row: row.__setitem__("value", value)

    def set_in(key: str, field: str, value: Any) -> Callable[[dict[str, Any]], None]:
        return lambda row: row[key].__setitem__(field, value)

    def drop_in(key: str, *fields: str) -> Callable[[dict[str, Any]], None]:
        def change(row: dict[str, Any]) -> None:
            for field in fields:
                row[key].pop(field, None)

        return change

    base_value = ledger_units.to_base(projected["value"], projected["measure"]["unit"])
    changed("value off by one", PROJECTED_LINE, set_value(base_value + 1))
    changed(
        "value left in the old scale", PROJECTED_LINE, set_value(projected["value"])
    )
    changed(
        "unit keeps its scale",
        PROJECTED_LINE,
        set_in("measure", "unit", projected["measure"]["unit"]),
    )
    changed(
        "unit is another base unit", PROJECTED_LINE, set_in("measure", "unit", "count")
    )
    changed(
        "recorded value off",
        PROJECTED_LINE,
        set_in("source", "recorded_value", projected["value"] + 1),
    )
    changed(
        "recorded value is text",
        PROJECTED_LINE,
        set_in("source", "recorded_value", str(projected["value"])),
    )
    changed(
        "recorded unit is another scale",
        PROJECTED_LINE,
        set_in("source", "recorded_unit", "usd_billions"),
    )
    changed(
        "recorded pair missing",
        PROJECTED_LINE,
        drop_in("source", "recorded_value", "recorded_unit"),
    )
    changed(
        "archive holds the row serialized again",
        PROJECTED_LINE,
        set_in(
            "responseArchive",
            "sha256",
            hashlib.sha256(json.dumps(projected).encode()).hexdigest(),
        ),
    )
    changed(
        "archive holds another row",
        PROJECTED_LINE,
        set_in(
            "responseArchive",
            "sha256",
            hashlib.sha256(line_of[UNSCALED_LINE].encode()).hexdigest(),
        ),
    )
    changed(
        "observed_at moves",
        PROJECTED_LINE,
        lambda row: row.__setitem__("observed_at", "2026-10-31"),
    )
    changed(
        "concept moves", PROJECTED_LINE, set_in("measure", "concept", "another.concept")
    )
    changed(
        "source url moves",
        PROJECTED_LINE,
        set_in("source", "url", "https://example.org/other"),
    )
    changed(
        "projection field moves",
        PROJECTED_LINE,
        set_in("sourceBindingProjection", "field", "another_field"),
    )
    changed(
        "projection dropped",
        PROJECTED_LINE,
        lambda row: row.pop("sourceBindingProjection"),
    )
    changed(
        "a field added", PROJECTED_LINE, lambda row: row.__setitem__("note", "added")
    )
    changed(
        "relation is another relation",
        PROJECTED_LINE,
        set_in("assertionVersion", "relation", "correction"),
    )
    changed(
        "relation is null",
        PROJECTED_LINE,
        set_in("assertionVersion", "relation", None),
    )
    changed(
        "supersedes names no row",
        PROJECTED_LINE,
        set_in("assertionVersion", "supersedes", "av2:" + "0" * 64),
    )
    changed(
        "supersedes is not text",
        PROJECTED_LINE,
        set_in("assertionVersion", "supersedes", 7),
    )
    changed(
        "method notes rewritten",
        PROJECTED_LINE,
        set_in("source", "method_notes", "Rewritten notes."),
    )
    changed(
        "provenance moves",
        PROJECTED_LINE,
        lambda row: row.update(
            {
                "retrievedAt": "2026-11-05T01:02:03Z",
                "ledgerRepoSha": "1" * 40,
                "sourceVintage": "2026-11-05",
            }
        ),
    )
    changed(
        "archive path moves",
        PROJECTED_LINE,
        set_in(
            "responseArchive",
            "path",
            "records/resolutions/elsewhere/responses/x.json.gz",
        ),
    )
    changed(
        "projection keeps the scaled unit",
        PROJECTED_LINE,
        set_in("sourceBindingProjection", "unit", projected["measure"]["unit"]),
    )
    changed(
        "relation removed",
        PROJECTED_LINE,
        drop_in("assertionVersion", "relation"),
    )
    changed(
        "unversioned row: observed_at moves",
        UNVERSIONED_LINE,
        lambda row: row.__setitem__("observed_at", "2026-10-31"),
    )
    changed(
        "unversioned row: method notes rewritten",
        UNVERSIONED_LINE,
        set_in("source", "method_notes", "Rewritten notes."),
    )

    # Falsy supersedes values: neither reader may coerce one into a row id.
    for name, value in (("empty", ""), ("zero", 0), ("false", False)):
        changed(
            f"supersedes is {name}",
            PROJECTED_LINE,
            set_in("assertionVersion", "supersedes", value),
        )

    # Two defects in one row: both readers must name the same one.
    def both(
        *changes: Callable[[dict[str, Any]], None],
    ) -> Callable[[dict[str, Any]], None]:
        def change(row: dict[str, Any]) -> None:
            for one in changes:
                one(row)

        return change

    unit_kept = set_in("measure", "unit", projected["measure"]["unit"])
    pair_off = set_in("source", "recorded_value", projected["value"] + 1)
    value_off = set_value(base_value + 1)
    archive_other = set_in(
        "responseArchive",
        "sha256",
        hashlib.sha256(line_of[UNSCALED_LINE].encode()).hexdigest(),
    )
    content_moved = lambda row: row.__setitem__(  # noqa: E731
        "observed_at", "2026-10-31"
    )
    for name, first, second in (
        ("unit and pair", unit_kept, pair_off),
        ("pair and value", pair_off, value_off),
        ("value and archive", value_off, archive_other),
        ("archive and content", archive_other, content_moved),
    ):
        changed(f"two defects: {name}", PROJECTED_LINE, both(first, second))

    # Where a restatement sits and what it names.
    index, row = writer_row(PROJECTED_LINE)
    rest = writer[:index] + writer[index + 1 :]
    case(
        "restatement before its row",
        [writer[index], *sample, *rest],
        prefix=0,
    )
    unscaled = _restatement_of(row_of[UNSCALED_LINE], line_of[UNSCALED_LINE])
    case(
        "restates an unscaled row",
        sample + writer + [resolve_pending.ledger_line(unscaled)],
    )
    twice = _restatement_of(row, writer[index])
    case(
        "restates a restatement",
        sample + writer + [resolve_pending.ledger_line(twice)],
    )
    superseded, _ = resolve_pending.restatement_row(
        row_of[SUPERSEDED_LINE],
        line_of[SUPERSEDED_LINE],
        run_dir=resolve_pending.resolution_run_dir(RETRIEVED_AT),
        retrieved_at=RETRIEVED_AT,
        ledger_repo_sha=source["sha"],
    )
    case(
        "restates a row a correction superseded",
        sample + writer + [resolve_pending.ledger_line(superseded)],
    )

    # Rows the resolver writes in base units once the ledger holds no scale.
    base = _base_row(
        row_of[BASE_ROW_LINE], "bls.jolts.job_openings_total.june_2026.first_print"
    )
    case("base row", sample + writer + [resolve_pending.ledger_line(base)])
    for name, change in (
        ("base row stores a value its pair does not", set_value(base["value"] + 1)),
        (
            "base row records an unscaled unit",
            set_in("source", "recorded_unit", "percent"),
        ),
        (
            "base row stores the scaled unit",
            set_in("measure", "unit", base["source"]["recorded_unit"]),
        ),
    ):
        other = copy.deepcopy(base)
        change(other)
        _reversioned(other)
        case(name, sample + writer + [resolve_pending.ledger_line(other)])

    # Defects in two rows: the site reads every row's relation and pair
    # before it folds restatements, so both readers must name the row the
    # site reaches first, not the earlier line.
    index, value_off = writer_row(PROJECTED_LINE)
    value_off["value"] = base_value + 1
    _reversioned(value_off)
    off_writer = list(writer)
    off_writer[index] = resolve_pending.ledger_line(value_off)
    for name, change in (
        ("a base row's pair", set_value(base["value"] + 1)),
        ("a relation", set_in("assertionVersion", "relation", "correction")),
    ):
        other = copy.deepcopy(base)
        change(other)
        _reversioned(other)
        case(
            f"two rows: a restated value, then {name}",
            sample + off_writer + [resolve_pending.ledger_line(other)],
        )
    not_text = copy.deepcopy(base)
    not_text["assertionVersion"]["supersedes"] = 7
    _reversioned(not_text)
    case(
        "a row that restates nothing supersedes 7",
        sample + writer + [resolve_pending.ledger_line(not_text)],
    )
    # The same order across two rows that are not restatements, and a
    # restatement's supersedes, which only the fold reads.
    pair_off = copy.deepcopy(base)
    pair_off["value"] = base["value"] + 1
    _reversioned(pair_off)
    relation = copy.deepcopy(base)
    relation["assertionVersion"]["relation"] = "correction"
    _reversioned(relation)
    for name, second in (
        ("a relation", relation),
        ("a row that restates nothing supersedes 7", not_text),
    ):
        case(
            f"two rows: a base row's pair, then {name}",
            sample
            + writer
            + [
                resolve_pending.ledger_line(pair_off),
                resolve_pending.ledger_line(second),
            ],
        )
    index, seven = writer_row(PROJECTED_LINE)
    seven["assertionVersion"]["supersedes"] = 7
    _reversioned(seven)
    seven_writer = list(writer)
    seven_writer[index] = resolve_pending.ledger_line(seven)
    case(
        "two rows: a restatement supersedes 7, then a base row's pair",
        sample + seven_writer + [resolve_pending.ledger_line(pair_off)],
    )
    _, corrected = writer_row(CORRECTED_LINE)
    correction = _base_row(
        {**row_of[CORRECTED_LINE], "value": row_of[CORRECTED_LINE]["value"] + 1},
        row_of[CORRECTED_LINE]["source_record_id"],
    )
    correction["assertionVersion"]["supersedes"] = corrected["assertionVersion"]["id"]
    case(
        "a correction follows a restatement",
        sample + writer + [resolve_pending.ledger_line(correction)],
    )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedBy": "scripts/generate_ledger_restatement_fixture.py",
        "source": {
            "repo": source["repo"],
            "sha": source["sha"],
            "path": source["path"],
            "jsonlSha256": source["jsonlSha256"],
            "lineNumbers": [int(number) for number in numbers],
        },
        "retrievedAt": RETRIEVED_AT,
        "sample": sample_refs,
        "writer": writer_refs,
        "lines": table.lines,
        "cases": cases,
    }


def render(fixture: dict[str, Any]) -> str:
    """One line or case per text line, so a regeneration diffs by row."""

    def dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))

    parts = []
    for key, value in fixture.items():
        if key in ("lines", "cases"):
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
                "scripts/generate_ledger_restatement_fixture.py",
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
