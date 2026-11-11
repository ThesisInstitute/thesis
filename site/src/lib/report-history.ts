import type { HistoricalPoint } from "@/data/forecast-cells";

type PeriodKind = "year" | "fiscal_year" | "quarter" | "month" | "day";
interface ParsedPeriod {
  kind: PeriodKind;
  ordinal: number;
}

const MONTHS = [
  "january",
  "february",
  "march",
  "april",
  "may",
  "june",
  "july",
  "august",
  "september",
  "october",
  "november",
  "december",
];

/** Plot only unambiguous chronological observations, never arbitrary numeric
 * reference values that happened to be archived in historicalContext. */
export function canPlotReportHistory(
  history: readonly HistoricalPoint[],
): boolean {
  if (history.length < 2) return false;
  let previous: ParsedPeriod | undefined;
  for (const point of history) {
    if (!Number.isFinite(point.value)) return false;
    const parsed = parsePeriodLabel(point.label);
    if (!parsed) return false;
    if (point.period) {
      const canonical = parseCanonicalPeriod(point.period);
      if (
        !canonical ||
        canonical.kind !== parsed.kind ||
        canonical.ordinal !== parsed.ordinal
      )
        return false;
    }
    if (
      previous &&
      (previous.kind !== parsed.kind || previous.ordinal >= parsed.ordinal)
    )
      return false;
    previous = parsed;
  }
  return true;
}

function parsePeriodLabel(label: string): ParsedPeriod | undefined {
  const text = label.trim();
  let match = /^(?:calendar year )?([1-9]\d{3})$/i.exec(text);
  if (match) return { kind: "year", ordinal: Number(match[1]) };
  match = /^(?:FY\s*|fiscal year )([1-9]\d{3})$/i.exec(text);
  if (match) return { kind: "fiscal_year", ordinal: Number(match[1]) };
  match = /^([1-9]\d{3})[- ]Q([1-4])$/i.exec(text);
  if (match)
    return {
      kind: "quarter",
      ordinal: Number(match[1]) * 4 + Number(match[2]) - 1,
    };
  match = /^Q([1-4]) ([1-9]\d{3})$/i.exec(text);
  if (match)
    return {
      kind: "quarter",
      ordinal: Number(match[2]) * 4 + Number(match[1]) - 1,
    };
  match = /^([1-9]\d{3})-(0[1-9]|1[0-2])$/.exec(text);
  if (match)
    return {
      kind: "month",
      ordinal: Number(match[1]) * 12 + Number(match[2]) - 1,
    };
  const monthFirst = /^([A-Za-z]+) ([1-9]\d{3})$/.exec(text);
  const yearFirst = /^([1-9]\d{3}) ([A-Za-z]+)$/.exec(text);
  const monthLabel = (monthFirst?.[1] ?? yearFirst?.[2])?.toLowerCase();
  const monthYear = monthFirst?.[2] ?? yearFirst?.[1];
  if (monthLabel && monthYear) {
    const month = MONTHS.findIndex(
      (name) => monthLabel === name || monthLabel === name.slice(0, 3),
    );
    if (month >= 0)
      return { kind: "month", ordinal: Number(monthYear) * 12 + month };
  }
  match = /^([1-9]\d{3})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.exec(text);
  if (match) {
    const [year, month, day] = match.slice(1).map(Number);
    const date = new Date(Date.UTC(year, month - 1, day));
    if (
      date.getUTCFullYear() === year &&
      date.getUTCMonth() === month - 1 &&
      date.getUTCDate() === day
    ) {
      return { kind: "day", ordinal: date.getTime() };
    }
  }
  return undefined;
}

function parseCanonicalPeriod(
  period: NonNullable<HistoricalPoint["period"]>,
): ParsedPeriod | undefined {
  const parsed = parsePeriodLabel(
    period.type === "fiscal_year" ? `FY${period.value}` : period.value,
  );
  const expectedKind = period.type === "week_ending" ? "day" : period.type;
  return parsed?.kind === expectedKind ? parsed : undefined;
}
