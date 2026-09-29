import { describe, expect, it } from "vitest";
import { resolutionVerb } from "@/components/ForecastCard";
import { FORECAST_CELLS } from "@/data/forecast-cells";
import rawStatus from "@/data/resolution-status.json";
import {
  NO_REPORT_REASON,
  RESOLUTION_STATUS_META,
  overdueNotice,
  shortReason,
  type OverdueStatus,
} from "@/data/resolution-status";

const row: OverdueStatus = {
  dataPointId: "treasury.mts.monthly_deficit.june_2026.first_print",
  forecastSlug: "us-mts-deficit-june-2026",
  resolutionDate: "2026-07-13",
  state: "no_executor",
  code: "NO_EXECUTOR_GENERIC_URL",
  reason:
    "The resolver has no route for this target's reference. The target was registered with a generic source link rather than a resolver binding.",
};
const file = {
  asOf: "2026-09-19",
  lookup: (slug: string) => (slug === row.forecastSlug ? row : undefined),
};

describe("overdueNotice", () => {
  it("states the resolver's reason for a pending forecast past its date", () => {
    expect(
      overdueNotice(
        { slug: row.forecastSlug, status: "pending", resolutionDate: "2026-07-13" },
        file,
      ),
    ).toEqual({ since: "2026-07-13", code: row.code, reason: row.reason });
  });

  it("never marks a resolved forecast overdue, whatever the file says", () => {
    // The file is as old as the last resolver run; the ledger may be newer.
    expect(
      overdueNotice(
        { slug: row.forecastSlug, status: "resolved", resolutionDate: "2026-07-13" },
        file,
      ),
    ).toBeNull();
  });

  it("leaves a forecast that is not yet due alone", () => {
    for (const resolutionDate of ["2026-09-19", "2026-10-30", "2035-09-15T00:00:00Z"]) {
      expect(
        overdueNotice({ slug: "later", status: "pending", resolutionDate }, file),
      ).toBeNull();
    }
  });

  it("says so when it is past due and no resolver run has reported on it", () => {
    expect(
      overdueNotice(
        { slug: "published-after-the-run", status: "pending", resolutionDate: "2026-09-01" },
        file,
      ),
    ).toEqual({ since: "2026-09-01", code: "NO_REPORT", reason: NO_REPORT_REASON });
  });

  it("carries the resolver's detail when there is one", () => {
    const detailed = { ...row, code: "UNIT_MISMATCH", detail: "cell='millions' adapter='thousands'" };
    expect(
      overdueNotice(
        { slug: row.forecastSlug, status: "pending", resolutionDate: "2026-07-13" },
        { asOf: "2026-09-19", lookup: () => detailed },
      )?.detail,
    ).toBe("cell='millions' adapter='thousands'");
  });
});

describe("card wording", () => {
  it("does not promise a future resolution for a date that has passed", () => {
    expect(resolutionVerb({ status: "pending", overdue: null })).toBe("resolves");
    expect(
      resolutionVerb({
        status: "pending",
        overdue: { since: "2026-07-13", reason: shortReason(row.reason) },
      }),
    ).toBe("was due");
    expect(resolutionVerb({ status: "resolved", overdue: null })).toBe("resolved");
  });

  it("shortens a reason to its first sentence", () => {
    expect(shortReason(row.reason)).toBe(
      "The resolver has no route for this target's reference.",
    );
    expect(shortReason("One sentence only.")).toBe("One sentence only.");
  });
});

describe("the committed status file", () => {
  // Completeness (one row per overdue pending target, nothing extra) is a
  // property of scripts/resolution_status.py, tested there against the
  // Thesis log; this site has no view of that log's pending links.
  it("names only published forecasts past their own due date", () => {
    expect(RESOLUTION_STATUS_META.asOf).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    const rows = Object.entries(rawStatus.targets);
    // Each row is a forecast this site publishes, on the target it
    // forecasts, past its own due date as of the file's date, and
    // explained.
    const cells = new Map(FORECAST_CELLS.map((cell) => [cell.slug, cell]));
    for (const [dataPointId, row] of rows) {
      const cell = cells.get(row.forecastSlug);
      expect(cell, row.forecastSlug).toBeDefined();
      if (cell?.dataPointId) expect(cell.dataPointId).toBe(dataPointId);
      expect(cell?.resolutionDate.slice(0, 10)).toBe(row.resolutionDate);
      expect(row.resolutionDate < RESOLUTION_STATUS_META.asOf).toBe(true);
      expect(row.code).toMatch(/^[A-Z_]+$/);
      expect(row.reason.length).toBeGreaterThan(0);
    }
  });
});
