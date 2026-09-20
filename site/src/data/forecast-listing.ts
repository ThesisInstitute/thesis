import {
  formatValue,
  getForecastCountry,
  type CountryCode,
  type ForecastCell,
  type ForecastCellType,
} from "./forecast-display";
import { publisherForCell, type PublisherInfo } from "./forecast-publishers";

/** The only catalog fields allowed across the /forecasts page boundary. */
export interface ForecastListingItem {
  slug: string;
  title: string;
  point: { value: number; label: string };
  interval: {
    lower: { value: number; label: string };
    upper: { value: number; label: string };
  };
  resolutionDate: string;
  status: "pending" | "resolved";
  country: CountryCode;
  type: ForecastCellType;
  publisher: PublisherInfo | null;
}

export function buildForecastListing(
  forecasts: ForecastCell[],
): ForecastListingItem[] {
  return forecasts.map((forecast) => ({
    slug: forecast.slug,
    title: forecast.title,
    point: {
      value: forecast.pointEstimate,
      label: formatValue(forecast.pointEstimate, forecast.unit),
    },
    interval: {
      lower: {
        value: forecast.ciLow,
        label: formatValue(forecast.ciLow, forecast.unit),
      },
      upper: {
        value: forecast.ciHigh,
        label: formatValue(forecast.ciHigh, forecast.unit),
      },
    },
    resolutionDate: forecast.resolutionDate,
    status: forecast.resolvedOutcome ? "resolved" : "pending",
    country: getForecastCountry(forecast),
    type: forecast.type,
    publisher: publisherForCell(forecast),
  }));
}

/** Deterministic facet filters over the listing. Every field is derived
 * from the cells themselves; an empty/undefined filter passes everything. */
export interface ForecastListingFilter {
  publisher?: string;
  country?: string;
  status?: "pending" | "resolved";
  query?: string;
}

export function filterForecastListing(
  items: ForecastListingItem[],
  filter: ForecastListingFilter,
): ForecastListingItem[] {
  const query = filter.query?.trim().toLowerCase();
  return items.filter((item) => {
    if (filter.publisher && item.publisher?.slug !== filter.publisher) {
      return false;
    }
    if (filter.country && item.country !== filter.country) return false;
    if (filter.status && item.status !== filter.status) return false;
    if (query && !item.title.toLowerCase().includes(query)) return false;
    return true;
  });
}
