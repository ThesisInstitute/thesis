"use client";

import Link from "next/link";
import { useState } from "react";

export interface BillForecastArmView {
  pointLabel: string;
  ciLabel: string;
  point: number;
  ciLow: number;
  ciHigh: number;
  slug: string;
}

export interface BillForecastView {
  metricLabel: string;
  groupSlug: string;
  example?: boolean;
  question: string;
  eventLabel: string;
  /** Arms' conditions are not exhaustive — an intermediate outcome resolves neither. */
  nonExhaustivePair?: boolean;
  gapLabel?: string;
  gapNote?: string;
  probability?: { pct: number; slug: string };
  enacted: BillForecastArmView;
  baseline?: BillForecastArmView;
  /** Single-arm groups: the unconditional cell shown as reference, never as a baseline claim. */
  unconditionalRef?: BillForecastArmView;
  unconditional?: { valueLabel: string; formula: string; slug: string };
}

const ENACTED = {
  badge: "border-[#BFE3D2] bg-[#EAF7F0] text-[#1C6B4A]",
  band: "#4C9A74",
};
const BASELINE = {
  badge:
    "border-[var(--color-mist-200)] bg-[var(--color-mist-100)] text-[var(--theme-text-muted)]",
  band: "#8B97A5",
};

function ArmCard({
  label,
  palette,
  arm,
  weight,
}: {
  label: string;
  palette: { badge: string };
  arm: BillForecastArmView;
  weight?: number;
}) {
  return (
    <div className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-surface)] p-6">
      <div className="mb-4 flex items-center justify-between gap-3">
        <span
          className={`inline-block rounded-full border px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em] ${palette.badge}`}
        >
          {label}
        </span>
        {weight !== undefined && (
          <span className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
            weight {Math.round(weight * 100)}%
          </span>
        )}
      </div>
      <div className="[font-family:var(--font-display)] text-[2.4rem] font-light leading-none text-[var(--theme-text)]">
        {arm.pointLabel}
      </div>
      <div className="mt-2 [font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
        80% interval {arm.ciLabel}
      </div>
      <Link
        href={`/${arm.slug}`}
        className="mt-4 inline-block [font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.1em] text-[var(--color-accent)] no-underline hover:underline"
      >
        Full cell + reasoning trace →
      </Link>
    </div>
  );
}

/** Both arms' intervals on one shared axis, so the overlap is visible. */
function IntervalStrip({ view }: { view: BillForecastView }) {
  const second = view.baseline ?? view.unconditionalRef;
  const values = [
    view.enacted.ciLow,
    view.enacted.ciHigh,
    ...(second ? [second.ciLow, second.ciHigh] : []),
  ];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = span * 0.06;
  const lo = min - pad;
  const width = span + pad * 2;
  const pos = (v: number) => `${((v - lo) / width) * 100}%`;
  const bandWidth = (a: number, b: number) => `${((b - a) / width) * 100}%`;

  const rows = [
    ...(view.baseline
      ? [{ label: "Baseline", arm: view.baseline, color: BASELINE.band }]
      : view.unconditionalRef
        ? [{ label: "Uncond.", arm: view.unconditionalRef, color: BASELINE.band }]
        : []),
    { label: "Enacted", arm: view.enacted, color: ENACTED.band },
  ];

  return (
    <div className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-surface)] px-6 py-5">
      <div className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] mb-4">
        Both arms on one scale — 80% intervals
      </div>
      <div className="grid gap-3">
        {rows.map(({ label, arm, color }) => (
          <div key={label} className="flex items-center gap-4">
            <span className="w-[4.5rem] shrink-0 [font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.08em] text-[var(--theme-text-muted)]">
              {label}
            </span>
            <div className="relative h-5 flex-1">
              <div className="absolute inset-y-[9px] left-0 right-0 rounded-full bg-[var(--theme-border)] opacity-40" />
              <div
                className="absolute inset-y-[6px] rounded-full opacity-45"
                style={{
                  left: pos(arm.ciLow),
                  width: bandWidth(arm.ciLow, arm.ciHigh),
                  backgroundColor: color,
                }}
              />
              <div
                className="absolute top-1/2 h-[13px] w-[13px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--theme-surface)]"
                style={{ left: pos(arm.point), backgroundColor: color }}
              />
            </div>
            <span className="w-[5.5rem] shrink-0 text-right [font-family:var(--font-mono)] text-[0.72rem] text-[var(--theme-text)]">
              {arm.pointLabel}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function BillForecasts({ views }: { views: BillForecastView[] }) {
  const [selected, setSelected] = useState(0);
  const view = views[selected];
  if (!view) return null;
  const p =
    view.probability !== undefined ? view.probability.pct / 100 : undefined;

  return (
    <div>
      {view.example && (
        <div className="mb-5 rounded-lg border border-[#F2DCAF] bg-[#FFF9EC] px-4 py-3 text-[0.85rem] leading-[1.6] text-[#7A5C20]">
          <strong className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.1em]">
            Example rendering
          </strong>{" "}
          — these are real registered forecast pairs for other policy
          states, shown here to demonstrate the bill-forecast view. They are
          not anchored to this bill; bill-anchored pairs replace them once
          registered.
        </div>
      )}
      {views.length > 1 && (
        <div className="mb-5 flex flex-wrap gap-2">
          {views.map((v, i) => (
            <button
              key={v.groupSlug}
              type="button"
              onClick={() => setSelected(i)}
              className={`cursor-pointer rounded-full border px-3 py-[5px] [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.08em] transition-colors ${
                i === selected
                  ? "border-[var(--color-accent)] bg-[var(--color-accent-subtle)] text-[var(--color-accent)]"
                  : "border-[var(--theme-border)] bg-transparent text-[var(--theme-text-muted)] hover:border-[var(--color-accent)]"
              }`}
            >
              {v.metricLabel}
            </button>
          ))}
        </div>
      )}

      <p className="mb-5 max-w-[820px] text-[0.95rem] leading-[1.65] text-[var(--theme-text-muted)]">
        {view.question}
      </p>

      {view.probability && p !== undefined && (
        <div className="mb-5 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-surface)] px-6 py-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] mb-1">
                Probability of enactment
              </div>
              <div className="max-w-[640px] text-[0.9rem] leading-[1.5] text-[var(--theme-text-muted)]">
                {view.eventLabel}
              </div>
            </div>
            <div className="text-right">
              <div className="[font-family:var(--font-display)] text-[2rem] font-light leading-none text-[var(--theme-text)]">
                {Math.round(view.probability.pct)}%
              </div>
              <Link
                href={`/${view.probability.slug}`}
                className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.1em] text-[var(--color-accent)] no-underline hover:underline"
              >
                Policy cell →
              </Link>
            </div>
          </div>
          <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-[var(--theme-border)]">
            <div
              className="h-full rounded-full bg-[var(--color-accent)]"
              style={{ width: `${Math.round(view.probability.pct)}%` }}
            />
          </div>
        </div>
      )}

      <div
        className={`mb-5 grid gap-5 max-md:grid-cols-1 ${
          view.baseline || view.unconditionalRef ? "grid-cols-2" : "grid-cols-1"
        }`}
      >
        {view.baseline ? (
          <ArmCard
            label={
              view.nonExhaustivePair
                ? "Baseline · current law holds"
                : "Baseline · not enacted"
            }
            palette={BASELINE}
            arm={view.baseline}
            weight={p !== undefined ? 1 - p : undefined}
          />
        ) : view.unconditionalRef ? (
          <ArmCard
            label="Unconditional · bill or no bill"
            palette={BASELINE}
            arm={view.unconditionalRef}
          />
        ) : null}
        <ArmCard
          label="Conditional · bill enacted"
          palette={ENACTED}
          arm={view.enacted}
          weight={p}
        />
      </div>

      <IntervalStrip view={view} />

      {view.gapLabel && (
      <div className="mt-5 rounded-xl border border-dashed border-[var(--theme-border)] px-6 py-5">
        <div className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] mb-2">
          The gap is the forecasted effect of the bill
        </div>
        <div className="text-[1rem] leading-[1.6] text-[var(--theme-text)]">
          <strong>{view.gapLabel}</strong>
          {view.gapNote ? (
            <span className="text-[var(--theme-text-muted)]">
              {" "}
              — {view.gapNote}
            </span>
          ) : null}
        </div>
      </div>
      )}

      {view.unconditional && (
        <div className="mt-5 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-surface)] px-6 py-4">
          <div>
            <div className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] mb-1">
              Implied unconditional forecast
            </div>
            <div className="[font-family:var(--font-mono)] text-[0.75rem] text-[var(--theme-text-muted)]">
              {view.unconditional.formula}
            </div>
          </div>
          <div className="text-right">
            <div className="[font-family:var(--font-display)] text-[1.8rem] font-light leading-none text-[var(--color-accent)]">
              {view.unconditional.valueLabel}
            </div>
            <Link
              href={`/${view.unconditional.slug}`}
              className="[font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.1em] text-[var(--color-accent)] no-underline hover:underline"
            >
              Unconditional cell →
            </Link>
          </div>
        </div>
      )}

    </div>
  );
}
