import type { Unit } from "./units";

// What each scaled unit measures, and how many of that base unit one of it
// holds. Chronicle stores plain numbers, so a current fact's measure.unit holds
// no scale word, while a registered forecast contract keeps the unit it
// registered. The site converts only to check a row, never to grade one.
//
// scripts/ledger_units.py holds the same table for the resolver.
// scripts/generate_ledger_units_fixture.py records what that copy returns, and
// site/src/__tests__/ledger-base-units.test.ts holds this one to the record.
export const LEDGER_UNIT_SCALES = {
  thousands: { base: "count", power: 3 },
  millions: { base: "count", power: 6 },
  usd_millions: { base: "usd", power: 6 },
  usd_billions: { base: "usd", power: 9 },
  // The spelling the DoD USAspending registrations carry (units.ts).
  "billions USD": { base: "usd", power: 9 },
  gbp_billions: { base: "gbp", power: 9 },
  million_cubic_feet: { base: "cubic_feet", power: 6 },
} as const satisfies Record<string, { base: Unit; power: number }>;

export type ScaledUnit = keyof typeof LEDGER_UNIT_SCALES;

export class LedgerUnitError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LedgerUnitError";
  }
}

export function isScaledUnit(unit: unknown): unit is ScaledUnit {
  return (
    typeof unit === "string" &&
    Object.prototype.hasOwnProperty.call(LEDGER_UNIT_SCALES, unit)
  );
}

// The shortest decimal that reads back as this double, as digits × 10^exponent
// with no trailing zero in the digits. Python's repr prints the same digits.
function shortestDecimal(value: number): { digits: string; exponent: number } {
  const [mantissa, exponent] = Math.abs(value).toExponential().split("e");
  const digits = mantissa.replace(".", "");
  return { digits, exponent: Number(exponent) - (digits.length - 1) };
}

/**
 * The double whose shortest decimal is this value's, moved `power` places.
 * Refuses a result that would store a different decimal, and an integer past
 * 2**53 - 1, which a JSON reader built on doubles cannot read back. Multiplying
 * would not do: 8.2 * 1e6 gives 8199999.999999999.
 */
export function shiftDecimal(value: number, power: number): number {
  if (!Number.isFinite(value)) {
    throw new LedgerUnitError(`${String(value)} has no decimal value to shift`);
  }
  if (value === 0) return 0;
  const { digits, exponent } = shortestDecimal(value);
  const sign = value < 0 ? "-" : "";
  const shifted = Number(`${sign}${digits}e${exponent + power}`);
  const stored = Number.isFinite(shifted) ? shortestDecimal(shifted) : null;
  if (
    stored?.digits !== digits ||
    stored.exponent !== exponent + power ||
    (Number.isInteger(shifted) && !Number.isSafeInteger(shifted))
  ) {
    throw new LedgerUnitError(
      `${String(value)} moved ${power} places does not store exactly`,
    );
  }
  return shifted;
}

/** This value in its unit's base unit, exactly, or a refusal. */
export function toBase(value: number, unit: ScaledUnit): number {
  return shiftDecimal(value, LEDGER_UNIT_SCALES[unit].power);
}
