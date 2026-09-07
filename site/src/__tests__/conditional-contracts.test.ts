import { describe, expect, it } from "vitest";
import { parseLab } from "@/lib/lab-schema";
import { fetchLab } from "@/app/lab/lab-client";
import {
  conditional,
  conditionalPage,
  expiredConditional,
  expiredSummary,
  unsuccessful,
} from "./conditional-fixtures";
import { ids } from "./lab-fixtures";

describe("conditional wire contracts", () => {
  it("preserves the exact native paired response and validates unsuccessful attempts", () => {
    expect(parseLab("ConditionalDetail", conditional)).toBe(conditional);
    expect(parseLab("ConditionalPage", conditionalPage)).toBe(conditionalPage);
    for (const state of ["failed", "unknown"] as const)
      expect(
        parseLab("ConditionalDetail", unsuccessful(state)).execution_state,
      ).toBe(state);
    expect(conditional.response!.reference.points).toHaveLength(201);
  });
  it("accepts an unrecovered expired lease without inventing a finish time", () => {
    expect(
      parseLab("ConditionalDetail", expiredConditional).finished_at,
    ).toBeNull();
    const page = {
      ...conditionalPage,
      generated_at: expiredConditional.generated_at,
      items: [conditionalPage.items[0], expiredSummary],
      total: 2,
    };
    expect(parseLab("ConditionalPage", page).items).toHaveLength(2);
    for (const error_code of [null, "invalid_response", "attempt_expired"]) {
      expect(() =>
        parseLab("ConditionalDetail", { ...expiredConditional, error_code }),
      ).toThrow();
    }
  });
  it.each([
    { ...conditional, response: null },
    {
      ...conditional,
      response: {
        ...conditional.response!,
        arms: [conditional.response!.arms[0]],
      },
    },
    {
      ...conditional,
      response: {
        ...conditional.response!,
        arms: [...conditional.response!.arms].reverse(),
      },
    },
    {
      ...conditional,
      contract: {
        ...conditional.contract,
        arms: [conditional.contract.arms[0], 3],
      },
    },
    {
      ...conditional,
      response: { ...conditional.response!, contract_id: ids.agent },
    },
    {
      ...conditional,
      response: { ...conditional.response!, shared_evidence_id: ids.agent },
    },
    { ...conditional, unit: "other unit" },
    {
      ...conditional,
      arm_quantiles: [
        conditional.arm_quantiles[1],
        conditional.arm_quantiles[0],
      ],
    },
    {
      ...conditional,
      response: {
        ...conditional.response!,
        arms: [
          { ...conditional.response!.arms[0], baseline_delta: 100 },
          conditional.response!.arms[1],
        ],
      },
    },
    { ...unsuccessful("failed"), response: conditional.response },
  ])("rejects partial or mismatched pairs %#", (value) => {
    expect(() => parseLab("ConditionalDetail", value)).toThrow();
  });
  it.each([
    { ...conditional, status: undefined },
    { ...conditional, scoring_status: "registered" },
    { ...conditional, trust_class: "ci" },
    { ...conditional, observed_model: "claimed-model" },
    { ...conditional, rank: 1 },
    { ...conditional, score: { reward: 1 } },
    { ...conditional, finished_at: "2026-02-30T00:00:00Z" },
    {
      ...conditional,
      contract: {
        ...conditional.contract,
        sources: [
          { ...conditional.contract.sources[0], url: "javascript:alert(1)" },
        ],
      },
    },
    {
      ...conditional,
      contract: {
        ...conditional.contract,
        shared_history: [
          {
            ...conditional.contract.shared_history[0],
            source_id: "missing-source",
          },
        ],
      },
    },
    {
      ...conditional,
      contract: {
        ...conditional.contract,
        outcome: {
          ...conditional.contract.outcome,
          release_date: "2026-02-30",
        },
      },
    },
  ])("refuses unsupported labels, claims and evidence %#", (value) => {
    expect(() => parseLab("ConditionalDetail", value)).toThrow();
  });
  it("refuses interval-seeded curves and summaries that disagree with native points", () => {
    const original = conditional.response!.reference;
    for (const distribution of [
      { ...original, provenance: "interval_seeded" },
      { ...original, transformVersion: "unsupported_version" },
      { ...original, summary: { ...original.summary, median: 6 } },
      { ...original, points: original.points.slice(1) },
    ])
      expect(() =>
        parseLab("ConditionalDetail", {
          ...conditional,
          response: { ...conditional.response!, reference: distribution },
        }),
      ).toThrow();
  });
  it("rejects a different attempt even if its detail is otherwise valid", async () => {
    const fetchImpl = async () =>
      new Response(JSON.stringify(conditional), {
        headers: { "content-type": "application/json" },
      });
    await expect(
      fetchLab(
        `/lab/conditionals/${ids.agent}`,
        "ConditionalDetail",
        undefined,
        fetchImpl,
      ),
    ).rejects.toThrow("different record");
  });
});
