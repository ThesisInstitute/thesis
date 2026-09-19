import {
  formatValue,
  getForecastCountry,
  type CountryCode,
  type ForecastCell,
  type ForecastCellType,
} from "./forecast-cells";
import { publisherForCell, type PublisherInfo } from "./forecast-publishers";
import { overdueNotice, shortReason } from "./resolution-status";

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
  /** Set only while the forecast is pending past its resolution date: the
   * first sentence of why it has not resolved, as the resolver last
   * reported it. The full reason is on the forecast's own page; this list
   * crosses to the client, so it stays one sentence. */
  overdue: { since: string; reason: string } | null;
}

export function buildForecastListing(
  forecasts: ForecastCell[],
): ForecastListingItem[] {
  return forecasts.map((forecast) => buildListingItem(forecast));
}

function buildListingItem(forecast: ForecastCell): ForecastListingItem {
  const status = forecast.resolvedOutcome ? "resolved" : "pending";
  return {
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
    status,
    country: getForecastCountry(forecast),
    type: forecast.type,
    publisher: publisherForCell(forecast),
    overdue: compactOverdue(forecast, status),
  };
}

function compactOverdue(
  forecast: ForecastCell,
  status: "pending" | "resolved",
): ForecastListingItem["overdue"] {
  const notice = overdueNotice({
    slug: forecast.slug,
    status,
    resolutionDate: forecast.resolutionDate,
  });
  return notice
    ? { since: notice.since, reason: shortReason(notice.reason) }
    : null;
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
