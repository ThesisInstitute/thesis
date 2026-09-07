import generatedSchema from "@/data/generated/thesis-lab.schema.json";
import { isLabApiPath } from "./lab-paths";
import type * as Lab from "@/data/generated/thesis-lab";

type Schema = boolean | { [key: string]: unknown };
const schema = generatedSchema as unknown as { $defs: Record<string, Schema> };

export interface LabModels {
  ConditionalPage: Lab.ConditionalPage;
  ConditionalDetail: Lab.ConditionalDetail;
  ForecastPage: Lab.ForecastPage;
  ForecastDetail: Lab.ForecastDetail;
  ExperimentPage: Lab.ExperimentPage;
  ExperimentDetail: Lab.ExperimentDetail;
  ComparisonPage: Lab.ComparisonPage;
  MatrixPage: Lab.MatrixPage;
  AttemptPage: Lab.AttemptPage;
  AgentPage: Lab.AgentPage;
  AgentDetail: Lab.AgentDetail;
  ExperimentResultPage: Lab.ExperimentResultPage;
  OperationsSummary: Lab.OperationsSummary;
}
export type LabModel = keyof LabModels;
export class LabShapeError extends Error {
  constructor() {
    super("The response does not match the lab contract.");
  }
}
function fail(): never {
  throw new LabShapeError();
}
const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export function isUtcInstant(value: string): boolean {
  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?Z$/.exec(
      value,
    );
  if (
    !match ||
    Number(match[4]) > 23 ||
    Number(match[5]) > 59 ||
    Number(match[6]) > 59
  )
    return false;
  const instant = new Date(value);
  return (
    Number.isFinite(instant.valueOf()) &&
    instant.getUTCFullYear() === Number(match[1]) &&
    instant.getUTCMonth() + 1 === Number(match[2]) &&
    instant.getUTCDate() === Number(match[3])
  );
}

/** Validate the generated schema, including required nullable fields. No coercion/defaults. */
function validate(value: unknown, rule: Schema, depth = 0): void {
  if (depth > 80 || rule === false) fail();
  if (rule === true) return;
  if (typeof rule.$ref === "string") {
    const name = rule.$ref.replace(/^#\/\$defs\//, "");
    if (!(name in schema.$defs)) fail();
    validate(value, schema.$defs[name], depth + 1);
    return;
  }
  for (const key of ["anyOf", "oneOf"] as const)
    if (Array.isArray(rule[key])) {
      const successes = (rule[key] as Schema[]).filter((candidate) => {
        try {
          validate(value, candidate, depth + 1);
          return true;
        } catch {
          return false;
        }
      }).length;
      if (key === "oneOf" ? successes !== 1 : successes === 0) fail();
    }
  if (Array.isArray(rule.allOf))
    for (const candidate of rule.allOf)
      validate(value, candidate as Schema, depth + 1);
  if ("const" in rule && value !== rule.const) fail();
  if (Array.isArray(rule.enum) && !rule.enum.includes(value)) fail();
  if (rule.type === "null" && value !== null) fail();
  if (rule.type === "boolean" && typeof value !== "boolean") fail();
  if (rule.type === "integer" || rule.type === "number") {
    if (
      typeof value !== "number" ||
      !Number.isFinite(value) ||
      (rule.type === "integer" && !Number.isInteger(value))
    )
      fail();
    const number = value as number;
    if (typeof rule.minimum === "number" && number < rule.minimum) fail();
    if (typeof rule.maximum === "number" && number > rule.maximum) fail();
    if (
      typeof rule.exclusiveMinimum === "number" &&
      number <= rule.exclusiveMinimum
    )
      fail();
    if (
      typeof rule.exclusiveMaximum === "number" &&
      number >= rule.exclusiveMaximum
    )
      fail();
  }
  if (rule.type === "string") {
    if (typeof value !== "string") fail();
    const text = value as string;
    if (typeof rule.minLength === "number" && text.length < rule.minLength)
      fail();
    if (typeof rule.maxLength === "number" && text.length > rule.maxLength)
      fail();
    if (
      typeof rule.pattern === "string" &&
      !new RegExp(rule.pattern).test(text)
    )
      fail();
    if (rule.format === "date-time" && !isUtcInstant(text)) fail();
    if (
      rule.format === "date" &&
      (!/^\d{4}-\d{2}-\d{2}$/.test(text) || !isUtcInstant(`${text}T00:00:00Z`))
    )
      fail();
  }
  if (rule.type === "array") {
    if (!Array.isArray(value)) fail();
    const values = value as unknown[];
    if (typeof rule.minItems === "number" && values.length < rule.minItems)
      fail();
    if (typeof rule.maxItems === "number" && values.length > rule.maxItems)
      fail();
    const prefix = Array.isArray(rule.prefixItems)
      ? (rule.prefixItems as Schema[])
      : [];
    values.forEach((item, index) => {
      const childRule = prefix[index] ?? rule.items;
      if (childRule !== undefined)
        validate(item, childRule as Schema, depth + 1);
    });
  }
  if (rule.type === "object") {
    if (!object(value)) fail();
    const record = value as Record<string, unknown>;
    const properties = (rule.properties ?? {}) as Record<string, Schema>;
    for (const key of (rule.required ?? []) as string[])
      if (!Object.prototype.hasOwnProperty.call(record, key)) fail();
    for (const [key, child] of Object.entries(record)) {
      if (Object.prototype.hasOwnProperty.call(properties, key))
        validate(child, properties[key], depth + 1);
      else if (rule.additionalProperties === false) fail();
      else if (object(rule.additionalProperties))
        validate(child, rule.additionalProperties as Schema, depth + 1);
    }
  }
}

const INSTANT_FIELDS = new Set([
  "generated_at",
  "finished_at",
  "expires_at",
  "retrieved_at",
  "condition_deadline",
  "checked_at",
  "recorded_at",
  "completed_at",
  "started_at",
  "registration_deadline",
  "submission_deadline",
  "declared_information_cutoff",
  "effective_information_boundary",
  "last_activity_at",
  "last_poll_at",
  "next_poll_at",
  "last_success_at",
]);

function semantic(value: unknown): void {
  if (Array.isArray(value)) {
    for (const child of value) semantic(child);
    return;
  }
  if (!object(value)) return;
  for (const [key, child] of Object.entries(value)) {
    if (
      child !== null &&
      INSTANT_FIELDS.has(key) &&
      (typeof child !== "string" || !isUtcInstant(child))
    )
      fail();
    if (
      key === "vintage_date" &&
      child !== null &&
      (typeof child !== "string" ||
        !/^\d{4}-\d{2}-\d{2}$/.test(child) ||
        !isUtcInstant(`${child}T00:00:00Z`))
    )
      fail();
    if (key.endsWith("_path") && child !== null) {
      const template =
        key === "comparisons_path" &&
        child === `/lab/forecasts/${value.id}/comparisons`;
      if (!template && !isLabApiPath(child)) fail();
    }
    if (
      ["official_url", "resolution_source_url", "url"].includes(key) &&
      child !== null
    ) {
      if (typeof child !== "string") fail();
      try {
        const url = new URL(child as string);
        if (
          !["http:", "https:"].includes(url.protocol) ||
          url.username ||
          url.password
        )
          fail();
      } catch {
        fail();
      }
    }
    semantic(child);
  }
  if ("record_path" in value && value.record_path !== `/records/${value.id}`)
    fail();
  if (
    "download_path" in value &&
    value.download_path !== `/artifacts/${value.sha256}`
  )
    fail();
  if (
    "rank_eligible" in value &&
    value.rank_eligible === false &&
    value.rank !== null
  )
    fail();
  if (["replay", "live_pilot"].includes(String(value.mode))) {
    if (
      value.rank_eligible === true ||
      ("rank" in value && value.rank !== null)
    )
      fail();
    if (
      object(value.score) &&
      object(value.score.eligibility) &&
      (value.score.eligibility.reward !== null ||
        value.score.eligibility.ranking_allowed !== false)
    )
      fail();
  }
  if (
    object(value.agent) &&
    "forecaster_id" in value &&
    value.agent.id !== value.forecaster_id
  )
    fail();
  if (
    object(value.mode_counts) &&
    Object.values(value.mode_counts).reduce<number>(
      (a, b) => a + Number(b),
      0,
    ) !== value.experiment_count
  )
    fail();
  if ("declared_tasks" in value) {
    const count = [
      "succeeded_tasks",
      "failed_tasks",
      "unknown_tasks",
      "queued_tasks",
      "running_tasks",
      "not_scheduled_tasks",
      "invalid_tasks",
    ].reduce((sum, key) => sum + Number(value[key]), 0);
    if (count !== value.declared_tasks) fail();
    for (const key of ["selected_tasks", "eligible_tasks"])
      if (Number(value[key]) > Number(value.declared_tasks)) fail();
    for (const key of ["resolved_targets", "paired_targets"])
      if (Number(value[key]) > Number(value.declared_targets)) fail();
  }
  if (
    "paired_coverage" in value &&
    Number(value.paired_coverage) > Number(value.targets)
  )
    fail();
  if (value.state === "verified" && "official_url" in value) {
    if (
      typeof value.lower !== "string" ||
      typeof value.upper !== "string" ||
      !isUtcInstant(value.lower) ||
      !isUtcInstant(value.upper) ||
      Date.parse(value.lower) > Date.parse(value.upper)
    )
      fail();
  }
  if (
    "q10" in value &&
    (Number(value.q10) > Number(value.q50) ||
      Number(value.q50) > Number(value.q90))
  )
    fail();
  if (
    "distribution" in value &&
    value.distribution !== null &&
    value.selected_run === null
  )
    fail();
  if (
    "items" in value &&
    Array.isArray(value.items) &&
    Number(value.total) < value.items.length
  )
    fail();
  if (
    value.state === "resolved" &&
    "resolution" in value &&
    (value.value === null ||
      value.resolution === null ||
      value.observation === null)
  )
    fail();
  if (
    (value.state === "pending" || value.state === "invalid") &&
    "resolution" in value &&
    value.value !== null
  )
    fail();
  if (value.format === "numeric_cdf_v1" || "pointCount" in value) {
    const cdf = value as unknown as Lab.NumericCdf;
    if (
      cdf.points.length !== 201 ||
      cdf.pointCount !== 201 ||
      cdf.format !== "numeric_cdf_v1"
    )
      fail();
    if (
      cdf.points[0].probability !== 0 ||
      cdf.points[200].probability !== 1 ||
      cdf.support.lower !== cdf.points[0].value ||
      cdf.support.upper !== cdf.points[200].value
    )
      fail();
    for (let i = 0; i < cdf.points.length; i++)
      if (
        cdf.points[i].probability < 0 ||
        cdf.points[i].probability > 1 ||
        (i > 0 &&
          (cdf.points[i].value <= cdf.points[i - 1].value ||
            cdf.points[i].probability < cdf.points[i - 1].probability))
      )
        fail();
  }
}

function conditionalSummary(value: Lab.ConditionalSummary): void {
  if (
    value.status !== "exploratory" ||
    value.scoring_status !== "not_registered" ||
    value.trust_class !== "local_operator" ||
    value.observed_model !== null ||
    (value.execution_state === "running" && value.finished_at !== null) ||
    (value.execution_state !== "running" &&
      !(
        value.execution_state === "unknown" &&
        value.error_code === "lease_expired"
      ) &&
      value.finished_at === null) ||
    ["failed", "unknown"].includes(value.execution_state) !==
      (value.error_code !== null) ||
    (value.finished_at !== null &&
      Date.parse(value.finished_at) < Date.parse(value.started_at))
  )
    fail();
}

/** A conditional pair joins only its frozen contract and native distributions. */
function conditionalDetail(value: Lab.ConditionalDetail): void {
  conditionalSummary(value);
  const { contract, response } = value;
  if (
    contract.schema_version !== "thesis_conditional_contract_v1" ||
    contract.methodology !== "paired_conditional_v1" ||
    contract.status !== value.status ||
    contract.scoring_status !== value.scoring_status ||
    contract.trust_class !== value.trust_class ||
    contract.title !== value.title ||
    contract.question !== value.question ||
    contract.outcome.unit !== value.unit ||
    contract.outcome.measurement_period !== value.measurement_period ||
    contract.arms.length !== 2 ||
    contract.arms[0].id === contract.arms[1].id ||
    Date.parse(value.expires_at) <= Date.parse(value.started_at)
  )
    fail();
  const sourceIds = new Set(contract.sources.map((source) => source.id));
  if (sourceIds.size !== contract.sources.length) fail();
  for (const history of contract.shared_history)
    if (!sourceIds.has(history.source_id)) fail();
  for (const evidence of contract.shared_evidence)
    for (const id of evidence.source_ids) if (!sourceIds.has(id)) fail();
  if (
    contract.outcome.release_date !== null &&
    !isUtcInstant(`${contract.outcome.release_date}T00:00:00Z`)
  )
    fail();
  if (value.execution_state !== "succeeded") {
    if (
      response !== null ||
      value.reference_quantiles !== null ||
      value.arm_quantiles.length !== 0
    )
      fail();
    return;
  }
  if (
    response === null ||
    value.reference_quantiles === null ||
    value.arm_quantiles.length !== 2 ||
    response.contract_id !== value.contract_id ||
    response.shared_evidence_id !== value.shared_evidence_id ||
    response.arms.length !== 2
  )
    fail();
  const paired = response as Lab.PairedModelResponse;
  paired.arms.forEach((arm, i) => {
    if (arm.id !== contract.arms[i].id) fail();
  });
  const close = (a: number, b: number) => Math.abs(a - b) <= 1e-8;
  const distributions = [
    paired.reference,
    ...paired.arms.map((arm) => arm.distribution),
  ];
  const quantiles = [value.reference_quantiles!, ...value.arm_quantiles];
  distributions.forEach((distribution, index) => {
    if (
      distribution.provenance !== "agent_reported" ||
      distribution.transformVersion !== "native_conditional_v1"
    )
      fail();
    const inverse = (probability: number) => {
      const i = distribution.points.findIndex(
        (point) => point.probability >= probability,
      );
      if (i < 0) fail();
      const point = distribution.points[i];
      if (i === 0 || point.probability === probability) return point.value;
      const previous = distribution.points[i - 1];
      return (
        previous.value +
        ((point.value - previous.value) *
          (probability - previous.probability)) /
          (point.probability - previous.probability)
      );
    };
    const q = quantiles[index];
    if (
      !close(q.q10, inverse(0.1)) ||
      !close(q.q50, inverse(0.5)) ||
      !close(q.q90, inverse(0.9)) ||
      !close(distribution.summary.pointEstimate, q.q50) ||
      !close(distribution.summary.median, q.q50) ||
      !close(distribution.summary.interval80.lower, q.q10) ||
      !close(distribution.summary.interval80.upper, q.q90)
    )
      fail();
  });
  paired.arms.forEach((arm, i) => {
    if (
      !close(
        arm.baseline_delta,
        value.arm_quantiles[i].q50 - value.reference_quantiles!.q50,
      )
    )
      fail();
  });
}

export function parseLab<M extends LabModel>(
  model: M,
  value: unknown,
): LabModels[M] {
  const rule = schema.$defs[model];
  if (!rule) fail();
  validate(value, rule);
  semantic(value);
  if (model === "ConditionalDetail")
    conditionalDetail(value as Lab.ConditionalDetail);
  if (model === "ConditionalPage")
    for (const item of (value as Lab.ConditionalPage).items)
      conditionalSummary(item);
  if (model === "MatrixPage") {
    const matrix = value as Lab.MatrixPage;
    if (
      matrix.rows.length > 20 ||
      matrix.columns.length > 10 ||
      matrix.total_targets < matrix.rows.length ||
      matrix.total_methods < matrix.columns.length
    )
      fail();
    for (const row of matrix.rows) {
      if (row.cells.length !== matrix.columns.length) fail();
      if (row.forecast_path !== `/lab/forecasts/${row.target_id}`) fail();
      row.cells.forEach((cell, i) => {
        if (
          cell.target_id !== row.target_id ||
          cell.forecaster_id !== matrix.columns[i].forecaster_id ||
          cell.mode !== matrix.mode
        )
          fail();
        if (
          cell.comparison_path !==
          `/lab/forecasts/${row.target_id}/comparisons?experiment_id=${matrix.experiment_id}`
        )
          fail();
        if (
          cell.task === null &&
          (cell.execution.state !== "invalid" ||
            cell.execution.attempt_counts.total !== 0 ||
            cell.execution.attempts_path !== null ||
            cell.selected_run !== null ||
            cell.quantiles !== null ||
            cell.score.eligibility.state !== "ineligible")
        )
          fail();
      });
    }
  }
  return value as LabModels[M];
}
