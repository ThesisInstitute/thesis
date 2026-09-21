import fs from "node:fs";
import path from "node:path";
import type { MetricStance } from "@/lib/stances";
import ledgerPin from "@/data/ledger-pin.json";

// bill.json artifacts live at the repo root (bills/<slug>.json), written
// by scripts/ingest_bill.py — the site reads them at build time. Vercel
// must have "include files outside root directory" enabled and the
// ignored-build-step watching bills/ for artifact-only pushes to deploy
// (issue #43).
const BILLS_DIR = path.join(process.cwd(), "..", "bills");
const DOCKET_FILE = path.join(process.cwd(), "..", "scripts", "docket_series.json");

// The catalog path is also used by scripts/pin_ledger.py. Link to the current
// catalog for discovery; the identity displayed on the card comes from the docket.
export const CHRONICLE_CATALOG_URL = `https://github.com/${ledgerPin.repo}/blob/${ledgerPin.branch}/ledger/series_catalog.json`;

export interface BillInfo {
  slug?: string;
  name: string;
  status: string;
  pages: number;
  analyzed: string;
  analysisDate: string;
  sourceUrl: string;
}

export interface BillEffect {
  mechanism: string;
  text: string;
}

export interface BillBarrier {
  actor: string;
  text: string;
}

export interface BillMetric {
  kind: string;
  text: string;
  series_hint?: string;
  /** Frozen analysis-day badge carried by ported artifacts. */
  registry?: string;
  /** Proposal metadata only; the current docket remains admission authority. */
  matched_series?: string;
  ledger_uuid?: string;
  mapping?: Record<string, unknown>;
  /**
   * Why this metric was selected — considered alternatives, resolution
   * properties, known weaknesses. Additive contract field; rendered as
   * a disclosure when present.
   */
  rationale?: string;
  /**
   * Stance v1 (issue #43 micro-spec): one extraction-time
   * serves/opposes/orthogonal judgment per imputed goal, keyed by goal
   * index. The client folds this over the countersign store.
   */
  stances?: MetricStance[];
  /**
   * Layer addendum (issue #43): does the agency act, do people engage,
   * does the world change. Intrinsic to the metric; accepted now,
   * rendered when the intended/unintended/operational grouping lands.
   */
  layer?: "execution" | "participation" | "outcome";
  category?: string;
}

export interface BillCompute {
  model: string;
  reform: Record<string, unknown>;
  result_summary: string;
  /**
   * Provenance for the audited PolicyEngine call path (issue #45) —
   * additive contract fields carried by compute rows produced through
   * scripts/tools/policyengine.py. `certification` records whether the
   * model version matches the dataset build's certified pairing; an
   * uncertified row is inadmissible for a published number.
   */
  engine?: string;
  pe_us_version?: string;
  pe_core_version?: string;
  dataset?: string;
  certification?: {
    certified_model_version?: string;
    running_model_version?: string;
    certified: boolean;
  };
  year?: number;
  region?: string;
  status?: string;
  budgetary_impact?: number;
  ten_year_budgetary_impact?: number;
  ten_year_window?: string;
  poverty_child_pct_change?: number;
  beneficiaries_share?: number;
  note?: string;
  source?: string;
}

export interface BillProvision {
  title: string;
  heading: string;
  quote: string;
  goals: string[];
  effects: BillEffect[];
  barriers: BillBarrier[];
  metrics: BillMetric[];
  conditionals: string[];
  context?: string;
  compute?: BillCompute[];
}

export interface BillArtifact {
  slug: string;
  bill: BillInfo;
  provisions: BillProvision[];
}

export function loadBills(billsDir: string = BILLS_DIR): BillArtifact[] {
  if (!fs.existsSync(billsDir)) return [];
  return fs
    .readdirSync(billsDir)
    .filter((name) => name.endsWith(".json") && !name.endsWith(".mapped.json"))
    .map((name) => {
      const raw = JSON.parse(
        fs.readFileSync(path.join(billsDir, name), "utf-8"),
      ) as Omit<BillArtifact, "slug">;
      return { slug: name.replace(/\.json$/, ""), ...raw };
    })
    .sort((a, b) =>
      (b.bill.analysisDate ?? "").localeCompare(a.bill.analysisDate ?? ""),
    );
}

export function getBill(slug: string): BillArtifact | undefined {
  return loadBills().find((bill) => bill.slug === slug);
}

export interface BillRawMeta {
  resolved_via?: string;
  source_url?: string;
  version_label?: string;
  axiomBillId?: string;
  axiomDashboardUrl?: string;
}

/** Provenance sidecar written by the fetcher — optional by design. */
export function loadBillMeta(slug: string): BillRawMeta | null {
  const file = path.join(BILLS_DIR, "raw", `${slug}.meta.json`);
  if (!fs.existsSync(file)) return null;
  try {
    return JSON.parse(fs.readFileSync(file, "utf-8")) as BillRawMeta;
  } catch {
    return null;
  }
}

export type RegistryStatus = "reachable" | "not-yet" | "ambiguous" | "unknown";

export const REGISTRY_LABEL: Record<RegistryStatus, string> = {
  reachable: "Admitted to docket",
  "not-yet": "Admission work needed",
  ambiguous: "Mapping review needed",
  unknown: "Series mapping needed",
};

export interface BillDocketSeries {
  series: string;
  ledger?: { uuid: string; concept: string };
}

export interface MetricRegistryMapping {
  status: RegistryStatus;
  live: true;
  note: string;
  series?: string;
  ledger?: { uuid: string; concept: string };
  candidates?: string[];
}

/** Read the reviewed docket at build time; a missing docket fails the build. */
export function loadBillDocket(): BillDocketSeries[] {
  const docket = JSON.parse(fs.readFileSync(DOCKET_FILE, "utf-8")) as {
    series: BillDocketSeries[];
  };
  if (
    !Array.isArray(docket.series) ||
    docket.series.some(
      (row) => typeof row.series !== "string" || !row.series.trim(),
    )
  ) {
    throw new Error("Bill metric mapping requires a valid docket series registry");
  }
  return docket.series;
}

/**
 * Admission is computed from the current docket, never from an analysis-day
 * badge, a proposal's matched_series/ledger_uuid, or the existence of a forecast.
 * Prefer an exact identity; a dot-descendant is usable only when unambiguous.
 */
export function metricRegistryStatus(
  metric: BillMetric,
  docket: readonly BillDocketSeries[] = loadBillDocket(),
): MetricRegistryMapping {
  const hint = metric.series_hint?.trim();
  if (!hint) {
    return {
      status: "unknown",
      live: true,
      note: "Mapping work: identify an official outcome series, then review its Chronicle coverage and docket admission.",
    };
  }

  const exact = docket.filter((row) => row.series === hint);
  const matchingRows =
    exact.length > 0
      ? exact
      : docket.filter((row) => row.series.startsWith(`${hint}.`));
  // Different periods can repeat one series. They are one mapping only when
  // their Chronicle identity agrees; conflicting UUIDs remain review work.
  const candidates = [
    ...new Map(
      matchingRows.map((row) => [
        JSON.stringify([row.series, row.ledger?.uuid, row.ledger?.concept]),
        row,
      ]),
    ).values(),
  ];
  if (candidates.length === 1) {
    const match = candidates[0];
    return {
      status: "reachable",
      live: true,
      note: "Series admitted to the current docket. A bill-specific conditional pair requires separate preregistration.",
      series: match.series,
      ...(match.ledger ? { ledger: match.ledger } : {}),
    };
  }
  if (candidates.length > 1) {
    const concepts = [...new Set(candidates.map((row) => row.series))].sort();
    return {
      status: "ambiguous",
      live: true,
      note: concepts.length === 1
        ? "Mapping work: this docket series has conflicting Chronicle identities. Resolve its identity before registration."
        : "Mapping work: this hint matches multiple docket series. Review the metric's scope and select its exact series before registration.",
      candidates: concepts,
    };
  }
  return {
    status: "not-yet",
    live: true,
    note: "Admission work: this hint has no current docket match. Verify the official series, ingest missing Chronicle history, and complete reviewed docket admission.",
  };
}
