// Why each overdue forecast has not resolved.
//
// `resolution-status.json` is written by `scripts/resolution_status.py`
// at the end of every resolver run (see resolve-and-rebuild.yml). Each row
// restates what the resolver printed about one pending target whose
// resolution date has passed, or the fact that no resolver covers it.
// Nothing here decides anything: a forecast is "overdue" only because it
// is still pending after the date it said it would resolve.
import rawStatus from "./resolution-status.json";

export interface OverdueStatus {
  dataPointId: string;
  forecastSlug: string;
  resolutionDate: string;
  state: string;
  code: string;
  reason: string;
  detail?: string;
}

interface StatusFile {
  schemaVersion: string;
  asOf: string;
  generatedAtUtc: string;
  workflowRun: string;
  run: { logAvailable: boolean; completed: boolean; error: string };
  targets: Record<string, Omit<OverdueStatus, "dataPointId">>;
}

const status = rawStatus as StatusFile;

export const RESOLUTION_STATUS_META = {
  asOf: status.asOf,
  generatedAtUtc: status.generatedAtUtc,
  workflowRun: status.workflowRun,
  runCompleted: status.run.completed,
};

/** Pending targets past their date when the file was written. */
export const OVERDUE_TARGET_COUNT = Object.keys(status.targets).length;

/** Said when a forecast is past due and the status file has no row for
 * it, for example one published after the last resolver run. */
export const NO_REPORT_REASON =
  "No resolver run has reported on this target yet.";

const bySlug = new Map<string, OverdueStatus>();
for (const [dataPointId, row] of Object.entries(status.targets)) {
  // Earliest-due row wins when a slug has more than one target.
  const existing = bySlug.get(row.forecastSlug);
  if (!existing || row.resolutionDate < existing.resolutionDate) {
    bySlug.set(row.forecastSlug, { dataPointId, ...row });
  }
}

export interface OverdueNotice {
  since: string;
  code: string;
  reason: string;
  detail?: string;
}

/** The overdue notice for a forecast, or null when it is not overdue.
 *
 * A resolved forecast never gets one, whatever the file says: the file is
 * as old as the last resolver run and the ledger may be newer. "Past due"
 * is judged against the status file's own `asOf` date, not the build
 * clock, so the page and the file cannot disagree about what day it is. */
export function overdueNotice(
  forecast: { slug: string; status: "pending" | "resolved"; resolutionDate: string },
  file: { asOf: string; lookup: (slug: string) => OverdueStatus | undefined } = {
    asOf: status.asOf,
    lookup: (slug) => bySlug.get(slug),
  },
): OverdueNotice | null {
  if (forecast.status !== "pending") return null;
  const due = forecast.resolutionDate.slice(0, 10);
  if (!(due < file.asOf)) return null;
  const row = file.lookup(forecast.slug);
  if (!row) return { since: due, code: "NO_REPORT", reason: NO_REPORT_REASON };
  return {
    since: due,
    code: row.code,
    reason: row.reason,
    ...(row.detail ? { detail: row.detail } : {}),
  };
}

/** First sentence of a reason, for the compact card. */
export function shortReason(reason: string): string {
  const end = reason.indexOf(". ");
  return end === -1 ? reason : reason.slice(0, end + 1);
}
