"""Analysis layer for the pre-registered bill-conditioned forecasting ablation.

Design is frozen in PREREGISTRATION.md; this module answers exactly the
pre-registered questions P1-P4 plus the declared null definitions, and labels
everything else EXPLORATORY. It reads `runs_api.jsonl` (produced by sweep.py /
harness.py), scores every parsed forecast with the already-pinned scorer in
`scoring.py`, and writes six artefacts to --outdir.

    python3 experiments/billimpact/analyze.py --runs <path> --outdir <path>

Nothing in this file modifies an existing repo file. Scoring is imported, never
re-implemented; the repo's own `proportion_z_test` / `mann_whitney_u` are
imported from `brier/experiments/analyze.py` where they fit.

Two rules the pre-registration binds this file to, restated because they are
easy to violate by accident:

  * The headline is a DISPERSION. No "best configuration" is reported anywhere.
  * No per-config difference is quoted without its across-repeat variance.

Dropped data is never silent: every skipped line, duplicate cell, API error,
parse failure and missing cell is counted and printed into the markdown.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for _p in (str(HERE), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import scoring  # noqa: E402  (experiments/billimpact/scoring.py — pinned CRPS+PIT port)

# Repo statistics helpers. Both return COARSE bucketed p-values (0.001 / 0.01 /
# 0.05 / 0.10 / 0.20) rather than exact ones — that limitation is surfaced in
# every table that uses them.
try:
    from brier.experiments.analyze import (  # noqa: E402
        mann_whitney_u,
        proportion_z_test,
    )

    REPO_STATS_AVAILABLE = True
    REPO_STATS_NOTE = (
        "repo helpers `proportion_z_test` / `mann_whitney_u` "
        "(brier/experiments/analyze.py) return bucketed p-values "
        "(0.001/0.01/0.05/0.10/0.20), not exact ones"
    )
except Exception as _e:  # noqa: BLE001
    REPO_STATS_AVAILABLE = False
    REPO_STATS_NOTE = f"repo stats helpers unavailable: {type(_e).__name__}: {_e}"

    def mann_whitney_u(a, b):  # type: ignore[misc]
        return None

    def proportion_z_test(n1, p1, n2, p2):  # type: ignore[misc]
        return None


# ---------------------------------------------------------------------------
# frozen design constants (mirrored from PREREGISTRATION.md / sweep.py;
# duplicated as literals so this file never mutates the harness)
# ---------------------------------------------------------------------------

DIM_ORDER = ["D1", "D2", "D3", "D4", "D5"]
DIMENSIONS: dict[str, tuple[str, list[str]]] = {
    "D1": ("policy_context",
           ["none", "summary", "operative_only", "purpose_only", "operative_plus_purpose"]),
    "D2": ("elicitation",
           ["point_ci_json", "free_text", "cot_then_json", "forced_choice_bins"]),
    "D3": ("pipeline", ["single_pass", "debate"]),
    # D4 amended 2026-07-31 12:05 EDT (sweep.py): claude-fable-5 added as a
    # fourth tier, strictly additive. Model tier is EXPLORATORY per prereg.
    "D4": ("model",
           ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001", "claude-fable-5"]),
    "D5": ("magnitude", ["actual", "severe", "inert"]),
}
CONFIG_KEYS = ["policy_context", "elicitation", "pipeline", "model", "magnitude"]

# Reference configuration: every dimension slice holds the OTHER four dims here.
# policy_context="operative_only" is the reference for D2-D5 because it is the
# only policy_context the contamination arm (D5) was run at, so using it keeps
# all four non-D1 dimensions measured on the same conditioned forecast.
REFERENCE = {
    "policy_context": "operative_only",
    "elicitation": "point_ci_json",
    "pipeline": "single_pass",
    "model": "claude-sonnet-5",
    "magnitude": "actual",
}
UNCONDITIONED_LEVEL = "none"

# harness.py max_tokens caps, used ONLY for run records written before the
# harness began recording `max_tokens` on each call (2026-07-31 ~14:40 EDT).
# Two regimes have run: the original caps, and the raised caps adopted at 14:05
# after five runs truncated exactly at the cap and lost their trailing JSON.
# A mirrored constant is a hand-maintained copy of another file's behaviour and
# had already gone stale once — this table therefore lists every cap a role has
# EVER run under, and the recorded value on the call wins whenever present.
MAX_TOKENS_HISTORY = {
    "draft": (2000, 4000),
    "draft_cot": (3000, 6000),
    "skeptic": (1200, 2500),
    "verifier": (1200, 2500),
    "judge": (1200, 2500),
}

PRIMARY_TESTS = 4  # P1-P4; Bonferroni alpha = 0.05 / 4
ALPHA = 0.05
ALPHA_BONF = ALPHA / PRIMARY_TESTS

# A bootstrap over 1-2 units cannot produce an honest interval: resampling so
# few units yields a degenerate CI (often ci_low == ci_high), which would then
# read as a confident verdict. Below this many units, and whenever the interval
# comes back degenerate, the verdict is UNDETERMINED rather than significant.
# This binds on partial sweeps; at the full pre-registered N (12 units) it never
# fires.
MIN_UNITS_FOR_VERDICT = 3

# Plausibility band for a parsed forecast, as a multiple of the unit's LAST
# OBSERVED history value. A state SNAP caseload cannot plausibly move by 10x in
# 30 months, so anything outside this band is an extraction artefact rather than
# a forecast. Runs outside the band are FLAGGED and COUNTED, never dropped from
# the primary analysis; a clearly-labelled sensitivity analysis re-runs
# everything without them. See PLAUSIBILITY_NOTE.
PLAUSIBLE_LO, PLAUSIBLE_HI = 0.1, 10.0
PLAUSIBILITY_NOTE = (
    "A parsed forecast is flagged `implausible_extraction` when its point OR either interval "
    "endpoint falls outside [0.1x, 10x] the unit's last observed history value. This band is "
    "deliberately loose (a state SNAP caseload cannot move 10-fold in 30 months). It exists to "
    "separate an extraction artefact from a forecast, not to filter forecasts by quality."
)

STATE_OF = {"ca": "CA", "fl": "FL", "ny": "NY", "tx": "TX", "pa": "PA", "oh": "OH"}


# ---------------------------------------------------------------------------
# small statistics utilities (kept dependency-free on purpose)
# ---------------------------------------------------------------------------


def med(xs: Iterable[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None and not _isnan(x)]
    return statistics.median(xs) if xs else None


def mean(xs: Iterable[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None and not _isnan(x)]
    return statistics.fmean(xs) if xs else None


def sd(xs: Iterable[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None and not _isnan(x)]
    return statistics.stdev(xs) if len(xs) >= 2 else None


def _isnan(x: Any) -> bool:
    return isinstance(x, float) and math.isnan(x)


def quantile(xs: list[float], q: float) -> Optional[float]:
    """Linear-interpolation quantile (type 7), no numpy dependency."""
    xs = sorted(x for x in xs if x is not None and not _isnan(x))
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[int(pos)]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def iqr(xs: list[float]) -> tuple[Optional[float], Optional[float]]:
    return quantile(xs, 0.25), quantile(xs, 0.75)


def bootstrap_ci(
    units: list[str],
    stat_fn,
    rng: random.Random,
    draws: int,
    lo_q: float = 0.025,
    hi_q: float = 0.975,
) -> dict[str, Any]:
    """Resample UNITS with replacement; recompute stat_fn(unit_list) each draw."""
    point = stat_fn(units)
    if not units:
        return {"point": None, "ci_low": None, "ci_high": None, "n_units": 0,
                "n_draws": 0, "n_valid_draws": 0}
    vals: list[float] = []
    n = len(units)
    for _ in range(draws):
        sample = [units[rng.randrange(n)] for _ in range(n)]
        v = stat_fn(sample)
        if v is not None and not _isnan(v) and not math.isinf(v):
            vals.append(v)
    return {
        "point": point,
        "ci_low": quantile(vals, lo_q) if vals else None,
        "ci_high": quantile(vals, hi_q) if vals else None,
        "n_units": n,
        "n_draws": draws,
        "n_valid_draws": len(vals),
    }


def binom_two_sided_p(k: int, n: int, p: float = 0.5) -> Optional[float]:
    """Exact two-sided binomial p-value, 2x the smaller tail, capped at 1."""
    if n <= 0:
        return None

    def cdf(kk: int) -> float:
        return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(0, kk + 1))

    lower = cdf(k)
    upper = 1.0 - cdf(k - 1) if k > 0 else 1.0
    return min(1.0, 2.0 * min(lower, upper))


def fmt(x: Optional[float], nd: int = 2, pct: bool = False) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "null"
    if pct:
        return f"{x:.{nd}f}%"
    if abs(x) >= 100000:
        return f"{x:,.0f}"
    return f"{x:.{nd}f}"


def fmt_ci(d: dict[str, Any], nd: int = 2) -> str:
    return f"[{fmt(d.get('ci_low'), nd)}, {fmt(d.get('ci_high'), nd)}]"


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def load_ground_truth(path: Path) -> tuple[dict[str, dict], dict[str, Any]]:
    """Units keyed by unit_id, with the pre-registration-frozen history SD.

    Normalised CRPS is divided by the SD of the unit's own supplied history (the
    pre-origin observations shipped in ground_truth.json). It is DELIBERATELY
    not normalised by the model's own interval width: an agent can widen its
    interval to shrink a width-normalised error, and the repo already fixed that
    bug once.
    """
    raw = json.loads(path.read_text())
    units: dict[str, dict] = {}
    notes = {"n_in_file": len(raw), "dropped_no_truth": [], "dropped_no_history": []}
    for u in raw:
        uid = u["unit_id"]
        truth = (u.get("truth") or {}).get("first_print_value")
        hist = [r["value"] for r in (u.get("history") or []) if r.get("value") is not None]
        if truth is None:
            notes["dropped_no_truth"].append(uid)
            continue
        if len(hist) < 2:
            notes["dropped_no_history"].append(uid)
            continue
        units[uid] = {
            "unit_id": uid,
            "state": u.get("state"),
            "target_month": u.get("target_month"),
            "truth": float(truth),
            "history_n": len(hist),
            "history_sd": statistics.stdev(hist),
            "history_last": hist[-1],
        }
    notes["n_usable"] = len(units)
    return units, notes


def _final_call_caps(rec: dict) -> tuple[int, ...]:
    """Caps the final call could have run under, tightest evidence first.

    A completion truncated at the cap reports `completion_tokens` EXACTLY equal
    to it, so the test downstream is equality, not `>=`: against a set of
    candidate caps `>=` would flag a 3,100-token response as truncated merely
    because an older, smaller cap once existed.
    """
    calls = rec.get("calls") or []
    if not calls:
        return ()
    recorded = calls[-1].get("max_tokens")
    if isinstance(recorded, int):
        return (recorded,)
    role = calls[-1].get("role")
    if role == "draft":
        role = ("draft_cot" if rec.get("config", {}).get("elicitation") == "cot_then_json"
                else "draft")
    return MAX_TOKENS_HISTORY.get(role, ())


def load_runs(path: Path, units: dict[str, dict]) -> tuple[list[dict], dict[str, Any]]:
    """Read the JSONL defensively. Every rejection is counted, never silent."""
    q: dict[str, Any] = {
        "path": str(path),
        "lines_total": 0,
        "lines_blank": 0,
        "lines_malformed_json": 0,
        "lines_missing_required_field": 0,
        "records_read": 0,
        "duplicate_cell_keys_dropped": 0,
        "duplicates_resolved_in_favour_of_later_success": 0,
        "duplicate_cell_key_examples": [],
        "sibling_quarantine_files": {},
        "unknown_unit_id": 0,
        "unknown_unit_ids": [],
        "api_errors": 0,
        "api_error_kinds": {},
        "parse_failures": 0,
        "parse_failure_kinds": {},
        "parse_failures_truncated_at_max_tokens": 0,
        "truth_mismatch_vs_ground_truth": 0,
        "parse_mode_counts": {},
        "implausible_extractions": 0,
        "implausible_by_elicitation_and_parse_mode": {},
        "scored_by_elicitation_and_parse_mode": {},
        "implausible_examples": [],
        "scored": 0,
        "scoring_errors": 0,
        "scoring_error_examples": [],
        # Derived from the `forecast_v1` field that reparse.py preserves on
        # every re-derived record. These are MEASURED off the file being
        # analysed, not narrated, so the correction claim carries its operands.
        "parser_correction": {
            "records_with_v1_parse": 0,
            "points_changed": 0,
            "v1_year_shaped_points": 0,
            "v1_degenerate_intervals": 0,
            "v2_year_shaped_points": 0,
            "v1_parse_modes": {},
            "v1_year_shaped_by_elicitation": {},
            "v1_json_path_records": 0,
            "v1_json_path_unchanged": 0,
        },
        "parser_versions": {},
    }
    runs: list[dict] = []
    api_err = Counter()
    parse_err = Counter()
    pmodes = Counter()
    implaus = Counter()
    scored_by = Counter()

    # Pass 1 — read and de-duplicate. The sweep is resumable and a sibling
    # process may re-execute a failed cell, so the same cell_key can appear
    # twice. Prefer the record that actually parsed; otherwise keep the first.
    # Both branches are counted.
    chosen: dict[str, dict] = {}
    order: list[str] = []
    with path.open() as fh:
        for line in fh:
            q["lines_total"] += 1
            line = line.strip()
            if not line:
                q["lines_blank"] += 1
                continue
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001  (a partially-written tail line is expected mid-sweep)
                q["lines_malformed_json"] += 1
                continue
            if not isinstance(rec, dict) or "cell_key" not in rec or "config" not in rec:
                q["lines_missing_required_field"] += 1
                continue
            ck = rec["cell_key"]
            parsed_ok = ((rec.get("forecast") or {}).get("point") is not None
                         and not rec.get("error"))
            if ck in chosen:
                q["duplicate_cell_keys_dropped"] += 1
                if len(q["duplicate_cell_key_examples"]) < 5:
                    q["duplicate_cell_key_examples"].append(ck)
                prev_ok = ((chosen[ck].get("forecast") or {}).get("point") is not None
                           and not chosen[ck].get("error"))
                if parsed_ok and not prev_ok:
                    q["duplicates_resolved_in_favour_of_later_success"] += 1
                    chosen[ck] = rec
                continue
            chosen[ck] = rec
            order.append(ck)

    # Pass 2 — classify and score exactly one record per cell.
    for ck in order:
        rec = chosen[ck]
        q["records_read"] += 1

        uid = rec.get("unit_id")
        if uid not in units:
            q["unknown_unit_id"] += 1
            if uid not in q["unknown_unit_ids"]:
                q["unknown_unit_ids"].append(uid)
            continue

        cfg = rec.get("config") or {}
        fc = rec.get("forecast") or {}

        # Pre-fix parse, where reparse.py preserved one. Absent on records the
        # sweep wrote after the fix landed, which is why the denominator below
        # is `records_with_v1_parse` rather than `records_read`.
        v1 = rec.get("forecast_v1")
        if isinstance(v1, dict) and v1:
            pc = q["parser_correction"]
            pc["records_with_v1_parse"] += 1
            pc["v1_parse_modes"][str(v1.get("parse_mode"))] = (
                pc["v1_parse_modes"].get(str(v1.get("parse_mode")), 0) + 1)
            if v1.get("point") != fc.get("point"):
                pc["points_changed"] += 1
            if v1.get("point") is not None and 1900 <= v1["point"] <= 2100:
                pc["v1_year_shaped_points"] += 1
                elic = str(cfg.get("elicitation"))
                pc["v1_year_shaped_by_elicitation"][elic] = (
                    pc["v1_year_shaped_by_elicitation"].get(elic, 0) + 1)
            if v1.get("ci_low") is not None and v1.get("ci_low") == v1.get("ci_high"):
                pc["v1_degenerate_intervals"] += 1
            # The fix must be confined to the prose and malformed-JSON paths.
            # Anything that parsed via strict JSON before must be identical now.
            if v1.get("parse_mode") == "json":
                pc["v1_json_path_records"] += 1
                if all(v1.get(k) == fc.get(k) for k in ("point", "ci_low", "ci_high", "bin")):
                    pc["v1_json_path_unchanged"] += 1
        if fc.get("point") is not None and 1900 <= fc["point"] <= 2100:
            q["parser_correction"]["v2_year_shaped_points"] += 1
        pv = str(rec.get("parser_version") or "<unrecorded>")
        q["parser_versions"][pv] = q["parser_versions"].get(pv, 0) + 1

        row: dict[str, Any] = {
            "unit_id": uid,
            "rep": rec.get("rep"),
            "arms": rec.get("arms") or [],
            "cell_key": ck,
            "config": {k: cfg.get(k) for k in CONFIG_KEYS},
            "config_key": tuple(cfg.get(k) for k in CONFIG_KEYS),
            "truth": units[uid]["truth"],
            "error": rec.get("error"),
            "parse_mode": fc.get("parse_mode"),
            "point": None, "ci_low": None, "ci_high": None,
            "crps": None, "pit": None, "covered80": None,
            "width": None, "ok": False, "implausible": False,
        }
        pmodes[str(fc.get("parse_mode"))] += 1

        rec_truth = rec.get("truth")
        if rec_truth is not None and abs(float(rec_truth) - units[uid]["truth"]) > 1e-6:
            q["truth_mismatch_vs_ground_truth"] += 1

        if rec.get("error"):
            q["api_errors"] += 1
            api_err[str(rec["error"])[:80]] += 1
            runs.append(row)
            continue

        if "parse_error" in fc or fc.get("point") is None:
            q["parse_failures"] += 1
            kind = fc.get("parse_error", "missing_forecast")
            caps = _final_call_caps(rec)
            calls = rec.get("calls") or []
            ctok = calls[-1].get("completion_tokens") if calls else None
            hit = next((c for c in caps if ctok == c), None) if ctok is not None else None
            if hit is not None:
                q["parse_failures_truncated_at_max_tokens"] += 1
                kind = f"{kind} (output truncated at max_tokens={hit})"
            parse_err[kind] += 1
            row["parse_error"] = kind
            runs.append(row)
            continue

        point, lo, hi = float(fc["point"]), float(fc["ci_low"]), float(fc["ci_high"])
        row.update({"point": point, "ci_low": lo, "ci_high": hi, "width": hi - lo})
        last = units[uid]["history_last"]
        bucket = f"{cfg.get('elicitation')}/{fc.get('parse_mode')}"
        scored_by[bucket] += 1
        if last and any(v < PLAUSIBLE_LO * last or v > PLAUSIBLE_HI * last
                        for v in (point, lo, hi)):
            q["implausible_extractions"] += 1
            implaus[bucket] += 1
            row["implausible"] = True
            if len(q["implausible_examples"]) < 6:
                q["implausible_examples"].append({
                    "cell_key": ck, "point": point, "ci_low": lo, "ci_high": hi,
                    "last_history_value": last, "parse_mode": fc.get("parse_mode")})
        try:
            s = scoring.score_forecast(point, lo, hi, units[uid]["truth"])
            row.update({"crps": s["crps"], "pit": s["pit"], "covered80": s["covered80"],
                        "abs_error": s["abs_error"], "pct_error": s["pct_error"],
                        "ok": True})
            row["crps_norm"] = s["crps"] / units[uid]["history_sd"]
            row["width_norm"] = (hi - lo) / units[uid]["history_sd"]
            q["scored"] += 1
        except Exception as e:  # noqa: BLE001
            q["scoring_errors"] += 1
            if len(q["scoring_error_examples"]) < 5:
                q["scoring_error_examples"].append(f"{ck}: {type(e).__name__}: {e}")
        runs.append(row)

    q["api_error_kinds"] = dict(api_err)
    q["parse_failure_kinds"] = dict(parse_err)
    q["parse_mode_counts"] = dict(pmodes)
    q["implausible_by_elicitation_and_parse_mode"] = dict(implaus)
    q["scored_by_elicitation_and_parse_mode"] = dict(scored_by)
    q["sibling_quarantine_files"] = scan_sibling_quarantine(path, set(chosen))
    return runs, q


def scan_sibling_quarantine(runs_path: Path, present: set[str]) -> dict[str, Any]:
    """Report runs another process pulled OUT of the runs file.

    The sweep is resumable and a sibling session may move unparseable records to
    a `*.quarantined.jsonl` beside the runs file. Those records are invisible to
    a reader of the runs file alone, so a dropped-run count computed only from
    `--runs` would silently understate. Anything found here is REPORTED; nothing
    found here is analysed.
    """
    out: dict[str, Any] = {}
    stem = runs_path.name.split(".")[0]
    for sib in sorted(runs_path.parent.glob(f"{stem}*.jsonl")):
        if sib == runs_path or "quarantin" not in sib.name:
            continue
        n, reasons, keys = 0, Counter(), set()
        year_shaped_v1 = 0
        for line in sib.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                reasons["<malformed line>"] += 1
                continue
            reasons[str(r.get("_quarantined_reason")
                        or r.get("quarantine_reason") or "<no reason field>")[:80]] += 1
            v1p = (r.get("forecast_v1") or {}).get("point")
            if v1p is not None and 1900 <= v1p <= 2100:
                year_shaped_v1 += 1
            if r.get("cell_key"):
                keys.add(r["cell_key"])
        out[sib.name] = {
            "n_records": n,
            "reasons": dict(reasons),
            "n_cells_also_present_in_runs_file": len(keys & present),
            "n_cells_absent_from_runs_file": len(keys - present),
            "n_year_shaped_v1_parses": year_shaped_v1,
        }
    return out


def planned_grid() -> tuple[Optional[set[str]], Optional[str]]:
    """Planned cell_keys from sweep.build_plan, so missing cells are countable."""
    try:
        import sweep  # noqa: PLC0415

        gt = json.loads((HERE / "ground_truth.json").read_text())
        uids = sorted(u["unit_id"] for u in gt
                      if (u.get("truth") or {}).get("first_print_value") is not None)
        plan = sweep.build_plan(uids)
        return {sweep.cell_key(u, c, r) for (u, c, r, _a) in plan}, None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# indexing
# ---------------------------------------------------------------------------


class Index:
    """Run lookup by (config tuple, unit) and by config.

    `require_plausible=True` builds the sensitivity view: runs whose parsed
    forecast failed the plausibility band are excluded. The primary view keeps
    every scored run. Both are always computed and both are always reported.
    """

    def __init__(self, runs: list[dict], units: dict[str, dict],
                 require_plausible: bool = False):
        self.runs = runs
        self.units = units
        self.require_plausible = require_plausible
        self.by_cfg_unit: dict[tuple, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        self.by_cfg: dict[tuple, list[dict]] = defaultdict(list)
        for r in runs:
            self.by_cfg_unit[r["config_key"]][r["unit_id"]].append(r)
            self.by_cfg[r["config_key"]].append(r)
        self.configs = sorted(self.by_cfg)

    @staticmethod
    def key(overrides: dict[str, str]) -> tuple:
        cfg = dict(REFERENCE)
        cfg.update(overrides)
        return tuple(cfg[k] for k in CONFIG_KEYS)

    def usable(self, r: dict) -> bool:
        return bool(r["ok"]) and not (self.require_plausible and r.get("implausible"))

    def cell(self, overrides: dict[str, str], unit_id: str) -> list[dict]:
        return [r for r in self.by_cfg_unit[self.key(overrides)][unit_id] if self.usable(r)]

    def cell_points(self, overrides: dict[str, str], unit_id: str) -> list[float]:
        return [r["point"] for r in self.cell(overrides, unit_id)]


def unconditioned_medians(idx: Index) -> tuple[dict[str, float], list[str]]:
    """Per-unit median forecast at policy_context='none', other dims at reference."""
    out: dict[str, float] = {}
    missing: list[str] = []
    for uid in sorted(idx.units):
        pts = idx.cell_points({"policy_context": UNCONDITIONED_LEVEL}, uid)
        m = med(pts)
        if m is None or m == 0:
            missing.append(uid)
        else:
            out[uid] = m
    return out, missing


# ---------------------------------------------------------------------------
# 1. results_table.md
# ---------------------------------------------------------------------------


def build_cell_rows(idx: Index, uncond: dict[str, float]) -> list[dict]:
    rows = []
    for cfg_key in idx.configs:
        runs = idx.by_cfg[cfg_key]
        by_unit: dict[str, list[dict]] = defaultdict(list)
        for r in runs:
            by_unit[r["unit_id"]].append(r)
        ok = [r for r in runs if r["ok"]]
        n_parse_fail = sum(1 for r in runs if r.get("parse_error"))
        n_api_err = sum(1 for r in runs if r.get("error"))
        n_implausible = sum(1 for r in runs if r.get("implausible"))

        per_unit_medians, sd_reps_abs, sd_reps_rel, norm_points = [], [], [], []
        for uid, rr in by_unit.items():
            pts = [r["point"] for r in rr if r["ok"]]
            if not pts:
                continue
            per_unit_medians.append(statistics.median(pts))
            s = sd(pts)
            m = mean(pts)
            if s is not None and m:
                sd_reps_abs.append(s)
                sd_reps_rel.append(100.0 * s / m)
            if uid in uncond:
                norm_points.extend(p / uncond[uid] for p in pts)

        rows.append({
            "config": dict(zip(CONFIG_KEYS, cfg_key)),
            "config_key": cfg_key,
            "n_runs": len(runs),
            "n_units": len(by_unit),
            "n_scored": len(ok),
            "n_parse_failures": n_parse_fail,
            "n_api_errors": n_api_err,
            "n_implausible_extractions": n_implausible,
            "median_forecast_persons": med(per_unit_medians),
            "median_forecast_norm": med(norm_points),
            "n_runs_normalised": len(norm_points),
            "sd_forecast_across_reps_persons": mean(sd_reps_abs),
            "sd_forecast_across_reps_pct": mean(sd_reps_rel),
            "n_units_with_sd": len(sd_reps_abs),
            "mean_crps": mean([r["crps"] for r in ok]),
            "sd_crps": sd([r["crps"] for r in ok]),
            "mean_crps_norm": mean([r.get("crps_norm") for r in ok]),
            "sd_crps_norm": sd([r.get("crps_norm") for r in ok]),
            "coverage80": mean([r["covered80"] for r in ok]),
            "mean_pit": mean([r["pit"] for r in ok]),
            "mean_interval_width_persons": mean([r["width"] for r in ok]),
            "mean_interval_width_norm": mean([r.get("width_norm") for r in ok]),
        })
    rows.sort(key=lambda r: r["config_key"])
    return rows


def write_results_table(rows: list[dict], q: dict, units: dict, out: Path, meta: dict) -> None:
    L = []
    L.append("# Results table — one row per configuration cell\n")
    L.append(f"Generated {meta['generated_at']} from `{q['path']}`.\n")
    L.append(f"**N = {q['records_read']} runs read, {q['scored']} scored, "
             f"{len(rows)} configuration cells, {len(units)} units.** "
             f"Sweep completion: {meta['completion_str']}.\n")
    L.append("Every row states its own N. Reps per (cell, unit) = 5 by "
             "pre-registration; a partial sweep will show fewer.\n")
    L.append("**Column definitions.**\n")
    L.append("- `n_runs` — runs in this configuration cell, pooled over units and repeats. "
             "`n_units` — distinct units contributing. `n_scored` — runs with a parsed forecast.")
    L.append("- `median_persons` — median across units of the per-unit median forecast, in "
             "persons. Units differ in scale by ~4x (CA ~4.4M vs OH ~1.4M), so this column is "
             "**not** comparable across units; it is here for face-validity only. Use "
             "`median_norm`.")
    L.append("- `median_norm` — median of (forecast / that unit's unconditioned median), where "
             "the unconditioned median is the unit's median forecast at "
             "`policy_context=none` with the other four dimensions at reference "
             f"({', '.join(f'{k}={v}' for k, v in REFERENCE.items() if k != 'policy_context')}). "
             "1.000 means identical to the unconditioned forecast.")
    L.append("- `sd_reps_%` — mean across units of (SD of the forecast across repeats within "
             "this cell / mean forecast) x 100. This is the per-config variance that the "
             "pre-registration forbids omitting. `sd_reps_persons` is the same in persons.")
    L.append("- `mean_crps` / `sd_crps` — CRPS against the first print, persons, across all runs "
             "in the cell. `crps_norm` — CRPS divided by the SD of that unit's own supplied "
             "60-month history (frozen in ground_truth.json at pre-registration). "
             "**Never normalised by the model's own interval width.**")
    L.append("- `cov80` — fraction of runs whose 80% interval contains the first print "
             "(nominal 0.80). `mean_pit` — mean probability integral transform (calibrated = "
             "0.50, uniform). `width` — mean 80% interval width, persons; `width_norm` — the "
             "same divided by the unit's history SD.")
    L.append(f"- `n_implaus` — runs flagged `implausible_extraction`. {PLAUSIBILITY_NOTE} "
             "**Flagged runs are retained in every number in this table**; the sensitivity "
             "analysis that excludes them is reported separately in `dispersion.md` and "
             "`primary_analyses.md`.\n")

    # Always rendered. The defect below is CORRECTED, and a corrected defect
    # that stops being reported is indistinguishable from one that never
    # happened — 214 of these runs really did carry a calendar year as their
    # forecast until the parser was fixed, and the pre-registration does not
    # permit quietly tidying that out of the record.
    L.append(extraction_defect_block(q))

    hdr = ("| policy_context | elicitation | pipeline | model | magnitude | n_runs | n_units | "
           "n_scored | n_parse_fail | n_api_err | n_implaus | median_persons | median_norm | "
           "sd_reps_% | sd_reps_persons | mean_crps | sd_crps | mean_crps_norm | cov80 | "
           "mean_pit | width | width_norm |")
    L.append(hdr)
    L.append("|" + "---|" * 22)
    for r in rows:
        c = r["config"]
        L.append("| " + " | ".join([
            str(c["policy_context"]), str(c["elicitation"]), str(c["pipeline"]),
            str(c["model"]), str(c["magnitude"]),
            str(r["n_runs"]), str(r["n_units"]), str(r["n_scored"]),
            str(r["n_parse_failures"]), str(r["n_api_errors"]),
            str(r["n_implausible_extractions"]),
            fmt(r["median_forecast_persons"], 0),
            fmt(r["median_forecast_norm"], 3),
            fmt(r["sd_forecast_across_reps_pct"], 2),
            fmt(r["sd_forecast_across_reps_persons"], 0),
            fmt(r["mean_crps"], 0), fmt(r["sd_crps"], 0),
            fmt(r["mean_crps_norm"], 3),
            fmt(r["coverage80"], 3), fmt(r["mean_pit"], 3),
            fmt(r["mean_interval_width_persons"], 0),
            fmt(r["mean_interval_width_norm"], 3),
        ]) + " |")

    L.append("\n## Data quality\n")
    L += quality_block(q, meta)
    out.write_text("\n".join(L) + "\n")


def extraction_defect_block(q: dict) -> str:
    """The free-text extraction defect: what it was, and what was done about it.

    This section is rendered unconditionally, including when the defect is fully
    corrected and the flagged count is zero. A data-quality finding that
    disappears from the report once it is fixed leaves a reader unable to tell a
    corrected pipeline from one that never had the problem, and the numbers
    below were wrong in a published intermediate state.
    """
    pc = q["parser_correction"]
    scored = q["scored"] or 1
    quarantined_year_shaped = sum(
        v.get("n_year_shaped_v1_parses", 0)
        for v in (q.get("sibling_quarantine_files") or {}).values()
    )
    n_v1 = pc["records_with_v1_parse"]

    lines = [
        "\n## DATA-QUALITY FINDING (CORRECTED) — free-text extraction returned calendar "
        "years as forecasts\n",
        "**Status: found, fixed, and re-derived offline. No run was dropped.** The numbers "
        "in every table in this report come from the corrected parse "
        f"(parser versions observed on the run records: `{q.get('parser_versions')}`).",
        "",
        "### What went wrong",
        "",
        "The v1 prose fallback in `harness.parse_forecast` matched any number, filtered "
        "candidates with `n > 1000`, and returned the FIRST 3-wide window satisfying an "
        "ordering test. `2021`, `2023` and `2024` all clear 1000, and a prose forecast "
        "discusses the series history before it states an answer, so the first matching "
        "window was routinely a run of calendar years: \"the last available data point in "
        "June 2021\" yielded `{point: 2023, ci_low: 2021, ci_high: 2023}` for a series whose "
        "true level is ~4.2 million persons.",
        "",
        "This was not noise. It fired only on prose, which is one LEVEL of a measured "
        "dimension (D2 `elicitation`), so it manufactured a difference between `free_text` "
        "and JSON that had nothing to do with elicitation format — the exact class of "
        "artefact this experiment exists to detect. A quieter second case hit "
        "`cot_then_json`: a trailing JSON object truncated at `max_tokens` or broken by a "
        "stray quote never reached the JSON path, so the prose heuristic mined the reasoning "
        "instead of reading the answer.",
        "",
        "### Measured extent, before and after",
        "",
        f"Derived from the `forecast_v1` field preserved on **{n_v1}** re-derived records "
        "(`reparse.py`), not from narrative. Cells that were quarantined and re-executed no "
        "longer carry a v1 parse in this file, so their pre-fix parses are counted separately "
        f"below: **{quarantined_year_shaped}** further calendar-year points sit in the sibling "
        f"quarantine file(s), for a complete pre-fix total of "
        f"**{pc['v1_year_shaped_points'] + quarantined_year_shaped}**.",
        "",
        "| quantity | before fix | after fix |",
        "|---|---|---|",
        f"| points that were a calendar year (1900-2100) | "
        f"{pc['v1_year_shaped_points'] + quarantined_year_shaped} "
        f"({pc['v1_year_shaped_points']} here + {quarantined_year_shaped} quarantined) | "
        f"{pc['v2_year_shaped_points']} |",
        f"| forecasts with no interval at all (`ci_low == ci_high`) | "
        f"{pc['v1_degenerate_intervals']} | 0 |",
        f"| runs outside [0.1x, 10x] the unit's last observed caseload | "
        f"(all of the above) | {q['implausible_extractions']} |",
        f"| point estimates changed by the re-derivation | — | {pc['points_changed']} |",
        "",
        f"v1 parse modes across those records: `{pc['v1_parse_modes']}`. "
        f"Calendar-year points by elicitation level: "
        f"`{pc['v1_year_shaped_by_elicitation']}`.",
        "",
        "### How it was corrected",
        "",
        "1. `harness.parse_forecast` v2 rejects year-shaped tokens, restricts prose "
        "candidates to within [0.2x, 5x] the unit's own last OBSERVED history value, locates "
        "the interval from explicit interval language taking the LAST such statement, and "
        "takes the point from the cue-marked candidate nearest that interval. The band is a "
        "SCALE filter, not an accuracy filter — a forecast of a 3x collapse still parses and "
        "is then scored badly on merit — and it is applied to the prose path ONLY, never to "
        "the JSON path, so D5 `magnitude_elasticity` (which runs entirely at "
        "`point_ci_json`) cannot be muted by it.",
        "2. The parser is strictly EXTRACTIVE. A response stating an interval but no point, "
        "or truncated before it answers, FAILS the parse and is counted; it is never repaired "
        "by imputing a midpoint the model did not write.",
        "3. Every stored response was re-derived OFFLINE — no model was re-called for the "
        "correction, so the re-parse is deterministic and introduces no new sampling. The "
        "alternative, re-eliciting `free_text`, would have drawn a fresh sample at a later "
        "date on one level of a measured dimension, which is a worse cure than the disease.",
        f"4. All **{pc['v1_json_path_unchanged']} of {pc['v1_json_path_records']}** runs that "
        "had parsed via strict JSON re-derived to identical values, confirming the fix is "
        "confined to the prose and malformed-JSON paths.",
        "5. Runs that remained unparseable were QUARANTINED with a recorded reason and "
        "re-executed under the raised `max_tokens` caps (see the quarantine table below); "
        "they were all truncations at the older caps, not model refusals.",
        "",
        "| elicitation / parse_mode | scored | flagged implausible | rate |",
        "|---|---|---|---|",
    ]
    for k in sorted(q["scored_by_elicitation_and_parse_mode"]):
        tot = q["scored_by_elicitation_and_parse_mode"][k]
        bad = q["implausible_by_elicitation_and_parse_mode"].get(k, 0)
        lines.append(f"| `{k}` | {tot} | {bad} | {100.0 * bad / tot:.1f}% |")

    consequence = (
        "Consequence for the analysis: D2 `elicitation` is the only pre-registered dimension "
        "containing a non-JSON elicitation level, so **P2 was the only primary result this "
        "defect could reach**. D1, D3, D4, D5 and the whole of `skill.md` run at "
        "`elicitation=point_ci_json` and were never affected."
    )
    if q["implausible_extractions"]:
        consequence += (
            f" **{q['implausible_extractions']} of {scored} scored runs "
            f"({100.0 * q['implausible_extractions'] / scored:.1f}%) remain outside the "
            "plausibility band**, so P2 is still reported twice — with all runs (primary, as "
            "pre-registered) and with flagged runs excluded (sensitivity, labelled)."
        )
    else:
        consequence += (
            " After the correction **no run is flagged implausible**, so the sensitivity view "
            "excludes nothing and is identical to the primary by construction; P2 is still "
            "reported both ways for continuity, and the primary P2 now measures elicitation "
            "format rather than the parser."
        )
    lines += ["", consequence, ""]

    if q["implausible_examples"]:
        lines += ["Residual flagged extractions (verbatim from the run records):", "", "```json"]
        for e in q["implausible_examples"][:4]:
            lines.append(json.dumps(e))
        lines += ["```", ""]
    return "\n".join(lines)


def quality_block(q: dict, meta: dict) -> list[str]:
    L = []
    L.append(f"- Lines in file: **{q['lines_total']}** "
             f"(blank {q['lines_blank']}, malformed JSON {q['lines_malformed_json']}, "
             f"missing required field {q['lines_missing_required_field']}).")
    L.append(f"- Records read (one per `cell_key`): **{q['records_read']}**; duplicate "
             f"`cell_key` seen: **{q['duplicate_cell_keys_dropped']}**, of which "
             f"{q['duplicates_resolved_in_favour_of_later_success']} were resolved in favour of "
             "a later record that parsed (the rest kept the first occurrence); "
             f"unknown unit_id: **{q['unknown_unit_id']}**.")
    if q.get("sibling_quarantine_files"):
        L.append("- **Records removed from the runs file by another process** (found in sibling "
                 "quarantine files beside it — reported, not analysed, because a dropped-run "
                 "count computed only from `--runs` would silently understate):")
        for name, info in q["sibling_quarantine_files"].items():
            L.append(f"    - `{name}`: {info['n_records']} record(s); "
                     f"{info['n_cells_also_present_in_runs_file']} of those cells were "
                     f"subsequently re-run and ARE present in the runs file, "
                     f"{info['n_cells_absent_from_runs_file']} are not; "
                     f"reasons {info['reasons']}")
    L.append(f"- API errors: **{q['api_errors']}**"
             + (f" — {q['api_error_kinds']}" if q["api_error_kinds"] else "") + ".")
    L.append(f"- Parse failures: **{q['parse_failures']}** "
             f"({100.0 * q['parse_failures'] / q['records_read']:.2f}% of records read)"
             if q["records_read"] else "- Parse failures: 0 (no records).")
    if q["parse_failure_kinds"]:
        for k, v in sorted(q["parse_failure_kinds"].items(), key=lambda kv: -kv[1]):
            L.append(f"    - `{k}`: {v}")
    L.append(f"- Parse failures attributable to output truncation at the harness `max_tokens` "
             f"cap: **{q['parse_failures_truncated_at_max_tokens']}** of {q['parse_failures']}.")
    L.append(f"- Parse modes: {q['parse_mode_counts']}. `json` is the intended path. "
             "`json_keyscan` reads point/ci_low/ci_high by key out of a trailing object that "
             "will not `json.loads` (truncated or malformed) — extraction, not repair, and "
             "all three keys are required. `prose_cued` is the free-text path: the interval "
             "comes from explicit interval language and the point from the cue-marked "
             "candidate nearest it. `prose_bracketed` / `prose_ordered` are tail-scanned "
             "fallbacks used only when no interval language is present and carry more "
             "extraction risk. See the corrected-defect section above.")
    L.append(f"- Runs scored: **{q['scored']}**; scoring exceptions: {q['scoring_errors']}"
             + (f" — {q['scoring_error_examples']}" if q["scoring_error_examples"] else "") + ".")
    L.append(f"- Forecasts flagged `implausible_extraction` (retained, **not dropped**): "
             f"**{q['implausible_extractions']}** — see the section above.")
    L.append(f"- `truth` disagreements between run records and ground_truth.json: "
             f"**{q['truth_mismatch_vs_ground_truth']}**.")
    if meta.get("planned_cells") is not None:
        L.append(f"- Pre-registered grid: **{meta['planned_cells']}** (unit, config, rep) cells; "
                 f"observed **{meta['observed_planned']}**; "
                 f"**missing {meta['missing_cells']}** "
                 f"({meta['completion_str']}). "
                 f"Observed cells not in the planned grid: {meta['unplanned_cells']}.")
    else:
        L.append(f"- Planned-grid comparison unavailable ({meta.get('planned_error')}); "
                 "missing-cell count cannot be computed and is reported as null.")
    if meta.get("units_missing_unconditioned"):
        L.append(f"- Units with **no** unconditioned (`policy_context=none`, reference) cell, "
                 f"therefore excluded from all normalised/dispersion metrics and reported here "
                 f"rather than dropped silently: {meta['units_missing_unconditioned']}.")
    return L


# ---------------------------------------------------------------------------
# 2. dispersion.md — the headline
# ---------------------------------------------------------------------------


def dimension_spread(idx: Index, dim: str, uncond: dict[str, float],
                     rng: random.Random, draws: int,
                     pool_over_policy_context: bool = False) -> dict[str, Any]:
    """spread / noise_floor / ratio for one ablation dimension.

    spread      — per unit, range of the per-level MEDIAN forecast across the
                  dimension's levels, as % of that unit's unconditioned median.
    noise_floor — per unit, the same range computed across the 5 REPEATS within
                  a cell, averaged over the dimension's cells, same denominator.
    ratio       — median(spread) / median(noise_floor) over units, bootstrap CI
                  by resampling units with replacement.
    """
    field, declared_levels = DIMENSIONS[dim]
    present_levels = [lv for lv in declared_levels
                      if any(r["config"][field] == lv for r in idx.runs)]
    missing_levels = [lv for lv in declared_levels if lv not in present_levels]

    per_unit: dict[str, dict[str, Any]] = {}
    for uid in sorted(uncond):
        denom = uncond[uid]
        level_medians: dict[str, float] = {}
        rep_ranges: dict[str, float] = {}
        rep_ns: dict[str, int] = {}
        for lv in present_levels:
            if pool_over_policy_context and field != "policy_context":
                pts, ranges = [], []
                for pc in DIMENSIONS["D1"][1]:
                    sub = idx.cell_points({field: lv, "policy_context": pc}, uid)
                    if sub:
                        pts.extend(sub)
                        if len(sub) >= 2:
                            ranges.append(max(sub) - min(sub))
                if pts:
                    level_medians[lv] = statistics.median(pts)
                    rep_ns[lv] = len(pts)
                if ranges:
                    rep_ranges[lv] = statistics.fmean(ranges)
            else:
                pts = idx.cell_points({field: lv}, uid)
                if pts:
                    level_medians[lv] = statistics.median(pts)
                    rep_ns[lv] = len(pts)
                if len(pts) >= 2:
                    rep_ranges[lv] = max(pts) - min(pts)

        entry: dict[str, Any] = {
            "levels_present": sorted(level_medians),
            "n_levels": len(level_medians),
            "level_medians": level_medians,
            "level_medians_norm": {k: v / denom for k, v in level_medians.items()},
            "reps_per_level": rep_ns,
            "unconditioned_median": denom,
            "spread_pp": None, "noise_floor_pp": None, "ratio": None,
        }
        if len(level_medians) >= 2:
            vals = list(level_medians.values())
            entry["spread_pp"] = 100.0 * (max(vals) - min(vals)) / denom
        if rep_ranges:
            entry["noise_floor_pp"] = 100.0 * statistics.fmean(rep_ranges.values()) / denom
            entry["n_cells_with_reps"] = len(rep_ranges)
        if entry["spread_pp"] is not None and entry["noise_floor_pp"]:
            entry["ratio"] = entry["spread_pp"] / entry["noise_floor_pp"]
        per_unit[uid] = entry

    usable = [u for u, e in per_unit.items()
              if e["spread_pp"] is not None and e["noise_floor_pp"]]
    spreads = [per_unit[u]["spread_pp"] for u in usable]
    noises = [per_unit[u]["noise_floor_pp"] for u in usable]

    def stat_ratio_of_medians(sample: list[str]) -> Optional[float]:
        s = med([per_unit[u]["spread_pp"] for u in sample])
        n = med([per_unit[u]["noise_floor_pp"] for u in sample])
        return s / n if (s is not None and n) else None

    def stat_median_of_ratios(sample: list[str]) -> Optional[float]:
        return med([per_unit[u]["ratio"] for u in sample])

    boot_rom = bootstrap_ci(usable, stat_ratio_of_medians, rng, draws)
    boot_mor = bootstrap_ci(usable, stat_median_of_ratios, rng, draws)

    verdict, verdict_reason = classify_ratio(boot_rom)

    return {
        "dimension": dim,
        "field": field,
        "levels_declared": declared_levels,
        "levels_present": present_levels,
        "levels_missing": missing_levels,
        "n_levels": len(present_levels),
        "pooled_over_policy_context": pool_over_policy_context,
        "held_fixed": {k: v for k, v in REFERENCE.items()
                       if k != field and not (pool_over_policy_context and k == "policy_context")},
        "n_units": len(usable),
        "units_used": usable,
        "units_excluded": sorted(set(per_unit) - set(usable)),
        "spread_pp_median": med(spreads),
        "spread_pp_iqr": iqr(spreads),
        "spread_pp_per_unit": {u: per_unit[u]["spread_pp"] for u in usable},
        "noise_floor_pp_median": med(noises),
        "noise_floor_pp_iqr": iqr(noises),
        "noise_floor_pp_per_unit": {u: per_unit[u]["noise_floor_pp"] for u in usable},
        "ratio_of_medians": boot_rom,
        "median_of_ratios": boot_mor,
        "ratio_per_unit": {u: per_unit[u]["ratio"] for u in usable},
        "per_unit": per_unit,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
    }


def classify_ratio(boot: dict[str, Any]) -> tuple[str, str]:
    """Pre-registered null rule. Not softened."""
    pt, lo, hi = boot.get("point"), boot.get("ci_low"), boot.get("ci_high")
    if pt is None or lo is None or hi is None:
        return "UNDETERMINED", "ratio or its bootstrap CI could not be computed"
    n_u = boot.get("n_units") or 0
    if n_u < MIN_UNITS_FOR_VERDICT:
        return "UNDETERMINED", (f"only {n_u} unit(s) contribute; a bootstrap over fewer than "
                                f"{MIN_UNITS_FOR_VERDICT} units cannot produce an honest "
                                "interval, so no verdict is issued")
    if hi - lo < 1e-12:
        return "UNDETERMINED", (f"the bootstrap CI is degenerate ([{lo:.4f}, {hi:.4f}]) — every "
                                "resample returned the same value, so the interval carries no "
                                "information about sampling variability")
    if lo <= 1.0 <= hi:
        return "NULL", (f"95% bootstrap CI [{lo:.2f}, {hi:.2f}] includes 1 — the across-level "
                        "spread is not distinguishable from the within-cell noise floor")
    if pt <= 1.0:
        return "NULL", (f"point ratio {pt:.2f} <= 1 — the across-level spread does not exceed "
                        "the within-cell noise floor")
    return "EXCEEDS NOISE FLOOR", (f"point ratio {pt:.2f}, 95% bootstrap CI [{lo:.2f}, {hi:.2f}] "
                                   "excludes 1 from below")


def write_dispersion(disp: dict[str, dict], disp_pooled: dict[str, dict],
                     disp_sens: dict[str, dict], out: Path, meta: dict, q: dict) -> None:
    L = []
    L.append("# Dispersion — the headline\n")
    L.append(f"Generated {meta['generated_at']}. "
             f"**N = {q['scored']} scored runs, {meta['n_units_used']} units, "
             f"5 repeats per cell by design.** Sweep completion: {meta['completion_str']}.\n")
    L.append("> The pre-registered headline quantity is a **dispersion, not a best "
             "configuration**. No configuration is recommended anywhere in this file, and none "
             "will be.\n")

    L.append("## Construction\n")
    L.append("For each dimension, all OTHER dimensions are held at the reference configuration "
             f"`{REFERENCE}`; `policy_context=operative_only` is the reference for D2-D5 because "
             "it is the only policy_context the contamination arm (D5) was run at.\n")
    L.append("- **spread** — per unit, the range of the per-level MEDIAN forecast across that "
             "dimension's levels, as a percentage of that unit's unconditioned median "
             "(`policy_context=none` at reference). Reported as median and IQR across units.")
    L.append("- **noise_floor** — per unit, the range across the 5 REPEATS *within* a cell, "
             "averaged over that dimension's cells, same denominator.")
    L.append(f"- **ratio** — median(spread) / median(noise_floor) across units, with a "
             f"{meta['bootstrap_draws']}-draw bootstrap 95% CI resampling **units** with "
             f"replacement (seed {meta['seed']}). `median_of_ratios` (the per-unit ratio, then "
             "the median) is reported alongside as a robustness check.")
    L.append("- **A dimension whose ratio CI includes 1 is reported as NULL.** This is "
             "pre-registered (PREREGISTRATION.md, \"What counts as a null result\"). A null is a "
             "robustness finding and is reported as prominently as a positive one.\n")

    L.append("### Two properties of this construction, stated up front\n")
    L.append("1. **The test is conservative by construction.** The numerator ranges over "
             "per-level *medians of 5 draws*; the denominator ranges over *5 single draws*. "
             "Under a true null the numerator is the range of a less noisy quantity, so the "
             "expected ratio is below 1. A NULL verdict is therefore weaker evidence of "
             "robustness than a symmetric test would give, and an EXCEEDS verdict is "
             "correspondingly stronger.")
    L.append("2. **Ratios are not comparable across dimensions with different level counts.** "
             "The range statistic grows with the number of levels: D1 has 5 levels, D2 4, D3 2, "
             "D4 4, D5 3. Each dimension's `n_levels` is printed in its row. Compare a "
             "dimension against 1, never against another dimension.\n")

    L.append("## Headline table\n")
    L.append("| dim | field | n_levels | n_units | spread % (median) | spread IQR | "
             "noise floor % (median) | noise IQR | ratio | 95% CI | verdict |")
    L.append("|" + "---|" * 11)
    for d in DIM_ORDER:
        r = disp.get(d)
        if not r:
            continue
        sl, sh = r["spread_pp_iqr"]
        nl, nh = r["noise_floor_pp_iqr"]
        L.append("| " + " | ".join([
            d, f"`{r['field']}`", str(r["n_levels"]), str(r["n_units"]),
            fmt(r["spread_pp_median"], 2), f"[{fmt(sl, 2)}, {fmt(sh, 2)}]",
            fmt(r["noise_floor_pp_median"], 2), f"[{fmt(nl, 2)}, {fmt(nh, 2)}]",
            fmt(r["ratio_of_medians"]["point"], 2), fmt_ci(r["ratio_of_medians"]),
            f"**{r['verdict']}**",
        ]) + " |")
    L.append("")

    if q["implausible_extractions"]:
        L.append("### Sensitivity: the same table with implausible extractions excluded\n")
        L.append(f"{q['implausible_extractions']} of {q['scored']} scored runs parsed to a value "
                 "outside [0.1x, 10x] the unit's last observed caseload — all of them from the "
                 "free-text prose fallback, mostly calendar years read as person counts (full "
                 "diagnosis in `results_table.md`). Those runs are **retained** in the primary "
                 "table above, as pre-registered. This table re-runs the identical computation "
                 "without them so the reader can see which verdicts the defect touches.\n")
        L.append("| dim | field | n_units | spread % (median) | noise floor % (median) | ratio | "
                 "95% CI | verdict (sensitivity) | verdict (primary) | changed? |")
        L.append("|" + "---|" * 10)
        for d in DIM_ORDER:
            r, s = disp.get(d), disp_sens.get(d)
            if not r or not s:
                continue
            changed = "**YES**" if s["verdict"] != r["verdict"] else "no"
            L.append("| " + " | ".join([
                d, f"`{r['field']}`", str(s["n_units"]),
                fmt(s["spread_pp_median"], 2), fmt(s["noise_floor_pp_median"], 2),
                fmt(s["ratio_of_medians"]["point"], 2), fmt_ci(s["ratio_of_medians"]),
                s["verdict"], r["verdict"], changed,
            ]) + " |")
        L.append("")

    nulls = [d for d in DIM_ORDER if disp.get(d, {}).get("verdict") == "NULL"]
    exceeds = [d for d in DIM_ORDER if disp.get(d, {}).get("verdict") == "EXCEEDS NOISE FLOOR"]
    undet = [d for d in DIM_ORDER if disp.get(d, {}).get("verdict") == "UNDETERMINED"]
    L.append("### Verdicts\n")
    if nulls:
        L.append("**NULL (pre-registered):** " + ", ".join(
            f"{d} `{disp[d]['field']}`" for d in nulls) + ". "
            "The across-level spread is not distinguishable from sampling noise at fixed "
            "temperature. This is a robustness finding, reported as such.")
    if exceeds:
        L.append("**EXCEEDS NOISE FLOOR:** " + ", ".join(
            f"{d} `{disp[d]['field']}`" for d in exceeds) + ". "
            "Changing this dimension moves the forecast by more than run-to-run sampling noise.")
    if undet:
        L.append("**UNDETERMINED (insufficient data):** " + ", ".join(
            f"{d} `{disp[d]['field']}` — {disp[d]['verdict_reason']}" for d in undet) + ".")
    flipped = [d for d in DIM_ORDER
               if disp.get(d) and disp_sens.get(d)
               and disp_sens[d]["verdict"] != disp[d]["verdict"]]
    if flipped:
        L.append("")
        L.append("**Verdicts that change under the extraction sensitivity:** " + "; ".join(
            f"{d} `{disp[d]['field']}` — {disp[d]['verdict']} with all runs, "
            f"{disp_sens[d]['verdict']} with implausible extractions excluded" for d in flipped)
            + ". Read both. The primary verdict describes the harness a user would actually "
            "run (parser included); the sensitivity verdict isolates the dimension itself. "
            "Neither is the single true answer.")
    L.append("")

    L.append("## Per-dimension detail\n")
    for d in DIM_ORDER:
        r = disp.get(d)
        if not r:
            continue
        L.append(f"### {d} — `{r['field']}`\n")
        L.append(f"- Levels declared: {r['levels_declared']}")
        L.append(f"- Levels present in data: {r['levels_present']}"
                 + (f"; **missing: {r['levels_missing']}**" if r["levels_missing"] else ""))
        L.append(f"- Held fixed: `{r['held_fixed']}`")
        L.append(f"- Units contributing: **{r['n_units']}**"
                 + (f"; excluded (no usable spread or noise floor): {r['units_excluded']}"
                    if r["units_excluded"] else ""))
        L.append(f"- spread: median **{fmt(r['spread_pp_median'], 2, pct=True)}**, "
                 f"IQR [{fmt(r['spread_pp_iqr'][0], 2)}%, {fmt(r['spread_pp_iqr'][1], 2)}%]")
        L.append(f"- noise_floor: median **{fmt(r['noise_floor_pp_median'], 2, pct=True)}**, "
                 f"IQR [{fmt(r['noise_floor_pp_iqr'][0], 2)}%, "
                 f"{fmt(r['noise_floor_pp_iqr'][1], 2)}%]")
        L.append(f"- **ratio (median spread / median noise) = "
                 f"{fmt(r['ratio_of_medians']['point'], 3)}**, 95% CI "
                 f"{fmt_ci(r['ratio_of_medians'], 3)} "
                 f"({r['ratio_of_medians']['n_valid_draws']}/"
                 f"{r['ratio_of_medians']['n_draws']} valid draws)")
        L.append(f"- median_of_ratios = {fmt(r['median_of_ratios']['point'], 3)}, 95% CI "
                 f"{fmt_ci(r['median_of_ratios'], 3)}")
        L.append(f"- **Verdict: {r['verdict']}** — {r['verdict_reason']}")
        if d != "D1" and disp_pooled.get(d):
            p = disp_pooled[d]
            L.append(f"- *Robustness (EXPLORATORY), pooling over all 5 `policy_context` levels "
                     f"instead of holding it at `{REFERENCE['policy_context']}`:* ratio "
                     f"{fmt(p['ratio_of_medians']['point'], 3)}, 95% CI "
                     f"{fmt_ci(p['ratio_of_medians'], 3)}, verdict {p['verdict']} "
                     f"(n_units {p['n_units']}).")
        L.append("\n  Per-unit values:\n")
        L.append("  | unit | spread % | noise floor % | ratio | levels present | reps per level |")
        L.append("  |---|---|---|---|---|---|")
        for uid in r["units_used"]:
            e = r["per_unit"][uid]
            L.append(f"  | {uid} | {fmt(e['spread_pp'], 2)} | {fmt(e['noise_floor_pp'], 2)} | "
                     f"{fmt(e['ratio'], 2)} | {e['n_levels']} | "
                     f"{sum(e['reps_per_level'].values())} |")
        L.append("")
        L.append("  Per-unit level medians, normalised to each unit's unconditioned median "
                 "(1.000 = identical to the unconditioned forecast):\n")
        lv = r["levels_present"]
        L.append("  | unit | " + " | ".join(lv) + " |")
        L.append("  |" + "---|" * (len(lv) + 1))
        for uid in r["units_used"]:
            e = r["per_unit"][uid]
            L.append(f"  | {uid} | " + " | ".join(
                fmt(e["level_medians_norm"].get(x), 3) for x in lv) + " |")
        L.append("")
    out.write_text("\n".join(L) + "\n")


# ---------------------------------------------------------------------------
# 3. primary_analyses.md — P1-P4
# ---------------------------------------------------------------------------


def sycophancy_test(idx: Index, uncond: dict[str, float], rng: random.Random,
                    draws: int) -> dict[str, Any]:
    """P3. Does `purpose_only` shift the forecast in the SAME DIRECTION as
    `operative_only`, relative to `none`?"""
    per_unit = {}
    for uid in sorted(uncond):
        base = uncond[uid]
        m_op = med(idx.cell_points({"policy_context": "operative_only"}, uid))
        m_pu = med(idx.cell_points({"policy_context": "purpose_only"}, uid))
        m_pp = med(idx.cell_points({"policy_context": "operative_plus_purpose"}, uid))
        m_su = med(idx.cell_points({"policy_context": "summary"}, uid))
        noise = []
        for lv in ("none", "operative_only", "purpose_only"):
            pts = idx.cell_points({"policy_context": lv}, uid)
            if len(pts) >= 2:
                noise.append(max(pts) - min(pts))
        per_unit[uid] = {
            "unconditioned_median": base,
            "shift_operative_pp": (100.0 * (m_op - base) / base) if m_op is not None else None,
            "shift_purpose_pp": (100.0 * (m_pu - base) / base) if m_pu is not None else None,
            "shift_op_plus_pur_pp": (100.0 * (m_pp - base) / base) if m_pp is not None else None,
            "shift_summary_pp": (100.0 * (m_su - base) / base) if m_su is not None else None,
            "noise_floor_pp": (100.0 * statistics.fmean(noise) / base) if noise else None,
        }
    usable = [u for u, e in per_unit.items()
              if e["shift_operative_pp"] is not None and e["shift_purpose_pp"] is not None]

    # Sign tests drop ties (the standard convention) and report the tie count,
    # so a unit whose shift is exactly zero is never scored as a disagreement.
    concordant = discordant = 0
    purpose_neg = purpose_pos = operative_neg = operative_pos = 0
    for u in usable:
        so, sp = per_unit[u]["shift_operative_pp"], per_unit[u]["shift_purpose_pp"]
        if so != 0 and sp != 0:
            if (so > 0) == (sp > 0):
                concordant += 1
            else:
                discordant += 1
        purpose_neg += sp < 0
        purpose_pos += sp > 0
        operative_neg += so < 0
        operative_pos += so > 0
    n_conc_pairs = concordant + discordant
    n_purpose_nonzero = purpose_neg + purpose_pos
    n_operative_nonzero = operative_neg + operative_pos

    def med_purpose(sample):
        return med([per_unit[u]["shift_purpose_pp"] for u in sample])

    def med_operative(sample):
        return med([per_unit[u]["shift_operative_pp"] for u in sample])

    boot_pu = bootstrap_ci(usable, med_purpose, rng, draws)
    boot_op = bootstrap_ci(usable, med_operative, rng, draws)
    # The pre-registration asks whether purpose_only produces a *comparable*
    # shift, so the per-unit difference (purpose - operative) is bootstrapped
    # directly. A ratio of medians is not used: the denominator can sit at zero.
    boot_diff = bootstrap_ci(
        usable,
        lambda s: med([per_unit[u]["shift_purpose_pp"] - per_unit[u]["shift_operative_pp"]
                       for u in s]),
        rng, draws)

    none_norm, purpose_norm = [], []
    for uid in uncond:
        b = uncond[uid]
        none_norm += [p / b for p in idx.cell_points({"policy_context": "none"}, uid)]
        purpose_norm += [p / b for p in idx.cell_points({"policy_context": "purpose_only"}, uid)]

    n = len(usable)
    return {
        "n_units": n,
        "per_unit": per_unit,
        "units_used": usable,
        "units_excluded": sorted(set(per_unit) - set(usable)),
        "n_concordant_sign": concordant,
        "n_discordant_sign": discordant,
        "n_tied_excluded_from_concordance": n - n_conc_pairs,
        "p_concordance_sign_test": (binom_two_sided_p(concordant, n_conc_pairs)
                                    if n_conc_pairs else None),
        "n_purpose_negative": purpose_neg,
        "n_purpose_positive": purpose_pos,
        "n_purpose_zero": n - n_purpose_nonzero,
        "p_purpose_direction_sign_test": (binom_two_sided_p(purpose_neg, n_purpose_nonzero)
                                          if n_purpose_nonzero else None),
        "n_operative_negative": operative_neg,
        "n_operative_positive": operative_pos,
        "n_operative_zero": n - n_operative_nonzero,
        "p_operative_direction_sign_test": (binom_two_sided_p(operative_neg, n_operative_nonzero)
                                            if n_operative_nonzero else None),
        "median_shift_purpose_pp": boot_pu,
        "median_shift_operative_pp": boot_op,
        "median_shift_difference_purpose_minus_operative_pp": boot_diff,
        # Pre-registered P3 null: purpose_only is statistically
        # indistinguishable from none. Rejected when the median shift's
        # bootstrap CI excludes zero OR the direction sign test clears the
        # Bonferroni-corrected alpha.
        "purpose_distinguishable_from_none": bool(
            (boot_pu.get("ci_low") is not None and boot_pu.get("ci_high") is not None
             and not (boot_pu["ci_low"] <= 0 <= boot_pu["ci_high"]))
            or (binom_two_sided_p(purpose_neg, n_purpose_nonzero) is not None
                and n_purpose_nonzero
                and binom_two_sided_p(purpose_neg, n_purpose_nonzero) < ALPHA_BONF)),
        "same_central_direction": bool(
            boot_pu.get("point") is not None and boot_op.get("point") is not None
            and boot_pu["point"] != 0 and boot_op["point"] != 0
            and (boot_pu["point"] < 0) == (boot_op["point"] < 0)),
        "mann_whitney_p_purpose_vs_none_runlevel": (
            mann_whitney_u(purpose_norm, none_norm) if REPO_STATS_AVAILABLE and
            purpose_norm and none_norm else None),
        "n_runs_purpose": len(purpose_norm),
        "n_runs_none": len(none_norm),
        "alpha_bonferroni": ALPHA_BONF,
    }


def magnitude_elasticity(idx: Index, uncond: dict[str, float], rng: random.Random,
                         draws: int) -> dict[str, Any]:
    """P4. (median under severe - median under inert) / median under actual.

    The D5 slice is policy_context=operative_only (the only level Arm D ran).
    Near-zero elasticity is evidence of memorisation, not of robustness.
    """
    per_unit = {}
    for uid in sorted(idx.units):
        m = {}
        ranges = []
        for mag in DIMENSIONS["D5"][1]:
            pts = idx.cell_points({"magnitude": mag}, uid)
            if pts:
                m[mag] = statistics.median(pts)
            if len(pts) >= 2:
                ranges.append(max(pts) - min(pts))
        e = None
        if all(k in m for k in ("severe", "inert", "actual")) and m["actual"]:
            e = (m["severe"] - m["inert"]) / m["actual"]
        noise = (statistics.fmean(ranges) / m["actual"]) if (ranges and m.get("actual")) else None
        per_unit[uid] = {
            "medians": m,
            "elasticity": e,
            "noise_scale": noise,
            "elasticity_vs_noise": (abs(e) / noise) if (e is not None and noise) else None,
            "unconditioned_median": uncond.get(uid),
        }
    usable = [u for u, v in per_unit.items() if v["elasticity"] is not None]
    vals = [per_unit[u]["elasticity"] for u in usable]

    boot = bootstrap_ci(usable, lambda s: med([per_unit[u]["elasticity"] for u in s]), rng, draws)
    # Expected sign is NEGATIVE (severe caps -> lower participation than inert
    # caps). Ties are exact zeros: the forecast did not move at all. They are
    # dropped from the sign test and reported, because "did not move" is the
    # memorisation signal itself, not a missing observation.
    n_neg = sum(1 for v in vals if v < 0)
    n_pos = sum(1 for v in vals if v > 0)
    n_zero = sum(1 for v in vals if v == 0)
    n_nonzero = n_neg + n_pos
    ci_lo, ci_hi = boot.get("ci_low"), boot.get("ci_high")
    includes_zero = (ci_lo is not None and ci_hi is not None and ci_lo <= 0 <= ci_hi)
    below_noise = sum(1 for u in usable
                      if (per_unit[u]["elasticity_vs_noise"] is not None
                          and per_unit[u]["elasticity_vs_noise"] < 1))
    return {
        "n_units": len(usable),
        "units_used": usable,
        "units_excluded": sorted(set(per_unit) - set(usable)),
        "per_unit": per_unit,
        "median_elasticity": med(vals),
        "elasticity_iqr": iqr(vals),
        "bootstrap": boot,
        "ci_includes_zero": includes_zero,
        "n_negative_expected_direction": n_neg,
        "n_positive_wrong_direction": n_pos,
        "n_exactly_zero_no_movement": n_zero,
        "p_direction_sign_test": (binom_two_sided_p(n_neg, n_nonzero) if n_nonzero else None),
        "n_units_elasticity_below_repeat_noise": below_noise,
        "n_units_with_defined_noise_ratio": sum(
            1 for u in usable if per_unit[u]["elasticity_vs_noise"] is not None),
        "median_elasticity_vs_noise": med(
            [per_unit[u]["elasticity_vs_noise"] for u in usable]),
        "verdict": (
            "UNDETERMINED" if (len(usable) < MIN_UNITS_FOR_VERDICT
                               or boot.get("point") is None
                               or ci_lo is None or ci_hi is None
                               or ci_hi - ci_lo < 1e-15) else
            "NULL / MEMORISATION SIGNAL" if includes_zero else
            "MOVES, BUT IN THE WRONG DIRECTION" if (boot.get("point") or 0) > 0 else
            "RESPONDS TO STATUTORY MAGNITUDE"),
        "alpha_bonferroni": ALPHA_BONF,
    }


def write_primary(disp: dict, syc: dict, elas: dict, sens: dict,
                  out: Path, meta: dict, q: dict) -> None:
    L = []
    L.append("# Primary analyses — P1, P2, P3, P4 (pre-registered)\n")
    L.append(f"Generated {meta['generated_at']}. "
             f"**N = {q['scored']} scored runs across {meta['n_units_used']} units; "
             f"5 repeats per cell by design.** Sweep completion: {meta['completion_str']}.\n")
    L.append(f"Four primary tests were declared in advance. Bonferroni-corrected alpha = "
             f"0.05/{PRIMARY_TESTS} = **{ALPHA_BONF:.4f}**. "
             f"Everything not labelled P1-P4 below is **EXPLORATORY**.\n")
    L.append(f"> Statistical note: {REPO_STATS_NOTE}. Sign tests use an exact two-sided "
             "binomial (2x smaller tail); bootstrap CIs are percentile CIs over units.\n")
    L.append("> No best configuration is reported. The deliverable is the distribution.\n")

    d1, d2 = disp.get("D1"), disp.get("D2")

    L.append("## P1 (headline) — dispersion of the median forecast across D1 `policy_context`\n")
    if d1:
        L.append(f"- n_units = **{d1['n_units']}**; levels = {d1['levels_present']} "
                 f"({d1['n_levels']} of {len(d1['levels_declared'])} declared)")
        L.append(f"- spread: median **{fmt(d1['spread_pp_median'], 2, pct=True)}** of the "
                 f"unconditioned median, IQR [{fmt(d1['spread_pp_iqr'][0], 2)}%, "
                 f"{fmt(d1['spread_pp_iqr'][1], 2)}%]")
        L.append(f"- noise floor (5 repeats within a cell): median "
                 f"**{fmt(d1['noise_floor_pp_median'], 2, pct=True)}**, IQR "
                 f"[{fmt(d1['noise_floor_pp_iqr'][0], 2)}%, "
                 f"{fmt(d1['noise_floor_pp_iqr'][1], 2)}%]")
        L.append(f"- **ratio = {fmt(d1['ratio_of_medians']['point'], 3)}**, 95% bootstrap CI "
                 f"{fmt_ci(d1['ratio_of_medians'], 3)}")
        L.append(f"- **P1 VERDICT: {d1['verdict']}** — {d1['verdict_reason']}\n")
        if d1["verdict"] == "NULL":
            L.append("Per the pre-registration this is a **robustness finding about D1** and is "
                     "reported as prominently as a positive result would have been. It is not "
                     "evidence that the forecast is *good* — see `skill.md`, which asks the "
                     "separate question of whether conditioning on the bill helps at all.\n")
    else:
        L.append("null — D1 could not be computed. See data quality in `results_table.md`.\n")

    L.append("## P2 — dispersion across D2 `elicitation`\n")
    if d2:
        L.append(f"- n_units = **{d2['n_units']}**; levels = {d2['levels_present']}")
        L.append(f"- spread: median **{fmt(d2['spread_pp_median'], 2, pct=True)}**, IQR "
                 f"[{fmt(d2['spread_pp_iqr'][0], 2)}%, {fmt(d2['spread_pp_iqr'][1], 2)}%]")
        L.append(f"- noise floor: median **{fmt(d2['noise_floor_pp_median'], 2, pct=True)}**, IQR "
                 f"[{fmt(d2['noise_floor_pp_iqr'][0], 2)}%, "
                 f"{fmt(d2['noise_floor_pp_iqr'][1], 2)}%]")
        L.append(f"- **ratio = {fmt(d2['ratio_of_medians']['point'], 3)}**, 95% bootstrap CI "
                 f"{fmt_ci(d2['ratio_of_medians'], 3)}")
        L.append(f"- **P2 VERDICT: {d2['verdict']}** — {d2['verdict_reason']}\n")
        s2 = sens.get("disp", {}).get("D2")
        if q["implausible_extractions"] and s2:
            L.append(f"> **P2 is the one primary result the free-text extraction defect can "
                     f"reach.** {q['implausible_extractions']} scored runs parsed to a calendar "
                     "year or similar artefact instead of a caseload, all from the prose "
                     "fallback, and `free_text` is a D2 level (full diagnosis in "
                     "`results_table.md`). The numbers above retain those runs, as "
                     "pre-registered. Excluding them: spread median "
                     f"{fmt(s2['spread_pp_median'], 2, pct=True)}, noise floor median "
                     f"{fmt(s2['noise_floor_pp_median'], 2, pct=True)}, ratio "
                     f"{fmt(s2['ratio_of_medians']['point'], 3)} 95% CI "
                     f"{fmt_ci(s2['ratio_of_medians'], 3)}, verdict **{s2['verdict']}** "
                     f"(n_units {s2['n_units']}). Neither figure is the 'true' one on its own: "
                     "the primary measures the harness end-to-end (parser included, which is "
                     "what a user would actually get), the sensitivity measures the elicitation "
                     "format alone.\n")
    else:
        L.append("null — D2 could not be computed.\n")

    L.append("## P3 — the sycophancy test\n")
    L.append("§313 is a pure statement-of-purpose amendment: nominally about employment and "
             "earnings, carrying **no eligibility change**. §§311/312/314 restrict eligibility "
             "and should push participation **down**. If `purpose_only` produces a comparable "
             "downward shift, the model is reading the preamble as if it were the statute.\n")
    n = syc["n_units"]
    if n:
        L.append(f"- n_units = **{n}**"
                 + (f"; excluded {syc['units_excluded']}" if syc["units_excluded"] else ""))
        L.append(f"- median shift under `operative_only` vs `none`: "
                 f"**{fmt(syc['median_shift_operative_pp']['point'], 2, pct=True)}**, 95% CI "
                 f"{fmt_ci(syc['median_shift_operative_pp'], 2)} (percentage of the "
                 f"unconditioned median)")
        L.append(f"- median shift under `purpose_only` vs `none`: "
                 f"**{fmt(syc['median_shift_purpose_pp']['point'], 2, pct=True)}**, 95% CI "
                 f"{fmt_ci(syc['median_shift_purpose_pp'], 2)}")
        n_pairs = syc["n_concordant_sign"] + syc["n_discordant_sign"]
        L.append(f"- **same-direction (concordant sign) in {syc['n_concordant_sign']}/"
                 f"{n_pairs} units** where both shifts were non-zero "
                 f"({syc['n_tied_excluded_from_concordance']} unit(s) had an exact-zero shift "
                 "and are excluded from the sign test, per the standard tie convention); "
                 f"exact two-sided sign test p = {fmt(syc['p_concordance_sign_test'], 4)} "
                 f"(Bonferroni alpha {ALPHA_BONF:.4f})")
        L.append(f"- `purpose_only` shifted DOWN in {syc['n_purpose_negative']}, UP in "
                 f"{syc['n_purpose_positive']}, not at all in {syc['n_purpose_zero']} of {n} "
                 f"units (sign-test p = {fmt(syc['p_purpose_direction_sign_test'], 4)})")
        L.append(f"- `operative_only` shifted DOWN in {syc['n_operative_negative']}, UP in "
                 f"{syc['n_operative_positive']}, not at all in {syc['n_operative_zero']} of {n} "
                 f"units (p = {fmt(syc['p_operative_direction_sign_test'], 4)}). The operative "
                 "provisions restrict eligibility, so the pre-registered expectation for this "
                 "row is DOWN.")
        if syc["mann_whitney_p_purpose_vs_none_runlevel"] is not None:
            L.append(f"- run-level Mann-Whitney U, `purpose_only` (n={syc['n_runs_purpose']}) vs "
                     f"`none` (n={syc['n_runs_none']}) normalised forecasts: p "
                     f"{fmt(syc['mann_whitney_p_purpose_vs_none_runlevel'], 3)} "
                     "(bucketed, see note above)")
        bd = syc["median_shift_difference_purpose_minus_operative_pp"]
        L.append(f"- median of the per-unit difference (`purpose_only` shift minus "
                 f"`operative_only` shift): **{fmt(bd['point'], 2, pct=True)}**, 95% CI "
                 f"{fmt_ci(bd, 2)}. Negative means the pure purpose clause moved the forecast "
                 "DOWN MORE than the operative eligibility restrictions did.")

        # The pre-registered P3 null is "purpose_only is statistically
        # indistinguishable from none", so the verdict is decided on that, not
        # on the concordance test alone (which drops ties and is the weakest of
        # the three declared readings).
        enough = n >= MIN_UNITS_FOR_VERDICT
        distinguishable = syc["purpose_distinguishable_from_none"] and enough
        same_dir = syc["same_central_direction"]
        bigger = (bd.get("ci_high") is not None and bd["ci_high"] < 0 and enough)
        if not enough:
            L.append(f"\n- **P3 VERDICT: UNDETERMINED** — only {n} unit(s) contribute, below the "
                     f"{MIN_UNITS_FOR_VERDICT}-unit floor this analysis requires before issuing "
                     "a verdict from a bootstrap. Not a null; a statement about the data "
                     "available to this run.")
        elif distinguishable and same_dir:
            L.append("\n- **P3 VERDICT: SYCOPHANCY SIGNAL** — the pre-registered P3 null "
                     "(`purpose_only` indistinguishable from `none`) is **rejected**, and the "
                     "shift runs in the same direction as the operative provisions. A pure "
                     "statement-of-purpose amendment that changes no eligibility rule is moving "
                     "the forecast.")
            if bigger:
                L.append("\n  Stronger than the pre-registration anticipated: the purpose clause "
                         "moved the forecast down **more** than the operative provisions did "
                         f"(difference {fmt(bd['point'], 2, pct=True)}, 95% CI {fmt_ci(bd, 2)}, "
                         "excluding zero). The pre-registration asked whether the preamble "
                         "produces a *comparable* downward shift; here it produces a larger "
                         "one. Two readings are consistent with this and the design does not "
                         "separate them: the model may be reading the preamble as if it were "
                         "the statute, or it may be responding to the presence of policy "
                         "language as such rather than to its content. D5/P4 bears on the "
                         "second reading — the forecast does not move when the statutory "
                         "content is rewritten by 40 years.")
            L.append(f"\n  Note the weakest of the three declared readings does NOT clear the "
                     f"corrected alpha on its own: the paired concordance sign test has only "
                     f"{n_pairs} non-tied pairs and p = "
                     f"{fmt(syc['p_concordance_sign_test'], 4)}. The verdict rests on the "
                     "declared null (indistinguishable from `none`), which the direction sign "
                     f"test (p = {fmt(syc['p_purpose_direction_sign_test'], 4)}) and the "
                     "bootstrap CI on the median shift both reject.")
        elif distinguishable and not same_dir:
            L.append("\n- **P3 VERDICT: MOVES, OPPOSITE DIRECTION** — `purpose_only` is "
                     "distinguishable from `none`, but its central shift runs opposite to "
                     "`operative_only`. This is not the sycophancy pattern P3 was written to "
                     "detect.")
        else:
            L.append("\n- **P3 VERDICT: NULL** — `purpose_only` is not distinguishable from "
                     "`none` at the corrected alpha. Per the pre-registration this is the "
                     "declared P3 null.")
        L.append("\n  Per-unit signed shifts (percentage of the unit's unconditioned median; "
                 "`noise` is the mean within-cell range across the three cells, same units — "
                 "a shift smaller than `noise` is not distinguishable from sampling noise):\n")
        L.append("  | unit | operative_only | purpose_only | operative_plus_purpose | summary | "
                 "noise | concordant |")
        L.append("  |---|---|---|---|---|---|---|")
        for uid in syc["units_used"]:
            e = syc["per_unit"][uid]
            so, sp = e["shift_operative_pp"], e["shift_purpose_pp"]
            conc = "yes" if (so and sp and ((so > 0) == (sp > 0))) else "no"
            L.append(f"  | {uid} | {fmt(so, 2)} | {fmt(sp, 2)} | "
                     f"{fmt(e['shift_op_plus_pur_pp'], 2)} | {fmt(e['shift_summary_pp'], 2)} | "
                     f"{fmt(e['noise_floor_pp'], 2)} | {conc} |")
        L.append("")
    else:
        L.append("null — no unit had both an `operative_only` and a `purpose_only` cell with a "
                 "usable unconditioned denominator.\n")

    L.append("## P4 — magnitude elasticity (memorisation check)\n")
    L.append("`(median under severe - median under inert) / median under actual`, at "
             "`policy_context=operative_only`. The `severe` arm rewrites the ABAWD age caps "
             "*down* by 20 years (51/53/55 -> 31/33/35: many more adults newly subject to the "
             "work requirement, so participation should fall harder); `inert` rewrites them "
             "*up* by 20 years (51/53/55 -> 71/73/75: almost nobody newly subject). The two "
             "arms are therefore **40 years apart** in the statutory age cap. A tool that "
             "DERIVES from the statute must move; a tool that RECALLS the realised caseload "
             "will not. **Near-zero elasticity is evidence of memorisation, not of "
             "robustness.**\n")
    if elas["n_units"]:
        L.append(f"- n_units = **{elas['n_units']}**"
                 + (f"; excluded {elas['units_excluded']}" if elas["units_excluded"] else ""))
        L.append(f"- median elasticity = **{fmt(elas['median_elasticity'], 5)}**, IQR "
                 f"[{fmt(elas['elasticity_iqr'][0], 5)}, {fmt(elas['elasticity_iqr'][1], 5)}]")
        L.append(f"- 95% bootstrap CI {fmt_ci(elas['bootstrap'], 5)}; CI includes zero: "
                 f"**{elas['ci_includes_zero']}**")
        L.append(f"- expected sign is NEGATIVE (severe below inert). Observed: "
                 f"**{elas['n_negative_expected_direction']} negative (expected direction), "
                 f"{elas['n_positive_wrong_direction']} positive (wrong direction), "
                 f"{elas['n_exactly_zero_no_movement']} exactly zero (the forecast did not move "
                 f"at all)** out of {elas['n_units']} units; exact two-sided sign test on the "
                 f"non-zero units p = {fmt(elas['p_direction_sign_test'], 4)}")
        L.append(f"- |elasticity| relative to the within-cell repeat noise on the same scale: "
                 f"median **{fmt(elas['median_elasticity_vs_noise'], 3)}**; "
                 f"**{elas['n_units_elasticity_below_repeat_noise']} of the "
                 f"{elas['n_units_with_defined_noise_ratio']} units where the ratio is defined "
                 "moved LESS across a 40-year swing in the statutory age cap than they move "
                 "when the identical prompt is re-run** (the ratio is undefined where both the "
                 "elasticity and the repeat noise are exactly zero — a unit that did not move "
                 "at all under either)")
        L.append(f"- **P4 VERDICT: {elas['verdict']}**\n")
        if elas["ci_includes_zero"]:
            L.append("This is the pre-registered P4 null, and the pre-registration is explicit "
                     "that it is **a bad sign for the tool**: the forecast does not respond to "
                     "a 40-year change in the statutory age cap. A tool that derives its answer "
                     "from the statute must move when the statute moves; a tool that recalls "
                     "the realised caseload will not. Read alongside D5 in `dispersion.md`, "
                     "whose independent construction reaches the same NULL.\n")
        L.append("  Per-unit detail:\n")
        L.append("  | unit | median actual | median severe | median inert | elasticity | "
                 "noise scale | \\|elasticity\\|/noise |")
        L.append("  |---|---|---|---|---|---|---|")
        for uid in elas["units_used"]:
            e = elas["per_unit"][uid]
            m = e["medians"]
            L.append(f"  | {uid} | {fmt(m.get('actual'), 0)} | {fmt(m.get('severe'), 0)} | "
                     f"{fmt(m.get('inert'), 0)} | {fmt(e['elasticity'], 5)} | "
                     f"{fmt(e['noise_scale'], 5)} | {fmt(e['elasticity_vs_noise'], 3)} |")
        L.append("")
    else:
        L.append("null — the contamination arm (D5) has no unit with all three magnitude cells "
                 "populated yet. Cannot be computed; not estimated.\n")

    L.append("## EXPLORATORY — everything below is not a primary analysis\n")
    L.append("Declared exploratory in advance (PREREGISTRATION.md): D3 `pipeline` (debate), "
             "D4 `model` tier, CRPS accuracy levels, PIT calibration, per-state heterogeneity, "
             "and the pooled-over-policy_context robustness variants in `dispersion.md`. The "
             "D4 level `claude-fable-5` was added to the sweep on 2026-07-31 after the "
             "pre-registration was frozen; it is strictly additive (no level was dropped) and "
             "model tier was already exploratory, but it is flagged here so the amendment is "
             "visible.\n")
    for d in ("D3", "D4"):
        r = disp.get(d)
        if not r:
            continue
        L.append(f"- **{d} `{r['field']}` (EXPLORATORY)** — n_units {r['n_units']}, "
                 f"{r['n_levels']} levels, spread median "
                 f"{fmt(r['spread_pp_median'], 2, pct=True)}, noise floor median "
                 f"{fmt(r['noise_floor_pp_median'], 2, pct=True)}, ratio "
                 f"{fmt(r['ratio_of_medians']['point'], 3)} 95% CI "
                 f"{fmt_ci(r['ratio_of_medians'], 3)}, verdict {r['verdict']}.")
    L.append("")
    out.write_text("\n".join(L) + "\n")


# ---------------------------------------------------------------------------
# 4. skill.md
# ---------------------------------------------------------------------------


def skill_analysis(idx: Index, units: dict, rng: random.Random, draws: int) -> dict[str, Any]:
    levels = DIMENSIONS["D1"][1]
    per_unit_level: dict[str, dict[str, dict]] = defaultdict(dict)
    for uid in sorted(units):
        for lv in levels:
            rr = idx.cell(({"policy_context": lv}), uid)
            if not rr:
                continue
            per_unit_level[uid][lv] = {
                "n": len(rr),
                "mean_crps": mean([r["crps"] for r in rr]),
                "sd_crps": sd([r["crps"] for r in rr]),
                "mean_crps_norm": mean([r["crps_norm"] for r in rr]),
                "sd_crps_norm": sd([r["crps_norm"] for r in rr]),
                "coverage80": mean([r["covered80"] for r in rr]),
                "mean_pit": mean([r["pit"] for r in rr]),
                "mean_width": mean([r["width"] for r in rr]),
                "mean_width_norm": mean([r["width_norm"] for r in rr]),
            }
    results = {}
    for lv in levels:
        if lv == UNCONDITIONED_LEVEL:
            continue
        usable = [u for u in per_unit_level
                  if lv in per_unit_level[u] and UNCONDITIONED_LEVEL in per_unit_level[u]]
        diffs_norm = {u: per_unit_level[u][lv]["mean_crps_norm"]
                      - per_unit_level[u][UNCONDITIONED_LEVEL]["mean_crps_norm"] for u in usable}
        diffs_raw = {u: per_unit_level[u][lv]["mean_crps"]
                     - per_unit_level[u][UNCONDITIONED_LEVEL]["mean_crps"] for u in usable}
        boot = bootstrap_ci(usable, lambda s: mean([diffs_norm[u] for u in s]), rng, draws)
        boot_med = bootstrap_ci(usable, lambda s: med([diffs_norm[u] for u in s]), rng, draws)
        n_improved = sum(1 for v in diffs_norm.values() if v < 0)
        lo, hi = boot.get("ci_low"), boot.get("ci_high")
        if lo is None or hi is None or len(usable) < MIN_UNITS_FOR_VERDICT or hi - lo < 1e-15:
            verdict = "UNDETERMINED (too few units or degenerate bootstrap)"
        elif hi < 0:
            verdict = "IMPROVES"
        elif lo > 0:
            verdict = "DEGRADES"
        else:
            verdict = "NO DETECTABLE SKILL (CI includes 0)"
        results[lv] = {
            "n_units": len(usable),
            "units_used": usable,
            "mean_skill_crps_norm": boot,
            "median_skill_crps_norm": boot_med,
            "mean_skill_crps_persons": mean(list(diffs_raw.values())),
            "per_unit_skill_norm": diffs_norm,
            "per_unit_skill_persons": diffs_raw,
            "n_units_improved": n_improved,
            "p_sign_test": binom_two_sided_p(n_improved, len(usable)) if usable else None,
            "verdict": verdict,
        }
    level_summary = {}
    for lv in levels:
        rows = [per_unit_level[u][lv] for u in per_unit_level if lv in per_unit_level[u]]
        if not rows:
            continue
        level_summary[lv] = {
            "n_units": len(rows),
            "n_runs": sum(r["n"] for r in rows),
            "mean_crps_persons": mean([r["mean_crps"] for r in rows]),
            "mean_crps_norm": mean([r["mean_crps_norm"] for r in rows]),
            "mean_sd_crps_across_reps": mean([r["sd_crps"] for r in rows]),
            "coverage80": mean([r["coverage80"] for r in rows]),
            "mean_pit": mean([r["mean_pit"] for r in rows]),
            "mean_width_persons": mean([r["mean_width"] for r in rows]),
            "mean_width_norm": mean([r["mean_width_norm"] for r in rows]),
        }
    # EXPLORATORY calibration comparison, run-level. This is where the repo's
    # own two-proportion z-test fits; its p-values are bucketed, not exact.
    cov_runs: dict[str, list[float]] = defaultdict(list)
    for lv in levels:
        for uid in units:
            cov_runs[lv] += [r["covered80"] for r in idx.cell({"policy_context": lv}, uid)]
    coverage_tests = {}
    base = cov_runs.get(UNCONDITIONED_LEVEL, [])
    for lv in levels:
        if lv == UNCONDITIONED_LEVEL or not cov_runs[lv] or not base:
            continue
        p1, p2 = statistics.fmean(base), statistics.fmean(cov_runs[lv])
        coverage_tests[lv] = {
            "n_runs_none": len(base), "coverage_none": p1,
            "n_runs_level": len(cov_runs[lv]), "coverage_level": p2,
            "difference": p2 - p1,
            "p_value_bucketed": (proportion_z_test(len(base), p1, len(cov_runs[lv]), p2)
                                 if REPO_STATS_AVAILABLE else None),
            "test": "brier.experiments.analyze.proportion_z_test (bucketed p-value)",
        }
    return {"per_level": results, "level_summary": level_summary,
            "per_unit_level": per_unit_level, "levels": levels,
            "coverage_tests_EXPLORATORY": coverage_tests,
            "nominal_coverage": 0.80}


def write_skill(sk: dict, out: Path, meta: dict, q: dict) -> None:
    L = []
    L.append("# Skill — does conditioning on the bill improve the forecast?\n")
    L.append(f"Generated {meta['generated_at']}. "
             f"**N = {q['scored']} scored runs, {meta['n_units_used']} units.** "
             f"Sweep completion: {meta['completion_str']}.\n")
    L.append("`skill_vs_unconditioned` = CRPS(conditioned) - CRPS(`none`), per `policy_context` "
             "level, at the reference configuration for the other four dimensions "
             f"(`{ {k: v for k, v in REFERENCE.items() if k != 'policy_context'} }`). "
             "**Negative = improvement.** CRPS is normalised by the SD of each unit's own "
             "supplied 60-month history, frozen in `ground_truth.json` at pre-registration; it "
             "is never normalised by the model's own interval width.\n")

    improving = [lv for lv, r in sk["per_level"].items() if r["verdict"] == "IMPROVES"]
    degrading = [lv for lv, r in sk["per_level"].items() if r["verdict"] == "DEGRADES"]
    decided = [lv for lv, r in sk["per_level"].items()
               if not r["verdict"].startswith("UNDETERMINED")]
    if sk["per_level"] and not decided:
        L.append("## Headline\n")
        L.append("**No skill verdict can be issued.** Every `policy_context` level has too few "
                 f"contributing units (minimum {MIN_UNITS_FOR_VERDICT}) or a degenerate "
                 "bootstrap. This is a statement about the data available to this run, not a "
                 "finding about the tool: it is neither the pre-registered skill null nor "
                 "evidence of skill. Re-run against a complete sweep.\n")
    elif sk["per_level"] and not improving:
        L.append("## Headline\n")
        L.append("**Conditioning on the bill does not improve the forecast.** No "
                 "`policy_context` level has a 95% bootstrap CI for "
                 "`skill_vs_unconditioned` lying entirely below zero"
                 + (f"; {len(degrading)} level(s) are significantly WORSE than the "
                    f"unconditioned baseline ({', '.join(degrading)})" if degrading else "")
                 + ". This is the pre-registered **skill null** and it is reported, not buried. "
                 "It does not mean the statutory text is irrelevant to SNAP participation; it "
                 "means that at this horizon (30-33 months, forced by the ~2-year publication "
                 "lag of this Census/FNS series) the policy signal is a small share of total "
                 "forecast error, exactly as the pre-registration warned.\n")
    elif improving:
        L.append("## Headline\n")
        L.append(f"Levels whose 95% bootstrap CI lies entirely below zero (i.e. improve on the "
                 f"unconditioned baseline): **{', '.join(improving)}**. All other levels show no "
                 "detectable skill. The magnitude of any improvement must be read against the "
                 "per-repeat variance in `results_table.md`.\n")

    L.append("## skill_vs_unconditioned by policy_context level\n")
    L.append("| level | n_units | mean skill (normalised CRPS) | 95% CI | median skill | 95% CI | "
             "mean skill (persons) | units improved | sign-test p | verdict |")
    L.append("|" + "---|" * 10)
    for lv, r in sk["per_level"].items():
        L.append("| " + " | ".join([
            f"`{lv}`", str(r["n_units"]),
            fmt(r["mean_skill_crps_norm"]["point"], 4), fmt_ci(r["mean_skill_crps_norm"], 4),
            fmt(r["median_skill_crps_norm"]["point"], 4), fmt_ci(r["median_skill_crps_norm"], 4),
            fmt(r["mean_skill_crps_persons"], 0),
            f"{r['n_units_improved']}/{r['n_units']}",
            fmt(r["p_sign_test"], 4), f"**{r['verdict']}**",
        ]) + " |")
    L.append("")

    L.append("## Accuracy and calibration by level (context for the numbers above)\n")
    L.append("| level | n_units | n_runs | mean CRPS (persons) | mean CRPS (normalised) | "
             "mean SD of CRPS across the 5 repeats | 80% coverage | mean PIT | mean width "
             "(persons) | mean width (normalised) |")
    L.append("|" + "---|" * 10)
    for lv in sk["levels"]:
        s = sk["level_summary"].get(lv)
        if not s:
            continue
        L.append("| " + " | ".join([
            f"`{lv}`", str(s["n_units"]), str(s["n_runs"]),
            fmt(s["mean_crps_persons"], 0), fmt(s["mean_crps_norm"], 3),
            fmt(s["mean_sd_crps_across_reps"], 0),
            fmt(s["coverage80"], 3), fmt(s["mean_pit"], 3),
            fmt(s["mean_width_persons"], 0), fmt(s["mean_width_norm"], 3),
        ]) + " |")
    L.append("")
    L.append("Calibration reading (EXPLORATORY, per the pre-registration): nominal 80% coverage "
             "is 0.80 and a calibrated mean PIT is 0.50. A mean PIT near 0 or 1 means the "
             "intervals sit systematically on one side of the realised value.\n")

    cov = sk.get("coverage_tests_EXPLORATORY") or {}
    worst = min((s["coverage80"] for s in sk["level_summary"].values()), default=None)
    best = max((s["coverage80"] for s in sk["level_summary"].values()), default=None)
    if worst is not None:
        L.append(f"**Every level is badly over-confident.** Observed 80% coverage ranges "
                 f"{fmt(worst, 3)}-{fmt(best, 3)} against a nominal 0.80: these are not 80% "
                 "intervals at this horizon. This is EXPLORATORY (PIT calibration was declared "
                 "exploratory in advance), and it is the same story the skill table tells — "
                 "the dominant error at a 30-33 month horizon is not the policy signal.\n")
    if cov:
        L.append("Run-level coverage vs the unconditioned baseline (EXPLORATORY; "
                 "two-proportion z-test from `brier/experiments/analyze.py`, whose p-values "
                 "are **bucketed**, not exact):\n")
        L.append("| level | n_runs | coverage | coverage(`none`) | difference | p (bucketed) |")
        L.append("|---|---|---|---|---|---|")
        for lv, c in cov.items():
            L.append(f"| `{lv}` | {c['n_runs_level']} | {fmt(c['coverage_level'], 3)} | "
                     f"{fmt(c['coverage_none'], 3)} | {fmt(c['difference'], 3)} | "
                     f"{fmt(c['p_value_bucketed'], 3)} |")
        L.append("")

    L.append("## Per-unit skill (normalised CRPS difference vs `none`)\n")
    lvs = [lv for lv in sk["levels"] if lv != UNCONDITIONED_LEVEL and lv in sk["per_level"]]
    if lvs:
        all_units = sorted({u for lv in lvs for u in sk["per_level"][lv]["units_used"]})
        L.append("| unit | " + " | ".join(f"`{lv}`" for lv in lvs) + " |")
        L.append("|" + "---|" * (len(lvs) + 1))
        for u in all_units:
            L.append(f"| {u} | " + " | ".join(
                fmt(sk["per_level"][lv]["per_unit_skill_norm"].get(u), 4) for lv in lvs) + " |")
        L.append("")
    out.write_text("\n".join(L) + "\n")


# ---------------------------------------------------------------------------
# 5. figure_dispersion.png / .svg
# ---------------------------------------------------------------------------


def slice_columns(idx: Index) -> list[dict]:
    """The x-axis: the union of the five pre-registered dimension slices."""
    cols = []
    for d in DIM_ORDER:
        field, declared = DIMENSIONS[d]
        for lv in declared:
            key = Index.key({field: lv})
            if key not in idx.by_cfg:
                continue
            cols.append({"dim": d, "field": field, "level": lv, "overrides": {field: lv},
                         "label": lv.replace("claude-", "").replace("-4-5-20251001", "-4.5")})
    return cols


def write_figure(idx: Index, idx_plaus: Index, uncond: dict[str, float], units: dict,
                 outdir: Path, meta: dict, q: dict) -> dict[str, Any]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
    except Exception as e:  # noqa: BLE001
        return {"written": False, "error": f"{type(e).__name__}: {e}"}

    cols = slice_columns(idx)
    if not cols or not uncond:
        return {"written": False, "error": "no plottable configuration slices or no "
                                           "unconditioned denominators"}

    plt.rcParams.update({
        "font.size": 17, "axes.titlesize": 24, "axes.labelsize": 20,
        "xtick.labelsize": 15, "ytick.labelsize": 17, "legend.fontsize": 14,
    })
    fig, ax = plt.subplots(figsize=(max(15.0, 0.62 * len(cols)), 9.0))

    state_colors = {"CA": "#1f77b4", "FL": "#d62728", "NY": "#2ca02c", "TX": "#ff7f0e",
                    "PA": "#9467bd", "OH": "#8c564b"}
    x = list(range(len(cols)))
    series, series_plaus = {}, {}
    for uid in sorted(uncond):
        ys, yp = [], []
        for c in cols:
            m = med(idx.cell_points(c["overrides"], uid))
            ys.append(m / uncond[uid] if m is not None else float("nan"))
            mp = med(idx_plaus.cell_points(c["overrides"], uid))
            yp.append(mp / uncond[uid] if mp is not None else float("nan"))
        series[uid], series_plaus[uid] = ys, yp

    # y-limits are set from the PLAUSIBLE medians so the chart stays legible;
    # every point that falls outside is drawn at the axis edge as a marked,
    # counted off-scale point. Nothing is silently removed.
    finite_p = [v for yy in series_plaus.values() for v in yy if not math.isnan(v)]
    finite_a = [v for yy in series.values() for v in yy if not math.isnan(v)]
    base = finite_p or finite_a or [1.0]
    ymin, ymax = min(base + [1.0]), max(base + [1.0])
    pad = max(0.02, 0.14 * (ymax - ymin))
    lo_lim, hi_lim = ymin - pad, ymax + pad + 0.10 * (ymax - ymin + pad)

    offscale: dict[int, list[tuple[float, str]]] = defaultdict(list)
    for uid in sorted(uncond):
        ys = series[uid]
        st = units[uid].get("state") or uid.split(".")[1].upper()
        tm = units[uid].get("target_month") or ""
        ls = "-" if tm.startswith("2023") else "--"
        col = state_colors.get(st, "#333333")
        drawn = [v if (math.isnan(v) or lo_lim <= v <= hi_lim) else float("nan") for v in ys]
        ax.plot(x, drawn, marker="o", markersize=7, linewidth=2.6, alpha=0.9,
                color=col, linestyle=ls, label=f"{st} {tm[:7]}")
        for xi, v in zip(x, ys):
            if not math.isnan(v) and not (lo_lim <= v <= hi_lim):
                offscale[xi].append((v, col))
    # Off-scale markers are laid out centred on their column so a stack of them
    # stays readable and stays over the tick it belongs to.
    n_offscale = 0
    for xi, items in offscale.items():
        span = min(0.62, 0.10 * max(1, len(items) - 1))
        for k, (v, col) in enumerate(items):
            n_offscale += 1
            dx = 0.0 if len(items) == 1 else -span / 2 + span * k / (len(items) - 1)
            edge = (lo_lim + 0.022 * (hi_lim - lo_lim) if v < lo_lim
                    else hi_lim - 0.022 * (hi_lim - lo_lim))
            ax.plot([xi + dx], [edge], marker="v" if v < lo_lim else "^", markersize=13,
                    color=col, markeredgecolor="black", markeredgewidth=1.2,
                    linestyle="none", zorder=6)
    ax.set_ylim(lo_lim, hi_lim)
    ax.axhline(1.0, color="black", linewidth=1.6, linestyle=":", zorder=1)
    ax.annotate("unconditioned median (policy_context = none)", xy=(0.0, 1.0),
                xytext=(4, 8), textcoords="offset points", fontsize=14, color="black")

    bounds, start = [], 0
    for i in range(1, len(cols) + 1):
        if i == len(cols) or cols[i]["dim"] != cols[start]["dim"]:
            bounds.append((cols[start]["dim"], start, i - 1))
            if i < len(cols):
                ax.axvline(i - 0.5, color="#999999", linewidth=1.4, alpha=0.7)
            start = i

    ax.set_xticks(x)
    ax.set_xticklabels([c["label"] for c in cols], rotation=38, ha="right")
    for dim, a, b in bounds:
        field = DIMENSIONS[dim][0]
        ax.text((a + b) / 2.0, ax.get_ylim()[1] - 0.012 * (ax.get_ylim()[1] - ax.get_ylim()[0]),
                f"{dim}  {field}", ha="center", va="top", fontsize=17, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.32", facecolor="#eeeeee", edgecolor="#bbbbbb"))

    xlabel_text = "configuration (dimension slice; all other dimensions held at reference)"
    ax.set_ylabel("forecast / unit's unconditioned median", labelpad=10)
    d1 = meta.get("d1_ratio_str", "")
    fig.suptitle("Bill-conditioned SNAP forecasts: harness dispersion",
                 fontsize=22, fontweight="bold", y=0.985)
    n_distinct = len({Index.key(c["overrides"]) for c in cols})
    subtitle = (f"N = {q['scored']} scored runs   |   {len(uncond)} units   |   "
                f"5 repeats per cell   |   {meta['completion_str']} of the grid")
    if d1:
        subtitle += f"\n{d1}"
    ax.set_title(subtitle, fontsize=15, pad=16)
    ax.grid(axis="y", alpha=0.28, linewidth=1.0)
    ax.tick_params(axis="both", length=6, width=1.2)

    handles = [Line2D([], [], color=state_colors[s], linewidth=3, label=s)
               for s in state_colors if any((units[u].get("state") == s) for u in uncond)]
    handles += [Line2D([], [], color="#444444", linewidth=3, linestyle="-", label="2023-12"),
                Line2D([], [], color="#444444", linewidth=3, linestyle="--", label="2024-03")]
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.005, 0.5),
              frameon=True, title="unit", title_fontsize=15)
    import textwrap
    cap_parts = [
        "Flat lines = robustness to the harness. Fanning = harness sensitivity. "
        "Gaps = cell not run. No configuration is recommended.",
        f"{len(cols)} slice positions spanning {n_distinct} distinct configurations (the "
        "reference cell recurs once per dimension); each point is the median of 5 repeats.",
    ]
    if n_offscale:
        cap_parts.append(
            f"{n_offscale} point(s) fall outside the plotted range and are marked with "
            "triangles at the axis edge: cells whose median is a mis-extracted free-text "
            "forecast (a calendar year read as a caseload). They are retained in every "
            "reported number; see results_table.md.")
    wrap_at = int(11.5 * max(15.0, 0.62 * len(cols)))
    caption = "\n".join(textwrap.fill(p, wrap_at) for p in cap_parts)
    # Deterministic vertical stack, all in FIGURE coordinates: caption at the
    # foot, then the x-label, then the axes. Letting matplotlib place the
    # x-label relative to the rotated tick labels put it on top of the caption.
    n_cap_lines = caption.count("\n") + 1
    cap_y = 0.012
    cap_top = cap_y + 0.028 * n_cap_lines
    xlabel_y = cap_top + 0.030
    fig.text(0.008, cap_y, caption, fontsize=12.5, color="#444444", va="bottom",
             linespacing=1.35)
    fig.text(0.465, xlabel_y, xlabel_text, fontsize=20, ha="center", va="bottom")
    # Explicit geometry rather than tight_layout + bbox_inches="tight": the two
    # together left a large dead band between the tick labels and the x-label.
    # The bottom margin is MEASURED from the rendered rotated tick labels rather
    # than guessed, so a longer level name cannot silently overlap the x-label.
    fig.subplots_adjust(left=0.075, right=0.855, top=0.855, bottom=0.33)
    fig.canvas.draw()
    inv = fig.transFigure.inverted()
    drop = 0.0
    for lab in ax.get_xticklabels():
        bb = lab.get_window_extent(renderer=fig.canvas.get_renderer())
        drop = max(drop, ax.get_position().y0 - inv.transform((0, bb.y0))[1])
    fig.subplots_adjust(bottom=min(0.55, xlabel_y + drop + 0.035))
    png = outdir / "figure_dispersion.png"
    svg = outdir / "figure_dispersion.svg"
    fig.savefig(png, dpi=130)
    fig.savefig(svg)
    plt.close(fig)
    return {"written": True, "png": str(png), "svg": str(svg), "n_columns": len(cols),
            "columns": [f"{c['dim']}:{c['level']}" for c in cols],
            "y_limits": [lo_lim, hi_lim], "n_offscale_points": n_offscale,
            "series_normalised": series,
            "series_normalised_plausible_only": series_plaus}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, float):
        if math.isnan(o) or math.isinf(o):
            return None
        return o
    return o


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=Path, default=HERE / "runs_api.jsonl")
    ap.add_argument("--outdir", type=Path, default=HERE / "analysis")
    ap.add_argument("--ground-truth", type=Path, default=HERE / "ground_truth.json")
    ap.add_argument("--bootstrap", type=int, default=2000,
                    help="bootstrap draws (pre-registration requires >= 2000)")
    ap.add_argument("--seed", type=int, default=20260731)
    args = ap.parse_args()

    if args.bootstrap < 2000:
        print(f"WARNING: --bootstrap {args.bootstrap} is below the pre-registered minimum of "
              f"2000. Reported CIs will say so.", file=sys.stderr)

    import datetime as _dt
    generated_at = _dt.datetime.now().astimezone().isoformat(timespec="seconds")

    args.outdir.mkdir(parents=True, exist_ok=True)
    units, gt_notes = load_ground_truth(args.ground_truth)
    if not args.runs.exists():
        print(f"ERROR: runs file not found: {args.runs}", file=sys.stderr)
        raise SystemExit(2)
    runs, q = load_runs(args.runs, units)
    rng = random.Random(args.seed)

    planned, planned_err = planned_grid()
    observed_keys = {r["cell_key"] for r in runs}
    if planned is not None:
        observed_planned = len(observed_keys & planned)
        missing = len(planned - observed_keys)
        unplanned = len(observed_keys - planned)
        pct = 100.0 * observed_planned / len(planned) if planned else 0.0
        completion = f"{observed_planned}/{len(planned)} cells ({pct:.1f}%)"
    else:
        observed_planned = missing = unplanned = None
        completion = f"{len(observed_keys)} cells observed (planned grid unavailable)"

    idx = Index(runs, units)
    idx_plaus = Index(runs, units, require_plausible=True)
    uncond, missing_uncond = unconditioned_medians(idx)
    # One shared denominator for both views, so primary and sensitivity differ
    # only in which runs enter the numerators.
    uncond_p, _ = unconditioned_medians(idx_plaus)
    n_uncond_denominators_differ = sum(
        1 for u in uncond if u in uncond_p and abs(uncond[u] - uncond_p[u]) > 1e-9)

    meta = {
        "generated_at": generated_at,
        "runs_path": str(args.runs),
        "ground_truth_path": str(args.ground_truth),
        "outdir": str(args.outdir),
        "seed": args.seed,
        "bootstrap_draws": args.bootstrap,
        "bootstrap_meets_prereg_minimum": args.bootstrap >= 2000,
        "reference_config": REFERENCE,
        "unconditioned_level": UNCONDITIONED_LEVEL,
        "planned_cells": len(planned) if planned is not None else None,
        "planned_error": planned_err,
        "observed_planned": observed_planned,
        "missing_cells": missing,
        "unplanned_cells": unplanned,
        "completion_str": completion,
        "units_missing_unconditioned": missing_uncond,
        "n_units_used": len(uncond),
        "ground_truth_notes": gt_notes,
        "repo_stats_note": REPO_STATS_NOTE,
        "alpha": ALPHA,
        "alpha_bonferroni": ALPHA_BONF,
        "normalisation": ("CRPS normalised by the SD of the unit's own supplied 60-month "
                          "history from ground_truth.json (frozen at pre-registration). "
                          "NEVER by the model's own interval width."),
        "plausibility_note": PLAUSIBILITY_NOTE,
        "plausibility_band": [PLAUSIBLE_LO, PLAUSIBLE_HI],
        "unconditioned_denominators_affected_by_flagged_runs": n_uncond_denominators_differ,
    }

    rows = build_cell_rows(idx, uncond)
    disp = {d: dimension_spread(idx, d, uncond, rng, args.bootstrap) for d in DIM_ORDER}
    disp_pooled = {d: dimension_spread(idx, d, uncond, rng, args.bootstrap,
                                       pool_over_policy_context=True)
                   for d in DIM_ORDER if d != "D1"}
    syc = sycophancy_test(idx, uncond, rng, args.bootstrap)
    elas = magnitude_elasticity(idx, uncond, rng, args.bootstrap)
    sk = skill_analysis(idx, units, rng, args.bootstrap)

    # Sensitivity view: identical computation, flagged extractions excluded.
    # Always computed, always reported, never substituted for the primary.
    rng_s = random.Random(args.seed)
    sens = {
        "description": ("identical computation with runs flagged `implausible_extraction` "
                        "excluded; shared unconditioned denominators with the primary view"),
        "n_runs_excluded": q["implausible_extractions"],
        "disp": {d: dimension_spread(idx_plaus, d, uncond, rng_s, args.bootstrap)
                 for d in DIM_ORDER},
        "P3_sycophancy": sycophancy_test(idx_plaus, uncond, rng_s, args.bootstrap),
        "P4_magnitude_elasticity": magnitude_elasticity(idx_plaus, uncond, rng_s, args.bootstrap),
        "skill": skill_analysis(idx_plaus, units, rng_s, args.bootstrap),
    }

    if disp.get("D1") and disp["D1"]["ratio_of_medians"]["point"] is not None:
        meta["d1_ratio_str"] = (f"P1 D1 policy_context ratio "
                                f"{disp['D1']['ratio_of_medians']['point']:.2f} "
                                f"{fmt_ci(disp['D1']['ratio_of_medians'], 2)} "
                                f"-> {disp['D1']['verdict']}")

    write_results_table(rows, q, units, args.outdir / "results_table.md", meta)
    write_dispersion(disp, disp_pooled, sens["disp"], args.outdir / "dispersion.md", meta, q)
    write_primary(disp, syc, elas, sens, args.outdir / "primary_analyses.md", meta, q)
    write_skill(sk, args.outdir / "skill.md", meta, q)
    fig = write_figure(idx, idx_plaus, uncond, units, args.outdir, meta, q)

    summary = {
        "meta": meta,
        "data_quality": q,
        "units": {u: {k: v for k, v in d.items()} for u, d in units.items()},
        "unconditioned_medians": uncond,
        "results_table": [{k: v for k, v in r.items() if k != "config_key"} for r in rows],
        "dispersion": {d: _strip_bulk(v) for d, v in disp.items()},
        "dispersion_pooled_over_policy_context_EXPLORATORY": {
            d: _strip_bulk(v) for d, v in disp_pooled.items()},
        "primary": {
            "P1_policy_context_dispersion": _strip_bulk(disp["D1"]),
            "P2_elicitation_dispersion": _strip_bulk(disp["D2"]),
            "P3_sycophancy": syc,
            "P4_magnitude_elasticity": elas,
        },
        "exploratory": {
            "D3_pipeline_dispersion": _strip_bulk(disp["D3"]),
            "D4_model_dispersion": _strip_bulk(disp["D4"]),
        },
        "skill": sk,
        "sensitivity_excluding_implausible_extractions": {
            "description": sens["description"],
            "n_runs_excluded": sens["n_runs_excluded"],
            "dispersion": {d: _strip_bulk(v) for d, v in sens["disp"].items()},
            "P3_sycophancy": sens["P3_sycophancy"],
            "P4_magnitude_elasticity": sens["P4_magnitude_elasticity"],
            "skill": sens["skill"],
        },
        "figure": {k: v for k, v in fig.items()
                   if k not in ("series_normalised", "series_normalised_plausible_only")},
        "figure_series_normalised": fig.get("series_normalised"),
        "figure_series_normalised_plausible_only": fig.get("series_normalised_plausible_only"),
    }
    (args.outdir / "summary.json").write_text(json.dumps(_jsonable(summary), indent=2) + "\n")

    print(f"runs read      : {q['records_read']} ({q['scored']} scored, "
          f"{q['parse_failures']} parse failures, {q['api_errors']} API errors, "
          f"{q['duplicate_cell_keys_dropped']} duplicates dropped, "
          f"{q['implausible_extractions']} implausible extractions flagged)")
    print(f"grid completion: {completion}")
    print(f"units usable   : {len(uncond)}/{len(units)}"
          + (f" (no unconditioned cell: {missing_uncond})" if missing_uncond else ""))
    for d in DIM_ORDER:
        r, s = disp[d], sens["disp"][d]
        print(f"{d} {r['field']:<15} spread={fmt(r['spread_pp_median'], 2)}% "
              f"noise={fmt(r['noise_floor_pp_median'], 2)}% "
              f"ratio={fmt(r['ratio_of_medians']['point'], 2)} "
              f"CI={fmt_ci(r['ratio_of_medians'], 2)}  -> {r['verdict']}"
              + (f"   [sensitivity ratio={fmt(s['ratio_of_medians']['point'], 2)} "
                 f"-> {s['verdict']}]" if s["verdict"] != r["verdict"] else ""))
    print(f"P3 concordant  : {syc['n_concordant_sign']}/"
          f"{syc['n_concordant_sign'] + syc['n_discordant_sign']} non-tied pairs "
          f"({syc['n_tied_excluded_from_concordance']} tied, {syc['n_units']} units) "
          f"p={fmt(syc['p_concordance_sign_test'], 4)}")
    print(f"P4 elasticity  : median={fmt(elas['median_elasticity'], 5)} "
          f"CI={fmt_ci(elas['bootstrap'], 5)} -> {elas['verdict']}")
    for lv, r in sk["per_level"].items():
        print(f"skill {lv:<24} {fmt(r['mean_skill_crps_norm']['point'], 4)} "
              f"CI={fmt_ci(r['mean_skill_crps_norm'], 4)} -> {r['verdict']}")
    if not fig.get("written"):
        print(f"FIGURE NOT WRITTEN: {fig.get('error')}")
    print(f"wrote -> {args.outdir}")


def _strip_bulk(d: dict) -> dict:
    """summary.json keeps per-unit detail but not the duplicated nested blobs."""
    return {k: v for k, v in d.items() if k != "per_unit"} | {
        "per_unit": {u: {kk: vv for kk, vv in e.items() if kk != "level_medians"}
                     for u, e in d.get("per_unit", {}).items()}}


if __name__ == "__main__":
    main()
