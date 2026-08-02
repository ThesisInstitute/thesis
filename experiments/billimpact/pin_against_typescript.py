#!/usr/bin/env python3
"""Cross-artefact agreement test: the site's TypeScript scorer vs the Python port.

The failure mode this exists to catch is a DISAGREEMENT between two files, so a
test that exercises either one alone would reproduce the bug rather than detect
it. This script therefore reads BOTH artefacts on every run:

  TypeScript  site/src/data/prediction-distribution.ts
              buildNumericCdfFromInterval + scoreNumericCdfDistribution,
              executed for real via `node ts_driver.mjs` (Node >= 22.6 strips
              the type annotations natively; nothing is hand-transpiled).

  Python      experiments/billimpact/scoring.py
              interval_distribution (delegating to the existing port at
              scripts/run_thesis_analyst.py) + score_numeric_cdf +
              score_forecast.

Both sides receive byte-identical inputs and are compared on CRPS, PIT, the
201-point CDF itself, and the support bounds. The CDF comparison is what
localises a failure to the builder rather than the scorer.

The script verifies that the JS side loaded the real TypeScript file by hashing
that path itself and requiring the driver to report the same SHA-256.

  Run the check:      python3 experiments/billimpact/pin_against_typescript.py
  Prove it can fail:  python3 experiments/billimpact/pin_against_typescript.py \
                          --negative-control all

Exit 0 only when every case agrees within tolerance AND both sides agree on
which cases are scoreable at all.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
TS_SOURCE = REPO_ROOT / "site" / "src" / "data" / "prediction-distribution.ts"
TS_DRIVER = HERE / "ts_driver.mjs"
RUNS_API = HERE / "runs_api.jsonl"

REL_TOL = 1e-9
ABS_TOL = 1e-9
REAL_CASE_TARGET = 20
CASE_SEED = 20260731

sys.path.insert(0, str(HERE))
import scoring  # noqa: E402  (path shim above is deliberate)


# --------------------------------------------------------------------------
# Case generation
#
# The support formula is duplicated here ONLY to choose where to probe. Both
# implementations receive the same literal observation values, so an error in
# this copy shifts where the probes land and can never manufacture agreement.
# --------------------------------------------------------------------------


def _probe_support(point: float, ci_low: float, ci_high: float) -> tuple[float, float]:
    lower_spread = max(abs(point - ci_low), 1e-9)
    upper_spread = max(abs(ci_high - point), 1e-9)
    lower = ci_low - lower_spread * 1.5
    upper = ci_high + upper_spread * 1.5
    if not math.isfinite(lower) or not math.isfinite(upper):
        lower, upper = point - 1, point + 1
    if upper <= lower:
        spread = max(abs(point), 1) * 0.1
        lower, upper = point - spread, point + spread
    return lower, upper


# (label, point, ci_low, ci_high) — spans the real input space and the edges.
SHAPES: list[tuple[str, float, float, float]] = [
    # Real SNAP scale (recipient counts in the millions), symmetric interval.
    ("snap_typical", 4_380_000.0, 4_280_000.0, 4_480_000.0),
    # Real scale, asymmetric interval (point off-centre).
    ("snap_asymmetric", 4_180_000.0, 4_050_000.0, 4_600_000.0),
    # Very wide interval.
    ("very_wide", 3_000_000.0, 500_000.0, 6_000_000.0),
    # Near-degenerate: ci_low ~= ci_high but the CDF stays strictly increasing.
    ("near_degenerate", 4_300_000.0, 4_299_999.9, 4_300_000.1),
    # Exactly degenerate: ci_low == ci_high == point. 3 rows of runs_api.jsonl
    # look like this (free-text parses that captured a year), so it is live.
    ("degenerate_zero_width", 4_300_000.0, 4_300_000.0, 4_300_000.0),
    # Large magnitude beyond the SNAP scale.
    ("huge_magnitude", 1_250_000_000.0, 1_100_000_000.0, 1_400_000_000.0),
    # Small magnitude.
    ("small_scale", 12.5, 9.0, 18.0),
    # Sub-unit magnitude (stresses the 12-significant-figure rounding).
    ("tiny_scale", 0.0004, 0.0002, 0.0009),
    # Wholly negative.
    ("negative", -250.0, -400.0, -120.0),
    # Interval straddling zero, point exactly at zero.
    ("zero_crossing", 0.0, -50.0, 75.0),
]


def _positions(point: float, ci_low: float, ci_high: float) -> list[tuple[str, float]]:
    lower, upper = _probe_support(point, ci_low, ci_high)
    width = upper - lower
    mid = lambda a, b: a + (b - a) / 2  # noqa: E731
    return [
        ("below_support", lower - 0.5 * width),
        ("at_support_lower", lower),
        ("below_ci_low", mid(lower, ci_low)),
        ("at_ci_low", ci_low),
        ("inside_low", mid(ci_low, point)),
        ("at_point", point),
        ("inside_high", mid(point, ci_high)),
        ("at_ci_high", ci_high),
        ("above_ci_high", mid(ci_high, upper)),
        ("at_support_upper", upper),
        ("above_support", upper + 0.5 * width),
    ]


def _load_real_cases(limit: int) -> tuple[list[dict[str, Any]], str]:
    """Pull (point, ci_low, ci_high, truth) tuples out of runs_api.jsonl."""
    if not RUNS_API.exists():
        return [], f"{RUNS_API.name} not found — synthetic cases only"

    usable: list[dict[str, Any]] = []
    parse_failures = 0
    with RUNS_API.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                parse_failures += 1
                continue
            forecast, truth = row.get("forecast"), row.get("truth")
            if not isinstance(forecast, dict) or not isinstance(truth, (int, float)):
                continue
            point = forecast.get("point")
            ci_low = forecast.get("ci_low")
            ci_high = forecast.get("ci_high")
            if any(
                not isinstance(v, (int, float)) for v in (point, ci_low, ci_high)
            ):
                continue
            usable.append(
                {
                    "point": float(point),
                    "ci_low": float(ci_low),
                    "ci_high": float(ci_high),
                    "observed": float(truth),
                    "cell_key": row.get("cell_key") or row.get("unit_id") or "?",
                }
            )

    if not usable:
        return [], f"{RUNS_API.name} had no parseable forecast/truth rows"

    # Zero-width intervals are the interesting minority (3 of 720), so take all
    # of them deliberately rather than hoping a random sample lands on one.
    degenerate = [c for c in usable if c["ci_low"] == c["ci_high"]]
    ordinary = [c for c in usable if c["ci_low"] != c["ci_high"]]
    rng = random.Random(CASE_SEED)
    sampled = rng.sample(ordinary, min(max(limit - len(degenerate), 0), len(ordinary)))
    picked = degenerate + sampled

    note = (
        f"{len(usable)} usable rows in {RUNS_API.name} "
        f"({len(degenerate)} with ci_low == ci_high, all included); "
        f"sampled {len(sampled)} others with seed {CASE_SEED}"
    )
    if parse_failures:
        note += f"; {parse_failures} unparseable lines skipped"
    return picked, note


def build_cases() -> tuple[list[dict[str, Any]], str]:
    cases: list[dict[str, Any]] = []
    for shape, point, ci_low, ci_high in SHAPES:
        for position, observed in _positions(point, ci_low, ci_high):
            cases.append(
                {
                    "id": len(cases),
                    "family": "synthetic",
                    "label": f"{shape}/{position}",
                    "point": point,
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "observed": observed,
                }
            )

    real, note = _load_real_cases(REAL_CASE_TARGET)
    for entry in real:
        cases.append(
            {
                "id": len(cases),
                "family": "real",
                "label": f"real/{entry['cell_key']}",
                "point": entry["point"],
                "ci_low": entry["ci_low"],
                "ci_high": entry["ci_high"],
                "observed": entry["observed"],
            }
        )
    return cases, note


# --------------------------------------------------------------------------
# Running each side
# --------------------------------------------------------------------------


def _decode(value: Any) -> float:
    """Undo ts_driver.mjs's non-finite tagging (JSON.stringify writes null)."""
    if isinstance(value, dict):
        tag = value.get("__nonfinite__")
        if tag == "NaN":
            return math.nan
        if tag == "Infinity":
            return math.inf
        if tag == "-Infinity":
            return -math.inf
        raise ValueError(f"undecodable number from ts_driver: {value!r}")
    if value is None:
        raise ValueError("ts_driver emitted null where a number was expected")
    return float(value)


def run_typescript(cases: list[dict[str, Any]], node: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, prefix="pin_cases_"
    ) as handle:
        json.dump({"cases": cases}, handle)
        case_path = handle.name

    proc = subprocess.run(
        [
            node,
            "--disable-warning=MODULE_TYPELESS_PACKAGE_JSON",
            str(TS_DRIVER),
            case_path,
            "--points",
        ],
        capture_output=True,
        text=True,
    )
    Path(case_path).unlink(missing_ok=True)

    if proc.returncode != 0:
        raise RuntimeError(
            "the TypeScript side did not run.\n"
            f"  command exit code: {proc.returncode}\n"
            f"  stderr: {proc.stderr.strip()[:2000]}\n"
            "  (Node >= 22.6 is required for native TypeScript type stripping.)"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"ts_driver produced unparseable stdout ({error}): "
            f"{proc.stdout[:500]!r}"
        ) from error


def _perturb(value: float, factor: float = 1.0000001) -> float:
    """Nudge a value past tolerance. Multiplicative, with an additive fallback
    so an exact zero (PIT saturates at 0 and 1) still moves."""
    moved = value * factor
    if moved == value:
        moved = value + 1e-6
    return moved


def run_python(
    cases: list[dict[str, Any]], negative_control: str | None
) -> list[dict[str, Any]]:
    results = []
    for case in cases:
        out: dict[str, Any] = {"id": case["id"]}
        try:
            distribution = scoring.interval_distribution(
                case["point"], case["ci_low"], case["ci_high"]
            )
        except Exception as error:  # noqa: BLE001 — status is the thing compared
            out["build_status"] = "error"
            out["build_error"] = f"{type(error).__name__}: {error}"
            out["score_status"] = "skipped"
            results.append(out)
            continue

        out["build_status"] = "ok"
        out["support"] = {
            "lower": float(distribution["support"]["lower"]),
            "upper": float(distribution["support"]["upper"]),
        }
        points = [
            [float(p["value"]), float(p["probability"])] for p in distribution["points"]
        ]
        out["point_count"] = len(points)

        try:
            score = scoring.score_numeric_cdf(distribution, case["observed"])
            # Also exercise the public entry point the experiment actually calls,
            # so a divergence between score_forecast and its own components
            # cannot slip past this pin.
            end_to_end = scoring.score_forecast(
                case["point"], case["ci_low"], case["ci_high"], case["observed"]
            )
            out["score_status"] = "ok"
            out["crps"] = float(score["crps"])
            out["pit"] = float(score["pit"])
            out["end_to_end_crps"] = float(end_to_end["crps"])
            out["end_to_end_pit"] = float(end_to_end["pit"])
        except Exception as error:  # noqa: BLE001
            out["score_status"] = "error"
            out["score_error"] = f"{type(error).__name__}: {error}"
            results.append(out)
            continue

        # The perturbation simulates "the Python port is wrong", which would
        # corrupt score_forecast identically — so move both, leaving the
        # end-to-end consistency guard free to report on its own axis.
        if negative_control in ("crps", "all"):
            out["crps"] = _perturb(out["crps"])
            out["end_to_end_crps"] = out["crps"]
        if negative_control in ("pit", "all"):
            out["pit"] = _perturb(out["pit"])
            out["end_to_end_pit"] = out["pit"]
        if negative_control in ("cdf", "all"):
            mid = len(points) // 2
            points[mid] = [_perturb(points[mid][0]), _perturb(points[mid][1])]
            out["support"]["upper"] = _perturb(out["support"]["upper"])

        out["points"] = points
        results.append(out)
    return results


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------


def divergence(a: float, b: float) -> tuple[float, float]:
    """(absolute, relative). Relative is scaled by the larger magnitude."""
    if math.isnan(a) and math.isnan(b):
        return 0.0, 0.0
    if a == b:
        return 0.0, 0.0
    absolute = abs(a - b)
    scale = max(abs(a), abs(b))
    if not math.isfinite(absolute):
        return math.inf, math.inf
    return absolute, (absolute / scale if scale > 0 else math.inf)


def agrees(a: float, b: float, rel_tol: float, abs_tol: float) -> bool:
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if a == b:
        return True
    absolute, relative = divergence(a, b)
    return absolute <= abs_tol or relative <= rel_tol


def _round_like_ts(value: float) -> float:
    """Python mirror of roundDistributionNumber: Number(v.toPrecision(12))."""
    if not math.isfinite(value):
        return value
    return float(format(value, ".12g")) + 0.0


class Tracker:
    """Accumulates divergence for one compared quantity."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.compared = 0
        self.failures: list[tuple[str, float, float, float, float]] = []
        self.max_abs = 0.0
        self.max_rel = 0.0
        # Tracked separately: the largest absolute and largest relative
        # divergence generally come from DIFFERENT cases, and printing one
        # number beside the other's label would misattribute both.
        self.worst_abs = "-"
        self.worst_rel = "-"

    def observe(self, label: str, ts: float, py: float, rel_tol: float, abs_tol: float):
        self.compared += 1
        absolute, relative = divergence(ts, py)
        if relative > self.max_rel:
            self.max_rel = relative
            self.worst_rel = label
        if absolute > self.max_abs:
            self.max_abs = absolute
            self.worst_abs = label
        if not agrees(ts, py, rel_tol, abs_tol):
            self.failures.append((label, ts, py, absolute, relative))

    @property
    def ok(self) -> bool:
        return not self.failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pin the Python forecast scorer against the site TypeScript."
    )
    parser.add_argument(
        "--negative-control",
        nargs="?",
        const="crps",
        choices=["crps", "pit", "cdf", "all"],
        default=None,
        help=(
            "Deliberately perturb the Python result so the comparison MUST fail. "
            "Exit 1 = the perturbation was caught (correct). "
            "Exit 3 = it slipped through, meaning the pin compares nothing."
        ),
    )
    parser.add_argument("--node", default=None, help="path to the node binary")
    parser.add_argument("--rel-tol", type=float, default=REL_TOL)
    parser.add_argument("--abs-tol", type=float, default=ABS_TOL)
    parser.add_argument(
        "--verbose", action="store_true", help="print every case, not just failures"
    )
    args = parser.parse_args()

    node = args.node or shutil.which("node")
    if not node:
        print("FAIL: no `node` on PATH; pass --node /path/to/node", file=sys.stderr)
        return 2
    if not TS_SOURCE.exists():
        print(f"FAIL: TypeScript source missing at {TS_SOURCE}", file=sys.stderr)
        return 2

    cases, real_note = build_cases()
    ts_payload = run_typescript(cases, node)
    py_results = run_python(cases, args.negative_control)

    # Proof that the JS side executed code from the file under test.
    local_sha = hashlib.sha256(TS_SOURCE.read_bytes()).hexdigest()
    sha_match = local_sha == ts_payload.get("ts_source_sha256")
    path_match = Path(ts_payload.get("ts_source_path", "")).resolve() == TS_SOURCE

    ts_by_id = {r["id"]: r for r in ts_payload["results"]}
    py_by_id = {r["id"]: r for r in py_results}

    both_scored: list[dict[str, Any]] = []
    both_rejected: list[str] = []
    ts_only_rejected: list[tuple[str, str]] = []
    py_only_rejected: list[tuple[str, str]] = []

    for case in cases:
        ts, py = ts_by_id.get(case["id"]), py_by_id.get(case["id"])
        if ts is None or py is None:
            py_only_rejected.append((case["label"], "missing result from one side"))
            continue
        ts_ok = ts["build_status"] == "ok" and ts["score_status"] == "ok"
        py_ok = py["build_status"] == "ok" and py["score_status"] == "ok"
        if ts_ok and py_ok:
            both_scored.append(case)
        elif not ts_ok and not py_ok:
            both_rejected.append(case["label"])
        elif py_ok:
            ts_only_rejected.append(
                (case["label"], ts.get("score_error") or ts.get("build_error") or "?")
            )
        else:
            py_only_rejected.append(
                (case["label"], py.get("score_error") or py.get("build_error") or "?")
            )

    trackers = {
        name: Tracker(name)
        for name in ("crps", "pit", "support", "cdf.value", "cdf.probability")
    }
    exact_after_ts_round = 0
    end_to_end_mismatch: list[str] = []

    for case in both_scored:
        ts, py = ts_by_id[case["id"]], py_by_id[case["id"]]
        label = case["label"]
        ts_crps, ts_pit = _decode(ts["crps"]), _decode(ts["pit"])
        trackers["crps"].observe(label, ts_crps, py["crps"], args.rel_tol, args.abs_tol)
        trackers["pit"].observe(label, ts_pit, py["pit"], args.rel_tol, args.abs_tol)

        if _round_like_ts(py["crps"]) == ts_crps and _round_like_ts(py["pit"]) == ts_pit:
            exact_after_ts_round += 1
        if (py["end_to_end_crps"], py["end_to_end_pit"]) != (py["crps"], py["pit"]):
            end_to_end_mismatch.append(label)

        for side in ("lower", "upper"):
            trackers["support"].observe(
                f"{label}[support.{side}]",
                _decode(ts["support"][side]),
                py["support"][side],
                args.rel_tol,
                args.abs_tol,
            )

        ts_points, py_points = ts.get("points", []), py.get("points", [])
        if len(ts_points) != len(py_points):
            trackers["cdf.value"].failures.append(
                (f"{label}[point_count]", len(ts_points), len(py_points), math.inf, math.inf)
            )
            continue
        for index, (tp, pp) in enumerate(zip(ts_points, py_points)):
            trackers["cdf.value"].observe(
                f"{label}[{index}].value",
                _decode(tp[0]),
                pp[0],
                args.rel_tol,
                args.abs_tol,
            )
            trackers["cdf.probability"].observe(
                f"{label}[{index}].probability",
                _decode(tp[1]),
                pp[1],
                args.rel_tol,
                args.abs_tol,
            )

    # ---------------- report ----------------
    line = "=" * 86
    print(line)
    print("CROSS-ARTEFACT PIN  —  site TypeScript scorer  vs  Python port")
    print(line)
    print(f"TS source     : {TS_SOURCE}")
    print(
        f"TS sha256     : {local_sha[:16]}…  "
        f"(driver loaded the same file: {'YES' if sha_match and path_match else 'NO'})"
    )
    print(f"TS exports    : {', '.join(ts_payload.get('exports_seen', []))}")
    print(f"Node          : {ts_payload.get('node_version')}  ({node})")
    print(f"Python        : {sys.version.split()[0]}")
    print(f"Python port   : {HERE / 'scoring.py'}")
    print(f"                -> {REPO_ROOT / 'scripts' / 'run_thesis_analyst.py'}")
    print(
        f"Cases         : {len(cases)} "
        f"({sum(1 for c in cases if c['family'] == 'synthetic')} synthetic, "
        f"{sum(1 for c in cases if c['family'] == 'real')} real)"
    )
    print(f"Real source   : {real_note}")
    print(f"Tolerance     : relative {args.rel_tol:g}, absolute {args.abs_tol:g}")
    mode = (
        f"NEGATIVE CONTROL — Python {args.negative_control} perturbed "
        "(this run MUST fail)"
        if args.negative_control
        else "normal"
    )
    print(f"Mode          : {mode}")

    print("\n--- status agreement " + "-" * 65)
    print(f"  both scored             : {len(both_scored)}")
    print(f"  both rejected           : {len(both_rejected)}")
    print(f"  TS rejected, Py scored  : {len(ts_only_rejected)}")
    print(f"  TS scored,  Py rejected : {len(py_only_rejected)}")
    divergent_status = ts_only_rejected + py_only_rejected
    for label, reason in divergent_status[:30]:
        print(f"      {label:<46} {reason[:64]}")
    if len(divergent_status) > 30:
        print(f"      … and {len(divergent_status) - 30} more")

    print(f"\n--- numeric agreement over {len(both_scored)} co-scored cases " + "-" * 33)
    header = f"  {'quantity':<18}{'compared':>10}{'max abs div':>16}{'max rel div':>16}  verdict"
    print(header)
    for name in ("crps", "pit", "support", "cdf.value", "cdf.probability"):
        t = trackers[name]
        verdict = "PASS" if t.ok else f"FAIL ({len(t.failures)})"
        print(
            f"  {name:<18}{t.compared:>10}{t.max_abs:>16.3e}{t.max_rel:>16.3e}  {verdict}"
        )
        if t.max_abs > 0 or args.verbose:
            print(f"  {'':<18}worst abs: {t.worst_abs}")
        if t.max_rel > 0 or args.verbose:
            print(f"  {'':<18}worst rel: {t.worst_rel}")

    numeric_ok = all(t.ok for t in trackers.values())
    compared_total = sum(t.compared for t in trackers.values())

    if not numeric_ok:
        print("\n--- divergent cases " + "-" * 66)
        shown = 0
        for t in trackers.values():
            for label, ts_value, py_value, absolute, relative in t.failures:
                if shown >= 25:
                    print("      … (further failures suppressed)")
                    break
                print(
                    f"  {t.name:<16} {label:<40}\n"
                    f"      ts={ts_value!r}  py={py_value!r}  "
                    f"abs={absolute:.6e}  rel={relative:.6e}"
                )
                shown += 1
            if shown >= 25:
                break

    print("\n--- diagnostics " + "-" * 70)
    print(
        f"  TS rounds its outputs to 12 significant figures "
        f"(roundDistributionNumber); the Python scorer does not."
    )
    print(
        f"  Cases where round_like_ts(python) == typescript EXACTLY: "
        f"{exact_after_ts_round}/{len(both_scored)}"
    )
    print(
        f"  score_forecast disagreeing with its own components: "
        f"{len(end_to_end_mismatch)}"
    )
    print(f"  Total scalar comparisons performed: {compared_total}")

    if args.negative_control:
        # Report the negative control's own DENOMINATOR. A perturbation that
        # trips "some" cases is not evidence that it could trip any given one,
        # and the untripped set is exactly where the pin is weakest.
        relevant = {
            "crps": ["crps"],
            "pit": ["pit"],
            "cdf": ["support", "cdf.value", "cdf.probability"],
            "all": list(trackers),
        }[args.negative_control]
        tripped_labels = {
            failure[0].split("[")[0]
            for name in relevant
            for failure in trackers[name].failures
        }
        untripped = [c["label"] for c in both_scored if c["label"] not in tripped_labels]
        print(
            f"\n  NEGATIVE CONTROL denominator: perturbation tripped "
            f"{len(both_scored) - len(untripped)}/{len(both_scored)} co-scored cases."
        )
        if untripped:
            print(
                f"    {len(untripped)} case(s) NOT tripped — the perturbed quantity "
                f"is small enough that a 1e-07 relative\n"
                f"    nudge lands under the {args.abs_tol:g} absolute tolerance floor. "
                f"Those cases are pinned only to\n"
                f"    +/-{args.abs_tol:g} absolute, which is the stated tolerance rule "
                f"working as specified:"
            )
            for label in untripped[:6]:
                print(f"      {label}")
            if len(untripped) > 6:
                print(f"      … and {len(untripped) - 6} more")

    # Guards against the false-clean failure: a test that compared nothing is
    # indistinguishable from a test that passed.
    executed = True
    if compared_total == 0 or not both_scored:
        print("\n  GUARD FAILED: zero comparisons were performed.")
        executed = False
    if not (sha_match and path_match):
        print("\n  GUARD FAILED: the driver did not load the expected TypeScript file.")
        executed = False
    if end_to_end_mismatch:
        print("\n  GUARD FAILED: score_forecast diverged from score_numeric_cdf.")
        executed = False

    status_ok = not ts_only_rejected and not py_only_rejected
    overall = numeric_ok and status_ok and executed

    print("\n" + line)
    print(f"  NUMERIC PIN : {'PASS' if numeric_ok else 'FAIL'}")
    print(
        f"  STATUS PIN  : {'PASS' if status_ok else f'FAIL ({len(ts_only_rejected) + len(py_only_rejected)} cases)'}"
    )
    print(f"  EXECUTION   : {'PASS' if executed else 'FAIL'}")
    print(f"  OVERALL     : {'PASS' if overall else 'FAIL'}")
    if args.negative_control:
        print(
            f"  NEGATIVE CONTROL: "
            f"{'CORRECT — the perturbation was caught' if not overall else 'BROKEN — a perturbed run still passed'}"
        )
    print(line)

    if args.negative_control:
        # A negative-control run is SUPPOSED to go red, so it exits 1 (visibly
        # failing) when the perturbation was caught. Exit 3 is the alarming
        # case: the perturbation slipped through, which means the comparison
        # is not actually comparing anything.
        return 1 if not overall else 3
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
