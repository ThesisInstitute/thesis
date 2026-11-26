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
period. We reran four series (W824RC1, UNRATE, CPILFESL and A191RL1Q225SBEA)
with one job and no `--walk-forward` on 2026-11-18 and compared the 820 rows it
gives in the ten arms that run without `--walk-forward`. Apart from the
walk-forward scores, the stanli rows matched the 60-print run exactly, and 19 of
the 164 `statsmodels` and `statsmodels-ladder` rows differed in CRPS or PIT by
less than one part in 100 million.

Later commits fix the script's CSV checks, cadence inference, tie rounding,
normalization floor and ladder tie step, and the stanli scale's fallback for
constant changes. We checked, without refitting, that the CSV, cadence, floor,
ladder and scale fixes change no committed row. From the same cache, the old and new code build the
same 2,094 targets, the same persistence and `persistence-ladder` scores and
normalizers, and the same standardization for all 152,862 histories a stanli fit
sees, walk-forward prefixes included. Those rescored persistence rows match the
committed rows, apart from two 36-print `persistence-ladder` CRPS values, for
CUSR0000SAH1 in 2025-02 and PPIFIS in 2026-03. They differ in the 12th
significant digit, and the old and new code agree on them. The tie-rounding fix
changes a score only when its unrounded value is an exact tie at the 13th
digit. No persistence row has one, and we didn't refit the other arms to look.

Every comparison in the doc comes from these rows. `summary.json` holds the full
runs' statistics. For subsets, such as the comparisons without W824RC1, we
applied the script's own functions to filtered rows. Run this from the
repository root to recompute the 60-print result without W824RC1 and the full
60-print power estimate:

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
