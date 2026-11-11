import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { UNITS } from "@/data/units";

// The Unit list must cover every unit that appears in the generated
// registration surface: a registered target with an uncovered unit turns
// main build-red only AFTER its registration lands (2026-08-03, twice —
// first the adapter union, then unit "billions USD"). This test moves the
// failure to the change that introduces the unit. The ledger-fact check in
// thesis-log.ts reads the same list (units.ts), so this covers it too.
describe("generated ledger targets use covered units", () => {
  it("every generated unit is a member of UNITS", () => {
    const covered = new Set<string>(UNITS);

    const generated = readFileSync(
      join(__dirname, "../data/ledger-targets.generated.ts"),
      "utf8",
    );
    const used = new Set(
      [...generated.matchAll(/unit: "([^"]+)"/g)].map((m) => m[1]),
    );
    expect(used.size).toBeGreaterThan(0);
    for (const unit of used) {
      expect(covered.has(unit), `unit "${unit}" missing from UNITS`).toBe(
        true,
      );
    }
  });
});
