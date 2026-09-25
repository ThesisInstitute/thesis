import type {
  CountryCode,
  ForecastCellType,
  ForecastCell,
  ForecastRunEntry,
  PredictionPackSet,
  PredictionPackSetMode,
  PredictionPreSubmitReviewWorkflow,
  PredictionRunActivityArtifact,
  ResolvedOutcome,
  Unit,
} from "./forecast-cells";
import { getForecastRunEntries } from "./forecast-cells";
import { verifyForecastRun } from "@/lib/forecast-publication";
import {
  conditionForCell,
  conditionStatusFor,
  isConditionGated,
  type ConditionStatus,
} from "./conditions";
export type { ConditionStatus } from "./conditions";
import {
  getDistributionTransformVersion,
  scoreNumericCdfDistribution,
  type DistributionProvenance,
  type NumericCdfScore,
  type PredictionDistribution,
} from "./prediction-distribution";
import {
  buildRecordedPredictionRunId,
  buildPredictionSpecs,
  buildResolutionRef,
  buildSpecId,
  buildSpecVersionId,
  buildRecordedPredictionRunRecords,
  SEEDED_RUN_RECORDED_AT,
  type PredictionRunRecord,
  type PredictionSpec,
} from "./prediction-specs";
import {
  buildForecastJudgeExport,
  type ForecastJudgeCalibrationReport,
  type ForecastJudgeExport,
} from "./forecast-judges";
import {
  THESIS_TARGET_LEDGER,
  requireLedgerTarget,
  type TargetRegisteredLedgerEntry,
} from "./ledger-targets";
import { createHash } from "node:crypto";
import { canonicalStringify, sha256Hex } from "./canonical-json";
import ledgerPinJson from "./ledger-pin.json";
import {
  LEDGER_AVAILABILITY,
  LEDGER_AVAILABILITY_HEAD_SHA,
  LEDGER_LEGACY_QUARANTINE_LINE_COUNT,
} from "./ledger-availability.generated";
import {
  buildLedgerPersistenceBaseline,
  ledgerHistoryAtCutoff,
  PERSISTENCE_BASELINE_AGENT,
  TIME_SERIES_PRIOR_VARIANT_ID,
} from "./time-series-priors";
import {
  classifyPublicationProof,
  dayOf,
  explicitInstantOf,
  type ScoreChronologyProof,
} from "./witnessed-timeline";
export {
  classifyPublicationProof,
  type PublicationProofStatus,
  type ScoreChronologyProof,
} from "./witnessed-timeline";

export type PolicyEngineLedgerEntry =
  | TargetRegisteredLedgerEntry
  | ObservationRecordedLedgerEntry;

export type ThesisLogEntry =
  | PredictionRecordedLogEntry
  | PredictionResolvedLogEntry;

export type LedgerSourceKind = "official_release";

export type RecordedPredictionDistribution = Pick<
  PredictionDistribution,
  "format" | "pointCount" | "summary" | "provenance"
> & { transformVersion: string };

// The registered resolver contract, restated by the resolver on the
// appended fact itself. A post-quarantine observation may grade a
// registered target only when this projection matches the registration
// (getResolutionContractViolation).
export interface SourceBindingProjection {
  series: string;
  concept?: string;
  period: string;
  releasePolicy: string;
  table: string;
  field: string;
  transform: unknown;
  unit: string;
  sourceUrl?: string;
  responseSha256: string;
}

export type LedgerRowCustody = "append_derived" | "rewritten_in_place";

export interface ObservationRecordedLedgerEntry extends ResolvedOutcome {
  kind: "observation_recorded";
  observationId: string;
  dataPointId: string;
  periodLabel: string;
  unit: Unit;
  observedAt: string;
  sourceKind: LedgerSourceKind;
  targetContentHash?: string;
  ledgerRepoSha?: string;
  sourceVintage?: string;
  retrievedAt?: string;
  // When the append-only ledger accepted this row, derived from the
  // thesis-facts branch history (scripts/pin_ledger.py). Publisher
  // observedAt is what the source claims; acceptance is what the ledger
  // can prove, and cutoff eligibility uses acceptance (finding N5).
  acceptedSequence?: number;
  acceptedAtUtc?: string;
  acceptedCommit?: string;
  ledgerCustody?: LedgerRowCustody;
  // Rows accepted before contract binding existed. They keep grading the
  // legacy cells they resolved, but every such score is flagged
  // legacy_unbound rather than silently treated as contract-bound.
  legacyQuarantined?: boolean;
  // When the resolution event itself was recorded (retrieval time for
  // resolver-appended rows, acceptance time otherwise) — distinct from the
  // publisher's observedAt, which a backfill can predate.
  resolutionRecordedAt?: string;
  assertionVersion?: { id: string; supersedes: string | null };
  sourceBindingProjection?: SourceBindingProjection;
  responseArchive?: {
    path: string;
    sha256: string;
    bytes: number;
    gzipSha256: string;
    gzipBytes: number;
    contentEncoding: "gzip";
  };
}

export interface PredictionRecordedLogEntry {
  kind: "prediction_recorded";
  forecastSlug: string;
  runId: string;
  specId: string;
  type: ForecastCellType;
  title: string;
  question: string;
  country: CountryCode;
  unit: Unit;
  pointEstimate: number;
  interval80: {
    lower: number;
    upper: number;
  };
  resolutionDate: string;
  resolutionSource: string;
  resolutionSourceUrl?: string;
  resolutionRule: string;
  resolutionPolicy?: string;
  recordedAt?: string;
  dataPointId?: string;
  distribution: RecordedPredictionDistribution;
  agent?: string;
  model?: string;
  runLabel: string;
  runDescription?: string;
  packSet?: PredictionPackSet;
  preSubmitReview?: PredictionPreSubmitReviewWorkflow;
  activityLog?: PredictionRunActivityArtifact[];
  custodyRootSha256?: string;
}

export interface PredictionResolvedLogEntry {
  kind: "prediction_resolved";
  resolutionRef: string;
  resolutionEventId: string;
  forecastSlug: string;
  recordedAt: string;
  dataPointId: string;
  ledgerFactRef: string;
  observationId: string;
}

export interface ResolvedForecastScore extends NumericCdfScore {
  scoreId: string;
  runId: string;
  runLabel: string;
  runAt?: string;
  agent?: string;
  model?: string;
  packSet?: PredictionPackSet;
  packMode: PredictionPackSetMode | "primary";
  packCount: number;
  resolutionEventId: string;
  scoringRule: "numeric_cdf_crps_v3_ledger_scale";
  distributionProvenance: DistributionProvenance;
  transformVersion: string;
  chronology: ScoreChronology;
  chronologyProof: ScoreChronologyProof;
  contractBinding: ResolutionContractBinding;
  observedAt: string;
  conditionId: string | null;
  conditionStatus: ConditionStatus | "unregistered" | null;
  normalizationScale: number | null;
  normalizationScaleSource: "ledger_dispersion" | "unavailable";
  normalizationScaleCutoff: string | null;
  normalizationScaleObservationCount: number;
  sharpness: number | null;
  ledgerFactRef: string;
  forecastSlug: string;
  dataPointId: string;
  observationId: string;
  pointEstimate: number;
  observedValue: number;
  unit: Unit;
  interval80: {
    lower: number;
    upper: number;
    width: number;
  };
  signedError: number;
  absoluteError: number;
  normalizedCrps: number | null;
  normalizedAbsoluteError: number | null;
  interval80Covered: boolean;
}

export interface PredictionResolutionLink {
  resolutionRef: string;
  specVersionId: string;
  predictionId: string;
  forecastSlug: string;
  targetFactRef?: string;
  factLedger: "PolicyEngine Ledger";
  resolverRule: string;
  status: "linked" | "pending";
}

export interface PredictionResolutionEvent {
  resolutionEventId: string;
  resolutionRef: string;
  forecastSlug: string;
  ledgerFactRef: string;
  observationId: string;
  occurredAt: string;
  payloadHash: string;
  status: "linked";
}

export interface PredictionResolutionQueueEntry {
  forecastSlug: string;
  title: string;
  country: CountryCode;
  dataPointId?: string;
  resolutionDate: string;
  resolutionSource: string;
  resolutionSourceUrl?: string;
  resolutionPolicy?: string;
  unit: Unit;
  pointEstimate: number;
  interval80: {
    lower: number;
    upper: number;
  };
}

export interface PolicyEngineLedgerExport {
  schemaVersion: "policyengine_ledger_v1";
  source: {
    name: "PolicyEngine Ledger";
    url: "https://github.com/PolicyEngine/chronicle";
    jsonMirrorUrl: "https://app.thesisinstitute.org/ledger.json";
    // The immutable upstream state this export was built from; the daily
    // recorder archives this surface, so the pin rides the witness chain.
    pin?: PolicyEngineLedgerPin;
  };
  counts: {
    facts: number;
    targets: number;
    observations: number;
  };
  entries: PolicyEngineLedgerEntry[];
}

export const THESIS_LOG_CHUNK_SIZE = 100;

export const THESIS_LOG_CHUNK_COLLECTIONS = [
  "entries",
  "specs",
  "runs",
  "scores",
] as const;

export type ThesisLogChunkCollection =
  (typeof THESIS_LOG_CHUNK_COLLECTIONS)[number];

export interface ThesisLogChunkReference {
  index: number;
  count: number;
  url: string;
  sha256: string;
}

export interface ThesisLogCollectionManifest {
  count: number;
  chunkCount: number;
  chunks: ThesisLogChunkReference[];
}

export interface ThesisLogExport {
  schemaVersion: "thesis_log_v3";
  source: {
    name: "Thesis Log";
    url: "https://app.thesisinstitute.org/log";
    jsonUrl: "https://app.thesisinstitute.org/log.json";
    factLedger: {
      name: "PolicyEngine Ledger";
      url: "https://github.com/PolicyEngine/chronicle";
      jsonUrl: "https://app.thesisinstitute.org/ledger.json";
    };
  };
  counts: {
    predictions: number;
    specs: number;
    runs: number;
    resolutions: number;
    scored: number;
    scoredClaimedTimeChronology: number;
    scoredUnverifiedChronology: number;
    scoredViolatedChronology: number;
    resolutionLinks: number;
    resolutionEvents: number;
    pendingResolution: number;
    preSubmitReviews: number;
    judgeTraceEvals: number;
    judgePairwiseEvals: number;
    judgePostResolutionEvals: number;
  };
  collections: Record<ThesisLogChunkCollection, ThesisLogCollectionManifest>;
  resolutionLinks: PredictionResolutionLink[];
  resolutionEvents: PredictionResolutionEvent[];
  judgeResults: ForecastJudgeLogSummary;
  resolutionQueue: PredictionResolutionQueueEntry[];
}

export interface ThesisLogData extends Omit<
  ThesisLogExport,
  "schemaVersion" | "collections"
> {
  schemaVersion: "thesis_log_v3";
  entries: ThesisLogEntry[];
  specs: PredictionSpec[];
  runs: ThesisLogRunRecord[];
  scores: ResolvedForecastScore[];
}

export interface ThesisLogChunkExport {
  schemaVersion: "thesis_log_chunk_v1";
  logSchemaVersion: "thesis_log_v3";
  collection: ThesisLogChunkCollection;
  chunkIndex: number;
  count: number;
  rows: ThesisLogData[ThesisLogChunkCollection];
}

export interface ForecastJudgeLogSummary {
  schemaVersion: "thesis_forecast_judges_summary_v1";
  generatedAt: string;
  policy: ForecastJudgeExport["policy"];
  calibration: ForecastJudgeCalibrationReport;
  fullExportJsonUrl: "https://app.thesisinstitute.org/forecasts/judges.json";
}

export interface PolicyEngineLedgerPin {
  schemaVersion: "thesis_ledger_pin_v1";
  repo: string;
  branch: string;
  sha: string;
  jsonlSha256: string;
  jsonlBytes: number;
  lineCount: number;
  catalogSha256?: string;
  catalogBytes?: number;
  pinnedAtUtc: string;
}

// The build consumes the fact ledger at one immutable commit whose exact
// bytes are committed here as a pin (scripts/pin_ledger.py). A branch name
// would let any upstream writer change what this site scores.
export const POLICYENGINE_LEDGER_PIN = ledgerPinJson as PolicyEngineLedgerPin;

function policyEngineLedgerFileUrl(
  pin: PolicyEngineLedgerPin,
  path: string,
): string {
  return `https://raw.githubusercontent.com/${pin.repo}/${pin.sha}/${path}`;
}

export const POLICYENGINE_LEDGER_FACTS_URL = policyEngineLedgerFileUrl(
  POLICYENGINE_LEDGER_PIN,
  "ledger/official_observations.jsonl",
);

export const POLICYENGINE_LEDGER_SERIES_CATALOG_URL = policyEngineLedgerFileUrl(
  POLICYENGINE_LEDGER_PIN,
  "ledger/series_catalog.json",
);

interface PolicyEngineAggregateFactRow {
  value: number;
  observed_at: string;
  period: {
    type: string;
    value: string | number;
  };
  measure: {
    unit: string;
    concept_evidence_notes?: string;
  };
  source: {
    source_name?: string;
    source_table?: string;
    url?: string;
  };
  source_record_id: string;
  targetContentHash?: string;
  ledgerRepoSha?: string;
  sourceVintage?: string;
  retrievedAt?: string;
  assertionVersion?: { id: string; supersedes: string | null };
  sourceBindingProjection?: SourceBindingProjection;
  responseArchive?: {
    path: string;
    sha256: string;
    bytes: number;
    gzipSha256: string;
    gzipBytes: number;
    contentEncoding: "gzip";
  };
}

let policyEngineLedgerPromise: Promise<PolicyEngineLedgerEntry[]> | null = null;

export async function loadPolicyEngineLedger(): Promise<
  PolicyEngineLedgerEntry[]
> {
  policyEngineLedgerPromise ??= fetchPolicyEngineLedger();
  return policyEngineLedgerPromise;
}

export function resetPolicyEngineLedgerCache() {
  policyEngineLedgerPromise = null;
}

export function parsePolicyEngineLedgerFacts(
  jsonl: string,
): PolicyEngineLedgerEntry[] {
  return jsonl
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => mapPolicyEngineAggregateFactToObservation(JSON.parse(line)));
}

function assertPinnedLedgerBytes(raw: Buffer, pin: PolicyEngineLedgerPin) {
  const digest = createHash("sha256").update(raw).digest("hex");
  if (digest !== pin.jsonlSha256 || raw.length !== pin.jsonlBytes) {
    throw new Error(
      `ledger bytes at ${pin.sha} are ${digest} (${raw.length} bytes) but ` +
        `the committed pin requires ${pin.jsonlSha256} (${pin.jsonlBytes}); ` +
        "refusing to build against an unpinned ledger state",
    );
  }
}

interface SeriesCatalogCommitment {
  sha256: string;
  bytes: number;
}

function seriesCatalogCommitment(
  pin: PolicyEngineLedgerPin,
): SeriesCatalogCommitment | null {
  const hasSha256 = Object.prototype.hasOwnProperty.call(pin, "catalogSha256");
  const hasBytes = Object.prototype.hasOwnProperty.call(pin, "catalogBytes");
  if (hasSha256 !== hasBytes) {
    throw new Error(
      "ledger pin must carry catalogSha256 and catalogBytes together",
    );
  }
  if (!hasSha256) {
    return null;
  }
  if (
    typeof pin.catalogSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(pin.catalogSha256)
  ) {
    throw new Error("ledger pin catalogSha256 must be a SHA-256 digest");
  }
  if (
    typeof pin.catalogBytes !== "number" ||
    !Number.isInteger(pin.catalogBytes) ||
    pin.catalogBytes < 0
  ) {
    throw new Error("ledger pin catalogBytes must be a non-negative integer");
  }
  return { sha256: pin.catalogSha256, bytes: pin.catalogBytes };
}

function assertPinnedSeriesCatalogBytes(
  raw: Buffer,
  pin: PolicyEngineLedgerPin,
  commitment: SeriesCatalogCommitment,
) {
  const digest = createHash("sha256").update(raw).digest("hex");
  if (digest !== commitment.sha256 || raw.length !== commitment.bytes) {
    throw new Error(
      `ledger series catalog bytes at ${pin.sha} are ${digest} ` +
        `(${raw.length} bytes) but the committed pin requires ` +
        `${commitment.sha256} (${commitment.bytes}); refusing to build ` +
        "against an unpinned ledger catalog",
    );
  }
}

export async function fetchPinnedPolicyEngineLedgerBytes(
  pin: PolicyEngineLedgerPin,
): Promise<Buffer> {
  const catalogCommitment = seriesCatalogCommitment(pin);
  const factsUrl = policyEngineLedgerFileUrl(
    pin,
    "ledger/official_observations.jsonl",
  );
  const catalogUrl = policyEngineLedgerFileUrl(
    pin,
    "ledger/series_catalog.json",
  );
  const [factsResponse, catalogResponse] = await Promise.all([
    fetch(factsUrl),
    catalogCommitment ? fetch(catalogUrl) : Promise.resolve(null),
  ]);
  if (!factsResponse.ok) {
    throw new Error(
      `PolicyEngine Ledger fetch failed with HTTP ${factsResponse.status}`,
    );
  }
  if (catalogResponse && !catalogResponse.ok) {
    throw new Error(
      "PolicyEngine Ledger series catalog fetch failed with HTTP " +
        catalogResponse.status,
    );
  }
  const raw = Buffer.from(await factsResponse.arrayBuffer());
  assertPinnedLedgerBytes(raw, pin);
  if (catalogResponse && catalogCommitment) {
    const catalogRaw = Buffer.from(await catalogResponse.arrayBuffer());
    assertPinnedSeriesCatalogBytes(catalogRaw, pin, catalogCommitment);
  }
  return raw;
}

// Every fetched row must carry its acceptance record; a row the committed
// availability index cannot vouch for (stale index, upstream rewrite) fails
// the build rather than silently entering cutoff histories.
function enrichWithAcceptance(
  entry: ObservationRecordedLedgerEntry,
  line: string,
  index: number,
): ObservationRecordedLedgerEntry {
  const row = LEDGER_AVAILABILITY[index];
  if (!row) {
    throw new Error(
      `ledger line ${index + 1} has no availability record; regenerate the ` +
        "pin and availability index together (scripts/pin_ledger.py)",
    );
  }
  const lineSha256 = createHash("sha256").update(line, "utf8").digest("hex");
  if (
    row.lineSha256 !== lineSha256 ||
    row.sourceRecordId !== entry.dataPointId
  ) {
    throw new Error(
      `ledger line ${index + 1} (${entry.dataPointId}) does not match its ` +
        `availability record (${row.sourceRecordId})`,
    );
  }
  return {
    ...entry,
    acceptedSequence: row.acceptedSequence,
    acceptedAtUtc: row.acceptedAtUtc,
    acceptedCommit: row.acceptedCommit,
    ledgerCustody: row.custody,
    legacyQuarantined:
      row.acceptedSequence < LEDGER_LEGACY_QUARANTINE_LINE_COUNT,
    resolutionRecordedAt: entry.retrievedAt ?? row.acceptedAtUtc,
  };
}

function mapPolicyEngineAggregateFactToObservation(
  fact: PolicyEngineAggregateFactRow,
): ObservationRecordedLedgerEntry {
  assertPolicyEngineFactShape(fact);

  return {
    kind: "observation_recorded",
    observationId: `obs.${fact.source_record_id}`,
    dataPointId: fact.source_record_id,
    periodLabel: formatLedgerPeriodLabel(fact.period),
    value: fact.value,
    unit: fact.measure.unit,
    observedAt: fact.observed_at,
    // The publisher's date is NOT when the resolution was recorded; a
    // backfilled print carries an old observed_at. Resolver-appended rows
    // carry their true retrieval instant.
    resolvedAt: fact.retrievedAt ?? fact.observed_at,
    sourceKind: "official_release",
    source: formatLedgerSource(fact.source),
    sourceUrl: fact.source.url,
    note: fact.measure.concept_evidence_notes,
    targetContentHash: fact.targetContentHash,
    ledgerRepoSha: fact.ledgerRepoSha,
    sourceVintage: fact.sourceVintage,
    retrievedAt: fact.retrievedAt,
    assertionVersion: fact.assertionVersion,
    sourceBindingProjection: fact.sourceBindingProjection,
    responseArchive: fact.responseArchive,
  };
}

// The committed pin also closes a freshness hole the branch URL had:
// branch-ref raw URLs sit behind a ~5-minute CDN cache, which once made a
// resolution rebuild read the ledger as it was BEFORE the observations it
// was rebuilt for (live-caught 2026-07-10: 21 fresh resolutions, unchanged
// scoreboard). A commit-pinned raw URL is content-addressed by path, and
// the byte-hash check below fails closed on any anomaly.
async function fetchPolicyEngineLedger(): Promise<PolicyEngineLedgerEntry[]> {
  const pin = POLICYENGINE_LEDGER_PIN;
  if (LEDGER_AVAILABILITY_HEAD_SHA !== pin.sha) {
    throw new Error(
      `availability index is for ${LEDGER_AVAILABILITY_HEAD_SHA} but the ` +
        `pin is ${pin.sha}; regenerate both together (scripts/pin_ledger.py)`,
    );
  }
  if (LEDGER_AVAILABILITY.length !== pin.lineCount) {
    throw new Error(
      `availability index covers ${LEDGER_AVAILABILITY.length} rows but ` +
        `the pin commits ${pin.lineCount}`,
    );
  }
  const raw = await fetchPinnedPolicyEngineLedgerBytes(pin);
  const facts = raw
    .toString("utf-8")
    .split("\n")
    .filter((line) => line.trim())
    .map((line, index) =>
      enrichWithAcceptance(
        mapPolicyEngineAggregateFactToObservation(JSON.parse(line)),
        line,
        index,
      ),
    );
  return [...THESIS_TARGET_LEDGER, ...facts];
}

function assertPolicyEngineFactShape(
  fact: PolicyEngineAggregateFactRow,
): asserts fact is PolicyEngineAggregateFactRow & {
  measure: { unit: Unit; concept_evidence_notes?: string };
} {
  if (!fact.source_record_id) {
    throw new Error("PolicyEngine Ledger fact is missing source_record_id");
  }
  if (!fact.observed_at) {
    throw new Error(
      `Ledger fact ${fact.source_record_id} is missing observed_at`,
    );
  }
  if (typeof fact.value !== "number") {
    throw new Error(
      `Ledger fact ${fact.source_record_id} has non-numeric value`,
    );
  }
  if (!isUnit(fact.measure.unit)) {
    throw new Error(
      `Ledger fact ${fact.source_record_id} has unsupported unit ${fact.measure.unit}`,
    );
  }
}

function isUnit(unit: string): unit is Unit {
  return [
    "percent",
    "count",
    "gbp_billions",
    "usd",
    "usd_millions",
    "usd_billions",
    "usd_monthly",
    "thousands",
    "millions",
    "million_cubic_feet",
    "per_1000_live_births",
    "ratio",
    "percent_growth",
  ].includes(unit);
}

function formatLedgerSource(source: PolicyEngineAggregateFactRow["source"]) {
  const publisher =
    source.source_name === "bls"
      ? "Bureau of Labor Statistics"
      : source.source_name === "statcan"
        ? "Statistics Canada"
        : source.source_name;
  return [publisher, source.source_table].filter(Boolean).join(" ");
}

function formatLedgerPeriodLabel(
  period: PolicyEngineAggregateFactRow["period"],
) {
  if (
    period.type === "month" &&
    typeof period.value === "string" &&
    /^\d{4}-\d{2}$/.test(period.value)
  ) {
    const [year, month] = period.value.split("-").map(Number);
    return new Intl.DateTimeFormat("en", {
      month: "long",
      year: "numeric",
      timeZone: "UTC",
    }).format(new Date(Date.UTC(year, month - 1, 1)));
  }
  return String(period.value);
}

const PREDICTION_RESOLUTION_FACT_LINKS = [
  {
    kind: "prediction_resolved",
    forecastSlug: "nonfarm-payrolls-may-2026",
    recordedAt: "2026-06-06T05:44:00+01:00",
    dataPointId: "bls.ces.total_nonfarm_payroll_change.may_2026.first_print",
    observationId:
      "obs.bls.ces.total_nonfarm_payroll_change.may_2026.first_print",
  },
  {
    kind: "prediction_resolved",
    forecastSlug: "unemployment-rate-may-2026-first-print",
    recordedAt: "2026-06-06T05:44:00+01:00",
    dataPointId: "bls.cps.unemployment_rate.may_2026.first_print",
    observationId: "obs.bls.cps.unemployment_rate.may_2026.first_print",
  },
  {
    kind: "prediction_resolved",
    forecastSlug: "average-hourly-earnings-mom-may-2026",
    recordedAt: "2026-06-06T05:44:00+01:00",
    dataPointId: "bls.ces.average_hourly_earnings_private.may_2026.first_print",
    observationId:
      "obs.bls.ces.average_hourly_earnings_private.may_2026.first_print",
  },
  {
    kind: "prediction_resolved",
    forecastSlug: "canada-unemployment-rate-may-2026",
    recordedAt: "2026-06-06T05:44:00+01:00",
    dataPointId: "statcan.lfs.unemployment_rate.canada.may_2026.first_print",
    observationId:
      "obs.statcan.lfs.unemployment_rate.canada.may_2026.first_print",
  },
  {
    kind: "prediction_resolved",
    forecastSlug: "canada-employment-change-may-2026",
    recordedAt: "2026-06-06T05:44:00+01:00",
    dataPointId: "statcan.lfs.employment_change.canada.may_2026.first_print",
    observationId:
      "obs.statcan.lfs.employment_change.canada.may_2026.first_print",
  },
  {
    kind: "prediction_resolved",
    forecastSlug: "cpi-headline-mom-may-2026",
    recordedAt: "2026-06-12T20:37:03+00:00",
    dataPointId: "bls.cpi.u.headline_mom.may_2026.first_print",
    observationId: "obs.bls.cpi.u.headline_mom.may_2026.first_print",
  },
  {
    kind: "prediction_resolved",
    forecastSlug: "core-cpi-mom-may-2026",
    recordedAt: "2026-06-12T20:37:03+00:00",
    dataPointId: "bls.cpi.u.core_mom.may_2026.first_print",
    observationId: "obs.bls.cpi.u.core_mom.may_2026.first_print",
  },
  {
    kind: "prediction_resolved",
    forecastSlug: "canada-overnight-rate-june-2026-boc",
    recordedAt: "2026-06-12T20:37:03+00:00",
    dataPointId: "bank_of_canada.overnight_rate.after_june_2026",
    observationId: "obs.bank_of_canada.overnight_rate.after_june_2026",
  },
  {
    kind: "prediction_resolved",
    forecastSlug: "us-mts-deficit-may-2026",
    recordedAt: "2026-06-12T20:37:03+00:00",
    dataPointId: "treasury.mts.monthly_deficit.may_2026.first_print",
    observationId: "obs.treasury.mts.monthly_deficit.may_2026.first_print",
  },
  {
    kind: "prediction_resolved",
    forecastSlug: "initial-jobless-claims-week-ending-2026-06-06",
    recordedAt: "2026-06-12T20:37:03+00:00",
    dataPointId: "dol.eta.initial_claims.sa.week_ending_2026_06_06",
    observationId: "obs.dol.eta.initial_claims.sa.week_ending_2026_06_06",
  },
  {
    kind: "prediction_resolved",
    forecastSlug: "euro-area-ecb-deposit-facility-rate-june-2026",
    recordedAt: "2026-06-12T20:37:03+00:00",
    dataPointId: "ecb.deposit_facility_rate.after_june_2026",
    observationId: "obs.ecb.deposit_facility_rate.after_june_2026",
  },
  {
    kind: "prediction_resolved",
    forecastSlug: "us-ppi-final-demand-mom-may-2026",
    recordedAt: "2026-06-12T20:37:03+00:00",
    dataPointId: "bls.ppi.final_demand_monthly_change.may_2026.first_print",
    observationId:
      "obs.bls.ppi.final_demand_monthly_change.may_2026.first_print",
  },
  {
    kind: "prediction_resolved",
    forecastSlug: "canada-building-permit-value-growth-april-2026",
    recordedAt: "2026-06-12T20:37:03+00:00",
    dataPointId:
      "statcan.building_permits.total_value_mom.canada.april_2026.first_print",
    observationId:
      "obs.statcan.building_permits.total_value_mom.canada.april_2026.first_print",
  },
  {
    kind: "prediction_resolved",
    forecastSlug: "uk-monthly-gdp-growth-april-2026",
    recordedAt: "2026-06-12T20:37:03+00:00",
    dataPointId: "ons.gdp.monthly_growth.april_2026.first_print",
    observationId: "obs.ons.gdp.monthly_growth.april_2026.first_print",
  },
] satisfies Array<
  Omit<
    PredictionResolvedLogEntry,
    "resolutionRef" | "resolutionEventId" | "ledgerFactRef"
  >
>;

// Historical seed snapshot retained for migration compatibility. Active
// resolution is derived from the PolicyEngine Ledger by dataPointId.
export const THESIS_LOG: PredictionResolvedLogEntry[] =
  PREDICTION_RESOLUTION_FACT_LINKS.map((entry) => ({
    ...entry,
    resolutionRef: buildResolutionRef(entry.forecastSlug),
    resolutionEventId: buildResolutionEventId(entry),
    ledgerFactRef: entry.dataPointId,
  }));

export function isObservationRecordedLedgerEntry(
  entry: PolicyEngineLedgerEntry | ThesisLogEntry,
): entry is ObservationRecordedLedgerEntry {
  return entry.kind === "observation_recorded";
}

export function isTargetRegisteredLedgerEntry(
  entry: PolicyEngineLedgerEntry | ThesisLogEntry,
): entry is TargetRegisteredLedgerEntry {
  return entry.kind === "target_registered";
}

export function isPredictionResolvedLogEntry(
  entry: ThesisLogEntry,
): entry is PredictionResolvedLogEntry {
  return entry.kind === "prediction_resolved";
}

export function isPredictionRecordedLogEntry(
  entry: ThesisLogEntry,
): entry is PredictionRecordedLogEntry {
  return entry.kind === "prediction_recorded";
}

export function getResolvedObservationForForecast(
  forecast: ForecastCell,
  ledger: PolicyEngineLedgerEntry[],
): ObservationRecordedLedgerEntry | undefined {
  if (!forecast.dataPointId) return undefined;
  const observations = getObservationsForDataPoint(
    forecast.dataPointId,
    ledger,
  );
  if (observations.length === 0) return undefined;

  return [...observations].sort(compareFirstPrintObservations)[0];
}

// First print = earliest observed INSTANT, not earliest string: lexical
// ordering lets a later print with a different UTC offset sort first
// (re-audit N6). Unparseable timestamps sort last; ties break on the
// observation ID for determinism.
function compareFirstPrintObservations(
  left: ObservationRecordedLedgerEntry,
  right: ObservationRecordedLedgerEntry,
): number {
  const leftInstant = Date.parse(left.observedAt);
  const rightInstant = Date.parse(right.observedAt);
  const leftParses = Number.isFinite(leftInstant);
  const rightParses = Number.isFinite(rightInstant);
  if (leftParses && rightParses && leftInstant !== rightInstant) {
    return leftInstant - rightInstant;
  }
  if (leftParses !== rightParses) return leftParses ? -1 : 1;
  return left.observationId.localeCompare(right.observationId);
}

function buildPredictionResolvedLogEntry(
  forecast: ForecastCell,
  observation: ObservationRecordedLedgerEntry,
): PredictionResolvedLogEntry {
  return {
    kind: "prediction_resolved",
    resolutionRef: buildResolutionRef(forecast.slug),
    resolutionEventId: buildResolutionEventId({
      forecastSlug: forecast.slug,
      observationId: observation.observationId,
    }),
    forecastSlug: forecast.slug,
    recordedAt: observation.resolvedAt,
    dataPointId: observation.dataPointId,
    ledgerFactRef: observation.dataPointId,
    observationId: observation.observationId,
  };
}

export function buildResolvedPredictionLogEntries(
  forecasts: ForecastCell[],
  ledger: PolicyEngineLedgerEntry[],
): PredictionResolvedLogEntry[] {
  return forecasts
    .flatMap((forecast) => {
      const observation = getResolvedObservationForForecast(forecast, ledger);
      return observation
        ? [buildPredictionResolvedLogEntry(forecast, observation)]
        : [];
    })
    .sort((a, b) =>
      a.recordedAt === b.recordedAt
        ? a.forecastSlug.localeCompare(b.forecastSlug)
        : a.recordedAt.localeCompare(b.recordedAt),
    );
}

export function buildPredictionRecordedLogEntries(
  forecasts: ForecastCell[],
): PredictionRecordedLogEntry[] {
  return forecasts.flatMap((forecast) => {
    const ledgerTarget = forecast.dataPointId
      ? requireLedgerTarget(forecast.dataPointId)
      : undefined;
    return getForecastRunEntries(forecast).flatMap((run) => {
      if (!run.predictionDistribution) return [];
      const runId = buildRecordedPredictionRunId(
        forecast,
        run.predictionRun?.runAt,
        run.variantId,
        run,
      );

      return [
        {
          kind: "prediction_recorded",
          forecastSlug: forecast.slug,
          runId,
          specId: buildSpecId(forecast.slug),
          type: forecast.type,
          title: forecast.title,
          question: forecast.question,
          country: forecast.country ?? "US",
          unit: forecast.unit,
          pointEstimate: run.pointEstimate,
          interval80: {
            lower: run.ciLow,
            upper: run.ciHigh,
          },
          resolutionDate:
            ledgerTarget?.resolutionDate ?? forecast.resolutionDate,
          resolutionSource:
            ledgerTarget?.resolutionSource ?? forecast.resolutionSource,
          resolutionSourceUrl:
            ledgerTarget?.resolutionSourceUrl ?? forecast.resolutionSourceUrl,
          resolutionRule:
            ledgerTarget?.resolutionRule ?? forecast.resolutionRule,
          resolutionPolicy:
            ledgerTarget?.resolutionPolicy ?? forecast.series?.resolutionPolicy,
          recordedAt: run.predictionRun?.runAt,
          dataPointId: ledgerTarget?.dataPointId ?? forecast.dataPointId,
          distribution: {
            format: run.predictionDistribution.format,
            pointCount: run.predictionDistribution.pointCount,
            summary: run.predictionDistribution.summary,
            provenance: run.predictionDistribution.provenance,
            transformVersion: getDistributionTransformVersion(
              run.predictionDistribution,
            ),
          },
          agent: run.predictionRun?.agent,
          model: run.predictionRun?.model,
          runLabel: run.label,
          runDescription: run.description,
          packSet: run.packSet,
          preSubmitReview: run.predictionRun?.preSubmitReview,
          activityLog: run.predictionRun?.activityLog,
          custodyRootSha256: run.predictionRun?.custodyRootSha256,
        },
      ];
    });
  });
}

export function buildThesisLog(
  forecasts: ForecastCell[],
  ledger: PolicyEngineLedgerEntry[],
): ThesisLogEntry[] {
  return [
    ...buildPredictionRecordedLogEntries(forecasts),
    ...buildResolvedPredictionLogEntries(forecasts, ledger),
  ];
}

export function buildResolutionQueue(
  forecasts: ForecastCell[],
  ledger: PolicyEngineLedgerEntry[],
): PredictionResolutionQueueEntry[] {
  return forecasts
    .filter((forecast) => !getResolutionForForecast(forecast, ledger))
    .map((forecast) => {
      const ledgerTarget = forecast.dataPointId
        ? requireLedgerTarget(forecast.dataPointId)
        : undefined;
      return {
        forecastSlug: forecast.slug,
        title: forecast.title,
        country: forecast.country ?? "US",
        dataPointId: ledgerTarget?.dataPointId ?? forecast.dataPointId,
        resolutionDate: ledgerTarget?.resolutionDate ?? forecast.resolutionDate,
        resolutionSource:
          ledgerTarget?.resolutionSource ?? forecast.resolutionSource,
        resolutionSourceUrl:
          ledgerTarget?.resolutionSourceUrl ?? forecast.resolutionSourceUrl,
        resolutionPolicy:
          ledgerTarget?.resolutionPolicy ?? forecast.series?.resolutionPolicy,
        unit: forecast.unit,
        pointEstimate: forecast.pointEstimate,
        interval80: {
          lower: forecast.ciLow,
          upper: forecast.ciHigh,
        },
      };
    })
    .sort((a, b) =>
      a.resolutionDate === b.resolutionDate
        ? a.title.localeCompare(b.title)
        : a.resolutionDate.localeCompare(b.resolutionDate),
    );
}

export function buildPredictionResolutionLinks(
  forecasts: ForecastCell[],
  specs: PredictionSpec[] = buildPredictionSpecs(forecasts),
  ledger: PolicyEngineLedgerEntry[] = [],
): PredictionResolutionLink[] {
  const specsByPredictionId = new Map(
    specs.map((spec) => [spec.predictionId, spec]),
  );

  return forecasts.map((forecast) => {
    const spec = specsByPredictionId.get(forecast.slug);
    const ledgerTarget = forecast.dataPointId
      ? requireLedgerTarget(forecast.dataPointId)
      : undefined;
    return {
      resolutionRef: buildResolutionRef(forecast.slug),
      specVersionId: spec?.specVersionId ?? buildSpecVersionId(forecast.slug),
      predictionId: forecast.slug,
      forecastSlug: forecast.slug,
      targetFactRef: ledgerTarget?.dataPointId ?? forecast.dataPointId,
      factLedger: "PolicyEngine Ledger",
      resolverRule: ledgerTarget?.resolutionRule ?? forecast.resolutionRule,
      status: getResolutionForForecast(forecast, ledger) ? "linked" : "pending",
    };
  });
}

export function buildPredictionResolutionEvents(
  forecasts: ForecastCell[],
  ledger: PolicyEngineLedgerEntry[],
): PredictionResolutionEvent[] {
  return buildResolvedPredictionLogEntries(forecasts, ledger).map((entry) => {
    const observation = getObservationForId(entry.observationId, ledger);
    if (!observation) {
      throw new Error(
        `Missing observation payload for resolution event ${entry.resolutionEventId}`,
      );
    }
    return {
      resolutionEventId: entry.resolutionEventId,
      resolutionRef: entry.resolutionRef,
      forecastSlug: entry.forecastSlug,
      ledgerFactRef: entry.ledgerFactRef,
      observationId: entry.observationId,
      occurredAt: entry.recordedAt,
      payloadHash: sha256Hex({
        resolutionEventId: entry.resolutionEventId,
        ledgerFactRef: entry.ledgerFactRef,
        observationId: entry.observationId,
        observedValue: observation.value,
        unit: observation.unit,
      }),
      status: "linked" as const,
    };
  });
}

export function buildPolicyEngineLedgerExport(
  entries: PolicyEngineLedgerEntry[],
): PolicyEngineLedgerExport {
  const targets = entries.filter(isTargetRegisteredLedgerEntry);
  const observations = entries.filter(isObservationRecordedLedgerEntry);

  return {
    schemaVersion: "policyengine_ledger_v1",
    source: {
      name: "PolicyEngine Ledger",
      url: "https://github.com/PolicyEngine/chronicle",
      jsonMirrorUrl: "https://app.thesisinstitute.org/ledger.json",
      pin: POLICYENGINE_LEDGER_PIN,
    },
    counts: {
      facts: entries.length,
      targets: targets.length,
      observations: observations.length,
    },
    entries,
  };
}

// Run records omit their 201-point CDFs. The full distributions are served by
// the target-architecture chunks and shown on each cell page.
export type ThesisLogRunRecord = Omit<PredictionRunRecord, "output"> & {
  output: Omit<PredictionRunRecord["output"], "distribution"> & {
    distribution: {
      format: PredictionRunRecord["output"]["distribution"]["format"];
      pointCount: number;
      pointsUrl: string;
      provenance: DistributionProvenance;
      transformVersion: string;
    };
  };
};

function toLogRunRecord(run: PredictionRunRecord): ThesisLogRunRecord {
  return {
    ...run,
    output: {
      ...run.output,
      distribution: {
        format: run.output.distribution.format,
        pointCount: run.output.distribution.pointCount,
        pointsUrl: "/forecasts/targets/forecastDistributions/manifest.json",
        provenance: run.output.distribution.provenance,
        transformVersion: getDistributionTransformVersion(
          run.output.distribution,
        ),
      },
    },
  };
}

export function buildThesisLogData(
  forecasts: ForecastCell[],
  ledger: PolicyEngineLedgerEntry[],
): ThesisLogData {
  const entries = buildThesisLog(forecasts, ledger);
  const specs = buildPredictionSpecs(forecasts);
  const runs = buildRecordedPredictionRunRecords(forecasts, specs);
  const resolutionLinks = buildPredictionResolutionLinks(
    forecasts,
    specs,
    ledger,
  );
  const resolutionEvents = buildPredictionResolutionEvents(forecasts, ledger);
  const scores = scoreResolvedForecasts(forecasts, ledger);
  const judgeResults = buildForecastJudgeExport({ forecasts, scores });
  const judgeSummary = buildForecastJudgeLogSummary(judgeResults);
  const resolutionQueue = buildResolutionQueue(forecasts, ledger);

  return {
    schemaVersion: "thesis_log_v3",
    source: {
      name: "Thesis Log",
      url: "https://app.thesisinstitute.org/log",
      jsonUrl: "https://app.thesisinstitute.org/log.json",
      factLedger: {
        name: "PolicyEngine Ledger",
        url: "https://github.com/PolicyEngine/chronicle",
        jsonUrl: "https://app.thesisinstitute.org/ledger.json",
      },
    },
    counts: {
      predictions: entries.filter(isPredictionRecordedLogEntry).length,
      specs: specs.length,
      runs: runs.length,
      resolutions: entries.filter(isPredictionResolvedLogEntry).length,
      // Headline scored count = witness-verified only: the run's custody
      // root was externally witnessed before the observation. Claimed-time
      // chronology (recorded run time precedes the observation but no
      // external witness proves it), unverified (no trustworthy run time),
      // and violated (run time at/after the observation) scores stay in
      // `scores` for transparency but are outside the official track record.
      scored: scores.filter((score) => score.chronology === "witness_verified")
        .length,
      scoredClaimedTimeChronology: scores.filter(
        (score) => score.chronology === "claimed_time_verified",
      ).length,
      scoredUnverifiedChronology: scores.filter(
        (score) => score.chronology === "unverified",
      ).length,
      scoredViolatedChronology: scores.filter(
        (score) => score.chronology === "violated",
      ).length,
      resolutionLinks: resolutionLinks.length,
      resolutionEvents: resolutionEvents.length,
      pendingResolution: resolutionQueue.length,
      preSubmitReviews: runs.filter((run) => run.preSubmitReview).length,
      judgeTraceEvals: judgeResults.traceQuality.length,
      judgePairwiseEvals: judgeResults.pairwise.length,
      judgePostResolutionEvals: judgeResults.postResolution.length,
    },
    entries,
    specs,
    runs: runs.map(toLogRunRecord),
    resolutionLinks,
    resolutionEvents,
    scores,
    judgeResults: judgeSummary,
    resolutionQueue,
  };
}

export function buildThesisLogExport(
  forecasts: ForecastCell[],
  ledger: PolicyEngineLedgerEntry[],
): ThesisLogExport {
  return buildThesisLogManifest(buildThesisLogData(forecasts, ledger));
}

export function buildThesisLogManifest(data: ThesisLogData): ThesisLogExport {
  const {
    entries: _entries,
    specs: _specs,
    runs: _runs,
    scores: _scores,
    ...slim
  } = data;
  return {
    ...slim,
    collections: Object.fromEntries(
      THESIS_LOG_CHUNK_COLLECTIONS.map((collection) => [
        collection,
        buildThesisLogCollectionManifest(data, collection),
      ]),
    ) as ThesisLogExport["collections"],
  };
}

export function buildThesisLogChunk(
  data: ThesisLogData,
  collection: ThesisLogChunkCollection,
  chunkIndex: number,
): ThesisLogChunkExport {
  const rows = data[collection];
  const start = chunkIndex * THESIS_LOG_CHUNK_SIZE;
  const chunkRows = rows.slice(
    start,
    start + THESIS_LOG_CHUNK_SIZE,
  ) as ThesisLogChunkExport["rows"];
  return {
    schemaVersion: "thesis_log_chunk_v1",
    logSchemaVersion: "thesis_log_v3",
    collection,
    chunkIndex,
    count: chunkRows.length,
    rows: chunkRows,
  };
}

export function isThesisLogChunkCollection(
  value: string,
): value is ThesisLogChunkCollection {
  return THESIS_LOG_CHUNK_COLLECTIONS.includes(
    value as ThesisLogChunkCollection,
  );
}

function buildThesisLogCollectionManifest(
  data: ThesisLogData,
  collection: ThesisLogChunkCollection,
): ThesisLogCollectionManifest {
  const count = data[collection].length;
  const chunkCount = Math.ceil(count / THESIS_LOG_CHUNK_SIZE);
  return {
    count,
    chunkCount,
    chunks: Array.from({ length: chunkCount }, (_, index) => {
      const chunk = buildThesisLogChunk(data, collection, index);
      return {
        index,
        count: chunk.count,
        url: `/log/${collection}/${index}.json`,
        sha256: sha256Hex(chunk),
      };
    }),
  };
}

export function buildForecastJudgeLogSummary(
  judgeResults: ForecastJudgeExport,
): ForecastJudgeLogSummary {
  return {
    schemaVersion: "thesis_forecast_judges_summary_v1",
    generatedAt: judgeResults.generatedAt,
    policy: judgeResults.policy,
    calibration: judgeResults.calibration,
    fullExportJsonUrl: "https://app.thesisinstitute.org/forecasts/judges.json",
  };
}

export function getObservationForId(
  observationId: string,
  ledger: PolicyEngineLedgerEntry[],
): ObservationRecordedLedgerEntry | undefined {
  return ledger
    .filter(isObservationRecordedLedgerEntry)
    .filter((entry) => entry.observationId === observationId)
    .sort(compareFirstPrintObservations)[0];
}

export function getObservationsForDataPoint(
  dataPointId: string,
  ledger: PolicyEngineLedgerEntry[],
): ObservationRecordedLedgerEntry[] {
  return ledger
    .filter(isObservationRecordedLedgerEntry)
    .filter((entry) => entry.dataPointId === dataPointId);
}

export function getResolutionForForecast(
  forecast: ForecastCell,
  ledger: PolicyEngineLedgerEntry[],
): PredictionResolvedLogEntry | undefined {
  const observation = getResolvedObservationForForecast(forecast, ledger);
  return observation
    ? buildPredictionResolvedLogEntry(forecast, observation)
    : undefined;
}

export function getResolvedOutcomeForForecast(
  forecast: ForecastCell,
  ledger: PolicyEngineLedgerEntry[],
): ResolvedOutcome | undefined {
  const entry = getResolutionForForecast(forecast, ledger);
  if (!entry) return undefined;
  const observation = getObservationForId(entry.observationId, ledger);
  if (!observation) return undefined;
  return {
    value: observation.value,
    resolvedAt: observation.resolvedAt,
    source: observation.source,
    sourceUrl: observation.sourceUrl,
    note: observation.note,
  };
}

export function scoreResolvedForecast(
  forecast: ForecastCell,
  ledger: PolicyEngineLedgerEntry[],
): ResolvedForecastScore | undefined {
  const primaryRun = getForecastRunEntries(forecast)[0];
  if (!primaryRun) return undefined;
  return scoreResolvedForecastRun(forecast, primaryRun, ledger);
}

// The headline track record requires PROOF of publication order, not
// testimony (re-audit N1). Tiers, strongest first:
//   "witness_verified"     — the run's claimed time precedes the observation
//                            AND its sealed custody root was externally
//                            witnessed (RFC 3161, complete inventory,
//                            verifier-side headline eligible) before the
//                            observation. Only this tier is headline.
//   "claimed_time_verified" — the recorded run time precedes the observation
//                            but no external witness proves the run existed
//                            before the outcome. Published, flagged, outside
//                            the headline (all legacy scores live here).
//   "unverified"           — no usable run time (including the legacy seeded
//                            placeholder), or same-day ambiguity.
//   "violated"             — the recorded time is at/after the observation.
// External proof upgrades a claimed-time-verified score; it never rescues an
// unverified or violated one.
export type ClaimedScoreChronology =
  | "claimed_time_verified"
  | "unverified"
  | "violated";

export type ScoreChronology = "witness_verified" | ClaimedScoreChronology;

// Bump when chronology semantics change; participates in score IDs (X3).
export const CHRONOLOGY_POLICY_VERSION = "chronology_v4_witnessed_publication";

const SEEDED_RUN_INSTANT = Date.parse(SEEDED_RUN_RECORDED_AT);

// Claimed-time tier only: compares the timestamps the run and the ledger
// assert about themselves. Publication proof is a separate tier consumed
// from the witnessed timeline (classifyPublicationProof) and composed by
// composeScoreChronology.
export function classifyScoreChronology(
  runAt: string | undefined,
  observedAt: string | undefined,
): ClaimedScoreChronology {
  if (!runAt || !observedAt) return "unverified";
  const runDay = dayOf(runAt);
  const observedDay = dayOf(observedAt);
  if (!runDay || !observedDay) return "unverified";
  const runInstant = explicitInstantOf(runAt);
  // The legacy seeded placeholder is unverifiable in ANY spelling of the
  // same instant, not just the canonical string (cross-review X4).
  if (runInstant !== null && runInstant === SEEDED_RUN_INSTANT) {
    return "unverified";
  }
  const observedInstant = explicitInstantOf(observedAt);
  if (runInstant !== null && observedInstant !== null) {
    return runInstant < observedInstant ? "claimed_time_verified" : "violated";
  }
  // Day granularity: strictly earlier written UTC dates verify, strictly
  // later violate, and same-day ordering is unknowable in either
  // direction, so it never enters the headline.
  if (runDay < observedDay) return "claimed_time_verified";
  if (runDay > observedDay) return "violated";
  return "unverified";
}

export function composeScoreChronology(
  claimed: ClaimedScoreChronology,
  proof: ScoreChronologyProof,
): ScoreChronology {
  return claimed === "claimed_time_verified" && proof.status === "witnessed"
    ? "witness_verified"
    : claimed;
}

// Published-but-flagged tiers: everything the claimed-time gate admits.
// Cell pages, the log scoreboard, and judge diagnostics draw on this
// population; the headline (calibration cards, counts.scored, rewards)
// requires isHeadlineChronology.
export function hasVerifiedClaimedChronology(
  chronology: ScoreChronology,
): boolean {
  return (
    chronology === "witness_verified" || chronology === "claimed_time_verified"
  );
}

export function isHeadlineChronology(chronology: ScoreChronology): boolean {
  return chronology === "witness_verified";
}

export interface TargetNormalizationScale {
  scale: number | null;
  source: "ledger_dispersion" | "unavailable";
  cutoff: string | null;
  observationCount: number;
}

// A step dispersion must exceed this fraction of the history's own
// magnitude to count as dispersion at all. Equal decimal steps leave
// binary-float residue that scales with the values (1.814, 1.805, 1.796
// left 1.57e-16; the same linear shape near 215 leaves 2.0e-14, which
// passed the old absolute Number.EPSILON gate), bounded by about
// 2 * n * Number.EPSILON of the magnitude for n steps, so under 1e-12 for
// any history shorter than ~2,000 prints. Twelve significant digits is
// also all the resolution a materialized distribution keeps
// (toPrecision(12)); no official series publishes finer.
export const NORMALIZATION_SCALE_RELATIVE_FLOOR = 1e-12;

// The denominator is frozen per dataPointId from observations that were in
// the public ledger before target registration. Legacy registrations have no
// timestamp, so their primary run seal is the cutoff. No forecast output —
// history, intervals, anything an agent authors — is ever an input: when the
// ledger lacks three pre-cutoff observations the scale is simply
// unavailable, raw CRPS still publishes, and the score stays out of
// normalized aggregates (re-audit X2: a forecast-derived fallback let a
// wider primary interval shrink its own normalized error).
export function targetNormalizationScale(
  forecast: ForecastCell,
  ledger: PolicyEngineLedgerEntry[],
): TargetNormalizationScale {
  const unavailable = (
    cutoff: string | null,
    observationCount: number,
  ): TargetNormalizationScale => ({
    scale: null,
    source: "unavailable",
    cutoff,
    observationCount,
  });
  if (!forecast.dataPointId) {
    return unavailable(null, 0);
  }
  const target = ledger.find(
    (entry): entry is TargetRegisteredLedgerEntry =>
      entry.kind === "target_registered" &&
      entry.dataPointId === forecast.dataPointId,
  );
  const registeredAt = target?.registeredAt;
  const primaryRunAt =
    forecast.normalizationCutoffRunAt !== undefined
      ? forecast.normalizationCutoffRunAt
      : getForecastRunEntries(forecast).find((run) => run.isPrimary)
          ?.predictionRun?.runAt;
  const cutoff =
    registeredAt && Number.isFinite(Date.parse(registeredAt))
      ? registeredAt
      : primaryRunAt && Number.isFinite(Date.parse(primaryRunAt))
        ? primaryRunAt
        : null;
  if (!cutoff) {
    return unavailable(null, 0);
  }

  const history = ledgerHistoryAtCutoff(forecast, ledger, cutoff);
  if (history.length < 3) {
    return unavailable(cutoff, history.length);
  }
  const values = history.map((entry) => entry.value);
  const diffs = values.slice(1).map((value, index) => value - values[index]);
  const mean = diffs.reduce((total, diff) => total + diff, 0) / diffs.length;
  const variance =
    diffs.reduce((total, diff) => total + (diff - mean) ** 2, 0) /
    (diffs.length - 1);
  const scale = Math.sqrt(variance);
  const magnitude = values.reduce(
    (largest, value) => Math.max(largest, Math.abs(value)),
    0,
  );
  // Residue below the relative floor is zero dispersion, not a tiny
  // denominator: dividing by it put -7.08e13 rewards in the 2026-09-23
  // export (continued-claims-week-2026-08-01), because the aggregate-only
  // fix (10670132) left the stored score and the per-row reward ungated.
  // Refusing here nulls normalized CRPS, sharpness, and reward for every
  // consumer at once; the variance arithmetic itself is unchanged, so
  // every usable scale (and its scoreId) stays byte-identical.
  if (
    !Number.isFinite(scale) ||
    !(scale > magnitude * NORMALIZATION_SCALE_RELATIVE_FLOOR)
  ) {
    return unavailable(cutoff, history.length);
  }
  return {
    scale,
    source: "ledger_dispersion",
    cutoff,
    observationCount: history.length,
  };
}

// Why a run earned no score. "unresolved" is the only reason that implies
// nothing happened yet; every other reason describes a RESOLVED target whose
// run is excluded by an integrity gate, and consumers must label it that
// way rather than folding it into "unresolved" (re-audit X9).
export type ScoreExclusionReason =
  | "unresolved"
  | "unverified_run"
  | "condition_not_satisfied"
  | "missing_distribution"
  | "contract_violation";

export interface ForecastRunScoreEvaluation {
  score?: ResolvedForecastScore;
  exclusion?: { reason: ScoreExclusionReason; detail?: string };
}

// How a score's resolving observation relates to its target's registered
// contract. legacy_unbound rows (the pre-contract quarantine, plus targets
// registered before source bindings existed) keep grading their cells but
// are flagged everywhere; they are never silently treated as bound.
export type ResolutionContractBinding = "contract_bound" | "legacy_unbound";

export const CONTRACT_BINDING_POLICY_VERSION = "contract-binding-v1";

export function classifyResolutionContractBinding(
  target: TargetRegisteredLedgerEntry | undefined,
  observation: ObservationRecordedLedgerEntry,
): ResolutionContractBinding {
  return !observation.legacyQuarantined &&
    target?.targetContentHash &&
    target.sourceBinding &&
    observation.targetContentHash &&
    observation.sourceBindingProjection
    ? "contract_bound"
    : "legacy_unbound";
}

function findRegisteredTarget(
  forecast: ForecastCell,
  ledger: PolicyEngineLedgerEntry[],
): TargetRegisteredLedgerEntry | undefined {
  return ledger.find(
    (entry): entry is TargetRegisteredLedgerEntry =>
      entry.kind === "target_registered" &&
      entry.dataPointId === forecast.dataPointId,
  );
}

// A resolution fact must satisfy the target's registered contract before it
// can grade anything: matching units always (re-audit N6: a wrong-unit fact
// from an unrelated source scored a reproduced target), and for observations
// accepted after the legacy quarantine, the full registered binding — the
// contract hash, retrieval provenance, an archived source response, and a
// source-binding projection that restates the registration. Missing bindings
// fail closed; only quarantined legacy rows are exempt, and those grade
// flagged as legacy_unbound instead.
export function getResolutionContractViolation(
  forecast: ForecastCell,
  observation: ObservationRecordedLedgerEntry,
  ledger: PolicyEngineLedgerEntry[],
): string | null {
  if (observation.unit !== forecast.unit) {
    return (
      `observation unit ${JSON.stringify(observation.unit)} does not match ` +
      `the forecast contract unit ${JSON.stringify(forecast.unit)}`
    );
  }
  const target = findRegisteredTarget(forecast, ledger);
  if (!target) return null;
  if (observation.unit !== target.unit) {
    return (
      `observation unit ${JSON.stringify(observation.unit)} does not match ` +
      `the registered target unit ${JSON.stringify(target.unit)}`
    );
  }
  if (
    observation.targetContentHash &&
    target.targetContentHash &&
    observation.targetContentHash !== target.targetContentHash
  ) {
    return (
      "observation was recorded against target contract " +
      `${observation.targetContentHash.slice(0, 16)}… but the registered ` +
      `contract is ${target.targetContentHash.slice(0, 16)}…`
    );
  }
  if (observation.legacyQuarantined || !target.targetContentHash) {
    return null;
  }

  if (!observation.targetContentHash) {
    return (
      "post-quarantine observation carries no target contract hash for " +
      `registered target ${target.dataPointId}`
    );
  }
  if (
    !observation.retrievedAt ||
    !observation.ledgerRepoSha ||
    !observation.sourceVintage
  ) {
    return "post-quarantine observation lacks retrieval provenance";
  }
  if (!observation.responseArchive) {
    return "post-quarantine observation lacks an archived source response";
  }
  const projection = observation.sourceBindingProjection;
  if (!projection) {
    return "post-quarantine observation lacks a source-binding projection";
  }
  if (projection.responseSha256 !== observation.responseArchive.sha256) {
    return (
      "source-binding projection digest does not match the archived " +
      "response bytes"
    );
  }
  // dataPointId is opaque: the exact registration is the identity authority.
  // Never derive a series by stripping a period or release-looking suffix.
  if (observation.dataPointId !== target.dataPointId) {
    return (
      `observation dataPointId ${JSON.stringify(observation.dataPointId)} ` +
      `does not match the registration's ${JSON.stringify(target.dataPointId)}`
    );
  }
  if (observation.observationId !== target.observationId) {
    return (
      `observation id ${JSON.stringify(observation.observationId)} does not ` +
      `match the registration's ${JSON.stringify(target.observationId)}`
    );
  }
  if (projection.series !== target.series) {
    return (
      `source-binding projection series ${JSON.stringify(projection.series)} ` +
      `does not match the registration's ${JSON.stringify(target.series)}`
    );
  }
  const binding = target.sourceBinding;
  if (binding) {
    const expected: [string, unknown, unknown][] = [
      ["period", projection.period, target.period],
      ["releasePolicy", projection.releasePolicy, binding.releasePolicy],
      ["table", projection.table, binding.table],
      ["field", projection.field, binding.field],
      ["transform", projection.transform, binding.transform],
      ["unit", projection.unit, target.unit],
    ];
    for (const [key, observed, registered] of expected) {
      if (canonicalStringify(observed) !== canonicalStringify(registered)) {
        return (
          `source-binding projection ${key} ` +
          `${JSON.stringify(observed)} does not match the registration's ` +
          `${JSON.stringify(registered)}`
        );
      }
    }
    // The observation's own publisher host must be one the registration
    // admits — a fact fetched from a novel host cannot grade the target.
    const allowedHosts = binding.allowedHosts;
    const observedUrl = observation.sourceUrl ?? projection.sourceUrl;
    if (allowedHosts && allowedHosts.length > 0 && observedUrl) {
      let host: string | null = null;
      try {
        host = new URL(observedUrl).hostname;
      } catch {
        host = null;
      }
      if (!host || !allowedHosts.includes(host)) {
        return (
          `observation source host ${JSON.stringify(host)} is not in the ` +
          `registered allowedHosts ${JSON.stringify(allowedHosts)}`
        );
      }
    }
  }
  // Registration pinned a ledger state; a resolving print that was already
  // a member of that state is a backfill grading a pre-registered target
  // (finding N5: availability means membership, not publisher dates).
  if (typeof target.ledgerPinLineCount === "number") {
    if (typeof observation.acceptedSequence !== "number") {
      return "post-quarantine observation has no ledger acceptance record";
    }
    if (observation.acceptedSequence < target.ledgerPinLineCount) {
      return (
        `observation was already inside the pinned ledger state at ` +
        `registration (sequence ${observation.acceptedSequence} < pinned ` +
        `count ${target.ledgerPinLineCount})`
      );
    }
  }
  return null;
}

export function scoreResolvedForecastRun(
  forecast: ForecastCell,
  run: ForecastRunEntry,
  ledger: PolicyEngineLedgerEntry[],
  conditionOverrides?: Map<string, ConditionStatus>,
): ResolvedForecastScore | undefined {
  return evaluateResolvedForecastRun(forecast, run, ledger, conditionOverrides)
    .score;
}

/**
 * Artifact-backed analyst runs can be scored. The only generated exception is
 * the paired ledger baseline, whose entire run must equal a fresh replay from
 * the supplied ledger and whose primary run must independently verify.
 */
export function isScoreEligibleForecastRun(
  forecast: ForecastCell,
  run: ForecastRunEntry,
  ledger: PolicyEngineLedgerEntry[],
): boolean {
  if (run.variantId !== TIME_SERIES_PRIOR_VARIANT_ID) {
    return verifyForecastRun(forecast, run).eligible;
  }
  if (
    run.isPrimary ||
    run.predictionRun?.agent !== PERSISTENCE_BASELINE_AGENT
  ) {
    return false;
  }
  const primary = getForecastRunEntries(forecast).find(
    (entry) => entry.isPrimary,
  );
  if (!primary || !verifyForecastRun(forecast, primary).eligible) return false;
  const reconstructed = buildLedgerPersistenceBaseline(
    forecast,
    ledger,
  ).comparisonRun;
  if (!reconstructed) return false;
  const expected = getForecastRunEntries({
    ...forecast,
    comparisonRuns: [reconstructed],
  }).find((entry) => entry.variantId === TIME_SERIES_PRIOR_VARIANT_ID);
  try {
    return canonicalStringify(run) === canonicalStringify(expected);
  } catch {
    return false;
  }
}

export function evaluateResolvedForecastRun(
  forecast: ForecastCell,
  run: ForecastRunEntry,
  ledger: PolicyEngineLedgerEntry[],
  conditionOverrides?: Map<string, ConditionStatus>,
): ForecastRunScoreEvaluation {
  if (!isScoreEligibleForecastRun(forecast, run, ledger)) {
    return {
      exclusion: {
        reason: "unverified_run",
        detail:
          "Run lacks verified execution artifacts or a matching ledger baseline reconstruction",
      },
    };
  }
  // A conditional branch is graded only when its registered condition
  // actually occurred. Both branches share the same official-print contract,
  // but an open, failed, or counterfactual branch is excluded before resolution
  // lookup; grading it would score a hypothesis whose premise never happened
  // (review finding F6).
  const condition = conditionForCell(forecast);
  const conditionStatus = isConditionGated(forecast)
    ? conditionStatusFor(forecast, conditionOverrides)
    : null;
  if (isConditionGated(forecast) && conditionStatus !== "satisfied") {
    return {
      exclusion: {
        reason: "condition_not_satisfied",
        detail: condition
          ? `${condition.conditionId} is ${conditionStatus ?? "unregistered"}`
          : "condition is not registered",
      },
    };
  }
  const resolution = getResolutionForForecast(forecast, ledger);
  if (!resolution) return { exclusion: { reason: "unresolved" } };
  if (!run.predictionDistribution) {
    return { exclusion: { reason: "missing_distribution" } };
  }

  const observation = getObservationForId(resolution.observationId, ledger);
  if (!observation) return { exclusion: { reason: "unresolved" } };
  const contractViolation = getResolutionContractViolation(
    forecast,
    observation,
    ledger,
  );
  if (contractViolation) {
    return {
      exclusion: { reason: "contract_violation", detail: contractViolation },
    };
  }
  const contractBinding = classifyResolutionContractBinding(
    findRegisteredTarget(forecast, ledger),
    observation,
  );

  const distributionScore = scoreNumericCdfDistribution(
    run.predictionDistribution,
    observation.value,
  );
  const signedError = observation.value - run.pointEstimate;
  const runId = buildRecordedPredictionRunId(
    forecast,
    run.predictionRun?.runAt,
    run.variantId,
    run,
  );
  const resolutionEventId = buildResolutionEventId(resolution);
  const scoringRule = "numeric_cdf_crps_v3_ledger_scale";
  const distributionProvenance = run.predictionDistribution.provenance;
  const transformVersion = getDistributionTransformVersion(
    run.predictionDistribution,
  );
  const interval80Width = Math.abs(run.ciHigh - run.ciLow);
  const normalization = targetNormalizationScale(forecast, ledger);
  const chronologyProof = classifyPublicationProof(
    run.predictionRun?.custodyRootSha256,
    observation.observedAt,
  );
  const chronology = composeScoreChronology(
    classifyScoreChronology(run.predictionRun?.runAt, observation.observedAt),
    chronologyProof,
  );

  const score: ResolvedForecastScore = {
    scoreId: buildScoreId({
      runId,
      resolutionEventId,
      scoringRule,
      transformVersion,
      forecastOutput: {
        pointEstimate: run.pointEstimate,
        interval80: { lower: run.ciLow, upper: run.ciHigh },
        distribution: run.predictionDistribution,
      },
      outcome: {
        observationId: observation.observationId,
        observedValue: observation.value,
        unit: observation.unit,
      },
      normalizationScale: normalization.scale,
      normalizationScaleSource: normalization.source,
      normalizationScaleCutoff: normalization.cutoff,
      normalizationScaleObservationCount: normalization.observationCount,
      observedAt: observation.observedAt,
      chronology,
      chronologyPolicy: CHRONOLOGY_POLICY_VERSION,
      // Whether the resolving observation was contract-bound is part of
      // what the score means, exactly like its chronology verdict.
      contractBinding,
      contractBindingPolicy: CONTRACT_BINDING_POLICY_VERSION,
      // A conditional branch's meaning includes WHICH premise gated it and
      // the premise's resolved status: rebinding the cell to a different
      // registered condition must change the score identity (re-audit N7).
      conditionId: condition?.conditionId ?? null,
      conditionStatus,
    }),
    runId,
    runLabel: run.label,
    runAt: run.predictionRun?.runAt,
    agent: run.predictionRun?.agent,
    model: run.predictionRun?.model,
    packSet: run.packSet,
    packMode: run.packSet?.mode ?? "primary",
    packCount: run.packSet?.packs.length ?? 0,
    resolutionEventId,
    scoringRule,
    distributionProvenance,
    transformVersion,
    chronology,
    chronologyProof,
    contractBinding,
    observedAt: observation.observedAt,
    conditionId: condition?.conditionId ?? null,
    conditionStatus,
    ledgerFactRef: observation.dataPointId,
    forecastSlug: forecast.slug,
    dataPointId: resolution.dataPointId,
    observationId: observation.observationId,
    pointEstimate: run.pointEstimate,
    observedValue: observation.value,
    unit: observation.unit,
    interval80: {
      lower: run.ciLow,
      upper: run.ciHigh,
      width: interval80Width,
    },
    signedError,
    absoluteError: Math.abs(signedError),
    normalizationScale: normalization.scale,
    normalizationScaleSource: normalization.source,
    normalizationScaleCutoff: normalization.cutoff,
    normalizationScaleObservationCount: normalization.observationCount,
    normalizedCrps:
      normalization.scale === null
        ? null
        : distributionScore.crps / normalization.scale,
    normalizedAbsoluteError:
      normalization.scale === null
        ? null
        : Math.abs(signedError) / normalization.scale,
    sharpness:
      normalization.scale === null
        ? null
        : interval80Width / normalization.scale,
    interval80Covered:
      run.ciLow <= observation.value && observation.value <= run.ciHigh,
    ...distributionScore,
  };
  return { score };
}

export function scoreResolvedForecasts(
  forecasts: ForecastCell[],
  ledger: PolicyEngineLedgerEntry[],
): ResolvedForecastScore[] {
  return forecasts.flatMap((forecast) => {
    return getForecastRunEntries(forecast).flatMap((run) => {
      const score = scoreResolvedForecastRun(forecast, run, ledger);
      return score ? [score] : [];
    });
  });
}

export function withResolvedOutcome(
  forecast: ForecastCell,
  ledger: PolicyEngineLedgerEntry[],
): ForecastCell {
  const resolvedForecast: ForecastCell = {
    ...forecast,
    comparisonRuns: forecast.comparisonRuns?.filter(
      (run) => run.variantId !== TIME_SERIES_PRIOR_VARIANT_ID,
    ),
    persistenceBaseline: undefined,
    resolvedOutcome:
      getResolvedOutcomeForForecast(forecast, ledger) ??
      forecast.resolvedOutcome,
  };
  const primaryRun = getForecastRunEntries(resolvedForecast)[0];
  const primaryScore = primaryRun
    ? scoreResolvedForecastRun(resolvedForecast, primaryRun, ledger)
    : undefined;
  // The paired persistence baseline attaches for any claimed-time-or-better
  // primary so legacy cell pages keep their comparison, but the baseline is
  // itself a deterministic reconstruction: pairs only reach the HEADLINE
  // statistic when the agent side is witness-verified (brier-lab attaches
  // score components to witness-verified rows only).
  if (!primaryScore || !hasVerifiedClaimedChronology(primaryScore.chronology)) {
    return resolvedForecast;
  }

  const baseline = buildLedgerPersistenceBaseline(resolvedForecast, ledger);
  return {
    ...resolvedForecast,
    persistenceBaseline: baseline.record,
    comparisonRuns: baseline.comparisonRun
      ? [...(resolvedForecast.comparisonRuns ?? []), baseline.comparisonRun]
      : resolvedForecast.comparisonRuns,
  };
}

export function withResolvedOutcomes(
  forecasts: ForecastCell[],
  ledger: PolicyEngineLedgerEntry[],
): ForecastCell[] {
  return forecasts.map((forecast) => withResolvedOutcome(forecast, ledger));
}

function buildResolutionEventId({
  forecastSlug,
  observationId,
}: {
  forecastSlug: string;
  observationId: string;
}) {
  return `resolution_event.${forecastSlug}.${observationId
    .replace(/^obs\./, "")
    .replace(/[^A-Za-z0-9]+/g, "-")}`;
}

export function buildScoreId(payload: {
  runId: string;
  resolutionEventId: string;
  scoringRule: ResolvedForecastScore["scoringRule"];
  transformVersion: string;
  forecastOutput: unknown;
  outcome: unknown;
  // A score's identity commits to its full meaning: the normalization
  // that produced the headline number, the observation instant, and the
  // chronology verdict + policy that admitted or excluded it (X3).
  normalizationScale: number | null;
  normalizationScaleSource: string;
  normalizationScaleCutoff: string | null;
  normalizationScaleObservationCount: number;
  observedAt: string;
  chronology: string;
  chronologyPolicy: string;
  contractBinding: string;
  contractBindingPolicy: string;
  // The gating premise and its resolved status are part of what the score
  // MEANS: rebinding a branch to another condition, or the same condition
  // resolving differently, must produce a different score ID (N7).
  conditionId: string | null;
  conditionStatus: string | null;
}) {
  const payloadDigest = sha256Hex(payload);
  return `score.${payload.runId}.${payload.resolutionEventId}.${payload.scoringRule}.${payloadDigest.slice(0, 16)}`;
}
