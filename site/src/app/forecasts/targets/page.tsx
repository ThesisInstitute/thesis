import type { Metadata } from "next";
import Link from "next/link";
import { Header } from "@/components/Header";
import type { ThesisTargetArchitectureProjection } from "@/data/thesis-target-architecture";
import { loadTargetArchitectureProjection } from "@/data/thesis-target-architecture-runtime";

export const metadata: Metadata = {
  title: "Target architecture — Axiom Forecasts",
  description:
    "Generated target-architecture projection for forecasts, strategies, packs, artifacts, and distributions.",
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

export default async function TargetArchitecturePage() {
  const projection = await loadTargetArchitectureProjection();
  const sourceFamilies = summarizeSourceFamilies(projection);

  return (
    <div>
      <Header activePage="forecasts" />
      <main className="mx-auto max-w-[1200px] px-8 pb-32 pt-12 max-md:px-5">
        <section className="mb-10 max-w-[780px]">
          <Link
            href="/forecasts/log"
            className="mb-5 inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
          >
            ← Forecast log
          </Link>
          <p className="mb-3 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.15em] text-[var(--color-accent)]">
            Forecast log · clean projection
          </p>
          <h1 className="mb-5 [font-family:var(--font-display)] text-[clamp(1.9rem,4vw,2.6rem)] font-light leading-[1.15] tracking-[-0.02em] text-[var(--theme-text)]">
            Target architecture
          </h1>
          <p className="text-[1.02rem] leading-[1.65] text-[var(--theme-text-muted)]">
            Generated targets, target versions, strategy versions, pack joins,
            baseline candidates, tool calls, artifact joins, distributions,
            public reasoning events, reviews, judges, resolution events, and
            score rows.
          </p>
          <div className="mt-5 flex flex-wrap gap-4">
            <a
              href="/targets.json"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--color-accent)] no-underline hover:no-underline"
            >
              Target architecture manifest →
            </a>
            <a
              href="/log.json"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            >
              Forecast log JSON →
            </a>
          </div>
        </section>

        <section className="mb-8 grid grid-cols-2 gap-4 md:grid-cols-4">
          <Metric label="targets" value={projection.counts.targets} />
          <Metric label="runs" value={projection.counts.forecastRuns} />
          <Metric
            label="strategies"
            value={projection.counts.strategyVersions}
          />
          <Metric label="artifacts" value={projection.counts.artifactRefs} />
          <Metric
            label="source series"
            value={projection.counts.sourceSeries}
          />
          <Metric label="observations" value={projection.counts.observations} />
          <Metric
            label="baselines"
            value={projection.counts.baselineCandidates}
          />
          <Metric label="tool calls" value={projection.counts.toolCalls} />
          <Metric label="resolved" value={projection.counts.resolutionEvents} />
          <Metric label="reviews" value={projection.counts.reviewRuns} />
          <Metric label="judges" value={projection.counts.judgeRuns} />
          <Metric
            label="CDF points"
            value={projection.counts.forecastDistributionPoints}
          />
          <Metric
            label="reasoning events"
            value={projection.counts.reasoningEvents}
          />
        </section>

        <section
          className="mb-8 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
              Strategy versions
            </h2>
            <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              {projection.counts.strategyVersions} rows
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-[0.86rem]">
              <thead>
                <tr className="border-b border-[var(--theme-border)] text-[var(--theme-text-dim)]">
                  <th className="py-2 pr-4 font-medium">strategy</th>
                  <th className="py-2 pr-4 font-medium">kind</th>
                  <th className="py-2 pr-4 font-medium">version</th>
                </tr>
              </thead>
              <tbody>
                {projection.forecastStrategies.map((strategy) => {
                  const version = projection.strategyVersions.find(
                    (candidate) => candidate.strategyId === strategy.strategyId,
                  );
                  return (
                    <tr
                      className="border-b border-[var(--theme-border)]"
                      key={strategy.strategyId}
                    >
                      <td className="py-3 pr-4 text-[var(--theme-text)]">
                        <div>{strategy.name}</div>
                        <div className="[font-family:var(--font-mono)] text-[0.68rem] text-[var(--theme-text-dim)]">
                          {strategy.strategyId}
                        </div>
                      </td>
                      <td className="py-3 pr-4 [font-family:var(--font-mono)] text-[0.72rem] text-[var(--theme-text-muted)]">
                        {strategy.strategyKind}
                      </td>
                      <td className="py-3 pr-4 [font-family:var(--font-mono)] text-[0.72rem] text-[var(--theme-text-muted)]">
                        {version?.versionLabel}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section
          className="rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
              Source families
            </h2>
            <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              top 12
            </span>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {sourceFamilies.slice(0, 12).map((family) => (
              <div
                className="border-b border-[var(--theme-border)] pb-3"
                key={family.sourceFamily}
              >
                <div className="text-[0.9rem] text-[var(--theme-text)]">
                  {family.sourceFamily}
                </div>
                <div className="[font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
                  {family.targets} targets · {family.sourceSeries} source series
                </div>
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div
      className="rounded-xl border bg-[var(--theme-bg-surface)] p-4"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
        {label}
      </div>
      <div className="mt-2 [font-family:var(--font-display)] text-[1.65rem] font-light text-[var(--theme-text)]">
        {value.toLocaleString("en-US")}
      </div>
    </div>
  );
}

function summarizeSourceFamilies(
  projection: ThesisTargetArchitectureProjection,
) {
  const targetCounts = new Map<string, number>();
  const sourceSeriesCounts = new Map<string, number>();
  for (const target of projection.targets) {
    targetCounts.set(
      target.sourceFamily,
      (targetCounts.get(target.sourceFamily) ?? 0) + 1,
    );
  }
  for (const sourceSeries of projection.sourceSeries) {
    sourceSeriesCounts.set(
      sourceSeries.sourceFamily,
      (sourceSeriesCounts.get(sourceSeries.sourceFamily) ?? 0) + 1,
    );
  }
  return [...targetCounts.entries()]
    .map(([sourceFamily, targets]) => ({
      sourceFamily,
      targets,
      sourceSeries: sourceSeriesCounts.get(sourceFamily) ?? 0,
    }))
    .sort(
      (left, right) =>
        right.targets - left.targets ||
        left.sourceFamily.localeCompare(right.sourceFamily),
    );
}
