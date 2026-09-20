import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { sha256Hex } from "@/data/canonical-json";
import {
  FORECAST_CELLS,
  getForecastRunEntries,
  type ForecastCell,
  type PredictionRunActivityArtifact,
} from "@/data/forecast-cells";
import { THESIS_TARGET_LEDGER } from "@/data/ledger-targets";
import { buildRecordedPredictionRunId } from "@/data/prediction-specs";
import { buildTargetArchitectureProjection } from "@/data/thesis-target-architecture";
import {
  buildTargetArchitectureChunkExport,
  buildTargetArchitectureChunkHashPayload,
  buildTargetArchitectureManifest,
  buildTargetArchitectureRootPayload,
} from "@/data/thesis-target-architecture-export";
import {
  buildScoreId,
  buildPredictionResolutionEvents,
  scoreResolvedForecastRun,
  type ObservationRecordedLedgerEntry,
} from "@/data/thesis-log";

// These fixtures test content addressing and score identities after execution verification.
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

const FULL_DIGEST = /^[0-9a-f]{64}$/;

describe("target architecture hashing", () => {
  it("commits every canonical chunk and table manifest into one root", () => {
    const projection = buildTargetArchitectureProjection([FORECAST_CELLS[0]]);
    const manifest = buildTargetArchitectureManifest(projection, {
      sourceCommit: "0123456789abcdef0123456789abcdef01234567",
    });

    expect(manifest.schemaVersion).toBe(
      "thesis_target_architecture_manifest_v2",
    );
    expect(manifest.projectionRootSha256).toBe(
      sha256Hex(buildTargetArchitectureRootPayload(manifest)),
    );
    for (const table of manifest.tables) {
      const { sha256, ...tablePayload } = table;
      expect(sha256).toBe(sha256Hex(tablePayload));
      for (const reference of table.chunks) {
        const chunk = buildTargetArchitectureChunkExport(
          projection,
          table.table,
          reference.index,
          manifest,
        );
        expect(chunk.projectionRootSha256).toBe(manifest.projectionRootSha256);
        expect(reference.sha256).toBe(
          sha256Hex(buildTargetArchitectureChunkHashPayload(chunk)),
        );
      }
    }

    const otherCommit = buildTargetArchitectureManifest(projection, {
      sourceCommit: "ffffffffffffffffffffffffffffffffffffffff",
    });
    expect(otherCommit.projectionRootSha256).not.toBe(
      manifest.projectionRootSha256,
    );
  });

  it("hashes every chunk of a table larger than the chunk boundary", () => {
    const projection = buildTargetArchitectureProjection([FORECAST_CELLS[0]]);
    const template = projection.targets[0];
    projection.targets = Array.from({ length: 10_001 }, (_, index) => ({
      ...template,
      targetId: `target.synthetic.${index}`,
      slug: `synthetic-${index}`,
      dataPointId: `synthetic.${index}`,
    }));
    projection.counts.targets = projection.targets.length;

    const manifest = buildTargetArchitectureManifest(projection, {
      sourceCommit: "0123456789abcdef0123456789abcdef01234567",
    });
    const targets = manifest.tables.find((table) => table.table === "targets");

    expect(targets?.chunkCount).toBe(2);
    expect(targets?.chunks.map((chunk) => chunk.rowCount)).toEqual([10_000, 1]);
    expect(targets?.chunks[0].sha256).not.toBe(targets?.chunks[1].sha256);
  });

  it("uses the shared canonical row digest parity vector", () => {
    const row = {
      alpha: 1,
      items: [true, null, 1e-7],
      nested: { "😀": "astral", "\uffff": "bmp" },
      timestamp: "2026-07-09T12:34:56Z",
    };

    expect(sha256Hex(row)).toBe(
      "e199cead09a282ee400e6dc9c5ab8b4c12822b75d25bc2fc84bc1a6652528402",
    );
  });

  it("defines an atomic generation pointer and locked audit-chain head", () => {
    const sql = readFileSync(
      `${process.cwd()}/supabase/migrations/20260710_verifiable_projection_snapshots.sql`,
      "utf8",
    );

    expect(sql).toContain("create table if not exists thesis_audit_chain_head");
    expect(sql).toContain("chain_sequence bigint");
    expect(sql).toContain("where singleton\n    for update");
    expect(sql).toContain("last_sequence + 1");
    expect(sql).not.toContain("order by event_time desc");
    expect(sql).toContain(
      "create table if not exists thesis_projection_generations",
    );
    expect(sql).toContain(
      "create table if not exists thesis_projection_active_generation",
    );
    expect(sql).toContain("thesis_projection_generations_append_only");
  });

  it("builds a synthetic catalog at three times today's target count", () => {
    const template = FORECAST_CELLS[0];
    const syntheticCatalog = Array.from(
      { length: FORECAST_CELLS.length * 3 },
      (_, index): ForecastCell => ({
        ...template,
        slug: `synthetic-scale-${index}`,
        title: `Synthetic scale target ${index}`,
        question: `Synthetic projection scaling target ${index}`,
        dataPointId: undefined,
        policyParameter: undefined,
        conditionalOn: undefined,
        series: undefined,
        predictionRun: undefined,
        comparisonRuns: undefined,
        resolvedOutcome: undefined,
        resolutionSourceUrl: `https://example.gov/synthetic/${index}`,
        reasoning: [],
      }),
    );

    const projection = buildTargetArchitectureProjection(syntheticCatalog);

    expect(projection.counts.targets).toBe(FORECAST_CELLS.length * 3);
    expect(projection.counts.forecastRuns).toBe(projection.counts.targets);
    expect(projection.counts.forecastDistributionPoints).toBe(
      projection.counts.forecastRuns * 201,
    );
  }, 60_000);

  it("builds the real catalog without collisions and guards its ID projection", () => {
    // Pinned grand totals would break the publish gate on every legitimate
    // wave, so this asserts the invariants the snapshot stood for instead:
    // globally unique identifiers, counts that describe the projection
    // exactly, and a fully deterministic ID projection for identical input.
    const projection = buildTargetArchitectureProjection(
      FORECAST_CELLS,
      THESIS_TARGET_LEDGER,
    );
    const identifierProjection = (candidate: typeof projection) => ({
      targetIds: candidate.targets.map((row) => row.targetId),
      sourceSeriesIds: candidate.sourceSeries.map((row) => row.sourceSeriesId),
      runIds: candidate.forecastRuns.map((row) => row.runId),
      artifactRefIds: candidate.artifactRefs.map((row) => row.artifactRefId),
    });
    const identifiers = identifierProjection(projection);
    for (const [family, ids] of Object.entries(identifiers)) {
      expect(new Set(ids).size, `${family} must be collision-free`).toBe(
        ids.length,
      );
      expect(ids.length, `${family} must be non-empty`).toBeGreaterThan(0);
    }

    const countedTables: Record<string, number | undefined> = {
      targets: projection.targets.length,
      sourceSeries: projection.sourceSeries.length,
      forecastRuns: projection.forecastRuns.length,
      artifactRefs: projection.artifactRefs.length,
      observations: projection.observations.length,
      observationVintages: projection.observationVintages.length,
      forecastDistributionPoints: projection.forecastDistributions.length,
    };
    for (const [key, expected] of Object.entries(countedTables)) {
      expect(
        projection.counts[key as keyof typeof projection.counts],
        `counts.${key} must describe the projection exactly`,
      ).toBe(expected);
    }
    expect(projection.counts.targetVersions).toBe(projection.counts.targets);
    expect(projection.counts.observationVintages).toBe(
      projection.counts.observations,
    );

    const rebuilt = buildTargetArchitectureProjection(
      FORECAST_CELLS,
      THESIS_TARGET_LEDGER,
    );
    expect(sha256Hex(identifierProjection(rebuilt))).toBe(
      sha256Hex(identifiers),
    );

    expect(
      projection.forecastDistributions.every(
        (point) =>
          ["agent_reported", "interval_seeded"].includes(
            point.distributionProvenance,
          ) && point.transformVersion.endsWith("_v1"),
      ),
    ).toBe(true);
  });

  it("retains full payload digests while truncating public IDs to 16 hex", () => {
    const projection = buildTargetArchitectureProjection(
      FORECAST_CELLS,
      THESIS_TARGET_LEDGER,
    );

    expect(projection.observations.length).toBeGreaterThan(0);
    expect(
      projection.observations.every((row) => FULL_DIGEST.test(row.payloadHash)),
    ).toBe(true);
    expect(
      projection.observationVintages.every((row) =>
        FULL_DIGEST.test(row.normalizedPayloadHash),
      ),
    ).toBe(true);
    expect(
      projection.packVersions.every((row) =>
        FULL_DIGEST.test(row.promptContentHash),
      ),
    ).toBe(true);
    expect(
      projection.strategyVersions.every(
        (row) =>
          (!row.promptPolicyHash || FULL_DIGEST.test(row.promptPolicyHash)) &&
          (!row.toolPolicyHash || FULL_DIGEST.test(row.toolPolicyHash)),
      ),
    ).toBe(true);
    expect(
      projection.artifactRefs.every((row) => FULL_DIGEST.test(row.contentHash)),
    ).toBe(true);
    expect(
      projection.artifactRefs
        .filter((row) => /^artifact\.[0-9a-f]+$/.test(row.artifactRefId))
        .every((row) => /^artifact\.[0-9a-f]{16}$/.test(row.artifactRefId)),
    ).toBe(true);
  });

  it("throws with both payload digests when truncated artifact IDs collide", () => {
    const base = FORECAST_CELLS.find((forecast) => forecast.predictionRun);
    if (!base?.predictionRun) throw new Error("Expected a recorded forecast");
    const prefix = "0123456789abcdef";
    const firstDigest = `${prefix}${"0".repeat(48)}`;
    const secondDigest = `${prefix}${"f".repeat(48)}`;
    const activityLog: PredictionRunActivityArtifact[] = [
      {
        artifactType: "prompt",
        path: "collision/first.txt",
        sha256: firstDigest,
        bytes: 1,
        createdAt: base.predictionRun.runAt,
      },
      {
        artifactType: "stdout",
        path: "collision/second.txt",
        sha256: secondDigest,
        bytes: 1,
        createdAt: base.predictionRun.runAt,
      },
    ];
    const collidingForecast: ForecastCell = {
      ...base,
      predictionRun: { ...base.predictionRun, activityLog },
    };

    expect(() =>
      buildTargetArchitectureProjection([collidingForecast]),
    ).toThrow(new RegExp(`${firstDigest} and ${secondDigest}`));
  });

  it("commits run IDs to the forecast output distribution summary", () => {
    const forecast = FORECAST_CELLS[0];
    const run = getForecastRunEntries(forecast)[0];
    const originalId = buildRecordedPredictionRunId(
      forecast,
      run.predictionRun?.runAt,
      run.variantId,
      run,
    );
    const changedId = buildRecordedPredictionRunId(
      forecast,
      run.predictionRun?.runAt,
      run.variantId,
      { ...run, pointEstimate: run.pointEstimate + 1 },
    );

    expect(originalId).toMatch(/\.[0-9a-f]{16}$/);
    expect(changedId).not.toBe(originalId);
  });

  it("commits resolution hashes and score IDs to the observed value", () => {
    const forecast = FORECAST_CELLS.find((row) => row.dataPointId);
    if (!forecast?.dataPointId) throw new Error("Expected a ledger target");
    const run = getForecastRunEntries(forecast)[0];
    const observation: ObservationRecordedLedgerEntry = {
      kind: "observation_recorded",
      observationId: `obs.${forecast.dataPointId}`,
      dataPointId: forecast.dataPointId,
      periodLabel: forecast.resolutionDate,
      value: run.pointEstimate,
      unit: forecast.unit,
      observedAt: forecast.resolutionDate,
      resolvedAt: forecast.resolutionDate,
      sourceKind: "official_release",
      source: forecast.resolutionSource,
      sourceUrl: forecast.resolutionSourceUrl,
    };
    const changedObservation = { ...observation, value: observation.value + 1 };
    const originalEvent = buildPredictionResolutionEvents(
      [forecast],
      [observation],
    )[0];
    const changedEvent = buildPredictionResolutionEvents(
      [forecast],
      [changedObservation],
    )[0];
    const originalScore = scoreResolvedForecastRun(forecast, run, [
      observation,
    ]);
    const changedScore = scoreResolvedForecastRun(forecast, run, [
      changedObservation,
    ]);
    const scoreProjection = buildTargetArchitectureProjection(
      [forecast],
      [observation],
    );

    expect(originalEvent.payloadHash).toMatch(FULL_DIGEST);
    expect(changedEvent.payloadHash).not.toBe(originalEvent.payloadHash);
    expect(originalScore?.scoreId).toContain(
      "numeric_cdf_crps_v3_ledger_scale",
    );
    expect(originalScore?.scoreId).toMatch(/\.[0-9a-f]{16}$/);
    expect(changedScore?.scoreId).not.toBe(originalScore?.scoreId);
    expect(scoreProjection.scores.length).toBeGreaterThan(0);
    expect(
      scoreProjection.scores.every(
        (score) =>
          ["agent_reported", "interval_seeded"].includes(
            score.distributionProvenance,
          ) && score.transformVersion.endsWith("_v1"),
      ),
    ).toBe(true);
    expect(
      scoreProjection.scores.every((score) =>
        FULL_DIGEST.test(score.scoreHash),
      ),
    ).toBe(true);
  });

  it("commits score IDs to the distribution transform version", () => {
    const payload = {
      runId: "run.test",
      resolutionEventId: "resolution_event.test",
      scoringRule: "numeric_cdf_crps_v3_ledger_scale" as const,
      forecastOutput: { pointEstimate: 1 },
      outcome: { observedValue: 1 },
      normalizationScale: 1,
      normalizationScaleSource: "ledger_dispersion",
      normalizationScaleCutoff: "2026-06-01T00:00:00Z",
      normalizationScaleObservationCount: 3,
      observedAt: "2026-07-01T00:00:00Z",
      chronology: "verified",
      chronologyPolicy: "test",
      contractBinding: "contract_bound",
      contractBindingPolicy: "test",
      conditionId: null,
      conditionStatus: null,
    };

    expect(
      buildScoreId({ ...payload, transformVersion: "interval_anchor_v1" }),
    ).not.toBe(
      buildScoreId({ ...payload, transformVersion: "interval_anchor_v2" }),
    );
  });
});
