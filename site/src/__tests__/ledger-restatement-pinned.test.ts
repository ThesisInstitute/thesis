import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import {
  LEDGER_AVAILABILITY,
  type LedgerAvailabilityRow,
} from "@/data/ledger-availability.generated";
import { effectiveAssertionId } from "@/data/ledger-current-view";
import { isUnitRestatement } from "@/data/ledger-restatements";
import { isScaledUnit } from "@/data/ledger-units";
import { getPublishedForecasts } from "@/lib/forecast-publication";
import {
  buildPolicyEngineLedgerExport,
  fetchPinnedPolicyEngineLedgerBytes,
  isObservationRecordedLedgerEntry,
  loadPolicyEngineLedger,
  loadPolicyEngineLedgerRestatements,
  POLICYENGINE_LEDGER_PIN,
  resetPolicyEngineLedgerCache,
  scoreResolvedForecasts,
  withResolvedOutcomes,
} from "@/data/thesis-log";
import { GET as getLedgerJson } from "../app/forecasts/ledger.json/route";
import {
  currentScaledLines,
  restatementOf,
  sha256,
  type Json,
} from "./ledger-restatement-helpers";

// Restating the real ledger must leave every graded input in place. Before the
// migration, these cases append each current scaled row's restatement to the
// pinned rows; once the pin holds the restatements, they take them back out.
// Either way the two ledgers are served through the pinned fetch path, with the
// pin and the availability index extended as scripts/pin_ledger.py would.
const SERVED = vi.hoisted(() => ({ jsonl: null as Buffer | null }));

vi.mock("@/data/ledger-pin.json", async (importOriginal) => {
  const { createHash: hash } = await import("node:crypto");
  const original = (await importOriginal()) as {
    default?: Record<string, unknown>;
  };
  const pin = (original.default ?? original) as Record<string, unknown>;
  const lines = (bytes: Buffer) =>
    bytes
      .toString("utf-8")
      .split("\n")
      .filter((line) => line.trim()).length;
  return {
    default: {
      ...pin,
      get jsonlSha256() {
        return SERVED.jsonl
          ? hash("sha256").update(SERVED.jsonl).digest("hex")
          : pin.jsonlSha256;
      },
      get jsonlBytes() {
        return SERVED.jsonl ? SERVED.jsonl.length : pin.jsonlBytes;
      },
      get lineCount() {
        return SERVED.jsonl ? lines(SERVED.jsonl) : pin.lineCount;
      },
    },
  };
});

vi.mock("@/data/ledger-availability.generated", async (importOriginal) => {
  const original =
    await importOriginal<
      typeof import("@/data/ledger-availability.generated")
    >();
  // A copy the tests can replace in place; thesis-log reads this array.
  return {
    ...original,
    LEDGER_AVAILABILITY: [...original.LEDGER_AVAILABILITY],
  };
});

const availability = LEDGER_AVAILABILITY as LedgerAvailabilityRow[];

describe("restating the pinned ledger", () => {
  let pinnedRows: LedgerAvailabilityRow[];
  let pinnedLines: string[];
  let plainLines: string[];
  let restatedLines: string[];
  const realFetch = globalThis.fetch;

  beforeAll(async () => {
    pinnedRows = [...availability];
    pinnedLines = (
      await fetchPinnedPolicyEngineLedgerBytes(POLICYENGINE_LEDGER_PIN)
    )
      .toString("utf-8")
      .split("\n")
      .filter((line) => line.trim());
    plainLines = pinnedLines.filter(
      (line) => !isUnitRestatement(JSON.parse(line)),
    );
    const added = currentScaledLines(plainLines).map((line) =>
      JSON.stringify(restatementOf(line)),
    );
    restatedLines =
      plainLines.length < pinnedLines.length
        ? pinnedLines
        : [...plainLines, ...added];
  });

  afterEach(() => {
    SERVED.jsonl = null;
    availability.length = 0;
    availability.push(...pinnedRows);
    vi.unstubAllGlobals();
    resetPolicyEngineLedgerCache();
  });

  // Serves these lines with the acceptance each pinned line already has, and
  // new lines accepted after every pinned one.
  function serve(lines: string[]) {
    const held = new Map(pinnedRows.map((row) => [row.lineSha256, row]));
    const last = pinnedRows[pinnedRows.length - 1];
    availability.length = 0;
    lines.forEach((line, index) => {
      const lineSha256 = sha256(line);
      availability.push(
        held.get(lineSha256) ?? {
          ...last,
          sourceRecordId: (JSON.parse(line) as Json).source_record_id as string,
          acceptedSequence: index,
          acceptedAtUtc: new Date(
            Date.parse(last.acceptedAtUtc) + 60_000,
          ).toISOString(),
          acceptedCommit: "f".repeat(40),
          lineSha256,
          custody: "append_derived",
          witnessedInReleaseIndex: null,
          witnessedInReleaseFreetsaGenTimeUtc: null,
          witnessedInReleaseDigicertGenTimeUtc: null,
        },
      );
    });
    const served = Buffer.from(`${lines.join("\n")}\n`, "utf-8");
    SERVED.jsonl = served;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) =>
      String(input).endsWith("/ledger/official_observations.jsonl")
        ? new Response(new Uint8Array(served))
        : realFetch(input),
    );
    resetPolicyEngineLedgerCache();
  }

  it("restates rows in every scaled unit the ledger holds", () => {
    expect(restatedLines.length).toBeGreaterThan(plainLines.length);
    const restatements = restatedLines.filter((line) =>
      isUnitRestatement(JSON.parse(line)),
    );
    expect(restatements.length).toBe(restatedLines.length - plainLines.length);
    const units = new Set(
      restatements.map(
        (line) =>
          ((JSON.parse(line) as Json).source as Json).recorded_unit as string,
      ),
    );
    expect([...units].every(isScaledUnit)).toBe(true);
    expect(units.size).toBeGreaterThan(3);
  });

  it("keeps every entry and every score, byte for byte", async () => {
    serve(plainLines);
    const plain = await loadPolicyEngineLedger();
    const plainScores = scoreResolvedForecasts(
      withResolvedOutcomes(getPublishedForecasts(), plain),
      plain,
    );
    const plainEntries = JSON.stringify(plain);
    const plainScoresJson = JSON.stringify(plainScores);
    expect(plainScores.length).toBeGreaterThan(0);

    serve(restatedLines);
    const restated = await loadPolicyEngineLedger();
    expect(JSON.stringify(restated)).toBe(plainEntries);
    expect(
      JSON.stringify(
        scoreResolvedForecasts(
          withResolvedOutcomes(getPublishedForecasts(), restated),
          restated,
        ),
      ),
    ).toBe(plainScoresJson);
  });

  it("publishes each restatement apart from the entries", async () => {
    serve(restatedLines);
    const entries = await loadPolicyEngineLedger();
    const restatements = await loadPolicyEngineLedgerRestatements();
    const expected = restatedLines.filter((line) =>
      isUnitRestatement(JSON.parse(line)),
    );
    expect(restatements.map((row) => row.assertionId)).toEqual(
      expected.map((line) => effectiveAssertionId(JSON.parse(line))),
    );
    for (const restatement of restatements) {
      expect(isScaledUnit(restatement.unit)).toBe(false);
      expect(restatement.acceptedSequence).toEqual(expect.any(Number));
    }
    const published = (await (await getLedgerJson()).json()) as ReturnType<
      typeof buildPolicyEngineLedgerExport
    >;
    expect(published.restatements).toEqual(restatements);
    expect(published.counts.observations).toBe(
      entries.filter(isObservationRecordedLedgerEntry).length,
    );
    expect(published.source.pin?.lineCount).toBe(restatedLines.length);
  });

  it("publishes no restatements on a ledger that holds none", async () => {
    serve(plainLines);
    const published = (await (await getLedgerJson()).json()) as Json;
    expect(published).not.toHaveProperty("restatements");
  });

  it("refuses a restatement with no acceptance record", async () => {
    serve(restatedLines);
    const index = restatedLines.findIndex((line) =>
      isUnitRestatement(JSON.parse(line)),
    );
    availability[index] = {
      ...availability[index],
      lineSha256: "0".repeat(64),
    };
    resetPolicyEngineLedgerCache();
    await expect(loadPolicyEngineLedger()).rejects.toThrow(
      /does not match its availability record/,
    );
  });
});
