#!/usr/bin/env python3
"""Map bill metrics to the Thesis docket and PolicyEngine Ledger catalog.

The mapper is deliberately proposal-only.  It annotates a copy of the bill
artifact and writes Ledger ingestion requests for unknown hinted series, but it
never changes the docket, catalog, or any record artifact.

Usage:
    python scripts/map_bill_metrics.py bills/<slug>.json \
        --catalog /path/to/ledger/series_catalog.json
    python scripts/map_bill_metrics.py bills/<slug>.json \
        --docket scripts/docket_series.json \
        --catalog /path/to/ledger/series_catalog.json
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import tempfile
from collections.abc import Sequence

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DOCKET = ROOT / "scripts" / "docket_series.json"
DEFAULT_DRAFTS_DIR = ROOT / "drafts" / "ledger-ingestion"
RECORDS_DIR = ROOT / "records"


class MappingError(ValueError):
    """Raised when a bill or docket artifact cannot be mapped safely."""


def load_registered_series(docket_path: pathlib.Path) -> list[str]:
    """Load registered series concept IDs, preserving docket order."""
    return list(
        dict.fromkeys(entry["series"] for entry in load_docket_entries(docket_path))
    )


def load_docket_entries(docket_path: pathlib.Path) -> list[dict]:
    """Keep reviewed Chronicle identities, including conflicting period rows."""
    docket = json.loads(docket_path.read_text(encoding="utf-8"))
    if not isinstance(docket, dict) or not isinstance(docket.get("series"), list):
        raise MappingError("docket must be an object with a series array")

    entries: list[dict] = []
    for index, entry in enumerate(docket["series"]):
        if not isinstance(entry, dict):
            raise MappingError(f"docket series entry {index} must be an object")
        concept = entry.get("series")
        if not isinstance(concept, str) or not concept.strip():
            raise MappingError(
                f"docket series entry {index} must have a nonempty series"
            )
        ledger = entry.get("ledger")
        if ledger is not None and (
            not isinstance(ledger, dict)
            or not all(
                isinstance(ledger.get(key), str) and ledger[key].strip()
                for key in ("uuid", "concept")
            )
        ):
            raise MappingError(
                f"docket series entry {index} has invalid ledger identity"
            )
        entries.append({"series": concept.strip(), "ledger": ledger})
    return entries


def load_catalog_series(catalog_path: pathlib.Path) -> list[dict]:
    """Load the Ledger series rows needed for identity matching."""
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not isinstance(catalog.get("series"), list):
        raise MappingError("catalog must be an object with a series array")

    series: list[dict] = []
    for index, entry in enumerate(catalog["series"]):
        if not isinstance(entry, dict):
            raise MappingError(f"catalog series entry {index} must be an object")

        uuid = entry.get("uuid")
        if not isinstance(uuid, str) or not uuid.strip():
            raise MappingError(
                f"catalog series entry {index} must have a nonempty uuid"
            )
        concept = entry.get("concept")
        if not isinstance(concept, str) or not concept.strip():
            raise MappingError(
                f"catalog series entry {index} must have a nonempty concept"
            )
        aliases = entry.get("aliases")
        if not isinstance(aliases, list) or not all(
            isinstance(alias, str) for alias in aliases
        ):
            raise MappingError(
                f"catalog series entry {index} aliases must be an array of strings"
            )
        geography = entry.get("geography")
        if geography is not None and not isinstance(geography, dict):
            raise MappingError(
                f"catalog series entry {index} geography must be an object or null"
            )
        entity = entry.get("entity")
        if entity is not None and not isinstance(entity, dict):
            raise MappingError(
                f"catalog series entry {index} entity must be an object or null"
            )
        source_concepts = entry.get("source_concepts")
        if not isinstance(source_concepts, list) or not all(
            isinstance(source_concept, str) for source_concept in source_concepts
        ):
            raise MappingError(
                "catalog series entry "
                f"{index} source_concepts must be an array of strings"
            )

        series.append(
            {
                "uuid": uuid.strip(),
                "concept": concept.strip(),
                "aliases": aliases,
                "geography": geography,
                "entity": entity,
                "source_concepts": source_concepts,
            }
        )
    return series


def registered_match_candidates(hint: str, registered: Sequence[str]) -> list[str]:
    """Exact identity wins; preserve every distinct descendant for review."""
    if hint in registered:
        return [hint]
    return sorted({concept for concept in registered if concept.startswith(f"{hint}.")})


def match_registered_series(hint: str, registered: Sequence[str]) -> str | None:
    """Return only an exact or unambiguous dot-descendant registry match."""
    candidates = registered_match_candidates(hint, registered)
    return candidates[0] if len(candidates) == 1 else None


def catalog_match_candidates(hint: str, catalog: Sequence[dict]) -> list[dict]:
    """Return every candidate at the first catalog matching tier with hits."""
    tiers = (
        lambda entry: entry["concept"] == hint,
        lambda entry: hint in entry["aliases"],
        lambda entry: hint in entry["source_concepts"],
        lambda entry: entry["concept"].startswith(f"{hint}."),
    )
    for tier_index, predicate in enumerate(tiers):
        candidates = [entry for entry in catalog if predicate(entry)]
        if not candidates:
            continue

        if tier_index == 2:
            # source_concepts are publisher provenance, not row identities. A
            # source-label hit identifies a concept, so retain every geography
            # and entity identity carrying that concept for disambiguation.
            concepts = {entry["concept"] for entry in candidates}
            candidates = [entry for entry in catalog if entry["concept"] in concepts]
        return candidates
    return []


def resolve_catalog_series(
    hint: str, catalog: Sequence[dict]
) -> tuple[dict | None, list[dict]]:
    """Resolve a catalog hint and preserve ambiguous candidates for triage."""
    candidates = catalog_match_candidates(hint, catalog)
    if len(candidates) == 1:
        return candidates[0], candidates
    if not candidates:
        return None, candidates

    national = [
        entry
        for entry in candidates
        if isinstance(entry["geography"], dict)
        and entry["geography"].get("level") == "country"
        and entry["geography"].get("id") == "0100000US"
    ]
    if len(national) == 1 and len({entry["concept"] for entry in candidates}) == 1:
        return national[0], candidates
    return None, candidates


def match_catalog_series(hint: str, catalog: Sequence[dict]) -> dict | None:
    """Return the unambiguous catalog match for ``hint``, if one exists."""
    match, _ = resolve_catalog_series(hint, catalog)
    return match


def slugify_hint(hint: str) -> str:
    """Convert a dotted series hint to the repository's filename style."""
    slug = re.sub(r"[^a-z0-9]+", "-", hint.lower()).strip("-")
    if not slug:
        raise MappingError(f"series_hint cannot form a draft filename: {hint!r}")
    return slug


def bill_slug(artifact: dict, input_path: pathlib.Path) -> str:
    """Read the canonical slug from the bill artifact."""
    bill = artifact.get("bill")
    slug = bill.get("slug") if isinstance(bill, dict) else None
    if not isinstance(slug, str) or not slug.strip():
        raise MappingError(f"{input_path} must contain a nonempty bill.slug")
    return slug.strip()


def _assert_not_records(path: pathlib.Path) -> None:
    try:
        path.resolve().relative_to(RECORDS_DIR.resolve())
    except ValueError:
        return
    raise MappingError(f"refusing to write under records/: {path}")


def _assert_not_source(path: pathlib.Path, *sources: pathlib.Path) -> None:
    resolved = path.resolve()
    for source in sources:
        if resolved == source.resolve():
            raise MappingError(f"refusing to overwrite source artifact: {source}")


def mapped_output_path(input_path: pathlib.Path) -> pathlib.Path:
    """Return ``<input-stem>.mapped.json`` beside the input artifact."""
    if input_path.suffix == ".json":
        return input_path.with_suffix(".mapped.json")
    return input_path.with_name(f"{input_path.name}.mapped.json")


def map_artifact(
    artifact: dict,
    registered: Sequence[str],
    catalog: Sequence[dict],
    *,
    proposed_from: str,
    docket_entries: Sequence[dict] = (),
) -> tuple[dict, list[dict]]:
    """Annotate an artifact in place and return unique ingestion requests."""
    provisions = artifact.get("provisions")
    if not isinstance(provisions, list):
        raise MappingError("bill artifact must contain a provisions array")

    summary = {"reachable": 0, "ledger": 0, "notYet": 0, "unmapped": 0}
    requests_by_hint: dict[str, dict] = {}

    for provision_index, provision in enumerate(provisions):
        if not isinstance(provision, dict):
            raise MappingError(f"provision {provision_index} must be an object")
        metrics = provision.get("metrics")
        if not isinstance(metrics, list):
            raise MappingError(
                f"provision {provision_index} must contain a metrics array"
            )

        for metric_index, metric in enumerate(metrics):
            if not isinstance(metric, dict):
                raise MappingError(
                    f"provision {provision_index} metric {metric_index} "
                    "must be an object"
                )
            raw_hint = metric.get("series_hint")
            if raw_hint is not None and not isinstance(raw_hint, str):
                raise MappingError(
                    f"provision {provision_index} metric {metric_index} "
                    "series_hint must be a string or null"
                )
            hint = raw_hint.strip() if isinstance(raw_hint, str) else ""
            match = match_registered_series(hint, registered) if hint else None
            registered_candidates = (
                registered_match_candidates(hint, registered) if hint else []
            )
            catalog_match, catalog_candidates = (
                resolve_catalog_series(hint, catalog) if hint else (None, [])
            )
            canonical_candidates = (
                registered_match_candidates(catalog_match["concept"], registered)
                if catalog_match is not None
                else []
            )
            canonical_rows = (
                [
                    entry
                    for entry in docket_entries
                    if entry["series"] == catalog_match["concept"]
                ]
                if catalog_match is not None
                else []
            )
            # A concept match alone cannot translate a catalog alias into docket
            # admission: a state row and a national row share concept strings.
            # The exact concept AND Chronicle UUID must match every docket row.
            catalog_registered_match = None
            if (
                catalog_match is not None
                and catalog_match["concept"] in registered
                and canonical_rows
                and all(
                    isinstance(entry.get("ledger"), dict)
                    and entry["ledger"].get("uuid") == catalog_match["uuid"]
                    and entry["ledger"].get("concept") == catalog_match["concept"]
                    for entry in canonical_rows
                )
            ):
                catalog_registered_match = catalog_match["concept"]
            identity_conflict = (
                bool(canonical_candidates) and catalog_registered_match is None
            )

            metric.pop("matched_series", None)
            metric.pop("ledger_uuid", None)
            if match is not None:
                metric["registry"] = "reachable"
                metric["matched_series"] = match
                summary["reachable"] += 1
            elif (
                catalog_registered_match is not None and len(registered_candidates) <= 1
            ):
                metric["registry"] = "reachable"
                metric["matched_series"] = catalog_registered_match
                metric["ledger_uuid"] = catalog_match["uuid"]
                summary["reachable"] += 1
            elif (
                catalog_match is not None
                and len(registered_candidates) <= 1
                and not identity_conflict
            ):
                metric["registry"] = "ledger"
                metric["matched_series"] = catalog_match["concept"]
                metric["ledger_uuid"] = catalog_match["uuid"]
                summary["ledger"] += 1
            elif hint:
                metric["registry"] = "not-yet"
                summary["notYet"] += 1
                if len(registered_candidates) > 1:
                    note = (
                        f"Ambiguous docket match for {hint!r}; candidates: "
                        + ", ".join(registered_candidates)
                        + ". A curator must select the exact outcome series."
                    )
                elif identity_conflict:
                    note = (
                        "Catalog identity does not exactly match the reviewed docket "
                        "concept and Chronicle UUID. Review geography/entity and "
                        "parent/child scope before mapping this metric to admission."
                    )
                elif catalog_candidates:
                    candidate_uuids = ", ".join(
                        entry["uuid"] for entry in catalog_candidates
                    )
                    note = (
                        f"Ambiguous Ledger catalog match for {hint!r}; candidate "
                        f"UUIDs: {candidate_uuids}. A curator must select or "
                        "clarify the intended geography and entity identity."
                    )
                else:
                    note = (
                        "Proposed catalog row for PolicyEngine/chronicle "
                        "series_catalog.json; verify identity, unit, cadence, "
                        "and official source before ingestion."
                    )
                requests_by_hint.setdefault(
                    hint,
                    {
                        "proposed_concept": hint,
                        "status": "proposed",
                        "unit": None,
                        "cadence": None,
                        "proposedFrom": proposed_from,
                        "metricText": metric.get("text"),
                        "note": note,
                    },
                )
            else:
                metric["registry"] = "unmapped"
                summary["unmapped"] += 1

    artifact["summary"] = summary
    return artifact, list(requests_by_hint.values())


def write_json(path: pathlib.Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True
    )
    temporary_path = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            temporary.write(body)
        temporary_path.chmod(0o644)
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def map_bill_metrics(
    input_path: pathlib.Path,
    docket_path: pathlib.Path,
    catalog_path: pathlib.Path,
    *,
    drafts_dir: pathlib.Path = DEFAULT_DRAFTS_DIR,
) -> tuple[pathlib.Path, list[pathlib.Path]]:
    """Map one bill artifact and write its copy and ingestion requests."""
    artifact = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(artifact, dict):
        raise MappingError("bill artifact must be a JSON object")

    proposed_from = bill_slug(artifact, input_path)
    registered = load_registered_series(docket_path)
    catalog = load_catalog_series(catalog_path)
    mapped, proposals = map_artifact(
        artifact,
        registered,
        catalog,
        proposed_from=proposed_from,
        docket_entries=load_docket_entries(docket_path),
    )

    output_path = mapped_output_path(input_path)
    _assert_not_records(output_path)
    _assert_not_records(drafts_dir)
    _assert_not_source(output_path, input_path, docket_path, catalog_path)

    planned_drafts: list[tuple[pathlib.Path, dict]] = []
    slugs: dict[str, str] = {}
    for proposal in proposals:
        hint = proposal["proposed_concept"]
        draft_slug = slugify_hint(hint)
        previous_hint = slugs.setdefault(draft_slug, hint)
        if previous_hint != hint:
            raise MappingError(
                "series hints produce the same draft filename: "
                f"{previous_hint!r} and {hint!r}"
            )
        draft_path = drafts_dir / f"{draft_slug}.json"
        _assert_not_records(draft_path)
        _assert_not_source(draft_path, input_path, docket_path, catalog_path)
        if draft_path.exists():
            try:
                existing = json.loads(draft_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise MappingError(
                    f"existing draft is not readable JSON: {draft_path}"
                ) from error
            existing_hint = (
                existing.get("proposed_concept") if isinstance(existing, dict) else None
            )
            if existing_hint != hint:
                raise MappingError(
                    f"draft filename {draft_path.name} already belongs to "
                    f"series {existing_hint!r}, not {hint!r}"
                )
        planned_drafts.append((draft_path, proposal))

    for draft_path, proposal in planned_drafts:
        write_json(draft_path, proposal)
    write_json(output_path, mapped)
    return output_path, [path for path, _ in planned_drafts]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Map bill metrics to the Thesis docket and Ledger catalog."
    )
    parser.add_argument("input", type=pathlib.Path, help="bill artifact JSON")
    parser.add_argument(
        "--docket",
        type=pathlib.Path,
        default=DEFAULT_DOCKET,
        help=f"series registry (default: {DEFAULT_DOCKET.relative_to(ROOT)})",
    )
    parser.add_argument(
        "--catalog",
        type=pathlib.Path,
        required=True,
        help="PolicyEngine Ledger series_catalog.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_path, draft_paths = map_bill_metrics(args.input, args.docket, args.catalog)
    summary = json.loads(output_path.read_text(encoding="utf-8"))["summary"]
    print(
        f"wrote {output_path} "
        f"(reachable={summary['reachable']}, ledger={summary['ledger']}, "
        f"not-yet={summary['notYet']}, unmapped={summary['unmapped']}, "
        f"ingestion-requests={len(draft_paths)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
