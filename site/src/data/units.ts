// The one list of units the site accepts. The Unit type, the ledger-fact
// check in thesis-log.ts and the generated-registration test all read it,
// so a runtime check cannot drift from the type again (2026-10-17: the
// type admitted "billions USD" but thesis-log.ts kept its own copy that did
// not, and the first ledger row in that unit failed every production build).
export const UNITS = [
  "count",
  "percent",
  "gbp_billions",
  "usd",
  "usd_millions",
  "usd_billions",
  // Non-canonical variant, tolerated since 2026-08-03 (5c6bc9d1). The DoD
  // USAspending targets registered 2026-08-07 and 2026-08-13 carry it, and
  // registrations are immutable. Canonical is "usd_billions";
  // registration-side enum validation is the follow-up.
  "billions USD",
  "usd_monthly",
  "thousands",
  "millions",
  "million_cubic_feet",
  "per_1000_live_births",
  "ratio",
  "minutes",
  "percent_growth",
  "index_points",
] as const;

export type Unit = (typeof UNITS)[number];

const UNIT_SET: ReadonlySet<string> = new Set(UNITS);

export function isUnit(unit: unknown): unit is Unit {
  return typeof unit === "string" && UNIT_SET.has(unit);
}
