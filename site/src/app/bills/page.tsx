import type { Metadata } from "next";
import Link from "next/link";
import { Header } from "@/components/Header";
import { loadBills } from "@/data/bills";

export const metadata: Metadata = {
  title: "Bill analyses — Axiom Forecasts",
  description:
    "Bills as forecasting input: provisions, countersignable goals, likely effects, and the outcome metrics the political system is about to bet on.",
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

export default function BillsIndexPage() {
  const bills = loadBills();

  return (
    <div>
      <Header activePage="bills" />
      <main className="mx-auto max-w-[1100px] px-8 pb-32 pt-12 max-md:px-5">
        <section className="mb-12 max-w-[760px]">
          <p className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.15em] text-[var(--color-accent)] mb-3">
            Axiom Forecasts · bill analyses
          </p>
          <h1 className="[font-family:var(--font-display)] text-[clamp(1.8rem,4vw,2.6rem)] font-light leading-[1.15] tracking-[-0.02em] text-[var(--theme-text)] mb-5">
            Start from the bill, derive the outcomes
          </h1>
          <p className="text-[1rem] leading-[1.65] text-[var(--theme-text-muted)]">
            Each analysis reads a bill&apos;s provisions and separates what its
            authors would sign their names to (countersignable goals) from what
            the text does regardless (likely effects), then maps candidate
            outcome metrics against the live forecast registry.
          </p>
        </section>

        <section className="grid gap-5">
          {bills.map((entry) => {
            const metricCount = entry.provisions.reduce(
              (sum, provision) => sum + provision.metrics.length,
              0,
            );
            return (
              <Link
                key={entry.slug}
                href={`/bills/${entry.slug}`}
                className="block rounded-xl border border-[var(--theme-border)] bg-[var(--theme-surface)] p-6 no-underline transition-colors hover:border-[var(--color-accent)]"
              >
                <p className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] mb-2">
                  {entry.bill.status}
                </p>
                <h2 className="[font-family:var(--font-display)] text-[1.3rem] font-normal leading-[1.3] text-[var(--theme-text)] mb-3">
                  {entry.bill.name}
                </h2>
                <p className="text-[0.9rem] leading-[1.6] text-[var(--theme-text-muted)] mb-4">
                  {entry.bill.analyzed} · {entry.bill.pages.toLocaleString()}{" "}
                  pages · analyzed {entry.bill.analysisDate}
                </p>
                <p className="[font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                  {entry.provisions.length} provisions · {metricCount} candidate
                  metrics
                </p>
              </Link>
            );
          })}
          {bills.length === 0 && (
            <p className="text-[0.95rem] text-[var(--theme-text-muted)]">
              No bill analyses yet.
            </p>
          )}
        </section>
      </main>
    </div>
  );
}
