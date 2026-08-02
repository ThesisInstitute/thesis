"""Thesis's own data as callable tools for the model loop.

Same shape as `experiments/billimpact/tools.py`: Anthropic tool schemas as
plain dicts (`name` / `description` / `input_schema`) plus a `run_tool`
dispatcher, so these can be concatenated onto the existing tool list and
dispatched by the same loop in `tools.call_with_tools`.

Two tools:

  `thesis_series_history`      the target series as it stood at the forecast
                               origin, from the frozen `ground_truth.json`.
                               Lookahead is not merely absent, it is ENFORCED:
                               every returned observation is checked against
                               both the origin cutoff and the target month, and
                               a violation raises rather than being trimmed
                               away quietly.

  `thesis_resolved_forecasts`  the lab's own track record — resolved Thesis
                               cells with point, 80% interval, the realised
                               official value, and CRPS where the reward export
                               carries one.

Both read repo artifacts only.  `thesis_resolved_forecasts` joins four sealed
surfaces from the same recorder snapshot:

    log/entries/*.json.gz  prediction_recorded  point + interval + resolver
    log/entries/*.json.gz  prediction_resolved  slug -> observationId
    ledger.json.gz         observation_recorded realised value + official source
    reward.json.gz         rewardRows           CRPS / normalized CRPS / coverage

No network, no live site.

Self-test:
    python3 experiments/billimpact/thesis_tools.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
RECORDS = REPO_ROOT / "records"
GROUND_TRUTH = HERE / "ground_truth.json"

MAX_MONTHS = 120


class LookaheadError(RuntimeError):
    """Raised when frozen history would expose an observation at or past the
    forecast origin.  Fail closed: a silently trimmed leak looks identical to
    no leak at all."""


# ---------------------------------------------------------------------------
# frozen corpus
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _units() -> list[dict[str, Any]]:
    return json.loads(GROUND_TRUTH.read_text())


def _data_point_id(unit: dict[str, Any]) -> str:
    """Same construction emit_cells.py uses, so ids round-trip between them."""
    target = unit["target_month"]
    return (
        f"fns.snap.recipients_{unit['state'].lower()}."
        f"{target[:4]}_{target[5:7]}.first_print"
    )


def _match_units(identifier: str) -> list[dict[str, Any]]:
    needle = (identifier or "").strip().lower()
    if not needle:
        return []
    matched = [
        unit
        for unit in _units()
        if needle
        in {
            unit["unit_id"].lower(),
            unit["series_id"].lower(),
            _data_point_id(unit).lower(),
        }
    ]
    if matched:
        return matched
    # A bare state code or series stem is a reasonable thing for a model to
    # try; resolve it rather than returning an unhelpful error.
    return [
        unit
        for unit in _units()
        if needle in unit["unit_id"].lower() or needle in unit["series_id"].lower()
    ]


def thesis_series_history(
    identifier: str,
    last_n_months: int = 60,
) -> dict[str, Any]:
    """Published history of a corpus series as it stood at the forecast origin.

    The cutoff is taken as the STRICTEST across every unit the identifier
    matches, so an ambiguous lookup can only ever narrow the window.
    """
    matched = _match_units(identifier)
    if not matched:
        return {
            "error": f"unknown series or data point: {identifier!r}",
            "known_identifiers": sorted(
                {unit["unit_id"] for unit in _units()}
                | {unit["series_id"] for unit in _units()}
            ),
        }

    series_ids = {unit["series_id"] for unit in matched}
    if len(series_ids) > 1:
        return {
            "error": (
                f"{identifier!r} matches more than one series "
                f"({sorted(series_ids)}); name one exactly"
            )
        }

    # Strictest cutoff wins.
    history_cutoff = min(unit["history_through"] for unit in matched)
    target_floor = min(unit["target_month"] for unit in matched)
    origin_vintage = min(unit["origin_vintage"] for unit in matched)
    history = matched[0]["history"]

    # Enforcement, not assumption.  Anything at or past either boundary is a
    # corpus defect and must stop the run.
    for row in history:
        if row["month"] >= target_floor:
            raise LookaheadError(
                f"{matched[0]['series_id']}: frozen history contains "
                f"{row['month']}, at or after target month {target_floor}"
            )
        if row["month"] > history_cutoff:
            raise LookaheadError(
                f"{matched[0]['series_id']}: frozen history contains "
                f"{row['month']}, after the origin cutoff {history_cutoff}"
            )

    try:
        window = int(last_n_months)
    except (TypeError, ValueError):
        window = 60
    window = max(1, min(window, MAX_MONTHS))
    selected = history[-window:]

    return {
        "series_id": matched[0]["series_id"],
        "data_point_ids": sorted(_data_point_id(unit) for unit in matched),
        "concept": (
            "Persons receiving SNAP benefits, state monthly, not seasonally "
            "adjusted"
        ),
        "unit": "count",
        "origin_vintage": origin_vintage[:10],
        "history_through": history_cutoff[:10],
        "earliest_target_month": target_floor[:10],
        "lookahead_enforced": True,
        "observations_available": len(history),
        "observations_returned": len(selected),
        "observations": [
            {"month": row["month"][:7], "value": row["value"]} for row in selected
        ],
        "source_note": (
            "Read from the ALFRED vintage archive at the origin vintage and "
            "frozen in experiments/billimpact/ground_truth.json before any "
            "model call. ALFRED is a vintage/history mirror here, not the "
            "source of record; the source of record is USDA-FNS."
        ),
    }


# ---------------------------------------------------------------------------
# the lab's own resolved track record
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _snapshot_dir() -> Path:
    """Newest recorder snapshot that carries reward + ledger + log surfaces."""
    best: Optional[tuple[str, Path]] = None
    for digest_path in sorted(RECORDS.glob("*/digest-*.json")):
        try:
            digest = json.loads(digest_path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        surfaces = digest.get("surfaces") or {}
        if not all(key in surfaces for key in ("reward", "ledger", "log")):
            continue
        body = REPO_ROOT / surfaces["reward"]["archivePath"]
        if not body.exists():
            continue
        stamp = str(digest.get("recordedAt") or "")
        if best is None or stamp > best[0]:
            best = (stamp, body.parent)
    if best is None:
        raise RuntimeError(
            "no recorder snapshot under records/ carries reward + ledger + log; "
            "thesis_resolved_forecasts has nothing to read"
        )
    return best[1]


def _read_gz(path: Path) -> Any:
    return json.loads(gzip.decompress(path.read_bytes()))


@lru_cache(maxsize=1)
def _lab_index() -> dict[str, Any]:
    snapshot = _snapshot_dir()

    recorded: dict[str, dict] = {}
    resolved: dict[str, dict] = {}
    entries_dir = snapshot / "log" / "entries"
    for chunk in sorted(entries_dir.glob("*.json.gz")):
        for row in _read_gz(chunk).get("rows", []):
            if row.get("kind") == "prediction_recorded":
                # Keep the first (primary) run per slug.
                recorded.setdefault(row["forecastSlug"], row)
            elif row.get("kind") == "prediction_resolved":
                resolved[row["forecastSlug"]] = row

    ledger = _read_gz(snapshot / "ledger.json.gz")
    observations = {
        entry["observationId"]: entry
        for entry in ledger.get("entries", [])
        if entry.get("kind") == "observation_recorded"
    }

    reward = _read_gz(snapshot / "reward.json.gz")
    scores: dict[str, list[dict]] = {}
    for row in reward.get("rewardRows", []):
        scores.setdefault(row["predictionId"], []).append(row)

    return {
        "snapshot": str(snapshot.relative_to(REPO_ROOT)),
        "recorded": recorded,
        "resolved": resolved,
        "observations": observations,
        "scores": scores,
        "rewardGeneratedAt": reward.get("generatedAt"),
        "ledgerPin": (ledger.get("source") or {}).get("pin", {}).get("sha"),
    }


def _score_for(slug: str, index: dict[str, Any]) -> dict[str, Any]:
    """Best available score row for a slug: the scored agent run if there is
    one, else whatever the export carries, so the caller can see the
    exclusion reason instead of a bare null."""
    rows = index["scores"].get(slug, [])
    if not rows:
        return {"crps": None, "normalizedCrps": None, "interval80Covered": None,
                "scoreEligibility": None, "note": "no reward row for this slug"}
    scored = [r for r in rows if r["reward"]["components"]["crps"] is not None]
    chosen = scored[0] if scored else rows[0]
    components = chosen["reward"]["components"]
    return {
        "runId": chosen["runId"],
        "agent": chosen.get("agent"),
        "model": chosen.get("model"),
        "split": chosen.get("split"),
        "scoreEligibility": chosen.get("scoreEligibility"),
        "crps": components["crps"],
        "normalizedCrps": components["normalizedCrps"],
        "normalizationScale": components["normalizationScale"],
        "normalizationScaleSource": components["normalizationScaleSource"],
        "absoluteError": components["absoluteError"],
        "interval80Covered": components["interval80Covered"],
        "runsForThisSlug": len(rows),
    }


def thesis_resolved_forecasts(
    query: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Resolved Thesis cells matching a program/indicator query.

    Matching is a case-insensitive substring over slug, title, question,
    dataPointId, resolutionSource and unit — deliberately loose, because the
    caller is a model probing for a reference class rather than a person who
    knows the catalog.
    """
    index = _lab_index()
    needle = (query or "").strip().lower()
    tokens = [token for token in re.split(r"[\s,;]+", needle) if token]

    results = []
    for slug, resolution in index["resolved"].items():
        recorded = index["recorded"].get(slug)
        if recorded is None:
            continue
        haystack = " ".join(
            str(recorded.get(field) or "")
            for field in (
                "forecastSlug",
                "title",
                "question",
                "dataPointId",
                "resolutionSource",
                "resolutionRule",
                "unit",
                "country",
            )
        ).lower()
        if tokens and not all(token in haystack for token in tokens):
            continue

        observation = index["observations"].get(resolution.get("observationId") or "")
        interval = recorded.get("interval80") or {}
        realized = observation.get("value") if observation else None
        point = recorded.get("pointEstimate")
        results.append(
            {
                "slug": slug,
                "title": recorded.get("title"),
                "question": recorded.get("question"),
                "country": recorded.get("country"),
                "unit": recorded.get("unit"),
                "dataPointId": recorded.get("dataPointId"),
                "pointEstimate": point,
                "interval80": {
                    "lower": interval.get("lower"),
                    "upper": interval.get("upper"),
                },
                "resolutionDate": recorded.get("resolutionDate"),
                "resolutionPolicy": recorded.get("resolutionPolicy"),
                "resolutionSource": recorded.get("resolutionSource"),
                "realizedValue": realized,
                "realizedObservedAt": observation.get("observedAt") if observation else None,
                "realizedSource": observation.get("source") if observation else None,
                "realizedSourceUrl": observation.get("sourceUrl") if observation else None,
                "realizedSourceKind": observation.get("sourceKind") if observation else None,
                "signedError": (point - realized)
                if (point is not None and realized is not None)
                else None,
                "coveredByInterval80": (
                    interval.get("lower") <= realized <= interval.get("upper")
                )
                if (
                    realized is not None
                    and interval.get("lower") is not None
                    and interval.get("upper") is not None
                )
                else None,
                "score": _score_for(slug, index),
            }
        )

    results.sort(key=lambda row: (row["resolutionDate"] or "", row["slug"]), reverse=True)
    try:
        cap = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        cap = 10

    scored = [r for r in results if r["score"]["crps"] is not None]
    return {
        "query": query,
        "snapshot": index["snapshot"],
        "ledgerPin": index["ledgerPin"],
        "resolvedCellsInSnapshot": len(index["resolved"]),
        "matched": len(results),
        "matchedWithCrps": len(scored),
        "returned": min(cap, len(results)),
        "forecasts": results[:cap],
        "caveat": (
            "Most resolved Thesis cells carry no CRPS: the reward export "
            "attaches score components only to witness-verified runs and the "
            "deterministic persistence baseline, and normalized CRPS "
            "additionally needs three pre-cutoff ledger observations. A null "
            "crps means excluded-by-integrity-gate, not zero error; read "
            "score.scoreEligibility."
        ),
    }


# ---------------------------------------------------------------------------
# tool schemas (same shape as tools.py)
# ---------------------------------------------------------------------------

THESIS_SERIES_HISTORY_TOOL = {
    "name": "thesis_series_history",
    "description": (
        "Look up the published history of a Thesis bill-impact corpus series as "
        "it stood at the forecast origin. Accepts either a Thesis dataPointId "
        "(e.g. 'fns.snap.recipients_ca.2023_12.first_print'), the underlying "
        "series id (e.g. 'BRCA06M647NCEN'), or a corpus unit id (e.g. "
        "'snap.ca.2023-12'). Returns month/value pairs plus the origin vintage "
        "and cutoff. Nothing at or after the forecast origin is reachable "
        "through this tool: the cutoff is enforced on every returned "
        "observation, and an ambiguous identifier narrows the window rather "
        "than widening it. This tool cannot see the future."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "data_point_id": {
                "type": "string",
                "description": (
                    "Thesis dataPointId, series id, or corpus unit id. Either "
                    "this or series_id is required."
                ),
            },
            "series_id": {
                "type": "string",
                "description": "Underlying published series id, e.g. 'BRCA06M647NCEN'.",
            },
            "last_n_months": {
                "type": "integer",
                "description": "How many of the most recent months to return (max 120).",
            },
        },
        "required": [],
    },
}

THESIS_RESOLVED_FORECASTS_TOOL = {
    "name": "thesis_resolved_forecasts",
    "description": (
        "Search the Thesis lab's own resolved forecasts for a reference class. "
        "Give a program or indicator query ('snap', 'poverty', 'initial "
        "claims', 'bls cpi'); all whitespace-separated tokens must match. "
        "Returns each resolved cell's point estimate, 80% interval, the "
        "realised official value with its agency source, whether the interval "
        "covered it, and CRPS where the Brier reward export carries one. Use it "
        "to check how the lab's forecasts on similar series have actually "
        "scored before committing to an interval width."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Program or indicator terms, e.g. 'snap', 'claims', "
                    "'poverty', 'us percent'. Empty string returns the most "
                    "recently resolved cells."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Maximum forecasts to return (default 10, max 100).",
            },
        },
        "required": [],
    },
}

THESIS_TOOLS = [THESIS_SERIES_HISTORY_TOOL, THESIS_RESOLVED_FORECASTS_TOOL]


def run_tool(name: str, args: dict, context: Optional[dict] = None) -> dict:
    """Dispatcher, signature-compatible with tools.run_tool.

    `context` is accepted for interface parity and is unused: these tools read
    frozen repo artifacts, so they cannot be widened by per-run context.
    """
    args = args or {}
    if name == "thesis_series_history":
        identifier = (
            args.get("data_point_id")
            or args.get("series_id")
            or args.get("identifier")
            or ""
        )
        if not identifier:
            return {"error": "one of data_point_id or series_id is required"}
        try:
            return thesis_series_history(identifier, args.get("last_n_months", 60))
        except LookaheadError as exc:
            return {"error": f"lookahead guard tripped: {exc}"}
    if name == "thesis_resolved_forecasts":
        return thesis_resolved_forecasts(args.get("query", ""), args.get("limit", 10))
    return {"error": f"unknown tool: {name}"}


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------


def _print(title: str, payload: Any, head: int = 1400) -> None:
    print(f"\n--- {title} ---")
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    print(text if len(text) <= head else text[:head] + "\n  ...(truncated)")


def _self_test() -> int:
    failures: list[str] = []

    print("=" * 72)
    print("thesis_tools self-test")
    print("=" * 72)
    print(f"ground truth : {GROUND_TRUTH.relative_to(REPO_ROOT)}")
    print(f"gt sha256    : {hashlib.sha256(GROUND_TRUTH.read_bytes()).hexdigest()[:16]}…")
    print(f"snapshot     : {_lab_index()['snapshot']}")
    print(f"ledger pin   : {_lab_index()['ledgerPin']}")

    history = run_tool("thesis_series_history", {"series_id": "BRCA06M647NCEN", "last_n_months": 4})
    _print("thesis_series_history(series_id='BRCA06M647NCEN', last_n_months=4)", history)
    if history.get("error"):
        failures.append("series lookup by series_id failed")

    by_dpid = run_tool(
        "thesis_series_history",
        {"data_point_id": "fns.snap.recipients_ca.2023_12.first_print", "last_n_months": 3},
    )
    _print("thesis_series_history(data_point_id=…ca.2023_12…, last_n_months=3)", by_dpid)
    if by_dpid.get("series_id") != "BRCA06M647NCEN":
        failures.append("dataPointId lookup did not resolve to the right series")

    print("\n--- lookahead check (every corpus series) ---")
    for unit in _units():
        out = run_tool(
            "thesis_series_history",
            {"data_point_id": _data_point_id(unit), "last_n_months": MAX_MONTHS},
        )
        if out.get("error"):
            failures.append(f"{unit['unit_id']}: {out['error']}")
            continue
        newest = out["observations"][-1]["month"]
        ok = newest < unit["target_month"][:7] and newest <= out["history_through"][:7]
        print(
            f"  {unit['unit_id']:20s} newest={newest} "
            f"cutoff={out['history_through'][:7]} target={unit['target_month'][:7]} "
            f"n={out['observations_returned']:3d} {'OK' if ok else 'LEAK'}"
        )
        if not ok:
            failures.append(f"{unit['unit_id']}: lookahead not enforced")

    capped = run_tool("thesis_series_history", {"series_id": "BRNY36M647NCEN", "last_n_months": 9999})
    print(
        f"\n  window cap: asked 9999, returned {capped['observations_returned']} "
        f"(available {capped['observations_available']}, cap {MAX_MONTHS})"
    )
    if capped["observations_returned"] > MAX_MONTHS:
        failures.append("last_n_months cap not enforced")

    unknown = run_tool("thesis_series_history", {"series_id": "NOT_A_SERIES"})
    print(f"  unknown identifier -> error: {unknown.get('error')}")
    if not unknown.get("error"):
        failures.append("unknown identifier did not error")

    snap = run_tool("thesis_resolved_forecasts", {"query": "snap", "limit": 3})
    _print("thesis_resolved_forecasts(query='snap', limit=3)", snap, head=1800)

    claims = run_tool("thesis_resolved_forecasts", {"query": "initial claims", "limit": 2})
    _print("thesis_resolved_forecasts(query='initial claims', limit=2)", claims, head=2600)
    if claims["matched"] == 0:
        failures.append("'initial claims' matched nothing (expected scored rows)")
    if claims["matchedWithCrps"] == 0:
        failures.append("'initial claims' returned no row carrying CRPS")

    everything = run_tool("thesis_resolved_forecasts", {"query": "", "limit": 1})
    print(
        f"\n  corpus-wide: {everything['resolvedCellsInSnapshot']} resolved cells, "
        f"{everything['matched']} matched empty query, "
        f"{everything['matchedWithCrps']} carry CRPS"
    )
    if everything["resolvedCellsInSnapshot"] == 0:
        failures.append("snapshot carries no resolved cells")

    bogus = run_tool("no_such_tool", {})
    print(f"  unknown tool -> {bogus}")
    if not bogus.get("error"):
        failures.append("unknown tool did not error")

    print("\n" + "=" * 72)
    if failures:
        print(f"SELF-TEST FAILED ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("SELF-TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
