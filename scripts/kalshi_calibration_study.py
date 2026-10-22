#!/usr/bin/env python3
"""Kalshi's calibration on the twelve economic series #381 scored.

Read-only: public Kalshi market data and official agency releases. No orders,
no account, no trading simulation. The analysis plan is
docs/kalshi-econ-calibration.md.

    uv run python scripts/kalshi_calibration_study.py \
        --out ~/reviews/kalshi-econ-calibration-2026-10/results \
        --cache ~/reviews/kalshi-econ-calibration-2026-10/fetch \
        --as-of <UTC time> \
        --repro381 ~/reviews/thesis-vs-kalshi-2026-10/results/results.json

Rerun from stored responses only with --offline.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kalshi_calibration import fixtures, pipeline, report, sensitivity  # noqa: E402
from kalshi_compare.fetch import FetchCache  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--cache", type=pathlib.Path, help="response store (default: <out>/fetch)")
    parser.add_argument(
        "--as-of",
        default=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        help="the data cutoff: events must be settled by then",
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--repro381",
        type=pathlib.Path,
        help="#381's frozen results.json, for the recalibrated-baseline sensitivity",
    )
    parser.add_argument(
        "--write-fixtures",
        type=pathlib.Path,
        help="also write the test fixtures (settlements and release excerpts) here",
    )
    args = parser.parse_args(argv)

    out = args.out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    cache = FetchCache((args.cache or out / "fetch").expanduser(), offline=args.offline)
    results = pipeline.run(cache=cache, as_of=args.as_of)
    events = results.pop("_events")
    if args.repro381:
        frozen = json.loads(args.repro381.expanduser().read_text())
        results["analyses"]["sensitivity381"] = sensitivity.run(frozen, results["binaryRows"])
    (out / "results.json").write_text(json.dumps(results, indent=1, default=str) + "\n")
    report.write(results, out, report.summary_lines(results))
    if args.write_fixtures:
        fixtures.write(cache, results, events, args.write_fixtures)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
