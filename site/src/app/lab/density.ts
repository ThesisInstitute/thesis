import type { NumericCdf } from "@/data/generated/thesis-lab";

export type DensityInterval = {
  lower: number;
  upper: number;
  density: number;
};

/** Average slope over adjacent CDF intervals, preserving each bin's probability mass. */
export function deriveDensity(
  points: NumericCdf["points"],
  intervalsPerBin = 1,
): DensityInterval[] | null {
  if (!Number.isInteger(intervalsPerBin) || intervalsPerBin < 1) return null;
  const intervals: DensityInterval[] = [];
  for (let i = 0; i < points.length - 1; i += intervalsPerBin) {
    const previous = points[i];
    const current = points[Math.min(i + intervalsPerBin, points.length - 1)];
    const width = current.value - previous.value;
    const mass = current.probability - previous.probability;
    const density = mass / width;
    // Even finite input coordinates can overflow or underflow during division.
    // Refuse an unrepresentable curve instead of dropping its probability mass.
    if (
      !Number.isFinite(width) ||
      width <= 0 ||
      !Number.isFinite(density) ||
      density < 0 ||
      (mass > 0 && density === 0)
    )
      return null;
    intervals.push({ lower: previous.value, upper: current.value, density });
  }
  return intervals.length > 0 ? intervals : null;
}
