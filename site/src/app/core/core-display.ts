/**
 * Prose for every reading the `/core` tables can produce.
 *
 * These strings are the honesty surface of the page, so they are pure
 * functions with their own tests. The distinctions they preserve:
 *
 * - "not available" — the API reported no value (an explicit null).
 * - "not reported"  — the API never mentioned the field.
 * - "unrecognized"  — the API sent something this page cannot read.
 *
 * None of those ever render as `0`, as an empty exclusion list, or as a
 * prospective claim.
 */

import { truncateForDisplay } from "./core-contracts";
import type {
  ExclusionsReading,
  ModeReading,
  Reading,
  CoreCoverage,
  TimestampReading,
  TimingOrdering,
} from "./core-contracts";

export const DECLARED_CUTOFF_LABEL = "Declared scheduling cutoff";
export const EFFECTIVE_BOUNDARY_LABEL =
  "Effective information boundary (bundle freeze)";
export const TIMING_CHECK_LABEL = "Timing check";
export const NOT_REPORTED = "not reported";
export const NOT_REPORTED_UNRECOGNIZED = "not reported (unrecognized value)";

export function describeTimestamp(reading: TimestampReading): string {
  switch (reading.state) {
    case "value":
      // Real instants are ~35 characters; the bound is only a layout guard,
      // and the ellipsis shows when it bites.
      return truncateForDisplay(reading.value, 64);
    case "null":
      return "not available";
    case "unrecognized":
      return NOT_REPORTED_UNRECOGNIZED;
    case "missing":
      return NOT_REPORTED;
  }
}

/** Which API field a shown timestamp came from, for a title/tooltip. */
export function describeTimestampSource(reading: TimestampReading): string {
  switch (reading.state) {
    case "value":
      return `read from \`${reading.field}\``;
    case "null":
      return `\`${reading.field}\` was reported as null`;
    case "unrecognized":
      return `\`${reading.field}\` was present but unreadable`;
    case "missing":
      return "no recognized field was present";
  }
}

export function describeMode(reading: ModeReading): string {
  switch (reading.state) {
    case "value":
      return reading.value === "prospective" ? "Prospective" : "Replay";
    case "unrecognized":
      return reading.raw
        ? `Mode unrecognized (${reading.raw})`
        : "Mode unrecognized";
    case "missing":
      return "Mode not reported";
  }
}

export function describeOrdering(ordering: TimingOrdering): string {
  switch (ordering.state) {
    case "prospective_satisfied":
      return "Bundle frozen before the declared cutoff.";
    case "prospective_violated":
      return "Bundle freeze is not before the declared cutoff — prospective ordering unmet.";
    case "replay_later_freeze":
      return "Replay: bundle assembled after the historical cutoff.";
    case "replay_within_cutoff":
      // Comparison resolution is one millisecond; "at or before" is the
      // strongest claim that resolution supports.
      return "Replay: bundle assembled at or before the historical cutoff.";
    case "not_assessable":
      switch (ordering.reason) {
        case "mode-missing":
          return "Not assessable: mode not reported.";
        case "mode-unrecognized":
          return "Not assessable: mode is not a recognized value.";
        case "missing-timestamp":
          return "Not assessable: a timing field is not reported.";
        case "unparseable-timestamp":
          return "Not assessable: a timing field is not a readable timestamp.";
        case "unzoned-timestamp":
          return "Not assessable: a timing field carries no timezone, so the order would depend on the reader's.";
      }
  }
}

/**
 * An unranked row says so, and says why when the API told us: a cohort with
 * incomplete eligible paired coverage gets no rank rather than a flattering
 * partial average.
 */
export function describeRank(
  reading: Reading<number>,
  rankEligible: Reading<boolean> = { state: "missing" },
): string {
  const ineligible =
    rankEligible.state === "value" && rankEligible.value === false
      ? " (not rank-eligible)"
      : "";
  switch (reading.state) {
    case "value":
      // A rank alongside rank_eligible=false is the API contradicting itself;
      // show both rather than quietly picking the flattering one.
      return `${reading.value}${ineligible}`;
    case "null":
      return `not ranked${ineligible}`;
    case "unrecognized":
      return NOT_REPORTED_UNRECOGNIZED;
    case "missing":
      return `${NOT_REPORTED}${ineligible}`;
  }
}

/** Full precision, no rounding: a displayed score must equal the recorded one. */
export function describeScore(reading: Reading<number>): string {
  switch (reading.state) {
    case "value":
      return String(reading.value);
    case "null":
      return "not available";
    case "unrecognized":
      return NOT_REPORTED_UNRECOGNIZED;
    case "missing":
      return NOT_REPORTED;
  }
}

export function describeCoverage(reading: Reading<CoreCoverage>): string {
  switch (reading.state) {
    case "value":
      return `${reading.value.eligible} / ${reading.value.total}`;
    case "null":
      return "not available";
    case "unrecognized":
      return NOT_REPORTED_UNRECOGNIZED;
    case "missing":
      return NOT_REPORTED;
  }
}

export function describeIdentifier(reading: Reading<string>): string {
  switch (reading.state) {
    case "value":
      return reading.value;
    case "null":
      return "not available";
    case "unrecognized":
      return NOT_REPORTED_UNRECOGNIZED;
    case "missing":
      return NOT_REPORTED;
  }
}

/**
 * An empty exclusion list is a claim ("nothing was excluded"); a missing one
 * is not. They must never read the same.
 */
export function describeExclusions(reading: ExclusionsReading): string {
  switch (reading.state) {
    case "value": {
      const unreadable =
        reading.unreadable > 0
          ? `${reading.unreadable} unreadable entr${reading.unreadable === 1 ? "y" : "ies"}`
          : "";
      if (reading.value.length === 0) {
        return unreadable || "none recorded";
      }
      return unreadable
        ? `${reading.value.join(", ")}; ${unreadable}`
        : reading.value.join(", ");
    }
    case "null":
      return "not available";
    case "unrecognized":
      return NOT_REPORTED_UNRECOGNIZED;
    case "missing":
      return NOT_REPORTED;
  }
}

export function describeSchemaVersion(reading: Reading<number>): string {
  switch (reading.state) {
    case "value":
      return String(reading.value);
    case "null":
      return "not available";
    case "unrecognized":
      return NOT_REPORTED_UNRECOGNIZED;
    case "missing":
      return NOT_REPORTED;
  }
}
