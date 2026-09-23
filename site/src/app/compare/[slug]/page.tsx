import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Header } from "@/components/Header";
import { formatValue, type ForecastCell } from "@/data/forecast-cells";
import {
  CONDITIONAL_GROUPS,
  getConditionalGroup,
} from "@/data/conditional-groups";

export function generateStaticParams() {
  return CONDITIONAL_GROUPS.filter(
    (group) => getConditionalGroup(group.slug)?.falseArm,
  ).map((group) => ({ slug: group.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const resolved = getConditionalGroup(slug);
  if (!resolved) return { title: "Comparison not found — Axiom Forecasts" };
  return {
    title: `${resolved.group.title} — Axiom Forecasts conditional comparison`,
    description: resolved.group.question,
    robots: { index: false, follow: false, nocache: true },
  };
}

function ArmCard({
  label,
  labelClass,
  cell,
  weight,
}: {
  label: string;
  labelClass: string;
  cell: ForecastCell;
  weight?: number;
}) {
  return (
    <div className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-surface)] p-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <span
          className={`inline-block rounded-full border px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em] ${labelClass}`}
        >
          {label}
        </span>
        {weight !== undefined && (
          <span className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
            weight {Math.round(weight * 100)}%
          </span>
        )}
      </div>
      <div className="[font-family:var(--font-display)] text-[2.6rem] font-light leading-none text-[var(--color-accent)]">
        {formatValue(cell.pointEstimate, cell.unit)}
      </div>
      <div className="mt-2 [font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
        80% interval {formatValue(cell.ciLow, cell.unit)} –{" "}
        {formatValue(cell.ciHigh, cell.unit)}
      </div>
      <p className="mt-4 text-[0.92rem] leading-[1.6] text-[var(--theme-text-muted)]">
        {cell.conditionalOn}
      </p>
      <Link
        href={`/${cell.slug}`}
        className="mt-4 inline-block [font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--color-accent)] no-underline hover:underline"
      >
        Full cell + reasoning trace →
      </Link>
    </div>
  );
}

export default async function ComparePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const resolved = getConditionalGroup(slug);
  if (!resolved) notFound();
  const { group, trueArm, falseArm, probability, unconditional } = resolved;
  // The compare view is the two-arm presentation; single-arm groups
  // render on their bill page instead.
  if (!falseArm) notFound();
  const p = probability ? probability.pointEstimate / 100 : undefined;
  const gap = trueArm.pointEstimate - falseArm.pointEstimate;

  return (
    <div>
      <Header activePage="forecasts" />
      <main className="mx-auto max-w-[1100px] px-8 pb-32 pt-10 max-md:px-5">
        <nav className="mb-6 [font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.12em] text-[var(--theme-text-muted)]">
          <Link
            href="/forecasts"
            className="text-[var(--theme-text-muted)] hover:text-[var(--color-accent)] no-underline"
          >
            ← All forecasts
          </Link>
        </nav>

        <header className="mb-10">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <span className="inline-block rounded-full border border-[#D8C7EE] bg-[#F4EDFC] px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em] text-[#5B3E86]">
              Conditional comparison
            </span>
            <span className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)]">
              {group.nonExhaustivePair
                ? "Same outcome · two policy states · at most one arm resolves"
                : "Same outcome · two policy states · exactly one arm resolves"}
            </span>
          </div>
          <h1 className="[font-family:var(--font-display)] text-[clamp(1.7rem,3.5vw,2.4rem)] font-light leading-[1.2] tracking-[-0.02em] text-[var(--theme-text)] mb-5">
            {group.title}
          </h1>
          <p className="max-w-[820px] text-[1rem] leading-[1.65] text-[var(--theme-text-muted)]">
            {group.question}
          </p>
        </header>

        {probability && p !== undefined && (
          <div className="mb-8 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-surface)] px-6 py-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] mb-1">
                  Probability the event holds
                </div>
                <div className="text-[0.95rem] leading-[1.5] text-[var(--theme-text-muted)] max-w-[640px]">
                  {group.eventLabel}
                </div>
              </div>
              <div className="text-right">
                <div className="[font-family:var(--font-display)] text-[2.2rem] font-light leading-none text-[var(--theme-text)]">
                  {Math.round(probability.pointEstimate)}%
                </div>
                <Link
                  href={`/${probability.slug}`}
                  className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.1em] text-[var(--color-accent)] no-underline hover:underline"
                >
                  Policy cell →
                </Link>
              </div>
            </div>
            <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-[var(--theme-border)]">
              <div
                className="h-full rounded-full bg-[var(--color-accent)]"
                style={{ width: `${Math.round(probability.pointEstimate)}%` }}
              />
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-5 max-md:grid-cols-1">
          <ArmCard
            label="Event holds · true"
            labelClass="border-[#BFE3D2] bg-[#EAF7F0] text-[#1C6B4A]"
            cell={trueArm}
            weight={p}
          />
          <ArmCard
            label={
              group.nonExhaustivePair
                ? "Baseline condition holds · false arm"
                : "Event fails · false"
            }
            labelClass="border-[#F2CFC4] bg-[#FBEFEA] text-[#9A4A2D]"
            cell={falseArm}
            weight={p !== undefined ? 1 - p : undefined}
          />
        </div>

        <div className="mt-6 rounded-xl border border-dashed border-[var(--theme-border)] px-6 py-5">
          <div className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] mb-2">
            The gap is the forecasted policy effect
          </div>
          <div className="text-[1.05rem] leading-[1.6] text-[var(--theme-text)]">
            {formatValue(
              Math.max(trueArm.pointEstimate, falseArm.pointEstimate),
              trueArm.unit,
            )}{" "}
            −{" "}
            {formatValue(
              Math.min(trueArm.pointEstimate, falseArm.pointEstimate),
              falseArm.unit,
            )}{" "}
            = <strong>{formatValue(Math.abs(gap), trueArm.unit)}</strong>
            {group.gapNote ? (
              <span className="text-[var(--theme-text-muted)]">
                {" "}
                — {group.gapNote}
              </span>
            ) : null}
          </div>
        </div>

        {unconditional && p !== undefined && (
          <div className="mt-6 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-surface)] px-6 py-5">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] mb-1">
                  Implied unconditional forecast — probability-weighted mixture
                </div>
                <div className="[font-family:var(--font-mono)] text-[0.78rem] text-[var(--theme-text-muted)]">
                  {Math.round((p ?? 0) * 100)}% ×{" "}
                  {formatValue(trueArm.pointEstimate, trueArm.unit)} +{" "}
                  {Math.round((1 - (p ?? 0)) * 100)}% ×{" "}
                  {formatValue(falseArm.pointEstimate, falseArm.unit)} ={" "}
                  {formatValue(unconditional.pointEstimate, unconditional.unit)}
                </div>
              </div>
              <div className="text-right">
                <div className="[font-family:var(--font-display)] text-[2.2rem] font-light leading-none text-[var(--color-accent)]">
                  {formatValue(unconditional.pointEstimate, unconditional.unit)}
                </div>
                <Link
                  href={`/${unconditional.slug}`}
                  className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.1em] text-[var(--color-accent)] no-underline hover:underline"
                >
                  Unconditional cell →
                </Link>
              </div>
            </div>
          </div>
        )}

        <p className="mt-8 max-w-[820px] text-[0.85rem] leading-[1.6] text-[var(--theme-text-dim)]">
          {group.nonExhaustivePair
            ? "The arms' registered conditions are deliberately not " +
              "exhaustive: at most one arm resolves, and an intermediate " +
              "policy outcome resolves neither."
            : "Exactly one arm resolves, against the resolution rule on " +
              "its cell page."}{" "}
          {group.nonExhaustivePair
            ? "If an arm's condition holds when the outcome publishes, scoring covers that arm"
            : "When the outcome publishes, scoring covers the resolving arm"}
          {unconditional ? ", the unconditional mixture," : ""}
          {probability ? " and the policy-probability cell" : ""} — one outcome,
          multiple calibration receipts. Disagree with the headline? Say which
          cell you disagree with.
        </p>
      </main>
    </div>
  );
}
