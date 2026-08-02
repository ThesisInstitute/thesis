#!/usr/bin/env python3
"""Convert spawned-forecast JSON (from thesis.analyst agent runs) into a
ForecastCell TS module, validating the trace-depth contract on the way in.

Usage:
  python3 scripts/spawned_cells_to_ts.py OUT_TS CONST_NAME IN1.json [IN2.json ...]
"""

import argparse
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
CUSTODY_ENFORCEMENT_DATE = "2026-07-10"

ALLOWED_UNITS = {
    "count",
    "percent",
    "gbp_billions",
    "usd",
    "usd_billions",
    "usd_monthly",
    "thousands",
    "millions",
    "per_1000_live_births",
    "ratio",
    "minutes",
    "percent_growth",
    "index_points",
}
ALLOWED_COUNTRIES = {"US", "UK", "CA", "AU", "EA", "JP", "BE"}
ALLOWED_TYPES = {"data", "policy", "conditional"}
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REQUIRED = [
    "slug",
    "country",
    "type",
    "title",
    "question",
    "unit",
    "pointEstimate",
    "ciLow",
    "ciHigh",
    "confidence",
    "resolutionDate",
    "resolutionSource",
    "resolutionSourceUrl",
    "resolutionRule",
    "dataPointId",
    "historicalContext",
    "drivers",
    "sourceContext",
    "runAt",
    "reasoning",
]
PRIVATE_SOURCE_RE = re.compile(
    r"(?i)(granola|\btranscripts?\b|meeting notes?|meeting with max|"
    r"pasted-text|\.codex/attachments|codex attachments|private meeting|"
    r"call notes?|email thread|chat transcript)"
)


def private_source_hits(cell: dict) -> list[str]:
    hits = []
    fields = {
        "sourceContext": cell.get("sourceContext"),
        "drivers": cell.get("drivers"),
        "reasoning": cell.get("reasoning"),
        "historicalContext": cell.get("historicalContext"),
    }
    for name, value in fields.items():
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if PRIVATE_SOURCE_RE.search(text):
            hits.append(name)
    return hits


def existing_slugs(site_data: pathlib.Path, out_ts: pathlib.Path) -> set[str]:
    slugs = set()
    for f in list(site_data.glob("forecast-examples/*.ts")) + [
        site_data / "forecast-cells.ts"
    ]:
        if f.resolve() == out_ts.resolve():
            continue  # rerunning over our own previous output is not a collision
        slugs |= set(re.findall(r'slug:\s*"([^"]+)"', f.read_text()))
    return slugs


def validate(cell: dict, taken: set[str]) -> list[str]:
    errs = []
    for k in REQUIRED:
        if k not in cell:
            errs.append(f"missing {k}")
    if errs:
        return errs
    if not SLUG_RE.match(cell["slug"]):
        errs.append("bad slug format")
    if cell["slug"] in taken:
        errs.append("slug collides with existing catalog")
    if cell["unit"] not in ALLOWED_UNITS:
        errs.append(f"unit {cell['unit']!r} not allowed")
    if cell["country"] not in ALLOWED_COUNTRIES:
        errs.append(f"country {cell['country']!r} not allowed")
    if cell["type"] not in ALLOWED_TYPES:
        errs.append(f"type {cell['type']!r} not allowed")
    # Discrete-outcome cells (e.g. policy-rate decisions) may legitimately put
    # the modal point at an interval edge; the interval itself must be real.
    if not (
        cell["ciLow"] <= cell["pointEstimate"] <= cell["ciHigh"]
        and cell["ciLow"] < cell["ciHigh"]
    ):
        errs.append("CI does not bracket point estimate")
    if cell["confidence"] != 0.8:
        errs.append("confidence must be 0.8")
    for key in ("resolutionDate",):
        try:
            datetime.strptime(cell[key], "%Y-%m-%d")
        except ValueError:
            errs.append(f"{key} not YYYY-MM-DD")
    try:
        run_at = datetime.fromisoformat(cell["runAt"].replace("Z", "+00:00"))
        if run_at > datetime.now(timezone.utc):
            errs.append("runAt is in the future")
        if run_at < datetime(2026, 6, 1, tzinfo=timezone.utc):
            errs.append("runAt predates the pipeline")
    except ValueError:
        errs.append("runAt not ISO-8601")
    if not str(cell["resolutionSourceUrl"]).startswith("https://"):
        errs.append("resolutionSourceUrl not https")
    if len(cell["historicalContext"]) < 2:
        errs.append("needs >=2 historical points")
    for h in cell["historicalContext"]:
        if isinstance(h.get("value"), str):
            cleaned = h["value"].replace("%", "").replace(",", "").strip()
            try:
                h["value"] = float(cleaned)
            except ValueError:
                errs.append(f"non-numeric historical value: {h['value']!r}")
        if isinstance(h.get("value"), float) and h["value"].is_integer():
            h["value"] = int(h["value"])
    if len(cell["sourceContext"]) < 2:
        errs.append("needs >=2 source URLs")
    # Mirror of trace-depth.test.ts: sourceContext entries are public URLs,
    # never local repo paths (a sibling run's artifacts are context, not
    # citable provenance).
    for url in cell["sourceContext"]:
        if not re.match(r"^https?://", str(url)):
            errs.append(f"sourceContext entry is not an http(s) URL: {url}")
    private_hits = private_source_hits(cell)
    if private_hits:
        errs.append(
            "private-source provenance is not allowed in " + ", ".join(private_hits)
        )

    steps = cell["reasoning"]
    if len(steps) < 7:
        errs.append(f"only {len(steps)} reasoning steps (need >=7)")
    tools = [s for s in steps if s.get("kind") == "tool"]
    if len(tools) < 2:
        errs.append(f"only {len(tools)} tool steps (need >=2)")
    for t in tools:
        if not re.search(r"\d", str(t.get("result", ""))):
            errs.append(f"tool step without numeric result: {t.get('tool')}")
    if not any(s.get("kind") == "math" for s in steps):
        errs.append("no math step")
    # Interval width must be derived, not vibed: the math step has to show
    # sigma (or the 1.28 z-multiplier) so the width is auditable. Applies to
    # cells run on/after 2026-07-05, same cutoff as trace-depth.test.ts —
    # earlier cells were valid under their run date's rubric and republishing
    # a wave must not retro-reject them. Keep the regex byte-identical to
    # the test.
    # Raw spawned cells carry the sealed runAt at the TOP level; the
    # predictionRun object only exists after this converter builds it.
    # Reading only predictionRun.runAt left run_at empty for every fresh
    # cell, silently skipping the leakage and sigma gates until vitest
    # bounced the staged wave (caught live 2026-07-10, Canada June LFS
    # forecast on LFS release day).
    run_at = str(
        cell.get("runAt") or (cell.get("predictionRun") or {}).get("runAt") or ""
    )
    # A forecast of an already-published number is leakage, not a forecast:
    # the resolution date must postdate the run. Caught live 2026-07-07 (a
    # "2025 provisional infant mortality" cell whose release was 2026-05-26).
    # Mirrors trace-depth.test.ts; same cutoff.
    if run_at >= "2026-07-07" and cell["resolutionDate"] <= run_at[:10]:
        errs.append(
            f"resolutionDate {cell['resolutionDate']} is not after runAt "
            f"{run_at[:10]} — target already published (leakage)"
        )
    if run_at >= "2026-07-05":
        math_text = " ".join(
            s.get("text") or "" for s in steps if s.get("kind") == "math"
        )
        prompt_mode = str(
            cell.get("promptMode")
            or (cell.get("predictionRun") or {}).get("promptMode")
            or ""
        )
        if prompt_mode == "ladder_v2":
            # ladder_v2's pre-registered derivation contract (2026-07-10) is
            # quantile-native: the ladder rungs plus the interpolated tail
            # percentiles stated literally, no parametric sigma disclosure.
            # Keep byte-identical to trace-depth.test.ts.
            if not (
                len(re.findall(r"P\(X\s*<=", math_text)) >= 3
                and re.search(r"10th percentile", math_text, re.IGNORECASE)
                and re.search(r"90th percentile", math_text, re.IGNORECASE)
            ):
                errs.append(
                    "ladder_v2 math step must list P(X <= t) rungs and state "
                    "the interpolated 10th and 90th percentiles"
                )
        elif not re.search(r"sigma\s*[=≈:]|1\.28", math_text, re.IGNORECASE):
            errs.append(
                "math step does not show interval derivation (sigma = X or 1.28)"
            )
    # Mirror site/src/__tests__/trace-depth.test.ts exactly: CI requires an
    # explicit reference-class phrase and interval-falsification wording, and
    # cells that validated here but failed there have shipped-then-bounced.
    # Keep these three regexes byte-identical to the test.
    trace_text = " ".join(
        s.get("text") or f"{s.get('call', '')} {s.get('result', '')}" for s in steps
    ).lower()
    base_rate_re = (
        r"base rate|reference class|last \d+ (prints|releases|months|meetings|"
        r"weeks|weekly|monthly|obs)|distribution of|(trailing|past|realized) "
        r"\d+|\d+-(week|month) (range|distribution|history)|realized "
        r"(volatility|distribution)|historical (range|distribution)|"
        r"trailing-?\d+|month-to-month volatility|std_samp|modal outcome|"
        r"market-implied|implied probabilit|p_hold"
    )
    falsification_re = (
        r"outside (the|our|this) interval|outside \[|would (push|put|land|"
        r"break)|upside risk|downside risk|miss(es)? (high|low)|surprise|tail "
        r"(scenario|risk)|break (the|this) (model|forecast)|breach|lands? "
        r"(above|below)|(above|below) the (interval|band|range)|forecast "
        r"(high|low)|probability would (fall|rise)|would (fail|flip)|fails? "
        r"(only )?if|wrong if|blow past|revert (into|to)|exceed (my|the) "
        r"central|right-skewed|saturation tail"
    )
    if not re.search(base_rate_re, trace_text):
        errs.append("no explicit base-rate/reference-class phrasing (CI regex)")
    if not re.search(falsification_re, trace_text):
        errs.append(
            "no interval-falsification phrasing (CI regex — say what would "
            "land outside the 80% interval / upside risk / downside risk)"
        )
    if not steps:
        # An empty trace must FAIL validation, not crash it: the length and
        # content errors above already describe the failure.
        return errs
    last = steps[-1]
    if last.get("kind") != "forecast":
        errs.append("last step is not the forecast")
    elif (last.get("point"), last.get("ciLow"), last.get("ciHigh")) != (
        cell["pointEstimate"],
        cell["ciLow"],
        cell["ciHigh"],
    ):
        errs.append("forecast step numbers do not match cell numbers")
    return errs


# Key under which load_cells carries a run's SEALED agent metadata (from its
# manifest) alongside the cell, so the published stamp names the agent that
# actually produced the forecast.
SEALED_AGENT_KEY = "_sealedAgentMeta"


def agent_stamp() -> dict:
    """Version/hash metadata from the live agent definition.

    Fallback only. A recorded run's stamp must come from its own sealed
    manifest (SEALED_AGENT_KEY) — stamping live metadata made published
    provenance track HEAD instead of the run: editing any skill silently
    restamped every previously published cell with a version that never
    produced it, and broke wave reproducibility until the wave was
    regenerated into that same untruth (2026-07-25).
    """
    import subprocess

    builder = (
        pathlib.Path(__file__).resolve().parents[1]
        / "agents/thesis-analyst/build_prompt.py"
    )
    meta = json.loads(
        subprocess.check_output([sys.executable, str(builder), "--metadata"])
    )
    return meta


def sealed_agent_meta(run_dir: pathlib.Path) -> dict | None:
    """Agent identity recorded in a run's manifest, if it has one."""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    meta = json.loads(manifest_path.read_text()).get("agent")
    if not isinstance(meta, dict):
        return None
    required = ("agent", "agentVersion", "promptHash", "toolPolicyHash")
    return meta if all(meta.get(key) for key in required) else None


def to_forecast_cell(cell: dict) -> dict:
    out = {
        k: cell[k]
        for k in (
            "slug",
            "country",
            "type",
            "title",
            "question",
            "unit",
            "pointEstimate",
            "ciLow",
            "ciHigh",
            "confidence",
            "resolutionDate",
            "resolutionSource",
            "resolutionSourceUrl",
            "resolutionRule",
            "historicalContext",
            "drivers",
        )
    }
    if cell.get("dataPointId"):
        out["dataPointId"] = cell["dataPointId"]
    if cell.get("conditionalOn"):
        out["conditionalOn"] = cell["conditionalOn"]
    if cell.get("predictionDistribution"):
        out["predictionDistribution"] = cell["predictionDistribution"]
    stamp = cell.get(SEALED_AGENT_KEY) or agent_stamp()
    out["predictionRun"] = {
        "kind": "recorded-agent-run",
        "runAt": cell["runAt"],
        "agent": stamp["agent"],
        "model": cell.get("model", stamp.get("model")),
        "agentVersion": stamp["agentVersion"],
        "promptHash": stamp["promptHash"],
        "toolPolicyHash": stamp["toolPolicyHash"],
        "sourceContext": cell["sourceContext"],
    }
    if cell.get("promptMode"):
        out["predictionRun"]["promptMode"] = cell["promptMode"]
    if cell.get("reasoningEffort"):
        out["predictionRun"]["reasoningEffort"] = cell["reasoningEffort"]
    if cell.get("activityLog"):
        out["predictionRun"]["activityLog"] = cell["activityLog"]
    if cell.get("custodyRootSha256"):
        out["predictionRun"]["custodyRootSha256"] = cell["custodyRootSha256"]
    if cell.get("preSubmitReview"):
        out["predictionRun"]["preSubmitReview"] = cell["preSubmitReview"]
    out["reasoning"] = cell["reasoning"]
    return out


def load_cells(path: pathlib.Path) -> list[dict]:
    from normalize_spawn_json import scrub_signed_zeros

    cells = scrub_signed_zeros(json.loads(path.read_text()))
    if not isinstance(cells, list):
        raise ValueError(f"cell input must be a JSON list: {path}")
    sealed_agent = sealed_agent_meta(path.parent)
    if sealed_agent:
        for cell in cells:
            cell[SEALED_AGENT_KEY] = sealed_agent
    manifest_path = path.parent / "manifest.json"
    custody_path = path.parent / "custody_root.json"
    if custody_path.exists():
        from verify_custody import verify_run

        verify_run(path.parent)
        manifest = json.loads(manifest_path.read_text())
        declared = pathlib.Path(manifest["cellsPath"])
        if not declared.is_absolute():
            declared = ROOT / declared
        if declared.resolve() != path.resolve():
            raise ValueError(
                "manifest cellsPath does not name converter input: "
                f"{declared} != {path}"
            )
        for cell in cells:
            cell["custodyRootSha256"] = manifest["custodyRootSha256"]
    elif any(
        str(cell.get("runAt", ""))[:10] >= CUSTODY_ENFORCEMENT_DATE for cell in cells
    ):
        raise ValueError(
            f"run on/after {CUSTODY_ENFORCEMENT_DATE} lacks custody_root.json: {path}"
        )
    return cells


def repo_path(path: pathlib.Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_ts")
    parser.add_argument("const_name")
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--batch-manifest", action="append", default=[])
    parser.add_argument("--replace-module")
    args = parser.parse_args()
    out_ts = args.out_ts
    const_name = args.const_name
    inputs = args.inputs
    site_data = ROOT / "site/src/data"
    collision_exclusion = pathlib.Path(args.replace_module or out_ts)
    taken = existing_slugs(site_data, collision_exclusion)
    cells, failed = [], []
    seen = set()
    for path in inputs:
        for cell in load_cells(pathlib.Path(path)):
            errs = validate(cell, taken | seen)
            if errs:
                failed.append((cell.get("slug", "?"), errs))
            else:
                seen.add(cell["slug"])
                cells.append(to_forecast_cell(cell))
    cells.sort(key=lambda c: c["resolutionDate"])

    body = ",\n".join(
        "  " + json.dumps(c, indent=2, ensure_ascii=False).replace("\n", "\n  ")
        for c in cells
    )
    provenance = ""
    if args.batch_manifest:
        batch_paths = [repo_path(pathlib.Path(path)) for path in args.batch_manifest]
        provenance = f"// Batch manifests: {json.dumps(batch_paths)}\n"
    header = (
        "// Generated by scripts/spawned_cells_to_ts.py from recorded\n"
        "// thesis.analyst agent runs. Every tool-step result was fetched from\n"
        "// the named source at predictionRun.runAt; regenerate, don't hand-edit.\n"
        + provenance
        + 'import type { ForecastCell } from "../forecast-cells";\n\n'
        f"export const {const_name}: ForecastCell[] = [\n{body},\n];\n"
    )
    pathlib.Path(out_ts).write_text(header)
    print(f"wrote {len(cells)} cells -> {out_ts}")
    for slug, errs in failed:
        print(f"REJECTED {slug}: {'; '.join(errs)}")
    return 1 if failed and not cells else 0


if __name__ == "__main__":
    sys.exit(main())
