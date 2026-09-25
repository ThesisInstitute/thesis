import { hasUsableNormalizationScale } from "./brier-lab";
import {
  getForecastRunEntries,
  type ForecastCell,
  type ForecastRunEntry,
  type Unit,
} from "./forecast-cells";
import {
  buildNumericCdfFromInterval,
  getDistributionTransformVersion,
  scoreNumericCdfDistribution,
  type DistributionProvenance,
  type NumericCdfDistribution,
} from "./prediction-distribution";
import {
  targetNormalizationScale,
  type PolicyEngineLedgerEntry,
} from "./thesis-log";

export type ForecastStrategyKind = "deterministic_baseline" | "agent_forward";

export type ForecastStrategyEvidenceMode = "historical_replay" | "forward_only";

export interface ForecastStrategy {
  strategyId: string;
  label: string;
  kind: ForecastStrategyKind;
  evidenceMode: ForecastStrategyEvidenceMode;
  description: string;
  inputDiscipline: string;
}

export interface StrategyScoreRow {
  scoreId: string;
  familyId: string;
  strategyId: string;
  strategyLabel: string;
  strategyKind: ForecastStrategyKind;
  evidenceMode: ForecastStrategyEvidenceMode;
  forecastSlug: string;
  title: string;
  dataPointId: string;
  entityCode: string;
  unit: Unit;
  runLabel?: string;
  agent?: string;
  model?: string;
  distributionProvenance: DistributionProvenance;
  transformVersion: string;
  pointEstimate: number;
  observedValue: number;
  interval80: {
    lower: number;
    upper: number;
    width: number;
  };
  signedError: number;
  absoluteError: number;
  normalizationScale: number | null;
  normalizationScaleSource: "ledger_dispersion" | "unavailable";
  normalizedCrps: number | null;
  normalizedAbsoluteError: number | null;
  interval80Covered: boolean;
  crps: number;
  probabilityIntegralTransform: number;
}

export interface StrategySummaryRow {
  strategyId: string;
  label: string;
  kind: ForecastStrategyKind;
  evidenceMode: ForecastStrategyEvidenceMode;
  description: string;
  distributionProvenance: DistributionProvenance | "mixed";
  transformVersions: string[];
  scoredRows: number;
  meanAbsoluteError: number | null;
  meanSignedError: number | null;
  meanNormalizedCrps: number | null;
  meanNormalizedAbsoluteError: number | null;
  interval80Coverage: number | null;
  meanAbsoluteErrorVsPersistence: number | null;
  meanNormalizedCrpsVsPersistence: number | null;
}

export interface StrategyComparisonRow {
  forecastSlug: string;
  title: string;
  dataPointId: string;
  entityCode: string;
  observedValue: number;
  persistencePointEstimate: number;
  agentPointEstimate: number;
  persistenceAbsoluteError: number;
  agentAbsoluteError: number;
  agentMinusPersistenceAbsoluteError: number;
  agentMinusPersistenceNormalizedCrps: number;
}

export interface StrategyFamilyReport {
  familyId: string;
  label: string;
  description: string;
  targetCount: number;
  resolvedTargetCount: number;
  panelStats: {
    fy2023Median: number;
    fy2024Median: number;
    deltaMedian: number;
    deltaP10: number;
    deltaP90: number;
  };
  rows: StrategyScoreRow[];
  summaries: StrategySummaryRow[];
  largestAgentNcrpsMissesVsPersistence: StrategyComparisonRow[];
}

export interface StrategyLabReport {
  schemaVersion: "brier_strategy_lab_v2";
  // The lab replays strategy formulas over already-resolved outcomes.
  // Except for the recorded agent runs it quotes, its rows are
  // retrospective reconstructions: they carry no chronology verification
  // and must never enter headline calibration, rewards, or leaderboards
  // (re-audit X9).
  evaluationMode: "retrospective_reconstruction";
  evaluationPolicy: string;
  registry: ForecastStrategy[];
  counts: {
    strategies: number;
    families: number;
    targets: number;
    resolvedTargets: number;
    scoredRows: number;
  };
  families: StrategyFamilyReport[];
  scoreRows: StrategyScoreRow[];
  summaries: StrategySummaryRow[];
}

interface SnapPanelCandidate {
  forecast: ForecastCell;
  entityCode: string;
  dataPointId: string;
  fy2023: number;
  fy2024: number;
  actual?: number;
}

interface SnapPanelMember extends SnapPanelCandidate {
  actual: number;
}

interface ScoreInput {
  familyId: string;
  strategy: ForecastStrategy;
  member: SnapPanelMember;
  pointEstimate: number;
  ciLow: number;
  ciHigh: number;
  run?: ForecastRunEntry;
  distribution?: NumericCdfDistribution;
  ledger: PolicyEngineLedgerEntry[];
}

const SNAP_PAYMENT_ERROR_FY2025_FAMILY_ID = "snap_payment_error_fy2025_panel";
const PERSISTENCE_STRATEGY_ID = "baseline.persistence.last_print";
const PANEL_SHRINKAGE_STRATEGY_ID = "baseline.panel_shrinkage";
const BRIER_PRIMARY_STRATEGY_ID = "agent.brier.primary";
const PANEL_ENTITY_TREND_WEIGHT = 0.25;

export const STRATEGY_REGISTRY: ForecastStrategy[] = [
  {
    strategyId: PERSISTENCE_STRATEGY_ID,
    label: "Last-print persistence",
    kind: "deterministic_baseline",
    evidenceMode: "historical_replay",
    description:
      "Hold the most recent official value flat and score it as a replayable benchmark.",
    inputDiscipline:
      "Uses only values published before the forecast target period resolves.",
  },
  {
    strategyId: PANEL_SHRINKAGE_STRATEGY_ID,
    label: "Panel shrinkage trend",
    kind: "deterministic_baseline",
    evidenceMode: "historical_replay",
    description:
      "Blend 25% of the entity's last annual change with 75% of the panel median change.",
    inputDiscipline:
      "Uses only the FY2023-to-FY2024 cross-section for the resolved SNAP panel.",
  },
  {
    strategyId: BRIER_PRIMARY_STRATEGY_ID,
    label: "Brier primary agent",
    kind: "agent_forward",
    evidenceMode: "forward_only",
    description:
      "The public Thesis forecast run actually recorded before resolution.",
    inputDiscipline:
      "Not replayed backward; evaluated only from immutable published runs.",
  },
];

export function buildStrategyLabReport(
  forecasts: ForecastCell[],
  ledger: PolicyEngineLedgerEntry[],
): StrategyLabReport {
  const families = [buildSnapPaymentErrorFy2025Family(forecasts, ledger)];
  const scoreRows = families.flatMap((family) => family.rows);
  const summaries = summarizeStrategies(scoreRows);

  return {
    schemaVersion: "brier_strategy_lab_v2",
    evaluationMode: "retrospective_reconstruction",
    evaluationPolicy:
      "Strategy rows are replayed over resolved outcomes to compare " +
      "formulas; they are not chronology-verified forward forecasts and " +
      "are excluded from headline calibration, rewards, and leaderboards.",
    registry: STRATEGY_REGISTRY,
    counts: {
      strategies: STRATEGY_REGISTRY.length,
      families: families.length,
      targets: sum(families.map((family) => family.targetCount)),
      resolvedTargets: sum(
        families.map((family) => family.resolvedTargetCount),
      ),
      scoredRows: scoreRows.length,
    },
    families,
    scoreRows,
    summaries,
  };
}

function buildSnapPaymentErrorFy2025Family(
  forecasts: ForecastCell[],
  ledger: PolicyEngineLedgerEntry[],
): StrategyFamilyReport {
  const candidates = getSnapPaymentErrorFy2025Candidates(forecasts);
  const members = candidates.filter(isResolvedSnapPanelMember);
  const deltas = candidates.map(
    (candidate) => candidate.fy2024 - candidate.fy2023,
  );
  const deltaP10 = quantile(deltas, 0.1);
  const deltaP90 = quantile(deltas, 0.9);
  const deltaMedian = quantile(deltas, 0.5);
  const rows = members.flatMap((member) =>
    buildSnapPaymentErrorStrategyRows({
      member,
      deltaMedian,
      deltaP10,
      deltaP90,
      ledger,
    }),
  );
  const summaries = summarizeStrategies(rows);

  return {
    familyId: SNAP_PAYMENT_ERROR_FY2025_FAMILY_ID,
    label: "SNAP FY2025 state payment error panel",
    description:
      "Resolved state and territory payment error rate forecasts scored against simple baselines and the recorded Brier agent run.",
    targetCount: candidates.length,
    resolvedTargetCount: members.length,
    panelStats: {
      fy2023Median: quantile(
        candidates.map((candidate) => candidate.fy2023),
        0.5,
      ),
      fy2024Median: quantile(
        candidates.map((candidate) => candidate.fy2024),
        0.5,
      ),
      deltaMedian,
      deltaP10,
      deltaP90,
    },
    rows,
    summaries,
    largestAgentNcrpsMissesVsPersistence:
      buildAgentNcrpsMissesVsPersistence(rows),
  };
}

function buildSnapPaymentErrorStrategyRows({
  member,
  deltaMedian,
  deltaP10,
  deltaP90,
  ledger,
}: {
  member: SnapPanelMember;
  deltaMedian: number;
  deltaP10: number;
  deltaP90: number;
  ledger: PolicyEngineLedgerEntry[];
}): StrategyScoreRow[] {
  const persistenceStrategy = requireStrategy(PERSISTENCE_STRATEGY_ID);
  const panelShrinkageStrategy = requireStrategy(PANEL_SHRINKAGE_STRATEGY_ID);
  const brierPrimaryStrategy = requireStrategy(BRIER_PRIMARY_STRATEGY_ID);
  const entityDelta = member.fy2024 - member.fy2023;
  const panelShrinkageDelta =
    PANEL_ENTITY_TREND_WEIGHT * entityDelta +
    (1 - PANEL_ENTITY_TREND_WEIGHT) * deltaMedian;
  const primaryRun = getForecastRunEntries(member.forecast).find(
    (run) => run.isPrimary,
  );
  const rows = [
    scoreStrategyPrediction({
      familyId: SNAP_PAYMENT_ERROR_FY2025_FAMILY_ID,
      strategy: persistenceStrategy,
      member,
      pointEstimate: member.fy2024,
      ...buildPanelDeltaInterval(member.fy2024, deltaP10, deltaP90),
      ledger,
    }),
    scoreStrategyPrediction({
      familyId: SNAP_PAYMENT_ERROR_FY2025_FAMILY_ID,
      strategy: panelShrinkageStrategy,
      member,
      pointEstimate: clampPercent(member.fy2024 + panelShrinkageDelta),
      ...buildPanelDeltaInterval(
        clampPercent(member.fy2024 + panelShrinkageDelta),
        deltaP10,
        deltaP90,
      ),
      ledger,
    }),
  ];

  if (primaryRun) {
    rows.push(
      scoreStrategyPrediction({
        familyId: SNAP_PAYMENT_ERROR_FY2025_FAMILY_ID,
        strategy: brierPrimaryStrategy,
        member,
        pointEstimate: primaryRun.pointEstimate,
        ciLow: primaryRun.ciLow,
        ciHigh: primaryRun.ciHigh,
        run: primaryRun,
        distribution: primaryRun.predictionDistribution,
        ledger,
      }),
    );
  }

  return rows;
}

function scoreStrategyPrediction({
  familyId,
  strategy,
  member,
  pointEstimate,
  ciLow,
  ciHigh,
  run,
  distribution,
  ledger,
}: ScoreInput): StrategyScoreRow {
  const intervalLow = Math.min(ciLow, pointEstimate);
  const intervalHigh = Math.max(ciHigh, pointEstimate);
  const interval80Width = Math.abs(intervalHigh - intervalLow);
  // Every strategy in the family shares the member target's pre-registration
  // ledger scale. No strategy output or historicalContext can change it.
  const normalization = targetNormalizationScale(member.forecast, ledger);
  const predictionDistribution =
    distribution ??
    buildNumericCdfFromInterval({
      pointEstimate,
      ciLow: intervalLow,
      ciHigh: intervalHigh,
    });
  const distributionScore = scoreNumericCdfDistribution(
    predictionDistribution,
    member.actual,
  );
  const signedError = member.actual - pointEstimate;

  return {
    scoreId: `strategy_score.${familyId}.${strategy.strategyId}.${member.forecast.slug}`,
    familyId,
    strategyId: strategy.strategyId,
    strategyLabel: strategy.label,
    strategyKind: strategy.kind,
    evidenceMode: strategy.evidenceMode,
    forecastSlug: member.forecast.slug,
    title: member.forecast.title,
    dataPointId: member.dataPointId,
    entityCode: member.entityCode,
    unit: member.forecast.unit,
    runLabel: run?.label,
    agent: run?.predictionRun?.agent,
    model: run?.predictionRun?.model,
    distributionProvenance: predictionDistribution.provenance,
    transformVersion: getDistributionTransformVersion(predictionDistribution),
    pointEstimate,
    observedValue: member.actual,
    interval80: {
      lower: intervalLow,
      upper: intervalHigh,
      width: interval80Width,
    },
    signedError,
    absoluteError: Math.abs(signedError),
    normalizationScale: normalization.scale,
    normalizationScaleSource: normalization.source,
    normalizedCrps:
      normalization.scale === null
        ? null
        : distributionScore.crps / normalization.scale,
    normalizedAbsoluteError:
      normalization.scale === null
        ? null
        : Math.abs(signedError) / normalization.scale,
    interval80Covered:
      intervalLow <= member.actual && member.actual <= intervalHigh,
    ...distributionScore,
  };
}

function getSnapPaymentErrorFy2025Candidates(
  forecasts: ForecastCell[],
): SnapPanelCandidate[] {
  return forecasts.flatMap((forecast) => {
    const dataPointId = forecast.dataPointId;
    const match = dataPointId?.match(
      /^fns\.snap\.total_payment_error_rate\.([a-z]{2})\.fy2025$/,
    );
    if (!dataPointId || !match || match[1] === "us") return [];

    const fy2023 = getHistoricalValue(forecast, "FY 2023");
    const fy2024 = getHistoricalValue(forecast, "FY 2024");
    const actual = forecast.resolvedOutcome?.value;
    if (!isFiniteNumber(fy2023) || !isFiniteNumber(fy2024)) {
      return [];
    }

    const candidate: SnapPanelCandidate = {
      forecast,
      entityCode: match[1].toUpperCase(),
      dataPointId,
      fy2023,
      fy2024,
    };
    if (isFiniteNumber(actual)) candidate.actual = actual;
    return [candidate];
  });
}

function isResolvedSnapPanelMember(
  candidate: SnapPanelCandidate,
): candidate is SnapPanelMember {
  return isFiniteNumber(candidate.actual);
}

function getHistoricalValue(forecast: ForecastCell, label: string) {
  return forecast.historicalContext.find((point) => point.label === label)
    ?.value;
}

function buildPanelDeltaInterval(
  pointEstimate: number,
  deltaP10: number,
  deltaP90: number,
) {
  const low = clampPercent(pointEstimate + Math.min(deltaP10, deltaP90));
  const high = clampPercent(pointEstimate + Math.max(deltaP10, deltaP90));
  return {
    ciLow: Math.min(low, pointEstimate),
    ciHigh: Math.max(high, pointEstimate),
  };
}

function summarizeStrategies(rows: StrategyScoreRow[]): StrategySummaryRow[] {
  const persistenceByForecast = new Map(
    rows
      .filter((row) => row.strategyId === PERSISTENCE_STRATEGY_ID)
      .map((row) => [row.forecastSlug, row]),
  );

  return STRATEGY_REGISTRY.map((strategy) => {
    const strategyRows = rows.filter(
      (row) => row.strategyId === strategy.strategyId,
    );
    const provenanceValues = new Set(
      strategyRows.map((row) => row.distributionProvenance),
    );
    const pairedRows = strategyRows
      .map((row) => {
        const persistenceRow = persistenceByForecast.get(row.forecastSlug);
        return persistenceRow ? { row, persistenceRow } : undefined;
      })
      .filter((pair): pair is NonNullable<typeof pair> => Boolean(pair));

    return {
      strategyId: strategy.strategyId,
      label: strategy.label,
      kind: strategy.kind,
      evidenceMode: strategy.evidenceMode,
      description: strategy.description,
      distributionProvenance:
        provenanceValues.size === 1
          ? (provenanceValues.values().next().value ?? "interval_seeded")
          : "mixed",
      transformVersions: [
        ...new Set(strategyRows.map((row) => row.transformVersion)),
      ].sort(),
      scoredRows: strategyRows.length,
      meanAbsoluteError: meanOrNull(
        strategyRows.map((row) => row.absoluteError),
      ),
      meanSignedError: meanOrNull(strategyRows.map((row) => row.signedError)),
      // Normalized aggregates admit only rows with a usable ledger scale:
      // a sub-epsilon dispersion is numerical zero, and dividing by it
      // would let one row own every mean. Raw-unit aggregates keep all rows.
      meanNormalizedCrps: meanOrNull(
        strategyRows
          .filter((row) => hasUsableNormalizationScale(row))
          .map((row) => row.normalizedCrps)
          .filter((value): value is number => value !== null),
      ),
      meanNormalizedAbsoluteError: meanOrNull(
        strategyRows
          .filter((row) => hasUsableNormalizationScale(row))
          .map((row) => row.normalizedAbsoluteError)
          .filter((value): value is number => value !== null),
      ),
      interval80Coverage: meanOrNull(
        strategyRows.map((row) => (row.interval80Covered ? 1 : 0)),
      ),
      meanAbsoluteErrorVsPersistence: meanOrNull(
        pairedRows.map(
          ({ row, persistenceRow }) =>
            row.absoluteError - persistenceRow.absoluteError,
        ),
      ),
      // Both sides of a pair divide by the target's single ledger scale, so
      // a degenerate scale poisons the pair as a whole and the pair drops;
      // pairedRows itself stays unfiltered for the raw-unit comparison
      // above.
      meanNormalizedCrpsVsPersistence: meanOrNull(
        pairedRows.flatMap(({ row, persistenceRow }) =>
          row.normalizedCrps === null ||
          persistenceRow.normalizedCrps === null ||
          !hasUsableNormalizationScale(row) ||
          !hasUsableNormalizationScale(persistenceRow)
            ? []
            : [row.normalizedCrps - persistenceRow.normalizedCrps],
        ),
      ),
    };
  });
}

function buildAgentNcrpsMissesVsPersistence(
  rows: StrategyScoreRow[],
): StrategyComparisonRow[] {
  const persistenceByForecast = new Map(
    rows
      .filter((row) => row.strategyId === PERSISTENCE_STRATEGY_ID)
      .map((row) => [row.forecastSlug, row]),
  );

  return rows
    .filter((row) => row.strategyId === BRIER_PRIMARY_STRATEGY_ID)
    .flatMap((agentRow) => {
      const persistenceRow = persistenceByForecast.get(agentRow.forecastSlug);
      if (
        !persistenceRow ||
        agentRow.normalizedCrps === null ||
        persistenceRow.normalizedCrps === null ||
        // Agent and persistence rows divide by the target's single ledger
        // scale; a sub-epsilon scale is numerical zero and would mint this
        // ranking's top entries, so the pair drops whole.
        !hasUsableNormalizationScale(agentRow) ||
        !hasUsableNormalizationScale(persistenceRow)
      )
        return [];
      return [
        {
          forecastSlug: agentRow.forecastSlug,
          title: agentRow.title,
          dataPointId: agentRow.dataPointId,
          entityCode: agentRow.entityCode,
          observedValue: agentRow.observedValue,
          persistencePointEstimate: persistenceRow.pointEstimate,
          agentPointEstimate: agentRow.pointEstimate,
          persistenceAbsoluteError: persistenceRow.absoluteError,
          agentAbsoluteError: agentRow.absoluteError,
          agentMinusPersistenceAbsoluteError:
            agentRow.absoluteError - persistenceRow.absoluteError,
          agentMinusPersistenceNormalizedCrps:
            agentRow.normalizedCrps - persistenceRow.normalizedCrps,
        },
      ];
    })
    .filter((row) => row.agentMinusPersistenceNormalizedCrps > 0)
    .sort(
      (left, right) =>
        right.agentMinusPersistenceNormalizedCrps -
        left.agentMinusPersistenceNormalizedCrps,
    )
    .slice(0, 12);
}

function requireStrategy(strategyId: string): ForecastStrategy {
  const strategy = STRATEGY_REGISTRY.find(
    (candidate) => candidate.strategyId === strategyId,
  );
  if (!strategy) throw new Error(`Unknown forecast strategy: ${strategyId}`);
  return strategy;
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

function meanOrNull(values: number[]) {
  const finiteValues = values.filter((value) => Number.isFinite(value));
  if (finiteValues.length === 0) return null;
  return sum(finiteValues) / finiteValues.length;
}

function sum(values: number[]) {
  return values.reduce((total, value) => total + value, 0);
}

function clampPercent(value: number) {
  return Math.min(100, Math.max(0, value));
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
