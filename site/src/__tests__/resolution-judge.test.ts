import fc from "fast-check";
import { beforeAll, describe, expect, it } from "vitest";
import { isNormalizedScoreAggregateEligible } from "@/data/brier-lab";
import type { PredictionPackSet } from "@/data/forecast-cells";
import {
  buildForecastJudgeExport,
  buildForecastResolutionJudgeRecords,
  type ForecastResolutionFailureMode,
  type ForecastResolutionJudgeRecord,
} from "@/data/forecast-judges";
import {
  loadPolicyEngineLedger,
  scoreResolvedForecasts,
  withResolvedOutcomes,
  type ResolvedForecastScore,
} from "@/data/thesis-log";
import { getPublishedForecasts } from "@/lib/forecast-publication";

// Post-resolution reviews tag failure modes only on evidence. A score whose
// ledger scale is unusable can never reach well_calibrated, so the review
// must not read that as a failure: it tags raw-unit evidence (coverage, the
// signed error against the run's own interval width, the target binding)
// and otherwise returns not_assessable. Every score with a usable scale keeps
// the original classifier's review byte for byte.

type Review = Pick<
  ForecastResolutionJudgeRecord,
  "primaryFailureMode" | "tags" | "severity" | "explanation"
>;

const OUTCOME_VERDICTS: ReadonlySet<ForecastResolutionFailureMode> = new Set([
  "well_calibrated",
  "not_assessable",
]);

// ---------------------------------------------------------------------------
// Differential oracle: the classifier this change replaces, copied verbatim
// from main at 59bcd5fd, the merge of #288 (whose explanation already names
// missing step dispersion). Usable-scale scores must still get exactly this
// review.
// ---------------------------------------------------------------------------

function legacyClassifyResolutionFailureModes(
  score: ResolvedForecastScore,
): ForecastResolutionFailureMode[] {
  if (
    score.interval80Covered &&
    score.normalizedCrps !== null &&
    score.normalizedCrps <= 0.25
  ) {
    return ["well_calibrated"];
  }

  const modes: ForecastResolutionFailureMode[] = [];
  if (!score.interval80Covered) modes.push("interval_too_narrow");
  if (
    score.normalizedAbsoluteError !== null &&
    score.normalizedAbsoluteError > 1.25
  )
    modes.push("surprising_release");
  if (score.packSet?.packs.some((pack) => /projection/i.test(pack.label))) {
    modes.push("ignored_official_projection");
  }
  if (Math.abs(score.signedError) > score.interval80.width * 0.75) {
    modes.push(
      score.signedError > 0 ? "bad_baseline" : "overreacted_to_recent_data",
    );
  }
  if (!score.dataPointId) modes.push("resolution_or_units_risk");

  return modes.length ? [...new Set(modes)] : ["bad_baseline"];
}

function legacyGetFailureSeverity(score: ResolvedForecastScore) {
  if (
    score.interval80Covered &&
    score.normalizedCrps !== null &&
    score.normalizedCrps <= 0.25
  )
    return "none";
  if (
    (score.normalizedCrps !== null && score.normalizedCrps >= 1) ||
    (score.normalizedAbsoluteError !== null &&
      score.normalizedAbsoluteError >= 1)
  ) {
    return "high";
  }
  if (
    (score.normalizedCrps !== null && score.normalizedCrps >= 0.5) ||
    !score.interval80Covered
  ) {
    return "medium";
  }
  return "low";
}

function legacyBuildResolutionExplanation(
  score: ResolvedForecastScore,
  mode: ForecastResolutionFailureMode,
) {
  if (mode === "well_calibrated") {
    return "Observed value landed inside the forecast interval with low normalized CRPS.";
  }
  const normalized =
    score.normalizedCrps !== null
      ? `nCRPS ${round2(score.normalizedCrps)}`
      : score.normalizationScaleObservationCount < 3
        ? "nCRPS unavailable (fewer than three pre-cutoff ledger observations)"
        : // Enough observations, but targetNormalizationScale found no step
          // dispersion above its relative floor: a flat or exactly linear
          // history (continued-claims-week-2026-08-01 is the live case).
          "nCRPS unavailable (the pre-cutoff ledger history has no usable step dispersion)";
  return `Observed value ${score.observedValue} versus point ${score.pointEstimate}; signed error ${round2(score.signedError)}, ${normalized}. Primary review tag: ${mode.replace(/_/g, " ")}.`;
}

function round2(value: number) {
  return Math.round(value * 100) / 100;
}

function legacyReview(score: ResolvedForecastScore): Review {
  const tags = legacyClassifyResolutionFailureModes(score);
  const primaryFailureMode = tags[0] ?? "well_calibrated";
  return {
    primaryFailureMode,
    tags,
    severity: legacyGetFailureSeverity(score),
    explanation: legacyBuildResolutionExplanation(score, primaryFailureMode),
  };
}

function review(score: ResolvedForecastScore): Review {
  const [record] = buildForecastResolutionJudgeRecords([score]);
  return {
    primaryFailureMode: record.primaryFailureMode,
    tags: record.tags,
    severity: record.severity,
    explanation: record.explanation,
  };
}

// ---------------------------------------------------------------------------
// Raw-unit evidence, stated independently of the implementation.
// ---------------------------------------------------------------------------

function rawEvidence(score: ResolvedForecastScore) {
  const missedInterval = !score.interval80Covered;
  const largeError =
    Math.abs(score.signedError) > score.interval80.width * 0.75;
  const projectionPack = Boolean(
    score.packSet?.packs.some((pack) => /projection/i.test(pack.label)),
  );
  return {
    missedInterval,
    largeError,
    projectionPack,
    unbound: !score.dataPointId,
    any: missedInterval || largeError || !score.dataPointId,
  };
}

// The tags an unscalable score earns: legacy order, raw evidence only, a
// projection pack only alongside a raw miss, not_assessable when none fire.
function expectedUnscalableTags(
  score: ResolvedForecastScore,
): ForecastResolutionFailureMode[] {
  const evidence = rawEvidence(score);
  const tags: ForecastResolutionFailureMode[] = [];
  if (evidence.missedInterval) tags.push("interval_too_narrow");
  if (
    evidence.projectionPack &&
    (evidence.missedInterval || evidence.largeError)
  ) {
    tags.push("ignored_official_projection");
  }
  if (evidence.largeError) {
    tags.push(
      score.signedError > 0 ? "bad_baseline" : "overreacted_to_recent_data",
    );
  }
  if (evidence.unbound) tags.push("resolution_or_units_risk");
  return tags.length ? tags : ["not_assessable"];
}

// ---------------------------------------------------------------------------
// Score construction.
// ---------------------------------------------------------------------------

interface ScoreShape {
  pointEstimate: number;
  lower: number;
  upper: number;
  observedValue: number;
  // null: targetNormalizationScale refused (unavailable source).
  scale: number | null;
  normalizedCrps?: number;
  normalizedAbsoluteError?: number;
  observationCount: number;
  cutoff: string | null;
  packLabels?: string[];
  dataPointId?: string;
}

function makeScore(shape: ScoreShape): ResolvedForecastScore {
  const signedError = shape.observedValue - shape.pointEstimate;
  const width = Math.abs(shape.upper - shape.lower);
  const scale = shape.scale;
  const packSet: PredictionPackSet | undefined = shape.packLabels
    ? {
        packSetId: "packset.test",
        label: "Test packs",
        mode: "with_packs",
        packs: shape.packLabels.map((label, index) => ({
          packId: `pack.test.${index}`,
          version: "v1",
          label,
          kind: "data",
          summary: label,
        })),
      }
    : undefined;
  const runId = `run.test.${shape.pointEstimate}.${shape.observedValue}`;
  return {
    crps: Math.abs(signedError),
    probabilityIntegralTransform: 0.5,
    scoreId: `score.${runId}`,
    runId,
    runLabel: "Test run",
    packSet,
    packMode: packSet ? "with_packs" : "primary",
    packCount: packSet?.packs.length ?? 0,
    resolutionEventId: "resolution_event.test",
    scoringRule: "numeric_cdf_crps_v3_ledger_scale",
    distributionProvenance: "interval_seeded",
    transformVersion: "interval_anchor_v1",
    chronology: "witness_verified",
    chronologyProof: {
      status: "witnessed",
      custodyRootSha256: null,
      earliestWitnessedAt: null,
      inventoryStatus: null,
      headlineEligible: null,
      witnessDigest: null,
    },
    contractBinding: "contract_bound",
    observedAt: "2026-10-01T00:00:00Z",
    conditionId: null,
    conditionStatus: null,
    normalizationScale: scale,
    normalizationScaleSource:
      scale === null ? "unavailable" : "ledger_dispersion",
    normalizationScaleCutoff: shape.cutoff,
    normalizationScaleObservationCount: shape.observationCount,
    sharpness: scale === null ? null : width / scale,
    ledgerFactRef: "test.fact",
    forecastSlug: "test-target",
    dataPointId: shape.dataPointId ?? "test.series.2026-09.first_print",
    observationId: "observation.test",
    pointEstimate: shape.pointEstimate,
    observedValue: shape.observedValue,
    unit: "percent",
    interval80: { lower: shape.lower, upper: shape.upper, width },
    signedError,
    absoluteError: Math.abs(signedError),
    normalizedCrps:
      scale === null
        ? null
        : (shape.normalizedCrps ?? Math.abs(signedError) / scale),
    normalizedAbsoluteError:
      scale === null
        ? null
        : (shape.normalizedAbsoluteError ?? Math.abs(signedError) / scale),
    interval80Covered:
      shape.lower <= shape.observedValue && shape.observedValue <= shape.upper,
  };
}

// Same score as targetNormalizationScale would have stored it with the scale
// refused: every normalized field null, the source unavailable.
function withoutNormalization(
  score: ResolvedForecastScore,
): ResolvedForecastScore {
  return {
    ...score,
    normalizationScale: null,
    normalizationScaleSource: "unavailable",
    normalizedCrps: null,
    normalizedAbsoluteError: null,
    sharpness: null,
  };
}

const finite = (min: number, max: number) =>
  fc.double({ min, max, noNaN: true, noDefaultInfinity: true });

// Values that sit on or straddle every classifier threshold.
const normalizedValue = fc.oneof(
  fc.constantFrom(0, 0.25, 0.2500001, 0.5, 0.4999999, 1, 0.9999999, 1.25),
  fc.constantFrom(1.2500001, 3, 7.08e13),
  finite(0, 10),
);

const packLabels = fc.option(
  fc.array(
    fc.constantFrom(
      "CBO baseline projection",
      "Fed SEP projections pack",
      "Seasonal adjustment notes",
      "Release calendar",
    ),
    { minLength: 1, maxLength: 3 },
  ),
  { nil: undefined },
);

const intervalAndOutcome = fc
  .record({
    pointEstimate: finite(-1e4, 1e4),
    below: fc.oneof(fc.constant(0), finite(0, 100)),
    above: fc.oneof(fc.constant(0), finite(0, 100)),
    // Offsets near the 0.75-width threshold and the interval edges.
    offsetShare: fc.oneof(
      fc.constantFrom(-1.5, -1, -0.75, -0.5, 0, 0.5, 0.75, 1, 1.5),
      finite(-3, 3),
    ),
  })
  .map(({ pointEstimate, below, above, offsetShare }) => {
    const lower = pointEstimate - below;
    const upper = pointEstimate + above;
    const width = upper - lower;
    return {
      pointEstimate,
      lower,
      upper,
      observedValue: pointEstimate + offsetShare * (width === 0 ? 1 : width),
    };
  });

const commonFields = fc.record({
  packLabels,
  dataPointId: fc.oneof(
    { weight: 9, arbitrary: fc.constant("test.series.2026-09.first_print") },
    { weight: 1, arbitrary: fc.constant("") },
  ),
});

// Stored ledger-dispersion scales from three or more pre-cutoff
// observations. The constants are float residue from equal decimal steps
// (the continued-claims-week-2026-08-01 history left 1.57e-16).
// targetNormalizationScale now refuses residue where it computes the scale,
// but a stored score can still carry one, and the review must follow
// whatever the usable-scale gate decides about it.
const ledgerScaledScore = fc
  .tuple(
    intervalAndOutcome,
    commonFields,
    fc.record({
      scale: fc.oneof(
        finite(1e-6, 1e6),
        fc.constantFrom(1.5700924586837752e-16, 2.0e-14, 1e-300),
      ),
      normalizedCrps: normalizedValue,
      normalizedAbsoluteError: normalizedValue,
      observationCount: fc.integer({ min: 3, max: 40 }),
    }),
  )
  .map(([outcome, common, normalization]) =>
    makeScore({
      ...outcome,
      ...common,
      ...normalization,
      cutoff: "2026-07-25T15:18:08Z",
    }),
  );

// Scales targetNormalizationScale refuses: no cutoff, fewer than three
// pre-cutoff observations, or three or more with no step dispersion.
const unscaledScore = fc
  .tuple(
    intervalAndOutcome,
    commonFields,
    fc.oneof(
      fc.record({
        observationCount: fc.constant(0),
        cutoff: fc.constant(null),
      }),
      fc.record({
        observationCount: fc.integer({ min: 0, max: 2 }),
        cutoff: fc.constant("2026-07-25T15:18:08Z"),
      }),
      fc.record({
        observationCount: fc.integer({ min: 3, max: 40 }),
        cutoff: fc.constant("2026-07-25T15:18:08Z"),
      }),
    ),
  )
  .map(([outcome, common, normalization]) =>
    makeScore({ ...outcome, ...common, ...normalization, scale: null }),
  );

const anyScore = fc.oneof(ledgerScaledScore, unscaledScore);

// Stored normalized scores the usable-scale gate refuses. The gate demands
// three or more pre-cutoff observations, so a stored scale from fewer is
// refused whatever its size. ledgerScaledScore rides along so that a gate
// which also refuses tiny scales (main's Number.EPSILON bound did, before
// #288) is exercised too.
const gateRefusedScore = fc.oneof(
  ledgerScaledScore,
  fc
    .tuple(
      intervalAndOutcome,
      commonFields,
      fc.record({
        scale: finite(1e-6, 1e6),
        normalizedCrps: normalizedValue,
        normalizedAbsoluteError: normalizedValue,
        observationCount: fc.integer({ min: 0, max: 2 }),
      }),
    )
    .map(([outcome, common, normalization]) =>
      makeScore({
        ...outcome,
        ...common,
        ...normalization,
        cutoff: "2026-07-25T15:18:08Z",
      }),
    ),
);

const RUNS = { numRuns: 3000 };

// ---------------------------------------------------------------------------
// Examples.
// ---------------------------------------------------------------------------

describe("post-resolution review of a score without a usable ledger scale", () => {
  it("does not tag a covered, small-error run as a failure", () => {
    // canada-cpi-annual-rate-september-2026 on 2026-11-07: observed 3.1
    // against point 3 inside [2.5, 3.5], no pre-cutoff ledger history.
    const score = makeScore({
      pointEstimate: 3,
      lower: 2.5,
      upper: 3.5,
      observedValue: 3.1,
      scale: null,
      observationCount: 0,
      cutoff: "2026-10-01T00:00:00Z",
    });

    expect(review(score)).toEqual({
      primaryFailureMode: "not_assessable",
      tags: ["not_assessable"],
      severity: "none",
      explanation:
        "Observed value 3.1 landed inside the 80% interval [2.5, 3.5] (point 3, signed error 0.1); nCRPS unavailable (fewer than three pre-cutoff ledger observations). No raw-unit failure mode fired, and without a usable ledger scale the review cannot grade calibration. Primary review tag: not assessable.",
    });
    // The original classifier called this a low-severity bad baseline.
    expect(legacyReview(score)).toMatchObject({
      tags: ["bad_baseline"],
      severity: "low",
    });
  });

  it("names missing step dispersion when the history has three observations", () => {
    const score = makeScore({
      pointEstimate: 1.78,
      lower: 1.729,
      upper: 1.831,
      observedValue: 1.777,
      scale: null,
      observationCount: 3,
      cutoff: "2026-07-25T15:18:08Z",
    });

    const result = review(score);
    expect(result.tags).toEqual(["not_assessable"]);
    expect(result.explanation).toContain(
      "nCRPS unavailable (the pre-cutoff ledger history has no usable step dispersion)",
    );
    expect(result.explanation).not.toContain("fewer than three");
  });

  it("names a missing cutoff instead of counting observations", () => {
    const score = makeScore({
      pointEstimate: 10,
      lower: 9,
      upper: 11,
      observedValue: 10.2,
      scale: null,
      observationCount: 0,
      cutoff: null,
    });

    expect(review(score).explanation).toContain(
      "nCRPS unavailable (no ledger cutoff to freeze a normalization scale)",
    );
  });

  it("still tags raw-unit failures, unchanged from the original classifier", () => {
    const covered = makeScore({
      pointEstimate: 1,
      lower: 0,
      upper: 10,
      observedValue: 9,
      scale: null,
      observationCount: 1,
      cutoff: "2026-10-01T00:00:00Z",
    });
    const missed = makeScore({
      pointEstimate: 3,
      lower: 2.5,
      upper: 3.5,
      observedValue: 2.1,
      scale: null,
      observationCount: 2,
      cutoff: "2026-10-01T00:00:00Z",
    });

    expect(review(covered)).toMatchObject({
      tags: ["bad_baseline"],
      severity: "low",
    });
    expect(review(missed)).toMatchObject({
      tags: ["interval_too_narrow", "overreacted_to_recent_data"],
      severity: "medium",
    });
    expect(review(covered)).toEqual(legacyReview(covered));
    expect(review(missed)).toEqual(legacyReview(missed));
  });

  it("does not treat a projection pack alone as evidence of a failure", () => {
    const shape = {
      pointEstimate: 3,
      lower: 2.5,
      upper: 3.5,
      scale: null,
      observationCount: 0,
      cutoff: "2026-10-01T00:00:00Z",
      packLabels: ["CBO baseline projection"],
    };

    expect(review(makeScore({ ...shape, observedValue: 3.1 })).tags).toEqual([
      "not_assessable",
    ]);
    expect(review(makeScore({ ...shape, observedValue: 3.9 })).tags).toEqual([
      "interval_too_narrow",
      "ignored_official_projection",
      "bad_baseline",
    ]);
  });

  it("names a stored scale the usable-scale gate refuses", () => {
    // Every version of the gate needs three pre-cutoff observations, so a
    // stored scale from two is refused whatever its size.
    const score = makeScore({
      pointEstimate: 3,
      lower: 2.5,
      upper: 3.5,
      observedValue: 3.1,
      scale: 0.4,
      normalizedCrps: 0.1,
      observationCount: 2,
      cutoff: "2026-10-01T00:00:00Z",
    });

    expect(isNormalizedScoreAggregateEligible(score)).toBe(false);
    expect(review(score)).toEqual({
      primaryFailureMode: "not_assessable",
      tags: ["not_assessable"],
      severity: "none",
      explanation:
        "Observed value 3.1 landed inside the 80% interval [2.5, 3.5] (point 3, signed error 0.1); nCRPS not usable (the ledger scale 0.40 from 2 pre-cutoff ledger observations fails the usable-scale gate). No raw-unit failure mode fired, and without a usable ledger scale the review cannot grade calibration. Primary review tag: not assessable.",
    });
  });

  it("follows the usable-scale gate on a stored residue scale", () => {
    // continued-claims-week-2026-08-01 before #288: equal decimal steps left
    // a 1.57e-16 scale and an nCRPS of 7.08e13, which the classifier read as
    // a high-severity surprising release although main's aggregate gate
    // refused the scale. #288 refuses residue where the scale is computed;
    // a stored score that still carries one gets whatever the gate allows.
    const score = makeScore({
      pointEstimate: 1.78,
      lower: 1.729,
      upper: 1.831,
      observedValue: 1.777,
      scale: 1.5700924586837752e-16,
      normalizedCrps: 70827601099507.89,
      observationCount: 3,
      cutoff: "2026-07-25T15:18:08Z",
    });
    const result = review(score);

    if (isNormalizedScoreAggregateEligible(score)) {
      // A gate that admits the scale admits its evidence too.
      expect(result).toEqual(legacyReview(score));
    } else {
      expect(result).toMatchObject({
        tags: ["not_assessable"],
        severity: "none",
      });
      expect(result.explanation).toContain(
        "nCRPS not usable (the ledger scale 1.6e-16 from 3 pre-cutoff ledger observations fails the usable-scale gate)",
      );
    }
  });
});

// ---------------------------------------------------------------------------
// Properties.
// ---------------------------------------------------------------------------

describe("post-resolution review properties", () => {
  it("gives every usable-scale score the original review, byte for byte", () => {
    fc.assert(
      fc.property(ledgerScaledScore, (score) => {
        fc.pre(isNormalizedScoreAggregateEligible(score));
        expect(review(score)).toEqual(legacyReview(score));
      }),
      RUNS,
    );
  });

  it("tags a score without a usable scale from raw-unit evidence only", () => {
    fc.assert(
      fc.property(anyScore, (score) => {
        fc.pre(!isNormalizedScoreAggregateEligible(score));
        const result = review(score);
        expect(result.tags).toEqual(expectedUnscalableTags(score));
        expect(result.tags).not.toContain("well_calibrated");
        expect(result.tags).not.toContain("surprising_release");
        const evidence = rawEvidence(score);
        expect(result.severity).toBe(
          !evidence.any ? "none" : evidence.missedInterval ? "medium" : "low",
        );
      }),
      RUNS,
    );
  });

  it("never calls an unscalable covered small-error run a failure", () => {
    fc.assert(
      fc.property(anyScore, (score) => {
        fc.pre(!isNormalizedScoreAggregateEligible(score));
        fc.pre(!rawEvidence(score).any);
        const result = review(score);
        expect(result.primaryFailureMode).toBe("not_assessable");
        expect(result.tags).toEqual(["not_assessable"]);
        expect(result.severity).toBe("none");
        expect(result.explanation).toContain("landed inside the 80% interval");
        expect(result.explanation).not.toMatch(/bad baseline/);
      }),
      RUNS,
    );
  });

  it("keeps the original review wherever raw-unit evidence decided it", () => {
    fc.assert(
      fc.property(unscaledScore, (score) => {
        const evidence = rawEvidence(score);
        // The original classifier differs only on its fallback, on an
        // unconditioned projection-pack tag, and on the reason it gives for a
        // missing cutoff (it counts zero observations); with a raw miss, no
        // projection pack, and a cutoff, the two agree exactly.
        fc.pre(evidence.any && !evidence.projectionPack);
        fc.pre(score.normalizationScaleCutoff !== null);
        expect(review(score)).toEqual(legacyReview(score));
      }),
      RUNS,
    );
  });

  it("lets the usable-scale gate, not the stored field, decide the evidence", () => {
    fc.assert(
      fc.property(gateRefusedScore, (score) => {
        fc.pre(!isNormalizedScoreAggregateEligible(score));
        const actual = review(score);
        const nulled = review(withoutNormalization(score));
        expect(actual.tags).toEqual(nulled.tags);
        expect(actual.severity).toBe(nulled.severity);
      }),
      RUNS,
    );
  });

  it("keeps the record structure honest for every score", () => {
    fc.assert(
      fc.property(anyScore, (score) => {
        const result = review(score);
        expect(result.tags.length).toBeGreaterThan(0);
        expect(new Set(result.tags).size).toBe(result.tags.length);
        expect(result.primaryFailureMode).toBe(result.tags[0]);
        for (const verdict of OUTCOME_VERDICTS) {
          if (result.tags.includes(verdict)) {
            expect(result.tags).toEqual([verdict]);
          }
        }
        expect(result.severity === "none").toBe(
          OUTCOME_VERDICTS.has(result.primaryFailureMode),
        );
        if (result.primaryFailureMode === "well_calibrated") {
          expect(isNormalizedScoreAggregateEligible(score)).toBe(true);
          expect(score.interval80Covered).toBe(true);
        }
        if (result.primaryFailureMode === "not_assessable") {
          expect(isNormalizedScoreAggregateEligible(score)).toBe(false);
        }
        if (!isNormalizedScoreAggregateEligible(score)) {
          expect(result.severity).not.toBe("high");
        }
        expect(review(score)).toEqual(result);
      }),
      RUNS,
    );
  });
});

// ---------------------------------------------------------------------------
// The published catalog, built exactly as /forecasts/judges.json builds it.
// ---------------------------------------------------------------------------

describe("post-resolution reviews in the published judge export", () => {
  let scores: ResolvedForecastScore[] = [];
  let reviews: ForecastResolutionJudgeRecord[] = [];

  // The pinned-ledger fetch plus the full judge export (trace and pairwise
  // judges included, as the route builds it) outlasts the 10s hook default
  // on a loaded runner.
  beforeAll(async () => {
    const ledger = await loadPolicyEngineLedger();
    const forecasts = withResolvedOutcomes(getPublishedForecasts(), ledger);
    scores = scoreResolvedForecasts(forecasts, ledger);
    reviews = buildForecastJudgeExport({ forecasts, scores }).postResolution;
  }, 120_000);

  it("keeps every usable-scale review identical to the original classifier", () => {
    const scoreById = new Map(scores.map((score) => [score.scoreId, score]));
    const usable = reviews.filter((record) =>
      isNormalizedScoreAggregateEligible(scoreById.get(record.scoreId)!),
    );
    expect(usable.length).toBeGreaterThan(0);
    for (const record of usable) {
      const score = scoreById.get(record.scoreId)!;
      expect({
        primaryFailureMode: record.primaryFailureMode,
        tags: record.tags,
        severity: record.severity,
        explanation: record.explanation,
      }).toEqual(legacyReview(score));
    }
  });

  it("tags no unscalable run as a failure without raw-unit evidence", () => {
    const scoreById = new Map(scores.map((score) => [score.scoreId, score]));
    const unscalable = reviews.filter(
      (record) =>
        !isNormalizedScoreAggregateEligible(scoreById.get(record.scoreId)!),
    );
    const notAssessable = unscalable.filter(
      (record) => record.primaryFailureMode === "not_assessable",
    );
    // Non-vacuous: the catalog holds unscalable runs of both kinds.
    expect(notAssessable.length).toBeGreaterThan(0);
    expect(notAssessable.length).toBeLessThan(unscalable.length);
    for (const record of unscalable) {
      const score = scoreById.get(record.scoreId)!;
      expect(record.tags).toEqual(expectedUnscalableTags(score));
      expect(record.severity === "none").toBe(
        record.primaryFailureMode === "not_assessable",
      );
    }
  });
});
