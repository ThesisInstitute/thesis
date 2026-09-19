"use client";

import { useState } from "react";
import { AgentReasoning } from "@/components/AgentReasoning";
import { classifyTraceProvenance } from "@/data/trace-provenance";
import { ForecastTrend, ForecastViz } from "@/components/ForecastViz";
import {
  formatValue,
  getForecastRunEntries,
  getResolutionResult,
  type ForecastCell,
  type ForecastRunEntry,
  type PredictionPackReference,
  type ReasoningStep,
} from "@/data/forecast-cells";
import type { ResolvedForecastScore } from "@/data/thesis-log";
import type { SavedForecastRun } from "@/lib/saved-forecast";

interface ForecastRuntimeProps {
  forecast: ForecastCell;
  resolvedScore?: ResolvedForecastScore;
  savedForecast?: SavedForecastRun | null;
}

export function ForecastRuntime({
  forecast: forecastCell,
  resolvedScore,
  savedForecast,
}: ForecastRuntimeProps) {
  // The estimate and explanation are one saved result. Replaying it never
  // starts another calculation or replaces the estimate after hydration.
  const displayedForecast = savedForecast?.forecast ?? forecastCell;
  const drivers = savedForecast?.forecast.drivers ?? forecastCell.drivers;
  const recordedRuns = getForecastRunEntries(forecastCell).map((run) =>
    savedForecast && run.isPrimary
      ? { ...run, label: "Catalog forecast" }
      : run,
  );
  const isRecorded = Boolean(savedForecast || forecastCell.predictionRun);

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[1.05fr_1fr]">
      <section className="min-w-0">
        <div
          className="rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <div role="region" aria-label="Forecast estimate">
            <div className="mb-4 flex items-baseline justify-between gap-4">
              <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
                {savedForecast
                  ? "latest saved forecast"
                  : forecastCell.predictionRun
                    ? "current forecast"
                    : "static prototype forecast"}{" "}
                · 80% CI
              </span>
              <span className="[font-family:var(--font-display)] text-[2rem] font-semibold leading-none text-[var(--color-accent)]">
                {formatValue(
                  displayedForecast.pointEstimate,
                  forecastCell.unit,
                )}
              </span>
            </div>
            <ForecastViz
              point={displayedForecast.pointEstimate}
              ciLow={displayedForecast.ciLow}
              ciHigh={displayedForecast.ciHigh}
              unit={forecastCell.unit}
              history={forecastCell.historicalContext}
              size="full"
            />
            {forecastCell.historicalContext.length > 0 && (
              <div
                className="mt-6 border-t pt-5"
                style={{ borderColor: "var(--theme-border)" }}
              >
                <div className="mb-3 flex items-baseline justify-between gap-4">
                  <h2 className="[font-family:var(--font-display)] text-[0.95rem] font-semibold tracking-[-0.01em]">
                    Trend
                  </h2>
                  <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                    history + forecast
                  </span>
                </div>
                <ForecastTrend
                  point={displayedForecast.pointEstimate}
                  ciLow={displayedForecast.ciLow}
                  ciHigh={displayedForecast.ciHigh}
                  unit={forecastCell.unit}
                  history={forecastCell.historicalContext}
                  targetLabel={targetPeriodLabel(forecastCell)}
                  actual={
                    forecastCell.resolvedOutcome
                      ? {
                          label: "actual",
                          value: forecastCell.resolvedOutcome.value,
                        }
                      : undefined
                  }
                />
              </div>
            )}
            <p className="mt-4 [font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              {savedForecast
                ? savedForecastSource(savedForecast)
                : forecastCell.predictionRun
                  ? `${forecastCell.predictionRun.agent} · ${forecastCell.predictionRun.runAt}`
                  : "static prototype estimate · seeded forecast value"}
            </p>
          </div>
          {forecastCell.resolvedOutcome && (
            <ResolvedOutcomePanel
              forecast={forecastCell}
              score={resolvedScore}
              catalogForecast={Boolean(savedForecast)}
            />
          )}
          {savedForecast ? (
            <SavedForecastRecordPanel savedForecast={savedForecast} />
          ) : (
            <ThesisLogRecordPanel forecast={forecastCell} />
          )}
          <RunComparisonPanel runs={recordedRuns} unit={forecastCell.unit} />
        </div>

        <div
          className="mt-6 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <h2 className="mb-3 [font-family:var(--font-display)] text-[0.95rem] font-semibold tracking-[-0.01em]">
            Key drivers
          </h2>
          <ul className="grid grid-cols-1 gap-2 [font-family:var(--font-body)] text-[0.88rem] text-[var(--theme-text)] sm:grid-cols-2">
            {drivers.map((driver) => (
              <li key={driver} className="flex items-start gap-2 leading-[1.5]">
                <span className="mt-[6px] inline-block h-1 w-2 shrink-0 bg-[var(--color-accent)]" />
                <span>{driver}</span>
              </li>
            ))}
          </ul>
        </div>

        <div
          className="mt-6 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <h2 className="mb-4 [font-family:var(--font-display)] text-[0.95rem] font-semibold tracking-[-0.01em]">
            Resolution
          </h2>
          <dl className="grid grid-cols-1 gap-x-5 gap-y-3 [font-family:var(--font-body)] text-[0.86rem] sm:grid-cols-[120px_minmax(0,1fr)]">
            <dt className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              source
            </dt>
            <dd className="min-w-0 break-words text-[var(--theme-text)]">
              {forecastCell.resolutionSourceUrl ? (
                <a
                  className="text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
                  href={forecastCell.resolutionSourceUrl}
                >
                  {forecastCell.resolutionSource}
                </a>
              ) : (
                forecastCell.resolutionSource
              )}
            </dd>
            <dt className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              {forecastCell.resolvedOutcome ? "resolved" : "expected"}
            </dt>
            <dd className="min-w-0 break-words text-[var(--theme-text)]">
              {formatFullDate(
                forecastCell.resolvedOutcome?.resolvedAt ??
                  forecastCell.resolutionDate,
              )}
            </dd>
            {forecastCell.resolvedOutcome && (
              <>
                <dt className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                  actual
                </dt>
                <dd className="min-w-0 break-words text-[var(--theme-text)]">
                  {formatValue(
                    forecastCell.resolvedOutcome.value,
                    forecastCell.unit,
                  )}
                </dd>
              </>
            )}
            <dt className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              rule
            </dt>
            <dd className="min-w-0 break-words leading-[1.55] text-[var(--theme-text)]">
              {forecastCell.resolutionRule}
            </dd>
            {forecastCell.dataPointId && (
              <>
                <dt className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                  Data point
                </dt>
                <dd className="min-w-0 break-all [font-family:var(--font-mono)] text-[0.78rem] leading-[1.55] text-[var(--color-horizon-700)]">
                  {forecastCell.dataPointId}
                </dd>
              </>
            )}
            {forecastCell.policyParameter && (
              <>
                <dt className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                  Policy parameter
                </dt>
                <dd className="min-w-0 break-all [font-family:var(--font-mono)] text-[0.78rem] leading-[1.55] text-[var(--color-rose-700)]">
                  {forecastCell.policyParameter}
                </dd>
              </>
            )}
          </dl>
        </div>
        {forecastCell.series && <SeriesMetadataPanel forecast={forecastCell} />}
      </section>

      <section className="min-w-0">
        <div className="mb-3 flex items-center justify-between gap-4">
          <h2 className="[font-family:var(--font-display)] text-[1rem] font-semibold tracking-[-0.01em]">
            {savedForecast
              ? "Saved forecast · explanation"
              : "Analyst agent · reasoning trace"}
          </h2>
          <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
            {isRecorded ? "recorded replay" : "static prototype"}
          </span>
        </div>
        <TraceStatusBanner
          forecast={forecastCell}
          savedForecast={savedForecast}
        />
        <AgentReasoning
          key={savedForecast?.artifactPath ?? forecastCell.slug}
          steps={savedForecast?.reasoning ?? forecastCell.reasoning}
          unit={forecastCell.unit}
          provenance={
            savedForecast
              ? "activity_backed"
              : classifyTraceProvenance(forecastCell)
          }
        />
        <p className="mt-3 text-[0.76rem] leading-[1.55] text-[var(--theme-text-dim)]">
          {savedForecast
            ? "This saved API result includes the forecast explanation, assumptions, and caveats. The original streamed tool activity was not archived. Replaying this explanation does not run a new forecast."
            : forecastCell.predictionRun
              ? "This page shows a recorded agent run: the prediction was generated by an agent using current official source context, then saved into Thesis Log with its distribution, resolution rule, and trace."
              : "The route, resolution rule, and catalog entry are live. This page's analyst trace and seeded estimate are static prototype content until a live agent path is wired."}
        </p>
      </section>
    </div>
  );
}

function ResolvedOutcomePanel({
  forecast,
  score,
  catalogForecast = false,
}: {
  forecast: ForecastCell;
  score?: ResolvedForecastScore;
  catalogForecast?: boolean;
}) {
  const outcome = forecast.resolvedOutcome;
  if (!outcome) return null;
  const result = getResolutionResult(forecast);
  const resultLabel =
    result === "inside" ? "inside 80% interval" : "outside 80% interval";

  return (
    <div
      className="mt-5 rounded-lg border bg-[var(--theme-bg-surface)] p-4"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
          {catalogForecast ? "Catalog forecast outcome" : "resolved outcome"}
        </span>
        <span
          className={`rounded-full border px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em] ${
            result === "inside"
              ? "border-[var(--color-horizon-300)] bg-[var(--color-horizon-50)] text-[var(--color-horizon-700)]"
              : "border-[#F2DCAF] bg-[#FFF4DD] text-[#7A5C20]"
          }`}
        >
          {resultLabel}
        </span>
      </div>
      <dl className="grid grid-cols-1 gap-x-5 gap-y-2 [font-family:var(--font-body)] text-[0.84rem] sm:grid-cols-[120px_minmax(0,1fr)]">
        <dt className="[font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          actual
        </dt>
        <dd className="text-[var(--theme-text)]">
          {formatValue(outcome.value, forecast.unit)}
        </dd>
        <dt className="[font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          forecast
        </dt>
        <dd className="text-[var(--theme-text)]">
          {formatValue(forecast.pointEstimate, forecast.unit)} with 80% CI [
          {formatValue(forecast.ciLow, forecast.unit)},{" "}
          {formatValue(forecast.ciHigh, forecast.unit)}]
        </dd>
        {score && (
          <>
            <dt className="[font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              error
            </dt>
            <dd className="text-[var(--theme-text)]">
              {formatSignedValue(score.signedError, forecast.unit)} · absolute{" "}
              {formatValue(score.absoluteError, forecast.unit)}
            </dd>
            <dt className="[font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              cdf score
            </dt>
            <dd className="text-[var(--theme-text)]">
              CRPS {formatCompactNumber(score.crps)} · PIT{" "}
              {formatCompactNumber(score.probabilityIntegralTransform)}
            </dd>
          </>
        )}
        <dt className="[font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          source
        </dt>
        <dd className="min-w-0 break-words text-[var(--theme-text)]">
          {outcome.sourceUrl ? (
            <a
              className="text-[var(--color-horizon-700)] no-underline hover:underline"
              href={outcome.sourceUrl}
            >
              {outcome.source}
            </a>
          ) : (
            outcome.source
          )}
        </dd>
      </dl>
      {outcome.note && (
        <p className="mt-3 text-[0.78rem] leading-[1.55] text-[var(--theme-text-muted)]">
          {outcome.note}
        </p>
      )}
    </div>
  );
}

function savedForecastSource({ forecast }: SavedForecastRun): string {
  switch (forecast.source) {
    case "ai_gateway":
      return `generated by ${forecast.model ?? "AI Gateway"}`;
    case "deterministic_fallback":
      return "BLS inputs · deterministic fallback";
    case "calibration_fallback":
      return "PolicyEngine inputs · calibration fallback";
    case "census_calibration_fallback":
      return "Census + PolicyEngine inputs · calibration fallback";
    default:
      return "saved API forecast";
  }
}

function SavedForecastRecordPanel({
  savedForecast,
}: {
  savedForecast: SavedForecastRun;
}) {
  return (
    <div
      className="mt-5 rounded-lg border bg-[var(--theme-bg-surface)] p-4"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
          Saved result
        </span>
        <a
          className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--color-accent)] no-underline hover:no-underline"
          href={`https://github.com/ThesisInstitute/thesis/blob/main/${savedForecast.artifactPath}`}
        >
          Archived result →
        </a>
      </div>
      <dl className="grid grid-cols-1 gap-x-5 gap-y-2 [font-family:var(--font-body)] text-[0.82rem] sm:grid-cols-[120px_minmax(0,1fr)]">
        <dt className="[font-family:var(--font-mono)] text-[0.66rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          Generated
        </dt>
        <dd>{formatRecordedTime(savedForecast.forecast.generatedAt)}</dd>
      </dl>
    </div>
  );
}

function formatRecordedTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

function ThesisLogRecordPanel({ forecast }: { forecast: ForecastCell }) {
  const distribution = forecast.predictionDistribution;
  const run = forecast.predictionRun;
  const runs = getForecastRunEntries(forecast);
  if (!distribution && !run && !forecast.dataPointId) return null;

  return (
    <div
      className="mt-5 rounded-lg border bg-[var(--theme-bg-surface)] p-4"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
          recorded in Thesis Log
        </span>
        <a
          className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--color-accent)] no-underline hover:no-underline"
          href="/log"
        >
          Open log →
        </a>
      </div>
      <dl className="grid grid-cols-1 gap-x-5 gap-y-2 [font-family:var(--font-body)] text-[0.82rem] sm:grid-cols-[120px_minmax(0,1fr)]">
        <dt className="[font-family:var(--font-mono)] text-[0.66rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          record
        </dt>
        <dd className="text-[var(--theme-text)]">
          {run?.runAt ? formatFullDate(run.runAt) : "prototype seed"}
        </dd>
        <dt className="[font-family:var(--font-mono)] text-[0.66rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          agent
        </dt>
        <dd className="text-[var(--theme-text)]">
          {run?.agent ?? "prototype seed"}
        </dd>
        <dt className="[font-family:var(--font-mono)] text-[0.66rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          distribution
        </dt>
        <dd className="text-[var(--theme-text)]">
          {runs.length > 1
            ? `${runs.length} runs · ${distribution?.pointCount ?? 201} CDF points each`
            : distribution
              ? `${distribution.pointCount} CDF points`
              : "not recorded"}
        </dd>
        {run?.model && (
          <>
            <dt className="[font-family:var(--font-mono)] text-[0.66rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              model
            </dt>
            <dd className="text-[var(--theme-text)]">{run.model}</dd>
          </>
        )}
        {forecast.dataPointId && (
          <>
            <dt className="[font-family:var(--font-mono)] text-[0.66rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              ledger fact
            </dt>
            <dd className="min-w-0 break-all [font-family:var(--font-mono)] text-[0.76rem] text-[var(--color-horizon-700)]">
              <a
                className="text-[var(--color-horizon-700)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
                href="/ledger"
              >
                {forecast.dataPointId}
              </a>
            </dd>
          </>
        )}
      </dl>
    </div>
  );
}

function RunComparisonPanel({
  runs,
  unit,
}: {
  runs: ForecastRunEntry[];
  unit: ForecastCell["unit"];
}) {
  const displayRuns = [...runs].sort(compareRunsByRecordedTime);
  const packs = buildUniquePacks(displayRuns);
  const [selectedPackKey, setSelectedPackKey] = useState<string | null>(null);

  if (runs.length <= 1) return null;
  const baseline =
    displayRuns.find((run) => run.packSet?.mode === "none") ?? displayRuns[0];
  const domain = buildRunDomain(displayRuns);
  const agentOrdinals = buildAgentOrdinals(displayRuns);
  const agentCount = new Set(displayRuns.map(getRunAgentLabel)).size;
  const modelCount = new Set(displayRuns.map(getRunModelLabel)).size;
  const packSetCount = new Set(
    displayRuns.map((run) => run.packSet?.packSetId ?? "unreported"),
  ).size;
  const reviewedCount = displayRuns.filter(
    (run) => run.predictionRun?.preSubmitReview?.status === "completed",
  ).length;
  const activePackKey =
    packs.find((pack) => pack.key === selectedPackKey)?.key ??
    packs[0]?.key ??
    null;

  return (
    <div
      className="mt-5 border-t pt-5"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="[font-family:var(--font-display)] text-[0.95rem] font-semibold tracking-[-0.01em]">
          Forecast runs
        </h2>
        <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          same target · agents, packs, updates
        </span>
      </div>
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <RunStat label="runs" value={displayRuns.length} />
        <RunStat label="agents" value={agentCount} />
        <RunStat label="models" value={modelCount} />
        <RunStat label="pack sets" value={packSetCount} />
        <RunStat label="reviewed" value={reviewedCount} />
      </div>
      {packs.length > 0 && activePackKey && (
        <PackVisualizer
          onSelectPack={setSelectedPackKey}
          packs={packs}
          selectedPackKey={activePackKey}
        />
      )}
      <div className="space-y-3">
        {displayRuns.map((run) => (
          <ForecastRunLane
            agentOrdinal={agentOrdinals.get(run.variantId)}
            baseline={baseline}
            domain={domain}
            key={run.variantId}
            onSelectPack={setSelectedPackKey}
            run={run}
            selectedPackKey={activePackKey}
            unit={unit}
          />
        ))}
      </div>
    </div>
  );
}

function RunStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="border-y border-[var(--theme-border)] py-3">
      <div className="[font-family:var(--font-display)] text-[1.55rem] font-semibold leading-none text-[var(--theme-text)]">
        {value}
      </div>
      <div className="mt-1 [font-family:var(--font-mono)] text-[0.56rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
        {label}
      </div>
    </div>
  );
}

function ForecastRunLane({
  agentOrdinal,
  baseline,
  domain,
  onSelectPack,
  run,
  selectedPackKey,
  unit,
}: {
  agentOrdinal?: { count: number; index: number };
  baseline: ForecastRunEntry;
  domain: { lower: number; upper: number };
  onSelectPack: (packKey: string) => void;
  run: ForecastRunEntry;
  selectedPackKey: string | null;
  unit: ForecastCell["unit"];
}) {
  const intervalLeft = runScalePosition(run.ciLow, domain);
  const intervalRight = runScalePosition(run.ciHigh, domain);
  const point = runScalePosition(run.pointEstimate, domain);
  const delta = run.pointEstimate - baseline.pointEstimate;
  const agentLabel = getRunAgentLabel(run);
  const modelLabel = getRunModelLabel(run);
  const ciLowLabel = formatValue(run.ciLow, unit).replace(/^\+/, "");
  const ciHighLabel = formatValue(run.ciHigh, unit).replace(/^\+/, "");
  // A point projection (e.g. a published BLS point estimate) carries a
  // negligible display interval, so its bounds round to the same value.
  // Render it as a point rather than a nonsensical "80% X to X" band.
  const isPointProjection = ciLowLabel === ciHighLabel;
  const pointLabel = formatValue(run.pointEstimate, unit).replace(/^\+/, "");

  return (
    <div
      className="border-y border-[var(--theme-border)] py-4"
      data-forecast-run={run.variantId}
    >
      <div className="grid grid-cols-[minmax(0,0.58fr)_minmax(0,1fr)_minmax(5.5rem,auto)] gap-4 max-md:grid-cols-1">
        <div className="min-w-0">
          <div className="font-medium leading-[1.35] text-[var(--theme-text)]">
            {run.label}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
            <span>{agentLabel}</span>
            <span>{modelLabel}</span>
            <span>{formatRunRecordedAt(run)}</span>
            {run.externalSubmission && (
              <span
                className="rounded-full border border-[#A94E80] px-2 py-[1px] text-[#A94E80]"
                title={`Open-challenge submission by ${run.externalSubmission.challenger} (self-declared ${run.externalSubmission.systemType}). Shows the submission record; a reasoning trace is not required.`}
              >
                external · {run.externalSubmission.systemType}
              </span>
            )}
            {agentOrdinal && agentOrdinal.count > 1 && (
              <span className="rounded-full border border-[var(--theme-border)] px-2 py-[1px]">
                update {agentOrdinal.index}/{agentOrdinal.count}
              </span>
            )}
            {run.predictionRun?.preSubmitReview && (
              <span className="rounded-full border border-[var(--theme-border)] px-2 py-[1px]">
                review{" "}
                {run.predictionRun.preSubmitReview.status.replace(/_/g, " ")}
              </span>
            )}
          </div>
          {run.description && (
            <p className="mt-2 text-[0.74rem] leading-[1.45] text-[var(--theme-text-muted)]">
              {run.description}
            </p>
          )}
          <div className="mt-3">
            <PackSetSummary
              onSelectPack={onSelectPack}
              run={run}
              selectedPackKey={selectedPackKey}
            />
          </div>
        </div>

        <div className="min-w-0">
          <div className="relative h-10">
            <div className="absolute left-0 right-0 top-[18px] h-[2px] bg-[var(--theme-border)]" />
            {!isPointProjection && (
              <div
                className="absolute top-[14px] h-[10px] rounded-full bg-[var(--color-horizon-300)]"
                style={{
                  left: `${intervalLeft}%`,
                  width: `${Math.max(intervalRight - intervalLeft, 1)}%`,
                }}
              />
            )}
            <div
              className="absolute top-[9px] h-5 w-5 -translate-x-1/2 rounded-full border-2 border-white bg-[var(--color-accent)] shadow-sm"
              style={{ left: `${point}%` }}
            />
          </div>
          <div className="mt-1 flex items-center justify-between [font-family:var(--font-mono)] text-[0.58rem] text-[var(--theme-text-dim)]">
            <span>{formatValue(domain.lower, unit)}</span>
            <span>
              {isPointProjection
                ? `point ${pointLabel}`
                : `80% ${ciLowLabel} to ${ciHighLabel}`}
            </span>
            <span>{formatValue(domain.upper, unit)}</span>
          </div>
          <RunTraceDetails run={run} unit={unit} />
        </div>

        <div className="text-right max-md:text-left">
          <div className="[font-family:var(--font-display)] text-[1.75rem] font-semibold leading-none text-[var(--color-accent)]">
            {formatValue(run.pointEstimate, unit)}
          </div>
          <div className="mt-2 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
            {run === baseline ? "baseline" : formatSignedValue(delta, unit)}
          </div>
        </div>
      </div>
    </div>
  );
}

function RunTraceDetails({
  run,
  unit,
}: {
  run: ForecastRunEntry;
  unit: ForecastCell["unit"];
}) {
  return (
    <details className="mt-3 border-t border-[var(--theme-border)] pt-3">
      <summary className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
        {run.externalSubmission
          ? "submission record (no reasoning trace required)"
          : "public trace"}
      </summary>
      <div className="mt-3 space-y-2">
        {run.predictionRun?.preSubmitReview && (
          <PreSubmitReviewTrace review={run.predictionRun.preSubmitReview} />
        )}
        {run.reasoning.map((step, index) => (
          <RunTraceStep key={index} step={step} unit={unit} />
        ))}
      </div>
    </details>
  );
}

function PreSubmitReviewTrace({
  review,
}: {
  review: NonNullable<
    NonNullable<ForecastRunEntry["predictionRun"]>["preSubmitReview"]
  >;
}) {
  return (
    <div
      className="border-l-2 border-[var(--color-accent)] pl-3"
      data-pre-submit-review=""
    >
      <div className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--color-accent)]">
        pre-submit review · {review.status.replace(/_/g, " ")}
      </div>
      <p className="mt-1 text-[0.74rem] leading-[1.55] text-[var(--theme-text-muted)]">
        {review.summary}
      </p>
      {review.findings.length > 0 && (
        <ul className="mt-2 space-y-1">
          {review.findings.slice(0, 3).map((finding) => (
            <li
              className="text-[0.72rem] leading-[1.45] text-[var(--theme-text-muted)]"
              key={finding.findingId}
            >
              <span className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
                {finding.severity}
              </span>{" "}
              {finding.rubricItem}: {finding.summary}
            </li>
          ))}
        </ul>
      )}
      {review.dispositions.length > 0 && (
        <div className="mt-2 space-y-1">
          {review.dispositions.slice(0, 3).map((disposition) => (
            <p
              className="text-[0.72rem] leading-[1.45] text-[var(--theme-text-muted)]"
              key={disposition.findingId}
            >
              <span className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
                disposition
              </span>{" "}
              {disposition.decision.replace(/_/g, " ")}: {disposition.rationale}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function RunTraceStep({
  step,
  unit,
}: {
  step: ReasoningStep;
  unit: ForecastCell["unit"];
}) {
  if (step.kind === "heading") {
    return (
      <div className="[font-family:var(--font-display)] text-[0.82rem] font-semibold text-[var(--theme-text)]">
        {step.text}
      </div>
    );
  }
  if (step.kind === "text") {
    return (
      <p className="text-[0.75rem] leading-[1.55] text-[var(--theme-text-muted)]">
        {step.text}
      </p>
    );
  }
  if (step.kind === "math") {
    return (
      <p className="break-words [font-family:var(--font-mono)] text-[0.68rem] leading-[1.55] text-[var(--theme-text)]">
        {step.text}
      </p>
    );
  }
  if (step.kind === "tool") {
    return (
      <div className="break-words [font-family:var(--font-mono)] text-[0.66rem] leading-[1.55] text-[var(--theme-text-dim)]">
        <div>
          <span className="text-[var(--color-accent)]">
            {step.tool ?? "policyengine.simulate"}
          </span>{" "}
          {step.call}
        </div>
        {step.result && (
          <div className="mt-1 border-l border-[var(--theme-border)] pl-3 text-[var(--theme-text)]">
            <span className="text-[var(--theme-text-dim)]">result </span>
            {step.result}
          </div>
        )}
      </div>
    );
  }
  const stepLow = formatValue(step.ciLow, unit).replace(/^\+/, "");
  const stepHigh = formatValue(step.ciHigh, unit).replace(/^\+/, "");
  return (
    <div className="[font-family:var(--font-mono)] text-[0.7rem] text-[var(--theme-text)]">
      {stepLow === stepHigh
        ? `forecast ${formatValue(step.point, unit)} · point`
        : `forecast ${formatValue(step.point, unit)} · 80% [${stepLow}, ${stepHigh}]`}
    </div>
  );
}

function compareRunsByRecordedTime(
  left: ForecastRunEntry,
  right: ForecastRunEntry,
) {
  const leftTime = parseRunTime(left);
  const rightTime = parseRunTime(right);
  if (leftTime !== rightTime) return leftTime - rightTime;
  return left.label.localeCompare(right.label);
}

function parseRunTime(run: ForecastRunEntry) {
  const value = run.predictionRun?.runAt;
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function buildRunDomain(runs: ForecastRunEntry[]) {
  const lower = Math.min(...runs.map((run) => run.ciLow));
  const upper = Math.max(...runs.map((run) => run.ciHigh));
  const spread = Math.max(upper - lower, 0.1);
  return {
    lower: lower - spread * 0.08,
    upper: upper + spread * 0.08,
  };
}

function runScalePosition(
  value: number,
  domain: { lower: number; upper: number },
) {
  const width = domain.upper - domain.lower;
  if (width <= 0) return 50;
  return Math.max(0, Math.min(100, ((value - domain.lower) / width) * 100));
}

function buildAgentOrdinals(runs: ForecastRunEntry[]) {
  const totals = new Map<string, number>();
  const seen = new Map<string, number>();
  const ordinals = new Map<string, { count: number; index: number }>();

  for (const run of runs) {
    const agent = getRunAgentLabel(run);
    totals.set(agent, (totals.get(agent) ?? 0) + 1);
  }
  for (const run of runs) {
    const agent = getRunAgentLabel(run);
    const next = (seen.get(agent) ?? 0) + 1;
    seen.set(agent, next);
    ordinals.set(run.variantId, {
      count: totals.get(agent) ?? 1,
      index: next,
    });
  }

  return ordinals;
}

function getRunAgentLabel(run: ForecastRunEntry) {
  return run.predictionRun?.agent ?? "prototype seed";
}

function getRunModelLabel(run: ForecastRunEntry) {
  return run.predictionRun?.model ?? "unreported model";
}

function formatRunRecordedAt(run: ForecastRunEntry) {
  const value = run.predictionRun?.runAt;
  if (!value) return "seed";
  return formatShortFullDate(value);
}

interface PackVisualizerEntry {
  key: string;
  pack: PredictionPackReference;
  agents: string[];
  packSetLabels: string[];
  runLabels: string[];
}

function PackVisualizer({
  onSelectPack,
  packs,
  selectedPackKey,
}: {
  onSelectPack: (packKey: string) => void;
  packs: PackVisualizerEntry[];
  selectedPackKey: string;
}) {
  const selectedEntry =
    packs.find((pack) => pack.key === selectedPackKey) ?? packs[0];
  const selectedPack = selectedEntry.pack;

  return (
    <div
      className="mb-5 border-y border-[var(--theme-border)] py-4"
      data-pack-visualizer=""
      data-selected-pack-key={selectedEntry.key}
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <h3 className="[font-family:var(--font-display)] text-[0.88rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
          Pack visualizer
        </h3>
        <span className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          {packs.length} {packs.length === 1 ? "pack" : "packs"}
        </span>
      </div>
      <div className="grid grid-cols-[minmax(170px,0.42fr)_minmax(0,1fr)] gap-4 max-md:grid-cols-1">
        <div className="flex flex-col gap-2">
          {packs.map((entry) => {
            const isSelected = entry.key === selectedEntry.key;
            return (
              <button
                aria-pressed={isSelected}
                className={`min-w-0 border px-3 py-2 text-left transition-colors ${
                  isSelected
                    ? "border-[var(--color-accent)] bg-[var(--color-horizon-50)]"
                    : "border-[var(--theme-border)] bg-[var(--theme-bg-surface)] hover:border-[var(--color-horizon-300)]"
                }`}
                data-pack-key={entry.key}
                key={entry.key}
                onClick={() => onSelectPack(entry.key)}
                type="button"
              >
                <span className="block truncate [font-family:var(--font-body)] text-[0.78rem] font-medium text-[var(--theme-text)]">
                  {entry.pack.label}
                </span>
                <span className="mt-1 block [font-family:var(--font-mono)] text-[0.54rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
                  {entry.pack.kind} · v{entry.pack.version}
                </span>
              </button>
            );
          })}
        </div>

        <div className="min-w-0 border-l border-[var(--theme-border)] pl-4 max-md:border-l-0 max-md:border-t max-md:pl-0 max-md:pt-4">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="[font-family:var(--font-mono)] text-[0.56rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                selected pack
              </div>
              <h4 className="mt-1 [font-family:var(--font-display)] text-[1rem] font-semibold leading-[1.2] text-[var(--theme-text)]">
                {selectedPack.label}
              </h4>
            </div>
            <span className="border border-[var(--theme-border)] px-2 py-[2px] [font-family:var(--font-mono)] text-[0.56rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
              {selectedPack.kind}
            </span>
          </div>
          <p className="text-[0.8rem] leading-[1.55] text-[var(--theme-text-muted)]">
            {selectedPack.summary}
          </p>
          <a
            className="mt-3 inline-block [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--color-accent)] no-underline hover:no-underline"
            href={`/briefings/${selectedPack.packId}`}
          >
            Open pack page →
          </a>
          <dl className="mt-4 grid grid-cols-1 gap-x-5 gap-y-2 [font-family:var(--font-body)] text-[0.76rem] sm:grid-cols-[100px_minmax(0,1fr)]">
            <dt className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              version
            </dt>
            <dd className="[font-family:var(--font-mono)] text-[var(--theme-text)]">
              {selectedPack.version}
            </dd>
            <dt className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              pack id
            </dt>
            <dd className="min-w-0 break-all [font-family:var(--font-mono)] text-[var(--theme-text)]">
              {selectedPack.packId}
            </dd>
            <dt className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              pack set
            </dt>
            <dd className="min-w-0 break-words text-[var(--theme-text)]">
              {selectedEntry.packSetLabels.join(", ")}
            </dd>
            <dt className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              agents
            </dt>
            <dd className="min-w-0 break-words text-[var(--theme-text)]">
              {selectedEntry.agents.join(", ")}
            </dd>
            <dt className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              used by
            </dt>
            <dd className="min-w-0 break-words text-[var(--theme-text)]">
              {selectedEntry.runLabels.join(", ")}
            </dd>
          </dl>
        </div>
      </div>
    </div>
  );
}

function PackSetSummary({
  onSelectPack,
  run,
  selectedPackKey,
}: {
  onSelectPack: (packKey: string) => void;
  run: ForecastRunEntry;
  selectedPackKey: string | null;
}) {
  const packSet = run.packSet;
  if (!packSet) {
    return (
      <span className="[font-family:var(--font-mono)] text-[0.66rem] text-[var(--theme-text-dim)]">
        unreported
      </span>
    );
  }
  if (packSet.packs.length === 0) {
    return (
      <span className="inline-flex rounded-full border border-[var(--theme-border)] px-2 py-[2px] [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
        {packSet.label}
      </span>
    );
  }

  return (
    <div>
      <div className="mb-2 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.08em] text-[var(--theme-text)]">
        {packSet.label}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {packSet.packs.map((pack) => {
          const key = buildPackKey(pack);
          const isSelected = key === selectedPackKey;
          return (
            <button
              aria-pressed={isSelected}
              className={`inline-flex rounded-full border px-2 py-[2px] [font-family:var(--font-mono)] text-[0.56rem] uppercase tracking-[0.06em] transition-colors ${
                isSelected
                  ? "border-[var(--color-accent)] bg-[var(--color-horizon-100)] text-[var(--theme-text)]"
                  : "border-[var(--color-horizon-300)] bg-[var(--color-horizon-50)] text-[var(--color-horizon-700)] hover:border-[var(--color-accent)]"
              }`}
              data-pack-key={key}
              key={key}
              onClick={() => onSelectPack(key)}
              title={pack.summary}
              type="button"
            >
              {pack.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function buildUniquePacks(runs: ForecastRunEntry[]): PackVisualizerEntry[] {
  const entries = new Map<
    string,
    {
      pack: PredictionPackReference;
      agents: Set<string>;
      packSetLabels: Set<string>;
      runLabels: Set<string>;
    }
  >();

  for (const run of runs) {
    for (const pack of run.packSet?.packs ?? []) {
      const key = buildPackKey(pack);
      const entry = entries.get(key) ?? {
        pack,
        agents: new Set<string>(),
        packSetLabels: new Set<string>(),
        runLabels: new Set<string>(),
      };
      entry.agents.add(getRunAgentLabel(run));
      if (run.packSet?.label) entry.packSetLabels.add(run.packSet.label);
      entry.runLabels.add(run.label);
      entries.set(key, entry);
    }
  }

  return [...entries.entries()].map(([key, entry]) => ({
    key,
    pack: entry.pack,
    agents: [...entry.agents],
    packSetLabels: [...entry.packSetLabels],
    runLabels: [...entry.runLabels],
  }));
}

function buildPackKey(pack: PredictionPackReference) {
  return `${pack.packId}@${pack.version}`;
}

function formatSignedValue(value: number, unit: ForecastCell["unit"]): string {
  const formatted = formatValue(Math.abs(value), unit).replace(/^\+/, "");
  if (value === 0) return formatted;
  return `${value > 0 ? "+" : "-"}${formatted}`;
}

function formatCompactNumber(value: number): string {
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(1);
  if (Math.abs(value) >= 1) return value.toFixed(2);
  return value.toPrecision(2);
}

function TraceStatusBanner({
  forecast,
  savedForecast,
}: {
  forecast: ForecastCell;
  savedForecast?: SavedForecastRun | null;
}) {
  const status = savedForecast
    ? {
        label: "Saved forecast",
        recorded: true,
        body: "The estimate and explanation come from the same completed run. Playback does not change the forecast.",
      }
    : forecast.predictionRun
      ? {
          label: "Recorded agent run",
          recorded: true,
          body: "The reasoning below was generated by an agent using official source context and saved in Thesis Log as this prediction's trace.",
        }
      : {
          label: "Static prototype",
          recorded: false,
          body: "No completed API result is available in this build. The estimate and explanation below are the saved prototype example.",
        };

  return (
    <div
      className="mb-3 rounded-md border bg-[var(--theme-bg-surface)] px-4 py-3 text-[0.78rem] leading-[1.5]"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <span
        className={`mr-2 inline-block rounded-full border px-2 py-[1px] [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] ${
          status.recorded
            ? "border-[var(--color-horizon-300)] bg-[var(--color-horizon-50)] text-[var(--color-horizon-700)]"
            : "border-[var(--theme-border)] bg-[var(--theme-bg-elevated)] text-[var(--theme-text-dim)]"
        }`}
      >
        {status.label}
      </span>
      <span className="text-[var(--theme-text-muted)]">{status.body}</span>
    </div>
  );
}

function SeriesMetadataPanel({ forecast }: { forecast: ForecastCell }) {
  const series = forecast.series;
  if (!series) return null;

  return (
    <div
      className="mt-6 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <h2 className="mb-4 [font-family:var(--font-display)] text-[0.95rem] font-semibold tracking-[-0.01em]">
        Series design
      </h2>
      <dl className="grid grid-cols-1 gap-x-5 gap-y-3 [font-family:var(--font-body)] text-[0.86rem] sm:grid-cols-[120px_minmax(0,1fr)]">
        <dt className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          series
        </dt>
        <dd className="min-w-0 break-all [font-family:var(--font-mono)] text-[0.78rem] leading-[1.55] text-[var(--color-horizon-700)]">
          {series.seriesId}
        </dd>
        <dt className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          cadence
        </dt>
        <dd className="min-w-0 break-words text-[var(--theme-text)]">
          {series.cadence} · {series.resolutionLatency}
        </dd>
        <dt className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          horizon
        </dt>
        <dd className="min-w-0 break-words text-[var(--theme-text)]">
          {series.horizonLabel} · {series.resolutionPolicy.replace("_", " ")}
        </dd>
        <dt className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          priority
        </dt>
        <dd className="min-w-0 break-words text-[var(--theme-text)]">
          {series.priority}
        </dd>
        {series.benchmark && (
          <>
            <dt className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              benchmark
            </dt>
            <dd className="min-w-0 break-words text-[var(--theme-text)]">
              {series.benchmark}
            </dd>
          </>
        )}
        <dt className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          chainable
        </dt>
        <dd className="min-w-0 break-words text-[var(--theme-text)]">
          {series.chainableQuestions.join(" · ")}
        </dd>
        {forecast.predictionRun && (
          <>
            <dt className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              run
            </dt>
            <dd className="min-w-0 break-words text-[var(--theme-text)]">
              {forecast.predictionRun.agent} · {forecast.predictionRun.model} ·{" "}
              {formatFullDate(forecast.predictionRun.runAt)}
            </dd>
          </>
        )}
      </dl>
    </div>
  );
}

// Read the calendar date written in an ISO string (the Y/M/D before any time
// zone offset) and rebuild it as a UTC instant. Formatting that as UTC shows
// the date exactly as recorded, identically on the server and the client —
// avoiding the timezone drift (e.g. a 22:15 ET run showing as the next day in
// UTC) and the hydration mismatch that `new Date(iso).toLocaleDateString()`
// without a timeZone produces. Also keeps date-only inputs (e.g. resolution
// dates like "2035-09-15") from shifting a day.
function isoCalendarDate(iso: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return null;
  return new Date(
    Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])),
  );
}

function formatFullDate(iso: string): string {
  const d = isoCalendarDate(iso);
  if (!d) return iso;
  return d.toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function formatShortFullDate(iso: string): string {
  const d = isoCalendarDate(iso);
  if (!d) return iso;
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function targetPeriodLabel(cell: ForecastCell): string {
  // Label the forecast by the PERIOD it grades, not the date it resolves:
  // a fiscal-year cell reads "FY 2025", never the June-after publication
  // month. Monthly and weekly cells keep the resolution-date fallback.
  const schoolYear = /sy[_ -]?(\d{4})[_-](\d{2})/i.exec(cell.dataPointId ?? "");
  if (schoolYear) return `SY ${schoolYear[1]}-${schoolYear[2]}`;
  const fiscalYear = /fy[_ -]?(\d{4})/i.exec(cell.dataPointId ?? "");
  if (fiscalYear) return `FY ${fiscalYear[1]}`;
  return formatShortDate(
    cell.resolvedOutcome?.resolvedAt ?? cell.resolutionDate,
  );
}

function formatShortDate(iso: string): string {
  const d = isoCalendarDate(iso);
  if (!d) return iso;
  return d.toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}
