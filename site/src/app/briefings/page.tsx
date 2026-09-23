import type { Metadata } from "next";
import Link from "next/link";
import { Header } from "@/components/Header";
import { buildPredictionPackCatalog } from "@/data/prediction-packs";

const PACK_OVERVIEW_POINTS = [
  {
    label: "Run input",
    value:
      "Selected per forecast run and stored in the prediction record as packId@version.",
  },
  {
    label: "Comparable",
    value:
      "Designed to be tested against no-pack controls or other pack sets on the same target.",
  },
  {
    label: "Scorable",
    value:
      "Travels with the run through resolution, scoring, and postmortem analysis.",
  },
];

export const metadata: Metadata = {
  title: "Briefings — Axiom Forecasts",
  description:
    "Browse the briefing library — versioned bundles of curated reference material handed to forecasters, with their purpose, checks, versions, and forecast runs.",
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

export default function PacksPage() {
  const packs = buildPredictionPackCatalog();
  const runCount = packs.reduce((total, pack) => total + pack.runCount, 0);
  const targetCount = new Set(
    packs.flatMap((pack) => pack.usage.map((usage) => usage.forecastSlug)),
  ).size;

  return (
    <div>
      <Header activePage="briefings" />
      <main className="mx-auto max-w-[1200px] px-8 pb-32 pt-12 max-md:px-5">
        <section className="mb-12 max-w-[760px]">
          <p className="mb-3 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.15em] text-[var(--color-accent)]">
            Axiom Forecasts · the briefing library
          </p>
          <h1 className="mb-5 [font-family:var(--font-display)] text-[clamp(1.9rem,4vw,2.6rem)] font-light leading-[1.15] tracking-[-0.02em] text-[var(--theme-text)]">
            Briefings: versioned material handed to forecasters
          </h1>
          <p className="text-[1.05rem] leading-[1.65] text-[var(--theme-text-muted)]">
            A briefing hands a forecaster curated evidence, calibration rules, and
            checks up front — research stays fully open with or without it, so
            briefed-versus-unbriefed contrasts measure the value of curation,
            not information access. Recorded as packId@version until the
            identifier migration. Each briefing page shows
            the pack's current version, how it is applied, and the runs where it
            appears.
          </p>
        </section>

        <section className="mb-10 grid grid-cols-3 gap-6 border-y border-[var(--theme-border)] py-6 max-md:grid-cols-1">
          {PACK_OVERVIEW_POINTS.map((point) => (
            <div key={point.label}>
              <div className="mb-2 [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                {point.label}
              </div>
              <p className="text-[0.86rem] leading-[1.6] text-[var(--theme-text-muted)]">
                {point.value}
              </p>
            </div>
          ))}
        </section>

        <section className="mb-10 grid grid-cols-3 gap-4 max-sm:grid-cols-1">
          <PackIndexStat label="packs" value={packs.length} />
          <PackIndexStat label="runs using packs" value={runCount} />
          <PackIndexStat label="targets" value={targetCount} />
        </section>

        <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {packs.map((pack) => (
            <Link
              className="rounded-xl border bg-[var(--theme-bg-elevated)] p-5 no-underline transition-colors hover:border-[var(--color-horizon-300)] hover:no-underline"
              href={`/briefings/${pack.packId}`}
              key={pack.packId}
              style={{ borderColor: "var(--theme-border)" }}
            >
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-[var(--theme-border)] px-2 py-[2px] [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
                  {pack.kind}
                </span>
                <span className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
                  v{pack.latestVersion}
                </span>
                <span className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.08em] text-[var(--color-accent)]">
                  {pack.runCount > 0 ? "run input" : "registered"}
                </span>
              </div>
              <h2 className="mb-3 [font-family:var(--font-display)] text-[1rem] font-semibold leading-[1.3] text-[var(--theme-text)]">
                {pack.label}
              </h2>
              <p className="mb-5 text-[0.86rem] leading-[1.55] text-[var(--theme-text-muted)]">
                {pack.summary}
              </p>
              <div className="grid grid-cols-2 gap-3 border-t border-[var(--theme-border)] pt-4">
                <MiniMetric label="runs" value={pack.runCount} />
                <MiniMetric label="agents" value={pack.agents.length} />
              </div>
            </Link>
          ))}
        </section>
      </main>
    </div>
  );
}

function PackIndexStat({ label, value }: { label: string; value: number }) {
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

function MiniMetric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="[font-family:var(--font-display)] text-[1.1rem] font-semibold leading-none text-[var(--color-accent)]">
        {value}
      </div>
      <div className="mt-1 [font-family:var(--font-mono)] text-[0.54rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
        {label}
      </div>
    </div>
  );
}
