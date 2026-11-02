# stanli backtest output

Two runs of `scripts/backtest_stanli_candidates.py` on real ALFRED vintages,
downloaded 2026-11-02. `docs/stanli-candidates.md` explains the method and reads
the results.

| folder | training window | command flags |
|---|---|---|
| `window60/` | last 60 prints | `--window 60 --walk-forward --jobs 4` |
| `window36/` | last 36 prints | `--window 36 --walk-forward --jobs 4` |

Each folder holds:

- `table.md`: the arm table the script prints;
- `summary.json`: per-arm statistics with bootstrap intervals, `perSeriesCrpsRatio`,
  `byTransform`, `leaveOneSeriesOut`, `selectionCounts` and the run's `config`.

Each run also writes `targets.jsonl`, one row per target and arm (about 3.5 MB),
which stays out of the repo. To rebuild it, rerun the command; a run takes about 15
minutes with 4 jobs and caches its 12 MB of downloads in
`~/.cache/thesis-stanli-backtest`. Turning on `--walk-forward` left all 9,423
fixed-arm rows in each window identical to a run without it.
