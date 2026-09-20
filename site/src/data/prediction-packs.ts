import { getPublishedForecasts } from "@/lib/forecast-publication";
import {
  getForecastRunEntries,
  type ForecastCell,
  type ForecastRunEntry,
  type PredictionPackKind,
  type PredictionPackReference,
  type PredictionPackSetMode,
  type Unit,
} from "./forecast-cells";

export interface PredictionPackDetail {
  packId: string;
  purpose: string;
  mechanism: string[];
  qualityChecks: string[];
  inputs: string[];
  limitations: string[];
}

export interface PredictionPackUsage {
  forecastSlug: string;
  forecastTitle: string;
  forecastQuestion: string;
  forecastType: ForecastCell["type"];
  unit: Unit;
  runVariantId: string;
  runLabel: string;
  runDescription?: string;
  agent: string;
  model?: string;
  runAt?: string;
  packSetId: string;
  packSetLabel: string;
  packSetMode: PredictionPackSetMode;
  pointEstimate: number;
  interval80: {
    lower: number;
    upper: number;
  };
  deltaVsNoPack?: number;
}

export interface PredictionPackVersionEntry {
  key: string;
  version: string;
  pack: PredictionPackReference;
  usage: PredictionPackUsage[];
}

export interface PredictionPackCatalogEntry {
  packId: string;
  label: string;
  kind: PredictionPackKind;
  summary: string;
  latestVersion: string;
  detail?: PredictionPackDetail;
  versions: PredictionPackVersionEntry[];
  usage: PredictionPackUsage[];
  agents: string[];
  packSetLabels: string[];
  targetCount: number;
  runCount: number;
}

const REGISTERED_PACKS: PredictionPackReference[] = [
  {
    packId: "panel-persistence-shrinkage",
    version: "0.1.0",
    label: "Panel persistence shrinkage",
    kind: "method",
    summary:
      "For repeated jurisdiction, occupation, or agency panels, scores the last-print baseline and shrinks agent updates toward it unless current evidence clears a stated bar.",
  },
];

const PACK_DETAILS: Record<string, Omit<PredictionPackDetail, "packId">> = {
  "base-rate-first": {
    purpose:
      "Keep the agent anchored to an explicit outside-view reference class before it applies target-specific adjustments.",
    mechanism: [
      "Identify a resolved historical base rate for the target series.",
      "State the base rate before any inside-view adjustment.",
      "Show how each adjustment moves the forecast away from that anchor.",
    ],
    qualityChecks: [
      "A reference class is named before the final forecast.",
      "The public trace includes a base-rate calculation or lookup.",
      "Inside-view adjustments are signed and small enough to audit.",
    ],
    inputs: [
      "Resolved historical observations",
      "Forecast horizon and unit",
      "Recent trend window selected by the run",
    ],
    limitations: [
      "Does not choose the best reference class by itself.",
      "Can underreact when the current regime has genuinely changed.",
    ],
  },
  "cpi-component-decomposition": {
    purpose:
      "Force headline CPI-U forecasts through interpretable component channels instead of a single aggregate extrapolation.",
    mechanism: [
      "Split headline CPI-U into shelter, services ex-shelter, core goods, food, and energy channels.",
      "Apply component-specific priors and current-source adjustments.",
      "Recombine components into the annual-average headline forecast.",
    ],
    qualityChecks: [
      "Major CPI components are named in the reasoning trace.",
      "The run explains the component that drives the central estimate.",
      "The final interval reflects component-level upside and downside risk.",
    ],
    inputs: [
      "BLS CPI-U history",
      "Supplemental CPI component tables",
      "External inflation baselines when available",
    ],
    limitations: [
      "Prototype weights are coarse and should be replaced with official CPI relative-importance tables.",
      "Component paths remain judgmental until a formal time-series model is attached.",
    ],
  },
  "cash-income-bridge": {
    purpose:
      "Translate labor-market and transfer-income signals into the official poverty measure's pretax cash-income definition.",
    mechanism: [
      "Start from a resolved official-poverty base rate.",
      "Separate earnings, Social Security, cash assistance, and threshold-indexation effects.",
      "Exclude tax credits and noncash benefits that belong in SPM rather than the official measure.",
    ],
    qualityChecks: [
      "The run states that official poverty is a pretax cash-income target.",
      "The public trace distinguishes official poverty from SPM.",
      "The forecast explains which cash-income channel moves the rate.",
    ],
    inputs: [
      "Census official poverty history",
      "Labor-market and wage indicators",
      "PolicyEngine cash-income simulation output",
    ],
    limitations: [
      "Does not model within-year CPS ASEC response bias directly.",
      "Can miss distributional changes if aggregate earnings look stable.",
    ],
  },
  "asec-income-nowcast": {
    purpose:
      "Combine wage, employment, and household-composition signals into a Census ASEC median-income nowcast.",
    mechanism: [
      "Anchor on the latest real median household income release.",
      "Update the center with real wage and employment-to-population signals.",
      "Adjust for household-composition drift before adding release uncertainty.",
    ],
    qualityChecks: [
      "The run reports the latest Census income base value.",
      "The nowcast separates wage growth from household-composition effects.",
      "The final interval includes both economic uncertainty and ASEC sampling uncertainty.",
    ],
    inputs: [
      "Census ASEC income history",
      "Real wage growth indicators",
      "Employment and household-composition signals",
    ],
    limitations: [
      "Prototype composition adjustments are coarse.",
      "Does not yet ingest microdata-level replicate weights directly.",
    ],
  },
  "asec-release-calibration": {
    purpose:
      "Add Census ASEC sampling, vintage, and release-table uncertainty to income and poverty forecasts.",
    mechanism: [
      "Identify whether the target resolves in the annual ASEC income or poverty release.",
      "Add release-specific uncertainty around the modeled central estimate.",
      "Keep the interval aligned with the headline table and first-publication resolution rule.",
    ],
    qualityChecks: [
      "The run names the Census ASEC release as the resolution surface.",
      "The trace separates model uncertainty from release-table uncertainty.",
      "The interval accounts for sampling noise even when the central model is stable.",
    ],
    inputs: [
      "Census ASEC release schedule",
      "Historical headline table volatility",
      "Modeled central estimate from the target-specific pack set",
    ],
    limitations: [
      "Does not yet use official replicate-weight variance formulas.",
      "Release-vintage uncertainty is approximated from historical headline behavior.",
    ],
  },
  "labor-market-momentum": {
    purpose:
      "Combine labor-market signals into a coherent nowcast before the next employment release.",
    mechanism: [
      "Start from recent payroll, unemployment, and participation prints.",
      "Cross-check the signal against claims and job-openings momentum.",
      "Flag contradictions between establishment, household, and claims data.",
    ],
    qualityChecks: [
      "The run names at least two labor-market surfaces beyond the target series.",
      "The trace explains whether the cross-check raises or lowers the center.",
      "The interval reflects first-print labor-market volatility.",
    ],
    inputs: [
      "BLS CES and CPS history",
      "Initial claims and JOLTS signals",
      "Recent first-print resolution facts",
    ],
    limitations: [
      "Does not estimate sector-level payroll detail yet.",
      "Can understate turning points when all labor indicators lag together.",
    ],
  },
  "consumer-spending-nowcast": {
    purpose:
      "Separate true consumer-demand momentum from volatile retail-release channels before advance sales and PCE spending releases.",
    mechanism: [
      "Start from recent headline and control-group retail sales momentum.",
      "Split autos, gasoline, food services, and control-group channels before recombining.",
      "Cross-check the channel signal against card-spending and price-level nowcasts when available.",
    ],
    qualityChecks: [
      "The run distinguishes headline retail sales from control-group demand.",
      "Auto and gasoline channels are treated separately from broad consumer demand.",
      "The interval reflects advance-release volatility and later revision risk.",
    ],
    inputs: [
      "Census MARTS advance retail sales history",
      "Auto-sales and gasoline-price signals",
      "Card-spending and control-group nowcasts",
    ],
    limitations: [
      "Prototype card-spending inputs are qualitative rather than a direct feed.",
      "Does not yet model seasonal retail-calendar effects at the store-category level.",
    ],
  },
  "housing-activity-nowcast": {
    purpose:
      "Cross-check housing starts and construction activity against permits, financing conditions, and builder sentiment.",
    mechanism: [
      "Anchor on recent starts, permits, and completions levels.",
      "Compare single-family and multifamily signals against mortgage-rate and builder-sentiment context.",
      "Add preliminary-release volatility for starts and permits that are frequently revised.",
    ],
    qualityChecks: [
      "The run identifies whether permits support or contradict the starts signal.",
      "Single-family and multifamily timing risk are considered separately.",
      "The interval is wide enough for preliminary New Residential Construction noise.",
    ],
    inputs: [
      "Census/HUD starts and permits history",
      "Mortgage-rate and builder-sentiment context",
      "Recent preliminary-release revision behavior",
    ],
    limitations: [
      "Does not yet ingest metro- or state-level permit microdata.",
      "Multifamily project timing remains a judgmental adjustment.",
    ],
  },
  "panel-persistence-shrinkage": {
    purpose:
      "Prevent agents from overreacting on stable panel targets where last year's official value is usually the strongest single predictor.",
    mechanism: [
      "Record a last-print persistence benchmark and score it beside the agent run.",
      "Estimate a panel-level drift or shrinkage term from comparable entities before applying inside-view adjustments.",
      "Require explicit current evidence before moving materially away from the persistence-plus-shrinkage baseline.",
    ],
    qualityChecks: [
      "The trace reports the persistence benchmark and the agent's delta from it.",
      "Large departures name the evidence source and the expected sign of the departure.",
      "Intervals widen for entities with volatile prior prints, small samples, or known release noise.",
    ],
    inputs: [
      "Prior official print for the same entity",
      "Comparable panel history across entities or occupations",
      "Current entity-specific evidence strong enough to justify a departure",
    ],
    limitations: [
      "Can underreact to true breaks, new policy regimes, or one-off administrative shocks.",
      "Should not be used when the target is a new series with no entity-level prior.",
      "Needs walk-forward scoring before promotion beyond panel-style targets.",
    ],
  },
  "bls-employment-projections-baseline": {
    purpose:
      "Use the official BLS 2024-2034 occupational employment projections as an outside-view prior for OEWS occupation forecasts.",
    mechanism: [
      "Map the OEWS SOC major group target to the matching BLS Employment Projections occupation row.",
      "Translate the decade projection direction into a modest near-term adjustment around the no-pack OEWS forecast.",
      "Keep the May 2026 OEWS first-published national occupation table as the resolution surface.",
    ],
    qualityChecks: [
      "The trace names the Employment Projections release and table used by the run.",
      "The signed pack adjustment is shown separately from the no-pack control forecast.",
      "The projection source is not used as the resolver for the OEWS target.",
    ],
    inputs: [
      "BLS Employment Projections 2024-2034 Summary",
      "BLS Employment Projections Table 1.2 occupational projections and worker characteristics",
      "BLS OEWS national occupational employment target",
    ],
    limitations: [
      "The projection is a 10-year BLS baseline, not an annual path to the May 2026 OEWS release.",
      "Major-group mappings can hide within-group variation in automation exposure.",
      "Projection vintages can lag shocks that affect the near-term OEWS first print.",
    ],
  },
  "release-vintage-calibration": {
    purpose:
      "Calibrate forecast uncertainty to first-publication behavior, not only later revised time series.",
    mechanism: [
      "Identify the first-print release surface for the target.",
      "Compare revised series volatility with first-print surprise behavior.",
      "Apply rounding and publication-grid checks where the source reports rounded values.",
    ],
    qualityChecks: [
      "The run states that the first print governs resolution.",
      "The trace distinguishes release rounding from underlying economic uncertainty.",
      "The final interval is not narrower than historical first-print noise supports.",
    ],
    inputs: [
      "Official release schedule",
      "Resolved first-print observations",
      "Historical revision or rounding behavior",
    ],
    limitations: [
      "Prototype calibration uses coarse first-print history.",
      "Does not yet model source-specific embargo or publication delays.",
    ],
  },
  "energy-price-nowcast": {
    purpose:
      "Capture short-horizon energy movements that can dominate headline inflation releases.",
    mechanism: [
      "Track gasoline, crude oil, utilities, and PPI energy signals.",
      "Translate energy movement into headline CPI pressure separately from core components.",
      "Keep central energy adjustments separate from tail-risk widening.",
    ],
    qualityChecks: [
      "The run identifies the energy channel separately from core inflation.",
      "The trace explains whether energy is decelerating, accelerating, or reversing.",
      "The interval reflects upside and downside energy tails explicitly.",
    ],
    inputs: [
      "Gasoline and crude price signals",
      "BLS CPI energy component history",
      "PPI energy and pipeline-price signals",
    ],
    limitations: [
      "Does not include daily station-level gasoline microdata.",
      "Energy pass-through to non-energy components remains judgmental.",
    ],
  },
  "pce-cpi-bridge": {
    purpose:
      "Map CPI component information into BEA PCE concepts before the PCE release.",
    mechanism: [
      "Separate CPI source-data signals by component.",
      "Adjust for PCE scope, formula, and component-weight differences.",
      "Calibrate the bridge to the BEA release surface rather than the CPI release.",
    ],
    qualityChecks: [
      "The run states why CPI information is relevant but not identical to PCE.",
      "The trace names at least one scope or weight adjustment.",
      "The final forecast remains in the PCE target unit and release rule.",
    ],
    inputs: [
      "Core CPI source-data signals",
      "BEA core PCE history",
      "Known CPI-PCE scope and weight differences",
    ],
    limitations: [
      "Prototype bridge is component-level, not item-level.",
      "Does not ingest unreleased BEA source-data revisions.",
    ],
  },
  "tariff-pass-through": {
    purpose:
      "Represent tariff risk as an asymmetric goods-price tail rather than burying it in a symmetric interval.",
    mechanism: [
      "Detect whether tariff risk is active for the target horizon.",
      "Apply a small central-case goods-price adjustment.",
      "Widen or skew the upper tail when pass-through uncertainty matters.",
    ],
    qualityChecks: [
      "The run names tariff pass-through as upside risk when active.",
      "The public trace distinguishes central adjustment from tail risk.",
      "The final distribution can move high without forcing the median equally high.",
    ],
    inputs: [
      "Tariff policy context",
      "Core-goods inflation history",
      "Agent-selected pass-through calibration",
    ],
    limitations: [
      "The current pack is a calibration scaffold, not a structural trade model.",
      "It does not estimate sector-specific tariff exposure yet.",
    ],
  },
};

export function buildPredictionPackCatalog(
  forecasts: ForecastCell[] = getPublishedForecasts(),
): PredictionPackCatalogEntry[] {
  const entries = new Map<string, MutablePackCatalogEntry>();

  for (const pack of REGISTERED_PACKS) {
    const entry = createMutablePackEntry(pack);
    entry.versions.set(
      buildPredictionPackVersionKey(pack),
      createMutableVersionEntry(pack),
    );
    entries.set(pack.packId, entry);
  }

  for (const forecast of forecasts) {
    const runs = getForecastRunEntries(forecast);
    const noPackBaseline = runs.find((run) => run.packSet?.mode === "none");

    for (const run of runs) {
      for (const pack of run.packSet?.packs ?? []) {
        const entry = entries.get(pack.packId) ?? createMutablePackEntry(pack);
        const versionKey = buildPredictionPackVersionKey(pack);
        const version =
          entry.versions.get(versionKey) ?? createMutableVersionEntry(pack);
        const usage = buildPredictionPackUsage(forecast, run, noPackBaseline);

        version.usage.push(usage);
        entry.usage.push(usage);
        entry.agents.add(usage.agent);
        entry.packSetLabels.add(usage.packSetLabel);
        entry.targetSlugs.add(forecast.slug);
        entry.versions.set(versionKey, version);
        entries.set(pack.packId, entry);
      }
    }
  }

  return [...entries.values()]
    .map(finalizePackEntry)
    .sort((left, right) => left.label.localeCompare(right.label));
}

export function getPredictionPackCatalogEntry(
  packId: string,
  forecasts: ForecastCell[] = getPublishedForecasts(),
) {
  return buildPredictionPackCatalog(forecasts).find(
    (entry) => entry.packId === packId,
  );
}

export function buildPredictionPackVersionKey(pack: PredictionPackReference) {
  return `${pack.packId}@${pack.version}`;
}

interface MutablePackCatalogEntry {
  packId: string;
  label: string;
  kind: PredictionPackKind;
  summary: string;
  detail?: PredictionPackDetail;
  versions: Map<string, PredictionPackVersionEntry>;
  usage: PredictionPackUsage[];
  agents: Set<string>;
  packSetLabels: Set<string>;
  targetSlugs: Set<string>;
}

function createMutablePackEntry(
  pack: PredictionPackReference,
): MutablePackCatalogEntry {
  const detail = PACK_DETAILS[pack.packId]
    ? { packId: pack.packId, ...PACK_DETAILS[pack.packId] }
    : undefined;

  return {
    packId: pack.packId,
    label: pack.label,
    kind: pack.kind,
    summary: pack.summary,
    detail,
    versions: new Map<string, PredictionPackVersionEntry>(),
    usage: [],
    agents: new Set<string>(),
    packSetLabels: new Set<string>(),
    targetSlugs: new Set<string>(),
  };
}

function createMutableVersionEntry(
  pack: PredictionPackReference,
): PredictionPackVersionEntry {
  return {
    key: buildPredictionPackVersionKey(pack),
    version: pack.version,
    pack,
    usage: [],
  };
}

function buildPredictionPackUsage(
  forecast: ForecastCell,
  run: ForecastRunEntry,
  noPackBaseline?: ForecastRunEntry,
): PredictionPackUsage {
  const packSet = run.packSet;

  return {
    forecastSlug: forecast.slug,
    forecastTitle: forecast.title,
    forecastQuestion: forecast.question,
    forecastType: forecast.type,
    unit: forecast.unit,
    runVariantId: run.variantId,
    runLabel: run.label,
    runDescription: run.description,
    agent: run.predictionRun?.agent ?? "prototype seed",
    model: run.predictionRun?.model,
    runAt: run.predictionRun?.runAt,
    packSetId: packSet?.packSetId ?? "pack_set.unreported",
    packSetLabel: packSet?.label ?? "Unreported pack set",
    packSetMode: packSet?.mode ?? "with_packs",
    pointEstimate: run.pointEstimate,
    interval80: {
      lower: run.ciLow,
      upper: run.ciHigh,
    },
    deltaVsNoPack: noPackBaseline
      ? run.pointEstimate - noPackBaseline.pointEstimate
      : undefined,
  };
}

function finalizePackEntry(
  entry: MutablePackCatalogEntry,
): PredictionPackCatalogEntry {
  const versions = [...entry.versions.values()].sort((left, right) =>
    compareVersions(left.version, right.version),
  );
  const latestVersion = versions.at(-1)?.version ?? "unversioned";

  return {
    packId: entry.packId,
    label: entry.label,
    kind: entry.kind,
    summary: entry.summary,
    latestVersion,
    detail: entry.detail,
    versions,
    usage: entry.usage.sort(comparePackUsage),
    agents: [...entry.agents].sort(),
    packSetLabels: [...entry.packSetLabels].sort(),
    targetCount: entry.targetSlugs.size,
    runCount: entry.usage.length,
  };
}

function comparePackUsage(
  left: PredictionPackUsage,
  right: PredictionPackUsage,
) {
  const leftTime = left.runAt ? Date.parse(left.runAt) : 0;
  const rightTime = right.runAt ? Date.parse(right.runAt) : 0;
  if (leftTime !== rightTime) return leftTime - rightTime;
  return left.runLabel.localeCompare(right.runLabel);
}

function compareVersions(left: string, right: string) {
  return left.localeCompare(right, undefined, {
    numeric: true,
    sensitivity: "base",
  });
}
