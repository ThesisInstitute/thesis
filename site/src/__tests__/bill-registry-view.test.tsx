import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Keep this page regression independent of the full forecast archive. The
// publication gate and conditional-pair tests cover those separate surfaces.
vi.mock("@/data/bill-forecasts", () => ({
  getBillForecastGroups: () => [],
  getBillContextSeriesLinks: () => [],
  getPendingConditionals: () => [],
}));
vi.mock("@/data/forecast-cells", () => ({ formatValue: String }));
vi.mock("@/components/Header", () => ({ Header: () => null }));
vi.mock("@/components/BillForecasts", () => ({ BillForecasts: () => null }));
vi.mock("@/components/ComputeCard", () => ({ ComputeCard: () => null }));
vi.mock("@/lib/bill-text", () => ({ fullSectionText: () => null }));
vi.mock("@/lib/metric-cells", () => ({ resolveMetricCell: vi.fn(() => null) }));
vi.mock("@/data/bills", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/data/bills")>()),
  loadBillMeta: () => null,
  loadBillDocket: () => [
    {
      series: "agency.outcome.rate",
      ledger: { uuid: "docket-uuid", concept: "agency.outcome.rate" },
    },
    { series: "agency.outcome.count" },
  ],
  getBill: () => ({
    slug: "registry-example",
    bill: {
      name: "Registry example",
      status: "Introduced",
      pages: 1,
      analyzed: "All provisions",
      analysisDate: "2026-09-21",
      sourceUrl: "https://www.congress.gov/",
    },
    provisions: [
      {
        title: "Section 1",
        heading: "Outcomes",
        quote: "",
        goals: [],
        effects: [],
        barriers: [],
        metrics: [
          {
            kind: "Outcome",
            text: "An admitted outcome rate.",
            series_hint: "agency.outcome.rate",
            registry: "no-series",
            ledger_uuid: "unreviewed-uuid",
          },
          {
            kind: "Outcome",
            text: "An unknown outcome rate.",
            series_hint: "unknown.outcome.rate",
            registry: "reachable",
            matched_series: "agency.outcome.rate",
          },
          {
            kind: "Outcome",
            text: "An ambiguous outcome.",
            series_hint: "agency.outcome",
            registry: "reachable",
          },
        ],
        conditionals: [],
      },
    ],
  }),
}));

import BillDetailPage from "@/app/bills/[slug]/page";
import { CHRONICLE_CATALOG_URL } from "@/data/bills";
import { resolveMetricCell } from "@/lib/metric-cells";

describe("bill page current registry status", () => {
  it("counts admitted metrics independently of hints, old badges, and forecasts", async () => {
    render(
      await BillDetailPage({
        params: Promise.resolve({ slug: "registry-example" }),
      }),
    );

    const progress = screen.getByRole("region", {
      name: "Metric mapping progress",
    });
    expect(progress).toHaveTextContent("1 of 3 candidate outcome metrics");
    expect(progress).toHaveTextContent(
      "2 remain on the mapping and admission worklist",
    );
    expect(screen.getAllByText("Admitted to docket")).toHaveLength(1);
    expect(screen.getByText("Admission work needed")).toBeInTheDocument();
    expect(screen.getByText("Mapping review needed")).toBeInTheDocument();
    expect(
      screen.getByText(/no enacted-vs-baseline pair is registered/),
    ).toHaveTextContent("1 of 3 candidate metrics map to admitted series");

    const historicalStatuses = screen.getAllByText(/Historical assessment;/);
    expect(historicalStatuses).toHaveLength(3);
    expect(historicalStatuses[0]).toHaveTextContent("no-series (2026-09-21)");

    const identityLink = screen.getByText("Chronicle catalog ↗");
    expect(identityLink).toHaveAttribute("href", CHRONICLE_CATALOG_URL);
    expect(
      within(identityLink.parentElement!).getByText("docket-uuid"),
    ).toBeInTheDocument();
    expect(screen.queryByText("unreviewed-uuid")).not.toBeInTheDocument();

    expect(resolveMetricCell).toHaveBeenCalledWith("agency.outcome.rate");
    expect(resolveMetricCell).not.toHaveBeenCalledWith("agency.outcome");
    expect(resolveMetricCell).not.toHaveBeenCalledWith("unknown.outcome.rate");
    expect(screen.queryByText(/Live forecast /)).not.toBeInTheDocument();
  });
});
