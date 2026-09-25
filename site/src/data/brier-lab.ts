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
  /** Targets where this agent and the persistence baseline both carry raw CRPS. */
  pairedTargets: number;
  /** The paired targets with a usable ledger scale: the ranking population. */
  pairedNormalizedTargets: number;
  // The ranking statistic (see leaderboardRankingStatistic): the mean over
  // pairedNormalizedTargets of (this agent's mean normalized CRPS on the
  // target - the persistence baseline's). Below 0 beats persistence.
  pairedNormalizedCrpsDelta: number | null;
  /** Sample SD of the per-target deltas over sqrt(n); null below two targets. */
  pairedNormalizedCrpsDeltaStdError: number | null;
  // Share of pairedTargets where the agent's mean raw CRPS is strictly
  // below persistence. Descriptive only: a win rate is not a proper score,
  // so it never orders the leaderboard.
  pairedWinRate: number | null;
  activityArtifactCoverage: number;
}

// Agents choose their own targets, so two leaderboard rows are usually
// scored on different target sets; each row's delta is against persistence
// on that row's own targets. A direct agent-vs-agent comparison is only
// meaningful on the targets both forecast, which is what these rows carry.
export interface BrierHeadToHeadRow {
  /** The higher-ranked side. */
  left: { agent: string; model?: string };
  right: { agent: string; model?: string };
  /** Targets both sides scored with a usable ledger scale. */
  sharedTargets: number;
  /** Mean per-target normalized CRPS, left minus right; below 0 favors left. */
  meanNormalizedCrpsDifference: number;
  stdError: number | null;
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
  /** Paired targets with a usable ledger scale. */
  normalizedTargets: number;
  // Mean per-target normalized CRPS of the primary agent runs minus the
  // paired persistence baseline's, over normalizedTargets; below 0 beats
  // persistence. Same statistic as the leaderboard's ranking key.
  normalizedCrpsDelta: number | null;
  normalizedCrpsDeltaStdError: number | null;
  /** Descriptive: share of pairedTargets where raw CRPS beats persistence. */
  agentWinRate: number | null;
}

interface NormalizationScaleCandidate {
  normalizationScale: number | null;
  normalizationScaleSource: "ledger_dispersion" | "unavailable" | null;
}

export function hasUsableNormalizationScale(
  score: NormalizationScaleCandidate,
): boolean {
  const scale = score.normalizationScale;
  // Float residue from equal decimal steps is refused where the scale is
  // computed (targetNormalizationScale), relative to the history's own
  // magnitude — the only place that magnitude is known. The absolute
  // Number.EPSILON bound this predicate used to apply was the wrong rule:
  // a linear series near 215 leaves a 2.0e-14 residue that passed it.
  return (
    score.normalizationScaleSource === "ledger_dispersion" &&
    scale !== null &&
    Number.isFinite(scale) &&
    scale > 0
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
  schemaVersion: "brier_reward_export_v3";
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
  headToHead: BrierHeadToHeadRow[];
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
  const headToHead = buildBrierHeadToHead(rewardRows, leaderboard);
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
    schemaVersion: "brier_reward_export_v3",
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
    headToHead,
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
      // Reward exists only where the shared usable-scale predicate holds, so
      // no row can carry a normalized value its own aggregates would refuse
      // (the 2026-09-23 export published -7.08e13 on a residue scale).
      value:
        score &&
        hasUsableNormalizationScale(score) &&
        isNumber(score.normalizedCrps)
          ? -score.normalizedCrps
          : null,
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
              pairedNormalizedTargets: 0,
              pairedNormalizedCrpsDelta: null,
              pairedNormalizedCrpsDeltaStdError: null,
              pairedWinRate: null,
            }
          : pairedPersistenceStats(rawScoredRows, rows);
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
      const leftDelta =
        leaderboardRankingStatistic(left) ?? Number.POSITIVE_INFINITY;
      const rightDelta =
        leaderboardRankingStatistic(right) ?? Number.POSITIVE_INFINITY;
      if (leftDelta !== rightDelta) return leftDelta - rightDelta;
      // Also proper: the unpaired mean reward is linear in each CRPS too.
      const leftReward = left.unpairedMeanReward ?? Number.NEGATIVE_INFINITY;
      const rightReward = right.unpairedMeanReward ?? Number.NEGATIVE_INFINITY;
      if (leftReward !== rightReward) return rightReward - leftReward;
      return right.scoredRuns - left.scoredRuns;
    });
}

// What orders the leaderboard, lowest first. It must stay proper: in
// expectation, reporting one's true belief minimizes it on every target,
// which leaderboard-propriety.test.ts checks through the real kernel and
// this function. The mean paired normalized-CRPS difference qualifies
// because it is LINEAR in each CRPS with weights (1 / scale, per target
// and run count) fixed before the outcome and untouched by the report,
// and CRPS itself is proper. The geometric mean of raw CRPS ratios it
// replaces was not: it minimizes E[log CRPS], whose optimal Gaussian
// "80%" interval is 0.39x the truthful width (38% coverage) whatever the
// baseline. Ratio-of-means and mean-of-ratios are improper at small n
// too, because the baseline's realized CRPS in the denominator reweights
// outcomes.
export function leaderboardRankingStatistic(
  row: Pick<BrierAgentLeaderboardRow, "pairedNormalizedCrpsDelta">,
): number | null {
  return row.pairedNormalizedCrpsDelta;
}

// Normalized CRPS a row may contribute to a paired statistic: only under
// the same usable-scale rule that gates its reward.
function usableNormalizedCrps(row: BrierRewardRow): number | null {
  const { normalizedCrps } = row.reward.components;
  return hasUsableNormalizationScale(row.reward.components) &&
    isNumber(normalizedCrps)
    ? normalizedCrps
    : null;
}

// Per-target means of a row set's usable normalized CRPS. A target counts
// only when every one of its rows has one: the scale is per dataPointId,
// so a partial set would mean the rows disagree about the target's scale.
function normalizedCrpsByTarget(rows: BrierRewardRow[]) {
  const rowsByTarget = new Map<string, BrierRewardRow[]>();
  for (const row of rows) {
    rowsByTarget.set(row.predictionId, [
      ...(rowsByTarget.get(row.predictionId) ?? []),
      row,
    ]);
  }
  const byTarget = new Map<string, number>();
  for (const [predictionId, targetRows] of rowsByTarget) {
    const values = targetRows.map(usableNormalizedCrps);
    if (values.every(isNumber)) {
      byTarget.set(predictionId, mean(values as number[])!);
    }
  }
  return byTarget;
}

// Pairs an agent's rows with the ledger persistence baseline on each
// target they share. Averaging the agent's runs within a target first
// weights targets equally, so repeat runs on one target cannot outweigh
// the rest. The win rate compares raw CRPS on the same outcome in the
// same units, so it needs no scale.
function pairedPersistenceStats(
  agentRows: BrierRewardRow[],
  allRows: BrierRewardRow[],
) {
  const baselineByTarget = new Map<string, BrierRewardRow>();
  for (const row of allRows) {
    if (
      row.agent === PERSISTENCE_BASELINE_AGENT &&
      row.reward.components.crps !== null
    ) {
      baselineByTarget.set(row.predictionId, row);
    }
  }
  const pairedRows = agentRows.filter(
    (row) =>
      row.reward.components.crps !== null &&
      baselineByTarget.has(row.predictionId),
  );
  const agentCrpsByTarget = new Map<string, number[]>();
  for (const row of pairedRows) {
    agentCrpsByTarget.set(row.predictionId, [
      ...(agentCrpsByTarget.get(row.predictionId) ?? []),
      row.reward.components.crps as number,
    ]);
  }
  let wins = 0;
  for (const [predictionId, agentScores] of agentCrpsByTarget) {
    const baselineCrps =
      baselineByTarget.get(predictionId)!.reward.components.crps!;
    if (mean(agentScores)! < baselineCrps) wins += 1;
  }
  const agentNormalized = normalizedCrpsByTarget(pairedRows);
  const deltas: number[] = [];
  for (const [predictionId, agentValue] of agentNormalized) {
    const baselineValue = usableNormalizedCrps(
      baselineByTarget.get(predictionId)!,
    );
    if (baselineValue !== null) deltas.push(agentValue - baselineValue);
  }
  const pairedTargets = agentCrpsByTarget.size;
  return {
    pairedTargets,
    pairedNormalizedTargets: deltas.length,
    pairedNormalizedCrpsDelta: mean(deltas),
    pairedNormalizedCrpsDeltaStdError: standardError(deltas),
    pairedWinRate: pairedTargets === 0 ? null : wins / pairedTargets,
  };
}

export function summarizePairedComparison(
  agentRows: BrierRewardRow[],
  baselineRows: BrierRewardRow[],
): BrierPairedComparisonSummary {
  const paired = pairedPersistenceStats(agentRows, baselineRows);
  return {
    pairedTargets: paired.pairedTargets,
    normalizedTargets: paired.pairedNormalizedTargets,
    normalizedCrpsDelta: paired.pairedNormalizedCrpsDelta,
    normalizedCrpsDeltaStdError: paired.pairedNormalizedCrpsDeltaStdError,
    agentWinRate: paired.pairedWinRate,
  };
}

// Every pair of forecasters (persistence excluded: the leaderboard already
// pairs everyone with it) compared only on the targets both scored with a
// usable scale, each side averaged within target first. Pairs follow
// leaderboard order, so "left" is the higher-ranked side.
export function buildBrierHeadToHead(
  rows: BrierRewardRow[],
  leaderboard: BrierAgentLeaderboardRow[],
): BrierHeadToHeadRow[] {
  const groupKey = (agent: string | undefined, model: string | undefined) =>
    `${agent ?? "prototype seed"}\u0000${model ?? ""}`;
  const normalizedByGroup = new Map<string, Map<string, number>>();
  const rowsByGroup = new Map<string, BrierRewardRow[]>();
  for (const row of rows) {
    if (row.agent === PERSISTENCE_BASELINE_AGENT) continue;
    if (row.reward.components.crps === null) continue;
    const key = groupKey(row.agent, row.model);
    rowsByGroup.set(key, [...(rowsByGroup.get(key) ?? []), row]);
  }
  for (const [key, groupRows] of rowsByGroup) {
    normalizedByGroup.set(key, normalizedCrpsByTarget(groupRows));
  }
  const ranked = leaderboard.filter((row) =>
    normalizedByGroup.has(groupKey(row.agent, row.model)),
  );
  const pairs: BrierHeadToHeadRow[] = [];
  for (let leftIndex = 0; leftIndex < ranked.length; leftIndex += 1) {
    for (
      let rightIndex = leftIndex + 1;
      rightIndex < ranked.length;
      rightIndex += 1
    ) {
      const left = ranked[leftIndex];
      const right = ranked[rightIndex];
      const leftValues = normalizedByGroup.get(
        groupKey(left.agent, left.model),
      )!;
      const rightValues = normalizedByGroup.get(
        groupKey(right.agent, right.model),
      )!;
      const differences = [...leftValues.keys()]
        .filter((predictionId) => rightValues.has(predictionId))
        .sort()
        .map(
          (predictionId) =>
            leftValues.get(predictionId)! - rightValues.get(predictionId)!,
        );
      if (differences.length === 0) continue;
      pairs.push({
        left: { agent: left.agent, model: left.model },
        right: { agent: right.agent, model: right.model },
        sharedTargets: differences.length,
        meanNormalizedCrpsDifference: mean(differences)!,
        stdError: standardError(differences),
      });
    }
  }
  return pairs;
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

// Standard error of a mean of independent per-target values: the sample
// SD (n - 1) over sqrt(n). One target has no spread to estimate from.
function standardError(values: number[]) {
  if (values.length < 2) return null;
  const center = mean(values)!;
  const variance =
    values.reduce((total, value) => total + (value - center) ** 2, 0) /
    (values.length - 1);
  return Math.sqrt(variance / values.length);
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
