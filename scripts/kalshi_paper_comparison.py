#!/usr/bin/env python3
"""Paper comparison of published Thesis forecasts against Kalshi prices.

Read-only: public Kalshi market data, official agency releases, and the
attested Thesis records at a git ref. No orders, no account, no trading
simulation. The analysis plan is docs/kalshi-paper-comparison.md.

    uv run python scripts/kalshi_paper_comparison.py \
        --out ~/reviews/thesis-vs-kalshi-2026-10 --as-of 2026-10-19T23:00:00Z

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

from kalshi_compare import pipeline, report  # noqa: E402
from kalshi_compare.fetch import FetchCache  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument(
        "--cache",
        type=pathlib.Path,
        help="response store (default: <out>/fetch)",
    )
    parser.add_argument("--repo", type=pathlib.Path, default=ROOT)
    parser.add_argument("--ref", default="origin/main")
    parser.add_argument(
        "--as-of",
        default=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        help="releases after this date are treated as not yet out",
    )
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)

    out = args.out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    cache = FetchCache((args.cache or out / "fetch").expanduser(), offline=args.offline)
    results = pipeline.run(repo=args.repo, ref=args.ref, cache=cache, as_of=args.as_of)
    (out / "results.json").write_text(json.dumps(results, indent=1, default=str) + "\n")
    report.write(results, out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
