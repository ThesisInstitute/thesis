"""Re-derive every stored forecast through the current harness parser.

WHY THIS EXISTS. The v1 prose fallback in `harness.parse_forecast` filtered
candidate numbers with `n > 1000` and returned the FIRST 3-wide window matching
an ordering test. Calendar years clear 1000, and prose reasons about the series
history before it states an answer, so the first matching window was routinely a
run of years: 214 of 2520 runs came back with a point in [1900, 2100] against
targets whose truth is 1.3-5.4 million recipients, and 9 came back with no
interval at all.

That is a harness failure, not a model failure, and it is not random: it fires
only on prose, which is one LEVEL of a measured dimension (D2 elicitation).
Left in place it makes `free_text` look catastrophically worse than JSON for
reasons having nothing to do with elicitation format — manufacturing exactly the
artefact this experiment exists to detect. A second, quieter version of the same
failure hit `cot_then_json`: a trailing JSON object truncated at max_tokens or
broken by a stray quote never reached the JSON path at all, so the prose
heuristic mined the reasoning instead of reading the answer.

Because every response was stored, the correction is OFFLINE: no model is
re-called, no run is discarded, and the re-derivation is deterministic. Original
parses are preserved as `forecast_v1` so the correction is auditable line by
line. Re-eliciting instead would draw a fresh sample at a later date on one
level of a measured dimension, which is a worse cure than the disease.

There is deliberately no parser in this file. It delegates to
`harness.parse_forecast`, so the parse that produced the stored runs and the
parse that regenerates them cannot drift apart.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402

YEAR_LO, YEAR_HI = 1900, 2100


def is_year_shaped(forecast: dict) -> bool:
    point = forecast.get("point")
    return point is not None and YEAR_LO <= point <= YEAR_HI


def reparse_record(rec: dict, anchors: dict[str, float]) -> dict:
    """Return the freshly derived forecast for one run record."""
    text = rec.get("final_text") or ""
    if not text:
        return {"parse_error": "no_stored_text", "parse_mode": "failed"}
    elicitation = (rec.get("config") or {}).get("elicitation", "point_ci_json")
    return H.parse_forecast(text, elicitation, anchors.get(rec.get("unit_id")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=Path, default=HERE / "runs_api.jsonl")
    ap.add_argument("--ground-truth", type=Path, default=HERE / "ground_truth.json")
    ap.add_argument("--out", type=Path, default=HERE / "runs_api.reparsed.jsonl")
    ap.add_argument("--apply", action="store_true",
                    help="rewrite --runs in place, keeping the pre-fix file beside it")
    args = ap.parse_args()

    units = {u["unit_id"]: u for u in json.loads(args.ground_truth.read_text())}
    anchors = {uid: a for uid, u in units.items()
               if (a := H.history_anchor(u)) is not None}

    stats = Counter()
    modes_before: Counter = Counter()
    modes_after: Counter = Counter()
    by_elic: dict[str, Counter] = {}
    rescued_examples: list[dict[str, Any]] = []
    lost_examples: list[dict[str, Any]] = []
    out_lines: list[str] = []

    for line in args.runs.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        stats["total"] += 1
        elic = (rec.get("config") or {}).get("elicitation", "?")
        bucket = by_elic.setdefault(elic, Counter())
        bucket["n"] += 1

        old = rec.get("forecast") or {}
        modes_before[str(old.get("parse_mode"))] += 1
        old_ok = old.get("point") is not None
        if old_ok:
            bucket["v1_parsed"] += 1
            if is_year_shaped(old):
                stats["v1_year_shaped"] += 1
                bucket["v1_year_shaped"] += 1
            if old.get("ci_low") is not None and old["ci_low"] == old["ci_high"]:
                stats["v1_degenerate_interval"] += 1

        new = reparse_record(rec, anchors)
        modes_after[str(new.get("parse_mode"))] += 1
        new_ok = new.get("point") is not None
        if new_ok:
            bucket["v2_parsed"] += 1
            if is_year_shaped(new):
                stats["v2_year_shaped"] += 1

        # `forecast_v1` records the ORIGINAL parse only. Re-running this script
        # must not overwrite it with an intermediate correction.
        rec.setdefault("forecast_v1", old)
        rec["forecast"] = new
        rec["parser_version"] = H.PARSER_VERSION

        if old_ok and not new_ok:
            stats["lost"] += 1
            if len(lost_examples) < 8:
                lost_examples.append({"cell_key": rec.get("cell_key"), "elicitation": elic,
                                      "was": {k: old.get(k) for k in ("point", "parse_mode")},
                                      "now": new.get("parse_error"),
                                      "completion_tokens": (rec.get("calls") or [{}])[-1]
                                      .get("completion_tokens")})
        elif new_ok and not old_ok:
            stats["rescued"] += 1
            if len(rescued_examples) < 8:
                rescued_examples.append({"cell_key": rec.get("cell_key"),
                                         "point": new["point"], "mode": new["parse_mode"]})
        if old.get("point") != new.get("point"):
            stats["point_changed"] += 1

        out_lines.append(json.dumps(rec))

    report = {
        "runs_file": str(args.runs),
        "parser_version": H.PARSER_VERSION,
        "totals": dict(stats),
        "parse_mode_before": dict(modes_before),
        "parse_mode_after": dict(modes_after),
        "by_elicitation": {k: dict(v) for k, v in sorted(by_elic.items())},
        "rescued_examples": rescued_examples,
        "lost_examples": lost_examples,
    }
    print(json.dumps(report, indent=2))

    if not args.apply:
        args.out.write_text("\n".join(out_lines) + "\n")
        print(f"\nwrote {args.out} (dry run — pass --apply to rewrite {args.runs.name})")
        return 0

    backup = args.runs.with_suffix(".preparserfix.jsonl")
    if not backup.exists():
        shutil.copy2(args.runs, backup)
        print(f"\npre-fix runs preserved at {backup}")
    args.runs.write_text("\n".join(out_lines) + "\n")
    print(f"rewrote {args.runs} with {H.PARSER_VERSION} parses "
          f"({stats['point_changed']} points changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
