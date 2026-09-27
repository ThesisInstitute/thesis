import {
  getConditionalGroup,
  type ResolvedConditionalGroup,
} from "./conditional-groups";
import reviewedBillBindings from "../../../scripts/bill_forecast_bindings.json";

/**
 * Links bill analyses (bills/<slug>.json) to registered conditional
 * forecast groups. One link per forecast metric: the group's true arm
 * is the outcome conditional on the bill's provision surviving into
 * enacted law, the false arm is the baseline (not enacted).
 *
 * Populated through the privileged registration path — the ingest lane
 * auto-drafts cell specs into drafts/, and links land here only when
 * the pair is actually registered. Never link a group whose condition
 * is not provision-anchored to the bill named by billSlug.
 */
export interface BillForecastLink {
  billSlug: string;
  /** Short label for the metric selector, e.g. "CRP enrolled acres". */
  metricLabel: string;
  groupSlug: string;
  /**
   * True when the pair is a real registered group from ANOTHER policy
   * state, linked purely to demonstrate the view. Rendered with an
   * explicit example banner; remove once real bill-anchored pairs are
   * registered. Never omit this flag on a pair that is not
   * provision-anchored to billSlug.
   */
  example?: boolean;
}

export const BILL_FORECAST_LINKS: BillForecastLink[] = [
  {
    billSlug: "farm-bill-2-0",
    metricLabel: "CRP enrolled acres (Sep 2027)",
    groupSlug: "crp-enrolled-acres-sep2027-ceiling-27m",
  },
  ...Object.entries(reviewedBillBindings.bills).flatMap(([billSlug, bill]) =>
    bill.pairs.map(({ metricLabel, groupSlug }) => ({
      billSlug,
      metricLabel,
      groupSlug,
    })),
  ),
];

/**
 * Registered conditional questions whose runs have not produced a cell:
 * either every documented attempt failed closed (refusal or validation
 * failure — no observations, no invented values) or the run is still in
 * flight. Nothing here is a forecast; it is the honest state of the
 * machine.
 */
export interface PendingConditional {
  billSlug: string;
  question: string;
  status: "refused" | "pending";
  /**
   * Editorial account of the attempt history and its public evidence —
   * not verbatim runner output (raw traces may be retained off-repo).
   */
  note?: string;
}

export const PENDING_CONDITIONALS: PendingConditional[] = [
  {
    billSlug: "farm-bill-2-0",
    question:
      "USDA FSA total CRP enrolled acres in the September 2027 CRP Monthly Summary — conditional on enactment of a 27,000,000-acre FY2027–31 ceiling versus no enacted FY2027–31 ceiling by 2027-09-30.",
    status: "refused",
    note: "Both arms were preregistered through the trusted docket on 2026-08-03 — chronology witnessed before any forecasting. Every documented attempt failed closed and published nothing: the two August 3 rolls made four generation attempts (two failed before producing run manifests; two produced candidate cells that failed anchor validation — all visible in the public workflow logs), and after a generation ticket was minted on 2026-08-04 (public record), the ticketed local run refused when the FSA statistics site failed to serve the official summary (fetch timeout — no observations, no invented values); the refusal report on issue #128 is public, while the raw refusal trace is retained off-repo. FSA was unreachable on 2026-08-04 and still unreachable at the pair's published seven-day grace deadline (2026-08-10 18:15 UTC), so both registrations terminated together on the record rather than forecasting against a stale information set. A fresh pair may be registered if the source recovers.",
  },
];

export function getPendingConditionals(billSlug: string): PendingConditional[] {
  return PENDING_CONDITIONALS.filter((p) => p.billSlug === billSlug);
}

/**
 * Links a bill page to registered UNCONDITIONAL context series: series
 * the docket tracks because the bill made them worth watching. A
 * context series is forecast regardless of the bill and never resolves
 * any bill metric — that boundary is carried in scopeNote and rendered
 * on the page next to the cell, not buried in a code comment. Populate
 * only for series admitted to the docket; seriesConcept is the
 * canonical Chronicle concept, which cell dataPointIds extend.
 */
export interface BillContextSeriesLink {
  billSlug: string;
  /** Canonical series concept; matched as a dataPointId prefix. */
  seriesConcept: string;
  /** Short display label for the series. */
  label: string;
  /** Generation lane for an admitted series whose first cell is pending. */
  pendingForecastLane?: "ticketed-attested";
  /** Verbatim-rendered scope boundary: what this series is NOT. */
  scopeNote: string;
}

export const BILL_CONTEXT_SERIES_LINKS: BillContextSeriesLink[] = [
  {
    billSlug: "flare-act-s1188-119",
    seriesConcept: "eia.ng.vented_flared.us.annual",
    label: "U.S. natural gas vented and flared (2025 annual value)",
    pendingForecastLane: "ticketed-attested",
    scopeNote:
      "Broad U.S. natural-gas venting-and-flaring outcome and " +
      "timing-tracking context only. Not facility-level activity, " +
      "compliance, enforcement, fees, or emissions reductions under S. " +
      "1188; no annual value or change is attributed to or treated as " +
      "caused by the FLARE Act.",
  },
  {
    billSlug: "cdfi-fund-s2718-119",
    seriesConcept: "usaspending.cdfi.assistance_transaction_obligations",
    label: "CDFI Fund assistance-transaction obligations (FY2026)",
    scopeNote:
      "USAspending award-transaction aggregate for the CDFI Fund awarding " +
      "subtier. Not all CDFI Fund financial-account obligations or outlays; " +
      "not purchases, guarantees, loan-loss reserves, or other assistance " +
      "authorized by S. 2718; not CDFI loan originations, liquidity, " +
      "competitiveness, or other downstream outcomes; and no spending is " +
      "attributed to the bill or amended section 113.",
  },
  {
    billSlug: "hidta-enhancement-s767-119",
    seriesConcept: "usaspending.ondcp.hidta_al95001_obligations",
    label: "HIDTA award-transaction obligations, AL 95.001 (FY2026)",
    scopeNote:
      "The whole Assistance Listing 95.001 award-transaction aggregate. Not " +
      "section 707(s) supplemental competitive grants or spending under a " +
      "newly permitted purpose; not all HIDTA financial-account " +
      "obligations, outlays, appropriations, budget authority, or " +
      "authorization; and no spending is attributed to S. 767.",
  },
  {
    billSlug: "future-networks-hr2449-119",
    seriesConcept: "usaspending.ntia.broadband_al11038_obligations",
    label: "Advanced-wireless grant obligations, AL 11.038 (FY2026)",
    scopeNote:
      "The Assistance Listing 11.038 award-transaction aggregate (FY2025 " +
      "awards under this listing were assigned to NIST). Not the proposed " +
      "6G Task Force, its work, reports, recommendations, or outcomes; not " +
      "all NTIA, NIST, Commerce, or FCC obligations or account 013-0565; " +
      "and no spending is attributed to or treated as caused or authorized " +
      "by H.R. 2449.",
  },
  {
    billSlug: "superior-national-forest-hr978-119",
    seriesConcept:
      "usaspending.usfs.minnesota_place_of_performance_obligations",
    label:
      "Forest Service award-transaction obligations, Minnesota place of " +
      "performance (FY2026)",
    scopeNote:
      "Minnesota-wide award-transaction context only, not Superior National " +
      "Forest obligations or activity confined to the bill's covered lands; " +
      "not H.R. 978 implementation, mineral instruments, or deadline " +
      "compliance; and no spending is attributed to or treated as caused by " +
      "H.R. 978.",
  },
  {
    billSlug: "remit-act-hr5595-119",
    seriesConcept: "bea.ita.personal_transfer_payments",
    label: "Personal-transfer payments, seasonally adjusted (2026 Q2)",
    scopeNote:
      "BEA ITA Table 5.1 line 18 Personal transfers, quarterly seasonally " +
      "adjusted in millions of dollars, is a broad personal-transfers flow " +
      "proxy (https://apps.bea.gov/iTable/?ReqID=62&step=6&isuri=1&tablelist=62&product=1). " +
      "It does not measure the section 4475 remittance-excise base, sender " +
      "citizenship, provider qualification, tax liability or receipts, or " +
      "section 36C credits; no value is attributed to H.R. 5595, and this " +
      "series never resolves any H.R. 5595 causal claim " +
      "(https://www.congress.gov/119/bills/hr5595/BILLS-119hr5595ih.pdf).",
  },
  {
    billSlug: "farm-bill-2-0",
    seriesConcept: "bls.qcew.child_day_care_services.annual_avg_employment",
    label: "Private child-day-care annual-average employment",
    scopeNote:
      "National private child-day-care payroll employment context. Not " +
      "rural-county employment, all-ownership coverage, self-employment, " +
      "slots/affordability/capacity, or any employment change caused by or " +
      "attributable to the bill.",
  },
];

export function getBillContextSeriesLinks(
  billSlug: string,
): BillContextSeriesLink[] {
  return BILL_CONTEXT_SERIES_LINKS.filter((l) => l.billSlug === billSlug);
}

export interface BillForecastGroup {
  metricLabel: string;
  resolved: ResolvedConditionalGroup;
  example: boolean;
}

export function getBillForecastGroups(billSlug: string): BillForecastGroup[] {
  return BILL_FORECAST_LINKS.filter((link) => link.billSlug === billSlug)
    .map((link) => {
      const resolved = getConditionalGroup(link.groupSlug);
      return resolved
        ? {
            metricLabel: link.metricLabel,
            resolved,
            example: link.example === true,
          }
        : undefined;
    })
    .filter((group): group is BillForecastGroup => group !== undefined);
}
