import type { CountryCode, ResolutionPolicy, Unit } from "./forecast-cells";
import { GENERATED_FORECAST_TARGETS } from "./ledger-targets.generated";

export const TARGET_PREREGISTRATION_ORPHAN_GRACE_DAYS = 7;

// Mirrors scripts/register_targets.py SOURCE_ADAPTERS exactly: any adapter
// python can register will appear in ledger-targets.generated.ts, so a
// missing member here breaks the next site build AFTER a registration lands
// (2026-08-03: "irs-soi-pub1304" registered by the S.3596 wave with no
// union member — main went build-red until this line existed).
export type TargetSourceAdapter =
  | "abs-data-api"
  | "abs-release-page"
  | "alfred-fred"
  | "bea-ita-itable"
  | "bea-release"
  | "bls-api"
  | "bls-qcew"
  | "census-spm-annual-report"
  | "eia-dnav-xls"
  | "eurostat-api"
  | "fsa-crp-monthly-summary"
  | "generic-url"
  | "irs-soi-pub1304"
  | "ons-timeseries"
  | "sba-loan-program-performance-pdf"
  | "statcan-wds"
  | "usaspending-api";

export interface TargetSourceBinding {
  adapter: TargetSourceAdapter;
  sourceUrl: string;
  sourceSeriesId: string;
  field: string;
  table: string;
  transform: unknown;
  releasePolicy:
    | "first_print"
    | "advance_vintage"
    | "registered_query_snapshot";
  // Every host the series' first prints have actually appeared on,
  // fixed at registration time; the resolution URL's host must be a
  // member. Absent on single-host legacy bindings, which stay pinned
  // to the sourceUrl host.
  allowedHosts?: string[];
  expectedReleaseWindow: {
    start: string;
    end: string;
  };
}

export interface TargetRegisteredLedgerEntry {
  kind: "target_registered";
  dataPointId: string;
  observationId: string;
  country: CountryCode;
  periodLabel: string;
  unit: Unit;
  resolutionDate: string;
  /**
   * Basis for resolutionDate; absent means release-calendar. A bounded date
   * is a Thesis lab commitment, not timing established by its announcement.
   */
  resolutionDateBasis?: "release-calendar" | "resolve-by-bound";
  resolutionSource: string;
  resolutionSourceUrl?: string;
  resolutionRule: string;
  resolutionPolicy: ResolutionPolicy;
  sourceKind: "official_release";
  source: string;
  sourceUrl?: string;
  note: string;
  /** Absent on legacy registrations, which are already published. */
  registrationState?: "preregistered" | "published";
  registeredAt?: string;
  targetContentHash?: string;
  series?: string;
  period?: string;
  catalogSlug?: string;
  valueScale?: number;
  sourceBinding?: TargetSourceBinding;
  // The ledger state pinned at registration (v3 registrations). A resolving
  // observation must have been accepted at or beyond this sequence count —
  // membership in the pinned state means the print predated the target.
  ledgerPinSha?: string;
  ledgerPinLineCount?: number;
}

const OEWS_SOURCE =
  "U.S. Bureau of Labor Statistics, Occupational Employment and Wage Statistics";
const OEWS_TABLES_URL = "https://www.bls.gov/oes/tables.htm";
const BLS_EMPLOYMENT_PROJECTIONS_SOURCE =
  "U.S. Bureau of Labor Statistics, Employment Projections";
const BLS_EMPLOYMENT_PROJECTIONS_TABLE_URL =
  "https://www.bls.gov/emp/tables/occupational-projections-and-characteristics.htm";
const BLS_EMPLOYMENT_SITUATION_SOURCE =
  "U.S. Bureau of Labor Statistics, Employment Situation";
const BLS_CPS_A19_URL = "https://www.bls.gov/web/empsit/cpseea19.htm";
const BLS_CES_SOURCE =
  "U.S. Bureau of Labor Statistics, Current Employment Statistics";
const BLS_CES_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data";
const TREASURY_MTS_SOURCE =
  "U.S. Treasury Bureau of the Fiscal Service, Monthly Treasury Statement";
const TREASURY_MTS_TABLE_5_URL =
  "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/mts/mts_table_5";
const USASPENDING_SOURCE = "USAspending.gov";
const USASPENDING_DOD_AWARD_CATEGORY_URL =
  "https://api.usaspending.gov/api/v2/agency/097/obligations_by_award_category/";
const USDA_FNS_SNAP_QC_SOURCE =
  "USDA FNS, SNAP Quality Control Payment Error Rates, FY 2026";
const USDA_FNS_SNAP_QC_URL = "https://www.fns.usda.gov/snap/qc/per";

const SNAP_QC_JURISDICTIONS = [
  ["us", "national"],
  ["ak", "Alaska"],
  ["al", "Alabama"],
  ["ar", "Arkansas"],
  ["az", "Arizona"],
  ["ca", "California"],
  ["co", "Colorado"],
  ["ct", "Connecticut"],
  ["dc", "District of Columbia"],
  ["de", "Delaware"],
  ["fl", "Florida"],
  ["ga", "Georgia"],
  ["gu", "Guam"],
  ["hi", "Hawaii"],
  ["ia", "Iowa"],
  ["id", "Idaho"],
  ["il", "Illinois"],
  ["in", "Indiana"],
  ["ks", "Kansas"],
  ["ky", "Kentucky"],
  ["la", "Louisiana"],
  ["ma", "Massachusetts"],
  ["md", "Maryland"],
  ["me", "Maine"],
  ["mi", "Michigan"],
  ["mn", "Minnesota"],
  ["mo", "Missouri"],
  ["ms", "Mississippi"],
  ["mt", "Montana"],
  ["nc", "North Carolina"],
  ["nd", "North Dakota"],
  ["ne", "Nebraska"],
  ["nh", "New Hampshire"],
  ["nj", "New Jersey"],
  ["nm", "New Mexico"],
  ["nv", "Nevada"],
  ["ny", "New York"],
  ["oh", "Ohio"],
  ["ok", "Oklahoma"],
  ["or", "Oregon"],
  ["pa", "Pennsylvania"],
  ["ri", "Rhode Island"],
  ["sc", "South Carolina"],
  ["sd", "South Dakota"],
  ["tn", "Tennessee"],
  ["tx", "Texas"],
  ["ut", "Utah"],
  ["va", "Virginia"],
  ["vi", "Virgin Islands"],
  ["vt", "Vermont"],
  ["wa", "Washington"],
  ["wi", "Wisconsin"],
  ["wv", "West Virginia"],
  ["wy", "Wyoming"],
] as const;

function oewsMajorOccupationTarget({
  socCode,
  label,
  note,
}: {
  socCode: string;
  label: string;
  note: string;
}): TargetRegisteredLedgerEntry {
  const dataPointId = `bls.oews.national_occupation_employment.soc_${socCode.replace("-", "_")}.may_2026.first_print`;
  return {
    kind: "target_registered",
    dataPointId,
    observationId: `obs.${dataPointId}`,
    country: "US",
    periodLabel: "May 2026",
    unit: "thousands",
    resolutionDate: "2027-05-14",
    resolutionSource: OEWS_SOURCE,
    resolutionSourceUrl: OEWS_TABLES_URL,
    resolutionRule:
      `Resolves to the first-published national OEWS employment estimate ` +
      `for SOC ${socCode} ${label} in the BLS May 2026 National Occupational ` +
      `Employment and Wage Estimates table, divided by 1,000 and rounded to ` +
      `the nearest thousand workers. Later revisions or table corrections do ` +
      `not change the resolved value unless BLS replaces the first table on ` +
      `the same publication date.`,
    resolutionPolicy: "first_print",
    sourceKind: "official_release",
    source: OEWS_SOURCE,
    sourceUrl: OEWS_TABLES_URL,
    note,
  };
}

type OewsOccupationWageStatistic =
  | "p10"
  | "p25"
  | "median"
  | "mean"
  | "p75"
  | "p90";

const OEWS_OCCUPATION_WAGE_STATISTICS = {
  p10: {
    label: "10th percentile",
    dataPointStatistic: "10th_percentile",
    field: "A_PCT10",
  },
  p25: {
    label: "25th percentile",
    dataPointStatistic: "25th_percentile",
    field: "A_PCT25",
  },
  median: {
    label: "median",
    dataPointStatistic: "median",
    field: "A_MEDIAN",
  },
  mean: {
    label: "mean",
    dataPointStatistic: "mean",
    field: "A_MEAN",
  },
  p75: {
    label: "75th percentile",
    dataPointStatistic: "75th_percentile",
    field: "A_PCT75",
  },
  p90: {
    label: "90th percentile",
    dataPointStatistic: "90th_percentile",
    field: "A_PCT90",
  },
} satisfies Record<
  OewsOccupationWageStatistic,
  { label: string; dataPointStatistic: string; field: string }
>;

const OEWS_OCCUPATION_WAGE_STATISTIC_ORDER = [
  "p10",
  "p25",
  "median",
  "mean",
  "p75",
  "p90",
] satisfies OewsOccupationWageStatistic[];

function oewsMajorOccupationWageTarget({
  socCode,
  label,
  note,
  statistic = "median",
}: {
  socCode: string;
  label: string;
  note: string;
  statistic?: OewsOccupationWageStatistic;
}): TargetRegisteredLedgerEntry {
  const wageStatistic = OEWS_OCCUPATION_WAGE_STATISTICS[statistic];
  const dataPointId = `bls.oews.national_occupation_${wageStatistic.dataPointStatistic}_annual_wage.soc_${socCode.replace("-", "_")}.may_2026.first_print`;
  return {
    kind: "target_registered",
    dataPointId,
    observationId: `obs.${dataPointId}`,
    country: "US",
    periodLabel: "May 2026",
    unit: "usd",
    resolutionDate: "2027-05-14",
    resolutionSource: OEWS_SOURCE,
    resolutionSourceUrl: OEWS_TABLES_URL,
    resolutionRule:
      `Resolves to the first-published national OEWS annual ${wageStatistic.label} wage ` +
      `estimate for SOC ${socCode} ${label} in the BLS May 2026 National ` +
      `Occupational Employment and Wage Estimates table, in nominal dollars. ` +
      `This uses the ${wageStatistic.field}/annual ${wageStatistic.label} wage field for the national, ` +
      `cross-industry row. Later revisions or table corrections do not change ` +
      `the resolved value unless BLS replaces the first table on the same ` +
      `publication date.`,
    resolutionPolicy: "first_print",
    sourceKind: "official_release",
    source: OEWS_SOURCE,
    sourceUrl: OEWS_TABLES_URL,
    note,
  };
}

function oewsWageTargetNote(
  note: string,
  statistic: OewsOccupationWageStatistic,
): string {
  const statisticLabel = OEWS_OCCUPATION_WAGE_STATISTICS[statistic].label;
  const prefix =
    statistic === "median"
      ? "Median annual wage target"
      : `${statisticLabel[0].toUpperCase()}${statisticLabel.slice(1)} annual wage target`;
  return note.replace("Median annual wage target", prefix);
}

export const OEWS_OCCUPATION_EMPLOYMENT_TARGETS = [
  oewsMajorOccupationTarget({
    socCode: "13-0000",
    label: "Business and Financial Operations Occupations",
    note: "White-collar analytical and compliance work; useful for tracking AI-assisted office-task substitution and complementarity.",
  }),
  oewsMajorOccupationTarget({
    socCode: "15-0000",
    label: "Computer and Mathematical Occupations",
    note: "Core software, data, and quantitative occupations; a direct exposure group for generative-AI coding and analysis tools.",
  }),
  oewsMajorOccupationTarget({
    socCode: "31-0000",
    label: "Healthcare Support Occupations",
    note: "Hands-on care and support work; useful as a lower-automation benchmark with strong demographic labor-demand pressure.",
  }),
  oewsMajorOccupationTarget({
    socCode: "43-0000",
    label: "Office and Administrative Support Occupations",
    note: "Routine clerical, back-office, scheduling, and records tasks; one of the cleanest occupation groups for task-automation exposure.",
  }),
  oewsMajorOccupationTarget({
    socCode: "51-0000",
    label: "Production Occupations",
    note: "Factory and production work; connects software automation, robotics, and trade-sensitive manufacturing demand.",
  }),
  oewsMajorOccupationTarget({
    socCode: "53-0000",
    label: "Transportation and Material Moving Occupations",
    note: "Logistics, warehousing, driving, and material movement; relevant for warehouse automation, routing, and autonomy exposure.",
  }),
] satisfies TargetRegisteredLedgerEntry[];

const OEWS_OCCUPATION_WAGE_TARGET_DEFINITIONS = [
  {
    socCode: "11-0000",
    label: "Management Occupations",
    note: "Median annual wage target for managers and executives, useful for separating broad nominal wage pressure from high-skill composition effects.",
  },
  {
    socCode: "13-0000",
    label: "Business and Financial Operations Occupations",
    note: "Median annual wage target for white-collar analytical and compliance work exposed to both AI productivity and skill-mix shifts.",
  },
  {
    socCode: "15-0000",
    label: "Computer and Mathematical Occupations",
    note: "Median annual wage target for software, data, security, and quantitative roles where AI can raise productivity while changing labor demand.",
  },
  {
    socCode: "17-0000",
    label: "Architecture and Engineering Occupations",
    note: "Median annual wage target for technical design and engineering work exposed to infrastructure demand and AI-assisted design tools.",
  },
  {
    socCode: "19-0000",
    label: "Life, Physical, and Social Science Occupations",
    note: "Median annual wage target for research and scientific work, where funding cycles and AI-assisted research may shift labor demand.",
  },
  {
    socCode: "21-0000",
    label: "Community and Social Service Occupations",
    note: "Median annual wage target for human-service occupations where staffing pressure and public funding are central.",
  },
  {
    socCode: "23-0000",
    label: "Legal Occupations",
    note: "Median annual wage target for legal work exposed to document automation, legal research tools, and professional-services demand.",
  },
  {
    socCode: "25-0000",
    label: "Educational Instruction and Library Occupations",
    note: "Median annual wage target for education and library work, linking public budgets, staffing pressure, and AI tutoring/content tools.",
  },
  {
    socCode: "27-0000",
    label: "Arts, Design, Entertainment, Sports, and Media Occupations",
    note: "Median annual wage target for creative and media work exposed to generative AI, advertising demand, and production cycles.",
  },
  {
    socCode: "29-0000",
    label: "Healthcare Practitioners and Technical Occupations",
    note: "Median annual wage target for licensed clinical and technical healthcare work with strong demographic demand and limited near-term substitution.",
  },
  {
    socCode: "31-0000",
    label: "Healthcare Support Occupations",
    note: "Median annual wage target for a low-wage, high-demand care support group with strong staffing pressure and limited physical-task automation.",
  },
  {
    socCode: "33-0000",
    label: "Protective Service Occupations",
    note: "Median annual wage target for public safety and private security work shaped by staffing pressure and public budgets.",
  },
  {
    socCode: "35-0000",
    label: "Food Preparation and Serving Related Occupations",
    note: "Median annual wage target for food-service work where wage-floor pressure, consumer demand, and service automation interact.",
  },
  {
    socCode: "37-0000",
    label: "Building and Grounds Cleaning and Maintenance Occupations",
    note: "Median annual wage target for physical service work affected by labor supply, real estate occupancy, and limited automation.",
  },
  {
    socCode: "39-0000",
    label: "Personal Care and Service Occupations",
    note: "Median annual wage target for in-person service and care work shaped by demographics, wage floors, and discretionary demand.",
  },
  {
    socCode: "41-0000",
    label: "Sales and Related Occupations",
    note: "Median annual wage target for sales work exposed to retail demand, e-commerce, commissions, and AI sales-support tools.",
  },
  {
    socCode: "43-0000",
    label: "Office and Administrative Support Occupations",
    note: "Median annual wage target for routine clerical and administrative work, where automation may affect composition as well as employment.",
  },
  {
    socCode: "45-0000",
    label: "Farming, Fishing, and Forestry Occupations",
    note: "Median annual wage target for outdoor and seasonal work exposed to labor supply constraints, commodity demand, and mechanization.",
  },
  {
    socCode: "47-0000",
    label: "Construction and Extraction Occupations",
    note: "Median annual wage target for skilled trades tied to infrastructure, housing, energy, and limited short-run physical-task automation.",
  },
  {
    socCode: "49-0000",
    label: "Installation, Maintenance, and Repair Occupations",
    note: "Median annual wage target for hands-on technical work that may gain from diagnostics while remaining difficult to automate physically.",
  },
  {
    socCode: "51-0000",
    label: "Production Occupations",
    note: "Median annual wage target for production workers, connecting manufacturing labor demand, union/shortage pressure, and process automation.",
  },
  {
    socCode: "53-0000",
    label: "Transportation and Material Moving Occupations",
    note: "Median annual wage target for logistics, warehousing, driving, and material-moving work affected by routing software and warehouse automation.",
  },
] satisfies Array<Parameters<typeof oewsMajorOccupationWageTarget>[0]>;

export const OEWS_OCCUPATION_WAGE_TARGETS =
  OEWS_OCCUPATION_WAGE_TARGET_DEFINITIONS.flatMap((target) =>
    OEWS_OCCUPATION_WAGE_STATISTIC_ORDER.map((statistic) =>
      oewsMajorOccupationWageTarget({
        ...target,
        statistic,
        note: oewsWageTargetNote(target.note, statistic),
      }),
    ),
  ) satisfies TargetRegisteredLedgerEntry[];

function blsEmploymentProjectionOccupationTarget({
  socCode,
  label,
  note,
}: {
  socCode: string;
  label: string;
  note: string;
}): TargetRegisteredLedgerEntry {
  const dataPointId = `bls.employment_projections.national_occupation_employment.soc_${socCode.replace("-", "_")}.2034.actual_first_print`;
  return {
    kind: "target_registered",
    dataPointId,
    observationId: `obs.${dataPointId}`,
    country: "US",
    periodLabel: "2034 base-year employment",
    unit: "thousands",
    resolutionDate: "2035-09-15",
    resolutionSource: BLS_EMPLOYMENT_PROJECTIONS_SOURCE,
    resolutionSourceUrl: BLS_EMPLOYMENT_PROJECTIONS_TABLE_URL,
    resolutionRule:
      `Resolves to the first BLS Employment Projections/National Employment ` +
      `Matrix table that uses 2034 as the base year, for SOC ${socCode} ` +
      `${label}, measured as employment in thousands. The published 2024-2034 ` +
      `projection is only a comparison forecast; the resolved value is the ` +
      `first official 2034 base-year employment estimate in that later BLS ` +
      `projection vintage or successor table.`,
    resolutionPolicy: "first_print",
    sourceKind: "official_release",
    source: BLS_EMPLOYMENT_PROJECTIONS_SOURCE,
    sourceUrl: BLS_EMPLOYMENT_PROJECTIONS_TABLE_URL,
    note,
  };
}

export const BLS_2034_OCCUPATION_EMPLOYMENT_TARGETS = [
  blsEmploymentProjectionOccupationTarget({
    socCode: "13-0000",
    label: "Business and Financial Operations Occupations",
    note: "Long-run occupation forecast target for comparing Brier automation scenarios against the BLS 2024-2034 baseline on the same resolver.",
  }),
  blsEmploymentProjectionOccupationTarget({
    socCode: "15-0000",
    label: "Computer and Mathematical Occupations",
    note: "Long-run occupation forecast target for software, data, and quantitative work under AI adoption scenarios.",
  }),
  blsEmploymentProjectionOccupationTarget({
    socCode: "31-0000",
    label: "Healthcare Support Occupations",
    note: "Long-run occupation forecast target for a demographically driven, lower-substitution benchmark group.",
  }),
  blsEmploymentProjectionOccupationTarget({
    socCode: "43-0000",
    label: "Office and Administrative Support Occupations",
    note: "Long-run occupation forecast target for the largest routine clerical automation-exposure group.",
  }),
  blsEmploymentProjectionOccupationTarget({
    socCode: "51-0000",
    label: "Production Occupations",
    note: "Long-run occupation forecast target for manufacturing, robotics, and goods-sector automation exposure.",
  }),
  blsEmploymentProjectionOccupationTarget({
    socCode: "53-0000",
    label: "Transportation and Material Moving Occupations",
    note: "Long-run occupation forecast target for logistics, warehouse automation, routing, and autonomy exposure.",
  }),
] satisfies TargetRegisteredLedgerEntry[];

function cpsOccupationEmploymentTarget({
  key,
  label,
  note,
}: {
  key: string;
  label: string;
  note: string;
}): TargetRegisteredLedgerEntry {
  const dataPointId = `bls.cps.employed_people_by_occupation.${key}.june_2026.first_print`;
  return {
    kind: "target_registered",
    dataPointId,
    observationId: `obs.${dataPointId}`,
    country: "US",
    periodLabel: "June 2026 CPS first print",
    unit: "thousands",
    resolutionDate: "2026-07-02",
    resolutionSource: BLS_EMPLOYMENT_SITUATION_SOURCE,
    resolutionSourceUrl: BLS_CPS_A19_URL,
    resolutionRule:
      `Resolves to the first-published June 2026 Employment Situation ` +
      `household-survey Table A-19 count of employed people, not seasonally ` +
      `adjusted, for ${label}, in thousands. Later revisions, database ` +
      `refreshes, or monthly table replacements do not change the resolved ` +
      `value unless BLS replaces the first July 2, 2026 table on the same ` +
      `publication date.`,
    resolutionPolicy: "first_print",
    sourceKind: "official_release",
    source: BLS_EMPLOYMENT_SITUATION_SOURCE,
    sourceUrl: BLS_CPS_A19_URL,
    note,
  };
}

export const CPS_JUNE_2026_OCCUPATION_EMPLOYMENT_TARGETS = [
  cpsOccupationEmploymentTarget({
    key: "business_financial_operations",
    label: "Business and financial operations occupations",
    note: "Fast monthly CPS proxy for the business and financial OEWS/SOC occupation group; noisy but resolves weeks after forecast registration.",
  }),
  cpsOccupationEmploymentTarget({
    key: "computer_mathematical",
    label: "Computer and mathematical occupations",
    note: "Fast monthly CPS proxy for software, data, and quantitative labor demand.",
  }),
  cpsOccupationEmploymentTarget({
    key: "healthcare_support",
    label: "Healthcare support occupations",
    note: "Fast monthly CPS proxy for lower-substitution, care-demand-sensitive occupations.",
  }),
  cpsOccupationEmploymentTarget({
    key: "office_administrative_support",
    label: "Office and administrative support occupations",
    note: "Fast monthly CPS proxy for routine clerical and administrative automation exposure.",
  }),
  cpsOccupationEmploymentTarget({
    key: "production",
    label: "Production occupations",
    note: "Fast monthly CPS proxy for manufacturing and process-automation exposure.",
  }),
  cpsOccupationEmploymentTarget({
    key: "transportation_material_moving",
    label: "Transportation and material moving occupations",
    note: "Fast monthly CPS proxy for logistics, warehouse automation, routing, and autonomy exposure.",
  }),
] satisfies TargetRegisteredLedgerEntry[];

function snapFy2026PaymentErrorRateTarget({
  code,
  label,
}: {
  code: string;
  label: string;
}): TargetRegisteredLedgerEntry {
  const dataPointId = `fns.snap.total_payment_error_rate.${code}.fy2026`;
  const subject = label === "national" ? "the national" : `${label}'s`;
  return {
    kind: "target_registered",
    dataPointId,
    observationId: `obs.${dataPointId}`,
    country: "US",
    periodLabel: "FY 2026",
    unit: "percent",
    resolutionDate: "2027-06-30",
    resolutionSource: USDA_FNS_SNAP_QC_SOURCE,
    resolutionSourceUrl: USDA_FNS_SNAP_QC_URL,
    resolutionRule:
      `Resolves to ${subject} combined SNAP payment error rate ` +
      `(overpayments plus underpayments) for fiscal year 2026 in the official ` +
      `FNS QC release, first print. FNS released FY 2025 rates on June 24, ` +
      `2026; the FY 2026 release is expected around June 2027.`,
    resolutionPolicy: "first_print",
    sourceKind: "official_release",
    source: USDA_FNS_SNAP_QC_SOURCE,
    sourceUrl: USDA_FNS_SNAP_QC_URL,
    note: `Target registration for ${label} SNAP payment error rate, FY 2026.`,
  };
}

function snapFy2026NationalPaymentErrorComponentTarget({
  component,
  label,
}: {
  component: "overpayment" | "underpayment";
  label: string;
}): TargetRegisteredLedgerEntry {
  const dataPointId = `fns.snap.${component}_payment_error_rate.us.fy2026`;
  return {
    kind: "target_registered",
    dataPointId,
    observationId: `obs.${dataPointId}`,
    country: "US",
    periodLabel: "FY 2026",
    unit: "percent",
    resolutionDate: "2027-06-30",
    resolutionSource: USDA_FNS_SNAP_QC_SOURCE,
    resolutionSourceUrl: USDA_FNS_SNAP_QC_URL,
    resolutionRule:
      `Resolves to the national SNAP ${label} error rate for fiscal ` +
      `year 2026 in the official FNS QC release, first print. FNS released ` +
      `FY 2025 rates on June 24, 2026; the FY 2026 release is expected ` +
      `around June 2027.`,
    resolutionPolicy: "first_print",
    sourceKind: "official_release",
    source: USDA_FNS_SNAP_QC_SOURCE,
    sourceUrl: USDA_FNS_SNAP_QC_URL,
    note: `Target registration for national SNAP ${label} payment error rate, FY 2026.`,
  };
}

export const SNAP_FY2026_PAYMENT_ERROR_RATE_TARGETS = SNAP_QC_JURISDICTIONS.map(
  ([code, label]) => snapFy2026PaymentErrorRateTarget({ code, label }),
) satisfies TargetRegisteredLedgerEntry[];

export const SNAP_FY2026_PAYMENT_ERROR_COMPONENT_TARGETS = [
  snapFy2026NationalPaymentErrorComponentTarget({
    component: "overpayment",
    label: "overpayment",
  }),
  snapFy2026NationalPaymentErrorComponentTarget({
    component: "underpayment",
    label: "underpayment",
  }),
] satisfies TargetRegisteredLedgerEntry[];

function blsCesEmploymentTarget({
  dataPointKey,
  seriesId,
  label,
  note,
}: {
  dataPointKey: string;
  seriesId: string;
  label: string;
  note: string;
}): TargetRegisteredLedgerEntry {
  const dataPointId = `bls.ces.${dataPointKey}.june_2026.first_print`;
  return {
    kind: "target_registered",
    dataPointId,
    observationId: `obs.${dataPointId}`,
    country: "US",
    periodLabel: "June 2026",
    unit: "thousands",
    resolutionDate: "2026-07-02",
    resolutionSource: BLS_CES_SOURCE,
    resolutionSourceUrl: `${BLS_CES_API_URL}/${seriesId}`,
    resolutionRule:
      `Resolves to the first-published June 2026 BLS CES all-employees ` +
      `value for ${seriesId} (${label}), seasonally adjusted, in thousands ` +
      `of workers. Later benchmark revisions, seasonal-factor updates, or ` +
      `database refreshes do not change the resolved value unless BLS ` +
      `replaces the first July 2, 2026 release on that publication date.`,
    resolutionPolicy: "first_print",
    sourceKind: "official_release",
    source: BLS_CES_SOURCE,
    sourceUrl: BLS_CES_API_URL,
    note,
  };
}

export const US_DEFENSE_PUBLIC_DATA_TARGETS = [
  blsCesEmploymentTarget({
    dataPointKey: "aerospace_product_and_parts_employment",
    seriesId: "CES3133640001",
    label: "Aerospace product and parts manufacturing",
    note: "Defense-industrial-base capacity proxy tied to aircraft, missiles, spacecraft, and major aerospace supply-chain production.",
  }),
  blsCesEmploymentTarget({
    dataPointKey: "ship_and_boat_building_employment",
    seriesId: "CES3133660001",
    label: "Ship and boat building",
    note: "Defense shipbuilding capacity proxy for naval procurement, yard labor constraints, and maritime industrial-base policy.",
  }),
  blsCesEmploymentTarget({
    dataPointKey: "federal_department_of_defense_employment",
    seriesId: "CES9091911001",
    label: "Federal government, Department of Defense",
    note: "Civilian DoD employment proxy for personnel authorities, hiring freezes, and execution capacity inside the department.",
  }),
  {
    kind: "target_registered",
    dataPointId:
      "treasury.mts.dod_military_programs_gross_outlays.june_2026.first_print",
    observationId:
      "obs.treasury.mts.dod_military_programs_gross_outlays.june_2026.first_print",
    country: "US",
    periodLabel: "June 2026",
    unit: "usd_billions",
    resolutionDate: "2026-07-13",
    resolutionSource: TREASURY_MTS_SOURCE,
    resolutionSourceUrl: TREASURY_MTS_TABLE_5_URL,
    resolutionRule:
      "Resolves to Monthly Treasury Statement table 5 line 5.12, Total--Department of Defense--Military Programs, current-month gross outlays for June 2026, divided by 1 billion dollars. The first published MTS table governs; later revisions or database refreshes do not change the resolved value unless Treasury replaces the first table on the same publication date.",
    resolutionPolicy: "first_print",
    sourceKind: "official_release",
    source: TREASURY_MTS_SOURCE,
    sourceUrl: TREASURY_MTS_TABLE_5_URL,
    note: "Fast official cash-flow target for Pentagon budget execution and appropriation-to-outlay timing.",
  },
  {
    kind: "target_registered",
    dataPointId:
      "usaspending.dod.contract_obligations.fy2026.fixed_vintage_2026_12_31",
    observationId:
      "obs.usaspending.dod.contract_obligations.fy2026.fixed_vintage_2026_12_31",
    country: "US",
    periodLabel: "FY 2026",
    unit: "usd_billions",
    resolutionDate: "2026-12-31",
    resolutionSource: USASPENDING_SOURCE,
    resolutionSourceUrl: USASPENDING_DOD_AWARD_CATEGORY_URL,
    resolutionRule:
      "Resolves to USAspending agency 097 obligations_by_award_category for fiscal_year=2026, category=contracts, aggregated_amount divided by 1 billion dollars, using a data pull on December 31, 2026. This fixed-vintage rule avoids treating later FPDS or DATA Act refreshes as forecast revisions.",
    resolutionPolicy: "fixed_vintage",
    sourceKind: "official_release",
    source: USASPENDING_SOURCE,
    sourceUrl: USASPENDING_DOD_AWARD_CATEGORY_URL,
    note: "Public contract-obligations target for tracking how appropriated resources convert into awards.",
  },
] satisfies TargetRegisteredLedgerEntry[];

export const THESIS_TARGET_LEDGER = dedupeTargetLedger([
  ...OEWS_OCCUPATION_EMPLOYMENT_TARGETS,
  ...OEWS_OCCUPATION_WAGE_TARGETS,
  ...BLS_2034_OCCUPATION_EMPLOYMENT_TARGETS,
  ...CPS_JUNE_2026_OCCUPATION_EMPLOYMENT_TARGETS,
  ...SNAP_FY2026_PAYMENT_ERROR_RATE_TARGETS,
  ...SNAP_FY2026_PAYMENT_ERROR_COMPONENT_TARGETS,
  ...US_DEFENSE_PUBLIC_DATA_TARGETS,
  ...GENERATED_FORECAST_TARGETS,
]);

function dedupeTargetLedger(
  targets: TargetRegisteredLedgerEntry[],
): TargetRegisteredLedgerEntry[] {
  const seen = new Set<string>();
  return targets.filter((target) => {
    if (seen.has(target.dataPointId)) return false;
    seen.add(target.dataPointId);
    return true;
  });
}

export function getLedgerTargetByDataPointId(
  dataPointId: string,
): TargetRegisteredLedgerEntry | undefined {
  return THESIS_TARGET_LEDGER.find(
    (entry) => entry.dataPointId === dataPointId,
  );
}

export function requireLedgerTarget(
  dataPointId: string,
): TargetRegisteredLedgerEntry {
  const target = getLedgerTargetByDataPointId(dataPointId);
  if (!target) {
    throw new Error(`Missing Thesis target ledger entry for ${dataPointId}`);
  }
  return target;
}

export function targetRegistrationState(
  target: TargetRegisteredLedgerEntry,
): "preregistered" | "published" {
  return target.registrationState ?? "published";
}

export function isPreregisteredTargetWithinOrphanGrace(
  target: TargetRegisteredLedgerEntry,
  now: Date = new Date(),
): boolean {
  if (targetRegistrationState(target) !== "preregistered") return false;
  const registeredAt = Date.parse(target.registeredAt ?? "");
  if (!Number.isFinite(registeredAt)) return false;
  const age = now.getTime() - registeredAt;
  return (
    age >= 0 &&
    age <= TARGET_PREREGISTRATION_ORPHAN_GRACE_DAYS * 24 * 60 * 60 * 1000
  );
}
