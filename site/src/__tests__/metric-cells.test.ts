import { describe, expect, it } from "vitest";
import { FORECAST_CELLS } from "@/data/forecast-cells";
import { getPublishedForecasts } from "@/lib/forecast-publication";
import { cellsForSeries, resolveMetricCell } from "@/lib/metric-cells";

describe("resolveMetricCell (live metric → cell join)", () => {
  it("fails closed on missing or vague hints", () => {
    expect(resolveMetricCell(undefined)).toBeNull();
    expect(resolveMetricCell("")).toBeNull();
    expect(resolveMetricCell("irs")).toBeNull();
    expect(resolveMetricCell("irs.soi")).toBeNull();
  });

  it("returns null for a confident hint with no registered series", () => {
    expect(resolveMetricCell("usda.fsa.no_such_series")).toBeNull();
  });

  it("does not match a partial token at the end of a series hint", () => {
    expect(cellsForSeries("us.dol.initial_claim")).toEqual([]);
    expect(resolveMetricCell("us.dol.initial_claim")).toBeNull();
  });

  it("does not turn withdrawn SPM and ACTC prototypes into live metric estimates", () => {
    for (const hint of [
      "census.spm.child_poverty_rate",
      "irs.soi.additional_child_tax_credit_returns",
    ]) {
      expect(
        FORECAST_CELLS.some((cell) => cell.dataPointId?.startsWith(hint)),
      ).toBe(true);
      expect(cellsForSeries(hint)).toEqual([]);
      expect(resolveMetricCell(hint)).toBeNull();
    }
  });

  it("joins a verified initial-claims forecast with its actual displayed values", () => {
    const match = resolveMetricCell("us.dol.initial_claims", "2026-08-01");
    expect(match).not.toBeNull();
    const published = getPublishedForecasts().find(
      (cell) => cell.slug === match!.slug,
    );
    expect(published).toBeDefined();
    expect(match!.point).toBe(published!.pointEstimate);
    expect(match!.ciLow).toBe(published!.ciLow);
    expect(match!.ciHigh).toBe(published!.ciHigh);
  });

  it("picks the nearest unresolved period and counts the rest", () => {
    const match = resolveMetricCell("us.dol.initial_claims", "2026-08-01");
    expect(match).not.toBeNull();
    // Real archived weekly claims runs supply multiple eligible periods.
    expect(match!.resolutionDate >= "2026-08-01").toBe(true);
    expect(match!.moreCount).toBeGreaterThan(0);
  });

  it("falls back to the latest cell when the series is fully resolved", () => {
    const match = resolveMetricCell("us.dol.initial_claims", "2099-01-01");
    expect(match).not.toBeNull();
    expect(match!.resolutionDate <= "2099-01-01").toBe(true);
    const selectedCell = getPublishedForecasts().find(
      (cell) => cell.slug === match!.slug,
    );
    expect(selectedCell?.type).not.toBe("conditional");
  });
});

describe("conditional arms never satisfy unconditional metric hints", () => {
  it("excludes type=conditional cells from hint resolution", () => {
    // Use a currently published mixed series so this remains a deletion
    // check before the FY27-NDAA arms themselves publish. The NDAA pair will
    // share the same shape: conditional arms beside unconditional metrics.
    const series = "census.spm.child_poverty_rate";
    const raw = FORECAST_CELLS.filter((cell) =>
      cell.dataPointId?.startsWith(series),
    );
    expect(raw.some((cell) => cell.type === "conditional")).toBe(true);
    expect(raw.some((cell) => cell.type !== "conditional")).toBe(true);

    const matches = cellsForSeries(series);
    expect(matches).toEqual([]);
    expect(resolveMetricCell(series)).toBeNull();
    // The surviving conditional arms cannot resurrect a withdrawn unconditional forecast.
    expect(
      getPublishedForecasts().some(
        (cell) =>
          cell.type === "conditional" && cell.dataPointId?.startsWith(series),
      ),
    ).toBe(true);
  });
});
