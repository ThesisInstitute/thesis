import type {
  CountryCode,
  ForecastRunEntry,
  ForecastCell,
  ForecastCellType,
  PredictionRunActivityArtifact,
  PredictionPreSubmitReviewWorkflow,
  PredictionPackSet,
  ReasoningStep,
  ResolutionPolicy,
  Unit,
} from "./forecast-cells";
import { getForecastRunEntries } from "./forecast-cells";
import { requireLedgerTarget } from "./ledger-targets";
import {
  validateNumericCdfDistribution,
  type PredictionDistribution,
} from "./prediction-distribution";
import { sha256Hex } from "./canonical-json";

export type PredictionSpecSchemaVersion = "thesis_prediction_spec_v1";
export type PredictionRunSchemaVersion = "thesis_prediction_run_v1";
export type QualityGateStatus = "passed" | "warning" | "failed";

export interface PredictionSpec {
  schemaVersion: PredictionSpecSchemaVersion;
  specId: string;
  specVersionId: string;
  parentSpecVersionId?: string;
  specHash: string;
  publishedAt: string;
  predictionId: string;
  title: string;
  question: string;
  type: ForecastCellType;
  country: CountryCode;
  unit: Unit;
  resolution: {
    expectedAt: string;
    source: string;
    sourceUrl?: string;
    rule: string;
    policy?: ResolutionPolicy;
    targetFactRef?: string;
    factLedger: "PolicyEngine Ledger";
  };
  distribution: {
    format: "numeric_cdf_v1";
    pointCount: 201;
    elicitation: "full_cdf";
    intervalMass: 0.8;
  };
  tools: {
    allowed: string[];
    required: string[];
  };
  agent: {
    instructions: string[];
    publicTraceOnly: true;
  };
  qualityGates: string[];
}

export interface PredictionRunToolCall {
  toolCallId: string;
  tool: string;
  call: string;
  result: string;
  allowedTool: boolean;
  requestHash: string;
  responseHash: string;
  provider: "recorded-public-trace";
  status: "succeeded" | "failed";
  costUsd: number | null;
  influencedFinalForecast: boolean;
}

export interface PredictionRunQualityGate {
  name: string;
  status: QualityGateStatus;
  detail?: string;
}

export interface PredictionRunRecord {
  schemaVersion: PredictionRunSchemaVersion;
  runId: string;
  specId: string;
  specVersionId: string;
  predictionId: string;
  agentId: string;
  runLabel: string;
  runDescription?: string;
  packSet?: PredictionPackSet;
  activityLog?: PredictionRunActivityArtifact[];
  preSubmitReview?: PredictionPreSubmitReviewWorkflow;
  idempotencyKey: string;
  createdAt: string;
  modelVersion?: string;
  aggregationAlgorithmVersion?: string;
  constituentRuns?: NonNullable<
    ForecastRunEntry["predictionRun"]
  >["constituentRuns"];
  promptHash: string;
  toolPolicyHash: string;
  inputBundleHash: string;
  status: "published" | "needs_review";
  runner: {
    id: "thesis.recorded-agent-runner";
    version: "prototype-v1";
    agent?: string;
    model?: string;
  };
  input: {
    specId: string;
    specVersionId: string;
    allowedTools: string[];
    targetFactRef?: string;
    packSetId?: string;
    packIds: string[];
    preSubmitReview?: PredictionPreSubmitReviewWorkflow;
  };
  output: {
    pointEstimate: number;
    interval80: {
      lower: number;
      upper: number;
    };
    distribution: PredictionDistribution;
    publicTrace: string[];
    publicTraceMetadata: {
      redactionStatus: "public_only";
      traceHash: string;
      publiclyReproducibleEnough: boolean;
    };
    toolCalls: PredictionRunToolCall[];
    drivers: string[];
  };
  resolution: {
    status: "linked" | "pending";
    resolutionRef: string;
    factLedger: "PolicyEngine Ledger";
    targetFactRef?: string;
    ledgerFactRef?: string;
  };
  qualityGates: PredictionRunQualityGate[];
}

export interface PredictionSpecExport {
  schemaVersion: "thesis_prediction_specs_v1";
  counts: {
    specs: number;
    withResolutionTarget: number;
  };
  specs: PredictionSpec[];
}

const SPEC_VERSION = "2026-06-09";
// Legacy placeholder stamped on early runs that never recorded a real run
// time. Chronology gating treats any run carrying this value (or no run
// time at all) as unverifiable — it can never enter the headline score.
export const SEEDED_RUN_RECORDED_AT = "2026-06-08T00:00:00+02:00";

const SYSTEM_TOOLS = [
  "distribution.validate",
  "policyengine-ledger.resolve",
  "thesis-log.write",
] as const;

const SPEC_QUALITY_GATES = [
  "prediction_id_present",
  "resolution_source_defined",
  "distribution_numeric_cdf_v1_201_points",
  "allowed_tools_declared",
  "public_trace_only",
  "ledger_target_ref_declared_when_available",
] as const;

export function buildPredictionSpec(forecast: ForecastCell): PredictionSpec {
  const specId = buildSpecId(forecast.slug);
  const specVersionId = buildSpecVersionId(forecast.slug);
  const ledgerTarget = forecast.dataPointId
    ? requireLedgerTarget(forecast.dataPointId)
    : undefined;
  const resolution = {
    expectedAt: ledgerTarget?.resolutionDate ?? forecast.resolutionDate,
    source: ledgerTarget?.resolutionSource ?? forecast.resolutionSource,
    sourceUrl:
      ledgerTarget?.resolutionSourceUrl ?? forecast.resolutionSourceUrl,
    rule: ledgerTarget?.resolutionRule ?? forecast.resolutionRule,
    policy: ledgerTarget?.resolutionPolicy ?? forecast.series?.resolutionPolicy,
    targetFactRef: ledgerTarget?.dataPointId ?? forecast.dataPointId,
    factLedger: "PolicyEngine Ledger" as const,
  };
  const tools = {
    allowed: buildAllowedTools(forecast),
    required: buildRequiredTools(forecast),
  };
  const qualityGates = [...SPEC_QUALITY_GATES];
  const hashMaterial = {
    specId,
    specVersionId,
    predictionId: forecast.slug,
    title: forecast.title,
    question: forecast.question,
    type: forecast.type,
    country: forecast.country ?? forecast.series?.country ?? "US",
    unit: forecast.unit,
    resolution,
    distribution: {
      format: "numeric_cdf_v1",
      pointCount: 201,
      elicitation: "full_cdf",
      intervalMass: 0.8,
    },
    tools,
    qualityGates,
  };

  return {
    schemaVersion: "thesis_prediction_spec_v1",
    specId,
    specVersionId,
    specHash: sha256Hex(hashMaterial),
    publishedAt: `${SPEC_VERSION}T00:00:00+02:00`,
    predictionId: forecast.slug,
    title: forecast.title,
    question: forecast.question,
    type: forecast.type,
    country: forecast.country ?? forecast.series?.country ?? "US",
    unit: forecast.unit,
    resolution,
    distribution: {
      format: "numeric_cdf_v1",
      pointCount: 201,
      elicitation: "full_cdf",
      intervalMass: 0.8,
    },
    tools,
    agent: {
      instructions: [
        "Produce an audit-ready public forecast for the specified prediction.",
        "Call only the allowed typed tools and record each tool call.",
        "Return a full numeric_cdf_v1 distribution with exactly 201 points.",
        "Write public reasoning only; do not expose hidden chain-of-thought.",
        "Resolve only by linking a resolution event to the PolicyEngine Ledger target ref.",
      ],
      publicTraceOnly: true,
    },
    qualityGates,
  };
}

export function buildPredictionSpecs(forecasts: ForecastCell[]) {
  return forecasts.map(buildPredictionSpec);
}

export function buildPredictionSpecExport(
  forecasts: ForecastCell[],
): PredictionSpecExport {
  const specs = buildPredictionSpecs(forecasts);

  return {
    schemaVersion: "thesis_prediction_specs_v1",
    counts: {
      specs: specs.length,
      withResolutionTarget: specs.filter(
        (spec) => spec.resolution.targetFactRef,
      ).length,
    },
    specs,
  };
}

export function buildRecordedPredictionRunRecord(
  forecast: ForecastCell,
  spec: PredictionSpec = buildPredictionSpec(forecast),
  run: ForecastRunEntry = getForecastRunEntries(forecast)[0],
): PredictionRunRecord | null {
  if (!run?.predictionDistribution) return null;

  const qualityGates = evaluateRunQualityGates(forecast, spec, run);
  const hasFailedGate = qualityGates.some((gate) => gate.status === "failed");
  const createdAt = run.predictionRun?.runAt ?? SEEDED_RUN_RECORDED_AT;
  const runId = buildRecordedPredictionRunId(
    forecast,
    createdAt,
    run.variantId,
    run,
  );
  const agentId = buildAgentId(run);
  const publicTrace = buildPublicTrace(
    run.reasoning,
    run.predictionRun?.preSubmitReview,
  );
  const toolCalls = extractToolCalls(run.reasoning, runId, spec);
  const promptHash = sha256Hex({
    specVersionId: spec.specVersionId,
    question: spec.question,
    instructions: spec.agent.instructions,
    runVariantId: run.variantId,
  });
  const toolPolicyHash = sha256Hex(spec.tools);
  const inputBundleHash =
    run.predictionRun?.inputBundleHash ??
    sha256Hex({
      specVersionId: spec.specVersionId,
      targetFactRef: spec.resolution.targetFactRef,
      historicalContext: forecast.historicalContext,
      policyParameter: forecast.policyParameter,
      packSet: run.packSet,
    });

  return {
    schemaVersion: "thesis_prediction_run_v1",
    runId,
    specId: spec.specId,
    specVersionId: spec.specVersionId,
    predictionId: forecast.slug,
    agentId,
    runLabel: run.label,
    runDescription: run.description,
    packSet: run.packSet,
    activityLog: run.predictionRun?.activityLog,
    preSubmitReview: run.predictionRun?.preSubmitReview,
    idempotencyKey: sha256Hex({
      specVersionId: spec.specVersionId,
      agentId,
      createdAt,
      runVariantId: run.variantId,
      packSetId: run.packSet?.packSetId,
    }),
    createdAt,
    modelVersion: run.predictionRun?.model,
    aggregationAlgorithmVersion: run.predictionRun?.aggregationAlgorithmVersion,
    constituentRuns: run.predictionRun?.constituentRuns,
    promptHash,
    toolPolicyHash,
    inputBundleHash,
    status: hasFailedGate ? "needs_review" : "published",
    runner: {
      id: "thesis.recorded-agent-runner",
      version: "prototype-v1",
      agent: run.predictionRun?.agent,
      model: run.predictionRun?.model,
    },
    input: {
      specId: spec.specId,
      specVersionId: spec.specVersionId,
      allowedTools: spec.tools.allowed,
      targetFactRef: spec.resolution.targetFactRef,
      packSetId: run.packSet?.packSetId,
      packIds: run.packSet?.packs.map((pack) => pack.packId) ?? [],
      preSubmitReview: run.predictionRun?.preSubmitReview,
    },
    output: {
      pointEstimate: run.pointEstimate,
      interval80: {
        lower: run.ciLow,
        upper: run.ciHigh,
      },
      distribution: run.predictionDistribution,
      publicTrace,
      publicTraceMetadata: {
        redactionStatus: "public_only",
        traceHash: sha256Hex(publicTrace),
        publiclyReproducibleEnough: true,
      },
      toolCalls,
      drivers: run.drivers,
    },
    resolution: {
      status: forecast.resolvedOutcome ? "linked" : "pending",
      resolutionRef: buildResolutionRef(forecast.slug),
      factLedger: "PolicyEngine Ledger",
      targetFactRef: spec.resolution.targetFactRef,
      ledgerFactRef: forecast.resolvedOutcome
        ? spec.resolution.targetFactRef
        : undefined,
    },
    qualityGates,
  };
}

export function buildRecordedPredictionRunRecords(
  forecasts: ForecastCell[],
  specs: PredictionSpec[] = buildPredictionSpecs(forecasts),
): PredictionRunRecord[] {
  const specsById = new Map(specs.map((spec) => [spec.predictionId, spec]));
  return forecasts.flatMap((forecast) => {
    return getForecastRunEntries(forecast).flatMap((runEntry) => {
      const run = buildRecordedPredictionRunRecord(
        forecast,
        specsById.get(forecast.slug),
        runEntry,
      );
      return run ? [run] : [];
    });
  });
}

function buildAllowedTools(forecast: ForecastCell) {
  const tools = new Set<string>(SYSTEM_TOOLS);
  for (const run of getForecastRunEntries(forecast)) {
    for (const tool of extractToolNames(run.reasoning)) {
      tools.add(tool);
    }
  }
  if (forecast.type === "conditional" || forecast.policyParameter) {
    tools.add("policyengine.simulate");
  }
  if (forecast.dataPointId) {
    tools.add("policyengine-ledger.lookup");
  }
  return [...tools].sort();
}

export function buildSpecId(predictionId: string) {
  return `spec.${predictionId}`;
}

export function buildSpecVersionId(predictionId: string) {
  return `${buildSpecId(predictionId)}.v${SPEC_VERSION.replace(/-/g, "")}`;
}

export function buildResolutionRef(predictionId: string) {
  return `resolution.${predictionId}`;
}

export function buildRecordedPredictionRunId(
  forecast: ForecastCell,
  createdAt: string = forecast.predictionRun?.runAt ?? SEEDED_RUN_RECORDED_AT,
  variantId = forecast.primaryVariantId ?? "primary",
  runEntry?: ForecastRunEntry,
) {
  const run =
    runEntry ??
    getForecastRunEntries(forecast).find(
      (candidate) =>
        candidate.variantId === variantId &&
        (candidate.predictionRun?.runAt ?? SEEDED_RUN_RECORDED_AT) ===
          createdAt,
    );
  const outputDigest = sha256Hex(
    buildForecastOutputDistributionSummary(
      run ?? {
        pointEstimate: forecast.pointEstimate,
        ciLow: forecast.ciLow,
        ciHigh: forecast.ciHigh,
        predictionDistribution: forecast.predictionDistribution,
      },
    ),
  );
  const variantSuffix =
    variantId === "primary" ? "" : `.${formatRunTimestamp(variantId)}`;
  return `run.${forecast.slug}.${formatRunTimestamp(createdAt)}${variantSuffix}.${outputDigest.slice(0, 16)}`;
}

function buildForecastOutputDistributionSummary(
  run: Pick<ForecastRunEntry, "pointEstimate" | "ciLow" | "ciHigh"> & {
    predictionDistribution?: PredictionDistribution;
  },
) {
  return {
    pointEstimate: run.pointEstimate,
    interval80: {
      lower: run.ciLow,
      upper: run.ciHigh,
    },
    distribution: run.predictionDistribution,
  };
}

function buildRequiredTools(forecast: ForecastCell) {
  const tools = new Set<string>(["distribution.validate", "thesis-log.write"]);
  if (forecast.dataPointId) tools.add("policyengine-ledger.resolve");
  return [...tools].sort();
}

function evaluateRunQualityGates(
  forecast: ForecastCell,
  spec: PredictionSpec,
  run: ForecastRunEntry,
): PredictionRunQualityGate[] {
  const distribution = run.predictionDistribution;
  const distributionErrors = distribution
    ? validateNumericCdfDistribution(distribution)
    : ["CDF is missing"];

  return [
    gate(
      "prediction_id_present",
      Boolean(spec.predictionId && spec.predictionId === forecast.slug),
      "Spec id must match the prediction slug.",
    ),
    gate(
      "resolution_source_defined",
      Boolean(
        spec.resolution.expectedAt &&
        spec.resolution.source &&
        spec.resolution.rule,
      ),
      "Resolution date, source, and rule are required.",
    ),
    gate(
      "distribution_numeric_cdf_v1_201_points",
      Boolean(
        distribution?.format === "numeric_cdf_v1" &&
        distribution.pointCount === 201 &&
        distribution.points.length === 201,
      ),
      "Agent output must be a 201-point numeric CDF.",
    ),
    gate(
      "distribution_monotone",
      distributionErrors.length === 0,
      distributionErrors.join("; "),
    ),
    gate(
      "allowed_tools_declared",
      spec.tools.allowed.length > 0 && spec.tools.required.length > 0,
      "Spec must declare allowed and required tools.",
    ),
    gate(
      "public_trace_present",
      buildPublicTrace(run.reasoning).length >= 3,
      "Run must include a public audit trace.",
    ),
    gate(
      "ledger_target_ref_declared_when_available",
      Boolean(spec.resolution.targetFactRef),
      "Prediction should identify the PolicyEngine Ledger target ref that will resolve it.",
      "warning",
    ),
  ];
}

function gate(
  name: string,
  condition: boolean,
  detail: string,
  missingStatus: QualityGateStatus = "failed",
): PredictionRunQualityGate {
  return {
    name,
    status: condition ? "passed" : missingStatus,
    detail: condition ? undefined : detail,
  };
}

function extractToolCalls(
  reasoning: ReasoningStep[],
  runId: string,
  spec: PredictionSpec,
): PredictionRunToolCall[] {
  return reasoning.flatMap((step, index) => {
    if (step.kind !== "tool") return [];
    const tool = step.tool ?? inferToolName(step.call);
    return [
      {
        toolCallId: `${runId}.tool.${index}`,
        tool,
        call: step.call,
        result: step.result,
        allowedTool: spec.tools.allowed.includes(tool),
        requestHash: sha256Hex({ tool, call: step.call }),
        responseHash: sha256Hex({ tool, result: step.result }),
        provider: "recorded-public-trace",
        status: "succeeded",
        costUsd: null,
        influencedFinalForecast: true,
      },
    ];
  });
}

function extractToolNames(reasoning: ReasoningStep[]) {
  return reasoning.flatMap((step) => {
    if (step.kind !== "tool") return [];
    return [step.tool ?? inferToolName(step.call)];
  });
}

function buildPublicTrace(
  reasoning: ReasoningStep[],
  preSubmitReview?: PredictionPreSubmitReviewWorkflow,
) {
  const reviewTrace = preSubmitReview
    ? [
        `Pre-submit review ${preSubmitReview.status}: ${preSubmitReview.summary}`,
        ...preSubmitReview.findings
          .slice(0, 2)
          .map(
            (finding) =>
              `Reviewer ${finding.severity}: ${finding.rubricItem} - ${finding.summary}`,
          ),
        ...preSubmitReview.dispositions
          .slice(0, 2)
          .map(
            (disposition) =>
              `Forecaster disposition: ${disposition.decision} ${disposition.findingId}; ${disposition.rationale}`,
          ),
      ]
    : [];
  const trace = reasoning.flatMap((step) => {
    if (
      step.kind === "heading" ||
      step.kind === "text" ||
      step.kind === "math"
    ) {
      return [step.text];
    }
    if (step.kind === "forecast") {
      return [
        `Published forecast: point ${step.point}, 80% interval [${step.ciLow}, ${step.ciHigh}].`,
      ];
    }
    return [];
  });

  return [...reviewTrace, ...trace].slice(0, 10);
}

function inferToolName(call: string) {
  const match = call.match(/^([a-zA-Z0-9_.-]+)\s*\(/);
  return match?.[1] ?? "agent.tool";
}

function buildAgentId(run: ForecastRunEntry) {
  const agent = run.predictionRun?.agent ?? "prototype-seed-agent";
  return `agent.${agent
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")}`;
}

function formatRunTimestamp(value: string) {
  return value.replace(/[^0-9A-Za-z]+/g, "-").replace(/^-|-$/g, "");
}
