import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { BackToBill } from "@/components/BackToBill";
import { Header } from "@/components/Header";
import { ForecastRuntime } from "@/components/ForecastRuntime";
import { loadLatestSavedForecast } from "@/lib/saved-forecast";
import {
  FORECAST_CELLS,
  TYPE_LABEL,
  TYPE_DESCRIPTION,
  formatValue,
  getForecastCell,
  type ForecastCell,
} from "@/data/forecast-cells";
import {
  loadPolicyEngineLedger,
  scoreResolvedForecast,
  withResolvedOutcome,
  withResolvedOutcomes,
} from "@/data/thesis-log";

export function generateStaticParams() {
  return FORECAST_CELLS.map((forecast) => ({ slug: forecast.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const forecast = getForecastCell(slug);
  if (!forecast) return { title: "Forecast not found — Thesis Institute" };
  return {
    title: `${forecast.title} — Thesis Institute forecasts`,
    description: forecast.question,
    robots: {
      index: false,
      follow: false,
      nocache: true,
      googleBot: {
        index: false,
        follow: false,
        noimageindex: true,
      },
    },
  };
}

const typeBadgeClass: Record<ForecastCell["type"], string> = {
  data: "bg-[var(--color-mist-100)] text-[var(--color-horizon-700)] border-[var(--color-mist-200)]",
  policy:
    "bg-[var(--color-accent-subtle)] text-[var(--color-rose-700)] border-[var(--color-rose-100)]",
  conditional: "bg-[#FFF4DD] text-[#7A5C20] border-[#F2DCAF]",
};

export default async function ForecastDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const forecastDefinition = getForecastCell(slug);
  if (!forecastDefinition) notFound();

  const ledger = await loadPolicyEngineLedger();
  const forecast = withResolvedOutcome(forecastDefinition, ledger);
  const forecasts = withResolvedOutcomes(FORECAST_CELLS, ledger);
  const resolvedScore = scoreResolvedForecast(forecast, ledger);
  const savedForecast = loadLatestSavedForecast(slug);

  return (
    <div>
      <Header activePage="forecasts" />
      <main className="mx-auto max-w-[1100px] px-8 pb-32 pt-10 max-md:px-5">
        <nav className="mb-6 [font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.12em] text-[var(--theme-text-muted)]">
          <Link
            href="/"
            className="text-[var(--theme-text-muted)] hover:text-[var(--color-accent)] no-underline"
          >
            ← all forecasts
          </Link>
          <Suspense fallback={null}>
            <BackToBill />
          </Suspense>
        </nav>

        {/* Hero */}
        <header className="mb-10">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <span
              className={`inline-block rounded-full border px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em] ${typeBadgeClass[forecast.type]}`}
            >
              {TYPE_LABEL[forecast.type]}
            </span>
            <span className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
              {TYPE_DESCRIPTION[forecast.type]}
            </span>
          </div>
          <h1 className="[font-family:var(--font-display)] text-[clamp(1.7rem,3.5vw,2.4rem)] font-light leading-[1.2] tracking-[-0.02em] text-[var(--theme-text)] mb-5">
            {forecast.title}
          </h1>
          <p className="max-w-[820px] text-[1rem] leading-[1.65] text-[var(--theme-text-muted)]">
            {forecast.question}
          </p>
          {forecast.conditionalOn && (
            <p className="mt-4 inline-block rounded-md border border-[#F2DCAF] bg-[#FFF4DD] px-3 py-2 [font-family:var(--font-mono)] text-[0.72rem] text-[#7A5C20]">
              conditional on:{" "}
              <span className="font-medium">{forecast.conditionalOn}</span>
            </p>
          )}
        </header>

        <ForecastRuntime
          forecast={forecast}
          resolvedScore={resolvedScore}
          savedForecast={savedForecast}
        />

        {/* Related forecasts */}
        <RelatedForecasts
          currentSlug={forecast.slug}
          currentType={forecast.type}
          forecasts={forecasts}
        />
      </main>
    </div>
  );
}

function RelatedForecasts({
  currentSlug,
  currentType,
  forecasts,
}: {
  currentSlug: string;
  currentType: ForecastCell["type"];
  forecasts: ForecastCell[];
}) {
  const related = forecasts
    .filter(
      (forecast) =>
        forecast.slug !== currentSlug && forecast.type === currentType,
    )
    .slice(0, 3);
  if (related.length === 0) return null;
  return (
    <section
      className="mt-20 border-t pt-10"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <h2 className="[font-family:var(--font-display)] text-[1.1rem] font-semibold tracking-[-0.01em] mb-5">
        More {TYPE_LABEL[currentType].toLowerCase()} forecasts
      </h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {related.map((forecast) => (
          <Link
            key={forecast.slug}
            href={`/${forecast.slug}`}
            className="rounded-xl border bg-[var(--theme-bg-elevated)] p-5 no-underline transition-colors hover:no-underline"
            style={{ borderColor: "var(--theme-border)" }}
          >
            <div className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)] mb-2">
              resolves {formatShortDate(forecast.resolutionDate)}
            </div>
            <div className="[font-family:var(--font-display)] text-[0.95rem] font-semibold leading-[1.3] text-[var(--theme-text)] mb-3">
              {forecast.title}
            </div>
            <div className="[font-family:var(--font-display)] text-[1rem] font-semibold text-[var(--color-accent)]">
              {formatValue(forecast.pointEstimate, forecast.unit)}
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

function formatShortDate(iso: string): string {
  // Read the calendar date as written (Y/M/D before any offset) and format it
  // as UTC so a date-only resolution date like "2035-09-15" never drifts a day
  // across timezones, and server/client render identically.
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const d = new Date(
    Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])),
  );
  return d.toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}
