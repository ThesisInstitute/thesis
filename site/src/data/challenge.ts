import {
  FORECAST_CELLS,
  type ExternalSubmissionAttribution,
  type ForecastCell,
  type ForecastComparisonRun,
} from "./forecast-cells";

// FROZEN registry of the two accepted challenge-lane v1 submissions
// (docs/open-challenge.md — lane withdrawn 2026-08-23; v2 lives on branch
// challenge-lane-v2). No new entries: intake is closed. The consistency
// test in __tests__/challenge-lane.test.ts keeps this in lockstep with
// the inbox artifacts and FORECAST_COMPARISON_RUN_AUGMENTS.
export interface ChallengeSubmissionRecord {
  /** GitHub identity from the submission's `challenger` field. */
  challenger: string;
  systemType: ExternalSubmissionAttribution["systemType"];
  /** Self-reported system name from the submission. */
  systemName: string;
  /** Catalog cell the submission targets. */
  cellSlug: string;
  /** Comparison-run variant carrying this submission on the cell. */
  variantId: string;
  /** Registered target the submission forecasts. */
  dataPointId: string;
  /** Merged inbox file, relative to the repository root. */
  inboxPath: string;
  /** Witnessed records digest that published the submission. */
  recordsDigest: string;
  /** Challenger-claimed generation time; chronology never trusts it. */
  submittedAtUtc: string;
}

export const CHALLENGE_SUBMISSIONS: ChallengeSubmissionRecord[] = [
  {
    challenger: "github:PavelMakarchuk",
    systemType: "ai",
    systemName: "Claude Fable 5 (pavel onboarding agent)",
    cellSlug: "jolts-hires-rate-june-2026",
    variantId:
      "jolts-hires-rate-june-2026-challenge-github-pavelmakarchuk-2026-07-31t14-00-26z",
    dataPointId: "bls.jolts.hires_rate.2026_06.first_print",
    inboxPath: "challenge/inbox/pavel/jolts-hires-rate.json",
    recordsDigest: "records/2026-07-31/digest-30648581183-1.json",
    submittedAtUtc: "2026-07-31T14:00:26Z",
  },
  {
    challenger: "github:khs",
    systemType: "ai",
    systemName: "Claude Opus 5 (Claude Code)",
    cellSlug: "u6-underemployment-rate-july-2026",
    variantId:
      "u6-underemployment-rate-july-2026-challenge-github-khs-2026-07-31t14-05-19z",
    dataPointId: "bls.cps.u6_underemployment_rate.2026_07.first_print",
    inboxPath: "challenge/inbox/keller-scholl/u6-underemployment-rate.json",
    recordsDigest: "records/2026-07-31/digest-30648581183-1.json",
    submittedAtUtc: "2026-07-31T14:05:19Z",
  },
];

export interface ChallengeSubmissionView extends ChallengeSubmissionRecord {
  cell: ForecastCell;
  run: ForecastComparisonRun;
}

/**
 * Registry entries joined onto their catalog cells. Throws when a registry
 * row has no matching cell or comparison run — the build should fail loudly
 * rather than render a submission that no longer exists.
 */
export function listChallengeSubmissions(
  cells: ForecastCell[] = FORECAST_CELLS,
): ChallengeSubmissionView[] {
  const cellsBySlug = new Map(cells.map((cell) => [cell.slug, cell]));
  return CHALLENGE_SUBMISSIONS.map((record) => {
    const cell = cellsBySlug.get(record.cellSlug);
    if (!cell) {
      throw new Error(
        `challenge registry names unknown cell slug ${record.cellSlug}`,
      );
    }
    const run = (cell.comparisonRuns ?? []).find(
      (candidate) => candidate.variantId === record.variantId,
    );
    if (!run) {
      throw new Error(
        `challenge registry names unknown comparison run ${record.variantId}`,
      );
    }
    return { ...record, cell, run };
  });
}
