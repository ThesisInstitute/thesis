import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { BackToBill } from "@/components/BackToBill";
import { Header } from "@/components/Header";
import { ForecastRuntime } from "@/components/ForecastRuntime";
import {
  getPublishedForecast,
  getPublishedForecasts,
  loadForecastToolEvidence,
} from "@/lib/forecast-publication";
import {
  FORECAST_CELLS,
  TYPE_LABEL,
  formatValue,
  getForecastCell,
  getForecastRunEntries,
  type ForecastCell,
} from "@/data/forecast-cells";
import {
  loadPolicyEngineLedger,
  scoreResolvedForecast,
  scoreResolvedForecastRun,
  withResolvedOutcome,
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
  if (!forecast) return { title: "Forecast not found — Axiom Forecasts" };
  return {
    title: `${forecast.title} — Axiom Forecasts`,
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

export default async function ForecastDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const target = getForecastCell(slug);
  if (!target) notFound();
  const forecastDefinition = getPublishedForecast(slug);
  if (!forecastDefinition) return <UnavailableForecast title={target.title} />;

  const ledger = await loadPolicyEngineLedger();
  const forecast = withResolvedOutcome(forecastDefinition, ledger);
  const forecasts = getPublishedForecasts();
  const resolvedScore = scoreResolvedForecast(forecast, ledger);
  const runScores = Object.fromEntries(
    getForecastRunEntries(forecast).flatMap((run) => {
      const score = scoreResolvedForecastRun(forecast, run, ledger);
      return score ? [[run.variantId, score]] : [];
    }),
  );

  return (
    <div>
      <Header activePage="forecasts" />
      <main className="mx-auto max-w-[960px] px-8 pb-24 pt-8 max-md:px-5">
        <nav
          aria-label="Forecast navigation"
          className="mb-8 text-[0.85rem] text-[var(--theme-text-muted)]"
        >
          <Link
            href="/"
            className="text-[var(--theme-text-muted)] hover:text-[var(--color-accent)] no-underline"
          >
            ← All forecasts
          </Link>
          <Suspense fallback={null}>
            <BackToBill />
          </Suspense>
        </nav>

        <header className="mb-9">
          <p className="mb-3 text-[0.85rem] text-[var(--theme-text-muted)]">
            {TYPE_LABEL[forecast.type]}
          </p>
          <h1 className="mb-4 [font-family:var(--font-display)] text-[clamp(1.8rem,4vw,2.7rem)] font-light leading-[1.15] tracking-[-0.025em] text-[var(--theme-text)]">
            {forecast.title}
          </h1>
          <p className="max-w-[760px] text-[1rem] leading-[1.65] text-[var(--theme-text-muted)]">
            {forecast.question}
          </p>
          {forecast.conditionalOn && (
            <p className="mt-4 border-l-2 border-[var(--color-accent)] pl-3 text-[0.9rem] leading-relaxed text-[var(--theme-text-muted)]">
              Conditional on:{" "}
              <span className="font-medium">{forecast.conditionalOn}</span>
            </p>
          )}
        </header>

        <ForecastRuntime
          key={forecast.slug}
          forecast={forecast}
          resolvedScore={resolvedScore}
          runScores={runScores}
          toolEvidence={loadForecastToolEvidence(forecastDefinition)}
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

function UnavailableForecast({ title }: { title: string }) {
  return (
    <div>
      <Header activePage="forecasts" />
      <main className="mx-auto max-w-[960px] px-8 py-12 max-md:px-5">
        <Link
          href="/"
          className="text-sm text-[var(--theme-text-muted)] hover:underline"
        >
          ← All forecasts
        </Link>
        <h1 className="mt-10 [font-family:var(--font-display)] text-3xl font-light">
          {title}
        </h1>
        <section className="mt-8 border-y border-[var(--theme-border)] py-8">
          <h2 className="[font-family:var(--font-display)] text-xl">
            No forecast available
          </h2>
          <p className="mt-3 max-w-[65ch] text-[var(--theme-text-muted)] leading-relaxed">
            This target does not currently have a forecast supported by
            complete, successful run records. Prototype estimates and failed
            runs have been withdrawn from the forecast catalog.
          </p>
          <Link
            href="/"
            className="mt-5 inline-block text-[var(--color-accent)] hover:underline"
          >
            Browse available forecasts →
          </Link>
        </section>
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
      className="mt-16 border-t pt-8"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <h2 className="mb-5 [font-family:var(--font-display)] text-[1.3rem] font-semibold tracking-[-0.01em]">
        More {TYPE_LABEL[currentType].toLowerCase()} forecasts
      </h2>
      <ul className="divide-y divide-[var(--theme-border)]">
        {related.map((forecast) => (
          <li key={forecast.slug}>
            <Link
              href={`/${forecast.slug}`}
              className="group flex items-baseline justify-between gap-6 py-4 no-underline hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--color-accent)]"
            >
              <div>
                <div className="text-[0.95rem] leading-[1.45] text-[var(--theme-text)] group-hover:text-[var(--color-accent)]">
                  {forecast.title}
                </div>
                <div className="mt-1 text-[0.8rem] text-[var(--theme-text-muted)]">
                  Resolves {formatShortDate(forecast.resolutionDate)}
                </div>
              </div>
              <div className="shrink-0 [font-family:var(--font-display)] text-[1.1rem] tabular-nums text-[var(--theme-text)]">
                {formatValue(forecast.pointEstimate, forecast.unit)}
              </div>
            </Link>
          </li>
        ))}
      </ul>
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
