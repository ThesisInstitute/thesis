# stanli model candidates

Fit a Stan program in the time-series runner
(`scripts/run_time_series_models.py`) to forecast the next print and record its
posterior predictive distribution as a model candidate.
`brier/stan_candidates.py` runs the program with
[stanli](https://github.com/seantalts/stanli). stanli, by Sean Talts (BSD-3),
ships the Stan compiler, Stan Math and a NUTS sampler in one Python package, so
it runs a Stan program with no per-model C++ compile.

The runner defaults to `persistence,statsmodels-local-level`, and no agent
prompt or skill names these candidates. Before analysts use them by default, the
pack has to pass the ablation that `docs/pack-promotion.md` sets out (see
[Ablation plan](#ablation-plan)).

## Usage

Install the `stan` extra, which pins `stanli==0.25.0`:

```bash
uv run --extra stan --extra experiments python scripts/run_time_series_models.py \
  --target-id bls.cps.unemployment_rate \
  --target-period 2026-10 \
  --history-file /tmp/history.json \
  --models persistence,statsmodels-local-level,stanli-rw-drift-t,stanli-ar1-t \
  --round-increment 0.1
```

The built-in programs fit a standardized history (below) under fixed priors:

| model | process | built for |
|---|---|---|
| `stanli-rw-drift-t` | random walk with drift, Student-t steps | levels that wander, the Bayesian counterpart of `statsmodels-local-level` |
| `stanli-ar1-t` | AR(1) around a fitted mean, Student-t errors | rates and monthly changes that revert |
| `stanli-ar1-diff-t` | AR(1) on one-step changes with drift (ARIMA(1,1,0)), Student-t errors | levels whose changes carry momentum |

`stanli-ar1-t` keeps its coefficient inside (-1, 1). As the coefficient nears 1,
the fitted mean drops out and the program behaves like a random walk without
drift. On the backtest's level series other than W824RC1, its ladder scored a
lower geometric-mean CRPS than either other program's in both windows (see
[Results](#results)).

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
| `y_scale` | a robust scale of the one-step changes. Use `1.4826 × MAD` (their median absolute deviation) when that product exceeds `1.4826 × threshold` in floating-point arithmetic. Otherwise, use `√(π/2) × mean absolute deviation` when the unscaled mean absolute deviation exceeds the threshold. If neither check passes, use the absolute first change, then a positive grid, then 1. The threshold is a millionth of `y_grid` or 1e-12 of the largest absolute print, whichever is larger, so float error in equal decimal changes does not set the scale |
| `y_std` | `(y - y_loc) / y_scale` |
| `y_grid` | the rounding step of the prints (see [Reporting grid](#reporting-grid)) |

Expose a finite scalar output named `y_next`, in raw units, and define it in
generated quantities as one draw from the next print's posterior predictive
distribution. The builder checks the output's name, shape and finite draws. It
refuses a `y_next` declared in parameters, because the R-hat check skips
`y_next`. Write a custom program in one file: the builder and replay refuse any
`#include`, even in a comment, so the candidate JSON carries the whole program.
The builder raises a `ValueError` naming the problem when a program fails to
parse, declares data the contract does not supply, contains `#include`, omits
`y_next`, declares it in parameters, makes it non-scalar, or draws a non-finite
value.

The built-ins fit `y_std` under fixed priors. Multiplying the history and grid
by a power of two multiplies a history- or grid-derived `y_scale` by the same
factor when both calculations stay in the normal floating-point range, including
intermediate arithmetic. When `y_scale` falls back to 1, as for a flat history
with a grid of 0, it doesn't scale. For the histories sampled in the tests,
rescaling the history and an explicit grid by a power of two with the same seed
rescaled every unrounded predictive quantile exactly. The seed comes from the
candidate id, which hashes the periods and not the values, so a rescaling keeps
it. With the grid held fixed, an exact translation preserves `y_scale` when
`1e-12 * max_abs_print <= 1e-6 * grid` holds in floating-point arithmetic before
and after the shift. Otherwise the threshold grows with the largest absolute
print, so a shift can change which fallback sets `y_scale`, and with it the
forecast's width, even when every print and change stays exact. The threshold
applies to the median and mean absolute deviations, not to each change: with a
grid of 0.1, `[0, 0, 1]` has a `y_scale` of 0.7413, and shifted by 1e12 its
deviations fall under the threshold and `y_scale` falls to the grid. `[0, 0, 1, 2, 4]` falls to the grid
when shifted by 2^39, although each of its nonzero deviations, 1, stays above
that threshold of 0.55. Most decimal prints are not exact: a shift changes their
float error, and the sampler can amplify that into quantile differences of Monte
Carlo size. `tests/test_stan_candidates.py` checks both examples on both sides
of the threshold. For the histories sampled in the tests,
shifts of up to 1,000 on a 1/8 grid translate the predictive quantiles up to
floating-point error. Separate tests preserve `y_scale` up to floating-point
error for the sampled histories of tenths and shifts up to 100,000.

## Reporting grid

Agencies round official prints, and rounded series repeat a print often.
Repeated prints can make a Student-t likelihood favor scales near zero and
produce a nearly degenerate forecast.

The built-in programs treat each print as the latent value plus a rounding
error, uniform on half a grid step either way (variance `y_grid^2 / 12`). They
approximate that noise by adding its contribution, from each print a residual
involves, to the squared Student-t scale. A positive reporting grid keeps that
scale bounded away from zero. `tests/test_stan_candidates.py` fits each built-in to a 0.1-grid series
that repeats its print in 40 of 47 changes. With the grid, every fit keeps its
5th to 95th percentiles at least 0.1 apart and passes its diagnostics. With a
grid of 0, every fit squeezes them into less than 0.01 and ends its diagnostics
with a warning.

To infer the grid, the runner rounds each print at the scale of the largest
absolute print, keeping 12 significant digits at that scale. It then sets the
grid to `10^-d`, where d counts the most decimal places among the rounded
prints, trailing zeros dropped. The fit uses the original values. Whole-number
prints get a grid of 1, and float noise such as `0.1 + 0.2` leaves the grid
alone. Python callers can pass `grid=` to `build_stanli_candidate` instead, and
a grid of 0 turns the rounding term off.

## Output

A stanli candidate follows `thesis_model_candidate_v1` with `library`
`stanli`, `intervalMethod` `posterior_predictive`, and point, p10 and p90 at
the predictive median, 10th and 90th percentiles (rounded to
`--round-increment` when given, then widened to bracket the point strictly,
by the next float where a step of the increment can't move an endpoint).
It adds a `posteriorPredictive` block:

- `quantiles`: 19 predictive quantiles at probabilities 0.05 to 0.95, unrounded;
- `draws`, `chains`, `warmup`, `samplesPerChain`, `seed` and `roundIncrement`;
- `standardization`: `yLoc`, `yScale`, `yGrid`, and `gridInferred`, true when
  the runner inferred the grid;
- `sampler`: divergent transitions, then, over the model's quantities that vary
  across draws other than `y_next`, the largest finite R-hat, the smallest finite
  bulk ESS (each null when the sampler reports no finite value) and the count of
  non-finite R-hats; and
- `program`: the model name, the Stan source and its SHA-256.

The seed derives from the candidate id, so the same target, cutoff, model and
history give the same draws. The builder ends the diagnostics with a `WARNING`
line when the sampler reports a divergence, an R-hat above 1.01 or a non-finite
R-hat, and with another when neighboring predictive quantiles tie, since tied
quantiles can't form a ladder. Treat a candidate with either warning as
unreliable.

A candidate's JSON carries its program, history, grid, rounding increment and
seed, so a trace that records the JSON can replay the fit:

```bash
uv run --extra stan python scripts/run_time_series_models.py --replay-stanli candidates.json
```

The command refuses a stanli candidate that no build of this version could have
produced: a source that doesn't match its hash or model name, a built-in whose
source isn't this version's program, a source with `#include`, sampler settings
other than this version's, quantiles at levels other than the 19, or a candidate
id, seed, standardization or inferred grid that doesn't follow from the record.
It also refuses a file that `json.loads` can't parse or that repeats a key in an
object. In the file, it refuses a record with a missing field, one it can't read
and one whose fit fails. It also refuses a record whose `modelName` isn't a
string, and one that names a stanli model or carries a posterior predictive
block but whose library isn't exactly `stanli`. It rebuilds every other
candidate from its history, grid, rounding increment and program, the
walk-forward score included when the record has one, and compares the rebuild
with the record field by field as JSON. So a value the builder would type, name
or nest differently counts as a mismatch, and so does a missing or extra field.
It names the fields that differ and exits 1 on any refusal or mismatch.

Builds before commit 22b08c84 left an interval endpoint on the point when a step
of the rounding increment couldn't move it off, as at `1e14` with an increment
of 0.0001. This version moves such an endpoint to the next float out and
refuses an endpoint that isn't finite, in the candidate's own fit and in each
walk-forward fit, so a default replay flags or refuses those records. When an
endpoint of the record sits on the point, the mismatch or refusal line names
`--legacy-endpoints`. A record built before that commit can need the option even
when its own endpoints sit off the point, since its walk-forward fits followed
the earlier rule too. The option rebuilds the candidate's own fit and each
walk-forward fit with the earlier rule and changes nothing else, so every field
must still match the record. The fixtures
`tests/fixtures/stanli_b30fab99_narrow_candidate.json` and
`tests/fixtures/stanli_b30fab99_scored_candidate.json`, built at commit
b30fab99, replay only with it.

`tests/test_stan_candidates.py` replays every built-in and a custom program
through a JSON round trip, checks that the rebuild equals the record, and checks
that replay refuses or flags an edit to each field. Those tests replay on the
machine that fitted, and no test compares platforms. Replay flags a record from
another stanli version, and the JSON records no platform.

When walk-forward scoring is on and the history is long enough, the builder
also scores up to 24 trailing one-step cutoffs. Each fit uses the full training
history's reporting grid. Otherwise `backtestScore` is null.

## Publishing a stanli forecast

In fast mode, an agent publishes a point and an 80% interval. It takes the
candidate's point, p10 and p90, and Thesis seeds an `interval_anchor_v1` CDF
from them, and the site rounds each of its values to 12 significant digits.
Rounding to 12 significant digits can merge adjacent CDF values. At
a point of `1e14`, an interval of `1e14 ± 1,000` gives 29 distinct values among
201 points and fails validation. Quantiles that tie add a warning, but a narrow
interval with distinct quantiles
doesn't: [issue 477](https://github.com/ThesisInstitute/thesis/issues/477)
tracks refusing such a CDF before it reaches the site.

In ladder mode, an agent publishes a threshold ladder, and the 19 posterior
quantiles form one: the quantile values set the thresholds, probabilities 0.05
to 0.95 set the cumulative probabilities, and the ladder's own q50, q10 and q90
set the stated point and interval. Keep the thresholds unrounded, since rounding
can tie neighboring rungs, which the ladder check rejects.
`tests/test_backtest_stanli_candidates.py` runs a stanli ladder through
`ladder_validation_errors`.

## Backtest

`scripts/backtest_stanli_candidates.py` replays every series a Thesis ALFRED
adapter resolves (46 after merging unit variants of the same FRED series) in
real time:

- It downloads ALFRED vintages on the 1st and 16th of each month from 2024-06-01
  through 2026-11-01. It caches a download only after parsing it, and parses a
  cached file the same way when it reads it. The parser refuses a header column
  that isn't one vintage of the series on a real date, a repeated vintage, a
  quote left open, a row whose cell count differs from the header's, an
  observation date that isn't a real YYYY-MM-DD date or repeats, a value that
  isn't a finite ASCII decimal such as `-2.5` or `1e3`, a body without a final
  line break, and a body with no rows. An empty cell or `.` marks a missing
  value. A body cut exactly at a line break passes these checks; `urlopen`
  raises `IncompleteRead` when a download stops short of its stated length.
- For each period it trains on the last sampled vintage without the period,
  reads the period's cadence from that vintage, and transforms that vintage's
  prints as the resolver does. It scores against the earliest sampled vintage
  that holds the period. Vintages are sampled twice a month, so that vintage can
  include revisions published after the first print. A period that any earlier
  sample held is never a new release, even when a later sample drops it and the
  next restores it.
- The models treat adjacent available prints as consecutive steps. In each run,
  111 training windows in 12 series contain a calendar gap: the latest vintage
  has no October 2025 print for UNRATE, U6RATE and CIVPART, and no October or
  November 2025 one-month change for the nine CPI, import price and export
  price series.
- Every arm forecasts one step ahead from the same last `--window` prints, and
  the script scores it by CRPS on the site's 201-point CDF.
  `tests/test_backtest_stanli_candidates.py` checks that the Python CRPS port
  gives the same CRPS and PIT as the site's `scoreNumericCdfDistribution`, bit
  for bit, on 120 random cases.
- The script divides CRPS by the sample standard deviation of the training
  window's one-step changes, the statistic the site's `ledgerStepDispersion`
  computes on the ledger's history. As the site does, it leaves normalized CRPS
  out when that scale is at or below 1e-12 times the window's largest absolute
  print.
- Each target's sampler seeds derive from its series and period.
- The script bootstraps the 95% intervals by resampling whole series.

```bash
uv run --extra stan --extra experiments python scripts/backtest_stanli_candidates.py \
  --output-dir experiments/stanli_backtest/window60 --window 60 --walk-forward --jobs 4
```

The 36-print run passes `--window 36` and writes to `window36`.

Each forecaster runs in two shapes. Its interval arm publishes a point and an
80% interval as an `interval_anchor_v1` CDF, as a fast-mode agent does. Its
ladder arm publishes 19 quantiles as an `agent_cdf_v1` ladder, as a ladder-mode
agent does.

| forecaster | interval arm | ladder arm |
|---|---|---|
| the last print | `persistence`, with the site's 80% interval | `persistence-ladder`, with the window's one-step changes at quantiles 0.05 to 0.95 |
| the default SARIMAX random walk with drift | `statsmodels` | `statsmodels-ladder`, its Gaussian quantiles |
| each stanli program | `stanli-ar1-t` and so on | `stanli-ar1-t-ladder` and so on |
| a rule that picks one program per target | `stanli-selected` | `stanli-selected-ladder` |
| the rule without its skip | `stanli-selected-noskip` | `stanli-selected-noskip-ladder` |

`--walk-forward` adds the last two rows. For each target, `stanli-selected`
drops the programs whose diagnostics warn, then takes the one with the lowest MAE
over the training history's last 24 cutoffs, with coverage nearest 80% breaking
exact ties. The `noskip` arms keep every program. Those inner fits read the
target's training vintage and reporting grid, so they can include revisions and
precision that were not available at the historical cutoffs.

Commit 33a078aa records the three programs and their priors, specifies a
60-print backtest, and proposes choosing among programs by walk-forward MAE and
coverage for series with at least 12 prints. We made it after a pilot on four
series, about four minutes into a first full run, which stopped unfinished. A
second full run scored the three programs on both windows, and we read its
results before commit 9f3d82b9 made coverage break exact MAE ties. Commit
0fb35048 first reports both windows, and its draft skill sets the 36-print
minimum and fits the last 60 prints. We later changed grid inference and seed
derivation, added the `persistence-ladder` and `noskip` arms, and, after reading
those reruns, chose a fixed `stanli-ar1-t` for the
[draft skill](#draft-pack-skill).

### Results

Both runs cover 46 series and 1,047 targets, for periods from 2024-04 through
2026-09, and no series failed. We report each arm's geometric-mean CRPS over its
baseline's (the CRPS ratio) and its mean normalized CRPS minus the baseline's
(the difference), with 95% intervals. Each run normalizes by its own window's
changes, so compare differences only within a window. No forecast scored a CRPS
of zero, so every ratio covers all 1,047 targets.

We compare each interval arm with the site's persistence interval:

| arm | CRPS ratio, 60 prints | CRPS ratio, 36 prints | difference, 60 prints | difference, 36 prints | series beating persistence (of 46), 60 / 36 | 80% coverage, 60 / 36 |
|---|---:|---:|---:|---:|---:|---:|
| `stanli-selected` | 0.834 (0.736, 0.906) | 0.822 (0.728, 0.898) | -0.086 (-0.176, -0.026) | -0.109 (-0.224, -0.035) | 39 / 39 | 79% / 76% |
| `stanli-selected-noskip` | 0.824 (0.709, 0.906) | 0.811 (0.697, 0.899) | -0.091 (-0.193, -0.026) | -0.111 (-0.231, -0.035) | 39 / 39 | 80% / 76% |
| `stanli-ar1-t` | 0.871 (0.833, 0.909) | 0.852 (0.810, 0.893) | -0.069 (-0.113, -0.037) | -0.098 (-0.153, -0.057) | 38 / 39 | 79% / 77% |
| `stanli-ar1-diff-t` | 0.871 (0.750, 0.954) | 0.869 (0.746, 0.957) | -0.073 (-0.174, -0.009) | -0.089 (-0.207, -0.015) | 33 / 34 | 80% / 77% |
| `stanli-rw-drift-t` | 0.977 (0.925, 1.021) | 0.968 (0.906, 1.021) | -0.033 (-0.096, +0.004) | -0.051 (-0.141, +0.004) | 11 / 12 | 80% / 79% |
| `statsmodels` | 1.175 (1.066, 1.294) | 1.000 (0.929, 1.063) | -0.009 (-0.079, +0.033) | -0.048 (-0.141, +0.008) | 6 / 13 | 84% / 79% |
| `persistence-ladder` | 0.891 (0.847, 0.929) | 0.896 (0.835, 0.947) | -0.039 (-0.102, -0.001) | -0.051 (-0.140, +0.003) | 41 / 37 | 79% / 75% |
| `persistence` | 1 | 1 | 0 | 0 | | 82% / 79% |

We compare each ladder arm with `persistence-ladder`:

| arm | CRPS ratio, 60 prints | CRPS ratio, 36 prints | difference, 60 prints | difference, 36 prints | series beating `persistence-ladder` (of 46), 60 / 36 | 80% coverage, 60 / 36 |
|---|---:|---:|---:|---:|---:|---:|
| `stanli-selected-ladder` | 0.872 (0.795, 0.935) | 0.872 (0.810, 0.931) | -0.051 (-0.086, -0.016) | -0.058 (-0.094, -0.024) | 37 / 31 | 79% / 76% |
| `stanli-selected-noskip-ladder` | 0.861 (0.767, 0.934) | 0.859 (0.776, 0.930) | -0.057 (-0.101, -0.018) | -0.060 (-0.099, -0.025) | 37 / 31 | 80% / 76% |
| `stanli-ar1-t-ladder` | 0.915 (0.869, 0.967) | 0.904 (0.847, 0.971) | -0.033 (-0.065, +0.003) | -0.046 (-0.086, +0.005) | 30 / 32 | 79% / 77% |
| `stanli-ar1-diff-t-ladder` | 0.911 (0.815, 0.977) | 0.922 (0.836, 0.986) | -0.039 (-0.080, -0.003) | -0.039 (-0.075, -0.006) | 31 / 27 | 80% / 77% |
| `stanli-rw-drift-t-ladder` | 1.023 (1.011, 1.033) | 1.027 (1.015, 1.040) | +0.002 (-0.001, +0.005) | -0.001 (-0.005, +0.003) | 8 / 10 | 80% / 79% |
| `statsmodels-ladder` | 1.240 (1.139, 1.368) | 1.068 (1.030, 1.117) | +0.021 (+0.011, +0.032) | +0.001 (-0.004, +0.006) | 7 / 12 | 84% / 79% |
| `persistence-ladder` | 1 | 1 | 0 | 0 | | 79% / 75% |

We also compare the selection rule's arms on the same targets with
`stanli-ar1-t` and with the rule without its skip:

| comparison | 60 prints | 36 prints | 60 prints, without W824RC1 | 36 prints, without W824RC1 |
|---|---:|---:|---:|---:|
| `stanli-selected-ladder` over `stanli-ar1-t-ladder` | 0.952 (0.855, 1.017) | 0.965 (0.874, 1.025) | 1.000 (0.978, 1.023) | 1.008 (0.984, 1.032) |
| `stanli-selected` over `stanli-ar1-t` | 0.957 (0.866, 1.016) | 0.966 (0.878, 1.022) | 1.001 (0.982, 1.022) | 1.008 (0.988, 1.027) |
| `stanli-selected-ladder` over `stanli-selected-noskip-ladder` | 1.012 (1.000, 1.036) | 1.016 (0.999, 1.049) | 1.001 (1.000, 1.002) | 1.000 (0.999, 1.002) |
| `stanli-selected` over `stanli-selected-noskip` | 1.012 (1.000, 1.036) | 1.014 (0.999, 1.045) | 1.001 (1.000, 1.002) | 1.000 (0.999, 1.001) |

`persistence-ladder` scores 0.891 (0.847, 0.929) against the site's persistence
interval with 60 prints and 0.896 (0.835, 0.947) with 36, though its 36-print
difference interval reaches zero. Before it adjusts tied rungs, its median adds
the window's median change to the last print, so it also follows a trend. Against that stronger baseline,
`stanli-ar1-t-ladder` scores 0.915 (0.869, 0.967) with 60 prints and 0.904
(0.847, 0.971) with 36. Its difference intervals reach zero in both windows:
-0.033 (-0.065, +0.003) and -0.046 (-0.086, +0.005).

`stanli-ar1-t` gains most on percent changes. Against `persistence-ladder`, its
ladder scores 0.845 on the 20 percent-change series with 60 prints and 0.807
with 36. On the 24 level series other than W824RC1, it scores 0.955 and 0.965,
`stanli-ar1-diff-t-ladder` scores 0.964 and 0.982, and
`stanli-rw-drift-t-ladder` scores 1.010 and 1.020.

W824RC1, Medicare benefits at a seasonally adjusted annual rate, moves by a
near-constant step. In the November 1, 2026 ALFRED vintage, its last 60 monthly
prints rise by an average of $7.6 billion each month, and in 54 of 58
consecutive pairs of monthly changes, the two changes differ by $0.5 billion or
less. `stanli-ar1-diff-t` can learn to repeat the last change, and there it
scores 0.056 of persistence's CRPS with 60 prints and 0.051 with 36, while
`stanli-ar1-t-ladder` scores 1.57 and 2.06 times `persistence-ladder`'s.
`stanli-selected` used `stanli-ar1-diff-t` on 18 of the series' 24 targets with
60 prints and 15 with 36.

That one series supplies the rule's whole lead over `stanli-ar1-t`. Without it,
the paired ladder ratio moves from 0.952 to 1.000 (0.978, 1.023) with 60 prints
and from 0.965 to 1.008 (0.984, 1.032) with 36. The rule picked a program other
than `stanli-ar1-t` on 547 of the 1,047 targets with 60 prints and 567 with 36,
and off W824RC1 those picks gained nothing on net. W824RC1 also supplies the
rule's edge on the difference, where its ladder beats `persistence-ladder` in
both windows, with intervals of (-0.086, -0.016) and (-0.094, -0.024). Without
W824RC1, `stanli-ar1-t-ladder` scores 0.904 (0.862, 0.947) against
`persistence-ladder` with 60 prints and 0.887 (0.837, 0.939) with 36. Its
differences then fall to -0.046 (-0.072, -0.026) and -0.065 (-0.093, -0.039),
against -0.040 (-0.070, -0.011) and -0.048 (-0.078, -0.018) for the rule's
ladder.

The skip changed the rule's pick on 13 targets with 60 prints and 16 with 36.
In the ladder arms, the rule with the skip scores 1.012 (1.000, 1.036) times the
rule without it with 60 prints and 1.016 (0.999, 1.049) with 36. W824RC1 holds 6
of the 13 changed picks and 9 of the 16, and nearly all of the gap: without it,
the ratio falls to 1.001 and 1.000. There `stanli-ar1-diff-t` warned on 6
targets with 60 prints and 9 with 36, and it still forecast best of the three
programs on 6 and 8 of them. On every one, the skip moved the rule to
`stanli-rw-drift-t`.

`stanli-ar1-t` forecast worse where its sampler warned, and `stanli-ar1-diff-t`
forecast better. With 60 prints, `stanli-ar1-t` warned on 22 targets across 11
series. There its ladder scored 0.894 against persistence and
`persistence-ladder` scored 0.842, against 0.814 and 0.892 on the other 1,025
targets. With 36 prints, it warned on 25 targets across 14 series, where its
ladder scored 0.953 and `persistence-ladder` 0.914, against 0.807 and 0.895 on
the other 1,022. `stanli-ar1-diff-t` warned on 10 targets with 60 prints, 6 on
W824RC1 and 4 on W055RC1 (personal current taxes), and on 13 with 36: 9 on
W824RC1, 3 on W055RC1 and 1 on A191RL1Q225SBEA (real GDP growth). It scored
0.183 of persistence's CRPS on its warned targets against 0.884 elsewhere with
60 prints, and 0.150 against 0.888 with 36. `stanli-rw-drift-t` warned on 2 targets with 60 prints, both on
CUSR0000SEHA, and on none with 36. Every warning came from the sampler, none
from tied quantiles, and at least one program fit cleanly on every target in
both windows.

The default `statsmodels` candidate's score moves with the window, and the
stanli arms' scores barely do. `statsmodels` scores 1.175 against persistence
with 60 prints and 1.000 (0.929, 1.063) with 36. On A063RC1, government social
benefits at a seasonally adjusted annual rate, its 60-print ratio reaches 3.73.
That series jumped from $3,235.1 billion in March 2020 to $6,397.7 billion in
April, and from $4,157.0 billion in February 2021 to $8,134.5 billion in March.
Of its 24 targets' 60-print windows, 17 contain the 2021 jump, seven of those
also contain the 2020 jump, and the other seven contain neither. The 36-print
windows start after both jumps, and with 36 prints its ratio falls to 0.837.
With 60 prints, `statsmodels` covered all 24 A063RC1 targets, and the stanli
programs scored 0.79 to 0.85. On the 97 targets whose 60-print window starts in
July 2021 or later, `statsmodels` scores 1.019, and its 60-print ratio falls
from 1.305 in the earlier half of the period to 1.061 in the later half. No
stanli arm's ratio moves by more than 0.02 between windows, and with 60 prints
`stanli-ar1-t` scores 0.886 and 0.857 in the two halves.

`stanli-ar1-t`'s 80% intervals run narrow on levels. With 60 prints they cover
73% of level targets and 87% of percent-change targets, against 77% and 88% for
persistence's interval. With 36 prints they cover 71% and 83%, against 73% and
87%.

When we drop any one series, `stanli-ar1-t-ladder` scores between 0.904 and
0.927 against `persistence-ladder` with 60 prints and between 0.887 and 0.916
with 36. `stanli-selected-ladder` scores between 0.864 and 0.904, and between
0.865 and 0.894.

### What the results leave open

- The backtest compares models and leaves agents untested. The analyst's prompt
  tells it to anchor on the strongest benchmark and move off it only with current
  evidence, so these gains need not carry over.
- The backtest covers target periods from April 2024 through September 2026.
- The series overlap (CPI and PCE price indexes, BEA benefit lines, consumer
  credit). The bootstrap resamples each series independently, so when paired
  score differences move together across related series, its intervals can be
  too narrow.
- We compare 14 arms over two windows with no multiple-comparison correction,
  and we chose every subset above (W824RC1, the warning split, the period
  halves, the late windows and the transforms) after reading the full runs'
  results.
- Persistence here reads the same window of ALFRED prints as the other arms,
  while the site's baseline reads the ledger's history. We built
  `persistence-ladder` for this backtest, and no analyst run has used it.
- The draft skill excludes a series that moves by a near-constant step, but no
  rule defines one, and W824RC1 alone moves that way here. The ablation scores
  every matched target, so the agent's reading of that exclusion is part of the
  treatment.

## Ablation plan

To test the pack on agents:

1. Install the `stan` extra in the analyst's environment and confirm that a fit
   runs in its Linux sandbox. stanli 0.25.0 publishes wheels only. Its Linux
   wheels need glibc 2.28 or newer on x86_64 or aarch64, and none covers musl.
   CI installs every extra, so a runner without a matching wheel would fail the
   whole sync.
2. Give the analyst the draft skill below. It adds `stanli-ar1-t` to the
   default candidates and, in ladder mode, has the agent submit its 19
   quantiles.
3. Run matched analyst runs on the same targets, resolver and model, with and
   without the skill, in fast and ladder prompt modes. Choose the targets
   without reference to the skill's exclusions or its warning fallback. The
   agent applies the exclusions and the fallback itself, and the analysis scores
   every matched target, so both count as part of the treatment. Report the
   targets where the agent used the candidate as a secondary subgroup analysis.
4. Score resolved runs through the Brier reward export and apply the gate in
   `docs/pack-promotion.md`, which measures accuracy by normalized CRPS first
   and interval coverage second.

We sized the ablation from the backtest, using the ladder model's log CRPS as a
proxy for the paired agent difference. Against `persistence-ladder`, the log
CRPS ratio of `stanli-ar1-t-ladder` has a target-level standard deviation of
0.40 with 60 prints and 0.53 with 36. Targets in one series correlate, with
intraclass correlations of 0.17 and 0.16 from a one-way ANOVA. On that proxy, we
estimate 532 matched targets, or 25 independent series, for 80% power to detect
a 10% reduction in geometric-mean CRPS with 60 prints. With 36 prints, the
estimates are 880 targets or 39 series. The target count allows for clustering
within series, and the series count treats each series mean as one observation.
Both assume about 23 targets per series, as in the backtest. A 5%
reduction takes about 2,250 targets or 104 series with 60 prints, and 3,710
targets or 163 series with 36, more than the 46 series here. The paired agent
study will need its own power calculation for mean normalized CRPS, the gate's
primary metric. Across all 1,047 model-backtest targets, the fixed ladder cuts
geometric-mean CRPS by 8.5% with 60 prints and 9.6% with 36 against
`persistence-ladder`. The paired agent study will estimate the effect of giving
agents this candidate.

### Draft pack skill

We also tested a rule that picks among the three programs by walk-forward MAE
and skips any that warns. On the gate's primary metric, normalized CRPS, the
rule's ladder beats `persistence-ladder` in both windows while
`stanli-ar1-t-ladder`'s intervals reach zero, but W824RC1 supplies that edge. On
the other 45 series, the rule's ladder scores 1.000 and 1.008 times
`stanli-ar1-t-ladder`'s in the two windows. On W729RC1 (Medicaid), the rule used
`stanli-ar1-diff-t` on all 24 targets in both windows and scored 1.218 and 1.212
of persistence's CRPS, against 0.992 and 1.015 for `stanli-ar1-t`. On mean normalized CRPS, the rule's ladder minus
`stanli-ar1-t-ladder`'s is -0.018 (-0.073, +0.020) with 60 prints and -0.012
(-0.079, +0.031) with 36, and without W824RC1 it is +0.006 (-0.009, +0.026) and
+0.017 (-0.0001, +0.037), whose lower end sits at zero. The rule's edge comes
from one series, so the draft runs `stanli-ar1-t` alone.

We will test a fixed `stanli-ar1-t` candidate with a warning fallback. On warned
targets, its ladder's geometric-mean CRPS ratios against `persistence-ladder`
were 1.063 with 60 prints and 1.042 with 36. Its mean normalized CRPS minus
`persistence-ladder`'s was +0.048 with 60 prints and -0.006 with 36. Using
`persistence-ladder` on the warned targets moves the full sample's mean
normalized CRPS by -0.001 (-0.003, +0.0003) with 60 prints and +0.000 (-0.003,
+0.004) with 36. The backtest neither supports nor rules out the fallback. We
keep it because a sampler warning means the draws may not represent the
posterior. With 60 prints, `stanli-ar1-t-ladder` also varies less from target to
target than the rule's, so on the same proxy a 10% test needs about 25 series
against the rule's 56. With 36 prints, the two need about 39 and 40.

> For a repeated numeric series with at least 36 prints, also run
> `stanli-ar1-t` on its last 60 prints. If its diagnostics end in a WARNING,
> forecast as you would without this skill. Otherwise treat it as a baseline
> candidate, and in ladder mode submit its 19 posterior quantiles as the
> threshold ladder. Record the candidate JSON in the trace. Move off the
> candidate only with named current evidence, as for any baseline.
>
> Do not use this for a series with fewer than 36 prints, a target more than one
> step past the last print, a series with a known recent break, or a series that
> moves by a near-constant step each print. Expect its 80% intervals on levels
> to run narrow.

## Limitations

- The programs forecast one step ahead and ignore seasonality, release
  calendars and other series.
- The programs ignore the correlation that shared rounding errors induce across
  neighboring residuals.
- A sampler warning flags a candidate but doesn't drop it. The draft skill falls
  back when one appears.
- No run covers a history longer than 60 prints or shorter than 36.
- The backtest scores each target against the earliest sampled ALFRED vintage
  that contains it. Vintages are sampled twice a month, so that sample can
  already include a revision to the first release.
- We have fit the programs under a macOS deny-write sandbox and on CI's Ubuntu
  runner, but not in the analyst's Linux sandbox.
