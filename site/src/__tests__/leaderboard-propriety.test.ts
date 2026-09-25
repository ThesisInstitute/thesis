import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  buildBrierAgentLeaderboard,
  leaderboardRankingStatistic,
  type BrierRewardRow,
} from "@/data/brier-lab";
import {
  buildNumericCdfFromInterval,
  scoreNumericCdfDistribution,
  type NumericCdfDistribution,
} from "@/data/prediction-distribution";
import { PERSISTENCE_BASELINE_AGENT } from "@/data/time-series-priors";

// The leaderboard claims proper scoring, so the statistic that orders it
// must reward honesty: for a forecaster whose belief about each outcome
// is F, reporting F must minimize the statistic's EXPECTED value. This
// suite checks that end to end — reports scored by the real CRPS kernel,
// rows ranked by the real buildBrierAgentLeaderboard — with a Gaussian
// belief Y ~ N(0, 1) and reports N(0, sigma²) over a grid of sigma, the
// expectation taken by quadrature over Y.
//
// Quadrature over one or two targets cannot see an aggregator that is only
// nonlinear across three or more (a median or trimmed mean of per-target
// deltas agrees with the mean below three and is improper at five), so a
// property test also pins the structural reason the statistic is proper:
// it moves by exactly delta / (scale * targets * runs on that target) when
// one run's CRPS moves by delta, whatever every other score is.
//
// The same harness convicts the statistics the leaderboard must never use
// again: the geometric mean of per-target raw CRPS ratios it ranked by
// until 2026-09-24 (optimum sigma 0.46 whatever the baseline: an "80%"
// interval with ~38% coverage), ratio-of-means, and mean-of-ratios. Each
// divides by the baseline's REALIZED CRPS, which reweights outcomes.

const SQRT_2PI = Math.sqrt(2 * Math.PI);

// Complementary error function, Numerical Recipes erfcc: fractional error
// below 1.2e-7 everywhere, far inside what these comparisons resolve.
function erfc(x: number) {
  const z = Math.abs(x);
  const t = 1 / (1 + 0.5 * z);
  const r =
    t *
    Math.exp(
      -z * z -
        1.26551223 +
        t *
          (1.00002368 +
            t *
              (0.37409196 +
                t *
                  (0.09678418 +
                    t *
                      (-0.18628806 +
                        t *
                          (0.27886807 +
                            t *
                              (-1.13520398 +
                                t *
                                  (1.48851587 +
                                    t * (-0.82215223 + t * 0.17087277)))))))),
    );
  return x >= 0 ? r : 2 - r;
}

const normalCdf = (x: number) => 0.5 * erfc(-x / Math.SQRT2);

// A report of N(mean, sd²) as the 201-point piecewise-linear CDF every
// scored run carries, spanning +/-8 sd.
function gaussianReport(mean: number, sd: number): NumericCdfDistribution {
  const points = Array.from({ length: 201 }, (_, index) => {
    const value = mean - 8 * sd + (16 * sd * index) / 200;
    const probability =
      index === 0 ? 0 : index === 200 ? 1 : normalCdf((value - mean) / sd);
    return { value, probability };
  });
  return {
    format: "numeric_cdf_v1",
    pointCount: 201,
    support: { lower: points[0].value, upper: points[200].value },
    points,
    summary: {
      pointEstimate: mean,
      median: mean,
      interval80: { lower: mean - 1.2816 * sd, upper: mean + 1.2816 * sd },
    },
    provenance: "agent_reported",
  };
}

// Trapezoid nodes and normalized weights for Y ~ N(0, 1) on [-8, 8].
function beliefNodes(count: number) {
  const step = 16 / (count - 1);
  const nodes = Array.from({ length: count }, (_, index) => -8 + index * step);
  const raw = nodes.map((y) => Math.exp((-y * y) / 2) / SQRT_2PI);
  const total = raw.reduce((sum, weight) => sum + weight, 0);
  return { nodes, weights: raw.map((weight) => weight / total) };
}

const crpsAt = (distribution: NumericCdfDistribution, nodes: number[]) =>
  nodes.map((y) => scoreNumericCdfDistribution(distribution, y).crps);

// A score-carrying reward row exactly as the export writes one.
function rewardRow(
  agent: string,
  predictionId: string,
  crps: number,
  scale: number,
): BrierRewardRow {
  return {
    predictionId,
    agent,
    reward: {
      value: -crps / scale,
      components: {
        crps,
        normalizedCrps: crps / scale,
        absoluteError: null,
        normalizedAbsoluteError: null,
        sharpness: 1,
        normalizationScale: scale,
        normalizationScaleSource: "ledger_dispersion",
        interval80Covered: null,
      },
    },
    provenance: { activityArtifactCount: 1 },
  } as unknown as BrierRewardRow;
}

const CANDIDATE = "candidate.forecaster";

// The leaderboard's own ranking statistic for the candidate, from rows.
function rankingStatistic(rows: BrierRewardRow[]) {
  const leaderboard = buildBrierAgentLeaderboard(rows);
  const candidate = leaderboard.find((row) => row.agent === CANDIDATE);
  const value = candidate ? leaderboardRankingStatistic(candidate) : null;
  if (value === null) throw new Error("candidate has no ranking statistic");
  return value;
}

interface Target {
  id: string;
  scale: number;
  baseline: NumericCdfDistribution;
}

// Scale-free per-target inputs a statistic may use: agent and baseline
// CRPS, and the target's ledger scale.
type PairedStatistic = (
  pairs: Array<{ agent: number; baseline: number; scale: number }>,
) => number;

const geomeanOfRatios: PairedStatistic = (pairs) =>
  Math.exp(
    pairs.reduce((sum, pair) => sum + Math.log(pair.agent / pair.baseline), 0) /
      pairs.length,
  );
const ratioOfMeans: PairedStatistic = (pairs) =>
  pairs.reduce((sum, pair) => sum + pair.agent, 0) /
  pairs.reduce((sum, pair) => sum + pair.baseline, 0);
const meanOfRatios: PairedStatistic = (pairs) =>
  pairs.reduce((sum, pair) => sum + pair.agent / pair.baseline, 0) /
  pairs.length;

const SIGMAS = [0.4, 0.6, 0.8, 1, 1.25, 1.6];
const TRUTHFUL = SIGMAS.indexOf(1);

// E[statistic] for each report sigma, over independent outcomes on every
// target (a full product quadrature, so nonlinear statistics are exact to
// quadrature error, not approximated by their large-n limit).
function expectedByReport(
  targets: Target[],
  nodeCount: number,
  statistic: (
    agentCrps: number[],
    baselineCrps: number[],
    targets: Target[],
  ) => number,
) {
  const { nodes, weights } = beliefNodes(nodeCount);
  const baselineCrps = targets.map((target) => crpsAt(target.baseline, nodes));
  return SIGMAS.map((sigma) => {
    const agentCrps = crpsAt(gaussianReport(0, sigma), nodes);
    let expected = 0;
    const indices = targets.map(() => 0);
    for (;;) {
      const weight = indices.reduce((product, i) => product * weights[i], 1);
      expected +=
        weight *
        statistic(
          indices.map((i) => agentCrps[i]),
          indices.map((i, t) => baselineCrps[t][i]),
          targets,
        );
      let digit = 0;
      while (digit < indices.length && ++indices[digit] === nodeCount) {
        indices[digit] = 0;
        digit += 1;
      }
      if (digit === indices.length) break;
    }
    return expected;
  });
}

const viaLeaderboard = (
  agentCrps: number[],
  baselineCrps: number[],
  targets: Target[],
) =>
  rankingStatistic(
    targets.flatMap((target, t) => [
      rewardRow(
        PERSISTENCE_BASELINE_AGENT,
        target.id,
        baselineCrps[t],
        target.scale,
      ),
      rewardRow(CANDIDATE, target.id, agentCrps[t], target.scale),
    ]),
  );

const viaPaired =
  (statistic: PairedStatistic) =>
  (agentCrps: number[], baselineCrps: number[], targets: Target[]) =>
    statistic(
      targets.map((target, t) => ({
        agent: agentCrps[t],
        baseline: baselineCrps[t],
        scale: target.scale,
      })),
    );

function expectTruthfulMinimizes(expected: number[]) {
  const truthful = expected[TRUTHFUL];
  expected.forEach((value, index) => {
    if (index === TRUTHFUL) return;
    expect(truthful).toBeLessThan(value);
  });
}

function expectMisreportingWins(expected: number[]) {
  const best = Math.min(...expected);
  expect(best).toBeLessThan(expected[TRUTHFUL]);
  expect(expected.indexOf(best)).not.toBe(TRUTHFUL);
}

// Baselines unlike the belief in location, spread, and units, as the
// ledger persistence baseline is.
const ONE_TARGET: Target[] = [
  { id: "claims", scale: 1, baseline: gaussianReport(0.3, 1.2) },
];
const TWO_TARGETS: Target[] = [
  { id: "claims", scale: 1, baseline: gaussianReport(0.3, 1.2) },
  { id: "rate", scale: 0.25, baseline: gaussianReport(-0.5, 0.6) },
];

describe("leaderboard ranking propriety", () => {
  it("ranks by the statistic leaderboardRankingStatistic reports", () => {
    const { nodes } = beliefNodes(9);
    for (const y of nodes) {
      const rows = SIGMAS.flatMap((sigma) => [
        rewardRow(
          `sigma-${sigma}`,
          "claims",
          scoreNumericCdfDistribution(gaussianReport(0, sigma), y).crps,
          1,
        ),
      ]).concat(
        rewardRow(
          PERSISTENCE_BASELINE_AGENT,
          "claims",
          scoreNumericCdfDistribution(ONE_TARGET[0].baseline, y).crps,
          1,
        ),
      );
      const ranked = buildBrierAgentLeaderboard(rows).filter(
        (row) => row.agent !== PERSISTENCE_BASELINE_AGENT,
      );
      const statistics = ranked.map((row) => leaderboardRankingStatistic(row)!);
      expect(statistics).toEqual([...statistics].sort((a, b) => a - b));
    }
  });

  it("is minimized in expectation by the truthful report on one target", () => {
    expectTruthfulMinimizes(expectedByReport(ONE_TARGET, 801, viaLeaderboard));
  });

  it("is minimized in expectation by the truthful report across two targets", () => {
    expectTruthfulMinimizes(expectedByReport(TWO_TARGETS, 97, viaLeaderboard));
  });

  it("keeps each repeat run honest when a forecaster runs a target twice", () => {
    const { nodes, weights } = beliefNodes(801);
    const baseline = crpsAt(ONE_TARGET[0].baseline, nodes);
    const honest = crpsAt(gaussianReport(0, 1), nodes);
    const expected = SIGMAS.map((sigma) => {
      const varied = crpsAt(gaussianReport(0, sigma), nodes);
      return nodes.reduce(
        (sum, _y, i) =>
          sum +
          weights[i] *
            rankingStatistic([
              rewardRow(PERSISTENCE_BASELINE_AGENT, "claims", baseline[i], 1),
              rewardRow(CANDIDATE, "claims", honest[i], 1),
              rewardRow(CANDIDATE, "claims", varied[i], 1),
            ]),
        0,
      );
    });
    expectTruthfulMinimizes(expected);
  });

  it.each([
    ["geometric mean of raw CRPS ratios", geomeanOfRatios],
    ["ratio of mean CRPS", ratioOfMeans],
    ["mean of CRPS ratios", meanOfRatios],
  ])(
    "convicts the %s: a misreport beats the truth in expectation",
    (_label, statistic) => {
      expectMisreportingWins(
        expectedByReport(ONE_TARGET, 801, viaPaired(statistic)),
      );
      expectMisreportingWins(
        expectedByReport(TWO_TARGETS, 97, viaPaired(statistic)),
      );
    },
  );
});

describe("leaderboard ranking linearity", () => {
  const targetArbitrary = fc.record({
    scale: fc.double({ min: 0.01, max: 100, noNaN: true }),
    baseline: fc.double({ min: 0, max: 10, noNaN: true }),
    runs: fc.array(fc.double({ min: 0, max: 10, noNaN: true }), {
      minLength: 1,
      maxLength: 3,
    }),
  });

  it("moves by exactly delta / (scale * targets * runs) for any one run", () => {
    fc.assert(
      fc.property(
        fc.array(targetArbitrary, { minLength: 1, maxLength: 7 }),
        fc.nat(),
        fc.nat(),
        fc.double({ min: 0, max: 5, noNaN: true }),
        (targets, targetPick, runPick, delta) => {
          const rowsWith = (bump: number) =>
            targets.flatMap((target, t) => [
              rewardRow(
                PERSISTENCE_BASELINE_AGENT,
                `t${t}`,
                target.baseline,
                target.scale,
              ),
              ...target.runs.map((crps, r) =>
                rewardRow(
                  CANDIDATE,
                  `t${t}`,
                  crps +
                    (t === targetPick % targets.length &&
                    r === runPick % target.runs.length
                      ? bump
                      : 0),
                  target.scale,
                ),
              ),
            ]);
          const picked = targets[targetPick % targets.length];
          const expectedShift =
            delta / (picked.scale * targets.length * picked.runs.length);
          const before = rankingStatistic(rowsWith(0));
          const shift = rankingStatistic(rowsWith(delta)) - before;
          // Summation noise scales with the statistic itself (normalized
          // CRPS up to 10 / 0.01 = 1000 per run).
          expect(Math.abs(shift - expectedShift)).toBeLessThanOrEqual(
            1e-9 * (Math.abs(expectedShift) + Math.abs(before)) + 1e-12,
          );
        },
      ),
      { numRuns: 400 },
    );
  });
});

describe("interval_anchor_v1 incentive (disclosed, not ranked on)", () => {
  // Scoring a (point, 80% interval) report through the fixed five-knot
  // transform is not proper for the interval itself: under a N(0, 1)
  // belief the expected-CRPS-optimal "80%" half-width is about 0.85 of the
  // truthful 1.2816, a ~0.7% expected-score gain. docs/brier-lab.md
  // discloses this; the pin makes any transform change revisit it.
  it("rewards an interval about 0.85x the truthful width", () => {
    const { nodes, weights } = beliefNodes(801);
    const truthfulHalfWidth = 1.2815515655446004;
    const factors = Array.from({ length: 31 }, (_, i) => 0.7 + i * 0.01);
    const expected = factors.map((factor) => {
      const half = factor * truthfulHalfWidth;
      const report = buildNumericCdfFromInterval({
        pointEstimate: 0,
        ciLow: -half,
        ciHigh: half,
      });
      return crpsAt(report, nodes).reduce(
        (sum, crps, i) => sum + weights[i] * crps,
        0,
      );
    });
    const best = factors[expected.indexOf(Math.min(...expected))];
    expect(best).toBeGreaterThanOrEqual(0.82);
    expect(best).toBeLessThanOrEqual(0.88);
    const truthful = expected[factors.findIndex((f) => Math.abs(f - 1) < 1e-9)];
    const gain = (truthful - Math.min(...expected)) / truthful;
    expect(gain).toBeGreaterThan(0.003);
    expect(gain).toBeLessThan(0.012);
  });
});
