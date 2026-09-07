"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  parseCoreHealth,
  parseCoreLeaderboard,
  parseCoreListPage,
  readStringField,
  readTimingSummary,
  type CoreHealth,
  type CoreLeaderboard,
  type CoreListPage,
  type CoreRecordItem,
  type CoreAttemptCounts,
  type Reading,
} from "./core-contracts";
import { fetchCoreResource, type CoreResourceState } from "./core-client";
import {
  DECLARED_CUTOFF_LABEL,
  EFFECTIVE_BOUNDARY_LABEL,
  TIMING_CHECK_LABEL,
  describeCoverage,
  describeExclusions,
  describeIdentifier,
  describeMode,
  describeOrdering,
  describeRank,
  describeSchemaVersion,
  describeScore,
  describeTimestamp,
  describeTimestampSource,
} from "./core-display";

/** One page is enough for a lab view; the cursor state is disclosed, not hidden. */
const PAGE_LIMIT = 25;

/**
 * A forecast run's canonical payload links to its attempt, not to an
 * experiment, so this is the join the record actually records.
 */
const RUN_REFERENCE = { label: "Attempt", field: "attempt_id" } as const;

const mono = "[font-family:var(--font-mono)]";
const cellBase = "px-4 py-3 align-top text-[0.8rem]";

export function CoreExperimentView() {
  const [health, setHealth] = useState<CoreResourceState<CoreHealth>>({
    state: "loading",
  });
  const [experiments, setExperiments] = useState<
    CoreResourceState<CoreListPage>
  >({
    state: "loading",
  });
  const [runs, setRuns] = useState<CoreResourceState<CoreListPage>>({
    state: "loading",
  });
  const [leaderboard, setLeaderboard] = useState<
    CoreResourceState<CoreLeaderboard>
  >({ state: "loading" });
  const [busy, setBusy] = useState(true);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    setBusy(true);
    const [nextHealth, nextExperiments, nextRuns, nextLeaderboard] =
      await Promise.all([
        fetchCoreResource("health", parseCoreHealth),
        fetchCoreResource(`experiments?limit=${PAGE_LIMIT}`, parseCoreListPage),
        fetchCoreResource(`runs?limit=${PAGE_LIMIT}`, parseCoreListPage),
        fetchCoreResource("leaderboard", parseCoreLeaderboard),
      ]);
    if (!mounted.current) return;
    setHealth(nextHealth);
    setExperiments(nextExperiments);
    setRuns(nextRuns);
    setLeaderboard(nextLeaderboard);
    setBusy(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div>
      <div
        className="mt-8 flex flex-wrap items-center justify-between gap-3 rounded-[12px] border px-4 py-3"
        style={{ borderColor: "var(--theme-border)" }}
        aria-live="polite"
        aria-busy={busy}
      >
        <HealthLine health={health} />
        <button
          type="button"
          onClick={() => void load()}
          disabled={busy}
          className={`${mono} rounded-[8px] border px-3 py-1.5 text-[0.72rem] uppercase tracking-[0.08em] disabled:opacity-50`}
          style={{
            borderColor: "var(--theme-border)",
            color: "var(--theme-text)",
          }}
        >
          {busy ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <RecordSection
        title="Experiments"
        description="Compare the declared information deadline with when each evidence bundle was recorded."
        testIdPrefix="experiment"
        state={experiments}
        emptyMessage="No experiments have been registered in the core database yet."
      />

      <RecordSection
        title="Runs"
        description="Recorded forecasts and the evidence supplied to each run."
        testIdPrefix="run"
        state={runs}
        emptyMessage="No runs have been recorded in the core database yet."
        reference={RUN_REFERENCE}
      />

      <LeaderboardSection state={leaderboard} />

      <p
        className="mt-12 max-w-[720px] text-[0.78rem] leading-[1.6]"
        style={{ color: "var(--theme-text-muted)" }}
      >
        This view is read-only. Select an ID to inspect the full record.
      </p>
    </div>
  );
}

function HealthLine({ health }: { health: CoreResourceState<CoreHealth> }) {
  const base = `${mono} text-[0.75rem]`;
  if (health.state === "loading") {
    return (
      <span className={base} style={{ color: "var(--theme-text-muted)" }}>
        Core API status: loading…
      </span>
    );
  }
  if (health.state === "unconfigured") {
    return (
      <span className={base} style={{ color: "var(--theme-text-muted)" }}>
        Core API status: not configured — {health.message}
      </span>
    );
  }
  if (health.state === "error") {
    return (
      <span className={base} style={{ color: "var(--theme-text)" }}>
        Core API status: unavailable — {health.message}
      </span>
    );
  }
  return (
    <span className={base} style={{ color: "var(--theme-text)" }}>
      Core API status: {health.data.status} · schema version{" "}
      {describeSchemaVersion(health.data.schemaVersion)}
    </span>
  );
}

function SectionShell({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-12">
      <h2
        className="[font-family:var(--font-display)] text-[1.25rem] font-semibold"
        style={{ color: "var(--theme-text)" }}
      >
        {title}
      </h2>
      <p
        className="mt-2 max-w-[720px] text-[0.85rem] leading-[1.6]"
        style={{ color: "var(--theme-text-muted)" }}
      >
        {description}
      </p>
      {children}
    </section>
  );
}

function StateNotice({ children }: { children: React.ReactNode }) {
  return (
    <p
      className={`${mono} mt-5 rounded-[12px] border px-4 py-3 text-[0.78rem]`}
      style={{
        borderColor: "var(--theme-border)",
        color: "var(--theme-text-muted)",
      }}
    >
      {children}
    </p>
  );
}

function PageNotes({ page }: { page: CoreListPage }) {
  if (page.nextCursor === null && page.rejectedItems === 0) return null;
  return (
    <p
      className="mt-3 text-[0.75rem] leading-[1.55]"
      style={{ color: "var(--theme-text-muted)" }}
    >
      {page.nextCursor !== null
        ? `Showing ${page.items.length} row(s) from the first page; the API reported more pages beyond this one. `
        : ""}
      {page.rejectedItems > 0
        ? `${page.rejectedItems} row(s) were returned in a shape this page does not recognize and are not displayed.`
        : ""}
    </p>
  );
}

function RecordSection({
  title,
  description,
  testIdPrefix,
  state,
  emptyMessage,
  reference,
}: {
  title: string;
  description: string;
  testIdPrefix: string;
  state: CoreResourceState<CoreListPage>;
  emptyMessage: string;
  reference?: { label: string; field: string };
}) {
  return (
    <SectionShell title={title} description={description}>
      {state.state === "loading" ? (
        <StateNotice>Loading {title.toLowerCase()}…</StateNotice>
      ) : null}
      {state.state === "unconfigured" ? (
        <StateNotice>{state.message}</StateNotice>
      ) : null}
      {state.state === "error" ? (
        <StateNotice>
          {title} unavailable: {state.message}
        </StateNotice>
      ) : null}
      {state.state === "ready" && state.data.items.length === 0 ? (
        <StateNotice>
          {state.data.rejectedItems > 0
            ? `The API returned ${state.data.rejectedItems} row(s) in a shape this page does not recognize, and no row it could read. This is not an empty database.`
            : emptyMessage}
        </StateNotice>
      ) : null}
      {state.state === "ready" && state.data.items.length > 0 ? (
        <>
          <div
            className="mt-5 overflow-x-auto rounded-[14px] border"
            style={{ borderColor: "var(--theme-border)" }}
          >
            <table className="w-full border-collapse text-[0.84rem]">
              <thead>
                <tr
                  className={`${mono} text-[0.6rem] uppercase tracking-[0.1em]`}
                  style={{ color: "var(--theme-text-muted)" }}
                >
                  <th className="px-4 py-3 text-left font-normal">Record ID</th>
                  <th className="px-4 py-3 text-left font-normal">Kind</th>
                  {reference ? (
                    <th className="px-4 py-3 text-left font-normal">
                      {reference.label}
                    </th>
                  ) : null}
                  <th className="px-4 py-3 text-left font-normal">Mode</th>
                  <th className="px-4 py-3 text-left font-normal">
                    {DECLARED_CUTOFF_LABEL}
                  </th>
                  <th className="px-4 py-3 text-left font-normal">
                    {EFFECTIVE_BOUNDARY_LABEL}
                  </th>
                  <th className="px-4 py-3 text-left font-normal">
                    {TIMING_CHECK_LABEL}
                  </th>
                </tr>
              </thead>
              <tbody>
                {state.data.items.map((item, index) => (
                  <RecordRow
                    // Record ids are content hashes and should be unique, but a
                    // duplicate must render as two rows, not silently as one.
                    key={`${item.id}#${index}`}
                    item={item}
                    testIdPrefix={testIdPrefix}
                    reference={reference}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <PageNotes page={state.data} />
        </>
      ) : null}
    </SectionShell>
  );
}

function RecordRow({
  item,
  testIdPrefix,
  reference,
}: {
  item: CoreRecordItem;
  testIdPrefix: string;
  reference?: { label: string; field: string };
}) {
  const timing = readTimingSummary(item.summary, item.payload);
  return (
    <tr className="border-t" style={{ borderColor: "var(--theme-border)" }}>
      <td
        className={`${cellBase} ${mono} whitespace-nowrap`}
        style={{ color: "var(--theme-text)" }}
        data-testid={`${testIdPrefix}-id:${item.id}`}
      >
        <RecordIdentifier reading={{ state: "value", value: item.id }} />
      </td>
      <td
        className={`${cellBase} ${mono} whitespace-nowrap`}
        style={{ color: "var(--theme-text-muted)" }}
      >
        {item.kind}
      </td>
      {reference ? (
        <td
          className={`${cellBase} ${mono} whitespace-nowrap`}
          style={{ color: "var(--theme-text-muted)" }}
          data-testid={`${testIdPrefix}-reference:${item.id}`}
        >
          <RecordIdentifier reading={readReference(item, reference.field)} />
        </td>
      ) : null}
      <td
        className={cellBase}
        style={{ color: "var(--theme-text)" }}
        data-testid={`${testIdPrefix}-mode:${item.id}`}
      >
        {describeMode(timing.mode)}
      </td>
      <td
        className={`${cellBase} ${mono} whitespace-nowrap`}
        style={{ color: "var(--theme-text)" }}
        title={describeTimestampSource(timing.declaredCutoff)}
        data-testid={`${testIdPrefix}-declared-cutoff:${item.id}`}
      >
        {describeTimestamp(timing.declaredCutoff)}
      </td>
      <td
        className={`${cellBase} ${mono} whitespace-nowrap`}
        style={{ color: "var(--theme-text)" }}
        title={describeTimestampSource(timing.effectiveBoundary)}
        data-testid={`${testIdPrefix}-effective-boundary:${item.id}`}
      >
        {describeTimestamp(timing.effectiveBoundary)}
      </td>
      <td
        className={cellBase}
        style={{ color: "var(--theme-text-muted)" }}
        data-testid={`${testIdPrefix}-timing-check:${item.id}`}
      >
        {describeOrdering(timing.ordering)}
      </td>
    </tr>
  );
}

function RecordIdentifier({ reading }: { reading: Reading<string> }) {
  if (reading.state !== "value" || !/^[0-9a-f]{64}$/.test(reading.value)) {
    return <>{describeIdentifier(reading)}</>;
  }
  return (
    <a
      href={`/api/core/records/${reading.value}`}
      title={reading.value}
      className="underline decoration-[var(--theme-border)] underline-offset-4 hover:decoration-current"
    >
      {reading.value.slice(0, 12)}…
    </a>
  );
}

function AttemptCounts({ reading }: { reading: Reading<CoreAttemptCounts> }) {
  if (reading.state !== "value") return <>{describeScore(reading)}</>;
  const count = reading.value;
  return (
    <div className="space-y-1 whitespace-nowrap">
      <p>
        {count.total} total · {count.succeeded} succeeded
      </p>
      <p>
        {count.failed} failed · {count.unknown} unknown · {count.pending}{" "}
        pending
      </p>
      <p>
        {count.reconciled} reconciled · {count.unknown_history} unknown history
      </p>
    </div>
  );
}

function Latency({ reading }: { reading: Reading<number> }) {
  if (reading.state !== "value") return <>{describeScore(reading)}</>;
  const seconds =
    reading.value > 0 && reading.value < 0.01
      ? "<0.01"
      : reading.value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return <span title={`${reading.value} seconds`}>{seconds} s</span>;
}

/** Read a linked record id from the API projection, then the payload. */
function readReference(item: CoreRecordItem, field: string) {
  const fromSummary = readStringField(item.summary, field);
  return fromSummary.state === "missing"
    ? readStringField(item.payload, field)
    : fromSummary;
}

function LeaderboardSection({
  state,
}: {
  state: CoreResourceState<CoreLeaderboard>;
}) {
  return (
    <SectionShell
      title="Forecaster evaluations"
      description="Ranks require complete eligible paired coverage. Replay and excluded results remain unranked."
    >
      {state.state === "loading" ? (
        <StateNotice>Loading forecaster evaluations…</StateNotice>
      ) : null}
      {state.state === "unconfigured" ? (
        <StateNotice>{state.message}</StateNotice>
      ) : null}
      {state.state === "error" ? (
        <StateNotice>
          Forecaster evaluations unavailable: {state.message}
        </StateNotice>
      ) : null}
      {state.state === "ready" && state.data.items.length === 0 ? (
        <StateNotice>
          {state.data.rejectedItems > 0
            ? `The API returned ${state.data.rejectedItems} evaluation row(s) in a shape this page does not recognize, and no row it could read. This is not an empty leaderboard.`
            : "No forecaster evaluations have been scored in the core database yet."}
        </StateNotice>
      ) : null}
      {state.state === "ready" && state.data.items.length > 0 ? (
        <>
          <div
            className="mt-5 overflow-x-auto rounded-[14px] border"
            style={{ borderColor: "var(--theme-border)" }}
          >
            <table className="w-full border-collapse text-[0.84rem]">
              <thead>
                <tr
                  className={`${mono} text-[0.6rem] uppercase tracking-[0.1em]`}
                  style={{ color: "var(--theme-text-muted)" }}
                >
                  <th className="px-4 py-3 text-left font-normal">
                    Experiment
                  </th>
                  <th className="px-4 py-3 text-left font-normal">
                    Forecaster
                  </th>
                  <th className="px-4 py-3 text-left font-normal">Mode</th>
                  <th className="px-4 py-3 text-left font-normal">Rank</th>
                  <th className="px-4 py-3 text-left font-normal">
                    Eligible coverage
                  </th>
                  <th className="px-4 py-3 text-left font-normal">
                    Mean normalized CRPS
                  </th>
                  <th className="px-4 py-3 text-left font-normal">
                    Exclusions
                  </th>
                  <th className="px-4 py-3 text-left font-normal">Attempts</th>
                  <th className="px-4 py-3 text-left font-normal">
                    Mean latency
                  </th>
                  <th className="px-4 py-3 text-left font-normal">
                    {DECLARED_CUTOFF_LABEL}
                  </th>
                  <th className="px-4 py-3 text-left font-normal">
                    {EFFECTIVE_BOUNDARY_LABEL}
                  </th>
                  <th className="px-4 py-3 text-left font-normal">
                    {TIMING_CHECK_LABEL}
                  </th>
                </tr>
              </thead>
              <tbody>
                {state.data.items.map((row, index) => {
                  const rowKey =
                    row.experimentId.state === "value" &&
                    row.forecasterId.state === "value"
                      ? `${row.experimentId.value}:${row.forecasterId.value}`
                      : `row-${index}`;
                  return (
                    <tr
                      key={`${rowKey}#${index}`}
                      className="border-t"
                      style={{ borderColor: "var(--theme-border)" }}
                    >
                      <td
                        className={`${cellBase} ${mono} whitespace-nowrap`}
                        style={{ color: "var(--theme-text-muted)" }}
                      >
                        <RecordIdentifier reading={row.experimentId} />
                      </td>
                      <td
                        className={`${cellBase} ${mono} whitespace-nowrap`}
                        style={{ color: "var(--theme-text)" }}
                        data-testid={`leaderboard-forecaster:${rowKey}`}
                      >
                        <RecordIdentifier reading={row.forecasterId} />
                      </td>
                      <td
                        className={cellBase}
                        style={{ color: "var(--theme-text)" }}
                        data-testid={`leaderboard-mode:${rowKey}`}
                      >
                        {describeMode(row.mode)}
                      </td>
                      <td
                        className={`${cellBase} ${mono}`}
                        style={{ color: "var(--theme-text)" }}
                        data-testid={`leaderboard-rank:${rowKey}`}
                      >
                        {describeRank(row.rank, row.rankEligible)}
                      </td>
                      <td
                        className={`${cellBase} ${mono}`}
                        style={{ color: "var(--theme-text-muted)" }}
                        data-testid={`leaderboard-coverage:${rowKey}`}
                      >
                        {describeCoverage(row.coverage)}
                      </td>
                      <td
                        className={`${cellBase} ${mono}`}
                        style={{ color: "var(--theme-text)" }}
                        data-testid={`leaderboard-crps:${rowKey}`}
                      >
                        {describeScore(row.meanNormalizedCrps)}
                      </td>
                      <td
                        className={`${cellBase} text-[0.76rem]`}
                        style={{ color: "var(--theme-text-muted)" }}
                        data-testid={`leaderboard-exclusions:${rowKey}`}
                      >
                        {describeExclusions(row.exclusions)}
                      </td>
                      <td
                        className={`${cellBase} ${mono} text-[0.72rem]`}
                        style={{ color: "var(--theme-text-muted)" }}
                        data-testid={`leaderboard-attempts:${rowKey}`}
                      >
                        <AttemptCounts reading={row.attemptCounts} />
                      </td>
                      <td
                        className={`${cellBase} ${mono} whitespace-nowrap`}
                        style={{ color: "var(--theme-text-muted)" }}
                        data-testid={`leaderboard-latency:${rowKey}`}
                      >
                        <Latency reading={row.meanLatencySeconds} />
                      </td>
                      <td
                        className={`${cellBase} ${mono} whitespace-nowrap`}
                        style={{ color: "var(--theme-text)" }}
                        title={describeTimestampSource(
                          row.timing.declaredCutoff,
                        )}
                        data-testid={`leaderboard-declared-cutoff:${rowKey}`}
                      >
                        {describeTimestamp(row.timing.declaredCutoff)}
                      </td>
                      <td
                        className={`${cellBase} ${mono} whitespace-nowrap`}
                        style={{ color: "var(--theme-text)" }}
                        title={describeTimestampSource(
                          row.timing.effectiveBoundary,
                        )}
                        data-testid={`leaderboard-effective-boundary:${rowKey}`}
                      >
                        {describeTimestamp(row.timing.effectiveBoundary)}
                      </td>
                      <td
                        className={cellBase}
                        style={{ color: "var(--theme-text-muted)" }}
                        data-testid={`leaderboard-timing-check:${rowKey}`}
                      >
                        {describeOrdering(row.timing.ordering)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {state.data.rejectedItems > 0 ? (
            <p
              className="mt-3 text-[0.75rem] leading-[1.55]"
              style={{ color: "var(--theme-text-muted)" }}
            >
              {state.data.rejectedItems} leaderboard row(s) were returned in a
              shape this page does not recognize and are not displayed.
            </p>
          ) : null}
        </>
      ) : null}
    </SectionShell>
  );
}
