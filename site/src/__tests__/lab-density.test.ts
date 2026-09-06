import { describe, expect, it } from "vitest";
import { deriveDensity } from "@/app/lab/density";
import { distribution } from "./lab-fixtures";

describe("density derived from the stored CDF", () => {
  it("preserves each wider bin's probability rather than averaging individual slopes", () => {
    const points = [
      { value: 0, probability: 0 },
      { value: 0.125, probability: 0.25 },
      { value: 0.5, probability: 0.5 },
      { value: 2, probability: 0.75 },
      { value: 3, probability: 1 },
    ];
    const bins = deriveDensity(points, 2)!;
    expect(bins).toEqual([
      { lower: 0, upper: 0.5, density: 1 },
      { lower: 0.5, upper: 3, density: 0.2 },
    ]);
    for (const bin of bins)
      expect(bin.density * (bin.upper - bin.lower)).toBe(0.5);
    expect(deriveDensity(distribution.points, 5)).toHaveLength(40);
  });
  it("preserves total probability in all 200 uniform intervals", () => {
    const intervals = deriveDensity(distribution.points)!;
    expect(intervals).toHaveLength(200);
    for (const interval of intervals) expect(interval.density).toBeCloseTo(0.1);
    expect(
      intervals.reduce((mass, p) => mass + p.density * (p.upper - p.lower), 0),
    ).toBeCloseTo(1);
  });

  it("preserves plateaus and unequal widths without smoothing or capping density", () => {
    const intervals = deriveDensity([
      { value: 0, probability: 0 },
      { value: 0.125, probability: 0.25 },
      { value: 0.25, probability: 0.25 },
      { value: 1, probability: 1 },
    ])!;
    expect(intervals).toEqual([
      { lower: 0, upper: 0.125, density: 2 },
      { lower: 0.125, upper: 0.25, density: 0 },
      { lower: 0.25, upper: 1, density: 1 },
    ]);
    expect(
      intervals.reduce((mass, p) => mass + p.density * (p.upper - p.lower), 0),
    ).toBe(1);
  });

  it("refuses division overflow and underflow instead of losing probability mass", () => {
    expect(
      deriveDensity([
        { value: 0, probability: 0 },
        { value: Number.MIN_VALUE, probability: 0.5 },
        { value: 1, probability: 1 },
      ]),
    ).toBeNull();
    expect(
      deriveDensity([
        { value: 0, probability: 0 },
        { value: 2, probability: Number.MIN_VALUE },
        { value: 3, probability: 1 },
      ]),
    ).toBeNull();
  });
});
