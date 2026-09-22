import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  extractSections,
  fullSectionText,
  parseSectionNumbers,
  reviewedSections,
} from "@/lib/bill-text";

describe("parseSectionNumbers", () => {
  it("reads multi-section farm-bill headings", () => {
    expect(
      parseSectionNumbers(
        "1. §§2101, 2105, and 2401(1): Conservation Reserve Program scale",
        "Title II — Conservation",
      ),
    ).toEqual(["2101", "2105", "2401"]);
  });

  it("drops parenthesized subsection designators", () => {
    expect(
      parseSectionNumbers(
        "3. §2401(2): the literal FY2028 conservation-funding cliff",
        "Title II — Conservation",
      ),
    ).toEqual(["2401"]);
  });

  it("falls back to a plain Section title", () => {
    expect(
      parseSectionNumbers(
        "Earned income threshold for the refundable child tax credit",
        "Section 2",
      ),
    ).toEqual(["2"]);
  });
});

describe("extractSections", () => {
  const raw = [
    "SEC. 2101. CONSERVATION RESERVE.  1",
    "Body of section 2101.  2",
    "46 ",
    "RYA26731 1TW [file 1 of 2]  S.L.C. ",
    "SEC. 2102. NEXT SECTION.  3",
    "Body of 2102.  4",
  ].join("\n");

  it("slices from the section heading to the next section", () => {
    const slice = extractSections(raw, ["2101"]);
    expect(slice).toContain("CONSERVATION RESERVE");
    expect(slice).toContain("Body of section 2101.");
    expect(slice).not.toContain("NEXT SECTION");
  });

  it("strips page furniture and line-number gutters", () => {
    const slice = extractSections(raw, ["2101"]);
    expect(slice).not.toMatch(/S\.L\.C\./);
    expect(slice).not.toMatch(/ \d{1,2}$/m);
  });

  it("rejoins hyphenated line breaks with gutter numbers", () => {
    const hyphenated = [
      "SEC. 6206. RURAL WATER AND WASTEWATER CYBERSECU -5",
      "RITY CIRCUIT RIDER PROGRAM.  6",
      "Section 306(a) is amended by in -8",
      "serting after paragraph (22) the following:  9",
    ].join("\n");
    const slice = extractSections(hyphenated, ["6206"]);
    expect(slice).toContain("CYBERSECURITY CIRCUIT RIDER PROGRAM.");
    expect(slice).toContain("inserting after paragraph (22)");
    expect(slice).not.toMatch(/-\d/);
  });

  it("returns null rather than wrong text when nothing matches", () => {
    expect(extractSections(raw, ["9999"])).toBeNull();
  });

  it("preserves the historical S3596 text-format section parser", () => {
    const historical = [
      "SECTION 1. SHORT TITLE.",
      "This Act may be cited as the Stronger Start for Working Families Act.",
      "SEC. 2. EARNED INCOME THRESHOLD FOR REFUNDABLE CHILD TAX CREDIT.",
      "Section 24 is amended by striking ``$3,000'' and inserting ``$1''.",
    ].join("\n");
    const text = extractSections(historical, ["2"]);
    expect(text).toContain("EARNED INCOME THRESHOLD FOR REFUNDABLE CHILD TAX");
    expect(text).toContain("striking ``$3,000'' and inserting ``$1''");
    expect(text).not.toContain("SHORT TITLE");
  });
});

describe("reviewed sections for flattened source text", () => {
  const span = "2. Refundable credit Section 24 is amended by inserting $1.";
  const raw = Buffer.from(`Bill preamble. 1. Short title. ${span}`, "utf8");
  const sidecar = () => ({
    sourceTextSha256: createHash("sha256").update(raw).digest("hex"),
    sections: { "2": span },
  });

  it("returns the reviewed exact span without guessing flattened numeric markers", () => {
    expect(extractSections(raw.toString("utf8"), ["2"])).toBeNull();
    expect(reviewedSections(raw, ["2"], sidecar())).toBe(span);
  });

  it("rejects stale hashes and changed raw source bytes", () => {
    expect(reviewedSections(raw, ["2"], {
      ...sidecar(), sourceTextSha256: "0".repeat(64),
    })).toBeNull();
    expect(reviewedSections(Buffer.concat([raw, Buffer.from("\n")]), ["2"], sidecar()))
      .toBeNull();
  });

  it("rejects edited or invented section text even with the correct source hash", () => {
    for (const text of [span.replace("$1", "$100"), "Not in this bill.", ""]) {
      expect(reviewedSections(raw, ["2"], {
        ...sidecar(), sections: { "2": text },
      })).toBeNull();
    }
  });

  it("requires every requested section instead of returning a partial fallback", () => {
    expect(reviewedSections(raw, ["3"], sidecar())).toBeNull();
    expect(reviewedSections(raw, ["2", "3"], sidecar())).toBeNull();
    expect(reviewedSections(raw, [], sidecar())).toBeNull();
  });

  it("validates unselected spans and rejects malformed sidecars", () => {
    expect(reviewedSections(raw, ["2"], {
      ...sidecar(), sections: { "2": span, "3": "Not present." },
    })).toBeNull();
    for (const invalid of [null, [], {}, { ...sidecar(), sections: [] }, {
      ...sidecar(), unexpected: "unreviewed",
    }]) {
      expect(reviewedSections(raw, ["2"], invalid)).toBeNull();
    }
  });
});

describe("fullSectionText on the real artifacts", () => {
  it("finds the reviewed S3596 Section 2 span in the current XML-derived source", () => {
    const text = fullSectionText(
      "s3596-119",
      "Earned income threshold for refundable child tax credit",
      "Section 2",
    );
    expect(text).toContain("2. Earned income threshold for refundable child tax credit");
    expect(text).toMatch(/striking\s+\$3,000\s+and inserting\s+\$1/);
    expect(text).toContain("taxable years beginning after December 31, 2025.");
  });

  it("finds all three sections of the CRP provision", () => {
    const text = fullSectionText(
      "farm-bill-2-0",
      "1. §§2101, 2105, and 2401(1): Conservation Reserve Program scale, grazing infrastructure, and payments",
      "Title II — Conservation",
    );
    expect(text).toContain("SEC. 2101");
    expect(text).toContain("SEC. 2105");
    expect(text).toContain("SEC. 2401");
    expect(text).not.toMatch(/S\.L\.C\./);
  });

  it("reflows the §6206 text cleanly", () => {
    const text = fullSectionText(
      "farm-bill-2-0",
      "3. §6206: Rural Water and Wastewater Cybersecurity Circuit Rider Program",
      "Title VI — Rural Development",
    );
    expect(text).toContain("CYBERSECURITY CIRCUIT RIDER PROGRAM");
    expect(text).toContain("AUTHORIZATION OF APPROPRIATIONS");
    expect(text).toContain("inserting after paragraph (22)");
    // No gutter digits stuck to hyphenated words, no mid-word splits.
    expect(text).not.toMatch(/[a-z] -\d/);
    expect(text).not.toContain("CYBERSECU -");
  });
});
