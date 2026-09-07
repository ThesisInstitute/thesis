export type ChartAxis = {
  lower: number;
  upper: number;
  ticks: number[];
};

/** Round spacing and bounds using the same preferred steps as Recharts niceTicks. */
export function niceAxis(min: number, max: number, tickCount = 6): ChartAxis {
  const roughStep = (max - min) / (tickCount - 1);
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const fraction = roughStep / magnitude;
  const multiple =
    [1, 2, 2.5, 5, 10].find((n) => fraction <= n * (1 + 1e-12)) ?? 10;
  const step = Math.max(Number.MIN_VALUE, multiple * magnitude);
  // At numeric limits a rounded domain may not be representable.
  if (!Number.isFinite(step) || !(max > min))
    return { lower: min, upper: max, ticks: [min, max] };
  const snap = (n: number) =>
    Math.abs(n - Math.round(n)) < 1e-10 ? Math.round(n) : n;
  const first = Math.floor(snap(min / step));
  const last = Math.ceil(snap(max / step));
  const ticks = Array.from(
    { length: Math.min(last - first + 1, 100) },
    (_, i) => Number(((first + i) * step).toPrecision(15)),
  ).filter(
    (value, i, values) =>
      Number.isFinite(value) && (i === 0 || value > values[i - 1]),
  );
  if (ticks.length < 2) return { lower: min, upper: max, ticks: [min, max] };
  return {
    lower: Math.min(min, ticks[0]),
    upper: Math.max(max, ticks.at(-1)!),
    ticks,
  };
}

export function axisLabel(value: number, precision = 12): string {
  if (value === 0) return "0";
  return Math.abs(value) < 0.001 || Math.abs(value) >= 1e6
    ? Number(value.toPrecision(precision)).toExponential()
    : Number(value.toPrecision(precision)).toLocaleString("en-US", {
        maximumSignificantDigits: precision,
      });
}

/** Prefer concise labels, increasing precision only when ticks would look identical. */
export function axisLabels(ticks: readonly number[]): string[] {
  for (let precision = 12; precision < 17; precision++) {
    const labels = ticks.map((tick) => axisLabel(tick, precision));
    if (new Set(labels).size === labels.length) return labels;
  }
  return ticks.map((tick) => axisLabel(tick, 17));
}
