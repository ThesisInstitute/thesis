"use client";

import { useEffect, useState } from "react";
import { MetricCard, type MetricRegistryView } from "@/components/MetricCard";
import { renderInline } from "@/lib/render-inline";
import {
  foldStances,
  type GoalState,
  type MetricStance,
} from "@/lib/stances";

export interface ProvisionMetricView {
  kind: string;
  text: string;
  badgeLabel: string;
  badgeClass: string;
  registry?: MetricRegistryView;
  rationale?: string;
  stances?: MetricStance[];
  forecast?: {
    slug: string;
    href?: string;
    pointLabel: string;
    ciLabel: string;
    resolutionDate: string;
    moreCount: number;
  };
}

export interface ProvisionAnalysisProps {
  billSlug: string;
  provisionIndex: number;
  goals: string[];
  effects: { mechanism: string; text: string }[];
  barriers: { actor: string; text: string }[];
  metrics: ProvisionMetricView[];
  conditionals: string[];
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="[font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] mb-3">
      {children}
    </h4>
  );
}

const goalStateChip: Record<GoalState, string> = {
  confirmed: "border-[#BFE3D2] bg-[#EAF7F0] text-[#1C6B4A]",
  struck: "border-[#E5C8C0] bg-[#F9EFEC] text-[#93412A]",
};

/**
 * Client half of Stance v1 (issue #43 micro-spec): owns the countersign
 * store for one provision — goal states persist to localStorage — and
 * refolds every metric's stance matrix on every countersign action.
 */
export function ProvisionAnalysis({
  billSlug,
  provisionIndex,
  goals,
  effects,
  barriers,
  metrics,
  conditionals,
}: ProvisionAnalysisProps) {
  const storageKey = `thesis.countersign.${billSlug}.${provisionIndex}`;
  const [goalStates, setGoalStates] = useState<Record<number, GoalState>>({});

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw) setGoalStates(JSON.parse(raw));
    } catch {
      // Unreadable store — start clean.
    }
  }, [storageKey]);

  const setGoal = (index: number, next: GoalState | undefined) => {
    setGoalStates((prev) => {
      const state = { ...prev };
      if (next) state[index] = next;
      else delete state[index];
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(state));
      } catch {
        // Persistence is best-effort (v1 is localStorage-only).
      }
      return state;
    });
  };

  const toggle = (index: number, target: GoalState) => {
    setGoal(index, goalStates[index] === target ? undefined : target);
  };

  return (
    <>
      {goals.length > 0 && (
        <div className="mb-6">
          <SectionLabel>Countersignable goals</SectionLabel>
          <div className="grid gap-3">
            {goals.map((goal, i) => {
              const state = goalStates[i];
              return (
                <div
                  key={i}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg)] p-4"
                >
                  <div
                    className={`min-w-[16rem] flex-1 text-[0.92rem] leading-[1.6] text-[var(--theme-text)] ${
                      state === "struck" ? "line-through opacity-60" : ""
                    }`}
                  >
                    {renderInline(goal)}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {state && (
                      <span
                        className={`inline-block rounded-full border px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.08em] ${goalStateChip[state]}`}
                      >
                        {state === "confirmed" ? "Countersigned" : "Struck"}
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() => toggle(i, "confirmed")}
                      className={`cursor-pointer rounded-full border px-2 py-[3px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.08em] transition-colors ${
                        state === "confirmed"
                          ? "border-[#1C6B4A] bg-[#EAF7F0] text-[#1C6B4A]"
                          : "border-[var(--theme-border)] bg-transparent text-[var(--theme-text-muted)] hover:border-[#1C6B4A] hover:text-[#1C6B4A]"
                      }`}
                    >
                      Countersign
                    </button>
                    <button
                      type="button"
                      onClick={() => toggle(i, "struck")}
                      className={`cursor-pointer rounded-full border px-2 py-[3px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.08em] transition-colors ${
                        state === "struck"
                          ? "border-[#93412A] bg-[#F9EFEC] text-[#93412A]"
                          : "border-[var(--theme-border)] bg-transparent text-[var(--theme-text-muted)] hover:border-[#93412A] hover:text-[#93412A]"
                      }`}
                    >
                      Strike
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {effects.length > 0 && (
        <div className="mb-6">
          <SectionLabel>Likely effects — shown regardless of the goals</SectionLabel>
          <div className="grid gap-3 md:grid-cols-2">
            {effects.map((effect, i) => (
              <div
                key={i}
                className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg)] p-4"
              >
                <p className="m-0 mb-1.5 text-[0.8rem] font-semibold leading-[1.4] text-[var(--theme-text)]">
                  {renderInline(effect.mechanism)}
                </p>
                <p className="m-0 text-[0.88rem] leading-[1.6] text-[var(--theme-text-muted)]">
                  {renderInline(effect.text)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {barriers.length > 0 && (
        <div className="mb-6">
          <SectionLabel>Implementation barriers</SectionLabel>
          <div className="grid gap-3 md:grid-cols-2">
            {barriers.map((barrier, i) => (
              <div
                key={i}
                className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg)] p-4"
              >
                <p className="m-0 mb-1.5 text-[0.8rem] font-semibold leading-[1.4] text-[var(--theme-text)]">
                  {renderInline(barrier.actor)}
                </p>
                <p className="m-0 text-[0.88rem] leading-[1.6] text-[var(--theme-text-muted)]">
                  {renderInline(barrier.text)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {metrics.length > 0 && (
        <div className="mb-6">
          <SectionLabel>Candidate outcome metrics</SectionLabel>
          <div className="grid gap-3 md:grid-cols-2">
            {metrics.map((metric, i) => (
              <MetricCard
                key={i}
                kind={metric.kind}
                text={metric.text}
                badgeLabel={metric.badgeLabel}
                badgeClass={metric.badgeClass}
                registry={metric.registry}
                rationale={metric.rationale}
                stance={foldStances(metric.stances, goalStates)}
                forecast={metric.forecast}
              />
            ))}
          </div>
        </div>
      )}

      {conditionals.length > 0 && (
        <div>
          <SectionLabel>Conditional forecast sketches</SectionLabel>
          <div className="grid gap-2">
            {conditionals.map((conditional, i) => (
              <pre
                key={i}
                className="m-0 overflow-x-auto whitespace-pre-wrap rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg)] p-3 [font-family:var(--font-mono)] text-[0.78rem] leading-[1.5] text-[var(--theme-text)]"
              >
                {conditional.replaceAll("`", "")}
              </pre>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
