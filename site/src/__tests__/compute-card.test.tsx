import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import fixture from "../../../tests/fixtures/compute_publishability_cases.json";
import { ComputeCard } from "@/components/ComputeCard";
import { type BillCompute, loadBills } from "@/data/bills";
import { isPublishableCompute } from "@/lib/compute-publishability";

/**
 * POLICYENGINE.md §0.2: a run whose certification is not certified is
 * inadmissible for a published number. Motivated by S.3596 (2026-07-31 to
 * 2026-10-22): the bill page showed −$1.83B / −$17.1B under an "uncertified
 * pairing" chip as "claimed-tier evidence", which the contract forbids.
 * The fixture is shared with tests/test_compute_publication_gate.py so the
 * site gate and attach_compute's Python gate cannot drift apart.
 */
const cases = fixture.cases as unknown as {
  name: string;
  publishable: boolean;
  row: BillCompute;
}[];

const FIGURE_TEXT = ["−$1.83B", "−$17.1B", "Child poverty", "People gaining", "FIGURE-SUMMARY", "FIGURE-NOTE"];

describe("compute publication gate", () => {
  it("covers both verdicts", () => {
    expect(new Set(cases.map((c) => c.publishable))).toEqual(new Set([true, false]));
  });

  for (const c of cases) {
    it(`${c.publishable ? "publishes" : "withholds"}: ${c.name}`, () => {
      expect(isPublishableCompute(c.row)).toBe(c.publishable);
      const { container, unmount } = render(<ComputeCard row={c.row} />);
      const text = container.textContent ?? "";
      if (c.publishable) {
        for (const figure of FIGURE_TEXT) expect(text).toContain(figure);
        expect(text).toContain("certified pairing");
        expect(text).not.toContain("uncertified pairing");
        expect(text).not.toContain("Figures withheld");
      } else {
        // No figure of any kind: stats, summary and note are all withheld,
        // and nothing else on a withheld card carries a dollar amount.
        for (const figure of FIGURE_TEXT) expect(text).not.toContain(figure);
        expect(text).not.toContain("$");
        expect(text).toContain("uncertified pairing");
        expect(text).toContain("Figures withheld");
        // Provenance still shows: the run is listed, never silently dropped.
        expect(text).toContain("Reform parameters");
        expect(text).toContain("policyengine-us");
      }
      unmount();
    });
  }

  it("shows the certification's own reason when it refuses", () => {
    const refused = cases.find((c) => c.row.certification?.warning)!;
    const { container } = render(<ComputeCard row={refused.row} />);
    expect(container.textContent).toContain(refused.row.certification!.warning!);
  });
});

describe("published bill compute rows", () => {
  const rows = loadBills().flatMap((bill) =>
    bill.provisions.flatMap((p, i) =>
      (p.compute ?? []).map((row) => ({ slug: bill.slug, provision: i, row })),
    ),
  );

  it("never claim a certification their provenance contradicts", () => {
    for (const { row } of rows) {
      if (row.certification?.certified === true) {
        expect(isPublishableCompute(row)).toBe(true);
      }
    }
  });

  it("S.3596 publishes its figure only as a certified, exact-runtime pairing", () => {
    const s3596 = rows.filter((r) => r.slug === "s3596-119");
    expect(s3596).toHaveLength(1);
    const { row } = s3596[0];
    expect(isPublishableCompute(row)).toBe(true);
    expect(row.certification?.validated_against).toBe(`policyengine-us@${row.pe_us_version}`);
    expect(JSON.stringify(row)).not.toContain("claimed-tier");
  });
});
