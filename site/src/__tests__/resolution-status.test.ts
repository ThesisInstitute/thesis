import { describe, expect, it } from "vitest";
import { resolutionVerb } from "@/components/ForecastCard";
import { FORECAST_CELLS } from "@/data/forecast-cells";
import { buildForecastListing } from "@/data/forecast-listing";
import rawStatus from "@/data/resolution-status.json";
import {
  NO_REPORT_REASON,
  RESOLUTION_STATUS_META,
  VOIDED_CODE,
  overdueNotice,
  shortReason,
  type OverdueStatus,
} from "@/data/resolution-status";

const row: OverdueStatus = {
  dataPointId: "treasury.mts.monthly_deficit.june_2026.first_print",
  forecastSlug: "us-mts-deficit-june-2026",
  resolutionDate: "2026-07-13",
  state: "no_route",
  code: "NO_ROUTE_GENERIC_URL",
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

describe("voided targets", () => {
  const voided: OverdueStatus = {
    ...row,
    state: "voided",
    code: VOIDED_CODE,
    reason:
      "This forecast is void and will not resolve. A recorded ruling found that its registered contract cannot be resolved as written.",
    ruling:
      "The registered source is SSA's July 2026 table, so it cannot hold the August 2026 figure this forecast names. Voided by ruling on 2026-10-22.",
  };
  const notice = overdueNotice(
    { slug: row.forecastSlug, status: "pending", resolutionDate: "2026-07-13" },
    { asOf: "2026-10-22", lookup: () => voided },
  );

  it("carry the ruling, never as the resolver's words", () => {
    expect(notice?.code).toBe(VOIDED_CODE);
    expect(notice?.ruling).toBe(voided.ruling);
    expect(notice && "detail" in notice).toBe(false);
  });

  it("lead the compact card with the void, not a refusal", () => {
    expect(shortReason(voided.reason)).toBe(
      "This forecast is void and will not resolve.",
    );
  });

  const rows = Object.entries(rawStatus.targets) as [
    string,
    Omit<OverdueStatus, "dataPointId">,
  ][];
  const voidedRows = rows.filter(([, status]) => status.code === VOIDED_CODE);

  it("are VOIDED in the committed file exactly when they carry a ruling", () => {
    // Not vacuous: the file holds the voids a ruling recorded (d1633), and
    // tests/test_voided_targets.py ties each one to the register.
    expect(voidedRows.length).toBeGreaterThan(0);
    for (const [dataPointId, status] of rows) {
      const hasRuling = "ruling" in status && Boolean(status.ruling);
      expect(status.code === VOIDED_CODE, dataPointId).toBe(hasRuling);
    }
    for (const [dataPointId, status] of voidedRows) {
      expect(status.ruling, dataPointId).toMatch(
        / Voided by ruling on \d{4}-\d{2}-\d{2}\.$/,
      );
    }
  });

  it("are the forecasts the listing marks Void, and no others", () => {
    const listing = buildForecastListing(FORECAST_CELLS);
    const marked = new Set(
      listing.filter((item) => item.overdue?.voided).map((item) => item.slug),
    );
    expect(marked).toEqual(
      new Set(voidedRows.map(([, status]) => status.forecastSlug)),
    );
    for (const item of listing) {
      if (item.overdue && !item.overdue.voided) {
        expect(item.overdue.reason, item.slug).not.toMatch(/void/i);
      }
    }
  });
});

describe("registration facts", () => {
  it("pass through as registration, never as the resolver's words", () => {
    // R26/R27: a no-route row's adapter and series are registration facts.
    // The page prints `detail` after "resolver:", so they must not arrive
    // there.
    const noRoute: OverdueStatus = {
      ...row,
      code: "NO_ROUTE_ADAPTER_REGISTERED",
      registration:
        "adapter alfred-fred, series bls.ppi.final_demand_monthly_change",
    };
    const notice = overdueNotice(
      { slug: row.forecastSlug, status: "pending", resolutionDate: "2026-07-13" },
      { asOf: "2026-09-19", lookup: () => noRoute },
    );
    expect(notice?.registration).toBe(noRoute.registration);
    expect(notice && "detail" in notice).toBe(false);
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
      // A reference the resolver has no route for has no resolver words:
      // what it knows about the target is registration facts, labelled so.
      if (row.code.startsWith("NO_ROUTE_")) {
        expect("detail" in row, dataPointId).toBe(false);
      }
    }
  });
});
