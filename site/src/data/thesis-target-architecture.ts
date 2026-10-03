import type {
  CountryCode,
  ForecastCell,
  ForecastRunEntry,
  PredictionCadence,
  PredictionPackReference,
  ResolutionPolicy,
  Unit,
} from "./forecast-cells";
import { getForecastRunEntries } from "./forecast-cells";
import {
  getDistributionTransformVersion,
  type DistributionProvenance,
} from "./prediction-distribution";
import {
  buildPredictionPackCatalog,
  buildPredictionPackVersionKey,
} from "./prediction-packs";
import {
  buildPredictionSpecs,
  buildRecordedPredictionRunRecords,
  type PredictionRunRecord,
  type PredictionSpec,
} from "./prediction-specs";
import { STRATEGY_REGISTRY } from "./strategy-lab";
import {
  buildForecastJudgeExport,
  type ForecastJudgeExport,
} from "./forecast-judges";
import {
  buildObservationResolutionEventId,
  getResolvedObservationForForecast,
  scoreResolvedForecasts,
  type ResolvedForecastScore,
  type ObservationRecordedLedgerEntry,
  type PolicyEngineLedgerEntry,
} from "./thesis-log";
import { sha256Hex } from "./canonical-json";

export interface ThesisTargetArchitectureProjection {
  schemaVersion: "thesis_target_architecture_projection_v1";
  generatedAt: string;
  source: {
    records: "forecast_cells";
  };
  counts: {
    targets: number;
    targetVersions: number;
    sourceSeries: number;
    observations: number;
    observationVintages: number;
    targetObservationBindings: number;
    baselineCandidates: number;
    forecastStrategies: number;
    strategyVersions: number;
    packs: number;
    packVersions: number;
    forecastRuns: number;
    runPackVersions: number;
    runArtifactRefs: number;
    toolCalls: number;
    forecastDistributionPoints: number;
    reasoningEvents: number;
    reviewRuns: number;
    judgeRuns: number;
    resolutionEvents: number;
    scores: number;
    artifactRefs: number;
  };
  targets: TargetProjection[];
  targetVersions: TargetVersionProjection[];
  sourceSeries: SourceSeriesProjection[];
  observations: ObservationProjection[];
  observationVintages: ObservationVintageProjection[];
  targetObservationBindings: TargetObservationBindingProjection[];
  baselineCandidates: BaselineCandidateProjection[];
  forecastStrategies: ForecastStrategyProjection[];
  strategyVersions: StrategyVersionProjection[];
  packs: PackProjection[];
  packVersions: PackVersionProjection[];
  forecastRuns: ForecastRunProjection[];
  runPackVersions: RunPackVersionProjection[];
  runArtifactRefs: RunArtifactRefProjection[];
  toolCalls: ToolCallProjection[];
  forecastDistributions: ForecastDistributionPointProjection[];
  reasoningEvents: ReasoningEventProjection[];
  reviewRuns: ReviewRunProjection[];
  judgeRuns: JudgeRunProjection[];
  resolutionEvents: ResolutionEventProjection[];
  scores: ScoreProjection[];
  artifactRefs: ArtifactRefProjection[];
}

export interface TargetArchitectureValidationIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
}

export interface TargetProjection {
  targetId: string;
  slug: string;
  dataPointId: string;
  country: CountryCode;
  agency?: string;
  sourceFamily: string;
  sourceUrl?: string;
  tags: string[];
  createdAt: string;
}

export interface TargetVersionProjection {
  targetVersionId: string;
  targetId: string;
  versionLabel: string;
  question: string;
  periodLabel: string;
  targetPeriod: string;
  unit: Unit;
  valueScale: number;
  scoringTransform?: string;
  resolverKind: ResolverKind;
  resolutionPolicy: ResolutionPolicy;
  resolutionDateBasis: ResolutionDateBasis;
  resolutionRule: string;
  resolutionSource: string;
  resolutionSourceUrl?: string;
  cdfPointCount: 201;
  publishedAt: string;
}

export interface SourceSeriesProjection {
  sourceSeriesId: string;
  adapterId: string;
  sourceFamily: string;
  agencySeriesId?: string;
  measureKey: string;
  country: CountryCode;
  agency?: string;
  sourceUrl: string;
  unit: Unit;
  updateCadence?: PredictionCadence;
  defaultVintagePolicy: ResolutionPolicy | "unknown";
}

export interface ObservationProjection {
  observationId: string;
  sourceSeriesId: string;
  dataPointId?: string;
  periodLabel: string;
  value: number;
  unit: Unit;
  valueScale: number;
  sourceUrl: string;
  retrievedAt: string;
  payloadHash: string;
}

export interface ObservationVintageProjection {
  vintageId: string;
  observationId: string;
  vintageKind: ResolutionPolicy | "unknown";
  publishedAt: string;
  retrievedAt: string;
  normalizedPayloadHash: string;
}

export interface TargetObservationBindingProjection {
  bindingId: string;
  targetVersionId: string;
  sourceSeriesId: string;
  bindingRole: "resolver" | "history";
  transformKind: "identity";
  adapterMethod: "official_release_lookup" | "historical_context";
}

export interface BaselineCandidateProjection {
  candidateId: string;
  targetVersionId: string;
  sourceSeriesId?: string;
  modelAdapter: string;
  candidateLabel: string;
  trainingCutoff: string;
  pointEstimate: number;
  p10?: number;
  p50: number;
  p90?: number;
  interval80Lower: number;
  interval80Upper: number;
  intervalMethod: string;
  calibrationSampleSize?: number;
  walkForwardScore?: number;
  assumptions?: string;
  failureModes: string[];
  artifactRefId?: string;
  provenance: {
    sourceRole: "run_artifact" | "source_series";
    forecastRunId: string;
  };
}

export interface ForecastStrategyProjection {
  strategyId: string;
  name: string;
  strategyKind: ForecastStrategyKind;
  description: string;
}

export interface StrategyVersionProjection {
  strategyVersionId: string;
  strategyId: string;
  versionLabel: string;
  promptPolicyHash?: string;
  toolPolicyHash?: string;
  requiredInputs: string[];
  modelFamilyConstraints: string[];
}

export interface PackProjection {
  packId: string;
  slug: string;
  name: string;
  targetFamilyTags: string[];
  ownerId: "thesis";
  createdAt: string;
}

export interface PackVersionProjection {
  packVersionId: string;
  packId: string;
  versionLabel: string;
  evidenceRequirements: string[];
  validatorRules: string[];
  promptContentHash: string;
  ablationPlan?: string;
}

export interface ForecastRunProjection {
  runId: string;
  targetVersionId: string;
  strategyVersionId: string;
  agentId: string;
  model?: string;
  runtime: string;
  promptHash: string;
  toolPolicyHash: string;
  inputBundleHash: string;
  status: "published" | "needs_review";
  idempotencyKey: string;
  runAt: string;
}

export interface RunPackVersionProjection {
  runPackVersionId: string;
  runId: string;
  packVersionId: string;
  packRole: "required" | "optional" | "comparison";
}

export interface RunArtifactRefProjection {
  runArtifactRefId: string;
  runId: string;
  artifactRefId: string;
  artifactRole: string;
  sequenceIndex: number;
}

export interface ToolCallProjection {
  toolCallId: string;
  runId: string;
  allowedToolDeclaration: string;
  toolName: string;
  requestHash: string;
  responseHash?: string;
  provider: string;
  status: "succeeded" | "failed";
  costUsd: number | null;
  influencedFinalForecast: boolean;
  sequenceIndex: number;
  sourceRole: "forecast_evidence";
}

export interface ForecastDistributionPointProjection {
  runId: string;
  pointIndex: number;
  value: number;
  probability: number;
  unit: Unit;
  intervalMass: 0.8;
  distributionProvenance: DistributionProvenance;
  transformVersion: string;
  validationStatus: "passed";
}

export interface ReasoningEventProjection {
  reasoningEventId: string;
  runId: string;
  sequenceIndex: number;
  eventKind: "assistant_message";
  publicText: string;
  artifactRefId?: string;
  redactionStatus: "public_only";
}

export interface ReviewRunProjection {
  reviewRunId: string;
  runId: string;
  reviewerAgentId: string;
  draftArtifactRefId?: string;
  findings: unknown[];
  revisionArtifactRefId?: string;
  disposition: "accepted" | "revised" | "rejected" | "no_change";
}

export interface JudgeRunProjection {
  judgeRunId: string;
  runId?: string;
  batchId?: string;
  leftRunId?: string;
  rightRunId?: string;
  judgeModel: string;
  promptVersion: string;
  findings: unknown[];
  recommendations: unknown[];
  rewardEligible: false;
}

export interface ResolutionEventProjection {
  resolutionEventId: string;
  targetVersionId: string;
  observationId: string;
  vintageId: string;
  resolvedValue: number;
  sourceUrl?: string;
  resolverProof: {
    dataPointId: string;
    observationId: string;
  };
  scoreableStatus: "scoreable";
  eventTimestamp: string;
}

export interface ScoreProjection {
  scoreId: string;
  runId: string;
  resolutionEventId: string;
  scoringRule: "numeric_cdf_crps_v3_ledger_scale";
  distributionProvenance: DistributionProvenance;
  transformVersion: string;
  crps: number;
  normalizationScale: number | null;
  normalizationScaleSource: "ledger_dispersion" | "target_primary_width" | "unavailable";
  normalizedScore: number | null;
  normalizedCrps: number | null;
  normalizedAbsoluteError: number | null;
  sharpness: number | null;
  probabilityIntegralTransform: number;
  interval80Covered: boolean;
  signedError: number;
  absoluteError: number;
  scoreHash: string;
  createdAt: string;
}

export interface ArtifactRefProjection {
  artifactRefId: string;
  contentHash: string;
  mediaType: string;
  storageUri: string;
  publicVisibility: "public";
  metadata: Record<string, unknown>;
}

type ResolverKind =
  | "public_release"
  | "policy_state"
  | "conditional_gate"
  | "formula_publication";

type ResolutionDateBasis =
  | "scheduled_release"
  | "policy_deadline"
  | "expected_first_post_window"
  | "unresolved_until_official_post";

type ForecastStrategyKind =
  | "llm_no_pack"
  | "llm_pack_informed"
  | "persistence_baseline"
  | "time_series_baseline"
  | "official_projection_anchor"
  | "formula_nowcast"
  | "reviewer_assisted_llm"
  | "meta_aggregator";

interface ForecastProjectionContext {
  forecast: ForecastCell;
  spec: PredictionSpec;
}

const PROJECTION_GENERATED_AT = "2026-06-29T00:00:00+00:00";
const VERSION_LABEL = "2026-06-09";

const CORE_STRATEGIES: ForecastStrategyProjection[] = [
  {
    strategyId: "agent.brier.no_pack",
    name: "Brier no-pack LLM",
    strategyKind: "llm_no_pack",
    description: "Recorded Brier agent run without optional forecasting packs.",
  },
  {
    strategyId: "agent.brier.pack_informed",
    name: "Brier pack-informed LLM",
    strategyKind: "llm_pack_informed",
    description:
      "Recorded Brier agent run with one or more typed forecasting packs.",
  },
  {
    strategyId: "agent.brier.meta_aggregator",
    name: "Brier meta-aggregator",
    strategyKind: "meta_aggregator",
    description:
      "Recorded Brier run that combines component strategies into a canonical forecast.",
  },
  {
    strategyId: "agent.prototype_seed",
    name: "Prototype seed",
    strategyKind: "llm_no_pack",
    description:
      "Seeded forecast-cell record used to bootstrap the first public target architecture projection.",
  },
  {
    strategyId: "baseline.official_projection.bls_employment_projections",
    name: "BLS Employment Projections anchor",
    strategyKind: "official_projection_anchor",
    description:
      "Deterministic comparison row from the official BLS Employment Projections release.",
  },
  {
    strategyId: "baseline.official_table.current_print",
    name: "Current official table carry-forward",
    strategyKind: "persistence_baseline",
    description:
      "Deterministic carry-forward baseline from the most recent official table value.",
  },
];

export function buildTargetArchitectureProjection(
  forecasts: ForecastCell[],
  ledger: PolicyEngineLedgerEntry[] = [],
): ThesisTargetArchitectureProjection {
  const specs = buildPredictionSpecs(forecasts);
  const runs = buildRecordedPredictionRunRecords(forecasts, specs);
  const contexts = forecasts.map((forecast, index) => ({
    forecast,
    spec: specs[index],
  }));
  const targetVersionsByLegacySpecVersionId = new Map(
    contexts.map(({ spec }) => [
      spec.specVersionId,
      buildTargetVersionId(spec.predictionId),
    ]),
  );
  const unitByLegacySpecVersionId = new Map(
    specs.map((spec) => [spec.specVersionId, spec.unit]),
  );
  const strategyVersionIdByStrategyId = new Map(
    buildForecastStrategies().map((strategy) => [
      strategy.strategyId,
      buildStrategyVersionId(strategy.strategyId),
    ]),
  );
  const targets = contexts.map(buildTargetProjection);
  const targetVersions = contexts.map(buildTargetVersionProjection);
  const sourceSeries = buildSourceSeriesProjections(contexts);
  const sourceSeriesIdByTargetVersionId = new Map(
    contexts.map(({ forecast, spec }) => [
      buildTargetVersionId(spec.predictionId),
      buildSourceSeriesId(forecast, spec),
    ]),
  );
  const targetObservationBindings = buildTargetObservationBindings(
    contexts,
    sourceSeriesIdByTargetVersionId,
  );
  const contextByForecastSlug = new Map(
    contexts.map((context) => [context.forecast.slug, context]),
  );
  const sourceSeriesIdByForecastSlug = new Map(
    contexts.map(({ forecast, spec }) => [
      forecast.slug,
      buildSourceSeriesId(forecast, spec),
    ]),
  );
  const observations = buildObservationProjections({
    contexts,
    ledger,
    sourceSeriesIdByForecastSlug,
  });
  const observationVintages = buildObservationVintageProjections({
    observations,
    contexts,
  });
  const forecastStrategies = buildForecastStrategies();
  const strategyVersions = buildStrategyVersions(forecastStrategies);
  const packCatalog = buildPredictionPackCatalog(forecasts);
  const packs = packCatalog.map((pack) => ({
    packId: pack.packId,
    slug: pack.packId,
    name: pack.label,
    targetFamilyTags: [],
    ownerId: "thesis" as const,
    createdAt: PROJECTION_GENERATED_AT,
  }));
  const packVersions = packCatalog.flatMap((pack) =>
    pack.versions.map((version) => ({
      packVersionId: buildPackVersionId(version.pack),
      packId: pack.packId,
      versionLabel: version.version,
      evidenceRequirements: pack.detail?.inputs ?? [],
      validatorRules: pack.detail?.qualityChecks ?? [],
      promptContentHash: sha256Hex({
        packId: pack.packId,
        version: version.version,
        summary: pack.summary,
        detail: pack.detail,
      }),
      ablationPlan: pack.detail?.limitations.join(" "),
    })),
  );
  const forecastRuns = runs.map((run) =>
    buildForecastRunProjection({
      run,
      targetVersionId:
        targetVersionsByLegacySpecVersionId.get(run.specVersionId) ??
        buildTargetVersionId(run.predictionId),
      strategyVersionId:
        strategyVersionIdByStrategyId.get(inferStrategyId(run)) ??
        buildStrategyVersionId("agent.brier.no_pack"),
    }),
  );
  const runPackVersions = runs.flatMap(buildRunPackVersionProjections);
  const runArtifactRefs = runs.flatMap(buildRunArtifactRefProjections);
  const baselineCandidates = buildBaselineCandidateProjections({
    runs,
    forecastRuns,
    artifactRefsByRunId: buildArtifactRefsByRunId(runs),
    sourceSeriesIdByTargetVersionId,
  });
  const toolCalls = runs.flatMap(buildToolCallProjections);
  const forecastDistributions = runs.flatMap((run) =>
    buildDistributionPointProjections(
      run,
      unitByLegacySpecVersionId.get(run.specVersionId) ?? "count",
    ),
  );
  const reasoningEvents = runs.flatMap(buildReasoningEventProjections);
  const reviewRuns = buildReviewRunProjections({
    runs,
    artifactRefsByRunId: buildArtifactRefsByRunId(runs),
  });
  const resolutionEvents = buildResolutionEventProjections({
    forecasts,
    ledger,
    contextByForecastSlug,
    observations,
  });
  const resolvedScores = scoreResolvedForecasts(forecasts, ledger);
  const scores = buildScoreProjections({
    resolvedScores,
    resolutionEvents,
  });
  const judgeRuns = buildJudgeRunProjections(
    buildForecastJudgeExport({
      forecasts,
      scores: resolvedScores,
    }),
  );
  const artifactRefs = buildArtifactRefs(runs);

  assertProjectionIdCollisions({
    targets,
    targetVersions,
    sourceSeries,
    observations,
    observationVintages,
    targetObservationBindings,
    baselineCandidates,
    forecastStrategies,
    strategyVersions,
    packs,
    packVersions,
    forecastRuns,
    runPackVersions,
    runArtifactRefs,
    toolCalls,
    forecastDistributions,
    reasoningEvents,
    reviewRuns,
    judgeRuns,
    resolutionEvents,
    scores,
    artifactRefs,
  });

  return {
    schemaVersion: "thesis_target_architecture_projection_v1",
    generatedAt: PROJECTION_GENERATED_AT,
    source: {
      records: "forecast_cells",
    },
    counts: {
      targets: targets.length,
      targetVersions: targetVersions.length,
      sourceSeries: sourceSeries.length,
      observations: observations.length,
      observationVintages: observationVintages.length,
      targetObservationBindings: targetObservationBindings.length,
      baselineCandidates: baselineCandidates.length,
      forecastStrategies: forecastStrategies.length,
      strategyVersions: strategyVersions.length,
      packs: packs.length,
      packVersions: packVersions.length,
      forecastRuns: forecastRuns.length,
      runPackVersions: runPackVersions.length,
      runArtifactRefs: runArtifactRefs.length,
      toolCalls: toolCalls.length,
      forecastDistributionPoints: forecastDistributions.length,
      reasoningEvents: reasoningEvents.length,
      reviewRuns: reviewRuns.length,
      judgeRuns: judgeRuns.length,
      resolutionEvents: resolutionEvents.length,
      scores: scores.length,
      artifactRefs: artifactRefs.length,
    },
    targets,
    targetVersions,
    sourceSeries,
    observations,
    observationVintages,
    targetObservationBindings,
    baselineCandidates,
    forecastStrategies,
    strategyVersions,
    packs,
    packVersions,
    forecastRuns,
    runPackVersions,
    runArtifactRefs,
    toolCalls,
    forecastDistributions,
    reasoningEvents,
    reviewRuns,
    judgeRuns,
    resolutionEvents,
    scores,
    artifactRefs,
  };
}

export function validateTargetArchitectureProjection(
  projection: ThesisTargetArchitectureProjection,
): TargetArchitectureValidationIssue[] {
  const issues: TargetArchitectureValidationIssue[] = [];
  const targetIds = new Set(
    projection.targets.map((target) => target.targetId),
  );
  const targetVersionIds = new Set(
    projection.targetVersions.map(
      (targetVersion) => targetVersion.targetVersionId,
    ),
  );
  const sourceSeriesIds = new Set(
    projection.sourceSeries.map((series) => series.sourceSeriesId),
  );
  const observationIds = new Set(
    projection.observations.map((observation) => observation.observationId),
  );
  const vintageIds = new Set(
    projection.observationVintages.map((vintage) => vintage.vintageId),
  );
  const strategyIds = new Set(
    projection.forecastStrategies.map((strategy) => strategy.strategyId),
  );
  const strategyVersionIds = new Set(
    projection.strategyVersions.map(
      (strategyVersion) => strategyVersion.strategyVersionId,
    ),
  );
  const packVersionIds = new Set(
    projection.packVersions.map((packVersion) => packVersion.packVersionId),
  );
  const runIds = new Set(projection.forecastRuns.map((run) => run.runId));
  const resolutionEventIds = new Set(
    projection.resolutionEvents.map(
      (resolutionEvent) => resolutionEvent.resolutionEventId,
    ),
  );
  const artifactRefIds = new Set(
    projection.artifactRefs.map((artifactRef) => artifactRef.artifactRefId),
  );

  expectUnique(
    projection.targets.map((target) => target.targetId),
    "target_id_unique",
    "targetId",
    issues,
  );
  expectUnique(
    projection.targets.map((target) => target.dataPointId),
    "data_point_id_unique",
    "dataPointId",
    issues,
  );
  expectUnique(
    projection.targetVersions.map(
      (targetVersion) => targetVersion.targetVersionId,
    ),
    "target_version_id_unique",
    "targetVersionId",
    issues,
  );
  expectUnique(
    projection.artifactRefs.map((artifactRef) => artifactRef.contentHash),
    "artifact_content_hash_unique",
    "artifact content hash",
    issues,
  );
  expectUnique(
    projection.sourceSeries.map((sourceSeries) =>
      [
        sourceSeries.adapterId,
        sourceSeries.agencySeriesId ?? "",
        sourceSeries.sourceUrl,
        sourceSeries.unit,
        sourceSeries.measureKey,
      ].join("::"),
    ),
    "source_series_sql_unique_key",
    "source_series SQL unique key",
    issues,
  );

  for (const targetVersion of projection.targetVersions) {
    if (!targetIds.has(targetVersion.targetId)) {
      issues.push(error("target_version_target_fk", targetVersion.targetId));
    }
    if (targetVersion.cdfPointCount !== 201) {
      issues.push(
        error(
          "target_version_cdf_count",
          `${targetVersion.targetVersionId} has ${targetVersion.cdfPointCount} CDF points`,
        ),
      );
    }
  }

  for (const binding of projection.targetObservationBindings) {
    if (!targetVersionIds.has(binding.targetVersionId)) {
      issues.push(error("binding_target_version_fk", binding.bindingId));
    }
    if (!sourceSeriesIds.has(binding.sourceSeriesId)) {
      issues.push(error("binding_source_series_fk", binding.bindingId));
    }
    const targetVersion = projection.targetVersions.find(
      (candidate) => candidate.targetVersionId === binding.targetVersionId,
    );
    const sourceSeries = projection.sourceSeries.find(
      (candidate) => candidate.sourceSeriesId === binding.sourceSeriesId,
    );
    if (
      targetVersion &&
      sourceSeries &&
      targetVersion.unit !== sourceSeries.unit
    ) {
      issues.push(
        error(
          "binding_source_series_unit_mismatch",
          `${binding.bindingId} binds ${targetVersion.unit} target to ${sourceSeries.unit} source series`,
        ),
      );
    }
    if (
      binding.bindingRole === "history" &&
      !projection.observations.some(
        (observation) => observation.sourceSeriesId === binding.sourceSeriesId,
      )
    ) {
      issues.push(
        error("binding_history_without_observation", binding.bindingId),
      );
    }
  }

  for (const observation of projection.observations) {
    if (!sourceSeriesIds.has(observation.sourceSeriesId)) {
      issues.push(
        error("observation_source_series_fk", observation.observationId),
      );
    }
  }

  for (const vintage of projection.observationVintages) {
    if (!observationIds.has(vintage.observationId)) {
      issues.push(error("vintage_observation_fk", vintage.vintageId));
    }
  }

  for (const strategyVersion of projection.strategyVersions) {
    if (!strategyIds.has(strategyVersion.strategyId)) {
      issues.push(
        error(
          "strategy_version_strategy_fk",
          strategyVersion.strategyVersionId,
        ),
      );
    }
  }

  for (const baselineCandidate of projection.baselineCandidates) {
    if (!targetVersionIds.has(baselineCandidate.targetVersionId)) {
      issues.push(
        error(
          "baseline_candidate_target_version_fk",
          baselineCandidate.candidateId,
        ),
      );
    }
    if (
      baselineCandidate.sourceSeriesId &&
      !sourceSeriesIds.has(baselineCandidate.sourceSeriesId)
    ) {
      issues.push(
        error(
          "baseline_candidate_source_series_fk",
          baselineCandidate.candidateId,
        ),
      );
    }
    if (
      baselineCandidate.artifactRefId &&
      !artifactRefIds.has(baselineCandidate.artifactRefId)
    ) {
      issues.push(
        error("baseline_candidate_artifact_fk", baselineCandidate.candidateId),
      );
    }
    if (!baselineCandidate.artifactRefId && !baselineCandidate.sourceSeriesId) {
      issues.push(
        error(
          "baseline_candidate_missing_provenance",
          baselineCandidate.candidateId,
        ),
      );
    }
  }

  for (const run of projection.forecastRuns) {
    if (!targetVersionIds.has(run.targetVersionId)) {
      issues.push(error("run_target_version_fk", run.runId));
    }
    if (!strategyVersionIds.has(run.strategyVersionId)) {
      issues.push(error("run_strategy_version_fk", run.runId));
    }
  }

  for (const runPackVersion of projection.runPackVersions) {
    if (!runIds.has(runPackVersion.runId)) {
      issues.push(error("run_pack_run_fk", runPackVersion.runPackVersionId));
    }
    if (!packVersionIds.has(runPackVersion.packVersionId)) {
      issues.push(error("run_pack_pack_version_fk", runPackVersion.runId));
    }
  }

  for (const runArtifactRef of projection.runArtifactRefs) {
    if (!runIds.has(runArtifactRef.runId)) {
      issues.push(
        error("run_artifact_run_fk", runArtifactRef.runArtifactRefId),
      );
    }
    if (!artifactRefIds.has(runArtifactRef.artifactRefId)) {
      issues.push(
        error("run_artifact_artifact_fk", runArtifactRef.runArtifactRefId),
      );
    }
  }

  for (const toolCall of projection.toolCalls) {
    if (!runIds.has(toolCall.runId)) {
      issues.push(error("tool_call_run_fk", toolCall.toolCallId));
    }
  }

  const distributionIndicesByRunId = new Map<string, Set<number>>();
  for (const point of projection.forecastDistributions) {
    if (!runIds.has(point.runId)) {
      issues.push(error("distribution_run_fk", point.runId));
    }
    if (point.pointIndex < 0 || point.pointIndex > 200) {
      issues.push(
        error("distribution_point_index", `${point.runId}:${point.pointIndex}`),
      );
    }
    let indices = distributionIndicesByRunId.get(point.runId);
    if (!indices) {
      indices = new Set();
      distributionIndicesByRunId.set(point.runId, indices);
    }
    if (indices.has(point.pointIndex)) {
      issues.push(
        error(
          "distribution_duplicate_point",
          `${point.runId}:${point.pointIndex}`,
        ),
      );
    }
    indices.add(point.pointIndex);
  }
  for (const runId of runIds) {
    const indices = distributionIndicesByRunId.get(runId);
    if (!indices || indices.size !== 201) {
      issues.push(
        error(
          "distribution_201_points_per_run",
          `${runId} has ${indices?.size ?? 0} points`,
        ),
      );
    }
  }

  for (const event of projection.reasoningEvents) {
    if (!runIds.has(event.runId)) {
      issues.push(error("reasoning_event_run_fk", event.reasoningEventId));
    }
    if (event.redactionStatus !== "public_only") {
      issues.push(error("reasoning_event_public_only", event.reasoningEventId));
    }
  }

  for (const reviewRun of projection.reviewRuns) {
    if (!runIds.has(reviewRun.runId)) {
      issues.push(error("review_run_run_fk", reviewRun.reviewRunId));
    }
    if (
      reviewRun.draftArtifactRefId &&
      !artifactRefIds.has(reviewRun.draftArtifactRefId)
    ) {
      issues.push(error("review_run_draft_artifact_fk", reviewRun.reviewRunId));
    }
    if (
      reviewRun.revisionArtifactRefId &&
      !artifactRefIds.has(reviewRun.revisionArtifactRefId)
    ) {
      issues.push(
        error("review_run_revision_artifact_fk", reviewRun.reviewRunId),
      );
    }
  }

  for (const judgeRun of projection.judgeRuns) {
    if (judgeRun.runId && !runIds.has(judgeRun.runId)) {
      issues.push(error("judge_run_run_fk", judgeRun.judgeRunId));
    }
    if (judgeRun.leftRunId && !runIds.has(judgeRun.leftRunId)) {
      issues.push(error("judge_run_left_run_fk", judgeRun.judgeRunId));
    }
    if (judgeRun.rightRunId && !runIds.has(judgeRun.rightRunId)) {
      issues.push(error("judge_run_right_run_fk", judgeRun.judgeRunId));
    }
    if (
      (judgeRun.leftRunId && !judgeRun.rightRunId) ||
      (!judgeRun.leftRunId && judgeRun.rightRunId)
    ) {
      issues.push(error("judge_run_pairwise_subject", judgeRun.judgeRunId));
    }
    if (!judgeRun.runId && !judgeRun.batchId) {
      issues.push(error("judge_run_subject", judgeRun.judgeRunId));
    }
    if (judgeRun.rewardEligible) {
      issues.push(error("judge_run_reward_eligible", judgeRun.judgeRunId));
    }
  }

  for (const resolutionEvent of projection.resolutionEvents) {
    if (!targetVersionIds.has(resolutionEvent.targetVersionId)) {
      issues.push(
        error(
          "resolution_event_target_version_fk",
          resolutionEvent.resolutionEventId,
        ),
      );
    }
    if (!observationIds.has(resolutionEvent.observationId)) {
      issues.push(
        error(
          "resolution_event_observation_fk",
          resolutionEvent.resolutionEventId,
        ),
      );
    }
    if (!vintageIds.has(resolutionEvent.vintageId)) {
      issues.push(
        error("resolution_event_vintage_fk", resolutionEvent.resolutionEventId),
      );
    }
  }

  for (const score of projection.scores) {
    if (!runIds.has(score.runId)) {
      issues.push(error("score_run_fk", score.scoreId));
    }
    if (!resolutionEventIds.has(score.resolutionEventId)) {
      issues.push(error("score_resolution_event_fk", score.scoreId));
    }
  }

  return issues;
}

export function assertValidTargetArchitectureProjection(
  projection: ThesisTargetArchitectureProjection,
) {
  const issues = validateTargetArchitectureProjection(projection);
  const errors = issues.filter((issue) => issue.severity === "error");
  if (errors.length > 0) {
    throw new Error(
      `Target architecture projection has ${errors.length} error(s): ${errors
        .slice(0, 5)
        .map((issue) => `${issue.code}: ${issue.message}`)
        .join("; ")}`,
    );
  }
  return issues;
}

function buildTargetProjection({
  forecast,
  spec,
}: ForecastProjectionContext): TargetProjection {
  return {
    targetId: buildTargetId(spec.predictionId),
    slug: forecast.slug,
    dataPointId: spec.resolution.targetFactRef ?? `forecast.${forecast.slug}`,
    country: spec.country,
    agency: inferAgency(spec.resolution.source),
    sourceFamily: buildSourceFamily(forecast, spec),
    sourceUrl: spec.resolution.sourceUrl,
    tags: buildTargetTags(forecast),
    createdAt: spec.publishedAt,
  };
}

function buildTargetVersionProjection({
  forecast,
  spec,
}: ForecastProjectionContext): TargetVersionProjection {
  return {
    targetVersionId: buildTargetVersionId(spec.predictionId),
    targetId: buildTargetId(spec.predictionId),
    versionLabel: VERSION_LABEL,
    question: spec.question,
    periodLabel: forecast.series?.horizonLabel ?? forecast.resolutionDate,
    targetPeriod: forecast.resolutionDate,
    unit: spec.unit,
    valueScale: 1,
    resolverKind: inferResolverKind(forecast),
    resolutionPolicy: spec.resolution.policy ?? "first_print",
    resolutionDateBasis: inferResolutionDateBasis(forecast),
    resolutionRule: spec.resolution.rule,
    resolutionSource: spec.resolution.source,
    resolutionSourceUrl: spec.resolution.sourceUrl,
    cdfPointCount: 201,
    publishedAt: spec.publishedAt,
  };
}

function buildSourceSeriesProjections(
  contexts: ForecastProjectionContext[],
): SourceSeriesProjection[] {
  const rows = new Map<string, SourceSeriesProjection>();
  for (const { forecast, spec } of contexts) {
    const sourceSeriesId = buildSourceSeriesId(forecast, spec);
    setByIdOrThrow(
      rows,
      sourceSeriesId,
      {
        sourceSeriesId,
        adapterId: buildAdapterId(forecast, spec),
        sourceFamily: buildSourceFamily(forecast, spec),
        agencySeriesId: forecast.series?.seriesId,
        measureKey: spec.resolution.targetFactRef ?? spec.predictionId,
        country: spec.country,
        agency: inferAgency(spec.resolution.source),
        sourceUrl: spec.resolution.sourceUrl ?? spec.resolution.source,
        unit: spec.unit,
        updateCadence: forecast.series?.cadence,
        defaultVintagePolicy: spec.resolution.policy ?? "unknown",
      },
      "source_series",
    );
  }
  return [...rows.values()].sort((left, right) =>
    left.sourceSeriesId.localeCompare(right.sourceSeriesId),
  );
}

function buildTargetObservationBindings(
  contexts: ForecastProjectionContext[],
  sourceSeriesIdByTargetVersionId: Map<string, string>,
): TargetObservationBindingProjection[] {
  return contexts.flatMap(({ forecast, spec }) => {
    const targetVersionId = buildTargetVersionId(spec.predictionId);
    const sourceSeriesId = sourceSeriesIdByTargetVersionId.get(targetVersionId);
    if (!sourceSeriesId) return [];
    const resolver: TargetObservationBindingProjection = {
      bindingId: `binding.${targetVersionId}.resolver`,
      targetVersionId,
      sourceSeriesId,
      bindingRole: "resolver",
      transformKind: "identity",
      adapterMethod: "official_release_lookup",
    };
    if (forecast.historicalContext.length === 0) return [resolver];
    return [
      resolver,
      {
        bindingId: `binding.${targetVersionId}.history`,
        targetVersionId,
        sourceSeriesId,
        bindingRole: "history",
        transformKind: "identity",
        adapterMethod: "historical_context",
      },
    ];
  });
}

function buildObservationProjections({
  contexts,
  ledger,
  sourceSeriesIdByForecastSlug,
}: {
  contexts: ForecastProjectionContext[];
  ledger: PolicyEngineLedgerEntry[];
  sourceSeriesIdByForecastSlug: Map<string, string>;
}): ObservationProjection[] {
  const rows = new Map<string, ObservationProjection>();
  for (const { forecast, spec } of contexts) {
    const observation = getResolvedObservationForForecast(forecast, ledger);
    const sourceSeriesId = sourceSeriesIdByForecastSlug.get(forecast.slug);
    if (!sourceSeriesId) continue;
    if (observation) {
      setByIdOrThrow(
        rows,
        observation.observationId,
        {
          observationId: observation.observationId,
          sourceSeriesId,
          dataPointId: observation.dataPointId,
          periodLabel: observation.periodLabel,
          value: observation.value,
          unit: observation.unit,
          valueScale: 1,
          sourceUrl: observation.sourceUrl ?? observation.source,
          retrievedAt: observation.observedAt,
          payloadHash: sha256Hex(observation),
        },
        "observations",
      );
    }
    for (const [pointIndex, point] of forecast.historicalContext.entries()) {
      const observationId = buildHistoricalObservationId({
        forecast,
        sourceSeriesId,
        pointLabel: point.label,
        pointIndex,
      });
      setByIdOrThrow(
        rows,
        observationId,
        {
          observationId,
          sourceSeriesId,
          periodLabel: point.label,
          value: point.value,
          unit: spec.unit,
          valueScale: 1,
          sourceUrl: spec.resolution.sourceUrl ?? spec.resolution.source,
          retrievedAt: spec.publishedAt,
          payloadHash: sha256Hex({
            kind: "forecast_historical_context",
            forecastSlug: forecast.slug,
            sourceSeriesId,
            point,
          }),
        },
        "observations",
      );
    }
  }
  // The database enforces unique (source_series_id, period_label,
  // payload_hash); a repeated historicalContext point produces two ids for
  // byte-identical content, which downstream vintages then reference
  // inconsistently. Content is identical (the hash is part of the key), so
  // keeping the first id is lossless.
  const byNaturalKey = new Map<string, ObservationProjection>();
  for (const row of rows.values()) {
    const key = `${row.sourceSeriesId} ${row.periodLabel} ${row.payloadHash}`;
    if (!byNaturalKey.has(key)) byNaturalKey.set(key, row);
  }
  return [...byNaturalKey.values()].sort((left, right) =>
    left.observationId.localeCompare(right.observationId),
  );
}

function buildObservationVintageProjections({
  observations,
  contexts,
}: {
  observations: ObservationProjection[];
  contexts: ForecastProjectionContext[];
}): ObservationVintageProjection[] {
  const policyByDataPointId = new Map<
    string,
    ObservationVintageProjection["vintageKind"]
  >();
  for (const { spec } of contexts) {
    if (spec.resolution.targetFactRef) {
      policyByDataPointId.set(
        spec.resolution.targetFactRef,
        spec.resolution.policy ?? "unknown",
      );
    }
  }
  return observations.map((observation) => {
    const vintageKind = observation.dataPointId
      ? (policyByDataPointId.get(observation.dataPointId) ?? "unknown")
      : "unknown";
    return {
      vintageId: buildVintageId(observation.observationId, vintageKind),
      observationId: observation.observationId,
      vintageKind,
      publishedAt: observation.retrievedAt,
      retrievedAt: observation.retrievedAt,
      normalizedPayloadHash: sha256Hex(observation),
    };
  });
}

function buildForecastStrategies(): ForecastStrategyProjection[] {
  const strategyById = new Map<string, ForecastStrategyProjection>();
  for (const strategy of CORE_STRATEGIES) {
    strategyById.set(strategy.strategyId, strategy);
  }
  for (const strategy of STRATEGY_REGISTRY) {
    strategyById.set(strategy.strategyId, {
      strategyId: strategy.strategyId,
      name: strategy.label,
      strategyKind:
        strategy.kind === "agent_forward"
          ? "llm_no_pack"
          : inferBaselineStrategyKind(strategy.strategyId),
      description: strategy.description,
    });
  }
  return [...strategyById.values()].sort((left, right) =>
    left.strategyId.localeCompare(right.strategyId),
  );
}

function buildStrategyVersions(
  strategies: ForecastStrategyProjection[],
): StrategyVersionProjection[] {
  return strategies.map((strategy) => ({
    strategyVersionId: buildStrategyVersionId(strategy.strategyId),
    strategyId: strategy.strategyId,
    versionLabel: VERSION_LABEL,
    promptPolicyHash: sha256Hex({
      strategyId: strategy.strategyId,
      description: strategy.description,
    }),
    toolPolicyHash: sha256Hex({
      strategyId: strategy.strategyId,
      requiredInputs: strategy.strategyKind,
    }),
    requiredInputs: [
      "target_version",
      "forecast_distribution",
      "public_reasoning_trace",
    ],
    modelFamilyConstraints: isDeterministicStrategyKind(strategy.strategyKind)
      ? ["deterministic"]
      : ["llm"],
  }));
}

function buildForecastRunProjection({
  run,
  targetVersionId,
  strategyVersionId,
}: {
  run: PredictionRunRecord;
  targetVersionId: string;
  strategyVersionId: string;
}): ForecastRunProjection {
  return {
    runId: run.runId,
    targetVersionId,
    strategyVersionId,
    agentId: run.agentId,
    model: run.modelVersion,
    runtime: run.runner.id,
    promptHash: run.promptHash,
    toolPolicyHash: run.toolPolicyHash,
    inputBundleHash: run.inputBundleHash,
    status: run.status,
    idempotencyKey: run.idempotencyKey,
    runAt: run.createdAt,
  };
}

function buildRunPackVersionProjections(
  run: PredictionRunRecord,
): RunPackVersionProjection[] {
  return (run.packSet?.packs ?? []).map((pack) => ({
    runPackVersionId: `run_pack.${run.runId}.${pack.packId}.${pack.version}`,
    runId: run.runId,
    packVersionId: buildPackVersionId(pack),
    packRole:
      run.packSet?.mode === "ensemble"
        ? "comparison"
        : run.packSet?.mode === "with_packs"
          ? "required"
          : "optional",
  }));
}

function buildRunArtifactRefProjections(
  run: PredictionRunRecord,
): RunArtifactRefProjection[] {
  // The ledger schema treats a run's reference to an artifact in a role as
  // one fact — unique (run_id, artifact_ref_id, artifact_role). Review-loop
  // runs reference the same artifact at several sequence points (draft,
  // review, revision), so dedupe on the schema's key and keep the first
  // sequence position.
  const seen = new Set<string>();
  const refs: RunArtifactRefProjection[] = [];
  for (const [sequenceIndex, artifact] of (run.activityLog ?? []).entries()) {
    const artifactRefId = buildArtifactRefId(artifact);
    const key = `${artifactRefId} ${artifact.artifactType}`;
    if (seen.has(key)) continue;
    seen.add(key);
    refs.push({
      runArtifactRefId: `run_artifact.${run.runId}.${sequenceIndex}`,
      runId: run.runId,
      artifactRefId,
      artifactRole: artifact.artifactType,
      sequenceIndex,
    });
  }
  return refs;
}

function buildBaselineCandidateProjections({
  runs,
  forecastRuns,
  artifactRefsByRunId,
  sourceSeriesIdByTargetVersionId,
}: {
  runs: PredictionRunRecord[];
  forecastRuns: ForecastRunProjection[];
  artifactRefsByRunId: Map<string, ArtifactRefProjection[]>;
  sourceSeriesIdByTargetVersionId: Map<string, string>;
}): BaselineCandidateProjection[] {
  const targetVersionByRunId = new Map(
    forecastRuns.map((run) => [run.runId, run.targetVersionId]),
  );
  return runs.flatMap((run) => {
    const strategyId = inferStrategyId(run);
    if (!strategyId.startsWith("baseline.")) return [];
    const targetVersionId = targetVersionByRunId.get(run.runId);
    if (!targetVersionId) return [];
    const firstArtifact = artifactRefsByRunId.get(run.runId)?.[0];
    const sourceSeriesId = sourceSeriesIdByTargetVersionId.get(targetVersionId);
    return [
      {
        candidateId: `candidate.${run.runId}`,
        targetVersionId,
        sourceSeriesId,
        modelAdapter: strategyId,
        candidateLabel: run.runLabel,
        trainingCutoff: run.createdAt,
        pointEstimate: run.output.pointEstimate,
        p10: run.output.interval80.lower,
        p50: run.output.pointEstimate,
        p90: run.output.interval80.upper,
        interval80Lower: run.output.interval80.lower,
        interval80Upper: run.output.interval80.upper,
        intervalMethod: "recorded_comparison_distribution",
        assumptions: run.runDescription,
        failureModes: [],
        artifactRefId: firstArtifact?.artifactRefId,
        provenance: {
          sourceRole: firstArtifact ? "run_artifact" : "source_series",
          forecastRunId: run.runId,
        },
      },
    ];
  });
}

function buildToolCallProjections(
  run: PredictionRunRecord,
): ToolCallProjection[] {
  return run.output.toolCalls.map((toolCall, sequenceIndex) => ({
    toolCallId: toolCall.toolCallId,
    runId: run.runId,
    allowedToolDeclaration: toolCall.allowedTool ? "allowed" : "not_allowed",
    toolName: toolCall.tool,
    requestHash: toolCall.requestHash,
    responseHash: toolCall.responseHash,
    provider: toolCall.provider,
    status: toolCall.status,
    costUsd: toolCall.costUsd,
    influencedFinalForecast: toolCall.influencedFinalForecast,
    sequenceIndex,
    sourceRole: "forecast_evidence",
  }));
}

function buildDistributionPointProjections(
  run: PredictionRunRecord,
  unit: Unit,
): ForecastDistributionPointProjection[] {
  const transformVersion = getDistributionTransformVersion(
    run.output.distribution,
  );
  return run.output.distribution.points.map((point, pointIndex) => ({
    runId: run.runId,
    pointIndex,
    value: point.value,
    probability: point.probability,
    unit,
    intervalMass: 0.8,
    distributionProvenance: run.output.distribution.provenance,
    transformVersion,
    validationStatus: "passed",
  }));
}

function buildReasoningEventProjections(
  run: PredictionRunRecord,
): ReasoningEventProjection[] {
  return run.output.publicTrace.map((publicText, sequenceIndex) => ({
    reasoningEventId: `reasoning.${run.runId}.${sequenceIndex}`,
    runId: run.runId,
    sequenceIndex,
    eventKind: "assistant_message",
    publicText,
    redactionStatus: "public_only",
  }));
}

function buildReviewRunProjections({
  runs,
  artifactRefsByRunId,
}: {
  runs: PredictionRunRecord[];
  artifactRefsByRunId: Map<string, ArtifactRefProjection[]>;
}): ReviewRunProjection[] {
  return runs.flatMap((run) => {
    const review = run.preSubmitReview;
    if (!review) return [];
    const artifactRefs = artifactRefsByRunId.get(run.runId) ?? [];
    const artifactByPath = new Map(
      artifactRefs.map((artifactRef) => [artifactRef.storageUri, artifactRef]),
    );
    return [
      {
        reviewRunId: `review.${run.runId}`,
        runId: run.runId,
        reviewerAgentId: review.reviewer.agent,
        draftArtifactRefId: review.draftArtifactPath
          ? artifactByPath.get(review.draftArtifactPath)?.artifactRefId
          : undefined,
        findings: review.findings,
        revisionArtifactRefId: review.revisionPromptPath
          ? artifactByPath.get(review.revisionPromptPath)?.artifactRefId
          : undefined,
        disposition: inferReviewDisposition(review),
      },
    ];
  });
}

function buildResolutionEventProjections({
  forecasts,
  ledger,
  contextByForecastSlug,
  observations,
}: {
  forecasts: ForecastCell[];
  ledger: PolicyEngineLedgerEntry[];
  contextByForecastSlug: Map<string, ForecastProjectionContext>;
  observations: ObservationProjection[];
}): ResolutionEventProjection[] {
  const observationsById = new Map(
    observations.map((observation) => [observation.observationId, observation]),
  );
  return forecasts
    .flatMap((forecast) => {
      const context = contextByForecastSlug.get(forecast.slug);
      const observation = getResolvedObservationForForecast(forecast, ledger);
      if (!context || !observation) return [];
      return [
        {
          resolutionEventId: buildObservationResolutionEventId(
            forecast.slug,
            observation,
          ),
          targetVersionId: buildTargetVersionId(context.spec.predictionId),
          observationId: observation.observationId,
          vintageId: buildVintageId(
            observation.observationId,
            context.spec.resolution.policy ?? "unknown",
          ),
          resolvedValue: observation.value,
          sourceUrl: observation.sourceUrl,
          resolverProof: {
            dataPointId: observation.dataPointId,
            observationId: observation.observationId,
          },
          scoreableStatus: "scoreable" as const,
          eventTimestamp:
            observationsById.get(observation.observationId)?.retrievedAt ??
            observation.resolvedAt,
        },
      ];
    })
    .sort((left, right) =>
      left.resolutionEventId.localeCompare(right.resolutionEventId),
    );
}

function buildJudgeRunProjections(
  judgeExport: ForecastJudgeExport,
): JudgeRunProjection[] {
  return [
    ...judgeExport.traceQuality.map((judge) => ({
      judgeRunId: judge.judgeId,
      runId: judge.runId,
      judgeModel: judge.judge.model,
      promptVersion: judge.judge.promptVersion,
      findings: judge.dimensions,
      recommendations: judge.flags,
      rewardEligible: false as const,
    })),
    ...judgeExport.pairwise.map((judge) => ({
      judgeRunId: judge.judgeId,
      batchId: `pairwise.${judge.predictionId}`,
      leftRunId: judge.leftRunId,
      rightRunId: judge.rightRunId,
      judgeModel: judge.judge.model,
      promptVersion: judge.judge.promptVersion,
      findings: [
        {
          winner: judge.winner,
          confidence: judge.confidence,
          reason: judge.reason,
          leftRunId: judge.leftRunId,
          rightRunId: judge.rightRunId,
        },
      ],
      recommendations: [],
      rewardEligible: false as const,
    })),
    ...judgeExport.postResolution.map((judge) => ({
      judgeRunId: judge.judgeId,
      runId: judge.runId,
      judgeModel: judge.judge.model,
      promptVersion: judge.judge.promptVersion,
      findings: [
        {
          primaryFailureMode: judge.primaryFailureMode,
          tags: judge.tags,
          severity: judge.severity,
          explanation: judge.explanation,
          scoreId: judge.scoreId,
        },
      ],
      recommendations: [],
      rewardEligible: false as const,
    })),
  ];
}

function buildScoreProjections({
  resolvedScores,
  resolutionEvents,
}: {
  resolvedScores: ResolvedForecastScore[];
  resolutionEvents: ResolutionEventProjection[];
}): ScoreProjection[] {
  const resolutionEventIds = new Set(
    resolutionEvents.map((event) => event.resolutionEventId),
  );
  return resolvedScores
    .flatMap((score) => {
      if (!resolutionEventIds.has(score.resolutionEventId)) return [];
      return [
        {
          scoreId: score.scoreId,
          runId: score.runId,
          resolutionEventId: score.resolutionEventId,
          scoringRule: score.scoringRule,
          distributionProvenance: score.distributionProvenance,
          transformVersion: score.transformVersion,
          crps: score.crps,
          normalizationScale: score.normalizationScale,
          normalizationScaleSource: score.normalizationScaleSource,
          normalizedScore: score.normalizedCrps,
          normalizedCrps: score.normalizedCrps,
          normalizedAbsoluteError: score.normalizedAbsoluteError,
          sharpness: score.sharpness,
          probabilityIntegralTransform: score.probabilityIntegralTransform,
          interval80Covered: score.interval80Covered,
          signedError: score.signedError,
          absoluteError: score.absoluteError,
          // Binds the scored numbers to the score row; the ledger schema
          // requires it (score_hash not null).
          scoreHash: sha256Hex({
            scoreId: score.scoreId,
            runId: score.runId,
            resolutionEventId: score.resolutionEventId,
            scoringRule: score.scoringRule,
            distributionProvenance: score.distributionProvenance,
            transformVersion: score.transformVersion,
            crps: score.crps,
            normalizationScale: score.normalizationScale,
            normalizationScaleSource: score.normalizationScaleSource,
            normalizedCrps: score.normalizedCrps,
            normalizedAbsoluteError: score.normalizedAbsoluteError,
            sharpness: score.sharpness,
            probabilityIntegralTransform: score.probabilityIntegralTransform,
            interval80Covered: score.interval80Covered,
            signedError: score.signedError,
            absoluteError: score.absoluteError,
          }),
          createdAt: PROJECTION_GENERATED_AT,
        },
      ];
    })
    .sort((left, right) => left.scoreId.localeCompare(right.scoreId));
}

function buildArtifactRefs(
  runs: PredictionRunRecord[],
): ArtifactRefProjection[] {
  const artifactRefs = new Map<string, ArtifactRefProjection>();
  for (const run of runs) {
    for (const artifact of run.activityLog ?? []) {
      const artifactRefId = buildArtifactRefId(artifact);
      const contentHash = buildArtifactContentHash(artifact);
      addArtifactRefOrThrow(artifactRefs, {
        artifactRefId,
        contentHash,
        mediaType: inferArtifactMediaType(artifact.artifactType),
        storageUri: artifact.path,
        publicVisibility: "public",
        metadata: {
          artifactType: artifact.artifactType,
          bytes: artifact.bytes,
          createdAt: artifact.createdAt,
          observationRefs: artifact.observationRefs,
          custodyRootSha256: artifact.custodyRootSha256,
        },
      });
    }
    const generatedBaselineArtifactRef =
      buildGeneratedBaselineArtifactRefIfNeeded(run);
    if (generatedBaselineArtifactRef) {
      addArtifactRefOrThrow(artifactRefs, generatedBaselineArtifactRef);
    }
  }
  return [...artifactRefs.values()].sort((left, right) =>
    left.artifactRefId.localeCompare(right.artifactRefId),
  );
}

function buildArtifactRefsByRunId(
  runs: PredictionRunRecord[],
): Map<string, ArtifactRefProjection[]> {
  return new Map(
    runs.map((run) => {
      const artifactRefs: ArtifactRefProjection[] = (run.activityLog ?? []).map(
        (artifact) => ({
          artifactRefId: buildArtifactRefId(artifact),
          contentHash: buildArtifactContentHash(artifact),
          mediaType: inferArtifactMediaType(artifact.artifactType),
          storageUri: artifact.path,
          publicVisibility: "public" as const,
          metadata: {
            artifactType: artifact.artifactType,
            bytes: artifact.bytes,
            createdAt: artifact.createdAt,
            observationRefs: artifact.observationRefs,
            custodyRootSha256: artifact.custodyRootSha256,
          },
        }),
      );
      const generatedBaselineArtifactRef =
        buildGeneratedBaselineArtifactRefIfNeeded(run);
      if (generatedBaselineArtifactRef) {
        artifactRefs.push(generatedBaselineArtifactRef);
      }
      return [run.runId, artifactRefs];
    }),
  );
}

function buildGeneratedBaselineArtifactRefIfNeeded(
  run: PredictionRunRecord,
): ArtifactRefProjection | undefined {
  const strategyId = inferStrategyId(run);
  if (!strategyId.startsWith("baseline.")) return undefined;
  if ((run.activityLog?.length ?? 0) > 0) return undefined;
  const contentPayload = {
    kind: "generated_baseline_candidate_summary",
    runId: run.runId,
    strategyId,
    pointEstimate: run.output.pointEstimate,
    interval80: run.output.interval80,
    drivers: run.output.drivers,
    runLabel: run.runLabel,
    runDescription: run.runDescription,
    createdAt: run.createdAt,
  };
  return {
    artifactRefId: `artifact.generated_baseline.${run.runId}`,
    contentHash: sha256Hex(contentPayload),
    mediaType: "application/json",
    storageUri: `generated://baseline-candidates/${run.runId}.json`,
    publicVisibility: "public",
    metadata: {
      artifactType: "generated_baseline_candidate_summary",
      strategyId,
      generatedFromRunId: run.runId,
    },
  };
}

function inferStrategyId(run: PredictionRunRecord): string {
  const agentId = run.agentId.toLowerCase();
  const model = (run.modelVersion ?? "").toLowerCase();
  const label = `${run.runLabel} ${run.runDescription ?? ""}`.toLowerCase();

  if (
    model === "persistence.last_print" ||
    agentId.includes("time-series-prior")
  ) {
    return "baseline.persistence.last_print";
  }
  if (
    agentId.includes("bls-employment-projections") ||
    model.includes("bls 2024-2034 projection") ||
    label.includes("bls-implied") ||
    label.includes("bls published projection")
  ) {
    return "baseline.official_projection.bls_employment_projections";
  }
  if (
    agentId.includes("bls-oews-current-table") ||
    model.includes("carry-forward baseline")
  ) {
    return "baseline.official_table.current_print";
  }
  if (agentId.includes("prototype-seed-agent")) {
    return "agent.prototype_seed";
  }
  if (
    agentId.includes("ensemble") ||
    model.includes("ensemble") ||
    label.includes("ensemble")
  ) {
    return "agent.brier.meta_aggregator";
  }
  if (run.packSet?.mode === "ensemble") return "agent.brier.meta_aggregator";
  if (run.packSet?.mode === "with_packs") return "agent.brier.pack_informed";
  return "agent.brier.no_pack";
}

function inferReviewDisposition(
  review: NonNullable<PredictionRunRecord["preSubmitReview"]>,
): ReviewRunProjection["disposition"] {
  if (review.status !== "completed") return "rejected";
  if (review.dispositions.some((disposition) => disposition.forecastChanged)) {
    return "revised";
  }
  if (review.findings.length > 0) return "accepted";
  return "no_change";
}

function isDeterministicStrategyKind(strategyKind: ForecastStrategyKind) {
  return (
    strategyKind === "persistence_baseline" ||
    strategyKind === "time_series_baseline" ||
    strategyKind === "official_projection_anchor" ||
    strategyKind === "formula_nowcast"
  );
}

function inferBaselineStrategyKind(strategyId: string): ForecastStrategyKind {
  if (strategyId.includes("persistence")) return "persistence_baseline";
  if (strategyId.includes("official")) return "official_projection_anchor";
  return "time_series_baseline";
}

function inferResolverKind(forecast: ForecastCell): ResolverKind {
  if (forecast.conditionalOn) return "conditional_gate";
  if (forecast.policyParameter) return "policy_state";
  if (forecast.resolutionRule.toLowerCase().includes("formula")) {
    return "formula_publication";
  }
  return "public_release";
}

function inferResolutionDateBasis(forecast: ForecastCell): ResolutionDateBasis {
  if (forecast.policyParameter) return "policy_deadline";
  if (forecast.resolutionDate) return "scheduled_release";
  if (forecast.series?.resolutionLatency) return "expected_first_post_window";
  return "unresolved_until_official_post";
}

function buildTargetTags(forecast: ForecastCell) {
  const tags: Array<string | undefined> = [
    forecast.type,
    forecast.series?.country,
    forecast.series?.cadence,
    forecast.series?.horizon,
    forecast.series?.priority,
  ];
  return tags.filter((tag): tag is string => Boolean(tag));
}

function buildTargetId(predictionId: string) {
  return `target.${predictionId}`;
}

function buildTargetVersionId(predictionId: string) {
  return `target_version.${predictionId}.v${VERSION_LABEL.replace(/-/g, "")}`;
}

function buildStrategyVersionId(strategyId: string) {
  return `strategy_version.${strategyId}.v${VERSION_LABEL.replace(/-/g, "")}`;
}

function buildVintageId(
  observationId: string,
  vintageKind: ObservationVintageProjection["vintageKind"],
) {
  return `vintage.${observationId.replace(/^obs\./, "")}.${vintageKind}`;
}

function buildHistoricalObservationId({
  forecast,
  sourceSeriesId,
  pointLabel,
  pointIndex,
}: {
  forecast: ForecastCell;
  sourceSeriesId: string;
  pointLabel: string;
  pointIndex: number;
}) {
  return `obs.history.${forecast.slug}.${slugify(pointLabel)}.${shortHash([
    sourceSeriesId,
    pointLabel,
    pointIndex.toString(),
  ])}`;
}

function buildPackVersionId(pack: PredictionPackReference) {
  return `pack_version.${buildPredictionPackVersionKey(pack).replace(
    /[^a-zA-Z0-9_.-]+/g,
    "-",
  )}`;
}

function buildSourceSeriesId(forecast: ForecastCell, spec: PredictionSpec) {
  const sourceBase =
    forecast.series?.seriesId ??
    `${buildSourceFamily(forecast, spec)}.${spec.resolution.source}`;
  const measureBase = spec.resolution.targetFactRef ?? spec.predictionId;
  return `source_series.${slugify(sourceBase)}.${shortHash([
    sourceBase,
    measureBase,
    spec.unit,
    spec.resolution.sourceUrl ?? spec.resolution.source,
  ])}`;
}

function buildAdapterId(forecast: ForecastCell, spec: PredictionSpec) {
  return `adapter.${slugify(buildSourceFamily(forecast, spec))}`;
}

function buildSourceFamily(forecast: ForecastCell, spec: PredictionSpec) {
  return forecast.series?.source ?? spec.resolution.source;
}

function inferAgency(source: string) {
  const upperSource = source.toUpperCase();
  if (upperSource.includes("BLS")) return "BLS";
  if (upperSource.includes("CENSUS")) return "Census";
  if (upperSource.includes("CMS")) return "CMS";
  if (upperSource.includes("FNS") || upperSource.includes("USDA")) {
    return "USDA FNS";
  }
  if (upperSource.includes("ONS")) return "ONS";
  if (upperSource.includes("TREASURY")) return "Treasury";
  return undefined;
}

function inferArtifactMediaType(artifactType: string) {
  if (artifactType === "baseline_inputs") return "application/json";
  if (artifactType.endsWith("_jsonl")) return "application/jsonl";
  if (artifactType.endsWith("_log")) return "text/plain";
  if (artifactType.includes("json")) return "application/json";
  return "text/plain";
}

function buildArtifactRefId(
  artifact: NonNullable<PredictionRunRecord["activityLog"]>[number],
) {
  return `artifact.${buildArtifactContentHash(artifact).slice(0, 16)}`;
}

function buildArtifactContentHash(
  artifact: NonNullable<PredictionRunRecord["activityLog"]>[number],
) {
  if (artifact.sha256 !== "generated") {
    if (!/^[0-9a-f]{64}$/.test(artifact.sha256)) {
      throw new Error(
        `Invalid artifact SHA-256 for ${artifact.path}: ${artifact.sha256}`,
      );
    }
    return artifact.sha256;
  }
  return sha256Hex({
    path: artifact.path,
    artifactType: artifact.artifactType,
  });
}

function slugify(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80);
}

function shortHash(value: unknown) {
  return sha256Hex(value).slice(0, 16);
}

type ProjectionRows = Omit<
  ThesisTargetArchitectureProjection,
  "schemaVersion" | "generatedAt" | "source" | "counts"
>;

function assertProjectionIdCollisions(projection: ProjectionRows) {
  assertNoIdCollisions("targets", projection.targets, (row) => row.targetId);
  assertNoIdCollisions(
    "target_versions",
    projection.targetVersions,
    (row) => row.targetVersionId,
  );
  assertNoIdCollisions(
    "source_series",
    projection.sourceSeries,
    (row) => row.sourceSeriesId,
  );
  assertNoIdCollisions(
    "observations",
    projection.observations,
    (row) => row.observationId,
  );
  assertNoIdCollisions(
    "observation_vintages",
    projection.observationVintages,
    (row) => row.vintageId,
  );
  assertNoIdCollisions(
    "target_observation_bindings",
    projection.targetObservationBindings,
    (row) => row.bindingId,
  );
  assertNoIdCollisions(
    "baseline_candidates",
    projection.baselineCandidates,
    (row) => row.candidateId,
  );
  assertNoIdCollisions(
    "forecast_strategies",
    projection.forecastStrategies,
    (row) => row.strategyId,
  );
  assertNoIdCollisions(
    "strategy_versions",
    projection.strategyVersions,
    (row) => row.strategyVersionId,
  );
  assertNoIdCollisions("packs", projection.packs, (row) => row.packId);
  assertNoIdCollisions(
    "pack_versions",
    projection.packVersions,
    (row) => row.packVersionId,
  );
  assertNoIdCollisions(
    "forecast_runs",
    projection.forecastRuns,
    (row) => row.runId,
  );
  assertNoIdCollisions(
    "run_pack_versions",
    projection.runPackVersions,
    (row) => row.runPackVersionId,
  );
  assertNoIdCollisions(
    "run_artifact_refs",
    projection.runArtifactRefs,
    (row) => row.runArtifactRefId,
  );
  assertNoIdCollisions(
    "tool_calls",
    projection.toolCalls,
    (row) => row.toolCallId,
  );
  assertNoIdCollisions(
    "forecast_distributions",
    projection.forecastDistributions,
    (row) => `${row.runId}:${row.pointIndex}`,
  );
  assertNoIdCollisions(
    "reasoning_events",
    projection.reasoningEvents,
    (row) => row.reasoningEventId,
  );
  assertNoIdCollisions(
    "review_runs",
    projection.reviewRuns,
    (row) => row.reviewRunId,
  );
  assertNoIdCollisions(
    "judge_runs",
    projection.judgeRuns,
    (row) => row.judgeRunId,
  );
  assertNoIdCollisions(
    "resolution_events",
    projection.resolutionEvents,
    (row) => row.resolutionEventId,
  );
  assertNoIdCollisions("scores", projection.scores, (row) => row.scoreId);
  assertNoIdCollisions(
    "artifact_refs",
    projection.artifactRefs,
    (row) => row.artifactRefId,
  );
}

function assertNoIdCollisions<T>(
  namespace: string,
  rows: T[],
  getId: (row: T) => string,
) {
  const payloadDigestById = new Map<string, string>();
  for (const row of rows) {
    const id = getId(row);
    const payloadDigest = sha256Hex(row);
    const existingDigest = payloadDigestById.get(id);
    if (existingDigest && existingDigest !== payloadDigest) {
      throwIdCollision(namespace, id, existingDigest, payloadDigest);
    }
    payloadDigestById.set(id, payloadDigest);
  }
}

function setByIdOrThrow<T>(
  rows: Map<string, T>,
  id: string,
  row: T,
  namespace: string,
) {
  const existing = rows.get(id);
  if (!existing) {
    rows.set(id, row);
    return;
  }
  const existingDigest = sha256Hex(existing);
  const payloadDigest = sha256Hex(row);
  if (existingDigest !== payloadDigest) {
    throwIdCollision(namespace, id, existingDigest, payloadDigest);
  }
}

function addArtifactRefOrThrow(
  artifactRefs: Map<string, ArtifactRefProjection>,
  artifactRef: ArtifactRefProjection,
) {
  const existing = artifactRefs.get(artifactRef.artifactRefId);
  if (!existing) {
    artifactRefs.set(artifactRef.artifactRefId, artifactRef);
    return;
  }
  if (existing.contentHash !== artifactRef.contentHash) {
    throwIdCollision(
      "artifact_refs",
      artifactRef.artifactRefId,
      existing.contentHash,
      artifactRef.contentHash,
    );
  }
}

function throwIdCollision(
  namespace: string,
  id: string,
  existingDigest: string,
  payloadDigest: string,
): never {
  throw new Error(
    `ID collision in ${namespace} for ${id}: payload digests ${existingDigest} and ${payloadDigest}`,
  );
}

function expectUnique(
  values: string[],
  code: string,
  label: string,
  issues: TargetArchitectureValidationIssue[],
) {
  const seen = new Set<string>();
  for (const value of values) {
    if (seen.has(value)) {
      issues.push(error(code, `Duplicate ${label}: ${value}`));
    }
    seen.add(value);
  }
}

function error(
  code: string,
  message: string,
): TargetArchitectureValidationIssue {
  return { severity: "error", code, message };
}
