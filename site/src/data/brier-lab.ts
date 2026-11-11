import type {
  ExternalSubmissionAttribution,
  ForecastCell,
  PredictionPreSubmitReviewWorkflow,
} from "./forecast-cells";
import {
  buildForecastJudgeExport,
  type ForecastJudgeExport,
  type ForecastResolutionFailureMode,
} from "./forecast-judges";
import {
  buildRecordedPredictionRunId,
  buildRecordedPredictionRunRecords,
  type PredictionRunRecord,
  type PredictionSpec,
} from "./prediction-specs";
import type {
  PolicyEngineLedgerEntry,
  ResolvedForecastScore,
} from "./thesis-log";
import {
  buildPredictionRecordedLogEntries,
  buildResolvedPredictionLogEntries,
  evaluateResolvedForecastRun,
  getResolutionForForecast,
  hasVerifiedClaimedChronology,
  isScoreEligibleForecastRun,
  scoreResolvedForecasts,
  withResolvedOutcomes,
  type ForecastRunScoreEvaluation,
} from "./thesis-log";
import { getForecastRunEntries } from "./forecast-cells";
import {
  getDistributionTransformVersion,
  type DistributionProvenance,
} from "./prediction-distribution";
import {
  PERSISTENCE_BASELINE_AGENT,
  TIME_SERIES_PRIOR_VARIANT_ID,
} from "./time-series-priors";
import { filterPublishedForecasts } from "@/lib/forecast-publication";

export type BrierEvalSplit = "train" | "validation" | "test" | "unresolved";

// Why a row does or doesn't carry a reward-eligible score. Only
// "scored_witness_verified" earns reward: the run's custody root was
// externally witnessed before the observation (re-audit N1 — a claimed
// timestamp is testimony, not proof). "scored_deterministic_baseline" rows
// are the paired persistence baseline: replayable pure functions of
// pre-cutoff ledger data, so they carry score components for the scale-free
// paired comparison without a witness of their own.
// "excluded_chronology_claimed_only" is the legacy tier — claimed run time
// precedes the observation but no external witness proves publication.
// Every "excluded_*" reason describes a RESOLVED target whose run an
// integrity gate kept out — those rows must never masquerade as
// "unresolved" (re-audit X9).
export type BrierScoreEligibility =
  | "scored_witness_verified"
  | "scored_deterministic_baseline"
  | "excluded_chronology_claimed_only"
  | "excluded_chronology_unverified"
  | "excluded_chronology_violated"
  | "excluded_condition_not_satisfied"
  | "excluded_contract_violation"
  | "excluded_missing_distribution"
  | "excluded_unverified_run"
  | "unresolved";

const SCORE_CARRYING_ELIGIBILITIES: ReadonlySet<BrierScoreEligibility> =
  new Set(["scored_witness_verified", "scored_deterministic_baseline"]);

export interface BrierRewardRow {
  schemaVersion: "brier_reward_row_v1";
  runId: string;
  predictionId: string;
  specId: string;
  dataPointId?: string;
  split: BrierEvalSplit;
  scoreEligibility: BrierScoreEligibility;
  agent?: string;
  model?: string;
  runLabel: string;
  runVariantId: string;
  runAt?: string;
  /** Present on open-challenge rows: the external submitter's identity. */
  externalSubmission?: ExternalSubmissionAttribution;
  distributionProvenance: DistributionProvenance;
  transformVersion: string;
  resolutionDate: string;
  horizonDaysAtRun?: number;
  reward: {
    objective: "minimize_normalized_crps";
    value: number | null;
    components: {
      crps: number | null;
      normalizedCrps: number | null;
      absoluteError: number | null;
      normalizedAbsoluteError: number | null;
      sharpness: number | null;
      normalizationScale: number | null;
      normalizationScaleSource: "ledger_dispersion" | "unavailable" | null;
      interval80Covered: boolean | null;
    };
  };
  auxiliaryJudges: {
    rewardEligible: false;
    traceJudgeId?: string;
    traceQualityScore: number | null;
    postResolutionJudgeId?: string;
    primaryFailureMode?: ForecastResolutionFailureMode;
  };
  preSubmitReview: {
    status: string;
    reviewed: boolean;
    findingCount: number;
    acceptedCount: number;
    blockingFindingCount: number;
  };
  provenance: {
    specVersionId: string;
    promptHash?: string;
    toolPolicyHash?: string;
    inputBundleHash?: string;
    scoreId?: string;
    resolutionEventId?: string;
    ledgerFactRef?: string;
    custodyRootSha256?: string;
    aggregationAlgorithmVersion?: string;
    constituentRuns?: PredictionRunRecord["constituentRuns"];
    activityArtifactCount: number;
  };
}

export interface BrierAgentLeaderboardRow {
  agent: string;
  model?: string;
  /** True when every run in the group is an open-challenge submission. */
  external: boolean;
  /** Self-declared system types present in an external group's rows. */
  externalSystemTypes?: ExternalSubmissionAttribution["systemType"][];
  scoredRuns: number;
  totalRuns: number;
  unpairedMeanReward: number | null;
  unpairedMeanNormalizedCrps: number | null;
  unpairedMeanAbsoluteError: number | null;
  unpairedInterval80Coverage: number | null;
  pairedTargets: number;
  // Geometric mean of per-target raw CRPS ratios (agent / paired
  // persistence baseline). Scale-free by construction: the baseline is
  // ledger-derived and shares the target's units and outcome, so no
  // normalization denominator — and nothing any forecast authors — can
  // move the statistic (re-audit X2/N5). Below 1 beats persistence.
  pairedCrpsRatioGeomean: number | null;
  pairedWinRate: number | null;
  activityArtifactCoverage: number;
}

export interface BrierBaselineCoverageRow {
  predictionId: string;
  primaryRunId: string;
  status: "available" | "unavailable";
  cutoff: string;
  targetDataPointId?: string;
  seriesId?: string;
  observationRefs: NonNullable<
    ForecastCell["persistenceBaseline"]
  >["observationRefs"];
  reason?: string;
}

export interface BrierPairedComparisonSummary {
  pairedTargets: number;
  // Geometric mean of per-target raw CRPS ratios (primary agent run /
  // paired persistence baseline); below 1 beats persistence. Pairs where
  // either side's CRPS is exactly zero cannot form a ratio and are
  // reported separately (they still count in the win rate).
  crpsRatioGeomean: number | null;
  agentWinRate: number | null;
  zeroCrpsPairs: number;
}

interface NormalizationScaleCandidate {
  normalizationScale: number | null;
  normalizationScaleSource: "ledger_dispersion" | "unavailable" | null;
}

export function hasUsableNormalizationScale(
  score: NormalizationScaleCandidate,
): boolean {
  const scale = score.normalizationScale;
  // Equal decimal step changes can leave a positive sub-epsilon deviation in
  // binary floating point; that is zero usable dispersion, not a denominator.
  return (
    score.normalizationScaleSource === "ledger_dispersion" &&
    scale !== null &&
    Number.isFinite(scale) &&
    scale > Number.EPSILON
  );
}

export function isNormalizedScoreAggregateEligible(
  score: ResolvedForecastScore,
): score is ResolvedForecastScore & {
  normalizationScale: number;
  normalizedCrps: number;
  sharpness: number;
} {
  return (
    score.normalizationScaleObservationCount >= 3 &&
    hasUsableNormalizationScale(score) &&
    isNumber(score.normalizedCrps) &&
    isNumber(score.sharpness)
  );
}

export function summarizeNormalizedScores(scores: ResolvedForecastScore[]) {
  const eligibleScores = scores.filter(isNormalizedScoreAggregateEligible);
  return {
    eligibleScores,
    meanNormalizedCrps: mean(
      eligibleScores.map((score) => score.normalizedCrps).filter(isNumber),
    ),
    meanSharpness: mean(
      eligibleScores.map((score) => score.sharpness).filter(isNumber),
    ),
  };
}

export interface BrierRewardExport {
  schemaVersion: "brier_reward_export_v2";
  generatedAt: string;
  mission: {
    agent: "Brier";
    objective: "maximize_forecast_accuracy";
    reward: "negative_normalized_crps";
    constraints: string[];
  };
  counts: {
    specs: number;
    runs: number;
    scoredRuns: number;
    rawScoredRuns: number;
    unresolvedRuns: number;
    agents: number;
    traceJudgedRuns: number;
    postResolutionJudgeRows: number;
    preSubmitReviewedRuns: number;
    baselineTargets: number;
    availableBaselines: number;
    unavailableBaselines: number;
    pairedTargets: number;
  };
  splits: Record<
    BrierEvalSplit,
    {
      runs: number;
      scoredRuns: number;
      rule: string;
    }
  >;
  noLeakagePolicy: {
    rule: string;
    trainingEligibleSplits: BrierEvalSplit[];
    holdoutSplits: BrierEvalSplit[];
  };
  judgePolicy: {
    role: "auxiliary_process_eval";
    rewardEligible: false;
    calibrationRule: string;
  };
  leaderboard: BrierAgentLeaderboardRow[];
  pairedComparison: BrierPairedComparisonSummary;
  baselineCoverage: BrierBaselineCoverageRow[];
  rewardRows: BrierRewardRow[];
  judgeResults: ForecastJudgeExport;
}

export function buildBrierRewardExport({
  forecasts,
  specs,
  runs,
  ledger,
  generatedAt = "2026-06-16T00:00:00Z",
}: {
  forecasts: ForecastCell[];
  specs: PredictionSpec[];
  runs: PredictionRunRecord[];
  ledger: PolicyEngineLedgerEntry[];
  generatedAt?: string;
}): BrierRewardExport {
  // Callers may supply the raw catalog: publication verification is a boundary
  // of the export itself, so prototypes cannot become even unscored training
  // or evaluation examples through a less careful route.
  const preparedForecasts = withResolvedOutcomes(
    filterPublishedForecasts(forecasts),
    ledger,
  );
  const publishedIds = new Set(
    preparedForecasts.map((forecast) => forecast.slug),
  );
  const publishedSpecs = specs.filter((spec) =>
    publishedIds.has(spec.predictionId),
  );
  const suppliedRunsById = new Map(runs.map((run) => [run.runId, run]));
  for (const run of buildRecordedPredictionRunRecords(
    preparedForecasts,
    publishedSpecs,
  )) {
    suppliedRunsById.set(run.runId, run);
  }
  const preparedRuns = [...suppliedRunsById.values()];
  // Judges are auxiliary process diagnostics (never reward), so they read
  // the published verified-chronology population — claimed-time or better.
  // Reward and leaderboard rows tighten further: score components attach
  // only to witness-verified runs and the deterministic paired baseline.
  const scores = scoreResolvedForecasts(preparedForecasts, ledger).filter(
    (score) => hasVerifiedClaimedChronology(score.chronology),
  );
  const judgeResults = buildForecastJudgeExport({
    forecasts: preparedForecasts,
    scores,
  });
  const traceJudgeByRunId = new Map(
    judgeResults.traceQuality.map((judge) => [judge.runId, judge]),
  );
  const postResolutionJudgeByRunId = new Map(
    judgeResults.postResolution.map((judge) => [judge.runId, judge]),
  );
  const specByPredictionId = new Map(
    publishedSpecs.map((spec) => [spec.predictionId, spec]),
  );
  const runByRunId = new Map(preparedRuns.map((run) => [run.runId, run]));
  const rewardRows = preparedForecasts.flatMap((forecast) => {
    const spec = specByPredictionId.get(forecast.slug);
    const resolved = Boolean(getResolutionForForecast(forecast, ledger));
    return getForecastRunEntries(forecast)
      .filter((run) => isScoreEligibleForecastRun(forecast, run, ledger))
      .map((run) => {
        const runId = buildRecordedPredictionRunId(
          forecast,
          run.predictionRun?.runAt,
          run.variantId,
          run,
        );
        const evaluation = evaluateResolvedForecastRun(forecast, run, ledger);
        const scoreEligibility = rewardEligibilityFor(
          evaluation,
          resolved,
          run.variantId === TIME_SERIES_PRIOR_VARIANT_ID &&
            run.predictionRun?.agent === PERSISTENCE_BASELINE_AGENT,
        );
        const score = SCORE_CARRYING_ELIGIBILITIES.has(scoreEligibility)
          ? evaluation.score
          : undefined;
        const runRecord = runByRunId.get(runId);
        // Splits describe RESOLUTION state; integrity exclusions are the
        // scoreEligibility field's job (re-audit X9: resolved-but-excluded
        // rows previously landed in "unresolved").
        const split = getBrierEvalSplit(forecast, resolved);
        return buildRewardRow({
          forecast,
          run,
          runId,
          spec,
          score,
          scoreEligibility,
          runRecord,
          split,
          traceJudge: traceJudgeByRunId.get(runId),
          postResolutionJudge: postResolutionJudgeByRunId.get(runId),
        });
      });
  });
  const leaderboard = buildBrierAgentLeaderboard(rewardRows);
  const primaryVariants = new Map(
    preparedForecasts.map((forecast) => [
      forecast.slug,
      forecast.primaryVariantId ?? "primary",
    ]),
  );
  const pairedComparison = summarizePairedComparison(
    rewardRows.filter((row) => {
      return row.runVariantId === primaryVariants.get(row.predictionId);
    }),
    rewardRows.filter((row) => row.agent === PERSISTENCE_BASELINE_AGENT),
  );
  const baselineCoverage = preparedForecasts.flatMap((forecast) => {
    const baseline = forecast.persistenceBaseline;
    if (!baseline) return [];
    const primary = getForecastRunEntries(forecast)[0];
    if (!primary) return [];
    return [
      {
        predictionId: forecast.slug,
        primaryRunId: buildRecordedPredictionRunId(
          forecast,
          primary.predictionRun?.runAt,
          primary.variantId,
          primary,
        ),
        ...baseline,
      },
    ];
  });

  return {
    schemaVersion: "brier_reward_export_v2",
    generatedAt,
    mission: {
      agent: "Brier",
      objective: "maximize_forecast_accuracy",
      reward: "negative_normalized_crps",
      constraints: [
        "agent-only forecasts",
        "public statistical series with predictable first-print resolution",
        "immutable run artifacts",
        "proper scoring rules",
        "holdout splits by resolution date",
      ],
    },
    counts: {
      specs: publishedSpecs.length,
      runs: rewardRows.length,
      scoredRuns: rewardRows.filter((row) => row.reward.value !== null).length,
      rawScoredRuns: rewardRows.filter(
        (row) => row.reward.components.crps !== null,
      ).length,
      unresolvedRuns: rewardRows.filter((row) => row.split === "unresolved")
        .length,
      agents: leaderboard.length,
      traceJudgedRuns: judgeResults.traceQuality.length,
      postResolutionJudgeRows: judgeResults.postResolution.length,
      preSubmitReviewedRuns: rewardRows.filter(
        (row) => row.preSubmitReview.reviewed,
      ).length,
      baselineTargets: baselineCoverage.length,
      availableBaselines: baselineCoverage.filter(
        (row) => row.status === "available",
      ).length,
      unavailableBaselines: baselineCoverage.filter(
        (row) => row.status === "unavailable",
      ).length,
      pairedTargets: pairedComparison.pairedTargets,
    },
    splits: buildSplitSummary(rewardRows),
    noLeakagePolicy: {
      rule: "Rows are split by resolutionDate, not run order. Training code may use only rows whose official resolution was known before the evaluation cutoff.",
      trainingEligibleSplits: ["train"],
      holdoutSplits: ["validation", "test"],
    },
    judgePolicy: {
      role: "auxiliary_process_eval",
      rewardEligible: false,
      calibrationRule:
        "Judge scores can be used as process diagnostics only after checking whether they predict held-out normalized CRPS. They must not replace the proper-score reward.",
    },
    leaderboard,
    pairedComparison,
    baselineCoverage,
    rewardRows,
    judgeResults,
  };
}

export function getBrierEvalSplit(
  forecast: ForecastCell,
  resolved: boolean,
): BrierEvalSplit {
  if (!resolved) return "unresolved";
  if (forecast.resolutionDate < "2026-07-01") return "train";
  if (forecast.resolutionDate < "2027-01-01") return "validation";
  return "test";
}

function rewardEligibilityFor(
  evaluation: ForecastRunScoreEvaluation,
  resolved: boolean,
  reconstructedBaseline: boolean,
): BrierScoreEligibility {
  if (evaluation.score) {
    switch (evaluation.score.chronology) {
      case "witness_verified":
        return "scored_witness_verified";
      case "claimed_time_verified":
        // The persistence baseline is a replayable pure function of
        // pre-cutoff ledger data — it has no custody root to witness, and
        // it only ever pairs against a witness-verified agent row.
        return reconstructedBaseline
          ? "scored_deterministic_baseline"
          : "excluded_chronology_claimed_only";
      case "violated":
        return "excluded_chronology_violated";
      default:
        return "excluded_chronology_unverified";
    }
  }
  switch (evaluation.exclusion?.reason) {
    case "unverified_run":
      return "excluded_unverified_run";
    case "condition_not_satisfied":
      return "excluded_condition_not_satisfied";
    case "contract_violation":
      return "excluded_contract_violation";
    case "missing_distribution":
      // A run with no distribution can't score either way; the primary
      // fact about an unresolved target is still that it's unresolved.
      return resolved ? "excluded_missing_distribution" : "unresolved";
    default:
      return "unresolved";
  }
}

function buildRewardRow({
  forecast,
  run,
  runId,
  spec,
  score,
  scoreEligibility,
  runRecord,
  split,
  traceJudge,
  postResolutionJudge,
}: {
  forecast: ForecastCell;
  run: ReturnType<typeof getForecastRunEntries>[number];
  runId: string;
  spec?: PredictionSpec;
  score?: ResolvedForecastScore;
  scoreEligibility: BrierScoreEligibility;
  runRecord?: PredictionRunRecord;
  split: BrierEvalSplit;
  traceJudge?: ForecastJudgeExport["traceQuality"][number];
  postResolutionJudge?: ForecastJudgeExport["postResolution"][number];
}): BrierRewardRow {
  return {
    schemaVersion: "brier_reward_row_v1",
    runId,
    predictionId: forecast.slug,
    specId: spec?.specId ?? `spec.${forecast.slug}`,
    dataPointId: forecast.dataPointId,
    split,
    scoreEligibility,
    agent: run.predictionRun?.agent,
    model: run.predictionRun?.model,
    runLabel: run.label,
    runVariantId: run.variantId,
    runAt: run.predictionRun?.runAt,
    externalSubmission: run.externalSubmission,
    distributionProvenance: run.predictionDistribution.provenance,
    transformVersion: getDistributionTransformVersion(
      run.predictionDistribution,
    ),
    resolutionDate: forecast.resolutionDate,
    horizonDaysAtRun: getHorizonDaysAtRun(run.predictionRun?.runAt, forecast),
    reward: {
      objective: "minimize_normalized_crps",
      value:
        score?.normalizedCrps === null || score?.normalizedCrps === undefined
          ? null
          : -score.normalizedCrps,
      components: {
        crps: score?.crps ?? null,
        normalizedCrps: score?.normalizedCrps ?? null,
        absoluteError: score?.absoluteError ?? null,
        normalizedAbsoluteError: score?.normalizedAbsoluteError ?? null,
        sharpness: score?.sharpness ?? null,
        normalizationScale: score?.normalizationScale ?? null,
        normalizationScaleSource: score?.normalizationScaleSource ?? null,
        interval80Covered: score?.interval80Covered ?? null,
      },
    },
    auxiliaryJudges: {
      rewardEligible: false,
      traceJudgeId: traceJudge?.judgeId,
      traceQualityScore: traceJudge?.overallScore ?? null,
      postResolutionJudgeId: postResolutionJudge?.judgeId,
      primaryFailureMode: postResolutionJudge?.primaryFailureMode,
    },
    preSubmitReview: summarizePreSubmitReview(
      run.predictionRun?.preSubmitReview,
    ),
    provenance: {
      specVersionId: spec?.specVersionId ?? `spec.${forecast.slug}.v1`,
      promptHash: runRecord?.promptHash,
      toolPolicyHash: runRecord?.toolPolicyHash,
      inputBundleHash: runRecord?.inputBundleHash,
      scoreId: score?.scoreId,
      resolutionEventId: score?.resolutionEventId,
      ledgerFactRef: score?.ledgerFactRef,
      custodyRootSha256: run.predictionRun?.custodyRootSha256,
      aggregationAlgorithmVersion:
        run.predictionRun?.aggregationAlgorithmVersion,
      constituentRuns: run.predictionRun?.constituentRuns,
      activityArtifactCount: run.predictionRun?.activityLog?.length ?? 0,
    },
  };
}

function summarizePreSubmitReview(
  review?: PredictionPreSubmitReviewWorkflow,
): BrierRewardRow["preSubmitReview"] {
  const findings = review?.findings ?? [];
  const dispositions = review?.dispositions ?? [];
  return {
    status: review?.status ?? "not_requested",
    reviewed: review?.status === "completed",
    findingCount: findings.length,
    acceptedCount: dispositions.filter((disposition) =>
      ["accepted", "partially_accepted"].includes(disposition.decision),
    ).length,
    blockingFindingCount: findings.filter(
      (finding) => finding.severity === "blocking",
    ).length,
  };
}

export function buildBrierAgentLeaderboard(
  rows: BrierRewardRow[],
): BrierAgentLeaderboardRow[] {
  const groups = new Map<string, BrierRewardRow[]>();
  for (const row of rows) {
    const key = `${row.agent ?? "prototype seed"}\u0000${row.model ?? ""}`;
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }

  return [...groups.entries()]
    .map(([key, group]) => {
      const [agent, model] = key.split("\u0000");
      const externalRows = group.filter((row) =>
        Boolean(row.externalSubmission),
      );
      // A group mixing internal and external rows means one agent
      // identity is being used by both the lab and a challenger; that is
      // an integrity anomaly, not a display choice — fail the build.
      if (externalRows.length > 0 && externalRows.length < group.length) {
        throw new Error(
          `leaderboard group ${agent} mixes internal and external rows`,
        );
      }
      const external = externalRows.length === group.length && group.length > 0;
      const externalSystemTypes = external
        ? [
            ...new Set(
              externalRows.flatMap((row) =>
                row.externalSubmission
                  ? [row.externalSubmission.systemType]
                  : [],
              ),
            ),
          ].sort()
        : undefined;
      const rawScoredRows = group.filter(
        (row) => row.reward.components.crps !== null,
      );
      const scoredRows = group.filter(
        (row) =>
          hasUsableNormalizationScale(row.reward.components) &&
          isNumber(row.reward.components.normalizedCrps) &&
          isNumber(row.reward.components.sharpness),
      );
      const artifactRows = group.filter(
        (row) => row.provenance.activityArtifactCount > 0,
      );
      const paired =
        agent === PERSISTENCE_BASELINE_AGENT
          ? {
              pairedTargets: 0,
              pairedCrpsRatioGeomean: null,
              pairedWinRate: null,
            }
          : pairedCrpsRatiosForRows(rawScoredRows, rows).stats;
      return {
        agent,
        model: model || undefined,
        external,
        externalSystemTypes,
        scoredRuns: rawScoredRows.length,
        totalRuns: group.length,
        unpairedMeanReward: mean(
          scoredRows.map((row) => row.reward.value).filter(isNumber),
        ),
        unpairedMeanNormalizedCrps: mean(
          scoredRows
            .map((row) => row.reward.components.normalizedCrps)
            .filter(isNumber),
        ),
        unpairedMeanAbsoluteError: mean(
          rawScoredRows
            .map((row) => row.reward.components.absoluteError)
            .filter(isNumber),
        ),
        unpairedInterval80Coverage: mean(
          rawScoredRows
            .map((row) => row.reward.components.interval80Covered)
            .filter((value): value is boolean => typeof value === "boolean")
            .map((covered) => (covered ? 1 : 0)),
        ),
        ...paired,
        activityArtifactCoverage:
          group.length === 0 ? 0 : artifactRows.length / group.length,
      };
    })
    .sort((left, right) => {
      const leftRatio = left.pairedCrpsRatioGeomean ?? Number.POSITIVE_INFINITY;
      const rightRatio =
        right.pairedCrpsRatioGeomean ?? Number.POSITIVE_INFINITY;
      if (leftRatio !== rightRatio) return leftRatio - rightRatio;
      const leftReward = left.unpairedMeanReward ?? Number.NEGATIVE_INFINITY;
      const rightReward = right.unpairedMeanReward ?? Number.NEGATIVE_INFINITY;
      if (leftReward !== rightReward) return rightReward - leftReward;
      return right.scoredRuns - left.scoredRuns;
    });
}

// The headline agent-vs-baseline statistic is a per-target RAW CRPS ratio
// against the paired ledger persistence baseline. Both sides score the
// same outcome in the same units, so the target's scale cancels: no
// normalization denominator exists for a forecast to game (re-audit X2
// killed the forecast-width fallback; N5 demanded a scale no forecast
// controls). Geometric mean is the right aggregate for ratios; the win
// rate counts strictly-better pairs.
function pairedCrpsRatiosForRows(
  agentRows: BrierRewardRow[],
  allRows: BrierRewardRow[],
) {
  const baselineByTarget = new Map<string, number>();
  for (const row of allRows) {
    const crps = row.reward.components.crps;
    if (row.agent === PERSISTENCE_BASELINE_AGENT && crps !== null) {
      baselineByTarget.set(row.predictionId, crps);
    }
  }
  const agentScoresByTarget = new Map<string, number[]>();
  for (const row of agentRows) {
    const crps = row.reward.components.crps;
    if (crps === null || !baselineByTarget.has(row.predictionId)) continue;
    agentScoresByTarget.set(row.predictionId, [
      ...(agentScoresByTarget.get(row.predictionId) ?? []),
      crps,
    ]);
  }
  let wins = 0;
  let zeroCrpsPairs = 0;
  const logRatios: number[] = [];
  for (const [predictionId, agentScores] of agentScoresByTarget) {
    const baselineCrps = baselineByTarget.get(predictionId);
    const agentCrps = mean(agentScores);
    if (baselineCrps === undefined || agentCrps === null) continue;
    if (agentCrps < baselineCrps) wins += 1;
    if (agentCrps > 0 && baselineCrps > 0) {
      logRatios.push(Math.log(agentCrps / baselineCrps));
    } else {
      zeroCrpsPairs += 1;
    }
  }
  const pairedTargets = agentScoresByTarget.size;
  return {
    stats: {
      pairedTargets,
      pairedCrpsRatioGeomean:
        logRatios.length === 0
          ? null
          : Math.exp(
              logRatios.reduce((total, value) => total + value, 0) /
                logRatios.length,
            ),
      pairedWinRate: pairedTargets === 0 ? null : wins / pairedTargets,
    },
    zeroCrpsPairs,
  };
}

export function summarizePairedComparison(
  agentRows: BrierRewardRow[],
  baselineRows: BrierRewardRow[],
): BrierPairedComparisonSummary {
  const paired = pairedCrpsRatiosForRows(agentRows, baselineRows);
  return {
    pairedTargets: paired.stats.pairedTargets,
    crpsRatioGeomean: paired.stats.pairedCrpsRatioGeomean,
    agentWinRate: paired.stats.pairedWinRate,
    zeroCrpsPairs: paired.zeroCrpsPairs,
  };
}

function buildSplitSummary(
  rows: BrierRewardRow[],
): BrierRewardExport["splits"] {
  return {
    train: summarizeSplit(rows, "train", "Resolved before 2026-07-01."),
    validation: summarizeSplit(
      rows,
      "validation",
      "Resolved from 2026-07-01 through 2026-12-31.",
    ),
    test: summarizeSplit(rows, "test", "Resolved on or after 2027-01-01."),
    unresolved: summarizeSplit(
      rows,
      "unresolved",
      "Not eligible for reward until the first-print resolver posts a fact.",
    ),
  };
}

function summarizeSplit(
  rows: BrierRewardRow[],
  split: BrierEvalSplit,
  rule: string,
) {
  const splitRows = rows.filter((row) => row.split === split);
  return {
    runs: splitRows.length,
    scoredRuns: splitRows.filter((row) => row.reward.value !== null).length,
    rule,
  };
}

function getHorizonDaysAtRun(
  runAt: string | undefined,
  forecast: ForecastCell,
): number | undefined {
  if (!runAt) return undefined;
  const runTime = Date.parse(runAt);
  const resolutionTime = Date.parse(`${forecast.resolutionDate}T00:00:00Z`);
  if (!Number.isFinite(runTime) || !Number.isFinite(resolutionTime)) {
    return undefined;
  }
  return Math.round((resolutionTime - runTime) / 86_400_000);
}

function mean(values: number[]) {
  if (values.length === 0) return null;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function summarizeBrierCoverage({
  forecasts,
  ledger,
}: {
  forecasts: ForecastCell[];
  ledger: PolicyEngineLedgerEntry[];
}) {
  const recorded = buildPredictionRecordedLogEntries(forecasts);
  const resolved = buildResolvedPredictionLogEntries(forecasts, ledger);
  const scored = scoreResolvedForecasts(forecasts, ledger).filter((score) =>
    hasVerifiedClaimedChronology(score.chronology),
  );
  return {
    recordedRuns: recorded.length,
    resolvedEvents: resolved.length,
    scoredRuns: scored.length,
    activityLoggedRuns: recorded.filter((entry) => entry.activityLog?.length)
      .length,
  };
}
