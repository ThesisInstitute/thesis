import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  buildScoreId,
  classifyScoreChronology,
  evaluateResolvedForecastRun,
  getResolutionContractViolation,
  loadPolicyEngineLedger,
  scoreResolvedForecastRun,
  scoreResolvedForecasts,
  targetNormalizationScale,
  withResolvedOutcomes,
  type ObservationRecordedLedgerEntry,
  type PolicyEngineLedgerEntry,
} from "@/data/thesis-log";
import { SEEDED_RUN_RECORDED_AT } from "@/data/prediction-specs";
import {
  buildPredictionSpecs,
  buildRecordedPredictionRunRecords,
} from "@/data/prediction-specs";
import {
  buildBrierRewardExport,
  summarizeNormalizedScores,
} from "@/data/brier-lab";
import { buildForecastJudgeExport } from "@/data/forecast-judges";
import { buildStrategyLabReport } from "@/data/strategy-lab";
import { CONDITIONS, type ConditionStatus } from "@/data/conditions";
import {
  FORECAST_CELLS,
  getForecastRunEntries,
  type ForecastCell,
} from "@/data/forecast-cells";
import {
  THESIS_TARGET_LEDGER,
  type TargetRegisteredLedgerEntry,
} from "@/data/ledger-targets";
import {
  buildLedgerPersistenceBaseline,
  ledgerHistoryAtCutoff,
  registeredObservationSeriesIdentity,
  registeredTargetSeriesIdentity,
} from "@/data/time-series-priors";
import { WITNESSED_CUSTODY_ROOTS } from "@/data/witnessed-timeline";

// The two scoring-integrity invariants: a score enters the headline only
// when its run provably predates the observation, and its CRPS denominator
// is a target-level scale no run can influence by widening itself.

describe("chronology gate", () => {
  const observedAt = "2026-07-01T12:30:00Z";

  it("claimed-time-verifies runs recorded strictly before the observation", () => {
    // The claimed-time classifier can never award the headline tier by
    // itself: witness_verified additionally requires publication proof
    // from the witnessed timeline (re-audit N1).
    expect(classifyScoreChronology("2026-06-28T09:00:00Z", observedAt)).toBe(
      "claimed_time_verified",
    );
  });

  it("flags runs recorded at or after the observation as violated", () => {
    expect(classifyScoreChronology(observedAt, observedAt)).toBe("violated");
    expect(classifyScoreChronology("2026-07-02T00:00:00Z", observedAt)).toBe(
      "violated",
    );
  });

  it("treats missing, seeded, or unparseable run times as unverified", () => {
    expect(classifyScoreChronology(undefined, observedAt)).toBe("unverified");
    expect(classifyScoreChronology(SEEDED_RUN_RECORDED_AT, observedAt)).toBe(
      "unverified",
    );
    expect(classifyScoreChronology("not-a-date", observedAt)).toBe(
      "unverified",
    );
    expect(classifyScoreChronology("2026-06-28T09:00:00Z", undefined)).toBe(
      "unverified",
    );
  });

  it("rejects the seeded instant in any equivalent spelling (X4)", () => {
    // SEEDED_RUN_RECORDED_AT is 2026-06-08T00:00:00+02:00 == this UTC form.
    expect(classifyScoreChronology("2026-06-07T22:00:00Z", observedAt)).toBe(
      "unverified",
    );
    expect(
      classifyScoreChronology("2026-06-07T22:00:00.000Z", observedAt),
    ).toBe("unverified");
  });

  it("resolves date-only observations at day granularity (X4)", () => {
    // Strictly earlier UTC date: claimed-time verified.
    expect(classifyScoreChronology("2026-06-28T09:00:00Z", "2026-07-01")).toBe(
      "claimed_time_verified",
    );
    // Same UTC date: sub-day ordering unknowable in either direction.
    expect(classifyScoreChronology("2026-07-01T02:00:00Z", "2026-07-01")).toBe(
      "unverified",
    );
    expect(classifyScoreChronology("2026-07-01T23:59:00Z", "2026-07-01")).toBe(
      "unverified",
    );
    // Strictly later UTC date: violated.
    expect(classifyScoreChronology("2026-07-02T00:01:00Z", "2026-07-01")).toBe(
      "violated",
    );
  });
});

describe("target normalization scale", () => {
  const series = "census.spm.child_poverty_rate";
  const targetContentHash = "a".repeat(64);
  const responseSha256 = "b".repeat(64);
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
  // Any real custody root the public chain witnessed with a complete,
  // headline-eligible inventory before the fixture outcome below. The
  // fixture run carries it so normalization and pairing mechanics are
  // exercised at the witness-verified headline tier.
  const witnessedRootSha256 = Object.entries(WITNESSED_CUSTODY_ROOTS).find(
    ([, entry]) =>
      entry.inventoryStatus === "complete" &&
      entry.headlineEligible &&
      entry.earliestWitnessedAt < "2026-08-01T00:00:00Z",
  )?.[0];
  if (!witnessedRootSha256) {
    throw new Error(
      "expected a witnessed, headline-eligible custody root in the timeline",
    );
  }

  const baseCell: ForecastCell = {
    slug: "test-cell",
    country: "US",
    type: "data",
    title: "Test",
    question: "?",
    unit: "percent",
    pointEstimate: 2,
    ciLow: 1,
    ciHigh: 3,
    confidence: 0.8,
    resolutionDate: "2026-08-01",
    resolutionSource: "Test",
    resolutionRule: "Test",
    dataPointId: "census.spm.child_poverty_rate.2025",
    historicalContext: [],
    drivers: [],
    predictionRun: {
      kind: "recorded-agent-run",
      runAt: "2026-04-11T00:00:00Z",
      agent: "test.agent",
      model: "test-model",
      sourceContext: [],
      custodyRootSha256: witnessedRootSha256,
    },
    reasoning: [{ kind: "forecast", point: 2, ciLow: 1, ciHigh: 3 }],
  };

  function registration(
    period: string,
    dataPointId = `${series}.${period}`,
    registeredSeries = series,
  ): TargetRegisteredLedgerEntry {
    return {
      kind: "target_registered",
      dataPointId,
      observationId: `obs.${dataPointId}`,
      country: "US",
      periodLabel: period,
      unit: "percent",
      resolutionDate:
        period === "2025" ? baseCell.resolutionDate : "2026-12-31",
      resolutionSource: "Test",
      resolutionRule: "Test",
      resolutionPolicy: "first_print",
      sourceKind: "official_release",
      source: "Test",
      note: "fixture",
      registrationState: "published",
      registeredAt: "2026-04-10T00:00:00Z",
      targetContentHash,
      series: registeredSeries,
      period,
      catalogSlug: `fixture-${period}`,
      valueScale: 1,
      sourceBinding: binding,
    };
  }

  const target = registration("2025", baseCell.dataPointId!);

  function observation(
    period: string,
    value: number,
    observedAt: string,
    dataPointId = `${series}.${period}`,
    registeredSeries = series,
  ): ObservationRecordedLedgerEntry {
    return {
      kind: "observation_recorded",
      observationId: `obs.${dataPointId}`,
      dataPointId,
      periodLabel: period,
      unit: "percent",
      value,
      observedAt,
      resolvedAt: observedAt,
      // Normalization history requires ledger acceptance at the cutoff.
      acceptedAtUtc: observedAt,
      acceptedSequence: 1,
      legacyQuarantined: false,
      sourceKind: "official_release",
      source: "Test",
      sourceUrl: "https://example.test/series",
      targetContentHash,
      ledgerRepoSha: "c".repeat(40),
      sourceVintage: observedAt.slice(0, 10),
      retrievedAt: observedAt,
      responseArchive: {
        path: `fixture/${period}.json.gz`,
        sha256: responseSha256,
        bytes: 1,
        gzipSha256: "d".repeat(64),
        gzipBytes: 1,
        contentEncoding: "gzip",
      },
      sourceBindingProjection: {
        series: registeredSeries,
        period,
        releasePolicy: binding.releasePolicy,
        table: binding.table,
        field: binding.field,
        transform: binding.transform,
        unit: "percent",
        responseSha256,
      },
    };
  }

  const history = [
    observation("2022", 10, "2026-02-01T00:00:00Z"),
    observation("2023", 14, "2026-03-01T00:00:00Z"),
    observation("2024", 12, "2026-04-01T00:00:00Z"),
  ];
  const historyRegistrations = ["2022", "2023", "2024"].map((period) =>
    registration(period),
  );
  // Observed AFTER the custody root's external witness so publication
  // proof holds for the fixture score.
  const outcome = observation("2025", 3, "2026-08-01T12:00:00Z");

  it("derives the correct scale from pre-registration ledger dispersion", () => {
    const ledger: PolicyEngineLedgerEntry[] = [
      target,
      ...historyRegistrations,
      ...history,
      registration("2026"),
      observation("2026", 1_000_000, "2026-04-10T00:00:01Z"),
    ];
    const { scale, source, observationCount } = targetNormalizationScale(
      baseCell,
      ledger,
    );
    expect(source).toBe("ledger_dispersion");
    expect(observationCount).toBe(3);
    // Ledger changes 4, -2 -> sample standard deviation sqrt(18).
    expect(scale).toBeCloseTo(Math.sqrt(18), 8);
  });

  it("ignores fabricated forecast history completely", () => {
    const honest = {
      ...baseCell,
      historicalContext: [
        { label: "t-3", value: 10 },
        { label: "t-2", value: 14 },
        { label: "t-1", value: 12 },
      ],
    };
    const fabricated = {
      ...baseCell,
      historicalContext: [
        { label: "t-3", value: -1_000_000 },
        { label: "t-2", value: 0 },
        { label: "t-1", value: 1_000_000 },
      ],
    };
    const ledger: PolicyEngineLedgerEntry[] = [
      target,
      ...historyRegistrations,
      ...history,
    ];
    expect(targetNormalizationScale(fabricated, ledger)).toEqual(
      targetNormalizationScale(honest, ledger),
    );
  });

  it("publishes raw CRPS but excludes an unavailable scale from rewards", () => {
    const ledger: PolicyEngineLedgerEntry[] = [
      target,
      ...historyRegistrations.slice(0, 2),
      ...history.slice(0, 2),
      outcome,
    ];
    const run = getForecastRunEntries(baseCell)[0];
    const score = scoreResolvedForecastRun(baseCell, run, ledger);
    expect(score?.crps).toEqual(expect.any(Number));
    // Young-ledger targets have NO independent scale. Nothing a forecast
    // authors may stand in as denominator (re-audit X2: the frozen
    // primary-width fallback let a wider interval shrink its own
    // normalized error), so the scale is simply unavailable.
    expect(score?.normalizationScaleSource).toBe("unavailable");
    expect(score?.normalizationScale).toBeNull();
    expect(score?.normalizedCrps).toBeNull();
    expect(score?.normalizedAbsoluteError).toBeNull();
    expect(score?.sharpness).toBeNull();

    const specs = buildPredictionSpecs([baseCell]);
    const runs = buildRecordedPredictionRunRecords([baseCell], specs);
    const reward = buildBrierRewardExport({
      forecasts: [baseCell],
      specs,
      runs,
      ledger,
    });
    const primary = reward.rewardRows.find(
      (row) => row.runVariantId === "primary",
    );
    // Raw CRPS publishes; normalized reward does not exist without an
    // independent scale.
    expect(primary?.reward.components.crps).toEqual(expect.any(Number));
    expect(primary?.reward.components.normalizedCrps).toBeNull();
    expect(primary?.reward.value).toBeNull();
    expect(primary?.scoreEligibility).toBe("scored_witness_verified");
    expect(reward.counts.scoredRuns).toBe(0);
    // Primary plus its F9 persistence baseline both carry raw scores, so
    // the scale-free paired comparison still works.
    expect(reward.counts.rawScoredRuns).toBe(2);
    expect(reward.pairedComparison.pairedTargets).toBe(1);
    expect(reward.pairedComparison.crpsRatioGeomean).toEqual(
      expect.any(Number),
    );
  });

  it("excludes floating-point-zero dispersion from normalized aggregates", () => {
    const degenerateHistory = [
      observation("2022", 1.1, "2026-02-01T00:00:00Z"),
      observation("2023", 1.2, "2026-03-01T00:00:00Z"),
      observation("2024", 1.3, "2026-04-01T00:00:00Z"),
    ];
    const degenerateLedger: PolicyEngineLedgerEntry[] = [
      target,
      ...historyRegistrations,
      ...degenerateHistory,
      outcome,
    ];
    const validLedger: PolicyEngineLedgerEntry[] = [
      target,
      ...historyRegistrations,
      ...history,
      outcome,
    ];
    const run = getForecastRunEntries(baseCell)[0];
    const degenerateScore = scoreResolvedForecastRun(
      baseCell,
      run,
      degenerateLedger,
    );
    const validScore = scoreResolvedForecastRun(baseCell, run, validLedger);
    expect(degenerateScore?.crps).toEqual(expect.any(Number));
    expect(degenerateScore?.normalizationScaleSource).toBe("ledger_dispersion");
    expect(degenerateScore?.normalizationScaleObservationCount).toBe(3);
    expect(degenerateScore?.normalizationScale).toBeGreaterThan(0);
    expect(degenerateScore?.normalizationScale).toBeLessThan(Number.EPSILON);
    expect(degenerateScore?.normalizedCrps).toBeGreaterThan(1_000_000);
    expect(degenerateScore?.sharpness).toBeGreaterThan(1_000_000);
    expect(validScore).toBeDefined();

    const summary = summarizeNormalizedScores([validScore!, degenerateScore!]);
    expect(summary.eligibleScores).toEqual([validScore]);
    expect(summary.meanNormalizedCrps).toBe(validScore?.normalizedCrps);
    expect(summary.meanSharpness).toBe(validScore?.sharpness);
    expect(Number.isFinite(summary.meanNormalizedCrps)).toBe(true);
    expect(Number.isFinite(summary.meanSharpness)).toBe(true);
    expect(summary.meanNormalizedCrps).toBeLessThan(1_000_000);
    expect(summary.meanSharpness).toBeLessThan(1_000_000);

    const specs = buildPredictionSpecs([baseCell]);
    const reward = buildBrierRewardExport({
      forecasts: [baseCell],
      specs,
      runs: buildRecordedPredictionRunRecords([baseCell], specs),
      ledger: degenerateLedger,
    });
    const primary = reward.rewardRows.find(
      (row) => row.runVariantId === "primary",
    );
    const agent = reward.leaderboard.find((row) => row.agent === "test.agent");
    expect(primary?.reward.components.normalizedCrps).toBe(
      degenerateScore?.normalizedCrps,
    );
    expect(agent?.unpairedMeanNormalizedCrps).toBeNull();
    // The raw row keeps its stored reward: the degenerate value publishes
    // as-is and only aggregates exclude it.
    expect(primary?.reward.value).toBeLessThan(-1_000_000);
  });

  it("keeps floating-point-zero dispersion out of judge calibration aggregates", () => {
    const degenerateSeries = "census.spm.deep_child_poverty_rate";
    const degenerateDataPointId = `${degenerateSeries}.2025`;
    const degenerateCell: ForecastCell = {
      ...baseCell,
      slug: "test-cell-degenerate",
      dataPointId: degenerateDataPointId,
      historicalContext: [
        { label: "2023", value: 1.2 },
        { label: "2024", value: 1.3 },
      ],
      drivers: ["caseload"],
      // A trace rich enough that the rubric judge scores this run >= 3: the
      // degenerate score must reach the strong band and the
      // high_judge_bad_score candidate pool, where only the aggregate
      // eligibility gate can keep it out.
      reasoning: [
        {
          kind: "text",
          text: "Base rate: the historical baseline and prior come from official ledger data.",
        },
        {
          kind: "tool",
          call: "fetch official series",
          result: "official ledger series; first print resolves on release",
        },
        {
          kind: "tool",
          call: "fetch release calendar",
          result: "release published",
        },
        {
          kind: "text",
          text: "Driver: caseload pressure because momentum; however a surprise offset risk remains uncertain.",
        },
        {
          kind: "text",
          text: "Uncertainty: the 80% interval covers the tail risk.",
        },
        { kind: "forecast", point: 2, ciLow: 1, ciHigh: 3 },
      ],
    };
    const combinedLedger: PolicyEngineLedgerEntry[] = [
      target,
      ...historyRegistrations,
      ...history,
      outcome,
      registration("2025", degenerateDataPointId, degenerateSeries),
      ...["2022", "2023", "2024"].map((period) =>
        registration(period, `${degenerateSeries}.${period}`, degenerateSeries),
      ),
      // Equal decimal steps: a positive sub-epsilon ledger dispersion.
      observation(
        "2022",
        1.1,
        "2026-02-01T00:00:00Z",
        `${degenerateSeries}.2022`,
        degenerateSeries,
      ),
      observation(
        "2023",
        1.2,
        "2026-03-01T00:00:00Z",
        `${degenerateSeries}.2023`,
        degenerateSeries,
      ),
      observation(
        "2024",
        1.3,
        "2026-04-01T00:00:00Z",
        `${degenerateSeries}.2024`,
        degenerateSeries,
      ),
      observation(
        "2025",
        3,
        "2026-08-01T12:00:00Z",
        degenerateDataPointId,
        degenerateSeries,
      ),
    ];

    const scores = scoreResolvedForecasts(
      [baseCell, degenerateCell],
      combinedLedger,
    );
    const validScore = scores.find(
      (score) => score.forecastSlug === baseCell.slug,
    );
    const degenerateScore = scores.find(
      (score) => score.forecastSlug === degenerateCell.slug,
    );
    expect(validScore?.normalizationScale).toBeGreaterThan(Number.EPSILON);
    expect(validScore?.normalizedCrps).toBeLessThan(1);
    expect(degenerateScore?.normalizationScaleSource).toBe("ledger_dispersion");
    expect(degenerateScore?.normalizationScale).toBeGreaterThan(0);
    expect(degenerateScore?.normalizationScale).toBeLessThan(Number.EPSILON);
    expect(degenerateScore?.normalizedCrps).toBeGreaterThan(1_000_000);

    const judgeExport = buildForecastJudgeExport({
      forecasts: [baseCell, degenerateCell],
      scores,
    });
    const calibration = judgeExport.calibration;
    const degenerateJudge = judgeExport.traceQuality.find(
      (judge) => judge.runId === degenerateScore?.runId,
    );
    // Premise pin: the degenerate run really is a strong-band, high-judge
    // run, so the band and disagreement assertions below bite.
    expect(degenerateJudge?.overallScore).toBeGreaterThanOrEqual(3);

    expect(calibration.counts.judgedRuns).toBe(2);
    expect(calibration.counts.scoredJudgedRuns).toBe(1);
    expect(calibration.meanNormalizedCrpsWhenScored).toBe(
      validScore?.normalizedCrps,
    );
    expect(calibration.meanNormalizedCrpsWhenScored).toBeLessThan(1_000_000);
    for (const row of calibration.disagreements) {
      expect(row.runId).not.toBe(degenerateScore?.runId);
      expect(row.normalizedCrps).toBeLessThan(1_000_000);
    }
    const strongBand = calibration.scoreBands.find(
      (band) => band.label === "strong",
    );
    // The degenerate run stays judged and counted in its band; only the
    // normalized mean refuses the unusable denominator.
    expect(strongBand?.judgedRuns).toBe(1);
    expect(strongBand?.scoredRuns).toBe(1);
    expect(strongBand?.meanNormalizedCrps).toBeNull();
    expect(strongBand?.meanAbsoluteError).toEqual(expect.any(Number));
    for (const band of calibration.scoreBands) {
      if (band.meanNormalizedCrps !== null) {
        expect(Number.isFinite(band.meanNormalizedCrps)).toBe(true);
        expect(band.meanNormalizedCrps).toBeLessThan(1_000_000);
      }
    }
  });

  it("keeps floating-point-zero dispersion out of Strategy Lab aggregates", () => {
    const validSeries = "fns.snap.total_payment_error_rate.ak";
    const degenerateSeries = "fns.snap.total_payment_error_rate.wy";
    const snapPeriods = ["fy2022", "fy2023", "fy2024"];
    const validSnapCell: ForecastCell = {
      ...baseCell,
      slug: "snap-payment-error-ak-fy2025",
      title: "Alaska SNAP payment error rate FY2025",
      dataPointId: `${validSeries}.fy2025`,
      pointEstimate: 11.5,
      ciLow: 10.5,
      ciHigh: 12.5,
      historicalContext: [
        { label: "FY 2023", value: 10 },
        { label: "FY 2024", value: 12 },
      ],
      resolvedOutcome: {
        value: 11,
        resolvedAt: "2026-08-01T12:00:00Z",
        source: "Test",
      },
      reasoning: [
        { kind: "forecast", point: 11.5, ciLow: 10.5, ciHigh: 12.5 },
      ],
    };
    const degenerateSnapCell: ForecastCell = {
      ...baseCell,
      slug: "snap-payment-error-wy-fy2025",
      title: "Wyoming SNAP payment error rate FY2025",
      dataPointId: `${degenerateSeries}.fy2025`,
      // The recorded agent run misses badly, so under the degenerate scale
      // its normalized miss vs persistence is a huge positive delta —
      // exactly the pair that would own the top-misses ranking.
      pointEstimate: 5,
      ciLow: 4,
      ciHigh: 6,
      historicalContext: [
        { label: "FY 2023", value: 1.2 },
        { label: "FY 2024", value: 1.3 },
      ],
      resolvedOutcome: {
        value: 1.4,
        resolvedAt: "2026-08-01T12:00:00Z",
        source: "Test",
      },
      reasoning: [{ kind: "forecast", point: 5, ciLow: 4, ciHigh: 6 }],
    };
    const snapLedger: PolicyEngineLedgerEntry[] = [
      registration("fy2025", `${validSeries}.fy2025`, validSeries),
      registration("fy2025", `${degenerateSeries}.fy2025`, degenerateSeries),
      ...snapPeriods.map((period) =>
        registration(period, `${validSeries}.${period}`, validSeries),
      ),
      ...snapPeriods.map((period) =>
        registration(period, `${degenerateSeries}.${period}`, degenerateSeries),
      ),
      observation(
        "fy2022",
        10,
        "2026-02-01T00:00:00Z",
        `${validSeries}.fy2022`,
        validSeries,
      ),
      observation(
        "fy2023",
        14,
        "2026-03-01T00:00:00Z",
        `${validSeries}.fy2023`,
        validSeries,
      ),
      observation(
        "fy2024",
        12,
        "2026-04-01T00:00:00Z",
        `${validSeries}.fy2024`,
        validSeries,
      ),
      // Equal decimal steps: a positive sub-epsilon ledger dispersion.
      observation(
        "fy2022",
        1.1,
        "2026-02-01T00:00:00Z",
        `${degenerateSeries}.fy2022`,
        degenerateSeries,
      ),
      observation(
        "fy2023",
        1.2,
        "2026-03-01T00:00:00Z",
        `${degenerateSeries}.fy2023`,
        degenerateSeries,
      ),
      observation(
        "fy2024",
        1.3,
        "2026-04-01T00:00:00Z",
        `${degenerateSeries}.fy2024`,
        degenerateSeries,
      ),
    ];

    const report = buildStrategyLabReport(
      [validSnapCell, degenerateSnapCell],
      snapLedger,
    );
    const family = report.families.find(
      (candidate) => candidate.familyId === "snap_payment_error_fy2025_panel",
    );
    const degeneratePersistenceRow = report.scoreRows.find(
      (row) =>
        row.forecastSlug === degenerateSnapCell.slug &&
        row.strategyId === "baseline.persistence.last_print",
    );
    const degenerateAgentRow = report.scoreRows.find(
      (row) =>
        row.forecastSlug === degenerateSnapCell.slug &&
        row.strategyId === "agent.brier.primary",
    );
    // Premise pins: both panel members resolve, and the degenerate rows
    // carry a sub-epsilon ledger_dispersion scale with trillion-scale
    // normalized values on the raw row surface, which publishes as-is.
    expect(family?.resolvedTargetCount).toBe(2);
    expect(report.counts.scoredRows).toBe(6);
    expect(degeneratePersistenceRow?.normalizationScaleSource).toBe(
      "ledger_dispersion",
    );
    expect(degeneratePersistenceRow?.normalizationScale).toBeGreaterThan(0);
    expect(degeneratePersistenceRow?.normalizationScale).toBeLessThan(
      Number.EPSILON,
    );
    expect(degeneratePersistenceRow?.normalizedCrps).toBeGreaterThan(
      1_000_000,
    );
    expect(degenerateAgentRow?.normalizedCrps).toBeGreaterThan(1_000_000);
    // The degenerate pair's delta clears the ranking's > 0 threshold by a
    // huge margin — its absence from the top-misses list below is the
    // eligibility gate at work, not the threshold.
    expect(
      (degenerateAgentRow?.normalizedCrps ?? 0) -
        (degeneratePersistenceRow?.normalizedCrps ?? 0),
    ).toBeGreaterThan(1_000_000);

    for (const summary of report.summaries) {
      expect(summary.scoredRows).toBe(2);
      expect(summary.meanNormalizedCrps).toEqual(expect.any(Number));
      expect(summary.meanNormalizedCrps).toBeLessThan(1_000_000);
      expect(summary.meanNormalizedAbsoluteError).toEqual(expect.any(Number));
      expect(summary.meanNormalizedAbsoluteError).toBeLessThan(1_000_000);
      if (summary.meanNormalizedCrpsVsPersistence !== null) {
        expect(Math.abs(summary.meanNormalizedCrpsVsPersistence)).toBeLessThan(
          1_000_000,
        );
      }
    }
    const agentSummary = report.summaries.find(
      (summary) => summary.strategyId === "agent.brier.primary",
    );
    // The raw-unit pairwise mean keeps BOTH pairs: the Wyoming agent miss
    // dominates it, so it stays positive even though the Alaska agent run
    // beats persistence.
    expect(agentSummary?.meanAbsoluteErrorVsPersistence).toBeGreaterThan(1);
    expect(agentSummary?.meanNormalizedCrpsVsPersistence).toEqual(
      expect.any(Number),
    );
    for (const row of family?.largestAgentNcrpsMissesVsPersistence ?? []) {
      expect(row.forecastSlug).not.toBe(degenerateSnapCell.slug);
      expect(row.agentMinusPersistenceNormalizedCrps).toBeLessThan(1_000_000);
    }
  });

  it("ignores contract-bound observations from a foreign suffix series", () => {
    const cleanLedger: PolicyEngineLedgerEntry[] = [target, outcome];
    const foreignSeries = `${series}.foreign`;
    const foreignRows = [
      ["2022", 20, "2026-02-01T00:00:00Z"],
      ["2023", 20, "2026-03-01T00:00:00Z"],
      ["2024", 30, "2026-04-01T00:00:00Z"],
    ] as const;
    const pollutedLedger: PolicyEngineLedgerEntry[] = [
      ...cleanLedger,
      ...foreignRows.flatMap(([period, value, observedAt]) => {
        const dataPointId = `${series}.${period}.first_print.foreign`;
        return [
          registration(period, dataPointId, foreignSeries),
          observation(period, value, observedAt, dataPointId, foreignSeries),
        ];
      }),
    ];

    const cleanBaseline = buildLedgerPersistenceBaseline(baseCell, cleanLedger);
    const pollutedBaseline = buildLedgerPersistenceBaseline(
      baseCell,
      pollutedLedger,
    );
    expect(pollutedBaseline).toEqual(cleanBaseline);
    expect(pollutedBaseline.record).toMatchObject({
      status: "unavailable",
      observationRefs: [],
    });
    expect(pollutedBaseline.comparisonRun).toBeNull();

    const cleanNormalization = targetNormalizationScale(baseCell, cleanLedger);
    const pollutedNormalization = targetNormalizationScale(
      baseCell,
      pollutedLedger,
    );
    expect(pollutedNormalization).toEqual(cleanNormalization);
    expect(pollutedNormalization).toMatchObject({
      scale: null,
      source: "unavailable",
      observationCount: 0,
    });

    const run = getForecastRunEntries(baseCell)[0];
    const cleanScore = scoreResolvedForecastRun(baseCell, run, cleanLedger);
    const pollutedScore = scoreResolvedForecastRun(
      baseCell,
      run,
      pollutedLedger,
    );
    expect(pollutedScore).toEqual(cleanScore);
    expect(pollutedScore?.normalizationScale).toBeNull();
    expect(pollutedScore?.normalizedCrps).toBeNull();
  });
});

describe("authenticated legacy series identities", () => {
  it("ignores a same-id clone whose pinned legacy value was changed", () => {
    const series = "us.dol.initial_claims.sa";
    const targetDataPointId = `${series}.week_2026-07-11`;
    const targetContentHash = "9".repeat(64);
    const target: TargetRegisteredLedgerEntry = {
      kind: "target_registered",
      dataPointId: targetDataPointId,
      observationId: `obs.${targetDataPointId}`,
      country: "US",
      periodLabel: "2026-07-11",
      unit: "thousands",
      resolutionDate: "2026-07-16",
      resolutionSource: "U.S. Department of Labor",
      resolutionRule: "First print",
      resolutionPolicy: "first_print",
      sourceKind: "official_release",
      source: "U.S. Department of Labor",
      note: "fixture",
      registrationState: "published",
      registeredAt: "2026-07-10T00:00:00Z",
      targetContentHash,
      series,
      period: "week_2026-07-11",
      catalogSlug: "fixture-initial-claims",
      valueScale: 1,
      sourceBinding: {
        adapter: "generic-url",
        sourceUrl: "https://www.dol.gov/ui/data.pdf",
        sourceSeriesId: "ICSA",
        field: "value",
        table: "weekly claims",
        transform: { operation: "identity", factor: 1 },
        releasePolicy: "first_print",
        allowedHosts: ["www.dol.gov"],
        expectedReleaseWindow: {
          start: "2026-07-16",
          end: "2026-07-16",
        },
      },
    };
    const forecast: ForecastCell = {
      slug: "fixture-initial-claims",
      country: "US",
      type: "data",
      title: "Initial claims",
      question: "Initial claims?",
      unit: "thousands",
      pointEstimate: 220,
      ciLow: 200,
      ciHigh: 240,
      confidence: 0.8,
      resolutionDate: "2026-07-16",
      resolutionSource: "U.S. Department of Labor",
      resolutionRule: "First print",
      dataPointId: targetDataPointId,
      historicalContext: [],
      drivers: [],
      predictionRun: {
        kind: "recorded-agent-run",
        runAt: "2026-07-10T00:00:00Z",
        agent: "fixture.agent",
        model: "fixture-model",
        sourceContext: [],
      },
      reasoning: [{ kind: "forecast", point: 220, ciLow: 200, ciHigh: 240 }],
    };
    const legacyRows = [
      {
        dataPointId: `${series}.week_2026-06-13`,
        periodLabel: "June 2026",
        value: 226,
        acceptedSequence: 43,
        acceptedCommit: "6c9209434048317c15355f42e019339efbd0d6ea",
        acceptedAtUtc: "2026-06-19T13:18:22Z",
        observedAt: "2026-06-18",
        sourceUrl: "https://www.dol.gov/ui/data.pdf",
      },
      {
        dataPointId: `${series}.week_2026-06-20`,
        periodLabel: "2026-06-20",
        value: 215,
        acceptedSequence: 104,
        acceptedCommit: "b67cbfcb5f08d07b856c3463858c765e6755a6f9",
        acceptedAtUtc: "2026-07-07T17:41:17Z",
        observedAt: "2026-06-25",
        sourceUrl:
          "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=ICSA&vintage_date=2026-06-25",
      },
      {
        dataPointId: `${series}.week_2026-07-04`,
        periodLabel: "2026-07-04",
        value: 215,
        acceptedSequence: 105,
        acceptedCommit: "ed97a5e2fa9036897d9dfdf1bae5c9727791ab87",
        acceptedAtUtc: "2026-07-09T16:15:28Z",
        observedAt: "2026-07-09",
        sourceUrl:
          "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=ICSA&vintage_date=2026-07-09",
      },
    ] as const;
    const legacyRegistrations: TargetRegisteredLedgerEntry[] = legacyRows.map(
      (row) => ({
        kind: "target_registered",
        dataPointId: row.dataPointId,
        observationId: `obs.${row.dataPointId}`,
        country: "US",
        periodLabel: row.periodLabel,
        unit: "thousands",
        resolutionDate: row.observedAt.slice(0, 10),
        resolutionSource: "U.S. Department of Labor",
        resolutionRule: "First print",
        resolutionPolicy: "first_print",
        sourceKind: "official_release",
        source: "U.S. Department of Labor",
        note: "legacy fixture",
      }),
    );
    const legacyObservations: ObservationRecordedLedgerEntry[] = legacyRows.map(
      (row) => ({
        kind: "observation_recorded",
        observationId: `obs.${row.dataPointId}`,
        dataPointId: row.dataPointId,
        periodLabel: row.periodLabel,
        unit: "thousands",
        value: row.value,
        observedAt: row.observedAt,
        resolvedAt: row.observedAt,
        acceptedSequence: row.acceptedSequence,
        acceptedAtUtc: row.acceptedAtUtc,
        acceptedCommit: row.acceptedCommit,
        legacyQuarantined: true,
        sourceKind: "official_release",
        source: "U.S. Department of Labor",
        sourceUrl: row.sourceUrl,
      }),
    );
    const cleanLedger: PolicyEngineLedgerEntry[] = [
      target,
      ...legacyRegistrations,
      ...legacyObservations,
    ];
    const changedClone: ObservationRecordedLedgerEntry = {
      ...legacyObservations[2],
      value: 999,
    };
    const pollutedLedger = [...cleanLedger, changedClone];

    expect(
      registeredObservationSeriesIdentity(changedClone, pollutedLedger),
    ).toBeNull();
    expect(
      ledgerHistoryAtCutoff(forecast, pollutedLedger, target.registeredAt!),
    ).toEqual(
      ledgerHistoryAtCutoff(forecast, cleanLedger, target.registeredAt!),
    );
    expect(buildLedgerPersistenceBaseline(forecast, pollutedLedger)).toEqual(
      buildLedgerPersistenceBaseline(forecast, cleanLedger),
    );
    expect(targetNormalizationScale(forecast, pollutedLedger)).toEqual(
      targetNormalizationScale(forecast, cleanLedger),
    );
  });
});

describe("chronology parser is host-timezone independent (X4 residual)", () => {
  it("compares timezone-less timestamps at day granularity only", () => {
    // Same written day, no offset on the run time: sub-day order is
    // unknowable without trusting the build host's timezone.
    expect(
      classifyScoreChronology(
        "2026-07-01T02:00:00",
        "2026-07-01T12:30:00Z",
      ),
    ).toBe("unverified");
    // Strictly earlier written day still verifies at the claimed tier.
    expect(
      classifyScoreChronology(
        "2026-06-30T23:00:00",
        "2026-07-01T12:30:00Z",
      ),
    ).toBe("claimed_time_verified");
  });

  it("supports date-only run seals at day granularity", () => {
    expect(classifyScoreChronology("2026-06-28", "2026-07-01T00:00:00Z")).toBe(
      "claimed_time_verified",
    );
    expect(classifyScoreChronology("2026-07-01", "2026-07-01T23:00:00Z")).toBe(
      "unverified",
    );
    expect(classifyScoreChronology("2026-07-02", "2026-07-01T23:00:00Z")).toBe(
      "violated",
    );
  });
});

describe("resolution contract gate (N6)", () => {
  const cell: ForecastCell = {
    slug: "contract-cell",
    country: "US",
    type: "data",
    title: "Contract test",
    question: "?",
    unit: "thousands",
    pointEstimate: 220,
    ciLow: 200,
    ciHigh: 240,
    confidence: 0.8,
    resolutionDate: "2026-08-01",
    resolutionSource: "Test",
    resolutionRule: "Test",
    dataPointId: "test.contract.series.2026",
    historicalContext: [],
    drivers: [],
    predictionRun: {
      kind: "recorded-agent-run",
      runAt: "2026-04-11T00:00:00Z",
      agent: "test.agent",
      model: "test-model",
      sourceContext: [],
    },
    reasoning: [{ kind: "forecast", point: 220, ciLow: 200, ciHigh: 240 }],
  };
  const registered: TargetRegisteredLedgerEntry = {
    kind: "target_registered",
    dataPointId: cell.dataPointId!,
    observationId: `obs.${cell.dataPointId}`,
    country: "US",
    periodLabel: "2026",
    unit: "thousands",
    resolutionDate: cell.resolutionDate,
    resolutionSource: "Test",
    resolutionRule: "Test",
    resolutionPolicy: "first_print",
    sourceKind: "official_release",
    source: "Test",
    note: "fixture",
    registeredAt: "2026-04-10T00:00:00Z",
  };
  const fact = (
    overrides: Partial<ObservationRecordedLedgerEntry>,
  ): ObservationRecordedLedgerEntry => ({
    kind: "observation_recorded",
    observationId: `obs.${cell.dataPointId}`,
    dataPointId: cell.dataPointId!,
    periodLabel: "2026",
    unit: "thousands",
    value: 225,
    observedAt: "2026-07-20T12:00:00Z",
    resolvedAt: "2026-07-20T12:00:00Z",
    sourceKind: "official_release",
    source: "Test",
    ...overrides,
  });

  it("refuses to score a fact whose unit contradicts the contract", () => {
    const run = getForecastRunEntries(cell)[0];
    const evaluation = evaluateResolvedForecastRun(cell, run, [
      registered,
      fact({ unit: "millions" as ObservationRecordedLedgerEntry["unit"] }),
    ]);
    expect(evaluation.score).toBeUndefined();
    expect(evaluation.exclusion?.reason).toBe("contract_violation");
    expect(evaluation.exclusion?.detail).toContain("millions");
  });

  it("scores a contract-conforming fact", () => {
    const run = getForecastRunEntries(cell)[0];
    const evaluation = evaluateResolvedForecastRun(cell, run, [
      registered,
      fact({}),
    ]);
    expect(evaluation.score?.crps).toEqual(expect.any(Number));
    expect(evaluation.exclusion).toBeUndefined();
  });

  it("selects the first print by parsed instant, not string order", () => {
    // +05:00 noon is 07:00Z — EARLIER than 08:00Z despite sorting later
    // lexically. The parsed-instant rule must pick it.
    const later = fact({
      observationId: `obs.${cell.dataPointId}.a`,
      value: 300,
      observedAt: "2026-07-20T08:00:00Z",
    });
    const earlier = fact({
      observationId: `obs.${cell.dataPointId}.b`,
      value: 225,
      observedAt: "2026-07-20T12:00:00+05:00",
    });
    const run = getForecastRunEntries(cell)[0];
    const evaluation = evaluateResolvedForecastRun(cell, run, [
      registered,
      later,
      earlier,
    ]);
    expect(evaluation.score?.observedValue).toBe(225);
  });
});

describe("contract-bound resolution (fail closed past the quarantine)", () => {
  const cell: ForecastCell = {
    slug: "bound-cell",
    country: "US",
    type: "data",
    title: "Bound contract test",
    question: "?",
    unit: "thousands",
    pointEstimate: 220,
    ciLow: 200,
    ciHigh: 240,
    confidence: 0.8,
    resolutionDate: "2026-08-01",
    resolutionSource: "Test",
    resolutionRule: "Test",
    dataPointId: "test.bound.series.2026",
    historicalContext: [],
    drivers: [],
    predictionRun: {
      kind: "recorded-agent-run",
      runAt: "2026-04-11T00:00:00Z",
      agent: "test.agent",
      model: "test-model",
      sourceContext: [],
    },
    reasoning: [{ kind: "forecast", point: 220, ciLow: 200, ciHigh: 240 }],
  };
  const binding = {
    adapter: "alfred-fred" as const,
    sourceUrl: "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=TEST",
    sourceSeriesId: "TEST",
    field: "TEST",
    table: "ALFRED graph CSV",
    transform: { operation: "multiply", factor: 0.001 },
    releasePolicy: "advance_vintage" as const,
    allowedHosts: ["alfred.stlouisfed.org"],
    expectedReleaseWindow: { start: "2026-07-15", end: "2026-07-25" },
  };
  const registered: TargetRegisteredLedgerEntry = {
    kind: "target_registered",
    dataPointId: cell.dataPointId!,
    observationId: `obs.${cell.dataPointId}`,
    country: "US",
    periodLabel: "2026",
    unit: "thousands",
    resolutionDate: cell.resolutionDate,
    resolutionSource: "Test",
    resolutionRule: "Test",
    resolutionPolicy: "first_print",
    sourceKind: "official_release",
    source: "Test",
    note: "fixture",
    registrationState: "preregistered",
    registeredAt: "2026-04-10T00:00:00Z",
    targetContentHash: "a".repeat(64),
    series: "test.bound.series",
    period: "2026",
    catalogSlug: cell.slug,
    valueScale: 0.001,
    sourceBinding: binding,
    ledgerPinSha: "b".repeat(40),
    ledgerPinLineCount: 107,
  };
  const responseSha256 = "c".repeat(64);
  const boundFact = (
    overrides: Partial<ObservationRecordedLedgerEntry>,
  ): ObservationRecordedLedgerEntry => ({
    kind: "observation_recorded",
    observationId: `obs.${cell.dataPointId}`,
    dataPointId: cell.dataPointId!,
    periodLabel: "2026",
    unit: "thousands",
    value: 225,
    observedAt: "2026-07-20T12:00:00Z",
    resolvedAt: "2026-07-20T12:00:00Z",
    acceptedSequence: 110,
    acceptedAtUtc: "2026-07-20T13:00:00Z",
    legacyQuarantined: false,
    sourceKind: "official_release",
    source: "Test",
    sourceUrl: "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=TEST",
    targetContentHash: registered.targetContentHash,
    ledgerRepoSha: "d".repeat(40),
    sourceVintage: "2026-07-20",
    retrievedAt: "2026-07-20T12:30:00Z",
    responseArchive: {
      path: "records/resolutions/test/responses/test.csv.gz",
      sha256: responseSha256,
      bytes: 100,
      gzipSha256: "e".repeat(64),
      gzipBytes: 60,
      contentEncoding: "gzip",
    },
    sourceBindingProjection: {
      series: "test.bound.series",
      period: "2026",
      releasePolicy: "advance_vintage",
      table: "ALFRED graph CSV",
      field: "TEST",
      transform: { operation: "multiply", factor: 0.001 },
      unit: "thousands",
      responseSha256,
    },
    ...overrides,
  });
  const run = () => getForecastRunEntries(cell)[0];

  function publishedIdShapeFixture({
    dataPointId,
    series,
    period,
    releasePolicy,
    conditionId,
  }: {
    dataPointId: string;
    series: string;
    period: string;
    releasePolicy: "first_print" | "registered_query_snapshot";
    conditionId?: string;
  }) {
    const condition = conditionId
      ? CONDITIONS.find((entry) => entry.conditionId === conditionId)
      : undefined;
    if (conditionId && !condition) {
      throw new Error(`missing fixture condition ${conditionId}`);
    }
    const slug = `bound-${dataPointId.replace(/[^a-z0-9]+/gi, "-")}`;
    const shapedCell: ForecastCell = {
      ...cell,
      slug,
      type: condition ? "conditional" : "data",
      dataPointId,
      conditionalOn: condition?.matchStrings[0],
    };
    const shapedTarget: TargetRegisteredLedgerEntry = {
      ...registered,
      dataPointId,
      observationId: `obs.${dataPointId}`,
      series,
      period,
      catalogSlug: slug,
      sourceBinding: { ...binding, releasePolicy },
    };
    const shapedFact = boundFact({
      dataPointId,
      observationId: `obs.${dataPointId}`,
      sourceBindingProjection: {
        ...boundFact({}).sourceBindingProjection!,
        series,
        period,
        releasePolicy,
      },
    });
    return {
      cell: shapedCell,
      run: getForecastRunEntries(shapedCell)[0],
      ledger: [shapedTarget, shapedFact] as PolicyEngineLedgerEntry[],
      conditionId,
    };
  }

  it("scores a fully bound post-quarantine observation as contract_bound", () => {
    const evaluation = evaluateResolvedForecastRun(cell, run(), [
      registered,
      boundFact({}),
    ]);
    expect(evaluation.exclusion).toBeUndefined();
    expect(evaluation.score?.contractBinding).toBe("contract_bound");
  });

  it("keeps open and failed registered-query conditional arms excluded", () => {
    const fixture = publishedIdShapeFixture({
      dataPointId:
        "usaspending.dod.prime_award_obligations.2027." +
        "registered_query_snapshot.fy27_ndaa_enacted",
      series: "usaspending.dod.prime_award_obligations",
      period: "2027",
      releasePolicy: "registered_query_snapshot",
      conditionId: "cond.fy27-ndaa-enactment.enacted",
    });

    const open = evaluateResolvedForecastRun(
      fixture.cell,
      fixture.run,
      fixture.ledger,
      new Map<string, ConditionStatus>([[fixture.conditionId!, "open"]]),
    );
    expect(open.score).toBeUndefined();
    expect(open.exclusion).toMatchObject({
      reason: "condition_not_satisfied",
      detail: `${fixture.conditionId} is open`,
    });

    const failed = evaluateResolvedForecastRun(
      fixture.cell,
      fixture.run,
      fixture.ledger,
      new Map<string, ConditionStatus>([[fixture.conditionId!, "failed"]]),
    );
    expect(failed.score).toBeUndefined();
    expect(failed.exclusion).toMatchObject({
      reason: "condition_not_satisfied",
      detail: `${fixture.conditionId} is failed`,
    });
  });

  it("scores the satisfied FY27 NDAA registered-query arm", () => {
    const fixture = publishedIdShapeFixture({
      dataPointId:
        "usaspending.dod.prime_award_obligations.2027." +
        "registered_query_snapshot.fy27_ndaa_enacted",
      series: "usaspending.dod.prime_award_obligations",
      period: "2027",
      releasePolicy: "registered_query_snapshot",
      conditionId: "cond.fy27-ndaa-enactment.enacted",
    });
    const evaluation = evaluateResolvedForecastRun(
      fixture.cell,
      fixture.run,
      fixture.ledger,
      new Map<string, ConditionStatus>([[fixture.conditionId!, "satisfied"]]),
    );

    expect(evaluation.exclusion).toBeUndefined();
    expect(evaluation.score?.contractBinding).toBe("contract_bound");
    expect(evaluation.score?.conditionStatus).toBe("satisfied");
  });

  it("scores an unconditional FY2026 registered-query observation", () => {
    const fixture = publishedIdShapeFixture({
      dataPointId:
        "usaspending.dod.new_prime_awards.fy2026." +
        "registered_query_snapshot",
      series: "usaspending.dod.new_prime_awards",
      period: "FY2026",
      releasePolicy: "registered_query_snapshot",
    });
    const evaluation = evaluateResolvedForecastRun(
      fixture.cell,
      fixture.run,
      fixture.ledger,
    );

    expect(evaluation.exclusion).toBeUndefined();
    expect(evaluation.score?.contractBinding).toBe("contract_bound");
  });

  it("scores an existing first-print conditional-pair observation", () => {
    const fixture = publishedIdShapeFixture({
      dataPointId: "irs.actc.total_claims.2027.first_print.current_law",
      series: "irs.actc.total_claims",
      period: "2027",
      releasePolicy: "first_print",
      conditionId: "cond.s3596-actc-threshold.current-law",
    });
    const evaluation = evaluateResolvedForecastRun(
      fixture.cell,
      fixture.run,
      fixture.ledger,
      new Map<string, ConditionStatus>([[fixture.conditionId!, "satisfied"]]),
    );

    expect(evaluation.exclusion).toBeUndefined();
    expect(evaluation.score?.contractBinding).toBe("contract_bound");
    expect(evaluation.score?.conditionStatus).toBe("satisfied");
  });

  it("derives every published series from its exact registered contract", () => {
    const failures: string[] = [];
    const publishedTargets = THESIS_TARGET_LEDGER.filter(
      (target) => target.registrationState === "published",
    );
    for (const target of publishedTargets) {
      if (
        !target.targetContentHash ||
        !target.series ||
        !target.period ||
        !target.sourceBinding
      ) {
        failures.push(
          `${target.dataPointId}: published registration lacks a complete series contract`,
        );
        continue;
      }
      const responseSha256 = "f".repeat(64);
      const forecast: ForecastCell = {
        ...cell,
        slug: target.catalogSlug ?? `bound-${target.dataPointId}`,
        dataPointId: target.dataPointId,
        unit: target.unit,
      };
      const observation: ObservationRecordedLedgerEntry = {
        kind: "observation_recorded",
        observationId: target.observationId,
        dataPointId: target.dataPointId,
        periodLabel: target.periodLabel,
        unit: target.unit,
        value: 0,
        observedAt: "2030-01-01T00:00:00Z",
        resolvedAt: "2030-01-01T00:00:00Z",
        acceptedSequence: target.ledgerPinLineCount ?? 1,
        acceptedAtUtc: "2030-01-01T00:00:01Z",
        legacyQuarantined: false,
        sourceKind: "official_release",
        source: target.source,
        sourceUrl: target.sourceBinding.sourceUrl,
        targetContentHash: target.targetContentHash,
        ledgerRepoSha: "d".repeat(40),
        sourceVintage: "fixture",
        retrievedAt: "2030-01-01T00:00:00Z",
        responseArchive: {
          path: "records/resolutions/test/responses/test.json.gz",
          sha256: responseSha256,
          bytes: 1,
          gzipSha256: "e".repeat(64),
          gzipBytes: 1,
          contentEncoding: "gzip",
        },
        sourceBindingProjection: {
          series: target.series,
          period: target.period,
          releasePolicy: target.sourceBinding.releasePolicy,
          table: target.sourceBinding.table,
          field: target.sourceBinding.field,
          transform: target.sourceBinding.transform,
          unit: target.unit,
          responseSha256,
        },
      };
      const fixtureLedger: PolicyEngineLedgerEntry[] = [target, observation];
      const violation = getResolutionContractViolation(
        forecast,
        observation,
        fixtureLedger,
      );
      if (violation) failures.push(`${target.dataPointId}: ${violation}`);
      if (
        registeredTargetSeriesIdentity(target.dataPointId, fixtureLedger) !==
        target.series
      ) {
        failures.push(
          `${target.dataPointId}: target series was not registered`,
        );
      }
      if (
        registeredObservationSeriesIdentity(observation, fixtureLedger) !==
        target.series
      ) {
        failures.push(
          `${target.dataPointId}: observation series was not contract-bound`,
        );
      }
      const history = ledgerHistoryAtCutoff(
        forecast,
        fixtureLedger,
        "2030-01-02T00:00:00Z",
      );
      if (
        history.length !== 1 ||
        history[0].observationId !== observation.observationId
      ) {
        failures.push(
          `${target.dataPointId}: exact registered observation was not history-eligible`,
        );
      }
    }
    expect(publishedTargets.length).toBeGreaterThan(0);
    expect(failures).toEqual([]);
  });

  it("accepts an opaque registered id bound to its canonical series", () => {
    // dataPointId is opaque. This early ABS target's descriptive id stem is
    // intentionally not byte-identical to its authoritative contract.series.
    const legacyDataPointId =
      "abs.labour.unemployment_rate.australia.july_2026.first_print";
    const legacyTargetContentHash =
      "cf3a2f76bb15d9f5eb9f5ae19d2e96b55111cf6842a1c8c8412b915ae614a85b";
    const canonicalSeries = "abs.labour.unemployment_rate";
    const legacyCell = { ...cell, dataPointId: legacyDataPointId };
    const legacyTarget: TargetRegisteredLedgerEntry = {
      ...registered,
      dataPointId: legacyDataPointId,
      observationId: `obs.${legacyDataPointId}`,
      targetContentHash: legacyTargetContentHash,
      series: canonicalSeries,
    };
    const legacyFact = boundFact({
      dataPointId: legacyDataPointId,
      observationId: `obs.${legacyDataPointId}`,
      targetContentHash: legacyTargetContentHash,
    });
    legacyFact.sourceBindingProjection = {
      ...legacyFact.sourceBindingProjection!,
      series: canonicalSeries,
    };
    const legacyRun = getForecastRunEntries(legacyCell)[0];
    const evaluation = evaluateResolvedForecastRun(legacyCell, legacyRun, [
      legacyTarget,
      legacyFact,
    ]);
    expect(evaluation.exclusion).toBeUndefined();
    expect(evaluation.score?.contractBinding).toBe("contract_bound");
  });

  it("accepts a novel opaque id when its exact contract binds the series", () => {
    const aliasDataPointId = "test.bound.series.unreviewed_alias.2026";
    const aliasCell = { ...cell, dataPointId: aliasDataPointId };
    const aliasTarget: TargetRegisteredLedgerEntry = {
      ...registered,
      dataPointId: aliasDataPointId,
      observationId: `obs.${aliasDataPointId}`,
    };
    const aliasFact = boundFact({
      dataPointId: aliasDataPointId,
      observationId: `obs.${aliasDataPointId}`,
    });
    const aliasRun = getForecastRunEntries(aliasCell)[0];
    const evaluation = evaluateResolvedForecastRun(aliasCell, aliasRun, [
      aliasTarget,
      aliasFact,
    ]);
    expect(evaluation.exclusion).toBeUndefined();
    expect(evaluation.score?.contractBinding).toBe("contract_bound");
  });

  it("rejects an observation bound to a different target content hash", () => {
    const evaluation = evaluateResolvedForecastRun(cell, run(), [
      registered,
      boundFact({ targetContentHash: "f".repeat(64) }),
    ]);
    expect(evaluation.exclusion?.reason).toBe("contract_violation");
    expect(evaluation.exclusion?.detail).toContain(
      "recorded against target contract",
    );
  });

  it("rejects a projection whose series contradicts the registration", () => {
    // Finding 1: the projection's declared series is checked against the
    // registration, not merely against its own copy.
    const fact = boundFact({});
    fact.sourceBindingProjection = {
      ...fact.sourceBindingProjection!,
      series: "unrelated.other.series",
    };
    const evaluation = evaluateResolvedForecastRun(cell, run(), [
      registered,
      fact,
    ]);
    expect(evaluation.exclusion?.reason).toBe("contract_violation");
    expect(evaluation.exclusion?.detail).toContain("series");
  });

  it("rejects an observation whose opaque id is not the registered id", () => {
    const violation = getResolutionContractViolation(
      cell,
      boundFact({ dataPointId: `${cell.dataPointId}.foreign` }),
      [registered],
    );
    expect(violation).toContain("dataPointId");
    expect(violation).toContain("does not match the registration");
  });

  it("rejects an observation fetched from a non-allowed publisher host", () => {
    const evaluation = evaluateResolvedForecastRun(cell, run(), [
      registered,
      boundFact({ sourceUrl: "https://evil.example.com/data.csv" }),
    ]);
    expect(evaluation.exclusion?.reason).toBe("contract_violation");
    expect(evaluation.exclusion?.detail).toContain("host");
  });

  it("rejects a post-quarantine observation with no contract hash", () => {
    const evaluation = evaluateResolvedForecastRun(cell, run(), [
      registered,
      boundFact({ targetContentHash: undefined }),
    ]);
    expect(evaluation.exclusion?.reason).toBe("contract_violation");
    expect(evaluation.exclusion?.detail).toContain("no target contract hash");
  });

  it("rejects a post-quarantine observation missing the binding projection", () => {
    const evaluation = evaluateResolvedForecastRun(cell, run(), [
      registered,
      boundFact({ sourceBindingProjection: undefined }),
    ]);
    expect(evaluation.exclusion?.reason).toBe("contract_violation");
    expect(evaluation.exclusion?.detail).toContain(
      "source-binding projection",
    );
  });

  it("rejects a projection that contradicts the registered binding", () => {
    const fact = boundFact({});
    fact.sourceBindingProjection = {
      ...fact.sourceBindingProjection!,
      transform: { operation: "multiply", factor: 1000 },
    };
    const evaluation = evaluateResolvedForecastRun(cell, run(), [
      registered,
      fact,
    ]);
    expect(evaluation.exclusion?.reason).toBe("contract_violation");
    expect(evaluation.exclusion?.detail).toContain("transform");
  });

  it("rejects a projection whose digest is not the archived response", () => {
    const fact = boundFact({});
    fact.sourceBindingProjection = {
      ...fact.sourceBindingProjection!,
      responseSha256: "f".repeat(64),
    };
    const evaluation = evaluateResolvedForecastRun(cell, run(), [
      registered,
      fact,
    ]);
    expect(evaluation.exclusion?.reason).toBe("contract_violation");
    expect(evaluation.exclusion?.detail).toContain("digest");
  });

  it("rejects a print that was already inside the pinned ledger state", () => {
    // The target was registered against a pinned 107-row state; a resolving
    // observation at sequence 50 predates the registration — a backfill
    // grading a pre-registered target (N5 by construction).
    const evaluation = evaluateResolvedForecastRun(cell, run(), [
      registered,
      boundFact({ acceptedSequence: 50 }),
    ]);
    expect(evaluation.exclusion?.reason).toBe("contract_violation");
    expect(evaluation.exclusion?.detail).toContain("pinned ledger state");
  });

  it("keeps the backfill gate armed after a target is published (Sol C1)", () => {
    // Publication must not drop the pin: a published target that retains its
    // ledgerPinLineCount still rejects an observation from inside the state.
    const published: TargetRegisteredLedgerEntry = {
      ...registered,
      registrationState: "published",
    };
    const inside = evaluateResolvedForecastRun(cell, run(), [
      published,
      boundFact({ acceptedSequence: 50 }),
    ]);
    expect(inside.exclusion?.reason).toBe("contract_violation");
    expect(inside.exclusion?.detail).toContain("pinned ledger state");
    // A print accepted after the pin still grades.
    const after = evaluateResolvedForecastRun(cell, run(), [
      published,
      boundFact({}),
    ]);
    expect(after.score?.contractBinding).toBe("contract_bound");
  });

  it("keeps grading quarantined legacy rows, flagged legacy_unbound", () => {
    const evaluation = evaluateResolvedForecastRun(cell, run(), [
      registered,
      boundFact({
        legacyQuarantined: true,
        acceptedSequence: 12,
        targetContentHash: undefined,
        sourceBindingProjection: undefined,
        responseArchive: undefined,
        retrievedAt: undefined,
        ledgerRepoSha: undefined,
        sourceVintage: undefined,
      }),
    ]);
    expect(evaluation.exclusion).toBeUndefined();
    expect(evaluation.score?.contractBinding).toBe("legacy_unbound");
  });
});

describe("Supabase projection compatibility (N10)", () => {
  it("emits only sources the migration CHECK admits, with matching null shape", async () => {
    const migration = readFileSync(
      join(__dirname, "../../supabase/migrations/20260709_ledger_normalization_scale.sql"),
      "utf8",
    );
    expect(migration).toContain("'ledger_dispersion'");
    expect(migration).toContain("'unavailable'");
    expect(migration).not.toContain("target_primary_width");

    const ledger = await loadPolicyEngineLedger();
    const prepared = withResolvedOutcomes(FORECAST_CELLS, ledger);
    const scores = scoreResolvedForecasts(prepared, ledger);
    expect(scores.length).toBeGreaterThan(0);
    for (const score of scores) {
      // Mirrors scores_normalization_availability_check exactly: the
      // TypeScript projection must be row-for-row ingestible.
      expect(["ledger_dispersion", "unavailable"]).toContain(
        score.normalizationScaleSource,
      );
      if (score.normalizationScaleSource === "ledger_dispersion") {
        expect(score.normalizationScale).toEqual(expect.any(Number));
        expect(score.normalizedCrps).toEqual(expect.any(Number));
        expect(score.normalizedAbsoluteError).toEqual(expect.any(Number));
        expect(score.sharpness).toEqual(expect.any(Number));
      } else {
        expect(score.normalizationScale).toBeNull();
        expect(score.normalizedCrps).toBeNull();
        expect(score.normalizedAbsoluteError).toBeNull();
        expect(score.sharpness).toBeNull();
      }
    }
  }, 60_000);
});

describe("condition identity in score IDs (N7)", () => {
  it("changes the score ID when the gating premise differs", () => {
    const payload = {
      runId: "run.test",
      resolutionEventId: "resolution_event.test",
      scoringRule: "numeric_cdf_crps_v3_ledger_scale" as const,
      transformVersion: "interval_anchor_v1",
      forecastOutput: { pointEstimate: 1 },
      outcome: { observedValue: 1 },
      normalizationScale: 1,
      normalizationScaleSource: "ledger_dispersion",
      normalizationScaleCutoff: "2026-06-01T00:00:00Z",
      normalizationScaleObservationCount: 3,
      observedAt: "2026-07-01T00:00:00Z",
      chronology: "witness_verified",
      chronologyPolicy: "test",
      contractBinding: "contract_bound",
      contractBindingPolicy: "test",
      conditionId: "cond.a",
      conditionStatus: "satisfied",
    };
    expect(buildScoreId(payload)).not.toBe(
      buildScoreId({ ...payload, conditionId: "cond.b" }),
    );
    expect(buildScoreId(payload)).not.toBe(
      buildScoreId({ ...payload, conditionStatus: "failed" }),
    );
  });
});
