import { canonicalStringify, sha256Hex } from "./canonical-json";
import {
  buildNumericCdfFromInterval,
  validateNumericCdfDistribution,
  type PredictionDistribution,
} from "./prediction-distribution";
import type {
  ForecastCell,
  ForecastComparisonRun,
  ForecastRunEntry,
  LedgerObservationReference,
  PersistenceBaselineRecord,
  Unit,
} from "./forecast-cells";
import type {
  ObservationRecordedLedgerEntry,
  PolicyEngineLedgerEntry,
} from "./thesis-log";
import type { TargetRegisteredLedgerEntry } from "./ledger-targets";

export const TIME_SERIES_PRIOR_VARIANT_ID = "time-series-prior";
export const PERSISTENCE_BASELINE_AGENT = "brier.time_series_prior";
export const PERSISTENCE_BASELINE_ALGORITHM_VERSION =
  "ledger_last_print_realized_change_p80_v1";

export interface TimeSeriesPriorAdjustmentRow {
  forecastSlug: string;
  title: string;
  dataPointId?: string;
  unit: Unit;
  priorLabel: string;
  priorModel: string;
  historyPoints: number;
  latestHistoricalLabel: string;
  latestHistoricalValue: number;
  priorPointEstimate: number;
  priorCiLow: number;
  priorCiHigh: number;
  priorIntervalWidth: number;
  agentPointEstimate: number;
  agentCiLow: number;
  agentCiHigh: number;
  adjustment: number;
  absoluteAdjustment: number;
  relativeAdjustment: number | null;
  adjustmentShareOfPriorInterval: number | null;
  direction: "up" | "down" | "flat";
}

export interface TimeSeriesPriorAdjustmentReport {
  schemaVersion: "time_series_prior_adjustment_report_v1";
  rows: TimeSeriesPriorAdjustmentRow[];
  counts: {
    forecastsWithPrior: number;
    adjustedUp: number;
    adjustedDown: number;
    flat: number;
  };
  summary: {
    meanAdjustment: number | null;
    meanAbsoluteAdjustment: number | null;
    medianAbsoluteAdjustment: number | null;
    meanAbsoluteShareOfPriorInterval: number | null;
    medianAbsoluteShareOfPriorInterval: number | null;
  };
  largestAbsoluteAdjustments: TimeSeriesPriorAdjustmentRow[];
  largestPriorIntervalShareAdjustments: TimeSeriesPriorAdjustmentRow[];
}

interface PriorInterval {
  pointEstimate: number;
  ciLow: number;
  ciHigh: number;
  historyPoints: number;
  latest: LedgerObservationReference;
  observations: LedgerObservationReference[];
  seriesId: string;
  intervalMethod: "ledger_realized_step_change_p80";
}

export function buildTimeSeriesPriorComparisonRun(
  forecast: ForecastCell,
  ledger: PolicyEngineLedgerEntry[],
): ForecastComparisonRun | null {
  return buildLedgerPersistenceBaseline(forecast, ledger).comparisonRun;
}

export interface LedgerPersistenceBaselineResult {
  record: PersistenceBaselineRecord;
  comparisonRun: ForecastComparisonRun | null;
}

export function buildLedgerPersistenceBaseline(
  forecast: ForecastCell,
  ledger: PolicyEngineLedgerEntry[],
): LedgerPersistenceBaselineResult {
  const cutoff = forecast.predictionRun?.runAt;
  const unavailable = (
    reason: string,
    observationRefs: LedgerObservationReference[] = [],
    seriesId?: string,
  ): LedgerPersistenceBaselineResult => ({
    record: {
      status: "unavailable",
      variantId: TIME_SERIES_PRIOR_VARIANT_ID,
      cutoff: cutoff ?? "",
      targetDataPointId: forecast.dataPointId,
      seriesId,
      observationRefs,
      reason,
    },
    comparisonRun: null,
  });

  if (!cutoff || !forecast.dataPointId) {
    return unavailable("missing recordedAt cutoff or target dataPointId");
  }

  const prior = buildLastPrintPriorInterval(forecast, ledger, cutoff);
  if (!prior) {
    const candidates = ledgerHistoryAtCutoff(forecast, ledger, cutoff);
    return unavailable(
      candidates.length === 0
        ? "ledger has no pre-cutoff observations for the target series"
        : "ledger has fewer than two pre-cutoff observations, so realized volatility is unavailable",
      candidates.map(toObservationReference),
      candidates[0]
        ? (registeredObservationSeriesIdentity(candidates[0], ledger) ??
            undefined)
        : undefined,
    );
  }

  const distribution = buildNumericCdfFromInterval({
    pointEstimate: prior.pointEstimate,
    ciLow: prior.ciLow,
    ciHigh: prior.ciHigh,
  });
  // A flat history makes the p80 half-width zero; the interval transform
  // then spans +/-1.5e-9, and from |value| >= 10 the 201-point grid
  // collapses under 12-significant-digit rounding, so the CDF fails the
  // scorer's own contract and scoring would throw mid-build. A baseline
  // the scorer cannot read is unavailable, with the validator's reasons.
  const distributionErrors = validateNumericCdfDistribution(distribution);
  if (distributionErrors.length > 0) {
    return unavailable(
      `persistence interval [${prior.ciLow}, ${prior.ciHigh}] is too narrow to materialize as a valid CDF: ${distributionErrors.join("; ")}`,
      prior.observations,
      prior.seriesId,
    );
  }
  const inputPayload = {
    schemaVersion: "thesis_persistence_baseline_inputs_v1",
    algorithmVersion: PERSISTENCE_BASELINE_ALGORITHM_VERSION,
    targetDataPointId: forecast.dataPointId,
    seriesId: prior.seriesId,
    cutoff,
    observations: prior.observations,
  };
  const inputDigest = sha256Hex(inputPayload);
  const inputBytes = new TextEncoder().encode(
    canonicalStringify(inputPayload),
  ).byteLength;
  const sourceContext = ledgerHistoryAtCutoff(forecast, ledger, cutoff)
    .map((entry) => entry.sourceUrl)
    .filter((url): url is string => Boolean(url));

  const comparisonRun: ForecastComparisonRun = {
    variantId: TIME_SERIES_PRIOR_VARIANT_ID,
    label: "Ledger persistence baseline",
    description:
      "Last official ledger print at the primary run cutoff, with an interval derived only from realized same-series ledger changes.",
    pointEstimate: prior.pointEstimate,
    ciLow: prior.ciLow,
    ciHigh: prior.ciHigh,
    confidence: forecast.confidence,
    drivers: [
      "Latest official historical value",
      "Ledger-archived realized one-step changes",
      "No target-specific agent judgment",
    ],
    predictionRun: {
      kind: "recorded-agent-run",
      runAt: cutoff,
      agent: PERSISTENCE_BASELINE_AGENT,
      model: "persistence.last_print",
      sourceContext: [...new Set(sourceContext)],
      runLabel: "Ledger persistence baseline",
      runDescription:
        "Deterministic last-print baseline generated exclusively from observations archived in the PolicyEngine Ledger before the primary run cutoff.",
      inputBundleHash: inputDigest,
      activityLog: [
        {
          artifactType: "baseline_inputs",
          path: `ledger://persistence-baselines/${inputDigest}.json`,
          sha256: inputDigest,
          bytes: inputBytes,
          createdAt: cutoff,
          observationRefs: prior.observations,
        },
      ],
    },
    predictionDistribution: distribution,
    reasoning: buildPriorReasoning(forecast, prior),
  };

  return {
    record: {
      status: "available",
      variantId: TIME_SERIES_PRIOR_VARIANT_ID,
      cutoff,
      targetDataPointId: forecast.dataPointId,
      seriesId: prior.seriesId,
      observationRefs: prior.observations,
    },
    comparisonRun,
  };
}

export function buildTimeSeriesPriorAdjustmentReport(
  forecasts: ForecastCell[],
): TimeSeriesPriorAdjustmentReport {
  const rows = forecasts
    .flatMap((forecast) => buildPriorAdjustmentRow(forecast) ?? [])
    .sort(
      (left, right) =>
        right.absoluteAdjustment - left.absoluteAdjustment ||
        left.forecastSlug.localeCompare(right.forecastSlug),
    );
  const shareRows = rows
    .filter((row) => row.adjustmentShareOfPriorInterval !== null)
    .sort(
      (left, right) =>
        Math.abs(right.adjustmentShareOfPriorInterval ?? 0) -
          Math.abs(left.adjustmentShareOfPriorInterval ?? 0) ||
        left.forecastSlug.localeCompare(right.forecastSlug),
    );

  return {
    schemaVersion: "time_series_prior_adjustment_report_v1",
    rows,
    counts: {
      forecastsWithPrior: rows.length,
      adjustedUp: rows.filter((row) => row.direction === "up").length,
      adjustedDown: rows.filter((row) => row.direction === "down").length,
      flat: rows.filter((row) => row.direction === "flat").length,
    },
    summary: {
      meanAdjustment: meanOrNull(rows.map((row) => row.adjustment)),
      meanAbsoluteAdjustment: meanOrNull(
        rows.map((row) => row.absoluteAdjustment),
      ),
      medianAbsoluteAdjustment: quantileOrNull(
        rows.map((row) => row.absoluteAdjustment),
        0.5,
      ),
      meanAbsoluteShareOfPriorInterval: meanOrNull(
        rows
          .map((row) => row.adjustmentShareOfPriorInterval)
          .filter((value): value is number => value !== null)
          .map((value) => Math.abs(value)),
      ),
      medianAbsoluteShareOfPriorInterval: quantileOrNull(
        rows
          .map((row) => row.adjustmentShareOfPriorInterval)
          .filter((value): value is number => value !== null)
          .map((value) => Math.abs(value)),
        0.5,
      ),
    },
    largestAbsoluteAdjustments: rows.slice(0, 12),
    largestPriorIntervalShareAdjustments: shareRows.slice(0, 12),
  };
}

function buildPriorAdjustmentRow(
  forecast: ForecastCell,
): TimeSeriesPriorAdjustmentRow | null {
  const prior = forecast.comparisonRuns?.find(
    (run) => run.variantId === TIME_SERIES_PRIOR_VARIANT_ID,
  );
  if (!prior) return null;
  const latest = prior.predictionRun.activityLog
    ?.find((artifact) => artifact.artifactType === "baseline_inputs")
    ?.observationRefs?.at(-1);
  if (!latest) return null;

  return buildPriorAdjustmentRowFromRun({ forecast, prior, latest });
}

function buildPriorAdjustmentRowFromRun({
  forecast,
  prior,
  latest,
}: {
  forecast: ForecastCell;
  prior: ForecastComparisonRun | ForecastRunEntry;
  latest: LedgerObservationReference;
}): TimeSeriesPriorAdjustmentRow {
  const adjustment = roundComparable(
    forecast.pointEstimate - prior.pointEstimate,
  );
  const priorIntervalWidth = Math.abs(prior.ciHigh - prior.ciLow);
  const relativeAdjustment =
    Math.abs(prior.pointEstimate) > 1e-9
      ? adjustment / Math.abs(prior.pointEstimate)
      : null;
  const adjustmentShareOfPriorInterval =
    priorIntervalWidth > 1e-9 ? adjustment / priorIntervalWidth : null;

  return {
    forecastSlug: forecast.slug,
    title: forecast.title,
    dataPointId: forecast.dataPointId,
    unit: forecast.unit,
    priorLabel: prior.label,
    priorModel: prior.predictionRun?.model ?? "persistence.last_print",
    historyPoints:
      prior.predictionRun?.activityLog?.find(
        (artifact) => artifact.artifactType === "baseline_inputs",
      )?.observationRefs?.length ?? 0,
    latestHistoricalLabel: latest.periodLabel,
    latestHistoricalValue: latest.value,
    priorPointEstimate: prior.pointEstimate,
    priorCiLow: prior.ciLow,
    priorCiHigh: prior.ciHigh,
    priorIntervalWidth,
    agentPointEstimate: forecast.pointEstimate,
    agentCiLow: forecast.ciLow,
    agentCiHigh: forecast.ciHigh,
    adjustment,
    absoluteAdjustment: Math.abs(adjustment),
    relativeAdjustment,
    adjustmentShareOfPriorInterval,
    direction: classifyDirection(adjustment),
  };
}

function buildLastPrintPriorInterval(
  forecast: ForecastCell,
  ledger: PolicyEngineLedgerEntry[],
  cutoff: string,
): PriorInterval | null {
  if (!forecast.dataPointId) return null;
  const seriesId = registeredTargetSeriesIdentity(forecast.dataPointId, ledger);
  if (!seriesId) return null;
  const history = ledgerHistoryAtCutoff(forecast, ledger, cutoff);
  if (history.length < 2) return null;
  const latest = history.at(-1);
  if (!latest) return null;

  const observations = history.map(toObservationReference);
  const pointEstimate = latest.value;
  const diffs = buildStepChanges(observations);
  const halfWidth = quantile(
    diffs.map((diff) => Math.abs(diff)),
    0.8,
  );

  return {
    pointEstimate,
    ciLow: roundComparable(pointEstimate - halfWidth),
    ciHigh: roundComparable(pointEstimate + halfWidth),
    historyPoints: history.length,
    latest: toObservationReference(latest),
    observations,
    seriesId,
    intervalMethod: "ledger_realized_step_change_p80",
  };
}

function buildPriorReasoning(forecast: ForecastCell, prior: PriorInterval) {
  const formattedLatest = formatCompact(prior.latest.value, forecast.unit);
  const formattedPoint = formatCompact(prior.pointEstimate, forecast.unit);
  const formattedLow = formatCompact(prior.ciLow, forecast.unit);
  const formattedHigh = formatCompact(prior.ciHigh, forecast.unit);

  return [
    {
      kind: "heading" as const,
      text: "Time-series prior",
    },
    {
      kind: "tool" as const,
      tool: "brier.timeseries.prior",
      call: `brier.timeseries.prior({ target: "${forecast.dataPointId ?? forecast.slug}", model: "persistence.last_print" })`,
      result: `latest=${formattedLatest} (${prior.latest.periodLabel}); history_points=${prior.historyPoints}; interval_method=${prior.intervalMethod}; ledger_refs=${prior.observations.map((observation) => observation.dataPointId).join(",")}`,
    },
    {
      kind: "math" as const,
      text: `Prior point = latest observed value = ${formattedPoint}; 80% interval = [${formattedLow}, ${formattedHigh}].`,
    },
    {
      kind: "text" as const,
      text: "This run stops before target-specific agent updates; the primary forecast records the adjustment away from this prior.",
    },
    {
      kind: "forecast" as const,
      point: prior.pointEstimate,
      ciLow: prior.ciLow,
      ciHigh: prior.ciHigh,
    },
  ];
}

function buildStepChanges(history: LedgerObservationReference[]) {
  const diffs: number[] = [];
  for (let index = 1; index < history.length; index += 1) {
    diffs.push(history[index].value - history[index - 1].value);
  }
  return diffs;
}

export function ledgerHistoryAtCutoff(
  forecast: ForecastCell,
  ledger: PolicyEngineLedgerEntry[],
  cutoff: string,
): ObservationRecordedLedgerEntry[] {
  if (!forecast.dataPointId) return [];
  const registrations = registrationsByDataPointId(ledger);
  const targetSeriesId = contractSeries(
    registrations.get(forecast.dataPointId),
  );
  if (!targetSeriesId) return [];
  const cutoffTime = Date.parse(cutoff);
  if (!Number.isFinite(cutoffTime)) return [];

  // Eligibility requires BOTH the publisher's claimed date and the ledger's
  // own acceptance to precede the cutoff. A backfilled print carries an old
  // observedAt but a late acceptance; admitting it would silently rewrite
  // published baselines and normalization scales (finding N5). Rows without
  // an acceptance record fail closed.
  const observations = ledger.filter(
    (entry): entry is ObservationRecordedLedgerEntry =>
      entry.kind === "observation_recorded" &&
      entry.unit === forecast.unit &&
      observationSeriesFromRegistrations(entry, registrations) ===
        targetSeriesId &&
      Date.parse(entry.observedAt) <= cutoffTime &&
      typeof entry.acceptedAtUtc === "string" &&
      Date.parse(entry.acceptedAtUtc) <= cutoffTime,
  );
  const byObservationId = new Map(
    observations.map((observation) => [observation.observationId, observation]),
  );
  return [...byObservationId.values()].sort((left, right) => {
    const timeDelta =
      Date.parse(left.observedAt) - Date.parse(right.observedAt);
    return timeDelta || left.observationId.localeCompare(right.observationId);
  });
}

interface LegacyObservationSeriesIdentity {
  dataPointId: string;
  observationId: string;
  periodLabel: string;
  unit: Unit;
  value: number;
  acceptedSequence: number;
  acceptedCommit: string;
  acceptedAtUtc: string;
  observedAt: string;
  sourceUrl: string;
  legacyQuarantined: boolean;
  series: string;
}

// These five pinned observations predate contract-bound series projections,
// but are still needed to preserve the published claims normalization scales.
// Compatibility is exact and immutable: a suffix, value, period label, unit,
// registration, ledger sequence, or accepting commit change makes the row
// ineligible. New rows must carry a registered contract and matching
// sourceBindingProjection instead.
const REVIEWED_LEGACY_OBSERVATION_SERIES: readonly LegacyObservationSeriesIdentity[] =
  [
    {
      dataPointId: "us.dol.initial_claims.sa.week_2026-06-13",
      observationId: "obs.us.dol.initial_claims.sa.week_2026-06-13",
      periodLabel: "June 2026",
      unit: "thousands",
      value: 226,
      acceptedSequence: 43,
      acceptedCommit: "6c9209434048317c15355f42e019339efbd0d6ea",
      acceptedAtUtc: "2026-06-19T13:18:22Z",
      observedAt: "2026-06-18",
      sourceUrl: "https://www.dol.gov/ui/data.pdf",
      legacyQuarantined: true,
      series: "us.dol.initial_claims.sa",
    },
    {
      dataPointId: "us.dol.initial_claims.sa.week_2026-06-20",
      observationId: "obs.us.dol.initial_claims.sa.week_2026-06-20",
      periodLabel: "2026-06-20",
      unit: "thousands",
      value: 215,
      acceptedSequence: 104,
      acceptedCommit: "b67cbfcb5f08d07b856c3463858c765e6755a6f9",
      acceptedAtUtc: "2026-07-07T17:41:17Z",
      observedAt: "2026-06-25",
      sourceUrl:
        "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=ICSA&vintage_date=2026-06-25",
      legacyQuarantined: true,
      series: "us.dol.initial_claims.sa",
    },
    {
      dataPointId: "us.dol.initial_claims.sa.week_2026-07-04",
      observationId: "obs.us.dol.initial_claims.sa.week_2026-07-04",
      periodLabel: "2026-07-04",
      unit: "thousands",
      value: 215,
      acceptedSequence: 105,
      acceptedCommit: "ed97a5e2fa9036897d9dfdf1bae5c9727791ab87",
      acceptedAtUtc: "2026-07-09T16:15:28Z",
      observedAt: "2026-07-09",
      sourceUrl:
        "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=ICSA&vintage_date=2026-07-09",
      legacyQuarantined: true,
      series: "us.dol.initial_claims.sa",
    },
    {
      dataPointId: "dol.eta.continued_claims.sa.week_2026-06-27.first_print",
      observationId:
        "obs.dol.eta.continued_claims.sa.week_2026-06-27.first_print",
      periodLabel: "2026-06-27",
      unit: "millions",
      value: 1.814,
      acceptedSequence: 106,
      acceptedCommit: "ed97a5e2fa9036897d9dfdf1bae5c9727791ab87",
      acceptedAtUtc: "2026-07-09T16:15:28Z",
      observedAt: "2026-07-09",
      sourceUrl:
        "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=CCSA&vintage_date=2026-07-09",
      legacyQuarantined: true,
      series: "dol.eta.continued_claims.sa",
    },
    {
      dataPointId: "dol.eta.continued_claims.sa.week_2026-07-04.first_print",
      observationId:
        "obs.dol.eta.continued_claims.sa.week_2026-07-04.first_print",
      periodLabel: "2026-07-04",
      unit: "millions",
      value: 1.805,
      acceptedSequence: 144,
      acceptedCommit: "18a269223d27db111681e2e1af38a7c674c1da87",
      acceptedAtUtc: "2026-07-18T16:28:37Z",
      observedAt: "2026-07-16",
      sourceUrl:
        "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=CCSA&vintage_date=2026-07-16",
      legacyQuarantined: false,
      series: "dol.eta.continued_claims.sa",
    },
  ];

function registrationsByDataPointId(
  ledger: PolicyEngineLedgerEntry[],
): Map<string, TargetRegisteredLedgerEntry> {
  const registrations = new Map<string, TargetRegisteredLedgerEntry>();
  const ambiguous = new Set<string>();
  for (const entry of ledger) {
    if (entry.kind !== "target_registered") continue;
    if (registrations.has(entry.dataPointId)) {
      ambiguous.add(entry.dataPointId);
      continue;
    }
    registrations.set(entry.dataPointId, entry);
  }
  for (const dataPointId of ambiguous) registrations.delete(dataPointId);
  return registrations;
}

function contractSeries(
  target: TargetRegisteredLedgerEntry | undefined,
): string | null {
  return target?.targetContentHash &&
    target.sourceBinding &&
    typeof target.series === "string" &&
    target.series.length > 0 &&
    typeof target.period === "string" &&
    target.period.length > 0
    ? target.series
    : null;
}

export function registeredTargetSeriesIdentity(
  dataPointId: string,
  ledger: PolicyEngineLedgerEntry[],
): string | null {
  return contractSeries(registrationsByDataPointId(ledger).get(dataPointId));
}

function projectionMatchesRegistration(
  observation: ObservationRecordedLedgerEntry,
  target: TargetRegisteredLedgerEntry,
): boolean {
  const projection = observation.sourceBindingProjection;
  const binding = target.sourceBinding;
  if (
    !projection ||
    !binding ||
    !target.targetContentHash ||
    !target.series ||
    !target.period ||
    observation.dataPointId !== target.dataPointId ||
    observation.observationId !== target.observationId ||
    observation.unit !== target.unit ||
    observation.legacyQuarantined !== false ||
    observation.targetContentHash !== target.targetContentHash ||
    !observation.retrievedAt ||
    !observation.ledgerRepoSha ||
    !observation.sourceVintage ||
    projection.series !== target.series ||
    projection.period !== target.period ||
    projection.releasePolicy !== binding.releasePolicy ||
    projection.table !== binding.table ||
    projection.field !== binding.field ||
    projection.unit !== target.unit ||
    canonicalStringify(projection.transform) !==
      canonicalStringify(binding.transform)
  ) {
    return false;
  }
  if (
    typeof target.ledgerPinLineCount === "number" &&
    (typeof observation.acceptedSequence !== "number" ||
      observation.acceptedSequence < target.ledgerPinLineCount)
  ) {
    return false;
  }
  const allowedHosts = binding.allowedHosts;
  if (allowedHosts && allowedHosts.length > 0) {
    const sourceUrl = observation.sourceUrl ?? projection.sourceUrl;
    try {
      if (!sourceUrl || !allowedHosts.includes(new URL(sourceUrl).hostname)) {
        return false;
      }
    } catch {
      return false;
    }
  }
  return (
    Boolean(observation.responseArchive) &&
    projection.responseSha256 === observation.responseArchive?.sha256
  );
}

function legacyObservationSeriesIdentity(
  observation: ObservationRecordedLedgerEntry,
  target: TargetRegisteredLedgerEntry | undefined,
): string | null {
  if (
    !target ||
    target.series ||
    target.targetContentHash ||
    target.sourceBinding ||
    target.dataPointId !== observation.dataPointId ||
    target.observationId !== observation.observationId ||
    target.unit !== observation.unit ||
    observation.targetContentHash ||
    observation.sourceBindingProjection
  ) {
    return null;
  }
  return (
    REVIEWED_LEGACY_OBSERVATION_SERIES.find(
      (identity) =>
        identity.dataPointId === observation.dataPointId &&
        identity.observationId === observation.observationId &&
        identity.periodLabel === observation.periodLabel &&
        identity.unit === observation.unit &&
        identity.value === observation.value &&
        identity.acceptedSequence === observation.acceptedSequence &&
        identity.acceptedCommit === observation.acceptedCommit &&
        identity.acceptedAtUtc === observation.acceptedAtUtc &&
        identity.observedAt === observation.observedAt &&
        identity.sourceUrl === observation.sourceUrl &&
        identity.legacyQuarantined === observation.legacyQuarantined,
    )?.series ?? null
  );
}

export function registeredObservationSeriesIdentity(
  observation: ObservationRecordedLedgerEntry,
  ledger: PolicyEngineLedgerEntry[],
): string | null {
  return observationSeriesFromRegistrations(
    observation,
    registrationsByDataPointId(ledger),
  );
}

function observationSeriesFromRegistrations(
  observation: ObservationRecordedLedgerEntry,
  registrations: Map<string, TargetRegisteredLedgerEntry>,
): string | null {
  const target = registrations.get(observation.dataPointId);
  const series = contractSeries(target);
  if (series) {
    return target && projectionMatchesRegistration(observation, target)
      ? series
      : null;
  }
  return legacyObservationSeriesIdentity(observation, target);
}

function toObservationReference(
  observation: ObservationRecordedLedgerEntry,
): LedgerObservationReference {
  return {
    observationId: observation.observationId,
    dataPointId: observation.dataPointId,
    periodLabel: observation.periodLabel,
    observedAt: observation.observedAt,
    value: observation.value,
    unit: observation.unit,
  };
}

function classifyDirection(
  adjustment: number,
): TimeSeriesPriorAdjustmentRow["direction"] {
  if (Math.abs(adjustment) < 1e-9) return "flat";
  return adjustment > 0 ? "up" : "down";
}

function quantile(values: number[], probability: number) {
  const finiteValues = values
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => left - right);
  if (finiteValues.length === 0) return 0;
  if (finiteValues.length === 1) return finiteValues[0];

  const index = (finiteValues.length - 1) * probability;
  const lowerIndex = Math.floor(index);
  const upperIndex = Math.ceil(index);
  const lower = finiteValues[lowerIndex];
  const upper = finiteValues[upperIndex];
  if (lowerIndex === upperIndex) return lower;
  return lower + (upper - lower) * (index - lowerIndex);
}

function quantileOrNull(values: number[], probability: number) {
  const finiteValues = values.filter((value) => Number.isFinite(value));
  if (finiteValues.length === 0) return null;
  return quantile(finiteValues, probability);
}

function meanOrNull(values: number[]) {
  const finiteValues = values.filter((value) => Number.isFinite(value));
  if (finiteValues.length === 0) return null;
  return (
    finiteValues.reduce((total, value) => total + value, 0) /
    finiteValues.length
  );
}

function roundComparable(value: number) {
  return Number(value.toPrecision(12));
}

function formatCompact(value: number, unit: Unit) {
  const fractionDigits =
    unit === "percent" ||
    unit === "percent_growth" ||
    unit === "millions" ||
    unit === "million_cubic_feet"
      ? 1
      : 0;
  const formatted = value.toLocaleString(undefined, {
    maximumFractionDigits: fractionDigits,
  });
  return unit === "million_cubic_feet" ? `${formatted} MMcf` : formatted;
}

export function buildPriorDistributionForTest(
  forecast: ForecastCell,
  ledger: PolicyEngineLedgerEntry[] = [],
): PredictionDistribution | null {
  const cutoff = forecast.predictionRun?.runAt;
  if (!cutoff) return null;
  const prior = buildLastPrintPriorInterval(forecast, ledger, cutoff);
  if (!prior) return null;
  return buildNumericCdfFromInterval({
    pointEstimate: prior.pointEstimate,
    ciLow: prior.ciLow,
    ciHigh: prior.ciHigh,
  });
}
