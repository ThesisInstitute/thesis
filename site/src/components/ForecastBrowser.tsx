"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  COUNTRY_LABEL,
  TYPE_DESCRIPTION,
  TYPE_LABEL,
  type CountryCode,
  type ForecastCellType,
} from "@/data/forecast-display";
import {
  filterForecastListing,
  type ForecastListingFilter,
  type ForecastListingItem,
} from "@/data/forecast-listing";
import { ForecastCard } from "./ForecastCard";

interface ForecastBrowserProps {
  forecasts: ForecastListingItem[];
}

const SECTIONS: {
  key: ForecastCellType;
  label: string;
  description: string;
}[] = [
  {
    key: "data",
    label: `${TYPE_LABEL.data} cells`,
    description: TYPE_DESCRIPTION.data,
  },
  {
    key: "policy",
    label: `${TYPE_LABEL.policy} parameters`,
    description: TYPE_DESCRIPTION.policy,
  },
  {
    key: "conditional",
    label: TYPE_LABEL.conditional,
    description: TYPE_DESCRIPTION.conditional,
  },
];

const STATUS_OPTIONS = [
  { value: "", label: "pending + resolved" },
  { value: "pending", label: "pending" },
  { value: "resolved", label: "resolved" },
];

function readFilter(params: URLSearchParams): ForecastListingFilter {
  const status = params.get("status");
  return {
    publisher: params.get("publisher") ?? undefined,
    country: params.get("country") ?? undefined,
    status: status === "pending" || status === "resolved" ? status : undefined,
    query: params.get("q") ?? undefined,
  };
}

/** Sync the filter into the query string without a server round trip. */
function writeFilter(filter: ForecastListingFilter) {
  const params = new URLSearchParams(window.location.search);
  const entries: [string, string | undefined][] = [
    ["publisher", filter.publisher],
    ["country", filter.country],
    ["status", filter.status],
    ["q", filter.query?.trim() || undefined],
  ];
  for (const [key, value] of entries) {
    if (value) params.set(key, value);
    else params.delete(key);
  }
  const query = params.toString();
  window.history.replaceState(
    null,
    "",
    query ? `?${query}` : window.location.pathname,
  );
}

export function ForecastBrowser({ forecasts }: ForecastBrowserProps) {
  // Null outside a Next router (unit tests render the component bare).
  const searchParams = useSearchParams();
  const [filter, setFilter] = useState<ForecastListingFilter>(() =>
    readFilter(new URLSearchParams(searchParams?.toString() ?? "")),
  );

  const update = (patch: Partial<ForecastListingFilter>) => {
    const next = { ...filter, ...patch };
    setFilter(next);
    writeFilter(next);
  };

  // Facet options derive from the full listing, so every option shown is
  // backed by at least one cell and new agencies appear with no edits.
  const publisherOptions = useMemo(() => {
    const counts = new Map<string, { label: string; count: number }>();
    for (const item of forecasts) {
      if (!item.publisher) continue;
      const existing = counts.get(item.publisher.slug);
      if (existing) existing.count += 1;
      else
        counts.set(item.publisher.slug, {
          label: item.publisher.label,
          count: 1,
        });
    }
    return [...counts.entries()]
      .map(([slug, entry]) => ({ slug, ...entry }))
      .sort((a, b) => b.count - a.count || a.slug.localeCompare(b.slug));
  }, [forecasts]);

  const countryOptions = useMemo(() => {
    const counts = new Map<CountryCode, number>();
    for (const item of forecasts) {
      counts.set(item.country, (counts.get(item.country) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [forecasts]);

  const filtered = useMemo(
    () => filterForecastListing(forecasts, filter),
    [forecasts, filter],
  );
  const sortedForecasts = useMemo(
    () => [...filtered].sort(compareByResolutionDate),
    [filtered],
  );
  const hasActiveFilter = Boolean(
    filter.publisher || filter.country || filter.status || filter.query?.trim(),
  );

  const selectClass =
    "rounded-lg border bg-[var(--theme-bg-elevated)] px-2.5 py-1.5 [font-family:var(--font-body)] text-[0.82rem] text-[var(--theme-text)]";

  return (
    <div>
      <div
        className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border bg-[var(--theme-bg-elevated)] p-3"
        style={{ borderColor: "var(--theme-border)" }}
      >
        <label className="flex items-center gap-2">
          <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
            publisher
          </span>
          <select
            className={selectClass}
            style={{ borderColor: "var(--theme-border)" }}
            value={filter.publisher ?? ""}
            onChange={(event) =>
              update({ publisher: event.target.value || undefined })
            }
          >
            <option value="">all ({forecasts.length})</option>
            {publisherOptions.map((option) => (
              <option key={option.slug} value={option.slug}>
                {option.label} ({option.count})
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
            country
          </span>
          <select
            className={selectClass}
            style={{ borderColor: "var(--theme-border)" }}
            value={filter.country ?? ""}
            onChange={(event) =>
              update({ country: event.target.value || undefined })
            }
          >
            <option value="">all</option>
            {countryOptions.map(([code, count]) => (
              <option key={code} value={code}>
                {COUNTRY_LABEL[code]} ({count})
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
            status
          </span>
          <select
            className={selectClass}
            style={{ borderColor: "var(--theme-border)" }}
            value={filter.status ?? ""}
            onChange={(event) =>
              update({
                status:
                  event.target.value === "pending" ||
                  event.target.value === "resolved"
                    ? event.target.value
                    : undefined,
              })
            }
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-[180px] flex-1 items-center gap-2">
          <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
            search
          </span>
          <input
            className={`${selectClass} w-full`}
            style={{ borderColor: "var(--theme-border)" }}
            type="search"
            placeholder="filter by title"
            value={filter.query ?? ""}
            onChange={(event) =>
              update({ query: event.target.value || undefined })
            }
          />
        </label>
        {hasActiveFilter && (
          <button
            type="button"
            className="[font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--color-accent)]"
            onClick={() =>
              update({
                publisher: undefined,
                country: undefined,
                status: undefined,
                query: undefined,
              })
            }
          >
            clear ×
          </button>
        )}
      </div>
      {hasActiveFilter && (
        <p className="mb-6 [font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          showing {sortedForecasts.length} of {forecasts.length} forecasts
        </p>
      )}

      <nav
        aria-label="Forecast sections"
        className="mb-8 flex flex-wrap items-center gap-1 rounded-xl border bg-[var(--theme-bg-elevated)] p-1.5"
        style={{ borderColor: "var(--theme-border)" }}
      >
        {SECTIONS.map((section) => (
          <Link
            key={section.key}
            href={`#${section.key}-forecasts`}
            className="flex items-center gap-2 rounded-lg px-3 py-1.5 [font-family:var(--font-body)] text-[0.85rem] text-[var(--theme-text-muted)] no-underline transition-colors hover:text-[var(--theme-text)] hover:no-underline"
          >
            <span>{section.label}</span>
            <span className="[font-family:var(--font-mono)] text-[0.7rem] text-[var(--theme-text-dim)]">
              {
                sortedForecasts.filter(
                  (forecast) => forecast.type === section.key,
                ).length
              }
            </span>
          </Link>
        ))}
      </nav>

      {SECTIONS.map((section) => {
        const sectionForecasts = sortedForecasts.filter(
          (forecast) => forecast.type === section.key,
        );
        return (
          <section
            className="mb-14 scroll-mt-6"
            id={`${section.key}-forecasts`}
            key={section.key}
          >
            <div className="mb-6 max-w-[680px]">
              <h2 className="mb-2 [font-family:var(--font-display)] text-[1.25rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
                {section.label}
              </h2>
              <p className="text-[0.9rem] text-[var(--theme-text-muted)]">
                {section.description} Showing {sectionForecasts.length}{" "}
                predictions, sorted by earliest expected resolution.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
              {sectionForecasts.map((forecast) => (
                <ForecastCard key={forecast.slug} forecast={forecast} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function compareByResolutionDate(
  a: ForecastListingItem,
  b: ForecastListingItem,
) {
  return a.resolutionDate.localeCompare(b.resolutionDate);
}
