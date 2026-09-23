import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Header } from "@/components/Header";
import { formatValue, type Unit } from "@/data/forecast-cells";
import {
  buildPredictionPackCatalog,
  getPredictionPackCatalogEntry,
  type PredictionPackCatalogEntry,
  type PredictionPackUsage,
} from "@/data/prediction-packs";

export function generateStaticParams() {
  return buildPredictionPackCatalog().map((pack) => ({
    briefingId: pack.packId,
  }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ briefingId: string }>;
}): Promise<Metadata> {
  const { briefingId } = await params;
  const pack = getPredictionPackCatalogEntry(briefingId);
  if (!pack) return { title: "Briefing not found — Axiom Forecasts" };

  return {
    title: `${pack.label} — Axiom Forecasts briefing`,
    description: pack.summary,
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

export default async function BriefingDetailPage({
  params,
}: {
  params: Promise<{ briefingId: string }>;
}) {
  const { briefingId } = await params;
  const pack = getPredictionPackCatalogEntry(briefingId);
  if (!pack) notFound();

  return (
    <div>
      <Header activePage="briefings" />
      <main className="mx-auto max-w-[1100px] px-8 pb-32 pt-10 max-md:px-5">
        <nav className="mb-6 [font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.12em] text-[var(--theme-text-muted)]">
          <Link
            className="text-[var(--theme-text-muted)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            href="/briefings"
          >
            ← all briefings
          </Link>
        </nav>

        <header className="mb-10">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <span className="inline-block rounded-full border border-[var(--color-horizon-300)] bg-[var(--color-horizon-50)] px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em] text-[var(--color-horizon-700)]">
              {pack.kind}
            </span>
            <span className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
              briefing · v{pack.latestVersion}
            </span>
          </div>
          <h1 className="mb-5 [font-family:var(--font-display)] text-[clamp(1.9rem,4vw,2.7rem)] font-light leading-[1.15] tracking-[-0.02em] text-[var(--theme-text)]">
            {pack.label}
          </h1>
          <p className="max-w-[860px] text-[1.05rem] leading-[1.65] text-[var(--theme-text-muted)]">
            {pack.summary}
          </p>
        </header>

        <section className="mb-10 grid grid-cols-4 gap-4 max-md:grid-cols-2 max-sm:grid-cols-1">
          <PackMetric label="runs" value={pack.runCount} />
          <PackMetric label="targets" value={pack.targetCount} />
          <PackMetric label="forecasters" value={pack.agents.length} />
          <PackMetric label="versions" value={pack.versions.length} />
        </section>

        <section className="grid grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] gap-10 max-lg:grid-cols-1">
          <PackDefinition pack={pack} />
          <PackUsageTable pack={pack} />
        </section>
      </main>
    </div>
  );
}

function PackMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="border-y border-[var(--theme-border)] py-4">
      <div className="[font-family:var(--font-display)] text-[1.7rem] font-semibold leading-none text-[var(--theme-text)]">
        {value}
      </div>
      <div className="mt-1 [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
        {label}
      </div>
    </div>
  );
}

function PackDefinition({ pack }: { pack: PredictionPackCatalogEntry }) {
  const detail = pack.detail;

  return (
    <div className="space-y-8">
      <section className="border-t border-[var(--theme-border)] pt-6">
        <h2 className="mb-3 [font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
          Purpose
        </h2>
        <p className="text-[0.92rem] leading-[1.65] text-[var(--theme-text-muted)]">
          {detail?.purpose ?? pack.summary}
        </p>
      </section>

      <PackList title="Mechanism" items={detail?.mechanism ?? []} />
      <PackList title="Checks" items={detail?.qualityChecks ?? []} />
      <PackList title="Inputs" items={detail?.inputs ?? []} />
      <PackList title="Limitations" items={detail?.limitations ?? []} />

      <section className="border-t border-[var(--theme-border)] pt-6">
        <h2 className="mb-4 [font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
          Versions
        </h2>
        <div className="space-y-3">
          {pack.versions.map((version) => (
            <div
              className="grid grid-cols-[90px_minmax(0,1fr)_80px] items-baseline gap-3 border-y border-[var(--theme-border)] py-3 max-sm:grid-cols-1"
              key={version.key}
            >
              <span className="[font-family:var(--font-mono)] text-[0.7rem] text-[var(--theme-text)]">
                v{version.version}
              </span>
              <span className="min-w-0 break-all [font-family:var(--font-mono)] text-[0.66rem] text-[var(--theme-text-dim)]">
                {version.key}
              </span>
              <span className="text-right [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)] max-sm:text-left">
                {version.usage.length} runs
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function PackList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;

  return (
    <section className="border-t border-[var(--theme-border)] pt-6">
      <h2 className="mb-4 [font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
        {title}
      </h2>
      <ul className="space-y-3">
        {items.map((item) => (
          <li
            className="flex items-start gap-3 text-[0.88rem] leading-[1.6] text-[var(--theme-text-muted)]"
            key={item}
          >
            <span className="mt-[0.7em] h-[2px] w-4 shrink-0 bg-[var(--color-accent)]" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function PackUsageTable({ pack }: { pack: PredictionPackCatalogEntry }) {
  const packSetLabel =
    pack.packSetLabels.length > 0
      ? pack.packSetLabels.join(", ")
      : "not used yet";

  return (
    <section className="border-t border-[var(--theme-border)] pt-6">
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
          Runs handed this briefing
        </h2>
        <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
          {packSetLabel}
        </span>
      </div>
      {pack.usage.length === 0 ? (
        <div className="border-y border-[var(--theme-border)] py-5">
          <p className="max-w-[620px] text-[0.88rem] leading-[1.6] text-[var(--theme-text-muted)]">
            No recorded runs yet. This briefing is registered for future
            contrasts, so its first runs can be compared against unbriefed
            controls before any promotion decision.
          </p>
        </div>
      ) : null}
      <div className="space-y-4">
        {pack.usage.map((usage) => (
          <PackUsageRow key={buildUsageKey(usage)} usage={usage} />
        ))}
      </div>
    </section>
  );
}

function PackUsageRow({ usage }: { usage: PredictionPackUsage }) {
  return (
    <article className="border-y border-[var(--theme-border)] py-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Link
            className="[font-family:var(--font-display)] text-[0.95rem] font-semibold leading-[1.3] text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            href={`/forecasts/${usage.forecastSlug}`}
          >
            {usage.forecastTitle}
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-2 [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
            <span>{usage.agent}</span>
            {usage.runAt && <span>{formatRunDate(usage.runAt)}</span>}
            <span>{usage.runLabel}</span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2 [font-family:var(--font-mono)] text-[0.56rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
            <span>{usage.packSetId}</span>
            <span>{formatPackSetMode(usage.packSetMode)}</span>
          </div>
        </div>
        <div className="text-right max-sm:text-left">
          <div className="[font-family:var(--font-display)] text-[1.45rem] font-semibold leading-none text-[var(--color-accent)]">
            {formatValue(usage.pointEstimate, usage.unit)}
          </div>
          <div className="mt-1 [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
            {formatPackDelta(usage.deltaVsNoPack, usage.unit)}
          </div>
        </div>
      </div>
      <p className="mb-3 text-[0.78rem] leading-[1.55] text-[var(--theme-text-muted)]">
        {usage.runDescription ?? usage.forecastQuestion}
      </p>
      <div className="[font-family:var(--font-mono)] text-[0.62rem] text-[var(--theme-text-dim)]">
        80% interval {formatValue(usage.interval80.lower, usage.unit)} to{" "}
        {formatValue(usage.interval80.upper, usage.unit).replace(/^\+/, "")}
      </div>
    </article>
  );
}

function buildUsageKey(usage: PredictionPackUsage) {
  return `${usage.forecastSlug}:${usage.runVariantId}:${usage.packSetId}`;
}

function formatRunDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatPackDelta(value: number | undefined, unit: Unit) {
  if (value === undefined) return "no control";
  if (value === 0) return "matches unbriefed control";
  return `${formatSignedPackValue(value, unit)} vs unbriefed`;
}

function formatPackSetMode(value: PredictionPackUsage["packSetMode"]) {
  if (value === "with_packs") return "briefed";
  if (value === "ensemble") return "ensemble";
  return value;
}

function formatSignedPackValue(value: number, unit: Unit) {
  const formatted = formatValue(Math.abs(value), unit).replace(/^\+/, "");
  return `${value > 0 ? "+" : "-"}${formatted}`;
}
