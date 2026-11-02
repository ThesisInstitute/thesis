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
kernels with Stan's own NUTS sampler. It needs no per-model C++ compile and
writes no files, so a fit runs inside the analyst's read-only sandbox, where a
CmdStan build cannot. On an Apple-silicon Mac a built-in program (4 chains
of 1,000 draws after 1,000 warmup) fits in 30 to 60 ms, and the first fit in a
process takes about 300 ms.

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
history length give the same draws. A trace that records the program, data and
seed can replay the fit exactly. When the sampler reports a divergence or an
R-hat above 1.01, the diagnostics end with a `WARNING` line; treat that
candidate as unreliable.

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
  --output-dir experiments/stanli_backtest/window60 --window 60
```

RESULTS_PLACEHOLDER

## Ablation plan

The backtest compares models, not agents. To test the pack:

1. Give the analyst a pack skill (draft below) that runs the stanli built-ins
   next to the default candidates and, in ladder mode, submits the selected
   candidate's 19 quantiles.
2. Run matched analyst runs on the same targets, resolver and model, with and
   without the pack, in fast and ladder prompt modes.
3. Score resolved runs through the Brier reward export and apply the gate in
   `docs/pack-promotion.md`.

Draft pack skill:

> For a repeated numeric series with at least 12 prints, also run
> `stanli-rw-drift-t`, `stanli-ar1-t` and `stanli-ar1-diff-t`. Pick the
> candidate with the best walk-forward MAE and 80% coverage closest to 0.8;
> skip any candidate whose diagnostics end in a WARNING. In ladder mode,
> submit its 19 posterior quantiles as the threshold ladder. Record the
> candidate id, program hash and seed in the trace. Move off the candidate
> only with named current evidence, as for any baseline.

## Limitations

- The programs forecast one step ahead and ignore seasonality, release
  calendars and other series.
- The rounding term treats rounding errors as independent.
- A sampler warning flags a candidate but does not drop it.
- The backtest uses the agent's information set only approximately: the
  vintage grid samples twice a month, so a revision published within two
  weeks of a first print counts as part of it.
