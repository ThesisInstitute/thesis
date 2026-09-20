import { describe, expect, it } from "vitest";
import { canPlotReportHistory } from "@/lib/report-history";
import type { HistoricalPoint } from "@/data/forecast-cells";

const history = (...labels: string[]): HistoricalPoint[] =>
  labels.map((label, index) => ({ label, value: index + 1 }));

describe("report history chart eligibility", () => {
  it.each([
    ["2023", "2024"],
    ["calendar year 2023", "2024"],
    ["FY2024", "FY 2025"],
    ["fiscal year 2024", "FY2025"],
    ["2025-Q4", "Q1 2026"],
    ["2025 Q4", "2026 Q1"],
    ["December 2025", "Jan 2026"],
    ["2025 December", "2026 January"],
    ["2025-12", "2026-01"],
    ["2024-02-29", "2024-03-07"],
  ])("accepts comparable ordered observations %s → %s", (first, second) => {
    expect(canPlotReportHistory(history(first, second))).toBe(true);
  });

  it("rejects mixed-unit reference values archived as historical context", () => {
    expect(
      canPlotReportHistory([
        {
          label: "latest_week_2026-07-04_sa_initial_claims_thousands",
          value: 215,
        },
        { label: "latest_nsa_initial_claims_persons", value: 224583 },
      ]),
    ).toBe(false);
  });

  it.each([
    ["latest", "prior"],
    ["2024", "2025e"],
    ["2024 baseline", "2025 projection"],
    ["2025", "2026-01"],
    ["2024", "FY2025"],
    ["2026-01", "2026-01-15"],
    ["2026-01", "2026-01"],
    ["2026-02", "2026-01"],
    ["2026-02-29", "2026-03-07"],
    ["2026-04-31", "2026-05-01"],
    ["2026-13", "2027-01"],
  ])(
    "rejects ambiguous, incompatible, or unordered labels %s → %s",
    (first, second) => {
      expect(canPlotReportHistory(history(first, second))).toBe(false);
    },
  );

  it("requires enough finite observations for a trend", () => {
    expect(canPlotReportHistory([])).toBe(false);
    expect(canPlotReportHistory(history("2025"))).toBe(false);
    expect(
      canPlotReportHistory([
        { label: "2024", value: NaN },
        { label: "2025", value: 2 },
      ]),
    ).toBe(false);
  });

  it("checks canonical period metadata against the displayed dates", () => {
    expect(
      canPlotReportHistory([
        { label: "2025", value: 1, period: { type: "year", value: "2025" } },
        { label: "2026", value: 2, period: { type: "year", value: "2026" } },
      ]),
    ).toBe(true);
    expect(
      canPlotReportHistory([
        { label: "2025", value: 1, period: { type: "year", value: "2024" } },
        { label: "2026", value: 2, period: { type: "year", value: "2026" } },
      ]),
    ).toBe(false);
    expect(
      canPlotReportHistory([
        {
          label: "2026-07-04",
          value: 215,
          period: { type: "week_ending", value: "2026-07-04" },
        },
        {
          label: "2026-07-11",
          value: 214,
          period: { type: "week_ending", value: "2026-07-11" },
        },
      ]),
    ).toBe(true);
  });
});
