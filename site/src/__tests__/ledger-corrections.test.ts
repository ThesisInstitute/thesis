import { createHash } from "node:crypto";
import { beforeAll, describe, expect, it } from "vitest";
import {
  FORECAST_CELLS,
  getForecastRunEntries,
  type ForecastCell,
} from "@/data/forecast-cells";
import { getLedgerTargetByDataPointId } from "@/data/ledger-targets";
import {
  assertAppendGateAssertionVersions,
  currentLedgerView,
  effectiveAssertionId,
  expectedAssertionVersionId,
  firstAcceptedSequence,
  firstObservedAt,
  observationAssertionId,
} from "@/data/ledger-current-view";
import {
  POLICYENGINE_LEDGER_PIN,
  POLICYENGINE_LEDGER_SERIES_CATALOG_URL,
  buildResolvedPredictionLogEntries,
  evaluateResolvedForecastRun,
  fetchPinnedPolicyEngineLedgerBytes,
  getObservationForId,
  getResolvedObservationForForecast,
  isObservationRecordedLedgerEntry,
  loadPolicyEngineLedger,
  mapPolicyEngineLedgerRows,
  withResolvedOutcomes,
  type ObservationRecordedLedgerEntry,
  type PolicyEngineLedgerEntry,
} from "@/data/thesis-log";
import {
  ledgerHistoryAtCutoff,
  registeredTargetSeriesIdentity,
} from "@/data/time-series-priors";

// Chronicle's journal is append-only. A correction appends a row that
// reuses its predecessor's source_record_id, so the two share an
// observationId, and names the version it replaces in
// assertionVersion.supersedes. receipt's check_rows accepts a repeated
// record only when the new row supersedes that record's active version,
// and accepts a supersedes only on a repeated record, so each record is
// one linear chain whose current row is its last.
//
// This mirrors those rules, written out apart from the site's current view
// (ledger-current-view.ts) so the checks below can compare the two. Rows are
// addressed as the append gate addresses them: by an explicit
// assertionVersion.id, or, for a pre-versioning row, by its recomputed av2
// content address, which the site's entries carry once a correction names
// it. ledger-current-view.test.ts holds that addressing to receipt itself.
interface CorrectionView {
  chains: Map<string, ObservationRecordedLedgerEntry[]>;
  current: ObservationRecordedLedgerEntry[];
  superseded: ObservationRecordedLedgerEntry[];
}

function correctionView(
  observations: ObservationRecordedLedgerEntry[],
): CorrectionView {
  const chains = new Map<string, ObservationRecordedLedgerEntry[]>();
  const versionIds = new Set<string>();
  for (const entry of observations) {
    const versionId = observationAssertionId(entry);
    const supersedes = entry.assertionVersion?.supersedes ?? null;
    // receipt reserves every row's version id, so no later row may restate
    // one (an A->B->A chain restoring a superseded value).
    if (versionId) {
      if (versionIds.has(versionId)) {
        throw new Error(
          `${entry.observationId} restates assertion version ${versionId}`,
        );
      }
      versionIds.add(versionId);
    }
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
    if (supersedes === null) {
      throw new Error(
        `${entry.observationId} duplicates its record without superseding ` +
          "an assertion version",
      );
    }
    // A pre-versioning row nothing names has no address on its entry, so a
    // supersedes can never match it.
    const activeId = observationAssertionId(chain[chain.length - 1]);
    if (supersedes !== activeId) {
      throw new Error(
        `${entry.observationId} repeats its record but supersedes ` +
          `${String(supersedes)}, not the active version ` +
          String(activeId ?? "(a pre-versioning row nothing names)"),
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

function daysLater(date: string, days: number): string {
  return new Date(instant(date) + days * 86_400_000).toISOString().slice(0, 10);
}

// A correction that is meant to take its record out of a cutoff history, for
// example by moving it to another unit. Histories drop superseded rows before
// their unit and series filters, so a correction that rightly leaves a
// history and a filter that wrongly starts rejecting corrections look the
// same from the history alone. The drop-out check below therefore fails on
// every drop-out not listed here, and on a listed one that no history makes.
interface IntendedHistoryDropOut {
  // The correcting row's assertionVersion.id.
  correction: string;
  // The history: the forecast's registered target series, and its unit.
  series: string;
  unit: string;
  reason: string;
}

const INTENDED_HISTORY_DROP_OUTS: readonly IntendedHistoryDropOut[] = [];

interface HistoryDropOut {
  forecastSlug: string;
  record: string;
  correction: string;
  series: string;
  unit: string;
}

// At each correction's acceptance, every forecast history that held the row
// it supersedes just before must hold the correction from then on.
function historyDropOuts(
  ledger: PolicyEngineLedgerEntry[],
  chains: ObservationRecordedLedgerEntry[][],
): { checks: number; dropOuts: HistoryDropOut[] } {
  let checks = 0;
  const dropOuts: HistoryDropOut[] = [];
  for (const chain of chains) {
    for (let index = 1; index < chain.length; index += 1) {
      const previous = chain[index - 1];
      const correction = chain[index];
      const accepted = instant(correction.acceptedAtUtc);
      if (accepted <= instant(previous.acceptedAtUtc)) {
        throw new Error(
          `${correction.observationId}: a correction accepted no later ` +
            "than the row it supersedes",
        );
      }
      const before = new Date(accepted - 1).toISOString();
      const at = new Date(accepted).toISOString();
      for (const forecast of FORECAST_CELLS) {
        if (
          !ledgerHistoryAtCutoff(forecast, ledger, before).includes(previous)
        ) {
          continue;
        }
        checks += 1;
        if (ledgerHistoryAtCutoff(forecast, ledger, at).includes(correction)) {
          continue;
        }
        dropOuts.push({
          forecastSlug: forecast.slug,
          record: correction.observationId,
          correction: observationAssertionId(correction) ?? "(none)",
          series:
            registeredTargetSeriesIdentity(
              forecast.dataPointId ?? "",
              ledger,
            ) ?? "(none)",
          unit: forecast.unit,
        });
      }
    }
  }
  return { checks, dropOuts };
}

function isListedDropOut(
  dropOut: Pick<HistoryDropOut, "correction" | "series" | "unit">,
  listed: IntendedHistoryDropOut,
): boolean {
  return (
    listed.correction === dropOut.correction &&
    listed.series === dropOut.series &&
    listed.unit === dropOut.unit
  );
}

describe("Chronicle corrections on the pinned ledger", () => {
  let ledger: PolicyEngineLedgerEntry[] = [];
  let observations: ObservationRecordedLedgerEntry[] = [];
  let rawRows: Record<string, unknown>[] = [];
  let view: CorrectionView;
  let correctedChains: ObservationRecordedLedgerEntry[][] = [];
  let resolvedForecastCells: ForecastCell[] = [];

  beforeAll(async () => {
    ledger = await loadPolicyEngineLedger();
    observations = ledger.filter(isObservationRecordedLedgerEntry);
    // The pinned rows themselves, line for line with the observations.
    rawRows = (
      await fetchPinnedPolicyEngineLedgerBytes(POLICYENGINE_LEDGER_PIN)
    )
      .toString("utf-8")
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => JSON.parse(line) as Record<string, unknown>);
    view = correctionView(observations);
    correctedChains = [...view.chains.values()].filter(
      (chain) => chain.length > 1,
    );
    resolvedForecastCells = withResolvedOutcomes(FORECAST_CELLS, ledger);
  });

  // The pinned ledger with one more row: a correction of `original` changed
  // by `changes`, accepted after every pinned row, as Chronicle's gate would
  // take it. A pre-versioning original also gets the content address its
  // correction names, as the pinned path annotates such a row.
  function withCorrection(
    original: ObservationRecordedLedgerEntry,
    changes: Record<string, unknown>,
  ) {
    const line = observations.indexOf(original);
    const raw = rawRows[line];
    expect(raw.source_record_id).toBe(original.dataPointId);
    const fix: Record<string, unknown> = {
      ...structuredClone(raw),
      ...changes,
    };
    delete fix.assertionVersion;
    fix.assertionVersion = {
      id: expectedAssertionVersionId(fix),
      supersedes: effectiveAssertionId(raw),
    };
    assertAppendGateAssertionVersions([...rawRows, fix]);
    const [mapped] = mapPolicyEngineLedgerRows([fix]);
    const acceptedAtUtc = new Date(
      Math.max(...observations.map((entry) => instant(entry.acceptedAtUtc))) +
        60_000,
    ).toISOString();
    const correction: ObservationRecordedLedgerEntry = {
      ...mapped,
      acceptedSequence: rawRows.length,
      acceptedAtUtc,
      acceptedCommit: "f".repeat(40),
      ledgerCustody: "append_derived",
      legacyQuarantined: false,
      resolutionRecordedAt: mapped.retrievedAt ?? acceptedAtUtc,
    };
    const replaced: ObservationRecordedLedgerEntry =
      observationAssertionId(original) === null
        ? { ...original, supersededContentAddress: effectiveAssertionId(raw) }
        : original;
    const extended = [
      ...ledger.map((entry) => (entry === original ? replaced : entry)),
      correction,
    ];
    return { correction, extended, fix, replaced };
  }

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
    expect(rawRows.length).toBe(observations.length);

    // receipt's effective_current_rows drops every row whose version some
    // row supersedes. On a ledger that passes the chain rules, that is the
    // same set as the last row of each chain, and it is the site's view.
    const supersededIds = new Set(
      observations.flatMap((entry) =>
        entry.assertionVersion?.supersedes
          ? [entry.assertionVersion.supersedes]
          : [],
      ),
    );
    expect(
      observations.filter((entry) => {
        const id = observationAssertionId(entry);
        return id === null || !supersededIds.has(id);
      }),
    ).toEqual(view.current);
    expect(
      currentLedgerView(ledger).filter(isObservationRecordedLedgerEntry),
    ).toEqual(view.current);
  });

  it("refuses ledgers that break receipt's chain rules", () => {
    const base = observations.find(
      (entry) =>
        entry.assertionVersion?.id &&
        view.chains.get(entry.observationId)!.length === 1,
    )!;
    const baseId = base.assertionVersion!.id;
    const versioned = (id: string, supersedes: string | null) => ({
      ...base,
      assertionVersion: { id, supersedes },
    });
    const first = `av2:${"1".repeat(64)}`;
    const second = `av2:${"2".repeat(64)}`;

    const corrected = correctionView([base, versioned(first, baseId)]);
    expect(corrected.current).toEqual([versioned(first, baseId)]);
    expect(corrected.superseded).toEqual([base]);

    expect(() => correctionView([base, versioned(first, null)])).toThrow(
      "without superseding",
    );
    expect(() => correctionView([versioned(first, baseId)])).toThrow(
      "has no earlier row",
    );
    expect(() =>
      correctionView([
        base,
        versioned(first, baseId),
        versioned(second, baseId),
      ]),
    ).toThrow("not the active version");
    expect(() =>
      correctionView([
        base,
        versioned(first, baseId),
        versioned(baseId, first),
      ]),
    ).toThrow("restates assertion version");
    expect(() =>
      correctionView([
        { ...base, assertionVersion: undefined },
        versioned(first, second),
      ]),
    ).toThrow("not the active version");
  });

  it("corrects a pre-versioning row through its av2 content address", () => {
    // #378 refused this case until the site could compute the address. A
    // correction names a pre-versioning row by the av2 address receipt
    // recomputes from its content; the gate accepts it, and the row drops out.
    const index = observations.findIndex(
      (entry, line) =>
        !rawRows[line].assertionVersion &&
        view.chains.get(entry.observationId)!.length === 1,
    );
    expect(index).toBeGreaterThanOrEqual(0);
    const legacy = rawRows[index];
    const address = expectedAssertionVersionId(legacy);
    const fix: Record<string, unknown> = {
      ...structuredClone(legacy),
      value: (legacy.value as number) + 1,
    };
    fix.assertionVersion = {
      id: expectedAssertionVersionId(fix),
      supersedes: address,
    };
    expect(() =>
      assertAppendGateAssertionVersions([legacy, fix]),
    ).not.toThrow();

    const [legacyEntry, fixEntry] = mapPolicyEngineLedgerRows([legacy, fix]);
    expect(legacyEntry.supersededContentAddress).toBe(address);
    const corrected = correctionView([legacyEntry, fixEntry]);
    expect(corrected.current).toEqual([fixEntry]);
    expect(corrected.superseded).toEqual([legacyEntry]);
    expect(currentLedgerView([legacyEntry, fixEntry])).toEqual([fixEntry]);

    // A supersedes naming anything but that address is refused, by the gate
    // and by the chain rules alike.
    const stray = {
      ...fix,
      assertionVersion: {
        ...(fix.assertionVersion as object),
        supersedes: "av2:x",
      },
    };
    expect(() => assertAppendGateAssertionVersions([legacy, stray])).toThrow(
      /active version/,
    );
    const [unnamed] = mapPolicyEngineLedgerRows([legacy]);
    expect(unnamed.supersededContentAddress).toBeUndefined();
    expect(() =>
      correctionView([
        unnamed,
        { ...fixEntry, assertionVersion: { id: "av2:y", supersedes: "av2:x" } },
      ]),
    ).toThrow("not the active version");
  });

  it("agrees with the current-view count Chronicle's pinned catalog records", async () => {
    // build_series_catalog.py counts receipt's effective_current_rows over
    // the same observation bytes, so this is a differential check against
    // Chronicle's own implementation. The catalog records a count, not rows;
    // the first test already ties the site's view to receipt's formulation
    // over these rows, so a mismatch here means the two sides read different
    // rows or Chronicle superseded a row by its content address.
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
    expect(
      currentLedgerView(ledger).filter(isObservationRecordedLedgerEntry).length,
    ).toBe(catalog.current_assertion_rows);
  });

  it("grades a corrected record on its current row, never a superseded one", () => {
    const current = new Set(view.current);
    for (const forecast of resolvedForecastCells) {
      const observation = getResolvedObservationForForecast(forecast, ledger);
      if (!observation) continue;
      expect(
        current.has(observation),
        `${forecast.slug} grades a superseded row of ` +
          `${observation.observationId}`,
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

  it("grades a same-date or later-dated correction in place of the row it replaces", () => {
    // A correction that keeps its original's observed_at, or moves it later,
    // ties or loses the first-print sort, so a lookup that ignored supersedes
    // kept grading the superseded row. #378 executed that counterexample on
    // initial-claims-week-2026-09-19: a same-date correction to 202 still
    // graded 197. Here every graded row gets both shapes of correction.
    let gradedRows = 0;
    let scoredRuns = 0;
    for (const forecast of resolvedForecastCells) {
      const graded = getResolvedObservationForForecast(forecast, ledger);
      if (!graded) continue;
      gradedRows += 1;
      const runs = getForecastRunEntries(forecast);
      const before = runs.map((run) =>
        evaluateResolvedForecastRun(forecast, run, ledger),
      );
      const observedAt = rawRows[observations.indexOf(graded)]
        .observed_at as string;
      for (const shape of [observedAt, daysLater(observedAt, 7)]) {
        const { correction, extended, fix } = withCorrection(graded, {
          value: graded.value + 5,
          observed_at: shape,
        });
        expect(getResolvedObservationForForecast(forecast, extended)).toBe(
          correction,
        );
        expect(
          withResolvedOutcomes([forecast], extended)[0].resolvedOutcome?.value,
        ).toBe(graded.value + 5);
        const fixId = (fix.assertionVersion as { id: string }).id;
        runs.forEach((run, index) => {
          const was = before[index].score;
          if (!was) return;
          const now = evaluateResolvedForecastRun(forecast, run, extended);
          const where = `${forecast.slug} ${run.variantId} on ${shape}`;
          if (!now.score) {
            // A correction is appended after the legacy quarantine. Against
            // a target with a registered contract it must carry the full
            // binding, which a quarantined legacy row's copy lacks; that is
            // the only exclusion a correction may add, and it never falls
            // back to the superseded row.
            const target = getLedgerTargetByDataPointId(
              forecast.dataPointId ?? "",
            );
            expect(was.contractBinding, where).toBe("legacy_unbound");
            expect(graded.legacyQuarantined, where).toBe(true);
            expect(target?.targetContentHash, where).toBeTruthy();
            expect(now.exclusion?.reason, where).toBe("contract_violation");
            return;
          }
          scoredRuns += 1;
          expect(now.score.contractBinding, where).toBe(was.contractBinding);
          expect(now.score.observedValue, where).toBe(graded.value + 5);
          // The chain's first print is unchanged, so is the ex-ante boundary.
          expect(now.score?.observedAt, where).toBe(was.observedAt);
          expect(now.score?.chronology, where).toBe(was.chronology);
          // The event keeps the record's historical id and names the
          // grading assertion, so it never names two outcomes.
          const slug = (text: string) => text.replace(/[^A-Za-z0-9]+/g, "-");
          expect(now.score?.resolutionEventId, where).toBe(
            `resolution_event.${forecast.slug}.` +
              `${slug(graded.observationId.replace(/^obs\./, ""))}.` +
              slug(fixId),
          );
          expect(now.score?.resolutionEventId).not.toBe(was.resolutionEventId);
        });
      }
    }
    expect(gradedRows).toBeGreaterThan(0);
    expect(scoredRuns).toBeGreaterThan(0);
  });

  it("dates and admits a graded correction by its whole chain", () => {
    // A run must precede the earliest print in the correction's chain, and
    // registration membership (finding N5) is judged on the chain's first
    // acceptance: the record was in the ledger state a registration pinned
    // exactly when some row of its chain was.
    //
    // That stays right for the first-vintage corrections on this pin, whose
    // superseded row recorded a later vintage rather than the first print.
    // A later vintage in the pinned state means the first print was public
    // even earlier, so the record was already known at registration; the
    // first acceptance is the strictest reading, and the only one under which
    // a correction can never make a known print gradeable. Here the earliest
    // print is the correction, and the first acceptance is the original's.
    const chainsById = new Map(
      correctedChains.map((chain) => [chain[0].observationId, chain]),
    );
    let gradedCorrections = 0;
    let firstVintageCorrections = 0;
    let scoredRuns = 0;
    let membershipChecks = 0;
    for (const forecast of resolvedForecastCells) {
      const observation = getResolvedObservationForForecast(forecast, ledger);
      const chain = observation && chainsById.get(observation.observationId);
      if (!observation || !chain) continue;
      gradedCorrections += 1;
      expect(observation).toBe(chain.at(-1));
      expect(forecast.resolvedOutcome?.value).toBe(observation.value);

      const earliest = chain.reduce((first, entry) =>
        instant(entry.observedAt) < instant(first.observedAt) ? entry : first,
      );
      expect(firstObservedAt(observation, ledger)).toBe(earliest.observedAt);
      const firstAcceptance = Math.min(
        ...chain.map((entry) => entry.acceptedSequence!),
      );
      expect(firstAcceptedSequence(observation, ledger)).toBe(firstAcceptance);
      if (earliest === observation) {
        firstVintageCorrections += 1;
        expect(firstAcceptance).toBe(chain[0].acceptedSequence);
        expect(firstAcceptance).toBeLessThan(observation.acceptedSequence!);
      }

      const evaluations = getForecastRunEntries(forecast).map((run) =>
        evaluateResolvedForecastRun(forecast, run, ledger),
      );
      for (const evaluation of evaluations) {
        if (!evaluation.score) continue;
        scoredRuns += 1;
        expect(evaluation.score.observedValue).toBe(observation.value);
        expect(evaluation.score.observedAt).toBe(earliest.observedAt);
      }
      const target = getLedgerTargetByDataPointId(forecast.dataPointId ?? "");
      if (typeof target?.ledgerPinLineCount !== "number") continue;
      membershipChecks += 1;
      const member = firstAcceptance < target.ledgerPinLineCount;
      const where =
        `${forecast.slug}: chain first accepted at sequence ` +
        `${firstAcceptance}, registration pinned ` +
        `${target.ledgerPinLineCount} rows`;
      for (const evaluation of evaluations) {
        if (member) {
          expect(evaluation.score, where).toBeUndefined();
        } else {
          expect(evaluation.exclusion?.detail ?? "", where).not.toMatch(
            /already inside the pinned ledger state/,
          );
        }
      }
    }
    expect(gradedCorrections).toBeGreaterThan(0);
    expect(firstVintageCorrections).toBeGreaterThan(0);
    expect(scoredRuns).toBeGreaterThan(0);
    expect(membershipChecks).toBeGreaterThan(0);
  });

  it("keeps cutoff histories on the ledger's current view as of each cutoff", () => {
    // A correction must not rewrite a history cut before it was accepted,
    // and a row superseded by the cutoff must not stay in it. Check every
    // forecast history at each acceptance instant in the corrected chains,
    // just before each, and far in the future: the only row of a corrected
    // record it may hold is that record's last row accepted by the cutoff.
    const chainRows = new Map(
      correctedChains.flatMap((chain) =>
        chain.map((entry) => [entry, chain] as const),
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
    let chainRowChecks = 0;
    const reaching = new Set<string>();
    for (const forecast of FORECAST_CELLS) {
      for (const cutoff of cutoffs) {
        const cutoffTime = instant(cutoff);
        for (const entry of ledgerHistoryAtCutoff(forecast, ledger, cutoff)) {
          const chain = chainRows.get(entry);
          if (!chain) continue;
          chainRowChecks += 1;
          reaching.add(forecast.slug);
          const asOf = chain
            .filter((row) => instant(row.acceptedAtUtc) <= cutoffTime)
            .at(-1);
          expect(
            entry,
            `${forecast.slug} history at ${cutoff} keeps ` +
              `${entry.observationId} at sequence ` +
              `${String(entry.acceptedSequence)}, not its row as of then ` +
              `(sequence ${String(asOf?.acceptedSequence)})`,
          ).toBe(asOf);
        }
      }
    }
    expect(reaching.size).toBeGreaterThan(0);
    expect(chainRowChecks).toBeGreaterThan(0);
  });

  it("keeps a corrected record in every history that held it, unless the drop-out is intended", () => {
    // The check fails on a filter that rejects some corrections as well as
    // on one that rejects them all, which an as-of check cannot tell from a
    // correction meant to leave its history.
    const { checks, dropOuts } = historyDropOuts(ledger, correctedChains);
    expect(checks).toBeGreaterThan(0);
    expect(
      dropOuts.filter(
        (dropOut) =>
          !INTENDED_HISTORY_DROP_OUTS.some((listed) =>
            isListedDropOut(dropOut, listed),
          ),
      ),
      "a correction left a history that held the row it supersedes: a " +
        "history filter is rejecting corrections, or the correction is " +
        "meant to leave (a unit change, say) and belongs in " +
        "INTENDED_HISTORY_DROP_OUTS with its reason",
    ).toEqual([]);
    expect(
      INTENDED_HISTORY_DROP_OUTS.filter(
        (listed) =>
          !dropOuts.some((dropOut) => isListedDropOut(dropOut, listed)),
      ),
      "INTENDED_HISTORY_DROP_OUTS lists a drop-out no history makes",
    ).toEqual([]);
  });

  // The contract-bound row the most cutoff histories hold, and how many.
  function mostHeldRecord(): [ObservationRecordedLedgerEntry, number] {
    const held = new Map<ObservationRecordedLedgerEntry, number>();
    for (const forecast of FORECAST_CELLS) {
      for (const entry of ledgerHistoryAtCutoff(
        forecast,
        ledger,
        "2100-01-01T00:00:00.000Z",
      )) {
        if (rawRows[observations.indexOf(entry)].sourceBindingProjection) {
          held.set(entry, (held.get(entry) ?? 0) + 1);
        }
      }
    }
    return [...held].sort((left, right) => right[1] - left[1])[0];
  }

  it("keeps a same-date or later-dated correction in every history that held its original", () => {
    // Histories keep a record's current row whatever its date, so a value
    // correction of a held record replaces it everywhere and leaves nothing.
    const [record, holders] = mostHeldRecord();
    expect(holders).toBeGreaterThan(1);
    const observedAt = rawRows[observations.indexOf(record)]
      .observed_at as string;
    // One day later keeps the print on or before the correction's acceptance.
    for (const shape of [observedAt, daysLater(observedAt, 1)]) {
      const { correction, extended, replaced } = withCorrection(record, {
        value: record.value + 5,
        observed_at: shape,
      });
      const { checks, dropOuts } = historyDropOuts(extended, [
        [replaced, correction],
      ]);
      expect(checks, shape).toBe(holders);
      expect(dropOuts, shape).toEqual([]);
    }
  });

  it("reports a unit-changing correction as a drop-out until it is listed", () => {
    // The case the list exists for. Move the record the most histories hold
    // into another unit: every history that held it loses it, and the check
    // above would name each one.
    const [record, holders] = mostHeldRecord();
    const raw = rawRows[observations.indexOf(record)];
    const unit = record.unit === "millions" ? "thousands" : "millions";
    const { correction, extended, replaced } = withCorrection(record, {
      measure: { ...(raw.measure as object), unit },
      sourceBindingProjection: {
        ...(raw.sourceBindingProjection as object),
        unit,
      },
    });
    const { checks, dropOuts } = historyDropOuts(extended, [
      [replaced, correction],
    ]);
    expect(checks).toBe(holders);
    expect(dropOuts).toHaveLength(checks);
    for (const dropOut of dropOuts) {
      expect(dropOut.correction).toBe(observationAssertionId(correction));
      expect(dropOut.unit).toBe(record.unit);
    }
    // The record leaves outright: the superseded row never stays behind in
    // place of a correction its history's filters reject.
    for (const forecast of FORECAST_CELLS) {
      expect(
        ledgerHistoryAtCutoff(forecast, extended, correction.acceptedAtUtc!),
      ).not.toContain(replaced);
    }
  });
});
