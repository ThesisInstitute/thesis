import type { Metadata } from "next";
import Link from "next/link";
import { CalibrationPlot } from "@/components/CalibrationPlot";
import { EXPIRED_UNFORECAST_REGISTRATIONS } from "@/data/expired-unforecast-registrations";
import { Header } from "@/components/Header";
import { FORECAST_CELLS, formatValue } from "@/data/forecast-cells";
import {
  OVERDUE_TARGET_COUNT,
  RESOLUTION_STATUS_META,
} from "@/data/resolution-status";
import {
  buildPredictionSpecs,
  buildRecordedPredictionRunRecords,
} from "@/data/prediction-specs";
import {
  buildBrierRewardExport,
  isNormalizedScoreAggregateEligible,
  summarizeNormalizedScores,
} from "@/data/brier-lab";
import {
  hasVerifiedClaimedChronology,
  loadPolicyEngineLedger,
  scoreResolvedForecasts,
  withResolvedOutcomes,
} from "@/data/thesis-log";

export const metadata: Metadata = {
  title: "Calibration — Thesis Institute",
  description:
    "The public scoreboard: interval coverage, CRPS against persistence baselines, and per-forecaster calibration for every resolved Thesis forecast.",
};

const BASELINE_AGENT_PREFIX = "brier.time_series_prior";

function formatCrps(value: number | null): string {
  return value === null ? "—" : value.toFixed(3);
}

function formatCoverage(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

export default async function CalibrationPage() {
  const ledger = await loadPolicyEngineLedger();
  const forecasts = withResolvedOutcomes(FORECAST_CELLS, ledger);
  const specs = buildPredictionSpecs(forecasts);
  const runs = buildRecordedPredictionRunRecords(forecasts, specs);
  const rewardExport = buildBrierRewardExport({
    forecasts,
    specs,
    runs,
    ledger,
  });
  const allScores = scoreResolvedForecasts(forecasts, ledger);
  // The headline track record is witness-verified scores only: the run's
  // sealed custody root was externally witnessed in the public record chain
  // before the observation. Claimed-time-only chronology — however
  // plausible the recorded timestamps — stays published below the fold and
  // in log.json, flagged, outside the official numbers.
  const scores = allScores.filter(
    (score) => score.chronology === "witness_verified",
  );
  const claimedOnlyCount = allScores.filter(
    (score) => score.chronology === "claimed_time_verified",
  ).length;
  const provisionalCount = allScores.filter(
    (score) => score.chronology === "unverified",
  ).length;
  const violatedCount = allScores.filter(
    (score) => score.chronology === "violated",
  ).length;
  // Published verified-chronology scores across both tiers, for the
  // resolutions table below the headline cards.
  const publishedScores = allScores.filter((score) =>
    hasVerifiedClaimedChronology(score.chronology),
  );

  const covered = scores.filter((score) => score.interval80Covered).length;
  const coverage = scores.length > 0 ? covered / scores.length : null;
  // The claimed-time tier stays fully DISPLAYED one level below the
  // headline: an empty headline (which is exactly what the witnessed
  // standard implies until the first custody-v2 waves resolve) must read
  // as a raised bar, never as an empty record.
  const claimedCovered = publishedScores.filter(
    (score) => score.interval80Covered,
  ).length;
  const claimedCoverage =
    publishedScores.length > 0 ? claimedCovered / publishedScores.length : null;
  const claimedByAgent = new Map<string, number>();
  for (const row of rewardExport.rewardRows) {
    if (row.scoreEligibility !== "excluded_chronology_claimed_only") continue;
    const key = `${row.agent ?? ""}\u0000${row.model ?? ""}`;
    claimedByAgent.set(key, (claimedByAgent.get(key) ?? 0) + 1);
  }
  const normalizedSummary = summarizeNormalizedScores(scores);
  const normalizedScores = normalizedSummary.eligibleScores;
  const meanNormalizedCrps = normalizedSummary.meanNormalizedCrps;
  const meanSharpness = normalizedSummary.meanSharpness;
  const claimedNormalizedSummary = summarizeNormalizedScores(
    publishedScores.filter(
      (score) => score.chronology === "claimed_time_verified",
    ),
  );
  const claimedNormalizedScores = claimedNormalizedSummary.eligibleScores;
  const claimedMeanNormalizedCrps = claimedNormalizedSummary.meanNormalizedCrps;
  // Until the first custody-v2 cells resolve, the witnessed tier is empty
  // by construction. The cards stay honest but never lead with a wall of
  // zeros: each shows its best PUBLISHED tier as the primary number with
  // the tier named right on the card, and flips to witnessed automatically
  // once witnessed scores exist.
  const witnessedLive = scores.length > 0;
  // `unresolvedRuns` counts forecast RUNS, several per target (agents,
  // prompt modes, strategies), so it is larger than the number of pending
  // forecasts on the home page. Say the unit, and say how many targets
  // are past their date: each of those explains itself on its own page.
  const awaitingResolution = `${rewardExport.counts.unresolvedRuns.toLocaleString()} forecast runs awaiting resolution (${OVERDUE_TARGET_COUNT.toLocaleString()} targets are past their resolution date as of ${RESOLUTION_STATUS_META.asOf}; each says why on its page)`;

  const leaderboard = [...rewardExport.leaderboard].sort((left, right) => {
    if (left.pairedCrpsRatioGeomean === null) return 1;
    if (right.pairedCrpsRatioGeomean === null) return -1;
    return left.pairedCrpsRatioGeomean - right.pairedCrpsRatioGeomean;
  });

  const cellBySlug = new Map(forecasts.map((cell) => [cell.slug, cell]));
  const recentScores = [...publishedScores]
    .sort((left, right) => {
      const a = cellBySlug.get(left.forecastSlug)?.resolutionDate ?? "";
      const b = cellBySlug.get(right.forecastSlug)?.resolutionDate ?? "";
      return b.localeCompare(a);
    })
    .slice(0, 12);

  const splits = rewardExport.splits;

  return (
    <div>
      <Header activePage="calibration" />
      <main className="mx-auto max-w-[1200px] px-8 pb-32 pt-12 max-md:px-5">
        <p
          className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.14em]"
          style={{ color: "var(--theme-text-muted)" }}
        >
          The scoreboard
        </p>
        <h1
          className="mt-2 [font-family:var(--font-display)] text-[2rem] font-semibold tracking-[-0.01em]"
          style={{ color: "var(--theme-text)" }}
        >
          Calibration
        </h1>
        <p
          className="mt-3 max-w-[640px] text-[0.95rem] leading-[1.6]"
          style={{ color: "var(--theme-text-muted)" }}
        >
          Every forecast publishes an 80% interval before resolution and is
          graded against the official first print when it lands. This page is
          computed from the same records that back{" "}
          <a href="/log.json">log.json</a> and{" "}
          <a href="/brier/reward.json">reward.json</a>; the daily
          pre-registration chain lives in the{" "}
          <a href="https://github.com/ThesisInstitute/thesis/tree/main/records">
            public records repository
          </a>
          .
        </p>
        <p
          className="mt-3 max-w-[640px] text-[0.85rem] leading-[1.6]"
          style={{ color: "var(--theme-text-muted)" }}
        >
          Scoring methodology v5 (2026-07-10): headline numbers count only
          witness-verified scores. A run enters the headline when its sealed
          custody root was externally witnessed — an RFC 3161 timestamp in
          the{" "}
          <a href="https://github.com/ThesisInstitute/thesis/blob/main/records/witnessed-timeline.json">
            witnessed chronology
          </a>{" "}
          extracted from the public record chain — before the observation,
          its custody inventory is complete and headline-eligible, and its
          recorded run time precedes the observation (sub-day ordering
          trusted only for explicit UTC-offset timestamps). A claimed
          timestamp alone never enters the headline: scores whose chronology
          rests on claimed times stay published in{" "}
          <a href="/log.json">log.json</a>, flagged claimed-time-verified,
          outside the official numbers, alongside unverified and violated
          legacy runs. CRPS is normalized only by same-series ledger
          dispersion frozen at target registration; scores without three
          pre-cutoff ledger observations publish raw CRPS and stay out of
          normalized means and rewards. The agent-versus-persistence headline
          is a per-target RAW CRPS ratio against the paired ledger baseline,
          which needs no scale at all — nothing a forecast authors can move
          its denominator.
        </p>

        <section className="mt-10 grid grid-cols-4 gap-4 max-md:grid-cols-2">
          {[
            {
              label: "Scored forecasts",
              tier: witnessedLive ? "witness-verified" : "claimed-time tier",
              value: witnessedLive
                ? String(scores.length)
                : publishedScores.length.toLocaleString(),
              detail: witnessedLive
                ? `witness-verified; ${claimedOnlyCount.toLocaleString()} claimed-time-only and ${(
                    provisionalCount + violatedCount
                  ).toLocaleString()} unverified or violated excluded, ${awaitingResolution}`
                : `witness-verified: 0 — the official headline fills as custody-v2 cells resolve (first eligible prints land July 23). ${(
                    provisionalCount + violatedCount
                  ).toLocaleString()} unverified or violated excluded, ${awaitingResolution}, ${EXPIRED_UNFORECAST_REGISTRATIONS.length} registrations expired unforecast.`,
            },
            {
              label: "80% interval coverage",
              tier: witnessedLive ? "witness-verified" : "claimed-time tier",
              value: witnessedLive
                ? formatCoverage(coverage)
                : formatCoverage(claimedCoverage),
              detail: witnessedLive
                ? `${covered} of ${scores.length} witness-verified observed inside the stated interval`
                : `${claimedCovered} of ${publishedScores.length} observed inside the stated interval · witness-verified: none scored yet`,
            },
            {
              label: "Unpaired mean normalized CRPS",
              tier: witnessedLive ? "witness-verified" : "claimed-time tier",
              value: witnessedLive
                ? formatCrps(meanNormalizedCrps)
                : formatCrps(claimedMeanNormalizedCrps),
              detail: witnessedLive
                ? `Lower is better; ${normalizedScores.length} of ${scores.length} witness-verified scores have a usable ledger scale. Mean sharpness ${
                    meanSharpness === null ? "—" : meanSharpness.toFixed(2)
                  }× target scale.`
                : `Lower is better; ${claimedNormalizedScores.length} of ${publishedScores.length} claimed-time scores have a usable pre-registered ledger scale.`,
            },
            {
              label: "CRPS ratio vs persistence",
              tier: "witness-verified",
              value:
                rewardExport.pairedComparison.crpsRatioGeomean === null
                  ? "—"
                  : rewardExport.pairedComparison.crpsRatioGeomean.toFixed(2),
              detail:
                rewardExport.pairedComparison.pairedTargets > 0
                  ? `Geometric mean of per-target raw CRPS ratios (agent / paired persistence baseline) on ${rewardExport.pairedComparison.pairedTargets} matched targets; below 1 beats persistence. ${formatCoverage(rewardExport.pairedComparison.agentWinRate)} agent win rate.`
                  : "Pairs form as series accumulate repeat resolutions; the headline ratio scores witness-verified runs only.",
            },
          ].map((stat) => (
            <div
              key={stat.label}
              className="rounded-[14px] border p-5"
              style={{
                borderColor: "var(--theme-border)",
                backgroundColor: "var(--theme-card-bg)",
              }}
            >
              <div
                className="[font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.12em]"
                style={{ color: "var(--theme-text-muted)" }}
              >
                {stat.label}
              </div>
              <div
                className="mt-2 [font-family:var(--font-display)] text-[1.7rem] font-semibold"
                style={{ color: "var(--theme-text)" }}
              >
                {stat.value}
              </div>
              <div
                className="mt-1 inline-block rounded-full border px-2 py-[1px] [font-family:var(--font-mono)] text-[0.56rem] uppercase tracking-[0.1em]"
                style={{
                  borderColor: "var(--theme-border)",
                  color: "var(--theme-text-muted)",
                }}
              >
                {stat.tier}
              </div>
              <div
                className="mt-1 text-[0.74rem] leading-[1.5]"
                style={{ color: "var(--theme-text-muted)" }}
              >
                {stat.detail}
              </div>
            </div>
          ))}
        </section>

        <section
          className="mt-6 rounded-[14px] border p-5"
          style={{
            borderColor: "var(--theme-border)",
            backgroundColor: "var(--theme-card-bg)",
          }}
        >
          <div
            className="[font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.12em]"
            style={{ color: "var(--theme-text-muted)" }}
          >
            The claimed-time tier
          </div>
          <div className="mt-3 flex flex-wrap items-baseline gap-x-10 gap-y-3">
            {[
              {
                value: publishedScores.length.toLocaleString(),
                label: "scores verified by recorded timestamps",
              },
              {
                value: formatCoverage(claimedCoverage),
                label: `interval coverage (${claimedCovered} of ${publishedScores.length} inside)`,
              },
              {
                value: violatedCount.toLocaleString(),
                label: "chronology violations",
              },
            ].map((stat) => (
              <div key={stat.label}>
                <span
                  className="[font-family:var(--font-display)] text-[1.35rem] font-semibold"
                  style={{ color: "var(--theme-text)" }}
                >
                  {stat.value}
                </span>
                <span
                  className="ml-2 text-[0.78rem]"
                  style={{ color: "var(--theme-text-muted)" }}
                >
                  {stat.label}
                </span>
              </div>
            ))}
          </div>
          <p
            className="mt-3 text-[0.78rem] leading-[1.55]"
            style={{ color: "var(--theme-text-muted)" }}
          >
            Scores whose runs predate the witnessed custody chain: their
            recorded timestamps order them before their outcomes, but no
            independent timestamp proves it, so they sit one tier below the
            headline — published and flagged in{" "}
            <a href="/log.json">log.json</a>, never deleted. The headline
            starts at zero by construction and fills as custody-v2 runs
            resolve against official prints.
          </p>
        </section>

        <section className="mt-14">
          <h2
            className="[font-family:var(--font-display)] text-[1.3rem] font-semibold"
            style={{ color: "var(--theme-text)" }}
          >
            The calibration curve
          </h2>
          <p
            className="mt-2 max-w-[640px] text-[0.88rem] leading-[1.6]"
            style={{ color: "var(--theme-text-muted)" }}
          >
            Each score records the forecast distribution evaluated at the
            official print (its probability integral transform), so coverage
            is checkable at every stated interval, not just the elicited 80%.
            A calibrated forecaster tracks the diagonal: above it means
            intervals are too wide, below it too narrow. The PIT histograms
            show the same thing distributionally — a calibrated forecaster
            fills each bin equally; a U shape is overconfidence, a central
            hump underconfidence. The curve reads coverage off each
            forecast&apos;s materialized distribution, while the headline 80%
            stat counts stated interval endpoints directly, so the two can
            differ by a few scores.
          </p>
          <div
            className="mt-5 rounded-[14px] border p-6"
            style={{
              borderColor: "var(--theme-border)",
              backgroundColor: "var(--theme-card-bg)",
            }}
          >
            <CalibrationPlot
              witnessedPits={scores.map(
                (score) => score.probabilityIntegralTransform,
              )}
              claimedPits={allScores
                .filter(
                  (score) => score.chronology === "claimed_time_verified",
                )
                .map((score) => score.probabilityIntegralTransform)}
            />
          </div>
        </section>

        <section className="mt-14">
          <h2
            className="[font-family:var(--font-display)] text-[1.3rem] font-semibold"
            style={{ color: "var(--theme-text)" }}
          >
            Forecasters against the baseline
          </h2>
          <p
            className="mt-2 max-w-[640px] text-[0.88rem] leading-[1.6]"
            style={{ color: "var(--theme-text-muted)" }}
          >
            Per-target raw CRPS ratio against the paired ledger persistence
            baseline (geometric mean; below 1 beats persistence), lowest first.
            Unpaired means remain visible for context. The persistence baseline
            forecasts every target as its last official print with a
            realized-volatility interval — an agent earns its place by beating
            it. Forecaster rows score here only when witness-verified; the
            deterministic baseline is a replayable function of pre-cutoff
            ledger data and needs no witness of its own. Rows with few scored
            runs are noisy; read them accordingly.
          </p>
          <div
            className="mt-5 overflow-x-auto rounded-[14px] border"
            style={{ borderColor: "var(--theme-border)" }}
          >
            <table className="w-full border-collapse text-[0.84rem]">
              <thead>
                <tr
                  className="[font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em]"
                  style={{ color: "var(--theme-text-muted)" }}
                >
                  <th className="px-4 py-3 text-left font-normal">Forecaster</th>
                  <th className="px-4 py-3 text-right font-normal">
                    Scored / total runs
                  </th>
                  <th className="px-4 py-3 text-right font-normal">
                    Claimed-time scored
                  </th>
                  <th className="px-4 py-3 text-right font-normal">
                    CRPS ratio vs persistence
                  </th>
                  <th className="px-4 py-3 text-right font-normal">
                    Paired win rate
                  </th>
                  <th className="px-4 py-3 text-right font-normal">
                    Unpaired mean nCRPS
                  </th>
                  <th className="px-4 py-3 text-right font-normal">
                    80% coverage
                  </th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.map((row) => {
                  const isBaseline = row.agent.startsWith(
                    BASELINE_AGENT_PREFIX,
                  );
                  return (
                    <tr
                      key={`${row.agent}-${row.model ?? ""}`}
                      className="border-t"
                      style={{
                        borderColor: "var(--theme-border)",
                        backgroundColor: isBaseline
                          ? "var(--theme-card-bg)"
                          : undefined,
                      }}
                    >
                      <td
                        className="px-4 py-3"
                        style={{ color: "var(--theme-text)" }}
                      >
                        {row.agent}
                        {row.model ? (
                          <span
                            className="ml-2 text-[0.72rem]"
                            style={{ color: "var(--theme-text-muted)" }}
                          >
                            {row.model}
                          </span>
                        ) : null}
                        {isBaseline ? (
                          <span
                            className="ml-2 rounded-full border px-2 py-[1px] [font-family:var(--font-mono)] text-[0.56rem] uppercase tracking-[0.1em]"
                            style={{
                              borderColor: "var(--theme-border)",
                              color: "var(--theme-text-muted)",
                            }}
                          >
                            baseline
                          </span>
                        ) : null}
                        {row.external ? (
                          <span
                            className="ml-2 rounded-full border border-[#A94E80] px-2 py-[1px] [font-family:var(--font-mono)] text-[0.56rem] uppercase tracking-[0.1em] text-[#A94E80]"
                            title="Open-challenge submission scored through the identical pipeline; the submission record is published, a reasoning trace is not required."
                          >
                            external
                            {row.externalSystemTypes?.length
                              ? ` · ${row.externalSystemTypes.join("/")}`
                              : ""}
                          </span>
                        ) : null}
                      </td>
                      <td
                        className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                        style={{ color: "var(--theme-text-muted)" }}
                      >
                        {row.scoredRuns} / {row.totalRuns}
                      </td>
                      <td
                        className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                        style={{ color: "var(--theme-text-muted)" }}
                      >
                        {claimedByAgent.get(
                          `${row.agent}\u0000${row.model ?? ""}`,
                        ) ?? 0}
                      </td>
                      <td
                        className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                        style={{ color: "var(--theme-text)" }}
                      >
                        {row.pairedCrpsRatioGeomean === null
                          ? "—"
                          : row.pairedCrpsRatioGeomean.toFixed(2)}
                      </td>
                      <td
                        className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                        style={{ color: "var(--theme-text-muted)" }}
                      >
                        {formatCoverage(row.pairedWinRate)}
                      </td>
                      <td
                        className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                        style={{ color: "var(--theme-text)" }}
                      >
                        {formatCrps(row.unpairedMeanNormalizedCrps)}
                      </td>
                      <td
                        className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                        style={{ color: "var(--theme-text-muted)" }}
                      >
                        {formatCoverage(row.unpairedInterval80Coverage)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="mt-14">
          <h2
            className="[font-family:var(--font-display)] text-[1.3rem] font-semibold"
            style={{ color: "var(--theme-text)" }}
          >
            Evaluation splits
          </h2>
          <p
            className="mt-2 max-w-[640px] text-[0.88rem] leading-[1.6]"
            style={{ color: "var(--theme-text-muted)" }}
          >
            {rewardExport.noLeakagePolicy.rule}
          </p>
          <div className="mt-5 grid grid-cols-4 gap-4 max-md:grid-cols-2">
            {(
              Object.entries(splits) as [
                keyof typeof splits,
                (typeof splits)[keyof typeof splits],
              ][]
            ).map(([name, split]) => (
              <div
                key={name}
                className="rounded-[14px] border p-5"
                style={{
                  borderColor: "var(--theme-border)",
                  backgroundColor: "var(--theme-card-bg)",
                }}
              >
                <div
                  className="[font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.12em]"
                  style={{ color: "var(--theme-text-muted)" }}
                >
                  {name}
                </div>
                <div
                  className="mt-2 [font-family:var(--font-display)] text-[1.35rem] font-semibold"
                  style={{ color: "var(--theme-text)" }}
                >
                  {split.scoredRuns}
                  <span
                    className="text-[0.85rem] font-normal"
                    style={{ color: "var(--theme-text-muted)" }}
                  >
                    {" "}
                    / {split.runs}
                  </span>
                </div>
                <div
                  className="mt-1 text-[0.72rem] leading-[1.5]"
                  style={{ color: "var(--theme-text-muted)" }}
                >
                  {split.rule}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-14">
          <h2
            className="[font-family:var(--font-display)] text-[1.3rem] font-semibold"
            style={{ color: "var(--theme-text)" }}
          >
            Latest resolutions
          </h2>
          <p
            className="mt-2 max-w-[640px] text-[0.88rem] leading-[1.6]"
            style={{ color: "var(--theme-text-muted)" }}
          >
            Both published chronology tiers appear here. Only rows marked
            witnessed — custody root externally witnessed before the
            observation — count toward the headline numbers above; claimed
            rows rest on recorded timestamps alone.
          </p>
          <div
            className="mt-5 overflow-x-auto rounded-[14px] border"
            style={{ borderColor: "var(--theme-border)" }}
          >
            <table className="w-full border-collapse text-[0.84rem]">
              <thead>
                <tr
                  className="[font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em]"
                  style={{ color: "var(--theme-text-muted)" }}
                >
                  <th className="px-4 py-3 text-left font-normal">Forecast</th>
                  <th className="px-4 py-3 text-right font-normal">
                    Predicted
                  </th>
                  <th className="px-4 py-3 text-right font-normal">Observed</th>
                  <th className="px-4 py-3 text-right font-normal">
                    In interval
                  </th>
                  <th className="px-4 py-3 text-right font-normal">
                    Elicitation
                  </th>
                  <th className="px-4 py-3 text-right font-normal">
                    Chronology
                  </th>
                  <th className="px-4 py-3 text-right font-normal">Score</th>
                </tr>
              </thead>
              <tbody>
                {recentScores.map((score) => {
                  const cell = cellBySlug.get(score.forecastSlug);
                  return (
                    <tr
                      key={score.scoreId}
                      className="border-t"
                      style={{ borderColor: "var(--theme-border)" }}
                    >
                      <td className="px-4 py-3">
                        <Link
                          href={`/${score.forecastSlug}`}
                          style={{ color: "var(--theme-text)" }}
                        >
                          {cell?.title ?? score.forecastSlug}
                        </Link>
                      </td>
                      <td
                        className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                        style={{ color: "var(--theme-text-muted)" }}
                      >
                        {cell
                          ? formatValue(score.pointEstimate, cell.unit)
                          : score.pointEstimate}
                      </td>
                      <td
                        className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                        style={{ color: "var(--theme-text)" }}
                      >
                        {cell
                          ? formatValue(score.observedValue, cell.unit)
                          : score.observedValue}
                      </td>
                      <td
                        className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                        style={{
                          color: score.interval80Covered
                            ? "var(--theme-text-muted)"
                            : "#A94E80",
                        }}
                      >
                        {score.interval80Covered ? "yes" : "no"}
                      </td>
                      <td
                        className="px-4 py-3 text-right [font-family:var(--font-mono)] text-[0.68rem] uppercase"
                        style={{ color: "var(--theme-text-muted)" }}
                      >
                        {score.distributionProvenance.replace("_", " ")}
                      </td>
                      <td
                        className="px-4 py-3 text-right [font-family:var(--font-mono)] text-[0.68rem] uppercase"
                        style={{
                          color:
                            score.chronology === "witness_verified"
                              ? "var(--theme-text)"
                              : "var(--theme-text-muted)",
                        }}
                      >
                        {score.chronology === "witness_verified"
                          ? "witnessed"
                          : "claimed"}
                      </td>
                      <td
                        className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                        style={{ color: "var(--theme-text)" }}
                      >
                        {isNormalizedScoreAggregateEligible(score)
                          ? `nCRPS ${formatCrps(score.normalizedCrps)}`
                          : `raw CRPS ${formatCrps(score.crps)}`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p
            className="mt-4 text-[0.82rem]"
            style={{ color: "var(--theme-text-muted)" }}
          >
            Full history: <Link href="/log">the Thesis Log</Link> · method:{" "}
            <Link href="/thesis">why forecasting is the harness</Link>
          </p>
        </section>
      </main>
    </div>
  );
}
