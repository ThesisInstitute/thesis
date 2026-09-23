import type { Metadata } from "next";
import Link from "next/link";
import { Header } from "@/components/Header";
import { formatValue } from "@/data/forecast-cells";
import type { TargetRegisteredLedgerEntry } from "@/data/ledger-targets";
import {
  buildPolicyEngineLedgerExport,
  isObservationRecordedLedgerEntry,
  isTargetRegisteredLedgerEntry,
  loadPolicyEngineLedger,
  type ObservationRecordedLedgerEntry,
} from "@/data/thesis-log";

export const metadata: Metadata = {
  title: "Ledger — Axiom Forecasts",
  description:
    "Public facts, official observations, source links, and provenance.",
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

export default async function PolicyEngineLedgerPage() {
  const ledgerEntries = await loadPolicyEngineLedger();
  const ledgerExport = buildPolicyEngineLedgerExport(ledgerEntries);
  const targetEntries = ledgerEntries.filter(isTargetRegisteredLedgerEntry);
  const observationEntries = ledgerEntries.filter(
    isObservationRecordedLedgerEntry,
  );

  return (
    <div>
      <Header activePage="log" />
      <main className="mx-auto max-w-[1200px] px-8 pb-32 pt-12 max-md:px-5">
        <section className="mb-10 max-w-[780px]">
          <Link
            href="/"
            className="mb-5 inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
          >
            ← all forecasts
          </Link>
          <p className="mb-3 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.15em] text-[var(--color-accent)]">
            PolicyEngine Ledger · targets and observations
          </p>
          <h1 className="mb-5 [font-family:var(--font-display)] text-[clamp(1.9rem,4vw,2.6rem)] font-light leading-[1.15] tracking-[-0.02em] text-[var(--theme-text)]">
            Ledger
          </h1>
          <p className="text-[1.02rem] leading-[1.65] text-[var(--theme-text-muted)]">
            Ledger records public fact targets before prediction runs, then the
            official observations that resolve them. Predictions live in
            the forecast log and point back to these fact IDs.
          </p>
          <div className="mt-5 flex flex-wrap gap-4">
            <a
              href="/ledger.json"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--color-accent)] no-underline hover:no-underline"
            >
              Machine-readable ledger JSON →
            </a>
            <a
              href="/log"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            >
              View Forecast log →
            </a>
            <a
              href="https://github.com/PolicyEngine/chronicle"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            >
              PolicyEngine ledger repo →
            </a>
          </div>
        </section>

        <section className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-3">
          <MetricCard label="facts" value={ledgerExport.counts.facts} />
          <MetricCard label="targets" value={ledgerExport.counts.targets} />
          <MetricCard
            label="observations"
            value={ledgerExport.counts.observations}
          />
        </section>

        {targetEntries.length > 0 && (
          <section
            className="mb-8 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
            style={{ borderColor: "var(--theme-border)" }}
          >
            <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
              <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
                Registered targets
              </h2>
              <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                {targetEntries.length} pending fact rows
              </span>
            </div>
            <div className="grid grid-cols-1 gap-3">
              {targetEntries.map((target) => (
                <TargetRow key={target.observationId} target={target} />
              ))}
            </div>
          </section>
        )}

        <section
          className="rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
              Official observations
            </h2>
            <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              {observationEntries.length} fact rows
            </span>
          </div>
          <div className="grid grid-cols-1 gap-3">
            {observationEntries.map((observation) => (
              <ObservationRow
                key={observation.observationId}
                observation={observation}
              />
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

function TargetRow({ target }: { target: TargetRegisteredLedgerEntry }) {
  return (
    <div
      className="rounded-lg border bg-[var(--theme-bg-surface)] p-4"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="min-w-0">
          <p className="break-all [font-family:var(--font-mono)] text-[0.72rem] text-[var(--color-horizon-700)]">
            {target.dataPointId}
          </p>
          <p className="mt-2 text-[0.92rem] leading-[1.5] text-[var(--theme-text)]">
            {target.sourceUrl ? (
              <a
                className="text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
                href={target.sourceUrl}
              >
                {target.source}
              </a>
            ) : (
              target.source
            )}
          </p>
          <p className="mt-2 text-[0.78rem] leading-[1.55] text-[var(--theme-text-muted)]">
            {target.note}
          </p>
        </div>
        <div className="text-right">
          <p className="[font-family:var(--font-display)] text-[1.25rem] font-semibold text-[var(--theme-text)]">
            {target.periodLabel}
          </p>
          <p className="[font-family:var(--font-mono)] text-[0.64rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
            {target.unit} · {target.resolutionPolicy.replace("_", " ")}
          </p>
          <p className="mt-1 [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
            resolves {formatDisplayDate(target.resolutionDate)}
          </p>
        </div>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) {
  return (
    <div
      className="rounded-xl border bg-[var(--theme-bg-elevated)] p-5"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <p className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
        {label}
      </p>
      <p className="mt-3 [font-family:var(--font-display)] text-[2rem] font-semibold leading-none text-[var(--theme-text)]">
        {value}
      </p>
    </div>
  );
}

function ObservationRow({
  observation,
}: {
  observation: ObservationRecordedLedgerEntry;
}) {
  return (
    <div
      className="rounded-lg border bg-[var(--theme-bg-surface)] p-4"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="min-w-0">
          <p className="break-all [font-family:var(--font-mono)] text-[0.72rem] text-[var(--color-horizon-700)]">
            {observation.dataPointId}
          </p>
          <p className="mt-2 text-[0.92rem] leading-[1.5] text-[var(--theme-text)]">
            {observation.sourceUrl ? (
              <a
                className="text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
                href={observation.sourceUrl}
              >
                {observation.source}
              </a>
            ) : (
              observation.source
            )}
          </p>
          {observation.note && (
            <p className="mt-2 text-[0.78rem] leading-[1.55] text-[var(--theme-text-muted)]">
              {observation.note}
            </p>
          )}
        </div>
        <div className="text-right">
          <p className="[font-family:var(--font-display)] text-[1.25rem] font-semibold text-[var(--theme-text)]">
            {formatValue(observation.value, observation.unit)}
          </p>
          <p className="[font-family:var(--font-mono)] text-[0.64rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
            {observation.periodLabel}
          </p>
          <p className="mt-1 [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
            observed {formatDisplayDate(observation.observedAt)}
          </p>
        </div>
      </div>
    </div>
  );
}

function formatDisplayDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}
