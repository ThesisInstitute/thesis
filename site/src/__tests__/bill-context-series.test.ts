import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  BILL_CONTEXT_SERIES_LINKS,
  getBillContextSeriesLinks,
} from "@/data/bill-forecasts";

const REPO_ROOT = path.resolve(__dirname, "../../..");
const BILLS_DIR = path.join(REPO_ROOT, "bills");

const billSlugs = new Set(
  fs
    .readdirSync(BILLS_DIR)
    .filter((name) => name.endsWith(".json") && !name.endsWith(".mapped.json"))
    .flatMap((name) => {
      const artifact = JSON.parse(
        fs.readFileSync(path.join(BILLS_DIR, name), "utf8"),
      ) as { bill?: { slug?: string } };
      return [name.replace(/\.json$/, ""), artifact.bill?.slug].filter(
        (slug): slug is string => Boolean(slug),
      );
    }),
);

const docket = JSON.parse(
  fs.readFileSync(
    path.join(REPO_ROOT, "scripts", "docket_series.json"),
    "utf8",
  ),
) as {
  series: Array<{
    series: string;
    comment?: string;
    billSlugs?: string[];
    ledger?: { uuid: string; concept: string };
  }>;
};

describe("bill context-series links", () => {
  it("names real bill analyses and admitted docket concepts only", () => {
    for (const link of BILL_CONTEXT_SERIES_LINKS) {
      expect(billSlugs.has(link.billSlug), link.billSlug).toBe(true);
      const entry = docket.series.find(
        (row) => row.series === link.seriesConcept,
      );
      expect(entry, `${link.seriesConcept} is not an admitted series`)
        .toBeDefined();
      expect(entry?.ledger?.concept).toBe(link.seriesConcept);
      // Confident prefix (the resolver requires ≥3 dotted segments).
      expect(
        link.seriesConcept.split(".").filter(Boolean).length,
      ).toBeGreaterThanOrEqual(3);
    }
  });

  it("carries the scope boundary on every link, not just in comments", () => {
    for (const link of BILL_CONTEXT_SERIES_LINKS) {
      expect(link.scopeNote.length).toBeGreaterThan(80);
      expect(link.scopeNote.toLowerCase()).toContain("not ");
      expect(link.scopeNote.toLowerCase()).toMatch(/attribut(?:ed|able)/);
    }
    const bySlug = new Map(
      BILL_CONTEXT_SERIES_LINKS.map((l) => [l.seriesConcept, l]),
    );
    // The Wave A boundaries reviews flagged as load-bearing — each must
    // survive verbatim in the canonical note:
    const cdfi = bySlug.get(
      "usaspending.cdfi.assistance_transaction_obligations",
    )?.scopeNote;
    expect(cdfi).toContain("downstream outcomes");
    expect(cdfi).toContain("amended section 113");
    const hidta = bySlug.get(
      "usaspending.ondcp.hidta_al95001_obligations",
    )?.scopeNote;
    expect(hidta).toContain("707(s)");
    expect(hidta).toContain("authorization");
    const ntia = bySlug.get(
      "usaspending.ntia.broadband_al11038_obligations",
    )?.scopeNote;
    expect(ntia).toContain("013-0565");
    expect(ntia).toContain("NIST");
    expect(ntia).toContain("caused or authorized");
    const usfs = bySlug.get(
      "usaspending.usfs.minnesota_place_of_performance_obligations",
    )?.scopeNote;
    expect(usfs).toContain("not Superior National Forest");
    expect(usfs).toContain("covered lands");
    const childCare = bySlug.get(
      "bls.qcew.child_day_care_services.annual_avg_employment",
    )?.scopeNote;
    expect(childCare).toContain("rural-county employment");
    expect(childCare).toContain("all-ownership coverage");
    expect(childCare).toContain("self-employment");
    expect(childCare).toContain("slots/affordability/capacity");
    expect(childCare).toContain("attributable to the bill");
    const flare = bySlug.get("eia.ng.vented_flared.us.annual")?.scopeNote;
    expect(flare).toContain("outcome and timing-tracking context only");
    expect(flare).toContain("no annual value or change is attributed");
    expect(flare).toContain("FLARE Act");
  });

  it("stays in lockstep with the bill-context docket admissions", () => {
    // Structured marker, not free text: every docket entry declaring
    // billSlugs must have exactly one page link per declared bill, and
    // every link must trace back to a declaring entry — an admission
    // without its page linkage (the round-1 gap) fails here.
    const declaring = docket.series.filter(
      (row) => (row.billSlugs ?? []).length > 0,
    );
    const admittedPairs = declaring
      .flatMap((row) =>
        (row.billSlugs ?? []).map((slug) => `${slug}::${row.series}`),
      )
      .sort();
    const linkedPairs = BILL_CONTEXT_SERIES_LINKS.map(
      (l) => `${l.billSlug}::${l.seriesConcept}`,
    ).sort();
    expect(linkedPairs).toEqual(admittedPairs);
    expect(BILL_CONTEXT_SERIES_LINKS.length).toBe(
      new Set(BILL_CONTEXT_SERIES_LINKS.map((l) => l.seriesConcept)).size,
    );
  });

  it("keeps docket comments and page scope notes in lockstep", () => {
    for (const link of BILL_CONTEXT_SERIES_LINKS) {
      const entry = docket.series.find(
        (row) => row.series === link.seriesConcept,
      );
      const legacyWaveAPrefixedNote =
        `Context series for the ${link.billSlug} bill page ` +
        `(thesis#159 Wave A). ${link.scopeNote}`;
      expect([link.scopeNote, legacyWaveAPrefixedNote]).toContain(
        entry?.comment,
      );
    }
    const itaLink = BILL_CONTEXT_SERIES_LINKS.find(
      (link) => link.seriesConcept === "bea.ita.personal_transfer_payments",
    );
    const itaEntry = docket.series.find(
      (row) => row.series === itaLink?.seriesConcept,
    );
    expect(itaEntry?.comment).toBe(itaLink?.scopeNote);
    const qcewLink = BILL_CONTEXT_SERIES_LINKS.find(
      (link) =>
        link.seriesConcept ===
        "bls.qcew.child_day_care_services.annual_avg_employment",
    );
    const qcewEntry = docket.series.find(
      (row) => row.series === qcewLink?.seriesConcept,
    );
    expect(qcewEntry?.comment).toBe(qcewLink?.scopeNote);
  });

  it("filters by bill slug", () => {
    const links = getBillContextSeriesLinks("cdfi-fund-s2718-119");
    expect(links).toHaveLength(1);
    expect(links[0].seriesConcept).toBe(
      "usaspending.cdfi.assistance_transaction_obligations",
    );
    expect(getBillContextSeriesLinks("no-such-bill")).toHaveLength(0);
    expect(getBillContextSeriesLinks("remit-act-hr5595-119")).toHaveLength(1);
    expect(getBillContextSeriesLinks("stress-119hr5595ih")).toHaveLength(0);
    const flareLinks = getBillContextSeriesLinks("flare-act-s1188-119");
    expect(flareLinks).toHaveLength(1);
    expect(flareLinks[0]).toMatchObject({
      seriesConcept: "eia.ng.vented_flared.us.annual",
      label: "U.S. natural gas vented and flared (2025 annual value)",
      pendingForecastLane: "ticketed-attested",
    });
  });
});

import { loadBills } from "@/data/bills";
import {
  BILL_FORECAST_LINKS,
  PENDING_CONDITIONALS,
} from "@/data/bill-forecasts";

describe("bill link integrity", () => {
  // The 8/12 BEA ITA link pointed at the stress-corpus slug
  // (stress-119hr5595ih) instead of the live page slug, so the REMIT
  // card rendered nowhere. Every link surface must name a real bill.
  const known = new Set(loadBills().map((bill) => bill.slug));
  it("every context-series link names a live bill page", () => {
    for (const link of BILL_CONTEXT_SERIES_LINKS) {
      expect(known.has(link.billSlug), link.billSlug).toBe(true);
    }
  });
  it("every forecast link and pending conditional names a live bill page", () => {
    for (const link of BILL_FORECAST_LINKS) {
      expect(known.has(link.billSlug), link.billSlug).toBe(true);
    }
    for (const pending of PENDING_CONDITIONALS) {
      expect(known.has(pending.billSlug), pending.billSlug).toBe(true);
    }
  });

  it("retains the terminated CRP history beside the fresh recovered pair", () => {
    const crp = PENDING_CONDITIONALS.filter(
      (pending) => pending.billSlug === "farm-bill-2-0",
    );
    expect(crp.map((pending) => pending.status)).toEqual(["refused"]);
    expect(crp[0].note).toContain(
      "A fresh pair may be registered if the source recovers.",
    );
    expect(BILL_FORECAST_LINKS).toContainEqual({
      billSlug: "farm-bill-2-0",
      metricLabel: "CRP enrolled acres (Sep 2027)",
      groupSlug: "crp-enrolled-acres-sep2027-ceiling-27m",
    });
  });
});
