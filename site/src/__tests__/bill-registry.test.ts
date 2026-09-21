import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  loadBillDocket,
  loadBills,
  metricRegistryStatus,
  type BillDocketSeries,
  type BillMetric,
} from "@/data/bills";

const docket: BillDocketSeries[] = [
  {
    series: "agency.outcome.rate",
    ledger: { uuid: "admitted-uuid", concept: "agency.outcome.rate" },
  },
  { series: "agency.outcome.count" },
  { series: "agency.unique.total" },
];
const metric = (fields: Partial<BillMetric>): BillMetric => ({
  kind: "Outcome",
  text: "An official outcome measure.",
  ...fields,
});

describe("bill metric docket mapping", () => {
  it.each(["not-yet", "no-series", "unknown"])(
    "recomputes a stale %s assessment using the admitted series",
    (registry) => {
      const candidate = metric({ series_hint: "agency.outcome.rate", registry });
      const result = metricRegistryStatus(candidate, docket);
      expect(result).toMatchObject({
        status: "reachable",
        live: true,
        series: "agency.outcome.rate",
        ledger: docket[0].ledger,
      });
      expect(candidate.registry).toBe(registry);
    },
  );

  it("prefers an exact concept over its descendants", () => {
    const result = metricRegistryStatus(
      metric({ series_hint: "agency.outcome.rate" }),
      [...docket, { series: "agency.outcome.rate.subgroup" }],
    );
    expect(result.series).toBe("agency.outcome.rate");
  });

  it("accepts only an unambiguous dot-descendant", () => {
    expect(
      metricRegistryStatus(metric({ series_hint: "agency.unique" }), docket),
    ).toMatchObject({ status: "reachable", series: "agency.unique.total" });
    const result = metricRegistryStatus(
      metric({ series_hint: "agency.outcome", registry: "reachable" }),
      docket,
    );
    expect(result).toMatchObject({
      status: "ambiguous",
      candidates: ["agency.outcome.count", "agency.outcome.rate"],
    });
    expect(result.series).toBeUndefined();
    expect(result.ledger).toBeUndefined();
  });

  it("treats repeated periods of one canonical series and identity as one match", () => {
    const rows = [
      { ...docket[0], period: "2026" },
      { ...docket[0], period: "2027" },
    ];
    for (const series_hint of ["agency.outcome.rate", "agency.outcome"]) {
      expect(metricRegistryStatus(metric({ series_hint }), rows)).toMatchObject({
        status: "reachable",
        series: docket[0].series,
        ledger: docket[0].ledger,
      });
    }
  });

  it("refuses conflicting Chronicle identities for the same canonical series", () => {
    const result = metricRegistryStatus(
      metric({ series_hint: "agency.outcome.rate" }),
      [
        docket[0],
        {
          ...docket[0],
          ledger: { uuid: "conflicting-uuid", concept: "agency.outcome.rate" },
        },
      ],
    );
    expect(result.status).toBe("ambiguous");
    expect(result.note).toContain("conflicting Chronicle identities");
    expect(result.candidates).toEqual(["agency.outcome.rate"]);
    expect(result.ledger).toBeUndefined();
  });

  it("does not use a lexical prefix or infer a parent series from a child hint", () => {
    for (const series_hint of ["agency.outcome.rat", "agency.outcome.rate.child"]) {
      expect(metricRegistryStatus(metric({ series_hint }), docket).status).toBe(
        "not-yet",
      );
    }
  });

  it("does not turn a frozen reachable badge or proposed identity into admission", () => {
    const result = metricRegistryStatus(
      metric({
        series_hint: "unknown.outcome.rate",
        registry: "reachable",
        matched_series: "agency.outcome.rate",
        ledger_uuid: "proposed-uuid",
        mapping: { status: "reachable" },
      }),
      docket,
    );
    expect(result.status).toBe("not-yet");
    expect(result.note).toContain("Admission work");
    expect(result.series).toBeUndefined();
    expect(result.ledger).toBeUndefined();
  });

  it("uses docket identity rather than suggested Chronicle metadata", () => {
    expect(
      metricRegistryStatus(
        metric({
          series_hint: "agency.outcome.rate",
          matched_series: "some.other.concept",
          ledger_uuid: "proposed-uuid",
        }),
        docket,
      ).ledger,
    ).toEqual(docket[0].ledger);
  });

  it.each([undefined, "", "   "])(
    "leaves missing hint %j as visible mapping work regardless of its old badge",
    (series_hint) => {
      const result = metricRegistryStatus(
        metric({ series_hint, registry: "reachable" }),
        docket,
      );
      expect(result.status).toBe("unknown");
      expect(result.note).toContain("Mapping work");
    },
  );

  it("computes the default mapping from the checked-in docket", () => {
    const admitted = loadBillDocket().find((row) => row.ledger);
    expect(admitted).toBeDefined();
    expect(
      metricRegistryStatus(metric({ series_hint: admitted!.series })),
    ).toMatchObject({
      status: "reachable",
      series: admitted!.series,
      ledger: admitted!.ledger,
    });
  });
});

describe("bill artifact loading", () => {
  const tempDirs: string[] = [];
  afterEach(() => {
    for (const dir of tempDirs.splice(0)) fs.rmSync(dir, { recursive: true });
  });

  it("excludes mapped proposal sidecars instead of publishing duplicate bills", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "thesis-bills-"));
    tempDirs.push(dir);
    fs.writeFileSync(
      path.join(dir, "example.json"),
      JSON.stringify({
        bill: { name: "Example", analysisDate: "2026-09-21" },
        provisions: [],
      }),
    );
    // It must not even parse this proposal file as a bill artifact.
    fs.writeFileSync(path.join(dir, "example.mapped.json"), "not a bill");
    expect(loadBills(dir).map((bill) => bill.slug)).toEqual(["example"]);
  });
});
