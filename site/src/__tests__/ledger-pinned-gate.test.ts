import { createHash } from "node:crypto";
import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  LEDGER_AVAILABILITY,
  type LedgerAvailabilityRow,
} from "@/data/ledger-availability.generated";
import {
  currentLedgerView,
  expectedAssertionVersionId,
} from "@/data/ledger-current-view";
import {
  POLICYENGINE_LEDGER_PIN,
  fetchPinnedPolicyEngineLedgerBytes,
  getObservationForId,
  isObservationRecordedLedgerEntry,
  loadPolicyEngineLedger,
  resetPolicyEngineLedgerCache,
} from "@/data/thesis-log";

// The build grades on what the pinned fetch path returns, so that path itself
// must re-run the append gate's assertion-version checks and give a
// pre-versioning row the content address its correction names. These cases
// serve the pinned bytes plus one appended row through loadPolicyEngineLedger,
// with the pin and the availability index extended to match, as
// scripts/pin_ledger.py would extend them.
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
  // A copy the tests can extend in place; thesis-log reads this array.
  return {
    ...original,
    LEDGER_AVAILABILITY: [...original.LEDGER_AVAILABILITY],
  };
});

type Row = Record<string, unknown>;

// The mocked module's copy, which these tests extend and restore.
const availability = LEDGER_AVAILABILITY as LedgerAvailabilityRow[];

const sha256 = (text: string | Buffer) =>
  createHash("sha256").update(text).digest("hex");

describe("the pinned fetch path", () => {
  let pinnedBytes: Buffer;
  let pinnedRows: Row[];
  let pinnedAvailability: number;
  const realFetch = globalThis.fetch;

  beforeAll(async () => {
    pinnedBytes = await fetchPinnedPolicyEngineLedgerBytes(
      POLICYENGINE_LEDGER_PIN,
    );
    pinnedRows = pinnedBytes
      .toString("utf-8")
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => JSON.parse(line) as Row);
    pinnedAvailability = availability.length;
    expect(pinnedAvailability).toBe(pinnedRows.length);
  });

  afterEach(() => {
    SERVED.jsonl = null;
    availability.length = pinnedAvailability;
    vi.unstubAllGlobals();
    resetPolicyEngineLedgerCache();
  });

  afterAll(() => {
    resetPolicyEngineLedgerCache();
  });

  // Serve the pinned rows plus `row`, accepted after every pinned row.
  function serveWith(row: Row) {
    const line = JSON.stringify(row);
    const base = pinnedBytes.toString("utf-8");
    SERVED.jsonl = Buffer.from(
      `${base}${base.endsWith("\n") ? "" : "\n"}${line}\n`,
      "utf-8",
    );
    const last = availability[pinnedAvailability - 1];
    const appended: LedgerAvailabilityRow = {
      ...last,
      sourceRecordId: row.source_record_id as string,
      acceptedSequence: pinnedAvailability,
      acceptedAtUtc: new Date(
        Date.parse(last.acceptedAtUtc) + 60_000,
      ).toISOString(),
      acceptedCommit: "f".repeat(40),
      lineSha256: sha256(line),
      custody: "append_derived",
      witnessedInReleaseIndex: null,
      witnessedInReleaseFreetsaGenTimeUtc: null,
      witnessedInReleaseDigicertGenTimeUtc: null,
    };
    availability.push(appended);
    const served = SERVED.jsonl;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/ledger/official_observations.jsonl")) {
        return new Response(new Uint8Array(served));
      }
      return realFetch(input);
    });
    resetPolicyEngineLedgerCache();
  }

  function correctionOf(original: Row, changes: Row, supersedes: string): Row {
    const fix: Row = { ...structuredClone(original), ...changes };
    delete fix.assertionVersion;
    fix.assertionVersion = { id: expectedAssertionVersionId(fix), supersedes };
    return fix;
  }

  it("addresses a pre-versioning row its correction names, so it stops grading", async () => {
    const counts = new Map<unknown, number>();
    for (const row of pinnedRows) {
      counts.set(
        row.source_record_id,
        (counts.get(row.source_record_id) ?? 0) + 1,
      );
    }
    const legacy = pinnedRows.find(
      (row) => !row.assertionVersion && counts.get(row.source_record_id) === 1,
    )!;
    const address = expectedAssertionVersionId(legacy);
    serveWith(
      correctionOf(legacy, { value: (legacy.value as number) + 1 }, address),
    );

    const ledger = await loadPolicyEngineLedger();
    const rows = ledger
      .filter(isObservationRecordedLedgerEntry)
      .filter((entry) => entry.dataPointId === legacy.source_record_id);
    expect(rows).toHaveLength(2);
    const [original, correction] = rows;
    expect(original.supersededContentAddress).toBe(address);
    expect(correction.acceptedSequence).toBe(pinnedAvailability);
    const view = currentLedgerView(ledger);
    expect(view).not.toContain(original);
    expect(view).toContain(correction);
    expect(getObservationForId(original.observationId, ledger)).toBe(
      correction,
    );
  });

  it("refuses a row whose version id does not match its content", async () => {
    const versioned = pinnedRows.findLast(
      (row) =>
        (row.assertionVersion as Row | undefined)?.id &&
        pinnedRows.filter(
          (other) => other.source_record_id === row.source_record_id,
        ).length === 1,
    )!;
    const fix = correctionOf(
      versioned,
      { value: (versioned.value as number) + 1 },
      (versioned.assertionVersion as Row).id as string,
    );
    (fix.assertionVersion as Row).id = `av2:${"0".repeat(64)}`;
    serveWith(fix);
    await expect(loadPolicyEngineLedger()).rejects.toThrow(
      /does not match its content/,
    );
  });

  it("refuses a row that repeats its record without superseding it", async () => {
    const versioned = pinnedRows.findLast(
      (row) => (row.assertionVersion as Row | undefined)?.id,
    )!;
    const duplicate: Row = { ...structuredClone(versioned), value: 0 };
    delete duplicate.assertionVersion;
    duplicate.assertionVersion = {
      id: expectedAssertionVersionId(duplicate),
      supersedes: null,
    };
    serveWith(duplicate);
    await expect(loadPolicyEngineLedger()).rejects.toThrow(
      /without superseding/,
    );
  });
});
