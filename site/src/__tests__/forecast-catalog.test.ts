import { readFileSync } from "node:fs";
import { beforeAll, describe, expect, it } from "vitest";
import {
  EXPIRED_UNFORECAST_REGISTRATIONS,
  EXPIRED_UNFORECAST_SET,
} from "@/data/expired-unforecast-registrations";
import { AGENT_RUN_PREDICTION_SERIES } from "@/data/forecast-examples/agent-runs";
import { CANADA_AUSTRALIA_PREDICTION_SERIES } from "@/data/forecast-examples/canada-australia";
import { EURO_JAPAN_PREDICTION_SERIES } from "@/data/forecast-examples/euro-japan";
import { GLOBAL_NEAR_TERM_PREDICTION_SERIES } from "@/data/forecast-examples/global-near-term";
import { LAUNCH_PREDICTION_SERIES } from "@/data/forecast-examples/launch-cadence";
import {
  BLS_2034_OCCUPATION_EMPLOYMENT_PREDICTION_SERIES,
  CPS_JUNE_2026_OCCUPATION_EMPLOYMENT_PREDICTION_SERIES,
  OEWS_OCCUPATION_EMPLOYMENT_PREDICTION_SERIES,
} from "@/data/forecast-examples/occupation-employment";
import { OEWS_OCCUPATION_WAGE_PREDICTION_SERIES } from "@/data/forecast-examples/occupation-wages";
import { UK_PREDICTION_SERIES } from "@/data/forecast-examples/uk";
import { US_DEFENSE_PREDICTION_SERIES } from "@/data/forecast-examples/us-defense";
import { US_NEAR_TERM_PREDICTION_SERIES } from "@/data/forecast-examples/us-near-term";
import {
  FORECAST_CELLS,
  LIVE_FORECAST_SLUGS,
  getForecastRunEntries,
  getForecastCountry,
  getForecastRuntimeKind,
  getResolutionResult,
  type CountryCode,
  type ForecastCell,
} from "@/data/forecast-cells";
import {
  buildRecordedPredictionRunId,
  buildPredictionSpecExport,
  buildPredictionSpecs,
  buildRecordedPredictionRunRecords,
} from "@/data/prediction-specs";
import {
  buildPredictionPackCatalog,
  getPredictionPackCatalogEntry,
} from "@/data/prediction-packs";
import { buildBrierRewardExport, getBrierEvalSplit } from "@/data/brier-lab";
import { buildForecastJudgeExport } from "@/data/forecast-judges";
import { buildStrategyLabReport } from "@/data/strategy-lab";
import { buildTimeSeriesPriorAdjustmentReport } from "@/data/time-series-priors";
import { sha256Hex } from "@/data/canonical-json";
import {
  assertValidTargetArchitectureProjection,
  buildTargetArchitectureProjection,
  validateTargetArchitectureProjection,
} from "@/data/thesis-target-architecture";
import {
  THESIS_TARGET_LEDGER,
  getLedgerTargetByDataPointId,
  isPreregisteredTargetWithinOrphanGrace,
  type TargetRegisteredLedgerEntry,
} from "@/data/ledger-targets";
import { findUncoveredLedgerObservationSeries } from "@/data/ledger-coverage";
import {
  buildPolicyEngineLedgerExport,
  buildPredictionResolutionEvents,
  buildResolvedPredictionLogEntries,
  buildResolutionQueue,
  buildThesisLog,
  buildThesisLogChunk,
  buildThesisLogData,
  buildThesisLogExport,
  getObservationForId,
  getObservationsForDataPoint,
  isObservationRecordedLedgerEntry,
  isPredictionRecordedLogEntry,
  isTargetRegisteredLedgerEntry,
  loadPolicyEngineLedger,
  scoreResolvedForecasts,
  withResolvedOutcomes,
  type ObservationRecordedLedgerEntry,
  type PolicyEngineLedgerEntry,
  type PredictionRecordedLogEntry,
} from "@/data/thesis-log";

const PRIVATE_SOURCE_PATTERN =
  /granola|\btranscripts?\b|meeting notes?|meeting with max|pasted-text|\.codex\/attachments|codex attachments|private meeting|call notes?|email thread|chat transcript/i;

describe("forecast catalog", () => {
  let policyEngineLedger: PolicyEngineLedgerEntry[] = [];
  let resolvedForecastCells: ForecastCell[] = [];

  beforeAll(async () => {
    policyEngineLedger = await loadPolicyEngineLedger();
    resolvedForecastCells = withResolvedOutcomes(
      FORECAST_CELLS,
      policyEngineLedger,
    );
  });

  it("has unique slugs", () => {
    const slugs = FORECAST_CELLS.map((forecast) => forecast.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it("does not publish private-source provenance", () => {
    const publicCatalogPayload = JSON.stringify({
      forecasts: FORECAST_CELLS,
      thesisLog: buildThesisLogExport(
        resolvedForecastCells,
        policyEngineLedger,
      ),
      targetArchitecture: buildTargetArchitectureProjection(
        resolvedForecastCells,
        policyEngineLedger,
      ),
    });

    expect(publicCatalogPayload).not.toMatch(PRIVATE_SOURCE_PATTERN);
  });

  it("keeps private-source bans in agent prompts and validators", () => {
    const files = [
      "../../../agents/thesis-analyst/system.md",
      "../../../scripts/run_thesis_analyst.py",
      "../../../scripts/spawned_cells_to_ts.py",
    ];

    for (const file of files) {
      const text = readFileSync(new URL(file, import.meta.url), "utf8");
      expect(text).toMatch(/private/i);
      expect(text).toMatch(/transcript/i);
    }
  });

  it("has valid 80% intervals", () => {
    for (const forecast of FORECAST_CELLS) {
      expect(forecast.confidence).toBe(0.8);
      expect(forecast.ciLow).toBeLessThanOrEqual(forecast.pointEstimate);
      expect(forecast.pointEstimate).toBeLessThanOrEqual(forecast.ciHigh);
    }
  });

  it("exports a numeric CDF for every scalar prediction", () => {
    for (const forecast of FORECAST_CELLS) {
      const distribution = forecast.predictionDistribution;
      expect(distribution?.format).toBe("numeric_cdf_v1");
      expect(distribution?.pointCount).toBe(201);
      expect(distribution?.points).toHaveLength(201);
      expect(distribution?.summary.pointEstimate).toBe(forecast.pointEstimate);
      expect(distribution?.summary.median).toBe(forecast.pointEstimate);
      expect(distribution?.summary.interval80.lower).toBe(forecast.ciLow);
      expect(distribution?.summary.interval80.upper).toBe(forecast.ciHigh);
      expect(distribution?.points[0]?.probability).toBe(0);
      expect(distribution?.points.at(-1)?.probability).toBe(1);

      const points = distribution?.points ?? [];
      for (let index = 1; index < points.length; index += 1) {
        expect(points[index].value).toBeGreaterThan(points[index - 1].value);
        expect(points[index].probability).toBeGreaterThanOrEqual(
          points[index - 1].probability,
        );
      }
    }
  });

  it("builds a Thesis Log with one recorded prediction per run", () => {
    const log = buildThesisLog(FORECAST_CELLS, policyEngineLedger);
    const recordedPredictions = log.filter(
      (entry): entry is PredictionRecordedLogEntry =>
        isPredictionRecordedLogEntry(entry),
    );
    const expectedRuns = FORECAST_CELLS.flatMap(getForecastRunEntries);

    expect(recordedPredictions).toHaveLength(expectedRuns.length);
    expect(new Set(recordedPredictions.map((entry) => entry.runId)).size).toBe(
      recordedPredictions.length,
    );

    for (const entry of recordedPredictions) {
      const forecast = FORECAST_CELLS.find(
        (cell) => cell.slug === entry.forecastSlug,
      );
      const run = forecast
        ? getForecastRunEntries(forecast).find(
            (candidate) =>
              buildRecordedPredictionRunId(
                forecast,
                candidate.predictionRun?.runAt,
                candidate.variantId,
              ) === entry.runId,
          )
        : undefined;
      expect(forecast).toBeTruthy();
      expect(run).toBeTruthy();
      expect(entry.runId).toMatch(/^run\./);
      expect(entry.specId).toBe(`spec.${entry.forecastSlug}`);
      expect(entry.type).toBe(forecast?.type);
      expect(entry.title).toBe(forecast?.title);
      expect(entry.question).toBe(forecast?.question);
      expect(entry.country).toBe(forecast?.country ?? "US");
      expect(entry.unit).toBe(forecast?.unit);
      expect(entry.pointEstimate).toBe(run?.pointEstimate);
      expect(entry.interval80.lower).toBe(run?.ciLow);
      expect(entry.interval80.upper).toBe(run?.ciHigh);
      expect(entry.resolutionDate).toBe(forecast?.resolutionDate);
      expect(entry.resolutionSource).toBe(forecast?.resolutionSource);
      expect(entry.resolutionSourceUrl).toBe(forecast?.resolutionSourceUrl);
      expect(entry.resolutionRule).toBe(forecast?.resolutionRule);
      expect(entry.dataPointId).toBe(forecast?.dataPointId);
      expect(entry.distribution.format).toBe("numeric_cdf_v1");
      expect(entry.distribution.pointCount).toBe(201);
      expect(entry.distribution.summary.pointEstimate).toBe(run?.pointEstimate);
      expect(entry.distribution.summary.interval80.lower).toBe(run?.ciLow);
      expect(entry.distribution.summary.interval80.upper).toBe(run?.ciHigh);
      expect(entry.model).toBe(run?.predictionRun?.model);
    }
  });

  it("exports a normalized Thesis Log payload with scores and a resolution queue", () => {
    const logData = buildThesisLogData(
      resolvedForecastCells,
      policyEngineLedger,
    );
    const exportPayload = buildThesisLogExport(
      resolvedForecastCells,
      policyEngineLedger,
    );
    const resolutionQueue = buildResolutionQueue(
      FORECAST_CELLS,
      policyEngineLedger,
    );
    const expectedRunCount = resolvedForecastCells.flatMap(
      getForecastRunEntries,
    ).length;

    expect(exportPayload.schemaVersion).toBe("thesis_log_v3");
    expect(exportPayload.source.name).toBe("Thesis Log");
    expect(exportPayload.source.url).toBe(
      "https://app.thesisinstitute.org/log",
    );
    expect(exportPayload.source.jsonUrl).toBe(
      "https://app.thesisinstitute.org/log.json",
    );
    expect(exportPayload.source.factLedger.name).toBe("PolicyEngine Ledger");
    expect(exportPayload.counts.predictions).toBe(expectedRunCount);
    expect(exportPayload.counts.specs).toBe(FORECAST_CELLS.length);
    expect(exportPayload.counts.runs).toBe(expectedRunCount);
    expect(exportPayload.counts.runs).toBeGreaterThan(
      exportPayload.counts.specs,
    );
    expect(exportPayload.counts.resolutions).toBeGreaterThan(0);
    expect(exportPayload.counts.resolutionLinks).toBe(FORECAST_CELLS.length);
    expect(exportPayload.counts.resolutionEvents).toBe(
      exportPayload.counts.resolutions,
    );
    // The headline scored count admits only witness-verified runs, so it
    // can legitimately be zero until witnessed custody-era cells resolve;
    // legacy scores live in the claimed-time tier.
    expect(exportPayload.counts.scored).toBeGreaterThanOrEqual(0);
    expect(exportPayload.counts.scoredClaimedTimeChronology).toBeGreaterThan(0);
    expect(exportPayload.counts.pendingResolution).toBe(resolutionQueue.length);
    expect(exportPayload.counts.preSubmitReviews).toBe(
      logData.runs.filter((run) => run.preSubmitReview).length,
    );
    expect(exportPayload.counts.judgeTraceEvals).toBe(expectedRunCount);
    expect(exportPayload.counts.judgePairwiseEvals).toBeGreaterThan(0);
    // Judges evaluate every scored run; the headline `scored` count is the
    // witness-verified subset of them.
    expect(exportPayload.counts.judgePostResolutionEvals).toBe(
      exportPayload.counts.scored +
        exportPayload.counts.scoredClaimedTimeChronology +
        exportPayload.counts.scoredUnverifiedChronology +
        exportPayload.counts.scoredViolatedChronology,
    );
    expect(
      logData.scores.filter(
        (score) => score.chronology === "witness_verified",
      ).length,
    ).toBe(exportPayload.counts.scored);
    expect(
      logData.scores.filter(
        (score) => score.chronology === "claimed_time_verified",
      ).length,
    ).toBe(exportPayload.counts.scoredClaimedTimeChronology);
    expect(logData.entries.some(isObservationRecordedLedgerEntry)).toBe(false);
    expect(logData.entries.length).toBeGreaterThan(FORECAST_CELLS.length);
    expect(logData.specs).toHaveLength(exportPayload.counts.specs);
    expect(logData.runs).toHaveLength(exportPayload.counts.runs);
    expect(logData.runs[0].schemaVersion).toBe("thesis_prediction_run_v1");
    expect(exportPayload.resolutionLinks).toHaveLength(
      exportPayload.counts.resolutionLinks,
    );
    expect(exportPayload.resolutionEvents).toHaveLength(
      exportPayload.counts.resolutionEvents,
    );
    expect(exportPayload.resolutionLinks[0].resolutionRef).toMatch(
      /^resolution\./,
    );
    expect(exportPayload.resolutionEvents[0].resolutionEventId).toMatch(
      /^resolution_event\./,
    );
    expect(logData.scores).toHaveLength(
      exportPayload.counts.scored +
        exportPayload.counts.scoredClaimedTimeChronology +
        exportPayload.counts.scoredUnverifiedChronology +
        exportPayload.counts.scoredViolatedChronology,
    );
    expect(logData.scores[0].observedValue).toEqual(expect.any(Number));
    expect(logData.scores[0].interval80.width).toBeGreaterThan(0);
    expect(logData.scores[0].crps).toBeGreaterThanOrEqual(0);
    expect(logData.scores[0].normalizationScaleSource).toMatch(
      /^(ledger_dispersion|target_primary_width|unavailable)$/,
    );
    if (logData.scores[0].normalizationScaleSource === "unavailable") {
      expect(logData.scores[0].normalizedCrps).toBeNull();
      expect(logData.scores[0].normalizedAbsoluteError).toBeNull();
    } else {
      expect(logData.scores[0].normalizedCrps).toBeGreaterThanOrEqual(0);
      expect(logData.scores[0].normalizedAbsoluteError).toBeGreaterThanOrEqual(
        0,
      );
    }
    expect(logData.scores[0].packMode).toBeTruthy();
    expect(exportPayload.judgeResults.schemaVersion).toBe(
      "thesis_forecast_judges_summary_v1",
    );
    expect(exportPayload.judgeResults.policy.rewardEligible).toBe(false);
    expect(exportPayload.judgeResults.calibration.counts.judgedRuns).toBe(
      expectedRunCount,
    );
    expect(
      exportPayload.judgeResults.calibration.counts.postResolutionReviews,
    ).toBe(logData.scores.length);
    expect(exportPayload.judgeResults.fullExportJsonUrl).toBe(
      "https://app.thesisinstitute.org/forecasts/judges.json",
    );
    expect(exportPayload.counts.judgePostResolutionEvals).toBe(
      logData.scores.length,
    );
    expect(exportPayload.resolutionQueue).toHaveLength(
      exportPayload.counts.pendingResolution,
    );

    for (const collection of ["entries", "specs", "runs", "scores"] as const) {
      const manifest = exportPayload.collections[collection];
      const rows: unknown[] = [];
      for (const reference of manifest.chunks) {
        const chunk = buildThesisLogChunk(logData, collection, reference.index);
        expect(reference.count).toBe(chunk.rows.length);
        expect(reference.sha256).toBe(sha256Hex(chunk));
        rows.push(...chunk.rows);
      }
      expect(rows).toEqual(logData[collection]);
      expect(manifest.count).toBe(logData[collection].length);
    }

    for (let index = 1; index < resolutionQueue.length; index += 1) {
      expect(
        resolutionQueue[index].resolutionDate >=
          resolutionQueue[index - 1].resolutionDate,
      ).toBe(true);
    }
  });

  it("exports a Brier reward dataset for agent training and evaluation", () => {
    const specs = buildPredictionSpecs(resolvedForecastCells);
    const runs = buildRecordedPredictionRunRecords(
      resolvedForecastCells,
      specs,
    );
    const exportPayload = buildBrierRewardExport({
      forecasts: resolvedForecastCells,
      specs,
      runs,
      ledger: policyEngineLedger,
    });
    const splitRunCount = Object.values(exportPayload.splits).reduce(
      (total, split) => total + split.runs,
      0,
    );
    const splitScoredCount = Object.values(exportPayload.splits).reduce(
      (total, split) => total + split.scoredRuns,
      0,
    );
    const scoredRow = exportPayload.rewardRows.find(
      (row) => row.reward.value !== null,
    );
    // Run IDs now end in a forecast-output digest, so match on the stable
    // slug/timestamp/variant prefix rather than the full ID.
    const liveRun = exportPayload.rewardRows.find((row) =>
      row.runId.startsWith(
        "run.uk-unemployment-rate-oct-dec-2026.2026-06-16T10-20-43Z.thesis-analyst-live-2026-06-16",
      ),
    );

    expect(exportPayload.schemaVersion).toBe("brier_reward_export_v2");
    expect(exportPayload.mission.objective).toBe("maximize_forecast_accuracy");
    expect(exportPayload.mission.reward).toBe("negative_normalized_crps");
    expect(exportPayload.counts.runs).toBe(runs.length);
    expect(exportPayload.counts.traceJudgedRuns).toBe(runs.length);
    // Judges are auxiliary diagnostics over the published
    // verified-chronology population (claimed-time or better): one
    // post-resolution row per such score. Reward components attach only to
    // witness-verified runs and the deterministic paired baseline, so the
    // judged population is broader than the reward-carrying one (N1).
    expect(exportPayload.counts.postResolutionJudgeRows).toBe(
      exportPayload.rewardRows.filter((row) =>
        [
          "scored_witness_verified",
          "scored_deterministic_baseline",
          "excluded_chronology_claimed_only",
        ].includes(row.scoreEligibility),
      ).length,
    );
    expect(exportPayload.counts.preSubmitReviewedRuns).toBe(
      exportPayload.rewardRows.filter((row) => row.preSubmitReview.reviewed)
        .length,
    );
    expect(exportPayload.rewardRows).toHaveLength(runs.length);
    expect(splitRunCount).toBe(exportPayload.counts.runs);
    expect(splitScoredCount).toBe(exportPayload.counts.scoredRuns);
    expect(exportPayload.noLeakagePolicy.holdoutSplits).toEqual([
      "validation",
      "test",
    ]);
    expect(exportPayload.judgePolicy.rewardEligible).toBe(false);
    expect(exportPayload.judgeResults.policy.rewardEligible).toBe(false);
    if (scoredRow) {
      expect(scoredRow.reward.value).toBeLessThanOrEqual(0);
      expect(scoredRow.reward.components.normalizedCrps).toBeGreaterThanOrEqual(
        0,
      );
      expect(scoredRow.auxiliaryJudges.rewardEligible).toBe(false);
      expect(scoredRow.auxiliaryJudges.traceQualityScore).toEqual(
        expect.any(Number),
      );
      // Which scored run this samples changes with every resolution wave;
      // strategy-suite runs carry completed pre-submit reviews (the 7/25
      // wave surfaced one). Assert the CONTRACT, not a data state: a valid
      // status, with `reviewed` derived exactly from completion.
      expect(["not_requested", "completed", "skipped", "failed"]).toContain(
        scoredRow.preSubmitReview.status,
      );
      expect(scoredRow.preSubmitReview.reviewed).toBe(
        scoredRow.preSubmitReview.status === "completed",
      );
      expect(scoredRow.distributionProvenance).toMatch(
        /^(agent_reported|interval_seeded)$/,
      );
      expect(scoredRow.transformVersion).toMatch(/_v1$/);
    }
    const liveCell = FORECAST_CELLS.find(
      (cell) => cell.slug === "uk-unemployment-rate-oct-dec-2026",
    );
    const liveResolved = policyEngineLedger.some(
      (entry) =>
        entry.kind === "observation_recorded" &&
        entry.dataPointId === liveCell?.dataPointId,
    );
    // Split mirrors resolution state — pinning "unresolved" broke the day
    // a pinned cell resolved.
    expect(liveRun?.split).toBe(
      liveCell ? getBrierEvalSplit(liveCell, liveResolved) : "unresolved",
    );
    expect(liveRun?.provenance.activityArtifactCount).toBe(8);
    expect(exportPayload.leaderboard.length).toBeGreaterThan(0);
  });

  it("builds LLM judge records without replacing proper scoring", () => {
    const scores = scoreResolvedForecasts(
      resolvedForecastCells,
      policyEngineLedger,
    );
    const runs = buildRecordedPredictionRunRecords(
      resolvedForecastCells,
      buildPredictionSpecs(resolvedForecastCells),
    );
    const exportPayload = buildForecastJudgeExport({
      forecasts: resolvedForecastCells,
      scores,
    });
    const traceRunIds = new Set(
      exportPayload.traceQuality.map((judge) => judge.runId),
    );
    const scoreRunIds = new Set(scores.map((score) => score.runId));

    expect(exportPayload.schemaVersion).toBe("thesis_forecast_judges_v1");
    expect(exportPayload.policy.role).toBe("auxiliary_process_eval");
    expect(exportPayload.policy.rewardEligible).toBe(false);
    expect(exportPayload.traceQuality).toHaveLength(runs.length);
    expect(exportPayload.postResolution).toHaveLength(scores.length);
    expect(exportPayload.calibration.counts.judgedRuns).toBe(runs.length);
    expect(exportPayload.calibration.counts.scoredJudgedRuns).toBe(
      scores.filter((score) => score.normalizationScale !== null).length,
    );
    expect(exportPayload.calibration.counts.pairwiseComparisons).toBe(
      exportPayload.pairwise.length,
    );
    expect(exportPayload.calibration.scoreBands.length).toBe(3);

    for (const run of runs) {
      expect(traceRunIds.has(run.runId)).toBe(true);
    }
    for (const score of scores) {
      expect(scoreRunIds.has(score.runId)).toBe(true);
    }
    for (const judge of exportPayload.traceQuality) {
      expect(judge.schemaVersion).toBe("thesis_forecast_trace_judge_v1");
      expect(judge.judge.kind).toBe("llm_judge");
      expect(judge.judge.rewardEligible).toBe(false);
      expect(judge.overallScore).toBeGreaterThanOrEqual(0);
      expect(judge.overallScore).toBeLessThanOrEqual(4);
      expect(judge.dimensions).toHaveLength(7);
      expect(judge.prompt.system).toContain("LLM-as-judge");
    }
    for (const pair of exportPayload.pairwise) {
      expect(pair.schemaVersion).toBe("thesis_forecast_pairwise_judge_v1");
      expect(["left", "right", "tie"]).toContain(pair.winner);
      expect(traceRunIds.has(pair.leftRunId)).toBe(true);
      expect(traceRunIds.has(pair.rightRunId)).toBe(true);
    }
    for (const review of exportPayload.postResolution) {
      expect(review.schemaVersion).toBe("thesis_forecast_resolution_judge_v1");
      expect(scoreRunIds.has(review.runId)).toBe(true);
      expect(review.judge.rewardEligible).toBe(false);
    }
  });

  it("projects current records into the clean target architecture", () => {
    const specs = buildPredictionSpecs(resolvedForecastCells);
    const runs = buildRecordedPredictionRunRecords(
      resolvedForecastCells,
      specs,
    );
    const exportPayload = buildTargetArchitectureProjection(
      resolvedForecastCells,
      policyEngineLedger,
    );
    const strategyVersionIds = new Set(
      exportPayload.strategyVersions.map(
        (strategyVersion) => strategyVersion.strategyVersionId,
      ),
    );
    const strategyById = new Map(
      exportPayload.forecastStrategies.map((strategy) => [
        strategy.strategyId,
        strategy,
      ]),
    );
    const packVersionIds = new Set(
      exportPayload.packVersions.map(
        (packVersion) => packVersion.packVersionId,
      ),
    );
    const artifactRefIds = new Set(
      exportPayload.artifactRefs.map(
        (artifactRef) => artifactRef.artifactRefId,
      ),
    );
    const sourceSeriesSqlKeys = exportPayload.sourceSeries.map((sourceSeries) =>
      [
        sourceSeries.adapterId,
        sourceSeries.agencySeriesId ?? "",
        sourceSeries.sourceUrl,
        sourceSeries.unit,
        sourceSeries.measureKey,
      ].join("::"),
    );
    const timeSeriesPriorRun = exportPayload.forecastRuns.find((run) =>
      run.runId.includes("time-series-prior"),
    );
    const blsProjectionRun = exportPayload.forecastRuns.find((run) =>
      run.runId.includes("bls-published-2024-2034-projection"),
    );
    const oewsCarryForwardRun = exportPayload.forecastRuns.find((run) =>
      run.runId.includes("may-2025-oews-carry-forward"),
    );
    const ensembleRun = exportPayload.forecastRuns.find(
      (run) =>
        run.agentId.includes("ensemble") ||
        run.model?.toLowerCase().includes("ensemble"),
    );

    expect(exportPayload.schemaVersion).toBe(
      "thesis_target_architecture_projection_v1",
    );
    expect(exportPayload.counts.targets).toBe(FORECAST_CELLS.length);
    expect(exportPayload.counts.targetVersions).toBe(FORECAST_CELLS.length);
    expect(exportPayload.counts.forecastRuns).toBe(runs.length);
    expect(exportPayload.counts.forecastDistributionPoints).toBe(
      runs.length * 201,
    );
    expect(exportPayload.counts.runArtifactRefs).toBeGreaterThan(0);
    expect(exportPayload.counts.sourceSeries).toBeGreaterThan(0);
    expect(exportPayload.counts.observations).toBeGreaterThan(0);
    expect(exportPayload.counts.observationVintages).toBe(
      exportPayload.counts.observations,
    );
    expect(
      exportPayload.observations.some((observation) =>
        observation.observationId.startsWith("obs.history."),
      ),
    ).toBe(true);
    expect(
      exportPayload.observations
        .filter((observation) =>
          observation.observationId.startsWith("obs.history."),
        )
        .every((observation) => observation.dataPointId === undefined),
    ).toBe(true);
    expect(exportPayload.counts.resolutionEvents).toBeGreaterThan(0);
    expect(exportPayload.counts.scores).toBeGreaterThan(0);
    expect(exportPayload.counts.baselineCandidates).toBeGreaterThan(0);
    expect(exportPayload.counts.toolCalls).toBeGreaterThan(0);
    expect(exportPayload.counts.reviewRuns).toBeGreaterThan(0);
    expect(exportPayload.counts.judgeRuns).toBeGreaterThan(0);
    expect(new Set(sourceSeriesSqlKeys).size).toBe(sourceSeriesSqlKeys.length);
    expect(
      exportPayload.counts.targetObservationBindings,
    ).toBeGreaterThanOrEqual(exportPayload.counts.targetVersions);
    expect(exportPayload.counts.forecastStrategies).toBeGreaterThanOrEqual(3);
    expect(exportPayload.counts.strategyVersions).toBe(
      exportPayload.counts.forecastStrategies,
    );
    expect(validateTargetArchitectureProjection(exportPayload)).toEqual([]);
    expect(() =>
      assertValidTargetArchitectureProjection(exportPayload),
    ).not.toThrow();
    expect(
      validateTargetArchitectureProjection({
        ...exportPayload,
        forecastRuns: [
          {
            ...exportPayload.forecastRuns[0],
            strategyVersionId: "strategy_version.missing",
          },
          ...exportPayload.forecastRuns.slice(1),
        ],
      }).some((issue) => issue.code === "run_strategy_version_fk"),
    ).toBe(true);
    expect(
      validateTargetArchitectureProjection({
        ...exportPayload,
        sourceSeries: [
          {
            ...exportPayload.sourceSeries[0],
            unit:
              exportPayload.sourceSeries[0].unit === "count"
                ? "percent"
                : "count",
          },
          ...exportPayload.sourceSeries.slice(1),
        ],
      }).some((issue) => issue.code === "binding_source_series_unit_mismatch"),
    ).toBe(true);
    for (const strategyVersion of exportPayload.strategyVersions) {
      const strategy = strategyById.get(strategyVersion.strategyId);
      expect(strategy).toBeTruthy();
      const expectedConstraint = [
        "persistence_baseline",
        "time_series_baseline",
        "official_projection_anchor",
        "formula_nowcast",
      ].includes(strategy?.strategyKind ?? "")
        ? "deterministic"
        : "llm";
      expect(strategyVersion.modelFamilyConstraints).toEqual([
        expectedConstraint,
      ]);
    }
    expect(
      new Set(exportPayload.targets.map((target) => target.targetId)).size,
    ).toBe(exportPayload.targets.length);
    expect(
      new Set(
        exportPayload.targetVersions.map(
          (targetVersion) => targetVersion.targetVersionId,
        ),
      ).size,
    ).toBe(exportPayload.targetVersions.length);
    expect(
      exportPayload.targets.every((target) =>
        target.targetId.startsWith("target."),
      ),
    ).toBe(true);
    expect(
      exportPayload.targetVersions.every((targetVersion) =>
        targetVersion.targetVersionId.startsWith("target_version."),
      ),
    ).toBe(true);
    expect(
      exportPayload.forecastRuns.every((run) =>
        strategyVersionIds.has(run.strategyVersionId),
      ),
    ).toBe(true);
    // Persistence-prior runs attach only when the ledger had ACCEPTED the
    // history rows before the cell's cutoff (N5). Every current legacy cell
    // predates the ledger's first commit, so none can honestly carry one;
    // when a run does exist it must project the persistence strategy.
    if (timeSeriesPriorRun) {
      expect(timeSeriesPriorRun.strategyVersionId).toContain(
        "baseline.persistence.last_print",
      );
    }
    expect(blsProjectionRun?.strategyVersionId).toContain(
      "baseline.official_projection.bls_employment_projections",
    );
    expect(oewsCarryForwardRun?.strategyVersionId).toContain(
      "baseline.official_table.current_print",
    );
    expect(ensembleRun?.strategyVersionId).toContain(
      "agent.brier.meta_aggregator",
    );
    expect(
      exportPayload.runPackVersions.every((runPackVersion) =>
        packVersionIds.has(runPackVersion.packVersionId),
      ),
    ).toBe(true);
    expect(
      exportPayload.runArtifactRefs.every((runArtifactRef) =>
        artifactRefIds.has(runArtifactRef.artifactRefId),
      ),
    ).toBe(true);
    // Persistence candidates exist only for cells whose prior runs survive
    // the acceptance gate (see the time-series-prior note above); the other
    // deterministic baselines keep the candidate table populated.
    expect(exportPayload.baselineCandidates.length).toBeGreaterThan(0);
    expect(
      exportPayload.baselineCandidates.every((candidate) =>
        candidate.modelAdapter.startsWith("baseline."),
      ),
    ).toBe(true);
    expect(
      exportPayload.baselineCandidates.every((candidate) =>
        exportPayload.targetVersions.some(
          (targetVersion) =>
            targetVersion.targetVersionId === candidate.targetVersionId,
        ),
      ),
    ).toBe(true);
    expect(
      exportPayload.baselineCandidates.every(
        (candidate) => candidate.artifactRefId || candidate.sourceSeriesId,
      ),
    ).toBe(true);
    expect(
      exportPayload.baselineCandidates.some((candidate) =>
        candidate.artifactRefId?.startsWith("artifact.generated_baseline."),
      ),
    ).toBe(true);
    expect(
      exportPayload.baselineCandidates.every((candidate) =>
        exportPayload.forecastRuns.some(
          (run) => run.runId === candidate.provenance.forecastRunId,
        ),
      ),
    ).toBe(true);
    expect(
      exportPayload.targetObservationBindings
        .filter((binding) => binding.bindingRole === "history")
        .every((binding) =>
          exportPayload.observations.some(
            (observation) =>
              observation.sourceSeriesId === binding.sourceSeriesId,
          ),
        ),
    ).toBe(true);
    expect(
      exportPayload.toolCalls.every((toolCall) =>
        exportPayload.forecastRuns.some((run) => run.runId === toolCall.runId),
      ),
    ).toBe(true);
    expect(
      exportPayload.reviewRuns.every((reviewRun) =>
        exportPayload.forecastRuns.some((run) => run.runId === reviewRun.runId),
      ),
    ).toBe(true);
    expect(
      exportPayload.judgeRuns.every((judgeRun) => !judgeRun.rewardEligible),
    ).toBe(true);
    expect(exportPayload.judgeRuns.some((judgeRun) => judgeRun.runId)).toBe(
      true,
    );
    expect(
      exportPayload.judgeRuns
        .filter((judgeRun) => judgeRun.batchId?.startsWith("pairwise."))
        .every((judgeRun) => judgeRun.leftRunId && judgeRun.rightRunId),
    ).toBe(true);
    expect(
      exportPayload.artifactRefs.every((artifactRef) =>
        [
          ...exportPayload.runArtifactRefs.map(
            (runArtifactRef) => runArtifactRef.artifactRefId,
          ),
          ...exportPayload.baselineCandidates.flatMap((candidate) =>
            candidate.artifactRefId ? [candidate.artifactRefId] : [],
          ),
        ].includes(artifactRef.artifactRefId),
      ),
    ).toBe(true);
    expect(
      exportPayload.forecastDistributions.every(
        (point) => point.pointIndex >= 0 && point.pointIndex <= 200,
      ),
    ).toBe(true);
    expect(
      exportPayload.reasoningEvents.every(
        (event) => event.redactionStatus === "public_only",
      ),
    ).toBe(true);
  });

  it("scores the Strategy Lab against replayable SNAP baselines", () => {
    const report = buildStrategyLabReport(
      resolvedForecastCells,
      policyEngineLedger,
    );
    const family = report.families.find(
      (candidate) => candidate.familyId === "snap_payment_error_fy2025_panel",
    );
    const persistence = report.summaries.find(
      (summary) => summary.strategyId === "baseline.persistence.last_print",
    );
    const shrinkage = report.summaries.find(
      (summary) => summary.strategyId === "baseline.panel_shrinkage",
    );
    const agent = report.summaries.find(
      (summary) => summary.strategyId === "agent.brier.primary",
    );

    expect(report.schemaVersion).toBe("brier_strategy_lab_v2");
    expect(report.evaluationMode).toBe("retrospective_reconstruction");
    expect(report.counts.strategies).toBe(3);
    expect(family?.targetCount).toBe(53);
    expect(family?.resolvedTargetCount).toBe(53);
    // 53 immutable panel members x however many strategies the registry
    // grows to — never a pinned product.
    expect(report.counts.scoredRows).toBe(53 * report.counts.strategies);
    expect(persistence?.evidenceMode).toBe("historical_replay");
    expect(persistence?.scoredRows).toBe(53);
    expect(shrinkage?.scoredRows).toBe(53);
    expect(agent?.evidenceMode).toBe("forward_only");
    expect(agent?.scoredRows).toBe(53);
    expect(persistence?.meanAbsoluteError).toBeGreaterThan(0);
    expect(agent?.meanAbsoluteErrorVsPersistence).toBeGreaterThan(0);
    expect(
      report.scoreRows.every(
        (row) =>
          (row.normalizationScaleSource === "unavailable") ===
          (row.normalizedCrps === null),
      ),
    ).toBe(true);

    const oneUnresolvedReport = buildStrategyLabReport(
      resolvedForecastCells.map((forecast) =>
        forecast.dataPointId === "fns.snap.total_payment_error_rate.ak.fy2025"
          ? { ...forecast, resolvedOutcome: undefined }
          : forecast,
      ),
      policyEngineLedger,
    );
    const oneUnresolvedFamily = oneUnresolvedReport.families.find(
      (candidate) => candidate.familyId === "snap_payment_error_fy2025_panel",
    );

    expect(oneUnresolvedFamily?.targetCount).toBe(53);
    expect(oneUnresolvedFamily?.resolvedTargetCount).toBe(52);
    expect(oneUnresolvedReport.counts.scoredRows).toBe(
      52 * oneUnresolvedReport.counts.strategies,
    );
  });

  it("generates time-series prior comparisons for agent adjustment audits", () => {
    const report = buildTimeSeriesPriorAdjustmentReport(resolvedForecastCells);
    const available = resolvedForecastCells.filter(
      (forecast) => forecast.persistenceBaseline?.status === "available",
    );

    expect(report.schemaVersion).toBe("time_series_prior_adjustment_report_v1");
    expect(report.counts.forecastsWithPrior).toBe(available.length);
    expect(
      report.counts.adjustedUp +
        report.counts.adjustedDown +
        report.counts.flat,
    ).toBe(report.counts.forecastsWithPrior);
    expect(
      report.rows.every((row) => row.priorModel === "persistence.last_print"),
    ).toBe(true);
  });

  it("exports a facts-only PolicyEngine Ledger payload", () => {
    const exportPayload = buildPolicyEngineLedgerExport(policyEngineLedger);
    const targets = policyEngineLedger.filter(isTargetRegisteredLedgerEntry);
    const observations = policyEngineLedger.filter(
      isObservationRecordedLedgerEntry,
    );

    expect(exportPayload.schemaVersion).toBe("policyengine_ledger_v1");
    expect(exportPayload.source.name).toBe("PolicyEngine Ledger");
    expect(exportPayload.source.url).toBe(
      "https://github.com/PolicyEngine/ledger",
    );
    expect(exportPayload.source.jsonMirrorUrl).toBe(
      "https://app.thesisinstitute.org/ledger.json",
    );
    expect(exportPayload.counts.facts).toBe(policyEngineLedger.length);
    expect(exportPayload.counts.targets).toBe(targets.length);
    expect(exportPayload.counts.observations).toBe(observations.length);
    expect(exportPayload.entries).toHaveLength(policyEngineLedger.length);
    expect(targets.length).toBeGreaterThan(0);
    expect(observations.length).toBeGreaterThan(0);
  });

  it("builds a production prediction spec for every forecast", () => {
    const exportPayload = buildPredictionSpecExport(FORECAST_CELLS);
    const specs = exportPayload.specs;

    expect(exportPayload.schemaVersion).toBe("thesis_prediction_specs_v1");
    expect(exportPayload.counts.specs).toBe(FORECAST_CELLS.length);
    expect(exportPayload.counts.withResolutionTarget).toBe(
      FORECAST_CELLS.filter((forecast) => forecast.dataPointId).length,
    );
    expect(specs).toHaveLength(FORECAST_CELLS.length);
    expect(new Set(specs.map((spec) => spec.predictionId)).size).toBe(
      specs.length,
    );
    expect(new Set(specs.map((spec) => spec.specId)).size).toBe(specs.length);
    expect(new Set(specs.map((spec) => spec.specVersionId)).size).toBe(
      specs.length,
    );

    for (const spec of specs) {
      const forecast = FORECAST_CELLS.find(
        (cell) => cell.slug === spec.predictionId,
      );
      expect(forecast).toBeTruthy();
      expect(spec.schemaVersion).toBe("thesis_prediction_spec_v1");
      expect(spec.specId).toBe(`spec.${spec.predictionId}`);
      expect(spec.specVersionId).toBe(`spec.${spec.predictionId}.v20260609`);
      expect(spec.specHash).toMatch(/^[0-9a-f]{64}$/);
      expect(spec.publishedAt).toBe("2026-06-09T00:00:00+02:00");
      expect(spec.question).toBe(forecast?.question);
      expect(spec.resolution.factLedger).toBe("PolicyEngine Ledger");
      expect(spec.resolution.expectedAt).toBe(forecast?.resolutionDate);
      expect(spec.resolution.targetFactRef).toBe(forecast?.dataPointId);
      expect("factId" in spec.resolution).toBe(false);
      expect(spec.distribution.format).toBe("numeric_cdf_v1");
      expect(spec.distribution.pointCount).toBe(201);
      expect(spec.distribution.elicitation).toBe("full_cdf");
      expect(spec.tools.allowed).toContain("distribution.validate");
      expect(spec.tools.required).toContain("thesis-log.write");
      expect(spec.agent.publicTraceOnly).toBe(true);
      expect(spec.qualityGates).toContain("resolution_source_defined");
    }
  });

  it("builds immutable run records from prediction specs", () => {
    const specs = buildPredictionSpecs(resolvedForecastCells);
    const runs = buildRecordedPredictionRunRecords(
      resolvedForecastCells,
      specs,
    );
    const expectedRunCount = resolvedForecastCells.flatMap(
      getForecastRunEntries,
    ).length;

    expect(runs).toHaveLength(expectedRunCount);
    expect(new Set(runs.map((run) => run.runId)).size).toBe(runs.length);
    expect(runs.length).toBeGreaterThan(resolvedForecastCells.length);

    for (const run of runs) {
      const forecast = resolvedForecastCells.find(
        (cell) => cell.slug === run.predictionId,
      );
      const runEntry = forecast
        ? getForecastRunEntries(forecast).find(
            (candidate) =>
              buildRecordedPredictionRunId(
                forecast,
                candidate.predictionRun?.runAt,
                candidate.variantId,
              ) === run.runId,
          )
        : undefined;
      expect(forecast).toBeTruthy();
      expect(runEntry).toBeTruthy();
      expect(run.schemaVersion).toBe("thesis_prediction_run_v1");
      expect(run.runner.id).toBe("thesis.recorded-agent-runner");
      expect(run.runId).toMatch(/^run\./);
      expect(run.specId).toBe(`spec.${run.predictionId}`);
      expect(run.specVersionId).toBe(`spec.${run.predictionId}.v20260609`);
      expect(run.agentId).toMatch(/^agent\./);
      expect(run.runLabel).toBe(runEntry?.label);
      expect(run.idempotencyKey).toMatch(/^[0-9a-f]{64}$/);
      expect(run.createdAt).toMatch(/^202[56]-/);
      expect(run.modelVersion).toBe(runEntry?.predictionRun?.model);
      expect(run.runner.model).toBe(runEntry?.predictionRun?.model);
      expect(run.promptHash).toMatch(/^[0-9a-f]{64}$/);
      expect(run.toolPolicyHash).toMatch(/^[0-9a-f]{64}$/);
      expect(run.inputBundleHash).toMatch(/^[0-9a-f]{64}$/);
      expect(run.status).toBe("published");
      expect(run.input.specId).toBe(run.specId);
      expect(run.input.specVersionId).toBe(run.specVersionId);
      expect(run.input.targetFactRef).toBe(forecast?.dataPointId);
      expect(run.input.allowedTools).toContain("distribution.validate");
      expect(run.input.packIds).toEqual(
        runEntry?.packSet?.packs.map((pack) => pack.packId) ?? [],
      );
      expect(run.output.distribution.format).toBe("numeric_cdf_v1");
      expect(run.output.distribution.pointCount).toBe(201);
      expect(run.output.pointEstimate).toBe(runEntry?.pointEstimate);
      expect(run.output.publicTrace.length).toBeGreaterThanOrEqual(3);
      expect(run.output.publicTraceMetadata.redactionStatus).toBe(
        "public_only",
      );
      expect(run.output.publicTraceMetadata.traceHash).toMatch(
        /^[0-9a-f]{64}$/,
      );
      for (const toolCall of run.output.toolCalls) {
        expect(toolCall.toolCallId).toMatch(/^run\..+\.tool\.[0-9]+$/);
        expect(toolCall.allowedTool).toBe(true);
        expect(toolCall.requestHash).toMatch(/^[0-9a-f]{64}$/);
        expect(toolCall.responseHash).toMatch(/^[0-9a-f]{64}$/);
      }
      expect(run.qualityGates.some((gate) => gate.status === "failed")).toBe(
        false,
      );
      expect(run.resolution.factLedger).toBe("PolicyEngine Ledger");
      expect(run.resolution.resolutionRef).toBe(
        `resolution.${run.predictionId}`,
      );
      expect(run.resolution.targetFactRef).toBe(forecast?.dataPointId);
    }
  });

  it("supports multiple pack-aware runs for one prediction target", () => {
    const cpi = FORECAST_CELLS.find(
      (forecast) => forecast.slug === "cpi-u-annual-2026",
    );
    expect(cpi).toBeTruthy();

    const runs = getForecastRunEntries(cpi!);
    expect(runs.length).toBeGreaterThanOrEqual(3);
    expect(runs.map((run) => run.variantId)).toContain("control-no-packs");
    expect(runs.map((run) => run.variantId)).toContain("with-cpi-packs");

    const control = runs.find((run) => run.variantId === "control-no-packs");
    const packed = runs.find((run) => run.variantId === "with-cpi-packs");
    expect(control?.packSet?.mode).toBe("none");
    expect(control?.packSet?.packs).toHaveLength(0);
    expect(packed?.packSet?.mode).toBe("with_packs");
    expect(packed?.packSet?.packs.map((pack) => pack.packId)).toEqual([
      "base-rate-first",
      "cpi-component-decomposition",
      "tariff-pass-through",
    ]);

    const specs = buildPredictionSpecs([cpi!]);
    const records = buildRecordedPredictionRunRecords([cpi!], specs);
    expect(new Set(records.map((run) => run.specId)).size).toBe(1);
    expect(records).toHaveLength(runs.length);
    expect(records.some((run) => run.packSet?.mode === "none")).toBe(true);
    expect(records.some((run) => run.packSet?.mode === "with_packs")).toBe(
      true,
    );
  });

  it("builds pack catalog pages from recorded forecast runs", () => {
    const catalog = buildPredictionPackCatalog(FORECAST_CELLS);
    expect(catalog.map((pack) => pack.packId)).toEqual(
      expect.arrayContaining([
        "asec-income-nowcast",
        "asec-release-calibration",
        "base-rate-first",
        "bls-employment-projections-baseline",
        "consumer-spending-nowcast",
        "cash-income-bridge",
        "cpi-component-decomposition",
        "energy-price-nowcast",
        "housing-activity-nowcast",
        "labor-market-momentum",
        "panel-persistence-shrinkage",
        "pce-cpi-bridge",
        "release-vintage-calibration",
        "tariff-pass-through",
      ]),
    );

    const tariff = getPredictionPackCatalogEntry(
      "tariff-pass-through",
      FORECAST_CELLS,
    );
    expect(tariff).toBeTruthy();
    expect(tariff?.latestVersion).toBe("0.1.0");
    expect(tariff?.kind).toBe("calibration");
    expect(tariff?.detail?.qualityChecks.length).toBeGreaterThan(0);
    expect(tariff?.targetCount).toBe(3);
    expect(tariff?.runCount).toBe(4);
    expect(tariff?.agents).toEqual(["brier-1.packed"]);
    expect(tariff?.usage.map((usage) => usage.forecastSlug)).toEqual(
      expect.arrayContaining([
        "cpi-u-annual-2026",
        "us-cpi-u-mom-june-2026",
        "us-core-cpi-mom-june-2026",
      ]),
    );
    expect(tariff?.usage[0].deltaVsNoPack).toBeCloseTo(0.1);
    expect(tariff?.usage[1].deltaVsNoPack).toBeCloseTo(0.2);

    const asecRelease = getPredictionPackCatalogEntry(
      "asec-release-calibration",
      FORECAST_CELLS,
    );
    expect(asecRelease?.targetCount).toBe(2);
    expect(asecRelease?.runCount).toBe(2);
    expect(asecRelease?.usage.map((usage) => usage.forecastSlug)).toEqual([
      "official-poverty-rate-2025",
      "median-household-income-2025",
    ]);

    const labor = getPredictionPackCatalogEntry(
      "labor-market-momentum",
      FORECAST_CELLS,
    );
    expect(labor?.targetCount).toBe(8);
    expect(labor?.runCount).toBe(8);
    expect(labor?.detail?.inputs).toContain("Initial claims and JOLTS signals");
    expect(labor?.usage.map((usage) => usage.forecastSlug)).toEqual([
      "nonfarm-payrolls-june-2026",
      "unemployment-rate-june-2026",
      "initial-claims-week-2026-06-13",
      "jolts-openings-may-2026",
      "australia-employment-change-may-2026",
      "australia-unemployment-rate-may-2026",
      "initial-claims-week-2026-06-20",
      "us-wages-and-salaries-may-2026",
    ]);

    const spending = getPredictionPackCatalogEntry(
      "consumer-spending-nowcast",
      FORECAST_CELLS,
    );
    expect(spending?.targetCount).toBeGreaterThanOrEqual(1);
    expect(spending?.runCount).toBeGreaterThanOrEqual(1);
    expect(
      spending?.usage.some(
        (row) => row.forecastSlug === "retail-sales-mom-may-2026",
      ),
    ).toBe(true);

    const housing = getPredictionPackCatalogEntry(
      "housing-activity-nowcast",
      FORECAST_CELLS,
    );
    expect(housing?.targetCount).toBe(1);
    expect(housing?.runCount).toBe(1);
    expect(housing?.usage[0].forecastSlug).toBe("housing-starts-may-2026");

    const blsProjection = getPredictionPackCatalogEntry(
      "bls-employment-projections-baseline",
      FORECAST_CELLS,
    );
    expect(blsProjection?.targetCount).toBe(12);
    expect(blsProjection?.runCount).toBe(12);
    expect(blsProjection?.kind).toBe("data");
    expect(blsProjection?.agents).toEqual([
      "brier-occupation-automation-scenarios",
      "brier-occupation-projection",
    ]);
    expect(blsProjection?.detail?.inputs).toContain(
      "BLS Employment Projections Table 1.2 occupational projections and worker characteristics",
    );
    expect(blsProjection?.usage.map((usage) => usage.forecastSlug)).toEqual(
      expect.arrayContaining([
        "oews-business-financial-employment-may-2026",
        "oews-computer-math-employment-may-2026",
        "oews-healthcare-support-employment-may-2026",
        "oews-office-admin-employment-may-2026",
        "oews-production-employment-may-2026",
        "oews-transport-material-moving-employment-may-2026",
        "bls-business-financial-employment-2034",
        "bls-computer-math-employment-2034",
        "bls-healthcare-support-employment-2034",
        "bls-office-admin-employment-2034",
        "bls-production-employment-2034",
        "bls-transport-material-moving-employment-2034",
      ]),
    );
    expect(
      blsProjection?.usage.every((usage) => usage.deltaVsNoPack !== undefined),
    ).toBe(true);

    const panelPersistence = getPredictionPackCatalogEntry(
      "panel-persistence-shrinkage",
      FORECAST_CELLS,
    );
    expect(panelPersistence).toBeTruthy();
    expect(panelPersistence?.latestVersion).toBe("0.1.0");
    expect(panelPersistence?.kind).toBe("method");
    expect(panelPersistence?.targetCount).toBe(0);
    expect(panelPersistence?.runCount).toBe(0);
    expect(panelPersistence?.agents).toEqual([]);
    expect(panelPersistence?.detail?.qualityChecks).toContain(
      "The trace reports the persistence benchmark and the agent's delta from it.",
    );
  });

  it("defines the clean target-architecture Supabase schema", () => {
    const sql = readFileSync(
      `${process.cwd()}/supabase/migrations/20260629_thesis_target_architecture.sql`,
      "utf8",
    );
    const tableNames = [
      "artifact_refs",
      "targets",
      "target_versions",
      "source_series",
      "observations",
      "observation_vintages",
      "target_observation_bindings",
      "baseline_candidates",
      "forecast_strategies",
      "strategy_versions",
      "packs",
      "pack_versions",
      "forecast_runs",
      "run_artifact_refs",
      "run_pack_versions",
      "forecast_distributions",
      "reasoning_events",
      "review_runs",
      "judge_runs",
      "tool_calls",
      "resolution_events",
      "scores",
      "audit_events",
    ];

    for (const tableName of tableNames) {
      expect(sql).toContain(`create table if not exists ${tableName}`);
      expect(sql).toContain(
        `alter table ${tableName} enable row level security`,
      );
      expect(sql).toContain(`create trigger ${tableName}_append_only`);
      expect(sql).toContain(`create policy ${tableName}_public_read`);
    }

    expect(sql).toContain("target_id text primary key");
    expect(sql).toContain("data_point_id text not null unique");
    expect(sql).toContain("target_version_id text primary key");
    expect(sql).toContain("resolver_kind text not null check");
    expect(sql).toContain("resolution_policy text not null check");
    expect(sql).toContain(
      "cdf_point_count integer not null default 201 check (cdf_point_count = 201)",
    );
    expect(sql).toContain("source_series_id text primary key");
    expect(sql).toContain("agency_series_id text not null default ''");
    expect(sql).toContain("measure_key text not null");
    expect(sql).toContain(
      "unique (adapter_id, agency_series_id, source_url, unit, measure_key)",
    );
    expect(sql).toContain("observation_id text primary key");
    expect(sql).toContain("vintage_id text primary key");
    expect(sql).toContain(
      "check (source_series_id is not null or observation_id is not null)",
    );
    expect(sql).toContain(
      "source_series_id text references source_series (source_series_id)",
    );
    expect(sql).toContain("provenance jsonb not null default");
    expect(sql).toContain(
      "check (artifact_ref_id is not null or source_series_id is not null)",
    );
    expect(sql).toContain("strategy_version_id text primary key");
    expect(sql).toContain("pack_version_id text primary key");
    expect(sql).toContain(
      "unique (target_version_id, strategy_version_id, agent_id, idempotency_key)",
    );
    expect(sql).toContain("primary key (run_id, point_index)");
    expect(sql).toContain(
      "point_index integer not null check (point_index between 0 and 200)",
    );
    expect(sql).toContain(
      "reward_eligible boolean not null default false check (reward_eligible = false)",
    );
    expect(sql).toContain("left_run_id text references forecast_runs (run_id)");
    expect(sql).toContain(
      "right_run_id text references forecast_runs (run_id)",
    );
    expect(sql).toContain("tool_call_id text primary key");
    expect(sql).toContain("unique (run_id, sequence_index)");
    expect(sql).toContain("resolution_event_id text primary key");
    expect(sql).toContain(
      "vintage_id text references observation_vintages (vintage_id)",
    );
    expect(sql).toContain("score_id text primary key");
    expect(sql).toContain("normalized_crps numeric");
    expect(sql).toContain("event_hash text not null unique");
    expect(sql).toContain(
      "create or replace function thesis_record_insert_audit_event()",
    );
    expect(sql).toContain("artifact_refs_public_read on artifact_refs");
    expect(sql).toContain(
      "drop trigger if exists forecast_runs_append_only on forecast_runs",
    );
    expect(sql).toContain(
      "drop trigger if exists forecast_runs_insert_audit on forecast_runs",
    );
    expect(sql).toContain(
      "drop policy if exists forecast_runs_public_read on forecast_runs",
    );
    expect(sql).toContain("public_visibility = 'public'");
    expect(sql).toContain("observation_vintages_public_read");
    expect(sql).toContain("baseline_candidates_public_read");
    expect(sql).toContain("run_artifact_refs_public_read");
    expect(sql).toContain("reasoning_events_public_read on reasoning_events");
    expect(sql).toContain("redaction_status = 'public_only'");
    expect(sql).toContain("review_runs_public_read on review_runs");
    expect(sql).toContain("drop policy if exists tool_calls_public_read");
    expect(sql).toContain("resolution_events_public_read on resolution_events");
    expect(sql).toContain("scores_public_read on scores");
    expect(sql).toContain("audit_events_public_read on audit_events");
    expect(sql).toContain("request_artifact_ref_id is null");
    expect(sql).toContain("response_artifact_ref_id is null");
    expect(sql).toContain(
      "perform pg_advisory_xact_lock(hashtext('thesis.audit_events')::bigint)",
    );
    expect(sql).toContain("forecast_runs_insert_audit");
    expect(sql).toContain("forecast_distributions_insert_audit");
    expect(sql).toContain("tool_calls_insert_audit");
    expect(sql).toContain("resolution_events_insert_audit");
    expect(sql).toContain("scores_insert_audit");
    expect(sql).not.toContain("prediction_specs");
    expect(sql).not.toContain("spec_versions");
    expect(sql).not.toContain("prediction_runs");
    expect(sql).not.toContain("cdf_points");
    expect(sql).not.toContain("public_traces");
    expect(sql).not.toContain("resolution_links");
    expect(sql).not.toContain("legacy_spec_id");
    expect(sql).not.toContain("legacy_prediction");
  });

  it("has enough public context to stand alone", () => {
    for (const forecast of FORECAST_CELLS) {
      expect(forecast.question.length).toBeGreaterThan(40);
      expect(forecast.resolutionRule.length).toBeGreaterThan(60);
      expect(forecast.drivers.length).toBeGreaterThanOrEqual(3);
      expect(forecast.reasoning.length).toBeGreaterThanOrEqual(5);
    }
  });

  it("uses prediction language in user-facing forecast labels", () => {
    for (const forecast of FORECAST_CELLS) {
      expect(forecast.title).not.toMatch(/\bmarkets?\b/i);
      expect(forecast.question).not.toMatch(/\bmarkets?\b/i);
    }
  });

  it("only marks known forecast cells as live API paths", () => {
    const slugs = new Set(FORECAST_CELLS.map((forecast) => forecast.slug));
    for (const slug of LIVE_FORECAST_SLUGS) {
      expect(slugs.has(slug)).toBe(true);
    }
  });

  it("uses public data point terminology for government data forecasts", () => {
    for (const forecast of FORECAST_CELLS) {
      if (forecast.type === "data") {
        expect(forecast.dataPointId).toBeTruthy();
      }
    }
  });

  it("registers every forecast data point in the ledger before spec generation", () => {
    const targetDataPointIds = new Set(
      THESIS_TARGET_LEDGER.map((target) => target.dataPointId),
    );
    const forecastDataPointIds = FORECAST_CELLS.flatMap((forecast) =>
      forecast.dataPointId ? [forecast.dataPointId] : [],
    );

    // Registration-first means every forecast's target must already be in
    // the ledger. The reverse direction — a registered target with no
    // forecast yet — is legal within the preregistration orphan grace and
    // is asserted (with that grace) by the next test, so no count equality
    // here: a wave that publishes only part of the day's docket must not
    // fail the publish gate.
    expect(new Set(forecastDataPointIds).size).toBeLessThanOrEqual(
      targetDataPointIds.size,
    );
    for (const dataPointId of forecastDataPointIds) {
      expect(targetDataPointIds.has(dataPointId)).toBe(true);
    }
  });

  const describeTarget = (target: TargetRegisteredLedgerEntry): string => {
    const window = target.sourceBinding?.expectedReleaseWindow;
    const registered = (target.registeredAt ?? "?").slice(0, 10);
    const opens = window?.start ?? "(no window recorded)";
    const closes = window?.end ?? "(no window recorded)";
    const alreadyOpen = Boolean(window?.start && registered > window.start);
    return [
      `  ${target.dataPointId}`,
      `      slug         ${target.catalogSlug}`,
      `      registered   ${registered}`,
      `      window       ${opens} -> ${closes}` +
        (alreadyOpen
          ? "   <-- ALREADY OPEN at registration; never forecastable"
          : ""),
    ].join("\n");
  };

  const failureReport = (targets: TargetRegisteredLedgerEntry[]): string =>
    [
      "",
      `${targets.length} registered ledger target(s) have no forecast and are out of grace.`,
      "",
      "Every registered target must reach exactly one of two terminal states:",
      "  1. a forecast cell carrying its dataPointId, or",
      "  2. an entry in site/src/data/expired-unforecast-registrations.ts",
      "",
      "A target lands here when its analyst run never published -- usually a",
      "publish leg that died after `generate` had already succeeded -- and it",
      "is now past the point where forecasting it would be honest.",
      "",
      "TO CLEAR THIS:",
      "  - if the release window has NOT opened, publish the missing forecast",
      "    (the awaiting-forecast lane exists to do this);",
      "  - if it HAS opened, the print is public and no forecast can be honest,",
      "    so add the id to expired-unforecast-registrations.ts with a comment",
      "    saying why it was never forecast.",
      "",
      "Do NOT relax this assertion. It is the preregistration integrity",
      "guarantee: it is the only thing preventing a registration from being",
      "quietly abandoned when its forecast fails to publish.",
      "",
      ...targets.map(describeTarget),
      "",
    ].join("\n");

  it("forecasts every registered ledger target", () => {
    const forecastDataPointIds = new Set(
      FORECAST_CELLS.flatMap((forecast) =>
        forecast.dataPointId ? [forecast.dataPointId] : [],
      ),
    );
    const missingForecastTargets = THESIS_TARGET_LEDGER.filter(
      (target) =>
        !forecastDataPointIds.has(target.dataPointId) &&
        !isPreregisteredTargetWithinOrphanGrace(target) &&
        !EXPIRED_UNFORECAST_SET.has(target.dataPointId),
    );

    // Raw objects here dump ~25 keys apiece and say nothing about which
    // invariant broke or how to clear it, which is how this failure came to
    // read as an unexplained outage on 2026-07-31. Compare ids and put the
    // whole diagnosis in the message instead.
    expect(
      missingForecastTargets.map((target) => target.dataPointId),
      failureReport(missingForecastTargets),
    ).toEqual([]);
  });

  it("keeps the expired-unforecast list exact", () => {
    // The list is a terminal record, not a dumping ground: every entry
    // must name a real preregistered target that is genuinely unforecast
    // and out of grace, and an id that gains a forecast (or leaves the
    // ledger) must be removed. Silent growth is impossible because
    // additions are reviewed commits gated by this test.
    const forecastDataPointIds = new Set(
      FORECAST_CELLS.flatMap((forecast) =>
        forecast.dataPointId ? [forecast.dataPointId] : [],
      ),
    );
    const targetsById = new Map(
      THESIS_TARGET_LEDGER.map((target) => [target.dataPointId, target]),
    );
    for (const dataPointId of EXPIRED_UNFORECAST_REGISTRATIONS) {
      const target = targetsById.get(dataPointId);
      expect(
        target,
        `${dataPointId} is listed as expired-unforecast but is not a ` +
          "registered ledger target at all. Either it was never registered, " +
          "or its id is misspelled, or the registration left the ledger. " +
          "Remove it from expired-unforecast-registrations.ts.",
      ).toBeDefined();
      expect(
        forecastDataPointIds.has(dataPointId),
        `${dataPointId} now HAS a forecast, so it is no longer expired ` +
          "unforecast. Delete it from expired-unforecast-registrations.ts -- " +
          "the list is a record of registrations that ended without a " +
          "forecast, and leaving a forecast id on it misreports the record.",
      ).toBe(false);
      expect(
        isPreregisteredTargetWithinOrphanGrace(target!),
        `${dataPointId} is still awaiting its forecast (its release window ` +
          `opens ${target?.sourceBinding?.expectedReleaseWindow?.start ?? "?"}` +
          "), so it is too early to call it expired. Either forecast it, or " +
          "wait until the window opens before listing it. Expiring a target " +
          "that is still forecastable throws away a usable registration.",
      ).toBe(false);
    }
  });

  it("covers every observed ledger series with an exact or derived forecast family", () => {
    const observations = policyEngineLedger.filter(
      (entry): entry is ObservationRecordedLedgerEntry =>
        isObservationRecordedLedgerEntry(entry),
    );
    const uncoveredObservations = findUncoveredLedgerObservationSeries(
      observations,
      FORECAST_CELLS,
    );

    expect(uncoveredObservations).toEqual([]);
  });

  it("forecasts national SNAP component error rates with model traces", () => {
    const componentForecasts = [
      {
        slug: "snap-overpayment-error-rate-fy2026",
        dataPointId: "fns.snap.overpayment_payment_error_rate.us.fy2026",
      },
      {
        slug: "snap-underpayment-error-rate-fy2026",
        dataPointId: "fns.snap.underpayment_payment_error_rate.us.fy2026",
      },
    ];

    for (const expected of componentForecasts) {
      const forecast = FORECAST_CELLS.find(
        (cell) => cell.slug === expected.slug,
      );

      expect(forecast?.dataPointId).toBe(expected.dataPointId);
      expect(getLedgerTargetByDataPointId(expected.dataPointId)).toBeTruthy();
      expect(
        forecast?.reasoning.some(
          (step) =>
            step.kind === "tool" &&
            step.tool === "forecast_model.damped_log_trend",
        ),
      ).toBe(true);
    }
  });

  it("rejects prediction specs whose target is not registered in the ledger", () => {
    const sourceForecast = FORECAST_CELLS.find(
      (forecast) => forecast.dataPointId,
    );
    expect(sourceForecast).toBeTruthy();

    expect(() =>
      buildPredictionSpecs([
        {
          ...sourceForecast!,
          slug: "unregistered-ledger-target-test",
          dataPointId: "test.unregistered_target",
        },
      ]),
    ).toThrow(/Missing Thesis target ledger entry/);
  });

  it("classifies every prediction by country", () => {
    // The single source of truth is the CountryCode union. `satisfies`
    // makes this record compile-time exhaustive: a hardcoded regex here
    // lagged the type when Belgium series were adopted and bounced a whole
    // wave at the publish gate.
    const allowed = Object.keys({
      US: 1,
      UK: 1,
      CA: 1,
      AU: 1,
      EA: 1,
      JP: 1,
      BE: 1,
    } satisfies Record<CountryCode, 1>);
    for (const forecast of FORECAST_CELLS) {
      expect(allowed).toContain(getForecastCountry(forecast));
    }
  });

  it("prioritizes near-term 2025 Census release targets", () => {
    const slugs = new Set(FORECAST_CELLS.map((forecast) => forecast.slug));
    expect(slugs.has("spm-child-poverty-2025")).toBe(true);
    expect(LIVE_FORECAST_SLUGS.has("spm-child-poverty-2025")).toBe(true);
    expect(slugs.has("spm-poverty-rate-2025")).toBe(true);
    expect(slugs.has("official-poverty-rate-2025")).toBe(true);
    expect(slugs.has("median-household-income-2025")).toBe(true);
    expect(slugs.has("federal-spm-poverty-rate-2026")).toBe(false);
  });

  it("includes near-term calibration examples across tax, health, and benefits", () => {
    const slugs = new Set(FORECAST_CELLS.map((forecast) => forecast.slug));
    expect(slugs.has("individual-income-tax-refunds-fy2026")).toBe(true);
    expect(slugs.has("net-premium-tax-credit-reconciliation-ty2025")).toBe(
      true,
    );
    expect(slugs.has("savers-credit-claimant-returns-ty2025")).toBe(true);
    expect(slugs.has("medicaid-chip-enrollment-dec-2026")).toBe(true);
    expect(slugs.has("direct-purchase-health-coverage-rate-2025")).toBe(true);
    expect(slugs.has("marketplace-new-consumers-oep-2027")).toBe(true);
    expect(slugs.has("infant-mortality-rate-2026-current-law")).toBe(true);
    expect(slugs.has("infant-mortality-rate-2026-ctc-3000-refundable")).toBe(
      true,
    );
    expect(slugs.has("snap-cumulative-benefit-redemptions-fy2026")).toBe(true);
    expect(slugs.has("wic-child-participation-fy2026")).toBe(true);
    expect(slugs.has("ccdf-average-monthly-payment-per-child-fy2026")).toBe(
      true,
    );
  });

  it("includes high-cadence launch examples from the working indicator slate", () => {
    const slugs = new Set(FORECAST_CELLS.map((forecast) => forecast.slug));
    expect(slugs.has("initial-jobless-claims-week-ending-2026-06-06")).toBe(
      true,
    );
    expect(slugs.has("nonfarm-payrolls-may-2026")).toBe(true);
    expect(slugs.has("unemployment-rate-may-2026-first-print")).toBe(true);
    expect(slugs.has("cpi-headline-mom-may-2026")).toBe(true);
    expect(slugs.has("retail-sales-mom-may-2026")).toBe(true);
    expect(slugs.has("us-capacity-utilization-may-2026")).toBe(true);
    expect(slugs.has("us-government-social-benefits-may-2026")).toBe(true);
    expect(slugs.has("us-social-security-benefits-may-2026")).toBe(true);
    expect(slugs.has("us-medicare-benefits-may-2026")).toBe(true);
    expect(slugs.has("us-medicaid-benefits-may-2026")).toBe(true);
    expect(slugs.has("us-wages-and-salaries-may-2026")).toBe(true);
    expect(slugs.has("us-personal-current-taxes-may-2026")).toBe(true);
    expect(slugs.has("us-disposable-personal-income-may-2026")).toBe(true);
    expect(slugs.has("core-pce-mom-may-2026")).toBe(true);
    expect(slugs.has("snap-participation-april-2026")).toBe(true);
    expect(slugs.has("medicaid-chip-enrollment-april-2026")).toBe(true);
  });

  it("registers OEWS occupation targets in the ledger before forecasting", () => {
    const expectedSlugs = [
      "oews-business-financial-employment-may-2026",
      "oews-computer-math-employment-may-2026",
      "oews-healthcare-support-employment-may-2026",
      "oews-office-admin-employment-may-2026",
      "oews-production-employment-may-2026",
      "oews-transport-material-moving-employment-may-2026",
    ];
    const seriesIds = new Set(
      OEWS_OCCUPATION_EMPLOYMENT_PREDICTION_SERIES.map(
        (series) => series.seriesId,
      ),
    );
    const targetDataPointIds = new Set(
      THESIS_TARGET_LEDGER.map((target) => target.dataPointId),
    );
    const occupationCells = FORECAST_CELLS.filter(
      (forecast) => forecast.series && seriesIds.has(forecast.series.seriesId),
    );

    expect(occupationCells.map((forecast) => forecast.slug).sort()).toEqual(
      expectedSlugs.sort(),
    );
    expect(occupationCells).toHaveLength(6);

    for (const forecast of occupationCells) {
      expect(forecast.dataPointId).toBeTruthy();
      expect(targetDataPointIds.has(forecast.dataPointId!)).toBe(true);

      const target = getLedgerTargetByDataPointId(forecast.dataPointId!);
      const ledgerTarget = policyEngineLedger.find(
        (entry): entry is TargetRegisteredLedgerEntry =>
          isTargetRegisteredLedgerEntry(entry) &&
          entry.dataPointId === forecast.dataPointId,
      );

      expect(target).toBeTruthy();
      expect(ledgerTarget).toEqual(target);
      expect(forecast.unit).toBe(target?.unit);
      expect(forecast.resolutionDate).toBe(target?.resolutionDate);
      expect(forecast.resolutionRule).toBe(target?.resolutionRule);
      expect(forecast.resolutionSourceUrl).toBe(target?.resolutionSourceUrl);
      expect(forecast.series?.resolutionPolicy).toBe("first_print");

      const runs = getForecastRunEntries(forecast);
      expect(runs.map((run) => run.variantId)).toEqual([
        "primary",
        "with-bls-employment-projections",
        "bls-implied-2026-annual-baseline",
      ]);
      const blsRun = runs.find(
        (run) => run.variantId === "with-bls-employment-projections",
      );
      const blsImpliedRun = runs.find(
        (run) => run.variantId === "bls-implied-2026-annual-baseline",
      );
      expect(runs.some((run) => run.packSet?.mode === "none")).toBe(true);
      expect(blsRun?.packSet?.packs.map((pack) => pack.packId)).toContain(
        "bls-employment-projections-baseline",
      );
      expect(blsImpliedRun?.predictionRun?.agent).toBe(
        "BLS Employment Projections",
      );
      expect(blsImpliedRun?.description).toContain(
        "Derived near-term annual baseline",
      );
      expect(
        blsRun?.reasoning.some(
          (step) =>
            step.kind === "math" &&
            step.text.includes("BLS projections pack adjustment"),
        ),
      ).toBe(true);
    }

    const officeAdmin = occupationCells.find(
      (forecast) => forecast.slug === "oews-office-admin-employment-may-2026",
    );
    const officeAdminBlsImplied = officeAdmin
      ? getForecastRunEntries(officeAdmin).find(
          (run) => run.variantId === "bls-implied-2026-annual-baseline",
        )
      : undefined;
    expect(officeAdminBlsImplied?.pointEstimate).toBe(17780);
  });

  it("registers OEWS occupation wage targets in the ledger before forecasting", () => {
    const expectedSlugBases = [
      "management",
      "business-financial",
      "computer-math",
      "architecture-engineering",
      "life-physical-social-science",
      "community-social-service",
      "legal",
      "education-library",
      "arts-media",
      "healthcare-practitioners-technical",
      "healthcare-support",
      "protective-service",
      "food-prep-serving",
      "building-grounds",
      "personal-care-service",
      "sales",
      "office-admin",
      "farming-fishing-forestry",
      "construction-extraction",
      "installation-maintenance-repair",
      "production",
      "transport-material-moving",
    ];
    const expectedStatisticSlugs = [
      "10th-percentile",
      "25th-percentile",
      "median",
      "mean",
      "75th-percentile",
      "90th-percentile",
    ];
    const expectedSlugs = expectedSlugBases.flatMap((base) =>
      expectedStatisticSlugs.map(
        (statistic) => `oews-${base}-${statistic}-wage-may-2026`,
      ),
    );
    const seriesIds = new Set(
      OEWS_OCCUPATION_WAGE_PREDICTION_SERIES.map((series) => series.seriesId),
    );
    const targetDataPointIds = new Set(
      THESIS_TARGET_LEDGER.map((target) => target.dataPointId),
    );
    const wageCells = FORECAST_CELLS.filter(
      (forecast) => forecast.series && seriesIds.has(forecast.series.seriesId),
    );

    expect(wageCells.map((forecast) => forecast.slug).sort()).toEqual(
      expectedSlugs.sort(),
    );
    expect(wageCells).toHaveLength(expectedSlugs.length);

    const management = wageCells.find(
      (forecast) => forecast.slug === "oews-management-median-wage-may-2026",
    );
    expect(management?.pointEstimate).toBe(130900);
    expect(management?.historicalContext).toEqual([
      { label: "May 2025 OEWS median", value: 126520 },
    ]);

    const managementMean = wageCells.find(
      (forecast) => forecast.slug === "oews-management-mean-wage-may-2026",
    );
    expect(managementMean?.pointEstimate).toBe(150300);
    expect(managementMean?.historicalContext).toEqual([
      { label: "May 2025 OEWS mean", value: 145260 },
    ]);

    const managementP90 = wageCells.find(
      (forecast) =>
        forecast.slug === "oews-management-90th-percentile-wage-may-2026",
    );
    expect(managementP90?.pointEstimate).toBe(266200);
    expect(managementP90?.historicalContext).toEqual([
      { label: "May 2025 OEWS 90th percentile", value: 257310 },
    ]);

    const computerMath = wageCells.find(
      (forecast) => forecast.slug === "oews-computer-math-median-wage-may-2026",
    );
    expect(computerMath?.pointEstimate).toBe(113000);
    expect(computerMath?.historicalContext).toEqual([
      { label: "May 2025 OEWS median", value: 109280 },
    ]);
    expect(
      computerMath?.reasoning.some(
        (step) =>
          step.kind === "tool" &&
          step.tool === "forecast_model.damped_log_trend" &&
          step.call.includes("damped_log_trend_v1") &&
          step.result.includes("status: 'fallback'"),
      ),
    ).toBe(true);

    for (const forecast of wageCells) {
      expect(forecast.dataPointId).toBeTruthy();
      expect(forecast.dataPointId).toMatch(
        /bls\.oews\.national_occupation_(10th_percentile|25th_percentile|median|mean|75th_percentile|90th_percentile)_annual_wage/,
      );
      expect(targetDataPointIds.has(forecast.dataPointId!)).toBe(true);

      const target = getLedgerTargetByDataPointId(forecast.dataPointId!);
      const ledgerTarget = policyEngineLedger.find(
        (entry): entry is TargetRegisteredLedgerEntry =>
          isTargetRegisteredLedgerEntry(entry) &&
          entry.dataPointId === forecast.dataPointId,
      );

      expect(target).toBeTruthy();
      expect(ledgerTarget).toEqual(target);
      expect(forecast.unit).toBe("usd");
      expect(forecast.unit).toBe(target?.unit);
      expect(forecast.resolutionDate).toBe("2027-05-14");
      expect(forecast.resolutionRule).toMatch(
        /annual (10th percentile|25th percentile|median|mean|75th percentile|90th percentile) wage/,
      );
      expect(forecast.resolutionRule).toMatch(
        /A_(PCT10|PCT25|MEDIAN|MEAN|PCT75|PCT90)/,
      );
      expect(forecast.series?.resolutionPolicy).toBe("first_print");

      const runs = getForecastRunEntries(forecast);
      expect(runs.map((run) => run.variantId)).toEqual([
        "primary",
        "may-2025-oews-carry-forward",
      ]);
      expect(runs[0].packSet?.mode).toBe("none");
      expect(runs[1].predictionRun?.agent).toBe("BLS OEWS current table");
      expect(
        runs[1].reasoning.some(
          (step) =>
            step.kind === "text" &&
            step.text.includes(
              "not an official May 2026 occupational wage projection",
            ),
        ),
      ).toBe(true);
    }
  });

  it("registers apples-to-apples 2034 BLS occupation targets", () => {
    const expectedSlugs = [
      "bls-business-financial-employment-2034",
      "bls-computer-math-employment-2034",
      "bls-healthcare-support-employment-2034",
      "bls-office-admin-employment-2034",
      "bls-production-employment-2034",
      "bls-transport-material-moving-employment-2034",
    ];
    const seriesIds = new Set(
      BLS_2034_OCCUPATION_EMPLOYMENT_PREDICTION_SERIES.map(
        (series) => series.seriesId,
      ),
    );
    const targetDataPointIds = new Set(
      THESIS_TARGET_LEDGER.map((target) => target.dataPointId),
    );
    const occupationCells = FORECAST_CELLS.filter(
      (forecast) => forecast.series && seriesIds.has(forecast.series.seriesId),
    );

    expect(occupationCells.map((forecast) => forecast.slug).sort()).toEqual(
      expectedSlugs.sort(),
    );
    expect(occupationCells).toHaveLength(6);

    const officeAdmin = occupationCells.find(
      (forecast) => forecast.slug === "bls-office-admin-employment-2034",
    );
    expect(officeAdmin?.pointEstimate).toBe(17200);
    expect(officeAdmin?.series?.horizon).toBe("long_run");
    expect(officeAdmin?.resolutionRule).toContain(
      "published 2024-2034 projection is only a comparison forecast",
    );

    for (const forecast of occupationCells) {
      expect(forecast.dataPointId).toBeTruthy();
      expect(forecast.dataPointId).toContain(
        "bls.employment_projections.national_occupation_employment",
      );
      expect(targetDataPointIds.has(forecast.dataPointId!)).toBe(true);

      const target = getLedgerTargetByDataPointId(forecast.dataPointId!);
      expect(target).toBeTruthy();
      expect(forecast.unit).toBe("thousands");
      expect(forecast.resolutionDate).toBe(target?.resolutionDate);
      expect(forecast.resolutionSourceUrl).toBe(target?.resolutionSourceUrl);

      const runs = getForecastRunEntries(forecast);
      expect(runs.map((run) => run.variantId)).toEqual([
        "primary",
        "with-bls-employment-projections",
        "bls-published-2024-2034-projection",
      ]);
      expect(runs.some((run) => run.packSet?.mode === "none")).toBe(true);

      const packedRun = runs.find(
        (run) => run.variantId === "with-bls-employment-projections",
      );
      expect(packedRun?.packSet?.packs.map((pack) => pack.packId)).toContain(
        "bls-employment-projections-baseline",
      );

      const blsRun = runs.find(
        (run) => run.variantId === "bls-published-2024-2034-projection",
      );
      expect(blsRun?.predictionRun?.agent).toBe("BLS Employment Projections");
      expect(blsRun?.reasoning.some((step) => step.kind === "tool")).toBe(true);
    }
  });

  it("registers fast monthly CPS occupation targets", () => {
    const expectedSlugs = [
      "cps-business-financial-employment-june-2026",
      "cps-computer-math-employment-june-2026",
      "cps-healthcare-support-employment-june-2026",
      "cps-office-admin-employment-june-2026",
      "cps-production-employment-june-2026",
      "cps-transport-material-moving-employment-june-2026",
    ];
    const seriesIds = new Set(
      CPS_JUNE_2026_OCCUPATION_EMPLOYMENT_PREDICTION_SERIES.map(
        (series) => series.seriesId,
      ),
    );
    const targetDataPointIds = new Set(
      THESIS_TARGET_LEDGER.map((target) => target.dataPointId),
    );
    const occupationCells = FORECAST_CELLS.filter(
      (forecast) => forecast.series && seriesIds.has(forecast.series.seriesId),
    );

    expect(occupationCells.map((forecast) => forecast.slug).sort()).toEqual(
      expectedSlugs.sort(),
    );
    expect(occupationCells).toHaveLength(6);

    const computerMath = occupationCells.find(
      (forecast) => forecast.slug === "cps-computer-math-employment-june-2026",
    );
    expect(computerMath?.pointEstimate).toBe(6920);
    expect(computerMath?.historicalContext).toEqual([
      { label: "May 2025 CPS", value: 6512 },
      { label: "May 2026 CPS", value: 6903 },
    ]);

    for (const forecast of occupationCells) {
      expect(forecast.dataPointId).toBeTruthy();
      expect(forecast.dataPointId).toContain(
        "bls.cps.employed_people_by_occupation",
      );
      expect(targetDataPointIds.has(forecast.dataPointId!)).toBe(true);
      expect(forecast.resolutionDate).toBe("2026-07-02");
      expect(forecast.series?.cadence).toBe("monthly");
      expect(forecast.series?.priority).toBe("P0");
      expect(forecast.unit).toBe("thousands");
      expect(forecast.resolutionRule).toContain("Table A-19");
      expect(forecast.resolutionRule).toContain("not seasonally adjusted");

      const runs = getForecastRunEntries(forecast);
      const expectedRunIds = ["primary"];
      expect(runs.map((run) => run.variantId)).toEqual(expectedRunIds);
      expect(runs[0].predictionRun?.agent).toBe(
        "brier-cps-occupation-fast-proxy",
      );
      expect(runs[0].packSet?.mode).toBe("none");
    }
  });

  it("carries official source URLs into the resolution queue when available", () => {
    // Property over the whole queue, never named cells: pending membership
    // changes every time a resolution lands, and pinning specific slugs
    // broke the suite the day those cells finally resolved.
    const queue = buildResolutionQueue(FORECAST_CELLS, policyEngineLedger);
    const cellsBySlug = new Map(FORECAST_CELLS.map((cell) => [cell.slug, cell]));
    expect(queue.length).toBeGreaterThan(0);
    let carried = 0;
    for (const entry of queue) {
      const cell = cellsBySlug.get(entry.forecastSlug);
      expect(cell).toBeDefined();
      if (cell?.resolutionSourceUrl) {
        expect(entry.resolutionSourceUrl).toBe(cell.resolutionSourceUrl);
        carried += 1;
      }
    }
    expect(carried).toBeGreaterThan(0);
  });

  it("infers actual resolution timestamps from ledger observations", () => {
    const forecast = FORECAST_CELLS.find(
      (cell) => cell.slug === "nonfarm-payrolls-may-2026",
    );
    expect(forecast).toBeTruthy();

    const resolvedEntries = buildResolvedPredictionLogEntries(
      [
        {
          ...forecast!,
          slug: "nonfarm-payrolls-may-2026-future-expected-date",
          resolutionDate: "2099-01-01",
        },
      ],
      policyEngineLedger,
    );

    expect(resolvedEntries).toHaveLength(1);
    expect(resolvedEntries[0].recordedAt).toBe("2026-06-05");
    expect(resolvedEntries[0].dataPointId).toBe(forecast?.dataPointId);
  });

  it("generates launch cells from structured prediction series", () => {
    expect(LAUNCH_PREDICTION_SERIES.length).toBeGreaterThanOrEqual(8);

    const launchSeriesIds = new Set(
      LAUNCH_PREDICTION_SERIES.map((series) => series.seriesId),
    );
    const launchCells = FORECAST_CELLS.filter(
      (forecast) =>
        forecast.series && launchSeriesIds.has(forecast.series.seriesId),
    );

    expect(launchCells.length).toBeGreaterThanOrEqual(
      LAUNCH_PREDICTION_SERIES.length,
    );
    for (const forecast of launchCells) {
      expect(forecast.series?.cadence).toMatch(/weekly|monthly/);
      expect(forecast.series?.horizon).toMatch(/next_release|plus_3m/);
      expect(forecast.series?.resolutionPolicy).toMatch(
        /first_print|fixed_vintage/,
      );
      expect(forecast.series?.chainableQuestions.length).toBeGreaterThan(1);
    }
  });

  it("includes agent-run predictions across indicators and policy settings", () => {
    expect(AGENT_RUN_PREDICTION_SERIES.length).toBeGreaterThanOrEqual(10);

    const slugs = new Set(FORECAST_CELLS.map((forecast) => forecast.slug));
    expect(slugs.has("average-hourly-earnings-mom-may-2026")).toBe(true);
    expect(slugs.has("core-cpi-mom-may-2026")).toBe(true);
    expect(slugs.has("jolts-job-openings-may-2026")).toBe(true);
    expect(slugs.has("snap-participation-march-2026")).toBe(true);
    expect(slugs.has("wic-total-participation-march-2026")).toBe(true);
    expect(slugs.has("medicaid-chip-enrollment-march-2026")).toBe(true);
    expect(slugs.has("irs-total-refunds-october-2026")).toBe(true);
    expect(slugs.has("snap-max-allotment-four-person-fy2027")).toBe(true);
    expect(slugs.has("hhs-poverty-guideline-family-four-2027")).toBe(true);
    expect(slugs.has("ctc-maximum-per-child-ty2027")).toBe(true);

    const policySettings = FORECAST_CELLS.filter((forecast) =>
      forecast.series
        ? AGENT_RUN_PREDICTION_SERIES.some(
            (series) =>
              series.seriesId === forecast.series?.seriesId &&
              series.type === "policy",
          )
        : false,
    );
    expect(policySettings.length).toBeGreaterThanOrEqual(3);
    for (const forecast of policySettings) {
      expect(forecast.type).toBe("policy");
      expect(forecast.policyParameter).toBeTruthy();
      expect(forecast.series?.horizon).toMatch(/threshold|next_release/);
    }
  });

  it("includes UK indicators and a forward unemployment path", () => {
    expect(UK_PREDICTION_SERIES.length).toBeGreaterThanOrEqual(7);

    const slugs = new Set(FORECAST_CELLS.map((forecast) => forecast.slug));
    expect(slugs.has("uk-monthly-gdp-growth-april-2026")).toBe(true);
    expect(slugs.has("uk-cpi-annual-rate-may-2026")).toBe(true);
    expect(slugs.has("uk-unemployment-rate-feb-apr-2026")).toBe(true);
    expect(slugs.has("uk-unemployment-rate-apr-jun-2026")).toBe(true);
    expect(slugs.has("uk-unemployment-rate-jul-sep-2026")).toBe(true);
    expect(slugs.has("uk-unemployment-rate-oct-dec-2026")).toBe(true);
    expect(slugs.has("uk-paye-payrolled-employees-may-2026")).toBe(true);
    expect(slugs.has("uk-retail-sales-volume-mom-may-2026")).toBe(true);
    expect(slugs.has("uk-public-sector-net-borrowing-may-2026")).toBe(true);
    expect(slugs.has("uk-bank-rate-june-2026-mpc")).toBe(true);

    const ukSeriesIds = new Set(
      UK_PREDICTION_SERIES.map((series) => series.seriesId),
    );
    const ukCells = FORECAST_CELLS.filter(
      (forecast) =>
        forecast.series && ukSeriesIds.has(forecast.series.seriesId),
    );
    expect(ukCells.length).toBeGreaterThanOrEqual(UK_PREDICTION_SERIES.length);
    for (const forecast of ukCells) {
      expect(forecast.resolutionDate >= "2026-06-01").toBe(true);
      expect(getForecastCountry(forecast)).toBe("UK");
      expect(forecast.predictionRun?.kind).toBe("recorded-agent-run");
      expect(getForecastRuntimeKind(forecast)).toBe("agent-run");
      expect(forecast.series?.source).toMatch(
        /Office for National Statistics|Bank of England|HMRC/,
      );
    }

    const q4Unemployment = FORECAST_CELLS.find(
      (forecast) => forecast.slug === "uk-unemployment-rate-oct-dec-2026",
    );
    expect(q4Unemployment?.series?.horizon).toBe("quarterly_path");
    expect(q4Unemployment?.pointEstimate).toBe(5.1);
    expect(q4Unemployment?.resolutionDate).toBe("2027-02-16");
    expect(q4Unemployment?.resolutionRule).toMatch(
      /published one-decimal rate/,
    );
  });

  it("includes quick-resolution Canada and Australia indicators", () => {
    expect(CANADA_AUSTRALIA_PREDICTION_SERIES.length).toBeGreaterThanOrEqual(9);

    const slugs = new Set(FORECAST_CELLS.map((forecast) => forecast.slug));
    expect(slugs.has("canada-unemployment-rate-may-2026")).toBe(true);
    expect(slugs.has("canada-employment-change-may-2026")).toBe(true);
    expect(slugs.has("canada-cpi-annual-rate-may-2026")).toBe(true);
    expect(slugs.has("canada-monthly-gdp-growth-april-2026")).toBe(true);
    expect(slugs.has("canada-overnight-rate-june-2026-boc")).toBe(true);
    expect(slugs.has("australia-unemployment-rate-may-2026")).toBe(true);
    expect(slugs.has("australia-employment-change-may-2026")).toBe(true);
    expect(slugs.has("australia-cpi-annual-rate-may-2026")).toBe(true);
    expect(slugs.has("australia-cash-rate-june-2026-rba")).toBe(true);

    const internationalSeriesIds = new Set(
      CANADA_AUSTRALIA_PREDICTION_SERIES.map((series) => series.seriesId),
    );
    const internationalCells = FORECAST_CELLS.filter(
      (forecast) =>
        forecast.series && internationalSeriesIds.has(forecast.series.seriesId),
    );
    expect(internationalCells.length).toBeGreaterThanOrEqual(
      CANADA_AUSTRALIA_PREDICTION_SERIES.length,
    );
    for (const forecast of internationalCells) {
      expect(forecast.resolutionDate).toMatch(/^2026-06-/);
      expect(["CA", "AU"]).toContain(getForecastCountry(forecast));
      expect(forecast.predictionRun?.kind).toBe("recorded-agent-run");
      expect(getForecastRuntimeKind(forecast)).toBe("agent-run");
      expect(forecast.series?.source).toMatch(
        /Statistics Canada|Bank of Canada|Australian Bureau of Statistics|Reserve Bank of Australia/,
      );
    }
  });

  it("includes quick-resolution euro area and Japan indicators", () => {
    expect(EURO_JAPAN_PREDICTION_SERIES.length).toBeGreaterThanOrEqual(7);

    const slugs = new Set(FORECAST_CELLS.map((forecast) => forecast.slug));
    expect(slugs.has("euro-area-ecb-deposit-facility-rate-june-2026")).toBe(
      true,
    );
    expect(slugs.has("euro-area-hicp-annual-rate-may-2026-final")).toBe(true);
    expect(slugs.has("euro-area-hicp-annual-rate-june-2026-flash")).toBe(true);
    expect(slugs.has("euro-area-unemployment-rate-may-2026")).toBe(true);
    expect(slugs.has("japan-boj-policy-rate-june-2026")).toBe(true);
    expect(slugs.has("japan-cpi-annual-rate-may-2026")).toBe(true);
    expect(slugs.has("japan-tokyo-cpi-annual-rate-june-2026-prelim")).toBe(
      true,
    );
    expect(slugs.has("japan-unemployment-rate-may-2026")).toBe(true);

    const seriesIds = new Set(
      EURO_JAPAN_PREDICTION_SERIES.map((series) => series.seriesId),
    );
    const cells = FORECAST_CELLS.filter(
      (forecast) => forecast.series && seriesIds.has(forecast.series.seriesId),
    );
    expect(cells.length).toBeGreaterThanOrEqual(
      EURO_JAPAN_PREDICTION_SERIES.length,
    );
    for (const forecast of cells) {
      expect(forecast.resolutionDate).toMatch(/^2026-0[67]-/);
      expect(["EA", "JP"]).toContain(getForecastCountry(forecast));
      expect(forecast.predictionRun?.kind).toBe("recorded-agent-run");
      expect(getForecastRuntimeKind(forecast)).toBe("agent-run");
      expect(forecast.series?.source).toMatch(
        /European Central Bank|Eurostat|Bank of Japan|Statistics Bureau of Japan/,
      );
    }
  });

  it("includes additional near-term US official-data indicators", () => {
    expect(US_NEAR_TERM_PREDICTION_SERIES.length).toBeGreaterThanOrEqual(8);

    const slugs = new Set(FORECAST_CELLS.map((forecast) => forecast.slug));
    expect(slugs.has("us-ppi-final-demand-mom-may-2026")).toBe(true);
    expect(slugs.has("us-industrial-production-mom-may-2026")).toBe(true);
    expect(slugs.has("us-import-price-index-mom-may-2026")).toBe(true);
    expect(slugs.has("us-housing-starts-may-2026")).toBe(true);
    expect(slugs.has("us-total-business-inventories-april-2026")).toBe(true);
    expect(slugs.has("us-pce-price-index-mom-may-2026")).toBe(true);
    expect(slugs.has("us-real-gdp-q1-2026-third-estimate")).toBe(true);
    expect(slugs.has("us-mts-deficit-may-2026")).toBe(true);

    const seriesIds = new Set(
      US_NEAR_TERM_PREDICTION_SERIES.map((series) => series.seriesId),
    );
    const cells = FORECAST_CELLS.filter(
      (forecast) => forecast.series && seriesIds.has(forecast.series.seriesId),
    );
    expect(cells.length).toBe(US_NEAR_TERM_PREDICTION_SERIES.length);
    for (const forecast of cells) {
      expect(getForecastCountry(forecast)).toBe("US");
      expect(forecast.predictionRun?.kind).toBe("recorded-agent-run");
      expect(getForecastRuntimeKind(forecast)).toBe("agent-run");
    }
  });

  it("includes US defense public-data forecast targets", () => {
    expect(US_DEFENSE_PREDICTION_SERIES).toHaveLength(5);

    const slugs = new Set(FORECAST_CELLS.map((forecast) => forecast.slug));
    expect(slugs.has("us-defense-aerospace-employment-june-2026")).toBe(true);
    expect(slugs.has("us-defense-shipbuilding-employment-june-2026")).toBe(
      true,
    );
    expect(slugs.has("us-defense-dod-employment-june-2026")).toBe(true);
    expect(slugs.has("us-defense-dod-military-outlays-june-2026")).toBe(true);
    expect(slugs.has("us-defense-dod-contract-obligations-fy2026")).toBe(true);

    const seriesIds = new Set(
      US_DEFENSE_PREDICTION_SERIES.map((series) => series.seriesId),
    );
    const cells = FORECAST_CELLS.filter(
      (forecast) => forecast.series && seriesIds.has(forecast.series.seriesId),
    );
    expect(cells).toHaveLength(US_DEFENSE_PREDICTION_SERIES.length);
    for (const forecast of cells) {
      expect(getForecastCountry(forecast)).toBe("US");
      expect(forecast.predictionRun?.agent).toBe("brier-defense-public-data");
      expect(getForecastRuntimeKind(forecast)).toBe("agent-run");
      expect(
        getLedgerTargetByDataPointId(forecast.dataPointId ?? ""),
      ).toBeTruthy();
    }
  });

  it("includes additional near-term international official-data indicators", () => {
    expect(GLOBAL_NEAR_TERM_PREDICTION_SERIES.length).toBeGreaterThanOrEqual(8);

    const slugs = new Set(FORECAST_CELLS.map((forecast) => forecast.slug));
    expect(slugs.has("canada-retail-sales-growth-april-2026")).toBe(true);
    expect(slugs.has("canada-wholesale-sales-growth-april-2026")).toBe(true);
    expect(slugs.has("canada-ei-regular-beneficiaries-april-2026")).toBe(true);
    expect(slugs.has("canada-building-permit-value-growth-april-2026")).toBe(
      true,
    );
    expect(slugs.has("euro-area-industrial-production-growth-april-2026")).toBe(
      true,
    );
    expect(slugs.has("euro-area-retail-trade-volume-growth-may-2026")).toBe(
      true,
    );
    expect(slugs.has("australia-dwelling-approvals-growth-may-2026")).toBe(
      true,
    );
    expect(slugs.has("japan-real-household-spending-growth-may-2026")).toBe(
      true,
    );

    const seriesIds = new Set(
      GLOBAL_NEAR_TERM_PREDICTION_SERIES.map((series) => series.seriesId),
    );
    const cells = FORECAST_CELLS.filter(
      (forecast) => forecast.series && seriesIds.has(forecast.series.seriesId),
    );
    expect(cells.length).toBe(GLOBAL_NEAR_TERM_PREDICTION_SERIES.length);
    for (const forecast of cells) {
      expect(["CA", "AU", "EA", "JP"]).toContain(getForecastCountry(forecast));
      expect(forecast.predictionRun?.kind).toBe("recorded-agent-run");
      expect(getForecastRuntimeKind(forecast)).toBe("agent-run");
    }
  });

  it("records official outcomes for resolved labor-market predictions", () => {
    const forecastsBySlug = new Map(
      resolvedForecastCells.map((forecast) => [forecast.slug, forecast]),
    );
    const resolutionEntries = buildResolvedPredictionLogEntries(
      resolvedForecastCells,
      policyEngineLedger,
    );
    const observationEntries = policyEngineLedger.filter(
      (entry): entry is ObservationRecordedLedgerEntry =>
        isObservationRecordedLedgerEntry(entry),
    );
    const resolutionSlugs = resolutionEntries.map(
      (entry) => entry.forecastSlug,
    );
    expect(new Set(resolutionSlugs).size).toBe(resolutionSlugs.length);
    expect(
      new Set(observationEntries.map((entry) => entry.observationId)).size,
    ).toBe(observationEntries.length);

    const resolvedPredictions = [
      {
        slug: "nonfarm-payrolls-may-2026",
        dataPointId:
          "bls.ces.total_nonfarm_payroll_change.may_2026.first_print",
        value: 172,
        unit: "thousands",
        result: "inside",
        source: /Bureau of Labor Statistics/,
      },
      {
        slug: "unemployment-rate-may-2026-first-print",
        dataPointId: "bls.cps.unemployment_rate.may_2026.first_print",
        value: 4.3,
        unit: "percent",
        result: "inside",
        source: /Bureau of Labor Statistics/,
      },
      {
        slug: "average-hourly-earnings-mom-may-2026",
        dataPointId:
          "bls.ces.average_hourly_earnings_private.may_2026.first_print",
        value: 0.3,
        unit: "percent_growth",
        result: "inside",
        source: /Bureau of Labor Statistics/,
      },
      {
        slug: "canada-unemployment-rate-may-2026",
        dataPointId:
          "statcan.lfs.unemployment_rate.canada.may_2026.first_print",
        value: 6.6,
        unit: "percent",
        result: "outside",
        source: /Statistics Canada/,
      },
      {
        slug: "canada-employment-change-may-2026",
        dataPointId:
          "statcan.lfs.employment_change.canada.may_2026.first_print",
        value: 88,
        unit: "thousands",
        result: "outside",
        source: /Statistics Canada/,
      },
    ] as const;

    for (const expected of resolvedPredictions) {
      const forecast = forecastsBySlug.get(expected.slug);
      const logEntry = resolutionEntries.find(
        (entry) => entry.forecastSlug === expected.slug,
      );
      expect(logEntry?.dataPointId).toBe(expected.dataPointId);
      const observation = logEntry
        ? getObservationForId(logEntry.observationId, policyEngineLedger)
        : undefined;
      expect(observation?.sourceKind).toBe("official_release");
      expect(observation?.dataPointId).toBe(expected.dataPointId);
      expect(observation?.value).toBe(expected.value);
      expect(observation?.unit).toBe(expected.unit);
      expect(
        getObservationsForDataPoint(
          expected.dataPointId,
          policyEngineLedger,
        ).map((entry) => entry.observationId),
      ).toContain(observation?.observationId);
      expect(forecast).toBeTruthy();
      expect(forecast?.resolvedOutcome?.value).toBe(expected.value);
      expect(forecast?.resolvedOutcome?.resolvedAt).toBe("2026-06-05");
      expect(forecast?.resolvedOutcome?.source).toMatch(expected.source);
      expect(forecast?.resolvedOutcome?.sourceUrl).toMatch(/^https:\/\//);
      expect(getResolutionResult(forecast!)).toBe(expected.result);
    }

    const scores = scoreResolvedForecasts(
      resolvedForecastCells,
      policyEngineLedger,
    );
    expect(scores.length).toBeGreaterThanOrEqual(resolvedPredictions.length);

    for (const expected of resolvedPredictions) {
      const score = scores.find(
        (entry) => entry.forecastSlug === expected.slug,
      );
      expect(score?.dataPointId).toBe(expected.dataPointId);
      expect(score?.ledgerFactRef).toBe(expected.dataPointId);
      expect(score?.runId).toMatch(/^run\./);
      expect(score?.resolutionEventId).toMatch(/^resolution_event\./);
      expect(score?.scoreId).toMatch(/^score\.run\./);
      expect(score?.scoringRule).toBe("numeric_cdf_crps_v3_ledger_scale");
      expect(score?.distributionProvenance).toMatch(
        /^(agent_reported|interval_seeded)$/,
      );
      expect(score?.transformVersion).toMatch(/_v1$/);
      expect(score?.observedValue).toBe(expected.value);
      expect(score?.unit).toBe(expected.unit);
      expect(score?.interval80.width).toBeGreaterThan(0);
      expect(score?.absoluteError).toBeGreaterThanOrEqual(0);
      expect(score?.crps).toBeGreaterThanOrEqual(0);
      if (score?.normalizationScaleSource === "unavailable") {
        expect(score.normalizedAbsoluteError).toBeNull();
        expect(score.normalizedCrps).toBeNull();
      } else {
        expect(score?.normalizedAbsoluteError).toBeGreaterThanOrEqual(0);
        expect(score?.normalizedCrps).toBeGreaterThanOrEqual(0);
      }
      expect(score?.probabilityIntegralTransform).toBeGreaterThanOrEqual(0);
      expect(score?.probabilityIntegralTransform).toBeLessThanOrEqual(1);
      expect(score?.packMode).toBeTruthy();
      expect(score?.interval80Covered).toBe(expected.result === "inside");
    }
  });
});

describe("conditional groups", () => {
  it("resolves every group's cells from the catalog", async () => {
    const { CONDITIONAL_GROUPS, getConditionalGroup } =
      await import("@/data/conditional-groups");
    for (const group of CONDITIONAL_GROUPS) {
      const resolved = getConditionalGroup(group.slug);
      expect(resolved, group.slug).toBeTruthy();
      expect(resolved!.trueArm.unit).toBe(resolved!.falseArm.unit);
      if (group.probabilitySlug) expect(resolved!.probability).toBeTruthy();
      if (group.unconditionalSlug) expect(resolved!.unconditional).toBeTruthy();
    }
  });
});
