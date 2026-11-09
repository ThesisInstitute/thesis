import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  AssertionVersionError,
  assertAppendGateAssertionVersions,
  effectiveAssertionId,
} from "@/data/ledger-current-view";
import { foldLedgerRestatements } from "@/data/ledger-restatements";
import { LedgerUnitError } from "@/data/ledger-units";
import { mapPolicyEngineLedgerRows } from "@/data/thesis-log";

// The resolver's restatement mode (scripts/resolve_pending.py
// --restate-base-units) checks the rows it writes with a Python port of this
// reader before it proposes them. The fixture holds real Chronicle rows, the
// rows the resolver's writer restates them with, copies with one thing
// changed, and what the port and Chronicle's append gate decided on each
// (scripts/generate_ledger_restatement_fixture.py). The reader must refuse
// exactly what the port refuses, and the writer's rows must leave every entry
// where it was.

type Verdict = { restates: string[] } | { refuses: string };

interface FixtureCase {
  name: string;
  lines: number[];
  port: Verdict;
  gate: "accept" | "refuse";
}

interface Fixture {
  schemaVersion: string;
  sample: number[];
  writer: number[];
  lines: string[];
  cases: FixtureCase[];
}

const fixture = JSON.parse(
  readFileSync(join(__dirname, "fixtures/ledger-restatements.json"), "utf8"),
) as Fixture;

const linesOf = (refs: readonly number[]) =>
  refs.map((index) => fixture.lines[index]);

// The site's reader as the pinned build runs it, on lines exactly as fetched.
function read(lines: readonly string[]) {
  const rows = lines.map((line) => JSON.parse(line) as unknown);
  return foldLedgerRestatements(mapPolicyEngineLedgerRows(rows), rows, lines);
}

// Why a reader refused, so the site and the port must refuse for one reason,
// not merely both throw. The port prints Python reprs where the site prints
// JSON, so each pattern accepts either quoting.
const NUMBER = String.raw`-?[\d.e+-]+`;
const REFUSAL_KINDS: ReadonlyArray<readonly [string, RegExp]> = [
  [
    "relation",
    /assertionVersion\.relation .+ (?:is not one the site reads|which the site does not read)$/,
  ],
  ["supersedes not a string", /assertionVersion\.supersedes .+, not a string\b/],
  ["no earlier row", /^line \d+ restates .+, which no earlier row holds$/],
  ["unscaled row", /^restatement of .+ names a row in .+, which holds no scale$/],
  ["restated unit", /^restatement of .+ stores .+, not the base unit of .+$/],
  [
    "restated value",
    new RegExp(String.raw`^restatement of .+ stores ${NUMBER}, not ${NUMBER}$`),
  ],
  ["restated pair", /^restatement of .+ records .+ but the row says .+$/],
  ["archive", /^restatement of .+ does not archive the exact line it restates$/],
  ["content", /^restatement of .+ changes more than the value and unit$/],
  ["pair not a number", /^\S+ records .+, which is not a number in a scaled unit$/],
  ["pair unit", /^\S+ records .+ but stores ["'][^"']*["']$/],
  ["pair value", new RegExp(String.raw`^\S+ records ${NUMBER} .+ but stores ${NUMBER}$`)],
];

// Kinds whose messages name no row on the site's side: those checks read a
// row's assertion version, not the row. Every other refusal names one.
const UNNAMED_KINDS: ReadonlySet<string> = new Set([
  "relation",
  "supersedes not a string",
]);

// The site refuses a malformed supersedes where it reads assertion versions,
// before the restatement checks, so with that module's error.
const errorOf = (kind: string) =>
  kind === "supersedes not a string" ? AssertionVersionError : LedgerUnitError;

function refusalKind(message: string): string {
  const kinds = REFUSAL_KINDS.filter(([, pattern]) => pattern.test(message));
  if (kinds.length !== 1) {
    throw new Error(`${kinds.length} refusal kinds match ${JSON.stringify(message)}`);
  }
  return kinds[0][0];
}

// The row a refusal names: its line, or its record id.
function subjectOf(message: string): string | null {
  const match =
    /^line (\d+) /.exec(message) ??
    /^restatement of (\S+) /.exec(message) ??
    /^(\S+) records /.exec(message);
  return match ? match[1] : null;
}

function caseNamed(name: string): FixtureCase {
  const found = fixture.cases.find((item) => item.name === name);
  if (!found) throw new Error(`fixture has no case ${name}`);
  return found;
}

describe("the restatement fixture", () => {
  it("is the version this reader replays", () => {
    expect(fixture.schemaVersion).toBe("thesis_ledger_restatement_fixture_v1");
    expect(fixture.writer.length).toBeGreaterThan(10);
    // Every case the port refuses, and every one it accepts, is covered.
    const refused = fixture.cases.filter((item) => "refuses" in item.port);
    expect(refused.length).toBeGreaterThan(20);
    expect(fixture.cases.length - refused.length).toBeGreaterThan(5);
  });

  it.each(fixture.cases.map((item) => [item.name, item] as const))(
    "reads %s as the resolver's port does",
    (_name, item) => {
      const lines = linesOf(item.lines);
      if ("refuses" in item.port) {
        let thrown: unknown;
        try {
          read(lines);
        } catch (error) {
          thrown = error;
        }
        const kind = refusalKind(item.port.refuses);
        expect(thrown).toBeInstanceOf(errorOf(kind));
        const message = (thrown as Error).message;
        expect(refusalKind(message)).toBe(kind);
        // Both refuse the same row. The kind decides whether a message must
        // name one, so a message that lost its row fails rather than skips.
        if (!UNNAMED_KINDS.has(kind)) {
          expect(subjectOf(message), message).not.toBeNull();
          expect(subjectOf(message)).toBe(subjectOf(item.port.refuses));
        }
        return;
      }
      const { restatements } = read(lines);
      expect(restatements.map((row) => row.supersedes)).toEqual(
        item.port.restates,
      );
    },
  );

  it("names every kind of refusal at least once", () => {
    const seen = new Set(
      fixture.cases.flatMap((item) =>
        "refuses" in item.port ? [refusalKind(item.port.refuses)] : [],
      ),
    );
    expect([...seen].sort()).toEqual(REFUSAL_KINDS.map(([kind]) => kind).sort());
  });

  it("holds each ledger the gate accepts to the site's assertion versions", () => {
    const accepted = fixture.cases.filter((item) => item.gate === "accept");
    expect(accepted.length).toBeGreaterThan(10);
    for (const item of accepted) {
      const rows = linesOf(item.lines).map((line) => JSON.parse(line));
      expect(() => assertAppendGateAssertionVersions(rows), item.name).not.toThrow();
    }
  });

  it("leaves every entry in place when the writer's rows land", () => {
    const sample = read(linesOf(fixture.sample));
    const restated = read(linesOf([...fixture.sample, ...fixture.writer]));
    expect(sample.restatements).toEqual([]);
    expect(JSON.stringify(restated.entries)).toBe(JSON.stringify(sample.entries));
    expect(restated.restatements).toHaveLength(fixture.writer.length);
    const priorIds = new Set(
      linesOf(fixture.sample).map((line) => effectiveAssertionId(JSON.parse(line))),
    );
    for (const [index, restatement] of restated.restatements.entries()) {
      const row = JSON.parse(fixture.lines[fixture.writer[index]]);
      expect(priorIds.has(restatement.supersedes)).toBe(true);
      expect(restatement.value).toBe(row.value);
      expect(restatement.unit).toBe(row.measure.unit);
    }
  });

  it("grades a correction of a restatement against the row it restates", () => {
    const item = caseNamed("a correction follows a restatement");
    const lines = linesOf(item.lines);
    const correction = JSON.parse(lines[lines.length - 1]);
    const restatement = lines
      .map((line) => JSON.parse(line))
      .find(
        (row) =>
          row.assertionVersion?.id === correction.assertionVersion.supersedes,
      );
    const { entries } = read(lines);
    const entry = entries[entries.length - 1];
    expect(entry.dataPointId).toBe(correction.source_record_id);
    expect(entry.gradedSupersedes).toBe(restatement.assertionVersion.supersedes);
    // The entry reads the recorded pair, as if the row had kept its scale.
    expect(entry.value).toBe(correction.source.recorded_value);
    expect(entry.unit).toBe(correction.source.recorded_unit);
    expect(entry.ledgerValue).toBe(correction.value);
  });

  it("reads a restatement without its relation as a correction in the same quantity", () => {
    const item = caseNamed("relation removed");
    const lines = linesOf(item.lines);
    const { entries } = read(lines);
    const bare = lines
      .map((line) => JSON.parse(line))
      .find(
        (row) =>
          row.assertionVersion?.supersedes !== undefined &&
          row.assertionVersion?.relation === undefined &&
          row.source?.recorded_unit !== undefined,
      );
    const prior = linesOf(fixture.sample)
      .map((line) => JSON.parse(line))
      .find(
        (row) => effectiveAssertionId(row) === bare.assertionVersion.supersedes,
      );
    const entry = entries.find(
      (candidate) => candidate.assertionVersion?.id === bare.assertionVersion.id,
    );
    expect(entry?.value).toBe(prior.value);
    expect(entry?.unit).toBe(prior.measure.unit);
  });
});
