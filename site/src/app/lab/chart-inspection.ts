import type { NumericCdf } from "@/data/generated/thesis-lab";
import { axisLabel } from "./chart-axis";
import type { DensityInterval } from "./density";

/** Evaluate the same piecewise linear CDF drawn by the chart, including its tails. */
export function cdfAt(points: NumericCdf["points"], value: number): number {
  if (value <= points[0].value) return 0;
  for (let i = 1; i < points.length; i++) {
    const previous = points[i - 1];
    const current = points[i];
    if (value <= current.value) {
      const share = (value - previous.value) / (current.value - previous.value);
      return (
        previous.probability +
        share * (current.probability - previous.probability)
      );
    }
  }
  return 1;
}

/** Internal boundaries belong to the bin on the right; the final endpoint is included. */
export function densityBinAt(
  bins: readonly DensityInterval[],
  value: number,
): DensityInterval | null {
  return (
    bins.find(
      (bin, i) =>
        value >= bin.lower &&
        (value < bin.upper || (i === bins.length - 1 && value === bin.upper)),
    ) ?? null
  );
}

/** Keep nearby inspected values distinguishable without exposing floating-point noise. */
export function inspectionLabels(values: readonly number[]): string[] {
  const distinct = new Set(values).size;
  const span = Math.max(...values) - Math.min(...values);
  const magnitude = Math.max(...values.map(Math.abs));
  const needed =
    span > 0 && magnitude > 0
      ? Math.floor(Math.log10(magnitude)) - Math.floor(Math.log10(span)) + 3
      : 5;
  for (
    let precision = Math.max(5, Math.min(17, needed));
    precision < 17;
    precision++
  ) {
    const labels = values.map((value) => axisLabel(value, precision));
    if (new Set(labels).size === distinct) return labels;
  }
  return values.map((value) => axisLabel(value, 17));
}
