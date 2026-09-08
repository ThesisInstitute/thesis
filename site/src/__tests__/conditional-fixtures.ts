/** Synthetic paired forecasts for contract/UI tests only; never product data. */
import type {
  ArtifactLink,
  ConditionalDetail,
  ConditionalPage,
  ConditionalSummary,
  NumericCdf,
  Quantiles,
} from "@/data/generated/thesis-lab";
import { envelope, ids, instant } from "./lab-fixtures";
const quantiles = (offset: number): Quantiles => ({
  method: "inverse_piecewise_linear_cdf_v1",
  q10: 1 + offset,
  q50: 5 + offset,
  q90: 9 + offset,
});
const distribution = (offset: number): NumericCdf => ({
  format: "numeric_cdf_v1",
  pointCount: 201,
  support: { lower: offset, upper: offset + 10 },
  points: Array.from({ length: 201 }, (_, i) => ({
    value: offset + i / 20,
    probability: i / 200,
  })),
  summary: {
    pointEstimate: offset + 5,
    median: offset + 5,
    interval80: { lower: offset + 1, upper: offset + 9 },
  },
  provenance: "agent_reported",
  transformVersion: "native_conditional_v1",
});
export const conditionalSummary: ConditionalSummary = {
  id: ids.task,
  title: "Synthetic policy comparison",
  question:
    "How does the synthetic outcome differ across the two test conditions?",
  unit: "index points",
  measurement_period: "2030",
  status: "exploratory",
  scoring_status: "not_registered",
  trust_class: "local_operator",
  requested_model: "synthetic-test-model",
  provider_metadata: null,
  observed_model: null,
  execution_state: "succeeded",
  started_at: instant,
  finished_at: "2026-09-05T12:00:30Z",
  error_code: null,
};
function withSelfHistory(
  data: Omit<ConditionalDetail, "revision_history">,
): ConditionalDetail {
  return {
    ...data,
    revision_history: [
      {
        attempt_id: data.id,
        contract_id: data.contract_id,
        shared_evidence_id: data.shared_evidence_id,
        parent_attempt_id: null,
        started_at: data.started_at,
        execution_state: data.execution_state,
        requested_model: data.requested_model,
        provider_metadata: data.provider_metadata,
        arm_quantiles: data.arm_quantiles,
        feedback: null,
        triggering_review_id: null,
        linked_at: null,
        association_basis: null,
        association_artifact: null,
      },
    ],
  };
}
export const conditional: ConditionalDetail = withSelfHistory({
  ...envelope,
  ...conditionalSummary,
  reviews: [],
  contract_id: ids.target,
  shared_evidence_id: ids.source,
  contract: {
    schema_version: "thesis_conditional_contract_v1",
    title: conditionalSummary.title,
    question: conditionalSummary.question,
    outcome: {
      name: "Synthetic index",
      country: "Test country",
      geography: "Test geography",
      population: "Test population",
      measure: "Synthetic index level",
      measurement_period: "2030",
      unit: "index points",
      resolution_rule: "Use the first synthetic print in this test fixture.",
      resolution_source_url: "https://example.org/synthetic-outcome",
      release_date: null,
    },
    arms: [
      {
        id: "condition-a",
        label: "Condition A",
        condition: "Synthetic condition A is met before the deadline.",
        assumptions: ["Synthetic assumption A."],
      },
      {
        id: "condition-b",
        label: "Condition B",
        condition: "Synthetic condition B is met before the deadline.",
        assumptions: ["Synthetic assumption B."],
      },
    ],
    reference_description: "One shared synthetic reference for both arms.",
    condition_deadline: "2028-01-01T00:00:00Z",
    condition_resolution_note: "Synthetic policy-state check.",
    exhaustive: false,
    shared_history: [
      { period: "2024", value: 4, source_id: "synthetic-source" },
    ],
    sources: [
      {
        id: "synthetic-source",
        title: "Synthetic source",
        url: "https://example.org/synthetic-source",
        retrieved_at: "2026-09-05T11:50:00Z",
        artifact: { sha256: ids.artifact, bytes: 12, media_type: "text/plain" },
      },
    ],
    shared_evidence: [
      {
        claim: "This is synthetic evidence used only in tests.",
        source_ids: ["synthetic-source"],
      },
    ],
    limitations: ["Synthetic fixture, not an actual policy forecast."],
    methodology: "paired_conditional_v1",
    status: "exploratory",
    scoring_status: "not_registered",
    trust_class: "local_operator",
  },
  response: {
    contract_id: ids.target,
    shared_evidence_id: ids.source,
    reference: distribution(0),
    reference_reasoning: "Synthetic common reference reasoning.",
    arms: [
      {
        id: "condition-a",
        baseline_delta: 2,
        distribution: distribution(2),
        reasoning: "Synthetic arm A reasoning.",
      },
      {
        id: "condition-b",
        baseline_delta: -1,
        distribution: distribution(-1),
        reasoning: "Synthetic arm B reasoning.",
      },
    ],
  },
  reference_quantiles: quantiles(0),
  arm_quantiles: [quantiles(2), quantiles(-1)],
  artifacts: [
    {
      sha256: ids.artifact,
      bytes: 12,
      media_type: "text/plain",
      role: "validation",
      download_path: `/artifacts/${ids.artifact}`,
    },
  ],
  expires_at: "2026-09-05T12:05:00Z",
});
export const conditionalPage: ConditionalPage = {
  ...envelope,
  requested_models: [conditionalSummary.requested_model],
  items: [conditionalSummary],
  total: 1,
  next_cursor: null,
};
export const unsuccessful = (state: "failed" | "unknown"): ConditionalDetail =>
  withSelfHistory({
    ...conditional,
    execution_state: state,
    error_code: state === "failed" ? "invalid_response" : "attempt_expired",
    response: null,
    reference_quantiles: null,
    arm_quantiles: [],
  });

/** API shape when a lease expires before an operator records recovery. */
export const expiredSummary: ConditionalSummary = {
  ...conditionalSummary,
  id: ids.agent,
  title: "Expired synthetic attempt",
  execution_state: "unknown",
  error_code: "lease_expired",
  finished_at: null,
};
export const expiredConditional: ConditionalDetail = withSelfHistory({
  ...unsuccessful("unknown"),
  ...expiredSummary,
  contract: { ...conditional.contract, title: expiredSummary.title },
  generated_at: "2026-09-05T12:06:00Z",
});

const syntheticArtifact = (role: string, hash: string): ArtifactLink => ({
  role,
  sha256: hash,
  bytes: 12,
  media_type: "text/plain",
  download_path: `/artifacts/${hash}`,
});
const originalResponse = syntheticArtifact("response", "8".repeat(64));
const originalStdout = syntheticArtifact("stdout", "9".repeat(64));
const provider = {
  provider: "google" as const,
  reported_model: "synthetic-returned-model",
  response_id: "synthetic-provider-response",
  usage: {
    prompt_tokens: 120,
    output_tokens: 200,
    total_tokens: 330,
    thought_tokens: 10,
  },
  source_artifact: { ...originalStdout, role: "provider_response" },
  verification: "matched_recorded_response" as const,
};
const originalReview = {
  id: "b".repeat(64),
  attempt_id: ids.task,
  response_sha256: originalResponse.sha256,
  recorded_at: "2026-09-05T12:10:00Z",
  reviewer: "Synthetic source reviewer",
  review_basis: "operator_assessment" as const,
  outcome: "issues_remaining" as const,
  findings: [
    {
      id: "synthetic-source-gap",
      title: "Unsupported synthetic assumption",
      detail: "The synthetic source does not establish this test assumption.",
      source_ids: ["synthetic-source"],
      response_location: "arms[0].reasoning",
    },
  ],
  report: syntheticArtifact("source_review", "a".repeat(64)),
  record_artifact: syntheticArtifact("review_record", "b".repeat(64)),
};
const originalBase = withSelfHistory({
  ...conditional,
  requested_model: "test/requested-model",
  provider_metadata: provider,
  artifacts: [...conditional.artifacts, originalResponse, originalStdout],
  reviews: [originalReview],
});
const revisedResponse = syntheticArtifact("response", "e".repeat(64));
const revisedStdout = syntheticArtifact("stdout", "f".repeat(64));
const revisedBase = withSelfHistory({
  ...conditional,
  id: ids.run,
  requested_model: originalBase.requested_model,
  started_at: "2026-09-05T12:02:00Z",
  finished_at: "2026-09-05T12:02:30Z",
  expires_at: "2026-09-05T12:07:00Z",
  provider_metadata: {
    ...provider,
    response_id: "synthetic-revised-response",
    source_artifact: { ...revisedStdout, role: "provider_response" },
  },
  response: {
    ...conditional.response!,
    reference: distribution(1),
    arms: [
      {
        ...conditional.response!.arms[0],
        distribution: distribution(3),
        baseline_delta: 2,
      },
      {
        ...conditional.response!.arms[1],
        distribution: distribution(1),
        baseline_delta: 0,
      },
    ],
  },
  reference_quantiles: quantiles(1),
  arm_quantiles: [quantiles(3), quantiles(1)],
  artifacts: [...conditional.artifacts, revisedResponse, revisedStdout],
  reviews: [
    {
      ...originalReview,
      id: "ab".repeat(32),
      attempt_id: ids.run,
      response_sha256: revisedResponse.sha256,
      findings: [
        {
          ...originalReview.findings[0],
          title: "Synthetic review findings remain",
          detail: "This recorded revision still has a synthetic reasoning gap.",
        },
      ],
      record_artifact: syntheticArtifact("review_record", "ab".repeat(32)),
    },
  ],
});
const revisionHistory: ConditionalDetail["revision_history"] = [
  originalBase.revision_history[0],
  {
    ...revisedBase.revision_history[0],
    parent_attempt_id: originalBase.id,
    triggering_review_id: originalReview.id,
    feedback: syntheticArtifact("revision_feedback", "d".repeat(64)),
    linked_at: "2026-09-05T12:11:00Z",
    association_basis: "retrospective_association",
    association_artifact: syntheticArtifact("revision_record", "c".repeat(64)),
  },
];
export const reviewedOriginal: ConditionalDetail = {
  ...originalBase,
  revision_history: revisionHistory,
};
export const reviewedRevision: ConditionalDetail = {
  ...revisedBase,
  revision_history: revisionHistory,
};
