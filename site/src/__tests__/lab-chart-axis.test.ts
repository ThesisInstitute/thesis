import { describe, expect, it } from "vitest";
import { axisLabel, axisLabels, niceAxis } from "@/app/lab/chart-axis";

describe("round chart axes", () => {
  it("uses round bounds and ticks for the CPI forecast and density", () => {
    expect(niceAxis(0.95, 4.95)).toEqual({
      lower: 0,
      upper: 5,
      ticks: [0, 1, 2, 3, 4, 5],
    });
    expect(niceAxis(0, 1.136363636)).toEqual({
      lower: 0,
      upper: 1.25,
      ticks: [0, 0.25, 0.5, 0.75, 1, 1.25],
    });
  });

  it("includes negative values, zero and outcomes outside the forecast support", () => {
    const axis = niceAxis(-4.1, 0.6);
    expect(axis).toEqual({
      lower: -5,
      upper: 1,
      ticks: [-5, -4, -3, -2, -1, 0, 1],
    });
    expect(niceAxis(0.95, 8.3).upper).toBe(10);
  });

  it("ignores floating-point noise at a round boundary without clipping data", () => {
    const axis = niceAxis(0, 0.200000000000004);
    expect(axis.ticks).toEqual([0, 0.05, 0.1, 0.15, 0.2]);
    expect(axis.upper).toBeGreaterThanOrEqual(0.200000000000004);
  });

  it.each([
    [0, 0.000013],
    [0, 13e6],
    [0, 200 * Number.MIN_VALUE],
  ])("keeps a finite enclosing scale for %s to %s", (min, max) => {
    const axis = niceAxis(min, max);
    expect(axis.lower).toBeLessThanOrEqual(min);
    expect(axis.upper).toBeGreaterThanOrEqual(max);
    expect(axis.ticks.length).toBeGreaterThan(1);
    expect(axis.ticks.every(Number.isFinite)).toBe(true);
    expect(new Set(axisLabels(axis.ticks)).size).toBe(axis.ticks.length);
  });

  it("formats round fractional ticks without artifacts or duplicate zero labels", () => {
    expect(axisLabel(0.30000000000000004)).toBe("0.3");
    expect(axisLabel(0.25)).toBe("0.25");
    expect(axisLabel(0.000005)).toBe("5e-6");
    expect(axisLabel(-0)).toBe("0");
  });
  it("keeps labels distinct for a narrow range around a large offset", () => {
    const { ticks } = niceAxis(1_000_000, 1_000_000.000013);
    const labels = axisLabels(ticks);
    expect(new Set(labels).size).toBe(ticks.length);
    expect(labels.map(Number)).toEqual(ticks);
  });
});
