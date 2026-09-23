import { getPublishedForecasts } from "@/lib/forecast-publication";
import type { Metadata } from "next";
import Link from "next/link";
import { Header } from "@/components/Header";
import { formatValue } from "@/data/forecast-cells";
import {
  buildStrategyLabReport,
  type StrategyComparisonRow,
  type StrategySummaryRow,
} from "@/data/strategy-lab";
import {
  buildTimeSeriesPriorAdjustmentReport,
  type TimeSeriesPriorAdjustmentRow,
} from "@/data/time-series-priors";
import {
  buildForecastJudgeExport,
  type ForecastJudgeCalibrationBand,
  type ForecastJudgeCalibrationDisagreement,
} from "@/data/forecast-judges";
import {
  hasVerifiedClaimedChronology,
  loadPolicyEngineLedger,
  scoreResolvedForecasts,
  withResolvedOutcomes,
} from "@/data/thesis-log";

export const metadata: Metadata = {
  title: "Strategy Lab — Axiom Forecasts",
  description:
    "Replayable baseline and forward-only agent strategy comparisons for Brier.",
  robots: {
    index: false,
    follow: false,
    nocache: true,
    googleBot: {
      index: false,
      follow: false,
      noimageindex: true,
    },
  },
};

export default async function StrategyLabPage() {
  const ledger = await loadPolicyEngineLedger();
  const forecasts = withResolvedOutcomes(getPublishedForecasts(), ledger);
  const report = buildStrategyLabReport(forecasts, ledger);
  const priorReport = buildTimeSeriesPriorAdjustmentReport(forecasts);
  // Judge diagnostics read the published verified-chronology population
  // (claimed-time or better); they are process evals, never headline.
  const scores = scoreResolvedForecasts(forecasts, ledger).filter((score) =>
    hasVerifiedClaimedChronology(score.chronology),
  );
  const judgeReport = buildForecastJudgeExport({ forecasts, scores });
  const family = report.families[0];
  const persistence = report.summaries.find(
    (summary) => summary.strategyId === "baseline.persistence.last_print",
  );
  const agent = report.summaries.find(
    (summary) => summary.strategyId === "agent.brier.primary",
  );

  return (
    <div>
      <Header activePage="brier" />
      <main className="mx-auto max-w-[1200px] px-8 pb-32 pt-12 max-md:px-5">
        <section className="mb-10 max-w-[860px]">
          <Link
            href="/brier"
            className="mb-4 inline-block [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.13em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
          >
            Brier Lab
          </Link>
          <p className="mb-3 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.15em] text-[var(--color-accent)]">
            Strategy Lab · baseline discipline
          </p>
          <h1 className="mb-5 [font-family:var(--font-display)] text-[clamp(1.9rem,4vw,2.6rem)] font-light leading-[1.15] tracking-[-0.02em] text-[var(--theme-text)]">
            Forecast strategies have to beat simple replayable benchmarks
          </h1>
          <p className="text-[1.03rem] leading-[1.65] text-[var(--theme-text-muted)]">
            This page compares deterministic baselines with the actual Brier
            agent run on resolved target panels. The first slice is SNAP FY2025
            state payment error rates: every baseline uses only FY2023 and
            FY2024 values, while the agent row is the immutable published
            forecast. Everything here is a retrospective reconstruction —
            strategy rows are replayed over outcomes that already resolved,
            carry no chronology verification, and never enter headline
            calibration, rewards, or leaderboards.
          </p>
        </section>

        <section className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-4">
          <MetricCard label="strategies" value={report.counts.strategies} />
          <MetricCard label="targets" value={report.counts.targets} />
          <MetricCard label="resolved" value={report.counts.resolvedTargets} />
          <MetricCard label="score rows" value={report.counts.scoredRows} />
        </section>

        <section
          className="mb-8 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
            <div>
              <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
                LLM Judge Layer
              </h2>
              <p className="mt-2 max-w-[760px] text-[0.86rem] leading-[1.6] text-[var(--theme-text-muted)]">
                Judge records score forecast process quality from the public
                trace: base rates, source grounding, resolution clarity,
                uncertainty, mechanisms, counterarguments, and coherence. They
                are auxiliary diagnostics; reward still comes only from resolved
                CRPS.
              </p>
            </div>
            <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              reward-ineligible process eval
            </span>
          </div>
          <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
            <FactStrip
              label="trace judges"
              value={judgeReport.calibration.counts.judgedRuns.toLocaleString()}
            />
            <FactStrip
              label="scored judges"
              value={judgeReport.calibration.counts.scoredJudgedRuns.toLocaleString()}
            />
            <FactStrip
              label="judge ↔ -nCRPS"
              value={formatMaybe(
                judgeReport.calibration.judgeScoreVsNegativeNormalizedCrps,
              )}
            />
            <FactStrip
              label="post-resolution reviews"
              value={judgeReport.calibration.counts.postResolutionReviews.toLocaleString()}
            />
          </div>
          <div className="mb-6 overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left [font-family:var(--font-body)] text-[0.84rem]">
              <thead>
                <tr className="border-b border-[var(--theme-border)] [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                  <th className="py-3 pr-5 font-medium">band</th>
                  <th className="py-3 pr-5 font-medium">judged</th>
                  <th className="py-3 pr-5 font-medium">scored</th>
                  <th className="py-3 pr-5 font-medium">judge</th>
                  <th className="py-3 pr-5 font-medium">nCRPS</th>
                  <th className="py-3 font-medium">80% cover</th>
                </tr>
              </thead>
              <tbody>
                {judgeReport.calibration.scoreBands.map((band) => (
                  <JudgeBandRow key={band.label} band={band} />
                ))}
              </tbody>
            </table>
          </div>
          {judgeReport.calibration.disagreements.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] border-collapse text-left [font-family:var(--font-body)] text-[0.84rem]">
                <thead>
                  <tr className="border-b border-[var(--theme-border)] [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                    <th className="py-3 pr-5 font-medium">disagreement</th>
                    <th className="py-3 pr-5 font-medium">target</th>
                    <th className="py-3 pr-5 font-medium">run</th>
                    <th className="py-3 pr-5 font-medium">judge</th>
                    <th className="py-3 pr-5 font-medium">nCRPS</th>
                    <th className="py-3 font-medium">80% cover</th>
                  </tr>
                </thead>
                <tbody>
                  {judgeReport.calibration.disagreements.map((row) => (
                    <JudgeDisagreementRow key={row.runId} row={row} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>

        <section
          className="mb-8 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
            <div>
              <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
                Agent Adjustments From Time-Series Prior
              </h2>
              <p className="mt-2 max-w-[760px] text-[0.86rem] leading-[1.6] text-[var(--theme-text-muted)]">
                Each eligible agent run now gets a last-print persistence prior.
                The adjustment is the primary Brier point estimate minus that
                prior, scaled where useful by the prior&apos;s 80% interval.
              </p>
            </div>
            <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              {priorReport.counts.forecastsWithPrior.toLocaleString()} prior
              comparisons
            </span>
          </div>
          <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
            <FactStrip
              label="direction"
              value={`${priorReport.counts.adjustedUp.toLocaleString()} up / ${priorReport.counts.adjustedDown.toLocaleString()} down`}
            />
            <FactStrip
              label="flat"
              value={priorReport.counts.flat.toLocaleString()}
            />
            <FactStrip
              label="median |adj| / interval"
              value={formatRatio(
                priorReport.summary.medianAbsoluteShareOfPriorInterval,
              )}
            />
            <FactStrip
              label="mean |adj| / interval"
              value={formatRatio(
                priorReport.summary.meanAbsoluteShareOfPriorInterval,
              )}
            />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] border-collapse text-left [font-family:var(--font-body)] text-[0.84rem]">
              <thead>
                <tr className="border-b border-[var(--theme-border)] [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                  <th className="py-3 pr-5 font-medium">target</th>
                  <th className="py-3 pr-5 font-medium">latest</th>
                  <th className="py-3 pr-5 font-medium">prior</th>
                  <th className="py-3 pr-5 font-medium">agent</th>
                  <th className="py-3 pr-5 font-medium">adjustment</th>
                  <th className="py-3 font-medium">interval share</th>
                </tr>
              </thead>
              <tbody>
                {priorReport.largestPriorIntervalShareAdjustments.map((row) => (
                  <TimeSeriesPriorRow key={row.forecastSlug} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {family ? (
          <>
            <section
              className="mb-8 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
              style={{ borderColor: "var(--theme-border)" }}
            >
              <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
                <div>
                  <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
                    {family.label}
                  </h2>
                  <p className="mt-2 max-w-[760px] text-[0.86rem] leading-[1.6] text-[var(--theme-text-muted)]">
                    {family.description}
                  </p>
                </div>
                <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                  {family.resolvedTargetCount.toLocaleString()} resolved targets
                </span>
              </div>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-5">
                <FactStrip
                  label="FY2023 median"
                  value={formatPoints(family.panelStats.fy2023Median)}
                />
                <FactStrip
                  label="FY2024 median"
                  value={formatPoints(family.panelStats.fy2024Median)}
                />
                <FactStrip
                  label="median change"
                  value={formatDeltaPoints(family.panelStats.deltaMedian)}
                />
                <FactStrip
                  label="p10 change"
                  value={formatDeltaPoints(family.panelStats.deltaP10)}
                />
                <FactStrip
                  label="p90 change"
                  value={formatDeltaPoints(family.panelStats.deltaP90)}
                />
              </div>
            </section>

            <section
              className="mb-8 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
              style={{ borderColor: "var(--theme-border)" }}
            >
              <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
                <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
                  Strategy Scoreboard
                </h2>
                <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                  lower nCRPS and MAE are better
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[980px] border-collapse text-left [font-family:var(--font-body)] text-[0.84rem]">
                  <thead>
                    <tr className="border-b border-[var(--theme-border)] [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                      <th className="py-3 pr-5 font-medium">strategy</th>
                      <th className="py-3 pr-5 font-medium">mode</th>
                      <th className="py-3 pr-5 font-medium">rows</th>
                      <th className="py-3 pr-5 font-medium">nCRPS</th>
                      <th className="py-3 pr-5 font-medium">MAE</th>
                      <th className="py-3 pr-5 font-medium">vs persistence</th>
                      <th className="py-3 pr-5 font-medium">bias</th>
                      <th className="py-3 font-medium">80% cover</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.summaries.map((summary) => (
                      <StrategyRow key={summary.strategyId} row={summary} />
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-2">
              <Callout
                label="persistence"
                value={formatNullablePoints(persistence?.meanAbsoluteError)}
                caption="mean absolute error"
              />
              <Callout
                label="Brier primary"
                value={formatNullablePoints(agent?.meanAbsoluteError)}
                caption={`MAE delta ${formatDeltaMaybe(
                  agent?.meanAbsoluteErrorVsPersistence,
                )}`}
              />
            </section>

            <section
              className="rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
              style={{ borderColor: "var(--theme-border)" }}
            >
              <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
                <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
                  Largest Agent nCRPS Misses Against Persistence
                </h2>
                <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                  top {family.largestAgentNcrpsMissesVsPersistence.length}
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[940px] border-collapse text-left [font-family:var(--font-body)] text-[0.84rem]">
                  <thead>
                    <tr className="border-b border-[var(--theme-border)] [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                      <th className="py-3 pr-5 font-medium">target</th>
                      <th className="py-3 pr-5 font-medium">actual</th>
                      <th className="py-3 pr-5 font-medium">persistence</th>
                      <th className="py-3 pr-5 font-medium">agent</th>
                      <th className="py-3 pr-5 font-medium">nCRPS delta</th>
                      <th className="py-3 font-medium">MAE delta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {family.largestAgentNcrpsMissesVsPersistence.map((row) => (
                      <ComparisonRow
                        key={`${row.forecastSlug}:${row.entityCode}`}
                        row={row}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        ) : null}
      </main>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: number }) {
  return (
    <div
      className="rounded-xl border bg-[var(--theme-bg-elevated)] p-4"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
        {label}
      </div>
      <div className="mt-2 [font-family:var(--font-display)] text-[1.55rem] font-semibold tracking-[-0.02em] text-[var(--theme-text)]">
        {value.toLocaleString()}
      </div>
    </div>
  );
}

function FactStrip({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-l border-[var(--theme-border)] pl-4">
      <div className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
        {label}
      </div>
      <div className="mt-2 text-[0.96rem] font-medium text-[var(--theme-text)]">
        {value}
      </div>
    </div>
  );
}

function StrategyRow({ row }: { row: StrategySummaryRow }) {
  return (
    <tr className="border-b border-[var(--theme-border)] last:border-b-0">
      <td className="max-w-[300px] py-4 pr-5 align-top">
        <div className="text-[var(--theme-text)]">{row.label}</div>
        <div className="mt-1 text-[0.75rem] leading-[1.45] text-[var(--theme-text-muted)]">
          {row.description}
        </div>
      </td>
      <td className="py-4 pr-5 align-top">
        <div className="[font-family:var(--font-mono)] text-[0.66rem] uppercase tracking-[0.08em] text-[var(--color-accent)]">
          {row.evidenceMode.replace("_", " ")}
        </div>
        <div className="mt-1 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
          {row.kind.replace("_", " ")}
        </div>
        <div className="mt-1 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
          {row.distributionProvenance.replace("_", " ")}
        </div>
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {row.scoredRows.toLocaleString()}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatMaybe(row.meanNormalizedCrps)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatNullablePoints(row.meanAbsoluteError)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatDeltaMaybe(row.meanAbsoluteErrorVsPersistence)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatDeltaMaybe(row.meanSignedError)}
      </td>
      <td className="py-4 align-top text-[var(--theme-text)]">
        {formatPercent(row.interval80Coverage)}
      </td>
    </tr>
  );
}

function ComparisonRow({ row }: { row: StrategyComparisonRow }) {
  return (
    <tr className="border-b border-[var(--theme-border)] last:border-b-0">
      <td className="max-w-[280px] py-4 pr-5 align-top">
        <Link
          href={`/forecasts/${row.forecastSlug}`}
          className="text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
        >
          {row.entityCode}
        </Link>
        <div className="mt-1 text-[0.75rem] leading-[1.45] text-[var(--theme-text-muted)]">
          {row.title}
        </div>
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatPoints(row.observedValue)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatPoints(row.persistencePointEstimate)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatPoints(row.agentPointEstimate)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatMaybe(row.agentMinusPersistenceNormalizedCrps)}
      </td>
      <td className="py-4 align-top text-[var(--theme-text)]">
        {formatDeltaPoints(row.agentMinusPersistenceAbsoluteError)}
      </td>
    </tr>
  );
}

function TimeSeriesPriorRow({ row }: { row: TimeSeriesPriorAdjustmentRow }) {
  return (
    <tr className="border-b border-[var(--theme-border)] last:border-b-0">
      <td className="max-w-[300px] py-4 pr-5 align-top">
        <Link
          href={`/forecasts/${row.forecastSlug}`}
          className="text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
        >
          {row.dataPointId ?? row.forecastSlug}
        </Link>
        <div className="mt-1 text-[0.75rem] leading-[1.45] text-[var(--theme-text-muted)]">
          {row.title}
        </div>
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        <div>{formatValue(row.latestHistoricalValue, row.unit)}</div>
        <div className="mt-1 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
          {row.latestHistoricalLabel}
        </div>
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatValue(row.priorPointEstimate, row.unit)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatValue(row.agentPointEstimate, row.unit)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatSignedValue(row.adjustment, row.unit)}
      </td>
      <td className="py-4 align-top text-[var(--theme-text)]">
        {formatSignedRatio(row.adjustmentShareOfPriorInterval)}
      </td>
    </tr>
  );
}

function JudgeBandRow({ band }: { band: ForecastJudgeCalibrationBand }) {
  return (
    <tr className="border-b border-[var(--theme-border)] last:border-b-0">
      <td className="py-4 pr-5 align-top">
        <div className="text-[var(--theme-text)]">{band.label}</div>
        <div className="mt-1 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
          {band.minScore.toFixed(1)}-{band.maxScore.toFixed(1)}
        </div>
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {band.judgedRuns.toLocaleString()}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {band.scoredRuns.toLocaleString()}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatMaybe(band.meanJudgeScore)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatMaybe(band.meanNormalizedCrps)}
      </td>
      <td className="py-4 align-top text-[var(--theme-text)]">
        {formatPercent(band.interval80Coverage)}
      </td>
    </tr>
  );
}

function JudgeDisagreementRow({
  row,
}: {
  row: ForecastJudgeCalibrationDisagreement;
}) {
  return (
    <tr className="border-b border-[var(--theme-border)] last:border-b-0">
      <td className="py-4 pr-5 align-top">
        <div className="[font-family:var(--font-mono)] text-[0.64rem] uppercase tracking-[0.08em] text-[var(--color-accent)]">
          {row.disagreement.replace(/_/g, " ")}
        </div>
      </td>
      <td className="max-w-[260px] py-4 pr-5 align-top">
        <Link
          href={`/forecasts/${row.predictionId}`}
          className="text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
        >
          {row.predictionId}
        </Link>
      </td>
      <td className="max-w-[220px] py-4 pr-5 align-top text-[var(--theme-text-muted)]">
        {row.runLabel}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatMaybe(row.judgeScore)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatMaybe(row.normalizedCrps)}
      </td>
      <td className="py-4 align-top text-[var(--theme-text)]">
        {row.interval80Covered ? "inside" : "outside"}
      </td>
    </tr>
  );
}

function Callout({
  label,
  value,
  caption,
}: {
  label: string;
  value: string;
  caption: string;
}) {
  return (
    <div
      className="rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
        {label}
      </div>
      <div className="mt-3 [font-family:var(--font-display)] text-[2rem] font-semibold tracking-[-0.02em] text-[var(--theme-text)]">
        {value}
      </div>
      <div className="mt-2 text-[0.86rem] text-[var(--theme-text-muted)]">
        {caption}
      </div>
    </div>
  );
}

function formatMaybe(value: number | null) {
  if (value === null) return "pending";
  return value.toFixed(3);
}

function formatPercent(value: number | null) {
  if (value === null) return "pending";
  return `${Math.round(value * 100)}%`;
}

function formatNullablePoints(value: number | null | undefined) {
  if (value === null || value === undefined) return "pending";
  return formatPoints(value);
}

function formatDeltaMaybe(value: number | null | undefined) {
  if (value === null || value === undefined) return "pending";
  return formatDeltaPoints(value);
}

function formatRatio(value: number | null | undefined) {
  if (value === null || value === undefined) return "pending";
  return `${value.toFixed(2)}x`;
}

function formatSignedRatio(value: number | null | undefined) {
  if (value === null || value === undefined) return "pending";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}x`;
}

function formatSignedValue(
  value: number,
  unit: TimeSeriesPriorAdjustmentRow["unit"],
) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatValue(value, unit)}`;
}

function formatPoints(value: number) {
  return `${value.toFixed(2)}pp`;
}

function formatDeltaPoints(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}pp`;
}
