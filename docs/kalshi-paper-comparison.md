# Paper comparison: Thesis forecasts vs Kalshi prices

This is a read-only scoring study. It compares published Thesis forecasts with
Kalshi market prices for the official statistics both cover (US national
statistics as first planned, plus one Australian series added after review),
and scores
both against the official first print. It places no orders, holds no
positions, simulates no trading strategy, and needs no Kalshi account: every
Kalshi number comes from the public, unauthenticated market-data API.

What it measures is forecast skill on monthly and weekly national statistics
at stated horizons. It says nothing about any other domain (for example state
or municipal finance), and small samples are expected.

`scripts/kalshi_paper_comparison.py` implements everything below. Results are
written outside the repository (`--out`); this document is the analysis plan.

## Status of this plan

The plan was written on 2026-10-19, after the outcomes in scope were public and
after inspecting the order book of one event (KXCPI-26AUG) to choose the price
rule, but before computing any Thesis or Kalshi score. Any later change to the
primary specification must be listed in the results as a deviation.

## Forecasts in scope

- **Source.** Every `prediction_recorded` entry in the published Thesis log
  (the attested `records/<day>/bodies-*/log` projection on `main`) whose
  `recordedAt` is on or after 2026-07-01T00:00:00Z and whose `dataPointId`
  maps to a Kalshi series in the table below.
- **Published distribution.** The run's 201-point `numeric_cdf_v1` from the
  published target-architecture table `forecastDistributions`
  (`/targets/forecastDistributions/<chunk>.json` on app.thesisinstitute.org).
  The CDF is read with linear interpolation between points, 0 below the first
  point and 1 above the last. A differential check rebuilds each
  `interval_seeded` CDF from the run's point and 80% interval with the
  `interval_anchor_v1` transform (`site/src/data/prediction-distribution.ts`)
  and must match the published points.
- **Primary forecaster.** The `thesis.analyst` run labelled `Headline` for
  each target (if a target has more than one, the earliest registered). Other
  agent variants (for example threshold-ladder runs) and
  the deterministic `brier.time_series_prior` persistence baseline are scored
  as secondary forecasters.
- **Withdrawn cells.** Catalog cells that the publication gate excludes (the
  site shows "No forecast available") are listed with their claimed run time
  and are not scored.

## Registration time

A run's registration time is the earliest RFC 3161 witness time of its custody
root in `records/witnessed-timeline.json` (`custodyRoots`). If the custody root
is absent there, the run directory's witness time (`runs`) is used; if neither
exists, the claimed `recordedAt` is used and flagged. Each run's coverage class
is reported.

## Kalshi series in scope

| Thesis target family | Kalshi series | Contract strike | Reported value and grid |
| --- | --- | --- | --- |
| `bls.cpi.u.headline_mom.<month>` | KXCPI | above X (`greater`) | CPI-U SA % change, 0.1 |
| `bls.cpi.u.core_mom.<month>` | KXCPICORE | above X | core CPI-U SA % change, 0.1 |
| `bls.cps.unemployment_rate.<month>` | KXU3 | above X | U-3 rate %, 0.1 |
| `bls.ces.*payroll*change*` | KXPAYROLLS | above X persons | total nonfarm change, 1,000 |
| `us.dol.initial_claims.sa.week_<date>` | KXJOBLESSCLAIMS | at least X (`greater_or_equal`) | advance SA initial claims, 1,000 |
| `dol.eta.continued_claims.sa.week_<date>` | KXCONTCLAIMS | at least X million | advance SA insured unemployment, 0.001 million |
| `bls.jolts.job_openings.<month>` | KXJOLTSOPEN | above X million | SA job openings, 0.001 million |
| `us.bea.core_pce.mom_sa.<month>`, `bea.pce.core_mom.<month>` | KXPCECORE | above X | core PCE price index % change, 0.1 |
| `census.housing_starts.saar.<month>` | KXHOUSINGSTART | above X million | housing starts SAAR, 0.001 million |
| `census.housing.permits_saar.<month>` | KXBUILDPERMS | above X million | building permits SAAR, 0.001 million |
| `census.new_residential_sales.new_single_family_houses_sold_saar.<month>` | KXNHSALES | above X homes | new houses sold SAAR, 1,000 |
| `abs.labour.unemployment_rate.<month>` | KXUE (Australia events) | above X | ABS unemployment rate %, 0.1 |

The last four rows were added after independent review (see the final section).

Secondary: KXECONSTATCPI, KXECONSTATCPICORE and KXECONSTATU3 list "exactly X"
markets for the same statistics. They are scored separately, with an added
"any other value" bracket, because their brackets do not cover every value.

Thesis targets with no Kalshi market for the same statistic and period (for
example JOLTS quits and hires, CPI components, or a GDP period Kalshi does not
list) are listed in the inventory and not scored. Each such target belongs to a
recorded catalog screen group (change 7 below), so every "no Kalshi series"
statement rests on a search the run repeats.

Kalshi events are matched by series and reference period, read from the
event's markets' rule text, and verified against the event title. Each
market's strike and its unit are read from its own rule text and must equal
its `floor_strike` (Kalshi moved continuing-claims strikes from "1.84 million"
to "1750K" between events).

## Horizons

- **At registration:** the Thesis registration time.
- **Seven days before release:** the official release instant minus 168 hours.
- **One day before release:** the official release instant minus 24 hours.

The release instant is the time the agency's own release document states:
8:30 ET for CPI, the Employment Situation, weekly claims, Personal Income and
Outlays and Census/HUD New Residential Construction; 10:00 ET for JOLTS and
Census/HUD New Residential Sales; 11:30 Canberra time (AEST or AEDT, as the
ABS release page states) for ABS Labour Force. Kalshi's market close must
precede it.

A Kalshi price is compared with a Thesis forecast only when the horizon is at
or after the Thesis registration time, so the market never has less
information than Thesis had. Pairs that fail this are counted and dropped.
Results are never pooled across horizons.

## Kalshi price at a time

- The market must have opened at or before the horizon.
- Use the hourly candlestick (`period_interval=60`) with the latest
  `end_period_ts` at or before the horizon, from the live endpoint or the
  historical tier for markets settled before Kalshi's archive cutoff.
- **Primary price:** the midpoint of the closing yes bid and yes ask, where an
  empty bid is 0 and an empty ask is 1.
- **Sensitivity price:** the last traded price at or before the horizon, or the
  midpoint if the market never traded.
- **Ladder repair:** within an event, P(yes) must not increase with the
  strike. Violations are repaired with unweighted pooled-adjacent-violators
  isotonic regression and counted.
- Volume is recorded per market: lifetime volume, volume up to the horizon,
  open interest at the horizon, and the bid-ask spread at the horizon.

## Brackets and probabilities

For an event at a horizon, the admitted markets' strikes s1 < ... < sn define
n + 1 brackets of the reported value Y, following each contract's wording:
`greater` gives (-inf, s1], (s1, s2], ..., (sn, inf); `greater_or_equal` gives
(-inf, s1), [s1, s2), ..., [sn, inf). Kalshi's bracket probabilities are the
differences of the repaired ladder prices.

Thesis's bracket probabilities come from its published CDF F. The agency
publishes Y as a latent value L rounded to the reporting grid g, and F is read
as the distribution of L (a symmetric convention for a continuous CDF of a value
published on a grid). So
P(Y > s) = 1 - F(s + g/2) and P(Y >= s) = 1 - F(s - g/2). Sensitivity: the
literal reading P(Y > s) = P(Y >= s) = 1 - F(s). Thesis units are converted to
the contract's strike units first (thousands to persons for payrolls and
initial claims).

## Outcomes

The outcome is the official first print, read from the agency's own release:
the BLS news release archive (CPI Table A, Employment Situation summary tables
A and B, JOLTS Table A), the DOL Employment and Training Administration weekly
claims press release, and the BEA Personal Income and Outlays release.
Each market's realized outcome under its rule must equal Kalshi's recorded
`result`; any disagreement is reported, and the official release governs.
Thesis's own resolution status is reported alongside, including targets its
resolver has not yet resolved.

## Scores

Both forecasters are scored on the same brackets.

- **Log score:** ln of the probability given to the realized bracket.
  Bracket probabilities are raised to at least 0.001, with the added mass
  taken proportionally from the other brackets, for both forecasters.
  Sensitivity floor: 0.01.
- **Brier score:** the multi-category Brier score, sum over brackets of
  (probability - indicator)^2, from 0 (best) to 2.
- **Ladder Brier (secondary):** the mean over the event's binary markets of
  (P(yes) - outcome)^2.

Paired differences are oriented so that a positive value favors Thesis:
delta log = log(Thesis) - log(Kalshi); delta Brier = Brier(Kalshi) -
Brier(Thesis).

## Inference

- The unit is the event (one statistic for one reference period), with one
  primary Thesis forecast per event.
- Per series: n, mean paired difference, a two-sided exact sign-flip
  randomization p-value (all 2^n sign patterns for n <= 16, otherwise 100,000
  draws with a fixed seed), and a 95% percentile bootstrap interval over
  events (10,000 resamples, fixed seed).
- A series with fewer than five resolved pairs gets its numbers reported and
  the plain statement that there are too few pairs to conclude anything.
- Pooled: (a) all events equally weighted; (b) series-balanced (the mean of
  series means). Events released together (headline and core CPI; U-3 and
  payrolls; initial and continued claims) are correlated, so the pooled
  interval also resamples release dates rather than events.
- There are three horizons and two scores. No result is described as
  significant; intervals are reported as they are.

## Changes made after this plan was first committed

The plan as first committed is commit 98940ca4. Later changes, in order:

1. **Strike units** are read from each market's own rule text, after the first
   full run showed Kalshi moving continuing-claims strikes from "1.84 million"
   to "1750K"; the rule's direction word must also match the market's strike
   type.
2. **Liquid markets only** (spread of 20 cents or less) was added as a
   sensitivity after inspecting bid-ask spreads. It was adopted after full runs
   whose saved output already contained scores; the author had not examined
   those scores, which the record cannot show, so treat it as post hoc. It is
   never the primary rule.
3. **Floor wording.** "Floored at 0.001 and renormalized" is implemented as:
   raise each bracket to at least 0.001, taking the added mass proportionally
   from the others.
4. **Tiebreak.** If a target has more than one headline run, the earliest
   registered is primary. No target has two, so it never applies.
5. **After independent review (2026-10-20):**
   - Kalshi's full series catalog is fetched and stored, and every statistic
     Thesis forecasts was screened against it. This found Kalshi events for
     Thesis's periods in four more series: KXHOUSINGSTART, KXBUILDPERMS and
     KXNHSALES (Census/HUD, scored from the New Residential Construction and
     Sales release PDFs) and KXUE's Australian events (scored from the ABS
     Labour Force release pages). Every other in-scope run is listed with the
     Kalshi evidence for its statistic and period.
   - Candles are read over each market's whole life. The first version
     fetched only 14 days before the earliest horizon, which silently dropped
     two open strikes in one event whose books had not changed in that window.
     A market open but never quoted before a horizon is listed as an exclusion.
   - Pooled intervals are reported both by event and by release date (the
     latter is the one this plan names). Per-series results with fewer than
     five events list the individual differences instead of an interval. The
     series-balanced interval resamples series as well as events. p-values
     above 16 events say they are Monte Carlo. Results on the same events as
     the registration comparison, and on headline-eligible custody roots only,
     are reported.
   - The justification for the rounding reading was corrected: Thesis point
     estimates sit between grid values only for some series, so the reading is
     stated as a convention.

6. **After the second review (2026-10-20):** the report's Summary quotes
   release-clustered intervals, says which series were added after the first
   review and gives the eight original series as a subset, and discloses Kalshi
   floor hits at every horizon it quotes. Other Kalshi series on the matched
   statistics (older tickers and second venues such as KXUSNFP and KXJOBLESS)
   are listed with whether they have an event for a matched period. Release
   times were added for the Census and ABS sources, and the scope statement
   above now says it includes one Australian series.

7. **After a further independent review (2026-10-20):** the catalog screen
   behind every "no Kalshi series" statement is now part of the run rather
   than a one-off search. Every unmatched Thesis target belongs to one of 39
   screen groups, each with the keywords a Kalshi series on that statistic
   would use. The run searches the ticker and title of every series in the
   stored catalog, in every category, and the event titles of series whose
   events cover several countries under a title that names none (KXUE,
   KXGDPNOM and KXGOVBAL, found by reading the events of every Economics and
   World series whose title names no country; change 8 widened this to every
   event of every Economics and World series). Each hit must be a scored
   series, an older ticker or second venue, a related series whose events are
   checked for each run's period, or a different statistic with a reviewed
   reason; a hit without one, or an unmatched target outside every group,
   stops the run. The hits and verdicts are written to `catalog_screen.csv`.
   The screen added KXJOLTS as an older venue for job openings, and KXUSPPIYOY,
   KXCPISHELTER, CPISHELTER, KXJPMOMINF, REALWAGES, KXTDEFFICITBY,
   KXDATACENTCON and KXMANUCON as related series. The reference-period reader
   now requires 20xx years, so StatCan's table number 36-10-0434-01 is no
   longer read as a period.

8. **After the review of change 7 (2026-10-20):** that review found series
   the keywords missed. Among them were a monthly "Credit card debt" series
   (CRED, KXCRED) behind the consumer-credit statement, a 12-month real
   earnings series (KXWAGESBEAT), federal debt series, state permit and house
   price series, and others. The keywords were widened across the groups. The
   screen now reads the events of every Economics and World series (5,688
   events in 999 series), not only those of series whose events name several
   countries, and it searches event tickers as well as titles. A series related
   to another family is labelled so, rather than as checked for this group. A
   related series is compared with a quarterly or annual run in that run's own
   period. The new related series are KXWAGESBEAT, KXAHEG, KXHEALTHCOST,
   CRED, KXCRED, KXTRUFPDEBT, KXDEBTLEVEL, the KXDEBTGROWTH series,
   KXDEBTSHRINK and KXNDEBTSHRINK. Every other new hit carries a reviewed
   reason. No score changed.

9. **After the review of change 8 (2026-10-20):** that review found that an
   event whose period the reader could not parse was reported as absent. Its
   examples were a month range (KXAHEG, August 2026 through July 2027), "any
   2026 quarter" (KXNFPROD) and day-dated events (KXTRUFPDEBT). The evidence
   for unmatched runs now reads day dates, month ranges, "any year quarter",
   and a lone month with a lone year. Scored matching keeps the strict reader.
   Any event still naming no period is listed in the evidence. A run is not
   called absent while such an event could cover its period, and on a
   same-statistic series such an event stops the run. Screen hits are
   counted one row per group, series and verdict, with distinct series
   counted. Two sweeps for missed series found none on the same statistic.
   Their adjacent series (personal spending, ADP, CPI-U index level,
   credit-card delinquency, housing inventory, semiconductor production,
   foreign trade flows, Canada's Ivey PMI) and KXUSDEBT now carry recorded
   verdicts. No score changed.

## Data provenance

Every HTTP response used is stored by SHA-256 with its URL and fetch time, so a
rerun with `--offline` reproduces the results byte for byte from the stored
responses.

## Running it

```bash
uv run python scripts/kalshi_paper_comparison.py \
  --out ~/reviews/thesis-vs-kalshi-2026-10/results \
  --cache ~/reviews/thesis-vs-kalshi-2026-10/fetch \
  --ref a179451fbddb3babaa26d1405f6dbff3d76bd559 \
  --as-of 2026-10-20T02:04:11Z
```

Add `--offline` to rerun from the stored responses only, and `--ref <commit>` to
pin the Thesis commit whose published log is scored (the default, origin/main,
moves as records land; the report's Reproduce section gives both). Reading the DOL
releases needs `pdftotext` (poppler). The run writes `REPORT.md`,
`REPORT.html`, the CSV tables and `summary.json` to `--out`; results stay
outside the repository.

Tests: `uv run --extra dev pytest tests/test_kalshi_paper_comparison.py`
(real excerpted fixtures, property tests for the scoring invariants, and
differential checks of the published CDFs and Kalshi's recorded results).
