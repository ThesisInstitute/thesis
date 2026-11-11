import { isNormalizedScoreAggregateEligible } from "./brier-lab";
import type {
  ForecastCell,
  ForecastRunEntry,
  ReasoningStep,
} from "./forecast-cells";
import { getForecastRunEntries } from "./forecast-cells";
import { buildRecordedPredictionRunId, buildSpecId } from "./prediction-specs";
import type { ResolvedForecastScore } from "./thesis-log";

export type ForecastTraceJudgeSchemaVersion = "thesis_forecast_trace_judge_v1";
export type ForecastPairwiseJudgeSchemaVersion =
  "thesis_forecast_pairwise_judge_v1";
export type ForecastResolutionJudgeSchemaVersion =
  "thesis_forecast_resolution_judge_v1";

export type ForecastTraceJudgeDimensionId =
  | "base_rate_use"
  | "source_grounding"
  | "resolution_clarity"
  | "uncertainty_calibration"
  | "mechanism_reasoning"
  | "counterarguments"
  | "forecast_coherence";

export interface ForecastTraceJudgeRubricDimension {
  dimensionId: ForecastTraceJudgeDimensionId;
  label: string;
  weight: number;
  description: string;
}

export interface ForecastJudgeModelMetadata {
  kind: "llm_judge";
  model: string;
  promptVersion: string;
  inputScope: "public_trace_and_spec";
  executionMode: "rubric_seed" | "model_generated";
  rewardEligible: false;
}

export interface ForecastTraceJudgeDimensionScore {
  dimensionId: ForecastTraceJudgeDimensionId;
  label: string;
  score: number;
  rationale: string;
  evidence: string[];
}

export interface ForecastTraceJudgeRecord {
  schemaVersion: ForecastTraceJudgeSchemaVersion;
  judgeId: string;
  runId: string;
  predictionId: string;
  specId: string;
  runLabel: string;
  evaluatedAt: string;
  judge: ForecastJudgeModelMetadata;
  scoreScale: {
    min: 0;
    max: 4;
  };
  overallScore: number;
  dimensions: ForecastTraceJudgeDimensionScore[];
  flags: string[];
  prompt: {
    system: string;
    user: string;
    outputSchema: string;
  };
  summary: string;
}

export interface ForecastPairwiseJudgeRecord {
  schemaVersion: ForecastPairwiseJudgeSchemaVersion;
  judgeId: string;
  predictionId: string;
  leftRunId: string;
  rightRunId: string;
  leftLabel: string;
  rightLabel: string;
  evaluatedAt: string;
  judge: ForecastJudgeModelMetadata;
  winner: "left" | "right" | "tie";
  confidence: number;
  reason: string;
}

export type ForecastResolutionFailureMode =
  | "well_calibrated"
  | "bad_baseline"
  | "overreacted_to_recent_data"
  | "ignored_official_projection"
  | "interval_too_narrow"
  | "resolution_or_units_risk"
  | "surprising_release";

export interface ForecastResolutionJudgeRecord {
  schemaVersion: ForecastResolutionJudgeSchemaVersion;
  judgeId: string;
  runId: string;
  scoreId: string;
  predictionId: string;
  evaluatedAt: string;
  judge: ForecastJudgeModelMetadata;
  primaryFailureMode: ForecastResolutionFailureMode;
  tags: ForecastResolutionFailureMode[];
  severity: "none" | "low" | "medium" | "high";
  explanation: string;
}

export interface ForecastJudgeCalibrationBand {
  label: string;
  minScore: number;
  maxScore: number;
  judgedRuns: number;
  scoredRuns: number;
  meanJudgeScore: number | null;
  meanNormalizedCrps: number | null;
  meanAbsoluteError: number | null;
  interval80Coverage: number | null;
}

export interface ForecastJudgeCalibrationDisagreement {
  runId: string;
  predictionId: string;
  runLabel: string;
  judgeScore: number;
  normalizedCrps: number;
  interval80Covered: boolean;
  disagreement: "high_judge_bad_score" | "low_judge_good_score";
}

export interface ForecastJudgeCalibrationReport {
  schemaVersion: "thesis_forecast_judge_calibration_v1";
  counts: {
    judgedRuns: number;
    scoredJudgedRuns: number;
    pairwiseComparisons: number;
    postResolutionReviews: number;
  };
  meanJudgeScore: number | null;
  meanNormalizedCrpsWhenScored: number | null;
  judgeScoreVsNegativeNormalizedCrps: number | null;
  scoreBands: ForecastJudgeCalibrationBand[];
  disagreements: ForecastJudgeCalibrationDisagreement[];
}

export interface ForecastJudgeExport {
  schemaVersion: "thesis_forecast_judges_v1";
  generatedAt: string;
  policy: {
    role: "auxiliary_process_eval";
    rewardEligible: false;
    rule: string;
  };
  traceQuality: ForecastTraceJudgeRecord[];
  pairwise: ForecastPairwiseJudgeRecord[];
  postResolution: ForecastResolutionJudgeRecord[];
  calibration: ForecastJudgeCalibrationReport;
}

const JUDGE_GENERATED_AT = "2026-06-26T00:00:00Z";
const JUDGE_PROMPT_VERSION = "forecast-trace-quality-v0.1";
const JUDGE_MODEL = "configured-llm-judge";

type NormalizedForecastScore = ResolvedForecastScore & {
  normalizationScale: number;
  normalizedCrps: number;
  normalizedAbsoluteError: number;
  sharpness: number;
};

// Eligibility gate for every normalized-metric aggregate in this module,
// delegated to the shared brier-lab predicate: a sub-epsilon
// ledger-dispersion scale is numerical zero left over from equal decimal
// steps, never a usable denominator, and scores carrying one must stay out
// of normalized aggregates. The normalizedAbsoluteError check only narrows
// the local type — every normalized field is null exactly when the scale
// is null.
function isAggregateEligibleNormalizedScore(
  score: ResolvedForecastScore,
): score is NormalizedForecastScore {
  return (
    isNormalizedScoreAggregateEligible(score) &&
    score.normalizedAbsoluteError !== null
  );
}

export const FORECAST_TRACE_JUDGE_RUBRIC: ForecastTraceJudgeRubricDimension[] =
  [
    {
      dimensionId: "base_rate_use",
      label: "Base-rate use",
      weight: 1.2,
      description:
        "The trace states an outside-view baseline or historical prior before current-release adjustments.",
    },
    {
      dimensionId: "source_grounding",
      label: "Source grounding",
      weight: 1.2,
      description:
        "The trace cites typed tools, official sources, ledger facts, or public data used in the forecast.",
    },
    {
      dimensionId: "resolution_clarity",
      label: "Resolution clarity",
      weight: 1,
      description:
        "The target has a concrete resolution date, source, rule, and first-print/fixed-vintage semantics.",
    },
    {
      dimensionId: "uncertainty_calibration",
      label: "Uncertainty calibration",
      weight: 1.1,
      description:
        "The trace explains the 80% interval and gives a distribution that is not just a point estimate.",
    },
    {
      dimensionId: "mechanism_reasoning",
      label: "Mechanism reasoning",
      weight: 1,
      description:
        "The trace names drivers and gives a causal/mechanical story for why the forecast should move.",
    },
    {
      dimensionId: "counterarguments",
      label: "Counterarguments",
      weight: 0.8,
      description:
        "The trace acknowledges plausible offsetting evidence, tails, or reasons the forecast could miss.",
    },
    {
      dimensionId: "forecast_coherence",
      label: "Forecast coherence",
      weight: 1.1,
      description:
        "The final forecast follows from the trace, has point inside interval, and matches the published distribution.",
    },
  ];

export function buildForecastJudgeExport({
  forecasts,
  scores,
  generatedAt = JUDGE_GENERATED_AT,
}: {
  forecasts: ForecastCell[];
  scores: ResolvedForecastScore[];
  generatedAt?: string;
}): ForecastJudgeExport {
  const traceQuality = buildForecastTraceJudgeRecords(forecasts, generatedAt);
  const pairwise = buildForecastPairwiseJudgeRecords(
    forecasts,
    traceQuality,
    generatedAt,
  );
  const postResolution = buildForecastResolutionJudgeRecords(
    scores,
    generatedAt,
  );
  const calibration = buildForecastJudgeCalibrationReport({
    traceQuality,
    pairwise,
    postResolution,
    scores,
  });

  return {
    schemaVersion: "thesis_forecast_judges_v1",
    generatedAt,
    policy: {
      role: "auxiliary_process_eval",
      rewardEligible: false,
      rule: "LLM judge scores evaluate public trace quality and failure modes. They are never used as proper-score reward; resolved CRPS/Brier-style scores remain the training objective.",
    },
    traceQuality,
    pairwise,
    postResolution,
    calibration,
  };
}

export function buildForecastTraceJudgeRecords(
  forecasts: ForecastCell[],
  evaluatedAt = JUDGE_GENERATED_AT,
): ForecastTraceJudgeRecord[] {
  return forecasts.flatMap((forecast) =>
    getForecastRunEntries(forecast).map((run) =>
      buildForecastTraceJudgeRecord(forecast, run, evaluatedAt),
    ),
  );
}

export function buildForecastPairwiseJudgeRecords(
  forecasts: ForecastCell[],
  traceQuality: ForecastTraceJudgeRecord[] = buildForecastTraceJudgeRecords(
    forecasts,
  ),
  evaluatedAt = JUDGE_GENERATED_AT,
): ForecastPairwiseJudgeRecord[] {
  const traceByRunId = new Map(
    traceQuality.map((record) => [record.runId, record]),
  );

  return forecasts.flatMap((forecast) => {
    const runs = getForecastRunEntries(forecast);
    const primary = runs[0];
    if (!primary || runs.length < 2) return [];
    const primaryRunId = getRunId(forecast, primary);
    const primaryTrace = traceByRunId.get(primaryRunId);
    if (!primaryTrace) return [];

    return runs.slice(1).flatMap((comparisonRun) => {
      const comparisonRunId = getRunId(forecast, comparisonRun);
      const comparisonTrace = traceByRunId.get(comparisonRunId);
      if (!comparisonTrace) return [];
      const delta = primaryTrace.overallScore - comparisonTrace.overallScore;
      const winner =
        Math.abs(delta) < 0.25 ? "tie" : delta > 0 ? "left" : "right";
      const reason =
        winner === "tie"
          ? "The public traces are similarly useful under the process-quality rubric."
          : winner === "left"
            ? "The primary run has stronger public trace quality under the rubric."
            : "The comparison run has stronger public trace quality under the rubric.";

      return [
        {
          schemaVersion: "thesis_forecast_pairwise_judge_v1",
          judgeId: `judge.pairwise.${primaryRunId}.vs.${comparisonRunId}`,
          predictionId: forecast.slug,
          leftRunId: primaryRunId,
          rightRunId: comparisonRunId,
          leftLabel: primary.label,
          rightLabel: comparisonRun.label,
          evaluatedAt,
          judge: buildJudgeMetadata(),
          winner,
          confidence: round2(Math.min(0.95, 0.55 + Math.abs(delta) / 4)),
          reason,
        },
      ];
    });
  });
}

export function buildForecastResolutionJudgeRecords(
  scores: ResolvedForecastScore[],
  evaluatedAt = JUDGE_GENERATED_AT,
): ForecastResolutionJudgeRecord[] {
  return scores.map((score) => {
    const tags = classifyResolutionFailureModes(score);
    const primaryFailureMode = tags[0] ?? "well_calibrated";
    return {
      schemaVersion: "thesis_forecast_resolution_judge_v1",
      judgeId: `judge.resolution.${score.scoreId}`,
      runId: score.runId,
      scoreId: score.scoreId,
      predictionId: score.forecastSlug,
      evaluatedAt,
      judge: buildJudgeMetadata(),
      primaryFailureMode,
      tags,
      severity: getFailureSeverity(score),
      explanation: buildResolutionExplanation(score, primaryFailureMode),
    };
  });
}

export function buildForecastJudgeCalibrationReport({
  traceQuality,
  pairwise,
  postResolution,
  scores,
}: {
  traceQuality: ForecastTraceJudgeRecord[];
  pairwise: ForecastPairwiseJudgeRecord[];
  postResolution: ForecastResolutionJudgeRecord[];
  scores: ResolvedForecastScore[];
}): ForecastJudgeCalibrationReport {
  const scoresByRunId = new Map(scores.map((score) => [score.runId, score]));
  const scoredJudges = traceQuality.flatMap((judge) => {
    const score = scoresByRunId.get(judge.runId);
    return score && isAggregateEligibleNormalizedScore(score)
      ? [{ judge, score }]
      : [];
  });
  const correlation = pearsonCorrelation(
    scoredJudges.map((row) => row.judge.overallScore),
    scoredJudges.map((row) => -row.score.normalizedCrps),
  );

  return {
    schemaVersion: "thesis_forecast_judge_calibration_v1",
    counts: {
      judgedRuns: traceQuality.length,
      scoredJudgedRuns: scoredJudges.length,
      pairwiseComparisons: pairwise.length,
      postResolutionReviews: postResolution.length,
    },
    meanJudgeScore: mean(traceQuality.map((judge) => judge.overallScore)),
    meanNormalizedCrpsWhenScored: mean(
      scoredJudges.map((row) => row.score.normalizedCrps),
    ),
    judgeScoreVsNegativeNormalizedCrps: correlation,
    scoreBands: buildScoreBands(traceQuality, scoresByRunId),
    disagreements: buildJudgeCalibrationDisagreements(scoredJudges),
  };
}

function buildForecastTraceJudgeRecord(
  forecast: ForecastCell,
  run: ForecastRunEntry,
  evaluatedAt: string,
): ForecastTraceJudgeRecord {
  const context = buildJudgeContext(forecast, run);
  const dimensions = FORECAST_TRACE_JUDGE_RUBRIC.map((rubric) =>
    scoreDimension(rubric, context),
  );
  const weightedScore =
    dimensions.reduce((total, dimension) => {
      const rubric = FORECAST_TRACE_JUDGE_RUBRIC.find(
        (candidate) => candidate.dimensionId === dimension.dimensionId,
      );
      return total + dimension.score * (rubric?.weight ?? 1);
    }, 0) /
    FORECAST_TRACE_JUDGE_RUBRIC.reduce(
      (total, rubric) => total + rubric.weight,
      0,
    );
  const runId = getRunId(forecast, run);
  const flags = buildTraceFlags(dimensions, context);

  return {
    schemaVersion: "thesis_forecast_trace_judge_v1",
    judgeId: `judge.trace.${runId}`,
    runId,
    predictionId: forecast.slug,
    specId: buildSpecId(forecast.slug),
    runLabel: run.label,
    evaluatedAt,
    judge: buildJudgeMetadata(),
    scoreScale: {
      min: 0,
      max: 4,
    },
    overallScore: round2(weightedScore),
    dimensions,
    flags,
    prompt: buildTraceJudgePrompt(forecast, run, context.publicTrace),
    summary: buildTraceSummary(dimensions, flags),
  };
}

function buildJudgeContext(forecast: ForecastCell, run: ForecastRunEntry) {
  const publicTrace = run.reasoning.flatMap(formatReasoningStep);
  const traceText = publicTrace.join("\n").toLowerCase();
  const toolCalls = run.reasoning.filter((step) => step.kind === "tool");
  const forecastSteps = run.reasoning.filter(
    (step) => step.kind === "forecast",
  );
  const intervalWidth = Math.abs(run.ciHigh - run.ciLow);
  const pointInsideInterval =
    run.ciLow <= run.pointEstimate && run.pointEstimate <= run.ciHigh;

  return {
    publicTrace,
    traceText,
    toolCalls,
    forecastSteps,
    intervalWidth,
    pointInsideInterval,
    hasDistribution: Boolean(run.predictionDistribution),
    hasLedgerTarget: Boolean(forecast.dataPointId),
    hasActivityLog: Boolean(run.predictionRun?.activityLog?.length),
    sourceContextCount: run.predictionRun?.sourceContext.length ?? 0,
    historicalPointCount: forecast.historicalContext.length,
    driverCount: run.drivers.length,
    packSet: run.packSet,
  };
}

function scoreDimension(
  rubric: ForecastTraceJudgeRubricDimension,
  context: ReturnType<typeof buildJudgeContext>,
): ForecastTraceJudgeDimensionScore {
  const score = scoreDimensionValue(rubric.dimensionId, context);
  return {
    dimensionId: rubric.dimensionId,
    label: rubric.label,
    score,
    rationale: buildDimensionRationale(rubric.dimensionId, score, context),
    evidence: selectEvidence(rubric.dimensionId, context),
  };
}

function scoreDimensionValue(
  dimensionId: ForecastTraceJudgeDimensionId,
  context: ReturnType<typeof buildJudgeContext>,
) {
  switch (dimensionId) {
    case "base_rate_use":
      return clampScore(
        1 +
          (context.historicalPointCount >= 2 ? 1 : 0) +
          keywordScore(context.traceText, [
            "base rate",
            "baseline",
            "prior",
            "persistence",
            "historical",
            "last print",
            "median",
          ]),
      );
    case "source_grounding":
      return clampScore(
        1 +
          Math.min(2, context.toolCalls.length) +
          (context.sourceContextCount > 0 || context.hasActivityLog ? 1 : 0) +
          keywordScore(context.traceText, [
            "official",
            "ledger",
            "bls",
            "census",
            "ons",
            "statcan",
            "eurostat",
            "bea",
          ]),
      );
    case "resolution_clarity":
      return clampScore(
        1 +
          (context.hasLedgerTarget ? 1 : 0) +
          keywordScore(context.traceText, [
            "first print",
            "resolves",
            "release",
            "published",
            "later revisions",
          ]),
      );
    case "uncertainty_calibration":
      return clampScore(
        1 +
          (context.intervalWidth > 0 ? 1 : 0) +
          (context.hasDistribution ? 1 : 0) +
          (context.forecastSteps.length > 0 ? 1 : 0) +
          keywordScore(context.traceText, [
            "uncertainty",
            "80%",
            "interval",
            "tail",
            "risk",
            "confidence",
          ]),
      );
    case "mechanism_reasoning":
      return clampScore(
        1 +
          Math.min(2, context.driverCount > 0 ? 1 : 0) +
          keywordScore(context.traceText, [
            "driver",
            "because",
            "pressure",
            "momentum",
            "mechanism",
            "channel",
            "adjust",
          ]),
      );
    case "counterarguments":
      return clampScore(
        keywordScore(context.traceText, [
          "however",
          "but",
          "offset",
          "downside",
          "upside",
          "tail",
          "risk",
          "surprise",
          "uncertain",
          "unless",
        ]) + (context.packSet ? 1 : 0),
      );
    case "forecast_coherence":
      return clampScore(
        1 +
          (context.pointInsideInterval ? 1 : 0) +
          (context.forecastSteps.length > 0 ? 1 : 0) +
          (context.hasDistribution ? 1 : 0),
      );
  }
}

function buildDimensionRationale(
  dimensionId: ForecastTraceJudgeDimensionId,
  score: number,
  context: ReturnType<typeof buildJudgeContext>,
) {
  if (dimensionId === "source_grounding") {
    return `Score ${score}/4: ${context.toolCalls.length} typed tool call(s), ${context.sourceContextCount} source-context item(s), activity log ${context.hasActivityLog ? "present" : "absent"}.`;
  }
  if (dimensionId === "base_rate_use") {
    return `Score ${score}/4: ${context.historicalPointCount} historical point(s) and ${mentionsAny(context.traceText, ["base rate", "baseline", "prior", "persistence"]) ? "explicit" : "implicit"} outside-view language.`;
  }
  if (dimensionId === "uncertainty_calibration") {
    return `Score ${score}/4: interval width ${round2(context.intervalWidth)}, distribution ${context.hasDistribution ? "present" : "missing"}, forecast step count ${context.forecastSteps.length}.`;
  }
  if (dimensionId === "counterarguments") {
    return `Score ${score}/4: offsetting-evidence language is ${mentionsAny(context.traceText, ["however", "but", "offset", "risk", "tail", "uncertain"]) ? "present" : "thin"}.`;
  }
  return `Score ${score}/4 under the ${dimensionId.replace(/_/g, " ")} rubric.`;
}

function selectEvidence(
  dimensionId: ForecastTraceJudgeDimensionId,
  context: ReturnType<typeof buildJudgeContext>,
) {
  const patternsByDimension: Record<ForecastTraceJudgeDimensionId, string[]> = {
    base_rate_use: ["base", "baseline", "prior", "historical", "median"],
    source_grounding: ["official", "ledger", "bls", "census", "ons", "statcan"],
    resolution_clarity: ["resolves", "first", "release", "published"],
    uncertainty_calibration: ["uncertainty", "interval", "tail", "risk"],
    mechanism_reasoning: ["driver", "because", "momentum", "pressure"],
    counterarguments: ["however", "but", "offset", "risk", "uncertain"],
    forecast_coherence: ["forecast", "point", "interval"],
  };
  const patterns = patternsByDimension[dimensionId];
  const evidence = context.publicTrace.filter((line) =>
    patterns.some((pattern) => line.toLowerCase().includes(pattern)),
  );
  return evidence.slice(0, 2);
}

function buildTraceFlags(
  dimensions: ForecastTraceJudgeDimensionScore[],
  context: ReturnType<typeof buildJudgeContext>,
) {
  const flags: string[] = [];
  for (const dimension of dimensions) {
    if (dimension.score < 2) {
      flags.push(`weak_${dimension.dimensionId}`);
    }
  }
  if (context.toolCalls.length === 0) flags.push("no_typed_tool_call");
  if (!context.hasLedgerTarget) flags.push("no_ledger_target");
  if (!context.pointInsideInterval) flags.push("point_outside_interval");
  return flags;
}

function buildTraceSummary(
  dimensions: ForecastTraceJudgeDimensionScore[],
  flags: string[],
) {
  const strongest = [...dimensions].sort((a, b) => b.score - a.score)[0];
  const weakest = [...dimensions].sort((a, b) => a.score - b.score)[0];
  return [
    strongest
      ? `Strongest dimension: ${strongest.label.toLowerCase()} (${strongest.score}/4).`
      : "",
    weakest
      ? `Weakest dimension: ${weakest.label.toLowerCase()} (${weakest.score}/4).`
      : "",
    flags.length ? `Flags: ${flags.join(", ")}.` : "No major process flags.",
  ]
    .filter(Boolean)
    .join(" ");
}

function buildTraceJudgePrompt(
  forecast: ForecastCell,
  run: ForecastRunEntry,
  publicTrace: string[],
) {
  return {
    system:
      "You are an LLM-as-judge for forecast process quality. Judge only the public trace and target contract. Do not reward a forecast for matching an unknown future; proper scoring happens after official resolution.",
    user: [
      "Evaluate the linked prediction run using its Thesis run record, publicTrace, target contract, distribution summary, and the forecast trace judge rubric.",
      `predictionId: ${forecast.slug}`,
      `runLabel: ${run.label}`,
      `resolutionDate: ${forecast.resolutionDate}`,
      `traceLineCount: ${publicTrace.length}`,
      "Do not duplicate hidden reasoning or re-score the outcome.",
    ].join("\n"),
    outputSchema:
      "{ overallScore: number, dimensions: [{ dimensionId, score, rationale, evidence }], flags: string[], summary: string }",
  };
}

function classifyResolutionFailureModes(
  score: ResolvedForecastScore,
): ForecastResolutionFailureMode[] {
  if (
    score.interval80Covered &&
    score.normalizedCrps !== null &&
    score.normalizedCrps <= 0.25
  ) {
    return ["well_calibrated"];
  }

  const modes: ForecastResolutionFailureMode[] = [];
  if (!score.interval80Covered) modes.push("interval_too_narrow");
  if (
    score.normalizedAbsoluteError !== null &&
    score.normalizedAbsoluteError > 1.25
  )
    modes.push("surprising_release");
  if (score.packSet?.packs.some((pack) => /projection/i.test(pack.label))) {
    modes.push("ignored_official_projection");
  }
  if (Math.abs(score.signedError) > score.interval80.width * 0.75) {
    modes.push(
      score.signedError > 0 ? "bad_baseline" : "overreacted_to_recent_data",
    );
  }
  if (!score.dataPointId) modes.push("resolution_or_units_risk");

  return modes.length ? [...new Set(modes)] : ["bad_baseline"];
}

function getFailureSeverity(score: ResolvedForecastScore) {
  if (
    score.interval80Covered &&
    score.normalizedCrps !== null &&
    score.normalizedCrps <= 0.25
  )
    return "none";
  if (
    (score.normalizedCrps !== null && score.normalizedCrps >= 1) ||
    (score.normalizedAbsoluteError !== null &&
      score.normalizedAbsoluteError >= 1)
  ) {
    return "high";
  }
  if (
    (score.normalizedCrps !== null && score.normalizedCrps >= 0.5) ||
    !score.interval80Covered
  ) {
    return "medium";
  }
  return "low";
}

function buildResolutionExplanation(
  score: ResolvedForecastScore,
  mode: ForecastResolutionFailureMode,
) {
  if (mode === "well_calibrated") {
    return "Observed value landed inside the forecast interval with low normalized CRPS.";
  }
  const normalized =
    score.normalizedCrps === null
      ? "nCRPS unavailable (fewer than three pre-cutoff ledger observations)"
      : `nCRPS ${round2(score.normalizedCrps)}`;
  return `Observed value ${score.observedValue} versus point ${score.pointEstimate}; signed error ${round2(score.signedError)}, ${normalized}. Primary review tag: ${mode.replace(/_/g, " ")}.`;
}

function buildScoreBands(
  traceQuality: ForecastTraceJudgeRecord[],
  scoresByRunId: Map<string, ResolvedForecastScore>,
): ForecastJudgeCalibrationBand[] {
  const bands = [
    { label: "weak", minScore: 0, maxScore: 1.99 },
    { label: "developing", minScore: 2, maxScore: 2.99 },
    { label: "strong", minScore: 3, maxScore: 4 },
  ];

  return bands.map((band) => {
    const judges = traceQuality.filter(
      (judge) =>
        judge.overallScore >= band.minScore &&
        judge.overallScore <= band.maxScore,
    );
    const scores = judges
      .map((judge) => scoresByRunId.get(judge.runId))
      .filter((score): score is ResolvedForecastScore => Boolean(score));
    return {
      ...band,
      judgedRuns: judges.length,
      scoredRuns: scores.length,
      meanJudgeScore: mean(judges.map((judge) => judge.overallScore)),
      // Only the normalized mean is scale-gated; the raw-unit and coverage
      // aggregates below keep every resolved score in the band.
      meanNormalizedCrps: mean(
        scores
          .filter(isNormalizedScoreAggregateEligible)
          .map((score) => score.normalizedCrps),
      ),
      meanAbsoluteError: mean(scores.map((score) => score.absoluteError)),
      interval80Coverage: mean(
        scores.map((score) => (score.interval80Covered ? 1 : 0)),
      ),
    };
  });
}

function buildJudgeCalibrationDisagreements(
  scoredJudges: Array<{
    judge: ForecastTraceJudgeRecord;
    score: NormalizedForecastScore;
  }>,
): ForecastJudgeCalibrationDisagreement[] {
  const highJudgeBadScore = scoredJudges
    .filter(
      ({ judge, score }) =>
        judge.overallScore >= 3 && score.normalizedCrps >= 0.75,
    )
    .sort((a, b) => b.score.normalizedCrps - a.score.normalizedCrps)
    .slice(0, 5)
    .map(({ judge, score }) => ({
      runId: judge.runId,
      predictionId: judge.predictionId,
      runLabel: judge.runLabel,
      judgeScore: judge.overallScore,
      normalizedCrps: score.normalizedCrps,
      interval80Covered: score.interval80Covered,
      disagreement: "high_judge_bad_score" as const,
    }));

  const lowJudgeGoodScore = scoredJudges
    .filter(
      ({ judge, score }) =>
        judge.overallScore < 2.5 && score.normalizedCrps <= 0.25,
    )
    .sort((a, b) => a.score.normalizedCrps - b.score.normalizedCrps)
    .slice(0, 5)
    .map(({ judge, score }) => ({
      runId: judge.runId,
      predictionId: judge.predictionId,
      runLabel: judge.runLabel,
      judgeScore: judge.overallScore,
      normalizedCrps: score.normalizedCrps,
      interval80Covered: score.interval80Covered,
      disagreement: "low_judge_good_score" as const,
    }));

  return [...highJudgeBadScore, ...lowJudgeGoodScore];
}

function formatReasoningStep(step: ReasoningStep) {
  if (step.kind === "heading" || step.kind === "text" || step.kind === "math") {
    return [step.text];
  }
  if (step.kind === "tool") {
    return [`Tool call: ${step.call}`, `Tool result: ${step.result}`];
  }
  return [
    `Forecast: point ${step.point}, 80% interval [${step.ciLow}, ${step.ciHigh}]`,
  ];
}

function getRunId(forecast: ForecastCell, run: ForecastRunEntry) {
  return buildRecordedPredictionRunId(
    forecast,
    run.predictionRun?.runAt,
    run.variantId,
    run,
  );
}

function buildJudgeMetadata(): ForecastJudgeModelMetadata {
  return {
    kind: "llm_judge",
    model: JUDGE_MODEL,
    promptVersion: JUDGE_PROMPT_VERSION,
    inputScope: "public_trace_and_spec",
    executionMode: "rubric_seed",
    rewardEligible: false,
  };
}

function keywordScore(text: string, keywords: string[]) {
  const matches = keywords.filter((keyword) => text.includes(keyword)).length;
  return Math.min(2, matches);
}

function mentionsAny(text: string, keywords: string[]) {
  return keywords.some((keyword) => text.includes(keyword));
}

function clampScore(value: number) {
  return Math.max(0, Math.min(4, value));
}

function pearsonCorrelation(left: number[], right: number[]) {
  if (left.length !== right.length || left.length < 2) return null;
  const leftMean = mean(left);
  const rightMean = mean(right);
  if (leftMean === null || rightMean === null) return null;
  const numerator = left.reduce(
    (total, value, index) =>
      total + (value - leftMean) * (right[index] - rightMean),
    0,
  );
  const leftDenominator = Math.sqrt(
    left.reduce((total, value) => total + (value - leftMean) ** 2, 0),
  );
  const rightDenominator = Math.sqrt(
    right.reduce((total, value) => total + (value - rightMean) ** 2, 0),
  );
  if (leftDenominator === 0 || rightDenominator === 0) return null;
  return round2(numerator / (leftDenominator * rightDenominator));
}

function mean(values: number[]) {
  if (!values.length) return null;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function round2(value: number) {
  return Math.round(value * 100) / 100;
}
