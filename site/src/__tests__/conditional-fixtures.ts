/** Synthetic paired forecasts for contract/UI tests only; never product data. */
import type {
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
  observed_model: null,
  execution_state: "succeeded",
  started_at: instant,
  finished_at: "2026-09-05T12:00:30Z",
  error_code: null,
};
export const conditional: ConditionalDetail = {
  ...envelope,
  ...conditionalSummary,
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
};
export const conditionalPage: ConditionalPage = {
  ...envelope,
  items: [conditionalSummary],
  total: 1,
  next_cursor: null,
};
export const unsuccessful = (
  state: "failed" | "unknown",
): ConditionalDetail => ({
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
export const expiredConditional: ConditionalDetail = {
  ...unsuccessful("unknown"),
  ...expiredSummary,
  contract: { ...conditional.contract, title: expiredSummary.title },
  generated_at: "2026-09-05T12:06:00Z",
};
