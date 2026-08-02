#!/usr/bin/env python3
"""Emit the bill-impact forecasts as house forecast cells, then let the house
validators judge them.

The point of this script is NOT to get a pass. It is to express our runs in
`docs/cell-contract.md` shape as faithfully as the run records allow, hand the
result to the repo's own gate (`scripts/spawned_cells_to_ts.py:validate`, whose
semantics `site/src/__tests__/trace-depth.test.ts` mirrors in CI), and print
exactly which requirements fail and why.

Three things are deliberately NOT done, because doing them would be fabrication
dressed as compliance:

  * No `kind: "tool"` reasoning steps.  These runs are single-shot Anthropic
    API calls with an empty tool list; the series history was pasted into the
    prompt by `harness.py`, not fetched by the model.  Writing a tool step
    would attribute a fetch to an agent that never made one — the exact
    failure mode `docs/thesis-analyst-runner.md` records for 2026-07-24.
  * No sigma-shaped math step.  The elicitation contract never asked the model
    to derive its interval width, so there is no derivation to publish.  The
    math step reports the arithmetic that genuinely exists (the elicited
    triple and the CDF knots it seeds) and the rubric is left to fail on it.
  * No invented `runAt`.  `harness.py` records `duration_s` per call and no
    wall clock, so the emitted cells carry `runAt: null`.

Output: `experiments/billimpact/cells/*.json` (converter-shaped lists) plus
`cells/_validation.json`.  Nothing is written under `site/`, and no catalog is
touched.

Run:
    python3 experiments/billimpact/emit_cells.py
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
OUT_DIR = HERE / "cells"

GROUND_TRUTH = HERE / "ground_truth.json"
# Prefer the corrected re-extraction when it exists: `runs_api.reparsed.jsonl`
# is the same rows re-read by parse_forecast_v2 after the v1 prose fallback was
# found extracting calendar years. Which file was used is printed and sealed
# into every cell's billimpactProvenance.
RUNS_CANONICAL = HERE / "runs_api.jsonl"
RUNS_REPARSED = HERE / "runs_api.reparsed.jsonl"
RUNS = RUNS_REPARSED if RUNS_REPARSED.exists() else RUNS_CANONICAL
PROVISIONS = HERE / "provisions.json"

# The pre-registered primary elicitation lane (PREREGISTRATION.md, Arm A x B
# intersection): the whole D1 policy_context dimension, everything else held
# at the primary level.  Five configurations x twelve units = sixty cells.
REFERENCE_CONFIG = {
    "elicitation": "point_ci_json",
    "pipeline": "single_pass",
    "model": "claude-sonnet-5",
    "magnitude": "actual",
}
POLICY_CONTEXTS = [
    "none",
    "summary",
    "operative_only",
    "purpose_only",
    "operative_plus_purpose",
]

POLICY_CONTEXT_LABEL = {
    "none": "no statutory context (unconditioned baseline)",
    "summary": "neutral operational summary, no statutory text",
    "operative_only": "FRA 2023 §§311, 312, 314 verbatim",
    "purpose_only": "FRA 2023 §313 verbatim (statement of purpose only)",
    "operative_plus_purpose": "FRA 2023 §§311–314 verbatim",
}

STATE_NAME = {
    "CA": "California",
    "FL": "Florida",
    "NY": "New York",
    "TX": "Texas",
    "PA": "Pennsylvania",
    "OH": "Ohio",
}

# Official agency source of record for SNAP participation.  This exact URL is
# already used by the repo's own FNS cells; ALFRED appears only as the
# vintage/history mirror it actually was, never as the resolver (AGENTS.md).
FNS_SNAP_URL = "https://www.fns.usda.gov/pd/supplemental-nutrition-assistance-program-snap"
ALFRED_CSV = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"

# Used ONLY to let the validator's date-gated checks execute so we can
# enumerate every other failure.  Never written into an emitted cell.
DIAGNOSTIC_ONLY_RUN_AT = (
    datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
)


# ---------------------------------------------------------------------------
# repo modules, loaded rather than reimplemented
# ---------------------------------------------------------------------------


def load_repo_module(rel_path: str, alias: str):
    scripts_dir = REPO_ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {rel_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def interval_distribution(point: float, lo: float, hi: float) -> dict[str, Any]:
    """The house CDF transform, imported — never reimplemented."""
    sys.path.insert(0, str(HERE))
    from scoring import interval_distribution as house_transform  # noqa: PLC0415

    return house_transform(point, lo, hi)


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------


def month_label(iso_month: str) -> str:
    return datetime.strptime(iso_month, "%Y-%m-%d").strftime("%b %Y")


def load_units() -> dict[str, dict[str, Any]]:
    return {unit["unit_id"]: unit for unit in json.loads(GROUND_TRUTH.read_text())}


def load_provisions() -> dict[str, Any]:
    if not PROVISIONS.exists():
        return {}
    return json.loads(PROVISIONS.read_text())


def load_reference_runs() -> tuple[list[dict], dict[str, Any]]:
    raw = RUNS.read_bytes()
    rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    selected = [
        row
        for row in rows
        if all(row["config"].get(key) == value for key, value in REFERENCE_CONFIG.items())
        and row["config"].get("policy_context") in POLICY_CONTEXTS
    ]
    return selected, {
        "path": str(RUNS.relative_to(REPO_ROOT)),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "totalRows": len(rows),
        "selectedRows": len(selected),
    }


def median_by_point(runs: list[dict]) -> dict | None:
    """Pick the representative repeat.

    Taking a componentwise median of (point, ciLow, ciHigh) would synthesise a
    triple no run ever produced and could in principle unorder it.  Instead we
    keep the run whose POINT is the (lower) median, so the emitted cell is an
    actually-elicited forecast, and record which repeat that was.
    """
    usable = [
        run
        for run in runs
        if run.get("forecast")
        and run["forecast"].get("point") is not None
        and run["forecast"].get("ci_low") is not None
        and run["forecast"].get("ci_high") is not None
        and run["forecast"]["ci_low"] < run["forecast"]["ci_high"]
    ]
    if not usable:
        return None
    ordered = sorted(usable, key=lambda r: (r["forecast"]["point"], r.get("rep") or 0))
    return ordered[(len(ordered) - 1) // 2]


# ---------------------------------------------------------------------------
# cell construction
# ---------------------------------------------------------------------------


def build_reasoning(
    unit: dict[str, Any],
    run: dict[str, Any],
    siblings: list[dict],
    provisions: dict[str, Any],
) -> list[dict[str, Any]]:
    history = unit["history"]
    values = [row["value"] for row in history]
    diffs = [values[i] - values[i - 1] for i in range(1, len(values))]
    forecast = run["forecast"]
    point, lo, hi = forecast["point"], forecast["ci_low"], forecast["ci_high"]
    truth = unit["truth"]
    context = run["config"]["policy_context"]
    provision_ids = (run.get("context_meta") or {}).get("provisions") or []
    provision_bits = []
    for pid in provision_ids:
        text = provisions.get(pid) if isinstance(provisions, dict) else None
        digest = (
            hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
            if isinstance(text, str)
            else None
        )
        provision_bits.append(f"{pid}" + (f" (sha256 {digest})" if digest else ""))

    steps: list[dict[str, Any]] = [
        {
            "kind": "heading",
            "text": (
                f"{STATE_NAME.get(unit['state'], unit['state'])} SNAP recipients, "
                f"{month_label(unit['target_month'])} — bill-impact ablation cell "
                f"({context})"
            ),
        },
        {
            "kind": "text",
            "text": (
                "Provenance of this cell, stated first because it changes how "
                "everything below should be read: this is a RETRODICTION from the "
                "`experiments/billimpact` harness-sensitivity ablation, not a "
                "thesis.analyst forecast wave. A single Anthropic API call was made "
                "with no tools available; the model saw only a prompt assembled by "
                "`experiments/billimpact/harness.py`. Every number attributed to a "
                "source below was fetched by the harness's ground-truth stage "
                "(`fetch_ground_truth.py`) before any model call, not by the "
                "forecaster."
            ),
        },
        {
            "kind": "text",
            "text": (
                f"Resolver: Census/USDA-FNS series {unit['series_id']}, "
                f"state-level monthly SNAP recipients (persons) for "
                f"{month_label(unit['target_month'])}, first print. The official "
                "series of record is USDA Food and Nutrition Service SNAP program "
                "data; the first print used here was recovered from the ALFRED "
                "vintage archive acting strictly as a history/vintage mirror, and "
                "no official FNS release artifact was fetched for this cell."
            ),
        },
        {
            "kind": "text",
            "text": (
                "History supplied to the forecaster, read at the ALFRED "
                f"{unit['origin_vintage'][:10]} vintage and truncated at "
                f"{unit['history_through'][:10]}: {len(values)} monthly "
                f"observations from {history[0]['month'][:7]} to "
                f"{history[-1]['month'][:7]}, ending at "
                f"{values[-1]:,.0f} recipients. This series publishes with a "
                "multi-year lag, so at the forecast origin the newest available "
                f"print was {history[-1]['month'][:7]} — "
                f"{months_between(history[-1]['month'], unit['target_month'])} "
                "months before the target month. Nothing at or after the target "
                "month was available; the harness enforces the truncation."
            ),
        },
        {
            "kind": "text",
            "text": (
                "Base rate / reference class: the trailing "
                f"{len(values)} monthly prints ending {history[-1]['month'][:7]} "
                f"have mean {statistics.fmean(values):,.0f} and range "
                f"{min(values):,.0f} to {max(values):,.0f}. Their "
                f"{len(diffs)} month-over-month changes have mean "
                f"{statistics.fmean(diffs):,.0f} and sample standard deviation "
                f"{statistics.stdev(diffs):,.0f} recipients per month, which is the "
                "same one-step dispersion the Brier reward export uses as its "
                "normalization scale."
            ),
        },
        {
            "kind": "text",
            "text": (
                "Policy conditioning for this cell: "
                f"`policy_context = {context}` — {POLICY_CONTEXT_LABEL[context]}."
                + (
                    " Provisions in the prompt: " + "; ".join(provision_bits) + "."
                    if provision_bits
                    else " No statutory text was placed in the prompt."
                )
                + " The statute is the Fiscal Responsibility Act of 2023, "
                "Pub. L. 118-5, Title III, enacted 2023-06-03; text is stored "
                "verbatim at `experiments/billimpact/bills/FRA-2023-118publ5.txt`."
            ),
        },
        {
            "kind": "text",
            "text": (
                "Forecaster's own rationale, quoted verbatim from the run record "
                f"(`cell_key = {run['cell_key']}`): "
                + json.dumps(model_rationale(run))
            ),
        },
        {
            "kind": "math",
            "text": (
                "Interval derivation is NOT available for this cell, and that is a "
                "property of the elicitation contract rather than an omission here: "
                "the `point_ci_json` prompt asks for a point and an 80% interval and "
                "never asks the model to disclose a sigma or a z-multiplier, so no "
                "derivation exists to publish and none is invented. What is "
                f"arithmetically true of the elicited triple: point = {point:,.0f}, "
                f"80% interval [{lo:,.0f}, {hi:,.0f}], half-widths "
                f"{point - lo:,.0f} below and {hi - point:,.0f} above, total width "
                f"{hi - lo:,.0f} recipients. Those five numbers seed the house "
                "`interval_anchor_v1` transform "
                "(`scripts/run_thesis_analyst.py:interval_distribution`) at CDF "
                "knots 0.1 / 0.5 / 0.9, and the resulting 201-point CDF is carried "
                "in `predictionDistribution`. For scale, the trailing one-step "
                f"dispersion above is {statistics.stdev(diffs):,.0f} per month and "
                "the target is "
                f"{months_between(history[-1]['month'], unit['target_month'])} "
                "months out."
            ),
        },
        {
            "kind": "text",
            "text": (
                "Repeat structure: this configuration was run "
                f"{len(siblings)} times at temperature 1.0; the emitted cell is the "
                f"median-by-point repeat (rep {run.get('rep')}), so it is an "
                "actually-elicited triple rather than a synthesised one. Across "
                f"repeats the points ranged {min(s['forecast']['point'] for s in siblings):,.0f} "
                f"to {max(s['forecast']['point'] for s in siblings):,.0f}. That "
                "spread is the experiment's noise floor and is the object of study, "
                "not a defect."
            ),
        },
        {
            "kind": "text",
            "text": (
                "Already-known outcome, disclosed rather than hidden: the first "
                f"print for this unit is {truth['first_print_value']:,.0f}, "
                f"discovered at ALFRED vintage {truth['first_print_vintage'][:10]} "
                f"with a revision of {truth['revision']:,.0f} to the current "
                "vintage. It was public before this experiment ran, so this cell "
                "must never enter a forward-looking scoring population."
            ),
        },
        {
            "kind": "forecast",
            "point": point,
            "ciLow": lo,
            "ciHigh": hi,
        },
    ]
    return steps


def model_rationale(run: dict[str, Any]) -> str:
    text = run.get("final_text") or ""
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        obj = json.loads(text[start:end])
        rationale = obj.get("rationale")
        if isinstance(rationale, str) and rationale.strip():
            return rationale.strip()
    except (ValueError, json.JSONDecodeError):
        pass
    return text.strip()[:1200] or "(the run record carries no rationale text)"


def months_between(start: str, end: str) -> int:
    sy, sm = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    return (ey - sy) * 12 + (em - sm)


def build_cell(
    unit: dict[str, Any],
    run: dict[str, Any],
    siblings: list[dict],
    provisions: dict[str, Any],
    run_meta: dict[str, Any],
) -> dict[str, Any]:
    forecast = run["forecast"]
    point, lo, hi = forecast["point"], forecast["ci_low"], forecast["ci_high"]
    context = run["config"]["policy_context"]
    state = unit["state"]
    target = unit["target_month"]
    truth = unit["truth"]
    history = unit["history"]
    slug = (
        f"billimpact-snap-{state.lower()}-{target[:4]}-{target[5:7]}-"
        + context.replace("_", "-")
    )
    period_token = f"{target[:4]}_{target[5:7]}"

    return {
        "slug": slug,
        "country": "US",
        "type": "data",
        "title": (
            f"{STATE_NAME.get(state, state)} SNAP Recipients "
            f"{month_label(target)} ({context})"
        ),
        "question": (
            f"Number of persons receiving SNAP benefits in "
            f"{STATE_NAME.get(state, state)} in {month_label(target)}, "
            f"not seasonally adjusted, as first published for series "
            f"{unit['series_id']} (Census Bureau / USDA-FNS state monthly SNAP "
            "recipients), first print, revisions ignored."
        ),
        "unit": "count",
        "pointEstimate": point,
        "ciLow": lo,
        "ciHigh": hi,
        "confidence": 0.8,
        # NOT inferred from cadence: this is the empirically discovered vintage
        # at which the value first appeared, from the forward vintage walk in
        # fetch_ground_truth.py:discover_first_print.
        "resolutionDate": truth["first_print_vintage"][:10],
        "resolutionSource": (
            "USDA Food and Nutrition Service, SNAP state-level participation "
            "(program data); first print recovered via the ALFRED vintage archive "
            "as a history mirror"
        ),
        "resolutionSourceUrl": FNS_SNAP_URL,
        "resolutionRule": (
            f"Resolve to the first published value of series {unit['series_id']} "
            f"for observation month {target[:10]} — persons receiving SNAP "
            f"benefits in {STATE_NAME.get(state, state)}, not seasonally adjusted, "
            "as reported by USDA-FNS and mirrored by the Census Bureau small-area "
            "series. First print only: the resolving value is the one carried by "
            "the earliest vintage in which the observation is non-missing, found "
            "by walking vintages forward month by month "
            "(fetch_ground_truth.py:discover_first_print). Later revisions are "
            "ignored. The vintage walk was executed against the ALFRED vintage "
            "archive, which is used strictly as a vintage/history mirror and is "
            "NOT the source of record; the source of record is the USDA-FNS "
            "release. For this unit the first print appeared at vintage "
            f"{truth['first_print_vintage'][:10]} and the revision from first "
            f"print to the current vintage is {truth['revision']:,.0f}."
        ),
        "dataPointId": f"fns.snap.recipients_{state.lower()}.{period_token}.first_print",
        "historicalContext": [
            {"label": row["month"][:7], "value": row["value"]}
            for row in history[-6:]
        ],
        "drivers": [
            f"Trailing {len(history)} monthly prints end {history[-1]['month'][:7]} "
            f"at {history[-1]['value']:,.0f}, "
            f"{months_between(history[-1]['month'], target)} months before target",
            f"Policy conditioning level: {POLICY_CONTEXT_LABEL[context]}",
            "FRA 2023 §311 ABAWD age caps phase in from roughly 2023-09-01, at "
            "initial certification or recertification",
            "Post-pandemic emergency-allotment unwind dominates the level shift "
            "over the forecast horizon",
            "Single-shot elicitation at temperature 1.0; repeat spread is the "
            "experiment's noise floor",
        ],
        "sourceContext": [
            f"{ALFRED_CSV}?id={unit['series_id']}&vintage_date={unit['origin_vintage'][:10]}",
            f"{ALFRED_CSV}?id={unit['series_id']}&vintage_date={truth['first_print_vintage'][:10]}",
        ],
        # harness.py records duration_s per call and no wall clock, so there is
        # no run timestamp to publish.  Null, not invented.
        "runAt": None,
        "predictionDistribution": interval_distribution(point, lo, hi),
        "model": run["config"]["model"],
        "reasoning": build_reasoning(unit, run, siblings, provisions),
        "billimpactProvenance": {
            "experiment": "experiments/billimpact (Leg B, harness sensitivity)",
            "preregistration": "experiments/billimpact/PREREGISTRATION.md",
            "unitId": unit["unit_id"],
            "cellKey": run["cell_key"],
            "runsFile": run_meta["path"],
            "runsFileSha256": run_meta["sha256"],
            "parseMode": run["forecast"].get("parse_mode"),
            "config": run["config"],
            "repSelected": run.get("rep"),
            "repCount": len(siblings),
            "repSelectionRule": "median-by-point across repeats, lower median on ties",
            "toolCallsInRun": 0,
            "runAtProvenance": (
                "unrecorded — experiments/billimpact/harness.py stamps duration_s "
                "per API call and no wall-clock timestamp"
            ),
            "realizedFirstPrint": truth["first_print_value"],
            "realizedFirstPrintVintage": truth["first_print_vintage"][:10],
            "alreadyPublicAtRunTime": True,
        },
    }


# ---------------------------------------------------------------------------
# validation against the repo's own gate
# ---------------------------------------------------------------------------


def validate_against_repo(cells: list[dict[str, Any]]) -> dict[str, Any]:
    converter = load_repo_module("scripts/spawned_cells_to_ts.py", "_spawned_cells_to_ts")
    site_data = REPO_ROOT / "site/src/data"
    taken = converter.existing_slugs(site_data, OUT_DIR / "__never__.ts")

    results = []
    seen: set[str] = set()
    for cell in cells:
        strict_errors: list[str] = []
        try:
            strict_errors = converter.validate(copy.deepcopy(cell), taken | seen)
        except Exception as exc:  # noqa: BLE001 — the crash IS a finding
            strict_errors = [
                f"validator raised {type(exc).__name__}: {exc} "
                "(runAt is null, and validate() assumes a string)"
            ]
        diagnostic = copy.deepcopy(cell)
        diagnostic["runAt"] = DIAGNOSTIC_ONLY_RUN_AT
        try:
            diagnostic_errors = converter.validate(diagnostic, taken | seen)
        except Exception as exc:  # noqa: BLE001
            diagnostic_errors = [f"validator raised {type(exc).__name__}: {exc}"]
        seen.add(cell["slug"])
        results.append(
            {
                "slug": cell["slug"],
                "strictErrors": strict_errors,
                "diagnosticErrors": diagnostic_errors,
                "passes": not strict_errors,
            }
        )

    tally: dict[str, int] = {}
    for result in results:
        for error in result["diagnosticErrors"]:
            key = normalize_error(error)
            tally[key] = tally.get(key, 0) + 1
    return {
        "validator": "scripts/spawned_cells_to_ts.py:validate",
        "ciMirror": "site/src/__tests__/trace-depth.test.ts",
        "diagnosticOnlyRunAt": DIAGNOSTIC_ONLY_RUN_AT,
        "cells": len(cells),
        "passing": sum(1 for result in results if result["passes"]),
        "failureTally": dict(sorted(tally.items(), key=lambda kv: -kv[1])),
        "perCell": results,
    }


def normalize_error(error: str) -> str:
    """Collapse per-cell specifics so the tally counts requirement classes."""
    if error.startswith("only ") and "reasoning steps" in error:
        return "reasoning steps < 7"
    if error.startswith("only ") and "tool steps" in error:
        return "tool steps < 2"
    if error.startswith("resolutionDate ") and "leakage" in error:
        return "resolutionDate not after runAt (leakage gate)"
    if error.startswith("validator raised"):
        return error.split("(")[0].strip()
    return error


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    units = load_units()
    provisions = load_provisions()
    runs, run_meta = load_reference_runs()

    grouped: dict[tuple[str, str], list[dict]] = {}
    for run in runs:
        key = (run["unit_id"], run["config"]["policy_context"])
        grouped.setdefault(key, []).append(run)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_cells: list[dict[str, Any]] = []
    missing: list[str] = []
    by_context: dict[str, list[dict]] = {ctx: [] for ctx in POLICY_CONTEXTS}

    for context in POLICY_CONTEXTS:
        for unit_id, unit in units.items():
            siblings = grouped.get((unit_id, context), [])
            chosen = median_by_point(siblings)
            if chosen is None:
                missing.append(f"{unit_id}|{context}")
                continue
            usable = [
                s
                for s in siblings
                if s.get("forecast") and s["forecast"].get("point") is not None
            ]
            cell = build_cell(unit, chosen, usable, provisions, run_meta)
            by_context[context].append(cell)
            all_cells.append(cell)

    for context, cells in by_context.items():
        path = OUT_DIR / f"billimpact-snap-{context.replace('_', '-')}.json"
        path.write_text(json.dumps(cells, indent=2, ensure_ascii=False) + "\n")

    report = validate_against_repo(all_cells)
    report["reference"] = {
        "config": REFERENCE_CONFIG,
        "policyContexts": POLICY_CONTEXTS,
        "units": len(units),
        "expectedCells": len(units) * len(POLICY_CONTEXTS),
        "emittedCells": len(all_cells),
        "missingCombinations": missing,
        "runsFile": run_meta["path"],
        "runsFileSha256": run_meta["sha256"],
        "runsFileRows": run_meta["totalRows"],
        "runsMatchingReferenceConfig": run_meta["selectedRows"],
    }
    (OUT_DIR / "_validation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )

    print(f"reference configuration : {REFERENCE_CONFIG}")
    print(f"policy_context levels   : {POLICY_CONTEXTS}")
    print(
        f"runs file               : {run_meta['path']} "
        f"(sha256 {run_meta['sha256'][:16]}…) — {run_meta['totalRows']} rows, "
        f"{run_meta['selectedRows']} match the reference lane"
    )
    print(f"cells emitted           : {len(all_cells)} -> {OUT_DIR.relative_to(REPO_ROOT)}/")
    if missing:
        print(f"missing (unit|context)  : {missing}")
    print()
    print(f"VALIDATOR: {report['validator']}")
    print(f"  passing cells: {report['passing']} / {report['cells']}")
    print()
    print("  strict pass (cells exactly as written to disk, runAt = null):")
    example = report["perCell"][0]
    for error in example["strictErrors"]:
        print(f"    - {error}")
    print()
    print(
        "  diagnostic pass (identical cells with a placeholder runAt so the "
        "date-gated\n  checks execute; the placeholder is never written to disk):"
    )
    for error, count in report["failureTally"].items():
        print(f"    - [{count}/{report['cells']}] {error}")
    print()
    print(f"  full detail: {(OUT_DIR / '_validation.json').relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
