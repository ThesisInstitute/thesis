import { getPublishedForecast } from "@/lib/forecast-publication";
import { type ForecastCell } from "./forecast-cells";

export interface ConditionalGroup {
  slug: string;
  title: string;
  question: string;
  eventLabel: string;
  trueArmSlug: string;
  /** Absent for single-arm registrations (enacted-conditional only). */
  falseArmSlug?: string;
  probabilitySlug?: string;
  unconditionalSlug?: string;
  gapNote?: string;
  /**
   * True when the two arms' conditions are deliberately not exhaustive:
   * at most one arm resolves, and an intermediate policy outcome resolves
   * neither. Surfaces must not claim "exactly one arm resolves."
   */
  nonExhaustivePair?: boolean;
}

export const CONDITIONAL_GROUPS: ConditionalGroup[] = [
  {
    slug: "crp-enrolled-acres-sep2027-ceiling-27m",
    title: "CRP enrolled acres under the FY2027–31 ceiling",
    question:
      "What will USDA FSA's CRP Monthly Summary report for total enrolled acres in September 2027 under a 27,000,000-acre FY2027–31 ceiling versus no enacted FY2027–31 ceiling?",
    eventLabel:
      "An enacted farm bill sets the CRP acreage ceiling at 27,000,000 acres for FY2027–31",
    trueArmSlug:
      "us-crp-enrolled-acres-september-2027-ceiling-27-million-source-recovered-2026-08-13",
    falseArmSlug:
      "us-crp-enrolled-acres-september-2027-no-fy2027-31-ceiling-source-recovered-2026-08-13",
    gapNote:
      "The 467,981-acre gap between arms is the forecasted effect of the " +
      "27,000,000-acre FY2027–31 ceiling on September 2027 CRP enrollment " +
      "— published before Congress decides. Each arm resolves against the " +
      "USDA FSA CRP Monthly Summary first print when its registered " +
      "condition holds; an enactment setting a different FY2027–31 ceiling " +
      "resolves neither arm.",
    nonExhaustivePair: true,
  },
  {
    slug: "spm-child-poverty-cy2027-threshold-one-dollar",
    title: "Child SPM poverty under the $1 earned-income threshold",
    question:
      "What does S. 3596's $1 earned-income threshold do to the CY2027 Supplemental Poverty Measure child poverty rate?",
    eventLabel:
      "Threshold ≤ $1 enacted for TY2027 (legislation enacted by 2027-12-31)",
    trueArmSlug: "spm-child-poverty-rate-cy2027-threshold-one-dollar",
    falseArmSlug: "spm-child-poverty-rate-cy2027-current-law",
    gapNote:
      "The 0.2-point gap between arms is the forecasted effect of the $1 " +
      "threshold on CY2027 child SPM poverty — published before Congress " +
      "decides, resolving against the first revised-methodology CY2027 " +
      "print by the registered 2028-12-31 bound. An intermediate " +
      "enactment (say, a $500 threshold) resolves neither arm.",
    nonExhaustivePair: true,
  },
  {
    slug: "actc-claims-ty2027-threshold-one-dollar",
    title: "ACTC claims under the $1 earned-income threshold",
    question:
      "What does S. 3596's $1 earned-income threshold do to the number of TY2027 Additional Child Tax Credit claims?",
    eventLabel:
      "Threshold ≤ $1 enacted for TY2027 (legislation enacted by 2027-12-31)",
    trueArmSlug:
      "additional-child-tax-credit-total-claims-ty2027-threshold-one-dollar",
    falseArmSlug: "additional-child-tax-credit-total-claims-ty2027-current-law",
    gapNote:
      "The 9.6-million-return gap between arms is the forecasted effect of " +
      "dropping the earned-income threshold from $2,500 to $1 — published " +
      "before Congress decides. Each arm resolves against the IRS Table " +
      "3.3 first print when its registered condition holds; an " +
      "intermediate enactment (say, a $500 threshold) resolves neither.",
    nonExhaustivePair: true,
  },
  {
    slug: "medicaid-work-req-wait-mar-2027",
    title: "Medicaid hold times under the work-requirement deadline",
    question:
      "What does the December 31, 2026 community-engagement compliance deadline do to the national average Medicaid call-center wait in March 2027?",
    eventLabel:
      "Deadline in effect as of 2027-03-31 (no statutory delay, no nationwide stay)",
    trueArmSlug: "medicaid-call-wait-mar-2027-work-req-deadline-holds",
    falseArmSlug: "medicaid-call-wait-mar-2027-work-req-deadline-delayed",
    probabilitySlug: "medicaid-work-req-deadline-in-effect-2027q1",
    unconditionalSlug: "medicaid-call-wait-mar-2027",
    gapNote:
      "At roughly 10 million calls a month, the 11-minute gap between arms is about 1.8 million person-hours of waiting per month riding on this one policy state.",
  },
  {
    slug: "snap-cost-share-error-rate-fy2026",
    title: "SNAP payment accuracy under the cost-share provision",
    question:
      "What does the 2025 reconciliation law's state cost-share provision do to the national SNAP payment error rate in FY 2026?",
    eventLabel:
      "Cost-share provision in effect through 2027-06-30 (no repeal or delay enacted)",
    trueArmSlug: "snap-error-rate-fy2026-cost-share-in-effect",
    falseArmSlug: "snap-error-rate-fy2026-cost-share-repealed",
    gapNote:
      "The 0.9-point gap between arms is the forecasted effect of the cost-share incentive on payment accuracy — published before the policy question is settled.",
  },
];

export interface ResolvedConditionalGroup {
  group: ConditionalGroup;
  trueArm: ForecastCell;
  falseArm?: ForecastCell;
  probability?: ForecastCell;
  unconditional?: ForecastCell;
}

export function getConditionalGroup(
  slug: string,
): ResolvedConditionalGroup | undefined {
  const group = CONDITIONAL_GROUPS.find((g) => g.slug === slug);
  if (!group) return undefined;
  const trueArm = getPublishedForecast(group.trueArmSlug);
  const falseArm = group.falseArmSlug
    ? getPublishedForecast(group.falseArmSlug)
    : undefined;
  if (!trueArm) return undefined;
  // A named-but-missing baseline arm is a data error — fail closed.
  if (group.falseArmSlug && !falseArm) return undefined;
  return {
    group,
    trueArm,
    falseArm,
    probability: group.probabilitySlug
      ? getPublishedForecast(group.probabilitySlug)
      : undefined,
    unconditional: group.unconditionalSlug
      ? getPublishedForecast(group.unconditionalSlug)
      : undefined,
  };
}
