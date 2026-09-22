"use client";

import { useState } from "react";
import { renderInline } from "@/lib/render-inline";
import type { StanceFold } from "@/lib/stances";

const stanceBadgeClass: Record<string, string> = {
  serves: "border-[#BFE3D2] bg-[#EAF7F0] text-[#1C6B4A]",
  opposes: "border-[#E5C8C0] bg-[#F9EFEC] text-[#93412A]",
  mixed: "border-[#F2DCAF] bg-[#FFF4DD] text-[#7A5C20]",
  orthogonal:
    "border-[var(--theme-border)] bg-transparent text-[var(--theme-text-dim)]",
  counts:
    "border-[var(--theme-border)] bg-transparent text-[var(--theme-text-muted)]",
};

function stanceLabel(stance: StanceFold): string {
  if (stance.kind !== "counts") {
    return stance.kind.charAt(0).toUpperCase() + stance.kind.slice(1);
  }
  const parts = [
    stance.serves > 0 ? `${stance.serves} serves` : null,
    stance.opposes > 0 ? `${stance.opposes} opposes` : null,
    stance.orthogonal > 0 ? `${stance.orthogonal} orthogonal` : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "No goals in force";
}

function stanceTitle(stance: StanceFold): string {
  switch (stance.kind) {
    case "serves":
      return "Serves at least one countersigned goal; opposes none";
    case "opposes":
      return "Opposes at least one countersigned goal; serves none";
    case "mixed":
      return "Serves one countersigned goal while opposing another";
    case "orthogonal":
      return "Neither serves nor opposes any countersigned goal";
    case "counts":
      return "No goals countersigned yet — raw stance counts across the goal set";
  }
}

export interface MetricRegistryView {
  note: string;
  series?: string;
  candidates?: string[];
  analysisSnapshot?: string;
  chronicle?: { uuid: string; concept: string; href: string };
}

/**
 * Candidate-metric card with the long sourcing note clamped to a few
 * lines; the full text is a click away instead of a wall by default.
 */
export function MetricCard({
  kind,
  text,
  badgeLabel,
  badgeClass,
  rationale,
  stance,
  forecast,
  registry,
}: {
  kind: string;
  text: string;
  badgeLabel: string;
  badgeClass: string;
  rationale?: string;
  stance?: StanceFold | null;
  registry?: MetricRegistryView;
  forecast?: {
    slug: string;
    href?: string;
    pointLabel: string;
    ciLabel: string;
    resolutionDate: string;
    moreCount: number;
  };
}) {
  const [expanded, setExpanded] = useState(false);
  const isLong = text.length > 220;

  return (
    <div className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-surface)] p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span
          className={`inline-block rounded-full border px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.08em] ${badgeClass}`}
        >
          {badgeLabel}
        </span>
        {stance && (
          <span
            title={stanceTitle(stance)}
            className={`inline-block cursor-help rounded-full border px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.08em] ${stanceBadgeClass[stance.kind]}`}
          >
            {stanceLabel(stance)}
          </span>
        )}
        <span className="[font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
          {kind}
        </span>
      </div>
      <p
        className={`m-0 text-[0.88rem] leading-[1.6] text-[var(--theme-text-muted)] ${
          isLong && !expanded ? "line-clamp-3" : ""
        }`}
      >
        {renderInline(text)}
      </p>
      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 cursor-pointer border-0 bg-transparent p-0 [font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.1em] text-[var(--color-accent)] hover:underline"
        >
          {expanded ? "Less ↑" : "Full sourcing ↓"}
        </button>
      )}
      {registry && (
        <div className="mt-3 text-[0.78rem] leading-[1.6] text-[var(--theme-text-muted)]">
          <p className="m-0">{registry.note}</p>
          {registry.series && (
            <p className="mb-0 mt-1 break-words">
              Current docket series: <code>{registry.series}</code>
            </p>
          )}
          {registry.candidates && registry.candidates.length > 0 && (
            <p className="mb-0 mt-1 break-words">
              Candidate series: <code>{registry.candidates.join(", ")}</code>
            </p>
          )}
          {registry.chronicle && (
            <p className="mb-0 mt-2 break-words">
              <a
                href={registry.chronicle.href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--color-accent)] hover:underline"
              >
                Chronicle catalog ↗
              </a>
              <br />
              Current docket identity: <code>{registry.chronicle.concept}</code>
              <br />
              UUID: <code>{registry.chronicle.uuid}</code>
            </p>
          )}
          {registry.analysisSnapshot && (
            <details className="mt-2">
              <summary className="cursor-pointer text-[var(--theme-text-dim)]">
                Analysis-day registry status
              </summary>
              <p className="mb-0 mt-1">
                {registry.analysisSnapshot}. Historical assessment; the badge
                above is recomputed from the docket at site build time.
              </p>
            </details>
          )}
        </div>
      )}
      {forecast && (
        <a
          href={forecast.href ?? `/${forecast.slug}`}
          className="mt-2 inline-block [font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.1em] text-[#1F6B33] no-underline hover:underline"
        >
          Live forecast {forecast.pointLabel} →
        </a>
      )}
      {rationale && (
        <details className="mt-3 border-t border-[var(--theme-border)] pt-3">
          <summary className="cursor-pointer list-none [font-family:var(--font-mono)] text-[0.65rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)] hover:text-[var(--color-accent)] [&::-webkit-details-marker]:hidden">
            Why this metric ▸
          </summary>
          <p className="mb-0 mt-2 text-[0.85rem] leading-[1.6] text-[var(--theme-text-muted)]">
            {renderInline(rationale)}
          </p>
        </details>
      )}
    </div>
  );
}
