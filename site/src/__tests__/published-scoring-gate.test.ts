import { beforeAll, describe, expect, it } from "vitest";
import {
  FORECAST_CELLS,
  getForecastRunEntries,
  type ForecastCell,
} from "@/data/forecast-cells";
import { buildBrierRewardExport } from "@/data/brier-lab";
import {
  buildPredictionSpecs,
  buildRecordedPredictionRunRecords,
} from "@/data/prediction-specs";
import {
  evaluateResolvedForecastRun,
  isScoreEligibleForecastRun,
  loadPolicyEngineLedger,
  scoreResolvedForecast,
  targetNormalizationScale,
  withResolvedOutcomes,
  type PolicyEngineLedgerEntry,
} from "@/data/thesis-log";
import {
  PERSISTENCE_BASELINE_AGENT,
  TIME_SERIES_PRIOR_VARIANT_ID,
} from "@/data/time-series-priors";
import { filterPublishedForecasts } from "@/lib/forecast-publication";

// Deliberately use the real artifact verifier here. Mathematical/chronology
// fixtures elsewhere mock that boundary; these tests enforce the production
// path even when callers pass raw or forged catalog data.
describe("published scoring and reward boundary", () => {
  const prototype: ForecastCell = {
    ...FORECAST_CELLS.find((cell) => cell.slug === "spm-child-poverty-2025")!,
    predictionRun: undefined,
    comparisonRuns: [],
  };
  let ledger: PolicyEngineLedgerEntry[];
  let published: ForecastCell[];

  beforeAll(async () => {
    ledger = await loadPolicyEngineLedger();
    published = filterPublishedForecasts(FORECAST_CELLS);
    expect(published.length).toBeGreaterThan(0);
  });

  it("rejects a prototype before chronology or resolution can give it a score", () => {
    const run = getForecastRunEntries(prototype)[0];
    expect(evaluateResolvedForecastRun(prototype, run, ledger)).toMatchObject({
      exclusion: { reason: "unverified_run" },
    });
    expect(scoreResolvedForecast(prototype, ledger)).toBeUndefined();
  });

  it("does not trust model names, timestamps, or fabricated artifact metadata", () => {
    const forged: ForecastCell = {
      ...prototype,
      predictionRun: {
        kind: "recorded-agent-run",
        runAt: "2026-01-01T00:00:00Z",
        model: "a-real-model-name",
        agent: "thesis.analyst",
        sourceContext: [],
        activityLog: [
          {
            artifactType: "raw_response",
            path: "records/thesis-analyst/missing-run/raw_response.json",
            sha256: "a".repeat(64),
            bytes: 100,
            createdAt: "2026-01-01T00:00:00Z",
          },
        ],
      },
    };
    expect(
      isScoreEligibleForecastRun(
        forged,
        getForecastRunEntries(forged)[0],
        ledger,
      ),
    ).toBe(false);
  });

  it("omits unverified runs entirely from training, evaluation, and judge exports", () => {
    const specs = buildPredictionSpecs([prototype]);
    const result = buildBrierRewardExport({
      forecasts: [prototype],
      specs,
      runs: buildRecordedPredictionRunRecords([prototype], specs),
      ledger,
    });
    expect(result.rewardRows).toEqual([]);
    expect(result.leaderboard).toEqual([]);
    expect(result.counts).toMatchObject({
      specs: 0,
      runs: 0,
      traceJudgedRuns: 0,
    });
    expect(result.judgeResults.traceQuality).toEqual([]);
    expect(
      Object.values(result.splits).every((split) => split.runs === 0),
    ).toBe(true);
  });

  it("requires the numbers in a real archived run to remain unchanged", () => {
    const forecast = published[0];
    const run = getForecastRunEntries(forecast)[0];
    expect(isScoreEligibleForecastRun(forecast, run, ledger)).toBe(true);
    expect(
      isScoreEligibleForecastRun(
        forecast,
        { ...run, pointEstimate: run.pointEstimate + 1 },
        ledger,
      ),
    ).toBe(false);
  });

  it("keeps verified records while omitting an injected unarchived comparison", () => {
    const verified = published[0];
    const run = getForecastRunEntries(verified)[0];
    const mixed: ForecastCell = {
      ...verified,
      comparisonRuns: [
        ...(verified.comparisonRuns ?? []),
        {
          ...run,
          variantId: "forged-comparison",
          label: "Fabricated comparison",
          predictionRun: run.predictionRun!,
          pointEstimate: run.pointEstimate + 1,
        },
      ],
    };
    const specs = buildPredictionSpecs([mixed]);
    const result = buildBrierRewardExport({
      forecasts: [mixed],
      specs,
      runs: buildRecordedPredictionRunRecords([mixed], specs),
      ledger,
    });
    expect(result.rewardRows.length).toBeGreaterThan(0);
    expect(
      result.rewardRows.some((row) => row.runVariantId === "forged-comparison"),
    ).toBe(false);
    expect(
      result.judgeResults.traceQuality.some(
        (row) => row.runLabel === "Fabricated comparison",
      ),
    ).toBe(false);
  });

  it("retains exactly reconstructed ledger baselines but rejects impersonations", () => {
    const prepared = withResolvedOutcomes(published, ledger);
    const forecast = prepared.find(
      (cell) => cell.persistenceBaseline?.status === "available",
    );
    expect(forecast).toBeDefined();
    const baseline = getForecastRunEntries(forecast!).find(
      (run) => run.variantId === TIME_SERIES_PRIOR_VARIANT_ID,
    )!;
    expect(isScoreEligibleForecastRun(forecast!, baseline, ledger)).toBe(true);
    expect(
      isScoreEligibleForecastRun(
        forecast!,
        { ...baseline, pointEstimate: baseline.pointEstimate + 1 },
        ledger,
      ),
    ).toBe(false);
    const forged = {
      ...getForecastRunEntries(prototype)[0],
      variantId: TIME_SERIES_PRIOR_VARIANT_ID,
      isPrimary: false,
      predictionRun: {
        ...baseline.predictionRun!,
        agent: PERSISTENCE_BASELINE_AGENT,
      },
    };
    expect(isScoreEligibleForecastRun(prototype, forged, ledger)).toBe(false);
  });

  it("preserves the original legacy normalization cutoff after display promotion", () => {
    const originalCutoff = "2026-01-01T00:00:00Z";
    const forecast: ForecastCell = {
      ...prototype,
      normalizationCutoffRunAt: originalCutoff,
      predictionRun: {
        kind: "recorded-agent-run",
        runAt: "2026-02-01T00:00:00Z",
        agent: "test",
        model: "test",
        sourceContext: [],
      },
    };
    expect(targetNormalizationScale(forecast, []).cutoff).toBe(originalCutoff);
    expect(
      targetNormalizationScale(
        { ...forecast, normalizationCutoffRunAt: null },
        [],
      ).cutoff,
    ).toBeNull();
  });
});
