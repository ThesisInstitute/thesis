import { createHash } from "node:crypto";
import { beforeAll, describe, expect, it } from "vitest";
import { FORECAST_CELLS, type ForecastCell } from "@/data/forecast-cells";
import { getLedgerTargetByDataPointId } from "@/data/ledger-targets";
import {
  POLICYENGINE_LEDGER_PIN,
  POLICYENGINE_LEDGER_SERIES_CATALOG_URL,
  buildResolvedPredictionLogEntries,
  getObservationForId,
  getResolvedObservationForForecast,
  isObservationRecordedLedgerEntry,
  loadPolicyEngineLedger,
  withResolvedOutcomes,
  type ObservationRecordedLedgerEntry,
  type PolicyEngineLedgerEntry,
} from "@/data/thesis-log";
import { ledgerHistoryAtCutoff } from "@/data/time-series-priors";

// Chronicle's journal is append-only. A correction appends a row that
// reuses its predecessor's source_record_id, so the two share an
// observationId, and names the version it replaces in
// assertionVersion.supersedes. receipt's check_rows accepts a repeated
// record only when the new row supersedes that record's active version,
// and accepts a supersedes only on a repeated record, so each record is
// one linear chain whose current row is its last.
//
// This mirrors those rules for rows that carry an explicit version id. A
// pre-versioning row is addressed by its recomputed av2 content address,
// which the site does not compute yet (thesis#309); a correction of one
// fails here instead of being guessed at.
interface CorrectionView {
  chains: Map<string, ObservationRecordedLedgerEntry[]>;
  current: ObservationRecordedLedgerEntry[];
  superseded: ObservationRecordedLedgerEntry[];
}

function correctionView(
  observations: ObservationRecordedLedgerEntry[],
): CorrectionView {
  const chains = new Map<string, ObservationRecordedLedgerEntry[]>();
  for (const entry of observations) {
    const supersedes = entry.assertionVersion?.supersedes ?? null;
    const chain = chains.get(entry.observationId);
    if (!chain) {
      if (supersedes !== null) {
        throw new Error(
          `${entry.observationId} supersedes ${supersedes} but has no ` +
            "earlier row",
        );
      }
      chains.set(entry.observationId, [entry]);
      continue;
    }
    const active = chain[chain.length - 1];
    if (!active.assertionVersion?.id) {
      throw new Error(
        `${entry.observationId} repeats a pre-versioning row, which is ` +
          "addressed by its av2 content address; grading it needs the " +
          "supersede-aware current view (thesis#309)",
      );
    }
    if (supersedes !== active.assertionVersion.id) {
      throw new Error(
        `${entry.observationId} repeats its record but supersedes ` +
          `${String(supersedes)}, not the active version ` +
          active.assertionVersion.id,
      );
    }
    chain.push(entry);
  }
  const isCurrent = (entry: ObservationRecordedLedgerEntry) =>
    chains.get(entry.observationId)!.at(-1) === entry;
  return {
    chains,
    current: observations.filter(isCurrent),
    superseded: observations.filter((entry) => !isCurrent(entry)),
  };
}

function instant(value: string | undefined): number {
  const parsed = Date.parse(value ?? "");
  if (!Number.isFinite(parsed)) {
    throw new Error(`unparseable ledger instant ${String(value)}`);
  }
  return parsed;
}

describe("Chronicle corrections on the pinned ledger", () => {
  let ledger: PolicyEngineLedgerEntry[] = [];
  let observations: ObservationRecordedLedgerEntry[] = [];
  let view: CorrectionView;
  let correctedChains: ObservationRecordedLedgerEntry[][] = [];
  let resolvedForecastCells: ForecastCell[] = [];

  beforeAll(async () => {
    ledger = await loadPolicyEngineLedger();
    observations = ledger.filter(isObservationRecordedLedgerEntry);
    view = correctionView(observations);
    correctedChains = [...view.chains.values()].filter(
      (chain) => chain.length > 1,
    );
    resolvedForecastCells = withResolvedOutcomes(FORECAST_CELLS, ledger);
  });

  it("keeps one current row per record, as receipt's current view does", () => {
    // The ledger is append-only, so a pin never loses its corrections; this
    // keeps the checks below from passing vacuously.
    expect(view.superseded.length).toBeGreaterThan(0);
    expect(new Set(view.current.map((entry) => entry.observationId)).size).toBe(
      view.current.length,
    );
    expect(view.current.length + view.superseded.length).toBe(
      observations.length,
    );

    // receipt's effective_current_rows drops every row whose version some
    // row supersedes. On a ledger that passes the chain rules, that is the
    // same set as the last row of each chain.
    const supersededIds = new Set(
      observations.flatMap((entry) =>
        entry.assertionVersion?.supersedes
          ? [entry.assertionVersion.supersedes]
          : [],
      ),
    );
    expect(
      observations.filter(
        (entry) =>
          !entry.assertionVersion ||
          !supersededIds.has(entry.assertionVersion.id),
      ),
    ).toEqual(view.current);
  });

  it("agrees with the current-view count Chronicle's pinned catalog records", async () => {
    // build_series_catalog.py counts receipt's effective_current_rows over
    // the same observation bytes, so this is a differential check against
    // Chronicle's own implementation.
    const pin = POLICYENGINE_LEDGER_PIN;
    expect(pin.catalogSha256).toMatch(/^[0-9a-f]{64}$/);
    const response = await fetch(POLICYENGINE_LEDGER_SERIES_CATALOG_URL);
    expect(response.ok).toBe(true);
    const raw = Buffer.from(await response.arrayBuffer());
    expect(createHash("sha256").update(raw).digest("hex")).toBe(
      pin.catalogSha256,
    );
    expect(raw.length).toBe(pin.catalogBytes);
    const catalog = JSON.parse(raw.toString("utf-8")) as {
      observations_sha256: string;
      observation_rows: number;
      current_assertion_rows: number;
    };

    expect(catalog.observations_sha256).toBe(pin.jsonlSha256);
    expect(catalog.observation_rows).toBe(observations.length);
    expect(catalog.current_assertion_rows).toBe(view.current.length);
  });

  it("grades a corrected record on its current row, never a superseded one", () => {
    const current = new Set(view.current);
    for (const forecast of resolvedForecastCells) {
      const observation = getResolvedObservationForForecast(forecast, ledger);
      if (!observation) continue;
      expect(
        current.has(observation),
        `${forecast.slug} grades a superseded row of ` +
          `${observation.observationId}; the first-print lookup needs the ` +
          "supersede-aware current view (thesis#309)",
      ).toBe(true);
    }
    for (const entry of buildResolvedPredictionLogEntries(
      resolvedForecastCells,
      ledger,
    )) {
      const observation = getObservationForId(entry.observationId, ledger);
      expect(observation && current.has(observation)).toBe(true);
    }
  });

  it("dates and admits a graded correction by its whole chain", () => {
    // The supersede-aware rules (thesis#309) bound a run by the earliest
    // print in a correction's chain and judge registration membership
    // (finding N5) on the chain's first acceptance. Today's lookups read the
    // graded row alone, so on the pinned ledger the two must coincide: the
    // graded row is the chain's earliest print, and no row of the chain was
    // already inside the ledger state its registration pinned.
    const chainsById = new Map(
      correctedChains.map((chain) => [chain[0].observationId, chain]),
    );
    let gradedCorrections = 0;
    for (const forecast of resolvedForecastCells) {
      const observation = getResolvedObservationForForecast(forecast, ledger);
      const chain = observation && chainsById.get(observation.observationId);
      if (!observation || !chain) continue;
      gradedCorrections += 1;

      expect(forecast.resolvedOutcome?.value).toBe(observation.value);
      const earliest = Math.min(
        ...chain.map((entry) => instant(entry.observedAt)),
      );
      expect(instant(observation.observedAt)).toBe(earliest);

      const target = getLedgerTargetByDataPointId(forecast.dataPointId ?? "");
      if (typeof target?.ledgerPinLineCount !== "number") continue;
      const pinLineCount = target.ledgerPinLineCount;
      for (const entry of chain) {
        expect(
          entry.acceptedSequence,
          `${forecast.slug}: ${entry.observationId} line ` +
            `${String(entry.acceptedSequence)} predates its registration's ` +
            `pinned ledger state (${pinLineCount} lines)`,
        ).toBeGreaterThanOrEqual(pinLineCount);
      }
    }
    expect(gradedCorrections).toBeGreaterThan(0);
  });

  it("keeps cutoff histories on the ledger's current view as of each cutoff", () => {
    // A correction must not rewrite a history cut before it was accepted,
    // and a row superseded by the cutoff must not stay in it. Check every
    // forecast whose history can reach a corrected record, at each
    // acceptance instant in the corrected chains and just before it.
    const chainRows = new Map(
      correctedChains.flatMap((chain) =>
        chain.map((entry, index) => [entry, { chain, index }] as const),
      ),
    );
    const cutoffs = [
      "2100-01-01T00:00:00.000Z",
      ...correctedChains.flatMap((chain) =>
        chain.flatMap((entry) => {
          const accepted = instant(entry.acceptedAtUtc);
          return [accepted - 1, accepted].map((time) =>
            new Date(time).toISOString(),
          );
        }),
      ),
    ];
    const reaching = FORECAST_CELLS.filter((forecast) =>
      ledgerHistoryAtCutoff(forecast, ledger, cutoffs[0]).some((entry) =>
        chainRows.has(entry),
      ),
    );
    expect(reaching.length).toBeGreaterThan(0);

    for (const forecast of reaching) {
      const reachable = new Set(
        ledgerHistoryAtCutoff(forecast, ledger, cutoffs[0]),
      );
      for (const cutoff of cutoffs) {
        const cutoffTime = instant(cutoff);
        const history = ledgerHistoryAtCutoff(forecast, ledger, cutoff);
        // The record's row as of the cutoff is its last row accepted by
        // then; when that row passes the history filters, it is the one kept.
        for (const chain of correctedChains) {
          if (!chain.some((entry) => reachable.has(entry))) continue;
          const asOf = chain
            .filter((entry) => instant(entry.acceptedAtUtc) <= cutoffTime)
            .at(-1);
          if (
            !asOf ||
            asOf.unit !== forecast.unit ||
            instant(asOf.observedAt) > cutoffTime
          ) {
            continue;
          }
          expect(history).toContain(asOf);
        }
        for (const entry of history) {
          const position = chainRows.get(entry);
          if (!position) continue;
          expect(instant(entry.acceptedAtUtc)).toBeLessThanOrEqual(cutoffTime);
          const supersededBy = position.chain
            .slice(position.index + 1)
            .find((later) => instant(later.acceptedAtUtc) <= cutoffTime);
          expect(
            supersededBy,
            `${forecast.slug} history at ${cutoff} keeps ` +
              `${entry.observationId} line ${String(entry.acceptedSequence)}, ` +
              `superseded by line ${String(supersededBy?.acceptedSequence)}`,
          ).toBeUndefined();
        }
      }
    }
  });
});
