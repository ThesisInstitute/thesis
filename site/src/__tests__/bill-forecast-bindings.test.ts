import { describe, expect, it } from "vitest";
import registry from "../../../scripts/bill_forecast_bindings.json";
import { CONDITIONAL_GROUPS } from "@/data/conditional-groups";
import { BILL_FORECAST_LINKS } from "@/data/bill-forecasts";

describe("reviewed bill forecast mapping", () => {
  for (const [billSlug, bill] of Object.entries(registry.bills)) {
    for (const pair of bill.pairs) {
      it(`${billSlug}: ${pair.series} links the exact reviewed sibling pair`, () => {
        const group = CONDITIONAL_GROUPS.find((g) => g.slug === pair.groupSlug);
        expect(group).toBeDefined();
        expect([group?.trueArmSlug, group?.falseArmSlug]).toEqual(pair.catalogSlugs);
        expect(BILL_FORECAST_LINKS).toContainEqual({
          billSlug,
          groupSlug: pair.groupSlug,
          metricLabel: pair.metricLabel,
        });
      });
    }
  }
});
