/** Synthetic contract fixtures for tests only; never imported by product code. */
import type * as Lab from "@/data/generated/thesis-lab";
export const ids = {
  target: "1".repeat(64),
  agent: "2".repeat(64),
  task: "3".repeat(64),
  experiment: "4".repeat(64),
  artifact: "5".repeat(64),
  run: "6".repeat(64),
  source: "7".repeat(64),
};
export const instant = "2026-09-05T12:00:00Z";
export const envelope = {
  schema_version: "thesis_lab_v1" as const,
  generated_at: instant,
};
export const record = (
  id: string,
  kind = "target_version",
): Lab.RecordLink => ({ id, kind, record_path: `/records/${id}` });
export const cost: Lab.Cost = {
  amount: null,
  currency: null,
  state: "not_reported",
};
export const counts: Lab.AttemptCounts = {
  total: 1,
  succeeded: 1,
  failed: 0,
  unknown: 0,
  pending: 0,
  reconciled: 0,
  unknown_history: 0,
};
export const coverage: Lab.Coverage = {
  declared_targets: 1,
  declared_tasks: 1,
  selected_tasks: 1,
  succeeded_tasks: 1,
  failed_tasks: 0,
  unknown_tasks: 0,
  queued_tasks: 0,
  running_tasks: 0,
  not_scheduled_tasks: 0,
  invalid_tasks: 0,
  resolved_targets: 0,
  eligible_tasks: 0,
  paired_targets: 0,
};
export const agent: Lab.AgentIdentity = {
  id: ids.agent,
  label: "Recorded forecaster v1",
  provider: "operator",
  model_request: "registered-model",
  observed_model: null,
  agent_version: "v1",
  harness_version: "h1",
};
export const release: Lab.ReleaseSummary = {
  state: "verified",
  lower: "2026-09-14T04:00:00Z",
  upper: "2026-09-15T04:00:00Z",
  raw_value: "September 14, 2026",
  timezone: "America/Toronto",
  official_url: "https://www.statcan.gc.ca/official-release",
  evidence: null,
};
export const resolution: Lab.ResolutionSummary = {
  state: "pending",
  resolution: null,
  observation: null,
  value: null,
  unit: "percent",
  recorded_at: null,
  reason_code: null,
};
export const score: Lab.ScoreSummary = {
  score: null,
  crps: null,
  normalized_crps: null,
  pit: null,
  scoring_version: null,
  eligibility: {
    state: "ineligible",
    reason_codes: ["live_pilot"],
    ranking_allowed: false,
    reward: null,
  },
};
export const execution: Lab.ExecutionSummary = {
  state: "succeeded",
  attempt_counts: counts,
  elapsed_seconds: null,
  elapsed_basis: null,
  cost,
  attempts_path: `/lab/tasks/${ids.task}/attempts`,
};
export const forecast: Lab.ForecastSummary = {
  id: ids.target,
  title: "Canadian CPI · August 2026",
  source: {
    id: ids.source,
    name: "Canadian CPI",
    adapter_id: "statcan-cpi-yoy",
  },
  measurement_period: "2026-08",
  unit: "percent",
  mode_counts: { prospective: 0, replay: 0, live_pilot: 1 },
  experiment_count: 1,
  coverage,
  release,
  resolution,
};
export const forecastPage: Lab.ForecastPage = {
  ...envelope,
  items: [forecast],
  total: 1,
  next_cursor: null,
};
export const forecastDetail: Lab.ForecastDetail = {
  ...envelope,
  ...forecast,
  target: record(ids.target),
  target_label: forecast.title,
  resolution_rule: "Resolve against the registered official CPI vintage.",
  resolution_policy: "fixed_vintage",
  vintage_date: "2026-09-14",
  submission_deadline: "2026-09-14T03:59:00Z",
  source_record: record(ids.source, "source_series"),
  experiments_path: `/lab/forecasts/${ids.target}/experiments`,
  comparisons_path: `/lab/forecasts/${ids.target}/comparisons`,
  evidence_links: [],
};
export const distribution: Lab.NumericCdf = {
  format: "numeric_cdf_v1",
  pointCount: 201,
  support: { lower: 0, upper: 10 },
  points: Array.from({ length: 201 }, (_, i) => ({
    value: i / 20,
    probability: i / 200,
  })),
  summary: { pointEstimate: 7, median: 7, interval80: { lower: 6, upper: 8 } },
  provenance: "agent_reported",
  transformVersion: "native-v1",
};
export const comparison: Lab.TaskComparison = {
  task: record(ids.task, "evaluation_task"),
  target_id: ids.target,
  experiment_id: ids.experiment,
  agent,
  is_baseline: false,
  mode: "live_pilot",
  execution,
  selected_run: record(ids.run, "forecast_run"),
  distribution,
  quantiles: {
    method: "inverse_piecewise_linear_cdf_v1",
    q10: 1,
    q50: 5,
    q90: 9,
  },
  resolution,
  score,
  declared_information_cutoff: instant,
  effective_information_boundary: "2026-09-05T11:59:59Z",
  submission_deadline: "2026-09-14T03:59:00Z",
  evidence_links: [],
};
export const matrix: Lab.MatrixPage = {
  ...envelope,
  experiment_id: ids.experiment,
  experiment_title: "CPI pilot",
  mode: "live_pilot",
  columns: [{ forecaster_id: ids.agent, agent, is_baseline: false }],
  rows: [
    {
      target_id: ids.target,
      title: forecast.title,
      measurement_period: "2026-08",
      unit: "percent",
      forecast_path: `/lab/forecasts/${ids.target}`,
      cells: [
        {
          target_id: ids.target,
          forecaster_id: ids.agent,
          task: comparison.task,
          mode: comparison.mode,
          execution,
          selected_run: comparison.selected_run,
          quantiles: comparison.quantiles,
          resolution,
          score,
          declared_information_cutoff: instant,
          effective_information_boundary:
            comparison.effective_information_boundary,
          submission_deadline: comparison.submission_deadline,
          comparison_path: `/lab/forecasts/${ids.target}/comparisons?experiment_id=${ids.experiment}`,
        },
      ],
    },
  ],
  total_targets: 1,
  total_methods: 1,
  next_cursor: null,
  next_method_cursor: null,
};
export const experimentDetail: Lab.ExperimentDetail = {
  ...envelope,
  id: ids.experiment,
  title: "CPI pilot",
  hypothesis: null,
  mode: "live_pilot",
  baseline: agent,
  target_count: 1,
  agent_count: 1,
  registration_deadline: instant,
  coverage,
  rank_eligible_agent_count: 0,
  record: record(ids.experiment, "experiment"),
  ranking_policy: "unranked_live_pilot_v1",
  declared_information_cutoff: instant,
  effective_information_boundary: "2026-09-05T11:59:59Z",
  matrix_path: `/lab/experiments/${ids.experiment}/matrix`,
  results_path: `/lab/experiments/${ids.experiment}/results`,
};
export const operations: Lab.OperationsSummary = {
  ...envelope,
  database: { state: "available", checked_at: instant },
  jobs: {
    pending: 0,
    leased: 0,
    complete: 10,
    failed: 0,
    unknown: 0,
    expired_leases: 0,
  },
  worker: { state: "unknown", last_activity_at: null, basis: "not_reported" },
  polling: {
    state: "not_scheduled",
    scheduled_sources: 0,
    next_poll_at: null,
    last_success_at: null,
    worker: { status: "never_seen", last_poll_at: null },
  },
  items: [],
  total: 0,
  next_cursor: null,
};
