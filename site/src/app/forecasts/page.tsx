import { getPublishedForecasts } from "@/lib/forecast-publication";
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { Header } from "@/components/Header";
import { ForecastBrowser } from "@/components/ForecastBrowser";
import { buildForecastListing } from "@/data/forecast-listing";
import {
  loadPolicyEngineLedger,
  withResolvedOutcomes,
} from "@/data/thesis-log";

export const metadata: Metadata = {
  title: "Policy forecasts — Thesis Institute",
  description:
    "Open forecasts on government statistics, policy states like the federal minimum wage, and outcomes conditional on those policy states. The audit trails, data, and everything else are visible.",
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

export default async function ForecastsPage() {
  const ledger = await loadPolicyEngineLedger();
  const forecasts = withResolvedOutcomes(getPublishedForecasts(), ledger);

  return (
    <div>
      <Header activePage="forecasts" />
      <main className="mx-auto max-w-[1200px] px-8 pb-32 pt-12 max-md:px-5">
        <section className="mb-12 max-w-[760px]">
          <p className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.15em] text-[var(--color-accent)] mb-3">
            Thesis Institute · policy futures
          </p>
          <h1 className="[font-family:var(--font-display)] text-[clamp(1.9rem,4vw,2.6rem)] font-light leading-[1.15] tracking-[-0.02em] text-[var(--theme-text)] mb-5">
            Forecasts on every consequential cell of government data
          </h1>
          <p className="text-[1.05rem] leading-[1.65] text-[var(--theme-text-muted)]">
            Thesis provides three types of forecasts:{" "}
            <strong>government statistics</strong>,{" "}
            <strong>policy states</strong> (like the federal minimum wage), and{" "}
            <strong>conditional forecasts</strong> <em>given</em> different
            policy states. The audit trails, data, and everything else are
            visible.
          </p>
          <div className="mt-5 flex flex-wrap gap-4">
            <Link
              href="/log"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--color-accent)] no-underline hover:no-underline"
            >
              View Thesis Log →
            </Link>
            <Link
              href="/ledger"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            >
              View facts ledger →
            </Link>
            <Link
              href="/forecasts/targets"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            >
              View target architecture →
            </Link>
            <Link
              href="/briefings"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            >
              View prediction packs →
            </Link>
          </div>
        </section>
        <Suspense>
          <ForecastBrowser forecasts={buildForecastListing(forecasts)} />
        </Suspense>
        <section
          className="mt-16 rounded-xl border bg-[var(--theme-bg-surface)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <p className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.15em] text-[var(--theme-text-dim)] mb-2">
            How forecasts are generated
          </p>
          <p className="text-[0.92rem] leading-[1.65] text-[var(--theme-text)]">
            Published forecasts have successful recorded runs, validated
            outputs, and matching activity artifacts. Open a forecast to read
            its analysis and inspect the underlying run records. Prototype
            estimates and failure fallbacks are excluded.
          </p>
        </section>
      </main>
    </div>
  );
}
