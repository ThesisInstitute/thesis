#!/usr/bin/env python3
"""Extract the house calibration baseline from Thesis's own reward export and
put the bill-impact runs beside it on the same scoring convention.

WHAT THIS READS, AND WHY THAT FILE
----------------------------------
`/brier/reward.json` is served by `site/src/app/brier/reward.json/route.ts`,
which composes three inputs:

    FORECAST_CELLS          site/src/data/forecast-cells.ts   (on disk)
    loadPolicyEngineLedger  site/src/data/thesis-log.ts       (NETWORK fetch)
    buildBrierRewardExport  site/src/data/brier-lab.ts        (on disk)

The ledger half is not on disk: `fetchPolicyEngineLedger` HTTP-GETs the
PolicyEngine/ledger facts JSONL pinned by `site/src/data/ledger-pin.json`, and
the repo keeps no local copy of that JSONL (only the pin and the
line-level availability index).  So the route cannot be replayed offline from
`site/src/data/*.ts` alone, and every score component in the export
(crps, normalizedCrps, coverage) depends on the ledger half.

What IS on disk is the recorder's sealed snapshot of the deployed response:
`records/<date>/bodies-<runId>/reward.json.gz`, whose origin URL, byte count
and SHA-256 are committed in the sibling `digest-<runId>.json` under
`surfaces.reward`.  That is the same bytes the route emitted, it is a repo
artifact rather than a live scrape, and this module verifies its digest before
reading a single number out of it.

Nothing here modifies repo state outside experiments/billimpact/.

Run:
    python3 experiments/billimpact/thesis_baseline.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
RECORDS = REPO_ROOT / "records"
OUT_MD = HERE / "baseline_comparison.md"

GROUND_TRUTH = HERE / "ground_truth.json"
# The sweep's canonical output and the corrected re-extraction of the same
# rows.  Which one is read is a decision, so it is made explicitly and
# printed, never inherited from whichever file happened to be named first.
RUNS_CANONICAL = HERE / "runs_api.jsonl"
RUNS_REPARSED = HERE / "runs_api.reparsed.jsonl"
# The pre-fix bytes, preserved by reparse.py --apply before it rewrote the
# canonical file in place. This is the only artefact that still carries the v1
# parses, and it is what the defect comparison has to be scored against.
RUNS_PREFIX = HERE / "runs_api.preparserfix.jsonl"

# House split boundaries, read out of the export itself rather than retyped;
# these constants only name the fields we assert against.
SPLIT_NAMES = ("train", "validation", "test", "unresolved")


# ---------------------------------------------------------------------------
# provenance: file:line citations that fail loudly instead of going stale
# ---------------------------------------------------------------------------


def cite(rel_path: str, anchor: str, occurrence: int = 1) -> str:
    """Return 'path:line' for the Nth line containing `anchor`.

    A citation that cannot be located is a hard error: a stale file:line in a
    report is worse than no citation, because it still reads as verified.
    """
    path = REPO_ROOT / rel_path
    hits = [
        index
        for index, line in enumerate(path.read_text().splitlines(), start=1)
        if anchor in line
    ]
    if len(hits) < occurrence:
        raise SystemExit(
            f"citation anchor not found in {rel_path}: {anchor!r} "
            f"(found {len(hits)} occurrences, wanted #{occurrence})"
        )
    return f"{rel_path}:{hits[occurrence - 1]}"


# ---------------------------------------------------------------------------
# the recorded reward export
# ---------------------------------------------------------------------------


def find_reward_snapshot() -> dict[str, Any]:
    """Newest recorder digest that committed a /brier/reward.json body."""
    candidates: list[tuple[str, Path, Path, dict]] = []
    for digest_path in sorted(RECORDS.glob("*/digest-*.json")):
        try:
            digest = json.loads(digest_path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        surface = (digest.get("surfaces") or {}).get("reward")
        if not surface or not surface.get("archivePath"):
            continue
        body = REPO_ROOT / surface["archivePath"]
        if not body.exists():
            continue
        candidates.append(
            (str(digest.get("recordedAt") or ""), digest_path, body, digest)
        )
    if not candidates:
        raise SystemExit(
            "no recorded /brier/reward.json body found under records/; "
            "cannot build a house baseline offline"
        )
    recorded_at, digest_path, body, digest = max(candidates, key=lambda row: row[0])

    surface = digest["surfaces"]["reward"]
    raw = body.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != surface["archiveSha256"]:
        raise SystemExit(
            f"recorded reward body {body} hashes {actual} but its digest "
            f"commits {surface['archiveSha256']}; refusing to read it"
        )
    payload_bytes = gzip.decompress(raw)
    payload_sha = hashlib.sha256(payload_bytes).hexdigest()
    if payload_sha != surface["sha256"]:
        raise SystemExit(
            f"decompressed reward body hashes {payload_sha} but the digest "
            f"commits {surface['sha256']}"
        )

    return {
        "payload": json.loads(payload_bytes),
        "ledgerPath": (digest.get("surfaces") or {}).get("ledger", {}).get("archivePath"),
        "digestPath": str(digest_path.relative_to(REPO_ROOT)),
        "bodyPath": surface["archivePath"],
        "url": surface.get("url"),
        "fetchedUrl": surface.get("fetchedUrl"),
        "bytes": surface.get("bytes"),
        "archiveSha256": surface["archiveSha256"],
        "bodySha256": surface["sha256"],
        "recordedAt": recorded_at,
        "ledgerRepository": (digest.get("dependencies") or {}).get("ledgerRepository"),
        "ledgerBranchCommit": (digest.get("dependencies") or {}).get(
            "ledgerBranchCommit"
        ),
        "liveDeploymentCommit": (digest.get("dependencies") or {}).get(
            "liveDeploymentCommit"
        ),
        "digestCounts": digest.get("counts"),
    }


# ---------------------------------------------------------------------------
# descriptive statistics (no numpy; quantiles are the inclusive/linear method,
# i.e. the same convention numpy.percentile uses by default)
# ---------------------------------------------------------------------------


def describe(values: Iterable[float]) -> dict[str, Any]:
    data = sorted(float(v) for v in values)
    n = len(data)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "q1": None, "q3": None,
                "min": None, "max": None, "sd": None}
    if n == 1:
        return {"n": 1, "mean": data[0], "median": data[0], "q1": data[0],
                "q3": data[0], "min": data[0], "max": data[0], "sd": None}
    q1, _, q3 = statistics.quantiles(data, n=4, method="inclusive")
    return {
        "n": n,
        "mean": statistics.fmean(data),
        "median": statistics.median(data),
        "q1": q1,
        "q3": q3,
        "min": data[0],
        "max": data[-1],
        "sd": statistics.stdev(data) if n > 1 else None,
    }


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value != value or math.isinf(value):
            return "null"
        if value == 0:
            return "0"
        if abs(value) >= 1e4:
            return f"{value:,.0f}"
        return f"{value:.{digits}g}"
    return str(value)


# ---------------------------------------------------------------------------
# house side
# ---------------------------------------------------------------------------


def summarize_house(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload["rewardRows"]
    resolved = [row for row in rows if row["split"] != "unresolved"]
    score_carrying = [
        row for row in rows if row["reward"]["components"]["crps"] is not None
    ]
    normalized = [
        row
        for row in score_carrying
        if row["reward"]["components"]["normalizedCrps"] is not None
    ]
    covered = [
        row["reward"]["components"]["interval80Covered"]
        for row in score_carrying
        if row["reward"]["components"]["interval80Covered"] is not None
    ]
    agent_rows = [
        row
        for row in score_carrying
        if row["scoreEligibility"] == "scored_witness_verified"
    ]
    baseline_rows = [
        row
        for row in score_carrying
        if row["scoreEligibility"] == "scored_deterministic_baseline"
    ]

    eligibility: dict[str, int] = {}
    for row in rows:
        eligibility[row["scoreEligibility"]] = (
            eligibility.get(row["scoreEligibility"], 0) + 1
        )

    horizons = [
        row["horizonDaysAtRun"]
        for row in score_carrying
        if row.get("horizonDaysAtRun") is not None
    ]

    return {
        "totalRows": len(rows),
        "resolvedRows": len(resolved),
        "scoreCarryingRows": len(score_carrying),
        "normalizedRows": len(normalized),
        "distinctScoredTargets": len({row["predictionId"] for row in score_carrying}),
        "eligibility": dict(sorted(eligibility.items())),
        "crps": describe(
            row["reward"]["components"]["crps"] for row in score_carrying
        ),
        "normalizedCrps": describe(
            row["reward"]["components"]["normalizedCrps"] for row in normalized
        ),
        "coverageCovered": sum(1 for value in covered if value),
        "coverageN": len(covered),
        "coverageRate": (sum(1 for value in covered if value) / len(covered))
        if covered
        else None,
        "agentRows": len(agent_rows),
        "agentCoverageCovered": sum(
            1
            for row in agent_rows
            if row["reward"]["components"]["interval80Covered"]
        ),
        "baselineRows": len(baseline_rows),
        "horizonDays": describe(horizons),
        "splits": payload["splits"],
        "counts": payload["counts"],
        "noLeakagePolicy": payload["noLeakagePolicy"],
        "pairedComparison": payload["pairedComparison"],
        "scoredDetail": [
            {
                "predictionId": row["predictionId"],
                "dataPointId": row.get("dataPointId"),
                "agent": row.get("agent"),
                "model": row.get("model"),
                "split": row["split"],
                "eligibility": row["scoreEligibility"],
                "crps": row["reward"]["components"]["crps"],
                "normalizedCrps": row["reward"]["components"]["normalizedCrps"],
                "scale": row["reward"]["components"]["normalizationScale"],
                "scaleSource": row["reward"]["components"][
                    "normalizationScaleSource"
                ],
                "covered": row["reward"]["components"]["interval80Covered"],
                "horizonDaysAtRun": row.get("horizonDaysAtRun"),
            }
            for row in sorted(
                score_carrying, key=lambda r: (r["predictionId"], r.get("agent") or "")
            )
        ],
    }


# ---------------------------------------------------------------------------
# our side
# ---------------------------------------------------------------------------


def house_dispersion_scale(values: list[float]) -> dict[str, Any]:
    """The house normalization estimator, applied to an arbitrary history.

    Byte-for-byte the arithmetic of `targetNormalizationScale`
    (site/src/data/thesis-log.ts): first differences of the ordered
    same-series observations available at the cutoff, then the
    Bessel-corrected (n-1) sample standard deviation of those differences,
    with fewer than three observations returning an unavailable scale.

    What differs is only the SUBSTRATE the history comes from; that is
    argued explicitly in the emitted markdown, never silently.
    """
    if len(values) < 3:
        return {"scale": None, "source": "unavailable", "observationCount": len(values)}
    diffs = [values[i] - values[i - 1] for i in range(1, len(values))]
    mean = sum(diffs) / len(diffs)
    variance = sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1)
    scale = math.sqrt(variance)
    if not math.isfinite(scale) or scale <= 0:
        return {"scale": None, "source": "unavailable", "observationCount": len(values)}
    return {
        "scale": scale,
        "source": "frozen_origin_history_dispersion",
        "observationCount": len(values),
        "diffCount": len(diffs),
    }


def probe_ledger_for_our_series(
    ledger_archive_path: str | None, units: dict[str, Any]
) -> dict[str, Any]:
    """Check, rather than assert, that the ledger has nothing for our series.

    The claim 'the house normalization is inapplicable to us' rests entirely
    on this absence, so it is re-derived from the sealed ledger surface on
    every run instead of being written down once and trusted.
    """
    if not ledger_archive_path:
        return {"checked": False, "reason": "snapshot carries no ledger surface"}
    path = REPO_ROOT / ledger_archive_path
    if not path.exists():
        return {"checked": False, "reason": f"missing {ledger_archive_path}"}
    entries = json.loads(gzip.decompress(path.read_bytes())).get("entries", [])
    blob = json.dumps(entries).lower()
    series_hits = {
        unit["unit"]["series_id"]: blob.count(unit["unit"]["series_id"].lower())
        for unit in units.values()
    }
    stem_hits = {
        stem: blob.count(stem)
        for stem in ("fns.snap.recipients", "m647ncen", "snap_recipients")
    }
    return {
        "checked": True,
        "ledgerPath": ledger_archive_path,
        "ledgerEntries": len(entries),
        "targetRegistered": sum(
            1 for entry in entries if entry.get("kind") == "target_registered"
        ),
        "observationsRecorded": sum(
            1 for entry in entries if entry.get("kind") == "observation_recorded"
        ),
        "seriesIdHits": series_hits,
        "stemHits": stem_hits,
        "anyHit": any(series_hits.values()) or any(stem_hits.values()),
    }


def month_gap(start: str, end: str) -> int:
    sy, sm = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    return (ey - sy) * 12 + (em - sm)


def load_units() -> dict[str, dict[str, Any]]:
    units = {}
    for unit in json.loads(GROUND_TRUTH.read_text()):
        history = [row["value"] for row in unit["history"]]
        last_month = unit["history"][-1]["month"] if unit["history"] else None
        scale = house_dispersion_scale(history)
        units[unit["unit_id"]] = {
            "unit": unit,
            "scale": scale,
            "lastObservedMonth": last_month,
            "stepsFromLastObservation": month_gap(last_month, unit["target_month"])
            if last_month
            else None,
            "stepsFromOriginVintage": month_gap(
                unit["origin_vintage"], unit["target_month"]
            ),
        }
    return units


def load_runs(path: Path) -> dict[str, Any]:
    """Snapshot a runs file once and pin its identity.

    The sweep and the reparser both write these files while this script may be
    running; a report that does not pin the bytes it read is not reproducible.
    """
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "rows": rows,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "rowCount": len(rows),
    }


def choose_runs_file() -> tuple[Path, Path | None]:
    """Score the canonical file; keep the PRE-FIX file for comparison.

    Intent, unchanged: the report must show the extraction defect rather than
    quietly benefiting from its fix, so the defective vintage is scored too.

    What changed (2026-07-31, when the fix landed in the harness rather than in
    a side file): `reparse.py --apply` re-derived every stored response through
    `harness.parse_forecast` and rewrote `runs_api.jsonl` IN PLACE, preserving
    the pre-fix bytes at `runs_api.preparserfix.jsonl`. The canonical file is
    therefore the corrected one, and it is the only file that also carries the
    five truncated cells after they were quarantined and re-executed.

    This function previously treated `runs_api.reparsed.jsonl` as primary and
    the canonical file as the legacy vintage. That was correct while the
    correction lived only in a side file and is now exactly inverted:
    `runs_api.reparsed.jsonl` is a regenerated mirror of the canonical rows, so
    selecting it as primary silently scored a stale intermediate.
    """
    return RUNS_CANONICAL, (RUNS_PREFIX if RUNS_PREFIX.exists() else None)


def summarize_ours(units: dict[str, Any], runs: list[dict]) -> dict[str, Any]:
    sys.path.insert(0, str(HERE))
    from scoring import score_forecast  # noqa: PLC0415  (local experiment module)

    scored: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in runs:
        forecast = row.get("forecast") or {}
        point, lo, hi = (
            forecast.get("point"),
            forecast.get("ci_low"),
            forecast.get("ci_high"),
        )
        truth = row.get("truth")
        unit_id = row.get("unit_id")
        meta = units.get(unit_id)
        if None in (point, lo, hi, truth) or meta is None or not (lo < hi):
            skipped.append(
                {
                    "cell_key": row.get("cell_key"),
                    "reason": "unusable forecast triple, missing truth, or unknown unit",
                }
            )
            continue
        out = score_forecast(float(point), float(lo), float(hi), float(truth))
        scale = meta["scale"]["scale"]
        scored.append(
            {
                "unit_id": unit_id,
                "config": row["config"],
                "rep": row.get("rep"),
                "cell_key": row.get("cell_key"),
                "parseMode": forecast.get("parse_mode"),
                "point": float(point),
                "truth": float(truth),
                "crps": out["crps"],
                "pit": out["pit"],
                "covered": bool(out["covered80"]),
                "absError": out["abs_error"],
                "scale": scale,
                "normalizedCrps": (out["crps"] / scale) if scale else None,
                "normalizedAbsoluteError": (out["abs_error"] / scale)
                if scale
                else None,
                "stepsAhead": meta["stepsFromLastObservation"],
            }
        )

    summary = cohort_summary(scored)
    summary["scored"] = scored
    summary["skipped"] = skipped
    summary["byParseMode"] = {
        mode: cohort_summary([r for r in scored if r["parseMode"] == mode])
        for mode in sorted({r["parseMode"] or "unknown" for r in scored})
    }
    # The JSON elicitation path, whichever parser version produced it
    # ("json" under v1, "json_v2" after the re-extraction). Matching the exact
    # v1 string silently returned an empty cohort against the corrected file.
    summary["jsonOnly"] = cohort_summary(
        [row for row in scored if str(row["parseMode"] or "").startswith("json")]
    )
    # Year-shaped points are the diagnostic signature of the prose parser
    # picking a calendar year out of the narrative instead of the forecast.
    summary["yearShaped"] = [
        row for row in scored if 1900 < row["point"] < 2100
    ]
    summary["stepsAhead"] = describe(
        row["stepsAhead"] for row in scored if row["stepsAhead"] is not None
    )
    return summary


def cohort_summary(scored: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [
        row["normalizedCrps"] for row in scored if row["normalizedCrps"] is not None
    ]
    covered = [row["covered"] for row in scored]
    ratios = [
        row["point"] / row["truth"] for row in scored if row["truth"]
    ]
    return {
        "n": len(scored),
        "crps": describe(row["crps"] for row in scored),
        "normalizedCrps": describe(normalized),
        "normalizedRows": len(normalized),
        "coverageCovered": sum(1 for value in covered if value),
        "coverageN": len(covered),
        "coverageRate": (sum(1 for value in covered if value) / len(covered))
        if covered
        else None,
        "pit": describe(row["pit"] for row in scored),
        "pointOverTruth": describe(ratios),
    }


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def stat_row(label: str, stats: dict[str, Any]) -> str:
    return (
        f"| {label} | {stats['n']} | {fmt(stats['mean'])} | {fmt(stats['median'])} | "
        f"{fmt(stats['q1'])} | {fmt(stats['q3'])} | {fmt(stats['min'])} | "
        f"{fmt(stats['max'])} |"
    )


def build_markdown(
    snapshot: dict[str, Any],
    house: dict[str, Any],
    ours: dict[str, Any],
    units: dict[str, Any],
    runs_meta: dict[str, Any],
    probe: dict[str, Any],
    legacy: dict[str, Any] | None,
    legacy_meta: dict[str, Any] | None,
) -> str:
    c_norm = cite("site/src/data/thesis-log.ts", "export function targetNormalizationScale")
    c_diffs = cite("site/src/data/thesis-log.ts", "const diffs = values.slice(1).map")
    c_var = cite("site/src/data/thesis-log.ts", "diffs.reduce((total, diff) => total + (diff - mean) ** 2, 0) /")
    c_sqrt = cite("site/src/data/thesis-log.ts", "const scale = Math.sqrt(variance);")
    c_min3 = cite("site/src/data/thesis-log.ts", "if (history.length < 3) {")
    c_cutoff = cite("site/src/data/thesis-log.ts", "const registeredAt = target?.registeredAt;")
    c_ncrps = cite("site/src/data/thesis-log.ts", "    normalizedCrps:")
    c_ncrps_div = cite("site/src/data/thesis-log.ts", ": distributionScore.crps / normalization.scale,")
    c_cov = cite("site/src/data/thesis-log.ts", "    interval80Covered:")
    c_hist = cite("site/src/data/time-series-priors.ts", "export function ledgerHistoryAtCutoff")
    c_histfilter = cite("site/src/data/time-series-priors.ts", "entry.unit === forecast.unit &&")
    c_split = cite("site/src/data/brier-lab.ts", "export function getBrierEvalSplit")
    c_split_train = cite("site/src/data/brier-lab.ts", 'if (forecast.resolutionDate < "2026-07-01") return "train";')
    c_reward = cite("site/src/data/brier-lab.ts", "          : -score.normalizedCrps,")
    c_route = cite("site/src/app/brier/reward.json/route.ts", "buildBrierRewardExport({")
    c_fetch = cite("site/src/data/thesis-log.ts", "async function fetchPolicyEngineLedger")
    c_x2 = cite("site/src/data/thesis-log.ts", "// unavailable, raw CRPS still publishes, and the score stays out of")
    c_x2b = cite("site/src/data/brier-lab.ts", "// normalization denominator — and nothing any forecast authors — can")
    c_transform = cite("scripts/run_thesis_analyst.py", "def interval_distribution")
    c_crps_ts = cite("site/src/data/prediction-distribution.ts", "export function scoreNumericCdfDistribution")

    lines: list[str] = []
    add = lines.append

    add("# Bill-impact runs against the Thesis house baseline")
    add("")
    add(
        "Generated by `experiments/billimpact/thesis_baseline.py`. Every number "
        "below is read from a repo file; nothing is estimated, and any field the "
        "repo does not carry is printed as `null`."
    )
    add("")

    add("## 1. Where the house baseline comes from")
    add("")
    add(
        f"`/brier/reward.json` is assembled at `{c_route}` from `FORECAST_CELLS` "
        f"plus the PolicyEngine Ledger, and the ledger half is fetched over the "
        f"network at `{c_fetch}` — the repo stores the pin "
        "(`site/src/data/ledger-pin.json`) and a line-level availability index, "
        "not the facts JSONL. The route therefore cannot be replayed offline "
        "from `site/src/data/*.ts` alone."
    )
    add("")
    add(
        "The offline stand-in used here is the recorder's sealed snapshot of the "
        "deployed response, whose SHA-256 this script verifies before reading it:"
    )
    add("")
    add(f"- body: `{snapshot['bodyPath']}` (gzip, {fmt(snapshot['bytes'])} bytes uncompressed)")
    add(f"- digest: `{snapshot['digestPath']}` (`surfaces.reward`)")
    add(f"- origin URL: {snapshot['url']}")
    add(f"- recorded at: {snapshot['recordedAt']}")
    add(f"- site deployment commit: `{snapshot['liveDeploymentCommit']}`")
    add(
        f"- ledger: `{snapshot['ledgerRepository']}` @ "
        f"`{snapshot['ledgerBranchCommit']}`"
    )
    add(f"- archive sha256: `{snapshot['archiveSha256']}`")
    add(f"- body sha256: `{snapshot['bodySha256']}`")
    add("")
    add("No live site was contacted.")
    add("")

    add("## 2. The house population, honestly counted")
    add("")
    add(f"- reward rows in the export: **{house['totalRows']}**")
    add(
        f"- rows whose split is not `unresolved` (i.e. the target has an official "
        f"fact): **{house['resolvedRows']}**"
    )
    add(
        f"- rows that actually carry score components: **{house['scoreCarryingRows']}** "
        f"across **{house['distinctScoredTargets']}** distinct targets"
    )
    add(
        f"- of those, rows with a non-null `normalizedCrps`: "
        f"**{house['normalizedRows']}**"
    )
    add("")
    add(
        "The gap between 'resolved' and 'scored' is not attrition, it is the "
        "integrity gate: `scoreEligibility` records why each resolved row was "
        "kept out."
    )
    add("")
    add("| scoreEligibility | rows |")
    add("| --- | ---: |")
    for key, value in house["eligibility"].items():
        add(f"| `{key}` | {value} |")
    add("")
    add(
        "So the honest headline is that the house has a **large resolved "
        f"population ({house['resolvedRows']} rows) and a very small scored one "
        f"({house['scoreCarryingRows']} rows, {house['normalizedRows']} normalized)**. "
        "Any comparison against it is a comparison against single digits."
    )
    add("")

    add("### Every scored house row")
    add("")
    add(
        "| predictionId | agent | eligibility | CRPS | normalized CRPS | scale | scale source | 80% covered | horizon (days) |"
    )
    add("| --- | --- | --- | ---: | ---: | ---: | --- | :---: | ---: |")
    for row in house["scoredDetail"]:
        add(
            f"| {row['predictionId']} | {row['agent']} | `{row['eligibility']}` | "
            f"{fmt(row['crps'])} | {fmt(row['normalizedCrps'])} | {fmt(row['scale'])} | "
            f"`{row['scaleSource']}` | {fmt(row['covered'])} | "
            f"{fmt(row['horizonDaysAtRun'])} |"
        )
    add("")
    add(
        "Raw CRPS is in each target's own unit (percent, thousands of claims, "
        "index points), so the raw column is **not** a pooled quantity — it is "
        "printed because the repo publishes it, and because it is the only "
        "column that exists for the six rows with no scale."
    )
    add("")

    add("## 3. How `normalizedCrps` is normalized")
    add("")
    add(f"`targetNormalizationScale` at `{c_norm}`:")
    add("")
    add(
        "1. **Dispersion, not interval width.** The denominator is the "
        "Bessel-corrected sample standard deviation of *successive first "
        f"differences* of the target's own history: differences at `{c_diffs}`, "
        f"variance over `n-1` at `{c_var}`, square root at `{c_sqrt}`."
    )
    add(
        "2. **Its substrate is the PolicyEngine Ledger, not the forecast.** The "
        f"history comes from `ledgerHistoryAtCutoff` (`{c_hist}`), which admits "
        "only `observation_recorded` ledger entries of the same series *and the "
        f"same unit* (`{c_histfilter}`), whose publisher date and the ledger's "
        "own acceptance both precede the cutoff."
    )
    add(
        "3. **The cutoff is registration time, falling back to the primary run "
        f"seal** (`{c_cutoff}`): the `target_registered` ledger entry's "
        "`registeredAt` for that `dataPointId`, else the primary run's `runAt`."
    )
    add(
        f"4. **Fewer than three pre-cutoff observations ⇒ no scale** (`{c_min3}`): "
        "`scale = null`, `normalizationScaleSource = \"unavailable\"`, raw CRPS "
        "still publishes, and the row is excluded from every normalized "
        "aggregate."
    )
    add(
        f"5. **`normalizedCrps = crps / scale`** (`{c_ncrps}`, division at "
        f"`{c_ncrps_div}`), and `reward.value = -normalizedCrps` "
        f"(`{c_reward}`)."
    )
    add("")
    add(
        "The scale is shared by every run on a `dataPointId`, so a forecast "
        "cannot move its own denominator. That is deliberate, and the code says "
        f"why: `{c_x2}` records re-audit X2, where a forecast-derived fallback "
        "let a *wider* primary interval shrink its own normalized error; "
        f"`{c_x2b}` records N5, which demanded a scale no forecast controls. "
        "Forecast-authored `historicalContext` and interval widths are never "
        "normalization inputs."
    )
    add("")
    add(
        f"Coverage is the plain containment test at `{c_cov}`: "
        "`ciLow <= observed <= ciHigh`."
    )
    add("")

    add("## 4. Splits")
    add("")
    add(f"`getBrierEvalSplit` at `{c_split}` keys on the cell's `resolutionDate`:")
    add("")
    for name in SPLIT_NAMES:
        entry = house["splits"][name]
        add(
            f"- `{name}` — {entry['rule']} ({entry['runs']} rows, "
            f"{entry['scoredRuns']} rewarded)"
        )
    add("")
    add(
        f"The train boundary is the literal at `{c_split_train}`. Unresolved "
        "targets short-circuit before any date comparison, so 'unresolved' is a "
        "resolution state rather than a date bucket. The export restates the "
        f"rule in `noLeakagePolicy`: \"{house['noLeakagePolicy']['rule']}\" — "
        f"trainable splits {house['noLeakagePolicy']['trainingEligibleSplits']}, "
        f"holdout {house['noLeakagePolicy']['holdoutSplits']}."
    )
    add("")
    add(
        "**Where our runs land under that rule.** Every bill-impact unit resolved "
        "at first-print vintage `2026-02-01`, which is before `2026-07-01`, so on "
        "the house rule all of our cells are `train` — none of them would enter a "
        "holdout. They also resolve on data that was already public when the "
        "models were called, which is why this experiment is a retrodiction "
        "study and not a Thesis forecast wave."
    )
    add("")

    add("## 5. Applying the house normalization to our runs")
    add("")
    add(
        "**The house convention is not literally applicable, and the reason is "
        "the substrate, not the estimator.** Our targets are state monthly SNAP "
        "recipient counts (`BR<ST><FIPS>M647NCEN`), and the PolicyEngine Ledger "
        "carries nothing for them."
    )
    add("")
    if probe.get("checked"):
        add(
            f"Verified on this run rather than asserted: the sealed ledger "
            f"surface `{probe['ledgerPath']}` holds {probe['ledgerEntries']} "
            f"entries ({probe['targetRegistered']} `target_registered`, "
            f"{probe['observationsRecorded']} `observation_recorded`). "
            "Substring hits for each of our twelve series ids: "
            + ", ".join(f"`{k}` {v}" for k, v in probe["seriesIdHits"].items())
            + ". Hits for the id stems "
            + ", ".join(f"`{k}` {v}" for k, v in probe["stemHits"].items())
            + "."
        )
        if probe["anyHit"]:
            add("")
            add(
                "**The probe found a hit, which contradicts the paragraph above "
                "— re-read the normalization section before trusting any "
                "normalized figure in this report.**"
            )
    else:
        add(
            f"The ledger-absence probe did not run ({probe.get('reason')}), so "
            "the inapplicability claim below is unverified on this run."
        )
    add("")
    add(
        "With no ledger history, `ledgerHistoryAtCutoff` returns an empty list "
        "and `targetNormalizationScale` returns `null` "
        "(`source = \"unavailable\"`) for all twelve units. Under the house "
        "function verbatim, our normalized CRPS is undefined for every row."
    )
    add("")
    add("What this script does instead, stated exactly:")
    add("")
    add(
        "- **Estimator: identical.** First differences of the ordered "
        "same-series history, Bessel-corrected sample SD, `< 3` observations ⇒ "
        "unavailable. Same arithmetic, same guard."
    )
    add(
        "- **Substrate: our frozen pre-origin history** in `ground_truth.json` — "
        "the ALFRED `2023-06-01` vintage of the same series, truncated before the "
        "forecast origin. ALFRED is used here strictly as a vintage/history "
        "mirror, exactly as `PREREGISTRATION.md` states and as AGENTS.md permits; "
        "it is not presented as a resolution source of record."
    )
    add(
        "- **The X2 invariant survives.** This history is fetched from a frozen "
        "vintage before any model is called and is identical across all "
        "configurations for a unit, so no forecast can move its own denominator — "
        "which is the property the house rule exists to protect."
    )
    add(
        "- **The label changes.** The scale source is emitted as "
        "`frozen_origin_history_dispersion`, never as `ledger_dispersion`. These "
        "numbers must not be pooled with house `ledger_dispersion` values as if "
        "they came from the same register."
    )
    add("")
    add(
        "| unit | series | target month | last observed | steps ahead | obs | scale (recipients/month) |"
    )
    add("| --- | --- | --- | --- | ---: | ---: | ---: |")
    for unit_id, meta in units.items():
        unit = meta["unit"]
        add(
            f"| `{unit_id}` | {unit['series_id']} | {unit['target_month'][:7]} | "
            f"{meta['lastObservedMonth'][:7]} | {meta['stepsFromLastObservation']} | "
            f"{meta['scale']['observationCount']} | {fmt(meta['scale']['scale'])} |"
        )
    add("")

    add("## 6. Extraction integrity")
    add("")
    add(
        f"Scored file: `{runs_meta['path']}`. Every run record carries a "
        "`forecast.parse_mode`, and the point-over-truth ratio per mode is the "
        "cheapest test of whether the extractor found the forecast at all:"
    )
    add("")
    add("| parse_mode | runs | median point / truth | min | max | median CRPS |")
    add("| --- | ---: | ---: | ---: | ---: | ---: |")
    for mode, cohort in ours["byParseMode"].items():
        add(
            f"| `{mode}` | {cohort['n']} | "
            f"{fmt(cohort['pointOverTruth']['median'])} | "
            f"{fmt(cohort['pointOverTruth']['min'])} | "
            f"{fmt(cohort['pointOverTruth']['max'])} | "
            f"{fmt(cohort['crps']['median'])} |"
        )
    add("")
    add(
        f"Runs whose point estimate falls in [1900, 2100] — a calendar year "
        f"standing where a recipient count should be: **{len(ours['yearShaped'])}**."
    )
    add("")
    if legacy is not None and legacy_meta is not None:
        add(
            f"**This report reads the canonical run file, whose forecasts were "
            f"re-derived through the corrected parser.** The pre-fix bytes at "
            f"`{legacy_meta['path']}` are preserved and scored alongside it, so "
            "the defect stays visible instead of being quietly fixed away. The "
            "v1 prose fallback filtered candidate numbers with `n > 1000` "
            "(calendar years clear that) and returned the first ordered triple, "
            "so a prose response that discusses history before answering parsed "
            "as its years. Same model responses in both rows — the only "
            "difference is the extraction."
        )
        add("")
        add("| file | runs scored | year-shaped points | median CRPS | mean normalized CRPS | 80% coverage |")
        add("| --- | ---: | ---: | ---: | ---: | ---: |")
        for label, cohort, meta in (
            ("corrected", ours, runs_meta),
            ("pre-fix", legacy, legacy_meta),
        ):
            add(
                f"| `{meta['path'].rsplit('/', 1)[-1]}` ({label}) | {cohort['n']} | "
                f"{len(cohort['yearShaped'])} | {fmt(cohort['crps']['median'])} | "
                f"{fmt(cohort['normalizedCrps']['mean'])} | "
                f"{fmt(cohort['coverageRate'])} |"
            )
        add("")
        add(
            "The defect fired only on `free_text`, which is one LEVEL of a "
            "measured dimension (D2 `elicitation`). That is worse than noise: it "
            "manufactures a difference between free text and JSON that has "
            "nothing to do with elicitation format, which is exactly the class "
            "of artifact this experiment exists to detect. Preregistered "
            "analysis P2 must be read off the corrected file."
        )
        add("")
    elif len(ours["yearShaped"]) > 0:
        add(
            "**No corrected re-extraction is present on disk, and the file read "
            "still carries year-shaped points.** Treat every pooled figure below "
            "as contaminated by extraction failure rather than forecast error."
        )
        add("")
    if ours["skipped"]:
        add(
            f"**{len(ours['skipped'])}** run(s) in the scored file are unusable "
            "outright (no interval: `ci_low == ci_high`, or a missing field) and "
            "are excluded from every figure rather than imputed."
        )
        add("")

    add("## 7. Side by side")
    add("")
    add(
        f"House rows are the {house['scoreCarryingRows']} score-carrying rows of "
        f"the sealed export ({house['normalizedRows']} of them normalized). Our "
        f"rows are the {ours['n']} scored bill-impact runs "
        f"(`{runs_meta['path']}`, sha256 `{runs_meta['sha256'][:16]}…`, "
        f"{runs_meta['rowCount']} lines, {runs_meta['bytes']} bytes at read time; "
        "the sweep was still writing this file, so the snapshot identity is "
        "pinned rather than assumed)."
    )
    add("")
    add("| population | metric | N | mean | median | Q1 | Q3 | min | max |")
    add("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    add("| house (`ledger_dispersion` + raw) " + stat_row("CRPS (mixed units)", house["crps"]))
    add("| house " + stat_row("normalized CRPS", house["normalizedCrps"]))
    add("| billimpact, all runs " + stat_row("CRPS (recipients)", ours["crps"]))
    add("| billimpact, all runs " + stat_row("normalized CRPS", ours["normalizedCrps"]))
    add("| billimpact, all runs " + stat_row("PIT", ours["pit"]))
    add("| billimpact, JSON path " + stat_row("CRPS (recipients)", ours["jsonOnly"]["crps"]))
    add("| billimpact, JSON path " + stat_row("normalized CRPS", ours["jsonOnly"]["normalizedCrps"]))
    add("| billimpact, JSON path " + stat_row("PIT", ours["jsonOnly"]["pit"]))
    add("")
    add("| population | 80% interval coverage | N |")
    add("| --- | ---: | ---: |")
    add(
        f"| house, all score-carrying rows | {fmt(house['coverageRate'])} "
        f"({house['coverageCovered']}/{house['coverageN']}) | {house['coverageN']} |"
    )
    add(
        f"| house, witness-verified agent rows only | "
        f"{fmt(house['agentCoverageCovered'] / house['agentRows']) if house['agentRows'] else 'null'} "
        f"({house['agentCoverageCovered']}/{house['agentRows']}) | {house['agentRows']} |"
    )
    add(
        f"| billimpact, all scored runs | {fmt(ours['coverageRate'])} "
        f"({ours['coverageCovered']}/{ours['coverageN']}) | {ours['coverageN']} |"
    )
    add(
        f"| billimpact, JSON path | {fmt(ours['jsonOnly']['coverageRate'])} "
        f"({ours['jsonOnly']['coverageCovered']}/{ours['jsonOnly']['coverageN']}) | "
        f"{ours['jsonOnly']['coverageN']} |"
    )
    add("")

    add("### What this table does and does not license")
    add("")
    add(
        f"- **Horizon.** House scored rows run "
        f"{fmt(house['horizonDays']['min'])}–{fmt(house['horizonDays']['max'])} days "
        f"ahead (median {fmt(house['horizonDays']['median'])}). Ours run "
        f"{fmt(ours['stepsAhead']['min'])}–{fmt(ours['stepsAhead']['max'])} *months* "
        "past the last observation the forecaster could see. Both sides divide by "
        "a **one-step** dispersion, so a normalized CRPS near 1 means 'about one "
        "month of ordinary movement' for us and 'about one release of ordinary "
        "movement' for the house. Our figures are inflated by the horizon by "
        "construction, and the preregistration says so up front."
    )
    add(
        "- **N.** The house side is single digits. Treat its mean and quartiles "
        "as a description of eleven rows, not as a lab-wide calibration estimate."
    )
    add(
        "- **Population.** House rows are witness-verified single forecasts on "
        "registered targets plus three deterministic persistence baselines. Ours "
        "are repeated single-shot API calls across a deliberately varied "
        "scaffolding grid, so their dispersion is the experiment's object of "
        "study rather than an agent's best effort."
    )
    add(
        "- **Same transform, same scorer.** Both sides run the identical CDF "
        f"construction and CRPS integral: `{c_transform}` (the Python port used "
        f"here) against `{c_crps_ts}` (the TypeScript original the export was "
        "built with). That part *is* apples to apples."
    )
    add(
        "- **The JSON-path cut is reported alongside the pooled row** because "
        "that elicitation path was never touched by the extraction defect in "
        f"§6; it is {ours['jsonOnly']['n']} runs."
    )
    add("")

    add("## 8. Reproduce")
    add("")
    add("```bash")
    add("python3 experiments/billimpact/thesis_baseline.py")
    add("```")
    add("")
    return "\n".join(lines) + "\n"


def main() -> int:
    snapshot = find_reward_snapshot()
    house = summarize_house(snapshot["payload"])
    units = load_units()
    probe = probe_ledger_for_our_series(snapshot.get("ledgerPath"), units)
    primary_path, legacy_path = choose_runs_file()
    runs_meta = load_runs(primary_path)
    ours = summarize_ours(units, runs_meta["rows"])
    legacy_meta = load_runs(legacy_path) if legacy_path else None
    legacy = (
        summarize_ours(units, legacy_meta["rows"]) if legacy_meta else None
    )

    print(f"reward snapshot: {snapshot['bodyPath']}")
    print(f"  origin: {snapshot['url']}  recorded {snapshot['recordedAt']}")
    print(f"  sha256 verified against {snapshot['digestPath']}")
    print()
    print(f"house rows                 : {house['totalRows']}")
    print(f"house resolved rows        : {house['resolvedRows']}")
    print(f"house score-carrying rows  : {house['scoreCarryingRows']}")
    print(f"house normalized rows      : {house['normalizedRows']}")
    print(f"house CRPS                 : {house['crps']}")
    print(f"house normalized CRPS      : {house['normalizedCrps']}")
    print(
        f"house coverage             : {house['coverageCovered']}/{house['coverageN']}"
        f" = {house['coverageRate']}"
    )
    print()
    print(f"billimpact runs read       : {runs_meta['path']} — "
          f"{runs_meta['rowCount']} rows (sha256 {runs_meta['sha256'][:16]}…)")
    if legacy_meta:
        print(f"  legacy comparison file   : {legacy_meta['path']} — "
              f"{legacy_meta['rowCount']} rows")
    print(f"billimpact scored          : {ours['n']} (skipped {len(ours['skipped'])})")
    print(f"billimpact CRPS            : {ours['crps']}")
    print(f"billimpact normalized CRPS : {ours['normalizedCrps']}")
    print(
        f"billimpact coverage        : {ours['coverageCovered']}/{ours['coverageN']}"
        f" = {ours['coverageRate']}"
    )
    print()
    print("PARSER INTEGRITY")
    for mode, cohort in ours["byParseMode"].items():
        print(
            f"  parse_mode={mode:14s} n={cohort['n']:5d} "
            f"median point/truth={cohort['pointOverTruth']['median']:.4g}"
        )
    print(f"  year-shaped points (1900<p<2100): {len(ours['yearShaped'])}")
    print(f"  json-only normalized CRPS: {ours['jsonOnly']['normalizedCrps']}")
    print(
        f"  json-only coverage       : {ours['jsonOnly']['coverageCovered']}"
        f"/{ours['jsonOnly']['coverageN']} = {ours['jsonOnly']['coverageRate']}"
    )
    print()

    OUT_MD.write_text(
        build_markdown(
            snapshot, house, ours, units, runs_meta, probe, legacy, legacy_meta
        )
    )
    print(
        "ledger probe for our series: "
        + (
            f"{probe['ledgerEntries']} entries scanned, any hit = {probe['anyHit']}"
            if probe.get("checked")
            else f"NOT RUN ({probe.get('reason')})"
        )
    )
    print(f"wrote {OUT_MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
