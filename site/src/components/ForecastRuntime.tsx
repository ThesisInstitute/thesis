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
} from "@/data/forecast-display";
import type { ResolvedForecastScore } from "@/data/thesis-log";
import { prepareReportContent } from "@/lib/report-content";
import { canPlotReportHistory } from "@/lib/report-history";

interface ForecastRuntimeProps {
  forecast: ForecastCell;
  resolvedScore?: ResolvedForecastScore;
  runScores?: Record<string, ResolvedForecastScore>;
}

type ReportRun = ForecastRunEntry;

function reportRuns(forecast: ForecastCell): ReportRun[] {
  return getForecastRunEntries(forecast)
    .filter((run) => classifyTraceProvenance(run) === "activity_backed")
    .map((run) => ({
      ...run,
      label: run.label === "Headline" ? "Original forecast" : run.label,
    }));
}

function runTime(run: ReportRun) {
  return run.predictionRun?.runAt;
}

function runMethod(run: ReportRun) {
  return run.predictionRun?.model;
}

function isReconstructedBaseline(run: ReportRun) {
  return (
    run.variantId === "time-series-prior" &&
    run.predictionRun?.model === "persistence.last_print"
  );
}

export function ForecastRuntime({
  forecast: forecastCell,
  resolvedScore,
  runScores,
}: ForecastRuntimeProps) {
  const runs = reportRuns(forecastCell);
  const [selection, setSelection] = useState({
    slug: forecastCell.slug,
    id: runs[0]?.variantId ?? "",
  });
  const selected =
    (selection.slug === forecastCell.slug &&
      runs.find((run) => run.variantId === selection.id)) ||
    runs[0];
  const selectRun = (id: string) =>
    setSelection({ slug: forecastCell.slug, id });
  if (!selected) return <p>No forecast available.</p>;
  const history = canPlotReportHistory(selected.historicalContext ?? [])
    ? selected.historicalContext!
    : [];
  const report = prepareReportContent(selected.reasoning);
  const selectedForecast: ForecastCell = {
    ...forecastCell,
    pointEstimate: selected.pointEstimate,
    ciLow: selected.ciLow,
    ciHigh: selected.ciHigh,
    confidence: selected.confidence,
    drivers: selected.drivers,
    reasoning: selected.reasoning,
    predictionRun: selected.predictionRun,
    predictionDistribution: selected.predictionDistribution,
    historicalContext: history,
    comparisonRuns: undefined,
  };
  const score =
    runScores?.[selected.variantId] ??
    (selected.isPrimary ? resolvedScore : undefined);
  const generatedAt = runTime(selected);
  const manifest = selected.predictionRun?.activityLog?.find(
    (artifact) => artifact.artifactType === "manifest",
  );
  const normalizedArtifact = selected.predictionRun?.activityLog?.find(
    (artifact) => artifact.artifactType === "normalized_cell",
  );
  // The publication gate also verifies manifests committed through custody
  // roots; those modern manifests may not be repeated in the artifact list.
  const manifestPath =
    manifest?.path ??
    normalizedArtifact?.path.replace(/\/[^/]+$/, "/manifest.json");
  const sourceHref = manifestPath
    ? `https://github.com/ThesisInstitute/thesis/blob/main/${manifestPath}`
    : "/log";
  const catalogRuns = runs;
  const pointProjection = isPointProjection(selected, forecastCell.unit);

  return (
    <div className="space-y-12">
      <section
        aria-label="Forecast estimate"
        className="border-y border-[var(--theme-border)] py-7"
      >
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div>
            <p className="mb-2 text-sm text-[var(--theme-text-muted)]">
              Forecast
            </p>
            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-3">
              <span className="[font-family:var(--font-display)] text-[clamp(2.75rem,7vw,4.5rem)] leading-none tracking-[-0.035em] text-[var(--color-accent)]">
                {formatValue(selected.pointEstimate, forecastCell.unit)}
              </span>
              {pointProjection ? (
                <p className="text-sm text-[var(--theme-text-muted)]">
                  Point projection
                </p>
              ) : (
                <div className="text-[var(--theme-text)]">
                  <div className="text-lg tabular-nums">
                    {formatValue(selected.ciLow, forecastCell.unit)}–
                    {formatValue(selected.ciHigh, forecastCell.unit)}
                  </div>
                  <div className="mt-1 text-sm text-[var(--theme-text-muted)]">
                    80% prediction interval
                  </div>
                </div>
              )}
            </div>
          </div>
          {runs.length > 1 && (
            <label className="flex max-w-full flex-col gap-2 text-sm text-[var(--theme-text-muted)]">
              Forecast version
              <select
                aria-label="Forecast version"
                className="max-w-full rounded-md border border-[var(--theme-border-strong)] bg-[var(--theme-bg)] px-3 py-2 text-sm text-[var(--theme-text)] sm:max-w-[300px]"
                value={selected.variantId}
                onChange={(event) => selectRun(event.target.value)}
              >
                {runs.map((run) => (
                  <option key={run.variantId} value={run.variantId}>
                    {run.label}
                    {runTime(run)
                      ? ` · ${formatShortFullDate(runTime(run)!)}`
                      : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-sm text-[var(--theme-text-muted)]">
          <span>{runMethod(selected)}</span>
          {generatedAt && (
            <time dateTime={generatedAt}>
              {formatRecordedTime(generatedAt)}
            </time>
          )}
          <a
            className="text-[var(--color-accent)] hover:underline"
            href={sourceHref}
          >
            {manifestPath ? "Run record" : "Thesis Log"} ↗
          </a>
        </div>
        {report.modelUnavailable && (
          <p
            role="note"
            className="mt-5 border-l-2 border-[#B17B39] pl-3 text-sm leading-relaxed text-[var(--theme-text)]"
          >
            A model request failed during this run. See run details for the
            original diagnostic.
          </p>
        )}
        {(!pointProjection || history.length > 0) && (
          <div className="mt-8" aria-label="Forecast chart">
            {history.length > 0 ? (
              <ForecastTrend
                point={selected.pointEstimate}
                ciLow={selected.ciLow}
                ciHigh={selected.ciHigh}
                unit={forecastCell.unit}
                history={history}
                targetLabel={targetPeriodLabel(forecastCell)}
                showInterval={!pointProjection}
                actual={
                  forecastCell.resolvedOutcome
                    ? {
                        label: "actual",
                        value: forecastCell.resolvedOutcome.value,
                      }
                    : undefined
                }
              />
            ) : (
              <ForecastViz
                point={selected.pointEstimate}
                ciLow={selected.ciLow}
                ciHigh={selected.ciHigh}
                unit={forecastCell.unit}
                distribution={selected.predictionDistribution}
              />
            )}
          </div>
        )}
        {!pointProjection && history.length > 0 && (
          <details className="mt-5 border-t border-[var(--theme-border)] pt-4">
            <summary className="cursor-pointer text-sm text-[var(--theme-text-muted)]">
              Probability distribution
            </summary>
            <div className="mt-5">
              <ForecastViz
                point={selected.pointEstimate}
                ciLow={selected.ciLow}
                ciHigh={selected.ciHigh}
                unit={forecastCell.unit}
                distribution={selected.predictionDistribution}
              />
            </div>
          </details>
        )}
        {forecastCell.resolvedOutcome && (
          <ResolvedOutcomePanel forecast={selectedForecast} score={score} />
        )}
      </section>

      <section aria-labelledby="analysis-heading" className="max-w-[75ch]">
        <h2
          id="analysis-heading"
          className="mb-5 [font-family:var(--font-display)] text-2xl font-semibold"
        >
          Analysis
        </h2>
        <AgentReasoning
          steps={report.steps.filter((step) => step.kind !== "forecast")}
          unit={forecastCell.unit}
          provenance={classifyTraceProvenance(selected)}
          reconstructedBaseline={isReconstructedBaseline(selected)}
        />
        {selected.drivers.length > 0 && (
          <div className="mt-8">
            <h3 className="mb-3 [font-family:var(--font-display)] text-lg font-semibold">
              Key drivers
            </h3>
            <ul className="list-disc space-y-2 pl-5 text-[0.94rem] leading-relaxed text-[var(--theme-text)]">
              {selected.drivers.map((driver) => (
                <li key={driver}>{driver}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section
        aria-labelledby="evidence-heading"
        className="border-t border-[var(--theme-border)] pt-7"
      >
        <h2
          id="evidence-heading"
          className="mb-5 [font-family:var(--font-display)] text-2xl font-semibold"
        >
          Sources and resolution
        </h2>
        <dl className="grid gap-x-6 gap-y-3 text-[0.94rem] leading-relaxed sm:grid-cols-[150px_minmax(0,1fr)]">
          <dt className="text-[var(--theme-text-muted)]">Official source</dt>
          <dd>
            {forecastCell.resolutionSourceUrl ? (
              <a
                className="text-[var(--color-accent)] hover:underline"
                href={forecastCell.resolutionSourceUrl}
              >
                {forecastCell.resolutionSource}
              </a>
            ) : (
              forecastCell.resolutionSource
            )}
          </dd>
          <dt className="text-[var(--theme-text-muted)]">
            {forecastCell.resolvedOutcome ? "Resolved" : "Resolution date"}
          </dt>
          <dd>
            {formatFullDate(
              forecastCell.resolvedOutcome?.resolvedAt ??
                forecastCell.resolutionDate,
            )}
            {!forecastCell.resolvedOutcome && (
              <span className="ml-2 text-sm text-[var(--theme-text-muted)]">
                · outcome not recorded
              </span>
            )}
          </dd>
          <dt className="text-[var(--theme-text-muted)]">Resolution rule</dt>
          <dd>{forecastCell.resolutionRule}</dd>
        </dl>
      </section>

      <RunHistory
        runs={runs}
        selectedId={selected.variantId}
        onSelect={selectRun}
        unit={forecastCell.unit}
        runScores={runScores}
        primaryScore={resolvedScore}
      />

      <RunDetails
        key={selected.variantId}
        run={selected}
        diagnostics={report.diagnostics}
        unit={forecastCell.unit}
      />
      {catalogRuns.some((run) => run.packSet?.packs.length) && (
        <PackDetails runs={catalogRuns} />
      )}
      {(forecastCell.series ||
        forecastCell.dataPointId ||
        forecastCell.policyParameter) && (
        <details className="border-t border-[var(--theme-border)] pt-5">
          <summary className="cursor-pointer text-sm text-[var(--theme-text-muted)]">
            Target metadata
          </summary>
          <div className="mt-4 space-y-3 text-sm text-[var(--theme-text-muted)]">
            {forecastCell.dataPointId && (
              <p>
                Data point:{" "}
                <code className="break-all">{forecastCell.dataPointId}</code>
              </p>
            )}
            {forecastCell.policyParameter && (
              <p>
                Policy parameter:{" "}
                <code className="break-all">
                  {forecastCell.policyParameter}
                </code>
              </p>
            )}
            {forecastCell.series && (
              <SeriesMetadataPanel forecast={selectedForecast} />
            )}
          </div>
        </details>
      )}
    </div>
  );
}

function isPointProjection(
  run: Pick<ReportRun, "ciLow" | "ciHigh">,
  unit: ForecastCell["unit"],
) {
  return formatValue(run.ciLow, unit) === formatValue(run.ciHigh, unit);
}

function RunHistory({
  runs,
  selectedId,
  onSelect,
  unit,
  runScores,
  primaryScore,
}: {
  runs: ReportRun[];
  selectedId: string;
  onSelect: (id: string) => void;
  unit: ForecastCell["unit"];
  runScores?: Record<string, ResolvedForecastScore>;
  primaryScore?: ResolvedForecastScore;
}) {
  if (runs.length <= 1) return null;
  const ordered = [...runs].sort(
    (a, b) =>
      (Date.parse(runTime(b) ?? "") || 0) - (Date.parse(runTime(a) ?? "") || 0),
  );
  const hasScores = ordered.some(
    (run) => runScores?.[run.variantId] || (run.isPrimary && primaryScore),
  );
  return (
    <section
      aria-labelledby="history-heading"
      className="border-t border-[var(--theme-border)] pt-7"
    >
      <h2
        id="history-heading"
        className="mb-2 [font-family:var(--font-display)] text-2xl font-semibold"
      >
        Forecast history
      </h2>
      <p className="mb-5 text-sm text-[var(--theme-text-muted)]">
        Select a version to read its estimate and analysis.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">
            Forecast versions, estimates, and intervals
          </caption>
          <thead className="border-b border-[var(--theme-border-strong)] text-[var(--theme-text-muted)]">
            <tr>
              <th scope="col" className="py-3 pr-4 font-normal">
                Version
              </th>
              <th scope="col" className="px-3 py-3 font-normal">
                Date
              </th>
              <th scope="col" className="px-3 py-3 font-normal">
                Estimate
              </th>
              <th scope="col" className="py-3 pl-3 font-normal">
                80% interval
              </th>
              {hasScores && (
                <th scope="col" className="py-3 pl-3 font-normal">
                  CRPS
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {ordered.map((run) => {
              const selected = run.variantId === selectedId;
              const score =
                runScores?.[run.variantId] ??
                (run.isPrimary ? primaryScore : undefined);
              return (
                <tr
                  key={run.variantId}
                  data-forecast-run={run.variantId}
                  className={`border-b border-[var(--theme-border)] ${selected ? "bg-[var(--theme-bg-surface)]" : ""}`}
                >
                  <th scope="row" className="py-4 pr-4 font-normal">
                    <button
                      type="button"
                      aria-pressed={selected}
                      onClick={() => onSelect(run.variantId)}
                      className="text-left font-medium text-[var(--color-accent)] hover:underline"
                    >
                      {run.label}
                    </button>
                    <span className="mt-1 block text-xs text-[var(--theme-text-muted)]">
                      {runMethod(run)}
                      {selected ? " · selected" : ""}
                    </span>
                  </th>
                  <td className="whitespace-nowrap px-3 py-4 text-[var(--theme-text-muted)]">
                    {runTime(run)
                      ? formatShortFullDate(runTime(run)!)
                      : "Undated"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-4 font-medium tabular-nums">
                    {formatValue(run.pointEstimate, unit)}
                  </td>
                  <td className="whitespace-nowrap py-4 pl-3 tabular-nums text-[var(--theme-text-muted)]">
                    {isPointProjection(run, unit)
                      ? "Point projection"
                      : `${formatValue(run.ciLow, unit)}–${formatValue(run.ciHigh, unit)}`}
                  </td>
                  {hasScores && (
                    <td className="py-4 pl-3 tabular-nums">
                      {score ? formatCompactNumber(score.crps) : "—"}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RunDetails({
  run,
  diagnostics,
  unit,
}: {
  run: ReportRun;
  diagnostics: string[];
  unit: ForecastCell["unit"];
}) {
  const metadata = run.predictionRun;
  return (
    <details
      id="run-details"
      className="border-t border-[var(--theme-border)] pt-5"
    >
      <summary className="cursor-pointer text-sm text-[var(--theme-text-muted)]">
        Run details{diagnostics.length ? " and diagnostics" : ""}
      </summary>
      <div className="mt-5 space-y-5 text-sm leading-relaxed">
        <p>
          {isReconstructedBaseline(run)
            ? "This baseline is reconstructed from pre-cutoff ledger observations. It is a comparison calculation, not an AI forecast."
            : "The analysis is the model’s written report. Tool-use descriptions in that report are model claims; the activity artifacts contain the execution record."}
        </p>
        {run.description && <p>{run.description}</p>}
        {metadata && (
          <p>
            {metadata.agent} · {metadata.model}
            {metadata.promptMode ? ` · ${metadata.promptMode}` : ""}
            {metadata.agentVersion ? ` · v${metadata.agentVersion}` : ""}
          </p>
        )}
        {run.externalSubmission && (
          <p>
            External submission by {run.externalSubmission.challenger};
            self-declared {run.externalSubmission.systemType}. A reasoning trace
            is not required.
          </p>
        )}
        {run.packSet && (
          <p>
            Pack set: {run.packSet.label} · {run.packSet.mode}
          </p>
        )}
        {diagnostics.length > 0 && (
          <div>
            <h3 className="mb-3 font-medium">Original diagnostics</h3>
            {diagnostics.map((text, index) => (
              <pre
                key={index}
                className="my-3 whitespace-pre-wrap break-words rounded-md bg-[var(--theme-bg-surface)] p-4 text-xs"
              >
                <code>{text}</code>
              </pre>
            ))}
          </div>
        )}
        {metadata?.preSubmitReview && (
          <PreSubmitReviewTrace review={metadata.preSubmitReview} />
        )}
        {Boolean(metadata?.activityLog?.length) && (
          <div>
            <h3 className="mb-3 font-medium">Activity artifacts</h3>
            <ul className="space-y-2">
              {metadata!.activityLog!.map((artifact) => (
                <li key={artifact.path}>
                  <a
                    className="break-all text-[var(--color-accent)] hover:underline"
                    href={`https://github.com/ThesisInstitute/thesis/blob/main/${artifact.path}`}
                  >
                    {artifact.artifactType}: {artifact.path}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
        <details>
          <summary className="cursor-pointer text-[var(--theme-text-muted)]">
            Complete original trace
          </summary>
          <div className="mt-5">
            <AgentReasoning
              steps={run.reasoning}
              unit={unit}
              provenance={classifyTraceProvenance(run)}
              reconstructedBaseline={isReconstructedBaseline(run)}
            />
          </div>
        </details>
      </div>
    </details>
  );
}

function PackDetails({ runs }: { runs: ForecastRunEntry[] }) {
  const packs = buildUniquePacks(runs);
  const [selection, setSelection] = useState(packs[0]?.key ?? "");
  if (!packs.length) return null;
  return (
    <details className="border-t border-[var(--theme-border)] pt-5">
      <summary className="cursor-pointer text-sm text-[var(--theme-text-muted)]">
        Forecasting packs
      </summary>
      <div className="mt-5">
        <PackVisualizer
          packs={packs}
          selectedPackKey={selection}
          onSelectPack={setSelection}
        />
      </div>
    </details>
  );
}

function ResolvedOutcomePanel({
  forecast,
  score,
}: {
  forecast: ForecastCell;
  score?: ResolvedForecastScore;
}) {
  const outcome = forecast.resolvedOutcome;
  if (!outcome) return null;
  const result = getResolutionResult(forecast);
  const pointProjection = isPointProjection(forecast, forecast.unit);
  const resultLabel =
    result === "inside" ? "inside 80% interval" : "outside 80% interval";

  return (
    <div
      className="mt-7 border-t pt-5"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <span className="[font-family:var(--font-display)] text-lg font-semibold">
          Observed outcome
        </span>
        {!pointProjection && (
          <span
            className={`rounded-full border px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em] ${
              result === "inside"
                ? "border-[var(--color-horizon-300)] bg-[var(--color-horizon-50)] text-[var(--color-horizon-700)]"
                : "border-[#F2DCAF] bg-[#FFF4DD] text-[#7A5C20]"
            }`}
          >
            {resultLabel}
          </span>
        )}
      </div>
      <dl className="grid grid-cols-1 gap-x-5 gap-y-2 [font-family:var(--font-body)] text-[0.84rem] sm:grid-cols-[120px_minmax(0,1fr)]">
        <dt className="text-sm text-[var(--theme-text-muted)]">actual</dt>
        <dd className="text-[var(--theme-text)]">
          {formatValue(outcome.value, forecast.unit)}
        </dd>
        <dt className="text-sm text-[var(--theme-text-muted)]">forecast</dt>
        <dd className="text-[var(--theme-text)]">
          {formatValue(forecast.pointEstimate, forecast.unit)}
          {pointProjection
            ? " · point projection"
            : ` with 80% interval [${formatValue(forecast.ciLow, forecast.unit)}, ${formatValue(forecast.ciHigh, forecast.unit)}]`}
        </dd>
        {score && (
          <>
            <dt className="text-sm text-[var(--theme-text-muted)]">error</dt>
            <dd className="text-[var(--theme-text)]">
              {formatSignedValue(score.signedError, forecast.unit)} · absolute{" "}
              {formatValue(score.absoluteError, forecast.unit)}
            </dd>
            <dt className="text-sm text-[var(--theme-text-muted)]">
              cdf score
            </dt>
            <dd className="text-[var(--theme-text)]">
              CRPS {formatCompactNumber(score.crps)} · PIT{" "}
              {formatCompactNumber(score.probabilityIntegralTransform)}
            </dd>
          </>
        )}
        <dt className="text-sm text-[var(--theme-text-muted)]">source</dt>
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
          {review.findings.map((finding) => (
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
          {review.dispositions.map((disposition) => (
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

function getRunAgentLabel(run: ForecastRunEntry) {
  return run.predictionRun?.agent ?? "prototype seed";
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
  const calendarYear = /\.(\d{4})$/.exec(cell.dataPointId ?? "");
  if (calendarYear) return calendarYear[1];
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
