import { describe, expect, it, vi } from "vitest";
import type { BrierRewardRow } from "@/data/brier-lab";
import { summarizePairedComparison } from "@/data/brier-lab";
import { canonicalStringify, sha256Hex } from "@/data/canonical-json";
import type { ForecastCell } from "@/data/forecast-cells";
import { getForecastRunEntries } from "@/data/forecast-cells";
import {
  PERSISTENCE_BASELINE_ALGORITHM_VERSION,
  PERSISTENCE_BASELINE_AGENT,
  buildLedgerPersistenceBaseline,
} from "@/data/time-series-priors";
import type { TargetRegisteredLedgerEntry } from "@/data/ledger-targets";
import {
  hasVerifiedClaimedChronology,
  scoreResolvedForecasts,
  withResolvedOutcomes,
  type ObservationRecordedLedgerEntry,
  type PolicyEngineLedgerEntry,
} from "@/data/thesis-log";

// These fixtures test deterministic ledger reconstruction and paired scoring after execution verification.
// The production verification boundary is exercised without mocks in
// published-scoring-gate.test.ts and forecast-publication.test.ts.
vi.mock("@/lib/forecast-publication", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/forecast-publication")>();
  return {
    ...actual,
    verifyForecastRun: () => ({
      eligible: true,
      reason: "Downstream scoring fixture",
    }),
    filterPublishedForecasts: (
      forecasts: import("@/data/forecast-cells").ForecastCell[],
    ) => forecasts,
  };
});

const RUN_AT = "2026-04-10T12:00:00Z";
const SERIES = "test.series";
const TARGET_CONTENT_HASH = "a".repeat(64);
const RESPONSE_SHA256 = "b".repeat(64);

const binding = {
  adapter: "generic-url" as const,
  sourceUrl: "https://example.test/series",
  sourceSeriesId: "TEST",
  field: "value",
  table: "fixture",
  transform: { operation: "identity", factor: 1 },
  releasePolicy: "first_print" as const,
  allowedHosts: ["example.test"],
  expectedReleaseWindow: { start: "2026-01-01", end: "2026-12-31" },
};

function forecast(agent = "agent.with.no.special.prefix"): ForecastCell {
  return {
    slug: "fixture-april",
    country: "US",
    type: "data",
    title: "Fixture series",
    question: "Fixture series April 2026 first print",
    unit: "percent",
    pointEstimate: 11,
    ciLow: 9,
    ciHigh: 13,
    confidence: 0.8,
    resolutionDate: "2026-05-01",
    resolutionSource: "Fixture agency",
    resolutionRule: "First print",
    dataPointId: "test.series.apr_2026.first_print",
    historicalContext: [
      { label: "agent-controlled latest", value: 999 },
      { label: "agent-controlled old", value: -999 },
    ],
    drivers: ["fixture"],
    predictionRun: {
      kind: "recorded-agent-run",
      runAt: RUN_AT,
      agent,
      model: "fixture-model",
      sourceContext: [],
    },
    reasoning: [{ kind: "forecast", point: 11, ciLow: 9, ciHigh: 13 }],
  };
}

function observation(
  period: string,
  value: number,
  observedAt: string,
): ObservationRecordedLedgerEntry {
  const dataPointId = `test.series.${period}_2026.first_print`;
  const registeredPeriod = `${period}_2026`;
  return {
    kind: "observation_recorded",
    observationId: `obs.${dataPointId}`,
    dataPointId,
    periodLabel: `${period} 2026`,
    unit: "percent",
    value,
    observedAt,
    resolvedAt: observedAt,
    // History eligibility requires ledger acceptance, not just the
    // publisher's claimed date; the clean fixture case accepts on print.
    acceptedAtUtc: observedAt,
    acceptedSequence: 1,
    legacyQuarantined: false,
    sourceKind: "official_release",
    source: "Fixture agency",
    sourceUrl: `https://example.test/${period}`,
    targetContentHash: TARGET_CONTENT_HASH,
    ledgerRepoSha: "c".repeat(40),
    sourceVintage: observedAt.slice(0, 10),
    retrievedAt: observedAt,
    responseArchive: {
      path: `fixture/${period}.json.gz`,
      sha256: RESPONSE_SHA256,
      bytes: 1,
      gzipSha256: "d".repeat(64),
      gzipBytes: 1,
      contentEncoding: "gzip",
    },
    sourceBindingProjection: {
      series: SERIES,
      period: registeredPeriod,
      releasePolicy: binding.releasePolicy,
      table: binding.table,
      field: binding.field,
      transform: binding.transform,
      unit: "percent",
      responseSha256: RESPONSE_SHA256,
    },
  };
}

function registration(
  period: string,
  observedAt: string,
): TargetRegisteredLedgerEntry {
  const dataPointId = `test.series.${period}_2026.first_print`;
  return {
    kind: "target_registered",
    dataPointId,
    observationId: `obs.${dataPointId}`,
    country: "US",
    periodLabel: `${period} 2026`,
    unit: "percent",
    resolutionDate: observedAt.slice(0, 10),
    resolutionSource: "Fixture agency",
    resolutionRule: "First print",
    resolutionPolicy: "first_print",
    sourceKind: "official_release",
    source: "Fixture agency",
    note: "fixture",
    registrationState: "published",
    registeredAt: "2026-01-01T00:00:00Z",
    targetContentHash: TARGET_CONTENT_HASH,
    series: SERIES,
    period: `${period}_2026`,
    catalogSlug: `fixture-${period}`,
    valueScale: 1,
    sourceBinding: binding,
  };
}

function fixtureLedger(includeHistory = true): PolicyEngineLedgerEntry[] {
  const rows: Array<readonly [string, number, string]> = includeHistory
    ? [
        ["mar", 12, "2026-04-01T12:00:00Z"],
        ["jan", 10, "2026-02-01T12:00:00Z"],
        ["feb", 14, "2026-03-01T12:00:00Z"],
      ]
    : [];
  rows.push(["apr", 13, "2026-05-01T12:00:00Z"]);
  return rows.flatMap(([period, value, observedAt]) => [
    registration(period, observedAt),
    observation(period, value, observedAt),
  ]);
}

describe("fair ledger-backed baselines", () => {
  it("uses the ledger's last print and realized history, never agent history", () => {
    const result = buildLedgerPersistenceBaseline(forecast(), fixtureLedger());
    const run = result.comparisonRun;

    expect(result.record.status).toBe("available");
    expect(run?.pointEstimate).toBe(12);
    expect(run?.ciLow).toBe(8.4);
    expect(run?.ciHigh).toBe(15.6);
    expect(result.record.observationRefs.map((ref) => ref.value)).toEqual([
      10, 14, 12,
    ]);
    expect(result.record.observationRefs.map((ref) => ref.observedAt)).toEqual([
      "2026-02-01T12:00:00Z",
      "2026-03-01T12:00:00Z",
      "2026-04-01T12:00:00Z",
    ]);
    expect(result.record.observationRefs.map((ref) => ref.value)).not.toContain(
      999,
    );

    const artifact = run?.predictionRun.activityLog?.[0];
    const payload = {
      schemaVersion: "thesis_persistence_baseline_inputs_v1",
      algorithmVersion: PERSISTENCE_BASELINE_ALGORITHM_VERSION,
      targetDataPointId: "test.series.apr_2026.first_print",
      seriesId: "test.series",
      cutoff: RUN_AT,
      observations: result.record.observationRefs,
    };
    expect(artifact?.artifactType).toBe("baseline_inputs");
    expect(artifact?.path).toMatch(/^ledger:\/\/persistence-baselines\//);
    expect(artifact?.sha256).toBe(sha256Hex(payload));
    expect(artifact?.bytes).toBe(
      new TextEncoder().encode(canonicalStringify(payload)).byteLength,
    );
    expect(artifact?.observationRefs).toEqual(result.record.observationRefs);
  });

  it("excludes rows the ledger accepted after the cutoff (N5 backfill)", () => {
    // Same publisher dates as the clean fixture, but the ledger only
    // accepted the rows AFTER the run cutoff — a backfill. Old observedAt
    // values must not smuggle the rows into pre-cutoff history.
    const backfilled = fixtureLedger().map((entry) =>
      entry.kind === "observation_recorded"
        ? { ...entry, acceptedAtUtc: "2026-04-20T12:00:00Z" }
        : entry,
    );
    const result = buildLedgerPersistenceBaseline(forecast(), backfilled);

    expect(result.record.status).toBe("unavailable");
    expect(result.comparisonRun).toBeNull();
  });

  it("excludes rows with no acceptance record at all (fail closed)", () => {
    const unaccepted = fixtureLedger().map((entry) =>
      entry.kind === "observation_recorded"
        ? { ...entry, acceptedAtUtc: undefined }
        : entry,
    );
    const result = buildLedgerPersistenceBaseline(forecast(), unaccepted);

    expect(result.record.status).toBe("unavailable");
    expect(result.comparisonRun).toBeNull();
  });

  it("records an unavailable baseline when the ledger has no history", () => {
    const enriched = withResolvedOutcomes([forecast()], fixtureLedger(false));
    const target = enriched[0];

    expect(target.persistenceBaseline).toMatchObject({
      status: "unavailable",
      observationRefs: [],
      reason: "ledger has no pre-cutoff observations for the target series",
    });
    expect(
      getForecastRunEntries(target).some(
        (run) => run.predictionRun?.agent === PERSISTENCE_BASELINE_AGENT,
      ),
    ).toBe(false);
  });

  it("adds persistence coverage for every verified primary agent prefix", () => {
    const enriched = withResolvedOutcomes(
      [forecast("completely-unselected-agent")],
      fixtureLedger(),
    );
    // The fixture run carries no custody root, so its chronology tops out
    // at claimed-time-verified — exactly the tier that still earns a paired
    // persistence baseline on cell pages.
    const scores = scoreResolvedForecasts(enriched, fixtureLedger()).filter(
      (score) => hasVerifiedClaimedChronology(score.chronology),
    );

    expect(enriched[0].persistenceBaseline?.status).toBe("available");
    expect(
      scores.some((score) => score.agent === PERSISTENCE_BASELINE_AGENT),
    ).toBe(true);
  });

  it("computes scale-free paired CRPS ratios and win rate", () => {
    const row = (predictionId: string, crps: number, agent: string) =>
      ({
        predictionId,
        agent,
        reward: {
          value: null,
          components: { crps },
        },
      }) as BrierRewardRow;
    const summary = summarizePairedComparison(
      [row("a", 0.3, "agent"), row("b", 0.5, "agent")],
      [
        row("a", 0.4, PERSISTENCE_BASELINE_AGENT),
        row("b", 0.2, PERSISTENCE_BASELINE_AGENT),
      ],
    );

    expect(summary.pairedTargets).toBe(2);
    // Geometric mean of 0.3/0.4 and 0.5/0.2: sqrt(0.75 * 2.5).
    expect(summary.crpsRatioGeomean).toBeCloseTo(Math.sqrt(0.75 * 2.5), 8);
    expect(summary.agentWinRate).toBe(0.5);
    expect(summary.zeroCrpsPairs).toBe(0);
  });

  it("keeps zero-CRPS pairs out of the ratio but in the win rate", () => {
    const row = (predictionId: string, crps: number, agent: string) =>
      ({
        predictionId,
        agent,
        reward: {
          value: null,
          components: { crps },
        },
      }) as BrierRewardRow;
    const summary = summarizePairedComparison(
      [row("a", 0, "agent"), row("b", 0.5, "agent")],
      [
        row("a", 0.4, PERSISTENCE_BASELINE_AGENT),
        row("b", 0.25, PERSISTENCE_BASELINE_AGENT),
      ],
    );

    expect(summary.pairedTargets).toBe(2);
    expect(summary.crpsRatioGeomean).toBeCloseTo(2, 8);
    expect(summary.agentWinRate).toBe(0.5);
    expect(summary.zeroCrpsPairs).toBe(1);
  });
});
