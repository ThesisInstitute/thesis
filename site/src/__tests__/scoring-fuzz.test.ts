import fc from "fast-check";
import { describe, expect, it, vi } from "vitest";
import {
  buildBrierRewardExport,
  hasUsableNormalizationScale,
} from "@/data/brier-lab";
import type { ForecastCell } from "@/data/forecast-cells";
import type { TargetRegisteredLedgerEntry } from "@/data/ledger-targets";
import {
  buildNumericCdfFromInterval,
  scoreNumericCdfDistribution,
  validateNumericCdfDistribution,
  type NumericCdfDistribution,
} from "@/data/prediction-distribution";
import {
  buildPredictionSpecs,
  buildRecordedPredictionRunRecords,
} from "@/data/prediction-specs";
import {
  NORMALIZATION_SCALE_RELATIVE_FLOOR,
  targetNormalizationScale,
  type ObservationRecordedLedgerEntry,
  type PolicyEngineLedgerEntry,
} from "@/data/thesis-log";
import { buildLedgerPersistenceBaseline } from "@/data/time-series-priors";
import { WITNESSED_CUSTODY_ROOTS } from "@/data/witnessed-timeline";

// Property tests for the numeric scoring path: the CRPS kernel, the
// interval transform, the ledger normalization scale, the persistence
// baseline, and the reward rows built from them. Every earlier failure of
// this path was a floating-point or degenerate-input case that example
// tests never reached: a 1.57e-16 residue scale inflated /calibration
// means to 1.18e13 (10670132) and, left ungated per row, published a
// -7.08e13 reward on 2026-09-23; a flat history's zero-width baseline
// collapses the 201-point grid and throws at scoring.

// Execution verification is exercised without mocks elsewhere
// (published-scoring-gate.test.ts); here every fixture run is published.
vi.mock("@/lib/forecast-publication", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/forecast-publication")>();
  return {
    ...actual,
    verifyForecastRun: () => ({
      eligible: true,
      reason: "Scoring fuzz fixture",
    }),
    filterPublishedForecasts: (forecasts: ForecastCell[]) => forecasts,
  };
});

// ---------------------------------------------------------------------
// Ledger fixture: a registered series with generated pre-cutoff history
// and one post-cutoff outcome that resolves the forecast. The target is a
// real catalog registration (prediction specs require one) and the run
// carries a custody root the public chain witnessed before the outcome,
// so agent rows reach the witness-verified reward tier, not only the
// deterministic baseline.

const RUN_AT = "2026-04-11T00:00:00Z";
const TARGET_REGISTERED_AT = "2026-04-10T00:00:00Z";
const OUTCOME_AT = "2026-08-01T12:00:00Z";
const SERIES = "census.spm.child_poverty_rate";
const TARGET_PERIOD = "2025";
const TARGET_CONTENT_HASH = "a".repeat(64);
const RESPONSE_SHA256 = "b".repeat(64);

const witnessedRootSha256 = Object.entries(WITNESSED_CUSTODY_ROOTS).find(
  ([, entry]) =>
    entry.inventoryStatus === "complete" &&
    entry.headlineEligible &&
    entry.earliestWitnessedAt < OUTCOME_AT,
)?.[0];
if (!witnessedRootSha256) {
  throw new Error(
    "expected a witnessed, headline-eligible custody root in the timeline",
  );
}

const binding = {
  adapter: "generic-url" as const,
  sourceUrl: "https://example.test/series",
  sourceSeriesId: "FUZZ",
  field: "value",
  table: "fixture",
  transform: { operation: "identity", factor: 1 },
  releasePolicy: "first_print" as const,
  allowedHosts: ["example.test"],
  expectedReleaseWindow: { start: "2026-01-01", end: "2026-12-31" },
};

const dataPointIdFor = (period: string) => `${SERIES}.${period}`;

function registration(period: string): TargetRegisteredLedgerEntry {
  const dataPointId = dataPointIdFor(period);
  return {
    kind: "target_registered",
    dataPointId,
    observationId: `obs.${dataPointId}`,
    country: "US",
    periodLabel: period,
    unit: "percent",
    resolutionDate: period === TARGET_PERIOD ? "2026-08-01" : "2026-12-31",
    resolutionSource: "Fixture agency",
    resolutionRule: "First print",
    resolutionPolicy: "first_print",
    sourceKind: "official_release",
    source: "Fixture agency",
    note: "fixture",
    registrationState: "published",
    registeredAt: TARGET_REGISTERED_AT,
    targetContentHash: TARGET_CONTENT_HASH,
    series: SERIES,
    period,
    catalogSlug: `fuzz-${period}`,
    valueScale: 1,
    sourceBinding: binding,
  };
}

function observation(
  period: string,
  value: number,
  observedAt: string,
): ObservationRecordedLedgerEntry {
  const dataPointId = dataPointIdFor(period);
  return {
    kind: "observation_recorded",
    observationId: `obs.${dataPointId}`,
    dataPointId,
    periodLabel: period,
    unit: "percent",
    value,
    observedAt,
    resolvedAt: observedAt,
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
      period,
      releasePolicy: binding.releasePolicy,
      table: binding.table,
      field: binding.field,
      transform: binding.transform,
      unit: "percent",
      responseSha256: RESPONSE_SHA256,
    },
  };
}

// Weekly prints through 2025, all before both cutoffs: the target's
// registration (normalization) and the primary run (persistence).
function ledgerFor(
  history: number[],
  outcome: number,
): PolicyEngineLedgerEntry[] {
  const weekMs = 7 * 86_400_000;
  const start = Date.parse("2025-01-01T12:00:00Z");
  return [
    registration(TARGET_PERIOD),
    ...history.flatMap((value, index) => {
      const period = `h${String(index).padStart(3, "0")}`;
      const observedAt = new Date(start + index * weekMs).toISOString();
      return [registration(period), observation(period, value, observedAt)];
    }),
    observation(TARGET_PERIOD, outcome, OUTCOME_AT),
  ];
}

function forecastFor(history: number[]): ForecastCell {
  const last = history.at(-1)!;
  const spread = Math.max(Math.abs(last) * 0.05, 1);
  return {
    slug: "fuzz-target",
    country: "US",
    type: "data",
    title: "Fuzz series",
    question: "Fuzz series first print",
    unit: "percent",
    pointEstimate: last,
    ciLow: last - spread,
    ciHigh: last + spread,
    confidence: 0.8,
    resolutionDate: "2026-08-01",
    resolutionSource: "Fixture agency",
    resolutionRule: "First print",
    dataPointId: dataPointIdFor(TARGET_PERIOD),
    historicalContext: [],
    drivers: ["fixture"],
    predictionRun: {
      kind: "recorded-agent-run",
      runAt: RUN_AT,
      agent: "fuzz.agent",
      model: "fuzz-model",
      sourceContext: [],
      custodyRootSha256: witnessedRootSha256,
    },
    reasoning: [
      {
        kind: "forecast",
        point: last,
        ciLow: last - spread,
        ciHigh: last + spread,
      },
    ],
  };
}

// ---------------------------------------------------------------------
// Histories the way official series arrive: decimal strings parsed to the
// nearest double. Mantissas are integers, so "equal steps" means equal in
// decimal, exactly the case binary floating point cannot represent.

type Shape = "flat" | "linear" | "varied";

interface HistoryCase {
  shape: Shape;
  decimals: number;
  values: number[];
}

const decimalValue = (mantissa: number, decimals: number) =>
  Number(`${mantissa}e-${decimals}`);

// Magnitude exponent plus decimals stays within 10 significant digits, so
// a genuinely varied history's step dispersion is at least ~3e-11 of its
// magnitude — well above NORMALIZATION_SCALE_RELATIVE_FLOOR — and every
// mantissa is a safe integer. Official series publish far fewer digits.
const historyArbitrary = (minLength: number) =>
  fc
    .record({
      shape: fc.constantFrom<Shape>("flat", "linear", "varied"),
      exponent: fc.integer({ min: -3, max: 8 }),
      decimals: fc.integer({ min: 0, max: 4 }),
      length: fc.integer({ min: minLength, max: 14 }),
      negative: fc.boolean(),
      seed: fc.array(fc.integer({ min: -1_000_000, max: 1_000_000 }), {
        minLength: 16,
        maxLength: 16,
      }),
    })
    .filter(({ exponent, decimals }) => exponent + decimals <= 10)
    .map(({ shape, exponent, decimals, length, negative, seed }) => {
      const unit = 10 ** Math.max(exponent + decimals, 0);
      const sign = negative ? -1 : 1;
      const base = sign * Math.round((Math.abs(seed[0]) / 1_000_000) * unit);
      const step = Math.max(Math.round(unit / 1000), 1) * (seed[1] || 1);
      const mantissas = Array.from({ length }, (_, index) => {
        if (shape === "flat") return base;
        if (shape === "linear") return base + index * step;
        return base + Math.round(seed[(index % 14) + 2] * (unit / 1_000_000));
      });
      // A "varied" draw can still come out flat or linear by chance; the
      // shape is decided by the mantissas, not by the label.
      const steps = mantissas.slice(1).map((value, i) => value - mantissas[i]);
      const decidedShape: Shape = steps.every((s) => s === 0)
        ? "flat"
        : steps.every((s) => s === steps[0])
          ? "linear"
          : "varied";
      return {
        shape: decidedShape,
        decimals,
        values: mantissas.map((mantissa) => decimalValue(mantissa, decimals)),
      } satisfies HistoryCase;
    });

const magnitudeOf = (values: number[]) =>
  values.reduce((largest, value) => Math.max(largest, Math.abs(value)), 0);

// Outcomes on, near, and far from the history, including its exact last
// print (the unchanged-print case where a degenerate baseline scores ~0).
const outcomeFor = (values: number[], pick: number, offset: number) => {
  const last = values.at(-1)!;
  const scale = Math.max(magnitudeOf(values), 1e-3);
  if (pick === 0) return last;
  if (pick === 1) return values[0];
  return last + offset * scale;
};

// ---------------------------------------------------------------------
// Independent CRPS check: the defining integral ∫ (F(x) - 1{x >= y})² dx
// by Simpson's rule between consecutive knots and y, where the integrand
// is quadratic (so Simpson is exact), plus the analytic tails outside the
// support. It shares no code with the kernel's closed-form segments.

function cdfAt(points: NumericCdfDistribution["points"], x: number) {
  if (x <= points[0].value)
    return x < points[0].value ? 0 : points[0].probability;
  for (let index = 1; index < points.length; index += 1) {
    const left = points[index - 1];
    const right = points[index];
    if (x <= right.value) {
      return (
        left.probability +
        ((x - left.value) / (right.value - left.value)) *
          (right.probability - left.probability)
      );
    }
  }
  return 1;
}

function quadratureCrps(distribution: NumericCdfDistribution, y: number) {
  const points = distribution.points;
  const lower = points[0].value;
  const upper = points.at(-1)!.value;
  let total = 0;
  if (y < lower) total += lower - y;
  if (y > upper) total += y - upper;
  const breaks = [...points.map((point) => point.value), y]
    .filter((x) => x >= lower && x <= upper)
    .sort((a, b) => a - b);
  for (let index = 1; index < breaks.length; index += 1) {
    const a = breaks[index - 1];
    const b = breaks[index];
    if (!(b > a)) continue;
    // The indicator is constant on (a, b); evaluate it at the midpoint so
    // the endpoint that equals y does not flip it.
    const indicator = (a + b) / 2 >= y ? 1 : 0;
    const f = (x: number) => (cdfAt(points, x) - indicator) ** 2;
    total += ((b - a) / 6) * (f(a) + 4 * f((a + b) / 2) + f(b));
  }
  return total;
}

// Arbitrary valid piecewise-linear CDFs: strictly increasing knots at any
// location and scale, monotone probabilities pinned to 0 and 1, including
// flat runs and jumps between knots.
const cdfArbitrary = fc
  .record({
    origin: fc.double({ min: -1e6, max: 1e6, noNaN: true }),
    scaleExponent: fc.integer({ min: -3, max: 4 }),
    gaps: fc.array(fc.double({ min: 0.01, max: 1, noNaN: true }), {
      minLength: 1,
      maxLength: 24,
    }),
    rises: fc.array(fc.double({ min: 0, max: 1, noNaN: true }), {
      minLength: 25,
      maxLength: 25,
    }),
  })
  .map(({ origin, scaleExponent, gaps, rises }) => {
    const scale = 10 ** scaleExponent;
    const values = [origin];
    for (const gap of gaps) values.push(values.at(-1)! + gap * scale);
    const weights = rises.slice(0, gaps.length);
    const totalWeight = weights.reduce((sum, weight) => sum + weight, 0) || 1;
    let cumulative = 0;
    const probabilities = [0];
    for (const weight of weights.slice(0, -1)) {
      cumulative += weight / totalWeight;
      probabilities.push(Math.min(cumulative, 1));
    }
    probabilities.push(1);
    return {
      format: "numeric_cdf_v1",
      pointCount: values.length,
      support: { lower: values[0], upper: values.at(-1)! },
      points: values.map((value, index) => ({
        value,
        probability: probabilities[index],
      })),
      summary: {
        pointEstimate: values[0],
        median: values[0],
        interval80: { lower: values[0], upper: values.at(-1)! },
      },
      provenance: "agent_reported",
    } as unknown as NumericCdfDistribution;
  })
  .filter((distribution) => {
    const values = distribution.points.map((point) => point.value);
    return values.every(
      (value, index) => index === 0 || value > values[index - 1],
    );
  });

describe("CRPS kernel", () => {
  it("is finite, nonnegative, and equals the defining integral for any valid CDF and outcome", () => {
    fc.assert(
      fc.property(
        cdfArbitrary,
        fc.integer({ min: 0, max: 3 }),
        fc.double({ min: -2, max: 2, noNaN: true }),
        (distribution, pick, offset) => {
          expect(validateNumericCdfDistribution(distribution)).toEqual([]);
          const points = distribution.points;
          const span = points.at(-1)!.value - points[0].value;
          const knot = points[Math.floor(points.length / 2)].value;
          const y =
            pick === 0
              ? knot
              : pick === 1
                ? points[0].value - Math.abs(offset) * span
                : points[0].value + ((offset + 2) / 4) * span * 1.5;
          const { crps, probabilityIntegralTransform } =
            scoreNumericCdfDistribution(distribution, y);
          expect(Number.isFinite(crps)).toBe(true);
          expect(crps).toBeGreaterThanOrEqual(0);
          expect(probabilityIntegralTransform).toBeGreaterThanOrEqual(0);
          expect(probabilityIntegralTransform).toBeLessThanOrEqual(1);
          const expected = quadratureCrps(distribution, y);
          // The kernel rounds to 12 significant digits. Every width both
          // sides compute (x - y, x_i - x_{i-1}) carries a few ulps of the
          // location, and the integrand is at most 1, so location-scaled
          // ulps bound the rest.
          const location = Math.max(
            Math.abs(y),
            Math.abs(points[0].value),
            Math.abs(points.at(-1)!.value),
          );
          expect(Math.abs(crps - expected)).toBeLessThanOrEqual(
            1e-9 * expected + 64 * Number.EPSILON * location + 1e-15,
          );
        },
      ),
      { numRuns: 300 },
    );
  });
});

describe("interval_anchor_v1 transform", () => {
  // The transform's representable domain: 201 grid points stay strictly
  // increasing after 12-significant-digit rounding only when the support
  // is wider than ~1e-9 of the magnitude. Relative widths from 1e-7 up
  // leave two orders of margin; narrower intervals are a caller contract
  // violation that the scorer's validator refuses (see the baseline case).
  it("materializes a valid, scorable CDF for every interval it can represent", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: -3, max: 9 }),
        fc.double({ min: 1, max: 10, noNaN: true }),
        fc.boolean(),
        fc.double({ min: 1e-7, max: 10, noNaN: true }),
        fc.double({ min: 1e-7, max: 10, noNaN: true }),
        fc.double({ min: -5, max: 5, noNaN: true }),
        (exponent, mantissa, negative, lowerWidth, upperWidth, offset) => {
          const pointEstimate = (negative ? -1 : 1) * mantissa * 10 ** exponent;
          const reference = Math.abs(pointEstimate);
          const ciLow = pointEstimate - lowerWidth * reference;
          const ciHigh = pointEstimate + upperWidth * reference;
          const distribution = buildNumericCdfFromInterval({
            pointEstimate,
            ciLow,
            ciHigh,
          });
          expect(validateNumericCdfDistribution(distribution)).toEqual([]);
          const outcome = pointEstimate + offset * (ciHigh - ciLow);
          const { crps } = scoreNumericCdfDistribution(distribution, outcome);
          expect(Number.isFinite(crps)).toBe(true);
          expect(crps).toBeGreaterThanOrEqual(0);
        },
      ),
      { numRuns: 300 },
    );
  });
});

describe("ledger normalization scale", () => {
  it("is unavailable for zero decimal dispersion at any magnitude, and otherwise clears the relative floor", () => {
    fc.assert(
      fc.property(
        historyArbitrary(3),
        fc.double({ min: -3, max: 3, noNaN: true }),
        (history, offset) => {
          const ledger = ledgerFor(
            history.values,
            outcomeFor(history.values, 2, offset),
          );
          const normalization = targetNormalizationScale(
            forecastFor(history.values),
            ledger,
          );
          expect(normalization.observationCount).toBe(history.values.length);
          if (history.shape === "varied") {
            expect(normalization.source).toBe("ledger_dispersion");
          } else {
            // Equal decimal steps: any positive "scale" is float residue.
            expect(normalization).toMatchObject({
              scale: null,
              source: "unavailable",
            });
          }
          if (normalization.scale !== null) {
            expect(Number.isFinite(normalization.scale)).toBe(true);
            expect(normalization.scale).toBeGreaterThan(
              magnitudeOf(history.values) * NORMALIZATION_SCALE_RELATIVE_FLOOR,
            );
          }
        },
      ),
      { numRuns: 300 },
    );
  });
});

describe("ledger persistence baseline", () => {
  it("is either unavailable with a reason or a CDF the scorer accepts for any outcome", () => {
    fc.assert(
      fc.property(
        historyArbitrary(2),
        fc.integer({ min: 0, max: 2 }),
        fc.double({ min: -3, max: 3, noNaN: true }),
        (history, pick, offset) => {
          const outcome = outcomeFor(history.values, pick, offset);
          const result = buildLedgerPersistenceBaseline(
            forecastFor(history.values),
            ledgerFor(history.values, outcome),
          );
          if (result.record.status === "unavailable") {
            expect(result.comparisonRun).toBeNull();
            expect(result.record.reason).toEqual(expect.any(String));
            expect(result.record.reason!.length).toBeGreaterThan(0);
            return;
          }
          const distribution = result.comparisonRun!.predictionDistribution!;
          expect(validateNumericCdfDistribution(distribution)).toEqual([]);
          const { crps } = scoreNumericCdfDistribution(distribution, outcome);
          expect(Number.isFinite(crps)).toBe(true);
          expect(crps).toBeGreaterThanOrEqual(0);
        },
      ),
      { numRuns: 300 },
    );
  });
});

describe("reward export rows", () => {
  it("carry a reward only under a usable scale, equal to minus normalized CRPS", () => {
    fc.assert(
      fc.property(
        historyArbitrary(2),
        fc.integer({ min: 0, max: 2 }),
        fc.double({ min: -3, max: 3, noNaN: true }),
        (history, pick, offset) => {
          const forecast = forecastFor(history.values);
          const ledger = ledgerFor(
            history.values,
            outcomeFor(history.values, pick, offset),
          );
          const specs = buildPredictionSpecs([forecast]);
          // Building the export scores every run it contains, so a baseline
          // the scorer cannot read would throw here.
          const reward = buildBrierRewardExport({
            forecasts: [forecast],
            specs,
            runs: buildRecordedPredictionRunRecords([forecast], specs),
            ledger,
          });
          for (const row of reward.rewardRows) {
            const { value } = row.reward;
            const components = row.reward.components;
            if (value === null) continue;
            expect(Number.isFinite(value)).toBe(true);
            expect(hasUsableNormalizationScale(components)).toBe(true);
            expect(value).toBe(-components.normalizedCrps!);
          }
          if (history.shape !== "varied") {
            expect(
              reward.rewardRows.every((row) => row.reward.value === null),
            ).toBe(true);
          }
          expect(reward.counts.scoredRuns).toBe(
            reward.rewardRows.filter((row) => row.reward.value !== null).length,
          );
        },
      ),
      { numRuns: 60 },
    );
  });
});
