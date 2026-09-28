import frozen from "./trace-provenance-frozen.json";

/**
 * Legacy structural labels for reasoning records, not publication eligibility.
 *
 * - "activity_backed": metadata references activity artifacts. This classifier
 *   does not open artifacts or prove that narrated tool calls were executed.
 * - "recorded_run": a real agent research run from before on-repo activity
 *   archives existed — honest process, weaker receipts.
 * - "illustrative": the trace was AUTHORED from source context when the
 *   cell was created; tool-call signatures were not executed. Numbers were
 *   transcribed from real releases at authoring time.
 *
 * The frozen registry pins today's non-activity-backed population and is
 * shrink-only: a cell may leave it by being regenerated through the real
 * pipeline, and no new cell may ever join it — the trace-provenance test
 * fails the build on any cell that is neither activity-backed nor frozen,
 * Publication separately requires the server-side forecast-publication gate;
 * this frozen registry alone cannot authenticate a forecast or its tool claims.
 */
export type TraceProvenance =
  | "activity_backed"
  | "recorded_run"
  | "illustrative";

const RECORDED_RUN_MODELS = new Set([
  "gpt-5-codex",
  "claude-fable-5",
  "Codex recorded agent run",
  "Codex recorded agent runs",
  "Codex recorded agent ensemble",
  // Deterministic component chain: its steps describe a computation that
  // actually ran, not external tool calls.
  "damped_log_trend_v1 + Brier component chain",
]);

interface TraceProvenanceFields {
  custodyRootSha256?: string;
  activityLog?: unknown[];
  predictionRun?: {
    custodyRootSha256?: string;
    activityLog?: unknown[];
    model?: string;
  };
  model?: string;
}

export function classifyTraceProvenance(
  cell: TraceProvenanceFields,
): TraceProvenance {
  const run = cell.predictionRun;
  if (
    cell.custodyRootSha256 ||
    run?.custodyRootSha256 ||
    (cell.activityLog?.length ?? 0) > 0 ||
    (run?.activityLog?.length ?? 0) > 0
  ) {
    return "activity_backed";
  }
  const model = run?.model ?? cell.model;
  if (model && RECORDED_RUN_MODELS.has(model)) {
    return "recorded_run";
  }
  // Unknown or synthesis-labeled models default to the conservative class:
  // an unlabeled trace without activity archives is presented as authored.
  return "illustrative";
}

export const FROZEN_PRE_CUSTODY_SLUGS: ReadonlySet<string> = new Set(
  frozen.slugs,
);
