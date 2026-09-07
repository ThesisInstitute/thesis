/**
 * Runtime shape validation for everything `/core` reads through the proxy.
 *
 * The core API is a separate service on its own release cycle, so the browser
 * treats every response as untrusted input: nothing is destructured on faith,
 * and no field is allowed to acquire a plausible-looking default. A metric the
 * API did not report renders as "not reported", never as `0`, never as an
 * empty exclusion list, and never as a prospective claim.
 */

/** Values the API may return for a row's experiment mode. */
export type CoreMode = "prospective" | "replay" | "live_pilot";

/**
 * A field reading that keeps the difference between "the API said there is no
 * value", "the API did not mention this field" and "the API sent something we
 * do not understand". Collapsing those three is how a scoreboard starts
 * lying.
 */
export type Reading<T> =
  | { state: "value"; value: T }
  | { state: "null" }
  | { state: "missing" }
  | { state: "unrecognized" };

export type ModeReading =
  | { state: "value"; value: CoreMode }
  | { state: "missing" }
  | { state: "unrecognized"; raw: string };

export class CoreShapeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CoreShapeError";
  }
}

export function isRecordObject(
  value: unknown,
): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Bound any echoed API string so a hostile payload cannot wreck the page. */
export function truncateForDisplay(value: string, max = 120): string {
  return value.length <= max ? value : `${value.slice(0, max)}…`;
}

// ---------------------------------------------------------------------------
// Collection pages: { items: [{ id, kind, payload }], next_cursor: null|string }
// ---------------------------------------------------------------------------

export interface CoreRecordItem {
  id: string;
  kind: string;
  /** The canonical record payload, exactly as recorded. */
  payload: Record<string, unknown>;
  /**
   * The whole API item. `thesis_core/api.py` projects `mode`,
   * `information_cutoff` and `effective_information_boundary` as siblings of
   * `payload` (an Experiment payload has no cutoff of its own), so timing is
   * read from here first and from the payload only as a fallback.
   */
  summary: Record<string, unknown>;
}

export interface CoreListPage {
  items: CoreRecordItem[];
  /** A non-null cursor means the view is showing a page, not the whole set. */
  nextCursor: string | null;
  /** Rows dropped for failing the record shape. Surfaced, never swallowed. */
  rejectedItems: number;
}

export function parseCoreListPage(value: unknown): CoreListPage {
  if (!isRecordObject(value)) {
    throw new CoreShapeError("response body is not a JSON object");
  }
  if (!Array.isArray(value.items)) {
    throw new CoreShapeError("response is missing an `items` array");
  }
  const cursorRaw = value.next_cursor;
  let nextCursor: string | null;
  if (cursorRaw === undefined || cursorRaw === null) {
    nextCursor = null;
  } else if (typeof cursorRaw === "string") {
    nextCursor = cursorRaw;
  } else {
    throw new CoreShapeError("`next_cursor` is neither a string nor null");
  }

  const items: CoreRecordItem[] = [];
  let rejectedItems = 0;
  for (const entry of value.items) {
    if (
      !isRecordObject(entry) ||
      typeof entry.id !== "string" ||
      entry.id.length === 0 ||
      typeof entry.kind !== "string" ||
      entry.kind.length === 0 ||
      !isRecordObject(entry.payload)
    ) {
      rejectedItems += 1;
      continue;
    }
    items.push({
      id: entry.id,
      kind: truncateForDisplay(entry.kind, 64),
      payload: entry.payload,
      summary: entry,
    });
  }
  return { items, nextCursor, rejectedItems };
}

// ---------------------------------------------------------------------------
// Health: { status: 'ok', schema_version: 1 }
// ---------------------------------------------------------------------------

export interface CoreHealth {
  status: string;
  schemaVersion: Reading<number>;
}

export function parseCoreHealth(value: unknown): CoreHealth {
  if (!isRecordObject(value)) {
    throw new CoreShapeError("health body is not a JSON object");
  }
  if (typeof value.status !== "string" || value.status.length === 0) {
    throw new CoreShapeError("health response is missing a `status` string");
  }
  return {
    status: truncateForDisplay(value.status, 40),
    schemaVersion: readIntegerField(value, "schema_version", { minimum: 1 }),
  };
}

// ---------------------------------------------------------------------------
// Leaderboard rows
// ---------------------------------------------------------------------------

export interface CoreCoverage {
  eligible: number;
  total: number;
}

const ATTEMPT_COUNT_KEYS = [
  "total",
  "succeeded",
  "failed",
  "unknown",
  "pending",
  "reconciled",
  "unknown_history",
] as const;

export type CoreAttemptCounts = Record<
  (typeof ATTEMPT_COUNT_KEYS)[number],
  number
>;

export interface LeaderboardRow {
  experimentId: Reading<string>;
  forecasterId: Reading<string>;
  mode: ModeReading;
  rank: Reading<number>;
  /** The API's own statement of whether this row could be ranked at all. */
  rankEligible: Reading<boolean>;
  coverage: Reading<CoreCoverage>;
  meanNormalizedCrps: Reading<number>;
  attemptCounts: Reading<CoreAttemptCounts>;
  meanLatencySeconds: Reading<number>;
  exclusions: ExclusionsReading;
  /** Leaderboard rows carry the same two timing disclosures as record rows. */
  timing: TimingSummary;
}

export interface CoreLeaderboard {
  items: LeaderboardRow[];
  rejectedItems: number;
}

export function parseCoreLeaderboard(value: unknown): CoreLeaderboard {
  if (!isRecordObject(value)) {
    throw new CoreShapeError("leaderboard body is not a JSON object");
  }
  if (!Array.isArray(value.items)) {
    throw new CoreShapeError("leaderboard is missing an `items` array");
  }
  const items: LeaderboardRow[] = [];
  let rejectedItems = 0;
  for (const entry of value.items) {
    if (!isRecordObject(entry)) {
      rejectedItems += 1;
      continue;
    }
    items.push({
      experimentId: readStringField(entry, "experiment_id"),
      forecasterId: readStringField(entry, "forecaster_id"),
      mode: readMode(entry),
      rank: readIntegerField(entry, "rank", { minimum: 1 }),
      rankEligible: readBooleanField(entry, "rank_eligible"),
      coverage: readCoverage(entry.coverage),
      meanNormalizedCrps: readFiniteNumberField(entry, "mean_normalized_crps"),
      attemptCounts: readAttemptCounts(entry.attempt_counts),
      meanLatencySeconds: readLatency(entry),
      exclusions: readExclusions(entry.exclusions),
      timing: readTimingSummary(entry),
    });
  }
  return { items, rejectedItems };
}

function readAttemptCounts(value: unknown): Reading<CoreAttemptCounts> {
  if (value === undefined) return { state: "missing" };
  if (value === null) return { state: "null" };
  if (!isRecordObject(value)) return { state: "unrecognized" };
  for (const key of ATTEMPT_COUNT_KEYS) {
    if (
      typeof value[key] !== "number" ||
      !Number.isSafeInteger(value[key]) ||
      value[key] < 0
    ) {
      return { state: "unrecognized" };
    }
  }
  return { state: "value", value: value as CoreAttemptCounts };
}

function readLatency(entry: Record<string, unknown>): Reading<number> {
  const reading = readFiniteNumberField(entry, "mean_latency_seconds");
  return reading.state === "value" && reading.value < 0
    ? { state: "unrecognized" }
    : reading;
}

export function readStringField(
  source: Record<string, unknown>,
  field: string,
): Reading<string> {
  if (!(field in source)) return { state: "missing" };
  const value = source[field];
  if (value === undefined) return { state: "missing" };
  if (value === null) return { state: "null" };
  if (typeof value !== "string" || value.length === 0) {
    return { state: "unrecognized" };
  }
  return { state: "value", value };
}

function readIntegerField(
  source: Record<string, unknown>,
  field: string,
  options: { minimum: number },
): Reading<number> {
  if (!(field in source)) return { state: "missing" };
  const value = source[field];
  if (value === undefined) return { state: "missing" };
  if (value === null) return { state: "null" };
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < options.minimum
  ) {
    return { state: "unrecognized" };
  }
  return { state: "value", value };
}

function readBooleanField(
  source: Record<string, unknown>,
  field: string,
): Reading<boolean> {
  if (!(field in source)) return { state: "missing" };
  const value = source[field];
  if (value === undefined) return { state: "missing" };
  if (value === null) return { state: "null" };
  if (typeof value !== "boolean") return { state: "unrecognized" };
  return { state: "value", value };
}

function readFiniteNumberField(
  source: Record<string, unknown>,
  field: string,
): Reading<number> {
  if (!(field in source)) return { state: "missing" };
  const value = source[field];
  if (value === undefined) return { state: "missing" };
  if (value === null) return { state: "null" };
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return { state: "unrecognized" };
  }
  return { state: "value", value };
}

/**
 * Exclusions get their own reading because a partly unreadable list must still
 * show every reason it can: dropping the whole cell to "unrecognized" would
 * hide real exclusions behind one malformed entry.
 */
export type ExclusionsReading =
  | { state: "value"; value: string[]; unreadable: number }
  | { state: "null" }
  | { state: "missing" }
  | { state: "unrecognized" };

/**
 * `thesis_core/service.py` reports exclusions two ways: a list of reasons when
 * cohort validation fails outright, and a reason-to-count map of ineligible
 * runs otherwise. Both are shown; neither is allowed to fall through to
 * "unrecognized", because a swallowed exclusion is the one thing a leaderboard
 * must never do.
 */
export function readExclusions(value: unknown): ExclusionsReading {
  if (value === undefined) return { state: "missing" };
  if (value === null) return { state: "null" };
  if (Array.isArray(value)) {
    const readable = value
      .filter((entry): entry is string => typeof entry === "string")
      .map((entry) => truncateForDisplay(entry, 160));
    return {
      state: "value",
      value: readable,
      unreadable: value.length - readable.length,
    };
  }
  if (isRecordObject(value)) {
    const entries = Object.entries(value);
    const readable = entries.filter(
      (entry): entry is [string, number] => typeof entry[1] === "number",
    );
    return {
      state: "value",
      value: readable.map(
        ([reason, count]) =>
          `${truncateForDisplay(reason, 120)} \u00d7 ${String(count)}`,
      ),
      unreadable: entries.length - readable.length,
    };
  }
  return { state: "unrecognized" };
}

function readCoverage(value: unknown): Reading<CoreCoverage> {
  if (value === undefined) return { state: "missing" };
  if (value === null) return { state: "null" };
  if (!isRecordObject(value)) return { state: "unrecognized" };
  const eligible = value.eligible;
  const total = value.total;
  if (
    typeof eligible !== "number" ||
    typeof total !== "number" ||
    !Number.isInteger(eligible) ||
    !Number.isInteger(total) ||
    eligible < 0 ||
    total < 0 ||
    eligible > total
  ) {
    return { state: "unrecognized" };
  }
  return { state: "value", value: { eligible, total } };
}

export function readMode(source: Record<string, unknown>): ModeReading {
  if (!("mode" in source)) return { state: "missing" };
  const value = source.mode;
  if (value === undefined) return { state: "missing" };
  if (value === "prospective" || value === "replay" || value === "live_pilot") {
    return { state: "value", value };
  }
  if (typeof value === "string" && value.length > 0) {
    return { state: "unrecognized", raw: truncateForDisplay(value, 48) };
  }
  return { state: "unrecognized", raw: "" };
}

// ---------------------------------------------------------------------------
// Timing: declared scheduling cutoff vs effective information boundary
// ---------------------------------------------------------------------------

/**
 * The declared cutoff is a preregistration commitment; the effective boundary
 * is the bundle post-commit acknowledgement (`evidence_frozen_at`). They are
 * different facts and are read from different fields — one is never used to
 * fill in for the other, because a missing freeze acknowledgement rendered as
 * the declared cutoff would assert evidence discipline nobody verified.
 *
 * Field names are read in the order below so a rename upstream degrades to a
 * visible "not reported" rather than a silent substitution.
 */
export const DECLARED_CUTOFF_FIELDS = [
  "declared_scheduling_cutoff",
  "declared_information_cutoff",
  "declared_cutoff",
  "information_cutoff",
] as const;

export const EFFECTIVE_BOUNDARY_FIELDS = [
  "effective_information_boundary",
  "evidence_frozen_at",
] as const;

export type TimestampReading =
  | { state: "value"; value: string; field: string }
  /** The API named the field and reported no value (`thesis_core/api.py`
   *  returns null when a bundle freeze is unknown). */
  | { state: "null"; field: string }
  | { state: "missing" }
  | { state: "unrecognized"; field: string };

export type TimingOrdering =
  | { state: "pilot_satisfied" }
  | { state: "pilot_violated" }
  | { state: "prospective_satisfied" }
  | { state: "prospective_violated" }
  | { state: "replay_later_freeze" }
  | { state: "replay_within_cutoff" }
  | {
      state: "not_assessable";
      reason:
        | "mode-missing"
        | "mode-unrecognized"
        | "missing-timestamp"
        | "unparseable-timestamp"
        | "unzoned-timestamp";
    };

export interface TimingSummary {
  declaredCutoff: TimestampReading;
  effectiveBoundary: TimestampReading;
  mode: ModeReading;
  ordering: TimingOrdering;
}

function readTimestamp(
  payload: Record<string, unknown>,
  fields: readonly string[],
): TimestampReading {
  for (const field of fields) {
    if (!(field in payload)) continue;
    const value = payload[field];
    if (value === undefined) continue;
    if (value === null) return { state: "null", field };
    if (typeof value !== "string" || value.length === 0) {
      return { state: "unrecognized", field };
    }
    return { state: "value", value, field };
  }
  return { state: "missing" };
}

/**
 * Summarize a row's timing disclosure.
 *
 * `primary` is the API's own summary projection and `fallback` the canonical
 * record payload underneath it. A field absent from the projection is looked
 * for in the payload (a publication manifest carries both timestamps itself);
 * a field the projection reports but this page cannot read is NOT retried
 * against the payload, because an unreadable projection value is a signal in
 * its own right.
 *
 * Ordering is only judged against the rule that applies to the row's own mode.
 * A prospective row must have frozen its bundle strictly before its declared
 * cutoff. A historical replay may assemble its bundle *after* the historical
 * cutoff; that later date is shown as-is next to the replay label rather than
 * scored against a rule replay never claimed to meet.
 */
export function readTimingSummary(
  primary: unknown,
  fallback?: unknown,
): TimingSummary {
  const source = isRecordObject(primary) ? primary : {};
  const secondary = isRecordObject(fallback) ? fallback : {};
  const declaredCutoff = orFallback(
    readTimestamp(source, DECLARED_CUTOFF_FIELDS),
    () => readTimestamp(secondary, DECLARED_CUTOFF_FIELDS),
  );
  const effectiveBoundary = orFallback(
    readTimestamp(source, EFFECTIVE_BOUNDARY_FIELDS),
    () => readTimestamp(secondary, EFFECTIVE_BOUNDARY_FIELDS),
  );
  const primaryMode = readMode(source);
  const mode =
    primaryMode.state === "missing" ? readMode(secondary) : primaryMode;
  return {
    declaredCutoff,
    effectiveBoundary,
    mode,
    ordering: assessOrdering(mode, declaredCutoff, effectiveBoundary),
  };
}

function orFallback(
  reading: TimestampReading,
  fallback: () => TimestampReading,
): TimestampReading {
  return reading.state === "missing" ? fallback() : reading;
}

export function assessOrdering(
  mode: ModeReading,
  declaredCutoff: TimestampReading,
  effectiveBoundary: TimestampReading,
): TimingOrdering {
  if (mode.state === "missing") {
    return { state: "not_assessable", reason: "mode-missing" };
  }
  if (mode.state === "unrecognized") {
    return { state: "not_assessable", reason: "mode-unrecognized" };
  }
  if (declaredCutoff.state !== "value" || effectiveBoundary.state !== "value") {
    return { state: "not_assessable", reason: "missing-timestamp" };
  }
  if (!isZoned(declaredCutoff.value) || !isZoned(effectiveBoundary.value)) {
    // `Date.parse` reads an offset-less date-time as the *viewer's* local time,
    // which would make the same record order differently in two browsers.
    // Refuse the verdict instead of publishing a timezone-dependent one.
    return { state: "not_assessable", reason: "unzoned-timestamp" };
  }
  const declared = Date.parse(declaredCutoff.value);
  const effective = Date.parse(effectiveBoundary.value);
  if (Number.isNaN(declared) || Number.isNaN(effective)) {
    return { state: "not_assessable", reason: "unparseable-timestamp" };
  }
  if (mode.value === "prospective") {
    // Strict: equal instants do not satisfy "frozen before the cutoff".
    return effective < declared
      ? { state: "prospective_satisfied" }
      : { state: "prospective_violated" };
  }
  if (mode.value === "live_pilot") {
    return effective < declared
      ? { state: "pilot_satisfied" }
      : { state: "pilot_violated" };
  }
  // Comparison resolution is one millisecond, so the replay wording says "at or
  // before" rather than claiming strict precedence it cannot establish.
  return effective > declared
    ? { state: "replay_later_freeze" }
    : { state: "replay_within_cutoff" };
}

/** An RFC 3339 instant carries `Z` or a numeric offset; a bare date-time does not. */
const ZONED_INSTANT = /(?:Z|z|[+-]\d{2}:?\d{2})$/;

function isZoned(value: string): boolean {
  return ZONED_INSTANT.test(value);
}
