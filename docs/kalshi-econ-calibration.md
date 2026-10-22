# Kalshi's calibration on economic-release series

This is a read-only study of Kalshi's own track record on the twelve series
that the Thesis-vs-Kalshi paper comparison
([docs/kalshi-paper-comparison.md](kalshi-paper-comparison.md), PR #381)
scored. It measures how well Kalshi's prices were calibrated, and how well they
scored, against the official first print of each statistic. It places no
orders, holds no positions, simulates no trading and uses no Kalshi account:
every Kalshi number comes from the public, unauthenticated market-data API.

`scripts/kalshi_calibration_study.py` will implement everything below. Results
are written outside the repository (`--out`); this document is the analysis
plan.

## Why

A 2026 paper, "Calibration, accuracy, and domain variation across one million
collective forecasts from prediction platforms" (PNAS 2026, doi
10.1073/pnas.2615627123; open preprint "The knowability of the future",
PsyArXiv, https://osf.io/g4ja9_v1), reports that in its markets with more than
$20,000 of volume Kalshi's prices sat too close to 50%: probabilities below 50%
were too high and probabilities above 50% too low. If that holds on these
economic series, #381's Kalshi baseline would be beatable by a recalibrated
Kalshi baseline, and #381's comparisons would understate how hard the baseline
is.

The paper's result cannot simply be carried over:

- its data (Project Themis) ends in November 2025, and its public data service
  was not reachable when this plan was written;
- it treats every strike of a Kalshi event as an independent binary market;
- its Kalshi drill-down pools many categories. The preprint's Figure S5, the
  high-volume sample, is captioned as excluding the Economy and Sports domains,
  so the reported Kalshi pattern may not involve these series at all.

So this study measures Kalshi on these series directly.

## Status of this plan

Written on 2026-10-22, before any Kalshi price was compared with any outcome
and before any score was computed. Before writing it the author had looked at:

- the event and market records of every event in the twelve series (titles,
  rule text, strike fields, the `result` and `expiration_value` fields, lifetime
  volume, open and close times, API tier), to learn the contract formats;
- which fields (not their values) are present in the hourly candlesticks of
  seven markets from 2021 to 2025, to check that bid and ask history exists for
  old markets;
- the BLS release archive index pages for CPI, the Employment Situation and
  JOLTS;
- the preprint's methods and Project Themis's Kalshi extraction code
  (`wasabipesto/themis` at 063f65b5).

Any later change to this specification will be listed in the results, and in
the last section of this document, as a deviation.

## Events in scope

- **Series.** KXCPI, KXCPICORE, KXU3, KXPAYROLLS, KXJOBLESSCLAIMS,
  KXCONTCLAIMS, KXJOLTSOPEN, KXPCECORE, KXHOUSINGSTART, KXBUILDPERMS, KXNHSALES
  and KXUE, with #381's statistic, grid, unit and official source for each
  (`scripts/kalshi_compare/contracts.py`).
- **Events.** Every event Kalshi lists for the series ticker
  (`GET /events?series_ticker=...`), from the start of each series. Kalshi
  lists legacy events inside several of these series (for example `CPI-21JUN`
  in KXCPI, `PROLLS-23OCT` and `PAYROLLS-24FEB` in KXPAYROLLS); they are in
  scope like any other event of the series.
- **KXUE.** Australian events only (ticker prefix `KXUE-AUS`), as in #381; the
  official parser exists only for the ABS. Other countries' KXUE events are
  counted and not scored.
- **Settled.** An event is settled when every market in it has a `result` of
  `yes` or `no` at the data cutoff (the run's `--as-of`). A market with any
  other result in an otherwise settled event is listed and dropped.
- **Reference period.** Read from the event title and every market's rule text,
  as in #381 (`contracts.event_period`). An event whose period cannot be read
  is listed and not scored. If Kalshi lists two events for one series and
  period, both are scored and both are listed.
- **Not in scope.** Other Kalshi series on the same statistics (older or second
  venues such as KXJOBLESS or KXUSNFP) are not scored; the report lists each
  with its event count.

## Reading a contract

Each market's strike and direction come from its own rule text, as in #381,
with three additions for legacy markets:

- When `strike_type` is empty, the direction comes from the rule's wording
  ("more than" or "above" is `greater`; "at least" is `greater_or_equal`).
- When the rule text names no number (some 2021 and 2022 U-3 rules read "above
  %"), the number comes from the market's `yes_sub_title` ("Above 3.4%"),
  which must equal the number in the ticker suffix (`T3.4`).
- `floor_strike`, when present, must equal the strike read from the text.

A market whose strike cannot be read this way is listed and dropped from its
event. Every event's markets must share one direction.

## Outcomes

- **Official first print.** The value of the statistic for the reference
  period in the first official release that publishes it, read with #381's
  parsers (`scripts/kalshi_compare/official.py`). Parsers are extended only
  where an older release words or lays out the same table differently; each
  extension is tested on a stored excerpt of a real release, and #381's own
  results must reproduce byte for byte from its stored responses afterwards.
- **Finding the release.** For BLS statistics, the release is found in the
  agency's archive index (`bls.gov/bls/news-release/<release>.htm`): the first
  archived release whose own title and table header name the reference period.
  The DOL weekly claims release is found by the event's market close date and
  then the neighbouring days, the BEA release by its period in the URL under
  the period's year and then the following year, and Census and ABS releases
  as in #381. The document's own title, table header and embargo statement
  decide the period and the release instant.
- **Delayed releases.** If a release was delayed or merged (for example by a
  government shutdown), the first print is the period's value in the first
  release that publishes it, even if that release is titled for a later month
  (for example a prior-month column). If no official value for the period was
  ever published, the event has no official outcome. It is excluded from the
  primary analysis and listed with Kalshi's recorded settlement.
- **Differential check.** For every settled market of an event with an
  official print, the print applied to the market's rule (`>` for `greater`,
  `>=` for `greater_or_equal`) must reproduce Kalshi's recorded `result`. Every
  disagreement is listed. The official print governs the primary analysis. The
  report also gives the agreement between the print and Kalshi's
  `expiration_value` where that field holds a number.
- **Sensitivity.** All analyses are repeated with Kalshi's recorded results as
  outcomes for every settled market, which adds the events with no official
  print.

## Anchor and horizons

- **Release instant.** The time the agency's release states, as in #381.
- **Anchor.** The release instant, or the latest close time among the event's
  markets if that is earlier. For an event released on schedule the two differ
  by minutes; for a delayed release the anchor is when trading stopped.
- **Fixed horizons.** The anchor minus 30 days, minus 7 days and minus 1 day.
  The same instant applies to every market of the event.
- **Life fractions (matching the paper).** 25%, 50% and 75% of a market's life.
  For a single market the life runs from its `open_time` to its `close_time`.
  For an event (brackets) it runs from the earliest `open_time` among its
  markets to the anchor.
- A market enters a horizon only if it opened at or before the instant and has
  an hourly candle ending at or before it. Markets open but not yet quoted, and
  events with no market quoted, are listed. Results are never pooled across
  horizons.

## Prices

- **Primary.** The midpoint of the closing yes bid and yes ask of the latest
  hourly candlestick (`period_interval=60`) ending at or before the instant,
  from the live or historical tier, with an empty bid read as 0 and an empty
  ask as 1 (#381's rule). Within an event at an instant, P(yes) must not rise
  with the strike; violations are repaired by unweighted pooled-adjacent-
  violators isotonic regression (#381's rule) and counted. A market's price in
  every analysis is its repaired value, so the binary and bracket analyses use
  the same numbers.
- **Raw-price sensitivity.** The unrepaired midpoint, for the binary analyses.
- **Liquid-only sensitivity.** Only quotes with a spread of 20 cents or less.
- **Paper-matched variant.** The last traded price (the closing trade price of
  the latest hourly candle with a trade, ending at or before the instant), no
  repair. A market's life for the life fractions then runs from the start of
  its first hourly candle with a trade to its `close_time`, as Themis measures
  it from the first trade. Markets never traded are excluded, as in the paper.
  This variant is also reported on markets with lifetime volume above 20,000
  contracts, the paper's threshold: Themis stores Kalshi's contract count
  `volume` as `volume_usd`.

## Units of analysis

- **Binary markets** (the paper's unit): each settled market at each horizon,
  with its price p and its outcome y.
- **Events** (#381's unit): each settled event at each horizon, with Kalshi's
  bracket probabilities from its repaired ladder (n strikes give n + 1
  brackets following each contract's `>` or `>=` wording, as in #381) and the
  realized bracket.

Strikes within one event are not independent, and events released on the same
day (headline and core CPI; U-3 and payrolls; initial and continuing claims;
housing starts and permits) are correlated. Every interval in this study is a
cluster bootstrap over **release dates** (primary) or over **events**
(secondary), never over markets.

## Groups

- **Families.** Inflation (KXCPI, KXCPICORE, KXPCECORE); monthly labor (KXU3,
  KXPAYROLLS, KXJOLTSOPEN); weekly claims (KXJOBLESSCLAIMS, KXCONTCLAIMS);
  housing (KXHOUSINGSTART, KXBUILDPERMS, KXNHSALES); Australian unemployment
  (KXUE). Plus all series pooled.
- **Per series.** Reported in tables; a series with fewer than ten settled
  events gets its numbers and the plain statement that there are too few
  events to conclude anything about it alone.
- **Secondary splits.** Legacy tickers versus KX tickers; release before
  2025-01-01 versus after; lifetime volume above versus at most 20,000
  contracts.

## Calibration

- **Reliability diagrams.** For each family and horizon, binary markets are
  binned by p into ten equal-width bins ([0, 0.1), ..., [0.9, 1]). Each bin
  reports its counts (markets, events, release dates), mean p, observed
  frequency, and a 95% percentile interval for the observed frequency from
  10,000 release-date cluster bootstrap draws (fixed seed).
- **Summary statistics.** Binary Brier score and its Murphy decomposition
  (reliability, resolution, uncertainty, over the ten bins), expected
  calibration error over the ten bins, and the paper's pattern directly: the
  mean of y − p over markets with p < 0.5 and over markets with p > 0.5, each
  with its cluster interval.

## Compression toward 50%

- **Model.** Logistic calibration: logit P(y = 1) = α + β logit(p̃), where p̃
  is p clipped to [0.001, 0.999], fitted by maximum likelihood.
- **Reading.** β > 1 means outcomes are more extreme than prices, that is,
  prices are compressed toward 50% (the paper's Kalshi pattern). β < 1 means
  prices are too extreme. α shifts all probabilities up or down.
- **Primary tests.** β for all series pooled at each of the six horizons, with
  a 95% interval from 2,000 release-date cluster bootstrap draws, refitting
  each draw (fixed seed). A horizon shows compression if the interval lies
  above 1 and over-extremity if it lies below 1; otherwise the report says
  neither is shown and gives the interval. Per-family β is secondary. Six
  primary intervals are reported; none is described as significant.

## Out-of-sample recalibration

The paper's ten random folds let later markets calibrate earlier ones. This
study never does.

- **Folds.** Each release date is a test fold. For a test fold at a horizon,
  the training set is every binary market at the same horizon whose event's
  release instant is strictly before the earliest horizon instant in the fold:
  only outcomes that were public when the test prices were quoted. A fold is
  evaluated only if its training set spans at least 20 release dates; the
  count of earlier folds is reported.
- **Models.** Identity (raw prices); logistic calibration (α, β, with β held
  at 0 if the fit gives a negative slope); beta calibration (Kull, Silva Filho
  and Flach 2017: logit q = c + a ln p̃ − b ln(1 − p̃) with a, b ≥ 0, a
  coefficient that comes out negative being set to 0 and the rest refitted).
  Both maps are non-decreasing in p by construction.
- **Pooling.** Primary: one map per horizon fitted on all series pooled.
  Secondary: per family, trained on that family only.
- **Metrics.** Binary log loss (p̃ clipped as above) and binary Brier score on
  the test markets; event-level bracket log score (0.001 floor, raised and
  renormalized as in #381) and multi-category Brier on the test events, using
  the recalibrated ladder g(p) for each strike. Because g is non-decreasing,
  the recalibrated ladder still falls with the strike and its brackets remain a
  distribution.
- **Comparison.** For each model, the per-fold mean improvement over identity,
  averaged over folds, with a 95% interval from 10,000 release-date cluster
  bootstrap draws.

## Sensitivity: a recalibrated Kalshi baseline in #381

#381's pre-registered results stay as they are. This section asks only whether
a recalibrated Kalshi baseline would change any of its conclusions.

- **Input.** #381's frozen `results.json`
  (`~/reviews/thesis-vs-kalshi-2026-10/results/`, study code as merged in
  3d3e81ec, Thesis log at a179451f, data as of 2026-10-20T02:04:11Z): every
  scored pair with its Kalshi repaired ladder, strikes, realized bracket and
  Thesis brackets.
- **Map.** For each pair, the pooled logistic map (and, separately, the beta
  map) of this study, fitted at the matching fixed horizon on markets whose
  release instant precedes the pair's horizon instant. #381's 7-day and 1-day
  horizons use the 7-day and 1-day maps. Its registration horizon uses the
  fixed horizon nearest in lead time on a log scale: 30 days for leads of 14.5
  days or more, 7 days for 2.65 to 14.5 days, 1 day below.
- **Scores.** Kalshi's bracket probabilities become the brackets of g applied
  to its repaired ladder; Thesis's are unchanged. #381's own summary code
  recomputes every pooled mean and interval, for every #381 price
  specification.
- **What counts as a change.** For each statement in #381's Summary (pooled
  log and Brier differences at each horizon, under the primary rule and the
  rules the Summary quotes), a change is a flip in the sign of the mean or a
  change in whether the release-clustered 95% interval includes zero. Every
  number is shown next to #381's.

## Invariants (tested)

- Bracket probabilities are non-negative and sum to 1, for raw, repaired,
  recalibrated and floored ladders.
- Each recalibration map is non-decreasing in p, for any training data.
- No candle ending after a horizon instant is used, for any candle history,
  at fixed horizons, life fractions and in the last-trade variant.
- The realized bracket follows each contract's `>` or `>=` rule: it agrees with
  every binary market's outcome under that rule.
- Differential: the official print applied to each contract's rule reproduces
  Kalshi's recorded result for every settled market with an official print,
  apart from the listed disagreements.

## Data provenance

Every HTTP response used is stored by SHA-256 with its URL and fetch time
(#381's `FetchCache`), so a rerun with `--offline` reproduces the results byte
for byte. Results are written under
`~/reviews/kalshi-econ-calibration-2026-10/`.

## What this does not measure

It measures the calibration and accuracy of Kalshi's prices on these twelve
series at stated horizons. It says nothing about Kalshi in other categories, or
about any trading strategy, and it does not test the paper's pooled result.

## Changes made after this plan was first committed

The plan as first committed is commit 64ab04df. Changes 1 to 4 were made while
reading the contracts and releases, before any Kalshi price was compared with
an outcome. A test run of the code on the two CPI series then computed scores;
changes 5 to 7 came after it, before the full run.

1. **Legacy rule periods.** Some 2021 and 2022 rules name the month without the
   year ("in June") or write "July, 2021". Such a rule is accepted only if it
   names the title's month, no other month and no year in another form. A rule
   that names a different month (one market of `CPI-22JUN` says July 2022)
   still makes its event unreadable, as planned.
2. **Legacy strike wordings.** The legacy reader also accepts "greater than"
   (2022-2023 core CPI rules, some with `strike_type` set) and "0.50
   percent%" (`CPI-21OCT-T0.5`). `floor_strike` must agree with the text to
   within 0.00001: Kalshi stored 4.099999 for rules that say 4.1 on U-3 markets
   from 2023 to 2025. Kalshi's results agree with the text's 4.1 on every such
   market (the settlement check).
3. **Release layouts.** BEA's release pages used five layouts over the period:
   a five-column table (2022-2024), a single statement in the text with no
   table (the December 2024 and January 2025 releases, which give one reading
   only), a "from February to March" table, a two-column table, and the
   combined October and November 2025 release, which the search reaches as
   `october-and-november-2025`. The ABS parser now reads the paragraph and table
   labelled seasonally adjusted: the April 2026 page puts the trend paragraph
   within the old reading window, and the February 2026 page puts the trend
   table first. Both fixes are in #381's shared parser; #381's results
   reproduce byte for byte afterwards.
4. **Weekly claims during the 2025 shutdown.** DOL's 2025-11-20 release says no
   claims releases were published from 2025-10-02 to 2025-11-13 and that the
   official seasonally adjusted data for those weeks were posted on its
   website. The posting as first published cannot be retrieved now, so
   `KXJOBLESSCLAIMS-25OCT02` (week ending 2025-09-27) has no official outcome
   and is listed; it enters the Kalshi-results sensitivity.
5. **Threads.** Independent analyses run on four threads; each seeds its own
   generator, so no number depends on the thread count.
6. **Interior prices (post hoc, secondary).** The CPI test run gave slopes
   above 1. Prices in this data move in one-cent steps, so a midpoint cannot go
   below half a cent or above 99.5 cents, and the slope is sensitive to
   markets at those edges. Before the full run, a secondary analysis was added
   that repeats the compression test and the reliability summary on prices from
   0.05 to 0.95 only. It is never primary.
7. **Market life ends at the release.** A market's life for the life
   fractions runs to its close or to the release, whichever is first, so no
   price after the release is read. The report lists every market that closed
   after its release (`lateCloses`): 77 markets in eight events (U-3 and
   payrolls for January 2026; housing starts and permits for March 2026;
   permits for April 2026; Australian unemployment for February, March and
   September 2026); each event's last market closed 52 minutes to 3.9
   hours after its release. Fixed horizons were already anchored at the
   earlier of the release and the last close, as planned.
