import { describe, expect, it, vi } from "vitest";
import {
  buildScoreId,
  CHRONOLOGY_POLICY_VERSION,
  CONTRACT_BINDING_POLICY_VERSION,
  classifyPublicationProof,
  composeScoreChronology,
  scoreResolvedForecastRun,
  type ObservationRecordedLedgerEntry,
  type PolicyEngineLedgerEntry,
} from "@/data/thesis-log";
import {
  WITNESSED_CUSTODY_ROOTS,
  instantPrecedence,
  type WitnessedCustodyRootMap,
} from "@/data/witnessed-timeline";
import { WITNESSED_TIMELINE_SCHEMA_VERSION } from "@/data/witnessed-timeline.generated";
import type { ForecastCell } from "@/data/forecast-cells";
import { getForecastRunEntries } from "@/data/forecast-cells";
import type { TargetRegisteredLedgerEntry } from "@/data/ledger-targets";

// These fixtures test publication chronology after archive execution verification has succeeded.
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

// Re-audit N1: the headline chronology tier requires external witness proof
// from the record chain, not claimed timestamps. These tests pin the proof
// classifier, its composition with the claimed-time gate, and the join from
// predictionRun.custodyRootSha256 through to score chronology.

const COMPLETE_ROOT =
  "1111111111111111111111111111111111111111111111111111111111111111";
const LEGACY_ROOT =
  "2222222222222222222222222222222222222222222222222222222222222222";
const INELIGIBLE_COMPLETE_ROOT =
  "3333333333333333333333333333333333333333333333333333333333333333";

const FIXTURE_ROOTS: WitnessedCustodyRootMap = {
  [COMPLETE_ROOT]: {
    coverage: "direct",
    custodyInventoryVersion: 2,
    earliestWitnessedAt: "2026-07-10T06:06:00Z",
    headlineEligible: true,
    inventoryStatus: "complete",
    tsaGenTime: "2026-07-10T06:06:00Z",
    witnessDigest: "records/2026-07-10/digest-fixture.json",
  },
  [LEGACY_ROOT]: {
    coverage: "direct",
    custodyInventoryVersion: 1,
    earliestWitnessedAt: "2026-07-10T06:06:00Z",
    headlineEligible: false,
    inventoryStatus: "legacy-incomplete",
    tsaGenTime: "2026-07-10T06:06:00Z",
    witnessDigest: "records/2026-07-10/digest-fixture.json",
  },
  // Complete custody but not verifier-side headline eligible (e.g. a failed
  // or validation-incomplete analyst run): a witness proves when the bytes
  // existed, never that the run qualifies.
  [INELIGIBLE_COMPLETE_ROOT]: {
    coverage: "direct",
    custodyInventoryVersion: 2,
    earliestWitnessedAt: "2026-07-10T06:06:00Z",
    headlineEligible: false,
    inventoryStatus: "complete",
    tsaGenTime: "2026-07-10T06:06:00Z",
    witnessDigest: "records/2026-07-10/digest-fixture.json",
  },
};

describe("publication proof classifier", () => {
  const afterWitness = "2026-08-01T12:00:00Z";

  it("witnesses a complete, eligible root witnessed before the observation", () => {
    const proof = classifyPublicationProof(
      COMPLETE_ROOT,
      afterWitness,
      FIXTURE_ROOTS,
    );
    expect(proof.status).toBe("witnessed");
    expect(proof.earliestWitnessedAt).toBe("2026-07-10T06:06:00Z");
    expect(proof.headlineEligible).toBe(true);
    expect(proof.inventoryStatus).toBe("complete");
    expect(proof.witnessDigest).toBe("records/2026-07-10/digest-fixture.json");
  });

  it("rejects a witness at or after the observation", () => {
    expect(
      classifyPublicationProof(
        COMPLETE_ROOT,
        "2026-07-10T06:06:00Z",
        FIXTURE_ROOTS,
      ).status,
    ).toBe("witness_not_before_observation");
    expect(
      classifyPublicationProof(
        COMPLETE_ROOT,
        "2026-06-15T00:00:00Z",
        FIXTURE_ROOTS,
      ).status,
    ).toBe("witness_not_before_observation");
  });

  it("treats same-day witness/observation ambiguity as unproven", () => {
    // Date-only observation on the witness day: sub-day order unknowable.
    expect(
      classifyPublicationProof(COMPLETE_ROOT, "2026-07-10", FIXTURE_ROOTS)
        .status,
    ).toBe("witness_not_before_observation");
  });

  it("never passes a legacy-incomplete or ineligible root", () => {
    expect(
      classifyPublicationProof(LEGACY_ROOT, afterWitness, FIXTURE_ROOTS).status,
    ).toBe("root_not_headline_eligible");
    expect(
      classifyPublicationProof(
        INELIGIBLE_COMPLETE_ROOT,
        afterWitness,
        FIXTURE_ROOTS,
      ).status,
    ).toBe("root_not_headline_eligible");
  });

  it("treats timeline absence as unproven chronology", () => {
    const proof = classifyPublicationProof(
      "4444444444444444444444444444444444444444444444444444444444444444",
      afterWitness,
      FIXTURE_ROOTS,
    );
    expect(proof.status).toBe("root_not_in_timeline");
    expect(proof.earliestWitnessedAt).toBeNull();
  });

  it("treats a missing custody root as unproven chronology", () => {
    expect(
      classifyPublicationProof(undefined, afterWitness, FIXTURE_ROOTS).status,
    ).toBe("no_custody_root");
  });

  it("never reads inherited object properties as roots", () => {
    expect(
      classifyPublicationProof("constructor", afterWitness, FIXTURE_ROOTS)
        .status,
    ).toBe("root_not_in_timeline");
  });
});

describe("chronology composition", () => {
  const witnessed = classifyPublicationProof(
    COMPLETE_ROOT,
    "2026-08-01T12:00:00Z",
    FIXTURE_ROOTS,
  );
  const unproven = classifyPublicationProof(
    undefined,
    "2026-08-01T12:00:00Z",
    FIXTURE_ROOTS,
  );

  it("upgrades claimed-time-verified to witness-verified only with proof", () => {
    expect(composeScoreChronology("claimed_time_verified", witnessed)).toBe(
      "witness_verified",
    );
    expect(composeScoreChronology("claimed_time_verified", unproven)).toBe(
      "claimed_time_verified",
    );
  });

  it("never rescues unverified or violated claimed chronology", () => {
    expect(composeScoreChronology("unverified", witnessed)).toBe("unverified");
    expect(composeScoreChronology("violated", witnessed)).toBe("violated");
  });
});

describe("witness precedence primitive", () => {
  it("orders explicit instants strictly", () => {
    expect(
      instantPrecedence("2026-07-10T06:06:00Z", "2026-07-10T06:06:01Z"),
    ).toBe("before");
    expect(
      instantPrecedence("2026-07-10T06:06:00Z", "2026-07-10T06:06:00Z"),
    ).toBe("not_before");
  });

  it("falls back to written-day granularity without explicit offsets", () => {
    expect(instantPrecedence("2026-07-09T23:00:00Z", "2026-07-10")).toBe(
      "before",
    );
    expect(instantPrecedence("2026-07-10T00:00:00Z", "2026-07-10")).toBe(
      "unknown",
    );
    expect(instantPrecedence("2026-07-11T00:00:00Z", "2026-07-10")).toBe(
      "not_before",
    );
  });
});

describe("bundled witnessed timeline", () => {
  it("carries the expected schema and verifier invariants", () => {
    expect(WITNESSED_TIMELINE_SCHEMA_VERSION).toBe(
      "thesis_witnessed_timeline_v1",
    );
    const entries = Object.entries(WITNESSED_CUSTODY_ROOTS);
    expect(entries.length).toBeGreaterThan(0);
    for (const [sha, entry] of entries) {
      expect(sha).toMatch(/^[0-9a-f]{64}$/);
      expect(["direct", "transitive"]).toContain(entry.coverage);
      expect(entry.earliestWitnessedAt).toMatch(/Z$/);
      expect(entry.witnessDigest).toMatch(/^records\//);
      // Mirrors the extractor's invariants: legacy inventories are never
      // headline eligible, and eligibility implies completeness.
      if (entry.inventoryStatus === "legacy-incomplete") {
        expect(entry.headlineEligible).toBe(false);
      }
      if (entry.headlineEligible) {
        expect(entry.inventoryStatus).toBe("complete");
      }
    }
  });

  it("contains both witnessed-complete and legacy-incomplete roots", () => {
    const entries = Object.values(WITNESSED_CUSTODY_ROOTS);
    expect(
      entries.some(
        (entry) =>
          entry.inventoryStatus === "complete" && entry.headlineEligible,
      ),
    ).toBe(true);
    expect(
      entries.some((entry) => entry.inventoryStatus === "legacy-incomplete"),
    ).toBe(true);
  });
});

describe("witness tier through the scoring pipeline", () => {
  const realWitnessedRoot = Object.entries(WITNESSED_CUSTODY_ROOTS).find(
    ([, entry]) =>
      entry.inventoryStatus === "complete" &&
      entry.headlineEligible &&
      entry.earliestWitnessedAt < "2026-08-01T00:00:00Z",
  )?.[0];
  if (!realWitnessedRoot) {
    throw new Error(
      "expected a witnessed, headline-eligible custody root in the timeline",
    );
  }

  const cell = (custodyRootSha256?: string): ForecastCell => ({
    slug: "witness-tier-cell",
    country: "US",
    type: "data",
    title: "Witness tier",
    question: "?",
    unit: "percent",
    pointEstimate: 2,
    ciLow: 1,
    ciHigh: 3,
    confidence: 0.8,
    resolutionDate: "2026-08-01",
    resolutionSource: "Test",
    resolutionRule: "Test",
    dataPointId: "test.witness.series.2026",
    historicalContext: [],
    drivers: [],
    predictionRun: {
      kind: "recorded-agent-run",
      runAt: "2026-04-11T00:00:00Z",
      agent: "test.agent",
      model: "test-model",
      sourceContext: [],
      custodyRootSha256,
    },
    reasoning: [{ kind: "forecast", point: 2, ciLow: 1, ciHigh: 3 }],
  });

  const target: TargetRegisteredLedgerEntry = {
    kind: "target_registered",
    dataPointId: "test.witness.series.2026",
    observationId: "obs.test.witness.series.2026",
    country: "US",
    periodLabel: "2026",
    unit: "percent",
    resolutionDate: "2026-08-01",
    resolutionSource: "Test",
    resolutionRule: "Test",
    resolutionPolicy: "first_print",
    sourceKind: "official_release",
    source: "Test",
    note: "fixture",
    registeredAt: "2026-04-10T00:00:00Z",
  };

  const observationAt = (
    observedAt: string,
  ): ObservationRecordedLedgerEntry => ({
    kind: "observation_recorded",
    observationId: "obs.test.witness.series.2026",
    dataPointId: "test.witness.series.2026",
    periodLabel: "2026",
    unit: "percent",
    value: 2.4,
    observedAt,
    resolvedAt: observedAt,
    sourceKind: "official_release",
    source: "Test",
  });

  const score = (forecast: ForecastCell, observedAt: string) => {
    const ledger: PolicyEngineLedgerEntry[] = [
      target,
      observationAt(observedAt),
    ];
    const run = getForecastRunEntries(forecast)[0];
    return scoreResolvedForecastRun(forecast, run, ledger);
  };

  it("awards witness_verified only with a witnessed root before the observation", () => {
    const witnessed = score(cell(realWitnessedRoot), "2026-08-01T12:00:00Z");
    expect(witnessed?.chronology).toBe("witness_verified");
    expect(witnessed?.chronologyProof.status).toBe("witnessed");
    expect(witnessed?.chronologyProof.custodyRootSha256).toBe(
      realWitnessedRoot,
    );
    expect(witnessed?.scoreId).toContain("numeric_cdf_crps_v3_ledger_scale");
  });

  it("keeps a run without proof at claimed_time_verified", () => {
    const noRoot = score(cell(undefined), "2026-08-01T12:00:00Z");
    expect(noRoot?.chronology).toBe("claimed_time_verified");
    expect(noRoot?.chronologyProof.status).toBe("no_custody_root");

    const fabricated = score(
      cell("4444444444444444444444444444444444444444444444444444444444444444"),
      "2026-08-01T12:00:00Z",
    );
    expect(fabricated?.chronology).toBe("claimed_time_verified");
    expect(fabricated?.chronologyProof.status).toBe("root_not_in_timeline");
  });

  it("keeps a run whose root was witnessed after the observation out of the headline", () => {
    const lateWitness = score(cell(realWitnessedRoot), "2026-06-15T00:00:00Z");
    expect(lateWitness?.chronology).toBe("claimed_time_verified");
    expect(lateWitness?.chronologyProof.status).toBe(
      "witness_not_before_observation",
    );
  });

  it("commits the score ID to the chronology tier and policy version", () => {
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
      chronologyPolicy: CHRONOLOGY_POLICY_VERSION,
      contractBinding: "contract_bound",
      contractBindingPolicy: CONTRACT_BINDING_POLICY_VERSION,
      conditionId: null,
      conditionStatus: null,
    };
    expect(buildScoreId(payload)).not.toBe(
      buildScoreId({ ...payload, chronology: "claimed_time_verified" }),
    );
    expect(buildScoreId(payload)).not.toBe(
      buildScoreId({
        ...payload,
        chronologyPolicy: "chronology_v3_explicit_instants",
      }),
    );
    // The contract-binding verdict is score identity for the same reason
    // the chronology verdict is: it changes what the number means.
    expect(buildScoreId(payload)).not.toBe(
      buildScoreId({ ...payload, contractBinding: "legacy_unbound" }),
    );
    expect(CHRONOLOGY_POLICY_VERSION).toBe(
      "chronology_v4_witnessed_publication",
    );
  });
});
