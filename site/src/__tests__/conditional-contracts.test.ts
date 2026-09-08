import { describe, expect, it } from "vitest";
import { parseLab } from "@/lib/lab-schema";
import { fetchLab } from "@/app/lab/lab-client";
import { isLabApiPath } from "@/lib/lab-paths";
import {
  conditional,
  conditionalPage,
  expiredConditional,
  expiredSummary,
  reviewedOriginal,
  reviewedRevision,
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

  it("validates provider response provenance, both review bindings and the complete revision history", () => {
    expect(parseLab("ConditionalDetail", reviewedOriginal)).toBe(
      reviewedOriginal,
    );
    expect(parseLab("ConditionalDetail", reviewedRevision)).toBe(
      reviewedRevision,
    );
  });

  it.each([
    "review_attempt",
    "review_response",
    "review_source",
    "review_record",
    "review_outcome",
    "provider_artifact",
    "provider_verification",
    "history_parent",
    "history_contract",
    "history_evidence",
    "history_values",
    "history_provider",
    "history_duplicate",
    "history_association",
    "history_timestamp",
  ])("rejects an unsafe conditional annotation join: %s", (failure) => {
    const value = JSON.parse(JSON.stringify(reviewedRevision));
    switch (failure) {
      case "review_attempt":
        value.reviews[0].attempt_id = ids.agent;
        break;
      case "review_response":
        value.reviews[0].response_sha256 = ids.agent;
        break;
      case "review_source":
        value.reviews[0].findings[0].source_ids = ["unknown-source"];
        break;
      case "review_record":
        value.reviews[0].record_artifact.sha256 = ids.agent;
        value.reviews[0].record_artifact.download_path = `/artifacts/${ids.agent}`;
        break;
      case "review_outcome":
        value.reviews[0].outcome = "no_actionable_findings";
        break;
      case "provider_artifact":
        value.provider_metadata.source_artifact.sha256 = ids.agent;
        value.provider_metadata.source_artifact.download_path = `/artifacts/${ids.agent}`;
        break;
      case "provider_verification":
        value.provider_metadata.verification = "authenticated_model";
        break;
      case "history_parent":
        value.revision_history[1].parent_attempt_id = ids.agent;
        break;
      case "history_contract":
        value.revision_history[0].contract_id = ids.agent;
        break;
      case "history_evidence":
        value.revision_history[0].shared_evidence_id = ids.agent;
        break;
      case "history_values":
        value.revision_history[1].arm_quantiles[0].q50 = 7.5;
        break;
      case "history_provider":
        value.revision_history[1].provider_metadata.reported_model =
          "another-model";
        break;
      case "history_duplicate":
        value.revision_history.push(value.revision_history[0]);
        break;
      case "history_association":
        value.revision_history[1].association_basis = null;
        break;
      case "history_timestamp":
        value.revision_history[1].linked_at = "2026-02-30T00:00:00Z";
        break;
    }
    expect(() => parseLab("ConditionalDetail", value)).toThrow();
  });

  it("accepts only model filters on conditional collections while preserving closed record paths", () => {
    expect(
      isLabApiPath(
        "/lab/conditionals?limit=20&requested_model=models%2Fgemini-3.1-pro-preview",
      ),
    ).toBe(true);
    for (const path of [
      "/lab/conditionals?requested_model=",
      "/lab/conditionals?requested_model=model%20name",
      "/lab/conditionals?requested_model=model%0Ainjection",
      "/lab/conditionals?requested_model=" + "a".repeat(201),
      "/lab/conditionals?requested_model=a&requested_model=b",
      "/lab/conditionals?model=a",
      "/lab/forecasts?requested_model=a",
      `/lab/conditionals/${ids.task}?requested_model=a`,
      `/lab/conditionals?after=%33${ids.task.slice(1)}`,
      `/lab/%63onditionals/${ids.task}`,
    ])
      expect(isLabApiPath(path)).toBe(false);
  });

  it("rejects a filtered page containing a different requested model", async () => {
    const fetchImpl = async () => new Response(JSON.stringify(conditionalPage));
    await expect(
      fetchLab(
        "/lab/conditionals?requested_model=other-model",
        "ConditionalPage",
        undefined,
        fetchImpl,
      ),
    ).rejects.toThrow("different record");
    expect(() =>
      parseLab("ConditionalPage", { ...conditionalPage, requested_models: [] }),
    ).toThrow();
    expect(() =>
      parseLab("ConditionalPage", {
        ...conditionalPage,
        requested_models: [
          conditionalPage.requested_models[0],
          conditionalPage.requested_models[0],
        ],
      }),
    ).toThrow();
  });
});
