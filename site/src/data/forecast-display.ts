// Display helpers deliberately do not import the raw forecast catalog at runtime.
import type {
  ForecastCell,
  ForecastRunEntry,
  CountryCode,
  ForecastCellType,
  Unit,
} from "./forecast-cells";
import { buildNumericCdfFromInterval } from "./prediction-distribution";
export type {
  ForecastCell,
  ForecastRunEntry,
  CountryCode,
  ForecastCellType,
  Unit,
  ReasoningStep,
  PredictionPackReference,
} from "./forecast-cells";

export function getForecastRunEntries(
  forecast: ForecastCell,
): ForecastRunEntry[] {
  const primaryDistribution =
    forecast.predictionDistribution ??
    buildNumericCdfFromInterval({
      pointEstimate: forecast.pointEstimate,
      ciLow: forecast.ciLow,
      ciHigh: forecast.ciHigh,
    });
  const primary: ForecastRunEntry = {
    variantId: forecast.primaryVariantId ?? "primary",
    label: forecast.predictionRun?.runLabel ?? "Headline",
    description: forecast.predictionRun?.runDescription,
    isPrimary: true,
    pointEstimate: forecast.pointEstimate,
    ciLow: forecast.ciLow,
    ciHigh: forecast.ciHigh,
    confidence: forecast.confidence,
    drivers: forecast.drivers,
    historicalContext: forecast.historicalContext,
    predictionRun: forecast.predictionRun,
    packSet: forecast.predictionRun?.packSet,
    predictionDistribution: primaryDistribution,
    reasoning: forecast.reasoning,
  };

  return [
    primary,
    ...(forecast.comparisonRuns ?? []).map(
      (run): ForecastRunEntry => ({
        variantId: run.variantId,
        label: run.label,
        description: run.description,
        isPrimary: false,
        pointEstimate: run.pointEstimate,
        ciLow: run.ciLow,
        ciHigh: run.ciHigh,
        confidence: run.confidence ?? forecast.confidence,
        drivers: run.drivers ?? forecast.drivers,
        historicalContext: run.historicalContext,
        predictionRun: run.predictionRun,
        packSet: run.predictionRun.packSet,
        predictionDistribution:
          run.predictionDistribution ??
          buildNumericCdfFromInterval({
            pointEstimate: run.pointEstimate,
            ciLow: run.ciLow,
            ciHigh: run.ciHigh,
          }),
        reasoning: run.reasoning,
        externalSubmission: run.externalSubmission,
      }),
    ),
  ];
}

export function getResolutionResult(
  forecast: ForecastCell,
): "inside" | "outside" | null {
  if (!forecast.resolvedOutcome) return null;
  const actual = forecast.resolvedOutcome.value;
  return forecast.ciLow <= actual && actual <= forecast.ciHigh
    ? "inside"
    : "outside";
}

export const COUNTRY_LABEL: Record<CountryCode, string> = {
  US: "United States",
  UK: "United Kingdom",
  CA: "Canada",
  AU: "Australia",
  EA: "Euro area",
  JP: "Japan",
  BE: "Belgium",
};

export function getForecastCountry(forecast: ForecastCell): CountryCode {
  if (forecast.country) return forecast.country;
  if (forecast.series?.country) return forecast.series.country;
  if (
    forecast.slug.startsWith("canada-") ||
    /\b(Canada|Statistics Canada|Bank of Canada)\b/.test(
      `${forecast.title} ${forecast.question} ${forecast.resolutionSource}`,
    )
  ) {
    return "CA";
  }
  if (
    forecast.slug.startsWith("australia-") ||
    /\b(Australia|Australian Bureau of Statistics|Reserve Bank of Australia|RBA)\b/.test(
      `${forecast.title} ${forecast.question} ${forecast.resolutionSource}`,
    )
  ) {
    return "AU";
  }
  if (
    forecast.slug.startsWith("euro-area-") ||
    /\b(Euro area|euro area|Eurostat|European Central Bank|ECB)\b/.test(
      `${forecast.title} ${forecast.question} ${forecast.resolutionSource}`,
    )
  ) {
    return "EA";
  }
  if (
    forecast.slug.startsWith("japan-") ||
    /\b(Japan|Bank of Japan|Statistics Bureau of Japan|Tokyo CPI|BOJ)\b/.test(
      `${forecast.title} ${forecast.question} ${forecast.resolutionSource}`,
    )
  ) {
    return "JP";
  }
  if (
    forecast.slug.startsWith("uk-") ||
    /\b(UK|United Kingdom|Great Britain|Office for National Statistics|Bank of England|HMRC)\b/.test(
      `${forecast.title} ${forecast.question} ${forecast.resolutionSource}`,
    )
  ) {
    return "UK";
  }
  return "US";
}

export function formatValue(value: number, unit: Unit): string {
  switch (unit) {
    case "count":
      return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
    case "percent":
      return `${formatPercent(value)}%`;
    case "percent_growth":
      return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
    case "gbp_billions":
      return `£${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}B`;
    case "usd":
      if (Math.abs(value) >= 1000) {
        return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
      }
      return `$${value.toFixed(2)}`;
    case "usd_millions":
      return `$${value.toLocaleString(undefined, { maximumFractionDigits: 3 })}M`;
    case "usd_billions":
      return `$${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}B`;
    case "usd_monthly":
      return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}/mo`;
    case "thousands":
      if (Math.abs(value) >= 1000) {
        return `${formatScaledThousandsAsMillions(value)}m`;
      }
      return `${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}k`;
    case "millions":
      return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}M`;
    case "million_cubic_feet":
      return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} MMcf`;
    case "per_1000_live_births":
      return `${value.toFixed(2)} per 1,000`;
    case "ratio":
      return value.toFixed(2);
    case "index_points":
      // Survey balances (NBB barometer, consumer confidence) print signed.
      return `${value >= 0 ? "+" : ""}${value.toFixed(1)}`;
    case "minutes":
      return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} min`;
    default:
      return value.toString();
  }
}

function formatScaledThousandsAsMillions(value: number): string {
  const millions = value / 1000;
  return millions.toLocaleString(undefined, {
    maximumFractionDigits: 2,
    minimumFractionDigits: Math.abs(millions) >= 10 ? 2 : 1,
  });
}

function formatPercent(value: number): string {
  const roundedToTenth = Math.round(value * 10) / 10;
  return Math.abs(value - roundedToTenth) < 1e-9
    ? value.toFixed(1)
    : value.toFixed(2);
}

export function formatValueShort(value: number, unit: Unit): string {
  if (unit === "usd" && Math.abs(value) >= 1000) {
    return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}B`;
  }
  return formatValue(value, unit);
}

export const TYPE_LABEL: Record<ForecastCellType, string> = {
  data: "Government data",
  policy: "Policy",
  conditional: "Conditional",
};

export const TYPE_DESCRIPTION: Record<ForecastCellType, string> = {
  data: "Forecast cell on a published government data point.",
  policy: "Forecast cell on a formal policy setting or encoded parameter.",
  conditional: "Outcome forecast conditional on a policy state.",
};
