import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Header } from "@/components/Header";
import {
  BillForecasts,
  type BillForecastView,
} from "@/components/BillForecasts";
import { ComputeCard } from "@/components/ComputeCard";
import { ProvisionAnalysis } from "@/components/ProvisionAnalysis";
import {
  getBillForecastGroups,
  getBillContextSeriesLinks,
  getPendingConditionals,
} from "@/data/bill-forecasts";
import {
  CHRONICLE_CATALOG_URL,
  REGISTRY_LABEL,
  getBill,
  loadBillMeta,
  loadBillDocket,
  loadBills,
  metricRegistryStatus,
  type RegistryStatus,
} from "@/data/bills";
import { formatValue } from "@/data/forecast-cells";
import { fullSectionText } from "@/lib/bill-text";
import { resolveMetricCell } from "@/lib/metric-cells";
import { renderInline, stripRegistryNote } from "@/lib/render-inline";

export function generateStaticParams() {
  return loadBills().map((entry) => ({ slug: entry.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const entry = getBill(slug);
  if (!entry) return { title: "Bill not found — Axiom Forecasts" };
  return {
    title: `${entry.bill.name} — Axiom Forecasts bill analyses`,
    description: `Provisions, countersignable goals, likely effects, and candidate outcome metrics for ${entry.bill.name}.`,
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

/** Server-side view models for the client selector — cells stay out of the bundle. */
function buildForecastViews(billSlug: string): BillForecastView[] {
  return getBillForecastGroups(billSlug).map(
    ({ metricLabel, resolved, example }) => {
    const { group, trueArm, falseArm, probability, unconditional } = resolved;
    const pct = probability?.pointEstimate;
    return {
      metricLabel,
      example,
      groupSlug: group.slug,
      question: group.question,
      eventLabel: group.eventLabel,
      nonExhaustivePair: group.nonExhaustivePair === true,
      // Larger arm first so the rendered equation is arithmetically true
      // whichever direction the forecasted effect points.
      gapLabel: falseArm
        ? (() => {
            const [hi, lo] =
              trueArm.pointEstimate >= falseArm.pointEstimate
                ? [trueArm, falseArm]
                : [falseArm, trueArm];
            return `${formatValue(hi.pointEstimate, hi.unit)} − ${formatValue(
              lo.pointEstimate,
              lo.unit,
            )} = ${formatValue(
              hi.pointEstimate - lo.pointEstimate,
              trueArm.unit,
            )}`;
          })()
        : undefined,
      gapNote: group.gapNote,
      probability:
        probability && pct !== undefined
          ? { pct, slug: probability.slug }
          : undefined,
      enacted: {
        point: trueArm.pointEstimate,
        ciLow: trueArm.ciLow,
        ciHigh: trueArm.ciHigh,
        pointLabel: formatValue(trueArm.pointEstimate, trueArm.unit),
        ciLabel: `${formatValue(trueArm.ciLow, trueArm.unit)} – ${formatValue(
          trueArm.ciHigh,
          trueArm.unit,
        )}`,
        slug: trueArm.slug,
      },
      baseline: falseArm ? {
        point: falseArm.pointEstimate,
        ciLow: falseArm.ciLow,
        ciHigh: falseArm.ciHigh,
        pointLabel: formatValue(falseArm.pointEstimate, falseArm.unit),
        ciLabel: `${formatValue(falseArm.ciLow, falseArm.unit)} – ${formatValue(
          falseArm.ciHigh,
          falseArm.unit,
        )}`,
        slug: falseArm.slug,
      } : undefined,
      unconditionalRef:
        !falseArm && unconditional ? {
        point: unconditional.pointEstimate,
        ciLow: unconditional.ciLow,
        ciHigh: unconditional.ciHigh,
        pointLabel: formatValue(unconditional.pointEstimate, unconditional.unit),
        ciLabel: `${formatValue(unconditional.ciLow, unconditional.unit)} – ${formatValue(
          unconditional.ciHigh,
          unconditional.unit,
        )}`,
        slug: unconditional.slug,
      } : undefined,
      unconditional:
        unconditional && falseArm && pct !== undefined
          ? {
              valueLabel: formatValue(
                unconditional.pointEstimate,
                unconditional.unit,
              ),
              formula: `${Math.round(pct)}% × ${formatValue(
                trueArm.pointEstimate,
                trueArm.unit,
              )} + ${Math.round(100 - pct)}% × ${formatValue(
                falseArm.pointEstimate,
                falseArm.unit,
              )} = ${formatValue(unconditional.pointEstimate, unconditional.unit)}`,
              slug: unconditional.slug,
            }
          : undefined,
    };
  });
}

const registryBadgeClass: Record<RegistryStatus, string> = {
  reachable: "bg-[#E8F4EA] text-[#1F6B33] border-[#BFDEC7]",
  "not-yet": "bg-[#FFF4DD] text-[#7A5C20] border-[#F2DCAF]",
  ambiguous: "bg-[#FFF4DD] text-[#7A5C20] border-[#F2DCAF]",
  unknown: "bg-transparent text-[var(--theme-text-dim)] border-[var(--theme-border)]",
};

export default async function BillDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const entry = getBill(slug);
  if (!entry) notFound();
  const forecastViews = buildForecastViews(slug);
  const pendingConditionals = getPendingConditionals(slug);
  const rawMeta = loadBillMeta(slug);
  const docket = loadBillDocket();
  // Unconditional cells on the bill's candidate series — the series
  // forecast regardless of this bill, deduped across provisions, each
  // carrying which provision/metric makes the series a candidate.
  const cellSources = new Map<
    string,
    { cell: NonNullable<ReturnType<typeof resolveMetricCell>>; from: string[] }
  >();
  for (const provision of entry.provisions) {
    for (const metric of provision.metrics) {
      const mapping = metricRegistryStatus(metric, docket);
      const cell = resolveMetricCell(mapping.series);
      if (!cell) continue;
      const source = `${provision.title} · ${metric.kind}`;
      const existing = cellSources.get(cell.slug) ?? { cell, from: [] };
      if (!existing.from.includes(source)) existing.from.push(source);
      cellSources.set(cell.slug, existing);
    }
  }
  const unconditionalCells = [...cellSources.values()];
  // Explicitly context-only linkage: registered series the docket
  // tracks because this bill made them worth watching. Never a
  // resolution of a bill metric — each link's scopeNote is rendered
  // verbatim so the boundary lives on the page.
  const contextBillSlugs = [
    ...new Set(
      [slug, entry.bill.slug].filter(
        (candidate): candidate is string => Boolean(candidate),
      ),
    ),
  ];
  const contextSeriesLinks = contextBillSlugs
    .flatMap((billSlug) => getBillContextSeriesLinks(billSlug))
    .map((link) => ({ link, cell: resolveMetricCell(link.seriesConcept) }));
  const computeRows = entry.provisions.flatMap((p) => p.compute ?? []);
  // Hints and proposal annotations are not evidence of docket admission.
  const allMetrics = entry.provisions.flatMap((p) => p.metrics);
  const admittedMetrics = allMetrics.filter(
    (metric) => metricRegistryStatus(metric, docket).status === "reachable",
  );
  const remainingMetrics = allMetrics.length - admittedMetrics.length;

  return (
    <div>
      <Header activePage="bills" />
      <main className="mx-auto max-w-[1100px] px-8 pb-32 pt-10 max-md:px-5">
        <nav className="mb-6 [font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.12em]">
          <Link
            href="/bills"
            className="text-[var(--theme-text-muted)] hover:text-[var(--color-accent)] no-underline"
          >
            ← all bills
          </Link>
        </nav>

        <header className="mb-12">
          <p className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.15em] text-[var(--color-accent)] mb-3">
            {entry.bill.status}
          </p>
          <h1 className="[font-family:var(--font-display)] text-[clamp(1.7rem,3.5vw,2.4rem)] font-light leading-[1.2] tracking-[-0.02em] text-[var(--theme-text)] mb-5">
            {entry.bill.name}
          </h1>
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={entry.bill.sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-full border border-[var(--theme-border)] bg-[var(--theme-surface)] px-3 py-[5px] [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.08em] text-[var(--theme-text-muted)] no-underline transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] hover:no-underline"
            >
              Bill text ↗
            </a>
            {rawMeta?.axiomDashboardUrl && (
              <a
                href={rawMeta.axiomDashboardUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 rounded-full border border-[var(--theme-border)] bg-[var(--theme-surface)] px-3 py-[5px] [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.08em] text-[var(--theme-text-muted)] no-underline transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] hover:no-underline"
              >
                Axiom bills ↗
              </a>
            )}
            <span className="ml-1 [font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
              analyzed {entry.bill.analysisDate}
            </span>
          </div>
        </header>

        <section aria-label="Metric mapping progress" className="mb-8">
          <p className="m-0 text-[0.9rem] leading-[1.6] text-[var(--theme-text-muted)]">
            {admittedMetrics.length} of {allMetrics.length} candidate outcome
            metrics map to the current docket at site build time.
            {remainingMetrics > 0 && (
              <>
                {" "}{remainingMetrics} remain on the mapping and admission worklist,
                with next steps shown on each metric below.
              </>
            )}
            {" "}Series admission and published forecasts are tracked separately.
          </p>
        </section>

        <section className="mb-14">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <span className="inline-block rounded-full border border-[#D8C7EE] bg-[#F4EDFC] px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em] text-[#5B3E86]">
              Conditional forecasts
            </span>
          </div>
          {forecastViews.length > 0 && <BillForecasts views={forecastViews} />}

          {pendingConditionals.length > 0 && (
            <div className={forecastViews.length > 0 ? "mt-5 grid gap-3" : "grid gap-3"}>
              {pendingConditionals.map((item, i) => (
                <div
                  key={i}
                  className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-surface)] px-6 py-5"
                >
                  <div className="mb-2">
                    <span
                      className={`inline-block rounded-full border px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.08em] ${
                        item.status === "refused"
                          ? "border-[#E5C8C0] bg-[#F9EFEC] text-[#93412A]"
                          : "border-[#F2DCAF] bg-[#FFF4DD] text-[#7A5C20]"
                      }`}
                    >
                      {item.status === "refused"
                        ? "Forecast refused — fail-closed"
                        : "Forecast pending"}
                    </span>
                  </div>
                  <p className="m-0 max-w-[820px] text-[0.95rem] leading-[1.6] text-[var(--theme-text)]">
                    {item.question}
                  </p>
                  {item.note && (
                    <p className="m-0 mt-2 max-w-[820px] text-[0.85rem] italic leading-[1.6] text-[var(--theme-text-muted)]">
                      {item.note}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          {forecastViews.length === 0 && pendingConditionals.length === 0 && (
            <div className="rounded-xl border border-dashed border-[var(--theme-border)] px-6 py-5 text-[0.9rem] leading-[1.6] text-[var(--theme-text-muted)]">
              {admittedMetrics.length === 0 ? (
                <>
                  The analysis found {allMetrics.length} candidate outcome{" "}
                  {allMetrics.length === 1 ? "metric" : "metrics"} for this
                  bill; none maps to an admitted series in the docket registry
                  yet, so no enacted-vs-baseline pair can be preregistered.
                  When a metric&apos;s series is admitted and a pair is
                  registered through the privileged path, both arms — enacted
                  and baseline — appear here; only the arm whose registered
                  condition is satisfied is scored publicly.
                </>
              ) : (
                <>
                  {admittedMetrics.length} of {allMetrics.length} candidate{" "}
                  metrics map to admitted series, but no enacted-vs-baseline
                  pair is registered for this bill yet. Pairs are registered
                  only through the privileged path; when one lands, both arms
                  appear here, and only the arm whose registered condition is
                  satisfied is scored publicly.
                </>
              )}
            </div>
          )}

          {unconditionalCells.length > 0 && (
            <div className="mt-5">
              <h3 className="[font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] mb-3">
                Live forecasts on this bill&apos;s candidate series —
                unconditional
              </h3>
              <div className="divide-y divide-[var(--theme-border)] rounded-xl border border-[var(--theme-border)] bg-[var(--theme-surface)]">
                {unconditionalCells.map(({ cell, from }) => {
                  const span = cell.ciHigh - cell.ciLow || 1;
                  const lo = cell.ciLow - span * 0.15;
                  const width = span * 1.3;
                  const pos = (v: number) => `${((v - lo) / width) * 100}%`;
                  return (
                    <Link
                      key={cell.slug}
                      href={`/${cell.slug}?from=/bills/${slug}`}
                      className="grid grid-cols-[minmax(0,1fr)_240px] items-center gap-8 px-5 py-4 text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline max-md:grid-cols-1 max-md:gap-3"
                    >
                      <div>
                        <p className="m-0 text-[0.95rem] font-medium leading-[1.5]">
                          {cell.title}
                        </p>
                        <p className="m-0 mt-1 max-w-[640px] text-[0.85rem] leading-[1.55] text-[var(--theme-text-muted)]">
                          {cell.question}
                        </p>
                      </div>
                      <div>
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                            Current forecast
                          </span>
                          <span className="[font-family:var(--font-display)] text-[1.35rem] font-normal leading-none">
                            {cell.pointLabel}
                          </span>
                        </div>
                        <div className="relative mt-2 h-4">
                          <div className="absolute inset-y-[7px] left-0 right-0 rounded-full bg-[var(--theme-border)] opacity-40" />
                          <div
                            className="absolute inset-y-[5px] rounded-full bg-[#4C9A74] opacity-45"
                            style={{
                              left: pos(cell.ciLow),
                              width: `${(span / width) * 100}%`,
                            }}
                          />
                          <div
                            className="absolute top-1/2 h-[11px] w-[11px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--theme-surface)] bg-[#4C9A74]"
                            style={{ left: pos(cell.point) }}
                          />
                        </div>
                        <div className="mt-1.5 flex items-baseline justify-between gap-3">
                          <span className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                            80% interval
                          </span>
                          <span className="[font-family:var(--font-mono)] text-[0.65rem] text-[var(--theme-text-muted)]">
                            {cell.ciLabel}
                          </span>
                        </div>
                        <div className="mt-1 flex items-baseline justify-between gap-3">
                          <span className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                            Resolves
                          </span>
                          <span className="[font-family:var(--font-mono)] text-[0.65rem] text-[var(--theme-text-muted)]">
                            {cell.resolutionDate} →
                          </span>
                        </div>
                      </div>
                    </Link>
                  );
                })}
              </div>
            </div>
          )}

          {contextSeriesLinks.length > 0 && (
            <div className="mt-5">
              <h3 className="[font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] mb-3">
                Registered context series — forecast regardless of this bill
              </h3>
              <p className="m-0 mb-3 max-w-[680px] text-[0.8rem] leading-[1.6] text-[var(--theme-text-muted)]">
                These series are tracked because the bill made them worth
                watching. They are not resolutions of any bill metric; each
                entry states what the series is not.
              </p>
              <div className="divide-y divide-[var(--theme-border)] rounded-xl border border-[var(--theme-border)] bg-[var(--theme-surface)]">
                {contextSeriesLinks.map(({ link, cell }) => (
                  <div key={link.seriesConcept} className="px-5 py-4">
                    {cell ? (
                      <Link
                        href={`/${cell.slug}?from=/bills/${slug}`}
                        className="grid grid-cols-[minmax(0,1fr)_240px] items-center gap-8 text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline max-md:grid-cols-1 max-md:gap-3"
                      >
                        <div>
                          <p className="m-0 text-[0.95rem] font-medium leading-[1.5]">
                            {cell.title}
                          </p>
                          <p className="m-0 mt-1 max-w-[640px] text-[0.85rem] leading-[1.55] text-[var(--theme-text-muted)]">
                            {cell.question}
                          </p>
                        </div>
                        <div>
                          <div className="flex items-baseline justify-between gap-3">
                            <span className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                              Current forecast
                            </span>
                            <span className="[font-family:var(--font-display)] text-[1.35rem] font-normal leading-none">
                              {cell.pointLabel}
                            </span>
                          </div>
                          <div className="mt-1.5 flex items-baseline justify-between gap-3">
                            <span className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                              80% interval
                            </span>
                            <span className="[font-family:var(--font-mono)] text-[0.65rem] text-[var(--theme-text-muted)]">
                              {cell.ciLabel}
                            </span>
                          </div>
                          <div className="mt-1 flex items-baseline justify-between gap-3">
                            <span className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                              Resolves
                            </span>
                            <span className="[font-family:var(--font-mono)] text-[0.65rem] text-[var(--theme-text-muted)]">
                              {cell.resolutionDate} →
                            </span>
                          </div>
                        </div>
                      </Link>
                    ) : (
                      <div>
                        <p className="m-0 text-[0.95rem] font-medium leading-[1.5]">
                          {link.label}
                        </p>
                        <p className="m-0 mt-1 text-[0.8rem] leading-[1.55] text-[var(--theme-text-muted)]">
                          {link.pendingForecastLane === "ticketed-attested" ? (
                            <>
                              Admitted to the docket — awaiting ticketed
                              registration and generation through the attested
                              lane.
                            </>
                          ) : (
                            <>
                              Admitted to the docket — the first registered
                              forecast arrives with the next roll.
                            </>
                          )}
                        </p>
                      </div>
                    )}
                    <p className="m-0 mt-2 max-w-[680px] text-[0.75rem] leading-[1.6] text-[var(--theme-text-dim)]">
                      {link.scopeNote}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {computeRows.length > 0 && (
            <div className="mt-5">
              <h3 className="[font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] mb-3">
                Computed impact — Axiom Simulator
              </h3>
              <div className="grid gap-3">
                {computeRows.map((row, i) => (
                  <ComputeCard key={i} row={row} />
                ))}
              </div>
            </div>
          )}
        </section>

        <section>
          <h2 className="mb-5 [font-family:var(--font-mono)] text-[0.75rem] uppercase tracking-[0.14em] text-[var(--theme-text)]">
            Provisions
          </h2>

          <div className="grid gap-3">
            {entry.provisions.map((provision, index) => {
              const sectionText = fullSectionText(
                entry.slug,
                provision.heading,
                provision.title,
              );
              return (
              <details
                key={index}
                className="group rounded-xl border border-[var(--theme-border)] bg-[var(--theme-surface)]"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4 [&::-webkit-details-marker]:hidden">
                  <div className="min-w-0">
                    <p className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] mb-1">
                      {provision.title}
                    </p>
                    <h3 className="[font-family:var(--font-display)] text-[1.05rem] font-normal leading-[1.35] text-[var(--theme-text)]">
                      {provision.heading}
                    </h3>
                  </div>
                  <span
                    aria-hidden
                    className="shrink-0 text-[var(--theme-text-dim)] transition-transform group-open:rotate-90"
                  >
                    ›
                  </span>
                </summary>

                <div className="border-t border-[var(--theme-border)] px-5 py-6">
                  {provision.context && (
                    <p className="mb-5 max-w-[820px] text-[0.92rem] leading-[1.65] text-[var(--theme-text-muted)]">
                      {renderInline(provision.context)}
                    </p>
                  )}

                  {provision.quote && (
                    <details className="mb-6">
                      <summary className="cursor-pointer list-none [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.1em] text-[var(--color-accent)] [&::-webkit-details-marker]:hidden">
                        Quoted from the bill ▸
                      </summary>
                      <blockquote className="mt-3 border-l-2 border-[var(--color-accent)] pl-4 text-[0.9rem] italic leading-[1.6] text-[var(--theme-text-muted)]">
                        {renderInline(provision.quote)}
                      </blockquote>
                    </details>
                  )}

                  {sectionText && (
                    <details className="mb-6">
                      <summary className="cursor-pointer list-none [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.1em] text-[var(--color-accent)] [&::-webkit-details-marker]:hidden">
                        Full section text ▸
                      </summary>
                      <pre className="mt-3 max-h-[420px] overflow-auto whitespace-pre-wrap rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg)] p-4 [font-family:var(--font-mono)] text-[0.75rem] leading-[1.55] text-[var(--theme-text-muted)]">
                        {sectionText}
                      </pre>
                    </details>
                  )}

                  <ProvisionAnalysis
                    billSlug={slug}
                    provisionIndex={index}
                    goals={provision.goals}
                    effects={provision.effects}
                    barriers={provision.barriers}
                    metrics={provision.metrics.map((metric) => {
                      const mapping = metricRegistryStatus(metric, docket);
                      const liveCell = resolveMetricCell(mapping.series);
                      return {
                        kind: metric.kind,
                        text: stripRegistryNote(metric.text),
                        badgeLabel: REGISTRY_LABEL[mapping.status],
                        badgeClass: registryBadgeClass[mapping.status],
                        registry: {
                          note: mapping.note,
                          series: mapping.series,
                          candidates: mapping.candidates,
                          analysisSnapshot: metric.registry
                            ? `${metric.registry} (${entry.bill.analysisDate})`
                            : undefined,
                          chronicle: mapping.ledger
                            ? { ...mapping.ledger, href: CHRONICLE_CATALOG_URL }
                            : undefined,
                        },
                        rationale: metric.rationale,
                        stances: metric.stances,
                        forecast: liveCell
                          ? {
                              ...liveCell,
                              href: `/${liveCell.slug}?from=/bills/${slug}`,
                            }
                          : undefined,
                      };
                    })}
                    conditionals={provision.conditionals}
                  />
                </div>
              </details>
              );
            })}
          </div>
        </section>
      </main>
    </div>
  );
}
