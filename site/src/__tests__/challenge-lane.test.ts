import fs from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import {
  CHALLENGE_SUBMISSIONS,
  listChallengeSubmissions,
} from "@/data/challenge";
import { FORECAST_CELLS, getForecastRunEntries } from "@/data/forecast-cells";
import {
  buildBrierAgentLeaderboard,
  buildBrierRewardExport,
  type BrierRewardRow,
} from "@/data/brier-lab";
import {
  buildPredictionSpecs,
  buildRecordedPredictionRunRecords,
} from "@/data/prediction-specs";

// These fixtures test challenge attribution propagation after a submission passes publication eligibility.
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

const REPO_ROOT = path.resolve(__dirname, "../../..");

const externalRuns = FORECAST_CELLS.flatMap((cell) =>
  (cell.comparisonRuns ?? [])
    .filter((run) => run.externalSubmission)
    .map((run) => ({ cell, run })),
);

describe("challenge registry", () => {
  it("joins every registry row onto a real cell and run", () => {
    const views = listChallengeSubmissions();
    expect(views).toHaveLength(CHALLENGE_SUBMISSIONS.length);
    for (const view of views) {
      expect(view.cell.slug).toBe(view.cellSlug);
      expect(view.run.variantId).toBe(view.variantId);
    }
  });

  it("stays in lockstep with externally flagged comparison runs", () => {
    const registryVariantIds = new Set(
      CHALLENGE_SUBMISSIONS.map((record) => record.variantId),
    );
    const flaggedVariantIds = new Set(
      externalRuns.map(({ run }) => run.variantId),
    );
    expect(flaggedVariantIds).toEqual(registryVariantIds);
  });

  it("covers every merged inbox submission — none can vanish silently", () => {
    // Completeness: enumerate the inbox itself, so removing a registry
    // row together with its augment still fails here.
    const inboxDir = path.join(REPO_ROOT, "challenge", "inbox");
    const inboxFiles = fs
      .readdirSync(inboxDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .flatMap((dir) =>
        fs
          .readdirSync(path.join(inboxDir, dir.name))
          .filter(
            (name) =>
              name.endsWith(".json") && !name.endsWith(".sigstore.json"),
          )
          .map((name) => path.posix.join("challenge/inbox", dir.name, name)),
      )
      .sort();
    const registryPaths = CHALLENGE_SUBMISSIONS.map(
      (record) => record.inboxPath,
    ).sort();
    expect(registryPaths).toEqual(inboxFiles);
  });

  it("matches the merged inbox files — the ground truth, not a copy", () => {
    for (const record of CHALLENGE_SUBMISSIONS) {
      const inboxFile = path.join(REPO_ROOT, record.inboxPath);
      const submission = JSON.parse(fs.readFileSync(inboxFile, "utf8")) as {
        schemaVersion: string;
        challenger: string;
        systemType: string;
        systemName: string;
        dataPointId: string;
      };
      expect(submission.schemaVersion).toBe("thesis_challenge_submission_v1");
      expect(submission.challenger).toBe(record.challenger);
      expect(submission.systemType).toBe(record.systemType);
      expect(submission.systemName).toBe(record.systemName);
      expect(submission.dataPointId).toBe(record.dataPointId);
    }
  });

  it("names records digests that actually publish each submission", () => {
    for (const record of CHALLENGE_SUBMISSIONS) {
      const digestFile = path.join(REPO_ROOT, record.recordsDigest);
      expect(fs.existsSync(digestFile), record.recordsDigest).toBe(true);
      // Content binding, not just existence: the digest must carry this
      // challenger's row for this target.
      const digest = fs.readFileSync(digestFile, "utf8");
      expect(
        digest,
        `${record.recordsDigest} names ${record.challenger}`,
      ).toContain(record.challenger);
      expect(
        digest,
        `${record.recordsDigest} names ${record.dataPointId}`,
      ).toContain(record.dataPointId);
    }
  });

  it("matches each cell's registered target and the run's claims", () => {
    for (const view of listChallengeSubmissions()) {
      expect(view.cell.dataPointId).toBe(view.dataPointId);
      expect(view.run.predictionRun.runAt).toBe(view.submittedAtUtc);
      expect(view.run.predictionRun.sourceContext ?? []).toContain(
        view.recordsDigest,
      );
      expect(view.run.externalSubmission).toEqual({
        challenger: view.challenger,
        systemType: view.systemType,
      });
    }
  });

  it("rejects registry rows that name unknown cells", () => {
    expect(() =>
      listChallengeSubmissions(
        FORECAST_CELLS.filter(
          (cell) => cell.slug !== CHALLENGE_SUBMISSIONS[0].cellSlug,
        ),
      ),
    ).toThrow(/unknown cell slug/);
  });
});

describe("external attribution propagation", () => {
  it("copies externalSubmission onto run entries", () => {
    for (const { cell, run } of externalRuns) {
      const entries = getForecastRunEntries(cell);
      const entry = entries.find(
        (candidate) => candidate.variantId === run.variantId,
      );
      expect(entry?.externalSubmission).toEqual(run.externalSubmission);
      const primary = entries.find((candidate) => candidate.isPrimary);
      expect(primary?.externalSubmission).toBeUndefined();
    }
  });

  it("carries eligible submission attribution through the reward export", () => {
    // Exercise attribution mapping after the separately tested publication
    // gate. If buildRewardRow drops externalSubmission, this fails.
    const specs = buildPredictionSpecs(FORECAST_CELLS);
    const runs = buildRecordedPredictionRunRecords(FORECAST_CELLS, specs);
    const rewardExport = buildBrierRewardExport({
      forecasts: FORECAST_CELLS,
      specs,
      runs,
      ledger: [],
    });
    const externalVariantIds = new Set(
      CHALLENGE_SUBMISSIONS.map((record) => record.variantId),
    );
    const externalRows = rewardExport.rewardRows.filter((row) =>
      externalVariantIds.has(row.runVariantId),
    );
    expect(externalRows).toHaveLength(CHALLENGE_SUBMISSIONS.length);
    for (const row of externalRows) {
      expect(row.externalSubmission).toBeDefined();
      expect(row.externalSubmission?.systemType).toBe("ai");
    }
    const externalLeaderboardRows = rewardExport.leaderboard.filter(
      (row) => row.external,
    );
    const flaggedAgents = new Set(
      externalLeaderboardRows.map((row) => row.agent),
    );
    for (const row of externalRows) {
      expect(row.agent).toBeDefined();
      expect(flaggedAgents.has(row.agent ?? "")).toBe(true);
    }
    for (const row of externalLeaderboardRows) {
      expect(row.externalSystemTypes).toEqual(["ai"]);
    }
  });

  it("fails loudly when a group mixes internal and external rows", () => {
    const base = (
      overrides: Partial<BrierRewardRow> & { runId: string },
    ): BrierRewardRow =>
      ({
        schemaVersion: "brier_reward_row_v1",
        predictionId: "p",
        specId: "s",
        split: "resolved",
        scoreEligibility: "scored_witness_verified",
        agent: "agent-a",
        runLabel: "run",
        runVariantId: "primary",
        distributionProvenance: "agent_reported",
        transformVersion: "v",
        resolutionDate: "2026-08-01",
        reward: {
          objective: "minimize_normalized_crps",
          value: null,
          components: {
            crps: null,
            normalizedCrps: null,
            absoluteError: null,
            normalizedAbsoluteError: null,
            sharpness: null,
            normalizationScale: null,
            normalizationScaleSource: null,
            interval80Covered: null,
          },
        },
        auxiliaryJudges: {
          rewardEligible: false,
          traceQualityScore: null,
          primaryFailureMode: undefined,
        },
        preSubmitReview: {
          status: "not_reviewed",
          reviewed: false,
          findingCount: 0,
          acceptedCount: 0,
          blockingFindingCount: 0,
        },
        provenance: {
          activityArtifactCount: 0,
        },
        ...overrides,
      }) as BrierRewardRow;

    const pure = buildBrierAgentLeaderboard([
      base({
        runId: "r1",
        agent: "github:pure-ext",
        externalSubmission: { challenger: "github:pure-ext", systemType: "ai" },
      }),
      base({ runId: "r2", agent: "thesis.analyst" }),
    ]);
    const byAgent = new Map(pure.map((row) => [row.agent, row]));
    expect(byAgent.get("github:pure-ext")?.external).toBe(true);
    expect(byAgent.get("github:pure-ext")?.externalSystemTypes).toEqual(["ai"]);
    expect(byAgent.get("thesis.analyst")?.external).toBe(false);

    expect(() =>
      buildBrierAgentLeaderboard([
        base({ runId: "r3", agent: "github:mixed" }),
        base({
          runId: "r4",
          agent: "github:mixed",
          externalSubmission: {
            challenger: "github:mixed",
            systemType: "ai",
          },
        }),
      ]),
    ).toThrow(/mixes internal and external rows/);
  });
});
