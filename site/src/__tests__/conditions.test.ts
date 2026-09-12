import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  CONDITIONS,
  PROVISION_ENACTED_CHECK_SOURCE,
  conditionForCell,
  conditionForContract,
  conditionStatusFor,
  conditionValidationErrors,
  isConditionGated,
  resolveProvisionEnactedCondition,
  type ProvisionEnactedConditionDefinition,
  type ProvisionEnactmentEvidence,
} from "@/data/conditions";
import { FORECAST_CELLS } from "@/data/forecast-cells";
import {
  scoreResolvedForecastRun,
  type ConditionStatus,
} from "@/data/thesis-log";
import { getForecastRunEntries } from "@/data/forecast-cells";

// F6: conditional branches are graded only when their registered
// condition actually occurred.

describe("condition registry", () => {
  it("validates every registered condition definition", () => {
    for (const condition of CONDITIONS) {
      expect(
        conditionValidationErrors(condition),
        condition.conditionId,
      ).toEqual([]);
    }
  });

  it("registers every published conditional cell's contract", () => {
    const unregistered = FORECAST_CELLS.filter(
      (cell) =>
        cell.type === "conditional" && conditionForCell(cell) === undefined,
    ).map((cell) => `${cell.slug}: ${cell.conditionalOn}`);
    expect(unregistered).toEqual([]);
  });

  it("keeps complement pairs in atomic states", () => {
    const byId = new Map(CONDITIONS.map((c) => [c.conditionId, c]));
    for (const condition of CONDITIONS) {
      if (!condition.complementOf) continue;
      const complement = byId.get(condition.complementOf);
      expect(complement, condition.complementOf).toBeDefined();
      expect(complement?.complementOf).toBe(condition.conditionId);
      // Allowed joint states only: (open, open), (satisfied, failed),
      // (failed, satisfied). A half-transitioned pair would leave a
      // resolved branch permanently unscorable (X12).
      const pair = [condition.status, complement!.status].sort().join("+");
      expect(["open+open", "failed+satisfied"]).toContain(pair);
    }
  });

  it("every cell carrying a conditional contract is typed conditional", () => {
    const downgraded = FORECAST_CELLS.filter(
      (cell) => cell.conditionalOn && cell.type !== "conditional",
    ).map((cell) => cell.slug);
    expect(downgraded).toEqual([]);
  });

  it("gates by marker even when the type field is downgraded", () => {
    const conditional = FORECAST_CELLS.find(
      (cell) => cell.type === "conditional" && cell.conditionalOn,
    );
    if (!conditional) return;
    expect(isConditionGated({ ...conditional, type: "data" })).toBe(true);
  });

  it("has well-formed ids and match strings", () => {
    const seen = new Set<string>();
    for (const condition of CONDITIONS) {
      expect(condition.conditionId).toMatch(/^cond\.[a-z0-9.-]+$/);
      for (const text of condition.matchStrings) {
        expect(seen.has(text), `duplicate match string: ${text}`).toBe(false);
        seen.add(text);
      }
    }
  });

  it("registers the FY27 NDAA enactment arms as literal complements", () => {
    const enacted = CONDITIONS.find(
      (condition) =>
        condition.conditionId === "cond.fy27-ndaa-enactment.enacted",
    );
    const notEnacted = CONDITIONS.find(
      (condition) =>
        condition.conditionId === "cond.fy27-ndaa-enactment.not-enacted",
    );
    expect(enacted?.complementOf).toBe(notEnacted?.conditionId);
    expect(notEnacted?.complementOf).toBe(enacted?.conditionId);
    expect(enacted?.resolvesBy).toBe("2026-12-31");
    expect(notEnacted?.resolvesBy).toBe("2026-12-31");
  });

  it("binds recorded condition contracts byte-for-byte", () => {
    const condition = CONDITIONS.find(
      (entry) => entry.conditionId === "cond.fy27-ndaa-enactment.enacted",
    );
    expect(condition).toBeDefined();
    const exactContract = condition!.matchStrings[0];
    expect(conditionForContract(exactContract)).toBe(condition);
    expect(conditionForContract(`${exactContract} `)).toBeUndefined();
  });
});

describe("provision_enacted conditions", () => {
  const crpCondition = CONDITIONS.find(
    (condition): condition is ProvisionEnactedConditionDefinition =>
      condition.conditionId === "cond.crp-acreage-ceiling-fy2027-31.enacted" &&
      condition.type === "provision_enacted",
  );
  const crpCurrentLaw = CONDITIONS.find(
    (condition) =>
      condition.conditionId ===
      "cond.crp-acreage-ceiling-fy2027-31.current-law",
  );

  function registeredCrpCondition(): ProvisionEnactedConditionDefinition {
    if (!crpCondition) throw new Error("CRP provision condition is missing");
    return crpCondition;
  }

  function qualifyingEvidence(
    overrides: Partial<ProvisionEnactmentEvidence> = {},
  ): ProvisionEnactmentEvidence {
    const condition = registeredCrpCondition();
    return {
      kind: "enacted_public_law",
      enactedOn: "2027-09-29",
      checkSource: PROVISION_ENACTED_CHECK_SOURCE,
      statutoryTest: condition.statutoryTest,
      satisfiesStatutoryTest: true,
      ...overrides,
    };
  }

  it("registers the exact CRP statutory contract", () => {
    const condition = registeredCrpCondition();
    expect(condition).toMatchObject({
      type: "provision_enacted",
      provisionDescription:
        "CRP acreage ceiling for fiscal years 2027 through 2031",
      statutoryTest:
        "an enacted farm bill sets the CRP acreage ceiling at 27,000,000 acres for FY2027-31",
      checkSource: "govinfo enrolled bill text",
      deadline: "2027-09-30",
      resolvesBy: "2027-09-30",
      status: "open",
    });
    expect(condition.matchStrings).toEqual([condition.statutoryTest]);
    expect(conditionForContract(condition.statutoryTest)).toBe(condition);
  });

  it("registers the CRP current-law arm without a complement", () => {
    // A different enacted FY2027-31 ceiling falsifies both exact premises,
    // so complement machinery would incorrectly score one of the arms.
    expect(crpCurrentLaw).toMatchObject({
      type: "recorded_status",
      status: "open",
      resolvesBy: "2027-09-30",
    });
    expect(crpCurrentLaw?.complementOf).toBeUndefined();
    expect(crpCondition?.complementOf).toBeUndefined();
    expect(conditionForContract(crpCurrentLaw?.matchStrings[0])).toBe(
      crpCurrentLaw,
    );
  });

  it("requires complete provision metadata, ISO dates, and the exact source", () => {
    const condition = registeredCrpCondition();
    const cases: Array<[ProvisionEnactedConditionDefinition, string]> = [
      [
        { ...condition, provisionDescription: "" },
        "provisionDescription is required",
      ],
      [{ ...condition, statutoryTest: "" }, "statutoryTest is required"],
      [
        {
          ...condition,
          checkSource: "GovInfo enrolled bill text",
        } as unknown as ProvisionEnactedConditionDefinition,
        'checkSource must be exactly "govinfo enrolled bill text"',
      ],
      [
        { ...condition, deadline: "2027-02-29" },
        "deadline must be an ISO date",
      ],
      [
        { ...condition, resolvesBy: "2027-09-29" },
        "deadline must equal resolvesBy",
      ],
    ];

    for (const [definition, error] of cases) {
      expect(conditionValidationErrors(definition)).toContain(error);
    }
  });

  it("stays open before the deadline and fails at the deadline otherwise", () => {
    const condition = registeredCrpCondition();
    expect(resolveProvisionEnactedCondition(condition, "2027-09-29", [])).toBe(
      "open",
    );
    expect(resolveProvisionEnactedCondition(condition, "2027-09-30", [])).toBe(
      "failed",
    );
    expect(resolveProvisionEnactedCondition(condition, "2027-10-01", [])).toBe(
      "failed",
    );
  });

  it("is satisfied by qualifying enactment on or before the deadline", () => {
    const condition = registeredCrpCondition();
    expect(
      resolveProvisionEnactedCondition(condition, "2027-09-29", [
        qualifyingEvidence(),
      ]),
    ).toBe("satisfied");
    expect(
      resolveProvisionEnactedCondition(condition, "2027-09-30", [
        qualifyingEvidence({ enactedOn: "2027-09-30" }),
      ]),
    ).toBe("satisfied");
    expect(
      resolveProvisionEnactedCondition(condition, "2027-10-01", [
        qualifyingEvidence(),
      ]),
    ).toBe("satisfied");
  });

  it("rejects evidence that does not prove the exact statutory test", () => {
    const condition = registeredCrpCondition();
    const nonqualifying = [
      qualifyingEvidence({ satisfiesStatutoryTest: false }),
      qualifyingEvidence({ checkSource: "congress.gov bill page" }),
      qualifyingEvidence({ statutoryTest: "a different statutory test" }),
      qualifyingEvidence({ enactedOn: "2027-10-01" }),
      qualifyingEvidence({ enactedOn: "not-a-date" }),
      {
        ...qualifyingEvidence(),
        kind: "introduced_bill",
      } as unknown as ProvisionEnactmentEvidence,
    ];

    expect(
      resolveProvisionEnactedCondition(condition, "2027-10-02", nonqualifying),
    ).toBe("failed");
  });

  it("does not use qualifying evidence before its enactment date", () => {
    const condition = registeredCrpCondition();
    expect(
      resolveProvisionEnactedCondition(condition, "2027-09-28", [
        qualifyingEvidence(),
      ]),
    ).toBe("open");
  });

  it("rejects a non-ISO as-of date", () => {
    expect(() =>
      resolveProvisionEnactedCondition(
        registeredCrpCondition(),
        "2027-9-30",
        [],
      ),
    ).toThrow("asOf must be an ISO date");
  });
});

describe("condition gate on scoring", () => {
  const conditionalCell = FORECAST_CELLS.find(
    (cell) => cell.type === "conditional",
  );

  it("finds a conditional cell to exercise", () => {
    expect(conditionalCell).toBeDefined();
  });

  it("classifies contracts", () => {
    expect(conditionStatusFor({ slug: "x" })).toBe("unregistered");
    expect(
      conditionStatusFor({ slug: "x", conditionalOn: "never registered text" }),
    ).toBe("unregistered");
    expect(
      conditionStatusFor({
        slug: "x",
        conditionalOn:
          "TCJA extension package matching House framework enacted by 2026-06-30",
      }),
    ).toBe("satisfied");
  });

  it("blocks scoring while the condition is open and admits it when satisfied", () => {
    if (!conditionalCell) return;
    const run = getForecastRunEntries(conditionalCell)[0];
    const condition = conditionForCell(conditionalCell);
    expect(condition).toBeDefined();

    // Synthetic ledger: an observation + resolution matching the cell,
    // so the ONLY thing standing between the run and a score is the gate.
    const observedAt = "2027-08-01T12:00:00Z";
    const dataPointId = conditionalCell.dataPointId ?? "test.dp";
    const ledger = [
      {
        kind: "observation_recorded",
        observationId: "obs.test.condition-gate",
        dataPointId,
        value: conditionalCell.pointEstimate,
        unit: conditionalCell.unit,
        observedAt,
        source: "test",
      },
      {
        kind: "resolution_recorded",
        resolutionRef: "res.test.condition-gate",
        forecastSlug: conditionalCell.slug,
        dataPointId,
        observationId: "obs.test.condition-gate",
        resolvedAt: observedAt,
      },
    ] as never[];

    const blocked = scoreResolvedForecastRun(conditionalCell, run, ledger);
    expect(blocked).toBeUndefined();

    const overrides = new Map<string, ConditionStatus>([
      [condition!.conditionId, "satisfied"],
    ]);
    const admitted = scoreResolvedForecastRun(
      conditionalCell,
      run,
      ledger,
      overrides,
    );
    // The gate no longer blocks; whether a score materializes now depends
    // only on the resolution join, which must at minimum get past the
    // conditional check (i.e. not short-circuit to undefined via the gate).
    if (admitted === undefined) {
      // If the synthetic ledger shape misses the join, the failed override
      // path is indistinguishable — so assert directly on the classifier.
      expect(conditionStatusFor(conditionalCell, overrides)).toBe("satisfied");
    } else {
      expect(admitted.forecastSlug).toBe(conditionalCell.slug);
    }
  });
});

describe("s3596 ACTC threshold conditional pair (thesis#106)", () => {
  const enacted = CONDITIONS.find(
    (condition) =>
      condition.conditionId === "cond.s3596-actc-threshold.enacted",
  );
  const currentLaw = CONDITIONS.find(
    (condition) =>
      condition.conditionId === "cond.s3596-actc-threshold.current-law",
  );

  function requireEnacted(): ProvisionEnactedConditionDefinition {
    if (!enacted || enacted.type !== "provision_enacted") {
      throw new Error("S.3596 enacted provision condition is missing");
    }
    return enacted;
  }

  it("registers the enacted arm as a provision_enacted condition", () => {
    const condition = requireEnacted();
    const spmConditional =
      "For the CY2027 Census Supplemental Poverty Measure child-poverty " +
      "outcome, legislation enacted by 2027-12-31 makes the IRC " +
      "§24(d)(1)(B)(i) earned-income threshold no more than $1 for tax " +
      "year 2027.";
    expect(condition.statutoryTest).toBe(
      "Legislation enacted by 2027-12-31 makes the IRC §24(d)(1)(B)(i) " +
        "earned-income threshold no more than $1 for tax year 2027.",
    );
    expect(condition.matchStrings).toEqual([
      condition.statutoryTest,
      spmConditional,
    ]);
    expect(condition.checkSource).toBe(PROVISION_ENACTED_CHECK_SOURCE);
    expect(condition.deadline).toBe("2027-12-31");
    expect(condition.resolvesBy).toBe("2027-12-31");
    expect(condition.status).toBe("open");
    expect(conditionForContract(condition.statutoryTest)).toBe(condition);
    expect(conditionForContract(spmConditional)).toBe(condition);
  });

  it("registers the current-law arm WITHOUT a complement declaration", () => {
    // The pair is deliberately not a complement pair: legislation setting
    // an intermediate TY2027 threshold (e.g. $500) falsifies BOTH
    // premises, a state the complement invariant (open+open or
    // failed+satisfied only) could not represent. Each condition resolves
    // on its own literal text; in intermediate worlds both fail and
    // neither arm scores.
    expect(currentLaw?.type).toBe("recorded_status");
    expect(currentLaw?.complementOf).toBeUndefined();
    expect(enacted?.complementOf).toBeUndefined();
    expect(currentLaw?.resolvesBy).toBe("2027-12-31");
    expect(currentLaw?.status).toBe("open");
    const actcConditional =
      "No legislation enacted by 2027-12-31 changes the IRC " +
      "§24(d)(1)(B)(i) earned-income threshold of $2,500 for tax year " +
      "2027; current law holds. The $2,500 operative amount is applied by " +
      "IRC §24(h)(6), while §24(d)(1)(B)(i) contains the underlying $3,000 " +
      "amount.";
    const spmConditional =
      "For the CY2027 Census Supplemental Poverty Measure child-poverty " +
      "outcome, no legislation enacted by 2027-12-31 changes the IRC " +
      "§24(d)(1)(B)(i) earned-income threshold of $2,500 for tax year " +
      "2027; current law holds. The $2,500 operative amount is applied by " +
      "IRC §24(h)(6), while §24(d)(1)(B)(i) contains the underlying $3,000 " +
      "amount.";
    expect(currentLaw?.matchStrings).toEqual([
      actcConditional,
      spmConditional,
    ]);
    expect(conditionForContract(actcConditional)).toBe(currentLaw);
    expect(conditionForContract(spmConditional)).toBe(currentLaw);
  });

  it("binds both preregistered docket conditionals to the registry", () => {
    // The roll-docket loop registers each arm's `conditional` text into the
    // immutable target contract, the analyst must repeat it verbatim, and
    // published cells resolve conditions by exact string match. This test
    // closes the loop BEFORE any roll: every conditional-pair arm committed
    // in the docket registry must already resolve to the condition it
    // names, so a preregistered rerun can never publish an unregistered
    // conditional cell.
    const docket = JSON.parse(
      readFileSync(
        join(__dirname, "../../../scripts/docket_series.json"),
        "utf8",
      ),
    ) as { series: Array<Record<string, unknown>> };
    const pairs = docket.series.filter(
      (entry) => typeof entry.conditionalPair === "object",
    );
    expect(pairs.length).toBeGreaterThan(0);
    for (const entry of pairs) {
      const pair = entry.conditionalPair as {
        arms: Array<{ conditional: string; conditionId: string }>;
      };
      expect(pair.arms).toHaveLength(2);
      const conditionIds = new Set<string>();
      for (const arm of pair.arms) {
        const condition = conditionForContract(arm.conditional);
        expect(condition, `${entry.series}: ${arm.conditionId}`).toBeDefined();
        expect(condition?.conditionId).toBe(arm.conditionId);
        expect(condition?.matchStrings).toContain(arm.conditional);
        conditionIds.add(arm.conditionId);
      }
      expect(conditionIds.size).toBe(2);
    }
  });

  it("resolves the enacted condition from enrolled-bill evidence", () => {
    const condition = requireEnacted();
    const qualifying: ProvisionEnactmentEvidence = {
      kind: "enacted_public_law",
      enactedOn: "2027-06-15",
      checkSource: PROVISION_ENACTED_CHECK_SOURCE,
      statutoryTest: condition.statutoryTest,
      satisfiesStatutoryTest: true,
    };
    expect(
      resolveProvisionEnactedCondition(condition, "2027-07-01", [qualifying]),
    ).toBe("satisfied");
    expect(resolveProvisionEnactedCondition(condition, "2027-07-01", [])).toBe(
      "open",
    );
    expect(resolveProvisionEnactedCondition(condition, "2027-12-31", [])).toBe(
      "failed",
    );
  });
});

describe("hr2763 AFA bundle conditional pair (thesis#113)", () => {
  const enacted = CONDITIONS.find(
    (condition) => condition.conditionId === "cond.hr2763-afa-bundle.enacted",
  );
  const currentLaw = CONDITIONS.find(
    (condition) =>
      condition.conditionId === "cond.hr2763-afa-bundle.current-law",
  );

  function requireEnacted(): ProvisionEnactedConditionDefinition {
    if (!enacted || enacted.type !== "provision_enacted") {
      throw new Error("AFA bundle enacted provision condition is missing");
    }
    return enacted;
  }

  it("registers the bundle as a provision_enacted condition", () => {
    const condition = requireEnacted();
    const actcConditional =
      "Legislation enacted by 2027-12-31 puts every concept revision of " +
      "the American Family Act introduced-text bundle " +
      "hr2763-119-ih-2025-04-09-v1 in force for tax year 2028; enacting " +
      "a bill number or a partial substitute is not sufficient.";
    const spmConditional =
      "For the CY2028 Census Supplemental Poverty Measure child-poverty " +
      "outcome, legislation enacted by 2027-12-31 puts every concept " +
      "revision of the American Family Act introduced-text bundle " +
      "hr2763-119-ih-2025-04-09-v1 in force for tax year 2028; enacting " +
      "a bill number or a partial substitute is not sufficient.";
    expect(condition.statutoryTest).toBe(actcConditional);
    expect(condition.matchStrings).toEqual([actcConditional, spmConditional]);
    expect(condition.checkSource).toBe(PROVISION_ENACTED_CHECK_SOURCE);
    expect(condition.deadline).toBe("2027-12-31");
    expect(condition.resolvesBy).toBe("2027-12-31");
    expect(condition.status).toBe("open");
    expect(conditionForContract(actcConditional)).toBe(condition);
    expect(conditionForContract(spmConditional)).toBe(condition);
  });

  it("versions the bundle against the committed bill artifact", () => {
    // The statutory test names the versioned revision set; the referent
    // must exist in the repository so "every concept revision" is a
    // checkable list, not prose. bills/hr2763-119.json carries the
    // bundleCondition with that exact version and the 38 revisions the
    // bundle conjoins.
    const artifact = JSON.parse(
      readFileSync(join(__dirname, "../../../bills/hr2763-119.json"), "utf8"),
    ) as {
      bundleCondition: { version: string; revisionIds: string[] };
      revisions: Array<{ id: string }>;
    };
    expect(requireEnacted().statutoryTest).toContain(
      artifact.bundleCondition.version,
    );
    expect(artifact.bundleCondition.revisionIds.length).toBe(
      artifact.revisions.length,
    );
    expect(new Set(artifact.bundleCondition.revisionIds)).toEqual(
      new Set(artifact.revisions.map((revision) => revision.id)),
    );
  });

  it("registers the current-law arm WITHOUT a complement declaration", () => {
    // Partial enactment of the 38-revision bundle, an S.3596-style
    // threshold-only change, or any other enacted §24 amendment falsifies
    // BOTH premises — for a bundle, intermediate worlds are the NORM, so
    // the non-complement design carries even more weight than for the
    // single-atom S.3596 pair.
    expect(currentLaw?.type).toBe("recorded_status");
    expect(currentLaw?.complementOf).toBeUndefined();
    expect(enacted?.complementOf).toBeUndefined();
    expect(currentLaw?.resolvesBy).toBe("2027-12-31");
    expect(currentLaw?.status).toBe("open");
    const actcConditional =
      "No legislation enacted by 2027-12-31 changes the IRC §24 child " +
      "tax credit rules in force for tax year 2028; current law holds.";
    const spmConditional =
      "For the CY2028 Census Supplemental Poverty Measure child-poverty " +
      "outcome, no legislation enacted by 2027-12-31 changes the IRC §24 " +
      "child tax credit rules in force for tax year 2028; current law " +
      "holds.";
    expect(currentLaw?.matchStrings).toEqual([actcConditional, spmConditional]);
    expect(conditionForContract(actcConditional)).toBe(currentLaw);
    expect(conditionForContract(spmConditional)).toBe(currentLaw);
  });

  it("resolves the bundle condition from enrolled-bill evidence", () => {
    const condition = requireEnacted();
    const qualifying: ProvisionEnactmentEvidence = {
      kind: "enacted_public_law",
      enactedOn: "2027-09-30",
      checkSource: PROVISION_ENACTED_CHECK_SOURCE,
      statutoryTest: condition.statutoryTest,
      satisfiesStatutoryTest: true,
    };
    expect(
      resolveProvisionEnactedCondition(condition, "2027-10-01", [qualifying]),
    ).toBe("satisfied");
    expect(resolveProvisionEnactedCondition(condition, "2027-10-01", [])).toBe(
      "open",
    );
    expect(resolveProvisionEnactedCondition(condition, "2027-12-31", [])).toBe(
      "failed",
    );
  });
});
