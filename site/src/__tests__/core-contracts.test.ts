// Shape validation for core API responses. The page treats the core API as
// untrusted input, so these tests pin the difference between "the API said
// there is no value", "the API never mentioned it" and "the API sent something
// unreadable" — the three states a scoreboard must not collapse.

import { describe, expect, it } from "vitest";
import {
  CoreShapeError,
  assessOrdering,
  parseCoreHealth,
  parseCoreLeaderboard,
  parseCoreListPage,
  readExclusions,
  readMode,
  readTimingSummary,
} from "@/app/core/core-contracts";
import {
  describeCoverage,
  describeExclusions,
  describeMode,
  describeOrdering,
  describeRank,
  describeScore,
  describeTimestamp,
  NOT_REPORTED,
  NOT_REPORTED_UNRECOGNIZED,
} from "@/app/core/core-display";

const ID = "c".repeat(64);

describe("collection page validation", () => {
  it("accepts the documented list envelope", () => {
    // The API projects mode and the timing fields alongside `payload`, so the
    // whole item is kept as the row's summary.
    const item = {
      id: ID,
      kind: "experiment",
      payload: { mode: "replay" },
      committed_at: "2026-09-01T00:00:00+00:00",
      mode: "replay",
    };
    const page = parseCoreListPage({ items: [item], next_cursor: null });
    expect(page.items).toEqual([
      {
        id: ID,
        kind: "experiment",
        payload: { mode: "replay" },
        summary: item,
      },
    ]);
    expect(page.nextCursor).toBeNull();
    expect(page.rejectedItems).toBe(0);
  });

  it("keeps a cursor so the page can say the set is incomplete", () => {
    expect(
      parseCoreListPage({ items: [], next_cursor: "abc" }).nextCursor,
    ).toBe("abc");
  });

  it.each([
    ["a non-object body", [] as unknown],
    ["a missing items array", { next_cursor: null }],
    ["a non-array items field", { items: {}, next_cursor: null }],
    ["a non-string cursor", { items: [], next_cursor: 7 }],
  ])("refuses %s", (_label, body) => {
    expect(() => parseCoreListPage(body)).toThrow(CoreShapeError);
  });

  it("counts unreadable rows instead of silently dropping them", () => {
    const page = parseCoreListPage({
      items: [
        { id: ID, kind: "experiment", payload: {} },
        { id: ID, kind: "experiment" },
        { id: "", kind: "experiment", payload: {} },
        { kind: "experiment", payload: {} },
        null,
      ],
      next_cursor: null,
    });
    expect(page.items).toHaveLength(1);
    expect(page.rejectedItems).toBe(4);
  });
});

describe("health validation", () => {
  it("reads status and schema version", () => {
    const health = parseCoreHealth({ status: "ok", schema_version: 1 });
    expect(health.status).toBe("ok");
    expect(health.schemaVersion).toEqual({ state: "value", value: 1 });
  });

  it("refuses a body with no status", () => {
    expect(() => parseCoreHealth({ schema_version: 1 })).toThrow(
      CoreShapeError,
    );
  });

  it("does not invent a schema version", () => {
    expect(parseCoreHealth({ status: "ok" }).schemaVersion).toEqual({
      state: "missing",
    });
    expect(
      parseCoreHealth({ status: "ok", schema_version: "1" }).schemaVersion,
    ).toEqual({ state: "unrecognized" });
  });
});

describe("leaderboard validation", () => {
  const row = {
    experiment_id: ID,
    forecaster_id: "f".repeat(64),
    mode: "prospective",
    rank: 2,
    coverage: { eligible: 3, total: 4 },
    mean_normalized_crps: 0.4213,
    exclusions: ["missing_normalization"],
  };

  it("accepts the documented row", () => {
    const board = parseCoreLeaderboard({ items: [row] });
    expect(board.rejectedItems).toBe(0);
    expect(board.items[0]).toMatchObject({
      experimentId: { state: "value", value: ID },
      forecasterId: { state: "value", value: "f".repeat(64) },
      mode: { state: "value", value: "prospective" },
      rank: { state: "value", value: 2 },
      coverage: { state: "value", value: { eligible: 3, total: 4 } },
      meanNormalizedCrps: { state: "value", value: 0.4213 },
      exclusions: { state: "value", value: ["missing_normalization"] },
    });
  });

  it("reads all attempt counters and latency while preserving unavailable states", () => {
    const counts = {
      total: 4,
      succeeded: 1,
      failed: 1,
      unknown: 1,
      pending: 1,
      reconciled: 0,
      unknown_history: 1,
    };
    const board = parseCoreLeaderboard({
      items: [
        { ...row, attempt_counts: counts, mean_latency_seconds: 12.5 },
        { ...row, attempt_counts: null, mean_latency_seconds: null },
        { ...row },
        {
          ...row,
          attempt_counts: { ...counts, failed: -1 },
          mean_latency_seconds: -1,
        },
        { ...row, attempt_counts: { total: 0 }, mean_latency_seconds: "12.5" },
      ],
    });
    expect(board.items[0].attemptCounts).toEqual({
      state: "value",
      value: counts,
    });
    expect(board.items[0].meanLatencySeconds).toEqual({
      state: "value",
      value: 12.5,
    });
    for (const field of ["attemptCounts", "meanLatencySeconds"] as const) {
      expect(board.items[1][field]).toEqual({ state: "null" });
      expect(board.items[2][field]).toEqual({ state: "missing" });
      expect(board.items[3][field]).toEqual({ state: "unrecognized" });
      expect(board.items[4][field]).toEqual({ state: "unrecognized" });
    }
  });

  it("reads the timing disclosure the API puts on every leaderboard row", () => {
    const board = parseCoreLeaderboard({
      items: [
        {
          ...row,
          declared_information_cutoff: "2026-09-04T12:00:00+00:00",
          effective_information_boundary: "2026-09-02T09:30:00+00:00",
          evidence_frozen_at: "2026-09-02T09:30:00+00:00",
        },
      ],
    });
    expect(board.items[0].timing.declaredCutoff).toEqual({
      state: "value",
      value: "2026-09-04T12:00:00+00:00",
      field: "declared_information_cutoff",
    });
    expect(board.items[0].timing.ordering).toEqual({
      state: "prospective_satisfied",
    });
  });

  it("reads rank eligibility as the API reports it", () => {
    const board = parseCoreLeaderboard({
      items: [
        { ...row, rank: null, rank_eligible: false },
        { ...row, rank_eligible: "yes" },
        { ...row },
      ],
    });
    expect(board.items[0].rankEligible).toEqual({
      state: "value",
      value: false,
    });
    expect(board.items[1].rankEligible).toEqual({ state: "unrecognized" });
    expect(board.items[2].rankEligible).toEqual({ state: "missing" });
  });

  it("distinguishes an explicit null rank from an absent one", () => {
    const board = parseCoreLeaderboard({
      items: [
        { ...row, rank: null },
        { ...row, rank: undefined },
      ],
    });
    expect(board.items[0].rank).toEqual({ state: "null" });
    expect(board.items[1].rank).toEqual({ state: "missing" });
  });

  it("refuses a rank that is not a positive integer", () => {
    const board = parseCoreLeaderboard({
      items: [
        { ...row, rank: 0 },
        { ...row, rank: 1.5 },
        { ...row, rank: "1" },
      ],
    });
    for (const parsed of board.items) {
      expect(parsed.rank).toEqual({ state: "unrecognized" });
    }
  });

  it("refuses a non-finite or non-numeric score rather than showing zero", () => {
    const board = parseCoreLeaderboard({
      items: [
        { ...row, mean_normalized_crps: Number.POSITIVE_INFINITY },
        { ...row, mean_normalized_crps: "0.4" },
        { ...row, mean_normalized_crps: null },
      ],
    });
    expect(board.items[0].meanNormalizedCrps).toEqual({
      state: "unrecognized",
    });
    expect(board.items[1].meanNormalizedCrps).toEqual({
      state: "unrecognized",
    });
    expect(board.items[2].meanNormalizedCrps).toEqual({ state: "null" });
  });

  it("refuses an incoherent coverage pair", () => {
    const board = parseCoreLeaderboard({
      items: [
        { ...row, coverage: { eligible: 3 } },
        { ...row, coverage: { eligible: 5, total: 4 } },
        { ...row, coverage: { eligible: -1, total: 4 } },
        { ...row, coverage: 4 },
      ],
    });
    for (const parsed of board.items) {
      expect(parsed.coverage).toEqual({ state: "unrecognized" });
    }
  });

  it("keeps an empty exclusion list distinct from an absent one", () => {
    const board = parseCoreLeaderboard({
      items: [
        { ...row, exclusions: [] },
        { ...row, exclusions: undefined },
        { ...row, exclusions: null },
        { ...row, exclusions: [1, 2] },
      ],
    });
    expect(board.items[0].exclusions).toEqual({
      state: "value",
      value: [],
      unreadable: 0,
    });
    expect(board.items[1].exclusions).toEqual({ state: "missing" });
    expect(board.items[2].exclusions).toEqual({ state: "null" });
    expect(board.items[3].exclusions).toEqual({
      state: "value",
      value: [],
      unreadable: 2,
    });
  });

  it("reads the reason-to-count exclusion map the API sends on ranked cohorts", () => {
    // thesis_core/service.py sets exclusions to Counter(eligibility) unless
    // cohort validation failed outright, in which case it is a list of strings.
    expect(readExclusions({ late_witness: 2, unknown_outcome: 1 })).toEqual({
      state: "value",
      value: ["late_witness \u00d7 2", "unknown_outcome \u00d7 1"],
      unreadable: 0,
    });
    expect(readExclusions({})).toEqual({
      state: "value",
      value: [],
      unreadable: 0,
    });
    expect(describeExclusions(readExclusions({}))).toBe("none recorded");
    expect(readExclusions(["cohort proof missing"])).toEqual({
      state: "value",
      value: ["cohort proof missing"],
      unreadable: 0,
    });
  });

  it("refuses a leaderboard body without an items array", () => {
    expect(() => parseCoreLeaderboard({})).toThrow(CoreShapeError);
    expect(() => parseCoreLeaderboard({ items: null })).toThrow(CoreShapeError);
  });

  it("counts unreadable rows", () => {
    const board = parseCoreLeaderboard({ items: [row, "nope", null] });
    expect(board.items).toHaveLength(1);
    expect(board.rejectedItems).toBe(2);
  });
});

describe("mode reading", () => {
  it("recognizes only the two declared modes", () => {
    expect(readMode({ mode: "prospective" })).toEqual({
      state: "value",
      value: "prospective",
    });
    expect(readMode({ mode: "replay" })).toEqual({
      state: "value",
      value: "replay",
    });
  });

  it("never promotes an unknown mode to prospective", () => {
    expect(readMode({ mode: "PROSPECTIVE" })).toEqual({
      state: "unrecognized",
      raw: "PROSPECTIVE",
    });
    expect(readMode({ mode: 1 })).toEqual({ state: "unrecognized", raw: "" });
    expect(readMode({})).toEqual({ state: "missing" });
    expect(describeMode(readMode({}))).toBe("Mode not reported");
    expect(describeMode(readMode({ mode: "PROSPECTIVE" }))).not.toContain(
      "Prospective",
    );
  });
});

describe("timing summary", () => {
  it("reads the declared cutoff and the effective boundary from their own fields", () => {
    const timing = readTimingSummary({
      mode: "prospective",
      declared_scheduling_cutoff: "2026-09-04T12:00:00Z",
      effective_information_boundary: "2026-09-03T08:00:00Z",
    });
    expect(timing.declaredCutoff).toEqual({
      state: "value",
      value: "2026-09-04T12:00:00Z",
      field: "declared_scheduling_cutoff",
    });
    expect(timing.effectiveBoundary).toEqual({
      state: "value",
      value: "2026-09-03T08:00:00Z",
      field: "effective_information_boundary",
    });
  });

  it("prefers the API projection over the record payload, without mixing fields", () => {
    const timing = readTimingSummary(
      { mode: "prospective", information_cutoff: "2026-09-04T12:00:00Z" },
      {
        declared_information_cutoff: "2020-01-01T00:00:00Z",
        evidence_frozen_at: "2026-09-02T09:30:00Z",
      },
    );
    expect(timing.declaredCutoff).toEqual({
      state: "value",
      value: "2026-09-04T12:00:00Z",
      field: "information_cutoff",
    });
    expect(timing.effectiveBoundary).toEqual({
      state: "value",
      value: "2026-09-02T09:30:00Z",
      field: "evidence_frozen_at",
    });
    expect(timing.ordering).toEqual({ state: "prospective_satisfied" });
  });

  it("does not fall back to the payload for a value the projection sent but broke", () => {
    const timing = readTimingSummary(
      { mode: "replay", effective_information_boundary: 17 },
      { evidence_frozen_at: "2026-09-02T09:30:00Z" },
    );
    expect(timing.effectiveBoundary).toEqual({
      state: "unrecognized",
      field: "effective_information_boundary",
    });
  });

  it("accepts the documented aliases for each field", () => {
    expect(
      readTimingSummary({ declared_information_cutoff: "2026-09-04T12:00:00Z" })
        .declaredCutoff,
    ).toMatchObject({ field: "declared_information_cutoff" });
    expect(
      readTimingSummary({ evidence_frozen_at: "2026-09-03T08:00:00Z" })
        .effectiveBoundary,
    ).toMatchObject({ field: "evidence_frozen_at" });
  });

  it("never substitutes one timing field for the other", () => {
    const declaredOnly = readTimingSummary({
      mode: "prospective",
      declared_scheduling_cutoff: "2026-09-04T12:00:00Z",
    });
    expect(declaredOnly.effectiveBoundary).toEqual({ state: "missing" });
    expect(describeTimestamp(declaredOnly.effectiveBoundary)).toBe(
      NOT_REPORTED,
    );

    const effectiveOnly = readTimingSummary({
      mode: "prospective",
      effective_information_boundary: "2026-09-03T08:00:00Z",
    });
    expect(effectiveOnly.declaredCutoff).toEqual({ state: "missing" });
    expect(describeTimestamp(effectiveOnly.declaredCutoff)).toBe(NOT_REPORTED);
  });

  it("marks a present-but-unreadable timestamp as unrecognized, not missing", () => {
    const timing = readTimingSummary({ effective_information_boundary: 17 });
    expect(timing.effectiveBoundary).toEqual({
      state: "unrecognized",
      field: "effective_information_boundary",
    });
    expect(describeTimestamp(timing.effectiveBoundary)).toBe(
      NOT_REPORTED_UNRECOGNIZED,
    );
  });

  it("requires a prospective freeze strictly before the declared cutoff", () => {
    const satisfied = readTimingSummary({
      mode: "prospective",
      declared_scheduling_cutoff: "2026-09-04T12:00:00Z",
      effective_information_boundary: "2026-09-03T08:00:00Z",
    });
    expect(satisfied.ordering).toEqual({ state: "prospective_satisfied" });

    for (const boundary of ["2026-09-04T12:00:00Z", "2026-09-05T00:00:00Z"]) {
      const violated = readTimingSummary({
        mode: "prospective",
        declared_scheduling_cutoff: "2026-09-04T12:00:00Z",
        effective_information_boundary: boundary,
      });
      expect(violated.ordering).toEqual({ state: "prospective_violated" });
    }
  });

  it("does not apply the prospective ordering rule to a replay row", () => {
    const replay = readTimingSummary({
      mode: "replay",
      declared_scheduling_cutoff: "2024-01-31T12:00:00Z",
      effective_information_boundary: "2026-09-03T08:00:00Z",
    });
    expect(replay.ordering).toEqual({ state: "replay_later_freeze" });
    expect(describeOrdering(replay.ordering)).toContain("Replay");
    expect(describeOrdering(replay.ordering)).not.toContain("unmet");
  });

  it("refuses to judge ordering when the mode or a timestamp is unknown", () => {
    expect(
      readTimingSummary({
        declared_scheduling_cutoff: "2026-09-04T12:00:00Z",
        effective_information_boundary: "2026-09-03T08:00:00Z",
      }).ordering,
    ).toEqual({ state: "not_assessable", reason: "mode-missing" });

    expect(
      readTimingSummary({
        mode: "prospective",
        declared_scheduling_cutoff: "2026-09-04T12:00:00Z",
      }).ordering,
    ).toEqual({ state: "not_assessable", reason: "missing-timestamp" });

    expect(
      readTimingSummary({
        mode: "prospective",
        declared_scheduling_cutoff: "whenever",
        effective_information_boundary: "2026-09-03T08:00:00Z",
      }).ordering,
    ).toEqual({ state: "not_assessable", reason: "unzoned-timestamp" });
  });

  it("refuses an ordering verdict when a timestamp carries no timezone", () => {
    expect(
      assessOrdering(
        { state: "value", value: "prospective" },
        {
          state: "value",
          value: "2026-09-04T12:00:00",
          field: "information_cutoff",
        },
        {
          state: "value",
          value: "2026-09-02T09:30:00Z",
          field: "effective_information_boundary",
        },
      ),
    ).toEqual({ state: "not_assessable", reason: "unzoned-timestamp" });
    expect(
      describeOrdering({
        state: "not_assessable",
        reason: "unzoned-timestamp",
      }),
    ).toContain("no timezone");
  });

  it("treats an equal freeze and cutoff as unmet for prospective, at-or-before for replay", () => {
    const same = "2026-09-04T12:00:00Z";
    expect(
      assessOrdering(
        { state: "value", value: "prospective" },
        { state: "value", value: same, field: "information_cutoff" },
        {
          state: "value",
          value: same,
          field: "effective_information_boundary",
        },
      ),
    ).toEqual({ state: "prospective_violated" });
    const replay = assessOrdering(
      { state: "value", value: "replay" },
      { state: "value", value: same, field: "information_cutoff" },
      { state: "value", value: same, field: "effective_information_boundary" },
    );
    expect(replay).toEqual({ state: "replay_within_cutoff" });
    expect(describeOrdering(replay)).toBe(
      "Replay: bundle assembled at or before the historical cutoff.",
    );
  });

  it("refuses a zoned string that is still not a real instant", () => {
    // Reachable only past the timezone guard, and the NaN check is what stops
    // an invalid date from ordering as 1970.
    expect(Number.isNaN(Date.parse("2026-13-45T99:00:00Z"))).toBe(true);
    expect(
      assessOrdering(
        { state: "value", value: "prospective" },
        {
          state: "value",
          value: "2026-13-45T99:00:00Z",
          field: "information_cutoff",
        },
        {
          state: "value",
          value: "2026-09-02T09:30:00Z",
          field: "effective_information_boundary",
        },
      ),
    ).toEqual({ state: "not_assessable", reason: "unparseable-timestamp" });
    expect(
      describeOrdering({ state: "not_assessable", reason: "unparseable-timestamp" }),
    ).toBe("Not assessable: a timing field is not a readable timestamp.");
  });

  it("compares instants, not strings, across offsets", () => {
    expect(
      assessOrdering(
        { state: "value", value: "prospective" },
        {
          state: "value",
          value: "2026-09-04T00:00:00Z",
          field: "declared_scheduling_cutoff",
        },
        {
          state: "value",
          value: "2026-09-03T21:00:00-04:00",
          field: "effective_information_boundary",
        },
      ),
    ).toEqual({ state: "prospective_violated" });
  });

  it("tolerates a payload that is not an object at all", () => {
    const timing = readTimingSummary("nonsense");
    expect(timing.declaredCutoff).toEqual({ state: "missing" });
    expect(timing.effectiveBoundary).toEqual({ state: "missing" });
    expect(timing.mode).toEqual({ state: "missing" });
  });
});

describe("display strings never manufacture a value", () => {
  it("shows a rank the API contradicts rather than the flattering half", () => {
    expect(
      describeRank(
        { state: "value", value: 3 },
        { state: "value", value: false },
      ),
    ).toBe("3 (not rank-eligible)");
    expect(
      describeRank(
        { state: "value", value: 3 },
        { state: "value", value: true },
      ),
    ).toBe("3");
    expect(
      describeRank({ state: "null" }, { state: "value", value: false }),
    ).toBe("not ranked (not rank-eligible)");
  });

  it("keeps rank, score and coverage away from a zero default", () => {
    expect(describeRank({ state: "null" })).toBe("not ranked");
    expect(describeRank({ state: "missing" })).toBe(NOT_REPORTED);
    expect(describeRank({ state: "unrecognized" })).toBe(
      NOT_REPORTED_UNRECOGNIZED,
    );
    expect(describeScore({ state: "null" })).toBe("not available");
    expect(describeScore({ state: "missing" })).toBe(NOT_REPORTED);
    expect(describeCoverage({ state: "missing" })).toBe(NOT_REPORTED);
    for (const rendered of [
      describeRank({ state: "null" }),
      describeScore({ state: "null" }),
      describeCoverage({ state: "null" }),
    ]) {
      expect(rendered).not.toMatch(/\b0\b/);
    }
  });

  it("shows a recorded score at full precision", () => {
    expect(describeScore({ state: "value", value: 0.123456789012 })).toBe(
      "0.123456789012",
    );
  });

  it("says 'none recorded' only when the API actually sent an empty list", () => {
    expect(
      describeExclusions({ state: "value", value: [], unreadable: 0 }),
    ).toBe("none recorded");
    expect(describeExclusions({ state: "missing" })).toBe(NOT_REPORTED);
    expect(describeExclusions({ state: "null" })).toBe("not available");
    expect(
      describeExclusions({
        state: "value",
        value: ["late_reconciliation", "no_scale"],
        unreadable: 0,
      }),
    ).toBe("late_reconciliation, no_scale");
  });

  it("never lets one malformed entry hide the exclusions it can read", () => {
    expect(readExclusions(["late_reconciliation", 7])).toEqual({
      state: "value",
      value: ["late_reconciliation"],
      unreadable: 1,
    });
    expect(describeExclusions(readExclusions(["late_reconciliation", 7]))).toBe(
      "late_reconciliation; 1 unreadable entry",
    );
    expect(describeExclusions(readExclusions({ late: 2, weird: "x" }))).toBe(
      "late \u00d7 2; 1 unreadable entry",
    );
    // Nothing readable at all still must not read as "none recorded".
    expect(describeExclusions(readExclusions([1, 2]))).toBe(
      "2 unreadable entries",
    );
    expect(describeExclusions(readExclusions("nonsense"))).toBe(
      NOT_REPORTED_UNRECOGNIZED,
    );
  });
});
