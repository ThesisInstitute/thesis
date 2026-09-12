import type { Metadata } from "next";
import { Header } from "@/components/Header";
import { CoreExperimentView } from "./CoreExperimentView";

export const metadata: Metadata = {
  title: "Core experiments — Thesis Institute",
  description:
    "Read-only view of the Thesis core experiment database: preregistered cohorts, runs, and forecaster evaluations with their declared cutoff and effective evidence-freeze boundary.",
};

/**
 * Server wrapper only. This page performs no data access at build or request
 * time: the tables below are filled by the client component through the
 * same-origin `/api/core` proxy, so the site builds with no core API
 * configured and never contacts a database or an upstream source while
 * rendering.
 */
export default function CorePage() {
  return (
    <div
      className="min-h-screen"
      style={{ backgroundColor: "var(--theme-bg)" }}
    >
      <Header activePage="core" />
      <main className="mx-auto w-full max-w-[1100px] px-6 pb-24 pt-12">
        <h1
          className="[font-family:var(--font-display)] text-[1.9rem] font-semibold"
          style={{ color: "var(--theme-text)" }}
        >
          Core experiments
        </h1>
        <p
          className="mt-3 max-w-[720px] text-[0.92rem] leading-[1.65]"
          style={{ color: "var(--theme-text-muted)" }}
        >
          Compare forecasts, their evidence cutoffs and their recorded results.
          Replay experiments use historical outcomes and remain separate from
          prospective evaluations.
        </p>
        <CoreExperimentView />
      </main>
    </div>
  );
}
