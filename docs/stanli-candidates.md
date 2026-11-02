# stanli model candidates

`brier/stan_candidates.py` adds Bayesian model candidates to
`scripts/run_time_series_models.py`. Each candidate fits a Stan program with
[stanli](https://github.com/seantalts/stanli) and reports the posterior
predictive distribution of the next print. The candidates are opt-in: the
default models stay `persistence,statsmodels-local-level`, and no agent prompt
or skill names them. `docs/pack-promotion.md` requires a pack ablation before
any of this becomes default analyst behavior.

## Why stanli

stanli (Sean Talts, BSD-3) runs Stan programs over precompiled Stan Math
kernels with Stan's own NUTS sampler. It needs no per-model C++ compile, and a
fit ran to completion under a macOS deny-write sandbox, so it should suit the
analyst's read-only sandbox, where a CmdStan build cannot run. On an
Apple-silicon Mac a built-in program (4 chains of 1,000 draws after 1,000 warmup)
fits in 30 to 60 ms, and the first fit in a process takes about 300 ms.

## Usage

Install the `stan` extra (exact-pinned to `stanli==0.25.0`):

```bash
uv run --extra stan --extra experiments python scripts/run_time_series_models.py \
  --target-id bls.cps.unemployment_rate \
  --target-period 2026-10 \
  --history-file /tmp/history.json \
  --models persistence,statsmodels-local-level,stanli-rw-drift-t,stanli-ar1-t \
  --round-increment 0.1
```

The built-in programs fit a standardized history (below) under fixed priors:

| model | process | use it for |
|---|---|---|
| `stanli-rw-drift-t` | random walk with drift, Student-t steps | levels that wander, the Bayesian counterpart of `statsmodels-local-level` |
| `stanli-ar1-t` | stationary AR(1) around a fitted mean, Student-t errors | rates and monthly changes that revert |
| `stanli-ar1-diff-t` | AR(1) on one-step changes with drift (ARIMA(1,1,0)), Student-t errors | levels whose changes carry momentum |

A custom program runs as `stanli-custom` with `--stan-file`. Print a
built-in to start from:

```bash
python3 scripts/run_time_series_models.py --print-stan-program stanli-ar1-t > ar1.stan
```

## Data contract

Every program receives the same data, and stanli ignores items a program does
not declare:

| name | meaning |
|---|---|
| `N` | number of prints (at least 3; `stanli-ar1-diff-t` needs 4) |
| `y` | the raw history |
| `y_loc` | the last print |
| `y_scale` | 1.4826 times the median absolute deviation of the one-step changes, falling back to the mean absolute deviation, then 1% of the last print, then 1 |
| `y_std` | `(y - y_loc) / y_scale` |
| `y_grid` | the increment the prints are reported on, 0 when unknown |

A program must define the generated quantity `y_next`: one scalar draw of the
next print, in raw units. A program that fails to parse, declares data the
contract does not supply, omits `y_next`, makes it non-scalar, or draws a
non-finite value raises a `ValueError` naming the problem.

The built-ins fit `y_std`, so scaling the history (and its grid) by a power of
two scales every predictive quantile exactly, and shifting it shifts them to
rounding error. `tests/test_stan_candidates.py` checks both.

## Reporting grid

Official prints are rounded, and rounded series repeat a print often. When
more than half of the one-step changes are exactly zero, a Student-t
likelihood grows without bound as its scale goes to zero. Without a fix, NUTS
returned a point mass at the last print on such a series, and for
`stanli-ar1-t` it still reported R-hat 1.000 and bulk ESS 4,000.

The built-in programs treat each print as the latent value plus rounding error
uniform on half a grid step either way (variance `y_grid^2 / 12`) and add that
variance to the residual scale, for every print the residual involves. That
keeps the likelihood bounded. The rounding errors enter as independent noise;
their correlation across neighbouring residuals is ignored.

The grid is `10^-d` for the most decimal places any print shows, with trailing
zeros dropped, so whole-number prints get a grid of 1. Python callers can pass
`grid=` to `build_stanli_candidate` instead.

## Output

A stanli candidate follows `thesis_model_candidate_v1` with `library`
`stanli`, `intervalMethod` `posterior_predictive`, and point, p10 and p90 at
the predictive median, 10th and 90th percentiles (rounded to
`--round-increment` when given, then widened to bracket the point strictly).
It adds a `posteriorPredictive` block:

- `quantiles`: 19 predictive quantiles at probabilities 0.05 to 0.95, unrounded;
- `draws`, `chains`, `warmup`, `samplesPerChain` and `seed`;
- `standardization`: `yLoc`, `yScale` and `yGrid`;
- `sampler`: divergent transitions, max R-hat and min bulk ESS over the
  parameters; and
- `program`: the model name, the Stan source and its SHA-256.

The seed derives from the candidate id, so the same target, cutoff, model and
history give the same draws. When the sampler reports a divergence or an R-hat
above 1.01, the diagnostics end with a `WARNING` line; treat that candidate as
unreliable.

A candidate's JSON carries its program, history, grid and seed, so a trace that
records the JSON can replay the fit:

```bash
uv run --extra stan python scripts/run_time_series_models.py --replay-stanli candidates.json
```

The command refits every stanli candidate in the file, compares all 19 quantiles
with the recorded ones, and exits 1 on any mismatch or on a source that does not
match its recorded hash. `tests/test_stan_candidates.py` checks exact replay for
every built-in and a custom program, each through a JSON round trip, and checks
that a changed seed, print or grid fails. Those tests replay on the machine that
fitted, and no test compares platforms or stanli versions. The JSON records
`libraryVersion` but not the platform.

Each candidate also carries a one-step walk-forward score over its last 24
cutoffs, fitted with the full history's grid.

## Publishing a stanli forecast

- **Fast mode** publishes a point and an 80% interval. Use the candidate's
  point, p10 and p90; Thesis seeds an `interval_anchor_v1` CDF from them.
- **Ladder mode** publishes a threshold ladder. The 19 posterior quantiles are
  a valid ladder as they stand: thresholds are the quantile values,
  cumulative probabilities 0.05 to 0.95, and the stated point and interval
  are the ladder's own q50, q10 and q90. Keep the thresholds unrounded;
  rounding can tie neighbouring rungs, which the ladder rejects.
  `tests/test_backtest_stanli_candidates.py` runs a stanli ladder through
  `ladder_validation_errors`.

## Backtest

`scripts/backtest_stanli_candidates.py` replays every series a Thesis ALFRED
adapter resolves (46 after merging unit variants of the same FRED series) in
real time:

- It downloads ALFRED vintages on the 1st and 16th of each month from
  2024-06-01 through 2026-11-01.
- For each period it trains on the vintage just before the period's first
  print, transformed as the resolver transforms prints, and scores against
  that first print.
- Every arm forecasts one step ahead from the same last `--window` prints and
  is scored by CRPS on the site's 201-point CDF. The Python CRPS port matches
  the site's `scoreNumericCdfDistribution` exactly in
  `tests/test_backtest_stanli_candidates.py`.
- CRPS is divided by the sample standard deviation of the training window's
  one-step changes.
- The 95% intervals come from a bootstrap that resamples whole series.

```bash
uv run --extra stan --extra experiments python scripts/backtest_stanli_candidates.py \
  --output-dir experiments/stanli_backtest/window60 --window 60 --walk-forward --jobs 4
```

`--walk-forward` adds the `stanli-selected` arms. For each target they apply the
draft skill's rule below to the training history: skip programs with a sampler
warning, then take the lowest MAE over the last 24 cutoffs. The rule, the programs
and their priors all predate these runs.

### Results

Each run covers 46 series and 1,047 targets, for periods from 2024-04 through
2026-09, and no series failed. Each cell gives the estimate and its 95% interval.
A CRPS ratio is the geometric mean of the arm's CRPS over persistence's. A
difference is the arm's mean normalized CRPS minus persistence's, which only
compares within a window because the windows normalize differently.

| arm | CRPS ratio, 60 prints | CRPS ratio, 36 prints | difference, 60 prints | difference, 36 prints | series beating persistence (of 46), 60 / 36 | 80% coverage, 60 / 36 |
|---|---:|---:|---:|---:|---:|---:|
| `stanli-selected-ladder` | 0.773 (0.674, 0.848) | 0.777 (0.682, 0.853) | -0.092 (-0.187, -0.029) | -0.108 (-0.221, -0.035) | 44 / 42 | 80% / 76% |
| `stanli-ar1-t-ladder` | 0.815 (0.778, 0.852) | 0.810 (0.771, 0.851) | -0.072 (-0.114, -0.042) | -0.097 (-0.149, -0.058) | 42 / 44 | 79% / 76% |
| `stanli-ar1-diff-t-ladder` | 0.812 (0.697, 0.895) | 0.826 (0.708, 0.912) | -0.077 (-0.179, -0.012) | -0.090 (-0.209, -0.016) | 44 / 41 | 80% / 77% |
| `stanli-rw-drift-t-ladder` | 0.911 (0.866, 0.953) | 0.919 (0.861, 0.968) | -0.036 (-0.097, -0.001) | -0.053 (-0.140, +0.000) | 38 / 31 | 80% / 79% |
| `stanli-selected` | 0.830 (0.728, 0.906) | 0.817 (0.717, 0.896) | -0.088 (-0.182, -0.026) | -0.108 (-0.221, -0.035) | 40 / 40 | 80% / 76% |
| `stanli-ar1-t` | 0.871 (0.832, 0.908) | 0.852 (0.810, 0.893) | -0.070 (-0.114, -0.038) | -0.097 (-0.153, -0.057) | 38 / 40 | 79% / 76% |
| `statsmodels-ladder` | 1.104 (1.010, 1.206) | 0.957 (0.891, 1.012) | -0.018 (-0.085, +0.021) | -0.050 (-0.141, +0.005) | 19 / 31 | 84% / 79% |
| `statsmodels` | 1.175 (1.066, 1.294) | 1.000 (0.929, 1.063) | -0.009 (-0.079, +0.033) | -0.048 (-0.141, +0.008) | 6 / 13 | 84% / 79% |
| persistence | 1 | 1 | 0 | 0 | | 82% / 79% |

What the runs show:

- **The selection rule leads, and one series supplies its lead over a fixed AR(1).**
  W824RC1, Medicare benefits, accounts for the whole gap between
  `stanli-selected-ladder` and `stanli-ar1-t-ladder`: `stanli-ar1-diff-t` scores
  0.049 of persistence's CRPS there. Without that series the ladder ratios read
  0.819 and 0.819 with 60 prints, and 0.820 and 0.816 with 36. `stanli-ar1-t` then
  leads on normalized CRPS (-0.057 against -0.051, -0.076 against -0.059).
- **`stanli-ar1-t` holds across series.** Dropping any one series keeps its ladder
  ratio between 0.810 and 0.824 with 60 prints and between 0.805 and 0.820 with 36.
  The same check moves `stanli-selected-ladder` between 0.765 and 0.819.
- **Ladder mode adds 4 to 7 points of CRPS ratio to the same program.** Its mean
  normalized CRPS moves by at most 0.004, so a run's gain from the format depends on
  which of the two metrics the run reports.
- **The default `statsmodels` candidate moves with the window, and the stanli arms
  barely do.** It scores 1.175 with 60 prints and 1.000 with 36. No stanli arm's
  ratio moves by more than 0.02.
- **Average coverage hides a split by transform.** `stanli-selected-ladder` covers
  74% (60 prints) and 71% (36) on levels, and 86% and 81% on percent changes. With 36
  prints its overall coverage falls to 76% (interval 71% to 80%).
- **A sampler warning predicts a worse forecast for `stanli-ar1-t`.** It warned on
  27 and 35 targets, which scored 0.965 and 0.977 against 0.811 and 0.805 for the
  rest. At least one program stayed clean on every target, so the rule never ran out
  of candidates.

`experiments/stanli_backtest/` holds both runs' summaries, per-series ratios and
per-transform tables.

### What the results leave open

- The backtest compares models and leaves agents untested. The analyst already
  anchors on baselines and moves off them with evidence, so these gains need not
  carry over.
- Every target falls in one period, 2024-04 through 2026-09.
- The series overlap (CPI and PCE components, BEA benefit lines, consumer credit).
  The bootstrap resamples them as independent, so its intervals understate the
  uncertainty when they move together.
- The table compares 11 arms over two windows with no multiple-comparison
  correction. The reading about W824RC1 came after the runs.
- Persistence here uses the same window of ALFRED prints as the other arms. The
  site's baseline reads the ledger's history.

## Ablation plan

To test the pack on agents:

1. Install the `stan` extra in the analyst's environment, since the analyst's lane
   cannot install packages, and confirm that a fit runs in its Linux sandbox.
2. Give the analyst the pack skill below, which runs the stanli built-ins next to
   the default candidates and, in ladder mode, submits the selected candidate's 19
   quantiles.
3. Run matched analyst runs on the same targets, resolver and model, with and
   without the pack, in fast and ladder prompt modes.
4. Score resolved runs through the Brier reward export and apply the gate in
   `docs/pack-promotion.md`.

The spread seen here sets the scale. The target-level standard deviation of the log
CRPS ratio runs from 0.37 (`stanli-ar1-t-ladder`) to 0.66
(`stanli-selected-ladder`). If agent pairs spread like that, detecting a 10% change
at 80% power takes about 100 to 300 matched targets per prompt mode.

Draft pack skill:

> For a repeated numeric series with at least 36 prints, also run
> `stanli-rw-drift-t`, `stanli-ar1-t` and `stanli-ar1-diff-t` on its last 60 prints.
> Skip any candidate whose diagnostics end in a WARNING, then take the one with the
> lowest walk-forward MAE. In ladder mode, submit its 19 posterior quantiles as the
> threshold ladder. Record the candidate JSON in the trace. Move off the candidate
> only with named current evidence, as for any baseline.
>
> Do not use this for a series with fewer than 36 prints, a target more than one
> step past the last print, or a series with a known recent break. Expect 80%
> intervals on levels to run narrow.

## Limitations

- The programs forecast one step ahead and ignore seasonality, release
  calendars and other series.
- The rounding term treats rounding errors as independent.
- A sampler warning flags a candidate but does not drop it; the draft skill does.
- No run covers a history longer than 60 prints or shorter than 36.
- The backtest uses the agent's information set only approximately: the
  vintage grid samples twice a month, so a revision published within two
  weeks of a first print counts as part of it.
- No analyst has used these candidates yet. Fits ran under a macOS deny-write
  sandbox and on CI's ubuntu, and not in the analyst's sandbox.
