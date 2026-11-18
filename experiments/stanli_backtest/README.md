# stanli backtest output

We ran `scripts/backtest_stanli_candidates.py` twice on real ALFRED vintages,
both times with the code at commit ec45aa8c on an Apple-silicon Mac. See
`docs/stanli-candidates.md` for the method and the results.

| folder | training window | command flags |
|---|---|---|
| `window60/` | last 60 prints | `--window 60 --walk-forward --jobs 4` |
| `window36/` | last 36 prints | `--window 36 --walk-forward --jobs 4` |

Each folder holds:

- `table.md`: the arm table the script writes;
- `summary.json`: each arm's statistics against persistence with bootstrap
  intervals and the run's `config`, plus `versusPersistenceLadder`,
  `pairedComparisons`, `perSeriesCrpsRatio`, `byTransform`,
  `leaveOneSeriesOut`, `selectionCounts`, `selectionCountsWithoutSkip`,
  `warningSplit`, `byPeriodHalf`, `windowsFrom` and `ablationPower`;
- `targets.jsonl.gz`: one row per target and arm, with its CRPS, PIT and 80%
  coverage. Each stanli program's rows also carry its warning flag and
  walk-forward score, and the selection arms' rows name the program they picked.

The script caches its ALFRED downloads (13 MB) in
`~/.cache/thesis-stanli-backtest`, and both runs read the vintages it downloaded
on 2026-11-02. The script writes rows in series order, so `--jobs` leaves the
output alone, and each target draws its sampler seeds from its series and
period. A rerun of four series (W824RC1, UNRATE, CPILFESL and A191RL1Q225SBEA)
with one job and no `--walk-forward` reproduced the 60-print run's rows for the
ten arms that run without `--walk-forward`. It matched every field of those 820
rows except the walk-forward scores.

Every comparison in the doc comes from these rows. `summary.json` holds the full
runs' statistics. For subsets, such as the comparisons without W824RC1, we
applied the script's own functions to filtered rows. Run this from the
repository root to recompute one subset and the power calculation:

```python
import gzip, json, sys

sys.path.insert(0, "scripts")
import backtest_stanli_candidates as bt

with gzip.open("experiments/stanli_backtest/window60/targets.jsonl.gz", "rt") as handle:
    rows = [json.loads(line) for line in handle]
kept = [row for row in rows if row["series"] != "W824RC1:level"]
stats = bt.compare(kept, baseline="persistence-ladder", arms=["stanli-ar1-t-ladder"])
print(stats["stanli-ar1-t-ladder"]["geometricMeanCrpsRatio"])  # 0.904
print(bt.ablation_power(rows, "stanli-ar1-t-ladder", baseline="persistence-ladder"))
```
