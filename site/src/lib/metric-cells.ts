import { getPublishedForecasts } from "@/lib/forecast-publication";
import { formatValue, type ForecastCell } from "@/data/forecast-cells";

/**
 * The live join from a candidate metric to registered forecast cells —
 * the piece that turns a bill analysis from case study into scoreboard
 * view. Matches the metric's series_hint as a prefix against cell
 * dataPointIds at build time.
 *
 * Fail-closed: a missing, short, or unmatched hint returns null and the
 * card renders exactly as before. A confident match supersedes any
 * stored registry value — the docket is the authority on reachability.
 */
export interface MetricCellMatch {
  slug: string;
  title: string;
  question: string;
  pointLabel: string;
  ciLabel: string;
  point: number;
  ciLow: number;
  ciHigh: number;
  resolutionDate: string;
  /** Other cells on the same series (earlier/later periods). */
  moreCount: number;
}

function isConfidentHint(hint: string): boolean {
  // Two dotted segments minimum — bare agency tokens ("irs") would
  // prefix-match half the registry.
  return hint.split(".").filter(Boolean).length >= 3;
}

export function resolveMetricCell(
  seriesHint: string | undefined,
  today: string = new Date().toISOString().slice(0, 10),
): MetricCellMatch | null {
  if (!seriesHint || !isConfidentHint(seriesHint)) return null;
  // Metric hints are unconditional accountability joins: a conditional
  // arm (e.g. the FY27-NDAA pair on the same series) must never satisfy
  // a bill metric's hint - conditional cells surface only through
  // explicit comparison-group links.
  const matches = cellsForSeries(seriesHint);
  if (matches.length === 0) return null;
  const byDate = [...matches].sort((a, b) =>
    (a.resolutionDate ?? "").localeCompare(b.resolutionDate ?? ""),
  );
  // Nearest cell still ahead of us; if the series is fully resolved,
  // show the latest.
  const chosen =
    byDate.find((cell) => (cell.resolutionDate ?? "") >= today) ??
    byDate[byDate.length - 1];
  return {
    slug: chosen.slug,
    title: chosen.title,
    question: chosen.question,
    pointLabel: formatValue(chosen.pointEstimate, chosen.unit),
    ciLabel: `${formatValue(chosen.ciLow, chosen.unit)} – ${formatValue(
      chosen.ciHigh,
      chosen.unit,
    )}`,
    point: chosen.pointEstimate,
    ciLow: chosen.ciLow,
    ciHigh: chosen.ciHigh,
    resolutionDate: chosen.resolutionDate ?? "",
    moreCount: matches.length - 1,
  };
}

export function cellsForSeries(seriesHint: string): ForecastCell[] {
  if (!isConfidentHint(seriesHint)) return [];
  return getPublishedForecasts().filter(
    (cell) =>
      cell.type !== "conditional" && cell.dataPointId?.startsWith(seriesHint),
  );
}
