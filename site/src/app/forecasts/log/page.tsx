import { getPublishedForecasts } from "@/lib/forecast-publication";
import type { Metadata } from "next";
import Link from "next/link";
import { Header } from "@/components/Header";
import {
  COUNTRY_LABEL,
  formatValue,
  getForecastCountry,
  type ForecastCell,
} from "@/data/forecast-cells";
import {
  buildPredictionSpecs,
  buildRecordedPredictionRunRecords,
  type PredictionRunRecord,
  type PredictionSpec,
} from "@/data/prediction-specs";
import { isNormalizedScoreAggregateEligible } from "@/data/brier-lab";
import {
  buildThesisLog,
  buildResolutionQueue,
  hasVerifiedClaimedChronology,
  isPredictionRecordedLogEntry,
  isPredictionResolvedLogEntry,
  loadPolicyEngineLedger,
  scoreResolvedForecasts,
  withResolvedOutcomes,
  type PredictionRecordedLogEntry,
  type PredictionResolvedLogEntry,
  type PredictionResolutionQueueEntry,
  type ResolvedForecastScore,
} from "@/data/thesis-log";

export const metadata: Metadata = {
  title: "Forecast log — Axiom Forecasts",
  description: "Prediction records, distributions, traces, and scoring rows.",
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

interface ScoreboardSummary {
  scored: number;
  meanNormalizedCrps: number | null;
  meanCrps: number | null;
  meanAbsoluteError: number | null;
  meanNormalizedAbsoluteError: number | null;
  intervalCoverage: number | null;
}

interface ScoreboardGroup extends ScoreboardSummary {
  label: string;
  recorded: number;
  nextResolutionDate?: string;
}

interface Scoreboard {
  overall: ScoreboardSummary;
  byAgent: ScoreboardGroup[];
  byModel: ScoreboardGroup[];
  byRunType: ScoreboardGroup[];
  bestScores: ResolvedForecastScore[];
  worstScores: ResolvedForecastScore[];
}

export default async function ThesisLogPage() {
  const ledger = await loadPolicyEngineLedger();
  const forecasts = withResolvedOutcomes(getPublishedForecasts(), ledger);
  const specs = buildPredictionSpecs(forecasts);
  const runs = buildRecordedPredictionRunRecords(forecasts, specs);
  const logEntries = buildThesisLog(forecasts, ledger);
  const recordedPredictions = logEntries.filter(
    (entry): entry is PredictionRecordedLogEntry =>
      isPredictionRecordedLogEntry(entry),
  );
  const resolutions = logEntries.filter(
    (entry): entry is PredictionResolvedLogEntry =>
      isPredictionResolvedLogEntry(entry),
  );
  // The log is the transparency surface: its scoreboard shows every
  // published verified-chronology score (witness-verified and
  // claimed-time-verified). The headline track on /calibration and the
  // machine-readable counts.scored admit only the witness-verified tier.
  const scores = scoreResolvedForecasts(forecasts, ledger).filter((score) =>
    hasVerifiedClaimedChronology(score.chronology),
  );
  const resolutionQueue = buildResolutionQueue(forecasts, ledger);
  const visibleResolutionQueue = resolutionQueue.slice(0, 12);
  const scoreboard = buildScoreboard(recordedPredictions, scores, forecasts);

  const intervalCoverage =
    scoreboard.overall.intervalCoverage === null
      ? null
      : scoreboard.overall.intervalCoverage;

  return (
    <div>
      <Header activePage="log" />
      <main className="mx-auto max-w-[1200px] px-8 pb-32 pt-12 max-md:px-5">
        <section className="mb-10 max-w-[780px]">
          <Link
            href="/"
            className="mb-5 inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
          >
            ← all forecasts
          </Link>
          <p className="mb-3 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.15em] text-[var(--color-accent)]">
            Forecast log · prediction records
          </p>
          <h1 className="mb-5 [font-family:var(--font-display)] text-[clamp(1.9rem,4vw,2.6rem)] font-light leading-[1.15] tracking-[-0.02em] text-[var(--theme-text)]">
            Forecast log
          </h1>
          <p className="text-[1.02rem] leading-[1.65] text-[var(--theme-text-muted)]">
            Forecast log records predictions, distributions, trace metadata,
            resolution events, and scores. Resolved predictions reference facts
            in the PolicyEngine Ledger. The machine-readable v3 surface is a
            compact manifest whose hash-verified chunks preserve every full
            entry, spec, run, and score.
          </p>
          <div className="mt-5 flex flex-wrap gap-4">
            <a
              href="/log.json"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--color-accent)] no-underline hover:no-underline"
            >
              Machine-readable log JSON →
            </a>
            <a
              href="/targets.json"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            >
              Target architecture manifest →
            </a>
            <Link
              href="/forecasts/targets"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            >
              Target architecture →
            </Link>
            <a
              href="/ledger"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            >
              View facts ledger →
            </a>
          </div>
        </section>

        <section className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-3 lg:grid-cols-6">
          <MetricCard label="predictions" value={recordedPredictions.length} />
          <MetricCard label="specs" value={specs.length} />
          <MetricCard label="runs" value={runs.length} />
          <MetricCard label="resolved" value={resolutions.length} />
          <MetricCard label="pending" value={resolutionQueue.length} />
          <MetricCard
            label="scored / coverage"
            value={
              intervalCoverage === null
                ? "n/a"
                : `${scores.length} · ${Math.round(intervalCoverage * 100)}%`
            }
          />
        </section>

        <ScoreboardPanel scoreboard={scoreboard} forecasts={forecasts} />

        <ProductionContractPanel specs={specs} runs={runs} />

        <section
          className="mb-8 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
              Resolution queue
            </h2>
            <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              {resolutionQueue.length} pending · next 12 shown
            </span>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {visibleResolutionQueue.map((entry) => (
              <ResolutionQueueRow entry={entry} key={entry.forecastSlug} />
            ))}
          </div>
        </section>

        <section
          className="rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
              Recorded predictions
            </h2>
            <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              {recordedPredictions.length} rows · 201-point CDFs
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1160px] border-collapse text-left [font-family:var(--font-body)] text-[0.84rem]">
              <thead>
                <tr className="border-b border-[var(--theme-border)] [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                  <th className="py-3 pr-5 font-medium">prediction</th>
                  <th className="py-3 pr-5 font-medium">geo</th>
                  <th className="py-3 pr-5 font-medium">recorded</th>
                  <th className="py-3 pr-5 font-medium">agent / model</th>
                  <th className="py-3 pr-5 font-medium">activity</th>
                  <th className="py-3 pr-5 font-medium">packs</th>
                  <th className="py-3 pr-5 font-medium">estimate</th>
                  <th className="py-3 pr-5 font-medium">80% interval</th>
                  <th className="py-3 font-medium">cdf</th>
                </tr>
              </thead>
              <tbody>
                {recordedPredictions.map((entry) => (
                  <RecordedPredictionRow entry={entry} key={entry.runId} />
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section
          className="mt-8 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
              Scored predictions
            </h2>
            <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              {scores.length} rows · facts from Ledger
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1040px] border-collapse text-left [font-family:var(--font-body)] text-[0.84rem]">
              <thead>
                <tr className="border-b border-[var(--theme-border)] [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                  <th className="py-3 pr-5 font-medium">prediction</th>
                  <th className="py-3 pr-5 font-medium">geo</th>
                  <th className="py-3 pr-5 font-medium">run type</th>
                  <th className="py-3 pr-5 font-medium">forecast</th>
                  <th className="py-3 pr-5 font-medium">actual</th>
                  <th className="py-3 pr-5 font-medium">error</th>
                  <th className="py-3 pr-5 font-medium">nCRPS</th>
                  <th className="py-3 pr-5 font-medium">CRPS</th>
                  <th className="py-3 pr-5 font-medium">PIT</th>
                  <th className="py-3 font-medium">80%</th>
                </tr>
              </thead>
              <tbody>
                {scores.map((score) => {
                  const forecast = getForecastBySlug(
                    score.forecastSlug,
                    forecasts,
                  );
                  if (!forecast) return null;
                  return (
                    <ScoreRow
                      forecast={forecast}
                      key={score.scoreId}
                      score={score}
                    />
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}

function ProductionContractPanel({
  runs,
  specs,
}: {
  runs: PredictionRunRecord[];
  specs: PredictionSpec[];
}) {
  const failedRuns = runs.filter((run) =>
    run.qualityGates.some((gate) => gate.status === "failed"),
  );
  const warningRuns = runs.filter((run) =>
    run.qualityGates.some((gate) => gate.status === "warning"),
  );
  const sampleRun = runs[0];

  return (
    <section
      className="mb-8 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <p className="mb-2 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.15em] text-[var(--theme-text-dim)]">
            production contract
          </p>
          <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
            Specs in, immutable runs out
          </h2>
        </div>
        <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          {failedRuns.length} failed · {warningRuns.length} warnings
        </span>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <ContractStep
          label="spec"
          value={`${specs.length} prediction specs`}
          detail="Question, unit, Ledger target ref, allowed tools, CDF schema, and quality gates."
        />
        <ContractStep
          label="runner"
          value={sampleRun?.runner.id ?? "thesis.recorded-agent-runner"}
          detail="Turns a spec, tool context, and optional pack set into one or more public traces, 201-point CDFs, and run records."
        />
        <ContractStep
          label="store"
          value="Forecast log"
          detail="Stores prediction runs and scores; observed facts stay in PolicyEngine Ledger."
        />
      </div>
    </section>
  );
}

function ContractStep({
  detail,
  label,
  value,
}: {
  detail: string;
  label: string;
  value: string;
}) {
  return (
    <div
      className="rounded-lg border bg-[var(--theme-bg-surface)] p-4"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <p className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
        {label}
      </p>
      <p className="mt-2 text-[0.92rem] font-medium text-[var(--theme-text)]">
        {value}
      </p>
      <p className="mt-2 text-[0.78rem] leading-[1.55] text-[var(--theme-text-muted)]">
        {detail}
      </p>
    </div>
  );
}

function MetricCard({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) {
  return (
    <div
      className="rounded-xl border bg-[var(--theme-bg-elevated)] p-5"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <p className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
        {label}
      </p>
      <p className="mt-3 [font-family:var(--font-display)] text-[2rem] font-semibold leading-none text-[var(--theme-text)]">
        {value}
      </p>
    </div>
  );
}

function ScoreboardPanel({
  forecasts,
  scoreboard,
}: {
  forecasts: ForecastCell[];
  scoreboard: Scoreboard;
}) {
  return (
    <section
      className="mb-8 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <p className="mb-2 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.15em] text-[var(--theme-text-dim)]">
            scoring
          </p>
          <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold text-[var(--theme-text)]">
            Scoreboard
          </h2>
        </div>
        <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          {scoreboard.overall.scored} scored · nCRPS = CRPS / ledger dispersion
          scale
        </span>
      </div>

      <div className="grid grid-cols-1 border-y border-[var(--theme-border)] sm:grid-cols-2 lg:grid-cols-4">
        <ScoreSummaryCell
          detail="lower is better"
          label="mean nCRPS"
          value={formatNullableScore(scoreboard.overall.meanNormalizedCrps)}
        />
        <ScoreSummaryCell
          detail="raw units"
          label="mean CRPS"
          value={formatNullableScore(scoreboard.overall.meanCrps)}
        />
        <ScoreSummaryCell
          detail="raw units"
          label="mean abs error"
          value={formatNullableScore(scoreboard.overall.meanAbsoluteError)}
        />
        <ScoreSummaryCell
          detail="target: 80%"
          label="80% coverage"
          value={formatRate(scoreboard.overall.intervalCoverage)}
        />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-7 xl:grid-cols-3">
        <ScoreGroupTable rows={scoreboard.byAgent} title="By agent" />
        <ScoreGroupTable rows={scoreboard.byModel} title="By model" />
        <ScoreGroupTable
          rows={scoreboard.byRunType}
          showNextResolution
          title="By run type"
        />
      </div>

      {scoreboard.bestScores.length === 0 &&
      scoreboard.worstScores.length === 0 ? (
        <p className="mt-6 max-w-[640px] text-[0.8rem] leading-[1.6] text-[var(--theme-text-muted)]">
          Normalized CRPS extremes appear once resolved scores carry their
          pre-registered normalization scale — CRPS divided by the target's
          historical dispersion in the official ledger at registration. No
          resolved score has an eligible scale yet; scales activate as the
          ledger accumulates pre-cutoff observations per target, and raw CRPS
          stays published on every resolved prediction below meanwhile.
        </p>
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-7 lg:grid-cols-2">
          <ScoreExtremesTable
            forecasts={forecasts}
            scores={scoreboard.bestScores}
            title="Best nCRPS"
          />
          <ScoreExtremesTable
            forecasts={forecasts}
            scores={scoreboard.worstScores}
            title="Largest nCRPS"
          />
        </div>
      )}
    </section>
  );
}

function ScoreSummaryCell({
  detail,
  label,
  value,
}: {
  detail: string;
  label: string;
  value: string;
}) {
  return (
    <div className="border-b border-[var(--theme-border)] py-4 pr-5 sm:border-r lg:border-b-0">
      <p className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
        {label}
      </p>
      <p className="mt-2 [font-family:var(--font-display)] text-[1.75rem] font-semibold leading-none text-[var(--theme-text)]">
        {value}
      </p>
      <p className="mt-2 text-[0.74rem] text-[var(--theme-text-muted)]">
        {detail}
      </p>
    </div>
  );
}

function ScoreGroupTable({
  rows,
  showNextResolution = false,
  title,
}: {
  rows: ScoreboardGroup[];
  showNextResolution?: boolean;
  title: string;
}) {
  return (
    <div>
      <h3 className="mb-3 [font-family:var(--font-display)] text-[0.96rem] font-semibold text-[var(--theme-text)]">
        {title}
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-left text-[0.78rem]">
          <thead>
            <tr className="border-b border-[var(--theme-border)] [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              <th className="py-3 pr-4 font-medium">group</th>
              <th className="py-3 pr-4 font-medium">runs</th>
              <th className="py-3 pr-4 font-medium">scored</th>
              <th className="py-3 pr-4 font-medium">nCRPS</th>
              <th className="py-3 pr-4 font-medium">CRPS</th>
              <th className="py-3 pr-4 font-medium">80%</th>
              {showNextResolution ? (
                <th className="py-3 font-medium">next</th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                className="border-b border-[var(--theme-border)] last:border-b-0"
                key={row.label}
              >
                <td className="py-3 pr-4 font-medium text-[var(--theme-text)]">
                  {row.label}
                </td>
                <td className="py-3 pr-4 text-[var(--theme-text-muted)]">
                  {row.recorded}
                </td>
                <td className="py-3 pr-4 text-[var(--theme-text-muted)]">
                  {row.scored}
                </td>
                <td className="py-3 pr-4 text-[var(--theme-text)]">
                  {formatNullableScore(row.meanNormalizedCrps)}
                </td>
                <td className="py-3 pr-4 text-[var(--theme-text)]">
                  {formatNullableScore(row.meanCrps)}
                </td>
                <td className="py-3 pr-4 text-[var(--theme-text)]">
                  {formatRate(row.intervalCoverage)}
                </td>
                {showNextResolution ? (
                  <td className="py-3 text-[var(--theme-text-muted)]">
                    {row.nextResolutionDate
                      ? formatDisplayDate(row.nextResolutionDate)
                      : row.scored < row.recorded
                        ? "pending"
                        : "complete"}
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ScoreExtremesTable({
  forecasts,
  scores,
  title,
}: {
  forecasts: ForecastCell[];
  scores: ResolvedForecastScore[];
  title: string;
}) {
  return (
    <div>
      <h3 className="mb-3 [font-family:var(--font-display)] text-[0.96rem] font-semibold text-[var(--theme-text)]">
        {title}
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-left text-[0.78rem]">
          <thead>
            <tr className="border-b border-[var(--theme-border)] [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              <th className="py-3 pr-4 font-medium">prediction</th>
              <th className="py-3 pr-4 font-medium">run</th>
              <th className="py-3 pr-4 font-medium">nCRPS</th>
              <th className="py-3 pr-4 font-medium">error</th>
              <th className="py-3 font-medium">80%</th>
            </tr>
          </thead>
          <tbody>
            {scores.map((score) => {
              const forecast = getForecastBySlug(score.forecastSlug, forecasts);
              return (
                <tr
                  className="border-b border-[var(--theme-border)] last:border-b-0"
                  key={score.scoreId}
                >
                  <td className="max-w-[260px] py-3 pr-4 align-top">
                    <Link
                      className="text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
                      href={`/${score.forecastSlug}`}
                    >
                      {forecast?.title ?? score.forecastSlug}
                    </Link>
                    <div className="mt-1 break-all [font-family:var(--font-mono)] text-[0.62rem] text-[var(--theme-text-dim)]">
                      {score.dataPointId}
                    </div>
                  </td>
                  <td className="py-3 pr-4 align-top">
                    <div className="text-[var(--theme-text)]">
                      {score.runLabel}
                    </div>
                    <div className="mt-1 [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
                      {getScoreRunTypeLabel(score)}
                    </div>
                    <div className="mt-1 break-words [font-family:var(--font-mono)] text-[0.58rem] text-[var(--theme-text-dim)]">
                      {score.model ?? "unreported model"}
                    </div>
                  </td>
                  <td className="py-3 pr-4 align-top text-[var(--theme-text)]">
                    {formatNullableScore(score.normalizedCrps)}
                  </td>
                  <td className="py-3 pr-4 align-top text-[var(--theme-text)]">
                    {formatSignedValue(score.signedError, score.unit)}
                  </td>
                  <td className="py-3 align-top text-[var(--theme-text-muted)]">
                    {score.interval80Covered ? "inside" : "outside"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ResolutionQueueRow({
  entry,
}: {
  entry: PredictionResolutionQueueEntry;
}) {
  return (
    <div
      className="rounded-lg border bg-[var(--theme-bg-surface)] p-4"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <Link
            href={`/${entry.forecastSlug}`}
            className="text-[0.92rem] font-medium leading-[1.45] text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
          >
            {entry.title}
          </Link>
          <p className="mt-2 break-all [font-family:var(--font-mono)] text-[0.66rem] text-[var(--theme-text-dim)]">
            {entry.dataPointId}
          </p>
          <p className="mt-2 text-[0.72rem] leading-[1.45] text-[var(--theme-text-muted)]">
            {entry.resolutionSourceUrl ? (
              <a
                className="text-[var(--theme-text-muted)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
                href={entry.resolutionSourceUrl}
              >
                {entry.resolutionSource}
              </a>
            ) : (
              entry.resolutionSource
            )}
          </p>
        </div>
        <span className="shrink-0 rounded-full border border-[var(--theme-border)] px-2 py-[2px] [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
          {COUNTRY_LABEL[entry.country]}
        </span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 text-[0.78rem] text-[var(--theme-text-muted)]">
        <div>
          <p className="[font-family:var(--font-mono)] text-[0.56rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
            resolves
          </p>
          <p className="mt-1 text-[var(--theme-text)]">
            {formatDisplayDate(entry.resolutionDate)}
          </p>
        </div>
        <div>
          <p className="[font-family:var(--font-mono)] text-[0.56rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
            estimate
          </p>
          <p className="mt-1 text-[var(--theme-text)]">
            {formatValue(entry.pointEstimate, entry.unit)}
          </p>
        </div>
      </div>
    </div>
  );
}

function RecordedPredictionRow({
  entry,
}: {
  entry: PredictionRecordedLogEntry;
}) {
  const forecast = getForecastBySlug(entry.forecastSlug);
  if (!forecast) return null;

  const country = getForecastCountry(forecast);
  const summary = entry.distribution.summary;
  const interval = summary.interval80;

  return (
    <tr className="border-b border-[var(--theme-border)] last:border-b-0">
      <td className="max-w-[280px] py-4 pr-5 align-top">
        <Link
          href={`/${forecast.slug}`}
          className="text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
        >
          {forecast.title}
        </Link>
        <div className="mt-1 break-all [font-family:var(--font-mono)] text-[0.68rem] text-[var(--theme-text-dim)]">
          {entry.dataPointId}
        </div>
        <div className="mt-1 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.08em] text-[var(--color-accent)]">
          {entry.runLabel}
        </div>
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text-muted)]">
        {COUNTRY_LABEL[country]}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {entry.recordedAt ? formatLedgerTimestamp(entry.recordedAt) : "seed"}
      </td>
      <td className="max-w-[190px] py-4 pr-5 align-top">
        <div className="text-[var(--theme-text)]">
          {entry.agent ?? "prototype seed"}
        </div>
        <div className="mt-1 break-words [font-family:var(--font-mono)] text-[0.62rem] text-[var(--theme-text-dim)]">
          {entry.model ?? "unreported model"}
        </div>
      </td>
      <td className="max-w-[180px] py-4 pr-5 align-top">
        {entry.activityLog?.length ? (
          <div>
            <div className="[font-family:var(--font-mono)] text-[0.66rem] uppercase tracking-[0.08em] text-[var(--theme-text)]">
              {entry.activityLog.length} artifacts
            </div>
            <div className="mt-1 text-[0.72rem] leading-[1.45] text-[var(--theme-text-muted)]">
              {entry.activityLog
                .slice(0, 3)
                .map((artifact) => artifact.artifactType.replace(/_/g, " "))
                .join(", ")}
            </div>
          </div>
        ) : (
          <span className="[font-family:var(--font-mono)] text-[0.66rem] text-[var(--theme-text-dim)]">
            trace only
          </span>
        )}
      </td>
      <td className="max-w-[220px] py-4 pr-5 align-top">
        {entry.packSet ? (
          <div>
            <div className="[font-family:var(--font-mono)] text-[0.66rem] uppercase tracking-[0.08em] text-[var(--theme-text)]">
              {entry.packSet.label}
            </div>
            <div className="mt-1 text-[0.72rem] leading-[1.45] text-[var(--theme-text-muted)]">
              {entry.packSet.packs.length === 0
                ? "none"
                : entry.packSet.packs.map((pack) => pack.label).join(", ")}
            </div>
          </div>
        ) : (
          <span className="[font-family:var(--font-mono)] text-[0.66rem] text-[var(--theme-text-dim)]">
            unreported
          </span>
        )}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatValue(summary.pointEstimate, forecast.unit)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatValue(interval.lower, forecast.unit)} to{" "}
        {formatValue(interval.upper, forecast.unit).replace(/^\+/, "")}
      </td>
      <td className="py-4 align-top [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
        {entry.distribution.pointCount} points
      </td>
    </tr>
  );
}

function ScoreRow({
  forecast,
  score,
}: {
  forecast: ForecastCell;
  score: ResolvedForecastScore;
}) {
  const country = getForecastCountry(forecast);

  return (
    <tr className="border-b border-[var(--theme-border)] last:border-b-0">
      <td className="max-w-[260px] py-4 pr-5 align-top">
        <Link
          href={`/${forecast.slug}`}
          className="text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
        >
          {forecast.title}
        </Link>
        <div className="mt-1 break-all [font-family:var(--font-mono)] text-[0.68rem] text-[var(--theme-text-dim)]">
          {score.dataPointId}
        </div>
        <div className="mt-1 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.08em] text-[var(--color-accent)]">
          {score.runLabel}
        </div>
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text-muted)]">
        {COUNTRY_LABEL[country]}
      </td>
      <td className="max-w-[160px] py-4 pr-5 align-top">
        <div className="[font-family:var(--font-mono)] text-[0.66rem] uppercase tracking-[0.08em] text-[var(--theme-text)]">
          {getScoreRunTypeLabel(score)}
        </div>
        <div className="mt-1 break-words [font-family:var(--font-mono)] text-[0.6rem] text-[var(--theme-text-dim)]">
          {score.model ?? "unreported model"}
        </div>
        {score.packSet ? (
          <div className="mt-1 text-[0.72rem] leading-[1.45] text-[var(--theme-text-muted)]">
            {score.packSet.label}
          </div>
        ) : null}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatValue(score.pointEstimate, score.unit)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatValue(score.observedValue, score.unit)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatSignedValue(score.signedError, score.unit)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {isNormalizedScoreAggregateEligible(score)
          ? formatNullableScore(score.normalizedCrps)
          : "n/a"}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatCompactNumber(score.crps)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatCompactNumber(score.probabilityIntegralTransform)}
      </td>
      <td className="py-4 align-top">
        <span
          className={`rounded-full border px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em] ${
            score.interval80Covered
              ? "border-[var(--color-horizon-300)] bg-[var(--color-horizon-50)] text-[var(--color-horizon-700)]"
              : "border-[#F2DCAF] bg-[#FFF4DD] text-[#7A5C20]"
          }`}
        >
          {score.interval80Covered ? "inside" : "outside"}
        </span>
      </td>
    </tr>
  );
}

function getForecastBySlug(
  slug: string,
  forecasts: ForecastCell[] = getPublishedForecasts(),
): ForecastCell | undefined {
  return forecasts.find((forecast) => forecast.slug === slug);
}

function buildScoreboard(
  recordedPredictions: PredictionRecordedLogEntry[],
  scores: ResolvedForecastScore[],
  forecasts: ForecastCell[],
): Scoreboard {
  const scoresByNormalizedCrps = scores
    .filter(isNormalizedScoreAggregateEligible)
    .sort((left, right) => {
      const crpsDelta = left.normalizedCrps - right.normalizedCrps;
      if (crpsDelta !== 0) return crpsDelta;
      return left.absoluteError - right.absoluteError;
    });

  return {
    overall: summarizeScores(scores),
    byAgent: buildScoreboardGroups({
      forecasts,
      getRecordedLabel: (entry) => entry.agent ?? "prototype seed",
      getScoreLabel: (score) => score.agent ?? "prototype seed",
      recordedPredictions,
      scores,
    }),
    byModel: buildScoreboardGroups({
      forecasts,
      getRecordedLabel: (entry) => entry.model ?? "unreported model",
      getScoreLabel: (score) => score.model ?? "unreported model",
      recordedPredictions,
      scores,
    }),
    byRunType: buildScoreboardGroups({
      forecasts,
      getRecordedLabel: getRecordedRunTypeLabel,
      getScoreLabel: getScoreRunTypeLabel,
      labelOrder: ["Primary", "No packs", "With packs", "Ensemble"],
      recordedPredictions,
      scores,
    }),
    bestScores: scoresByNormalizedCrps.slice(0, 5),
    worstScores: [...scoresByNormalizedCrps].reverse().slice(0, 5),
  };
}

function buildScoreboardGroups({
  forecasts,
  getRecordedLabel,
  getScoreLabel,
  labelOrder = [],
  recordedPredictions,
  scores,
}: {
  forecasts: ForecastCell[];
  getRecordedLabel: (entry: PredictionRecordedLogEntry) => string;
  getScoreLabel: (score: ResolvedForecastScore) => string;
  labelOrder?: string[];
  recordedPredictions: PredictionRecordedLogEntry[];
  scores: ResolvedForecastScore[];
}): ScoreboardGroup[] {
  const labels = new Set<string>();
  const recordedCounts = new Map<string, number>();
  const nextResolutionDates = new Map<string, string>();
  const scoredRunIds = new Set(scores.map((score) => score.runId));
  const scoresByLabel = new Map<string, ResolvedForecastScore[]>();

  for (const entry of recordedPredictions) {
    const label = getRecordedLabel(entry);
    labels.add(label);
    recordedCounts.set(label, (recordedCounts.get(label) ?? 0) + 1);

    if (!scoredRunIds.has(entry.runId)) {
      const resolutionDate = getForecastBySlug(
        entry.forecastSlug,
        forecasts,
      )?.resolutionDate;
      const existingDate = nextResolutionDates.get(label);
      if (resolutionDate && (!existingDate || resolutionDate < existingDate)) {
        nextResolutionDates.set(label, resolutionDate);
      }
    }
  }

  for (const score of scores) {
    const label = getScoreLabel(score);
    labels.add(label);
    const scoreGroup = scoresByLabel.get(label) ?? [];
    scoreGroup.push(score);
    scoresByLabel.set(label, scoreGroup);
  }

  const labelOrderIndex = new Map(
    labelOrder.map((label, index) => [label, index]),
  );

  return [...labels]
    .map((label) => ({
      label,
      recorded: recordedCounts.get(label) ?? 0,
      nextResolutionDate: nextResolutionDates.get(label),
      ...summarizeScores(scoresByLabel.get(label) ?? []),
    }))
    .sort((left, right) => {
      const leftOrder = labelOrderIndex.get(left.label);
      const rightOrder = labelOrderIndex.get(right.label);
      if (leftOrder !== undefined || rightOrder !== undefined) {
        return (
          (leftOrder ?? Number.MAX_SAFE_INTEGER) -
          (rightOrder ?? Number.MAX_SAFE_INTEGER)
        );
      }
      if (right.scored !== left.scored) return right.scored - left.scored;
      if (right.recorded !== left.recorded) {
        return right.recorded - left.recorded;
      }
      return left.label.localeCompare(right.label);
    });
}

function summarizeScores(scores: ResolvedForecastScore[]): ScoreboardSummary {
  const normalizedScores = scores.filter(isNormalizedScoreAggregateEligible);
  return {
    scored: scores.length,
    meanNormalizedCrps: mean(
      normalizedScores
        .map((score) => score.normalizedCrps)
        .filter((value): value is number => value !== null),
    ),
    meanCrps: mean(scores.map((score) => score.crps)),
    meanAbsoluteError: mean(scores.map((score) => score.absoluteError)),
    meanNormalizedAbsoluteError: mean(
      normalizedScores
        .map((score) => score.normalizedAbsoluteError)
        .filter((value): value is number => value !== null),
    ),
    intervalCoverage:
      scores.length === 0
        ? null
        : scores.filter((score) => score.interval80Covered).length /
          scores.length,
  };
}

function mean(values: number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function getRecordedRunTypeLabel(entry: PredictionRecordedLogEntry): string {
  return formatRunTypeLabel(entry.packSet?.mode ?? "primary");
}

function getScoreRunTypeLabel(score: ResolvedForecastScore): string {
  return formatRunTypeLabel(score.packMode);
}

function formatRunTypeLabel(mode: string): string {
  switch (mode) {
    case "none":
      return "No packs";
    case "with_packs":
      return "With packs";
    case "ensemble":
      return "Ensemble";
    default:
      return "Primary";
  }
}

function formatSignedValue(value: number, unit: ForecastCell["unit"]): string {
  const formatted = formatValue(Math.abs(value), unit).replace(/^\+/, "");
  if (value === 0) return formatted;
  return `${value > 0 ? "+" : "-"}${formatted}`;
}

function formatNullableScore(value: number | null): string {
  return value === null ? "n/a" : formatCompactNumber(value);
}

function formatRate(value: number | null): string {
  return value === null ? "n/a" : `${Math.round(value * 100)}%`;
}

function formatCompactNumber(value: number): string {
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(1);
  if (Math.abs(value) >= 1) return value.toFixed(2);
  return value.toPrecision(2);
}

function formatDisplayDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

function formatLedgerTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().slice(0, 10);
}
